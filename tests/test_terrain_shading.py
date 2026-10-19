"""Vertical terrain lighting: original pixels, history bounds and view resets.

Controlled columns use the caller conventions observed in normal and IR frames.
Original-machine-code comparisons require the verified retail executable. These
tests supplement complete-frame and moving-view playtesting; they do not measure
whole-game performance or establish that a synthetic allocator models the heap.
"""
import struct
import unittest
from features import terrain_raster as f
from patch_support import asm
from original_inputs import original_ram
from tests import with_original_code
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_MEM_WRITE, UC_HOOK_CODE
from unicorn.x86_const import *

BLOCK, YBUF, ROWS = 0x427e10, 0x1000000, 0x1010000
DEST, TEX, FOG = 0x1100000, 0x1500000, 0x1510000
CANVAS, STOP, STACK, SB = 0x1600000, 0x1804000, 0x1808000, 0x41c228


def put(u, address, *values):
    u.mem_write(address, struct.pack('<'+'I'*len(values), *(v&0xffffffff for v in values)))


def call(u, address, **registers):
    put(u, STACK, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK)
    for name,value in registers.items():
        u.reg_write(globals()['UC_X86_REG_'+name],value&0xffffffff)
    u.emu_start(address,STOP,count=2000000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert u.reg_read(UC_X86_REG_ESP)==STACK+4


def machine(shading=True, width=1280):
    u=Uc(UC_ARCH_X86,UC_MODE_32)
    u.mem_map(0,0x2000000)
    u.mem_map(f.SHAD_STATE,0x1000)
    u.mem_write(0x2b2000,bytes(original_ram[0x2b2000:0x2b3000]))
    if shading:
        for a,b in f.shad_bodies():u.mem_write(a,b)
    u.mem_write(TEX,bytes(i%16 for i in range(65536)))
    u.mem_write(SB,bytes(row*16+colour%16 for row in range(16) for colour in range(256)))
    u.mem_write(SB+0x1000,bytes(range(256)))
    u.mem_write(FOG,bytes(range(256)))
    put(u,ROWS,*(DEST+y*width for y in range(400)))
    put(u,0x2b2a6a,ROWS)
    put(u,0x2b2aa0,width)
    put(u,0x2b2b8a,ROWS)
    put(u,0x2b2bb0,width)
    put(u,0x427f54,*(0 if k==0 else 65536//k for k in range(256)))
    put(u,0x44b1a0,CANVAS)
    put(u,CANVAS+6,width<<16)
    u.mem_write(CANVAS+10,struct.pack('<H',400))
    return u


def slab(u, *, width=1280, count=8, top=10, bottom=40, step=0,
         shade=4, phase=0, special=False, ring=0, previous=0):
    put(u,YBUF+f.SHAD_HISTORY,*([previous]*width))
    put(u,YBUF,*([bottom]*width))
    u.mem_write(DEST,b'\xf1'*(width*400))
    put(u,BLOCK,TEX,0x2200,YBUF,width,top*65536,0,
        SB+0x1000 if special else SB+shade*256,FOG,ROWS,width,phase,step)
    put(u,f.SHAD_STATE,ring,ring<<12,(ring-1)<<12)
    writes=[]
    hook=u.hook_add(UC_HOOK_MEM_WRITE,
                   lambda cpu,access,a,n,value,_:writes.append((a,n)))
    call(u,0x2b29b0,EBX=BLOCK,ECX=count,EBP=0x123456)
    u.hook_del(hook)
    assert u.reg_read(UC_X86_REG_EBP)==0x123456
    return (bytes(u.mem_read(DEST,width*400)),bytes(u.mem_read(YBUF,width*4)),
            [(a,n) for a,n in writes if DEST<=a<DEST+width*400])


class TerrainShadingTests(unittest.TestCase):
    @with_original_code
    def test_disabled_columns_keep_original_pixels_and_clipping(self):
        for width in (320,1280,1600):
            a,b=machine(False,width),machine(True,width)
            for phase in (0,128,255):
                for step in (0,32,-32):
                    args=dict(width=width,phase=phase,step=step)
                    self.assertEqual(slab(a,**args),slab(b,**args),args)

    @with_original_code
    def test_supported_flat_columns_match_original(self):
        a,b=machine(False),machine(True)
        for shade,phase,step in ((4,0,0),(0,1152,32),(0,1152,-32),
                                 (0,2176,-256),(0,128,256)):
            for top,bottom in ((10,40),(40,40),(60,40)):
                args=dict(shade=shade,phase=phase,step=step,top=top,bottom=bottom)
                self.assertEqual(slab(a,**args),slab(b,ring=2,**args),args)

    @with_original_code
    def test_previous_ring_changes_only_interior_shading(self):
        for prior_ring in (1,2,255):
            for previous_top in (15,40,80):
                old=slab(machine(False),shade=0,phase=1152,step=32)
                prior=(previous_top<<20)|(prior_ring<<12)|(8*256+128)
                new=slab(machine(),shade=0,phase=1152,step=32,ring=2,previous=prior)
                self.assertEqual(old[1:],new[1:])
                self.assertEqual(old[0]!=new[0],prior_ring==1 and previous_top>=40)

    @with_original_code
    def test_unsupported_palette_or_phase_disables_history_for_view(self):
        a,b=machine(False),machine()
        for args in (dict(special=True),dict(shade=4,phase=128,step=0),
                     dict(shade=4,phase=128,step=32),dict(shade=0,phase=0,step=32),
                     dict(shade=0,phase=128,step=-256),
                     dict(shade=0,phase=1152,step=0x7fffffff)):
            self.assertEqual(slab(a,**args),slab(b,ring=2,**args),args)
            self.assertEqual(bytes(b.mem_read(f.SHAD_STATE,12)),struct.pack('<3I',0,0,0xfffff000))

    def test_allocation_and_ring_tags_reset_for_every_supported_view(self):
        for enabled in (0,1):
            for width,height in ((320,400),(1280,960),(1600,960),(1280,4096)):
                u=machine(width=width)
                put(u,f.SHAD_STATE+12,enabled)
                u.mem_write(CANVAS+10,struct.pack('<H',height))
                # An allocator stub records requested size, returns a known
                # buffer, and leaves original post-allocation setup outside
                # this focused reset test.
                u.mem_write(0x2c4f40,asm(0x2c4f40,f'mov eax,{YBUF};ret'))
                u.mem_write(0x2ab666,b'\xc3')
                requested=[]
                u.hook_add(UC_HOOK_CODE,lambda cpu,a,n,_:requested.append(cpu.reg_read(UC_X86_REG_EAX)),
                           begin=0x2c4f40,end=0x2c4f40)
                for _ in range(2):
                    u.mem_write(YBUF,b'\xaa'*(width*4+f.SHAD_HISTORY+16))
                    put(u,f.SHAD_STATE,90,90<<12,89<<12)
                    call(u,0x2ab65e,EAX=width,ECX=0x1234,EDI=0x5678,EDX=0x4321)
                    supported=enabled and width<=1280 and height<=4095
                    self.assertEqual(requested[-1],4*width+(f.SHAD_HISTORY if supported else 0))
                    expected=(1,0x1000,0) if supported else (0,0,0xfffff000)
                    self.assertEqual(bytes(u.mem_read(f.SHAD_STATE,12)),struct.pack('<3I',*expected))
                    if supported:
                        self.assertEqual(bytes(u.mem_read(YBUF+f.SHAD_HISTORY,width*4)),bytes(width*4))
                    self.assertEqual(bytes(u.mem_read(YBUF+width*4+f.SHAD_HISTORY,16)),b'\xaa'*16)
                    self.assertEqual(u.reg_read(UC_X86_REG_EDX),0x4321)

    def test_ring_limit_stays_disabled_until_next_view(self):
        u=machine()
        u.mem_write(0x2ac33c,b'\xc3')
        u.mem_write(0x2b582b,b'\xc3')
        for before,after in ((1,2),(253,254),(254,0),(0,0)):
            put(u,f.SHAD_STATE,before)
            call(u,0x2b5826,EAX=0x1234)
            self.assertEqual(bytes(u.mem_read(f.SHAD_STATE,12)),
                             struct.pack('<3I',after,after<<12,((after-1)<<12)&0xffffffff))
            self.assertEqual(u.reg_read(UC_X86_REG_EAX),0x1234)

    def test_declared_mutable_operands_are_bounded_and_relocatable(self):
        code,_,fields=f.shad_layout()
        self.assertEqual(len(fields),16)
        self.assertLessEqual(code[-1][0]+len(code[-1][1]),f.SHAD_END)
        for address in fields.values():
            self.assertTrue(f.SHAD_CODE<=address<=f.SHAD_END-4)
            self.assertLessEqual(address&0xfff,0xffc)
        self.assertEqual(len(set(fields.values())),16)

    @with_original_code
    def test_cached_palette_and_stride_operands_follow_current_view(self):
        fields=f.shad_layout()[2]
        for width in (320,1280):
            u=machine(width=width)
            slab(u,width=width,shade=0,phase=1152,step=32,ring=2)
            for name,address in fields.items():
                actual=int.from_bytes(u.mem_read(address,4),'little')
                expected=FOG if name.startswith('P') else width*(1,2,3,4,4,1)[int(name[1:])]
                self.assertEqual(actual,expected,(width,name))

    def test_conflicting_hook_rejects_install_before_any_write(self):
        ram=bytearray(0x2000000)
        state=bytearray(f.SHAD_STATE_SIZE)
        for a,b in f.SHAD_ORIGINAL.items():ram[a:a+len(b)]=b
        ram[0x2b5826]^=1
        read=lambda a,n: bytes(state[a-f.SHAD_STATE:a-f.SHAD_STATE+n]) if a>=f.SHAD_STATE else bytes(ram[a:a+n])
        writes=[]
        with self.assertRaises(ValueError):f.shad_install(lambda a,b:writes.append((a,b)),read)
        self.assertFalse(writes)
