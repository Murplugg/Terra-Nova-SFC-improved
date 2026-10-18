"""Draw detailed maps while retaining the game's markers and widget behavior.

Terrain drawing is reconstructed from the supported original routine. Cache and
merge helpers keep map pixels tied to the correct view, palette and widget owner.
Separate helpers repair dark map colors and center the large map on the player.
"""
from dataclasses import dataclass
import hashlib, struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from features import hud
from features.render_views import assemble as code
from patch_support import asm

TERRAIN = 0x1e44000
ENTRY = 0x1e45000
ORIGINAL = 0x1e45700
BACKGROUND = 0x1e45800
MERGE = 0x1e45a00
CTX = 0x1e46000
KEY = 0x1e46100
CONTROL = 0x1e46200
SLOT = hud.SLOTS + 384
PIXELS = 0x1f00100
REF = 0x1f78000
MASK = 0x1fa0000
BUFFERS = ((PIXELS, 480000), (REF, 128000), (MASK, 128000))


@dataclass(frozen=True)
class Symbols:
    TERRAIN: int = TERRAIN
    ENTRY: int = ENTRY
    ORIGINAL: int = ORIGINAL
    BACKGROUND: int = BACKGROUND
    MERGE: int = MERGE
    CTX: int = CTX
    KEY: int = KEY
    CONTROL: int = CONTROL
    SLOT: int = SLOT
    PIXELS: int = PIXELS
    REF: int = REF
    MASK: int = MASK


SYMBOLS = Symbols()
ORIGINAL_START = 0x2774c0
ORIGINAL_END = 0x277829
ORIGINAL_SHA256 = 'd1d64269ea745058624b9323598b3944af23f721fa357decddc3f7cd11a5a7c0'


def terrain_code(read):
    start = 0x2774c0
    end = 0x277829
    b = bytearray(read(start, end - start))
    if len(b) != end - start or hashlib.sha256(b).hexdigest() != ORIGINAL_SHA256:
        raise ValueError('Unsupported or short original map terrain provider')
    cs = Cs(CS_ARCH_X86, CS_MODE_32)
    for ins in cs.disasm(b, start):
        if (ins.mnemonic == 'call' or ins.mnemonic.startswith('j')) and ins.op_str.startswith('0x'):
            target = int(ins.op_str, 16)
            if not start <= target < end:
                assert ins.bytes[0] == 0xe8 and ins.size == 5
                at = ins.address - start
                struct.pack_into('<i', b, at + 1, target - (TERRAIN + at + 5))
    # This clone only draws full rectangles, but support the initial Y offset
    # too. Original terrain colours/lighting/resource sampling remain intact.
    for a, old, new in (
        (0x2775a3, 'd3fe', '9090'), (0x277603, '8b5f0a', '8b5f40'), (0x277801, '8b470a', '8b4740'),
        (0x277807, 'd3f8', '9090')
    ):
        off = a - start
        assert b[off:off + len(bytes.fromhex(old))] == bytes.fromhex(old)
        b[off:off + len(bytes.fromhex(old))] = bytes.fromhex(new)
    return bytes(b)


def owner_capture(maps):
    return (
        f"    mov eax,[{maps.SLOT+8}];"
        f"sub eax,0x22;"
        f"\n    cmp eax,[0x389dec];"
        f"jb original;"
        f"cmp eax,[0x389de8];"
        f"ja original;"
        f"\n    mov [{maps.SLOT+12}],eax;"
        f"\n    mov edx,[eax+0x1c];"
        f"mov [{maps.SLOT+68}],edx;"
        f"\n    mov edx,[eax+0x18];"
        f"mov [{maps.SLOT+72}],edx;"
        f"\n    movzx edx,byte ptr [eax+0x21];"
        f"mov [{maps.SLOT+76}],edx;"
        f"\n    cmp edx,3;"
        f"jae original;"
        f"shl edx,5;"
        f"movzx edx,byte ptr [edx+0x38fc12];"
        f"mov [{maps.SLOT+80}],edx;"
        f"\n    movzx edx,byte ptr [eax+0x20];"
        f"and edx,0x40;"
        f"mov [{maps.SLOT+88}],edx;"
        f"\n    mov edx,[0x359708];"
        f"mov [{maps.SLOT+96}],edx;"
        f"\n"
    )


def entry_source(maps, layout=None, *, persistent=True):
    """Map cache and enlarged terrain canvas; logical markers keep original coordinates."""
    pixels = PIXELS if layout is None else layout.map
    x_start = 'imul edx,edx,5;inc edx;shr edx,1;' if layout is None else 'shl edx,2;'
    x_end = (
        "imul ebx,ebx,5;"
        "inc ebx;"
        "shr ebx,1;"
        "sub ebx,edx;"
    ) if layout is None else 'shl ebx,2;sub ebx,edx;'
    if layout is None:
        y_start = 'imul eax,eax,3;inc eax;shr eax,1;'
        y_end = ("imul edi,edi,3;"
                 "inc edi;"
                 "shr edi,1;"
                 "sub edi,eax;")
    else:
        y_start = (
            "push eax;"
            "push ecx;"
            "push edx;"
            "mov eax,eax;"
            "imul eax,eax,12;"
            "add eax,4;"
            "xor edx,edx;"
            "mov ecx,5;"
            "div ecx;"
            "mov [esp+8],eax;"
            "pop edx;"
            "pop ecx;"
            "pop eax;"
        )
        y_end = (
            "push eax;"
            "push ecx;"
            "push edx;"
            "mov eax,edi;"
            "imul eax,eax,12;"
            "add eax,4;"
            "xor edx,edx;"
            "mov ecx,5;"
            "div ecx;"
            "mov edi,eax;"
            "pop edx;"
            "pop ecx;"
            "pop eax;"
            "sub edi,eax;"
        )
    identity = owner_capture(maps) if persistent else ''
    return (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"mov dword ptr [{maps.SLOT}],0;"
        f"\n cmp dword ptr [0x446f80],0x01900140;"
        f"jne original;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f"jne original;"
        f"\n mov ebp,[0x44b1a0];"
        f"cmp word ptr [ebp+12],320;"
        f"jne original;"
        f"\n mov esi,eax;"
        f"mov [{maps.CONTROL}],eax;"
        f"mov [{maps.SLOT+8}],ebp;"
        f"\n mov edx,[0x446f78];"
        f"mov [{maps.SLOT+16}],edx;"
        f"mov eax,[ebp];"
        f"sub eax,edx;"
        f"cmp eax,128000;"
        f"jae original;"
        f"\n mov [{maps.SLOT+20}],eax;"
        f"xor edx,edx;"
        f"mov ecx,320;"
        f"div ecx;"
        f"\n mov [{maps.SLOT+24}],edx;"
        f"mov [{maps.SLOT+28}],eax;"
        f"\n movzx ebx,word ptr [ebp+8];"
        f"test ebx,ebx;"
        f"jz original;"
        f"mov [{maps.SLOT+32}],ebx;"
        f"\n add ebx,edx;"
        f"cmp ebx,320;"
        f"ja original;"
        f"\n movzx edi,word ptr [ebp+10];"
        f"test edi,edi;"
        f"jz original;"
        f"mov [{maps.SLOT+36}],edi;"
        f"\n add edi,eax;"
        f"cmp edi,400;"
        f"ja original;"
        f"\n {x_start}mov [{maps.SLOT+40}],edx;"
        f"\n {x_end}mov [{maps.SLOT+48}],ebx;"
        f"\n {y_start}mov [{maps.SLOT+44}],eax;"
        f"\n {y_end}mov [{maps.SLOT+52}],edi;"
        f"\n mov eax,[esi];"
        f"mov [{maps.KEY}],eax;"
        f"mov eax,[esi+4];"
        f"mov [{maps.KEY+4}],eax;"
        f"\n mov eax,[esi+10];"
        f"mov [{maps.KEY+8}],eax;"
        f"mov eax,[{maps.SLOT+32}];"
        f"mov [{maps.KEY+12}],eax;"
        f"\n mov eax,[{maps.SLOT+36}];"
        f"mov [{maps.KEY+16}],eax;"
        f"mov eax,[{maps.SLOT+48}];"
        f"mov [{maps.KEY+20}],eax;"
        f"\n mov eax,[{maps.SLOT+52}];"
        f"mov [{maps.KEY+24}],eax;"
        f"mov eax,[esi+38];"
        f"mov [{maps.KEY+28}],eax;"
        f"\n mov eax,[0x359708];"
        f"mov [{maps.KEY+32}],eax;"
        f"movzx eax,byte ptr [0x35ade0];"
        f"mov [{maps.KEY+36}],eax;"
        f"\n push esi;"
        f"mov esi,{maps.KEY};"
        f"mov edi,{maps.KEY+64};"
        f"mov ecx,10;"
        f"repe cmpsd;"
        f"pop esi;"
        f"je cached;"
        f"\n push esi;"
        f"mov esi,{maps.KEY};"
        f"mov edi,{maps.KEY+64};"
        f"mov ecx,10;"
        f".byte 0xf3,0xa5;"
        f"pop esi;"
        f"\n mov edi,{maps.CTX};"
        f"mov ecx,16;"
        f".byte 0xf3,0xa5;"
        f"\n mov eax,[{maps.CTX+10}];"
        f"imul eax,[{maps.SLOT+32}];"
        f"xor edx,edx;"
        f"div dword ptr [{maps.SLOT+48}];"
        f"mov [{maps.CTX+10}],eax;"
        f"\n mov eax,[{maps.KEY+8}];"
        f"shr eax,1;"
        f"imul eax,[{maps.SLOT+36}];"
        f"xor edx,edx;"
        f"div dword ptr [{maps.SLOT+52}];"
        f"mov [{maps.CTX+64}],eax;"
        f"\n mov dword ptr [{maps.CTX+22}],{pixels};"
        f"mov eax,[{maps.SLOT+48}];"
        f"mov [{maps.CTX+30}],ax;"
        f"mov [{maps.CTX+34}],ax;"
        f"\n mov eax,[{maps.SLOT+52}];"
        f"mov [{maps.CTX+32}],ax;"
        f"\n mov eax,{maps.CTX};"
        f"xor edx,edx;"
        f"call {maps.TERRAIN};"
        f"inc dword ptr [{maps.CONTROL+4}];"
        f"\n cmp byte ptr [0x35ade0],0;"
        f"je cached;"
        f"\n mov esi,{pixels};"
        f"mov ecx,[{maps.SLOT+48}];"
        f"imul ecx,[{maps.SLOT+52}];"
        f"\n infrared:movzx eax,byte ptr [esi];"
        f"mov al,[eax+0x417928];"
        f"mov [esi],al;"
        f"inc esi;"
        f"loop infrared;"
        f"\n cached:\n    {identity}    mov dword ptr [{maps.SLOT}],1;"
        f"mov dword ptr [{maps.SLOT+4}],1;"
        f"mov eax,[0x35f400];"
        f"mov [{maps.SLOT+92}],eax;"
        f"\n mov dword ptr [{maps.SLOT+56}],{pixels};"
        f"mov dword ptr [{maps.SLOT+60}],{maps.REF};"
        f"mov dword ptr [{maps.SLOT+64}],{maps.MASK};"
        f"\n original:popad;"
        f"popfd;"
        f"jmp {maps.ORIGINAL};"
    )


def background_source(maps):
    """Capture the original logical map pixels used by per-cell coverage."""
    return (
        f"call dword ptr [ecx+0x238];"
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"\n cmp dword ptr [{maps.SLOT}],1;"
        f"jne done;"
        f"\n mov eax,[0x44b1a0];"
        f"cmp eax,[{maps.SLOT+8}];"
        f"jne done;"
        f"\n mov esi,[eax];"
        f"mov edi,{maps.REF};"
        f"mov edx,[{maps.SLOT+36}];"
        f"\n row:mov ecx,[{maps.SLOT+32}];"
        f"rep movsb;"
        f"add esi,320;"
        f"sub esi,[{maps.SLOT+32}];"
        f"dec edx;"
        f"jnz row;"
        f"\n done:popad;"
        f"popfd;"
        f"ret;"
    )


def panel_entry_source(layout, maps):
    """Cache each original map context independently in the native arena.

    The game has four 40-byte map contexts, including the enlarged visor map.
    Camera slot numbers are insufficient because two widgets can share one.
    Records contain the compositor slot, a pending key and its last drawn key.
    The shared CTX is only scratch space during this synchronous draw call.
    """
    return f"""
        pushfd; pushad; cld;
        mov dword ptr [{maps.CONTROL+12}],0;
        mov esi,eax;
        sub eax,0x390260;
        cmp eax,160; jae original;
        xor edx,edx; mov ecx,40; div ecx;
        test edx,edx; jnz original;
        mov ebx,eax; shl eax,9; lea ebp,[eax+{layout.map_slots}];
        mov dword ptr [ebp],0;
        test byte ptr [esi+38],2; jz original;
        cmp dword ptr [0x446f80],0x01900140; jne original;
        cmp byte ptr [0x1d0d449],0x6b; jne original;
        mov ecx,[0x44b1a0];
        cmp ecx,[esi+18]; jne original;
        cmp word ptr [ecx+12],320; jne original;
        mov [ebp+8],ecx;
        lea eax,[ecx-0x22];
        cmp eax,[0x389dec]; jb original;
        cmp eax,[0x389de8]; ja original;
        mov [ebp+12],eax;
        mov edx,[eax+0x1c]; mov [ebp+68],edx;
        mov edx,[eax+0x18]; mov [ebp+72],edx;
        movzx edx,byte ptr [eax+0x21];
        cmp edx,3; jae original;
        mov [ebp+76],edx; shl edx,5;
        movzx edx,byte ptr [edx+0x38fc12]; mov [ebp+80],edx;
        movzx edx,byte ptr [eax+0x20]; and edx,0x40; mov [ebp+88],edx;
        mov edx,[0x359708]; mov [ebp+96],edx;
        mov [ebp+108],esi;
        mov eax,ebx; shl eax,21; add eax,{layout.map_pixels[0]}; mov [ebp+56],eax;
        imul eax,ebx,0x50000; add eax,{layout.map_refs[0]}; mov [ebp+60],eax;
        add eax,0x20200; mov [ebp+64],eax;
        mov edx,[0x446f78]; mov [ebp+16],edx;
        mov eax,[ecx]; sub eax,edx;
        cmp eax,128000; jae original;
        mov [ebp+20],eax;
        xor edx,edx; mov ecx,320; div ecx;
        mov [ebp+24],edx; mov [ebp+28],eax;
        mov ecx,[ebp+8];
        movzx ebx,word ptr [ecx+8]; test ebx,ebx; jz original;
        mov [ebp+32],ebx; add ebx,edx; cmp ebx,320; ja original;
        movzx edi,word ptr [ecx+10]; test edi,edi; jz original;
        mov [ebp+36],edi; add edi,eax; cmp edi,400; ja original;
        shl edx,2; mov [ebp+40],edx;
        shl ebx,2; sub ebx,edx; mov [ebp+48],ebx;
        imul eax,eax,12; add eax,4; xor edx,edx; mov ecx,5; div ecx;
        mov [ebp+44],eax;
        imul eax,edi,12; add eax,4; xor edx,edx; div ecx;
        sub eax,[ebp+44]; mov [ebp+52],eax;
        mov eax,[esi]; mov [ebp+128],eax;
        mov eax,[esi+4]; mov [ebp+132],eax;
        mov eax,[esi+10]; mov [ebp+136],eax;
        mov eax,[ebp+32]; mov [ebp+140],eax;
        mov eax,[ebp+36]; mov [ebp+144],eax;
        mov eax,[ebp+48]; mov [ebp+148],eax;
        mov eax,[ebp+52]; mov [ebp+152],eax;
        movzx eax,word ptr [esi+38]; mov [ebp+156],eax;
        mov eax,[0x359708]; mov [ebp+160],eax;
        movzx eax,byte ptr [0x35ade0]; mov [ebp+164],eax;
        mov [ebp+168],esi;
        mov eax,[ebp+12]; mov [ebp+172],eax;
        mov eax,[ebp+68]; mov [ebp+176],eax;
        mov eax,[ebp+72]; mov [ebp+180],eax;
        cmp dword ptr [ebp+104],1; jne redraw;
        push esi; lea esi,[ebp+128]; lea edi,[ebp+192];
        mov ecx,14; repe cmpsd; pop esi; je cached;
    redraw:
        push esi; lea esi,[ebp+128]; lea edi,[ebp+192];
        mov ecx,14; rep movsd; pop esi;
        mov edi,{maps.CTX}; mov ecx,10; rep movsd;
        mov eax,[ebp+136]; imul eax,[ebp+32]; xor edx,edx;
        div dword ptr [ebp+48]; mov [{maps.CTX+10}],eax;
        mov eax,[ebp+136]; shr eax,1; imul eax,[ebp+36]; xor edx,edx;
        div dword ptr [ebp+52]; mov [{maps.CTX+64}],eax;
        mov eax,[ebp+56]; mov [{maps.CTX+22}],eax;
        mov eax,[ebp+48]; mov [{maps.CTX+30}],ax; mov [{maps.CTX+34}],ax;
        mov eax,[ebp+52]; mov [{maps.CTX+32}],ax;
        mov eax,{maps.CTX}; xor edx,edx; call {maps.TERRAIN};
        inc dword ptr [{maps.CONTROL+4}];
        cmp byte ptr [0x35ade0],0; je rendered;
        mov esi,[ebp+56]; mov ecx,[ebp+48]; imul ecx,[ebp+52];
    infrared:
        movzx eax,byte ptr [esi]; mov al,[eax+0x417928]; mov [esi],al;
        inc esi; loop infrared;
    rendered:
        mov dword ptr [ebp+104],1;
    cached:
        mov dword ptr [ebp],1; mov dword ptr [ebp+4],1;
        mov eax,[0x35f400]; mov [ebp+92],eax;
        mov [{maps.CONTROL+12}],ebp;
    original:
        popad; popfd; jmp {maps.ORIGINAL};
    """


def panel_background_source(layout, maps):
    """Save this map's logical terrain before markers are drawn over it."""
    return f"""
        call dword ptr [ecx+0x238]; pushfd; pushad; cld;
        mov ebp,[{maps.CONTROL+12}];
        cmp ebp,{layout.map_slots}; jb done;
        cmp ebp,{layout.map_slots+4*512}; jae done;
        mov eax,ebp; sub eax,{layout.map_slots}; test eax,511; jnz done;
        cmp dword ptr [ebp],1; jne done;
        mov eax,[0x44b1a0]; cmp eax,[ebp+8]; jne done;
        mov esi,[eax]; mov edi,[ebp+60]; mov edx,[ebp+36];
    row:
        mov ecx,[ebp+32]; rep movsb;
        add esi,320; sub esi,[ebp+32]; dec edx; jnz row;
    done:
        popad; popfd; ret;
    """


def logical_merge_source(*, persistent=False):
    if persistent:
        identity = (
            "mov eax,[ebp+12];"
            "cmp eax,[0x389dec];"
            "jb next;"
            "cmp eax,[0x389de8];"
            "ja next;"
            "\n    cmp eax,[0x389e0c];"
            "je next;"
            "\n    mov edx,[eax+0x1c];"
            "cmp edx,[ebp+68];"
            "jne next;"
            "\n    mov edx,[eax+0x18];"
            "cmp edx,[ebp+72];"
            "jne next;"
            "\n    movzx edx,byte ptr [eax+0x21];"
            "cmp edx,[ebp+76];"
            "jne next;"
            "\n    cmp edx,3;"
            "jae next;"
            "shl edx,5;"
            "movzx edx,byte ptr [edx+0x38fc12];"
            "cmp edx,[ebp+80];"
            "jne next;"
            "\n    movzx edx,byte ptr [eax+0x20];"
            "and edx,0x40;"
            "cmp edx,[ebp+88];"
            "jne next;"
            "\n    mov edx,[0x359708];"
            "cmp edx,[ebp+96];"
            "jne next;"
            "\n    "
        )
    else:
        identity = (
            "mov eax,[0x35f400];"
            "cmp eax,[ebp+92];"
            "je current;"
            "cmp byte ptr [0x35f3f4],1;"
            "jne next;"
            "sub eax,[ebp+92];"
            "cmp eax,1;"
            "ja next;"
            "current:\n "
        )
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f" jne done;"
        f"\n cmp dword ptr [0x446f80],0x01900140;"
        f" jne done;"
        f"\n xor ebx,ebx;"
        f" mov ebp,0x1e3c580;"
        f"\n slot: cmp dword ptr [ebp],0;"
        f" je next;"
        f"\n {identity}mov eax,[ebp+8];"
        f"mov edx,[0x446f78];"
        f"cmp edx,[ebp+16];"
        f"jne next;"
        f"\n add edx,[ebp+20];"
        f"cmp edx,[eax];"
        f"jne next;"
        f"\n movzx edx,word ptr [eax+8];"
        f"cmp edx,[ebp+32];"
        f"jne next;"
        f"\n movzx edx,word ptr [eax+10];"
        f"cmp edx,[ebp+36];"
        f"jne next;"
        f"\n  push ebx;"
        f"\n mov esi,dword ptr [ebp+56];"
        f" mov edi,dword ptr [ebp+44];"
        f" imul edi,edi,800;"
        f" add edi,dword ptr [ebp+40];"
        f" add edi,0x8a35e8;"
        f"\n mov eax,dword ptr [ebp+20];"
        f" add eax,0x1e60000;"
        f" mov dword ptr [0x1e46244],eax;"
        f"\n mov eax,dword ptr [ebp+60];"
        f" mov dword ptr [0x1e46248],eax;"
        f"\n mov eax,dword ptr [ebp+64];"
        f" mov dword ptr [0x1e4624c],eax;"
        f"\n xor edx,edx;"
        f"\n row:mov eax,edx;"
        f"add eax,[ebp+28];"
        f"and eax,1;"
        f"neg eax;"
        f"add eax,2;"
        f"mov [0x1e46250],eax;"
        f"xor ebx,ebx;"
        f"\n pixel: mov ecx,ebx;"
        f" add ecx,dword ptr [ebp+24];"
        f" and ecx,1;"
        f" neg ecx;"
        f" add ecx,3;"
        f"\n mov eax,dword ptr [0x1e4624c];"
        f" cmp byte ptr [eax+ebx],0;"
        f" je skip;"
        f"\n mov eax,dword ptr [0x1e46248];"
        f" mov al,byte ptr [eax+ebx];"
        f"\n push ecx;"
        f" mov ecx,dword ptr [0x1e46244];"
        f" cmp byte ptr [ecx+ebx],al;"
        f" pop ecx;"
        f" jne skip;"
        f"\n  copy: push ecx;"
        f" push edx;"
        f" push esi;"
        f" push edi;"
        f"\n mov edx,[0x1e46250];"
        f"\n scan: push ecx;"
        f" rep movsb;"
        f" pop ecx;"
        f" add edi,800;"
        f" sub edi,ecx;"
        f" add esi,dword ptr [ebp+48];"
        f" sub esi,ecx;"
        f" dec edx;"
        f" jnz scan;"
        f"\n pop edi;"
        f" pop esi;"
        f" pop edx;"
        f" pop ecx;"
        f"\n mov eax,dword ptr [0x1e46244];"
        f" mov byte ptr [eax+ebx],0;"
        f"\n skip: add esi,ecx;"
        f" add edi,ecx;"
        f" inc ebx;"
        f" cmp ebx,dword ptr [ebp+32];"
        f" jb pixel;"
        f"\n mov eax,[0x1e46250];"
        f"dec eax;"
        f"imul eax,[ebp+48];"
        f"add esi,eax;"
        f"mov eax,[0x1e46250];"
        f"imul eax,eax,800;"
        f"add edi,eax;"
        f"sub edi,[ebp+48];"
        f"\n add dword ptr [0x1e46244],320;"
        f" mov eax,dword ptr [ebp+32];"
        f" add dword ptr [0x1e46248],eax;"
        f" add dword ptr [0x1e4624c],eax;"
        f"\n inc edx;"
        f" cmp edx,dword ptr [ebp+36];"
        f" jb row;"
        f"\n inc dword ptr [ebp+84];"
        f" pop ebx;"
        f"\n next: inc ebx;"
        f" add ebp,128;"
        f" cmp ebx,1;"
        f" jb slot;"
        f"\n done: popad;"
        f" popfd;"
        f" ret;"
        f"\n "
    )


def overlay_source():
    """Keep range rings round on the tall logical HUD, then restore the driver.

    The software driver can restore its 320 x 200 pixel aspect while our HUD
    still uses 320 x 400. Terrain and marker positions use the map's own scale,
    but circles read the driver aspect. Scope the correction to this existing
    overlay call so other views retain their incoming projection settings.
    """
    return '''
        push dword ptr [0x44b1ac]
        pushfd
        cmp dword ptr [0x446f80], 0x01900140
        jne draw
        mov dword ptr [0x44b1ac], 0x9999
    draw:
        popfd
        call original
        pushfd
        push eax
        mov eax, [esp + 8]
        mov [0x44b1ac], eax
        pop eax
        popfd
        lea esp, [esp + 4]
        ret
    original:
        push ebx
        push ecx
        push esi
        push edi
        push ebp
        jmp 0x276efd
    '''


def view_bodies(*, persistent=False):
    return [
        (ENTRY, code(ENTRY, entry_source(SYMBOLS, persistent=persistent))),
        (
            ORIGINAL,
            code(ORIGINAL, overlay_source())
        ), (BACKGROUND, code(BACKGROUND, background_source(SYMBOLS))),
        (MERGE, code(MERGE, logical_merge_source(persistent=persistent)))
    ]


def bodies(read):
    result = [(TERRAIN, terrain_code(read))] + view_bodies()
    for address, body in result:
        limit = {
            TERRAIN: 0x800,
            ENTRY: 0x700,
            ORIGINAL: 0x100,
            BACKGROUND: 0x200,
            MERGE: 0x600
        }[address]
        if len(body) > limit:
            raise ValueError('Map helper exceeds reservation')
    return result


def hooks():
    return [
        (0x276ef8, asm(0x276ef8, f'jmp {ENTRY}')),
        (0x276fa6, asm(0x276fa6, f'call {BACKGROUND}') + b'\x90')
    ]


MAPCOLOR = 0x1f76800


def palette_bodies():
    body = asm(
        MAPCOLOR, (
            "mov cl,[ecx];"
            "pushfd;"
            "cmp dword ptr [0x359708],23;"
            "jne done;"
            "\n cmp cl,12;"
            "jb done;"
            "cmp cl,16;"
            "ja done;"
            "mov cl,17;"
            "\n done:popfd;"
            "mov [esp+0x48],cl;"
            "ret;"
        )
    )
    return [(MAPCOLOR, body)] + [
        (a, asm(a, f'call {MAPCOLOR}') + b'\x90') for a in (0x277755, 0x1e44295)
    ]


CENTER = 0x1e50000
CENTER_END = 0x1e50400
CENTER_SITE = 0x27631c
CENTER_HOOKS = {CENTER_SITE: asm(CENTER_SITE, 'call 0x26485c;')}


def center_bodies():
    s = (
        "call 0x26485c;"
        "pushfd;"
        "pushad;"
        "\n cmp dword ptr [0x359708],0x2e;"
        "je done;"
        "\n mov esi,[0x38fb20];"
        "test esi,esi;"
        "je done;"
        "\n movzx eax,word ptr [0x441350];"
        "imul eax,eax,37;"
        "\n mov edx,[eax+0x3c324f];"
        "mov ebx,[eax+0x3c3253];"
        "\n mov eax,esi;"
        "call 0x276c4c;"
        "\n movzx eax,word ptr [esi+0x1e];"
        "shr eax,1;"
        "imul eax,[esi+0xa];"
        "add eax,[esi];"
        "mov [0x38fa88],eax;"
        "\n movzx eax,word ptr [esi+0x20];"
        "shr eax,1;"
        "mov cl,[0x35a544];"
        "shr eax,cl;"
        "\n imul eax,[esi+0xa];"
        "add eax,[esi+4];"
        "mov [0x38fa8c],eax;"
        "\n done:popad;"
        "popfd;"
        "ret;"
    )
    b = asm(CENTER, s)
    assert len(b) < CENTER_END - CENTER
    return [(CENTER, b), (CENTER_SITE, asm(CENTER_SITE, f'call {CENTER};'))]


def center_installed(r):
    return bytes(r[CENTER_SITE:CENTER_SITE + 5]) == asm(CENTER_SITE, f'call {CENTER};')


def verify_center(r):
    for a, b in center_bodies():
        assert bytes(r[a:a + len(b)]) == b, (hex(a), 'map114')
    return True


def center_predecessor_view(r):
    verify_center(r)
    out = bytearray(r)
    out[CENTER:CENTER_END] = bytes(CENTER_END - CENTER)
    for a, b in CENTER_HOOKS.items():
        out[a:a + len(b)] = b
    return out


def install_center(write, r):
    if center_installed(r):
        verify_center(r)
        return dict(ranges=[])
    for a, b in CENTER_HOOKS.items():
        assert bytes(r[a:a + len(b)]) == b, hex(a)
    assert not any(r[CENTER:CENTER_END])
    for a, b in center_bodies():
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in center_bodies()])


def frame_source(*, reset_slot=False):
    reset = f'mov dword ptr [{SLOT}],0;' if reset_slot else ''
    return (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"\n cmp dword ptr [0x446f80],0x01900140;"
        f"jne done;"
        f"\n mov edi,{hud.MASK};"
        f"mov eax,-1;"
        f"mov ecx,32000;"
        f"rep stosd;"
        f"\n {reset}done:popad;"
        f"popfd;"
        f"push ebx;"
        f"push ecx;"
        f"push edx;"
        f"mov edx,[0x389dec];"
        f"jmp 0x261be1;"
    )


def persistence_bodies():
    return [(a, b) for a, b in view_bodies(persistent=True) if a in (ENTRY, MERGE)] + [
        (hud.FRAME_BEGIN, code(hud.FRAME_BEGIN, frame_source()))
    ]


def persistence_plan(extras=()):
    """Explicit cold preimages; optional adjacent features supply their own spans."""
    before = dict(view_bodies())
    before[hud.FRAME_BEGIN] = code(hud.FRAME_BEGIN, frame_source(reset_slot=True))
    spans = [(a, before[a], b) for a, b in persistence_bodies()] + list(extras)
    out = []
    for a, old, new in spans:
        size = max(len(old), len(new))
        if not size or not 0x11000 <= a < a + size <= 0x2000000:
            raise ValueError('Invalid map persistence span')
        if any(a < at + len(prior) and at < a + size for at, prior, _ in out):
            raise ValueError('Overlapping map persistence spans')
        out.append((a, old.ljust(size, b'\0'), new.ljust(size, b'\0')))
    return tuple(out)


def install_persistence(write, read, *, extras=()):
    plan = persistence_plan(extras)
    current = tuple(bytes(read(a, len(old))) for a, old, new in plan)
    if all(now == new for now, (_, old, new) in zip(current, plan)):
        return dict(already_installed=True, ranges=[])
    if any(now != old for now, (_, old, new) in zip(current, plan)):
        raise ValueError('Map persistence provider differs')
    for a, old, new in plan:
        write(a, new)
    write(SLOT, bytes(4))
    return dict(ranges=[(a, a + len(new)) for a, old, new in plan] + [(SLOT, SLOT + 4)])
