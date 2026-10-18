"""Build the Windows x64 launcher bundle; optionally attach it to a setup.

Run in an isolated CPython 3.12 environment with requirements-launcher.txt.
The game contract is deliberately unchanged: launcher payloads are checked by
the installer, but do not become captured game assets in portable.json.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile

PROJECT = Path(__file__).resolve().parent
NAME = 'Terra Nova Launcher'
# Public release label; game_revision separately identifies compatible snapshots.
RELEASE_VERSION = '0.1.0'
LIBFFI_URL = (
    'https://raw.githubusercontent.com/python/cpython-bin-deps/'
    '94cb9a1c7feb608adf2b9f8fe2dbd6925ffbf90d/amd64/libffi-8.dll'
)
LIBFFI_SHA256 = 'eff52743773eb550fcc6ce3efc37c85724502233b6b002a35496d828bd7b280a'


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def libffi_input(output, supplied=None):
    """Use CPython's published Windows x64 dependency, with verified provenance.

    A local copy supports offline builds. Otherwise fetch the immutable upstream
    file into this build directory. Never modify the developer's Python runtime.
    """
    if supplied is None:
        with urllib.request.urlopen(LIBFFI_URL, timeout=30) as response:
            data = response.read()
    else:
        data = Path(supplied).read_bytes()
    if hashlib.sha256(data).hexdigest() != LIBFFI_SHA256:
        raise ValueError('libffi differs from the reviewed CPython dependency')
    target = output / 'libffi-8.dll'
    target.write_bytes(data)
    return target


def build(output, libffi=None):
    output = output.resolve()
    if os.name != 'nt' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
        raise ValueError('Build the launcher with Windows x64 CPython 3.12.')
    if output.exists() or output.is_relative_to(PROJECT) or PROJECT.is_relative_to(output):
        raise ValueError('Choose a new launcher build folder outside the source project.')
    versions = {}
    for line in (PROJECT / 'requirements-launcher.txt').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, version = line.split('==')
        if metadata.version(name) != version:
            raise ValueError('Launcher build dependency differs: ' + name)
        versions[name] = version
    output.mkdir(parents=True)
    ffi = libffi_input(output, libffi)
    command = [
        sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
        '--noupx', '--name', NAME, '--contents-directory', '_launcher', '--distpath',
        str(output / 'dist'), '--workpath',
        str(output / 'work'), '--specpath',
        str(output), '--paths',
        str(PROJECT), '--additional-hooks-dir',
        str(PROJECT / 'launcher-hooks'), '--collect-binaries', 'keystone', '--exclude-module',
        'pytest', '--exclude-module', 'numpy', '--exclude-module', 'capstone',
        # Snapshots store raw files and JSON. LZMA is an optional stdlib import
        # discovered through generic archive support and is unused by the launcher.
        '--exclude-module', '_lzma', '--add-data',
        f'{PROJECT / "tnova/state-layout.json"}:tnova', '--add-data',
        f'{PROJECT / "tnova/state-contracts.json"}:tnova',
        str(PROJECT / 'launcher.py')
    ]
    env = dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    # Binary discovery must use this Python distribution and Windows itself.
    # An inherited PATH can otherwise pull unrelated application DLLs into the
    # bundle, making both dependency provenance and clean-machine use uncertain.
    windows = Path(os.environ['SystemRoot'])
    env['PATH'] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix),
        Path(sys.base_prefix) / 'DLLs', windows / 'System32', windows,
    )))
    done = subprocess.run(command, cwd=output, env=env, capture_output=True, text=True)
    (output / 'freeze.log').write_text(done.stdout + done.stderr, encoding='utf-8')
    if done.returncode:
        raise ValueError('Launcher freezing failed; see ' + str(output / 'freeze.log'))
    bundle = output / 'dist' / NAME
    # CPython 3.12 uses this ABI. Select the reviewed upstream build instead of
    # inheriting an unidentifiable libffi from the developer's Python package.
    shutil.copyfile(ffi, bundle / '_launcher/libffi-8.dll')
    notices = bundle / '_launcher/licenses'
    notices.mkdir()
    shutil.copyfile(Path(sys.base_prefix) / 'LICENSE.txt', notices / 'Python.txt')
    shutil.copyfile(Path(sys.base_prefix) / 'tcl/tk8.6/license.terms', notices / 'Tk.txt')
    for package in ('pyinstaller', 'keystone-engine'):
        dist = metadata.distribution(package)
        for file in dist.files:
            if file.name.lower() in ('license.txt', 'copying.txt'):
                shutil.copyfile(dist.locate_file(file), notices / (package + '-' + file.name))
    shutil.copyfile(PROJECT / 'docs/launcher-third-party.txt', notices / 'launcher-third-party.txt')
    shutil.copyfile(PROJECT / 'LICENSE', notices / 'project-LICENSE.txt')
    files = {
        p.relative_to(bundle).as_posix(): digest(p)
        for p in sorted(bundle.rglob('*')) if p.is_file()
    }
    report = dict(
        schema=1,
        milestone=136,
        python=sys.version,
        platform=sys.platform,
        dependencies=versions,
        libffi=dict(version='3.4.4', url=LIBFFI_URL, sha256=LIBFFI_SHA256),
        files=files,
        bytes=sum((bundle / n).stat().st_size for n in files),
        executable=NAME + '.exe',
        runtime_folder='_launcher',
        windows_x64=True
    )
    (bundle / 'launcher-bundle.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8'
    )
    return bundle


def attach(build_root, bundle):
    """Add checked launcher outputs to a freshly built setup package."""
    build_root, bundle = build_root.resolve(), bundle.resolve()
    package = build_root / 'package'
    manifest_path = package / 'install.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    # Package compatibility follows its format and matching engine/setup identity.
    # A list of old build numbers rejects later valid builds before bundling.
    revision = manifest.get('game_revision')
    if (manifest.get('schema') not in (2, 3) or type(revision) is not int or revision <= 0
            or manifest.get('installer_revision') != revision):
        raise ValueError('Expected a supported unbundled setup package.')
    local_generation = manifest['schema'] == 3
    if local_generation and (manifest.get('generation', {}).get('schema') != 1
                             or any(r['kind'] == 'delta' for r in manifest['outputs'])
                             or not any(r['kind'] == 'generated' for r in manifest['outputs'])):
        raise ValueError('Expected local generators in place of prepared deltas.')
    for name, expected in manifest['package_files'].items():
        path = (package / name).resolve()
        if not path.is_relative_to(package) or digest(path) != expected:
            raise ValueError('Setup changed before launcher attachment: ' + name)
    info = json.loads((bundle / 'launcher-bundle.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    if actual != set(info['files']) | {'launcher-bundle.json'}:
        raise ValueError('Unexpected or missing launcher bundle files.')
    for name, expected in info['files'].items():
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle) or digest(path) != expected:
            raise ValueError('Launcher bundle changed: ' + name)
    old_paths = {row['path'] for row in manifest['outputs']}
    if old_paths & actual:
        raise ValueError('Launcher output overlaps existing game files.')
    revision = manifest['game_revision']
    milestone = max(136, revision)
    suffix = '-launcher' if milestone == manifest['installer_revision'] else ''
    if local_generation:
        suffix += '-local-generation'
    archive = build_root / f'TerraNova-native-v{revision}-setup{milestone}{suffix}.zip'
    if archive.exists():
        raise ValueError('Bundled setup archive already exists.')

    def payload(name, data):
        path = package / 'payload' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest['outputs'] = [row for row in manifest['outputs'] if row['path'] != name]
        manifest['outputs'].append(
            dict(
                path=name,
                kind='payload',
                payload='payload/' + name,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest()
            )
        )

    for name in sorted(actual):
        payload(name, (bundle / name).read_bytes())
    payload('Play.cmd', b'@echo off\r\nstart "" "%~dp0Terra Nova Launcher.exe"\r\n')
    revision = manifest['game_revision']
    switching = 'Prequel switches campaigns in the same game window.' if revision >= 138 else 'Prequel still restarts the game process.'
    release_label = 'Public test candidate.'
    payload(
        'README.txt', f'''TNova Native v{RELEASE_VERSION} with portable launcher.
Snapshot compatibility build: {revision}.
Open Play.cmd or Terra Nova Launcher.exe. Keep _launcher and the rest of this folder together.
Windows 10/11 x64; no installed Python or compiler is needed to play or save/load states.
Play opens the retail main menu, including Prequel. In a paused Prequel mission, F5 opens
Save and F9 opens Load. Loading restarts the window; each save keeps a separate state.
You can also pause during a mission, switch to
the launcher and Save paused game. Exit the game before Load selected state.
States live under states/. Ordinary campaign saves remain under retail/. Load only
your own trusted states, and use the matching game revision shown by the launcher.
Older generated restore runs are pruned; the two newest recognized runs are kept.
Campaign reports and saved states are never automatically removed.
Unchanged resource files may share disk storage with originals or other installations.
Treat those assets as read-only; use --data-mode copy during setup before editing them.
Saves, settings and generated resources remain independent.
Move the entire installation only while the game and launcher are closed.
Use an ASCII installation path of at most 115 characters. Original input paths may contain Unicode. {switching}
Launch.ps1 remains a direct-play diagnostic fallback; it does not provide state controls.
Licenses are in _launcher/licenses/. Microsoft runtime use and redistribution are
subject to Python.txt's Windows binary-build conditions. Distributors must provide
the matching TerraNova-native-source.zip alongside this player package; see the
third-party notices for source contents and component terms.
{release_label} Tested on the development Windows 10 laptop; a clean
Windows installation and other hardware remain unverified. See the release notes.
'''.encode()
    )
    setup_tools = 'Python 3.11+'
    setup_arguments = ''
    setup_content = 'patches, native support and a portable launcher runtime'
    setup_note = ''
    if local_generation:
        setup_tools = '64-bit Windows CPython 3.12'
        setup_arguments = ' --tools-cache "C:\\TNovaTools"'
        setup_content = 'local generators, native support and a portable launcher runtime'
        setup_note = ('No prepared game/resource deltas are included. --check-only also runs\n'
                      'and verifies local generation. Tools download about 95 MB once and stay\n'
                      'in the chosen folder; allow about 700 MB for tools and temporary work.\n'
                      'Nothing is installed globally. For offline setup add --tool-downloads\n'
                      'with the three official archives named in generation/generation_tools.py.\n'
                      'Existing tools may instead use --compiler and --dependencies.\n'
                      'The tools folder is not needed to play the installed game.\n')
    readme = f'''TNova Native v{RELEASE_VERSION} - portable setup ZIP

This ZIP contains {setup_content}, not a complete game.
One-time setup requires {setup_tools} and the supported English retail v1.09 files,
both demos and the original CD ISO. Setup verifies hashes and leaves originals untouched.
Use --original for the root containing TNOVA, TNDEMO1, TNDEMO2 and _ISO, or select
separate locations with --retail, --download-demo, --cd-demo and --cd-image.
Folder options point to the contents of TNOVA/TNDEMO1/TNDEMO2; --cd-image is a file.
Options may override individual locations beneath --original. No search or conversion
is performed: the same supported English editions and exact hashes are required.

Extract this ZIP, then double-click Setup.cmd. The setup window lets you browse
for each original folder, the CD ISO, a new game folder and the tools folder.
Use 64-bit Windows CPython 3.12 with Tcl/Tk and the Python launcher installed.
Setup shows the current stage and offers an error log if it cannot finish.
After completion, click Open game folder and start Terra Nova Launcher.exe.

Alternatively, run from the extracted folder:
python -B install_portable.py --original "C:\\path\\to\\originals" --destination "C:\\Games\\TNovaNative"{setup_arguments}

{setup_note}

Unchanged assets share disk storage through hard links where supported. CD-only
files are extracted once into TNova-shared-data beside the installation; choose
another cache with --data-cache PATH. Saves/settings/generated files remain private.
Use --data-mode copy for independent resource copies. Treat shared files as read-only;
editing one linked name changes the others. Moving/deleting originals or the cache
does not break existing links. Cross-volume/unsupported links fall back to copies;
setup reports their storage cost. Explorer may still show full logical folder size.

Choose a new separate destination. Add --check-only to generate and verify without installing.
Existing destinations are never overwritten. No administrator installation,
registry registration or uninstaller is involved.

After setup, open Play.cmd or Terra Nova Launcher.exe in the destination.
Windows 10/11 x64; playing and saving/loading paused states require no installed
Python or compiler. Keep _launcher/ and all other installed files together.
Close both the launcher and game before moving the installation.
Campaign saves are local; existing progress is not imported automatically.
Mission snapshots are separate from ordinary saves. Load only your own trusted
states with the matching game build. See the installed README for controls.

Component licenses are in payload/_launcher/licenses/ and remain in the installation.
Microsoft runtime use and redistribution are subject to the Windows binary-build
conditions in Python.txt. Distributors must provide the matching
TerraNova-native-source.zip alongside the player download from the same release
location. It includes launcher sources and Keystone's upstream source archive.

Current limits: exact supported input hashes; ASCII destination (at most 115 characters),
build-specific snapshots. {switching} This is a public test candidate, tested
on the development Windows 10 laptop. Clean Windows installation and broader
hardware compatibility remain unverified. See the release notes for gameplay limits.
'''
    (package / 'README.txt').write_text(readme, encoding='utf-8')
    manifest['installer_revision'] = milestone
    manifest['outputs'].sort(key=lambda row: row['path'])
    manifest['package_files'] = {
        p.relative_to(package).as_posix(): digest(p)
        for p in sorted(package.rglob('*')) if p.is_file() and p != manifest_path
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(package.rglob('*')):
            if not path.is_file():
                continue
            entry = zipfile.ZipInfo(path.relative_to(package).as_posix(), (2026, 10, 8, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            z.writestr(entry, path.read_bytes())
    return dict(
        archive=str(archive),
        sha256=digest(archive),
        bytes=archive.stat().st_size,
        launcher_files=len(actual),
        launcher_bytes=info['bytes'],
        outputs=len(manifest['outputs'])
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--libffi', type=Path, help='Verified upstream DLL for an offline build')
    args = parser.parse_args()
    print(build(args.output, args.libffi))


if __name__ == '__main__':
    main()
