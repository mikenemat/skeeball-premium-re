#!/usr/bin/env python3
"""libmatch.py - find the functions of ELF relocatable objects / ar archives byte for byte in a flat image.

Every FUNC symbol of an executable section is turned into a pattern: the section bytes of the function with the
bytes covered by its relocations masked out (the only bytes the linker changes). Each pattern is searched in the
dump; a single hit at a Thumb-aligned offset is a confirmed library function at that address.

    libmatch.py --objdir <dir|file.a|file.o> [--objdir ...] --dump image.bin [--base 0x10000000]
                --out report.tsv [--md summary.md] [--min-unmasked 16] [--region 0xstart-0xend]
"""
import argparse
import hashlib
import io
import os
import re
import sys
from collections import defaultdict

from elftools.common.exceptions import ELFError
from elftools.elf.constants import SH_FLAGS
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from elftools.elf.sections import SymbolTableSection

# Bytes rewritten by the linker for each ARM relocation type (ELF for the Arm Architecture, table 4-9 / 4-10).
RELOC_WIDTH = {
    0: 0,     # R_ARM_NONE
    40: 0,    # R_ARM_V4BX (marker)
    5: 2,     # R_ARM_ABS16
    8: 1,     # R_ARM_ABS8
    7: 2,     # R_ARM_THM_ABS5
    11: 2,    # R_ARM_THM_PC8
    52: 2,    # R_ARM_THM_JUMP6
    102: 2,   # R_ARM_THM_JUMP11
    103: 2,   # R_ARM_THM_JUMP8
}
for _t in (1, 2, 3, 4, 6, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
           33, 34, 35, 36, 37, 38, 39, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 53, 54, 55, 56, 57, 58, 59, 60,
           61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86,
           87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 104, 105, 106, 107, 108, 109, 110, 111,
           112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131):
    RELOC_WIDTH.setdefault(_t, 4)

ARCHIVE_LIBS = {
    'libc': 'newlib', 'libg': 'newlib', 'libm': 'newlib-libm', 'libc_nano': 'newlib-nano', 'libg_nano': 'newlib-nano',
    'libgcc': 'libgcc', 'libstdc++': 'libstdc++', 'libsupc++': 'libsupc++', 'libnosys': 'libnosys',
    'librdimon': 'librdimon', 'libgloss': 'libgloss',
}


class Pattern:
    __slots__ = ('symbol', 'obj', 'lib', 'size', 'data', 'mask', 'align', 'secoff', 'runs', 'unmasked', 'key',
                 'status', 'hits', 'local', 'aliases')

    def __init__(self, symbol, obj, lib, data, mask, align, secoff, local):
        self.symbol, self.obj, self.lib, self.aliases = symbol, obj, lib, []
        self.data, self.mask, self.size = bytes(data), bytes(mask), len(data)
        self.align, self.secoff, self.local = max(2, align), secoff, local
        self.runs = []
        i = 0
        while i < self.size:
            if mask[i]:
                i += 1
                continue
            j = i
            while j < self.size and not mask[j]:
                j += 1
            self.runs.append((i, self.data[i:j]))
            i = j
        self.unmasked = sum(len(r) for _, r in self.runs)
        self.key = (self.data, self.mask)
        self.status, self.hits = None, []


# ---------------------------------------------------------------------------------------------- input collection

def iter_archive(data):
    """Yield (member name, bytes) for a GNU/SysV 'ar' archive."""
    if not data.startswith(b'!<arch>\n'):
        raise ValueError('not an ar archive')
    pos, longnames = 8, b''
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        if hdr[58:60] != b'`\n':
            raise ValueError('bad ar member header at %d' % pos)
        name = hdr[0:16].decode('latin1').rstrip()
        size = int(hdr[48:58])
        body = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
        if name in ('/', '/SYM64/'):
            continue
        if name == '//':
            longnames = body
            continue
        if name.startswith('/'):
            off = int(name[1:])
            end = longnames.index(b'\n', off)
            name = longnames[off:end].decode('latin1')
        if name.endswith('/'):
            name = name[:-1]
        yield name, body


def library_name(path):
    """Derive a library name from an object path (CMake tree of a Pico SDK project, or an archive name)."""
    p = path.replace('\\', '/')
    m = re.search(r'([^/]+)\.a(?:\(|$)', p)
    if m:
        return ARCHIVE_LIBS.get(m.group(1), m.group(1))
    if ('FreeRTOS-Kernel' in p or 'freertos' in p.lower() or '/frk/' in p
            or re.search(r'/(tasks|queue|list|timers|event_groups|stream_buffer|croutine|heap_[1-5])\.c\.obj?$', p)
            or '/portable/ThirdParty/GCC/RP2040/' in p):
        return 'freertos'
    if '/tinyusb/' in p or '/tusb-rev/' in p or '/tusb-' in p:
        return 'tinyusb'
    m = re.search(r'pico[-_]sdk/src/(?:rp2_common|common|rp2040|host|boards)/([^/]+)/', p)
    if m:
        return m.group(1)
    m = re.search(r'pico[-_]sdk/src/([^/]+)/', p)
    if m:
        return 'pico-sdk:' + m.group(1)
    if 'pico-sdk' in p or 'pico_sdk' in p:
        return 'pico-sdk'
    return 'app'


def patterns_from_elf(blob, objname, warn):
    try:
        elf = ELFFile(io.BytesIO(blob))
    except ELFError:
        return
    if elf['e_type'] != 'ET_REL' or elf['e_machine'] != 'EM_ARM':
        return
    relocs = defaultdict(list)
    for sec in elf.iter_sections():
        if isinstance(sec, RelocationSection):
            tgt = sec['sh_info']
            for r in sec.iter_relocations():
                t = r['r_info_type']
                w = RELOC_WIDTH.get(t)
                if w is None:
                    warn('%s: unknown reloc type %d in %s, masking 4 bytes' % (objname, t, sec.name))
                    w = 4
                relocs[tgt].append((r['r_offset'], w))
    lib = library_name(objname)
    secdata, seen = {}, {}
    for sec in elf.iter_sections():
        if not isinstance(sec, SymbolTableSection):
            continue
        for sym in sec.iter_symbols():
            if sym['st_info']['type'] != 'STT_FUNC' or sym['st_size'] == 0:
                continue
            shndx = sym['st_shndx']
            if not isinstance(shndx, int):
                continue
            tsec = elf.get_section(shndx)
            if tsec['sh_type'] != 'SHT_PROGBITS' or not (tsec['sh_flags'] & SH_FLAGS.SHF_EXECINSTR):
                continue
            if shndx not in secdata:
                secdata[shndx] = tsec.data()
            start = sym['st_value'] & ~1
            size = sym['st_size']
            if (shndx, start, size) in seen:  # alias (e.g. C1/C2 constructors): one code copy, one pattern
                seen[(shndx, start, size)].aliases.append(sym.name)
                continue
            data = secdata[shndx][start:start + size]
            if len(data) != size:
                continue
            mask = bytearray(size)
            for off, w in relocs.get(shndx, ()):
                lo, hi = max(off, start), min(off + w, start + size)
                if lo < hi:
                    mask[lo - start:hi - start] = b'\x01' * (hi - lo)
            p = Pattern(sym.name, objname, lib, data, mask, tsec['sh_addralign'], start,
                        sym['st_info']['bind'] == 'STB_LOCAL')
            seen[(shndx, start, size)] = p
            yield p


def collect_patterns(inputs, warn):
    pats, files = [], []
    for root in inputs:
        if os.path.isdir(root):
            for d, _, fs in os.walk(root):
                for f in sorted(fs):
                    if f.endswith(('.o', '.obj', '.a')):
                        files.append((root, os.path.join(d, f)))
        elif os.path.isfile(root):
            files.append((os.path.dirname(root), root))
        else:
            warn('input not found: %s' % root)
    nobj = narch = 0
    for root, path in files:
        rel = os.path.relpath(path, root).replace('\\', '/') if root else path
        with open(path, 'rb') as fh:
            blob = fh.read()
        if blob.startswith(b'!<arch>\n'):
            narch += 1
            for member, body in iter_archive(blob):
                pats.extend(patterns_from_elf(body, '%s(%s)' % (rel, member), warn))
        elif blob.startswith(b'\x7fELF'):
            nobj += 1
            pats.extend(patterns_from_elf(blob, rel, warn))
    return pats, nobj, narch


# ---------------------------------------------------------------------------------------------- search

def search(dump, pat, base, lo, hi, max_hits):
    anchor_off, anchor = max(pat.runs, key=lambda r: len(r[1]))
    hits, pos = [], lo
    end = hi
    while True:
        i = dump.find(anchor, pos, end)
        if i < 0:
            break
        pos = i + 1
        s = i - anchor_off
        if s < lo or s + pat.size > hi:
            continue
        if (base + s - pat.secoff) % pat.align:
            continue
        if all(dump[s + o:s + o + len(b)] == b for o, b in pat.runs):
            hits.append(s)
            if len(hits) > max_hits:
                break
    return hits


def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


# ---------------------------------------------------------------------------------------------- main

def parse_region(s, base, n):
    if not s:
        return 0, n
    a, b = s.split('-')
    lo, hi = int(a, 0) - base, int(b, 0) - base
    return max(0, lo), min(n, hi)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--objdir', action='append', required=True, help='build dir, archive or object (repeatable)')
    ap.add_argument('--dump', required=True)
    ap.add_argument('--base', type=lambda x: int(x, 0), default=0x10000000)
    ap.add_argument('--out', required=True, help='TSV report')
    ap.add_argument('--md', help='markdown summary')
    ap.add_argument('--min-unmasked', type=int, default=16)
    ap.add_argument('--region', help='0xstart-0xend (addresses); default: the whole dump')
    ap.add_argument('--max-hits', type=int, default=64)
    args = ap.parse_args()

    warnings = []
    warn = lambda m: warnings.append(m)
    with open(args.dump, 'rb') as fh:
        dump = fh.read()
    lo, hi = parse_region(args.region, args.base, len(dump))
    pats, nobj, narch = collect_patterns(args.objdir, warn)
    groups = defaultdict(list)
    for p in pats:
        groups[p.key].append(p)

    for p in pats:
        if p.unmasked < args.min_unmasked:
            p.status = 'skipped-small'
            continue
        p.hits = search(dump, p, args.base, lo, hi, args.max_hits)
        p.status = 'unique' if len(p.hits) == 1 else ('none' if not p.hits else 'multi')

    def explained(p):
        # N byte-identical patterns (after masking) with exactly N copies in the image
        return p.status == 'multi' and len(p.hits) == len(groups[p.key])

    covered = []
    for p in pats:
        if p.status == 'unique':
            covered.append((p.hits[0], p.hits[0] + p.size))
        elif explained(p):
            covered.extend((h, h + p.size) for h in p.hits)
    covered = merge(covered)

    pats.sort(key=lambda p: (p.obj, p.secoff, p.symbol))
    with open(args.out, 'w', newline='') as fh:
        fh.write('symbol\tobject\tsize\tunmasked_bytes\tstatus\taddresses\taliases\n')
        for p in pats:
            addrs = ','.join('0x%08X' % (args.base + h) for h in p.hits)
            fh.write('%s\t%s\t%d\t%d\t%s\t%s\t%s\n' % (p.symbol, p.obj, p.size, p.unmasked, p.status, addrs,
                                                      ','.join(p.aliases)))

    counts = defaultdict(int)
    for p in pats:
        counts[p.status] += 1
    uniq_bytes = sum(p.size for p in pats if p.status == 'unique')
    cov_bytes = sum(e - s for s, e in covered)
    region_cov = sum(max(0, min(e, hi) - max(s, lo)) for s, e in covered)
    summary = ('objects %d, archives %d, functions %d: unique %d (%d bytes), multi %d, none %d, skipped-small %d; '
               'region 0x%08X-0x%08X covered %d/%d bytes (%.1f%%)' % (
                   nobj, narch, len(pats), counts['unique'], uniq_bytes, counts['multi'], counts['none'],
                   counts['skipped-small'], args.base + lo, args.base + hi, region_cov, hi - lo,
                   100.0 * region_cov / max(1, hi - lo)))
    print(summary)
    for w in warnings[:20]:
        print('warning:', w, file=sys.stderr)

    if args.md:
        write_md(args, dump, pats, groups, covered, lo, hi, nobj, narch, counts, uniq_bytes, cov_bytes, region_cov,
                 warnings, explained)
        print('summary:', args.md)
    print('report:', args.out)


def write_md(args, dump, pats, groups, covered, lo, hi, nobj, narch, counts, uniq_bytes, cov_bytes, region_cov,
             warnings, explained):
    base = args.base
    sha = hashlib.sha256(dump).hexdigest()
    L = []
    L.append('# libmatch — %s vs %s' % (', '.join(args.objdir), os.path.basename(args.dump)))
    L.append('')
    L.append('- dump: `%s` (%d bytes, SHA-256 `%s`), base 0x%08X' % (args.dump, len(dump), sha, base))
    L.append('- inputs: %d objects, %d archives, %d function patterns; `--min-unmasked %d`' % (
        nobj, narch, len(pats), args.min_unmasked))
    L.append('- region: 0x%08X–0x%08X (%d bytes)' % (base + lo, base + hi, hi - lo))
    L.append('')
    L.append('## Totals')
    L.append('')
    L.append('| status | functions | bytes |')
    L.append('|---|---:|---:|')
    for st in ('unique', 'multi', 'none', 'skipped-small'):
        L.append('| %s | %d | %d |' % (st, counts[st], sum(p.size for p in pats if p.status == st)))
    multi_dup = sum(1 for p in pats if explained(p))
    L.append('')
    L.append('- covered bytes (union of unique hits + multi hits explained by duplicate patterns): %d; '
             'in region: %d / %d (%.2f%%)' % (cov_bytes, region_cov, hi - lo, 100.0 * region_cov / max(1, hi - lo)))
    L.append('- multi matches explained by N identical patterns with N hits (counted as covered): %d' % multi_dup)
    ambiguous = merge((h, h + p.size) for p in pats if p.status == 'multi' and not explained(p) for h in p.hits)
    amb_only = 0
    for s, e in ambiguous:
        s, e = max(s, lo), min(e, hi)
        for cs, ce in covered:
            if cs < e and ce > s:
                s2, e2 = max(s, cs), min(e, ce)
                amb_only -= e2 - s2
        amb_only += max(0, e - s)
    L.append('- bytes in the region hit only by ambiguous multi patterns (not counted, candidates): %d' % amb_only)
    L.append('- unique bytes (sum over unique functions, duplicates counted twice): %d' % uniq_bytes)
    L.append('')

    L.append('## Per library')
    L.append('')
    L.append('| library | functions | unique | multi | none | skipped-small | unique bytes |')
    L.append('|---|---:|---:|---:|---:|---:|---:|')
    bylib = defaultdict(list)
    for p in pats:
        bylib[p.lib].append(p)
    for lib in sorted(bylib, key=lambda k: -sum(p.size for p in bylib[k] if p.status == 'unique')):
        ps = bylib[lib]
        c = defaultdict(int)
        for p in ps:
            c[p.status] += 1
        L.append('| %s | %d | %d | %d | %d | %d | %d |' % (
            lib, len(ps), c['unique'], c['multi'], c['none'], c['skipped-small'],
            sum(p.size for p in ps if p.status == 'unique')))
    L.append('')

    gaps = []
    cur = lo
    for s, e in covered:
        if e <= lo or s >= hi:
            continue
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < hi:
        gaps.append((cur, hi))
    small = [g for g in gaps if g[1] - g[0] < 8]
    big = sorted((g for g in gaps if g[1] - g[0] >= 8), key=lambda g: -(g[1] - g[0]))
    L.append('## Unmatched gaps in the region (application code, data, padding)')
    L.append('')
    L.append('- gaps ≥ 8 bytes: %d (%d bytes); gaps < 8 bytes (alignment padding): %d (%d bytes)' % (
        len(big), sum(e - s for s, e in big), len(small), sum(e - s for s, e in small)))
    L.append('')
    L.append('| start | end | size |')
    L.append('|---|---|---:|')
    for s, e in big:
        L.append('| 0x%08X | 0x%08X | %d |' % (base + s, base + e, e - s))
    L.append('')

    L.append('## Matched functions by address')
    L.append('')
    L.append('(byte-identical patterns at the same address are collapsed into one row)')
    L.append('')
    L.append('| address | size | symbol | library | object | identical patterns |')
    L.append('|---|---:|---|---|---|---|')
    rows = defaultdict(list)
    for p in pats:
        if p.status == 'unique' or explained(p):
            for h in p.hits:
                rows[(h, p.key)].append(p)
    for (h, _), ps in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[1][0].symbol)):
        p = ps[0]
        others = ', '.join('`%s`' % q.symbol for q in ps[1:4]) + (' +%d more' % (len(ps) - 4) if len(ps) > 4 else '')
        L.append('| 0x%08X | %d | `%s` | %s | %s | %s |' % (base + h, p.size, p.symbol, p.lib, p.obj, others))
    L.append('')

    multis = [p for p in pats if p.status == 'multi' and not explained(p)]
    if multis:
        L.append('## Ambiguous (multi) matches not explained by duplicates')
        L.append('')
        L.append('| symbol | object | size | unmasked | hits |')
        L.append('|---|---|---:|---:|---|')
        for p in sorted(multis, key=lambda p: -p.unmasked):
            L.append('| `%s` | %s | %d | %d | %s |' % (
                p.symbol, p.obj, p.size, p.unmasked,
                ', '.join('0x%08X' % (base + h) for h in p.hits[:8]) + (' …' if len(p.hits) > 8 else '')))
        L.append('')
    if warnings:
        L.append('## Warnings')
        L.append('')
        L.extend('- %s' % w for w in warnings[:50])
        L.append('')
    with open(args.md, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L))


if __name__ == '__main__':
    main()
