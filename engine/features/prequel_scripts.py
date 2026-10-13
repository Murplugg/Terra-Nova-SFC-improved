"""Connect the original demo mission scripts to the retail engine's services.

The caller supplies verified, relocated original images and the callback-table
recipe. These bindings let the native game run demo missions with retail services.
"""
import struct
import re
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from patch_support import asm

md = Cs(CS_ARCH_X86, CS_MODE_32)
md.detail = True


def table(r, a):
    out = []
    for i in range(1000):
        v = struct.unpack_from('<I', r, a + 4 * i)[0]
        if not 0x244000 <= v < 0x354000:
            break
        out.append(v)
    return out


def instructions(r, a):
    out = []
    for i in md.disasm(bytes(r[a:a + 160]), a):
        out.append(i)
        if i.mnemonic.startswith('ret'):
            break
    return out


def norm(i):
    s = i.op_str
    if i.mnemonic.startswith(('j', 'call')):
        s = re.sub(r'0x[0-9a-f]+', 'ADDR', s)
    else:
        s = re.sub(r'0x[0-9a-f]{5,}', 'ADDR', s)
    return (i.mnemonic, s)


def sig(r, a):
    return [norm(i) for i in instructions(r, a)]


CODE = 0x1ef6800

VARS = CODE

FUNCS = CODE + 0x100

SQUAD = CODE + 0x400

STUB = CODE + 0x600

LOADOUT = CODE + 0xd40


def port(start, end, dest, *, retail, demo):
    b = bytearray(demo[start:end])
    for i in md.disasm(bytes(b), start):
        off = i.address - start
        if i.mnemonic == 'call' and i.op_str.startswith('0x'):
            target = int(i.op_str, 16)
            mapped = target + (0x9d0 if target >= 0x2e0000 else 0x160)
            assert sig(demo, target) == sig(retail, mapped), (hex(target), hex(mapped))
            struct.pack_into('<i', b, off + i.imm_offset, mapped - (dest + off + i.size))
        for operand in i.operands:
            value = operand.imm if operand.type == 2 else operand.mem.disp if operand.type == 3 else 0
            if 0x354000 <= value < 0x450000:
                mapped = value + (0x2d0 if value < 0x360000 else -0x230)
                pos = i.imm_offset if operand.type == 2 else i.disp_offset
                assert (i.imm_size if operand.type == 2 else i.disp_size) == 4
                struct.pack_into('<I', b, off + pos, mapped)
    return bytes(b)


def pieces(retail, demo, rows):
    rf = table(retail, 0x35dccc)
    assert len(rf) > 100 and len(demo) > 0x35e004, "Incomplete original script inputs"
    overrides = {
        1: 84,
        2: 85,
        4: 86,
        40: 20,
        59: 42,
        62: None,
        67: None,
        72: None,
        73: None,
        74: None,
        98: 100
    }
    mapped = []
    for x in rows:
        idx = x['index']
        c = overrides.get(idx, x['retail_indices'][0] if len(x['retail_indices']) == 1 else None)
        assert c is not None or idx in overrides, idx
        mapped.append(
            SQUAD if idx == 62 else {
                67: CODE + 0xc40,
                72: CODE + 0x800,
                73: CODE + 0xa00,
                74: CODE + 0xc00
            }[idx] if c is None else rf[c]
        )
    rv = list(struct.unpack_from('<57I', retail, 0x35dbe8))
    # Match C-backed script variables by their original addresses and use the
    # corresponding retail globals. These are external variables, not script locals.
    var_indices = [
        29, 30, 7, None, None, None, None, None, None, 37, 24, 25, 26, 27, 28, 0, 1, 2, 3, 4, 5, 6,
        8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, None, 23, None, 54, 55, 56
    ]
    dv = list(struct.unpack_from('<42I', demo, 0x35df5c))
    vars = [rv[j] if j is not None else dv[i] - 0x230 for i, j in enumerate(var_indices)]
    # These globals were reordered, not shifted uniformly. Four independently
    # matching call sites bind the pickup callback to 36f49c. The modal flags
    # have six/one matching uses at 36f4a8/36f4ac respectively. Script-only
    # callback variables (no native uses in the demo) get private storage.
    for i, a in {
        5: 0x36f49c,
        36: 0x36f4ac,
        38: 0x36f4a8,
        4: CODE + 0xe0,
        6: CODE + 0xe4,
        7: CODE + 0xe8
    }.items():
        vars[i] = a
    squad = asm(
        SQUAD, (
            f"pushad;"
            f"call 0x266320;"
            f"push 3;"
            f"mov ebx,1;"
            f"mov ecx,{LOADOUT};"
            f"xor eax,eax;"
            f"xor edx,edx;"
            f"call 0x266390;"
            f"\n mov esi,1;"
            f"xor edi,edi;"
            f"loop:cmp byte ptr [edi+0x428b84],0;"
            f"je next;"
            f"\n push 3;"
            f"mov ebx,1;"
            f"mov ecx,{LOADOUT};"
            f"mov edx,[esi+0x428b80];"
            f"mov eax,esi;"
            f"sar edx,24;"
            f"call 0x266390;"
            f"inc esi;"
            f"\n next:inc edi;"
            f"cmp edi,3;"
            f"jl loop;"
            f"popad;"
            f"ret;"
        )
    )
    # Retail selects the next campaign mission when no campaign save is loaded.
    # The demos instead use the mission selected by their menu in that branch.
    # Copy the complete retail routine and redirect only the three fallback tests.
    start, end, dest = 0x2c8e78, 0x2c8fc7, CODE + 0xe00
    # Reassembly preserves internal destinations while allowing branch widening.
    lines = []
    for ins in md.disasm(bytes(retail[start:end]), start):
        op = ins.op_str
        if ins.mnemonic.startswith(('j', 'call')) and op.startswith('0x'):
            target = int(op, 16)
            op = 'requested' if ins.address in (
                0x2c8f1b, 0x2c8f20, 0x2c8f2a
            ) else f'L{target:x}' if start <= target < end else op
        lines.append(f'L{ins.address:x}: {ins.mnemonic} {op};')
    lines.append('requested:mov ecx,[0x359708];jmp L2c8f37;')
    init = asm(dest, ''.join(lines))
    assert len(init) < 0x200
    # Original demo 2c66fe ends its campaign at mission 4 before looking up a
    # successor. Retail has no such branch and would load the demo's sentinel 0.
    assert retail[0x2c6f83:0x2c6f88] == bytes.fromhex('a178094400')
    finish = asm(
        STUB, (
            "cmp dword ptr [0x359708],4;"
            "jne ordinary;"
            "\n mov dword ptr [0x35d0cc],1;"
            "jmp 0x2c6f98;"
            "\n ordinary:mov eax,[0x440978];"
            "jmp 0x2c6f88;"
        )
    )
    page = bytearray(port(0x2bf01c, 0x2bf1a0, CODE + 0xa00, retail=retail, demo=demo))
    # Native prequel information/closing pages are full-page text. The demo's
    # bottom caption at y=369 clipped the recruitment letter and longer notes.
    for offset, old, new in ((0x2bf062 - 0x2bf01c, 380, 552), (0x2bf08d - 0x2bf01c, 369, 64)):
        assert struct.unpack_from('<I', page, offset)[0] == old
        struct.pack_into('<I', page, offset, new)
    return [
        (VARS, struct.pack('<42I', *vars)), (FUNCS, struct.pack('<138I', *mapped)), (SQUAD, squad),
        (LOADOUT, bytes(demo[0x35b1c4:0x35b1c8])), (STUB, finish),
        (0x2c6f83, asm(0x2c6f83, f'jmp {STUB}')),
        (CODE + 0xc40, asm(CODE + 0xc40, f'mov dword ptr [0x35d0cc],0;call {dest};jmp 0x278d18')),
        (dest, init),
        (CODE + 0x800, port(0x2bf1a0, 0x2bf364, CODE + 0x800, retail=retail, demo=demo)),
        (CODE + 0xa00, bytes(page)),
        (CODE + 0xc00, port(0x2c2c58, 0x2c2c79, CODE + 0xc00, retail=retail, demo=demo)),
        (0x2448c7, struct.pack('<I', VARS)), (0x2448cc, struct.pack('<I', FUNCS)),
        (0x244938, struct.pack('<I', 0x3eb0003))
    ]
