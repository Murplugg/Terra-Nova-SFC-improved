"""Draw the logical HUD and share its storage with the native renderer.

Map code and hook addresses are supplied by the map feature. The arena renderer
replaces selected entry points when it installs enlarged views. The logical
helpers keep their fixed locations so existing snapshots remain compatible.
"""
import struct
from patch_support import asm
from features import target_picking as pick
from features.render_views import assemble as code


def _logical_install(payload, edits, write, read):
    from features.input_views import _install
    return _install(
        payload + [(a, b) for a, b, old in edits], {
            a: old
            for a, b, old in edits
        }, write, read
    )


def damage_install(write, read):
    return _logical_install(damage_bodies(asm), damage_hooks(asm), write, read)


def nav_install(write, read):
    return _logical_install(nav_bodies(asm), nav_hooks(asm), write, read)


def menu_install(write, read):
    return _logical_install(menu_bodies(asm), menu_hooks(asm), write, read)


def _logical_verify(payload, edits, read):
    from features.input_views import _verify
    return _verify(payload + [(a, b) for a, b, old in edits], read)


def damage_verify(read):
    return _logical_verify(damage_bodies(asm), damage_hooks(asm), read)


def nav_verify(read):
    return _logical_verify(nav_bodies(asm), nav_hooks(asm), read)


def menu_verify(read):
    return _logical_verify(menu_bodies(asm), menu_hooks(asm), read)


WORLD = 0x1e30000
TARGET = 0x1e31000
CONVERT = 0x1e31800
RESET = 0x1e32000
TEXT = 0x1e32200
COVER = 0x1e33000
COMPOSE = 0x1e34000
PAINT = 0x1e35000
MOVEMENT = 0x1e35a00
CALLBACK = 0x1e35c00
CURSOR_COMPOSE = 0x1e36000
CACHE = 0x1e60000
MASK = 0x1e80000
TEMP = 0x1ea0000
ROOT_PIXELS = 0x1ec0000
ROWS = 0x1e51000
CAMERA = 0x1e38000
MERGE = 0x1e3a000
PREPARE = 0x1e3b000
INVALIDATE = 0x1e3b400
STATE = 0x1e3c000
SAVE = 0x1e3c100
SLOTS = 0x1e3c400
REFS = tuple(0x1ee0100 + i * 0x3400 for i in range(3))
MASKS = tuple(0x1ee9d00 + i * 0x3400 for i in range(3))
BASES = (0x9e0100, 0x9ec100, 0x9f8100)
BOXES = ((0x2454bc, 0x1e37000, 0xa11a00), (0x245600, 0x1e37400, 0xa11a20))
QUICK = 0x1e37800
POINT = 0x1e46a00
SPRITE = 0x1e46c00
DATA = 0x9b90e8
CANVAS = 0x9c34e8
PIXELS = 0x918ae8
FRAME = 0x8a35e8
READY = 0x9aa0ec
LOW = 0x9a3d08
HIGH = 0x9a3ce8
CTX = 0x38fb24
TRACK = 0x9aa1e8
CAPACITY = 0x75300
MODE = 0x1e40000
MODE_ORIG = 0x1e40400
MISSION = 0x1e40600
GATES = 0x1e41000
PICK = 0x1e43000
FRAME_BEGIN = 0x1e40800


def world_source():
    """Render into the physical visor, preserving original projection and heap ownership."""
    return (
        f"\n cmp edx,{CTX};"
        f" jne other;"
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov dword ptr [{READY}],0;"
        f"\n mov esi,dword ptr [0x38fb40];"
        f"\n cmp word ptr [esi+12],320;"
        f" jne fail;"
        f"\n cmp word ptr [esi+8],0;"
        f"je fail;"
        f"cmp word ptr [esi+10],0;"
        f"je fail;"
        f" dimensions:\n mov eax,dword ptr [esi];"
        f" sub eax,dword ptr [0x446f78];"
        f"\n cmp eax,0x1f400;"
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
        f" cmp ebp,400;"
        f" ja fail;"
        f"\n imul eax,eax,3;"
        f"inc eax;"
        f"shr eax,1;"
        f" mov dword ptr [0x9b90ec],eax;"
        f"\n imul ebp,ebp,3;"
        f"inc ebp;"
        f"shr ebp,1;"
        f" mov dword ptr [0x9b90f4],ebp;"
        f" sub ebp,eax;"
        f" mov dword ptr [0x9b90fc],ebp;"
        f"\n imul edx,edx,5;"
        f" inc edx;"
        f" shr edx,1;"
        f" mov dword ptr [{DATA}],edx;"
        f"\n imul ebx,ebx,5;"
        f" inc ebx;"
        f" shr ebx,1;"
        f" mov dword ptr [0x9b90f0],ebx;"
        f"\n sub ebx,edx;"
        f" mov dword ptr [0x9b90f8],ebx;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
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
        f" mov ecx,0x35a84;"
        f" rep movsb;"
        f"\n mov ecx,0x4a57c;"
        f" xor eax,eax;"
        f" rep stosb;"
        f"\n mov dword ptr [{TRACK}],0;"
        f" inc dword ptr [0x9b9104];"
        f"\n allocated:\n mov eax,dword ptr [0x41ec80];"
        f" cmp eax,dword ptr [{TRACK}];"
        f" je guarded;"
        f"\n mov dword ptr [{TRACK}],eax;"
        f" lea edi,[eax+{CAPACITY}];"
        f" mov al,0xa5;"
        f" mov ecx,256;"
        f" rep stosb;"
        f"\n guarded:\n mov esi,dword ptr [0x38fb40];"
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
        f"\n mov esi,dword ptr [0x38fb40];"
        f" mov edi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov dword ptr [{CANVAS}],{PIXELS};"
        f"\n mov eax,dword ptr [0x9b90f8];"
        f" mov word ptr [0x9c34f0],ax;"
        f" mov word ptr [0x9c34f4],ax;"
        f"\n mov edx,eax;"
        f" shl edx,16;"
        f" mov dword ptr [0x9c351c],edx;"
        f"\n shr eax,1;"
        f" mov dword ptr [0x38fb34],eax;"
        f" imul eax,dword ptr [{CTX}];"
        f" mov dword ptr [0x38fb2c],eax;"
        f"\n mov eax,dword ptr [0x9b90fc];"
        f" mov word ptr [0x9c34f2],ax;"
        f"\n mov edx,eax;"
        f" shl edx,16;"
        f" mov dword ptr [0x9c3520],edx;"
        f"\n shr eax,1;"
        f" mov dword ptr [0x38fb38],eax;"
        f" imul eax,dword ptr [0x38fb28];"
        f" mov dword ptr [0x38fb30],eax;"
        f"\n mov dword ptr [0x38fb40],{CANVAS};"
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
        f"\n mov eax,dword ptr [0x9a3d24];"
        f" call 0x2eab30;"
        f"\n mov dword ptr [{READY}],1;"
        f" inc dword ptr [0x9b9100];"
        f"\n popad;"
        f" popfd;"
        f" ret;"
        f"\n fail: inc dword ptr [0x9b9108];"
        f" popad;"
        f" popfd;"
        f" ret;"
        f"\n other: jmp 0x9a36e8;"
        f"\n "
    )


def target_source():
    """Convert target rectangles while restoring the logical HUD projection."""
    return (
        f"\n pushfd;"
        f" cmp edx,{CTX};"
        f" jne other;"
        f" popfd;"
        f"\n push dword ptr [0x44b1ac];"
        f" mov dword ptr [0x44b1ac],0x10000;"
        f"\n call {RESET};"
        f"\n pushfd;"
        f" pushad;"
        f"\n mov eax,dword ptr [esp+36];"
        f" mov dword ptr [0x44b1ac],eax;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f" jne done;"
        f"\n cmp word ptr [0x446f80],320;"
        f" jne done;"
        f"\n cmp word ptr [0x446f82],400;"
        f" jne done;"
        f"\n mov dword ptr [0x3622ce],eax;"
        f"\n mov esi,dword ptr [0x38fb40];"
        f"\n movzx eax,word ptr [esi+8];"
        f" mov dword ptr [0x3622d2],eax;"
        f"\n mov edx,eax;"
        f" shr edx,1;"
        f" mov dword ptr [0x3622da],edx;"
        f"\n shl eax,15;"
        f" mov dword ptr [0x3622e2],eax;"
        f" mov dword ptr [0x3622ea],eax;"
        f"\n movzx eax,word ptr [esi+10];"
        f" mov dword ptr [0x3622d6],eax;"
        f"\n mov edx,eax;"
        f" shr edx,1;"
        f" mov dword ptr [0x3622de],edx;"
        f"\n shl eax,15;"
        f" mov dword ptr [0x3622e6],eax;"
        f" mov dword ptr [0x3622ee],eax;"
        f"\n mov edi,dword ptr [0x35bf80];"
        f" cmp edi,64;"
        f" ja done;"
        f"\n mov esi,0x397ca0;"
        f" test edi,edi;"
        f" jz done;"
        f"\n next_rect: call {CONVERT};"
        f" add esi,10;"
        f" dec edi;"
        f" jnz next_rect;"
        f"\n inc dword ptr [0x9b38e8];"
        f"\n done: popad;"
        f" popfd;"
        f" lea esp,[esp+4];"
        f" ret;"
        f"\n other: popfd;"
        f" jmp {RESET};"
        f"\n "
    )


def reset_source():
    """Clear per-frame coverage and rebuild the world view before text drawing."""
    return (
        f"\n        pushfd;"
        f" pushad;"
        f" cld;"
        f"\n        cmp edx,{CTX};"
        f" jne done;"
        f"\n        mov edi,{MASK};"
        f" mov eax,0xffffffff;"
        f" mov ecx,32000;"
        f"\n        rep stosd dword ptr es:[edi],eax;"
        f"\n        inc dword ptr [0x9b10e8];"
        f"\n    done: popad;"
        f" popfd;"
        f" jmp {WORLD};"
        f"\n    "
    )


def text_source():
    """Keep text coverage opaque, including black glyph/background pixels."""
    return (
        f"\n        pushfd;"
        f" pushad;"
        f"\n        push dword ptr [esp+40];"
        f" call 0x9b06e8;"
        f"\n        pushfd;"
        f" pushad;"
        f" mov ebp,esp;"
        f"\n        cmp byte ptr [0x1d0d449],0x6b;"
        f" jne done;"
        f"\n        cmp word ptr [0x446f80],320;"
        f" jne done;"
        f"\n        cmp word ptr [0x446f82],400;"
        f" jne done;"
        f"\n        mov esi,dword ptr [0x44b1a0];"
        f"\n        cmp word ptr [esi+12],320;"
        f" jne done;"
        f"\n        mov edi,dword ptr [esi];"
        f" mov eax,edi;"
        f" sub eax,dword ptr [0x446f78];"
        f"\n        cmp eax,0x1f400;"
        f" jae done;"
        f"\n        movzx edx,word ptr [esi+10];"
        f" test edx,edx;"
        f" jz done;"
        f"\n        dec edx;"
        f" imul edx,edx,320;"
        f"\n        movzx ecx,word ptr [esi+8];"
        f" test ecx,ecx;"
        f" jz done;"
        f"\n        add edx,ecx;"
        f" add edx,eax;"
        f" cmp edx,0x1f400;"
        f" ja done;"
        f"\n        push dword ptr [0x9aa0e8];"
        f" push dword ptr [esi+16];"
        f"\n        mov dword ptr [0x9aa0e8],1;"
        f" inc byte ptr [0x447115];"
        f"\n        add eax,{MASK};"
        f" mov dword ptr [esi],eax;"
        f"\n        mov eax,dword ptr [ebp+64];"
        f" mov edx,dword ptr [ebp+56];"
        f"\n        mov ebx,dword ptr [ebp+52];"
        f" mov ecx,dword ptr [ebp+60];"
        f"\n        push 0;"
        f" call 0x9b06e8;"
        f"\n        mov dword ptr [esi],edi;"
        f"\n        pop dword ptr [esi+16];"
        f" pop dword ptr [0x9aa0e8];"
        f"\n        dec byte ptr [0x447115];"
        f" inc dword ptr [0x9b10ec];"
        f"\n    done:\n        popad;"
        f" popfd;"
        f" lea esp,[esp+36];"
        f" ret 4;"
        f"\n    "
    )


def compose_source():
    """Compose the logical HUD over the world using alternating 2/1 physical rows."""
    return (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"cmp dword ptr [0x9aa0e8],0;"
        f"jne done;"
        f"\n mov dword ptr [0x9aa0e8],1;"
        f"inc byte ptr [0x447115];"
        f"\n mov esi,[0x446f78];"
        f"mov edi,{CACHE};"
        f"mov ecx,32000;"
        f".byte 0xf3,0xa5;"
        f"call {PREPARE};"
        f"call {COVER};"
        f"\n cmp dword ptr [{READY}],0;"
        f"je hud;"
        f"\n mov esi,{PIXELS};"
        f"mov edi,[0x9b90ec];"
        f"imul edi,edi,800;"
        f"add edi,[{DATA}];"
        f"add edi,{FRAME};"
        f"\n mov ebp,[0x9b90fc];"
        f"mov ebx,[0x9b90f8];"
        f"mov edx,800;"
        f"sub edx,ebx;"
        f"\n worldrow:mov ecx,ebx;"
        f"shr ecx,2;"
        f".byte 0xf3,0xa5;"
        f"mov ecx,ebx;"
        f"and ecx,3;"
        f"rep movsb;"
        f"add edi,edx;"
        f"dec ebp;"
        f"jnz worldrow;"
        f"\n hud:mov esi,{CACHE};"
        f"mov edi,{FRAME};"
        f"xor ebp,ebp;"
        f"sub esp,8;"
        f"mov dword ptr [esp],0;"
        f"\n row:mov eax,[esp];"
        f"and eax,1;"
        f"neg eax;"
        f"add eax,2;"
        f"mov [esp+4],eax;"
        f"xor ebx,ebx;"
        f"xor edx,edx;"
        f"\n pixel:mov ecx,edx;"
        f"and ecx,1;"
        f"neg ecx;"
        f"add ecx,3;"
        f"\n mov al,[esi];"
        f"test al,al;"
        f"jnz opaque;"
        f"cmp dword ptr [{READY}],0;"
        f"je opaque;"
        f"\n cmp ebp,[0x9b90ec];"
        f"jb opaque;"
        f"cmp ebp,[0x9b90f4];"
        f"jae opaque;"
        f"\n cmp ebx,[{DATA}];"
        f"jb opaque;"
        f"cmp ebx,[0x9b90f0];"
        f"jae opaque;"
        f"\n cmp byte ptr [esi+0x20000],0;"
        f"jne next;"
        f"\n opaque:mov ah,al;"
        f"mov [edi],ax;"
        f"cmp ecx,3;"
        f"jne shortcell;"
        f"mov [edi+2],al;"
        f"\n shortcell:cmp dword ptr [esp+4],2;"
        f"jne next;"
        f"mov [edi+800],ax;"
        f"cmp ecx,3;"
        f"jne next;"
        f"mov [edi+802],al;"
        f"\n next:inc esi;"
        f"add edi,ecx;"
        f"add ebx,ecx;"
        f"inc edx;"
        f"cmp edx,320;"
        f"jb pixel;"
        f"\n mov eax,[esp+4];"
        f"add ebp,eax;"
        f"dec eax;"
        f"imul eax,eax,800;"
        f"add edi,eax;"
        f"inc dword ptr [esp];"
        f"cmp dword ptr [esp],400;"
        f"jb row;"
        f"\n add esp,8;"
        f"call {MERGE};"
        f"call 0x1e45a00;"
        f"mov esi,{FRAME};"
        f"mov edi,0xe0000000;"
        f"mov ecx,0x1d4c0;"
        f".byte 0xf3,0xa5;"
        f"\n dec byte ptr [0x447115];"
        f"mov dword ptr [0x9aa0e8],0;"
        f"\n done:popad;"
        f"popfd;"
        f"ret;"
    )


def paint_source():
    """Restore cursor pixels from the last completed frame without rendering a new frame."""
    return (
        f"\n        pushfd;"
        f" pushad;"
        f" cld;"
        f"\n        cmp dword ptr [0x9af4e8],0;"
        f" je done;"
        f"\n        cmp dword ptr [0x9aa0e8],0;"
        f" jne blocked;"
        f"\n        mov dword ptr [0x9aa0e8],1;"
        f" inc byte ptr [0x447115];"
        f"\n        inc dword ptr [0x9af4f4];"
        f"\n\n        cmp dword ptr [0x9af5e8],0;"
        f" je cursor_bounds;"
        f"\n        mov eax,dword ptr [0x9af5f4];"
        f" imul eax,eax,800;"
        f"\n        add eax,dword ptr [0x9af5ec];"
        f"\n        lea esi,[eax+{FRAME}];"
        f" lea edi,[eax+0xe0000000];"
        f"\n        mov edx,dword ptr [0x9af5f0];"
        f" sub edx,dword ptr [0x9af5ec];"
        f"\n        mov ebx,dword ptr [0x9af5f8];"
        f" sub ebx,dword ptr [0x9af5f4];"
        f"\n        mov eax,edx;"
        f" imul eax,ebx;"
        f" add dword ptr [0x9af4f8],eax;"
        f"\n        mov ebp,800;"
        f" sub ebp,edx;"
        f"\n    restore_row:\n        mov ecx,edx;"
        f" rep movsb byte ptr es:[edi],byte ptr [esi];"
        f"\n        add esi,ebp;"
        f" add edi,ebp;"
        f" dec ebx;"
        f" jnz restore_row;"
        f"\n\n    cursor_bounds:\n        mov dword ptr [0x9af5e8],0;"
        f"\n        cmp byte ptr [0x447118],0;"
        f" je finish;"
        f"\n        movsx eax,word ptr [0x4470a4];"
        f" movsx edx,word ptr [0x4470b8];"
        f" sub eax,edx;"
        f"\n        movzx edx,word ptr [0x4470b0];"
        f" add edx,eax;"
        f"\n        test eax,eax;"
        f" jns left_ok;"
        f" xor eax,eax;"
        f"\n    left_ok:\n        cmp edx,320;"
        f" jle right_ok;"
        f" mov edx,320;"
        f"\n    right_ok:\n        cmp eax,edx;"
        f" jge finish;"
        f"\n        lea eax,[eax+eax*4+1];"
        f" sar eax,1;"
        f" mov dword ptr [0x9af608],eax;"
        f"\n        lea edx,[edx+edx*4+1];"
        f" sar edx,1;"
        f" mov dword ptr [0x9af60c],edx;"
        f"\n        movsx eax,word ptr [0x4470a6];"
        f" movsx edx,word ptr [0x4470ba];"
        f" sub eax,edx;"
        f"\n        movzx edx,word ptr [0x4470b2];"
        f" add edx,eax;"
        f"\n        test eax,eax;"
        f" jns top_ok;"
        f" xor eax,eax;"
        f"\n    top_ok:\n        cmp edx,400;"
        f" jle bottom_ok;"
        f" mov edx,400;"
        f"\n    bottom_ok:\n        cmp eax,edx;"
        f" jge finish;"
        f"\n        lea eax,[eax+eax*2+1];"
        f"sar eax,1;"
        f" mov dword ptr [0x9af610],eax;"
        f"\n        lea edx,[edx+edx*2+1];"
        f"sar edx,1;"
        f" mov dword ptr [0x9af614],edx;"
        f"\n\n        push dword ptr [0x446f78];"
        f" push dword ptr [0x446fd0];"
        f"\n        mov eax,dword ptr [0x446fd0];"
        f" sub eax,dword ptr [0x446f78];"
        f" add eax,{CACHE};"
        f"\n        mov dword ptr [0x446fd0],eax;"
        f" mov dword ptr [0x446f78],{CACHE};"
        f"\n        mov eax,0x4470a8;"
        f" mov edx,dword ptr [0x4470a4];"
        f"\n        mov ebx,0x446f78;"
        f" mov ecx,0x4470d4;"
        f" call 0x2f25e0;"
        f"\n\n        mov ebp,dword ptr [0x9af610];"
        f"\n    paint_row:\n        mov esi,dword ptr [{ROWS}+ebp*4];"
        f" add esi,{CACHE};"
        f"\n        imul ebx,ebp,800;"
        f"\n        lea edi,[ebx+0xe0000000];"
        f" add edi,dword ptr [0x9af608];"
        f"\n        add ebx,{FRAME};"
        f" mov ecx,dword ptr [0x9af608];"
        f"\n    paint_pixel:\n        movzx edx,word ptr [0x9a54e8+ecx*2];"
        f" mov al,byte ptr [esi+edx];"
        f"\n        test al,al;"
        f" jnz store_pixel;"
        f" mov al,byte ptr [ebx+ecx];"
        f"\n    store_pixel:\n        stosb;"
        f" inc ecx;"
        f" cmp ecx,dword ptr [0x9af60c];"
        f" jb paint_pixel;"
        f"\n        inc ebp;"
        f" cmp ebp,dword ptr [0x9af614];"
        f" jb paint_row;"
        f"\n\n        mov eax,0x4470d4;"
        f" call 0x2f26e8;"
        f"\n        pop dword ptr [0x446fd0];"
        f" pop dword ptr [0x446f78];"
        f"\n        mov eax,dword ptr [0x9af60c];"
        f" sub eax,dword ptr [0x9af608];"
        f"\n        mov edx,dword ptr [0x9af614];"
        f" sub edx,dword ptr [0x9af610];"
        f"\n        imul eax,edx;"
        f" add dword ptr [0x9af4f8],eax;"
        f"\n        mov esi,0x9af608;"
        f" mov edi,0x9af5ec;"
        f" mov ecx,4;"
        f"\n        rep movsd dword ptr es:[edi],dword ptr [esi];"
        f"\n        mov dword ptr [0x9af5e8],1;"
        f"\n    finish:\n        dec byte ptr [0x447115];"
        f" mov dword ptr [0x9aa0e8],0;"
        f" jmp done;"
        f"\n    blocked: inc dword ptr [0x9af4fc];"
        f"\n    done: popad;"
        f" popfd;"
        f" ret;"
        f"\n    "
    )


def movement_source():
    return (
        f"\n        cmp byte ptr [0x1d0d449],0x6b;"
        f" jne regular;"
        f"\n        cmp word ptr [0x446f80],320;"
        f" jne regular;"
        f"\n        cmp word ptr [0x446f82],400;"
        f" jne regular;"
        f"\n        pushfd;"
        f" pushad;"
        f"\n        mov eax,dword ptr [0x4470c0];"
        f" mov dword ptr [0x4470a4],eax;"
        f"\n        inc dword ptr [0x9af4f0];"
        f" call {PAINT};"
        f"\n        popad;"
        f" popfd;"
        f" jmp 0x2f25d3;"
        f"\n    regular: xor eax,eax;"
        f" call 0x2f26e8;"
        f" jmp 0x2f25b5;"
        f"\n    "
    )


def callback_source():
    return (
        f"\n        cmp byte ptr [0x1d0d449],0x6b;"
        f" jne regular;"
        f"\n        cmp word ptr [0x446f80],320;"
        f" jne regular;"
        f"\n        cmp word ptr [0x446f82],400;"
        f" jne regular;"
        f"\n        pushfd;"
        f" pushad;"
        f" cmp bl,1;"
        f" jne done;"
        f"\n        inc dword ptr [0x9af500];"
        f" call {PAINT};"
        f"\n    done: popad;"
        f" popfd;"
        f" ret;"
        f"\n    regular: jmp 0x9ac0e8;"
        f"\n    "
    )


def cursor_compose_source():
    return (
        f"pushfd;"
        f"pushad;"
        f"xor eax,eax;"
        f"call {COMPOSE};"
        f"mov dword ptr [0x9af4e8],1;"
        f"call {PAINT};"
        f"popad;"
        f"popfd;"
        f"ret;"
    )


def camera_source():
    from features.cameras import high_source
    return high_source()


def prepare_source():
    """Invalidate camera slots whose current widget no longer owns the view."""
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f" mov ebp,{SLOTS};"
        f"\n slot: cmp dword ptr [ebp],0;"
        f" je next;"
        f" cmp dword ptr [ebp+4],0;"
        f" je next;"
        f"\n mov esi,dword ptr [ebp+20];"
        f" add esi,{MASK};"
        f" mov edi,dword ptr [ebp+64];"
        f"\n mov edx,dword ptr [ebp+36];"
        f"\n row: mov ecx,dword ptr [ebp+32];"
        f" rep movsb;"
        f" add esi,320;"
        f" sub esi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz row;"
        f"\n mov dword ptr [ebp+4],0;"
        f"\n next: add ebp,128;"
        f" cmp ebp,0x1e3c600;"
        f" jb slot;"
        f"\n popad;"
        f" popfd;"
        f" ret;"
        f"\n "
    )


def merge_source():
    """Merge camera cells only when owner, viewport and frame identity still match."""
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f" jne done;"
        f"\n cmp dword ptr [0x446f80],0x1900140;"
        f" jne done;"
        f"\n xor ebx,ebx;"
        f" mov ebp,{SLOTS};"
        f"\n slot: cmp dword ptr [ebp],0;"
        f" je next;"
        f"\n mov eax,dword ptr [ebx*4+0x389df8];"
        f" cmp eax,dword ptr [ebp+12];"
        f" jne next;"
        f"\n cmp eax,dword ptr [0x389dec];"
        f" jb next;"
        f" cmp eax,dword ptr [0x389de8];"
        f" ja next;"
        f"\n mov edx,ebx;"
        f" shl edx,5;"
        f" movzx edx,byte ptr [edx+0x38fc12];"
        f" cmp edx,dword ptr [ebp+80];"
        f" jne next;"
        f"\n mov edx,dword ptr [eax+0x1c];"
        f" cmp edx,dword ptr [ebp+68];"
        f" jne next;"
        f"\n movzx edx,byte ptr [eax+0x20];"
        f" and edx,0x40;"
        f" cmp edx,dword ptr [ebp+88];"
        f" jne next;"
        f"\n mov edx,dword ptr [0x446f78];"
        f" cmp edx,dword ptr [ebp+16];"
        f" jne next;"
        f"\n add edx,dword ptr [ebp+20];"
        f" cmp edx,dword ptr [eax+0x22];"
        f" jne next;"
        f"\n movzx edx,word ptr [eax+0x2a];"
        f" cmp edx,dword ptr [ebp+32];"
        f" jne next;"
        f"\n movzx edx,word ptr [eax+0x2c];"
        f" cmp edx,dword ptr [ebp+36];"
        f" jne next;"
        f"\n push ebx;"
        f"\n mov esi,dword ptr [ebp+56];"
        f" mov edi,dword ptr [ebp+44];"
        f" imul edi,edi,800;"
        f" add edi,dword ptr [ebp+40];"
        f" add edi,{FRAME};"
        f"\n mov eax,dword ptr [ebp+20];"
        f" add eax,{CACHE};"
        f" mov dword ptr [0x1e3c004],eax;"
        f"\n mov eax,dword ptr [ebp+60];"
        f" mov dword ptr [0x1e3c008],eax;"
        f"\n mov eax,dword ptr [ebp+64];"
        f" mov dword ptr [0x1e3c00c],eax;"
        f"\n xor edx,edx;"
        f"\n row:mov eax,edx;"
        f"add eax,[ebp+28];"
        f"and eax,1;"
        f"neg eax;"
        f"add eax,2;"
        f"mov [0x1e3c010],eax;"
        f"xor ebx,ebx;"
        f"\n pixel: mov ecx,ebx;"
        f" add ecx,dword ptr [ebp+24];"
        f" and ecx,1;"
        f" neg ecx;"
        f" add ecx,3;"
        f"\n mov eax,dword ptr [0x1e3c00c];"
        f" cmp byte ptr [eax+ebx],0;"
        f" je skip;"
        f"\n mov eax,dword ptr [0x1e3c008];"
        f" mov al,byte ptr [eax+ebx];"
        f"\n push ecx;"
        f" mov ecx,dword ptr [0x1e3c004];"
        f" cmp byte ptr [ecx+ebx],al;"
        f" pop ecx;"
        f" jne skip;"
        f"\n  copy: push ecx;"
        f" push edx;"
        f" push esi;"
        f" push edi;"
        f"\n mov edx,[0x1e3c010];"
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
        f"\n mov eax,dword ptr [0x1e3c004];"
        f" mov byte ptr [eax+ebx],0;"
        f"\n skip: add esi,ecx;"
        f" add edi,ecx;"
        f" inc ebx;"
        f" cmp ebx,dword ptr [ebp+32];"
        f" jb pixel;"
        f"\n mov eax,[0x1e3c010];"
        f"dec eax;"
        f"imul eax,[ebp+48];"
        f"add esi,eax;"
        f"mov eax,[0x1e3c010];"
        f"imul eax,eax,800;"
        f"add edi,eax;"
        f"sub edi,[ebp+48];"
        f"\n add dword ptr [0x1e3c004],320;"
        f" mov eax,dword ptr [ebp+32];"
        f" add dword ptr [0x1e3c008],eax;"
        f" add dword ptr [0x1e3c00c],eax;"
        f"\n inc edx;"
        f" cmp edx,dword ptr [ebp+36];"
        f" jb row;"
        f"\n inc dword ptr [ebp+84];"
        f" pop ebx;"
        f"\n next: inc ebx;"
        f" add ebp,128;"
        f" cmp ebx,3;"
        f" jb slot;"
        f"\n done: popad;"
        f" popfd;"
        f" ret;"
        f"\n "
    )


def invalidate_source():
    return (
        f"\n pushfd;"
        f" push eax;"
        f" cmp eax,3;"
        f" jae done;"
        f"\n shl eax,7;"
        f" mov dword ptr [eax+{SLOTS}],0;"
        f"\n done: pop eax;"
        f" popfd;"
        f" push ebx;"
        f" push ecx;"
        f" push edx;"
        f" push esi;"
        f" push edi;"
        f" jmp 0x274da9;"
        f"\n "
    )


def message_box_source():
    return (
        f"\n   pushfd;"
        f" pushad;"
        f" call 0xa11a00;"
        f"\n   pushfd;"
        f" pushad;"
        f" mov ebp,esp;"
        f" cld;"
        f"\n   cmp byte ptr [0x1d0d449],0x6b;"
        f" jne done;"
        f"\n   cmp dword ptr [0x446f80],0x1900140;"
        f" jne done;"
        f"\n   mov esi,dword ptr [0x44b1a0];"
        f"\n   cmp word ptr [esi+12],320;"
        f" jne done;"
        f"\n   mov edi,dword ptr [esi];"
        f" mov eax,edi;"
        f" sub eax,dword ptr [0x446f78];"
        f"\n   cmp eax,0x1f400;"
        f" jae done;"
        f"\n   movzx edx,word ptr [esi+10];"
        f" test edx,edx;"
        f" jz done;"
        f"\n   dec edx;"
        f" imul edx,edx,320;"
        f"\n   movzx ecx,word ptr [esi+8];"
        f" test ecx,ecx;"
        f" jz done;"
        f"\n   add edx,ecx;"
        f" add edx,eax;"
        f" cmp edx,0x1f400;"
        f" ja done;"
        f"\n   push edi;"
        f" push dword ptr [esi+16];"
        f" push dword ptr [0x9aa0e8];"
        f"\n   mov dword ptr [0x9aa0e8],1;"
        f" inc byte ptr [0x447115];"
        f"\n   add eax,{TEMP};"
        f" mov dword ptr [esi],eax;"
        f"\n   mov edi,{TEMP};"
        f" mov eax,0xffffffff;"
        f" mov ecx,32000;"
        f" rep stosd;"
        f"\n   mov eax,dword ptr [ebp+64];"
        f" xor ebx,ebx;"
        f" xor ecx,ecx;"
        f" xor edx,edx;"
        f"\n   call 0xa11a00;"
        f"\n   pop dword ptr [0x9aa0e8];"
        f" pop dword ptr [esi+16];"
        f" pop dword ptr [esi];"
        f"\n   dec byte ptr [0x447115];"
        f"\n   mov esi,{TEMP};"
        f" mov edi,{MASK};"
        f" mov ecx,32000;"
        f"\n   mask: lodsd;"
        f" and dword ptr [edi],eax;"
        f" add edi,4;"
        f" loop mask;"
        f"\n   mov ebp,{SLOTS};"
        f"\n   slot: cmp dword ptr [ebp],0;"
        f" je next;"
        f"\n   mov eax,dword ptr [0x446f78];"
        f" cmp eax,dword ptr [ebp+16];"
        f" jne next;"
        f"\n   mov esi,dword ptr [ebp+20];"
        f" add esi,{TEMP};"
        f" mov edi,dword ptr [ebp+64];"
        f"\n   mov edx,dword ptr [ebp+36];"
        f"\n   row: mov ecx,dword ptr [ebp+32];"
        f"\n   cell: lodsb;"
        f" and byte ptr [edi],al;"
        f" inc edi;"
        f" loop cell;"
        f"\n   add esi,320;"
        f" sub esi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz row;"
        f"\n   next: add ebp,128;"
        f" cmp ebp,0x1e3c600;"
        f" jb slot;"
        f"\n   inc dword ptr [0xa11c00];"
        f"\n   done: popad;"
        f" popfd;"
        f"\n   push eax;"
        f" lea eax,[esp+12];"
        f" add eax,0x10;"
        f" pop eax;"
        f"\n   lea esp,[esp+36];"
        f" ret;"
        f"\n  "
    )


def confirmation_box_source():
    return (
        f"\n   pushfd;"
        f" pushad;"
        f" call 0xa11a20;"
        f"\n   pushfd;"
        f" pushad;"
        f" mov ebp,esp;"
        f" cld;"
        f"\n   cmp byte ptr [0x1d0d449],0x6b;"
        f" jne done;"
        f"\n   cmp dword ptr [0x446f80],0x1900140;"
        f" jne done;"
        f"\n   mov esi,dword ptr [0x44b1a0];"
        f"\n   cmp word ptr [esi+12],320;"
        f" jne done;"
        f"\n   mov edi,dword ptr [esi];"
        f" mov eax,edi;"
        f" sub eax,dword ptr [0x446f78];"
        f"\n   cmp eax,0x1f400;"
        f" jae done;"
        f"\n   movzx edx,word ptr [esi+10];"
        f" test edx,edx;"
        f" jz done;"
        f"\n   dec edx;"
        f" imul edx,edx,320;"
        f"\n   movzx ecx,word ptr [esi+8];"
        f" test ecx,ecx;"
        f" jz done;"
        f"\n   add edx,ecx;"
        f" add edx,eax;"
        f" cmp edx,0x1f400;"
        f" ja done;"
        f"\n   push edi;"
        f" push dword ptr [esi+16];"
        f" push dword ptr [0x9aa0e8];"
        f"\n   mov dword ptr [0x9aa0e8],1;"
        f" inc byte ptr [0x447115];"
        f"\n   add eax,{TEMP};"
        f" mov dword ptr [esi],eax;"
        f"\n   mov edi,{TEMP};"
        f" mov eax,0xffffffff;"
        f" mov ecx,32000;"
        f" rep stosd;"
        f"\n   mov eax,dword ptr [ebp+64];"
        f" xor ebx,ebx;"
        f" xor ecx,ecx;"
        f" xor edx,edx;"
        f"\n   call 0xa11a20;"
        f"\n   pop dword ptr [0x9aa0e8];"
        f" pop dword ptr [esi+16];"
        f" pop dword ptr [esi];"
        f"\n   dec byte ptr [0x447115];"
        f"\n   mov esi,{TEMP};"
        f" mov edi,{MASK};"
        f" mov ecx,32000;"
        f"\n   mask: lodsd;"
        f" and dword ptr [edi],eax;"
        f" add edi,4;"
        f" loop mask;"
        f"\n   mov ebp,{SLOTS};"
        f"\n   slot: cmp dword ptr [ebp],0;"
        f" je next;"
        f"\n   mov eax,dword ptr [0x446f78];"
        f" cmp eax,dword ptr [ebp+16];"
        f" jne next;"
        f"\n   mov esi,dword ptr [ebp+20];"
        f" add esi,{TEMP};"
        f" mov edi,dword ptr [ebp+64];"
        f"\n   mov edx,dword ptr [ebp+36];"
        f"\n   row: mov ecx,dword ptr [ebp+32];"
        f"\n   cell: lodsb;"
        f" and byte ptr [edi],al;"
        f" inc edi;"
        f" loop cell;"
        f"\n   add esi,320;"
        f" sub esi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz row;"
        f"\n   next: add ebp,128;"
        f" cmp ebp,0x1e3c600;"
        f" jb slot;"
        f"\n   inc dword ptr [0xa11c00];"
        f"\n   done: popad;"
        f" popfd;"
        f"\n   push eax;"
        f" lea eax,[esp+12];"
        f" add eax,0x10;"
        f" pop eax;"
        f"\n   lea esp,[esp+36];"
        f" ret;"
        f"\n  "
    )


def quick_source():
    return (
        f"\n call 0x1dfc400;"
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f"jne done;"
        f"\n cmp dword ptr [0x446f80],0x1900140;"
        f"jne done;"
        f"\n cmp dword ptr [0x44b1a0],0x392410;"
        f"jne done;"
        f"\n cmp word ptr [0x39241c],320;"
        f"jne done;"
        f"\n movsx eax,word ptr [0x392450];"
        f"movsx edx,word ptr [0x392452];"
        f"\n movsx ebx,word ptr [0x392454];"
        f"movsx ebp,word ptr [0x392456];"
        f"\n test eax,eax;"
        f"js done;"
        f"test edx,edx;"
        f"js done;"
        f"\n cmp ebx,320;"
        f"ja done;"
        f"cmp ebp,400;"
        f"ja done;"
        f"\n sub ebx,eax;"
        f"jle done;"
        f"sub ebp,edx;"
        f"jle done;"
        f"\n cmp bx,word ptr [0x392418];"
        f"jne done;"
        f"cmp bp,word ptr [0x39241a];"
        f"jne done;"
        f"\n imul edi,edx,320;"
        f"add edi,eax;"
        f"mov esi,edi;"
        f"add esi,[0x446f78];"
        f"\n cmp esi,[0x392410];"
        f"jne done;"
        f"\n add edi,{MASK};"
        f"xor eax,eax;"
        f"\n row:mov ecx,ebx;"
        f"rep stosb;"
        f"add edi,320;"
        f"sub edi,ebx;"
        f"dec ebp;"
        f"jnz row;"
        f"\n mov ebp,{SLOTS};"
        f"\n slot:cmp dword ptr [ebp],0;"
        f"je next;"
        f"\n mov eax,[0x446f78];"
        f"cmp eax,[ebp+16];"
        f"jne next;"
        f"\n mov ebx,[ebp+32];"
        f"test ebx,ebx;"
        f"jz next;"
        f"cmp ebx,320;"
        f"ja next;"
        f"\n mov edx,[ebp+36];"
        f"test edx,edx;"
        f"jz next;"
        f"cmp edx,400;"
        f"ja next;"
        f"\n mov eax,ebx;"
        f"imul eax,edx;"
        f"cmp eax,0x1f400;"
        f"ja next;"
        f"\n mov esi,[ebp+20];"
        f"cmp esi,0x1f400;"
        f"jae next;"
        f"\n lea eax,[edx-1];"
        f"imul eax,eax,320;"
        f"add eax,ebx;"
        f"add eax,esi;"
        f"cmp eax,0x1f400;"
        f"ja next;"
        f"\n add esi,{MASK};"
        f"mov edi,[ebp+64];"
        f"\n scan:mov ecx,ebx;"
        f"\n cell:lodsb;"
        f"and byte ptr [edi],al;"
        f"inc edi;"
        f"loop cell;"
        f"\n add esi,320;"
        f"sub esi,ebx;"
        f"dec edx;"
        f"jnz scan;"
        f"\n next:add ebp,128;"
        f"cmp ebp,0x1e3c600;"
        f"jb slot;"
        f"\n inc dword ptr [{STATE}];"
        f"\n done:popad;"
        f"popfd;"
        f"\n push eax;"
        f"lea eax,[esp-0x114];"
        f"add eax,0x104;"
        f"pop eax;"
        f"ret;"
        f"\n "
    )


def point_source():
    """Preserve weather cells across alternating physical row heights."""
    return (
        f"\n cmp dword ptr [0x44b1a0],{CANVAS};"
        f" jne other;"
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f" inc dword ptr [0x9bbae8];"
        f"\n mov esi,eax;"
        f" movsx edx,dx;"
        f" movsx ebx,bx;"
        f"\n test edx,edx;"
        f" js done;"
        f" test ebx,ebx;"
        f" js done;"
        f"\n mov eax,dword ptr [0x9a3d24];"
        f" mov eax,dword ptr [eax];"
        f" sub eax,dword ptr [0x446f78];"
        f"\n and eax,1;"
        f" xor eax,1;"
        f"\n imul edx,edx,5;"
        f" add edx,eax;"
        f" lea ebp,[edx+5];"
        f" sar edx,1;"
        f" sar ebp,1;"
        f"\n movzx ecx,word ptr [0x9c34f0];"
        f" cmp edx,ecx;"
        f" jge done;"
        f"\n cmp ebp,ecx;"
        f" jle right;"
        f" mov ebp,ecx;"
        f"\n right: sub ebp,edx;"
        f"\n push edx;"
        f"mov eax,[0x9a3d24];"
        f"mov eax,[eax];"
        f"sub eax,[0x446f78];"
        f"xor edx,edx;"
        f"mov ecx,320;"
        f"div ecx;"
        f"\n and eax,1;"
        f"xor eax,1;"
        f"lea ecx,[ebx+ebx*2];"
        f"add ecx,eax;"
        f"mov edx,ecx;"
        f"add edx,3;"
        f"shr ecx,1;"
        f"shr edx,1;"
        f"sub edx,ecx;"
        f"mov ebx,ecx;"
        f"pop ecx;"
        f"push edx;"
        f"mov edx,ecx;"
        f"\n movzx eax,word ptr [0x9c34f2];"
        f"cmp ebx,eax;"
        f"jl rowinside;"
        f"add esp,4;"
        f"jmp done;"
        f"rowinside:sub eax,ebx;"
        f"pop ecx;"
        f"cmp eax,ecx;"
        f"jle bottom;"
        f"mov eax,ecx;"
        f"\n bottom: push eax;"
        f"\n movzx ecx,word ptr [0x9c34f4];"
        f" imul ebx,ecx;"
        f" add ebx,edx;"
        f"\n mov edi,dword ptr [{CANVAS}];"
        f" add edi,ebx;"
        f"\n mov ebx,ecx;"
        f" sub ebx,ebp;"
        f" pop edx;"
        f" mov eax,esi;"
        f"\n row: mov ecx,ebp;"
        f" rep stosb;"
        f" add edi,ebx;"
        f" dec edx;"
        f" jnz row;"
        f"\n inc dword ptr [0x9bbaec];"
        f"\n done: popad;"
        f" popfd;"
        f" ret;"
        f"\n other: jmp 0x2fad20;"
        f"\n "
    )


def sprite_source():
    return (
        f"\n cmp dword ptr [0x44b1a0],{CANVAS};"
        f" jne other;"
        f"\n cmp byte ptr [eax+4],2;"
        f" jne other;"
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f" inc dword ptr [0x9bbaf0];"
        f"\n movzx ecx,word ptr [eax+8];"
        f" movzx ebp,word ptr [eax+10];"
        f"\n test ecx,ecx;"
        f" jz done;"
        f" cmp ecx,32;"
        f" ja done;"
        f"\n test ebp,ebp;"
        f" jz done;"
        f" cmp ebp,32;"
        f" ja done;"
        f"\n movzx edi,word ptr [eax+12];"
        f" sub edi,ecx;"
        f" js done;"
        f"\n mov esi,dword ptr [eax];"
        f" movsx edx,dx;"
        f" movsx ebx,bx;"
        f"\n push edi;"
        f" push ecx;"
        f" push edx;"
        f"\n row: mov edx,dword ptr [esp];"
        f" mov ecx,dword ptr [esp+4];"
        f"\n pixel: movzx eax,byte ptr [esi];"
        f" test eax,eax;"
        f" jz transparent;"
        f"\n call {POINT};"
        f"\n transparent: inc esi;"
        f" inc edx;"
        f" dec ecx;"
        f" jnz pixel;"
        f"\n add esi,dword ptr [esp+8];"
        f" inc ebx;"
        f" dec ebp;"
        f" jnz row;"
        f"\n add esp,12;"
        f"\n done: popad;"
        f" popfd;"
        f" ret;"
        f"\n other: jmp dword ptr [edi+0x24c];"
        f"\n "
    )


def coverage_source(*, high_rows=True, compass=True):
    rows = 400 if high_rows else 200
    MASK = 0x1e80000 if high_rows else 0x870000
    DATA = 0x9b90e8
    owner_guard = (
        "cmp esi,0x11000;"
        "jb done;"
        "cmp ebp,0x17fffa0;"
        "ja done;"
    ) if high_rows else ''
    compass_policy = (
        'cmp dword ptr [esi+0x18],0x2657a8; jne camera;'
        'cmp byte ptr [0x38fbfe],0; je normal;'
        'cmp byte ptr [0x38b9a2],0; je mark; jmp next;'
        'normal: cmp byte ptr [0x38b9a5],0; je mark; jmp next;camera:'
        if compass else 'cmp dword ptr [esi+0x18],0x2657a8; je mark;'
    )
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov esi,dword ptr [0x389dec];"
        f" mov ebp,dword ptr [0x389de8];"
        f"\n {owner_guard}cmp ebp,esi;"
        f" jb done;"
        f" mov eax,ebp;"
        f" sub eax,esi;"
        f" cmp eax,0x2000;"
        f" ja done;"
        f"\n widget:\n cmp dword ptr [esi+0x14],0x265028;"
        f" je mark;"
        f"\n {compass_policy}\n cmp dword ptr [esi+0x18],0x26bd44;"
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
        f" cmp ecx,{rows};"
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


def fast_compose_source():
    """Equivalent logical compositor with a four-transparent-cell skip."""
    return (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"cmp dword ptr [0x9aa0e8],0;"
        f"jne done;"
        f"\n mov dword ptr [0x9aa0e8],1;"
        f"inc byte ptr [0x447115];"
        f"\n mov esi,[0x446f78];"
        f"mov edi,{CACHE};"
        f"mov ecx,32000;"
        f".byte 0xf3,0xa5;"
        f"call {PREPARE};"
        f"call {COVER};"
        f"\n cmp dword ptr [{READY}],0;"
        f"je hud;"
        f"\n mov esi,{PIXELS};"
        f"mov edi,[0x9b90ec];"
        f"imul edi,edi,800;"
        f"add edi,[{DATA}];"
        f"add edi,{FRAME};"
        f"\n mov ebp,[0x9b90fc];"
        f"mov ebx,[0x9b90f8];"
        f"mov edx,800;"
        f"sub edx,ebx;"
        f"\n worldrow:mov ecx,ebx;"
        f"shr ecx,2;"
        f".byte 0xf3,0xa5;"
        f"mov ecx,ebx;"
        f"and ecx,3;"
        f"rep movsb;"
        f"add edi,edx;"
        f"dec ebp;"
        f"jnz worldrow;"
        f"\n hud:mov esi,{CACHE};"
        f"mov edi,{FRAME};"
        f"xor ebp,ebp;"
        f"sub esp,8;"
        f"mov dword ptr [esp],0;"
        f"\n row:mov eax,[esp];"
        f"and eax,1;"
        f"neg eax;"
        f"add eax,2;"
        f"mov [esp+4],eax;"
        f"xor ebx,ebx;"
        f"xor edx,edx;"
        f"\n pixel:test edx,3;"
        f"jnz slow87;"
        f"\n cmp dword ptr [esi],0;"
        f"jne slow87;"
        f"\n cmp dword ptr [esi+0x20000],-1;"
        f"jne slow87;"
        f"\n cmp dword ptr [{READY}],0;"
        f"je slow87;"
        f"\n cmp ebp,[0x9b90ec];"
        f"jb slow87;"
        f"cmp ebp,[0x9b90f4];"
        f"jae slow87;"
        f"\n cmp ebx,[{DATA}];"
        f"jb slow87;"
        f"lea eax,[ebx+10];"
        f"cmp eax,[0x9b90f0];"
        f"ja slow87;"
        f"\n add esi,4;"
        f"add edi,10;"
        f"add ebx,10;"
        f"add edx,4;"
        f"cmp edx,320;"
        f"jb pixel;"
        f"jmp rowend87;"
        f"\n slow87:mov ecx,edx;"
        f"and ecx,1;"
        f"neg ecx;"
        f"add ecx,3;"
        f"\n mov al,[esi];"
        f"test al,al;"
        f"jnz opaque;"
        f"cmp dword ptr [{READY}],0;"
        f"je opaque;"
        f"\n cmp ebp,[0x9b90ec];"
        f"jb opaque;"
        f"cmp ebp,[0x9b90f4];"
        f"jae opaque;"
        f"\n cmp ebx,[{DATA}];"
        f"jb opaque;"
        f"cmp ebx,[0x9b90f0];"
        f"jae opaque;"
        f"\n cmp byte ptr [esi+0x20000],0;"
        f"jne next;"
        f"\n opaque:mov ah,al;"
        f"mov [edi],ax;"
        f"cmp ecx,3;"
        f"jne shortcell;"
        f"mov [edi+2],al;"
        f"\n shortcell:cmp dword ptr [esp+4],2;"
        f"jne next;"
        f"mov [edi+800],ax;"
        f"cmp ecx,3;"
        f"jne next;"
        f"mov [edi+802],al;"
        f"\n next:inc esi;"
        f"add edi,ecx;"
        f"add ebx,ecx;"
        f"inc edx;"
        f"cmp edx,320;"
        f"jb pixel;"
        f"\n rowend87:mov eax,[esp+4];"
        f"add ebp,eax;"
        f"dec eax;"
        f"imul eax,eax,800;"
        f"add edi,eax;"
        f"inc dword ptr [esp];"
        f"cmp dword ptr [esp],400;"
        f"jb row;"
        f"\n add esp,8;"
        f"call {MERGE};"
        f"call 0x1e45a00;"
        f"mov esi,{FRAME};"
        f"mov edi,0xe0000000;"
        f"mov ecx,0x1d4c0;"
        f".byte 0xf3,0xa5;"
        f"\n dec byte ptr [0x447115];"
        f"mov dword ptr [0x9aa0e8],0;"
        f"\n done:popad;"
        f"popfd;"
        f"ret;"
    )


def bodies():
    """Shared logical HUD and retained fallback bodies, in fixed installation order."""
    return [
        (0x1e30000, code(0x1e30000, world_source())),
        (0x1e31000, code(0x1e31000, target_source())),
        (0x1e31800, code(CONVERT, pick.rectangle_source(pick.Profile.HUD400))),
        (0x1e32000, code(0x1e32000, reset_source())),
        (0x1e32200, code(0x1e32200, text_source())),
        (0x1e33000, code(COVER, coverage_source(compass=False))),
        (0x1e34000, code(0x1e34000, compose_source())),
        (0x1e35000, code(0x1e35000, paint_source())),
        (0x1e35a00, code(0x1e35a00, movement_source())),
        (0x1e35c00, code(0x1e35c00, callback_source())),
        (0x1e36000, code(0x1e36000, cursor_compose_source())),
        (0x1e51000, struct.pack('<600I', *((y * 2 // 3) * 320 for y in range(600)))),
        (0x1e38000, code(0x1e38000, camera_source())),
        (0x1e3b000, code(0x1e3b000, prepare_source())),
        (0x1e3a000, code(0x1e3a000, merge_source())),
        (0x1e3b400, code(0x1e3b400, invalidate_source())),
        (0x1e37000, code(0x1e37000, message_box_source())),
        (0x1e37400, code(0x1e37400, confirmation_box_source())),
        (0x1e37800, code(0x1e37800, quick_source())),
        (0x1e46a00, code(0x1e46a00, point_source())),
        (0x1e46c00, code(0x1e46c00, sprite_source())),
    ]


def dispatch_bodies(map_payload, map_hooks, map_slot):
    out = bodies() + list(map_payload)
    hooks = []
    gate = GATES

    def dispatch(site, new, old):
        nonlocal gate
        a = gate
        gate += 0x40
        out.append(
            (
                a,
                code(
                    a, (
                        f"pushfd;"
                        f"cmp dword ptr [0x446f80],0x01900140;"
                        f"jne low;"
                        f"popfd;"
                        f"jmp {new};"
                        f"low:popfd;"
                        f"jmp {old};"
                    )
                )
            )
        )
        if site is not None:
            hooks.append((site, asm(site, f'jmp {a}')))
        return a

    camera_gate = dispatch(None, CAMERA, pick.ORIGINAL_RENDER)
    # Preserve the target-selection quad cache around both rendering backends.
    out.append((pick.RENDER, code(pick.RENDER, pick.render_source(camera_gate))))
    out.append((PICK, code(PICK, pick.quad_source(pick.Profile.HUD400))))
    dispatch(pick.SITE, PICK, pick.ENTRY)
    dispatch(0x2e43d0, CURSOR_COMPOSE, 0x9ab6e8)
    for site, new, old in (
        (0x268098, TEXT, 0x9b02e8), (0x9ab8e8, CURSOR_COMPOSE, 0x9ae6e8),
        (0x2f25ae, MOVEMENT, 0x9af0e8), (0x2e54e0, CALLBACK, 0x9af2e8),
        (0x274da4, INVALIDATE, 0x9d9400), (0x27be1c, QUICK, 0x1dfc000),
        (0x2454bc, BOXES[0][1], 0xa11200), (0x245600, BOXES[1][1], 0xa11600)
    ):
        dispatch(site, new, old)
    point_gate = dispatch(None, POINT, 0x9bb0e8)
    sprite_gate = dispatch(None, SPRITE, 0x9bb4e8)
    for site in (0x2afb47, 0x2afb6a, 0x2afb82):
        hooks.append((site, asm(site, f'call {point_gate}')))
    hooks.append((0x2afbad, asm(0x2afbad, f'call {sprite_gate}') + b'\x90'))
    hooks.extend(map_hooks)
    # A map can occupy the main visor, with no main-world render to clear the
    # frame's coverage mask. Reset it at the actual widget-frame boundary.
    out.append(
        (
            FRAME_BEGIN,
            code(
                FRAME_BEGIN, (
                    f"pushfd;"
                    f"pushad;"
                    f"cld;"
                    f"\n cmp dword ptr [0x446f80],0x01900140;"
                    f"jne done;"
                    f"\n mov edi,{MASK};"
                    f"mov eax,-1;"
                    f"mov ecx,32000;"
                    f"rep stosd;"
                    f"\n mov dword ptr [{map_slot}],0;"
                    f"\n done:popad;"
                    f"popfd;"
                    f"push ebx;"
                    f"push ecx;"
                    f"push edx;"
                    f"mov edx,[0x389dec];"
                    f"jmp 0x261be1;"
                )
            )
        )
    )
    hooks.append((0x261bd8, asm(0x261bd8, f'jmp {FRAME_BEGIN}') + b'\x90' * 4))
    # Ask the original mode-0 driver to initialize its linear surface, then
    # replace the owned heap buffer with a taller one. It remains heap-owned,
    # so the game's next resize/free path works unchanged.
    s = (
        f"cmp ax,2;"
        f"jne original;"
        f"push eax;"
        f"xor eax,eax;"
        f"call {MODE_ORIG};"
        f"add esp,4;"
        f"\n pushfd;"
        f"pushad;"
        f"mov eax,128000;"
        f"call dword ptr [0x35f4a4];"
        f"test eax,eax;"
        f"jz failed;"
        f"\n push eax;"
        f"mov eax,[0x446f78];"
        f"call dword ptr [0x35f4ac];"
        f"pop eax;"
        f"mov [0x446f78],eax;"
        f"\n mov edi,eax;"
        f"xor eax,eax;"
        f"mov ecx,32000;"
        f"cld;"
        f"rep stosd;"
        f"\n mov dword ptr [0x446f80],0x01900140;"
        f"mov word ptr [0x446f84],320;"
        f"\n mov dword ptr [0x446fa4],0;"
        f"mov dword ptr [0x446fa8],0;"
        f"mov dword ptr [0x446fac],0x01400000;"
        f"mov dword ptr [0x446fb0],0x01900000;"
        f"\n mov dword ptr [0x446fbc],0x01900140;"
        f"mov dword ptr [0x44b1ac],0x9999;"
        f"\n mov eax,0x446f78;"
        f"call 0x2eab30;"
        f"\n mov dword ptr [0x9af4e8],0;"
        f"mov dword ptr [0x9af5e8],0;"
        f"mov dword ptr [{READY}],0;"
        f"\n mov dword ptr [{SLOTS}],0;"
        f"mov dword ptr [{SLOTS+128}],0;"
        f"mov dword ptr [{SLOTS+256}],0;"
        f"\n popad;"
        f"popfd;"
        f"ret;"
        f"\n failed:mov eax,0xff00;"
        f"int 0x21;"
        f"\n original:jmp {MODE_ORIG};"
    )
    out.append((MODE, code(MODE, s)))
    out.append(
        (
            MODE_ORIG,
            asm(
                MODE_ORIG,
                ("push ebx;"
                 "push ecx;"
                 "push edx;"
                 "push esi;"
                 "push edi;"
                 "jmp 0x2e3f95;")
            )
        )
    )
    hooks.append((0x2e3f90, asm(0x2e3f90, f'jmp {MODE}')))
    out.append(
        (
            MISSION,
            code(
                MISSION, (
                    "call 0x2617f4;"
                    "pushfd;"
                    "pushad;"
                    "cmp word ptr [0x446f82],200;"
                    "jne done;"
                    "mov eax,2;"
                    "call 0x2633a0;"
                    "done:popad;"
                    "popfd;"
                    "ret;"
                )
            )
        )
    )
    hooks.append((0x2617e6, asm(0x2617e6, f'call {MISSION}')))
    # Restore the real resolution selector, formerly locked to 200 rows.
    hooks.append((0x2633f0, bytes.fromhex('750d')))
    return out, hooks


# Damage providers for the original logical HUD.
DAMAGE_ENTRY = 0x1df7000
DAMAGE_CHOOSE = DAMAGE_ENTRY + 0x400
DAMAGE_PIXEL = DAMAGE_ENTRY + 0x600
DAMAGE_COPY = DAMAGE_ENTRY + 0x700
DAMAGE_LINE = DAMAGE_ENTRY + 0x800
DAMAGE_STATE = 0x1df8000
DAMAGE_BUCKET = DAMAGE_STATE
DAMAGE_RECORD = DAMAGE_STATE + 4
DAMAGE_KIND = DAMAGE_STATE + 8
DAMAGE_WIDTH = DAMAGE_STATE + 12
DAMAGE_HEIGHT = DAMAGE_STATE + 16
DAMAGE_COMMANDS = DAMAGE_STATE + 20
DAMAGE_OWNER = DAMAGE_STATE + 24
DAMAGE_CALLS = DAMAGE_STATE + 28
DAMAGE_TRIALS = DAMAGE_STATE + 32
DAMAGE_EVENTS = DAMAGE_STATE + 36
DAMAGE_RENDERS = DAMAGE_STATE + 40
DAMAGE_FALLBACKS = DAMAGE_STATE + 44
DAMAGE_DOTS = DAMAGE_STATE + 0x400
DAMAGE_RECTS = DAMAGE_STATE + 0x900
DAMAGE_DRAW = 0x1df9000
DAMAGE_RECT = 0x1df9300
DAMAGE_NOISE = 0x1df9600
DAMAGE_LINES = 0x1df9900
DAMAGE_END = 0x1dfa000
DAMAGE_SITE = 0x26920e
DAMAGE_PERIOD = 50
DAMAGE_CANVAS = 0x9c34e8
DAMAGE_PIXELS = 0x918ae8


def damage_branch(a, b, call=False):
    return (b'\xe8' if call else b'\xe9') + struct.pack('<i', b - a - 5)


def damage_bodies(
    asm,
    *,
    entry_address=DAMAGE_ENTRY,
    draw_address=DAMAGE_DRAW,
    rect_address=DAMAGE_RECT,
    noise_address=DAMAGE_NOISE,
    lines_address=DAMAGE_LINES,
    pixels=DAMAGE_PIXELS,
    width=800,
    height=600
):
    # Explicit drawing addresses/capacity permit a second canvas without mutating
    # the original recording damage_hooks, shared commands, RNG or timing state.
    entry = asm(
        entry_address, (
            f"pushfd;"
            f"pushad;"
            f"\n inc dword ptr [{DAMAGE_CALLS}];"
            f"\n cmp byte ptr [0x1d0d449],0x6b;"
            f"jne fallback;"
            f"\n cmp dword ptr [0x9aa0ec],1;"
            f"jne fallback;"
            f"\n mov esi,[0x44b1a0];"
            f"cmp esi,[0x9a3d24];"
            f"jne fallback;"
            f"\n cmp dword ptr [{DAMAGE_CANVAS}],{pixels};"
            f"jne fallback;"
            f"\n movzx eax,word ptr [{DAMAGE_CANVAS+8}];"
            f"test eax,eax;"
            f"jz fallback;"
            f"cmp eax,{width};"
            f"ja fallback;"
            f"\n movzx eax,word ptr [{DAMAGE_CANVAS+10}];"
            f"test eax,eax;"
            f"jz fallback;"
            f"cmp eax,{height};"
            f"ja fallback;"
            f"\n movzx eax,word ptr [esi+8];"
            f"test eax,eax;"
            f"jz fallback;"
            f"\n movzx eax,word ptr [esi+10];"
            f"cmp eax,8;"
            f"jb fallback;"
            f"\n mov eax,[0x446ae8];"
            f"xor edx,edx;"
            f"mov ebx,{DAMAGE_PERIOD};"
            f"div ebx;"
            f"inc eax;"
            f"\n cmp eax,[{DAMAGE_BUCKET}];"
            f"jne trial;"
            f"\n mov edx,[0x44134e];"
            f"cmp edx,[{DAMAGE_OWNER}];"
            f"je paint;"
            f"\n trial:mov [{DAMAGE_BUCKET}],eax;"
            f"mov eax,[0x44134e];"
            f"mov [{DAMAGE_OWNER}],eax;"
            f"\n movzx eax,word ptr [esi+8];"
            f"mov [{DAMAGE_WIDTH}],eax;"
            f"\n movzx eax,word ptr [esi+10];"
            f"mov [{DAMAGE_HEIGHT}],eax;"
            f"\n mov dword ptr [{DAMAGE_KIND}],-1;"
            f"mov dword ptr [{DAMAGE_COMMANDS}],0;"
            f"mov dword ptr [{DAMAGE_RECORD}],1;"
            f"\n inc dword ptr [{DAMAGE_TRIALS}];"
            f"call 0x27a618;"
            f"mov dword ptr [{DAMAGE_RECORD}],0;"
            f"\n cmp dword ptr [{DAMAGE_KIND}],-1;"
            f"je paint;"
            f"inc dword ptr [{DAMAGE_EVENTS}];"
            f"\n paint:cmp dword ptr [{DAMAGE_KIND}],-1;"
            f"je done;"
            f"\n call {draw_address};"
            f"inc dword ptr [{DAMAGE_RENDERS}];"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
            f"\n fallback:inc dword ptr [{DAMAGE_FALLBACKS}];"
            f"popad;"
            f"popfd;"
            f"jmp 0xa11d00;"
        )
    )
    assert len(entry) < 0x400
    choose = asm(
        DAMAGE_CHOOSE, (
            f"pushfd;"
            f"cmp dword ptr [{DAMAGE_RECORD}],1;"
            f"jne original;"
            f"mov [{DAMAGE_KIND}],ecx;"
            f"\n original:popfd;"
            f"cmp ecx,7;"
            f"ja 0x27a72d;"
            f"jmp 0x27a6c5;"
        )
    )
    pixel = asm(
        DAMAGE_PIXEL, (
            f"pushfd;"
            f"cmp dword ptr [{DAMAGE_RECORD}],1;"
            f"jne original;"
            f"pushad;"
            f"\n cmp ecx,1;"
            f"jb done;"
            f"cmp ecx,100;"
            f"ja done;"
            f"\n lea edi,[ecx-1];"
            f"imul edi,edi,12;"
            f"add edi,{DAMAGE_DOTS};"
            f"\n mov [edi],edx;"
            f"mov [edi+4],ebx;"
            f"mov [edi+8],eax;"
            f"\n done:popad;"
            f"popfd;"
            f"cmp ecx,100;"
            f"jmp 0x27a784;"
            f"\n original:popfd;"
            f"call dword ptr [esi+4];"
            f"cmp ecx,100;"
            f"jmp 0x27a784;"
        )
    )
    copy = asm(
        DAMAGE_COPY, (
            f"pushfd;"
            f"cmp dword ptr [{DAMAGE_RECORD}],1;"
            f"jne original;"
            f"pushad;"
            f"\n mov edi,[{DAMAGE_COMMANDS}];"
            f"cmp edi,2;"
            f"jae done;"
            f"imul edi,edi,24;"
            f"add edi,{DAMAGE_RECTS};"
            f"\n mov [edi],eax;"
            f"mov [edi+4],edx;"
            f"mov [edi+8],ebx;"
            f"mov [edi+12],ecx;"
            f"\n mov eax,[esp+40];"
            f"mov [edi+16],eax;"
            f"mov eax,[esp+44];"
            f"mov [edi+20],eax;"
            f"\n inc dword ptr [{DAMAGE_COMMANDS}];"
            f"\n done:popad;"
            f"popfd;"
            f"ret 8;"
            f"\n original:popfd;"
            f"push esi;"
            f"push edi;"
            f"sub esp,24;"
            f"jmp 0x27a505;"
        )
    )
    line = asm(
        DAMAGE_LINE, (
            f"pushfd;"
            f"cmp dword ptr [{DAMAGE_RECORD}],1;"
            f"jne original;"
            f"popfd;"
            f"ret;"
            f"\n original:popfd;"
            f"jmp 0x2f3a46;"
        )
    )
    draw = asm(
        draw_address, (
            f"pushad;"
            f"\n push dword ptr [0x44b1a0];"
            f"mov eax,{DAMAGE_CANVAS};"
            f"call 0x2eab30;"
            f"\n mov eax,[{DAMAGE_KIND}];"
            f"cmp eax,4;"
            f"je lines;"
            f"test eax,eax;"
            f"jz rectangles;"
            f"cmp eax,5;"
            f"jae rectangles;"
            f"\n call {noise_address};"
            f"jmp done;"
            f"\n lines:call {lines_address};"
            f"jmp done;"
            f"\n rectangles:mov ecx,[{DAMAGE_COMMANDS}];"
            f"cmp ecx,2;"
            f"ja done;"
            f"test ecx,ecx;"
            f"jz done;"
            f"mov esi,{DAMAGE_RECTS};"
            f"\n next:call {rect_address};"
            f"add esi,24;"
            f"dec ecx;"
            f"jnz next;"
            f"\n done:pop eax;"
            f"call 0x2eab30;"
            f"popad;"
            f"ret;"
        )
    )
    # Expand logical inclusive rectangles into native pixel extents. Keep the
    # original forward-copy routine: its overlap deliberately produces smears.
    rect = 'pushad;sub esp,24;'
    for i in range(6):
        dim = 8 if i % 2 == 0 else 10
        den = DAMAGE_WIDTH if i % 2 == 0 else DAMAGE_HEIGHT
        rect += f'mov eax,[esi+{i*4}];'
        if i in (2, 3):
            rect += 'inc eax;'
        rect += (
            f"movzx ebx,word ptr [{DAMAGE_CANVAS+dim}];"
            f"imul eax,ebx;"
            f"xor edx,edx;"
            f"div dword ptr [{den}];"
        )
        if i in (2, 3):
            rect += 'dec eax;'
        rect += f'mov [esp+{i*4}],eax;'
    rect += (
        "mov eax,[esp];"
        "mov edx,[esp+4];"
        "mov ebx,[esp+8];"
        "mov ecx,[esp+12];"
        "push dword ptr [esp+20];"
        "push dword ptr [esp+20];"
        "call 0x27a500;"
        "add esp,24;"
        "popad;"
        "ret;"
    )
    rect = asm(rect_address, rect)
    assert len(rect) < 0x300
    # The original 100 samples become logical-pixel-sized speckles. Coordinates
    # and colours were recorded before compositing, retaining opaque black dots.
    noise = (
        f"pushad;"
        f"sub esp,24;"
        f"cld;"
        f"mov esi,{DAMAGE_DOTS};"
        f"mov ebp,100;"
        f"\n dot:mov eax,[esi];"
        f"movzx ebx,word ptr [{DAMAGE_CANVAS+8}];"
        f"imul eax,ebx;"
        f"xor edx,edx;"
        f"div dword ptr [{DAMAGE_WIDTH}];"
        f"mov [esp],eax;"
        f"\n mov eax,[esi];"
        f"inc eax;"
        f"imul eax,ebx;"
        f"xor edx,edx;"
        f"div dword ptr [{DAMAGE_WIDTH}];"
        f"sub eax,[esp];"
        f"mov [esp+4],eax;"
        f"\n mov eax,[esi+4];"
        f"movzx ebx,word ptr [{DAMAGE_CANVAS+10}];"
        f"imul eax,ebx;"
        f"xor edx,edx;"
        f"div dword ptr [{DAMAGE_HEIGHT}];"
        f"mov [esp+8],eax;"
        f"\n mov eax,[esi+4];"
        f"inc eax;"
        f"imul eax,ebx;"
        f"xor edx,edx;"
        f"div dword ptr [{DAMAGE_HEIGHT}];"
        f"sub eax,[esp+8];"
        f"mov [esp+12],eax;"
        f"\n movzx edx,word ptr [{DAMAGE_CANVAS+12}];"
        f"mov [esp+16],edx;"
        f"\n mov edi,[esp+8];"
        f"imul edi,edx;"
        f"add edi,[esp];"
        f"add edi,{pixels};"
        f"\n mov ebx,[esp+12];"
        f"test ebx,ebx;"
        f"jz next;"
        f"mov eax,[esi+8];"
        f"\n row:push edi;"
        f"mov ecx,[esp+8];"
        f"rep stosb;"
        f"pop edi;"
        f"add edi,[esp+16];"
        f"dec ebx;"
        f"jnz row;"
        f"\n next:add esi,12;"
        f"dec ebp;"
        f"jnz dot;"
        f"add esp,24;"
        f"popad;"
        f"ret;"
    )
    noise = asm(noise_address, noise)
    assert len(noise) < 0x300
    # Alternate logical scanlines, expanding each row group and its two-pixel
    # displacement. The original overlap-safe mover retains each edge's pixels.
    lines = asm(
        lines_address, (
            f"pushad;"
            f"sub esp,16;"
            f"\n movzx eax,word ptr [{DAMAGE_CANVAS+8}];"
            f"mov [esp],eax;"
            f"add eax,eax;"
            f"xor edx,edx;"
            f"div dword ptr [{DAMAGE_WIDTH}];"
            f"mov [esp+4],eax;"
            f"\n movzx eax,word ptr [{DAMAGE_CANVAS+10}];"
            f"mov [esp+8],eax;"
            f"mov dword ptr [esp+12],0;"
            f"\n row:mov eax,[esp+12];"
            f"imul eax,[{DAMAGE_HEIGHT}];"
            f"xor edx,edx;"
            f"div dword ptr [esp+8];"
            f"mov ebp,eax;"
            f"\n movzx eax,word ptr [{DAMAGE_CANVAS+12}];"
            f"imul eax,[esp+12];"
            f"add eax,{pixels};"
            f"mov edx,eax;"
            f"\n test ebp,1;"
            f"jnz left;"
            f"add eax,[esp+4];"
            f"jmp move;"
            f"\n left:add edx,[esp+4];"
            f"\n move:mov ebx,[esp];"
            f"sub ebx,[esp+4];"
            f"jle next;"
            f"call 0x2f3a46;"
            f"\n next:inc dword ptr [esp+12];"
            f"mov eax,[esp+12];"
            f"cmp eax,[esp+8];"
            f"jb row;"
            f"\n add esp,16;"
            f"popad;"
            f"ret;"
        )
    )
    assert len(lines) < 0x300
    return [
        (entry_address, entry), (DAMAGE_CHOOSE, choose), (DAMAGE_PIXEL, pixel), (DAMAGE_COPY, copy),
        (DAMAGE_LINE, line), (draw_address, draw), (rect_address, rect), (noise_address, noise),
        (lines_address, lines)
    ]


def damage_hooks(asm):
    return [
        (
            DAMAGE_SITE, damage_branch(DAMAGE_SITE, DAMAGE_ENTRY,
                                       True), damage_branch(DAMAGE_SITE, 0xa11d00, True)
        ), (0x27a6c0, damage_branch(0x27a6c0, DAMAGE_CHOOSE), bytes.fromhex('83f9077768')),
        (0x27a77e, damage_branch(0x27a77e, DAMAGE_PIXEL) + b'\x90', bytes.fromhex('ff560483f964')),
        (0x27a500, damage_branch(0x27a500, DAMAGE_COPY), bytes.fromhex('565783ec18')),
        (
            0x27a7f6, damage_branch(0x27a7f6, DAMAGE_LINE,
                                    True), damage_branch(0x27a7f6, 0x2f3a46, True)
        )
    ]


# Nav providers for the original logical HUD.
NAV_LABEL = 0x1dfb000
NAV_STATE = 0x1dfb400
NAV_END = 0x1dfc000
NAV_NAV = 0x29ba3c
NAV_TEXT = 0x29bbf1
NAV_CANVAS = 0x9c34e8
NAV_PIXELS = 0x918ae8
NAV_LOW = 0x9a3d24


def nav_branch(a, b, call=False):
    return (b'\xe8' if call else b'\xe9') + struct.pack('<i', b - a - 5)


def nav_bodies(asm, *, label=NAV_LABEL, pixels=NAV_PIXELS):
    code = asm(
        label, (
            f"\n pushfd;"
            f"pushad;"
            f"\n cmp byte ptr [0x1d0d449],0x6b;"
            f"jne other;"
            f"\n cmp dword ptr [0x44b1a0],{NAV_CANVAS};"
            f"jne other;"
            f"\n cmp dword ptr [{NAV_CANVAS}],{pixels};"
            f"jne other;"
            f"\n mov esi,[{NAV_LOW}];"
            f"test esi,esi;"
            f"jz other;"
            f"\n cmp word ptr [esi+12],320;"
            f"jne other;"
            f"\n movzx eax,word ptr [{NAV_CANVAS+8}];"
            f"test eax,eax;"
            f"jz other;"
            f"\n movzx eax,word ptr [{NAV_CANVAS+10}];"
            f"test eax,eax;"
            f"jz other;"
            f"\n sub esp,8;"
            f"\n mov eax,[esi+32];"
            f"mov [esp],eax;"
            f"mov eax,[esi+36];"
            f"mov [esp+4],eax;"
            f"\n mov dword ptr [esi+32],0;"
            f"\n mov eax,[{NAV_CANVAS+16}];"
            f"mov [esi+16],eax;"
            f"\n mov eax,[0x41e210];"
            f"movzx ebx,word ptr [esi+8];"
            f"imul eax,ebx;"
            f"cdq;"
            f"\n movzx ecx,word ptr [{NAV_CANVAS+8}];"
            f"idiv ecx;"
            f"mov [0x41e210],eax;"
            f"add eax,15;"
            f"mov [esp+24],eax;"
            f"\n mov eax,[0x41e214];"
            f"movzx ebx,word ptr [esi+10];"
            f"imul eax,ebx;"
            f"cdq;"
            f"\n movzx ecx,word ptr [{NAV_CANVAS+10}];"
            f"idiv ecx;"
            f"mov [0x41e214],eax;"
            f"sub eax,3;"
            f"mov [esp+32],eax;"
            f"\n mov eax,esi;"
            f"call 0x2eab30;"
            f"\n inc dword ptr [{NAV_STATE}];"
            f"\n mov edi,[esp+8];"
            f"mov esi,[esp+12];"
            f"mov ebp,[esp+16];"
            f"mov ebx,[esp+24];"
            f"\n mov edx,[esp+28];"
            f"mov ecx,[esp+32];"
            f"mov eax,[esp+36];"
            f"push dword ptr [esp+40];"
            f"popfd;"
            f"\n call 0x2e4304;"
            f"\n pushfd;"
            f"pushad;"
            f"\n mov esi,[{NAV_LOW}];"
            f"mov eax,[esp+36];"
            f"mov [esi+32],eax;"
            f"mov eax,[esp+40];"
            f"mov [esi+36],eax;"
            f"\n mov eax,[esi+16];"
            f"mov [{NAV_CANVAS+16}],eax;"
            f"\n mov eax,{NAV_CANVAS};"
            f"call 0x2eab30;"
            f"\n popad;"
            f"popfd;"
            f"lea esp,[esp+44];"
            f"ret;"
            f"\n other:inc dword ptr [{NAV_STATE+4}];"
            f"popad;"
            f"popfd;"
            f"jmp 0x2e4304;"
            f"\n "
        )
    )
    assert len(code) < 0x400
    return [(label, code)]


def nav_hooks(asm):
    return [
        (NAV_NAV, bytes.fromhex('5351525657'), nav_branch(NAV_NAV, 0x9b70e8)),
        (NAV_TEXT, nav_branch(NAV_TEXT, NAV_LABEL, True), nav_branch(NAV_TEXT, 0x2e4304, True))
    ]


# Menu providers for the original logical HUD.
from foundation_cameras import SLOTS as MENU_SLOTS

MENU_ENTRY = 0x1dfc000
MENU_ORIGINAL = 0x1dfc400
MENU_STATE = 0x1dfc500
MENU_END = 0x1dfd000
MENU_DRAW = 0x27be1c
MENU_CANVAS = 0x392410
MENU_RECT = 0x392450
MENU_MASK = 0x870000


def menu_branch(a, b):
    return b'\xe9' + struct.pack('<i', b - a - 5)


def menu_bodies(asm):
    code = asm(
        MENU_ENTRY, (
            f"\n call {MENU_ORIGINAL};"
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"\n cmp byte ptr [0x1d0d449],0x6b;"
            f"jne done;"
            f"\n cmp dword ptr [0x446f80],0x00c80140;"
            f"jne done;"
            f"\n cmp dword ptr [0x44b1a0],{MENU_CANVAS};"
            f"jne done;"
            f"\n cmp word ptr [{MENU_CANVAS+12}],320;"
            f"jne done;"
            f"\n movsx eax,word ptr [{MENU_RECT}];"
            f"movsx edx,word ptr [{MENU_RECT+2}];"
            f"\n movsx ebx,word ptr [{MENU_RECT+4}];"
            f"movsx ebp,word ptr [{MENU_RECT+6}];"
            f"\n test eax,eax;"
            f"js done;"
            f"test edx,edx;"
            f"js done;"
            f"\n cmp ebx,320;"
            f"ja done;"
            f"cmp ebp,200;"
            f"ja done;"
            f"\n sub ebx,eax;"
            f"jle done;"
            f"sub ebp,edx;"
            f"jle done;"
            f"\n cmp bx,word ptr [{MENU_CANVAS+8}];"
            f"jne done;"
            f"cmp bp,word ptr [{MENU_CANVAS+10}];"
            f"jne done;"
            f"\n imul edi,edx,320;"
            f"add edi,eax;"
            f"mov esi,edi;"
            f"add esi,[0x446f78];"
            f"\n cmp esi,[{MENU_CANVAS}];"
            f"jne done;"
            f"\n add edi,{MENU_MASK};"
            f"xor eax,eax;"
            f"\n row:mov ecx,ebx;"
            f"rep stosb;"
            f"add edi,320;"
            f"sub edi,ebx;"
            f"dec ebp;"
            f"jnz row;"
            f"\n mov ebp,{MENU_SLOTS};"
            f"\n slot:cmp dword ptr [ebp],0;"
            f"je next;"
            f"\n mov eax,[0x446f78];"
            f"cmp eax,[ebp+16];"
            f"jne next;"
            f"\n mov ebx,[ebp+32];"
            f"test ebx,ebx;"
            f"jz next;"
            f"cmp ebx,320;"
            f"ja next;"
            f"\n mov edx,[ebp+36];"
            f"test edx,edx;"
            f"jz next;"
            f"cmp edx,200;"
            f"ja next;"
            f"\n mov eax,ebx;"
            f"imul eax,edx;"
            f"cmp eax,6400;"
            f"ja next;"
            f"\n mov esi,[ebp+20];"
            f"cmp esi,64000;"
            f"jae next;"
            f"\n lea eax,[edx-1];"
            f"imul eax,eax,320;"
            f"add eax,ebx;"
            f"add eax,esi;"
            f"cmp eax,64000;"
            f"ja next;"
            f"\n add esi,{MENU_MASK};"
            f"mov edi,[ebp+64];"
            f"\n scan:mov ecx,ebx;"
            f"\n cell:lodsb;"
            f"and byte ptr [edi],al;"
            f"inc edi;"
            f"loop cell;"
            f"\n add esi,320;"
            f"sub esi,ebx;"
            f"dec edx;"
            f"jnz scan;"
            f"\n next:add ebp,128;"
            f"cmp ebp,{MENU_SLOTS+384};"
            f"jb slot;"
            f"\n inc dword ptr [{MENU_STATE}];"
            f"\n done:popad;"
            f"popfd;"
            f"\n push eax;"
            f"lea eax,[esp-0x114];"
            f"add eax,0x104;"
            f"pop eax;"
            f"ret;"
            f"\n "
        )
    )
    tramp = asm(
        MENU_ORIGINAL,
        (f"push ebx;"
         f"push ecx;"
         f"push edx;"
         f"push esi;"
         f"push edi;"
         f"jmp {MENU_DRAW+5};")
    )
    assert len(code) < 0x400
    return [(MENU_ENTRY, code), (MENU_ORIGINAL, tramp)]


def menu_hooks(asm):
    return [(MENU_DRAW, menu_branch(MENU_DRAW, MENU_ENTRY), bytes.fromhex('5351525657'))]
