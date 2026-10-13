"""Route recovery execution with the original planner as a checked boundary."""
from pathlib import Path
import sys, struct, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import ai_response as f
from tests.test_ai_response import machine, NOW, REGS
from tests.test_render_views import put, get, STACK
from tests.test_input_views import run
from tests.test_ai_firing import execute_until
from patch_support import asm
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *


def recovery():
    u, obj, ai, target, other = machine()
    for a, b in f.recovery_bodies() + f.recovery_providers():
        u.mem_write(a, b)
    u.mem_write(ai + 0xca, b'\x14')
    row = f.RECOVERY_STATE + f.RECOVERY_STRIDE
    u.mem_write(row, struct.pack('<8I', 10, 20, NOW - 5000, NOW, 20 << 16, 20 << 16, 0, 0))
    requests = []
    result = [0]
    u.mem_write(0x24fc04, asm(0x24fc04, 'ret 12'))

    def planner(uc, a, n, d):
        requests.append(
            (
                uc.reg_read(UC_X86_REG_EAX),
                struct.unpack('<3I', uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4, 12))
            )
        )
        uc.reg_write(UC_X86_REG_EAX, result[0])

    u.hook_add(UC_HOOK_CODE, planner, begin=0x24fc04, end=0x24fc04)
    return u, obj, ai, target, other, row, requests, result


class AIRecoveryTests(unittest.TestCase):

    def test_direct_generation_checked_install_and_live_state_preservation(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(f.recovery_bodies()), 11)
        for problem in (
            'none', 'hook', 'partial', 'code', 'state', 'select', 'mission_reset', 'slot_reset',
            'short'
        ):
            ram = bytearray(0x2000000)
            writes = []
            for a, b in list(f.RECOVERY_SITES.items()) + f.recovery_providers():
                ram[a:a + len(b)] = b
            original = bytes(ram)
            where = {
                'hook': 0x24fe55,
                'code': f.RECOVERY_END - 1,
                'state': f.RECOVERY_STATE_END - 1,
                'select': f.ALLY_SELECT,
                'mission_reset': f.IDLE_MISSION_RESET,
                'slot_reset': f.AVOIDANCE_SLOT_RESET
            }
            if problem in where:
                ram[where[problem]] ^= 1
            if problem == 'partial':
                a, b = f.recovery_bodies()[0]
                ram[a:a + len(b)] = b

            def write(a, b):
                writes.append((a, b))
                ram[a:a + len(b)] = b

            read = lambda a, n: ram[a:a + n - int(problem == 'short')]
            if problem != 'none':
                with self.assertRaises(ValueError):
                    f.recovery_install(write, read)
                self.assertFalse(writes, problem)
            else:
                f.recovery_install(write, read)
                self.assertEqual(writes, f.recovery_bodies())
                writes.clear()
                ram[f.RECOVERY_STATE:f.RECOVERY_STATE + 4] = b'\x55' * 4
                self.assertTrue(f.recovery_verify(read))
                self.assertTrue(f.recovery_install(write, read)['already_installed'])
                self.assertFalse(writes)
                self.assertEqual(ram[f.RECOVERY_STATE:f.RECOVERY_STATE + 4], b'\x55' * 4)
                self.assertEqual(f.recovery_predecessor_view(ram), original)

    def test_eligibility_retains_orders_guard_ownership_and_enemy_pba_scope(self):
        for order in range(11):
            u, obj, ai, target, other, row, *_ = recovery()
            u.mem_write(0x3805bb, bytes([order]))
            run(u, f.RECOVERY_VALID, eax=ai)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(order in (1, 2, 3)), order)
        for condition in (
            'normal', 'guard', 'ally', 'player', 'inactive', 'noncombat', 'vehicle', 'no_route',
            'bad_owner', 'bad_slot', 'dead_target', 'target_vehicle', 'target_faction',
            'target_owner', 'target_inactive', 'unaligned', 'zero_slot', 'high_slot'
        ):
            u, obj, ai, target, other, row, *_ = recovery()
            address = ai
            mutations = {
                'guard': (0x38059a, b'\1'),
                'ally': (ai + 5, b'\1'),
                'player': (ai + 10, b'\1'),
                'inactive': (ai, b'\0'),
                'noncombat': (ai + 0xc3, b'\0'),
                'vehicle': (ai + 13, b'\2'),
                'bad_owner': (ai + 11, b'\x0b\0'),
                'bad_slot': (obj + 33, b'\2'),
                'dead_target': (target, b'\0'),
                'target_vehicle': (target + 1, b'\2'),
                'target_faction': (other + 5, b'\2'),
                'target_owner': (other + 11, b'\x15\0'),
                'target_inactive': (other, b'\0')
            }
            if condition in mutations:
                u.mem_write(*mutations[condition])
            if condition == 'no_route':
                put(u, ai + 0xad, 0)
            if condition == 'unaligned':
                address += 1
            if condition == 'zero_slot':
                address = 0x3832f0
            if condition == 'high_slot':
                address = 0x3832f0 + 334 * 60
            run(u, f.RECOVERY_VALID, eax=address)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(condition == 'normal'), condition)
            if condition == 'normal':
                self.assertEqual(
                    [
                        u.reg_read(r)
                        for r in (UC_X86_REG_EBP, UC_X86_REG_EDI, UC_X86_REG_ESI, UC_X86_REG_EBX)
                    ], [ai, row, obj, target]
                )

    def test_failure_observation_resets_on_identity_gap_clock_reversal_and_progress(self):
        for condition in (
            'continuous', 'gap_edge', 'gap', 'clock_back', 'moved_x', 'moved_y', 'moved_z', 'owner',
            'target', 'success', 'zero_anchor'
        ):
            u, obj, ai, target, other, row, *_ = recovery()
            before = bytes(u.mem_read(row, 32))
            result = 0xffffffff
            if condition == 'gap_edge':
                put(u, row + 12, NOW - 2500)
            if condition == 'gap':
                put(u, row + 12, NOW - 2501)
            if condition == 'clock_back':
                put(u, row + 12, NOW + 1)
            if condition == 'moved_x':
                put(u, obj + 15, (20 << 16) + 0x8001)
            if condition == 'moved_y':
                put(u, obj + 19, (20 << 16) + 0x8001)
            if condition == 'moved_z':
                put(u, obj + 23, 10 << 16)
            if condition == 'owner':
                put(u, row, 99)
            if condition == 'target':
                put(u, row + 4, 99)
            if condition == 'zero_anchor':
                put(u, row + 8, 0)
            if condition == 'success':
                result = 0
            run(u, f.RECOVERY_OBSERVE, eax=ai, edx=result)
            fresh = condition in (
                'gap', 'clock_back', 'moved_x', 'moved_y', 'owner', 'target', 'zero_anchor'
            )
            self.assertEqual(
                get(u, row + 8), 0 if condition == 'success' else NOW if fresh else NOW - 5000,
                condition
            )
            self.assertEqual(get(u, row + 12), 0 if condition == 'success' else NOW)
            if fresh:
                self.assertEqual(bytes(u.mem_read(row + 16, 8)), bytes(u.mem_read(obj + 15, 8)))
            self.assertEqual((get(u, row), get(u, row + 4)), (10, 20))

    def test_update_requires_sustained_recent_failure_retry_time_and_no_ground_progress(self):
        for condition in (
            'normal', 'short', 'stale', 'retry', 'priority', 'x_progress', 'y_progress',
            'z_progress', 'owner', 'target', 'cleared'
        ):
            u, obj, ai, target, other, row, requests, result = recovery()
            if condition == 'short':
                put(u, row + 8, NOW - 4999)
            if condition == 'stale':
                put(u, row + 12, NOW - 2501)
            if condition == 'retry':
                put(u, row + 24, NOW + 1)
            if condition == 'priority':
                u.mem_write(ai + 0xd5, b'\4\0')
            if condition == 'x_progress':
                put(u, obj + 15, (20 << 16) + 0x8001)
            if condition == 'y_progress':
                put(u, obj + 19, (20 << 16) + 0x8001)
            if condition == 'z_progress':
                put(u, obj + 23, 10 << 16)
            if condition == 'owner':
                put(u, row, 99)
            if condition == 'target':
                put(u, row + 4, 99)
            if condition == 'cleared':
                put(u, row + 8, 0)
            run(u, f.RECOVERY_UPDATE, eax=ai)
            self.assertEqual(bool(requests), condition in ('normal', 'z_progress'), condition)
        # Inclusive timing/progress/priority boundaries still admit a request.
        u, obj, ai, target, other, row, requests, result = recovery()
        put(u, row + 12, NOW - 2500)
        put(u, row + 24, NOW)
        u.mem_write(ai + 0xd5, b'\3\0')
        put(u, row + 16, (20 << 16) - 0x8000)
        run(u, f.RECOVERY_UPDATE, eax=ai)
        self.assertEqual(len(requests), 1)

    def test_failed_routes_cycle_sideways_then_away_without_moving_or_consuming_rng(self):
        u, obj, ai, target, other, row, requests, result = recovery()
        position = bytes(u.mem_read(obj + 15, 12))
        u.mem_write(0x2ddd70, b'\xcc')
        for step in range(3):
            now = NOW + step * 2500
            put(u, 0x446ae8, now)
            put(u, row + 12, now)
            run(u, f.RECOVERY_UPDATE, eax=ai)
            self.assertEqual(get(u, row + 24), now + 2500)
            self.assertEqual(get(u, row + 8), NOW - 5000)
            self.assertEqual(bytes(u.mem_read(obj + 15, 12)), position)
        self.assertEqual(
            requests, [
                (ai, (20 << 16, 22 << 16, 3)), (ai, (20 << 16, 18 << 16, 3)),
                (ai, (22 << 16, 20 << 16, 3))
            ]
        )
        self.assertEqual(get(u, row + 28), 0)

    def test_success_clears_failure_and_waits_eight_seconds_bounds_still_throttle(self):
        u, obj, ai, target, other, row, requests, result = recovery()
        result[0] = 1
        run(u, f.RECOVERY_UPDATE, eax=ai)
        self.assertEqual(get(u, row + 24), NOW + 8000)
        self.assertEqual(get(u, row + 8), 0)
        self.assertEqual(get(u, row + 12), 0)
        put(u, row + 8, NOW - 5000)
        put(u, row + 12, NOW)
        run(u, f.RECOVERY_UPDATE, eax=ai)
        self.assertEqual(len(requests), 1)
        for x, y in ((0x10000, 0x10000), (0x1fe0000, 0x1fe0000)):
            u, obj, ai, target, other, row, requests, result = recovery()
            put(u, obj + 15, x)
            put(u, obj + 19, y)
            put(u, row + 16, x)
            put(u, row + 20, y)
            # Force away candidate out of bounds on each side of the map.
            put(u, row + 28, 2)
            put(u, target + 15, x + 0x40000 if x == 0x10000 else x - 0x40000)
            put(u, target + 19, y)
            run(u, f.RECOVERY_UPDATE, eax=ai)
            self.assertFalse(requests)
            self.assertEqual(get(u, row + 24), NOW + 2500)

    def test_mission_and_slot_resets_chain_to_shared_owners_without_adjacent_writes(self):
        u, obj, ai, target, other, row, *_ = recovery()
        u.mem_write(f.RECOVERY_STATE, b'\x55' * f.RECOVERY_STATE_SIZE)
        u.mem_write(f.RECOVERY_STATE + f.RECOVERY_STATE_SIZE, b'\xaa')
        u.mem_write(0x1e2f100, b'\x55' * 1024)
        execute_until(u, f.RECOVERY_RESET, {0x1e29400}, eax=99, **REGS)
        self.assertFalse(any(u.mem_read(f.RECOVERY_STATE, f.RECOVERY_STATE_SIZE)))
        self.assertFalse(any(u.mem_read(0x1e2f100, 1024)))
        self.assertEqual(u.mem_read(f.RECOVERY_STATE + f.RECOVERY_STATE_SIZE, 1), b'\xaa')
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
        for index in (0, 1, 59, 60):
            u.mem_write(f.RECOVERY_STATE, b'\x55' * f.RECOVERY_STATE_SIZE)
            u.mem_write(0x1e2b000, b'\x55' * (60 * 16))
            execute_until(u, f.RECOVERY_SLOTRESET, {0x1e23500}, eax=99, esi=0x3832f0 + 334 * index)
            expected = bytearray(b'\x55' * f.RECOVERY_STATE_SIZE)
            avoid = bytearray(b'\x55' * (60 * 16))
            if index < 60:
                expected[index * 32:index * 32 + 32] = bytes(32)
                avoid[index * 16:index * 16 + 16] = bytes(16)
            self.assertEqual(bytes(u.mem_read(f.RECOVERY_STATE, len(expected))), expected)
            self.assertEqual(bytes(u.mem_read(0x1e2b000, len(avoid))), avoid)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 99)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)

    def test_finish_and_selection_wrappers_preserve_original_results_and_call_order(self):
        u, obj, ai, target, other, row, requests, result = recovery()
        put(u, STACK + 0x16, 0x11223344)
        execute_until(u, f.RECOVERY_FINISH, {0x24fe5d}, eax=0xffffffff, esi=ai)
        self.assertEqual(get(u, STACK + 0x18), 0xffffffff)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0xffff3344)
        self.assertEqual(u.reg_read(UC_X86_REG_ESI), ai)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
        calls = []
        u.mem_write(0x24c618, asm(0x24c618, 'mov eax,77;mov edx,88;ret'))

        def boundary(uc, a, n, d):
            calls.append(a)

        for address in (0x24c618, f.PREFER, f.FALLBACK, f.ALLY_PREFER, f.RECOVERY_UPDATE):
            u.hook_add(UC_HOOK_CODE, boundary, begin=address, end=address)
        run(u, f.RECOVERY_SELECT, eax=ai, **REGS)
        self.assertEqual(calls, [0x24c618, f.PREFER, f.FALLBACK, f.ALLY_PREFER, f.RECOVERY_UPDATE])
        self.assertEqual(len(requests), 1)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 77)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 88)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
        for name, value in REGS.items():
            self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)


if __name__ == '__main__':
    unittest.main()
