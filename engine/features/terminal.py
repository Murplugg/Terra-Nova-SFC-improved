"""Add terminal keyboard navigation, contextual Review keys and the exit sound.

The original callbacks still open documents, mark them read and manage resources.
These helpers connect keyboard actions to that behavior and keep navigation state
within fixed slots shared with the UI and Options features.
"""
import struct
from patch_support import asm as default_asm

ENTRY = 0x1e10000
KEY = 0x1e10100
DRAW = 0x1e11000
OPEN = 0x1e11500
STATE = 0x1e11800
TICK = 0x1e11900
POLL = 0x1e11c00
REPORT_OPEN = 0x1e11d00
TRAMP = 0x1e12f00
END = 0x1e13000
DESCS = (0x43d40c, 0x43d3be, 0x43d370, 0x43d322)


def branch(a, b):
    return b'\xe9' + struct.pack('<i', b - a - 5)


def navigation_bodies(asm=default_asm):
    entry = asm(
        ENTRY, (
            f"pushfd;"
            f"pushad;"
            f"call {KEY};"
            f"test al,al;"
            f"jz pass;"
            f"\n popad;"
            f"popfd;"
            f"mov al,1;"
            f"ret;"
            f"\n pass:popad;"
            f"popfd;"
            f"jmp {TRAMP};"
        )
    )
    key = asm(
        KEY, (
            f"\n mov edi,eax;"
            f"movzx ebx,word ptr [edi+4];"
            f"and ebx,0xffffdcff;"
            f"\n mov edx,ebx;"
            f"and edx,255;"
            f"cmp edx,9;"
            f"jne normalized;"
            f"mov ebx,9;"
            f"\n normalized:\n cmp dword ptr [edi],0x200;"
            f"jne scope;"
            f"\n cmp ebx,[{STATE}];"
            f"jne scope;"
            f"mov dword ptr [{STATE}],0;"
            f"mov dword ptr [{STATE+32}],0;"
            f"\n scope:cmp byte ptr [0x1d0d449],0x69;"
            f"jne ignore;"
            f"\n movzx ebp,word ptr [0x43d46e];"
            f"cmp ebp,23;"
            f"ja ignore;"
            f"\n cmp ebp,11;"
            f"je ignore;"
            f"cmp ebp,12;"
            f"je ignore;"
            f"\n mov eax,[0x446ef0];"
            f"cmp eax,0x446ef8;"
            f"je ignore;"
            f"\n mov edx,[ebp*4+0x35ce14];"
            f"cmp edx,[eax+13];"
            f"jne ignore;"
            f"\n cmp ebx,0x84b;"
            f"je known;"
            f"cmp ebx,0x84d;"
            f"je known;"
            f"\n cmp ebx,8;"
            f"je known;"
            f"cmp ebx,27;"
            f"je known;"
            f"cmp ebx,9;"
            f"je known;"
            f"\n cmp ebp,13;"
            f"jb ignore;"
            f"cmp ebp,20;"
            f"ja ignore;"
            f"\n cmp ebx,0x848;"
            f"je known;"
            f"cmp ebx,0x850;"
            f"je known;"
            f"\n cmp ebx,13;"
            f"jne ignore;"
            f"\n known:cmp dword ptr [edi],0x200;"
            f"je consumed;"
            f"\n cmp dword ptr [edi],0x100;"
            f"jne ignore;"
            f"\n mov edx,[0x35f8dc];"
            f"cmp ebx,[{STATE}];"
            f"jne first;"
            f"\n cmp ebp,14;"
            f"je consumed;"
            f"cmp ebp,17;"
            f"je consumed;"
            f"cmp ebp,19;"
            f"je consumed;"
            f"\n cmp ebx,0x800;"
            f"jb consumed;"
            f"\n mov eax,edx;"
            f"sub eax,[{STATE+4}];"
            f"cmp eax,150;"
            f"jb consumed;"
            f"\n first:mov dword ptr [{STATE+32}],0;"
            f"mov [{STATE}],ebx;"
            f"mov [{STATE+4}],edx;"
            f"inc dword ptr [{STATE+8}];"
            f"\n cmp ebx,9;"
            f"jne non_tab;"
            f"test byte ptr [0x44d290],0x18;"
            f"jnz section_left;"
            f"jmp section_right;"
            f"\n non_tab:cmp ebx,27;"
            f"je back;"
            f"cmp ebx,8;"
            f"je back;"
            f"\n cmp ebx,0x84b;"
            f"je section_left;"
            f"cmp ebx,0x84d;"
            f"je section_right;"
            f"\n xor esi,esi;"
            f"xor ecx,ecx;"
            f"\n cmp ebp,13;"
            f"je mail;"
            f"cmp ebp,14;"
            f"je mail;"
            f"cmp ebp,15;"
            f"je mail;"
            f"\n cmp ebp,16;"
            f"je news;"
            f"cmp ebp,17;"
            f"je news;"
            f"\n cmp ebp,18;"
            f"je library;"
            f"cmp ebp,19;"
            f"je library;"
            f"cmp ebp,20;"
            f"je reports;"
            f"jmp consumed;"
            f"\n mail:mov esi,0x43d40c;"
            f"mov ecx,{STATE+16};"
            f"jmp descriptor;"
            f"\n news:mov esi,0x43d3be;"
            f"mov ecx,{STATE+20};"
            f"jmp descriptor;"
            f"\n library:mov esi,0x43d370;"
            f"mov ecx,{STATE+24};"
            f"jmp descriptor;"
            f"\n reports:mov esi,0x43d322;"
            f"mov ecx,{STATE+28};"
            f"\n descriptor:cmp ebp,13;"
            f"je listing;"
            f"cmp ebp,16;"
            f"je listing;"
            f"cmp ebp,18;"
            f"je listing;"
            f"cmp ebp,20;"
            f"je listing;"
            f"\n cmp ebp,15;"
            f"je consumed;"
            f"\n cmp ebx,0x848;"
            f"je scroll_up;"
            f"cmp ebx,0x850;"
            f"jne consumed;"
            f"\n mov edx,8;"
            f"jmp scroll;"
            f"\n scroll_up:mov edx,7;"
            f"\n scroll:mov [{STATE+32}],ebp;"
            f"mov [{STATE+36}],ebx;"
            f"\n mov eax,[0x35f8dc];"
            f"add eax,100;"
            f"mov [{STATE+40}],eax;"
            f"\n mov eax,esi;"
            f"call 0x2c11b0;"
            f"mov word ptr [0x43d31c],0;"
            f"jmp consumed;"
            f"\n listing:movsx edx,word ptr [esi+8];"
            f"test edx,edx;"
            f"js consumed;"
            f"\n mov eax,[ecx];"
            f"test eax,eax;"
            f"jns not_negative;"
            f"xor eax,eax;"
            f"\n not_negative:cmp eax,edx;"
            f"jle bounded;"
            f"mov eax,edx;"
            f"\n bounded:cmp ebx,13;"
            f"je open_item;"
            f"\n cmp ebx,0x848;"
            f"je select_up;"
            f"cmp ebx,0x850;"
            f"jne consumed;"
            f"\n cmp eax,edx;"
            f"jge consumed;"
            f"inc eax;"
            f"jmp select;"
            f"\n select_up:test eax,eax;"
            f"jz consumed;"
            f"dec eax;"
            f"\n select:mov [ecx],eax;"
            f"\n movsx edx,word ptr [esi+6];"
            f"cmp eax,edx;"
            f"jge below_top;"
            f"\n mov [esi+6],ax;"
            f"jmp redraw;"
            f"\n below_top:movsx ebx,word ptr [esi+2];"
            f"add ebx,edx;"
            f"cmp eax,ebx;"
            f"jle redraw;"
            f"\n sub eax,ebx;"
            f"add eax,edx;"
            f"mov [esi+6],ax;"
            f"\n redraw:mov eax,ebp;"
            f"call 0x2b6cdc;"
            f"call dword ptr [ebp*4+0x35cda0];"
            f"call 0x2b60cc;"
            f"jmp consumed;"
            f"\n open_item:mov [ecx],eax;"
            f"movsx edx,word ptr [esi+6];"
            f"sub eax,edx;"
            f"add eax,9;"
            f"\n cmp eax,[0x43cdd4];"
            f"jg consumed;"
            f"\n lea edx,[eax*8+0x43cc40];"
            f"movzx eax,word ptr [edx];"
            f"movzx ebx,word ptr [edx+2];"
            f"inc eax;"
            f"inc ebx;"
            f"\n sub esp,12;"
            f"mov dword ptr [esp],1;"
            f"mov dword ptr [esp+4],0;"
            f"\n mov word ptr [esp+8],ax;"
            f"mov word ptr [esp+10],bx;"
            f"mov eax,esp;"
            f"\n call dword ptr [ebp*4+0x35ce14];"
            f"add esp,12;"
            f"jmp consumed;"
            f"\n section_left:movzx eax,byte ptr [ebp+0x35cfae];"
            f"dec eax;"
            f"cmp eax,1;"
            f"jge section;"
            f"mov eax,5;"
            f"jmp section;"
            f"\n section_right:movzx eax,byte ptr [ebp+0x35cfae];"
            f"inc eax;"
            f"cmp eax,5;"
            f"jle section;"
            f"mov eax,1;"
            f"\n section:movsx eax,word ptr [eax*2+0x35cfc4];"
            f"call 0x2b60b4;"
            f"jmp consumed;"
            f"\n back:mov eax,21;"
            f"cmp ebp,22;"
            f"je transition;"
            f"cmp ebp,23;"
            f"je transition;"
            f"\n mov eax,13;"
            f"cmp ebp,14;"
            f"je transition;"
            f"cmp ebp,15;"
            f"je transition;"
            f"\n mov eax,16;"
            f"cmp ebp,17;"
            f"je transition;"
            f"\n mov eax,18;"
            f"cmp ebp,19;"
            f"je transition;"
            f"\n mov eax,20;"
            f"cmp ebp,20;"
            f"jg transition;"
            f"\n xor eax,eax;"
            f"test ebp,ebp;"
            f"jz exit_terminal;"
            f"cmp ebp,10;"
            f"jbe transition;"
            f"\n exit_terminal:mov eax,-1;"
            f"\n transition:call 0x2b60b4;"
            f"\n consumed:mov eax,1;"
            f"ret;"
            f"\n ignore:xor eax,eax;"
            f"ret;"
            f"\n "
        )
    )
    # Preserve the exact original return state while keeping the descriptor for
    # the small focus marker drawn in the same canvas as the original list.
    draw = asm(
        DRAW, (
            f"push eax;"
            f"call {TRAMP+32};"
            f"xchg eax,[esp];"
            f"pushfd;"
            f"pushad;"
            f"\n mov esi,eax;"
            f"mov edi,{STATE+16};"
            f"cmp esi,0x43d40c;"
            f"je selected;"
            f"\n mov edi,{STATE+20};"
            f"cmp esi,0x43d3be;"
            f"je selected;"
            f"\n mov edi,{STATE+24};"
            f"cmp esi,0x43d370;"
            f"je selected;"
            f"\n mov edi,{STATE+28};"
            f"cmp esi,0x43d322;"
            f"jne draw_done;"
            f"\n selected:movsx edx,word ptr [esi+8];"
            f"test edx,edx;"
            f"js draw_done;"
            f"\n mov eax,[edi];"
            f"movsx ebx,word ptr [esi+6];"
            f"cmp eax,ebx;"
            f"jge top_ok;"
            f"mov eax,ebx;"
            f"\n top_ok:movsx ecx,word ptr [esi+2];"
            f"add ecx,ebx;"
            f"cmp eax,ecx;"
            f"jle view_ok;"
            f"mov eax,ecx;"
            f"\n view_ok:cmp eax,edx;"
            f"jle total_ok;"
            f"mov eax,edx;"
            f"\n total_ok:mov [edi],eax;"
            f"sub eax,ebx;"
            f"js draw_done;"
            f"imul ebp,eax,14;"
            f"add ebp,119;"
            f"\n mov esi,[0x44b1a0];"
            f"mov edi,[esi+16];"
            f"mov dword ptr [esi+16],0xf2;"
            f"\n mov eax,54;"
            f"mov edx,ebp;"
            f"mov ebx,59;"
            f"call 0x2ed5a0;"
            f"\n mov eax,54;"
            f"lea edx,[ebp-1];"
            f"mov ebx,58;"
            f"call 0x2ed5a0;"
            f"\n mov eax,54;"
            f"lea edx,[ebp+1];"
            f"mov ebx,58;"
            f"call 0x2ed5a0;"
            f"\n mov [esi+16],edi;"
            f"\n draw_done:popad;"
            f"popfd;"
            f"pop eax;"
            f"ret;"
        )
    )
    opened = asm(
        OPEN, (
            f"pushfd;"
            f"pushad;"
            f"\n mov ecx,{STATE+16};"
            f"cmp eax,0x43d40c;"
            f"je remember;"
            f"\n mov ecx,{STATE+20};"
            f"cmp eax,0x43d3be;"
            f"je remember;"
            f"\n mov ecx,{STATE+24};"
            f"cmp eax,0x43d370;"
            f"jne open_done;"
            f"\n remember:movsx ebx,word ptr [eax+6];"
            f"add ebx,edx;"
            f"sub ebx,9;"
            f"mov [ecx],ebx;"
            f"\n open_done:popad;"
            f"popfd;"
            f"jmp {TRAMP+64};"
        )
    )
    report_open = asm(
        REPORT_OPEN, (
            f"pushfd;"
            f"pushad;"
            f"movsx ebx,word ptr [eax+6];"
            f"add ebx,edx;"
            f"sub ebx,9;"
            f"mov [{STATE+28}],ebx;"
            f"popad;"
            f"popfd;"
            f"jmp {TRAMP+96};"
        )
    )
    # Original UI polls the mouse each iteration, even while stationary. Repeat
    # from this same clock/poll cadence as mouse-held scrolling, independently of
    # Windows' keyboard repeat delay. Native focus loss clears PRESSED.
    tick = asm(
        TICK, (
            f"cmp dword ptr [{STATE+32}],0;"
            f"je done;"
            f"\n cmp byte ptr [0x1d0d449],0x69;"
            f"jne cancel;"
            f"\n movzx ebp,word ptr [0x43d46e];"
            f"cmp ebp,[{STATE+32}];"
            f"jne cancel;"
            f"\n mov eax,[0x446ef0];"
            f"cmp eax,0x446ef8;"
            f"je cancel;"
            f"\n mov edx,[ebp*4+0x35ce14];"
            f"cmp edx,[eax+13];"
            f"jne cancel;"
            f"\n mov edx,7;"
            f"mov ecx,0xc8;"
            f"cmp dword ptr [{STATE+36}],0x848;"
            f"je pressed;"
            f"\n mov edx,8;"
            f"mov ecx,0xd0;"
            f"\n pressed:cmp byte ptr [ecx+0x1d0f500],0;"
            f"jne held;"
            f"\n sub ecx,128;"
            f"cmp byte ptr [ecx+0x1d0f500],0;"
            f"je cancel;"
            f"\n held:\n mov ebx,[0x35f8dc];"
            f"sub ebx,[{STATE+40}];"
            f"js done;"
            f"\n mov eax,0x43d40c;"
            f"cmp ebp,14;"
            f"je scroll;"
            f"\n mov eax,0x43d3be;"
            f"cmp ebp,17;"
            f"je scroll;"
            f"\n mov eax,0x43d370;"
            f"cmp ebp,19;"
            f"jne cancel;"
            f"\n scroll:mov ebx,[0x35f8dc];"
            f"add ebx,100;"
            f"mov [{STATE+40}],ebx;"
            f"\n call 0x2c11b0;"
            f"mov word ptr [0x43d31c],0;"
            f"inc dword ptr [{STATE+44}];"
            f"\n done:ret;"
            f"\n cancel:mov dword ptr [{STATE+32}],0;"
            f"mov dword ptr [{STATE}],0;"
            f"ret;"
        )
    )
    poll = asm(
        POLL, (
            f"pushfd;"
            f"pushad;"
            f"call {TICK};"
            f"popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x2e5051;"
        )
    )
    assert len(tick) < 0x300 and len(poll) < 0x100 and len(report_open) < 0x100
    assert len(key) < 0xf00 and len(draw) < 0x500 and len(opened) < 0x300
    return [
        (ENTRY, entry), (KEY, key), (DRAW, draw), (OPEN, opened), (TICK, tick), (POLL, poll),
        (REPORT_OPEN, report_open),
        (TRAMP, bytes.fromhex('53515289c3') + branch(TRAMP + 5, 0x2e3989)),
        (TRAMP + 32, bytes.fromhex('5156575583ec10') + branch(TRAMP + 39, 0x2c0ad3)),
        (TRAMP + 64, bytes.fromhex('56575583ec04') + branch(TRAMP + 70, 0x2c0c7e)),
        (TRAMP + 96, bytes.fromhex('5383ea09668b5806') + branch(TRAMP + 104, 0x2c0ea4))
    ]


def hooks(asm=default_asm):
    return [
        (0x2e3984, branch(0x2e3984, ENTRY), bytes.fromhex('53515289c3')),
        (0x2c0acc, branch(0x2c0acc, DRAW) + b'\x90\x90', bytes.fromhex('5156575583ec10')),
        (0x2c0c78, branch(0x2c0c78, OPEN) + b'\x90', bytes.fromhex('56575583ec04')),
        (0x2e504c, branch(0x2e504c, POLL), bytes.fromhex('5351525657')),
        (0x2c0e9c, branch(0x2c0e9c, REPORT_OPEN) + b'\x90' * 3, bytes.fromhex('5383ea09668b5806'))
    ]


REVIEW = 0x1fca000
EXIT = 0x1f75600
EXIT_SITES = (0x1e10465, 0x1e104b8)
RESERVATIONS = ((ENTRY, END), (REVIEW, REVIEW + 0x100), (EXIT, EXIT + 0x100))


def review_bodies(asm=default_asm):
    b = asm(
        REVIEW, (
            f"pushfd;"
            f"pushad;"
            f"cmp byte ptr [0x1d0d449],0x69;"
            f"jne pass;"
            f"\n movzx ecx,word ptr [0x43d46e];"
            f"cmp ecx,1;"
            f"jb pass;"
            f"cmp ecx,10;"
            f"ja pass;"
            f"\n mov edx,[0x446ef0];"
            f"cmp edx,0x446ef8;"
            f"je pass;"
            f"mov ebx,[ecx*4+0x35ce14];"
            f"cmp [edx+13],ebx;"
            f"jne pass;"
            f"\n movzx edx,word ptr [eax+4];"
            f"and edx,0xffffdcff;"
            f"cmp edx,0x84b;"
            f"je original;"
            f"cmp edx,0x84d;"
            f"je original;"
            f"and edx,255;"
            f"cmp edx,9;"
            f"je original;"
            f"\n pass:popad;"
            f"popfd;"
            f"jmp {KEY};"
            f"\n original:popad;"
            f"popfd;"
            f"xor eax,eax;"
            f"ret;"
        )
    )
    entry = asm(
        ENTRY, (
            f"pushfd;"
            f"pushad;"
            f"call {REVIEW};"
            f"test al,al;"
            f"jz pass;"
            f"popad;"
            f"popfd;"
            f"mov al,1;"
            f"ret;"
            f"pass:popad;"
            f"popfd;"
            f"jmp {TRAMP};"
        )
    )
    return [(REVIEW, b), (ENTRY, entry)]


def exit_sound(asm=default_asm):
    return asm(
        EXIT, (
            "cmp eax,-1;"
            "jne transition;"
            "pushfd;"
            "pushad;"
            "\n push 0;"
            "push 0x40;"
            "mov eax,0x786;"
            "mov ebx,0x40;"
            "push -1;"
            "mov ecx,1;"
            "xor edx,edx;"
            "call 0x247b60;"
            "\n popad;"
            "popfd;"
            "transition:jmp 0x2b60b4;"
        )
    )


def exit_bodies(asm=default_asm):
    # Both transitions share the helper; only destination -1 makes a sound.
    baseline = dict(navigation_bodies(asm))[KEY]
    for site in EXIT_SITES:
        assert baseline[site - KEY:site - KEY + 5] == asm(site, 'call 0x2b60b4')
    return [(EXIT, exit_sound(asm)), *[(a, asm(a, f'call {EXIT}')) for a in EXIT_SITES]]


def bodies(asm=default_asm):
    pieces = dict(navigation_bodies(asm))
    pieces.update(review_bodies(asm))
    key = bytearray(pieces[KEY])
    for a, b in exit_bodies(asm)[1:]:
        key[a - KEY:a - KEY + len(b)] = b
    pieces[KEY] = bytes(key)
    pieces[EXIT] = exit_sound(asm)
    for a, b in pieces.items():
        assert any(start <= a and a + len(b) <= end for start, end in RESERVATIONS), hex(a)
    return list(pieces.items())


def install(write, ram, asm=default_asm):
    """Check each terminal hook and owned range before writing any replacements.

    EXIT owns a 256-byte slot within the shared UI reservation. REVIEW ends at the
    wrist-options reservation, so those neighboring bytes must remain untouched.
    """
    pieces = bodies(asm)
    edits = hooks(asm)
    for a, b, old in edits:
        assert bytes(ram[a:a + len(old)]) == old, (hex(a), 'terminal hook')
    for a, end in RESERVATIONS:
        assert not any(ram[a:end]), (hex(a), 'terminal reservation')
    pieces += [(a, b) for a, b, _ in edits]
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])


RETAINED_ENTRY = 0x1dfd000

RETAINED_KEY = 0x1dfd100

RETAINED_DRAW = 0x1dfe000

RETAINED_OPEN = 0x1dfe500

RETAINED_STATE = 0x1dfe800

RETAINED_TRAMP = 0x1dfef00

RETAINED_END = 0x1dff000

RETAINED_DESCS = (0x43d40c, 0x43d3be, 0x43d370)


def retained_branch(a, b):
    return b'\xe9' + struct.pack('<i', b - a - 5)


def retained_bodies(asm):
    entry = asm(
        RETAINED_ENTRY, (
            f"pushfd;"
            f"pushad;"
            f"call {RETAINED_KEY};"
            f"test al,al;"
            f"jz pass;"
            f"\n popad;"
            f"popfd;"
            f"mov al,1;"
            f"ret;"
            f"\n pass:popad;"
            f"popfd;"
            f"jmp {RETAINED_TRAMP};"
        )
    )
    key = asm(
        RETAINED_KEY, (
            f"\n mov edi,eax;"
            f"movzx ebx,word ptr [edi+4];"
            f"and ebx,0xffffdcff;"
            f"\n cmp dword ptr [edi],0x200;"
            f"jne scope;"
            f"\n cmp ebx,[{RETAINED_STATE}];"
            f"jne scope;"
            f"mov dword ptr [{RETAINED_STATE}],0;"
            f"\n scope:cmp byte ptr [0x1d0d449],0x69;"
            f"jne ignore;"
            f"\n movzx ebp,word ptr [0x43d46e];"
            f"cmp ebp,23;"
            f"ja ignore;"
            f"\n cmp ebp,11;"
            f"je ignore;"
            f"cmp ebp,12;"
            f"je ignore;"
            f"\n mov eax,[0x446ef0];"
            f"cmp eax,0x446ef8;"
            f"je ignore;"
            f"\n mov edx,[ebp*4+0x35ce14];"
            f"cmp edx,[eax+13];"
            f"jne ignore;"
            f"\n cmp ebx,0x84b;"
            f"je known;"
            f"cmp ebx,0x84d;"
            f"je known;"
            f"\n cmp ebx,8;"
            f"je known;"
            f"cmp ebx,27;"
            f"je known;"
            f"\n cmp ebp,13;"
            f"jb ignore;"
            f"cmp ebp,19;"
            f"ja ignore;"
            f"\n cmp ebx,0x848;"
            f"je known;"
            f"cmp ebx,0x850;"
            f"je known;"
            f"\n cmp ebx,13;"
            f"jne ignore;"
            f"\n known:cmp dword ptr [edi],0x200;"
            f"je consumed;"
            f"\n cmp dword ptr [edi],0x100;"
            f"jne ignore;"
            f"\n mov edx,[0x35f8dc];"
            f"cmp ebx,[{RETAINED_STATE}];"
            f"jne first;"
            f"\n cmp ebx,0x800;"
            f"jb consumed;"
            f"\n mov eax,edx;"
            f"sub eax,[{RETAINED_STATE+4}];"
            f"cmp eax,150;"
            f"jb consumed;"
            f"\n first:mov [{RETAINED_STATE}],ebx;"
            f"mov [{RETAINED_STATE+4}],edx;"
            f"inc dword ptr [{RETAINED_STATE+8}];"
            f"\n cmp ebx,27;"
            f"je back;"
            f"cmp ebx,8;"
            f"je back;"
            f"\n cmp ebx,0x84b;"
            f"je section_left;"
            f"cmp ebx,0x84d;"
            f"je section_right;"
            f"\n xor esi,esi;"
            f"xor ecx,ecx;"
            f"\n cmp ebp,13;"
            f"je mail;"
            f"cmp ebp,14;"
            f"je mail;"
            f"cmp ebp,15;"
            f"je mail;"
            f"\n cmp ebp,16;"
            f"je news;"
            f"cmp ebp,17;"
            f"je news;"
            f"\n cmp ebp,18;"
            f"je library;"
            f"cmp ebp,19;"
            f"je library;"
            f"jmp consumed;"
            f"\n mail:mov esi,0x43d40c;"
            f"mov ecx,{RETAINED_STATE+16};"
            f"jmp descriptor;"
            f"\n news:mov esi,0x43d3be;"
            f"mov ecx,{RETAINED_STATE+20};"
            f"jmp descriptor;"
            f"\n library:mov esi,0x43d370;"
            f"mov ecx,{RETAINED_STATE+24};"
            f"\n descriptor:cmp ebp,13;"
            f"je listing;"
            f"cmp ebp,16;"
            f"je listing;"
            f"cmp ebp,18;"
            f"je listing;"
            f"\n cmp ebp,15;"
            f"je consumed;"
            f"\n cmp ebx,0x848;"
            f"je scroll_up;"
            f"cmp ebx,0x850;"
            f"jne consumed;"
            f"\n mov edx,8;"
            f"jmp scroll;"
            f"\n scroll_up:mov edx,7;"
            f"\n scroll:mov eax,esi;"
            f"call 0x2c11b0;"
            f"mov word ptr [0x43d31c],0;"
            f"jmp consumed;"
            f"\n listing:movsx edx,word ptr [esi+8];"
            f"test edx,edx;"
            f"js consumed;"
            f"\n mov eax,[ecx];"
            f"test eax,eax;"
            f"jns not_negative;"
            f"xor eax,eax;"
            f"\n not_negative:cmp eax,edx;"
            f"jle bounded;"
            f"mov eax,edx;"
            f"\n bounded:cmp ebx,13;"
            f"je open_item;"
            f"\n cmp ebx,0x848;"
            f"je select_up;"
            f"cmp ebx,0x850;"
            f"jne consumed;"
            f"\n cmp eax,edx;"
            f"jge consumed;"
            f"inc eax;"
            f"jmp select;"
            f"\n select_up:test eax,eax;"
            f"jz consumed;"
            f"dec eax;"
            f"\n select:mov [ecx],eax;"
            f"\n movsx edx,word ptr [esi+6];"
            f"cmp eax,edx;"
            f"jge below_top;"
            f"\n mov [esi+6],ax;"
            f"jmp redraw;"
            f"\n below_top:movsx ebx,word ptr [esi+2];"
            f"add ebx,edx;"
            f"cmp eax,ebx;"
            f"jle redraw;"
            f"\n sub eax,ebx;"
            f"add eax,edx;"
            f"mov [esi+6],ax;"
            f"\n redraw:mov eax,ebp;"
            f"call 0x2b6cdc;"
            f"call dword ptr [ebp*4+0x35cda0];"
            f"call 0x2b60cc;"
            f"jmp consumed;"
            f"\n open_item:mov [ecx],eax;"
            f"movsx edx,word ptr [esi+6];"
            f"sub eax,edx;"
            f"add eax,9;"
            f"\n cmp eax,[0x43cdd4];"
            f"jg consumed;"
            f"\n lea edx,[eax*8+0x43cc40];"
            f"movzx eax,word ptr [edx];"
            f"movzx ebx,word ptr [edx+2];"
            f"inc eax;"
            f"inc ebx;"
            f"\n sub esp,12;"
            f"mov dword ptr [esp],1;"
            f"mov dword ptr [esp+4],0;"
            f"\n mov word ptr [esp+8],ax;"
            f"mov word ptr [esp+10],bx;"
            f"mov eax,esp;"
            f"\n call dword ptr [ebp*4+0x35ce14];"
            f"add esp,12;"
            f"jmp consumed;"
            f"\n section_left:movzx eax,byte ptr [ebp+0x35cfae];"
            f"dec eax;"
            f"cmp eax,1;"
            f"jge section;"
            f"mov eax,5;"
            f"jmp section;"
            f"\n section_right:movzx eax,byte ptr [ebp+0x35cfae];"
            f"inc eax;"
            f"cmp eax,5;"
            f"jle section;"
            f"mov eax,1;"
            f"\n section:movsx eax,word ptr [eax*2+0x35cfc4];"
            f"call 0x2b60b4;"
            f"jmp consumed;"
            f"\n back:mov eax,13;"
            f"cmp ebp,14;"
            f"je transition;"
            f"cmp ebp,15;"
            f"je transition;"
            f"\n mov eax,16;"
            f"cmp ebp,17;"
            f"je transition;"
            f"\n mov eax,18;"
            f"cmp ebp,19;"
            f"je transition;"
            f"\n mov eax,20;"
            f"cmp ebp,20;"
            f"jg transition;"
            f"\n xor eax,eax;"
            f"test ebp,ebp;"
            f"jz exit_terminal;"
            f"cmp ebp,10;"
            f"jbe transition;"
            f"\n exit_terminal:mov eax,-1;"
            f"\n transition:call 0x2b60b4;"
            f"\n consumed:mov eax,1;"
            f"ret;"
            f"\n ignore:xor eax,eax;"
            f"ret;"
            f"\n "
        )
    )
    # Preserve the exact original return state while keeping the descriptor for
    # the small focus marker drawn in the same canvas as the original list.
    draw = asm(
        RETAINED_DRAW, (
            f"push eax;"
            f"call {RETAINED_TRAMP+32};"
            f"xchg eax,[esp];"
            f"pushfd;"
            f"pushad;"
            f"\n mov esi,eax;"
            f"mov edi,{RETAINED_STATE+16};"
            f"cmp esi,0x43d40c;"
            f"je selected;"
            f"\n mov edi,{RETAINED_STATE+20};"
            f"cmp esi,0x43d3be;"
            f"je selected;"
            f"\n mov edi,{RETAINED_STATE+24};"
            f"cmp esi,0x43d370;"
            f"jne draw_done;"
            f"\n selected:movsx edx,word ptr [esi+8];"
            f"test edx,edx;"
            f"js draw_done;"
            f"\n mov eax,[edi];"
            f"movsx ebx,word ptr [esi+6];"
            f"cmp eax,ebx;"
            f"jge top_ok;"
            f"mov eax,ebx;"
            f"\n top_ok:movsx ecx,word ptr [esi+2];"
            f"add ecx,ebx;"
            f"cmp eax,ecx;"
            f"jle view_ok;"
            f"mov eax,ecx;"
            f"\n view_ok:cmp eax,edx;"
            f"jle total_ok;"
            f"mov eax,edx;"
            f"\n total_ok:mov [edi],eax;"
            f"sub eax,ebx;"
            f"js draw_done;"
            f"imul ebp,eax,14;"
            f"add ebp,119;"
            f"\n mov esi,[0x44b1a0];"
            f"mov edi,[esi+16];"
            f"mov dword ptr [esi+16],0xf2;"
            f"\n mov eax,54;"
            f"mov edx,ebp;"
            f"mov ebx,59;"
            f"call 0x2ed5a0;"
            f"\n mov eax,54;"
            f"lea edx,[ebp-1];"
            f"mov ebx,58;"
            f"call 0x2ed5a0;"
            f"\n mov eax,54;"
            f"lea edx,[ebp+1];"
            f"mov ebx,58;"
            f"call 0x2ed5a0;"
            f"\n mov [esi+16],edi;"
            f"\n draw_done:popad;"
            f"popfd;"
            f"pop eax;"
            f"ret;"
        )
    )
    opened = asm(
        RETAINED_OPEN, (
            f"pushfd;"
            f"pushad;"
            f"\n mov ecx,{RETAINED_STATE+16};"
            f"cmp eax,0x43d40c;"
            f"je remember;"
            f"\n mov ecx,{RETAINED_STATE+20};"
            f"cmp eax,0x43d3be;"
            f"je remember;"
            f"\n mov ecx,{RETAINED_STATE+24};"
            f"cmp eax,0x43d370;"
            f"jne open_done;"
            f"\n remember:movsx ebx,word ptr [eax+6];"
            f"add ebx,edx;"
            f"sub ebx,9;"
            f"mov [ecx],ebx;"
            f"\n open_done:popad;"
            f"popfd;"
            f"jmp {RETAINED_TRAMP+64};"
        )
    )
    assert len(key) < 0xf00 and len(draw) < 0x500 and len(opened) < 0x300
    return [
        (RETAINED_ENTRY, entry), (RETAINED_KEY, key), (RETAINED_DRAW, draw),
        (RETAINED_OPEN, opened),
        (
            RETAINED_TRAMP,
            bytes.fromhex('53515289c3') + retained_branch(RETAINED_TRAMP + 5, 0x2e3989)
        ),
        (
            RETAINED_TRAMP + 32,
            bytes.fromhex('5156575583ec10') + retained_branch(RETAINED_TRAMP + 39, 0x2c0ad3)
        ),
        (
            RETAINED_TRAMP + 64,
            bytes.fromhex('56575583ec04') + retained_branch(RETAINED_TRAMP + 70, 0x2c0c7e)
        )
    ]
