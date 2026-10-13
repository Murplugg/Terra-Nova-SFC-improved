"""Frozen-runtime inheritance and setup attachment regression checks."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch, call
import json
import zipfile

from tnova import sessions
from build_launcher import attach, digest


class LibraryPathTests(TestCase):

    def test_source_runtime_does_not_change_library_search(self):
        with patch.object(
            sessions.sys, 'frozen', False, create=True
        ), patch.object(sessions.ctypes, 'WinDLL') as load:
            with sessions.game_library_path():
                pass
            load.assert_not_called()

    def test_frozen_restores_search_path_even_when_child_creation_fails(self):
        for fail in (False, True):
            kernel = Mock()
            with patch.object(
                sessions.sys, 'frozen', True, create=True
            ), patch.object(
                sessions.sys, '_MEIPASS', 'runtime', create=True
            ), patch.object(
                sessions.ctypes, 'WinDLL', return_value=kernel
            ):
                try:
                    with sessions.game_library_path():
                        kernel.SetDllDirectoryW.assert_called_once_with(None)
                        if fail:
                            raise RuntimeError('child failed')
                except RuntimeError as exc:
                    self.assertTrue(fail)
                    self.assertEqual(str(exc), 'child failed')
                self.assertEqual(
                    kernel.SetDllDirectoryW.call_args_list,
                    [call(None), call('runtime')]
                )

    def test_failed_reset_prevents_child_launch(self):
        kernel = Mock()
        kernel.SetDllDirectoryW.return_value = False
        with patch.object(
            sessions.sys, 'frozen', True, create=True
        ), patch.object(
            sessions.ctypes, 'WinDLL', return_value=kernel
        ):
            with self.assertRaises(OSError):
                with sessions.game_library_path():
                    self.fail('Unsafe inherited path allowed')


class AttachmentTests(TestCase):

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='tnova-package-test-')
        self.root = Path(self.temp.name)
        self.package = self.root / 'build/package'
        self.bundle = self.root / 'bundle'
        (self.package / 'payload').mkdir(parents=True)
        self.bundle.mkdir()
        (self.package / 'payload/portable.json').write_bytes(b'{"contract":"unchanged"}')
        (self.package / 'README.txt').write_text('old setup')
        manifest = dict(
            schema=2,
            installer_revision=133,
            game_revision=133,
            outputs=[dict(path='portable.json', kind='payload', payload='payload/portable.json')],
            package_files={
                p.relative_to(self.package).as_posix(): digest(p)
                for p in self.package.rglob('*') if p.is_file()
            }
        )
        (self.package / 'install.json').write_text(json.dumps(manifest))
        (self.bundle / 'Terra Nova Launcher.exe').write_bytes(b'fixture launcher')
        self.bundle_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def bundle_manifest(self):
        files = {
            p.name: digest(p)
            for p in self.bundle.iterdir() if p.name != 'launcher-bundle.json'
        }
        (self.bundle / 'launcher-bundle.json').write_text(json.dumps(dict(files=files, bytes=16)))

    def test_attachment_keeps_game_contract_and_checks_all_payloads(self):
        before = (self.package / 'payload/portable.json').read_bytes()
        report = attach(self.root / 'build', self.bundle)
        self.assertEqual((self.package / 'payload/portable.json').read_bytes(), before)
        manifest = json.loads((self.package / 'install.json').read_text())
        self.assertEqual(manifest['installer_revision'], 136)
        for name, expected in manifest['package_files'].items():
            self.assertEqual(digest(self.package / name), expected)
        with zipfile.ZipFile(report['archive']) as archive:
            self.assertEqual(archive.read('payload/portable.json'), before)
            self.assertIn(b'Terra Nova Launcher.exe', archive.read('payload/Play.cmd'))
        with self.assertRaises(ValueError):
            attach(self.root / 'build', self.bundle)

    def test_tampered_missing_extra_and_overlapping_files_rejected_before_mutation(self):
        original = (self.package / 'install.json').read_bytes()
        exe = self.bundle / 'Terra Nova Launcher.exe'
        exe.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'changed'):
            attach(self.root / 'build', self.bundle)
        exe.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            attach(self.root / 'build', self.bundle)
        exe.write_bytes(b'fixture launcher')
        (self.bundle / 'extra').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            attach(self.root / 'build', self.bundle)
        (self.bundle / 'extra').unlink()
        (self.bundle / 'portable.json').write_text('overlap')
        self.bundle_manifest()
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            attach(self.root / 'build', self.bundle)
        self.assertEqual((self.package / 'install.json').read_bytes(), original)

    def test_current_build_is_admitted_by_format_and_rejected_on_identity_mismatch(self):
        # Packaging once rejected a newer engine solely because its number was
        # absent from a historical allowlist. Exercise a future fixture identity
        # without depending on the current production release number.
        path = self.package / 'install.json'
        original = json.loads(path.read_text())
        for changes in ({'schema': 99}, {'installer_revision': 999},
                        {'game_revision': '133'}, {'game_revision': True}):
            bad = dict(original, **changes)
            path.write_text(json.dumps(bad))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'supported unbundled'):
                attach(self.root / 'build', self.bundle)
            self.assertEqual(path.read_bytes(), before)
        original.update(game_revision=999, installer_revision=999)
        path.write_text(json.dumps(original))
        result = attach(self.root / 'build', self.bundle)
        self.assertIn('v999', result['archive'])

    def test_local_generation_attachment_preserves_recipes_and_names_setup_tools(self):
        # A generator package must stay a generator package after the launcher
        # is added. Its one-time compiler requirement must remain visible.
        path = self.package / 'install.json'
        manifest = json.loads(path.read_text())
        manifest.update(schema=3, generation=dict(schema=1, inputs={}))
        manifest['outputs'].append(dict(path='native-template.bin', kind='generated'))
        path.write_text(json.dumps(manifest))
        result = attach(self.root / 'build', self.bundle)
        after = json.loads(path.read_text())
        self.assertEqual(after['generation'], manifest['generation'])
        self.assertEqual(after['schema'], 3)
        self.assertFalse(any(r['kind'] == 'delta' for r in after['outputs']))
        with zipfile.ZipFile(result['archive']) as archive:
            readme = archive.read('README.txt').decode()
            self.assertIn('--compiler', readme)
            self.assertIn('No prepared game/resource deltas', readme)


if __name__ == '__main__':
    main()
