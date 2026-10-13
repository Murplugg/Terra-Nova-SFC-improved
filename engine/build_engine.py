"""Build the current native engine from verified originals and named features."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from build_support import DOS_SHA, ORIGINAL_SHA, install_audit, validate_layout, verify_sources

KIT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(args):
    if sys.flags.optimize:
        raise ValueError('Python -O disables required build checks')
    output = args.output.resolve()
    original = args.original.resolve()
    audio = args.audio.resolve()
    demo = args.demo_executable.resolve()
    mesh = args.mesh_archive.resolve()
    compiler = args.compiler.resolve()
    inputs = [KIT, original, audio, demo, mesh, compiler]
    if output.exists() or any(p.is_relative_to(output) or output.is_relative_to(p) for p in inputs):
        raise ValueError('Output must be new and separate from all inputs')
    allowed = inputs + [output, Path(sys.base_prefix), Path(sys.prefix)]
    if args.dependencies:
        dependencies = args.dependencies.resolve()
        allowed.append(dependencies)
        sys.path.insert(0, str(dependencies))
    accesses = install_audit(allowed)
    manifest = verify_sources()
    import capstone
    import keystone
    versions = {'capstone': capstone.__version__, 'keystone-engine': keystone.__version__}
    if versions != manifest['tool_versions']:
        raise ValueError('Unexpected assembler/disassembler versions')

    from feature_plan import DEMO_SHA, REVISION
    data = original.read_bytes()
    demo_data = demo.read_bytes()
    bridge = audio.read_bytes()
    if sha(data) != ORIGINAL_SHA or sha(demo_data) != DEMO_SHA:
        raise ValueError('Unsupported retail or CD demo executable')
    if not bridge.startswith(b'MZ'):
        raise ValueError('Invalid audio/display bridge')

    import original_inputs
    import build_paths
    import native_host
    import patch_engine
    from build_helpers import compile_helpers, register_modules
    from feature_build import emit
    from export_snapshot_layout import export
    from patch_audit import PatchAudit

    original_inputs.initialize(data)
    original_inputs.initialize_demo(demo_data)
    generated, helpers = compile_helpers(KIT, compiler, output / 'helpers', mesh)
    register_modules(generated)
    config = validate_layout(
        json.loads((KIT / 'reference-layout.json').read_text(encoding='utf-8'))
    )
    build_paths.CONFIG.update(config)
    le, _ = patch_engine.make(data)
    if sha(le) != DOS_SHA:
        raise ValueError('Relocatable foundation mismatch')
    foundation = native_host.build(le, config)
    audit = PatchAudit() if args.patch_audit else None
    contract, details = {}, {}
    executable, groups = emit(
        foundation,
        progress=lambda row: print(f'{row["feature"]}: built', flush=True),
        audit=audit,
        runtime_contract=contract,
        report=details,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / 'native-chain.exe').write_bytes(executable)
    export(output / 'snapshot-layout.json', REVISION, contract=contract['snapshot'])
    (output / 'tn-audio.dll').write_bytes(bridge)
    report = dict(
        scope='Current native engine from original inputs and named features',
        original_sha256=sha(data),
        demo_executable_sha256=sha(demo_data),
        foundation_sha256=sha(foundation),
        executable_sha256=sha(executable),
        audio_sha256=sha(bridge),
        compiled_helpers=helpers,
        source_files=len(manifest['files']),
        tool_versions=versions,
        feature_groups=groups,
        named_features=details,
        accessed_files=sorted(accesses),
    )
    (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if audit:
        (output / 'patch-audit.json').write_text(
            json.dumps(audit.report(), indent=2) + '\n', encoding='utf-8'
        )
    print('Engine verified: ' + sha(executable))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'demo-executable', 'mesh-archive', 'audio', 'compiler', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--dependencies', type=Path)
    parser.add_argument('--patch-audit', action='store_true')
    build(parser.parse_args())


if __name__ == '__main__':
    main()
