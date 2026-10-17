"""Smoke regression checks for invisible obstructions and distant tiny puffs.

The geometry cases use deliberately arranged particles and a modeled transform,
so their expected contact distances are independent of the game renderer. The
compiled helper is loaded from a verified local build with test.py --helpers.
The installation and display-hook checks also run without compiled helpers.
Captured combat/render comparisons are recorded separately in docs/testing.md.
"""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
from features import smoke as f, projectiles

STACK, STOP, DATA = 0x1800000, 0x1801000, 0x1900000
MOBILE = 32484448


def call(u, entry, args=(), regs=None, stop=STOP):
    u.mem_write(
        STACK, struct.pack('<' + 'I' * (len(args) + 1), STOP, *[v & 0xffffffff for v in args])
    )
    u.reg_write(UC_X86_REG_ESP, STACK)
    for reg, value in (regs or {}).items():
        u.reg_write(reg, value & 0xffffffff)
    u.emu_start(entry, stop, count=1000000)
    if u.reg_read(UC_X86_REG_EIP) != stop:
        raise AssertionError('Smoke routine did not return')
    return struct.unpack('<i', struct.pack('<I', u.reg_read(UC_X86_REG_EAX)))[0]


def put(u, address, *values):
    u.mem_write(address, struct.pack('<' + 'I' * len(values), *[v & 0xffffffff for v in values]))


class SmokeBudget(unittest.TestCase):
    """Replay the retail allocator that used to thin clouds during unrelated fire.

    Invented groups contain recognizable particle records. The retained allocator,
    compactor and particle-deletion code run from the verified retail executable;
    expected survivors are computed independently from the published thinning rule.
    These checks establish pool behavior, not appearance or battle frame rate.
    """

    def machine(self, groups, capacity=4096, patched=True):
        from original_inputs import original_ram
        if not any(original_ram[0x2a414c:0x2a43ad]):
            self.skipTest('Supply the verified retail executable for particle-pool checks')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(0x2a414c, bytes(original_ram[0x2a414c:0x2a43ad]))
        if patched:
            bodies = dict(f.bodies(f.LOW, ()))
            for address in (f.THIN_SITE, f.THIN_FILTER, *f.CAPACITY_SITES, f.CAPACITY_QUERY):
                u.mem_write(address, bodies[address])
        for address, value in ((0x421a08, 64), (0x421a0c, len(groups)),
                               (0x421a24, capacity), (0x421a14, DATA),
                               (0x421a1c, DATA + 0x1000), (0x421a00, DATA + 0x2000),
                               (0x421a04, DATA + 0x3000), (0x421a20, DATA + 0x10000),
                               (0x35c270, 2)):
            put(u, address, value)
        end = 0
        for group, (mode, count) in enumerate(groups):
            u.mem_write(DATA + 0x1000 + group * 16 + 14, bytes((mode,)))
            for particle in range(count):
                put(u, DATA + 0x10000 + end * 12, group, particle, 0x12345678)
                end += 1
            put(u, DATA + 4 * (group + 1), end)
        self.assertLessEqual(end, capacity)
        u.mem_write(DATA + 0x10000 + capacity * 12, b'GUARD' * 8)
        return u

    def particles(self, u):
        count = struct.unpack('<I', u.mem_read(0x421a0c, 4))[0]
        ends = struct.unpack('<' + 'I' * (count + 1), u.mem_read(DATA, 4 * (count + 1)))
        return [bytes(u.mem_read(DATA + 0x10000 + a * 12, (b - a) * 12)) if b > a else b''
                for a, b in zip(ends, ends[1:])]

    def test_thinning_preserves_smoke_records_and_compacts_other_modes(self):
        groups = [(mode, 7 + mode) for mode in range(12)]
        for patched in (False, True):
            u = self.machine(groups, patched=patched)
            expected = self.particles(u)
            for repeat in range(5):
                source_index = 0
                next_expected = []
                for (mode, _), records in zip(groups, expected):
                    kept = []
                    for offset in range(0, len(records), 12):
                        if (patched and mode in (0, 1, 8)) or source_index & 2:
                            kept.append(records[offset:offset + 12])
                        source_index += 1
                    next_expected.append(b''.join(kept))
                call(u, 0x2a420c, regs={UC_X86_REG_EAX: 2})
                self.assertEqual(self.particles(u), next_expected, (patched, repeat))
                expected = next_expected

    def test_repeated_weapon_allocations_leave_existing_smoke_intact(self):
        for capacity in (1024, 4096):
            groups = [(mode, capacity // 8) for mode in (0, 3, 8, 11, 1, 3, 3, 3)]
            u = self.machine(groups, capacity)
            smoke = {i: records for i, records in enumerate(self.particles(u))
                     if groups[i][0] in (0, 1, 8)}
            for repeat in range(48):
                group = call(u, 0x2a42c8, regs={UC_X86_REG_EAX: 159})
                self.assertEqual(group, 8 + repeat)
                u.mem_write(DATA + 0x1000 + group * 16 + 14, b'\x03')
                records = self.particles(u)
                self.assertEqual({i: records[i] for i in smoke}, smoke)
                self.assertLessEqual(sum(map(len, records)), capacity * 12)
                self.assertEqual(bytes(u.mem_read(DATA + 0x10000 + capacity * 12, 40)),
                                 b'GUARD' * 8)

    def test_full_smoke_pool_limits_new_effects_and_still_allows_particle_deletion(self):
        u = self.machine([(0, 1024), (1, 1024), (8, 2048)])
        before = self.particles(u)
        self.assertEqual(call(u, 0x2a42c8, regs={UC_X86_REG_EAX: 159}), 3)
        self.assertEqual(self.particles(u), before + [b''])
        # Actual particle deletion remains effective; the protection applies
        # only to pressure thinning, not age, impacts or normal cloud cleanup.
        call(u, 0x2a414c, regs={UC_X86_REG_EAX: 0, UC_X86_REG_EDX: 0})
        self.assertEqual(len(self.particles(u)[0]), 1023 * 12)
        self.assertEqual(call(u, 0x2a42c8, regs={UC_X86_REG_EAX: 159}), 4)
        self.assertEqual(len(self.particles(u)[4]), 12)
        self.assertEqual(bytes(u.mem_read(DATA + 0x10000 + 4096 * 12, 40)), b'GUARD' * 8)

    def test_full_group_table_rejects_new_group_without_touching_smoke(self):
        u = self.machine([(0, 4)] * 64)
        before = self.particles(u)
        self.assertEqual(call(u, 0x2a42c8, regs={UC_X86_REG_EAX: 159}), -1)
        self.assertEqual(self.particles(u), before)

    def test_visual_only_allocations_keep_original_particle_density(self):
        # A larger backing allocation must not delay the original thinning.
        # Railgun trails otherwise retain dense old puffs until the group table
        # fills. Compare actual allocator/compactor output, not just a limit.
        original = self.machine([(10, 64)] * 12, capacity=1024, patched=False)
        guarded = self.machine([(10, 64)] * 12, capacity=4096)
        for repeat in range(40):
            groups = [call(u, 0x2a42c8, regs={UC_X86_REG_EAX: 64})
                      for u in (original, guarded)]
            self.assertEqual(groups[0], groups[1])
            for u, group in zip((original, guarded), groups):
                u.mem_write(DATA + 0x1000 + group * 16 + 14, b'\x0a')
            self.assertEqual(self.particles(guarded), self.particles(original), repeat)

    def test_capacity_query_counts_smoke_and_ignores_empty_group_modes(self):
        cases = [([], 4096, 1024), ([(10, 600)], 4096, 1024),
                 ([(0, 300), (1, 400), (8, 500), (10, 600)], 4096, 2224),
                 ([(8, 4000)], 4096, 4096), ([(8, 400)], 1024, 1024),
                 ([(0, 0), (1, 0), (8, 0), (10, 64)], 4096, 1024)]
        for groups, capacity, expected in cases:
            u = self.machine(groups, capacity)
            regs = {UC_X86_REG_EBX: 19, UC_X86_REG_ECX: 23, UC_X86_REG_EDX: 29,
                    UC_X86_REG_ESI: 31, UC_X86_REG_EDI: 37, UC_X86_REG_EBP: 41}
            u.reg_write(UC_X86_REG_EFLAGS, 0x246)
            self.assertEqual(call(u, f.CAPACITY_QUERY, regs=regs), expected)
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x246)
            self.assertEqual({r: u.reg_read(r) for r in regs}, regs)


class SmokeHooks(unittest.TestCase):

    def machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        for address, data in f.bodies(f.LOW, ()):
            u.mem_write(address, data)
        return u

    def test_smoke_circle_shape_with_original_raster_and_clipping(self):
        # Execute the retained raster, rather than just checking a new operand.
        # This small mask has independent, explicitly specified row spans.
        from original_inputs import original_ram
        if not any(original_ram[0x2a6478:0x2a6b44]):
            self.skipTest('Supply the verified retail executable for raster checks')
        u = self.machine()
        u.mem_write(0x2a6478, bytes(original_ram[0x2a6478:0x2a6b44]))
        for start, end in ((0x2e7df0, 0x2e7e08), (0x2f0e80, 0x2f1000)):
            u.mem_write(start, bytes(original_ram[start:end]))
        mask = bytes((4, 4, 8, 3, 1, 1, 6, 0, 8, 0, 8, 0, 8, 0, 8, 1, 6, 3, 1))
        u.mem_write(DATA + 0x100, mask)
        put(u, 0x423730 + 8 * 4, DATA + 0x100)
        put(u, 0x423230 + 8 * 4, 0)
        pixels = DATA + 0x1000

        def draw(entry, height, mode, x, logical=False):
            canvas = 0x446f78 if logical else DATA
            u.mem_write(canvas, bytes(64))
            put(u, 0x44b1a0, canvas)
            put(u, canvas, pixels)
            u.mem_write(canvas + 8, struct.pack('<3H', 256, height, 256))
            put(u, canvas + 0x34, 256 << 16, height << 16)
            put(u, f.DRAW_MODE, mode)
            u.mem_write(pixels, bytes(256 * height))
            call(u, entry, regs={UC_X86_REG_EAX: x, UC_X86_REG_EDX: 50,
                                UC_X86_REG_EBX: 7 << 15, UC_X86_REG_ECX: 8})
            image = bytes(u.mem_read(pixels, 256 * height))
            return {(n % 256, n // 256) for n, value in enumerate(image) if value}

        for height in (200, 400, 768):
            for mode in (0, 1, 2, 7, 8, 11):
                for x in (0, 100, 255):
                    old = draw(0x2a6af8, height, mode, x)
                    new = draw(f.CODE + 0x700, height, mode, x)
                    if height <= 200 or mode not in (0, 1, 8):
                        self.assertEqual(new, old)
                    else:
                        # Reference uses the explicit mask, with x doubled and
                        # original two-row vertical repetition, then clips.
                        expected = set()
                        for row in range(8):
                            start, count = mask[3 + row * 2:5 + row * 2]
                            count *= 2
                            left = x - 8 + start * 2
                            # The retained raster reserves its rightmost column.
                            if left + count >= 256:
                                count = 255 - left
                            for dx in range(count):
                                xx = x - 8 + start * 2 + dx
                                for dy in (0, 1):
                                    if 0 <= xx < 256:
                                        expected.add((xx, 42 + row * 2 + dy))
                        self.assertEqual(new, expected)
        self.assertEqual(draw(f.CODE + 0x700, 400, 8, 100, True),
                         draw(0x2a6af8, 400, 8, 100, True))

    def test_installation_is_atomic_and_idempotent(self):
        for conflict in (None, f.LOW, f.END - 1, *f.SITES):
            ram = bytearray(0x2000000)
            for address, data in f.SITES.items():
                ram[address:address + len(data)] = data
            post = dict(projectiles.vehicle_bodies(MOBILE, ()))[projectiles.VEHICLE_POST]
            ram[projectiles.VEHICLE_POST:projectiles.VEHICLE_POST + len(post)] = post
            if conflict is not None:
                ram[conflict] ^= 1
            writes = []

            def write(a, b):
                writes.append(a)
                ram[a:a + len(b)] = b

            options = dict(entry=f.LOW, regions=((f.LOW, b'\xc3'), ), mobile_entry=MOBILE)
            read = lambda a, n: ram[a:a + n]
            if conflict is not None:
                with self.assertRaises(ValueError):
                    f.install(write, read, **options)
                self.assertFalse(writes)
            else:
                f.install(write, read, **options)
                self.assertTrue(f.verify(read, **options))
                writes.clear()
                f.install(write, read, **options)
                self.assertFalse(writes)

    def test_mission_scenery_reset_preserves_smoke_code_and_state(self):
        # Execute the game's actual table-clear calls with the widened scenery
        # operands. A blank cold image hid a collision with this live storage.
        from original_inputs import original_ram
        from features import terrain_distance as terrain
        if not any(original_ram[0x298ccb:0x298cdc]):
            self.skipTest('Requires the original retail executable')
        u = self.machine()
        u.mem_write(0x298ccb, bytes(original_ram[0x298ccb:0x298cfe]))
        u.mem_write(0x2e7df0, bytes(original_ram[0x2e7df0:0x2e7e08]))
        u.mem_write(0x2f0e80, bytes(original_ram[0x2f0e80:0x2f1000]))
        for address, data in terrain.instance_bodies():
            u.mem_write(address, data)
        put(u, f.STATE, 123, 456)
        before = bytes(u.mem_read(f.LOW, f.END - f.LOW))
        for entry, end, table, size in (
            (0x298ccb, 0x298cdc, terrain.INSTANCE_TABLE, terrain.INSTANCE_TABLE_SIZE),
            (0x298ced, 0x298cfe, terrain.INSTANCE_BITS, terrain.INSTANCE_BITS_SIZE),
        ):
            self.assertTrue(f.END <= table or f.LOW >= table + size)
            u.mem_write(table, b'\xa5' * size)
            call(u, entry, stop=end)
            self.assertEqual(bytes(u.mem_read(table, size)), bytes(size))
            self.assertEqual(bytes(u.mem_read(f.LOW, f.END - f.LOW)), before)

    def test_runtime_storage_overlap_is_rejected_even_when_empty(self):
        from unittest.mock import patch
        with patch.object(f, 'LOW', f.terrain_distance.INSTANCE_TABLE):
            with self.assertRaisesRegex(ValueError, 'declared host gap'):
                f.install(
                    lambda a, b: self.fail('Wrote before validation'),
                    lambda a, n: bytes(n),
                    entry=f.LOW,
                    regions=(),
                    mobile_entry=MOBILE
                )

    def test_smoke_sizes_scale_without_changing_other_effects(self):
        u = self.machine()
        put(u, 0x44b1a0, DATA)
        for width in (160, 320, 640, 1280):
            u.mem_write(DATA + 8, struct.pack('<H', width))
            for mode in range(12):
                for inverse in (-8819234, -1, 0, 1000, 7000, 65536, 0x7fffffff):
                    with self.subTest(width=width, mode=mode, inverse=inverse):
                        call(
                            u,
                            f.CODE + 0x500,
                            regs={
                                UC_X86_REG_EAX: mode,
                                UC_X86_REG_EDI: inverse,
                                UC_X86_REG_EDX: 0x123456
                            },
                            stop=0x2a59fa
                        )
                        expected = min(
                            inverse * width // 320, 0x20000
                        ) if mode in (0, 1, 8) and width > 320 and inverse > 0 else inverse
                        self.assertEqual(u.reg_read(UC_X86_REG_EDI), expected & 0xffffffff)
                        self.assertEqual(u.reg_read(UC_X86_REG_ECX), (expected * 4) & 0xffffffff)
                        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 0x123456)
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX), mode)

    def test_distance_extension_is_limited_to_main_view_clouds(self):
        u = self.machine()
        for canvas, kind, before, expected in (
            (0x9c34e8, 797, 160, 384), (0x9c34e8, 797, 500, 500), (DATA, 797, 160, 160),
            (0x9c34e8, 796, 160, 160)
        ):
            put(u, 0x44b1a0, canvas)
            call(
                u,
                f.CODE + 0x600,
                regs={
                    UC_X86_REG_ECX: kind,
                    UC_X86_REG_EBX: before
                },
                stop=f.terrain_distance.SCENERY_CODE
            )
            self.assertEqual(u.reg_read(UC_X86_REG_EBX), expected)

    def test_projectile_generations_change_on_slot_reuse(self):
        u = self.machine()
        for expected in (1, 2):
            call(u, f.CODE + 0x100, regs={UC_X86_REG_EAX: 31}, stop=0x2d9540)
            self.assertEqual(
                struct.unpack('<I', u.mem_read(f.SHOT_SERIAL + 31 * 4, 4))[0], expected
            )
        u.mem_write(DATA, struct.pack('<H', 31 | 0x8000))
        call(u, f.CODE, regs={UC_X86_REG_EBP: DATA}, stop=0x2f074c)
        self.assertEqual(struct.unpack('<I', u.mem_read(f.STATE + 4, 4))[0], 2)


class SmokeGeometry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import collision_smoke
        except ImportError:
            raise unittest.SkipTest('Use --helpers with a verified local engine helper build')
        cls.helper = collision_smoke

    def machine(self, count=400, mode=8):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        for a, b in self.helper.REGIONS:
            u.mem_write(a, b)
        for a, v in (
            (0x421a08, 64), (0x421a0c, 1), (0x421a18, DATA), (0x421a1c, DATA + 0x1000),
            (0x421a14, DATA + 0x2000), (0x421a20, DATA + 0x3000), (0x421a24, 1024)
        ):
            put(u, a, v)
        put(u, DATA, 0)
        put(u, DATA + 0x2000, 0, count)
        u.mem_write(DATA + 0x100e, bytes((mode, )))
        self.matrix = [256, 0, 0, 0, 256, 0, 0, 0, 256, 0, 0, 0]

        def model(cpu, a, n, d):
            sp = cpu.reg_read(UC_X86_REG_ESP)
            ret, arg1, arg2 = struct.unpack('<3I', cpu.mem_read(sp, 12))
            if a == f.CODE + 0x200:
                cpu.mem_write(arg2, struct.pack('<12i', *self.matrix))
            elif a == MOBILE:
                cpu.reg_write(UC_X86_REG_EAX, arg2)  # preserve prior world result
            else:
                return
            cpu.reg_write(UC_X86_REG_ESP, sp + 4)
            cpu.reg_write(UC_X86_REG_EIP, ret)

        for a in (f.CODE + 0x200, MOBILE):
            u.hook_add(UC_HOOK_CODE, model, begin=a, end=a)
        return u

    def contact(self, u, start=(-20000, 0, 0), length=40000, shot=1, identity=1):
        put(u, DATA + 0x7000, *[v * 6 for v in start], 65536, 0, 0, length * 6, 0)
        return call(u, self.helper.TEST, (0, DATA + 0x7000, shot, identity))

    def test_finite_puffs_have_no_invisible_column(self):
        u = self.machine()
        self.assertAlmostEqual(self.contact(u), int((20000 - 8192) / 40000 * 65536), delta=1)
        self.assertEqual(self.contact(u, start=(-20000, 8193, 0)), -1)
        self.assertEqual(self.contact(u, start=(-20000, 0, -8193)), -1)
        self.assertEqual(self.contact(u, start=(-20000, 0, 8193)), -1)
        self.assertEqual(self.contact(u, start=(0, 0, 0)), 0)
        self.assertEqual(self.contact(u, length=10000), -1)
        self.assertEqual(self.contact(u, start=(-20000, 8192, 0)), 32768)
        self.matrix[11] = 50000
        self.assertEqual(self.contact(u), -1)
        self.assertGreaterEqual(self.contact(u, start=(-20000, 0, 50000)), 0)

    def test_particle_positions_rotation_and_expiry_are_used(self):
        u = self.machine(count=400)
        for i in range(400):
            u.mem_write(DATA + 0x3000 + i * 12, struct.pack('<3h', 0, 25000, 0))
        self.assertEqual(self.contact(u), -1)
        self.matrix[:9] = [0, 256, 0, -256, 0, 0, 0, 0, 256]
        self.assertGreaterEqual(self.contact(u, length=60000), 0)
        put(u, DATA + 0x2000, 400, 400)
        self.assertEqual(self.contact(u, length=60000), -1)
        put(u, DATA, -1)
        self.assertEqual(self.contact(u), -1)

    def test_non_smoke_modes_do_not_block(self):
        u = self.machine()
        for mode in range(12):
            u.mem_write(DATA + 0x100e, bytes((mode, )))
            hit = self.contact(u)
            self.assertEqual(hit >= 0, mode in (0, 1, 8))

    def test_segment_count_does_not_multiply_density_chances(self):
        u = self.machine(count=12)
        for shot in range(1, 31):
            expected = self.contact(u, shot=shot) >= 0
            for pieces in (1, 2, 3, 6, 12, 24):
                found = False
                for i in range(pieces):
                    start = -24000 + 48000 * i // pieces
                    found |= self.contact(
                        u, start=(start, 0, 0), length=48000 // pieces, shot=shot
                    ) >= 0
                self.assertEqual(found, expected, (shot, pieces))
        rolls = [call(u, self.helper.ROLL, (shot, 1, 12)) for shot in range(1, 1001)]
        self.assertGreater(sum(rolls), 10)
        self.assertLess(sum(rolls), 55)

    def test_world_postpass_preserves_nearer_solids_and_returns_nearest_cloud(self):
        u = self.machine()
        o = 0x3c3240 + 10 * 37
        u.mem_write(o, bytes((1, 6, 29, 1, 0)))
        put(u, 0x1e20000 + 44 + 10, 0)
        u.mem_write(0x1e20000 + 44 + 42, b'\x08')
        ray, point, out1, out2, flag = (
            DATA + 0x7000, DATA + 0x7100, DATA + 0x7200, DATA + 0x7204, DATA + 0x7208
        )
        put(u, ray, -120000, 0, 0, 65536, 0, 0, 240000, 0)
        for nearer in (False, True):
            put(u, point, -100000 if nearer else 120000, 0, 0)
            put(u, out1, 0, 0, 1 if nearer else 0)
            put(u, f.STATE + 4, 1)
            result = call(
                u, self.helper.ENTRY, (ray, 23 if nearer else -1, point, out1, out2, flag)
            )
            self.assertEqual(result, 23 if nearer else -1)
            self.assertEqual(struct.unpack('<I', u.mem_read(out1, 4))[0], 0 if nearer else 10)
            self.assertEqual(struct.unpack('<I', u.mem_read(f.STATE + 4, 4))[0], 0)
