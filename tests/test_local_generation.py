"""Local setup must reject bad inputs/results before writing an installation.

Fixtures contain invented text, not game bytes. The compiler subprocess is
substituted here to exercise failure handling and temporary-file ownership.
Actual original-input generation and byte identity are checked by the full
generation acceptance run; these tests do not stand in for that comparison.
"""
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tests import test_install_paths as installer_fixtures
from install_portable import install, sha
from generate_local import checked_inputs, required_inputs
import generation_tools
from original_inputs import edited_assembly
from patch_support import asm


class LocalAssemblyTests(TestCase):
    """Invented x86 checks local extraction, edits, branches and rejection."""

    def fixture(self):
        raw = asm(0x1000, 'inc eax; cmp eax,4; jb 0x1000; ret')
        return raw, (0x1000, 0x1000 + len(raw), sha(raw), {}, {})

    def test_local_branch_and_inserted_instruction_preserve_layout(self):
        raw, recipe = self.fixture()
        read = lambda a, n: raw[a-0x1000:a-0x1000+n]
        self.assertEqual(asm(0x2000, edited_assembly(recipe, read)), raw)
        recipe = (*recipe[:3], {0x1000: (0x1000, 'nop;')}, {})
        expected = asm(0x2000, 'nop; inc eax; cmp eax,4; jb 0x2000; ret')
        self.assertEqual(asm(0x2000, edited_assembly(recipe, read)), expected)

    def test_changed_or_short_local_code_is_rejected(self):
        raw, recipe = self.fixture()
        for changed in (raw[:-1], b'\x90' + raw[1:]):
            with self.assertRaisesRegex(ValueError, 'verified original'):
                edited_assembly(recipe, lambda a, n: changed)

    def test_edits_require_boundaries_and_local_branches(self):
        raw, recipe = self.fixture()
        for edits in ({0x1002: (0x1004, 'nop;')}, {0x1000: (0x1001, ''), 0x1001: (0x1000, '')}):
            with self.assertRaisesRegex(ValueError, 'boundaries'):
                edited_assembly((*recipe[:3], edits, {}), lambda a, n: raw)
        outside = asm(0x1000, 'jmp 0x5000')
        with self.assertRaisesRegex(ValueError, 'leaves'):
            edited_assembly((0x1000,0x1000+len(outside),sha(outside),{},{}),lambda a,n:outside)


class LocalGenerationTests(TestCase):
    def setUp(self):
        self.f = installer_fixtures.InstallPathsTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        self.raw = b'locally generated synthetic image'
        f.outputs.append(dict(path='native-template.bin', kind='generated',
                              size=len(self.raw), sha256=sha(self.raw)))
        f.manifest['schema'] = 3
        f.manifest['generation'] = dict(schema=1, inputs={
            'TNOVA/DATA/item.res': f.inputs['TNOVA/DATA/item.res']
        })
        f.write_manifest()
        self.tools = dict(compiler=f.root / 'compiler', dependencies=f.root / 'deps')
        self.work = None

    def generated_process(self, command, **unused):
        self.work = Path(command[command.index('--output') + 1])
        path = self.work / 'generated/native-template.bin'
        path.parent.mkdir(parents=True)
        path.write_bytes(self.raw)
        (self.work / 'generation.json').write_text(json.dumps(dict(
            game_revision=133, outputs={'native-template.bin': {}}, mode='local-generators'
        )))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def test_check_and_install_generate_without_deltas_and_remove_work(self):
        f = self.f
        with patch('install_portable.subprocess.run', side_effect=self.generated_process) as run:
            result = install(f.package, f.original, f.dest, True, **self.tools)
            self.assertEqual(result['generation']['mode'], 'local-generators')
            self.assertFalse(f.dest.exists())
            self.assertFalse(self.work.parent.exists())
            install(f.package, f.original, f.dest, **self.tools)
            self.assertEqual((f.dest / 'native-template.bin').read_bytes(), self.raw)
            self.assertEqual(run.call_count, 2)
        self.assertFalse(self.work.parent.exists())

    def test_corrupted_generated_bytes_never_create_destination(self):
        self.raw = b'wrong generated image'
        with patch('install_portable.subprocess.run', side_effect=self.generated_process):
            with self.assertRaisesRegex(ValueError, 'Generated output verification failed'):
                install(self.f.package, self.f.original, self.f.dest, **self.tools)
        self.assertFalse(self.f.dest.exists())
        self.assertFalse(self.work.parent.exists())

    def test_generator_failure_never_creates_destination(self):
        with patch('install_portable.subprocess.run', return_value=SimpleNamespace(
            returncode=1, stdout='compiler log', stderr='synthetic failure'
        )):
            with self.assertRaisesRegex(ValueError, 'synthetic failure'):
                install(self.f.package, self.f.original, self.f.dest, **self.tools)
        self.assertFalse(self.f.dest.exists())

    def test_missing_tools_and_mixed_delta_package_fail_before_generation(self):
        f = self.f
        with patch('install_portable.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, '--compiler'):
                install(f.package, f.original, f.dest)
            f.outputs.append(dict(path='old.res', kind='delta'))
            f.write_manifest()
            with self.assertRaisesRegex(ValueError, 'replace every prepared delta'):
                install(f.package, f.original, f.dest, **self.tools)
            run.assert_not_called()

    def test_changed_source_rejected_before_generation(self):
        f = self.f
        (f.original / 'TNOVA/DATA/item.res').write_bytes(b'changed')
        with patch('install_portable.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'unsupported original'):
                install(f.package, f.original, f.dest, **self.tools)
            run.assert_not_called()
        self.assertFalse(f.dest.exists())

    def test_generation_contract_includes_demo_executable_and_checked_resources(self):
        expected = required_inputs()
        self.assertEqual(len(expected), 10)
        self.assertIn('TNDEMO2/_SETUP/__FF.EXE', expected)
        self.assertIn('TNOVA/DATA/RESTNOBJ.RES', expected)
        f = self.f
        small = {'TNOVA/DATA/item.res': f.inputs['TNOVA/DATA/item.res']}
        self.assertEqual(checked_inputs({'TNOVA': f.original / 'TNOVA'}, small),
                         {'TNOVA/DATA/item.res': b'TNOVA'})
        (f.original / 'TNOVA/DATA/item.res').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'Unsupported generation input'):
            checked_inputs({'TNOVA': f.original / 'TNOVA'}, small)

    def test_tool_cache_cannot_be_created_inside_originals(self):
        f = self.f
        with patch('install_portable.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'Keep tools separate'):
                install(f.package, f.original, f.dest, tools_cache=f.original / 'tools')
            run.assert_not_called()
        self.assertFalse((f.original / 'tools').exists())

    def test_offline_tool_archive_requires_exact_bytes(self):
        f = self.f
        downloads = f.root / 'downloads'
        downloads.mkdir()
        (downloads / 'tool.zip').write_bytes(b'synthetic archive')
        row = dict(name='tool.zip', size=17, sha256=sha(b'synthetic archive'))
        generation_tools.fetch(row, f.root / 'good.zip', downloads)
        self.assertEqual((f.root / 'good.zip').read_bytes(), b'synthetic archive')
        (downloads / 'tool.zip').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            generation_tools.fetch(row, f.root / 'bad.zip', downloads)

    def test_tool_extraction_rejects_escape_duplicate_and_symlink_before_writing(self):
        f = self.f
        for index, bad in enumerate(('../outside', 'SAFE.txt', 'link')):
            archive = f.root / f'{index}.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                zipped.writestr('safe.txt', b'ok')
                if bad == 'link':
                    info = zipfile.ZipInfo(bad)
                    info.external_attr = 0o120777 << 16
                    zipped.writestr(info, b'outside')
                else:
                    zipped.writestr(bad, b'bad')
            destination = f.root / f'unpacked{index}'
            with self.assertRaises(ValueError):
                generation_tools.unpack(archive, destination)
            self.assertFalse(destination.exists())
