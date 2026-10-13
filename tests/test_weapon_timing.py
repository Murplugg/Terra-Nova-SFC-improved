"""Weapon phase and partial-volley contracts, with original calls as boundaries."""
from pathlib import Path
import sys, struct, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import weapon_timing as w, projectiles as p
from tests.test_render_views import Fixture, put, get, STACK
from tests.test_input_views import run
from tests.test_ai_firing import actor, execute_until
from patch_support import asm
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

WEAPON = 0x160000
FRAME = 0x170000
ROW = w.TABLE + 10 * w.STRIDE


def machine():
    u = Fixture().u
    for a, b in w.bodies() + p.volley_bodies():
        u.mem_write(a, b)
    actor(u, 10, slot=1)
    u.mem_write(WEAPON, b'\7')
    put(u, 0x35f400, 20)
    put(u, 0x446ae8, 1000)
    put(u, 0x35f3f8, 16)
    return u


def mark(u, **args):
    run(u, w.MARK, **dict(dict(eax=WEAPON, edx=10, ecx=20, ebx=1), **args))


class WeaponTimingTests(unittest.TestCase):

    def test_generators_have_no_history_and_installers_reject_partial_writes(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(w.bodies()), 29)
            self.assertEqual(len(p.physics_bodies()), 2)
            self.assertEqual(len(p.sweep_bodies()), 5)
            self.assertEqual(len(p.volley_bodies()), 15)
            with self.assertRaises(ValueError):
                p.sweep_bodies(vehicle_call=0)
        for part in ('weapon', 'physics', 'sweep', 'volley'):
            pieces = w.bodies() if part == 'weapon' else p._part(part, None)[0]
            sites = w.sites() if part == 'weapon' else p._part(part, None)[1]
            state = w.TABLE if part == 'weapon' else p.STATE if part == 'sweep' else None
            for problem in ('none', 'hook', 'partial', 'short'):
                ram = bytearray(0x2000000)
                writes = []
                for a, b in sites.items():
                    ram[a:a + len(b)] = b
                if problem == 'hook':
                    ram[next(iter(sites))] ^= 1
                if problem == 'partial':
                    a, b = pieces[0]
                    ram[a:a + len(b)] = b

                def write(a, b):
                    writes.append((a, b))
                    ram[a:a + len(b)] = b

                read = lambda a, n: ram[a:a + n - int(problem == 'short')]
                install = lambda: w.install(write, read) if part == 'weapon' else p.install(
                    write, read, part=part
                )
                if problem != 'none':
                    with self.assertRaises(ValueError):
                        install()
                    self.assertFalse(writes, (part, problem))
                else:
                    install()
                    self.assertEqual(writes, pieces)
                    writes.clear()
                    if state is not None:
                        ram[state:state + 4] = b'\x55' * 4
                    self.assertTrue(install()['already_installed'])
                    self.assertFalse(writes)
                    self.assertTrue(
                        w.verify(read) if part == 'weapon' else p.verify(read, part=part)
                    )
                    if state is not None:
                        self.assertEqual(ram[state:state + 4], b'\x55' * 4)

    def test_mark_requires_contiguous_eligible_frames_and_same_weapon_target(self):
        for condition in (
            'same_frame', 'next_frame', 'missed_frame', 'weapon_id', 'weapon_pointer', 'target',
            'backward', 'unavailable'
        ):
            u = machine()
            mark(u)
            put(u, ROW + 16, 1)
            args = {}
            if condition == 'next_frame':
                put(u, 0x35f400, 21)
            if condition == 'missed_frame':
                put(u, 0x35f400, 22)
            if condition == 'weapon_id':
                u.mem_write(WEAPON, b'\6')
            if condition == 'weapon_pointer':
                u.mem_write(WEAPON + 0x100, b'\7')
                args['eax'] = WEAPON + 0x100
            if condition == 'target':
                args['ecx'] = 21
            if condition == 'backward':
                put(u, 0x446ae8, 999)
            if condition == 'unavailable':
                args['ebx'] = 0
            mark(u, **args)
            self.assertEqual(
                get(u, ROW + 16), int(condition in ('same_frame', 'next_frame')), condition
            )
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
        u = machine()
        mark(u)
        self.assertEqual(get(u, ROW + 16), 0)  # Mark alone cannot arm a deadline.

    def test_base_carries_only_bounded_current_deadline_and_retains_difficulty_scaling(self):
        for condition in (
            'normal', 'future', 'too_late', 'stall', 'not_armed', 'wrong_deadline', 'wrong_frame',
            'period_edge', 'enemy_easy', 'enemy_hard'
        ):
            u = machine()
            mark(u)
            put(u, ROW + 16, 1)
            put(u, ROW + 20, 990)
            put(u, WEAPON + 10, 990)
            u.mem_write(0x395126 + 7 * 36, struct.pack('<H', 20))
            u.mem_write(0x442900, b'\1')
            # Non-SFC artwork invokes the original enemy difficulty table.
            if condition.startswith('enemy'):
                u.mem_write(0x3c3240 + 37 * 10 + 2, b'\5')
                u.mem_write(
                    0x39636a + 2, struct.pack('<H', 100 if condition == 'enemy_easy' else 50)
                )
            if condition == 'future':
                put(u, ROW + 20, 1001)
                put(u, WEAPON + 10, 1001)
            if condition == 'too_late':
                put(u, 0x35f3f8, 9)
            if condition == 'stall':
                put(u, 0x35f3f8, 101)
            if condition == 'not_armed':
                put(u, ROW + 16, 0)
            if condition == 'wrong_deadline':
                put(u, WEAPON + 10, 989)
            if condition == 'wrong_frame':
                put(u, 0x35f400, 21)
            if condition == 'period_edge':
                u.mem_write(0x395126 + 7 * 36, struct.pack('<H', 10))
            run(u, w.BASE, esi=10, edi=WEAPON, ebx=123, ecx=456, edx=789)
            self.assertEqual(
                u.reg_read(UC_X86_REG_EAX), 990 if condition in ('normal', 'enemy_easy') else 1000,
                condition
            )
            self.assertEqual(
                [u.reg_read(r) for r in (UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX)],
                [123, 456, 789]
            )

    def test_post_success_arms_exact_deadline_and_keeps_original_duration(self):
        u = machine()
        mark(u)
        execute_until(u, w.POST, {0x28f71a}, eax=123, edx=0x10032, esi=10, edi=WEAPON)
        self.assertEqual(get(u, ROW + 16), 1)
        self.assertEqual(get(u, ROW + 20), 1050)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 1000)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 50)

    def test_failure_dry_run_release_and_allocation_have_separate_reset_scope(self):
        for actual, result, armed in ((0, 0, 1), (1, 1, 1), (1, 0, 0), (1, 0xffff, 0)):
            u = machine()
            put(u, ROW + 16, 1)
            put(u, FRAME + 0x28, actual)
            put(u, FRAME - 0x2c, 10)
            # Common original epilogue: saved EBP, EDI, ESI then return + args.
            u.mem_write(FRAME, struct.pack('<4I', 111, 222, 333, 0x10000))
            execute_until(u, w.FAIL, {0x10000}, ebp=FRAME, eax=result)
            self.assertEqual(get(u, ROW + 16), armed)
        u = machine()
        u.mem_write(ROW, b'\x55' * 64)
        put(u, 0x441350, 10)
        execute_until(u, w.RELEASE, {0x290860})
        self.assertEqual(get(u, ROW + 16), 0)
        self.assertEqual(get(u, ROW + 20), 0x55555555)
        u.mem_write(ROW, b'\x55' * 64)
        u.mem_write(w.ALLOC + 0x80, asm(w.ALLOC + 0x80, 'mov eax,10;ret'))
        run(u, w.ALLOC)
        self.assertFalse(any(u.mem_read(ROW, 64)))
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 10)

    def test_partial_volley_uses_first_emitted_bolt_and_original_commit_path(self):
        for index, count, cont in (
            (1, 1, 0x28f36c), (2, 2, 0x28f3c2), (3, 3, 0x28f419), (4, 4, 0x28f46e),
            (5, 0, 0x28f4f9), (6, 0, 0x28f548)
        ):
            for result in (0, 1):
                u = machine()
                put(u, FRAME - 0x58, 17)
                put(u, FRAME - 8, 0)
                calls = []
                u.mem_write(0x2c6fa4, b'\xc3')
                u.hook_add(
                    UC_HOOK_CODE,
                    lambda uc, a, n, d: calls.append(uc.reg_read(UC_X86_REG_EAX)),
                    begin=0x2c6fa4,
                    end=0x2c6fa4
                )
                stop = execute_until(
                    u,
                    p.VOLLEY_CODE + index * 0x100, {0x28f5cc, cont},
                    eax=result,
                    ebp=FRAME,
                    esi=10,
                    edi=WEAPON,
                    ecx=99
                )
                self.assertEqual(stop, cont if result else 0x28f5cc)
                if not result:
                    self.assertEqual(u.mem_read(FRAME - 8, 2), b'\x11\0')
                    self.assertEqual(calls, [10] * count)
                else:
                    self.assertFalse(calls)
                self.assertEqual(u.reg_read(UC_X86_REG_ECX), 99)


if __name__ == '__main__':
    unittest.main()
