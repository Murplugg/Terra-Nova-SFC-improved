"""Preserve dialog coverage, redirect suit damage drawing and prepare movie I/O.

These wrappers adapt original drawing and file callbacks to the native canvas.
Each generator owns distinct final spans; it does not amend another provider.
The temporary mask and callback state keep their accepted address layout.
"""
import struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
from foundation_hud import branch, READY, LOW, CANVAS, PIXELS, MASK
from foundation_cameras import SLOTS

DIALOG_BOXES = ((0x2454bc, 0xa11200, 0xa11a00), (0x245600, 0xa11600, 0xa11a20))

DIALOG_TEMP = 0xa13000

DIALOG_STATS = 0xa11c00

DIALOG_BUSY = 0x9aa0e8


def dialog_coverage():
    """Record opaque dialog pixels without relying on their palette color."""
    k = Ks(KS_ARCH_X86, KS_MODE_32)

    def asm(a, s):
        return bytes(k.asm(s.replace('rep stosd;', '.byte 0xf3,0xab;'), addr=a)[0])

    payload = []
    for original, entry, trampoline in DIALOG_BOXES:
        code = asm(
            entry, (
                f"\n   pushfd;"
                f" pushad;"
                f" call {trampoline};"
                f"\n   pushfd;"
                f" pushad;"
                f" mov ebp,esp;"
                f" cld;"
                f"\n   cmp byte ptr [0x449],0x6b;"
                f" jne done;"
                f"\n   cmp dword ptr [0x446f80],0x00c80140;"
                f" jne done;"
                f"\n   mov esi,dword ptr [0x44b1a0];"
                f"\n   cmp word ptr [esi+12],320;"
                f" jne done;"
                f"\n   mov edi,dword ptr [esi];"
                f" mov eax,edi;"
                f" sub eax,dword ptr [0x446f78];"
                f"\n   cmp eax,64000;"
                f" jae done;"
                f"\n   movzx edx,word ptr [esi+10];"
                f" test edx,edx;"
                f" jz done;"
                f"\n   dec edx;"
                f" imul edx,edx,320;"
                f"\n   movzx ecx,word ptr [esi+8];"
                f" test ecx,ecx;"
                f" jz done;"
                f"\n   add edx,ecx;"
                f" add edx,eax;"
                f" cmp edx,64000;"
                f" ja done;"
                f"\n   push edi;"
                f" push dword ptr [esi+16];"
                f" push dword ptr [{DIALOG_BUSY}];"
                f"\n   mov dword ptr [{DIALOG_BUSY}],1;"
                f" inc byte ptr [0x447115];"
                f"\n   add eax,{DIALOG_TEMP};"
                f" mov dword ptr [esi],eax;"
                f"\n   mov edi,{DIALOG_TEMP};"
                f" mov eax,0xffffffff;"
                f" mov ecx,16000;"
                f" rep stosd;"
                f"\n   mov eax,dword ptr [ebp+64];"
                f" xor ebx,ebx;"
                f" xor ecx,ecx;"
                f" xor edx,edx;"
                f"\n   call {trampoline};"
                f"\n   pop dword ptr [{DIALOG_BUSY}];"
                f" pop dword ptr [esi+16];"
                f" pop dword ptr [esi];"
                f"\n   dec byte ptr [0x447115];"
                f"\n   mov esi,{DIALOG_TEMP};"
                f" mov edi,{MASK};"
                f" mov ecx,16000;"
                f"\n   mask: lodsd;"
                f" and dword ptr [edi],eax;"
                f" add edi,4;"
                f" loop mask;"
                f"\n   mov ebp,{SLOTS};"
                f"\n   slot: cmp dword ptr [ebp],0;"
                f" je next;"
                f"\n   mov eax,dword ptr [0x446f78];"
                f" cmp eax,dword ptr [ebp+16];"
                f" jne next;"
                f"\n   mov esi,dword ptr [ebp+20];"
                f" add esi,{DIALOG_TEMP};"
                f" mov edi,dword ptr [ebp+64];"
                f"\n   mov edx,dword ptr [ebp+36];"
                f"\n   row: mov ecx,dword ptr [ebp+32];"
                f"\n   cell: lodsb;"
                f" and byte ptr [edi],al;"
                f" inc edi;"
                f" loop cell;"
                f"\n   add esi,320;"
                f" sub esi,dword ptr [ebp+32];"
                f" dec edx;"
                f" jnz row;"
                f"\n   next: add ebp,128;"
                f" cmp ebp,{SLOTS+384};"
                f" jb slot;"
                f"\n   inc dword ptr [{DIALOG_STATS}];"
                f"\n   done: popad;"
                f" popfd;"
                f"\n   push eax;"
                f" lea eax,[esp+12];"
                f" add eax,0x10;"
                f" pop eax;"
                f"\n   lea esp,[esp+36];"
                f" ret;"
                f"\n  "
            )
        )
        # Both originals end in ADD ESP,0x10; reproduce its arithmetic flags using
        # the caller's original stack depth, rather than the wrapper's deeper stack.
        assert len(code) < 0x400
        tramp = asm(
            trampoline,
            (f"push esi;"
             f" push edi;"
             f" push ebp;"
             f" sub esp,0x10;"
             f" jmp {original+6};")
        )
        payload.extend(
            [(entry, code), (trampoline, tramp), (original, branch(original, entry) + b'\x90')]
        )

    return payload


DAMAGE_ENTRY = 0xa11d00

DAMAGE_STATS = 0xa11f00

DAMAGE_SAVE = DAMAGE_STATS + 32

DAMAGE_SITE = 0x26920e

DAMAGE_ORIGINAL = 0x27a618


def damage_call_branch(a, b):
    return b'\xe8' + struct.pack('<i', b - a - 5)


def damage_canvas():
    """Draw suit damage into the enlarged active world canvas."""
    k = Ks(KS_ARCH_X86, KS_MODE_32)
    code = bytes(
        k.asm(
            (
                f"\n pushfd;"
                f" pushad;"
                f"\n cmp byte ptr [0x449],0x6b;"
                f" jne fallback;"
                f"\n cmp dword ptr [{READY}],1;"
                f" jne fallback;"
                f"\n mov esi,dword ptr [0x44b1a0];"
                f"\n cmp esi,dword ptr [{LOW+28}];"
                f" jne fallback;"
                f"\n cmp dword ptr [{CANVAS}],{PIXELS};"
                f" jne fallback;"
                f"\n mov dword ptr [{DAMAGE_SAVE}],esi;"
                f"\n mov eax,dword ptr [{CANVAS+32}];"
                f" mov dword ptr [{DAMAGE_SAVE+4}],eax;"
                f"\n mov eax,dword ptr [{CANVAS+36}];"
                f" mov dword ptr [{DAMAGE_SAVE+8}],eax;"
                f"\n mov eax,dword ptr [esi+32];"
                f" mov dword ptr [{CANVAS+32}],eax;"
                f"\n mov eax,dword ptr [esi+36];"
                f" mov dword ptr [{CANVAS+36}],eax;"
                f"\n mov eax,{CANVAS};"
                f" call 0x2eab30;"
                f"\n inc dword ptr [{DAMAGE_STATS}];"
                f"\n popad;"
                f" popfd;"
                f"\n call {DAMAGE_ORIGINAL};"
                f"\n pushfd;"
                f" pushad;"
                f"\n mov eax,dword ptr [{DAMAGE_SAVE+4}];"
                f" mov dword ptr [{CANVAS+32}],eax;"
                f"\n mov eax,dword ptr [{DAMAGE_SAVE+8}];"
                f" mov dword ptr [{CANVAS+36}],eax;"
                f"\n mov eax,dword ptr [{DAMAGE_SAVE}];"
                f" call 0x2eab30;"
                f"\n popad;"
                f" popfd;"
                f" ret;"
                f"\n fallback: inc dword ptr [{DAMAGE_STATS+4}];"
                f" popad;"
                f" popfd;"
                f" jmp {DAMAGE_ORIGINAL};"
                f"\n "
            ),
            addr=DAMAGE_ENTRY
        )[0]
    )
    assert len(code) < 0x200
    return [(DAMAGE_ENTRY, code), (DAMAGE_SITE, damage_call_branch(DAMAGE_SITE, DAMAGE_ENTRY))]


MOVIE_OPEN = 0xa22b00

MOVIE_PREFETCH = 0xa22d00

MOVIE_CURSOR = 0xa22e00

MOVIE_STATE = 0xa23000


def movie_branch(a, b, opcode=0xe9):
    return bytes([opcode]) + struct.pack('<i', b - a - 5)


def movie_io():
    """Bind movie file prefetch and cursor handling to the native runtime."""
    k = Ks(KS_ARCH_X86, KS_MODE_32)

    def code(a, s):
        return bytes(k.asm(s, addr=a)[0])

    op = code(
        MOVIE_OPEN, (
            f"\n push dword ptr [esp+12];"
            f"push dword ptr [esp+12];"
            f"push dword ptr [esp+12];"
            f"call 0x3007a0;"
            f"\n pushfd;"
            f"pushad;"
            f"\n mov dword ptr [{MOVIE_STATE}],0;"
            f"mov dword ptr [{MOVIE_STATE+4}],0;"
            f"\n test eax,eax;"
            f"jz done;"
            f"\n cmp dword ptr [eax],0x324b4d53;"
            f"jne done;"
            f"\n mov esi,[eax+0x3b4];"
            f"mov ecx,[eax+12];"
            f"\n test ecx,ecx;"
            f"jz done;"
            f"cmp ecx,100000;"
            f"ja done;"
            f"\n mov edx,[eax+20];"
            f"and edx,1;"
            f"add ecx,edx;"
            f"\n mov edx,[eax+0x3a4];"
            f"test esi,esi;"
            f"jz done;"
            f"\n sum: add edx,[esi];"
            f"jc done;"
            f"add esi,4;"
            f"dec ecx;"
            f"jnz sum;"
            f"\n mov [{MOVIE_STATE}],eax;"
            f"mov [{MOVIE_STATE+4}],edx;"
            f"\n done:popad;"
            f"popfd;"
            f"ret 12;"
            f"\n "
        )
    )
    pre = code(
        MOVIE_PREFETCH, (
            f"\n pushfd;"
            f"push edx;"
            f"\n cmp eax,[{MOVIE_STATE}];"
            f"jne original;"
            f"\n cmp dword ptr [{MOVIE_STATE+4}],0;"
            f"je original;"
            f"\n mov edx,[eax+0x440];"
            f"add edx,[eax+0x438];"
            f"jc original;"
            f"\n cmp edx,[{MOVIE_STATE+4}];"
            f"jb original;"
            f"\n inc dword ptr [{MOVIE_STATE+8}];"
            f"pop edx;"
            f"popfd;"
            f"xor eax,eax;"
            f"ret;"
            f"\n original:pop edx;"
            f"popfd;"
            f"\n push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"jmp 0x301b06;"
            f"\n "
        )
    )
    cur = code(
        MOVIE_CURSOR, (
            f"\n pushfd;"
            f"\n cmp byte ptr [0x449],0x69;"
            f"jne original;"
            f"\n cmp word ptr [0x446f80],640;"
            f"jne original;"
            f"\n cmp word ptr [0x446f82],480;"
            f"jne original;"
            f"\n cmp word ptr [0x44d0ca],640;"
            f"jae original;"
            f"\n cmp word ptr [0x44d0cc],480;"
            f"jae original;"
            f"\n mov eax,[0x44d0ca];"
            f"inc dword ptr [{MOVIE_STATE+12}];"
            f"\n original:popfd;"
            f"\n push ebx;"
            f"push ecx;"
            f"push edx;"
            f"sub esp,4;"
            f"jmp 0x2e4a6e;"
            f"\n "
        )
    )
    assert len(op) <= MOVIE_PREFETCH - MOVIE_OPEN and len(
        pre
    ) <= MOVIE_CURSOR - MOVIE_PREFETCH and len(cur) <= MOVIE_STATE - MOVIE_CURSOR
    return [
        (MOVIE_OPEN, op), (MOVIE_PREFETCH, pre), (MOVIE_CURSOR, cur),
        (0x2dc2f9, movie_branch(0x2dc2f9, MOVIE_OPEN, 0xe8)),
        (0x2dc314, movie_branch(0x2dc314, MOVIE_OPEN, 0xe8)),
        (0x301b00, movie_branch(0x301b00, MOVIE_PREFETCH) + b'\x90'),
        (0x2e4a68, movie_branch(0x2e4a68, MOVIE_CURSOR) + b'\x90')
    ]
