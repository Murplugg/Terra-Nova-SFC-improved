"""Adapt menu artwork, labels and demo resources for the native game."""
import struct
from resource_codec import entries, archive, parts, compound, replace, decode, encode


def build_menu(path):
    rows = entries(path.read_bytes())
    ps = parts(rows[1003][1])
    assert len(ps) == 34
    # The optional prequel returns to its menu without replaying the retail intro.
    # Leave all bytecode addresses intact by jumping over the two movie calls.
    init = bytearray(ps[3])
    a = init.index(bytes.fromhex('7ff000'))
    b = init.index(bytes.fromhex('7ff200'))
    init[a:a + 3] = b'\x2d' + struct.pack('<H', sum(map(len, ps[:3])) + b)
    ps[3] = bytes(init)
    body = ps[31]
    start = body.index(bytes.fromhex('7f1504'))
    end = body.index(bytes.fromhex('01022b'), start)
    first = body[start:end]
    assert first.endswith(bytes.fromhex('2d3216'))
    first = first.replace(bytes.fromhex('0b0200010223'), bytes.fromhex('0b0200010423'))
    # Existing branch addresses refer to bytecode after the compound header.
    appended = sum(map(len, ps))
    assert appended < 65536
    marker = bytes.fromhex('01042bb4157f4804')
    i = body.index(marker) + 5
    body = body[:i] + b'\x2d' + struct.pack('<H', appended) + body[i + 3:]
    for old, new in ((2, 1), (3, 2), (4, 3)):
        pattern = bytes.fromhex('0b020001') + bytes([old]) + b'\x23'
        assert body.count(pattern) == 1
        body = body.replace(pattern, bytes.fromhex('0b020001') + bytes([new]) + b'\x23')
    ps[31] = body
    ps[-1] += first
    replace(rows, 1003, compound(ps))
    labels = parts(rows[1004][1])
    for i, s in {
        6: '1. Johnson Steading',
        5: '2. Thompson Steading',
        4: '3. Jes River',
        3: '4. Pirate Base'
    }.items():
        labels[i] = s.encode() + b'\0'
    replace(rows, 1004, compound(labels))
    path.write_bytes(archive(rows))


def build_campaign(path):
    rows = entries(path.read_bytes())
    ps = parts(rows[1709][1])
    assert len(ps) == 1 and len(ps[0]) == 47
    assert ps[0][:4] == bytes([2, 3, 4, 0])
    ps[0] = bytes([1, 2, 3, 4]) + bytes(43)
    replace(rows, 1709, compound(ps))
    path.write_bytes(archive(rows))


class Script:

    def __init__(self, origin):
        self.origin = origin
        self.b = bytearray()
        self.labels = {}
        self.fix = []

    def raw(self, *b):
        for x in b:
            self.b.extend(bytes.fromhex(x) if isinstance(x, str) else x)

    def label(self, n):
        assert n not in self.labels
        self.labels[n] = self.origin + len(self.b)

    def branch(self, op, label):
        self.raw(bytes([op]))
        self.fix.append((len(self.b), label))
        self.raw(b'\0\0')

    def val(self, n):
        self.raw(bytes([1, n]) if 0 <= n < 128 else b'\2' + struct.pack('<h', n))

    def local(self, n):
        self.raw(b'\6' + struct.pack('<H', n))

    def set(self, n, value):
        self.raw(b'\x0a' + struct.pack('<H', n))
        self.val(value)
        self.raw('23')

    def call(self, idx, args=(), drop=True):
        for x in args:
            self.local(x[1]) if isinstance(x, tuple) else self.val(x)
        self.raw(b'\x29' * len(args), b'\x2a' + struct.pack('<H', idx) + bytes([len(args)]))
        if drop:
            self.raw('0e')

    def ifeq(self, value, label):
        self.local(4)
        self.val(value)
        self.raw('19')
        self.branch(0x24, label)

    def finish(self):
        for at, l in self.fix:
            struct.pack_into('<H', self.b, at, self.labels[l] if isinstance(l, str) else l)
        return bytes(self.b)


def finish_prequel(GAME, DEMO):
    # The successful final debrief invokes the ordinary text renderer with a new
    # page index. Same bytecode length: all original absolute branches survive.
    path = GAME / 'DATA/RESBABL2.RES'
    rows = entries(path.read_bytes())
    ps = parts(rows[1003][1])
    old = bytes.fromhex('0103292a490001')
    assert ps[12].count(old) == 1
    ps[12] = ps[12].replace(old, bytes.fromhex('0109292a490001'))
    # Hover events can arrive while the VM is already processing another event.
    # Resolve the actual rectangle again on a click, rather than requiring a
    # previously delivered hover event. Preserve every existing branch address.
    body = ps[31]
    mark = bytes.fromhex('7ffd0306080001001a')
    assert body.count(mark) == 1
    at = body.index(mark)
    target = sum(map(len, ps))
    resume = sum(map(len, ps[:31])) + at + 3
    ps[31] = body[:at] + b'\x2d' + struct.pack('<H', target) + body[at + 3:]
    ps[-1] += bytes.fromhex('0a08002a2f000023') + b'\x2d' + struct.pack('<H', resume)
    replace(rows, 1003, compound(ps))
    path.write_bytes(archive(rows))
    path = GAME / 'DATA/RESGAME.RES'
    rows = entries(path.read_bytes())
    ps = parts(rows[456][1])
    assert len(ps) == 9
    ps[
        0
    ] = b'THE DEMO PREQUEL\n\nFour original missions set before Nikola joins Strike Force Centauri. Play them in sequence, or select any mission from the menu.\n\nThe original equipment presets and squad assignments are preserved.\0'
    ps[
        1
    ] = b'SAVING YOUR MISSION\n\nPress P to pause in a mission, then use Save Demo State in the native launcher. Saved missions are separate from the retail campaign.\n\nClose the prequel before loading a saved mission. It will reopen paused.\0'
    ps[
        2
    ] = b'CONTINUING THE STORY\n\nAfter completing Operation Citadel, return to the native launcher and choose Retail Campaign to play Terra Nova: Strike Force Centauri.\n\nThe prequel does not change your retail campaign progress.\0'
    ps[
        3
    ] = b'QUICK CONTROLS\n\nP pauses the mission. O opens Options while the mission is running; Abort Mission returns to mission selection. Alt+X exits the prequel.\n\nUse the arrow keys and Enter, or click a mission in the menu. Press H in a mission for the original controls.\0'
    ps[4] = b'Demo Prequel - Hints and Tips\0'
    for i, text in enumerate(
        [
            'Terra Nova - Demo Prequel', 'Four original missions, preserved in native Windows',
            'Select a mission to begin or replay it',
            'Save and load paused missions from the native launcher'
        ], 5
    ):
        ps[i] = text.encode() + b'\0'
    story = parts(entries((DEMO / 'TNDEMO2/DATA/DEMOPTRM.RES').read_bytes())[1455][1])
    ps.append(story[8])
    replace(rows, 456, compound(ps))
    path.write_bytes(archive(rows))


def build_art(home, retail, demo):
    rows = entries((retail / 'RESBASE.RES').read_bytes())
    b = parts(rows[205][1])[0]
    original = decode(b)
    pixels = bytearray(original)
    # Copy the full 212x25 Load Game bevel, with its original empty interior.
    for y in range(25):
        pixels[(439 + y) * 640 + 80:(439 + y) * 640 + 292] = original[(385 + y) * 640 +
                                                                      80:(385 + y) * 640 + 292]
    replace(rows, 205, compound([encode(b, pixels)]))
    (home / 'menu-retail-art.res').write_bytes(archive(rows))
    rows = entries((demo / 'RESGAME.RES').read_bytes())
    b = parts(rows[452][1])[0]
    pixels = decode(b)
    # Restore the corresponding original background below the buttons; retain the
    # demo menu's six-button lower section and original palette.
    for y in range(438, 467):
        pixels[y * 640 + 200:y * 640 + 440] = original[y * 640 + 200:y * 640 + 440]
    replace(rows, 452, compound([encode(b, pixels)]))
    (home / 'menu-demo-art.res').write_bytes(archive(rows))


def build_overlays(home, retail, demo):
    rows = entries((retail / 'RESBABL2.RES').read_bytes())
    ps = parts(rows[1001][1])
    offsets = [sum(map(len, ps[:i])) for i in range(len(ps))]
    origin = sum(map(len, ps))
    extra = bytearray()

    def hook(part, at, make):
        nonlocal extra
        at -= offsets[part]
        assert ps[part][at] == 0x7f, (part, at)
        s = Script(origin + len(extra))
        make(s)
        payload = s.finish()
        ps[part] = ps[part][:at] + b'\x2d' + struct.pack('<H', s.origin) + ps[part][at + 3:]
        extra += payload

    # Keep the original opening-movie call. The native campaign callback skips
    # it on a return from Prequel; a fresh retail launch plays it normally.
    assert ps[4].count(bytes.fromhex('2a2f00000e')) == 1

    def draw(s):
        s.local(0xfff0)
        s.val(8)
        s.raw('19')
        s.branch(0x24, 'normal')
        s.local(0xffe4)
        s.raw('59')
        s.branch(0x2d, 'text')
        s.label('normal')
        s.local(0xffe8)
        s.raw('59')
        s.label('text')
        s.val(165)
        s.val(445)
        s.raw(b'\x0d' + struct.pack('<HH', 35, 1002))
        s.raw('61')
        s.branch(0x2d, 0x2265)

    hook(40, 0x2262, draw)
    # Original part41 starts at0x226f; source marker at+6=0x2275, next0x2278.
    hook(
        41, offsets[41] + 6, lambda s: (
            s.local(0xfff4), s.val(8), s.raw('19'), s.branch(0x24, offsets[41] + 9),
            s.call(27, [184, 451]), s.branch(0x2d, 0x234e)
        )
    )

    def region(s):
        s.call(17, [8, 81, 440, 291, 464])
        s.branch(0x2d, 0x2517)

    hook(42, 0x2514, region)

    def click(s):
        s.local(4)
        s.val(0x81)
        s.raw('19')
        s.branch(0x24, 0x277e)
        s.raw('0a0800')
        s.call(29, drop=False)
        s.raw('23')
        s.branch(0x2d, 0x277e)

    hook(42, 0x277b, click)

    def choose(s):
        s.local(8)
        s.val(8)
        s.raw('19')
        s.branch(0x24, 0x282e)
        s.call(165, [2])
        s.branch(0x2d, 0x25d0)

    hook(42, 0x282b, choose)

    def hover(s):
        s.local(4)
        s.val(0x98)
        s.raw('19')
        s.branch(0x24, 0x27c1)
        s.set(8, 8)
        s.branch(0x2d, 0x2800)

    hook(42, 0x27be, hover)

    # Prequel keeps ID 8 for drawing, clicks and campaign dispatch. Keyboard
    # traversal follows its position below Skip Instruction in the left column.
    # Original handling still skips Load Game when there are no saved games.
    def navigation(s, transitions, resume, redraw):
        for current, target in transitions:
            s.local(8)
            s.val(current)
            s.raw('19')
            s.branch(0x24, f'next{current}')
            s.set(8, target)
            s.branch(0x2d, redraw)
            s.label(f'next{current}')
        s.branch(0x2d, resume)

    for site, transitions, redraw in (
        (0x25f7, ((7, 8), (8, 8)), 0x263e),                     # Left: Exit -> Prequel
        (0x2663, ((8, 7),), 0x267c),                     # Right: Prequel -> Exit
        (0x26a8, ((3, 8), (8, 4), (7, 1)), 0x26f7),     # Down
        (0x271c, ((1, 7), (4, 8), (8, 3)), 0x276b),     # Up
    ):
        hook(42, site, lambda s, t=transitions, r=site+3, d=redraw:
             navigation(s, t, r, d))
    b = bytearray(ps[42])
    for old, new in [
        ('06080001071924df26', '06080001081924df26'), ('0a08000107232d6b27', '0a08000108232d6b27'),
        ('0604000297001e17', '0604000298001e17')
    ]:
        a = bytes.fromhex(old)
        assert bytes(b).count(a) == 1, old
        b = b.replace(a, bytes.fromhex(new))
    ps[42] = bytes(b)
    ps[-1] += extra
    replace(rows, 1001, compound(ps))
    labels = parts(rows[1002][1])
    assert len(labels) == 35
    labels.append(b'Prequel\0')
    replace(rows, 1002, compound(labels))
    (home / 'menu-retail.res').write_bytes(archive(rows))
    rows = entries((demo / 'RESBABL2.RES').read_bytes())
    ps = parts(rows[1003][1])
    start = sum(map(len, ps))
    body = ps[31]
    needle = bytes.fromhex('2a0e0000')
    assert body.count(needle) == 1
    at = body.index(needle)
    back = sum(map(len, ps[:31])) + at + 4
    ps[31] = body[:at] + b'\x2d' + struct.pack('<H', start) + b'\0' + body[at + 4:]
    ps[-1] += bytes.fromhex('0100292aa50001') + b'\x2d' + struct.pack('<H', back)
    ps[29] = ps[29].replace(
        bytes.fromhex('02b80102a2010d0100ec03'), bytes.fromhex('02a60102a2010d0100ec03')
    )
    replace(rows, 1003, compound(ps))
    labels = parts(rows[1004][1])
    labels[1] = b'Main Menu\0'
    replace(rows, 1004, compound(labels))
    (home / 'menu-demo.res').write_bytes(archive(rows))
    build_art(home, retail, demo)
    return dict(
        retail_button='Prequel',
        demo_return='Main Menu',
        appended_script_bytes=len(extra),
        original_script_offsets_preserved=True
    )
