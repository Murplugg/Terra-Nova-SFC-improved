"""Candidate resource fix: select room actions from the pointer on a click.

Retail RESBABL2 resource 1001 parts 6/7 select their next room from global 4.
Hover events populate it, but a mouse-down can arrive before the hover poll.
Refresh only their click branches using the existing rectangle API 29. Also
replace the three cached-rectangle API 20 calls in the base/medals handlers.
Original offsets, hover text, keyboard paths and transition code stay intact.
This does not queue input or execute a room VM reentrantly.
"""
import hashlib
import struct
from resource_codec import entries, parts, compound, archive, replace
from resource_transforms import Script

SOURCE_SHA = '2c5e20c6d65e46e6d9eda31ad2b06de575a1055265e6c70574081ea171ff6ea8'
RESULT_SHA = '5a8918e2fd7ca96bc6c1a364a6c7a6ef076f28c7c05a4601bb6e704f9524ae94'
# Original click marker, part, and hotspot -> next-room action.
ROOMS = ((6, 0x613, 931, (0, 12, 15, 3, 9, 20, 666)), (7, 0x89e, 1035, (0, 1, 16, 20)))
CACHED_CALLS = ((7, 0x8a1), (8, 0xabc), (8, 0xcb7))
EXIT_HOOK = (8, 0xcc1, bytes.fromhex('7f9204'))


def selector(origin, actions, resume):
    s = Script(origin)
    s.call(29, drop=False)
    for rectangle, action in enumerate(actions):
        s.val(rectangle)
        s.branch(0x2b, f'next{rectangle}')
        # Global address (opcode 08), not the local address used by Script.set.
        s.raw('080400')
        s.val(action)
        s.raw('23')
        s.branch(0x2d, 'done')
        s.label(f'next{rectangle}')
    s.raw('080400')
    s.val(0)
    s.raw('23')
    s.label('done')
    s.raw('0e')
    s.branch(0x2d, resume)
    return s.finish()


def patch(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('Room-click candidate requires the accepted retail menu overlay')
    rows = entries(raw)
    ps = parts(rows[1001][1])
    offsets = [sum(map(len, ps[:i])) for i in range(len(ps))]
    original_length = sum(map(len, ps))
    extra = bytearray()
    hooks = []
    for part, site, line, actions in ROOMS:
        at = site - offsets[part]
        marker = b'\x7f' + struct.pack('<H', line)
        assert ps[part][at:at + 3] == marker
        target = original_length + len(extra)
        payload = selector(target, actions, site + 3)
        ps[part] = ps[part][:at] + b'\x2d' + struct.pack('<H', target) + ps[part][at + 3:]
        extra.extend(payload)
        hooks.append(dict(part=part, site=site, target=target, bytes=len(payload)))
    for part, site in CACHED_CALLS:
        at = site - offsets[part]
        assert ps[part][at:at + 4] == bytes.fromhex('2a140000')
        ps[part] = ps[part][:at] + bytes.fromhex('2a1d0000') + ps[part][at + 4:]
    # The medals Exit hover also sets global 4 to quarters. A fresh rectangle
    # alone is insufficient: a rapid click can still leave global 4 at medals.
    # Update it only on the confirmed Exit branch, then run the original pop
    # and cleanup jump. Other medal clicks and keyboard exits are untouched.
    part, site, old = EXIT_HOOK
    at = site - offsets[part]
    target = original_length + len(extra)
    assert ps[part][at:at + len(old)] == old
    payload = bytes.fromhex('0804000101232d') + struct.pack('<H', site + len(old))
    ps[part] = ps[part][:at] + b'\x2d' + struct.pack('<H', target) + ps[part][at + len(old):]
    extra.extend(payload)
    hooks.append(dict(part=part, site=site, target=target, bytes=len(payload)))
    # Append to the final part: preserve the compound header and all old starts.
    ps[-1] += extra
    assert sum(map(len, ps)) + 2 + 4 * (len(ps) + 1) < 65536
    replace(rows, 1001, compound(ps))
    result = archive(rows)
    assert hashlib.sha256(result).hexdigest() == RESULT_SHA
    return result, dict(
        hooks=hooks,
        cached_calls=[a for _, a in CACHED_CALLS],
        appended_bytes=len(extra),
        original_offsets_preserved=True
    )
