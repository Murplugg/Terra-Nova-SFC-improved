"""Deliver room hover events reliably without dismissing noninteractive pages.

The poller at 0x2b6457 updates its rectangle cache before offering event 0x90+n
to the room interpreter. A busy interpreter rejects that offer. Retry until it
is accepted, and discard a pending event when the room removes its last hotspot.
Otherwise that event can immediately dismiss the recruitment letter's input wait.
EAX and flags follow the original poller convention; the callee preserves the
other registers and the stack.
"""
from patch_support import asm

SITE = 0x2B6457
CONTINUE = 0x2B647A
CODE = 0x1D2EF00
STATE = 0x1D2EFC0
END = 0x1D2F000
ORIGINAL = bytes.fromhex('3b05d0cd4300741ba3d0cd4300b890000000660305d0cd430025ffff0000e8221d0300')


def code(discard_without_hotspots=True):
    prefix = (
        f"cmp dword ptr [0x43cdd4],0;"
        f"jg interactive;"
        f"\n        mov [0x43cdd0],eax;"
        f"mov dword ptr [{STATE}],0;"
        f"\n        jmp {CONTINUE};"
        f"interactive:"
    ) if discard_without_hotspots else ''
    body = asm(
        CODE, prefix + (
            f"cmp eax,[0x43cdd0];"
            f"jne changed;"
            f"\n        cmp dword ptr [{STATE}],0;"
            f"je done;"
            f"\n        changed:mov [0x43cdd0],eax;"
            f"add eax,0x90;"
            f"and eax,0xffff;"
            f"\n        call 0x2e819c;"
            f"mov dword ptr [{STATE}],0;"
            f"test eax,eax;"
            f"jnz done;"
            f"\n        mov dword ptr [{STATE}],1;"
            f"\n        done:jmp {CONTINUE};"
        )
    )
    assert CODE + len(body) <= STATE
    return body


def hook():
    return asm(SITE, f'jmp {CODE}') + b'\x90' * 3


def install(write, ram):
    """Install reliable hover delivery into a fresh build image.

    The original poller must match and reserved storage must be empty. A partial
    installation is rejected before any instructions are replaced.
    """
    assert bytes(ram[SITE:CONTINUE]) == ORIGINAL, 'unexpected room hover poller'
    assert not any(ram[CODE:END]), 'room event reservation is occupied'
    pieces = [(CODE, code()), (STATE, b'\1\0\0\0'), (SITE, hook())]
    for address, data in pieces:
        write(address, data)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
