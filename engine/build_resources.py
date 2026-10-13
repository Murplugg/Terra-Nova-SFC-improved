"""Rebuild current menu and Prequel resources from verified originals."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from build_support import install_audit, verify_sources

KIT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(original, output, manifest, candidate_room_clicks=True, candidate_prequel_help=True):
    original, output = original.resolve(), output.resolve()
    if output.exists() or original.is_relative_to(output) or KIT.is_relative_to(output):
        raise ValueError('Resource output must be new and separate from inputs')
    inputs = {}
    for name, expected in manifest['inputs'].items():
        path = (original / name).resolve()
        if not path.is_relative_to(original):
            raise ValueError('Input path escapes original folder')
        raw = path.read_bytes()
        if len(raw) != expected['size'] or sha(raw) != expected['sha256']:
            raise ValueError('Unsupported original resource: ' + name)
        inputs[name] = raw
    from resource_codec import entries, archive
    from resource_transforms import build_menu, build_campaign, finish_prequel, build_overlays
    demo = output / 'prequel/DATA'
    demo.mkdir(parents=True)
    (demo / 'RESBABL2.RES').write_bytes(inputs['TNDEMO2/DATA/DEMOBAB2.RES'])
    (demo / 'RESMISS.RES').write_bytes(inputs['TNDEMO2/DATA/DEMOMIS2.RES'])
    build_menu(demo / 'RESBABL2.RES')
    build_campaign(demo / 'RESMISS.RES')
    rows = entries(inputs['TNOVA/DATA/RESGAME.RES'])
    demo_rows = entries(inputs['TNDEMO2/DATA/DEMOGAM2.RES'])
    for rid in [373, *range(452, 457)]:
        rows[rid] = demo_rows[rid]
    (demo / 'RESGAME.RES').write_bytes(archive(rows))
    finish_prequel(output / 'prequel', original)
    details = build_overlays(output, original / 'TNOVA/DATA', demo)
    results = {}
    for name, expected in manifest['outputs'].items():
        path = (output / name).resolve()
        if not path.is_relative_to(output):
            raise ValueError('Resource output path escapes destination')
        raw = path.read_bytes()
        actual = dict(size=len(raw), sha256=sha(raw))
        if actual != expected:
            raise ValueError('Rebuilt resource differs: ' + name + ' ' + actual['sha256'])
        results[name] = actual
        print(name + ': exact match', flush=True)
    report = dict(
        inputs=manifest['inputs'],
        outputs=results,
        menu=details,
        scope='Resources rebuilt from seven verified original files'
    )
    if candidate_room_clicks:
        from room_clicks import patch
        path = output / 'menu-retail.res'
        raw, details = patch(path.read_bytes())
        path.write_bytes(raw)
        report['accepted_outputs'] = results.copy()
        report['outputs']['menu-retail.res'] = dict(size=len(raw), sha256=sha(raw))
        report['candidate_room_clicks'] = details
        report['scope'] = 'Current room-click resource changes'
        print('menu-retail.res: room-click correction applied', flush=True)
    if candidate_prequel_help:
        from prequel_help import patch
        name = 'prequel/DATA/RESGAME.RES'
        path = output / name
        raw = patch(path.read_bytes(), manifest['outputs'][name]['sha256'])
        path.write_bytes(raw)
        report['outputs'][name] = dict(size=len(raw), sha256=sha(raw))
        report['candidate_prequel_help'] = True
        report['scope'] = 'Current Prequel help and room-click resources'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.flags.optimize:
        raise ValueError('Python -O disables required resource checks')
    original = args.original_root.resolve()
    output = args.output.resolve()
    # Limit input access to the individually declared files, not the whole install.
    manifest = json.loads((KIT / 'resource-manifest.json').read_text(encoding='utf-8'))
    allowed = [KIT, output, Path(sys.base_prefix), Path(sys.prefix)]
    allowed.extend(original / name for name in manifest['inputs'])
    accesses = install_audit(allowed)
    verify_sources()
    report = build(original, output, manifest)
    report['accessed_files'] = sorted(accesses)
    (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
