"""Execute weather and secondary-camera boundaries without assets or a desktop.

Camera fixtures model widget identity, drawing masks and projection state. The
final merge is compared with an independent pixel model, including paused views:
a stale pause rectangle must not hide pixels outside the actual drawing mask.
"""
import struct, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import foundation_weather as w
import foundation_cameras as c
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *


class FoundationViewsTests(unittest.TestCase):

    def machine(self, spans):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0xb00000)
        for a, b in spans:
            u.mem_write(a, b)
        u.reg_write(UC_X86_REG_ESP, 0x800000)
        self.put(u, 0x800000, 0x1000)
        return u

    def put(self, u, a, v):
        u.mem_write(a, struct.pack('<I', v & 0xffffffff))

    def get(self, u, a):
        return int.from_bytes(u.mem_read(a, 4), 'little')

    def execute(self, u, entry, end=0x1000):
        u.emu_start(entry, end, count=200000)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), end)

    def canvas(self, u, *, parity=0):
        self.put(u, 0x44b1a0, w.CANVAS)
        self.put(u, w.CANVAS, 0x600010)
        u.mem_write(w.CANVAS + 8, struct.pack('<HHH', 9, 5, 12))
        self.put(u, w.LOW + 28, 0x610000)
        self.put(u, 0x610000, 0x500000 + parity)
        self.put(u, 0x446f78, 0x500000)
        u.mem_write(0x600000, b'\xa5' * 92)

    def test_weather_points_clip_signed_coordinates_and_row_padding(self):
        for parity in (0, 1):
            for x, y in ((0, 0), (1, 1), (3, 1), (4, 0), (-1, 0), (0, -1), (0, 2)):
                with self.subTest(parity=parity, x=x, y=y):
                    u = self.machine(w.weather())
                    self.canvas(u, parity=parity)
                    u.reg_write(UC_X86_REG_EAX, 0x37)
                    u.reg_write(UC_X86_REG_EDX, x & 0xffff)
                    u.reg_write(UC_X86_REG_EBX, y & 0xffff)
                    self.execute(u, w.POINT)
                    expected = bytearray(b'\xa5' * 92)
                    if x >= 0 and y >= 0:
                        for yy in range(y * 3, min(y * 3 + 3, 5)):
                            for xx in range(
                                (x * 5 + (1 - parity)) // 2,
                                min((x * 5 + (1 - parity) + 5) // 2, 9)
                            ):
                                expected[16 + yy * 12 + xx] = 0x37
                    self.assertEqual(bytes(u.mem_read(0x600000, 92)), expected)
                    self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x37)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x800004)

    def test_weather_sprite_transparency_stride_and_rejected_geometry(self):
        for width, height, stride in (
            (2, 2, 3), (0, 2, 3), (33, 2, 33), (2, 0, 3), (2, 33, 3), (2, 2, 1)
        ):
            u = self.machine(w.weather())
            self.canvas(u)
            self.put(u, 0x620000, 0x630000)
            u.mem_write(0x620004, b'\x02')
            u.mem_write(0x620008, struct.pack('<HHH', width, height, stride))
            u.mem_write(0x630000, bytes((5, 0, 99, 0, 9, 99)))
            u.reg_write(UC_X86_REG_EAX, 0x620000)
            self.execute(u, w.SPRITE)
            expected = bytearray(b'\xa5' * 92)
            if (width, height, stride) == (2, 2, 3):
                for yy in range(3):
                    expected[16 + yy * 12:19 + yy * 12] = b'\x05' * 3
                for yy in range(3, 5):
                    expected[19 + yy * 12:21 + yy * 12] = b'\x09' * 2
            self.assertEqual(bytes(u.mem_read(0x600000, 92)), expected)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x800004)

    def test_sky_helpers_bound_both_index_registers_and_restore_flags(self):
        for entry, reg in ((w.SKY_D, UC_X86_REG_EDX), (w.SKY_C, UC_X86_REG_ECX)):
            for height in (0, 5, 600, 601):
                for index in (0, 3, 4, 20, 24, 2400, 2404, 0xfffffffc):
                    u = self.machine(w.weather())
                    self.put(u, 0x44b1a0, w.CANVAS)
                    u.mem_write(w.CANVAS + 10, struct.pack('<H', height))
                    u.mem_write(w.EFFECT - 16, b'\xa5' * 2432)
                    u.reg_write(reg, index)
                    u.reg_write(UC_X86_REG_EAX, 0x12345678)
                    u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                    self.execute(u, entry)
                    expected = bytearray(b'\xa5' * 2432)
                    accepted = 4 <= index <= min(height, 600) * 4
                    if accepted:
                        struct.pack_into('<I', expected, 12 + index, 0x12345678)
                    self.assertEqual(bytes(u.mem_read(w.EFFECT - 16, 2432)), expected)
                    self.assertEqual(self.get(u, w.STATS + 12), int(not accepted))
                    self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_wide_sky_span_uses_full_width_end_pointer(self):
        for width in (1, 255, 256, 320, 800):
            u = self.machine(w.sky_spans())
            self.put(u, 0x610000, 0x12345678)
            u.mem_write(0x610016, struct.pack('<H', width))
            u.reg_write(UC_X86_REG_ESI, 0x610000)
            u.reg_write(UC_X86_REG_EDI, 0x620000)
            u.reg_write(UC_X86_REG_EBP, 0x87654321)
            self.execute(u, 0x354c00, 0x2b2746)
            self.assertEqual(self.get(u, 0x354cf0), 0x620000 + width)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x56780000)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x7ffffc)
            # Original UV inner loop is outside this helper; model a drawn pixel.
            u.mem_write(0x2b2768, c.assemble(0x2b2768, 'inc edi; jmp 0x354c80;'))
            self.execute(u, 0x2b2768)
            self.assertEqual(u.reg_read(UC_X86_REG_EDI), 0x620000 + width)
            self.assertEqual(u.reg_read(UC_X86_REG_EBP), 0x87654321)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x800004)

    def camera_fixture(self, u, width=6, height=2, x=3, y=4, mirror=0):
        for a, b in c.initial_data():
            u.mem_write(a, b)
        self.put(u, 0x446f78, 0x500000)
        self.put(u, 0x446f80, 0x00c80140)
        u.mem_write(0x449, b'\x6b')
        self.put(u, 0x389df8, 0x620000)
        self.put(u, 0x389dec, 0x620000)
        self.put(u, 0x389de8, 0x620000)
        u.mem_write(0x38fc12, b'\x03')
        self.put(u, 0x62001c, 0x111111)
        u.mem_write(0x620020, bytes((mirror, )))
        self.put(u, 0x620022, 0x500000 + y * 320 + x)
        u.mem_write(0x62002a, struct.pack('<HH', width, height))
        original = struct.pack('<8I', 65536, 65536, 11, 22, 33, 44, 0, 0x610000)
        u.mem_write(0x390010, original)
        self.put(u, 0x610000, 0x500000 + y * 320 + x)
        u.mem_write(0x610008, struct.pack('<HHH', width, height, 320))
        self.put(u, 0x44b1ac, 0x12345)
        u.mem_write(c.LOW, bytes(range(32)))
        u.mem_write(c.CANVAS, bytes(range(64)))
        u.mem_write(0x2eab30, b'\xc3')
        u.mem_write(0x9a36e8, b'\xc3')
        u.mem_write(
            0x9b30e8,
            c.assemble(0x9b30e8, ("pushfd;"
                                  " inc dword ptr [0x630000];"
                                  " popfd;"
                                  " ret;"))
        )
        return original

    def test_camera_world_mirroring_bounds_and_context_restoration(self):
        for mirror, width in ((0, 6), (64, 6), (64, 4), (0, 3), (0, 5), (0, 102)):
            with self.subTest(mirror=mirror, width=width):
                u = self.machine(c.cameras())
                original = self.camera_fixture(u, width=width, mirror=mirror)

                def render(uc, address, size, data):
                    pw = self.get(uc, c.SLOTS + 48)
                    ph = self.get(uc, c.SLOTS + 52)
                    uc.mem_write(c.BASES[0], bytes((i % 251 + 1 for i in range(pw * ph))))

                u.hook_add(UC_HOOK_CODE, render, begin=0x9a36e8, end=0x9a36e8)
                u.reg_write(UC_X86_REG_EDX, 0x390010)
                u.reg_write(UC_X86_REG_EAX, 0x1234)
                u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                self.execute(u, c.ENTRY)
                accepted = width in (4, 6)
                self.assertEqual(self.get(u, c.SLOTS), int(accepted))
                self.assertEqual(self.get(u, 0x630000), int(not accepted))
                self.assertEqual(bytes(u.mem_read(0x390010, 32)), original)
                self.assertEqual(bytes(u.mem_read(c.LOW, 32)), bytes(range(32)))
                self.assertEqual(bytes(u.mem_read(c.CANVAS, 64)), bytes(range(64)))
                self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x1234)
                if accepted:
                    self.assertEqual(self.get(u, 0x44b1ac), 0x12345)
                    pw = width * 5 // 2
                    pixels = bytes((i % 251 + 1 for i in range(pw * 6)))
                    refs = bytearray()
                    for row in range(2):
                        line = [
                            pixels[row * 3 * pw + ((i + 3) * 5 + 1) // 2 - 8] for i in range(width)
                        ]
                        if mirror:
                            line.reverse()
                            if width % 4 == 2:
                                line[width // 2 - 1], line[width // 2
                                                           ] = line[width // 2
                                                                    ], line[width // 2 - 1]
                        refs.extend(line)
                    if mirror:
                        pixels = b''.join(pixels[i:i + pw][::-1] for i in range(0, len(pixels), pw))
                    self.assertEqual(bytes(u.mem_read(c.BASES[0], len(pixels))), pixels)
                    self.assertEqual(bytes(u.mem_read(c.REFS[0], len(refs))), refs)
                    for a in c.CAM_GUARDS:
                        self.assertEqual(bytes(u.mem_read(a, 256)), b'\xa5' * 256)

    def test_camera_merge_run_copy_matches_pixel_model_and_rejects_stale_views(self):
        for fault in ('none', 'pointer', 'type', 'callback', 'mirror', 'root', 'width', 'invalid'):
            for paused in (False, True):
                with self.subTest(fault=fault, paused=paused):
                    u = self.machine([(c.MERGE, c.camera_merge())])
                    self.camera_fixture(u)
                    fields = {
                        0: 1,
                        12: 0x620000,
                        16: 0x500000,
                        20: 1283,
                        24: 3,
                        28: 4,
                        32: 6,
                        36: 2,
                        40: 8,
                        44: 12,
                        48: 15,
                        52: 6,
                        68: 0x111111,
                        80: 3,
                        88: 0
                    }
                    for off, v in fields.items():
                        self.put(u, c.SLOTS + off, v)
                    pixels = bytes(range(1, 91))
                    refs = bytes(range(11, 23))
                    mask = bytes((1, 1, 0, 1, 1, 1) * 2)
                    u.mem_write(c.BASES[0], pixels)
                    u.mem_write(c.REFS[0], refs)
                    u.mem_write(c.MASKS[0], mask)
                    cache = bytearray(refs)
                    cache[4] = 99
                    for row in range(2):
                        u.mem_write(0x860000 + 1283 + row * 320, bytes(cache[row * 6:row * 6 + 6]))
                    u.mem_write(0x35f3f4, bytes((paused, )))
                    u.mem_write(0x390250, struct.pack('<4h', 4, 4, 6, 5))
                    for name, a, v in (
                        ('pointer', 0x389df8, 0x620004), ('type', c.SLOTS + 80, 4),
                        ('callback', c.SLOTS + 68, 9), ('mirror', c.SLOTS + 88, 64),
                        ('root', c.SLOTS + 16, 0x500001), ('width', c.SLOTS + 32,
                                                           8), ('invalid', c.SLOTS, 0)
                    ):
                        if fault == name:
                            self.put(u, a, v)
                    u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                    self.execute(u, c.MERGE)
                    expected = bytearray(480000)
                    expected_cache = bytearray(cache)
                    if fault == 'none':
                        for y in range(2):
                            for x in range(6):
                                if (not mask[y * 6 + x] or cache[y * 6 + x] != refs[y * 6 + x]):
                                    continue
                                left = ((x + 3) * 5 + 1) // 2 - 8
                                right = ((x + 4) * 5 + 1) // 2 - 8
                                for sy in range(3):
                                    start = (12 + y * 3 + sy) * 800 + 8 + left
                                    expected[start:start + right -
                                             left] = pixels[(y * 3 + sy) * 15 +
                                                            left:(y * 3 + sy) * 15 + right]
                                expected_cache[y * 6 + x] = 0
                    self.assertEqual(bytes(u.mem_read(c.FRAME, 480000)), expected)
                    actual_cache = b''.join(
                        bytes(u.mem_read(0x860000 + 1283 + y * 320, 6)) for y in range(2)
                    )
                    self.assertEqual(actual_cache, expected_cache)
                    self.assertEqual(self.get(u, c.SLOTS + 84), int(fault == 'none'))
                    self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)

    def test_dirty_mask_preparation_and_slot_invalidation(self):
        u = self.machine(c.cameras())
        for a, b in c.initial_data():
            u.mem_write(a, b)
        for i, (valid, dirty) in enumerate(((1, 1), (1, 0), (0, 1))):
            slot = c.SLOTS + i * 128
            for off, v in ((0, valid), (4, dirty), (20, i * 10), (32, 4), (36, 2)):
                self.put(u, slot + off, v)
            for y in range(2):
                u.mem_write(c.MASK + i * 10 + y * 320, bytes((i + 1, 2, 3, 4)))
        self.execute(u, c.PREPARE)
        self.assertEqual(bytes(u.mem_read(c.MASKS[0], 8)), bytes((1, 2, 3, 4) * 2))
        self.assertEqual(bytes(u.mem_read(c.MASKS[1], 8)), bytes(8))
        self.assertEqual(bytes(u.mem_read(c.MASKS[2], 8)), bytes(8))
        self.assertEqual([self.get(u, c.SLOTS + i * 128 + 4) for i in range(3)], [0, 0, 1])
        for index in (0, 1, 2, 3, 0xffffffff):
            uc = self.machine(c.cameras())
            for i in range(3):
                self.put(uc, c.SLOTS + i * 128, 1)
            uc.reg_write(UC_X86_REG_EAX, index)
            uc.reg_write(UC_X86_REG_EFLAGS, 0x247)
            self.execute(uc, c.INVALIDATE, 0x274da9)
            self.assertEqual(
                [self.get(uc, c.SLOTS + i * 128) for i in range(3)],
                [int(i != index) for i in range(3)]
            )
            self.assertEqual(uc.reg_read(UC_X86_REG_ESP), 0x800000 - 20)
            self.assertEqual(uc.reg_read(UC_X86_REG_EAX), index)
            self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x247)


if __name__ == '__main__':
    unittest.main()
