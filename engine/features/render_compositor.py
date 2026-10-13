"""Combine enlarged world, map and camera pixels with the logical HUD.

The caller supplies buffer layouts and the HUD/map entry points. Copy loops
preserve exact pixel coverage, while fixed arena slots keep snapshots compatible.
"""
from dataclasses import replace
from . import render_views as views, render_install as install
from .render_arena import W, H
from patch_support import asm

CODE = 0x1fd0400
END = 0x1fd3000
SLOT = CODE
CAMERA = CODE + 0x800
MAP = CODE + 0xc00
COMPOSE = CODE + 0x1000


def slot_source(layout, hud):
    # Carry/remainder stepping and row offsets avoid per-pixel division.
    return (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"sub esp,80;"
        f"mov eax,[ebp+48];"
        f"xor edx,edx;"
        f"div dword ptr [ebp+32];"
        f"mov [esp+48],eax;"
        f"mov [esp+52],edx;"
        f"\n         mov dword ptr [esp+4],0;"
        f"\n         row:mov eax,[esp+4];"
        f"imul eax,[ebp+52];"
        f"xor edx,edx;"
        f"div dword ptr [ebp+36];"
        f"mov [esp+16],eax;"
        f"\n         mov eax,[esp+4];"
        f"inc eax;"
        f"imul eax,[ebp+52];"
        f"xor edx,edx;"
        f"div dword ptr [ebp+36];"
        f"sub eax,[esp+16];"
        f"mov [esp+20],eax;"
        f"\n         mov eax,[esp+4];"
        f"add eax,[ebp+28];"
        f"mov edx,[{layout.yedges}+eax*4];"
        f"mov [esp+24],edx;"
        f"\n         mov ecx,[{layout.yedges}+eax*4+4];"
        f"sub ecx,edx;"
        f"mov [esp+28],ecx;"
        f"\n         mov dword ptr [esp],0;"
        f"mov dword ptr [esp+8],0;"
        f"mov dword ptr [esp+56],0;"
        f"\n   xor ebx,ebx;"
        f"prepare_rows:mov eax,ebx;"
        f"imul eax,[esp+20];"
        f"xor edx,edx;"
        f"div dword ptr [esp+28];"
        f"\n   add eax,[esp+16];"
        f"imul eax,[ebp+48];"
        f"add eax,[ebp+56];"
        f"mov [esp+ebx*4+60],eax;"
        f"\n   inc ebx;"
        f"cmp ebx,[esp+28];"
        f"jb prepare_rows;"
        f"\n         pixel:mov eax,[esp+48];"
        f"mov edx,[esp+56];"
        f"add edx,[esp+52];"
        f"cmp edx,[ebp+32];"
        f"jb no_carry;"
        f"\n   sub edx,[ebp+32];"
        f"inc eax;"
        f"no_carry:mov [esp+12],eax;"
        f"mov [esp+56],edx;"
        f"mov eax,[esp+4];"
        f"imul eax,[ebp+32];"
        f"add eax,[esp];"
        f"mov edx,[ebp+64];"
        f"cmp byte ptr [edx+eax],0;"
        f"je next;"
        f"\n         mov edx,[ebp+60];"
        f"mov cl,[edx+eax];"
        f"mov eax,[esp+4];"
        f"imul eax,eax,320;"
        f"add eax,[ebp+20];"
        f"add eax,[esp];"
        f"\n         cmp byte ptr [eax+{hud.CACHE}],cl;"
        f"jne next;"
        f"mov [esp+44],eax;"
        f"\n         mov dword ptr [esp+32],0;"
        f"\n         scan:mov eax,[esp+32];"
        f"mov esi,[esp+eax*4+60];"
        f"add esi,[esp+8];"
        f"mov edi,[esp+24];"
        f"add edi,[esp+32];"
        f"imul edi,edi,{W};"
        f"mov eax,[esp];"
        f"add eax,[ebp+24];"
        f"lea edi,[edi+eax*4+{layout.frame}];"
        f"\n         cmp dword ptr [esp+12],4;"
        f"je four;"
        f"\n   cmp dword ptr [esp+12],3;"
        f"je three;"
        f"cmp dword ptr [esp+12],2;"
        f"je two;"
        f"\n   xor ecx,ecx;"
        f"sample:mov eax,ecx;"
        f"imul eax,[esp+12];"
        f"shr eax,2;"
        f"mov al,[esi+eax];"
        f"stosb;"
        f"\n   inc ecx;"
        f"cmp ecx,4;"
        f"jb sample;"
        f"jmp sampled;"
        f"\n   four:mov eax,[esi];"
        f"stosd;"
        f"jmp sampled;"
        f"\n   three:movzx eax,byte ptr [esi];"
        f"imul eax,eax,0x101;"
        f"movzx edx,word ptr [esi+1];"
        f"shl edx,16;"
        f"or eax,edx;"
        f"stosd;"
        f"jmp sampled;"
        f"\n   two:movzx eax,byte ptr [esi];"
        f"imul eax,eax,0x101;"
        f"movzx edx,byte ptr [esi+1];"
        f"imul edx,edx,0x1010000;"
        f"or eax,edx;"
        f"stosd;"
        f"\n   sampled:inc dword ptr [esp+32];"
        f"mov eax,[esp+32];"
        f"cmp eax,[esp+28];"
        f"jb scan;"
        f"\n         mov eax,[esp+44];"
        f"mov byte ptr [eax+{hud.CACHE}],0;"
        f"\n         next:mov eax,[esp+12];"
        f"add [esp+8],eax;"
        f"inc dword ptr [esp];"
        f"mov eax,[esp];"
        f"cmp eax,[ebp+32];"
        f"jb pixel;"
        f"\n         inc dword ptr [esp+4];"
        f"mov eax,[esp+4];"
        f"cmp eax,[ebp+36];"
        f"jb row;"
        f"\n         add esp,80;"
        f"popad;"
        f"popfd;"
        f"ret;"
    )


def compose_source(layout, hud, maps):
    # Skip four transparent logical pixels together only inside the world view.
    return (
        f"pushfd;"
        f"pushad;"
        f"cld;"
        f"cmp dword ptr [0x9aa0e8],0;"
        f"jne done;"
        f"\n         mov dword ptr [0x9aa0e8],1;"
        f"inc byte ptr [0x447115];"
        f"\n         mov esi,[0x446f78];"
        f"mov edi,{hud.CACHE};"
        f"mov ecx,32000;"
        f"rep movsd;"
        f"call {hud.PREPARE};"
        f"call {hud.COVER};"
        f"\n         cmp dword ptr [{hud.READY}],0;"
        f"je hud;"
        f"\n         mov esi,{layout.pixels};"
        f"mov edi,[{hud.DATA+4}];"
        f"imul edi,edi,{W};"
        f"add edi,[{hud.DATA}];"
        f"add edi,{layout.frame};"
        f"\n         mov ebp,[{hud.DATA+20}];"
        f"mov ebx,[{hud.DATA+16}];"
        f"mov edx,{W};"
        f"sub edx,ebx;"
        f"\n         worldrow:mov ecx,ebx;"
        f"shr ecx,2;"
        f"rep movsd;"
        f"mov ecx,ebx;"
        f"and ecx,3;"
        f"rep movsb;"
        f"add edi,edx;"
        f"dec ebp;"
        f"jnz worldrow;"
        f"\n         hud:mov esi,{hud.CACHE};"
        f"mov edi,{layout.frame};"
        f"xor ebp,ebp;"
        f"sub esp,8;"
        f"mov dword ptr [esp],0;"
        f"\n         row:mov eax,[esp];"
        f"mov edx,[{layout.yedges}+eax*4+4];"
        f"sub edx,[{layout.yedges}+eax*4];"
        f"mov [esp+4],edx;"
        f"xor ebx,ebx;"
        f"\n         pixel:test ebx,15;"
        f"jnz slow91;"
        f"cmp dword ptr [esi],0;"
        f"jne slow91;"
        f"\n  cmp dword ptr [esi+{hud.MASK-hud.CACHE}],-1;"
        f"jne slow91;"
        f"\n  cmp dword ptr [{hud.READY}],0;"
        f"je slow91;"
        f"\n  cmp ebp,[{hud.DATA+4}];"
        f"jb slow91;"
        f"cmp ebp,[{hud.DATA+12}];"
        f"jae slow91;"
        f"\n  cmp ebx,[{hud.DATA}];"
        f"jb slow91;"
        f"lea eax,[ebx+16];"
        f"cmp eax,[{hud.DATA+8}];"
        f"ja slow91;"
        f"\n  add esi,4;"
        f"add edi,16;"
        f"add ebx,16;"
        f"cmp ebx,1280;"
        f"jb pixel;"
        f"jmp rowend91;"
        f"\n  slow91:movzx eax,byte ptr [esi];"
        f"test al,al;"
        f"jnz opaque;"
        f"cmp dword ptr [{hud.READY}],0;"
        f"je opaque;"
        f"\n         cmp ebp,[{hud.DATA+4}];"
        f"jb opaque;"
        f"cmp ebp,[{hud.DATA+12}];"
        f"jae opaque;"
        f"\n         cmp ebx,[{hud.DATA}];"
        f"jb opaque;"
        f"cmp ebx,[{hud.DATA+8}];"
        f"jae opaque;"
        f"\n         cmp byte ptr [esi+{hud.MASK-hud.CACHE}],0;"
        f"jne next;"
        f"\n         opaque:imul eax,eax,0x01010101;"
        f"mov [edi],eax;"
        f"mov [edi+{W}],eax;"
        f"\n         cmp dword ptr [esp+4],3;"
        f"jne next;"
        f"mov [edi+{2*W}],eax;"
        f"\n         next:inc esi;"
        f"add edi,4;"
        f"add ebx,4;"
        f"cmp ebx,{W};"
        f"jb pixel;"
        f"\n         rowend91:mov eax,[esp+4];"
        f"add ebp,eax;"
        f"dec eax;"
        f"imul eax,eax,{W};"
        f"add edi,eax;"
        f"\n         inc dword ptr [esp];"
        f"cmp dword ptr [esp],400;"
        f"jb row;"
        f"\n         add esp,8;"
        f"call {hud.MERGE};"
        f"call {maps.MERGE};"
        f"mov esi,{layout.frame};"
        f"mov edi,{layout.screen};"
        f"mov ecx,{W*H//4};"
        f"rep movsd;"
        f"\n         mov dword ptr [{layout.state+24}],1;"
        f"inc dword ptr [{layout.state+28}];"
        f"\n         dec byte ptr [0x447115];"
        f"mov dword ptr [0x9aa0e8],0;"
        f"\n         done:popad;"
        f"popfd;"
        f"ret;"
    )


def bodies(layout, hud, maps):
    out = []
    for address, limit, source in (
        (SLOT, CAMERA, slot_source(layout, hud)), (CAMERA, MAP, views.camera_merge(hud, SLOT)),
        (MAP, COMPOSE, views.map_merge(maps,
                                       SLOT)), (COMPOSE, END, compose_source(layout, hud, maps))
    ):
        code = views.assemble(address, source)
        if address + len(code) > limit:
            raise ValueError('Compositor code exceeds reservation')
        out.append((address, code))
    # Keep write order stable so callers can compare complete installation plans.
    return [
        out[0], out[1], (hud.MERGE, asm(hud.MERGE, f'jmp {CAMERA}')), out[2],
        (maps.MERGE, asm(maps.MERGE, f'jmp {MAP}')), out[3],
        (hud.COMPOSE, asm(hud.COMPOSE, f'jmp {COMPOSE}'))
    ]


def prepare(renderer, integration, hud, maps, read):
    """Fold final compositor hooks into the cold renderer installation once.

    The renderer's original embedded arena payload is retained to keep exact
    snapshots compatible. Only the three declared hook replacements may overlap.
    """
    hooks = {hud.MERGE: 'camera_merge', maps.MERGE: 'map_merge', hud.COMPOSE: 'compose'}
    patches = list(renderer.patches)
    if any(install.checked(read, p.address, len(p.before)) != p.before for p in patches):
        raise ValueError('Renderer plan no longer matches cold providers')
    for a, b in bodies(integration, hud, maps):
        if a in hooks:
            indices = [n for n, p in enumerate(patches) if p.address == a]
            if len(indices) != 1:
                raise ValueError('Missing compositor hook provider')
            n = indices[0]
            p = patches[n]
            if p.after != asm(a, f'jmp {integration.entries[hooks[a]]}'):
                raise ValueError('Unexpected compositor hook provider')
            patches[n] = replace(p, after=b)
        else:
            before = install.checked(read, a, len(b))
            if any(before):
                raise ValueError('Compositor reservation occupied')
            patches.append(install.Patch(a, before, b))
    return install.Plan(tuple(patches))
