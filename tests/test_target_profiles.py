"""Renderer-profile picking/conversion and bounded cache x86 execution.

Synthetic projected quads/rectangles are the inputs. No original visibility,
projection, framebuffer or live gameplay is simulated here.
"""
import struct, unittest
from tests.test_target_picking import (
    f, machine, obj, queue, quad, run_pick, put, get, STACK, STOP, CHOSEN, REGS
)
from patch_support import asm
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

ENTRY = 0x1b00000
CONVERT = ENTRY + 0x1000
RECT = ENTRY + 0x2000
RENDERER = ENTRY + 0x3000


def profiled(profile):
    u = machine()
    for a, b in f.quad_bodies(asm, profile=profile, entry=ENTRY, renderer=RENDERER):
        u.mem_write(a, b)
    return u


def convert(u, rectangle):
    u.mem_write(RECT, struct.pack('<4h', *rectangle))
    put(u, STACK, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK)
    u.reg_write(UC_X86_REG_ESI, RECT)
    u.reg_write(UC_X86_REG_ECX, 0xdeadbeef)
    u.reg_write(UC_X86_REG_EDI, 0xcafebabe)
    u.emu_start(CONVERT, STOP, count=200)
    assert u.reg_read(UC_X86_REG_ESP) == STACK + 4
    assert u.reg_read(UC_X86_REG_ECX) == 0xdeadbeef and u.reg_read(UC_X86_REG_EDI) == 0xcafebabe
    return struct.unpack('<4h', u.mem_read(RECT, 8))


def capture(u, vertices):
    # The original part routine exposes four six-dword vertices at entry ESP.
    u.mem_write(
        STACK, b''.join(struct.pack('<6i', x << 16, y << 16, 0, 0, 0, 0) for x, y in vertices)
    )
    u.reg_write(UC_X86_REG_ESP, STACK)
    u.reg_write(UC_X86_REG_EFLAGS, 0x202)
    for i, reg in enumerate(REGS):
        u.reg_write(reg, 0x123400 + i)
    u.emu_start(f.PART, f.PART_SITE + 5, count=1000)
    assert u.reg_read(UC_X86_REG_EIP) == f.PART_SITE + 5
    assert u.reg_read(UC_X86_REG_ESP) == STACK and u.reg_read(UC_X86_REG_EFLAGS) == 0x202
    for i, reg in enumerate(REGS):
        if reg != UC_X86_REG_EAX:
            assert u.reg_read(reg) == 0x123400 + i
    assert u.reg_read(UC_X86_REG_EAX) == get(u, 0x44b1a0)


class TargetProfileTests(unittest.TestCase):

    def test_rectangle_floor_all_profiles_negative_and_edge_values(self):
        for profile in f.Profile:
            u = profiled(profile)
            u.mem_write(CONVERT, asm(CONVERT, f.rectangle_source(profile)))
            lw, lh, ww, wh, _ = profile.value
            for rectangle in (
                (-3, -5, 1, 1), (-32768, -32768, 32767, 32767), (0, 0, ww - 1, wh - 1),
                (31, 29, 33, 31)
            ):
                expected = tuple(
                    v * (lw if i % 2 == 0 else lh) // (ww if i % 2 == 0 else wh)
                    for i, v in enumerate(rectangle)
                )
                self.assertEqual(convert(u, rectangle), expected, (profile, rectangle))

    def test_relocated_picker_uses_profile_click_rounding(self):
        for profile in f.Profile:
            lw, lh, ww, wh, _ = profile.value
            for x, y in ((1, 1), (123, 117), (319, lh - 1)):
                u = profiled(profile)
                px = x * ww // lw
                py = (y * wh + lh - 1) // lh if profile is f.Profile.HD960 else y * wh // lh
                obj(u, 1, (100000, 0, 0))
                obj(u, 2, (20000, 0, 0))
                queue(u, [(x, y, x, y, 1), (x, y, x, y, 2)])
                quad(u, 0, 1, [(px, py)] * 4)
                quad(u, 1, 2, [(px, py - 1)] * 4)
                put(u, f.VALID, 1)
                put(u, f.COUNT, 2)
                self.assertEqual(run_pick(u, ENTRY, x, y), (CHOSEN, 1), (profile, x, y))

    def test_scaled_distance_limit_preserves_historical_plus_one(self):
        for profile in f.Profile:
            lw, lh, ww, wh, limit = profile.value
            radius = 80 if profile is f.Profile.HD960 else 50
            for dx, dy, chosen in ((radius, 1, True), (radius, 2, False)):
                u = profiled(profile)
                obj(u, 1, (100000, 0, 0))
                queue(u, [(0, 0, 319, lh - 1, 1)])
                px = 100 * ww // lw
                py = 100 * wh // lh
                quad(u, 0, 1, [(px + dx, py + dy)] * 4)
                put(u, f.VALID, 1)
                put(u, f.COUNT, 1)
                result = run_pick(u, ENTRY, 100, 100, (f.MARKER_ENTRY, ))
                self.assertEqual(result[0], CHOSEN if chosen else f.MARKER_ENTRY, (profile, limit))

    def test_logical_non_pba_blocker_still_wins_under_hd_profile(self):
        u = profiled(f.Profile.HD960)
        obj(u, 1, (100000, 0, 0))
        obj(u, 2, (20000, 0, 0), kind=2)
        queue(u, [(99, 99, 101, 101, 1), (99, 99, 101, 101, 2)])
        quad(u, 0, 1, [(399, 239), (401, 239), (401, 241), (399, 241)])
        put(u, f.VALID, 1)
        put(u, f.COUNT, 1)
        self.assertEqual(run_pick(u, ENTRY, 100, 100, (f.MARKER_ENTRY, ))[0], f.MARKER_ENTRY)

    def test_custom_renderer_keeps_main_view_cache_lifecycle(self):
        for main in (False, True):
            u = profiled(f.Profile.HD960)
            u.mem_write(RENDERER, b'\xc3')
            put(u, f.COUNT, 17)
            put(u, f.VALID, 1)
            put(u, f.ACTIVE, 0)
            put(u, STACK, STOP)
            u.reg_write(UC_X86_REG_ESP, STACK)
            u.reg_write(UC_X86_REG_EDX, f.MAIN_CAMERA if main else 0x123456)
            seen = []

            def observe(u, a, n, _):
                if a == RENDERER:
                    seen.append((get(u, f.COUNT), get(u, f.VALID), get(u, f.ACTIVE)))

            u.hook_add(UC_HOOK_CODE, observe)
            u.emu_start(f.RENDER, STOP, count=1000)
            self.assertEqual(seen, [(0, 0, 1) if main else (17, 1, 0)])
            self.assertEqual((get(u, f.VALID), get(u, f.ACTIVE)), (1, 0))

    def test_cache_capture_rejects_auxiliary_views_and_invalid_vertices(self):
        for active, canvas, vertices, accepted in (
            (1, f.MAIN_CANVAS, [(1, 2), (3, 4), (5, 6), (7, 8)],
             True), (0, f.MAIN_CANVAS, [(1, 2)] * 4, False), (1, 0x123456, [(1, 2)] * 4, False),
            (1, f.MAIN_CANVAS, [(1, 2), (3, 4), (5, 6), (8193, 8)], False)
        ):
            u = profiled(f.Profile.HD960)
            put(u, f.ACTIVE, active)
            put(u, 0x44b1a0, canvas)
            obj(u, 1)
            put(u, 0x420154, 1)
            capture(u, vertices)
            self.assertEqual(get(u, f.COUNT), int(accepted))
            if accepted:
                self.assertEqual(
                    struct.unpack('<9i', u.mem_read(f.DATA, 36)), (1, 2, 3, 4, 5, 6, 7, 8, 1)
                )

    def test_full_cache_marks_overflow_without_writing_past_end(self):
        u = profiled(f.Profile.HD960)
        put(u, f.ACTIVE, 1)
        put(u, 0x44b1a0, f.MAIN_CANVAS)
        obj(u, 1)
        put(u, 0x420154, 1)
        put(u, f.COUNT, f.CAPACITY - 1)
        guard = b'unchanged cache boundary' * 3
        u.mem_write(f.END, guard)
        capture(u, [(1, 2)] * 4)
        self.assertEqual(get(u, f.COUNT), f.CAPACITY)
        final = bytes(u.mem_read(f.DATA + (f.CAPACITY - 1) * f.RECORD_SIZE, f.RECORD_SIZE))
        capture(u, [(3, 4)] * 4)
        self.assertEqual(get(u, f.COUNT), f.CAPACITY + 1)
        self.assertEqual(bytes(u.mem_read(f.END, len(guard))), guard)
        self.assertEqual(
            bytes(u.mem_read(f.DATA + (f.CAPACITY - 1) * f.RECORD_SIZE, f.RECORD_SIZE)), final
        )

    def test_unknown_profile_is_rejected(self):
        for value in (None, '1280x960', (320, 400, 1280, 960, 6401)):
            with self.assertRaises(ValueError):
                f.quad_source(value)
            with self.assertRaises(ValueError):
                f.rectangle_source(value)


if __name__ == '__main__':
    unittest.main()
