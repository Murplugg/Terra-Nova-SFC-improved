"""FPS preference, Options checkbox, and a small native-pixel display."""
from patch_support import asm

BASE = 0x1f75500
DRAW = BASE + 0x400
EVENT = BASE + 0x600
ACCEPT = BASE + 0x800
CLOSE = BASE + 0x880
POST = BASE + 0x900
FPS = BASE + 0xa00
GLYPH = BASE + 0xd00
from features.option_contracts import FPS as preference

INIT = preference.init
SAVE = preference.save
STATE = preference.state
STATE_SIZE = preference.size
TEXT = BASE + 0x2600
FONT = BASE + 0x2700


# State: initialized, enabled, pending, options open, timer, frame count, value,
# profile-read/write pointers. Path is constructed from this instance's game root.
def bodies(imports, postsite):
    from features.input_views import api_slots
    api_slots(imports)
    out = []

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    labels = {}
    raw = bytearray()
    for k, v in [
        ('dll', 'kernel32.dll'), ('read', 'GetPrivateProfileIntA'),
        ('write', 'WritePrivateProfileStringA'), ('section', 'Display'), ('key', 'ShowFPS'),
        ('file', 'TNHR.INI'), ('label', 'SHOW FPS'), ('zero', '0'), ('one', '1')
    ]:
        labels[k] = TEXT + len(raw)
        raw += v.encode() + b'\0'
    out.append((TEXT, bytes(raw)))
    emit(
        INIT, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [{STATE}],1;"
            f"je done;"
            f"\n push {labels['dll']};"
            f"call dword ptr [{imports['GetModuleHandleA']}];"
            f"test eax,eax;"
            f"jz done;"
            f"mov ebp,eax;"
            f"\n push {labels['read']};"
            f"push ebp;"
            f"call dword ptr [{imports['GetProcAddress']}];"
            f"test eax,eax;"
            f"jz done;"
            f"mov [{STATE+28}],eax;"
            f"\n push {labels['write']};"
            f"push ebp;"
            f"call dword ptr [{imports['GetProcAddress']}];"
            f"test eax,eax;"
            f"jz done;"
            f"mov [{STATE+32}],eax;"
            f"\n cld;"
            f"mov esi,0x1d08400;"
            f"mov edi,{STATE+64};"
            f"mov ecx,255;"
            f"\n path:lodsb;"
            f"test al,al;"
            f"jz suffix;"
            f"stosb;"
            f"loop path;"
            f"jmp done;"
            f"\n suffix:mov esi,{labels['file']};"
            f"copy:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jnz copy;"
            f"\n push {STATE+64};"
            f"push 0;"
            f"push {labels['key']};"
            f"push {labels['section']};"
            f"call dword ptr [{STATE+28}];"
            f"\n and eax,1;"
            f"mov [{STATE+4}],eax;"
            f"mov dword ptr [{STATE}],1;"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x200
    )
    emit(
        SAVE, (
            f"pushfd;"
            f"pushad;"
            f"call {INIT};"
            f"cmp dword ptr [{STATE}],1;"
            f"jne done;"
            f"\n mov eax,[{STATE+8}];"
            f"mov [{STATE+4}],eax;"
            f"mov edx,{labels['zero']};"
            f"test eax,eax;"
            f"jz value;"
            f"mov edx,{labels['one']};"
            f"\n value:push {STATE+64};"
            f"push edx;"
            f"push {labels['key']};"
            f"push {labels['section']};"
            f"call dword ptr [{STATE+32}];"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )
    emit(
        DRAW, (
            f"call 0x2cac54;"
            f"pushfd;"
            f"pushad;"
            f"call {INIT};"
            f"cmp dword ptr [{STATE+12}],1;"
            f"je draw;"
            f"\n mov eax,[{STATE+4}];"
            f"mov [{STATE+8}],eax;"
            f"mov dword ptr [{STATE+12}],1;"
            f"\n draw:mov esi,[0x44b1a0];"
            f"push dword ptr [esi+0x10];"
            f"push dword ptr [esi+0x18];"
            f"\n mov dword ptr [esi+0x10],0;"
            f"mov eax,228;"
            f"mov edx,388;"
            f"mov ebx,420;"
            f"mov ecx,410;"
            f"mov edi,[0x44b194];"
            f"call dword ptr [edi+0x40];"
            f"\n mov dword ptr [esi+0x10],0xf7;"
            f"mov eax,232;"
            f"mov edx,392;"
            f"mov ebx,242;"
            f"mov ecx,402;"
            f"call dword ptr [edi+0x48];"
            f"\n cmp dword ptr [{STATE+8}],0;"
            f"je label;"
            f"mov eax,234;"
            f"mov edx,394;"
            f"mov ebx,240;"
            f"mov ecx,400;"
            f"call dword ptr [edi+0x40];"
            f"\n label:mov eax,0x164;"
            f"call 0x2eb380;"
            f"mov [esi+0x18],eax;"
            f"mov edx,{labels['label']};"
            f"mov ebx,248;"
            f"mov ecx,392;"
            f"call dword ptr [edi+0x4ec];"
            f"mov eax,0x164;"
            f"call 0x2eb3f4;"
            f"\n pop dword ptr [esi+0x18];"
            f"pop dword ptr [esi+0x10];"
            f"popad;"
            f"popfd;"
            f"ret;"
        ), 0x200
    )
    emit(0x2ca9b4, f'call {DRAW}', 5)
    emit(0x2cab9d, f'call {DRAW}', 5)
    emit(
        EVENT, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [eax],1;"
            f"jne pass;"
            f"\n movsx ecx,word ptr [eax+8];"
            f"cmp ecx,228;"
            f"jl pass;"
            f"cmp ecx,420;"
            f"jge pass;"
            f"\n movsx ecx,word ptr [eax+10];"
            f"cmp ecx,388;"
            f"jl pass;"
            f"cmp ecx,410;"
            f"jge pass;"
            f"\n xor dword ptr [{STATE+8}],1;"
            f"call 0x2e4b1c;"
            f"mov eax,0x446f78;"
            f"call {DRAW};"
            f"mov eax,0x446fb8;"
            f"call 0x2e43d0;"
            f"call 0x2e4b78;"
            f"\n push 0;"
            f"push 0x40;"
            f"mov eax,0x7cc;"
            f"mov ebx,0x28;"
            f"push 0x40;"
            f"mov ecx,1;"
            f"xor edx,edx;"
            f"call 0x247b60;"
            f"\n popad;"
            f"popfd;"
            f"mov al,1;"
            f"ret;"
            f"\n pass:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x2ca455;"
        ), 0x200
    )
    emit(0x2ca450, f'jmp {EVENT}', 5)
    emit(ACCEPT, f'call {SAVE};jmp 0x2ca1e4;', 0x80)
    emit(0x2cbbdc, f'call {ACCEPT}', 5)
    emit(
        CLOSE, (
            f"pushfd;"
            f"mov dword ptr [{STATE+12}],0;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"sub esp,12;"
            f"jmp 0x2cbc0e;"
        ), 0x80
    )
    out.append((0x2cbc08, asm(0x2cbc08, f'jmp {CLOSE}') + b'\x90'))
    emit(
        POST, (
            f"call {BASE+0x1600};"
            f"call 0x1fd3000;"
            f"pushfd;"
            f"pushad;"
            f"call {FPS};"
            f"popad;"
            f"popfd;"
            f"ret;"
        ), 0x100
    )
    emit(postsite, f'call {POST}', 5)
    # Count distinct completed world frames; cursor recompositions do not count.
    # Painting happens after the HUD merge and is absent from menus and movies.
    emit(
        FPS, (
            f"call {INIT};"
            f"cmp dword ptr [{STATE+4}],0;"
            f"je done;"
            f"\n cmp byte ptr [0x1d0d449],0x6b;"
            f"jne done;"
            f"\n mov eax,[0x1d0f300];"
            f"mov ebx,eax;"
            f"sub eax,[{STATE+16}];"
            f"cmp eax,1000;"
            f"jb count;"
            f"\n cmp eax,3000;"
            f"ja reset;"
            f"mov ecx,eax;"
            f"mov eax,[{STATE+20}];"
            f"imul eax,eax,1000;"
            f"xor edx,edx;"
            f"div ecx;"
            f"\n cmp eax,999;"
            f"jbe store;"
            f"mov eax,999;"
            f"store:mov [{STATE+24}],eax;"
            f"\n reset:mov [{STATE+16}],ebx;"
            f"mov dword ptr [{STATE+20}],0;"
            f"\n count:mov eax,[0x35f400];"
            f"cmp eax,[{STATE+40}];"
            f"je paint;"
            f"mov [{STATE+40}],eax;"
            f"inc dword ptr [{STATE+20}];"
            f"paint:\n mov edi,0x68500000+942*1280+1160;"
            f"mov ebp,16;"
            f"xor eax,eax;"
            f"\n clear:mov ecx,112;"
            f"rep stosb;"
            f"add edi,1168;"
            f"dec ebp;"
            f"jnz clear;"
            f"\n mov esi,0x9aa4e8;"
            f"xor ecx,ecx;"
            f"xor ebx,ebx;"
            f"xor edx,edx;"
            f"\n palette:movzx eax,byte ptr [esi];"
            f"movzx ebp,byte ptr [esi+1];"
            f"add eax,ebp;"
            f"movzx ebp,byte ptr [esi+2];"
            f"add eax,ebp;"
            f"\n cmp eax,edx;"
            f"jbe next;"
            f"mov edx,eax;"
            f"mov ebx,ecx;"
            f"next:add esi,3;"
            f"inc ecx;"
            f"cmp ecx,256;"
            f"jb palette;"
            f"\n mov [{STATE+36}],ebx;"
            f"\n mov eax,[{STATE+24}];"
            f"xor edx,edx;"
            f"mov ecx,100;"
            f"div ecx;"
            f"push edx;"
            f"mov edi,0x68500000+943*1280+1164;"
            f"call {GLYPH};"
            f"pop eax;"
            f"\n xor edx,edx;"
            f"mov ecx,10;"
            f"div ecx;"
            f"push edx;"
            f"add edi,12;"
            f"call {GLYPH};"
            f"pop eax;"
            f"add edi,12;"
            f"call {GLYPH};"
            f"\n add edi,18;"
            f"mov eax,10;"
            f"call {GLYPH};"
            f"add edi,12;"
            f"mov eax,11;"
            f"call {GLYPH};"
            f"add edi,12;"
            f"mov eax,12;"
            f"call {GLYPH};"
            f"\n done:ret;"
        ), 0x300
    )
    emit(
        GLYPH, (
            f"pushad;"
            f"imul esi,eax,7;"
            f"add esi,{FONT};"
            f"mov ebp,7;"
            f"mov al,[{STATE+36}];"
            f"mov ah,al;"
            f"\n row:mov bl,[esi];"
            f"mov ecx,5;"
            f"push edi;"
            f"\n pixel:test bl,16;"
            f"jz blank;"
            f"mov [edi],ax;"
            f"mov [edi+1280],ax;"
            f"blank:shl bl,1;"
            f"add edi,2;"
            f"loop pixel;"
            f"\n pop edi;"
            f"add edi,2560;"
            f"inc esi;"
            f"dec ebp;"
            f"jnz row;"
            f"popad;"
            f"ret;"
        ), 0x100
    )
    glyphs = [
        '01110 10001 10011 10101 11001 10001 01110', '00100 01100 00100 00100 00100 00100 01110',
        '01110 10001 00001 00010 00100 01000 11111', '11110 00001 00001 01110 00001 00001 11110',
        '00010 00110 01010 10010 11111 00010 00010', '11111 10000 10000 11110 00001 00001 11110',
        '01110 10000 10000 11110 10001 10001 01110', '11111 00001 00010 00100 01000 01000 01000',
        '01110 10001 10001 01110 10001 10001 01110', '01110 10001 10001 01111 00001 00001 01110',
        '11111 10000 10000 11110 10000 10000 10000', '11110 10001 10001 11110 10000 10000 10000',
        '01111 10000 10000 01110 00001 00001 11110'
    ]
    out.append((FONT, bytes(int(row, 2) for g in glyphs for row in g.split())))
    return out
