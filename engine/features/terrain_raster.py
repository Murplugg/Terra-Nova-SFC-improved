"""Terrain column, reflective and affine rasterizers with bounded span storage."""
from patch_support import asm
from original_inputs import edited_assembly as retained_source
import struct
import hashlib
from features import frame_clock

# The water/haze column routine below adapts SHIPPED_BODY from Terra Nova
# Plus tools/view_fix.py, commit 51c56c0604ef514532bff3ad2987fcb8909775ca.
# Copyright (c) 2026 skw-1337
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


def haze_column_candidate(address):
    """Equivalent replacement for the original water/haze pass at 0x2B2785.

    Ordinary pixels need no reflection-source or remap-row calculation. Defer
    those calculations until a pixel needs them, and keep the table address in
    stack storage instead of writing an instruction operand on every call.
    Inputs, palette rules and final registers follow the original routine.
    Like its original caller, this routine requires a positive column length.
    """
    return asm(address, '''
        push ebp
        mov eax, [ebx+4]
        mov ebp, [ebx+8]
        mov ebx, [ebx]
        add esi, edx
        sub esp, 12
        mov [esp], eax
        lea eax, [esi+edi]
        sub eax, edx
        mov [esp+4], eax
        lea eax, [ebx+ecx*4]
        mov [esp+8], eax
    haze_pixel:
        movzx eax, byte ptr [edi]
        cmp byte ptr [eax+ebp], 0
        jne haze_remap
    haze_next:
        add edi, edx
        dec ecx
        jnz haze_pixel
        mov ebx, [esp+8]
        mov esi, [esp+4]
        sub esi, edi
        add esi, edx
        lea esp, [esp+12]
        pop ebp
        lea ebx, [ebx-4]
        add ebx, 4
        mov ecx, 1
        dec ecx
        ret
    haze_remap:
        shl eax, 2
        add eax, [esp]
        mov eax, [eax]
        add eax, [esp+4]
        sub eax, edi
        movzx eax, byte ptr [eax]
        mov ebx, ecx
        shl ebx, 2
        neg ebx
        add ebx, [esp+8]
        add eax, [ebx]
        mov al, [eax]
        mov [edi], al
        xor eax, eax
        jmp haze_next
    ''')

# Pixel-identical terrain columns without writing the next loop instruction.
COLUMN_CODE = 0x1e4c000

COLUMN_END = COLUMN_CODE + 0x1000
HAZE_CODE = COLUMN_CODE + 0x800
HAZE_SITE = 0x2b2785
HAZE_ORIGINAL = asm(HAZE_SITE, 'push ebp; mov ebp,0x2b279c')

COLUMN_SITE = 0x2b2a85

COLUMN_ORIGINAL = bytes.fromhex('892d9a2a2b00')


def column_candidate(address=COLUMN_CODE):
    return asm(
        address, (
            "push esi;"
            "push ecx;"
            "\n mov esi,[0x2b2a92];"
            "mov ecx,[0x2b2aa6];"
            "xor eax,eax;"
            "\n column88:movzx eax,byte ptr [edx+esi];"
            "inc dl;"
            "\n movzx eax,byte ptr [eax+ebp];"
            "add edi,[0x2b2aa0];"
            "\n mov al,[eax+ecx];"
            "mov [edi],al;"
            "dec ebx;"
            "jnz column88;"
            "\n pop ecx;"
            "pop esi;"
            "pop ebp;"
            "jmp 0x2b2aaf;"
        )
    )


# IR uses separate surface routines from normal vision. Their original setup
# stores texture steps and palette addresses inside instruction operands. These
# replacements execute from a separate reservation and read those operands as
# data, avoiding repeated invalidation of the instructions being executed.
# Keep the original setup, fixed-point carries, texture/palette lookups and
# parameter writebacks so clipping and subsequent spans see identical state.
IR_SPAN_SITE = 0x34e223
IR_AFFINE_SITE = 0x3311f0
IR_SPAN_CODE = COLUMN_CODE + 0x100
IR_AFFINE_CODE = COLUMN_CODE + 0x400
IR_ORIGINAL = {
    IR_SPAN_SITE: bytes.fromhex('608bf0b98a'),
    IR_AFFINE_SITE: bytes.fromhex('608bf88b1d'),
}

# The first routine draws a stepped terrain span. The second handles affine
# trapezoid rows, including the original empty-row and oversized-row returns.
# Absolute addresses below name the retained original parameter slots.
IR_SPAN_RECIPE = (
    0x34e223, 0x34e40a,
    'cbd8b18738d6ae7dfb0d759e873b3edbdac83178cc8f6428973ff408fea9d9f0',
    {
        0x34e22b: (0x34e235,
            'mov ebp, dword ptr [0x34e22c];'
            'mov ebx, dword ptr [0x34e231];'
        ),
        0x34e246: (0x34e249,
            'push ecx;'
            'mov cl,[0x34e248];'
            'sar eax,cl;'
            'pop ecx;'
        ),
        0x34e277: (0x34e27a,
            'push ecx;'
            'mov cl,[0x34e279];'
            'sar eax,cl;'
            'pop ecx;'
        ),
        0x34e2bc: (0x34e2c4,
            'push ecx;'
            'mov cl,[0x34e2be];'
            'sar eax,cl;'
            'pop ecx;'
            'and eax, dword ptr [0x34e2c0];'
        ),
        0x34e2d5: (0x34e2da,
            'mov ecx, dword ptr [0x34e2d6];'
        ),
        0x34e2e4: (0x34e2ea,
            'and ebx, dword ptr [0x34e2e6];'
        ),
        0x34e2f1: (0x34e2f9,
            'push ecx;'
            'mov cl,[0x34e2f3];'
            'sar eax,cl;'
            'pop ecx;'
            'and eax, dword ptr [0x34e2f5];'
        ),
        0x34e310: (0x34e322,
            'and ebx, dword ptr [0x34e312];'
            'add ebp, dword ptr [0x34e318];'
            'push esi;'
            'mov esi,dword ptr [0x34e31e];'
            'mov cl, byte ptr [ebx+esi];'
            'pop esi;'
        ),
        0x34e324: (0x34e33e,
            'add edx, dword ptr [0x34e326];'
            'adc ebx, dword ptr [0x34e32c];'
            'push esi;'
            'movsx esi,byte ptr [0x34e332];'
            'mov cl, byte ptr [ecx+esi];'
            'pop esi;'
            'push esi;'
            'mov esi,dword ptr [0x34e335];'
            'mov byte ptr [eax+esi], cl;'
            'pop esi;'
            'add eax, dword ptr [0x34e33a];'
        ),
        0x34e340: (0x34e346,
            'add edi, dword ptr [0x34e342];'
        ),
        0x34e348: (0x34e34e,
            'test edx, dword ptr [0x34e34a];'
        ),
        0x34e350: (0x34e362,
            'and ebx, dword ptr [0x34e352];'
            'add ebp, dword ptr [0x34e358];'
            'push esi;'
            'mov esi,dword ptr [0x34e35e];'
            'mov cl, byte ptr [ebx+esi];'
            'pop esi;'
        ),
        0x34e364: (0x34e37e,
            'add edx, dword ptr [0x34e366];'
            'adc ebx, dword ptr [0x34e36c];'
            'push esi;'
            'movsx esi,byte ptr [0x34e372];'
            'mov cl, byte ptr [ecx+esi];'
            'pop esi;'
            'push esi;'
            'mov esi,dword ptr [0x34e375];'
            'mov byte ptr [eax+esi], cl;'
            'pop esi;'
            'add eax, dword ptr [0x34e37a];'
        ),
        0x34e380: (0x34e386,
            'add edi, dword ptr [0x34e382];'
        ),
        0x34e390: (0x34e3a2,
            'and ebx, dword ptr [0x34e392];'
            'add ebp, dword ptr [0x34e398];'
            'push esi;'
            'mov esi,dword ptr [0x34e39e];'
            'mov cl, byte ptr [ebx+esi];'
            'pop esi;'
        ),
        0x34e3a4: (0x34e3be,
            'add edx, dword ptr [0x34e3a6];'
            'adc ebx, dword ptr [0x34e3ac];'
            'push esi;'
            'movsx esi,byte ptr [0x34e3b2];'
            'mov cl, byte ptr [ecx+esi];'
            'pop esi;'
            'push esi;'
            'mov esi,dword ptr [0x34e3b5];'
            'mov byte ptr [eax+esi], cl;'
            'pop esi;'
            'add eax, dword ptr [0x34e3ba];'
        ),
        0x34e3c0: (0x34e3c6,
            'add edi, dword ptr [0x34e3c2];'
        ),
        0x34e3c8: (0x34e3ce,
            'test edx, dword ptr [0x34e3ca];'
        ),
        0x34e3d0: (0x34e3e2,
            'and ebx, dword ptr [0x34e3d2];'
            'add ebp, dword ptr [0x34e3d8];'
            'push esi;'
            'mov esi,dword ptr [0x34e3de];'
            'mov cl, byte ptr [ebx+esi];'
            'pop esi;'
        ),
        0x34e3e4: (0x34e3fe,
            'add edx, dword ptr [0x34e3e6];'
            'adc ebx, dword ptr [0x34e3ec];'
            'push esi;'
            'movsx esi,byte ptr [0x34e3f2];'
            'mov cl, byte ptr [ecx+esi];'
            'pop esi;'
            'push esi;'
            'mov esi,dword ptr [0x34e3f5];'
            'mov byte ptr [eax+esi], cl;'
            'pop esi;'
            'add eax, dword ptr [0x34e3fa];'
        ),
        0x34e400: (0x34e406,
            'add edi, dword ptr [0x34e402];'
        ),
    },
    {},
)

IR_AFFINE_RECIPE = (
    0x3311de, 0x3313c3,
    '93260db7d7ad7a691f83fb0a05822c8d917df27e6ec2791c24fa95bd9d940e0f',
    {
        0x3311df: (0x3311e4,
            'mov eax, dword ptr [0x3311e0];'
        ),
        0x331200: (0x331206,
            'cmp ebx, dword ptr [0x331202];'
        ),
        0x331227: (0x33122a,
            'push ecx;'
            'mov cl,[0x331229];'
            'shl edx,cl;'
            'pop ecx;'
        ),
        0x331234: (0x33123a,
            'add edx, dword ptr [0x331236];'
        ),
        0x331245: (0x331250,
            'push ecx;'
            'mov cl,[0x331247];'
            'shl esi,cl;'
            'pop ecx;'
            'push ecx;'
            'mov cl,[0x33124a];'
            'sar eax,cl;'
            'pop ecx;'
            'and eax, dword ptr [0x33124c];'
        ),
        0x331255: (0x33125b,
            'push ecx;'
            'mov cl,[0x331257];'
            'shl edi,cl;'
            'pop ecx;'
            'push ecx;'
            'mov cl,[0x33125a];'
            'sar edx,cl;'
            'pop ecx;'
        ),
        0x331266: (0x331275,
            'test eax, dword ptr [0x331267];'
            'test eax, dword ptr [0x33126c];'
            'L331270:and eax, dword ptr [0x331271];'
        ),
        0x331277: (0x331282,
            'push edi;'
            'mov edi,[0x331279];'
            'mov dl, byte ptr [eax+edi];'
            'pop edi;'
            'adc eax, dword ptr [0x33127e];'
        ),
        0x331284: (0x331290,
            'push edi;'
            'mov edi,[0x331286];'
            'mov dl, byte ptr [edx+edi];'
            'pop edi;'
            'push edi;'
            'mov edi,[0x33128c];'
            'mov byte ptr [ebx+edi], dl;'
            'pop edi;'
        ),
        0x331295: (0x3312a5,
            'and eax, dword ptr [0x331296];'
            'and edx, dword ptr [0x33129c];'
            'L3312a0:and eax, dword ptr [0x3312a1];'
        ),
        0x3312a7: (0x3312b2,
            'push edi;'
            'mov edi,[0x3312a9];'
            'mov dl, byte ptr [eax+edi];'
            'pop edi;'
            'adc eax, dword ptr [0x3312ae];'
        ),
        0x3312b4: (0x3312c0,
            'push edi;'
            'mov edi,[0x3312b6];'
            'mov dl, byte ptr [edx+edi];'
            'pop edi;'
            'push edi;'
            'mov edi,[0x3312bc];'
            'mov byte ptr [ebx+edi], dl;'
            'pop edi;'
        ),
        0x3312c8: (0x3312cd,
            'mov eax, dword ptr [0x3312c9];'
        ),
        0x3312ed: (0x3312f9,
            'add eax, dword ptr [0x3312ef];'
            'adc ebx, dword ptr [0x3312f5];'
        ),
        0x3312fc: (0x331306,
            'add ax, word ptr [0x3312fe];'
            'adc ecx, dword ptr [0x331302];'
        ),
        0x331320: (0x331326,
            'cmp ebx, dword ptr [0x331322];'
        ),
        0x331335: (0x331340,
            'add edx, dword ptr [0x331337];'
            'add eax, dword ptr [0x33133c];'
        ),
        0x33134c: (0x33134f,
            'push ecx;'
            'mov cl,[0x33134e];'
            'shl edx,cl;'
            'pop ecx;'
        ),
        0x331357: (0x331362,
            'add edx, dword ptr [0x331359];'
            'add eax, dword ptr [0x33135e];'
        ),
        0x331376: (0x33137c,
            'add edx, dword ptr [0x331378];'
        ),
        0x33138e: (0x331393,
            'mov esi, dword ptr [0x33138f];'
        ),
    },
    {},
)



def infrared_bodies():
    spans = asm(IR_SPAN_CODE, retained_source(IR_SPAN_RECIPE))
    affine = asm(IR_AFFINE_CODE, 'jmp L3311f0;' + retained_source(IR_AFFINE_RECIPE))
    assert len(spans) <= IR_AFFINE_CODE - IR_SPAN_CODE
    assert len(affine) <= COLUMN_END - IR_AFFINE_CODE
    return [(IR_SPAN_CODE, spans), (IR_AFFINE_CODE, affine),
            (IR_SPAN_SITE, asm(IR_SPAN_SITE, f'jmp {IR_SPAN_CODE}')),
            (IR_AFFINE_SITE, asm(IR_AFFINE_SITE, f'jmp {IR_AFFINE_CODE}'))]


def column_bodies():
    b = column_candidate()
    haze = haze_column_candidate(HAZE_CODE)
    assert len(b) <= HAZE_CODE - COLUMN_CODE
    assert len(haze) <= COLUMN_END - HAZE_CODE
    return [(COLUMN_CODE, b), (COLUMN_SITE, asm(COLUMN_SITE, f'jmp {COLUMN_CODE}') + b'\x90'),
            *infrared_bodies(), (HAZE_CODE, haze),
            (HAZE_SITE, asm(HAZE_SITE, f'jmp {HAZE_CODE}') + b'\x90')]


# Pixel-identical reflective terrain rows without per-row executable writes.
WATER_CODE = 0x1e3d000

WATER_END = WATER_CODE + 0x2000

WATER_SITE = 0x32de50

WATER_ORIGINAL = bytes.fromhex('608bf88b35a0b14400')

WATER_LOW, WATER_HIGH = 0x32de43, 0x32e33b

WATER_CONSTANTS = {
    0x6a890101: 0x32e127,
    0x6a890202: 0x32e133,
    0x6a890303: 0x32e148,
    0x6a890404: 0x32e172
}

WATER_RECIPE = (
    0x32de43, 0x32e33b,
    '763699a5ef1b9ac9307f927642ea2149c9e1663f357d8b9e0ed75134799eefc4',
    {
        0x32e012: (0x32e015,
            'push ecx;'
            'mov cl,[3334164];'
            'shl edx,cl;'
            'pop ecx;'
        ),
        0x32e021: (0x32e027,
            'add edx,[0x32e023];'
        ),
        0x32e060: (0x32e063,
            'push ecx;'
            'mov cl,[3334242];'
            'shl esi,cl;'
            'pop ecx;'
        ),
        0x32e0b4: (0x32e0b7,
            'push ecx;'
            'mov cl,[3334326];'
            'shl edx,cl;'
            'pop ecx;'
        ),
        0x32e0c3: (0x32e0c9,
            'add edx,[0x32e0c5];'
        ),
        0x32e0e3: (0x32e0e6,
            'push ecx;'
            'mov cl,[3334373];'
            'shl esi,cl;'
            'pop ecx;'
        ),
        0x32e120: (0x32e137,
            'mov eax,[0x32e121];'
            'pixCommon:and esi,0x6a890101;'
            'add edi,[0x32e12d];'
            'mov dl,[esi+0x6a890202];'
        ),
        0x32e13b: (0x32e141,
            'add ebp,[0x32e13d];'
        ),
        0x32e145: (0x32e14c,
            'mov eax,[eax*4+0x6a890303];'
        ),
        0x32e14e: (0x32e157,
            'je opaque;'
            'cmp word ptr [0x32e150],0x848a;'
            'jne plain;'
            'push esi;'
            'mov esi,[0x32e153];'
            'lea esi,[esi+ebx];'
            'mov al,[esi+eax];'
            'pop esi;'
            'jmp reflected;'
            'plain:mov al,dl;'
        ),
        0x32e15c: (0x32e17c,
            'add ecx,[0x32e15e];'
            'push esi;'
            'mov esi,[0x32e164];'
            'mov dl,[esi+eax];'
            'pop esi;'
            'jmp store;'
            'opaque:add ecx,[0x32e16c];'
            'mov dl,[edx+0x6a890404];'
            'store:push esi;'
            'mov esi,[0x32e178];'
            'mov [esi+ebx],dl;'
            'pop esi;'
        ),
        0x32e181: (0x32e188,
            'mov eax,[0x32e182];'
            'jmp pixCommon;'
        ),
        0x32e1ad: (0x32e1b8,
            'add eax,[0x32e1ae];'
            'L32e1b2:adc ebx,[0x32e1b4];'
        ),
        0x32e219: (0x32e223,
            'add ax,word ptr [0x32e21b];'
            'L32e21d:adc ecx,[0x32e21f];'
        ),
        0x32e250: (0x32e256,
            'add ebx,[0x32e252];'
        ),
        0x32e26f: (0x32e275,
            'add ebp,[0x32e271];'
        ),
        0x32e27b: (0x32e280,
            'add eax,[0x32e27c];'
        ),
        0x32e293: (0x32e299,
            'add ebp,[0x32e295];'
        ),
        0x32e29f: (0x32e2a4,
            'add eax,[0x32e2a0];'
        ),
        0x32e2b5: (0x32e2bb,
            'add edx,[0x32e2b7];'
        ),
        0x32e2c1: (0x32e2c6,
            'add eax,[0x32e2c2];'
        ),
    },
    {0x32e157: 'reflected'},
)

WATER_PARAMS = [
    (0x32e014, 1), (0x32e023, 4), (0x32e062, 1), (0x32e0b6, 1), (0x32e0c5, 4), (0x32e0e5, 1),
    (0x32e121, 4), (0x32e127, 4), (0x32e12d, 4), (0x32e133, 4), (0x32e13d, 4), (0x32e148, 4),
    (0x32e150, 7), (0x32e15e, 4), (0x32e164, 4), (0x32e16c, 4), (0x32e172, 4), (0x32e178, 4),
    (0x32e182, 4), (0x32e1ae, 4), (0x32e1b4, 4), (0x32e21b, 2), (0x32e21f, 4), (0x32e252, 4),
    (0x32e271, 4), (0x32e27c, 4), (0x32e295, 4), (0x32e2a0, 4), (0x32e2b7, 4), (0x32e2c2, 4)
]


def water_original_fingerprint(r, installed=False):
    b = bytearray(r[WATER_LOW:WATER_HIGH])
    if installed:
        b[WATER_SITE - WATER_LOW:WATER_SITE - WATER_LOW + len(WATER_ORIGINAL)] = WATER_ORIGINAL
    for a, n in WATER_PARAMS:
        b[a - WATER_LOW:a - WATER_LOW + n] = bytes(n)
    return hashlib.sha256(b).hexdigest()


def water_generated(address=WATER_CODE):
    bodybase = address + 0x1000
    labels = {}
    items = []
    pc = bodybase
    for token in ('jmp L32de50;' + retained_source(WATER_RECIPE)).split(';'):
        token = token.strip()
        if not token:
            continue
        if ':' in token:
            label, token = token.split(':', 1)
            labels[label] = pc
            token = token.strip()
        if not token:
            continue
        size = (5 if token.startswith('jmp ') else 6) if token.startswith('j') else len(
            asm(pc, token)
        )
        items.append((pc, token, size))
        pc += size
    body = b''
    for pc, token, size in items:
        if token.startswith('j'):
            op, label = token.split()
            token = f'{op} {labels[label]}'
        encoded = asm(pc, token)
        assert len(encoded) <= size
        body += encoded.ljust(size, b'\x90')
    head = 'push eax;'
    mutable = []
    for marker, param in WATER_CONSTANTS.items():
        needle = struct.pack('<I', marker)
        assert body.count(needle) == 1
        offset = 0x1000 + body.index(needle)
        mutable.append(offset)
        head += f'mov eax,[{param}];mov [{address+offset}],eax;'
    head += f'pop eax;jmp {bodybase};'
    head = asm(address, head)
    assert len(head) < 0x1000
    return head.ljust(0x1000, b'\x90') + body, mutable


def water_candidate(address=WATER_CODE):
    return water_generated(address)[0]


def water_bodies():
    b = water_candidate()
    assert len(b) <= WATER_END - WATER_CODE
    return [(WATER_CODE, b), (WATER_SITE, asm(WATER_SITE, f'jmp {WATER_CODE}') + b'\x90' * 4)]


WATER_FINGERPRINT = '21300be4d165be1a861dd4826e2a49f6849e3ebca4aee8f5cc50ffd6fe36e30c'

# Reserve a whole transformed-polygon row before mutating column-span lists.
SPAN_CODE = 0x1ffe800

SPAN_END = 0x1ffec00

SPAN_SITE = 0x3502a7

SPAN_SITES = {
    SPAN_SITE: bytes.fromhex('8b7c24248b742418'),
    0x1d27000: asm(0x1d27000, 'push 0x1d28000')
}


def span_bodies(audio_path):
    b = asm(
        SPAN_CODE, (
            "pushfd;"
            "pushad;"
            "\n mov esi,[esp+0x48];"
            "mov edi,[esi];"
            "mov ecx,[esi+4];"
            "mov ebp,[esp+0x34];"
            "\n cmp ecx,ebx;"
            "jle separate;"
            "cmp edi,ebp;"
            "jge separate;"
            "\n xor edx,edx;"
            "cmp edi,ebx;"
            "jge right;"
            "mov edx,ebx;"
            "sub edx,edi;"
            "\n right:cmp ecx,ebp;"
            "jle budget;"
            "sub ecx,ebp;"
            "add edx,ecx;"
            "jmp budget;"
            "\n separate:mov edx,ecx;"
            "sub edx,edi;"
            "\n budget:imul edx,edx,12;"
            "jo full;"
            "add edx,eax;"
            "jc full;"
            "\n cmp edx,[esp+0x40];"
            "ja full;"
            "\n popad;"
            "popfd;"
            "mov edi,[esp+0x24];"
            "mov esi,[esp+0x18];"
            "jmp 0x3502af;"
            "\n full:popad;"
            "popfd;"
            "jmp 0x350453;"
        )
    )
    assert len(b) <= SPAN_END - SPAN_CODE
    path = str(audio_path).encode() + b'\0'
    assert len(path) <= SPAN_END - (SPAN_CODE + 0x200)
    return [
        (SPAN_CODE, b), (SPAN_SITE, asm(SPAN_SITE, f'jmp {SPAN_CODE}') + b'\x90' * 3),
        (SPAN_CODE + 0x200, path), (0x1d27000, asm(0x1d27000, f'push {SPAN_CODE+0x200}'))
    ]


# Affine terrain rows, one cue per head reset, and consumed-PCM movie timing.
AFFINE_CODE = 0x1e3f000

AFFINE_END = AFFINE_CODE + 0x1000

AFFINE_SITE = 0x32f700

AFFINE_SOUND = AFFINE_CODE + 0x400

AFFINE_STATE = AFFINE_CODE + 0xe00

AFFINE_SITES = {
    AFFINE_SITE: bytes.fromhex('608bd08b1d9cf73200'),
    0x2d7d18: asm(0x2d7d18, 'call 0x249094'),
    0x2d7e0f: asm(0x2d7e0f, 'call 0x249094'),
    0x1d27000: asm(0x1d27000, 'push 0x1ffea00')
}

AFFINE_SITES[frame_clock.MOVIE_SITE] = frame_clock.MOVIE_ORIGINAL

AFFINE_PARAMS = [
    0x32f78a, 0x32f7ca, 0x32f79c, 0x32f7dc, None, 0x32f772, 0x32f778, 0x32f77e, 0x32f784, 0x32f7c4,
    0x32f75d, 0x32f796, 0x32f7fe, 0x32f804, 0x32f80d, 0x32f813, 0x32f833, 0x32f838, 0x32f84e,
    0x32f85d, 0x32f756
]

AFFINE_N = len(AFFINE_PARAMS) * 4


def affine_source():
    s = f'pushad;sub esp,{AFFINE_N};'
    for i, p in enumerate(AFFINE_PARAMS):
        if p is None:
            continue
        if i == 14:
            s += f'movzx eax,word ptr [{p}];'
        elif i == 20:
            s += f'movzx eax,byte ptr [{p}];'
        else:
            s += f'mov eax,[{p}];'
        s += f'mov [esp+{i*4}],eax;'
    s += (
        f"mov edx,[esp+{AFFINE_N+28}];"
        f"\n row:mov ebx,[esp+8];"
        f"mov eax,[edx+28];"
        f"sub ebx,eax;"
        f"jz nextrow;"
        f"\n cmp ebx,1024;"
        f"jae bad;"
        f"\n mov ebp,[ebx*4+0x45f71c];"
        f"mov esi,[edx+40];"
        f"mov edi,[edx+36];"
        f"\n mov eax,[edx+80];"
        f"mov ecx,[edx+44];"
        f"sub eax,ecx;"
        f"imul ebp;"
        f"\n mov [esp],eax;"
        f"mov [esp+4],eax;"
        f"\n ror ecx,16;"
        f"mov ch,dl;"
        f"mov eax,ecx;"
        f"mov edx,ecx;"
        f"and edx,65535;"
        f"\n mov [esp+16],eax;"
        f"\n mov ecx,esi;"
        f"shl ecx,16;"
        f"mov cl,dh;"
        f"sar esi,16;"
        f"mov ebp,edi;"
        f"\n push ecx;"
        f"mov ecx,[esp+84];"
        f"shl esi,cl;"
        f"pop ecx;"
        f"\n sar ebp,16;"
        f"add esi,ebp;"
        f"mov ebp,[esp+40];"
        f"mov dh,dl;"
        f"neg ebx;"
        f"shl edi,16;"
        f"\n add ecx,ebp;"
        f"jc pixelB;"
        f"jmp pixelA;"
        f"\n pixelA:and esi,[esp+20];"
        f"add edi,[esp+24];"
        f"mov eax,[esp+28];"
        f"mov dl,[esi+eax];"
        f"\n adc esi,[esp+32];"
        f"mov eax,[esp];"
        f"add [esp+16],eax;"
        f"adc dh,cl;"
        f"add ecx,ebp;"
        f"inc ebx;"
        f"\n mov eax,[esp+44];"
        f"mov ch,[edx+eax];"
        f"mov eax,[esp+8];"
        f"mov [ebx+eax],ch;"
        f"\n ja pixelA;"
        f"je nextrow;"
        f"\n pixelB:and esi,[esp+20];"
        f"add edi,[esp+24];"
        f"mov eax,[esp+28];"
        f"mov dl,[esi+eax];"
        f"\n adc esi,[esp+36];"
        f"mov eax,[esp+4];"
        f"add [esp+16],eax;"
        f"adc dh,cl;"
        f"add ecx,ebp;"
        f"inc ebx;"
        f"\n mov eax,[esp+44];"
        f"mov ch,[edx+eax];"
        f"mov eax,[esp+12];"
        f"mov [ebx+eax],ch;"
        f"\n ja pixelA;"
        f"jne pixelB;"
        f"\n nextrow:mov edx,[esp+{AFFINE_N+28}];"
        f"mov ebx,[esp+12];"
        f"\n mov eax,[edx+8];"
        f"add eax,[esp+48];"
        f"adc ebx,[esp+52];"
        f"mov ecx,[edx+28];"
        f"\n add ax,[esp+56];"
        f"sbb ebp,ebp;"
        f"add ecx,[esp+60];"
        f"sub ecx,ebp;"
        f"\n mov [edx+8],eax;"
        f"mov [esp+12],ebx;"
        f"mov [esp+8],ebx;"
        f"mov [edx+28],ecx;"
        f"\n mov eax,[edx+80];"
        f"mov ecx,[edx+44];"
        f"add ecx,[esp+64];"
        f"add eax,[esp+68];"
        f"\n mov [edx+44],ecx;"
        f"mov [edx+80],eax;"
        f"\n mov eax,[edx+52];"
        f"mov edi,[edx+36];"
        f"and eax,ebp;"
        f"add edi,eax;"
        f"add edi,[esp+72];"
        f"mov [edx+36],edi;"
        f"\n mov esi,[edx+40];"
        f"and ebp,[edx+56];"
        f"add esi,[esp+76];"
        f"add esi,ebp;"
        f"mov [edx+40],esi;"
        f"\n dec dword ptr [edx];"
        f"jnz row;"
        f"jmp good;"
        f"\n "
    )
    # The old clipping/setup helpers read the updated generated operands.
    # Preserve these observable side effects once at return, outside the hot loop.
    for label, result in [('bad', 'mov eax,1;'), ('good', 'xor eax,eax;')]:
        s += label + ':'
        for i, p in enumerate(AFFINE_PARAMS[:4]):
            s += f'mov eax,[esp+{i*4}];mov [{p}],eax;'
        s += f'lea esp,[esp+{AFFINE_N}];popad;{result}ret;'
    return s


def affine_bodies(audio_path):
    b = asm(AFFINE_CODE, affine_source())
    assert len(b) < 0x400
    out = [(AFFINE_CODE, b), (AFFINE_SITE, asm(AFFINE_SITE, f'jmp {AFFINE_CODE}') + b'\x90' * 4)]
    for k, (site, ident) in enumerate(((0x2d7d18, 3), (0x2d7e0f, 2))):
        a = AFFINE_SOUND + k * 0x80
        state = AFFINE_STATE + k * 4
        out.append(
            (
                a,
                asm(
                    a, (
                        f"pushfd;"
                        f"cmp eax,{ident};"
                        f"jne reset;"
                        f"test edx,edx;"
                        f"jz reset;"
                        f"\n   cmp dword ptr [{state}],0;"
                        f"jne silent;"
                        f"mov dword ptr [{state}],1;"
                        f"\n   popfd;"
                        f"jmp 0x249094;"
                        f"\n   reset:mov dword ptr [{state}],0;"
                        f"popfd;"
                        f"jmp 0x249094;"
                        f"\n   silent:popfd;"
                        f"ret;"
                    )
                )
            )
        )
        out.append((site, asm(site, f'call {a}')))
    path = str(audio_path).encode() + b'\0'
    assert len(path) < 0x200
    out.extend(
        [(AFFINE_CODE + 0x600, path), (0x1d27000, asm(0x1d27000, f'push {AFFINE_CODE+0x600}'))]
    )
    out.extend(frame_clock.movie_bodies())
    return out


def column_install(write, read):
    """Validate original hooks and the complete cold reservation before writing."""
    from features.input_views import _install
    return _install(
        column_bodies(), {COLUMN_SITE: COLUMN_ORIGINAL, HAZE_SITE: HAZE_ORIGINAL, **IR_ORIGINAL},
        write,
        read,
        cold_state=((COLUMN_CODE, COLUMN_END - COLUMN_CODE), )
    )


def column_verify(read):
    from features.input_views import _verify
    return _verify(column_bodies(), read)


def water_fingerprint(read, *, installed=False):
    original = bytearray(read(WATER_LOW, WATER_HIGH - WATER_LOW))
    if installed:
        offset = WATER_SITE - WATER_LOW
        original[offset:offset + len(WATER_ORIGINAL)] = WATER_ORIGINAL
    for address, size in WATER_PARAMS:
        original[address - WATER_LOW:address - WATER_LOW + size] = bytes(size)
    return hashlib.sha256(original).hexdigest()


def water_verify(read):
    expected, mutable = water_generated()
    actual = bytearray(read(WATER_CODE, len(expected)))
    for offset in mutable:
        actual[offset:offset + 4] = expected[offset:offset + 4]
    if bytes(actual) != expected:
        raise ValueError('Reflection helper instructions changed')
    hook = dict(water_bodies())[WATER_SITE]
    if (
        bytes(read(WATER_SITE, len(hook))) != hook
        or water_fingerprint(read, installed=True) != WATER_FINGERPRINT
    ):
        raise ValueError('Original reflection setup changed')
    return True


def water_install(write, read):
    from features.input_views import _install
    hook = dict(water_bodies())[WATER_SITE]
    if bytes(read(WATER_SITE, len(hook))) == hook:
        water_verify(read)
        return dict(already_installed=True, ranges=[])
    if water_fingerprint(read) != WATER_FINGERPRINT:
        raise ValueError('Unexpected reflection program')
    return _install(
        water_bodies(), {WATER_SITE: WATER_ORIGINAL},
        write,
        read,
        cold_state=((WATER_CODE, WATER_END - WATER_CODE), )
    )


def surface_bodies(span_audio_path, movie_audio_path):
    """Emit final row/storage hooks once, retaining snapshot-compatible bytes.

    The two DLL strings occupy accepted image slots. Only the movie path is
    active; packaging relocates it. Neither path is inferred from history.
    """
    spans = dict(span_bodies(span_audio_path))
    spans.update(affine_bodies(movie_audio_path))
    return list(spans.items())


def surface_providers():
    return {**AFFINE_SITES, **SPAN_SITES}


def surface_install(write, read, *, span_audio_path, movie_audio_path):
    from features.input_views import _install
    return _install(
        surface_bodies(span_audio_path, movie_audio_path),
        surface_providers(),
        write,
        read,
        cold_state=((SPAN_CODE, SPAN_END - SPAN_CODE), (AFFINE_CODE, AFFINE_END - AFFINE_CODE))
    )


def surface_verify(read, *, span_audio_path, movie_audio_path):
    from features.input_views import _verify
    return _verify(surface_bodies(span_audio_path, movie_audio_path), read)


SKY_ROW_SITE = 0x2a73de
SKY_ROW_END = 0x2a7423
SKY_ROW_ORIGINAL_SHA = '1fd96c54d86b3c46ad5f4793010c5dc1569be442bdeba4073a333f49f3713df5'


def sky_row_body():
    """Evaluate each sky ray directly to avoid accumulating rounded increments.

    EAX contains the normalized 16.16 screen row. The original recurrence
    rounds each tiny negative product down before adding it to the preceding
    row. Small changes in walking tilt can therefore move the cloud layer by
    a visible step. Direct evaluation keeps each rounding error below one
    fixed-point unit, regardless of the viewport height.

    EBX, ESI and EDX are the three ray components consumed by the original
    intersection calculation. No extra storage or per-frame state is needed.
    """
    body = asm(
        SKY_ROW_SITE, (
            'mov ecx,eax;'
            'mov eax,[0x41ebaa];imul ecx;shrd eax,edx,16;'
            'sub eax,[0x41eb9e];mov ebx,eax;'
            'mov eax,[0x41ebb2];imul ecx;shrd eax,edx,16;'
            'sub eax,[0x41eba6];mov esi,eax;'
            'mov eax,[0x41ebae];imul ecx;shrd eax,edx,16;'
            'mov edx,[0x41eba2];sub edx,eax;'
        )
    )
    assert len(body) <= SKY_ROW_END - SKY_ROW_SITE
    return body.ljust(SKY_ROW_END - SKY_ROW_SITE, b'\x90')


def sky_install(write, read):
    body = sky_row_body()
    before = bytes(read(SKY_ROW_SITE, len(body)))
    if before == body:
        return dict(already_installed=True, ranges=[])
    if hashlib.sha256(before).hexdigest() != SKY_ROW_ORIGINAL_SHA:
        raise ValueError('Unexpected original sky row calculation')
    write(SKY_ROW_SITE, body)
    return dict(ranges=[(SKY_ROW_SITE, SKY_ROW_END)])


def sky_verify(read):
    if bytes(read(SKY_ROW_SITE, SKY_ROW_END - SKY_ROW_SITE)) != sky_row_body():
        raise ValueError('Sky row calculation differs')
    return True
