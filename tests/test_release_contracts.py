"""Snapshot compatibility decisions must happen before payload reads/writes."""
import copy, hashlib, unittest
from types import SimpleNamespace
from tnova import state_core as c


class Contracts(unittest.TestCase):

    def test_runtime_paths_keep_disk_image_fixed(self):
        install = c.Installation.__new__(c.Installation)
        install.template = b'fixed portable image'
        install.fresh = b'image with current in-memory paths'
        install.meta = {'runtime_paths': 'executable-directory-v1'}
        self.assertEqual(install.startup_image, install.template)
        install.meta = {}
        self.assertEqual(install.startup_image, install.fresh)
        install.meta = {'runtime_paths': 'unknown'}
        with self.assertRaisesRegex(ValueError, 'Unsupported runtime path policy'):
            _ = install.startup_image

    def install(self, revision):
        return SimpleNamespace(revision=revision, profile=c.CONTRACTS[str(revision)])

    def meta(self, revision):
        p = c.CONTRACTS[str(revision)]
        return dict(
            format='tn-portable-state-126',
            revision=revision,
            template=p['template'],
            contract=p['contract'],
            bridge=c.BRIDGE
        )

    def test_matching_builds(self):
        for revision in tuple(map(int, c.CONTRACTS)):
            c.validate_build(self.install(revision), self.meta(revision))

    def test_both_cross_build_directions_explain_recovery(self):
        for old, new in (
            (a, b) for a in tuple(map(int, c.CONTRACTS))
            for b in tuple(map(int, c.CONTRACTS)) if a != b
        ):
            meta = self.meta(old)
            before = copy.deepcopy(meta)
            with self.assertRaisesRegex(ValueError, 'ordinary campaign save'):
                c.validate_build(self.install(new), meta)
            self.assertEqual(meta, before)

    def test_pins_are_not_interchangeable(self):
        for revision in tuple(map(int, c.CONTRACTS)):
            for field in ('template', 'contract', 'bridge'):
                meta = self.meta(revision)
                meta[field] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'build mismatch'):
                    c.validate_build(self.install(revision), meta)

    def test_unknown_format(self):
        meta = self.meta(133)
        meta['format'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'format/version'):
            c.validate_build(self.install(133), meta)

    def test_legacy_has_no_new_ui_requirements(self):
        c.validate_ui_state(
            self.install(120),
            lambda *_: self.fail('Legacy bytes must not be interpreted as new UI state')
        )

    def test_ui_code_and_idle_state(self):
        data = {100: b'fixed hook', 200: bytes(8)}
        profile = dict(
            code=[dict(address=100, size=10, sha256=hashlib.sha256(data[100]).hexdigest())],
            idle=[dict(address=200, size=8)]
        )
        install = SimpleNamespace(profile=profile)
        c.validate_ui_state(install, lambda a, n: data[a])
        data[100] = b'wrong hook'
        with self.assertRaisesRegex(ValueError, 'UI code mismatch'):
            c.validate_ui_state(install, lambda a, n: data[a])
        data[100] = b'fixed hook'
        data[200] = b'\1' + bytes(7)
        with self.assertRaisesRegex(ValueError, 'Close the dialog'):
            c.validate_ui_state(install, lambda a, n: data[a])

    def test_new_hook_regions_do_not_overlap_checkpoint_gate(self):
        p = c.CONTRACTS['133']
        self.assertTrue(p['code'])
        self.assertTrue(p['idle'])
        for row in p['code'] + p['idle']:
            a, b = row['address'], row['address'] + row['size']
            self.assertTrue(b <= c.PARK or a >= c.PARK + 0x1000)
            self.assertLessEqual(b, 0x2000000)

    def test_retry_flag_is_mutable_but_bounded(self):
        profile = dict(code=[], idle=[], flags=[dict(address=0x1d2efc0)])
        install = SimpleNamespace(profile=profile)
        for value in (0, 1):
            c.validate_ui_state(install, lambda a, n: c.pack(value))
        with self.assertRaisesRegex(ValueError, 'retry flag'):
            c.validate_ui_state(install, lambda a, n: c.pack(2))
        self.assertNotIn(0x1d2efc0, [r['address'] for r in c.CONTRACTS['133']['code']])

    def test_campaign_transition_must_be_idle(self):
        p = c.CONTRACTS['138']
        self.assertIn(dict(address=0x1efe800, size=4), p['idle'])
        for row in p['code']:
            self.assertFalse(row['address'] <= 0x1efe800 < row['address'] + row['size'])
        data = {r['address']: bytes(r['size']) for r in p['idle']}
        profile = dict(code=[], idle=p['idle'])
        c.validate_ui_state(SimpleNamespace(profile=profile), lambda a, n: data[a])
        data[0x1efe800] = c.pack(3)
        with self.assertRaises(ValueError):
            c.validate_ui_state(SimpleNamespace(profile=profile), lambda a, n: data[a])


if __name__ == '__main__':
    unittest.main()
