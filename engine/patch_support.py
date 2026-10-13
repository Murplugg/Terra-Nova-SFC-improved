"""Assemble x86 helpers and read or write their little-endian operands."""
import struct
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
from original_inputs import Image

k = Ks(KS_ARCH_X86, KS_MODE_32)


def asm(address, source):
    return bytes(k.asm(source, addr=address)[0])


u32 = lambda data, at=0: struct.unpack_from('<I', data, at)[0]
pack = lambda value: struct.pack('<I', value)


def PE(image):
    if not isinstance(image, Image):
        raise TypeError('Supply a rebuilt predecessor image')
    return image
