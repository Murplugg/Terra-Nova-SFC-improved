"""Build the current engine, resources and portable setup ZIP."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_support import install_audit, verify_sources
from package_core import package, sha

KIT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original-root', 'compiler', 'dependencies', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--local-generation', action='store_true', default=True,
                        help='Ship generators in place of game/resource deltas')
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('Python -O disables required checks')
    original, compiler, deps, out = (
        args.original_root.resolve(),
        args.compiler.resolve(),
        args.dependencies.resolve(),
        args.output.resolve(),
    )
    if (
        out.exists() or any(
            p.is_relative_to(out) or out.is_relative_to(p)
            for p in (original, KIT, deps, compiler.parent)
        )
    ):
        raise ValueError('Output must be new and separate from inputs')
    accesses = install_audit(
        [KIT, KIT.parent / 'source-export.json', original, compiler, out, deps,
         Path(sys.base_prefix),
         Path(sys.prefix)]
    )
    verify_sources()
    recipe = json.loads((KIT / 'release-recipe.json').read_text(encoding='utf-8'))
    if sha(compiler.read_bytes()) != recipe['compiler_sha256']:
        raise ValueError('Compiler differs from pinned version')
    out.mkdir(parents=True)

    def run(name, arguments):
        result = subprocess.run(
            [sys.executable, '-B', str(KIT / name), *map(str, arguments)],
            cwd=out,
            capture_output=True,
            text=True,
        )
        (out / (Path(name).stem + '.log')).write_text(
            result.stdout + result.stderr, encoding='utf-8'
        )
        if result.returncode:
            raise ValueError(name + ' failed:\n' + result.stderr)
        print(name + ': passed', flush=True)

    run(
        'build_bridge.py',
        ['--zig', compiler, '--source', KIT / 'bridge', '--destination', out / 'bridge']
    )
    run(
        'build_engine.py', [
            '--original',
            original / 'TNOVA/__FF.EXE',
            '--demo-executable',
            original / 'TNDEMO2/_SETUP/__FF.EXE',
            '--mesh-archive',
            original / 'TNOVA/DATA/RESTNOBJ.RES',
            '--audio',
            out / 'bridge/tn-audio.dll',
            '--compiler',
            compiler,
            '--dependencies',
            deps,
            '--output',
            out / 'engine',
            '--patch-audit',
        ]
    )
    run('build_resources.py', ['--original-root', original, '--output', out / 'resources'])
    report = package(original, out, recipe, local_generation=args.local_generation)
    report.update(engine_build_mode='named-features', accessed_files=sorted(accesses))
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Portable setup verified: ' + report['zip_sha256'])


if __name__ == '__main__':
    main()
