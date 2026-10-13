"""Shared Options/wrist policy tests with only external API boundaries modeled."""
from pathlib import Path
import struct, sys, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import options as f
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

STACK = 0x1700000
STOP = 0x10000
MODULE = 0x1800000
PROC = MODULE + 16
READ = MODULE + 32
WRITE = MODULE + 48
IREAD = MODULE + 64
IWRITE = MODULE + 80


def put(u, a, n):
    u.mem_write(a, struct.pack('<I', n & 0xffffffff))


def get(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def string(u, a):
    return bytes(u.mem_read(a, 256)).split(b'\0')[0]


class Fixture:

    def __init__(self):
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        self.values = list(range(25))
        self.read_success = True
        self.integer = None
        self.calls = []
        self.saved = None
        self.integer_saved = None
        self.ai_ready = True
        for a, b in f.bodies(
            {
                'GetModuleHandleA': 0x300000,
                'GetProcAddress': 0x300004
            }, 'C:/fixture/retail', (0x1f76540, 0x1e39240), 0x1e396a0
        ):
            u.mem_write(a, b)
        put(u, 0x300000, MODULE)
        put(u, 0x300004, PROC)
        for a in (
            f.FPS_INIT, f.AI_INIT, f.AI_ACCEPT, f.AI_CLOSE, 0x2ca1e4, f.WRIST_MUZZLE, 0x28a6f0,
            MODULE, PROC, READ, WRITE, IREAD, IWRITE
        ):
            u.mem_write(a, b'\xc3')
        u.mem_write(f.FPS_STATE + 64, b'C:/fixture/retail/TNHR.INI\0')
        u.mem_write(f.AI_STATE + 64, b'C:/fixture/retail/TNHR.INI\0')
        put(u, f.AI_STATE + 16, IREAD)
        put(u, f.AI_STATE + 20, IWRITE)
        u.hook_add(UC_HOOK_CODE, self.boundary)

    def boundary(self, u, a, n, _):
        if (
            a not in (
                MODULE, PROC, READ, WRITE, IREAD, IWRITE, f.AI_INIT, f.AI_ACCEPT, f.AI_CLOSE,
                0x2ca1e4, f.WRIST_MUZZLE, 0x28a6f0
            )
        ):
            return
        self.calls.append(a)
        sp = u.reg_read(UC_X86_REG_ESP)
        arg = lambda i: get(u, sp + 4 + i * 4)
        pops = 0
        result = None
        if a == MODULE:
            pops = 4
            result = 1
        elif a == PROC:
            pops = 8
            result = READ if string(u, arg(1)) == b'GetPrivateProfileStructA' else WRITE
        elif a == READ:
            self.assert_profile(arg, 100)
            pops = 20
            result = int(self.read_success)
            if self.read_success:
                u.mem_write(arg(2), struct.pack('<25I', *self.values))
        elif a == WRITE:
            self.assert_profile(arg, 100)
            pops = 20
            result = 1
            self.saved = bytes(u.mem_read(arg(2), arg(3)))
        elif a == IREAD:
            pops = 16
            result = arg(2) if self.integer is None else self.integer
        elif a == IWRITE:
            pops = 16
            result = 1
            self.integer_saved = string(u, arg(2))
        elif a == f.AI_INIT:
            put(u, f.AI_STATE, int(self.ai_ready))
        elif a == f.WRIST_MUZZLE:
            result = 97
        elif a == 0x28a6f0:
            result = 1
        if result is not None:
            u.reg_write(UC_X86_REG_EAX, result)
        if pops:
            u.reg_write(UC_X86_REG_EIP, get(u, sp))
            u.reg_write(UC_X86_REG_ESP, sp + 4 + pops)

    def assert_profile(self, arg, size):
        assert string(self.u, arg(0)) == b'Options'
        assert string(self.u, arg(1)) == b'Original25'
        assert arg(3) == size and string(self.u, arg(4)) == b'C:/fixture/retail/TNHR.INI'

    def call(self, a):
        put(self.u, STACK, STOP)
        self.u.reg_write(UC_X86_REG_ESP, STACK)
        self.u.emu_start(a, STOP, count=20000)
        assert self.u.reg_read(UC_X86_REG_EIP) == STOP
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK + 4
        return self.u.reg_read(UC_X86_REG_EAX)


class OptionsTests(unittest.TestCase):

    def test_valid_original_options_and_once_only_load(self):
        x = Fixture()
        x.call(f.FIRST)
        self.assertEqual(bytes(x.u.mem_read(0x43d510, 100)), struct.pack('<25I', *x.values))
        x.values = [30] * 25
        x.call(f.FIRST)
        self.assertEqual(x.calls.count(READ), 1)

    def test_missing_or_invalid_profile_never_partially_changes_options(self):
        for case in ('missing', 'invalid-first', 'invalid-last'):
            x = Fixture()
            sentinel = bytes([0x7a]) * 100
            x.u.mem_write(0x43d510, sentinel)
            if case == 'missing':
                x.read_success = False
            else:
                x.values[0 if case == 'invalid-first' else 24] = 31
            x.call(f.LOAD)
            self.assertEqual(bytes(x.u.mem_read(0x43d510, 100)), sentinel)

    def test_shared_accept_saves_wrist_then_ai_then_original(self):
        x = Fixture()
        put(x.u, f.WRIST_STATE, 1)
        put(x.u, f.WRIST_STATE + 8, 0)
        values = struct.pack('<25I', *range(25))
        x.u.mem_write(0x43d510, values)
        x.call(f.SAVE)
        self.assertEqual(x.integer_saved, b'0')
        self.assertEqual(x.saved, values)
        self.assertLess(x.calls.index(IWRITE), x.calls.index(f.AI_ACCEPT))
        self.assertLess(x.calls.index(f.AI_ACCEPT), x.calls.index(WRITE))

    def test_wrist_default_gate_and_cancel(self):
        for enabled in (None, 0, 1):
            x = Fixture()
            x.integer = enabled
            self.assertEqual(x.call(f.WRIST_GATE), 1 if enabled == 0 else 97)
            active = get(x.u, f.WRIST_STATE + 4)
            put(x.u, f.WRIST_STATE + 8, 1 - active)
            put(x.u, f.WRIST_STATE + 12, 1)
            put(x.u, f.WRIST_STATE + 16, 2)
            x.call(f.WRIST_CLOSE)
            self.assertEqual(get(x.u, f.WRIST_STATE + 4), active)
            self.assertEqual(get(x.u, f.WRIST_STATE + 12), 0)
            self.assertEqual(get(x.u, f.WRIST_STATE + 16), 0)
            self.assertIsNone(x.integer_saved)

    def test_unavailable_preference_api_retains_wrist_default(self):
        x = Fixture()
        x.ai_ready = False
        x.integer = 0
        self.assertEqual(x.call(f.WRIST_GATE), 97)
        self.assertEqual(get(x.u, f.WRIST_STATE), 0)
        self.assertNotIn(IREAD, x.calls)


if __name__ == '__main__':
    unittest.main()
