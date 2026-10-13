"""Cadence branch/ABI contracts; actual firing remains an engine boundary."""
from pathlib import Path
import sys, struct, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import ai_cadence as f
from tests.test_render_views import Fixture, put, get, STACK
from tests.test_ai_firing import actor, execute_until
from tests.test_input_views import run
from tests.test_option_lifecycle import Fixture as OptionsFixture
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

IMPORTS = dict(GetModuleHandleA=0x300000, GetProcAddress=0x300004)
ORIGINAL = 0x251d79
EXTRA = 0x251d97
WAIT = 0x251f79
REGS = dict(ebx=0x1234, ecx=0x2345, edx=0x3456, edi=0x4567, ebp=0x5678)


def machine(cls=1, team=1, weapon=7):
    u = Fixture().u
    for a, b in f.bodies(IMPORTS) + [(f.fire.RESOLVE, f.fire.selected_weapon_body())]:
        u.mem_write(a, b)
    obj, ai = actor(u, 10, cls=cls, slot=1, team=team)
    for base, stride, off in (
        (0x3a5608, 0x582, 0x45), (0x3a19e8, 296, 0x17), (0x39c750, 121, 0x33)
    ):
        u.mem_write(base + stride + off, bytes([weapon]))
    put(u, f.STATE, 1)
    put(u, f.STATE + 4, 1)
    put(u, 0x441350, 1)
    put(u, 0x446ae8, 10000)
    put(u, ai + 0xf1, 9999)
    return u, obj, ai


class AICadenceTests(unittest.TestCase):

    def test_explicit_imports_without_history_and_atomic_installation(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(f.bodies(IMPORTS)), 14)
            self.assertNotEqual(
                f.bodies(IMPORTS), f.bodies({
                    k: v + 0x100
                    for k, v in IMPORTS.items()
                })
            )
            for bad in (
                {}, {
                    'GetModuleHandleA': 0,
                    'GetProcAddress': 0x300004
                }, {
                    'GetModuleHandleA': 0x300000,
                    'GetProcAddress': 0x300000
                }
            ):
                with self.assertRaises(ValueError):
                    f.bodies(bad)
        for problem in (
            'none', 'hook', 'partial', 'reservation', 'resolver', 'fps', 'imports', 'short',
            'bad_preimage'
        ):
            ram = bytearray(0x2000000)
            writes = []
            for a, b in list(f.sites().items()) + f.providers(IMPORTS):
                ram[a:a + len(b)] = b
            original = bytes(ram)
            if problem == 'hook':
                ram[f.GATE_SITE] ^= 1
            if problem == 'partial':
                a, b = f.bodies(IMPORTS)[0]
                ram[a:a + len(b)] = b
            if problem == 'reservation':
                ram[f.END - 1] = 1
            if problem == 'resolver':
                ram[f.fire.RESOLVE] ^= 1
            if problem == 'fps':
                ram[f.fps.INIT] ^= 1

            def write(a, b):
                writes.append((a, b))
                ram[a:a + len(b)] = b

            read = lambda a, n: ram[a:a + n - int(problem == 'short')]
            if problem != 'none':
                with self.assertRaises(ValueError):
                    f.install(
                        write,
                        read, {} if problem == 'imports' else IMPORTS,
                        gate_before=b'bad' if problem == 'bad_preimage' else f.ORIGINAL_GATE
                    )
                self.assertFalse(writes, problem)
            else:
                f.install(write, read, IMPORTS)
                self.assertEqual(writes, f.bodies(IMPORTS))
                writes.clear()
                ram[f.STATE:f.STATE + 4] = b'\x55' * 4
                self.assertTrue(f.verify(read, IMPORTS))
                self.assertTrue(f.install(write, read, IMPORTS)['already_installed'])
                self.assertFalse(writes)
                self.assertEqual(ram[f.STATE:f.STATE + 4], b'\x55' * 4)
                self.assertEqual(f.predecessor_view(ram, IMPORTS), original)

    def test_stock_poll_branch_is_unchanged_and_never_initializes_preference(self):
        u, obj, ai = machine()
        calls = []
        u.hook_add(UC_HOOK_CODE, lambda uc, a, n, d: calls.append(a), begin=f.INIT, end=f.INIT)
        for enabled in (0, 1):
            put(u, f.STATE, 0)
            put(u, f.STATE + 4, enabled)
            for elapsed in (251, 1000, 0xffffffff):
                stop = execute_until(
                    u, f.GATE, {ORIGINAL, EXTRA, WAIT}, eax=elapsed, esi=ai, **REGS
                )
                self.assertEqual(stop, ORIGINAL)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), elapsed)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
        self.assertFalse(calls)

    def test_all_weapons_both_factions_and_supported_classes_obey_opt_in_and_cooldown(self):
        for cls in (1, 2, 4):
            for team in (1, 2):
                u, obj, ai = machine(cls, team)
                base, stride, off = {
                    1: (0x3a5608, 0x582, 0x45),
                    2: (0x3a19e8, 296, 0x17),
                    4: (0x39c750, 121, 0x33)
                }[cls]
                for weapon in range(1, 33):
                    u.mem_write(base + stride + off, bytes([weapon]))
                    for enabled in (0, 1):
                        put(u, f.STATE + 4, enabled)
                        for deadline in (9999, 10000, 10001):
                            put(u, ai + 0xf1, deadline)
                            stop = execute_until(
                                u, f.GATE, {ORIGINAL, EXTRA, WAIT}, eax=250, esi=ai, **REGS
                            )
                            self.assertEqual(
                                stop, EXTRA if enabled and deadline < 10000 else WAIT,
                                (cls, team, weapon, enabled, deadline)
                            )
                            self.assertEqual(get(u, ai + 0xf1), deadline)
                            for name, value in dict(REGS, eax=250, esi=ai).items():
                                self.assertEqual(
                                    u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value
                                )
                            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)

    def test_extra_polls_exclude_player_invalid_owner_dead_actor_and_bad_weapon(self):
        for condition in (
            'player', 'zero', 'negative', 'high', 'dead', 'scenery', 'unsupported', 'no_weapon',
            'invalid_weapon', 'bad_selection'
        ):
            u, obj, ai = machine()
            if condition == 'player':
                put(u, 0x441350, 10)
            if condition in ('zero', 'negative', 'high'):
                u.mem_write(
                    ai + 11,
                    struct.pack('<H', {
                        'zero': 0,
                        'negative': 65535,
                        'high': 300
                    }[condition])
                )
            if condition == 'dead':
                u.mem_write(obj, b'\0')
            if condition == 'scenery':
                u.mem_write(obj + 1, b'\0')
            if condition == 'unsupported':
                u.mem_write(obj + 1, b'\3')
            if condition in ('no_weapon', 'invalid_weapon'):
                u.mem_write(0x3a5608 + 0x582 + 0x45, bytes([0 if condition == 'no_weapon' else 33]))
            if condition == 'bad_selection':
                u.mem_write(0x3a5608 + 0x582 + 0xce, b'\4')
            stop = execute_until(u, f.GATE, {ORIGINAL, EXTRA, WAIT}, eax=0, esi=ai, **REGS)
            self.assertEqual(stop, WAIT, condition)

    def test_gate_rechecks_every_time_without_firing_or_mutating_timing_rows(self):
        u, obj, ai = machine()
        sentinel = b'\x5a' * (f.POLL_COUNT * f.POLL_STRIDE)
        u.mem_write(f.POLL_TABLE, sentinel)
        # Downstream firing/permission is deliberately a boundary: admission
        # must return the original frame and must not synthesize a projectile.
        for elapsed, enabled, deadline, expected in (
            (0, 1, 9999, EXTRA), (16, 1, 10000, WAIT), (250, 0, 9999, WAIT), (250, 1, 9999, EXTRA)
        ):
            put(u, f.STATE + 4, enabled)
            put(u, ai + 0xf1, deadline)
            self.assertEqual(
                execute_until(u, f.GATE, {ORIGINAL, EXTRA, WAIT}, eax=elapsed, esi=ai), expected
            )
        self.assertEqual(bytes(u.mem_read(f.POLL_TABLE, len(sentinel))), sentinel)

    def test_profile_defaults_and_switches_restore_vanilla_including_railgun(self):
        x = OptionsFixture()
        u = x.u
        x.initialize()
        obj, ai = actor(u, 10, slot=1, team=1)
        u.mem_write(f.fire.RESOLVE, f.fire.selected_weapon_body())
        u.mem_write(0x3a5608 + 0x582 + 0x45, b'\7')
        put(u, 0x441350, 1)
        put(u, 0x446ae8, 10000)
        put(u, ai + 0xf1, 9999)
        self.assertEqual(get(u, f.STATE + 4), 0)
        self.assertEqual(execute_until(u, f.GATE, {ORIGINAL, EXTRA, WAIT}, eax=10, esi=ai), WAIT)
        for enabled in (1, 0):
            put(u, f.STATE + 8, enabled)
            x.call(f.SAVE)
            self.assertEqual(x.values['WeaponTimedAI'], enabled)
            self.assertEqual(
                execute_until(u, f.GATE, {ORIGINAL, EXTRA, WAIT}, eax=10, esi=ai),
                EXTRA if enabled else WAIT
            )

    def test_profile_path_exhaustion_is_bounded_and_can_retry(self):
        u, obj, ai = machine()
        put(u, f.STATE, 0)
        module = 0x1800000
        proc = module + 16
        read = module + 32
        write = module + 48
        put(u, IMPORTS['GetModuleHandleA'], module)
        put(u, IMPORTS['GetProcAddress'], proc)
        u.mem_write(module, b'\xc2\x04\0')
        u.mem_write(proc, b'\xc2\x08\0')
        u.mem_write(read, b'\xc2\x10\0')
        seen = []

        def api(uc, a, n, d):
            if a == module:
                uc.reg_write(UC_X86_REG_EAX, 1)
            if a == proc:
                sp = uc.reg_read(UC_X86_REG_ESP)
                name = bytes(uc.mem_read(get(uc, sp + 8), 32)).split(b'\0')[0]
                uc.reg_write(UC_X86_REG_EAX, read if name == b'GetPrivateProfileIntA' else write)
            if a == read:
                seen.append(a)
                uc.reg_write(UC_X86_REG_EAX, 0)

        u.hook_add(UC_HOOK_CODE, api)
        u.mem_write(0x1d08400, b'x' * 256 + b'\0')
        u.mem_write(f.STATE + 64 + 264, b'\xaa')
        run(u, f.INIT)
        self.assertEqual(get(u, f.STATE), 0)
        self.assertFalse(seen)
        self.assertEqual(u.mem_read(f.STATE + 64 + 264, 1), b'\xaa')
        u.mem_write(0x1d08400, b'C:/game/\0')
        run(u, f.INIT)
        self.assertEqual(get(u, f.STATE), 1)
        self.assertEqual(len(seen), 1)


if __name__ == '__main__':
    unittest.main()
