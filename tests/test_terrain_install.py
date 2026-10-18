"""Cold terrain installation: final hooks and atomic provider admission."""
import struct
import unittest
from features import terrain_distance as d
from patch_support import asm


def fixture(kind):
    ram = bytearray(0x2000000)

    def put(a, b):
        ram[a:a + len(b)] = b

    if kind == 'foundation':
        pieces, providers = d.foundation_pieces()
        install = d.install_foundation
    elif kind == 'storage':
        for a, b in d.bodies() + [(d.DETAIL_ENTRY, d.detail_body())]:
            put(a, b)
        put(d.CONFIG, struct.pack('<I', 1))
        pieces, providers, install = d.storage_pieces(), d.storage_providers(), d.install_storage
    elif kind == 'profiles':
        for a, b in d.preset_bodies() + d.scenery_bodies() + d.heap_bodies():
            put(a, b)
        pieces, providers, install = d.profile_pieces(), d.profile_providers(), d.install_profiles
    else:
        for a, b in d.heap_bodies():
            put(a, b)
        pieces, providers, install = d.scenery_clip_bodies(
        ), d.CLIP_SITES, d.install_scenery_clipping
    for a, b in providers.items():
        put(a, b)
    return ram, put, lambda a, n: ram[a:a + n], pieces, providers, install


class TerrainInstallTests(unittest.TestCase):

    def test_complete_transition_and_each_final_hook_written_once(self):
        for kind in ('foundation', 'storage', 'profiles', 'clipping'):
            with self.subTest(kind=kind):
                ram, put, read, pieces, providers, install = fixture(kind)
                expected = bytearray(ram)
                writes = []
                for a, b in pieces:
                    expected[a:a + len(b)] = b

                def write(a, b):
                    writes.append((a, b))
                    put(a, b)

                result = install(write, read)
                self.assertEqual(ram, expected)
                self.assertEqual(result['ranges'], [(a, a + len(b)) for a, b in pieces])
                for a in providers:
                    self.assertEqual(sum(x == a for x, b in writes), 1)
                if kind == 'clipping':
                    self.assertTrue(d.verify_scenery_clipping(read))

    def test_last_hook_conflict_rejects_entire_group_before_write(self):
        for kind in ('foundation', 'storage', 'profiles', 'clipping'):
            with self.subTest(kind=kind):
                ram, _, read, _, providers, install = fixture(kind)
                ram[list(providers)[-1]] ^= 1
                before = bytes(ram)
                writes = []
                with self.assertRaises(ValueError):
                    install(lambda a, b: writes.append((a, b)), read)
                self.assertEqual(writes, [])
                self.assertEqual(ram, before)

    def test_corrupt_required_helper_rejects_before_allocation_or_hooks(self):
        for kind, address in (
            ('storage', d.RAYS), ('profiles', d.SCENERY_GATHER), ('clipping', d.HEAP_FREE)
        ):
            with self.subTest(kind=kind):
                ram, _, read, _, _, install = fixture(kind)
                ram[address] ^= 1
                writes = []
                with self.assertRaises(ValueError):
                    install(lambda a, b: writes.append((a, b)), read)
                self.assertEqual(writes, [])

    def test_late_profile_reservation_conflict_rejects_before_write(self):
        ram, _, read, _, _, install = fixture('profiles')
        ram[d.RANGE_END - 1] = 1
        writes = []
        with self.assertRaisesRegex(ValueError, 'reservation'):
            install(lambda a, b: writes.append((a, b)), read)
        self.assertEqual(writes, [])

    def test_combined_profiles_equal_previous_transitions_without_intermediate_hooks(self):
        ram, _, _, pieces, _, _ = fixture('profiles')
        previous = bytearray(ram)
        combined = bytearray(ram)
        for a, b in d.zoom_bodies() + d.quality_bodies() + d.handoff_bodies(
        ) + d.scenery_range_bodies():
            previous[a:a + len(b)] = b
        for a, b in pieces:
            combined[a:a + len(b)] = b
        self.assertEqual(previous, combined)
        self.assertEqual(len(pieces), 10)
        self.assertEqual(dict(pieces)[d.ZOOM_SITE], asm(d.ZOOM_SITE, f'jmp {d.ZOOM_CODE}'))

    def test_combined_storage_preserves_snapshot_helpers_and_final_preference(self):
        ram, _, _, pieces, _, _ = fixture('storage')
        previous = bytearray(ram)
        combined = bytearray(ram)
        for a, b in d.mesh_bodies() + d.heap_bodies() + d.preset_bodies() + [
            (d.MESH_CONFIG, struct.pack('<I', 3))
        ]:
            previous[a:a + len(b)] = b
        for a, b in pieces:
            combined[a:a + len(b)] = b
        self.assertEqual(previous, combined)
        self.assertEqual(dict(pieces)[d.MESH_ENTRY], dict(d.mesh_bodies())[d.MESH_ENTRY])


class SkyRowTests(unittest.TestCase):
    """A playtest exposed a cloud-layer jump around a nearly level camera.

    Synthetic matrices check the direct ray equation independently of game
    assets. The optional original-input case verifies installer admission;
    it does not stand in for visual checks while walking through the scene.
    """

    def test_rows_match_direct_fixed_point_equation_and_preserve_callers(self):
        from features import terrain_raster as f
        from tests.test_render_views import Fixture, put, STACK
        from unicorn.x86_const import (
            UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDX, UC_X86_REG_EDI,
            UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP
        )
        u = Fixture().u
        u.mem_write(f.SKY_ROW_SITE, f.sky_row_body())
        matrices = ((-58569, -4106, -1), (65536, -65536, 0), (1, -1, 1), (-32000, 12000, -45000))
        base = (33, -27, 64428)
        for a, value in zip((0x41eb9e, 0x41eba6, 0x41eba2), base):
            put(u, a, value & 0xffffffff)
        for coefficients in matrices:
            for a, value in zip((0x41ebaa, 0x41ebb2, 0x41ebae), coefficients):
                put(u, a, value & 0xffffffff)
            for height in (200, 400, 936, 960, 1200):
                for row in (
                    0, 1, height // 4, height // 2 - 1, height // 2, height - 2, height - 1
                ):
                    y = (row * 65536 // (height // 2)) - 65536
                    for reg, value in (
                        (UC_X86_REG_EAX, y & 0xffffffff), (UC_X86_REG_EDI, 0x123456),
                        (UC_X86_REG_EBP, 0x654321), (UC_X86_REG_ESP, STACK)
                    ):
                        u.reg_write(reg, value)
                    u.emu_start(f.SKY_ROW_SITE, f.SKY_ROW_END, count=100)
                    expected = (
                        (coefficients[0] * y >> 16) - base[0],
                        (coefficients[1] * y >> 16) - base[1],
                        base[2] - (coefficients[2] * y >> 16)
                    )
                    for reg, value in zip(
                        (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDX), expected
                    ):
                        self.assertEqual(u.reg_read(reg), value & 0xffffffff)
                    for reg, value in (
                        (UC_X86_REG_EDI, 0x123456), (UC_X86_REG_EBP, 0x654321),
                        (UC_X86_REG_ESP, STACK), (UC_X86_REG_EIP, f.SKY_ROW_END)
                    ):
                        self.assertEqual(u.reg_read(reg), value)

    def test_sky_installer_rejects_unknown_or_partial_code_without_writes(self):
        from features import terrain_raster as f
        body = f.sky_row_body()
        for before in (bytes(len(body)), body[:-1], bytes([body[0] ^ 1]) + body[1:]):
            writes = []
            with self.assertRaises(ValueError):
                f.sky_install(lambda a, b: writes.append((a, b)), lambda a, n: before)
            self.assertFalse(writes)
        self.assertTrue(f.sky_verify(lambda a, n: body))
        self.assertTrue(f.sky_install(self.fail, lambda a, n: body)['already_installed'])

    def test_verified_original_sky_span_accepts_one_in_place_replacement(self):
        from features import terrain_raster as f
        from original_inputs import original_ram
        before = bytes(original_ram[f.SKY_ROW_SITE:f.SKY_ROW_END])
        if not any(before):
            self.skipTest('Requires the original retail executable')
        writes = []
        result = f.sky_install(lambda a, b: writes.append((a, b)), lambda a, n: before)
        self.assertEqual(writes, [(f.SKY_ROW_SITE, f.sky_row_body())])
        self.assertEqual(result['ranges'], [(f.SKY_ROW_SITE, f.SKY_ROW_END)])


class ObjectRowHandoffTests(unittest.TestCase):
    """Keep actor collection timely without shortening distant scenery.

    A Target Camera reproduction exposed the shared scenery/row flag: increasing
    scenery range delayed nearby bodies until the clipping horizon was complete.
    These execution cases check the split thresholds and the unchanged fallback.
    Captured world-render comparisons supplement these small contract tests.
    """

    def test_native_row_boundary_and_legacy_flag_are_independent(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EAX
        stack, stop, result = 0x1800000, 0x1801000, 0x1802000
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x2000000)
        u.mem_write(d.ROW_SITE, asm(d.ROW_SITE, f'jmp {d.ROW_GATE}'))
        u.mem_write(d.ROW_GATE, d.object_row_body())
        for address, value in ((0x2b58da, 0), (0x2b5859, 1)):
            u.mem_write(address, asm(address, f'mov dword ptr [{result}],{value};ret;'))
        for canvas in (0x9c34e8, 0x123400):
            for enabled in (0, 1):
                for cutoff in (20, 40, 68, 120):
                    for radius in (cutoff - 1, cutoff, cutoff + 1):
                        for flag in (0, 1):
                            for address, value in ((0x44b1a0, canvas), (d.CONFIG, enabled),
                                                   (d.ROW_CUTOFF, cutoff), (0x43cad8, radius),
                                                   (stack, stop)):
                                u.mem_write(address, struct.pack('<I', value))
                            u.mem_write(0x43cc0b, bytes([flag]))
                            u.reg_write(UC_X86_REG_ESP, stack)
                            u.reg_write(UC_X86_REG_EAX, 0xabcdef)
                            u.emu_start(d.ROW_SITE, stop, count=100)
                            expected = radius > cutoff if canvas == 0x9c34e8 and enabled else not flag
                            self.assertEqual(int.from_bytes(u.mem_read(result, 4), 'little'), expected)
                            self.assertEqual(u.reg_read(UC_X86_REG_EAX), 0xabcdef)
                            self.assertEqual(u.reg_read(UC_X86_REG_ESP), stack + 4)
                            self.assertEqual(bytes(u.mem_read(0x43cc0b, 1)), bytes([flag]))

    def test_cutoff_is_saved_before_both_scenery_extensions(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EDX
        stack, stop, context, result = 0x1800000, 0x1801000, 0x1802000, 0x1803000
        for zoom, base, extended in ((0x10000, 20, 84), (0x100000, 40, 120)):
            u = Uc(UC_ARCH_X86, UC_MODE_32)
            u.mem_map(0, 0x2000000)
            for a, b in d.scenery_bodies() + d.scenery_range_bodies():
                u.mem_write(a, b)
            u.mem_write(d.DETAIL_ENTRY, asm(d.DETAIL_ENTRY,
                f'push eax;movzx eax,word ptr [edx+0x38];mov [{result}],eax;pop eax;ret;'))
            for address, value in ((stack, stop), (context, zoom), (context + 28, 0x9c34e8),
                                   (d.CONFIG, 1)):
                u.mem_write(address, struct.pack('<I', value))
            u.mem_write(context + 0x38, struct.pack('<HHH', base, 50, 80))
            u.reg_write(UC_X86_REG_ESP, stack)
            u.reg_write(UC_X86_REG_EDX, context)
            u.emu_start(d.RANGE_SITE, stop, count=1000)
            self.assertEqual(int.from_bytes(u.mem_read(d.ROW_CUTOFF, 4), 'little'), base)
            self.assertEqual(int.from_bytes(u.mem_read(result, 4), 'little'), extended)
            self.assertEqual(bytes(u.mem_read(context + 0x38, 6)), struct.pack('<HHH', base, 50, 80))
            self.assertEqual(u.reg_read(UC_X86_REG_ESP), stack + 4)


class HazeColumnTrialTests(unittest.TestCase):
    """Compare the isolated trial with locally extracted original machine code.

    Synthetic columns exercise dry, mixed and entirely remapped surfaces at
    main-view and smaller-view strides. They are not a whole-frame benchmark.
    The independent pixel equation checks both implementations against the
    intended source offset and per-row palette table.
    """

    def test_original_pixels_registers_flags_and_bounded_writes(self):
        from tests import with_original_code
        return with_original_code(self._compare_columns)()

    def test_reflection_source_can_overlap_destination(self):
        from tests import with_original_code
        return with_original_code(lambda: self._compare_columns(alias=True))()

    def _compare_columns(self, alias=False):
        import random
        from original_inputs import original_ram
        from features.terrain_raster import haze_column_candidate
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        from unicorn.x86_const import (
            UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
            UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
            UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
        )
        rng = random.Random(20261018)
        original, candidate, stop, stack = 0x2b2785, 0x1800000, 0x1801000, 0x1700000
        dest, source, palette, rows, offsets, flags, block = (
            0x800000, 0x1000000, 0x1400000, 0x1410000, 0x1420000,
            0x1430000, 0x1440000,
        )
        registers = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
                     UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                     UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS)
        texture = rng.randbytes(0x300000)
        palettes = rng.randbytes(65536)
        source_offsets = [0 if alias else rng.randrange(65536) for _ in range(256)]
        palette_rows = [rng.randrange(256) * 256 for _ in range(1200)]
        machines = []
        for entry in (original, candidate):
            u = Uc(UC_ARCH_X86, UC_MODE_32)
            u.mem_map(0, 0x2000000)
            u.mem_write(original, bytes(original_ram[original:0x2b27da]))
            u.mem_write(candidate, haze_column_candidate(candidate))
            u.mem_write(source, texture)
            u.mem_write(palette, palettes)
            u.mem_write(rows, struct.pack('<1200I', *(palette + r for r in palette_rows)))
            u.mem_write(offsets, struct.pack('<256I', *source_offsets))
            u.mem_write(block, struct.pack('<3I', rows, offsets, flags))
            writes, steps = [], [0]
            u.hook_add(UC_HOOK_MEM_WRITE,
                       lambda cpu, access, a, n, value, out: out.append((a, n)), writes)
            u.hook_add(UC_HOOK_CODE,
                       lambda cpu, a, n, counter: counter.__setitem__(0, counter[0] + 1), steps)
            machines.append((u, entry, writes, steps))
        samples = []
        for stride in (160, 320, 800, 1280, 1600, -320):
            for count in (1, 2, 3, 4, 15, 255, 576, 960):
                for density in (0, 64, 256):
                    with self.subTest(stride=stride, count=count, density=density):
                        n = (count + 2) * abs(stride) + 32
                        background = rng.randbytes(n)
                        first = dest + 8 + (0 if stride > 0 else count * -stride)
                        source_phase = (dest + 8 + ((count - 1) * stride if stride > 0 else -stride)
                                        if alias else source + 0x180000)
                        remap = bytes(1 if i < density else 0 for i in range(256))
                        initial = (rng.getrandbits(32), block, count, stride & 0xffffffff,
                                   source_phase, first, rng.getrandbits(32), stack, 0x202)
                        expected = bytearray(background)
                        allowed = set()
                        for y in range(count):
                            at = first - dest + y * stride
                            colour = background[at]
                            if remap[colour]:
                                texel = (expected[source_phase - dest - y * stride] if alias else
                                         texture[source_offsets[colour] + 0x180000 - y * stride])
                                expected[at] = palettes[palette_rows[y] + texel]
                                allowed.add((dest + at, 1))
                        outcomes, costs = [], []
                        for u, entry, writes, steps in machines:
                            u.mem_write(dest, background)
                            u.mem_write(flags, remap)
                            u.mem_write(stack, struct.pack('<I', stop))
                            for reg, val in zip(registers, initial):
                                u.reg_write(reg, val)
                            writes.clear()
                            steps[0] = 0
                            u.emu_start(entry, stop, count=50000)
                            self.assertEqual(u.reg_read(UC_X86_REG_EIP), stop)
                            self.assertEqual(bytes(u.mem_read(dest, n)), expected)
                            self.assertEqual({(a, size) for a, size in writes
                                              if not stack - 32 <= a < stack
                                              and a != 0x2b27bb}, allowed)
                            outcomes.append(tuple(u.reg_read(reg) for reg in registers))
                            costs.append(steps[0])
                        self.assertEqual(outcomes[0], outcomes[1])
                        samples.append((stride, count, density, *costs))
        self.assertEqual(len(samples), 144)
        # A dry long column is the intended gain. Dense remapping is explicitly
        # measured too, rather than treating a dry-column win as universal.
        self.cost_samples = samples


if __name__ == '__main__':
    unittest.main()
