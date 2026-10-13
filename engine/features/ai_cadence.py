"""Optional extra AI readiness polls and their persisted preference.

The original slow decision branch, weapon cooldowns, difficulty, aim and firing
permission remain authoritative. Off restores vanilla cadence for every weapon.
Windows import slots are explicit; Options owns the final row and shared root.
"""
from patch_support import asm
from features.weapon_timing import RESOLVE as WEAPON_RESOLVE
from features import ai_firing as fire, fps_display as fps

GATE_SITE = 0x251d6e
ORIGINAL_GATE = bytes.fromhex('3dfa0000000f8600020000')
# Original weapon-timing ABI: only the poll timestamp at row +16 is reset.
# Broader timing-table ownership is consolidated separately from this consumer.
from features.weapon_timing import TABLE as POLL_TABLE, COUNT as POLL_COUNT, STRIDE as POLL_STRIDE

CODE = 0x1e39000
END = 0x1e3a000
GATE = CODE
INIT = CODE + 0x200
SAVE = CODE + 0x400
DRAW = CODE + 0x600
EVENT = CODE + 0x800
ACCEPT = CODE + 0xa00
CLOSE = CODE + 0xa80
from features.option_contracts import AI as preference

STATE = preference.state
STATE_SIZE = preference.size
TEXT = CODE + 0xe00
assert (INIT, SAVE) == (preference.init, preference.save)


# initialized, enabled, pending, Options-open, profile read/write pointers,
# followed by a bounded path buffer at +64. No gameplay pointers are stored.
def sites(gate_before=ORIGINAL_GATE):
    return {
        GATE_SITE: gate_before,
        0x2ca9b4: asm(0x2ca9b4, f'call {fps.DRAW}'),
        0x2cab9d: asm(0x2cab9d, f'call {fps.DRAW}'),
        0x2ca450: asm(0x2ca450, f'jmp {fps.EVENT}'),
        0x2cbbdc: asm(0x2cbbdc, f'call {fps.ACCEPT}'),
        0x2cbc08: asm(0x2cbc08, f'jmp {fps.CLOSE}') + b'\x90'
    }


def bodies(imports):
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
        ('write', 'WritePrivateProfileStringA'), ('section', 'Gameplay'), ('key', 'WeaponTimedAI'),
        ('file', 'TNHR.INI'), ('label', 'FASTER AI FIRING'), ('zero', '0'), ('one', '1')
    ]:
        labels[k] = TEXT + len(raw)
        raw += v.encode() + b'\0'
    assert len(raw) < END - TEXT
    out.append((TEXT, bytes(raw)))
    # Keep the original >250-ms branch exactly, including its weapon-choice call.
    # Extra polls bypass only that throttle, never the downstream permission tests.
    emit(
        GATE, (
            f"cmp eax,250;"
            f"ja original;"
            f"pushfd;"
            f"pushad;"
            f"call {INIT};"
            f"\n cmp dword ptr [{STATE+4}],1;"
            f"jne no;"
            f"\n movsx edx,word ptr [esi+11];"
            f"test edx,edx;"
            f"jle no;"
            f"cmp edx,300;"
            f"jae no;"
            f"\n cmp dx,word ptr [0x441350];"
            f"je no;"
            f"\n imul ecx,edx,37;"
            f"cmp byte ptr [ecx+0x3c3240],0;"
            f"je no;"
            f"\n call {fire.RESOLVE};"
            f"test eax,eax;"
            f"jz no;"
            f"\n cmp byte ptr [eax],1;"
            f"jb no;"
            f"cmp byte ptr [eax],32;"
            f"ja no;"
            f"\n mov eax,[0x446ae8];"
            f"cmp eax,[esi+0xf1];"
            f"jbe no;"
            f"\n popad;"
            f"popfd;"
            f"jmp 0x251d97;"
            f"\n no:popad;"
            f"popfd;"
            f"jmp 0x251f79;"
            f"original:jmp 0x251d79;"
        ), 0x200
    )
    out.append((GATE_SITE, asm(GATE_SITE, f'jmp {GATE}') + b'\x90' * (len(ORIGINAL_GATE) - 5)))
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
            f"mov [{STATE+16}],eax;"
            f"\n push {labels['write']};"
            f"push ebp;"
            f"call dword ptr [{imports['GetProcAddress']}];"
            f"test eax,eax;"
            f"jz done;"
            f"mov [{STATE+20}],eax;"
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
            f"call dword ptr [{STATE+16}];"
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
            f"cmp eax,[{STATE+4}];"
            f"je persist;"
            f"\n mov [{STATE+4}],eax;"
            f"\n mov edi,{POLL_TABLE+16};"
            f"mov ecx,{POLL_COUNT};"
            f"\n clear:mov dword ptr [edi],0;"
            f"add edi,{POLL_STRIDE};"
            f"loop clear;"
            f"\n persist:mov edx,{labels['zero']};"
            f"test eax,eax;"
            f"jz value;"
            f"mov edx,{labels['one']};"
            f"\n value:push {STATE+64};"
            f"push edx;"
            f"push {labels['key']};"
            f"push {labels['section']};"
            f"call dword ptr [{STATE+20}];"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        ), 0x200
    )
    emit(
        DRAW, (
            f"call {fps.DRAW};"
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
            f"\n mov edi,[0x44b194];"
            f"mov dword ptr [esi+0x10],0;"
            f"\n mov eax,436;"
            f"mov edx,388;"
            f"mov ebx,630;"
            f"mov ecx,410;"
            f"call dword ptr [edi+0x40];"
            f"\n mov dword ptr [esi+0x10],0xf7;"
            f"mov eax,440;"
            f"mov edx,392;"
            f"mov ebx,450;"
            f"mov ecx,402;"
            f"call dword ptr [edi+0x48];"
            f"\n cmp dword ptr [{STATE+8}],0;"
            f"je label;"
            f"\n mov eax,442;"
            f"mov edx,394;"
            f"mov ebx,448;"
            f"mov ecx,400;"
            f"call dword ptr [edi+0x40];"
            f"\n label:mov eax,0x164;"
            f"call 0x2eb380;"
            f"mov [esi+0x18],eax;"
            f"\n mov edx,{labels['label']};"
            f"mov ebx,456;"
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
    for site in (0x2ca9b4, 0x2cab9d):
        emit(site, f'call {DRAW}', 5)
    emit(
        EVENT, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [eax],1;"
            f"jne pass;"
            f"\n movsx ecx,word ptr [eax+8];"
            f"cmp ecx,436;"
            f"jl pass;"
            f"cmp ecx,630;"
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
            f"\n mov eax,0x446fb8;"
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
            f"jmp {fps.EVENT};"
        ), 0x200
    )
    emit(0x2ca450, f'jmp {EVENT}', 5)
    emit(ACCEPT, f'call {SAVE};jmp {fps.ACCEPT};', 0x80)
    emit(0x2cbbdc, f'call {ACCEPT}', 5)
    emit(CLOSE, (f"pushfd;"
                 f"mov dword ptr [{STATE+12}],0;"
                 f"popfd;"
                 f"jmp {fps.CLOSE};"), 0x80)
    out.append((0x2cbc08, asm(0x2cbc08, f'jmp {CLOSE}') + b'\x90'))
    return out


def providers(imports):
    # Rendering continuation itself is bound by the FPS feature. Only its
    # option helpers/text are dependencies of this consumer, not the FPS meter.
    fps_parts = dict(fps.bodies(imports, 0x11000))
    return [(fire.RESOLVE, fire.selected_weapon_body())] + [
        (a, fps_parts[a])
        for a in (fps.DRAW, fps.EVENT, fps.INIT, fps.SAVE, fps.ACCEPT, fps.CLOSE, fps.TEXT)
    ]


def _dependencies(read, imports):
    for a, b in providers(imports):
        if bytes(read(a, len(b))) != b:
            raise ValueError('AI cadence provider differs at ' + hex(a))


def install(write, read, imports, *, gate_before=ORIGINAL_GATE):
    from features.input_views import _install
    if not isinstance(gate_before, bytes) or len(gate_before) != len(ORIGINAL_GATE):
        raise ValueError('Invalid AI decision-gate preimage')
    _dependencies(read, imports)
    return _install(
        bodies(imports), sites(gate_before), write, read, cold_state=((CODE, END - CODE), )
    )


def verify(read, imports):
    from features.input_views import _verify
    _dependencies(read, imports)
    return _verify(bodies(imports), read)


def predecessor_view(ram, imports, *, gate_before=ORIGINAL_GATE):
    """Private regression rollback of this feature's hooks and reservation."""
    verify(lambda a, n: ram[a:a + n], imports)
    out = bytearray(ram)
    for a, b in sites(gate_before).items():
        out[a:a + len(b)] = b
    out[CODE:END] = bytes(END - CODE)
    return out


# Allow SFC allies' selected Railguns to fire at their weapon cooldown.
RAILGUN_CODE = 0x1fc2000
RAILGUN_SITE = 0x251d6e
RAILGUN_ORIGINAL = bytes.fromhex('3dfa0000000f8600020000')


def railgun_bodies():
    s = (
        f"cmp eax,250;"
        f"ja original;"
        f"\n pushfd;"
        f"pushad;"
        f"movsx edx,word ptr [esi+11];"
        f"test edx,edx;"
        f"jle no;"
        f"\n cmp edx,300;"
        f"jae no;"
        f"cmp dx,word ptr [0x441350];"
        f"je no;"
        f"\n cmp byte ptr [esi+5],1;"
        f"jne no;"
        f"\n imul ecx,edx,37;"
        f"cmp byte ptr [ecx+0x3c3241],1;"
        f"jne no;"
        f"\n movzx eax,byte ptr [ecx+0x3c3242];"
        f"cmp eax,2;"
        f"jbe sfc;"
        f"cmp eax,13;"
        f"jne no;"
        f"\n sfc:call {WEAPON_RESOLVE};"
        f"test eax,eax;"
        f"jz no;"
        f"cmp byte ptr [eax],7;"
        f"jne no;"
        f"\n mov eax,[0x446ae8];"
        f"cmp eax,[esi+0xf1];"
        f"jbe no;"
        f"\n popad;"
        f"popfd;"
        f"jmp 0x251d97;"
        f"\n no:popad;"
        f"popfd;"
        f"jmp 0x251f79;"
        f"\n original:jmp 0x251d79;"
    )
    b = asm(RAILGUN_CODE, s)
    assert len(b) < 0x400
    return [
        (RAILGUN_CODE, b),
        (
            RAILGUN_SITE,
            asm(RAILGUN_SITE, f'jmp {RAILGUN_CODE}') + b'\x90' * (len(RAILGUN_ORIGINAL) - 5)
        )
    ]


# Apply the extra Railgun readiness polls by allegiance, not suit artwork.
ALLY_RAILGUN_CODE = 0x1fcd000
ALLY_RAILGUN_SITE = RAILGUN_SITE


def ally_railgun_bodies():
    # The original cooldown still decides when a shot can be made, including
    # model/difficulty scaling. Keep squad orders, LOS and aiming checks intact.
    s = (
        f"cmp eax,250;"
        f"ja original;"
        f"pushfd;"
        f"pushad;"
        f"\n movsx edx,word ptr [esi+11];"
        f"test edx,edx;"
        f"jle no;"
        f"cmp edx,300;"
        f"jae no;"
        f"\n cmp dx,word ptr [0x441350];"
        f"je no;"
        f"cmp byte ptr [esi+5],1;"
        f"jne no;"
        f"\n imul ecx,edx,37;"
        f"cmp byte ptr [ecx+0x3c3240],0;"
        f"je no;"
        f"\n cmp byte ptr [ecx+0x3c3241],1;"
        f"jne no;"
        f"\n call {WEAPON_RESOLVE};"
        f"test eax,eax;"
        f"jz no;"
        f"cmp byte ptr [eax],7;"
        f"jne no;"
        f"\n mov eax,[0x446ae8];"
        f"cmp eax,[esi+0xf1];"
        f"jbe no;"
        f"\n popad;"
        f"popfd;"
        f"jmp 0x251d97;"
        f"\n no:popad;"
        f"popfd;"
        f"jmp 0x251f79;"
        f"original:jmp 0x251d79;"
    )
    b = asm(ALLY_RAILGUN_CODE, s)
    assert len(b) < 0x400
    return [
        (ALLY_RAILGUN_CODE, b),
        (
            ALLY_RAILGUN_SITE, asm(ALLY_RAILGUN_SITE, f'jmp {ALLY_RAILGUN_CODE}') + b'\x90' *
            (len(RAILGUN_ORIGINAL) - 5)
        )
    ]


def railgun_pieces():
    """Keep both helper bodies; install the allegiance-based gate once."""
    return [(a, b) for a, b in railgun_bodies() if a != RAILGUN_SITE] + ally_railgun_bodies()


def railgun_install(write, read):
    from features.input_views import _install
    return _install(
        railgun_pieces(), {RAILGUN_SITE: RAILGUN_ORIGINAL},
        write,
        read,
        cold_state=((RAILGUN_CODE, 0x400), (ALLY_RAILGUN_CODE, 0x400))
    )


def railgun_verify(read):
    from features.input_views import _verify
    return _verify(railgun_pieces(), read)
