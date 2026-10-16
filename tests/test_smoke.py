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


class SmokeHooks(unittest.TestCase):

    def machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        for address, data in f.bodies(f.LOW, ()):
            u.mem_write(address, data)
        return u

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
