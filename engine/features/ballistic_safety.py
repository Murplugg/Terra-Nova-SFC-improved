"""Check squad explosive trajectories before allocating their physical bodies.

The straight aiming preview does not describe a gravity projectile's full arc.
Use the prepared launch vector to forecast contact and check allied blast
exposure. Refusal follows the original failure exit and existing AI feedback.
"""
from patch_support import asm
from features import projectiles, weapon_timing

LOW, HIGH = 0x1ddc000, 0x1ddd400
CODE, END = HIGH, 0x1dde000
TERRAIN, SQRT, DISTANCE = CODE + 0x800, CODE + 0x900, CODE + 0xa00
SITE = 0x2d934e
ORIGINAL = asm(SITE, 'lea eax,[esp+0x320]')


def bodies(entry, regions):
    restore = 'fxrstor [esp]; mov esp,ebp; popad; popfd;'
    wrapper = asm(CODE, f'''
        pushfd; pushad; mov ebp,esp; sub esp,528; and esp,-16;
        fxsave [esp];
        lea edx,[ebp+36];
        lea eax,[edx+0x320]; push eax;
        movzx eax,word ptr [edx+0x35c]; imul eax,eax,37;
        movzx eax,byte ptr [eax+0x3c3242]; push eax;
        movzx eax,word ptr [edx+0x368]; push eax;
        push esi; call {entry}; add esp,16;
        test eax,eax; jz allowed;
        movzx eax,word ptr [ebp+36+0x368];
        imul eax,eax,{weapon_timing.STRIDE};
        mov dword ptr [eax+{weapon_timing.TABLE+weapon_timing.LAUNCH_VETO}],1;
        {restore}
        jmp 0x2d92aa;
    allowed:
        {restore}
        lea eax,[esp+0x320]; jmp 0x2d9355;
    ''')
    terrain = asm(TERRAIN, '''
        push ebx; push esi; push edi; push ebp;
        mov eax,[esp+20]; mov edx,[esp+24]; mov ebx,[esp+28];
        mov ecx,[esp+32]; push ecx; xor ecx,ecx; call 0x2f0829;
        pop ebp; pop edi; pop esi; pop ebx; ret;
    ''')
    square = asm(SQRT, '''
        push ebx; push esi; push edi; push ebp;
        mov eax,[esp+20]; call 0x2f0676;
        pop ebp; pop edi; pop esi; pop ebx; ret;
    ''')
    distance = asm(DISTANCE, '''
        push ebx; push esi; push edi; push ebp; sub esp,12;
        mov eax,[esp+32]; mov esi,[esp+36];
        mov edx,[esi]; mov ebx,[esi+4]; mov ecx,[esi+8];
        push esp; call 0x298980;
        add esp,12; pop ebp; pop edi; pop esi; pop ebx; ret;
    ''')
    assert len(wrapper) < 0x800 and len(distance) < END-DISTANCE
    return [*regions, (CODE, wrapper), (TERRAIN, terrain), (SQRT, square),
            (DISTANCE, distance), (SITE, asm(SITE, f'jmp {CODE}') + b'\x90\x90')]


def install(write, read, *, entry, regions):
    # This gap follows the weapon-timing table and precedes projectile code.
    if weapon_timing.TABLE + weapon_timing.COUNT * weapon_timing.STRIDE != LOW or END != projectiles.CODE or not LOW <= entry < HIGH:
        raise ValueError('Ballistic helper leaves its reserved memory')
    if any(not LOW <= a < a+len(b) <= HIGH for a, b in regions):
        raise ValueError('Ballistic helper segment exceeds its reservation')
    pieces = bodies(entry, regions)
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    if bytes(read(SITE, len(ORIGINAL))) != ORIGINAL or any(read(LOW, END-LOW)):
        raise ValueError('Ballistic provider or reservation differs')
    for a, b in pieces:
        write(a, b)
    return dict(ranges=[(a, a+len(b)) for a, b in pieces])


def verify(read, *, entry, regions):
    from features.input_views import _verify
    return _verify(bodies(entry, regions), read)
