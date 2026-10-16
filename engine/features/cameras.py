"""Keep teammate views aligned with their suits and pace damaged-camera noise.

Visibility, facing and interference helpers share the original camera slots.
The rendering paths support both logical HUD pixels and enlarged native views,
including the Pirate suit's uneven panel width.
"""
import re
from patch_support import asm
from features.render_views import assemble as code

VISIBILITY_SITES = (0x9d8000, 0x1e3a000, 0x1e45a00)
VISIBILITY_ENTRIES = (0x1e4a000, 0x1e4a100, 0x1e4a200)


def visibility_prefix(site):
    # Complete displaced instructions shared by all three map/camera mergers.
    return asm(site, 'pushfd;pushad;cld;cmp byte ptr [0x1d0d449],0x6b')


def visibility_bodies():
    out = []
    for site, entry in zip(VISIBILITY_SITES, VISIBILITY_ENTRIES):
        old = visibility_prefix(site)
        source = (
            "pushfd;"
            "cmp byte ptr [0x38fbfe],0;"
            "je visible;"
            "\n        test byte ptr [0x35aef0],1;"
            "jz visible;"
        )
        if site == VISIBILITY_SITES[-1]:
            source += (
                "push eax;"
                "mov eax,[0x1e3c58c];"
                "cmp eax,[0x389df4];"
                "pop eax;"
                "je visible;"
            )
        source += 'popfd;ret;visible:popfd;'
        gate = code(entry, source)
        gate += old + asm(entry + len(gate) + len(old), f'jmp {site+len(old)}')
        if len(gate) >= 0x100:
            raise ValueError('Camera visibility gate exceeds reservation')
        out.extend(((entry, gate), (site, asm(site, f'jmp {entry}') + b'\x90' * (len(old) - 5))))
    return out


def visibility_install(write, read):
    bodies = visibility_bodies()
    old = {a: visibility_prefix(a) for a in VISIBILITY_SITES}
    before = tuple(old.get(a, bytes(len(b))) for a, b in bodies)
    current = tuple(bytes(read(a, len(b))) for a, b in bodies)
    for a, b in bodies:
        if a in VISIBILITY_ENTRIES:
            tail = bytes(read(a + len(b), 0x100 - len(b)))
            if tail != bytes(0x100 - len(b)):
                raise ValueError('Camera visibility reservation differs')
    if current == tuple(b for a, b in bodies):
        return dict(already_installed=True, ranges=[])
    if current != before:
        raise ValueError('Camera visibility providers differ')
    for a, b in bodies:
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in bodies])


def visibility_predecessor_view(r):

    def reject(a, b):
        raise ValueError('Camera visibility installation incomplete')

    visibility_install(reject, lambda a, n: r[a:a + n])
    shadow = bytearray(r)
    for a, b in visibility_bodies():
        shadow[a:a + len(b)] = visibility_prefix(a) if a in VISIBILITY_SITES else bytes(len(b))
    return shadow


def high_source():
    from features.hud import SLOTS, STATE, LOW, SAVE, CANVAS, MASK, TARGET
    """Render a secondary view into its owned slot and save its logical reference pixels."""
    return (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov eax,edx;"
        f" sub eax,0x390010;"
        f" xor edx,edx;"
        f" mov ecx,186;"
        f" div ecx;"
        f"\n test edx,edx;"
        f" jnz other;"
        f" cmp eax,3;"
        f" jae other;"
        f"\n mov edx,eax;"
        f" shl edx,7;"
        f" add edx,{SLOTS};"
        f" mov dword ptr [{STATE}],edx;"
        f"\n mov dword ptr [edx],0;"
        f" mov ebp,edx;"
        f"\n mov ecx,eax;"
        f" shl ecx,5;"
        f" movzx ecx,byte ptr [ecx+0x38fc12];"
        f" mov dword ptr [ebp+80],ecx;"
        f"\n mov ecx,dword ptr [eax*4+0x389df8];"
        f" mov dword ptr [ebp+12],ecx;"
        f"\n movzx ebx,byte ptr [ecx+0x20];"
        f" and ebx,0x40;"
        f" mov dword ptr [ebp+88],ebx;"
        f"\n mov ecx,dword ptr [ecx+0x1c];"
        f" mov dword ptr [ebp+68],ecx;"
        f"\n mov ecx,dword ptr [esp+20];"
        f" mov dword ptr [ebp+8],ecx;"
        f"\n mov esi,dword ptr [ecx+28];"
        f" cmp word ptr [esi+12],320;"
        f" jne fallback;"
        f"\n movzx ebx,word ptr [esi+8];"
        f" cmp ebx,4;"
        f" jb fallback;"
        f" cmp ebx,100;"
        f" ja fallback;"
        f"\n mov dword ptr [ebp+32],ebx;"
        f"\n movzx edi,word ptr [esi+10];"
        f" test edi,edi;"
        f" jz fallback;"
        f" cmp edi,128;"
        f" ja fallback;"
        f"\n mov dword ptr [ebp+36],edi;"
        f"\n mov eax,dword ptr [0x446f78];"
        f" mov dword ptr [ebp+16],eax;"
        f"\n mov edx,dword ptr [esi];"
        f" sub edx,eax;"
        f" cmp edx,0x1f400;"
        f" jae fallback;"
        f"\n mov dword ptr [ebp+20],edx;"
        f" mov eax,edx;"
        f" xor edx,edx;"
        f" mov ecx,320;"
        f" div ecx;"
        f"\n mov dword ptr [ebp+24],edx;"
        f" mov dword ptr [ebp+28],eax;"
        f"\n add ebx,edx;"
        f" cmp ebx,320;"
        f" ja fallback;"
        f" add edi,eax;"
        f" cmp edi,400;"
        f" ja fallback;"
        f"\n imul eax,eax,3;"
        f"inc eax;"
        f"shr eax,1;"
        f"mov dword ptr [ebp+44],eax;"
        f"\n imul edx,edx,5;"
        f" inc edx;"
        f" shr edx,1;"
        f" mov dword ptr [ebp+40],edx;"
        f"\n imul ebx,ebx,5;"
        f" inc ebx;"
        f" shr ebx,1;"
        f" sub ebx,edx;"
        f" mov dword ptr [ebp+48],ebx;"
        f"\n imul edi,edi,3;"
        f"inc edi;"
        f"shr edi,1;"
        f"sub edi,[ebp+44];"
        f"mov [ebp+52],edi;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f" je mode_ready;"
        f"\n pushad;"
        f" mov dx,0x3c7;"
        f" xor eax,eax;"
        f" out dx,al;"
        f" add dx,2;"
        f" mov edi,0x9aa4e8;"
        f" mov ecx,768;"
        f"\n readpal: in al,dx;"
        f" stosb;"
        f" loop readpal;"
        f"\n mov eax,0x4f02;"
        f" mov ebx,0x4103;"
        f" int 0x10;"
        f"\n mov dx,0x3c8;"
        f" xor eax,eax;"
        f" out dx,al;"
        f" inc dx;"
        f" mov esi,0x9aa4e8;"
        f" mov ecx,768;"
        f"\n writepal: lodsb;"
        f" out dx,al;"
        f" loop writepal;"
        f" popad;"
        f"\n mode_ready:\n mov esi,{LOW};"
        f" mov edi,{SAVE};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [0x44b1ac];"
        f" mov dword ptr [0x1e3c160],eax;"
        f"\n mov esi,dword ptr [ebp+8];"
        f" mov edi,{LOW};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,dword ptr [0x9a3d24];"
        f" mov edi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [ebp+56];"
        f" mov dword ptr [{CANVAS}],eax;"
        f"\n mov eax,dword ptr [ebp+48];"
        f" mov word ptr [0x9c34f0],ax;"
        f" mov word ptr [0x9c34f4],ax;"
        f"\n shl eax,16;"
        f" mov dword ptr [0x9c351c],eax;"
        f"\n mov eax,dword ptr [ebp+52];"
        f" mov word ptr [0x9c34f2],ax;"
        f"\n shl eax,16;"
        f" mov dword ptr [0x9c3520],eax;"
        f"\n mov edi,dword ptr [ebp+56];"
        f" mov ecx,dword ptr [ebp+48];"
        f" imul ecx,dword ptr [ebp+52];"
        f" xor eax,eax;"
        f" rep stosb;"
        f"\n mov esi,dword ptr [ebp+8];"
        f" mov eax,dword ptr [ebp+48];"
        f" shr eax,1;"
        f"\n mov dword ptr [esi+16],eax;"
        f" imul eax,dword ptr [esi];"
        f" mov dword ptr [esi+8],eax;"
        f"\n mov eax,dword ptr [ebp+52];"
        f" shr eax,1;"
        f" mov dword ptr [esi+20],eax;"
        f"\n imul eax,dword ptr [esi+4];"
        f" mov dword ptr [esi+12],eax;"
        f"\n mov dword ptr [esi+28],{CANVAS};"
        f" mov dword ptr [0x44b1ac],0x10000;"
        f"\n mov eax,dword ptr [esp+28];"
        f" mov edx,esi;"
        f" call 0x9a36e8;"
        f"\n mov ebp,dword ptr [{STATE}];"
        f"\n mov esi,{LOW};"
        f" mov edi,dword ptr [ebp+8];"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,{LOW};"
        f" mov edi,0x41ebc4;"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [0x1e3c160];"
        f" mov dword ptr [0x44b1ac],eax;"
        f" mov dword ptr [0x3622ce],eax;"
        f"\n mov eax,dword ptr [ebp+32];"
        f" mov dword ptr [0x3622d2],eax;"
        f" mov edx,eax;"
        f" shr edx,1;"
        f" mov dword ptr [0x3622da],edx;"
        f"\n shl eax,15;"
        f" mov dword ptr [0x3622e2],eax;"
        f" mov dword ptr [0x3622ea],eax;"
        f"\n mov eax,dword ptr [ebp+36];"
        f" mov dword ptr [0x3622d6],eax;"
        f" mov edx,eax;"
        f" shr edx,1;"
        f" mov dword ptr [0x3622de],edx;"
        f"\n shl eax,15;"
        f" mov dword ptr [0x3622e6],eax;"
        f" mov dword ptr [0x3622ee],eax;"
        f"\n mov eax,dword ptr [0x9a3d24];"
        f" call 0x2eab30;"
        f"\n mov esi,{SAVE};"
        f" mov edi,{LOW};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov edi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov ebp,dword ptr [{STATE}];"
        f" mov edi,dword ptr [ebp+20];"
        f" add edi,dword ptr [ebp+16];"
        f"\n mov esi,dword ptr [ebp+56];"
        f" mov ebx,dword ptr [ebp+60];"
        f" xor edx,edx;"
        f"\n row: push edx;"
        f" xor ecx,ecx;"
        f" xor edx,edx;"
        f"\n pixel: mov al,byte ptr [esi+edx];"
        f" mov byte ptr [edi+ecx],al;"
        f" mov byte ptr [ebx+ecx],al;"
        f"\n mov eax,ecx;"
        f" add eax,dword ptr [ebp+24];"
        f" and eax,1;"
        f" neg eax;"
        f" add eax,3;"
        f" add edx,eax;"
        f"\n inc ecx;"
        f" cmp ecx,dword ptr [ebp+32];"
        f" jb pixel;"
        f"\n add edi,320;"
        f" add ebx,dword ptr [ebp+32];"
        f" mov eax,[esp];"
        f"add eax,[ebp+28];"
        f"and eax,1;"
        f"neg eax;"
        f"add eax,2;"
        f"imul eax,[ebp+48];"
        f"add esi,eax;"
        f"\n pop edx;"
        f" inc edx;"
        f" cmp edx,dword ptr [ebp+36];"
        f" jb row;"
        f"\n mov edi,dword ptr [ebp+20];"
        f" add edi,{MASK};"
        f" mov edx,dword ptr [ebp+36];"
        f" mov al,255;"
        f"\n maskrow: mov ecx,dword ptr [ebp+32];"
        f" rep stosb;"
        f" add edi,320;"
        f" sub edi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz maskrow;"
        f"\n cmp dword ptr [ebp+88],0;"
        f" je mirrored;"
        f"\n mov esi,dword ptr [ebp+56];"
        f" mov edx,dword ptr [ebp+52];"
        f"\n mirrorrow: mov edi,esi;"
        f" add edi,dword ptr [ebp+48];"
        f" dec edi;"
        f" mov ecx,dword ptr [ebp+48];"
        f" shr ecx,1;"
        f" push esi;"
        f"\n mirrorpixel: mov al,byte ptr [esi];"
        f" mov ah,byte ptr [edi];"
        f" mov byte ptr [esi],ah;"
        f" mov byte ptr [edi],al;"
        f" inc esi;"
        f" dec edi;"
        f" loop mirrorpixel;"
        f"\n pop esi;"
        f" add esi,dword ptr [ebp+48];"
        f" dec edx;"
        f" jnz mirrorrow;"
        f"\n mov esi,dword ptr [ebp+60];"
        f" mov edx,dword ptr [ebp+36];"
        f"\n refrow: mov edi,esi;"
        f" add edi,dword ptr [ebp+32];"
        f" dec edi;"
        f" mov ecx,dword ptr [ebp+32];"
        f" shr ecx,1;"
        f" push esi;"
        f"\n refpixel: mov al,byte ptr [esi];"
        f" mov ah,byte ptr [edi];"
        f" mov byte ptr [esi],ah;"
        f" mov byte ptr [edi],al;"
        f" inc esi;"
        f" dec edi;"
        f" loop refpixel;"
        f"\n pop esi;"
        f" mov ecx,[ebp+32];"
        f"and ecx,3;"
        f"cmp ecx,2;"
        f"jb refnext;"
        f"\n mov ecx,[ebp+32];"
        f"shr ecx,1;"
        f"mov edi,ecx;"
        f"test byte ptr [ebp+32],1;"
        f"jz middle_ready;"
        f"inc edi;"
        f"\n middle_ready:mov al,[esi+ecx-1];"
        f"xchg al,[esi+edi];"
        f"mov [esi+ecx-1],al;"
        f"\n refnext: add esi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz refrow;"
        f"\n mirrored:\n mov dword ptr [ebp],1;"
        f" mov dword ptr [ebp+4],1;"
        f" inc dword ptr [ebp+72];"
        f"\n popad;"
        f" popfd;"
        f" ret;"
        f"\n fallback: inc dword ptr [ebp+76];"
        f"\n other: popad;"
        f" popfd;"
        f" jmp {TARGET};"
        f"\n "
    )


LOW_ENTRY = 0x9d6000


def low_body(*, odd_width=True):
    LOW = 0x9a3d08
    CANVAS = 0x9c34e8
    STATE = 0x9dc000
    SAVE = 0x9dc100
    SLOTS = 0x9dc400
    MASK = 0x870000
    width_gate = '' if odd_width else 'test ebx,1; jnz fallback; '
    if odd_width:
        middle = (
            "mov ecx,dword ptr [ebp+32];"
            " and ecx,3;"
            " cmp ecx,2;"
            " jb refnext;"
            "\n mov ecx,dword ptr [ebp+32];"
            " shr ecx,1;"
            " mov edi,ecx;"
            "\n test byte ptr [ebp+32],1;"
            " jz middle_ready;"
            " inc edi;"
            "\n middle_ready: mov al,byte ptr [esi+ecx-1];"
            " xchg al,byte ptr [esi+edi];"
            " mov byte ptr [esi+ecx-1],al;"
        )
    else:
        middle = (
            "mov ecx,dword ptr [ebp+32];"
            " and ecx,3;"
            " cmp ecx,2;"
            " jne refnext;"
            "\n mov ecx,dword ptr [ebp+32];"
            " shr ecx,1;"
            " mov al,byte ptr [esi+ecx-1];"
            " xchg al,byte ptr [esi+ecx];"
            " mov byte ptr [esi+ecx-1],al;"
        )
    source = (
        f"\n pushfd;"
        f" pushad;"
        f" cld;"
        f"\n mov eax,edx;"
        f" sub eax,0x390010;"
        f" xor edx,edx;"
        f" mov ecx,186;"
        f" div ecx;"
        f"\n test edx,edx;"
        f" jnz other;"
        f" cmp eax,3;"
        f" jae other;"
        f"\n mov edx,eax;"
        f" shl edx,7;"
        f" add edx,{SLOTS};"
        f" mov dword ptr [{STATE}],edx;"
        f"\n mov dword ptr [edx],0;"
        f" mov ebp,edx;"
        f"\n mov ecx,eax;"
        f" shl ecx,5;"
        f" movzx ecx,byte ptr [ecx+0x38fc12];"
        f" mov dword ptr [ebp+80],ecx;"
        f"\n mov ecx,dword ptr [eax*4+0x389df8];"
        f" mov dword ptr [ebp+12],ecx;"
        f"\n movzx ebx,byte ptr [ecx+0x20];"
        f" and ebx,0x40;"
        f" mov dword ptr [ebp+88],ebx;"
        f"\n mov ecx,dword ptr [ecx+0x1c];"
        f" mov dword ptr [ebp+68],ecx;"
        f"\n mov ecx,dword ptr [esp+20];"
        f" mov dword ptr [ebp+8],ecx;"
        f"\n mov esi,dword ptr [ecx+28];"
        f" cmp word ptr [esi+12],320;"
        f" jne fallback;"
        f"\n movzx ebx,word ptr [esi+8];"
        f" cmp ebx,4;"
        f" jb fallback;"
        f" {width_gate}cmp ebx,100;"
        f" ja fallback;"
        f"\n mov dword ptr [ebp+32],ebx;"
        f"\n movzx edi,word ptr [esi+10];"
        f" test edi,edi;"
        f" jz fallback;"
        f" cmp edi,64;"
        f" ja fallback;"
        f"\n mov dword ptr [ebp+36],edi;"
        f"\n mov eax,dword ptr [0x446f78];"
        f" mov dword ptr [ebp+16],eax;"
        f"\n mov edx,dword ptr [esi];"
        f" sub edx,eax;"
        f" cmp edx,64000;"
        f" jae fallback;"
        f"\n mov dword ptr [ebp+20],edx;"
        f" mov eax,edx;"
        f" xor edx,edx;"
        f" mov ecx,320;"
        f" div ecx;"
        f"\n mov dword ptr [ebp+24],edx;"
        f" mov dword ptr [ebp+28],eax;"
        f"\n add ebx,edx;"
        f" cmp ebx,320;"
        f" ja fallback;"
        f" add edi,eax;"
        f" cmp edi,200;"
        f" ja fallback;"
        f"\n imul eax,eax,3;"
        f" mov dword ptr [ebp+44],eax;"
        f"\n imul edx,edx,5;"
        f" inc edx;"
        f" shr edx,1;"
        f" mov dword ptr [ebp+40],edx;"
        f"\n imul ebx,ebx,5;"
        f" inc ebx;"
        f" shr ebx,1;"
        f" sub ebx,edx;"
        f" mov dword ptr [ebp+48],ebx;"
        f"\n mov eax,dword ptr [ebp+36];"
        f" imul eax,eax,3;"
        f" mov dword ptr [ebp+52],eax;"
        f"\n cmp byte ptr [0x1d0d449],0x6b;"
        f" je mode_ready;"
        f"\n pushad;"
        f" mov dx,0x3c7;"
        f" xor eax,eax;"
        f" out dx,al;"
        f" add dx,2;"
        f" mov edi,0x9aa4e8;"
        f" mov ecx,768;"
        f"\n readpal: in al,dx;"
        f" stosb;"
        f" loop readpal;"
        f"\n mov eax,0x4f02;"
        f" mov ebx,0x4103;"
        f" int 0x10;"
        f"\n mov dx,0x3c8;"
        f" xor eax,eax;"
        f" out dx,al;"
        f" inc dx;"
        f" mov esi,0x9aa4e8;"
        f" mov ecx,768;"
        f"\n writepal: lodsb;"
        f" out dx,al;"
        f" loop writepal;"
        f" popad;"
        f"\n mode_ready:\n mov esi,{LOW};"
        f" mov edi,{SAVE};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [0x44b1ac];"
        f" mov dword ptr [{SAVE+96}],eax;"
        f"\n mov esi,dword ptr [ebp+8];"
        f" mov edi,{LOW};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,dword ptr [{LOW+28}];"
        f" mov edi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [ebp+56];"
        f" mov dword ptr [{CANVAS}],eax;"
        f"\n mov eax,dword ptr [ebp+48];"
        f" mov word ptr [{CANVAS+8}],ax;"
        f" mov word ptr [{CANVAS+12}],ax;"
        f"\n shl eax,16;"
        f" mov dword ptr [{CANVAS+52}],eax;"
        f"\n mov eax,dword ptr [ebp+52];"
        f" mov word ptr [{CANVAS+10}],ax;"
        f"\n shl eax,16;"
        f" mov dword ptr [{CANVAS+56}],eax;"
        f"\n mov edi,dword ptr [ebp+56];"
        f" mov ecx,dword ptr [ebp+48];"
        f" imul ecx,dword ptr [ebp+52];"
        f" xor eax,eax;"
        f" rep stosb;"
        f"\n mov esi,dword ptr [ebp+8];"
        f" mov eax,dword ptr [ebp+48];"
        f" shr eax,1;"
        f"\n mov dword ptr [esi+16],eax;"
        f" imul eax,dword ptr [esi];"
        f" mov dword ptr [esi+8],eax;"
        f"\n mov eax,dword ptr [ebp+52];"
        f" shr eax,1;"
        f" mov dword ptr [esi+20],eax;"
        f"\n imul eax,dword ptr [esi+4];"
        f" mov dword ptr [esi+12],eax;"
        f"\n mov dword ptr [esi+28],{CANVAS};"
        f" mov dword ptr [0x44b1ac],0x10000;"
        f"\n mov eax,dword ptr [esp+28];"
        f" mov edx,esi;"
        f" call 0x9a36e8;"
        f"\n mov ebp,dword ptr [{STATE}];"
        f"\n mov esi,{LOW};"
        f" mov edi,dword ptr [ebp+8];"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov esi,{LOW};"
        f" mov edi,0x41ebc4;"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov eax,dword ptr [{SAVE+96}];"
        f" mov dword ptr [0x44b1ac],eax;"
        f" mov dword ptr [0x3622ce],eax;"
        f"\n mov eax,dword ptr [ebp+32];"
        f" mov dword ptr [0x3622d2],eax;"
        f" mov edx,eax;"
        f" shr edx,1;"
        f" mov dword ptr [0x3622da],edx;"
        f"\n shl eax,15;"
        f" mov dword ptr [0x3622e2],eax;"
        f" mov dword ptr [0x3622ea],eax;"
        f"\n mov eax,dword ptr [ebp+36];"
        f" mov dword ptr [0x3622d6],eax;"
        f" mov edx,eax;"
        f" shr edx,1;"
        f" mov dword ptr [0x3622de],edx;"
        f"\n shl eax,15;"
        f" mov dword ptr [0x3622e6],eax;"
        f" mov dword ptr [0x3622ee],eax;"
        f"\n mov eax,dword ptr [{LOW+28}];"
        f" call 0x2eab30;"
        f"\n mov esi,{SAVE};"
        f" mov edi,{LOW};"
        f" mov ecx,8;"
        f" rep movsd;"
        f"\n mov edi,{CANVAS};"
        f" mov ecx,16;"
        f" rep movsd;"
        f"\n mov ebp,dword ptr [{STATE}];"
        f" mov edi,dword ptr [ebp+20];"
        f" add edi,dword ptr [ebp+16];"
        f"\n mov esi,dword ptr [ebp+56];"
        f" mov ebx,dword ptr [ebp+60];"
        f" xor edx,edx;"
        f"\n row: push edx;"
        f" xor ecx,ecx;"
        f" xor edx,edx;"
        f"\n pixel: mov al,byte ptr [esi+edx];"
        f" mov byte ptr [edi+ecx],al;"
        f" mov byte ptr [ebx+ecx],al;"
        f"\n mov eax,ecx;"
        f" add eax,dword ptr [ebp+24];"
        f" and eax,1;"
        f" neg eax;"
        f" add eax,3;"
        f" add edx,eax;"
        f"\n inc ecx;"
        f" cmp ecx,dword ptr [ebp+32];"
        f" jb pixel;"
        f"\n add edi,320;"
        f" add ebx,dword ptr [ebp+32];"
        f" mov eax,dword ptr [ebp+48];"
        f" imul eax,eax,3;"
        f" add esi,eax;"
        f"\n pop edx;"
        f" inc edx;"
        f" cmp edx,dword ptr [ebp+36];"
        f" jb row;"
        f"\n mov edi,dword ptr [ebp+20];"
        f" add edi,{MASK};"
        f" mov edx,dword ptr [ebp+36];"
        f" mov al,255;"
        f"\n maskrow: mov ecx,dword ptr [ebp+32];"
        f" rep stosb;"
        f" add edi,320;"
        f" sub edi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz maskrow;"
        f"\n cmp dword ptr [ebp+88],0;"
        f" je mirrored;"
        f"\n mov esi,dword ptr [ebp+56];"
        f" mov edx,dword ptr [ebp+52];"
        f"\n mirrorrow: mov edi,esi;"
        f" add edi,dword ptr [ebp+48];"
        f" dec edi;"
        f" mov ecx,dword ptr [ebp+48];"
        f" shr ecx,1;"
        f" push esi;"
        f"\n mirrorpixel: mov al,byte ptr [esi];"
        f" mov ah,byte ptr [edi];"
        f" mov byte ptr [esi],ah;"
        f" mov byte ptr [edi],al;"
        f" inc esi;"
        f" dec edi;"
        f" loop mirrorpixel;"
        f"\n pop esi;"
        f" add esi,dword ptr [ebp+48];"
        f" dec edx;"
        f" jnz mirrorrow;"
        f"\n mov esi,dword ptr [ebp+60];"
        f" mov edx,dword ptr [ebp+36];"
        f"\n refrow: mov edi,esi;"
        f" add edi,dword ptr [ebp+32];"
        f" dec edi;"
        f" mov ecx,dword ptr [ebp+32];"
        f" shr ecx,1;"
        f" push esi;"
        f"\n refpixel: mov al,byte ptr [esi];"
        f" mov ah,byte ptr [edi];"
        f" mov byte ptr [esi],ah;"
        f" mov byte ptr [edi],al;"
        f" inc esi;"
        f" dec edi;"
        f" loop refpixel;"
        f"\n pop esi;"
        f" {middle}\n refnext: add esi,dword ptr [ebp+32];"
        f" dec edx;"
        f" jnz refrow;"
        f"\n mirrored:\n mov dword ptr [ebp],1;"
        f" mov dword ptr [ebp+4],1;"
        f" inc dword ptr [ebp+72];"
        f"\n popad;"
        f" popfd;"
        f" ret;"
        f"\n fallback: inc dword ptr [ebp+76];"
        f"\n other: popad;"
        f" popfd;"
        f" jmp 0x9b30e8;"
        f"\n "
    )
    source = re.sub(r'\b(other|fallback|row|pixel|maskrow)\b', r'camera_\1', source)
    return code(LOW_ENTRY, source)


def install_low_width(write, read):
    old = low_body(odd_width=False)
    new = low_body()
    size = max(len(old), len(new))
    if bytes(read(LOW_ENTRY, size)) != old.ljust(size, b'\0'):
        raise ValueError('Secondary renderer provider differs')
    new = new.ljust(size, b'\x90')
    write(LOW_ENTRY, new)
    return dict(
        address=LOW_ENTRY,
        bytes=len(new),
        old_bytes=len(old),
        logical_bounds=[4, 100, 1, 64],
        native_bda=True
    )


"""Use the rendered PBA facing for teammate feeds, not its AI goal bearing.

The sole call-site hook is inside the original type-4 camera path. Damage yaw
and pitch are still added by the caller. No camera clocks or actor state change.
"""
HEADING_CODE = 0x1fff800
HEADING_END = 0x1fffa00  # The following reservation holds audio allocation guards.
HEADING_SITE = 0x275404
HEADING_SITES = (HEADING_SITE, )
HEADING_ORIGINAL = asm(HEADING_SITE, 'call 0x2750cc')


def heading_bodies():
    b = asm(
        HEADING_CODE, (
            "pushfd;"
            "push ebx;"
            "push ecx;"
            "push edx;"
            "\n    movzx ecx,ax;"
            "test ecx,ecx;"
            "jz invalid;"
            "cmp ecx,300;"
            "jae invalid;"
            "\n    imul ebx,ecx,37;"
            "add ebx,0x3c3240;"
            "\n    cmp byte ptr [ebx],0;"
            "je invalid;"
            "cmp byte ptr [ebx+1],1;"
            "jne invalid;"
            "\n    movzx edx,word ptr [ebx+3];"
            "cmp edx,64;"
            "jae object_heading;"
            "\n    imul edx,edx,0x582;"
            "add edx,0x3a5608;"
            "\n    cmp word ptr [edx+0x2f9],cx;"
            "jne object_heading;"
            "\n    movzx eax,word ptr [edx+0x305];"
            "jmp done;"
            "\n    object_heading:movzx eax,word ptr [ebx+0x1b];"
            "\n    done:pop edx;"
            "pop ecx;"
            "pop ebx;"
            "popfd;"
            "ret;"
            "\n    invalid:pop edx;"
            "pop ecx;"
            "pop ebx;"
            "popfd;"
            "jmp 0x2750cc;"
        )
    )
    assert len(b) < 0x200
    return [(HEADING_CODE, b), (HEADING_SITE, asm(HEADING_SITE, f'call {HEADING_CODE}'))]


def heading_installed(r):
    return bytes(r[HEADING_SITE:HEADING_SITE + 5]) == asm(HEADING_SITE, f'call {HEADING_CODE}')


def heading_verify(r):
    for a, b in heading_bodies():
        assert bytes(r[a:a + len(b)]) == b, (hex(a), 'camera96')
    return True


def heading_predecessor_view(r):
    heading_verify(r)
    out = bytearray(r)
    for a, b in heading_bodies():
        out[a:a + len(b)] = HEADING_ORIGINAL if a == HEADING_SITE else bytes(len(b))
    return out


def heading_setup(write, r):
    if heading_installed(r):
        heading_verify(r)
        return dict(ranges=[], already_installed=True)
    assert bytes(r[HEADING_SITE:HEADING_SITE + 5]) == HEADING_ORIGINAL
    assert not any(r[HEADING_CODE:HEADING_END]), 'Camera96 reservation must be unused'
    for a, b in heading_bodies():
        write(a, b)
    return dict(ranges=[(a, a + len(b)) for a, b in heading_bodies()])


"""Preserve original camera damage rendering and a 50-ms interference cadence."""
NOISE_CODE = 0x1fc2100
NOISE_END = 0x1fc2900
NOISE_GATE = NOISE_CODE
NOISE_RAND_X = NOISE_CODE + 0x200
NOISE_RAND_Y = NOISE_CODE + 0x300
NOISE_STATIC = NOISE_CODE + 0x400
NOISE_RENDER = NOISE_CODE + 0x500
NOISE_STATE = NOISE_END
NOISE_STATE_SIZE = 0x100
NOISE_TABLE = NOISE_STATE + 0x40
NOISE_STRIDE = 64
NOISE_PERIOD = 50
NOISE_SITES = {
    0x27a471: asm(0x27a471, "call 0x29edb4"),
    0x27a4d9: asm(0x27a4d9, "call 0x29edb4"),
    0x26c50c: bytes.fromhex('5351525657'),
    0x274db1: asm(0x274db1, 'call 0x27a118'),
    0x26c550: asm(0x26c550, 'call 0x2ddd70'),
    0x26c560: asm(0x26c560, 'call 0x2ddd70')
}


def noise_bodies():
    out = []

    def emit(a, s, cap):
        b = asm(a, s)
        assert len(b) <= cap, (hex(a), len(b))
        out.append((a, b))

    emit(
        NOISE_GATE, (
            f"pushfd;"
            f"pushad;"
            f"cmp eax,2;"
            f"ja fallback;"
            f"\n mov ebp,eax;"
            f"shl eax,6;"
            f"lea edi,[eax+{NOISE_TABLE}];"
            f"mov [{NOISE_STATE}],edi;"
            f"\n mov eax,[0x446ae8];"
            f"xor edx,edx;"
            f"mov ecx,{NOISE_PERIOD};"
            f"div ecx;"
            f"inc eax;"
            f"\n cmp eax,[edi];"
            f"jne choose;"
            f"mov edx,[0x44134e];"
            f"cmp edx,[edi+4];"
            f"jne choose;"
            f"\n mov ecx,ebp;"
            f"shl ecx,5;"
            f"movzx edx,byte ptr [ecx+0x38fc12];"
            f"cmp edx,[edi+8];"
            f"jne choose;"
            f"\n mov eax,[edi+12];"
            f"jmp result;"
            f"\n choose:mov [edi],eax;"
            f"mov eax,[0x44134e];"
            f"mov [edi+4],eax;"
            f"\n mov ecx,ebp;"
            f"shl ecx,5;"
            f"movzx eax,byte ptr [ecx+0x38fc12];"
            f"mov [edi+8],eax;"
            f"\n mov dword ptr [edi+16],0;"
            f"mov eax,ebp;"
            f"call 0x27a118;"
            f"mov [edi+12],eax;"
            f"\n result:mov [esp+28],eax;"
            f"popad;"
            f"popfd;"
            f"ret;"
            f"\n fallback:mov dword ptr [{NOISE_STATE}],0;"
            f"popad;"
            f"popfd;"
            f"jmp 0x27a118;"
        ), 0x200
    )
    for target, bit, off in ((NOISE_RAND_X, 1, 24), (NOISE_RAND_Y, 2, 32)):
        emit(
            target, (
                f"pushfd;"
                f"pushad;"
                f"mov edi,[{NOISE_STATE}];"
                f"test edi,edi;"
                f"jz original;"
                f"\n test dword ptr [edi+16],{bit};"
                f"jz sample;"
                f"cmp ebx,[edi+{off+4}];"
                f"jne sample;"
                f"\n mov eax,[edi+{off}];"
                f"jmp result;"
                f"\n sample:mov [edi+{off+4}],ebx;"
                f"call 0x2ddd70;"
                f"mov [edi+{off}],eax;"
                f"or dword ptr [edi+16],{bit};"
                f"\n result:mov [esp+28],eax;"
                f"popad;"
                f"popfd;"
                f"ret;"
                f"\n original:popad;"
                f"popfd;"
                f"jmp 0x2ddd70;"
            ), 0x100
        )
    emit(
        NOISE_STATIC, (
            f"pushfd;"
            f"pushad;"
            f"cmp eax,2;"
            f"ja invalid;"
            f"\n shl eax,6;"
            f"lea edi,[eax+{NOISE_TABLE}];"
            f"mov [{NOISE_STATE}],edi;"
            f"\n mov eax,[0x446ae8];"
            f"xor edx,edx;"
            f"mov ecx,{NOISE_PERIOD};"
            f"div ecx;"
            f"inc eax;"
            f"\n cmp eax,[edi+20];"
            f"je ready;"
            f"mov [edi+20],eax;"
            f"mov dword ptr [edi+16],0;"
            f"jmp ready;"
            f"\n invalid:mov dword ptr [{NOISE_STATE}],0;"
            f"\n ready:popad;"
            f"popfd;"
            f"push ebx;"
            f"push ecx;"
            f"push edx;"
            f"push esi;"
            f"push edi;"
            f"jmp 0x26c511;"
        ), 0x100
    )
    out.append((0x26c50c, asm(0x26c50c, f'jmp {NOISE_STATIC}')))
    for a, dest in ((0x274db1, NOISE_GATE), (0x26c550, NOISE_RAND_X), (0x26c560, NOISE_RAND_Y)):
        out.append((a, asm(a, f'call {dest}')))
    # The distortion deliberately renders and doubles the original small canvas.
    # Enter after the native camera upscaler, retaining the renderer's safety hooks.
    # The widget's normal invalidation leaves this frame for the logical compositor.
    emit(
        NOISE_RENDER, (
            "pushfd;"
            "push eax;"
            "mov eax,edx;"
            "sub eax,0x390010;"
            "\n cmp eax,0;"
            "je camera;"
            "cmp eax,186;"
            "je camera;"
            "cmp eax,372;"
            "je camera;"
            "\n pop eax;"
            "popfd;"
            "jmp 0x29edb4;"
            "\n camera:pop eax;"
            "popfd;"
            "jmp 0x9a36e8;"
        ), 0x100
    )
    for a in (0x27a471, 0x27a4d9):
        out.append((a, asm(a, f'call {NOISE_RENDER}')))
    return out


def noise_installed(r):
    return bytes(r[0x274db1:0x274db6]) == asm(0x274db1, f'call {NOISE_GATE}')


def noise_verify(r):
    for a, b in noise_bodies():
        assert bytes(r[a:a + len(b)]) == b, (hex(a), 'camera118')
    return True


def noise_predecessor_view(r):
    noise_verify(r)
    out = bytearray(r)
    for a, b in NOISE_SITES.items():
        out[a:a + len(b)] = b
    out[NOISE_CODE:NOISE_END] = bytes(NOISE_END - NOISE_CODE)
    out[NOISE_STATE:NOISE_STATE + NOISE_STATE_SIZE] = bytes(NOISE_STATE_SIZE)
    return out


def noise_setup(write, r):
    if noise_installed(r):
        noise_verify(r)
        return
    for a, b in NOISE_SITES.items():
        assert bytes(r[a:a + len(b)]) == b, hex(a)
    assert not any(r[NOISE_CODE:NOISE_STATE + NOISE_STATE_SIZE]), 'camera118 occupied'
    for a, b in noise_bodies():
        write(a, b)


"""Use the actual suit eye for the player's forward secondary camera."""
EYE_CODE = 0x1dc4000
EYE_STATE = 0x1dc5000
EYE_HOOK = 0x2752f7
EYE_EXPECTED = bytes.fromhex('8aa112fc3800')


def eye_setup(write, asm, r):
    assert bytes(r[EYE_HOOK:EYE_HOOK + len(EYE_EXPECTED)]) == EYE_EXPECTED
    code = asm(
        EYE_CODE, (
            f"\n pushfd;"
            f" pushad;"
            f"\n cmp byte ptr [ecx+0x38fc12],8;"
            f" jne done;"
            f"\n cmp di,word ptr [0x441350];"
            f" jne done;"
            f"\n cmp byte ptr [esi+0x3c3241],1;"
            f" jne done;"
            f"\n mov eax,0x41eb68;"
            f" mov edx,edi;"
            f" call 0x27ec90;"
            f"\n mov eax,dword ptr [0x38fb1c];"
            f" add dword ptr [0x41eb70],eax;"
            f"\n inc dword ptr [{EYE_STATE}];"
            f"\n done: popad;"
            f" popfd;"
            f"\n mov ah,byte ptr [ecx+0x38fc12];"
            f" jmp {EYE_HOOK+len(EYE_EXPECTED)};"
            f"\n "
        )
    )
    assert len(code) < 0x1000
    write(EYE_CODE, code)
    write(EYE_STATE, bytes(0x1000))
    write(EYE_HOOK, asm(EYE_HOOK, f'jmp {EYE_CODE}') + b'\x90')
    return [(EYE_CODE, code)]
