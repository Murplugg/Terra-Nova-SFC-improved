"""Check renderer dependencies before generating any replacement code.

A bounded image reader supplies the six sky-row groups and two sky helpers.
Binding verifies their instructions and addresses, then returns an immutable plan
that the renderer can use without searching the image again.
"""
from dataclasses import dataclass
import struct
from patch_support import asm

PRESENTER_BEGIN = 0x1d19000
PRESENTER_END = 0x1d19800
PRESENTER_STORE = bytes.fromhex('a30cd0d101')


@dataclass(frozen=True)
class Bindings:
    presenter: int
    edits: tuple


def sky_source(index, effect, stats, height):
    """Existing sky-row guard; preserve its instruction order and register ABI."""
    if index not in ('edx', 'ecx'):
        raise ValueError('Unsupported sky index register')
    return (
        f"pushfd;"
        f"push ebx;"
        f"push esi;"
        f"\n    mov ebx,dword ptr [0x44b1a0];"
        f"movzx ebx,word ptr [ebx+10];"
        f"\n    cmp ebx,{height};"
        f"jbe cap;"
        f"mov ebx,{height};"
        f"\n    cap:shl ebx,2;"
        f"cmp {index},4;"
        f"jb skip;"
        f"cmp {index},ebx;"
        f"ja skip;"
        f"\n    mov dword ptr [{index}+{effect-4}],eax;"
        f"jmp done;"
        f"\n    skip:inc dword ptr [{stats+12}];"
        f"\n    done:pop esi;"
        f"pop ebx;"
        f"popfd;"
        f"ret;"
    )


def bind(read, layout, row_groups, sky_helpers, *, old_effect, stats):
    """Verify full helper preimages and uniquely identify the presenter hook."""

    def checked(address, size):
        if not 0x11000 <= address < address + size <= 0x2000000:
            raise ValueError('Renderer provider outside native image')
        data = bytes(read(address, size))
        if len(data) != size:
            raise ValueError('Truncated renderer provider at ' + hex(address))
        return data

    if len(row_groups) != 6 or len(layout.skyrows) != 6:
        raise ValueError('Renderer requires six sky-row groups')
    if len(sky_helpers) != 2 or tuple(index for _, index in sky_helpers) != ('edx', 'ecx'):
        raise ValueError('Renderer requires EDX/ECX sky helpers in order')
    edits = []
    seen = set()

    def add(address, value):
        if any(address < old + 4 and old < address + 4 for old in seen):
            raise ValueError('Overlapping renderer provider operands')
        seen.add(address)
        edits.append((address, value))

    for replacement, (old, sites) in zip(layout.skyrows, row_groups):
        if not sites:
            raise ValueError('Empty sky-row provider group')
        for address in sites:
            if checked(address, 4) != struct.pack('<I', old):
                raise ValueError('Sky-row predecessor mismatch at ' + hex(address))
            add(address, replacement)
    # This adjacent entry was already protected by the stage installer's full
    # preimage comparison. Validate it at binding time as well.
    if checked(0x2a7a1e, 4) != struct.pack('<I', row_groups[0][0] - 4):
        raise ValueError('Sky-row base predecessor mismatch')
    add(0x2a7a1e, layout.skyrows[0] - 4)
    for address, index in sky_helpers:
        expected = asm(address, sky_source(index, old_effect, stats, 600))
        if checked(address, len(expected)) != expected:
            raise ValueError('Sky helper predecessor mismatch at ' + hex(address))
        # Full-source verification above establishes these are the intended
        # operands, not coincidental values in unrelated instructions/data.
        for old, replacement, count in ((old_effect - 4, layout.effect - 4, 1), (600, 1200, 2)):
            needle = struct.pack('<I', old)
            positions = [n for n in range(len(expected) - 3) if expected[n:n + 4] == needle]
            if len(positions) != count:
                raise ValueError('Unexpected sky helper operand layout')
            for pos in positions:
                add(address + pos, replacement)
    block = checked(PRESENTER_BEGIN, PRESENTER_END - PRESENTER_BEGIN)
    positions = [
        n for n in range(len(block) - len(PRESENTER_STORE) + 1)
        if block[n:n + len(PRESENTER_STORE)] == PRESENTER_STORE
    ]
    if len(positions) != 1:
        raise ValueError('Expected one renderer presenter store; found ' + str(len(positions)))
    presenter = PRESENTER_BEGIN + positions[0]
    if any(presenter < address + 4 and address < presenter + 5 for address in seen):
        raise ValueError('Presenter overlaps renderer operand edits')
    return Bindings(presenter, tuple(edits))
