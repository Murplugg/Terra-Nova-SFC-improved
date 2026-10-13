"""Execute projectile sweep/remainder helpers and the vehicle-query wrapper.

This covers their arithmetic and caller contracts, not full world collision.
Original continuation addresses are stopping boundaries, never fake collisions.
"""
from pathlib import Path
import struct, sys, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from patch_support import asm
from features import projectiles as sweep, projectiles as physics

VEHICLE_CALL = 0x1fcf400
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

STACK = 0x1700000
FRAME = 0x1800000
CALLER = FRAME + 0x100
PARENT = CALLER + 0x100


def put(u, a, n):
    u.mem_write(a, struct.pack('<I', n & 0xffffffff))


def get(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


class Fixture:

    def __init__(self, wrapped=False):
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        r = bytearray(0x2000000)
        for a, b in sweep.HOOKS.items():
            r[a:a + len(b)] = b
        r[physics.HOOK:physics.HOOK + len(physics.ORIGINAL)] = physics.ORIGINAL
        for part in ('sweep', 'physics'):
            sweep.install(u.mem_write, lambda a, n: r[a:a + n], part=part)
        if wrapped:
            u.mem_write(sweep.CODE, dict(sweep.sweep_bodies(vehicle_call=VEHICLE_CALL))[sweep.CODE])
        self.stop = None
        u.hook_add(UC_HOOK_CODE, self.boundary)

    def boundary(self, u, a, n, _):
        if a in (0x311555, 0x311563, 0x3119ca, 0x3119cc, physics.HOOK + len(physics.ORIGINAL)):
            self.stop = a
            u.emu_stop()

    def run(self, a):
        self.stop = None
        self.u.reg_write(UC_X86_REG_ESP, STACK)
        self.u.emu_start(a, 0, count=20000)
        assert self.stop is not None
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK
        return self.stop

    def query(self, length, step=0x10000, caller=0x2d96da, outer=0x2f07c6, parent=0x2d96da):
        u = self.u
        put(u, FRAME + 0x72, outer)
        put(u, FRAME + 0x66, CALLER)
        put(u, CALLER + 12, caller)
        put(u, CALLER, PARENT)
        put(u, PARENT + 4, parent)
        put(u, FRAME + 0x56, 0xdeadbeef)
        put(u, 0x44e0c8, step)
        u.reg_write(UC_X86_REG_EBP, FRAME)
        u.reg_write(UC_X86_REG_EAX, length & 0xffffffff)
        return self.run(sweep.CODE)


class ProjectilePhysicsTests(unittest.TestCase):

    def test_vertical_projectile_cell_admission_preserves_other_queries(self):
        """Reproduce the XY-only gate with controlled height and caller state.

        Stop at the original inspect/skip destinations; actual terrain and
        object contacts require the separate captured-state gameplay fixture.
        """
        for xy in (0, 15, 16, 17):
            for z1 in (99, 100, 101):
                for projectile in (0, 1):
                    with self.subTest(xy=xy, z1=z1, projectile=projectile):
                        u = Uc(UC_ARCH_X86, UC_MODE_32)
                        u.mem_map(0, 0x2000000)
                        for a, b in sweep.vertical_bodies():
                            u.mem_write(a, b)
                        u.mem_write(CALLER, asm(CALLER, f'cmp eax,16;jmp {sweep.VERTICAL_SITE}'))
                        put(u, sweep.STATE, projectile)
                        put(u, 0x446778, 100)
                        put(u, 0x446748, z1)
                        u.reg_write(UC_X86_REG_ESP, STACK)
                        u.reg_write(UC_X86_REG_EAX, xy)
                        u.reg_write(UC_X86_REG_EDX, 456)
                        reached, flags = [], []
                        def boundary(cpu, a, n, data):
                            if a == sweep.VERTICAL_SITE:
                                flags.append(cpu.reg_read(UC_X86_REG_EFLAGS))
                            if a in (sweep.VERTICAL_SITE+6, 0x2db061):
                                reached.append(a)
                                cpu.emu_stop()
                        u.hook_add(UC_HOOK_CODE, boundary)
                        u.emu_start(CALLER, 0, count=100)
                        inspect_cell = xy >= 16 or (projectile == 1 and z1 != 100)
                        self.assertEqual(reached, [sweep.VERTICAL_SITE+6 if inspect_cell else 0x2db061])
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX), xy)
                        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 456)
                        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
                        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), flags[0])

    def cylinder(self, start, end):
        """Synthetic cylinder: radius 10000, top 1000, original vertical scale.

        Run the assembled short-segment helper. The long-segment continuation
        is a stopping boundary; these tests contain no original game code.
        """
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        for a, b in sweep.cylinder_bodies():
            u.mem_write(a, b)
        u.mem_write(FRAME, bytes(12))
        u.mem_write(FRAME+32, struct.pack('<4i', 0, 10000, 1000, 0))
        z0, z1 = start[2]*24, end[2]*24
        args = (CALLER, z0, end[0], end[1], z1, 0, FRAME+64)
        u.mem_write(STACK, struct.pack('<7I', *(x & 0xffffffff for x in args)))
        put(u, FRAME+64, 0xdeadbeef)
        for reg, value in ((UC_X86_REG_ESP, STACK), (UC_X86_REG_EAX, FRAME),
                           (UC_X86_REG_EDX, FRAME+32), (UC_X86_REG_EBX, start[0]),
                           (UC_X86_REG_ECX, start[1]), (UC_X86_REG_EBP, 123),
                           (UC_X86_REG_ESI, 456), (UC_X86_REG_EDI, 789)):
            u.reg_write(reg, value & 0xffffffff)
        vectors = [0x123456789abcdef123456789abcdef + i for i in range(8)]
        for i, value in enumerate(vectors):
            u.reg_write(UC_X86_REG_XMM0+i, value)
        u.reg_write(UC_X86_REG_MXCSR, 0x1f80)
        reached = []
        def boundary(cpu, address, size, data):
            if address in (CALLER, sweep.CYLINDER_SITE+6):
                reached.append(address)
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, boundary)
        u.emu_start(sweep.CYLINDER_SITE, 0, count=2000)
        self.assertEqual(len(reached), 1)
        self.assertEqual([u.reg_read(UC_X86_REG_XMM0+i) for i in range(8)], vectors)
        self.assertEqual(u.reg_read(UC_X86_REG_MXCSR), 0x1f80)
        return u, reached[0]

    def test_short_cylinder_top_side_tangent_and_empty_space(self):
        # Known geometric contacts, including the deliberately open bottom.
        cap = ((2000*24*0xaaa >> 16)-1000) / (
            (2000*24*0xaaa >> 16)-(0*24*0xaaa >> 16))
        cases = (
            ((0, 0, 2000), (0, 0, 0), cap),
            ((10001, 0, 2000), (10001, 0, 0), None),
            ((0, 0, 2000), (0, 0, 1500), None),
            ((0, 0, -2000), (0, 0, 2000), 0),
            ((10200, 0, 0), (9800, 0, 0), .5),
            ((10000, -200, 0), (10000, 200, 0), .5),
            ((10001, -200, 0), (10001, 200, 0), None),
            ((0, 0, 0), (0, 0, 0), 0),
        )
        for start, end, fraction in cases:
            with self.subTest(start=start, end=end):
                u, reached = self.cylinder(start, end)
                self.assertEqual(reached, CALLER)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX)&255, int(fraction is not None))
                self.assertEqual(get(u, FRAME+64),
                                 0xdeadbeef if fraction is None else int(fraction*65536))
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK+28)
                self.assertEqual(u.reg_read(UC_X86_REG_EBP), 123)
                self.assertEqual(u.reg_read(UC_X86_REG_ESI), 456)
                self.assertEqual(u.reg_read(UC_X86_REG_EDI), 789)

    def test_short_cylinder_uses_overlap_of_height_and_radial_intervals(self):
        # Enter the radius halfway through, but reach the top only near the end.
        u, _ = self.cylinder((10200, 0, 5000), (9800, 0, 0))
        z0 = 5000*24*0xaaa >> 16
        self.assertEqual(get(u, FRAME+64), int((z0-1000)/z0*65536))
        # Leave the radius halfway through, before descending below the top.
        u, _ = self.cylinder((9800, 0, 5000), (10200, 0, 0))
        self.assertEqual(u.reg_read(UC_X86_REG_EAX)&255, 0)

    def test_ordinary_cylinder_segments_reach_original_body_unchanged(self):
        u, reached = self.cylinder((20000, 100, 2000), (0, 100, 0))
        self.assertEqual(reached, sweep.CYLINDER_SITE+6)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), FRAME)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), FRAME+32)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 20000)
        self.assertEqual(u.reg_read(UC_X86_REG_ECX), 100)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK-52)
        self.assertEqual(get(u, FRAME+64), 0xdeadbeef)

    def test_projectile_exclusion_is_scoped_and_source_body_is_preserved(self):
        """A turret hit can leave its ID in scratch slot zero for the next shot.

        Execute the maintained wrapper around modeled world/mesh boundaries.
        Check both boundaries see the intended exclusion, then verify restoration,
        result, stack and saved registers. Live collision evidence is kept privately.
        """
        mesh = 0x1600000
        for caller in (0x2d96da, 0x123456):
            for body in (0, 1, 59):
                for stale in (0, 38, 299):
                    with self.subTest(caller=caller, body=body, stale=stale):
                        u = Uc(UC_ARCH_X86, UC_MODE_32)
                        u.mem_map(0, 0x2000000)
                        for address, code in sweep.vehicle_bodies(mesh, ()):
                            u.mem_write(address, code)
                        # World query uses callee cleanup; the mesh uses caller cleanup.
                        u.mem_write(sweep.VEHICLE_TRAMP, asm(sweep.VEHICLE_TRAMP, 'mov eax,-1;ret 28;'))
                        u.mem_write(mesh, asm(mesh, 'mov eax,38;ret;'))
                        put(u, 0x4464b8, stale | (77 << 16))
                        args = (caller, 0x1000, 150912, body, body, FRAME+0x30, FRAME+0x34, FRAME+0x38)
                        u.mem_write(STACK, struct.pack('<8I', *args))
                        for reg, val in ((UC_X86_REG_ESP, STACK), (UC_X86_REG_EBP, FRAME),
                                         (UC_X86_REG_EAX, FRAME+0x10), (UC_X86_REG_EDX, FRAME+0x20),
                                         (UC_X86_REG_ESI, 123), (UC_X86_REG_EDI, 456)):
                            u.reg_write(reg, val)
                        seen = []
                        def boundary(cpu, address, size, data):
                            if address in (sweep.VEHICLE_TRAMP, mesh):
                                seen.append(get(cpu, 0x4464b8))
                        u.hook_add(UC_HOOK_CODE, boundary)
                        u.emu_start(sweep.VEHICLE_CODE, caller, count=1000)
                        expected = 0 if caller == 0x2d96da and body == 0 else stale
                        self.assertEqual(seen, [expected | (77 << 16)] * 2)
                        self.assertEqual(get(u, 0x4464b8), stale | (77 << 16))
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 38)
                        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK+32)
                        self.assertEqual(u.reg_read(UC_X86_REG_EBP), FRAME)
                        self.assertEqual(u.reg_read(UC_X86_REG_ESI), 123)
                        self.assertEqual(u.reg_read(UC_X86_REG_EDI), 456)

    def test_projectile_counts_ceil_cells_and_retains_true_segment_limit(self):
        for step in (0x10000, 0x18000, 0x34000):
            for length in (0, 1, step - 1, step, step + 1, 3 * step, 3 * step + 17):
                x = Fixture()
                self.assertEqual(x.query(length, step), 0x311563)
                self.assertEqual(get(x.u, FRAME + 0x56), (length + step - 1) // step)
                self.assertEqual(get(x.u, sweep.STATE), 1)
                self.assertEqual(get(x.u, sweep.STATE + 4), length)
                self.assertEqual(x.run(sweep.LIMIT), 0x3119cc)
                self.assertEqual(x.u.reg_read(UC_X86_REG_EAX), length)
                self.assertEqual(x.u.reg_read(UC_X86_REG_EDX), length)

    def test_nonpositive_segment_has_no_cells(self):
        for length in (0, -1, -65536):
            x = Fixture()
            x.query(length)
            self.assertEqual(get(x.u, FRAME + 0x56), 0)

    def test_nonprojectile_callers_keep_original_sampling_and_limit(self):
        for caller, outer in ((0x2d96db, 0x2f07c6), (0x2d96da, 0x2f07c7)):
            x = Fixture()
            self.assertEqual(x.query(0x38000, 0x18000, caller, outer), 0x311555)
            self.assertEqual(get(x.u, sweep.STATE), 0)
            self.assertEqual(get(x.u, FRAME + 0x56), 0xdeadbeef)
            self.assertEqual(x.u.reg_read(UC_X86_REG_EAX), 0x38000)
            self.assertEqual(x.u.reg_read(UC_X86_REG_EDX), 0x38000)
            put(x.u, STACK + 0x40, 2)
            self.assertEqual(x.run(sweep.LIMIT), 0x3119ca)
            self.assertEqual(x.u.reg_read(UC_X86_REG_EAX), 0x30000)

    def test_each_query_clears_previous_projectile_classification(self):
        x = Fixture()
        x.query(0x18000)
        self.assertEqual(get(x.u, sweep.STATE), 1)
        x.query(0x18000, caller=0x12345)
        self.assertEqual(get(x.u, sweep.STATE), 0)

    def test_vehicle_wrapper_recognizes_only_original_projectile_ancestor(self):
        for wrapped, caller, parent, expected in (
            (False, VEHICLE_CALL + 5, 0x2d96da, False), (True, VEHICLE_CALL + 5, 0x2d96da, True),
            (True, VEHICLE_CALL + 5, 0x123456, False), (True, VEHICLE_CALL + 6, 0x2d96da,
                                                        False), (True, 0x2d96da, 0x123456, True)
        ):
            x = Fixture(wrapped)
            x.query(0x18001, caller=caller, parent=parent)
            self.assertEqual(get(x.u, sweep.STATE), int(expected))
            if expected:
                self.assertEqual(get(x.u, FRAME + 0x56), 2)

    def test_helper_preserves_unrelated_registers_and_flags(self):
        x = Fixture(True)
        u = x.u
        for reg, val in ((UC_X86_REG_ECX, 23), (UC_X86_REG_ESI, 42), (UC_X86_REG_EDI, 91)):
            u.reg_write(reg, val)
        u.reg_write(UC_X86_REG_EFLAGS, 0x202)
        x.query(0x30000, caller=VEHICLE_CALL + 5)
        for reg, val in (
            (UC_X86_REG_ECX, 23), (UC_X86_REG_ESI, 42), (UC_X86_REG_EDI, 91),
            (UC_X86_REG_EBP, FRAME)
        ):
            self.assertEqual(u.reg_read(reg), val)
        # The displaced original arithmetic changes arithmetic flags; IF stays intact.
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS) & 0x200, 0x200)

    def test_physics_remainder_consumed_once_and_replenished_next_tick(self):
        for remainder in (0, 1, 65535, 0xfffffffe):
            x = Fixture()
            u = x.u
            acc = FRAME + 0x300
            put(u, acc, 100)
            put(u, physics.REMAINDER, remainder)
            put(u, 0x453991, 0x12345678)
            u.reg_write(UC_X86_REG_EDX, acc)
            for expected in ((100 + remainder) & 0xffffffff, ) * 3:
                x.run(physics.BRIDGE)
                self.assertEqual(get(u, acc), expected)
                self.assertEqual(get(u, physics.REMAINDER), 0)
                self.assertEqual(u.reg_read(UC_X86_REG_EDI), 0x12345678)
            put(u, physics.REMAINDER, 17)
            x.run(physics.BRIDGE)
            self.assertEqual(get(u, acc), (100 + remainder + 17) & 0xffffffff)


if __name__ == '__main__':
    unittest.main()
