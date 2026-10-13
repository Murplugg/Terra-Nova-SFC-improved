"""Check foundation ownership, navigation, target projection and cursor bounds.

Manifest checks reject changed fingerprints, missing/duplicate spans and
overlapping ownership. Reversing descriptors verifies that ordering selects no
behavior. Synthetic x86 fixtures model original allocator/drawing calls; signed
coordinate and pixel expectations are independent calculations. They protect
state restoration and bounds, without simulating whole missions or Windows.
"""
import json, struct, sys, tempfile, unittest
from tests import with_original_code
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from foundation_recipes import GENERATORS, navigation, allocation_guard, target_bounds
import foundation_cursor as cursor
from patch_inventory import recipe_rows, inventory
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EFLAGS, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_ESI

KIT = Path(__file__).resolve().parents[1] / 'engine'


class FoundationRecipeTests(unittest.TestCase):

    def fixture(self):
        rows = json.loads((KIT / 'recipes/foundation.json').read_text())
        return [r for r in rows if r['recipe'] == 'display-state']

    def resolve(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recipes.json'
            path.write_text(json.dumps(rows))
            return recipe_rows(path)

    @with_original_code
    def test_all_reviewed_groups_match_hash_only_descriptors(self):
        rows = recipe_rows()
        generated = [r for r in rows if 'source' in r]
        self.assertEqual(len(rows), 121)
        self.assertEqual(len(generated), 121)
        self.assertEqual(sum(len(bytes.fromhex(r['bytes'])) for r in generated), 11142)
        self.assertEqual({r['recipe'] for r in generated}, set(GENERATORS))
        sky = [r for r in rows if r['recipe'] == 'sky-spans']
        self.assertEqual(len(sky), 4)
        self.assertEqual({r['recipe'] for r in sky}, {'sky-spans'})
        raw = json.loads((KIT / 'recipes/foundation.json').read_text())
        self.assertTrue(all('bytes' not in r for r in raw if 'source' in r))

    def test_changed_hash_size_address_or_source_rejected(self):
        for key, value in [
            ('sha256', '0' * 64), ('size', 999), ('address', 123), ('source', '../private.py'),
            ('recipe', 'not-known')
        ]:
            rows = self.fixture()
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.resolve(rows)

    def test_incomplete_duplicate_and_mixed_groups_rejected(self):
        rows = self.fixture()
        for bad in (
            rows[:-1], rows + [rows[0]],
            rows + [dict(recipe='display-state', address=10, bytes='00')]
        ):
            with self.assertRaises(ValueError):
                self.resolve(bad)
        spans = allocation_guard()
        with patch.dict(GENERATORS, {'display-state': lambda: spans + [spans[0]]}):
            with self.assertRaisesRegex(ValueError, 'Duplicate generated'):
                self.resolve(rows)

    def test_overlapping_spans_are_rejected_even_when_bytes_agree(self):
        for address, data in ((0x1000, '0102'), (0x1001, '02'), (0x1001, 'ff')):
            rows = [
                dict(recipe='first', address=0x1000, bytes='0102'),
                dict(recipe='second', address=address, bytes=data)
            ]
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'plan.json'
                path.write_text(json.dumps(rows))
                with self.assertRaisesRegex(ValueError, 'Foundation overlap'):
                    inventory(path)

    @with_original_code
    def test_complete_plan_is_independent_of_descriptor_order(self):
        rows = json.loads((KIT / 'recipes/foundation.json').read_text())
        expected = inventory()[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(list(reversed(rows))))
            self.assertEqual(inventory(path)[0], expected)

    def test_literal_only_manifest_does_not_call_generators(self):
        rows = [dict(recipe='original', address=1, bytes='abc0')]

        def fail():
            self.fail('Generator used for unrelated literal rows')

        with patch.dict(GENERATORS, {k: fail for k in GENERATORS}):
            self.assertEqual(self.resolve(rows), rows)

    def machine(self, spans):
        uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(0, 0xa00000)
        for a, data in spans:
            uc.mem_write(a, data)
        uc.reg_write(UC_X86_REG_ESP, 0x800000)
        uc.mem_write(0x800000, struct.pack('<I', 0x1000))
        return uc

    def test_navigation_refresh_signed_coordinates_and_empty_context(self):
        for present in (False, True):
            uc = self.machine(navigation())
            write = lambda a, v: uc.mem_write(a, struct.pack('<I', v & 0xffffffff))
            write(0x389dfc, 0x700000)
            uc.mem_write(0x700021, b'\x02')
            uc.mem_write(0x700008, struct.pack('<hh', 10, 20))
            write(0x38fc20 + 64, 0x710000 if present else 0)
            write(0x710000, 2 * 65536)
            write(0x710004, 65536)
            write(0x71000e, 2 * 65536)
            write(0x38fff0, int(9.5 * 65536))
            write(0x38fff4, int(-3.5 * 65536))
            uc.mem_write(0x35a544, b'\x01')
            write(0x390300, 123)
            write(0x390304, 456)
            uc.reg_write(UC_X86_REG_EAX, 0x12345678)
            uc.reg_write(UC_X86_REG_EDI, 0x76543210)
            uc.reg_write(UC_X86_REG_EFLAGS, 0x247)
            uc.emu_start(0x9b22e8, 0x1000, count=500)
            self.assertEqual(
                struct.unpack('<II', uc.mem_read(0x390300, 8)), (25, 2) if present else (123, 456)
            )
            self.assertEqual(int.from_bytes(uc.mem_read(0x9b2ae8, 4), 'little'), int(present))
            self.assertEqual(uc.reg_read(UC_X86_REG_EAX), 0x12345678)
            self.assertEqual(uc.reg_read(UC_X86_REG_EDI), 0x76543210)
            self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_allocation_guard_rearms_only_after_success_and_preserves_flags(self):
        for result in (0, 0x700000):
            uc = self.machine(allocation_guard())
            uc.mem_write(0x35f4a4, struct.pack('<I', 0x1100))
            # A model allocator returns EAX and sets carry. The wrapper preserves both.
            uc.mem_write(0x1100, b'\xb8' + struct.pack('<I', result) + b'\xf9\xc3')
            uc.mem_write(0x9aa1e8, struct.pack('<I', 0x778899))
            uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
            uc.emu_start(0x9b40e8, 0x1000, count=100)
            self.assertEqual(uc.reg_read(UC_X86_REG_EAX), result)
            self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x203)
            self.assertEqual(
                int.from_bytes(uc.mem_read(0x9aa1e8, 4), 'little'), 0 if result else 0x778899
            )

    def test_cursor_profiles_and_generated_call_bindings_are_checked(self):
        for kwargs in ({'cached': True}, {'outlined': True}, {'buffered': True, 'outlined': True}):
            with self.assertRaises(ValueError):
                cursor.compositor_source(**kwargs)
        with self.assertRaises(ValueError):
            cursor.redirected_slot(0x1000, b'\xc3', 0x2000)
        body = b'\x90' * 12
        self.assertEqual(
            cursor.redirected_slot(0x1000, body, 0x2000),
            cursor.branch(0x1000, 0x2000) + body[5:]
        )

    def test_target_bounds_signed_floor_preserves_object_id_and_neighbors(self):
        uc = self.machine(target_bounds())
        for edges in ((220, 186, 246, 204), (-9, -7, 745, 302), (-32768, -32768, 32767, 32767)):
            uc.mem_write(0x710000, b'AB' + struct.pack('<4hH', *edges, 0xbeef) + b'CD')
            uc.reg_write(UC_X86_REG_ESI, 0x710002)
            uc.reg_write(UC_X86_REG_ESP, 0x800000)
            uc.emu_start(0x9b32e8, 0x1000, count=200)
            expected = (edges[0] * 2 // 5, edges[1] // 3, edges[2] * 2 // 5, edges[3] // 3)
            self.assertEqual(
                bytes(uc.mem_read(0x710000, 14)),
                b'AB' + struct.pack('<4hH', *expected, 0xbeef) + b'CD'
            )

    def test_target_world_restores_projection_and_bound_queue_access(self):
        cases = (
            (0x38fb24, 0x6b, 320, 200, 1), (0x38fb24, 0x6b, 320, 200, 64),
            (0x38fb24, 0x6b, 320, 200, 65), (0x38fb24, 0x6b, 320, 200, 0),
            (0x38fb24, 0x69, 320, 200, 1), (0x38fb24, 0x6b, 640, 200, 1),
            (0x38fb24, 0x6b, 320, 400, 1), (0x38fc24, 0x6b, 320, 200, 1)
        )
        for context, mode, width, height, count in cases:
            with self.subTest(context=context, mode=mode, width=width, height=height, count=count):
                uc = self.machine(target_bounds())
                write = lambda a, v: uc.mem_write(a, struct.pack('<I', v))
                # Record the aspect seen by the old world call without changing its outputs.
                uc.mem_write(
                    0x9b00e8,
                    cursor.assemble(
                        0x9b00e8, 'push eax; mov eax,[0x44b1ac]; mov [0x720000],eax; pop eax; ret;'
                    )
                )
                write(0x44b1ac, 0x10733)
                write(0x38fb40, 0x700000)
                uc.mem_write(0x700008, struct.pack('<HH', 296, 99))
                uc.mem_write(0x449, bytes([mode]))
                uc.mem_write(0x446f80, struct.pack('<HH', width, height))
                write(0x35bf80, count)
                uc.mem_write(0x3622ce, b'\x5a' * 36)
                original = struct.pack('<4hH', -9, -7, 745, 302, 0xbeef)
                uc.mem_write(0x397ca0, original * 65)
                uc.reg_write(UC_X86_REG_EDX, context)
                uc.reg_write(UC_X86_REG_EAX, 0x12345678)
                uc.reg_write(UC_X86_REG_EDI, 0x76543210)
                uc.reg_write(UC_X86_REG_EFLAGS, 0x247)
                uc.emu_start(0x9b30e8, 0x1000, count=10000)
                main = context == 0x38fb24
                active = main and mode == 0x6b and width == 320 and height == 200
                converts = active and 0 < count <= 64
                converted = struct.pack('<4hH', -4, -3, 298, 100, 0xbeef)
                self.assertEqual(
                    bytes(uc.mem_read(0x397ca0, 650)),
                    converted * count + original * (65 - count) if converts else original * 65
                )
                self.assertEqual(int.from_bytes(uc.mem_read(0x9b38e8, 4), 'little'), int(converts))
                self.assertEqual(
                    int.from_bytes(uc.mem_read(0x720000, 4), 'little'), 0x10000 if main else 0x10733
                )
                self.assertEqual(int.from_bytes(uc.mem_read(0x44b1ac, 4), 'little'), 0x10733)
                projection = struct.pack(
                    '<9I', 0x10733, 296, 99, 148, 49, 296 << 15, 99 << 15, 296 << 15, 99 << 15
                )
                self.assertEqual(
                    bytes(uc.mem_read(0x3622ce, 36)), projection if active else b'\x5a' * 36
                )
                self.assertEqual(uc.reg_read(UC_X86_REG_EAX), 0x12345678)
                self.assertEqual(uc.reg_read(UC_X86_REG_EDI), 0x76543210)
                self.assertEqual(uc.reg_read(UC_X86_REG_EDX), context)
                self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x247)
                self.assertEqual(uc.reg_read(UC_X86_REG_ESP), 0x800004)

    def test_derived_cursor_canvas_uses_matching_cached_offset_and_restores_state(self):
        uc = self.machine(cursor.cached_canvas())
        uc.mem_write(0x446f78, struct.pack('<I', 0x700000))
        uc.mem_write(0x446fd0, struct.pack('<I', 0x700123))
        # Stand-in draw records the derived canvas visible during the call.
        uc.mem_write(
            0x9b08e8,
            cursor.assemble(
                0x9b08e8, 'push eax; mov eax,[0x446fd0]; mov [0x710000],eax; pop eax; ret;'
            )
        )
        uc.reg_write(UC_X86_REG_EDX, 0x12345678)
        uc.reg_write(UC_X86_REG_EFLAGS, 0x247)
        uc.emu_start(0x9ae4e8, 0x1000, count=100)
        self.assertEqual(int.from_bytes(uc.mem_read(0x710000, 4), 'little'), cursor.CACHE + 0x123)
        self.assertEqual(int.from_bytes(uc.mem_read(0x446fd0, 4), 'little'), 0x700123)
        self.assertEqual(uc.reg_read(UC_X86_REG_EDX), 0x12345678)
        self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x247)
        self.assertEqual(uc.reg_read(UC_X86_REG_ESP), 0x800004)

    def paint_machine(self):
        uc = self.machine(cursor.cursor_updates())
        uc.mem_map(0xe0000000, 0x76000)
        uc.mem_write(0xe0000000, b'\xa7' * (800 * 600 + 16))
        uc.mem_write(cursor.FRAME, b'\x55' * (800 * 600))
        uc.mem_write(cursor.CACHE, b'\x11' * 64000)
        uc.mem_write(cursor.COLS, struct.pack('<800H', *(x * 320 // 800 for x in range(800))))
        uc.mem_write(cursor.ROWS, struct.pack('<600I', *(y // 3 * 320 for y in range(600))))
        uc.mem_write(0x9af4e8, struct.pack('<I', 1))
        uc.mem_write(0x446f78, struct.pack('<I', 0x700000))
        uc.mem_write(0x446fd0, struct.pack('<I', 0x700123))
        # Stub original cursor draw/erase; solid cached pixels isolate rectangle geometry.
        uc.mem_write(0x2f25e0, b'\xc3')
        uc.mem_write(0x2f26e8, b'\xc3')
        return uc

    def test_cursor_paint_clips_all_edges_and_restores_canvas(self):
        for x, y, expected in (
            (-5, -3, (0, 8, 0, 9)), (318, 198, (795, 800, 594, 600)), (-20, 20, None),
            (400, 20, None), (20, -20, None), (20, 220, None)
        ):
            with self.subTest(x=x, y=y):
                uc = self.paint_machine()
                uc.mem_write(0x447118, b'\x01')
                uc.mem_write(0x4470a4, struct.pack('<hh', x, y))
                uc.mem_write(0x4470b0, struct.pack('<HH', 8, 6))
                uc.reg_write(UC_X86_REG_EFLAGS, 0x247)
                uc.reg_write(UC_X86_REG_EAX, 0x76543210)
                uc.emu_start(0x9ae8e8, 0x1000, count=20000)
                expected_screen = bytearray(b'\xa7' * (800 * 600 + 16))
                if expected:
                    left, right, top, bottom = expected
                    self.assertEqual(struct.unpack('<4I', uc.mem_read(0x9af5ec, 16)), expected)
                    for row in range(top, bottom):
                        expected_screen[row * 800 + left:row * 800 + right] = b'\x11' * (
                            right - left
                        )
                self.assertEqual(
                    bytes(uc.mem_read(0xe0000000, len(expected_screen))), bytes(expected_screen)
                )
                self.assertEqual(
                    int.from_bytes(uc.mem_read(0x9af5e8, 4), 'little'), int(expected is not None)
                )
                self.assertEqual(int.from_bytes(uc.mem_read(0x446f78, 4), 'little'), 0x700000)
                self.assertEqual(int.from_bytes(uc.mem_read(0x446fd0, 4), 'little'), 0x700123)
                self.assertEqual(uc.mem_read(cursor.BUSY, 4), bytes(4))
                self.assertEqual(uc.mem_read(0x447115, 1), bytes(1))
                self.assertEqual(uc.reg_read(UC_X86_REG_EAX), 0x76543210)
                self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x247)
                self.assertEqual(uc.reg_read(UC_X86_REG_ESP), 0x800004)

    def test_hidden_cursor_restores_only_old_rectangle_and_busy_skips_it(self):
        for busy in (0, 1):
            uc = self.paint_machine()
            uc.mem_write(cursor.BUSY, struct.pack('<I', busy))
            uc.mem_write(0x9af5e8, struct.pack('<5I', 1, 10, 14, 20, 22))
            uc.emu_start(0x9ae8e8, 0x1000, count=1000)
            expected = bytearray(b'\xa7' * (800 * 600 + 16))
            if not busy:
                for row in (20, 21):
                    expected[row * 800 + 10:row * 800 + 14] = b'\x55' * 4
            self.assertEqual(bytes(uc.mem_read(0xe0000000, len(expected))), bytes(expected))
            self.assertEqual(int.from_bytes(uc.mem_read(0x9af5e8, 4), 'little'), busy)
            self.assertEqual(int.from_bytes(uc.mem_read(0x9af4e8 + 20, 4), 'little'), busy)
            self.assertEqual(int.from_bytes(uc.mem_read(cursor.BUSY, 4), 'little'), busy)

    def test_text_coverage_reset_is_main_view_only_and_respects_guards(self):
        for context in (0x38fb24, 0x38fc24):
            uc = self.machine(cursor.outlined_text())
            uc.mem_write(0x9a94e8, b'\xc3')
            uc.mem_write(cursor.MASK, b'\x23' * 64000)
            uc.reg_write(UC_X86_REG_EDX, context)
            uc.emu_start(0x9b00e8, 0x1000, count=20000)
            self.assertEqual(
                bytes(uc.mem_read(cursor.MASK, 64000)),
                (b'\xff' if context == 0x38fb24 else b'\x23') * 64000
            )
            self.assertEqual(bytes(uc.mem_read(cursor.MASK - 256, 256)), b'\xa5' * 256)
            self.assertEqual(bytes(uc.mem_read(cursor.MASK + 64000, 256)), b'\xa5' * 256)


if __name__ == '__main__':
    unittest.main()
