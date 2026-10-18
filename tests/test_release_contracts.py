"""Snapshot compatibility decisions must happen before payload reads/writes."""
import copy, hashlib, json, struct, unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from tnova import state_core as c


class Contracts(unittest.TestCase):

    def test_runtime_paths_keep_disk_image_fixed(self):
        install = c.Installation.__new__(c.Installation)
        install.template = b'fixed portable image'
        install.fresh = b'image with current in-memory paths'
        install.meta = {'runtime_paths': 'executable-directory-v1'}
        self.assertEqual(install.startup_image, install.template)
        install.meta = {}
        self.assertEqual(install.startup_image, install.fresh)
        install.meta = {'runtime_paths': 'unknown'}
        with self.assertRaisesRegex(ValueError, 'Unsupported runtime path policy'):
            _ = install.startup_image

    def install(self, revision):
        return SimpleNamespace(revision=revision, profile=c.CONTRACTS[str(revision)])

    def meta(self, revision):
        p = c.CONTRACTS[str(revision)]
        return dict(
            format='tn-portable-state-126',
            revision=revision,
            template=p['template'],
            contract=p['contract'],
            bridge=c.BRIDGE
        )

    def test_matching_builds(self):
        for revision in tuple(map(int, c.CONTRACTS)):
            c.validate_build(self.install(revision), self.meta(revision))

    def test_both_cross_build_directions_explain_recovery(self):
        for old, new in (
            (a, b) for a in tuple(map(int, c.CONTRACTS))
            for b in tuple(map(int, c.CONTRACTS)) if a != b
        ):
            meta = self.meta(old)
            before = copy.deepcopy(meta)
            with self.assertRaisesRegex(ValueError, 'ordinary campaign save'):
                c.validate_build(self.install(new), meta)
            self.assertEqual(meta, before)

    def test_pins_are_not_interchangeable(self):
        for revision in tuple(map(int, c.CONTRACTS)):
            for field in ('template', 'contract', 'bridge'):
                meta = self.meta(revision)
                meta[field] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'build mismatch'):
                    c.validate_build(self.install(revision), meta)

    def test_unknown_format(self):
        meta = self.meta(133)
        meta['format'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'format/version'):
            c.validate_build(self.install(133), meta)

    def test_legacy_has_no_new_ui_requirements(self):
        c.validate_ui_state(
            self.install(120),
            lambda *_: self.fail('Legacy bytes must not be interpreted as new UI state')
        )

    def test_ui_code_and_idle_state(self):
        data = {100: b'fixed hook', 200: bytes(8)}
        profile = dict(
            code=[dict(address=100, size=10, sha256=hashlib.sha256(data[100]).hexdigest())],
            idle=[dict(address=200, size=8)]
        )
        install = SimpleNamespace(profile=profile)
        c.validate_ui_state(install, lambda a, n: data[a])
        data[100] = b'wrong hook'
        with self.assertRaisesRegex(ValueError, 'UI code mismatch'):
            c.validate_ui_state(install, lambda a, n: data[a])
        data[100] = b'fixed hook'
        data[200] = b'\1' + bytes(7)
        with self.assertRaisesRegex(ValueError, 'Close the dialog'):
            c.validate_ui_state(install, lambda a, n: data[a])

    def test_new_hook_regions_do_not_overlap_checkpoint_gate(self):
        p = c.CONTRACTS['133']
        self.assertTrue(p['code'])
        self.assertTrue(p['idle'])
        for row in p['code'] + p['idle']:
            a, b = row['address'], row['address'] + row['size']
            self.assertTrue(b <= c.PARK or a >= c.PARK + 0x1000)
            self.assertLessEqual(b, 0x2000000)

    def test_retry_flag_is_mutable_but_bounded(self):
        profile = dict(code=[], idle=[], flags=[dict(address=0x1d2efc0)])
        install = SimpleNamespace(profile=profile)
        for value in (0, 1):
            c.validate_ui_state(install, lambda a, n: c.pack(value))
        with self.assertRaisesRegex(ValueError, 'retry flag'):
            c.validate_ui_state(install, lambda a, n: c.pack(2))
        self.assertNotIn(0x1d2efc0, [r['address'] for r in c.CONTRACTS['133']['code']])

    def test_campaign_transition_must_be_idle(self):
        p = c.CONTRACTS['138']
        self.assertIn(dict(address=0x1efe800, size=4), p['idle'])
        for row in p['code']:
            self.assertFalse(row['address'] <= 0x1efe800 < row['address'] + row['size'])
        data = {r['address']: bytes(r['size']) for r in p['idle']}
        profile = dict(code=[], idle=p['idle'])
        c.validate_ui_state(SimpleNamespace(profile=profile), lambda a, n: data[a])
        data[0x1efe800] = c.pack(3)
        with self.assertRaises(ValueError):
            c.validate_ui_state(SimpleNamespace(profile=profile), lambda a, n: data[a])


class RendererLayouts(unittest.TestCase):
    """Renderer expansion must preserve old snapshots in matching installations.

    Authored layouts and payloads exercise the launcher contract without private
    game files. The generated restore reader executes with modeled Windows I/O.
    """

    def setUp(self):
        self.published_layout = json.loads((c.ROOT/'state-layout.json').read_text())
        self.temp = TemporaryDirectory(prefix='tnova-render-layout-')
        self.root = Path(self.temp.name)
        self.layouts = {'layouts': {
            'legacy-16m': dict(revision=120, arena_size=0x1000000,
                              guards=[c.ARENA+0x100], external=[]),
            'map-cache-32m': dict(revision=171, arena_size=0x2000000,
                                guards=[c.ARENA+0x100, c.ARENA+0x1000100], external=[],
                                restore_zero=[dict(address=c.ARENA+0x1e00100, size=0x800)])}}
        (self.root/'state-layout.json').write_text(json.dumps(self.layouts))
        self.root_patch = patch.object(c, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def install(self, expanded):
        profile = dict(template='template', contract='contract', code=[], idle=[])
        if expanded:
            profile['render_layout'] = 'map-cache-32m'
        return SimpleNamespace(profile=profile, revision=171 if expanded else 170,
                               home=self.root, meta=dict(assets={}),
                               pe=SimpleNamespace(read=lambda a,n:bytes(n)))

    def test_flat_legacy_and_registry_selection_are_explicit(self):
        legacy = dict(self.layouts['layouts']['legacy-16m'])
        del legacy['arena_size']
        self.assertEqual(c.renderer_layout(self.install(False), legacy)['arena_size'], 0x1000000)
        with self.assertRaisesRegex(ValueError, 'explicit layout'):
            c.renderer_layout(self.install(True), legacy)
        self.assertEqual(c.snapshot_sizes(self.install(False))['render-arena.bin'], 0x1000000)
        self.assertEqual(c.snapshot_sizes(self.install(True))['render-arena.bin'], 0x2000000)
        for size in (0, 0x1000000, 0x1800000, 0x4000000, True):
            bad = copy.deepcopy(self.layouts)
            bad['layouts']['map-cache-32m']['arena_size'] = size
            with self.assertRaisesRegex(ValueError, 'arena size'):
                c.renderer_layout(self.install(True), bad)
        bad = self.install(True)
        bad.profile['render_layout'] = 'untrusted'
        with self.assertRaisesRegex(ValueError, 'Unsupported renderer layout'):
            c.renderer_layout(bad)

    def test_real_legacy_declaration_keeps_image_guards_and_rejects_unmapped_gap(self):
        # The shipped declaration guards both the low executable image and
        # the external arena. An arena-only synthetic fixture missed this ABI.
        declared = c.renderer_layout(self.install(False), self.published_layout)
        self.assertTrue(any(a < c.ARENA for a in declared['guards']))
        self.assertTrue(any(a >= c.ARENA for a in declared['guards']))
        self.assertTrue(all(c.ARENA <= row['address'] < c.ARENA+0x1000000
                            for row in declared['external']))
        registry = {'layouts': {'legacy-16m': declared,
                                'map-cache-32m': dict(declared, arena_size=0x2000000)}}
        registry['layouts']['map-cache-32m']['guards'] = declared['guards'] + [c.ARENA+0x1000100]
        for expanded in (False, True):
            install = self.install(expanded)
            layout = c.renderer_layout(install, registry)
            self.assertEqual(layout['guards'][:len(declared['guards'])], declared['guards'])
            key = install.profile.get('render_layout', 'legacy-16m')
            for address in (0, 0x10000, 0x2000000, c.ARENA-256,
                            c.ARENA+layout['arena_size'], True):
                bad = copy.deepcopy(registry)
                bad['layouts'][key]['guards'].append(address)
                with self.assertRaisesRegex(ValueError, 'outside image and arena'):
                    c.renderer_layout(install, bad)

    def test_builder_compares_selected_layout_and_rejects_guard_drift(self):
        from build import validate_snapshot_layout
        for expanded in (False, True):
            install = self.install(expanded)
            key = install.profile.get('render_layout', 'legacy-16m')
            generated = copy.deepcopy(self.layouts['layouts'][key])
            generated['revision'] = install.revision
            with patch.dict(c.CONTRACTS, {str(install.revision): install.profile}):
                validate_snapshot_layout(generated, self.layouts, install.revision)
                if not expanded:
                    legacy = dict(generated)
                    del legacy['arena_size']
                    validate_snapshot_layout(legacy, legacy, install.revision)
                for field, value in (('guards', []), ('external', [dict(address=c.ARENA+200,size=1,sha256='x')]),
                                     ('arena_size', 0x4000000)):
                    wrong = dict(generated, **{field:value})
                    with self.assertRaisesRegex(ValueError, 'snapshot declarations'):
                        validate_snapshot_layout(wrong, self.layouts, install.revision)

    def test_matching_layout_guards_and_capture_extent(self):
        def read(a,n):
            if a == c.ARENA+0xb0007c:
                return c.pack(0x39305254)
            return b'\xa5'*n if a < c.ARENA+0x1000000 else bytes(n)
        self.assertEqual(c.validate_buffers(read, self.install(False)), 1)
        with self.assertRaisesRegex(ValueError, 'Damaged render guard'):
            c.validate_buffers(read, self.install(True))
        for expanded, size in ((False,0x1000000),(True,0x2000000)):
            calls=[]
            c.capture_render_buffers(self.install(expanded), lambda a,n:calls.append((a,n)) or b'copied')
            self.assertEqual(calls, [(0xe0000000,0x800000),(c.ARENA,size)])
            c.validate_audio_base(c.ARENA+size, size)
            with self.assertRaisesRegex(ValueError, 'audio base'):
                c.validate_audio_base(c.ARENA+size-0x10000, size)
        c.validate_audio_base(c.ARENA+0x1000000, 0x1000000)
        with self.assertRaisesRegex(ValueError, 'audio base'):
            c.validate_audio_base(c.ARENA+0x1000000, 0x2000000)

    def test_payload_length_comes_from_installation_and_cross_revision_stays_rejected(self):
        for expanded in (False, True):
            install=self.install(expanded);size=c.snapshot_sizes(install)['render-arena.bin']
            folder=self.root/str(expanded);folder.mkdir()
            memory=bytearray(c.SIZES['memory.bin']);stack=0x100000
            for a,value in ((0x1d0b000,0x103),(0x9aa0ec,1),(0x446ae8,1),
                            (0x1d0f300,2),(0x359708,42)):
                struct.pack_into('<I',memory,a,value)
            memory[0x35f3f4]=1
            arena=bytearray(size)
            struct.pack_into('<I',arena,0xb0007c,0x39305254)
            for guard in c.renderer_layout(install)['guards']:
                arena[guard-c.ARENA:guard-c.ARENA+256]=b'\xa5'*256
            blobs={'render-arena.bin':arena,'memory.bin':memory,
                   **{k:bytes(n) for k,n in c.SIZES.items() if k not in ('render-arena.bin','memory.bin')},
                   'mission-reports.res':c.archive({})}
            meta=dict(format='tn-portable-state-126',revision=install.revision,campaign='retail',
                      template='template',contract='contract',bridge=c.BRIDGE,game_clock=1,host_ms=2,
                      saved_stack=stack,audio_base=0x40000000,files=[],
                      payloads={k:c.digest(v) for k,v in blobs.items()})
            # An invented snapshot size must not override the installation.
            meta['arena_size']=0x4000000
            for name,data in blobs.items():(folder/name).write_bytes(data)
            (folder/'snapshot.json').write_text(json.dumps(meta))
            _,loaded=c.validate_snapshot(install,folder,'retail')
            self.assertEqual(len(loaded['render-arena.bin']),size)
            del loaded,blobs,memory,arena
            with (folder/'render-arena.bin').open('r+b') as f:f.truncate(0x1000000 if expanded else 0x2000000)
            with self.assertRaisesRegex(ValueError, 'payload size: render-arena.bin'):
                c.validate_snapshot(install,folder,'retail')
            other=self.install(not expanded)
            with self.assertRaisesRegex(ValueError, 'ordinary campaign save'):
                c.validate_snapshot(other,folder,'retail')

    def test_generated_restore_reads_full_arena_and_clears_only_cache_records(self):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_EAX
        for expanded in (False,True):
            for short in (False,True):
                install=self.install(expanded);size=c.snapshot_sizes(install)['render-arena.bin']
                u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,0x2000000);u.mem_map(c.ARENA,size)
                api={'CreateFileA':0x1800000,'ReadFile':0x1800010,'CloseHandle':0x1800020}
                text=c.render_payload_restore_source(install,Path('render-arena.bin'),
                    lambda name:f'call {api[name]};',lambda path:0x11000)
                u.mem_write(0x1820000,c.asm(0x1820000,text+'mov eax,1;ret;failed:xor eax,eax;ret;'))
                u.mem_write(0x1700000,c.pack(0x10000));u.reg_write(UC_X86_REG_ESP,0x1700000)
                calls=[];cache=c.ARENA+0x1e00100
                def windows(cpu,a,n,d):
                    sp=cpu.reg_read(UC_X86_REG_ESP);ret=c.u(cpu.mem_read(sp,4))
                    if a==api['CreateFileA']:pops,result=28,7
                    elif a==api['ReadFile']:
                        handle,dest,count,out,overlap=struct.unpack('<5I',cpu.mem_read(sp+4,20))
                        calls.append((dest,count));self.assertEqual((dest,count),(c.ARENA,size))
                        cpu.mem_write(dest,b'A');cpu.mem_write(dest+count-1,b'Z')
                        if expanded:cpu.mem_write(cache-1,b'X'+b'Q'*0x800+b'Y')
                        cpu.mem_write(out,c.pack(count-int(short)));pops,result=20,1
                    else:pops,result=4,1
                    cpu.reg_write(UC_X86_REG_EAX,result);cpu.reg_write(UC_X86_REG_ESP,sp+4+pops)
                    cpu.reg_write(UC_X86_REG_EIP,ret)
                for address in api.values():u.hook_add(UC_HOOK_CODE,windows,begin=address,end=address)
                u.emu_start(0x1820000,0x10000,count=20000)
                self.assertEqual(u.reg_read(UC_X86_REG_EAX),int(not short))
                self.assertEqual(calls,[(c.ARENA,size)])
                self.assertEqual(bytes(u.mem_read(c.ARENA,1)),b'A')
                self.assertEqual(bytes(u.mem_read(c.ARENA+size-1,1)),b'Z')
                if expanded:
                    self.assertEqual(bytes(u.mem_read(cache-1,0x802)),
                                     b'X'+(b'Q'*0x800 if short else bytes(0x800))+b'Y')


if __name__ == '__main__':
    unittest.main()
