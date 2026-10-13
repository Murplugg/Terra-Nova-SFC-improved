"""Present the gameplay/display checkboxes and their contextual help.

This module draws labels and handles checkbox input, Accept and Close. Each
preference provider owns its state and persistence. The Prequel footer is drawn
through its TAIL entry so the checkbox row is painted only once. Fixed addresses
preserve the layout expected by saved snapshots.
"""
from patch_support import asm
from features.option_contracts import WRIST, FPS, AI, SHOT, PICK, WRIST_ACCEPT, WRIST_CLOSE, AI_DRAW, SHARED_SAVE
from features import prequel_help

DRAW = 0x1d34800
EVENT = 0x1d34d00
ACCEPT = 0x1d35000
CLOSE = 0x1d35080
TEXT = 0x1d35100
STATE = SHOT.state
WRIST_STATE = WRIST.state
FPS_STATE = FPS.state
AI_STATE = AI.state
WRIST_INIT = WRIST.init
FPS_INIT = FPS.init
INIT = SHOT.init
SAVE = SHOT.save
EVENT_SITE = 0x2ca450
CLOSE_SITE = 0x2cbc08
# Unequal columns leave room for the longer selection label.
COLUMNS = (0, 128, 208, 326, 460, 640)


def strings():
    labels = {}
    raw = bytearray()
    for key, value in [
        ('section', 'Gameplay'), ('key', 'UnlockedShotAssist'), ('zero', '0'), ('one', '1'),
        ('wrist', 'WRIST-HEIGHT FIRING'), ('fps', 'SHOW FPS'), ('assist', 'SHOT AIM ASSIST'),
        ('ai', 'FULL-RATE AI FIRING'),
        ('pkey', 'ImprovedTargetSelection'), ('pick', 'IMPROVED TARGET SELECTION'),
        ('phelp', 'On: precise selection with depth checks. Off: original selection, including units behind buildings.'),
        (
            'whelp',
            'On: fire from animated wrists. Off: helmet height. Nearby cover can block wrist shots.'
        ), ('fhelp', 'Show the in-game frame rate.'),
        (
            'shelp',
            'Unlocked shots: on helps hit mobile units; off keeps the reticle ray. Target lock is unchanged.'
        ),
        (
            'ahelp',
            'Both sides use weapon cooldowns. Normal aiming, range and safety checks still apply.'
        )
    ]:
        labels[key] = TEXT + len(raw)
        raw += value.encode('ascii') + b'\0'
    assert TEXT + len(raw) < STATE
    return labels, bytes(raw)


def bodies(*, help_tail=prequel_help.TAIL):
    if help_tail != prequel_help.TAIL:
        raise ValueError('Unsupported Prequel-help continuation')
    out = []
    labels, _ = strings()

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b), cap)
        out.append((a, b))

    # Five controls share the existing row above Accept and Cancel. Keep the existing accept/cancel machinery
    # and each older preference's own persistence routines.
    checks = [
        (WRIST_STATE, 'wrist', 'whelp'), (FPS_STATE, 'fps', 'fhelp'), (STATE, 'assist', 'shelp'),
        (AI_STATE, 'ai', 'ahelp'), (PICK.state, 'pick', 'phelp')
    ]
    s = (
        f"call 0x2cac54;"
        f"pushfd;"
        f"pushad;"
        f"call {WRIST_INIT};"
        f"call {FPS_INIT};"
        f"call {INIT};"
        f"call {PICK.init};"
    )
    for state, _, _ in checks:
        s += (
            f"cmp dword ptr [{state+12}],1;"
            f"je ready{state};"
            f"mov eax,[{state+4}];"
            f"mov [{state+8}],eax;"
            f"\n          mov dword ptr [{state+12}],1;"
            f"ready{state}:;"
        )
    s += (
        "mov esi,[0x44b1a0];"
        "push dword ptr [esi+0x10];"
        "push dword ptr [esi+0x18];"
        "mov edi,[0x44b194];"
        "\n        mov dword ptr [esi+0x10],0;"
        "mov eax,0;"
        "mov edx,388;"
        "mov ebx,639;"
        "mov ecx,410;"
        "call dword ptr [edi+0x40];"
        "\n        mov eax,0;"
        "mov edx,466;"
        "mov ebx,639;"
        "mov ecx,479;"
        "call dword ptr [edi+0x40];"
        "\n        mov dword ptr [esi+0x10],0xf7;"
        "mov eax,0x164;"
        "call 0x2eb380;"
        "mov [esi+0x18],eax;"
    )
    for i, (state, label, helpkey) in enumerate(checks):
        x = 8 + COLUMNS[i]
        y = 392
        s += (
            f"mov eax,{x};"
            f"mov edx,{y};"
            f"mov ebx,{x+10};"
            f"mov ecx,{y+10};"
            f"call dword ptr [edi+0x48];"
            f"\n          cmp dword ptr [{state+8}],0;"
            f"je label{i};"
            f"mov eax,{x+2};"
            f"mov edx,{y+2};"
            f"mov ebx,{x+8};"
            f"mov ecx,{y+8};"
            f"call dword ptr [edi+0x40];"
            f"\n          label{i}:mov eax,[esi+0x18];"
            f"mov edx,{labels[label]};"
            f"mov ebx,{x+16};"
            f"mov ecx,{y};"
            f"call dword ptr [edi+0x4ec];"
            f"\n          cmp dword ptr [{STATE+16}],{i+1};"
            f"jne nohelp{i};"
            f"mov eax,[esi+0x18];"
            f"mov edx,{labels[helpkey]};"
            f"mov ebx,6;"
            f"mov ecx,468;"
            f"call dword ptr [edi+0x4ec];"
            f"nohelp{i}:;"
        )
    s += (
        f"mov eax,0x164;"
        f"call 0x2eb3f4;"
        f"pop dword ptr [esi+0x18];"
        f"pop dword ptr [esi+0x10];"
        f"popad;"
        f"popfd;"
        f"jmp {help_tail};"
    )
    emit(DRAW, s, 0x500)
    s = (
        "pushfd;"
        "pushad;"
        "cmp dword ptr [eax],0x40;"
        "je mouse;"
        "cmp dword ptr [eax],1;"
        "jne pass;"
        "\n        mouse:xor ebx,ebx;"
        "movsx ecx,word ptr [eax+10];"
        "cmp ecx,388;"
        "jl selected;"
        "cmp ecx,410;"
        "jge selected;"
        "\n        movsx ecx,word ptr [eax+8];"
        "cmp ecx,0;"
        "jl selected;"
        "cmp ecx,640;"
        "jge selected;"
        "\n        mov ebx,1;"
        "cmp ecx,128;jl selected;inc ebx;"
        "cmp ecx,208;jl selected;inc ebx;"
        "cmp ecx,326;jl selected;inc ebx;"
        "cmp ecx,460;jl selected;inc ebx;"
        "\n        selected:cmp dword ptr [eax],1;"
        "jne hover;"
        "test ebx,ebx;"
        "jz hover;"
    )
    for i, (state, _, _) in enumerate(checks):
        s += (f"cmp ebx,{i+1};"
              f"jne next{i};"
              f"xor dword ptr [{state+8}],1;"
              f"next{i}:;")
    s += (
        f"mov [{STATE+16}],ebx;"
        f"mov [{WRIST_STATE+16}],ebx;"
        f"call redraw;"
        f"push 0;"
        f"push 0x40;"
        f"mov eax,0x7cc;"
        f"mov ebx,0x28;"
        f"push 0x40;"
        f"mov ecx,1;"
        f"xor edx,edx;"
        f"call 0x247b60;"
        f"\n        popad;"
        f"popfd;"
        f"mov al,1;"
        f"ret;"
        f"\n        hover:cmp ebx,[{STATE+16}];"
        f"je pass;"
        f"mov [{STATE+16}],ebx;"
        f"mov [{WRIST_STATE+16}],ebx;"
        f"call redraw;"
        f"\n        pass:popad;"
        f"popfd;"
        f"push ebx;"
        f"push ecx;"
        f"push edx;"
        f"push esi;"
        f"push edi;"
        f"jmp 0x2ca455;"
        f"\n        redraw:call 0x2e4b1c;"
        f"mov eax,0x446f78;"
        f"call {DRAW};"
        f"mov eax,0x446fb8;"
        f"call 0x2e43d0;"
        f"call 0x2e4b78;"
        f"ret;"
    )
    emit(EVENT, s, 0x300)
    emit(ACCEPT, f'call {PICK.save};call {SAVE};jmp {WRIST_ACCEPT};', 0x80)
    emit(
        CLOSE, (
            f"pushfd;"
            f"mov dword ptr [{PICK.state+12}],0;"
            f"mov dword ptr [{STATE+12}],0;"
            f"mov dword ptr [{STATE+16}],0;"
            f"popfd;"
            f"jmp {WRIST_CLOSE};"
        ), 0x80
    )
    return out


def hooks():
    return [
        (AI_DRAW, asm(AI_DRAW, f'jmp {DRAW}')), (EVENT_SITE, asm(EVENT_SITE, f'jmp {EVENT}')),
        (SHARED_SAVE, asm(SHARED_SAVE, f'call {ACCEPT}')),
        (CLOSE_SITE, asm(CLOSE_SITE, f'jmp {CLOSE}'))
    ]
