"""Check startup movie policy using the real generated x86 guard.

The original movie player is a sentinel: these tests verify dispatch, registers
and the stack, while private playback checks cover decoding and menu input.
"""
import struct
import unittest
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP
from features import campaign_switch as c


class OpeningMovies(unittest.TestCase):

    def test_fresh_and_returning_sessions(self):
        for count in (0, 1, 2, 100):
            with self.subTest(completed_switches=count):
                machine = Uc(UC_ARCH_X86, UC_MODE_32)
                machine.mem_map(0, 0x2000000)
                machine.mem_write(c.OPENING, c.opening_body())
                machine.mem_write(c.STATE + 4, struct.pack('<I', count))
                machine.mem_write(c.ORIGINAL_OPENING, b'\xc3')
                calls = []
                machine.hook_add(
                    UC_HOOK_CODE,
                    lambda *_: calls.append(True),
                    begin=c.ORIGINAL_OPENING,
                    end=c.ORIGINAL_OPENING
                )
                machine.mem_write(0x1cff000, struct.pack('<I', 0x10000))
                machine.reg_write(UC_X86_REG_ESP, 0x1cff000)
                machine.reg_write(UC_X86_REG_EAX, 0x1234)
                machine.reg_write(UC_X86_REG_EDX, 0x5678)
                machine.emu_start(c.OPENING, 0x10000, count=30)
                self.assertEqual(len(calls), int(count == 0))
                self.assertEqual(machine.reg_read(UC_X86_REG_ESP), 0x1cff004)
                self.assertEqual(machine.reg_read(UC_X86_REG_EDX), 0x5678)
                self.assertEqual(machine.reg_read(UC_X86_REG_EAX), 0x1234 if count == 0 else 0)

    def test_installation_rejects_wrong_callback_or_occupied_reservation(self):
        for damaged in (None, c.RETAIL_FUNCTIONS + 47 * 4, c.END - 1):
            with self.subTest(damaged=damaged):
                ram = bytearray(0x2000000)
                slot = c.RETAIL_FUNCTIONS + 47 * 4
                ram[slot:slot + 4] = struct.pack('<I', c.ORIGINAL_OPENING)
                if damaged is not None:
                    ram[damaged] ^= 1
                writes = []
                install = lambda: c.install_opening_policy(
                    lambda a, b: writes.append((a, b)), lambda a, n: ram[a:a + n]
                )
                if damaged is not None:
                    with self.assertRaises(ValueError):
                        install()
                    self.assertEqual(writes, [])
                else:
                    install()
                    self.assertEqual([a for a, _ in writes], [c.OPENING, slot])


if __name__ == '__main__':
    unittest.main()
