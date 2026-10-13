"""Prevent AI units from firing beyond weapon range or through nearby allies.

The original weapon data, readiness checks, difficulty rules and resource costs
still govern firing. Range and clearance checks add reasons to withhold a shot.
The final preflight check also preserves the original cover and ballistic failures.
"""
from patch_support import asm
import struct

CODE = 0x1e42000
END = CODE + 0x1000
RANGE = CODE
PREFLIGHT = CODE + 0x180
LAUNCH = CODE + 0x300
CLEARANCE = CODE + 0x500
SITES = {
    0x252ccf: bytes.fromhex('807f0d010f857b000000'),
    0x252e42: bytes.fromhex('83c40c5d5f5e'),
    0x28f1ac: bytes.fromhex('8b55b08b5dbc')
}


def bodies():
    # EAX/EDX point pointers, ECX nominal range (six-metre world units).
    # Q8 deltas have <2.4 cm quantization; bound each axis before squaring.
    s = (
        "push ebx;"
        "push esi;"
        "push edi;"
        "push ebp;"
        "mov esi,eax;"
        "mov edi,edx;"
        "shl ecx,8;"
        "mov ebp,ecx;"
        "imul ebp,ebp;"
        "xor ebx,ebx;"
    )
    for k in (0, 4, 8):
        s += (
            f"mov eax,[esi+{k}];"
            f"sub eax,[edi+{k}];"
            f"sar eax,8;"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,ecx;"
            f"ja outside;"
            f"imul eax,eax;"
            f"add ebx,eax;"
            f"cmp ebx,ebp;"
            f"ja outside;"
        )
    s += (
        "xor eax,eax;"
        "jmp done;"
        "outside:mov eax,1;"
        "done:pop ebp;"
        "pop edi;"
        "pop esi;"
        "pop ebx;"
        "ret;"
    )
    out = [(RANGE, asm(RANGE, s))]
    # Replace the PBA-only planar approximation, leaving the original LOS query.
    out.append((0x252ccf, asm(0x252ccf, 'jmp 0x252d54') + b'\x90' * 5))
    pre = preflight_source(preserve_blocked=False)
    out.extend(
        [(PREFLIGHT, asm(PREFLIGHT, pre)), (0x252e42, asm(0x252e42, f'jmp {PREFLIGHT}') + b'\x90')]
    )
    # World-space muzzle and actual target point have now been prepared by stock
    # code. Run only for real AI launches; the player's manual shots are unchanged.
    launch = (
        f"pushfd;"
        f"pushad;"
        f"sub esp,16;"
        f"cmp byte ptr [ebp+40],0;"
        f"je good;"
        f"\n movzx ecx,si;"
        f"cmp cx,word ptr [0x441350];"
        f"je good;"
        f"test ecx,ecx;"
        f"jz good;"
        f"\n cmp ecx,300;"
        f"jae good;"
        f"imul eax,ecx,37;"
        f"movzx edx,byte ptr [eax+0x3c3241];"
        f"\n cmp edx,1;"
        f"jb good;"
        f"cmp edx,4;"
        f"ja good;"
        f"\n movzx ecx,byte ptr [edi];"
        f"test ecx,ecx;"
        f"jz good;"
        f"cmp ecx,32;"
        f"ja good;"
        f"\n imul ecx,ecx,36;"
        f"movzx ecx,word ptr [ecx+0x39511e];"
        f"\n mov eax,[ebp-64];"
        f"mov [esp],eax;"
        f"mov eax,[ebp-68];"
        f"mov [esp+4],eax;"
        f"mov eax,[ebp-72];"
        f"mov [esp+8],eax;"
        f"\n mov eax,esp;"
        f"lea edx,[ebp-84];"
        f"call {RANGE};"
        f"test eax,eax;"
        f"jnz blocked;"
        f"\n movzx ecx,si;"
        f"imul eax,ecx,37;"
        f"cmp byte ptr [eax+0x3c3241],1;"
        f"jne good;"
        f"\n movzx edx,byte ptr [eax+0x3c3261];"
        f"test edx,edx;"
        f"jz good;"
        f"cmp edx,60;"
        f"jae good;"
        f"\n mov eax,esp;"
        f"lea edx,[ebp-84];"
        f"movzx ebx,word ptr [ebp+32];"
        f"call {CLEARANCE};"
        f"test eax,eax;"
        f"jnz blocked;"
        f"\n good:add esp,16;"
        f"popad;"
        f"popfd;"
        f"mov edx,[ebp-80];"
        f"mov ebx,[ebp-68];"
        f"jmp 0x28f1b2;"
        f"\n blocked:add esp,16;"
        f"popad;"
        f"popfd;"
        f"xor eax,eax;"
        f"jmp 0x28f7f1;"
    )
    out.extend(
        [(LAUNCH, asm(LAUNCH, launch)), (0x28f1ac, asm(0x28f1ac, f'jmp {LAUNCH}') + b'\x90')]
    )
    # Capsule around the intended firing segment. 1.25 m PBA / 2.5 m vehicle
    # clearance. No RNG calls, persistent state, damage immunity or ally teleport.
    s = ("push ebp;"
         "mov ebp,esp;"
         "push ebx;"
         "push esi;"
         "push edi;"
         "sub esp,176;")
    s += ("mov [esp+128],eax;"
          "mov [esp+132],edx;"
          "mov [esp+136],ecx;"
          "mov [esp+140],ebx;")
    s += ''.join(f'movdqu [esp+{k*16}],xmm{k};' for k in range(8))
    s += (
        "stmxcsr [esp+160];"
        "imul edi,ecx,37;"
        "movzx edi,byte ptr [edi+0x3c3261];"
        "imul edi,edi,334;"
        "movzx edi,byte ptr [edi+0x3832f5];"
    )
    for k in range(3):
        s += f'mov esi,[edx+{k*4}];sub esi,[eax+{k*4}];mov [esp+144+{k*4}],esi;'
    s += (
        "mov dword ptr [esp+156],0;"
        "movdqu xmm0,[esp+144];"
        "cvtdq2ps xmm0,xmm0;"
        "movaps xmm1,xmm0;"
        "mulps xmm1,xmm1;"
        "movaps xmm2,xmm1;"
        "shufps xmm2,xmm2,0x4e;"
        "addps xmm1,xmm2;"
        "movaps xmm2,xmm1;"
        "shufps xmm2,xmm2,0xb1;"
        "addss xmm1,xmm2;"
        "xorps xmm7,xmm7;"
        "comiss xmm1,xmm7;"
        "jbe clear;"
        "mov ecx,1;"
    )
    s += (
        "loop:cmp ecx,[esp+136];"
        "je next;"
        "cmp ecx,[esp+140];"
        "je next;"
        "imul esi,ecx,37;"
        "add esi,0x3c3240;"
        "cmp byte ptr [esi],0;"
        "je next;"
        "movzx ebx,byte ptr [esi+1];"
        "cmp ebx,1;"
        "je actor;"
        "cmp ebx,2;"
        "jne next;"
        "actor:movzx edx,byte ptr [esi+33];"
        "test edx,edx;"
        "jz next;"
        "cmp edx,60;"
        "jae next;"
        "imul edx,edx,334;"
        "mov al,[edx+0x3832f0];"
        "or al,[edx+0x3832fa];"
        "jz next;"
        "movzx edx,byte ptr [edx+0x3832f5];"
        "cmp edx,edi;"
        "jne next;"
        "mov eax,[esp+128];"
    )
    for k in range(3):
        s += f'mov edx,[esi+15+{k*4}];sub edx,[eax+{k*4}];mov [esp+144+{k*4}],edx;'
    s += (
        "movdqu xmm3,[esp+144];"
        "cvtdq2ps xmm3,xmm3;"
        "movaps xmm4,xmm3;"
        "mulps xmm4,xmm0;"
        "movaps xmm5,xmm4;"
        "shufps xmm5,xmm5,0x4e;"
        "addps xmm4,xmm5;"
        "movaps xmm5,xmm4;"
        "shufps xmm5,xmm5,0xb1;"
        "addss xmm4,xmm5;"
        "comiss xmm4,xmm7;"
        "jbe next;"
        "comiss xmm4,xmm1;"
        "jae next;"
        "divss xmm4,xmm1;"
        "shufps xmm4,xmm4,0;"
        "mulps xmm4,xmm0;"
        "subps xmm3,xmm4;"
        "mulps xmm3,xmm3;"
        "movaps xmm4,xmm3;"
        "shufps xmm4,xmm4,0x4e;"
        "addps xmm3,xmm4;"
        "movaps xmm4,xmm3;"
        "shufps xmm4,xmm4,0xb1;"
        "addss xmm3,xmm4;"
    )
    s += (
        f"cmp ebx,1;"
        f"jne vehicle;"
        f"comiss xmm3,[{CODE+0xf00}];"
        f"jb blocked;"
        f"jmp next;"
        f"vehicle:comiss xmm3,[{CODE+0xf04}];"
        f"jb blocked;"
        f"next:inc ecx;"
        f"cmp ecx,300;"
        f"jb loop;"
        f"clear:xor eax,eax;"
        f"jmp finish;"
        f"blocked:mov eax,1;"
        f"finish:ldmxcsr [esp+160];"
    )
    s += ''.join(f'movdqu xmm{k},[esp+{k*16}];' for k in range(8))
    s += ("add esp,176;"
          "pop edi;"
          "pop esi;"
          "pop ebx;"
          "pop ebp;"
          "ret;")
    out.extend(
        [
            (CLEARANCE, asm(CLEARANCE, s)),
            (CODE + 0xf00, struct.pack('<2f', (1.25 / 6 * 65536)**2, (2.5 / 6 * 65536)**2))
        ]
    )
    for (a, b), limit in zip(out[:1], [PREFLIGHT]):
        assert a + len(b) <= limit
    assert len(dict(out)[PREFLIGHT]
               ) < 0x180 and len(dict(out)[LAUNCH]) < 0x200 and len(dict(out)[CLEARANCE]) < 0xa00
    return out


RESOLVE = 0x1dc8800
OBJECT_LIMIT = 1024


def selected_weapon_source():
    return (
        f"\n push ecx;"
        f" push esi;"
        f" push edi;"
        f"\n xor eax,eax;"
        f" test edx,edx;"
        f" jle done;"
        f" cmp edx,{OBJECT_LIMIT};"
        f" jae done;"
        f"\n imul esi,edx,37;"
        f" movzx ecx,word ptr [esi+0x3c3243];"
        f"\n movzx edi,byte ptr [esi+0x3c3241];"
        f"\n cmp edi,1;"
        f" je suit;"
        f" cmp edi,2;"
        f" je vehicle;"
        f" cmp edi,4;"
        f" je turret;"
        f" jmp done;"
        f"\n suit: cmp ecx,60;"
        f" jae done;"
        f" imul esi,ecx,0x582;"
        f" add esi,0x3a5608;"
        f"\n movzx ecx,byte ptr [esi+0xce];"
        f" cmp ecx,4;"
        f" jae done;"
        f"\n lea ebx,[esi+0x86];"
        f" add esi,0x45;"
        f" jmp selected;"
        f"\n vehicle: cmp ecx,52;"
        f" jae done;"
        f" imul esi,ecx,296;"
        f" add esi,0x3a19e8;"
        f"\n movzx ecx,byte ptr [esi+0x36];"
        f" cmp ecx,2;"
        f" jae done;"
        f"\n lea ebx,[esi+0x37];"
        f" add esi,0x17;"
        f" jmp selected;"
        f"\n turret: cmp ecx,64;"
        f" jae done;"
        f" imul esi,ecx,121;"
        f" add esi,0x39c750;"
        f"\n movzx ecx,byte ptr [esi+0x0e];"
        f" cmp ecx,2;"
        f" jae done;"
        f"\n lea ebx,[esi+0x56];"
        f" add esi,0x33;"
        f"\n selected: imul ecx,ecx,15;"
        f" add esi,ecx;"
        f" mov eax,esi;"
        f"\n done: pop edi;"
        f" pop esi;"
        f" pop ecx;"
        f" ret;"
        f"\n "
    )


def selected_weapon_body():
    return asm(RESOLVE, selected_weapon_source())


def preflight_source(*, preserve_blocked=True):
    combine = "or" if preserve_blocked else "mov"
    return (
        f"pushfd;"
        f"pushad;"
        f"movzx edx,word ptr [edi+11];"
        f"cmp edx,300;"
        f"jae done;"
        f"\n call 0x1dc8800;"
        f"test eax,eax;"
        f"jz done;"
        f"movzx ecx,byte ptr [eax];"
        f"test ecx,ecx;"
        f"jz done;"
        f"\n cmp ecx,32;"
        f"ja done;"
        f"imul ecx,ecx,36;"
        f"movzx ecx,word ptr [ecx+0x39511e];"
        f"\n imul eax,edx,37;"
        f"add eax,0x3c324f;"
        f"movzx edx,word ptr [esp+44];"
        f"\n test edx,edx;"
        f"jz done;"
        f"cmp edx,300;"
        f"jae done;"
        f"imul edx,edx,37;"
        f"add edx,0x3c324f;"
        f"\n call {RANGE};"
        f"mov edx,[esp+64];"
        f"{combine} [edx],al;"
        f"\n done:popad;"
        f"popfd;"
        f"add esp,12;"
        f"pop ebp;"
        f"pop edi;"
        f"pop esi;"
        f"jmp 0x252e48;"
    )


CHOICE_CODE = 0x1fc9800
CHOICE_END = 0x1fca000
CHOICE_FAST = CHOICE_CODE
CHOICE_SCAN = CHOICE_CODE + 0x100
CHOICE_CHECK = CHOICE_CODE + 0x200
CHOICE_INIT = CHOICE_CODE + 0x400
CHOICE_FINISH = CHOICE_CODE + 0x500
CHOICE_SITES = {
    0x250e58: bytes.fromhex('535156575583ec30'),
    0x250f15: bytes.fromhex('31d28a138d04d500000000'),
    0x251034: bytes.fromhex('0fb6336bf624'),
    0x250f38: b'\x30',
    0x25128e: bytes.fromhex('8b44241c83c430')
}


def choice_bodies():
    # Both callers carry ECX=AI record and EBX=weapon record. No target, dead
    # target, or absent actor keeps the original noncombat selection behavior.
    check = asm(
        CHOICE_CHECK, (
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"\n mov ebp,ecx;"
            f"mov esi,ebx;"
            f"cmp byte ptr [ebp+0xc3],0;"
            f"je inside;"
            f"\n movzx edi,byte ptr [ebp+0xca];"
            f"test edi,edi;"
            f"jz inside;"
            f"\n imul edi,edi,37;"
            f"add edi,0x3c3240;"
            f"cmp byte ptr [edi],0;"
            f"je inside;"
            f"\n movzx eax,word ptr [ebp+11];"
            f"test eax,eax;"
            f"jz inside;"
            f"cmp eax,300;"
            f"jae inside;"
            f"\n imul eax,eax,37;"
            f"add eax,0x3c3240;"
            f"cmp byte ptr [eax],0;"
            f"je inside;"
            f"\n movzx ecx,byte ptr [esi];"
            f"test ecx,ecx;"
            f"jz inside;"
            f"cmp ecx,32;"
            f"ja inside;"
            f"\n imul ecx,ecx,36;"
            f"movzx ecx,word ptr [ecx+0x39511e];"
            f"\n add eax,15;"
            f"lea edx,[edi+15];"
            f"call {RANGE};"
            f"jmp done;"
            f"\n inside:xor eax,eax;"
            f"done:pop ebp;"
            f"pop edi;"
            f"pop esi;"
            f"pop edx;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    fast = asm(
        CHOICE_FAST, (
            f"cmp byte ptr [esp+0x30],1;"
            f"je accepted;"
            f"\n push eax;"
            f"call {CHOICE_CHECK};"
            f"test eax,eax;"
            f"pop eax;"
            f"jnz reconsider;"
            f"\n accepted:\n xor edx,edx;"
            f"mov dl,[ebx];"
            f"lea eax,[edx*8];"
            f"jmp 0x250f20;"
            f"\n reconsider:mov byte ptr [esp+0x30],2;"
            f"jmp 0x250fed;"
        )
    )
    scan = asm(
        CHOICE_SCAN, (
            f"cmp byte ptr [esp+0x30],1;"
            f"je accepted;"
            f"\n push eax;"
            f"call {CHOICE_CHECK};"
            f"test eax,eax;"
            f"pop eax;"
            f"jnz rejected;"
            f"\n accepted:\n movzx esi,byte ptr [ebx];"
            f"imul esi,esi,36;"
            f"jmp 0x25103a;"
            f"\n rejected:mov byte ptr [esp+0x30],2;"
            f"jmp 0x251279;"
        )
    )
    # A private stack local makes the fallback reentrant. If every usable weapon
    # is too short, run the original scan so its approach-distance result survives.
    # The existing firing preflight still prevents an out-of-range real launch.
    init = asm(
        CHOICE_INIT, (
            "push ebx;"
            "push ecx;"
            "push esi;"
            "push edi;"
            "push ebp;"
            "sub esp,0x34;"
            "mov byte ptr [esp+0x30],0;"
            "mov byte ptr [esp+0x31],dl;"
            "jmp 0x250e60;"
        )
    )
    finish = asm(
        CHOICE_FINISH, (
            "cmp byte ptr [esp+0x30],2;"
            "jne done;"
            "\n cmp dword ptr [esp+0x1c],0;"
            "jne done;"
            "\n mov byte ptr [esp+0x30],1;"
            "mov dword ptr [esp+0x14],0;"
            "\n mov dword ptr [esp+4],0;"
            "mov dword ptr [esp],0;"
            "mov byte ptr [esp+0x24],0;"
            "\n mov bl,[esp+0x31];"
            "jmp 0x250ee8;"
            "\n done:mov eax,[esp+0x1c];"
            "add esp,0x34;"
            "jmp 0x251295;"
        )
    )
    assert len(fast) < 0x100 and len(scan) < 0x100 and len(check) < 0x200 and len(finish) < 0x300
    return [
        (CHOICE_FAST, fast), (CHOICE_SCAN, scan), (CHOICE_CHECK, check), (CHOICE_INIT, init),
        (CHOICE_FINISH, finish), (0x250e58, asm(0x250e58, f'jmp {CHOICE_INIT}') + b'\x90' * 3),
        (0x250f38, b'\x34'), (0x25128e, asm(0x25128e, f'jmp {CHOICE_FINISH}') + b'\x90' * 2),
        (0x250f15, asm(0x250f15, f'jmp {CHOICE_FAST}') + b'\x90' * 6),
        (0x251034, asm(0x251034, f'jmp {CHOICE_SCAN}') + b'\x90')
    ]


def _dependencies(read, *, choice):
    # Selection calls only RANGE. The launch/preflight group also resolves the
    # selected weapon through the shared, maintained object-class resolver.
    expected = ((RANGE,
                 dict(bodies())[RANGE]), ) if choice else ((RESOLVE, selected_weapon_body()), )
    for a, b in expected:
        if bytes(read(a, len(b))) != b:
            raise ValueError('AI firing provider differs at ' + hex(a))


def install(write, read, *, choice=False):
    """Validate all hook preimages and the complete cold reservation first."""
    from features.input_views import _install
    _dependencies(read, choice=choice)
    start, end = (CHOICE_CODE, CHOICE_END) if choice else (CODE, END)
    return _install(
        choice_bodies() if choice else bodies(),
        CHOICE_SITES if choice else SITES,
        write,
        read,
        cold_state=((start, end - start), )
    )


def verify(read, *, choice=False):
    from features.input_views import _verify
    _dependencies(read, choice=choice)
    return _verify(choice_bodies() if choice else bodies(), read)


def predecessor_view(ram, *, choice=False):
    """Private comparison rollback: restore hook preimages and owned code only."""
    verify(lambda a, n: ram[a:a + n], choice=choice)
    out = bytearray(ram)
    sites = CHOICE_SITES if choice else SITES
    for a, b in choice_bodies() if choice else bodies():
        out[a:a + len(b)] = sites.get(a, bytes(len(b)))
    return out


from dataclasses import dataclass


@dataclass(frozen=True)
class AttackPreview:
    """Response-layer preflight and two transient solver-result slots.

    The response owner sets/clears these slots around its shot solver. Scenery
    retry borrows them, restores both, and then delegates the range decision.
    """
    preflight: int = 0x1fc7200
    active: int = 0x1fc7f80
    failed: int = 0x1fc7f84

    def validate(self):
        for a in (self.preflight, self.active, self.failed):
            if not isinstance(a, int) or a % 4 or not 0x11000 <= a <= 0x1fffffc:
                raise ValueError('Invalid attack-preview binding')
        spans = [
            (self.preflight, len(asm(self.preflight, preflight_source()))), (self.active, 4),
            (self.failed, 4)
        ]
        for i, (a, n) in enumerate(spans):
            if not isinstance(a, int) or a % 4 or not 0x11000 <= a < a + n <= 0x2000000:
                raise ValueError('Invalid attack-preview binding')
            if a < SCENERY_END and SCENERY_CODE < a + n:
                raise ValueError('Attack-preview binding overlaps scenery storage')
            if any(a < b + k and b < a + n for b, k in spans[:i]):
                raise ValueError('Attack-preview bindings overlap')


ATTACK_PREVIEW = AttackPreview()

# Preview-only exclusion of foliage. Live projectiles and movement keep their
# original collision queries. The repeat is limited to obstructed straight fire.
SCENERY_CODE = 0x1e38400
SCENERY_END = 0x1e39000
SCENERY_PREFLIGHT = SCENERY_CODE
SCENERY_DYNAMIC = SCENERY_CODE + 0x400
SCENERY_STATIC = SCENERY_CODE + 0x500
SCENERY_ACTIVE = SCENERY_CODE + 0xb00


def scenery_bodies(preview=ATTACK_PREVIEW):
    preview.validate()
    # The enclosing preflight's stack S has target at S+8, blocked/scenery
    # pointers at S+32/+36. 36 bytes saved registers + 64 private bytes.
    s = (
        f"pushfd;"
        f"pushad;"
        f"sub esp,64;"
        f"\n    cmp dword ptr [{SCENERY_ACTIVE}],0;"
        f"jne done;"
        f"\n    cmp byte ptr [edi+13],1;"
        f"jne done;"
        f"\n    mov eax,[esp+132];"
        f"cmp byte ptr [eax],0;"
        f"je done;"
        f"\n    mov eax,[esp+136];"
        f"cmp byte ptr [eax],0;"
        f"je done;"
        f"\n    movzx edx,word ptr [edi+11];"
        f"call 0x1dc8800;"
        f"test eax,eax;"
        f"jz done;"
        f"\n    movzx ecx,byte ptr [eax];"
        f"test ecx,ecx;"
        f"jz done;"
        f"cmp ecx,32;"
        f"ja done;"
        f"\n    imul ecx,ecx,36;"
        f"cmp byte ptr [ecx+0x395113],0;"
        f"je done;"
        f"\n    "
    )
    for k in range(5):
        s += f'mov eax,[{0x44658c+4*k}];mov [esp+{32+4*k}],eax;'
    s += (
        f"mov eax,[{preview.failed}];"
        f"mov [esp+52],eax;"
        f"\n    mov eax,[{preview.active}];"
        f"mov [esp+56],eax;"
        f"\n    mov dword ptr [esp+16],0;"
        f"mov dword ptr [{SCENERY_ACTIVE}],1;"
        f"\n    movzx edx,word ptr [esp+108];"
        f"mov ebx,esp;"
        f"lea ecx,[esp+12];"
        f"\n    lea eax,[esp+18];"
        f"push eax;"
        f"lea eax,[esp+21];"
        f"push eax;"
        f"\n    lea eax,[esp+24];"
        f"push eax;"
        f"mov eax,edi;"
        f"call 0x252c5c;"
        f"\n    mov dword ptr [{SCENERY_ACTIVE}],0;"
        f"\n    cmp byte ptr [esp+17],0;"
        f"jne deny;"
        f"\n    cmp byte ptr [esp+16],0;"
        f"je restore;"
        f"\n    deny:mov eax,[esp+136];"
        f"mov byte ptr [eax],0;"
        f"\n    restore:mov eax,[esp+52];"
        f"mov [{preview.failed}],eax;"
        f"\n    mov eax,[esp+56];"
        f"mov [{preview.active}],eax;"
        f"\n    "
    )
    for k in range(5):
        s += f'mov eax,[esp+{32+4*k}];mov [{0x44658c+4*k}],eax;'
    s += (f"done:add esp,64;"
          f"popad;"
          f"popfd;"
          f"jmp {preview.preflight};")
    out = [
        (SCENERY_PREFLIGHT, asm(SCENERY_PREFLIGHT, s)),
        (0x252e42, asm(0x252e42, f'jmp {SCENERY_PREFLIGHT}') + b'\x90')
    ]
    for code, site, stride, table, popbytes in (
        (SCENERY_DYNAMIC, 0x2db1a4, 37, 0x3c3241, 20), (SCENERY_STATIC, 0x2db20c, 29, 0x3cc8f4, 24)
    ):
        s = (
            f"pushfd;"
            f"cmp dword ptr [{SCENERY_ACTIVE}],0;"
            f"je original;"
            f"\n        push ecx;"
            f"movzx ecx,ax;"
            f"imul ecx,ecx,{stride};"
            f"\n        cmp byte ptr [ecx+{table}],0;"
            f"pop ecx;"
            f"jne original;"
            f"\n        popfd;"
            f"xor eax,eax;"
            f"ret {popbytes};"
            f"\n        original:popfd;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"mov esi,edx;"
            f"jmp {site+5};"
        )
        b = asm(code, s)
        assert len(b) < 0x100
        out.extend(((code, b), (site, asm(site, f'jmp {code}'))))
    assert len(out[0][1]) < 0x400
    return out


def scenery_sites(preview=ATTACK_PREVIEW):
    preview.validate()
    return {
        0x252e42: asm(0x252e42, f'jmp {preview.preflight}') + b'\x90',
        0x2db1a4: bytes.fromhex('56575589d6'),
        0x2db20c: bytes.fromhex('56575589d6')
    }


def scenery_providers(preview=ATTACK_PREVIEW):
    preview.validate()
    return [
        (RESOLVE, selected_weapon_body()), (RANGE, dict(bodies())[RANGE]),
        (preview.preflight, asm(preview.preflight, preflight_source()))
    ]


def _scenery_dependencies(read, preview):
    for a, b in scenery_providers(preview):
        if bytes(read(a, len(b))) != b:
            raise ValueError('Scenery-preview provider differs at ' + hex(a))
    if bytes(read(SCENERY_ACTIVE, 4)) != bytes(4):
        raise ValueError('Scenery preview must be inactive at installation/checkpoint')


def scenery_install(write, read, preview=ATTACK_PREVIEW):
    from features.input_views import _install
    _scenery_dependencies(read, preview)
    return _install(
        scenery_bodies(preview),
        scenery_sites(preview),
        write,
        read,
        cold_state=((SCENERY_CODE, SCENERY_END - SCENERY_CODE), )
    )


def scenery_verify(read, preview=ATTACK_PREVIEW):
    from features.input_views import _verify
    _scenery_dependencies(read, preview)
    return _verify(scenery_bodies(preview), read)


def scenery_predecessor_view(ram, preview=ATTACK_PREVIEW):
    """Private snapshot rollback; an active preview is never a safe checkpoint."""
    scenery_verify(lambda a, n: ram[a:a + n], preview)
    out = bytearray(ram)
    sites = scenery_sites(preview)
    for a, b in scenery_bodies(preview):
        out[a:a + len(b)] = sites.get(a, bytes(len(b)))
    out[SCENERY_ACTIVE:SCENERY_ACTIVE + 4] = bytes(4)
    return out
