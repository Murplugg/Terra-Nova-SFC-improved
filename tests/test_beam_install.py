"""Final beam/railgun composition and input/list admission contracts."""
import unittest
from features import effect_timing as effects, ai_cadence as cadence
from features import terrain_distance as terrain, input_views, projectiles
from patch_support import asm


def image(providers):
    ram = bytearray(0x2000000)
    writes = []
    for address, data in providers.items():
        ram[address:address + len(data)] = data

    def write(address, data):
        writes.append((address, data))
        ram[address:address + len(data)] = data

    return ram, lambda a, n: ram[a:a + n], write, writes


class BeamInstallTests(unittest.TestCase):

    def test_final_beam_image_matches_all_prior_transitions_with_one_write_per_hook(self):
        ram, read, write, writes = image(effects.beam_providers())
        expected = bytearray(ram)
        previous = (
            effects.beam_visual_bodies() + effects.beam_pixel_bodies() +
            effects.beam_density_bodies() + effects.beam_spread_bodies() +
            effects.beam_impact_bodies()
        )
        for address, data in previous:
            expected[address:address + len(data)] = data
        effects.beam_install(write, read)
        self.assertEqual(ram, expected)
        self.assertTrue(effects.beam_verify(read))
        for address in effects.beam_providers():
            self.assertEqual(sum(a == address for a, _ in writes), 1)
        self.assertLess(len(writes), len(previous))
        writes.clear()
        effects.beam_install(write, read)
        self.assertFalse(writes)
        ram[effects.BEAM_STATE] = 3
        self.assertTrue(effects.beam_verify(read))  # Live expiry counters are not code.

    def test_late_beam_hook_gap_and_state_conflicts_reject_before_write(self):
        for address in (
            effects.BEAM_DENSITY_CALLS[-1], effects.BEAM_SPREAD_CODE + 0x3ff, effects.BEAM_END - 1
        ):
            with self.subTest(address=hex(address)):
                ram, read, write, writes = image(effects.beam_providers())
                ram[address] ^= 1
                before = bytes(ram)
                with self.assertRaises(ValueError):
                    effects.beam_install(write, read)
                self.assertEqual(ram, before)
                self.assertFalse(writes)

    def test_railgun_final_gate_preserves_both_helpers_and_rejects_partial_install(self):
        ram, read, write, writes = image({cadence.RAILGUN_SITE: cadence.RAILGUN_ORIGINAL})
        expected = bytearray(ram)
        for address, data in cadence.railgun_bodies() + cadence.ally_railgun_bodies():
            expected[address:address + len(data)] = data
        cadence.railgun_install(write, read)
        self.assertEqual(ram, expected)
        self.assertEqual(sum(a == cadence.RAILGUN_SITE for a, _ in writes), 1)
        self.assertTrue(cadence.railgun_verify(read))
        writes.clear()
        cadence.railgun_install(write, read)
        self.assertFalse(writes)
        ram[cadence.RAILGUN_CODE] ^= 1
        with self.assertRaises(ValueError):
            cadence.railgun_install(write, read)
        self.assertFalse(writes)

    def test_renderer_lists_require_heap_helpers_and_complete_hook_admission(self):
        providers = {**dict(terrain.heap_bodies()), **terrain.LIST_ORIGINAL}
        for corrupt in (terrain.HEAP_FREE, list(terrain.LIST_ORIGINAL)[-1], None):
            with self.subTest(corrupt=corrupt):
                ram, read, write, writes = image(providers)
                if corrupt is not None:
                    ram[corrupt] ^= 1
                    with self.assertRaises(ValueError):
                        terrain.list_install(write, read)
                    self.assertFalse(writes)
                else:
                    terrain.list_install(write, read)
                    self.assertTrue(terrain.list_verify(read))

    def test_reticle_and_keyboard_validate_original_input_and_installed_output(self):
        for install, verify, providers, corrupt in (
            (
                projectiles.reticle_install, projectiles.reticle_verify, {
                    projectiles.RETICLE_SITE: asm(projectiles.RETICLE_SITE, 'call 0x2a28d0')
                }, projectiles.RETICLE_CODE + 0x3ff
            ),
            (
                input_views.keyboard_install, input_views.keyboard_verify, {
                    input_views.KEYBOARD_SITE: input_views.KEYBOARD_ORIGINAL
                }, input_views.KEYBOARD_SITE
            ),
        ):
            with self.subTest(install=install.__name__):
                ram, read, write, writes = image(providers)
                before = ram[corrupt]
                ram[corrupt] ^= 1
                with self.assertRaises(ValueError):
                    install(write, read)
                self.assertFalse(writes)
                ram[corrupt] = before
                install(write, read)
                self.assertTrue(verify(read))

    def test_scenery_checks_full_distance_provider_and_preserves_neighbors(self):
        providers = dict(terrain.bodies())
        providers.update(dict(terrain.mesh_bodies()))
        providers[terrain.SCENERY_SCENERY_SITE] = terrain.SCENERY_SCENERY_OLD
        ram, read, write, writes = image(providers)
        ram[terrain.ENTRY + 20] ^= 1
        with self.assertRaises(ValueError):
            terrain.scenery_install(write, read)
        self.assertFalse(writes)
        ram[terrain.ENTRY + 20] ^= 1
        tail = bytes(ram[terrain.ENTRY + 5:terrain.ENTRY + len(providers[terrain.ENTRY])])
        terrain.scenery_install(write, read)
        self.assertTrue(terrain.scenery_verify(read))
        self.assertEqual(ram[terrain.ENTRY + 5:terrain.ENTRY + len(providers[terrain.ENTRY])], tail)


if __name__ == '__main__':
    unittest.main()
