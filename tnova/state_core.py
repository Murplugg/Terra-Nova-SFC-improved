"""Hash-pinned snapshot engine, shared by the portable launcher and CLI.

Snapshots contain executable memory: load only your own trusted snapshots.
The hashes catch corruption/mismatches, not a maliciously rewritten snapshot.
Python 3.11+ and keystone-engine 0.9.2 are currently developer requirements.
"""
from pathlib import Path, PurePosixPath
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import struct
import time
import uuid

TEMPLATE = 'd7a1ce9fba5da7878b1b96f1286e89c6542f07f152275bd175802b560bda5a59'
BRIDGE = '1a378236ae663f99342dc770177875c7be4d3765df77807f38520e57a4d5028c'
CONTRACT = 'db2f80217df7513f120bf127a4cf0588457e55ff5f9d13fdf73fd25380072c3c'
ROOT = Path(__file__).resolve().parent
CONTRACTS = json.loads((ROOT / 'state-contracts.json').read_text(encoding='utf-8'))
PARK = 0x1d2f000
FLAG, READY, SP, FX = PARK + 0x800, PARK + 0x804, PARK + 0x808, PARK + 0x900
SLOTS = 0x1d2a000
ARENA = 0x68000000
SIZES = {
    'memory.bin': 0x2000000,
    'cpu.bin': 36,
    'fpu.bin': 512,
    'audio.bin': 0x11800,
    'framebuffer.bin': 0x800000,
    'render-arena.bin': 0x1000000
}
NAMES = [
    'TN_Pump', 'TN_InstallDIG', 'TN_UninstallDIG', 'TN_InstallMDI', 'TN_InitSample',
    'TN_StartSample', 'TN_LoadBuffer', 'TN_MinimumBuffer', 'TN_GetStats', 'TN_TimeMS',
    'TN_FrameBegin', 'TN_FrameEnd', 'TN_Suspend', 'TN_Resume', 'TN_BindLegacyAudio', 'TN_NewWindow',
    'TN_MinMax', 'TN_Layout', 'TN_ClearBars'
]


def preference_restore_writes(revision):
    """Clear process-local preference caches without replacing mission Options.

    Standalone launcher ABI: checked against features.option_contracts by the
    source tests. Do not import build-time modules into the player launcher.
    """
    regions = [(0x1f77900, 0x200), (0x1e39c00, 0x200), (0x1fc2f00, 0x100), (0x1fcae00, 0x100)]
    if revision >= 143:
        regions.append((0x1d35800, 0x40))
    return [(a, bytes(n)) for a, n in regions] + [(0x1fc2f00 + 104, struct.pack('<I', 1))]


def render_restore_values():
    """Invalidate viewport identity after loading the complete captured arena.

    This is not cold startup: retain the captured frame, presenter flag, map
    slots and simulation state. Keep the standalone launcher free of builders.
    """
    return ((0x9aa0ec, 1), (ARENA + 0xb00000, 1), (0x9af5e8, 0))


def render_restore_source():
    return ''.join(f'mov dword ptr [{a}],{value};' for a, value in render_restore_values())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate_home(home, relocations=()):
    """Apply the generated restore-run limit before play or capture, including moves."""
    try:
        str(home).encode('ascii')
    except UnicodeEncodeError:
        raise ValueError(
            'Use an ASCII installation path; move the whole folder nearer the drive root.'
        ) from None
    limits = [155] + [
        (row['capacity'] - 1 - len(row['value'].replace('{ROOT}', ''))) //
        row['value'].count('{ROOT}') for row in relocations if '{ROOT}' in row['value']
    ]
    limit = min(limits)
    require(
        len(str(home)) <= limit,
        f'Installation path is too long; this build allows at most {limit} characters. Move the whole folder nearer the drive root.'
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def u(data, a=0):
    return struct.unpack_from('<I', data, a)[0]


def pack(value):
    return struct.pack('<I', value & 0xffffffff)


def cstr(data, a, size=256):
    b = data[a:a + size]
    require(b'\0' in b, 'Unterminated path/string')
    return b.split(b'\0')[0].decode('ascii')


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def inside(root, relative):
    require(
        isinstance(relative, str) and relative and '\\' not in relative and ':' not in relative,
        'Invalid relative path'
    )
    p = PurePosixPath(relative)
    require(
        not p.is_absolute() and all(s not in ('..', '.') for s in relative.split('/')),
        'Escaping or non-canonical path'
    )
    require(str(p) == relative, 'Non-canonical path')
    result = (root / Path(*p.parts)).resolve()
    require(result.is_relative_to(root) and result != root, 'Path escapes its root')
    return result


def asm(address, source):
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    return bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(source, addr=address)[0])


class PE:
    """Small PE32 reader for the hash-pinned native executable and bridge."""

    def __init__(self, raw):
        self.raw = bytes(raw)
        self.nt = u(raw, 0x3c)
        require(raw[self.nt:self.nt + 4] == b'PE\0\0', 'Not a PE image')
        self.opt = self.nt + 24
        require(struct.unpack_from('<H', raw, self.opt)[0] == 0x10b, 'Not PE32')
        self.base = u(raw, self.opt + 28)
        self.mem = bytearray(u(raw, self.opt + 56))
        self.sections = []
        sec = self.opt + struct.unpack_from('<H', raw, self.nt + 20)[0]
        for i in range(struct.unpack_from('<H', raw, self.nt + 6)[0]):
            _, rva, size, pos = struct.unpack_from('<4I', raw, sec + i * 40 + 8)
            require(rva + size <= len(self.mem) and pos + size <= len(raw), 'Bad PE section')
            self.mem[rva:rva + size] = raw[pos:pos + size]
            self.sections.append((rva, size, pos))
        self.imports, self.exports = {}, {}
        desc = u(raw, self.opt + 104)
        while desc and any(self.mem[desc:desc + 20]):
            ilt, _, _, _, iat = struct.unpack_from('<5I', self.mem, desc)
            for i in range(1000):
                ptr = u(self.mem, (ilt or iat) + i * 4)
                if not ptr:
                    break
                if not ptr & 0x80000000:
                    self.imports[cstr(self.mem, ptr + 2)] = self.base + iat + i * 4
            desc += 20
        exp = u(raw, self.opt + 96)
        if exp:
            count = u(self.mem, exp + 24)
            funcs, names, ords = struct.unpack_from('<3I', self.mem, exp + 28)
            for i in range(count):
                name = cstr(self.mem, u(self.mem, names + i * 4))
                ordinal = struct.unpack_from('<H', self.mem, ords + i * 2)[0]
                self.exports[name] = u(self.mem, funcs + ordinal * 4)

    def read(self, a, n):
        return bytes(self.mem[a - self.base:a - self.base + n])

    def offset(self, rva):
        for va, size, pos in self.sections:
            if va <= rva < va + size:
                return pos + rva - va
        raise ValueError('Unmapped PE offset')


class Installation:

    def __init__(self, home, verify_assets=True):
        self.home = Path(home).resolve()
        validate_home(self.home)
        contract = sha(self.home / 'portable.json')
        matches = [p for p in CONTRACTS.values() if p['contract'] == contract]
        require(len(matches) == 1, 'Unsupported portable manifest')
        self.profile = matches[0]
        self.revision = self.profile['revision']
        self.meta = json.loads((self.home / 'portable.json').read_text(encoding='utf-8'))
        validate_home(self.home, self.meta['relocations'])
        self.template = (self.home / 'native-template.bin').read_bytes()
        require(
            self.meta['revision'] == self.revision
            and self.meta['template_sha256'] == self.profile['template'],
            'Portable revision/template mismatch'
        )
        require(digest(self.template) == self.profile['template'], 'Unsupported native template')
        require(sha(self.home / 'tn-audio.dll') == BRIDGE, 'Unsupported audio/display bridge')
        self.fresh = bytearray(self.template)
        for entry in self.meta['relocations']:
            value = entry['value'].replace('{ROOT}', str(self.home)).encode('ascii')
            size, at = entry['capacity'], entry['offset']
            require(len(value) < size, 'Installation path exceeds this pilot\'s path capacity')
            self.fresh[at:at + size] = (value + b'\0').ljust(size, b'\0')
        if verify_assets:
            for rel, expected in self.meta['assets'].items():
                require(
                    sha(inside(self.home, rel)) == expected, 'Changed installation asset: ' + rel
                )
        self.pe = PE(self.fresh)

    def relocate(self, memory, campaign):
        for entry in self.meta['relocations']:
            off, size = entry['offset'], entry['capacity']
            addr = off + 0x10e00
            memory[addr:addr + size] = self.fresh[off:off + size]
        root = (str(self.home / campaign) + '\\').encode('ascii') + b'\0'
        require(len(root) <= 256, 'Campaign path too long')
        memory[0x1d08400:0x1d08500] = root.ljust(256, b'\0')


def resource_entries(b):
    require(b.startswith(b'LG Res File v2\r\n\x1a') and len(b) >= 128, 'Invalid report archive')
    d = u(b, 124)
    require(128 <= d <= len(b) - 6, 'Invalid report directory')
    count, pos = struct.unpack_from('<HI', b, d)
    require(d + 6 + count * 10 == len(b), 'Invalid report directory length')
    out = {}
    for i in range(count):
        e = b[d + 6 + i * 10:d + 16 + i * 10]
        rid, size = int.from_bytes(e[:2], 'little'), int.from_bytes(e[6:9], 'little')
        require(rid not in out and 128 <= pos <= pos + size <= d, 'Invalid report entry')
        out[rid] = (e, b[pos:pos + size])
        pos = (pos + size + 3) & ~3
    require(pos == d, 'Invalid report payload length')
    return out


def archive(rows):
    b = bytearray(128)
    b[:17] = b'LG Res File v2\r\n\x1a'
    directory = []
    for rid, (e, data) in sorted(rows.items()):
        require(
            len(e) == 10 and len(data) == int.from_bytes(e[6:9], 'little'), 'Invalid report size'
        )
        directory.append(struct.pack('<H', rid) + e[2:])
        b.extend(data)
        b.extend(bytes((-len(b)) % 4))
    struct.pack_into('<I', b, 124, len(b))
    b.extend(struct.pack('<HI', len(directory), 128))
    b.extend(b''.join(directory))
    resource_entries(b)
    return bytes(b)


def required_reports(r):
    profile, count = u(r, 0x359710), u(r, 0x35d0ec)
    require(profile < 64 and count <= 80, 'Invalid campaign report counters')
    first = r[0x4412ce + profile]
    first = 1 if first <= 2 or first >= 128 else first - 2
    return list(range(0x659 + first, 0x659 + max(first, count - 2)))


def reports(r, install, campaign):
    name = cstr(r, 0x440934).replace('/', '\\')
    root = install.home / campaign
    need = required_reports(r) if campaign == 'retail' else None
    if name:
        prefix = 'C:\\TNOVA\\'
        require(name.upper().startswith(prefix), 'Unsupported mission report path')
        leaf = name[len(prefix):]
        require(
            leaf.upper().endswith('.RES') and '/' not in leaf and '\\' not in leaf,
            'Invalid report name'
        )
        path = inside(root, leaf)
        if path.is_file():
            rows = resource_entries(path.read_bytes())
            if need is None:
                return archive(rows)
            require(all(k in rows for k in need), 'Completed mission reports are missing')
            return archive({k: rows[k] for k in need})
    require(need == [], 'Missing closed mission report file; preserve the session for recovery')
    return archive({})


def validate_buffers(read):
    layout = json.loads((ROOT / 'state-layout.json').read_text(encoding='utf-8'))
    require(u(read(ARENA + 0xb0007c, 4)) == 0x39305254, 'Render arena marker mismatch')
    for address in layout['guards']:
        require(read(address, 256) == b'\xa5' * 256, 'Damaged render guard: ' + hex(address))
    for item in layout['external']:
        require(
            digest(read(item['address'], item['size'])) == item['sha256'],
            'Render code/table mismatch: ' + hex(item['address'])
        )
    return len(layout['guards'])


def validate_ui_state(install, read):
    """Pin added UI code; snapshots must be outside a live modal transaction."""
    # The hover retry flag is mutable state, not executable code. Both pending
    # and delivered notifications are valid and must survive a snapshot.
    for span in install.profile.get('flags', []):
        require(u(read(span['address'], 4)) in (0, 1), 'Invalid room hover retry flag')
    for span in install.profile['code']:
        require(
            digest(read(span['address'], span['size'])) == span['sha256'],
            'UI code mismatch: ' + hex(span['address'])
        )
    for span in install.profile['idle']:
        require(
            not any(read(span['address'], span['size'])),
            'Close the dialog before saving a paused game'
        )


def validate_build(install, meta):
    require(meta['format'] == 'tn-portable-state-126', 'Unsupported snapshot format/version')
    require(
        meta['revision'] == install.revision,
        f"Snapshot v{meta['revision']} cannot load in v{install.revision}. "
        'Use its matching installation; transfer progress with an ordinary campaign save. '
        'The snapshot has not been changed.'
    )
    require(
        meta['template'] == install.profile['template'] and meta['bridge'] == BRIDGE
        and meta['contract'] == install.profile['contract'], 'Snapshot build mismatch'
    )


def validate_snapshot(install, folder, campaign):
    require(campaign in ('retail', 'prequel'), 'Choose retail or prequel')
    folder = Path(folder).resolve()
    meta = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
    validate_build(install, meta)
    require(meta['campaign'] == campaign, 'Snapshot belongs to the other campaign')
    require(
        set(meta['payloads']) == set(SIZES) | {'mission-reports.res'},
        'Incomplete snapshot payload set'
    )
    blobs = {}
    for name, expected in meta['payloads'].items():
        path = inside(folder, name)
        size = path.stat().st_size
        require(
            size == SIZES.get(name, size)
            and (name != 'mission-reports.res' or 134 <= size < 0x1000000),
            'Invalid snapshot payload size: ' + name
        )
        blobs[name] = path.read_bytes()
        require(digest(blobs[name]) == expected, 'Corrupt snapshot payload: ' + name)
    r = blobs['memory.bin']
    validate_ui_state(install, lambda a, n: r[a:a + n])
    require(
        r[0x35f3f4] == 1 and u(r, 0x1d0b000) == 0x103 and u(r, 0x9aa0ec) == 1,
        'Snapshot is not a paused mission'
    )
    require((u(r, 0x2448c7) == 0x1ef6800) == (campaign == 'prequel'), 'Campaign marker mismatch')
    require(
        u(r, 0x446ae8) == meta['game_clock'] and u(r, 0x1d0f300) == meta['host_ms'],
        'Snapshot clock mismatch'
    )
    stack, base = meta['saved_stack'], meta['audio_base']
    require(type(stack) is int and 0x11000 < stack < 0x1800000 - 36, 'Invalid saved stack')
    require(
        type(base) is int and 0x2000000 <= base < 0x7ff00000 and base % 0x10000 == 0
        and not (ARENA - 0x100000 < base < ARENA + 0x1000000), 'Invalid audio base'
    )
    require(r[stack:stack + 36] == blobs['cpu.bin'], 'Saved CPU stack mismatch')
    require(r[PARK:PARK + 0x1000] == bytes(0x1000), 'Snapshot gate was not removed')
    require(r[0x1800000:0x1830000] == bytes(0x30000), 'Snapshot restore scratch was not removed')
    require(r[0x2de888:0x2de88d] == install.pe.read(0x2de888, 5), 'Dispatch hook mismatch')
    rows = resource_entries(blobs['mission-reports.res'])
    if campaign == 'retail':
        require(
            all(k in rows for k in required_reports(r)), 'Snapshot lacks completed mission reports'
        )
    slots = set()
    for f in meta['files']:
        slot, offset = f['slot'], f['offset']
        require(
            type(slot) is int and 5 <= slot < 32 and slot not in slots,
            'Invalid/duplicate file slot'
        )
        slots.add(slot)
        path = inside(install.home, f['path'])
        require(
            install.meta['assets'].get(f['path']) == f['sha256'],
            'Open file is not a supported immutable asset'
        )
        require(
            path.stat().st_size == f['bytes'] and sha(path) == f['sha256'],
            'Open mission asset changed'
        )
        require(
            type(offset) is int and 0 <= offset <= min(f['bytes'], 0x7fffffff),
            'Invalid file position'
        )
        require(
            u(r, 0x1d08c00 + slot * 4) != 0 and u(r, 0x1d08c80 + slot * 4) == 0,
            'Open file table mismatch'
        )
    live_slots = {i for i in range(5, 32) if u(r, 0x1d08c00 + i * 4)}
    require(slots == live_slots, 'Snapshot is missing open mission files')

    def read(a, n):
        if ARENA <= a and a + n <= ARENA + len(blobs['render-arena.bin']):
            return blobs['render-arena.bin'][a - ARENA:a - ARENA + n]
        require(0 <= a and a + n <= len(r), 'Invalid validation address')
        return r[a:a + n]

    validate_buffers(read)
    return meta, blobs


def windows():
    k, user = C.WinDLL('kernel32', use_last_error=True), C.WinDLL('user32', use_last_error=True)
    declarations = {
        'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'ReadProcessMemory':
        ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
          C.POINTER(C.c_size_t)], W.BOOL),
        'WriteProcessMemory':
        ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t,
          C.POINTER(C.c_size_t)], W.BOOL),
        'QueryFullProcessImageNameW': ([W.HANDLE, W.DWORD, W.LPWSTR,
                                        C.POINTER(W.DWORD)], W.BOOL),
        'FlushInstructionCache': ([W.HANDLE, C.c_void_p, C.c_size_t], W.BOOL),
        'OpenThread': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
        'SuspendThread': ([W.HANDLE], W.DWORD),
        'ResumeThread': ([W.HANDLE], W.DWORD),
        'Wow64GetThreadContext': ([W.HANDLE, C.c_void_p], W.BOOL),
        'DuplicateHandle':
        ([W.HANDLE, W.HANDLE, W.HANDLE,
          C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD], W.BOOL),
        'GetCurrentProcess': ([], W.HANDLE),
        'GetFinalPathNameByHandleW': ([W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD], W.DWORD),
        'SetFilePointerEx': ([W.HANDLE, C.c_longlong,
                              C.POINTER(C.c_longlong), W.DWORD], W.BOOL),
    }
    for name, (args, result) in declarations.items():
        getattr(k, name).argtypes, getattr(k, name).restype = args, result
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    return k, user


class Process:

    def __init__(self, pid, expected):
        self.k, self.user = windows()
        self.h = self.k.OpenProcess(0x478, False, pid)
        require(self.h, 'Cannot open the selected game process')
        self.pid = pid
        name, n = C.create_unicode_buffer(32768), W.DWORD(32768)
        try:
            require(
                self.k.QueryFullProcessImageNameW(self.h, 0, name, C.byref(n)),
                'Cannot identify game process'
            )
            require(
                Path(name.value).resolve() == expected.resolve(),
                'Selected process is a different executable'
            )
        except Exception:
            self.close()
            raise

    def read(self, a, n):
        b, got = C.create_string_buffer(n), C.c_size_t()
        require(
            self.k.ReadProcessMemory(self.h, a, b, n, C.byref(got)) and got.value == n,
            'Cannot read ' + hex(a)
        )
        return b.raw

    def u(self, a):
        return u(self.read(a, 4))

    def write(self, a, b):
        got = C.c_size_t()
        require(
            self.k.WriteProcessMemory(self.h, a, b, len(b), C.byref(got)) and got.value == len(b),
            'Cannot write ' + hex(a)
        )
        require(self.read(a, len(b)) == b, 'Write verification failed')
        require(self.k.FlushInstructionCache(self.h, a, len(b)), 'Cannot flush instruction cache')

    def close(self):
        self.k.CloseHandle(self.h)

    def ip(self, thread):
        ctx = C.create_string_buffer(716)
        struct.pack_into('<I', ctx, 0, 0x10007)
        require(self.k.Wow64GetThreadContext(thread, ctx), 'Cannot inspect game thread')
        return u(ctx.raw, 0xb8)


def release_capture(n, thread, original, gate_size, armed, touched):
    """Release even after disarming fails; never erase a still-reachable gate."""
    try:
        if armed:
            for _ in range(100):
                require(
                    n.k.SuspendThread(thread) != 0xffffffff, 'Cannot disarm checkpoint boundary'
                )
                try:
                    if 0x2de888 <= n.ip(thread) < 0x2de88d:
                        continue
                    n.write(0x2de888, original)
                    armed = False
                    break
                finally:
                    require(n.k.ResumeThread(thread) != 0xffffffff, 'Cannot resume after disarming')
            require(not armed, 'Could not disarm checkpoint boundary')
    finally:
        if touched:
            n.write(FLAG, pack(0))
    if not touched:
        return False
    # A timeout can race with entering the gate. Check READY and EIP while
    # suspended before clearing scratch; disarm failure must never reach here.
    for _ in range(200):
        time.sleep(.01)
        require(n.k.SuspendThread(thread) != 0xffffffff, 'Cannot inspect gate cleanup')
        try:
            ip = n.ip(thread)
            if n.u(READY) or PARK <= ip < PARK + gate_size:
                continue
            n.write(PARK, bytes(0x1000))
            return True
        finally:
            require(n.k.ResumeThread(thread) != 0xffffffff, 'Cannot finish gate cleanup')
    raise ValueError('Game released but gate cleanup is unverified; partial snapshot retained')


def capture(install, pid, destination, executable='native-startup.exe'):
    dest = Path(destination).resolve()
    require(not dest.exists(), 'Snapshot destination already exists')
    expected = inside(install.home, executable)
    restored = executable != 'native-startup.exe'
    dllpath = install.home / 'tn-audio.dll'
    if restored:
        provenance = json.loads((expected.parent / 'restore.json').read_text(encoding='utf-8'))
        require(
            provenance['format'] == 'tn-portable-restore-126'
            and provenance['template'] == install.profile['template'],
            'Unsupported restored process'
        )
        require(sha(expected) == provenance['executable_sha256'], 'Restored executable changed')
        dllpath = expected.parent / 'tn-checkpoint-audio.dll'
        require(sha(dllpath) == provenance['audio_sha256'], 'Restored audio bridge changed')
    else:
        require(
            expected.read_bytes() == install.fresh,
            'Game executable does not match this relocated installation'
        )
    pe, dll = PE(expected.read_bytes()), PE(dllpath.read_bytes())
    n = Process(pid, expected)
    thread = None
    armed = False
    parked = False
    released = False
    touched = False
    stage = dest.with_name(dest.name + '.partial-' + uuid.uuid4().hex[:8])
    try:
        campaign = 'prequel' if n.u(0x2448c7) == 0x1ef6800 else 'retail'
        require(
            Path(cstr(n.read(0x1d08400, 256), 0)).resolve() == install.home / campaign,
            'Campaign root mismatch'
        )
        initial = (n.read(0x35f3f4, 1), n.u(0x446ae8), n.read(0x3c3240, 20000))
        require(
            initial[0] == b'\1' and n.u(0x1d0b000) == 0x103 and n.u(0x9aa0ec) == 1,
            'Pause an active mission before saving a snapshot'
        )
        original = n.read(0x2de888, 5)
        require(
            original == pe.read(0x2de888, 5) == install.pe.read(0x2de888, 5),
            'Unexpected dispatch hook'
        )
        require(n.read(PARK, 0x1000) == bytes(0x1000), 'Checkpoint gate is already occupied')
        require(n.u(0x1d04014) <= 0x1800000, 'Game heap overlaps checkpoint scratch')
        if not restored:
            require(n.read(0x1800000, 0x30000) == bytes(0x30000), 'Restore scratch is occupied')
        validate_buffers(n.read)
        validate_ui_state(install, n.read)
        base = n.u(SLOTS) - dll.exports['TN_Pump']
        require(
            0x2000000 <= base < 0x7ff00000 and base % 0x10000 == 0, 'Unsupported bridge address'
        )
        stats = n.u(0x1d2b000)
        require(
            n.u(stats + 40) == base + 0x37568 and n.u(stats + 48) == base + 0x37168,
            'Mixer identity mismatch'
        )
        sleep = n.u(base + dll.imports['Sleep'] - dll.base)
        gate = asm(
            PARK, (
                f"pushfd;"
                f"pushad;"
                f"mov [{SP}],esp;"
                f"fxsave [{FX}];"
                f"call dword ptr [{SLOTS+48}];"
                f"\n          mov dword ptr [{READY}],1;"
                f"again:cmp dword ptr [{FLAG}],0;"
                f"je done;"
                f"push 1;"
                f"mov eax,{sleep};"
                f"call eax;"
                f"jmp again;"
                f"\n          done:call dword ptr [{SLOTS+52}];"
                f"fxrstor [{FX}];"
                f"mov dword ptr [{READY}],0;"
                f"popad;"
                f"popfd;"
                f"jmp 0x1d18500;"
            )
        )
        require(len(gate) < 0x800, 'Checkpoint gate exceeds its area')
        owner = W.DWORD()
        tid = n.user.GetWindowThreadProcessId(n.u(0x1d1d000), C.byref(owner))
        require(owner.value == pid, 'Window does not belong to this game')
        thread = n.k.OpenThread(0x4a, False, tid)
        require(thread, 'Cannot inspect game thread')
        touched = True
        n.write(PARK, gate)
        n.write(FLAG, pack(1))
        for _ in range(100):
            require(n.k.SuspendThread(thread) != 0xffffffff, 'Cannot briefly suspend game thread')
            try:
                ip = n.ip(thread)
                if 0x2de888 <= ip < 0x2de88d:
                    continue
                # A failed verification/cache flush can follow a successful
                # write. Cleanup must attempt restoration in that case too.
                armed = True
                n.write(0x2de888, asm(0x2de888, f'jmp {PARK}'))
                break
            finally:
                require(n.k.ResumeThread(thread) != 0xffffffff, 'Cannot resume game thread')
        require(armed, 'Could not arm checkpoint boundary')
        deadline = time.monotonic() + 8
        while not n.u(READY):
            require(time.monotonic() < deadline, 'Game did not reach its checkpoint boundary')
            time.sleep(.01)
        parked = True
        require(
            (n.read(0x35f3f4, 1), n.u(0x446ae8), n.read(0x3c3240, 20000)) == initial,
            'Mission changed during capture; leave it paused'
        )
        r = bytearray(bytes(0x11000) + n.read(0x11000, 0x2000000 - 0x11000))
        r[0x2de888:0x2de88d] = original
        r[PARK:PARK + 0x1000] = bytes(0x1000)
        r[0x1800000:0x1830000] = bytes(0x30000)
        # A re-capture restores the normal boot stub in the serialized memory.
        r[0x1d00000:0x1d00005] = install.pe.read(0x1d00000, 5)
        stack = n.u(SP)
        require(0x11000 < stack < 0x1800000 - 36, 'Invalid saved stack')
        files = []
        for slot in range(5, 32):
            handle = n.u(0x1d08c00 + slot * 4)
            if not handle:
                continue
            require(
                n.u(0x1d08c80 + slot * 4) == 0,
                'A writable file is still open; cannot checkpoint safely'
            )
            duplicate = W.HANDLE()
            require(
                n.k.DuplicateHandle(
                    n.h, handle, n.k.GetCurrentProcess(), C.byref(duplicate), 0, False, 2
                ), 'Cannot inspect open mission file'
            )
            try:
                name, offset = C.create_unicode_buffer(32768), C.c_longlong()
                require(
                    n.k.GetFinalPathNameByHandleW(duplicate, name, len(name), 0),
                    'Cannot resolve mission file'
                )
                require(
                    n.k.SetFilePointerEx(duplicate, 0, C.byref(offset), 1),
                    'Cannot inspect mission file position'
                )
                path = Path(name.value.removeprefix('\\\\?\\')).resolve()
                require(
                    path.is_relative_to(install.home),
                    'Open mission file is outside this installation'
                )
                relative = path.relative_to(install.home).as_posix()
                h = sha(path)
                require(
                    install.meta['assets'].get(relative) == h,
                    'Open file is not a supported immutable asset: ' + relative
                )
                files.append(
                    dict(
                        slot=slot,
                        path=relative,
                        offset=offset.value,
                        bytes=path.stat().st_size,
                        sha256=h
                    )
                )
            finally:
                n.k.CloseHandle(duplicate)
        blobs = {
            'memory.bin': bytes(r),
            'cpu.bin': n.read(stack, 36),
            'fpu.bin': n.read(FX, 512),
            'audio.bin': n.read(base + 0x37168, 0x11800),
            'framebuffer.bin': n.read(0xe0000000, 0x800000),
            'render-arena.bin': n.read(ARENA, 0x1000000),
            'mission-reports.res': reports(r, install, campaign)
        }
        meta = dict(
            format='tn-portable-state-126',
            revision=install.revision,
            template=install.profile['template'],
            bridge=BRIDGE,
            contract=install.profile['contract'],
            campaign=campaign,
            audio_base=base,
            saved_stack=stack,
            game_clock=initial[1],
            host_ms=u(r, 0x1d0f300),
            files=files,
            payloads={
                name: digest(data)
                for name, data in blobs.items()
            }
        )
        stage.mkdir(parents=True, exist_ok=False)
        for name, data in blobs.items():
            (stage / name).write_bytes(data)
        save_json(stage / 'snapshot.json', meta)
        validate_snapshot(install, stage, campaign)
    finally:
        try:
            released = release_capture(
                n, thread, original if armed else b'',
                len(gate) if touched else 0, armed, touched
            )
            if parked:
                require(
                    (n.read(0x35f3f4, 1), n.u(0x446ae8), n.read(0x3c3240, 20000)) == initial,
                    'Paused mission changed after checkpoint release'
                )
        finally:
            if thread:
                n.k.CloseHandle(thread)
            n.close()
    require(released, 'Capture did not complete')
    stage.rename(dest)
    return dict(
        snapshot=str(dest),
        campaign=campaign,
        files=len(files),
        clock=meta['game_clock'],
        guards=52,
        capture_released=True,
        bytes=sum(len(b) for b in blobs.values())
    )


def fixed_audio(raw, base):
    """Keep the captured Miles pointer identity in a new private DLL copy."""
    dll = PE(raw)
    result = bytearray(raw)
    start, size = struct.unpack_from('<2I', raw, dll.opt + 96 + 5 * 8)
    cursor, count = start, 0
    while cursor < start + size:
        page, length = struct.unpack_from('<2I', dll.mem, cursor)
        require(length >= 8 and cursor + length <= start + size, 'Invalid DLL relocation block')
        for i in range((length - 8) // 2):
            entry = struct.unpack_from('<H', dll.mem, cursor + 8 + i * 2)[0]
            kind = entry >> 12
            if not kind:
                continue
            require(kind == 3, 'Unsupported DLL relocation')
            at = dll.offset(page + (entry & 4095))
            result[at:at + 4] = pack(u(raw, at) + base - dll.base)
            count += 1
        cursor += length
    require(cursor == start + size, 'Invalid DLL relocation end')
    struct.pack_into('<I', result, dll.opt + 28, base)
    flags = struct.unpack_from('<H', result, dll.opt + 70)[0]
    struct.pack_into('<H', result, dll.opt + 70, flags & ~0x60)
    return bytes(result), count


def build_restore(install, source, destination, campaign):
    """Build only. The caller starts the private executable after this returns."""
    meta, blobs = validate_snapshot(install, source, campaign)
    source, dest = Path(source).resolve(), Path(destination).resolve()
    require(
        dest.parent == install.home / 'state-runs' and not dest.exists(),
        'Choose a new run folder immediately under the installation\'s state-runs folder'
    )
    require(
        (install.home / 'native-startup.exe').read_bytes() == install.fresh,
        'Run Launch.ps1 -CheckOnly after moving the installation, before restoring'
    )
    require(
        len(str(dest)) < 200 and len(str(source)) < 230,
        'Snapshot/run path is too long for this pilot'
    )
    str(source).encode('ascii')
    str(dest).encode('ascii')
    r = bytearray(blobs['memory.bin'])
    install.relocate(r, campaign)

    def put(a, b):
        require(0x11000 <= a <= 0x2000000 - len(b), 'Restore write exceeds its image')
        r[a:a + len(b)] = b

    def d(a, value):
        put(a, pack(value))

    def api(name):
        return f'call dword ptr [{install.pe.imports[name]}];'

    cursor = 0x1813000

    def string(value):
        nonlocal cursor
        a = cursor
        b = str(value).encode('ascii') + b'\0'
        cursor += len(b)
        require(cursor < 0x181f000, 'Restore strings exceed scratch area')
        put(a, b)
        return a

    # Retain simulation/AI clocks and tables. Reset only host handles, input,
    # process API caches and display preference caches, as in the old restorer.

    reset = [
        (0x1d1d000, 0x100), (0x1d0f500, 256), (0x1d04000, 4), (0x1d041c0, 4), (0x1d041d4, 8),
        (0x1d08c00, 0x100), (0x1d40000, 0x80000), (0x1fcb800, 12), (0x1e4a500, 4),
        (0x1fd3e00, 0x100)
    ]
    for a, n in reset:
        put(a, bytes(n))
    for a in (0x1d04070, 0x1d0f008, 0x1d0f414, 0x1d0f418):
        d(a, 0)
    # Original Options values belong to the captured mission; its first Options
    # opening must not replace them. New shared checkboxes re-read current INI.
    for a, b in preference_restore_writes(install.revision):
        put(a, b)
    for a, name in (
        (0x1d05000, 'services.bin'), (0x1d05400, 'stopped-memory.bin'),
        (0x1d05500, 'framebuffer.bin'), (0x1d05600, 'stdout.txt')
    ):
        value = str(dest / name).encode('ascii') + b'\0'
        require(len(value) <= 256, 'Diagnostic path too long')
        put(a, value.ljust(256, b'\0'))
    base = meta['audio_base']
    audio, relocations = fixed_audio((install.home / 'tn-audio.dll').read_bytes(), base)
    put(0x1800000, blobs['audio.bin'])
    put(0x1812000, blobs['fpu.bin'])
    code = (
        f"cld;"
        f"fninit;"
        f"mov esp,0x1cff000;"
        f"push 3;"
        f"{api('SetErrorMode')}\n      push 0x1d00800;"
        f"push 1;"
        f"{api('AddVectoredExceptionHandler')}\n      push {string(dest/'tn-checkpoint-audio.dll')};"
        f"{api('LoadLibraryA')}cmp eax,{base};"
        f"jne failed;"
    )
    for i, name in enumerate(NAMES):
        code += (
            f"""push {string(name)};"""
            f"""push {base};"""
            f"""{api("GetProcAddress")}test eax,eax;"""
            f"""jz failed;"""
            f"""mov [{SLOTS+i*4}],eax;"""
        )
    code += (
        f"call dword ptr [{SLOTS+32}];"
        f"mov [0x1d2b000],eax;"
        f"push 0;"
        f"push 0;"
        f"call dword ptr [{SLOTS+4}];"
        f"add esp,8;"
        f"\n      cmp eax,{base+0x37168};"
        f"jne failed;"
        f"mov esi,0x1800000;"
        f"mov edi,{base+0x37168};"
        f"mov ecx,0x11800;"
        f"rep movsb;"
    )
    for f in meta['files']:
        path = inside(install.home, f['path'])
        code += (
            f"push 0;"
            f"push 0x80;"
            f"push 3;"
            f"push 0;"
            f"push 1;"
            f"push 0x80000000;"
            f"push {string(path)};"
            f"{api('CreateFileA')}\n          cmp eax,-1;"
            f"je failed;"
            f"mov ebx,eax;"
            f"mov [{0x1d08c00+f['slot']*4}],eax;"
            f"\n          push 0;"
            f"push 0;"
            f"push {f['offset']};"
            f"push ebx;"
            f"{api('SetFilePointer')}cmp eax,{f['offset']};"
            f"jne failed;"
        )

    def read_file(path, address, size):
        return (
            f"push 0;"
            f"push 0x80;"
            f"push 3;"
            f"push 0;"
            f"push 1;"
            f"push 0x80000000;"
            f"push {string(path)};"
            f"{api('CreateFileA')}\n          cmp eax,-1;"
            f"je failed;"
            f"mov ebx,eax;"
            f"push 0;"
            f"push 0x181f000;"
            f"push {size};"
            f"push {address};"
            f"push ebx;"
            f"{api('ReadFile')}\n          test eax,eax;"
            f"jz failed;"
            f"cmp dword ptr [0x181f000],{size};"
            f"jne failed;"
            f"push ebx;"
            f"{api('CloseHandle')}"
        )

    code += (
        f"""push 4;"""
        f"""push 0x3000;"""
        f"""push 0x800000;"""
        f"""push 0xe0000000;"""
        f"""{api("VirtualAlloc")}cmp eax,0xe0000000;"""
        f"""jne failed;"""
    )
    code += read_file(source / 'framebuffer.bin', 0xe0000000, 0x800000)
    code += 'call 0x1d19a00;'
    code += read_file(source / 'render-arena.bin', ARENA, 0x1000000)
    code += render_restore_source()
    code += (
        f"\n      push 0x1d0f120;"
        f"{api('QueryPerformanceFrequency')}test eax,eax;"
        f"jz failed;"
        f"\n      push 0x1d0f110;"
        f"{api('QueryPerformanceCounter')}test eax,eax;"
        f"jz failed;"
        f"\n      cmp dword ptr [0x1d0f124],0;"
        f"jne failed;"
        f"mov eax,[0x1d0f120];"
        f"mov ecx,{meta['host_ms']};"
        f"mul ecx;"
        f"\n      mov esi,eax;"
        f"mov eax,edx;"
        f"xor edx,edx;"
        f"mov ecx,1000;"
        f"div ecx;"
        f"mov edi,eax;"
        f"mov eax,esi;"
        f"div ecx;"
        f"\n      sub [0x1d0f110],eax;"
        f"sbb [0x1d0f114],edi;"
        f"\n      mov dword ptr [0x1d1d080],1;"
        f"mov dword ptr [0x181f004],0x43485054;"
        f"fxrstor [0x1812000];"
        f"\n      mov esp,{meta['saved_stack']};"
        f"popad;"
        f"popfd;"
        f"jmp 0x1d18500;"
        f"\n      failed:mov dword ptr [0x181f004],0x4641494c;"
        f"mov eax,0xff00;"
        f"int 0x21;"
    )
    body = asm(0x1820000, code)
    require(len(body) < 0x10000, 'Restore entry exceeds scratch area')
    put(0x1820000, body)
    put(0x1d00000, asm(0x1d00000, 'jmp 0x1820000'))
    # Keep a distinct title; second-generation snapshots may already have it.
    for old in (
        f'Terra Nova - native Windows research {install.revision} (PCM audio)\0'.encode(),
        f'Terra Nova - Demo Prequel (native v{install.revision})\0'.encode(),
        f'Terra Nova - portable restored v{install.revision}\0'.encode()
    ):
        at = r.find(old)
        if at >= 0:
            title = f'Terra Nova - portable restored v{install.revision}\0'.encode()
            require(len(title) <= len(old), 'Restore title too long')
            put(at, title.ljust(len(old), b'\0'))
            break
    else:
        raise ValueError('Unsupported checkpoint window title')
    leaf = 'M' + uuid.uuid4().hex[:7].upper() + '.RES'
    report = inside(install.home / campaign, leaf)
    name = ('C:\\TNOVA\\' + leaf).encode('ascii') + b'\0'
    require(len(name) <= 32, 'Report name too long')
    put(0x440934, name.ljust(32, b'\0'))
    executable = bytes(install.fresh[:512]) + r[0x11000:]
    # Preflight completed. Publish a new private run; never overwrite a save,
    # report, snapshot, normal executable, or another restore directory.
    dest.mkdir(parents=True, exist_ok=False)
    with report.open('xb') as f:
        f.write(blobs['mission-reports.res'])
    (dest / 'tn-checkpoint-audio.dll').write_bytes(audio)
    (dest / 'native-checkpoint.exe').write_bytes(executable)
    result = dict(
        format='tn-portable-restore-126',
        template=install.profile['template'],
        revision=install.revision,
        campaign=campaign,
        executable_sha256=digest(executable),
        audio_sha256=digest(audio),
        audio_base=base,
        audio_relocations=relocations,
        game_clock=meta['game_clock'],
        snapshot_manifest_sha256=sha(source / 'snapshot.json'),
        report=report.relative_to(install.home).as_posix(),
        report_sha256=sha(report)
    )
    save_json(dest / 'restore.json', result)
    return dict(executable=str(dest / 'native-checkpoint.exe'), **result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, required=True)
    sub = p.add_subparsers(dest='action', required=True)
    cap = sub.add_parser('capture')
    cap.add_argument('--pid', type=int, required=True)
    cap.add_argument('--output', type=Path, required=True)
    cap.add_argument('--executable', default='native-startup.exe')
    verify = sub.add_parser('verify')
    verify.add_argument('--snapshot', type=Path, required=True)
    verify.add_argument('--campaign', choices=['retail', 'prequel'], required=True)
    restore = sub.add_parser('restore')
    restore.add_argument('--snapshot', type=Path, required=True)
    restore.add_argument('--campaign', choices=['retail', 'prequel'], required=True)
    restore.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    install = Installation(a.home)
    if a.action == 'capture':
        result = capture(install, a.pid, a.output, a.executable)
    elif a.action == 'restore':
        result = build_restore(install, a.snapshot, a.output, a.campaign)
    else:
        meta, _ = validate_snapshot(install, a.snapshot, a.campaign)
        result = dict(valid=True, campaign=meta['campaign'], files=len(meta['files']), guards=52)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
