"""Share Options between campaigns and offer wrist-height player firing.

The caller supplies verified Windows imports, the shared settings root and the
existing FPS/AI preference helpers. options_row draws the complete checkbox row
and calls the wrist INIT/SAVE/GATE/ACCEPT/CLOSE helpers defined here.

Windows API calls use stdcall. Helpers preserve integer registers and flags
except for documented return values. Original25 holds 25 uint32 settings; all
must be at most 30 before the original Options code applies them.
WristHeightFiring defaults on. Accept saves changes, Cancel discards pending
values, and snapshot restore reloads preferences from the installation's INI.
"""
from patch_support import asm

DATA = 0x1fc2a00
END = 0x1fc3000
LOAD = 0x1fc2b00
SAVE = 0x1fc2d00
TEXT = 0x1fc2e80
STATE = 0x1fc2f00
LOAD_SITE = 0x2c3a34
SAVE_SITE = 0x2cbbdc
FIRST = LOAD + 0x180
EXTRA = {0x2caf83: FIRST, 0x2ca4cd: SAVE}
WRIST_CODE = 0x1fca100
WRIST_END = 0x1fcb000
WRIST_INIT = WRIST_CODE
WRIST_SAVE = WRIST_CODE + 0x100
WRIST_GATE = WRIST_CODE + 0x200
WRIST_DRAW = WRIST_CODE + 0x300
WRIST_EVENT = WRIST_CODE + 0x600
WRIST_ACCEPT = WRIST_CODE + 0x800
WRIST_CLOSE = WRIST_CODE + 0x850
WRIST_TEXT = WRIST_CODE + 0x900
WRIST_STATE = WRIST_CODE + 0xd00
WRIST_STATE_SIZE = 0x100
from features.option_contracts import AI, FPS, AI_DRAW, AI_EVENT, AI_ACCEPT, AI_CLOSE, FPS_DRAW

AI_INIT = AI.init
AI_STATE = AI.state
FPS_INIT = FPS.init
FPS_STATE = FPS.state
WRIST_MUZZLE = 0x1ff7000
RESERVATIONS = ((DATA, END), (WRIST_CODE, WRIST_END))


def bind_providers(ram, *, imports, root):
    """Find the preference hooks in the image being built.

    Searches stay inside the named FPS/AI helpers and require one match each.
    Installation then checks their instruction bytes and reserved storage.
    """
    for name in ('GetModuleHandleA', 'GetProcAddress'):
        if not isinstance(imports.get(name), int) or not 0x11000 <= imports[name] < len(ram) - 4:
            raise ValueError('Missing or invalid Options import: ' + name)
    needle = asm(0, 'mov esi,0x1d08400')
    paths = []
    for start in (FPS_INIT, AI_INIT):
        block = bytes(ram[start:start + 0x200])
        if block.count(needle) != 1:
            raise ValueError('Ambiguous or missing preference path provider')
        paths.append(start + block.index(needle))
    text_start = 0x1e39e00
    label = b'FASTER AI FIRING\0'
    block = bytes(ram[text_start:text_start + 0x200])
    if block.count(label) != 1:
        raise ValueError('Ambiguous or missing AI label provider')
    old_label = text_start + block.index(label)
    needle = asm(0, f'mov edx,{old_label}')
    block = bytes(ram[AI_DRAW:AI_DRAW + 0x200])
    if block.count(needle) != 1:
        raise ValueError('Ambiguous or missing AI draw provider')
    return dict(
        imports=dict(imports),
        root=root,
        path_sites=tuple(paths),
        label_site=AI_DRAW + block.index(needle),
        old_label=old_label
    )


def shared_bodies(imports, root, path_sites):
    value = (str(root) + '\\').encode() + b'\0'
    assert len(value) <= 0x100
    out = [(DATA, value), *[(a, asm(a, f'mov esi,{DATA}')) for a in path_sites]]
    labels = {}
    raw = bytearray()
    for k, v in [
        ('dll', 'kernel32.dll'), ('read', 'GetPrivateProfileStructA'),
        ('write', 'WritePrivateProfileStructA'), ('section', 'Options'), ('key', 'Original25')
    ]:
        labels[k] = TEXT + len(raw)
        raw += v.encode() + b'\0'
    assert len(raw) <= STATE - TEXT
    out.append((TEXT, bytes(raw)))
    common = (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"call {FPS_INIT};"
        f"push {labels['dll']};"
        f"call dword ptr [{imports['GetModuleHandleA']}];"
    )
    read = common + (
        f"push {labels['read']};"
        f"push eax;"
        f"call dword ptr [{imports['GetProcAddress']}];"
        f"test eax,eax;"
        f"jz done;"
        f"push {FPS_STATE+64};"
        f"push 100;"
        f"push {STATE};"
        f"push {labels['key']};"
        f"push {labels['section']};"
        f"call eax;"
        f"test eax,eax;"
        f"jz done;"
        f"mov esi,{STATE};"
        f"mov ecx,25;"
        f"check:cmp dword ptr [esi],30;"
        f"ja done;"
        f"add esi,4;"
        f"loop check;"
        f"mov esi,{STATE};"
        f"mov edi,0x43d510;"
        f"mov ecx,25;"
        f".byte 0xf3,0xa5;"
        f"done:popad;"
        f"popfd;"
        f"jmp 0x2ca1e4;"
    )
    save = f'call {AI_ACCEPT};' + common + (
        f"push {labels['write']};"
        f"push eax;"
        f"call dword ptr [{imports['GetProcAddress']}];"
        f"test eax,eax;"
        f"jz done;"
        f"push {FPS_STATE+64};"
        f"push 100;"
        f"push 0x43d510;"
        f"push {labels['key']};"
        f"push {labels['section']};"
        f"call eax;"
        f"done:popad;"
        f"popfd;"
        f"ret;"
    )
    for a, body, cap in ((LOAD, read, 0x200), (SAVE, save, 0x180)):
        b = asm(a, body)
        assert len(b) <= cap
        out.append((a, b))
    out.append(
        (
            FIRST,
            asm(
                FIRST, (
                    f"cmp dword ptr [{STATE+104}],0;"
                    f"jne ready;"
                    f"mov dword ptr [{STATE+104}],1;"
                    f"jmp {LOAD};"
                    f"ready:jmp 0x2ca1e4;"
                )
            )
        )
    )
    out.extend((a, asm(a, f'call {dest}')) for a, dest in EXTRA.items())
    out.extend(
        [(LOAD_SITE, asm(LOAD_SITE, f'call {LOAD}')), (SAVE_SITE, asm(SAVE_SITE, f'call {SAVE}'))]
    )
    return out


def wrist_bodies(label_site):
    out = []
    labels = {}
    raw = bytearray()
    for k, v in [
        ('section', 'Gameplay'), ('key', 'WristHeightFiring'), ('zero', '0'), ('one', '1'),
        ('ai', 'FULL-RATE AI FIRING'), ('wrist', 'WRIST-HEIGHT FIRING'),
        (
            'aihelp',
            'Both sides use weapon cooldowns. Normal aiming, range and safety checks still apply.'
        ),
        (
            'whelp',
            'On: fire from animated wrists. Off: helmet height. Nearby cover can block wrist shots.'
        )
    ]:
        labels[k] = WRIST_TEXT + len(raw)
        raw += v.encode() + b'\0'
    assert len(raw) < WRIST_STATE - WRIST_TEXT
    out.append((WRIST_TEXT, bytes(raw)))

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b), cap)
        out.append((a, b))

    emit(
        WRIST_INIT, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [{WRIST_STATE}],1;"
            f"je done;"
            f"call {AI_INIT};"
            f"cmp dword ptr [{AI_STATE}],1;"
            f"jne done;"
            f"\n push {AI_STATE+64};"
            f"push 1;"
            f"push {labels['key']};"
            f"push {labels['section']};"
            f"call dword ptr [{AI_STATE+16}];"
            f"and eax,1;"
            f"mov [{WRIST_STATE+4}],eax;"
            f"mov dword ptr [{WRIST_STATE}],1;"
            f"done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )
    emit(
        WRIST_SAVE, (
            f"pushfd;"
            f"pushad;"
            f"call {WRIST_INIT};"
            f"cmp dword ptr [{WRIST_STATE}],1;"
            f"jne done;"
            f"mov eax,[{WRIST_STATE+8}];"
            f"mov [{WRIST_STATE+4}],eax;"
            f"mov edx,{labels['zero']};"
            f"test eax,eax;"
            f"jz value;"
            f"mov edx,{labels['one']};"
            f"value:push {AI_STATE+64};"
            f"push edx;"
            f"push {labels['key']};"
            f"push {labels['section']};"
            f"call dword ptr [{AI_STATE+20}];"
            f"done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )
    emit(
        WRIST_GATE, (
            f"pushfd;"
            f"call {WRIST_INIT};"
            f"cmp dword ptr [{WRIST_STATE}],1;"
            f"jne yes;"
            f"cmp dword ptr [{WRIST_STATE+4}],0;"
            f"je no;"
            f"yes:popfd;"
            f"jmp {WRIST_MUZZLE};"
            f"no:popfd;"
            f"jmp 0x28a6f0;"
        ), 0x100
    )
    emit(
        WRIST_DRAW, (
            f"call {FPS_DRAW};"
            f"pushfd;"
            f"pushad;"
            f"call {WRIST_INIT};"
            f"cmp dword ptr [{WRIST_STATE+12}],1;"
            f"je draw;"
            f"mov eax,[{WRIST_STATE+4}];"
            f"mov [{WRIST_STATE+8}],eax;"
            f"mov dword ptr [{WRIST_STATE+12}],1;"
            f"\n draw:mov esi,[0x44b1a0];"
            f"push dword ptr [esi+0x10];"
            f"push dword ptr [esi+0x18];"
            f"mov edi,[0x44b194];"
            f"mov dword ptr [esi+0x10],0;"
            f"\n mov eax,10;"
            f"mov edx,388;"
            f"mov ebx,210;"
            f"mov ecx,410;"
            f"call dword ptr [edi+0x40];"
            f"\n mov eax,0;"
            f"mov edx,466;"
            f"mov ebx,639;"
            f"mov ecx,479;"
            f"call dword ptr [edi+0x40];"
            f"\n mov dword ptr [esi+0x10],0xf7;"
            f"mov eax,14;"
            f"mov edx,392;"
            f"mov ebx,24;"
            f"mov ecx,402;"
            f"call dword ptr [edi+0x48];"
            f"\n cmp dword ptr [{WRIST_STATE+8}],0;"
            f"je label;"
            f"mov eax,16;"
            f"mov edx,394;"
            f"mov ebx,22;"
            f"mov ecx,400;"
            f"call dword ptr [edi+0x40];"
            f"\n label:mov eax,0x164;"
            f"call 0x2eb380;"
            f"mov [esi+0x18],eax;"
            f"mov edx,{labels['wrist']};"
            f"mov ebx,30;"
            f"mov ecx,392;"
            f"call dword ptr [edi+0x4ec];"
            f"\n cmp dword ptr [{WRIST_STATE+16}],0;"
            f"je done;"
            f"mov edx,{labels['aihelp']};"
            f"cmp dword ptr [{WRIST_STATE+16}],1;"
            f"je help;"
            f"mov edx,{labels['whelp']};"
            f"help:mov eax,[esi+0x18];"
            f"mov ebx,6;"
            f"mov ecx,468;"
            f"call dword ptr [edi+0x4ec];"
            f"\n done:mov eax,0x164;"
            f"call 0x2eb3f4;"
            f"pop dword ptr [esi+0x18];"
            f"pop dword ptr [esi+0x10];"
            f"popad;"
            f"popfd;"
            f"ret;"
        ), 0x300
    )
    emit(
        WRIST_EVENT, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [eax],0x40;"
            f"je mouse;"
            f"cmp dword ptr [eax],1;"
            f"jne pass;"
            f"\n mouse:xor ebx,ebx;"
            f"movsx ecx,word ptr [eax+10];"
            f"cmp ecx,388;"
            f"jl selected;"
            f"cmp ecx,410;"
            f"jge selected;"
            f"\n movsx ecx,word ptr [eax+8];"
            f"cmp ecx,436;"
            f"jl wrist;"
            f"cmp ecx,630;"
            f"jge selected;"
            f"mov ebx,1;"
            f"jmp selected;"
            f"\n wrist:cmp ecx,10;"
            f"jl selected;"
            f"cmp ecx,210;"
            f"jge selected;"
            f"mov ebx,2;"
            f"\n selected:cmp dword ptr [eax],1;"
            f"jne hover;"
            f"cmp ebx,2;"
            f"jne hover;"
            f"xor dword ptr [{WRIST_STATE+8}],1;"
            f"mov [{WRIST_STATE+16}],ebx;"
            f"call redraw;"
            f"\n push 0;"
            f"push 0x40;"
            f"mov eax,0x7cc;"
            f"mov ebx,0x28;"
            f"push 0x40;"
            f"mov ecx,1;"
            f"xor edx,edx;"
            f"call 0x247b60;"
            f"popad;"
            f"popfd;"
            f"mov al,1;"
            f"ret;"
            f"\n hover:cmp ebx,[{WRIST_STATE+16}];"
            f"je pass;"
            f"mov [{WRIST_STATE+16}],ebx;"
            f"call redraw;"
            f"\n pass:popad;"
            f"popfd;"
            f"jmp {AI_EVENT};"
            f"\n redraw:call 0x2e4b1c;"
            f"mov eax,0x446f78;"
            f"call {AI_DRAW};"
            f"mov eax,0x446fb8;"
            f"call 0x2e43d0;"
            f"call 0x2e4b78;"
            f"ret;"
        ), 0x200
    )
    emit(WRIST_ACCEPT, f'call {WRIST_SAVE};jmp {AI_ACCEPT};', 0x50)
    emit(
        WRIST_CLOSE, (
            f"pushfd;"
            f"mov dword ptr [{WRIST_STATE+12}],0;"
            f"mov dword ptr [{WRIST_STATE+16}],0;"
            f"popfd;"
            f"jmp {AI_CLOSE};"
        ), 0xb0
    )
    labelsite = label_site
    for a, s in [
        (AI_DRAW, f'call {WRIST_DRAW}'), (labelsite, f"mov edx,{labels['ai']}"),
        (0x2ca450, f'jmp {WRIST_EVENT}'), (SAVE, f'call {WRIST_ACCEPT}'),
        (0x2cbc08, f'jmp {WRIST_CLOSE}'), (0x28a925, f'call {WRIST_GATE}')
    ]:
        emit(a, s, 5)
    return out


def predecessors(path_sites, label_site, old_label):
    """Describe required hooks using the caller's verified AI label address."""
    return {
        **{
            a: asm(a, 'mov esi,0x1d08400')
            for a in path_sites
        }, LOAD_SITE: asm(LOAD_SITE, 'call 0x2ca1e4'),
        SAVE_SITE: asm(SAVE_SITE, f'call {AI_ACCEPT}'),
        **{
            a: asm(a, 'call 0x2ca1e4')
            for a in EXTRA
        }, AI_DRAW: asm(AI_DRAW, f'call {FPS_DRAW}'),
        label_site: asm(label_site, f'mov edx,{old_label}'),
        0x2ca450: asm(0x2ca450, f'jmp {AI_EVENT}'),
        0x2cbc08: asm(0x2cbc08, f'jmp {AI_CLOSE}'),
        0x28a925: asm(0x28a925, f'call {WRIST_MUZZLE}')
    }


def bodies(imports, root, path_sites, label_site):
    """Final writes, merging superseded bytes instead of replaying amendments."""
    owned = {}
    for a, b in shared_bodies(imports, root, path_sites) + wrist_bodies(label_site):
        owned.update((a + i, v) for i, v in enumerate(b))
    out = []
    for a in sorted(owned):
        if out and a == out[-1][0] + len(out[-1][1]):
            out[-1][1].append(owned[a])
        else:
            out.append((a, bytearray([owned[a]])))
    return [(a, bytes(b)) for a, b in out]


def install(write, ram, *, imports, root, path_sites, label_site, old_label):
    """Fresh offline install only. Validate everything before any write."""
    pieces = bodies(imports, root, path_sites, label_site)
    for a, b in predecessors(path_sites, label_site, old_label).items():
        assert bytes(ram[a:a + len(b)]) == b, (hex(a), 'unexpected Options hook')
    for start, end in RESERVATIONS:
        assert not any(ram[start:end]), (hex(start), 'Options reservation occupied')
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
