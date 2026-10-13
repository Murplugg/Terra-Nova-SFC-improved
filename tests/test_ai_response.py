"""Execute response helpers against small actor fixtures and engine boundaries."""
from pathlib import Path
import sys, struct, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import ai_response as f
from patch_support import asm
from tests.test_render_views import Fixture, put, get, STACK, STOP
from tests.test_input_views import run
from tests.test_ai_firing import actor, execute_until
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

NOW = 100000
OUT = 0x160000
EVENT = 0x160100
REGS = dict(ebx=0x2345, ecx=0x3456, esi=0x4567, edi=0x5678, ebp=0x6789)


def machine():
    u = Fixture().u
    for a, b in f.alert_bodies() + f.bodies():
        u.mem_write(a, b)
    obj, ai = actor(u, 10, slot=1, team=2, xyz=(20 << 16, 20 << 16, 0))
    target, other = actor(u, 20, slot=2, team=1, xyz=(16 << 16, 20 << 16, 0))
    u.mem_write(ai + 13, b'\1')
    u.mem_write(ai + 0xc3, b'\1')
    put(u, ai + 0xad, 0x123400)
    u.mem_write(0x3805bb, b'\1')
    put(u, 0x446ae8, NOW)
    return u, obj, ai, target, other


def remember(u):
    run(u, f.REMEMBER, eax=10, edx=20, **REGS)


def ready():
    u, obj, ai, target, other = machine()
    remember(u)
    run(u, f.PREFER, eax=ai)
    row = f.STATE + f.STRIDE
    u.mem_write(row + 12, struct.pack('<5I', NOW - 2000, NOW - 2500, 0, 20 << 16, 20 << 16))
    requests = []
    u.mem_write(0x24fc04, asm(0x24fc04, 'mov eax,1;ret 12'))

    def route(uc, a, n, d):
        requests.append(
            (
                uc.reg_read(UC_X86_REG_EAX),
                struct.unpack('<3I', uc.mem_read(uc.reg_read(UC_X86_REG_ESP) + 4, 12))
            )
        )

    u.hook_add(UC_HOOK_CODE, route, begin=0x24fc04, end=0x24fc04)
    return u, obj, ai, target, other, row, requests


def allied():
    u, obj, ai, target, other = machine()
    for a, b in f.ally_bodies() + f.providers():
        u.mem_write(a, b)
    u.mem_write(ai + 5, b'\1')
    u.mem_write(other + 5, b'\2')
    put(u, 0x441350, 1)
    weapon = 0x3a5608 + 0x582 + 0x45
    u.mem_write(weapon, b'\5')
    u.mem_write(0x39511e + 5 * 36, struct.pack('<H', 12))
    run(u, f.ALLY_REMEMBER, eax=10, edx=20)
    previews = []
    outcomes = {20: (20, 0), 30: (0, 0)}
    u.mem_write(0x293834, b'\xc3')

    def preview(uc, a, n, d):
        oid = uc.reg_read(UC_X86_REG_EDX)
        previews.append(
            (uc.reg_read(UC_X86_REG_EAX), oid, uc.reg_read(UC_X86_REG_EBX), get(uc, f.ACTIVE))
        )
        hit, failed = outcomes.get(oid, (0, 0))
        put(uc, 0x446598, hit)
        put(uc, f.FAILED, failed)
        uc.reg_write(UC_X86_REG_EAX, 6)

    u.hook_add(UC_HOOK_CODE, preview, begin=0x293834, end=0x293834)
    return u, obj, ai, target, other, f.ALLY_STATE + f.ALLY_STRIDE, previews, outcomes


class AIResponseTests(unittest.TestCase):

    def test_history_free_exact_installation_rejects_partial_inputs_before_writing(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(f.alert_bodies()), 5)
            self.assertEqual(len(f.bodies()), 19)
        for alert in (True, False):
            pieces = f.alert_bodies() if alert else f.bodies()
            install = f.alert_install if alert else f.install
            verify = f.alert_verify if alert else f.verify
            sites = {
                f.ALERT_SITE: f.ALERT_ORIGINAL,
                f.ALERT_RESET: f.ALERT_RESET_ORIGINAL
            } if alert else f.SITES
            for problem in (
                'none', 'hook', 'partial', 'reservation', 'short',
                *(() if alert else ('provider', ))
            ):
                with self.subTest(alert=alert, problem=problem):
                    ram = bytearray(0x2000000)
                    writes = []
                    for a, b in list(sites.items()) + ([] if alert else f.providers()):
                        ram[a:a + len(b)] = b
                    original = bytes(ram)
                    if problem == 'hook':
                        ram[next(iter(sites))] ^= 1
                    if problem == 'partial':
                        a, b = pieces[0]
                        ram[a:a + len(b)] = b
                    if problem == 'reservation':
                        ram[(f.ALERT_END if alert else f.END) - 1] = 1
                    if problem == 'provider':
                        ram[f.ALERT_EMIT] ^= 1

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    read = lambda a, n: ram[a:a + n - int(problem == 'short')]
                    if problem != 'none':
                        with self.assertRaises(ValueError):
                            install(write, read)
                        self.assertFalse(writes)
                    else:
                        install(write, read)
                        self.assertEqual(
                            writes, pieces + (
                                [(f.ALERT_STATE,
                                  bytes(f.ALERT_END - f.ALERT_STATE))] if alert else []
                            )
                        )
                        # A verified live checkpoint may contain encounter state;
                        # repeated installation must never erase that state.
                        state = f.ALERT_STATE if alert else f.STATE
                        ram[state:state + 4] = b'\x55' * 4
                        self.assertTrue(verify(read))
                        writes.clear()
                        self.assertTrue(install(write, read)['already_installed'])
                        self.assertFalse(writes)
                        self.assertEqual(ram[state:state + 4], b'\x55' * 4)
                        if not alert:
                            self.assertEqual(f.predecessor_view(ram), original)

    def test_notification_throttle_event_ownership_allocation_failure_and_abi(self):
        u, obj, ai, target, other = machine()
        events = []
        frees = []
        alloc = [EVENT]
        u.mem_write(0x2ec630, b'\xc3')
        u.mem_write(0x25ae48, asm(0x25ae48, 'ret 4'))
        u.mem_write(0x2ec678, b'\xc3')

        def boundary(uc, a, n, d):
            if a == 0x2ec630:
                uc.reg_write(UC_X86_REG_EAX, alloc[0])
            elif a == 0x25ae48:
                events.append(
                    (
                        uc.reg_read(UC_X86_REG_EAX), get(uc,
                                                         uc.reg_read(UC_X86_REG_ESP) + 4),
                        uc.reg_read(UC_X86_REG_EDX), uc.reg_read(UC_X86_REG_EBX)
                    )
                )
            elif a == 0x2ec678:
                frees.append(uc.reg_read(UC_X86_REG_EAX))

        u.hook_add(UC_HOOK_CODE, boundary)
        for dt in (0, 16, 499, 500):
            put(u, 0x446ae8, NOW + dt)
            run(u, f.ALERT_EMIT, eax=10, edx=20, **REGS)
            for name, value in dict(REGS, eax=10, edx=20).items():
                self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
        self.assertEqual(events, [(EVENT, 1, (20 << 16) | 128, (1 << 16) | 128)] * 2)
        self.assertEqual(frees, [EVENT] * 2)
        put(u, 0x446ae8, NOW + 1000)
        alloc[0] = 0
        run(u, f.ALERT_EMIT, eax=10, edx=20)
        self.assertEqual(get(u, f.ALERT_STATE + 8), NOW + 500)
        alloc[0] = EVENT
        run(u, f.ALERT_EMIT, eax=10, edx=20)
        self.assertEqual(len(events), 3)

    def test_notification_and_memory_exclude_invalid_or_ineligible_identities(self):
        for condition in (
            'zero', 'high', 'dead_victim', 'vehicle', 'slot_zero', 'bad_owner', 'ally_victim',
            'player_victim', 'enemy_source', 'bad_source_owner'
        ):
            u, obj, ai, target, other = machine()
            victim = 10
            if condition == 'zero':
                victim = 0
            elif condition == 'high':
                victim = 300
            else:
                a, b = {
                    'dead_victim': (obj, b'\0'),
                    'vehicle': (obj + 1, b'\2'),
                    'slot_zero': (obj + 33, b'\0'),
                    'bad_owner': (ai + 11, b'\x0b\0'),
                    'ally_victim': (ai + 5, b'\1'),
                    'player_victim': (ai + 10, b'\1'),
                    'enemy_source': (other + 5, b'\2'),
                    'bad_source_owner': (other + 11, b'\x15\0')
                }[condition]
                u.mem_write(a, b)
            # Reaching the allocator is forbidden for all these cases.
            u.mem_write(0x2ec630, b'\xcc')
            for entry in (f.ALERT_EMIT, f.REMEMBER):
                run(u, entry, eax=victim, edx=20)
            self.assertFalse(any(u.mem_read(f.STATE, f.STATE_SIZE)), condition)
            self.assertFalse(any(u.mem_read(f.ALERT_STATE, f.ALERT_END - f.ALERT_STATE)), condition)

    def test_recent_attacker_memory_preserves_stall_only_for_same_live_encounter(self):
        u, obj, ai, target, other = machine()
        row = f.STATE + f.STRIDE
        remember(u)
        self.assertEqual(struct.unpack('<3I', u.mem_read(row, 12)), (NOW, 10, 20))
        for elapsed, clear in ((15000, False), (15001, True)):
            put(u, row, NOW)
            u.mem_write(row + 12, b'\x55' * 20)
            put(u, 0x446ae8, NOW + elapsed)
            remember(u)
            self.assertEqual(bytes(u.mem_read(row + 12, 20)), bytes(20) if clear else b'\x55' * 20)
        for field in (4, 8):
            put(u, row + field, 99)
            u.mem_write(row + 12, b'\x55' * 20)
            remember(u)
            self.assertFalse(any(u.mem_read(row + 12, 20)))
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_preference_refreshes_target_and_respects_age_orders_and_identity(self):
        for condition in (
            'normal', 'hold', 'expired', 'guard', 'script5', 'script9', 'no_combat', 'not_pba',
            'dead_source', 'same_target', 'unaligned'
        ):
            u, obj, ai, target, other = machine()
            remember(u)
            address = ai
            u.mem_write(other + 6, b'\4')
            put(u, ai + 0x106, 99)
            u.mem_write(ai + 0xc4, b'\5')
            if condition == 'hold':
                u.mem_write(0x3805bb, b'\7')
            if condition == 'expired':
                put(u, 0x446ae8, NOW + 5001)
            if condition == 'guard':
                u.mem_write(0x38059a, b'\1')
            if condition.startswith('script'):
                u.mem_write(0x3805bb, bytes([int(condition[6:])]))
            if condition == 'no_combat':
                u.mem_write(ai + 0xc3, b'\0')
            if condition == 'not_pba':
                u.mem_write(ai + 13, b'\2')
            if condition == 'dead_source':
                u.mem_write(other, b'\0')
            if condition == 'same_target':
                u.mem_write(ai + 0xc9, b'\2\x14')
            if condition == 'unaligned':
                address += 1
            before = bytes(u.mem_read(ai, 334))
            run(u, f.PREFER, eax=address, **REGS)
            self.assertEqual(
                u.reg_read(UC_X86_REG_EAX), int(condition in ('normal', 'hold')), condition
            )
            if condition in ('normal', 'hold'):
                self.assertEqual(bytes(u.mem_read(ai + 0xc9, 7)), b'\2\x14\4\x10\0\x14\0')
                self.assertEqual(get(u, ai + 0xd7), NOW)
                self.assertEqual(get(u, ai + 0xc5), NOW)
                self.assertEqual(get(u, ai + 0x106), 0)
            else:
                self.assertEqual(bytes(u.mem_read(ai, 334)), before, condition)
            for name, value in REGS.items():
                self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)

    def test_preview_error_six_is_not_failure_and_failure_flag_is_preview_scoped(self):
        u, *_ = machine()
        u.mem_write(0x293834, asm(0x293834, 'mov eax,6;ret'))
        seen = []

        def query(uc, a, n, d):
            seen.append((get(uc, f.ACTIVE), get(uc, f.FAILED)))

        u.hook_add(UC_HOOK_CODE, query, begin=0x293834, end=0x293834)
        put(u, f.FAILED, 99)
        run(u, f.QUERY)
        self.assertEqual(seen, [(1, 0)])
        self.assertEqual(get(u, f.ACTIVE), 0)
        self.assertEqual(get(u, f.FAILED), 0)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 6)
        for active in (0, 1):
            put(u, f.ACTIVE, active)
            put(u, f.FAILED, 0)
            put(u, STACK + 0x1e, 0xfffe0000)
            execute_until(u, f.FAIL, {0x2d9bba})
            self.assertEqual(get(u, f.FAILED), active)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0xfffffffe)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)

    def test_gravity_probe_preserves_original_solver_arguments_and_return(self):
        for active, gravity, valid in ((0, 0, 0), (1, 1, 0), (1, 0, 0), (1, 0, 1)):
            u, *_ = machine()
            calls = []
            put(u, f.ACTIVE, active)
            put(u, 0x4463d8, 600)
            descriptor = 0x170000
            u.mem_write(descriptor + 3, bytes([gravity]))
            put(u, STACK + 40, descriptor)
            for i, v in enumerate((111, 222, 333)):
                put(u, STACK + 4 + 4 * i, v)
            u.mem_write(0x2d8d04, asm(0x2d8d04, 'ret 12'))

            def solver(uc, a, n, d):
                sp = uc.reg_read(UC_X86_REG_ESP)
                calls.append(
                    (
                        tuple(
                            uc.reg_read(r) for r in
                            (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_ECX)
                        ), struct.unpack('<3I', uc.mem_read(sp + 4, 12))
                    )
                )
                uc.reg_write(
                    UC_X86_REG_EAX, valid if len(calls) == 1 and active and not gravity else 77
                )

            u.hook_add(UC_HOOK_CODE, solver, begin=0x2d8d04, end=0x2d8d04)
            run(u, f.SOLVER, eax=10, edx=20, **REGS)
            self.assertEqual(len(calls), 2 if active and not gravity else 1)
            self.assertEqual(calls[-1], ((10, 20, REGS['ebx'], REGS['ecx']), (111, 222, 333)))
            if len(calls) == 2:
                self.assertEqual(calls[0][1][0], 100)
            self.assertEqual(get(u, f.FAILED), int(active and not gravity and not valid))
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 77)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 16)

    def test_reach_tracks_first_failure_clears_success_and_excludes_non_pbas(self):
        u, obj, ai, *_ = machine()
        remember(u)
        run(u, f.PREFER, eax=ai)
        row = f.STATE + f.STRIDE
        for cls, failed, expected in ((1, 1, NOW), (1, 1, NOW), (2, 0, NOW), (1, 0, 0)):
            u.mem_write(ai + 13, bytes([cls]))
            put(u, f.FAILED, failed)
            u.mem_write(OUT, b'\0')
            put(u, STACK + 28, OUT)
            put(u, 0x44658c, 77)
            execute_until(u, f.REACH, {0x252d6d}, edi=ai)
            self.assertEqual(get(u, row + 12), expected)
            self.assertEqual(u.mem_read(OUT, 1)[0], int(cls == 1 and failed))
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 77)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
            put(u, 0x446ae8, NOW + 100)
        self.assertEqual(struct.unpack('<2I', u.mem_read(row + 24, 8)), (20 << 16, 20 << 16))

    def test_retreat_calls_original_planner_away_and_sideways_without_moving_actor(self):
        u, obj, ai, target, other, row, requests = ready()
        position = bytes(u.mem_read(obj + 15, 12))
        for phase in range(3):
            put(u, row + 12, NOW - 2000)
            put(u, row + 16, NOW - 2500)
            run(u, f.FALLBACK, eax=ai, **REGS)
            self.assertEqual(bytes(u.mem_read(obj + 15, 12)), position)
            self.assertEqual(get(u, row + 12), NOW)
            self.assertEqual(get(u, row + 16), NOW)
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
            for name, value in dict(REGS, eax=ai).items():
                self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)
        self.assertEqual(
            requests, [
                (ai, (22 << 16, 20 << 16, 3)), (ai, (20 << 16, 22 << 16, 3)),
                (ai, (20 << 16, 18 << 16, 3))
            ]
        )
        self.assertEqual(get(u, row + 20), 0)

    def test_retreat_gates_retain_orders_timing_identity_and_progress(self):
        for condition in (
            'hold', 'script', 'guard', 'ally', 'vehicle', 'player', 'inactive', 'no_combat',
            'no_route', 'wrong_target', 'stale', 'usable_shot', 'short_stall', 'retry', 'priority',
            'moving', 'dead_source', 'source_faction', 'edge'
        ):
            u, obj, ai, target, other, row, requests = ready()
            mutations = {
                'hold': (0x3805bb, b'\7'),
                'script': (0x3805bb, b'\4'),
                'guard': (0x38059a, b'\1'),
                'ally': (ai + 5, b'\1'),
                'vehicle': (ai + 13, b'\2'),
                'player': (ai + 10, b'\1'),
                'inactive': (ai, b'\0'),
                'no_combat': (ai + 0xc3, b'\0'),
                'wrong_target': (ai + 0xca, b'\x15'),
                'dead_source': (other, b'\0'),
                'source_faction': (other + 5, b'\2')
            }
            if condition in mutations:
                u.mem_write(*mutations[condition])
            if condition == 'no_route':
                put(u, ai + 0xad, 0)
            if condition == 'stale':
                put(u, row, NOW - 15001)
            if condition == 'usable_shot':
                put(u, row + 12, 0)
            if condition == 'short_stall':
                put(u, row + 12, NOW - 1999)
            if condition == 'retry':
                put(u, row + 16, NOW - 2499)
            if condition == 'priority':
                put(u, ai + 0xd1, NOW)
                u.mem_write(ai + 0xd5, b'\3\0')
            if condition == 'moving':
                put(u, row + 24, (20 << 16) - 0x8001)
            if condition == 'edge':
                put(u, obj + 15, 0x1fe0000)
                put(u, row + 24, 0x1fe0000)
            run(u, f.FALLBACK, eax=ai)
            self.assertFalse(requests, condition)
            if condition == 'moving':
                self.assertEqual(get(u, row + 12), NOW)
                self.assertEqual(get(u, row + 24), 20 << 16)

    def test_reset_clears_both_owned_tables_and_replays_original_instruction(self):
        u, *_ = machine()
        u.mem_write(f.ALERT_STATE, b'\x55' * (f.ALERT_END - f.ALERT_STATE))
        u.mem_write(f.STATE, b'\x55' * f.STATE_SIZE)
        execute_until(u, f.RESET, {0x295402}, eax=99, **REGS)
        self.assertFalse(any(u.mem_read(f.STATE, f.STATE_SIZE)))
        self.assertFalse(any(u.mem_read(f.ALERT_STATE, f.ALERT_END - f.ALERT_STATE)))
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 99)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x2b5c)
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)

    def test_selection_runs_original_first_then_preference_and_retreat_preserving_result(self):
        u, obj, ai, target, other, row, requests = ready()
        u.mem_write(ai + 0xca, b'\x15')
        original = []

        def select(uc, a, n, d):
            original.append((uc.reg_read(UC_X86_REG_EAX), uc.mem_read(ai + 0xca, 1)[0]))

        u.hook_add(UC_HOOK_CODE, select, begin=0x24c618, end=0x24c618)
        u.mem_write(0x24c618, asm(0x24c618, 'mov eax,77;mov edx,88;ret'))
        run(u, f.SELECT, eax=ai, **REGS)
        self.assertEqual(original, [(ai, 21)])
        self.assertEqual(u.mem_read(ai + 0xca, 1), b'\x14')
        self.assertEqual(requests, [(ai, (22 << 16, 20 << 16, 3))])
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 77)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 88)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
        for name, value in REGS.items():
            self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)

    def test_allied_installation_is_history_free_atomic_and_preserves_live_state(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(f.ally_bodies()), 9)
        for problem in ('none', 'hook', 'partial', 'reservation', 'query', 'range', 'short'):
            ram = bytearray(0x2000000)
            writes = []
            for a, b in list(f.ALLY_SITES.items()) + f.ally_providers():
                ram[a:a + len(b)] = b
            original = bytes(ram)
            if problem == 'hook':
                ram[0x24dfe0] ^= 1
            if problem == 'partial':
                a, b = f.ally_bodies()[0]
                ram[a:a + len(b)] = b
            if problem == 'reservation':
                ram[f.ALLY_END - 1] = 1
            if problem == 'query':
                ram[f.QUERY] ^= 1
            if problem == 'range':
                ram[f.fire.RANGE] ^= 1

            def write(a, b):
                writes.append((a, b))
                ram[a:a + len(b)] = b

            read = lambda a, n: ram[a:a + n - int(problem == 'short')]
            if problem != 'none':
                with self.assertRaises(ValueError):
                    f.ally_install(write, read)
                self.assertFalse(writes, problem)
            else:
                f.ally_install(write, read)
                self.assertEqual(writes, f.ally_bodies())
                writes.clear()
                ram[f.ALLY_STATE:f.ALLY_STATE + 4] = b'\x55' * 4
                self.assertTrue(f.ally_verify(read))
                self.assertTrue(f.ally_install(write, read)['already_installed'])
                self.assertFalse(writes)
                self.assertEqual(ram[f.ALLY_STATE:f.ALLY_STATE + 4], b'\x55' * 4)
                self.assertEqual(f.ally_predecessor_view(ram), original)

    def test_allied_memory_accepts_hostile_mobile_and_turret_classes_and_retains_throttle(self):
        for cls in (0, 1, 2, 3, 4, 5):
            u, obj, ai, target, other, row, previews, outcomes = allied()
            u.mem_write(row, bytes(16))
            u.mem_write(target + 1, bytes([cls]))
            run(u, f.ALLY_REMEMBER, eax=10, edx=20, **REGS)
            self.assertEqual(bool(get(u, row)), cls in (1, 2, 3, 4))
            if cls in (1, 2, 3, 4):
                self.assertEqual(struct.unpack('<3I', u.mem_read(row, 12)), (NOW, 10, 20))
                put(u, row + 12, NOW - 100)
                put(u, 0x446ae8, NOW + 20000)
                run(u, f.ALLY_REMEMBER, eax=10, edx=20)
                self.assertEqual(
                    get(u, row + 12), NOW - 100
                )  # Same identity, even after a long gap.
                for offset in (4, 8):
                    put(u, row + offset, 99)
                    run(u, f.ALLY_REMEMBER, eax=10, edx=20)
                    self.assertEqual(get(u, row + 12), 0)
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_allied_memory_rejects_player_inactive_and_reused_actor_records(self):
        for condition in (
            'player_id', 'player_flag', 'dead_victim', 'enemy_victim', 'bad_victim_owner',
            'dead_source', 'ally_source', 'bad_source_owner', 'source_slot_zero',
            'source_slot_high', 'zero', 'high'
        ):
            u, obj, ai, target, other, row, *_ = allied()
            u.mem_write(row, bytes(16))
            victim = 10
            if condition == 'zero':
                victim = 0
            elif condition == 'high':
                victim = 256
            elif condition == 'player_id':
                put(u, 0x441350, 10)
            else:
                a, b = {
                    'player_flag': (ai + 10, b'\1'),
                    'dead_victim': (ai, b'\0'),
                    'enemy_victim': (ai + 5, b'\2'),
                    'bad_victim_owner': (ai + 11, b'\x0b\0'),
                    'dead_source': (other, b'\0'),
                    'ally_source': (other + 5, b'\1'),
                    'bad_source_owner': (other + 11, b'\x15\0'),
                    'source_slot_zero': (target + 33, b'\0'),
                    'source_slot_high': (target + 33, b'\x3c')
                }[condition]
                u.mem_write(a, b)
            run(u, f.ALLY_REMEMBER, eax=victim, edx=20, **REGS)
            self.assertFalse(any(u.mem_read(row, 16)), condition)
            for name, value in dict(REGS, eax=victim, edx=20).items():
                self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)

    def test_allied_visible_requires_weapon_range_real_hit_and_no_solver_failure(self):
        for condition in (
            'clear', 'edge', 'far', 'blocked', 'failed', 'dead', 'no_weapon', 'invalid_weapon',
            'invalid_selection', 'zero', 'high'
        ):
            u, obj, ai, target, other, row, previews, outcomes = allied()
            oid = 20
            if condition in ('edge', 'far'):
                put(u, target + 15, (32 << 16) + (256 if condition == 'far' else 0))
            if condition == 'blocked':
                outcomes[20] = (30, 0)
            if condition == 'failed':
                outcomes[20] = (20, 1)
            if condition == 'dead':
                u.mem_write(target, b'\0')
            if condition == 'no_weapon':
                u.mem_write(0x3a5608 + 0x582 + 0x45, b'\0')
            if condition == 'invalid_weapon':
                u.mem_write(0x3a5608 + 0x582 + 0x45, b'\x21')
            if condition == 'invalid_selection':
                u.mem_write(0x3a5608 + 0x582 + 0xce, b'\4')
            if condition == 'zero':
                oid = 0
            if condition == 'high':
                oid = 256
            run(u, f.ALLY_VISIBLE, eax=ai, edx=oid, **REGS)
            self.assertEqual(
                u.reg_read(UC_X86_REG_EAX), int(condition in ('clear', 'edge')), condition
            )
            self.assertEqual(
                previews,
                [(10, 20, 0, 1)] if condition in ('clear', 'edge', 'blocked', 'failed') else [],
                condition
            )
            self.assertEqual(get(u, f.ACTIVE), 0)
            self.assertEqual(u.reg_read(UC_X86_REG_EDX), oid)
            for name, value in REGS.items():
                self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)

    def test_allied_preference_preserves_usable_target_and_checks_candidate_at_most_twice_per_second(
        self
    ):
        for current_usable, candidate_usable in (
            (False, True), (True, True), (False, False), (True, False)
        ):
            u, obj, ai, target, other, row, previews, outcomes = allied()
            actor(u, 30, slot=3, team=2, xyz=(21 << 16, 20 << 16, 0))
            u.mem_write(ai + 0xca, b'\x1e')
            outcomes[30] = (30 if current_usable else 0, 0)
            outcomes[20] = (20 if candidate_usable else 0, 0)
            u.mem_write(other + 6, b'\4')
            put(u, ai + 0x106, 99)
            u.mem_write(ai + 0xc4, b'\5')
            before = bytes(u.mem_read(ai, 334))
            run(u, f.ALLY_PREFER, eax=ai, **REGS)
            changed = not current_usable and candidate_usable
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(changed))
            self.assertEqual(get(u, row + 12), NOW)
            self.assertEqual([p[1] for p in previews], [30] if current_usable else [30, 20])
            if changed:
                self.assertEqual(bytes(u.mem_read(ai + 0xc9, 7)), b'\2\x14\4\x10\0\x14\0')
                self.assertEqual(get(u, ai + 0xd7), NOW)
                self.assertEqual(get(u, ai + 0xc5), NOW)
                self.assertEqual(get(u, ai + 0x106), 0)
            else:
                self.assertEqual(bytes(u.mem_read(ai, 334)), before)
            # Reset only target to exercise retry admission independently of same-target exit.
            u.mem_write(ai + 0xca, b'\x1e')
            previews.clear()
            put(u, 0x446ae8, NOW + 499)
            run(u, f.ALLY_PREFER, eax=ai)
            self.assertFalse(previews)
            put(u, 0x446ae8, NOW + 500)
            run(u, f.ALLY_PREFER, eax=ai)
            self.assertTrue(previews)

    def test_allied_preference_respects_orders_guard_identity_and_five_second_window(self):
        for order in range(11):
            for guard in (0, 1, 99):
                u, obj, ai, target, other, row, previews, outcomes = allied()
                u.mem_write(0x3805bb, bytes([order]))
                u.mem_write(0x380599, struct.pack('<H', guard))
                run(u, f.ALLY_PREFER, eax=ai)
                allowed = order in (1, 2, 3, 4, 7,
                                    8) and (guard == 0 or (order == 8 and guard == 1))
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(allowed), (order, guard))
                self.assertEqual(bool(previews), allowed)
        for condition in (
            'edge', 'expired', 'player', 'bad_owner', 'enemy', 'noncombat', 'vehicle',
            'same_target', 'dead_source', 'source_identity', 'source_faction', 'unaligned'
        ):
            u, obj, ai, target, other, row, previews, outcomes = allied()
            address = ai
            if condition in ('edge', 'expired'):
                put(u, 0x446ae8, NOW + 5000 + int(condition == 'expired'))
            if condition == 'player':
                put(u, 0x441350, 10)
            if condition == 'bad_owner':
                put(u, row + 4, 99)
            if condition == 'enemy':
                u.mem_write(ai + 5, b'\2')
            if condition == 'noncombat':
                u.mem_write(ai + 0xc3, b'\0')
            if condition == 'vehicle':
                u.mem_write(ai + 13, b'\2')
            if condition == 'same_target':
                u.mem_write(ai + 0xca, b'\x14')
            if condition == 'dead_source':
                u.mem_write(other, b'\0')
            if condition == 'source_identity':
                u.mem_write(other + 11, b'\x15\0')
            if condition == 'source_faction':
                u.mem_write(other + 5, b'\1')
            if condition == 'unaligned':
                address += 1
            before = bytes(u.mem_read(ai, 334))
            run(u, f.ALLY_PREFER, eax=address, **REGS)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(condition == 'edge'), condition)
            if condition != 'edge':
                self.assertEqual(bytes(u.mem_read(ai, 334)), before)
                self.assertFalse(previews)
            for name, value in REGS.items():
                self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)

    def test_allied_selection_calls_original_then_shared_chain_and_keeps_original_result(self):
        u, obj, ai, target, other, row, previews, outcomes = allied()
        calls = []
        u.mem_write(0x24c618, asm(0x24c618, 'mov eax,77;mov edx,88;ret'))

        def boundary(uc, a, n, d):
            calls.append(a)

        for address in (0x24c618, f.PREFER, f.FALLBACK, f.ALLY_PREFER):
            u.hook_add(UC_HOOK_CODE, boundary, begin=address, end=address)
        run(u, f.ALLY_SELECT, eax=ai, **REGS)
        self.assertEqual(calls, [0x24c618, f.PREFER, f.FALLBACK, f.ALLY_PREFER])
        self.assertEqual(u.mem_read(ai + 0xca, 1), b'\x14')
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 77)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 88)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 4)
        for name, value in REGS.items():
            self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value)

    def test_allied_reset_clears_all_three_tables_and_leaves_adjacent_memory_alone(self):
        u, *_ = allied()
        regions = (
            (f.ALERT_STATE, f.ALERT_END - f.ALERT_STATE), (f.STATE, f.STATE_SIZE),
            (f.ALLY_STATE, f.ALLY_STATE_SIZE)
        )
        for start, size in regions:
            u.mem_write(start, b'\x55' * size)
            u.mem_write(start + size, b'\xaa')
        execute_until(u, f.ALLY_RESET, {0x295402}, eax=99, **REGS)
        for start, size in regions:
            self.assertFalse(any(u.mem_read(start, size)))
            self.assertEqual(u.mem_read(start + size, 1), b'\xaa')
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 99)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x2b5c)
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)


if __name__ == '__main__':
    unittest.main()
