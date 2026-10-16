"""Keep detached visual tails from blocking gameplay object allocation.

A combat dump had all 299 object IDs occupied, including 48 retained tails,
when a clone spawn entered the original fatal allocation path. These synthetic
cases exercise tail selection and preservation of caller state. Deletion is
modeled here; the captured-state check separately uses the real deletion and
object/suit allocators. No original game data is embedded in these fixtures.
"""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
from features import effect_timing as e


class BeamPressure(unittest.TestCase):

    def machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(e.BEAM_PRESSURE, dict(e.beam_visual_bodies())[e.BEAM_PRESSURE])
        u.mem_write(0x295730, b'\xc3')
        deleted = []

        def deletion(cpu, address, size, data):
            oid = cpu.reg_read(UC_X86_REG_EAX)
            deleted.append(oid)
            cpu.mem_write(0x3c3247, struct.pack('<H', oid))
            cpu.mem_write(e.BEAM_TABLE + oid * 8 + 4, bytes(4))
            # An ordinary callee is allowed to alter scratch registers/flags.
            cpu.reg_write(UC_X86_REG_EAX, 1)
            cpu.reg_write(UC_X86_REG_ECX, 99)

        u.hook_add(UC_HOOK_CODE, deletion, begin=0x295730, end=0x295730)
        return u, deleted

    def tail(self, u, oid, *, active=1, kind=0x1c06, generation=12, tag=13):
        u.mem_write(0x3c3240 + oid * 37, struct.pack('<BHH', active, kind, generation))
        u.mem_write(e.BEAM_TABLE + oid * 8 + 4, struct.pack('<I', tag))

    def run_pressure(self, u):
        stack, stop = 0x1800000, 0x1801000
        regs = (
            UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI,
            UC_X86_REG_EDI, UC_X86_REG_EBP
        )
        for n, reg in enumerate(regs):
            u.reg_write(reg, 100 + n)
        u.reg_write(UC_X86_REG_EFLAGS, 0x246)
        u.reg_write(UC_X86_REG_ESP, stack)
        u.mem_write(stack, struct.pack('<I', stop))
        u.emu_start(e.BEAM_PRESSURE, stop, count=100000)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), stop)
        self.assertEqual([u.reg_read(reg) for reg in regs], list(range(100, 107)))
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x246)

    def test_available_slot_preserves_visual_tails(self):
        u, deleted = self.machine()
        self.tail(u, 12)
        u.mem_write(0x3c3247, struct.pack('<H', 90))
        self.run_pressure(u)
        self.assertEqual(deleted, [])

    def test_full_pool_reclaims_exactly_one_matching_tail(self):
        u, deleted = self.machine()
        self.tail(u, 12)
        self.tail(u, 14)
        self.run_pressure(u)
        self.assertEqual(deleted, [12])
        self.assertEqual(bytes(u.mem_read(e.BEAM_TABLE + 14 * 8 + 4, 4)), struct.pack('<I', 13))

    def test_reused_inactive_and_untagged_slots_are_preserved(self):
        u, deleted = self.machine()
        self.tail(u, 1, kind=0x0701)  # A PBA occupying a reused object ID.
        self.tail(u, 2, active=0)
        self.tail(u, 3, generation=14)
        self.tail(u, 4, tag=0)  # A currently linked live segment.
        self.tail(u, 299)
        self.run_pressure(u)
        self.assertEqual(deleted, [299])

    def test_no_eligible_tail_preserves_normal_allocation_failure(self):
        u, deleted = self.machine()
        self.tail(u, 2, tag=0)
        self.run_pressure(u)
        self.assertEqual(deleted, [])
        self.assertEqual(bytes(u.mem_read(0x3c3247, 2)), bytes(2))
