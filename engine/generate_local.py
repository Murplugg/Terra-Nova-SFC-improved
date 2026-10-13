"""Generate the native image and edited resources on the owner's machine.

This entry point uses the same generators as the contributor build. It needs
only ten original files, the independent Windows bridge and the pinned build
tools. It never reads a prepared game delta or copies an entire installation.
The final eight outputs must match the selected, playtested release exactly.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from build_support import verify_sources
from install_portable import child

KIT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def required_inputs(kit=KIT):
    """Keep setup's input contract tied to the maintained release recipes."""
    resources = json.loads((kit / 'resource-manifest.json').read_text(encoding='utf-8'))
    release = json.loads((kit / 'release-recipe.json').read_text(encoding='utf-8'))
    names = set(resources['inputs']) | {
        'TNOVA/__FF.EXE', 'TNOVA/DATA/RESTNOBJ.RES', 'TNDEMO2/_SETUP/__FF.EXE'
    }
    result = {}
    for name in sorted(names):
        if name == 'TNDEMO2/_SETUP/__FF.EXE':
            from feature_plan import DEMO_SHA
            expected = dict(size=1855141, sha256=DEMO_SHA)
        else:
            expected = {key: release['inputs'][name][key] for key in ('size', 'sha256')}
        if name in resources['inputs'] and expected != resources['inputs'][name]:
            raise ValueError('Conflicting original-input recipes: ' + name)
        result[name] = expected
    return result


def checked_inputs(folders, expected):
    """Read and check every generation input before creating a work folder."""
    result = {}
    for name, row in expected.items():
        prefix, _, tail = name.partition('/')
        if prefix not in folders:
            raise ValueError('Missing original location: ' + prefix)
        raw = child(folders[prefix], tail).read_bytes()
        if len(raw) != row['size'] or sha(raw) != row['sha256']:
            raise ValueError('Unsupported generation input: ' + name)
        result[name] = raw
    return result


def generate(retail, cd_demo, bridge, compiler, dependencies, output, *,
             tools_cache=None, tool_downloads=None):
    if sys.flags.optimize:
        raise ValueError('Python -O disables required generation checks')
    retail, cd_demo, bridge, output = (
        Path(p).resolve() for p in (retail, cd_demo, bridge, output)
    )
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output)
                              for p in (KIT, retail, cd_demo, bridge)):
        raise ValueError('Generation output must be new and separate from all inputs')
    verify_sources()
    if tools_cache is not None:
        cache = Path(tools_cache).resolve()
        if compiler is not None or dependencies is not None:
            raise ValueError('Choose --tools-cache or explicit compiler/dependencies')
        if any(cache.is_relative_to(p) or p.is_relative_to(cache)
               for p in (KIT, retail, cd_demo, bridge, output)):
            raise ValueError('Keep tools separate from original files, setup and generation output')
        # Verify the originals first, before downloading or preparing any tools.
        checked_inputs({'TNOVA': retail, 'TNDEMO2': cd_demo}, required_inputs())
        from generation_tools import prepare
        compiler, dependencies = prepare(cache, tool_downloads)
    elif tool_downloads is not None:
        raise ValueError('--tool-downloads requires --tools-cache')
    if compiler is None or dependencies is None:
        raise ValueError('Specify --tools-cache or both --compiler and --dependencies')
    compiler, dependencies = Path(compiler).resolve(), Path(dependencies).resolve()
    protected = [KIT, retail, cd_demo, bridge, compiler.parent, dependencies]
    if output.exists() or any(
        output.is_relative_to(p) or p.is_relative_to(output) for p in protected
    ):
        raise ValueError('Generation output must be new and separate from all inputs')
    recipe = json.loads((KIT / 'release-recipe.json').read_text(encoding='utf-8'))
    if sha(compiler.read_bytes()) != recipe['compiler_sha256']:
        raise ValueError('Compiler differs from the pinned version')
    from build_bridge import normalized, EXPECTED_NORMALIZED
    normalized_bridge, _ = normalized(bridge.read_bytes())
    if sha(normalized_bridge) != EXPECTED_NORMALIZED:
        raise ValueError('Windows bridge code/data differs')
    expected = required_inputs()
    inputs = checked_inputs({'TNOVA': retail, 'TNDEMO2': cd_demo}, expected)
    output.mkdir(parents=True)
    # The resource generator retains its established input layout. Stage only
    # its declared files; movies, sounds, maps and saved games are never copied.
    originals = output / 'inputs'
    for name, raw in inputs.items():
        path = child(originals, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def run(script, arguments):
        command = [sys.executable, '-B', str(KIT / script), *map(str, arguments)]
        result = subprocess.run(command, cwd=output, capture_output=True, text=True)
        (output / (Path(script).stem + '.log')).write_text(
            result.stdout + result.stderr, encoding='utf-8'
        )
        if result.returncode:
            raise ValueError('Local generation failed: ' + script + '\n' + result.stderr)
        print(script + ': generated locally', flush=True)

    run('build_engine.py', [
        '--original', originals / 'TNOVA/__FF.EXE',
        '--demo-executable', originals / 'TNDEMO2/_SETUP/__FF.EXE',
        '--mesh-archive', originals / 'TNOVA/DATA/RESTNOBJ.RES',
        '--audio', bridge, '--compiler', compiler, '--dependencies', dependencies,
        '--output', output / 'engine',
    ])
    run('build_resources.py', ['--original-root', originals, '--output', output / 'resources'])
    from package_core import template
    generated = {'native-template.bin': template(
        (output / 'engine/native-chain.exe').read_bytes(), recipe
    )}
    for row in recipe['deltas']:
        name = row['path']
        if name not in generated:
            generated[name] = child(output / 'resources', name).read_bytes()
        raw = generated[name]
        if len(raw) != row['size'] or sha(raw) != row['sha256']:
            raise ValueError('Locally generated output differs: ' + name)
    for name, raw in generated.items():
        path = child(output / 'generated', name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    report = dict(
        schema=1,
        game_revision=recipe['game_revision'],
        mode='local-generators',
        inputs=expected,
        staged_input_bytes=sum(map(len, inputs.values())),
        outputs={name: dict(size=len(raw), sha256=sha(raw)) for name, raw in generated.items()},
        compiler_sha256=recipe['compiler_sha256'],
        bridge_sha256=sha(normalized_bridge),
        prepared_game_deltas_used=False,
        originals_modified=False,
    )
    (output / 'generation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('All eight local outputs match the selected release.', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('retail', 'cd-demo', 'bridge', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('compiler', 'dependencies', 'tools-cache', 'tool-downloads'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    generate(args.retail, args.cd_demo, args.bridge, args.compiler, args.dependencies, args.output,
             tools_cache=args.tools_cache, tool_downloads=args.tool_downloads)


if __name__ == '__main__':
    main()
