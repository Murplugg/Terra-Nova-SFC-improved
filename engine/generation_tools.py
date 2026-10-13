"""Prepare pinned generation tools without installing anything system-wide.

The downloads are official Windows x64 releases. Exact sizes and SHA-256 values
are checked before extraction. The cache keeps their licenses and a complete
file inventory. Existing caches must verify; incomplete folders are not reused.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import urllib.request
import zipfile

from install_portable import child, file_sha

ARTIFACTS = (
    dict(
        name='zig-0.15.2-windows.zip', size=92614574,
        sha256='3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c',
        url='https://ziglang.org/download/0.15.2/zig-x86_64-windows-0.15.2.zip',
        destination='compiler',
    ),
    dict(
        name='capstone-5.0.6-py3-none-win_amd64.whl', size=1271345,
        sha256='761c3deae00b22ac697081cdae1383bb90659dd0d79387a09cf5bdbb22b17064',
        url='https://files.pythonhosted.org/packages/da/72/ff7894c2fb5716d9a3ce9c27ba34b29d991a11d8442d2ef0fcdc5564ba7e/capstone-5.0.6-py3-none-win_amd64.whl',
        destination='dependencies',
    ),
    dict(
        name='keystone_engine-0.9.2-py2.py3-none-win_amd64.whl', size=1370823,
        sha256='c91db1ff16d9d094e00d1827107d1b4afd5e63ce19b491a0140e660635000e8b',
        url='https://files.pythonhosted.org/packages/a4/8d/58471cb026de45397b29ba4b37ae3e20b434fae14c4b92fd3e9771a7bac8/keystone_engine-0.9.2-py2.py3-none-win_amd64.whl',
        destination='dependencies',
    ),
)
COMPILER = 'compiler/zig-x86_64-windows-0.15.2/zig.exe'
COMPILER_SHA = 'd408dd38eed3e5204af841bcebf70502a4dbbb8399a3a3262be55059370bc018'


def fetch(row, target, downloads=None):
    """An explicit download folder selects offline mode; never silently fetch."""
    if downloads is None:
        stream = urllib.request.urlopen(row['url'], timeout=60)
    else:
        stream = child(Path(downloads).resolve(), row['name']).open('rb')
    digest, count = hashlib.sha256(), 0
    with stream, target.open('xb') as output:
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > row['size']:
                raise ValueError('Tool download exceeds expected size: ' + row['name'])
            output.write(block)
            digest.update(block)
    if count != row['size'] or digest.hexdigest() != row['sha256']:
        raise ValueError('Tool download verification failed: ' + row['name'])


def unpack(archive, destination):
    """Check paths before extraction; never follow archive links or overwrite."""
    with zipfile.ZipFile(archive) as zipped:
        seen = set()
        for info in zipped.infolist():
            name = info.filename.rstrip('/')
            target = child(destination, name)
            identity = str(target).casefold()
            if identity in seen or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError('Duplicate path or link in tool archive: ' + name)
            seen.add(identity)
            if target.exists():
                raise ValueError('Tool archive would overwrite a file: ' + name)
        for info in zipped.infolist():
            target = child(destination, info.filename.rstrip('/'))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source, target.open('xb') as output:
                while block := source.read(1024 * 1024):
                    output.write(block)


def verify_cache(cache):
    receipt = json.loads((cache / 'tools.json').read_text(encoding='utf-8'))
    if receipt.get('schema') != 1 or receipt.get('artifacts') != list(ARTIFACTS):
        raise ValueError('Generation tools cache describes different versions')
    actual = {p.relative_to(cache).as_posix() for p in cache.rglob('*') if p.is_file()}
    if actual != set(receipt['files']) | {'tools.json'}:
        raise ValueError('Generation tools cache has missing or extra files')
    for name, expected in receipt['files'].items():
        if file_sha(child(cache, name)) != expected:
            raise ValueError('Generation tool changed: ' + name)
    if file_sha(child(cache, COMPILER)) != COMPILER_SHA:
        raise ValueError('Generation compiler differs from selected release')
    return cache / COMPILER, cache / 'dependencies'


def prepare(cache, downloads=None):
    if os.name != 'nt' or struct.calcsize('P') != 8:
        raise ValueError('Generation tools require 64-bit Windows Python')
    cache = Path(cache).resolve()
    kit = Path(__file__).resolve().parent
    if cache.is_relative_to(kit) or kit.is_relative_to(cache):
        raise ValueError('Keep the tools cache separate from setup sources')
    if cache.exists():
        return verify_cache(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=cache.name + '.preparing-', dir=cache.parent) as work:
        staged = Path(work) / 'tools'
        downloads_out = staged / 'downloads'
        downloads_out.mkdir(parents=True)
        for row in ARTIFACTS:
            print('Preparing ' + row['name'], flush=True)
            archive = downloads_out / row['name']
            fetch(row, archive, downloads)
            unpack(archive, staged / row['destination'])
        if file_sha(staged / COMPILER) != COMPILER_SHA:
            raise ValueError('Downloaded compiler differs from selected release')
        receipt = dict(schema=1, artifacts=list(ARTIFACTS), files={
            p.relative_to(staged).as_posix(): file_sha(p)
            for p in sorted(staged.rglob('*')) if p.is_file()
        })
        (staged / 'tools.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        if cache.exists():
            raise ValueError('Tools cache appeared while preparing; existing files preserved')
        staged.rename(cache)
    return cache / COMPILER, cache / 'dependencies'
