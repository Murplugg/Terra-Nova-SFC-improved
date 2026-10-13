"""Install HUD helpers after checking every hook, buffer and guard byte.

Expected instructions identify the original game or a required feature. New
storage must be empty. Map code, context and buffers are supplied explicitly
so a missing dependency fails before any part of the HUD is written.
"""
import struct
from features import hud


def install_logical(write, read, original):
    from features import maps
    return install(
        write,
        read,
        map_payload=maps.bodies(original),
        map_hooks=maps.hooks(),
        map_slot=maps.SLOT,
        map_context=maps.CTX,
        map_buffers=maps.BUFFERS
    )


def verify_logical(read, original):

    def reject(a, b):
        raise ValueError('Logical HUD installation incomplete')

    if not install_logical(reject, read, original)['already_installed']:
        raise ValueError('Logical HUD installation incomplete')
    return True


def visual_pieces():
    from features import maps, input_views
    return maps.persistence_bodies() + input_views.sky_bodies()


def install_visual(write, read):
    from features import maps, input_views
    extras = [
        (a, asm(a, 'cmp ebp,0x10000') if a == 0x2a81a2 else bytes(len(b)), b)
        for a, b in input_views.sky_bodies()
    ]
    return maps.install_persistence(write, read, extras=extras)


def verify_visual(ram, original):
    from features import maps

    def reject(a, b):
        raise ValueError('HUD visual installation incomplete')

    if not install_visual(reject, lambda a, n: ram[a:a + n])['already_installed']:
        raise ValueError('HUD visual installation incomplete')
    # Map persistence supersedes three logical helpers. Restore only those
    # declared spans in a verification copy; never mutate live data.
    shadow = bytearray(ram)
    before = dict(hud.dispatch_bodies(maps.bodies(original), maps.hooks(), maps.SLOT)[0])
    for a, b in visual_pieces():
        if a in before:
            old = before[a].ljust(max(len(before[a]), len(b)), b'\0')
            shadow[a:a + len(old)] = old
    return verify_logical(lambda a, n: shadow[a:a + n], original)


def verify_visibility(ram, original):
    from features.cameras import visibility_predecessor_view
    return verify_visual(visibility_predecessor_view(ram), original)


def providers():
    """Displaced original hooks and already installed low-row/target providers."""
    from patch_support import asm
    from features import target_picking as pick
    out = {pick.RENDER: asm(pick.RENDER, pick.render_source(pick.ORIGINAL_RENDER))}
    for site, target in (
        (pick.SITE, pick.ENTRY), (0x2e43d0, 0x9ab6e8), (0x268098, 0x9b02e8), (0x9ab8e8, 0x9ae6e8),
        (0x2f25ae, 0x9af0e8), (0x2e54e0, 0x9af2e8), (0x274da4, 0x9d9400), (0x27be1c, 0x1dfc000),
        (0x2454bc, 0xa11200), (0x245600, 0xa11600)
    ):
        out[site] = asm(site, f'jmp {target}')
    for site in (0x2afb47, 0x2afb6a, 0x2afb82):
        out[site] = asm(site, 'call 0x9bb0e8')
    for site, source in (
        (0x2afbad, 'call 0x9bb4e8;nop'),
        (0x276ef8, ("push ebx;"
                    "push ecx;"
                    "push esi;"
                    "push edi;"
                    "push ebp")), (0x276fa6, 'call dword ptr [ecx+0x238]'),
        (0x261bd8, 'push ebx;push ecx;push edx;mov edx,[0x389dec]'),
        (0x2e3f90, ("push ebx;"
                    "push ecx;"
                    "push edx;"
                    "push esi;"
                    "push edi")), (0x2617e6, 'call 0x2617f4'), (0x2633f0, 'jmp 0x2633ff')
    ):
        out[site] = asm(site, source)
    return out


def regions(map_buffers):
    return ((hud.CACHE, 128000), (hud.MASK, 128000),
            (hud.TEMP, 128000)) + tuple((a, 12800)
                                        for a in (*hud.REFS, *hud.MASKS)) + tuple(map_buffers)


def validate_guards(read, map_buffers):
    for address, size in regions(map_buffers):
        for at in (address - 256, address + size):
            if bytes(read(at, 256)) != b'\xa5' * 256:
                raise ValueError('HUD/map buffer guard differs at ' + hex(at))
    return len(regions(map_buffers)) * 2


def install(write, read, *, map_payload, map_hooks, map_slot, map_context, map_buffers):
    payload, hooks = hud.dispatch_bodies(map_payload, map_hooks, map_slot)
    pieces = payload + hooks
    expected_providers = providers()
    if not expected_providers.keys() <= {a for a, b in pieces}:
        raise ValueError('Missing HUD hook provider')
    occupied = []
    for a, b in pieces:
        if not b or not 0x11000 <= a < a + len(b) <= 0x2000000:
            raise ValueError('Invalid HUD provider span')
        if any(a < hi and lo < a + len(b) for lo, hi in occupied):
            raise ValueError('Overlapping HUD providers')
        occupied.append((a, a + len(b)))
    current = [bytes(read(a, len(b))) for a, b in pieces]
    if all(now == b for now, (_, b) in zip(current, pieces)):
        validate_guards(read, map_buffers)
        return dict(already_installed=True, ranges=[])
    for now, (a, b) in zip(current, pieces):
        if len(now) != len(b):
            raise ValueError('Short HUD provider read')
        expected = expected_providers.get(a)
        if expected is None:
            if any(now):
                raise ValueError('HUD reservation occupied at ' + hex(a))
        elif now != expected:
            raise ValueError('HUD hook provider differs at ' + hex(a))
    empty = (
        (hud.CACHE, 128000), (hud.MASK, 128000), (hud.TEMP, 128000), (hud.STATE, 0x600),
        (map_context, 0x400)
    ) + tuple(map_buffers)
    for a, n in empty:
        if bytes(read(a, n)) != bytes(n):
            raise ValueError('HUD/map storage occupied at ' + hex(a))
    pieces.append((hud.STATE, bytes(0x600)))
    for i in range(3):
        pieces.append(
            (hud.SLOTS + i * 128 + 56, struct.pack('<3I', hud.BASES[i], hud.REFS[i], hud.MASKS[i]))
        )
    for a, n in regions(map_buffers):
        for at in (a - 256, a + n):
            if bytes(read(at, 256)) != bytes(256):
                raise ValueError('HUD guard reservation occupied at ' + hex(at))
            pieces.append((at, b'\xa5' * 256))
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])


from patch_support import asm

LOW_COVER = 0x9b84e8
COMPASS_SLOTS = ((LOW_COVER, 0x400), (hud.COVER, 0x1000))


def compass_bodies(original=False):
    from features.hud import coverage_source
    result = [
        (LOW_COVER, asm(LOW_COVER, coverage_source(high_rows=False, compass=not original))),
        (hud.COVER, hud.code(hud.COVER, coverage_source(compass=not original)))
    ]
    for (a, b), (at, cap) in zip(result, COMPASS_SLOTS):
        assert a == at and len(b) < cap
    return result


def compass_installed(r):
    a, b = compass_bodies()[1]
    return bytes(r[a:a + len(b)]) == b


def verify_compass(r):
    for a, b in compass_bodies():
        assert bytes(r[a:a + len(b)]) == b, (hex(a), 'compass code')
    return True


def compass_predecessors():
    new = dict(compass_bodies())
    # The low-row provider retains ten NOPs after its shorter coverage routine.
    return [
        (
            a, b + (b'\x90' * 10 if a == LOW_COVER else b'') +
            bytes(len(new[a]) - len(b) - (10 if a == LOW_COVER else 0))
        ) for a, b in compass_bodies(original=True)
    ]


def install_compass(write, r):
    if compass_installed(r):
        verify_compass(r)
        return dict(ranges=[], already_installed=True)
    new = compass_bodies()
    old = dict(compass_predecessors())
    for a, b in new:
        assert len(b) >= len(old[a])
        assert bytes(r[a:a + len(b)]) == old[a], (hex(a), 'compass predecessor/padding')
    for a, b in new:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in new])


def compass_predecessor_view(r):
    verify_compass(r)
    shadow = bytearray(r)
    for a, b in compass_predecessors():
        shadow[a:a + len(b)] = b
    return shadow


FAST_CODE = 0x1e4a800
FAST_END = FAST_CODE + 0x800
FAST_SITE = hud.COMPOSE


def fast_candidate(address=FAST_CODE):
    from features.hud import fast_compose_source
    return hud.code(address, fast_compose_source())


def fast_predecessor():
    from features.hud import bodies
    return dict(bodies())[FAST_SITE]


def fast_bodies():
    b = fast_candidate()
    assert len(b) <= FAST_END - FAST_CODE
    return [(FAST_CODE, b), (FAST_SITE, asm(FAST_SITE, f'jmp {FAST_CODE}'))]


def fast_installed(r):
    return bytes(r[FAST_SITE:FAST_SITE + 5]) == dict(fast_bodies())[FAST_SITE]


def verify_fast(r):
    assert all(bytes(r[a:a + len(b)]) == b for a, b in fast_bodies())
    old = fast_predecessor()
    assert bytes(r[FAST_SITE + 5:FAST_SITE + len(old)]) == old[5:]
    return True


def fast_predecessor_view(r):
    verify_fast(r)
    r = bytearray(r)
    r[FAST_SITE:FAST_SITE + 5] = fast_predecessor()[:5]
    r[FAST_CODE:FAST_END] = bytes(FAST_END - FAST_CODE)
    return r


def install_fast(write, r):
    if fast_installed(r):
        verify_fast(r)
        return dict(ranges=[])
    old = fast_predecessor()
    assert bytes(r[FAST_SITE:FAST_SITE + len(old)]) == old, 'Unexpected HUD compositor provider'
    assert not any(r[FAST_CODE:FAST_END]), 'Reserved compositor capacity occupied'
    pieces = fast_bodies()
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
