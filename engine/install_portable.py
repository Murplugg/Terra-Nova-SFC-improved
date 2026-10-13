"""Offline original-input installer for the selected hash-pinned package."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, uuid
from package_delta import decode, delta_basis


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def child(root, rel):
    path = PurePosixPath(rel)
    if (
        not rel or '\\' in rel or ':' in rel or path.is_absolute()
        or any(x in ('', '.', '..') for x in rel.split('/'))
    ):
        raise ValueError('Unsafe package path: ' + rel)
    result = (root / Path(*path.parts)).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError('Path escapes selected folder: ' + rel)
    return result


def source_locations(original, retail=None, download_demo=None, cd_demo=None, cd_image=None):
    """Explicit locations only: never search other folders or relax input hashes."""
    root = original.resolve() if original is not None else None
    choices = {'TNOVA': retail, 'TNDEMO1': download_demo, 'TNDEMO2': cd_demo}
    folders = {}
    for name, path in choices.items():
        if path is None:
            if root is None:
                raise ValueError('Specify --original or all four source locations; missing ' + name)
            path = root / name
        folders[name] = path.resolve()
    if cd_image is None:
        if root is None:
            raise ValueError('Specify --cd-image when --original is omitted')
        cd_image = root / '_ISO/TNF108.ISO'
    return folders, cd_image.resolve()


def validate_destination(destination, portable):
    try:
        str(destination).encode('ascii')
    except UnicodeEncodeError:
        raise ValueError(
            'Use an ASCII destination path; original source paths may contain Unicode.'
        )
    # Snapshot runs allow 155 root characters, but current game slots allow 115.
    limits = [155] + [
        (row['capacity'] - 1 - len(row['value'].replace('{ROOT}', ''))) //
        row['value'].count('{ROOT}') for row in portable['relocations'] if '{ROOT}' in row['value']
    ]
    limit = min(limits)
    if len(str(destination)) > limit:
        raise ValueError(
            f'Destination path is too long; this build allows at most {limit} characters. Choose a folder nearer the drive root.'
        )
    for row in portable['relocations']:
        value = row['value'].replace('{ROOT}', str(destination)).encode('ascii')
        if len(value) >= row['capacity']:
            raise ValueError('Destination path is too long; choose a folder nearer the drive root.')


def generate_outputs(package, folders, manifest, compiler, dependencies,
                     tools_cache=None, tool_downloads=None):
    """Run checked generators in a temporary build, retaining only final bytes.

    This is separate from installation: a failed compiler or mismatched result
    must never create a partial game destination. Temporary original copies and
    compiler outputs are owned by this invocation and are removed together.
    """
    if tools_cache is None and (compiler is None or dependencies is None):
        raise ValueError('Local generation requires --tools-cache or --compiler and --dependencies')
    descriptor = manifest.get('generation', {})
    if descriptor.get('schema') != 1:
        raise ValueError('Unsupported local-generation recipe')
    for name, expected in descriptor.get('inputs', {}).items():
        actual = manifest['inputs'].get(name, {})
        if any(actual.get(k) != expected[k] for k in ('size', 'sha256')):
            raise ValueError('Generation input is absent from setup inventory: ' + name)
    if getattr(sys, 'frozen', False):
        raise ValueError('This preview generation command requires the documented Python runtime')
    with tempfile.TemporaryDirectory(prefix='tnova-generation-') as temporary:
        output = Path(temporary) / 'build'
        command = [
            sys.executable, '-B', str(child(package, 'generation/generate_local.py')),
            '--retail', str(folders['TNOVA']), '--cd-demo', str(folders['TNDEMO2']),
            '--bridge', str(child(package, 'payload/tn-audio.dll')),
            '--output', str(output),
        ]
        for name, value in (('compiler', compiler), ('dependencies', dependencies),
                            ('tools-cache', tools_cache), ('tool-downloads', tool_downloads)):
            if value is not None:
                command.extend(['--' + name, str(Path(value).resolve())])
        run = subprocess.run(command, capture_output=True, text=True)
        if run.returncode:
            raise ValueError('Setup generation failed:\n' + run.stdout + run.stderr)
        report = json.loads((output / 'generation.json').read_text(encoding='utf-8'))
        wanted = {r['path']: r for r in manifest['outputs'] if r['kind'] == 'generated'}
        if report.get('game_revision') != manifest['game_revision'] or set(report['outputs']) != set(wanted):
            raise ValueError('Generator output inventory differs from setup')
        generated = {}
        for name, expected in wanted.items():
            raw = child(output / 'generated', name).read_bytes()
            if len(raw) != expected['size'] or sha(raw) != expected['sha256']:
                raise ValueError('Generated output verification failed: ' + name)
            generated[name] = raw
        return generated, report


def install(
    package,
    original,
    destination,
    check_only=False,
    *,
    retail=None,
    download_demo=None,
    cd_demo=None,
    cd_image=None,
    compiler=None,
    dependencies=None,
    tools_cache=None,
    tool_downloads=None
):
    package = package.resolve()
    destination = destination.resolve()
    folders, iso_path = source_locations(original, retail, download_demo, cd_demo, cd_image)
    if destination.exists():
        raise ValueError('Choose a new destination; existing files are never overwritten.')
    protected = [package, *folders.values(), iso_path]
    if original is not None:
        protected.append(original.resolve())
    if any(destination.is_relative_to(p) or p.is_relative_to(destination) for p in protected):
        raise ValueError('Keep installation separate from original files and setup files.')
    if tools_cache is not None:
        cache = Path(tools_cache).resolve()
        if any(cache.is_relative_to(p) or p.is_relative_to(cache) for p in [*protected, destination]):
            raise ValueError('Keep tools separate from original files, setup and installation')

    def source(rel):
        prefix, separator, tail = rel.partition('/')
        if not separator or prefix not in folders:
            raise ValueError('Unknown original source: ' + rel)
        return child(folders[prefix], tail)

    manifest = json.loads((package / 'install.json').read_text(encoding='utf-8'))
    if manifest['schema'] not in (1, 2, 3):
        raise ValueError('Unsupported installer schema')
    generated_rows = any(r['kind'] == 'generated' for r in manifest['outputs'])
    if manifest['schema'] != 3 and generated_rows:
        raise ValueError('Local generation requires installer schema3')
    if manifest['schema'] == 3:
        if not generated_rows or any(r['kind'] == 'delta' for r in manifest['outputs']):
            raise ValueError('Local-generation setup must replace every prepared delta')
        if tools_cache is None and (compiler is None or dependencies is None):
            raise ValueError('Local generation requires --tools-cache or --compiler and --dependencies')
    if manifest['schema'] == 1 and any('base_inputs' in r for r in manifest['outputs']):
        raise ValueError('Multiple delta inputs require installer schema2')
    portable = json.loads(child(package, 'payload/portable.json').read_text(encoding='utf-8'))
    validate_destination(destination, portable)
    for rel, digest in manifest['package_files'].items():
        if file_sha(child(package, rel)) != digest:
            raise ValueError('Installer component changed: ' + rel)
    used = manifest['inputs']
    iso = manifest['iso']
    if file_sha(iso_path) != iso['sha256']:
        raise ValueError('Unsupported CD image: ' + iso['path'])
    for rel, row in used.items():
        if rel.startswith('iso:'):
            if row['offset'] < 0 or row['offset'] + row['size'] > iso['size']:
                raise ValueError('Invalid CD extent')
        elif file_sha(source(rel)) != row['sha256']:
            raise ValueError('Missing, changed, or unsupported original file: ' + rel)

    def read_input(rel):
        row = used[rel]
        if rel.startswith('iso:'):
            with iso_path.open('rb') as f:
                f.seek(row['offset'])
                data = f.read(row['size'])
        else:
            data = source(rel).read_bytes()
        if len(data) != row['size'] or sha(data) != row['sha256']:
            raise ValueError('Original input changed: ' + rel)
        return data

    # Validate all output paths, deltas, and original extents before creating anything.
    for row in manifest['outputs']:
        child(destination, row['path'])
    reconstructed, generation_report = {}, None
    if manifest['schema'] == 3:
        reconstructed, generation_report = generate_outputs(
            package, folders, manifest, compiler, dependencies, tools_cache, tool_downloads
        )
    for row in manifest['outputs']:
        child(destination, row['path'])
        if row['kind'] == 'copy':
            data = read_input(row['input'])
        elif row['kind'] == 'delta':
            base = delta_basis(row, read_input)
            data = decode(base, child(package, row['patch']).read_bytes(), row['size'])
            reconstructed[row['path']] = data
        elif row['kind'] == 'payload':
            data = child(package, row['payload']).read_bytes()
            reconstructed[row['path']] = data
        elif row['kind'] == 'generated':
            data = reconstructed[row['path']]
        else:
            raise ValueError('Unknown output kind')
        if len(data) != row['size'] or sha(data) != row['sha256']:
            raise ValueError('Output verification failed: ' + row['path'])
    result = dict(
        schema=1,
        game_revision=manifest['game_revision'],
        installer_revision=manifest.get("installer_revision", 121),
        outputs=len(manifest['outputs']),
        original_inputs=len(used),
        originals_modified=False,
        destination=str(destination)
    )
    if generation_report is not None:
        result['generation'] = generation_report
    if check_only:
        return dict(result, check_only=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + '.installing-' + uuid.uuid4().hex)
    staging.mkdir(exist_ok=False)
    # On failure leave the uniquely named staging folder for diagnosis; never alter
    # an existing installation or delete anything under the original directory.
    for row in manifest['outputs']:
        data = reconstructed.get(row['path'])
        if data is None:
            data = read_input(row['input'])
        target = child(staging, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (staging / 'installation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if destination.exists():
        raise ValueError('Destination appeared during installation; keeping staging folder.')
    staging.rename(destination)
    return result


def main():
    parser = argparse.ArgumentParser(
        description=
        'Create a separate native Terra Nova installation from verified English retail and demo files.'
    )
    parser.add_argument(
        '--original',
        type=Path,
        help='Root containing TNOVA, TNDEMO1, TNDEMO2 and _ISO (optional with all source options)'
    )
    parser.add_argument('--retail', type=Path, help='Retail folder containing DATA, MAPS, etc.')
    parser.add_argument(
        '--download-demo', type=Path, help='Download demo folder (TNDEMO1 contents)'
    )
    parser.add_argument('--cd-demo', type=Path, help='CD demo folder (TNDEMO2 contents)')
    parser.add_argument('--cd-image', type=Path, help='Supported retail CD ISO file')
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--compiler', type=Path, help='Pinned Zig executable for local generation')
    parser.add_argument('--dependencies', type=Path, help='Generator Python dependency folder')
    parser.add_argument('--tools-cache', type=Path, help='Prepare/reuse pinned tools in a separate folder')
    parser.add_argument('--tool-downloads', type=Path, help='Offline folder containing the three pinned tool archives')
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                install(
                    Path(__file__).resolve().parent,
                    args.original,
                    args.destination,
                    args.check_only,
                    retail=args.retail,
                    download_demo=args.download_demo,
                    cd_demo=args.cd_demo,
                    cd_image=args.cd_image,
                    compiler=args.compiler,
                    dependencies=args.dependencies,
                    tools_cache=args.tools_cache,
                    tool_downloads=args.tool_downloads
                ),
                indent=2
            )
        )
    except (OSError, ValueError, AssertionError, KeyError) as exc:
        print('Installation stopped: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
