"""Build the Windows display and digital-audio bridge with a pinned compiler."""
from pathlib import Path
import argparse, hashlib, json, subprocess, struct

FILES = ['audio.c', 'audio_abi.S', 'display.c']
EXPECTED_NORMALIZED = '1a378236ae663f99342dc770177875c7be4d3765df77807f38520e57a4d5028c'


def normalized(data):
    """Ignore only COFF/debug timestamps and the CodeView debug GUID."""
    raw = bytearray(data)
    nt = struct.unpack_from('<I', raw, 60)[0]
    if raw[nt:nt + 4] != b'PE\0\0':
        raise ValueError('Not a PE image')
    opt = nt + 24
    sections = opt + struct.unpack_from('<H', raw, nt + 20)[0]

    def offset(rva):
        for i in range(struct.unpack_from('<H', raw, nt + 6)[0]):
            _, va, size, at = struct.unpack_from('<4I', raw, sections + i * 40 + 8)
            if va <= rva < va + size:
                return at + rva - va
        raise ValueError('PE address outside raw sections')

    ranges = [(nt + 8, 4)]
    rva, size = struct.unpack_from('<II', raw, opt + 96 + 6 * 8)
    if size % 28:
        raise ValueError('Invalid PE debug directory')
    for p in range(offset(rva), offset(rva) + size, 28):
        ranges.append((p + 4, 4))
        kind, length, _, at = struct.unpack_from('<4I', raw, p + 12)
        if kind == 2:
            if raw[at:at + 4] != b'RSDS' or length < 24:
                raise ValueError('Unexpected CodeView record')
            ranges.append((at + 4, 16))
    for at, n in ranges:
        if at + n > len(raw):
            raise ValueError('Debug field outside image')
        raw[at:at + n] = bytes(n)
    return bytes(raw), ranges


def build(zig, source, destination):
    zig = zig.resolve()
    source = source.resolve()
    destination = destination.resolve()
    version = subprocess.check_output([str(zig), 'version'], text=True).strip()
    if version != '0.15.2':
        raise ValueError('Use the recorded Zig 0.15.2 toolchain for this reproduction.')
    destination.mkdir(parents=True, exist_ok=False)
    output = destination / 'tn-audio.dll'
    command = [str(zig), 'cc', '-target', 'x86-windows-gnu', '-O2', '-mstackrealign', '-shared'
               ] + [str(source / n)
                    for n in FILES] + ['-lwinmm', '-lgdi32', '-luser32', '-o',
                                       str(output)]
    result = subprocess.run(command, cwd=destination, capture_output=True, text=True)
    (destination / 'compiler.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    result.check_returncode()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    stable, ranges = normalized(output.read_bytes())
    report = dict(
        compiler_version=version,
        compiler_sha256=digest(zig),
        sources={n: digest(source / n)
                 for n in FILES},
        command=command,
        output_sha256=digest(output),
        output_bytes=output.stat().st_size,
        normalized_sha256=hashlib.sha256(stable).hexdigest(),
        ignored_debug_metadata=ranges
    )
    if report['normalized_sha256'] != EXPECTED_NORMALIZED:
        raise ValueError(
            'Rebuilt bridge differs from the accepted code/data baseline; inspect before using it.'
        )
    report['accepted_code_and_data_match'] = True
    (destination / 'build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--zig', type=Path, required=True)
    p.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--destination', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.zig, a.source, a.destination), indent=2))
