"""Keep actor decisions, movement and poses consistent across frame rates.

The original movement and decision routines still choose what actors do. These
helpers control when those routines advance and share the reset of their clocks.
The 50-ms reference is the patch's calibration interval; it does not establish
the original game's frame rate. State addresses remain fixed for saved snapshots.
"""
import struct
from patch_support import asm

IDLE_MISSION_RESET = 0x1e2e900
AVOIDANCE_SLOT_RESET = 0x1e29500


def idle_mission_reset_body():
    return asm(
        IDLE_MISSION_RESET, (
            "pushfd;"
            "pushad;"
            "cld;"
            "mov edi,0x1e2f100;"
            "xor eax,eax;"
            "mov ecx,256;"
            "rep stosd;"
            "popad;"
            "popfd;"
            "jmp 0x1e29400;"
        )
    )


def avoidance_slot_reset_body():
    return asm(
        AVOIDANCE_SLOT_RESET, (
            "pushfd;"
            "pushad;"
            "mov eax,esi;"
            "sub eax,0x3832f0;"
            "xor edx,edx;"
            "mov ecx,334;"
            "div ecx;"
            "\n    test edx,edx;"
            "jnz done;"
            "cmp eax,60;"
            "jae done;"
            "shl eax,4;"
            "lea edi,[eax+0x1e2b000];"
            "\n    cld;"
            "xor eax,eax;"
            "mov ecx,4;"
            "rep stosd;"
            "done:popad;"
            "popfd;"
            "jmp 0x1e23500;"
        )
    )


# Attack polling: owner/type, target, frame/clock, armed deadline, observed flag.
# Carry bounded lateness only across continuously eligible frames; no catch-up attacks.
DRONE_CODE = 0x1e4f000
DRONE_STATE = 0x1e52000
DRONE_TABLE = 0x1e52100
DRONE_COUNT = 60
DRONE_STRIDE = 32
DRONE_LIMIT = 0x1e52880
DRONE_AI = 0x3832f0
DRONE_SITES = {
    0x24bba0: bytes.fromhex('5351525657'),
    0x24bc24: bytes.fromhex('39c80f83cc000000'),
    0x24bc80: bytes.fromhex('8986f6000000'),
    0x249b2c: bytes.fromhex('5352ba01000000'),
    0x24b52d: bytes.fromhex('c60601c1e004')
}


def drone_bodies():
    out = []

    def emit(a, s, cap=0x200):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    def hook(a, t):
        out.append((a, asm(a, f'jmp {t}') + b'\x90' * (len(DRONE_SITES[a]) - 5)))

    emit(
        DRONE_CODE, (
            f"pushfd;"
            f"pushad;"
            f"mov esi,eax;"
            f"sub eax,{DRONE_AI};"
            f"xor edx,edx;"
            f"mov ebx,334;"
            f"div ebx;"
            f"\n test edx,edx;"
            f"jnz invalid;"
            f"cmp eax,{DRONE_COUNT};"
            f"jae invalid;"
            f"shl eax,5;"
            f"lea edi,[eax+{DRONE_TABLE}];"
            f"\n cmp byte ptr [0x35f3f4],0;"
            f"jne stopped;"
            f"cmp dword ptr [0x35f3f8],0;"
            f"jle stopped;"
            f"\n movzx ebx,word ptr [esi+11];"
            f"cmp ebx,300;"
            f"jae inactive;"
            f"imul eax,ebx,37;"
            f"\n movzx ebp,byte ptr [eax+0x3c3242];"
            f"shl ebp,16;"
            f"or ebp,ebx;"
            f"\n movzx ebx,word ptr [esi+0xc9];"
            f"\n cmp byte ptr [esi],0;"
            f"je inactive;"
            f"cmp byte ptr [esi+5],2;"
            f"jne inactive;"
            f"\n movzx ecx,byte ptr [esi+0xca];"
            f"test ecx,ecx;"
            f"jz inactive;"
            f"imul ecx,37;"
            f"\n cmp byte ptr [ecx+0x3c3261],0;"
            f"je inactive;"
            f"\n movzx ecx,byte ptr [eax+0x3c3242];"
            f"cmp ecx,5;"
            f"je bomber;"
            f"cmp ecx,6;"
            f"je bomber;"
            f"\n cmp ecx,4;"
            f"jne eligible;"
            f"cmp dword ptr [esi+0x140],0;"
            f"je inactive;"
            f"jmp eligible;"
            f"\n bomber:cmp dword ptr [esi+0x13c],0;"
            f"jne inactive;"
            f"\n eligible:cmp dword ptr [edi+28],1;"
            f"jne fresh;"
            f"cmp [edi],ebp;"
            f"jne fresh;"
            f"cmp [edi+4],ebx;"
            f"jne fresh;"
            f"\n mov eax,[0x35f400];"
            f"cmp eax,[edi+8];"
            f"jne nextframe;"
            f"\n mov eax,[0x446ae8];"
            f"cmp eax,[edi+12];"
            f"je duplicate;"
            f"jmp fresh;"
            f"\n nextframe:sub eax,[edi+8];"
            f"cmp eax,1;"
            f"jne fresh;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+12];"
            f"test eax,eax;"
            f"jle fresh;"
            f"cmp eax,[0x35f3f8];"
            f"jne fresh;"
            f"\n cmp eax,250;"
            f"ja fresh;"
            f"cmp dword ptr [edi+16],0;"
            f"je update;"
            f"\n mov eax,[esi+0xf6];"
            f"cmp eax,[edi+20];"
            f"jne fresh;"
            f"jmp update;"
            f"\n fresh:mov dword ptr [edi+16],0;"
            f"inc dword ptr [{DRONE_STATE+8}];"
            f"\n update:mov [edi],ebp;"
            f"mov [edi+4],ebx;"
            f"mov eax,[0x35f400];"
            f"mov [edi+8],eax;"
            f"\n mov eax,[0x446ae8];"
            f"mov [edi+12],eax;"
            f"mov dword ptr [edi+28],1;"
            f"jmp original;"
            f"\n inactive:mov dword ptr [edi+16],0;"
            f"mov dword ptr [edi+28],0;"
            f"jmp original;"
            f"\n stopped:mov dword ptr [edi+16],0;"
            f"mov dword ptr [edi+28],0;"
            f"\n duplicate:popad;"
            f"popfd;"
            f"ret;"
            f"\n invalid:inc dword ptr [{DRONE_STATE+12}];"
            f"\n original:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x24bba5;"
        ), 0x500
    )
    hook(0x24bba0, DRONE_CODE)
    # Signed time difference permits a normal 32-bit game-clock wrap.
    emit(
        DRONE_CODE + 0x500, (
            "push edx;"
            "mov edx,ecx;"
            "sub edx,eax;"
            "test edx,edx;"
            "pop edx;"
            "jle 0x24bcf8;"
            "jmp 0x24bc2c;"
        )
    )
    hook(0x24bc24, DRONE_CODE + 0x500)
    emit(
        DRONE_CODE + 0x600, (
            f"pushfd;"
            f"pushad;"
            f"mov ebp,eax;"
            f"mov eax,esi;"
            f"sub eax,{DRONE_AI};"
            f"xor edx,edx;"
            f"mov ebx,334;"
            f"div ebx;"
            f"\n test edx,edx;"
            f"jnz store;"
            f"cmp eax,{DRONE_COUNT};"
            f"jae store;"
            f"shl eax,5;"
            f"lea edi,[eax+{DRONE_TABLE}];"
            f"\n inc dword ptr [{DRONE_STATE}];"
            f"cmp dword ptr [edi+16],1;"
            f"jne armed;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[esi+0xf6];"
            f"sub eax,250;"
            f"test eax,eax;"
            f"jle armed;"
            f"\n cmp eax,250;"
            f"ja armed;"
            f"cmp eax,[0x35f3f8];"
            f"ja armed;"
            f"\n sub ebp,eax;"
            f"inc dword ptr [{DRONE_STATE+4}];"
            f"\n armed:mov dword ptr [edi+16],1;"
            f"mov [edi+20],ebp;"
            f"\n store:mov [esi+0xf6],ebp;"
            f"popad;"
            f"popfd;"
            f"jmp 0x24bc86;"
        )
    )
    hook(0x24bc80, DRONE_CODE + 0x600)
    emit(
        DRONE_CODE + 0x800, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"xor eax,eax;"
            f"mov edi,{DRONE_TABLE};"
            f"mov ecx,{DRONE_COUNT*DRONE_STRIDE//4};"
            f"rep stosd;"
            f"\n popad;"
            f"popfd;"
            f"push ebx;"
            f"push edx;"
            f"mov edx,1;"
            f"jmp 0x249b33;"
        )
    )
    hook(0x249b2c, DRONE_CODE + 0x800)
    emit(
        DRONE_CODE + 0xa00, (
            f"pushfd;"
            f"pushad;"
            f"mov eax,esi;"
            f"sub eax,{DRONE_AI};"
            f"xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz finish;"
            f"cmp eax,{DRONE_COUNT};"
            f"jae finish;"
            f"shl eax,5;"
            f"lea edi,[eax+{DRONE_TABLE}];"
            f"xor eax,eax;"
            f"mov ecx,8;"
            f"cld;"
            f"rep stosd;"
            f"\n finish:popad;"
            f"popfd;"
            f"mov byte ptr [esi],1;"
            f"shl eax,4;"
            f"jmp 0x24b533;"
        )
    )
    hook(0x24b52d, DRONE_CODE + 0xa00)
    return out


DRONE_HOOKS = DRONE_SITES
DRONE_SHARED = {}

# Automatic non-combat aircraft execute original movement in 50-ms steps.
# Directly controlled drones and combat aircraft bypass this compatibility clock.
AIRCRAFT_CODE = 0x1ff8000
AIRCRAFT_ORIGINAL = 0x1ff8600
AIRCRAFT_FREE = 0x1ff8700
AIRCRAFT_TABLE = 0x1ff9000
AIRCRAFT_COUNT = 40
AIRCRAFT_STRIDE = 32
AIRCRAFT_LIMIT = 0x1ff9500
AIRCRAFT_SITE = 0x283f2c
AIRCRAFT_DELETE = 0x2844f4
AIRCRAFT_OLD = bytes.fromhex('5351565755')


def aircraft_bodies():
    # Rows: armed, owner/type, frame, clock, remainder, steps, reserved, reserved.
    b = asm(
        AIRCRAFT_CODE, (
            f"pushfd;"
            f"pushad;"
            f"mov esi,eax;"
            f"mov ebp,edx;"
            f"\n sub eax,0x39e590;"
            f"xor edx,edx;"
            f"mov ecx,335;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz passthrough;"
            f"cmp eax,{AIRCRAFT_COUNT};"
            f"jae passthrough;"
            f"\n shl eax,5;"
            f"lea edi,[eax+{AIRCRAFT_TABLE}];"
            f"movzx ebx,word ptr [esi];"
            f"and ebx,0x7fff;"
            f"\n test ebx,ebx;"
            f"jz inactive;"
            f"cmp ebx,300;"
            f"jae inactive;"
            f"\n imul eax,ebx,37;"
            f"add eax,0x3c3240;"
            f"cmp byte ptr [eax],0;"
            f"je inactive;"
            f"\n cmp byte ptr [eax+1],3;"
            f"jne inactive;"
            f"movzx ecx,byte ptr [eax+2];"
            f"\n cmp ecx,1;"
            f"jbe passthrough_row;"
            f"\n cmp ecx,7;"
            f"jb passthrough_row;"
            f"cmp ecx,14;"
            f"ja passthrough_row;"
            f"\n shl ecx,16;"
            f"or ebx,ecx;"
            f"\n cmp byte ptr [0x35f3f4],0;"
            f"jne stopped;"
            f"test ebp,ebp;"
            f"jle stopped;"
            f"\n cmp dword ptr [edi],1;"
            f"jne fresh;"
            f"cmp [edi+4],ebx;"
            f"jne fresh;"
            f"\n mov eax,[0x35f400];"
            f"cmp eax,[edi+8];"
            f"jne nextframe;"
            f"\n mov eax,[0x446ae8];"
            f"cmp eax,[edi+12];"
            f"je done;"
            f"jmp fresh;"
            f"\n nextframe:sub eax,[edi+8];"
            f"cmp eax,1;"
            f"jne fresh;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+12];"
            f"cmp eax,ebp;"
            f"jne fresh;"
            f"test eax,eax;"
            f"jle fresh;"
            f"jmp known;"
            f"\n fresh:mov dword ptr [edi+16],0;"
            f"mov dword ptr [edi],1;"
            f"mov [edi+4],ebx;"
            f"\n known:mov eax,[0x35f400];"
            f"mov [edi+8],eax;"
            f"mov eax,[0x446ae8];"
            f"mov [edi+12],eax;"
            f"\n cmp ebp,250;"
            f"jbe credit;"
            f"mov ebp,50;"
            f"mov dword ptr [edi+16],0;"
            f"\n credit:add [edi+16],ebp;"
            f"\n again:cmp dword ptr [edi+16],50;"
            f"jb done;"
            f"sub dword ptr [edi+16],50;"
            f"\n inc dword ptr [edi+20];"
            f"mov eax,esi;"
            f"mov edx,50;"
            f"push edi;"
            f"push esi;"
            f"call {AIRCRAFT_ORIGINAL};"
            f"pop esi;"
            f"pop edi;"
            f"\n cmp dword ptr [edi],1;"
            f"jne done;"
            f"\n movzx eax,word ptr [esi];"
            f"and eax,0x7fff;"
            f"mov ecx,[edi+4];"
            f"and ecx,0xffff;"
            f"cmp eax,ecx;"
            f"jne stopped;"
            f"\n imul eax,37;"
            f"cmp byte ptr [eax+0x3c3240],0;"
            f"je stopped;"
            f"jmp again;"
            f"\n stopped:mov dword ptr [edi],0;"
            f"mov dword ptr [edi+16],0;"
            f"jmp done;"
            f"\n inactive:mov dword ptr [edi],0;"
            f"jmp done;"
            f"\n passthrough_row:mov dword ptr [edi],0;"
            f"mov dword ptr [edi+16],0;"
            f"\n passthrough:popad;"
            f"popfd;"
            f"jmp {AIRCRAFT_ORIGINAL};"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    # Original function saves all registers except its EAX/EDX scratch outputs.
    trampoline = AIRCRAFT_OLD + asm(AIRCRAFT_ORIGINAL + len(AIRCRAFT_OLD), f'jmp {AIRCRAFT_SITE+5}')
    # A deleted record must not carry fractional credit into immediate reuse.
    free = asm(
        AIRCRAFT_FREE, (
            f"pushfd;"
            f"pushad;"
            f"movsx eax,ax;"
            f"test eax,eax;"
            f"jle finish;"
            f"cmp eax,300;"
            f"jae finish;"
            f"\n imul eax,37;"
            f"cmp byte ptr [eax+0x3c3241],3;"
            f"jne finish;"
            f"\n movsx eax,word ptr [eax+0x3c3243];"
            f"cmp eax,{AIRCRAFT_COUNT};"
            f"jae finish;"
            f"shl eax,5;"
            f"\n lea edi,[eax+{AIRCRAFT_TABLE}];"
            f"xor eax,eax;"
            f"mov ecx,8;"
            f"cld;"
            f"rep stosd;"
            f"\n finish:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"sub esp,8;"
            f"jmp {AIRCRAFT_DELETE+7};"
        )
    )
    assert len(b) < 0x600 and len(free) < 0x100
    return [
        (AIRCRAFT_CODE, b), (AIRCRAFT_ORIGINAL, trampoline), (AIRCRAFT_FREE, free),
        (AIRCRAFT_SITE, asm(AIRCRAFT_SITE, f'jmp {AIRCRAFT_CODE}')),
        (AIRCRAFT_DELETE, asm(AIRCRAFT_DELETE, f'jmp {AIRCRAFT_FREE}') + b'\x90\x90')
    ]


AIRCRAFT_HOOKS = {0x283f2c: bytes.fromhex('5351565755'), 0x2844f4: bytes.fromhex('5351525683ec08')}
AIRCRAFT_SHARED = {}

# Retry/orbit: elapsed credit drives the original random tests. Retry draws use
# the upper RNG bits to avoid low-bit phase locking; orbit keeps its original range.
GATES_CODE = 0x1ffa000
GATES_STATE = 0x1ffc000
GATES_TABLE = 0x1ffd000
GATES_STRIDE = 32
GATES_GATES = [
    {
        'name': 'squad',
        'entry': 0x256e40,
        'end': 0x256e71,
        'reg': 'ebp',
        'base': 0x3804f0,
        'stride': 368,
        'count': 32,
        'offset': 153,
        'table': 0x1ffd000
    }, {
        'name': 'individual',
        'entry': 0x250454,
        'end': 0x250485,
        'reg': 'esi',
        'base': 0x3832f0,
        'stride': 334,
        'count': 60,
        'offset': 177,
        'table': 0x1ffd400
    }, {
        'name': 'orbit',
        'entry': 0x24c5d1,
        'end': 0x24c5ff,
        'reg': 'ecx',
        'base': 0x3832f0,
        'stride': 334,
        'count': 60,
        'offset': 332,
        'table': 0x1ffdc00
    }
]
GATES_TABLE_SIZE = 5120


def _gate_emit(write, reference=20, *, retry_range=63):
    assert reference in (20, 30)
    assert retry_range in (63, 0x7fff)
    period = 1000 // reference
    hooks = {}
    regions = []

    def hook(a, addr, n):
        b = asm(a, f'jmp {addr}') + b'\x90' * (n - 5)
        write(a, b)
        hooks[a] = b

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b), cap)
        write(a, b)
        regions.append((a, len(b)))

    for index, g in enumerate(GATES_GATES):
        entry = g['entry']
        end = g['end']
        offset = g['offset']
        addr = GATES_CODE + index * 0x400
        stats = GATES_STATE + index * 16
        orbit = index == 2
        owner = 'movzx eax,word ptr [esi+11];' if index else 'xor eax,eax;'
        eligible = '' if orbit else f'cmp byte ptr [esi+{offset}],0;je inactive;'
        result = (
            f"cmp byte ptr [esi+{offset}],0;"
            f"sete al;"
            f"mov byte ptr [esi+{offset}],al;"
            f"inc dword ptr [{stats+4}];"
            f"jmp more;"
        ) if orbit else (
            f"mov byte ptr [esi+{offset}],0;"
            f"inc dword ptr [{stats+4}];"
            f"mov dword ptr [edi],0;"
            f"jmp done;"
        )
        divisor = 500 if orbit else 64
        success = 100 if orbit else 0
        random_range = 0x7fff if orbit else retry_range
        # Entire wrapper preserves the surrounding routine's register state. The
        # three original continuations re-establish their own flags/register inputs.
        emit(
            addr, (
                f"pushfd;"
                f"pushad;"
                f"mov esi,{g['reg']};"
                f"mov eax,esi;"
                f"sub eax,{g['base']};"
                f"\n  xor edx,edx;"
                f"mov ebx,{g['stride']};"
                f"div ebx;"
                f"test edx,edx;"
                f"jnz invalid;"
                f"cmp eax,{g['count']};"
                f"jae invalid;"
                f"\n  shl eax,5;"
                f"lea edi,[eax+{g['table']}];"
                f"inc dword ptr [{stats+12}];"
                f"\n  cmp byte ptr [esi],0;"
                f"je inactive;"
                f"{eligible}\n  cmp byte ptr [0x35f3f4],0;"
                f"jne done;"
                f"mov ebp,[0x35f3f8];"
                f"test ebp,ebp;"
                f"jle done;"
                f"\n  {owner}cmp dword ptr [edi+16],1;"
                f"jne fresh;"
                f"cmp [edi+12],eax;"
                f"jne fresh;"
                f"\n  mov edx,[0x446ae8];"
                f"cmp edx,[edi+8];"
                f"jb fresh;"
                f"\n  mov ecx,[0x35f400];"
                f"cmp ecx,[edi+4];"
                f"je done;"
                f"\n  sub edx,[edi+8];"
                f"cmp edx,ebp;"
                f"jne fresh;"
                f"jmp known;"
                f"\n  fresh:mov dword ptr [edi],0;"
                f"mov [edi+12],eax;"
                f"mov dword ptr [edi+16],1;"
                f"\n  known:mov eax,[0x35f400];"
                f"mov [edi+4],eax;"
                f"mov eax,[0x446ae8];"
                f"mov [edi+8],eax;"
                f"\n  cmp ebp,250;"
                f"jbe bounded;"
                f"mov ebp,1000;"
                f"mov dword ptr [edi],0;"
                f"jmp add_credit;"
                f"\n  bounded:imul ebp,{reference};"
                f"\n  add_credit:add [edi],ebp;"
                f"\n  more:cmp dword ptr [edi],1000;"
                f"jb done;"
                f"sub dword ptr [edi],1000;"
                f"\n  mov eax,0x3596e0;"
                f"mov ebx,{random_range};"
                f"xor edx,edx;"
                f"call 0x2ddd70;"
                f"\n  inc dword ptr [{stats}];"
                f"mov edx,eax;"
                f"sar edx,31;"
                f"mov ebx,{divisor};"
                f"idiv ebx;"
                f"cmp edx,{success};"
                f"jne more;"
                f"\n  {result}\n  inactive:mov dword ptr [edi],0;"
                f"mov dword ptr [edi+16],0;"
                f"jmp done;"
                f"\n  invalid:inc dword ptr [{stats+8}];"
                f"\n  done:popad;"
                f"popfd;"
                f"jmp {end};"
            ), 0x400
        )
        hook(entry, addr, 7 if not orbit else 5)
    # Reset all private timing on original whole-AI initialization.
    reset = GATES_CODE + 0xc00
    emit(
        reset, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{GATES_TABLE};"
            f"xor eax,eax;"
            f"mov ecx,{GATES_TABLE_SIZE//4};"
            f"rep stosd;"
            f"mov edi,{AIRCRAFT_TABLE};"
            f"mov ecx,{(AIRCRAFT_LIMIT-AIRCRAFT_TABLE)//4};"
            f"rep stosd;"
            f"popad;"
            f"popfd;"
            f"jmp {DRONE_CODE+0x800};"
        ), 0x100
    )
    hook(0x249b2c, reset, 7)

    # Clear the appropriate rows whenever original AI slots become active, even
    # when a recycled slot has the same owner object id in the same frame.
    def clearrow(reg, base, stride, count, tables):
        return (
            f"pushfd;"
            f"pushad;"
            f"mov eax,{reg};"
            f"sub eax,{base};"
            f"xor edx,edx;"
            f"mov ecx,{stride};"
            f"div ecx;"
            f"\n  test edx,edx;"
            f"jnz finish;"
            f"cmp eax,{count};"
            f"jae finish;"
            f"shl eax,5;"
            f"mov ebx,eax;"
            f"cld;"
        ) + ''.join(
            (f"mov edi,{table};"
             f"add edi,ebx;"
             f"xor eax,eax;"
             f"mov ecx,8;"
             f"rep stosd;") for table in tables
        ) + 'finish:popad;popfd;'

    ai_alloc = GATES_CODE + 0xd00
    emit(
        ai_alloc,
        clearrow('esi', 0x3832f0, 334, 60, [GATES_TABLE + 0x400, GATES_TABLE + 0xc00]) +
        f'jmp {DRONE_CODE+0xa00};', 0x100
    )
    hook(0x24b52d, ai_alloc, 6)
    squad_alloc = GATES_CODE + 0xe00
    emit(
        squad_alloc,
        clearrow('ebx', 0x3804f0, 368, 32, [GATES_TABLE]) +
        'mov byte ptr [ebx],1;add eax,edx;jmp 0x253b5b;', 0x100
    )
    hook(0x253b56, squad_alloc, 5)
    # A newly failed path starts a new waiting episode. Do not carry time left
    # from a previous successful retry or an external cancellation into it.
    for i, (a, reg, which) in enumerate(
        ((0x250522, 'esi', 1), (0x254c9a, 'esi', 0), (0x256f13, 'ebp', 0))
    ):
        g = GATES_GATES[which]
        addr = GATES_CODE + 0xf00 + i * 0x100
        emit(
            addr,
            clearrow(reg, g['base'], g['stride'], g['count'], [g['table']]) +
            f'mov byte ptr [{reg}+{g["offset"]}],1;jmp {a+7};', 0x100
        )
        hook(a, addr, 7)
    write(GATES_STATE, bytes(0x1000))
    write(GATES_TABLE, bytes(GATES_TABLE_SIZE))
    return dict(
        reference_hz=reference,
        period_ms=period,
        hooks={
            hex(a): b.hex()
            for a, b in hooks.items()
        },
        regions=regions
    )


def gates_bodies(*, retry_range=63, reference=20):
    """Direct final retry odds; the wide-range profile is private oracle input."""
    pieces = []
    _gate_emit(lambda a, b: pieces.append((a, b)), reference, retry_range=retry_range)
    return pieces


GATES_SHARED = {a: b for a, b in drone_bodies() if a in (0x249b2c, 0x24b52d)}
GATES_HOOKS = {
    **GATES_SHARED,
    **{
        0x256e40: bytes.fromhex('80bd9900000000'),
        0x250454: bytes.fromhex('80beb100000000'),
        0x24c5d1: bytes.fromhex('b8e0963500'),
        0x253b56: bytes.fromhex('c6030101d0'),
        0x250522: bytes.fromhex('c686b100000001'),
        0x254c9a: bytes.fromhex('c6869900000001'),
        0x256f13: bytes.fromhex('c6859900000001')
    }
}

# Cache only random rolls for 50 game ms. All current detection policy runs each query.
PERCEPTION_CODE = 0x1e23000
PERCEPTION_STATE = 0x1e24000
PERCEPTION_TABLE = 0x1e25000
PERCEPTION_COLS = 61
PERCEPTION_TABLE_SIZE = 15616
PERCEPTION_SITE = 0x257e5e
PERCEPTION_REPRESENTATIVE = 0x2575e3


def perception_bodies():
    pieces = []

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        pieces.append((a, b))

    # Caller stack local +134 holds the observing squad. A call return address
    # and PUSHFD/PUSHAD add 40 bytes. ECX still holds the candidate AI record.
    emit(
        PERCEPTION_CODE, (
            f"pushfd;"
            f"pushad;"
            f"inc dword ptr [{PERCEPTION_STATE}];"
            f"\n mov eax,[esp+0x15c];"
            f"sub eax,0x3804f0;"
            f"xor edx,edx;"
            f"mov ebx,368;"
            f"div ebx;"
            f"\n test edx,edx;"
            f"jnz invalid;"
            f"cmp eax,32;"
            f"jae invalid;"
            f"imul edi,eax,{PERCEPTION_COLS};"
            f"\n mov eax,ecx;"
            f"sub eax,0x3832f0;"
            f"xor edx,edx;"
            f"mov ebx,334;"
            f"div ebx;"
            f"\n test edx,edx;"
            f"jnz invalid;"
            f"cmp eax,60;"
            f"jae invalid;"
            f"add edi,eax;"
            f"\n lea edi,[edi*8+{PERCEPTION_TABLE}];"
            f"movzx esi,word ptr [ecx+11];"
            f"test esi,esi;"
            f"jz invalid;"
            f"\n cmp esi,300;"
            f"jae invalid;"
            f"jmp {PERCEPTION_CODE+0x200};"
            f"\n invalid:inc dword ptr [{PERCEPTION_STATE+12}];"
            f"popad;"
            f"popfd;"
            f"jmp 0x2ddd70;"
        ), 0x200
    )
    emit(
        PERCEPTION_CODE + 0x200, (
            f"mov ebp,[0x446ae8];"
            f"cmp [edi+6],si;"
            f"jne fresh;"
            f"\n mov eax,ebp;"
            f"sub eax,[edi];"
            f"js fresh;"
            f"cmp eax,50;"
            f"jb cached;"
            f"\n cmp eax,250;"
            f"ja fresh;"
            f"xor edx,edx;"
            f"mov ebx,50;"
            f"div ebx;"
            f"\n sub ebp,edx;"
            f"jmp roll;"
            f"\n fresh:\n roll:mov [edi],ebp;"
            f"mov [edi+6],si;"
            f"\n mov eax,0x3596e0;"
            f"xor edx,edx;"
            f"mov ebx,0x7fff;"
            f"call 0x2ddd70;"
            f"\n mov [edi+4],ax;"
            f"inc dword ptr [{PERCEPTION_STATE+4}];"
            f"jmp result;"
            f"\n cached:movzx eax,word ptr [edi+4];"
            f"inc dword ptr [{PERCEPTION_STATE+8}];"
            f"\n result:mov [esp+28],eax;"
            f"mov [esp+20],eax;"
            f"popad;"
            f"popfd;"
            f"ret;"
        ), 0x200
    )
    # Original range RNG leaves EAX=EDX for range [0,32767]; downstream code
    # overwrites flags before observing them. Other registers are preserved.
    pieces.append((PERCEPTION_SITE, asm(PERCEPTION_SITE, f'call {PERCEPTION_CODE}')))
    # The fallback also randomly chooses one current squad member as observer.
    # Scope this second cache to that caller; other uses of 2575c0 are untouched.
    emit(
        PERCEPTION_CODE + 0x700, (
            f"cmp dword ptr [esp+20],0x257d86;"
            f"jne passthrough;"
            f"\n pushfd;"
            f"pushad;"
            f"inc dword ptr [{PERCEPTION_STATE+16}];"
            f"mov eax,ecx;"
            f"sub eax,0x3804f0;"
            f"\n xor edx,edx;"
            f"mov ebx,368;"
            f"div ebx;"
            f"test edx,edx;"
            f"jnz invalid;"
            f"cmp eax,32;"
            f"jae invalid;"
            f"\n imul edi,eax,{PERCEPTION_COLS*8};"
            f"add edi,{PERCEPTION_TABLE+60*8};"
            f"mov esi,1;"
            f"jmp {PERCEPTION_CODE+0x200};"
            f"\n invalid:popad;"
            f"popfd;"
            f"passthrough:jmp 0x2ddd70;"
        ), 0x100
    )
    pieces.append(
        (
            PERCEPTION_REPRESENTATIVE,
            asm(PERCEPTION_REPRESENTATIVE, f'call {PERCEPTION_CODE+0x700}')
        )
    )
    for site, entry, kind, target in (
        (0x249b2c, PERCEPTION_CODE + 0x400, 'all',
         GATES_CODE + 0xc00), (0x24b52d, PERCEPTION_CODE + 0x500, 'target', GATES_CODE + 0xd00),
        (0x253b56, PERCEPTION_CODE + 0x600, 'squad', GATES_CODE + 0xe00)
    ):
        if kind == 'all':
            s = (
                f"cld;"
                f"mov edi,{PERCEPTION_TABLE};"
                f"xor eax,eax;"
                f"mov ecx,{PERCEPTION_TABLE_SIZE//4};"
                f"rep stosd;"
            )
        elif kind == 'target':
            s = (
                f"mov eax,esi;"
                f"sub eax,0x3832f0;"
                f"xor edx,edx;"
                f"mov ecx,334;"
                f"div ecx;"
                f"\n   test edx,edx;"
                f"jnz done;"
                f"cmp eax,60;"
                f"jae done;"
                f"lea edi,[eax*8+{PERCEPTION_TABLE}];"
                f"\n   mov ecx,32;"
                f"xor eax,eax;"
                f"again:mov [edi],eax;"
                f"mov [edi+4],eax;"
                f"add edi,{PERCEPTION_COLS*8};"
                f"loop again;"
            )
        else:
            s = (
                f"mov eax,ebx;"
                f"sub eax,0x3804f0;"
                f"xor edx,edx;"
                f"mov ecx,368;"
                f"div ecx;"
                f"\n   test edx,edx;"
                f"jnz done;"
                f"cmp eax,32;"
                f"jae done;"
                f"imul eax,eax,{PERCEPTION_COLS*8};"
                f"lea edi,[eax+{PERCEPTION_TABLE}];"
                f"\n   cld;"
                f"xor eax,eax;"
                f"mov ecx,{PERCEPTION_COLS*2};"
                f"rep stosd;"
            )
        emit(entry, (f"pushfd;"
                     f"pushad;"
                     f"{s}done:popad;"
                     f"popfd;"
                     f"jmp {target};"), 0x100)
        pieces.append(
            (site, asm(site, f'jmp {entry}') + b'\x90' * (len(PERCEPTION_SHARED[site]) - 5))
        )
    pieces.extend(((PERCEPTION_STATE, bytes(64)), (PERCEPTION_TABLE, bytes(PERCEPTION_TABLE_SIZE))))
    return pieces


PERCEPTION_SHARED = {a: b for a, b in gates_bodies() if a in (0x249b2c, 0x24b52d, 0x253b56)}
PERCEPTION_HOOKS = {
    **PERCEPTION_SHARED,
    **{
        0x257e5e: bytes.fromhex('e80d5f0800'),
        0x2575e3: bytes.fromhex('e888670800')
    }
}

# Hold obstruction-steering randomness, never position. Each axis has its own cell.
AVOIDANCE_CODE = 0x1e29000
AVOIDANCE_STATE = 0x1e2a000
AVOIDANCE_TABLE = 0x1e2b000
AVOIDANCE_STRIDE = 16
AVOIDANCE_TABLE_SIZE = 960
AVOIDANCE_SITES = (
    0x24ed10,
    0x24ed48,
)


def avoidance_bodies():
    pieces = []

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        pieces.append((a, b))

    for axis, site in enumerate(AVOIDANCE_SITES):
        # One 8-byte cell per axis: game-clock anchor, uint16 roll, uint16 owner.
        entry = AVOIDANCE_CODE + axis * 0x100
        emit(
            entry, (
                f"pushfd;"
                f"pushad;"
                f"inc dword ptr [{AVOIDANCE_STATE}];"
                f"mov eax,esi;"
                f"sub eax,0x3832f0;"
                f"\n  xor edx,edx;"
                f"mov ebx,334;"
                f"div ebx;"
                f"test edx,edx;"
                f"jnz invalid;"
                f"cmp eax,60;"
                f"jae invalid;"
                f"\n  shl eax,4;"
                f"lea edi,[eax+{AVOIDANCE_TABLE+axis*8}];"
                f"movzx esi,word ptr [esi+11];"
                f"test esi,esi;"
                f"jz invalid;"
                f"\n  cmp esi,300;"
                f"jae invalid;"
                f"jmp {AVOIDANCE_CODE+0x200};"
                f"\n  invalid:inc dword ptr [{AVOIDANCE_STATE+12}];"
                f"popad;"
                f"popfd;"
                f"jmp 0x2ddd70;"
            ), 0x100
        )
        pieces.append((site, asm(site, f'call {entry}')))
    emit(
        AVOIDANCE_CODE + 0x200, (
            f"mov ebp,[0x446ae8];"
            f"cmp [edi+6],si;"
            f"jne fresh;"
            f"\n mov eax,ebp;"
            f"sub eax,[edi];"
            f"js fresh;"
            f"cmp eax,50;"
            f"jb cached;"
            f"\n cmp eax,250;"
            f"ja fresh;"
            f"xor edx,edx;"
            f"mov ebx,50;"
            f"div ebx;"
            f"sub ebp,edx;"
            f"\n fresh:mov [edi],ebp;"
            f"mov [edi+6],si;"
            f"\n mov eax,0x3596e0;"
            f"xor edx,edx;"
            f"mov ebx,0x7fff;"
            f"call 0x2ddd70;"
            f"\n mov [edi+4],ax;"
            f"inc dword ptr [{AVOIDANCE_STATE+4}];"
            f"jmp result;"
            f"\n cached:movzx eax,word ptr [edi+4];"
            f"inc dword ptr [{AVOIDANCE_STATE+8}];"
            f"\n result:mov [esp+28],eax;"
            f"mov [esp+20],eax;"
            f"popad;"
            f"popfd;"
            f"ret;"
        ), 0x200
    )
    emit(
        AVOIDANCE_CODE + 0x400, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{AVOIDANCE_TABLE};"
            f"xor eax,eax;"
            f"mov ecx,{AVOIDANCE_TABLE_SIZE//4};"
            f"rep stosd;"
            f"\n popad;"
            f"popfd;"
            f"jmp {PERCEPTION_CODE+0x400};"
        ), 0x100
    )
    pieces.append((AVOIDANCE_CODE + 0x500, avoidance_slot_reset_body()))
    for site, entry in ((0x249b2c, AVOIDANCE_CODE + 0x400), (0x24b52d, AVOIDANCE_CODE + 0x500)):
        pieces.append(
            (site, asm(site, f'jmp {entry}') + b'\x90' * (len(AVOIDANCE_SHARED[site]) - 5))
        )
    pieces.extend(((AVOIDANCE_STATE, bytes(64)), (AVOIDANCE_TABLE, bytes(AVOIDANCE_TABLE_SIZE))))
    return pieces


AVOIDANCE_SHARED = {a: b for a, b in perception_bodies() if a in (0x249b2c, 0x24b52d)}
AVOIDANCE_HOOKS = {
    **AVOIDANCE_SHARED,
    **{
        0x24ed10: bytes.fromhex('e85bf00800'),
        0x24ed48: bytes.fromhex('e823f00800')
    }
}

# Nozzle velocity uses the same actual 50-ms step as aircraft movement.
# Intermediate rendered frames keep the last pose, avoiding alternating false speeds.
NOZZLES_CODE = 0x1e2c000
NOZZLES_STATE = 0x1e2d000
NOZZLES_MAIN = 0x283ef2
NOZZLES_ENGINE = 0x28605c
NOZZLES_TRAMP = 0x1e2c400


def nozzles_bodies():
    pieces = []

    def emit(a, s, n):
        b = asm(a, s)
        assert len(b) <= n, (hex(a), len(b))
        pieces.append((a, b))

    emit(
        NOZZLES_CODE, (
            f"push eax;"
            f"call {NOZZLES_TRAMP};"
            f"pushfd;"
            f"pushad;"
            f"call {NOZZLES_CODE+0x200};"
            f"\n test eax,eax;"
            f"jz done;"
            f"cmp eax,[esp+36];"
            f"jne done;"
            f"\n mov eax,50;"
            f"call {NOZZLES_ENGINE};"
            f"inc dword ptr [{NOZZLES_STATE}];"
            f"\n done:popad;"
            f"popfd;"
            f"lea esp,[esp+4];"
            f"ret;"
        ), 0x100
    )
    emit(
        NOZZLES_CODE + 0x100, (
            f"pushfd;"
            f"pushad;"
            f"call {NOZZLES_CODE+0x200};"
            f"test eax,eax;"
            f"jz original;"
            f"\n inc dword ptr [{NOZZLES_STATE+4}];"
            f"popad;"
            f"popfd;"
            f"ret;"
            f"\n original:inc dword ptr [{NOZZLES_STATE+8}];"
            f"popad;"
            f"popfd;"
            f"jmp {NOZZLES_ENGINE};"
        ), 0x100
    )
    # Return the current pickup aircraft's record only when its aircraft clock owns it.
    emit(
        NOZZLES_CODE + 0x200, (
            f"movzx ebx,word ptr [0x397a8a];"
            f"test ebx,ebx;"
            f"jz invalid;"
            f"\n cmp ebx,300;"
            f"jae invalid;"
            f"imul edi,ebx,37;"
            f"add edi,0x3c3240;"
            f"\n cmp byte ptr [edi],0;"
            f"je invalid;"
            f"cmp byte ptr [edi+1],3;"
            f"jne invalid;"
            f"\n movzx ecx,byte ptr [edi+2];"
            f"cmp ecx,7;"
            f"jb invalid;"
            f"cmp ecx,14;"
            f"ja invalid;"
            f"\n movzx edx,word ptr [edi+3];"
            f"cmp edx,40;"
            f"jae invalid;"
            f"imul eax,edx,335;"
            f"add eax,0x39e590;"
            f"\n cmp [eax],bx;"
            f"jne invalid;"
            f"shl edx,5;"
            f"add edx,{AIRCRAFT_TABLE};"
            f"cmp dword ptr [edx],1;"
            f"jne invalid;"
            f"\n shl ecx,16;"
            f"or ecx,ebx;"
            f"cmp [edx+4],ecx;"
            f"jne invalid;"
            f"ret;"
            f"\n invalid:xor eax,eax;"
            f"ret;"
        ), 0x200
    )
    pieces.append((NOZZLES_TRAMP, AIRCRAFT_OLD + asm(NOZZLES_TRAMP + 5, f'jmp {AIRCRAFT_SITE+5}')))
    pieces.append(
        (
            AIRCRAFT_ORIGINAL, asm(AIRCRAFT_ORIGINAL, f'jmp {NOZZLES_CODE}') + b'\x90' *
            (len(NOZZLES_SHARED[AIRCRAFT_ORIGINAL]) - 5)
        )
    )
    pieces.append((NOZZLES_MAIN, asm(NOZZLES_MAIN, f'call {NOZZLES_CODE+0x100}')))
    pieces.append((NOZZLES_STATE, bytes(64)))
    return pieces


NOZZLES_SHARED = {AIRCRAFT_ORIGINAL: dict(aircraft_bodies())[AIRCRAFT_ORIGINAL]}
NOZZLES_HOOKS = {**NOZZLES_SHARED, **{0x283ef2: bytes.fromhex('e865210000')}}

# Only idle-facing choices/slew are clocked; moving and reset paths clear their rows.
IDLE_CODE = 0x1e2e000
IDLE_STATE = 0x1e2f000
IDLE_TABLE = 0x1e2f100
IDLE_TABLE_SIZE = 1024
IDLE_SITE = 0x280c47
IDLE_MOVING = 0x280ce9
IDLE_RESET = 0x27ee34
IDLE_FULL = 0x249b2c


def idle_bodies():
    p = []

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        p.append((a, b))

    # EBP is the original live pose. Lookup returns EDI=clock row, ESI=owner
    # identity, or EDI=0. Caller registers/flags survive all helper bookkeeping.
    emit(
        IDLE_CODE, (
            f"pushfd;"
            f"pushad;"
            f"inc dword ptr [{IDLE_STATE}];"
            f"mov eax,ebp;"
            f"\n call {IDLE_CODE+0x400};"
            f"test edi,edi;"
            f"jz invalid;"
            f"\n mov ebx,[0x446ae8];"
            f"cmp dword ptr [edi+12],1;"
            f"jne fresh;"
            f"\n cmp [edi],esi;"
            f"jne fresh;"
            f"mov eax,ebx;"
            f"sub eax,[edi+4];"
            f"js fresh;"
            f"\n cmp eax,250;"
            f"jbe elapsed;"
            f"mov dword ptr [edi+8],0;"
            f"mov eax,50;"
            f"jmp elapsed;"
            f"\n fresh:mov [edi],esi;"
            f"mov dword ptr [edi+12],1;"
            f"mov dword ptr [edi+8],0;"
            f"\n mov eax,[0x3924e0];"
            f"test eax,eax;"
            f"jle zero;"
            f"cmp eax,3277;"
            f"jae fifty;"
            f"\n imul eax,eax,1000;"
            f"add eax,32768;"
            f"shr eax,16;"
            f"jmp elapsed;"
            f"\n fifty:mov eax,50;"
            f"jmp elapsed;"
            f"zero:xor eax,eax;"
            f"\n elapsed:mov [edi+4],ebx;"
            f"add eax,[edi+8];"
            f"cmp eax,50;"
            f"jb hold;"
            f"\n xor edx,edx;"
            f"mov ecx,50;"
            f"div ecx;"
            f"mov [edi+8],edx;"
            f"\n inc dword ptr [{IDLE_STATE+4}];"
            f"popad;"
            f"popfd;"
            f"mov eax,0x3596e0;"
            f"jmp {IDLE_SITE+5};"
            f"\n hold:mov [edi+8],eax;"
            f"inc dword ptr [{IDLE_STATE+8}];"
            f"popad;"
            f"popfd;"
            f"\n mov ax,[ebp+0x227];"
            f"mov [0x3924f8],ax;"
            f"mov dword ptr [ebp+0x229],0;"
            f"jmp 0x280d0b;"
            f"\n invalid:inc dword ptr [{IDLE_STATE+12}];"
            f"popad;"
            f"popfd;"
            f"mov eax,0x3596e0;"
            f"jmp {IDLE_SITE+5};"
        ), 0x400
    )
    emit(
        IDLE_CODE + 0x400, (
            f"sub eax,0x3a56e6;"
            f"xor edx,edx;"
            f"mov ecx,0x582;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz bad;"
            f"cmp eax,64;"
            f"jae bad;"
            f"mov ebx,eax;"
            f"\n imul edx,eax,0x582;"
            f"add edx,0x3a56e6;"
            f"movzx esi,word ptr [edx+0x21b];"
            f"\n test esi,esi;"
            f"jz bad;"
            f"cmp esi,300;"
            f"jae bad;"
            f"imul ecx,esi,37;"
            f"add ecx,0x3c3240;"
            f"\n cmp byte ptr [ecx],0;"
            f"je bad;"
            f"cmp byte ptr [ecx+1],1;"
            f"jne bad;"
            f"\n cmp [ecx+3],bx;"
            f"jne bad;"
            f"movzx eax,byte ptr [ecx+2];"
            f"shl eax,16;"
            f"or esi,eax;"
            f"\n shl ebx,4;"
            f"lea edi,[ebx+{IDLE_TABLE}];"
            f"ret;"
            f"bad:xor edi,edi;"
            f"ret;"
        ), 0x200
    )
    # Clear a row by pose pointer. Validate before touching the reservation.
    emit(
        IDLE_CODE + 0x600, (
            f"call {IDLE_CODE+0x400};"
            f"test edi,edi;"
            f"jz done;"
            f"\n mov dword ptr [edi],0;"
            f"mov dword ptr [edi+4],0;"
            f"\n mov dword ptr [edi+8],0;"
            f"mov dword ptr [edi+12],0;"
            f"\n inc dword ptr [{IDLE_STATE+16}];"
            f"done:ret;"
        ), 0x100
    )
    emit(
        IDLE_CODE + 0x700, (
            f"pushfd;"
            f"pushad;"
            f"mov eax,ebp;"
            f"call {IDLE_CODE+0x600};"
            f"popad;"
            f"popfd;"
            f"\n mov ax,[0x3924f8];"
            f"jmp {IDLE_MOVING+6};"
        ), 0x100
    )
    # Reset is also called by original physical creation and off-screen reset.
    emit(
        IDLE_CODE + 0x800, (
            f"pushfd;"
            f"pushad;"
            f"movzx eax,ax;"
            f"cmp eax,300;"
            f"jae done;"
            f"\n imul eax,eax,37;"
            f"movzx eax,word ptr [eax+0x3c3243];"
            f"cmp eax,64;"
            f"jae done;"
            f"\n shl eax,4;"
            f"add eax,{IDLE_TABLE};"
            f"mov dword ptr [eax],0;"
            f"mov dword ptr [eax+4],0;"
            f"\n mov dword ptr [eax+8],0;"
            f"mov dword ptr [eax+12],0;"
            f"inc dword ptr [{IDLE_STATE+20}];"
            f"\n done:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp {IDLE_RESET+5};"
        ), 0x100
    )
    p.append((IDLE_CODE + 0x900, idle_mission_reset_body()))
    p.extend(
        [
            (IDLE_SITE, asm(IDLE_SITE, f'jmp {IDLE_CODE}')),
            (IDLE_MOVING, asm(IDLE_MOVING, f'jmp {IDLE_CODE+0x700}') + b'\x90'),
            (IDLE_RESET, asm(IDLE_RESET, f'jmp {IDLE_CODE+0x800}')),
            (
                IDLE_FULL, asm(IDLE_FULL, f'jmp {IDLE_CODE+0x900}') + b'\x90' *
                (len(IDLE_SHARED[IDLE_FULL]) - 5)
            ), (IDLE_STATE, bytes(64)), (IDLE_TABLE, bytes(IDLE_TABLE_SIZE))
        ]
    )
    return p


IDLE_SHARED = {IDLE_FULL: dict(avoidance_bodies())[IDLE_FULL]}
IDLE_HOOKS = {
    **IDLE_SHARED,
    **{
        0x280c47: bytes.fromhex('b8e0963500'),
        0x280ce9: bytes.fromhex('66a1f8243900'),
        0x27ee34: bytes.fromhex('5351525657')
    }
}

# Upper-body slew/damping use elapsed time and match the original at 50 ms.
POSE_CODE = 0x1e5e000
POSE_END = 0x1e5f000
POSE_COEFFICIENTS = 0x1e5e800
POSE_PITCH = 0x281219
POSE_DAMP = 0x280e6e


def pose_bodies():
    p = []

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap
        p.append((a, b))

    # Keep the original requested signed angle delta in EAX. Only EDX changes.
    emit(
        POSE_CODE, (
            f"pushfd;"
            f"pushad;"
            f"mov ebx,eax;"
            f"mov eax,[0x3924e0];"
            f"\n test eax,eax;"
            f"jle zero;"
            f"cmp eax,6554;"
            f"jbe bounded;"
            f"mov eax,6554;"
            f"\n bounded:imul eax,eax,16380;"
            f"add eax,32768;"
            f"shr eax,16;"
            f"jmp limit;"
            f"\n zero:xor eax,eax;"
            f"limit:cmp ebx,eax;"
            f"jle low;"
            f"mov ebx,eax;"
            f"jmp done;"
            f"\n low:neg eax;"
            f"cmp ebx,eax;"
            f"jge done;"
            f"mov ebx,eax;"
            f"\n done:mov [esp+20],ebx;"
            f"popad;"
            f"popfd;"
            f"jmp 0x281235;"
        ), 0x100
    )
    # ceil(v * (7/8) ** (dt_ms/50)), matching v-(v>>3) at 50 ms.
    # Return the removed amount in EAX and original velocity in EDX so the
    # unmodified store/subtract/store sequence at 280e75 retains its contract.
    emit(
        POSE_CODE + 0x100, (
            f"pushfd;"
            f"pushad;"
            f"mov eax,[0x3924e0];"
            f"test eax,eax;"
            f"jle unchanged;"
            f"\n cmp eax,6554;"
            f"jbe bounded;"
            f"mov eax,6554;"
            f"\n bounded:imul eax,eax,1000;"
            f"add eax,32768;"
            f"shr eax,16;"
            f"test eax,eax;"
            f"jz unchanged;"
            f"\n mov ecx,[eax*4+{POSE_COEFFICIENTS}];"
            f"mov eax,edi;"
            f"imul ecx;"
            f"\n mov ebx,eax;"
            f"and ebx,0x7fffffff;"
            f"shrd eax,edx,31;"
            f"\n test ebx,ebx;"
            f"jz rounded;"
            f"inc eax;"
            f"\n rounded:mov edx,edi;"
            f"sub edx,eax;"
            f"mov [esp+28],edx;"
            f"mov [esp+20],edi;"
            f"\n popad;"
            f"popfd;"
            f"jmp 0x280e75;"
            f"\n unchanged:mov dword ptr [esp+28],0;"
            f"mov [esp+20],edi;"
            f"popad;"
            f"popfd;"
            f"jmp 0x280e75;"
        ), 0x200
    )
    coeff = [round((7 / 8)**(i / 50) * (1 << 31)) for i in range(101)]
    assert coeff[50] == 7 * (1 << 28)
    p.extend(
        [
            (POSE_COEFFICIENTS, struct.pack('<101I', *coeff)),
            (POSE_PITCH, asm(POSE_PITCH, f'jmp {POSE_CODE}') + b'\x90\x90'),
            (POSE_DAMP, asm(POSE_DAMP, f'jmp {POSE_CODE+0x100}') + b'\x90\x90')
        ]
    )
    return p


POSE_HOOKS = {0x281219: bytes.fromhex('89c23d33030000'), 0x280e6e: bytes.fromhex('89f889fac1f803')}
POSE_SHARED = {}

_GENERATORS = dict(
    drone=drone_bodies,
    aircraft=aircraft_bodies,
    gates=gates_bodies,
    perception=perception_bodies,
    avoidance=avoidance_bodies,
    nozzles=nozzles_bodies,
    idle=idle_bodies,
    pose=pose_bodies
)
_HOOKS = dict(
    drone=DRONE_HOOKS,
    aircraft=AIRCRAFT_HOOKS,
    gates=GATES_HOOKS,
    perception=PERCEPTION_HOOKS,
    avoidance=AVOIDANCE_HOOKS,
    nozzles=NOZZLES_HOOKS,
    idle=IDLE_HOOKS,
    pose=POSE_HOOKS
)
_SHARED = dict(
    drone=DRONE_SHARED,
    aircraft=AIRCRAFT_SHARED,
    gates=GATES_SHARED,
    perception=PERCEPTION_SHARED,
    avoidance=AVOIDANCE_SHARED,
    nozzles=NOZZLES_SHARED,
    idle=IDLE_SHARED,
    pose=POSE_SHARED
)
_STATE = dict(
    drone=((DRONE_STATE, DRONE_LIMIT - DRONE_STATE), ),
    aircraft=((AIRCRAFT_TABLE, AIRCRAFT_LIMIT - AIRCRAFT_TABLE), ),
    gates=((GATES_STATE, 0x1000), (GATES_TABLE, GATES_TABLE_SIZE)),
    perception=((PERCEPTION_STATE, 64), (PERCEPTION_TABLE, PERCEPTION_TABLE_SIZE)),
    avoidance=((AVOIDANCE_STATE, 64), (AVOIDANCE_TABLE, AVOIDANCE_TABLE_SIZE)),
    nozzles=((NOZZLES_STATE, 64), ),
    idle=((IDLE_STATE, 64), (IDLE_TABLE, IDLE_TABLE_SIZE)),
    pose=()
)


def part_bodies(part, *, retry_range=63):
    if part not in _GENERATORS:
        raise ValueError('Unknown actor timing component: ' + str(part))
    pieces = _GENERATORS[part](retry_range=retry_range) if part == 'gates' else _GENERATORS[part]()
    if part in ('drone', 'aircraft'):
        pieces = pieces + [(a, bytes(n)) for a, n in _STATE[part]]
    return pieces


def verify(read, *, part, retry_range=63):
    from features.input_views import _verify
    state = {a for a, n in _STATE[part]}
    return _verify(
        [(a, b) for a, b in part_bodies(part, retry_range=retry_range) if a not in state], read
    )


def install(write, read, *, part, retry_range=63):
    """Validate before writes; repeated installation preserves live clocks.

    Shared reset entries may be temporarily restored by a private checkpoint
    migration. Only those entries are repaired; timing rows are never reset.
    """
    from features.input_views import _install
    pieces = part_bodies(part, retry_range=retry_range)
    state = {a for a, n in _STATE[part]}
    shared = _SHARED[part]
    code = [(a, b) for a, b in pieces if a not in state]
    if all(bytes(read(a, len(b))) == b for a, b in code):
        return dict(already_installed=True, ranges=[])
    if shared and all(bytes(read(a, len(b))) in (b, shared.get(a, b)) for a, b in code):
        repair = [(a, b) for a, b in pieces if a in shared]
        for a, b in repair:
            write(a, b)
        return dict(ranges=[(a, a + len(b)) for a, b in repair])
    return _install(pieces, _HOOKS[part], write, read)


def predecessor_view(ram, *, part, retry_range=63):
    """Private oracle rollback of shared entries, without touching live rows."""
    verify(lambda a, n: ram[a:a + n], part=part, retry_range=retry_range)
    out = bytearray(ram)
    for a, b in _SHARED[part].items():
        out[a:a + len(b)] = b
    return out


# Repair impossible PBA leg poses before exposing their armor sprites.
POSE_GUARD_CODE = 0x1fc9000

POSE_GUARD_STATE = POSE_GUARD_CODE + 0x400

POSE_GUARD_SITE = 0x29c508

POSE_GUARD_ORIGINAL = bytes.fromhex('5351565755')


def pose_guard_bodies():
    # Original per-suit pose preparation receives suit slot EAX and detail EDX.
    # Four times the model's complete leg length is deliberately permissive:
    # the captured defect is hundreds of metres, not ordinary gait separation.
    s = (
        f"pushfd;"
        f"pushad;"
        f"movsx esi,ax;"
        f"cmp esi,60;"
        f"jae done;"
        f"\n imul esi,esi,0x582;"
        f"add esi,0x3a5608;"
        f"movsx eax,word ptr [esi];"
        f"and eax,0x7fff;"
        f"\n test eax,eax;"
        f"jz done;"
        f"cmp eax,300;"
        f"jae done;"
        f"mov ebp,eax;"
        f"imul ebx,eax,37;"
        f"\n cmp byte ptr [ebx+0x3c3240],0;"
        f"je done;"
        f"cmp byte ptr [ebx+0x3c3241],1;"
        f"jne done;"
        f"\n lea edi,[esi+0xde];"
        f"cmp byte ptr [edi+4],3;"
        f"je done;"
        f"cmp dword ptr [edi],11;"
        f"jae done;"
        f"\n mov ecx,[edi+0x2fe];"
        f"test ecx,ecx;"
        f"jle done;"
        f"cmp ecx,0x10000;"
        f"ja done;"
        f"shl ecx,2;"
        f"\n lea ebx,[edi+0xd1];"
        f"xor edx,edx;"
        f"\n axis:mov eax,[ebx+edx];"
        f"sub eax,[ebx+edx+72];"
        f"jo repair;"
        f"\n cmp eax,ecx;"
        f"jg repair;"
        f"neg eax;"
        f"cmp eax,ecx;"
        f"jg repair;"
        f"\n mov eax,[ebx+edx+12];"
        f"sub eax,[ebx+edx+84];"
        f"jo repair;"
        f"\n cmp eax,ecx;"
        f"jg repair;"
        f"neg eax;"
        f"cmp eax,ecx;"
        f"jg repair;"
        f"\n mov eax,[ebx+edx+24];"
        f"sub eax,[ebx+edx+72];"
        f"jo repair;"
        f"\n cmp eax,ecx;"
        f"jg repair;"
        f"neg eax;"
        f"cmp eax,ecx;"
        f"jg repair;"
        f"\n mov eax,[ebx+edx+36];"
        f"sub eax,[ebx+edx+84];"
        f"jo repair;"
        f"\n cmp eax,ecx;"
        f"jg repair;"
        f"neg eax;"
        f"cmp eax,ecx;"
        f"jg repair;"
        f"\n add edx,4;"
        f"cmp edx,12;"
        f"jb axis;"
        f"jmp done;"
        f"\n repair:mov eax,ebp;"
        f"call 0x27ee34;"
        f"inc dword ptr [{POSE_GUARD_STATE}];"
        f"mov [{POSE_GUARD_STATE+4}],ebp;"
        f"\n done:popad;"
        f"popfd;"
        f"push ebx;"
        f"push ecx;"
        f"push esi;"
        f"push edi;"
        f"push ebp;"
        f"jmp {POSE_GUARD_SITE+5};"
    )
    b = asm(POSE_GUARD_CODE, s)
    assert len(b) < 0x400
    return [(POSE_GUARD_CODE, b), (POSE_GUARD_SITE, asm(POSE_GUARD_SITE, f'jmp {POSE_GUARD_CODE}'))]


def pose_guard_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        pose_guard_bodies(), {POSE_GUARD_SITE: POSE_GUARD_ORIGINAL},
        write,
        read,
        cold_state=((POSE_GUARD_CODE, 0x408), )
    )


def pose_guard_verify(read):
    from features.input_views import _verify
    return _verify(pose_guard_bodies(), read)


JET_RETRY = 0x1d2e600

JET_AIR = 0x1d2e500


def jet_setup(write, asm, r):
    assert r[0x288f53:0x288f60] == bytes.fromhex('668b1a4366891a6683fb027211')
    assert struct.unpack_from('<I', r, 0x288ee4)[0] == 0x288f1f
    write(
        JET_RETRY,
        asm(
            JET_RETRY, (
                "add bx,word ptr [edx];"
                "mov word ptr [edx],bx;"
                "cmp bx,100;"
                "jb 0x288f71;"
                "jmp 0x288f60;"
            )
        )
    )
    write(0x288f53, asm(0x288f53, f'jmp {JET_RETRY}'))
    # Phase 2 also enters 0x288F23: redirect only the phase-1 table slot.
    write(0x288ee4, struct.pack('<I', JET_AIR))
    write(
        JET_AIR,
        asm(
            JET_AIR, (
                "mov byte ptr [edx+3],2;"
                "mov word ptr [edx],0;"
                "mov di,word ptr [edx];"
                "jmp 0x288f26;"
            )
        )
    )


PROTECTION_CODE = 0x1dc0000

PROTECTION_RESET = PROTECTION_CODE + 0x400

PROTECTION_ALLOC = PROTECTION_CODE + 0x500

PROTECTION_STATE = 0x1dc1000

PROTECTION_TABLE = 0x1dc2000

PROTECTION_COUNT = 60

PROTECTION_STRIDE = 32

PROTECTION_HOOKS = {
    0x289fff: bytes.fromhex('b9e8030000'),
    0x2953f0: bytes.fromhex('5351525657'),
    0x296a84: bytes.fromhex('5351525625ff000000')
}


def protection_setup(write, asm, r):
    for a, b in PROTECTION_HOOKS.items():
        assert r[a:a + len(b)] == b, (hex(a), r[a:a + len(b)].hex())
    # EBP points to suit+6; EDI is the original elapsed-time argument. Keep all
    # eligibility checks before the old loop. Per-section remainders are base 1000.
    body = (
        f"pushfd;"
        f"pushad;"
        f"\n mov eax,ebp;"
        f"sub eax,0x3a560e;"
        f"xor edx,edx;"
        f"mov ecx,0x582;"
        f"div ecx;"
        f"\n test edx,edx;"
        f"jnz invalid;"
        f"cmp eax,{PROTECTION_COUNT};"
        f"jae invalid;"
        f"\n shl eax,5;"
        f"lea esi,[eax+{PROTECTION_TABLE}];"
        f"\n movzx eax,word ptr [ebp-6];"
        f"and eax,0x7fff;"
        f"\n cmp [esi+16],eax;"
        f"jne fresh;"
        f"\n mov ecx,[0x446ae8];"
        f"cmp ecx,[esi+20];"
        f"jb fresh;"
        f"\n jmp owned;"
        f"\n fresh:mov [esi+16],eax;"
        f"mov dword ptr [esi],0;"
        f"mov dword ptr [esi+4],0;"
        f"\n mov dword ptr [esi+8],0;"
        f"mov dword ptr [esi+12],0;"
        f"\n owned:mov ecx,[0x446ae8];"
        f"mov [esi+20],ecx;"
        f"\n imul eax,eax,37;"
        f"movzx eax,byte ptr [eax+0x3c3242];"
        f"\n imul eax,eax,70;"
        f"movzx ecx,byte ptr [eax+0x395bdc];"
        f"\n test edi,edi;"
        f"jle finish;"
        f"\n cmp edi,1000;"
        f"jbe dt_ok;"
        f"inc dword ptr [{PROTECTION_STATE+12}];"
        f"\n dt_ok:mov eax,ecx;"
        f"mul edi;"
        f"mov ebx,eax;"
        f"\n xor ecx,ecx;"
        f"\n section:movsx eax,word ptr [ebp+15];"
        f"movsx edx,word ptr [ebp+19];"
        f"\n cmp eax,edx;"
        f"jge capped;"
        f"\n mov eax,ebx;"
        f"add eax,[esi+ecx*4];"
        f"xor edx,edx;"
        f"push ecx;"
        f"mov ecx,1000;"
        f"div ecx;"
        f"pop ecx;"
        f"\n mov [esi+ecx*4],edx;"
        f"movsx edx,word ptr [ebp+15];"
        f"add eax,edx;"
        f"\n movsx edx,word ptr [ebp+19];"
        f"cmp eax,edx;"
        f"jge capped;"
        f"\n mov word ptr [ebp+15],ax;"
        f"jmp next;"
        f"\n capped:mov word ptr [ebp+15],dx;"
        f"mov dword ptr [esi+ecx*4],0;"
        f"\n next:add ebp,7;"
        f"inc ecx;"
        f"cmp ecx,4;"
        f"jb section;"
        f"\n finish:inc dword ptr [{PROTECTION_STATE}];"
        f"popad;"
        f"popfd;"
        f"add ebp,28;"
        f"jmp 0x28a052;"
        f"\n invalid:inc dword ptr [{PROTECTION_STATE+4}];"
        f"popad;"
        f"popfd;"
        f"mov ecx,1000;"
        f"jmp 0x28a004;"
    )
    b = asm(PROTECTION_CODE, body)
    assert len(b) < 0x400
    write(PROTECTION_CODE, b)
    # Reset before original object-system initialization, reached by mission
    # cleanup/loading. Never add fields to the original save data.
    b = asm(
        PROTECTION_RESET, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"xor eax,eax;"
            f"mov edi,{PROTECTION_TABLE};"
            f"mov ecx,{PROTECTION_COUNT*PROTECTION_STRIDE//4};"
            f"rep stosd;"
            f"\n inc dword ptr [{PROTECTION_STATE+8}];"
            f"popad;"
            f"popfd;"
            f"\n push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x2953f5;"
        )
    )
    assert len(b) < 0x100
    write(PROTECTION_RESET, b)
    # Wrap the complete class allocator, retaining its input class on our stack.
    # It returns zero on failure and the allocated class slot otherwise.
    b = asm(
        PROTECTION_ALLOC, (
            f"push eax;"
            f"call {PROTECTION_ALLOC+0x80};"
            f"pushfd;"
            f"pushad;"
            f"\n cmp byte ptr [esp+36],1;"
            f"jne done;"
            f"movzx eax,ax;"
            f"test eax,eax;"
            f"jz done;"
            f"cmp eax,{PROTECTION_COUNT};"
            f"jae done;"
            f"\n shl eax,5;"
            f"lea edi,[eax+{PROTECTION_TABLE}];"
            f"xor eax,eax;"
            f"mov ecx,8;"
            f"cld;"
            f"rep stosd;"
            f"\n inc dword ptr [{PROTECTION_STATE+16}];"
            f"\n done:popad;"
            f"popfd;"
            f"lea esp,[esp+4];"
            f"ret;"
        )
    )
    assert len(b) < 0x80
    write(PROTECTION_ALLOC, b)
    write(
        PROTECTION_ALLOC + 0x80,
        asm(
            PROTECTION_ALLOC + 0x80,
            ("push ebx;"
             "push ecx;"
             "push edx;"
             "push esi;"
             "and eax,0xff;"
             "jmp 0x296a8d;")
        )
    )
    for a, dest in [
        (0x289fff, PROTECTION_CODE), (0x2953f0, PROTECTION_RESET), (0x296a84, PROTECTION_ALLOC)
    ]:
        write(a, asm(a, f'jmp {dest}') + b'\x90' * (len(PROTECTION_HOOKS[a]) - 5))


VEHICLE_PROTECTION_CODE = 0x1de2000

VEHICLE_PROTECTION_RESET = VEHICLE_PROTECTION_CODE + 0x400

VEHICLE_PROTECTION_ALLOC = VEHICLE_PROTECTION_CODE + 0x500

VEHICLE_PROTECTION_STATE = 0x1de3000

VEHICLE_PROTECTION_TABLE = 0x1de4000

VEHICLE_PROTECTION_COUNT = 52

VEHICLE_PROTECTION_STRIDE = 16


def vehicle_protection_jump(a, b):
    return b'\xe9' + struct.pack('<i', b - a - 5)


VEHICLE_PROTECTION_HOOKS = {
    0x28e997: bytes.fromhex('bbe8030000'),
    0x2953f0: vehicle_protection_jump(0x2953f0, 0x1dc9600),
    0x296a84: vehicle_protection_jump(0x296a84, 0x1dc0500)
}


def vehicle_protection_setup(write, asm, r):
    for a, b in VEHICLE_PROTECTION_HOOKS.items():
        assert bytes(r[a:a + len(b)]) == b, (hex(a), bytes(r[a:a + len(b)]).hex())
    # EAX contains the original rate*elapsed product. Increase that numerator by
    # the saved fraction; the original division, clamp and return registers follow.
    body = (
        f"pushfd;"
        f"pushad;"
        f"mov eax,ecx;"
        f"sub eax,0x3a19e8;"
        f"xor edx,edx;"
        f"mov ebx,296;"
        f"div ebx;"
        f"\n test edx,edx;"
        f"jnz invalid;"
        f"test eax,eax;"
        f"jz invalid;"
        f"cmp eax,{VEHICLE_PROTECTION_COUNT};"
        f"jae invalid;"
        f"\n shl eax,4;"
        f"lea ebp,[eax+{VEHICLE_PROTECTION_TABLE}];"
        f"movzx eax,word ptr [ecx];"
        f"and eax,0x7fff;"
        f"\n cmp [ebp+4],eax;"
        f"jne fresh;"
        f"mov edx,[0x446ae8];"
        f"cmp edx,[ebp+8];"
        f"jb fresh;"
        f"jmp owned;"
        f"\n fresh:mov [ebp+4],eax;"
        f"mov dword ptr [ebp],0;"
        f"\n owned:mov edx,[0x446ae8];"
        f"mov [ebp+8],edx;"
        f"test esi,esi;"
        f"jg positive;"
        f"\n mov dword ptr [esp+28],0;"
        f"jmp finish;"
        f"\n positive:movsx ebx,word ptr [ecx+6];"
        f"movsx edi,word ptr [ecx+10];"
        f"sub edi,ebx;"
        f"jle capped;"
        f"\n mov eax,[esp+28];"
        f"add eax,[ebp];"
        f"mov [esp+28],eax;"
        f"xor edx,edx;"
        f"mov ebx,1000;"
        f"div ebx;"
        f"\n cmp eax,edi;"
        f"jae capped;"
        f"mov [ebp],edx;"
        f"jmp finish;"
        f"\n capped:mov dword ptr [ebp],0;"
        f"\n finish:inc dword ptr [{VEHICLE_PROTECTION_STATE}];"
        f"popad;"
        f"popfd;"
        f"mov ebx,1000;"
        f"jmp 0x28e99c;"
        f"\n invalid:inc dword ptr [{VEHICLE_PROTECTION_STATE+4}];"
        f"popad;"
        f"popfd;"
        f"mov ebx,1000;"
        f"jmp 0x28e99c;"
    )
    b = asm(VEHICLE_PROTECTION_CODE, body)
    assert len(b) < 0x400
    write(VEHICLE_PROTECTION_CODE, b)
    b = asm(
        VEHICLE_PROTECTION_RESET, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"xor eax,eax;"
            f"mov edi,{VEHICLE_PROTECTION_TABLE};"
            f"mov ecx,{VEHICLE_PROTECTION_COUNT*VEHICLE_PROTECTION_STRIDE//4};"
            f"rep stosd;"
            f"\n inc dword ptr [{VEHICLE_PROTECTION_STATE+8}];"
            f"popad;"
            f"popfd;"
            f"jmp 0x1dc9600;"
        )
    )
    assert len(b) < 0x100
    write(VEHICLE_PROTECTION_RESET, b)
    # Chain the existing suit allocator wrapper; only class 2 resets our table.
    b = asm(
        VEHICLE_PROTECTION_ALLOC, (
            f"push eax;"
            f"call 0x1dc0500;"
            f"pushfd;"
            f"pushad;"
            f"\n cmp byte ptr [esp+36],2;"
            f"jne done;"
            f"movzx eax,ax;"
            f"test eax,eax;"
            f"jz done;"
            f"cmp eax,{VEHICLE_PROTECTION_COUNT};"
            f"jae done;"
            f"\n shl eax,4;"
            f"lea edi,[eax+{VEHICLE_PROTECTION_TABLE}];"
            f"xor eax,eax;"
            f"mov ecx,4;"
            f"cld;"
            f"rep stosd;"
            f"inc dword ptr [{VEHICLE_PROTECTION_STATE+12}];"
            f"\n done:popad;"
            f"popfd;"
            f"lea esp,[esp+4];"
            f"ret;"
        )
    )
    assert len(b) < 0x100
    write(VEHICLE_PROTECTION_ALLOC, b)
    for a, dest in (
        (0x28e997, VEHICLE_PROTECTION_CODE), (0x2953f0, VEHICLE_PROTECTION_RESET),
        (0x296a84, VEHICLE_PROTECTION_ALLOC)
    ):
        write(a, asm(a, f'jmp {dest}'))
    write(VEHICLE_PROTECTION_STATE, bytes(0x1000))
    write(VEHICLE_PROTECTION_TABLE, bytes(0x1000))
