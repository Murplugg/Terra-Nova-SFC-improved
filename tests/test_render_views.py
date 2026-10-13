"""Direct HD view generation and execution, with original rendering boundaries modeled."""
from pathlib import Path
import hashlib, json, struct, sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import render_integration as r
from features import render_views as v
from features.render_arena import Layout, BASE, SIZE
from patch_support import asm
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

STOP = 0x10000
STACK = 0x1700000
ENTRY = 0x1800000
CTOR = ENTRY + 0x2000
MODE = CTOR + 16
MERGER = CTOR + 32
LOGICAL = 0x200000
CANVAS = 0x120000
OWNER = 0x130000
CONTROL = 0x140000


def put(u, a, n):
    u.mem_write(a, struct.pack('<I', n & 0xffffffff))


def word(u, a, n):
    u.mem_write(a, struct.pack('<H', n))


def get(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def image():
    ram = bytearray(0x2000000)
    for old, sites in r.weather.ROW_TABLES.values():
        for a in sites:
            struct.pack_into('<I', ram, a, old)
    struct.pack_into('<I', ram, 0x2a7a1e, next(iter(r.weather.ROW_TABLES.values()))[0] - 4)
    for address, body in r.weather.weather():
        if address in (r.weather.SKY_D, r.weather.SKY_C):
            ram[address:address + len(body)] = body
    ram[0x1d19040:0x1d19045] = bytes.fromhex('a30cd0d101')
    return ram


class Fixture:

    def __init__(self):
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_map(BASE, SIZE)
        self.layout = Layout(BASE)
        self.calls = []
        self.render_state = []
        for address in (CTOR, MODE, MERGER, 0x9a36e8, 0x2eab30, r.maps.TERRAIN, r.maps.ORIGINAL):
            u.mem_write(address, b'\xc3')
            u.hook_add(UC_HOOK_CODE, self.boundary, begin=address, end=address)
        put(u, 0x446f78, LOGICAL)
        put(u, 0x446f80, 0x01900140)
        u.mem_write(0x1d0d449, b'\x6b')
        put(u, 0x389dec, OWNER)
        put(u, 0x389de8, OWNER)
        put(u, 0x389df8, OWNER)
        self.canvas(CANVAS)

    def canvas(self, address, width=37, height=29):
        put(self.u, address, LOGICAL + 13 * 320 + 11)
        word(self.u, address + 8, width)
        word(self.u, address + 10, height)
        word(self.u, address + 12, 320)

    def boundary(self, u, a, n, _):
        self.calls.append(a)
        if a == 0x9a36e8:
            self.render_state.append(
                (
                    get(u, 0x41ec80), get(u, r.h.CTX + 28), get(u,
                                                                r.h.CANVAS), get(u, r.h.DATA + 16),
                    get(u, r.h.DATA + 20)
                )
            )
        elif a == CTOR:
            # The real constructor may alter the active projection structure.
            # The wrapper must restore the saved high-view context afterward.
            put(u, r.h.CTX + 24, 0xabcdef)
        elif a == r.maps.TERRAIN:
            self.render_state.append(
                (get(u, r.maps.CTX + 22), get(u, r.maps.SLOT + 48), get(u, r.maps.SLOT + 52))
            )
        elif a == MERGER:
            self.render_state.append(u.reg_read(UC_X86_REG_EBP))

    def run(self, source, eax=0x222, edx=0):
        u = self.u
        u.mem_write(ENTRY, v.assemble(ENTRY, source))
        # Different helpers intentionally reuse this fixture code slot. Drop
        # Unicorn's translated blocks before switching from map entry to merge.
        u.ctl_remove_cache(ENTRY, ENTRY + 0x2000)
        put(u, STACK, STOP)
        u.reg_write(UC_X86_REG_ESP, STACK)
        u.reg_write(UC_X86_REG_EAX, eax)
        u.reg_write(UC_X86_REG_EDX, edx)
        u.reg_write(UC_X86_REG_EFLAGS, 0x202)
        u.emu_start(ENTRY, STOP, count=1000000)
        assert u.reg_read(UC_X86_REG_EIP) == STOP
        assert u.reg_read(UC_X86_REG_ESP) == STACK + 4

    def world(self):
        return v.world(self.layout, r.h, CTOR, MODE)

    def prepare_world(self):
        for n, value in enumerate((0x10000, 0x10000, 1, 2, 3, 4, 5, CANVAS)):
            put(self.u, r.h.CTX + 4 * n, value)
        put(self.u, 0x41ec80, 0x500000)
        put(self.u, self.layout.state, 1)
        return bytes(self.u.mem_read(r.h.CTX, 32))

    def prepare_map(self):
        self.canvas(OWNER + 0x22)
        put(self.u, 0x44b1a0, OWNER + 0x22)
        put(self.u, CONTROL, 17)
        put(self.u, CONTROL + 4, 19)
        put(self.u, CONTROL + 10, 0x10000)


class RenderViewTests(unittest.TestCase):

    def test_integration_never_calls_legacy_source_capture_or_mutates_effect_providers(self):
        before_damage = r.h.damage_bodies(asm)
        before_nav = r.h.nav_bodies(asm)
        # Import denial proves current generation needs no private providers.
        with patch.dict('sys.modules', {'prototype_hud400_v49': None, 'native_visual_v50': None}), \
             patch.object(r.maps, 'bodies', side_effect=AssertionError('legacy map')):
            a = r.Integration(BASE)
            a.build(image())
            b = r.Integration(BASE)
            b.build(image())
        self.assertEqual(a.writes, b.writes)
        self.assertEqual(r.h.damage_bodies(asm), before_damage)
        self.assertEqual(r.h.nav_bodies(asm), before_nav)
        pins = json.loads((Path(__file__).parent / 'render-view-fingerprints.json').read_text())
        for name, row in pins.items():
            address = r.MODE_IO if name == 'mode' else a.entries[name]
            body = dict(a.writes)[address]
            self.assertEqual(
                (address, len(body), hashlib.sha256(body).hexdigest()),
                (row['address'], row['size'], row['sha256']), name
            )

    def test_world_cache_rebuilds_only_for_geometry_identity_or_invalidation(self):
        x = Fixture()
        u = x.u
        original = x.prepare_world()
        x.run(x.world(), edx=r.h.CTX)
        width = 37 * 4
        height = ((13 + 29) * 12 + 4) // 5 - (13 * 12 + 4) // 5
        self.assertEqual(
            x.render_state[-1], (x.layout.reflection, r.h.CANVAS, x.layout.pixels, width, height)
        )
        self.assertEqual(bytes(u.mem_read(r.h.CTX, 32)), original)
        self.assertEqual(get(u, 0x41ec80), 0x500000)
        self.assertEqual(get(u, r.h.READY), 1)
        self.assertEqual(x.calls.count(CTOR), 1)
        x.run(x.world(), edx=r.h.CTX)
        self.assertEqual(x.calls.count(CTOR), 1)
        word(u, CANVAS + 8, 38)
        x.run(x.world(), edx=r.h.CTX)
        self.assertEqual(x.calls.count(CTOR), 2)
        put(u, r.h.CTX, 0x20000)
        x.run(x.world(), edx=r.h.CTX)
        self.assertEqual(x.calls.count(CTOR), 3)
        put(u, x.layout.state, 1)
        x.run(x.world(), edx=r.h.CTX)
        self.assertEqual(x.calls.count(CTOR), 4)
        self.assertEqual(get(u, 0x41ec80), 0x500000)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x222)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), r.h.CTX)

    def test_world_fallback_and_invalid_canvas_never_replace_reflection_owner(self):
        x = Fixture()
        original = x.prepare_world()
        x.run(x.world(), edx=0x555)
        self.assertEqual(x.calls, [0x9a36e8])
        self.assertEqual(get(x.u, 0x41ec80), 0x500000)
        x.calls.clear()
        word(x.u, CANVAS + 8, 0)
        x.run(x.world(), edx=r.h.CTX)
        self.assertFalse(x.calls)
        self.assertEqual(get(x.u, r.h.DATA + 32), 1)
        self.assertEqual(get(x.u, r.h.READY), 0)
        self.assertEqual(bytes(x.u.mem_read(r.h.CTX, 32)), original)

    def test_map_reuses_terrain_until_view_settings_or_geometry_change(self):
        x = Fixture()
        u = x.u
        x.prepare_map()
        source = v.map_entry(x.layout, r.maps)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(r.maps.TERRAIN), 1)
        self.assertEqual(x.render_state[-1], (x.layout.map, 148, 69))
        self.assertEqual(get(u, r.maps.SLOT), 1)
        self.assertEqual(get(u, r.maps.SLOT + 12), OWNER)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(r.maps.TERRAIN), 1)
        put(u, CONTROL, 18)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(r.maps.TERRAIN), 2)
        word(u, OWNER + 0x22 + 8, 38)
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(r.maps.TERRAIN), 3)
        u.mem_write(0x35ade0, b'\x01')
        x.run(source, eax=CONTROL)
        self.assertEqual(x.calls.count(r.maps.TERRAIN), 4)
        self.assertEqual(u.reg_read(UC_X86_REG_EAX), CONTROL)

    def test_map_merge_rejects_stale_owner_view_or_settings(self):
        x = Fixture()
        u = x.u
        x.prepare_map()
        x.run(v.map_entry(x.layout, r.maps), eax=CONTROL)
        source = v.map_merge(r.maps, MERGER)
        x.calls.clear()
        x.run(source)
        self.assertEqual(x.calls, [MERGER])
        # Every mismatch must suppress the detailed overlay; otherwise a cached
        # map can appear under a different actor or obsolete control state.
        for address, value in (
            (OWNER + 0x1c, 17), (OWNER + 0x18, 19), (0x359708, 21), (OWNER + 0x22 + 8, 0),
            (0x389e0c, OWNER)
        ):
            with self.subTest(address=hex(address)):
                old = bytes(u.mem_read(address, 4))
                put(u, address, value)
                x.calls.clear()
                x.run(source)
                self.assertFalse(x.calls)
                u.mem_write(address, old)

    def test_camera_merge_checks_actor_identity_and_cockpit_visibility(self):
        x = Fixture()
        u = x.u
        slot = r.h.SLOTS
        for off, value in (
            (0, 1), (12, OWNER), (16, LOGICAL), (20, 13 * 320 + 11), (32, 37), (36, 29)
        ):
            put(u, slot + off, value)
        x.canvas(OWNER + 0x22)
        source = v.camera_merge(r.h, MERGER)
        x.run(source)
        self.assertEqual(x.render_state, [slot])
        put(u, 0x389df8, OWNER + 4)
        x.calls.clear()
        x.run(source)
        self.assertFalse(x.calls)
        put(u, 0x389df8, OWNER)
        u.mem_write(0x38fbfe, b'\x01')
        u.mem_write(0x35aef0, b'\x01')
        x.calls.clear()
        x.run(source)
        self.assertFalse(x.calls)

    def test_cursor_restores_only_its_previous_rectangle_from_completed_frame(self):
        x = Fixture()
        u = x.u
        i = x.layout
        left, top, right, bottom = 1201, 703, 1208, 708
        for off, value in ((0, 1), (4, left), (8, right), (12, top), (16, bottom)):
            put(u, v.CURSOR_RECT + off, value)
        put(u, v.CURSOR_STATS, 1)
        for y in range(top - 1, bottom + 1):
            u.mem_write(i.frame + y * 1280 + left - 1, bytes([y & 255]) * 9)
            u.mem_write(i.screen + y * 1280 + left - 1, b'Z' * 9)
        x.run(v.cursor(i, r.h))
        for y in range(top - 1, bottom + 1):
            expected = b'Z' + bytes([y & 255]) * 7 + b'Z' if top <= y < bottom else b'Z' * 9
            self.assertEqual(bytes(u.mem_read(i.screen + y * 1280 + left - 1, 9)), expected)
        self.assertEqual(get(u, v.CURSOR_RECT), 0)
        self.assertEqual(get(u, v.COMPOSE_BUSY), 0)
        self.assertEqual(get(u, v.CURSOR_STATS + 16), 35)

    def test_damage_and_nav_profiles_are_reentrant_and_keep_shared_recording_state(self):
        original = dict(r.h.damage_bodies(asm))
        nav = r.h.nav_bodies(asm)
        relocated = dict(
            r.h.damage_bodies(
                asm,
                entry_address=0x68c02000,
                draw_address=0x68c02400,
                rect_address=0x68c02800,
                noise_address=0x68c02c00,
                lines_address=0x68c03000,
                pixels=0x68100000,
                width=1280,
                height=960
            )
        )
        for a in (r.h.DAMAGE_CHOOSE, r.h.DAMAGE_PIXEL, r.h.DAMAGE_COPY, r.h.DAMAGE_LINE):
            self.assertEqual(original[a], relocated[a])
        self.assertEqual(dict(r.h.damage_bodies(asm)), original)
        self.assertNotEqual(r.h.nav_bodies(asm, label=0x68c03400, pixels=0x68100000), nav)
        self.assertEqual(r.h.nav_bodies(asm), nav)


if __name__ == '__main__':
    unittest.main()
