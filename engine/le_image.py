"""Strict LE reader/writer for the hash-pinned Terra Nova image."""
from pathlib import Path
import struct, hashlib

U = lambda b, a: struct.unpack_from('<I', b, a)[0]
P = lambda b, a, n: struct.pack_into('<I', b, a, n)


class LE:

    def __init__(self, data):
        self.data = data
        self.mz = 0x352a4
        self.le = self.mz + U(data, self.mz + 0x3c)
        assert data[self.le:self.le + 4] == b'LE\0\0'
        self.h = bytearray(data[self.le:self.le + 0xc4])
        h = self.h
        assert U(h, 0x28) == 4096 and U(h, 0x44) in (3, 4)
        self.objects = []
        self.images = []
        self.fixups = []
        total = U(h, 0x14)
        page = 0
        for i in range(U(h, 0x44)):
            obj = list(struct.unpack_from('<6I', data, self.le + U(h, 0x40) + i * 24))
            self.objects.append(obj)
            size, base, flags, index, count, _ = obj
            img = bytearray(size)
            for j in range(count):
                p = self.le + U(h, 0x48) + 4 * (index + j - 1)
                pn = int.from_bytes(data[p:p + 3], 'big')
                pf = data[p + 3]
                assert pf == 0
                n = U(h, 0x2c) if pn == total else 4096
                at = self.mz + U(h, 0x80) + (pn - 1) * 4096
                img[j * 4096:min(size, j * 4096 + n)] = data[at:at + min(n, size - j * 4096)]
                f0 = U(data, self.le + U(h, 0x68) + 4 * (index + j - 1))
                f1 = U(data, self.le + U(h, 0x68) + 4 * (index + j))
                at = self.le + U(h, 0x6c) + f0
                end = self.le + U(h, 0x6c) + f1
                while at < end:
                    st, fl = data[at:at + 2]
                    at += 2
                    assert st & ~15 == 0 and fl in (0, 0x10), (hex(at), st, fl)
                    off = struct.unpack_from('<h', data, at)[0]
                    at += 2
                    target = data[at]
                    at += 1
                    typ = st & 15
                    assert typ in (2, 7, 8), (typ, hex(at))
                    if typ == 2:
                        dest = 0
                    elif fl & 0x10:
                        dest = U(data, at)
                        at += 4
                    else:
                        dest = struct.unpack_from('<H', data, at)[0]
                        at += 2
                    self.fixups.append((i + 1, j * 4096 + off, typ, target, dest))
                assert at == end
            self.images.append(img)
        # Duplicate records legitimately describe pointers which straddle a page.
        self.fixups = list(dict.fromkeys(self.fixups))

    def encode(self):
        h = bytearray(self.h)
        objs = [list(o) for o in self.objects]
        count = 0
        pages = []
        page_objects = []
        for i, (obj, img) in enumerate(zip(objs, self.images), 1):
            # Store every page, including BSS; deterministic and simple to validate.
            n = (len(img) + 4095) // 4096
            obj[0] = len(img)
            obj[3] = count + 1
            obj[4] = n
            for j in range(n):
                pages.append(bytes(img[j * 4096:(j + 1) * 4096]).ljust(4096, b'\0'))
                page_objects.append((i, j))
            count += n
        buckets = [[] for _ in pages]
        for obj, off, typ, target, dest in self.fixups:
            n = 2 if typ == 2 else 4
            assert 0 <= off <= len(self.images[obj - 1]) - n
            assert 1 <= target <= len(objs) and 0 <= dest <= len(self.images[target - 1])
            for page in range(off // 4096, (off + n - 1) // 4096 + 1):
                flags = 0x10 if typ != 2 else 0
                rec = bytes((typ, flags)) + struct.pack('<hB', off - page * 4096, target)
                if typ != 2:
                    rec += struct.pack('<I', dest)
                buckets[objs[obj - 1][3] - 1 + page].append(rec)
        tables = bytearray()

        def append(field, b):
            P(h, field, 0xc4 + len(tables))
            tables.extend(b)

        append(0x40, b''.join(struct.pack('<6I', *o) for o in objs))
        P(h, 0x44, len(objs))
        append(0x48, b''.join((i + 1).to_bytes(3, 'big') + b'\0' for i in range(count)))
        # Preserve the original resident names and entry table verbatim.
        old = self.h
        append(0x58, self.data[self.le + U(old, 0x58):self.le + U(old, 0x5c)])
        append(0x5c, self.data[self.le + U(old, 0x5c):self.le + U(old, 0x68)])
        P(h, 0x38, 0xc4 + len(tables) - U(h, 0x40))
        records = bytearray()
        offsets = []
        for bucket in buckets:
            offsets.append(len(records))
            records.extend(b''.join(bucket))
        offsets.append(len(records))
        append(0x68, struct.pack('<' + 'I' * len(offsets), *offsets))
        append(0x6c, records)
        append(0x70, b'')
        P(h, 0x74, 0)
        append(0x78, b'\0')
        P(h, 0x30, 0xc4 + len(tables) - U(h, 0x68))
        for off in (0x34, 0x3c, 0x4c, 0x50, 0x54, 0x60, 0x64, 0x7c, 0x88, 0x8c, 0x90, 0x98, 0x9c):
            P(h, off, 0)
        P(h, 0x14, count)
        P(h, 0x2c, 4096)
        prefix = self.data[:self.le] + h + tables
        padding = (-len(prefix)) % 4096
        P(h, 0x80, len(prefix) + padding - self.mz)
        return self.data[:self.le] + h + tables + bytes(padding) + b''.join(pages)

    def relocated(self, bases, selectors=(0x180, 0x190, 0x188, 0x188)):
        images = [bytearray(x) for x in self.images]
        for obj, off, typ, target, dest in self.fixups:
            value = selectors[target - 1] if typ == 2 else bases[target - 1] + dest
            if typ == 8:
                value -= bases[obj - 1] + off + 4
            struct.pack_into(
                '<H' if typ == 2 else '<I', images[obj - 1], off,
                value & (0xffff if typ == 2 else 0xffffffff)
            )
        return images


if __name__ == '__main__':
    p = Path('work/terra-nova/__FF-original.EXE')
    le = LE(p.read_bytes())
    out = le.encode()
    again = LE(out)
    assert le.images == again.images and set(le.fixups) == set(again.fixups)
    print('Roundtrip:', len(le.fixups), 'relocations;', len(out), 'bytes;', le.objects)
