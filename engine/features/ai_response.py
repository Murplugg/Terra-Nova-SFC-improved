"""Help units respond to attackers and recover from unreachable firing positions.

The original AI owns navigation and combat orders. These helpers report damage,
remember a recent attacker and request short routes when repeated firing failures
and lack of progress justify trying another position.
"""
from patch_support import asm
from features import ai_firing as fire
from features.ai_firing import ATTACK_PREVIEW

# Notification throttle: 60 rows of (last notification time, owner object ID).
ALERT_CODE = 0x1e5b400
ALERT_EMIT = ALERT_CODE + 0x80
ALERT_STATE = ALERT_CODE + 0x800
ALERT_END = ALERT_STATE + 60 * 8
ALERT_SITE = 0x286c7c
ALERT_ORIGINAL = bytes.fromhex('535189c30fbfc2')
ALERT_RESET = 0x2953fd
ALERT_RESET_ORIGINAL = bytes.fromhex('bb5c2b0000')


def alert_bodies():
    wrapper = asm(
        ALERT_CODE, (
            f"call {ALERT_EMIT};"
            f"push ebx;"
            f"push ecx;"
            f"mov ebx,eax;"
            f"movsx eax,dx;"
            f"jmp 0x286c83;"
        )
    )
    s = (
        f"pushfd;"
        f"pushad;"
        f"movzx edi,ax;"
        f"movzx esi,dx;"
        f"\n test edi,edi;"
        f"jz done;"
        f"test esi,esi;"
        f"jz done;"
        f"cmp edi,300;"
        f"jae done;"
        f"cmp esi,300;"
        f"jae done;"
        f"cmp edi,esi;"
        f"je done;"
        f"\n imul ebx,edi,37;"
        f"cmp byte ptr [ebx+0x3c3240],0;"
        f"je done;"
        f"cmp byte ptr [ebx+0x3c3241],1;"
        f"jne done;"
        f"\n movzx ebp,byte ptr [ebx+0x3c3261];"
        f"test ebp,ebp;"
        f"jz done;"
        f"cmp ebp,60;"
        f"jae done;"
        f"\n imul ebx,ebp,334;"
        f"add ebx,0x3832f0;"
        f"cmp byte ptr [ebx],0;"
        f"je done;"
        f"cmp word ptr [ebx+11],di;"
        f"jne done;"
        f"\n cmp byte ptr [ebx+5],2;"
        f"jne done;"
        f"cmp byte ptr [ebx+10],0;"
        f"jne done;"
        f"\n imul eax,esi,37;"
        f"cmp byte ptr [eax+0x3c3240],0;"
        f"je done;"
        f"movzx ecx,byte ptr [eax+0x3c3261];"
        f"cmp ecx,60;"
        f"jae done;"
        f"\n imul eax,ecx,334;"
        f"add eax,0x3832f0;"
        f"cmp word ptr [eax+11],si;"
        f"jne done;"
        f"cmp byte ptr [eax+5],1;"
        f"jne done;"
        f"\n lea edx,[ebp*8+{ALERT_STATE}];"
        f"cmp [edx+4],edi;"
        f"jne alert;"
        f"mov eax,[0x446ae8];"
        f"sub eax,[edx];"
        f"cmp eax,500;"
        f"jb done;"
        f"\n alert:push ecx;"
        f"push edx;"
        f"call 0x2ec630;"
        f"pop edx;"
        f"pop ecx;"
        f"test eax,eax;"
        f"jz done;"
        f"\n mov [edx+4],edi;"
        f"push eax;"
        f"mov eax,[0x446ae8];"
        f"mov [edx],eax;"
        f"pop eax;"
        f"\n mov edx,esi;"
        f"shl edx,16;"
        f"or edx,0x80;"
        f"mov ebx,ebp;"
        f"shl ebx,16;"
        f"or ebx,0x80;"
        f"\n push eax;"
        f"push ebp;"
        f"call 0x25ae48;"
        f"pop eax;"
        f"call 0x2ec678;"
        f"\n done:popad;"
        f"popfd;"
        f"ret;"
    )
    b = asm(ALERT_EMIT, s)
    assert len(b) < 0x700
    reset = asm(
        ALERT_CODE + 0x700, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{ALERT_STATE};"
            f"xor eax,eax;"
            f"mov ecx,120;"
            f"rep stosd;"
            f"popad;"
            f"popfd;"
            f"mov ebx,0x2b5c;"
            f"jmp 0x295402;"
        )
    )
    return [
        (ALERT_CODE, wrapper), (ALERT_EMIT, b),
        (ALERT_SITE, asm(ALERT_SITE, f'jmp {ALERT_CODE}') + b'\x90' * 2),
        (ALERT_CODE + 0x700, reset), (ALERT_RESET, asm(ALERT_RESET, f'jmp {ALERT_CODE+0x700}'))
    ]


# Recent-attacker rows: time, owner, attacker, failed-since, retry time,
# direction cycle, progress X/Y; followed by the two attack-preview words.
CODE = 0x1fc6800
END = 0x1fc8000
FAIL = CODE + 0x40
HIT = CODE
REMEMBER = CODE + 0x80
SELECT = CODE + 0x300
PREFER = CODE + 0x400
REACH = CODE + 0x800
PREFLIGHT = ATTACK_PREVIEW.preflight
FALLBACK = CODE + 0xb00
SOLVER = CODE + 0xe00
QUERY = CODE + 0x700
RESET = CODE + 0x780
STATE = CODE + 0x1000
STRIDE = 32
STATE_SIZE = 60 * STRIDE + 8
ACTIVE = ATTACK_PREVIEW.active
FAILED = ATTACK_PREVIEW.failed
assert ACTIVE == STATE + 60 * STRIDE and FAILED == ACTIVE + 4 and PREFLIGHT == CODE + 0xa00
SITES = {
    0x2d9baa: asm(0x2d9baa, 'call 0x2d8d04'),
    0x252d63: asm(0x252d63, 'call 0x293834'),
    0x2d9bb3: bytes.fromhex('8b44241ec1f810'),
    0x252d68: bytes.fromhex('a18c654400'),
    0x252e42: asm(0x252e42, f'jmp {fire.PREFLIGHT}') + b'\x90',
    ALERT_SITE: asm(ALERT_SITE, f'jmp {ALERT_CODE}') + b'\x90' * 2,
    0x24dfe0: asm(0x24dfe0, 'call 0x24c618'),
    ALERT_RESET: asm(ALERT_RESET, f'jmp {ALERT_CODE+0x700}')
}


def bodies():
    hit = asm(HIT, f'call {REMEMBER};jmp {ALERT_CODE};')
    # The damage helper has already resolved projectile ownership to its actor.
    remember = asm(
        REMEMBER, (
            f"pushfd;"
            f"pushad;"
            f"movzx edi,ax;"
            f"movzx esi,dx;"
            f"\n test edi,edi;"
            f"jz done;"
            f"cmp edi,256;"
            f"jae done;"
            f"test esi,esi;"
            f"jz done;"
            f"cmp esi,256;"
            f"jae done;"
            f"\n imul edx,edi,37;"
            f"cmp byte ptr [edx+0x3c3240],0;"
            f"je done;"
            f"cmp byte ptr [edx+0x3c3241],1;"
            f"jne done;"
            f"\n movzx ebp,byte ptr [edx+0x3c3261];"
            f"test ebp,ebp;"
            f"jz done;"
            f"cmp ebp,60;"
            f"jae done;"
            f"\n imul ebx,ebp,334;"
            f"add ebx,0x3832f0;"
            f"cmp byte ptr [ebx],0;"
            f"je done;"
            f"\n cmp word ptr [ebx+11],di;"
            f"jne done;"
            f"cmp byte ptr [ebx+5],2;"
            f"jne done;"
            f"cmp byte ptr [ebx+10],0;"
            f"jne done;"
            f"\n imul edx,esi,37;"
            f"cmp byte ptr [edx+0x3c3240],0;"
            f"je done;"
            f"cmp byte ptr [edx+0x3c3241],1;"
            f"jne done;"
            f"\n movzx eax,byte ptr [edx+0x3c3261];"
            f"cmp eax,60;"
            f"jae done;"
            f"imul eax,eax,334;"
            f"add eax,0x3832f0;"
            f"\n cmp word ptr [eax+11],si;"
            f"jne done;"
            f"cmp byte ptr [eax+5],1;"
            f"jne done;"
            f"\n mov dl,[eax];"
            f"or dl,[eax+10];"
            f"jz done;"
            f"\n imul ebp,ebp,{STRIDE};"
            f"add ebp,{STATE};"
            f"\n cmp [ebp+4],edi;"
            f"jne fresh;"
            f"cmp [ebp+8],esi;"
            f"jne fresh;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[ebp];"
            f"cmp eax,15000;"
            f"jbe record;"
            f"\n fresh:xor eax,eax;"
            f"mov [ebp+12],eax;"
            f"mov [ebp+16],eax;"
            f"mov [ebp+20],eax;"
            f"mov [ebp+24],eax;"
            f"mov [ebp+28],eax;"
            f"\n record:mov eax,[0x446ae8];"
            f"mov [ebp],eax;"
            f"mov [ebp+4],edi;"
            f"mov [ebp+8],esi;"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    select = asm(
        SELECT, (
            f"push eax;"
            f"call 0x24c618;"
            f"pushfd;"
            f"pushad;"
            f"mov eax,[esp+36];"
            f"call {PREFER};"
            f"mov eax,[esp+36];"
            f"call {FALLBACK};"
            f"popad;"
            f"popfd;"
            f"add esp,4;"
            f"ret;"
        )
    )
    prefer = asm(
        PREFER, (
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"\n mov ebp,eax;"
            f"sub eax,0x3832f0;"
            f"xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz no;"
            f"test eax,eax;"
            f"jz no;"
            f"cmp eax,60;"
            f"jae no;"
            f"imul edi,eax,{STRIDE};"
            f"add edi,{STATE};"
            f"\n cmp byte ptr [ebp],0;"
            f"je no;"
            f"cmp byte ptr [ebp+5],2;"
            f"jne no;"
            f"cmp byte ptr [ebp+10],0;"
            f"jne no;"
            f"\n cmp byte ptr [ebp+13],1;"
            f"jne no;"
            f"cmp byte ptr [ebp+0xc3],0;"
            f"je no;"
            f"\n movzx eax,byte ptr [ebp+6];"
            f"cmp eax,32;"
            f"jae no;"
            f"imul eax,eax,368;"
            f"\n cmp word ptr [eax+0x380599],0;"
            f"jne no;"
            f"\n cmp byte ptr [eax+0x3805bb],5;"
            f"je no;"
            f"cmp byte ptr [eax+0x3805bb],9;"
            f"je no;"
            f"\n movzx ebx,word ptr [ebp+11];"
            f"cmp [edi+4],ebx;"
            f"jne no;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi];"
            f"cmp eax,5000;"
            f"ja no;"
            f"\n mov esi,[edi+8];"
            f"test esi,esi;"
            f"jz no;"
            f"cmp esi,256;"
            f"jae no;"
            f"\n imul edx,esi,37;"
            f"cmp byte ptr [edx+0x3c3240],0;"
            f"je no;"
            f"cmp byte ptr [edx+0x3c3241],1;"
            f"jne no;"
            f"\n movzx edi,byte ptr [edx+0x3c3261];"
            f"cmp edi,60;"
            f"jae no;"
            f"imul eax,edi,334;"
            f"add eax,0x3832f0;"
            f"\n cmp word ptr [eax+11],si;"
            f"jne no;"
            f"cmp byte ptr [eax+5],1;"
            f"jne no;"
            f"\n mov dl,[eax];"
            f"or dl,[eax+10];"
            f"jz no;"
            f"\n mov eax,esi;"
            f"cmp byte ptr [ebp+0xca],al;"
            f"jne changed;"
            f"mov eax,edi;"
            f"cmp byte ptr [ebp+0xc9],al;"
            f"je no;"
            f"\n changed:mov eax,esi;"
            f"mov [ebp+0xca],al;"
            f"mov eax,edi;"
            f"mov [ebp+0xc9],al;"
            f"\n imul eax,edi,334;"
            f"mov al,[eax+0x3832f6];"
            f"mov [ebp+0xcb],al;"
            f"\n imul edx,esi,37;"
            f"mov eax,[edx+0x3c324f];"
            f"sar eax,16;"
            f"mov [ebp+0xcc],ax;"
            f"\n mov eax,[edx+0x3c3253];"
            f"sar eax,16;"
            f"mov [ebp+0xce],ax;"
            f"\n mov eax,[0x446ae8];"
            f"mov [ebp+0xd7],eax;"
            f"mov [ebp+0xc5],eax;"
            f"\n mov byte ptr [ebp+0xc4],0;"
            f"mov dword ptr [ebp+0x106],0;"
            f"\n mov eax,1;"
            f"jmp done;"
            f"\n no:xor eax,eax;"
            f"done:pop ebp;"
            f"pop edi;"
            f"pop esi;"
            f"pop edx;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    reset = asm(
        RESET, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{STATE};"
            f"xor eax,eax;"
            f"mov ecx,{STATE_SIZE//4};"
            f"rep stosd;"
            f"popad;"
            f"popfd;"
            f"jmp {ALERT_CODE+0x700};"
        )
    )
    assert len(remember) < 0x280 and len(prefer) < 0x300 and len(reset) < 0x80
    # The dry run also returns error 6 for VALID shots: it releases the temporary
    # projectile. Only the solver's real failure branch is evidence of failure.
    # Capture that branch inside an AI preflight, before it reads stale hit data.
    query = asm(
        QUERY, (
            f"mov dword ptr [{FAILED}],0;"
            f"mov dword ptr [{ACTIVE}],1;"
            f"call 0x293834;"
            f"mov dword ptr [{ACTIVE}],0;"
            f"ret;"
        )
    )
    fail = asm(
        FAIL, (
            f"pushfd;"
            f"cmp dword ptr [{ACTIVE}],0;"
            f"je done;"
            f"mov dword ptr [{FAILED}],1;"
            f"done:popfd;"
            f"mov eax,[esp+0x1e];"
            f"sar eax,16;"
            f"jmp 0x2d9bba;"
        )
    )
    # Stock preflight uses a straight ray even for gravity projectiles. Ask the
    # actual firing solver whether an arc exists as well, retaining the original
    # straight-ray result/output for the existing terrain/ally LOS checks.
    solver = asm(
        SOLVER, (
            f"pushfd;"
            f"pushad;"
            f"cmp dword ptr [{ACTIVE}],0;"
            f"je done;"
            f"\n mov esi,[esp+76];"
            f"cmp byte ptr [esi+3],0;"
            f"jne done;"
            f"\n mov eax,[0x4463d8];"
            f"cdq;"
            f"mov ecx,6;"
            f"idiv ecx;"
            f"mov edi,eax;"
            f"\n mov ecx,[esp+24];"
            f"mov esi,[esp+28];"
            f"mov ebp,[esp+20];"
            f"mov ebx,[esp+16];"
            f"\n sub esp,12;"
            f"mov edx,esp;"
            f"push dword ptr [esp+60];"
            f"push edx;"
            f"push edi;"
            f"\n mov eax,esi;"
            f"mov edx,ebp;"
            f"call 0x2d8d04;"
            f"test al,al;"
            f"jnz valid;"
            f"mov dword ptr [{FAILED}],1;"
            f"\n valid:add esp,12;"
            f"done:popad;"
            f"popfd;"
            f"jmp 0x2d8d04;"
        )
    )
    reach = asm(
        REACH, (
            f"pushfd;"
            f"pushad;"
            f"cmp byte ptr [edi+13],1;"
            f"jne done;"
            f"\n mov ebx,[{FAILED}];"
            f"test ebx,ebx;"
            f"jz track;"
            f"mov eax,[esp+64];"
            f"mov byte ptr [eax],1;"
            f"\n track:mov eax,edi;"
            f"sub eax,0x3832f0;"
            f"xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz done;"
            f"test eax,eax;"
            f"jz done;"
            f"cmp eax,60;"
            f"jae done;"
            f"\n imul esi,eax,{STRIDE};"
            f"add esi,{STATE};"
            f"movzx eax,word ptr [edi+11];"
            f"cmp [esi+4],eax;"
            f"jne done;"
            f"\n movzx edx,byte ptr [edi+0xca];"
            f"cmp [esi+8],edx;"
            f"jne done;"
            f"\n test bl,bl;"
            f"jnz failure;"
            f"mov dword ptr [esi+12],0;"
            f"jmp done;"
            f"\n failure:cmp dword ptr [esi+12],0;"
            f"jne done;"
            f"\n mov edx,[0x446ae8];"
            f"mov [esi+12],edx;"
            f"imul eax,eax,37;"
            f"\n mov edx,[eax+0x3c324f];"
            f"mov [esi+24],edx;"
            f"mov edx,[eax+0x3c3253];"
            f"mov [esi+28],edx;"
            f"\n done:popad;"
            f"popfd;"
            f"mov eax,[0x44658c];"
            f"jmp 0x252d6d;"
        )
    )
    pre = asm(PREFLIGHT, fire.preflight_source())
    # A short local retreat after two seconds without either a usable ballistic
    # solution or meaningful movement. Feed destinations to the original route
    # planner; never teleport, bypass collisions, or change scripted/hold orders.
    fallback = asm(
        FALLBACK, (
            f"pushfd;"
            f"pushad;"
            f"mov ebp,eax;"
            f"sub eax,0x3832f0;"
            f"\n xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"test edx,edx;"
            f"jnz done;"
            f"test eax,eax;"
            f"jz done;"
            f"cmp eax,60;"
            f"jae done;"
            f"\n imul edi,eax,{STRIDE};"
            f"add edi,{STATE};"
            f"cmp byte ptr [ebp],0;"
            f"je done;"
            f"\n cmp byte ptr [ebp+5],2;"
            f"jne done;"
            f"cmp byte ptr [ebp+10],0;"
            f"jne done;"
            f"\n cmp byte ptr [ebp+13],1;"
            f"jne done;"
            f"cmp byte ptr [ebp+0xc3],0;"
            f"je done;"
            f"\n cmp dword ptr [ebp+0xad],0;"
            f"je done;"
            f"\n movzx eax,byte ptr [ebp+6];"
            f"cmp eax,32;"
            f"jae done;"
            f"imul eax,eax,368;"
            f"\n cmp word ptr [eax+0x380599],0;"
            f"jne done;"
            f"\n movzx eax,byte ptr [eax+0x3805bb];"
            f"dec eax;"
            f"cmp eax,2;"
            f"ja done;"
            f"\n movzx esi,word ptr [ebp+11];"
            f"cmp [edi+4],esi;"
            f"jne done;"
            f"\n movzx ebx,byte ptr [ebp+0xca];"
            f"cmp [edi+8],ebx;"
            f"jne done;"
            f"\n test ebx,ebx;"
            f"jz done;"
            f"cmp ebx,256;"
            f"jae done;"
            f"\n imul ebx,ebx,37;"
            f"cmp byte ptr [ebx+0x3c3240],0;"
            f"je done;"
            f"\n cmp byte ptr [ebx+0x3c3241],1;"
            f"jne done;"
            f"\n movzx eax,byte ptr [ebx+0x3c3261];"
            f"cmp eax,60;"
            f"jae done;"
            f"imul eax,eax,334;"
            f"add eax,0x3832f0;"
            f"\n movzx edx,word ptr [eax+11];"
            f"cmp [edi+8],edx;"
            f"jne done;"
            f"cmp byte ptr [eax+5],1;"
            f"jne done;"
            f"\n mov dl,[eax];"
            f"or dl,[eax+10];"
            f"jz done;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi];"
            f"cmp eax,15000;"
            f"ja done;"
            f"\n cmp dword ptr [edi+12],0;"
            f"je done;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+12];"
            f"cmp eax,2000;"
            f"jb done;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+16];"
            f"cmp eax,2500;"
            f"jb done;"
            f"\n mov eax,[0x446ae8];"
            f"cmp eax,[ebp+0xd1];"
            f"ja position;"
            f"\n cmp word ptr [ebp+0xd5],3;"
            f"jge done;"
            f"\n position:imul esi,esi,37;"
            f"add esi,0x3c324f;"
            f"\n mov eax,[esi];"
            f"sub eax,[edi+24];"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,0x8000;"
            f"ja progress;"
            f"\n mov eax,[esi+4];"
            f"sub eax,[edi+28];"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,0x8000;"
            f"ja progress;"
            f"\n mov eax,[0x446ae8];"
            f"mov [edi+16],eax;"
            f"\n mov ecx,[esi];"
            f"sub ecx,[ebx+0x3c324f];"
            f"mov edx,[esi+4];"
            f"sub edx,[ebx+0x3c3253];"
            f"\n mov eax,ecx;"
            f"or eax,edx;"
            f"jnz vector;"
            f"mov ecx,1;"
            f"\n vector:mov eax,ecx;"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"mov ebx,eax;"
            f"\n mov edx,[esi+4];"
            f"mov eax,[edi+8];"
            f"imul eax,eax,37;"
            f"sub edx,[eax+0x3c3253];"
            f"\n mov eax,edx;"
            f"push edx;"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"pop edx;"
            f"\n add ebx,ebx;"
            f"cmp eax,ebx;"
            f"jbe keepx;"
            f"xor ecx,ecx;"
            f"\n keepx:shr ebx,1;"
            f"add eax,eax;"
            f"cmp ebx,eax;"
            f"jbe keepy;"
            f"xor edx,edx;"
            f"\n keepy:xor eax,eax;"
            f"test ecx,ecx;"
            f"setnz al;"
            f"shl eax,17;"
            f"test ecx,ecx;"
            f"jns xpos;"
            f"neg eax;"
            f"xpos:mov ecx,eax;"
            f"\n xor eax,eax;"
            f"test edx,edx;"
            f"setnz al;"
            f"shl eax,17;"
            f"test edx,edx;"
            f"jns ypos;"
            f"neg eax;"
            f"ypos:mov edx,eax;"
            f"\n mov eax,[edi+20];"
            f"inc dword ptr [edi+20];"
            f"cmp eax,2;"
            f"jb rotate;"
            f"mov dword ptr [edi+20],0;"
            f"mov eax,2;"
            f"\n rotate:test eax,eax;"
            f"jz destination;"
            f"cmp eax,1;"
            f"jne right;"
            f"neg edx;"
            f"xchg ecx,edx;"
            f"jmp destination;"
            f"\n right:neg ecx;"
            f"xchg ecx,edx;"
            f"\n destination:add ecx,[esi];"
            f"add edx,[esi+4];"
            f"\n cmp ecx,0x10000;"
            f"jb done;"
            f"cmp edx,0x10000;"
            f"jb done;"
            f"cmp ecx,0x1ff0000;"
            f"jae done;"
            f"cmp edx,0x1ff0000;"
            f"jae done;"
            f"\n push 3;"
            f"push edx;"
            f"push ecx;"
            f"mov eax,ebp;"
            f"call 0x24fc04;"
            f"\n progress:mov eax,[0x446ae8];"
            f"mov [edi+12],eax;"
            f"mov eax,[esi];"
            f"mov [edi+24],eax;"
            f"mov eax,[esi+4];"
            f"mov [edi+28],eax;"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    assert REACH + len(reach) <= PREFLIGHT and PREFLIGHT + len(pre) <= FALLBACK and FALLBACK + len(
        fallback
    ) <= SOLVER and SOLVER + len(solver) <= STATE
    assert STATE + STATE_SIZE <= END
    assert len(fail) < 0x40 and len(query) < 0x80
    return [
        (SOLVER, solver), (0x2d9baa, asm(0x2d9baa, f'call {SOLVER}')), (FAIL, fail), (QUERY, query),
        (0x252d63, asm(0x252d63,
                       f'call {QUERY}')), (0x2d9bb3, asm(0x2d9bb3, f'jmp {FAIL}') + b'\x90' * 2),
        (FALLBACK, fallback), (REACH, reach), (PREFLIGHT, bytes(pre)),
        (0x252d68, asm(0x252d68, f'jmp {REACH}')),
        (0x252e42, asm(0x252e42, f'jmp {PREFLIGHT}') + b'\x90'), (HIT, hit), (REMEMBER, remember),
        (SELECT, select), (PREFER, prefer), (RESET, reset),
        (ALERT_SITE, asm(ALERT_SITE, f'jmp {HIT}') + b'\x90' * 2),
        (0x24dfe0, asm(0x24dfe0, f'call {SELECT}')),
        (ALERT_RESET, asm(ALERT_RESET, f'jmp {RESET}'))
    ]


def alert_install(write, read):
    from features.input_views import _install
    result = _install(
        alert_bodies(), {
            ALERT_SITE: ALERT_ORIGINAL,
            ALERT_RESET: ALERT_RESET_ORIGINAL
        },
        write,
        read,
        cold_state=((ALERT_CODE, ALERT_END - ALERT_CODE), )
    )
    if not result.get('already_installed'):
        # Keep the explicit initialization write in the recorded build contract.
        write(ALERT_STATE, bytes(ALERT_END - ALERT_STATE))
        result['ranges'].append((ALERT_STATE, ALERT_END))
    return result


def alert_verify(read):
    from features.input_views import _verify
    return _verify(alert_bodies(), read)


def providers():
    """Code dependencies, excluding the two notification hooks we replace."""
    return [(a, b) for a, b in alert_bodies() if a not in (ALERT_SITE, ALERT_RESET)] + [
        (fire.RESOLVE, fire.selected_weapon_body()), (fire.RANGE, dict(fire.bodies())[fire.RANGE])
    ]


def _dependencies(read):
    for a, b in providers():
        if bytes(read(a, len(b))) != b:
            raise ValueError('Enemy response provider differs at ' + hex(a))


def install(write, read):
    from features.input_views import _install
    _dependencies(read)
    return _install(bodies(), SITES, write, read, cold_state=((CODE, END - CODE), ))


def verify(read):
    from features.input_views import _verify
    _dependencies(read)
    return _verify(bodies(), read)


def predecessor_view(ram):
    """Private regression rollback: code preimages and response-owned state."""
    verify(lambda a, n: ram[a:a + n])
    out = bytearray(ram)
    for a, b in bodies():
        out[a:a + len(b)] = SITES.get(a, bytes(len(b)))
    out[STATE:STATE + STATE_SIZE] = bytes(STATE_SIZE)
    return out


# Allied recent-attacker response. Each row holds hit time, owner, attacker
# and last visibility-check time. It shares the enemy shot-query boundary.
ALLY_CODE = 0x1fcba00
ALLY_END = 0x1fcd000
ALLY_HIT = ALLY_CODE
ALLY_SELECT = ALLY_CODE + 0x40
ALLY_RESET = ALLY_CODE + 0x80
ALLY_REMEMBER = ALLY_CODE + 0x100
ALLY_PREFER = ALLY_CODE + 0x400
ALLY_VISIBLE = ALLY_CODE + 0x900
ALLY_STATE = ALLY_CODE + 0x1000
ALLY_STRIDE = 16
ALLY_STATE_SIZE = 60 * ALLY_STRIDE
ALLY_SITES = {
    0x286c7c: asm(0x286c7c, f'jmp {HIT}') + b'\x90' * 2,
    0x24dfe0: asm(0x24dfe0, f'call {SELECT}'),
    ALERT_RESET: asm(ALERT_RESET, f'jmp {RESET}')
}


def ally_bodies():
    hit = asm(ALLY_HIT, f'call {ALLY_REMEMBER};jmp {HIT};')
    select = asm(
        ALLY_SELECT, (
            f"push eax;"
            f"call {SELECT};"
            f"pushfd;"
            f"pushad;"
            f"mov eax,[esp+36];"
            f"call {ALLY_PREFER};"
            f"popad;"
            f"popfd;"
            f"add esp,4;"
            f"ret;"
        )
    )
    reset = asm(
        ALLY_RESET, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{ALLY_STATE};"
            f"xor eax,eax;"
            f"mov ecx,{ALLY_STATE_SIZE//4};"
            f"rep stosd;"
            f"popad;"
            f"popfd;"
            f"jmp {RESET};"
        )
    )
    remember = asm(
        ALLY_REMEMBER, (
            f"pushfd;"
            f"pushad;"
            f"movzx esi,ax;"
            f"movzx edi,dx;"
            f"\n test esi,esi;"
            f"jz done;"
            f"cmp esi,256;"
            f"jae done;"
            f"cmp si,word ptr [0x441350];"
            f"je done;"
            f"\n test edi,edi;"
            f"jz done;"
            f"cmp edi,256;"
            f"jae done;"
            f"\n imul eax,esi,37;"
            f"cmp byte ptr [eax+0x3c3240],0;"
            f"je done;"
            f"cmp byte ptr [eax+0x3c3241],1;"
            f"jne done;"
            f"\n movzx ebp,byte ptr [eax+0x3c3261];"
            f"test ebp,ebp;"
            f"jz done;"
            f"cmp ebp,60;"
            f"jae done;"
            f"\n imul ebx,ebp,334;"
            f"add ebx,0x3832f0;"
            f"cmp byte ptr [ebx],0;"
            f"je done;"
            f"\n cmp word ptr [ebx+11],si;"
            f"jne done;"
            f"cmp byte ptr [ebx+5],1;"
            f"jne done;"
            f"cmp byte ptr [ebx+10],0;"
            f"jne done;"
            f"\n imul eax,edi,37;"
            f"cmp byte ptr [eax+0x3c3240],0;"
            f"je done;"
            f"\n movzx edx,byte ptr [eax+0x3c3241];"
            f"dec edx;"
            f"cmp edx,3;"
            f"ja done;"
            f"\n movzx edx,byte ptr [eax+0x3c3261];"
            f"test edx,edx;"
            f"jz done;"
            f"cmp edx,60;"
            f"jae done;"
            f"\n imul ebx,edx,334;"
            f"add ebx,0x3832f0;"
            f"cmp byte ptr [ebx],0;"
            f"je done;"
            f"\n cmp word ptr [ebx+11],di;"
            f"jne done;"
            f"cmp byte ptr [ebx+5],2;"
            f"jne done;"
            f"\n imul ebp,ebp,{ALLY_STRIDE};"
            f"add ebp,{ALLY_STATE};"
            f"cmp [ebp+4],esi;"
            f"jne fresh;"
            f"cmp [ebp+8],edi;"
            f"je record;"
            f"\n fresh:mov dword ptr [ebp+12],0;"
            f"\n record:mov eax,[0x446ae8];"
            f"mov [ebp],eax;"
            f"mov [ebp+4],esi;"
            f"mov [ebp+8],edi;"
            f"\n done:popad;"
            f"popfd;"
            f"ret;"
        )
    )
    prefer = asm(
        ALLY_PREFER, (
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"\n mov ebp,eax;"
            f"sub eax,0x3832f0;"
            f"xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz no;"
            f"test eax,eax;"
            f"jz no;"
            f"cmp eax,60;"
            f"jae no;"
            f"\n imul edi,eax,{ALLY_STRIDE};"
            f"add edi,{ALLY_STATE};"
            f"cmp byte ptr [ebp],0;"
            f"je no;"
            f"\n cmp byte ptr [ebp+5],1;"
            f"jne no;"
            f"cmp byte ptr [ebp+10],0;"
            f"jne no;"
            f"\n cmp byte ptr [ebp+13],1;"
            f"jne no;"
            f"cmp byte ptr [ebp+0xc3],0;"
            f"je no;"
            f"\n movzx ebx,word ptr [ebp+11];"
            f"cmp bx,word ptr [0x441350];"
            f"je no;"
            f"cmp [edi+4],ebx;"
            f"jne no;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi];"
            f"cmp eax,5000;"
            f"ja no;"
            f"\n movzx eax,byte ptr [ebp+6];"
            f"cmp eax,32;"
            f"jae no;"
            f"imul eax,eax,368;"
            f"\n movzx edx,byte ptr [eax+0x3805bb];"
            f"cmp edx,1;"
            f"jb no;"
            f"cmp edx,9;"
            f"jae no;"
            f"cmp edx,5;"
            f"je no;"
            f"cmp edx,6;"
            f"je no;"
            f"\n cmp word ptr [eax+0x380599],0;"
            f"je target;"
            f"\n cmp edx,8;"
            f"jne no;"
            f"mov dx,word ptr [0x441350];"
            f"cmp word ptr [eax+0x380599],dx;"
            f"jne no;"
            f"\n target:mov esi,[edi+8];"
            f"test esi,esi;"
            f"jz no;"
            f"cmp esi,256;"
            f"jae no;"
            f"\n mov eax,esi;"
            f"cmp [ebp+0xca],al;"
            f"je no;"
            f"\n imul edx,esi,37;"
            f"cmp byte ptr [edx+0x3c3240],0;"
            f"je no;"
            f"\n movzx eax,byte ptr [edx+0x3c3241];"
            f"dec eax;"
            f"cmp eax,3;"
            f"ja no;"
            f"\n movzx ebx,byte ptr [edx+0x3c3261];"
            f"test ebx,ebx;"
            f"jz no;"
            f"cmp ebx,60;"
            f"jae no;"
            f"\n imul eax,ebx,334;"
            f"add eax,0x3832f0;"
            f"cmp byte ptr [eax],0;"
            f"je no;"
            f"\n cmp word ptr [eax+11],si;"
            f"jne no;"
            f"cmp byte ptr [eax+5],2;"
            f"jne no;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+12];"
            f"cmp eax,500;"
            f"jb no;"
            f"\n mov eax,[0x446ae8];"
            f"mov [edi+12],eax;"
            f"\n movzx edx,byte ptr [ebp+0xca];"
            f"test edx,edx;"
            f"jz candidate;"
            f"\n mov eax,ebp;"
            f"call {ALLY_VISIBLE};"
            f"test eax,eax;"
            f"jnz no;"
            f"\n candidate:mov eax,ebp;"
            f"mov edx,esi;"
            f"call {ALLY_VISIBLE};"
            f"test eax,eax;"
            f"jz no;"
            f"\n mov eax,esi;"
            f"mov [ebp+0xca],al;"
            f"mov eax,ebx;"
            f"mov [ebp+0xc9],al;"
            f"\n imul eax,ebx,334;"
            f"mov al,[eax+0x3832f6];"
            f"mov [ebp+0xcb],al;"
            f"\n imul edx,esi,37;"
            f"mov eax,[edx+0x3c324f];"
            f"sar eax,16;"
            f"mov [ebp+0xcc],ax;"
            f"\n mov eax,[edx+0x3c3253];"
            f"sar eax,16;"
            f"mov [ebp+0xce],ax;"
            f"\n mov eax,[0x446ae8];"
            f"mov [ebp+0xd7],eax;"
            f"mov [ebp+0xc5],eax;"
            f"\n mov byte ptr [ebp+0xc4],0;"
            f"mov dword ptr [ebp+0x106],0;"
            f"\n mov eax,1;"
            f"jmp done;"
            f"\n no:xor eax,eax;"
            f"done:pop ebp;"
            f"pop edi;"
            f"pop esi;"
            f"pop edx;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    visible = asm(
        ALLY_VISIBLE, (
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"push ebp;"
            f"\n mov esi,eax;"
            f"mov edi,edx;"
            f"test edi,edi;"
            f"jz no;"
            f"cmp edi,256;"
            f"jae no;"
            f"\n imul eax,edi,37;"
            f"cmp byte ptr [eax+0x3c3240],0;"
            f"je no;"
            f"\n movzx ebp,word ptr [esi+11];"
            f"mov edx,ebp;"
            f"call 0x1dc8800;"
            f"test eax,eax;"
            f"jz no;"
            f"\n movzx ecx,byte ptr [eax];"
            f"test ecx,ecx;"
            f"jz no;"
            f"cmp ecx,32;"
            f"ja no;"
            f"\n imul ecx,ecx,36;"
            f"movzx ecx,word ptr [ecx+0x39511e];"
            f"\n imul eax,ebp,37;"
            f"add eax,0x3c324f;"
            f"imul edx,edi,37;"
            f"add edx,0x3c324f;"
            f"\n call {fire.RANGE};"
            f"test eax,eax;"
            f"jnz no;"
            f"\n mov eax,ebp;"
            f"mov edx,edi;"
            f"xor ebx,ebx;"
            f"call {QUERY};"
            f"\n cmp dword ptr [{FAILED}],0;"
            f"jne no;"
            f"\n xor eax,eax;"
            f"cmp word ptr [0x446598],di;"
            f"sete al;"
            f"jmp done;"
            f"\n no:xor eax,eax;"
            f"done:pop ebp;"
            f"pop edi;"
            f"pop esi;"
            f"pop edx;"
            f"pop ecx;"
            f"pop ebx;"
            f"ret;"
        )
    )
    assert len(hit) < 0x40 and len(select) < 0x40 and len(reset) < 0x80 and len(remember) < 0x300
    assert len(prefer) < 0x500 and len(visible) < 0x700 and ALLY_STATE + ALLY_STATE_SIZE <= ALLY_END
    return [
        (ALLY_HIT, hit), (ALLY_SELECT, select), (ALLY_RESET, reset), (ALLY_REMEMBER, remember),
        (ALLY_PREFER, prefer), (ALLY_VISIBLE, visible),
        (0x286c7c, asm(0x286c7c, f'jmp {ALLY_HIT}') + b'\x90' * 2),
        (0x24dfe0, asm(0x24dfe0, f'call {ALLY_SELECT}')),
        (ALERT_RESET, asm(ALERT_RESET, f'jmp {ALLY_RESET}'))
    ]


def ally_providers():
    """Retained notification/firing providers and enemy response helper bodies.

    Shared entry hooks are checked as transition preimages, not dependencies:
    allied response replaces three of them and later consumers wrap others.
    """
    return providers() + [(a, b) for a, b in bodies() if CODE <= a < STATE]


def _ally_dependencies(read):
    for a, b in ally_providers():
        if bytes(read(a, len(b))) != b:
            raise ValueError('Allied response provider differs at ' + hex(a))


def ally_install(write, read):
    from features.input_views import _install
    _ally_dependencies(read)
    return _install(
        ally_bodies(), ALLY_SITES, write, read, cold_state=((ALLY_CODE, ALLY_END - ALLY_CODE), )
    )


def ally_verify(read):
    from features.input_views import _verify
    _ally_dependencies(read)
    return _verify(ally_bodies(), read)


def ally_predecessor_view(ram):
    """Private regression rollback of allied hooks and owned memory only."""
    ally_verify(lambda a, n: ram[a:a + n])
    out = bytearray(ram)
    for a, b in ally_bodies():
        out[a:a + len(b)] = ALLY_SITES.get(a, bytes(len(b)))
    out[ALLY_STATE:ALLY_STATE + ALLY_STATE_SIZE] = bytes(ALLY_STATE_SIZE)
    return out


# Timing tables and their reset bodies have one owner.
from features.actor_timing import (
    IDLE_MISSION_RESET, AVOIDANCE_SLOT_RESET, idle_mission_reset_body, avoidance_slot_reset_body
)

# Repeated route failure, progress tracking and local planner retries.
RECOVERY_CODE = 0x1e50400
RECOVERY_END = 0x1e51000
RECOVERY_STATE = 0x1e3c600
RECOVERY_STATE_END = 0x1e3d000
RECOVERY_STRIDE = 32
RECOVERY_STATE_SIZE = 60 * RECOVERY_STRIDE
RECOVERY_FINISH = RECOVERY_CODE
RECOVERY_SELECT = RECOVERY_CODE + 0x80
RECOVERY_VALID = RECOVERY_CODE + 0x100
RECOVERY_OBSERVE = RECOVERY_CODE + 0x300
RECOVERY_UPDATE = RECOVERY_CODE + 0x500
RECOVERY_RESET = RECOVERY_CODE + 0x900
RECOVERY_SLOTRESET = RECOVERY_CODE + 0x980
RECOVERY_SITES = {
    0x24fe55: bytes.fromhex('894424188b442416'),
    0x24dfe0: asm(0x24dfe0, f'call {ALLY_SELECT};'),
    0x249b2c: asm(0x249b2c, f'jmp {IDLE_MISSION_RESET}') + b'\x90' * 2,
    0x24b52d: asm(0x24b52d, f'jmp {AVOIDANCE_SLOT_RESET}') + b'\x90' * 1
}


def recovery_bodies():
    out = []

    def emit(a, s, n):
        b = asm(a, s)
        assert len(b) <= n, (hex(a), len(b))
        out.append((a, b))

    emit(
        RECOVERY_FINISH, (
            f"pushfd;"
            f"pushad;"
            f"mov edx,eax;"
            f"mov eax,esi;"
            f"call {RECOVERY_OBSERVE};"
            f"popad;"
            f"popfd;"
            f"mov [esp+0x18],eax;"
            f"mov eax,[esp+0x16];"
            f"jmp 0x24fe5d;"
        ), 0x80
    )
    emit(
        RECOVERY_SELECT, (
            f"push eax;"
            f"call {ALLY_SELECT};"
            f"pushfd;"
            f"pushad;"
            f"mov eax,[esp+36];"
            f"call {RECOVERY_UPDATE};"
            f"popad;"
            f"popfd;"
            f"lea esp,[esp+4];"
            f"ret;"
        ), 0x80
    )
    # EAX=AI. Return EAX=1 plus EBP=AI, EDI=row, ESI=object, EBX=target object.
    emit(
        RECOVERY_VALID, (
            f"mov ebp,eax;"
            f"sub eax,0x3832f0;"
            f"xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"\n test edx,edx;"
            f"jnz no;"
            f"test eax,eax;"
            f"jz no;"
            f"cmp eax,60;"
            f"jae no;"
            f"shl eax,5;"
            f"lea edi,[eax+{RECOVERY_STATE}];"
            f"\n cmp byte ptr [ebp],0;"
            f"je no;"
            f"cmp byte ptr [ebp+5],2;"
            f"jne no;"
            f"cmp byte ptr [ebp+10],0;"
            f"jne no;"
            f"\n cmp byte ptr [ebp+13],1;"
            f"jne no;"
            f"cmp byte ptr [ebp+0xc3],0;"
            f"je no;"
            f"cmp dword ptr [ebp+0xad],0;"
            f"je no;"
            f"\n movzx eax,byte ptr [ebp+6];"
            f"cmp eax,32;"
            f"jae no;"
            f"imul eax,eax,368;"
            f"\n cmp word ptr [eax+0x380599],0;"
            f"jne no;"
            f"movzx ecx,byte ptr [eax+0x3805bb];"
            f"dec ecx;"
            f"cmp ecx,2;"
            f"ja no;"
            f"\n movzx esi,word ptr [ebp+11];"
            f"test esi,esi;"
            f"jz no;"
            f"cmp esi,256;"
            f"jae no;"
            f"imul esi,esi,37;"
            f"add esi,0x3c3240;"
            f"\n cmp byte ptr [esi],0;"
            f"je no;"
            f"cmp byte ptr [esi+1],1;"
            f"jne no;"
            f"movzx ecx,byte ptr [esi+33];"
            f"imul ecx,ecx,334;"
            f"add ecx,0x3832f0;"
            f"cmp ecx,ebp;"
            f"jne no;"
            f"\n movzx ebx,byte ptr [ebp+0xca];"
            f"test ebx,ebx;"
            f"jz no;"
            f"cmp ebx,256;"
            f"jae no;"
            f"\n imul ebx,ebx,37;"
            f"add ebx,0x3c3240;"
            f"cmp byte ptr [ebx],0;"
            f"je no;"
            f"cmp byte ptr [ebx+1],1;"
            f"jne no;"
            f"\n movzx eax,byte ptr [ebx+33];"
            f"cmp eax,60;"
            f"jae no;"
            f"imul eax,eax,334;"
            f"add eax,0x3832f0;"
            f"cmp byte ptr [eax+5],1;"
            f"jne no;"
            f"movzx ecx,byte ptr [ebp+0xca];"
            f"cmp word ptr [eax+11],cx;"
            f"jne no;"
            f"mov cl,[eax];"
            f"or cl,[eax+10];"
            f"jz no;"
            f"\n mov eax,1;"
            f"ret;"
            f"no:xor eax,eax;"
            f"ret;"
        ), 0x200
    )
    emit(
        RECOVERY_OBSERVE, (
            f"push edx;"
            f"call {RECOVERY_VALID};"
            f"pop edx;"
            f"test eax,eax;"
            f"jz done;"
            f"\n movzx eax,word ptr [ebp+11];"
            f"cmp [edi],eax;"
            f"jne identity;"
            f"movzx ecx,byte ptr [ebp+0xca];"
            f"cmp [edi+4],ecx;"
            f"je result;"
            f"\n identity:mov [edi],eax;"
            f"movzx eax,byte ptr [ebp+0xca];"
            f"mov [edi+4],eax;"
            f"xor eax,eax;"
            f"mov [edi+8],eax;"
            f"mov [edi+12],eax;"
            f"mov [edi+24],eax;"
            f"mov [edi+28],eax;"
            f"\n result:cmp edx,-1;"
            f"je failed;"
            f"mov dword ptr [edi+8],0;"
            f"mov dword ptr [edi+12],0;"
            f"ret;"
            f"\n failed:mov ecx,[0x446ae8];"
            f"mov eax,ecx;"
            f"sub eax,[edi+12];"
            f"js fresh;"
            f"cmp eax,2500;"
            f"ja fresh;"
            f"cmp dword ptr [edi+8],0;"
            f"je fresh;"
            f"\n mov eax,[esi+15];"
            f"sub eax,[edi+16];"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,0x8000;"
            f"ja fresh;"
            f"\n mov eax,[esi+19];"
            f"sub eax,[edi+20];"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,0x8000;"
            f"ja fresh;"
            f"jmp stamp;"
            f"\n fresh:mov [edi+8],ecx;"
            f"mov eax,[esi+15];"
            f"mov [edi+16],eax;"
            f"mov eax,[esi+19];"
            f"mov [edi+20],eax;"
            f"\n stamp:mov [edi+12],ecx;"
            f"done:ret;"
        ), 0x200
    )
    emit(
        RECOVERY_UPDATE, (
            f"call {RECOVERY_VALID};"
            f"test eax,eax;"
            f"jz done;"
            f"\n movzx eax,word ptr [ebp+11];"
            f"cmp [edi],eax;"
            f"jne done;"
            f"movzx eax,byte ptr [ebp+0xca];"
            f"cmp [edi+4],eax;"
            f"jne done;"
            f"\n cmp dword ptr [edi+8],0;"
            f"je done;"
            f"mov eax,[0x446ae8];"
            f"sub eax,[edi+8];"
            f"cmp eax,5000;"
            f"jb done;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+12];"
            f"cmp eax,2500;"
            f"ja done;"
            f"\n mov eax,[0x446ae8];"
            f"sub eax,[edi+24];"
            f"js done;"
            f"\n cmp word ptr [ebp+0xd5],3;"
            f"jg done;"
            f"\n mov eax,[esi+15];"
            f"sub eax,[edi+16];"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,0x8000;"
            f"ja done;"
            f"\n mov eax,[esi+19];"
            f"sub eax,[edi+20];"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"cmp eax,0x8000;"
            f"ja done;"
            f"\n mov ecx,[esi+15];"
            f"sub ecx,[ebx+15];"
            f"mov edx,[esi+19];"
            f"sub edx,[ebx+19];"
            f"\n mov eax,ecx;"
            f"or eax,edx;"
            f"jnz vector;"
            f"mov ecx,1;"
            f"\n vector:mov eax,ecx;"
            f"push edx;"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"pop edx;"
            f"mov ebx,eax;"
            f"\n mov eax,edx;"
            f"push edx;"
            f"cdq;"
            f"xor eax,edx;"
            f"sub eax,edx;"
            f"pop edx;"
            f"\n add ebx,ebx;"
            f"cmp eax,ebx;"
            f"jbe keepx;"
            f"xor ecx,ecx;"
            f"\n keepx:shr ebx,1;"
            f"add eax,eax;"
            f"cmp ebx,eax;"
            f"jbe keepy;"
            f"xor edx,edx;"
            f"\n keepy:xor eax,eax;"
            f"test ecx,ecx;"
            f"setnz al;"
            f"shl eax,17;"
            f"test ecx,ecx;"
            f"jns xpos;"
            f"neg eax;"
            f"xpos:mov ecx,eax;"
            f"\n xor eax,eax;"
            f"test edx,edx;"
            f"setnz al;"
            f"shl eax,17;"
            f"test edx,edx;"
            f"jns ypos;"
            f"neg eax;"
            f"ypos:mov edx,eax;"
            f"\n mov eax,[edi+28];"
            f"inc eax;"
            f"cmp eax,3;"
            f"jb cycle;"
            f"xor eax,eax;"
            f"cycle:mov [edi+28],eax;"
            f"\n test eax,eax;"
            f"jz destination;"
            f"cmp eax,1;"
            f"jne right;"
            f"neg edx;"
            f"xchg ecx,edx;"
            f"jmp destination;"
            f"\n right:neg ecx;"
            f"xchg ecx,edx;"
            f"\n destination:add ecx,[esi+15];"
            f"add edx,[esi+19];"
            f"\n mov eax,[0x446ae8];"
            f"add eax,2500;"
            f"mov [edi+24],eax;"
            f"\n cmp ecx,0x10000;"
            f"jb done;"
            f"cmp edx,0x10000;"
            f"jb done;"
            f"cmp ecx,0x1ff0000;"
            f"jae done;"
            f"cmp edx,0x1ff0000;"
            f"jae done;"
            f"\n push 3;"
            f"push edx;"
            f"push ecx;"
            f"mov eax,ebp;"
            f"call 0x24fc04;"
            f"test al,al;"
            f"jz done;"
            f"\n mov eax,[0x446ae8];"
            f"add eax,8000;"
            f"mov [edi+24],eax;"
            f"mov dword ptr [edi+8],0;"
            f"mov dword ptr [edi+12],0;"
            f"\n done:ret;"
        ), 0x400
    )
    emit(
        RECOVERY_RESET, (
            f"pushfd;"
            f"pushad;"
            f"cld;"
            f"mov edi,{RECOVERY_STATE};"
            f"xor eax,eax;"
            f"mov ecx,{RECOVERY_STATE_SIZE//4};"
            f"rep stosd;"
            f"popad;"
            f"popfd;"
            f"jmp {IDLE_MISSION_RESET};"
        ), 0x80
    )
    emit(
        RECOVERY_SLOTRESET, (
            f"pushfd;"
            f"pushad;"
            f"mov eax,esi;"
            f"sub eax,0x3832f0;"
            f"xor edx,edx;"
            f"mov ecx,334;"
            f"div ecx;"
            f"test edx,edx;"
            f"jnz done;"
            f"cmp eax,60;"
            f"jae done;"
            f"\n shl eax,5;"
            f"lea edi,[eax+{RECOVERY_STATE}];"
            f"xor eax,eax;"
            f"mov ecx,8;"
            f"cld;"
            f"rep stosd;"
            f"done:popad;"
            f"popfd;"
            f"jmp {AVOIDANCE_SLOT_RESET};"
        ), 0x80
    )
    out += [
        (0x24fe55, asm(0x24fe55, f'jmp {RECOVERY_FINISH}') + b'\x90' * 3),
        (0x24dfe0, asm(0x24dfe0, f'call {RECOVERY_SELECT}'))
    ]
    for site, target in ((0x249b2c, RECOVERY_RESET), (0x24b52d, RECOVERY_SLOTRESET)):
        out.append((site, asm(site, f'jmp {target}') + b'\x90' * (len(RECOVERY_SITES[site]) - 5)))
    return out


def recovery_providers():
    return ally_providers() + [(a, b) for a, b in ally_bodies() if ALLY_CODE <= a < ALLY_STATE] + [
        (IDLE_MISSION_RESET, idle_mission_reset_body()),
        (AVOIDANCE_SLOT_RESET, avoidance_slot_reset_body())
    ]


def _recovery_dependencies(read):
    for a, b in recovery_providers():
        if bytes(read(a, len(b))) != b:
            raise ValueError('Route recovery provider differs at ' + hex(a))


def recovery_install(write, read):
    from features.input_views import _install
    _recovery_dependencies(read)
    return _install(
        recovery_bodies(),
        RECOVERY_SITES,
        write,
        read,
        cold_state=(
            (RECOVERY_CODE, RECOVERY_END - RECOVERY_CODE),
            (RECOVERY_STATE, RECOVERY_STATE_END - RECOVERY_STATE)
        )
    )


def recovery_verify(read):
    from features.input_views import _verify
    _recovery_dependencies(read)
    return _verify(recovery_bodies(), read)


def recovery_predecessor_view(ram):
    """Private rollback restores hooks and clears only owned reservations."""
    recovery_verify(lambda a, n: ram[a:a + n])
    out = bytearray(ram)
    for a, b in RECOVERY_SITES.items():
        out[a:a + len(b)] = b
    out[RECOVERY_CODE:RECOVERY_END] = bytes(RECOVERY_END - RECOVERY_CODE)
    out[RECOVERY_STATE:RECOVERY_STATE_END] = bytes(RECOVERY_STATE_END - RECOVERY_STATE)
    return out


ROUTE_RESET_SITE = 0x252fd5
ROUTE_RESET_END = 0x252fde
ROUTE_RESET_CODE = 0x1e53000
ROUTE_RESET_ORIGINAL = bytes.fromhex('8b82ad000000c60000')


def route_reset_bodies():
    body = asm(
        ROUTE_RESET_CODE, (
            "mov eax,[edx+0xad];"
            "pushfd;"
            "test eax,eax;"
            "jz absent;"
            "\n mov byte ptr [eax],0;"
            "absent:popfd;"
            "jmp 0x252fde;"
        )
    )
    assert len(body) < 0x40
    return [
        (ROUTE_RESET_CODE, body),
        (ROUTE_RESET_SITE, asm(ROUTE_RESET_SITE, f'jmp {ROUTE_RESET_CODE}') + b'\x90' * 4)
    ]


ROUTE_PLAN_SITE = 0x24fd52
ROUTE_PLAN_END = 0x24fd57
ROUTE_PLAN_CODE = 0x1e53040
ROUTE_PLAN_ORIGINAL = bytes.fromhex('a1e86a4400')


def route_plan_bodies():
    body = asm(
        ROUTE_PLAN_CODE, (
            "cmp dword ptr [esi+0xad],0;"
            "je absent;"
            "\n    mov eax,[0x446ae8];"
            "jmp 0x24fd57;"
            "\n    absent:jmp 0x24ff16;"
        )
    )
    assert len(body) < 0x40
    return [
        (ROUTE_PLAN_CODE, body), (ROUTE_PLAN_SITE, asm(ROUTE_PLAN_SITE, f'jmp {ROUTE_PLAN_CODE}'))
    ]


def route_pieces(*, reset=True, planner=True):
    """Stationary actors have neither resettable storage nor a usable planner."""
    return (route_reset_bodies() if reset else []) + (route_plan_bodies() if planner else [])


def route_install(write, read, *, reset=True, planner=True):
    from features.input_views import _install
    sites = {}
    if reset:
        sites[ROUTE_RESET_SITE] = ROUTE_RESET_ORIGINAL
    if planner:
        sites[ROUTE_PLAN_SITE] = ROUTE_PLAN_ORIGINAL
    # Validate both independent hooks before writing either one. Live-route
    # actors continue through the original planner without movement changes.
    return _install(route_pieces(reset=reset, planner=planner), sites, write, read)


def route_verify(read, *, reset=True, planner=True):
    from features.input_views import _verify
    return _verify(route_pieces(reset=reset, planner=planner), read)


# Let a confirmed allied hit invoke the original investigation out to PB range.
INVESTIGATE_CODE = 0x1fc8000

INVESTIGATE_SITE = 0x2509c3

INVESTIGATE_ORIGINAL = bytes.fromhex('39d87e0b30c0')

INVESTIGATE_HIT_RETURN = 0x24caf3


def investigate_bodies():
    s = (
        f"cmp ebx,0x190000;"
        f"jne original;"
        f"cmp dword ptr [esp+0x44],{INVESTIGATE_HIT_RETURN};"
        f"jne original;"
        f"\n pushad;"
        f"movzx edi,word ptr [esp+0x4c];"
        f"movzx esi,word ptr [esp+0x48];"
        f"\n test edi,edi;"
        f"jz no;"
        f"cmp edi,300;"
        f"jae no;"
        f"test esi,esi;"
        f"jz no;"
        f"cmp esi,300;"
        f"jae no;"
        f"\n imul edx,edi,37;"
        f"cmp byte ptr [edx+0x3c3240],0;"
        f"je no;"
        f"cmp byte ptr [edx+0x3c3241],1;"
        f"jne no;"
        f"\n movzx ecx,byte ptr [edx+0x3c3261];"
        f"test ecx,ecx;"
        f"jz no;"
        f"cmp ecx,60;"
        f"jae no;"
        f"\n imul edx,ecx,334;"
        f"add edx,0x3832f0;"
        f"cmp byte ptr [edx],0;"
        f"je no;"
        f"cmp byte ptr [edx+10],0;"
        f"jne no;"
        f"\n cmp word ptr [edx+11],di;"
        f"jne no;"
        f"cmp byte ptr [edx+5],2;"
        f"jne no;"
        f"\n cmp [ecx*8+0x1e5bc04],edi;"
        f"jne no;"
        f"mov eax,[0x446ae8];"
        f"sub eax,[ecx*8+0x1e5bc00];"
        f"cmp eax,2000;"
        f"ja no;"
        f"\n imul edx,esi,37;"
        f"cmp byte ptr [edx+0x3c3240],0;"
        f"je no;"
        f"\n movzx ecx,byte ptr [edx+0x3c3261];"
        f"cmp ecx,60;"
        f"jae no;"
        f"imul edx,ecx,334;"
        f"add edx,0x3832f0;"
        f"\n cmp word ptr [edx+11],si;"
        f"jne no;"
        f"cmp byte ptr [edx+5],1;"
        f"jne no;"
        f"\n imul edi,edi,37;"
        f"imul esi,esi,37;"
        f"\n mov eax,[edi+0x3c324f];"
        f"sub eax,[esi+0x3c324f];"
        f"imul eax;"
        f"mov ebx,eax;"
        f"mov ebp,edx;"
        f"\n mov eax,[edi+0x3c3253];"
        f"sub eax,[esi+0x3c3253];"
        f"imul eax;"
        f"add ebx,eax;"
        f"adc ebp,edx;"
        f"\n cmp ebp,900;"
        f"ja no;"
        f"jb accepted;"
        f"test ebx,ebx;"
        f"jnz no;"
        f"\n accepted:popad;"
        f"jmp 0x2509d2;"
        f"\n no:popad;"
        f"\n original:cmp eax,ebx;"
        f"jle 0x2509d2;"
        f"xor al,al;"
        f"jmp 0x2509c9;"
    )
    b = asm(INVESTIGATE_CODE, s)
    assert len(b) < 0x200
    return [
        (INVESTIGATE_CODE, b),
        (INVESTIGATE_SITE, asm(INVESTIGATE_SITE, f'jmp {INVESTIGATE_CODE}') + b'\x90')
    ]


def investigate_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        investigate_bodies(), {INVESTIGATE_SITE: INVESTIGATE_ORIGINAL},
        write,
        read,
        cold_state=((INVESTIGATE_CODE, 0x200), )
    )


def investigate_verify(read):
    from features.input_views import _verify
    return _verify(investigate_bodies(), read)
