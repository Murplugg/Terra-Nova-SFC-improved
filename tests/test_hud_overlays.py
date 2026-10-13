"""Overlay pixels, pointer lifetime and adjacent UI helpers at modeled boundaries."""
from pathlib import Path
import sys, struct, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import hud_overlays as h, fps_display as f, modal_ui as m
from features import render_compositor as c, hud, maps, input_views
from features.render_arena import Layout, BASE
from patch_support import asm
from tests.test_render_views import Fixture, put, word, get, STACK, STOP
from tests.test_input_views import run, IMPORTS
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *


def machine(pieces):
    u = Fixture().u
    for a, b in pieces:
        u.mem_write(a, b)
    return u


def predecessor(ui):
    r = bytearray(0x2000000)
    groups = [c.bodies(Layout(BASE), hud, maps), h.drag_bodies(), list(h.sites().items())]
    if ui:
        groups += [
            h.bodies(IMPORTS),
            [(input_views.MAP, asm(input_views.MAP, input_views.coordinate_source()))],
            list(h.ui_sites().items())
        ]
    for pieces in groups:
        for a, b in pieces:
            r[a:a + len(b)] = b
    return r


class OverlayTests(unittest.TestCase):

    def test_explicit_authoring_has_no_history_and_binds_imports(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source')
        ):
            for generator in (h.bodies, h.ui_bodies):
                self.assertTrue(generator(IMPORTS))
                self.assertNotEqual(
                    generator(IMPORTS), generator({
                        k: v + 0x100
                        for k, v in IMPORTS.items()
                    })
                )
                with self.assertRaises(ValueError):
                    generator({})
            self.assertTrue(m.dialog_bodies())
            self.assertTrue(m.tooltip_bodies())

    def test_checked_installation_roundtrip_rejects_partial_dirty_and_changed_providers(self):
        for ui in (False, True):
            pristine = predecessor(ui)
            for issue in ('none', 'hook', 'partial', 'reservation', 'compositor', 'drag', 'short'):
                with self.subTest(ui=ui, issue=issue):
                    r = bytearray(pristine)
                    writes = []
                    parts = h.ui_bodies(IMPORTS) if ui else h.bodies(IMPORTS)
                    if issue == 'hook':
                        r[next(iter(h.ui_sites() if ui else h.sites()))] ^= 1
                    if issue == 'partial':
                        a, b = parts[0]
                        r[a:a + len(b)] = b
                    if issue == 'reservation':
                        r[h.UI_END - 1 if ui else h.END - 1] = 1
                    if issue == 'compositor':
                        r[c.COMPOSE] ^= 1
                    if issue == 'drag':
                        r[h.WRAPPERS if ui else h.DRAG_CODE] ^= 1

                    def write(a, b):
                        writes.append((a, b))
                        r[a:a + len(b)] = b

                    read = lambda a, n: r[a:a + n - int(issue == 'short')]
                    if issue != 'none':
                        with self.assertRaises(ValueError):
                            h.install(write, read, IMPORTS, ui=ui)
                        self.assertFalse(writes)
                    else:
                        h.install(write, read, IMPORTS, ui=ui)
                        self.assertEqual(writes, parts)
                        writes.clear()
                        self.assertTrue(h.verify(read, IMPORTS, ui=ui))
                        self.assertTrue(h.install(write, read, IMPORTS, ui=ui)['already_installed'])
                        self.assertFalse(writes)
                        self.assertEqual(h.predecessor_view(r, IMPORTS, ui=ui), pristine)

    def test_rectangle_copies_black_and_clips_using_shared_pixel_edges(self):
        u = machine(h.bodies(IMPORTS))
        frame = 0x68500000
        source = 0x1e60000
        raw = bytes((i * 13 % 256 for i in range(320 * 400)))
        u.mem_write(source, raw)
        edges = [(12 * y + 4) // 5 for y in range(401)]
        u.mem_write(0x68b04000, struct.pack('<401I', *edges))
        for x0, y0, x1, y1 in ((-3, -1, 2, 2), (318, 398, 330, 405), (5, 6, 5, 10), (7, 7, 6, 6)):
            u.mem_write(frame, b'\x7f' * (1280 * 960))
            expected = bytearray(b'\x7f' * (1280 * 960))
            for y in range(max(0, y0), min(400, y1)):
                for x in range(max(0, x0), min(320, x1)):
                    for dy in range(edges[y], edges[y + 1]):
                        expected[dy * 1280 + x * 4:dy * 1280 + x * 4 +
                                 4] = bytes([raw[y * 320 + x]]) * 4
            run(u, h.RECT, eax=x0 & 0xffffffff, edx=y0 & 0xffffffff, ebx=x1, ecx=y1)
            self.assertEqual(bytes(u.mem_read(frame, len(expected))), expected)

    def test_arrow_outlines_only_use_expanded_visible_hud_arrow_widgets(self):
        u = machine(h.world_bodies())
        calls = []
        u.mem_write(h.RECT, b'\xc3')
        u.hook_add(
            UC_HOOK_CODE, lambda uc, a, n, d: calls.append(
                tuple(
                    uc.reg_read(r)
                    for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_ECX)
                )
            ) if a == h.RECT else None
        )
        base = 0x140000
        put(u, 0x389dec, base)
        put(u, 0x389de8, base + 2 * 0x62)
        for i, callback in enumerate((0x2654d0, 0x12345, 0x2654e0)):
            u.mem_write(base + i * 0x62 + 8, struct.pack('<4h', 10, 20, 30, 40))
            put(u, base + i * 0x62 + 24, callback)
        for enabled, hidden, count in ((0, 0, 0), (1, 1, 0), (1, 0, 2)):
            calls.clear()
            u.mem_write(0x38fbfe, bytes([enabled]))
            u.mem_write(0x35aef0, bytes([hidden]))
            run(u, h.WORLD_ARROWS)
            self.assertEqual(calls, [(9, 19, 31, 41)] * count)

    def test_drag_accumulates_signed_axes_without_cross_axis_carry(self):
        u = machine(h.drag_bodies())
        for i, (_, _, anchor) in enumerate(h.DRAG_SITES):
            u.mem_write(anchor, struct.pack('<2h', -1, 20))
            run(u, h.DRAG_CODE + i * 0x80, end=0x276cdc, edx=(0xfffd << 16) | 2, ecx=0x12345)
            self.assertEqual(struct.unpack('<2h', u.mem_read(anchor, 4)), (1, 17))
            self.assertEqual(u.reg_read(UC_X86_REG_ECX), 0x12345)
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_tree_collision_copy_filters_species_and_leaves_resource_untouched(self):
        u = machine(h.world_bodies())
        resource = 0x150000
        for cls, species, kind, radius, selected in (
            (0, 0, 0x60003, 100, True), (0, 11, 0x60003, 101, True), (0, 3, 0x60003, 100, False),
            (1, 0, 0x60003, 100, False), (0, 0, 7, 100, False), (0, 1, 0x60003, 0, False)
        ):
            original = bytearray(range(60))
            struct.pack_into('<I', original, 0, kind)
            struct.pack_into('<I', original, 52, radius)
            u.mem_write(resource, bytes(original))
            run(u, h.WORLD_TREE, edi=cls, ebp=species, edx=resource)
            self.assertEqual(bytes(u.mem_read(resource, 60)), bytes(original))
            self.assertEqual(u.reg_read(UC_X86_REG_EDX), h.WORLD_TREEBUF if selected else resource)
            if selected:
                struct.pack_into('<I', original, 52, radius * 4 // 5)
                self.assertEqual(bytes(u.mem_read(h.WORLD_TREEBUF, 60)), bytes(original))

    def test_ashford_label_is_scoped_to_resource_row_and_mission_window(self):
        u = machine(h.ui_bodies(IMPORTS))
        u.mem_write(0x2e3194, b'\xc3')
        for mission in (20, 21, 28, 29):
            for resource, row in ((0x5ab0148, 3458), (0x5ab0149, 3458), (0x5ab0148, 3457)):
                put(u, 0x359708, mission)
                run(u, h.UI_ASHFORD, eax=resource, ebp=row)
                self.assertEqual(
                    u.reg_read(UC_X86_REG_EAX), h.UI_ASHFORD + 0x80
                    if 21 <= mission <= 28 and resource == 0x5ab0148 and row == 3458 else resource
                )

    def test_fps_counts_world_frames_not_cursor_paints_and_resets_long_gaps(self):
        u = machine(f.bodies(IMPORTS, h.compositor_site()))
        put(u, f.STATE, 1)
        put(u, f.STATE + 4, 1)
        u.mem_write(0x1d0d449, b'k')
        u.mem_write(0x9aa4e8 + 42 * 3, b'\xff\xff\xff')
        put(u, 0x1d0f300, 100)
        for frame in (1, 1, 2, 2):
            put(u, 0x35f400, frame)
            run(u, f.FPS)
        self.assertEqual(get(u, f.STATE + 20), 2)
        self.assertEqual(get(u, f.STATE + 36), 42)
        put(u, f.STATE + 20, 60)
        put(u, 0x1d0f300, 1000)
        run(u, f.FPS)
        self.assertEqual(get(u, f.STATE + 24), 60)
        self.assertEqual(get(u, f.STATE + 20), 0)
        put(u, f.STATE + 20, 100)
        put(u, 0x1d0f300, 5001)
        run(u, f.FPS)
        self.assertEqual(get(u, f.STATE + 24), 60)
        self.assertEqual(get(u, f.STATE + 20), 0)
        put(u, f.STATE + 20, 1200)
        put(u, 0x1d0f300, 6001)
        run(u, f.FPS)
        self.assertEqual(get(u, f.STATE + 24), 999)

    def test_fps_hidden_in_menus_or_disabled_and_paints_only_its_corner(self):
        u = machine(f.bodies(IMPORTS, h.compositor_site()))
        put(u, f.STATE, 1)
        frame = 0x68500000
        for enabled, mode in ((0, b'k'), (1, b'i'), (1, b'k')):
            put(u, f.STATE + 4, enabled)
            u.mem_write(0x1d0d449, mode)
            u.mem_write(frame, b'\x77' * (1280 * 960))
            run(u, f.FPS)
            expected = bytearray(b'\x77' * (1280 * 960))
            if enabled and mode == b'k':
                for y in range(942, 958):
                    expected[y * 1280 + 1160:y * 1280 + 1272] = bytes(112)
            self.assertEqual(bytes(u.mem_read(frame, len(expected))), expected)

    def test_capture_admission_rollback_and_release_messages(self):
        u = machine(h.bodies(IMPORTS))
        put(u, h.STATE + 32, 1)
        put(u, 0x1d1d000, 42)
        put(u, 0x1d0f008, 1)
        calls = []
        answers = {'GetForegroundWindow': 42, 'GetCapture': 42}
        for i, name in enumerate(h.APIS):
            address = 0x1900000 + i * 0x10
            put(u, h.STATE + 4 + i * 4, address)
            count = {
                'GetClientRect': 2,
                'ClientToScreen': 2,
                'ClipCursor': 1,
                'SetCapture': 1
            }.get(name, 0)
            u.mem_write(address, b'\xc2' + struct.pack('<H', 4 * count))

        def callback(uc, a, n, d):
            if 0x1900000 <= a < 0x1900000 + len(h.APIS) * 0x10 and (a - 0x1900000) % 0x10 == 0:
                name = h.APIS[(a - 0x1900000) // 0x10]
                calls.append(name)
                uc.reg_write(UC_X86_REG_EAX, answers.get(name, 1))

        u.hook_add(UC_HOOK_CODE, callback)
        for foreground, buttons, capture, active in (
            (7, 1, 42, 0), (42, 0, 42, 0), (42, 1, 7, 0), (42, 1, 42, 1)
        ):
            put(u, h.STATE, 0)
            answers.update(GetForegroundWindow=foreground, GetCapture=capture)
            put(u, 0x1d0f008, buttons)
            calls.clear()
            run(u, h.CAPTURE)
            self.assertEqual(get(u, h.STATE), active)
            if capture == 7:
                self.assertEqual(calls.count('ClipCursor'), 2)
                self.assertNotIn('ReleaseCapture', calls)
        for message in (0x202, 0x205, 0x208, 8, 2, 0x1f, 0x215, 0x231, 0x200):
            put(u, h.STATE, 1)
            put(u, STACK + 8, message)
            calls.clear()
            run(u, h.PROC, end=0x1e4a300)
            self.assertEqual(get(u, h.STATE), int(message == 0x200))
            self.assertEqual(calls.count('ReleaseCapture'), int(message != 0x200))


if __name__ == '__main__':
    unittest.main()
