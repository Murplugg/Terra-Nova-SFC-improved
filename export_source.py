"""Copy the explicit contributor file list and write a deterministic source ZIP.

Files are copied byte-for-byte. This command never rewrites Python, generates
feature implementations, or reads private builds and game installations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parent


def export(destination):
    destination = destination.resolve()
    if (
        destination.exists() or destination.is_relative_to(PROJECT)
        or PROJECT.is_relative_to(destination)
    ):
        raise ValueError('Choose a new export folder outside the source checkout')
    archive = destination.with_suffix('.zip')
    if archive.exists():
        raise ValueError('Source archive already exists')
    files = json.loads((PROJECT / 'source-export.json').read_text(encoding='utf-8'))['files']
    if files != sorted(set(files)):
        raise ValueError('Export list must be sorted and unique')
    contents = {}
    for name in files:
        source = (PROJECT / name).resolve()
        target = (destination / name).resolve()
        if not source.is_relative_to(PROJECT) or not target.is_relative_to(destination):
            raise ValueError('Export path escapes its root: ' + name)
        if source.suffix.lower() in ('.exe', '.dll', '.pyc', '.res', '.iso', '.zip'):
            raise ValueError('Binary/input artifact in source export: ' + name)
        contents[name] = source.read_bytes()
    pins = json.loads((PROJECT / 'engine/source-manifest.json').read_text(encoding='utf-8'))
    selected = {}
    for name, data in contents.items():
        if name.startswith('engine/'):
            relative = name.removeprefix('engine/')
            digest = hashlib.sha256(data).hexdigest()
            if pins['files'].get(relative) != digest:
                raise ValueError('Unreviewed source integrity change: ' + name)
            selected[relative] = digest
    # Only the integrity inventory is narrowed; maintained sources are unchanged.
    pins['files'] = selected
    contents['engine/source-manifest.json'] = (json.dumps(pins, indent=2) + '\n').encode()
    manifest = dict(
        schema=1,
        files={
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(contents.items())
        }
    )
    contents['export-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, data in sorted(contents.items()):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 11, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zipped.writestr(info, data)
    return dict(
        files=len(contents),
        source_bytes=sum(map(len, contents.values())),
        zip_bytes=archive.stat().st_size,
        zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest()
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(export(parser.parse_args().output), indent=2))
