"""Switch retail and Prequel campaigns in the same game window.

The script callback queues a request. Once the interpreter unwinds, the switch
disposes of GUI surfaces, stops effects and destroys the script VM before changing
campaign archives and bindings. RESSOUND stays open because its locked event table
is identical across the supported campaigns. Graphics, input, audio devices and
their shutdown registrations remain alive.

Address names describe reverse-engineered roles in the original v1.09 executable.
They are descriptive labels chosen for this project, rather than recovered symbols.
"""
from dataclasses import dataclass
from patch_support import asm

CALLBACK = 0x1EFDC00  # Replace the startup callback with a request to switch campaigns in this window.
OUTER = 0x1EFE000
STATE = 0x1EFE800  # pending, completed, request, phase (four words)
CHECK = 0x1EFE900
CLEAN_UI = 0x1EFEB00
ERROR = 0x1EFEC00
TEXT = 0x1EFED00
REPORT_EXIT = 0x1EFEE90
OPENING = 0x1EFEF00
ORIGINAL_OPENING = 0x2DBE7C
FINISH_SOUNDS = 0x2473BC  # Release resources owned by completed sound channels.
END = 0x1EFF000
SITE = 0x2449BA
ORIGINAL = bytes.fromhex('803df26a440000')
CAMPAIGN = 0x1FC0700
RETAIL_ROOT, DEMO_ROOT, ACTIVE_ROOT = 0x1FC2A00, 0x1FC132C, 0x1D08400
RETAIL_FUNCTIONS, DEMO_FUNCTIONS, DEMO_VARIABLES = 0x1FC0100, 0x1FC0400, 0x1EF6800


@dataclass(frozen=True)
class Bindings:
    campaign_state: int
    retail_root: int
    demo_root: int
    active_root: int
    retail_functions: int
    demo_functions: int
    demo_variables: int


def validate(imports, bindings):
    for name in ('ExitProcess', 'GetModuleHandleA', 'GetProcAddress'):
        slot = imports.get(name)
        if type(slot) is not int or not 0 < slot <= 0x2000000 - 4:
            raise ValueError('Invalid campaign import slot: ' + name)
    if not isinstance(bindings, Bindings):
        raise ValueError('Campaign switch requires explicit bindings')
    capacities = dict(
        campaign_state=4,
        retail_root=256,
        demo_root=256,
        active_root=256,
        retail_functions=166 * 4,
        demo_functions=166 * 4,
        demo_variables=4
    )
    for name, size in capacities.items():
        address = getattr(bindings, name)
        if type(address) is not int or not 0x11000 <= address <= 0x2000000 - size:
            raise ValueError('Campaign provider outside image: ' + name)


def bodies(imports, bindings):
    """Emit position-stable code; immutable roots use existing relocations."""
    validate(imports, bindings)
    CAMPAIGN = bindings.campaign_state
    RETAIL_ROOT, DEMO_ROOT, ACTIVE_ROOT = bindings.retail_root, bindings.demo_root, bindings.active_root
    RETAIL_FUNCTIONS, DEMO_FUNCTIONS, DEMO_VARIABLES = bindings.retail_functions, bindings.demo_functions, bindings.demo_variables
    out = []

    def emit(address, end, source):
        data = asm(address, source)
        assert address + len(data) <= end, hex(address)
        out.append((address, data))

    # Return the original callback argument. No destructor runs on its stack.
    emit(
        CALLBACK, OUTER, (
            f"cmp eax,1;"
            f"je done;"
            f"cmp eax,3;"
            f"je quit;"
            f"\n        cmp eax,2;"
            f"ja done;"
            f"inc eax;"
            f"mov [{STATE}],eax;"
            f"dec eax;"
            f"\n        done:ret;"
            f"quit:push 0;"
            f"call dword ptr [{imports['ExitProcess']}];"
            f"ret;"
        )
    )

    # Require one main-menu VM, ordinary menu surfaces, no live animations,
    # the expected four archives and no unexpected locked resource consumers.
    # Finished sounds can still own resource locks after leaving Quarters.
    # Drain their normal completion queue once the menu structure is safe,
    # then check every remaining lock. Active sounds and other consumers still
    # prevent switching; a rejection leaves the menu and archives in place.
    emit(
        CHECK, CLEAN_UI, (
            "\n        cmp dword ptr [0x447250],0x447258;"
            "jne bad;"
            "\n        cmp dword ptr [0x36f4a0],0;"
            "jne bad;"
            "\n        cmp dword ptr [0x3596d8],1;"
            "jne bad;"
            "\n        xor ecx,ecx;"
            "\n        archives:cmp dword ptr [0x446c08+ecx*8],-1;"
            "je bad;"
            "\n        inc ecx;"
            "cmp ecx,4;"
            "jb archives;"
            "\n        extras:cmp dword ptr [0x446c08+ecx*8],-1;"
            "jne bad;"
            "\n        inc ecx;"
            "cmp ecx,16;"
            "jb extras;"
            "\n        mov eax,[0x448dac];"
            "cmp eax,0x448db4;"
            "je bad;"
            "\n        cmp dword ptr [eax],0x448db4;"
            "jne bad;"
            "\n        movzx edx,word ptr [eax+0xa];"
            "cmp edx,1001;"
            "je vm_ok;"
            "\n        cmp edx,1003;"
            "jne bad;"
            "\n        vm_ok:mov esi,[0x447224];"
            "mov ecx,64;"
            "\n        screens:cmp esi,0x44722c;"
            "je locks;"
            "\n        cmp byte ptr [esi+0xa],2;"
            "jne bad;"
            "\n        cmp dword ptr [esi+0x64],0;"
            "jne bad;"
            "\n        cmp dword ptr [esi+0x68],0;"
            "jne bad;"
            "\n        mov esi,[esi];"
            "loop screens;"
            "jmp bad;"
            "\n        locks:pushad;"
            f"call {FINISH_SOUNDS};"
            "popad;"
            "mov esi,[0x446be8];"
            "movzx ecx,word ptr [0x446bf0];"
            "mov ebx,3;"
            "\n        resource:cmp ebx,ecx;"
            "ja good;"
            "mov edi,ebx;"
            "shl edi,4;"
            "\n        cmp byte ptr [esi+edi+4],0;"
            "je next;"
            "\n        cmp ebx,edx;"
            "je next;"
            "cmp ebx,363;"
            "je next;"
            "cmp ebx,2222;"
            "jne bad;"
            "\n        next:inc ebx;"
            "jmp resource;"
            "\n        good:mov eax,1;"
            "ret;"
            "bad:xor eax,eax;"
            "ret;"
        )
    )

    # VM destruction alone does not destroy UI objects. Their copied menu
    # bitmaps otherwise survive and later overwrite the in-mission visor.
    emit(
        CLEAN_UI, ERROR, (
            "pushad;"
            "mov esi,[0x447224];"
            "\n        screen:cmp esi,0x44722c;"
            "je finished;"
            "\n        mov ebx,[esi];"
            "test byte ptr [esi+0xb],4;"
            "jnz next;"
            "\n        mov eax,esi;"
            "call 0x2e575c;"
            "\n        next:mov esi,ebx;"
            "jmp screen;"
            "\n        finished:call 0x2e60f4;"
            "popad;"
            "ret;"
        )
    )

    # Resolve MessageBoxA without adding an import or keeping a new DLL alive.
    # user32 is already loaded by the existing native window support layer.
    title, dll, proc, rejected, failed = TEXT, TEXT + 32, TEXT + 48, TEXT + 80, TEXT + 240
    strings = [
        (title, b'Terra Nova\0'), (dll, b'user32.dll\0'), (proc, b'MessageBoxA\0'),
        (
            rejected,
            b'The campaign menu is still busy. Please wait a moment and try again.\0'
        ),
        (
            failed,
            b'Unable to open the selected campaign resources. The game will close. Please verify this installation in the launcher. Saved games are unchanged.\0'
        )
    ]
    out.extend(strings)
    # Reuse the original unique working-report creation on each campaign
    # entry, but register its process-exit cleanup only on initial startup.
    emit(
        REPORT_EXIT, END, (
            f"pushfd;"
            f"cmp dword ptr [{STATE+12}],4;"
            f"je switching;"
            f"\n        popfd;"
            f"mov eax,0x2c65a4;"
            f"call 0x2de841;"
            f"jmp 0x2c6599;"
            f"\n        switching:popfd;"
            f"jmp 0x2c6599;"
        )
    )
    out.append((0x2c658f, asm(0x2c658f, f'jmp {REPORT_EXIT};') + b'\x90' * 5))
    emit(
        ERROR, TEXT, (
            f"pushad;"
            f"mov ebp,eax;"
            f"\n        push {dll};"
            f"call dword ptr [{imports['GetModuleHandleA']}];"
            f"test eax,eax;"
            f"jz done;"
            f"\n        push {proc};"
            f"push eax;"
            f"call dword ptr [{imports['GetProcAddress']}];"
            f"test eax,eax;"
            f"jz done;"
            f"\n        push 0x10;"
            f"push {title};"
            f"push ebp;"
            f"push 0;"
            f"call eax;"
            f"\n        done:popad;"
            f"ret;"
        )
    )

    emit(
        OUTER, STATE, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"\n        cmp dword ptr [{STATE}],0;"
            f"je done;"
            f"\n        mov eax,[{STATE}];"
            f"mov [{STATE+8}],eax;"
            f"mov dword ptr [{STATE}],0;"
            f"\n        call {CHECK};"
            f"test eax,eax;"
            f"jnz begin;"
            f"\n        mov dword ptr [{STATE+12}],0xfffffffe;"
            f"mov eax,{rejected};"
            f"call {ERROR};"
            f"jmp done;"
            f"\n        begin:mov dword ptr [{STATE+12}],1;"
            f"\n        call 0x2e4b1c;"
            f"call 0x2ee580;"
            f"call {CLEAN_UI};"
            f"call 0x2e7e8c;"
            f"\n        call 0x2c65a4;"
            f"\n        mov dword ptr [0x449648],0;"
            f"mov dword ptr [0x36f4b4],0;"
            f"\n        mov eax,363;"
            f"call 0x2eb3f4;"
            f"\n        mov dword ptr [0x44707c],0;"
            f"mov dword ptr [0x4470a8],0;"
            f"\n        mov dword ptr [{STATE+12}],2;"
            f"\n        mov eax,3;"
            f"call 0x2e1848;"
            f"mov eax,1;"
            f"call 0x2e1848;"
            f"xor eax,eax;"
            f"call 0x2e1848;"
            f"\n        mov dword ptr [{STATE+12}],3;"
            f"\n        cmp dword ptr [{STATE+8}],3;"
            f"je demo;"
            f"\n        mov dword ptr [{CAMPAIGN}],0;"
            f"mov dword ptr [0x2448c7],0x35dbe8;"
            f"\n        mov dword ptr [0x2448cc],{RETAIL_FUNCTIONS};"
            f"mov dword ptr [0x244938],0x3e90004;"
            f"\n        mov byte ptr [0x2c6f83],0xa1;"
            f"mov dword ptr [0x2c6f84],0x440978;"
            f"\n        mov esi,{RETAIL_ROOT};"
            f"jmp root;"
            f"\n        demo:mov dword ptr [{CAMPAIGN}],1;"
            f"mov dword ptr [0x2448c7],{DEMO_VARIABLES};"
            f"\n        mov dword ptr [0x2448cc],{DEMO_FUNCTIONS};"
            f"mov dword ptr [0x244938],0x3eb0003;"
            f"\n        mov byte ptr [0x2c6f83],0xe9;"
            f"mov dword ptr [0x2c6f84],{0x1ef6e00-0x2c6f88};"
            f"\n        mov esi,{DEMO_ROOT};"
            f"\n        root:mov edi,{ACTIVE_ROOT};"
            f"mov ecx,255;"
            f"\n        copy:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jz copied;"
            f"loop copy;"
            f"\n        copied:mov dword ptr [{STATE+12}],4;"
            f"\n        call 0x2c64e8;"
            f"\n        mov dword ptr [0x1ef68e0],0;"
            f"mov dword ptr [0x1ef68e4],0;"
            f"mov dword ptr [0x1ef68e8],0;"
            f"\n        mov eax,0x355208;"
            f"xor edx,edx;"
            f"xor ebx,ebx;"
            f"call 0x2e15d0;"
            f"mov [0x36f4a0],eax;"
            f"\n        cmp eax,0;"
            f"jne failed;"
            f"\n        mov eax,0x355238;"
            f"xor edx,edx;"
            f"xor ebx,ebx;"
            f"call 0x2e15d0;"
            f"mov [0x3596d8],eax;"
            f"\n        cmp eax,1;"
            f"jne failed;"
            f"\n        mov dword ptr [{STATE+12}],5;"
            f"\n        mov eax,0x16b0000;"
            f"call 0x2e4930;"
            f"\n        mov dword ptr [{STATE+12}],6;"
            f"\n        call 0x278d18;"
            f"call 0x2c7afc;"
            f"\n        mov dword ptr [{STATE+12}],7;"
            f"\n        mov eax,0x3552c0;"
            f"xor edx,edx;"
            f"xor ebx,ebx;"
            f"call 0x2e15d0;"
            f"\n        cmp eax,3;"
            f"jne failed;"
            f"\n        mov eax,1000;"
            f"mov edx,[0x2448c7];"
            f"mov ebx,[0x2448cc];"
            f"call 0x2e7e48;"
            f"\n        mov dword ptr [{STATE+12}],8;"
            f"\n        mov eax,[0x244938];"
            f"xor ecx,ecx;"
            f"call 0x2e7ff4;"
            f"mov [0x36f4b4],eax;"
            f"\n        test eax,eax;"
            f"jz failed;"
            f"mov eax,[eax+6];"
            f"shr eax,16;"
            f"mov [0x36f4b0],eax;"
            f"\n        mov dword ptr [{STATE+12}],9;"
            f"inc dword ptr [{STATE+4}];"
            f"jmp done;"
            f"\n        failed:mov dword ptr [{STATE+12}],0xffffffff;"
            f"mov eax,{failed};"
            f"call {ERROR};"
            f"\n        push 1;"
            f"call dword ptr [{imports['ExitProcess']}];"
            f"\n        done:popad;"
            f"popfd;"
            f"cmp byte ptr [0x446af2],0;"
            f"jmp 0x2449c1;"
        )
    )
    out.append((SITE, asm(SITE, f'jmp {OUTER};nop;nop;')))
    return out


def install(write, read, *, imports, bindings, callback_before):
    """Validate the supplied menu callback before installing campaign switching.

    The caller supplies the complete callback reservation. Checking it as a whole
    prevents a partial or incompatible callback from being accepted.
    """
    pieces = bodies(imports, bindings)
    if type(callback_before) is not bytes or len(callback_before) != OUTER - CALLBACK:
        raise ValueError('Campaign callback requires its full predecessor reservation')

    def expect(address, before, label):
        if bytes(read(address, len(before))) != before:
            raise ValueError('Campaign ' + label + ' differs at ' + hex(address))

    expect(SITE, ORIGINAL, 'dispatch hook')
    expect(0x2c658f, asm(0x2c658f, 'mov eax,0x2c65a4;call 0x2de841;'), 'report hook')
    expect(OUTER, bytes(END - OUTER), 'lifecycle reservation')
    expect(CALLBACK, callback_before, 'callback predecessor')
    for address, data in pieces:
        write(address, data)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])


def install_from_startup(
    write,
    read,
    *,
    imports,
    home,
    demo_root,
    shared_root,
    retail_root=RETAIL_ROOT,
    active_root=ACTIVE_ROOT
):
    """Connect startup to same-window switching in the build image.

    Generated text, registered callbacks and the entire startup callback must
    match before replacement. Runtime switching and snapshot restore have their
    own paths because they operate on an active game.
    """
    from . import campaign_startup as startup
    import struct
    provider = startup.switch_provider(
        imports, home=home, demo_root=demo_root, shared_root=shared_root
    )
    if bytes(read(startup.TEXT, len(provider.text))) != provider.text:
        raise ValueError('Campaign startup text/provider paths differ')
    suffix = struct.pack('<2I', startup.DRAW, startup.SWITCH)
    for table in (startup.RF, startup.DF):
        if bytes(read(table + 164 * 4, 8)) != suffix:
            raise ValueError('Campaign startup callback registration differs')
    bindings = Bindings(
        startup.STATE, retail_root, provider.demo_root_address, active_root, startup.RF, startup.DF,
        startup.VARS
    )
    return install(
        write, read, imports=imports, bindings=bindings, callback_before=provider.callback
    )


def opening_body():
    """Play the original openings only before the first campaign handover.

    The menu clears its original movie flag during initialization, so that flag
    cannot distinguish a fresh process from a recreated menu. The switch counter
    persists for the session and is incremented before the new VM runs. Snapshot
    restoration resumes a mission directly; any later handover also increments
    this counter. The separate Play Intro callback remains available.
    """
    return asm(
        OPENING, f'''
        cmp dword ptr [{STATE + 4}], 0
        jne returned
        jmp {ORIGINAL_OPENING}
    returned:
        xor eax, eax
        ret
    '''
    )


def install_opening_policy(write, read):
    """Bind the startup movie callback after the lifecycle reservation exists."""
    import struct
    body = opening_body()
    slot = RETAIL_FUNCTIONS + 47 * 4
    if bytes(read(slot, 4)) != struct.pack('<I', ORIGINAL_OPENING):
        raise ValueError('Original opening callback differs')
    if bytes(read(OPENING, END - OPENING)) != bytes(END - OPENING):
        raise ValueError('Opening callback reservation is occupied')
    assert OPENING + len(body) <= END
    write(OPENING, body)
    write(slot, struct.pack('<I', OPENING))


DEBRIEF_CODE = 0x1EFF100  # This slot lies between the pose bridge and the map buffer.
DEBRIEF_END = 0x1EFF400
DEBRIEF_SITE = 0x2BD694
DEBRIEF_ORIGINAL = bytes.fromhex('be16010000')  # mov esi,278
DEBRIEF_NORMAL = DEBRIEF_SITE + len(DEBRIEF_ORIGINAL)
DEBRIEF_CONTINUE = 0x2BD743


def debrief_bodies():
    body = asm(
        DEBRIEF_CODE, (
            f"\n        pushfd;"
            f"pushad;"
            f"cld;"
            f"\n        cmp dword ptr [0x1fc0700],1;"
            f"jne normal;"
            f"\n        mov eax,[0x440978];"
            f"test eax,eax;"
            f"jz normal;"
            f"\n        mov edx,[eax+0x842];"
            f"cmp edx,1;"
            f"jb normal;"
            f"cmp edx,3;"
            f"ja normal;"
            f"\n        cmp byte ptr [eax+0x806],1;"
            f"jne normal;"
            f"\n        cmp byte ptr [eax],3;"
            f"je normal;"
            f"\n        lea eax,[edx+0x5af0004];"
            f"call 0x2e3194;"
            f"test eax,eax;"
            f"jz normal;"
            f"\n        mov esi,eax;"
            f"mov edi,0x43cec8;"
            f"mov ecx,1023;"
            f"\n        copy:lodsb;"
            f"stosb;"
            f"test al,al;"
            f"jz text;"
            f"loop copy;"
            f"\n        mov byte ptr [edi],0;"
            f"\n        text:mov eax,[0x44b1a0];"
            f"mov dword ptr [eax+0x10],0xf2;"
            f"\n        mov edx,0x43cec8;"
            f"mov eax,[0x43cde0];"
            f"mov ebx,590;"
            f"mov ecx,278;"
            f"\n        call 0x2f3050;"
            f"\n        mov edx,0x43cec8;"
            f"mov eax,[0x43cde0];"
            f"mov ebx,30;"
            f"mov ecx,278;"
            f"\n        mov edi,[0x44b194];"
            f"call dword ptr [edi+0x4ec];"
            f"\n        popad;"
            f"popfd;"
            f"jmp {DEBRIEF_CONTINUE};"
            f"\n        normal:popad;"
            f"popfd;"
            f"mov esi,278;"
            f"jmp {DEBRIEF_NORMAL};"
            f"\n    "
        )
    )
    assert DEBRIEF_CODE + len(body) <= DEBRIEF_END
    return [(DEBRIEF_CODE, body), (DEBRIEF_SITE, asm(DEBRIEF_SITE, f'jmp {DEBRIEF_CODE}'))]


EQUIPMENT_CODE = 0x1EFF400
EQUIPMENT_END = 0x1EFF500
EQUIPMENT_SITE = 0x279BA4
EQUIPMENT_ORIGINAL = bytes.fromhex('53515689c3')
EQUIPMENT_NORMAL = EQUIPMENT_SITE + len(EQUIPMENT_ORIGINAL)
EQUIPMENT_PRESET = 0x1EF7540


def equipment_bodies():
    body = asm(
        EQUIPMENT_CODE, (
            f"\n        pushfd;"
            f"cmp dword ptr [0x1fc0700],1;"
            f"jne retail;"
            f"popfd;"
            f"\n        push ebx;"
            f"push ecx;"
            f"push 3;"
            f"\n        mov ebx,1;"
            f"mov ecx,{EQUIPMENT_PRESET};"
            f"movsx edx,dl;"
            f"\n        call 0x266390;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
            f"\n        retail:popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push esi;"
            f"mov ebx,eax;"
            f"\n        jmp {EQUIPMENT_NORMAL};"
            f"\n    "
        )
    )
    assert EQUIPMENT_CODE + len(body) <= EQUIPMENT_END
    return [(EQUIPMENT_CODE, body), (EQUIPMENT_SITE, asm(EQUIPMENT_SITE, f'jmp {EQUIPMENT_CODE}'))]


def _content_inputs(read, *, debrief, equipment):
    checks = []
    if debrief:
        checks.extend(
            ((DEBRIEF_SITE, DEBRIEF_ORIGINAL), (DEBRIEF_CODE, bytes(DEBRIEF_END - DEBRIEF_CODE)))
        )
    if equipment:
        checks.extend(
            (
                (EQUIPMENT_SITE,
                 EQUIPMENT_ORIGINAL), (EQUIPMENT_CODE, bytes(EQUIPMENT_END - EQUIPMENT_CODE)),
                (EQUIPMENT_PRESET, bytes.fromhex('05030402'))
            )
        )
    for address, expected in checks:
        if bytes(read(address, len(expected))) != expected:
            raise ValueError('Campaign content provider differs at ' + hex(address))


def install_content(write, read, *, debrief=True, equipment=True):
    """Bind fixed demo equipment and successful-mission story paragraphs.

    Both original hooks, complete helper reservations and the startup-provided
    equipment preset are checked before any write. Retail/failure paths remain
    original; the final mission keeps its separate recruitment-letter page.
    """
    _content_inputs(read, debrief=debrief, equipment=equipment)
    pieces = (debrief_bodies() if debrief else []) + (equipment_bodies() if equipment else [])
    for address, data in pieces:
        write(address, data)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])


def install_debrief(write, ram):
    return install_content(write, lambda a, n: ram[a:a + n], equipment=False)


def install_equipment(write, ram):
    return install_content(write, lambda a, n: ram[a:a + n], debrief=False)


# Vehicle damage safety and report preflight before an ordinary save is opened.
SAFETY_CODE = 0x1ffe400

SAFETY_END = 0x1ffe800

SAFETY_SITES = {0x28793e: bytes.fromhex('8b4c246c8a4914'), 0x2c35bc: bytes.fromhex('5351525657')}


def safety_bodies():
    return [
        (
            SAFETY_CODE,
            asm(
                SAFETY_CODE, (
                    "mov ecx,[esp+0x6c];"
                    "test ecx,ecx;"
                    "jnz present;"
                    "\n mov edx,[esp+0x14];"
                    "mov [esp+0x18],eax;"
                    "add edx,eax;"
                    "mov [esp+0x14],edx;"
                    "\n mov eax,1;"
                    "xor edx,edx;"
                    "jmp 0x2879c7;"
                    "\n present:mov cl,[ecx+0x14];"
                    "jmp 0x287945;"
                )
            )
        ), (0x28793e, asm(0x28793e, f'jmp {SAFETY_CODE}') + b'\x90\x90'),
        (
            SAFETY_CODE + 0x100,
            asm(
                SAFETY_CODE + 0x100, (
                    f"pushfd;"
                    f"pushad;"
                    f"call {SAFETY_CODE+0x180};"
                    f"test eax,eax;"
                    f"jz failed;"
                    f"\n popad;"
                    f"popfd;"
                    f"push ebx;"
                    f"push ecx;"
                    f"push edx;"
                    f"push esi;"
                    f"push edi;"
                    f"jmp 0x2c35c1;"
                    f"\n failed:popad;"
                    f"popfd;"
                    f"xor eax,eax;"
                    f"ret;"
                )
            )
        ),
        (
            SAFETY_CODE + 0x180,
            asm(
                SAFETY_CODE + 0x180, (
                    "push ebx;"
                    "push ecx;"
                    "push edx;"
                    "push esi;"
                    "push edi;"
                    "push ebp;"
                    "\n mov edi,[0x35d0ec];"
                    "sub edi,2;"
                    "mov eax,[0x359710];"
                    "cmp eax,64;"
                    "jae bad;"
                    "\n movsx ebp,byte ptr [eax+0x4412ce];"
                    "cmp ebp,2;"
                    "jg later;"
                    "mov ebp,1;"
                    "jmp first;"
                    "\n later:sub ebp,2;"
                    "first:cmp ebp,edi;"
                    "jge good;"
                    "\n add ebp,0x659;"
                    "add edi,0x659;"
                    "mov eax,0x440934;"
                    "xor edx,edx;"
                    "xor ebx,ebx;"
                    "call 0x2e15d0;"
                    "\n test eax,eax;"
                    "jz bad;"
                    "mov esi,eax;"
                    "\n next:mov eax,ebp;"
                    "call 0x2eb380;"
                    "test eax,eax;"
                    "jz close_bad;"
                    "\n mov eax,ebp;"
                    "call 0x2eb3f4;"
                    "inc ebp;"
                    "cmp ebp,edi;"
                    "jl next;"
                    "\n mov eax,esi;"
                    "call 0x2e1848;"
                    "good:mov eax,1;"
                    "jmp done;"
                    "\n close_bad:mov eax,esi;"
                    "call 0x2e1848;"
                    "bad:xor eax,eax;"
                    "\n done:pop ebp;"
                    "pop edi;"
                    "pop esi;"
                    "pop edx;"
                    "pop ecx;"
                    "pop ebx;"
                    "ret;"
                )
            )
        ), (0x2c35bc, asm(0x2c35bc, f'jmp {SAFETY_CODE+0x100}'))
    ]


def safety_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        safety_bodies(),
        SAFETY_SITES,
        write,
        read,
        cold_state=((SAFETY_CODE, SAFETY_END - SAFETY_CODE), )
    )


def safety_verify(read):
    from features.input_views import _verify
    return _verify(safety_bodies(), read)
