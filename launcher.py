"""Open the launcher for an existing private portable installation."""
from pathlib import Path
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--home', type=Path, help='Installation folder (defaults to beside the packaged launcher)'
    )
    parser.add_argument(
        '--dependencies', type=Path, help='Optional isolated Python dependency folder'
    )
    parser.add_argument('--self-check', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--in-game', choices=('save', 'load'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('Python -O disables required validation')
    if args.home is None:
        if not getattr(sys, 'frozen', False):
            parser.error('--home is required when running from source')
        args.home = Path(sys.executable).resolve().parent
    if args.dependencies:
        if getattr(sys, 'frozen', False):
            parser.error('The packaged launcher uses its bundled dependencies')
        sys.path.insert(0, str(args.dependencies.resolve()))
    if args.self_check:
        import ctypes
        import os
        import struct
        import tkinter as tk
        import keystone
        from tnova import state_core as core
        root = tk.Tk()
        root.withdraw()
        try:
            # Exercise Windows calls and a native-to-Python callback so a runtime
            # change cannot pass solely because the UI and assembler import.
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcessId.restype = ctypes.c_ulong
            assert kernel.GetCurrentProcessId() == os.getpid()
            compare_type = ctypes.CFUNCTYPE(
                ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
            )
            compare = compare_type(lambda a, b: (a[0] > b[0]) - (a[0] < b[0]))
            numbers = (ctypes.c_int * 5)(8, -2, 0, 4, 1)
            runtime = ctypes.CDLL(str(Path(os.environ['SystemRoot']) / 'System32/ucrtbase.dll'))
            runtime.qsort.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, compare_type]
            runtime.qsort.restype = None
            runtime.qsort(numbers, len(numbers), ctypes.sizeof(ctypes.c_int), compare)
            assert list(numbers) == [-2, 0, 1, 4, 8]
            assert core.asm(0x1000, 'mov eax,0x1234; ret') == bytes.fromhex('b834120000c3')
            install = core.Installation(args.home.resolve())
            core.save_json(
                args.self_check,
                dict(
                    frozen=bool(getattr(sys, 'frozen', False)),
                    python=sys.version,
                    pointer_bits=struct.calcsize('P') * 8,
                    executable=sys.executable,
                    bundle=getattr(sys, '_MEIPASS', None),
                    keystone=keystone.__file__,
                    tk=root.tk.call('info', 'patchlevel'),
                    installation=str(install.home),
                    revision=install.revision,
                    assembly_check=True,
                    windows_call_check=True,
                    native_callback_check=True
                )
            )
        finally:
            root.destroy()
        return
    if args.in_game:
        from tnova.ingame_ui import run
        run(args.home, args.in_game)
        return
    from tnova.launcher_ui import run
    run(args.home)


if __name__ == '__main__':
    main()
