"""HUD provider isolation, offline installation, and executed coverage behavior."""
from pathlib import Path
import struct, sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import hud as h, hud_install as install
from patch_support import asm
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EFLAGS

MAP_SLOT = h.SLOTS + 384
MAP_CONTEXT = 0x1e46000
MAP_BUFFERS = ((0x1f00100, 480000), (0x1f78000, 128000), (0x1fa0000, 128000))
INPUTS = dict(
    map_payload=((0x1e44000, b'\xc3'), ),
    map_hooks=(
        (0x276ef8, asm(0x276ef8, 'jmp 0x1e45000')), (0x276fa6, asm(0x276fa6, 'call 0x1e45800;nop'))
    ),
    map_slot=MAP_SLOT,
    map_context=MAP_CONTEXT,
    map_buffers=MAP_BUFFERS
)


def fixture():
    ram = bytearray(0x2000000)
    for a, b in install.providers().items():
        ram[a:a + len(b)] = b
    return ram


class HudInstallTests(unittest.TestCase):

    def test_install_initializes_slots_and_all_guards_then_repeats_without_writes(self):
        ram = fixture()
        writes = []

        def write(a, b):
            writes.append((a, b))
            ram[a:a + len(b)] = b
        with patch.dict('sys.modules', {'build_inputs': None}), \
             patch('build_paths.source_path',side_effect=AssertionError('Source parsing')):
            result = install.install(write, lambda a, n: ram[a:a + n], **INPUTS)
        self.assertEqual(result['ranges'], [(a, a + len(b)) for a, b in writes])
        for i in range(3):
            self.assertEqual(
                struct.unpack_from('<3I', ram, h.SLOTS + i * 128 + 56),
                (h.BASES[i], h.REFS[i], h.MASKS[i])
            )
        self.assertEqual(install.validate_guards(lambda a, n: ram[a:a + n], MAP_BUFFERS), 24)
        writes.clear()
        self.assertTrue(
            install.install(write, lambda a, n: ram[a:a + n], **INPUTS)['already_installed']
        )
        self.assertEqual(writes, [])

    def test_late_guard_and_hook_corruption_fail_before_first_write(self):
        for a in (
            h.MASK - 1, MAP_BUFFERS[-1][0] + MAP_BUFFERS[-1][1] + 255, h.STATE + 0x5ff, h.WORLD + 8,
            0x2633f0
        ):
            with self.subTest(address=hex(a)):
                ram = fixture()
                ram[a] ^= 1
                writes = []
                with self.assertRaises(ValueError):
                    install.install(
                        lambda *args: writes.append(args), lambda a, n: ram[a:a + n], **INPUTS
                    )
                self.assertEqual(writes, [])

    def test_short_reads_missing_or_overlapping_map_providers_fail_before_writes(self):
        ram = fixture()
        for changes, short in (
            ({}, True), ({
                'map_hooks': ()
            }, False), ({
                'map_payload': ((h.WORLD, b'\xc3'), )
            }, False)
        ):
            writes = []
            with self.assertRaises(ValueError):
                install.install(
                    lambda *args: writes.append(args), lambda a, n: ram[a:a + n - int(short)],
                    **dict(INPUTS, **changes)
                )
            self.assertEqual(writes, [])

    def test_partially_installed_or_damaged_output_is_not_accepted(self):
        for corrupt_guard in (False, True):
            ram = fixture()
            install.install(
                lambda a, b: ram.__setitem__(slice(a, a + len(b)), b), lambda a, n: ram[a:a + n],
                **INPUTS
            )
            ram[h.MASK - 1 if corrupt_guard else h.TEXT + 4] ^= 1
            writes = []
            with self.assertRaises(ValueError):
                install.install(
                    lambda *args: writes.append(args), lambda a, n: ram[a:a + n], **INPUTS
                )
            self.assertEqual(writes, [])

    def test_final_compass_installation_validates_both_profiles_before_writing(self):
        ram = bytearray(0x2000000)
        for a, b in install.compass_predecessors():
            ram[a:a + len(b)] = b
        writes = []
        saved = bytes(ram)
        ram[h.COVER + 4] ^= 1
        with self.assertRaises(AssertionError):
            install.install_compass(lambda *x: writes.append(x), ram)
        self.assertEqual(writes, [])
        ram[:] = saved

        def write(a, b):
            writes.append((a, b))
            ram[a:a + len(b)] = b

        install.install_compass(write, ram)
        self.assertTrue(install.verify_compass(ram))
        self.assertEqual(install.compass_predecessor_view(ram), saved)
        writes.clear()
        self.assertTrue(install.install_compass(write, ram)['already_installed'])
        self.assertEqual(writes, [])

    def test_fast_compositor_reservation_and_retained_tail_are_validated(self):
        ram = bytearray(0x2000000)
        old = install.fast_predecessor()
        ram[h.COMPOSE:h.COMPOSE + len(old)] = old
        ram[install.FAST_END - 1] = 1
        writes = []
        with self.assertRaises(AssertionError):
            install.install_fast(lambda *x: writes.append(x), ram)
        self.assertEqual(writes, [])
        ram[install.FAST_END - 1] = 0
        saved = bytes(ram)

        def write(a, b):
            writes.append((a, b))
            ram[a:a + len(b)] = b

        install.install_fast(write, ram)
        self.assertTrue(install.verify_fast(ram))
        self.assertEqual(install.fast_predecessor_view(ram), saved)
        ram[h.COMPOSE + len(old) - 1] ^= 1
        writes.clear()
        with self.assertRaises(AssertionError):
            install.install_fast(write, ram)
        self.assertEqual(writes, [])


class HudCoverageTests(unittest.TestCase):

    def run_coverage(self, *, high=True, expanded=False, style=0, rect=None, owner=0x150000):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        rows = 400 if high else 200
        mask = h.MASK if high else 0x870000
        u.mem_write(mask, b'\xff' * (320 * rows))
        u.mem_write(mask - 16, b'Z' * 16)
        u.mem_write(mask + 320 * rows, b'Z' * 16)
        u.mem_write(0x389dec, struct.pack('<I', owner))
        u.mem_write(0x389de8, struct.pack('<I', owner))
        u.mem_write(owner + 0x18, struct.pack('<I', 0x2657a8))
        u.mem_write(owner + 8, struct.pack('<4h', *(rect or (3, rows - 2, 8, rows))))
        u.mem_write(0x38fbfe, bytes([expanded]))
        u.mem_write(0x38b9a2 if expanded else 0x38b9a5, bytes([style]))
        entry = 0x160000
        stack = 0x170000
        stop = 0x10000
        u.mem_write(entry, h.code(entry, h.coverage_source(high_rows=high)))
        u.mem_write(stack, struct.pack('<I', stop))
        u.reg_write(UC_X86_REG_ESP, stack)
        u.reg_write(UC_X86_REG_EFLAGS, 0x246)
        u.emu_start(entry, stop, count=100000)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), stack + 4)
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x246)
        self.assertEqual(bytes(u.mem_read(mask - 16, 16)), b'Z' * 16)
        self.assertEqual(bytes(u.mem_read(mask + 320 * rows, 16)), b'Z' * 16)
        return bytes(u.mem_read(mask, 320 * rows)), rows

    def test_compass_style_controls_black_coverage_in_both_row_profiles(self):
        for high in (False, True):
            for expanded in (False, True):
                for style in (0, 1):
                    with self.subTest(high=high, expanded=expanded, style=style):
                        mask, rows = self.run_coverage(high=high, expanded=expanded, style=style)
                        expected = bytearray(b'\xff' * (320 * rows))
                        if style == 0:
                            for row in (rows - 2, rows - 1):
                                expected[row * 320 + 3:row * 320 + 8] = bytes(5)
                        self.assertEqual(mask, bytes(expected))

    def test_invalid_or_empty_rectangles_never_write_coverage(self):
        for rect in (
            (-1, 0, 5, 2), (0, -1, 5, 2), (0, 0, 321, 2), (0, 0, 5, 401), (4, 2, 4, 3),
            (4, 3, 5, 3)
        ):
            mask, rows = self.run_coverage(rect=rect)
            self.assertEqual(mask, b'\xff' * (320 * rows))

    def test_missing_widget_owner_is_ignored_during_mode_transition(self):
        mask, rows = self.run_coverage(owner=0)
        self.assertEqual(mask, b'\xff' * (320 * rows))


if __name__ == '__main__':
    unittest.main()
