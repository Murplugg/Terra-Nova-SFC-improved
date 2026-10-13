"""Combined ray-contact installation and all-or-nothing provider admission."""
import unittest
from features import projectiles as p
from patch_support import asm

CANNON = (0x1fc5430, ((0x1fc5000, b'cannon'), ))
MESHES = {
    'vehicle': (0x1ee0400, ((0x1ee0000, b'vehicle'), )),
    'pba': (0x1ed0400, ((0x1ed0000, b'pba'), )),
    'mobile': (0x1ec0400, ((0x1ec0000, b'mobile'), )),
}


def image(providers):
    ram = bytearray(0x2000000)
    writes = []

    def write(address, data):
        writes.append((address, data))
        ram[address:address + len(data)] = data

    for address, data in providers.items():
        ram[address:address + len(data)] = data
    return ram, lambda a, n: ram[a:a + n], write, writes


def static_image():
    providers = dict(p.fuel_bodies())
    providers.update(p.static_contact_providers())
    return image(providers)


class CollisionInstallTests(unittest.TestCase):

    def test_fuel_checks_last_hook_and_reserved_gap_before_writes(self):
        for corrupt in ('hook', 'gap', None):
            with self.subTest(corrupt=corrupt):
                ram, read, write, writes = image({s: asm(s, 'call 0x2973e8') for s in p.FUEL_SITES})
                if corrupt == 'hook':
                    ram[p.FUEL_SITES[-1]] ^= 1
                elif corrupt == 'gap':
                    ram[p.FUEL_SHAPE - 1] = 1
                if corrupt:
                    with self.assertRaises(ValueError):
                        p.fuel_install(write, read)
                    self.assertFalse(writes)
                else:
                    p.fuel_install(write, read)
                    self.assertTrue(p.fuel_verify(read))
                    writes.clear()
                    p.fuel_install(write, read)
                    self.assertFalse(writes)

    def test_static_final_image_matches_separate_transitions_and_hooks_emit_once(self):
        ram, read, write, writes = static_image()
        expected = bytearray(ram)
        for address, data in p.static_bodies() + p.cannon_bodies(*CANNON):
            expected[address:address + len(data)] = data
        args = dict(mesh_entry=CANNON[0], mesh_regions=CANNON[1])
        p.install_static_contacts(write, read, **args)
        self.assertEqual(ram, expected)
        self.assertTrue(p.verify_static_contacts(read, **args))
        for site in p.static_contact_providers():
            self.assertEqual(sum(a == site for a, _ in writes), 1)
        self.assertEqual(len(writes), len(p.static_bodies()) + len(p.cannon_bodies(*CANNON)) - 2)
        writes.clear()
        p.install_static_contacts(write, read, **args)
        self.assertFalse(writes)

    def test_static_helper_last_hook_and_compiled_storage_conflicts_reject_before_writes(self):
        for address in (p.FUEL_CODE, p.CANNON_SCAN_SITE, CANNON[1][-1][0]):
            with self.subTest(address=hex(address)):
                ram, read, write, writes = static_image()
                ram[address] ^= 1
                before = bytes(ram)
                with self.assertRaises(ValueError):
                    p.install_static_contacts(
                        write, read, mesh_entry=CANNON[0], mesh_regions=CANNON[1]
                    )
                self.assertFalse(writes)
                self.assertEqual(ram, before)

    def test_contacts_compose_once_and_install_idempotently(self):
        ram, read, write, writes = image(p.mobile_contact_providers())
        expected = bytearray(ram)
        assembled = (
            p.vehicle_bodies(*MESHES['vehicle']) + p.pba_bodies(*MESHES['pba']) +
            p.mobile_bodies(*MESHES['mobile']) + p.cylinder_bodies() + p.vertical_bodies()
        )
        for address, data in assembled:
            expected[address:address + len(data)] = data
        p.install_mobile_contacts(write, read, **MESHES)
        self.assertEqual(ram, expected)
        self.assertTrue(p.verify_mobile_contacts(read, **MESHES))
        self.assertEqual(sum(a == p.VEHICLE_POST for a, _ in writes), 1)
        self.assertEqual(len(writes), len(assembled) - 2)
        writes.clear()
        p.install_mobile_contacts(write, read, **MESHES)
        self.assertFalse(writes)

    def test_mobile_late_compiled_region_and_sweep_conflicts_reject_before_writes(self):
        for address in (MESHES['mobile'][1][-1][0], p.CODE + 10, p.VEHICLE_SITE,
                        p.CYLINDER_SITE, p.CYLINDER_CODE, p.VERTICAL_SITE, p.VERTICAL_CODE):
            with self.subTest(address=hex(address)):
                ram, read, write, writes = image(p.mobile_contact_providers())
                ram[address] ^= 1
                before = bytes(ram)
                with self.assertRaises(ValueError):
                    p.install_mobile_contacts(write, read, **MESHES)
                self.assertFalse(writes)
                self.assertEqual(ram, before)

    def test_overlapping_compiled_regions_and_short_reads_are_rejected(self):
        _, read, write, writes = image(p.mobile_contact_providers())
        bad = dict(MESHES, mobile=(0x1ec0400, ((p.VEHICLE_CODE, b'overlap'), )))
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            p.install_mobile_contacts(write, read, **bad)
        self.assertFalse(writes)
        with self.assertRaises(ValueError):
            p.install_mobile_contacts(write, lambda a, n: read(a, n - 1), **MESHES)
        self.assertFalse(writes)


if __name__ == '__main__':
    unittest.main()
