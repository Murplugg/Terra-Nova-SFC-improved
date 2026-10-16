"""Resolve installation paths before the Windows host opens files or audio.

The executable remains identical in every installation. At startup it finds its
own folder and fills the existing host path slots in memory. Snapshot restoration
fills those same slots from the selected installation before resuming the game.
The original DOS path resolver and campaign resource ownership remain unchanged.
"""
import struct

from patch_support import asm

ENTRY = 0x1d00000
ORIGINAL = bytes.fromhex('fcdbe36a03')  # cld; fninit; push 3 (SetErrorMode argument)
CODE, TEXT, ROOT, END = 0x1d3c000, 0x1d3d000, 0x1d3f000, 0x1d40000
ROOT_CAPACITY = 260


def bodies(imports, relocations):
    """Use the packaging path inventory as the single list of host destinations."""
    strings = bytearray()

    def string(value):
        address = TEXT + len(strings)
        strings.extend(value.encode('ascii') + b'\0')
        return address

    kernel = string('kernel32.dll')
    module_name = string('GetModuleFileNameA')
    directory_name = string('SetCurrentDirectoryA')
    user = string('user32.dll')
    message_name = string('MessageBoxA')
    title = string('TNova Native')
    error = string('Cannot use this installation path. Use an ASCII folder name and move the complete game folder nearer the drive root.')
    rows, spans = [], []
    for row in relocations:
        destination, capacity = row['offset'] + 0x10e00, row['capacity']
        value = row['value']
        if value.count('{ROOT}') != 1:
            raise ValueError('Runtime path must contain one installation root')
        if not 0x11000 <= destination < destination + capacity <= 0x2000000:
            raise ValueError('Runtime path destination outside image')
        if destination < END and destination + capacity > CODE:
            raise ValueError('Runtime path overlaps initializer')
        if any(destination < high and low < destination + capacity for low, high in spans):
            raise ValueError('Runtime path destinations overlap')
        spans.append((destination, destination + capacity))
        prefix, suffix = value.split('{ROOT}')
        rows.append((destination, capacity, string(prefix), len(prefix), string(suffix), len(suffix)))
    table = TEXT + len(strings)
    for row in rows:
        strings.extend(struct.pack('<6I', *row))
    if TEXT + len(strings) > ROOT:
        raise ValueError('Runtime path inventory exceeds reserved text storage')
    call = lambda name: f"call dword ptr [{imports[name]}];"
    source = f'''
        pushfd; pushad; cld;
        push {kernel}; {call('GetModuleHandleA')}
        test eax,eax; jz failed; mov ebp,eax;
        push {module_name}; push ebp; {call('GetProcAddress')}
        test eax,eax; jz failed;
        push {ROOT_CAPACITY}; push {ROOT}; push 0; call eax;
        test eax,eax; jz failed; cmp eax,{ROOT_CAPACITY}; jae failed;
        mov ecx,eax; mov edi,{ROOT}; xor ebx,ebx;
    scan:
        mov al,[edi]; cmp al,0x20; jb failed; cmp al,0x7e; ja failed;
        cmp al,0x5c; jne next; mov ebx,edi;
    next:
        inc edi; loop scan;
        test ebx,ebx; jz failed;
        cmp ebx,{ROOT+2}; jne root_end; inc ebx;
    root_end:
        mov byte ptr [ebx],0;
        sub ebx,{ROOT}; mov [{ROOT+ROOT_CAPACITY}],ebx;
        push {directory_name}; push ebp; {call('GetProcAddress')}
        test eax,eax; jz failed;
        push {ROOT}; call eax; test eax,eax; jz failed;
        mov ebp,{table}; mov edx,{len(rows)};
    path:
        mov eax,[ebp+12]; add eax,[ebp+20]; add eax,ebx;
        cmp eax,[ebp+4]; jae failed;
        mov edi,[ebp]; mov ecx,[ebp+4]; xor eax,eax; rep stosb;
        mov edi,[ebp]; mov esi,[ebp+8]; mov ecx,[ebp+12]; rep movsb;
        mov esi,{ROOT}; mov ecx,ebx; rep movsb;
        mov esi,[ebp+16]; mov ecx,[ebp+20]; rep movsb;
        add ebp,24; dec edx; jnz path;
        popad; popfd; cld; fninit; push 3; jmp {ENTRY+len(ORIGINAL)};
    failed:
        push {user}; {call('LoadLibraryA')} test eax,eax; jz exit;
        push {message_name}; push eax; {call('GetProcAddress')}
        test eax,eax; jz exit;
        push 0x10; push {title}; push {error}; push 0; call eax;
    exit:
        push 1; {call('ExitProcess')}
        int3;
    '''
    code = asm(CODE, source)
    if CODE + len(code) > TEXT:
        raise ValueError('Runtime path initializer exceeds reserved code storage')
    return [(CODE, code), (TEXT, bytes(strings)), (ENTRY, asm(ENTRY, f'jmp {CODE}'))]


def install(write, read, *, imports, relocations):
    # Smoke ends at CODE and the host log begins at END. No game table owns
    # this gap; rejecting occupied bytes catches incompatible future providers.
    if bytes(read(ENTRY, len(ORIGINAL))) != ORIGINAL or any(read(CODE, END-CODE)):
        raise ValueError('Runtime path initialization space is occupied')
    for address, data in bodies(imports, relocations):
        write(address, data)
