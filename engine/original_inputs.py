"""Verified original executable images and native import-table access."""
import struct
import hashlib
from le_image import LE
from pathlib import Path
from build_paths import CONFIG

SIZE = 0x2000000
PAGE = 4096
original_ram = bytearray(SIZE)
demo_ram = bytearray(0x1000000)
_original = None
_header = None


def reference_root():
    return Path(CONFIG['log_root']).parent


def set_header(header):
    global _header
    _header = bytes(header)


def initialize(data):
    global _original
    if _original is not None:
        raise RuntimeError('Build inputs already initialized')
    _original = bytes(data)
    le = LE(data)
    bases = (0x244000, 0x354000, 0x355000)
    for base, img in zip(bases, le.relocated(bases)):
        original_ram[base:base + len(img)] = img


def initialize_demo(data):
    le = LE(data)
    bases = (0x244000, 0x354000, 0x355000)
    for base, img in zip(bases, le.relocated(bases)):
        if base + len(img) > len(demo_ram):
            raise ValueError('Demo image exceeds address space')
        demo_ram[base:base + len(img)] = img


def original_executable():
    if _original is None:
        raise RuntimeError('Original input not initialized')
    return _original


class Image:
    base = 0x10000

    def __init__(self, ram, previous=None):
        if len(ram) != SIZE:
            raise ValueError('Unexpected native address space size')
        self.pages = tuple(
            previous.pages[i // PAGE] if previous is not None
            and ram[i:i + PAGE] == previous.pages[i // PAGE] else bytes(ram[i:i + PAGE])
            for i in range(0, SIZE, PAGE)
        )

    def read(self, address, size):
        if address < 0 or size < 0 or address + size > SIZE:
            raise ValueError('Image read out of bounds')
        if not size:
            return b''
        start = address // PAGE
        end = (address + size - 1) // PAGE + 1
        return b''.join(self.pages[start:end])[address % PAGE:address % PAGE + size]

    @property
    def mem(self):
        return self.read(self.base, SIZE - self.base)

    @property
    def imports(self):
        if _header is None:
            raise RuntimeError('PE header not supplied')
        u32 = lambda b, o=0: struct.unpack_from('<I', b, o)[0]
        opt = u32(_header, 0x3c) + 24
        desc = u32(_header, opt + 104)
        result = {}
        for _ in range(128):
            if not desc:
                break
            entry = self.read(self.base + desc, 20)
            if not any(entry):
                break
            ilt, _, _, dll, iat = struct.unpack('<5I', entry)
            for i in range(1000):
                p = u32(self.read(self.base + (ilt or iat) + i * 4, 4))
                if not p:
                    break
                if not p & 0x80000000:
                    name = self.read(self.base + p + 2, 256).split(b'\0')[0].decode('ascii')
                    result[name] = self.base + iat + i * 4
            else:
                raise ValueError('Unterminated import table')
            desc += 20
        else:
            raise ValueError('Unterminated import descriptors')
        return result


def edited_assembly(recipe, read=None):
    """Read retained instructions locally, then apply the listed changes.

    These routines use their original setup and branch layout. Keeping those
    passages in the user's executable avoids publishing copied disassembly.
    Callers supply only their edits, such as reading mutable operands as data
    or reversing a sprite's texture coordinates.
    The input digest and instruction boundaries make a different executable
    fail before assembly, rather than silently producing a different loop.
    """
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    low, high, digest, edits, aliases = recipe
    if read is None:
        read = lambda address, size: bytes(original_ram[address:address + size])
    data = bytes(read(low, high - low))
    if len(data) != high - low or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Local assembly requires the verified original executable')
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(data, low))
    boundaries = {i.address for i in instructions} | {high}
    if sum(i.size for i in instructions) != len(data):
        raise ValueError('Original routine did not decode completely')
    end = low
    for start, (stop, replacement) in sorted(edits.items()):
        if start == high or start not in boundaries or stop not in boundaries or not end <= start <= stop:
            raise ValueError('Invalid assembly edit boundaries')
        end = stop
    parts = []
    end = low
    for instruction in instructions:
        address = instruction.address
        if address < end:
            continue
        prefix = (aliases[address] + ':;' if address in aliases else '') + f'L{address:x}:'
        if address in edits:
            end, replacement = edits[address]
            parts.append(prefix + replacement)
            if end > address:
                continue
            prefix = ''
        operand = instruction.op_str
        if instruction.mnemonic.startswith('j') and operand.startswith('0x'):
            target = int(operand, 16)
            if target not in boundaries or target == high:
                raise ValueError('Branch leaves the declared original routine')
            operand = f'L{target:x}'
        parts.append(prefix + instruction.mnemonic + ' ' + operand + ';')
    return '\n'.join(parts)


