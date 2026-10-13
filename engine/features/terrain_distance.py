"""Terrain distance, mesh storage and scenery profiles with explicit providers.

The extended view saves/restores caller projection settings. Terrain sampling
tiers and object visibility remain scoped to the owned native world canvas.
Mesh storage and final zoom/scenery profiles have combined cold installers.
Hook locations belong to the supported executable; retained helper bodies keep
the accepted image and snapshot layout stable during source consolidation.
"""
import struct
from patch_support import asm

DETAIL_ENTRY = 0x1de8000
DETAIL_SITE = 0x9a36e8
DETAIL_CANVAS = 0x9c34e8
DETAIL_COUNT = DETAIL_ENTRY + 0xf00


def detail_body():
    return asm(
        DETAIL_ENTRY, (
            f"\n cmp dword ptr [edx+28],{DETAIL_CANVAS};"
            f"jne original;"
            f"\n test byte ptr [edx+0x2e],3;"
            f"jz original;"
            f"\n push dword ptr [edx+0x2c];"
            f"push edx;"
            f"\n and byte ptr [edx+0x2e],0xfc;"
            f"\n inc dword ptr [{DETAIL_COUNT}];"
            f"call original;"
            f"\n pushfd;"
            f"push eax;"
            f"push edx;"
            f"\n mov edx,[esp+12];"
            f"mov eax,[esp+16];"
            f"shr eax,16;"
            f"\n mov [edx+0x2e],ax;"
            f"mov [0x41ebf2],ax;"
            f"\n pop edx;"
            f"pop eax;"
            f"popfd;"
            f"lea esp,[esp+8];"
            f"ret;"
            f"\n original:push ebx;"
            f"push ecx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"jmp 0x29edb9;"
            f"\n "
        )
    )


RAY_SITE = 0x2b564f
ENTRY = 0x1e48000
RAYS = 0x1e48400
OBJECT = 0x1e48800
CONFIG = 0x1e48f00
SITE = 0x9a36e8


def bodies():
    # Restore the caller's original render settings even across nested views.
    body = asm(
        ENTRY, (
            f"cmp dword ptr [edx+28],0x9c34e8;"
            f"jne original;"
            f"\n  cmp dword ptr [{CONFIG}],0;"
            f"je original;"
            f"\n  push dword ptr [edx+0x38];"
            f"push dword ptr [edx+0x3c];"
            f"push edx;"
            f"\n  shl word ptr [edx+0x38],1;"
            f"shl word ptr [edx+0x3a],1;"
            f"shl word ptr [edx+0x3c],1;"
            f"\n  call original;"
            f"pushfd;"
            f"push eax;"
            f"push edx;"
            f"\n  mov edx,[esp+12];"
            f"mov eax,[esp+20];"
            f"mov [edx+0x38],eax;"
            f"mov [0x41ebfc],eax;"
            f"\n  mov eax,[esp+16];"
            f"mov [edx+0x3c],eax;"
            f"mov [0x41ec00],eax;"
            f"\n  pop edx;"
            f"pop eax;"
            f"popfd;"
            f"lea esp,[esp+12];"
            f"ret;"
            f"\n  original:jmp 0x1de8000;"
        )
    )
    # The ray-marched terrain has independent sampling tiers and retains its
    # original polygon near mesh/cache. Do not enlarge that 64x64 vertex cache.
    ray = asm(
        RAYS, (
            f"call 0x2b53b0;"
            f"pushfd;"
            f"pushad;"
            f"\n  cmp dword ptr [0x44b1a0],0x9c34e8;"
            f"jne done;"
            f"\n  cmp dword ptr [{CONFIG}],0;"
            f"je done;"
            f"\n  cmp dword ptr [0x43ca64],6;"
            f"jne done;"
            f"\n  cmp dword ptr [0x43b734],30;"
            f"jne done;"
            f"cmp dword ptr [0x43b738],64;"
            f"jne done;"
            f"\n  cmp dword ptr [0x43b73c],100;"
            f"jne done;"
            f"cmp dword ptr [0x43b740],240;"
            f"jne done;"
            f"\n  cmp dword ptr [0x43b744],360;"
            f"jne done;"
            f"\n  mov dword ptr [0x43b734],60;"
            f"mov dword ptr [0x43b738],128;"
            f"\n  mov dword ptr [0x43b73c],200;"
            f"mov dword ptr [0x43b740],320;"
            f"mov dword ptr [0x43b744],480;"
            f"\n  done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    obj = asm(
        OBJECT, (
            f"cmp dword ptr [0x44b1a0],0x9c34e8;"
            f"jne original;"
            f"\n  cmp dword ptr [{CONFIG}],0;"
            f"je original;"
            f"add ebx,ebx;"
            f"\n  original:cmp eax,ebx;"
            f"setle al;"
            f"jmp 0x2a0ec0;"
        )
    )
    return [
        (ENTRY, body), (RAYS, ray), (OBJECT, obj), (SITE, asm(SITE, f'jmp {ENTRY}')),
        (RAY_SITE, asm(RAY_SITE, f'call {RAYS}')), (0x2a0ebb, asm(0x2a0ebb, f'jmp {OBJECT}'))
    ]


def sites():
    return {
        SITE: asm(SITE, f'jmp {DETAIL_ENTRY}'),
        RAY_SITE: asm(RAY_SITE, 'call 0x2b53b0'),
        0x2a0ebb: asm(0x2a0ebb, 'cmp eax,ebx;setle al')
    }


def verify(read):
    from features.input_views import _verify
    _verify(bodies() + [(DETAIL_ENTRY, detail_body())], read)
    if bytes(read(CONFIG, 4)) not in (bytes(4), b'\1\0\0\0'):
        raise ValueError('Invalid view-distance preference')
    return True


def install(write, read, *, enabled=1):
    from features.input_views import _install, _verify
    if type(enabled) is not int or enabled not in (0, 1):
        raise ValueError('Invalid view-distance preference')
    _verify([(DETAIL_ENTRY, detail_body())], read)
    pieces = bodies()
    value = enabled.to_bytes(4, 'little')
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        verify(read)
        if bytes(read(CONFIG, 4)) != value:
            write(CONFIG, value)
        return dict(already_installed=True, ranges=[(CONFIG, CONFIG + 4)])
    return _install(pieces + [(CONFIG, value)], sites(), write, read)


# Keep the four-sample terrain-lighting kernel inside its heightfield.
LIGHT_ENTRY = 0x1de6000
LIGHT_BOUNDARY_COUNT = LIGHT_ENTRY + 0xf00
LIGHT_SITES = (0x2b4819, 0x2b48c3, 0x2b496f, 0x2b4a1c)


def lighting_body():
    # Fine terrain is the original fixed 513-square grid. Coarse coordinates
    # use the same signed shifts, origins and dimensions as the original map.
    code = (
        "pushad;"
        "mov esi,eax;"
        "mov edi,edx;"
        "mov ebp,[0x35bfb4];"
        "\n    mov ebx,512;"
        "mov ecx,512;"
        "\n    cmp byte ptr [0x43cc10],0;"
        "je fine;"
        "\n    sar esi,2;"
        "sar edi,2;"
        "\n    movsx eax,word ptr [ebp+8];"
        "add esi,eax;"
        "\n    movsx eax,word ptr [ebp+10];"
        "add edi,eax;"
        "\n    movzx ebx,word ptr [ebp+4];"
        "dec ebx;"
        "\n    movzx ecx,word ptr [ebp+6];"
        "dec ecx;"
        "\n    add ebp,0x4a;"
        "jmp bounds;"
        "\n    fine:add ebp,0x84e;"
        "\n    bounds:cmp esi,ebx;"
        "jae edge;"
        "cmp edi,ecx;"
        "jae edge;"
        "\n    popad;"
        "call 0x2b3fd0;"
        "jmp 0x2b46d0;"
        "\n    edge:inc dword ptr [0x1de6f00];"
        "\n    lea edx,[esi+1];"
        "lea eax,[edi+1];"
    )
    # Clamp each of the four sample coordinates independently: an absent row
    # duplicates its nearest border row, rather than shifting the whole kernel.
    for reg, maximum in (('esi', 'ebx'), ('edx', 'ebx'), ('edi', 'ecx'), ('eax', 'ecx')):
        code += (
            f"test {reg},{reg};"
            f"jns nonnegative_{reg};"
            f"xor {reg},{reg};"
            f"\n        nonnegative_{reg}:cmp {reg},{maximum};"
            f"jle bounded_{reg};"
            f"mov {reg},{maximum};"
            f"\n        bounded_{reg}:"
        )
    code += (
        "mov edi,[ebp+edi*4];"
        "mov ebp,[ebp+eax*4];"
        "\n    lea esi,[esi+esi*2];"
        "lea edx,[edx+edx*2];"
        "\n    movzx eax,word ptr [edi+esi];"
        "shr eax,6;"
        "and eax,14;"
        "\n    movzx ebx,word ptr [edi+edx];"
        "shr ebx,6;"
        "and ebx,14;"
        "add eax,ebx;"
        "\n    movzx ecx,word ptr [ebp+esi];"
        "shr ecx,6;"
        "and ecx,14;"
        "add eax,ecx;"
        "\n    movzx edx,word ptr [ebp+edx];"
        "shr edx,6;"
        "and edx,14;"
        "add eax,edx;"
        "\n    shr eax,2;"
        "mov [esp+28],eax;"
        "popad;"
        "ret;"
    )
    result = asm(LIGHT_ENTRY, code)
    assert len(result) < 0xf00
    return result


# Extend textured terrain and actor visibility in owned native world views.
MESH_ENTRY = 0x1e56000
MESH_OBJECT = 0x1e56400
MESH_CONFIG = 0x1e56f00
MESH_SITE = SITE
MESH_ACTOR_SITE = 0x2a0ebb
MESH_ALLOCATIONS = (
    (0x2adf10, 0x7242, 4096 * 39), (0x2adf1f, 0x7d00, 8192 * 32),
    (0x2ab0d5, 0x3ec0, 4096 * 32 + 0x40)
)
MESH_QUALITY = (0x6b, 0x71, 0x75, 0x7b)


def mesh_bodies():
    s = (
        f"cmp dword ptr [edx+28],0x9c34e8;"
        f"jne original;"
        f"\n    cmp dword ptr [{CONFIG}],0;"
        f"je original;"
        f"\n    test dword ptr [{MESH_CONFIG}],1;"
        f"jz original;"
        f"\n    cmp word ptr [edx+0x58],2;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x5a],6;"
        f"jne original;"
        f"\n    cmp byte ptr [edx+0x68],2;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x69],2;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x6b],12;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x6d],1;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x75],12;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x77],30;"
        f"jne original;"
        f"\n    cmp word ptr [edx+0x79],1;"
        f"jne original;"
    )
    for off in MESH_QUALITY:
        s += f'push dword ptr [edx+{off}];mov word ptr [edx+{off}],24;'
    s += (f"push edx;"
          f"call {ENTRY};"
          f"pushfd;"
          f"push eax;"
          f"push edx;"
          f"mov edx,[esp+12];")
    for i, off in enumerate(reversed(MESH_QUALITY)):
        s += f'mov eax,[esp+{16+i*4}];mov [edx+{off}],eax;mov [{0x41ebc4+off}],eax;'
    s += (f"pop edx;"
          f"pop eax;"
          f"popfd;"
          f"lea esp,[esp+20];"
          f"ret;"
          f"original:jmp {ENTRY};")
    body = asm(MESH_ENTRY, s)
    assert len(body) < 0x400
    obj = asm(
        MESH_OBJECT, (
            f"cmp dword ptr [0x44b1a0],0x9c34e8;"
            f"jne original;"
            f"\n    cmp dword ptr [{CONFIG}],0;"
            f"je original;"
            f"\n    add ebx,ebx;"
            f"test dword ptr [{MESH_CONFIG}],2;"
            f"jz original;"
            f"\n    cmp ecx,128;"
            f"jb original;"
            f"cmp ecx,512;"
            f"jae original;"
            f"\n    lea ebx,[ebx+ebx*2];"
            f"shr ebx,1;"
            f"\n    original:cmp eax,ebx;"
            f"setle al;"
            f"jmp 0x2a0ec0;"
        )
    )
    assert len(obj) < 0x100
    return [
        (MESH_ENTRY, body), (MESH_OBJECT, obj), (MESH_SITE, asm(MESH_SITE, f'jmp {MESH_ENTRY}')),
        (MESH_ACTOR_SITE, asm(MESH_ACTOR_SITE, f'jmp {MESH_OBJECT}'))
    ] + [(a, struct.pack('<I', n)) for a, old, n in MESH_ALLOCATIONS]


# Keep the enlarged vertex/triangle arrays out of the bounded frame arena.
HEAP_ALLOC = 0x1e57000
HEAP_FREE = 0x1e57040
HEAP_ALLOC_SITES = (0x2adf14, 0x2adf23)
HEAP_FREE_SITES = (0x2adf3e, 0x2adf48)


def heap_bodies():
    a = asm(
        HEAP_ALLOC, (
            "push ebx;"
            "push ecx;"
            "push edx;"
            "call dword ptr [0x35f4a4];"
            "pop edx;"
            "pop ecx;"
            "pop ebx;"
            "ret;"
        )
    )
    b = asm(
        HEAP_FREE, (
            "push ebx;"
            "push ecx;"
            "push edx;"
            "call dword ptr [0x35f4ac];"
            "mov al,1;"
            "pop edx;"
            "pop ecx;"
            "pop ebx;"
            "ret;"
        )
    )
    return [(HEAP_ALLOC, a), (HEAP_FREE, b)] + [
        (s, asm(s, f'call {HEAP_ALLOC}')) for s in HEAP_ALLOC_SITES
    ] + [(s, asm(s, f'call {HEAP_FREE}')) for s in HEAP_FREE_SITES]


# Apply the bounded 24-cell mesh to both observed original detail presets.
PRESET_ENTRY = 0x1e58000
PRESET_SITE = MESH_SITE
PRESET_PROFILES = tuple(
    bytes.fromhex(x) for x in (
        '0100000200010000000200000202000c00010002000c0000000c001e0001000c001e0000',
        '0100000400010000000400000204000f00010004000f0000000f00220001000f00220000'
    )
)
assert all(len(profile) == 36 for profile in PRESET_PROFILES)


def preset_bodies():
    s = (
        f"cmp dword ptr [edx+28],0x9c34e8;"
        f"jne original;"
        f"\n cmp dword ptr [{CONFIG}],0;"
        f"je original;"
        f"\n test dword ptr [{MESH_CONFIG}],1;"
        f"jz original;"
        f"\n cmp word ptr [edx+0x58],2;"
        f"jne original;"
        f"\n cmp word ptr [edx+0x5a],6;"
        f"jne original;"
    )
    for i, profile in enumerate(PRESET_PROFILES):
        s += f'profile{i}:'
        fail = f'profile{i+1}' if i + 1 < len(PRESET_PROFILES) else 'original'
        for offset in range(0, len(profile), 4):
            value = int.from_bytes(profile[offset:offset + 4], 'little')
            s += f'cmp dword ptr [edx+{0x5c+offset}],{value};jne {fail};'
        s += 'jmp apply;'
    s += 'apply:'
    for offset in MESH_QUALITY:
        s += f'push dword ptr [edx+{offset}];mov word ptr [edx+{offset}],24;'
    s += (f"push edx;"
          f"call {ENTRY};"
          f"pushfd;"
          f"push eax;"
          f"push edx;"
          f"mov edx,[esp+12];")
    for i, offset in enumerate(reversed(MESH_QUALITY)):
        s += f'mov eax,[esp+{16+i*4}];mov [edx+{offset}],eax;mov [{0x41ebc4+offset}],eax;'
    s += (f"pop edx;"
          f"pop eax;"
          f"popfd;"
          f"lea esp,[esp+20];"
          f"ret;"
          f"original:jmp {ENTRY};")
    body = asm(PRESET_ENTRY, s)
    assert len(body) < 0x1000
    return [(PRESET_ENTRY, body), (PRESET_SITE, asm(PRESET_SITE, f'jmp {PRESET_ENTRY}'))]


# Retain the terrain-quality extension when zoom rebuilds live LOD distances.
ZOOM_CODE = 0x1e58400
ZOOM_END = 0x1e59000
ZOOM_SITE = PRESET_SITE
ZOOM_RAYS = ZOOM_CODE + 0x400
ZOOM_RAY_SITE = 0x2b564f
ZOOM_SITES = {
    ZOOM_SITE: asm(ZOOM_SITE, f'jmp {PRESET_ENTRY}'),
    ZOOM_RAY_SITE: asm(ZOOM_RAY_SITE, f'call {RAYS}')
}


def zoom_bodies():
    s = (
        f"cmp dword ptr [edx+28],0x9c34e8;"
        f"jne original;"
        f"\n cmp dword ptr [{CONFIG}],0;"
        f"je original;"
        f"test dword ptr [{MESH_CONFIG}],1;"
        f"jz original;"
        f"\n cmp word ptr [edx+0x58],2;"
        f"jne original;"
        f"cmp word ptr [edx+0x5a],6;"
        f"jne original;"
        f"\n cmp word ptr [edx+0x6b],24;"
        f"jae original;"
    )
    for i, profile in enumerate(PRESET_PROFILES):
        s += f'profile{i}:'
        fail = f'profile{i+1}' if i + 1 < len(PRESET_PROFILES) else 'original'
        # Each 12-byte tier has mode/current bounds/step/reference bounds.
        # Zoom legitimately rewrites the current bounds at +1 and +3 only.
        for t in (0, 12, 24):
            s += f'cmp byte ptr [edx+{0x5c+t}],{profile[t]};jne {fail};'
            for off in (5, 7, 9):
                value = int.from_bytes(profile[t + off:t + off + 2], 'little')
                s += f'cmp word ptr [edx+{0x5c+t+off}],{value};jne {fail};'
        s += 'jmp apply;'
    s += 'apply:'
    for off in MESH_QUALITY:
        s += f'push dword ptr [edx+{off}];mov word ptr [edx+{off}],24;'
    s += (f"push edx;"
          f"call {ENTRY};"
          f"pushfd;"
          f"push eax;"
          f"push edx;"
          f"mov edx,[esp+12];")
    for i, off in enumerate(reversed(MESH_QUALITY)):
        s += f'mov eax,[esp+{16+i*4}];mov [edx+{off}],eax;mov [{0x41ebc4+off}],eax;'
    s += (f"pop edx;"
          f"pop eax;"
          f"popfd;"
          f"lea esp,[esp+20];"
          f"ret;"
          f"original:jmp {ENTRY};")
    b = asm(ZOOM_CODE, s)
    assert len(b) < ZOOM_END - ZOOM_CODE
    # Recognize the reference preset, which zoom does not rewrite. Apply the
    # existing quality ratios to the zoom-adjusted distances, before traversal.
    r = (
        f"call 0x2b53b0;"
        f"pushfd;"
        f"pushad;"
        f"\n cmp dword ptr [0x44b1a0],0x9c34e8;"
        f"jne done;"
        f"\n cmp dword ptr [{CONFIG}],0;"
        f"je done;"
        f"\n cmp dword ptr [0x43ca64],6;"
        f"jne done;"
    )
    for tier, end in ((2, 30), (3, 64), (4, 100), (5, 240)):
        r += f'cmp word ptr [{0x43cb50+0x5c+tier*12+9}],{end};jne done;'
    for i in range(1, 6):
        at = 0x43b730 + i * 4
        r += f'mov eax,[{at}];'
        if i <= 3:
            r += 'add eax,eax;'
        else:
            r += ("shl eax,2;"
                  "xor edx,edx;"
                  "mov ecx,3;"
                  "div ecx;")
        r += (f"cmp eax,998;"
              f"jbe ok{i};"
              f"mov eax,998;"
              f"ok{i}:mov [{at}],eax;")
    r += 'done:popad;popfd;ret;'
    rb = asm(ZOOM_RAYS, r)
    assert len(b) < 0x400 and len(rb) < 0x400
    return [
        (ZOOM_CODE, b), (ZOOM_RAYS, rb), (ZOOM_SITE, asm(ZOOM_SITE, f'jmp {ZOOM_CODE}')),
        (ZOOM_RAY_SITE, asm(ZOOM_RAY_SITE, f'call {ZOOM_RAYS}'))
    ]


# Apply the existing ray-detail extension to both High and Excellent.
QUALITY_CODE = ZOOM_CODE + 0x800
QUALITY_END = ZOOM_END
QUALITY_SITE = ZOOM_RAY_SITE
QUALITY_SITES = {QUALITY_SITE: asm(QUALITY_SITE, f'call {ZOOM_RAYS}')}
QUALITY_PROFILES = ((30, 64, 100, 240), (34, 68, 120, 280))


def quality_bodies():
    s = (
        f"call 0x2b53b0;"
        f"pushfd;"
        f"pushad;"
        f"\n cmp dword ptr [0x44b1a0],0x9c34e8;"
        f"jne done;"
        f"\n cmp dword ptr [{CONFIG}],0;"
        f"je done;"
        f"cmp dword ptr [0x43ca64],6;"
        f"jne done;"
    )
    for k, profile in enumerate(QUALITY_PROFILES):
        fail = f'profile{k+1}' if k + 1 < len(QUALITY_PROFILES) else 'done'
        s += f'profile{k}:'
        for tier, end in zip(range(2, 6), profile):
            s += f'cmp word ptr [{0x43cb50+0x5c+tier*12+9}],{end};jne {fail};'
        s += 'jmp apply;'
    s += 'apply:'
    for i in range(1, 6):
        at = 0x43b730 + i * 4
        s += f'mov eax,[{at}];'
        s += 'add eax,eax;' if i <= 3 else ("shl eax,2;"
                                            "xor edx,edx;"
                                            "mov ecx,3;"
                                            "div ecx;")
        s += (f"cmp eax,998;"
              f"jbe ok{i};"
              f"mov eax,998;"
              f"ok{i}:mov [{at}],eax;")
    s += 'done:popad;popfd;ret;'
    b = asm(QUALITY_CODE, s)
    assert len(b) < QUALITY_END - QUALITY_CODE
    return [(QUALITY_CODE, b), (QUALITY_SITE, asm(QUALITY_SITE, f'call {QUALITY_CODE}'))]


# Keep the fine-map / landscape-map handoff from receding with zoom.
HANDOFF_CODE = 0x1e3b800
HANDOFF_END = 0x1e3c000
HANDOFF_SITE = QUALITY_SITE
HANDOFF_SITES = {HANDOFF_SITE: asm(HANDOFF_SITE, f'call {QUALITY_CODE}')}


def handoff_bodies():
    s = (
        f"call {QUALITY_CODE};"
        f"pushfd;"
        f"pushad;"
        f"\n cmp dword ptr [0x44b1a0],0x9c34e8;"
        f"jne done;"
        f"\n cmp dword ptr [{CONFIG}],0;"
        f"je done;"
        f"\n cmp dword ptr [0x43ca64],6;"
        f"jne done;"
    )
    for k, profile in enumerate(QUALITY_PROFILES):
        fail = f'profile{k+1}' if k + 1 < len(QUALITY_PROFILES) else 'done'
        s += f'profile{k}:'
        for tier, end in zip(range(2, 6), profile):
            s += f'cmp word ptr [{0x43cb50+0x5c+tier*12+9}],{end};jne {fail};'
        s += f'mov eax,{profile[1]*2};jmp apply;'
    s += (
        "apply:cmp [0x43b738],eax;"
        "jbe done;"
        "mov [0x43b738],eax;"
        "\n cmp [0x43b734],eax;"
        "jbe done;"
        "mov [0x43b734],eax;"
        "\n done:popad;"
        "popfd;"
        "ret;"
    )
    b = asm(HANDOFF_CODE, s)
    assert len(b) < HANDOFF_END - HANDOFF_CODE
    return [(HANDOFF_CODE, b), (HANDOFF_SITE, asm(HANDOFF_SITE, f'call {HANDOFF_CODE}'))]


# Increase natural scenery cutoffs by 50%, retaining the terrain footprint.
SCENERY_CODE = 0x1e5d800
SCENERY_SITE = MESH_ACTOR_SITE
SCENERY_SCENERY = SCENERY_CODE + 0x200
SCENERY_SCENERY_SITE = 0x2a0e38
SCENERY_SCENERY_OLD = bytes.fromhex('8a8403c0ec4100')
SCENERY_GATHER = SCENERY_CODE + 0x400


def scenery_bodies():
    b = asm(
        SCENERY_CODE, (
            f"cmp dword ptr [0x44b1a0],0x9c34e8;"
            f"jne original;"
            f"\n cmp dword ptr [{CONFIG}],0;"
            f"je original;"
            f"\n add ebx,ebx;"
            f"cmp ecx,26;"
            f"jb extend;"
            f"cmp ecx,52;"
            f"je extend;"
            f"\n test dword ptr [{MESH_CONFIG}],2;"
            f"jz original;"
            f"\n cmp ecx,128;"
            f"jb original;"
            f"cmp ecx,512;"
            f"jae original;"
            f"\n extend:lea ebx,[ebx+ebx*2];"
            f"shr ebx,1;"
            f"\n original:cmp eax,ebx;"
            f"setle al;"
            f"jmp 0x2a0ec0;"
        )
    )
    assert len(b) < 0x200
    s = asm(
        SCENERY_SCENERY, (
            f"push ecx;"
            f"mov ecx,eax;"
            f"add ecx,ebx;"
            f"\n movzx eax,byte ptr [ecx+0x41ecc0];"
            f"shl eax,2;"
            f"\n cmp dword ptr [0x44b1a0],0x9c34e8;"
            f"jne original;"
            f"\n cmp dword ptr [{CONFIG}],0;"
            f"je original;"
            f"\n cmp ecx,26;"
            f"jb extend;"
            f"cmp ecx,52;"
            f"jne original;"
            f"\n extend:lea eax,[eax+eax*2];"
            f"shr eax,1;"
            f"\n original:imul edx,dword ptr [esp];"
            f"pop ecx;"
            f"\n cmp edx,eax;"
            f"setle al;"
            f"jmp 0x2a0e4f;"
        )
    )
    assert len(s) < 0x200
    # Ray terrain already continues farther. Its +0x38 cutoff stops collecting
    # scenery/objects earlier. Extend that collection radius, not terrain tiers.
    g = asm(
        SCENERY_GATHER, (
            f"cmp dword ptr [edx+28],0x9c34e8;"
            f"jne original;"
            f"\n cmp dword ptr [{CONFIG}],0;"
            f"je original;"
            f"\n push dword ptr [edx+0x38];"
            f"push dword ptr [edx+0x3c];"
            f"push edx;"
            f"\n push eax;"
            f"movzx eax,word ptr [edx+0x38];"
            f"lea eax,[eax+eax*2];"
            f"\n mov [edx+0x38],ax;"
            f"pop eax;"
            f"\n shl word ptr [edx+0x3a],1;"
            f"shl word ptr [edx+0x3c],1;"
            f"\n call original;"
            f"pushfd;"
            f"push eax;"
            f"push edx;"
            f"\n mov edx,[esp+12];"
            f"mov eax,[esp+20];"
            f"mov [edx+0x38],eax;"
            f"mov [0x41ebfc],eax;"
            f"\n mov eax,[esp+16];"
            f"mov [edx+0x3c],eax;"
            f"mov [0x41ec00],eax;"
            f"\n pop edx;"
            f"pop eax;"
            f"popfd;"
            f"lea esp,[esp+12];"
            f"ret;"
            f"\n original:jmp 0x1de8000;"
        )
    )
    assert len(g) < 0x200
    return [
        (SCENERY_CODE, b), (SCENERY_SCENERY, s), (SCENERY_GATHER, g),
        (ENTRY, asm(ENTRY, f'jmp {SCENERY_GATHER}')),
        (SCENERY_SITE, asm(SCENERY_SITE, f'jmp {SCENERY_CODE}')),
        (SCENERY_SCENERY_SITE, asm(SCENERY_SCENERY_SITE, f'jmp {SCENERY_SCENERY}') + b'\x90' * 2)
    ]


# Give unzoomed main-view scenery the previous first-zoom collection range.
RANGE_CODE = 0x1e4fc00
RANGE_END = 0x1e50000
RANGE_SITE = ENTRY
RANGE_SITES = {RANGE_SITE: asm(RANGE_SITE, f'jmp {SCENERY_GATHER}')}


def scenery_range_bodies():
    s = (
        f"cmp dword ptr [edx+28],0x9c34e8;"
        f"jne original;"
        f"\n cmp dword ptr [{CONFIG}],0;"
        f"je original;"
        f"\n cmp dword ptr [edx],0x10000;"
        f"jne original;"
        f"\n push dword ptr [edx+0x38];"
        f"push edx;"
        f"push eax;"
        f"push ecx;"
        f"push edx;"
        f"\n movzx eax,word ptr [edx+0x38];"
        f"imul eax,eax,7;"
        f"\n xor edx,edx;"
        f"mov ecx,5;"
        f"div ecx;"
        f"\n cmp eax,21845;"
        f"jbe bounded;"
        f"mov eax,21845;"
        f"\n bounded:pop edx;"
        f"mov [edx+0x38],ax;"
        f"pop ecx;"
        f"pop eax;"
        f"\n call original;"
        f"pushfd;"
        f"push eax;"
        f"push edx;"
        f"\n mov edx,[esp+12];"
        f"mov eax,[esp+16];"
        f"mov [edx+0x38],eax;"
        f"mov [0x41ebfc],eax;"
        f"\n pop edx;"
        f"pop eax;"
        f"popfd;"
        f"lea esp,[esp+8];"
        f"ret;"
        f"\n original:jmp {SCENERY_GATHER};"
    )
    b = asm(RANGE_CODE, s)
    assert len(b) < RANGE_END - RANGE_CODE
    return [(RANGE_CODE, b), (RANGE_SITE, asm(RANGE_SITE, f'jmp {RANGE_CODE}'))]


# Match repeated-scenery clip records to the full 16-bit instance IDs.
CLIP_SIZE = 65536 * 4
CLIP_SITE = 0x2a0f1d
CLIP_SITES = {
    CLIP_SITE: asm(CLIP_SITE, 'mov eax,0x1000;'),
    0x2a0f22: asm(0x2a0f22, 'call 0x2c4f40;'),
    0x2a0f57: asm(0x2a0f57, 'call 0x2c4fe4;')
}


def scenery_clip_bodies():
    return [
        (CLIP_SITE, asm(CLIP_SITE, f'mov eax,{CLIP_SIZE};')),
        (0x2a0f22, asm(0x2a0f22, f'call {HEAP_ALLOC};')),
        (0x2a0f57, asm(0x2a0f57, f'call {HEAP_FREE};'))
    ]


def foundation_pieces():
    detail = detail_body()
    original = asm(
        DETAIL_SITE, ("push ebx;"
                      "push ecx;"
                      "push esi;"
                      "push edi;"
                      "push ebp;"
                      "jmp 0x29edb9")
    )
    pieces = [(LIGHT_ENTRY, lighting_body())] + [
        (a, asm(a, f'call {LIGHT_ENTRY}') + b'\x90' * 5) for a in LIGHT_SITES
    ]
    pieces += [
        (DETAIL_ENTRY, detail),
        (DETAIL_SITE, asm(DETAIL_SITE, f'jmp {DETAIL_ENTRY}').ljust(len(original), b'\x90'))
    ]
    providers = {a: asm(a, 'call 0x2b3fd0;call 0x2b46d0') for a in LIGHT_SITES}
    providers[DETAIL_SITE] = original
    return pieces, providers


def install_foundation(write, read):
    from features.input_views import _install
    pieces, providers = foundation_pieces()
    return _install(pieces, providers, write, read)


def storage_pieces():
    """Emit the final preset hook once, retaining snapshot-compatible helpers."""
    pieces = [(a, b) for a, b in mesh_bodies() if a != MESH_SITE]
    pieces += heap_bodies() + preset_bodies() + [(MESH_CONFIG, struct.pack('<I', 3))]
    return pieces


def storage_providers():
    out = {
        MESH_SITE: asm(MESH_SITE, f'jmp {ENTRY}'),
        MESH_ACTOR_SITE: asm(MESH_ACTOR_SITE, f'jmp {OBJECT}')
    }
    out.update({a: struct.pack('<I', old) for a, old, new in MESH_ALLOCATIONS})
    out.update({a: asm(a, 'call 0x2c4f40') for a in HEAP_ALLOC_SITES})
    out.update({a: asm(a, 'call 0x2c4fe4') for a in HEAP_FREE_SITES})
    return out


def install_storage(write, read):
    from features.input_views import _install
    # Complete view-distance provider verification precedes any allocation or
    # hook write. The helper's accepted initial preference enables both bits.
    verify(read)
    return _install(storage_pieces(), storage_providers(), write, read)


def profile_pieces():
    """Final mesh, quality, landscape handoff and unzoomed scenery installation.

    Retained helper bodies keep accepted image/snapshot identities. Only final
    world/ray/gather hooks are emitted; no intermediate hook is installed.
    """
    pieces = [(a, b) for a, b in zoom_bodies() if a not in (ZOOM_SITE, ZOOM_RAY_SITE)]
    pieces += [(a, b) for a, b in quality_bodies() if a != QUALITY_SITE]
    pieces += handoff_bodies() + scenery_range_bodies()
    pieces += [(ZOOM_SITE, asm(ZOOM_SITE, f'jmp {ZOOM_CODE}'))]
    return pieces


def profile_providers():
    return {
        ZOOM_SITE: asm(ZOOM_SITE, f'jmp {PRESET_ENTRY}'),
        ZOOM_RAY_SITE: asm(ZOOM_RAY_SITE, f'call {RAYS}'),
        RANGE_SITE: asm(RANGE_SITE, f'jmp {SCENERY_GATHER}')
    }


def install_profiles(write, read):
    from features.input_views import _install, _verify
    # The mesh and scenery providers were installed in their owning groups;
    # validate their real helper bodies and hooks without a predecessor image.
    _verify(preset_bodies() + scenery_bodies() + heap_bodies(), read)
    return _install(
        profile_pieces(),
        profile_providers(),
        write,
        read,
        cold_state=(
            (ZOOM_CODE, ZOOM_END - ZOOM_CODE), (HANDOFF_CODE, HANDOFF_END - HANDOFF_CODE),
            (RANGE_CODE, RANGE_END - RANGE_CODE)
        )
    )


def install_scenery_clipping(write, read):
    from features.input_views import _install, _verify
    _verify(heap_bodies(), read)
    return _install(scenery_clip_bodies(), CLIP_SITES, write, read)


def verify_scenery_clipping(read):
    from features.input_views import _verify
    return _verify(scenery_clip_bodies() + heap_bodies(), read)


# Bound renderer lists independently of visibility distances.
LIST_CODE = 0x1fc1000
LIST_CAPACITY = 4096
LIST_ORIGINAL = {
    0x2a0f2c: asm(0x2a0f2c, 'mov eax,0x12c0'),
    0x2a0f33: asm(0x2a0f33, 'call 0x2c4f40'),
    0x2a0f4d: asm(0x2a0f4d, 'call 0x2c4fe4'),
    0x2a10e8: bytes.fromhex('535189c389d1'),
    0x2a14ec: bytes.fromhex('66a156014200663d9001720a89c24a66891556014200'),
    0x2a16d5: bytes.fromhex('668b0d560142006681f99001720a89cf4f66893d56014200')
}


def list_room(desc, good, bad):
    return (
        f"cmp word ptr [0x420156],{LIST_CAPACITY};"
        f"jae {bad};"
        f"\n push edx;"
        f"mov edx,[0x427de0];"
        f"sub edx,0x40;"
        f"cmp {desc},edx;"
        f"je special;"
        f"\n add edx,0x20;"
        f"cmp {desc},edx;"
        f"je special;"
        f"pop edx;"
        f"\n cmp byte ptr [{desc}+0x1e],255;"
        f"jae {bad};"
        f"jmp {good};"
        f"\n special:pop edx;"
        f"jmp {good};"
    )


def list_bodies():
    a = asm(
        LIST_CODE,
        list_room('eax', 'ok', 'full') +
        ("ok:push ebx;"
         "push ecx;"
         "mov ebx,eax;"
         "mov ecx,edx;"
         "jmp 0x2a10ee;"
         "full:ret;")
    )
    # Only original-object callers use this first preflight; the central guard
    # also covers distant objects appended by the ray terrain pass.
    b = asm(
        LIST_CODE + 0x100,
        list_room('ebp', 'ok', 'full') + '''ok:mov ax,[0x420156];jmp 0x2a1502;full:jmp 0x2a15b0;'''
    )
    d = asm(
        LIST_CODE + 0x200,
        list_room('ebp', 'ok', 'full') + '''ok:mov cx,[0x420156];jmp 0x2a16ed;full:jmp 0x2a181c;'''
    )
    assert max(map(len, (a, b, d))) < 0x100
    return [
        (LIST_CODE, a), (LIST_CODE + 0x100, b), (LIST_CODE + 0x200, d),
        (0x2a0f2c, asm(0x2a0f2c, f'mov eax,{LIST_CAPACITY*12}')),
        (0x2a0f33, asm(0x2a0f33, f'call {HEAP_ALLOC}')),
        (0x2a0f4d, asm(0x2a0f4d, f'call {HEAP_FREE}'))
    ] + [
        (site, asm(site, f'jmp {target}') + b'\x90' * (len(LIST_ORIGINAL[site]) - 5))
        for site, target in
        ((0x2a10e8, LIST_CODE), (0x2a14ec, LIST_CODE + 0x100), (0x2a16d5, LIST_CODE + 0x200))
    ]


def list_install(write, read):
    from features.input_views import _install, _verify
    _verify(heap_bodies(), read)
    return _install(list_bodies(), LIST_ORIGINAL, write, read)


def list_verify(read):
    from features.input_views import _verify
    return _verify(list_bodies() + heap_bodies(), read)


def scenery_install(write, read):
    from features.input_views import _install, _verify
    pieces = scenery_bodies()
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    original = dict(bodies())[ENTRY]
    _verify([(ENTRY, original), (MESH_OBJECT, dict(mesh_bodies())[MESH_OBJECT])], read)
    providers = {
        ENTRY: original[:5],
        SCENERY_SITE: asm(SCENERY_SITE, f'jmp {MESH_OBJECT}'),
        SCENERY_SCENERY_SITE: SCENERY_SCENERY_OLD,
    }
    return _install(pieces, providers, write, read)


def scenery_verify(read):
    from features.input_views import _verify
    return _verify(scenery_bodies(), read)


# Widen repeated-static renderer indices and bound their transient tables.
INSTANCE_CODE = 0x1fd0000

INSTANCE_LOOKUP = INSTANCE_CODE

INSTANCE_OBJECT_LOOKUP = INSTANCE_CODE + 0x100

INSTANCE_GUARD = INSTANCE_CODE + 0x200

INSTANCE_FOUND = INSTANCE_CODE + 0x300

INSTANCE_TABLE = 0x1fd4000

INSTANCE_CAPACITY = 16416

INSTANCE_TABLE_SIZE = (INSTANCE_CAPACITY + 1) * 8

INSTANCE_BITS = 0x1ff5000

INSTANCE_BITS_SIZE = 8192

INSTANCE_RELOCS = {
    0x298ccc: 0x3cb8ec,
    0x298cee: 0x3c9e1c,
    0x29902d: 0x3cb8f2,
    0x299105: 0x3cb8ec,
    0x29910c: 0x3cb8f0,
    0x299130: 0x3cb8f0,
    0x299138: 0x3cb8f0,
    0x29913f: 0x3cb8f0,
    0x299149: 0x3cb8ec,
    0x299167: 0x3cb8f2,
    0x299170: 0x3cb8fa,
    0x2991e4: 0x3cb8ec,
    0x2991f4: 0x3cb8f0,
    0x29924d: 0x3cb8ec,
    0x299264: 0x3cb8f2,
    0x29927a: 0x3cb8f0,
    0x29f63b: 0x3cb8ea,
    0x29f669: 0x3cb8ec,
    0x2a0efe: 0x3c9e1c,
    0x2a169b: 0x3cb8f2,
    0x2a16b8: 0x3c9e1c,
    0x2a1811: 0x3c9e1c,
    0x2a1869: 0x3cb8ea,
    0x2a187c: 0x3cb8ec,
    0x2a26d5: 0x3cb8ea,
    0x2a26e8: 0x3cb8ec,
    0x2a289b: 0x3cb8ec
}

INSTANCE_ORIGINAL = {
    0x2991b4: bytes.fromhex('53515688c3'),
    0x299200: bytes.fromhex('5351565789c6'),
    0x299128: bytes.fromhex('31d26689fa'),
    0x2a1685: bytes.fromhex('89c289c631c0'),
    0x298cd1: struct.pack('<I', 0x1000),
    0x298cf3: struct.pack('<I', 0x80),
    0x2a0f03: struct.pack('<I', 0x80)
}

INSTANCE_ORIGINAL.update({a: struct.pack('<I', b) for a, b in INSTANCE_RELOCS.items()})


def instance_bodies():
    a = asm(
        INSTANCE_LOOKUP, (
            f"push ebx;"
            f"push ecx;"
            f"push esi;"
            f"movzx ebx,al;"
            f"\n mov eax,ebx;"
            f"mov ecx,ebx;"
            f"shr eax,3;"
            f"and ecx,7;"
            f"movzx esi,byte ptr [eax+0x3cc8ec];"
            f"\n mov eax,1;"
            f"shl eax,cl;"
            f"test esi,eax;"
            f"jz miss;"
            f"mov ecx,{INSTANCE_CAPACITY};"
            f"\n loop:test ebx,ebx;"
            f"jz miss;"
            f"cmp ebx,{INSTANCE_CAPACITY};"
            f"jae miss;"
            f"\n cmp edx,[ebx*8+{INSTANCE_TABLE}];"
            f"je hit;"
            f"movzx ebx,word ptr [ebx*8+{INSTANCE_TABLE+4}];"
            f"dec ecx;"
            f"jnz loop;"
            f"\n miss:xor eax,eax;"
            f"jmp done;"
            f"hit:mov eax,ebx;"
            f"done:pop esi;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    b = asm(
        INSTANCE_OBJECT_LOOKUP, (
            f"push ebx;"
            f"push ecx;"
            f"push esi;"
            f"push edi;"
            f"movzx esi,ax;"
            f"\n imul eax,esi,29;"
            f"movzx edi,byte ptr [eax+0x3cc90f];"
            f"mov ecx,edi;"
            f"mov eax,edi;"
            f"shr eax,3;"
            f"and ecx,7;"
            f"\n movzx ebx,byte ptr [eax+0x3cc8ec];"
            f"mov eax,1;"
            f"shl eax,cl;"
            f"test ebx,eax;"
            f"jz miss;"
            f"mov ecx,{INSTANCE_CAPACITY};"
            f"\n loop:test edi,edi;"
            f"jz miss;"
            f"cmp edi,{INSTANCE_CAPACITY};"
            f"jae miss;"
            f"\n cmp edx,[edi*8+{INSTANCE_TABLE}];"
            f"je hit;"
            f"movzx edi,word ptr [edi*8+{INSTANCE_TABLE+4}];"
            f"dec ecx;"
            f"jnz loop;"
            f"\n miss:xor eax,eax;"
            f"jmp done;"
            f"hit:movzx eax,word ptr [edi*8+{INSTANCE_TABLE+6}];"
            f"imul esi,esi,29;"
            f"\n movsx ebx,byte ptr [esi+0x3cc910];"
            f"add ax,bx;"
            f"\n done:pop edi;"
            f"pop esi;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    guard = asm(
        INSTANCE_GUARD, (
            f"cmp di,{INSTANCE_CAPACITY};"
            f"jae full;"
            f"push eax;"
            f"push ecx;"
            f"\n movzx edx,di;"
            f"movzx eax,word ptr [edx*8+{INSTANCE_TABLE+6}];"
            f"imul ecx,ebx,19;"
            f"\n movsx ecx,byte ptr [ecx+0x3cae9e];"
            f"test ecx,ecx;"
            f"js invalid;"
            f"\n add eax,ecx;"
            f"cmp eax,65535;"
            f"ja invalid;"
            f"pop ecx;"
            f"pop eax;"
            f"jmp 0x29912d;"
            f"\n invalid:pop ecx;"
            f"pop eax;"
            f"full:jmp 0x2991a2;"
        )
    )
    found = asm(
        INSTANCE_FOUND,
        ("test ax,ax;"
         "jz 0x2a1837;"
         "mov edx,eax;"
         "mov esi,eax;"
         "xor eax,eax;"
         "jmp 0x2a168b;")
    )
    assert max(map(len, (a, b, guard, found))) < 0x100
    pieces = [
        (INSTANCE_LOOKUP, a), (INSTANCE_OBJECT_LOOKUP, b), (INSTANCE_GUARD, guard),
        (INSTANCE_FOUND, found)
    ]
    pieces += [
        (x, struct.pack('<I', INSTANCE_TABLE + (y - 0x3cb8ec) if y != 0x3c9e1c else INSTANCE_BITS))
        for x, y in INSTANCE_RELOCS.items()
    ]
    pieces += [
        (0x298cd1, struct.pack('<I', INSTANCE_TABLE_SIZE)),
        (0x298cf3, struct.pack('<I', INSTANCE_BITS_SIZE)),
        (0x2a0f03, struct.pack('<I', INSTANCE_BITS_SIZE))
    ]
    pieces += [
        (x, asm(x, f'jmp {y}') + b'\x90' * (len(INSTANCE_ORIGINAL[x]) - 5)) for x, y in (
            (0x2991b4, INSTANCE_LOOKUP), (0x299200, INSTANCE_OBJECT_LOOKUP),
            (0x299128, INSTANCE_GUARD), (0x2a1685, INSTANCE_FOUND)
        )
    ]
    return pieces


def instance_install(write, read):
    """Widen both renderer tables while preserving their existing entries."""
    from features.input_views import _install
    bodies = instance_bodies()
    if all(bytes(read(a, len(b))) == b for a, b in bodies):
        return dict(already_installed=True, ranges=[])
    tables = [
        (INSTANCE_TABLE, bytes(read(0x3cb8ec, 0x1000)) + bytes(INSTANCE_TABLE_SIZE - 0x1000)),
        (INSTANCE_BITS, bytes(read(0x3c9e1c, 128)) + bytes(INSTANCE_BITS_SIZE - 128)),
    ]
    return _install(
        tables + bodies,
        INSTANCE_ORIGINAL,
        write,
        read,
        cold_state=(
            (INSTANCE_CODE, 0x400), (INSTANCE_TABLE, INSTANCE_TABLE_SIZE),
            (INSTANCE_BITS, INSTANCE_BITS_SIZE)
        )
    )


def instance_verify(read):
    from features.input_views import _verify
    return _verify(instance_bodies(), read)  # Runtime tables change each frame.
