"""Elapsed-time actor behavior at original policy/RNG/controller boundaries."""
from pathlib import Path
import sys, struct, math, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import actor_timing as f, ai_response, descrambler as d
from tests.test_render_views import Fixture, put, word, get, STACK, STOP
from tests.test_input_views import run
from tests.test_ai_firing import actor, execute_until
from patch_support import asm
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

NOW = 100000


def machine(*parts):
    u = Fixture().u
    for part in parts:
        for a, b in f.part_bodies(part):
            u.mem_write(a, b)
    put(u, 0x446ae8, NOW)
    put(u, 0x35f400, 1)
    put(u, 0x35f3f8, 50)
    return u


def rng(u, result=1):
    calls = []
    value = [result]
    u.mem_write(0x2ddd70, b'\xc3')

    def record(uc, a, n, d):
        calls.append((uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_EDX)))
        uc.reg_write(UC_X86_REG_EAX, value[0])
        uc.reg_write(UC_X86_REG_EDX, value[0])

    u.hook_add(UC_HOOK_CODE, record, begin=0x2ddd70, end=0x2ddd70)
    return calls, value


def advance(u, delta):
    put(u, 0x446ae8, get(u, 0x446ae8) + delta)
    put(u, 0x35f400, get(u, 0x35f400) + 1)
    put(u, 0x35f3f8, delta)


class ActorTimingTests(unittest.TestCase):

    def test_direct_generation_atomic_install_and_live_state_repair(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source text')
        ):
            for part in f._GENERATORS:
                self.assertTrue(f.part_bodies(part))
        self.assertIs(ai_response.idle_mission_reset_body, f.idle_mission_reset_body)
        self.assertIs(ai_response.avoidance_slot_reset_body, f.avoidance_slot_reset_body)
        for part in f._GENERATORS:
            for fault in ('none', 'hook', 'partial', 'state', 'short'):
                if fault == 'state' and not f._STATE[part]:
                    continue
                with self.subTest(part=part, fault=fault):
                    ram = bytearray(0x2000000)
                    writes = []
                    for a, b in f._HOOKS[part].items():
                        ram[a:a + len(b)] = b
                    pieces = f.part_bodies(part)
                    if fault == 'hook':
                        ram[next(iter(f._HOOKS[part]))] ^= 1
                    if fault == 'partial':
                        a, b = pieces[0]
                        ram[a:a + len(b)] = b
                    if fault == 'state':
                        a, n = f._STATE[part][-1]
                        ram[a + n - 1] = 1

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    read = lambda a, n: ram[a:a + n - int(fault == 'short')]
                    if fault != 'none':
                        with self.assertRaises(ValueError):
                            f.install(write, read, part=part)
                        self.assertFalse(writes)
                    else:
                        f.install(write, read, part=part)
                        self.assertEqual(writes, pieces)
                        writes.clear()
                        for a, n in f._STATE[part]:
                            ram[a:a + n] = b'\x55' * n
                        live = bytes(ram)
                        self.assertTrue(f.verify(read, part=part))
                        self.assertTrue(f.install(write, read, part=part)['already_installed'])
                        self.assertFalse(writes)
                        for a, b in f._SHARED[part].items():
                            ram[a:a + len(b)] = b
                        f.install(write, read, part=part)
                        self.assertEqual(bytes(ram), live)

    def test_retry_ticks_track_elapsed_time_and_final_rng_range(self):
        for index, g in enumerate(f.GATES_GATES):
            for schedule in ([50] * 20, [16, 17, 17] * 20, [100] * 10):
                u = machine('gates')
                calls, value = rng(u)
                row = g['base'] + g['stride']
                u.mem_write(row, b'\1')
                word(u, row + 11, 10)
                u.mem_write(row + g['offset'], b'\1')
                for delta in schedule:
                    advance(u, delta)
                    execute_until(u, f.GATES_CODE + index * 0x400, {g['end']}, **{g['reg']: row})
                self.assertEqual(len(calls), 20, (g['name'], schedule[:3]))
                self.assertEqual(set(calls), {(32767 if index == 2 else 63, 0)})
                if index < 2:
                    self.assertEqual(bytes(u.mem_read(row + g['offset'], 1)), b'\1')

    def test_retry_pause_duplicate_stall_success_and_new_waiting_episode(self):
        g = f.GATES_GATES[1]
        u = machine('gates')
        calls, value = rng(u)
        row = g['base'] + 334
        u.mem_write(row, b'\1')
        word(u, row + 11, 10)
        u.mem_write(row + g['offset'], b'\1')
        tick = lambda: execute_until(u, f.GATES_CODE + 0x400, {g['end']}, esi=row)
        put(u, 0x35f3f8, 25)
        tick()
        self.assertFalse(calls)
        tick()
        self.assertFalse(calls)
        u.mem_write(0x35f3f4, b'\1')
        advance(u, 25)
        tick()
        self.assertFalse(calls)
        u.mem_write(0x35f3f4, b'\0')
        advance(u, 1000)
        tick()
        self.assertEqual(len(calls), 1)
        # A success stops retry rolls even when several elapsed periods are available.
        value[0] = 0
        advance(u, 200)
        tick()
        self.assertEqual(len(calls), 2)
        self.assertEqual(bytes(u.mem_read(row + g['offset'], 1)), b'\0')
        slot = g['table'] + 32
        u.mem_write(slot, b'\x55' * 32)
        execute_until(u, f.GATES_CODE + 0xf00, {0x250529}, esi=row)
        self.assertEqual(bytes(u.mem_read(slot, 32)), bytes(32))
        self.assertEqual(bytes(u.mem_read(row + g['offset'], 1)), b'\1')

    def test_perception_roll_cache_identity_cadence_and_caller_scope(self):
        u = machine('perception')
        calls, value = rng(u, 123)
        obj, ai = actor(u, 10, slot=2)
        squad = 0x3804f0 + 368
        put(u, STACK + 0x138, squad)
        row = f.PERCEPTION_TABLE + (61 + 2) * 8

        def query():
            run(u, f.PERCEPTION_CODE, ecx=ai, ebx=0x7fff, edx=0)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), u.reg_read(UC_X86_REG_EDX))

        query()
        self.assertEqual(len(calls), 1)
        advance(u, 49)
        value[0] = 321
        query()
        self.assertEqual(len(calls), 1)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 123)
        advance(u, 1)
        query()
        self.assertEqual(len(calls), 2)
        self.assertEqual(get(u, row), NOW + 50)
        advance(u, 137)
        query()
        self.assertEqual(len(calls), 3)
        self.assertEqual(get(u, row), NOW + 150)
        advance(u, 1000)
        query()
        self.assertEqual(len(calls), 4)
        self.assertEqual(get(u, row), NOW + 1187)
        word(u, ai + 11, 11)
        query()
        self.assertEqual(len(calls), 5)
        put(u, 0x446ae8, NOW)
        query()
        self.assertEqual(len(calls), 6)
        # Representative selection caching is limited to the fallback detector.
        put(u, STACK + 20, 0x257d86)
        run(u, f.PERCEPTION_CODE + 0x700, ecx=squad)
        n = len(calls)
        run(u, f.PERCEPTION_CODE + 0x700, ecx=squad)
        self.assertEqual(len(calls), n)
        put(u, STACK + 20, 0xabcdef)
        run(u, f.PERCEPTION_CODE + 0x700, ecx=squad, ebx=32767, edx=0)
        self.assertEqual(len(calls), n + 1)

    def test_avoidance_axes_hold_randomness_without_touching_actor_position(self):
        u = machine('avoidance')
        calls, value = rng(u, 17)
        obj, ai = actor(u, 10, slot=2, xyz=(100, 200, 300))
        run(u, f.AVOIDANCE_CODE, esi=ai)
        value[0] = 23
        run(u, f.AVOIDANCE_CODE + 0x100, esi=ai)
        self.assertEqual(len(calls), 2)
        u.mem_write(obj + 15, struct.pack('<3i', 400, 500, 600))
        advance(u, 49)
        run(u, f.AVOIDANCE_CODE, esi=ai)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 17)
        run(u, f.AVOIDANCE_CODE + 0x100, esi=ai)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 23)
        self.assertEqual(len(calls), 2)
        self.assertEqual(bytes(u.mem_read(obj + 15, 12)), struct.pack('<3i', 400, 500, 600))
        advance(u, 1)
        run(u, f.AVOIDANCE_CODE, esi=ai)
        self.assertEqual(len(calls), 3)
        word(u, ai + 11, 11)
        run(u, f.AVOIDANCE_CODE + 0x100, esi=ai)
        self.assertEqual(len(calls), 4)

    def test_drone_poll_continuity_and_bounded_lateness(self):
        u = machine('drone')
        obj, ai = actor(u, 10, cls=3, slot=2, team=2)
        target, _ = actor(u, 20, slot=3)
        u.mem_write(obj + 2, b'\5')
        word(u, ai + 0xc9, 20 * 256 + 3)
        put(u, ai + 0xf6, NOW - 260)
        row = f.DRONE_TABLE + 2 * 32
        execute_until(u, f.DRONE_CODE, {0x24bba5}, eax=ai)
        execute_until(u, f.DRONE_CODE + 0x600, {0x24bc86}, esi=ai, eax=NOW + 500)
        self.assertEqual(get(u, ai + 0xf6), NOW + 500)
        self.assertEqual(get(u, row + 16), 1)
        # Expected deadline plus original extra 250-ms readiness boundary.
        put(u, ai + 0xf6, NOW - 260)
        put(u, row + 20, NOW - 260)
        advance(u, 16)
        execute_until(u, f.DRONE_CODE, {0x24bba5}, eax=ai)
        # lateness 26 exceeds this 16-ms frame and must not carry.
        execute_until(u, f.DRONE_CODE + 0x600, {0x24bc86}, esi=ai, eax=NOW + 516)
        self.assertEqual(get(u, ai + 0xf6), NOW + 516)
        put(u, ai + 0xf6, NOW - 240)
        put(u, row + 20, NOW - 240)
        execute_until(u, f.DRONE_CODE + 0x600, {0x24bc86}, esi=ai, eax=NOW + 516)
        self.assertEqual(get(u, ai + 0xf6), NOW + 510)
        actor(u, 21, slot=4)
        word(u, ai + 0xc9, 21 * 256 + 4)
        advance(u, 16)
        execute_until(u, f.DRONE_CODE, {0x24bba5}, eax=ai)
        self.assertEqual(get(u, row + 16), 0)
        put(u, STACK, STOP)
        run(u, f.DRONE_CODE, eax=ai)  # duplicate frame returns, no original poll
        u.mem_write(0x35f3f4, b'\1')
        run(u, f.DRONE_CODE, eax=ai)
        self.assertEqual(get(u, row + 28), 0)

    def test_aircraft_controller_and_nozzles_share_actual_steps(self):
        for schedule in ([50] * 20, [16, 17, 17] * 20, [100] * 10):
            u = machine('aircraft', 'nozzles')
            obj, ai = actor(u, 10, cls=3, slot=1)
            u.mem_write(obj + 2, b'\7')
            record = 0x39e590 + 335
            word(u, record, 10)
            word(u, 0x397a8a, 10)
            movement = []
            engines = []
            # Original controller and engine routines are modeled boundaries.
            u.mem_write(f.NOZZLES_TRAMP, b'\xc3')
            u.mem_write(f.NOZZLES_ENGINE, b'\xc3')

            def record_call(uc, a, n, d):
                (movement if a == f.NOZZLES_TRAMP else engines).append(
                    uc.reg_read(UC_X86_REG_EDX if a == f.NOZZLES_TRAMP else UC_X86_REG_EAX)
                )

            for a in (f.NOZZLES_TRAMP, f.NOZZLES_ENGINE):
                u.hook_add(UC_HOOK_CODE, record_call, begin=a, end=a)
            for delta in schedule:
                advance(u, delta)
                run(u, f.AIRCRAFT_CODE, eax=record, edx=delta)
                run(u, f.NOZZLES_CODE + 0x100, eax=delta)
            self.assertEqual(movement, [50] * 20)
            self.assertEqual(engines, [50] * 20)
            run(u, f.AIRCRAFT_CODE, eax=record, edx=schedule[-1])
            self.assertEqual(len(movement), 20)
            advance(u, 1000)
            run(u, f.AIRCRAFT_CODE, eax=record, edx=1000)
            self.assertEqual(len(movement), 21)
            self.assertEqual(len(engines), 21)

    def test_aircraft_passthrough_pause_reuse_and_deleted_slot(self):
        u = machine('aircraft')
        obj, ai = actor(u, 10, cls=3, slot=1)
        record = 0x39e590 + 335
        word(u, record, 10)
        row = f.AIRCRAFT_TABLE + 32
        calls = []
        u.mem_write(f.AIRCRAFT_ORIGINAL, b'\xc3')
        u.hook_add(
            UC_HOOK_CODE,
            lambda uc, a, n, d: calls.append(uc.reg_read(UC_X86_REG_EDX)),
            begin=f.AIRCRAFT_ORIGINAL,
            end=f.AIRCRAFT_ORIGINAL
        )
        # Types outside the pickup range retain the incoming update duration.
        u.mem_write(obj + 2, b'\4')
        run(u, f.AIRCRAFT_CODE, eax=record, edx=17)
        self.assertEqual(calls, [17])
        u.mem_write(obj + 2, b'\7')
        advance(u, 25)
        run(u, f.AIRCRAFT_CODE, eax=record, edx=25)
        self.assertEqual(get(u, row + 16), 25)
        u.mem_write(0x35f3f4, b'\1')
        run(u, f.AIRCRAFT_CODE, eax=record, edx=25)
        self.assertEqual(get(u, row + 16), 0)
        u.mem_write(0x35f3f4, b'\0')
        advance(u, 25)
        run(u, f.AIRCRAFT_CODE, eax=record, edx=25)
        u.mem_write(obj + 2, b'\10')
        advance(u, 25)
        run(u, f.AIRCRAFT_CODE, eax=record, edx=25)
        self.assertEqual(calls, [17])
        self.assertEqual(get(u, row + 16), 25)
        u.mem_write(row + 32, b'\x55' * 32)
        execute_until(u, f.AIRCRAFT_FREE, {f.AIRCRAFT_DELETE + 7}, eax=10)
        self.assertEqual(bytes(u.mem_read(row, 32)), bytes(32))
        self.assertEqual(bytes(u.mem_read(row + 32, 32)), b'\x55' * 32)

    def test_manual_drone_turn_uses_elapsed_time_and_retains_small_inputs(self):
        # These are complete one-second schedules. The expected angle comes
        # from the original doubled control at the 50-ms calibration interval.
        # Execute the patched original site, including its heading store.
        schedules = ([50] * 20, [16, 17, 17] * 20, [8, 8, 9] * 40,
                     [100] * 10, [1] * 1000)
        for kind in (0, 1):
            for turn in (-820, 819, -1, 1):
                for schedule in schedules:
                    with self.subTest(kind=kind, turn=turn, frames=len(schedule)):
                        u = machine('aircraft')
                        obj, _ = actor(u, 10, cls=3, slot=1)
                        u.mem_write(obj + 2, bytes([kind]))
                        record = 0x39e590 + 335
                        word(u, record, 10)
                        word(u, record + 0x136, turn & 0xffff)
                        word(u, 0x396868 + 6, 10)
                        for dt in schedule:
                            run(u, f.AIRCRAFT_TURN_SITE,
                                end=f.AIRCRAFT_TURN_SITE + len(f.AIRCRAFT_TURN_OLD),
                                edi=record, esi=obj, ebp=dt, ebx=0x12345678, ecx=0x87654321)
                            self.assertEqual(u.reg_read(UC_X86_REG_EBX), 0x12345678)
                            self.assertEqual(u.reg_read(UC_X86_REG_ECX), 0x87654321)
                            self.assertEqual(u.reg_read(UC_X86_REG_EDI), record)
                            self.assertEqual(u.reg_read(UC_X86_REG_ESI), obj)
                            self.assertEqual(u.reg_read(UC_X86_REG_EBP), dt)
                        self.assertEqual(get(u, obj + 0x1b) & 0xffff, (turn * 40) & 0xffff)
                        self.assertEqual(get(u, f.AIRCRAFT_TABLE + 32 + 28), 0)

    def test_manual_drone_turn_keeps_automatic_control_and_resets_fraction(self):
        u = machine('aircraft')
        obj, _ = actor(u, 10, cls=3, slot=1)
        record, row = 0x39e590 + 335, f.AIRCRAFT_TABLE + 32
        word(u, record, 10)
        word(u, record + 0x136, 1)
        word(u, 0x396868, 10)

        def step(dt=16):
            run(u, f.AIRCRAFT_TURN_SITE,
                end=f.AIRCRAFT_TURN_SITE + len(f.AIRCRAFT_TURN_OLD),
                edi=record, esi=obj, ebp=dt)
            return get(u, obj + 0x1b) & 0xffff

        step()
        self.assertEqual(get(u, row + 28), 32)
        # A changed owner cannot inherit the preceding drone's fractional turn.
        word(u, record, 11)
        step()
        self.assertEqual(get(u, row + 28), 32)
        for dt, paused in ((0, False), (-1, False), (16, True)):
            put(u, row + 28, 32)
            before = get(u, obj + 0x1b) & 0xffff
            u.mem_write(0x35f3f4, bytes([paused]))
            self.assertEqual(step(dt), before)
            self.assertEqual(get(u, row + 28), 0)
        u.mem_write(0x35f3f4, b'\0')
        before = get(u, obj + 0x1b) & 0xffff
        put(u, row + 28, 32)
        self.assertEqual(step(1000), (before + 2) & 0xffff)
        self.assertEqual(get(u, row + 28), 0)
        word(u, record + 0x136, 0)
        put(u, row + 28, 32)
        before = get(u, obj + 0x1b) & 0xffff
        self.assertEqual(step(), before)
        self.assertEqual(get(u, row + 28), 0)

        word(u, record, 10)
        word(u, record + 0x136, 819)
        for kind, following, target, selected in (
                (0, 1, 0, 10), (1, 0, 20, 10), (1, 0, 0, 12),
                *((k, 0, 0, 10) for k in range(2, 15))):
            u.mem_write(obj + 2, bytes([kind]))
            u.mem_write(0x3968b4, bytes([following]))
            word(u, 0x396868, selected)
            word(u, 0x397c90, target)
            put(u, row + 24, 10)
            put(u, row + 28, 32)
            before = get(u, obj + 0x1b) & 0xffff
            self.assertEqual(step(), (before + 1638) & 0xffff)
            self.assertEqual(bytes(u.mem_read(row + 24, 8)), bytes(8))

    def test_original_keyboard_conversion_reaches_manual_drone_turn(self):
        # Retain the actual keyboard scanner, movement tables and converters.
        # Only the unrelated AI-order cancellation boundary is modeled.
        from original_inputs import original_ram
        if not any(original_ram[0x2765f4:0x276813]):
            self.skipTest('Supply the verified retail executable for keyboard checks')
        self.assertEqual(bytes(original_ram[f.AIRCRAFT_TURN_SITE:
                                          f.AIRCRAFT_TURN_SITE + len(f.AIRCRAFT_TURN_OLD)]),
                         f.AIRCRAFT_TURN_OLD)
        u = machine('aircraft')
        for lo, hi in ((0x2765f4, 0x276813), (0x27c8b8, 0x27cc85),
                       (0x35b338, 0x35b3bc), (0x35b618, 0x35b66e)):
            u.mem_write(lo, bytes(original_ram[lo:hi]))
        u.mem_write(0x24bb1c, b'\xc3')
        obj, _ = actor(u, 10, cls=3, slot=1)
        record, bitmap = 0x39e590 + 335, 0x1900000
        word(u, record, 10)
        word(u, 0x396868, 10)
        put(u, 0x44c5d0, bitmap)
        for scancode, expected in ((0x1e, -820), (0x20, 819)):
            keys = bytearray(32)
            for key in (0x1d, scancode):  # Ctrl + A/D.
                keys[key // 8] |= 1 << (key % 8)
            u.mem_write(bitmap, bytes(keys))
            run(u, 0x2765f4, end=0x276813)
            self.assertEqual(struct.unpack('<h', u.mem_read(record + 0x136, 2))[0], expected)
            word(u, obj + 0x1b, 0)
            put(u, f.AIRCRAFT_TABLE + 32 + 28, 0)
            for dt in [16, 17, 17] * 20:
                run(u, f.AIRCRAFT_TURN_SITE,
                    end=f.AIRCRAFT_TURN_SITE + len(f.AIRCRAFT_TURN_OLD),
                    edi=record, esi=obj, ebp=dt)
            self.assertEqual(get(u, obj + 0x1b) & 0xffff, (expected * 40) & 0xffff)

    def test_mission_and_slot_resets_follow_one_table_ownership_chain(self):
        parts = ('drone', 'aircraft', 'gates', 'perception', 'avoidance', 'idle')
        u = machine(*parts)
        tables = (
            (f.DRONE_TABLE, 60 * 32), (f.AIRCRAFT_TABLE, 40 * 32),
            (f.GATES_TABLE, f.GATES_TABLE_SIZE), (f.PERCEPTION_TABLE, f.PERCEPTION_TABLE_SIZE),
            (f.AVOIDANCE_TABLE, f.AVOIDANCE_TABLE_SIZE), (f.IDLE_TABLE, f.IDLE_TABLE_SIZE)
        )
        for a, n in tables:
            u.mem_write(a, b'\x55' * n)
        execute_until(u, f.IDLE_MISSION_RESET, {0x249b33})
        for a, n in tables:
            self.assertEqual(bytes(u.mem_read(a, n)), bytes(n), hex(a))
        for a, n in tables:
            u.mem_write(a, b'\x55' * n)
        ai = f.DRONE_AI + 2 * 334
        execute_until(u, f.AVOIDANCE_SLOT_RESET, {0x24b533}, esi=ai, eax=3)
        for base, stride in (
            (f.DRONE_TABLE, 32), (f.GATES_TABLE + 0x400, 32), (f.GATES_TABLE + 0xc00, 32),
            (f.AVOIDANCE_TABLE, 16)
        ):
            self.assertEqual(bytes(u.mem_read(base + stride * 2, stride)), bytes(stride))
            self.assertEqual(bytes(u.mem_read(base + stride, stride)), b'\x55' * stride)
        for squad in range(32):
            a = f.PERCEPTION_TABLE + (squad * 61 + 2) * 8
            self.assertEqual(bytes(u.mem_read(a, 8)), bytes(8))
            self.assertEqual(bytes(u.mem_read(a - 8, 8)), b'\x55' * 8)
        self.assertEqual(bytes(u.mem_read(f.AIRCRAFT_TABLE, 32)), b'\x55' * 32)

    def test_idle_pose_holds_heading_discards_stall_catchup_and_resets_moving(self):
        u = machine('idle')
        obj, ai = actor(u, 10, slot=2)
        pose = 0x3a56e6 + 2 * 0x582
        word(u, pose + 0x21b, 10)
        word(u, pose + 0x227, 1234)
        row = f.IDLE_TABLE + 2 * 16
        put(u, 0x3924e0, round(.016 * 65536))
        tick = lambda: execute_until(u, f.IDLE_CODE, {f.IDLE_SITE + 5, 0x280d0b}, ebp=pose)
        self.assertEqual(tick(), 0x280d0b)
        self.assertEqual(get(u, 0x3924f8) & 65535, 1234)
        advance(u, 17)
        self.assertEqual(tick(), 0x280d0b)
        advance(u, 17)
        self.assertEqual(tick(), f.IDLE_SITE + 5)
        advance(u, 1000)
        self.assertEqual(tick(), f.IDLE_SITE + 5)
        self.assertEqual(get(u, row + 8), 0)
        execute_until(u, f.IDLE_CODE + 0x700, {f.IDLE_MOVING + 6}, ebp=pose)
        self.assertEqual(bytes(u.mem_read(row, 16)), bytes(16))

    def test_pose_slew_and_damping_keep_fifty_ms_contract_and_signed_rounding(self):
        u = machine('pose')
        for ms in (0, 1, 16, 33, 50, 100, 1000):
            dt = round(ms * 65536 / 1000)
            put(u, 0x3924e0, dt)
            for delta in (-2000, -500, 0, 500, 2000):
                execute_until(u, f.POSE_CODE, {0x281235}, eax=delta & 0xffffffff)
                limit = (min(dt, 6554) * 16380 + 32768) >> 16
                self.assertEqual(
                    u.reg_read(UC_X86_REG_EDX),
                    max(-limit, min(limit, delta)) & 0xffffffff
                )
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), delta & 0xffffffff)
            for velocity in (-8000, -7, 0, 7, 8000):
                execute_until(u, f.POSE_CODE + 0x100, {0x280e75}, edi=velocity & 0xffffffff)
                expected = velocity - (velocity >> 3) if ms == 50 else math.ceil(
                    velocity * (7 / 8)**(min(ms, 100) / 50)
                )
                removed = u.reg_read(UC_X86_REG_EAX)
                self.assertEqual(
                    (velocity - removed) & 0xffffffff, expected & 0xffffffff, (ms, velocity)
                )
                self.assertEqual(u.reg_read(UC_X86_REG_EDX), velocity & 0xffffffff)




class DescramblerPacingTests(unittest.TestCase):
    """Whole-line noise needs a slower clock than readable character scrolling.

    Two owner snapshots exposed distracting weak reception despite the earlier
    timer working correctly. Execute the timer and its real completion helper;
    model only the original random-line generator. Resource-backed panel replays
    separately check the visible line and the adjacent signal thresholds.
    """

    def test_noise_cadence_holds_text_and_survives_signal_transitions(self):
        import struct
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_EIP
        for fps in (20, 60, 120):
            with self.subTest(fps=fps):
                u=Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0, 0x2000000)
                for address, code in d.bodies():
                    u.mem_write(address, code)
                # Skip the original random-letter generator after counting it.
                u.mem_write(0x26eb4a, asm(0x26eb4a, f'jmp {d.FINISH}'))
                updates=[]
                u.hook_add(UC_HOOK_CODE, lambda *args: updates.append(1), begin=0x26eb4a, end=0x26eb4a)
                put=lambda a,v:u.mem_write(a, struct.pack('<I',v))
                def draw(now, signal=0xe000, end=0x26ebe3):
                    put(0x446ae8,now)
                    u.mem_write(0x35b184,b'\1')
                    u.reg_write(UC_X86_REG_ESP,0x1700000)
                    u.reg_write(UC_X86_REG_ECX,signal)
                    u.reg_write(UC_X86_REG_ESI,0x1400000)
                    u.emu_start(d.WEAK,end,count=10000)
                    self.assertEqual(u.reg_read(UC_X86_REG_EIP),end)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP),0x1700000)
                    if signal>0x8000:
                        self.assertEqual(bytes(u.mem_read(0x35b184,1)),b'\0')
                for i in range(fps+1):
                    draw(100000+round(i*1000/fps))
                self.assertEqual(len(updates),11)  # Initial line and ten timed replacements.
                draw(101000)
                self.assertEqual(len(updates),11)  # Repainting at the same clock holds the line.
                draw(101001,0x8000,0x26ebac)
                self.assertEqual(bytes(u.mem_read(d.NOISE,4)),b'\0'*4)
                draw(101002,0x8001)
                self.assertEqual(len(updates),12)  # Reception returns without waiting on stale text.
                draw(100000)
                self.assertEqual(len(updates),13)  # A restarted mission clock resets once.


if __name__ == '__main__':
    unittest.main()
