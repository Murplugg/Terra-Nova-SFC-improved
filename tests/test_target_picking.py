"""Execute picking policies on synthetic geometry; no original game data.

Original sensor/projection calls are modeled at their ABI boundary. These
tests verify our selection/cache logic, not original visibility calculations.
"""
from pathlib import Path
import struct, sys, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import target_picking as f
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

STACK = 0x1800000
STOP = 0x10000
CHOSEN = 0x26a103
ORIGINAL = 0x269f53
REGS = (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
    UC_X86_REG_EBP
)


def put(u, a, n):
    u.mem_write(a, struct.pack('<I', n & 0xffffffff))


def get(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def machine():
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(0, 0x2000000)
    for a, b in f.bodies():
        u.mem_write(a, b)
    return u


def obj(u, oid, pos=(0, 0, 0), kind=1, active=True):
    p = 0x3c3240 + oid * 37
    u.mem_write(p, bytes([int(active), kind, 0]))
    u.mem_write(p + 15, struct.pack('<3i', *pos))


def queue(u, rows):
    put(u, 0x35bf80, len(rows))
    for i, row in enumerate(rows):
        u.mem_write(0x397ca0 + i * 10, struct.pack('<5h', *row))


def quad(u, index, oid, vertices):
    u.mem_write(f.DATA + 36 * index, struct.pack('<9i', *(v for pt in vertices for v in pt), oid))


def run_pick(u, entry, x, y, stop_at=()):
    for i, reg in enumerate(REGS):
        u.reg_write(reg, 0x123400 + i)
    u.reg_write(UC_X86_REG_EFLAGS, 0x202)
    u.reg_write(UC_X86_REG_ESP, STACK)
    u.mem_write(STACK + 12, struct.pack('<hhH', x, y, 0x7777))
    hits = []

    def stop(u, a, n, _):
        if a in (CHOSEN, ORIGINAL, *stop_at):
            hits.append(a)
            u.emu_stop()

    h = u.hook_add(UC_HOOK_CODE, stop)
    try:
        u.emu_start(entry, STOP, count=200000)
    finally:
        u.hook_del(h)
    assert hits, 'picker did not reach continuation'
    assert u.reg_read(UC_X86_REG_ESP) == STACK
    assert u.reg_read(UC_X86_REG_EFLAGS) == 0x202
    for i, reg in enumerate(REGS):
        if hits[0] == ORIGINAL and reg == UC_X86_REG_EBX:
            continue  # original load reproduced
        assert u.reg_read(reg) == 0x123400 + i, (reg, hits)
    return hits[0], struct.unpack('<H', u.mem_read(STACK + 16, 2))[0]


class PickingTests(unittest.TestCase):

    def test_original_selection_uses_rectangle_centres_without_depth_blocking(self):
        # A drone behind a large building remains selectable in original mode.
        # Height conversion preserves the original margin in a tall logical HUD.
        from features import options_row, option_contracts as c
        u = machine()
        for a, b in f.preference_bodies(options_row.strings()[0]):
            u.mem_write(a, b)
        put(u, 0x446f80, 0x1900140)
        obj(u, 1, (200000, 0, 0), kind=3)
        obj(u, 2, (20000, 0, 0), kind=4)
        queue(u, [(95, 190, 105, 210, 1), (0, 0, 200, 399, 2)])
        self.assertEqual(run_pick(u, f.LEGACY_PICK, 100, 200), (CHOSEN, 1))
        self.assertEqual(run_pick(u, f.RECT_ENTRY, 100, 200), (CHOSEN, 2))
        queue(u, [(95, 190, 105, 210, 1)])
        self.assertEqual(run_pick(u, f.LEGACY_PICK, 100, 228), (CHOSEN, 1))
        self.assertEqual(run_pick(u, f.LEGACY_PICK, 100, 250), (CHOSEN, 0))
        # The switch preserves the existing renderer dispatch when on, and
        # takes the original policy only after successful preference loading.
        put(u, c.PICK.state, 1)
        put(u, c.PICK.state+4, 1)
        self.assertEqual(run_pick(u, f.PREFERENCE_GATE, 100, 200,
                                 (f.IMPROVED_DISPATCH,))[0], f.IMPROVED_DISPATCH)
        put(u, c.PICK.state+4, 0)
        self.assertEqual(run_pick(u, f.PREFERENCE_GATE, 100, 200), (CHOSEN, 1))

    def test_original_selection_ties_and_empty_list(self):
        from features import options_row
        u = machine()
        for a, b in f.preference_bodies(options_row.strings()[0]):
            u.mem_write(a, b)
        obj(u, 1, kind=3)
        obj(u, 2, kind=3)
        queue(u, [(10, 10, 20, 20, 2), (10, 10, 20, 20, 1)])
        self.assertEqual(run_pick(u, f.LEGACY_PICK, 15, 15), (CHOSEN, 2))
        queue(u, [])
        self.assertEqual(run_pick(u, f.LEGACY_PICK, 15, 15), (CHOSEN, 0))

    def test_rectangle_depth_and_inclusive_edges(self):
        for click in ((10, 10), (0, 0), (20, 20)):
            u = machine()
            obj(u, 1, (100000, 0, 0))
            obj(u, 2, (20000, 0, 0))
            queue(u, [(0, 0, 20, 20, 1), (0, 0, 20, 20, 2)])
            self.assertEqual(run_pick(u, f.RECT_ENTRY, *click), (CHOSEN, 2))

    def test_rectangle_ties_and_original_fallback(self):
        u = machine()
        obj(u, 1, (20000, 0, 0))
        obj(u, 2, (20000, 0, 0))
        queue(u, [(0, 0, 20, 20, 2), (0, 0, 20, 20, 1)])
        self.assertEqual(run_pick(u, f.RECT_ENTRY, 10, 10), (CHOSEN, 2))
        self.assertEqual(run_pick(u, f.RECT_ENTRY, 21, 10), (ORIGINAL, 0x7777))
        for n in (0, 65, 0xffffffff):
            put(u, 0x35bf80, n)
            self.assertEqual(run_pick(u, f.RECT_ENTRY, 10, 10), (ORIGINAL, 0x7777))

    def test_marker_score_depth_and_visibility(self):
        u = machine()
        obj(u, 1, (100000, 0, 0))
        obj(u, 2, (20000, 0, 0))
        queue(u, [(0, 0, 20, 20, 1), (0, 0, 20, 20, 2)])
        visible = {1, 2}
        centres = {1: (10, 10), 2: (14, 10)}

        def calls(u, a, n, _):
            if a == 0x27d458:
                u.reg_write(UC_X86_REG_EAX, int(u.reg_read(UC_X86_REG_EDX) in visible))
            elif a == 0x27eaf4:
                x, y = centres[u.reg_read(UC_X86_REG_EAX)]
                put(u, u.reg_read(UC_X86_REG_EDX), x << 16)
                put(u, u.reg_read(UC_X86_REG_EBX), y << 16)
            else:
                return
            sp = u.reg_read(UC_X86_REG_ESP)
            u.reg_write(UC_X86_REG_EIP, get(u, sp))
            u.reg_write(UC_X86_REG_ESP, sp + 4)

        u.hook_add(UC_HOOK_CODE, calls)
        self.assertEqual(run_pick(u, f.MARKER_ENTRY, 10, 10), (CHOSEN, 1))
        centres[2] = (10, 10)
        self.assertEqual(run_pick(u, f.MARKER_ENTRY, 10, 10), (CHOSEN, 2))
        visible.clear()
        self.assertEqual(
            run_pick(u, f.MARKER_ENTRY, 10, 10, (f.RECT_ENTRY, )), (f.RECT_ENTRY, 0x7777)
        )

    def test_quad_distance_inside_edges_and_outside(self):
        u = machine()
        quad(u, 0, 1, [(0, 0), (20, 0), (20, 20), (0, 20)])
        for x, y, expected in ((10, 10, 0), (20, 0, 0), (23, 10, 9), (23, 24, 25), (-3, 10, 9)):
            put(u, STACK, STOP)
            u.reg_write(UC_X86_REG_ESP, STACK)
            u.reg_write(UC_X86_REG_ESI, f.DATA)
            u.reg_write(UC_X86_REG_EAX, x & 0xffffffff)
            u.reg_write(UC_X86_REG_EBX, y & 0xffffffff)
            u.emu_start(f.DIST, STOP, count=10000)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), expected)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)

    def test_quad_depth_absent_queue_and_overflow(self):
        u = machine()
        obj(u, 1, (100000, 0, 0))
        obj(u, 2, (20000, 0, 0))
        queue(u, [(90, 90, 110, 110, 1), (90, 90, 110, 110, 2)])
        for i, oid in enumerate((1, 2)):
            quad(u, i, oid, [(240, 290), (260, 290), (260, 310), (240, 310)])
        put(u, f.VALID, 1)
        put(u, f.COUNT, 2)
        self.assertEqual(run_pick(u, f.ENTRY, 100, 100), (CHOSEN, 2))
        queue(u, [(90, 90, 110, 110, 1)])
        self.assertEqual(run_pick(u, f.ENTRY, 100, 100), (CHOSEN, 1))
        for n in (0, f.CAPACITY + 1, 0xffffffff):
            put(u, f.COUNT, n)
            self.assertEqual(
                run_pick(u, f.ENTRY, 100, 100, (f.MARKER_ENTRY, )), (f.MARKER_ENTRY, 0x7777)
            )
        put(u, f.COUNT, 2)
        put(u, f.VALID, 0)
        self.assertEqual(
            run_pick(u, f.ENTRY, 100, 100, (f.MARKER_ENTRY, )), (f.MARKER_ENTRY, 0x7777)
        )

    def test_nearer_non_pba_blocks_quad_choice(self):
        u = machine()
        obj(u, 1, (100000, 0, 0))
        obj(u, 2, (20000, 0, 0), kind=2)
        queue(u, [(90, 90, 110, 110, 1), (90, 90, 110, 110, 2)])
        quad(u, 0, 1, [(240, 290), (260, 290), (260, 310), (240, 310)])
        put(u, f.VALID, 1)
        put(u, f.COUNT, 1)
        self.assertEqual(
            run_pick(u, f.ENTRY, 100, 100, (f.MARKER_ENTRY, )), (f.MARKER_ENTRY, 0x7777)
        )

    def test_only_main_render_owns_cache_lifecycle(self):
        for main in (False, True):
            u = machine()
            put(u, f.COUNT, 17)
            put(u, f.VALID, 1)
            put(u, f.ACTIVE, 0)
            put(u, STACK, STOP)
            u.reg_write(UC_X86_REG_ESP, STACK)
            u.reg_write(UC_X86_REG_EDX, 0x38fb24 if main else 0x123456)
            observed = []

            def render(u, a, n, _):
                if a == f.ORIGINAL_RENDER:
                    observed.append((get(u, f.COUNT), get(u, f.VALID), get(u, f.ACTIVE)))

            u.mem_write(f.ORIGINAL_RENDER, b'\xc3')
            u.hook_add(UC_HOOK_CODE, render)
            u.emu_start(f.RENDER, STOP, count=1000)
            self.assertEqual(observed, [(0, 0, 1) if main else (17, 1, 0)])
            self.assertEqual((get(u, f.VALID), get(u, f.ACTIVE)), (1, 0))


if __name__ == '__main__':
    unittest.main()
