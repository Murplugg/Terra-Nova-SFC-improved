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
SITES = {
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
        CODE + 0x500, '''
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
    pieces += [
        (0x2da1d0, b'\x31\xc0\x90\x90\x90'),
        (0x2d96d5, asm(0x2d96d5, f'call {CODE}')),
        (0x2d9db5, asm(0x2d9db5, f'call {CODE+0x100}')),
        (0x2a62d3, asm(0x2a62d3, f'jmp {CODE+0x400}')),
        (0x2a59f3, asm(0x2a59f3, f'jmp {CODE+0x500}') + b'\x90\x90'),
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
