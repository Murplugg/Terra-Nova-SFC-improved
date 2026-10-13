"""Check the final foundation's viewport, coverage and frame-copy contracts.

These synthetic x86 fixtures model original rendering/canvas calls at explicit
boundaries. Expected pixels come from simple geometry, independently of the
assembly. They protect clipping, odd-width copying and callback ordering during
source cleanup; they do not establish correctness in every in-game HUD state.
"""
import struct, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import foundation_hud as h
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EFLAGS


class FoundationHudTests(unittest.TestCase):

    def machine(self, spans):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0xa00000)
        for a, b in spans:
            u.mem_write(a, b)
        u.reg_write(UC_X86_REG_ESP, 0x800000)
        u.mem_write(0x800000, struct.pack('<I', 0x1000))
        return u

    def put(self, u, a, v):
        u.mem_write(a, struct.pack('<I', v))

    def get(self, u, a):
        return int.from_bytes(u.mem_read(a, 4), 'little')

    def test_world_dimensions_are_bounded_and_context_is_restored(self):
        cases = (
            (12, 21, 296, 99, 320, True, True), (0, 0, 320, 190, 320, True, True),
            (3, 23, 314, 98, 320, False, True), (317, 198, 3, 2, 320, False, True),
            (0, 0, 0, 99, 320, False, False), (0, 0, 296, 0, 320, False, False),
            (319, 0, 2, 2, 320, False, False), (0, 199, 2, 2, 320, False, False),
            (0, 0, 296, 99, 640, False, False), (0, 200, 2, 2, 320, False, False)
        )
        for x, y, w, height, stride, legacy_ok, bounded_ok in cases:
            with self.subTest(view=(x, y, w, height, stride)):
                u = self.machine([(h.WORLD, h.assemble(h.WORLD, h.world_source()))])
                self.put(u, 0x446f78, 0x500000)
                self.put(u, h.CTX + 28, 0x600000)
                original = struct.pack('<8I', 65536, 65536, 11, 22, 33, 44, 0, 0x600000)
                u.mem_write(h.CTX, original)
                self.put(u, 0x600000, 0x500000 + y * 320 + x)
                u.mem_write(0x600008, struct.pack('<HHH', w, height, stride))
                u.mem_write(0x449, b'\x6b')
                self.put(u, 0x41ec80, 0x700004)
                self.put(u, 0x700000, 0x80004)
                # Original renderer and canvas switch are the explicit model boundary.
                u.mem_write(0x9a36e8, h.assemble(0x9a36e8, 'inc dword ptr [0x620000]; ret;'))
                u.mem_write(0x2eab30, h.assemble(0x2eab30, 'mov [0x44b1a0],eax; ret;'))
                u.reg_write(UC_X86_REG_EDX, h.CTX)
                u.reg_write(UC_X86_REG_EAX, 0x12345678)
                u.emu_start(h.WORLD, 0x1000, count=200000)
                accepted = bounded_ok
                self.assertEqual(self.get(u, h.READY), int(accepted))
                self.assertEqual(self.get(u, h.DATA + 32), int(not accepted))
                self.assertEqual(self.get(u, 0x620000), int(accepted))
                self.assertEqual(bytes(u.mem_read(h.CTX, 32)), original)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x12345678)
                self.assertEqual(u.reg_read(UC_X86_REG_EDX), h.CTX)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x800004)
                if accepted:
                    left = (x * 5 + 1) // 2
                    right = ((x + w) * 5 + 1) // 2
                    self.assertEqual(
                        struct.unpack('<6I', u.mem_read(h.DATA, 24)),
                        (left, y * 3, right, (y + height) * 3, right - left, height * 3)
                    )
                    self.assertEqual(
                        struct.unpack('<HHH', u.mem_read(h.CANVAS + 8, 6)),
                        (right - left, height * 3, right - left)
                    )
                    self.assertEqual(bytes(u.mem_read(0x700004 + h.CAPACITY, 256)), b'\xa5' * 256)

    def test_panel_coverage_respects_geometry_including_hidden_widgets(self):
        for bounds in ((1, 2, 5, 4), (-1, 0, 3, 2), (0, 0, 321, 2), (0, 0, 2, 201), (5, 2, 1, 4)):
            for hidden in (False, True):
                u = self.machine([(h.COVER, h.assemble(h.COVER, h.cover_source()))])
                self.put(u, 0x389dec, 0x610000)
                self.put(u, 0x389de8, 0x610000)
                self.put(u, 0x610014, 0x265028)
                u.mem_write(0x610008, struct.pack('<4h', *bounds))
                u.mem_write(0x610020, bytes([0x20 if hidden else 0]))
                u.mem_write(h.MASK - 16, b'\xa5' * 16 + b'\xff' * 64000 + b'\xa5' * 16)
                u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                u.emu_start(h.COVER, 0x1000, count=1000)
                expected = bytearray(b'\xff' * 64000)
                if bounds == (1, 2, 5, 4):
                    for y in (2, 3):
                        expected[y * 320 + 1:y * 320 + 5] = bytes(4)
                self.assertEqual(
                    bytes(u.mem_read(h.MASK - 16, 64032)), b'\xa5' * 16 + expected + b'\xa5' * 16
                )
                self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x800004)

    def test_fast_compositor_copies_remainder_and_orders_camera_callbacks(self):
        for width in (4, 5, 6, 7, 17):
            with self.subTest(width=width):
                u = self.machine([(h.FAST, h.fast_compositor(prepare=0x1100, merge=0x1200))])
                u.mem_map(0xe0000000, 0x76000)
                self.put(u, 0x446f78, 0x500000)
                self.put(u, h.READY, 1)
                # No low HUD coverage: copied world pixels must survive composition.
                u.mem_write(h.MASK, b'\xff' * 64000)
                u.mem_write(h.FRAME, b'\x77' * 480000)
                u.mem_write(h.PIXELS, bytes(range(1, width * 2 + 1)))
                u.mem_write(h.DATA, struct.pack('<6I', 10, 12, 10 + width, 14, width, 2))
                # Distinct state transitions verify preparation -> coverage -> merge.
                u.mem_write(0x1100, h.assemble(0x1100, 'mov dword ptr [0x620000],1; ret;'))
                u.mem_write(
                    h.COVER,
                    h.assemble(
                        h.COVER, (
                            "mov eax,[0x620000];"
                            " mov [0x620004],eax;"
                            " inc dword ptr [0x620000];"
                            " ret;"
                        )
                    )
                )
                u.mem_write(
                    0x1200, h.assemble(0x1200, 'mov eax,[0x620000]; mov [0x620008],eax; ret;')
                )
                u.reg_write(UC_X86_REG_EAX, 0)
                u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                u.emu_start(h.FAST, 0x1000, count=6000000)
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x800004)
                self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0)
                self.assertEqual(struct.unpack('<3I', u.mem_read(0x620000, 12)), (2, 1, 2))
                for y in range(2):
                    expected = bytes(range(1 + y * width, 1 + (y + 1) * width))
                    at = (12 + y) * 800 + 10
                    self.assertEqual(bytes(u.mem_read(h.FRAME + at, width)), expected)
                    self.assertEqual(bytes(u.mem_read(0xe0000000 + at, width)), expected)
                self.assertEqual(self.get(u, h.BUSY), 0)


if __name__ == '__main__':
    unittest.main()
