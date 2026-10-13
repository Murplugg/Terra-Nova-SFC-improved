"""Logical HUD admission and expanded effect-list lifecycle contracts."""
import struct, unittest
from unittest.mock import patch
from features import hud as h, effect_timing as e, hud_install as hi, maps, cameras, input_views
from patch_support import asm


def pool_fixture(live=False):
    ram = bytearray(0x2000000)
    writes = []

    def read(a, n):
        return bytes(ram[a:a + n])

    def write(a, b):
        writes.append((a, b))
        ram[a:a + len(b)] = b

    refs = [(e.POOL_DESCRIPTOR + 4, e.POOL_OLD), (0x300000, e.POOL_OLD + 44)]
    struct.pack_into('<HHI', ram, e.POOL_DESCRIPTOR, e.POOL_OLD_COUNT, e.POOL_STRIDE, e.POOL_OLD)
    for a, v in refs:
        struct.pack_into('<I', ram, a, v)
    if live:
        struct.pack_into('<HH', ram, e.POOL_OLD, 1, 2)
        for i in range(2, 128):
            struct.pack_into('<H', ram, e.POOL_OLD + i * 44 + 2, i + 1 if i < 127 else 0)
        ram[e.POOL_OLD + 44 + 8:e.POOL_OLD + 44 + 12] = b'live'
    return ram, read, write, writes, refs


class HudBindingTests(unittest.TestCase):

    def test_logical_helpers_validate_late_hooks_before_writing_and_verify(self):
        for label in ('damage', 'nav', 'menu'):
            for corrupt in (False, True):
                with self.subTest(label=label, corrupt=corrupt):
                    ram = bytearray(0x2000000)
                    writes = []
                    edits = getattr(h, label + '_hooks')(asm)
                    for a, b, old in edits:
                        ram[a:a + len(old)] = old
                    if corrupt:
                        ram[edits[-1][0]] ^= 1

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    read = lambda a, n: ram[a:a + n]
                    if corrupt:
                        with self.assertRaises(ValueError):
                            getattr(h, label + '_install')(write, read)
                        self.assertFalse(writes)
                    else:
                        getattr(h, label + '_install')(write, read)
                        self.assertTrue(getattr(h, label + '_verify')(read))
                        writes.clear()
                        getattr(h, label + '_install')(write, read)
                        self.assertFalse(writes)

    def test_rain_rejects_partial_install_then_preserves_exact_reinstall(self):
        ram = bytearray(0x2000000)
        ram[e.RAIN_SITE:e.RAIN_SITE + 5] = e.RAIN_PREFIX
        writes = []
        read = lambda a, n: ram[a:a + n]

        def write(a, b):
            writes.append((a, b))
            ram[a:a + len(b)] = b

        ram[e.RAIN_ENTRY] = 1
        with self.assertRaises(ValueError):
            e.rain_install(write, read)
        self.assertFalse(writes)
        ram[e.RAIN_ENTRY] = 0
        e.rain_install(write, read)
        self.assertTrue(e.rain_verify(read))
        writes.clear()
        e.rain_install(write, read)
        self.assertFalse(writes)

    def test_pool_cold_initialization_and_live_active_id_preservation(self):
        for live in (False, True):
            with self.subTest(live=live):
                ram, read, write, writes, refs = pool_fixture(live)
                original_record = read(e.POOL_OLD + 44, 44)
                with patch.object(e, 'pool_references', return_value=refs) as reference:
                    result = e.pool_install(write, read, b'original', cold=not live)
                    self.assertEqual(result['pool'], dict(active=int(live), free=255 - int(live)))
                    active, free = e.pool_lists(read(e.POOL_NEW, 256 * 44), 256)
                    self.assertEqual(active, [1] if live else [])
                    self.assertEqual(free, list(range(2 if live else 1, 256)))
                    if live:
                        self.assertEqual(read(e.POOL_NEW + 44, 44), original_record)
                    self.assertTrue(e.pool_verify(read, b'original'))
                    writes.clear()
                    self.assertTrue(e.pool_install(write, read, b'original')['already_expanded'])
                    self.assertFalse(writes)
                    reference.assert_called_with(b'original')

    def test_pool_rejects_bad_list_last_operand_and_occupied_storage_before_write(self):
        for fault in ('cycle', 'operand', 'arena', 'cold-live'):
            with self.subTest(fault=fault):
                ram, read, write, writes, refs = pool_fixture(True)
                if fault == 'cycle':
                    struct.pack_into('<H', ram, e.POOL_OLD + 2 * 44 + 2, 2)
                elif fault == 'operand':
                    ram[refs[-1][0]] ^= 1
                elif fault == 'arena':
                    ram[e.POOL_END - 1] = 1
                with patch.object(e, 'pool_references', return_value=refs):
                    with self.assertRaises(AssertionError):
                        e.pool_install(write, read, b'original', cold=fault == 'cold-live')
                self.assertFalse(writes)

    def test_pool_postinstall_guard_corruption_is_rejected(self):
        ram, read, write, writes, refs = pool_fixture()
        with patch.object(e, 'pool_references', return_value=refs):
            e.pool_install(write, read, b'original', cold=True)
            ram[e.POOL_END - 1] ^= 1
            with self.assertRaises(AssertionError):
                e.pool_verify(read, b'original')

    def test_visual_and_visibility_verification_preserves_image_and_checks_other_hud_bytes(self):
        ram = bytearray(0x2000000)
        for a, b in hi.providers().items():
            ram[a:a + len(b)] = b

        def write(a, b):
            ram[a:a + len(b)] = b

        read = lambda a, n: ram[a:a + n]
        original = lambda a, n: b''
        # The original terrain clone has its own hash/admission tests. Supply a
        # minimal clone here so this test isolates the full HUD provider chain.
        with patch.object(maps, 'terrain_code', return_value=b'\xc3'):
            hi.install_logical(write, read, original)
            self.assertTrue(hi.verify_logical(read, original))
            write(0x2a81a2, asm(0x2a81a2, 'cmp ebp,0x10000'))
            hi.install_visual(write, read)
            self.assertTrue(hi.verify_visual(ram, original))
            for site in cameras.VISIBILITY_SITES:
                if site == 0x9d8000:
                    write(site, cameras.visibility_prefix(site))
            cameras.visibility_install(write, read)
            before = bytes(ram)
            self.assertTrue(hi.verify_visibility(ram, original))
            self.assertEqual(ram, before)
            ram[h.COVER + 20] ^= 1
            with self.assertRaises(ValueError):
                hi.verify_visibility(ram, original)


if __name__ == '__main__':
    unittest.main()
