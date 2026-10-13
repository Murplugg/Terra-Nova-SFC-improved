"""Declared foundation recipes; regenerate reviewed groups without capture data."""
import hashlib, json
from build_paths import source_path


def recipe_rows(path=None):
    """Resolve named generators and check each declared span against its fingerprint.

 The manifest retains hashes for generated groups, not their machine code.
 Unknown sources, mixed literal/generated groups, missing/extra/duplicate spans
 or changed outputs are errors. No filename or import comes from the manifest.
 """
    rows = json.loads((path or source_path('recipes/foundation.json')).read_text(encoding='utf-8'))
    generated = {}
    seen = {}
    resolved = []
    for row in rows:
        if 'source' not in row:
            if set(row) != {'recipe', 'address', 'bytes'}:
                raise ValueError('Invalid literal recipe fields')
            bytes.fromhex(row['bytes'])
            resolved.append(dict(row))
            continue
        if (
            set(row) != {'recipe', 'address', 'source', 'size', 'sha256'}
            or row['source'] != 'foundation_recipes'
        ):
            raise ValueError('Unknown recipe source or fields')
        from foundation_recipes import GENERATORS
        name = row['recipe']
        address = row['address']
        if name not in GENERATORS:
            raise ValueError('Unknown generated recipe: ' + name)
        if name not in generated:
            spans = GENERATORS[name]()
            generated[name] = dict(spans)
            seen[name] = set()
            if len(generated[name]) != len(spans):
                raise ValueError('Duplicate generated address')
        if address in seen[name] or address not in generated[name]:
            raise ValueError('Duplicate or unknown recipe address')
        data = generated[name][address]
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Generated recipe differs from accepted span')
        seen[name].add(address)
        resolved.append(dict(row, bytes=data.hex()))
    for name, spans in generated.items():
        if seen[name] != set(spans):
            raise ValueError('Missing generated recipe spans')
        if any(r['recipe'] == name and 'source' not in r for r in rows):
            raise ValueError('Mixed recipe source forms')
    return resolved


def inventory(path=None):
    """Collect the final image plan, rejecting any multiply owned byte.

    Even identical overlapping writes are an error: each site has one owner.
    This prevents ordering from silently changing the selected implementation.
    """
    static = {}
    owners = {}
    blocks = []
    for row in recipe_rows(path):
        address = row['address']
        data = bytes.fromhex(row['bytes'])
        for offset, value in enumerate(data):
            site = address + offset
            if site in static:
                raise ValueError(
                    f"Foundation overlap at {site:#x}: {owners[site]} and {row['recipe']}"
                )
            static[site] = value
            owners[site] = row['recipe']
        blocks.append((address, len(data), row['recipe']))
    return static, {}, blocks
