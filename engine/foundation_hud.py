"""Prepare world rendering and HUD composition before native relocation.

World preparation validates viewport bounds and tracks opaque panel coverage.
Projection and allocation calls follow the original engine's calling conventions.
Some DOS video-port code remains in the fixed foundation image for compatibility;
the native host redirects that path to its Windows display service.
"""
import struct, re
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
from foundation_cursor import compositor_source

WORLD = 0x9b60e8
NAV = 0x9b70e8
COMPOSE = 0x9b78e8
COVER = 0x9b84e8
DATA = 0x9b90e8
PIXELS = 0x918ae8
CAPACITY = 480000
CANVAS = 0x9c34e8
CLIP = 0x9c44e8
CLIP2 = 0x9c64e8
EFFECT = 0x9c84e8
MASK = 0x870000
TRACK = 0x9aa1e8
READY = 0x9aa0ec
LOW = 0x9a3d08
HIGH = 0x9a3ce8
CTX = 0x38fb24
FRAME = 0x8a35e8
FAST = 0x9ba0e8
FAST_STATS = 0x9ba8e8
BUSY = 0x9aa0e8
CACHE = 0x860000
RECT = 0x9ad2e8


def branch(a, b):
    return b'\xe9' + struct.pack('<i', b - a - 5)


def dword(n):
    return struct.pack('<I', n)


def assemble(address, source):
    return bytes(
        Ks(KS_ARCH_X86,
           KS_MODE_32).asm(source.replace('rep movsd;', '.byte 0xf3,0xa5;'), addr=address)[0]
    )


def world_source():
    """Render a validated HUD viewport into the enlarged terrain canvas."""
    dimensions = ("cmp word ptr [esi+8],0; je fail;"
                  "cmp word ptr [esi+10],0; je fail;")
    return (
        f"\n cmp edx,{CTX};"
        f" jne other;"
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov dword ptr [{READY}],0;"
        f"\n mov esi,dword ptr [{CTX+28}];"
        f"\n cmp word ptr [esi+12],320;"
        f" jne fail;"
        f"\n {dimensions}\n dimensions:\n mov eax,dword ptr [esi];"
        f" sub eax,dword ptr [0x446f78];"
        f"\n cmp eax,64000;"
        f" jae fail;"
        f"\n xor edx,edx;"
        f" mov ecx,320;"
        f" div ecx;"
        f"\n movzx ebx,word ptr [esi+8];"
        f" add ebx,edx;"
        f" cmp ebx,320;"
        f" ja fail;"
        f"\n movzx ebp,word ptr [esi+10];"
        f" add ebp,eax;"
        f" cmp ebp,200;"
        f" ja fail;"
        f"\n imul eax,eax,3;"
        f" mov dword ptr [{DATA+4}],eax;"
        f"\n imul ebp,ebp,3;"
        f" mov dword ptr [{DATA+12}],ebp;"
        f" sub ebp,eax;"
        f" mov dword ptr [{DATA+20}],ebp;"
        f"\n imul edx,edx,5;"
        f" inc edx;"
        f" shr edx,1;"
        f" mov dword ptr [{DATA}],edx;"
        f"\n imul ebx,ebx,5;"
        f" inc ebx;"
        f" shr ebx,1;"
        f" mov dword ptr [{DATA+8}],ebx;"
        f"\n sub ebx,edx;"
        f" mov dword ptr [{DATA+16}],ebx;"
        f"\n cmp byte ptr [0x449],0x6b;"
        f" je mode_ready;"
        f"\n mov dx,0x3c7;"
        f" xor eax,eax;"
        f" out dx,al;"
        f" add dx,2;"
        f"\n mov edi,0x9aa4e8;"
        f" mov ecx,768;"
        f"\n readpal: in al,dx;"
        f" stosb;"
        f" loop readpal;"
        f"\n mov eax,0x4f02;"
        f" mov ebx,0x4103;"
        f" int 0x10;"
        f"\n mov dx,0x3c8;"
        f" xor eax,eax;"
        f" out dx,al;"
        f" inc dx;"
        f"\n mov esi,0x9aa4e8;"
        f" mov ecx,768;"
        f"\n writepal: lodsb;"
        f" out dx,al;"
        f" loop writepal;"
        f"\n mode_ready:\n mov esi,dword ptr [0x41ec80];"
        f" test esi,esi;"
        f" jz fail;"
        f"\n mov eax,dword ptr [esi-4];"
        f" and eax,0xfffffffc;"
        f" cmp eax,0x80004;"
        f" jae allocated;"
        f"\n mov eax,0x80000;"
        f" call dword ptr [0x35f4a4];"
        f" test eax,eax;"
        f" jz fail;"
        f"\n mov dword ptr [0x41ec80],eax;"
        f"\n mov edi,eax;"
        f" mov ecx,{740*297};"
        f" rep movsb;"
        f"\n mov ecx,{0x80000-740*297};"
        f" xor eax,eax;"
        f" rep stosb;"
        f"\n mov dword ptr [{TRACK}],0;"
        f" inc dword ptr [{DATA+28}];"
        f"\n allocated:\n mov eax,dword ptr [0x41ec80];"
        f" cmp eax,dword ptr [{TRACK}];"
        f" je guarded;"
        f"\n mov dword ptr [{TRACK}],eax;"
        f" lea edi,[eax+{CAPACITY}];"
        f" mov al,0xa5;"
        f" mov ecx,256;"
        f" rep stosb;"
        f"\n guarded:\n mov esi,dword ptr [{CTX+28}];"
        f" mov edi,dword ptr [esi];"
        f"\n movzx ebp,word ptr [esi+10];"
        f" movzx edx,word ptr [esi+12];"
        f"\n movzx ebx,word ptr [esi+8];"
        f" sub edx,ebx;"
        f" xor eax,eax;"
        f"\n clearrow: mov ecx,ebx;"
        f" rep stosb;"
        f" add edi,edx;"
        f" dec ebp;"
        f" jnz clearrow;"
        f"\n mov esi,{CTX};"
        f" mov edi,{LOW};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,dword ptr [{CTX+28}];"
        f" mov edi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov dword ptr [{CANVAS}],{PIXELS};"
        f"\n mov eax,dword ptr [{DATA+16}];"
        f" mov word ptr [{CANVAS+8}],ax;"
        f" mov word ptr [{CANVAS+12}],ax;"
        f"\n mov edx,eax;"
        f" shl edx,16;"
        f" mov dword ptr [{CANVAS+0x34}],edx;"
        f"\n shr eax,1;"
        f" mov dword ptr [{CTX+16}],eax;"
        f" imul eax,dword ptr [{CTX}];"
        f" mov dword ptr [{CTX+8}],eax;"
        f"\n mov eax,dword ptr [{DATA+20}];"
        f" mov word ptr [{CANVAS+10}],ax;"
        f"\n mov edx,eax;"
        f" shl edx,16;"
        f" mov dword ptr [{CANVAS+0x38}],edx;"
        f"\n shr eax,1;"
        f" mov dword ptr [{CTX+20}],eax;"
        f" imul eax,dword ptr [{CTX+4}];"
        f" mov dword ptr [{CTX+12}],eax;"
        f"\n mov dword ptr [{CTX+28}],{CANVAS};"
        f"\n mov esi,{CTX};"
        f" mov edi,{HIGH};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [esp+28];"
        f" mov edx,{CTX};"
        f" call 0x9a36e8;"
        f"\n mov esi,{LOW};"
        f" mov edi,{CTX};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,{LOW};"
        f" mov edi,0x41ebc4;"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [{LOW+28}];"
        f" call 0x2eab30;"
        f"\n mov dword ptr [{READY}],1;"
        f" inc dword ptr [{DATA+24}];"
        f"\n popad;"
        f" popfd;"
        f" ret;"
        f"\n fail: inc dword ptr [{DATA+32}];"
        f" popad;"
        f" popfd;"
        f" ret;"
        f"\n other: jmp 0x9a36e8;"
        f"\n "
    )


def cover_source():
    """Mark opaque panel rectangles after their logical drawing callbacks."""
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov esi,dword ptr [0x389dec];"
        f" mov ebp,dword ptr [0x389de8];"
        f"\n cmp ebp,esi;"
        f" jb done;"
        f" mov eax,ebp;"
        f" sub eax,esi;"
        f" cmp eax,0x2000;"
        f" ja done;"
        f"\n widget:\n cmp dword ptr [esi+0x14],0x265028;"
        f" je mark;"
        f"\n cmp dword ptr [esi+0x18],0x2657a8;"
        f" je mark;"
        f"\n cmp dword ptr [esi+0x18],0x26bd44;"
        f" jne next;"
        f"\n cmp byte ptr [0x38fbfe],0;"
        f" je mark;"
        f"\n test byte ptr [0x35aef0],1;"
        f" jnz next;"
        f"\n mark:\n movsx eax,word ptr [esi+8];"
        f" movsx edx,word ptr [esi+10];"
        f"\n movsx ebx,word ptr [esi+12];"
        f" movsx ecx,word ptr [esi+14];"
        f"\n test eax,eax;"
        f" js next;"
        f" test edx,edx;"
        f" js next;"
        f"\n cmp ebx,320;"
        f" ja next;"
        f" cmp ecx,200;"
        f" ja next;"
        f"\n sub ebx,eax;"
        f" jle next;"
        f" sub ecx,edx;"
        f" jle next;"
        f"\n push esi;"
        f" push ebp;"
        f" mov ebp,ecx;"
        f"\n imul edi,edx,320;"
        f" add edi,eax;"
        f" add edi,{MASK};"
        f" xor eax,eax;"
        f"\n row: mov ecx,ebx;"
        f" rep stosb;"
        f" add edi,320;"
        f" sub edi,ebx;"
        f" dec ebp;"
        f" jnz row;"
        f"\n pop ebp;"
        f" pop esi;"
        f"\n next: add esi,0x62;"
        f" cmp esi,ebp;"
        f" jbe widget;"
        f"\n inc dword ptr [{DATA+36}];"
        f"\n done: popad;"
        f" popfd;"
        f" ret;"
        f"\n "
    )


def nav_source():
    from foundation_recipes import navigation_overlay_source
    return navigation_overlay_source(canvas=CANVAS, pixels=PIXELS, dynamic=True)


# Fixed initialized footprints include padding retained by the accepted image.
# They are layout contracts, independent of how long the current routines are.
WORLD_BYTES = 685
COVER_BYTES = 198


def padded_body(address, source, size):
    code = assemble(address, source)
    if len(code) > size:
        raise ValueError(f'Foundation body exceeds its slot at {address:#x}')
    return code.ljust(size, b'\x90')


def hud():
    """Install final world preparation, panel coverage and drawing buffers.

    The camera foundation owns the optimized compositor. The cursor foundation
    owns its entry jump. This provider supplies the bounded world view and the
    retained pixel compositor, with dialog coverage authored directly.
    """
    payload = [
        (WORLD, padded_body(WORLD, world_source(), WORLD_BYTES)),
        (NAV, assemble(NAV, nav_source())),
        (
            COMPOSE,
            assemble(
                COMPOSE,
                compositor_source(
                    buffered=True,
                    cached=True,
                    outlined=True,
                    viewport=DATA,
                    pixels=PIXELS,
                    cover=COVER,
                    coverage_tracks_dialogs=True
                )
            )
        ),
        (COVER, padded_body(COVER, cover_source(), COVER_BYTES)),
        (0x9a94e8, branch(0x9a94e8, WORLD)),
        (0x29ba3c, branch(0x29ba3c, NAV)),
    ]
    for a, value in (
        (0x29e3ef, CLIP), (0x29e210, CLIP - 4), (0x29e24c, CLIP - 4), (0x29e374, CLIP - 4),
        (0x2a84ae, CLIP2), (0x2a86ad, CLIP2), (0x2a84b3, 800 * 4), (0x2a87b7,
                                                                    EFFECT), (0x2b22f6, EFFECT)
    ):
        payload.append((a, dword(value)))
    payload.extend((a, dword(0x80000)) for a in (0x26152e, 0x261574, 0x262f69, 0x26303f))
    return payload


def fast_source(*, prepare, merge):
    """Compose a frame with odd-width copies, empty-cell skipping and cameras."""
    STATS = FAST_STATS
    remainder = 'mov ecx,ebx; and ecx,3; rep movsb;'
    prepare_call = f'call {prepare};'
    merge_call = f'call {merge};'
    # Explicit dialog coverage replaces the fixed pause rectangle. Preserve the
    # instruction footprint so downstream helpers and snapshots keep their layout.
    coverage_branch = 'jmp'
    empty_cells = (
        f"cmp edx,316;"
        f" ja single_cell;"
        f"\n cmp dword ptr [esi],0;"
        f" jne single_cell;"
        f"\n cmp dword ptr [esi+{MASK-CACHE}],0xffffffff;"
        f" jne single_cell;"
        f"\n cmp dword ptr [{READY}],0;"
        f" je single_cell;"
        f"\n cmp byte ptr [0x35f3f4],0;"
        f" jne single_cell;"
        f"\n cmp ebp,dword ptr [{DATA+4}];"
        f" jb single_cell;"
        f"\n cmp ebp,dword ptr [{DATA+12}];"
        f" jae single_cell;"
        f"\n cmp ebx,dword ptr [{DATA}];"
        f" jb single_cell;"
        f"\n lea eax,[ebx+10];"
        f" cmp eax,dword ptr [{DATA+8}];"
        f" ja single_cell;"
        f"\n add esi,4;"
        f" add edi,10;"
        f" add ebx,10;"
        f" add edx,4;"
        f"\n cmp edx,320;"
        f" jb pixel;"
        f" jmp row_finish;"
        f"\n single_cell:"
    )
    row_finish = 'row_finish:'
    s = (
        f"\n pushfd;"
        f"\n test eax,eax;"
        f" jz fast;"
        f"\n popfd;"
        f" jmp {COMPOSE};"
        f"\n fast: pushad;"
        f" cld;"
        f"\n cmp dword ptr [{BUSY}],0;"
        f" jne done;"
        f"\n mov dword ptr [{BUSY}],1;"
        f" inc byte ptr [0x447115];"
        f"\n mov esi,dword ptr [0x446f78];"
        f" mov edi,{CACHE};"
        f" mov ecx,16000;"
        f"\n .byte 0xf3,0xa5;"
        f"\n {prepare_call} call {COVER};"
        f"\n movsx eax,word ptr [0x390250];"
        f" imul eax,eax,5;"
        f" inc eax;"
        f" sar eax,1;"
        f" mov dword ptr [{RECT}],eax;"
        f"\n movsx eax,word ptr [0x390254];"
        f" imul eax,eax,5;"
        f" inc eax;"
        f" sar eax,1;"
        f" mov dword ptr [{RECT+4}],eax;"
        f"\n movsx eax,word ptr [0x390252];"
        f" imul eax,eax,3;"
        f" mov dword ptr [{RECT+8}],eax;"
        f"\n movsx eax,word ptr [0x390256];"
        f" imul eax,eax,3;"
        f" mov dword ptr [{RECT+12}],eax;"
        f"\n cmp dword ptr [{READY}],0;"
        f" je hud;"
        f"\n mov esi,{PIXELS};"
        f" mov edi,dword ptr [{DATA+4}];"
        f" imul edi,edi,800;"
        f"\n add edi,dword ptr [{DATA}];"
        f" add edi,{FRAME};"
        f"\n mov ebp,dword ptr [{DATA+20}];"
        f" mov ebx,dword ptr [{DATA+16}];"
        f"\n mov edx,800;"
        f" sub edx,ebx;"
        f"\n worldrow: mov ecx,ebx;"
        f" shr ecx,2;"
        f" .byte 0xf3,0xa5;"
        f" {remainder}\n add edi,edx;"
        f" dec ebp;"
        f" jnz worldrow;"
        f"\n hud: mov esi,{CACHE};"
        f" mov edi,{FRAME};"
        f" xor ebp,ebp;"
        f"\n row: xor ebx,ebx;"
        f" xor edx,edx;"
        f"\n pixel:\n {empty_cells}\n mov ecx,edx;"
        f" and ecx,1;"
        f" neg ecx;"
        f" add ecx,3;"
        f"\n mov al,byte ptr [esi];"
        f" test al,al;"
        f" jnz opaque;"
        f"\n cmp dword ptr [{READY}],0;"
        f" je opaque;"
        f"\n cmp ebp,dword ptr [{DATA+4}];"
        f" jb opaque;"
        f"\n cmp ebp,dword ptr [{DATA+12}];"
        f" jae opaque;"
        f"\n cmp ebx,dword ptr [{DATA}];"
        f" jb opaque;"
        f"\n cmp ebx,dword ptr [{DATA+8}];"
        f" jae opaque;"
        f"\n cmp byte ptr [0x35f3f4],0;"
        f" {coverage_branch} coverage;"
        f"\n cmp ebp,dword ptr [{RECT+8}];"
        f" jl coverage;"
        f"\n cmp ebp,dword ptr [{RECT+12}];"
        f" jge coverage;"
        f"\n cmp ebx,dword ptr [{RECT}];"
        f" jl coverage;"
        f"\n cmp ebx,dword ptr [{RECT+4}];"
        f" jl opaque;"
        f"\n coverage: cmp byte ptr [esi+{MASK-CACHE}],0;"
        f" jne next;"
        f"\n opaque:\n mov ah,al;"
        f"\n mov word ptr [edi],ax;"
        f" mov word ptr [edi+800],ax;"
        f" mov word ptr [edi+1600],ax;"
        f"\n cmp ecx,3;"
        f" jne next;"
        f"\n mov byte ptr [edi+2],al;"
        f" mov byte ptr [edi+802],al;"
        f" mov byte ptr [edi+1602],al;"
        f"\n next: inc esi;"
        f" add edi,ecx;"
        f" add ebx,ecx;"
        f" inc edx;"
        f" cmp edx,320;"
        f" jb pixel;"
        f"\n {row_finish} add edi,1600;"
        f" add ebp,3;"
        f" cmp ebp,600;"
        f" jb row;"
        f"\n {merge_call} mov esi,{FRAME};"
        f" mov edi,0xe0000000;"
        f" mov ecx,120000;"
        f" .byte 0xf3,0xa5;"
        f"\n inc dword ptr [{STATS}];"
        f"\n dec byte ptr [0x447115];"
        f" mov dword ptr [{BUSY}],0;"
        f"\n done: popad;"
        f" popfd;"
        f" ret;"
        f"\n "
    )
    # Retain unambiguous local labels for the pinned Keystone assembler.
    return re.sub(r'\b(fast|done|hud|worldrow|row|pixel|opaque|coverage|next)\b', r'compose_\1', s)


def fast_compositor(**kwargs):
    return assemble(FAST, fast_source(**kwargs))


GUARDS = (
    PIXELS - 256, PIXELS + CAPACITY, CLIP - 256, CLIP + 800 * 4, CLIP2 - 256, CLIP2 + 800 * 4,
    EFFECT - 256, EFFECT + 600 * 4
)
