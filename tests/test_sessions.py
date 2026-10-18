"""Session isolation and failure handling without operating a live game."""
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch, Mock
import json
import os
import struct

from tnova import sessions as s


class ScenarioReportTests(TestCase):
    """Arena snapshots must not invent reports from retained campaign counters.

    The captured failure had current map 42, profile 37 and progress counter 40.
    Small authored resource archives exercise preservation and the strict retail
    failure path. Native capture/restore remains a separate integration check.
    """

    def memory(self, mission):
        from tnova import state_core as c
        r = bytearray(0x450000)
        for a, value in ((0x359708, mission), (0x359710, 37), (0x35d0ec, 40)):
            struct.pack_into('<I', r, a, value)
        r[0x4412ce+37] = 3
        r[0x440934:0x440934+19] = b'C:\\TNOVA\\mstat.res\0'
        return r

    def test_only_known_scenario_maps_skip_campaign_report_sequence(self):
        from tnova import state_core as c
        for mission in (1, 10, 37, 39, 40, 41, 42, 43, 44, 45, 46, 47):
            need = c.required_reports(self.memory(mission))
            self.assertEqual(need == [], mission in (42, 43, 44), mission)

    def test_scenario_capture_preserves_existing_reports(self):
        from tnova import state_core as c
        with TemporaryDirectory(prefix='tnova-reports-') as folder:
            home = Path(folder).resolve()
            (home/'retail').mkdir()
            rows = {0x659: (struct.pack('<H', 0x659)+bytes(4)+b'\x03\0\0\0', b'abc')}
            (home/'retail/mstat.res').write_bytes(c.archive(rows))
            install = Mock(home=home)
            for mission in (42, 43, 44):
                result = c.reports(self.memory(mission), install, 'retail')
                self.assertEqual(c.resource_entries(result), rows)
            with self.assertRaisesRegex(ValueError, 'Completed mission reports are missing'):
                c.reports(self.memory(37), install, 'retail')

    def test_scenario_without_report_file_can_start_with_empty_archive(self):
        from tnova import state_core as c
        with TemporaryDirectory(prefix='tnova-reports-') as folder:
            install = Mock(home=Path(folder).resolve())
            self.assertEqual(c.resource_entries(c.reports(self.memory(42), install, 'retail')), {})
            with self.assertRaisesRegex(ValueError, 'Missing closed mission report'):
                c.reports(self.memory(37), install, 'retail')


class SessionsTests(TestCase):

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='tnova-session-test-')
        self.home = Path(self.temp.name).resolve()
        (self.home / 'portable.json').write_text('{}')
        self.service = s.Sessions(self.home)
        self.lock = patch.object(s, 'installation_lock', return_value=nullcontext())
        self.lock.start()

    def tearDown(self):
        self.lock.stop()
        if not self.home.name.startswith('tnova-session-test-'):
            raise ValueError('Unexpected test cleanup path')
        self.temp.cleanup()

    def state(self, name='one', campaign='retail', label=None):
        folder = self.home / 'states' / name
        folder.mkdir(parents=True)
        meta = dict(format='tn-portable-state-126', revision=120, campaign=campaign)
        (folder / 'snapshot.json').write_text(json.dumps(meta))
        if label is not None:
            (folder / 'label.json').write_text(json.dumps(dict(title=label)))
        return folder

    def test_only_this_installation_processes_selected(self):
        paths = [
            self.home / 'native-startup.exe', self.home / 'state-runs/a/native-checkpoint.exe',
            self.home.parent / 'native-startup.exe', self.home / 'other/native-checkpoint.exe',
            self.home / 'state-runs/a/extra/native-checkpoint.exe',
            self.home / 'state-runs/a/other.exe'
        ]
        with patch.object(
            s, 'game_processes', return_value=[s.GameProcess(i, p) for i, p in enumerate(paths)]
        ):
            self.assertEqual([p.pid for p in self.service.running()], [0, 1])

    def test_listing_ignores_incomplete_wrong_version_and_wrong_campaign(self):
        valid = self.state(label='My mission')
        self.state('.partial-hidden')
        self.state('wrong', campaign='unrelated')
        old = self.state('old')
        (old / 'snapshot.json').write_text('{"format":"old"}')
        broken = self.state('broken')
        (broken / 'snapshot.json').write_text('not json')
        self.assertEqual(
            [(r.folder, r.title) for r in self.service.states()], [(valid, 'My mission')]
        )

    def test_oversized_metadata_not_read(self):
        folder = self.state()
        (folder / 'snapshot.json').write_bytes(b' ' * 65537)
        self.assertEqual(self.service.states(), [])

    def test_listing_includes_new_supported_revision_but_not_unknown_builds(self):
        current = self.state('current')
        unknown = self.state('unknown')
        for folder, revision in ((current, 133), (unknown, 999)):
            meta = json.loads((folder / 'snapshot.json').read_text())
            meta['revision'] = revision
            (folder / 'snapshot.json').write_text(json.dumps(meta))
        self.assertEqual([row.folder for row in self.service.states()], [current])

    def test_title_is_not_used_as_path(self):
        self.state(label='../../another/save')
        self.assertEqual(self.service.states()[0].folder.parent, self.home / 'states')

    def test_outside_snapshot_rejected_before_restore(self):
        with patch.object(s.core, 'build_restore') as restore:
            with self.assertRaisesRegex(ValueError, 'from this installation'):
                self.service.load(self.home.parent / 'elsewhere')
            restore.assert_not_called()

    def test_active_game_prevents_play_and_load(self):
        folder = self.state()
        with patch.object(
            self.service,
            'running',
            return_value=[s.GameProcess(1, self.home / 'native-startup.exe')]
        ), patch.object(s.core, 'Installation') as install:
            for action in (self.service.play, lambda: self.service.load(folder)):
                with self.assertRaisesRegex(ValueError, 'Exit the game'):
                    action()
            install.assert_not_called()

    def test_no_game_or_multiple_games_prevents_capture(self):
        with patch.object(s.core, 'capture') as capture:
            for rows in ([], [s.GameProcess(1, self.home / 'native-startup.exe')] * 2):
                with patch.object(
                    self.service, 'running', return_value=rows
                ), self.assertRaisesRegex(ValueError, 'exactly one'):
                    self.service.save('A name')
            capture.assert_not_called()

    def test_repeated_save_has_unique_destination_and_correct_checkpoint_path(self):
        checkpoint = self.home / 'state-runs/run1/native-checkpoint.exe'

        def capture(install, pid, folder, executable):
            self.assertEqual(pid, 7)
            self.assertEqual(executable, 'state-runs/run1/native-checkpoint.exe')
            self.assertFalse(folder.exists())
            folder.mkdir(parents=True)
            return dict(snapshot=str(folder))

        with patch.object(
            self.service, 'running', return_value=[s.GameProcess(7, checkpoint)]
        ), patch.object(s.core, 'Installation'), patch.object(
            s.core, 'capture', side_effect=capture
        ):
            a = self.service.save('My game')
            b = self.service.save('My game')
        self.assertNotEqual(a['snapshot'], b['snapshot'])
        self.assertEqual(
            json.loads((Path(a['snapshot']) / 'label.json').read_text())['title'], 'My game'
        )

    def test_failed_capture_creates_no_visible_state(self):
        with patch.object(
            self.service,
            'running',
            return_value=[s.GameProcess(1, self.home / 'native-startup.exe')]
        ), patch.object(s.core, 'Installation'), patch.object(
            s.core, 'capture', side_effect=ValueError('Pause first')
        ):
            with self.assertRaisesRegex(ValueError, 'Pause'):
                self.service.save('New')
        self.assertEqual(self.service.states(), [])

    def test_load_uses_saved_campaign_new_run_and_launches_result(self):
        folder = self.state(campaign='prequel')

        def restore(install, source, destination, campaign):
            self.assertEqual(source, folder)
            self.assertEqual(destination.parent, self.home / 'state-runs')
            self.assertFalse(destination.exists())
            self.assertEqual(campaign, 'prequel')
            return dict(executable=str(destination / 'native-checkpoint.exe'))

        with patch.object(
            self.service, 'running', return_value=[]
        ), patch.object(s.core, 'Installation'), patch.object(self.service,
                                                              'prepare') as prepare, patch.object(
                                                                  s.core,
                                                                  'build_restore',
                                                                  side_effect=restore
                                                              ), patch.object(
                                                                  self.service,
                                                                  'launch',
                                                                  return_value=42
                                                              ) as launch:
            result = self.service.load(folder)
            self.assertEqual(result['pid'], 42)
            launch.assert_called_once_with(Path(result['executable']))
            prepare.assert_called_once()

    def test_restore_failure_never_launches(self):
        folder = self.state()
        with patch.object(
            self.service, 'running', return_value=[]
        ), patch.object(s.core,
                        'Installation'), patch.object(self.service, 'prepare'), patch.object(
                            s.core, 'build_restore', side_effect=ValueError('Corrupt state')
                        ), patch.object(self.service, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, 'Corrupt'):
                self.service.load(folder)
            launch.assert_not_called()

    def test_ingame_invalid_state_leaves_current_game_open(self):
        folder = self.state(campaign='prequel')
        game = s.GameProcess(8, self.home / 'native-startup.exe')
        with patch.object(self.service,
                          'paused_prequel'), patch.object(s.core, 'Installation'), patch.object(
                              s.core, 'build_restore', side_effect=ValueError('Corrupt state')
                          ), patch.object(s, 'close_game') as close, patch.object(
                              self.service, 'launch'
                          ) as launch:
            with self.assertRaisesRegex(ValueError, 'Corrupt'):
                self.service.load_in_game(folder, game)
            close.assert_not_called()
            launch.assert_not_called()

    def test_ingame_process_changed_during_preparation_is_not_closed(self):
        folder = self.state(campaign='prequel')
        game = s.GameProcess(8, self.home / 'native-startup.exe')
        with patch.object(
            self.service, 'paused_prequel', side_effect=[game, ValueError('game changed')]
        ), patch.object(s.core, 'Installation'), patch.object(
            s.core, 'build_restore', return_value={'executable': 'prepared.exe'}
        ), patch.object(s, 'close_game') as close, patch.object(self.service, 'launch') as launch:
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.service.load_in_game(folder, game)
            close.assert_not_called()
            launch.assert_not_called()

    def test_ingame_restore_is_prepared_before_close_and_launch(self):
        folder = self.state(campaign='prequel')
        game = s.GameProcess(8, self.home / 'native-startup.exe')
        order = []

        def restore(install, source, destination, campaign):
            order.append('prepare')
            self.assertEqual(campaign, 'prequel')
            return {'executable': str(destination / 'native-checkpoint.exe')}

        with patch.object(
            self.service, 'paused_prequel', side_effect=lambda expected: order.append('recheck')
        ), patch.object(s.core, 'Installation'), patch.object(
            s.core, 'build_restore', side_effect=restore
        ), patch.object(
            s, 'close_game', side_effect=lambda game: order.append('close')
        ), patch.object(self.service,
                        'require_closed'), patch.object(self.service, 'prune_runs'), patch.object(
                            self.service, 'launch', side_effect=lambda exe: order.append('launch')
                        ):
            self.service.load_in_game(folder, game)
        self.assertEqual(order, ['recheck', 'prepare', 'recheck', 'close', 'launch'])

    def test_ingame_retail_state_cannot_close_prequel(self):
        folder = self.state(campaign='retail')
        with patch.object(s, 'close_game') as close:
            with self.assertRaisesRegex(ValueError, 'Prequel saved state'):
                self.service.load_in_game(
                    folder, s.GameProcess(8, self.home / 'native-startup.exe')
                )
            close.assert_not_called()

    def test_prepare_after_move_preserves_other_files(self):

        class Install:
            startup_image = b'regenerated portable entry point'

        (self.home / 'native-startup.exe').write_bytes(b'old location')
        (self.home / 'keep.txt').write_text('keep')
        with patch.object(self.service, 'running', return_value=[]):
            result = self.service.prepare(Install())
        self.assertEqual(result.read_bytes(), Install.startup_image)
        self.assertEqual((self.home / 'keep.txt').read_text(), 'keep')
        self.assertEqual(list(self.home.glob('*.tmp')), [])

    def test_process_scan_failure_does_not_allow_play(self):
        with patch.object(
            s, 'game_processes', side_effect=OSError('scan failed')
        ), patch.object(s.core, 'Installation') as install:
            with self.assertRaises(OSError):
                self.service.play()
            install.assert_not_called()

    def test_invalid_title_does_not_capture(self):
        for name in ('x' * 101, 'a\nb'):
            with self.assertRaisesRegex(ValueError, '100 ordinary'):
                self.service.save(name)


class RunCleanupTests(TestCase):

    def setUp(self):
        self.temp = TemporaryDirectory(prefix='tnova-cleanup-test-')
        self.home = Path(self.temp.name).resolve()
        (self.home / 'portable.json').write_text('{}')
        self.service = s.Sessions(self.home)
        self.scan = patch.object(self.service, 'running', return_value=[])
        self.scan.start()
        self.folders = [self.make_run(i) for i in range(4)]

    def tearDown(self):
        self.scan.stop()
        if not self.home.name.startswith('tnova-cleanup-test-'):
            raise ValueError('Unexpected test cleanup path')
        self.temp.cleanup()

    def make_run(self, i):
        folder = self.home / 'state-runs' / f'{i:032x}'
        folder.mkdir(parents=True)
        for name in ('native-checkpoint.exe', 'tn-checkpoint-audio.dll', 'stdout.txt'):
            (folder / name).write_bytes(b'test')
        s.core.save_json(
            folder / 'restore.json',
            dict(
                format='tn-portable-restore-126',
                revision=133,
                template=s.core.CONTRACTS['133']['template'],
                campaign='retail',
                executable_sha256=s.core.digest(b'test'),
                audio_sha256=s.core.digest(b'test'),
                report='../must-never-follow.RES'
            )
        )
        os.utime(folder / 'restore.json', ns=(1000000000 + i, 1000000000 + i))
        return folder

    def test_keeps_two_newest_and_never_touches_saves_or_reports(self):
        for name in ('states/keep/memory.bin', 'retail/M1234567.RES', 'native-startup.exe'):
            p = self.home / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'keep')
        result = self.service.prune_runs()
        self.assertEqual(set(result['removed']), {p.name for p in self.folders[:2]})
        self.assertGreater(result['bytes_reclaimed'], 0)
        self.assertTrue(all(p.exists() for p in self.folders[2:]))
        for name in ('states/keep/memory.bin', 'retail/M1234567.RES', 'native-startup.exe'):
            self.assertEqual((self.home / name).read_bytes(), b'keep')
        self.assertFalse(self.service.prune_runs()['removed'])

    def test_dry_run_changes_nothing(self):
        result = self.service.prune_runs(dry_run=True)
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(result['removed'], [])
        self.assertTrue(all(p.exists() for p in self.folders))

    def test_current_launch_protected_against_clock_rollback(self):
        self.service.prune_runs(protect=self.folders[0])
        self.assertTrue(self.folders[0].exists())
        self.assertTrue(self.folders[3].exists())

    def test_live_game_blocks_every_deletion(self):
        with patch.object(
            self.service,
            'running',
            return_value=[s.GameProcess(5, self.folders[0] / 'native-checkpoint.exe')]
        ):
            with self.assertRaisesRegex(ValueError, 'Exit the game'):
                self.service.prune_runs()
        self.assertTrue(all(p.exists() for p in self.folders))

    def test_scan_failure_blocks_every_deletion(self):
        with patch.object(self.service, 'running', side_effect=OSError('scan failed')):
            with self.assertRaises(OSError):
                self.service.prune_runs()
        self.assertTrue(all(p.exists() for p in self.folders))

    def test_unknown_files_nested_folders_and_modified_binaries_preserved(self):
        (self.folders[0] / 'notes.txt').write_text('mine')
        (self.folders[1] / 'subdir').mkdir()
        (self.folders[2] / 'native-checkpoint.exe').write_bytes(b'changed')
        result = self.service.prune_runs()
        self.assertEqual(len(result['skipped']), 3)
        self.assertTrue(all(p.exists() for p in self.folders))

    def test_bad_metadata_incomplete_and_unknown_names_preserved(self):
        (self.folders[0] / 'restore.json').write_text('{}')
        (self.folders[1] / 'tn-checkpoint-audio.dll').unlink()
        self.folders[2].rename(self.home / 'state-runs' / 'manual-run')
        result = self.service.prune_runs()
        self.assertEqual(len(result['skipped']), 3)
        self.assertEqual(result['removed'], [])

    def test_reparse_root_or_child_rejected(self):
        original = s.plain_path
        for blocked in (self.home / 'state-runs', self.folders[0], self.folders[0] / 'stdout.txt'):
            with patch.object(
                s,
                'plain_path',
                side_effect=lambda p, directory=False: p != blocked and original(p, directory)
            ):
                self.assertIsNone(s.inspect_run(self.home, self.folders[0]))

    def test_windows_reparse_attribute_rejected(self):
        fake = Mock()
        fake.lstat.return_value = Mock(st_mode=0o100644, st_file_attributes=0x400)
        self.assertFalse(s.plain_path(fake))

    def test_changed_folder_rechecked_before_deletion(self):
        original = s.inspect_run
        calls = {}

        def inspect(home, folder):
            calls[folder] = calls.get(folder, 0) + 1
            if calls[folder] == 2:
                (folder / 'new-notes.txt').write_text('keep')
            return original(home, folder)

        with patch.object(s, 'inspect_run', side_effect=inspect):
            result = self.service.prune_runs()
        self.assertEqual(result['removed'], [])
        self.assertTrue(all(p.exists() for p in self.folders))

    def test_io_failure_retains_folder_and_records_error(self):
        with patch.object(Path, 'unlink', side_effect=PermissionError('busy')):
            result = self.service.prune_runs()
        self.assertEqual(len(result['errors']), 2)
        self.assertTrue(all(p.exists() for p in self.folders))


class LockTests(TestCase):

    def test_concurrent_operation_rejected_and_lock_released(self):
        temp = TemporaryDirectory(prefix='tnova-lock-test-')
        home = Path(temp.name).resolve()
        try:
            with s.installation_lock(home):
                with self.assertRaisesRegex(ValueError, 'Another launcher'):
                    with s.installation_lock(home):
                        self.fail('Second operation obtained lock')
            with s.installation_lock(home):
                pass
        finally:
            if not home.name.startswith('tnova-lock-test-'):
                raise ValueError('Unexpected test cleanup path')
            temp.cleanup()


class ProcessScanTests(TestCase):
    """Model a Windows image-query race observed immediately after game exit.

    Only an exited process may disappear from the result. An active process or
    failed status query must still block operations that require a closed game.
    """

    def scan(self, exit_code, status_ok=True, image_ok=False):
        kernel = Mock()
        kernel.CreateToolhelp32Snapshot.return_value = 100
        kernel.OpenProcess.return_value = 200

        def first(snapshot, result):
            result._obj.pid = 42
            result._obj.name = 'native-checkpoint.exe'
            return True

        def image(handle, flags, text, size):
            if image_ok:
                text.value = str(Path('native-checkpoint.exe').resolve())
            return image_ok

        def status(handle, result):
            self.assertEqual(handle, 200)
            result._obj.value = exit_code
            return status_ok

        kernel.Process32FirstW.side_effect = first
        kernel.Process32NextW.return_value = False
        kernel.QueryFullProcessImageNameW.side_effect = image
        kernel.GetExitCodeProcess.side_effect = status
        try:
            with patch.object(s.ctypes, 'WinDLL', return_value=kernel), patch.object(
                s.ctypes, 'get_last_error', return_value=18
            ):
                return s.game_processes(), kernel
        finally:
            self.assertEqual(kernel.CloseHandle.call_args_list,
                             [((200,), {}), ((100,), {})])

    def test_confirmed_exited_process_is_ignored(self):
        result, kernel = self.scan(0)
        self.assertEqual(result, [])
        kernel.GetExitCodeProcess.assert_called_once()

    def test_live_or_unconfirmed_process_still_blocks(self):
        for code, ok in ((259, True), (0, False)):
            with self.subTest(code=code, status_ok=ok):
                with self.assertRaisesRegex(OSError, 'Could not identify'):
                    self.scan(code, ok)

    def test_successful_image_query_keeps_original_behavior(self):
        result, kernel = self.scan(259, image_ok=True)
        self.assertEqual(result, [s.GameProcess(42, Path('native-checkpoint.exe').resolve())])
        kernel.GetExitCodeProcess.assert_not_called()


class CloseTests(TestCase):

    def test_exit_wait_keeps_verified_handle_without_reenumerating_image(self):
        game = s.GameProcess(42, Path('native-checkpoint.exe'))
        process = Mock(h=123)
        process.u.return_value = 456
        user = Mock()

        def owner(window, result):
            result._obj.value = game.pid
            return 99

        user.GetWindowThreadProcessId.side_effect = owner
        codes = iter([259, 0])

        def exit_code(handle, result):
            self.assertEqual(handle, 123)
            result._obj.value = next(codes)
            return True

        process.k.GetExitCodeProcess.side_effect = exit_code
        with patch.object(
            s.core, 'Process', return_value=process
        ), patch.object(
            s.ctypes, 'WinDLL', return_value=user
        ), patch.object(
            s, 'game_processes', side_effect=OSError('exiting image unavailable')
        ), patch.object(s.time, 'sleep'):
            s.close_game(game)
        user.PostMessageW.assert_called_once_with(456, 0x10, 0, 0)
        process.close.assert_called_once()


class StartupTests(TestCase):

    def test_immediate_exit_reports_code(self):
        process = Mock(pid=42)
        process.poll.return_value = 0xc0000005
        with patch.object(s, 'process_ready') as ready:
            with self.assertRaisesRegex(RuntimeError, '0xC0000005'):
                s.wait_for_start(process, Path('native-startup.exe'))
            ready.assert_not_called()
        process.kill.assert_not_called()

    def test_transient_window_is_not_success(self):
        process = Mock(pid=42)
        process.poll.side_effect = [None, 7]
        with patch.object(s, 'process_ready', return_value=True), patch.object(s.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'exited during startup'):
                s.wait_for_start(process, Path('native-startup.exe'))

    def test_two_ready_samples_succeed(self):
        process = Mock(pid=42)
        process.poll.return_value = None
        with patch.object(
            s, 'process_ready', side_effect=[False, True, False, True, True]
        ) as ready, patch.object(s.time, 'sleep'):
            self.assertEqual(s.wait_for_start(process, Path('native-startup.exe')), 42)
            self.assertEqual(ready.call_count, 5)

    def test_timeout_does_not_terminate_process(self):
        process = Mock(pid=42)
        process.poll.return_value = None
        with patch.object(s, 'process_ready', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'may still be running'):
                s.wait_for_start(process, Path('native-startup.exe'), timeout=0)
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_read_race_reports_exit(self):
        process = Mock(pid=42)
        process.poll.side_effect = [None, 9]
        with patch.object(
            s, 'process_ready', side_effect=OSError('process exited')
        ), patch.object(s.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, '0x00000009'):
                s.wait_for_start(process, Path('native-startup.exe'))

    def test_checkpoint_needs_restore_marker_and_presented_frame(self):
        memory = {0x1d1d000: 123, 0x1d1d018: 0, 0x181f004: 0}
        process = Mock()
        process.u.side_effect = memory.__getitem__
        with patch.object(s.core, 'Process', return_value=process):
            self.assertFalse(s.process_ready(42, Path('native-startup.exe')))
            memory[0x1d1d018] = 1
            self.assertTrue(s.process_ready(42, Path('native-startup.exe')))
            self.assertFalse(s.process_ready(42, Path('native-checkpoint.exe')))
            memory[0x181f004] = 0x43485054
            self.assertTrue(s.process_ready(42, Path('native-checkpoint.exe')))
        self.assertEqual(process.close.call_count, 4)

    def test_exact_read_race_reports_exit(self):
        process = Mock(pid=42)
        process.poll.side_effect = [None, 9, 9]
        with patch.object(s, 'process_ready', side_effect=ValueError('Cannot read memory')):
            with self.assertRaisesRegex(RuntimeError, '0x00000009'):
                s.wait_for_start(process, Path('native-startup.exe'))

    def test_live_process_validation_error_is_not_hidden(self):
        process = Mock(pid=42)
        process.poll.return_value = None
        with patch.object(s, 'process_ready', side_effect=ValueError('Wrong executable')):
            with self.assertRaisesRegex(ValueError, 'Wrong executable'):
                s.wait_for_start(process, Path('native-startup.exe'))


if __name__ == '__main__':
    main()
