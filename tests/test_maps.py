"""Map provider guards and executed cache, palette and centering behavior."""
from pathlib import Path
import sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import maps as m
from tests.test_render_views import Fixture, put, word, get, CONTROL, OWNER, STACK, STOP
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *


class MapProviderTests(unittest.TestCase):

    def test_overlay_aspect_is_scoped_and_preserves_original_call_state(self):
        # Model the original overlay boundary rather than ship game bytes.
        # A mode reset and a nested view can leave different incoming aspects;
        # drawing a map must repair its rings without leaking that repair.
        x = Fixture()
        u = x.u
        seen = []
        u.mem_write(m.ORIGINAL, dict(m.view_bodies())[m.ORIGINAL])
        u.mem_write(0x276efd, m.code(0x276efd, '''
            mov eax, 0x12345678
            mov edx, 0x87654321
            xor ebx, ebx
            pop ebp
            pop edi
            pop esi
            pop ecx
            pop ebx
            ret
        '''))

        def original(u, a, n, _):
            seen.append((get(u, 0x44b1ac), u.reg_read(UC_X86_REG_EFLAGS)))
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), CONTROL)
            self.assertEqual(u.reg_read(UC_X86_REG_EDX), 123)

        u.hook_add(UC_HOOK_CODE, original, begin=0x276efd, end=0x276efd)
        for mode in (0x01900140, 0x00c80140):
            for aspect in (0x9999, 0x10000, 0x13333):
                for flags in (0x202, 0x247):
                    put(u, 0x446f80, mode)
                    put(u, 0x44b1ac, aspect)
                    put(u, STACK, STOP)
                    u.reg_write(UC_X86_REG_ESP, STACK)
                    u.reg_write(UC_X86_REG_EFLAGS, flags)
                    u.reg_write(UC_X86_REG_EAX, CONTROL)
                    u.reg_write(UC_X86_REG_EDX, 123)
                    saved = (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESI,
                             UC_X86_REG_EDI, UC_X86_REG_EBP)
                    for i, reg in enumerate(saved):
                        u.reg_write(reg, 100 + i)
                    u.emu_start(m.ORIGINAL, STOP, count=1000)
                    self.assertEqual(seen[-1], (0x9999 if mode == 0x01900140 else aspect, flags))
                    self.assertEqual(get(u, 0x44b1ac), aspect)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP), STOP)
                    self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x12345678)
                    self.assertEqual(u.reg_read(UC_X86_REG_EDX), 0x87654321)
                    self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x246)
                    self.assertEqual([u.reg_read(reg) for reg in saved], list(range(100, 105)))

    def test_original_terrain_requires_complete_verified_input(self):
        for data in (b'', b'\0' * (m.ORIGINAL_END - m.ORIGINAL_START), b'\0' * 10):
            with self.assertRaises(ValueError):
                m.terrain_code(lambda a, n: data)

    def test_persistence_install_validates_all_inputs_and_repeats_without_writes(self):
        ram = bytearray(0x2000000)
        plan = m.persistence_plan()
        writes = []
        for a, old, new in plan:
            ram[a:a + len(old)] = old
            ram[a - 1] = 0x77
            ram[a + len(old)] = 0x88
        ram[m.SLOT:m.SLOT + 4] = b'live'

        def write(a, b):
            writes.append((a, b))
            ram[a:a + len(b)] = b
        with patch.dict('sys.modules', {'build_inputs': None}), \
             patch('build_paths.source_path',side_effect=AssertionError('Source parsing')):
            result = m.install_persistence(write, lambda a, n: ram[a:a + n])
        self.assertEqual(result['ranges'], [(a, a + len(b)) for a, b in writes])
        self.assertEqual(ram[m.SLOT:m.SLOT + 4], bytes(4))
        for a, old, new in plan:
            self.assertEqual(ram[a:a + len(new)], new)
            self.assertEqual((ram[a - 1], ram[a + len(new)]), (0x77, 0x88))
        writes.clear()
        self.assertTrue(
            m.install_persistence(write, lambda a, n: ram[a:a + n])['already_installed']
        )
        self.assertEqual(writes, [])

    def test_partial_corrupt_short_and_overlapping_providers_fail_before_writes(self):
        plan = m.persistence_plan()
        for problem in ('partial', 'corrupt', 'short', 'overlap'):
            with self.subTest(problem=problem):
                ram = bytearray(0x2000000)
                writes = []
                for a, old, new in plan:
                    ram[a:a + len(old)] = old
                if problem == 'partial':
                    a, old, new = plan[0]
                    ram[a:a + len(new)] = new
                if problem == 'corrupt':
                    ram[plan[-1][0] + 3] ^= 1
                extras = ((m.ENTRY, b'x', b'y'), ) if problem == 'overlap' else ()
                with self.assertRaises(ValueError):
                    m.install_persistence(
                        lambda *x: writes.append(x),
                        lambda a, n: ram[a:a + n - int(problem == 'short')],
                        extras=extras
                    )
                self.assertEqual(writes, [])

    def test_logical_map_cache_preserves_original_markers_and_rebuilds_on_changes(self):
        x = Fixture()
        u = x.u
        x.prepare_map()
        source = m.entry_source(m.SYMBOLS)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.render_state[-1], (m.PIXELS, 92, 43))
        self.assertEqual(get(u, m.SLOT + 12), OWNER)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(m.TERRAIN), 1)
        for count, (address, value) in enumerate(((CONTROL, 18), (0x359708, 23), (0x35ade0, 1)), 2):
            put(u, address, value)
            x.run(source, eax=CONTROL)
            self.assertEqual(x.calls.count(m.TERRAIN), count)
        word(u, OWNER + 0x22 + 8, 38)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(m.TERRAIN), 5)
        self.assertEqual(x.calls.count(m.ORIGINAL), 6)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), CONTROL)

    def test_palette_fix_only_remaps_dark_mission_30_colors_and_preserves_flags(self):
        x = Fixture()
        u = x.u
        body = dict(m.palette_bodies())[m.MAPCOLOR]
        u.mem_write(m.MAPCOLOR, body)
        for mission in (22, 23, 24):
            put(u, 0x359708, mission)
            for color in range(256):
                u.mem_write(CONTROL, bytes([color]))
                put(u, STACK, STOP)
                u.reg_write(UC_X86_REG_ESP, STACK)
                u.reg_write(UC_X86_REG_ECX, CONTROL)
                u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                u.emu_start(m.MAPCOLOR, STOP, count=100)
                expected = 17 if mission == 23 and 12 <= color <= 16 else color
                self.assertEqual(bytes(u.mem_read(STACK + 0x48, 1)), bytes([expected]))
                self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_center_uses_original_clamp_and_preserves_minimap_call_and_registers(self):
        x = Fixture()
        u = x.u
        calls = []
        widget = 0x150000

        def boundary(u, a, n, _):
            calls.append(
                (
                    a, u.reg_read(UC_X86_REG_EAX), u.reg_read(UC_X86_REG_EDX),
                    u.reg_read(UC_X86_REG_EBX)
                )
            )
            if a == 0x276c4c:
                put(u, widget, 100)
                put(u, widget + 4, 200)

        for a in (0x26485c, 0x276c4c):
            u.mem_write(a, b'\xc3')
            u.hook_add(UC_HOOK_CODE, boundary, begin=a, end=a)
        u.mem_write(m.CENTER, dict(m.center_bodies())[m.CENTER])
        word(u, 0x441350, 3)
        put(u, 3 * 37 + 0x3c324f, 1234)
        put(u, 3 * 37 + 0x3c3253, 5678)
        put(u, widget + 10, 10)
        word(u, widget + 30, 40)
        word(u, widget + 32, 32)
        u.mem_write(0x35a544, b'\x01')
        for mission, pointer in ((0, widget), (0x2e, widget), (0, 0)):
            calls.clear()
            put(u, 0x359708, mission)
            put(u, 0x38fb20, pointer)
            put(u, STACK, STOP)
            put(u, 0x38fa88, 0)
            put(u, 0x38fa8c, 0)
            u.reg_write(UC_X86_REG_ESP, STACK)
            u.reg_write(UC_X86_REG_EAX, 999)
            u.reg_write(UC_X86_REG_EDX, 888)
            u.reg_write(UC_X86_REG_EBX, 777)
            u.reg_write(UC_X86_REG_EFLAGS, 0x247)
            u.emu_start(m.CENTER, STOP, count=1000)
            self.assertEqual(calls[0][0], 0x26485c)
            if mission == 0 and pointer:
                self.assertEqual(calls[1], (0x276c4c, widget, 1234, 5678))
                self.assertEqual((get(u, 0x38fa88), get(u, 0x38fa8c)), (300, 280))
            else:
                self.assertEqual(len(calls), 1)
                self.assertEqual((get(u, 0x38fa88), get(u, 0x38fa8c)), (0, 0))
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
            self.assertEqual(
                [u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EBX)],
                [999, 888, 777]
            )


if __name__ == '__main__':
    unittest.main()
