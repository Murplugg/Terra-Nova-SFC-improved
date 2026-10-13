"""Keep descrambler text readable at higher frame rates.

Readable text scrolls one character every 50 game milliseconds. A scrambled
line replaces all 26 characters at once, so it uses a slower 100-ms interval
to keep weak reception from becoming a distracting flicker.
Drawing and signal checks still run each frame. The original decode deadline,
random-number calls and sounds retain their roles. A 64-byte state block holds
the clock shared by these paths.
"""
from patch_support import asm

CODE = 0x1e54000
ACTIVE = CODE + 0x400
STATE = CODE + 0x800
STATE_SIZE = 0x40
SITE = 0x26ead2
END = 0x26eb07
CHECK = 0x26e960
READABLE_MAGIC = 0x74344344

DISPATCH = CODE + 0x440
WEAK = CODE + 0x480
FINISH = CODE + 0x680
NOISE = STATE + 36
NOISE_MAGIC = 0x75354344
NOISE_INTERVAL_MS = 100
WEAK_SITE = 0x26eb42
FINISH_SITE = 0x26eb9c


def readable_bodies():
    b = asm(
        CODE, (
            f"push ebp;"
            f"cmp ecx,0xea00;"
            f"jle weak;"
            f"\n xor eax,eax;"
            f"mov ecx,-1;"
            f"repne scasb;"
            f"not ecx;"
            f"sub ecx,2;"
            f"mov ebp,ecx;"
            f"\n inc dword ptr [{STATE+24}];"
            f"mov ebx,[0x446ae8];"
            f"\n cmp dword ptr [{STATE}],{READABLE_MAGIC};"
            f"jne first;"
            f"\n cmp esi,[{STATE+12}];"
            f"jne first;"
            f"\n cmp ebp,[{STATE+32}];"
            f"jne first;"
            f"\n mov eax,[0x35b180];"
            f"cmp eax,[{STATE+20}];"
            f"jne first;"
            f"\n mov eax,ebx;"
            f"sub eax,[{STATE+4}];"
            f"js first;"
            f"cmp eax,250;"
            f"ja first;"
            f"\n mov [{STATE+4}],ebx;"
            f"add eax,[{STATE+8}];"
            f"xor edx,edx;"
            f"mov ecx,50;"
            f"div ecx;"
            f"\n mov [{STATE+8}],edx;"
            f"test eax,eax;"
            f"jz display;"
            f"jmp advance;"
            f"\n first:mov dword ptr [{STATE}],{READABLE_MAGIC};"
            f"mov [{STATE+4}],ebx;"
            f"\n mov dword ptr [{STATE+8}],0;"
            f"mov [{STATE+12}],esi;"
            f"mov [{STATE+32}],ebp;"
            f"mov eax,1;"
            f"\n advance:add [{STATE+28}],eax;"
            f"mov edi,eax;"
            f"\n step:mov edx,[0x35b180];"
            f"lea eax,[edx+1];"
            f"cmp eax,ebp;"
            f"jb nowrap;"
            f"\n xor eax,eax;"
            f"xor edx,edx;"
            f"\n nowrap:mov [0x35b180],eax;"
            f"mov [{STATE+16}],edx;"
            f"dec edi;"
            f"jnz step;"
            f"\n mov [{STATE+20}],eax;"
            f"\n display:mov edx,[{STATE+16}];"
            f"xor ebx,ebx;"
            f"pop ebp;"
            f"jmp {END};"
            f"\n weak:mov dword ptr [{STATE}],0;"
            f"pop ebp;"
            f"jmp 0x26eb42;"
        )
    )
    active = asm(
        ACTIVE, (
            f"test byte ptr [0x35b175],1;"
            f"jnz enabled;"
            f"\n mov dword ptr [{STATE}],0;"
            f"\n enabled:jmp {CHECK+7};"
        )
    )
    assert len(b) < 0x400 and len(active) < 0x400
    hook = asm(SITE, f'jmp {CODE}')
    return [
        (CODE, b), (ACTIVE, active), (SITE, hook + b'\x90' * (END - SITE - len(hook))),
        (CHECK, asm(CHECK, f'jmp {ACTIVE}') + b'\x90\x90')
    ]


def bodies():
    pieces = dict(readable_bodies())
    active = asm(
        ACTIVE, (
            f"test byte ptr [0x35b175],1;"
            f"jnz enabled;"
            f"\n mov dword ptr [{STATE}],0;"
            f"mov dword ptr [{NOISE}],0;"
            f"\n enabled:jmp {CHECK+7};"
        )
    )
    dispatch = asm(
        DISPATCH,
        (f"cmp ecx,0xea00;"
         f"jle weak;"
         f"\n mov dword ptr [{NOISE}],0;"
         f"\n weak:jmp {CODE};")
    )
    weak = asm(
        WEAK, (
            f"cmp ecx,0x8000;"
            f"jle lost;"
            f"\n pushad;"
            f"inc dword ptr [{NOISE+16}];"
            f"mov ebx,[0x446ae8];"
            f"\n cmp dword ptr [{NOISE}],{NOISE_MAGIC};"
            f"jne first;"
            f"\n cmp esi,[{NOISE+12}];"
            f"jne first;"
            f"\n mov eax,ebx;"
            f"sub eax,[{NOISE+4}];"
            f"js first;"
            f"cmp eax,250;"
            f"ja first;"
            f"\n mov [{NOISE+4}],ebx;"
            f"add eax,[{NOISE+8}];"
            f"xor edx,edx;"
            f"mov ecx,{NOISE_INTERVAL_MS};"
            f"div ecx;"
            f"\n mov [{NOISE+8}],edx;"
            f"test eax,eax;"
            f"jz hold;"
            f"jmp update;"
            f"\n first:mov dword ptr [{NOISE}],{NOISE_MAGIC};"
            f"mov [{NOISE+4}],ebx;"
            f"\n mov dword ptr [{NOISE+8}],0;"
            f"mov [{NOISE+12}],esi;"
            f"mov eax,1;"
            f"\n update:mov [{NOISE+24}],eax;"
            f"popad;"
            f"jmp 0x26eb4a;"
            f"\n hold:popad;"
            f"mov byte ptr [0x35b184],0;"
            f"jmp 0x26ebe3;"
            f"\n lost:mov dword ptr [{NOISE}],0;"
            f"jmp 0x26ebac;"
        )
    )
    finish = asm(
        FINISH, (
            f"inc dword ptr [{NOISE+20}];"
            f"dec dword ptr [{NOISE+24}];"
            f"\n jnz 0x26eb4a;"
            f"\n xor ch,ch;"
            f"mov [0x35b184],ch;"
            f"mov [ebp+0x38fc98],ch;"
            f"jmp 0x26ebe3;"
        )
    )
    assert len(active) <= DISPATCH - ACTIVE
    assert len(dispatch) <= WEAK - DISPATCH and len(weak) <= FINISH - WEAK and len(
        finish
    ) <= STATE - FINISH
    hook = asm(SITE, f'jmp {DISPATCH}')
    pieces.update(
        {
            ACTIVE: active,
            SITE: hook + b'\x90' * (END - SITE - len(hook)),
            DISPATCH: dispatch,
            WEAK: weak,
            FINISH: finish,
            WEAK_SITE: asm(WEAK_SITE, f'jmp {WEAK}') + b'\x90' * 3,
            FINISH_SITE: asm(FINISH_SITE, f'jmp {FINISH}') + b'\x90' * (0x26ebac - FINISH_SITE - 5)
        }
    )
    return list(pieces.items())


def install(write, ram, original):
    """Install readable and noisy text clocks over verified original instructions.

    The original image must be relocated and verified. Empty storage and complete
    hook checks prevent an occupied or partially installed feature from changing.
    """
    assert not any(ram[CODE:STATE + STATE_SIZE]), 'descrambler reservation occupied'
    pieces = bodies()
    sites = (SITE, CHECK, WEAK_SITE, FINISH_SITE)
    for address, data in pieces:
        expected = bytes(original[address:address +
                                  len(data)]) if address in sites else bytes(len(data))
        assert bytes(ram[address:address + len(data)]
                     ) == expected, (hex(address), 'descrambler predecessor')
    for address, data in pieces:
        write(address, data)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
