"""Synthetic format checks; owner-resource byte equivalence is a build gate."""
from pathlib import Path
import hashlib, json, struct, sys, tempfile, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import mesh_geometry as mesh


def fixture():
    raw = bytearray(230)
    raw[:4] = b'test'
    struct.pack_into('<HH', raw, 0x40, 1, 3)
    struct.pack_into('<I', raw, 0x4a, len(raw) - 2)
    for i, point in enumerate(((0, 0, 0), (10, 0, 0), (0, 10, 0))):
        struct.pack_into('<HH3i', raw, 144 + 16 * i, 21, i, *point)
    struct.pack_into('<H', raw, 192, 51)
    struct.pack_into('<H3H', raw, 222, 3, 0, 1, 2)
    recipe = dict(
        tag='test',
        size=len(raw),
        name='test',
        instructions=[[144, 21, 0], [160, 21, 0], [176, 21, 0]],
        faces=[192]
    )
    return raw, recipe


def decode(raw, recipe):
    recipe['sha256'] = hashlib.sha256(raw).hexdigest()
    return mesh.decode(raw, recipe)


class MeshGeometryTests(unittest.TestCase):

    def test_triangle_and_bounds(self):
        raw, r = fixture()
        m = decode(raw, r)
        self.assertEqual(mesh.triangles(m['faces']), [(0, 1, 2)])
        self.assertEqual(mesh.bounds(m['vertices']), ([0, 0, 0], [10, 10, 0]))

    def test_delta_vertex_and_overflow(self):
        raw, r = fixture()
        r['instructions'][2][1] = 10
        struct.pack_into('<HHHi', raw, 176, 10, 2, 1, 5)
        self.assertEqual(decode(raw, r)['vertices'][2], [15, 0, 0])
        struct.pack_into('<i', raw, 164, 2**31 - 1)
        with self.assertRaisesRegex(ValueError, 'overflow'):
            decode(raw, r)

    def test_bad_opcode_and_delta_base(self):
        raw, r = fixture()
        struct.pack_into('<H', raw, 144, 22)
        with self.assertRaisesRegex(ValueError, 'opcode'):
            decode(raw, r)
        raw, r = fixture()
        r['instructions'][0][1] = 10
        struct.pack_into('<HHHi', raw, 144, 10, 0, 2, 5)
        with self.assertRaisesRegex(ValueError, 'base/group'):
            decode(raw, r)

    def test_face_membership_and_group_boundaries(self):
        raw, r = fixture()
        struct.pack_into('<H', raw, 228, 3)
        with self.assertRaisesRegex(ValueError, 'absent vertex'):
            decode(raw, r)
        raw, r = fixture()
        r['instructions'][2][2] = 1
        with self.assertRaisesRegex(ValueError, 'articulation'):
            decode(raw, r)

    def test_repeated_vertices_faces_and_missing_faces(self):
        raw, r = fixture()
        struct.pack_into('<H', raw, 178, 1)
        with self.assertRaisesRegex(ValueError, 'repeated vertex'):
            decode(raw, r)
        raw, r = fixture()
        r['faces'] *= 2
        with self.assertRaisesRegex(ValueError, 'Repeated face'):
            decode(raw, r)
        raw, r = fixture()
        r['faces'] = []
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            decode(raw, r)

    def test_truncation_and_identity(self):
        raw, r = fixture()
        r['size'] -= 1
        struct.pack_into('<I', raw, 0x4a, r['size'] - 2)
        with self.assertRaisesRegex(ValueError, 'outside resource'):
            decode(raw[:-1], r)
        raw, r = fixture()
        r['name'] = 'other'
        with self.assertRaisesRegex(ValueError, 'identity'):
            decode(raw, r)

    def test_changed_archive_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            archive = root / 'archive'
            recipe = root / 'recipe.json'
            out = root / 'new'
            archive.write_bytes(b'changed original')
            recipe.write_text(json.dumps(dict(schema=1, archive_sha256='0' * 64)))
            with self.assertRaisesRegex(ValueError, 'Unsupported original'):
                mesh.build_headers(archive, recipe, out)
            self.assertFalse(out.exists())

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sentinel = root / 'keep'
            sentinel.write_bytes(b'preserve')
            with self.assertRaisesRegex(ValueError, 'must be new'):
                mesh.build_headers(root / 'absent', root / 'absent', root)
            self.assertEqual(sentinel.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
