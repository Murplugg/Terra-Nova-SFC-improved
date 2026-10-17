"""Deterministic portable packaging from verified originals and current outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from build_support import install_audit, verify_sources
from build_bridge import normalized, EXPECTED_NORMALIZED
from package_delta import encode, decode, delta_basis
from install_portable import child

KIT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def readme_text(revision, milestone, *, installed=False):
    """Instructions for the current unbundled developer package."""
    name = 'package-support/README.txt' if installed else 'SETUP-README.txt'
    return (KIT / name).read_bytes().decode('utf-8')


def template(exe, recipe):
    if sha(exe) != recipe['executable_sha256']:
        raise ValueError('Executable differs from selected release')
    result = bytearray(exe)
    seen = []
    for row in recipe['relocations']:
        at, n = row['offset'], row['capacity']
        value = row['value'].encode('ascii')
        if not 0 <= at < at + n <= len(exe) or len(value) >= n:
            raise ValueError('Invalid relocation bounds')
        if any(at < b and a < at + n for a, b in seen):
            raise ValueError('Overlapping relocation slots')
        if sha(exe[at:at + n]) != row['before_sha256']:
            raise ValueError('Unexpected relocation source bytes')
        result[at:at + n] = value.ljust(n, b'\0')
        seen.append((at, at + n))
    if sha(result) != recipe['template_sha256']:
        raise ValueError('Portable template differs')
    return bytes(result)


def copy_generators(target):
    """Package maintained build sources, never generated images or geometry.

    Use the contributor allowlist so private research cannot enter player setup.
    The source review remains a separate requirement: Python/assembly text can
    also contain original-derived instructions.
    """
    export = json.loads((KIT.parent / 'source-export.json').read_text(encoding='utf-8'))
    pins = json.loads((KIT / 'source-manifest.json').read_text(encoding='utf-8'))
    selected = {}
    for name in export['files']:
        if not name.startswith('engine/'):
            continue
        relative = name.removeprefix('engine/')
        raw = child(KIT, relative).read_bytes()
        if pins['files'].get(relative) != sha(raw):
            raise ValueError('Generator source changed: ' + relative)
        path = child(target / 'generation', relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        selected[relative] = sha(raw)
    pins['files'] = selected
    (target / 'generation/source-manifest.json').write_text(
        json.dumps(pins, indent=2) + '\n', encoding='utf-8'
    )


def package(original, build_root, recipe, *, local_generation=False):
    target = build_root / 'package'
    target.mkdir()
    if not local_generation:
        (target / 'patches').mkdir()
    (target / 'payload').mkdir()
    used = {}
    outputs = []

    generation_inputs = {}
    if local_generation:
        from generate_local import required_inputs
        generation_inputs = required_inputs()

    def read(name):
        row = recipe['inputs'].get(name, generation_inputs.get(name))
        if row is None:
            raise ValueError('Undeclared original input: ' + name)
        if name.startswith('iso:'):
            iso = recipe['iso']
            path = child(original, iso['path'])
            if row['offset'] < 0 or row['offset'] + row['size'] > iso['size']:
                raise ValueError('Invalid ISO extent')
            with path.open('rb') as f:
                f.seek(row['offset'])
                data = f.read(row['size'])
        else:
            data = child(original, name).read_bytes()
        if len(data) != row['size'] or sha(data) != row['sha256']:
            raise ValueError('Unsupported original: ' + name)
        used[name] = row
        return data

    # Copy recipes already declare hashes; verify each distinct source without
    # writing full game assets into the small distribution ZIP.
    with child(original, recipe['iso']['path']).open('rb') as f:
        iso_sha = hashlib.file_digest(f, 'sha256').hexdigest()
    if iso_sha != recipe['iso']['sha256']:
        raise ValueError('Unsupported CD image')
    for row in recipe['copies']:
        if row['input'] not in used:
            read(row['input'])
        outputs.append(dict(row))
    for name in generation_inputs:
        if name not in used:
            read(name)
    exe = (build_root / 'engine/native-chain.exe').read_bytes()
    generated = {'native-template.bin': template(exe, recipe)}
    resource_inputs = tuple(
        json.loads((KIT / 'resource-manifest.json').read_text(encoding='utf-8'))['inputs']
    )
    for row in recipe['deltas']:
        rel = row['path']
        data = generated.get(rel)
        if data is None:
            data = child(build_root / 'resources', rel).read_bytes()
        if len(data) != row['size'] or sha(data) != row['sha256']:
            raise ValueError('Wrong generated output: ' + rel)
        if local_generation:
            outputs.append(dict(path=rel, kind='generated', size=len(data), sha256=sha(data)))
            continue
        row = dict(row)
        if not row.get('transform'):
            row['base_inputs'] = [row['input'], *[n for n in resource_inputs if n != row['input']]]
        base = delta_basis(row, read)
        patch = encode(base, data)
        if decode(base, patch, len(data)) != data:
            raise ValueError('Delta roundtrip differs')
        name = 'patches/' + rel.replace('/', '_') + '.tnd'
        child(target, name).write_bytes(patch)
        outputs.append(dict(row, patch=name))

    def payload(rel, data):
        path = 'payload/' + rel
        dest = child(target, path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        outputs.append(
            dict(path=rel, kind='payload', payload=path, size=len(data), sha256=sha(data))
        )

    # Canonicalize only linker timestamps/debug identity, already excluded by
    # the bridge equivalence check. Runtime code/data are unchanged.
    bridge, _ = normalized((build_root / 'bridge/tn-audio.dll').read_bytes())
    if sha(bridge) != EXPECTED_NORMALIZED:
        raise ValueError('Bridge code/data differs')
    payload('tn-audio.dll', bridge)
    assets = {row['path']: row['sha256'] for row in outputs if row['path'] != 'native-template.bin'}
    revision = recipe['game_revision']
    milestone = recipe['setup_milestone']
    portable = dict(
        schema=1,
        revision=revision,
        template_sha256=recipe['template_sha256'],
        relocations=[
            {
                k: v
                for k, v in row.items() if k != 'before_sha256'
            } for row in recipe['relocations']
        ],
        assets=assets
    )
    if recipe.get('runtime_paths'):
        portable['runtime_paths'] = recipe['runtime_paths']
    payload('portable.json', (json.dumps(portable, indent=2) + '\n').encode())
    for name in recipe['support']:
        data = child(KIT / 'package-support', name).read_bytes()
        if name == 'README.txt':
            data = readme_text(revision, milestone, installed=True).encode('utf-8')
        payload(name, data)
    for name in ('install_portable.py', 'package_delta.py', 'le_image.py'):
        shutil.copyfile(KIT / name, target / name)
    if local_generation:
        copy_generators(target)
    readme = readme_text(revision, milestone)
    (target / 'README.txt').write_text(readme, encoding='utf-8')
    manifest = dict(
        schema=3 if local_generation else 2,
        installer_revision=milestone,
        game_revision=revision,
        iso=recipe['iso'],
        inputs=used,
        outputs=sorted(outputs, key=lambda r: r['path']),
        package_files={}
    )
    if local_generation:
        manifest['generation'] = dict(schema=1, inputs=generation_inputs)
        readme = '''TNova Native - local-generation setup

This package generates the native executable and seven edited resources from
your verified original files. It carries no prepared game/resource deltas.
The matching source download explains the changes and their input requirements.

One-time setup needs 64-bit Windows CPython 3.12. Run install_portable.py with
the usual original locations and destination, plus --tools-cache C:\\TNovaTools.
Setup downloads about 95 MB of verified tools into that separate folder;
it installs nothing globally. Allow about 700 MB for tools and temporary work.
For offline setup, add --tool-downloads with the folder containing the three
archives named in generation/generation_tools.py. Existing tools can instead
be selected with --compiler PATH_TO_ZIG_EXE --dependencies PATH_TO_DEPENDENCIES.
Use --check-only to generate and verify without installing a game.
Generation uses temporary storage and does not change the originals.
The finished game needs no compiler or tools folder. See the contributor build guide.
Unchanged assets share disk storage through hard links where supported. CD-only
files are extracted once into TNova-shared-data beside the installation; choose
another cache with --data-cache PATH. Saves/settings/generated files remain private.
Use --data-mode copy for independent resource copies. Treat shared files as read-only;
editing one linked name changes the others. Moving/deleting originals or the cache
does not break existing links. Cross-volume/unsupported links fall back to copies;
setup reports their storage cost. Explorer may still show full logical folder size.

'''
        (target / 'README.txt').write_text(readme, encoding='utf-8')
    manifest['package_files'] = {
        p.relative_to(target).as_posix(): sha(p.read_bytes())
        for p in sorted(target.rglob('*')) if p.is_file()
    }
    (target / 'install.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    # Stable ZIP ordering, permissions and timestamps make repeat builds comparable.
    suffix = '-local-generation' if local_generation else ''
    archive = build_root / f'TerraNova-native-v{revision}-setup{milestone}{suffix}.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(target.rglob('*')):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(
                path.relative_to(target).as_posix(), date_time=(2026, 10, 7, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
    return dict(
        archive=str(archive),
        zip_sha256=sha(archive.read_bytes()),
        zip_bytes=archive.stat().st_size,
        outputs=len(outputs),
        original_inputs=len(used),
        template_sha256=sha(generated['native-template.bin']),
        bridge_sha256=sha(bridge),
        game_revision=revision,
        installer_revision=milestone,
        scope='Source-built setup ZIP; original game files remain user inputs',
        generation_mode='local-generators' if local_generation else 'prepared-deltas'
    )
