"""Execute renderer startup/preview x86 without original game files or Windows.

WinAPI and original window construction are modeled; copies, guards, cache
resets, preview resampling, registers and stack behavior execute for real.
"""
from pathlib import Path
import struct, sys, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import render_arena as r
from patch_support import asm
from tnova import state_core
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.x86_const import *

STACK = 0x1700000
STOP = 0x10000
API = 0x1800000
NAMES = ('VirtualAlloc', 'LoadLibraryA', 'GetProcAddress')
REGS = (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
    UC_X86_REG_EBP
)


def put(u, a, n):
    u.mem_write(a, struct.pack('<I', n & 0xffffffff))


def get(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def string(u, a):
    return bytes(u.mem_read(a, 64)).split(b'\0')[0].decode('ascii')


def plan():
    i = r.Layout(r.BASE)
    i.writes = [
        (0x12000, b'\x90'), (i.cols, b'fixture table\0'), (r.BASE + 0xc00000, b'\xc3\x90\x90')
    ]
    return i


class Fixture:

    def __init__(self):
        self.i = plan()
        self.imports = {name: 0x300000 + 4 * n for n, name in enumerate(NAMES)}
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_map(r.BASE, r.SIZE)
        u.mem_map(0xe0000000, 0x800000)
        self.calls = []
        self.alloc_result = r.BASE
        self.library = 1
        self.missing = None
        self.adjust = 1
        self.interrupts = []
        old = asm(r.SITE, 'push 0x12345678')
        self.pieces = r.bodies(self.i, lambda a, n: old[:n], self.imports)
        for a, b in self.pieces:
            u.mem_write(a, b)
        # Original constructor consumes its displaced argument, returns a known
        # EAX and preserves the remaining registers. Startup must keep that ABI.
        u.mem_write(r.SITE + 5, asm(r.SITE + 5, 'pop eax;ret'))
        for n, name in enumerate(NAMES):
            put(u, self.imports[name], API + 16 * n)
        for n in range(6):
            address = API + 16 * n
            u.mem_write(address, b'\xc3')
            u.hook_add(UC_HOOK_CODE, self.api, begin=address, end=address)
        u.hook_add(UC_HOOK_INTR, self.interrupt)
        put(u, 0x1d1d000, 0x999)

    def interrupt(self, u, n, _):
        self.interrupts.append((n, u.reg_read(UC_X86_REG_EAX)))
        u.emu_stop()

    def api(self, u, a, n, _):
        sp = u.reg_read(UC_X86_REG_ESP)
        arg = lambda i: get(u, sp + 4 + i * 4)
        if a == API:
            args = tuple(arg(i) for i in range(4))
            self.calls.append(('alloc', args))
            pops = 16
            result = self.alloc_result
        elif a == API + 16:
            self.calls.append(('library', string(u, arg(0))))
            pops = 4
            result = self.library
        elif a == API + 32:
            name = string(u, arg(1))
            self.calls.append(('resolve', name))
            result = 0 if name == self.missing else {
                'GetDpiForWindow': API + 48,
                'AdjustWindowRectExForDpi': API + 64,
                'SetWindowPos': API + 80
            }[name]
            pops = 8
        elif a == API + 48:
            self.calls.append(('dpi', arg(0)))
            pops = 4
            result = 144
        elif a == API + 64:
            self.calls.append(('adjust', tuple(arg(i) for i in range(1, 5))))
            self.rect = tuple(get(u, arg(0) + 4 * i) for i in range(4))
            for n, v in enumerate((-8, -31, r.W + 8, r.H + 8)):
                put(u, arg(0) + 4 * n, v)
            pops = 20
            result = self.adjust
        else:
            self.calls.append(('position', tuple(arg(i) for i in range(7))))
            pops = 28
            result = 1
        u.reg_write(UC_X86_REG_EAX, result)
        # Model volatile register clobbering too, as real Windows calls may do.
        u.reg_write(UC_X86_REG_ECX, 0xcafebabe)
        u.reg_write(UC_X86_REG_EDX, 0xdeadbeef)
        u.reg_write(UC_X86_REG_EIP, get(u, sp))
        u.reg_write(UC_X86_REG_ESP, sp + 4 + pops)

    def call(self, address=r.CODE):
        for n, reg in enumerate(REGS):
            self.u.reg_write(reg, 0x700 + n)
        self.u.reg_write(UC_X86_REG_EFLAGS, 0x602)  # initial DF deliberately set
        put(self.u, STACK, STOP)
        self.u.reg_write(UC_X86_REG_ESP, STACK)
        self.u.emu_start(address, STOP, count=30000000)
        if not self.interrupts:
            assert self.u.reg_read(UC_X86_REG_EIP) == STOP
            assert self.u.reg_read(UC_X86_REG_ESP) == STACK + 4


class RenderArenaTests(unittest.TestCase):

    def test_layout_matches_snapshot_abi_and_guards_do_not_overlap(self):
        i = plan()
        r.validate(i, {n: 0x300000 + 4 * j for j, n in enumerate(NAMES)})
        self.assertEqual(r.BASE, state_core.ARENA)
        self.assertEqual(r.SIZE, 32 * 1024 * 1024)
        self.assertEqual(len(i.guard_edges()), 58)
        self.assertEqual(r.MARKER, i.state + 124)
        self.assertEqual(
            (i.pixels, i.reflection, i.frame, i.screen, i.map),
            (0x68100000, 0x68300000, 0x68500000, 0x68700000, 0x68900000)
        )

    def test_bootstrap_copies_payload_sets_guards_resets_only_declared_caches(self):
        x = Fixture()
        u = x.u
        i = x.i
        # Windows allocations are zero initialized. Low process caches may be
        # inherited from the checkpoint image and must be invalidated explicitly.
        reset = ((0x9aa0ec, 4), (0x9af5e8, 4), (0x1e3c580, 4), (0x1e46140, 40))
        for a, n in reset:
            u.mem_write(a - 4, b'Z' * (n + 8))
        u.mem_write(i.map_slots, b'Z' * 2048)
        x.call(r.SITE)
        self.assertEqual(bytes(u.mem_read(i.map_slots, 2048)), bytes(2048))
        self.assertEqual(x.calls[0], ('alloc', (r.BASE, r.SIZE, 0x3000, 0x40)))
        for a, b in i.writes:
            self.assertEqual(bytes(u.mem_read(a, len(b))), b)
        for g in i.guard_edges():
            self.assertEqual(bytes(u.mem_read(g, 256)), b'\xa5' * 256)
        for a, n in reset:
            self.assertEqual(bytes(u.mem_read(a, n)), bytes(n))
            self.assertEqual(bytes(u.mem_read(a - 4, 4)), b'Z' * 4)
            self.assertEqual(bytes(u.mem_read(a + n, 4)), b'Z' * 4)
        self.assertEqual(bytes(u.mem_read(i.terrain_shading,16)),
                         struct.pack('<4I',0,0,0xfffff000,1))
        self.assertEqual(bytes(u.mem_read(i.object_fog,15*0x1800)),bytes(15*0x1800))
        self.assertEqual(get(u, i.state), 1)
        self.assertEqual(get(u, i.state + 24), 0)
        self.assertEqual(get(u, r.MARKER), r.MAGIC)
        self.assertEqual(x.rect, (0, 0, 1280, 960))
        self.assertIn(('adjust', (0x10cf0000, 0, 0, 144)), x.calls)
        self.assertIn(('position', (0x999, 0, 15, 15, 1296, 999, 0x14)), x.calls)
        self.assertEqual(u.reg_read(REGS[0]), 0x12345678)
        for n, reg in enumerate(REGS[1:], 1):
            self.assertEqual(u.reg_read(reg), 0x700 + n)
        self.assertTrue(u.reg_read(UC_X86_REG_EFLAGS) & 0x400)

    def test_allocation_failure_exits_before_copy_or_original_constructor(self):
        for result in (0, r.BASE + 0x1000000):
            with self.subTest(result=result):
                x = Fixture()
                x.alloc_result = result
                x.call()
                self.assertEqual(x.interrupts, [(0x21, 0xff00)])
                self.assertEqual(len(x.calls), 1)
                self.assertEqual(get(x.u, r.MARKER), 0)
                self.assertEqual(bytes(x.u.mem_read(x.i.cols, 14)), bytes(14))

    def test_optional_dpi_api_failures_leave_valid_initialized_renderer(self):
        for failure in (
            'library', 'GetDpiForWindow', 'AdjustWindowRectExForDpi', 'adjust', 'SetWindowPos'
        ):
            with self.subTest(failure=failure):
                x = Fixture()
                if failure == 'library':
                    x.library = 0
                elif failure == 'adjust':
                    x.adjust = 0
                else:
                    x.missing = failure
                x.call()
                self.assertEqual(get(x.u, r.MARKER), r.MAGIC)
                self.assertFalse(any(call[0] == 'position' for call in x.calls))
                self.assertEqual(x.u.reg_read(UC_X86_REG_EAX), 0x12345678)

    def test_preview_requires_all_three_old_display_identifiers(self):
        expected = ((0x1d0b000, 0x103), (0x1d0b004, 0xe0000000), (0x446f80, 0x01900140))
        for wrong in range(3):
            x = Fixture()
            for j, (a, v) in enumerate(expected):
                put(x.u, a, v if j != wrong else v + 1)
            x.u.mem_write(x.i.frame, b'frame')
            x.u.mem_write(x.i.screen, b'screen')
            x.call(r.CODE + 0xa00)
            self.assertEqual(get(x.u, x.i.state + 24), 0)
            self.assertEqual(bytes(x.u.mem_read(x.i.frame, 5)), b'frame')
            self.assertEqual(bytes(x.u.mem_read(x.i.screen, 6)), b'screen')

    def test_old_checkpoint_preview_scales_both_buffers_and_stays_within_frame(self):
        x = Fixture()
        u = x.u
        i = x.i
        for a, v in ((0x1d0b000, 0x103), (0x1d0b004, 0xe0000000), (0x446f80, 0x01900140)):
            put(u, a, v)
        old = bytes((x * 7 + y * 13) & 255 for y in range(600) for x in range(800))
        u.mem_write(0xe0000000, old)
        for a in (i.frame, i.screen):
            u.mem_write(a - 1, b'Z')
            u.mem_write(a + r.W * r.H, b'Z')
        x.call()
        expected = b''.join(
            bytes(old[(y * 5 // 8) * 800 + x * 5 // 8] for x in range(r.W)) for y in range(r.H)
        )
        for a in (i.frame, i.screen):
            self.assertEqual(bytes(u.mem_read(a, len(expected))), expected)
            # The pixel before the buffer is its guard, initialized by startup.
            self.assertEqual(bytes(u.mem_read(a - 1, 1)), b'\xa5')
            self.assertEqual(bytes(u.mem_read(a + len(expected), 1)), b'Z')
        self.assertEqual(get(u, i.state + 24), 1)

    def test_rejects_bad_external_bounds_guards_state_and_overlapping_payloads(self):
        for a, b in (
            (r.BASE + r.SIZE - 1, b'bad'), (r.BASE + 0x100000 - 1, b'bad'),
            (r.BASE + 0xb0007c, b'bad'), (r.BASE + 0xb01001, b'bad'), (1, b'bad')
        ):
            with self.subTest(address=hex(a)):
                x = plan()
                x.writes.append((a, b))
                with self.assertRaises(ValueError):
                    r.bodies(x, lambda a, n: b'\x68' + bytes(4), {n: 0x300000 for n in NAMES})

    def test_rejects_changed_layout_missing_import_or_invalid_displaced_instruction(self):
        x = plan()
        imports = {n: 0x300000 for n in NAMES}
        x.frame += 4
        with self.assertRaisesRegex(ValueError, 'snapshot ABI'):
            r.bodies(x, None, imports)
        with self.assertRaisesRegex(ValueError, 'import'):
            r.bodies(plan(), None, {})
        for old in (b'\x68', b'\x90' * 5):
            with self.assertRaisesRegex(ValueError, 'PUSH imm32'):
                r.bodies(plan(), lambda a, n: old, imports)

    def test_exact_snapshot_restore_invalidates_identity_without_cold_resetting_frames(self):
        x = Fixture()
        x.call()
        u = x.u
        i = x.i
        # Captured arena replaces the freshly initialized one before this reset.
        # Populate values that cold initialization would clear, including cached
        # presenter identity. Exact restore must preserve them.
        for a, v in (
            (i.state, 0), (i.state + 24, 1), (0x9aa0ec, 7), (0x9af5e8, 8), (0x1e3c580, 9),
            (0x1e46140, 10)
        ):
            put(u, a, v)
        u.mem_write(i.frame, b'captured frame')
        u.mem_write(i.screen, b'captured screen')
        before = bytes(u.mem_read(r.BASE, r.SIZE))
        code = state_core.render_restore_source()
        u.mem_write(0x13000, asm(0x13000, code + 'ret;'))
        x.call(0x13000)
        expected = bytearray(before)
        struct.pack_into('<I', expected, i.state - r.BASE, 1)
        self.assertEqual(bytes(u.mem_read(r.BASE, r.SIZE)), bytes(expected))
        self.assertEqual(get(u, 0x9aa0ec), 1)
        self.assertEqual(get(u, 0x9af5e8), 0)
        self.assertEqual(get(u, 0x1e3c580), 9)
        self.assertEqual(get(u, 0x1e46140), 10)

    def test_launcher_restore_source_preserves_previous_emitted_instructions(self):
        self.assertEqual(
            state_core.render_restore_values(),
            ((0x9aa0ec, 1), (r.BASE + 0xb00000, 1), (0x9af5e8, 0))
        )
        original = 'mov dword ptr [0x9aa0ec],1;mov dword ptr [0x68b00000],1;mov dword ptr [0x9af5e8],0;'
        self.assertEqual(
            asm(0x1820000, state_core.render_restore_source()), asm(0x1820000, original)
        )


if __name__ == '__main__':
    unittest.main()
