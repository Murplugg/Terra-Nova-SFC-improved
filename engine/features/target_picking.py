"""Select visible units using their projected armor, markers and object bounds.

Selection first checks armor-piece quads, then visible PBA sensor markers, then
object rectangles and depth. The original assisted picker remains the fallback.
Each renderer chooses an explicit coordinate profile. The quad cache and distance
helpers keep fixed image addresses; enlarged views place their specialized picker
in the renderer arena. Shot Aim Assist controls a separate firing query.

At entry, the original picker prologue has placed packed x/y at ESP+12 and the
target word at ESP+16. Helpers preserve integer registers and flags, writing the
target and diagnostics before returning to the selected original continuation.
The main world render builds up to 1024 quad records, each with four signed pixel
vertices and an object ID. Auxiliary views cannot populate the cache. Overflow
discards the incomplete quad result and uses the fallback selection paths.
"""
import struct
from patch_support import asm as default_asm
from enum import Enum

SITE = 0x269f4d
ORIGINAL = bytes.fromhex('8b1d80bf3500')
RECT_ENTRY = 0x1de7000
RECT_STATE = RECT_ENTRY + 0xf00
MARKER_ENTRY = 0x1de9000
MARKER_STATE = MARKER_ENTRY + 0xf00
ENTRY = 0x1dea000
DIST = ENTRY + 0x600
RENDER = ENTRY + 0x900
PART = ENTRY + 0xa00
STATE = ENTRY + 0xf00
COUNT = STATE + 16
ACTIVE = STATE + 20
VALID = STATE + 24
DATA = 0x1deb000
CAPACITY = 1024
RECORD_SIZE = 36
END = DATA + CAPACITY * RECORD_SIZE
MAIN_CAMERA = 0x38fb24
MAIN_CANVAS = 0x9c34e8
COORD_LIMIT = 8192
RENDER_SITE = 0x29edb4
PART_SITE = 0x2f717e
ORIGINAL_RENDER = 0x9d6000
RESERVATIONS = ((RECT_ENTRY, RECT_ENTRY + 0x1000), (MARKER_ENTRY, END))


class Profile(Enum):
    """Define logical size, world size and selection distance for each renderer.

    These profiles match fixed buffer layouts. Quad-click Y uses multiplication,
    signed floor or nonnegative ceiling according to the profile. Rectangle edges
    round down even for negative coordinates beyond the screen.
    """
    HUD200 = (320, 200, 800, 600, 2501)
    HUD400 = (320, 400, 800, 600, 2501)
    HD960 = (320, 400, 1280, 960, 6401)


def require_profile(profile):
    if not isinstance(profile, Profile):
        raise ValueError('Unsupported target renderer profile')
    return profile


def click_scale(profile):
    require_profile(profile)
    if profile is Profile.HUD200:
        return 'imul eax,eax,5;sar eax,1;', 'imul eax,eax,3;'
    if profile is Profile.HUD400:
        return 'imul eax,eax,5;sar eax,1;', 'imul eax,eax,3;sar eax,1;'
    # Preserve the accepted nonnegative ceil sequence and its temporary saves.
    # Real click coordinates have already been clipped by the UI dispatcher.
    return 'shl eax,2;', (
        'push eax;push ecx;push edx;mov eax,eax;imul eax,eax,12;'
        'add eax,4;xor edx,edx;mov ecx,5;div ecx;mov [esp+8],eax;pop edx;pop ecx;pop eax;'
    )


def rectangle_source(profile):
    """Physical inclusive target rectangles -> logical HUD, in-place at ESI.

    This has the original converter ABI (EAX/EBX/EDX scratch). Signed IDIV
    truncates toward zero; a negative remainder decrements to mathematical floor.
    """
    require_profile(profile)
    xd, yd = (4, 12) if profile is Profile.HD960 else (5, 3)
    xs = '' if profile is Profile.HD960 else 'add eax,eax;'
    ys = {
        Profile.HUD200: '',
        Profile.HUD400: 'add eax,eax;',
        Profile.HD960: 'imul eax,eax,5;'
    }[profile]
    return (
        f"mov ebx,{xd};"
        f"\n    movsx eax,word ptr [esi];"
        f"{xs}cdq;"
        f"idiv ebx;"
        f"test edx,edx;"
        f"jns x0;"
        f"dec eax;"
        f"\n    x0:mov word ptr [esi],ax;"
        f"\n    movsx eax,word ptr [esi+4];"
        f"{xs}cdq;"
        f"idiv ebx;"
        f"test edx,edx;"
        f"jns x1;"
        f"dec eax;"
        f"\n    x1:mov word ptr [esi+4],ax;"
        f"mov ebx,{yd};"
        f"\n    movsx eax,word ptr [esi+2];"
        f"{ys}cdq;"
        f"idiv ebx;"
        f"test edx,edx;"
        f"jns y0;"
        f"dec eax;"
        f"\n    y0:mov word ptr [esi+2],ax;"
        f"\n    movsx eax,word ptr [esi+6];"
        f"{ys}cdq;"
        f"idiv ebx;"
        f"test edx,edx;"
        f"jns y1;"
        f"dec eax;"
        f"\n    y1:mov word ptr [esi+6],ax;"
        f"ret;"
    )


def rectangle_code(asm):
    # Entry is after the original mode/map branch and stack-frame setup. The
    # packed click is at original ESP+12; target ID is at original ESP+16.
    # Locals: best ID, 64-bit best distance, x/y, camera q8 xyz, current distance.
    code = (
        f"pushfd;"
        f"pushad;"
        f"sub esp,40;"
        f"\n inc dword ptr [{RECT_STATE}];"
        f"\n mov dword ptr [esp],0;"
        f"mov dword ptr [esp+4],-1;"
        f"mov dword ptr [esp+8],-1;"
        f"\n movsx eax,word ptr [esp+88];"
        f"mov [esp+12],eax;"
        f"\n movsx eax,word ptr [esp+90];"
        f"mov [esp+16],eax;"
        f"\n mov eax,[0x38fab8];"
        f"sar eax,8;"
        f"mov [esp+20],eax;"
        f"\n mov eax,[0x38fabc];"
        f"sar eax,8;"
        f"mov [esp+24],eax;"
        f"\n mov eax,[0x38fac0];"
        f"sar eax,8;"
        f"mov [esp+28],eax;"
        f"\n mov ecx,[0x35bf80];"
        f"test ecx,ecx;"
        f"jle fallback;"
        f"cmp ecx,64;"
        f"ja fallback;"
        f"\n mov esi,0x397ca0;"
        f"\n scan:mov eax,[esp+12];"
        f"movsx edx,word ptr [esi];"
        f"cmp eax,edx;"
        f"jl next;"
        f"\n movsx edx,word ptr [esi+4];"
        f"cmp eax,edx;"
        f"jg next;"
        f"\n mov eax,[esp+16];"
        f"movsx edx,word ptr [esi+2];"
        f"cmp eax,edx;"
        f"jl next;"
        f"\n movsx edx,word ptr [esi+6];"
        f"cmp eax,edx;"
        f"jg next;"
        f"\n movsx ebp,word ptr [esi+8];"
        f"test ebp,ebp;"
        f"jle next;"
        f"\n imul ebx,ebp,37;"
        f"add ebx,0x3c3240;"
        f"\n movzx eax,byte ptr [ebx+1];"
        f"test eax,eax;"
        f"jz static_type;"
        f"cmp eax,4;"
        f"ja next;"
        f"jmp eligible;"
        f"\n static_type:movzx eax,byte ptr [ebx+2];"
        f"lea eax,[eax+eax*2];"
        f"cmp byte ptr [eax+0x3960c4],0;"
        f"je next;"
        f"\n eligible:mov dword ptr [esp+32],0;"
        f"mov dword ptr [esp+36],0;"
    )
    # q8 differences stay within signed 25 bits over the full signed q16 input
    # range. Full 64-bit squares avoid overflow while retaining subpixel-scale
    # world precision. Queue iteration breaks exact distance ties as before.
    for obj_offset, cam_offset in ((15, 20), (19, 24), (23, 28)):
        code += (
            f"mov eax,[ebx+{obj_offset}];"
            f"sar eax,8;"
            f"sub eax,[esp+{cam_offset}];"
            f"\n  imul eax;"
            f"add [esp+32],eax;"
            f"adc [esp+36],edx;"
        )
    code += (
        f"mov edx,[esp+36];"
        f"cmp edx,[esp+8];"
        f"ja next;"
        f"jb better;"
        f"\n mov eax,[esp+32];"
        f"cmp eax,[esp+4];"
        f"jae next;"
        f"\n better:mov [esp],ebp;"
        f"mov eax,[esp+32];"
        f"mov [esp+4],eax;"
        f"mov eax,[esp+36];"
        f"mov [esp+8],eax;"
        f"\n next:add esi,10;"
        f"dec ecx;"
        f"jnz scan;"
        f"\n mov eax,[esp];"
        f"test eax,eax;"
        f"jz fallback;"
        f"\n mov [esp+92],ax;"
        f"mov [{RECT_STATE+8}],eax;"
        f"inc dword ptr [{RECT_STATE+4}];"
        f"\n add esp,40;"
        f"popad;"
        f"popfd;"
        f"jmp 0x26a103;"
        f"\n fallback:inc dword ptr [{RECT_STATE+12}];"
        f"add esp,40;"
        f"popad;"
        f"popfd;"
        f"\n mov ebx,[0x35bf80];"
        f"jmp 0x269f53;"
    )
    body = asm(RECT_ENTRY, code)
    assert len(body) < 0xf00
    return body


def marker_code(asm):
    # Use the common picker entry contract and the original sensor color and torso
    # projection routines used by the HUD, including its five-pixel corners.
    # Locals: best ID/score/depth, click x/y, projected x/y, score/depth scratch.
    code = (
        f"pushfd;"
        f"pushad;"
        f"sub esp,44;"
        f"\n inc dword ptr [{MARKER_STATE}];"
        f"mov dword ptr [esp],0;"
        f"\n mov dword ptr [esp+4],-1;"
        f"mov dword ptr [esp+8],-1;"
        f"mov dword ptr [esp+12],-1;"
        f"\n movsx eax,word ptr [esp+92];"
        f"mov [esp+16],eax;"
        f"\n movsx eax,word ptr [esp+94];"
        f"mov [esp+20],eax;"
        f"\n mov ecx,[0x35bf80];"
        f"test ecx,ecx;"
        f"jle fallback;"
        f"cmp ecx,64;"
        f"ja fallback;"
        f"\n mov esi,0x397ca0;"
        f"\n scan:movzx ebp,word ptr [esi+8];"
        f"test ebp,ebp;"
        f"jz next;"
        f"cmp ebp,264;"
        f"ja next;"
        f"\n imul eax,ebp,37;"
        f"cmp byte ptr [eax+0x3c3240],0;"
        f"je next;"
        f"\n cmp byte ptr [eax+0x3c3241],1;"
        f"jne next;"
        f"\n mov eax,[0x441350];"
        f"shr eax,16;"
        f"imul eax,eax,0x582;"
        f"add eax,0x3a56ba;"
        f"\n mov edx,ebp;"
        f"call 0x27d458;"
        f"test al,al;"
        f"jz next;"
        f"\n mov eax,ebp;"
        f"lea edx,[esp+24];"
        f"lea ebx,[esp+28];"
        f"call 0x27eaf4;"
        f"\n mov eax,[esp+24];"
        f"sar eax,16;"
        f"sub eax,[esp+16];"
        f"cmp eax,-5;"
        f"jl next;"
        f"cmp eax,5;"
        f"jg next;"
        f"\n imul eax,eax;"
        f"imul eax,eax,25;"
        f"mov [esp+32],eax;"
        f"\n mov eax,[esp+20];"
        f"mov edx,[esp+28];"
        f"sar edx,16;"
        f"sub eax,edx;"
        f"\n cmp byte ptr [0x35a540],2;"
        f"jb normal_height;"
        f"\n cmp eax,-9;"
        f"jl next;"
        f"cmp eax,8;"
        f"jg next;"
        f"jmp score;"
        f"\n normal_height:cmp eax,-5;"
        f"jl next;"
        f"cmp eax,5;"
        f"jg next;"
        f"\n score:imul eax,eax;"
        f"imul eax,eax,36;"
        f"add eax,[esp+32];"
        f"mov [esp+32],eax;"
        f"\n cmp eax,[esp+4];"
        f"ja next;"
        f"\n imul ebx,ebp,37;"
        f"add ebx,0x3c3240;"
        f"\n mov dword ptr [esp+36],0;"
        f"mov dword ptr [esp+40],0;"
    )
    for offset, camera in ((15, 0x38fab8), (19, 0x38fabc), (23, 0x38fac0)):
        code += (
            f"mov eax,[ebx+{offset}];"
            f"sar eax,8;"
            f"mov edx,[{camera}];"
            f"sar edx,8;"
            f"sub eax,edx;"
            f"\n  imul eax;"
            f"add [esp+36],eax;"
            f"adc [esp+40],edx;"
        )
    code += (
        f"mov eax,[esp+32];"
        f"cmp eax,[esp+4];"
        f"jb better;"
        f"\n mov eax,[esp+40];"
        f"cmp eax,[esp+12];"
        f"ja next;"
        f"jb better;"
        f"\n mov eax,[esp+36];"
        f"cmp eax,[esp+8];"
        f"jae next;"
        f"\n better:mov [esp],ebp;"
        f"mov eax,[esp+32];"
        f"mov [esp+4],eax;"
        f"\n mov eax,[esp+36];"
        f"mov [esp+8],eax;"
        f"mov eax,[esp+40];"
        f"mov [esp+12],eax;"
        f"\n next:add esi,10;"
        f"dec ecx;"
        f"jnz scan;"
        f"\n mov eax,[esp];"
        f"test eax,eax;"
        f"jz fallback;"
        f"\n mov [esp+96],ax;"
        f"inc dword ptr [{MARKER_STATE+4}];"
        f"mov [{MARKER_STATE+8}],eax;"
        f"\n add esp,44;"
        f"popad;"
        f"popfd;"
        f"jmp 0x26a103;"
        f"\n fallback:inc dword ptr [{MARKER_STATE+12}];"
        f"add esp,44;"
        f"popad;"
        f"popfd;"
        f"jmp {RECT_ENTRY};"
    )
    body = asm(MARKER_ENTRY, code)
    assert len(body) < 0xf00
    return body


def quad_source(profile=Profile.HUD200):
    require_profile(profile)
    x_scale, y_scale = click_scale(profile)
    score_limit = profile.value[4]
    # Distances use physical display pixels, so horizontal and vertical units
    # match despite the original 320x200 game's non-square logical pixels.
    code = (
        f"pushfd;"
        f"pushad;"
        f"sub esp,48;"
        f"\n inc dword ptr [{STATE}];"
        f"mov dword ptr [esp],0;"
        f"mov dword ptr [esp+4],{score_limit};"
        f"\n mov dword ptr [esp+8],-1;"
        f"mov dword ptr [esp+12],-1;"
        f"\n cmp dword ptr [{VALID}],1;"
        f"jne fallback;"
        f"\n mov ecx,[{COUNT}];"
        f"test ecx,ecx;"
        f"jle fallback;"
        f"cmp ecx,{CAPACITY};"
        f"ja fallback;"
        f"\n movsx eax,word ptr [esp+96];"
        f"{x_scale}mov [esp+16],eax;"
        f"\n movsx eax,word ptr [esp+98];"
        f"{y_scale}mov [esp+20],eax;"
        f"\n mov esi,{DATA};"
        f"\n scan:mov ebp,[esi+32];"
        f"test ebp,ebp;"
        f"jz next;"
        f"cmp ebp,264;"
        f"ja next;"
        f"\n imul ebx,ebp,37;"
        f"add ebx,0x3c3240;"
        f"\n cmp byte ptr [ebx],0;"
        f"je next;"
        f"cmp byte ptr [ebx+1],1;"
        f"jne next;"
        f"\n push ecx;"
        f"push esi;"
        f"\n mov ecx,[0x35bf80];"
        f"test ecx,ecx;"
        f"jle absent;"
        f"cmp ecx,64;"
        f"ja absent;"
        f"\n mov edi,0x397ca0;"
        f"\n queued:cmp [edi+8],bp;"
        f"je present;"
        f"add edi,10;"
        f"dec ecx;"
        f"jnz queued;"
        f"\n absent:pop esi;"
        f"pop ecx;"
        f"jmp next;"
        f"\n present:pop esi;"
        f"pop ecx;"
        f"\n mov eax,[esp+16];"
        f"mov ebx,[esp+20];"
        f"call {DIST};"
        f"\n cmp eax,[esp+4];"
        f"ja next;"
        f"mov [esp+24],eax;"
        f"\n imul ebx,ebp,37;"
        f"add ebx,0x3c3240;"
        f"\n mov dword ptr [esp+28],0;"
        f"mov dword ptr [esp+32],0;"
    )
    for off, cam in ((15, 0x38fab8), (19, 0x38fabc), (23, 0x38fac0)):
        code += (
            f"mov eax,[ebx+{off}];"
            f"sar eax,8;"
            f"mov edx,[{cam}];"
            f"sar edx,8;"
            f"sub eax,edx;"
            f"\n  imul eax;"
            f"add [esp+28],eax;"
            f"adc [esp+32],edx;"
        )
    code += (
        f"mov eax,[esp+24];"
        f"cmp eax,[esp+4];"
        f"jb better;"
        f"\n mov eax,[esp+32];"
        f"cmp eax,[esp+12];"
        f"ja next;"
        f"jb better;"
        f"\n mov eax,[esp+28];"
        f"cmp eax,[esp+8];"
        f"jae next;"
        f"\n better:mov [esp],ebp;"
        f"mov eax,[esp+24];"
        f"mov [esp+4],eax;"
        f"\n mov eax,[esp+28];"
        f"mov [esp+8],eax;"
        f"mov eax,[esp+32];"
        f"mov [esp+12],eax;"
        f"\n next:add esi,{RECORD_SIZE};"
        f"dec ecx;"
        f"jnz scan;"
        f"\n cmp dword ptr [esp],0;"
        f"je fallback;"
        f"\n mov ecx,[0x35bf80];"
        f"test ecx,ecx;"
        f"jle chosen;"
        f"cmp ecx,64;"
        f"ja fallback;"
        f"mov esi,0x397ca0;"
        f"\n blockers:movzx ebp,word ptr [esi+8];"
        f"test ebp,ebp;"
        f"jz next_block;"
        f"cmp ebp,264;"
        f"ja next_block;"
        f"\n imul ebx,ebp,37;"
        f"add ebx,0x3c3240;"
        f"\n cmp byte ptr [ebx],0;"
        f"je next_block;"
        f"\n movzx eax,byte ptr [ebx+1];"
        f"cmp eax,1;"
        f"je next_block;"
        f"cmp eax,4;"
        f"ja next_block;"
        f"\n test eax,eax;"
        f"jnz blocker_rect;"
        f"movzx eax,byte ptr [ebx+2];"
        f"lea eax,[eax+eax*2];"
        f"cmp byte ptr [eax+0x3960c4],0;"
        f"je next_block;"
        f"\n blocker_rect:movsx eax,word ptr [esp+96];"
        f"cmp ax,[esi];"
        f"jl next_block;"
        f"cmp ax,[esi+4];"
        f"jg next_block;"
        f"\n movsx eax,word ptr [esp+98];"
        f"cmp ax,[esi+2];"
        f"jl next_block;"
        f"cmp ax,[esi+6];"
        f"jg next_block;"
        f"\n cmp dword ptr [esp+4],0;"
        f"jne fallback;"
        f"\n mov dword ptr [esp+28],0;"
        f"mov dword ptr [esp+32],0;"
    )
    for off, cam in ((15, 0x38fab8), (19, 0x38fabc), (23, 0x38fac0)):
        code += (
            f"mov eax,[ebx+{off}];"
            f"sar eax,8;"
            f"mov edx,[{cam}];"
            f"sar edx,8;"
            f"sub eax,edx;"
            f"\n  imul eax;"
            f"add [esp+28],eax;"
            f"adc [esp+32],edx;"
        )
    code += (
        f"mov eax,[esp+32];"
        f"cmp eax,[esp+12];"
        f"jb fallback;"
        f"ja next_block;"
        f"\n mov eax,[esp+28];"
        f"cmp eax,[esp+8];"
        f"jbe fallback;"
        f"\n next_block:add esi,10;"
        f"dec ecx;"
        f"jnz blockers;"
        f"\n chosen:mov eax,[esp];"
        f"mov [esp+100],ax;"
        f"mov [{STATE+8}],eax;"
        f"inc dword ptr [{STATE+4}];"
        f"\n add esp,48;"
        f"popad;"
        f"popfd;"
        f"jmp 0x26a103;"
        f"\n fallback:inc dword ptr [{STATE+12}];"
        f"add esp,48;"
        f"popad;"
        f"popfd;"
        f"jmp {MARKER_ENTRY};"
    )
    return code


def render_source(renderer=ORIGINAL_RENDER):
    return (
        f"pushfd;"
        f"cmp edx,{MAIN_CAMERA};"
        f"jne other;"
        f"\n mov dword ptr [{COUNT}],0;"
        f"mov dword ptr [{VALID}],0;"
        f"mov dword ptr [{ACTIVE}],1;"
        f"\n popfd;"
        f"call {renderer};"
        f"pushfd;"
        f"mov dword ptr [{ACTIVE}],0;"
        f"mov dword ptr [{VALID}],1;"
        f"popfd;"
        f"ret;"
        f"\n other:popfd;"
        f"jmp {renderer};"
    )


def quad_bodies(asm, *, profile=Profile.HUD200, entry=ENTRY, renderer=ORIGINAL_RENDER):
    pick = asm(entry, quad_source(profile))
    assert len(pick) < 0x600
    # Squared point-to-convex-quad distance. All intermediates are integers;
    # the cross-product square uses full 64-bit multiplication/division.
    distance = asm(
        DIST, (
            "pushad;"
            "sub esp,48;"
            "\n mov [esp],eax;"
            "mov [esp+4],ebx;"
            "mov dword ptr [esp+8],0x7fffffff;"
            "\n mov dword ptr [esp+12],0;"
            "mov dword ptr [esp+16],0;"
            "\n edge:mov ecx,[esp+16];"
            "lea edi,[esi+ecx*8];"
            "inc ecx;"
            "and ecx,3;"
            "lea ebp,[esi+ecx*8];"
            "\n mov eax,[ebp];"
            "sub eax,[edi];"
            "mov [esp+20],eax;"
            "\n mov eax,[ebp+4];"
            "sub eax,[edi+4];"
            "mov [esp+24],eax;"
            "\n mov eax,[esp];"
            "sub eax,[edi];"
            "mov [esp+28],eax;"
            "\n mov eax,[esp+4];"
            "sub eax,[edi+4];"
            "mov [esp+32],eax;"
            "\n mov eax,[esp+20];"
            "imul eax,eax;"
            "mov ebx,[esp+24];"
            "imul ebx,ebx;"
            "add eax,ebx;"
            "mov [esp+36],eax;"
            "\n mov eax,[esp+28];"
            "imul eax,[esp+24];"
            "mov edx,[esp+32];"
            "imul edx,[esp+20];"
            "sub eax,edx;"
            "\n test eax,eax;"
            "jz cross_done;"
            "jg positive;"
            "or dword ptr [esp+12],1;"
            "jmp cross_done;"
            "\n positive:or dword ptr [esp+12],2;"
            "\n cross_done:mov [esp+40],eax;"
            "\n mov eax,[esp+28];"
            "imul eax,[esp+20];"
            "mov edx,[esp+32];"
            "imul edx,[esp+24];"
            "add eax,edx;"
            "\n test eax,eax;"
            "jle endpoint_a;"
            "cmp eax,[esp+36];"
            "jge endpoint_b;"
            "\n mov eax,[esp+40];"
            "imul eax;"
            "div dword ptr [esp+36];"
            "jmp score;"
            "\n endpoint_b:mov eax,[esp];"
            "sub eax,[ebp];"
            "mov edx,[esp+4];"
            "sub edx,[ebp+4];"
            "jmp square;"
            "\n endpoint_a:mov eax,[esp+28];"
            "mov edx,[esp+32];"
            "\n square:imul eax,eax;"
            "imul edx,edx;"
            "add eax,edx;"
            "\n score:cmp eax,[esp+8];"
            "jae following;"
            "mov [esp+8],eax;"
            "\n following:inc dword ptr [esp+16];"
            "cmp dword ptr [esp+16],4;"
            "jb edge;"
            "\n mov eax,[esp+8];"
            "mov edx,[esp+12];"
            "test edx,edx;"
            "jz done;"
            "cmp edx,3;"
            "je done;"
            "xor eax,eax;"
            "\n done:mov [esp+76],eax;"
            "add esp,48;"
            "popad;"
            "ret;"
        )
    )
    assert len(distance) < 0x300
    render = asm(RENDER, render_source(renderer))
    # ESP on entry is the original routine's first vertex. Copy only during
    # the primary high-resolution view, never teammate/reflection canvases.
    part = asm(
        PART, (
            f"pushfd;"
            f"pushad;"
            f"\n cmp dword ptr [{ACTIVE}],1;"
            f"jne done;"
            f"\n cmp dword ptr [0x44b1a0],{MAIN_CANVAS};"
            f"jne done;"
            f"\n mov ecx,[{COUNT}];"
            f"cmp ecx,{CAPACITY};"
            f"jae overflow;"
            f"\n movzx ebp,word ptr [0x420154];"
            f"test ebp,ebp;"
            f"jz done;"
            f"cmp ebp,264;"
            f"ja done;"
            f"\n imul eax,ebp,37;"
            f"cmp byte ptr [eax+0x3c3241],1;"
            f"jne done;"
            f"\n imul edi,ecx,{RECORD_SIZE};"
            f"add edi,{DATA};"
            f"lea esi,[esp+36];"
            f"mov ecx,4;"
            f"\n copy:mov eax,[esi];"
            f"sar eax,16;"
            f"cmp eax,{-COORD_LIMIT};"
            f"jl done;"
            f"cmp eax,{COORD_LIMIT};"
            f"jg done;"
            f"mov [edi],eax;"
            f"\n mov eax,[esi+4];"
            f"sar eax,16;"
            f"cmp eax,{-COORD_LIMIT};"
            f"jl done;"
            f"cmp eax,{COORD_LIMIT};"
            f"jg done;"
            f"mov [edi+4],eax;"
            f"\n add edi,8;"
            f"add esi,24;"
            f"dec ecx;"
            f"jnz copy;"
            f"\n mov [edi],ebp;"
            f"inc dword ptr [{COUNT}];"
            f"jmp done;"
            f"\n overflow:mov dword ptr [{COUNT}],{CAPACITY+1};"
            f"\n done:popad;"
            f"popfd;"
            f"mov eax,[0x44b1a0];"
            f"jmp {PART_SITE+5};"
        )
    )
    assert len(render) < 0x100 and len(part) < 0x500
    return [(entry, pick), (DIST, distance), (RENDER, render), (PART, part)]


def bodies(asm=default_asm):
    return [(RECT_ENTRY, rectangle_code(asm)), (MARKER_ENTRY, marker_code(asm)), *quad_bodies(asm)]


def hooks(asm=default_asm):
    return [
        (SITE, asm(SITE, f'jmp {ENTRY}') + b'\x90', ORIGINAL),
        (
            RENDER_SITE, asm(RENDER_SITE,
                             f'jmp {RENDER}'), asm(RENDER_SITE, f'jmp {ORIGINAL_RENDER}')
        ), (PART_SITE, asm(PART_SITE, f'jmp {PART}'), asm(PART_SITE, 'mov eax,[0x44b1a0]'))
    ]


def install(write, ram, asm=default_asm):
    """Check all hooks and storage before installing the base selection helpers.

    The image must have the original hook state and an empty selection cache.
    The renderer installs its corresponding resolution profile separately.
    """
    payloads = bodies(asm)
    edits = hooks(asm)
    for a, b, old in edits:
        assert bytes(ram[a:a + len(old)]) == old, (hex(a), 'unexpected target hook')
    for start, end in RESERVATIONS:
        assert not any(ram[start:end]), (hex(start), 'target reservation occupied')
    pieces = payloads + [(a, b) for a, b, _ in edits]
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces], capacity=CAPACITY)


# Guard target-label compound resources and supply the demo's custom names.
from patch_support import asm

NAMES_CODE = 0x1e3a200

NAMES_END = 0x1e3b000

NAMES_TEXT = NAMES_CODE + 0x400

NAMES_TABLE = NAMES_TEXT + 0x100

NAMES_SITE = 0x26a79e

NAMES_SITES = {NAMES_SITE: asm(NAMES_SITE, 'call 0x2e3194')}

NAMES_NAMES = (
    b'Storage Dome', b'Prefabricated Building', b'Pirate Hovercraft', b'Pirate Transport', b'BUG'
)


def names_bodies():
    raw = bytearray(b'Unknown Object\0')
    pointers = []
    for name in NAMES_NAMES:
        pointers.append(NAMES_TEXT + len(raw))
        raw += name + b'\0'
    assert len(raw) < 0x100
    code = asm(
        NAMES_CODE, (
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"\n    mov ebx,eax;"
            f"mov ecx,eax;"
            f"shr ecx,16;"
            f"\n    cmp ecx,0x177;"
            f"jne ordinary;"
            f"\n    cmp dword ptr [0x2448c7],0x1ef6800;"
            f"jne ordinary;"
            f"\n    movzx edx,bx;"
            f"sub edx,25;"
            f"cmp edx,4;"
            f"ja ordinary;"
            f"\n    mov eax,[edx*4+{NAMES_TABLE}];"
            f"jmp done;"
            f"\n    ordinary:cmp ecx,0x16c;"
            f"je valid;"
            f"cmp ecx,0x177;"
            f"je valid;"
            f"\n    cmp ecx,0x17d;"
            f"jb bad;"
            f"cmp ecx,0x181;"
            f"ja bad;"
            f"\n    valid:mov edx,ecx;"
            f"shl edx,4;"
            f"add edx,[0x446be8];"
            f"\n    mov ebp,[edx+4];"
            f"shr ebp,8;"
            f"cmp ebp,6;"
            f"jb bad;"
            f"\n    cmp ebp,0x100000;"
            f"ja bad;"
            f"\n    and eax,0xffff0000;"
            f"call 0x2e3194;"
            f"\n    mov esi,[edx];"
            f"cmp esi,0x11000;"
            f"jb bad;"
            f"\n    mov eax,esi;"
            f"add eax,ebp;"
            f"jc bad;"
            f"cmp eax,0x2000000;"
            f"ja bad;"
            f"\n    movzx ecx,word ptr [esi];"
            f"movzx edx,bx;"
            f"cmp edx,ecx;"
            f"jae bad;"
            f"\n    lea edi,[ecx*4+6];"
            f"cmp edi,ebp;"
            f"ja bad;"
            f"\n    mov eax,[esi+edx*4+2];"
            f"cmp eax,edi;"
            f"jb bad;"
            f"\n    mov ecx,[esi+edx*4+6];"
            f"cmp ecx,ebp;"
            f"ja bad;"
            f"cmp eax,ecx;"
            f"jae bad;"
            f"\n    sub ecx,eax;"
            f"add eax,esi;"
            f"mov edi,eax;"
            f"\n    scan:cmp byte ptr [edi],0;"
            f"je done;"
            f"inc edi;"
            f"dec ecx;"
            f"jnz scan;"
            f"\n    bad:mov eax,{NAMES_TEXT};"
            f"\n    done:pop ebp;"
            f"pop edi;"
            f"pop esi;"
            f"pop edx;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    assert len(code) < 0x400
    return [
        (NAMES_CODE, code), (NAMES_TEXT, bytes(raw)), (NAMES_TABLE, struct.pack('<5I', *pointers)),
        (NAMES_SITE, asm(NAMES_SITE, f'call {NAMES_CODE}'))
    ]


def names_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        names_bodies(),
        NAMES_SITES,
        write,
        read,
        cold_state=((NAMES_CODE, NAMES_END - NAMES_CODE), )
    )


def names_verify(read):
    from features.input_views import _verify
    return _verify(names_bodies(), read)


# These helpers share the final Options reservation. Selection has its own
# preference, but its small cache fits inside the existing restored UI block.
from features.option_contracts import PICK, AI
PREFERENCE_GATE = 0x1d35b00
LEGACY_PICK = 0x1d35c00
IMPROVED_DISPATCH = 0x1e41040


def preference_bodies(labels):
    """Offer the original rectangle-centre policy without undoing HUD scaling.

    Original selection allows overlapping objects and chooses the centre nearest
    the click, with a twenty-pixel margin. It does not reject a drone because a
    building is closer to the camera. The current mode retains all quad, marker
    and depth checks. Both feed the unchanged selection/lock continuation.
    """
    out = []

    def emit(a, code, size):
        body = default_asm(a, code)
        assert len(body) <= size, (hex(a), len(body), size)
        out.append((a, body))

    emit(PICK.init, f"""
        pushfd; pushad;
        cmp dword ptr [{PICK.state}],1; je done;
        call {AI.init}; cmp dword ptr [{AI.state}],1; jne done;
        push {AI.state+64}; push 1; push {labels['pkey']}; push {labels['section']};
        call dword ptr [{AI.state+16}]; and eax,1;
        mov [{PICK.state+4}],eax; mov dword ptr [{PICK.state}],1;
        done: popad; popfd; ret;
    """, 0x100)
    emit(PICK.save, f"""
        pushfd; pushad; call {PICK.init};
        cmp dword ptr [{PICK.state}],1; jne done;
        mov eax,[{PICK.state+8}]; mov [{PICK.state+4}],eax;
        mov edx,{labels['zero']}; test eax,eax; jz value;
        mov edx,{labels['one']};
        value: push {AI.state+64}; push edx; push {labels['pkey']}; push {labels['section']};
        call dword ptr [{AI.state+20}]; done: popad; popfd; ret;
    """, 0x100)
    emit(PREFERENCE_GATE, f"""
        pushfd; call {PICK.init};
        cmp dword ptr [{PICK.state}],1; jne improved;
        cmp dword ptr [{PICK.state+4}],0; jne improved;
        popfd; jmp {LEGACY_PICK};
        improved: popfd; jmp {IMPROVED_DISPATCH};
    """, 0x100)
    # Local values: click x/y, best score/id, current centre x/y, HUD y shift.
    # The saved prologue's click/target are 76/80 bytes above this local frame.
    emit(LEGACY_PICK, f"""
        pushfd; pushad; sub esp,28;
        xor ecx,ecx;
        cmp dword ptr [0x446f80],0x1900140; sete cl;
        mov [esp+24],ecx;
        movsx eax,word ptr [esp+76]; mov [esp],eax;
        movsx eax,word ptr [esp+78]; sar eax,cl; mov [esp+4],eax;
        mov dword ptr [esp+8],0x7fffffff; mov dword ptr [esp+12],0;
        mov edi,[0x35bf80]; test edi,edi; jle done; cmp edi,64; ja done;
        mov esi,0x397ca0;
        scan: movsx ebp,word ptr [esi+8]; test ebp,ebp; jle next;
        cmp ebp,1024; jae next;
        imul ebx,ebp,37; movzx eax,byte ptr [ebx+0x3c3241];
        test eax,eax; jz static_type; cmp eax,4; ja next; jmp bounds;
        static_type: movzx eax,byte ptr [ebx+0x3c3242]; lea eax,[eax+eax*2];
        cmp byte ptr [eax+0x3960c4],0; je next;
        bounds: movsx eax,word ptr [esi]; movsx edx,word ptr [esi+4];
        lea ebx,[eax-20]; cmp [esp],ebx; jle next;
        lea ebx,[edx+20]; cmp [esp],ebx; jge next;
        add eax,edx; cdq; sub eax,edx; sar eax,1; mov [esp+16],eax;
        mov ecx,[esp+24]; movsx eax,word ptr [esi+2]; sar eax,cl;
        movsx edx,word ptr [esi+6]; sar edx,cl;
        lea ebx,[eax-20]; cmp [esp+4],ebx; jle next;
        lea ebx,[edx+20]; cmp [esp+4],ebx; jge next;
        add eax,edx; cdq; sub eax,edx; sar eax,1;
        sub eax,[esp+4]; imul eax,eax;
        mov edx,[esp+16]; sub edx,[esp]; imul edx,edx; add eax,edx;
        cmp eax,[esp+8]; jge next;
        mov [esp+8],eax; mov [esp+12],ebp;
        next: add esi,10; dec edi; jnz scan;
        done: mov eax,[esp+12]; mov [esp+80],ax;
        add esp,28; popad; popfd; jmp 0x26a103;
    """, 0x400)
    out.append((SITE, default_asm(SITE, f'jmp {PREFERENCE_GATE}') + b'\x90'))
    return out
