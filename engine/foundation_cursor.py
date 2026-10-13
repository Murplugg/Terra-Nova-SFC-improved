"""Keep mouse updates small and preserve black outlines around HUD text.

The active cursor restores its old rectangle from the completed frame, then
draws at the new position. The text wrapper records opaque coverage separately
from pixel color, allowing black lettering outlines to survive composition.

Addresses describe the original engine image before Windows relocation. Some
buffered helpers and unreachable slot tails remain solely to preserve the
accepted binary layout and saved states. They have no alternate installation
sequence. Sprite drawing still calls the owner's original game routines.
"""
import struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_32

BUSY = 0x9aa0e8
READY = BUSY + 4
COLS = 0x9a54e8
ROWS = 0x9a64e8
FRAME = 0x8a35e8
CACHE = 0x860000
MASK = 0x870000
PAUSE_RECT = 0x9ad2e8


def assemble(address, source):
    return bytes(Ks(KS_ARCH_X86, KS_MODE_32).asm(source, addr=address)[0])


def branch(address, destination, opcode=0xe9):
    return bytes([opcode]) + struct.pack('<i', destination - address - 5)


def redirected_slot(address, body, destination):
    """Keep the allocated tail behind a final entry jump.

    These tails are retained for executable and snapshot identity. They are
    emitted once and are never selected as an intermediate implementation.
    Removing them belongs to a separate layout change.
    """
    if len(body) < 5:
        raise ValueError('A redirected slot needs room for its entry jump')
    return branch(address, destination) + body[5:]


def compositor_source(
    *,
    buffered=False,
    cached=False,
    outlined=False,
    viewport=None,
    pixels=None,
    cover=None,
    coverage_tracks_dialogs=False
):
    """One authoring body for the four retained compositor profiles."""
    if (cached and not buffered) or (outlined and not cached):
        raise ValueError('Cached/text coverage needs the completed-frame profile')
    if (viewport is None) != (pixels is None) or (viewport is not None and not outlined):
        raise ValueError('Dynamic viewport requires pixels and outlined coverage')
    busy, ready, cols, rows = BUSY, READY, COLS, ROWS
    destination = FRAME if buffered else 0xe0000000
    cache_enter = (
        f"\npush dword ptr [0x446f78];"
        f"\ncmp eax,2;"
        f" je cached_hud;"
        f"\nmov esi,dword ptr [0x446f78];"
        f" mov edi,{CACHE};"
        f" mov ecx,16000;"
        f"\nrep movsd dword ptr es:[edi],dword ptr [esi];"
        f"\ncached_hud: mov dword ptr [0x446f78],{CACHE};"
        f"\n"
    ) if cached else ''
    cache_leave = 'pop dword ptr [0x446f78];' if cached else ''
    pause_bounds = (
        f"\nmovsx eax,word ptr [0x390250];"
        f" imul eax,eax,5;"
        f" inc eax;"
        f" sar eax,1;"
        f" mov dword ptr [{PAUSE_RECT}],eax;"
        f"\nmovsx eax,word ptr [0x390254];"
        f" imul eax,eax,5;"
        f" inc eax;"
        f" sar eax,1;"
        f" mov dword ptr [{PAUSE_RECT+4}],eax;"
        f"\nmovsx eax,word ptr [0x390252];"
        f" imul eax,eax,3;"
        f" mov dword ptr [{PAUSE_RECT+8}],eax;"
        f"\nmovsx eax,word ptr [0x390256];"
        f" imul eax,eax,3;"
        f" mov dword ptr [{PAUSE_RECT+12}],eax;"
        f"\n"
    ) if buffered else ''
    coverage_branch = 'jmp' if coverage_tracks_dialogs else 'je'
    pause_coverage = (
        f"\ncmp byte ptr [0x35f3f4],0;"
        f" {coverage_branch} weapon;"
        f"\ncmp ebp,dword ptr [{PAUSE_RECT+8}];"
        f" jl weapon;"
        f" cmp ebp,dword ptr [{PAUSE_RECT+12}];"
        f" jge weapon;"
        f"\ncmp ecx,dword ptr [{PAUSE_RECT}];"
        f" jl weapon;"
        f" cmp ecx,dword ptr [{PAUSE_RECT+4}];"
        f" jl store_pixel;"
        f"\nweapon:\n"
    ) if buffered else ''
    text_coverage = f'add edx,esi; cmp byte ptr [edx+{MASK-CACHE}],0; je store_pixel;' if outlined else ''
    present_frame = (
        f"mov esi,{FRAME};"
        f" mov edi,0xe0000000;"
        f" mov ecx,120000;"
        f" rep movsd dword ptr es:[edi],dword ptr [esi];"
    ) if buffered else ''
    coverage_call = f'call {cover};' if cover is not None else ''
    world_row = (
        (
            f"mov ebx,ebp;"
            f" sub ebx,dword ptr [{viewport+4}];"
            f" imul ebx,dword ptr [{viewport+16}];"
            f" add ebx,{pixels};"
            f" sub ebx,dword ptr [{viewport}];"
        ) if viewport is not None else
        (f"mov ebx,ebp;"
         f" sub ebx,63;"
         f" imul ebx,ebx,740;"
         f" add ebx,{0x8235e8-30};")
    )
    bounds = (
        f'cmp ebp,dword ptr [{viewport+4}]; jb store_pixel; cmp ebp,dword ptr [{viewport+12}]; jae store_pixel;\n'
        f'cmp ecx,dword ptr [{viewport}]; jb store_pixel; cmp ecx,dword ptr [{viewport+8}]; jae store_pixel;'
        if viewport is not None else (
            "cmp ebp,63;"
            " jb store_pixel;"
            " cmp ebp,360;"
            " jae store_pixel;"
            "\ncmp ecx,30;"
            " jb store_pixel;"
            " cmp ecx,770;"
            " jae store_pixel;"
        )
    )
    weapon_bounds = (
        "cmp ebp,339;"
        " jb world_pixel;"
        "\ncmp edx,147;"
        " jb world_pixel;"
        " cmp edx,173;"
        " jae world_pixel;"
        "\ntest byte ptr [0x38a1a4],0x20;"
        " jz store_pixel;"
    ) if viewport is None else ''
    return (
        f"\npushfd;"
        f" pushad;"
        f" cld;"
        f"\ncmp dword ptr [{busy}],0;"
        f" jne done;"
        f"\nmov dword ptr [{busy}],1;"
        f" inc byte ptr [0x447115];"
        f"\n{cache_enter}\npush 0;"
        f"\ntest eax,eax;"
        f" jz draw_frame;"
        f"\ncmp byte ptr [0x447118],0;"
        f" je draw_frame;"
        f"\nmov eax,0x4470a8;"
        f" mov edx,dword ptr [0x4470a4];"
        f"\nmov ebx,0x446f78;"
        f" mov ecx,0x4470d4;"
        f" call 0x2f25e0;"
        f"\nmov dword ptr [esp],1;"
        f"\ndraw_frame:\n{coverage_call}\n{pause_bounds}\nmov edi,{destination};"
        f" xor ebp,ebp;"
        f"\nrow:\nmov esi,dword ptr [{rows}+ebp*4];"
        f" add esi,dword ptr [0x446f78];"
        f"\n{world_row}\nxor ecx,ecx;"
        f"\npixel:\nmovzx edx,word ptr [{cols}+ecx*2];"
        f" mov al,byte ptr [esi+edx];"
        f"\ncmp dword ptr [{ready}],0;"
        f" je store_pixel;"
        f"\ntest al,al;"
        f" jnz store_pixel;"
        f"\n{bounds}\n{pause_coverage}\n{weapon_bounds}\nworld_pixel: {text_coverage}\nmov al,byte ptr [ebx+ecx];"
        f"\nstore_pixel: stosb;"
        f" inc ecx;"
        f" cmp ecx,800;"
        f" jb pixel;"
        f"\ninc ebp;"
        f" cmp ebp,600;"
        f" jb row;"
        f"\n{present_frame}\npop eax;"
        f" test eax,eax;"
        f" jz finish;"
        f"\nmov eax,0x4470d4;"
        f" call 0x2f26e8;"
        f"\nfinish: {cache_leave}\ndec byte ptr [0x447115];"
        f" mov dword ptr [{busy}],0;"
        f"\ndone: popad;"
        f" popfd;"
        f" ret;"
        f"\n"
    )


def display_callbacks():
    """Present through the display-resume entry and retain cursor fallback."""
    present, blit, compose, cursor, original = 0x9ab4e8, 0x9ab6e8, 0x9ab8e8, 0x9abee8, 0x9ac0e8
    busy, counter = BUSY, 0x9a3d38
    asm = assemble
    c = redirected_slot(compose, asm(compose, compositor_source()), 0x9b98e8)
    p = asm(
        present, (
            f"\n    cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n    pushfd;"
            f" mov dword ptr [{busy}],1;"
            f" popfd;"
            f"\n    call 0x262814;"
            f"\n    pushfd;"
            f" pushad;"
            f"\n    mov dword ptr [{busy}],0;"
            f" mov eax,1;"
            f" call {compose};"
            f"\n    inc dword ptr [{counter}];"
            f" popad;"
            f" popfd;"
            f" ret;"
            f"\n    regular: jmp 0x262814;"
            f"\n    "
        )
    )
    b = asm(
        blit, (
            f"\n    cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f80],320;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f82],200;"
            f" jne regular;"
            f"\n    pushfd;"
            f" pushad;"
            f" mov eax,1;"
            f" call {compose};"
            f"\n    popad;"
            f" popfd;"
            f" ret;"
            f"\n    regular: push ebx;"
            f" push ecx;"
            f" push edx;"
            f" mov edx,eax;"
            f" jmp 0x2e43d5;"
            f"\n    "
        )
    )
    k = asm(
        cursor, (
            f"\n    cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f80],320;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f82],200;"
            f" jne regular;"
            f"\n    pushfd;"
            f" pushad;"
            f"\n    cmp bl,1;"
            f" je draw_cursor;"
            f"\n    cmp bl,2;"
            f" jne done;"
            f"\n    xor eax,eax;"
            f" call {compose};"
            f" jmp done;"
            f"\n    draw_cursor: mov eax,1;"
            f" call {compose};"
            f"\n    done: popad;"
            f" popfd;"
            f" ret;"
            f"\n    regular: jmp {original};"
            f"\n    "
        )
    )
    # The fallback is the unchanged original cursor routine, read locally.
    from original_inputs import edited_assembly
    o = asm(original, edited_assembly((
        0x2e54e0, 0x2e5505,
        'd10dbc4079a31fb974bdc2622c9c1e3acbe6b85118ab2f2117a7d27c00176c4d',
        {}, {},
    )))
    return [
        (present, p), (blit, b), (compose, c), (cursor, k), (original, o),
        (0x261fcc, branch(0x261fcc, present, 0xe8)), (0x2e43d0, branch(0x2e43d0, blit))
    ]


def retained_buffered_helpers(*, cached=False):
    """Emit fixed compatibility slots without installing alternate cursor hooks.

    Both buffered profiles remain in the accepted image. Cached callbacks bind
    directly to the canvas wrapper; normal mouse updates use cursor_updates().
    """
    compose, cursor, movement = (0x9ad4e8, 0x9adce8,
                                 0x9adee8) if cached else (0x9ac4e8, 0x9acce8, 0x9acee8)
    mode = 2 if cached else 1
    callback = 0x9ae4e8 if cached else compose
    asm = assemble
    c = asm(compose, compositor_source(buffered=True, cached=cached))
    k = asm(
        cursor, (
            f"\n    cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f80],320;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f82],200;"
            f" jne regular;"
            f"\n    pushfd;"
            f" pushad;"
            f" cmp bl,1;"
            f" jne done;"
            f"\n    mov eax,{mode};"
            f" call {callback};"
            f"\n    done: popad;"
            f" popfd;"
            f" ret;"
            f"\n    regular: jmp 0x9ac0e8;"
            f"\n    "
        )
    )
    m = asm(
        movement, (
            f"\n    cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f80],320;"
            f" jne regular;"
            f"\n    cmp word ptr [0x446f82],200;"
            f" jne regular;"
            f"\n    pushfd;"
            f" pushad;"
            f"\n    mov eax,dword ptr [0x4470c0];"
            f" mov dword ptr [0x4470a4],eax;"
            f"\n    mov eax,{mode};"
            f" call {callback};"
            f"\n    popad;"
            f" popfd;"
            f" jmp 0x2f25d3;"
            f"\n    regular: xor eax,eax;"
            f" call 0x2f26e8;"
            f" jmp 0x2f25b5;"
            f"\n    "
        )
    )
    start, end = (CACHE, CACHE + 64000) if cached else (FRAME, FRAME + 800 * 600)
    return [
        (compose, c), (cursor, k), (movement, m), (start - 256, b'\xa5' * 256),
        (end, b'\xa5' * 256)
    ]


def cached_canvas():
    """Temporarily bind the derived drawing canvas to the cached HUD."""
    entry = 0x9ae4e8
    code = assemble(
        entry, (
            "\npushfd;"
            " push edx;"
            " push dword ptr [0x446fd0];"
            "\nmov edx,dword ptr [0x446fd0];"
            " sub edx,dword ptr [0x446f78];"
            " add edx,0x860000;"
            "\nmov dword ptr [0x446fd0],edx;"
            "\ncall 0x9b08e8;"
            "\npop dword ptr [0x446fd0];"
            " pop edx;"
            " popfd;"
            " ret;"
            "\n"
        )
    )
    return [(entry, code)]


def cursor_updates():
    """Restore the old cursor rectangle and paint only its new screen area."""
    COMPOSE, PAINT, MOVEMENT, CALLBACK = 0x9ae6e8, 0x9ae8e8, 0x9af0e8, 0x9af2e8
    STATS, RECT = 0x9af4e8, 0x9af5e8
    ks = Ks(KS_ARCH_X86, KS_MODE_32)

    def asm(a, s):
        return bytes(ks.asm(s, addr=a)[0])

    def jump(a, b):
        return b'\xe9' + struct.pack('<i', b - a - 5)

    # EAX=0 builds a completed cursor-free frame and HUD cache. All subsequent
    # mouse events use these two completed images, never the live world buffer.
    compose = asm(
        COMPOSE, (
            f"\n        pushfd;"
            f" pushad;"
            f"\n        cmp dword ptr [{BUSY}],0;"
            f" jne done;"
            f"\n        xor eax,eax;"
            f" call 0x9ae4e8;"
            f"\n        mov dword ptr [{STATS}],1;"
            f" inc dword ptr [{STATS+4}];"
            f"\n        call {PAINT};"
            f"\n    done: popad;"
            f" popfd;"
            f" ret;"
            f"\n    "
        )
    )
    paint = asm(
        PAINT, (
            f"\n        pushfd;"
            f" pushad;"
            f" cld;"
            f"\n        cmp dword ptr [{STATS}],0;"
            f" je done;"
            f"\n        cmp dword ptr [{BUSY}],0;"
            f" jne blocked;"
            f"\n        mov dword ptr [{BUSY}],1;"
            f" inc byte ptr [0x447115];"
            f"\n        inc dword ptr [{STATS+12}];"
            f"\n\n        cmp dword ptr [{RECT}],0;"
            f" je cursor_bounds;"
            f"\n        mov eax,dword ptr [{RECT+12}];"
            f" imul eax,eax,800;"
            f"\n        add eax,dword ptr [{RECT+4}];"
            f"\n        lea esi,[eax+{FRAME}];"
            f" lea edi,[eax+0xe0000000];"
            f"\n        mov edx,dword ptr [{RECT+8}];"
            f" sub edx,dword ptr [{RECT+4}];"
            f"\n        mov ebx,dword ptr [{RECT+16}];"
            f" sub ebx,dword ptr [{RECT+12}];"
            f"\n        mov eax,edx;"
            f" imul eax,ebx;"
            f" add dword ptr [{STATS+16}],eax;"
            f"\n        mov ebp,800;"
            f" sub ebp,edx;"
            f"\n    restore_row:\n        mov ecx,edx;"
            f" rep movsb byte ptr es:[edi],byte ptr [esi];"
            f"\n        add esi,ebp;"
            f" add edi,ebp;"
            f" dec ebx;"
            f" jnz restore_row;"
            f"\n\n    cursor_bounds:\n        mov dword ptr [{RECT}],0;"
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
            f" mov dword ptr [{RECT+32}],eax;"
            f"\n        lea edx,[edx+edx*4+1];"
            f" sar edx,1;"
            f" mov dword ptr [{RECT+36}],edx;"
            f"\n        movsx eax,word ptr [0x4470a6];"
            f" movsx edx,word ptr [0x4470ba];"
            f" sub eax,edx;"
            f"\n        movzx edx,word ptr [0x4470b2];"
            f" add edx,eax;"
            f"\n        test eax,eax;"
            f" jns top_ok;"
            f" xor eax,eax;"
            f"\n    top_ok:\n        cmp edx,200;"
            f" jle bottom_ok;"
            f" mov edx,200;"
            f"\n    bottom_ok:\n        cmp eax,edx;"
            f" jge finish;"
            f"\n        lea eax,[eax+eax*2];"
            f" mov dword ptr [{RECT+40}],eax;"
            f"\n        lea edx,[edx+edx*2];"
            f" mov dword ptr [{RECT+44}],edx;"
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
            f"\n\n        mov ebp,dword ptr [{RECT+40}];"
            f"\n    paint_row:\n        mov esi,dword ptr [{ROWS}+ebp*4];"
            f" add esi,{CACHE};"
            f"\n        imul ebx,ebp,800;"
            f"\n        lea edi,[ebx+0xe0000000];"
            f" add edi,dword ptr [{RECT+32}];"
            f"\n        add ebx,{FRAME};"
            f" mov ecx,dword ptr [{RECT+32}];"
            f"\n    paint_pixel:\n        movzx edx,word ptr [{COLS}+ecx*2];"
            f" mov al,byte ptr [esi+edx];"
            f"\n        test al,al;"
            f" jnz store_pixel;"
            f" mov al,byte ptr [ebx+ecx];"
            f"\n    store_pixel:\n        stosb;"
            f" inc ecx;"
            f" cmp ecx,dword ptr [{RECT+36}];"
            f" jb paint_pixel;"
            f"\n        inc ebp;"
            f" cmp ebp,dword ptr [{RECT+44}];"
            f" jb paint_row;"
            f"\n\n        mov eax,0x4470d4;"
            f" call 0x2f26e8;"
            f"\n        pop dword ptr [0x446fd0];"
            f" pop dword ptr [0x446f78];"
            f"\n        mov eax,dword ptr [{RECT+36}];"
            f" sub eax,dword ptr [{RECT+32}];"
            f"\n        mov edx,dword ptr [{RECT+44}];"
            f" sub edx,dword ptr [{RECT+40}];"
            f"\n        imul eax,edx;"
            f" add dword ptr [{STATS+16}],eax;"
            f"\n        mov esi,{RECT+32};"
            f" mov edi,{RECT+4};"
            f" mov ecx,4;"
            f"\n        rep movsd dword ptr es:[edi],dword ptr [esi];"
            f"\n        mov dword ptr [{RECT}],1;"
            f"\n    finish:\n        dec byte ptr [0x447115];"
            f" mov dword ptr [{BUSY}],0;"
            f" jmp done;"
            f"\n    blocked: inc dword ptr [{STATS+20}];"
            f"\n    done: popad;"
            f" popfd;"
            f" ret;"
            f"\n    "
        )
    )
    movement = asm(
        MOVEMENT, (
            f"\n        cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n        cmp word ptr [0x446f80],320;"
            f" jne regular;"
            f"\n        cmp word ptr [0x446f82],200;"
            f" jne regular;"
            f"\n        pushfd;"
            f" pushad;"
            f"\n        mov eax,dword ptr [0x4470c0];"
            f" mov dword ptr [0x4470a4],eax;"
            f"\n        inc dword ptr [{STATS+8}];"
            f" call {PAINT};"
            f"\n        popad;"
            f" popfd;"
            f" jmp 0x2f25d3;"
            f"\n    regular: xor eax,eax;"
            f" call 0x2f26e8;"
            f" jmp 0x2f25b5;"
            f"\n    "
        )
    )
    callback = asm(
        CALLBACK, (
            f"\n        cmp byte ptr [0x449],0x6b;"
            f" jne regular;"
            f"\n        cmp word ptr [0x446f80],320;"
            f" jne regular;"
            f"\n        cmp word ptr [0x446f82],200;"
            f" jne regular;"
            f"\n        pushfd;"
            f" pushad;"
            f" cmp bl,1;"
            f" jne done;"
            f"\n        inc dword ptr [{STATS+24}];"
            f" call {PAINT};"
            f"\n    done: popad;"
            f" popfd;"
            f" ret;"
            f"\n    regular: jmp 0x9ac0e8;"
            f"\n    "
        )
    )
    assert len(compose) < 0x200 and len(paint) < 0x800
    assert len(movement) < 0x200 and len(callback) < 0x200
    return [
        (COMPOSE, compose), (PAINT, paint), (MOVEMENT, movement), (CALLBACK, callback),
        (0x2e54e0, jump(0x2e54e0, CALLBACK)), (0x2f25ae, jump(0x2f25ae, MOVEMENT) + b'\x90\x90')
    ]


def outlined_text(*, guards=True):
    WORLD, TEXT, ORIGINAL, COMPOSE, STATS = 0x9b00e8, 0x9b02e8, 0x9b06e8, 0x9b08e8, 0x9b10e8
    asm = assemble
    world = asm(
        WORLD, (
            f"\n            pushfd;"
            f" pushad;"
            f" cld;"
            f"\n            cmp edx,0x38fb24;"
            f" jne done;"
            f"\n            mov edi,{MASK};"
            f" mov eax,0xffffffff;"
            f" mov ecx,16000;"
            f"\n            rep stosd dword ptr es:[edi],eax;"
            f"\n            inc dword ptr [{STATS}];"
            f"\n        done: popad;"
            f" popfd;"
            f" jmp 0x9a94e8;"
            f"\n        "
        )
    )
    text = asm(
        TEXT, (
            f"\n            pushfd;"
            f" pushad;"
            f"\n            push dword ptr [esp+40];"
            f" call {ORIGINAL};"
            f"\n            pushfd;"
            f" pushad;"
            f" mov ebp,esp;"
            f"\n            cmp byte ptr [0x449],0x6b;"
            f" jne done;"
            f"\n            cmp word ptr [0x446f80],320;"
            f" jne done;"
            f"\n            cmp word ptr [0x446f82],200;"
            f" jne done;"
            f"\n            mov esi,dword ptr [0x44b1a0];"
            f"\n            cmp word ptr [esi+12],320;"
            f" jne done;"
            f"\n            mov edi,dword ptr [esi];"
            f" mov eax,edi;"
            f" sub eax,dword ptr [0x446f78];"
            f"\n            cmp eax,64000;"
            f" jae done;"
            f"\n            movzx edx,word ptr [esi+10];"
            f" test edx,edx;"
            f" jz done;"
            f"\n            dec edx;"
            f" imul edx,edx,320;"
            f"\n            movzx ecx,word ptr [esi+8];"
            f" test ecx,ecx;"
            f" jz done;"
            f"\n            add edx,ecx;"
            f" add edx,eax;"
            f" cmp edx,64000;"
            f" ja done;"
            f"\n            push dword ptr [{BUSY}];"
            f" push dword ptr [esi+16];"
            f"\n            mov dword ptr [{BUSY}],1;"
            f" inc byte ptr [0x447115];"
            f"\n            add eax,{MASK};"
            f" mov dword ptr [esi],eax;"
            f"\n            mov eax,dword ptr [ebp+64];"
            f" mov edx,dword ptr [ebp+56];"
            f"\n            mov ebx,dword ptr [ebp+52];"
            f" mov ecx,dword ptr [ebp+60];"
            f"\n            push 0;"
            f" call {ORIGINAL};"
            f"\n            mov dword ptr [esi],edi;"
            f"\n            pop dword ptr [esi+16];"
            f" pop dword ptr [{BUSY}];"
            f"\n            dec byte ptr [0x447115];"
            f" inc dword ptr [{STATS+4}];"
            f"\n        done:\n            popad;"
            f" popfd;"
            f" lea esp,[esp+36];"
            f" ret 4;"
            f"\n        "
        )
    )
    original = asm(
        ORIGINAL, ("push esi;"
                   " push edi;"
                   " push ebp;"
                   " sub esp,0x14;"
                   " jmp 0x26809e;")
    )
    compose = asm(COMPOSE, compositor_source(buffered=True, cached=True, outlined=True))
    compose = redirected_slot(COMPOSE, compose, 0x9ba0e8)
    spans = [
        (WORLD, world), (TEXT, text), (ORIGINAL, original), (COMPOSE, compose),
        (0x268098, branch(0x268098, TEXT) + b'\x90')
    ]
    # The 64,000-byte live mask initialization is not a static recipe.
    if guards:
        spans.extend([(MASK - 256, b'\xa5' * 256), (MASK + 64000, b'\xa5' * 256)])
    return spans


def cursor():
    """Emit each cursor/text slot and its final hook exactly once."""
    return (
        display_callbacks() + retained_buffered_helpers() + retained_buffered_helpers(cached=True) +
        cached_canvas() + cursor_updates() + outlined_text()
    )
