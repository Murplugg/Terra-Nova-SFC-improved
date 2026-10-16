"""Run the actual startup initializer against modeled Windows path APIs.

The cases cover folder moves, quoted campaign commands, failure boundaries and
the startup ABI. Native startup and snapshot tests must additionally exercise
real Windows file loading; these CPU cases do not replace those checks.
"""
import json
from pathlib import Path
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
from features import runtime_paths as f


class RuntimePathTests(unittest.TestCase):
    def run_initializer(self, executable, directory_ok=True):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        names = ['GetModuleHandleA', 'GetProcAddress', 'LoadLibraryA', 'ExitProcess',
                 'GetModuleFileNameA', 'SetCurrentDirectoryA', 'MessageBoxA']
        slots = {name: 0x100000+i*4 for i, name in enumerate(names)}
        functions = {name: 0x110000+i*16 for i, name in enumerate(names)}
        for name in names:
            u.mem_write(slots[name], struct.pack('<I', functions[name]))
        recipe = json.loads((Path(__file__).resolve().parents[1] / 'engine/release-recipe.json').read_text())
        rows = recipe['relocations']
        u.mem_write(f.ENTRY, f.ORIGINAL)
        f.install(u.mem_write, u.mem_read, imports=slots, relocations=rows)
        calls = []
        word = lambda address: struct.unpack('<I', u.mem_read(address, 4))[0]

        def string(address):
            return bytes(u.mem_read(address, 260)).split(b'\0')[0]

        def model(uc, address, size, unused):
            name = next((n for n, a in functions.items() if a == address), None)
            if name is None:
                return
            sp = uc.reg_read(UC_X86_REG_ESP)
            arg = lambda i: word(sp+4*i)
            count, result = 1, 1
            calls.append(name)
            if name == 'GetProcAddress':
                count, result = 2, functions[string(arg(2)).decode()]
            elif name == 'GetModuleFileNameA':
                count, result = 3, min(len(executable), arg(3))
                uc.mem_write(arg(2), (executable+b'\0')[:arg(3)])
            elif name == 'SetCurrentDirectoryA':
                calls.append(('directory', string(arg(1))))
                result = int(directory_ok)
            elif name == 'MessageBoxA':
                count = 4
            elif name == 'ExitProcess':
                self.assertEqual(arg(1), 1)
                uc.emu_stop()
                return
            uc.reg_write(UC_X86_REG_EAX, result)
            uc.reg_write(UC_X86_REG_ESP, sp+4*(count+1))
            uc.reg_write(UC_X86_REG_EIP, word(sp))

        u.hook_add(UC_HOOK_CODE, model)
        u.reg_write(UC_X86_REG_ESP, 0x1800000)
        u.reg_write(UC_X86_REG_EBX, 0x12345678)
        u.emu_start(f.ENTRY, f.ENTRY+len(f.ORIGINAL), count=200000)
        return u, calls, rows

    def test_move_and_quoted_paths(self):
        for home in (b'C:\\Games\\TNova', b'D:\\Other Folder\\TNova', b'C:\\'):
            with self.subTest(home=home):
                exe = home.rstrip(b'\\') + b'\\native-startup.exe'
                u, calls, rows = self.run_initializer(exe)
                self.assertNotIn('ExitProcess', calls)
                self.assertIn(('directory', home), calls)
                for row in rows:
                    expected = row['value'].encode().replace(b'{ROOT}', home)
                    actual = bytes(u.mem_read(row['offset']+0x10e00, row['capacity']))
                    self.assertEqual(actual, expected.ljust(row['capacity'], b'\0'))
                self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x12345678)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x1800000-4)
                self.assertEqual(bytes(u.mem_read(0x1800000-4, 4)), struct.pack('<I', 3))

    def test_reject_long_non_ascii_and_inaccessible_roots(self):
        for executable, directory_ok in (
            (b'C:\\'+b'x'*120+b'\\native-startup.exe', True),
            (b'C:\\'+b'x'*260, True),
            (b'C:\\caf\xe9\\native-startup.exe', True),
            (b'C:\\Game\\native-startup.exe', False),
        ):
            with self.subTest(executable=executable[:30], directory_ok=directory_ok):
                _, calls, _ = self.run_initializer(executable, directory_ok)
                self.assertIn('MessageBoxA', calls)
                self.assertIn('ExitProcess', calls)

    def test_reject_conflicting_installation(self):
        ram = bytearray(0x2000000)
        ram[f.ENTRY:f.ENTRY+len(f.ORIGINAL)] = f.ORIGINAL
        ram[f.ROOT] = 1
        with self.assertRaisesRegex(ValueError, 'occupied'):
            f.install(lambda a, b: None, lambda a, n: ram[a:a+n], imports={}, relocations=[])
