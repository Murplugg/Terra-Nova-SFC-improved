"""Checked LG resource, compound and menu bitmap codecs."""
import struct

U = lambda r, a: struct.unpack_from('<I', r, a)[0]


def entries(b):
    assert b.startswith(b'LG Res File v2\r\n\x1a') and len(b) >= 128
    d = U(b, 124)
    assert 128 <= d <= len(b) - 6
    count, pos = struct.unpack_from('<HI', b, d)
    assert d + 6 + count * 10 == len(b)
    out = {}
    for i in range(count):
        e = b[d + 6 + i * 10:d + 16 + i * 10]
        rid = int.from_bytes(e[:2], 'little')
        n = int.from_bytes(e[6:9], 'little')
        assert rid not in out and 128 <= pos <= pos + n <= d
        out[rid] = (e, b[pos:pos + n])
        pos = (pos + n + 3) & ~3
    assert pos == d
    return out


def archive(rows):
    b = bytearray(128)
    b[:17] = b'LG Res File v2\r\n\x1a'
    directory = []
    for rid, (e, data) in sorted(rows.items()):
        assert len(e) == 10 and len(data) == int.from_bytes(e[6:9], 'little')
        directory.append(struct.pack('<H', rid) + e[2:])
        b.extend(data)
        b.extend(bytes((-len(b)) % 4))
    struct.pack_into('<I', b, 124, len(b))
    b.extend(struct.pack('<HI', len(directory), 128))
    b.extend(b''.join(directory))
    result = bytes(b)
    assert set(entries(result)) == set(rows)
    return result


def parts(data):
    n = int.from_bytes(data[:2], 'little')
    ofs = struct.unpack_from('<' + str(n + 1) + 'I', data, 2)
    assert ofs[0] == 2 + 4 * (n + 1) and ofs[-1] == len(data) and list(ofs) == sorted(ofs)
    return [data[ofs[i]:ofs[i + 1]] for i in range(n)]


def compound(ps):
    offset = 2 + 4 * (len(ps) + 1)
    offsets = [offset]
    for p in ps:
        offset += len(p)
        offsets.append(offset)
    return struct.pack('<H', len(ps)) + struct.pack('<' + 'I' * len(offsets), *
                                                    offsets) + b''.join(ps)


def replace(rows, rid, data):
    e = bytearray(rows[rid][0])
    assert e[5] == 2
    e[2:5] = len(data).to_bytes(3, 'little')
    e[6:9] = len(data).to_bytes(3, 'little')
    rows[rid] = (bytes(e), data)


def decode(b):
    out = bytearray()
    p = 28
    while p < len(b):
        op = b[p]
        p += 1
        if op == 0:
            n, v = b[p:p + 2]
            p += 2
            out += bytes([v]) * n
        elif op < 128:
            out += b[p:p + op]
            p += op
        elif op > 128:
            out += bytes(op - 128)
        else:
            n = struct.unpack_from('<H', b, p)[0]
            p += 2
            if n == 0:
                break
            if n < 0x8000:
                out += bytes(n)
            elif n < 0xc000:
                n &= 0x3fff
                out += b[p:p + n]
                p += n
            else:
                n &= 0x3fff
                out += bytes([b[p]]) * n
                p += 1
        assert len(out) <= 640 * 480, (len(out), p)
    assert len(out) == 640 * 480, (len(out), p, len(b))
    return out


def encode(header, pixels):
    out = bytearray()
    p = 0
    while p < len(pixels):
        n = 1
        while n < 255 and p + n < len(pixels) and pixels[p + n] == pixels[p]:
            n += 1
        if n >= 3:
            out += bytes([0, n, pixels[p]])
            p += n
        else:
            start = p
            p += n
            while p < len(pixels) and p - start < 125:
                if p + 2 < len(pixels) and pixels[p] == pixels[p + 1] == pixels[p + 2]:
                    break
                p += 1
            out += bytes([p - start]) + pixels[start:p]
    out += b'\x80\0\0'
    h = bytearray(header[:28])
    palette_at = struct.unpack_from('<I', header, 24)[0] - 10
    palette = header[palette_at:]
    assert len(palette) == 769
    struct.pack_into('<I', h, 24, 28 + len(out) + 10)
    result = bytes(h + out + palette)
    assert decode(result) == pixels
    return result
