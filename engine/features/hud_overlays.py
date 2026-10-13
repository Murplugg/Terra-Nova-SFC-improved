"""Preserve original UI black and confine the host pointer during map drags."""
from patch_support import asm

CODE = 0x1fd3000
END = 0x1fd4000
POST = CODE
RECT = CODE + 0x300
CAPTURE = CODE + 0x500
RELEASE = CODE + 0x800
PROC = CODE + 0x900
WRAPPERS = CODE + 0xb00
STATE = CODE + 0xe00
STATE_SIZE = 0x100
NAMES = CODE + 0xf00
APIS = (
    'GetForegroundWindow', 'GetClientRect', 'ClientToScreen', 'ClipCursor', 'SetCapture',
    'ReleaseCapture', 'GetCapture'
)


def compositor_site():
    from features import render_compositor as compositor, hud, maps
    from features.render_arena import Layout, BASE
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    body = dict(compositor.bodies(Layout(BASE), hud, maps))[compositor.COMPOSE]
    found = [
        x.address for x in Cs(CS_ARCH_X86, CS_MODE_32).disasm(body, compositor.COMPOSE)
        if x.mnemonic == 'mov' and x.op_str == 'esi, 0x68500000'
    ]
    assert len(found) == 1, 'compositor must expose exactly one frame handoff'
    return found[0]


def sites():
    return {
        compositor_site(): asm(compositor_site(), 'mov esi,0x68500000'),
        0x1d19800: asm(0x1d19800, 'jmp 0x1e4a300'),
        0x263b55: asm(0x263b55, 'mov eax,[0x44b1a0]'),
        0x261bd8: asm(0x261bd8, 'jmp 0x1e40800'),
        **{
            a: asm(a, f'call {DRAG_CODE+i*0x80}')
            for i, (a, _, _) in enumerate(DRAG_SITES)
        }
    }


def bodies(imports):
    from features.input_views import api_slots
    api_slots(imports)
    postsite = compositor_site()
    out = []

    def emit(a, src, cap):
        b = asm(a, src.replace('rep stosd;', '.byte 0xf3,0xab;'))
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    # Compose retained UI rectangles after camera/map merges. Inactive tooltip
    # rectangles and hidden panels never affect world pixels. All drawing clips.
    emit(
        POST, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"\n cmp byte ptr [0x38fbfe],0;"
            f"je tooltip;"
            f"test byte ptr [0x35aef0],1;"
            f"jnz tooltip;"
            f"\n xor ebp,ebp;"
            f"panel:mov esi,[0x389df8+ebp*4];"
            f"cmp esi,0x11000;"
            f"jb nextpanel;"
            f"cmp esi,0x17fff00;"
            f"ja nextpanel;"
            f"\n movsx eax,word ptr [esi+8];"
            f"movsx edx,word ptr [esi+10];"
            f"movsx ebx,word ptr [esi+12];"
            f"movsx ecx,word ptr [esi+14];"
            f"\n cmp ebx,eax;"
            f"jle nextpanel;"
            f"cmp ecx,edx;"
            f"jle nextpanel;"
            f"\n dec eax;"
            f"dec edx;"
            f"inc ebx;"
            f"inc ecx;"
            f"\n push ecx;"
            f"lea ecx,[edx+1];"
            f"call {RECT};"
            f"pop ecx;"
            f"\n push edx;"
            f"lea edx,[ecx-1];"
            f"call {RECT};"
            f"pop edx;"
            f"\n push ebx;"
            f"lea ebx,[eax+1];"
            f"call {RECT};"
            f"pop ebx;"
            f"\n push eax;"
            f"lea eax,[ebx-1];"
            f"call {RECT};"
            f"pop eax;"
            f"\n nextpanel:inc ebp;"
            f"cmp ebp,3;"
            f"jb panel;"
            f"\n tooltip:cmp dword ptr [{STATE+36}],0;"
            f"je done;"
            f"\n movsx eax,word ptr [{STATE+96}];"
            f"movsx edx,word ptr [{STATE+98}];"
            f"movsx ebx,word ptr [{STATE+100}];"
            f"movsx ecx,word ptr [{STATE+102}];"
            f"\n call {RECT};"
            f"done:popad;"
            f"popfd;"
            f"mov esi,0x68500000;"
            f"ret;"
        ), 0x300
    )
    # Copy exact logical HUD colors (including black), nearest-neighbor at the
    # established integer X and shared ceil(12Y/5) edges. No palette key is used.
    emit(
        RECT, (
            "pushfd;"
            "pushad;"
            "test eax,eax;"
            "jns xok;"
            "xor eax,eax;"
            "xok:test edx,edx;"
            "jns yok;"
            "xor edx,edx;"
            "yok:\n cmp ebx,320;"
            "jle rok;"
            "mov ebx,320;"
            "rok:cmp ecx,400;"
            "jle bok;"
            "mov ecx,400;"
            "bok:\n sub ebx,eax;"
            "jle done;"
            "sub ecx,edx;"
            "jle done;"
            "\n mov ebp,ecx;"
            "imul esi,edx,320;"
            "add esi,eax;"
            "add esi,0x1e60000;"
            "push eax;"
            "\n row:mov edi,[0x68b04000+edx*4];"
            "mov ecx,[0x68b04004+edx*4];"
            "sub ecx,edi;"
            "imul edi,edi,1280;"
            "add edi,0x68500000;"
            "mov eax,[esp];"
            "lea edi,[edi+eax*4];"
            "\n scan:push ecx;"
            "push esi;"
            "push edi;"
            "mov ecx,ebx;"
            "pixel:movzx eax,byte ptr [esi];"
            "imul eax,eax,0x01010101;"
            "stosd;"
            "inc esi;"
            "loop pixel;"
            "\n pop edi;"
            "pop esi;"
            "pop ecx;"
            "add edi,1280;"
            "dec ecx;"
            "jnz scan;"
            "\n add esi,320;"
            "inc edx;"
            "dec ebp;"
            "jnz row;"
            "add esp,4;"
            "done:popad;"
            "popfd;"
            "ret;"
        ), 0x200
    )
    names = {}
    data = bytearray(b'user32.dll\0')
    for n in APIS:
        names[n] = NAMES + len(data)
        data.extend(n.encode() + b'\0')
    assert len(data) <= 0x100
    out.append((NAMES, bytes(data)))

    def api(n):
        return f'call dword ptr [{STATE+4+APIS.index(n)*4}];'

    code = (
        f"""pushfd;"""
        f"""pushad;"""
        f"""cmp dword ptr [{STATE}],0;"""
        f"""jne done;"""
        f"""cmp dword ptr [{STATE+32}],1;"""
        f"""je resolved;"""
        f"""push {NAMES};"""
        f"""call dword ptr [{imports["GetModuleHandleA"]}];"""
        f"""test eax,eax;"""
        f"""jz done;"""
        f"""mov ebp,eax;"""
    )
    for n in APIS:
        code += (
            f"""push {names[n]};"""
            f"""push ebp;"""
            f"""call dword ptr [{imports["GetProcAddress"]}];"""
            f"""test eax,eax;"""
            f"""jz done;"""
            f"""mov [{STATE+4+APIS.index(n)*4}],eax;"""
        )
    code += (
        f"mov dword ptr [{STATE+32}],1;"
        f"resolved:{api('GetForegroundWindow')}cmp eax,[0x1d1d000];"
        f"jne done;"
        f"\n test dword ptr [0x1d0f008],7;"
        f"jz done;"
        f"\n push {STATE+64};"
        f"push dword ptr [0x1d1d000];"
        f"{api('GetClientRect')}test eax,eax;"
        f"jz done;"
        f"\n push {STATE+64};"
        f"push dword ptr [0x1d1d000];"
        f"{api('ClientToScreen')}test eax,eax;"
        f"jz done;"
        f"\n push {STATE+72};"
        f"push dword ptr [0x1d1d000];"
        f"{api('ClientToScreen')}test eax,eax;"
        f"jz done;"
        f"\n push {STATE+64};"
        f"{api('ClipCursor')}test eax,eax;"
        f"jz done;"
        f"\n mov dword ptr [{STATE}],1;"
        f"push dword ptr [0x1d1d000];"
        f"{api('SetCapture')}\n {api('GetCapture')}cmp eax,[0x1d1d000];"
        f"je done;"
        f"call {RELEASE};"
        f"done:popad;"
        f"popfd;"
        f"ret;"
    )
    emit(CAPTURE, code, 0x300)
    emit(
        RELEASE, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [{STATE}],0;"
            f"je done;"
            f"mov dword ptr [{STATE}],0;"
            f"\n push 0;"
            f"{api('ClipCursor')}{api('GetCapture')}cmp eax,[0x1d1d000];"
            f"jne done;"
            f"{api('ReleaseCapture')}done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )
    emit(
        PROC, (
            f"pushfd;"
            f"pushad;"
            f"mov eax,[esp+44];"
            f"cmp eax,0x202;"
            f"je release;"
            f"cmp eax,0x205;"
            f"je release;"
            f"cmp eax,0x208;"
            f"je release;"
            f"\n cmp eax,8;"
            f"je release;"
            f"cmp eax,2;"
            f"je release;"
            f"cmp eax,0x1f;"
            f"je release;"
            f"cmp eax,0x215;"
            f"je release;"
            f"cmp eax,0x231;"
            f"je release;"
            f"\n jmp done;"
            f"release:call {RELEASE};"
            f"done:popad;"
            f"popfd;"
            f"jmp 0x1e4a300;"
        ), 0x200
    )
    out.extend(
        [(postsite, asm(postsite, f'call {POST}')), (0x1d19800, asm(0x1d19800, f'jmp {PROC}'))]
    )
    emit(
        CODE + 0xc00, (
            f"pushfd;"
            f"pushad;"
            f"mov dword ptr [{STATE+36}],1;"
            f"mov eax,[0x389db0];"
            f"mov [{STATE+96}],eax;"
            f"mov eax,[0x389db4];"
            f"mov [{STATE+100}],eax;"
            f"popad;"
            f"popfd;"
            f"mov eax,[0x44b1a0];"
            f"ret;"
        ), 0x100
    )
    emit(
        CODE + 0xd00, (f"pushfd;"
                       f"mov dword ptr [{STATE+36}],0;"
                       f"popfd;"
                       f"jmp 0x1e40800;"), 0x100
    )
    out.extend(
        [
            (0x263b55, asm(0x263b55, f'call {CODE+0xc00}')),
            (0x261bd8, asm(0x261bd8, f'jmp {CODE+0xd00}'))
        ]
    )
    for i, (site, _, _) in enumerate(DRAG_SITES):
        a = WRAPPERS + i * 0x40
        emit(a, f'call {CAPTURE};jmp {DRAG_CODE+i*0x80};', 0x40)
        out.append((site, asm(site, f'call {a}')))
    return out


"""Incremental map dragging, with no fixed-anchor mouse reset feedback."""
from patch_support import asm

DRAG_CODE = 0x1e59000
DRAG_SITES = (
    (0x26b448, 0x26b452, 0x38fc08), (0x2734e8, 0x2734f2, 0x38fffe), (0x273c95, 0x273c9f, 0x390002),
    (0x2740a8, 0x2740b2, 0x390006)
)


def drag_bodies():
    out = []
    for i, (site, warp, anchor) in enumerate(DRAG_SITES):
        address = DRAG_CODE + i * 0x80
        # Each signed 16-bit component is added independently: carry from x must
        # never contaminate y. Advance even at the map edge, preventing stored drag.
        body = asm(
            address, (
                f"pushfd;"
                f"push ecx;"
                f"add word ptr [{anchor}],dx;"
                f"mov ecx,edx;"
                f"sar ecx,16;"
                f"add word ptr [{anchor+2}],cx;"
                f"pop ecx;"
                f"popfd;"
                f"jmp 0x276cdc;"
            )
        )
        assert len(body) < 0x80
        out.extend(((address, body), (site, asm(site, f'call {address}')), (warp, b'\x90' * 5)))
    return out


def drag_setup(write, ram):
    if all(bytes(ram[a:a + len(b)]) == b for a, b in drag_bodies()):
        return dict(already_installed=True, ranges=[])
    for site, warp, anchor in DRAG_SITES:
        assert bytes(ram[site:site + 5]) == asm(site, 'call 0x276cdc'), hex(site)
        assert bytes(ram[warp:warp + 5]) == asm(warp, 'call 0x2e4a68'), hex(warp)
    assert not any(ram[DRAG_CODE:DRAG_CODE + 0x200])
    for a, b in drag_bodies():
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in drag_bodies()])


def drag_verify(ram):
    assert all(bytes(ram[a:a + len(b)]) == b for a, b in drag_bodies())
    return True


"""Map palette repair, retained arrow ink, and narrower tree movement solids."""
from patch_support import asm

WORLD_BASE = 0x1f75500
WORLD_MAPCOLOR = WORLD_BASE + 0x1300
WORLD_TREE = WORLD_BASE + 0x1400
WORLD_STATIC = WORLD_BASE + 0x1500
WORLD_DYNAMIC = WORLD_BASE + 0x1580
WORLD_ARROWS = WORLD_BASE + 0x1600
WORLD_TREEBUF = WORLD_BASE + 0x2300
WORLD_TREE_TYPES = (0, 1, 2, 9, 10, 11)


def world_bodies():
    out = []

    def emit(a, s, cap=0x100):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    from features.maps import palette_bodies
    out.extend(palette_bodies())
    # EDI/EBP identify class/species; EDX is the untouched resource collider.
    # A local scratch copy changes only the cylinder radius. Weapon rays use
    # separate entry points and never see the copy. No world/resource writes.
    emit(
        WORLD_TREE, (
            f"pushfd;"
            f"pushad;"
            f"test edi,edi;"
            f"jnz done;"
            f"\n cmp ebp,2;"
            f"jbe selected;"
            f"cmp ebp,9;"
            f"jb done;"
            f"cmp ebp,11;"
            f"ja done;"
            f"\n selected:cmp dword ptr [edx],0x60003;"
            f"jne done;"
            f"\n mov esi,edx;"
            f"mov edi,{WORLD_TREEBUF};"
            f"mov ecx,15;"
            f"cld;"
            f".byte 0xf3,0xa5;"
            f"\n mov eax,[{WORLD_TREEBUF+52}];"
            f"test eax,eax;"
            f"jle done;"
            f"shl eax,2;"
            f"xor edx,edx;"
            f"mov ecx,5;"
            f"div ecx;"
            f"\n mov [{WORLD_TREEBUF+52}],eax;"
            f"mov dword ptr [esp+20],{WORLD_TREEBUF};"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    emit(WORLD_STATIC, (f"add eax,[edx+2];"
                        f"mov edx,eax;"
                        f"call {WORLD_TREE};"
                        f"ret;"))
    emit(0x2979e8, f'call {WORLD_STATIC}')
    emit(
        WORLD_DYNAMIC, (
            f"push edi;"
            f"push ebp;"
            f"movzx edi,byte ptr [eax-14];"
            f"movzx ebp,byte ptr [eax-13];"
            f"\n call {WORLD_TREE};"
            f"pop ebp;"
            f"pop edi;"
            f"jmp 0x297a40;"
        )
    )
    emit(0x29799c, f'call {WORLD_DYNAMIC}')
    emit(
        WORLD_ARROWS, (
            f"pushfd;"
            f"pushad;"
            f"cmp byte ptr [0x38fbfe],0;"
            f"je done;"
            f"test byte ptr [0x35aef0],1;"
            f"jnz done;"
            f"\n mov esi,[0x389dec];"
            f"mov ebp,64;"
            f"\n scan:cmp esi,[0x389de8];"
            f"ja done;"
            f"mov eax,[esi+24];"
            f"cmp eax,0x2654d0;"
            f"je arrow;"
            f"cmp eax,0x2654e0;"
            f"jne next;"
            f"\n arrow:movsx eax,word ptr [esi+8];"
            f"movsx edx,word ptr [esi+10];"
            f"movsx ebx,word ptr [esi+12];"
            f"movsx ecx,word ptr [esi+14];"
            f"\n dec eax;"
            f"dec edx;"
            f"inc ebx;"
            f"inc ecx;"
            f"call {RECT};"
            f"\n next:add esi,0x62;"
            f"dec ebp;"
            f"jnz scan;"
            f"done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x200
    )
    return out


UI_CODE = 0x1f75500
UI_END = 0x1f77f00
UI_MAP = UI_CODE
UI_EXIT = UI_CODE + 0x100
UI_ASHFORD = UI_CODE + 0x200


def ui_bodies(imports, *, terminal_exit=True):
    out = []

    def emit(a, s):
        out.append((a, asm(a, s)))

    # Native absolute coordinates keep the full viewport scale when DOS changes
    # the permitted cursor rectangle. The rectangle clamps; it never stretches.
    from features.input_views import viewport_mapping_bodies
    out += viewport_mapping_bodies()
    # Only exiting the terminal gets its existing exit sound. Section navigation
    # and document Back continue to use their existing navigation behavior.
    from features.terminal import exit_bodies
    if terminal_exit:
        out += exit_bodies(asm)
    emit(
        UI_ASHFORD, (
            f"cmp eax,0x5ab0148;"
            f"jne original;"
            f"cmp ebp,3458;"
            f"jne original;"
            f"\n cmp dword ptr [0x359708],21;"
            f"jb original;"
            f"cmp dword ptr [0x359708],28;"
            f"ja original;"
            f"\n mov eax,{UI_ASHFORD+0x80};"
            f"ret;"
            f"original:jmp 0x2e3194;"
        )
    )
    out.append((UI_ASHFORD + 0x80, b'Deceased\0'))
    emit(0x2ba8cf, f'call {UI_ASHFORD}')
    from features import fps_display
    out += fps_display.bodies(imports, compositor_site())
    out += world_bodies()
    return out


def ui_sites(*, terminal_exit=True):
    """Original instructions and maintained providers replaced by this group."""
    from features.input_views import coordinate_source, MAP
    sources = {
        0x1e10465: 'call 0x2b60b4',
        0x1e104b8: 'call 0x2b60b4',
        0x2ba8cf: 'call 0x2e3194',
        0x2ca9b4: 'call 0x2cac54',
        0x2cab9d: 'call 0x2cac54',
        0x2ca450: ("push ebx;"
                   "push ecx;"
                   "push edx;"
                   "push esi;"
                   "push edi"),
        0x2cbbdc: 'call 0x2ca1e4',
        0x2cbc08: 'push ebx;push ecx;push edx;sub esp,12',
        0x277755: 'mov cl,[ecx];mov [esp+0x44],cl',
        0x1e44295: 'mov cl,[ecx];mov [esp+0x44],cl',
        0x2979e8: 'add eax,[edx+2];mov edx,eax',
        0x29799c: 'call 0x297a40',
        compositor_site(): f'call {POST}'
    }
    if not terminal_exit:
        from features.terminal import EXIT_SITES
        for a in EXIT_SITES:
            del sources[a]
    return {MAP: asm(MAP, coordinate_source())[:5], **{a: asm(a, s) for a, s in sources.items()}}


def _compositor_contract(read, hook):
    from features import render_compositor as compositor, hud, maps
    from features.render_arena import Layout, BASE
    expected = bytearray(dict(compositor.bodies(Layout(BASE), hud, maps))[compositor.COMPOSE])
    offset = compositor_site() - compositor.COMPOSE
    expected[offset:offset + 5] = hook
    if bytes(read(compositor.COMPOSE, len(expected))) != expected:
        raise ValueError('Overlay compositor provider differs')


def _dependencies(read, imports, *, ui, installed):
    from features.input_views import MAP, coordinate_source
    if ui:
        from features.fps_display import POST as final_post
        target = final_post if installed else POST
        _compositor_contract(read, asm(compositor_site(), f'call {target}'))
        for a, b in bodies(imports):
            if a != compositor_site() and bytes(read(a, len(b))) != b:
                raise ValueError('Black HUD/capture provider differs at ' + hex(a))
        original = asm(MAP, coordinate_source())
        if bytes(read(MAP + 5, len(original) - 5)) != original[5:]:
            raise ValueError('Coordinate provider tail differs')
    else:
        _compositor_contract(
            read,
            asm(compositor_site(), f'call {POST}') if installed else sites()[compositor_site()]
        )
        for a, b in drag_bodies():
            if a not in {s for s, _, _ in DRAG_SITES} and bytes(read(a, len(b))) != b:
                raise ValueError('Incremental map-drag provider differs')


def install(write, read, imports, *, ui=False, terminal_exit=True):
    """Offline, all-or-nothing admission; reservations are cold on first install."""
    from features.input_views import _install
    if not ui and not terminal_exit:
        raise ValueError('Terminal exit selection requires UI group')
    pieces = ui_bodies(imports, terminal_exit=terminal_exit) if ui else bodies(imports)
    complete = all(bytes(read(a, len(b))) == b for a, b in pieces)
    _dependencies(read, imports, ui=ui, installed=complete)
    start, end = (UI_CODE, UI_END) if ui else (CODE, END)
    return _install(
        pieces,
        ui_sites(terminal_exit=terminal_exit) if ui else sites(),
        write,
        read,
        cold_state=((start, end - start), )
    )


def verify(read, imports, *, ui=False):
    from features.input_views import _verify
    _dependencies(read, imports, ui=ui, installed=True)
    return _verify(ui_bodies(imports) if ui else bodies(imports), read)


def predecessor_view(ram, imports, *, ui=False):
    """Private snapshot compatibility: remove only this group's owned writes."""
    verify(lambda a, n: ram[a:a + n], imports, ui=ui)
    pieces = ui_bodies(imports) if ui else bodies(imports)
    providers = ui_sites() if ui else sites()
    out = bytearray(ram)
    for a, b in pieces:
        out[a:a + len(b)] = providers.get(a, bytes(len(b)))
    start, end = (UI_CODE, UI_END) if ui else (CODE, END)
    out[start:end] = bytes(end - start)
    return out
