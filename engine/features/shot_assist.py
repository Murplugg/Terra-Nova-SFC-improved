"""Offer optional body-center assistance for unlocked player shots.

The original physics query returns an approximate body center on a sphere hit
(0x311742). The muzzle-to-reticle helper uses that endpoint, which can pull a
shot away from the visible aiming point. With assistance off, this wrapper
uses the body's ray-contact depth while preserving range and nearby cover
checks. Accurate mesh/terrain endpoints keep their existing depth. Explicit
target locks use their existing path.

The setting defaults on. Only the aiming query is wrapped; projectile collision
and AI physics retain their original callers. options_row supplies the checkbox
presentation, while this module owns the preference and query correction.
"""
from patch_support import asm
from features import options_row, prequel_help
from features import projectiles, target_picking
# Shared preferences expose fixed entry points for initialization and saving.
from features.option_contracts import (
    WRIST, AI, FPS, WRIST_DRAW, WRIST_EVENT, WRIST_ACCEPT, WRIST_CLOSE, AI_DRAW, SHARED_SAVE
)

WRIST_STATE = WRIST.state
WRIST_INIT = WRIST.init
AI_STATE = AI.state
AI_INIT = AI.init
PREQUEL_HELP_DRAW = prequel_help.DRAW
FPS_STATE = FPS.state
FPS_INIT = FPS.init

BASE = 0x1d34000
END = 0x1d36000
QUERY = BASE
INIT = BASE + 0x500
SAVE = BASE + 0x600
DRAW = options_row.DRAW
EVENT = options_row.EVENT
ACCEPT = options_row.ACCEPT
CLOSE = options_row.CLOSE
TEXT = options_row.TEXT
STATE = BASE + 0x1800
STATE_SIZE = 0x40
# initialized, enabled, pending, options-open, hover (1..4)


def query_site():
    code = dict(projectiles.reticle_bodies())[projectiles.RETICLE_CODE]
    sites = [
        projectiles.RETICLE_CODE + i for i in range(len(code) - 4)
        if code[i:i + 5] == asm(projectiles.RETICLE_CODE + i, 'call 0x2f074c')
    ]
    assert len(sites) == 1
    return sites[0]


def predecessors():
    return {
        target_picking.SITE: asm(target_picking.SITE, f'jmp {target_picking.IMPROVED_DISPATCH}') + b'\x90',
        query_site(): asm(query_site(), 'call 0x2f074c'),
        AI_DRAW: asm(AI_DRAW, f'call {PREQUEL_HELP_DRAW}'),
        0x2ca450: asm(0x2ca450, f'jmp {WRIST_EVENT}'),
        SHARED_SAVE: asm(SHARED_SAVE, f'call {WRIST_ACCEPT}'),
        0x2cbc08: asm(0x2cbc08, f'jmp {WRIST_CLOSE}')
    }


def bodies():
    labels, raw = options_row.strings()
    out = [(TEXT, raw)]

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b), cap)
        out.append((a, b))

    emit(
        INIT, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [{STATE}],1;"
            f"je done;"
            f"\n        call {AI_INIT};"
            f"cmp dword ptr [{AI_STATE}],1;"
            f"jne done;"
            f"\n        push {AI_STATE+64};"
            f"push 1;"
            f"push {labels['key']};"
            f"push {labels['section']};"
            f"\n        call dword ptr [{AI_STATE+16}];"
            f"and eax,1;"
            f"mov [{STATE+4}],eax;"
            f"\n        mov dword ptr [{STATE}],1;"
            f"done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )
    emit(
        SAVE, (
            f"pushfd;"
            f"pushad;"
            f"call {INIT};"
            f"cmp dword ptr [{STATE}],1;"
            f"jne done;"
            f"\n        mov eax,[{STATE+8}];"
            f"mov [{STATE+4}],eax;"
            f"mov edx,{labels['zero']};"
            f"test eax,eax;"
            f"jz value;"
            f"\n        mov edx,{labels['one']};"
            f"value:push {AI_STATE+64};"
            f"push edx;"
            f"push {labels['key']};"
            f"\n        push {labels['section']};"
            f"call dword ptr [{AI_STATE+20}];"
            f"done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )

    # Preserve all integer/vector state. The nested query's callee-pop ABI is
    # reproduced exactly; the muzzle-to-reticle helper consumes only its EAX result.
    s = (f"pushfd;"
         f"pushad;"
         f"sub esp,192;"
         f"mov edi,esp;"
         f"stmxcsr [edi+32];")
    for i in range(8):
        s += f'movdqu [edi+64+{i*16}],xmm{i};'
    s += 'mov [edi+24],eax;'
    for i in range(3):
        s += (
            f"mov ecx,[eax+{i*4}];"
            f"mov [edi+{i*4}],ecx;"
            f"mov ecx,[edx+{i*4}];"
            f"mov [edi+{12+i*4}],ecx;"
        )
    for offset in reversed(range(232, 260, 4)):
        s += f'push dword ptr [edi+{offset}];'
    s += (
        f"mov eax,[edi+220];"
        f"mov edx,[edi+212];"
        f"mov ebx,[edi+208];"
        f"mov ecx,[edi+216];"
        f"\n        call 0x2f074c;"
        f"mov [edi+220],eax;"
        f"test eax,eax;"
        f"jle done;"
        f"call {INIT};"
        f"\n        cmp dword ptr [{STATE}],1;"
        f"jne done;"
        f"cmp dword ptr [{STATE+4}],0;"
        f"jne done;"
        f"\n        mov esi,[edi+24];"
        f"mov dword ptr [edi+52],0;"
        f"mov eax,[edi+220];"
        f"cmp eax,96;"
        f"jae project;"
        f"mov edx,[eax*4+0x44b9e4];"
        f"cmp edx,96;"
        f"jae project;"
        f"cmp [edx*4+0x44bb64],eax;"
        f"jne project;"
        f"imul ebx,edx,160;"
        f"imul edx,edx,48;"
    )
    # The original sphere query returns centre - one ray step. Recognize that
    # exact output before replacing its depth: the supplemental leg and vehicle
    # queries already return actual contacts, even for the same physics ID.
    # All scratch values live in this call's stack frame; no new game state.
    for i in range(3):
        s += f'mov eax,[edx+0x44e0dd+{i*16}];'
        if i == 2:
            s += 'add eax,[ebx+0x44f388];'
        s += (
            f'mov [edi+{36+i*4}],eax;'
            f'sub eax,[0x44e0cc+{i*4}];'
            f'cmp eax,[esi+{i*4}];'
            'jne project;'
        )
    s += (
        'mov eax,[ebx+0x44f368];'
        'test eax,eax;'
        'jle project;'
        'mov [edi+48],eax;'
        'mov dword ptr [edi+52],1;'
        'lea esi,[edi+36];'
        'project:'
        f"xorpd xmm4,xmm4;"
        f"xorpd xmm5,xmm5;"
        f"xorpd xmm6,xmm6;"
    )
    # Work in doubles: raw world coordinates can exceed 2**24. A single-
    # precision reconstruction can move an endpoint visibly at close range.
    for i in range(3):
        s += (
            f"cvtsi2sd xmm0,dword ptr [esi+{i*4}];"
            f"cvtsi2sd xmm1,dword ptr [edi+{i*4}];"
            f"\n          subsd xmm0,xmm1;"
            f"movapd xmm3,xmm0;"
            f"mulsd xmm3,xmm3;"
            f"addsd xmm6,xmm3;"
            f"cvtsi2sd xmm2,dword ptr [edi+{12+i*4}];"
            f"mulsd xmm0,xmm2;"
            f"\n          addsd xmm4,xmm0;"
            f"mulsd xmm2,xmm2;"
            f"addsd xmm5,xmm2;"
        )
    s += (
        "xorpd xmm0,xmm0;"
        "ucomisd xmm5,xmm0;"
        "jbe done;"
        "movapd xmm3,xmm4;"
        "divsd xmm4,xmm5;"
        "cmp dword ptr [edi+52],0;"
        "je clamp_depth;"
    )
    # t_c = dot(B-C,D)/dot(D,D). Subtract the sphere's half-chord to
    # obtain the entry point. The original query also admits near misses within
    # its thickness; those use closest approach (zero half-chord), keeping the
    # crosshair ray unchanged. An origin inside the body uses its forward exit.
    s += (
        'mulsd xmm3,xmm4;'
        'subsd xmm6,xmm3;'
        'cvtsi2sd xmm1,dword ptr [edi+48];'
        'mulsd xmm1,xmm1;'
        'subsd xmm1,xmm6;'
        'maxsd xmm1,xmm0;'
        'divsd xmm1,xmm5;'
        'sqrtsd xmm1,xmm1;'
        'movapd xmm3,xmm4;'
        'subsd xmm4,xmm1;'
        'ucomisd xmm4,xmm0;'
        'jae clamp_depth;'
        'movapd xmm4,xmm3;'
        'addsd xmm4,xmm1;'
        'clamp_depth:'
        "\n        maxsd xmm4,xmm0;"
        "sqrtsd xmm5,xmm5;"
        "cvtsi2sd xmm0,dword ptr [edi+236];"
        "\n        divsd xmm0,xmm5;"
        "minsd xmm4,xmm0;"
        "mov esi,[edi+24];"
    )
    for i in range(3):
        s += (
            f"cvtsi2sd xmm0,dword ptr [edi+{12+i*4}];"
            f"mulsd xmm0,xmm4;"
            f"\n          cvtsi2sd xmm1,dword ptr [edi+{i*4}];"
            f"addsd xmm0,xmm1;"
            f"cvttsd2si eax,xmm0;"
            f"mov [esi+{i*4}],eax;"
        )
    s += 'done:ldmxcsr [edi+32];'
    for i in range(8):
        s += f'movdqu xmm{i},[edi+64+{i*16}];'
    s += ("add esp,192;"
          "popad;"
          "popfd;"
          "ret 28;")
    emit(QUERY, s, 0x500)

    out.extend(target_picking.preference_bodies(labels))
    out.extend(options_row.bodies())
    emit(query_site(), f'call {QUERY}', 5)
    out.extend(options_row.hooks())
    return out


def verify(ram):
    assert all(bytes(ram[a:a + len(b)]) == b for a, b in bodies())
    return True


def setup(write, ram):
    assert not any(ram[BASE:END]), 'shot-assist reservation occupied'
    for a, b in predecessors().items():
        assert bytes(ram[a:a + len(b)]) == b, hex(a)
    for a, b in bodies():
        write(a, b)


def install(write, ram):
    """Connect the shot query and checkbox row to Options and snapshot controls.

    Snapshot controls first supply strings, input and helper-launch routines with
    presentation=False. This installer owns the checkbox and footer code slots.
    Preferences, wrist origins and reticle helpers must already be present.
    All hook, text and empty-storage checks finish before writes begin.
    """
    expected = predecessors()
    expected[AI_DRAW] = asm(AI_DRAW, f'call {WRIST_DRAW}')
    assert not any(ram[BASE:END]), 'shot/row reservation occupied'
    assert not any(ram[prequel_help.DRAW:prequel_help.END]), 'Prequel-help reservation occupied'
    prequel_help.validate_text(ram)
    for a, b in expected.items():
        assert bytes(ram[a:a + len(b)]) == b, (hex(a), 'final Options predecessor')
    pieces = [(prequel_help.DRAW, prequel_help.code()), *bodies()]
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
