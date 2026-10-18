"""Portable-installation sessions; no dependency on the engine reconstruction chain.

Only the selected installation's normal executable and generated checkpoint
executables are eligible. Snapshot integrity and live memory checks belong to
state_core; this layer owns selection, naming, locking and process launch.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import ctypes
from ctypes import wintypes
import json
import logging
import os
import re
import stat
import sys
import subprocess
import time
import uuid

from . import state_core as core


@dataclass(frozen=True)
class GameProcess:
    pid: int
    executable: Path


@dataclass(frozen=True)
class SavedState:
    folder: Path
    title: str
    campaign: str
    saved_at: str


def game_processes():
    """Enumerate image paths, without opening other games for memory access."""
    if os.name != 'nt':
        raise OSError('The development launcher requires Windows.')
    k = ctypes.WinDLL('kernel32', use_last_error=True)

    class Entry(ctypes.Structure):
        _fields_ = [
            ('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
            ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
            ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
            ('name', wintypes.WCHAR * 260)
        ]

    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ('Process32FirstW', 'Process32NextW'):
        fn = getattr(k, name)
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        fn.restype = wintypes.BOOL
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)
    ]
    k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    result = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.name.lower() in ('native-startup.exe', 'native-checkpoint.exe'):
                handle = k.OpenProcess(0x1000, False, entry.pid)
                if handle:
                    try:
                        size = wintypes.DWORD(32768)
                        text = ctypes.create_unicode_buffer(size.value)
                        if k.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(size)):
                            result.append(GameProcess(entry.pid, Path(text.value).resolve()))
                        else:
                            # A Toolhelp snapshot can retain a process that exits
                            # before its image path is queried. Ignore it only when
                            # this same open handle confirms termination.
                            code = wintypes.DWORD()
                            known_exit = k.GetExitCodeProcess(handle, ctypes.byref(code))
                            if not known_exit or code.value == 259:
                                raise OSError(
                                    'Could not identify a Terra Nova process; retry after it exits.'
                                )
                    finally:
                        k.CloseHandle(handle)
                elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
                    # The fixed access flags are valid. A snapshotted nonzero PID
                    # can disappear before OpenProcess; access failures still block.
                    raise OSError('Could not inspect a Terra Nova process; retry after it exits.')
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES; do not mistake a failed scan for no game.
            raise ctypes.WinError(error)
    finally:
        k.CloseHandle(snapshot)
    return result


def belongs_to(home, executable):
    home, executable = Path(home).resolve(), Path(executable).resolve()
    if executable == home / 'native-startup.exe':
        return True
    try:
        parts = executable.relative_to(home / 'state-runs').parts
    except ValueError:
        return False
    return len(parts) == 2 and parts[1].lower() == 'native-checkpoint.exe'


def read_small_json(path):
    if path.stat().st_size > 65536:
        raise ValueError('State description is too large.')
    return json.loads(path.read_text(encoding='utf-8'))


RUN_FILES = {
    'restore.json', 'native-checkpoint.exe', 'tn-checkpoint-audio.dll', 'services.bin',
    'stopped-memory.bin', 'framebuffer.bin', 'stdout.txt'
}


def plain_path(path, directory=False):
    """Do not traverse symlinks or Windows junction/reparse points."""
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    return (
        kind(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        and not getattr(info, 'st_file_attributes', 0) & 0x400
    )


def inspect_run(home, folder):
    """Recognize only flat, complete generated runs. Unknown contents stay put.

    This is a local housekeeping check, not authentication of untrusted files.
    Never follow the report path: campaign reports and saved states are excluded.
    """
    root = home / 'state-runs'
    if (
        not plain_path(root, directory=True) or root.resolve() != root
        or not re.fullmatch('[0-9a-f]{32}', folder.name) or folder.parent != root
        or not plain_path(folder, directory=True) or folder.resolve() != folder
    ):
        return None
    files = list(folder.iterdir())
    names = {p.name for p in files}
    if (
        not {'restore.json', 'native-checkpoint.exe', 'tn-checkpoint-audio.dll'} <= names <=
        RUN_FILES
    ):
        return None
    if any(not plain_path(p) or p.resolve().parent != folder for p in files):
        return None
    meta = read_small_json(folder / 'restore.json')
    profile = core.CONTRACTS.get(str(meta.get('revision')))
    if (
        not profile or meta.get('format') != 'tn-portable-restore-126'
        or meta.get('template') != profile['template']
        or meta.get('campaign') not in ('retail', 'prequel')
    ):
        return None
    for name, key in [
        ('native-checkpoint.exe', 'executable_sha256'), ('tn-checkpoint-audio.dll', 'audio_sha256')
    ]:
        if core.sha(folder / name) != meta.get(key):
            return None
    return dict(
        folder=folder,
        files=files,
        stamp=(folder / 'restore.json').stat().st_mtime_ns,
        fingerprint={p.name: (p.stat().st_size, p.stat().st_mtime_ns)
                     for p in files}
    )


def process_ready(pid, executable):
    """Require a presented game window, and completed restoration for snapshots."""
    process = core.Process(pid, executable)
    try:
        window = process.u(0x1d1d000)
        presented = process.u(0x1d1d018)
        restored = executable.name.lower(
        ) != 'native-checkpoint.exe' or process.u(0x181f004) == 0x43485054
        return bool(window and presented and restored)
    finally:
        process.close()


def wait_for_start(process, executable, timeout=20):
    """Report an early exit instead of treating successful Popen as startup.

    A timeout never kills a game: the player may still be waiting on Windows.
    Two ready samples avoid accepting a transient window during failed restore.
    """
    deadline = time.monotonic() + timeout
    ready = False
    while True:
        code = process.poll()
        if code is not None:
            raise RuntimeError(
                f'Terra Nova exited during startup (code 0x{code & 0xffffffff:08X}). '
                'Your saved state is unchanged. See launcher.log for details.'
            )
        try:
            current = process_ready(process.pid, executable)
        except OSError:
            current = False  # The process may have exited between poll and read.
        except ValueError:
            # Exact reads also fail if the process exits between the two calls.
            # Preserve identity/layout validation errors from a live process.
            if process.poll() is None:
                raise
            continue
        if ready and current and process.poll() is None:
            return process.pid
        ready = current
        if time.monotonic() >= deadline:
            raise RuntimeError(
                'Terra Nova has not finished starting. It may still be running; '
                'check its window and close it before trying again. Your saved state is unchanged.'
            )
        time.sleep(.1)


@contextmanager
def game_library_path():
    """Do not let the frozen launcher's DLL search folder leak into the game.

    PyInstaller documents SetDllDirectory inheritance on Windows. Restore the
    launcher's path immediately after process creation, including on failure.
    """
    if not getattr(sys, 'frozen', False):
        yield
        return
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    k.SetDllDirectoryW.restype = wintypes.BOOL
    if not k.SetDllDirectoryW(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not k.SetDllDirectoryW(sys._MEIPASS):
            raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def installation_lock(home):
    """Serialize launcher operations, including separate launcher windows."""
    import msvcrt
    lock_path = core.inside(home, '.launcher.lock')
    with lock_path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError('Another launcher operation is still running.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class Sessions:

    def __init__(self, home):
        self.home = Path(home).resolve()
        core.validate_home(self.home)
        if not (self.home / 'portable.json').is_file():
            raise ValueError('Choose an installation made by the portable setup.')

    def running(self):
        return [p for p in game_processes() if belongs_to(self.home, p.executable)]

    def require_closed(self):
        if self.running():
            raise ValueError(
                'Exit the game in this installation before starting or loading another game.'
            )

    def paused_prequel(self, expected=None):
        """Recheck process identity and a safe mission before a picker operation."""
        games = self.running()
        if len(games) != 1 or (expected is not None and games[0] != expected):
            raise ValueError(
                'The original game is no longer running. Close this picker and try again.'
            )
        game = games[0]
        process = core.Process(game.pid, game.executable)
        try:
            if (
                process.u(0x1fc0700) != 1 or process.read(0x35f3f4, 1) != b'\1'
                or process.u(0x9aa0ec) != 1 or process.u(0x1d0b000) != 0x103
            ):
                raise ValueError('Pause an active Prequel mission before using these controls.')
            core.validate_ui_state(core.Installation(self.home), process.read)
        finally:
            process.close()
        return game

    def states(self):
        """List descriptions only; full payload validation happens on Load."""
        root = core.inside(self.home, 'states')
        if not root.exists():
            return []
        rows = []
        for path in root.iterdir():
            if path.name.startswith('.') or not path.is_dir() or path.resolve().parent != root:
                continue
            try:
                meta = read_small_json(path / 'snapshot.json')
                if (
                    meta.get('format') != 'tn-portable-state-126'
                    or str(meta.get('revision')) not in core.CONTRACTS
                ):
                    continue
                campaign = meta['campaign']
                if campaign not in ('retail', 'prequel'):
                    continue
                label = read_small_json(path / 'label.json') if (path /
                                                                 'label.json').exists() else {}
                title = label.get('title', path.name)
                if not isinstance(title, str) or not title.strip():
                    title = path.name
                title = ''.join(c for c in title if c.isprintable())[:100]
                stamp = datetime.fromtimestamp(
                    (path / 'snapshot.json').stat().st_mtime, timezone.utc
                )
                rows.append(
                    SavedState(
                        path.resolve(), title, campaign, stamp.isoformat(timespec='seconds')
                    )
                )
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
        return sorted(rows, key=lambda s: (s.saved_at, s.folder.name), reverse=True)

    def prepare(self, install):
        """Prepare the fixed entry point, retaining relocation for older builds."""
        exe = core.inside(self.home, 'native-startup.exe')
        if exe.exists() and exe.read_bytes() == install.startup_image:
            return exe
        temp = core.inside(self.home, '.launch-' + uuid.uuid4().hex + '.tmp')
        try:
            temp.write_bytes(install.startup_image)
            self.require_closed()
            os.replace(temp, exe)
        finally:
            temp.unlink(missing_ok=True)
        return exe

    def launch(self, executable):
        self.require_closed()
        with game_library_path():
            process = subprocess.Popen(
                [str(executable)], cwd=self.home, creationflags=subprocess.CREATE_NO_WINDOW
            )
        return wait_for_start(process, Path(executable))

    def prune_runs(self, protect=None, dry_run=False):
        """Called under installation_lock, with the game closed, before launch.

        Retain the latest two recognized runs for diagnosis. No recursive delete,
        no writes outside state-runs, no guesses about partial/modified folders.
        A cleanup failure is logged and does not prevent playing.
        """
        self.require_closed()
        result = dict(removed=[], bytes_reclaimed=0, skipped=[], errors=[], candidates=[])
        root = self.home / 'state-runs'
        if not root.exists():
            return result
        try:
            if not plain_path(root, directory=True) or root.resolve() != root:
                result['skipped'].append(str(root))
                return result
            runs = []
            for folder in root.iterdir():
                try:
                    row = inspect_run(self.home, folder)
                except (OSError, ValueError, TypeError, AttributeError):
                    row = None
                if row:
                    runs.append(row)
                else:
                    result['skipped'].append(folder.name)
            # Always retain the executable about to launch, even if the system
            # clock moved backwards or older files have future timestamps.
            runs.sort(
                key=lambda r: (r['folder'] == protect, r['stamp'], r['folder'].name), reverse=True
            )
            for row in runs[2:]:
                result['candidates'].append(row['folder'].name)
                if dry_run:
                    continue
                self.require_closed()
                try:
                    current = inspect_run(self.home, row['folder'])
                    if not current or current['fingerprint'] != row['fingerprint']:
                        result['skipped'].append(row['folder'].name)
                        continue
                    # Paths have been resolved and checked within this exact root.
                    # Leave restore.json until last to aid diagnosis of I/O failure.
                    for path in sorted(current['files'], key=lambda p: p.name == 'restore.json'):
                        size = path.stat().st_size
                        path.unlink()
                        result['bytes_reclaimed'] += size
                    row['folder'].rmdir()
                    result['removed'].append(row['folder'].name)
                except (OSError, ValueError, TypeError, AttributeError) as exc:
                    result['errors'].append(f"{row['folder'].name}: {exc}")
        except OSError as exc:
            result['errors'].append(str(exc))
        logging.getLogger(__name__).info('Restore run cleanup: %s', result)
        return result

    def play(self):
        with installation_lock(self.home):
            self.require_closed()
            install = core.Installation(self.home)
            executable = self.prepare(install)
            self.prune_runs()
            return self.launch(executable)

    def save(self, title, expected=None):
        if (
            not isinstance(title, str) or len(title) > 100
            or any(not c.isprintable() for c in title)
        ):
            raise ValueError('Use a name of up to 100 ordinary characters.')
        with installation_lock(self.home):
            if expected is not None:
                self.paused_prequel(expected)
            games = self.running()
            if len(games) != 1:
                raise ValueError(
                    'Run exactly one game in this installation, then pause it during a mission.'
                )
            install = core.Installation(self.home)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
            folder = core.inside(self.home, 'states/' + stamp + '-' + uuid.uuid4().hex[:8])
            exe = games[0].executable.relative_to(self.home).as_posix()
            result = core.capture(install, games[0].pid, folder, executable=exe)
            # The valid snapshot remains listed by folder name even if label writing fails.
            core.save_json(folder / 'label.json', {'title': title.strip() or 'Saved game'})
            return result

    def load_in_game(self, folder, expected):
        """Prepare a validated restore before requesting this game's normal close.

        No termination fallback. A failed validation/build leaves the paused game
        alone. A failed startup leaves the source state and prepared run intact.
        """
        folder = Path(folder).resolve()
        rows = {row.folder: row for row in self.states() if row.campaign == 'prequel'}
        if folder not in rows:
            raise ValueError('Choose a Prequel saved state from this installation.')
        with installation_lock(self.home):
            self.paused_prequel(expected)
            install = core.Installation(self.home)
            destination = core.inside(self.home, 'state-runs/' + uuid.uuid4().hex)
            result = core.build_restore(install, folder, destination, 'prequel')
            self.paused_prequel(expected)
            close_game(expected)
            self.require_closed()
            self.prune_runs(protect=destination)
            return dict(result, pid=self.launch(Path(result['executable'])))

    def load(self, folder):
        folder = Path(folder).resolve()
        rows = {row.folder: row for row in self.states()}
        if folder not in rows:
            raise ValueError('Choose a saved state from this installation.')
        with installation_lock(self.home):
            self.require_closed()
            install = core.Installation(self.home)
            self.prepare(install)
            destination = core.inside(self.home, 'state-runs/' + uuid.uuid4().hex)
            result = core.build_restore(install, folder, destination, rows[folder].campaign)
            self.prune_runs(protect=destination)
            return dict(result, pid=self.launch(Path(result['executable'])))


def close_game(game, timeout=15):
    """WM_CLOSE on a freshly verified window; wait without force-killing anything."""
    process = core.Process(game.pid, game.executable)
    try:
        window = process.u(0x1d1d000)
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowThreadProcessId.restype = wintypes.DWORD
        user.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user.PostMessageW.restype = wintypes.BOOL
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value != game.pid:
            raise ValueError('The current game window changed; load was cancelled.')
        if not user.PostMessageW(window, 0x10, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        # Keep the verified process handle. Enumerating image paths while that
        # very process exits races QueryFullProcessImageName and reports a false
        # failure. Its exit code remains queryable through this held handle.
        process.k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        process.k.GetExitCodeProcess.restype = wintypes.BOOL
        deadline = time.monotonic() + timeout
        while True:
            code = wintypes.DWORD()
            if not process.k.GetExitCodeProcess(process.h, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            if code.value != 259:  # STILL_ACTIVE
                break
            if time.monotonic() >= deadline:
                raise ValueError(
                    'The game did not close. Your saved state is unchanged; close the game before retrying.'
                )
            time.sleep(.1)
    finally:
        process.close()
