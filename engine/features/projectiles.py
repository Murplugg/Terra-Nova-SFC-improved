"""Physics remainder, projectile-only sweep profiles and partial-volley accounting.

Call-frame admission is explicit. Other ray users retain their original path.
"""
import struct
from patch_support import asm

REMAINDER = 0x44e0d8
HOOK = 0x311f2a
BRIDGE = 0x1d2e000
ORIGINAL = bytes.fromhex('a1d8e0440001028b3d91394500')


def _physics_emit(write, asm):
    write(
        BRIDGE,
        asm(
            BRIDGE, (
                f"mov eax,[{REMAINDER}];"
                f"mov dword ptr [{REMAINDER}],0;"
                f"add [edx],eax;"
                f"mov edi,[0x453991];"
                f"jmp {HOOK+len(ORIGINAL)};"
            )
        )
    )
    write(HOOK, asm(HOOK, f'jmp {BRIDGE}') + b'\x90' * (len(ORIGINAL) - 5))


CODE = 0x1dde000
LIMIT = CODE + 0x200
STATE = 0x1ddf000
HOOKS = {
    0x31154d: bytes.fromhex('8b1dc8e0440089c2'),
    0x3119b8: bytes.fromhex('8b542440c1e210a1c8e04400f7ea0facd010')
}


def _sweep_emit(write, asm, *, vehicle_call=None):
    caller = 'cmp dword ptr [edx+12],0x2d96da; jne original;'
    if vehicle_call is not None:
        if not isinstance(vehicle_call, int) or not 0x11000 <= vehicle_call <= 0x1fffff0:
            raise ValueError('Invalid vehicle sweep call')
        caller = (
            f"cmp dword ptr [edx+12],0x2d96da;"
            f"je valid;"
            f"cmp dword ptr [edx+12],{vehicle_call+5};"
            f"jne original;"
            f"mov edx,[edx];"
            f"cmp dword ptr [edx+4],0x2d96da;"
            f"jne original;"
            f"valid:"
        )
    # EAX is the actual traced segment length, before division by the cell step.
    # EBP+66 holds 2F074C's saved frame; its return address identifies our caller.
    body = (
        f"pushfd;"
        f" pushad;"
        f" mov dword ptr [{STATE}],0;"
        f"\n cmp dword ptr [ebp+0x72],0x2f07c6;"
        f" jne original;"
        f"\n mov edx,[ebp+0x66];"
        f" {caller}\n mov dword ptr [{STATE}],1;"
        f" mov [{STATE+4}],eax;"
        f" inc dword ptr [{STATE+8}];"
        f"\n mov ebx,[0x44e0c8];"
        f" test eax,eax;"
        f" jle zero;"
        f"\n xor edx,edx;"
        f" div ebx;"
        f" test edx,edx;"
        f" jz counted;"
        f" inc eax;"
        f"\n counted: mov [ebp+0x56],eax;"
        f" cmp eax,1;"
        f" jne finish;"
        f" inc dword ptr [{STATE+12}];"
        f" jmp finish;"
        f"\n zero: mov dword ptr [ebp+0x56],0;"
        f"\n finish: popad;"
        f" popfd;"
        f" mov ebx,[0x44e0c8];"
        f" mov edx,eax;"
        f" sar edx,16;"
        f" shl eax,16;"
        f" idiv ebx;"
        f" sar eax,16;"
        f" jmp 0x311563;"
        f"\n original: popad;"
        f" popfd;"
        f" mov ebx,[0x44e0c8];"
        f" mov edx,eax;"
        f" jmp 0x311555;"
    )
    b = asm(CODE, body)
    assert len(b) < 0x200
    write(CODE, b)
    body = (
        f"cmp dword ptr [{STATE}],0;"
        f" je original;"
        f"\n mov eax,[{STATE+4}];"
        f" mov edx,eax;"
        f" jmp 0x3119cc;"
        f"\n original: mov edx,[esp+0x40];"
        f" shl edx,16;"
        f" mov eax,[0x44e0c8];"
        f" imul edx;"
        f" shrd eax,edx,16;"
        f" jmp 0x3119ca;"
    )
    b = asm(LIMIT, body)
    assert len(b) < 0x200
    write(LIMIT, b)
    for a, dest in ((0x31154d, CODE), (0x3119b8, LIMIT)):
        write(a, asm(a, f'jmp {dest}') + b'\x90' * (len(HOOKS[a]) - 5))
    write(STATE, bytes(0x1000))


VOLLEY_CODE = 0x1fff000
VOLLEY_END = 0x1fff800
VOLLEY_SITES = {
    0x28f0b9: bytes.fromhex('83ec54'),
    0x28f2a8: bytes.fromhex('8a5d2889c2'),
    0x28f363: bytes.fromhex('6685c00f8e85040000'),
    0x28f3b9: bytes.fromhex('6685c00f8e2f040000'),
    0x28f410: bytes.fromhex('6685c00f8ed8030000'),
    0x28f467: bytes.fromhex('8b55f0668945f8'),
    0x28f4f0: bytes.fromhex('6685c00f8ef8020000'),
    0x28f542: bytes.fromhex('89c2668945f8')
}


def volley_bodies():
    out = [(0x28f0b9, bytes.fromhex('83ec58'))]

    def emit(a, s):
        b = asm(a, s)
        assert len(b) <= 0x100, (hex(a), len(b))
        out.append((a, b))

    def hook(site, a):
        out.append((site, asm(site, f'jmp {a}') + b'\x90' * (len(VOLLEY_SITES[site]) - 5)))

    emit(VOLLEY_CODE, ("mov [ebp-0x58],eax;"
                       "mov bl,[ebp+0x28];"
                       "mov edx,eax;"
                       "jmp 0x28f2ad;"))
    hook(0x28f2a8, VOLLEY_CODE)
    for i, (site, count, continuation, replay) in enumerate(
        [
            (0x28f363, 1, 0x28f36c, ''), (0x28f3b9, 2, 0x28f3c2, ''), (0x28f410, 3, 0x28f419, ''),
            (0x28f467, 4, 0x28f46e, 'mov edx,[ebp-0x10];mov [ebp-8],ax;'),
            (0x28f4f0, 1, 0x28f4f9, ''), (0x28f542, 2, 0x28f548, 'mov edx,eax;mov [ebp-8],ax;')
        ]
    ):
        a = VOLLEY_CODE + 0x100 * (i + 1)
        # First bolt already succeeded and actual-fire was checked before these
        # sites. ESI/EDI still identify the owner and weapon, as in the stock path.
        recoil = (
            (
                f"movsx eax,si;"
                f"imul eax,eax,37;"
                f"cmp byte ptr [eax+0x3c3241],1;"
                f"jne accounted;"
                f"\n   push ecx;"
                f"mov ecx,{count};"
                f"again:push ecx;"
                f"movsx eax,si;"
                f"call 0x2c6fa4;"
                f"pop ecx;"
                f"dec ecx;"
                f"jnz again;"
                f"pop ecx;"
                f"\n   accounted:"
            )
        ) if i < 4 else ''
        emit(
            a, (
                f"test ax,ax;"
                f"jg original;"
                f"mov ax,[ebp-0x58];"
                f"mov [ebp-8],ax;"
                f"\n   {recoil}jmp 0x28f5cc;"
                f"original:{replay}jmp {continuation};"
            )
        )
        hook(site, a)
    return out


def physics_bodies():
    pieces = []
    _physics_emit(lambda a, b: pieces.append((a, b)), asm)
    return pieces


def sweep_bodies(*, vehicle_call=None):
    pieces = []
    _sweep_emit(lambda a, b: pieces.append((a, b)), asm, vehicle_call=vehicle_call)
    return pieces


def install(write, read, *, part, vehicle_call=None):
    from features.input_views import _install
    pieces, sites = _part(part, vehicle_call)
    if all(bytes(read(a, len(b))) == b for a, b in pieces if part != 'sweep' or a != STATE):
        return dict(already_installed=True, ranges=[])
    return _install(pieces, sites, write, read)


def _part(part, vehicle_call):
    if part == 'physics':
        return physics_bodies(), {HOOK: ORIGINAL}
    if part == 'sweep':
        return sweep_bodies(vehicle_call=vehicle_call), HOOKS
    if part == 'volley':
        return volley_bodies(), VOLLEY_SITES
    raise ValueError('Unknown projectile feature')


def verify(read, *, part, vehicle_call=None):
    from features.input_views import _verify
    pieces, _ = _part(part, vehicle_call)
    return _verify([(a, b) for a, b in pieces if part != 'sweep' or a != STATE], read)


def volley_predecessor_view(ram):
    verify(lambda a, n: ram[a:a + n], part='volley')
    out = bytearray(ram)
    for a, b in volley_bodies():
        out[a:a + len(b)] = VOLLEY_SITES.get(a, bytes(len(b)))
    return out


# Fit both fuel-tank ray colliders to the packaged ftank model's extents.
FUEL_CODE = 0x1e5c400
FUEL_SHAPE = FUEL_CODE + 0x100
FUEL_SITES = (0x2db1dd, 0x2db23b)


def fuel_bodies():
    s = (
        f"cmp al,4;"
        f"jne scenery;"
        f"cmp dl,51;"
        f"je fuel;"
        f"jmp original;"
        f"\n scenery:test al,al;"
        f"jnz original;"
        f"cmp dl,55;"
        f"jne original;"
        f"\n fuel:and edx,255;"
        f"mov eax,{FUEL_SHAPE};"
        f"ret;"
        f"\n original:jmp 0x2973e8;"
    )
    b = asm(FUEL_CODE, s)
    assert len(b) < 0x100
    return [(FUEL_CODE, b), (FUEL_SHAPE, struct.pack('<HHii', 3, 0, 33748, 61641))] + [
        (a, asm(a, f'call {FUEL_CODE}')) for a in FUEL_SITES
    ]


# Model-fitted genbul1 wedge and conservative separate barge upper solids.
STATIC_CODE = 0x1fc3000
STATIC_LOOKUP = STATIC_CODE
STATIC_STATIC_LOOKUP = STATIC_CODE + 0x100
STATIC_DISPATCH = STATIC_CODE + 0x200
STATIC_ORIGINAL = STATIC_CODE + 0x500
STATIC_DATA = STATIC_CODE + 0x600
STATIC_GEN = STATIC_DATA
STATIC_BARGE = STATIC_DATA + 0x80
STATIC_CABIN = STATIC_DATA + 0x100
STATIC_POST = STATIC_DATA + 0x140
STATIC_CANOPY = STATIC_DATA + 0x180
STATIC_ENTRY = 0x2db27c
STATIC_ENTRY_BYTES = bytes.fromhex('5657558b742410')


def static_prism(x0, x1, y0, y1, heights):
    return struct.pack('<HH12i', 1, 4, x1, y1, x0, y1, x0, y0, x1, y0, *heights)


def static_bodies():
    # The live caller's EBX points to object transform (+15 in its 37-byte record).
    # Its class-4 instance status at +38 selects the damaged model variant.
    lookup = asm(
        STATIC_LOOKUP, (
            f"cmp al,4;"
            f"jne fallback;"
            f"cmp dl,50;"
            f"je check;"
            f"cmp dl,61;"
            f"jne fallback;"
            f"\n check:push ecx;"
            f"movzx ecx,word ptr [ebx-12];"
            f"imul ecx,ecx,121;"
            f"\n cmp byte ptr [ecx+0x39c7c8],0;"
            f"pop ecx;"
            f"jne fallback;"
            f"\n jmp {STATIC_STATIC_LOOKUP};"
            f"fallback:jmp {FUEL_CODE};"
        )
    )
    static = asm(
        STATIC_STATIC_LOOKUP, (
            f"cmp al,4;"
            f"jne fallback;"
            f"cmp dl,61;"
            f"je gen;"
            f"cmp dl,50;"
            f"je barge;"
            f"\n fallback:jmp {FUEL_CODE};"
            f"gen:mov eax,{STATIC_GEN};"
            f"ret;"
            f"barge:mov eax,{STATIC_BARGE};"
            f"ret;"
        )
    )
    # Compound input carries an original shape type plus raised component pointers.
    # Reuse original fixed-point segment/static_prism math, choosing the nearest fraction.
    dispatch = asm(
        STATIC_DISPATCH, (
            f"cmp edx,{STATIC_BARGE};"
            f"je compound;"
            f"jmp {STATIC_ORIGINAL};"
            f"\n compound:push ebp;"
            f"mov ebp,esp;"
            f"push ebx;"
            f"push esi;"
            f"push edi;"
            f"sub esp,64;"
            f"\n mov [ebp-16],eax;"
            f"mov [ebp-20],ebx;"
            f"mov [ebp-24],ecx;"
            f"\n mov dword ptr [ebp-28],0x10001;"
            f"mov dword ptr [ebp-32],0;"
            f"\n mov esi,{STATIC_BARGE+8};"
            f"mov edi,4;"
            f"\n loop:mov eax,[ebp-16];"
            f"mov ecx,[eax];"
            f"mov [ebp-64],ecx;"
            f"\n mov ecx,[eax+4];"
            f"mov [ebp-60],ecx;"
            f"mov ecx,[eax+8];"
            f"add ecx,[esi+4];"
            f"mov [ebp-56],ecx;"
            f"\n mov ecx,[eax+12];"
            f"mov [ebp-52],ecx;"
            f"mov cx,[eax+16];"
            f"mov [ebp-48],cx;"
            f"\n mov edx,[esi];"
            f"test edx,edx;"
            f"jnz ready;"
            f"mov eax,4;"
            f"mov edx,50;"
            f"call 0x2973e8;"
            f"mov edx,eax;"
            f"\n ready:lea eax,[ebp-36];"
            f"push eax;"
            f"push dword ptr [ebp+24];"
            f"push dword ptr [ebp+20];"
            f"\n push dword ptr [ebp+16];"
            f"push dword ptr [ebp+12];"
            f"push dword ptr [ebp+8];"
            f"\n lea eax,[ebp-64];"
            f"mov ebx,[ebp-20];"
            f"mov ecx,[ebp-24];"
            f"call {STATIC_ORIGINAL};"
            f"\n test al,al;"
            f"jz next;"
            f"mov eax,[ebp-36];"
            f"cmp eax,[ebp-28];"
            f"jae next;"
            f"\n mov [ebp-28],eax;"
            f"mov dword ptr [ebp-32],1;"
            f"\n next:add esi,8;"
            f"dec edi;"
            f"jnz loop;"
            f"\n mov eax,[ebp-32];"
            f"test eax,eax;"
            f"jz done;"
            f"mov edx,[ebp+28];"
            f"mov ecx,[ebp-28];"
            f"mov [edx],ecx;"
            f"\n done:add esp,64;"
            f"pop edi;"
            f"pop esi;"
            f"pop ebx;"
            f"pop ebp;"
            f"ret 24;"
        )
    )
    trampoline = STATIC_ENTRY_BYTES + asm(
        STATIC_ORIGINAL + len(STATIC_ENTRY_BYTES), f'jmp {STATIC_ENTRY+len(STATIC_ENTRY_BYTES)}'
    )
    assert len(lookup) < 0x100 and len(static) < 0x100 and len(dispatch) < 0x300
    return [
        (STATIC_LOOKUP, lookup),
        (STATIC_STATIC_LOOKUP, static),
        (STATIC_DISPATCH, dispatch),
        (STATIC_ORIGINAL, trampoline),
        (STATIC_GEN, static_prism(-36238, 36238, -138486, 138486, (71372, 102593, 102593, 71372))),
        (
            STATIC_BARGE,
            struct.pack(
                '<HHI8i', 4, 4, 50, 0, 0, STATIC_CABIN, 67427, STATIC_POST, 93692, STATIC_CANOPY,
                102170
            )
        ),
        # Model axes (x,y,z) become collider (z,x,-y). These boxes fit inside the
        # visible tapered cabin and narrow bridge support. The canopy is a separate
        # slab, so its overhang does not create solid air below it.
        (STATIC_CABIN, static_prism(-9492, 69014, -16735, 40455, (25870, ) * 4)),
        (STATIC_POST, static_prism(24939, 40457, -730, 22662, (8395, ) * 4)),
        (STATIC_CANOPY, static_prism(9384, 53641, -36286, 52907, (16860, ) * 4)),
        (FUEL_SITES[0], asm(FUEL_SITES[0], f'call {STATIC_LOOKUP}')),
        (FUEL_SITES[1], asm(FUEL_SITES[1], f'call {STATIC_STATIC_LOOKUP}')),
        (
            STATIC_ENTRY,
            asm(STATIC_ENTRY, f'jmp {STATIC_DISPATCH}') + b'\x90' * (len(STATIC_ENTRY_BYTES) - 5)
        )
    ]


# Supplement intact live heg_gun ray collision with its articulated upper mesh.
CANNON_CODE = 0x1fc4000
CANNON_LOOKUP = CANNON_CODE
CANNON_MARKER = CANNON_CODE + 0x100
CANNON_DISPATCH = CANNON_CODE + 0x200
CANNON_SCAN = CANNON_CODE + 0x600
CANNON_SCAN_SITE = 0x2da240
CANNON_SCAN_OLD = bytes.fromhex('a16c674400')


def cannon_bodies(mesh_entry, mesh_regions):
    lookup = asm(
        CANNON_LOOKUP, (
            f"cmp al,4;"
            f"jne fallback;"
            f"cmp dl,49;"
            f"jne fallback;"
            f"\n push ecx;"
            f"movzx ecx,word ptr [ebx-12];"
            f"imul ecx,ecx,121;"
            f"\n cmp byte ptr [ecx+0x39c7c8],0;"
            f"pop ecx;"
            f"jne fallback;"
            f"\n mov eax,{CANNON_MARKER};"
            f"ret;"
            f"fallback:jmp {STATIC_LOOKUP};"
        )
    )
    save = ';'.join(f'movdqu [ebp-{80+i*16}],xmm{i}' for i in range(8))
    restore = ';'.join(f'movdqu xmm{i},[ebp-{80+i*16}]' for i in range(8))
    dispatch = asm(
        CANNON_DISPATCH, (
            f"cmp edx,{CANNON_MARKER};"
            f"je cannon;"
            f"jmp {STATIC_DISPATCH};"
            f"\n cannon:push ebp;"
            f"mov ebp,esp;"
            f"push ebx;"
            f"push esi;"
            f"push edi;"
            f"sub esp,208;"
            f"\n {save};"
            f"stmxcsr [ebp-196];"
            f"\n mov [ebp-16],eax;"
            f"mov [ebp-48],ebx;"
            f"mov [ebp-44],ecx;"
            f"\n mov eax,[ebp+8];"
            f"mov [ebp-40],eax;"
            f"mov eax,[ebp+12];"
            f"mov [ebp-36],eax;"
            f"\n mov eax,[ebp+16];"
            f"mov [ebp-32],eax;"
            f"mov eax,[ebp+20];"
            f"mov [ebp-28],eax;"
            f"\n mov dword ptr [ebp-56],0x10001;"
            f"mov dword ptr [ebp-60],0;"
            f"\n mov eax,4;"
            f"mov edx,49;"
            f"call 0x2973e8;"
            f"mov edx,eax;"
            f"\n lea eax,[ebp-52];"
            f"push eax;"
            f"push dword ptr [ebp+24];"
            f"push dword ptr [ebp+20];"
            f"\n push dword ptr [ebp+16];"
            f"push dword ptr [ebp+12];"
            f"push dword ptr [ebp+8];"
            f"\n mov eax,[ebp-16];"
            f"mov ebx,[ebp-48];"
            f"mov ecx,[ebp-44];"
            f"call {STATIC_ORIGINAL};"
            f"\n test al,al;"
            f"jz mesh;"
            f"mov eax,[ebp-52];"
            f"mov [ebp-56],eax;"
            f"mov dword ptr [ebp-60],1;"
            f"\n mesh:mov eax,[ebp-16];"
            f"movzx ecx,word ptr [eax-12];"
            f"imul ecx,ecx,121;"
            f"\n movzx edx,word ptr [ecx+0x39c7c2];"
            f"push edx;"
            f"movzx edx,word ptr [ecx+0x39c7c0];"
            f"push edx;"
            f"\n lea edx,[ebp-48];"
            f"push edx;"
            f"push eax;"
            f"call {mesh_entry};"
            f"add esp,16;"
            f"\n test eax,eax;"
            f"js done;"
            f"cmp eax,[ebp-56];"
            f"jge done;"
            f"\n mov [ebp-56],eax;"
            f"mov dword ptr [ebp-60],1;"
            f"\n done:mov eax,[ebp-60];"
            f"test eax,eax;"
            f"jz end;"
            f"\n mov edx,[ebp+28];"
            f"mov ecx,[ebp-56];"
            f"mov [edx],ecx;"
            f"\n end:ldmxcsr [ebp-196];"
            f"{restore};"
            f"add esp,208;"
            f"pop edi;"
            f"pop esi;"
            f"pop ebx;"
            f"pop ebp;"
            f"ret 24;"
        )
    )
    # Include projecting barrels even outside the base's registered map cells.
    # The original per-cell nearest fraction and source exclusion stay in force.
    scan = asm(
        CANNON_SCAN, (
            f"push ecx;"
            f"push edx;"
            f"push ebx;"
            f"push esi;"
            f"push edi;"
            f"sub esp,4;"
            f"\n mov edi,1;"
            f"mov esi,0x3c3265;"
            f"\n loop:cmp byte ptr [esi],0;"
            f"je next;"
            f"cmp byte ptr [esi+1],4;"
            f"jne next;"
            f"\n cmp byte ptr [esi+2],49;"
            f"jne next;"
            f"\n mov eax,[0x446720];"
            f"mov eax,[eax+0x30];"
            f"cmp di,word ptr [eax*2+0x4464b8];"
            f"je next;"
            f"\n movzx eax,word ptr [esi+3];"
            f"imul eax,eax,121;"
            f"cmp byte ptr [eax+0x39c7c8],0;"
            f"jne next;"
            f"\n mov eax,[esi+15];"
            f"sar eax,16;"
            f"sub eax,[0x44676c];"
            f"add eax,7;"
            f"cmp eax,14;"
            f"ja next;"
            f"\n mov eax,[esi+19];"
            f"sar eax,16;"
            f"sub eax,[0x44675c];"
            f"add eax,7;"
            f"cmp eax,14;"
            f"ja next;"
            f"\n lea eax,[esp];"
            f"push eax;"
            f"mov eax,[0x446720];"
            f"push dword ptr [eax+0x2c];"
            f"\n push dword ptr [0x446748];"
            f"push dword ptr [0x446744];"
            f"push dword ptr [0x446740];"
            f"\n mov eax,edi;"
            f"mov edx,[0x446770];"
            f"mov ebx,[0x446774];"
            f"mov ecx,[0x446778];"
            f"call 0x2db1a4;"
            f"\n test al,al;"
            f"jz next;"
            f"cmp ebp,[esp];"
            f"jle next;"
            f"\n mov ebp,[esp];"
            f"mov eax,[esp+64];"
            f"mov [eax],di;"
            f"\n next:inc edi;"
            f"add esi,37;"
            f"cmp edi,300;"
            f"jb loop;"
            f"\n add esp,4;"
            f"pop edi;"
            f"pop esi;"
            f"pop ebx;"
            f"pop edx;"
            f"pop ecx;"
            f"mov eax,[0x44676c];"
            f"ret;"
        )
    )
    assert len(lookup) < 0x100 and len(dispatch) < 0x400 and len(scan) < 0xa00
    return [
        (CANNON_LOOKUP, lookup), (CANNON_MARKER, b'C66\0'), (CANNON_DISPATCH, dispatch),
        (CANNON_SCAN, scan), *mesh_regions,
        (FUEL_SITES[0], asm(FUEL_SITES[0], f'call {CANNON_LOOKUP}')),
        (STATIC_ENTRY, asm(STATIC_ENTRY, f'jmp {CANNON_DISPATCH}') + b'\x90' * 2),
        (CANNON_SCAN_SITE, asm(CANNON_SCAN_SITE, f'call {CANNON_SCAN}'))
    ]


# Supplement utility-vehicle shot/visibility rays with their intact mesh.
VEHICLE_CODE = 0x1fcf000
VEHICLE_CALL = VEHICLE_CODE + 0x400
VEHICLE_POST = VEHICLE_CODE + 0x500
VEHICLE_TRAMP = VEHICLE_CODE + 0x700
VEHICLE_SITE = 0x2f074c
VEHICLE_ORIGINAL = bytes.fromhex('56575589e5')

# The cylinder's fixed-point quadratic loses short horizontal segments. Keep
# its normal path, but intersect those short segments in double precision.
# The original shape has a solid top and no bottom plane. The result remains a
# fraction along the supplied segment, so callers can choose the nearest hit.
CYLINDER_SITE = 0x2dbaa0
CYLINDER_ORIGINAL = bytes.fromhex('56575583ec28')
CYLINDER_CODE = VEHICLE_CODE + 0x900
VERTICAL_SITE = 0x2da91d
VERTICAL_CODE = VEHICLE_CODE + 0xc00
VERTICAL_ORIGINAL = asm(VERTICAL_SITE, 'jl 0x2db061')


def vertical_bodies():
    """Let vertically moving projectiles inspect their current terrain cell.

    The original gate measures only XY travel and skips the whole cell when
    that distance is tiny. Reuse the sweep's projectile classification to keep
    a segment that changes height. Truly empty segments and other query types
    keep the original skip, and ordinary XY travel keeps its original path.
    """
    body = asm(VERTICAL_CODE, f'''
        jge ordinary;
        pushfd; push eax;
        cmp dword ptr [{STATE}],1; jne skip;
        mov eax,[0x446778]; cmp eax,[0x446748]; je skip;
        pop eax; popfd; jmp {VERTICAL_SITE+6};
    skip:
        pop eax; popfd; jmp 0x2db061;
    ordinary:
        jmp {VERTICAL_SITE+6};
    ''')
    assert len(body) < 0x100
    return [(VERTICAL_CODE, body),
            (VERTICAL_SITE, asm(VERTICAL_SITE, f'jmp {VERTICAL_CODE}') + b'\x90')]


def cylinder_bodies():
    """Retain the fixed-point admission threshold and repair its rejected case.

    The short path intersects two intervals: inside the XY circle, and below
    the top plane. Their overlap supplies the earliest contact in [0, 1].
    Match the original 0xAAA vertical conversion and open bottom. Preserve all
    XMM registers and MXCSR because visibility callers also use this routine.
    Stack doubles at 136/144 hold the interval; 168 holds the cylinder top.
    """
    save = ';'.join(f'movdqu [esp+{i*16}],xmm{i}' for i in range(8))
    restore = ';'.join(f'movdqu xmm{i},[esp+{i*16}]' for i in range(8))
    body = asm(CYLINDER_CODE, f'''
        push ebp; mov ebp,esp; pushad;
        mov edi,[ebp+12]; sub edi,ebx;
        mov eax,edi; imul edi; shrd eax,edx,16; mov esi,eax;
        mov eax,[ebp+16]; sub eax,ecx;
        imul eax; shrd eax,edx,16; add eax,esi;
        cmp eax,8; jge original;

        sub esp,192; {save}; stmxcsr [esp+128];
        mov esi,[ebp-4]; mov edx,[ebp-12];
        movzx eax,word ptr [edx+2]; lea edx,[edx+eax*8+4];
        cvtsi2sd xmm7,dword ptr [edx];
        cvtsi2sd xmm6,dword ptr [edx+4]; movsd [esp+168],xmm6;
        sub ebx,[esi]; sub ecx,[esi+4];
        cvtsi2sd xmm0,ebx; cvtsi2sd xmm1,ecx;
        cvtsi2sd xmm2,edi;
        mov eax,[ebp+16]; sub eax,[ebp-8]; cvtsi2sd xmm3,eax;

        movapd xmm4,xmm2; mulsd xmm4,xmm2;
        movapd xmm5,xmm3; mulsd xmm5,xmm3; addsd xmm4,xmm5;
        mulsd xmm2,xmm0; mulsd xmm3,xmm1;
        movapd xmm5,xmm2; addsd xmm5,xmm3;
        mulsd xmm0,xmm0; mulsd xmm1,xmm1;
        movapd xmm6,xmm0; addsd xmm6,xmm1;
        mulsd xmm7,xmm7; subsd xmm6,xmm7;

        xorpd xmm7,xmm7; movsd [esp+136],xmm7;
        mov eax,1; cvtsi2sd xmm0,eax; movsd [esp+144],xmm0;
        ucomisd xmm4,xmm7; je vertical;
        movapd xmm0,xmm5; mulsd xmm0,xmm5;
        mulsd xmm6,xmm4; subsd xmm0,xmm6;
        ucomisd xmm0,xmm7; jb miss;
        sqrtsd xmm0,xmm0;
        xorpd xmm1,xmm1; subsd xmm1,xmm5;
        movapd xmm2,xmm1; subsd xmm1,xmm0; addsd xmm2,xmm0;
        divsd xmm1,xmm4; divsd xmm2,xmm4;
        maxsd xmm1,[esp+136]; minsd xmm2,[esp+144];
        movsd [esp+136],xmm1; movsd [esp+144],xmm2;
        jmp height;
    vertical:
        ucomisd xmm6,xmm7; ja miss;
    height:
        mov eax,[ebp+8]; mov edx,0xaaa; imul edx;
        shrd eax,edx,16; sub eax,[esi+8]; cvtsi2sd xmm0,eax;
        mov eax,[ebp+20]; mov edx,0xaaa; imul edx;
        shrd eax,edx,16; sub eax,[esi+8]; cvtsi2sd xmm1,eax;
        subsd xmm1,xmm0;
        movsd xmm2,[esp+168]; subsd xmm2,xmm0;
        ucomisd xmm1,xmm7; je level;
        divsd xmm2,xmm1;
        jb descending;
        minsd xmm2,[esp+144]; movsd [esp+144],xmm2; jmp interval;
    descending:
        maxsd xmm2,[esp+136]; movsd [esp+136],xmm2; jmp interval;
    level:
        ucomisd xmm2,xmm7; jb miss;
    interval:
        movsd xmm0,[esp+136]; ucomisd xmm0,[esp+144]; ja miss;
        mov eax,65536; cvtsi2sd xmm1,eax; mulsd xmm0,xmm1;
        cvttsd2si eax,xmm0; mov edx,[ebp+28]; mov [edx],eax;
        mov byte ptr [ebp-4],1; jmp done;
    miss:
        mov byte ptr [ebp-4],0;
    done:
        ldmxcsr [esp+128]; {restore}; add esp,192;
        popad; pop ebp; ret 24;
    original:
        popad; pop ebp; push esi; push edi; push ebp; sub esp,0x28;
        jmp {CYLINDER_SITE+len(CYLINDER_ORIGINAL)};
    ''')
    assert len(body) <= 0x700
    return [(CYLINDER_CODE, body),
            (CYLINDER_SITE, asm(CYLINDER_SITE, f'jmp {CYLINDER_CODE}') + b'\x90')]


def vehicle_sweep_bodies(fixed=False):
    return dict(sweep_bodies(vehicle_call=VEHICLE_CALL if fixed else None))[CODE]


def vehicle_bodies(mesh_entry, mesh_regions):
    # Impact tracing leaves its last object in the shared no-body exclusion slot.
    # A later projectile segment can then ignore that object indefinitely. Give
    # ordinary projectile sweeps with no source body an empty exclusion for this
    # query, and restore the shared value for impact/visibility callers afterward.
    # The first segment's real source-body exclusion still prevents self hits.
    save = ';'.join(f'movdqu [ebp-{128+i*16}],xmm{i}' for i in range(8))
    restore = ';'.join(f'movdqu xmm{i},[ebp-{128+i*16}]' for i in range(8))
    pre = (
        f"push ebp;"
        f"mov ebp,esp;"
        f"sub esp,272;"
        f"{save};"
        f"stmxcsr [ebp-256];"
        f"\n mov [ebp-16],eax;"
        f"mov [ebp-20],edx;"
        f"mov [ebp-24],ebx;"
        f"mov [ebp-28],ecx;"
        f"mov dword ptr [ebp-72],0;"
        f"cmp dword ptr [ebp+4],0x2d96da;"
        f"jne exclusion_ready;"
        f"cmp dword ptr [ebp+16],0;"
        f"jne exclusion_ready;"
        f"mov cx,word ptr [0x4464b8];"
        f"mov [ebp-68],cx;"
        f"mov dword ptr [ebp-72],1;"
        f"mov word ptr [0x4464b8],0;"
        f"exclusion_ready:"
    )
    for i in range(3):
        pre += (
            f"mov ecx,[eax+{i*4}];"
            f"mov [ebp-{64-i*4}],ecx;"
            f"mov ecx,[edx+{i*4}];"
            f"mov [ebp-{52-i*4}],ecx;"
        )
    pre += (
        f"mov ecx,[ebp+12];"
        f"mov [ebp-40],ecx;"
        f"mov ecx,[ebp+16];"
        f"mov [ebp-36],ecx;"
        f"\n push dword ptr [ebp+32];"
        f"push dword ptr [ebp+28];"
        f"push dword ptr [ebp+24];"
        f"\n push dword ptr [ebp+20];"
        f"push dword ptr [ebp+16];"
        f"push dword ptr [ebp+12];"
        f"push dword ptr [ebp+8];"
        f"\n mov eax,[ebp-16];"
        f"mov edx,[ebp-20];"
        f"mov ebx,[ebp-24];"
        f"mov ecx,[ebp-28];"
        f"jmp {VEHICLE_CALL};"
    )
    post = (
        f"pushad;"
        f"push dword ptr [ebp+32];"
        f"push dword ptr [ebp+28];"
        f"push dword ptr [ebp+24];"
        f"push dword ptr [ebp-16];"
        f"push eax;"
        f"\n lea eax,[ebp-64];"
        f"push eax;"
        f"call {mesh_entry};"
        f"add esp,24;"
        f"mov [esp+28],eax;"
        f"pushfd;"
        f"cmp dword ptr [ebp-72],0;"
        f"je exclusion_restored;"
        f"mov ax,word ptr [ebp-68];"
        f"mov word ptr [0x4464b8],ax;"
        f"exclusion_restored:popfd;"
        f"popad;"
        f"\n ldmxcsr [ebp-256];"
        f"{restore};"
        f"mov esp,ebp;"
        f"pop ebp;"
        f"ret 28;"
    )
    pre = asm(VEHICLE_CODE, pre)
    post = asm(VEHICLE_POST, post)
    assert len(pre) < 0x400 and len(post) < 0x200
    return [
        (VEHICLE_CODE, pre),
        (VEHICLE_CALL, asm(VEHICLE_CALL, f'call {VEHICLE_TRAMP};jmp {VEHICLE_POST}')),
        (VEHICLE_POST, post),
        (VEHICLE_TRAMP, VEHICLE_ORIGINAL + asm(VEHICLE_TRAMP + 5, f'jmp {VEHICLE_SITE+5}')),
        (
            VEHICLE_CODE + 0x800,
            asm(VEHICLE_CODE + 0x800, 'mov eax,[esp+4];mov edx,[esp+8];jmp 0x29dd64;')
        ),
        (
            VEHICLE_CODE + 0x840,
            asm(
                VEHICLE_CODE + 0x840, (
                    "push ebx;"
                    "push esi;"
                    "push edi;"
                    "push ebp;"
                    "mov eax,[esp+20];"
                    "call 0x2d45cc;"
                    "pop ebp;"
                    "pop edi;"
                    "pop esi;"
                    "pop ebx;"
                    "ret;"
                )
            )
        ), *mesh_regions, (CODE, vehicle_sweep_bodies(True)),
        (VEHICLE_SITE, asm(VEHICLE_SITE, f'jmp {VEHICLE_CODE}'))
    ]


PBA_BRIDGE = 0x1eff000


def pba_bodies(mesh_entry, mesh_regions):
    bridge = asm(
        PBA_BRIDGE, (
            "push ebx;"
            "push esi;"
            "push edi;"
            "push ebp;"
            "mov eax,[esp+20];"
            "mov edx,[esp+24];"
            "call 0x280934;"
            "pop ebp;"
            "pop edi;"
            "pop esi;"
            "pop ebx;"
            "ret;"
        )
    )
    return [
        (VEHICLE_POST, dict(vehicle_bodies(mesh_entry, ()))[VEHICLE_POST]), (PBA_BRIDGE, bridge),
        *mesh_regions
    ]


def mobile_bodies(mesh_entry, mesh_regions):
    return [(VEHICLE_POST, dict(vehicle_bodies(mesh_entry, ()))[VEHICLE_POST]), *mesh_regions]


def fuel_install(write, read):
    """Fit the original two ray lookups without changing movement colliders."""
    from features.input_views import _install
    return _install(
        fuel_bodies(), {site: asm(site, 'call 0x2973e8')
                        for site in FUEL_SITES},
        write,
        read,
        cold_state=((FUEL_CODE, FUEL_SHAPE + 12 - FUEL_CODE), )
    )


def fuel_verify(read):
    from features.input_views import _verify
    return _verify(fuel_bodies(), read)


def static_contact_pieces(mesh_entry, mesh_regions):
    """Keep fitted shapes and cannon helpers; write final lookup hooks once."""
    replaced = (FUEL_SITES[0], STATIC_ENTRY)
    return (
        [(a, b) for a, b in static_bodies() if a not in replaced] +
        cannon_bodies(mesh_entry, mesh_regions)
    )


def static_contact_providers():
    return {
        **{
            site: asm(site, f'call {FUEL_CODE}')
            for site in FUEL_SITES
        },
        STATIC_ENTRY: STATIC_ENTRY_BYTES,
        CANNON_SCAN_SITE: CANNON_SCAN_OLD,
    }


def install_static_contacts(write, read, *, mesh_entry, mesh_regions):
    from features.input_views import _install, _verify
    # The two lookup hooks are deliberately superseded below; their underlying
    # fuel helper and shape must still be present and intact on every install.
    _verify([(a, b) for a, b in fuel_bodies() if a not in FUEL_SITES], read)
    return _install(
        static_contact_pieces(mesh_entry, mesh_regions), static_contact_providers(), write, read
    )


def verify_static_contacts(read, *, mesh_entry, mesh_regions):
    from features.input_views import _verify
    return _verify(
        static_contact_pieces(mesh_entry, mesh_regions) +
        [(a, b) for a, b in fuel_bodies() if a not in FUEL_SITES], read
    )


def mobile_contact_pieces(*, vehicle, pba, mobile):
    """Explicit compiled (entry, regions) inputs; one final shared ray callback.

    The compiled vehicle/PBA helpers remain part of the accepted layout and
    mobile collision implementation. No intermediate callback is installed.
    """
    parts = vehicle_bodies(*vehicle) + pba_bodies(*pba)
    return ([(a, b) for a, b in parts if a != VEHICLE_POST] + mobile_bodies(*mobile)
            + cylinder_bodies() + vertical_bodies())


def mobile_contact_providers():
    before = vehicle_sweep_bodies(False)
    after = vehicle_sweep_bodies(True)
    return {VEHICLE_SITE: VEHICLE_ORIGINAL, CODE: before.ljust(len(after), b'\0'),
            CYLINDER_SITE: CYLINDER_ORIGINAL, VERTICAL_SITE: VERTICAL_ORIGINAL}


def install_mobile_contacts(write, read, *, vehicle, pba, mobile):
    from features.input_views import _install
    return _install(
        mobile_contact_pieces(vehicle=vehicle, pba=pba, mobile=mobile), mobile_contact_providers(),
        write, read
    )


def verify_mobile_contacts(read, *, vehicle, pba, mobile):
    from features.input_views import _verify
    return _verify(mobile_contact_pieces(vehicle=vehicle, pba=pba, mobile=mobile), read)


# Converge unlocked direct-fire weapons on the surface under the reticle.
RETICLE_CODE = 0x1e59400
RETICLE_SITE = 0x2cceec


def reticle_bodies():
    s = (
        f"pushad;"
        f"push dword ptr [esp+40];"
        f"push dword ptr [esp+40];"
        f"call 0x2a28d0;"
        f"\n cmp word ptr [esp+0x4c],0;"
        f"jne done;"
        f"\n movzx eax,word ptr [0x441352];"
        f"imul eax,eax,0x582;"
        f"add eax,0x3a5608;"
        f"\n movzx edx,byte ptr [eax+0xce];"
        f"imul edx,edx,15;"
        f"movzx eax,byte ptr [eax+edx+0x45];"
        f"\n cmp eax,4;"
        f"jb done;"
        f"cmp eax,7;"
        f"ja done;"
        f"\n sub esp,80;"
        f"mov ebp,esp;"
        f"imul eax,eax,36;"
        f"movzx eax,word ptr [eax+0x39511e];"
        f"\n test eax,eax;"
        f"jz finished;"
        f"imul eax,eax,393216;"
        f"mov [ebp+36],eax;"
        f"\n mov esi,[ebp+120];"
        f"mov ebx,10;"
    )
    for axis, ptr in ((0, 100), (4, 96), (8, 104)):
        s += (
            f"mov ecx,[ebp+{ptr}];"
            f"mov eax,[ecx];"
            f"sub eax,[esi+{axis}];"
            f"cdq;"
            f"idiv ebx;"
            f"mov [ebp+{12+axis}],eax;"
            f"\n   mov eax,[esi+{axis}];"
            f"imul eax,eax,6;"
            f"mov [ebp+{axis}],eax;"
        )
    s += (
        "mov dword ptr [ebp+24],0;"
        "mov dword ptr [ebp+28],0;"
        "mov dword ptr [ebp+32],0;"
        "\n movzx eax,word ptr [0x441350];"
        "imul eax,eax,37;"
        "movzx edi,byte ptr [eax+0x3c3262];"
        "\n lea eax,[ebp+32];"
        "push eax;"
        "lea eax,[ebp+28];"
        "push eax;"
        "lea eax,[ebp+24];"
        "push eax;"
        "\n push edi;"
        "push edi;"
        "push dword ptr [ebp+36];"
        "push 0x1000;"
        "\n mov eax,ebp;"
        "lea edx,[ebp+12];"
        "mov ebx,0x640000;"
        "xor ecx,ecx;"
        "call 0x2f074c;"
        "\n mov ebx,6;"
    )
    for axis, ptr in ((0, 100), (4, 96), (8, 104)):
        s += (
            f"mov eax,[ebp+{axis}];"
            f"cdq;"
            f"idiv ebx;"
            f"mov ecx,[ebp+{ptr}];"
            f"mov [ecx],eax;"
        )
    s += 'finished:add esp,80;done:popad;ret 8;'
    b = asm(RETICLE_CODE, s)
    assert len(b) < 0x400
    return [(RETICLE_CODE, b), (RETICLE_SITE, asm(RETICLE_SITE, f'call {RETICLE_CODE}'))]


def reticle_install(write, read):
    from features.input_views import _install
    return _install(
        reticle_bodies(), {RETICLE_SITE: asm(RETICLE_SITE, 'call 0x2a28d0')},
        write,
        read,
        cold_state=((RETICLE_CODE, 0x400), )
    )


def reticle_verify(read):
    from features.input_views import _verify
    return _verify(reticle_bodies(), read)


# Keep friendly missile wall checks; seat newly deployed ASF turrets.
DEPLOY_CODE = 0x1e44800

DEPLOY_PLACE = DEPLOY_CODE + 0x100

DEPLOY_BODY = DEPLOY_CODE + 0x200

DEPLOY_SYNC = DEPLOY_CODE + 0x300

DEPLOY_END = DEPLOY_CODE + 0x600

DEPLOY_LOF_SITE = 0x252e25

DEPLOY_PLACE_SITE = 0x292610

DEPLOY_BODY_SITE = 0x2d4498

DEPLOY_SYNC_SITE = 0x2d3d02

DEPLOY_RADIUS = 0xc000

DEPLOY_HEIGHT = DEPLOY_RADIUS // 6

DEPLOY_ORIGINAL = {
    DEPLOY_LOF_SITE: bytes.fromhex('80fe017518'),
    DEPLOY_PLACE_SITE: asm(DEPLOY_PLACE_SITE, 'call 0x297400'),
    DEPLOY_BODY_SITE: asm(DEPLOY_BODY_SITE, 'call 0x2f0ccd'),
    DEPLOY_SYNC_SITE: asm(DEPLOY_SYNC_SITE, 'mov [esp+10],eax;mov ax,word ptr [ebx+0x3c325d]')
}


def deploy_bodies():
    lof = asm(
        DEPLOY_CODE, (
            "cmp dh,1;"
            "jne 0x252e42;"
            "\n        cmp byte ptr [edi+5],1;"
            "jne 0x252e2a;"
            "\n        cmp ebx,5;"
            "jle 0x252e2a;"
            "\n        cmp dl,10;"
            "je missile;"
            "cmp dl,30;"
            "je missile;"
            "\n        cmp dl,32;"
            "jne 0x252e2a;"
            "\n        missile:push eax;"
            "movzx eax,word ptr [0x446598];"
            "test eax,eax;"
            "jz solid;"
            "\n        cmp eax,300;"
            "jae transient;"
            "imul eax,eax,37;"
            "\n        cmp byte ptr [eax+0x3c3241],4;"
            "je solid;"
            "\n        transient:pop eax;"
            "jmp 0x252e2a;"
            "\n        solid:pop eax;"
            "jmp 0x252e42;"
        )
    )
    # Source ID is the ASF caller's existing local at record +0x34c.
    # Normal standing origin clearance here is ~0.85 m; allow up to 1.5 m.
    # Keep x/y, heading, ASF accounting, original footprint registration and
    # subsequent physics creation intact. Sample the actual forward drop point.
    place = asm(
        DEPLOY_PLACE, (
            f"pushfd;"
            f"pushad;"
            f"mov esi,eax;"
            f"\n        movzx edi,word ptr [esi+0x34c];"
            f"test edi,edi;"
            f"jz done;"
            f"\n        cmp edi,300;"
            f"jae done;"
            f"imul edi,edi,37;"
            f"add edi,0x3c3240;"
            f"\n        cmp byte ptr [edi],0;"
            f"je done;"
            f"cmp byte ptr [edi+1],1;"
            f"jne done;"
            f"\n        mov eax,[edi+15];"
            f"mov edx,[edi+19];"
            f"call 0x2949c4;"
            f"\n        mov edx,[edi+23];"
            f"sub edx,eax;"
            f"cmp edx,0x4000;"
            f"ja done;"
            f"\n        mov eax,[esi+2];"
            f"mov edx,[esi+6];"
            f"call 0x2949c4;"
            f"\n        mov [esi+10],eax;"
            f"\n        done:popad;"
            f"popfd;"
            f"jmp 0x297400;"
        )
    )
    # Keep stock type-46 model/muzzle coordinates at the base. The separate
    # physical sphere's center is radius metres higher. Shared class-4 creation
    # also handles mines: check both class and subtype before translating.
    body = asm(
        DEPLOY_BODY, (
            f"pushfd;"
            f"\n        cmp byte ptr [ebx+0x3c3241],4;"
            f"jne done;"
            f"\n        cmp byte ptr [ebx+0x3c3242],46;"
            f"jne done;"
            f"\n        add dword ptr [edx+8],{DEPLOY_RADIUS};"
            f"\n        done:popfd;"
            f"jmp 0x2f0ccd;"
        )
    )
    # This happens before the original sleep test can remove the physics body.
    # Preserve flags and every register except the intended converted Z/AX.
    sync = asm(
        DEPLOY_SYNC, (
            f"pushfd;"
            f"\n        cmp byte ptr [ebx+0x3c3241],4;"
            f"jne done;"
            f"\n        cmp byte ptr [ebx+0x3c3242],46;"
            f"jne done;"
            f"\n        sub eax,{DEPLOY_HEIGHT};"
            f"\n        done:popfd;"
            f"mov [esp+10],eax;"
            f"mov ax,word ptr [ebx+0x3c325d];"
            f"jmp 0x2d3d0d;"
        )
    )
    assert len(lof) <= 0x100 and len(place) <= 0x100 and len(body) <= 0x100 and len(
        sync
    ) <= DEPLOY_END - DEPLOY_SYNC
    return [
        (DEPLOY_CODE, lof), (DEPLOY_PLACE, place), (DEPLOY_BODY, body), (DEPLOY_SYNC, sync),
        (DEPLOY_LOF_SITE, asm(DEPLOY_LOF_SITE, f'jmp {DEPLOY_CODE}')),
        (DEPLOY_PLACE_SITE, asm(DEPLOY_PLACE_SITE, f'call {DEPLOY_PLACE}')),
        (DEPLOY_BODY_SITE, asm(DEPLOY_BODY_SITE, f'call {DEPLOY_BODY}')),
        (
            DEPLOY_SYNC_SITE, asm(DEPLOY_SYNC_SITE, f'jmp {DEPLOY_SYNC}') + b'\x90' *
            (len(DEPLOY_ORIGINAL[DEPLOY_SYNC_SITE]) - 5)
        )
    ]


def deploy_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        deploy_bodies(),
        DEPLOY_ORIGINAL,
        write,
        read,
        cold_state=((DEPLOY_CODE, DEPLOY_END - DEPLOY_CODE), )
    )


def deploy_verify(read):
    from features.input_views import _verify
    return _verify(deploy_bodies(), read)
