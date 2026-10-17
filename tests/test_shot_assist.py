"""Execute the optional camera-ray correction without proprietary game data."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import shot_assist as f
from patch_support import asm
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import *

STOP = 0x10000
STACK = 0x1c00000
POINT = 0x1800000
DIRECTION = POINT + 16
pack = lambda n: struct.pack('<I', n & 0xffffffff)


def machine(enabled):
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(0, 0x2000000)
    for a, b in f.bodies():
        u.mem_write(a, b)
    u.mem_write(f.STATE, pack(1) + pack(enabled))
    u.reg_write(UC_X86_REG_MXCSR, 0x1f80)
    return u


def call(u, address, args=(), registers=()):
    u.mem_write(STACK, pack(STOP) + b''.join(pack(x) for x in args))
    u.reg_write(UC_X86_REG_ESP, STACK)
    for reg, value in registers:
        u.reg_write(reg, value & ((1 << 128) - 1))
    u.emu_start(address, STOP, count=100000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP


class ShotAssistTests(unittest.TestCase):

    def test_original_body_depth_and_surface_output(self):
        # Independent axis-aligned geometry: a radius-five sphere whose centre
        # is ten units ahead has entry depth six at lateral distance three.
        # Tangency/tolerated grazes use depth ten; starting inside uses the exit.
        # Exercise all world axes/signs, translated coordinates and physics IDs.
        for axis in range(3):
            for sign in (-1, 1):
                for physics_id, slot in ((1, 0), (37, 62), (95, 95)):
                    for lateral, forward, expected in ((3, 10, 6), (5, 10, 10),
                                                       (6, 10, 10), (0, 2, 7),
                                                       (3, 100, 96), (3, 1000, 996)):
                        for enabled in (0, 1):
                            u = machine(enabled)
                            origin = [140000003, -100000007, 50000001]
                            direction = [0, 0, 0]
                            direction[axis] = sign * 65536
                            centre = origin[:]
                            centre[axis] += sign * forward * 65536
                            centre[(axis + 1) % 3] += lateral * 65536
                            endpoint = [a-b for a,b in zip(centre, direction)]
                            u.mem_write(POINT, struct.pack('<3i', *origin))
                            u.mem_write(DIRECTION, struct.pack('<3i', *direction))
                            u.mem_write(0x44e0cc, struct.pack('<3i', *direction))
                            u.mem_write(0x44b9e4 + physics_id*4, pack(slot))
                            u.mem_write(0x44bb64 + slot*4, pack(physics_id))
                            # Nonzero body-height offset must be included once.
                            for i, value in enumerate(centre):
                                u.mem_write(0x44e0dd+slot*48+i*16,
                                            pack(value - (12345 if i == 2 else 0)))
                            u.mem_write(0x44f2ec+slot*160+0x9c, pack(12345))
                            u.mem_write(0x44f2ec+slot*160+0x7c, pack(5*65536))
                            code = ';'.join(f'mov dword ptr [eax+{i*4}],{v}'
                                            for i,v in enumerate(endpoint))
                            u.mem_write(0x2f074c, asm(0x2f074c,
                                        code+f';mov eax,{physics_id};ret 28;'))
                            call(u, f.QUERY, (0x1000, 200000000, 1, 1,
                                             POINT+32, POINT+36, POINT+40),
                                 ((UC_X86_REG_EAX, POINT),
                                  (UC_X86_REG_EDX, DIRECTION)))
                            wanted = endpoint if enabled else origin[:]
                            if not enabled:
                                wanted[axis] += sign * expected * 65536
                            self.assertEqual(struct.unpack('<3i',u.mem_read(POINT,12)),
                                             tuple(wanted))
                            # Same body ID, but a supplemental mesh/leg hit at
                            # depth four: keep that true nearer contact.
                            contact = origin[:]
                            contact[axis] += sign*4*65536
                            code = ';'.join(f'mov dword ptr [eax+{i*4}],{v}'
                                            for i,v in enumerate(contact))
                            u.mem_write(0x2f074c, asm(0x2f074c,
                                        code+f';mov eax,{physics_id};ret 28;'))
                            u.mem_write(POINT, struct.pack('<3i',*origin))
                            u.ctl_remove_cache(0x2f074c, 0x2f0800)
                            call(u, f.QUERY, (0x1000, 200000000, 1, 1,
                                             POINT+32, POINT+36, POINT+40),
                                 ((UC_X86_REG_EAX, POINT),
                                  (UC_X86_REG_EDX, DIRECTION)))
                            self.assertEqual(struct.unpack('<3i',u.mem_read(POINT,12)),
                                             tuple(contact))

    def test_camera_ray_and_compatibility(self):
        # Coordinates above float32's exact-integer range exercise the reason
        # this correction uses doubles. Orthogonal directions make the expected
        # projection independent of the implementation's arithmetic.
        for axis in range(3):
            for sign in (-1, 1):
                for hit in (-1, 0, 2):
                    for enabled in (0, 1):
                        u = machine(enabled)
                        origin = [140000003, -100000007, 50000001]
                        direction = [0, 0, 0]
                        direction[axis] = sign * 65536
                        endpoint = [x + 12345 for x in origin]
                        endpoint[axis] = origin[axis] + sign * 300000
                        u.mem_write(POINT, struct.pack('<3i', *origin))
                        u.mem_write(DIRECTION, struct.pack('<3i', *direction))
                        code = ';'.join(
                            f'mov dword ptr [eax+{i*4}],{x}' for i, x in enumerate(endpoint)
                        )
                        u.mem_write(0x2f074c, asm(0x2f074c, code + f';mov eax,{hit};ret 28;'))
                        vectors = [
                            (UC_X86_REG_XMM0 + i, (i + 1) * 0x112233445566778899aabbcc)
                            for i in range(8)
                        ]
                        call(
                            u, f.QUERY, (0x1000, 2000000, 1, 1, POINT + 32, POINT + 36, POINT + 40),
                            (
                                (UC_X86_REG_EAX, POINT), (UC_X86_REG_EDX, DIRECTION),
                                (UC_X86_REG_EBX, 0x640000), (UC_X86_REG_ECX, 0), *vectors
                            )
                        )
                        wanted = endpoint[:]
                        if not enabled and hit > 0:
                            wanted = origin[:]
                            wanted[axis] = endpoint[axis]
                        self.assertEqual(struct.unpack('<3i', u.mem_read(POINT, 12)), tuple(wanted))
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX), hit & 0xffffffff)
                        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 32)
                        self.assertEqual(u.reg_read(UC_X86_REG_MXCSR), 0x1f80)
                        for reg, value in vectors:
                            self.assertEqual(u.reg_read(reg), value)

    def test_range_and_behind_camera_clamp(self):
        for x, wanted in ((-500, 0), (3000000, 1000000)):
            u = machine(0)
            u.mem_write(POINT, bytes(12))
            u.mem_write(DIRECTION, struct.pack('<3i', 65536, 0, 0))
            u.mem_write(
                0x2f074c,
                asm(
                    0x2f074c, (
                        f"mov dword ptr [eax],{x};"
                        f"mov dword ptr [eax+4],100;"
                        f"mov eax,2;"
                        f"ret 28;"
                    )
                )
            )
            call(
                u, f.QUERY, (0x1000, 1000000, 1, 1, POINT + 32, POINT + 36, POINT + 40),
                ((UC_X86_REG_EAX, POINT), (UC_X86_REG_EDX, DIRECTION))
            )
            self.assertEqual(struct.unpack('<3i', u.mem_read(POINT, 12)), (wanted, 0, 0))

    def test_install_rejects_before_mutation(self):
        base = bytearray(0x2000000)
        for a, b in f.predecessors().items():
            base[a:a + len(b)] = b
        for address in (f.BASE, f.STATE, f.END - 1, f.query_site(), f.AI_DRAW):
            ram = base[:]
            ram[address] ^= 255
            with self.assertRaises(AssertionError):
                f.setup(lambda *args: self.fail('partial write'), ram)
        f.setup(lambda a, b: base.__setitem__(slice(a, a + len(b)), b), base)
        self.assertTrue(f.verify(base))

    def test_existing_shared_option_contracts(self):
        # Changing any older layout intentionally requires updating this bridge.
        self.assertEqual(f.WRIST_STATE, 0x1fcae00)
        self.assertEqual(f.FPS_STATE, 0x1f77900)
        self.assertEqual(f.AI_STATE, 0x1e39c00)
        pieces = f.bodies()
        for a, b in pieces:
            for c, d in pieces:
                if a < c:
                    self.assertLessEqual(a + len(b), c, 'overlapping feature spans')


if __name__ == '__main__':
    unittest.main()
