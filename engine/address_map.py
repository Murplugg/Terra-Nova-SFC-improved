"""Map original locations and final patch ranges for DOSBox/native backporting.

Read the verified original LE image and the native PE section table. The CSV
contains addresses and ownership labels, never copied game instructions. A
matching address identifies a location, not equivalent behavior or a portable
patch. Helper allocation, runtime buffers and host services need separate review.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import struct

from build_support import ORIGINAL_SHA
from feature_plan import OUTPUT_SHA, PLAN
from le_image import LE, U

ROOT = Path(__file__).resolve().parent
NATIVE_BASES = (0x244000, 0x72000, 0x355000)
# This is the supported Plus retail reference layout, not a DOSBox loader rule.
# Object 2 has no independently established guest base in that reference.
GUEST_BASES = (0x244000, None, 0x355000)
FIELDS = (
    'kind', 'label', 'native_start', 'native_end_exclusive', 'dosbox_start', 'dosbox_end_exclusive',
    'le_object', 'object_offset', 'original_file_offset', 'native_file_offset', 'size', 'source',
    'direct_jump_target', 'notes'
)
ANCHORS = {
    'Projectile sampling hook': 0x311553,
    'Physics remainder hook': 0x311f2a,
    'Camera setup entry': 0x29e830,
    'AI firing-poll gate': 0x251d6e,
    'Entity table': 0x3c3240,
    'Player entity ID': 0x441350,
    'PBA records': 0x3a5608,
    'AI soldier records': 0x3832f0,
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def number(value):
    return '' if value is None else f'0x{value:X}'


def pe_sections(data):
    """Return file-backed PE ranges, without assuming VA equals file offset."""
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('Expected a PE executable')
    header = U(data, 0x3c)
    if header + 24 > len(data) or data[header:header + 4] != b'PE\0\0':
        raise ValueError('Invalid PE header')
    count = struct.unpack_from('<H', data, header + 6)[0]
    optional_size = struct.unpack_from('<H', data, header + 20)[0]
    optional = header + 24
    if optional_size < 32 or optional + optional_size + count * 40 > len(data):
        raise ValueError('Truncated PE section table')
    if struct.unpack_from('<H', data, optional)[0] != 0x10b:
        raise ValueError('Expected PE32')
    base = U(data, optional + 28)
    result = []
    for index in range(count):
        at = optional + optional_size + index * 40
        raw_size, raw_offset = U(data, at + 16), U(data, at + 20)
        if raw_offset + raw_size > len(data):
            raise ValueError('PE section exceeds file')
        start = base + U(data, at + 12)
        result.append(
            dict(
                name=data[at:at + 8].rstrip(b'\0').decode('ascii'),
                start=start,
                end=start + raw_size,
                file_offset=raw_offset
            )
        )
    result.sort(key=lambda row: row['start'])
    if any(a['end'] > b['start'] for a, b in zip(result, result[1:])):
        raise ValueError('Overlapping PE sections')
    return base, result


def file_offset(sections, start, end):
    for row in sections:
        if row['start'] <= start < end <= row['end']:
            return row['file_offset'] + start - row['start']
    raise ValueError(f'Native range is not file-backed: {start:#x}..{end:#x}')


def original_regions(le):
    """Split at LE pages and zero-fill tails, then merge continuous mappings."""
    if len(le.objects) != 3:
        raise ValueError('Unsupported original LE object count')
    rows = []
    total_pages = U(le.h, 0x14)
    for index, obj in enumerate(le.objects):
        size, _, _, first_page, count, _ = obj
        base, guest = NATIVE_BASES[index], GUEST_BASES[index]
        for offset in range(0, size, 4096):
            length = min(4096, size - offset)
            raw, backed = None, 0
            if offset // 4096 < count:
                at = le.le + U(le.h, 0x48) + (first_page + offset // 4096 - 1) * 4
                page = int.from_bytes(le.data[at:at + 3], 'big')
                if le.data[at + 3] != 0 or not 1 <= page <= total_pages:
                    raise ValueError('Unsupported LE page')
                raw = le.mz + U(le.h, 0x80) + (page - 1) * 4096
                backed = min(length, U(le.h, 0x2c) if page == total_pages else 4096)
                if raw + backed > len(le.data):
                    raise ValueError('LE page exceeds file')
            for delta, amount, file_at in ((0, backed, raw), (backed, length - backed, None)):
                if not amount:
                    continue
                start = base + offset + delta
                row = dict(
                    start=start,
                    end=start + amount,
                    object=index + 1,
                    object_base=base,
                    guest_base=guest,
                    file_offset=file_at
                )
                if rows and can_merge(rows[-1], row):
                    rows[-1]['end'] = row['end']
                else:
                    rows.append(row)
    return sorted(rows, key=lambda row: row['start'])


def can_merge(a, b):
    if a['end'] != b['start'] or a['object'] != b['object']:
        return False
    if a['file_offset'] is None or b['file_offset'] is None:
        return a['file_offset'] is b['file_offset']
    return a['file_offset'] + a['end'] - a['start'] == b['file_offset']


def slices(start, end, regions):
    if not 0 <= start < end:
        raise ValueError('Invalid range')
    cuts = {start, end}
    for row in regions:
        cuts.update(a for a in (row['start'], row['end']) if start < a < end)
    ordered = sorted(cuts)
    for lo, hi in zip(ordered, ordered[1:]):
        region = next((r for r in regions if r['start'] <= lo < hi <= r['end']), None)
        yield lo, hi, region


def remove_covered(start, end, spans):
    """Keep foundation declarations only where no later feature wrote."""
    cursor = start
    for lo, hi in spans:
        if hi <= cursor or lo >= end:
            continue
        if lo > cursor:
            yield cursor, lo
        cursor = max(cursor, hi)
    if cursor < end:
        yield cursor, end


def audit_spans(audit, native, sections):
    """Validate the final-writer index and all surviving complete-write hashes."""
    if audit.get('schema') != 1:
        raise ValueError('Unsupported patch audit')
    writes, expected = audit['writes'], []
    features = {feature.name for feature in PLAN}
    for index, row in enumerate(writes):
        start, end = row['start'], row['end']
        file_offset(sections, start, end)
        if row['module'] not in features:
            raise ValueError('Unknown audited feature')
        previous = expected
        expected = []
        for lo, hi, owner in previous:
            if hi <= start or lo >= end:
                expected.append((lo, hi, owner))
            else:
                if lo < start:
                    expected.append((lo, start, owner))
                if hi > end:
                    expected.append((end, hi, owner))
        expected.append((start, end, index))
        expected.sort()
    actual = [(r['start'], r['end'], r['write']) for r in audit['final_spans']]
    if actual != expected:
        raise ValueError('Patch audit final spans do not match its writes')
    checked = 0
    for start, end, owner in actual:
        row = writes[owner]
        if (start, end) == (row['start'], row['end']):
            offset = file_offset(sections, start, end)
            if digest(native[offset:offset + end - start]) != row['after_sha256']:
                raise ValueError('Patch audit does not match the native executable')
            checked += 1
    return actual, checked


def build_tables(original, native, audit, foundation):
    if digest(original) != ORIGINAL_SHA or digest(native) != OUTPUT_SHA:
        raise ValueError('Expected the supported original and unbundled native build')
    le = LE(original)
    base, sections = pe_sections(native)
    regions = original_regions(le)
    final, checked = audit_spans(audit, native, sections)
    rows = []

    def add(kind, label, start, end, source, note=''):
        for lo, hi, region in slices(start, end, regions):
            offset = file_offset(sections, lo, hi)
            guest = raw = obj_offset = None
            obj = ''
            if region:
                obj = region['object']
                obj_offset = lo - region['object_base']
                if region['guest_base'] is not None:
                    guest = region['guest_base'] + obj_offset
                if region['file_offset'] is not None:
                    raw = region['file_offset'] + lo - region['start']
            notes = [note] if note else []
            if not region:
                notes.append(
                    'Added native range; no original DOS location. Reallocate for a backport.'
                )
            elif guest is None:
                notes.append('DOSBox guest base unverified for this object.')
            if region and raw is None:
                notes.append('Original zero-filled memory; no original file bytes.')
            jump = None
            if kind in ('patch', 'anchor') and hi - lo >= 5 and native[offset] == 0xe9:
                jump = (lo + 5 + struct.unpack_from('<i', native, offset + 1)[0]) & 0xffffffff
                notes.append(
                    'E9 rel32 encoding at row start; confirm executable code before following it.'
                )
            rows.append(
                dict(
                    zip(
                        FIELDS, (
                            kind, label, number(lo), number(hi), number(guest),
                            number(None if guest is None else guest + hi - lo), obj,
                            number(obj_offset), number(raw), number(offset), hi - lo, source,
                            number(jump), ' '.join(notes)
                        )
                    )
                )
            )

    for row in regions:
        add(
            'original-region', f"Original LE object {row['object']}", row['start'], row['end'],
            'engine/le_image.py; engine/native_host.py',
            'Location mapping only; patched instructions and runtime contents can differ.'
        )
    coverage = [(lo, hi) for lo, hi, _ in final]
    for row in foundation:
        for lo, hi in remove_covered(row['address'], row['address'] + row['size'], coverage):
            add(
                'patch', 'foundation: ' + row['recipe'], lo, hi, 'engine/foundation_recipes.py',
                'Surviving declared foundation range.'
            )
    for lo, hi, owner in final:
        add(
            'patch', audit['writes'][owner]['module'], lo, hi, 'engine/feature_build.py',
            'Final feature writer; includes instructions, data and padding. Source names the dispatcher.'
        )
    for label, address in ANCHORS.items():
        # Anchors identify locations rather than claiming a function's full size.
        add('anchor', label, address, address + 1, 'engine/address_map.py')
    rows.sort(key=lambda row: (int(row['native_start'], 16), row['kind'], row['label']))
    metadata = dict(
        schema=1,
        original_sha256=ORIGINAL_SHA,
        native_sha256=OUTPUT_SHA,
        guest_profile='English retail v1.09 / Terra Nova Plus reference code and data bases',
        native_image_base=number(base),
        native_sections=sections,
        original_objects=[
            dict(
                object=i + 1,
                native_base=number(n),
                guest_base=number(g),
                virtual_size=le.objects[i][0]
            ) for i, (n, g) in enumerate(zip(NATIVE_BASES, GUEST_BASES))
        ],
        rows=len(rows),
        complete_final_writes_checked=checked,
        audit_sha256=digest(json.dumps(audit, sort_keys=True).encode()),
        foundation_sha256=digest(json.dumps(foundation, sort_keys=True).encode()),
        limitations=[
            'Retail only; demo code and other editions need separate profiles.',
            'Guest bases describe a reference DOSBox layout, not every allocation/environment.',
            'Object 2 guest base is intentionally unverified.',
            'Locations and final writers do not establish behavior, ABI or dependency equivalence.',
            'No runtime heap, dynamic pointer or complete Windows-host inventory is inferred.',
            'Only declared foundation recipes and audited final features are enumerated as patches.',
            'Split final writes have no independent partial hash; exact native hash still applies.',
        ]
    )
    return rows, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'native', 'patch-audit', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    inputs = [args.original.resolve(), args.native.resolve(), args.patch_audit.resolve(), ROOT]
    if output.exists() or any(p.is_relative_to(output) or output.is_relative_to(p) for p in inputs):
        parser.error('Choose a new output directory outside the source and inputs')
    rows, metadata = build_tables(
        args.original.read_bytes(), args.native.read_bytes(),
        json.loads(args.patch_audit.read_text(encoding='utf-8')),
        json.loads((ROOT / 'recipes/foundation.json').read_text(encoding='utf-8'))
    )
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    csv_data = text.getvalue().encode('utf-8')
    metadata['csv_sha256'] = digest(csv_data)
    output.mkdir(parents=True)
    (output / 'address-map.csv').write_bytes(csv_data)
    (output / 'address-map.json').write_text(
        json.dumps(metadata, indent=2) + '\n', encoding='utf-8'
    )
    print(f"Wrote {len(rows)} mapping rows to {output}")


if __name__ == '__main__':
    main()
