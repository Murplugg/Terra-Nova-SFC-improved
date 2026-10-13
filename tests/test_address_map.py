"""Address conversion uses synthetic PE/LE layouts and patch ownership examples.

These tests target file-versus-memory mistakes, zero-fill and overlapping writes.
They do not claim a live DOSBox/native gameplay comparison.
"""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import address_map as mapping


def pe():
    data = bytearray(0x700)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', data, 0x86, 2)
    struct.pack_into('<H', data, 0x94, 224)
    struct.pack_into('<H', data, 0x98, 0x10b)
    struct.pack_into('<I', data, 0x98 + 28, 0x10000)
    for index, (rva, size, raw) in enumerate(((0x1000, 0x100, 0x300), (0x3000, 0x200, 0x500))):
        at = 0x178 + index * 40
        data[at:at + 8] = b'.test\0\0\0'
        struct.pack_into('<4I', data, at + 8, size, rva, size, raw)
    return data


class AddressMapTests(unittest.TestCase):

    def test_pe_file_offsets_follow_each_section(self):
        base, sections = mapping.pe_sections(pe())
        self.assertEqual(base, 0x10000)
        self.assertEqual(mapping.file_offset(sections, 0x11010, 0x11020), 0x310)
        self.assertEqual(mapping.file_offset(sections, 0x13100, 0x13200), 0x600)
        for start, end in ((0x11100, 0x11101), (0x110ff, 0x13001), (0x13100, 0x13100)):
            with self.assertRaises(ValueError):
                mapping.file_offset(sections, start, end)

    def test_pe_rejects_truncation_wrong_format_and_overlap(self):
        cases = [b'', bytes(128), pe()[:0x190]]
        data = pe()
        struct.pack_into('<H', data, 0x98, 0x20b)
        cases.append(data)
        data = pe()
        struct.pack_into('<I', data, 0x178 + 40 + 12, 0x1080)
        cases.append(data)
        data = pe()
        struct.pack_into('<I', data, 0x178 + 20, 0x10000)
        cases.append(data)
        for data in cases:
            with self.assertRaises(ValueError):
                mapping.pe_sections(data)

    def test_le_pages_keep_embedded_header_offset_and_zero_fill(self):
        header = bytearray(0xc4)
        struct.pack_into('<I', header, 0x14, 3)
        struct.pack_into('<I', header, 0x2c, 0x80)
        struct.pack_into('<I', header, 0x48, 0x100)
        struct.pack_into('<I', header, 0x80, 0x400)
        data = bytearray(0x4000)
        for i in range(3):
            data[0x180 + i * 4:0x184 + i * 4] = (i + 1).to_bytes(3, 'big') + b'\0'
        le = SimpleNamespace(
            h=header,
            data=data,
            le=0x80,
            mz=0x40,
            objects=[[0x1800, 0, 0, 1, 1, 0], [0x20, 0, 0, 2, 1, 0], [0x180, 0, 0, 3, 1, 0]]
        )
        rows = mapping.original_regions(le)
        code = [r for r in rows if r['object'] == 1]
        self.assertEqual([r['file_offset'] for r in code], [0x440, None])
        self.assertEqual(code[0]['end'] - code[0]['start'], 0x1000)
        last = [r for r in rows if r['object'] == 3]
        self.assertEqual([r['file_offset'] for r in last], [0x2440, None])
        self.assertEqual(last[0]['end'] - last[0]['start'], 0x80)
        self.assertIsNone(next(r for r in rows if r['object'] == 2)['guest_base'])

    def test_slices_do_not_invent_original_locations_for_helpers(self):
        regions = [dict(start=10, end=20), dict(start=30, end=35)]
        pieces = list(mapping.slices(8, 40, regions))
        self.assertEqual(
            [(a, b) for a, b, _ in pieces], [(8, 10), (10, 20), (20, 30), (30, 35), (35, 40)]
        )
        self.assertEqual([r is None for _, _, r in pieces], [True, False, True, False, True])

    def test_contiguous_virtual_memory_does_not_imply_contiguous_file(self):
        a = dict(start=10, end=20, object=1, file_offset=100)
        b = dict(start=20, end=30, object=1, file_offset=200)
        self.assertFalse(mapping.can_merge(a, b))
        b['file_offset'] = 110
        self.assertTrue(mapping.can_merge(a, b))
        b['file_offset'] = None
        self.assertFalse(mapping.can_merge(a, b))

    def test_foundation_ranges_exclude_final_feature_writes(self):
        self.assertEqual(
            list(mapping.remove_covered(10, 40, [(0, 12), (15, 20), (30, 50)])),
            [(12, 15), (20, 30)]
        )
        self.assertEqual(list(mapping.remove_covered(10, 40, [(0, 50)])), [])
        self.assertEqual(list(mapping.remove_covered(10, 40, [])), [(10, 40)])

    def test_audit_validates_last_writer_index_and_surviving_bytes(self):
        native = b'abcXYf'
        sections = [dict(start=100, end=106, file_offset=0)]
        audit = dict(
            schema=1,
            writes=[
                dict(
                    start=100,
                    end=106,
                    module='terrain-foundation',
                    after_sha256=mapping.digest(b'abcdef')
                ),
                dict(start=103, end=105, module='logical-hud', after_sha256=mapping.digest(b'XY')),
            ],
            final_spans=[
                dict(start=100, end=103, write=0),
                dict(start=103, end=105, write=1),
                dict(start=105, end=106, write=0)
            ]
        )
        spans, checked = mapping.audit_spans(audit, native, sections)
        self.assertEqual(checked, 1)
        self.assertEqual(len(spans), 3)
        with self.assertRaises(ValueError):
            mapping.audit_spans(audit, b'abcZZf', sections)
        audit['final_spans'][0]['end'] = 104
        with self.assertRaises(ValueError):
            mapping.audit_spans(audit, native, sections)

    def test_unverified_executables_are_rejected_before_mapping(self):
        with self.assertRaises(ValueError):
            mapping.build_tables(b'unverified original', b'unverified native', {}, [])


if __name__ == '__main__':
    unittest.main()
