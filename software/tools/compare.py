#!/usr/bin/env python3
"""compare.py - compare a built image with the reference image, function by function.

    compare.py --elf built.elf --bin built.bin --dump image.bin [--base 0x10000000] --out compare.md
               [--code-end 0xADDRESS] [--diff <symbol|0xaddr>] [--range 0xstart-0xend]

Every FUNC symbol of the ELF (size > 0) is compared at its load address (LMA; RAM functions are compared where
they are stored in flash):
  MATCH         identical bytes
  MATCH-ADDR    identical once BL immediates and literal-pool words holding flash/RAM addresses are masked
                (the code is right, something it references is linked elsewhere)
  MISMATCH      anything else (first differing offset + number of differing bytes)
  OUT-OF-IMAGE  the function lies beyond the dump's code region (--code-end) or beyond the dump
"""
import argparse
import hashlib
import os
import sys
from collections import defaultdict

from elftools.elf.constants import SH_FLAGS
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

try:
    import capstone
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
    from capstone.arm import ARM_OP_MEM, ARM_REG_PC
    _MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    _MD.detail = True
    _BL_IDS = {capstone.arm.ARM_INS_BL, capstone.arm.ARM_INS_BLX}
except ImportError:  # pragma: no cover
    _MD = None

FLASH = (0x10000000, 0x10200000)
RAM = (0x20000000, 0x20042000)


def in_addr_range(v):
    return FLASH[0] <= v < FLASH[1] or RAM[0] <= v < RAM[1]


# ---------------------------------------------------------------------------------------------- ELF

class Func:
    __slots__ = ('name', 'vma', 'size', 'lma', 'aliases', 'status', 'detail', 'built', 'dumped')

    def __init__(self, name, vma, size, lma):
        self.name, self.vma, self.size, self.lma = name, vma, size, lma
        self.aliases, self.status, self.detail = [], '', ''
        self.built = self.dumped = b''


def load_elf(path):
    with open(path, 'rb') as fh:
        elf = ELFFile(fh)
        segs = [(s['p_vaddr'], s['p_paddr'], s['p_filesz']) for s in elf.iter_segments()
                if s['p_type'] == 'PT_LOAD' and s['p_filesz'] > 0]

        def to_lma(vma):
            for v, p, n in segs:
                if v <= vma < v + n:
                    return p + (vma - v)
            return None

        # objcopy -O binary starts the file at the lowest load address of a section with contents
        lmas = [to_lma(s['sh_addr']) for s in elf.iter_sections()
                if s['sh_flags'] & SH_FLAGS.SHF_ALLOC and s['sh_type'] != 'SHT_NOBITS' and s['sh_size'] > 0]
        bin_base = min(l for l in lmas if l is not None) if any(l is not None for l in lmas) else 0

        funcs = {}
        for sec in elf.iter_sections():
            if not isinstance(sec, SymbolTableSection):
                continue
            for sym in sec.iter_symbols():
                if sym['st_info']['type'] != 'STT_FUNC' or sym['st_size'] == 0:
                    continue
                vma = sym['st_value'] & ~1
                lma = to_lma(vma)
                if lma is None:
                    continue
                key = (lma, sym['st_size'])
                if key in funcs:
                    funcs[key].aliases.append(sym.name)
                else:
                    funcs[key] = Func(sym.name, vma, sym['st_size'], lma)
    return sorted(funcs.values(), key=lambda f: f.lma), bin_base


# ---------------------------------------------------------------------------------------------- disassembly

def analyze(code, addr):
    """Disassemble Thumb code; returns (items, literal word addresses, BL offsets).
    items: list of (address, size, kind, text) with kind in {'insn', 'word', 'bad'}.
    Literal pools are recognised through pc-relative loads and skipped (re-run until stable)."""
    literals = set()
    for _ in range(6):
        items, bls, new = [], [], set()
        pos, n = 0, len(code)
        while pos < n:
            a = addr + pos
            if a in literals:
                if pos + 4 <= n:
                    items.append((a, 4, 'word', '.word 0x%08X' % int.from_bytes(code[pos:pos + 4], 'little')))
                    pos += 4
                else:
                    items.append((a, n - pos, 'bad', '.short'))
                    pos = n
                continue
            nxt = min([l for l in literals if l > a] + [addr + n])
            chunk = code[pos:nxt - addr]
            consumed = 0
            for ins in _MD.disasm(chunk, a):
                items.append((ins.address, ins.size, 'insn', '%s %s' % (ins.mnemonic, ins.op_str)))
                consumed += ins.size
                if ins.id in _BL_IDS:
                    bls.append(ins.address - addr)
                for op in ins.operands:
                    if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC and op.mem.index == 0:
                        lit = ((ins.address + 4) & ~3) + op.mem.disp
                        if addr <= lit < addr + n and lit not in literals:
                            new.add(lit)
            pos += consumed
            if consumed < len(chunk):
                items.append((addr + pos, 2, 'bad', '.short 0x%04X' % int.from_bytes(code[pos:pos + 2], 'little')))
                pos += 2
        if not new:
            return items, literals, bls
        literals |= new
    return items, literals, bls


def classify(f):
    if f.built == f.dumped:
        return 'MATCH', ''
    diffs = [i for i in range(len(f.built)) if f.built[i] != f.dumped[i]]
    first = diffs[0]
    detail = 'first diff at +0x%X, %d bytes differ' % (first, len(diffs))
    if _MD is None:
        return 'MISMATCH', detail
    _, literals, bls = analyze(f.built, f.vma)
    mask = bytearray(f.size)
    for off in bls:
        mask[off:off + 4] = b'\x01' * 4
    words = 0
    for lit in literals:
        off = lit - f.vma
        if off + 4 > f.size:
            continue
        b = int.from_bytes(f.built[off:off + 4], 'little')
        d = int.from_bytes(f.dumped[off:off + 4], 'little')
        if b != d and in_addr_range(b) and in_addr_range(d):
            mask[off:off + 4] = b'\x01' * 4
            words += 1
    if all(mask[i] for i in diffs):
        refs = sum(1 for off in bls if f.built[off:off + 4] != f.dumped[off:off + 4])
        return 'MATCH-ADDR', '%d BL target(s), %d address word(s) differ' % (refs, words)
    outside = sum(1 for i in diffs if not mask[i])
    return 'MISMATCH', detail + (' (%d outside address refs)' % outside if outside != len(diffs) else '')


# ---------------------------------------------------------------------------------------------- reporting

def region_stats(built, bin_base, dump, base, lo, hi):
    """Compare [lo, hi) (addresses) between built and dump; returns (compared, differing, first_mismatch)."""
    lo = max(lo, bin_base, base)
    hi = min(hi, bin_base + len(built), base + len(dump))
    if hi <= lo:
        return 0, 0, None
    b = built[lo - bin_base:hi - bin_base]
    d = dump[lo - base:hi - base]
    if b == d:
        return hi - lo, 0, None
    first = next(i for i in range(len(b)) if b[i] != d[i])
    ndiff = sum(1 for i in range(len(b)) if b[i] != d[i])
    return hi - lo, ndiff, lo + first


def fmt_diff(f, base, dump_bytes):
    out = ['## diff %s  vma 0x%08X  lma 0x%08X  size %d  %s %s' % (
        f.name, f.vma, f.lma, f.size, f.status, f.detail), '']
    bi, _, _ = analyze(f.built, f.vma)
    di, _, _ = analyze(dump_bytes, f.vma)
    bmap = {a: (s, k, t) for a, s, k, t in bi}
    dmap = {a: (s, k, t) for a, s, k, t in di}
    w = 46
    out.append('%-10s %-*s | %s' % ('addr', w, 'built', 'dump'))
    for a in sorted(set(bmap) | set(dmap)):
        def cell(m, src):
            if a not in m:
                return ' ' * w, None
            s, k, t = m[a]
            raw = src[a - f.vma:a - f.vma + s]
            return ('%-9s %s' % (raw.hex(), t))[:w].ljust(w), raw
        bc, braw = cell(bmap, f.built)
        dc, draw = cell(dmap, dump_bytes)
        mark = ' ' if braw == draw and bmap.get(a, (0, 0, ''))[2] == dmap.get(a, (0, 0, ''))[2] else '!'
        out.append('%s0x%08X %s | %s' % (mark, a, bc, dc.rstrip()))
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--elf', required=True)
    ap.add_argument('--bin', required=True)
    ap.add_argument('--dump', required=True)
    ap.add_argument('--base', type=lambda x: int(x, 0), default=0x10000000)
    ap.add_argument('--code-end', type=lambda x: int(x, 0), default=None,
                    help='end of the code region in the dump (strings/data follow)')
    ap.add_argument('--out', help='markdown report')
    ap.add_argument('--diff', help='symbol or 0xaddr: side-by-side disassembly built vs dump')
    ap.add_argument('--range', help='0xstart-0xend: compare an arbitrary address range')
    args = ap.parse_args()

    with open(args.bin, 'rb') as fh:
        built = fh.read()
    with open(args.dump, 'rb') as fh:
        dump = fh.read()
    funcs, bin_base = load_elf(args.elf)
    base = args.base
    built_end = bin_base + len(built)
    dump_end = base + len(dump)
    if args.code_end is None:
        args.code_end = dump_end

    for f in funcs:
        if f.lma + f.size > built_end or f.lma < bin_base:
            f.status, f.detail = 'OUT-OF-IMAGE', 'not in the built binary (LMA 0x%08X)' % f.lma
            continue
        f.built = built[f.lma - bin_base:f.lma - bin_base + f.size]
        if f.lma + f.size > min(args.code_end, dump_end) or f.lma < base:
            f.status = 'OUT-OF-IMAGE'
            f.detail = 'beyond the dump code end 0x%08X' % min(args.code_end, dump_end)
            continue
        f.dumped = dump[f.lma - base:f.lma - base + f.size]
        f.status, f.detail = classify(f)
        if f.vma != f.lma:
            f.detail = ('RAM function, vma 0x%08X; ' % f.vma) + f.detail

    counts, nbytes = defaultdict(int), defaultdict(int)
    for f in funcs:
        counts[f.status] += 1
        nbytes[f.status] += f.size

    regions = [
        ('boot2', base, base + 0x100),
        ('code', base + 0x100, args.code_end),
        ('data', args.code_end, min(built_end, dump_end)),
    ]
    reg_lines = []
    for name, lo, hi in regions:
        cmp_n, ndiff, first = region_stats(built, bin_base, dump, base, lo, hi)
        reg_lines.append((name, lo, max(lo, hi), cmp_n, ndiff, first))
    rest = dump[built_end - base:] if built_end < dump_end else b''
    rest_nonff = sum(1 for _ in rest.translate(None, b'\xff')) if rest else 0
    first_nonff = None
    if rest_nonff:
        i = next(i for i in range(len(rest)) if rest[i] != 0xFF)
        first_nonff = built_end + i

    sha_built = hashlib.sha256(built).hexdigest()
    sha_dump = hashlib.sha256(dump).hexdigest()
    padded = built if bin_base != base else built + b'\xff' * max(0, len(dump) - len(built))
    sha_padded = hashlib.sha256(padded[:len(dump)]).hexdigest() if bin_base == base else None
    sha_equal = sha_padded == sha_dump

    lines = []
    lines.append('compare: %s (%d bytes at 0x%08X) vs %s (%d bytes at 0x%08X)' % (
        os.path.basename(args.bin), len(built), bin_base, os.path.basename(args.dump), len(dump), base))
    lines.append('functions %d: MATCH %d (%d bytes), MATCH-ADDR %d (%d), MISMATCH %d (%d), OUT-OF-IMAGE %d (%d)' % (
        len(funcs), counts['MATCH'], nbytes['MATCH'], counts['MATCH-ADDR'], nbytes['MATCH-ADDR'],
        counts['MISMATCH'], nbytes['MISMATCH'], counts['OUT-OF-IMAGE'], nbytes['OUT-OF-IMAGE']))
    for name, lo, hi, cmp_n, ndiff, first in reg_lines:
        lines.append('%-5s 0x%08X-0x%08X: %d bytes compared, %d differ%s' % (
            name, lo, hi, cmp_n, ndiff, (', first mismatch at 0x%08X' % first) if first is not None else ''))
    lines.append('rest  0x%08X-0x%08X: %d non-0xFF bytes in the dump beyond the built image%s' % (
        built_end, dump_end, rest_nonff, (', first at 0x%08X' % first_nonff) if first_nonff else ''))
    lines.append('whole image SHA-256 equal: %s (built padded with 0xFF %s, dump %s)' % (
        'YES' if sha_equal else 'no', (sha_padded or 'n/a')[:16], sha_dump[:16]))

    if args.out:
        md = ['# compare — %s vs %s' % (args.elf, args.dump), '']
        md.append('- built: `%s` %d bytes, SHA-256 `%s`, starts at 0x%08X' % (args.bin, len(built), sha_built, bin_base))
        md.append('- dump: `%s` %d bytes, SHA-256 `%s`, base 0x%08X' % (args.dump, len(dump), sha_dump, base))
        md.append('- whole image equal (built padded with 0xFF to the dump size): **%s**%s' % (
            'yes' if sha_equal else 'no', '' if sha_padded else ' (built image does not start at base)'))
        md.append('')
        md.append('## Summary')
        md.append('')
        md.append('| status | functions | bytes |')
        md.append('|---|---:|---:|')
        for st in ('MATCH', 'MATCH-ADDR', 'MISMATCH', 'OUT-OF-IMAGE'):
            md.append('| %s | %d | %d |' % (st, counts[st], nbytes[st]))
        md.append('| total | %d | %d |' % (len(funcs), sum(nbytes.values())))
        md.append('')
        md.append('| region | range | compared | differing | first mismatch |')
        md.append('|---|---|---:|---:|---|')
        for name, lo, hi, cmp_n, ndiff, first in reg_lines:
            md.append('| %s | 0x%08X–0x%08X | %d | %d | %s |' % (
                name, lo, hi, cmp_n, ndiff, ('0x%08X' % first) if first is not None else '—'))
        md.append('| rest (dump beyond built) | 0x%08X–0x%08X | %d | %d non-0xFF | %s |' % (
            built_end, dump_end, len(rest), rest_nonff, ('0x%08X' % first_nonff) if first_nonff else '—'))
        md.append('')
        md.append('## Functions (by load address)')
        md.append('')
        md.append('| name | addr | size | status | detail |')
        md.append('|---|---|---:|---|---|')
        for f in funcs:
            d = f.detail
            if f.aliases:
                d = (d + '; ' if d else '') + 'alias ' + ', '.join('`%s`' % a for a in f.aliases)
            md.append('| `%s` | 0x%08X | %d | %s | %s |' % (f.name, f.lma, f.size, f.status, d))
        md.append('')
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(md))
        lines.append('report: %s' % args.out)

    print('\n'.join(lines))

    if args.range:
        a, b = args.range.split('-')
        lo, hi = int(a, 0), int(b, 0)
        cmp_n, ndiff, first = region_stats(built, bin_base, dump, base, lo, hi)
        print('range 0x%08X-0x%08X: %s' % (lo, hi, 'equal (%d bytes)' % cmp_n if not ndiff and cmp_n else (
            'empty (outside both images)' if not cmp_n else
            '%d of %d bytes differ, first at 0x%08X' % (ndiff, cmp_n, first))))

    if args.diff:
        sel = None
        for f in funcs:
            if f.name == args.diff or args.diff in f.aliases:
                sel = f
                break
        if sel is None and args.diff.lower().startswith('0x'):
            a = int(args.diff, 16) & ~1
            for f in funcs:
                if f.lma <= a < f.lma + f.size or f.vma <= a < f.vma + f.size:
                    sel = f
                    break
        if sel is None:
            print('diff: function %s not found' % args.diff)
            return 2
        if _MD is None:
            print('diff: capstone not installed')
            return 2
        if not sel.built:
            sel.built = built[sel.lma - bin_base:sel.lma - bin_base + sel.size]
        dumped = dump[sel.lma - base:sel.lma - base + sel.size] if base <= sel.lma < dump_end else b''
        print()
        print(fmt_diff(sel, base, dumped))
    return 0


if __name__ == '__main__':
    sys.exit(main())
