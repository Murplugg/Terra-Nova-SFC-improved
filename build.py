"""One documented entry point for the reproducible engine/setup build."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / 'engine'))
from feature_plan import REVISION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-root', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--local-generation', action='store_true', default=True,
                        help='Build a setup that generates game outputs on the player machine')
    parser.add_argument(
        '--launcher-python',
        type=Path,
        help='Isolated Windows x64 CPython 3.12 with requirements-launcher.txt'
    )
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('Python -O disables required checks')
    output = args.output.resolve()
    if output.is_relative_to(PROJECT) or PROJECT.is_relative_to(output):
        parser.error('Choose a build folder outside the source checkout')
    command = [sys.executable, '-B', str(PROJECT / 'engine/release_package.py')]
    for key, value in vars(args).items():
        if key == 'launcher_python':
            continue
        if isinstance(value, bool):
            if value:
                command.append('--' + key.replace('_', '-'))
            continue
        command.extend(
            [
                '--' + key.replace('_', '-'),
                str(value.resolve() if isinstance(value, Path) else value)
            ]
        )
    subprocess.run(command, check=True)
    generated = output / 'engine/snapshot-layout.json'
    accepted = PROJECT / 'tnova/state-layout.json'
    expected = json.loads(accepted.read_text())
    expected['revision'] = REVISION
    if json.loads(generated.read_text()) != expected:
        raise ValueError('Generated snapshot declarations differ from the launcher contract')
    report = dict(
        game_revision=REVISION,
        setup_milestone=REVISION,
        project_milestone=REVISION,
        snapshot_layout_derived=True,
        snapshot_layout_sha256=hashlib.sha256(generated.read_bytes()).hexdigest(),
        launcher_in_setup_zip=False
    )
    report['engine_build_mode'] = json.loads((output / 'build.json').read_text()
                                             )['engine_build_mode']
    if args.launcher_python:
        from build_launcher import attach
        subprocess.run(
            [
                str(args.launcher_python.resolve()), '-B',
                str(PROJECT / 'build_launcher.py'), '--output',
                str(output / 'launcher')
            ],
            check=True
        )
        report.update(attach(output, output / 'launcher/dist/Terra Nova Launcher'))
        report.update(setup_milestone=REVISION, project_milestone=REVISION, launcher_in_setup_zip=True)
    (output / 'project-build.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8'
    )
    print(
        'Engine/setup build and generated snapshot layout verified. Bundled launcher: ' +
        str(bool(args.launcher_python))
    )


if __name__ == '__main__':
    main()
