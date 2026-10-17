"""Particle integration and sweep clocks; original emission/expiry stay intact.

Particles use 16-ms integration with signed drift remainders. The drift and
sweep preserve the existing 50-ms visual reference without throttling render.
"""
import struct
from patch_support import asm


def rain_install(write, read):
    from features.input_views import _install
    return _install(rain_bodies(), {RAIN_SITE: RAIN_PREFIX}, write, read)


def rain_verify(read):
    from features.input_views import _verify
    return _verify(rain_bodies(), read)


def pool_verify(read, original):

    def reject(a, b):
        raise ValueError('Effect pool installation incomplete')

    if not pool_install(reject, read, original)['already_expanded']:
        raise ValueError('Effect pool installation incomplete')
    return True


CODE = 0x1e4b000
STATE = 0x1e4d000
TABLE = 0x1e4d100
ROWS = 256
LIMIT = TABLE + ROWS * 16
SITES = {
    0x2a4978: bytes.fromhex('5351525657'),
    0x2a49a6: bytes.fromhex('8b141f8b0101c289141f8b410401441f048b410801441f08'),
    0x2a403c: bytes.fromhex('5351525657'),
    0x2a438a: bytes.fromhex('c7400800000000'),
    0x2a3c70: bytes.fromhex('5351525655'),
    0x2882fa: bytes.fromhex('80835c323c0004')
}


def bodies():
    out = []

    def emit(a, s, cap=0x200):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    def hook(a, target):
        out.append((a, asm(a, f'jmp {target}') + b'\x90' * (len(SITES[a]) - 5)))

    # Entry keeps an unsigned <16-ms balance. The clock check only detects a
    # backward discontinuity; a normal 32-bit wrap still has a positive delta.
    emit(
        CODE, (
            f"pushfd;"
            f"pushad;"
            f"test eax,eax;"
            f"jle done;"
            f"\n cmp byte ptr [0x35f3f4],0;"
            f"jne done;"
            f"\n mov edx,[0x446ae8];"
            f"cmp dword ptr [{STATE+8}],0;"
            f"je first;"
            f"\n mov ecx,edx;"
            f"sub ecx,[{STATE+4}];"
            f"js rewind;"
            f"\n first:mov [{STATE+4}],edx;"
            f"mov dword ptr [{STATE+8}],1;"
            f"\n cmp eax,256;"
            f"jbe credit;"
            f"mov eax,256;"
            f"mov dword ptr [{STATE}],0;"
            f"\n credit:add [{STATE}],eax;"
            f"\n again:cmp dword ptr [{STATE}],16;"
            f"jb done;"
            f"sub dword ptr [{STATE}],16;"
            f"\n mov eax,16;"
            f"call {CODE+0x200};"
            f"jmp again;"
            f"\n rewind:mov [{STATE+4}],edx;"
            f"mov dword ptr [{STATE}],0;"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    emit(
        CODE + 0x200, ("push ebx;"
                       "push ecx;"
                       "push edx;"
                       "push esi;"
                       "push edi;"
                       "jmp 0x2a497d;")
    )
    hook(0x2a4978, CODE)
    # EDI is the original group byte offset; ECX its velocity record, EBX
    # the anchor table. Wide signed arithmetic covers both velocity signs.
    move = ("pushfd;"
            "pushad;"
            "lea ebp,[ebx+edi];"
            "mov esi,ecx;")
    move += (f"cmp edi,{ROWS*16};"
             f"jae untracked;"
             f"add edi,{TABLE};"
             f"mov ebx,25;")
    for axis in (0, 4, 8):
        move += (
            f"mov eax,[esi+{axis}];"
            f"mov ecx,8;"
            f"imul ecx;"
            f"\n  mov ecx,[edi+{axis}];"
            f"mov ebx,ecx;"
            f"sar ebx,31;"
            f"add eax,ecx;"
            f"adc edx,ebx;"
            f"\n  mov ebx,25;"
            f"idiv ebx;"
            f"add [ebp+{axis}],eax;"
            f"mov [edi+{axis}],edx;"
        )
    move += 'jmp moved;untracked:'
    for axis in (0, 4, 8):
        move += (
            f"mov eax,[esi+{axis}];"
            f"mov ecx,8;"
            f"imul ecx;"
            f"mov ebx,25;"
            f"idiv ebx;"
            f"add [ebp+{axis}],eax;"
        )
    move += 'moved:popad;popfd;jmp 0x2a49be;'
    emit(CODE + 0x400, move, 0x300)
    hook(0x2a49a6, CODE + 0x400)
    # Original deletion compacts whole groups. Keep the auxiliary rows aligned,
    # including deletion during the library's own update loop.
    emit(
        CODE + 0x800, (
            f"pushfd;"
            f"pushad;"
            f"mov ecx,[0x421a0c];"
            f"cmp ecx,{ROWS};"
            f"ja finish;"
            f"\n test eax,eax;"
            f"js finish;"
            f"cmp eax,ecx;"
            f"jae finish;"
            f"\n sub ecx,eax;"
            f"dec ecx;"
            f"shl ecx,2;"
            f"shl eax,4;"
            f"lea edi,[eax+{TABLE}];"
            f"lea esi,[edi+16];"
            f"cld;"
            f".byte 0xf3,0xa5;"
            f"\n xor eax,eax;"
            f"mov ecx,4;"
            f"rep stosd;"
            f"\n finish:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x2a4041;"
        )
    )
    hook(0x2a403c, CODE + 0x800)
    emit(
        CODE + 0xa00, (
            f"pushfd;"
            f"pushad;"
            f"cmp ebx,{ROWS};"
            f"jae finish;"
            f"\n mov edi,ebx;"
            f"shl edi,4;"
            f"add edi,{TABLE};"
            f"xor eax,eax;"
            f"mov ecx,4;"
            f"cld;"
            f"rep stosd;"
            f"\n finish:popad;"
            f"popfd;"
            f"mov dword ptr [eax+8],0;"
            f"jmp 0x2a4391;"
        )
    )
    hook(0x2a438a, CODE + 0xa00)
    emit(
        CODE + 0xc00, (
            f"pushfd;"
            f"pushad;"
            f"mov edi,{STATE};"
            f"mov ecx,{(LIMIT-STATE)//4};"
            f"xor eax,eax;"
            f"cld;"
            f"rep stosd;"
            f"\n popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push ebp;"
            f"jmp 0x2a3c75;"
        )
    )
    hook(0x2a3c70, CODE + 0xc00)
    # No per-object timer is needed: derive a fractional sweep increment from
    # game time. EDI is the original elapsed-time argument. Change the complete
    # angle word so intermediate frames are smooth, preserving the 50-ms result.
    emit(
        CODE + 0xe00, (
            "pushfd;"
            "pushad;"
            "test edi,edi;"
            "jle done;"
            "\n cmp byte ptr [0x35f3f4],0;"
            "jne done;"
            "\n mov eax,[0x446ae8];"
            "sub eax,edi;"
            "xor edx,edx;"
            "mov ecx,50;"
            "div ecx;"
            "\n mov esi,edx;"
            "imul eax,esi,1024;"
            "xor edx,edx;"
            "div ecx;"
            "mov ebp,eax;"
            "\n mov eax,edi;"
            "add eax,esi;"
            "mov ecx,1024;"
            "mul ecx;"
            "mov ecx,50;"
            "div ecx;"
            "\n sub eax,ebp;"
            "add word ptr [ebx+0x3c325b],ax;"
            "\n done:popad;"
            "popfd;"
            "jmp 0x288301;"
        )
    )
    hook(0x2882fa, CODE + 0xe00)
    return out


def install(write, read):
    from features.input_views import _install
    pieces = bodies()
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    return _install(pieces + [(STATE, bytes(LIMIT - STATE))], SITES, write, read)


def verify(read):
    from features.input_views import _verify
    return _verify(bodies(), read)


# Rain providers for the original logical HUD.
RAIN_SITE = 0x2af53a
RAIN_ENTRY = 0x1e4a600
RAIN_END = 0x2af562
RAIN_RETURN = 0x2af94e
RAIN_PREFIX = bytes.fromhex('89c82b4726')


def rain_bodies():
    body = asm(
        RAIN_ENTRY, (
            f"cmp dword ptr [edi+0x1a],0xffff0000;"
            f"je initial;"
            f"\n mov eax,ecx;"
            f"sub eax,[edi+0x26];"
            f"js rewind;"
            f"\n cmp eax,32;"
            f"jb skip;"
            f"cmp eax,128;"
            f"jae stall;"
            f"\n shr eax,5;"
            f"mov [esp+0x10],eax;"
            f"\n mov eax,ecx;"
            f"sub eax,[edi+0x26];"
            f"and eax,31;"
            f"sub ecx,eax;"
            f"\n jmp {RAIN_END};"
            f"\n initial:mov dword ptr [esp+0x10],1;"
            f"jmp {RAIN_END};"
            f"\n stall:mov dword ptr [esp+0x10],3;"
            f"jmp {RAIN_END};"
            f"\n rewind:mov [edi+0x26],ecx;"
            f"\n skip:jmp {RAIN_RETURN};"
        )
    )
    assert len(body) < 0x200
    return [(RAIN_ENTRY, body), (RAIN_SITE, asm(RAIN_SITE, f'jmp {RAIN_ENTRY}'))]


# Expanded effect records retain the original allocation/lifecycle routines.
POOL_OLD = 0x39a530
POOL_OLD_COUNT = 128
POOL_COUNT = 256
POOL_STRIDE = 44
POOL_NEW = 0x1e20000
POOL_DESCRIPTOR = 0x295350
POOL_START = POOL_NEW - 256
POOL_END = POOL_NEW + POOL_COUNT * POOL_STRIDE + 256


def pool_references(raw):
    from le_image import LE
    import hashlib
    assert hashlib.sha256(raw).hexdigest(
    ) == 'b762c54509f1716282c4d357a72013b8d84ba25f17b0483b733678ff81e63dd1'
    le = LE(raw)
    bases = (0x244000, 0x354000, 0x355000)
    return sorted(
        (bases[o - 1] + off, bases[t - 1] + dest) for o, off, typ, t, dest in le.fixups
        if typ == 7 and POOL_OLD <= bases[t - 1] + dest < POOL_OLD + POOL_OLD_COUNT * POOL_STRIDE
    )


def pool_lists(data, count):
    assert len(data) == count * POOL_STRIDE
    active, free = struct.unpack_from('<2H', data)
    chains = []
    for is_active, at in ((True, active), (False, free)):
        chain = []
        previous = 0
        while at:
            assert 0 < at < count and at not in chain, 'Invalid effect link'
            if is_active:
                assert struct.unpack_from('<H', data, at * POOL_STRIDE +
                                          4)[0] == previous, 'Invalid previous effect link'
            chain.append(at)
            previous = at
            at = struct.unpack_from('<H', data, at * POOL_STRIDE + 2)[0]
        chains.append(chain)
    assert not set(chains[0]) & set(chains[1])
    assert set(chains[0]) | set(chains[1]) == set(range(1, count)), 'Unaccounted effect record'
    return chains


def pool_validate(read):
    assert read(POOL_START, 256) == read(POOL_END - 256, 256) == b'\xa5' * 256
    a, f = pool_lists(read(POOL_NEW, POOL_COUNT * POOL_STRIDE), POOL_COUNT)
    return dict(active=len(a), free=len(f))


def pool_install(write, read, original, *, cold=False):
    """Preflight every operand/list before writes. Already upgraded saves are no-ops.

 Only a pinned cold executable may have an uninitialized original array.
 Its normal startup/reset routine will initialize the expanded descriptor.
 """
    refs = pool_references(original)
    count, stride, base = struct.unpack('<HHI', read(POOL_DESCRIPTOR, 8))
    assert stride == POOL_STRIDE
    if count == POOL_COUNT:
        assert base == POOL_NEW
        for a, v in refs:
            assert read(a, 4) == struct.pack('<I', POOL_NEW + v - POOL_OLD), hex(a)
        state = pool_validate(read)
        return dict(migrated=False, already_expanded=True, pool=state, ranges=[])
    assert count == POOL_OLD_COUNT and base == POOL_OLD
    assert read(POOL_START, POOL_END -
                POOL_START) == bytes(POOL_END - POOL_START), 'Effect arena already occupied'
    for a, v in refs:
        assert read(a, 4) == struct.pack('<I', v), hex(a)
    old = bytearray(read(POOL_OLD, POOL_OLD_COUNT * POOL_STRIDE))
    if cold:
        assert not any(old), 'Cold build must start with an uninitialized array'
        struct.pack_into('<H', old, 2, 1)
        for i in range(1, POOL_OLD_COUNT):
            struct.pack_into('<H', old, i * POOL_STRIDE + 2, i + 1 if i + 1 < POOL_OLD_COUNT else 0)
    active, free = pool_lists(old, POOL_OLD_COUNT)
    extended = old + bytearray((POOL_COUNT - POOL_OLD_COUNT) * POOL_STRIDE)
    # Preserve every active ID and append capacity after the existing free list.
    struct.pack_into('<H', extended, (free[-1] * POOL_STRIDE + 2) if free else 2, POOL_OLD_COUNT)
    for i in range(POOL_OLD_COUNT, POOL_COUNT):
        struct.pack_into('<H', extended, i * POOL_STRIDE + 2, i + 1 if i + 1 < POOL_COUNT else 0)
    new_active, new_free = pool_lists(extended, POOL_COUNT)
    assert new_active == active and new_free == free + list(range(POOL_OLD_COUNT, POOL_COUNT))
    operations = [(POOL_START, b'\xa5' * 256 + extended + b'\xa5' * 256)]
    operations += [(a, struct.pack('<I', POOL_NEW + v - POOL_OLD)) for a, v in refs]
    operations += [(POOL_DESCRIPTOR, struct.pack('<H', POOL_COUNT))]
    for a, b in operations:
        write(a, bytes(b))
    return dict(
        migrated=True,
        already_expanded=False,
        cold=cold,
        original_usable_slots=127,
        expanded_usable_slots=255,
        extra_record_bytes=5632,
        relocations=len(refs),
        preserved_active_ids=active,
        pool=dict(active=len(new_active), free=len(new_free)),
        ranges=[(a, a + len(b)) for a, b in operations]
    )


# Slightly heavier beam particles and a bounded 33-ms detached trail tail.
BEAM_CODE = 0x1e59800
BEAM_STATE = 0x1e5a800
BEAM_ROWS = 300
BEAM_TABLE = BEAM_STATE + 0x100
BEAM_END = BEAM_TABLE + BEAM_ROWS * 8
BEAM_PRESSURE = BEAM_CODE + 0xe00
BEAM_IMPACT = BEAM_CODE + 0xd00
BEAM_IMPACT_SITE = 0x2d9759
BEAM_SITES = {
    0x2a616c: bytes.fromhex('89c289442414'),
    0x2a6478: bytes.fromhex('5156575583ec0c'),
    0x2a6af8: bytes.fromhex('565789c789d6'),
    0x290b02: asm(0x290b02, 'call 0x295730'),
    0x295730: bytes.fromhex('5351520fbfd8'),
    0x28cc68: bytes.fromhex('5351525657'),
    0x2953f5: bytes.fromhex('83ec04b840323c00')
}


def beam_visual_bodies():
    out = []

    def emit(a, s, cap=0x200):
        b = asm(a, s)
        assert len(b) < cap, (hex(a), len(b))
        out.append((a, b))

    def hook(a, dest, call=False):
        out.append(
            (
                a,
                asm(a,
                    ('call ' if call else 'jmp ') + str(dest)) + b'\x90' * (len(BEAM_SITES[a]) - 5)
            )
        )

    # The fourth dword of each particle-clock row is unused. Its original allocation,
    # compaction and reset operations already maintain the tag's lifetime.
    emit(
        BEAM_CODE, (
            f"pushfd;"
            f"pushad;"
            f"test eax,eax;"
            f"js done;"
            f"cmp eax,256;"
            f"jae done;"
            f"\n shl eax,4;"
            f"xor edx,edx;"
            f"cmp esi,{0x35c390+9*68};"
            f"je beam;"
            f"\n cmp esi,{0x35c390+13*68};"
            f"jne tagged;"
            f"\n beam:mov edx,1;"
            f"tagged:mov [eax+{TABLE+12}],edx;"
            f"\n done:popad;"
            f"popfd;"
            f"mov edx,eax;"
            f"mov [esp+0x14],eax;"
            f"jmp 0x2a6172;"
        )
    )
    hook(0x2a616c, BEAM_CODE)
    # Return carry set only for a tagged group in a square-pixel world canvas.
    emit(
        BEAM_CODE + 0x200, (
            f"push eax;"
            f"push edx;"
            f"mov eax,[0x421a10];"
            f"cmp eax,256;"
            f"jae no;"
            f"\n shl eax,4;"
            f"cmp dword ptr [eax+{TABLE+12}],1;"
            f"jne no;"
            f"\n mov eax,[0x44b1a0];"
            f"movzx edx,word ptr [eax+8];"
            f"cmp edx,200;"
            f"jb no;"
            f"cmp edx,320;"
            f"je no;"
            f"\n cmp word ptr [eax+10],100;"
            f"jb no;"
            f"pop edx;"
            f"pop eax;"
            f"stc;"
            f"ret;"
            f"\n no:pop edx;"
            f"pop eax;"
            f"clc;"
            f"ret;"
        )
    )
    emit(
        BEAM_CODE + 0x280,
        ("push ecx;"
         "push esi;"
         "push edi;"
         "push ebp;"
         "sub esp,12;"
         "jmp 0x2a647f;")
    )
    s = (f"pushfd;"
         f"call {BEAM_CODE+0x200};"
         f"jnc original;"
         f"pushad;")
    for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
        s += (
            f"mov eax,[esp+28];"
            f"mov edx,[esp+20];"
            f"mov ebx,[esp+16];"
            f"add eax,{x};"
            f"add edx,{y};"
            f"call {BEAM_CODE+0x280};"
        )
    s += (f"popad;"
          f"popfd;"
          f"ret;"
          f"original:popfd;"
          f"jmp {BEAM_CODE+0x280};")
    emit(BEAM_CODE + 0x300, s)
    hook(0x2a6478, BEAM_CODE + 0x300)
    emit(
        BEAM_CODE + 0x500, (
            f"pushfd;"
            f"call {BEAM_CODE+0x200};"
            f"jnc original;"
            f"push eax;"
            f"mov eax,ebx;"
            f"sar eax,2;"
            f"add ebx,eax;"
            f"pop eax;"
            f"\n original:popfd;"
            f"push esi;"
            f"push edi;"
            f"mov edi,eax;"
            f"mov esi,edx;"
            f"jmp 0x2a6afe;"
        )
    )
    hook(0x2a6af8, BEAM_CODE + 0x500)
    # Intercept only deletion of linked ray-trail segments. Limit retained tails
    # to 48; pool pressure then takes the original immediate-delete path.
    emit(
        BEAM_CODE + 0x600, (
            f"pushfd;"
            f"pushad;"
            f"movzx edi,ax;"
            f"test edi,edi;"
            f"jz original;"
            f"cmp edi,{BEAM_ROWS};"
            f"jae original;"
            f"\n imul esi,edi,37;"
            f"cmp word ptr [esi+0x3c3241],0x1c06;"
            f"jne original;"
            f"\n cmp dword ptr [{BEAM_STATE}],48;"
            f"jae original;"
            f"\n lea ebp,[edi*8+{BEAM_TABLE}];"
            f"cmp dword ptr [ebp+4],0;"
            f"jne kept;"
            f"\n movzx eax,word ptr [esi+0x3c3243];"
            f"inc eax;"
            f"mov [ebp+4],eax;"
            f"\n mov eax,[0x446ae8];"
            f"add eax,33;"
            f"mov [ebp],eax;"
            f"inc dword ptr [{BEAM_STATE}];"
            f"\n kept:popad;"
            f"popfd;"
            f"mov al,1;"
            f"ret;"
            f"\n original:popad;"
            f"popfd;"
            f"jmp 0x295730;"
        )
    )
    hook(0x290b02, BEAM_CODE + 0x600, True)
    # Every ordinary deletion cancels its queued expiry before freeing an ID.
    emit(
        BEAM_CODE + 0x800, (
            f"pushfd;"
            f"pushad;"
            f"movzx eax,ax;"
            f"cmp eax,{BEAM_ROWS};"
            f"jae done;"
            f"\n lea eax,[eax*8+{BEAM_TABLE}];"
            f"cmp dword ptr [eax+4],0;"
            f"je done;"
            f"\n mov dword ptr [eax+4],0;"
            f"dec dword ptr [{BEAM_STATE}];"
            f"\n done:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"movsx ebx,ax;"
            f"jmp 0x295736;"
        )
    )
    hook(0x295730, BEAM_CODE + 0x800)
    emit(
        BEAM_CODE + 0xa00, (
            f"pushfd;"
            f"pushad;"
            f"cmp byte ptr [0x35f3f4],0;"
            f"jne done;"
            f"\n xor edi,edi;"
            f"mov esi,{BEAM_TABLE};"
            f"\n again:cmp dword ptr [esi+4],0;"
            f"je next;"
            f"mov eax,[0x446ae8];"
            f"sub eax,[esi];"
            f"js next;"
            f"\n imul ebx,edi,37;"
            f"cmp byte ptr [ebx+0x3c3240],0;"
            f"je discard;"
            f"\n cmp word ptr [ebx+0x3c3241],0x1c06;"
            f"jne discard;"
            f"\n movzx eax,word ptr [ebx+0x3c3243];"
            f"inc eax;"
            f"cmp eax,[esi+4];"
            f"jne discard;"
            f"\n mov eax,edi;"
            f"call 0x295730;"
            f"jmp next;"
            f"\n discard:mov dword ptr [esi+4],0;"
            f"dec dword ptr [{BEAM_STATE}];"
            f"\n next:add esi,8;"
            f"inc edi;"
            f"cmp edi,{BEAM_ROWS};"
            f"jb again;"
            f"\n done:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x28cc6d;"
        )
    )
    hook(0x28cc68, BEAM_CODE + 0xa00)
    emit(
        BEAM_CODE + 0xc00, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{BEAM_STATE};"
            f"xor eax,eax;"
            f"mov ecx,{(BEAM_END-BEAM_STATE)//4};"
            f"rep stosd;"
            f"\n popad;"
            f"popfd;"
            f"sub esp,4;"
            f"mov eax,0x3c3240;"
            f"jmp 0x2953fd;"
        )
    )
    hook(0x2953f5, BEAM_CODE + 0xc00)
    # Detached tails only extend the appearance of an already finished segment.
    # When the shared object pool is full, release one matching tail through
    # ordinary deletion so a new unit or projectile can use its slot. Check the
    # effect-record identity as well as the object ID to avoid deleting a reused
    # slot. With no suitable tail, preserve the allocator's normal failure.
    emit(
        BEAM_PRESSURE, f'''
        pushfd;
        cmp word ptr [0x3c3247], 0;
        jne done;
        pushad;
        mov edi, 1;
    scan:
        mov edx, [edi*8+{BEAM_TABLE+4}];
        test edx, edx;
        jz next;
        imul esi, edi, 37;
        cmp byte ptr [esi+0x3c3240], 1;
        jne next;
        cmp word ptr [esi+0x3c3241], 0x1c06;
        jne next;
        movzx eax, word ptr [esi+0x3c3243];
        inc eax;
        cmp eax, edx;
        jne next;
        mov eax, edi;
        call 0x295730;
        jmp restored;
    next:
        inc edi;
        cmp edi, {BEAM_ROWS};
        jb scan;
    restored:
        popad;
    done:
        popfd;
        ret;
    '''
    )
    return out


# Enlarge the faded-pixel path actually used by Laser/Particle Beam presets.
BEAM_PIXEL_CODE = 0x1e5c000
BEAM_PIXEL_SITE = 0x2a5ba4


def beam_pixel_bodies():
    s = (f"pushfd;"
         f"call {BEAM_CODE+0x200};"
         f"jnc original;"
         f"pushad;")
    for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
        # This primitive takes EAX=color, EDX=x, EBX=y (unlike 2a6478).
        s += (
            f"mov eax,[esp+28];"
            f"mov edx,[esp+20];"
            f"mov ebx,[esp+16];"
            f"add edx,{x};"
            f"add ebx,{y};"
            f"call 0x2fad20;"
        )
    s += ("popad;"
          "popfd;"
          "ret;"
          "original:popfd;"
          "jmp 0x2fad20;")
    b = asm(BEAM_PIXEL_CODE, s)
    assert len(b) < 0x200
    return [
        (BEAM_PIXEL_CODE, b), (BEAM_PIXEL_SITE, asm(BEAM_PIXEL_SITE, f'call {BEAM_PIXEL_CODE}'))
    ]


# Fine beam points with deterministic extra 3-D samples near the viewer.
BEAM_DENSITY_CODE = 0x1e5d000
BEAM_DENSITY_CALLS = (0x2a5341, 0x2a5373)


def beam_density_bodies(*, half_spread=False):
    address = BEAM_SPREAD_CODE if half_spread else BEAM_DENSITY_CODE
    spread = "sar word ptr [esp],1;sar word ptr [esp+2],1;" if half_spread else ""
    s = (
        f"pushfd;"
        f"pushad;"
        f"push dword ptr [esp+40];"
        f"call 0x2a59dc;"
        f"\n cmp dword ptr [esp+28],7;"
        f"jne done;"
        f"\n call {BEAM_CODE+0x200};"
        f"jnc done;"
        f"\n cmp dword ptr [esp+40],16384;"
        f"jl done;"
        f"\n sub esp,24;"
        f"mov esi,[esp+44];"
        f"\n mov eax,[esi];"
        f"mov [esp],eax;"
        f"mov eax,[esi+4];"
        f"mov [esp+4],eax;"
        f"\n mov eax,[esi+8];"
        f"mov [esp+8],eax;"
        f"\n {spread}\n movzx edi,word ptr [esi+6];"
        f"imul edi,edi,1103515245;"
        f"shr edi,16;"
        f"\n and edi,16383;"
        f"add edi,16384;"
        f"mov ebp,2;"
        f"\n again:cmp [esp+64],edi;"
        f"jl next;"
        f"\n movsx eax,word ptr [esp];"
        f"movsx edx,word ptr [esp+2];"
        f"\n neg edx;"
        f"mov [esp],dx;"
        f"mov [esp+2],ax;"
        f"\n mov eax,esp;"
        f"lea edx,[esp+12];"
        f"lea ebx,[esp+16];"
        f"lea ecx,[esp+20];"
        f"\n call 0x2a504c;"
        f"test eax,eax;"
        f"jnz next;"
        f"\n mov eax,7;"
        f"mov edx,esp;"
        f"mov ebx,[esp+12];"
        f"mov ecx,[esp+16];"
        f"\n push dword ptr [esp+20];"
        f"call 0x2a59dc;"
        f"\n next:add edi,edi;"
        f"dec ebp;"
        f"jnz again;"
        f"\n add esp,24;"
        f"\n done:popad;"
        f"popfd;"
        f"ret 4;"
    )
    b = asm(address, s)
    assert len(b) < 0x400
    return [(address, b)] + [(a, asm(a, f'call {address}')) for a in BEAM_DENSITY_CALLS] + [
        (BEAM_PIXEL_SITE, asm(BEAM_PIXEL_SITE, 'call 0x2fad20')), (0x2a6478, BEAM_SITES[0x2a6478]),
        (0x2a6af8, BEAM_SITES[0x2a6af8])
    ]


# Fine beam points with deterministic extra 3-D samples near the viewer.
BEAM_SPREAD_CODE = 0x1fc0000
BEAM_SPREAD_CALLS = (0x2a5341, 0x2a5373)


def beam_spread_bodies():
    return beam_density_bodies(half_spread=True)


def beam_impact_bodies():
    """Keep the final visible beam segment aligned with its incoming direction.

    The original mobile-body query returns a point relative to the body's centre.
    That point can lie beside the incoming ray. Project only the trail builder's
    endpoint onto that ray; collision results, damage and impact effects retain
    their original coordinates. Misses and terrain contacts bypass this helper.

    After PUSHFD/PUSHAD, the caller's hit flag/result are at +108/+96. The trail
    arguments are start Z at +40 and end XYZ at +44. EBP still identifies the
    projectile record, whose direction begins at +10. SSE state is preserved.
    """
    save = ';'.join(f'movdqu [esp+{i*16}],xmm{i}' for i in range(4))
    restore = ';'.join(f'movdqu xmm{i},[esp+{i*16}]' for i in range(4))
    body = asm(BEAM_IMPACT, f'''
        pushfd; pushad; mov esi,esp;
        cmp byte ptr [esi+108],0; je done;
        cmp dword ptr [esi+96],0; jle done;
        sub esp,96; {save}; stmxcsr [esp+64];
        mov [esp+80],ebx; mov [esp+84],ecx;
        mov eax,[esi+40]; mov [esp+88],eax;
        xorpd xmm2,xmm2; xorpd xmm3,xmm3; xor edi,edi;
    dot:
        cvtsi2sd xmm0,dword ptr [esi+edi*4+44];
        cvtsi2sd xmm1,dword ptr [esp+edi*4+80]; subsd xmm0,xmm1;
        cvtsi2sd xmm1,dword ptr [ebp+edi*4+10];
        mulsd xmm0,xmm1; addsd xmm2,xmm0;
        mulsd xmm1,xmm1; addsd xmm3,xmm1;
        inc edi; cmp edi,3; jb dot;
        xorpd xmm0,xmm0; ucomisd xmm3,xmm0; jbe restore;
        divsd xmm2,xmm3; maxsd xmm2,xmm0; xor edi,edi;
    endpoint:
        cvtsi2sd xmm0,dword ptr [ebp+edi*4+10]; mulsd xmm0,xmm2;
        cvtsi2sd xmm1,dword ptr [esp+edi*4+80]; addsd xmm0,xmm1;
        cvttsd2si eax,xmm0; mov [esi+edi*4+44],eax;
        inc edi; cmp edi,3; jb endpoint;
    restore:
        ldmxcsr [esp+64]; {restore}; add esp,96;
    done:
        popad; popfd; jmp 0x28d730;
    ''')
    assert len(body) <= BEAM_PRESSURE - BEAM_IMPACT, len(body)
    return [(BEAM_IMPACT, body),
            (BEAM_IMPACT_SITE, asm(BEAM_IMPACT_SITE, f'call {BEAM_IMPACT}'))]


def beam_pieces():
    """Emit final beam hooks once and retain accepted helper/state addresses."""
    parts = (
        beam_visual_bodies() + beam_pixel_bodies() + beam_density_bodies() + beam_spread_bodies()
        + beam_impact_bodies()
    )
    # The sampling and restored raster hooks supersede the temporary heavier
    # pixel treatment. Its helper bytes remain for exact image compatibility.
    return list(dict(parts).items()) + [(BEAM_STATE, bytes(BEAM_END - BEAM_STATE))]


def beam_providers():
    return {
        BEAM_IMPACT_SITE: asm(BEAM_IMPACT_SITE, 'call 0x28d730'),
        **BEAM_SITES,
        BEAM_PIXEL_SITE: asm(BEAM_PIXEL_SITE, 'call 0x2fad20'),
        **{
            site: asm(site, 'call 0x2a59dc')
            for site in BEAM_DENSITY_CALLS
        },
    }


def beam_install(write, read):
    from features.input_views import _install
    return _install(
        beam_pieces(),
        beam_providers(),
        write,
        read,
        cold_state=(
            (BEAM_CODE, BEAM_END - BEAM_CODE), (BEAM_PIXEL_CODE, 0x200), (BEAM_DENSITY_CODE, 0x400),
            (BEAM_SPREAD_CODE, 0x400)
        )
    )


def beam_verify(read):
    from features.input_views import _verify
    return _verify([(a, b) for a, b in beam_pieces() if a != BEAM_STATE], read)


# Run the original storm state machine on a 50-ms visual reference clock.
STORM_CODE = 0x1fce000

STORM_RESET = STORM_CODE + 0x200

STORM_STATE = STORM_CODE + 0x300

STORM_SITE = 0x2b0501

STORM_INIT = 0x244dcb


def storm_bodies():
    b = asm(
        STORM_CODE, (
            f"pushfd;"
            f"pushad;"
            f"mov ebx,[0x446ae8];"
            f"\n cmp dword ptr [{STORM_STATE}],0;"
            f"je first;"
            f"\n mov eax,ebx;"
            f"sub eax,[{STORM_STATE+4}];"
            f"js reset;"
            f"test eax,eax;"
            f"jz done;"
            f"\n cmp eax,250;"
            f"ja reset;"
            f"\n mov [{STORM_STATE+4}],ebx;"
            f"add eax,[{STORM_STATE+8}];"
            f"xor edx,edx;"
            f"mov ecx,50;"
            f"div ecx;"
            f"\n mov [{STORM_STATE+8}],edx;"
            f"mov esi,eax;"
            f"test esi,esi;"
            f"jz done;"
            f"\n loop:call 0x2b0244;"
            f"dec esi;"
            f"jnz loop;"
            f"jmp done;"
            f"\n first:mov dword ptr [{STORM_STATE}],1;"
            f"mov [{STORM_STATE+4}],ebx;"
            f"mov dword ptr [{STORM_STATE+8}],0;"
            f"jmp done;"
            f"\n reset:mov [{STORM_STATE+4}],ebx;"
            f"mov dword ptr [{STORM_STATE+8}],0;"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    reset = asm(
        STORM_RESET, (
            f"pushfd;"
            f"push eax;"
            f"xor eax,eax;"
            f"mov [{STORM_STATE}],eax;"
            f"mov [{STORM_STATE+4}],eax;"
            f"mov [{STORM_STATE+8}],eax;"
            f"pop eax;"
            f"popfd;"
            f"jmp 0x2b0238;"
        )
    )
    assert len(b) < 0x200
    return [
        (STORM_CODE, b), (STORM_RESET, reset), (STORM_SITE, asm(STORM_SITE, f'call {STORM_CODE}')),
        (STORM_INIT, asm(STORM_INIT, f'call {STORM_RESET}'))
    ]


def storm_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        storm_bodies(), {
            STORM_SITE: asm(STORM_SITE, 'call 0x2b0244'),
            STORM_INIT: asm(STORM_INIT, 'call 0x2b0238')
        },
        write,
        read,
        cold_state=((STORM_CODE, 0x30c), )
    )


def storm_verify(read):
    from features.input_views import _verify
    return _verify(storm_bodies(), read)


WATER_NOISE_BEGIN = 0x1d32000

WATER_NOISE_FIRST = 0x1d32100

WATER_NOISE_SECOND = 0x1d32200

WATER_NOISE_STATE = 0x1d33000

WATER_NOISE_PAIRS = 0x1d33400

WATER_NOISE_STAMP = 0x1d33c00

WATER_NOISE_PERIOD_MS = 50


def water_noise_setup(write, asm, r):
    assert r[0x2a84cd:0x2a84d6] == bytes.fromhex('31f631c9bdff7f0000')
    for a in (0x2a84e8, 0x2a8516):
        assert r[a:a + 5] == b'\xe8' + struct.pack('<i', 0x2ddd70 - a - 5)
    # The same game-time bucket is used by the main view and camera views.
    # Cached values are random samples, not byte offsets: the original code
    # recalculates displacement using each view's current framebuffer stride.
    write(
        WATER_NOISE_BEGIN,
        asm(
            WATER_NOISE_BEGIN, (
                f"push eax;"
                f"push ebx;"
                f"push edx;"
                f"\n mov eax,[0x446ae8];"
                f"xor edx,edx;"
                f"mov ebx,{WATER_NOISE_PERIOD_MS};"
                f"div ebx;"
                f"inc eax;"
                f"mov [{WATER_NOISE_STATE}],eax;"
                f"\n inc dword ptr [{WATER_NOISE_STATE+4}];"
                f"pop edx;"
                f"pop ebx;"
                f"pop eax;"
                f"\n xor esi,esi;"
                f"xor ecx,ecx;"
                f"mov ebp,0x7fff;"
                f"jmp 0x2a84d6;"
            )
        )
    )
    for addr, offset, last in [(WATER_NOISE_FIRST, 0, False), (WATER_NOISE_SECOND, 4, True)]:
        stamp = (
            f"push edx;"
            f"mov edx,[{WATER_NOISE_STATE}];"
            f"mov [{WATER_NOISE_STAMP}+ecx],edx;"
            f"pop edx;"
        ) if last else ''
        counter = f'inc dword ptr [{WATER_NOISE_STATE+8}];' if last else ''
        # Preserve the original random routine's flags, including for diagnostics.
        count = f'pushfd;{counter}popfd;' if counter else ''
        write(
            addr,
            asm(
                addr, (
                    f"push eax;"
                    f"mov eax,[{WATER_NOISE_STATE}];"
                    f"cmp [{WATER_NOISE_STAMP}+ecx],eax;"
                    f"pop eax;"
                    f"je cached;"
                    f"\n  call 0x2ddd70;"
                    f"mov [{WATER_NOISE_PAIRS+offset}+ecx*2],eax;"
                    f"{stamp}{count}ret;"
                    f"\n  cached:mov eax,[{WATER_NOISE_PAIRS+offset}+ecx*2];"
                    f"mov edx,eax;"
                    f"add eax,0;"
                    f"ret;"
                )
            )
        )
    write(0x2a84cd, asm(0x2a84cd, f'jmp {WATER_NOISE_BEGIN}'))
    write(0x2a84e8, asm(0x2a84e8, f'call {WATER_NOISE_FIRST}'))
    write(0x2a8516, asm(0x2a8516, f'call {WATER_NOISE_SECOND}'))
