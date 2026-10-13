"""Execute the connected FPS/AI/wrist/shot preference chain, modeling WinAPI.

No original data or snapshots required. Rendering and original apply/close
continuations are boundaries; preference initialization/save helpers are real.
"""
from pathlib import Path
import struct, sys, types, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import options, shot_assist as shot, option_contracts as c, ai_cadence as ai
from patch_support import asm
from features import fps_display as fps
from tnova.state_core import preference_restore_writes
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

STACK = 0x1700000
STOP = 0x10000
MODULE = 0x1800000
PROC = MODULE + 16
IREAD = MODULE + 32
IWRITE = MODULE + 48
SREAD = MODULE + 64
SWRITE = MODULE + 80
ROOT = 'C:/fixture/shared'


def put(u, a, n):
    u.mem_write(a, struct.pack('<I', n & 0xffffffff))


def get(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def string(u, a):
    return bytes(u.mem_read(a, 256)).split(b'\0')[0].decode('ascii')


class Fixture:

    def __init__(self):
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        self.values = {}
        self.calls = []
        self.fail_proc = None
        self.imports = {'GetModuleHandleA': 0x300000, 'GetProcAddress': 0x300004}
        predecessor = types.SimpleNamespace(imports=self.imports)
        pieces = fps.bodies(self.imports, 0x100000)
        pieces += ai.bodies(self.imports)
        # These operands are discovered by the real adapter too; using an
        # arbitrary stand-in site would overwrite this fixture's live helpers.
        path_sites = []
        for entry in (c.FPS.init, c.AI.init):
            body = dict(pieces)[entry]
            needle = asm(entry, 'mov esi,0x1d08400')
            assert body.count(needle) == 1
            path_sites.append(entry + body.index(needle))
        pieces += options.bodies(self.imports, ROOT, path_sites, 0x1e396a0)
        pieces += shot.bodies()
        for a, b in pieces:
            u.mem_write(a, b)
        put(u, 0x300000, MODULE)
        put(u, 0x300004, PROC)
        u.mem_write(0x1d08400, b'C:/fixture/prequel/\0')
        for a in (MODULE, PROC, IREAD, IWRITE, SREAD, SWRITE, 0x2ca1e4):
            u.mem_write(a, b'\xc3')
        # Original close's frame is already established by FPS.CLOSE.
        u.mem_write(0x2cbc0e, b'\x83\xc4\x0c\x5a\x59\x5b\xc3')
        u.hook_add(UC_HOOK_CODE, self.boundary)

    def boundary(self, u, a, n, _):
        if a not in (MODULE, PROC, IREAD, IWRITE, SREAD, SWRITE, 0x2ca1e4):
            return
        sp = u.reg_read(UC_X86_REG_ESP)
        arg = lambda i: get(u, sp + 4 + i * 4)
        pops = 0
        result = None
        if a == MODULE:
            pops = 4
            result = 1
        elif a == PROC:
            name = string(u, arg(1))
            pops = 8
            result = 0 if name == self.fail_proc else {
                'GetPrivateProfileIntA': IREAD,
                'WritePrivateProfileStringA': IWRITE,
                'GetPrivateProfileStructA': SREAD,
                'WritePrivateProfileStructA': SWRITE
            }[name]
        elif a in (IREAD, IWRITE):
            section, key, path = string(u, arg(0)), string(u, arg(1)), string(u, arg(3))
            self.calls.append(('read' if a == IREAD else 'write', key, path))
            assert path == ROOT + '/TNHR.INI' or path == ROOT + '\\TNHR.INI'
            pops = 16
            if a == IREAD:
                result = self.values.get(key, arg(2))
            else:
                self.values[key] = int(string(u, arg(2)))
                result = 1
        elif a == SREAD:
            self.calls.append(('read', 'Original25', string(u, arg(4))))
            pops = 20
            result = 0
        elif a == SWRITE:
            self.calls.append(('write', 'Original25', string(u, arg(4))))
            pops = 20
            result = 1
            self.saved = bytes(u.mem_read(arg(2), arg(3)))
        else:
            self.calls.append(('original', 'apply', ''))
        if result is not None:
            u.reg_write(UC_X86_REG_EAX, result)
        if pops:
            u.reg_write(UC_X86_REG_EIP, get(u, sp))
            u.reg_write(UC_X86_REG_ESP, sp + 4 + pops)

    def call(self, address):
        put(self.u, STACK, STOP)
        self.u.reg_write(UC_X86_REG_ESP, STACK)
        self.u.emu_start(address, STOP, count=100000)
        assert self.u.reg_read(UC_X86_REG_EIP) == STOP
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK + 4

    def initialize(self):
        for p in c.PREFERENCES.values():
            self.call(p.init)


class OptionLifecycleTests(unittest.TestCase):

    def test_default_values_shared_path_and_initialization_once(self):
        x = Fixture()
        x.initialize()
        for p in c.PREFERENCES.values():
            self.assertEqual(get(x.u, p.state), 1)
            self.assertEqual(get(x.u, p.state + 4), p.default)
        self.assertEqual(len(x.calls), 5)
        # Resource root changes during same-window campaign switches; shared
        # paths/preferences deliberately survive. No stale process pointers here.
        x.u.mem_write(0x1d08400, b'C:/fixture/retail-again/\0')
        x.initialize()
        self.assertEqual(len(x.calls), 5)
        self.assertEqual(string(x.u, c.AI.state + c.PATH_OFFSET), ROOT + '\\TNHR.INI')
        self.assertEqual(string(x.u, c.FPS.state + c.PATH_OFFSET), ROOT + '\\TNHR.INI')

    def test_api_failure_does_not_poison_initialized_flags_and_can_retry(self):
        x = Fixture()
        x.fail_proc = 'WritePrivateProfileStringA'
        x.initialize()
        self.assertFalse(x.calls)
        for p in c.PREFERENCES.values():
            self.assertEqual(get(x.u, p.state), 0)
        x.fail_proc = None
        x.initialize()
        for p in c.PREFERENCES.values():
            self.assertEqual(get(x.u, p.state), 1)

    def test_accept_order_persists_all_and_clears_only_ai_poll_timestamps(self):
        x = Fixture()
        x.initialize()
        u = x.u
        weapons = types.SimpleNamespace(
            TABLE=ai.POLL_TABLE, COUNT=ai.POLL_COUNT, STRIDE=ai.POLL_STRIDE
        )
        table = bytes([0x5a]) * (weapons.COUNT * weapons.STRIDE)
        u.mem_write(weapons.TABLE, table)
        for p in c.PREFERENCES.values():
            put(u, p.state + 8, 1 - p.default)
        original = struct.pack('<25I', *range(25))
        u.mem_write(c.ORIGINAL_VALUES, original)
        x.call(options.SAVE)
        self.assertEqual(
            [r[1] for r in x.calls if r[0] == 'write'],
            ['ImprovedTargetSelection', 'UnlockedShotAssist', 'WristHeightFiring', 'WeaponTimedAI', 'ShowFPS', 'Original25']
        )
        self.assertEqual(x.saved, original)
        expected = bytearray(table)
        for i in range(weapons.COUNT):
            expected[i * weapons.STRIDE + 16:i * weapons.STRIDE + 20] = bytes(4)
        self.assertEqual(bytes(u.mem_read(weapons.TABLE, len(table))), expected)
        for p in c.PREFERENCES.values():
            self.assertEqual(get(u, p.state + 4), 1 - p.default)
        # Reaccepting the same AI preference must not repeatedly clear live polls.
        put(u, weapons.TABLE + 16, 123)
        x.call(options.SAVE)
        self.assertEqual(get(u, weapons.TABLE + 16), 123)

    def test_cancel_closes_every_checkbox_without_committing(self):
        x = Fixture()
        x.initialize()
        u = x.u
        for p in c.PREFERENCES.values():
            put(u, p.state + 8, 1 - p.default)
            put(u, p.state + 12, 1)
        put(u, c.WRIST.state + 16, 2)
        put(u, c.SHOT.state + 16, 3)
        x.call(shot.CLOSE)
        for p in c.PREFERENCES.values():
            self.assertEqual(get(u, p.state + 4), p.default)
            self.assertEqual(get(u, p.state + 12), 0)
        self.assertEqual(get(u, c.WRIST.state + 16), 0)
        self.assertEqual(get(u, c.SHOT.state + 16), 0)
        self.assertFalse([r for r in x.calls if r[0] == 'write'])

    def test_restore_reloads_checkboxes_but_preserves_mission_original_options(self):
        x = Fixture()
        x.initialize()
        u = x.u
        original = struct.pack('<25I', *range(25))
        u.mem_write(c.ORIGINAL_VALUES, original)
        for p in c.PREFERENCES.values():
            x.values[p.key] = 1 - p.default
        for a, b in preference_restore_writes(143):
            u.mem_write(a, b)
        self.assertEqual(get(u, c.AI.state + c.AI_READ_OFFSET), 0)
        self.assertEqual(get(u, c.FPS.state + c.FPS_READ_OFFSET), 0)
        x.initialize()
        x.call(options.FIRST)
        for p in c.PREFERENCES.values():
            self.assertEqual(get(u, p.state + 4), 1 - p.default)
        self.assertEqual(bytes(u.mem_read(c.ORIGINAL_VALUES, 100)), original)
        self.assertFalse([r for r in x.calls if r[:2] == ('read', 'Original25')])

    def test_launcher_restore_matches_authoring_contract_and_previous_bytes(self):
        for revision in (120, 133, 138, 142, 143):
            writes = preference_restore_writes(revision)
            self.assertEqual(
                [(a, len(b)) for a, b in writes[:-1]], list(c.restore_ranges(revision))
            )
            self.assertEqual(writes[-1], (c.ORIGINAL_LOADED, struct.pack('<I', 1)))
            # Independently listed restore instructions catch accidental changes to the shared ABI.
            before = bytearray([0x5a]) * 0x2000000
            actual = before[:]
            for a, n in ((0x1f77900, 512), (0x1e39c00, 512), (0x1fc2f00, 256), (0x1fcae00, 256)):
                before[a:a + n] = bytes(n)
            if revision >= 143:
                before[0x1d35800:0x1d35840] = bytes(64)
            before[0x1fc2f68:0x1fc2f6c] = struct.pack('<I', 1)
            for a, b in writes:
                actual[a:a + len(b)] = b
            self.assertEqual(actual, before)


if __name__ == '__main__':
    unittest.main()
