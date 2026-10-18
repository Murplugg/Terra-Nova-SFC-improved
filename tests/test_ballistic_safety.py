"""Ballistic admission boundaries and protected-unit selection.

These synthetic cases isolate cleanup routing and classification. The compiled
query/actual-flight comparisons require original game inputs and are described
in docs/testing.md; these tests do not simulate a whole firefight.
"""
import importlib
import struct
import unittest
from features import ballistic_safety as f, weapon_timing
from patch_support import asm
from tests.test_render_views import Fixture, STACK
from tests.test_ai_firing import actor, execute_until
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *


class Installation(unittest.TestCase):
    def test_conflicts_reject_before_writing(self):
        for conflict in (f.SITE, f.LOW, f.CODE):
            ram = bytearray(0x2000000)
            ram[f.SITE:f.SITE+len(f.ORIGINAL)] = f.ORIGINAL
            ram[conflict] ^= 1
            writes = []
            with self.assertRaises(ValueError):
                f.install(lambda a,b: writes.append((a,b)), lambda a,n: ram[a:a+n],
                          entry=f.LOW, regions=[(f.LOW,b'\xc3')])
            self.assertEqual(writes, [])

    def test_allocation_boundary_preserves_machine_state(self):
        for refuse in (0,1):
            u=Fixture().u
            for a,b in f.bodies(f.LOW, [(f.LOW,asm(f.LOW,f'pxor xmm0,xmm0; mov eax,{refuse}; ret'))]):
                u.mem_write(a,b)
            u.mem_write(STACK+0x368,struct.pack('<H',43))
            u.reg_write(UC_X86_REG_XMM0,0x112233445566778899aabbccddeeff00)
            end=execute_until(u,f.CODE,(0x2d92aa,0x2d9355),esi=0x123450,ebp=0x334455,edx=0x123456)
            self.assertEqual(end,0x2d92aa if refuse else 0x2d9355)
            self.assertEqual(u.reg_read(UC_X86_REG_XMM0),0x112233445566778899aabbccddeeff00)
            self.assertEqual(u.reg_read(UC_X86_REG_ESI),0x123450)
            self.assertEqual(u.reg_read(UC_X86_REG_EBP),0x334455)
            self.assertEqual(u.reg_read(UC_X86_REG_EDX),0x123456)
            self.assertEqual(u.reg_read(UC_X86_REG_ESP),STACK)
            if not refuse:
                self.assertEqual(u.reg_read(UC_X86_REG_EAX),STACK+0x320)
            reason=int.from_bytes(u.mem_read(weapon_timing.TABLE+43*weapon_timing.STRIDE+weapon_timing.LAUNCH_VETO,4),'little')
            self.assertEqual(reason,refuse)


class CompiledPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.helper=importlib.import_module('ballistic_safety_code')
        except ImportError:
            raise unittest.SkipTest('Use test.py --helpers for compiled ballistic checks')

    def test_protection_and_scope(self):
        from tests.test_smoke import call, put
        for kind,team,alive,expected in ((1,1,1,1),(2,1,1,1),(4,1,1,0),(1,2,1,0),(1,1,0,0)):
            u=Fixture().u
            for a,b in f.bodies(self.helper.ENTRY,self.helper.REGIONS):
                u.mem_write(a,b)
            actor(u,1,slot=1,team=1)
            actor(u,43,slot=2,team=1)
            actor(u,44,cls=kind,slot=3,team=team,alive=alive)
            u.mem_write(0x441350,struct.pack('<H',1))
            u.mem_write(0x3c3262+43*37,b'\x05')
            put(u,0x44b9e4+5*4,19);put(u,0x44bb64+19*4,5)
            u.mem_write(0x395110+36*10+7,b'\x01');put(u,0x396404+9+2,65536)
            # Forecast contact is supplied to isolate victim selection. The
            # separate copied-world controls execute real contact prediction.
            u.mem_write(self.helper.FORECAST,asm(self.helper.FORECAST,
                'mov edx,[esp+8]; mov dword ptr [edx+12],0; mov dword ptr [edx+16],0; mov dword ptr [edx+20],0; mov eax,1; ret'))
            u.mem_write(f.DISTANCE,asm(f.DISTANCE,
                'mov eax,[esp+4]; cmp eax,44; jne far; mov eax,32768; ret; far:mov eax,131072; ret'))
            data=0x1900000
            put(u,data,*([0]*10))
            self.assertEqual(call(u,self.helper.ENTRY,[data,43,10,data+24]),expected)
            # Player shots, enemy shooters, unsupported weapons and explicit
            # terrain exclusions must retain the existing firing decision.
            self.assertEqual(call(u,self.helper.ENTRY,[data,1,10,data+24]),0)
            self.assertEqual(call(u,self.helper.ENTRY,[data,43,4,data+24]),0)
            put(u,0x4464b8+5*4,18)
            self.assertEqual(call(u,self.helper.ENTRY,[data,43,10,data+24]),0)

    def test_muzzle_terrain_contact_and_unknown_budget(self):
        from tests.test_smoke import call, put
        u=Fixture().u
        for a,b in f.bodies(self.helper.ENTRY,self.helper.REGIONS):
            u.mem_write(a,b)
        # A terrain surface above the muzzle must be tested at step zero.
        u.mem_write(f.TERRAIN,asm(f.TERRAIN,'mov eax,[esp+16]; mov dword ptr [eax],65536; ret'))
        put(u,0x4534f4,2133)
        data=0x1900000
        launch=[100*65536,100*65536,0,0,0,0,13*65536,16384,0,-1,176,17,5]
        put(u,data,*launch)
        self.assertEqual(call(u,self.helper.FORECAST,[data,data+64]),1)
        self.assertEqual(int.from_bytes(u.mem_read(data+72,4),'little'),0)
        put(u,data+40,0)
        self.assertEqual(call(u,self.helper.FORECAST,[data,data+64]),-1)
