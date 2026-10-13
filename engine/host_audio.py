"""Connect the original Miles audio calls to the Windows digital-audio bridge.

Expected instructions identify each supported entry point before it is replaced.
The original backend calling conventions are preserved by the bridge adapters.
"""
from build_paths import CONFIG
from pathlib import Path
import struct

INIT = 0x1d27000
SLOTS = 0x1d2a000
STATE = 0x1d2b000
TEXT = 0x1d28000
NAMES = [
    'TN_Pump', 'TN_InstallDIG', 'TN_UninstallDIG', 'TN_InstallMDI', 'TN_InitSample',
    'TN_StartSample', 'TN_LoadBuffer', 'TN_MinimumBuffer', 'TN_GetStats', 'TN_TimeMS',
    'TN_FrameBegin', 'TN_FrameEnd', 'TN_Suspend', 'TN_Resume', 'TN_BindLegacyAudio', 'TN_NewWindow',
    'TN_MinMax', 'TN_Layout', 'TN_ClearBars'
]


def slot(name):
    return SLOTS + NAMES.index(name) * 4


def setup(write, asm, call, r):
    cursor = TEXT

    def string(s):
        nonlocal cursor
        a = cursor
        write(a, s.encode() + b'\0')
        cursor += len(s) + 1
        return a

    dll = Path(CONFIG['audio_dll']).resolve()
    code = (
        f"push {string(str(dll))};"
        f"{call('LoadLibraryA')}test eax,eax;"
        f"jz audio_failure;"
        f"mov ebx,eax;"
    )
    for n in NAMES:
        code += (
            f"push {string(n)};"
            f"push ebx;"
            f"{call('GetProcAddress')}test eax,eax;"
            f"jz audio_failure;"
            f"mov [{slot(n)}],eax;"
        )
    code += (
        f"call dword ptr [{slot('TN_GetStats')}];"
        f"mov [{STATE}],eax;"
        f"ret;"
        f"audio_failure:{call('GetLastError')}mov [{STATE+4}],eax;"
        f"mov eax,0xff00;"
        f"int 0x21;"
    )
    data = asm(INIT, code)
    assert len(data) < 0x1000
    write(INIT, data)
    # Backend init/start stay intact for DLL-to-Watcom ABI adapters.
    hooks = {
        0x30b300: 'TN_InstallDIG',
        0x30b410: 'TN_UninstallDIG',
        0x30d1ac: 'TN_InstallMDI',
        0x30b720: 'TN_InitSample',
        0x30b9dc: 'TN_StartSample',
        0x30c7a4: 'TN_LoadBuffer',
        0x30c58c: 'TN_MinimumBuffer'
    }
    signatures = {
        0x30b300: '5657558b7424',
        0x30b410: '57558b15f4df',
        0x30d1ac: '5657558b7424',
        0x30b720: '57558b15f4df',
        0x30b9dc: '57558b15f4df',
        0x30c7a4: '5657558b15f4',
        0x30c58c: '5657558b7424'
    }
    for a, n in hooks.items():
        assert r[a:a + 6] == bytes.fromhex(signatures[a]), (hex(a), r[a:a + 8].hex())
        write(a, asm(a, f'jmp dword ptr [{slot(n)}]'))
    assert r[0x31edec:0x31edf2] == bytes.fromhex('56575583ec1c')
    write(0x31edec, b'\xc3')  # Software mixer applies volume directly, no ISA table.
    return hooks
