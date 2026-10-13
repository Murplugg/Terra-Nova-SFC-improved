"""Build a relocatable LE image from the verified retail executable.

Checked assembly generators supply the foundation patches and their initial
state. The native host then adapts system calls and installs the game features.
"""
from le_image import *
from patch_inventory import inventory
from foundation_overlays import DIALOG_TEMP as TEMP
from foundation_cameras import initial_data, CAM_GUARDS
from foundation_hud import GUARDS, FRAME, CAPACITY
from foundation_weather import ROW_GUARDS
from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_GRP_JUMP, CS_GRP_CALL, CS_GRP_RET
from capstone.x86 import X86_OP_IMM, X86_OP_MEM
import json

ARENA = 0x8234e8
BASES = (0x244000, 0x354000, 0x355000, ARENA)
SOURCE_HASH = 'b762c54509f1716282c4d357a72013b8d84ba25f17b0483b733678ff81e63dd1'


def make(data):
    assert hashlib.sha256(data).hexdigest() == SOURCE_HASH
    le = LE(data)
    # Extra image object is owned by the DOS loader rather than a captured heap.
    le.objects.append([0x200000, 0x260000, 0x2047, 0, 0, 0])
    le.images.append(bytearray(0x200000))
    le.images[0].extend(bytes(0x111000 - len(le.images[0])))
    static, _, blocks = inventory()
    # Preserve displaced original world-entry instructions in their trampoline.
    from keystone import Ks, KS_ARCH_X86, KS_MODE_32
    k = Ks(KS_ARCH_X86, KS_MODE_32)
    tramp = bytes(
        k.asm(
            ("push ebx;"
             " push ecx;"
             " push esi;"
             " push edi;"
             " push ebp;"
             " jmp 0x29edb9"),
            addr=0x9a36e8
        )[0]
    )
    for a, b in [(0x9a36e8, tramp)]:
        static.update({a + i: x for i, x in enumerate(b)})
        blocks.append((a, len(b), 'final'))
    # The 640x480 Help screen borrows 307200 scratch bytes. Four enlarged view
    # caches consume 13392 bytes, exceeding the original 319488-byte pool by
    # 1104 bytes. Grow both the real allocation and its allocator capacity.
    for a in (0x2c4ee2, 0x2c4ee7):
        assert bytes(le.images[0][a - BASES[0]:a - BASES[0] + 4]) == struct.pack('<I', 0x4e000)
        b = struct.pack('<I', 0x80000)
        static.update({a + i: x for i, x in enumerate(b)})
        blocks.append((a, 4, 'scratch capacity'))

    def locate(a):
        if 0x244000 <= a < 0x355000:
            return 1, a - 0x244000
        if 0x355000 <= a < 0x464900:
            return 3, a - 0x355000
        if ARENA <= a < ARENA + 0x200000:
            return 4, a - ARENA
        return None

    def write(a, b):
        obj, off = locate(a)
        assert off + len(b) <= len(le.images[obj - 1]), hex(a)
        le.images[obj - 1][off:off + len(b)] = b

    def read(a, n):
        obj, off = locate(a)
        return bytes(le.images[obj - 1][off:off + n])

    # Existing original fixups will be replaced where a hook changes their bytes.
    le.fixups = [
        f for f in le.fixups
        if not any(BASES[f[0] - 1] + f[1] + i in static for i in range(2 if f[2] == 2 else 4))
    ]
    for a, b in static.items():
        write(a, bytes([b]))
    for a in (
        TEMP - 256, TEMP + 64000, *GUARDS, *ROW_GUARDS, *CAM_GUARDS, 0x85ff00, 0x86fa00, 0x86ff00,
        0x87fa00, FRAME - 256, FRAME + CAPACITY
    ):
        write(a, b'\xa5' * 256)
    write(0x870000, b'\xff' * 64000)
    write(0x9a54e8, b''.join(struct.pack('<H', x * 320 // 800) for x in range(800)))
    write(0x9a64e8, b''.join(struct.pack('<I', (y // 3) * 320) for y in range(600)))
    for a, b in initial_data():
        write(a, b)
    # Identify reachable payload instructions from the original-image hooks.
    cs = Cs(CS_ARCH_X86, CS_MODE_32)
    cs.detail = True
    code = {}
    queue = []
    fixups = {}
    outside = []

    def fix(a, typ, dest):
        target = locate(dest)
        if not target:
            return
        obj, off = locate(a)
        record = (obj, off, typ, *target)
        if a in fixups:
            assert fixups[a] == record
        fixups[a] = record

    def instruction(i):
        for op in i.operands:
            if op.type == X86_OP_MEM and i.disp_size == 4:
                v = op.mem.disp & 0xffffffff
                if locate(v):
                    fix(i.address + i.disp_offset, 7, v)
            elif op.type == X86_OP_IMM:
                v = op.imm & 0xffffffff
                if i.group(CS_GRP_CALL) or i.group(CS_GRP_JUMP):
                    if i.imm_size == 4 and locate(v):
                        fix(i.address + i.imm_offset, 8, v)
                    if v >= ARENA or 0x354940 <= v < 0x355000:
                        queue.append(v)
                elif i.imm_size == 4 and locate(v):
                    fix(i.address + i.imm_offset, 7, v)
        code[i.address] = i

    # All external edits are either an instruction sequence or a 32-bit immediate.
    changed = sorted(a for a in static if a < 0x354940)
    ranges = []
    for a in changed:
        if ranges and ranges[-1][1] == a:
            ranges[-1][1] = a + 1
        else:
            ranges.append([a, a + 1])
    for a, end in ranges:
        b = read(a, end - a)
        if len(b) == 4:
            value = U(b, 0)
            if locate(value):
                fix(a, 7, value)
        else:
            consumed = 0
            for i in cs.disasm(b, a):
                instruction(i)
                consumed += i.size
            assert consumed == len(b), (hex(a), b.hex())
    while queue:
        a = queue.pop()
        while a not in code:
            if not (ARENA <= a < ARENA + 0x200000 or 0x354940 <= a < 0x355000):
                break
            i = next(cs.disasm(read(a, 15), a, count=1), None)
            assert i is not None, hex(a)
            assert all(i.address + j in static for j in range(i.size)
                       ), (hex(a), i.mnemonic, i.op_str, 'uninitialized code')
            instruction(i)
            if i.group(CS_GRP_RET) or i.mnemonic == 'jmp':
                break
            a += i.size
    # Initialized camera pointers are data, not instruction operands.
    for i in range(3):
        for off in (56, 60, 64):
            a = 0x9dc400 + 128 * i + off
            fix(a, 7, U(read(a, 4), 0))
    le.fixups.extend(fixups.values())
    # Reject accidental references to old runtime heap objects in payload operands.
    for a, i in code.items():
        if a < ARENA:
            continue
        for op in i.operands:
            v = (
                op.imm if op.type == X86_OP_IMM else op.mem.disp if op.type == X86_OP_MEM else 0
            ) & 0xffffffff
            if 0x464900 <= v < 0x2000000 and not locate(v) and v != 0x00c80140:
                outside.append((hex(a), i.mnemonic, i.op_str, hex(v)))
    assert not outside, outside
    out = le.encode()
    again = LE(out)
    assert set(le.fixups) == set(again.fixups) and le.images == again.images
    # Relocate back to the proven layout and compare all patched instruction bytes.
    images = again.relocated(BASES)
    for a, i in code.items():
        obj, off = locate(a)
        assert bytes(images[obj - 1][off:off + i.size]) == i.bytes, (hex(a), i.mnemonic, i.op_str)
    return out, dict(
        original_sha256=SOURCE_HASH,
        patched_sha256=hashlib.sha256(out).hexdigest(),
        bytes=len(out),
        payload_instructions=len(code),
        new_relocations=len(fixups),
        original_hooks=ranges,
        objects=again.objects,
        relocations=len(again.fixups)
    )
