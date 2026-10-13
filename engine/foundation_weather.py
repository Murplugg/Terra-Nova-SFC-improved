"""Reviewed weather scaling, clipped sky writes and terrain row relocation.

Projection coordinates, displaced draw calls and table operands belong to the
original engine. These generators retain its calling conventions and the checked
foundation layout; they read no process state, captured memory or journals.
"""
import struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
from foundation_hud import CANVAS, LOW, EFFECT, dword, assemble, branch

POINT = 0x9bb0e8
SPRITE = 0x9bb4e8
SKY_D = 0x9bb8e8
SKY_C = 0x9bb9e8
STATS = 0x9bbae8
ROW_TABLES = {
    0x424a80: (0x9d04e8, (0x2a79f9, 0x2a7a4c)),
    0x425400: (0x9d14e8, (0x2a7624, 0x2a76d3, 0x2a7762)),
    0x425f80: (0x9d24e8, (0x2a73af, 0x2a757f, 0x2a7618, 0x2a76b5)),
    0x426700: (0x9d34e8, (0x2a75c7, 0x2a76c2)),
    0x426e80: (0x9d44e8, (0x2a75bf, 0x2a76a2)),
    0x427600: (0x9d54e8, (0x2a73b5, 0x2a7532, 0x2a761e, 0x2a76ac)),
}
ROW_GUARDS = tuple(a for base, _ in ROW_TABLES.values() for a in (base - 256, base + 600 * 4))


def callpatch(a, b):
    return b'\xe8' + struct.pack('<i', b - a - 5)


def weather():
    """Scale weather, bound sky writes and relocate terrain row buffers."""
    k = Ks(KS_ARCH_X86, KS_MODE_32)
    asm = lambda a, s: bytes(k.asm(s, addr=a)[0])
    point = asm(
        POINT, (
            f"\n cmp dword ptr [0x44b1a0],{CANVAS};"
            f" jne other;"
            f"\n pushfd;"
            f" pushad;"
            f" cld;"
            f" inc dword ptr [{STATS}];"
            f"\n mov esi,eax;"
            f" movsx edx,dx;"
            f" movsx ebx,bx;"
            f"\n test edx,edx;"
            f" js done;"
            f" test ebx,ebx;"
            f" js done;"
            f"\n mov eax,dword ptr [{LOW+28}];"
            f" mov eax,dword ptr [eax];"
            f" sub eax,dword ptr [0x446f78];"
            f"\n and eax,1;"
            f" xor eax,1;"
            f"\n imul edx,edx,5;"
            f" add edx,eax;"
            f" lea ebp,[edx+5];"
            f" sar edx,1;"
            f" sar ebp,1;"
            f"\n movzx ecx,word ptr [{CANVAS+8}];"
            f" cmp edx,ecx;"
            f" jge done;"
            f"\n cmp ebp,ecx;"
            f" jle right;"
            f" mov ebp,ecx;"
            f"\n right: sub ebp,edx;"
            f"\n imul ebx,ebx,3;"
            f" movzx eax,word ptr [{CANVAS+10}];"
            f" cmp ebx,eax;"
            f" jge done;"
            f"\n sub eax,ebx;"
            f" cmp eax,3;"
            f" jle bottom;"
            f" mov eax,3;"
            f"\n bottom: push eax;"
            f"\n movzx ecx,word ptr [{CANVAS+12}];"
            f" imul ebx,ecx;"
            f" add ebx,edx;"
            f"\n mov edi,dword ptr [{CANVAS}];"
            f" add edi,ebx;"
            f"\n mov ebx,ecx;"
            f" sub ebx,ebp;"
            f" pop edx;"
            f" mov eax,esi;"
            f"\n row: mov ecx,ebp;"
            f" rep stosb;"
            f" add edi,ebx;"
            f" dec edx;"
            f" jnz row;"
            f"\n inc dword ptr [{STATS+4}];"
            f"\n done: popad;"
            f" popfd;"
            f" ret;"
            f"\n other: jmp 0x2fad20;"
            f"\n "
        )
    )
    sprite = asm(
        SPRITE, (
            f"\n cmp dword ptr [0x44b1a0],{CANVAS};"
            f" jne other;"
            f"\n cmp byte ptr [eax+4],2;"
            f" jne other;"
            f"\n pushfd;"
            f" pushad;"
            f" cld;"
            f" inc dword ptr [{STATS+8}];"
            f"\n movzx ecx,word ptr [eax+8];"
            f" movzx ebp,word ptr [eax+10];"
            f"\n test ecx,ecx;"
            f" jz done;"
            f" cmp ecx,32;"
            f" ja done;"
            f"\n test ebp,ebp;"
            f" jz done;"
            f" cmp ebp,32;"
            f" ja done;"
            f"\n movzx edi,word ptr [eax+12];"
            f" sub edi,ecx;"
            f" js done;"
            f"\n mov esi,dword ptr [eax];"
            f" movsx edx,dx;"
            f" movsx ebx,bx;"
            f"\n push edi;"
            f" push ecx;"
            f" push edx;"
            f"\n row: mov edx,dword ptr [esp];"
            f" mov ecx,dword ptr [esp+4];"
            f"\n pixel: movzx eax,byte ptr [esi];"
            f" test eax,eax;"
            f" jz transparent;"
            f"\n call {POINT};"
            f"\n transparent: inc esi;"
            f" inc edx;"
            f" dec ecx;"
            f" jnz pixel;"
            f"\n add esi,dword ptr [esp+8];"
            f" inc ebx;"
            f" dec ebp;"
            f" jnz row;"
            f"\n add esp,12;"
            f"\n done: popad;"
            f" popfd;"
            f" ret;"
            f"\n other: jmp dword ptr [edi+0x24c];"
            f"\n "
        )
    )

    def sky(a, index):
        return asm(
            a, (
                f"\n  pushfd;"
                f" push ebx;"
                f" push esi;"
                f"\n  mov ebx,dword ptr [0x44b1a0];"
                f" movzx ebx,word ptr [ebx+10];"
                f"\n  cmp ebx,600;"
                f" jbe cap;"
                f" mov ebx,600;"
                f"\n  cap: shl ebx,2;"
                f" cmp {index},4;"
                f" jb skip;"
                f" cmp {index},ebx;"
                f" ja skip;"
                f"\n  mov dword ptr [{index}+{EFFECT-4}],eax;"
                f" jmp done;"
                f"\n  skip: inc dword ptr [{STATS+12}];"
                f"\n  done: pop esi;"
                f" pop ebx;"
                f" popfd;"
                f" ret;"
                f"\n  "
            )
        )

    assert len(point) < 0x400 and len(sprite) < 0x400
    p = [(POINT, point), (SPRITE, sprite), (SKY_D, sky(SKY_D, 'edx')), (SKY_C, sky(SKY_C, 'ecx'))]
    p += [(a, callpatch(a, POINT)) for a in (0x2afb47, 0x2afb6a, 0x2afb82)]
    p += [(0x2afbad, callpatch(0x2afbad, SPRITE) + b'\x90')]
    p += [
        (a, callpatch(a, b) + b'\x90')
        for a, b in ((0x2a85c6, SKY_D), (0x2a860a, SKY_C), (0x2a8628, SKY_C))
    ]
    for old, (new, sites) in ROW_TABLES.items():
        p += [(a, dword(new)) for a in sites]
    p += [(0x2a7a1e, dword(ROW_TABLES[0x424a80][0] - 4))]
    return p + rain_lifetime()


RAIN_ENTRY = 0xa11000

RAIN_RETURN = 0x2af56c


def rain_lifetime():
    k = Ks(KS_ARCH_X86, KS_MODE_32)

    def asm(a, s):
        return bytes(k.asm(s.replace('rep movsd;', '.byte 0xf3,0xa5;'), addr=a)[0])

    # Timestamp store and original following CMP are displaced together.
    rain = asm(
        RAIN_ENTRY, (
            "\n pushfd;"
            "\n cmp ebx,0x41eb68;"
            " jne unchanged;"
            "\n shl dword ptr [esp+0x14],1;"
            "\n unchanged: popfd;"
            "\n mov dword ptr [edi+0x26],ecx;"
            "\n cmp dword ptr [edi+0x1a],0xffff0000;"
            "\n jmp 0x2af56c;"
            "\n "
        )
    )
    payload = [(RAIN_ENTRY, rain), (0x2af562, branch(0x2af562, RAIN_ENTRY) + b'\x90' * 5)]
    return payload


def sky_spans():
    """Wide-span termination, retaining the original inner loop's UV arithmetic.

    The displaced push/load/shift prologue and final pop/return are original
    instructions. Only the packed 8-bit counter termination is replaced by a
    destination-end comparison, so rows wider than 256 pixels finish drawing.
    """
    start, tail, stub, finish, end = 0x2b2740, 0x2b277f, 0x354c00, 0x354c80, 0x354cf0
    first = assemble(
        stub, (
            f"push eax;"
            f"movzx eax,word ptr [esi+0x16];"
            f"add eax,edi;"
            f"\n        mov [{end}],eax;"
            f"pop eax;"
            f"push ebp;"
            f"mov eax,[esi];"
            f"shl eax,16;"
            f"jmp {start+6};"
        )
    )
    last = assemble(finish, (f"cmp edi,[{end}];"
                             f"jne 0x2b2768;"
                             f"pop ebp;"
                             f"ret;"))
    return [
        (stub, first), (finish, last), (start, branch(start, stub) + b'\x90'),
        (tail, branch(tail, finish))
    ]
