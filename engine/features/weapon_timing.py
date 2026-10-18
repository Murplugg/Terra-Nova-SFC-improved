"""Carry bounded polling lateness only through verified firing eligibility.

One private row per original object. Never synthesize shots or edit damage.
Readiness/status queries do not arm rows. A successful original creation is the
only source of a carried deadline; all resource and burst accounting stays in
the original function. A stall may discard phase, never emit a backlog.
"""
from features.ai_firing import selected_weapon_source

# Drone damage queries receive no power-plant record from the
# generic actor lookup. Readiness previously dereferenced that null pointer
# when checking another energy weapon. Report insufficient charge instead;
# the damage caller counts that as an intact weapon, preserving its existing
# protection for the last functioning weapon. Normal firing supplies a real
# energy record and keeps its original charge and cooldown checks.
READINESS_SITE = 0x28f05f
READINESS_BEFORE = bytes.fromhex('31ffbb01000000668bb818513900')


def readiness_body():
    from patch_support import asm
    body = asm(READINESS_SITE, '''
        test edx, edx;
        jz 0x28f07f;
        push 1;
        pop ebx;
        movzx edi, word ptr [eax+0x395118];
    ''')
    # PUSH/POP and MOVZX leave room for the guard within the existing span.
    # The following original instructions still query charge without consuming it.
    assert len(body) == len(READINESS_BEFORE)
    return body


def readiness_install(write, read):
    from features.input_views import _install
    return _install([(READINESS_SITE, readiness_body())],
                    {READINESS_SITE: READINESS_BEFORE}, write, read)


def readiness_verify(read):
    from features.input_views import _verify
    return _verify([(READINESS_SITE, readiness_body())], read)

POST = 0x1dc8000
MARK = 0x1dc8400
RESOLVE = 0x1dc8800
QUAL = 0x1dc8b00
VEHICLE_ALIGN = 0x1dc8e00
AIM = 0x1dc9000
AI_GATE = 0x1dc9200
FAIL = 0x1dc9400
RESET = 0x1dc9600
RELEASE = 0x1dc9800
STATE = 0x1dca000
TABLE = 0x1dcc000
COUNT = 1024
STRIDE = 64
# Scoped feedback from the final AI range/ally check. The controller saves,
# clears and restores this word around one real firing call, so an earlier veto
# cannot affect another attempt. Existing whole-row reset/reallocation clears it.
LAUNCH_VETO = 40
BASE = 0x1dc9a00
BURST = 0x1dc9e00
ALLOC = 0x1dc9f00
# Row: weapon pointer, weapon id, target, last eligible frame, armed,
# assigned deadline, last eligible clock, reserved, aim frame+1, aim target,
# scoped launch veto; remaining bytes are reserved.
HOOKS = {
    0x28f70f: bytes.fromhex('a1e86a440081e2ffff0000'),
    0x28f64e: bytes.fromhex('3b1de86a4400'),
    0x293826: bytes.fromhex('8a44242483c428'),
    0x293811: bytes.fromhex('807c2420007408'),
    0x251ee8: bytes.fromhex('80bc24a800000000'),
    0x28f551: bytes.fromhex('89ec5d5f5e'),
    0x28f7f1: bytes.fromhex('89ec5d5f5e'),
    0x290858: bytes.fromhex('53528b1550134400'),
    0x296828: bytes.fromhex('535152668b1547323c00')
}
QUAL_CALLS = (0x269ec5, 0x2745ac, 0x274c7f)


def _emit(write, asm):
    from features.effect_timing import BEAM_PRESSURE
    blocks = []

    def add(a, s, cap=0x200):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        write(a, b)
        blocks.append((a, b))

    # Resolve a live object's selected weapon and energy block. EDX is owner;
    # result EAX=weapon, EBX=energy (zero EAX for unsupported/invalid objects).
    add(RESOLVE, selected_weapon_source())
    # EAX=weapon, EDX=owner, ECX=target, EBX=1 iff all resources available.
    # Preserve every register. Repeated marks within a frame cannot manufacture
    # continuity; missing a whole eligible frame clears the armed deadline.
    add(
        MARK, (
            f"\n pushfd;"
            f" pushad;"
            f"\n test edx,edx;"
            f" jle done;"
            f" cmp edx,{COUNT};"
            f" jae done;"
            f" test eax,eax;"
            f" jz done;"
            f"\n mov esi,edx;"
            f" shl esi,6;"
            f" add esi,{TABLE};"
            f" mov edi,dword ptr [0x35f400];"
            f"\n cmp eax,[esi];"
            f" jne fresh;"
            f" movzx edx,byte ptr [eax];"
            f" cmp edx,[esi+4];"
            f" jne fresh;"
            f"\n cmp ecx,[esi+8];"
            f" jne fresh;"
            f" mov edx,[0x446ae8];"
            f" cmp edx,[esi+24];"
            f" jb fresh;"
            f"\n cmp edi,[esi+12];"
            f" je known;"
            f" dec edi;"
            f" cmp edi,[esi+12];"
            f" jne fresh;"
            f" inc edi;"
            f" jmp known;"
            f"\n fresh: mov dword ptr [esi+16],0;"
            f" mov edi,[0x35f400];"
            f" inc dword ptr [{STATE+8}];"
            f"\n known: test ebx,ebx;"
            f" jnz available;"
            f" mov dword ptr [esi+16],0;"
            f"\n available: mov [esi],eax;"
            f" movzx edx,byte ptr [eax];"
            f" mov [esi+4],edx;"
            f" mov [esi+8],ecx;"
            f"\n mov [esi+12],edi;"
            f" mov edx,[0x446ae8];"
            f" mov [esi+24],edx;"
            f" inc dword ptr [{STATE+4}];"
            f"\n done: popad;"
            f" popfd;"
            f" ret;"
            f"\n "
        ), 0x400
    )
    # Qualified player readiness calls. Automatic mini-camera polling also runs
    # without the trigger, so require the original held-fire bit there.
    qualifier = (
        f"\n push edx;"
        f" push eax;"
        f" call 0x28f024;"
        f" pushfd;"
        f" pushad;"
        f"\n mov edi,eax;"
        f" mov edx,[0x441350];"
        f" shr edx,16;"
        f" cmp edx,60;"
        f" jae done;"
        f"\n imul esi,edx,0x582;"
        f" add esi,0x3a5608;"
        f"\n cmp dword ptr [esp+44],0x2745b1;"
        f" je intent;"
        f"\n test byte ptr [esi+0xcf],2;"
        f" jz done;"
        f"\n intent: mov eax,[esp+36];"
        f" movzx edx,word ptr [0x441350];"
        f"\n xor ecx,ecx;"
        f" cmp byte ptr [0x35a944],0;"
        f" je target_ready;"
        f" movzx ecx,word ptr [0x35a93c];"
        f"\n target_ready: xor ebx,ebx;"
        f" and edi,255;"
        f" test edi,edi;"
        f" jz available;"
        f" cmp edi,5;"
        f" jne marked;"
        f"\n available: inc ebx;"
        f"\n marked: call {MARK};"
        f"\n done: popad;"
        f" popfd;"
        f" lea esp,[esp+8];"
        f" ret;"
        f"\n "
    )
    add(QUAL, qualifier, 0x300)
    # The vehicle's failed-alignment branch originally enters the stack cleanup
    # at 29382A, inside the seven-byte AIM hook. Redirect that complete decision
    # so a failed alignment keeps AL=0 and never enters overwritten bytes.
    add(
        VEHICLE_ALIGN, (
            "cmp byte ptr [esp+0x20],0;"
            " je failed;"
            " test al,al;"
            " je failed;"
            "\n mov al,1;"
            " jmp 0x293826;"
            "\n failed: xor al,al;"
            " add esp,0x28;"
            " jmp 0x29382d;"
        )
    )
    # 293826 is reached only after both original aim-alignment tests pass.
    add(
        AIM, (
            f"\n pushfd;"
            f" pushad;"
            f" movsx edx,word ptr [esp+36+0x18];"
            f"\n test edx,edx;"
            f" jle done;"
            f" cmp edx,{COUNT};"
            f" jae done;"
            f"\n shl edx,6;"
            f" add edx,{TABLE};"
            f" mov eax,[0x35f400];"
            f" inc eax;"
            f" mov [edx+32],eax;"
            f"\n movzx eax,word ptr [esp+36+0x14];"
            f" mov [edx+36],eax;"
            f"\n done: popad;"
            f" popfd;"
            f" mov al,byte ptr [esp+0x24];"
            f" add esp,0x28;"
            f" jmp 0x29382d;"
            f"\n "
        )
    )
    # This AI branch has passed the original target/fire-policy/line checks;
    # the saved ready boolean still includes cooldown. Do not bypass its decision.
    add(
        AI_GATE, (
            f"\n pushfd;"
            f" pushad;"
            f" cmp byte ptr [esp+36+0xa8],0;"
            f" je done;"
            f"\n movsx edx,word ptr [esi+0x0b];"
            f" test edx,edx;"
            f" jle done;"
            f" cmp edx,{COUNT};"
            f" jae done;"
            f"\n mov edi,edx;"
            f" shl edi,6;"
            f" add edi,{TABLE};"
            f" mov eax,[0x35f400];"
            f" inc eax;"
            f"\n cmp eax,[edi+32];"
            f" jne done;"
            f" movzx ecx,byte ptr [esi+0xca];"
            f" cmp ecx,[edi+36];"
            f" jne done;"
            f"\n call {RESOLVE};"
            f" test eax,eax;"
            f" jz done;"
            f" push ecx;"
            f" push edx;"
            f" push eax;"
            f"\n mov edx,ebx;"
            f" call 0x28f024;"
            f" movzx ebx,al;"
            f" pop eax;"
            f" pop edx;"
            f" pop ecx;"
            f"\n cmp ebx,5;"
            f" je available;"
            f" test ebx,ebx;"
            f" jz available;"
            f" xor ebx,ebx;"
            f" jmp marked;"
            f"\n available: mov ebx,1;"
            f"\n marked: call {MARK};"
            f"\n done: popad;"
            f" popfd;"
            f" cmp byte ptr [esp+0xa8],0;"
            f" jmp 0x251ef0;"
            f"\n "
        )
    )
    # Replace only the base time in the original post-success deadline addition.
    # Duration already includes difficulty scaling and the original burst pause.
    add(
        BASE, (
            f"\n pushfd;"
            f" pushad;"
            f" mov ebx,[0x446ae8];"
            f"\n movsx edx,si;"
            f" test edx,edx;"
            f" jle unchanged;"
            f" cmp edx,{COUNT};"
            f" jae unchanged;"
            f"\n shl edx,6;"
            f" add edx,{TABLE};"
            f" cmp edi,[edx];"
            f" jne unchanged;"
            f"\n movzx eax,byte ptr [edi];"
            f" cmp eax,[edx+4];"
            f" jne unchanged;"
            f"\n mov eax,[0x35f400];"
            f" cmp eax,[edx+12];"
            f" jne unchanged;"
            f"\n cmp dword ptr [edx+16],0;"
            f" je unchanged;"
            f" mov eax,[edi+10];"
            f" cmp eax,[edx+20];"
            f" jne unchanged;"
            f"\n mov ebp,ebx;"
            f" sub ebp,eax;"
            f" jb unchanged;"
            f"\n cmp dword ptr [0x35f3f8],100;"
            f" ja unchanged;"
            f" cmp ebp,[0x35f3f8];"
            f" ja unchanged;"
            f"\n movzx eax,byte ptr [edi];"
            f" imul eax,eax,36;"
            f" movzx ecx,word ptr [eax+0x395126];"
            f"\n cmp si,word ptr [0x441350];"
            f" jne other;"
            f"\n cmp dword ptr [0x35cd9c],0;"
            f" je player_rate;"
            f" test byte ptr [0x442f1b],4;"
            f" jnz unchanged;"
            f"\n player_rate: movzx eax,byte ptr [0x442900];"
            f" movzx eax,word ptr [eax*2+0x396360];"
            f" jmp scale;"
            f"\n other: movsx eax,si;"
            f" imul eax,eax,37;"
            f" cmp byte ptr [eax+0x3c3241],1;"
            f" jne enemy_rate;"
            f"\n movzx eax,byte ptr [eax+0x3c3242];"
            f" cmp eax,2;"
            f" jbe period;"
            f" cmp eax,13;"
            f" je period;"
            f"\n enemy_rate: movzx eax,byte ptr [0x442900];"
            f" movzx eax,word ptr [eax*2+0x39636a];"
            f"\n scale: imul eax,ecx;"
            f" xor edx,edx;"
            f" mov ecx,100;"
            f" div ecx;"
            f" mov ecx,eax;"
            f"\n period: cmp ebp,ecx;"
            f" jae unchanged;"
            f" sub ebx,ebp;"
            f"\n unchanged: mov [esp+28],ebx;"
            f"\n popad;"
            f" popfd;"
            f" ret;"
            f"\n "
        ), 0x400
    )
    add(BURST, (f"push eax;"
                f" call {BASE};"
                f" cmp ebx,eax;"
                f" pop eax;"
                f" jmp 0x28f654;"))
    add(
        POST, (
            f"\n call {BASE};"
            f" pushfd;"
            f" pushad;"
            f" mov ebx,eax;"
            f" mov ecx,[0x446ae8];"
            f" sub ecx,ebx;"
            f"\n add dword ptr [{STATE+12}],ecx;"
            f" test ecx,ecx;"
            f" jz exact;"
            f" inc dword ptr [{STATE}];"
            f"\n exact: mov ecx,edx;"
            f" and ecx,65535;"
            f" movsx edx,si;"
            f" test edx,edx;"
            f" jle done;"
            f" cmp edx,{COUNT};"
            f" jae done;"
            f"\n shl edx,6;"
            f" add edx,{TABLE};"
            f" cmp edi,[edx];"
            f" jne done;"
            f" movzx eax,byte ptr [edi];"
            f" cmp eax,[edx+4];"
            f" jne done;"
            f"\n mov eax,[0x35f400];"
            f" cmp eax,[edx+12];"
            f" jne done;"
            f"\n add ecx,ebx;"
            f" mov [edx+20],ecx;"
            f" mov dword ptr [edx+16],1;"
            f"\n done: popad;"
            f" popfd;"
            f" and edx,65535;"
            f" jmp 0x28f71a;"
            f"\n "
        ), 0x400
    )
    # Both original common-fire exits have the same five-byte epilogue. Dry-run
    # trajectory queries (actual flag 0) must not alter scheduler state.
    add(
        FAIL, (
            f"\n pushfd;"
            f" pushad;"
            f" cmp byte ptr [ebp+0x28],0;"
            f" je done;"
            f" test ax,ax;"
            f" jg done;"
            f"\n mov edx,[ebp-0x2c];"
            f" test edx,edx;"
            f" jle done;"
            f" cmp edx,{COUNT};"
            f" jae done;"
            f"\n shl edx,6;"
            f" mov dword ptr [edx+{TABLE+16}],0;"
            f" inc dword ptr [{STATE+20}];"
            f"\n done: popad;"
            f" popfd;"
            f" mov esp,ebp;"
            f" pop ebp;"
            f" pop edi;"
            f" pop esi;"
            f" ret 0x1c;"
            f"\n "
        )
    )
    add(
        RESET, (
            f"pushfd;"
            f" pushad;"
            f" cld;"
            f" xor eax,eax;"
            f" mov edi,{TABLE};"
            f" mov ecx,{COUNT*STRIDE//4};"
            f" rep stosd;"
            f"\n inc dword ptr [{STATE+24}];"
            f" popad;"
            f" popfd;"
            f" jmp 0x1dc0400;"
        )
    )
    add(
        RELEASE, (
            f"pushfd;"
            f" pushad;"
            f" movzx edx,word ptr [0x441350];"
            f" cmp edx,{COUNT};"
            f" jae done;"
            f"\n shl edx,6;"
            f" mov dword ptr [edx+{TABLE+16}],0;"
            f" inc dword ptr [{STATE+28}];"
            f"\n done: popad;"
            f" popfd;"
            f" push ebx;"
            f" push edx;"
            f" mov edx,[0x441350];"
            f" jmp 0x290860;"
        )
    )
    # Clear the entire private row whenever the original object allocator returns
    # an object ID. A reused ID must not inherit either phase or an AI aim token.
    add(
        ALLOC, (
            f"call {ALLOC+0x80};"
            f" pushfd;"
            f" pushad;"
            f" movzx eax,ax;"
            f"\n test eax,eax;"
            f" jz done;"
            f" cmp eax,{COUNT};"
            f" jae done;"
            f" shl eax,6;"
            f" lea edi,[eax+{TABLE}];"
            f"\n xor eax,eax;"
            f" mov ecx,16;"
            f" cld;"
            f" rep stosd;"
            f" inc dword ptr [{STATE+32}];"
            f"\n done: popad;"
            f" popfd;"
            f" ret;"
        ), 0x80
    )
    add(
        ALLOC + 0x80, (
            f"call {BEAM_PRESSURE};"
            "push ebx;"
            " push ecx;"
            " push edx;"
            " mov dx,word ptr [0x3c3247];"
            " jmp 0x296832;"
        ), 0x80
    )
    for a, b in HOOKS.items():
        target = {
            0x28f70f: POST,
            0x28f64e: BURST,
            0x293826: AIM,
            0x293811: VEHICLE_ALIGN,
            0x251ee8: AI_GATE,
            0x28f551: FAIL,
            0x28f7f1: FAIL,
            0x290858: RELEASE,
            0x296828: ALLOC
        }[a]
        write(a, asm(a, f'jmp {target}') + b'\x90' * (len(b) - 5))
    for a in QUAL_CALLS:
        write(a, asm(a, f'call {QUAL}'))
    write(0x2953f0, asm(0x2953f0, f'jmp {RESET}'))
    write(STATE, bytes(0x1000))
    write(TABLE, bytes(COUNT * STRIDE))
    return blocks


def sites():
    from patch_support import asm
    return dict(
        list(HOOKS.items()) + [(a, asm(a, 'call 0x28f024'))
                               for a in QUAL_CALLS] + [(0x2953f0, asm(0x2953f0, 'jmp 0x1dc0400'))]
    )


def bodies():
    from patch_support import asm
    pieces = []
    _emit(lambda a, b: pieces.append((a, b)), asm)
    return pieces


def install(write, read):
    from features.input_views import _install
    pieces = bodies()
    if all(bytes(read(a, len(b))) == b for a, b in pieces if a not in (STATE, TABLE)):
        return dict(already_installed=True, ranges=[])
    return _install(pieces, sites(), write, read)


def verify(read):
    from features.input_views import _verify
    # Stateful timing rows and counters are allowed in live checkpoints.
    return _verify([(a, b) for a, b in bodies() if a not in (STATE, TABLE)], read)
