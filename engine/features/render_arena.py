"""Allocate and initialize the extra memory used by enlarged native views.

The renderer supplies code and tables; the caller supplies image bytes and
Windows imports. Addresses remain fixed for exact snapshots. Startup returns to
the original window initializer after setting up buffers, caches and guard bytes.
"""
import struct
from patch_support import asm

W, H = 1280, 960
CAP = 1600 * 1200
CODE = 0x1f97500
END = 0x1f9ff00
SITE = 0x1d19a00
BASE = 0x68000000
SIZE = 0x2000000
MARKER = BASE + 0xb0007c
MAGIC = 0x39305254
GUARD_BYTES = 256


class Layout:
    """Describe renderer addresses and capacities shared with snapshot restore."""

    def __init__(self, base):
        self.base = base
        self.pixels = base + 0x100000
        self.reflection = base + 0x300000
        self.frame = base + 0x500000
        self.screen = base + 0x700000
        self.map = base + 0x900000
        self.state = base + 0xb00000
        self.cols = base + 0xb01000
        self.rows = base + 0xb02000
        self.yedges = base + 0xb04000
        self.clip = base + 0xb05000
        self.clip2 = base + 0xb07000
        self.effect = base + 0xb09000
        self.skyrows = [base + 0xb0b000 + i * 0x2000 for i in range(6)]
        # Mission palette reloads regenerate object fog; snapshots retain the
        # composed tables. Terrain shading history itself belongs to each view's
        # temporary clip allocation; only its current ring bookkeeping lives here.
        self.object_fog = base + 0xb20100
        self.terrain_shading = base + 0xb39000
        # The original game owns four map contexts. Each needs independent
        # terrain pixels and logical coverage while its widget remains visible.
        self.map_slots = base + 0x1e00100
        self.map_pixels = tuple(base + 0x1000000 + i * 0x200000 for i in range(4))
        self.map_refs = tuple(base + 0x1800100 + i * 0x50000 for i in range(4))
        self.map_masks = tuple(a + 0x20200 for a in self.map_refs)
        self.regions = [
            (name, a, CAP) for name, a in [
                ('world',
                 self.pixels), ('reflection',
                                self.reflection), ('frame',
                                                   self.frame), ('screen',
                                                                 self.screen), ('map', self.map)
            ]
        ]
        self.regions += [
            ('clip', self.clip, 1600 * 4), ('clip2', self.clip2, 1600 * 4),
            ('effect', self.effect, 1200 * 4)
        ]
        self.regions += [('sky' + str(i), a, 1200 * 4) for i, a in enumerate(self.skyrows)]
        self.regions += [('object-fog-palettes', self.object_fog, 15 * 0x1800),
                         ('terrain-shading-state', self.terrain_shading, 16)]
        self.regions += [('map-cache-records', self.map_slots, 4 * 512)]
        for i in range(4):
            self.regions += [('map-pixels-' + str(i), self.map_pixels[i], CAP),
                             ('map-ref-' + str(i), self.map_refs[i], 128000),
                             ('map-mask-' + str(i), self.map_masks[i], 128000)]

    def guard_edges(self):
        return tuple(edge for _, a, n in self.regions for edge in (a - GUARD_BYTES, a + n))


def validate(i, imports):
    """Reject plans that could copy outside the arena or overwrite its guards."""
    expected = Layout(BASE)
    for name, value in vars(expected).items():
        if getattr(i, name, None) != value:
            raise ValueError('Renderer snapshot ABI differs: ' + name)
    for name in ('VirtualAlloc', 'LoadLibraryA', 'GetProcAddress'):
        slot = imports.get(name)
        if not isinstance(slot, int) or not 0 < slot <= 0x2000000 - 4:
            raise ValueError('Invalid render import slot: ' + name)
    spans = []
    for name, a, n in i.regions:
        span = (a - GUARD_BYTES, a + n + GUARD_BYTES)
        if not BASE <= span[0] < span[1] <= BASE + SIZE:
            raise ValueError('Render region outside arena: ' + name)
        spans.append(span)
    if any(a[1] > b[0] for a, b in zip(sorted(spans), sorted(spans)[1:])):
        raise ValueError('Overlapping guarded render regions')
    external = []
    for a, b in i.writes:
        if a < BASE:
            if not 0x11000 <= a < a + len(b) <= 0x2000000:
                raise ValueError('Internal renderer write outside image')
            continue
        end = a + len(b)
        if not BASE <= a < end <= BASE + SIZE:
            raise ValueError('External renderer write outside arena')
        if any(a < g + GUARD_BYTES and g < end for g in expected.guard_edges()):
            raise ValueError('External renderer write overlaps guard')
        if a < expected.state + 128 and expected.state < end:
            raise ValueError('External payload overwrites runtime state')
        external.append((a, end))
    ordered = sorted(external)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Overlapping external renderer payloads')


def bodies(i, read, imports):
    """Emit renderer startup from an explicit plan and image reader.

    The caller checks hook bytes and empty storage before installing the result.
    """
    validate(i, imports)
    internal = [(a, b) for a, b in i.writes if a < BASE]
    external = [(a, b) for a, b in i.writes if a >= BASE]
    cursor = CODE + 0xc00
    payload = bytearray()
    records = []
    for a, b in external:
        records.append((a, cursor + len(payload), len(b)))
        payload.extend(b)
    table = cursor + len(payload)
    for a, src, n in records:
        payload.extend(struct.pack('<3I', a, src, n))
    payload.extend(bytes(12))
    strings = {}
    for name in ('user32.dll', 'GetDpiForWindow', 'AdjustWindowRectExForDpi', 'SetWindowPos'):
        strings[name] = cursor + len(payload)
        payload.extend(name.encode() + b'\0')
    original = CODE + 0x900
    displaced = read(SITE, 5)
    if len(displaced) != 5 or displaced[0] != 0x68:
        raise ValueError('Render startup requires a complete PUSH imm32 preimage')
    trampoline = displaced + asm(original + 5, f'jmp {SITE+5}')

    def api(n):
        return f'call dword ptr [{imports[n]}];'

    s = (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"\n     push 0x40;"
        f"push 0x3000;"
        f"push {SIZE};"
        f"push {BASE};"
        f"{api('VirtualAlloc')}cmp eax,{BASE};"
        f"jne failed;"
        f"\n     mov ebp,{table};"
        f"\n     copy:mov edi,[ebp];"
        f"test edi,edi;"
        f"jz guards;"
        f"mov esi,[ebp+4];"
        f"mov ecx,[ebp+8];"
        f"rep movsb;"
        f"add ebp,12;"
        f"jmp copy;"
        f"\n     guards:"
    )
    for name, a, n in i.regions:
        for edge in (a - 256, a + n):
            s += (f"mov edi,{edge};"
                  f"mov eax,0xa5a5a5a5;"
                  f"mov ecx,64;"
                  f"rep stosd;")
    # Do not trust persisted partial frames or viewport cache identity after
    # cold start or checkpoint upgrade. The next real frame re-establishes it.
    s += (
        f"mov dword ptr [{i.terrain_shading+8}],0xfffff000;"
          f"mov dword ptr [{i.terrain_shading+12}],1;"
        f"mov edi,{i.map_slots};xor eax,eax;mov ecx,512;rep stosd;"
        f"mov dword ptr [{i.state}],1;"
        f"mov dword ptr [{i.state+24}],0;"
        f"\n     mov dword ptr [0x9aa0ec],0;"
        f"mov dword ptr [0x9af5e8],0;"
        f"\n     mov dword ptr [0x1e3c580],0;"
        f"mov edi,0x1e46140;"
        f"xor eax,eax;"
        f"mov ecx,10;"
        f"rep stosd;"
        f"\n     mov dword ptr [{MARKER}],{MAGIC};"
        f"call {CODE+0xa00};"
        f"popad;"
        f"popfd;"
        f"call {original};"
        f"pushfd;"
        f"pushad;"
        f"\n     push {strings['user32.dll']};"
        f"{api('LoadLibraryA')}test eax,eax;"
        f"jz resized;"
        f"mov ebp,eax;"
        f"\n     push {strings['GetDpiForWindow']};"
        f"push ebp;"
        f"{api('GetProcAddress')}test eax,eax;"
        f"jz resized;"
        f"\n     push dword ptr [0x1d1d000];"
        f"call eax;"
        f"mov ebx,eax;"
        f"\n     push {strings['AdjustWindowRectExForDpi']};"
        f"push ebp;"
        f"{api('GetProcAddress')}test eax,eax;"
        f"jz resized;"
        f"\n     mov esi,{i.state+64};"
        f"mov dword ptr [esi],0;"
        f"mov dword ptr [esi+4],0;"
        f"mov dword ptr [esi+8],{W};"
        f"mov dword ptr [esi+12],{H};"
        f"\n     push ebx;"
        f"push 0;"
        f"push 0;"
        f"push 0x10cf0000;"
        f"push esi;"
        f"call eax;"
        f"test eax,eax;"
        f"jz resized;"
        f"\n     push {strings['SetWindowPos']};"
        f"push ebp;"
        f"{api('GetProcAddress')}test eax,eax;"
        f"jz resized;"
        f"\n     mov ebx,[esi+8];"
        f"sub ebx,[esi];"
        f"mov ecx,[esi+12];"
        f"sub ecx,[esi+4];"
        f"\n     push 0x14;"
        f"push ecx;"
        f"push ebx;"
        f"push 15;"
        f"push 15;"
        f"push 0;"
        f"push dword ptr [0x1d1d000];"
        f"call eax;"
        f"\n     resized:popad;"
        f"popfd;"
        f"ret;"
        f"\n     failed:mov eax,0xff00;"
        f"int 0x21;"
    )
    b = asm(CODE, s.replace('rep stosd;', '.byte 0xf3,0xab;'))
    assert len(b) < 0x900
    # An older checkpoint contains only the old display image. Show that frozen
    # image at the new window size until the first real 1280-pixel game frame.
    # New checkpoints replace it with their captured native frame after INIT.
    preview = asm(
        CODE + 0xa00, (
            f"cmp dword ptr [0x1d0b000],0x103;"
            f"jne done;"
            f"\n     cmp dword ptr [0x1d0b004],0xe0000000;"
            f"jne done;"
            f"cmp dword ptr [0x446f80],0x01900140;"
            f"jne done;"
            f"\n     xor ebp,ebp;"
            f"mov edi,{i.frame};"
            f"\n     row:lea eax,[ebp+ebp*4];"
            f"shr eax,3;"
            f"imul esi,eax,800;"
            f"add esi,0xe0000000;"
            f"xor ecx,ecx;"
            f"\n     pixel:lea eax,[ecx+ecx*4];"
            f"shr eax,3;"
            f"mov dl,[esi+eax];"
            f"mov [edi],dl;"
            f"mov [edi+{i.screen-i.frame}],dl;"
            f"\n     inc edi;"
            f"inc ecx;"
            f"cmp ecx,{W};"
            f"jb pixel;"
            f"inc ebp;"
            f"cmp ebp,{H};"
            f"jb row;"
            f"\n     mov dword ptr [{i.state+24}],1;"
            f"done:ret;"
        )
    )
    assert len(preview) < 0x200
    assert cursor + len(payload) <= END, (len(payload), hex(cursor + len(payload)))
    return internal + [
        (CODE, b), (original, trampoline), (CODE + 0xa00, preview), (cursor, bytes(payload)),
        (SITE, asm(SITE, f'jmp {CODE}'))
    ]
