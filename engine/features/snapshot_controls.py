"""Paused Prequel F5/F9 controls; launch the shared snapshot picker.

Input only queues the request. The ordinary idle dispatch launches the helper
after input unwinds. No process handles or queued requests survive a capture.
Retail and unpaused input keep the previous behavior. Options advertises the
shortcuts without covering its existing contextual help.
"""
from patch_support import asm
from features import prequel_help

BASE = 0x1eff500
INPUT, DISPATCH, SPAWN, DRAW = BASE, BASE + 0x100, BASE + 0x180, BASE + 0x500
TEXT, STATE, END = BASE + 0x600, BASE + 0x800, 0x1f00000
REQUEST, PI, SI, EXE, CMD = STATE, STATE + 16, STATE + 32, STATE + 112, STATE + 320
INPUT_SITE, DISPATCH_SITE, DRAW_SITE = 0x1d22000, 0x1d18508, 0x1e39600


def bodies(imports, *, presentation=True):
    """Emit snapshot controls with optional standalone footer drawing.

    presentation=False supplies strings, input and helper dispatch while leaving
    the footer slot and drawing hook to the combined Options row installer.
    """
    out = []

    def emit(a, limit, source):
        data = asm(a, source)
        assert a + len(data) <= limit, (hex(a), len(data))
        out.append((a, data))

    labels, raw = {}, bytearray()
    for name, value in [
        ('kernel', 'kernel32.dll'), ('create', 'CreateProcessA'),
        ('exe', 'Terra Nova Launcher.exe'), ('save', '" --in-game save'),
        ('load', '" --in-game load'), ('help', 'PREQUEL STATES: PAUSE (P), THEN F5 SAVE / F9 LOAD')
    ]:
        labels[name] = TEXT + len(raw)
        raw += value.encode('ascii') + b'\0'
    assert TEXT + len(raw) <= STATE
    out.append((TEXT, bytes(raw)))
    emit(
        INPUT, DISPATCH, (
            f"pushfd;"
            f"\n        cmp dword ptr [0x1fc0700],1;"
            f"jne pass;"
            f"\n        cmp byte ptr [0x35f3f4],1;"
            f"jne pass;"
            f"\n        cmp dword ptr [0x9aa0ec],1;"
            f"jne pass;"
            f"\n        cmp dword ptr [0x1fcae0c],0;"
            f"jne pass;"
            f"\n        cmp eax,0x100;"
            f"je key;"
            f"cmp eax,0x101;"
            f"jne pass;"
            f"\n        key:cmp ebx,0x74;"
            f"je selected;"
            f"cmp ebx,0x78;"
            f"jne pass;"
            f"\n        selected:cmp eax,0x101;"
            f"je consumed;"
            f"test ecx,0x40000000;"
            f"jnz consumed;"
            f"\n        mov [{REQUEST}],ebx;"
            f"\n        consumed:popfd;"
            f"ret;"
            f"\n        pass:popfd;"
            f"cmp eax,8;"
            f"je 0x1d2219a;"
            f"jmp 0x1d22009;"
        )
    )
    emit(
        DISPATCH, SPAWN, (
            f"call 0x1d18000;"
            f"pushfd;"
            f"pushad;"
            f"\n        cmp dword ptr [{REQUEST}],0;"
            f"je done;"
            f"\n        cmp byte ptr [0x35f3f4],1;"
            f"jne clear;"
            f"\n        cmp dword ptr [0x1fc0700],1;"
            f"jne clear;"
            f"\n        cmp dword ptr [0x9aa0ec],1;"
            f"jne clear;"
            f"\n        call {SPAWN};"
            f"\n        clear:cld;"
            f"mov edi,{STATE};"
            f"xor eax,eax;"
            f"mov ecx,{(END-STATE)//4};"
            f"rep stosd;"
            f"\n        done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    # Paths come from the already relocated retail root. Supply lpApplicationName
    # separately, quote argv[0], and do not invoke a shell. Buffers are bounded.
    emit(
        SPAWN, DRAW, (
            f"cld;"
            f"\n        push {labels['kernel']};"
            f"call dword ptr [{imports['GetModuleHandleA']}];"
            f"\n        push {labels['create']};"
            f"push eax;"
            f"call dword ptr [{imports['GetProcAddress']}];"
            f"\n        test eax,eax;"
            f"jz failed;"
            f"mov ebp,eax;"
            f"\n        mov esi,0x1fc2a00;"
            f"mov edi,{EXE};"
            f"mov ecx,180;"
            f"\n        path:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jz suffix;"
            f"loop path;"
            f"jmp failed;"
            f"\n        suffix:sub edi,8;"
            f"cmp edi,{EXE};"
            f"jb failed;"
            f"\n        mov esi,{labels['exe']};"
            f"name:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jnz name;"
            f"\n        mov edi,{CMD};"
            f"mov al,34;"
            f"stosb;"
            f"mov esi,{EXE};"
            f"\n        command:lodsb;"
            f"test al,al;"
            f"jz arguments;"
            f"stosb;"
            f"jmp command;"
            f"\n        arguments:mov esi,{labels['save']};"
            f"cmp dword ptr [{REQUEST}],0x74;"
            f"je append;"
            f"\n        mov esi,{labels['load']};"
            f"append:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jnz append;"
            f"\n        mov dword ptr [{SI}],68;"
            f"\n        push {PI};"
            f"push {SI};"
            f"push 0;"
            f"push 0;"
            f"push 0x08000000;"
            f"push 0;"
            f"push 0;"
            f"push 0;"
            f"\n        push {CMD};"
            f"push {EXE};"
            f"call ebp;"
            f"test eax,eax;"
            f"jz failed;"
            f"\n        push dword ptr [{PI}];"
            f"call dword ptr [{imports['CloseHandle']}];"
            f"\n        push dword ptr [{PI+4}];"
            f"call dword ptr [{imports['CloseHandle']}];"
            f"ret;"
            f"\n        failed:mov eax,{labels['help']};"
            f"call 0x1efec00;"
            f"ret;"
        )
    )
    assert labels['help'] == prequel_help.TEXT
    out.append((DRAW, prequel_help.code(labels['help'])))
    out += [
        (INPUT_SITE, asm(INPUT_SITE, f'jmp {INPUT};') + b'\x90' * 4),
        (DISPATCH_SITE, asm(DISPATCH_SITE, f'call {DISPATCH};')),
        (DRAW_SITE, asm(DRAW_SITE, f'call {DRAW};'))
    ]
    return out if presentation else [(a, b) for a, b in out if a not in (DRAW, DRAW_SITE)]


def predecessors():
    return {
        INPUT_SITE: bytes.fromhex('83f8080f8491010000'),
        DISPATCH_SITE: asm(DISPATCH_SITE, 'call 0x1d18000;'),
        DRAW_SITE: asm(DRAW_SITE, 'call 0x1fca400;')
    }


def install(write, read, *, imports, presentation=True):
    """Cold offline installation from explicit platform imports.

    presentation=False leaves the footer and its hook for the final Options
    family, but still supplies its strings and validates the provider hook.
    Live patching and migration of existing controls are not supported.
    """
    for name in ('GetModuleHandleA', 'GetProcAddress', 'CloseHandle'):
        a = imports.get(name)
        if type(a) is not int or not 0x11000 <= a <= 0x2000000 - 4:
            raise ValueError('Invalid snapshot-control import: ' + name)
    for a, b in predecessors().items():
        if bytes(read(a, len(b))) != b:
            raise ValueError('Snapshot-control provider differs at ' + hex(a))
    reservation = bytes(read(BASE, END - BASE))
    if len(reservation) != END - BASE or any(reservation):
        raise ValueError('Snapshot-control reservation occupied or truncated')
    pieces = bodies(imports, presentation=presentation)
    # Authoring completes before the first write. No image or revision lookup.
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
