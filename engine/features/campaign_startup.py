"""Prepare campaign menus, resource paths and demo callbacks at game startup.

The caller supplies Windows imports and verified demo/retail code explicitly.
Startup prepares the campaign state; campaign_switch connects it to same-window
switching after the script interpreter has finished the current callback.
"""
from dataclasses import dataclass
from types import MappingProxyType
import struct
from patch_support import asm

BOOT = 0x1e4e100
OPEN = BOOT + 0x600
DRAW = 0x1e5f000
SWITCH = 0x1efdc00
DATA = 0x1fc0100
RF = DATA
DF = DATA + 0x300
STATE = DATA + 0x600
TEXT = 0x1fc1300
RANGES = (
    (BOOT, 0x1e4f000), (DRAW, 0x1e5ff00), (SWITCH, 0x1eff000), (DATA, 0x1fc1000), (TEXT, 0x1fc2000)
)
ENTRY = 0x1d00018
VARS = 0x1ef6800
FUNCS = VARS + 0x100
STUB = VARS + 0x600
TAG = TEXT + 0xcf0
MAGIC = b'CAMPAIGN120\0'


@dataclass(frozen=True)
class Context:
    imports: object
    retail_functions: tuple
    demo_functions: tuple
    open_site: int

    def __post_init__(self):
        required = (
            'CreateFileA', 'GetModuleHandleA', 'GetProcAddress', 'CloseHandle', 'ExitProcess'
        )
        if (
            any(
                not isinstance(self.imports.get(k), int)
                or not 0x11000 <= self.imports[k] < 0x2000000 - 4 for k in required
            )
        ):
            raise ValueError('Missing or invalid campaign import provider')
        if len(self.retail_functions) != 164 or len(self.demo_functions) != 138:
            raise ValueError('Wrong campaign function-table size')
        if (
            any(
                not isinstance(v, int) or not 0 <= v < 0x2000000
                for v in (*self.retail_functions, *self.demo_functions)
            )
        ):
            raise ValueError('Invalid campaign function binding')
        if not 0x1d00805 <= self.open_site < 0x1d03000 - 6:
            raise ValueError('Invalid campaign open hook')
        object.__setattr__(self, 'imports', MappingProxyType(dict(self.imports)))
        object.__setattr__(self, 'retail_functions', tuple(self.retail_functions))
        object.__setattr__(self, 'demo_functions', tuple(self.demo_functions))


def bind(read, imports, demo_functions):
    window = bytes(read(0x1d00800, 0x2800))
    if len(window) != 0x2800:
        raise ValueError('Short campaign provider window')
    needle = asm(0, 'push 0x1d08000;') + b'\xff\x15' + struct.pack('<I', imports['CreateFileA'])
    hits = [n for n in range(len(window) - len(needle) + 1) if window.startswith(needle, n)]
    if len(hits) != 1:
        raise ValueError('Expected one original campaign open provider')
    raw = bytes(read(0x35dccc, 164 * 4))
    if len(raw) != 164 * 4:
        raise ValueError('Short retail function table')
    return Context(
        imports, struct.unpack('<164I', raw), tuple(demo_functions), 0x1d00800 + hits[0] + 5
    )


def text_data(*, profile, home, demo_root, shared_root):
    if profile not in (116, 118, 119):
        raise ValueError('Unknown campaign profile')
    HOME, DEMO_ROOT, SHARED_ROOT = home, demo_root, shared_root
    labels = {}
    raw = bytearray()
    if profile == 116:
        texts = [
            ('dll', 'kernel32.dll'), ('cmd', 'GetCommandLineA'), ('create', 'CreateProcessA'),
            ('demo_root', str(DEMO_ROOT) + '\\'), ('retail_menu', str(HOME / 'menu-retail.res')),
            ('demo_menu', str(HOME / 'menu-demo.res')), ('exe', str(HOME / 'native-startup.exe')),
            ('run', f'"{HOME / "native-startup.exe"}"'),
            ('run_demo', f'"{HOME / "native-startup.exe"}" --demo'), ('title', 'TERRA NOVA'),
            ('subtitle', 'STRIKE FORCE CENTAURI'), ('retail', 'SFC CAMPAIGN'),
            ('demo', 'DEMO PREQUEL'), ('quit', 'QUIT'),
            ('hint', 'Arrow keys / Enter or click to choose'),
            ('detail', 'Four original demo missions. Separate saves and fixed equipment.'),
            ('error', 'Unable to start the selected campaign. Please try again.')
        ]
    elif profile == 118:
        texts = [
            ('dll', 'kernel32.dll'), ('cmd', 'GetCommandLineA'), ('create', 'CreateProcessA'),
            ('demo_root', str(DEMO_ROOT) + '\\'), ('retail_menu', str(HOME / 'menu-retail.res')),
            ('demo_menu', str(HOME / 'menu-demo.res')), ('exe', str(HOME / 'native-startup.exe')),
            ('run', f'"{HOME / "native-startup.exe"}"'),
            ('run_demo', f'"{HOME / "native-startup.exe"}" --demo'), ('prequel', 'Prequel'),
            ('title', 'TERRA NOVA'), ('subtitle', 'STRIKE FORCE CENTAURI'),
            ('retail', 'SFC CAMPAIGN'), ('demo', 'DEMO PREQUEL'), ('quit', 'QUIT'),
            ('hint', 'Arrow keys / Enter or click to choose'),
            ('detail', 'Four original demo missions. Separate saves and fixed equipment.'),
            ('error', 'Unable to start the selected campaign. Please try again.')
        ]
    else:
        texts = [
            ('dll', 'kernel32.dll'), ('cmd', 'GetCommandLineA'), ('create', 'CreateProcessA'),
            ('demo_root', str(DEMO_ROOT) + '\\'), ('retail_menu', str(HOME / 'menu-retail.res')),
            ('demo_menu', str(HOME / 'menu-demo.res')), ('exe', str(HOME / 'native-startup.exe')),
            ('run', f'"{HOME / "native-startup.exe"}"'),
            ('run_demo', f'"{HOME / "native-startup.exe"}" --demo'), ('prequel', 'Prequel'),
            ('retail_art', str(HOME / 'menu-retail-art.res')),
            ('demo_art', str(HOME / 'menu-demo-art.res')), ('config', str(SHARED_ROOT / 'TN.CFG'))
        ]

    for k, v in texts:
        labels[k] = TEXT + len(raw)
        raw += v.encode('ascii') + b'\0'
    assert len(raw) <= 0xd00, len(raw)
    return labels, bytes(raw)


def restart_code(imports, labels):
    return asm(
        SWITCH, (
            f"cmp eax,1;"
            f"je nothing;"
            f"cmp eax,3;"
            f"je quit;"
            f"\n pushfd;"
            f"pushad;"
            f"mov ebp,eax;"
            f"cld;"
            f"mov edi,{STATE+0x40};"
            f"xor eax,eax;"
            f"mov ecx,36;"
            f"rep stosd;"
            f"\n push {labels['dll']};"
            f"call dword ptr [{imports['GetModuleHandleA']}];"
            f"\n push {labels['create']};"
            f"push eax;"
            f"call dword ptr [{imports['GetProcAddress']}];"
            f"test eax,eax;"
            f"jz fail;"
            f"mov ebx,eax;"
            f"\n mov esi,{labels['run']};"
            f"cmp ebp,2;"
            f"jne copy;"
            f"mov esi,{labels['run_demo']};"
            f"\n copy:mov edi,{STATE+0x100};"
            f"mov ecx,511;"
            f"cmd:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jz start;"
            f"loop cmd;"
            f"jmp fail;"
            f"\n start:mov dword ptr [{STATE+0x80}],68;"
            f"\n push {STATE+0x40};"
            f"push {STATE+0x80};"
            f"push 0;"
            f"push 0;"
            f"push 0x08000000;"
            f"push 0;"
            f"push 0;"
            f"push 0;"
            f"push {STATE+0x100};"
            f"push {labels['exe']};"
            f"call ebx;"
            f"\n test eax,eax;"
            f"jz fail;"
            f"push dword ptr [{STATE+0x40}];"
            f"call dword ptr [{imports['CloseHandle']}];"
            f"push dword ptr [{STATE+0x44}];"
            f"call dword ptr [{imports['CloseHandle']}];"
            f"\n popad;"
            f"popfd;"
            f"jmp quit;"
            f"\n fail:mov dword ptr [{STATE+8}],1;"
            f"popad;"
            f"popfd;"
            f"\n nothing:ret;"
            f"\n quit:push 0;"
            f"call dword ptr [{imports['ExitProcess']}];"
            f"ret;"
        )
    )


def bodies(context, *, profile, home, demo_root, shared_root):
    labels, raw = text_data(
        profile=profile, home=home, demo_root=demo_root, shared_root=shared_root
    )
    out = []
    out.append((TEXT, bytes(raw)))

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    # These tables retain every original binding and append two menu functions.
    rf = context.retail_functions
    df = context.demo_functions
    out.extend(
        [
            (RF, struct.pack('<166I', *rf, DRAW, SWITCH)),
            (DF, struct.pack('<166I', *df, *([0] * 26), DRAW, SWITCH))
        ]
    )
    # The startup call precedes audio/resource initialization. Restores skip it.
    emit(
        BOOT, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"\n push {labels['dll']};"
            f"call dword ptr [{context.imports['GetModuleHandleA']}];"
            f"mov ebx,eax;"
            f"\n push {labels['cmd']};"
            f"push ebx;"
            f"call dword ptr [{context.imports['GetProcAddress']}];"
            f"test eax,eax;"
            f"jz retail;"
            f"call eax;"
            f"mov esi,eax;"
            f"mov ecx,32768;"
            f"\n scan:cmp byte ptr [esi],0;"
            f"je retail;"
            f"cmp byte ptr [esi],32;"
            f"jne next;"
            f"\n cmp dword ptr [esi+1],0x65642d2d;"
            f"jne next;"
            f"cmp word ptr [esi+5],0x6f6d;"
            f"jne next;"
            f"\n cmp byte ptr [esi+7],0;"
            f"je demo;"
            f"cmp byte ptr [esi+7],32;"
            f"je demo;"
            f"\n next:inc esi;"
            f"loop scan;"
            f"jmp retail;"
            f"\n demo:mov dword ptr [{STATE}],1;"
            f"\n mov dword ptr [0x2448c7],{VARS};"
            f"mov dword ptr [0x2448cc],{DF};"
            f"mov dword ptr [0x244938],0x3eb0003;"
            f"\n mov byte ptr [0x2c6f83],0xe9;"
            f"mov dword ptr [0x2c6f84],{STUB-(0x2c6f83+5)};"
            f"\n mov esi,{labels['demo_root']};"
            f"mov edi,0x1d08400;"
            f"mov ecx,255;"
            f"copy:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jz ready;"
            f"loop copy;"
            f"jmp ready;"
            f"\n retail:mov dword ptr [{STATE}],0;"
            f"mov dword ptr [0x2448cc],{RF};"
            f"\n ready:popad;"
            f"popfd;"
            f"call 0x1d27000;"
            f"ret;"
        ), 0x600
    )
    # stdcall tail wrapper: replace only the filename stack argument when its
    # generated DOS-open path has this exact basename. All access flags survive.
    if profile < 119:
        emit(
            OPEN, (
                f"pushfd;"
                f"pushad;"
                f"cmp dword ptr [esp+44],0x80000000;"
                f"jne done;"
                f"cmp dword ptr [esp+56],3;"
                f"jne done;"
                f"\n mov esi,[esp+40];"
                f"test esi,esi;"
                f"jz done;"
                f"mov edi,esi;"
                f"mov ecx,260;"
                f"\n scan:cmp byte ptr [edi],0;"
                f"je end;"
                f"inc edi;"
                f"loop scan;"
                f"jmp done;"
                f"\n end:mov eax,edi;"
                f"sub eax,esi;"
                f"cmp eax,13;"
                f"jb done;"
                f"sub edi,13;"
                f"\n cmp dword ptr [edi],0x5345525c;"
                f"jne done;"
                f"cmp dword ptr [edi+4],0x4c424142;"
                f"jne done;"
                f"\n cmp dword ptr [edi+8],0x45522e32;"
                f"jne done;"
                f"cmp byte ptr [edi+12],0x53;"
                f"jne done;"
                f"\n mov eax,{labels['retail_menu']};"
                f"cmp dword ptr [0x2448c7],{VARS};"
                f"jne chosen;"
                f"mov eax,{labels['demo_menu']};"
                f"\n chosen:mov [esp+40],eax;"
                f"\n done:popad;"
                f"popfd;"
                f"jmp dword ptr [{context.imports['CreateFileA']}];"
            ), 0x500
        )
    else:
        emit(
            OPEN, (
                f"pushfd;"
                f"pushad;"
                f"\n mov esi,[esp+40];"
                f"test esi,esi;"
                f"jz done;"
                f"mov edi,esi;"
                f"mov ecx,260;"
                f"\n scan:cmp byte ptr [edi],0;"
                f"je end;"
                f"inc edi;"
                f"loop scan;"
                f"jmp done;"
                f"\n end:mov ecx,edi;"
                f"sub ecx,esi;"
                f"cmp ecx,7;"
                f"jb done;"
                f"\n cmp dword ptr [esp+44],0x80000000;"
                f"jne done;"
                f"cmp dword ptr [esp+56],3;"
                f"jne done;"
                f"\n cmp ecx,13;"
                f"jb done;"
                f"sub edi,13;"
                f"cmp dword ptr [edi],0x5345525c;"
                f"jne art;"
                f"\n cmp dword ptr [edi+4],0x4c424142;"
                f"jne art;"
                f"\n cmp dword ptr [edi+8],0x45522e32;"
                f"jne done;"
                f"cmp word ptr [edi+12],0x53;"
                f"jne done;"
                f"\n mov eax,{labels['retail_menu']};"
                f"cmp dword ptr [0x2448c7],{VARS};"
                f"jne chosen;"
                f"mov eax,{labels['demo_menu']};"
                f"jmp chosen;"
                f"\n art:inc edi;"
                f"cmp dword ptr [edi],0x5345525c;"
                f"jne done;"
                f"cmp dword ptr [edi+8],0x5345522e;"
                f"jne done;"
                f"cmp byte ptr [edi+12],0;"
                f"jne done;"
                f"\n cmp dword ptr [0x2448c7],{VARS};"
                f"je demo_art;"
                f"\n cmp dword ptr [edi+4],0x45534142;"
                f"jne done;"
                f"mov eax,{labels['retail_art']};"
                f"jmp chosen;"
                f"\n demo_art:cmp dword ptr [edi+4],0x454d4147;"
                f"jne done;"
                f"mov eax,{labels['demo_art']};"
                f"\n chosen:mov [esp+40],eax;"
                f"\n done:popad;"
                f"popfd;"
                f"jmp dword ptr [{context.imports['CreateFileA']}];"
            ), 0x500
        )
    if profile == 116:
        # Original graphics API and fonts, on the ordinary 640x480 menu canvas.
        draw = (
            f"pushfd;"
            f"pushad;"
            f"mov [{STATE+4}],eax;"
            f"call 0x2e4b1c;"
            f"\n  push dword ptr [0x44b1a0];"
            f"cld;"
            f"mov esi,[0x44b1a0];"
            f"mov edi,{STATE+0x300};"
            f"mov ecx,15;"
            f".byte 0xf3,0xa5;"
            f"\n  mov esi,0x446f78;"
            f"mov edi,{STATE+0x300};"
            f"mov ecx,4;"
            f".byte 0xf3,0xa5;"
            f"\n  mov dword ptr [{STATE+0x32c}],0;"
            f"mov dword ptr [{STATE+0x330}],0;"
            f"\n  mov dword ptr [{STATE+0x334}],0x2800000;"
            f"mov dword ptr [{STATE+0x338}],0x1e00000;"
            f"\n  mov eax,{STATE+0x300};"
            f"call 0x2eab30;"
            f"\n  mov esi,[0x44b1a0];"
            f"mov edi,[0x44b194];"
            f"push dword ptr [esi+0x10];"
            f"push dword ptr [esi+0x18];"
            f"\n  mov dword ptr [esi+0x10],0;"
            f"xor eax,eax;"
            f"xor edx,edx;"
            f"mov ebx,640;"
            f"mov ecx,480;"
            f"call dword ptr [edi+0x40];"
            f"\n  mov eax,0x167;"
            f"call 0x2eb380;"
            f"mov [esi+0x18],eax;"
            f"mov dword ptr [esi+0x10],0xf7;"
        )

        def text(label, x, y):
            return (
                f"mov eax,[esi+0x18];"
                f"mov edx,{labels[label]};"
                f"mov ebx,{x};"
                f"mov ecx,{y};"
                f"call dword ptr [edi+0x4ec];"
            )

        draw += text('title', 230, 70) + text('subtitle', 165, 105)
        for idx, (label, y) in enumerate([('retail', 190), ('demo', 245), ('quit', 300)], 1):
            draw += (
                f"mov dword ptr [esi+0x10],0x9f;"
                f"cmp dword ptr [{STATE+4}],{idx};"
                f"jne border{idx};"
                f"mov dword ptr [esi+0x10],0xf7;"
                f"\n  border{idx}:mov eax,150;"
                f"mov edx,{y};"
                f"mov ebx,490;"
                f"mov ecx,{y+42};"
                f"call dword ptr [edi+0x48];"
            )
            draw += text(label, 190, y + 11)
        draw += (
            "mov eax,0x167;"
            "call 0x2eb3f4;"
            "mov eax,0x164;"
            "call 0x2eb380;"
            "mov [esi+0x18],eax;"
            "mov dword ptr [esi+0x10],0xf7;"
        )
        draw += text('hint', 158, 375) + text('detail', 62, 402)
        draw += f'cmp dword ptr [{STATE+8}],0;je no_error;' + text('error', 72, 435) + 'no_error:'
        draw += (
            "mov eax,0x164;"
            "call 0x2eb3f4;"
            "pop dword ptr [esi+0x18];"
            "pop dword ptr [esi+0x10];"
            "pop eax;"
            "call 0x2eab30;"
            "mov eax,0x446fb8;"
            "call 0x2e43d0;"
            "call 0x2e4b78;"
            "popad;"
            "popfd;"
            "ret;"
        )
        emit(DRAW, draw, 0xf00)
    else:
        # Draw the additional retail button in the same font and beveled style.
        draw = (
            f"pushfd;"
            f"pushad;"
            f"mov [{STATE+4}],eax;"
            f"\n  mov esi,[0x44b1a0];"
            f"cmp dword ptr [esi+8],0x01e00280;"
            f"jne draw_done;"
            f"cmp word ptr [esi+12],640;"
            f"jne draw_done;"
            f"mov [{STATE+12}],esi;"
            f"mov edi,[0x44b194];"
            f"push dword ptr [esi+0x10];"
            f"push dword ptr [esi+0x18];"
            f"\n  push esi;"
            f"push edi;"
            f"cld;"
            f"mov esi,[esi];"
            f"lea edi,[esi+440*640+81];"
            f"add esi,412*640+81;"
            f"mov ebx,24;"
            f"\n  row:mov ecx,210;"
            f".byte 0xf3,0xa4;"
            f"add esi,430;"
            f"add edi,430;"
            f"dec ebx;"
            f"jnz row;"
            f"\n  mov edi,[{STATE+12}];"
            f"mov edi,[edi];"
            f"add edi,445*640+94;"
            f"mov ebx,14;"
            f"xor eax,eax;"
            f"\n  blank:mov ecx,184;"
            f"rep stosb;"
            f"add edi,456;"
            f"dec ebx;"
            f"jnz blank;"
            f"pop edi;"
            f"pop esi;"
            f"\n  mov eax,0x167;"
            f"call 0x2eb380;"
            f"mov [esi+0x18],eax;"
            f"\n  mov dword ptr [esi+0x10],57;"
            f"cmp dword ptr [{STATE+4}],8;"
            f"je label;"
            f"mov dword ptr [esi+0x10],159;"
            f"\n  label:mov edx,{labels['prequel']};"
            f"mov ebx,154;"
            f"mov ecx,446;"
            f"call dword ptr [edi+0x4ec];"
            f"\n  mov eax,0x167;"
            f"call 0x2eb3f4;"
            f"pop dword ptr [esi+0x18];"
            f"pop dword ptr [esi+0x10];"
            f"draw_done:popad;"
            f"popfd;"
            f"ret;"
        )
        emit(DRAW, draw, 0xf00)
    # EAX 0=retail main menu, 1=no-op, 2=Prequel, 3=quit.
    # A failed CreateProcess leaves the current menu open; no progress is lost.
    out.append((SWITCH, restart_code(context.imports, labels)))
    out.append((ENTRY, asm(ENTRY, f'call {BOOT}')))
    a = context.open_site
    out.append((a, asm(a, f'call {OPEN}') + b'\x90'))
    return out


@dataclass(frozen=True)
class Patch:
    address: int
    before: bytes
    after: bytes


@dataclass(frozen=True)
class Plan:
    patches: tuple
    context: Context

    @property
    def ranges(self):
        return tuple((p.address, p.address + len(p.after)) for p in self.patches)


def prepare(read, *, imports, demo_pieces, home, demo_root, shared_root):
    """Prepare campaign startup in a fresh build image.

    Demo helpers come from verified original demo/retail sources. Matching helper
    bodies can be reused, while intervening data is preserved. Campaign-owned
    storage must be empty before the startup code is installed.
    """
    helpers = tuple((a, bytes(b)) for a, b in demo_pieces if a >= VARS)
    if len(dict(helpers)) != len(helpers):
        raise ValueError('Duplicate demo helper')
    for i, (a, b) in enumerate(helpers):
        if not b or not VARS <= a < a + len(b) <= VARS + 0x1000:
            raise ValueError('Invalid demo helper bounds')
        if any(a < c + len(d) and c < a + len(b) for c, d in helpers[:i]):
            raise ValueError('Overlapping demo helpers')
    table = dict(helpers).get(FUNCS, b'')
    if len(table) != 138 * 4:
        raise ValueError('Missing demo function table')
    context = bind(read, imports, struct.unpack('<138I', table))
    expected_entry = asm(ENTRY, 'call 0x1d27000')
    expected_open = b'\xff\x15' + struct.pack('<I', imports['CreateFileA'])
    for a, b in (
        (ENTRY, expected_entry), (context.open_site, expected_open),
        (0x2448cc, struct.pack('<I', 0x35dccc))
    ):
        if bytes(read(a, len(b))) != b:
            raise ValueError('Unexpected cold campaign provider')
    regions = []
    for a, end in RANGES:
        before = bytes(read(a, end - a))
        if len(before) != end - a or any(before):
            raise ValueError('Campaign reservation occupied')
        regions.append((a, before, bytearray(before)))
    for a, b in helpers:
        before = bytes(read(a, len(b)))
        if before not in (b, bytes(len(b))):
            raise ValueError('Demo helper differs from original-derived provider')
        regions.append((a, before, bytearray(b)))
    for a, b in (
        (ENTRY, expected_entry), (context.open_site, expected_open),
        (0x2448cc, struct.pack('<I', 0x35dccc))
    ):
        regions.append((a, b, bytearray(b)))
    payload = bodies(context, profile=119, home=home, demo_root=demo_root, shared_root=shared_root)
    payload += [(TAG, MAGIC), (0x2448cc, struct.pack('<I', RF))]
    for a, b in payload:
        hits = [
            (base, out) for base, _, out in regions if base <= a and a + len(b) <= base + len(out)
        ]
        if len(hits) != 1:
            raise ValueError('Campaign payload escaped owned region')
        base, out = hits[0]
        out[a - base:a - base + len(b)] = b
    return Plan(tuple(Patch(a, before, bytes(out)) for a, before, out in regions), context)


def install(plan, write, read):
    current = tuple(bytes(read(p.address, len(p.before))) for p in plan.patches)
    if all(now == p.after for now, p in zip(current, plan.patches)):
        return
    if any(now != p.before for now, p in zip(current, plan.patches)):
        raise ValueError('Campaign install preimage changed')
    for p in plan.patches:
        write(p.address, p.after)


@dataclass(frozen=True)
class SwitchProvider:
    text: bytes
    callback: bytes
    demo_root_address: int


def switch_provider(imports, *, home, demo_root, shared_root):
    """Recreate the complete cold callback from its maintained authoring source.

    This provider has no image lookup or captured preimage. Its text addresses
    come from the same generator used by startup, including caller-supplied paths.
    """
    for name in ('GetModuleHandleA', 'GetProcAddress', 'CloseHandle', 'ExitProcess'):
        a = imports.get(name)
        if type(a) is not int or not 0x11000 <= a <= 0x2000000 - 4:
            raise ValueError('Invalid campaign callback import: ' + name)
    labels, text = text_data(profile=119, home=home, demo_root=demo_root, shared_root=shared_root)
    callback = restart_code(imports, labels)
    if len(callback) > 0x400:
        raise ValueError('Campaign callback exceeds handoff reservation')
    return SwitchProvider(text, callback.ljust(0x400, b'\0'), labels['demo_root'])
