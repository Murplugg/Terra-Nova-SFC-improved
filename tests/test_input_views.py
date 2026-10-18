"""Native coordinate, cursor and projection behavior at modeled OS boundaries."""
from pathlib import Path
import struct, sys, types, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import input_views as f
from patch_support import asm
from tests.test_render_views import Fixture, put, word, get, STACK, STOP, ENTRY
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

IMPORTS = {'GetModuleHandleA': 0x120000, 'GetProcAddress': 0x120004}
CONTEXT = 0x140000
CANVAS = 0x150000


def input_bodies():
    ram = bytearray(0x2000000)
    ram[0x319530:0x319539] = bytes.fromhex('061e55565752515350')
    ram[0x31aae0:0x31aae7] = bytes.fromhex('fb50531e515256')
    out = []
    f.connect(
        lambda a, b: out.append((a, b)), asm, lambda name: 'call dword ptr [0x1d1c020];',
        types.SimpleNamespace(S=0x1d1d000), ram
    )
    return out


def run(u, address, *, end=STOP, **registers):
    put(u, STACK, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK)
    u.reg_write(UC_X86_REG_EFLAGS, 0x247)
    for name, value in registers.items():
        u.reg_write(globals()['UC_X86_REG_' + name.upper()], value)
    u.emu_start(address, end, count=100000)
    assert u.reg_read(UC_X86_REG_EIP) == end


class InputViewTests(unittest.TestCase):

    def drone_cpu(self, patched, drone_type=0):
        # Run the original scanner, action table and converters. Only the
        # unrelated AI-order cancellation call is modeled. Both drone types
        # use this selected-object path; no keyboard hardware is simulated.
        from original_inputs import original_ram
        if not any(original_ram[0x2765f4:0x276813]):
            self.skipTest('Supply the verified retail executable for keyboard checks')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        for lo, hi in ((0x2765f4, 0x276813), (0x27c8b8, 0x27cc85),
                       (0x35b338, 0x35b3bc), (0x35b618, 0x35b66e)):
            u.mem_write(lo, bytes(original_ram[lo:hi]))
        self.assertEqual(bytes(original_ram[f.DRONE_CONTROLS_SITE:f.DRONE_CONTROLS_SITE + 5]),
                         asm(f.DRONE_CONTROLS_SITE, 'call 0x27cb58'))
        u.mem_write(0x24bb1c, b'\xc3')
        obj, record = 0x3c3240 + 10 * 37, 0x39e590 + 335
        u.mem_write(obj, struct.pack('<BBBH', 1, 3, drone_type, 1))
        word(u, record, 10)
        word(u, 0x396868, 10)
        put(u, 0x44c5d0, 0x1900000)
        if patched:
            for a, b in f.drone_controls_bodies():
                u.mem_write(a, b)
        return u

    def drone_keys(self, u, keys, reset=True):
        bitmap = bytearray(32)
        for key in keys:
            bitmap[key // 8] |= 1 << (key % 8)
        u.mem_write(0x1900000, bytes(bitmap))
        if reset:
            word(u, 0x39025a, 0)
            u.mem_write(0x39e590 + 335 + 0x132, bytes(8))
        run(u, 0x2765f4, end=0x276813)
        return struct.unpack('<ihh', u.mem_read(0x39e590 + 335 + 0x132, 8))

    def test_drone_independent_translation_and_turning_combine(self):
        # Assert actual single-key calibration, then require both components
        # for independent axes. These are held bitmap inputs, not a claim about
        # the owner's physical arrow-key report.
        for drone_type in (0, 1):
            old, new = self.drone_cpu(False, drone_type), self.drone_cpu(True, drone_type)
            for ctrl in (29, 157):
                for move in (17, 31, 45, 200, 208, 44, 46):
                    for turn in (30, 32, 203, 205):
                        with self.subTest(type=drone_type, ctrl=ctrl, move=move, turn=turn):
                            movement = self.drone_keys(old, (ctrl, move))
                            turning = self.drone_keys(old, (ctrl, turn))
                            self.assertNotEqual(movement[0], 0)
                            self.assertEqual(movement[1], 0)
                            self.assertEqual(turning[0], 0)
                            self.assertNotEqual(turning[1], 0)
                            actual = self.drone_keys(new, (ctrl, move, turn))
                            self.assertEqual(actual, (movement[0], turning[1], movement[2]))

    def test_drone_single_keys_conflicts_aliases_and_ctrl_release_are_preserved(self):
        actions = (17, 30, 31, 32, 44, 45, 46, 203, 205, 200, 208)
        conflicts = ((17, 45), (17, 31), (30, 32), (203, 205), (200, 208),
                     (17, 200), (30, 203), (32, 205), (45, 208), (44, 46),
                     (17, 44), (17, 46), (45, 44))
        for drone_type in (0, 1):
            old, new = self.drone_cpu(False, drone_type), self.drone_cpu(True, drone_type)
            for ctrl in ((), (29,), (157,)):
                for alt in ((), (56,), (184,)):
                    for keys in [(), *[(a,) for a in actions], *conflicts]:
                        names = ctrl + alt + keys
                        with self.subTest(type=drone_type, keys=names):
                            if ctrl and alt and keys in ((30, 203), (32, 205)):
                                # Alt changes the arrow to strafe, while A/D
                                # remain turn bindings: these cease to be aliases.
                                turning = self.drone_keys(old, ctrl + alt + keys[:1])
                                movement = self.drone_keys(old, ctrl + alt + keys[1:])
                                self.assertEqual(self.drone_keys(new, names),
                                                 (movement[0], turning[1], movement[2]))
                            else:
                                self.assertEqual(self.drone_keys(new, names), self.drone_keys(old, names))
            for keys in ((29, 17, 30), (157, 200, 205), (29, 44, 30), (29, 56, 17, 203)):
                # Holding repeats the same command. Releasing either Ctrl or
                # all keys clears the old manual command immediately.
                first = self.drone_keys(new, keys)
                self.assertEqual(self.drone_keys(new, keys, reset=False), first)
                self.assertEqual(self.drone_keys(new, keys[1:], reset=False), (0, 0, 0))
                self.drone_keys(new, keys)
                self.assertEqual(self.drone_keys(new, (), reset=False), (0, 0, 0))

    def test_drone_key_order_release_one_axis_and_selected_object_boundary(self):
        for drone_type in (0, 1):
            old, new = self.drone_cpu(False, drone_type), self.drone_cpu(True, drone_type)
            for first, second in ((17, 30), (30, 17), (200, 205), (205, 200), (44, 32), (32, 44)):
                expected_first = self.drone_keys(old, (29, first))
                expected_second = self.drone_keys(old, (29, second))
                self.assertEqual(self.drone_keys(new, (29, first)), expected_first)
                combined = self.drone_keys(new, (29, first, second), reset=False)
                self.assertNotEqual(combined[0], 0)
                self.assertNotEqual(combined[1], 0)
                self.assertEqual(self.drone_keys(new, (29, second), reset=False), expected_second)
                self.assertEqual(self.drone_keys(new, (29,), reset=False), (0, 0, 0))
            # The original missing-selected-drone branch must still bypass the
            # converter, rather than letting a second action address slot zero.
            word(new, 0x396868, 0)
            record = 0x39e590 + 335 + 0x132
            sentinel = struct.pack('<ihh', 123, 456, 789)
            new.mem_write(record, sentinel)
            self.drone_keys(new, (29, 17, 30), reset=False)
            self.assertEqual(bytes(new.mem_read(record, 8)), sentinel)

    def test_drone_combination_retains_action_limit_and_elapsed_turning(self):
        from features import actor_timing as timing
        for drone_type in (0, 1):
            u = self.drone_cpu(True, drone_type)
            combined = self.drone_keys(u, (29, 17, 30))
            self.assertEqual(combined, (1023, -820, 0))
            # The original collector's alias removal and two-action priority
            # still decide which requests reach this consumer.
            for keys in ((29, 17, 30, 32), (29, 17, 30, 200), (29, 17, 30, 203)):
                self.assertEqual(self.drone_keys(u, keys), combined)
            for a, b in timing.part_bodies('aircraft'):
                u.mem_write(a, b)
            obj, record = 0x3c3240 + 10 * 37, 0x39e590 + 335
            word(u, obj + 0x1b, 0)
            for dt in [16, 17, 17] * 20:
                run(u, timing.AIRCRAFT_TURN_SITE,
                    end=timing.AIRCRAFT_TURN_SITE + len(timing.AIRCRAFT_TURN_OLD),
                    edi=record, esi=obj, ebp=dt)
            self.assertEqual(get(u, obj + 0x1b) & 0xffff, (-820 * 40) & 0xffff)
            self.assertEqual(get(u, record + 0x132), 1023)

    def test_drone_combination_install_checks_hook_and_helper_without_state(self):
        for fault in ('none', 'hook', 'helper', 'partial', 'short'):
            with self.subTest(fault=fault):
                ram = bytearray(0x2000000)
                a = f.DRONE_CONTROLS_SITE
                ram[a:a + 5] = asm(a, 'call 0x27cb58')
                if fault == 'hook':
                    ram[a] ^= 1
                elif fault == 'helper':
                    ram[f.DRONE_CONTROLS_ENTRY] = 1
                elif fault == 'partial':
                    ram[a:a + 5] = f.drone_controls_bodies()[0][1]
                writes = []

                def write(a, b):
                    writes.append((a, b))
                    ram[a:a + len(b)] = b

                read = lambda a, n: ram[a:a + n - int(fault == 'short')]
                if fault != 'none':
                    with self.assertRaises(ValueError):
                        f.drone_controls_install(write, read)
                    self.assertFalse(writes)
                else:
                    f.drone_controls_install(write, read)
                    self.assertTrue(f.drone_controls_verify(read))
                    self.assertEqual(writes, f.drone_controls_bodies())
                    writes.clear()
                    self.assertTrue(f.drone_controls_install(write, read)['already_installed'])
                    self.assertFalse(writes)

    def test_detail_setup_receives_current_zoom_and_preserves_other_arguments(self):
        # A live Options round trip exposed a mismatch between selected zoom
        # and projection scale. Stop at the original terrain setup boundary:
        # this checks the caller's ABI without pretending to emulate resources.
        x = Fixture()
        u = x.u
        for address, body in f.zoom_bodies():
            u.mem_write(address, body)
        for zoom in range(4):
            for detail in range(4):
                with self.subTest(zoom=zoom, detail=detail):
                    word(u, 0x38fbe2, zoom)
                    run(u, f.ZOOM_DETAIL_SITE, end=0x2ac7a0,
                        eax=0x38fb24, ebx=0, ecx=0, edx=detail,
                        esi=123, edi=456, ebp=789)
                    self.assertEqual(u.reg_read(UC_X86_REG_EBX), zoom)
                    for name, value in [('EAX', 0x38fb24), ('ECX', 0), ('EDX', detail),
                                        ('ESI', 123), ('EDI', 456), ('EBP', 789)]:
                        self.assertEqual(u.reg_read(globals()['UC_X86_REG_' + name]), value)
                    self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK - 4)
                    self.assertEqual(get(u, STACK - 4), f.ZOOM_DETAIL_SITE + 5)
                    self.assertEqual(get(u, STACK), STOP)


    def test_detail_zoom_install_is_checked_atomic_and_repeatable(self):
        for issue in ('none', 'hook', 'reservation', 'partial', 'short'):
            with self.subTest(issue=issue):
                ram = bytearray(0x2000000)
                old = asm(f.ZOOM_DETAIL_SITE, 'call 0x2ac7a0')
                ram[f.ZOOM_DETAIL_SITE:f.ZOOM_DETAIL_SITE + len(old)] = old
                if issue == 'hook':
                    ram[f.ZOOM_DETAIL_SITE] ^= 1
                elif issue == 'reservation':
                    ram[f.ZOOM_DETAIL_ENTRY] = 1
                elif issue == 'partial':
                    address, body = f.zoom_bodies()[0]
                    ram[address:address + len(body)] = body
                writes = []

                def write(address, body):
                    writes.append((address, body))
                    ram[address:address + len(body)] = body

                read = lambda a, n: ram[a:a + n - int(issue == 'short')]
                if issue != 'none':
                    with self.assertRaises(ValueError):
                        f.zoom_install(write, read)
                    self.assertFalse(writes)
                else:
                    f.zoom_install(write, read)
                    self.assertTrue(f.zoom_verify(read))
                    self.assertEqual(writes, f.zoom_bodies())
                    writes.clear()
                    self.assertTrue(f.zoom_install(write, read)['already_installed'])
                    self.assertFalse(writes)

    def test_generators_require_explicit_valid_imports_without_history(self):
        with patch.dict('sys.modules', {'build_inputs': None}), \
             patch('build_paths.source_path',side_effect=AssertionError('source parsing')):
            self.assertEqual(len(f.aspect_bodies()), 4)
            self.assertEqual(len(input_bodies()), 4)
            for body in (f.cursor_bodies, f.room_bodies):
                self.assertTrue(body(IMPORTS))
                self.assertNotEqual(body(IMPORTS), body({k: v + 0x100 for k, v in IMPORTS.items()}))
                for bad in (
                    {}, {
                        'GetModuleHandleA': 0,
                        'GetProcAddress': 0x120004
                    }, {
                        'GetModuleHandleA': 0x120000,
                        'GetProcAddress': 0x120000
                    }, {
                        'GetModuleHandleA': 0x120001,
                        'GetProcAddress': 0x120004
                    }
                ):
                    with self.assertRaises(ValueError):
                        body(bad)

    def test_installers_reject_changed_partial_short_and_dirty_cache_before_writing(self):
        profiles = (
            (f.aspect_bodies(), f.aspect_providers(), f.ASPECT_VALUE, f.aspect_install), (
                f.cursor_bodies(IMPORTS), {
                    f.CURSOR_PROC: f.CURSOR_PREFIX
                }, f.CURSOR_SLOT, lambda w, r: f.cursor_install(w, r, IMPORTS)
            ), (
                f.room_bodies(IMPORTS), {
                    f.ROOM_SITE: f.ROOM_ORIGINAL
                }, f.ROOM_CACHE, lambda w, r: f.room_install(w, r, IMPORTS)
            )
        )
        for pieces, providers, state, install in profiles:
            for problem in ('partial', 'hook', 'short', 'cache', 'none'):
                with self.subTest(entry=hex(pieces[0][0]), problem=problem):
                    ram = bytearray(0x2000000)
                    writes = []
                    for a, b in providers.items():
                        ram[a:a + len(b)] = b
                    if problem == 'partial':
                        a, b = pieces[0]
                        ram[a:a + len(b)] = b
                    if problem == 'hook':
                        ram[next(iter(providers))] ^= 1
                    if problem == 'cache':
                        ram[state] = 1

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    reader = lambda a, n: ram[a:a + n - int(problem == 'short')]
                    if problem != 'none':
                        with self.assertRaises(ValueError):
                            install(write, reader)
                        self.assertFalse(writes)
                    else:
                        install(write, reader)
                        self.assertEqual(writes, pieces)
                        writes.clear()
                        self.assertTrue(install(write, reader)['already_installed'])
                        self.assertFalse(writes)

    def test_mouse_mapping_clamps_and_scales_signed_client_coordinates(self):
        x = Fixture()
        u = x.u
        u.mem_write(f.MAP, dict(input_bodies())[f.MAP])
        for extent in (0, 1, 2, 640, 1280):
            for minimum, maximum in ((0, 639), (12, 411)):
                put(u, CONTEXT, minimum)
                put(u, CONTEXT + 4, maximum)
                for coordinate in (-50, 0, 1, extent // 2, extent - 1, extent, 2000):
                    run(u, f.MAP, eax=coordinate & 0xffffffff, ecx=extent, esi=CONTEXT)
                    expected = minimum if extent <= 1 else minimum + max(
                        0, min(coordinate, extent - 1)
                    ) * (maximum - minimum) // (
                        extent - 1
                    )
                    self.assertEqual(u.reg_read(UC_X86_REG_EAX), expected)

    def test_final_mapping_clamps_restricted_ranges_without_stretching_viewport(self):
        x = Fixture()
        u = x.u
        u.mem_write(f.VIEWPORT_MAP, dict(f.viewport_mapping_bodies())[f.VIEWPORT_MAP])
        put(u, 0x446f80, 320 | (400 << 16))
        u.mem_write(0x3644ce, b'\x01\x00')
        for axis, maximum, extent in ((f.MOUSE + 12, 638, 1280), (f.MOUSE + 20, 399, 960)):
            for minimum, limit in ((0, maximum), (100, 200)):
                put(u, axis, minimum)
                put(u, axis + 4, limit)
                for position in (-1, 0, extent // 2, extent - 1, extent + 10):
                    run(
                        u,
                        f.VIEWPORT_MAP,
                        eax=position & 0xffffffff,
                        ecx=extent,
                        esi=axis,
                        ebx=42,
                        edi=43
                    )
                    expected = max(
                        minimum,
                        min(limit,
                            max(0, min(position, extent - 1)) * maximum // (extent - 1))
                    )
                    self.assertEqual(u.reg_read(UC_X86_REG_EAX), expected)
                    self.assertEqual(
                        (u.reg_read(UC_X86_REG_EBX), u.reg_read(UC_X86_REG_EDI)), (42, 43)
                    )

    def test_final_mapping_installer_checks_retained_tail_and_new_reservation(self):
        original = asm(f.MAP, f.coordinate_source())
        for problem in ('tail', 'new', 'none'):
            ram = bytearray(0x2000000)
            ram[f.MAP:f.MAP + len(original)] = original
            writes = []
            if problem == 'tail':
                ram[f.MAP + len(original) - 1] ^= 1
            if problem == 'new':
                ram[f.VIEWPORT_MAP + 255] = 1

            def write(a, b):
                writes.append((a, b))
                ram[a:a + len(b)] = b

            if problem != 'none':
                with self.assertRaises(ValueError):
                    f.viewport_mapping_install(write, lambda a, n: ram[a:a + n])
                self.assertFalse(writes)
            else:
                f.viewport_mapping_install(write, lambda a, n: ram[a:a + n])
                self.assertEqual(writes, f.viewport_mapping_bodies())
                writes.clear()
                self.assertTrue(
                    f.viewport_mapping_install(write,
                                               lambda a, n: ram[a:a + n])['already_installed']
                )
                self.assertFalse(writes)

    def test_extended_keys_and_focus_loss_release_every_held_button(self):
        x = Fixture()
        u = x.u
        keys = []
        mouse = []
        for a, b in input_bodies():
            u.mem_write(a, b)
        for a in (f.KEY, f.DELIVER):
            u.mem_write(a, b'\xc3')
        u.hook_add(
            UC_HOOK_CODE,
            lambda u, a, n, _: keys.append(u.reg_read(UC_X86_REG_EAX)),
            begin=f.KEY,
            end=f.KEY
        )
        u.hook_add(
            UC_HOOK_CODE,
            lambda u, a, n, _: mouse.append(u.reg_read(UC_X86_REG_EAX)),
            begin=f.DELIVER,
            end=f.DELIVER
        )
        run(u, f.HANDLE, eax=0x100, ecx=0x01000000 | (0x4b << 16))
        self.assertEqual(keys, [0xe0, 0x4b])
        self.assertEqual(bytes(u.mem_read(f.PRESSED + 0xcb, 1)), b'\1')
        put(u, f.MOUSE + 8, 7)
        run(u, f.HANDLE, eax=8)
        self.assertEqual(keys, [0xe0, 0x4b, 0xe0, 0xcb])
        self.assertEqual(mouse, [4 | 16 | 64])
        self.assertEqual(get(u, f.MOUSE + 8), 0)
        self.assertFalse(any(u.mem_read(f.PRESSED, 256)))

    def test_mouse_service_masks_callback_flags_and_consumes_deltas_once(self):
        x = Fixture()
        u = x.u
        u.mem_write(ENTRY, asm(ENTRY, f.mouse_assembly() + 'stop:ret;resume:ret;'))
        put(u, CONTEXT + 0xb0, 0xc)
        put(u, CONTEXT + 0xac, 0x12340007)
        run(u, ENTRY, ebp=CONTEXT)
        self.assertEqual(get(u, f.MOUSE + 32), 7)
        put(u, CONTEXT + 0xb0, 0xb)
        put(u, f.STATE + 20, 19)
        put(u, f.STATE + 24, 0xfffffff9)
        run(u, ENTRY, ebp=CONTEXT)
        self.assertEqual(bytes(u.mem_read(CONTEXT + 0xac, 2)), b'\x13\0')
        self.assertEqual(bytes(u.mem_read(CONTEXT + 0xa8, 2)), b'\xf9\xff')
        self.assertEqual((get(u, f.STATE + 20), get(u, f.STATE + 24)), (0, 0))
        run(u, ENTRY, ebp=CONTEXT)
        self.assertEqual(bytes(u.mem_read(CONTEXT + 0xac, 2)), b'\0\0')

    def test_room_sync_rounds_to_client_pixels_and_skips_unfocused_or_invalid_ranges(self):
        x = Fixture()
        u = x.u
        moves = []
        focus = [0xabc]
        translate = [True]
        for a, b in f.room_bodies(IMPORTS):
            u.mem_write(a, b)
        for i, address in enumerate((0x160000, 0x160010, 0x160020)):
            put(u, f.ROOM_CACHE + 4 * i, address)
        u.mem_write(0x160000, b'\xc3')
        u.mem_write(0x160010, b'\xc2\x08\0')
        u.mem_write(0x160020, b'\xc2\x08\0')

        def fg(u, a, n, _):
            u.reg_write(UC_X86_REG_EAX, focus[0])

        def client(u, a, n, _):
            point = get(u, u.reg_read(UC_X86_REG_ESP) + 8)
            put(u, point, get(u, point) + 100)
            put(u, point + 4, get(u, point + 4) + 200)
            u.reg_write(UC_X86_REG_EAX, int(translate[0]))

        def move(u, a, n, _):
            esp = u.reg_read(UC_X86_REG_ESP)
            moves.append((get(u, esp + 4), get(u, esp + 8)))

        for a, callback in ((0x160000, fg), (0x160010, client), (0x160020, move)):
            u.hook_add(UC_HOOK_CODE, callback, begin=a, end=a)
        put(u, 0x1d1d000, 0xabc)
        for a, value in (
            (f.MOUSE, 320), (f.MOUSE + 4, 200), (f.MOUSE + 12, 0), (f.MOUSE + 16, 639),
            (f.MOUSE + 20, 0), (f.MOUSE + 24, 399), (0x1d1d090, 20), (0x1d1d094, 30),
            (0x1d1d098, 1280), (0x1d1d09c, 960)
        ):
            put(u, a, value)
        for mode in ('valid', 'unfocused', 'outside', 'zero_extent', 'translation_failure'):
            moves.clear()
            focus[0] = 0 if mode == 'unfocused' else 0xabc
            translate[0] = mode != 'translation_failure'
            put(u, f.MOUSE, 640 if mode == 'outside' else 320)
            put(u, 0x1d1d098, 1 if mode == 'zero_extent' else 1280)
            put(u, f.STATE + 20, 11)
            put(u, f.STATE + 24, 12)
            run(u, f.ROOM_SYNC)
            if mode == 'valid':
                self.assertEqual(
                    moves, [(120 + (320 * 1279 + 319) // 639, 230 + (200 * 959 + 199) // 399)]
                )
                self.assertEqual((get(u, f.STATE + 20), get(u, f.STATE + 24)), (0, 0))
            else:
                self.assertFalse(moves)
                self.assertEqual((get(u, f.STATE + 20), get(u, f.STATE + 24)), (11, 12))

    def test_windows_cursor_hides_only_client_cursor_and_handles_api_failure(self):
        x = Fixture()
        u = x.u
        calls = []
        module = [0xabc]
        resolved = [0x160020]
        for a, b in f.cursor_bodies(IMPORTS):
            u.mem_write(a, b)
        put(u, IMPORTS['GetModuleHandleA'], 0x160000)
        put(u, IMPORTS['GetProcAddress'], 0x160010)
        for a, b in (
            (0x160000, b'\xc2\x04\0'), (0x160010, b'\xc2\x08\0'), (0x160020, b'\xc2\x04\0')
        ):
            u.mem_write(a, b)

        def gm(u, a, n, _):
            calls.append('module')
            u.reg_write(UC_X86_REG_EAX, module[0])

        def gp(u, a, n, _):
            calls.append('symbol')
            u.reg_write(UC_X86_REG_EAX, resolved[0])

        def hide(u, a, n, _):
            calls.append(get(u, u.reg_read(UC_X86_REG_ESP) + 4))

        for a, cb in ((0x160000, gm), (0x160010, gp), (0x160020, hide)):
            u.hook_add(UC_HOOK_CODE, cb, begin=a, end=a)
        continuation = f.CURSOR_PROC + len(f.CURSOR_PREFIX)
        u.mem_write(continuation, b'\x90')
        u.hook_add(
            UC_HOOK_CODE, lambda u, a, n, _: u.emu_stop(), begin=continuation, end=continuation
        )
        for mode in (
            'resolve', 'cached', 'frame', 'other_message', 'missing_module', 'missing_symbol'
        ):
            calls.clear()
            module[0] = 0 if mode == 'missing_module' else 0xabc
            resolved[0] = 0 if mode == 'missing_symbol' else 0x160020
            if mode != 'cached':
                put(u, f.CURSOR_SLOT, 0)
            put(u, STACK, STOP)
            put(u, STACK + 8, 0x21 if mode == 'other_message' else 0x20)
            put(u, STACK + 16, 2 if mode == 'frame' else 1)
            u.reg_write(UC_X86_REG_ESP, STACK)
            u.emu_start(f.CURSOR_ENTRY, STOP, count=1000)
            if mode in ('resolve', 'cached'):
                self.assertEqual(u.reg_read(UC_X86_REG_ESP), STACK + 20)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), 1)
                self.assertEqual(calls, ['module', 'symbol', 0] if mode == 'resolve' else [0])
            else:
                self.assertEqual(u.reg_read(UC_X86_REG_EIP), continuation)
                self.assertNotIn(0, calls)

    def test_aspect_constructor_preserves_original_modes_and_reduced_detail_policy(self):
        x = Fixture()
        u = x.u
        u.mem_write(f.ASPECT_ENTRY, dict(f.aspect_bodies())[f.ASPECT_ENTRY])
        put(u, 0x35f8cc, 0x123456)
        for mode in (0x01900140, 0x00c80140):
            put(u, 0x446f80, mode)
            for flags in range(4):
                u.mem_write(CONTEXT + 0x2e, bytes([flags]))
                run(u, f.ASPECT_ENTRY, end=0x29ea56, esi=CONTEXT)
                self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
                if mode == 0x01900140:
                    self.assertEqual(u.reg_read(UC_X86_REG_EAX), f.ASPECT_VALUE)
                    self.assertEqual(get(u, f.ASPECT_VALUE), 0x4ccc if flags == 1 else 0x9999)
                else:
                    self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0x123456)

    def test_projection_repair_changes_only_owned_valid_contexts_and_only_when_needed(self):
        x = Fixture()
        u = x.u
        angles = []
        context = 0x390010
        u.mem_write(f.ASPECT_RENDER, dict(f.aspect_bodies())[f.ASPECT_RENDER])
        u.mem_write(0x1dea900, b'\xc3')
        u.mem_write(0x2ecc24, b'\xc3')

        def angle(u, a, n, _):
            angles.append(u.reg_read(UC_X86_REG_EDX))
            u.reg_write(UC_X86_REG_EAX, 0x7777)

        u.hook_add(UC_HOOK_CODE, angle, begin=0x2ecc24, end=0x2ecc24)
        for flags in range(4):
            put(u, context, 0x10000)
            put(u, context + 4, 0)
            put(u, context + 20, 40)
            put(u, context + 28, CANVAS)
            word(u, CANVAS + 8, 100)
            word(u, CANVAS + 10, 80)
            word(u, CANVAS + 12, 320)
            u.mem_write(context + 0x2e, bytes([flags]))
            angles.clear()
            run(u, f.ASPECT_RENDER, eax=123, edx=context)
            w = 50 if flags & 1 else 100
            h = 40 if flags & 2 else 80
            aspect = 0x4ccc if flags == 1 else 0x9999
            expected = (w * 0x10000 << 16) // (h * aspect)
            self.assertEqual(get(u, context + 4), expected)
            self.assertEqual(get(u, context + 12), expected * 40)
            self.assertEqual(angles, [expected])
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 123)
            self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
            run(u, f.ASPECT_RENDER, edx=context)
            self.assertEqual(len(angles), 1)
        for invalid in ('owner', 'stride', 'width', 'height', 'mode'):
            angles.clear()
            put(u, context + 4, 0)
            word(u, CANVAS + 8, 100)
            word(u, CANVAS + 10, 80)
            word(u, CANVAS + 12, 320)
            put(u, 0x446f80, 0x01900140)
            if invalid == 'stride':
                word(u, CANVAS + 12, 321)
            if invalid == 'width':
                word(u, CANVAS + 8, 321)
            if invalid == 'height':
                word(u, CANVAS + 10, 0)
            if invalid == 'mode':
                put(u, 0x446f80, 0x00c80140)
            run(u, f.ASPECT_RENDER, edx=CONTEXT if invalid == 'owner' else context)
            self.assertFalse(angles)
            self.assertEqual(get(u, context + 4), 0)




class EnemyOutfittingTests(unittest.TestCase):
    """A unit-label click exposed a null read before the original null check.

    Replay the locally supplied original dispatch instructions with an unmapped
    null page, as on Windows. Authored button records cover ordinary callbacks
    and the original restrictions on the last two slots of certain unit types.
    Sound and callback execution are boundaries; they are not simulated here.
    """

    def machine(self, fixed=True, null_page=False):
        from original_inputs import original_ram
        if not any(original_ram[0x2cf68c:0x2cf6fc]):
            self.skipTest('Requires the original retail executable')
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(0, bytes(original_ram))
        if not null_page:
            u.mem_unmap(0, 0x1000)
        if fixed:
            f.outfit_install(u.mem_write, u.mem_read)
        u.mem_write(0x247b60, b'\xc2\x0c\0')
        return u

    def dispatch(self, u, pointer):
        def stop(cpu, address, size, data):
            if address in (0x2cf6ed, 0x2cf6f0):
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE, stop)
        u.reg_write(UC_X86_REG_ESP, STACK)
        u.reg_write(UC_X86_REG_EAX, pointer)
        u.emu_start(0x2cf68c, STOP, count=1000)
        return (u.reg_read(UC_X86_REG_EIP), u.reg_read(UC_X86_REG_EAX) & 255,
                u.reg_read(UC_X86_REG_ESI), u.reg_read(UC_X86_REG_ESP))

    def test_empty_click_is_ignored_before_reading_a_button(self):
        old = self.machine(fixed=False)
        with self.assertRaises(UcError):
            self.dispatch(old, 0)
        self.assertEqual(old.reg_read(UC_X86_REG_EIP), 0x2cf68e)
        self.assertEqual(self.dispatch(self.machine(), 0)[0], 0x2cf6f0)
        # A readable low page allows the original late check to be reached.
        self.assertEqual(self.dispatch(self.machine(False, True), 0)[0], 0x2cf6f0)

    def test_valid_callbacks_and_restricted_slots_match_original(self):
        for callback in (0x2d0c00, 0x2d1000):
            for unit_type in range(5):
                for slot in range(4):
                    results = []
                    for fixed in (False, True):
                        u = self.machine(fixed)
                        put(u, CONTEXT + 12, callback)
                        u.mem_write(CONTEXT + 16, bytes([8 + slot]))
                        u.mem_write(0x442f20 + 8, bytes([unit_type]))
                        results.append(self.dispatch(u, CONTEXT))
                    self.assertEqual(results[0], results[1], (callback, unit_type, slot))
                    expected = 0x2cf6f0 if (callback == 0x2d0c00 and
                                unit_type in (2, 3) and slot >= 2) else 0x2cf6ed
                    self.assertEqual(results[1][0], expected)

    def test_installer_checks_both_original_spans_before_writing(self):
        u = self.machine(False)
        f.outfit_install(u.mem_write, u.mem_read)
        self.assertTrue(f.outfit_verify(u.mem_read))
        self.assertTrue(f.outfit_install(u.mem_write, u.mem_read)['already_installed'])
        u = self.machine(False)
        u.mem_write(0x2cf69d, b'\xcc')
        with self.assertRaises(ValueError):
            f.outfit_install(u.mem_write, u.mem_read)
        self.assertEqual(bytes(u.mem_read(0x2cf68c, 15)), f.OUTFIT_BEFORE[0x2cf68c])



if __name__ == '__main__':
    unittest.main()
