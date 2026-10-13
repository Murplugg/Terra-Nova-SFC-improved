"""Cold terrain installation: final hooks and atomic provider admission."""
import struct
import unittest
from features import terrain_distance as d
from patch_support import asm


def fixture(kind):
    ram = bytearray(0x2000000)

    def put(a, b):
        ram[a:a + len(b)] = b

    if kind == 'foundation':
        pieces, providers = d.foundation_pieces()
        install = d.install_foundation
    elif kind == 'storage':
        for a, b in d.bodies() + [(d.DETAIL_ENTRY, d.detail_body())]:
            put(a, b)
        put(d.CONFIG, struct.pack('<I', 1))
        pieces, providers, install = d.storage_pieces(), d.storage_providers(), d.install_storage
    elif kind == 'profiles':
        for a, b in d.preset_bodies() + d.scenery_bodies() + d.heap_bodies():
            put(a, b)
        pieces, providers, install = d.profile_pieces(), d.profile_providers(), d.install_profiles
    else:
        for a, b in d.heap_bodies():
            put(a, b)
        pieces, providers, install = d.scenery_clip_bodies(
        ), d.CLIP_SITES, d.install_scenery_clipping
    for a, b in providers.items():
        put(a, b)
    return ram, put, lambda a, n: ram[a:a + n], pieces, providers, install


class TerrainInstallTests(unittest.TestCase):

    def test_complete_transition_and_each_final_hook_written_once(self):
        for kind in ('foundation', 'storage', 'profiles', 'clipping'):
            with self.subTest(kind=kind):
                ram, put, read, pieces, providers, install = fixture(kind)
                expected = bytearray(ram)
                writes = []
                for a, b in pieces:
                    expected[a:a + len(b)] = b

                def write(a, b):
                    writes.append((a, b))
                    put(a, b)

                result = install(write, read)
                self.assertEqual(ram, expected)
                self.assertEqual(result['ranges'], [(a, a + len(b)) for a, b in pieces])
                for a in providers:
                    self.assertEqual(sum(x == a for x, b in writes), 1)
                if kind == 'clipping':
                    self.assertTrue(d.verify_scenery_clipping(read))

    def test_last_hook_conflict_rejects_entire_group_before_write(self):
        for kind in ('foundation', 'storage', 'profiles', 'clipping'):
            with self.subTest(kind=kind):
                ram, _, read, _, providers, install = fixture(kind)
                ram[list(providers)[-1]] ^= 1
                before = bytes(ram)
                writes = []
                with self.assertRaises(ValueError):
                    install(lambda a, b: writes.append((a, b)), read)
                self.assertEqual(writes, [])
                self.assertEqual(ram, before)

    def test_corrupt_required_helper_rejects_before_allocation_or_hooks(self):
        for kind, address in (
            ('storage', d.RAYS), ('profiles', d.SCENERY_GATHER), ('clipping', d.HEAP_FREE)
        ):
            with self.subTest(kind=kind):
                ram, _, read, _, _, install = fixture(kind)
                ram[address] ^= 1
                writes = []
                with self.assertRaises(ValueError):
                    install(lambda a, b: writes.append((a, b)), read)
                self.assertEqual(writes, [])

    def test_late_profile_reservation_conflict_rejects_before_write(self):
        ram, _, read, _, _, install = fixture('profiles')
        ram[d.RANGE_END - 1] = 1
        writes = []
        with self.assertRaisesRegex(ValueError, 'reservation'):
            install(lambda a, b: writes.append((a, b)), read)
        self.assertEqual(writes, [])

    def test_combined_profiles_equal_previous_transitions_without_intermediate_hooks(self):
        ram, _, _, pieces, _, _ = fixture('profiles')
        previous = bytearray(ram)
        combined = bytearray(ram)
        for a, b in d.zoom_bodies() + d.quality_bodies() + d.handoff_bodies(
        ) + d.scenery_range_bodies():
            previous[a:a + len(b)] = b
        for a, b in pieces:
            combined[a:a + len(b)] = b
        self.assertEqual(previous, combined)
        self.assertEqual(len(pieces), 8)
        self.assertEqual(dict(pieces)[d.ZOOM_SITE], asm(d.ZOOM_SITE, f'jmp {d.ZOOM_CODE}'))

    def test_combined_storage_preserves_snapshot_helpers_and_final_preference(self):
        ram, _, _, pieces, _, _ = fixture('storage')
        previous = bytearray(ram)
        combined = bytearray(ram)
        for a, b in d.mesh_bodies() + d.heap_bodies() + d.preset_bodies() + [
            (d.MESH_CONFIG, struct.pack('<I', 3))
        ]:
            previous[a:a + len(b)] = b
        for a, b in pieces:
            combined[a:a + len(b)] = b
        self.assertEqual(previous, combined)
        self.assertEqual(dict(pieces)[d.MESH_ENTRY], dict(d.mesh_bodies())[d.MESH_ENTRY])


if __name__ == '__main__':
    unittest.main()
