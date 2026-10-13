"""Build the Windows executable that hosts the original game instructions."""
from pathlib import Path
import struct
from le_image import LE, U
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import host_files as fs
import host_services as svc
import host_video as video
import host_window as window
from features import frame_clock as native_clock
from features import input_views as inputs, projectiles, cameras, weapon_timing, actor_timing, effect_timing
import host_audio as native_audio


def build(le_bytes, config):
    """Relocate the game and connect its system calls to Windows services.

    Original x86 instructions execute directly. The exception handler implements
    the required DOS calls and stops with diagnostics on unsupported operations.
    Feature installation follows this host setup to produce the playable game.
    """

    p = Path(config['log_root'])
    RUN_MS = config['run_ms']
    BASE = 0x10000
    START = 0x11000
    END = 0x2000000
    ENTRY = 0x1d00000
    HANDLER = 0x1d00800
    IMPORTS = 0x1d03000
    ILT = 0x1d03100
    IAT = 0x1d03200
    NAMES = 0x1d03300
    STATE = 0x1d04000
    LOG = 0x1d40000
    LOG_SIZE = 512 * 1024
    LOGFILE = 0x1d05000
    DUMPFILE = 0x1d05400
    PSP = 0x60000
    ENV = 0x70000
    CB = 0x1c00000
    le = LE(le_bytes)
    bases = (0x244000, 0x72000, 0x355000, 0x8234e8)
    r = bytearray(END)

    def write(a, b):
        r[a:a + len(b)] = b

    def d(a, v):
        write(a, struct.pack('<I', v))

    for a, b in zip(bases, le.relocated(bases, (0x23, 0x2b, 0x2b, 0x2b))):
        if a:
            write(a, b)
    d(CB + 0x10, PSP)
    d(CB + 0x1c, bases[2])
    write(PSP + 0x2c, struct.pack('<H', ENV >> 4))
    write(ENV, b'TN_DIR=C:\\TNOVA\0GEN_DIR=C:\\TNOVA\0\0\x01\0TNHR.EXE\0')
    d(STATE + 20, 0xb00000)
    write(LOGFILE, str((p / 'services.bin').resolve()).encode() + b'\0')
    write(DUMPFILE, str((p / 'stopped-memory.bin').resolve()).encode() + b'\0')
    write(0x1d05600, str((p / 'stdout.txt').resolve()).encode() + b'\0')
    cfg = Path(config['config_file']).resolve()
    write(0x1d05800, str(cfg).encode() + b'\0')
    write(0x1d05500, str((p / "framebuffer.bin").resolve()).encode() + b"\0")
    fs.setup(write)
    svc.setup(write)
    video.setup(write)
    assert r[0x304dd9:0x304dde] == bytes.fromhex('bb17040000')
    d(0x304dda, 0x1d0d417)
    assert r[0x2445d2:0x2445d7] == bytes.fromhex('b801000000')
    d(0x2445d3, 1)
    inputs.initialize_mouse(write)
    bda_patches = svc.bda_setup(r, write)
    names = [
        'ExitProcess', 'CreateFileA', 'WriteFile', 'CloseHandle', 'SetErrorMode',
        'AddVectoredExceptionHandler', 'GetLocalTime', 'ReadFile', 'SetFilePointer'
    ] + fs.APIS + svc.APIS + [
        'GetTickCount64', 'QueryPerformanceCounter', 'QueryPerformanceFrequency'
    ] + window.APIS
    write(IMPORTS, struct.pack('<5I', ILT - BASE, 0, 0, NAMES - BASE, IAT - BASE) + bytes(20))
    write(NAMES, b'kernel32.dll\0')
    at = NAMES + 32
    api = {}
    for i, name in enumerate(names):
        write(at, b'\0\0' + name.encode() + b'\0')
        d(ILT + i * 4, at - BASE)
        d(IAT + i * 4, at - BASE)
        api[name] = IAT + i * 4
        at += (len(name) + 4) & ~1

    def call(name):
        return f'call dword ptr [{api[name]}];'

    def output(path, buffer, size):
        return (
            f"push 0;"
            f"push 0x80;"
            f"push 2;"
            f"push 0;"
            f"push 0;"
            f"push 0x40000000;"
            f"push {path};"
        ) + call('CreateFileA') + (
            f"mov ebx,eax;"
            f"push 0;"
            f"push {STATE+8};"
            f"push {size};"
            f"push {buffer};"
            f"push ebx;"
        ) + call('WriteFile') + 'push ebx;' + call('CloseHandle')

    gameentry = bases[U(le.h, 0x18) - 1] + U(le.h, 0x1c)
    stack = bases[U(le.h, 0x20) - 1] + U(le.h, 0x24)
    k = Ks(KS_ARCH_X86, KS_MODE_32)

    def asm(a, s):
        return bytes(k.asm(s.replace('rep movsd;', '.byte 0xf3,0xa5;'), addr=a)[0])

    assert r[0x2fe810:0x2fe818] == bytes.fromhex('56578b155c463600')
    write(0x2fe810, asm(0x2fe810, 'jmp 0x1d18000'))
    win = window.setup(write, asm, call)
    inputs.connect(write, asm, win, window, r)
    video.palette_setup(write, asm, r)
    svc.exception_setup(write, asm, r)
    native_audio.setup(write, asm, call, r)
    # The S3-register refresh is specific to emulated DOS display mappings.
    # Native VBE owns a stable Windows mapping and has no emulated S3 device.
    assert r[0x9ab8e8:0x9ab8ed] == asm(0x9ab8e8, 'jmp 0x9b98e8')
    write(0x9ab8e8, asm(0x9ab8e8, 'jmp 0x9ae6e8'))
    clock_callbacks = native_clock.Callbacks(
        native_audio.slot('TN_FrameBegin'), native_audio.slot('TN_FrameEnd'),
        native_audio.slot('TN_TimeMS'), window.PUMP
    )
    native_clock.install(write, lambda a, n: r[a:a + n], clock_callbacks)
    projectiles.install(write, lambda a, n: r[a:a + n], part='physics')
    actor_timing.jet_setup(write, asm, r)
    effect_timing.water_noise_setup(write, asm, r)
    actor_timing.protection_setup(write, asm, r)
    cameras.eye_setup(write, asm, r)
    weapon_timing.install(write, lambda a, n: r[a:a + n])
    projectiles.install(write, lambda a, n: r[a:a + n], part='sweep')
    actor_timing.vehicle_protection_setup(write, asm, r)
    cameras.install_low_width(write, lambda a, n: r[a:a + n])

    write(
        ENTRY,
        asm(
            ENTRY, (
                f"cld;"
                f"fninit;"
                f"push 3;"
                f"{call('SetErrorMode')}\n     push {HANDLER};"
                f"push 1;"
                f"{call('AddVectoredExceptionHandler')}\n     call {native_audio.INIT};"
                f"call {window.INIT};"
                f"push 0x1d0f120;"
                f"{call('QueryPerformanceFrequency')}push 0x1d0f110;"
                f"{call('QueryPerformanceCounter')}mov esp,{stack};"
                f"xor ebp,ebp;"
                f"xor eax,eax;"
                f"xor ebx,ebx;"
                f"xor ecx,ecx;"
                f"xor edx,edx;"
                f"xor esi,esi;"
                f"xor edi,edi;"
                f"jmp {gameentry};"
            )
        )
    )
    # x86 CONTEXT offsets from winnt.h. Only documented return fields are changed.
    handler = (
        f"\n     pushad;"
        f"cld;"
        f"mov eax,[esp+36];"
        f"mov ebp,[eax+4];"
        f"mov edx,[eax];"
        f"\n     inc dword ptr [{STATE+24}];"
        f"\n     mov eax,[ebp+0xb8];"
        f"cmp [{STATE+28}],eax;"
        f"jne record;"
        f"mov ecx,[ebp+0xb0];"
        f"cmp [{STATE+32}],ecx;"
        f"je dispatch;"
        f"\n     record:mov [{STATE+28}],eax;"
        f"mov ecx,[ebp+0xb0];"
        f"mov [{STATE+32}],ecx;"
        f"\n     mov ecx,[{STATE}];"
        f"cmp ecx,{LOG_SIZE//64};"
        f"jb record_space;"
        f"xor ecx,ecx;"
        f"mov [{STATE}],ecx;"
        f"inc dword ptr [{STATE+0x1c0}];"
        f"record_space:\n     shl ecx,6;"
        f"lea edi,[ecx+{LOG}];"
        f"\n     mov eax,[edx];"
        f"stosd;"
        f"mov eax,[ebp+0xb8];"
        f"stosd;"
        f"\n     mov esi,eax;"
        f"xor eax,eax;"
        f"cmp esi,{START};"
        f"jb record_unknown;"
        f"cmp esi,{END-4};"
        f"ja record_unknown;"
        f"mov eax,[esi];"
        f"record_unknown:stosd;"
        f"mov eax,[ebp+0xc0];"
        f"stosd;"
        f"\n     lea esi,[ebp+0x9c];"
        f"mov ecx,8;"
        f"rep movsd;"
        f"\n     mov eax,[ebp+0xc4];"
        f"stosd;"
        f"mov eax,[ebp+0x94];"
        f"stosd;"
        f"mov eax,[ebp+0x98];"
        f"stosd;"
        f"mov eax,[ebp+0xbc];"
        f"stosd;"
        f"\n     inc dword ptr [{STATE}];"
        f"\n     dispatch:mov eax,[edx];"
        f"cmp eax,0xc0000094;"
        f"je native_divide;"
        f"cmp eax,0xc0000095;"
        f"je native_divide;"
        f"mov esi,[ebp+0xb8];"
        f"cmp esi,{START};"
        f"jb stop;"
        f"cmp esi,{END-4};"
        f"ja stop;"
        f"cmp byte ptr [esi],0xe4;"
        f"je input_in_imm8;"
        f"cmp byte ptr [esi],0xe6;"
        f"je native_out_imm8;"
        f"cmp byte ptr [esi],0xee;"
        f"je native_out8;"
        f"cmp byte ptr [esi],0xec;"
        f"je native_in8;"
        f"cmp byte ptr [esi],0xfb;"
        f"je sti;"
        f"cmp byte ptr [esi],0xfa;"
        f"je cli;"
        f"\n     cmp word ptr [esi],0x10cd;"
        f"je direct_video;"
        f"cmp word ptr [esi],0x33cd;"
        f"je native_mouse;"
        f"cmp word ptr [esi],0x31cd;"
        f"je dpmi;"
        f"\n     cmp word ptr [esi],0x21cd;"
        f"jne stop;"
        f"\n     mov eax,[ebp+0xb0];"
        f"cmp ah,0x35;"
        f"je dos_getvector;"
        f"cmp ah,0x25;"
        f"je dos_setvector;"
        f"cmp ah,0x4c;"
        f"je native_process_exit;"
        f"cmp ah,0x30;"
        f"je version;"
        f"cmp ah,0x4a;"
        f"je resize;"
        f"\n     cmp eax,0x80004800;"
        f"je allocate;"
        f"\n     cmp ah,0x2c;"
        f"je localtime;"
        f"\n     cmp ax,0x4400;"
        f"je deviceinfo;"
        f"\n     cmp ah,0x41;"
        f"je deletefile;"
        f"cmp ah,0x3c;"
        f"je createfile;"
        f"cmp ah,0x40;"
        f"je choosewrite;"
        f"\n     cmp ax,0x4b00;"
        f"je execdrive;"
        f"cmp ah,0x4d;"
        f"je childstatus;"
        f"cmp ah,0x36;"
        f"je diskspace;"
        f"cmp ax,0x4300;"
        f"je fileattrs;"
        f"cmp ah,0x1a;"
        f"je setdta;"
        f"cmp ax,0x3700;"
        f"je switchchar;"
        f"cmp ah,0x0b;"
        f"je stdinstatus;"
        f"\n     cmp ah,0x2f;"
        f"je getdta;"
        f"cmp ah,0x4e;"
        f"je findfirst;"
        f"cmp ah,0x4f;"
        f"je findnext;"
        f"cmp ah,0x19;"
        f"je currentdrive;"
        f"cmp ah,0x47;"
        f"je currentdir;"
        f"cmp ah,0x3d;"
        f"je openconfig;"
        f"cmp ah,0x3f;"
        f"je readconfig;"
        f"cmp ah,0x3e;"
        f"je closeconfig;"
        f"cmp ah,0x42;"
        f"je seekconfig;"
        f"\n     jmp stop;"
        f"\n     dpmi:mov eax,[ebp+0xb0];"
        f"cmp ax,0;"
        f"je selector_alloc;"
        f"cmp ax,1;"
        f"je selector_free;"
        f"cmp ax,7;"
        f"je selector_setbase;"
        f"cmp ax,8;"
        f"je selector_setlimit;"
        f"cmp ax,0x400;"
        f"je dpmi_version;"
        f"cmp ax,0x200;"
        f"je get_real_interrupt;"
        f"cmp ax,0x201;"
        f"je set_real_interrupt;"
        f"cmp ax,0x100;"
        f"je dosmem_alloc;"
        f"cmp ax,0x101;"
        f"je dosmem_free;"
        f"cmp ax,6;"
        f"je selector_base;"
        f"cmp ax,3;"
        f"je selector_increment;"
        f"cmp ax,0x300;"
        f"je rm_interrupt;"
        f"cmp ax,0x801;"
        f"je unmap_framebuffer;"
        f"cmp ax,0x800;"
        f"je map_framebuffer;"
        f"cmp ax,0x600;"
        f"je pagelock;"
        f"cmp ax,0x601;"
        f"je pagelock;"
        f"\n     cmp ax,0x202;"
        f"je getexception;"
        f"cmp ax,0x203;"
        f"je setexception;"
        f"cmp ax,0x204;"
        f"je getinterrupt;"
        f"cmp ax,0x205;"
        f"je setinterrupt;"
        f"jmp stop;"
        f"\n     {svc.assembly(call,STATE,END)}\n     {video.assembly(call,STATE,END)}\n     native_process_exit:mov dword ptr [{STATE+0x1d4}],1;"
        f"movzx eax,byte ptr [ebp+0xb0];"
        f"mov [{STATE+0x1d8}],eax;"
        f"jmp stop;"
        f"\n     {inputs.mouse_assembly()}\n     direct_video:cmp byte ptr [ebp+0xb1],0x4f;"
        f"je direct_vbe;"
        f"cmp byte ptr [ebp+0xb1],0;"
        f"je direct_setmode;"
        f"cmp word ptr [ebp+0xb0],0x1a00;"
        f"jne stop;"
        f"mov byte ptr [ebp+0xb0],0x1a;"
        f"mov word ptr [ebp+0xa4],8;"
        f"jmp resume;"
        f"direct_setmode:mov esi,0x1d0f200;"
        f"mov eax,[ebp+0xb0];"
        f"mov [esi+28],eax;"
        f"jmp bios_setmode;"
        f"\n     direct_vbe:mov esi,0x1d0f200;"
        f"mov eax,[ebp+0xb0];"
        f"mov [esi+28],eax;"
        f"mov eax,[ebp+0xa4];"
        f"mov [esi+16],eax;"
        f"mov eax,[ebp+0xac];"
        f"mov [esi+24],eax;"
        f"mov eax,[ebp+0xa8];"
        f"mov [esi+20],eax;"
        f"mov dword ptr [0x1d0f238],1;"
        f"mov ax,[esi+28];"
        f"cmp ax,0x4f02;"
        f"je vbe_setmode;"
        f"cmp ax,0x4f03;"
        f"je vbe_getmode;"
        f"cmp ax,0x4f06;"
        f"je vbe_scanline;"
        f"cmp ax,0x4f07;"
        f"je vbe_displaystart;"
        f"jmp stop;"
        f"\n     input_in_imm8:cmp byte ptr [esi+1],0x60;"
        f"jne stop;"
        f"mov al,[30471168];"
        f"mov byte ptr [ebp+0xb0],al;"
        f"jmp resume;"
        f"\n     {svc.exception_assembly()}\n     getinterrupt:movzx eax,byte ptr [ebp+0xa4];"
        f"mov ecx,[eax*8+0x1d07000];"
        f"mov edx,[eax*8+0x1d07004];"
        f"\n     mov [ebp+0xac],ecx;"
        f"mov [ebp+0xa8],edx;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     setinterrupt:movzx eax,byte ptr [ebp+0xa4];"
        f"mov ecx,[ebp+0xac];"
        f"mov edx,[ebp+0xa8];"
        f"mov [eax*8+0x1d07000],ecx;"
        f"mov [eax*8+0x1d07004],edx;"
        f"\n     and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     getexception:movzx eax,byte ptr [ebp+0xa4];"
        f"cmp eax,32;"
        f"jae stop;"
        f"mov ecx,[eax*8+0x1d06000];"
        f"mov edx,[eax*8+0x1d06004];"
        f"\n     mov [ebp+0xac],ecx;"
        f"mov [ebp+0xa8],edx;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     setexception:movzx eax,byte ptr [ebp+0xa4];"
        f"cmp eax,32;"
        f"jae stop;"
        f"mov ecx,[ebp+0xac];"
        f"mov edx,[ebp+0xa8];"
        f"mov [eax*8+0x1d06000],ecx;"
        f"mov [eax*8+0x1d06004],edx;"
        f"\n     and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     pagelock:mov eax,[ebp+0xa4];"
        f"shl eax,16;"
        f"mov ax,word ptr [ebp+0xac];"
        f"cmp eax,0x11000;"
        f"jb stop;"
        f"\n     mov edx,[ebp+0xa0];"
        f"shl edx,16;"
        f"mov dx,word ptr [ebp+0x9c];"
        f"add edx,eax;"
        f"jc stop;"
        f"cmp edx,{END};"
        f"ja stop;"
        f"\n     and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     version:mov dword ptr [ebp+0xb0],0x42430600;"
        f"mov dword ptr [ebp+0xa8],{CB};"
        f"jmp resume;"
        f"\n     resize:cmp dword ptr [ebp+0xa8],{bases[2]};"
        f"jne stop;"
        f"mov eax,[ebp+0xa4];"
        f"add eax,{bases[2]};"
        f"jc stop;"
        f"cmp eax,0xb00000;"
        f"ja stop;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     setdta:mov eax,[ebp+0xa8];"
        f"cmp eax,0x11000;"
        f"jb stop;"
        f"cmp eax,{END-128};"
        f"ja stop;"
        f"mov [{STATE+64}],eax;"
        f"jmp resume;"
        f"\n     choosewrite:cmp word ptr [ebp+0xa4],5;"
        f"jae writefile;"
        f"\n     consolewrite:mov eax,[ebp+0xa4];"
        f"cmp eax,1;"
        f"je consoleok;"
        f"cmp eax,2;"
        f"jne stop;"
        f"\n     consoleok:mov ecx,[ebp+0xac];"
        f"mov esi,[ebp+0xa8];"
        f"cmp esi,0x11000;"
        f"jb stop;"
        f"mov eax,esi;"
        f"add eax,ecx;"
        f"jc stop;"
        f"cmp eax,{END};"
        f"ja stop;"
        f"\n     mov edi,[{STATE+40}];"
        f"add edi,ecx;"
        f"jc stop;"
        f"cmp edi,8192;"
        f"ja stop;"
        f"mov edi,[{STATE+40}];"
        f"add edi,0x1d20000;"
        f"\n     mov [ebp+0xb0],ecx;"
        f"add [{STATE+40}],ecx;"
        f"rep movsb;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     {fs.assembly(call,STATE,END)}\n     deviceinfo:mov eax,[ebp+0xa4];"
        f"and eax,0xffff;"
        f"cmp eax,5;"
        f"jb standardinfo;"
        f"cmp eax,32;"
        f"jae stop;"
        f"cmp dword ptr [eax*4+{fs.HANDLES}],0;"
        f"je stop;"
        f"jmp diskinfo;"
        f"standardinfo:cmp eax,2;"
        f"ja stop;"
        f"\n     mov dword ptr [ebp+0xa8],0x80d3;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     diskinfo:mov dword ptr [ebp+0xa8],2;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     localtime:push {STATE+0x100};"
        f"{call('GetLocalTime')}\n     movzx ecx,word ptr [{STATE+0x108}];"
        f"shl ecx,8;"
        f"\n     mov cl,byte ptr [{STATE+0x10a}];"
        f"mov [ebp+0xac],ecx;"
        f"\n     movzx eax,word ptr [{STATE+0x10e}];"
        f"xor edx,edx;"
        f"mov ecx,10;"
        f"div ecx;"
        f"\n     movzx edx,byte ptr [{STATE+0x10c}];"
        f"shl edx,8;"
        f"mov dl,al;"
        f"mov [ebp+0xa8],edx;"
        f"jmp resume;"
        f"\n     allocate:mov eax,[{STATE+20}];"
        f"mov edx,[ebp+0xa4];"
        f"test edx,edx;"
        f"jz stop;"
        f"\n     add edx,15;"
        f"jc stop;"
        f"and edx,0xfffffff0;"
        f"add edx,eax;"
        f"jc stop;"
        f"cmp edx,0x1800000;"
        f"ja stop;"
        f"\n     mov [{STATE+20}],edx;"
        f"mov [ebp+0xb0],eax;"
        f"and dword ptr [ebp+0xc0],0xfffffffe;"
        f"jmp resume;"
        f"\n     sti:mov dword ptr [{STATE+16}],1;"
        f"jmp resume_one;"
        f"\n     cli:mov dword ptr [{STATE+16}],0;"
        f"\n     resume_one:inc dword ptr [ebp+0xb8];"
        f"popad;"
        f"mov eax,-1;"
        f"ret 4;"
        f"\n     resume:add dword ptr [ebp+0xb8],2;"
        f"popad;"
        f"mov eax,-1;"
        f"ret 4;"
        f"\n     stop:\n     cmp dword ptr [{svc.VBE_STATE+4}],0;"
        f"je no_framebuffer_dump;"
        f"\n     {output(0x1d05500,svc.FB,svc.FB_SIZE)}\n     no_framebuffer_dump:\n     {output(LOGFILE,LOG,LOG_SIZE)}\n     {output(DUMPFILE,START,END-START)}\n     {output(0x1d05600,0x1d20000,f'dword ptr [{STATE+40}]')}\n     push 0;"
        f"{call('ExitProcess')}\n    "
    )
    body = asm(HANDLER, handler)
    assert len(body) < 0x2800
    write(HANDLER, body)
    h = bytearray(512)
    h[:2] = b'MZ'
    struct.pack_into('<I', h, 0x3c, 0x80)
    h[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', h, 0x84, 0x14c, 1, 0, 0, 0, 224, 0x123)
    o = 0x98
    struct.pack_into('<H', h, o, 0x10b)
    for off, val in (
        (4, END - START), (16, ENTRY - BASE), (20, 0x1000), (24, 0x1000), (28, BASE), (32, 4096),
        (36, 512), (56, END - BASE), (60, 512), (72, 0x100000), (76, 0x10000), (80, 0x100000),
        (84, 0x1000), (92, 16), (104, IMPORTS - BASE), (108, 40), (192, IAT - BASE),
        (196, (len(names) + 1) * 4)
    ):
        struct.pack_into('<I', h, o + off, val)
    struct.pack_into('<HH', h, o + 40, 6, 0)
    struct.pack_into('<HH', h, o + 48, 6, 0)
    struct.pack_into('<H', h, o + 68, 3)
    sec = o + 224
    h[sec:sec + 8] = b'.game\0\0\0'
    struct.pack_into(
        '<IIIIIIHHI', h, sec + 8, END - START, 0x1000, END - START, 512, 0, 0, 0, 0, 0xe0000060
    )
    return bytes(h + r[START:])
