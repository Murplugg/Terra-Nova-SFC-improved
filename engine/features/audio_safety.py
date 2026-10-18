"""Protect QSound allocation and preserve firing sounds after immediate impacts.

The original availability estimate can include channels that are reserved but
have not started playing. Either allocation can therefore fail after the
estimate succeeds. Treat its -1 result as failure before indexing the channel
tables. Successful pairs and the original permitted single-channel path keep
their existing behavior.

The original firing queue also cancels a muzzle sound when its projectile dies.
Keep that sound while removing the dead projectile association; its separate
flight sound must not attach to a deleted or reused object.
"""
from patch_support import asm

CODE = 0x1fffa00
END = 0x2000000
FIRST_SITE = 0x2effd8
SECOND_SITE = 0x2efffa
QUEUE_DELETE = 0x2904f8
QUEUE_CODE = CODE + 0x80
SITES = {
    FIRST_SITE: bytes.fromhex('8b4df08845fc'),
    SECOND_SITE: bytes.fromhex('8b4df9c1f918'),
    QUEUE_DELETE: bytes.fromhex('535689c331c0'),
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
    queue_delete = asm(QUEUE_CODE, '''
        push ebx;
        push esi;
        mov ebx, eax;
        xor eax, eax;
    again:
        cmp bx, word ptr [eax+0x397a50];
        je shooter;
        cmp bx, word ptr [eax+0x397a52];
        jne next;
        mov word ptr [eax+0x397a52], 0;
        jmp next;
    shooter:
        xor esi, esi;
        mov word ptr [eax+0x397a54], si;
    next:
        add eax, 12;
        cmp eax, 24;
        jne again;
        pop esi;
        pop ebx;
        ret;
    ''')
    # Two queue entries hold shooter, projectile, muzzle/flight samples and
    # distance. The drain checks projectile > 0 before starting flight audio.
    # Deleting the shooter still cancels its pending muzzle sound entirely.
    assert len(first) <= 0x40 and len(second) <= 0x40
    assert QUEUE_CODE + len(queue_delete) <= END
    return (
        (CODE, first), (CODE + 0x40, second),
        (FIRST_SITE, asm(FIRST_SITE, f'jmp {CODE}') + b'\x90'),
        (SECOND_SITE, asm(SECOND_SITE, f'jmp {CODE + 0x40}') + b'\x90'),
        (QUEUE_CODE, queue_delete),
        (QUEUE_DELETE, asm(QUEUE_DELETE, f'jmp {QUEUE_CODE}') + b'\x90'),
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
