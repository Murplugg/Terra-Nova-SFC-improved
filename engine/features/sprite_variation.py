"""Stable scenery/effect variation, wrist origins and transparent scorch overlays."""
from patch_support import asm
import struct
import hashlib
from features import frame_clock

# Physical player wrist muzzles and stable per-placement scenery mirroring.
SCENERY_CODE = 0x1ff7000

SCENERY_END = 0x1ff8000

SCENERY_WRIST = SCENERY_CODE

SCENERY_CHOOSE = SCENERY_CODE + 0x100

SCENERY_SCALE5 = SCENERY_CODE + 0x400

SCENERY_SCALELIT = SCENERY_CODE + 0x600

SCENERY_SITES = {
    0x28a925: asm(0x28a925, 'call 0x28a6f0'),
    0x29c079: bytes.fromhex('ff96a4020000'),
    0x29c0c0: bytes.fromhex('ff96a4020000'),
    0x29c0f7: bytes.fromhex('ff96dc020000')
}


# Read the original clipping/lighting wrappers locally. The edits reverse U
# coordinates and retain the accepted two-corner mapping and calling convention.
SCALER_RECIPES = {
    True: (0x3288e8, 0x32899c,
        '2aa5846755c6afde1ceb1d91957cd71bf12bbce6f35b42c53c5334bddcc71334',
        {
            0x328916: (0x32891a,
                ''
            ),
            0x328939: (0x32893f,
                'movsx eax,word ptr [esi+8];'
            ),
            0x328946: (0x32894c,
                'mov dword ptr [esp+0x20],0;'
                'movsx eax,word ptr [esi+10];'
            ),
            0x32894f: (0x32894f,
                'mov [esp+12],eax;'
            ),
            0x328951: (0x328955,
                ''
            ),
            0x32895e: (0x32895e,
                'movsx edx,word ptr [esi+8];'
                'shl edx,16;'
                'dec edx;'
                'neg dword ptr [esp+8];'
                'add [esp+8],edx;'
                'neg dword ptr [esp+0x20];'
                'add [esp+0x20],edx;'
            ),
        },
        {0x328995: 'done'},
    ),
    False: (0x32882c, 0x3288e6,
        'af6d11620d30a5b149fd988c19e5271fe97fa805f5de898d302ae2b87a601f1a',
        {
            0x328833: (0x32883c,
                ''
            ),
            0x328846: (0x328849,
                ''
            ),
            0x32884d: (0x32884f,
                'movsx eax,dx;'
            ),
            0x328852: (0x328855,
                ''
            ),
            0x328858: (0x32885a,
                'movsx eax,bx;'
            ),
            0x328861: (0x32886a,
                'movsx eax,dx;'
                'add eax,ecx;'
            ),
            0x328878: (0x328880,
                'add eax,ebx;'
            ),
            0x328883: (0x328887,
                ''
            ),
            0x32888b: (0x328891,
                'movsx eax,word ptr [esi+8];'
            ),
            0x328898: (0x32889e,
                'mov dword ptr [esp+0xc],0;'
                'mov dword ptr [esp+8],0;'
                'movsx eax,word ptr [esi+10];'
            ),
            0x3288a1: (0x3288a5,
                ''
            ),
            0x3288ab: (0x3288ab,
                'lea edx,[esp+0x18];'
            ),
            0x3288b0: (0x3288b0,
                'movsx edx,word ptr [esi+8];'
                'shl edx,16;'
                'dec edx;'
                'neg dword ptr [esp+8];'
                'add [esp+8],edx;'
                'neg dword ptr [esp+0x20];'
                'add [esp+0x20],edx;'
            ),
        },
        {0x3288dc: 'done'},
    ),
}


def scenery_scaler(address, lit):
    from original_inputs import edited_assembly
    b = asm(address, edited_assembly(SCALER_RECIPES[lit]))
    assert len(b) < 0x200
    return b


def scenery_bodies():
    wrist = asm(
        SCENERY_WRIST, (
            "pushfd;"
            "cmp edx,2;"
            "jb fallback;"
            "cmp edx,3;"
            "ja fallback;"
            "\n cmp ax,word ptr [0x441350];"
            "jne fallback;"
            "\n push eax;"
            "push esi;"
            "movzx eax,word ptr [0x441352];"
            "cmp eax,64;"
            "jae bad;"
            "\n imul esi,eax,0x582;"
            "add esi,0x3a5608;"
            "\n movsx esi,word ptr [esi];"
            "and esi,0x7fff;"
            "cmp si,word ptr [0x441350];"
            "jne bad;"
            "\n pop esi;"
            "add esp,4;"
            "popfd;"
            "jmp 0x29b2c0;"
            "\n bad:pop esi;"
            "pop eax;"
            "fallback:popfd;"
            "jmp 0x28a6f0;"
        )
    )
    # Return flip decision in CF, preserve all registers. Only natural class-0
    # sprites. Hash immutable placement X/Y and species; never touch game RNG.
    choose = asm(
        SCENERY_CHOOSE, (
            "pushad;"
            "cmp byte ptr [ebp+1],0;"
            "jne no;"
            "\n movzx eax,byte ptr [ebp+2];"
            "cmp eax,26;"
            "jb natural;"
            "cmp eax,52;"
            "jne no;"
            "\n natural:mov edx,[ebp+15];"
            "imul edx,edx,0x9e3779b1;"
            "\n xor edx,[ebp+19];"
            "imul eax,eax,0x85ebca6b;"
            "xor eax,edx;"
            "\n mov edx,eax;"
            "shr edx,16;"
            "xor eax,edx;"
            "imul eax,eax,0x7feb352d;"
            "\n mov edx,eax;"
            "shr edx,15;"
            "xor eax,edx;"
            "test eax,1;"
            "jz no;"
            "\n popad;"
            "stc;"
            "ret;"
            "no:popad;"
            "clc;"
            "ret;"
        )
    )
    out = [
        (SCENERY_WRIST, wrist), (SCENERY_CHOOSE, choose),
        (SCENERY_SCALE5, scenery_scaler(SCENERY_SCALE5, False)),
        (SCENERY_SCALELIT, scenery_scaler(SCENERY_SCALELIT, True))
    ]
    assert len(wrist) < 0x100 and len(choose) < 0x100
    for i, site in enumerate((0x29c079, 0x29c0c0, 0x29c0f7)):
        entry = SCENERY_CODE + 0x800 + 0x100 * i
        lit = i == 2
        offset = 0x2dc if lit else 0x2a4
        s = (
            f"pushfd;"
            f"call {SCENERY_CHOOSE};"
            f"jnc original;"
            f"\n  cmp word ptr [eax+8],0;"
            f"jle original;"
            f"cmp ecx,0;"
            f"jle original;"
            f"\n  pushad;"
            f"\n  cmp word ptr [eax+16],0;"
            f"jne pivot;"
            f"cmp word ptr [eax+18],0;"
            f"je centered;"
            f"\n  pivot:mov esi,eax;"
            f"mov edi,ecx;"
            f"movsx eax,word ptr [esi+16];"
            f"imul eax,edi;"
            f"cdq;"
            f"\n  movsx ecx,word ptr [esi+8];"
            f"idiv ecx;"
            f"mov ebx,eax;"
            f"\n  movsx eax,word ptr [esi+16];"
            f"neg eax;"
            f"add eax,ecx;"
            f"imul eax,edi;"
            f"cdq;"
            f"idiv ecx;"
            f"\n  sub ebx,eax;"
            f"add [esp+20],ebx;"
            f"\n  centered:popad;"
            f"popfd;"
            f"jmp {SCENERY_SCALELIT if lit else SCENERY_SCALE5};"
            f"\n  original:popfd;"
            f"jmp dword ptr [esi+{offset}];"
        )
        b = asm(entry, s)
        assert len(b) < 0x100
        out.extend([(entry, b), (site, asm(site, f'call {entry}') + b'\x90')])
    out.append((0x28a925, asm(0x28a925, f'call {SCENERY_WRIST}')))
    return out


# Stable horizontal variation for animated effect billboards only.
EFFECT_CODE = 0x1e55000

EFFECT_END = EFFECT_CODE + 0x1000

EFFECT_SITES = (SCENERY_CHOOSE, )


def effect_bodies():
    old = dict(scenery_bodies())[SCENERY_CHOOSE]
    # These are the stock animated effect sprites. Types 28 onward are beams,
    # particle groups and other custom renderers, and deliberately excluded.
    s = (
        f"cmp byte ptr [ebp+1],6;"
        f"je effect;"
        f"jmp {EFFECT_CODE+0x100};"
        f"\n effect:pushad;"
        f"movzx eax,byte ptr [ebp+2];"
        f"cmp eax,28;"
        f"jae no;"
        f"\n movzx edx,word ptr [ebp+3];"
        f"imul edx,edx,0x9e3779b1;"
        f"\n imul eax,eax,0x85ebca6b;"
        f"xor eax,edx;"
        f"mov edx,ebp;"
        f"sub edx,0x3c3240;"
        f"\n xor eax,edx;"
        f"mov edx,eax;"
        f"shr edx,16;"
        f"xor eax,edx;"
        f"\n imul eax,eax,0x7feb352d;"
        f"test eax,1;"
        f"jz no;"
        f"popad;"
        f"stc;"
        f"ret;"
        f"\n no:popad;"
        f"clc;"
        f"ret;"
    )
    b = asm(EFFECT_CODE, s)
    assert len(b) < 0x100
    return [
        (EFFECT_CODE, b), (EFFECT_CODE + 0x100, old),
        (SCENERY_CHOOSE, asm(SCENERY_CHOOSE, f'jmp {EFFECT_CODE}'))
    ]


# Stable dihedral variation of the brown 64x64 scorch overlay only.
SCORCH_CODE = 0x1e03000

SCORCH_END = SCORCH_CODE + 0x5000

SCORCH_SELECT = SCORCH_CODE + 0x200

SCORCH_BLIT = SCORCH_CODE + 0x400

SCORCH_HASH = SCORCH_CODE + 0x800

SCORCH_STATE = SCORCH_CODE + 0xc00

SCORCH_MODE = SCORCH_STATE

SCORCH_KEYS = SCORCH_STATE + 0x40

SCORCH_ZERO = SCORCH_CODE + 0x1000

SCORCH_WHITE = SCORCH_CODE + 0x2000

SCORCH_SITES = {a: asm(a, 'call 0x2ac5bc') for a in (0x2b23b1, 0x2b2482)}

SCORCH_SITES[0x2ac6bd] = asm(0x2ac6bd, 'call 0x2faf1c')


def scorch_bodies():
    out = []
    # First caller retains the row pointer in EBX and tile X on its stack.
    out.append(
        (
            SCORCH_CODE,
            asm(
                SCORCH_CODE, (
                    f"push ebx;"
                    f"push ecx;"
                    f"push edx;"
                    f"\n      mov ecx,[esp+16];"
                    f"lea ecx,[ecx+ecx*2];"
                    f"add ebx,ecx;"
                    f"\n      call {SCORCH_SELECT};"
                    f"pop edx;"
                    f"pop ecx;"
                    f"pop ebx;"
                    f"ret;"
                )
            )
        )
    )
    # Second caller retains the row pointer in EDX and tile X in EBP.
    out.append(
        (
            SCORCH_CODE + 0x80,
            asm(
                SCORCH_CODE + 0x80, (
                    f"push ebx;"
                    f"push ecx;"
                    f"push edx;"
                    f"\n      lea ebx,[ebp+ebp*2];"
                    f"add ebx,edx;"
                    f"\n      call {SCORCH_SELECT};"
                    f"pop edx;"
                    f"pop ecx;"
                    f"pop ebx;"
                    f"ret;"
                )
            )
        )
    )
    out.append(
        (
            SCORCH_HASH,
            asm(
                SCORCH_HASH, (
                    "push edx;"
                    "mov edx,[0x35bfb4];"
                    "\n      sub ebx,[edx+0x84e];"
                    "imul ebx,ebx,0x9e3779b1;"
                    "\n      mov edx,ebx;"
                    "shr edx,16;"
                    "xor ebx,edx;"
                    "imul ebx,ebx,0x7feb352d;"
                    "\n      mov edx,ebx;"
                    "shr edx,15;"
                    "xor ebx,edx;"
                    "and ebx,7;"
                    "pop edx;"
                    "ret;"
                )
            )
        )
    )
    out.append(
        (
            SCORCH_SELECT,
            asm(
                SCORCH_SELECT, (
                    f"push ecx;"
                    f"push edx;"
                    f"push ebx;"
                    f"\n      call {SCORCH_HASH};"
                    f"mov [{SCORCH_MODE}],ebx;"
                    f"\n      movzx edx,byte ptr [eax+0x428810];"
                    f"test edx,edx;"
                    f"jz remember;"
                    f"\n      cmp bl,byte ptr [eax+{SCORCH_KEYS}];"
                    f"je remember;"
                    f"\n      shl edx,4;"
                    f"mov byte ptr [edx+0x428858],255;"
                    f"\n      mov dword ptr [edx+0x428854],0;"
                    f"mov byte ptr [eax+0x428810],0;"
                    f"\n      remember:mov byte ptr [eax+{SCORCH_KEYS}],bl;"
                    f"\n      call 0x2ac5bc;"
                    f"pop ebx;"
                    f"pop edx;"
                    f"pop ecx;"
                    f"ret;"
                )
            )
        )
    )
    # Decode twice to distinguish explicit palette-zero pixels from skipped
    # pixels. This preserves the original transparency exactly, including black.
    s = (
        f"cmp dword ptr [{SCORCH_MODE}],0;"
        f"je original;"
        f"pushad;"
        f"\n      mov edi,{SCORCH_ZERO};"
        f"xor eax,eax;"
        f"mov ecx,1024;"
        f"rep stosd;"
        f"\n      mov edi,{SCORCH_WHITE};"
        f"mov eax,0xffffffff;"
        f"mov ecx,1024;"
        f"rep stosd;"
        f"\n      mov edx,[esp+20];"
        f"mov eax,{SCORCH_ZERO};"
        f"call 0x2faf1c;"
        f"\n      mov edx,[esp+20];"
        f"mov eax,{SCORCH_WHITE};"
        f"call 0x2faf1c;"
        f"\n      mov edi,[esp+28];"
        f"mov ebp,[{SCORCH_MODE}];"
        f"xor esi,esi;"
        f"\n      pixel:mov eax,esi;"
        f"and eax,63;"
        f"mov edx,esi;"
        f"shr edx,6;"
        f"\n      test ebp,4;"
        f"jz noswap;"
        f"xchg eax,edx;"
        f"\n      noswap:test ebp,1;"
        f"jz nox;"
        f"xor eax,63;"
        f"\n      nox:test ebp,2;"
        f"jz noy;"
        f"xor edx,63;"
        f"\n      noy:shl edx,6;"
        f"add edx,eax;"
        f"\n      mov al,[edx+{SCORCH_ZERO}];"
        f"test al,al;"
        f"jnz draw_pixel;"
        f"\n      cmp byte ptr [edx+{SCORCH_WHITE}],255;"
        f"je next;"
        f"\n      draw_pixel:mov [edi+esi],al;"
        f"\n      next:inc esi;"
        f"cmp esi,4096;"
        f"jb pixel;"
        f"popad;"
        f"ret;"
        f"\n      original:jmp 0x2faf1c;"
    )
    b = asm(SCORCH_BLIT, s)
    assert len(b) < 0x400
    out.append((SCORCH_BLIT, b))
    out.extend(
        [
            (0x2b23b1, asm(0x2b23b1, f'call {SCORCH_CODE}')),
            (0x2b2482, asm(0x2b2482, f'call {SCORCH_CODE+0x80}')),
            (0x2ac6bd, asm(0x2ac6bd, f'call {SCORCH_BLIT}'))
        ]
    )
    return out


def sprite_bodies():
    """Compose scenery and effect selection with one final selection hook."""
    spans = dict(scenery_bodies())
    for address, data in effect_bodies():
        # The five-byte jump replaces only the start of the old selector.
        # Its tail remains part of the saved image and must be retained.
        previous = spans.get(address, b'')
        spans[address] = data + previous[len(data):]
    return list(spans.items())


def sprite_install(write, read):
    from features.input_views import _install
    return _install(
        sprite_bodies(),
        SCENERY_SITES,
        write,
        read,
        cold_state=(
            (SCENERY_CODE, SCENERY_END - SCENERY_CODE), (EFFECT_CODE, EFFECT_END - EFFECT_CODE)
        )
    )


def sprite_verify(read):
    from features.input_views import _verify
    return _verify(sprite_bodies(), read)


def scorch_install(write, read):
    from features.input_views import _install
    pieces = scorch_bodies()
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    # The old cache may contain overlays. Invalidate it after admission so
    # original decoding lazily regenerates transformed tiles on next use.
    cache = 0x428810
    return _install(
        pieces + [(cache, bytes(64))], {
            **SCORCH_SITES, cache: bytes(read(cache, 64))
        },
        write,
        read,
        cold_state=((SCORCH_CODE, SCORCH_END - SCORCH_CODE), )
    )


def scorch_verify(read):
    from features.input_views import _verify
    return _verify(scorch_bodies(), read)
