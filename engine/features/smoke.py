"""Keep smoke visible at native resolution and align its shot obstruction.

Clouds use the current particle positions, including drift and rotation, in a
separate sweep after solid terrain and units. The old fixed, bottomless cylinder
is skipped by that sweep. Shot/cloud identities keep the density decision stable
across frames; the particle library retains its elapsed-time movement.
"""
from patch_support import asm
from features import projectiles, terrain_distance

LOW, HIGH = 0x1d36000, 0x1d3a000
CODE, STATE, END = 0x1d3a000, 0x1d3b000, 0x1d3c000
SHOT_SERIAL, CLOUD_SERIAL = STATE + 0x100, STATE + 0x800
DRAW_MODE = STATE + 8
THIN_SITE, THIN_FILTER = 0x2a4264, CODE + 0x900
PARTICLE_CAPACITY_SITE, PARTICLE_CAPACITY = 0x244414, 4096
VISUAL_CAPACITY = 1024
CAPACITY_SITES, CAPACITY_QUERY = (0x2a4321, 0x2a433a), CODE + 0xa00
SMOKE_CIRCLES = (0x2a5a2b, 0x2a5a6e, 0x2a5afc)
SITES = {
    **{site: asm(site, 'mov eax,dword ptr [0x421a24]') for site in CAPACITY_SITES},
    THIN_SITE:
    asm(THIN_SITE, 'test dword ptr [esp+12],eax; je 0x2a4282'),
    PARTICLE_CAPACITY_SITE:
    asm(PARTICLE_CAPACITY_SITE, 'mov eax,1024'),
    0x2da1d0:
    asm(0x2da1d0, 'call 0x28b9e0'),
    0x2d96d5:
    asm(0x2d96d5, 'call 0x2f074c'),
    0x2d9db5:
    asm(0x2d9db5, 'call 0x2d9540'),
    0x2a62d3:
    bytes.fromhex('83c4185d5f'),
    0x2a59f3:
    bytes.fromhex('8d0cbd00000000'),
    terrain_distance.SCENERY_SITE:
    asm(terrain_distance.SCENERY_SITE, f'jmp {terrain_distance.SCENERY_CODE}'),
    **{site: asm(site, 'call 0x2a6af8') for site in SMOKE_CIRCLES},
}


def bodies(entry, regions):
    pieces = list(regions)

    def emit(address, source, capacity=0x100):
        body = asm(address, source)
        assert len(body) <= capacity
        pieces.append((address, body))

    # EBP is the original 30-byte projectile record. Its first word names the
    # object. Tail-entry preserves the return address used by other ray guards.
    emit(
        CODE, f'''
        pushfd; pushad;
        movzx eax,word ptr [ebp]; and eax,0x7fff;
        cmp eax,300; jae clear;
        mov eax,[eax*4+{SHOT_SERIAL}]; jmp set;
    clear: xor eax,eax;
    set: mov [{STATE+4}],eax;
        popad; popfd; jmp 0x2f074c;
    '''
    )
    emit(
        CODE + 0x100, f'''
        pushfd; pushad;
        and eax,0xffff; cmp eax,300; jae done;
        inc dword ptr [{STATE}]; mov edx,[{STATE}];
        mov [eax*4+{SHOT_SERIAL}],edx;
    done: popad; popfd; jmp 0x2d9540;
    '''
    )
    # Build the world matrix with the original transform, saving its renderer
    # scratch globals. The C caller owns the resulting twelve integers.
    emit(
        CODE + 0x200, f'''
        push ebp; mov ebp,esp; pushad; sub esp,96;
        mov esi,0x421930; mov edi,esp; mov ecx,12; cld; .byte 0xf3,0xa5;
        lea edi,[esp+48]; xor eax,eax; mov ecx,12; rep stosd;
        mov dword ptr [esp+48],65536;
        mov dword ptr [esp+64],65536;
        mov dword ptr [esp+80],65536;
        mov eax,0x421930; mov edx,[ebp+8];
        lea ebx,[esp+48]; lea ecx,[esp+84]; call 0x2a4ce8;
        mov eax,[ebp+8]; call 0x2a4d80;
        mov esi,0x421930; mov edi,[ebp+12]; mov ecx,12; .byte 0xf3,0xa5;
        mov esi,esp; mov edi,0x421930; mov ecx,12; .byte 0xf3,0xa5;
        add esp,96; popad; pop ebp; ret;
    ''', 0x180
    )
    emit(
        CODE + 0x400, f'''
        pushfd; pushad; cmp eax,256; jae done;
        inc dword ptr [{STATE}]; mov edx,[{STATE}];
        mov [eax*4+{CLOUD_SERIAL}],edx;
    done: popad; popfd;
        add esp,24; pop ebp; pop edi; jmp 0x2a62d8;
    '''
    )
    # Smoke used fixed pixel sizes even on a much larger canvas. Scale the
    # projected puff and its point/circle transition together. Other effects
    # and the separate beam-density work keep their existing appearance.
    # Behind-camera values stay on the original path. Saturate positive scaling
    # once every supported mode already reaches the largest raster circle, so
    # very close particles cannot overflow the multiply/divide or size arithmetic.
    emit(
        CODE + 0x500, f'''
        mov [{DRAW_MODE}],eax;
        cmp eax,0; je scale; cmp eax,1; je scale; cmp eax,8; jne done;
    scale:
        test edi,edi; jle done;
        push eax; push edx; push ecx;
        mov eax,[0x44b1a0]; movzx ecx,word ptr [eax+8];
        cmp ecx,320; jbe restore;
        mov eax,edi; mul ecx; test edx,edx; jne cap;
        mov ecx,320; div ecx; cmp eax,0x20000; jbe store;
    cap: mov eax,0x20000;
    store: mov edi,eax;
    restore: pop ecx; pop edx; pop eax;
    done: lea ecx,[edi*4]; jmp 0x2a59fa;
    '''
    )
    emit(
        CODE + 0x600, f'''
        cmp ecx,797; jne done;
        cmp dword ptr [0x44b1a0],0x9c34e8; jne done;
        cmp ebx,384; jae done; mov ebx,384;
    done: jmp {terrain_distance.SCENERY_CODE};
    '''
    )
    # The original circle drawer doubles mask rows when canvas height exceeds
    # 200. That suits its logical HUD, but makes smoke twice as tall as wide on
    # native world canvases. Expand the horizontal row spans in a stack-local
    # mask, preserving the current vertical size, center, shading and clipping.
    # A mode embedded in another particle type can reach these same calls;
    # DRAW_MODE retains the outer mode so that those effects stay unchanged.
    emit(
        CODE + 0x700, f'''
        pushfd;
        cmp dword ptr [{DRAW_MODE}],0; je canvas;
        cmp dword ptr [{DRAW_MODE}],1; je canvas;
        cmp dword ptr [{DRAW_MODE}],8; jne original;
    canvas:
        push eax; mov eax,[0x44b1a0];
        cmp eax,0x446f78; je logical;
        cmp word ptr [eax+10],200;
        pop eax; jle original;
        popfd; pushad; sub esp,144;
        lea eax,[ebx+0x8000]; cmp eax,0x10000; jl small;
        sar eax,15; cmp eax,65; jb index;
        mov eax,64;
    index:
        mov esi,[eax*4+0x423730];
        movzx ecx,byte ptr [esi+2]; cmp ecx,64; ja small;
        mov edi,esp; lodsb; add al,al; stosb;
        movsb; movsb; add ecx,ecx;
        test ecx,ecx; jz draw;
    span:
        lodsb; add al,al; stosb; loop span;
    draw:
        mov eax,[esp+172]; mov edx,[esp+164];
        mov ecx,[esp+168]; mov ebx,esp; call 0x2a6564;
        add esp,144; popad; ret;
    small:
        add esp,144; popad; jmp 0x2a6af8;
    logical:
        pop eax;
    original:
        popfd; jmp 0x2a6af8;
    ''', 0x200
    )
    # The particle allocator halves existing groups when it needs space. Smoke
    # also obstructs shots, so unrelated weapon effects must not remove it.
    # Preserve every particle in smoke draw modes; other groups retain the
    # original thinning rule and in-place compaction. The one-based group index
    # is on the original routine's stack. Empty, newly allocated groups never
    # reach this predicate, so their uninitialized draw mode is not consulted.
    emit(
        THIN_FILTER, '''
        push edx;
        mov edx,[esp+8]; dec edx; shl edx,4;
        add edx,[0x421a1c];
        cmp byte ptr [edx+14],0; je keep;
        cmp byte ptr [edx+14],1; je keep;
        cmp byte ptr [edx+14],8; je keep;
        pop edx;
        test dword ptr [esp+12],eax; je discard;
        jmp 0x2a426a;
    keep:
        pop edx; jmp 0x2a426a;
    discard:
        jmp 0x2a4282;
    '''
    )
    # Retain the original budget for visual particles. Enlarging the shared
    # allocation alone postpones thinning: Railgun trails become dense clouds
    # and fill the separate group table, leaving later shots without a trail.
    # Smoke counts against physical storage but has its own additional headroom.
    # The allocator calls this before and after thinning. Its newly reserved
    # group is empty, so skip empty intervals before reading their draw mode.
    emit(
        CAPACITY_QUERY, f'''
        pushfd; push ecx; push edx; push ebx; push esi; push edi;
        mov ecx,[0x421a0c]; mov esi,[0x421a14]; mov edi,[0x421a1c];
        xor edx,edx;
        test ecx,ecx; jz capacity;
    group:
        mov ebx,[esi+4]; sub ebx,[esi]; jle next;
        cmp byte ptr [edi+14],0; je smoke;
        cmp byte ptr [edi+14],1; je smoke;
        cmp byte ptr [edi+14],8; jne next;
    smoke:
        add edx,ebx;
    next:
        add esi,4; add edi,16; loop group;
    capacity:
        add edx,{VISUAL_CAPACITY}; mov eax,[0x421a24];
        cmp eax,edx; jbe done; mov eax,edx;
    done:
        pop edi; pop esi; pop ebx; pop edx; pop ecx; popfd; ret;
    '''
    )
    pieces += [
        *[(site, asm(site, f'call {CAPACITY_QUERY}')) for site in CAPACITY_SITES],
        (THIN_SITE, asm(THIN_SITE, f'jmp {THIN_FILTER}') + b'\x90'),
        # The original initializer allocates twelve bytes per particle from
        # this argument. Additional headroom is available to protected smoke;
        # CAPACITY_QUERY preserves visual-effect density within that storage.
        # Group/handle counts and the separate object/effect pools stay intact.
        (PARTICLE_CAPACITY_SITE, asm(PARTICLE_CAPACITY_SITE, f'mov eax,{PARTICLE_CAPACITY}')),
        (0x2da1d0, b'\x31\xc0\x90\x90\x90'),
        (0x2d96d5, asm(0x2d96d5, f'call {CODE}')),
        (0x2d9db5, asm(0x2d9db5, f'call {CODE+0x100}')),
        (0x2a62d3, asm(0x2a62d3, f'jmp {CODE+0x400}')),
        (0x2a59f3, asm(0x2a59f3, f'jmp {CODE+0x500}') + b'\x90\x90'),
        *[(site, asm(site, f'call {CODE+0x700}')) for site in SMOKE_CIRCLES],
        (terrain_distance.SCENERY_SITE, asm(terrain_distance.SCENERY_SITE, f'jmp {CODE+0x600}')),
        (
            projectiles.VEHICLE_POST, dict(projectiles.vehicle_bodies(entry,
                                                                      ()))[projectiles.VEHICLE_POST]
        ),
    ]
    return pieces


def install(write, read, *, entry, regions, mobile_entry):
    # This gap follows the Options reservation and ends before the host log.
    # Empty template bytes alone do not establish ownership: scenery tables
    # are empty too, then cleared and populated when a mission starts.
    from features import shot_assist
    if not shot_assist.END <= LOW < HIGH == CODE < STATE < END <= 0x1d40000:
        raise ValueError('Smoke storage leaves its declared host gap')
    pieces = bodies(entry, regions)
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    expected = dict(SITES)
    expected[projectiles.VEHICLE_POST] = dict(projectiles.vehicle_bodies(mobile_entry, ())
                                              )[projectiles.VEHICLE_POST]
    for a, b in expected.items():
        if bytes(read(a, len(b))) != b:
            raise ValueError(f'Smoke provider differs at {a:#x}')
    if any(read(LOW, END - LOW)):
        raise ValueError('Smoke helper reservation is occupied')
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])


def verify(read, *, entry, regions, **unused):
    from features.input_views import _verify
    return _verify(bodies(entry, regions), read)
