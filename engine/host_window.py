"""Small Win32/GDI presenter for native VGA/VBE buffers, on the game thread."""
import struct
from features import input_views as inputs
import host_audio as audio
from host_services import VBE_STATE, FB
from host_video import PAL

PUMP = 0x1d19000
PROC = 0x1d19800
INIT = 0x1d19a00
IAT = 0x1d1c000
S = 0x1d1d000
WC = S + 0x100
MSG = S + 0x200
RECT = S + 0x240
BMI = S + 0x400
TEXT = 0x1d1e000
FPU = 0x1d1f000
APIS = ['LoadLibraryA', 'GetProcAddress', 'GetModuleHandleA']


def setup(write, asm, call):
    funcs = {
        'user32.dll': [
            'RegisterClassExA', 'CreateWindowExA', 'DefWindowProcA', 'PeekMessageA',
            'TranslateMessage', 'DispatchMessageA', 'GetDC', 'ReleaseDC', 'GetClientRect',
            'PostQuitMessage', 'SetWindowTextA'
        ],
        'gdi32.dll': ['StretchDIBits', 'SetStretchBltMode']
    }
    cursor = TEXT
    api = {}
    code = []

    def string(s):
        nonlocal cursor
        a = cursor
        write(a, s.encode() + b'\0')
        cursor += len(s) + 1
        return a

    for dll, names in funcs.items():
        code.append(
            (
                f"push {string(dll)};"
                f"{call('LoadLibraryA')}test eax,eax;"
                f"jz window_failure;"
                f"mov ebx,eax;"
            )
        )
        for name in names:
            a = IAT + 4 * len(api)
            api[name] = a
            code.append(
                (
                    f"push {string(name)};"
                    f"push ebx;"
                    f"{call('GetProcAddress')}test eax,eax;"
                    f"jz window_failure;"
                    f"mov [{a}],eax;"
                )
            )

    def win(name):
        return f'call dword ptr [{api[name]}];'

    cls = string('TNHRNativeResearch37')
    title = string('Terra Nova - native Windows research 37 (PCM audio)')
    write(WC, struct.pack('<12I', 48, 3, PROC, 0, 0, 0, 0, 0, 0, 0, cls, 0))
    write(BMI, struct.pack('<IiiHHIIiiII', 40, 320, -200, 1, 8, 0, 64000, 0, 0, 256, 256))
    code.append(
        (
            f"call dword ptr [{audio.slot('TN_NewWindow')}];"
            f"test eax,eax;"
            f"jz window_failure;"
            f"push {title};"
            f"push eax;"
            f"{win('SetWindowTextA')}ret;"
        )
    )
    code.append(f"window_failure:{call('GetLastError')}mov [{S+60}],eax;mov eax,0xff00;int 0x21;")
    init = asm(INIT, ''.join(code))
    assert len(init) < 0x600
    write(INIT, init)
    write(
        PROC,
        asm(
            PROC, (
                f"mov eax,[esp+8];"
                f"cmp eax,2;"
                f"je window_destroy;"
                f"cmp eax,0x24;"
                f"je window_minmax;"
                f"\n cmp eax,0x231;"
                f"je window_modal_enter;"
                f"cmp eax,0x211;"
                f"je window_modal_enter;"
                f"\n cmp eax,0x232;"
                f"je window_modal_exit;"
                f"cmp eax,0x212;"
                f"je window_modal_exit;"
                f"\n cmp eax,8;"
                f"je window_input;"
                f"cmp eax,0x100;"
                f"jb window_default;"
                f"cmp eax,0x105;"
                f"jbe window_input;"
                f"\n cmp eax,0x200;"
                f"jb window_default;"
                f"cmp eax,0x209;"
                f"jbe window_input;"
                f"jmp window_default;"
                f"\n window_input:pushfd;"
                f"pushad;"
                f"mov eax,[esp+44];"
                f"mov ebx,[esp+48];"
                f"mov ecx,[esp+52];"
                f"call {inputs.HANDLE};"
                f"popad;"
                f"popfd;"
                f"xor eax,eax;"
                f"ret 16;"
                f"\n window_destroy:mov eax,[esp+4];"
                f"cmp eax,[{S}];"
                f"jne window_ignore;"
                f"\n mov dword ptr [{S+4}],1;"
                f"push 0;"
                f"{win('PostQuitMessage')}xor eax,eax;"
                f"ret 16;"
                f"\n window_modal_enter:pushfd;"
                f"pushad;"
                f"call dword ptr [{audio.slot('TN_Suspend')}];"
                f"popad;"
                f"popfd;"
                f"xor eax,eax;"
                f"ret 16;"
                f"\n window_modal_exit:pushfd;"
                f"pushad;"
                f"call dword ptr [{audio.slot('TN_Resume')}];"
                f"popad;"
                f"popfd;"
                f"xor eax,eax;"
                f"ret 16;"
                f"\n window_minmax:pushfd;"
                f"pushad;"
                f"push dword ptr [esp+52];"
                f"push dword ptr [esp+44];"
                f"call dword ptr [{audio.slot('TN_MinMax')}];"
                f"add esp,8;"
                f"popad;"
                f"popfd;"
                f"\n window_ignore:xor eax,eax;"
                f"ret 16;"
                f"\n window_default:push dword ptr [esp+16];"
                f"push dword ptr [esp+16];"
                f"push dword ptr [esp+16];"
                f"push dword ptr [esp+16];"
                f"{win('DefWindowProcA')}ret 16;"
            )
        )
    )
    code = (
        f"\n pushfd;"
        f"pushad;"
        f"cmp dword ptr [{S+64}],0;"
        f"jne window_reentrant;"
        f"mov dword ptr [{S+64}],1;"
        f"fxsave [{FPU}];"
        f"cld;"
        f"\n window_messages:push 1;"
        f"push 0;"
        f"push 0;"
        f"push 0;"
        f"push {MSG};"
        f"{win('PeekMessageA')}test eax,eax;"
        f"jz window_tick;"
        f"\n cmp dword ptr [{MSG+4}],0x12;"
        f"je window_quit;"
        f"push {MSG};"
        f"{win('TranslateMessage')}push {MSG};"
        f"{win('DispatchMessageA')}jmp window_messages;"
        f"\n window_tick:cmp dword ptr [{S+4}],0;"
        f"jne window_quit;"
        f"call dword ptr [{audio.slot('TN_Pump')}];"
        f"\n cmp dword ptr [{S+0x80}],0;"
        f"jne window_force_present;"
        f"\n cmp dword ptr [{VBE_STATE}],0x103;"
        f"jne window_normal_present;"
        f"cmp byte ptr [0x35f3f4],0;"
        f"je window_done;"
        f"\n window_normal_present:\n push {S+0x68};"
        f"{call('QueryPerformanceCounter')}\n mov eax,[0x1d0f120];"
        f"xor edx,edx;"
        f"mov ecx,60;"
        f"div ecx;"
        f"test eax,eax;"
        f"jz window_done;"
        f"mov ecx,eax;"
        f"\n mov eax,[{S+0x68}];"
        f"mov edx,[{S+0x6c}];"
        f"sub eax,[{S+0x70}];"
        f"sbb edx,[{S+0x74}];"
        f"test edx,edx;"
        f"jnz window_present_reset;"
        f"\n cmp eax,ecx;"
        f"jb window_done;"
        f"xor edx,edx;"
        f"div ecx;"
        f"mul ecx;"
        f"add [{S+0x70}],eax;"
        f"adc dword ptr [{S+0x74}],edx;"
        f"jmp window_present_ready;"
        f"\n window_present_reset:mov eax,[{S+0x68}];"
        f"mov [{S+0x70}],eax;"
        f"mov eax,[{S+0x6c}];"
        f"mov [{S+0x74}],eax;"
        f"\n jmp window_present_ready;"
        f"\n window_force_present:mov dword ptr [{S+0x80}],0;"
        f"\n window_present_ready:\n mov eax,[{VBE_STATE}];"
        f"cmp eax,0x13;"
        f"je window_vga;"
        f"cmp eax,0x101;"
        f"je window_vesa;"
        f"cmp eax,0x103;"
        f"jne window_done;"
        f"\n window_vesa:cmp dword ptr [{VBE_STATE+4}],0;"
        f"je window_done;"
        f"mov eax,[{VBE_STATE+8}];"
        f"mov [{S+16}],eax;"
        f"mov eax,[{VBE_STATE+12}];"
        f"mov [{S+20}],eax;"
        f"mov edx,[{VBE_STATE+16}];"
        f"mov eax,[{VBE_STATE+24}];"
        f"imul eax,edx;"
        f"add eax,[{VBE_STATE+20}];"
        f"add eax,{FB};"
        f"jmp window_format;"
        f"\n window_vga:mov dword ptr [{S+16}],320;"
        f"mov dword ptr [{S+20}],200;"
        f"mov edx,320;"
        f"mov eax,0xa0000;"
        f"\n window_format:mov [{S+12}],eax;"
        f"mov [{BMI+4}],edx;"
        f"mov eax,[{S+20}];"
        f"neg eax;"
        f"mov [{BMI+8}],eax;"
        f"\n mov esi,{PAL};"
        f"mov edi,{BMI+40};"
        f"mov ecx,256;"
        f"\n window_palette:movzx eax,byte ptr [esi+2];"
        f"movzx ebx,byte ptr [esi+1];"
        f"shl ebx,8;"
        f"or eax,ebx;"
        f"movzx ebx,byte ptr [esi];"
        f"shl ebx,16;"
        f"or eax,ebx;"
        f"mov ebx,eax;"
        f"shr ebx,4;"
        f"and ebx,0x030303;"
        f"shl eax,2;"
        f"or eax,ebx;"
        f"stosd;"
        f"add esi,3;"
        f"loop window_palette;"
        f"\n push {RECT};"
        f"push dword ptr [{S}];"
        f"{win('GetClientRect')}test eax,eax;"
        f"jz window_done;"
        f"\n push dword ptr [{S+16}];"
        f"push dword ptr [{S+20}];"
        f"\n cmp dword ptr [{VBE_STATE}],0x13;"
        f"jne window_layout;"
        f"\n mov dword ptr [{S+16}],800;"
        f"mov dword ptr [{S+20}],600;"
        f"\n window_layout:call dword ptr [{audio.slot('TN_Layout')}];"
        f"pop dword ptr [{S+20}];"
        f"pop dword ptr [{S+16}];"
        f"\n push dword ptr [{S}];"
        f"{win('GetDC')}test eax,eax;"
        f"jz window_done;"
        f"mov ebx,eax;"
        f"\n push ebx;"
        f"call dword ptr [{audio.slot('TN_ClearBars')}];"
        f"add esp,4;"
        f"push 3;"
        f"push ebx;"
        f"{win('SetStretchBltMode')}\n push 0x00cc0020;"
        f"push 0;"
        f"push {BMI};"
        f"push dword ptr [{S+12}];"
        f"push dword ptr [{S+20}];"
        f"push dword ptr [{S+16}];"
        f"push 0;"
        f"push 0;"
        f"push dword ptr [{S+0x9c}];"
        f"push dword ptr [{S+0x98}];"
        f"push dword ptr [{S+0x94}];"
        f"push dword ptr [{S+0x90}];"
        f"push ebx;"
        f"{win('StretchDIBits')}\n mov [{S+28}],eax;"
        f"test eax,eax;"
        f"jz window_release;"
        f"inc dword ptr [{S+24}];"
        f"\n window_release:push ebx;"
        f"push dword ptr [{S}];"
        f"{win('ReleaseDC')}\n window_done:fxrstor [{FPU}];"
        f"mov dword ptr [{S+64}],0;"
        f"\n window_reentrant:popad;"
        f"popfd;"
        f"ret;"
        f"\n window_quit:mov eax,0xff00;"
        f"int 0x21;"
        f"\n "
    )
    body = asm(PUMP, code)
    assert len(body) < 0x800
    write(PUMP, body)
    return win
