"""AI range/selection/clearance contracts; original continuations are boundaries."""
from pathlib import Path
import sys, struct, random, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import ai_firing as f
from features import weapon_timing as timing
from patch_support import asm
from tests.test_render_views import Fixture, put, get, STACK, STOP
from tests.test_input_views import run
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

POINT = 0x140000
AI = 0x150000
WEAPON = 0x160000
FRAME = 0x1800000
OUT = 0x150300


def machine():
    u = Fixture().u
    for a, b in f.bodies() + f.choice_bodies() + [(f.RESOLVE, f.selected_weapon_body())]:
        u.mem_write(a, b)
    return u


def actor(u, oid, cls=1, slot=1, team=1, xyz=(0, 0, 0), alive=1):
    a = 0x3c3240 + 37 * oid
    u.mem_write(a, bytes(37))
    u.mem_write(a, bytes([alive, cls, 0]) + struct.pack('<H', slot))
    u.mem_write(a + 33, bytes([slot]))
    u.mem_write(a + 15, struct.pack('<3i', *xyz))
    row = 0x3832f0 + 334 * slot
    u.mem_write(row, bytes(334))
    u.mem_write(row, bytes([alive]))
    u.mem_write(row + 5, bytes([team]))
    u.mem_write(row + 11, struct.pack('<H', oid))
    return a, row


def execute_until(u, address, stops, **registers):
    seen = []

    def boundary(uc, a, n, d):
        if a in stops:
            seen.append(a)
            uc.emu_stop()

    hook = u.hook_add(UC_HOOK_CODE, boundary)
    u.reg_write(UC_X86_REG_ESP, STACK)
    u.reg_write(UC_X86_REG_EFLAGS, 0x247)
    for name, value in registers.items():
        u.reg_write(globals()['UC_X86_REG_' + name.upper()], value)
    u.emu_start(address, 0, count=100000)
    u.hook_del(hook)
    assert len(seen) == 1
    return seen[0]


class EnemyLaserSelectionTests(unittest.TestCase):
    """Exercise the original selector with an authored custom enemy loadout.

    The observed Captain had an empty Railgun and a healthy Laser. These cases
    isolate the faction exclusion and retain real readiness/scoring code from
    the user's original executable. Catalog fields are explicit test data;
    this does not simulate controller movement or a complete firefight.
    """

    # The selector's AI classes differ from object classes for structures/drones.
    PROFILES = {
        1: (1, 0x3a5608, 0x582, 0x81, 0xce, 0x45, 0x86),
        2: (2, 0x3a19e8, 296, 0x35, 0x36, 0x17, 0x37),
        3: (4, 0x39c750, 121, 0x0d, 0x0e, 0x33, 0x56),
        4: (3, 0x39e590, 335, 0x4a, 0x4b, 0x2a, 0x4c),
    }
    # Customized Enemy Outfitting maps its 26 nonempty choices to these IDs.
    OFFERED = (2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 18, 19, 20,
               21, 22, 23, 24, 25, 26, 27, 29, 30, 31, 32)

    def prepare(self, *, fixed=True, faction=2, weapon=4, health=300,
                charge=1000, ammo=1, deadline=0, ai_class=1, clock=1000):
        from original_inputs import original_ram
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        if not any(original_ram[0x250e58:0x25129b]):
            self.skipTest('Requires the original retail executable')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(0, bytes(original_ram))
        if fixed:
            self.assertEqual(bytes(u.mem_read(0x25124b, 2)), f.CHOICE_SITES[0x25124b])
            for address in (0x25124b, 0x251170):
                self.assertEqual(bytes(u.mem_read(address, len(f.CHOICE_SITES[address]))),
                                 f.CHOICE_SITES[address])
                u.mem_write(address, dict(f.choice_bodies())[address])
        cls, base, stride, count, selected, equipped, energy = self.PROFILES[ai_class]
        actor(u, 10, cls=cls, slot=1, team=faction)
        ai = 0x3832f0 + 334
        record = base + stride
        u.mem_write(ai + 13, bytes([ai_class]))
        u.mem_write(record + count, b'\x01')
        u.mem_write(record + selected, b'\x00')
        u.mem_write(record + equipped,
                    struct.pack('<BBHHIIB', weapon, 2, health, ammo, 0, deadline, 0))
        put(u, record + energy, charge << 16)
        put(u, 0x446ae8, clock)
        # Direct-fire catalog: damage, charge/ammo/health, range and cooldown.
        cat = 0x395110 + weapon*36
        u.mem_write(cat, bytes(36))
        u.mem_write(cat+5, struct.pack('<H', 10))
        u.mem_write(cat+8, struct.pack('<3H', 20 if weapon == 4 else 0,
                                      0 if weapon == 4 else 100, 300))
        u.mem_write(cat+14, struct.pack('<H', 100))
        u.mem_write(cat+22, struct.pack('<H', 100))
        for a in (0x3598dc, 0x3598e0, 0x3598e4):
            put(u, a, 1)
        return u, ai, record

    def select(self, *, force=1, **kwargs):
        u, ai, _ = self.prepare(**kwargs)
        run(u, 0x250e58, eax=ai, edx=force)
        return u.reg_read(UC_X86_REG_EAX) & 65535

    def test_original_enemy_scan_rejects_usable_laser(self):
        self.assertEqual(self.select(fixed=False), 0)
        self.assertEqual(self.select(), 100)

    def test_other_factions_and_weapons_keep_their_selection(self):
        for faction in (0, 1, 2, 3):
            for weapon in (4, 5, 6, 7):
                for force in (0, 1):
                    if faction == 2 and weapon == 4 and force:
                        continue
                    with self.subTest(faction=faction, weapon=weapon, force=force):
                        args = dict(faction=faction, weapon=weapon, force=force)
                        self.assertEqual(self.select(fixed=False, **args), self.select(**args))

    def test_custom_weapon_scan_changes_only_enemy_laser_across_record_layouts(self):
        # Real selector/readiness execution with an authored direct-fire catalog.
        # The resource-backed investigation separately exercises all 21 menu
        # types. This protects class dispatch and the narrow faction correction.
        for ai_class in self.PROFILES:
            for faction in (1, 2):
                for weapon in self.OFFERED:
                    args = dict(ai_class=ai_class, faction=faction, weapon=weapon, clock=20000)
                    with self.subTest(**args):
                        before = self.select(fixed=False, **args)
                        after = self.select(**args)
                        if faction == 2 and weapon == 4:
                            self.assertEqual((before, after), (0, 100))
                        else:
                            self.assertEqual(before, after)

    def test_controller_rescans_empty_selection_at_half_second_boundary(self):
        # 0x25129c uses a cached selection before 500 ms, then asks the selector
        # to scan again. Preserve that controller schedule and ordinary cooldowns.
        for ai_class in self.PROFILES:
            for fixed in (False, True):
                with self.subTest(ai_class=ai_class, fixed=fixed):
                    u, ai, record = self.prepare(fixed=fixed, ai_class=ai_class)
                    _, _, _, count, selected, equipped, _ = self.PROFILES[ai_class]
                    u.mem_write(record + count, b'\x02')
                    u.mem_write(record + selected, b'\x01')
                    u.mem_write(record + equipped + 15,
                                struct.pack('<BBHHIIB', 7, 3, 300, 0, 0, 0, 0))
                    # Railgun is ammunition-fed, even though its ammo is empty.
                    u.mem_write(0x395110 + 7 * 36 + 10, struct.pack('<H', 300))
                    put(u, ai + 0xfe, 1000)
                    samples = []
                    for clock in (1000, 1499, 1500, 1501):
                        put(u, 0x446ae8, clock)
                        run(u, 0x25129c, eax=ai)
                        samples.append((u.reg_read(UC_X86_REG_EAX),
                                        u.mem_read(record + selected, 1)[0]))
                    expected = [(4, 1), (4, 1)]
                    expected += [(50, 0), (50, 0)] if fixed else [(4, 1), (4, 1)]
                    self.assertEqual(samples, expected)

    def test_thermal_disruptor_eligible_branch_initializes_acceptance(self):
        # The original allowed branch reaches [ESP+0x28] without defining it.
        # Seed that dead stack byte explicitly and retain the real timestamp and
        # target-class checks. The corrected jump reaches the existing flag=1.
        for ai_class in self.PROFILES:
            for fixed in (False, True):
                for seed in (0, 1, 255):
                    u, ai, _ = self.prepare(fixed=fixed, ai_class=ai_class, weapon=9)
                    u.mem_write(ai + 0xc9, b'\x02')
                    u.mem_write(0x3832f0 + 2 * 334 + 13, b'\x01')
                    u.mem_write(STACK - 20 - 48 + 0x28, bytes([seed]))
                    run(u, 0x250e58, eax=ai, edx=1)
                    with self.subTest(ai_class=ai_class, fixed=fixed, seed=seed):
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX) & 65535,
                                         100 if fixed or seed else 0)

    def test_thermal_disruptor_keeps_target_and_unsigned_time_restrictions(self):
        # Preserve the original unsigned (squad timestamp + 10000) >= clock
        # comparison, including its existing wrap behavior and exact boundary.
        clocks = ((0, 0), (1000, 11000), (1000, 11001),
                  (0xfffffff0, 0), (0xfffffff0, 9984),
                  (0xfffffff0, 9985), (0, 0xffffffff))
        for target_class in (1, 2, 3, 4):
            for timestamp, clock in clocks:
                for seed in (0, 255):
                    u, ai, _ = self.prepare(weapon=9, clock=clock)
                    u.mem_write(ai + 0xc9, b'\x02')
                    u.mem_write(0x3832f0 + 2 * 334 + 13, bytes([target_class]))
                    put(u, 0x3804f0 + 0xef, timestamp)
                    u.mem_write(STACK - 20 - 48 + 0x28, bytes([seed]))
                    run(u, 0x250e58, eax=ai, edx=1)
                    allowed = (target_class not in (3, 4) and
                               ((timestamp + 10000) & 0xffffffff) >= clock)
                    with self.subTest(target_class=target_class, timestamp=timestamp,
                                      clock=clock, seed=seed):
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX) & 65535,
                                         100 if allowed else 0)

    def test_unusable_weapons_remain_unavailable(self):
        for ai_class in self.PROFILES:
            for args in (dict(health=0), dict(charge=0), dict(deadline=1001),
                         dict(weapon=7, ammo=0)):
                with self.subTest(ai_class=ai_class, **args):
                    self.assertEqual(self.select(ai_class=ai_class, **args), 0)


class WeaponSuitabilityTests(unittest.TestCase):
    """Original selector execution with explicit catalog/clearance fixtures.

    These controls isolate the observed score loss and cached-policy bypass.
    Clearance outputs are modeled at 0x250ce0 for exact boundary tests; they
    do not claim to simulate blast damage or moving actors.
    """
    PROFILES = EnemyLaserSelectionTests.PROFILES
    prepare = EnemyLaserSelectionTests.prepare

    def loadout(self, weapons, *, selected=0, target_class=1, fixed=True):
        u, ai, record = self.prepare(faction=1, weapon=4)
        if fixed:
            for address, body in f.choice_bodies() + [(f.RANGE, dict(f.bodies())[f.RANGE])]:
                u.mem_write(address, body)
        u.mem_write(record + 0x81, bytes([len(weapons)]))
        u.mem_write(record + 0xce, bytes([selected]))
        for slot, (wid, damage, explosive) in enumerate(weapons):
            u.mem_write(record + 0x45 + 15 * slot,
                        struct.pack('<BBHHIIB', wid, 2, 300, 100, 0, 0, 0))
            cat = 0x395110 + 36 * wid
            u.mem_write(cat, bytes(36))
            u.mem_write(cat+4, bytes([explosive]))
            u.mem_write(cat+5, struct.pack('<H', damage))
            u.mem_write(cat+10, struct.pack('<H', 100))
            u.mem_write(cat+14, struct.pack('<H', 100))
            u.mem_write(cat+22, struct.pack('<H', 100))
        _, target_ai = actor(u, 20, slot=2, team=2, xyz=(10*65536, 0, 0))
        u.mem_write(target_ai+13, bytes([target_class]))
        u.mem_write(ai+0xc3, b'\x01')
        u.mem_write(ai+0xc9, b'\x02\x14')
        self.clearance(u, target=10*65536, shooter=2*65536)
        return u, ai, record

    def clearance(self, u, *, target, shooter):
        u.mem_write(0x250ce0, asm(0x250ce0,
                    f'mov dword ptr [ebx],{target};mov dword ptr [edx],{shooter};ret'))

    def select(self, u, ai, record, force):
        saved = dict(ebx=0x12345678, ecx=0x23456789, esi=0x3456789a,
                     edi=0x456789ab, ebp=0x56789abc)
        run(u, 0x250e58, eax=ai, edx=force, **saved)
        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK+4)
        for reg, value in saved.items():
            self.assertEqual(u.reg_read(globals()['UC_X86_REG_'+reg.upper()]), value)
        slot = u.mem_read(record+0xce, 1)[0]
        return u.reg_read(UC_X86_REG_EAX)&65535, u.mem_read(record+0x45+15*slot, 1)[0]

    def test_best_eligible_score_wins_independent_of_equipment_order(self):
        for weapons in (((5, 10, 0), (6, 30, 0)), ((6, 30, 0), (5, 10, 0))):
            u, ai, rec = self.loadout(weapons)
            self.assertEqual(self.select(u, ai, rec, 1), (100, 6))

    def test_equal_scores_keep_first_and_rejected_high_score_does_not_win(self):
        u, ai, rec = self.loadout(((5, 10, 0), (6, 10, 0)))
        self.assertEqual(self.select(u, ai, rec, 1), (100, 5))
        u, ai, rec = self.loadout(((4, 10, 0), (13, 250, 1), (6, 30, 0)), target_class=4)
        self.assertEqual(self.select(u, ai, rec, 1), (100, 6))

    def test_cached_explosives_and_close_range_weapon_recheck_drone_target(self):
        for wid in (3, 10, 13, 14, 21, 29, 30, 31, 32, 12):
            for force in (0, 1):
                with self.subTest(weapon=wid, force=force):
                    u, ai, rec = self.loadout(((4, 10, 0), (wid, 250, int(wid != 12))),
                                              selected=1, target_class=4)
                    self.assertEqual(self.select(u, ai, rec, force), (100, 4))

    def test_cached_explosive_rechecks_original_clearance_boundaries(self):
        for target, shooter, expected in ((6*65536, 65536, 4),
                (6*65536+1, 65536, 13), (7*65536, 65535, 4)):
            for force in (0, 1):
                u, ai, rec = self.loadout(((4, 10, 0), (13, 250, 1)), selected=1)
                self.clearance(u, target=target, shooter=shooter)
                self.assertEqual(self.select(u, ai, rec, force), (100, expected))

    def test_valid_cached_weapon_keeps_selection_until_normal_rescan(self):
        u, ai, rec = self.loadout(((4, 10, 0), (6, 250, 0)))
        put(u, ai+0xfe, 1000)
        seen = []
        u.hook_add(UC_HOOK_CODE, lambda c,a,n,d: seen.append(a),
                   begin=0x2510b5, end=0x2510b5)
        for clock, slot, scans in ((1000, 0, 0), (1499, 0, 0), (1500, 1, 2)):
            put(u, 0x446ae8, clock)
            run(u, 0x25129c, eax=ai)
            self.assertEqual(u.mem_read(rec+0xce, 1)[0], slot)
            self.assertEqual(len(seen), scans)

    def test_noncombat_cache_ignores_stale_target_metadata(self):
        u, ai, rec = self.loadout(((4, 10, 0), (13, 250, 1)), selected=1, target_class=4)
        u.mem_write(ai+0xc3, b'\0')
        self.assertEqual(self.select(u, ai, rec, 0), (100, 13))

    def test_unready_cache_does_not_rescan_and_no_eligible_returns_zero(self):
        u, ai, rec = self.loadout(((4, 10, 0), (13, 250, 1)), selected=1, target_class=4)
        put(u, rec+0x45+15+10, 1001)
        self.assertEqual(self.select(u, ai, rec, 0), (0, 13))
        u, ai, rec = self.loadout(((13, 250, 1),), target_class=4)
        self.assertEqual(self.select(u, ai, rec, 0), (0, 13))
        # The original API leaves the equipped slot unchanged when it returns0;
        # its caller decides how a failed selection affects movement/firing.

    def test_rejected_cache_cannot_escape_policy_through_range_fallback(self):
        u, ai, rec = self.loadout(((4, 10, 0), (13, 250, 1)), selected=1, target_class=4)
        u.mem_write(0x39511e+4*36, struct.pack('<H', 1))
        self.assertEqual(self.select(u, ai, rec, 0), (1, 4))

    def test_controller_admission_obeys_selection_failure_and_keeps_timer(self):
        for elapsed in (0, 499, 500):
            for target_class in (1, 4):
                for ready_beam in (False, True):
                    u, ai, rec = self.loadout(((4, 10, 0), (13, 250, 1)),
                                              selected=1, target_class=target_class)
                    put(u, ai+0xfe, 1000)
                    put(u, 0x446ae8, 1000+elapsed)
                    if not ready_beam:
                        put(u, rec+0x45+10, 5000)
                    before = bytes(u.mem_read(rec+0x45, 30))
                    stop = execute_until(u, f.CHOICE_ADMISSION, {0x251d97, 0x251edf},
                                         eax=ai, ebx=123, ecx=456, edx=789)
                    allowed = target_class == 1 or ready_beam
                    self.assertEqual(stop, 0x251d97 if allowed else 0x251edf)
                    self.assertEqual(get(u, ai+0xfe), 1500 if elapsed == 500 else 1000)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
                    for register, value in ((UC_X86_REG_EBX,123), (UC_X86_REG_ECX,456),
                                            (UC_X86_REG_EDX,789)):
                        self.assertEqual(u.reg_read(register), value)
                    self.assertEqual(bytes(u.mem_read(rec+0x45, 30)), before)



class AIFiringTests(unittest.TestCase):

    def test_history_free_generators_and_atomic_installation_contracts(self):
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(f.bodies()), 10)
            self.assertEqual(len(f.choice_bodies()), 18)
            self.assertTrue(f.selected_weapon_body())
            self.assertTrue(f.preflight_source())
        for choice in (False, True):
            sites = f.CHOICE_SITES if choice else f.SITES
            pieces = f.choice_bodies() if choice else f.bodies()
            for problem in ('none', 'hook', 'partial', 'provider', 'reservation', 'short'):
                with self.subTest(choice=choice, problem=problem):
                    ram = bytearray(0x2000000)
                    writes = []
                    for a, b in sites.items():
                        ram[a:a + len(b)] = b
                    provider = f.RANGE if choice else f.RESOLVE
                    body = dict(f.bodies())[f.RANGE] if choice else f.selected_weapon_body()
                    ram[provider:provider + len(body)] = body
                    original = bytes(ram)
                    if problem == 'hook':
                        ram[next(iter(sites))] ^= 1
                    if problem == 'partial':
                        a, b = pieces[0]
                        ram[a:a + len(b)] = b
                    if problem == 'provider':
                        ram[provider] ^= 1
                    if problem == 'reservation':
                        ram[(f.CHOICE_END if choice else f.END) - 1] = 1

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    read = lambda a, n: ram[a:a + n - int(problem == 'short')]
                    if problem != 'none':
                        with self.assertRaises(ValueError):
                            f.install(write, read, choice=choice)
                        self.assertFalse(writes)
                    else:
                        f.install(write, read, choice=choice)
                        self.assertEqual(writes, pieces)
                        writes.clear()
                        self.assertTrue(f.verify(read, choice=choice))
                        self.assertTrue(f.install(write, read, choice=choice)['already_installed'])
                        self.assertFalse(writes)
                        self.assertEqual(f.predecessor_view(ram, choice=choice), original)

    def test_selected_weapon_resolves_suits_vehicles_turrets_and_rejects_invalid_slots(self):
        u = machine()
        profiles = (
            (1, 60, 0x582, 0x3a5608, 0xce, 4, 0x45, 0x86),
            (2, 52, 296, 0x3a19e8, 0x36, 2, 0x17, 0x37), (4, 64, 121, 0x39c750, 0xe, 2, 0x33, 0x56)
        )
        for cls, limit, stride, base, selection, count, weapon, energy in profiles:
            for slot, index in ((0, 0), (limit - 1, count - 1), (limit, 0), (1, count)):
                actor(u, 10, cls, slot)
                record = base + slot * stride
                u.mem_write(record + selection, bytes([index]))
                run(u, f.RESOLVE, edx=10, ecx=0x1234, esi=0x5678, edi=0x9876)
                valid = slot < limit and index < count
                self.assertEqual(
                    u.reg_read(UC_X86_REG_EAX), record + weapon + index * 15 if valid else 0
                )
                if valid:
                    self.assertEqual(u.reg_read(UC_X86_REG_EBX), record + energy)
                self.assertEqual(
                    [u.reg_read(r) for r in (UC_X86_REG_ECX, UC_X86_REG_ESI, UC_X86_REG_EDI)],
                    [0x1234, 0x5678, 0x9876]
                )
        for cls in (0, 3, 5):
            actor(u, 10, cls)
            run(u, f.RESOLVE, edx=10)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0)
        for oid in (0, 1024, 0xffffffff):
            run(u, f.RESOLVE, edx=oid)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0)

    def test_quantized_3d_range_matches_independent_distance_calculation(self):
        u = machine()
        rng = random.Random(102)
        for radius in (0, 5, 12, 30, 60):
            for i in range(80):
                source = [rng.randrange(-0x2000000, 0x2000000) for _ in range(3)]
                dest = [
                    p + rng.randrange(-(radius + 1) * 131072, (radius + 1) * 131072) for p in source
                ]
                u.mem_write(POINT, struct.pack('<6i', *source, *dest))
                run(u, f.RANGE, eax=POINT, edx=POINT + 12, ecx=radius)
                self.assertEqual(
                    u.reg_read(UC_X86_REG_EAX),
                    int(sum(((a - b) >> 8)**2 for a, b in zip(source, dest)) > (radius * 256)**2)
                )

    def test_choice_checks_all_weapon_ids_and_axis_range_boundaries(self):
        u = machine()
        actor(u, 10)
        actor(u, 20, slot=2)
        u.mem_write(AI + 0xc3, b'\1')
        u.mem_write(AI + 0xca, b'\x14')
        u.mem_write(AI + 11, struct.pack('<H', 10))
        for weapon in range(1, 33):
            radius = weapon + 5
            u.mem_write(0x39511e + 36 * weapon, struct.pack('<H', radius))
            u.mem_write(WEAPON, bytes([weapon]))
            for axis in range(3):
                for sign in (-1, 1):
                    for offset in (-256, 0, 256):
                        xyz = [0, 0, 0]
                        xyz[axis] = sign * (radius * 65536 + offset)
                        u.mem_write(0x3c324f + 37 * 20, struct.pack('<3i', *xyz))
                        run(u, f.CHOICE_CHECK, ecx=AI, ebx=WEAPON)
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(offset > 0))

    def test_choice_leaves_noncombat_invalid_or_absent_targets_to_original_policy(self):
        for condition in (
            'noncombat', 'no_target', 'dead_target', 'no_owner', 'invalid_owner', 'dead_owner',
            'no_weapon', 'invalid_weapon'
        ):
            u = machine()
            actor(u, 10)
            actor(u, 20, slot=2, xyz=(100 * 65536, 0, 0))
            u.mem_write(AI + 0xc3, b'\1')
            u.mem_write(AI + 0xca, b'\x14')
            u.mem_write(AI + 11, struct.pack('<H', 10))
            u.mem_write(WEAPON, b'\x05')
            a, b = {
                'noncombat': (AI + 0xc3, b'\0'),
                'no_target': (AI + 0xca, b'\0'),
                'dead_target': (0x3c3240 + 37 * 20, b'\0'),
                'no_owner': (AI + 11, b'\0\0'),
                'invalid_owner': (AI + 11, struct.pack('<H', 300)),
                'dead_owner': (0x3c3240 + 37 * 10, b'\0'),
                'no_weapon': (WEAPON, b'\0'),
                'invalid_weapon': (WEAPON, b'\x21')
            }[condition]
            u.mem_write(a, b)
            run(u, f.CHOICE_CHECK, ecx=AI, ebx=WEAPON)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0, condition)

    def test_cached_and_scanned_choices_reject_short_weapons_but_allow_fallback_pass(self):
        u = machine()
        actor(u, 10)
        actor(u, 20, slot=2, xyz=(20 * 65536, 0, 0))
        u.mem_write(AI + 0xc3, b'\1')
        u.mem_write(AI + 0xca, b'\x14')
        u.mem_write(AI + 11, struct.pack('<H', 10))
        u.mem_write(WEAPON, b'\5')
        u.mem_write(0x39511e + 36 * 5, struct.pack('<H', 10))
        for entry, accepted, rejected in (
            (f.CHOICE_FAST, 0x2510bf, 0x250fed), (f.CHOICE_SCAN, 0x25103a, 0x251279)
        ):
            for fallback in (0, 1):
                u.mem_write(STACK + 0x30, bytes([fallback]))
                stop = execute_until(u, entry, {accepted, rejected}, ecx=AI, ebx=WEAPON, eax=777)
                self.assertEqual(stop, accepted if fallback else rejected)
                self.assertEqual(u.mem_read(STACK + 0x30, 1)[0], 1 if fallback else 2)

    def test_no_reachable_choice_retries_original_scan_once_and_preserves_approach_result(self):
        u = machine()
        for state, result in ((2, 0), (1, 0), (0, 0), (2, 45)):
            u.mem_write(STACK + 0x30, bytes([state, 7]))
            put(u, STACK + 0x1c, result)
            stop = execute_until(u, f.CHOICE_FINISH, {0x250ee8, 0x251295})
            if state == 2 and result == 0:
                self.assertEqual(stop, 0x250ee8)
                self.assertEqual(u.mem_read(STACK + 0x30, 1), b'\1')
                self.assertEqual(u.reg_read(UC_X86_REG_EBX) & 255, 7)
            else:
                self.assertEqual(stop, 0x251295)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), result)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 0x34)

    def test_final_preflight_preserves_cover_failure_and_adds_range_failure(self):
        u = machine()
        address = 0x1fc7200
        u.mem_write(address, asm(address, f.preflight_source()))
        actor(u, 10)
        actor(u, 20, slot=2)
        u.mem_write(AI + 11, struct.pack('<H', 10))
        u.mem_write(0x3a5608 + 0x582 + 0xce, b'\0')
        u.mem_write(0x3a5608 + 0x582 + 0x45, b'\5')
        u.mem_write(0x39511e + 5 * 36, struct.pack('<H', 10))
        for distance in (9, 11):
            for blocked in (0, 1):
                u.mem_write(0x3c324f + 37 * 20, struct.pack('<3i', distance * 65536, 0, 0))
                put(u, STACK + 8, 20)
                put(u, STACK + 28, OUT)
                u.mem_write(OUT, bytes([blocked]))
                run(u, address, end=0x252e48, edi=AI)
                self.assertEqual(u.mem_read(OUT, 1)[0], int(blocked or distance > 10))
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 24)

    def test_clearance_capsule_excludes_endpoints_and_uses_class_radius(self):
        u = machine()
        actor(u, 10, slot=1)
        a, row = actor(u, 30, slot=3)
        u.mem_write(POINT, struct.pack('<6i', 0, 0, 0, 10 * 65536, 0, 0))
        for cls, x, y, z, blocked in (
            (1, 5 * 65536, 13000, 0, 1), (1, 5 * 65536, 14000, 0, 0), (2, 5 * 65536, 27000, 0, 1),
            (2, 5 * 65536, 28000, 0, 0), (1, 5 * 65536, 0, 14000, 0), (1, -65536, 0, 0, 0),
            (1, 0, 0, 0, 0), (1, 10 * 65536, 0, 0, 0), (1, 11 * 65536, 0, 0, 0)
        ):
            u.mem_write(a + 1, bytes([cls]))
            u.mem_write(a + 15, struct.pack('<3i', x, y, z))
            run(u, f.CLEARANCE, eax=POINT, edx=POINT + 12, ecx=10, ebx=20)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), blocked)

    def test_clearance_filters_faction_liveness_shooter_target_and_preserves_simd(self):
        for mode in (
            'ally', 'opponent', 'inactive', 'target', 'shooter', 'scenery', 'no_ai', 'zero_segment',
            'player_flag'
        ):
            u = machine()
            actor(u, 10, slot=1)
            a, row = actor(u, 30, slot=3, xyz=(5 * 65536, 0, 0))
            u.mem_write(POINT, struct.pack('<6i', 0, 0, 0, 10 * 65536, 0, 0))
            if mode == 'opponent':
                u.mem_write(row + 5, b'\2')
            if mode in ('inactive', 'player_flag'):
                u.mem_write(row, b'\0')
            if mode == 'player_flag':
                u.mem_write(row + 10, b'\1')
            if mode == 'scenery':
                u.mem_write(a + 1, b'\0')
            if mode == 'no_ai':
                u.mem_write(a + 33, b'\0')
            if mode == 'zero_segment':
                u.mem_write(POINT + 12, bytes(12))
            values = [(i + 1) * 0x123456789abcdef for i in range(8)]
            for i, v in enumerate(values):
                u.reg_write(UC_X86_REG_XMM0 + i, v)
            u.reg_write(UC_X86_REG_MXCSR, 0x1fa0)
            run(
                u,
                f.CLEARANCE,
                eax=POINT,
                edx=POINT + 12,
                ecx=30 if mode == 'shooter' else 10,
                ebx=30 if mode == 'target' else 20
            )
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(mode in ('ally', 'player_flag')), mode)
            self.assertEqual([u.reg_read(UC_X86_REG_XMM0 + i) for i in range(8)], values)
            self.assertEqual(u.reg_read(UC_X86_REG_MXCSR), 0x1fa0)

    def test_final_launch_applies_range_to_ai_classes_but_bypasses_manual_and_dry_runs(self):
        u = machine()
        put(u, 0x441350, 1)
        u.mem_write(WEAPON, b'\5')
        u.mem_write(0x39511e + 5 * 36, struct.pack('<H', 10))
        u.mem_write(FRAME - 84, struct.pack('<3i', 11 * 65536, 0, 0))
        for cls, owner, real, blocked in (
            (1, 10, 1, 1), (2, 10, 1, 1), (3, 10, 1, 1), (4, 10, 1, 1), (1, 1, 1, 0), (1, 10, 0, 0),
            (0, 10, 1, 0), (1, 0, 1, 0), (1, 300, 1, 0)
        ):
            actor(u, 10, cls)
            reason = timing.TABLE + owner * timing.STRIDE + timing.LAUNCH_VETO
            put(u, reason, 0)
            u.mem_write(FRAME + 40, bytes([real]))
            stop = execute_until(
                u, f.LAUNCH, {0x28f1b2, 0x28f7f1}, ebp=FRAME, esi=owner, edi=WEAPON
            )
            self.assertEqual(stop, 0x28f7f1 if blocked else 0x28f1b2)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
            self.assertEqual(get(u, reason), blocked)

    def test_final_launch_denies_same_faction_body_only_for_pba_shooters(self):
        for cls, team, blocked in ((1, 1, 1), (1, 2, 0), (2, 1, 0), (4, 1, 0)):
            u = machine()
            actor(u, 10, cls, slot=1)
            actor(u, 30, slot=3, team=team, xyz=(3 * 65536, 0, 0))
            put(u, 0x441350, 1)
            u.mem_write(WEAPON, b'\5')
            u.mem_write(0x39511e + 5 * 36, struct.pack('<H', 10))
            u.mem_write(FRAME - 84, struct.pack('<3i', 6 * 65536, 0, 0))
            put(u, FRAME + 32, 20)
            u.mem_write(FRAME + 40, b'\1')
            stop = execute_until(u, f.LAUNCH, {0x28f1b2, 0x28f7f1}, ebp=FRAME, esi=10, edi=WEAPON)
            self.assertEqual(stop, 0x28f7f1 if blocked else 0x28f1b2)
            self.assertEqual(get(u, timing.TABLE + 10 * timing.STRIDE + timing.LAUNCH_VETO), blocked)


class LaunchFeedbackTests(unittest.TestCase):
    """Keep movement feedback specific to a veto during this firing attempt.

    The original firing wrapper is a boundary here. It supplies authored return
    statuses and register values; existing launch tests exercise the real reason
    producer. Copied-controller tests separately establish the movement effect.
    """

    def test_original_call_preimage(self):
        from original_inputs import original_ram
        if not any(original_ram[0x251f09:0x251f0e]):
            self.skipTest('Original executable was not supplied')
        self.assertEqual(bytes(original_ram[0x251f09:0x251f0e]), f.SITES[0x251f09])

    def scene(self):
        u = machine()
        _, ai = actor(u, 10)
        row = timing.TABLE + 10 * timing.STRIDE
        u.mem_write(STACK + 0xa8, b'\1')
        return u, ai, row + timing.LAUNCH_VETO

    def test_only_current_veto_with_failure_clears_permission(self):
        for status in range(7):
            for old in (0, 1, 0x12345678):
                for veto in (0, 1):
                    u, ai, reason = self.scene()
                    put(u, reason, old)
                    u.mem_write(0x252758, asm(0x252758, f'''
                        mov ecx,[{reason}]; mov [{OUT}],ecx;
                        mov dword ptr [{reason}],{veto};
                        mov eax,{0xabc000+status};
                        mov ebx,0x22222222; mov ecx,0x33333333;
                        mov edx,0x44444444; mov esi,0x55555555;
                        mov edi,0x66666666; mov ebp,0x77777777;
                        push 0x647; popfd; ret;
                    '''))
                    execute_until(u, 0x251f09, {0x251f0e}, eax=ai)
                    self.assertEqual(get(u, OUT), 0)
                    self.assertEqual(get(u, reason), old)
                    self.assertEqual(u.mem_read(STACK + 0xa8, 1)[0], int(not(status == 6 and veto)))
                    for reg, value in ((UC_X86_REG_EAX, 0xabc000+status),
                                       (UC_X86_REG_EBX, 0x22222222), (UC_X86_REG_ECX, 0x33333333),
                                       (UC_X86_REG_EDX, 0x44444444), (UC_X86_REG_ESI, 0x55555555),
                                       (UC_X86_REG_EDI, 0x66666666), (UC_X86_REG_EBP, 0x77777777)):
                        self.assertEqual(u.reg_read(reg), value)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
                    self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x647)

    def test_skipped_call_does_not_consume_stale_result_or_reason(self):
        u, _, reason = self.scene()
        put(u, reason, 1)
        u.mem_write(0x251f0e, asm(0x251f0e, 'mov bh,byte ptr [esp+0xa8]'))
        execute_until(u, 0x251f0e, {0x251f15}, eax=6)
        self.assertEqual(get(u, reason), 1)
        self.assertEqual(u.mem_read(STACK + 0xa8, 1), b'\1')

    def test_veto_outside_controller_does_not_affect_later_generic_failure(self):
        u, ai, reason = self.scene()
        put(u, 0x441350, 1)
        u.mem_write(WEAPON, b'\5')
        u.mem_write(0x39511e + 5*36, struct.pack('<H', 10))
        u.mem_write(FRAME - 84, struct.pack('<3i', 11*65536, 0, 0))
        u.mem_write(FRAME + 40, b'\1')
        execute_until(u, f.LAUNCH, {0x28f7f1}, ebp=FRAME, esi=10, edi=WEAPON)
        self.assertEqual(get(u, reason), 1)
        u.mem_write(0x252758, asm(0x252758, 'mov eax,6; ret;'))
        execute_until(u, 0x251f09, {0x251f0e}, eax=ai)
        self.assertEqual(get(u, reason), 1)
        self.assertEqual(u.mem_read(STACK + 0xa8, 1), b'\1')

    def test_nested_attempt_restores_outer_reason(self):
        for outer, inner in ((1, 0), (0, 1)):
            u, ai, reason = self.scene()
            put(u, reason, 0x12345678)
            put(u, OUT, 0)
            u.mem_write(0x252758, asm(0x252758, f'''
                inc dword ptr [{OUT}]; cmp dword ptr [{OUT}],1;
                jne inner;
                mov dword ptr [{reason}],{outer};
                mov eax,{ai}; call {f.LAUNCH_FEEDBACK};
                mov eax,6; ret;
            inner:
                mov ecx,[{reason}]; mov [{OUT+4}],ecx;
                mov dword ptr [{reason}],{inner};
                mov eax,6; ret;
            '''))
            execute_until(u, 0x251f09, {0x251f0e}, eax=ai)
            self.assertEqual(get(u, OUT), 2)
            self.assertEqual(get(u, OUT+4), 0)
            self.assertEqual(get(u, reason), 0x12345678)
            self.assertEqual(u.mem_read(STACK + 0xa8, 1)[0], 1-outer)

    def test_existing_row_reset_and_reallocation_clear_reason(self):
        for entry in (timing.RESET, timing.ALLOC):
            u, _, reason = self.scene()
            for address, body in timing.bodies():
                u.mem_write(address, body)
            put(u, reason, 1)
            # The original allocator is a boundary: return a reused object ID
            # and let the actual row-reset helper establish fresh ownership.
            if entry == timing.ALLOC:
                u.mem_write(timing.ALLOC+0x80, asm(timing.ALLOC+0x80, 'mov eax,10; ret;'))
                run(u, entry)
            else:
                execute_until(u, entry, {0x1dc0400}, eax=10)
            self.assertEqual(get(u, reason), 0)


class SceneryPreviewTests(unittest.TestCase):

    def scene(self, preview=f.ATTACK_PREVIEW):
        u = machine()
        for a, b in f.scenery_bodies(preview) + f.scenery_providers(preview):
            u.mem_write(a, b)
        actor(u, 10)
        actor(u, 20, slot=2, xyz=(6 * 65536, 0, 0))
        u.mem_write(AI + 11, struct.pack('<H', 10))
        u.mem_write(AI + 13, b'\1')
        suit = 0x3a5608 + 0x582
        u.mem_write(suit + 0xce, b'\0')
        u.mem_write(suit + 0x45, b'\5')
        u.mem_write(0x395113 + 36 * 5, b'\1')
        u.mem_write(0x39511e + 36 * 5, struct.pack('<H', 10))
        put(u, STACK + 8, 20)
        for offset, target in ((28, OUT), (32, OUT + 1), (36, OUT + 2)):
            put(u, STACK + offset, target)
        u.mem_write(OUT, b'\0\1\1')
        u.mem_write(0x44658c, bytes(range(20)))
        put(u, preview.active, 7)
        put(u, preview.failed, 9)
        u.mem_write(0x252c5c, b'\xc2\x0c\x00')
        return u

    def preview_stub(self, u, preview, flags=(0, 0, 0)):
        calls = []

        def query(uc, a, n, data):
            if a != 0x252c5c:
                return
            self.assertEqual(get(uc, f.SCENERY_ACTIVE), 1)
            sp = uc.reg_read(UC_X86_REG_ESP)
            buffer = uc.reg_read(UC_X86_REG_EBX)
            calls.append((uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)))
            self.assertEqual(uc.reg_read(UC_X86_REG_ECX), buffer + 12)
            for i, value in enumerate(flags):
                pointer = get(uc, sp + 4 + i * 4)
                self.assertEqual(pointer, buffer + 16 + i)
                uc.mem_write(pointer, bytes([value]))
            uc.mem_write(buffer, b'P' * 16)
            uc.mem_write(0x44658c, b'Q' * 20)
            put(uc, preview.active, 123)
            put(uc, preview.failed, 456)
            for r in (
                UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI,
                UC_X86_REG_EDI, UC_X86_REG_EBP
            ):
                uc.reg_write(r, 0x123456)
            uc.reg_write(UC_X86_REG_EFLAGS, 0x202)

        u.hook_add(UC_HOOK_CODE, query)
        return calls

    def test_scenery_authoring_binds_preview_without_history_or_private_modules(self):
        alternate = f.AttackPreview(0x1600000, 0x1601000, 0x1601004)
        with patch.dict('sys.modules', {'build_inputs': None}), patch(
            'build_paths.source_path', side_effect=AssertionError('source parsing')
        ):
            self.assertEqual(len(f.scenery_bodies()), 6)
            self.assertNotEqual(f.scenery_bodies(), f.scenery_bodies(alternate))
            self.assertTrue(f.scenery_providers(alternate))
        for preview in (
            f.AttackPreview(active=0), f.AttackPreview(failed=f.ATTACK_PREVIEW.active),
            f.AttackPreview(preflight=f.SCENERY_CODE),
            f.AttackPreview(active=f.ATTACK_PREVIEW.preflight), f.AttackPreview(active=0x150001),
            f.AttackPreview(preflight='bad')
        ):
            with self.assertRaises(ValueError):
                f.scenery_bodies(preview)

    def test_scenery_installation_checks_dependencies_and_idle_state_before_writing(self):
        for preview in (f.ATTACK_PREVIEW, f.AttackPreview(0x1600000, 0x1601000, 0x1601004)):
            for problem in (
                'none', 'hook', 'partial', 'resolver', 'range', 'preflight', 'reservation',
                'active', 'short'
            ):
                with self.subTest(preview=preview, problem=problem):
                    ram = bytearray(0x2000000)
                    writes = []
                    for a, b in f.scenery_providers(preview) + list(
                        f.scenery_sites(preview).items()
                    ):
                        ram[a:a + len(b)] = b
                    original = bytes(ram)
                    changed = {
                        'hook': 0x252e42,
                        'resolver': f.RESOLVE,
                        'range': f.RANGE,
                        'preflight': preview.preflight,
                        'reservation': f.SCENERY_END - 1,
                        'active': f.SCENERY_ACTIVE
                    }
                    if problem in changed:
                        ram[changed[problem]] ^= 1
                    if problem == 'partial':
                        a, b = f.scenery_bodies(preview)[0]
                        ram[a:a + len(b)] = b

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    read = lambda a, n: ram[a:a + n - int(problem == 'short')]
                    if problem != 'none':
                        with self.assertRaises(ValueError):
                            f.scenery_install(write, read, preview)
                        self.assertFalse(writes)
                    else:
                        f.scenery_install(write, read, preview)
                        self.assertEqual(writes, f.scenery_bodies(preview))
                        writes.clear()
                        self.assertTrue(f.scenery_verify(read, preview))
                        self.assertTrue(
                            f.scenery_install(write, read, preview)['already_installed']
                        )
                        self.assertFalse(writes)
                        self.assertEqual(f.scenery_predecessor_view(ram, preview), original)
                        ram[f.SCENERY_ACTIVE] = 1
                        with self.assertRaises(ValueError):
                            f.scenery_verify(read, preview)
                        with self.assertRaises(ValueError):
                            f.scenery_install(write, read, preview)
                        self.assertFalse(writes)

    def test_retry_changes_only_scenery_permission_and_restores_all_borrowed_state(self):
        regs = {
            'eax': 0x111,
            'ebx': 0x222,
            'ecx': 0x333,
            'edx': 0x444,
            'esi': 0x555,
            'edi': AI,
            'ebp': 0x777
        }
        for preview in (f.ATTACK_PREVIEW, f.AttackPreview(0x1600000, 0x1601000, 0x1601004)):
            for failed in (0, 1):
                for blocked in (0, 1):
                    for scenery in (0, 1):
                        u = self.scene(preview)
                        calls = self.preview_stub(u, preview, (failed, blocked, scenery))
                        run(u, f.SCENERY_PREFLIGHT, end=preview.preflight, **regs)
                        self.assertEqual(calls, [(AI, 20)])
                        self.assertEqual(
                            bytes(u.mem_read(OUT, 3)), bytes([0, 1,
                                                              int(not (failed or blocked))])
                        )
                        self.assertEqual(bytes(u.mem_read(0x44658c, 20)), bytes(range(20)))
                        self.assertEqual(get(u, preview.active), 7)
                        self.assertEqual(get(u, preview.failed), 9)
                        self.assertEqual(get(u, f.SCENERY_ACTIVE), 0)
                        self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK)
                        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
                        for name, value in regs.items():
                            self.assertEqual(
                                u.reg_read(globals()['UC_X86_REG_' + name.upper()]), value
                            )

    def test_retry_scope_excludes_nested_clear_nonpba_gravity_and_invalid_weapons(self):
        for condition in (
            'nested', 'clear', 'no_scenery', 'nonpba', 'gravity', 'invalid_owner', 'no_weapon',
            'invalid_weapon'
        ):
            u = self.scene()
            preview = f.ATTACK_PREVIEW
            suit = 0x3a5608 + 0x582
            a, b = {
                'nested': (f.SCENERY_ACTIVE, b'\1'),
                'clear': (OUT + 1, b'\0'),
                'no_scenery': (OUT + 2, b'\0'),
                'nonpba': (AI + 13, b'\2'),
                'gravity': (0x395113 + 36 * 5, b'\0'),
                'invalid_owner': (AI + 11, struct.pack('<H', 1024)),
                'no_weapon': (suit + 0x45, b'\0'),
                'invalid_weapon': (suit + 0x45, b'\x21')
            }[condition]
            u.mem_write(a, b)
            before = bytes(u.mem_read(OUT, 3))
            calls = self.preview_stub(u, preview, (1, 1, 1))
            run(u, f.SCENERY_PREFLIGHT, end=preview.preflight, edi=AI)
            self.assertFalse(calls, condition)
            self.assertEqual(bytes(u.mem_read(OUT, 3)), before)
            self.assertEqual(bytes(u.mem_read(0x44658c, 20)), bytes(range(20)))
            self.assertEqual(get(u, preview.active), 7)
            self.assertEqual(get(u, preview.failed), 9)
            self.assertEqual(get(u, f.SCENERY_ACTIVE), int(condition == 'nested'))

    def test_dynamic_and_static_queries_skip_only_class_zero_during_preview(self):
        for entry, site, table, stride, popbytes in (
            (f.SCENERY_DYNAMIC, 0x2db1a4, 0x3c3241, 37, 20),
            (f.SCENERY_STATIC, 0x2db20c, 0x3cc8f4, 29, 24)
        ):
            for active in (0, 1):
                for cls in (0, 1, 2, 3, 4, 255):
                    u = self.scene()
                    put(u, f.SCENERY_ACTIVE, active)
                    u.mem_write(table + stride * 10, bytes([cls]))
                    put(u, STACK, STOP)
                    skipped = active and cls == 0
                    stop = execute_until(
                        u, entry, {STOP, site + 5}, eax=0xabcd000a, edx=0x123456, ecx=0x98765
                    )
                    self.assertEqual(stop, STOP if skipped else site + 5)
                    self.assertEqual(
                        u.reg_read(UC_X86_REG_ESP), STACK + 4 + popbytes if skipped else STACK - 12
                    )
                    self.assertEqual(u.reg_read(UC_X86_REG_ECX), 0x98765)
                    if skipped:
                        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0)
                    else:
                        self.assertEqual(u.reg_read(UC_X86_REG_ESI), 0x123456)
                        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_preview_chain_retains_blocked_and_range_results_for_both_factions(self):
        for faction in (1, 2):
            for distance in (6, 11):
                for failure in (0, 1):
                    u = self.scene()
                    u.mem_write(AI + 5, bytes([faction]))
                    u.mem_write(0x3c324f + 37 * 20, struct.pack('<3i', distance * 65536, 0, 0))
                    calls = self.preview_stub(u, f.ATTACK_PREVIEW, (failure, failure, 0))
                    run(u, f.SCENERY_PREFLIGHT, end=0x252e48, edi=AI)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(
                        bytes(u.mem_read(OUT, 3)), bytes([int(distance > 10), 1,
                                                          int(not failure)])
                    )
                    self.assertEqual(get(u, f.SCENERY_ACTIVE), 0)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 24)


if __name__ == '__main__':
    unittest.main()
