"""Check the visual endpoint correction independently of collision decisions.

Tracing an incoming Tripulsar showed that the original mobile-body query can
return an endpoint beside the incoming ray. These invented coordinates exercise
the assembled trail hook and its original calling convention. The renderer is
represented by a recorder; captured-game replay supplies separate integration
evidence. These tests do not claim that every weapon has been visually checked.
"""
import math
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
from features import effect_timing as effects


class BeamImpact(unittest.TestCase):
    def run_case(self, start, end, direction, *, hit=1, result=12):
        cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        cpu.mem_map(0, 0x2000000)
        for address, body in effects.beam_impact_bodies():
            cpu.mem_write(address, body)
        cpu.mem_write(0x28d730, b'\xc2\x10\x00')  # Original trail's RET 16.
        stack, stop, projectile = 0x1800000, 0x1801000, 0x1802000
        cpu.mem_write(projectile, bytes(range(30)))
        cpu.mem_write(projectile + 10, struct.pack('<3i', *direction))
        cpu.mem_write(stack, struct.pack('<Ii3i', stop, start[2], *end))
        cpu.mem_write(stack + 60, struct.pack('<i', result))
        cpu.mem_write(stack + 72, bytes([hit]))
        original_projectile = bytes(cpu.mem_read(projectile, 30))
        original_frame = bytes(cpu.mem_read(stack + 20, 64))
        registers = {
            UC_X86_REG_EAX: 29, UC_X86_REG_EDX: 0x395110,
            UC_X86_REG_EBX: start[0] & 0xffffffff,
            UC_X86_REG_ECX: start[1] & 0xffffffff,
            UC_X86_REG_EBP: projectile, UC_X86_REG_ESI: 123,
            UC_X86_REG_EDI: 456, UC_X86_REG_EFLAGS: 0x246,
            UC_X86_REG_MXCSR: 0x5f80,
        }
        for index in range(8):
            registers[UC_X86_REG_XMM0 + index] = int.from_bytes(bytes([index + 1]) * 16, 'little')
        for register, value in registers.items():
            cpu.reg_write(register, value)
        cpu.reg_write(UC_X86_REG_ESP, stack)
        calls = []

        def trail(u, address, size, data):
            calls.append(struct.unpack('<3i', u.mem_read(stack + 8, 12)))

        cpu.hook_add(UC_HOOK_CODE, trail, begin=0x28d730, end=0x28d730)
        cpu.emu_start(effects.BEAM_IMPACT, stop, count=1000)
        self.assertEqual(cpu.reg_read(UC_X86_REG_EIP), stop)
        self.assertEqual(cpu.reg_read(UC_X86_REG_ESP), stack + 20)
        self.assertEqual(len(calls), 1)
        for register, value in registers.items():
            self.assertEqual(cpu.reg_read(register), value, register)
        self.assertEqual(bytes(cpu.mem_read(projectile, 30)), original_projectile)
        self.assertEqual(bytes(cpu.mem_read(stack + 20, 64)), original_frame)
        return calls[0]

    def test_body_hit_ends_on_incoming_ray_across_axes_and_large_coordinates(self):
        for start, end, direction in (
            ((100, 200, 300), (180, 250, 290), (65536, 0, 0)),
            ((100, 200, 300), (110, 280, 290), (0, 65536, 0)),
            ((100, 200, 300), (110, 220, 210), (0, 0, -65536)),
            ((27000000, 18000000, -900000), (26996200, 17997500, -898600), (-46000, -40000, 23000)),
            ((-27000000, -18000000, 900000), (-26996200, -17997500, 898600), (46000, 40000, -23000)),
        ):
            with self.subTest(direction=direction):
                actual = self.run_case(start, end, direction)
                delta = [b-a for a, b in zip(start, end)]
                fraction = sum(a*b for a, b in zip(delta, direction)) / sum(v*v for v in direction)
                expected = [a + fraction*v for a, v in zip(start, direction)]
                self.assertLess(math.dist(actual, expected), 2)

    def test_misses_and_non_body_contacts_keep_the_original_endpoint(self):
        start, end, direction = (100, 200, 300), (180, 250, 290), (65536, 0, 0)
        for hit, result in ((0, 12), (1, 0), (1, -1)):
            with self.subTest(hit=hit, result=result):
                self.assertEqual(self.run_case(start, end, direction, hit=hit, result=result), end)

    def test_zero_direction_and_contact_behind_start_are_bounded(self):
        self.assertEqual(self.run_case((1, 2, 3), (4, 5, 6), (0, 0, 0)), (4, 5, 6))
        self.assertEqual(self.run_case((1, 2, 3), (-4, 5, 6), (65536, 0, 0)), (1, 2, 3))

    def test_code_fits_the_existing_reserved_gap(self):
        body = dict(effects.beam_impact_bodies())[effects.BEAM_IMPACT]
        self.assertLessEqual(effects.BEAM_IMPACT + len(body), effects.BEAM_PRESSURE)


if __name__ == '__main__':
    unittest.main()
