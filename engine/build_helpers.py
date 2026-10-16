"""Compile and verify the freestanding collision helpers (no live game access)."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import ModuleType

FLAGS = [
    'cc', '-target', 'x86-freestanding', '-O2', '-msse2', '-mfpmath=sse', '-ffreestanding',
    '-fno-stack-protector', '-fno-asynchronous-unwind-tables', '-fno-unwind-tables', '-fno-pic',
    '-fno-pie', '-nostdlib', '-static'
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_elf(data, low, high, ignore_headers=False):
    """Read bounded ELF32/i386 load segments and defined symbols, never execute."""

    def span(offset, size):
        if offset < 0 or size < 0 or offset + size > len(data):
            raise ValueError('Truncated ELF range')
        return data[offset:offset + size]

    def fields(fmt, offset):
        return struct.unpack(fmt, span(offset, struct.calcsize(fmt)))

    if span(0, 7) != b'\x7fELF\x01\x01\x01' or fields('<HH', 16) != (2, 3):
        raise ValueError('Expected a little-endian ELF32 i386 executable')
    phoff, shoff = fields('<II', 28)
    phsize, phnum, shsize, shnum = fields('<4H', 42)
    if phsize != 32 or shsize != 40:
        raise ValueError('Unexpected ELF table sizes')
    regions = []
    for i in range(phnum):
        typ, off, addr, _, fs, ms, flags, _ = fields('<8I', phoff + i * phsize)
        if typ != 1 or not ms:
            continue
        if fs > ms:
            raise ValueError('ELF file segment exceeds memory segment')
        raw = span(off, fs)
        if ignore_headers and addr + ms <= low:
            if flags & 3:  # Excluded ELF headers must not be executable/writable.
                raise ValueError('Excluded segment contains code or writable data')
            continue
        if not low <= addr < addr + ms <= high:
            raise ValueError('ELF segment outside reserved helper memory')
        if any(addr < a + len(b) and a < addr + ms for a, b in regions):
            raise ValueError('Overlapping ELF segments')
        regions.append((addr, raw + bytes(ms - fs)))
    if not regions:
        raise ValueError('No loadable helper data')
    sections = [fields('<10I', shoff + i * shsize) for i in range(shnum)]
    symbols = {}
    for section in sections:
        if section[1] != 2:
            continue
        if section[6] >= len(sections) or section[9] != 16 or section[5] % 16:
            raise ValueError('Invalid ELF symbol table')
        strings = sections[section[6]]
        names = span(strings[4], strings[5])
        for pos in range(section[4], section[4] + section[5], 16):
            name, value, _, _, _, index = fields('<IIIBBH', pos)
            if not index or not name:
                continue
            end = names.find(b'\0', name)
            if name >= len(names) or end < 0:
                raise ValueError('Invalid ELF symbol name')
            symbol = names[name:end].decode('utf-8')
            if symbol in symbols and symbols[symbol] != value:
                raise ValueError('Ambiguous ELF symbol: ' + symbol)
            symbols[symbol] = value
    return regions, symbols


def verify_helper(recipe, regions, symbols):
    actual = [dict(address=a, size=len(b), sha256=sha(b)) for a, b in regions]
    if actual != recipe['regions']:
        raise ValueError('Compiled helper code/data differs: ' + recipe['module'])
    exported = {}
    for key, symbol in recipe['symbols'].items():
        address = symbols.get(symbol)
        if address != recipe['addresses'][key]:
            raise ValueError('Compiled helper entry differs: ' + symbol)
        if not any(a <= address < a + len(b) for a, b in regions):
            raise ValueError('Helper entry is outside its loaded data')
        exported[key] = address
    return actual, exported


def compile_helpers(kit, compiler, output, mesh_archive):
    kit, compiler, output = (Path(p).resolve() for p in (kit, compiler, output))
    recipe = json.loads((kit / 'helpers/manifest.json').read_text(encoding='utf-8'))
    if output.exists() or kit.is_relative_to(output) or compiler.is_relative_to(output):
        raise ValueError('Helper output must be new and separate from its inputs')
    if sha(compiler.read_bytes()) != recipe['compiler']['sha256']:
        raise ValueError('Compiler does not match the pinned Zig executable')
    version = subprocess.run(
        [str(compiler), 'version'], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    if version != recipe['compiler']['version']:
        raise ValueError('Unexpected Zig version')
    for name, digest in recipe['sources'].items():
        path = (kit / 'helpers' / name).resolve()
        if not path.is_relative_to(kit / 'helpers') or sha(path.read_bytes()) != digest:
            raise ValueError('Helper source integrity check failed: ' + name)
    from mesh_geometry import build_headers, OUTPUTS
    if any((kit / 'helpers' / name).exists() for name in OUTPUTS):
        raise ValueError(
            'Generated mesh headers must not shadow build output in the source directory'
        )
    # Generated includes live only in this build, never beside maintained C.
    geometry = build_headers(mesh_archive, kit / 'helpers/mesh-recipes.json', output / 'generated')
    env = os.environ.copy()
    # Fresh caches make the independent build exercise compilation too.
    env['ZIG_GLOBAL_CACHE_DIR'] = str(output / 'cache-global')
    env['ZIG_LOCAL_CACHE_DIR'] = str(output / 'cache-local')
    modules, reports = {}, []
    for helper in recipe['helpers']:
        name = helper['module']
        link = output / (name + '.ld')
        link.write_text(
            'ENTRY(' + helper['symbols']['ENTRY'] + ')\nSECTIONS { . = ' + hex(helper['low']) +
            '; .text : { *(.text*) } .rodata : { *(.rodata*) } ' +
            '.data : { *(.data*) } .bss : { *(.bss*) } ' +
            '/DISCARD/ : { *(.comment*) *(.eh_frame*) *(.note*) } }\n',
            encoding='utf-8'
        )
        defines = []
        for define, dependency in helper.get('defines', {}).items():
            defines.append('-D' + define + '=' + str(getattr(modules[dependency], 'ENTRY')))
        elf = output / (name + '.elf')
        command = [
            str(compiler), *FLAGS, *defines, '-I' + str(output / 'generated'),
            '-Wl,-T,' + str(link), '-Wl,--build-id=none',
            str(kit / 'helpers' / helper['source']), '-o',
            str(elf)
        ]
        run = subprocess.run(
            command, cwd=output, env=env, capture_output=True, text=True, timeout=120
        )
        (output / (name + '.compiler.txt')).write_text(run.stdout + run.stderr, encoding='utf-8')
        if run.returncode:
            raise ValueError('Helper compilation failed: ' + name + '\n' + run.stderr)
        regions, symbols = parse_elf(
            elf.read_bytes(), helper['low'], helper['high'], helper.get('ignore_headers', False)
        )
        region_report, exports = verify_helper(helper, regions, symbols)
        module = ModuleType(name)
        module.__file__ = str(output / (name + '.py'))
        module.__dict__.update(exports, REGIONS=regions)
        modules[name] = module
        text = '"""Generated by build_helpers.py from checked C source."""\n'
        text += ''.join(k + '=' + hex(v) + '\n' for k, v in exports.items())
        text += 'REGIONS=[\n' + ''.join(
            ' (' + hex(a) + ',bytes.fromhex(' + repr(b.hex()) + ')),\n' for a, b in regions
        ) + ']\n'
        Path(module.__file__).write_text(text, encoding='utf-8')
        reports.append(
            dict(
                module=name,
                command=command,
                regions=region_report,
                addresses=exports,
                exact_match=True
            )
        )
        print(name + ': compiled code/data and entries match', flush=True)
    report = dict(
        compiler=recipe['compiler'],
        sources=recipe['sources'],
        helpers=reports,
        geometry=geometry,
        scope='Compiled code and geometry regenerated from verified owner resources'
    )
    (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return modules, report


def register_modules(modules):
    if any(name in sys.modules for name in modules):
        raise ValueError('A collision helper was imported before compilation')
    sys.modules.update(modules)
