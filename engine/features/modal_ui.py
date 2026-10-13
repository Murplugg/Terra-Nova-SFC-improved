"""Modal HUD coverage and pause/tooltip lifetime providers.

Both use bounded owned state and original game heap/clock callbacks.
"""
"""Restore native HUD coverage alongside the original modal-dialog bitmap.

The DOS dialog at 246094 backs up logical pixels, then 2461b0 restores them.
Native framed-box drawing also changes separate coverage masks. Without the
same lifetime, cancelling Alt+X while paused leaves an opaque black rectangle.
The hook at 24622e restores coverage before the existing full compositor call.
An original-heap allocation is owned only for the modal lifetime; neither the
simulation nor the renderer runs an extra frame to repair the screen.
"""
from patch_support import asm

DIALOG_CODE = 0x1D2C000
DIALOG_RESTORE = DIALOG_CODE + 0x800
DIALOG_END = 0x1D2E000
DIALOG_STATE = DIALOG_END - 0x100  # nesting depth, original-heap context pointer
DIALOG_ENTRY = 0x246094
DIALOG_PRESENT = 0x24622E
DIALOG_MAGIC = 0x39323144
DIALOG_PLANS = {
    0x00C80140: ((0x870000, 64000), (0xA0B100, 6400), (0xA0D100, 6400), (0xA0F100, 6400)),
    0x01900140: (
        (0x1E80000, 128000), (0x1EE9D00, 12800), (0x1EED100, 12800), (0x1EF0500, 12800),
        (0x1FA0000, 128000)
    ),
}
DIALOG_OLD = {
    DIALOG_ENTRY: bytes.fromhex('535152565755'),
    DIALOG_PRESENT: bytes.fromhex('e89de10900')
}


def dialog_encode(address, source):
    return asm(address, source.replace('rep movsd;', '.byte 0xf3,0xa5;'))


def dialog_bodies():
    save = (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"inc dword ptr [{DIALOG_STATE}];"
        f"\n        cmp dword ptr [{DIALOG_STATE}],1;"
        f"jne done;"
        f"\n        cmp byte ptr [0x1d0d449],0x6b;"
        f"jne done;"
    )
    restore = (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"cmp dword ptr [{DIALOG_STATE}],0;"
        f"je done;"
        f"\n        dec dword ptr [{DIALOG_STATE}];"
        f"jnz done;"
        f"\n        mov ebp,[{DIALOG_STATE+4}];"
        f"mov dword ptr [{DIALOG_STATE+4}],0;"
        f"\n        test ebp,ebp;"
        f"jz done;"
        f"\n        cmp dword ptr [ebp+12],{DIALOG_MAGIC};"
        f"jne release;"
        f"\n        cmp byte ptr [0x1d0d449],0x6b;"
        f"jne release;"
        f"\n        mov eax,[0x446f78];"
        f"cmp eax,[ebp+4];"
        f"jne release;"
        f"\n        mov eax,[0x446f80];"
        f"cmp eax,[ebp];"
        f"jne release;"
    )
    for dims in DIALOG_PLANS:
        save += f'cmp dword ptr [0x446f80],{dims};je save{dims};'
        restore += f'cmp eax,{dims};je restore{dims};'
    save += 'jmp done;'
    restore += 'jmp release;'
    for dims, spans in DIALOG_PLANS.items():
        size = 16 + sum(n for _, n in spans) + 16
        save += f'''save{dims}:mov eax,{size};call dword ptr [0x35f4a4];
            test eax,eax;jz done;mov ebp,eax;mov [{DIALOG_STATE+4}],eax;
            mov dword ptr [ebp],{dims};mov eax,[0x446f78];mov [ebp+4],eax;
            mov dword ptr [ebp+8],{size};mov dword ptr [ebp+12],{DIALOG_MAGIC};
            lea edi,[ebp+16];'''
        restore += f'restore{dims}:cmp dword ptr [ebp+8],{size};jne release;'
        for offset in range(size - 16, size, 4):
            restore += f'cmp dword ptr [ebp+{offset}],0xa5a5a5a5;jne release;'
        restore += 'lea esi,[ebp+16];'
        for address, count in spans:
            assert count % 4 == 0
            save += f'mov esi,{address};mov ecx,{count//4};rep movsd;'
            restore += f'mov edi,{address};mov ecx,{count//4};rep movsd;'
        save += ("mov eax,0xa5a5a5a5;"
                 "stosd;"
                 "stosd;"
                 "stosd;"
                 "stosd;"
                 "jmp done;")
        restore += 'jmp release;'
    save += (
        f"done:popad;"
        f"popfd;"
        f"push ebx;"
        f"push ecx;"
        f"push edx;"
        f"push esi;"
        f"\n        push edi;"
        f"push ebp;"
        f"jmp {DIALOG_ENTRY+6};"
    )
    restore += (
        "release:mov eax,ebp;"
        "call dword ptr [0x35f4ac];"
        "\n        done:popad;"
        "popfd;"
        "jmp 0x2e43d0;"
    )
    a, b = dialog_encode(DIALOG_CODE, save), dialog_encode(DIALOG_RESTORE, restore)
    assert len(a) <= DIALOG_RESTORE - DIALOG_CODE and len(b) <= DIALOG_STATE - DIALOG_RESTORE
    return [
        (DIALOG_CODE, a), (DIALOG_RESTORE, b),
        (DIALOG_ENTRY, asm(DIALOG_ENTRY, f'jmp {DIALOG_CODE}') + b'\x90'),
        (DIALOG_PRESENT, asm(DIALOG_PRESENT, f'call {DIALOG_RESTORE}'))
    ]


def dialog_setup(write, ram):
    pieces = dialog_bodies()
    if bytes(ram[DIALOG_ENTRY:DIALOG_ENTRY + 6]) == pieces[-2][1]:
        dialog_verify(ram)
        return dict(ranges=[], already_installed=True)
    for address, expected in DIALOG_OLD.items():
        assert bytes(ram[address:address + len(expected)]) == expected, hex(address)
    assert not any(ram[DIALOG_CODE:DIALOG_END]), 'dialog code/state reservation is occupied'
    for address, data in pieces:
        write(address, data)
    return dict(
        ranges=[(a, a + len(b)) for a, b in pieces],
        state=[DIALOG_STATE, 8],
        temporary_heap_bytes=294432
    )


def dialog_verify(ram):
    for address, data in dialog_bodies():
        assert bytes(ram[address:address + len(data)]) == data, hex(address)
    return True


"""Keep the paused HUD intact when the mouse leaves a hover tooltip.

The original mission mouse handler at 2623e4 removes help by redrawing the
bare visor (resource 2ee0000) and marking every widget dirty. Paused missions
do not run that widget repaint. Native cursor presentation can conceal the
cleared logical surface until a modal dialog forces a complete composition.

Freeze tooltip dismissal with the rest of the paused view. On resume the
unchanged original path removes it and schedules the normal widget redraw.
The original dialog also pauses/unpauses the clock without remembering an
existing pause. Preserve that state and its time anchor across the dialog.
No extra render/simulation step or image buffer is needed.
"""
from patch_support import asm

TOOLTIP_CODE = 0x1D2EC00
TOOLTIP_END = 0x1D2EF00
TOOLTIP_PAUSE = TOOLTIP_CODE + 0x100
TOOLTIP_RESUME = TOOLTIP_CODE + 0x180
TOOLTIP_STATE = TOOLTIP_CODE + 0x240  # depth, then 16 (paused, event-pump flag, time anchor) records
TOOLTIP_CAPACITY = 16
TOOLTIP_PAUSE_SITE = 0x24613E
TOOLTIP_RESUME_SITE = 0x24627B
TOOLTIP_SITE = 0x262433
TOOLTIP_CONTINUE = 0x262439
TOOLTIP_SKIP = 0x2624C5
TOOLTIP_OLD = bytes.fromhex('8a2518a93500')  # mov ah,[35a918], tooltip state


def tooltip_bodies():
    body = asm(
        TOOLTIP_CODE, (
            f"pushfd;"
            f"cmp byte ptr [0x35f3f4],0;"
            f"jne paused;"
            f"\n        popfd;"
            f"mov ah,[0x35a918];"
            f"jmp {TOOLTIP_CONTINUE};"
            f"\n        paused:popfd;"
            f"jmp {TOOLTIP_SKIP};"
        )
    )
    pause = asm(
        TOOLTIP_PAUSE, (
            f"pushfd;"
            f"pushad;"
            f"mov ecx,[{TOOLTIP_STATE}];"
            f"inc dword ptr [{TOOLTIP_STATE}];"
            f"\n        cmp ecx,{TOOLTIP_CAPACITY};"
            f"jae done;"
            f"lea edi,[ecx*8+{TOOLTIP_STATE+4}];"
            f"\n        mov al,[0x35f3f4];"
            f"mov [edi],al;"
            f"mov al,[0x35f3fc];"
            f"mov [edi+1],al;"
            f"\n        mov eax,[0x446ae0];"
            f"mov [edi+4],eax;"
            f"\n        done:popad;"
            f"popfd;"
            f"jmp 0x2deb80;"
        )
    )
    resume = asm(
        TOOLTIP_RESUME, (
            f"pushfd;"
            f"pushad;"
            f"mov ecx,[{TOOLTIP_STATE}];"
            f"test ecx,ecx;"
            f"jz original;"
            f"\n        dec ecx;"
            f"mov [{TOOLTIP_STATE}],ecx;"
            f"cmp ecx,{TOOLTIP_CAPACITY};"
            f"jae original;"
            f"\n        lea edi,[ecx*8+{TOOLTIP_STATE+4}];"
            f"cmp byte ptr [edi],0;"
            f"je original;"
            f"\n        mov al,[edi];"
            f"mov [0x35f3f4],al;"
            f"mov al,[edi+1];"
            f"mov [0x35f3fc],al;"
            f"\n        mov eax,[edi+4];"
            f"mov [0x446ae0],eax;"
            f"popad;"
            f"popfd;"
            f"ret;"
            f"\n        original:popad;"
            f"popfd;"
            f"jmp 0x2deba0;"
        )
    )
    assert len(body
               ) <= TOOLTIP_PAUSE - TOOLTIP_CODE and len(pause) <= TOOLTIP_RESUME - TOOLTIP_PAUSE
    assert len(
        resume
    ) <= TOOLTIP_STATE - TOOLTIP_RESUME and TOOLTIP_STATE + 4 + TOOLTIP_CAPACITY * 8 <= TOOLTIP_END
    return [
        (TOOLTIP_CODE, body), (TOOLTIP_PAUSE, pause), (TOOLTIP_RESUME, resume),
        (TOOLTIP_SITE, asm(TOOLTIP_SITE, f'jmp {TOOLTIP_CODE}') + b'\x90'),
        (TOOLTIP_PAUSE_SITE, asm(TOOLTIP_PAUSE_SITE, f'call {TOOLTIP_PAUSE}')),
        (TOOLTIP_RESUME_SITE, asm(TOOLTIP_RESUME_SITE, f'call {TOOLTIP_RESUME}'))
    ]


def tooltip_verify(ram):
    for address, data in tooltip_bodies():
        assert bytes(ram[address:address + len(data)]) == data, hex(address)
    return True


def tooltip_setup(write, ram):
    pieces = tooltip_bodies()
    if bytes(ram[TOOLTIP_SITE:TOOLTIP_SITE + len(TOOLTIP_OLD)]) == dict(pieces)[TOOLTIP_SITE]:
        tooltip_verify(ram)
        return dict(ranges=[], already_installed=True)
    assert bytes(
        ram[TOOLTIP_SITE:TOOLTIP_SITE + len(TOOLTIP_OLD)]
    ) == TOOLTIP_OLD, 'unexpected tooltip handler'
    assert bytes(ram[TOOLTIP_PAUSE_SITE:TOOLTIP_PAUSE_SITE + 5]
                 ) == asm(TOOLTIP_PAUSE_SITE, 'call 0x2deb80')
    assert bytes(ram[TOOLTIP_RESUME_SITE:TOOLTIP_RESUME_SITE + 5]
                 ) == asm(TOOLTIP_RESUME_SITE, 'call 0x2deba0')
    assert not any(ram[TOOLTIP_CODE:TOOLTIP_END]), 'tooltip code reservation is occupied'
    for address, data in pieces:
        write(address, data)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
