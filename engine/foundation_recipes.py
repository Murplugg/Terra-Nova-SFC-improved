"""Build the foundation routines for navigation, targeting and display.

Addresses here belong to the DOS image before relocation. Navigation prologues
repeat displaced original instructions, and map coordinates follow the original
calculation. Fixed helper slots also preserve the expected image layout. The
native host redirects the S3 video-port path before the game runs on Windows.
"""
import struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
from foundation_cursor import cursor
from foundation_hud import hud


def branch(a, b):
    return b'\xe9' + struct.pack('<i', b - a - 5)


def navigation_coordinates():
    """Refresh map guides from live world coordinates before each draw."""
    ENTRY = 0x9b20e8
    REFRESH = 0x9b22e8
    RECOVER = 0x9b26e8
    STATS = 0x9b2ae8
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    asm = lambda a, s: bytes(ks.asm(s, addr=a)[0])
    entry = asm(
        ENTRY, (
            f"\n call {REFRESH};"
            f"\n push ebx;"
            f" push ecx;"
            f" push edx;"
            f" push esi;"
            f" push edi;"
            f"\n jmp 0x261c61;"
            f"\n "
        )
    )
    # Reproduce the game's marker-to-map calculation without drawing the marker.
    # Fetch the live context through the map pane's view index, just as its draw
    # callback does. Every guide draw starts from world coordinates, not the prior
    # screen coordinate that the map callback can repeatedly offset.
    refresh = asm(
        REFRESH, (
            f"\n pushfd;"
            f" pushad;"
            f"\n mov edi,dword ptr [0x389dfc];"
            f"\n movzx eax,byte ptr [edi+0x21];"
            f" shl eax,5;"
            f"\n mov esi,dword ptr [eax+0x38fc20];"
            f"\n test esi,esi;"
            f" jz done;"
            f"\n mov eax,dword ptr [0x38fff0];"
            f" sub eax,dword ptr [esi];"
            f"\n imul dword ptr [esi+0xe];"
            f" shrd eax,edx,16;"
            f" sar eax,16;"
            f"\n movsx edx,word ptr [edi+8];"
            f" add eax,edx;"
            f"\n mov dword ptr [0x390300],eax;"
            f"\n mov eax,dword ptr [0x38fff4];"
            f" sub eax,dword ptr [esi+4];"
            f"\n mov cl,byte ptr [0x35a544];"
            f" shl eax,cl;"
            f"\n imul dword ptr [esi+0xe];"
            f" shrd eax,edx,16;"
            f" sar eax,16;"
            f"\n movsx edx,word ptr [edi+10];"
            f" add eax,edx;"
            f"\n mov dword ptr [0x390304],eax;"
            f"\n inc dword ptr [{STATS}];"
            f"\n done: popad;"
            f" popfd;"
            f" ret;"
            f"\n "
        )
    )
    # Retained recovery slot for the navigation clipper. The outcode classifier
    # returns here with ESP at the clipper's ordinary local frame. Restore its
    # working endpoint and direction, then restart its classification loop.
    recover = asm(
        RECOVER, (
            f"\n call {REFRESH};"
            f"\n mov esi,dword ptr [esp+8];"
            f"\n mov eax,dword ptr [0x390300];"
            f" sub eax,2;"
            f" shl eax,16;"
            f" or ah,0x80;"
            f"\n mov dword ptr [esi],eax;"
            f"\n mov eax,dword ptr [0x390304];"
            f" sub eax,2;"
            f" shl eax,16;"
            f" or ah,0x80;"
            f"\n mov dword ptr [esi+4],eax;"
            f"\n mov eax,dword ptr [esp+12];"
            f"\n mov ebp,dword ptr [esi];"
            f" sub ebp,dword ptr [eax];"
            f"\n mov edi,dword ptr [esi+4];"
            f" sub edi,dword ptr [eax+4];"
            f"\n inc dword ptr [{STATS+4}];"
            f" jmp 0x313d53;"
            f"\n "
        )
    )
    hook = b'\xe9' + struct.pack('<i', ENTRY - 0x261c5c - 5)
    assert len(entry) < 0x200 and len(refresh) < 0x400 and len(recover) < 0x400
    return [(ENTRY, entry), (REFRESH, refresh), (RECOVER, recover), (0x261c5c, hook)]


def allocation_guard():
    """Rearm buffer tracking only after the original allocator succeeds."""
    ALLOC = 0x9b40e8
    TRACK = 0x9aa1e8
    SITES = (0x261578, 0x262f6d, 0x263043)
    k = Ks(KS_ARCH_X86, KS_MODE_32)
    code = bytes(
        k.asm(
            (
                f"\n      call dword ptr [0x35f4a4];"
                f" pushfd;"
                f"\n      test eax,eax;"
                f" jz done;"
                f"\n      mov dword ptr [{TRACK}],0;"
                f"\n      done: popfd;"
                f" ret;"
                f"\n    "
            ),
            addr=ALLOC
        )[0]
    )
    return [(ALLOC, code)] + [
        (a, b'\xe8' + struct.pack('<i', ALLOC - a - 5) + b'\x90') for a in SITES
    ]


def navigation_overlay_source(
    *, original=0x9b54e8, stats=0x9b56e8, canvas=0x9234e8, pixels=0x8235e8, dynamic=False
):
    """Preserve map projection while drawing into the logical HUD.

    Both fixed and dynamic canvas helpers occupy retained image slots. Only
    the bounded HUD provider installs the active navigation overlay hook.
    """
    ORIGINAL = original
    STATS = stats
    dimensions = '' if dynamic else (
        "cmp word ptr [esi+8],296;"
        " jne other;"
        " cmp word ptr [esi+10],99;"
        " jne other;"
    )
    projection = (
        "mov esi,dword ptr [0x9a3d24];"
        "\n movzx eax,word ptr [esi+8];"
        " mov dword ptr [0x3622d2],eax;"
        "\n mov edx,eax;"
        " shr edx,1;"
        " mov dword ptr [0x3622da],edx;"
        "\n shl eax,15;"
        " mov dword ptr [0x3622e2],eax;"
        " mov dword ptr [0x3622ea],eax;"
        "\n movzx eax,word ptr [esi+10];"
        " mov dword ptr [0x3622d6],eax;"
        "\n mov edx,eax;"
        " shr edx,1;"
        " mov dword ptr [0x3622de],edx;"
        "\n shl eax,15;"
        " mov dword ptr [0x3622e6],eax;"
        " mov dword ptr [0x3622ee],eax;"
    ) if dynamic else (
        f"\n mov dword ptr [0x3622d2],296;"
        f" mov dword ptr [0x3622d6],99;"
        f"\n mov dword ptr [0x3622da],148;"
        f" mov dword ptr [0x3622de],49;"
        f"\n mov dword ptr [0x3622e2],{296<<15};"
        f" mov dword ptr [0x3622ea],{296<<15};"
        f"\n mov dword ptr [0x3622e6],{99<<15};"
        f" mov dword ptr [0x3622ee],{99<<15};"
    )
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n cmp byte ptr [0x449],0x6b;"
        f" jne other;"
        f"\n cmp dword ptr [0x44b1a0],{canvas};"
        f" jne other;"
        f"\n cmp dword ptr [{canvas}],{pixels};"
        f" jne other;"
        f"\n mov esi,dword ptr [0x9a3d24];"
        f"\n {dimensions}\n cmp word ptr [esi+12],320;"
        f" jne other;"
        f"\n sub esp,40;"
        f"\n mov eax,dword ptr [0x44b1a0];"
        f" mov dword ptr [esp],eax;"
        f"\n mov esi,0x3622ce;"
        f" lea edi,[esp+4];"
        f" mov ecx,9;"
        f" rep movsd;"
        f"\n mov dword ptr [0x3622ce],0x13333;"
        f"\n {projection}\n mov eax,dword ptr [0x9a3d24];"
        f" call 0x2eab30;"
        f"\n inc dword ptr [{STATS}];"
        f"\n mov edi,dword ptr [esp+40];"
        f" mov esi,dword ptr [esp+44];"
        f" mov ebp,dword ptr [esp+48];"
        f"\n mov ebx,dword ptr [esp+56];"
        f" mov edx,dword ptr [esp+60];"
        f" mov ecx,dword ptr [esp+64];"
        f" mov eax,dword ptr [esp+68];"
        f"\n push dword ptr [esp+72];"
        f" popfd;"
        f"\n call {ORIGINAL};"
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov edx,dword ptr [0x44b1a0];"
        f" mov edx,dword ptr [edx+16];"
        f"\n mov eax,dword ptr [esp+36];"
        f" mov dword ptr [eax+16],edx;"
        f" call 0x2eab30;"
        f"\n lea esi,[esp+40];"
        f" mov edi,0x3622ce;"
        f" mov ecx,9;"
        f" rep movsd;"
        f"\n popad;"
        f" popfd;"
        f" lea esp,[esp+76];"
        f" ret;"
        f"\n other: popad;"
        f" popfd;"
        f" jmp {ORIGINAL};"
        f"\n "
    )


def navigation_overlay():
    ENTRY = 0x9b50e8
    ORIGINAL = 0x9b54e8
    STATS = 0x9b56e8
    k = Ks(KS_ARCH_X86, KS_MODE_32)
    asm = lambda a, s: bytes(k.asm(s.replace('rep movsd', '.byte 0xf3,0xa5'), addr=a)[0])
    wrapper = asm(ENTRY, navigation_overlay_source())
    original = asm(
        ORIGINAL,
        ("push ebx;"
         " push ecx;"
         " push edx;"
         " push esi;"
         " push edi;"
         " jmp 0x29ba41;")
    )
    assert len(wrapper) < 0x400
    return [(ENTRY, wrapper), (ORIGINAL, original)]


def display_restore():
    """Retain the display-resume entry redirected by the Windows host."""
    CODE = 0x9b98e8
    STATS = 0x9b99e8
    ORIGINAL = 0x9ae6e8
    s = (
        f"\n pushfd;"
        f" pushad;"
        f"\n cmp byte ptr [0x449],0x6b;"
        f" jne done;"
        f"\n cli;"
        f"\n mov dx,0x3d4;"
        f" in al,dx;"
        f" mov bl,al;"
        f"\n mov al,0x58;"
        f" out dx,al;"
        f" inc edx;"
        f"\n in al,dx;"
        f" out dx,al;"
        f"\n dec edx;"
        f" mov al,bl;"
        f" out dx,al;"
        f"\n inc dword ptr [{STATS}];"
        f"\n done: popad;"
        f" popfd;"
        f" jmp {ORIGINAL};"
        f"\n "
    )
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(s, addr=CODE)[0])
    assert len(code) < 0x100
    return [(CODE, code)]


def resolution_guard():
    # Original conditional branch becomes unconditional; the destination stays.
    address = 0x2633f0
    code = bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm('jmp 0x2633ff', addr=address)[0])
    return [(address, code)]


def target_bounds():
    """Convert target rectangles and restore the original projection state.

    The camera provider owns the world-entry hook. This helper is a retained
    link in that call path, with one final aspect/rectangle policy.
    """
    WORLD, CONVERT, STATS = 0x9b30e8, 0x9b32e8, 0x9b38e8
    k = Ks(KS_ARCH_X86, KS_MODE_32)
    asm = lambda a, s: bytes(k.asm(s, addr=a)[0])
    aspect_enter = 'push dword ptr [0x44b1ac]; mov dword ptr [0x44b1ac],0x10000;'
    aspect_restore = 'mov eax,dword ptr [esp+36]; mov dword ptr [0x44b1ac],eax;'
    stack_restore = 'lea esp,[esp+4];'
    projection = (
        " mov dword ptr [0x3622ce],eax;"
        "\n mov esi,dword ptr [0x38fb40];"
        "\n movzx eax,word ptr [esi+8];"
        " mov dword ptr [0x3622d2],eax;"
        "\n mov edx,eax;"
        " shr edx,1;"
        " mov dword ptr [0x3622da],edx;"
        "\n shl eax,15;"
        " mov dword ptr [0x3622e2],eax;"
        " mov dword ptr [0x3622ea],eax;"
        "\n movzx eax,word ptr [esi+10];"
        " mov dword ptr [0x3622d6],eax;"
        "\n mov edx,eax;"
        " shr edx,1;"
        " mov dword ptr [0x3622de],edx;"
        "\n shl eax,15;"
        " mov dword ptr [0x3622e6],eax;"
        " mov dword ptr [0x3622ee],eax;"
        "\n"
    )
    world = asm(
        WORLD, (
            f"\n pushfd;"
            f" cmp edx,0x38fb24;"
            f" jne other;"
            f" popfd;"
            f"\n {aspect_enter}\n call 0x9b00e8;"
            f"\n pushfd;"
            f" pushad;"
            f"\n {aspect_restore}\n cmp byte ptr [0x449],0x6b;"
            f" jne done;"
            f"\n cmp word ptr [0x446f80],320;"
            f" jne done;"
            f"\n cmp word ptr [0x446f82],200;"
            f" jne done;"
            f"\n {projection}\n mov edi,dword ptr [0x35bf80];"
            f" cmp edi,64;"
            f" ja done;"
            f"\n mov esi,0x397ca0;"
            f" test edi,edi;"
            f" jz done;"
            f"\n next_rect: call {CONVERT};"
            f" add esi,10;"
            f" dec edi;"
            f" jnz next_rect;"
            f"\n inc dword ptr [{STATS}];"
            f"\n done: popad;"
            f" popfd;"
            f" {stack_restore} ret;"
            f"\n other: popfd;"
            f" jmp 0x9b00e8;"
            f"\n "
        )
    )
    # Signed floor, not truncation towards zero; preserve the queue's object ID.
    convert = asm(
        CONVERT, (
            f"\n mov ebx,5;"
            f"\n movsx eax,word ptr [esi];"
            f" add eax,eax;"
            f" cdq;"
            f" idiv ebx;"
            f"\n test edx,edx;"
            f" jns x0;"
            f" dec eax;"
            f"\n x0: mov word ptr [esi],ax;"
            f"\n movsx eax,word ptr [esi+4];"
            f" add eax,eax;"
            f" cdq;"
            f" idiv ebx;"
            f"\n test edx,edx;"
            f" jns x1;"
            f" dec eax;"
            f"\n x1: mov word ptr [esi+4],ax;"
            f"\n mov ebx,3;"
            f"\n movsx eax,word ptr [esi+2];"
            f" cdq;"
            f" idiv ebx;"
            f"\n test edx,edx;"
            f" jns y0;"
            f" dec eax;"
            f"\n y0: mov word ptr [esi+2],ax;"
            f"\n movsx eax,word ptr [esi+6];"
            f" cdq;"
            f" idiv ebx;"
            f"\n test edx,edx;"
            f" jns y1;"
            f" dec eax;"
            f"\n y1: mov word ptr [esi+6],ax;"
            f" ret;"
            f"\n "
        )
    )
    return [(WORLD, world), (CONVERT, convert)]


def navigation():
    return navigation_coordinates() + navigation_overlay()


def display_state():
    return allocation_guard() + resolution_guard() + display_restore()


from foundation_weather import weather, sky_spans
from foundation_cameras import cameras
from foundation_overlays import dialog_coverage, damage_canvas, movie_io

# These independent groups describe the final pre-relocation image. The
# inventory rejects overlapping spans, so list order cannot select a behavior.
GENERATORS = {
    'cursor-text': cursor,
    'world-hud': hud,
    'secondary-cameras': cameras,
    'navigation': navigation,
    'target-projection': target_bounds,
    'weather-terrain': weather,
    'sky-spans': sky_spans,
    'display-state': display_state,
    'dialog-coverage': dialog_coverage,
    'damage-canvas': damage_canvas,
    'movie-io': movie_io,
}
