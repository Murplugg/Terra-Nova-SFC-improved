"""Small deterministic copy/zero/literal delta codec, using only Python stdlib."""
import struct, zlib


def delta_basis(row, read_input):
    """Schema2 may concatenate verified originals for existing TND1 copies.

    Order is explicit and starts with the legacy primary input. The caller
    verifies each original's size/hash. Schema1 rows retain their exact basis.
    """
    names = row.get('base_inputs', [row['input']])
    if (
        not isinstance(names, list) or not 1 <= len(names) <= 16
        or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names)
        or names[0] != row['input']
    ):
        raise ValueError('Invalid delta input list')
    transform = row.get('transform')
    if transform not in (None, 'native-le'):
        raise ValueError('Unknown delta input transform')
    if transform and len(names) != 1:
        raise ValueError('Transformed delta requires one input')
    parts = []
    size = 0
    for name in names:
        data = read_input(name)
        size += len(data)
        if size > 64 * 1024 * 1024:
            raise ValueError('Delta input basis is too large')
        parts.append(data)
    base = b''.join(parts)
    return native_base(base) if transform == 'native-le' else base


def encode(base, target):
    # Sparse index: zero runs have their own instruction and need no index.
    index = {}
    for p in range(0, len(base) - 31, 16):
        key = base[p:p + 32]
        if key != bytes(32):
            index.setdefault(key, p)
    out = bytearray(b'TND1')
    literal = bytearray()
    i = 0

    def flush():
        if literal:
            out.extend(b'L' + struct.pack('<I', len(literal)) + literal)
            literal.clear()

    while i < len(target):
        key = target[i:i + 32]
        if key == bytes(32):
            flush()
            end = i + 32
            while target[end:end + 4096] == bytes(4096):
                end += 4096
            while end < len(target) and target[end] == 0:
                end += 1
            out.extend(b'Z' + struct.pack('<I', end - i))
            i = end
            continue
        at = i if len(key) == 32 and base[i:i + 32] == key else index.get(key)
        if at is not None:
            flush()
            n = 32
            while len(target) >= i + n + 4096 and base[at + n:at + n + 4096] == target[i + n:i + n +
                                                                                       4096]:
                n += 4096
            while at + n < len(base) and i + n < len(target) and base[at + n] == target[i + n]:
                n += 1
            out.extend(b'C' + struct.pack('<II', at, n))
            i += n
        else:
            literal.append(target[i])
            i += 1
    flush()
    return zlib.compress(out, 9)


def decode(base, patch, size):
    if not 0 <= size <= 64 * 1024 * 1024:
        raise ValueError('Unsupported output size')
    inflater = zlib.decompressobj()
    limit = 2 * size + 1024
    raw = inflater.decompress(patch, limit + 1)
    if len(raw) > limit or not inflater.eof or inflater.unused_data:
        raise ValueError('Invalid delta compression')
    if raw[:4] != b'TND1':
        raise ValueError('Invalid delta header')
    out = bytearray()
    p = 4
    while p < len(raw):
        tag = raw[p:p + 1]
        p += 1
        if p + 4 > len(raw):
            raise ValueError('Truncated instruction')
        n = struct.unpack_from('<I', raw, p)[0]
        p += 4
        if tag == b'C':
            at = n
            if p + 4 > len(raw):
                raise ValueError('Truncated copy')
            n = struct.unpack_from('<I', raw, p)[0]
            p += 4
            if at + n > len(base):
                raise ValueError('Copy outside input')
            payload = base[at:at + n]
        elif tag == b'Z':
            payload = None
        elif tag == b'L':
            if p + n > len(raw):
                raise ValueError('Truncated literal')
            payload = raw[p:p + n]
            p += n
        else:
            raise ValueError('Invalid delta instruction')
        if n == 0 or len(out) + n > size:
            raise ValueError('Delta exceeds output bounds')
        out.extend(bytes(n) if payload is None else payload)
    if len(out) != size:
        raise ValueError('Delta output is incomplete')
    return bytes(out)


def native_base(original):
    from le_image import LE
    le = LE(original)
    bases = (0x244000, 0x72000, 0x355000)
    if len(le.objects) != 3:
        raise ValueError('Expected retail three-object LE image')
    image = bytearray(0x2000000)
    for at, body in zip(bases, le.relocated(bases, (0x23, 0x2b, 0x2b))):
        if at + len(body) > len(image):
            raise ValueError('LE object outside native allocation')
        image[at:at + len(body)] = body
    return bytes(512) + bytes(image[0x11000:])
