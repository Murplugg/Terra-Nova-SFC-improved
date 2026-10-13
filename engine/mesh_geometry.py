"""Regenerate collision geometry from the owner's verified RESTNOBJ archive.

Recipes retain offsets, traversal order and articulation group labels from the
original renderer traces. They contain no vertex coordinates or model headers.
This is a bounded decoder for twelve pinned stock models, not a general model
interpreter. Unknown inputs/opcodes fail rather than producing guessed geometry.
"""
import hashlib, json, struct
from pathlib import Path
from resource_codec import entries, parts

OUTPUTS = ('cannon_mesh_v66.h', 'vehicle_mesh_v69.h', 'mobile_mesh_v71.h')
AXES = {10: (0, ), 11: (1, ), 12: (2, ), 13: (0, 1), 14: (0, 2), 15: (1, 2), 16: (0, 1, 2)}
sha = lambda data: hashlib.sha256(data).hexdigest()


def read(raw, fmt, at):
    size = struct.calcsize(fmt)
    if at < 0 or at + size > len(raw):
        raise ValueError('Model field outside resource')
    return struct.unpack_from(fmt, raw, at)


def decode(raw, recipe):
    if len(raw) != recipe['size'] or sha(raw) != recipe['sha256']:
        raise ValueError('Model hash/size differs: ' + recipe['tag'])
    if raw[:8].split(b'\0')[0].decode('ascii') != recipe['name']:
        raise ValueError('Model identity differs')
    if read(raw, '<I', 0x4a)[0] + 2 != len(raw):
        raise ValueError('Model bytecode extent differs')
    vertices = {}
    groups = {}
    transforms = []
    previous = -1
    limit = read(raw, '<H', 0x42)[0]

    def vertex(index, value, group):
        if not 0 <= index < limit or index in vertices:
            raise ValueError('Invalid/repeated vertex index')
        if any(not -2**31 <= v < 2**31 for v in value):
            raise ValueError('Vertex arithmetic overflow')
        vertices[index] = list(value)
        groups[index] = group

    for at, op, group in recipe['instructions']:
        if at <= previous or group < 0:
            raise ValueError('Invalid instruction ordering/group')
        previous = at
        if read(raw, '<H', at)[0] != op:
            raise ValueError('Model opcode differs')
        if op == 3:
            count, first = read(raw, '<2H', at + 2)
            for i in range(count):
                vertex(first + i, read(raw, '<3i', at + 6 + i * 12), group)
        elif op == 21:
            vertex(read(raw, '<H', at + 2)[0], read(raw, '<3i', at + 4), group)
        elif op in AXES:
            index, base = read(raw, '<2H', at + 2)
            if base not in vertices or groups[base] != group:
                raise ValueError('Invalid delta-vertex base/group')
            value = vertices[base].copy()
            for i, axis in enumerate(AXES[op]):
                value[axis] += read(raw, '<i', at + 6 + i * 4)[0]
            vertex(index, value, group)
        elif op == 40:
            transforms.append(
                dict(
                    parent=group,
                    param=read(raw, '<H', at + 2)[0],
                    pivot=read(raw, '<3i', at + 4),
                    basis=read(raw, '<9i', at + 16)
                )
            )
        else:
            raise ValueError('Unsupported geometry opcode')
    if sorted(vertices) != list(range(len(vertices))) or not vertices:
        raise ValueError('Non-contiguous geometry vertices')
    faces = []
    if len(set(recipe['faces'])) != len(recipe['faces']):
        raise ValueError('Repeated face offset')
    for at in recipe['faces']:
        if read(raw, '<H', at)[0] != 51:
            raise ValueError('Unsupported face opcode')
        count = read(raw, '<H', at + 0x1e)[0]
        if not 3 <= count <= limit:
            raise ValueError('Invalid face size')
        ids = read(raw, '<' + str(count) + 'H', at + 0x20)
        if any(i not in vertices for i in ids):
            raise ValueError('Face references absent vertex')
        if len({groups[i] for i in ids}) != 1:
            raise ValueError('Face crosses articulation groups')
        faces.append(dict(ids=ids, group=groups[ids[0]]))
    if len(faces) != read(raw, '<H', 0x40)[0]:
        raise ValueError('Incomplete face traversal')
    return dict(
        vertices=[vertices[i] for i in range(len(vertices))],
        groups=[groups[i] for i in range(len(vertices))],
        faces=faces,
        transforms=transforms
    )


def array(items):
    return '{' + ','.join(map(str, items)) + '}'


def triangles(faces):
    return [
        (f['ids'][0], f['ids'][i], f['ids'][i + 1]) for f in faces
        for i in range(1,
                       len(f['ids']) - 1)
    ]


def bounds(vertices):
    if not vertices:
        raise ValueError('Empty articulation group')
    return [min(v[i] for v in vertices)
            for i in range(3)], [max(v[i] for v in vertices) for i in range(3)]


def render(models):
    cannon = ''
    vehicle = ''
    mobile = ''
    definitions = []
    for item, raw, m in models:
        vs = m['vertices']
        tag = item['tag']
        family = item['family']
        if family == 'cannon':
            if len(vs) != 151:
                raise ValueError('Cannon vertex count differs')
            tri = []
            counts = []
            boxes = []
            for low, high in ((51, 139), (139, 151)):
                tri += triangles(
                    [f for f in m['faces'] if low <= min(f['ids']) and max(f['ids']) < high]
                )
                counts.append(len(tri))
                lo, hi = bounds(vs[low:high])
                boxes.append(lo + hi)
            cannon = 'static const int vertices[151][3]={' + ','.join(array(v) for v in vs) + '};\n'
            cannon += 'static const unsigned short triangles[][3]={' + ','.join(
                array(t) for t in tri
            ) + '};\n'
            cannon += f'#define BARREL_START {counts[0]}\n#define TRI_COUNT {counts[1]}\n'
            cannon += 'static const int part_bounds[2][6]={' + ','.join(
                array(b) for b in boxes
            ) + '};\n'
            # These joint values previously lived as constants in the helper C.
            # Read them from the checked model too, so the source package need
            # not carry the stock cannon's pivot coordinates or slanted basis.
            pose = item['cannon_pose']
            upper = m['transforms'][pose['upper_transform']]['pivot']
            barrel = read(raw, '<3i', pose['barrel_pivot'])
            a, b = read(raw, '<2i', pose['barrel_basis'])
            cannon += '#define UPPER_PIVOT ' + array(upper) + '\n'
            cannon += '#define BARREL_PIVOT ' + array(barrel) + '\n'
            cannon += f'#define BARREL_A {a}.0\n#define BARREL_B {b}.0\n'
        elif family == 'vehicle':
            tri = triangles(m['faces'])
            lo, hi = bounds(vs)
            vehicle += f'static const int v{tag}[][3]={{' + ','.join(array(v) for v in vs) + '};\n'
            vehicle += f'static const unsigned short t{tag}[][3]={{' + ','.join(
                array(t) for t in tri
            ) + '};\n'
            vehicle += f'static const B h{tag}[]=' + array(raw[:144]) + ';\n'
            vehicle += f'static const Mesh mesh{tag}={{' + array(lo) + ',' + array(
                hi
            ) + f',{len(vs)},{len(tri)},v{tag},t{tag},h{tag}' + '};\n'
        elif family == 'mobile':
            tri = []
            subparts = []
            if set(m['groups']) != set(range(max(m['groups']) + 1)):
                raise ValueError('Non-contiguous groups')
            for group in range(max(m['groups']) + 1):
                first = len(tri)
                tri += triangles([f for f in m['faces'] if f['group'] == group])
                lo, hi = bounds([v for v, g in zip(vs, m['groups']) if g == group])
                subparts.append((lo, hi, first, len(tri)))
            mobile += f'static const int v{tag}[][3]={{' + ','.join(array(v) for v in vs) + '};\n'
            mobile += f'static const unsigned short t{tag}[][3]={{' + ','.join(
                array(t) for t in tri
            ) + '};\n'
            mobile += f'static const Part p{tag}[]={{' + ','.join(
                '{' + array(lo) + ',' + array(hi) + f',{a},{b}' + '}' for lo, hi, a, b in subparts
            ) + '};\n'
            mobile += f'static const B h{tag}[]=' + array(raw[:144]) + ';\n'
            if m['transforms']:
                if (
                    [t['parent'] for t in m['transforms']] != [0, 1]
                    or [t['param'] for t in m['transforms']] != [0, 1]
                ):
                    raise ValueError('Unexpected joint hierarchy')
                mobile += f'static const Joint j{tag}[]={{' + ','.join(
                    '{' + array(t['pivot']) + ',' + array(t['basis']) + '}' for t in m['transforms']
                ) + '};\n'
            cl, typ = item['kind']
            definitions.append(
                '{' + f'{cl},{typ},{len(subparts)},v{tag},t{tag},p{tag},' +
                (f'j{tag}' if m['transforms'] else '0') + f',h{tag}' + '}'
            )
        else:
            raise ValueError('Unknown mesh family')
    mobile += 'static const Mesh meshes[]={' + ','.join(definitions
                                                        ) + '};\n#define MESH_COUNT ' + str(
                                                            len(definitions)
                                                        ) + '\n'
    # Generated headers use CRLF on every host so their byte hashes are reproducible.
    return {
        name: text.replace('\n', '\r\n').encode('ascii')
        for name, text in zip(OUTPUTS, (cannon, vehicle, mobile))
    }


def generate(archive, recipe):
    if recipe['schema'] != 1 or sha(archive) != recipe['archive_sha256']:
        raise ValueError('Unsupported original model archive')
    rows = entries(archive)
    models = []
    for item in recipe['models']:
        entry, data = rows[item['resource']]
        if entry[5] != 2:
            raise ValueError('Expected uncompressed compound resource')
        raw = parts(data)[item['part']][:item['size']]
        models.append((item, raw, decode(raw, item)))
    result = render(models)
    if {name: sha(data) for name, data in result.items()} != recipe['outputs']:
        raise ValueError('Regenerated collision geometry differs from accepted headers')
    return result


def build_headers(archive_path, recipe_path, output):
    output = Path(output)
    if output.exists():
        raise ValueError('Mesh output must be new')
    recipe = json.loads(Path(recipe_path).read_text(encoding='utf-8'))
    result = generate(Path(archive_path).read_bytes(), recipe)
    output.mkdir(parents=True)
    for name, data in result.items():
        (output / name).write_bytes(data)
    report = dict(
        archive_sha256=recipe['archive_sha256'],
        models=len(recipe['models']),
        headers={
            n: sha(b)
            for n, b in result.items()
        },
        source='Verified original resource archive; no saved game/render trace read'
    )
    (output / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
