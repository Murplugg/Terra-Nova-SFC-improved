"""Exercise QSound allocation using locally supplied original game routines.

These cases follow an observed combat crash: a failed companion allocation
overwrote sound handles with function pointers. The real availability counter,
channel selector and allocator run here; only the audio-device/sample API is
modeled. No original routine is distributed with the tests.
"""
import struct
import unittest

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
from original_inputs import original_ram
from features import audio_safety as f

STACK = 0x1800000
STOP = 0x1801000
SAMPLES = 0x1900000


class AudioSafetyTests(unittest.TestCase):
    def machine(self, free, fixed=True, stopped=True):
        if not any(original_ram[0x2eff7c:0x2f00e8]):
            self.skipTest('Requires the original retail executable')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(0, bytes(original_ram))
        if fixed:
            f.install(u.mem_write, u.mem_read)
        put = lambda a, v: u.mem_write(a, struct.pack('<I', v))
        put(0x35f950, 16)
        for i in range(16):
            sample = SAMPLES + i * 0x1000
            put(0x44b600 + 4*i, sample)
            put(sample + 4, 2 if stopped or i in free else 4)
            u.mem_write(0x44b3a0 + 38*i + 2, bytes((127, 0 if i in free else 0x82)))
            put(0x44b648 + 20*i, 0x35f938)
        calls = []

        def model(uc, address, size, unused):
            # These leaf calls preserve the register ABI expected by the game.
            leaves = (0x30a02c, 0x30a034, 0x30bdec, 0x30b720,
                      0x30b948, 0x30b8b4, 0x30cbe8, 0x2ebda0)
            if address not in leaves:
                return
            calls.append(address)
            sp = uc.reg_read(UC_X86_REG_ESP)
            word = lambda a: struct.unpack('<I', uc.mem_read(a, 4))[0]
            if address == 0x30bdec:
                uc.reg_write(UC_X86_REG_EAX, word(word(sp+4)+4))
            elif address == 0x30b720:
                put(word(sp+4)+4, 2)
            elif address == 0x30cbe8:
                put(word(sp+4)+0x850, word(sp+8))
            uc.reg_write(UC_X86_REG_ESP, sp+4)
            uc.reg_write(UC_X86_REG_EIP, word(sp))

        u.hook_add(UC_HOOK_CODE, model)
        return u, calls

    def run_pair(self, u, flags=0x180):
        u.mem_write(STACK, struct.pack('<3I', STOP, 0x1234, flags))
        for reg, value in (
            (UC_X86_REG_ESP, STACK), (UC_X86_REG_EAX, 0x1700000),
            (UC_X86_REG_EDX, 0x1701000), (UC_X86_REG_EBX, 128),
            (UC_X86_REG_ECX, 63), (UC_X86_REG_ESI, 0xabcdef),
            (UC_X86_REG_EDI, 0x123456), (UC_X86_REG_EBP, 0x654321),
        ):
            u.reg_write(reg, value)
        u.emu_start(0x2eff7c, STOP, count=100000)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), STOP)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK+12)
        for reg, value in ((UC_X86_REG_ESI, 0xabcdef),
                           (UC_X86_REG_EDI, 0x123456), (UC_X86_REG_EBP, 0x654321)):
            self.assertEqual(u.reg_read(reg), value)
        return u.reg_read(UC_X86_REG_EAX) & 0xff

    def test_original_companion_failure_matches_observed_handle_corruption(self):
        u, _ = self.machine({11}, fixed=False, stopped=False)
        # One genuinely free channel and one reserved, not-yet-playing channel
        # suffice. All other channels are busy; the count promises exactly two.
        u.mem_write(SAMPLES + 13*0x1000 + 4, struct.pack('<I', 2))
        self.run_pair(u)
        self.assertEqual(struct.unpack('<3I', u.mem_read(0x44b62c, 12)),
                         (0x2f00e8, 0x2f02a8, 0x35fb5c))
        self.assertEqual(u.mem_read(0x35fa8c + 13*11, 1), b'\xff')
        guarded, _ = self.machine({11}, stopped=False)
        guarded.mem_write(SAMPLES + 13*0x1000 + 4, struct.pack('<I', 2))
        handles = bytes(guarded.mem_read(0x44b600, 64))
        self.assertEqual(self.run_pair(guarded), 255)
        self.assertEqual(bytes(guarded.mem_read(0x44b600, 64)), handles)
        self.assertEqual(guarded.mem_read(0x44b3a3 + 38*11, 1), b'\0')

    def test_failed_pair_preserves_handles_and_releases_first_reservation(self):
        for slot in range(16):
            with self.subTest(slot=slot):
                u, _ = self.machine({slot})
                handles = bytes(u.mem_read(0x44b600, 64))
                pairs = bytes(u.mem_read(0x35fa8c, 16*13))
                for _ in range(3):
                    self.assertEqual(self.run_pair(u), 255)
                    self.assertEqual(bytes(u.mem_read(0x44b600, 64)), handles)
                    self.assertEqual(bytes(u.mem_read(0x35fa8c, 16*13)), pairs)
                    self.assertEqual(u.mem_read(0x44b3a3+38*slot, 1), b'\0')
                    self.assertEqual(struct.unpack('<I', u.mem_read(0x35fa54, 4))[0], 0x200)

    def test_first_allocation_failure_does_not_attempt_companion(self):
        u, calls = self.machine(set())
        before = bytes(u.mem_read(0x44b600, 64))
        self.assertEqual(self.run_pair(u), 255)
        self.assertNotIn(0x30b720, calls)
        self.assertEqual(bytes(u.mem_read(0x44b600, 64)), before)

    def test_successful_pair_and_permitted_mono_match_original(self):
        for free, flags, stopped, expected in (
            ({0, 15}, 0x180, True, 0), ({7, 8}, 0x80, True, 7),
            ({11}, 0x80, False, 11), ({11}, 0x180, False, 255),
            (set(), 0x180, False, 255),
        ):
            with self.subTest(free=free, flags=flags):
                old, old_calls = self.machine(free, fixed=False, stopped=stopped)
                new, new_calls = self.machine(free, stopped=stopped)
                self.assertEqual(self.run_pair(old, flags), expected)
                self.assertEqual(self.run_pair(new, flags), expected)
                self.assertEqual(old_calls, new_calls)
                for address, size in ((0x35fa54, 4), (0x35fa8c, 16*13),
                                      (0x44b3a0, 16*38), (0x44b600, 64+16*20),
                                      (SAMPLES, 16*0x1000)):
                    self.assertEqual(old.mem_read(address, size), new.mem_read(address, size))

    def test_installation_rejects_conflicts_before_writing(self):
        for conflict in (*f.SITES, f.CODE, f.END-1):
            ram = bytearray(0x2000000)
            for a, b in f.SITES.items():
                ram[a:a+len(b)] = b
            ram[conflict] ^= 1
            writes = []
            with self.assertRaises(ValueError):
                f.install(lambda a, b: writes.append((a, b)), lambda a, n: ram[a:a+n])
            self.assertFalse(writes)


class QueuedWeaponSoundTests(unittest.TestCase):
    """Original two-entry queue and drain with modeled host audio dispatch.

    A captured close Tripulsar impact deletes its bolt before the queue drains.
    Authored entries isolate projectile versus shooter lifetime and ID reuse.
    These tests verify dispatch, not audible mixing or game-loop timing.
    """

    def machine(self, fixed, host_success=False):
        if not any(original_ram[0x2904f8:0x290857]):
            self.skipTest('Requires the original retail executable')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(0, bytes(original_ram))
        if fixed:
            f.install(u.mem_write, u.mem_read)
        entries = struct.pack('<4HI', 19, 267, 0x828, 0x81c, 100)
        entries += struct.pack('<4HI', 20, 268, 0x829, 0x81d, 200)
        u.mem_write(0x397a50, entries)
        for oid, slot in ((19, 1), (20, 2)):
            u.mem_write(0x3c3240 + oid*37 + 3, struct.pack('<H', slot))
            u.mem_write(0x3a5608 + slot*0x582 + 0x82, b'\xff'*4)
        # Model failed dispatch or one stable successful handle. Callback
        # registration is a boundary; this does not exercise the audio device.
        # The flight boundary records which projectile would receive its sound.
        handle = 42 if host_success else 0xffffffff
        u.mem_write(0x247b60, b'\xb8' + struct.pack('<I', handle) + b'\xc2\x0c\x00')
        u.mem_write(0x247e30, b'\xc3')
        u.mem_write(0x249388, b'\xc3')
        events = []

        def dispatch(cpu, address, size, unused):
            events.append((address, cpu.reg_read(UC_X86_REG_EAX),
                           cpu.reg_read(UC_X86_REG_EDX)))

        for address in (0x247b60, 0x249388, 0x247e30):
            u.hook_add(UC_HOOK_CODE, dispatch, begin=address, end=address)
        return u, entries, events

    def call(self, u, address, object_id=0):
        u.mem_write(STACK, struct.pack('<I', STOP))
        u.reg_write(UC_X86_REG_ESP, STACK)
        u.reg_write(UC_X86_REG_EAX, object_id)
        u.reg_write(UC_X86_REG_EBX, 0x12345678)
        u.reg_write(UC_X86_REG_ESI, 0x87654321)
        u.emu_start(address, STOP, count=10000)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), STOP)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK+4)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x12345678)
        self.assertEqual(u.reg_read(UC_X86_REG_ESI), 0x87654321)

    def test_projectile_deletion_keeps_muzzle_sound_without_stale_flight_audio(self):
        for fixed in (False, True):
            with self.subTest(fixed=fixed):
                u, entries, events = self.machine(fixed)
                self.call(u, f.QUEUE_DELETE, 267)
                expected = bytearray(entries)
                expected[2:4] = b'\0\0' if fixed else entries[2:4]
                expected[4:6] = entries[4:6] if fixed else b'\0\0'
                self.assertEqual(bytes(u.mem_read(0x397a50, 24)), expected)
                # A later deletion callback for the same numeric ID must not
                # cancel the muzzle sample after its association was cleared.
                self.call(u, f.QUEUE_DELETE, 267)
                self.assertEqual(bytes(u.mem_read(0x397a50, 24)), expected)
                self.call(u, 0x29079c)
                muzzle = [a for site, a, d in events if site == 0x247b60]
                flights = [a for site, a, d in events if site == 0x249388]
                self.assertEqual(muzzle, [0x828, 0x829] if fixed else [0x829])
                self.assertEqual(flights, [268])
                self.assertEqual(bytes(u.mem_read(0x397a54, 2)), b'\0\0')
                self.call(u, f.QUEUE_DELETE, 267)
                events.clear()
                self.call(u, 0x29079c)
                self.assertEqual(events, [])

    def test_successful_dispatch_registers_surviving_shooter_handle(self):
        u, entries, events = self.machine(True, host_success=True)
        self.call(u, f.QUEUE_DELETE, 267)
        self.call(u, 0x29079c)
        registers = [(a, d) for site, a, d in events if site == 0x247e30]
        slots = [0x3a5608 + slot*0x582 + 0x82 for slot in (1, 2)]
        self.assertEqual(registers, [(42, address) for address in slots])
        for address in slots:
            self.assertEqual(struct.unpack('<I', u.mem_read(address, 4))[0], 42)
        self.assertEqual([a for site, a, d in events if site == 0x249388], [268])

    def test_shooter_and_unrelated_deletion_keep_original_behavior(self):
        for oid in (19, 20, 123):
            states = []
            for fixed in (False, True):
                u, entries, events = self.machine(fixed)
                self.call(u, f.QUEUE_DELETE, oid)
                states.append(bytes(u.mem_read(0x397a50, 24)))
            self.assertEqual(*states, oid)

    def test_sound_before_projectile_deletion_keeps_dispatch(self):
        events_by_mode = []
        for fixed in (False, True):
            u, entries, events = self.machine(fixed)
            self.call(u, 0x29079c)
            self.call(u, f.QUEUE_DELETE, 267)
            events_by_mode.append(events)
        self.assertEqual(*events_by_mode)


if __name__ == '__main__':
    unittest.main()
