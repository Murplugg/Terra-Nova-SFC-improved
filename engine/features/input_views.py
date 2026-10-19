"""Translate Windows pointer input into the game's HUD and world coordinates.

These helpers clamp mouse positions, place the cursor and preserve projection
settings across views. The caller supplies Windows imports and a reader for the
image being built, allowing the installer to check each instruction it replaces.
"""
import struct
from patch_support import asm
from features.render_views import assemble as code


# Enemy Outfitting labels and gaps have no button record. The original handler
# read that record's callback before checking for null, which crashes on Windows.
# Check first, then retain the original restrictions on rear weapon slots.
# Comparing the callback in memory leaves room for this check in the same span;
# ESI supplies the record to the following slot test instead of a redundant EDX.
OUTFIT_BEFORE = {
    0x2cf68c: bytes.fromhex('89c28b480c89c681f9000c2d00752d'),
    0x2cf69d: bytes.fromhex('8a4210'),
}


def outfit_bodies():
    return [
        (0x2cf68c, asm(0x2cf68c, '''
            test eax, eax;
            jz 0x2cf6f0;
            mov esi, eax;
            cmp dword ptr [eax+12], 0x2d0c00;
            jne 0x2cf6c8;
        ''')),
        (0x2cf69d, asm(0x2cf69d, 'mov al, byte ptr [esi+16]')),
    ]


def outfit_install(write, read):
    return _install(outfit_bodies(), OUTFIT_BEFORE, write, read)


def outfit_verify(read):
    return _verify(outfit_bodies(), read)


# The keyboard scanner collects two drone actions but converts only the first.
# Convert the second as well so translation and turning can work together.
# Translation is a speed/direction pair: keep it together, and retain the first
# action when both request translation or both request turning. This preserves
# the original binding priority, including opposing keys and arrow aliases.
DRONE_CONTROLS_SITE = 0x2767ca
DRONE_CONTROLS_ENTRY = 0x1e49b00
DRONE_CONTROLS_LIMIT = 0x1e49d00


def drone_controls_bodies():
    body = code(DRONE_CONTROLS_ENTRY, '''
        pushad
        sub esp, 24
        mov eax, [esp+52]
        mov edx, [esp+44]
        call 0x27cb58

        cmp dword ptr [esp+28], 2
        jne done
        cmp dword ptr [esp+32], 0
        je done
        cmp word ptr [esp+88], 0
        je done

        mov eax, [esp+76]
        mov edx, [0x35b3b4]
        mov ebx, esp
        call 0x27c8b8
        mov eax, esp
        lea edx, [esp+12]
        call 0x27cb58

        mov edx, [esp+44]
        cmp word ptr [edx+4], 0
        jne translation
        mov ax, [esp+16]
        mov [edx+4], ax
    translation:
        cmp dword ptr [edx], 0
        jne done
        cmp word ptr [edx+6], 0
        jne done
        mov eax, [esp+12]
        mov [edx], eax
        mov ax, [esp+18]
        mov [edx+6], ax
    done:
        add esp, 24
        popad
        ret
    ''')
    # Scratch contains a 10-byte descriptor and an 8-byte output, on this call's
    # stack only. Saved registers follow it; the caller's second control point
    # is at +76, and its remaining-key mask is at +88. No persistent state is used.
    zoom_end = max(a + len(b) for a, b in zoom_bodies())
    if not zoom_end <= DRONE_CONTROLS_ENTRY < DRONE_CONTROLS_ENTRY + len(body) <= DRONE_CONTROLS_LIMIT <= ASPECT_VALUE:
        raise ValueError('Drone controls exceed the input helper reservation')
    return [(DRONE_CONTROLS_SITE, asm(DRONE_CONTROLS_SITE, f'call {DRONE_CONTROLS_ENTRY}')),
            (DRONE_CONTROLS_ENTRY, body)]


def drone_controls_install(write, read):
    return _install(drone_controls_bodies(),
                    {DRONE_CONTROLS_SITE: asm(DRONE_CONTROLS_SITE, 'call 0x27cb58')},
                    write, read)


def drone_controls_verify(read):
    return _verify(drone_controls_bodies(), read)


def api_slots(imports):
    result = []
    for name in ('GetModuleHandleA', 'GetProcAddress'):
        address = imports.get(name)
        if not isinstance(address, int) or address % 4 or not 0x11000 <= address <= 0x1fffffc:
            raise ValueError('Missing or invalid cursor API slot: ' + name)
        result.append(address)
    if len(set(result)) != 2:
        raise ValueError('Cursor API slots overlap')
    return result


def _install(pieces, providers, write, read, *, cold_state=()):
    """Validate the whole offline transition before emitting its first write."""
    if not providers.keys() <= {a for a, b in pieces}:
        raise ValueError('Missing input hook provider')
    occupied = []
    for a, b in pieces:
        if not b or not 0x11000 <= a < a + len(b) <= 0x2000000:
            raise ValueError('Invalid input span')
        if any(a < end and start < a + len(b) for start, end in occupied):
            raise ValueError('Overlapping input spans')
        occupied.append((a, a + len(b)))
    current = tuple(bytes(read(a, len(b))) for a, b in pieces)
    if current == tuple(b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    before = tuple(providers.get(a, bytes(len(b))) for a, b in pieces)
    if current != before:
        raise ValueError('Native input provider differs')
    for a, n in cold_state:
        if bytes(read(a, n)) != bytes(n):
            raise ValueError('Native input state reservation differs')
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])


def _verify(pieces, read):
    for a, b in pieces:
        if bytes(read(a, len(b))) != b:
            raise ValueError('Native input output differs at ' + hex(a))
    return True


def aspect_providers():
    return {
        ASPECT_CONSTRUCTOR: asm(ASPECT_CONSTRUCTOR, 'mov eax,[0x35f8cc]'),
        ASPECT_SITE: asm(ASPECT_SITE, 'jmp 0x1dea900')
    }


def aspect_install(write, read):
    return _install(
        aspect_bodies(), aspect_providers(), write, read, cold_state=((ASPECT_VALUE, 4), )
    )


def aspect_verify(read):
    return _verify(aspect_bodies(), read)


# Reapplying Ground Detail rebuilds the main terrain view. The original caller
# supplies zoom zero even when the player has selected magnification, leaving
# the picture and the zoom controls out of step after closing Options.
ZOOM_DETAIL_SITE = 0x26bb89
ZOOM_DETAIL_ENTRY = 0x1e49a00


def zoom_bodies():
    return [
        (ZOOM_DETAIL_SITE, asm(ZOOM_DETAIL_SITE, f'call {ZOOM_DETAIL_ENTRY}')),
        (ZOOM_DETAIL_ENTRY, code(ZOOM_DETAIL_ENTRY, '''
            movzx ebx, word ptr [0x38fbe2]
            jmp 0x2ac7a0
        ''')),
    ]


def zoom_install(write, read):
    """Keep the selected zoom when the original Ground Detail setup runs."""
    return _install(
        zoom_bodies(), {ZOOM_DETAIL_SITE: asm(ZOOM_DETAIL_SITE, 'call 0x2ac7a0')}, write, read
    )


def zoom_verify(read):
    return _verify(zoom_bodies(), read)


def cursor_install(write, read, imports):
    return _install(
        cursor_bodies(imports), {CURSOR_PROC: CURSOR_PREFIX},
        write,
        read,
        cold_state=((CURSOR_SLOT, 4), )
    )


def cursor_verify(read, imports):
    return _verify(cursor_bodies(imports), read)


def room_install(write, read, imports):
    return _install(
        room_bodies(imports), room_providers(),
        write,
        read,
        cold_state=((ROOM_CACHE, 12), )
    )


def room_verify(read, imports):
    return _verify(room_bodies(imports), read)


ASPECT_ENTRY = 0x1e49000
ASPECT_RENDER = 0x1e49400
ASPECT_VALUE = 0x1e49f00
ASPECT_CONSTRUCTOR = 0x29ea51
ASPECT_SITE = 0x29edb4


def aspect_bodies():
    # The original driver may reselect mode 0, whose aspect is 1.2, while
    # our logical surface remains 320x400 (aspect 0.6). Use logical geometry
    # only for this mode; retain original reduced-detail flag handling.
    s = (
        f"pushfd;"
        f"cmp dword ptr [0x446f80],0x01900140;"
        f"jne original;"
        f"\n mov eax,{ASPECT_VALUE};"
        f"mov dword ptr [eax],0x9999;"
        f"\n test byte ptr [esi+0x2e],1;"
        f"jz ready;"
        f"test byte ptr [esi+0x2e],2;"
        f"jnz ready;"
        f"sar dword ptr [eax],1;"
        f"\n ready:popfd;"
        f"jmp 0x29ea56;"
        f"\n original:popfd;"
        f"mov eax,[0x35f8cc];"
        f"jmp 0x29ea56;"
    )
    # Repair an already captured context on its next draw. Only projection
    # scale/angle change, using exactly the constructor's arithmetic. Avoid
    # rerunning its LOD renormalization or changing simulation/camera state.
    r = (
        f"pushfd;"
        f"pushad;"
        f"cmp dword ptr [0x446f80],0x01900140;"
        f"jne done;"
        f"\n mov esi,edx;"
        f"cmp esi,0x38fb24;"
        f"je owned;"
        f"\n cmp esi,0x390010;"
        f"je owned;"
        f"cmp esi,0x3900ca;"
        f"je owned;"
        f"cmp esi,0x390184;"
        f"jne done;"
        f"\n owned:mov edi,[esi+28];"
        f"cmp edi,0x11000;"
        f"jb done;"
        f"cmp edi,0x1ffffc0;"
        f"ja done;"
        f"\n cmp word ptr [edi+12],320;"
        f"jne done;"
        f"\n movzx eax,word ptr [edi+8];"
        f"movzx ebx,word ptr [edi+10];"
        f"test eax,eax;"
        f"jz done;"
        f"test ebx,ebx;"
        f"jz done;"
        f"\n cmp eax,320;"
        f"ja done;"
        f"cmp ebx,400;"
        f"ja done;"
        f"mov ebp,0x9999;"
        f"\n movzx ecx,byte ptr [esi+0x2e];"
        f"test ecx,1;"
        f"jz width_ready;"
        f"shr eax,1;"
        f"test ecx,2;"
        f"jnz width_ready;"
        f"shr ebp,1;"
        f"\n width_ready:test ecx,2;"
        f"jz height_ready;"
        f"shr ebx,1;"
        f"\n height_ready:imul ebx,ebp;"
        f"test ebx,ebx;"
        f"jz done;"
        f"imul eax,[esi];"
        f"mov edx,eax;"
        f"sar edx,16;"
        f"shl eax,16;"
        f"idiv ebx;"
        f"\n cmp eax,[esi+4];"
        f"je done;"
        f"mov [esi+4],eax;"
        f"mov edx,eax;"
        f"imul eax,[esi+20];"
        f"mov [esi+12],eax;"
        f"\n mov eax,0x10000;"
        f"call 0x2ecc24;"
        f"mov [esi+26],ax;"
        f"\n done:popad;"
        f"popfd;"
        f"jmp 0x1dea900;"
    )
    return [
        (ASPECT_ENTRY, code(ASPECT_ENTRY, s)), (ASPECT_RENDER, code(ASPECT_RENDER, r)),
        (ASPECT_CONSTRUCTOR, asm(ASPECT_CONSTRUCTOR, f'jmp {ASPECT_ENTRY}')),
        (ASPECT_SITE, asm(ASPECT_SITE, f'jmp {ASPECT_RENDER}'))
    ]


CURSOR_PROC = 0x1d19800
CURSOR_ENTRY = 0x1e4a300
CURSOR_SLOT = 0x1e4a500
CURSOR_DLL = 0x1e4a520
CURSOR_NAME = 0x1e4a540
CURSOR_PREFIX = bytes.fromhex('8b44240883f802')


def cursor_bodies(imports):
    gm, gp = api_slots(imports)
    body = asm(
        CURSOR_ENTRY, (
            f"cmp dword ptr [esp+8],0x20;"
            f"jne original;"
            f"\n cmp word ptr [esp+16],1;"
            f"jne original;"
            f"\n pushfd;"
            f"pushad;"
            f"mov eax,[{CURSOR_SLOT}];"
            f"test eax,eax;"
            f"jnz hide;"
            f"\n push {CURSOR_DLL};"
            f"call dword ptr [{gm}];"
            f"test eax,eax;"
            f"jz failure;"
            f"\n push {CURSOR_NAME};"
            f"push eax;"
            f"call dword ptr [{gp}];"
            f"test eax,eax;"
            f"jz failure;"
            f"\n mov [{CURSOR_SLOT}],eax;"
            f"\n hide:push 0;"
            f"call eax;"
            f"popad;"
            f"popfd;"
            f"mov eax,1;"
            f"ret 16;"
            f"\n failure:popad;"
            f"popfd;"
            f"\n original:mov eax,[esp+8];"
            f"cmp eax,2;"
            f"jmp {CURSOR_PROC+len(CURSOR_PREFIX)};"
        )
    )
    assert len(body) < CURSOR_SLOT - CURSOR_ENTRY
    return [
        (CURSOR_ENTRY, body), (CURSOR_DLL, b'user32.dll\0'), (CURSOR_NAME, b'SetCursor\0'),
        (CURSOR_PROC, asm(CURSOR_PROC, f'jmp {CURSOR_ENTRY}') + b'\x90\x90')
    ]


ROOM_CODE = 0x1fcb000
ROOM_TRAMP = ROOM_CODE + 0x300
ROOM_SYNC = ROOM_CODE + 0x400
ROOM_CACHE = ROOM_CODE + 0x800
ROOM_DLL = ROOM_CODE + 0x840
ROOM_NAMES = [ROOM_CODE + 0x860, ROOM_CODE + 0x880, ROOM_CODE + 0x8a0]
ROOM_SITE = 0x2b670d
ROOM_ORIGINAL = asm(ROOM_SITE, 'call 0x2e4a68')
GEAR_POINTER_SITE = 0x2c2003


def room_providers():
    return {site: asm(site, 'call 0x2e4a68') for site in (ROOM_SITE, GEAR_POINTER_SITE)}


def room_bodies(imports):
    gm, gp = api_slots(imports)
    body = asm(
        ROOM_CODE, (
            f"cmp byte ptr [0x1d0d449],0x69;"
            f"jne other;"
            f"\n call {ROOM_TRAMP};"
            f"pushfd;"
            f"pushad;"
            f"call {ROOM_SYNC};"
            f"popad;"
            f"popfd;"
            f"ret;"
            f"\n other:jmp 0x2e4a68;"
        )
    )
    # Room navigation and the New Technology screen explicitly place the mouse.
    # The latter computes the OK button's center for each equipment reveal.
    # Preserve those requests through the original routine, then synchronize
    # Windows while the game has focus. Other cursor-preservation calls remain.
    tramp = asm(ROOM_TRAMP, ("push ebx;"
                             "push ecx;"
                             "push edx;"
                             "sub esp,4;"
                             "jmp 0x2e4a6e;"))
    s = (
        f"cmp dword ptr [{ROOM_CACHE}],0;"
        f"jne resolved;"
        f"\n push {ROOM_DLL};"
        f"call dword ptr [{gm}];"
        f"test eax,eax;"
        f"jz done;"
        f"mov ebp,eax;"
    )
    for i, name in enumerate(ROOM_NAMES):
        s += (
            f"push {name};"
            f"push ebp;"
            f"call dword ptr [{gp}];"
            f"test eax,eax;"
            f"jz done;"
            f"mov [{ROOM_CACHE+4*i}],eax;"
        )
    s += (
        f"resolved:cmp dword ptr [{ROOM_CACHE+4}],0;"
        f"je done;"
        f"cmp dword ptr [{ROOM_CACHE+8}],0;"
        f"je done;"
        f"\n call dword ptr [{ROOM_CACHE}];"
        f"cmp eax,[0x1d1d000];"
        f"jne done;"
        f"\n sub esp,8;"
        f"mov edi,esp;"
        f"xor ebx,ebx;"
        f"\n axis:mov eax,[0x1d0f000+ebx];"
        f"mov ecx,[0x1d0f010+ebx*2];"
        f"sub ecx,[0x1d0f00c+ebx*2];"
        f"jle failed;"
        f"\n sub eax,[0x1d0f00c+ebx*2];"
        f"js failed;"
        f"cmp eax,ecx;"
        f"ja failed;"
        f"\n mov edx,[0x1d1d098+ebx];"
        f"dec edx;"
        f"jle failed;"
        f"imul eax,edx;"
        f"mov edx,ecx;"
        f"shr edx,1;"
        f"add eax,edx;"
        f"xor edx,edx;"
        f"div ecx;"
        f"\n add eax,[0x1d1d090+ebx];"
        f"mov [edi+ebx],eax;"
        f"add ebx,4;"
        f"cmp ebx,8;"
        f"jb axis;"
        f"\n push edi;"
        f"push dword ptr [0x1d1d000];"
        f"call dword ptr [{ROOM_CACHE+4}];"
        f"test eax,eax;"
        f"jz failed;"
        f"\n push dword ptr [edi+4];"
        f"push dword ptr [edi];"
        f"call dword ptr [{ROOM_CACHE+8}];"
        f"\n mov dword ptr [0x1d0f414],0;"
        f"mov dword ptr [0x1d0f418],0;"
        f"\n failed:add esp,8;"
        f"done:ret;"
    )
    sync = asm(ROOM_SYNC, s)
    assert len(sync) < ROOM_CACHE - ROOM_SYNC
    return [(ROOM_CODE, body), (ROOM_TRAMP, tramp), (ROOM_SYNC, sync),
            (ROOM_DLL, b'user32.dll\0')] + list(
                zip(ROOM_NAMES, [b'GetForegroundWindow\0', b'ClientToScreen\0', b'SetCursorPos\0'])
            ) + [(site, asm(site, f'call {ROOM_CODE}')) for site in room_providers()]


MOUSE = 0x1d0f000
HANDLE = 0x1d22000
KEY = 0x1d23000
DELIVER = 0x1d23200
MAP = 0x1d23400
STATE = 0x1d0f400
PRESSED = STATE + 0x100
RECT = STATE + 0x40


def initialize_mouse(write):
    write(MOUSE, struct.pack('<12I', 320, 100, 0, 0, 639, 0, 199, 0, 0, 0, 0, 0))


def mouse_assembly(*, delivered=True):
    delta = (
        f"mov eax,[{STATE+20}];"
        f"mov word ptr [ebp+0xac],ax;"
        f"mov eax,[{STATE+24}];"
        f"mov word ptr [ebp+0xa8],ax;"
        f"mov dword ptr [{STATE+20}],0;"
        f"mov dword ptr [{STATE+24}],0;"
    ) if delivered else 'mov word ptr [ebp+0xac],0;mov word ptr [ebp+0xa8],0;'
    callback = 'movzx eax,word ptr [ebp+0xac]' if delivered else 'mov eax,[ebp+0xac]'
    return (
        f"\n native_mouse:movzx eax,word ptr [ebp+0xb0];"
        f"test eax,eax;"
        f"jz mouse_reset;"
        f"cmp eax,0x21;"
        f"je mouse_reset;"
        f"\n cmp eax,1;"
        f"je mouse_show;"
        f"cmp eax,2;"
        f"je mouse_hide;"
        f"cmp eax,3;"
        f"je mouse_get;"
        f"cmp eax,4;"
        f"je mouse_set;"
        f"\n cmp eax,7;"
        f"je mouse_xrange;"
        f"cmp eax,8;"
        f"je mouse_yrange;"
        f"cmp eax,0xb;"
        f"je mouse_delta;"
        f"cmp eax,0xc;"
        f"je mouse_callback;"
        f"cmp eax,0xf;"
        f"je mouse_ratio;"
        f"cmp eax,0x13;"
        f"je mouse_threshold;"
        f"jmp stop;"
        f"\n mouse_reset:mov dword ptr [{MOUSE+8}],0;"
        f"mov dword ptr [{MOUSE+28}],0;"
        f"mov word ptr [ebp+0xb0],0xffff;"
        f"mov word ptr [ebp+0xa4],3;"
        f"jmp resume;"
        f"\n mouse_show:inc dword ptr [{MOUSE+28}];"
        f"jmp resume;"
        f"\n mouse_hide:dec dword ptr [{MOUSE+28}];"
        f"jmp resume;"
        f"\n mouse_get:mov eax,[{MOUSE+8}];"
        f"mov word ptr [ebp+0xa4],ax;"
        f"mov eax,[{MOUSE}];"
        f"mov word ptr [ebp+0xac],ax;"
        f"mov eax,[{MOUSE+4}];"
        f"mov word ptr [ebp+0xa8],ax;"
        f"jmp resume;"
        f"\n mouse_set:movzx eax,word ptr [ebp+0xac];"
        f"mov [{MOUSE}],eax;"
        f"movzx eax,word ptr [ebp+0xa8];"
        f"mov [{MOUSE+4}],eax;"
        f"jmp resume;"
        f"\n mouse_xrange:movzx eax,word ptr [ebp+0xac];"
        f"mov [{MOUSE+12}],eax;"
        f"movzx eax,word ptr [ebp+0xa8];"
        f"mov [{MOUSE+16}],eax;"
        f"jmp resume;"
        f"\n mouse_yrange:movzx eax,word ptr [ebp+0xac];"
        f"mov [{MOUSE+20}],eax;"
        f"movzx eax,word ptr [ebp+0xa8];"
        f"mov [{MOUSE+24}],eax;"
        f"jmp resume;"
        f"\n mouse_delta:{delta}jmp resume;"
        f"\n mouse_callback:{callback};"
        f"mov [{MOUSE+32}],eax;"
        f"mov eax,[ebp+0xa8];"
        f"mov [{MOUSE+36}],eax;"
        f"mov eax,[ebp+0x94];"
        f"mov [{MOUSE+40}],eax;"
        f"jmp resume;"
        f"\n mouse_ratio:mov eax,[ebp+0xac];"
        f"mov [{MOUSE+44}],eax;"
        f"mov eax,[ebp+0xa8];"
        f"mov [{MOUSE+48}],eax;"
        f"jmp resume;"
        f"\n mouse_threshold:movzx eax,word ptr [ebp+0xa8];"
        f"mov [{MOUSE+52}],eax;"
        f"jmp resume;"
        f"\n "
    )


def connect(write, asm, win, window, r):
    assert r[0x319530:0x319539] == bytes.fromhex('061e55565752515350')
    assert r[0x31aae0:0x31aae7] == bytes.fromhex('fb50531e515256')
    # MAP: signed EAX coordinate, ECX client extent, ESI points to min/max.
    write(MAP, asm(MAP, coordinate_source()))
    # Keep the game's handler, including extended keys and press/release queues.
    write(
        KEY,
        asm(
            KEY, (
                f"pushfd;"
                f"pushad;"
                f"\n cmp dword ptr [0x1d07004+9*8],0x31aae0;"
                f"jne key_done;"
                f"\n cmp dword ptr [0x45d62c],0;"
                f"jz key_done;"
                f"\n mov [{STATE}],al;"
                f"inc dword ptr [{STATE+4}];"
                f"\n pushfd;"
                f"push 0x23;"
                f"call 0x31aae0;"
                f"\n key_done:popad;"
                f"popfd;"
                f"ret;"
            )
        )
    )
    # Original mouse entry uses a far return. Supply a real Windows code selector.
    write(
        DELIVER,
        asm(
            DELIVER, (
                f"pushfd;"
                f"pushad;"
                f"\n test eax,[{MOUSE+32}];"
                f"jz mouse_done;"
                f"\n cmp dword ptr [{MOUSE+36}],0x319530;"
                f"jne mouse_done;"
                f"\n mov ebx,[{MOUSE+8}];"
                f"mov ecx,[{MOUSE}];"
                f"mov edx,[{MOUSE+4}];"
                f"xor esi,esi;"
                f"xor edi,edi;"
                f"\n inc dword ptr [{STATE+8}];"
                f"push 0x23;"
                f"call 0x319530;"
                f"\n mouse_done:popad;"
                f"popfd;"
                f"ret;"
            )
        )
    )
    code = (
        f"\n cmp eax,8;"
        f"je input_blur;"
        f"\n cmp eax,0x100;"
        f"je input_key;"
        f"cmp eax,0x101;"
        f"je input_key;"
        f"cmp eax,0x104;"
        f"je input_key;"
        f"cmp eax,0x105;"
        f"je input_key;"
        f"\n cmp eax,0x200;"
        f"jb input_done;"
        f"cmp eax,0x209;"
        f"ja input_done;"
        f"\n mov [{STATE+12}],ebx;"
        f"mov [{STATE+16}],ecx;"
        f"\n push {RECT};"
        f"push dword ptr [{window.S}];"
        f"{win('GetClientRect')}test eax,eax;"
        f"jz input_done;"
        f"\n movsx eax,word ptr [{STATE+16}];"
        f"sub eax,[{window.S+0x90}];"
        f"mov ecx,[{window.S+0x98}];"
        f"mov esi,{MOUSE+12};"
        f"call {MAP};"
        f"\n mov edx,eax;"
        f"sub edx,[{MOUSE}];"
        f"add [{STATE+20}],edx;"
        f"mov [{MOUSE}],eax;"
        f"\n movsx eax,word ptr [{STATE+18}];"
        f"sub eax,[{window.S+0x94}];"
        f"mov ecx,[{window.S+0x9c}];"
        f"mov esi,{MOUSE+20};"
        f"call {MAP};"
        f"\n mov edx,eax;"
        f"sub edx,[{MOUSE+4}];"
        f"add [{STATE+24}],edx;"
        f"mov [{MOUSE+4}],eax;"
        f"\n mov ebx,[{STATE+12}];"
        f"mov edx,ebx;"
        f"and ebx,3;"
        f"shr edx,2;"
        f"and edx,4;"
        f"or ebx,edx;"
        f"\n mov ecx,[{MOUSE+8}];"
        f"xor ecx,ebx;"
        f"mov [{MOUSE+8}],ebx;"
        f"mov eax,1;"
        f"\n test ecx,1;"
        f"jz mouse_right;"
        f"or eax,4;"
        f"test ebx,1;"
        f"jz mouse_right;"
        f"xor eax,6;"
        f"\n mouse_right:test ecx,2;"
        f"jz mouse_middle;"
        f"or eax,16;"
        f"test ebx,2;"
        f"jz mouse_middle;"
        f"xor eax,24;"
        f"\n mouse_middle:test ecx,4;"
        f"jz mouse_dispatch;"
        f"or eax,64;"
        f"test ebx,4;"
        f"jz mouse_dispatch;"
        f"xor eax,96;"
        f"\n mouse_dispatch:call {DELIVER};"
        f"ret;"
        f"\n input_key:mov edx,ecx;"
        f"shr edx,16;"
        f"and edx,127;"
        f"jz input_done;"
        f"\n test ecx,0x01000000;"
        f"jz key_not_extended;"
        f"or edx,128;"
        f"\n key_not_extended:mov edi,edx;"
        f"mov eax,1;"
        f"test ecx,0x80000000;"
        f"jz key_make;"
        f"xor eax,eax;"
        f"\n key_make:mov [{PRESSED}+edi],al;"
        f"mov ebx,edx;"
        f"and ebx,127;"
        f"test eax,eax;"
        f"jnz key_press;"
        f"or ebx,128;"
        f"\n key_press:test edi,128;"
        f"jz key_send;"
        f"mov eax,0xe0;"
        f"call {KEY};"
        f"\n key_send:mov eax,ebx;"
        f"call {KEY};"
        f"ret;"
        f"\n input_blur:xor edi,edi;"
        f"\n blur_keys:cmp byte ptr [{PRESSED}+edi],0;"
        f"je blur_next;"
        f"mov byte ptr [{PRESSED}+edi],0;"
        f"\n test edi,128;"
        f"jz blur_basic;"
        f"mov eax,0xe0;"
        f"call {KEY};"
        f"\n blur_basic:mov eax,edi;"
        f"or eax,128;"
        f"call {KEY};"
        f"\n blur_next:inc edi;"
        f"cmp edi,256;"
        f"jb blur_keys;"
        f"\n mov ecx,[{MOUSE+8}];"
        f"mov dword ptr [{MOUSE+8}],0;"
        f"xor eax,eax;"
        f"\n test ecx,1;"
        f"jz blur_right;"
        f"or eax,4;"
        f"\n blur_right:test ecx,2;"
        f"jz blur_middle;"
        f"or eax,16;"
        f"\n blur_middle:test ecx,4;"
        f"jz blur_mouse;"
        f"or eax,64;"
        f"\n blur_mouse:call {DELIVER};"
        f"\n input_done:ret;"
        f"\n "
    )
    body = asm(HANDLE, code)
    assert len(body) < 0x1000
    write(HANDLE, body)


SKY = 0x1e47000


def sky_bodies():
    out = []
    # The legacy cap is in 320x200 asset pixels. Native canvases use square
    # pixels at 2.5 times the horizontal density; the art's original 6:5
    # vertical pixel aspect remains necessary, but 400-row doubling does not.
    out.append(
        (
            SKY,
            code(
                SKY, (
                    f"cmp dword ptr [0x44b1a0],0x9c34e8;"
                    f"jne original;"
                    f"\n  cmp ebp,0x28000;"
                    f"jle aspect;"
                    f"cmp ecx,0x28000;"
                    f"jle aspect;"
                    f"\n  mov ebp,0x28000;"
                    f"mov ecx,ebp;"
                    f"\n  aspect:push eax;"
                    f"push edx;"
                    f"push ebx;"
                    f"mov eax,ecx;"
                    f"mov ebx,6;"
                    f"imul ebx;"
                    f"\n  mov ebx,5;"
                    f"idiv ebx;"
                    f"mov ecx,eax;"
                    f"pop ebx;"
                    f"pop edx;"
                    f"pop eax;"
                    f"jmp 0x2a81c8;"
                    f"\n  original:cmp ebp,0x10000;"
                    f"jmp 0x2a81a8;"
                )
            )
        )
    )
    out.append((0x2a81a2, asm(0x2a81a2, f'jmp {SKY}') + b'\x90'))
    return out


def coordinate_source():
    return (
        "test eax,eax;"
        "jns map_positive;"
        "xor eax,eax;"
        "\n map_positive:dec ecx;"
        "cmp ecx,1;"
        "jl map_min;"
        "cmp eax,ecx;"
        "jle map_inside;"
        "mov eax,ecx;"
        "\n map_inside:mov edx,[esi+4];"
        "sub edx,[esi];"
        "imul eax,edx;"
        "xor edx,edx;"
        "div ecx;"
        "add eax,[esi];"
        "ret;"
        "\n map_min:mov eax,[esi];"
        "ret;"
    )


VIEWPORT_MAP = 0x1f75500


def viewport_mapping_bodies():
    source = (
        "push ebx;"
        "push edi;"
        "test eax,eax;"
        "jns positive;"
        "xor eax,eax;"
        "\n positive:dec ecx;"
        "cmp ecx,1;"
        "jl minimum;"
        "cmp eax,ecx;"
        "jle inside;"
        "mov eax,ecx;"
        "\n inside:mov edi,ecx;"
        "movzx ebx,word ptr [0x446f80];"
        "mov cl,[0x3644ce];"
        "\n cmp esi,0x1d0f00c;"
        "je scale;"
        "movzx ebx,word ptr [0x446f82];"
        "mov cl,[0x3644cf];"
        "\n scale:dec ebx;"
        "shl ebx,cl;"
        "imul eax,ebx;"
        "xor edx,edx;"
        "div edi;"
        "\n cmp eax,[esi];"
        "jge upper;"
        "minimum:mov eax,[esi];"
        "upper:cmp eax,[esi+4];"
        "jle done;"
        "mov eax,[esi+4];"
        "\n done:pop edi;"
        "pop ebx;"
        "ret;"
    )
    return [(VIEWPORT_MAP, asm(VIEWPORT_MAP, source)), (MAP, asm(MAP, f'jmp {VIEWPORT_MAP}'))]


def viewport_mapping_install(write, read):
    # Preserve the unmodified tail after the existing five-byte entry hook.
    original = asm(MAP, coordinate_source())
    if bytes(read(MAP + 5, len(original) - 5)) != original[5:]:
        raise ValueError('Viewport coordinate provider tail differs')
    pieces = viewport_mapping_bodies()
    size = len(pieces[0][1])
    return _install(
        pieces, {MAP: original[:5]},
        write,
        read,
        cold_state=((VIEWPORT_MAP + size, 0x100 - size), )
    )


# Windows owns the keyboard LEDs; retain the game's logical lock-key state.
KEYBOARD_SITE = 0x31a210
KEYBOARD_ORIGINAL = bytes.fromhex('53515256')
KEYBOARD_PATCH = bytes.fromhex('31c0c390')


def keyboard_bodies():
    return [(KEYBOARD_SITE, KEYBOARD_PATCH)]


def keyboard_install(write, read):
    return _install(keyboard_bodies(), {KEYBOARD_SITE: KEYBOARD_ORIGINAL}, write, read)


def keyboard_verify(read):
    return _verify(keyboard_bodies(), read)
