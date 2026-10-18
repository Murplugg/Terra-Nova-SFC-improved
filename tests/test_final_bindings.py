"""Admission, retained state, and final composition for the remaining features."""
import unittest
from tests import with_original_code
import ast
import re
import struct
from pathlib import Path
from feature_plan import PLAN
from features import terrain_raster as raster, sprite_variation as sprites
from features import terrain_distance as terrain, ai_response, actor_timing
from features import effect_timing, projectiles, campaign_switch, target_picking
from tests.test_beam_install import image


class FinalBindingTests(unittest.TestCase):

    @with_original_code
    def test_ir_span_reads_current_texture_and_palette_parameters(self):
        # A synthetic row makes each texture index observable through a simple
        # palette. Exercise wrapping, both U directions, and changed parameters
        # between calls without depending on proprietary textures or a save.
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP
        for count, step in ((1, 1), (7, 1), (64, 1), (7, -1)):
            with self.subTest(count=count, step=step):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0, 0x2000000)
                put = lambda a, v: u.mem_write(a, struct.pack('<I', v & 0xffffffff))
                u.mem_write(raster.IR_SPAN_CODE, raster.asm(raster.IR_SPAN_CODE, raster.retained_source(raster.IR_SPAN_RECIPE)))
                for a, value in ((0x34e22c, 0xfc0), (0x34e231, 64),
                                 (0x34e2c0, 0xfc0), (0x34e2e6, 63),
                                 (0x34e2f5, 63), (0x34e2d6, 0x500000),
                                 (0x34e33a, 1), (0x34e3ba, 1),
                                 (0x34e37a, 1), (0x34e3fa, 1)):
                    put(a, value)
                for a in (0x34e248, 0x34e279, 0x34e2be):
                    u.mem_write(a, b'\x0a')
                u.mem_write(0x34e2f3, b'\x06')
                for base in (0x34e310, 0x34e350, 0x34e390, 0x34e3d0):
                    put(base + 2, 4095)
                    put(base + 14, 0x510000)
                u.mem_write(0x510000, bytes(range(256)) * 16)
                for bias in (0, 11):
                    u.mem_write(0x500000, bytes((i+bias) & 255 for i in range(256)))
                    u.mem_write(0x520000, b'\xaa' * 128)
                    u.mem_write(0x530000, bytes(128))
                    for offset, value in ((0x20, step << 16), (0x28, step << 16),
                                          (0x30, 0x520000 + count), (0x34, -count)):
                        put(0x530000 + offset, value)
                    put(0x1800000, 0x10000)
                    u.reg_write(UC_X86_REG_EAX, 0x530000)
                    u.reg_write(UC_X86_REG_ESP, 0x1800000)
                    u.emu_start(raster.IR_SPAN_CODE, 0x10000, count=10000)
                    self.assertEqual(bytes(u.mem_read(0x520000, count)),
                                     bytes(((i*step)+bias) & 255 for i in range(count)))
                    self.assertEqual(bytes(u.mem_read(0x520000+count, 8)), b'\xaa'*8)
                    self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x1800004)

    @with_original_code
    def test_ir_affine_fills_a_row_and_retains_width_rejection(self):
        # Constant synthetic texels isolate row coverage and the original
        # oversized-row return. Real-scene comparisons cover varying slopes;
        # this asset-free fixture also checks the memory immediately after a row.
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP
        for width in (1, 17, 1024):
            u = Uc(UC_ARCH_X86, UC_MODE_32)
            u.mem_map(0, 0x2000000)
            put = lambda a, v: u.mem_write(a, struct.pack('<I', v & 0xffffffff))
            u.mem_write(raster.IR_AFFINE_CODE, raster.asm(raster.IR_AFFINE_CODE, 'jmp L3311f0;' + raster.retained_source(raster.IR_AFFINE_RECIPE)))
            for a, value in ((0x3311e0, 1), (0x3312c9, 1),
                             (0x331202, 1024), (0x331322, 1024),
                             (0x331271, 4095), (0x3312a1, 4095),
                             (0x331279, 0x510000), (0x3312a9, 0x510000),
                             (0x331286, 0x500000), (0x3312b6, 0x500000),
                             (0x33128c, 0x520000+width), (0x3312bc, 0x520000+width),
                             (0x3312f5, width), (0x331302, width),
                             (0x33124c, 0xffffffc0), (0x331236, 64),
                             (0x331378, 64), (0x33138f, 0x331351)):
                put(a, value)
            u.mem_write(0x33122c, b'\x06')
            u.mem_write(0x33134e, b'\x06')
            u.mem_write(0x33124a, b'\x0a')
            u.mem_write(0x510000, b'\x07' * 4096)
            u.mem_write(0x500000, bytes((i+11) & 255 for i in range(256)))
            u.mem_write(0x520000, b'\xaa' * 2048)
            put(0x530000, 1)
            put(0x530000+0x1c, 0x520000)
            put(0x1800000, 0x10000)
            u.reg_write(UC_X86_REG_EAX, 0x530000)
            u.reg_write(UC_X86_REG_ESP, 0x1800000)
            u.emu_start(raster.IR_AFFINE_CODE, 0x10000, count=10000)
            expected = b'\xaa' * width if width == 1024 else b'\x12' * width
            self.assertEqual(bytes(u.mem_read(0x520000, width)), expected)
            self.assertEqual(bytes(u.mem_read(0x520000+width, 8)), b'\xaa'*8)
            self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(width == 1024))
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), 0x1800004)

    def test_menu_admission_releases_finished_audio_before_checking_remaining_locks(self):
        # Leaving Quarters can leave a completed voice queued for cleanup.
        # Model the completion callback here so this regression needs no saved
        # game or original asset. Only the callback may release its own lock;
        # active voices and unrelated consumers must still block the switch.
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP
        c = campaign_switch
        bindings = c.Bindings(c.CAMPAIGN, c.RETAIL_ROOT, c.DEMO_ROOT, c.ACTIVE_ROOT,
                              c.RETAIL_FUNCTIONS, c.DEMO_FUNCTIONS, c.DEMO_VARIABLES)
        imports = dict(ExitProcess=0x300000, GetModuleHandleA=0x300004, GetProcAddress=0x300008)
        code = dict(c.bodies(imports, bindings))[c.CHECK]
        for completed, extra, unsafe in ((True, False, False), (False, False, False),
                                        (True, True, False), (True, False, True)):
            with self.subTest(completed=completed, extra=extra, unsafe=unsafe):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0, 0x2000000)
                put = lambda address, value: u.mem_write(address, struct.pack('<I', value & 0xffffffff))
                u.mem_write(c.CHECK, code)
                u.mem_write(c.FINISH_SOUNDS, b'\xc3')
                put(0x447250, 123 if unsafe else 0x447258)
                put(0x3596d8, 1)
                for index in range(16):
                    put(0x446c08 + index*8, index if index < 4 else -1)
                put(0x448dac, 0x150000)
                put(0x150000, 0x448db4)
                u.mem_write(0x15000a, struct.pack('<H', 1001))
                put(0x447224, 0x44722c)
                put(0x446be8, 0x160000)
                u.mem_write(0x446bf0, struct.pack('<H', 2222))
                for resource in (363, 1001, 1917, 2222) + ((400,) if extra else ()):
                    u.mem_write(0x160000 + resource*16 + 4, b'\x01')
                calls = []

                def finish(machine, address, size, unused):
                    if address == c.FINISH_SOUNDS:
                        calls.append(address)
                        if completed:
                            machine.mem_write(0x160000 + 1917*16 + 4, b'\0')
                        # The original consumer changes EAX, so admission must
                        # preserve the menu VM identity across this call.
                        machine.reg_write(UC_X86_REG_EAX, 0xdeadbeef)

                u.hook_add(UC_HOOK_CODE, finish)
                put(0x1800000, 0x10000)
                u.reg_write(UC_X86_REG_ESP, 0x1800000)
                u.emu_start(c.CHECK, 0x10000, count=100000)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX), int(completed and not extra and not unsafe))
                self.assertEqual(len(calls), int(not unsafe))

    def test_normal_core_dependency_graph_excludes_comparison_adapters(self):
        root = Path(__file__).resolve().parents[1] / 'engine'
        pending = ['native_host', 'patch_engine', 'feature_build']
        seen = set()
        while pending:
            name = pending.pop()
            path = root / (name.replace('.', '/') + '.py')
            if name in seen or not path.is_file():
                continue
            seen.add(name)
            self.assertIsNone(re.search(r'_v\d+$', name), name)
            self.assertNotIn(
                name, (
                    'resolution90', 'demo102_adapter', 'demo102_bindings', 'movie_clock101',
                    'direct_build', 'final_ui'
                )
            )
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    pending.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    pending.append(node.module)
                    pending.extend(node.module + '.' + alias.name for alias in node.names)
        self.assertIn('features.prequel_scripts', seen)
        self.assertIn('features.render_integration', seen)
        self.assertIn('host_services', seen)

    def test_plan_has_no_legacy_dispatch_or_intermediate_effect_steps(self):
        entries = [name for feature in PLAN for name in feature.sources]
        self.assertTrue(entries)
        self.assertFalse(any(name.startswith('native_') for name in entries))
        self.assertEqual(entries.count('sprite-variation'), 1)
        self.assertEqual(entries.count('terrain-surfaces'), 1)

    def test_simple_installers_reject_late_conflicts_without_partial_writes(self):
        cases = (
            (
                ai_response, 'investigate', {
                    ai_response.INVESTIGATE_SITE: ai_response.INVESTIGATE_ORIGINAL
                }, ai_response.INVESTIGATE_CODE + 0x1ff
            ),
            (
                actor_timing, 'pose_guard', {
                    actor_timing.POSE_GUARD_SITE: actor_timing.POSE_GUARD_ORIGINAL
                }, actor_timing.POSE_GUARD_STATE + 7
            ),
            (
                effect_timing, 'storm', {
                    effect_timing.STORM_SITE: raster.asm(effect_timing.STORM_SITE, 'call 0x2b0244'),
                    effect_timing.STORM_INIT: raster.asm(effect_timing.STORM_INIT, 'call 0x2b0238')
                }, effect_timing.STORM_STATE + 11
            ),
            (projectiles, 'deploy', projectiles.DEPLOY_ORIGINAL, projectiles.DEPLOY_END - 1),
            (raster, 'column', {
                raster.COLUMN_SITE: raster.COLUMN_ORIGINAL,
                raster.HAZE_SITE: raster.HAZE_ORIGINAL, **raster.IR_ORIGINAL
            }, raster.COLUMN_END - 1),
            (
                campaign_switch, 'safety', campaign_switch.SAFETY_SITES,
                campaign_switch.SAFETY_END - 1
            ),
            (target_picking, 'names', target_picking.NAMES_SITES, target_picking.NAMES_END - 1),
        )
        for owner, label, providers, conflict in cases:
            with self.subTest(feature=label):
                if label == 'column':
                    with_original_code(lambda: None)()
                ram, read, write, writes = image(providers)
                ram[conflict] = 1
                with self.assertRaises(ValueError):
                    getattr(owner, label + '_install')(write, read)
                self.assertFalse(writes)
                ram[conflict] = 0
                getattr(owner, label + '_install')(write, read)
                self.assertTrue(getattr(owner, label + '_verify')(read))
                writes.clear()
                getattr(owner, label + '_install')(write, read)
                self.assertFalse(writes)

    def test_instance_tables_migrate_once_and_remain_mutable(self):
        ram, read, write, writes = image(terrain.INSTANCE_ORIGINAL)
        ram[0x3cb8ec:0x3cc8ec] = bytes(range(256)) * 16
        ram[0x3c9e1c:0x3c9e9c] = bytes(range(128))
        ram[terrain.INSTANCE_BITS + terrain.INSTANCE_BITS_SIZE - 1] = 1
        with self.assertRaises(ValueError):
            terrain.instance_install(write, read)
        self.assertFalse(writes)
        ram[terrain.INSTANCE_BITS + terrain.INSTANCE_BITS_SIZE - 1] = 0
        terrain.instance_install(write, read)
        self.assertEqual(read(terrain.INSTANCE_TABLE, 0x1000), read(0x3cb8ec, 0x1000))
        self.assertEqual(read(terrain.INSTANCE_BITS, 128), read(0x3c9e1c, 128))
        ram[terrain.INSTANCE_TABLE + 5] ^= 17
        writes.clear()
        terrain.instance_install(write, read)
        self.assertFalse(writes)
        self.assertTrue(terrain.instance_verify(read))

    @with_original_code
    def test_sprite_composition_preserves_selector_tail_and_emits_final_hook_once(self):
        ram, read, write, writes = image(sprites.SCENERY_SITES)
        expected = bytearray(ram)
        for address, data in sprites.scenery_bodies() + sprites.effect_bodies():
            expected[address:address + len(data)] = data
        sprites.sprite_install(write, read)
        self.assertEqual(ram, expected)
        self.assertEqual(sum(a == sprites.SCENERY_CHOOSE for a, _ in writes), 1)
        self.assertTrue(sprites.sprite_verify(read))
        ram[sprites.SCENERY_CHOOSE + 6] ^= 1
        with self.assertRaises(ValueError):
            sprites.sprite_verify(read)

    def test_surface_composition_retains_both_paths_with_one_active_binding(self):
        paths = dict(
            span_audio_path='C:/fixture/retained-audio.dll',
            movie_audio_path='C:/fixture/active-audio.dll'
        )
        ram, read, write, writes = image(raster.surface_providers())
        expected = bytearray(ram)
        for address, data in raster.span_bodies(paths['span_audio_path']) + raster.affine_bodies(
            paths['movie_audio_path']
        ):
            expected[address:address + len(data)] = data
        raster.surface_install(write, read, **paths)
        self.assertEqual(ram, expected)
        self.assertEqual(sum(a == 0x1d27000 for a, _ in writes), 1)
        ram[raster.AFFINE_STATE] = 1
        self.assertTrue(raster.surface_verify(read, **paths))

    def test_scorch_cache_is_invalidated_only_after_all_reservations_pass(self):
        ram, read, write, writes = image(sprites.SCORCH_SITES)
        cache = 0x428810
        ram[cache:cache + 64] = bytes(range(64))
        ram[sprites.SCORCH_END - 1] = 1
        with self.assertRaises(ValueError):
            sprites.scorch_install(write, read)
        self.assertFalse(writes)
        self.assertEqual(read(cache, 64), bytes(range(64)))
        ram[sprites.SCORCH_END - 1] = 0
        sprites.scorch_install(write, read)
        self.assertEqual(read(cache, 64), bytes(64))
        ram[cache] = 7
        self.assertTrue(sprites.scorch_verify(read))

    def test_water_admission_rejects_an_unverified_original_program(self):
        ram, read, write, writes = image({raster.WATER_SITE: raster.WATER_ORIGINAL})
        with self.assertRaises(ValueError):
            raster.water_install(write, read)
        self.assertFalse(writes)


if __name__ == '__main__':
    unittest.main()
