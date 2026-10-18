"""Export snapshot declarations from the renderer plan used by this build."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

EXPECTED = 'cdf5467a4d8e7b083fce34edda76dcaaaebba003cf63de43824fb3711eb2b8eb'


@dataclass(frozen=True)
class Contract:
    guards: tuple
    external: tuple
    arena_size: int
    restore_zero: tuple


def capture(integration):
    from features import hud, maps
    from features.render_arena import BASE, SIZE, Layout

    expected = Layout(BASE)
    for name, value in vars(expected).items():
        if getattr(integration, name, None) != value:
            raise ValueError('Renderer snapshot ABI differs: ' + name)
    guards = list(expected.guard_edges())
    regions = ((hud.CACHE, 128000), (hud.MASK, 128000), (hud.TEMP, 128000))
    regions += tuple((address, 12800) for address in (*hud.REFS, *hud.MASKS))
    regions += maps.BUFFERS
    guards += [edge for address, size in regions for edge in (address - 256, address + size)]
    if len(guards) != 78:
        raise ValueError('Unexpected snapshot guard layout')
    external = []
    spans = []
    for address, data in integration.writes:
        if address < BASE:
            continue
        if not BASE <= address < address + len(data) <= BASE + SIZE:
            raise ValueError('Snapshot payload outside renderer arena')
        external.append((address, len(data), hashlib.sha256(data).hexdigest()))
        spans.append((address, address + len(data)))
    ordered = sorted(spans)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Overlapping snapshot payloads')
    if not external:
        raise ValueError('Snapshot export requires a built renderer plan')
    return Contract(tuple(guards), tuple(external), SIZE, ())


def encode(contract, revision=120):
    if not isinstance(contract, Contract):
        raise TypeError('An explicit renderer snapshot contract is required')
    if type(revision) is not int or not 90 <= revision <= 65535:
        raise ValueError('Invalid snapshot revision')
    external = [dict(address=a, size=n, sha256=digest) for a, n, digest in contract.external]

    def serialize(value):
        return (
            json.dumps(dict(revision=value, arena_size=contract.arena_size,
                            guards=contract.guards, external=external,
                            restore_zero=[dict(address=a, size=n)
                                          for a, n in contract.restore_zero]), indent=2) +
            '\n'
        ).encode()

    data = serialize(120)
    if hashlib.sha256(data).hexdigest() != EXPECTED:
        raise ValueError(
            'Snapshot layout differs from the pinned runtime contract: ' +
            hashlib.sha256(data).hexdigest()
        )
    # Validate the renderer against its fixed compatibility layout,
    # then record the engine identity. A matching layout alone does not establish
    # compatibility with a snapshot from a different engine.
    if revision != 120:
        data = serialize(revision)
    return data


def export(path, revision=120, *, contract):
    Path(path).write_bytes(encode(contract, revision))
