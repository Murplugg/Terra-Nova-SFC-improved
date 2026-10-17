"""Installer layouts, preservation, exact hashes and launcher path boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import errno
import json
import sys
import struct, zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from install_portable import install, sha, validate_destination
from tnova.state_core import validate_home


class InstallPathsTests(TestCase):

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='tn-install-')
        self.root = Path(self.temp.name).resolve()
        self.package = self.root / 'setup'
        (self.package / 'payload').mkdir(parents=True)
        self.original = self.root / 'original'
        self.inputs = {}
        self.outputs = []
        for folder in ('TNOVA', 'TNDEMO1', 'TNDEMO2'):
            path = self.original / folder / 'DATA/item.res'
            path.parent.mkdir(parents=True)
            data = folder.encode()
            path.write_bytes(data)
            rel = folder + '/DATA/item.res'
            self.inputs[rel] = dict(size=len(data), sha256=sha(data))
            self.outputs.append(
                dict(
                    path=folder + '/item.res',
                    kind='copy',
                    input=rel,
                    size=len(data),
                    sha256=sha(data)
                )
            )
        iso = self.original / '_ISO/TNF108.ISO'
        iso.parent.mkdir()
        iso.write_bytes(b'headCD contenttail')
        data = b'CD content'
        self.inputs['iso:video'] = dict(offset=4, size=len(data), sha256=sha(data))
        self.outputs.append(
            dict(
                path='video.res', kind='copy', input='iso:video', size=len(data), sha256=sha(data)
            )
        )
        self.portable = dict(relocations=[dict(value='{ROOT}\\retail\\', capacity=256)])
        payload = self.package / 'payload/portable.json'
        payload.write_text(json.dumps(self.portable))
        self.outputs.append(
            dict(
                path='portable.json',
                kind='payload',
                payload='payload/portable.json',
                size=payload.stat().st_size,
                sha256=sha(payload.read_bytes())
            )
        )
        self.manifest = dict(
            schema=1,
            game_revision=133,
            iso=dict(path='_ISO/TNF108.ISO', size=iso.stat().st_size, sha256=sha(iso.read_bytes())),
            inputs=self.inputs,
            outputs=self.outputs,
            package_files={'payload/portable.json': sha(payload.read_bytes())}
        )
        self.write_manifest()
        self.dest = self.root / 'new game & extras'

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        (self.package / 'install.json').write_text(json.dumps(self.manifest))

    def multi_source(self):
        names = ['TNOVA/DATA/item.res', 'TNDEMO2/DATA/item.res']
        a = (self.original / names[0]).read_bytes()
        b = (self.original / names[1]).read_bytes()
        target = b + a
        patch = zlib.compress(
            b'TND1C' + struct.pack('<II', len(a), len(b)) + b'C' + struct.pack('<II', 0, len(a))
        )
        (self.package / 'combined.tnd').write_bytes(patch)
        self.manifest['schema'] = 2
        self.manifest['package_files']['combined.tnd'] = sha(patch)
        self.outputs.append(
            dict(
                path='combined.res',
                kind='delta',
                input=names[0],
                base_inputs=names,
                patch='combined.tnd',
                size=len(target),
                sha256=sha(target)
            )
        )
        self.write_manifest()
        return names, target

    def test_multi_source_delta_check_and_install_from_split_originals(self):
        names, target = self.multi_source()
        paths = self.split_sources()
        result = install(self.package, None, self.dest, True, **paths)
        self.assertTrue(result['check_only'])
        self.assertFalse(self.dest.exists())
        install(self.package, None, self.dest, **paths)
        self.assertEqual((self.dest / 'combined.res').read_bytes(), target)

    def test_multi_source_delta_rejects_secondary_input_damage_before_output(self):
        names, _ = self.multi_source()
        (self.original / names[1]).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            install(self.package, self.original, self.dest)
        self.assertFalse(self.dest.exists())

    def test_multi_source_metadata_requires_schema2_and_unambiguous_order(self):
        names, _ = self.multi_source()
        self.manifest['schema'] = 1
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'schema2'):
            install(self.package, self.original, self.dest)
        self.manifest['schema'] = 2
        for bad in ([], names[::-1], [names[0], names[0]], 'not-a-list'):
            self.outputs[-1]['base_inputs'] = bad
            self.write_manifest()
            with self.assertRaises(ValueError):
                install(self.package, self.original, self.dest)
            self.assertFalse(self.dest.exists())

    def split_sources(self):
        paths = {}
        for key, folder in [
            ('retail', 'TNOVA'), ('download_demo', 'TNDEMO1'), ('cd_demo', 'TNDEMO2')
        ]:
            target = self.root / ('Separate æ originals ' + key)
            (self.original / folder).rename(target)
            paths[key] = target
        target = self.root / 'retail disc æ.iso'
        (self.original / '_ISO/TNF108.ISO').rename(target)
        paths['cd_image'] = target
        return paths

    def test_legacy_layout_and_check_only_preserve_sources(self):
        before = {p: sha(p.read_bytes()) for p in self.original.rglob('*') if p.is_file()}
        result = install(self.package, self.original, self.dest, True)
        self.assertTrue(result['check_only'])
        self.assertFalse(self.dest.exists())
        install(self.package, self.original, self.dest)
        self.assertEqual(before, {p: sha(p.read_bytes()) for p in before})
        self.assertEqual((self.dest / 'video.res').read_bytes(), b'CD content')

    def test_separate_unicode_sources_produce_identical_files(self):
        legacy = self.root / 'legacy'
        install(self.package, self.original, legacy)
        choices = self.split_sources()
        result = install(self.package, None, self.dest, **choices)
        self.assertEqual(result['original_inputs'], 4)
        for row in self.outputs:
            self.assertEqual(
                (legacy / row['path']).read_bytes(), (self.dest / row['path']).read_bytes()
            )

    def test_partial_override_and_missing_locations(self):
        moved = self.root / 'retail moved'
        (self.original / 'TNOVA').rename(moved)
        install(self.package, self.original, self.dest, True, retail=moved)
        with self.assertRaisesRegex(ValueError, 'missing TNDEMO1'):
            install(self.package, None, self.dest, retail=moved)
        self.assertFalse(self.dest.exists())

    def test_changed_original_or_cd_rejected_without_destination(self):
        choices = self.split_sources()
        item = choices['retail'] / 'DATA/item.res'
        old = item.read_bytes()
        item.write_bytes(b'wrong edition')
        with self.assertRaisesRegex(ValueError, 'unsupported original'):
            install(self.package, None, self.dest, **choices)
        self.assertFalse(self.dest.exists())
        item.write_bytes(old)
        choices['cd_image'].write_bytes(b'wrong CD')
        with self.assertRaisesRegex(ValueError, 'Unsupported CD'):
            install(self.package, None, self.dest, **choices)
        self.assertFalse(self.dest.exists())

    def test_destination_must_not_overlap_any_source_or_setup(self):
        choices = self.split_sources()
        for target in [
            self.package / 'child', choices['retail'] / 'child', choices['download_demo'] / 'child',
            choices['cd_demo'] / 'child'
        ]:
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'separate'):
                install(self.package, None, target, **choices)
            self.assertFalse(target.exists())
        self.dest.mkdir()
        (self.dest / 'keep').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'never overwritten'):
            install(self.package, None, self.dest, **choices)
        self.assertEqual((self.dest / 'keep').read_bytes(), b'keep')

    def test_escaping_or_unknown_input_rejected(self):
        for bad in ('TNOVA/../secret', 'TNOVA/DATA\\item.res', 'UNKNOWN/file'):
            original = self.manifest['inputs']
            self.manifest['inputs'] = {bad: dict(size=1, sha256='bad')}
            self.write_manifest()
            with self.assertRaises(ValueError):
                install(self.package, self.original, self.dest)
            self.assertFalse(self.dest.exists())
            self.manifest['inputs'] = original

    def test_path_limit_matches_launcher_and_rejects_unicode(self):
        # Windows absolute paths: 155 + 44 = 199, the last supported run length.
        for length in (154, 155, 156, 199):
            path = Path('C:/' + ('x' * (length - 3)))
            for check in (lambda p: validate_destination(p, self.portable), validate_home):
                if length <= 155:
                    check(path)
                else:
                    with self.assertRaisesRegex(ValueError, 'too long'):
                        check(path)
        for check in (lambda p: validate_destination(p, self.portable), validate_home):
            with self.assertRaisesRegex(ValueError, 'ASCII'):
                check(Path('C:/Gåmes/TNova'))

    def test_shorter_relocation_capacity_still_enforced(self):
        with self.assertRaisesRegex(ValueError, 'too long'):
            validate_destination(
                Path('C:/Games'), dict(relocations=[dict(value='{ROOT}/long', capacity=8)])
            )

    def test_current_game_slots_limit_root_to_115_characters(self):
        recipe = json.loads(
            (Path(__file__).resolve().parents[1] / 'engine/release-recipe.json').read_text()
        )
        for length in (114, 115, 116, 155):
            path = Path('C:/' + ('x' * (length - 3)))
            for check in (
                lambda p: validate_destination(p, recipe),
                lambda p: validate_home(p, recipe['relocations'])
            ):
                if length <= 115:
                    check(path)
                else:
                    with self.assertRaisesRegex(ValueError, '115 characters'):
                        check(path)

    def shared_outputs(self):
        """Model original archives, duplicate CD use and private mutable state."""
        self.outputs[0]['path'] = 'retail/DATA/item.res'
        self.outputs.append(dict(self.outputs[0], path='cd/DATA/item.res'))
        self.outputs.append(dict(self.outputs[0], path='retail/TN.CFG'))
        self.outputs.append(dict(self.outputs[0], path='retail/SAVE01.RES'))
        self.outputs[3]['path'] = 'cd/MOVIE/intro.smk'
        self.outputs.append(dict(self.outputs[3], path='prequel/MOVIE/intro.smk'))
        self.write_manifest()

    def test_shared_assets_reuse_originals_and_cd_cache_with_private_settings(self):
        self.shared_outputs()
        result = install(self.package, self.original, self.dest)
        original = self.original / 'TNOVA/DATA/item.res'
        self.assertTrue((self.dest / 'retail/DATA/item.res').samefile(original))
        self.assertTrue((self.dest / 'cd/DATA/item.res').samefile(original))
        self.assertFalse((self.dest / 'retail/TN.CFG').samefile(original))
        self.assertFalse((self.dest / 'retail/SAVE01.RES').samefile(original))
        (self.dest / 'retail/TN.CFG').write_bytes(b'private settings')
        self.assertEqual(original.read_bytes(), b'TNOVA')
        self.assertEqual(result['storage']['cache_bytes_added'], len(b'CD content'))
        second = self.root / 'second installation'
        second_result = install(self.package, self.original, second)
        self.assertEqual(second_result['storage']['cache_bytes_added'], 0)
        self.assertTrue((second / 'cd/MOVIE/intro.smk').samefile(self.dest / 'cd/MOVIE/intro.smk'))
        # Removing an original directory entry cannot break its installed link.
        original.unlink()
        self.assertEqual((self.dest / 'retail/DATA/item.res').read_bytes(), b'TNOVA')

    def test_copy_mode_keeps_every_file_independent_and_creates_no_cache(self):
        self.shared_outputs()
        result = install(self.package, self.original, self.dest, data_mode='copy')
        self.assertEqual(result['storage']['linked_files'], 0)
        self.assertFalse((self.root / 'TNova-shared-data').exists())
        self.assertFalse((self.dest / 'retail/DATA/item.res').samefile(self.original / 'TNOVA/DATA/item.res'))
        self.assertFalse((self.dest / 'cd/MOVIE/intro.smk').samefile(self.dest / 'prequel/MOVIE/intro.smk'))

    def test_unsupported_links_fall_back_to_verified_copies_and_report_storage(self):
        self.shared_outputs()
        with patch('install_portable.os.link', side_effect=OSError(errno.EXDEV, 'Different volume')):
            result = install(self.package, self.original, self.dest)
        self.assertEqual(result['storage']['copy_fallbacks'], 4)
        self.assertEqual(result['storage']['linked_files'], 0)
        self.assertEqual((self.dest / 'cd/MOVIE/intro.smk').read_bytes(), b'CD content')

    def test_shared_cache_check_only_and_invalid_locations(self):
        self.shared_outputs()
        install(self.package, self.original, self.dest, True)
        self.assertFalse((self.root / 'TNova-shared-data').exists())
        self.assertFalse(self.dest.exists())
        for cache in (self.original, self.dest / 'cache', self.package / 'cache'):
            with self.assertRaisesRegex(ValueError, 'shared data cache separate'):
                install(self.package, self.original, self.dest, data_cache=cache)

    def test_changed_cache_rejected_without_overwriting_shared_content(self):
        self.shared_outputs()
        cache = self.root / 'cache'
        digest = sha(b'CD content')
        entry = cache / digest[:2] / (digest + '.bin')
        entry.parent.mkdir(parents=True)
        entry.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Changed shared data cache'):
            install(self.package, self.original, self.dest, data_cache=cache)
        self.assertFalse(self.dest.exists())
        self.assertEqual(entry.read_bytes(), b'changed')

    def test_payload_override_never_links_to_original_with_identical_bytes(self):
        self.shared_outputs()
        payload = self.package / 'payload/override.res'
        payload.write_bytes(b'TNOVA')
        self.outputs.append(dict(path='prequel/DATA/override.res', kind='payload',
                                 payload='payload/override.res', size=5, sha256=sha(b'TNOVA')))
        self.manifest['package_files']['payload/override.res'] = sha(b'TNOVA')
        self.write_manifest()
        install(self.package, self.original, self.dest)
        self.assertFalse((self.dest / 'prequel/DATA/override.res').samefile(self.original / 'TNOVA/DATA/item.res'))


if __name__ == '__main__':
    main()
