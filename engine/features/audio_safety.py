"""Reject incomplete QSound channel pairs before they can corrupt memory.

The original availability estimate can include channels that are reserved but
have not started playing. Either allocation can therefore fail after the
estimate succeeds. Treat its -1 result as failure before indexing the channel
tables. Successful pairs and the original permitted single-channel path keep
their existing behavior.
"""
from patch_support import asm

CODE = 0x1fffa00
END = 0x2000000
FIRST_SITE = 0x2effd8
SECOND_SITE = 0x2efffa
SITES = {
    FIRST_SITE: bytes.fromhex('8b4df08845fc'),
    SECOND_SITE: bytes.fromhex('8b4df9c1f918'),
}


def bodies():
    first = asm(CODE, '''
        cmp al, 0xff;
        je failed;
        mov ecx, [ebp-0x10];
        mov [ebp-4], al;
        jmp 0x2effde;
    failed:
        jmp 0x2effab;
    ''')
    second = asm(CODE + 0x40, '''
        cmp al, 0xff;
        je failed;
        mov ecx, [ebp-7];
        sar ecx, 24;
        jmp 0x2f0000;
    failed:
        movzx eax, byte ptr [ebp-4];
        imul eax, eax, 38;
        mov byte ptr [eax+0x44b3a3], 0;
        jmp 0x2effab;
    ''')
    # The first sample has only been initialized; playback has not started.
    # Release its reservation directly. Ending an already-stopped sample does
    # nothing, while running its completion callback would release resources
    # that the caller already releases when this function reports failure.
    assert len(first) <= 0x40 and CODE + 0x40 + len(second) <= END
    return (
        (CODE, first), (CODE + 0x40, second),
        (FIRST_SITE, asm(FIRST_SITE, f'jmp {CODE}') + b'\x90'),
        (SECOND_SITE, asm(SECOND_SITE, f'jmp {CODE + 0x40}') + b'\x90'),
    )


def verify(read):
    for address, data in bodies():
        if bytes(read(address, len(data))) != data:
            raise ValueError(f'QSound allocation guard differs at {address:#x}')
    return True


def install(write, read):
    pieces = bodies()
    if all(bytes(read(a, len(b))) == b for a, b in pieces):
        return dict(already_installed=True, ranges=[])
    if any(bytes(read(a, len(b))) != b for a, b in SITES.items()):
        raise ValueError('Unexpected QSound allocation instructions')
    if any(read(CODE, END - CODE)):
        raise ValueError('QSound allocation reservation is occupied')
    for address, data in pieces:
        write(address, data)
    return dict(ranges=[(a, a + len(b)) for a, b in pieces])
