"""Inspect or explicitly refresh hashes for already-declared source files."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--refresh', action='store_true', help='Accept reviewed edits to listed sources'
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    path = root / 'source-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    changed = []
    for name, expected in manifest['files'].items():
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError('Source path escapes root')
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            changed.append(name)
            manifest['files'][name] = actual
    print(json.dumps({'changed_sources': changed, 'refreshed': args.refresh}, indent=2))
    if args.refresh:
        path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    elif changed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
