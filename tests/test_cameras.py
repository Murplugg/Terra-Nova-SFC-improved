"""Executed camera ownership, facing, distortion timing and offline bindings."""
from pathlib import Path
import sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from features import cameras as c, hud
from patch_support import asm
from tests.test_render_views import Fixture, put, word, get, OWNER, CANVAS, STACK, STOP, ENTRY
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *


def call(u, address, eax=0, edx=0, ebx=0):
    put(u, STACK, STOP)
    for reg, value in (
        (UC_X86_REG_ESP, STACK), (UC_X86_REG_EAX, eax), (UC_X86_REG_EDX, edx),
        (UC_X86_REG_EBX, ebx), (UC_X86_REG_EFLAGS, 0x247)
    ):
        u.reg_write(reg, value)
    u.emu_start(address, STOP, count=1000000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert u.reg_read(UC_X86_REG_ESP) == STACK + 4
    return u.reg_read(UC_X86_REG_EAX)


class CameraTests(unittest.TestCase):

    def test_heading_and_noise_installations_validate_hooks_and_full_reservations(self):
        for setup, sites, end in (
            (c.heading_setup, {
                c.HEADING_SITE: c.HEADING_ORIGINAL
            }, c.HEADING_END), (c.noise_setup, c.NOISE_SITES, c.NOISE_STATE + c.NOISE_STATE_SIZE)
        ):
            for problem in ('hook', 'tail', 'none'):
                with self.subTest(setup=setup.__name__, problem=problem):
                    ram = bytearray(0x2000000)
                    writes = []
                    for a, b in sites.items():
                        ram[a:a + len(b)] = b
                    if problem == 'hook':
                        ram[next(reversed(sites))] ^= 1
                    if problem == 'tail':
                        ram[end - 1] = 1

                    def write(a, b):
                        writes.append((a, b))
                        ram[a:a + len(b)] = b

                    if problem != 'none':
                        with self.assertRaises(AssertionError):
                            setup(write, ram)
                        self.assertEqual(writes, [])
                    else:
                        setup(write, ram)
                        self.assertTrue(writes)
                        writes.clear()
                        setup(write, ram)
                        self.assertEqual(writes, [])

    def test_low_width_installation_checks_complete_old_body_and_retained_tail(self):
        old = c.low_body(odd_width=False)
        new = c.low_body()
        size = max(len(old), len(new))
        for corrupt in (False, True):
            ram = bytearray(0x2000000)
            ram[c.LOW_ENTRY:c.LOW_ENTRY + len(old)] = old
            writes = []
            if corrupt:
                ram[c.LOW_ENTRY + size - 1] ^= 1
            if corrupt:
                with self.assertRaises(ValueError):
                    c.install_low_width(lambda *x: writes.append(x), lambda a, n: ram[a:a + n])
                self.assertEqual(writes, [])
            else:
                c.install_low_width(lambda *x: writes.append(x), lambda a, n: ram[a:a + n])
                self.assertEqual(writes, [(c.LOW_ENTRY, new.ljust(size, b'\x90'))])

    def test_sources_build_without_historical_images_or_source_capture(self):
        with patch.dict('sys.modules', {'build_inputs': None}), \
             patch('build_paths.source_path',side_effect=AssertionError('source capture')):
            self.assertTrue(c.low_body())
            self.assertTrue(c.low_body(odd_width=False))
            self.assertTrue(hud.code(hud.CAMERA, c.high_source()))
            self.assertEqual(len(c.visibility_bodies()), 6)
            self.assertEqual(len(c.heading_bodies()), 2)
            self.assertEqual(len(c.noise_bodies()), 11)

    def test_visibility_install_rejects_partial_short_hook_and_reservation_damage(self):
        baseline = bytearray(0x2000000)
        for a in c.VISIBILITY_SITES:
            baseline[a:a + 10] = c.visibility_prefix(a)
        for problem in ('partial', 'short', 'hook', 'tail', 'none'):
            with self.subTest(problem=problem):
                ram = bytearray(baseline)
                writes = []
                if problem == 'partial':
                    a, b = c.visibility_bodies()[0]
                    ram[a:a + len(b)] = b
                if problem == 'hook':
                    ram[c.VISIBILITY_SITES[-1] + 9] ^= 1
                if problem == 'tail':
                    ram[c.VISIBILITY_ENTRIES[-1] + 255] = 1

                def write(a, b):
                    writes.append((a, b))
                    ram[a:a + len(b)] = b

                reader = lambda a, n: ram[a:a + n - int(problem == 'short')]
                if problem != 'none':
                    with self.assertRaises(ValueError):
                        c.visibility_install(write, reader)
                    self.assertEqual(writes, [])
                else:
                    c.visibility_install(write, reader)
                    writes.clear()
                    self.assertTrue(c.visibility_install(write, reader)['already_installed'])
                    self.assertEqual(writes, [])
                    self.assertEqual(c.visibility_predecessor_view(ram), baseline)

    def test_visibility_keeps_main_map_exception_when_side_panels_are_hidden(self):
        x = Fixture()
        u = x.u
        for site, entry in zip(c.VISIBILITY_SITES, c.VISIBILITY_ENTRIES):
            u.mem_write(entry, dict(c.visibility_bodies())[entry])
            for hidden, flag, main_map in (
                (0, 1, False), (1, 0, False), (1, 1, False), (1, 1, True)
            ):
                u.mem_write(0x38fbfe, bytes([hidden]))
                u.mem_write(0x35aef0, bytes([flag]))
                put(u, 0x1e3c58c, OWNER)
                put(u, 0x389df4, OWNER if main_map else OWNER + 4)
                put(u, STACK, STOP)
                u.reg_write(UC_X86_REG_ESP, STACK)
                u.reg_write(UC_X86_REG_EFLAGS, 0x247)
                continuation = site + len(c.visibility_prefix(site))
                u.mem_write(continuation, b'\x90')

                # Stop before either original body or the caller resumes.
                def stop_at(u, a, n, _):
                    u.emu_stop()

                hook = u.hook_add(UC_HOOK_CODE, stop_at, begin=continuation, end=continuation)
                u.emu_start(entry, STOP, count=100)
                visible = not (hidden and flag) or (main_map and site == c.VISIBILITY_SITES[-1])
                self.assertEqual(u.reg_read(UC_X86_REG_EIP), continuation if visible else STOP)
                u.hook_del(hook)

    def test_heading_uses_rendered_pose_then_object_heading_then_original_fallback(self):
        x = Fixture()
        u = x.u
        fallback = []
        u.mem_write(c.HEADING_CODE, dict(c.heading_bodies())[c.HEADING_CODE])
        u.mem_write(0x2750cc, b'\xc3')

        def original(u, a, n, _):
            fallback.append(1)
            u.reg_write(UC_X86_REG_EAX, 0xbeef)

        u.hook_add(UC_HOOK_CODE, original, begin=0x2750cc, end=0x2750cc)
        actor = 0x3c3240 + 37 * 7
        suit = 0x3a5608 + 0x582 * 3
        u.mem_write(actor, b'\x01\x01')
        word(u, actor + 3, 3)
        word(u, actor + 0x1b, 0x1234)
        word(u, suit + 0x2f9, 7)
        word(u, suit + 0x305, 0x5678)
        self.assertEqual(call(u, c.HEADING_CODE, 7, 44, 55), 0x5678)
        self.assertEqual(u.reg_read(UC_X86_REG_EDX), 44)
        self.assertEqual(u.reg_read(UC_X86_REG_EBX), 55)
        self.assertEqual(u.reg_read(UC_X86_REG_EFLAGS), 0x247)
        word(u, suit + 0x2f9, 8)
        self.assertEqual(call(u, c.HEADING_CODE, 7), 0x1234)
        word(u, actor + 3, 64)
        self.assertEqual(call(u, c.HEADING_CODE, 7), 0x1234)
        u.mem_write(actor + 1, b'\x02')
        self.assertEqual(call(u, c.HEADING_CODE, 7), 0xbeef)
        for actor_id in (0, 300):
            self.assertEqual(call(u, c.HEADING_CODE, actor_id), 0xbeef)
        self.assertEqual(len(fallback), 3)

    def test_noise_decision_is_cached_for_50ms_per_view_and_actor_identity(self):
        x = Fixture()
        u = x.u
        calls = []
        for a, b in c.noise_bodies():
            u.mem_write(a, b)
        u.mem_write(0x27a118, b'\xc3')

        def original(u, a, n, _):
            calls.append(u.reg_read(UC_X86_REG_EAX))
            u.reg_write(UC_X86_REG_EAX, len(calls))

        u.hook_add(UC_HOOK_CODE, original, begin=0x27a118, end=0x27a118)
        put(u, 0x44134e, 123)
        u.mem_write(0x38fc12, b'\x04')
        for time, result in ((0, 1), (16, 1), (49, 1), (50, 2), (99, 2)):
            put(u, 0x446ae8, time)
            self.assertEqual(call(u, c.NOISE_GATE, 0), result)
        put(u, 0x44134e, 124)
        self.assertEqual(call(u, c.NOISE_GATE, 0), 3)
        u.mem_write(0x38fc12, b'\x05')
        self.assertEqual(call(u, c.NOISE_GATE, 0), 4)
        self.assertEqual(call(u, c.NOISE_GATE, 1), 5)
        self.assertEqual(call(u, c.NOISE_GATE, 0), 4)
        self.assertEqual(call(u, c.NOISE_GATE, 3), 6)
        self.assertEqual(get(u, c.NOISE_STATE), 0)

    def test_noise_offsets_reuse_samples_but_resample_when_bound_changes(self):
        x = Fixture()
        u = x.u
        calls = []
        for a, b in c.noise_bodies():
            u.mem_write(a, b)
        put(u, c.NOISE_STATE, c.NOISE_TABLE)
        u.mem_write(0x2ddd70, b'\xc3')

        def rng(u, a, n, _):
            calls.append(u.reg_read(UC_X86_REG_EBX))
            u.reg_write(UC_X86_REG_EAX, len(calls))

        u.hook_add(UC_HOOK_CODE, rng, begin=0x2ddd70, end=0x2ddd70)
        self.assertEqual(call(u, c.NOISE_RAND_X, ebx=100), 1)
        self.assertEqual(call(u, c.NOISE_RAND_X, ebx=100), 1)
        self.assertEqual(call(u, c.NOISE_RAND_Y, ebx=100), 2)
        self.assertEqual(call(u, c.NOISE_RAND_X, ebx=99), 3)
        put(u, c.NOISE_TABLE + 16, 0)
        self.assertEqual(call(u, c.NOISE_RAND_X, ebx=99), 4)
        put(u, c.NOISE_STATE, 0)
        self.assertEqual(call(u, c.NOISE_RAND_X, ebx=99), 5)
        self.assertEqual(calls, [100, 100, 99, 99, 99])

    def test_damage_render_bypasses_upscaling_only_for_three_camera_contexts(self):
        x = Fixture()
        u = x.u
        calls = []
        u.mem_write(c.NOISE_RENDER, dict(c.noise_bodies())[c.NOISE_RENDER])
        for a in (0x29edb4, 0x9a36e8):
            u.mem_write(a, b'\xc3')
            u.hook_add(UC_HOOK_CODE, lambda u, a, n, _: calls.append(a), begin=a, end=a)
        for context in (0x390010, 0x390010 + 186, 0x390010 + 372, 0x390011, 0x38fb24):
            calls.clear()
            call(u, c.NOISE_RENDER, 123, context)
            self.assertEqual(
                calls,
                [0x9a36e8 if context in (0x390010, 0x390010 + 186, 0x390010 + 372) else 0x29edb4]
            )
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 123)

    def test_high_camera_renders_odd_pirate_width_and_restores_projection(self):
        x = Fixture()
        u = x.u
        context = 0x390010
        slot = hud.SLOTS
        x.canvas(CANVAS, width=85, height=55)
        for n, value in enumerate((0x10000, 0x10000, 1, 2, 3, 4, 5, CANVAS)):
            put(u, context + n * 4, value)
        original = bytes(u.mem_read(context, 32))
        for offset, value in ((56, hud.BASES[0]), (60, hud.REFS[0]), (64, hud.MASKS[0])):
            put(u, slot + offset, value)
        u.mem_write(hud.TARGET, b'\xc3')

        def render(u, a, n, _):
            width = get(u, slot + 48)
            height = get(u, slot + 52)
            u.mem_write(hud.BASES[0], bytes([73]) * (width * height))

        hook = u.hook_add(UC_HOOK_CODE, render, begin=0x9a36e8, end=0x9a36e8)
        x.run(c.high_source(), eax=123, edx=context)
        self.assertEqual((get(u, slot + 48), get(u, slot + 52)), (212, 82))
        self.assertEqual(bytes(u.mem_read(context, 32)), original)
        self.assertEqual(get(u, slot), 1)
        self.assertEqual(bytes(u.mem_read(hud.REFS[0], 85 * 55)), bytes([73]) * (85 * 55))
        self.assertEqual(x.calls.count(0x9a36e8), 1)
        u.hook_del(hook)
        word(u, CANVAS + 8, 101)
        x.calls.clear()
        x.run(c.high_source(), edx=context)
        self.assertEqual(get(u, slot), 0)
        self.assertNotIn(0x9a36e8, x.calls)


if __name__ == '__main__':
    unittest.main()
