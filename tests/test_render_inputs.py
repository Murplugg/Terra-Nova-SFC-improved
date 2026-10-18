"""Check renderer inputs, compare operand bindings and execute relocated helpers."""
from dataclasses import FrozenInstanceError
import struct, unittest
from tests.test_render_views import image, Fixture, put, get, r, ENTRY, STOP, STACK
from features import render_inputs as inputs
from features.render_arena import Layout, BASE, SIZE
from patch_support import asm
from unicorn.x86_const import *


def binding(ram):
    return r.Integration(BASE).bind(lambda a, n: ram[a:a + n])


class RenderInputTests(unittest.TestCase):

    def test_bound_plan_matches_old_operand_scan_and_is_immutable(self):
        ram = image()
        layout = Layout(BASE)
        bound = binding(ram)
        old = []
        for new, (before, sites) in zip(layout.skyrows, r.weather.ROW_TABLES.values()):
            old.extend((a, new) for a in sites)
        old.append((0x2a7a1e, layout.skyrows[0] - 4))
        # Independent pre-extraction rule, retained only as an equality oracle.
        for a in (r.weather.SKY_D, r.weather.SKY_C):
            block = bytes(ram[a:a + 0x80])
            for before, new in ((0x9c84e4, layout.effect - 4), (600, 1200)):
                old.extend(
                    (a + n, new) for n in range(len(block) - 3)
                    if block[n:n + 4] == struct.pack('<I', before)
                )
        self.assertEqual(bound.edits, tuple(old))
        self.assertEqual(len(bound.edits), 24)
        self.assertEqual(bound.presenter, 0x1d19040)
        with self.assertRaises(FrozenInstanceError):
            bound.presenter = 0

    def test_explicit_bindings_emit_identical_integration_without_reading_an_image(self):
        ram = image()
        a = r.Integration(BASE)
        b = r.Integration(BASE)
        reads = []

        def read(address, size):
            reads.append((address, size))
            return ram[address:address + size]

        bound = b.bind(read)
        self.assertEqual(len(reads), 21)
        self.assertLess(sum(n for _, n in reads), 4096)
        a.build(ram)
        b.build(bindings=bound)
        self.assertEqual(a.writes, b.writes)
        self.assertEqual(len(a.writes), 76)
        with self.assertRaisesRegex(ValueError, 'either'):
            r.Integration(BASE).build(ram, bindings=bound)

    def test_presenter_must_be_unique_and_entirely_inside_its_search_region(self):
        for mode in ('missing', 'duplicate', 'straddles_end'):
            with self.subTest(mode=mode):
                ram = image()
                if mode != 'duplicate':
                    ram[0x1d19040:0x1d19045] = bytes(5)
                at = 0x1d19100 if mode == 'duplicate' else inputs.PRESENTER_END - 2
                if mode != 'missing':
                    ram[at:at + 5] = inputs.PRESENTER_STORE
                i = r.Integration(BASE)
                with self.assertRaisesRegex(ValueError, 'presenter store'):
                    i.build(ram)
                self.assertEqual(i.writes, [])

    def test_wrong_row_base_or_full_helper_rejected_before_generating_payloads(self):
        for address in (0x2a79f9, 0x2a7a1e, r.weather.SKY_D, r.weather.SKY_C + 1):
            with self.subTest(address=hex(address)):
                ram = image()
                ram[address] ^= 1
                i = r.Integration(BASE)
                with self.assertRaisesRegex(ValueError, 'predecessor mismatch'):
                    i.build(ram)
                self.assertEqual(i.writes, [])

    def test_truncated_and_out_of_bounds_providers_rejected(self):
        ram = image()
        i = r.Integration(BASE)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            i.bind(lambda a, n: ram[a:a + n - 1])
        rows = list(r.weather.ROW_TABLES.values())
        rows[0] = (rows[0][0], (0x2000000, ))
        with self.assertRaisesRegex(ValueError, 'outside'):
            inputs.bind(
                lambda a, n: ram[a:a + n],
                i,
                rows, ((r.weather.SKY_D, 'edx'), (r.weather.SKY_C, 'ecx')),
                old_effect=r.weather.EFFECT,
                stats=r.weather.STATS
            )

    def test_bad_provider_count_order_and_overlaps_rejected(self):
        ram = image()
        layout = Layout(BASE)
        rows = list(r.weather.ROW_TABLES.values())
        helpers = ((r.weather.SKY_D, 'edx'), (r.weather.SKY_C, 'ecx'))

        def bind(groups, entries):
            return inputs.bind(
                lambda a, n: ram[a:a + n],
                layout,
                groups,
                entries,
                old_effect=r.weather.EFFECT,
                stats=r.weather.STATS
            )

        with self.assertRaisesRegex(ValueError, 'six'):
            bind(rows[:-1], helpers)
        with self.assertRaisesRegex(ValueError, 'in order'):
            bind(rows, helpers[::-1])
        duplicate = rows[:]
        duplicate[0] = (rows[0][0], rows[0][1] + rows[0][1][:1])
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            bind(duplicate, helpers)
        with self.assertRaisesRegex(ValueError, 'Empty'):
            bind([(rows[0][0], ())] + rows[1:], helpers)

    def test_relocated_sky_rows_obey_height_cap_and_preserve_registers_flags(self):
        ram = image()
        bound = binding(ram)
        layout = Layout(BASE)
        for a, v in bound.edits:
            struct.pack_into('<I', ram, a, v)
        for address, index in (
            (r.weather.SKY_D, UC_X86_REG_EDX), (r.weather.SKY_C, UC_X86_REG_ECX)
        ):
            for height, offset, hit in (
                (960, 0, False), (960, 4, True), (960, 3840, True), (960, 3844, False),
                (1400, 4800, True), (1400, 4804, False)
            ):
                with self.subTest(address=hex(address), height=height, offset=offset):
                    x = Fixture()
                    u = x.u
                    u.mem_write(address, bytes(ram[address:address + 0x80]))
                    put(u, 0x44b1a0, 0x150000)
                    u.mem_write(0x15000a, struct.pack('<H', height))
                    put(u, STACK, STOP)
                    u.reg_write(UC_X86_REG_ESP, STACK)
                    u.reg_write(UC_X86_REG_EFLAGS, 0x246)
                    u.reg_write(UC_X86_REG_EAX, 0x12345678)
                    u.reg_write(UC_X86_REG_EBX, 0x999)
                    u.reg_write(UC_X86_REG_ESI, 0x888)
                    u.reg_write(index, offset)
                    u.emu_start(address, STOP, count=1000)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
                    self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x999)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESI), 0x888)
                    self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x246)
                    self.assertEqual(get(u, r.weather.STATS + 12), int(not hit))
                    if hit:
                        self.assertEqual(get(u, layout.effect + offset - 4), 0x12345678)
                    else:
                        self.assertEqual(bytes(u.mem_read(layout.effect, 4800)), bytes(4800))

    def test_presenter_selects_completed_native_frame_only_for_matching_mode(self):
        i = r.Integration(BASE)
        i.build(image())
        source = i.sources['present']
        for mismatch in (None, 'mode', 'logical', 'ready'):
            with self.subTest(mismatch=mismatch):
                x = Fixture()
                u = x.u
                u.mem_write(0x1d19045, b'\xc3')
                put(u, 0x1d0b000, 0x103)
                put(u, i.state + 24, 1)
                put(u, 0x1d1d010, 800)
                put(u, 0x1d1d014, 600)
                if mismatch == 'mode':
                    put(u, 0x1d0b000, 0x101)
                if mismatch == 'logical':
                    put(u, 0x446f80, 0x00c80140)
                if mismatch == 'ready':
                    put(u, i.state + 24, 0)
                x.run(source, eax=0xe0000000, edx=800)
                self.assertEqual(get(u, 0x1d1d00c), i.screen if mismatch is None else 0xe0000000)
                self.assertEqual(
                    (get(u, 0x1d1d010), get(u, 0x1d1d014)), (1280, 960) if mismatch is None else
                    (800, 600)
                )
                self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x202)


if __name__ == '__main__':
    unittest.main()
