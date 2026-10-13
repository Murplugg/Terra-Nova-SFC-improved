"""Draw the Prequel snapshot shortcuts beneath the Options checkboxes.

DRAW includes the wrist/FPS row; TAIL draws only the conditional footer. The
combined checkbox row calls TAIL to avoid painting the controls twice. Text comes
from the snapshot-control string block and is verified before installation.
"""
from patch_support import asm
from features.option_contracts import WRIST_DRAW

DRAW = 0x1effa00
TAIL = DRAW + 5
END = 0x1effb00
TEXT = 0x1effb56
MESSAGE = b'PREQUEL STATES: PAUSE (P), THEN F5 SAVE / F9 LOAD\0'


def code(text=TEXT):
    if text != TEXT:
        raise ValueError('Unsupported Prequel-help text location')
    result = asm(
        DRAW, (
            f"\ncall {WRIST_DRAW};"
            f"pushfd;"
            f"pushad;"
            f"\n        cmp dword ptr [0x1fc0700],1;"
            f"jne done;"
            f"\n        cmp dword ptr [0x1fcae10],0;"
            f"jne done;"
            f"\n        mov esi,[0x44b1a0];"
            f"push dword ptr [esi+0x10];"
            f"push dword ptr [esi+0x18];"
            f"\n        mov dword ptr [esi+0x10],0xf7;"
            f"mov eax,0x164;"
            f"call 0x2eb380;"
            f"mov [esi+0x18],eax;"
            f"\n        mov edi,[0x44b194];"
            f"mov edx,{text};"
            f"mov ebx,6;"
            f"mov ecx,468;"
            f"call dword ptr [edi+0x4ec];"
            f"\n        mov eax,0x164;"
            f"call 0x2eb3f4;"
            f"\n        pop dword ptr [esi+0x18];"
            f"pop dword ptr [esi+0x10];"
            f"done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    assert result[:5] == asm(DRAW, f'call {WRIST_DRAW}')
    assert DRAW + len(result) <= END
    return result


def validate_text(ram):
    assert bytes(ram[TEXT:TEXT + len(MESSAGE)]) == MESSAGE, 'Prequel-help text provider differs'
