#!/usr/bin/env python3
"""Fixture tests for libmatch.py / compare.py / extract.py. Needs arm-none-eabi-gcc on PATH, pyelftools, capstone.

    run_tests.py [workdir]
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
PY = sys.executable
CC = os.environ.get('CC', 'arm-none-eabi-gcc')
CFLAGS = ['-mcpu=cortex-m0plus', '-mthumb', '-O2', '-ffunction-sections', '-fdata-sections', '-c']
LDFLAGS = ['-nostdlib', '-Wl,--gc-sections', '-Wl,--build-id=none', '-Wl,-T,' + os.path.join(HERE, 'fixture.ld')]
BASE = 0x10000000
failures = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        failures.append(msg)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(' '.join(cmd))
        print(r.stdout, r.stderr)
        raise SystemExit('command failed')
    return r.stdout


def tool(name, *a):
    return run([PY, os.path.join(TOOLS, name)] + list(a))


def elf_funcs(path):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(path, 'rb') as fh:
        elf = ELFFile(fh)
        segs = [(s['p_vaddr'], s['p_paddr'], s['p_filesz']) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        for sym in elf.get_section_by_name('.symtab').iter_symbols():
            if sym['st_info']['type'] == 'STT_FUNC' and sym['st_size']:
                vma = sym['st_value'] & ~1
                lma = next(p + vma - v for v, p, n in segs if v <= vma < v + n)
                out[sym.name] = (lma, sym['st_size'])
    return out


def read_tsv(path):
    with open(path, newline='') as fh:
        return {r['symbol']: r for r in csv.DictReader(fh, delimiter='\t')}


def read_compare(path):
    rows = {}
    for line in open(path, encoding='utf-8'):
        m = re.match(r'^\| `([^`]+)` \| (0x[0-9A-F]+) \| (\d+) \| ([A-Z-]+) \| (.*) \|$', line)
        if m:
            rows[m.group(1)] = (int(m.group(2), 16), int(m.group(3)), m.group(4), m.group(5))
    return rows


def build(wd, tag, objs, extra_ld=()):
    elf = os.path.join(wd, tag + '.elf')
    binf = os.path.join(wd, tag + '.bin')
    run([CC, '-mcpu=cortex-m0plus', '-mthumb'] + LDFLAGS + list(extra_ld) + ['-o', elf] + objs)
    run([CC.replace('gcc', 'objcopy'), '-O', 'binary', elf, binf])
    return elf, binf


def main():
    wd = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='tooling-tests-')
    os.makedirs(wd, exist_ok=True)
    objdir = os.path.join(wd, 'objs')
    mutdir = os.path.join(wd, 'objs_mut')
    for d in (objdir, mutdir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    print('workdir', wd)

    # --- fixtures -------------------------------------------------------------------------------------------
    for src in ('fix_a', 'fix_b', 'fix_c', 'fix_pad'):
        run([CC] + CFLAGS + ['-o', os.path.join(objdir, src + '.o'), os.path.join(HERE, src + '.c')])
        run([CC] + CFLAGS + ['-DMUTATE'] + ['-o', os.path.join(mutdir, src + '.o'), os.path.join(HERE, src + '.c')])
    objs = [os.path.join(objdir, s + '.o') for s in ('fix_a', 'fix_b', 'fix_c')]
    ref_elf, ref_bin = build(wd, 'ref', objs)
    ref = elf_funcs(ref_elf)
    with open(ref_bin, 'rb') as fh:
        ref_bytes = fh.read()
    dump = os.path.join(wd, 'dump.bin')
    with open(dump, 'wb') as fh:
        body = b'\xff' * 0x100 + ref_bytes
        fh.write(body + b'\xff' * (0x10000 - len(body)))
    archive = os.path.join(wd, 'fix.a')
    run([CC.replace('gcc', 'ar'), 'rcs', archive] + objs)
    print('reference functions:', ', '.join('%s@0x%X' % (k, v[0]) for k, v in sorted(ref.items(), key=lambda kv: kv[1])))

    # --- libmatch: objects --------------------------------------------------------------------------------------
    print('libmatch objects')
    tsv, md = os.path.join(wd, 'm_obj.tsv'), os.path.join(wd, 'm_obj.md')
    out = tool('libmatch.py', '--objdir', objdir, '--dump', dump, '--base', hex(BASE), '--out', tsv, '--md', md)
    print('  ' + out.splitlines()[0])
    rows = read_tsv(tsv)
    for name, (lma, size) in ref.items():
        if name.endswith('_veneer'):
            continue  # linker-generated long-branch veneer, not in any object
        r = rows.get(name)
        check(r is not None, 'pattern for %s' % name)
        if r is None:
            continue
        if name == 'a_tiny':
            check(r['status'] == 'skipped-small', '%s skipped-small (unmasked %s)' % (name, r['unmasked_bytes']))
        elif name in ('b_dup', 'c_dup'):
            check(r['status'] == 'multi' and r['addresses'] == '0x%08X,0x%08X' % (ref['b_dup'][0], ref['c_dup'][0]),
                  '%s multi at both copies (%s)' % (name, r['addresses']))
        else:
            check(r['status'] == 'unique' and r['addresses'] == '0x%08X' % lma,
                  '%s unique at 0x%08X (got %s %s)' % (name, lma, r['status'], r['addresses']))
        check(int(r['size']) == size, '%s size %d' % (name, size))
    check('pad_fn' in rows and rows['pad_fn']['status'] == 'none', 'pad_fn none (not linked)')
    mdtxt = open(md, encoding='utf-8').read()
    check('## Unmatched gaps' in mdtxt and '## Per library' in mdtxt and '| app |' in mdtxt, 'summary md sections')
    check(rows['c_ramfn']['status'] == 'unique' and rows['c_ramfn']['addresses'] == '0x%08X' % ref['c_ramfn'][0]
          and ref['c_ramfn'][0] < 0x20000000, 'RAM function matched at its load address')

    # --- libmatch: archive -------------------------------------------------------------------------------------
    print('libmatch archive')
    tsv_a = os.path.join(wd, 'm_ar.tsv')
    tool('libmatch.py', '--objdir', archive, '--dump', dump, '--out', tsv_a)
    rows_a = read_tsv(tsv_a)
    check(all(rows_a[k]['status'] == rows[k]['status'] and rows_a[k]['addresses'] == rows[k]['addresses']
              for k in rows if k != 'pad_fn') and all(v['object'].startswith('fix.a(') for v in rows_a.values()),
          'archive members give the same results as the objects')

    # --- libmatch: region + mutated object ---------------------------------------------------------------------
    print('libmatch mutated / region')
    tsv_m = os.path.join(wd, 'm_mut.tsv')
    tool('libmatch.py', '--objdir', mutdir, '--dump', dump, '--out', tsv_m,
         '--region', '0x%08X-0x%08X' % (BASE + 0x100, BASE + 0x100 + len(ref_bytes)))
    rows_m = read_tsv(tsv_m)
    check(rows_m['b_const_fn']['status'] == 'none', 'mutated b_const_fn none')
    check(rows_m['a_caller']['status'] == 'unique' and rows_m['b_add']['status'] == 'unique',
          'untouched functions still unique in --region')

    # --- compare: identical ---------------------------------------------------------------------------------------
    print('compare identical')
    cmp_md = os.path.join(wd, 'cmp_ref.md')
    out = tool('compare.py', '--elf', ref_elf, '--bin', ref_bin, '--dump', dump, '--out', cmp_md,
               '--code-end', hex(BASE + 0x10000))
    cr = read_compare(cmp_md)
    check(len(cr) == len(ref), 'all %d functions listed (%d)' % (len(ref), len(cr)))
    check(all(v[2] == 'MATCH' for v in cr.values()), 'all MATCH')
    check(cr['c_ramfn'][0] == ref['c_ramfn'][0] and 'RAM function' in cr['c_ramfn'][3],
          'RAM function compared at its LMA 0x%08X' % ref['c_ramfn'][0])
    check('0 differ' in out and 'whole image SHA-256 equal: no' in out, 'regions equal, whole-file not (bin starts at 0x10000100)')

    out = tool('compare.py', '--elf', ref_elf, '--bin', ref_bin, '--dump', dump, '--code-end', hex(BASE + 0x10000),
               '--range', '0x%08X-0x%08X' % (BASE + 0x100, BASE + 0x100 + len(ref_bytes)))
    check(re.search(r'range .*: equal \(%d bytes\)' % len(ref_bytes), out) is not None, '--range equal')

    # --- compare: mutated constant → MISMATCH --------------------------------------------------------------------
    print('compare mutated')
    mut_objs = [os.path.join(mutdir, s + '.o') for s in ('fix_a', 'fix_b', 'fix_c')]
    mut_elf, mut_bin = build(wd, 'mut', mut_objs)
    cmp_mut = os.path.join(wd, 'cmp_mut.md')
    out = tool('compare.py', '--elf', mut_elf, '--bin', mut_bin, '--dump', dump, '--out', cmp_mut,
               '--code-end', hex(BASE + 0x10000), '--diff', 'b_const_fn',
               '--range', '0x%08X-0x%08X' % (BASE + 0x100, BASE + 0x100 + len(ref_bytes)))
    cm = read_compare(cmp_mut)
    check(cm['b_const_fn'][2] == 'MISMATCH' and 'bytes differ' in cm['b_const_fn'][3],
          'b_const_fn MISMATCH (%s)' % cm['b_const_fn'][3])
    check(sum(1 for v in cm.values() if v[2] != 'MATCH') == 1, 'only b_const_fn differs')
    check('## diff b_const_fn' in out and re.search(r'^!0x1000[0-9A-F]+ .*\.word', out, re.M) is not None,
          '--diff shows the changed literal word')
    check(re.search(r'range .*: 1 of \d+ bytes differ', out) is not None, '--range reports 1 differing byte')

    # --- compare: moved callees → MATCH-ADDR ---------------------------------------------------------------------
    print('compare moved')
    mv_objs = [os.path.join(objdir, s + '.o') for s in ('fix_a', 'fix_pad', 'fix_b', 'fix_c')]
    mv_elf, mv_bin = build(wd, 'moved', mv_objs, ['-Wl,-u,pad_fn'])
    mv = elf_funcs(mv_elf)
    check(mv['a_caller'] == ref['a_caller'] and mv['b_add'][0] != ref['b_add'][0], 'pad_fn shifted fix_b/fix_c')
    cmp_mv = os.path.join(wd, 'cmp_moved.md')
    out = tool('compare.py', '--elf', mv_elf, '--bin', mv_bin, '--dump', dump, '--out', cmp_mv,
               '--code-end', hex(BASE + 0x10000), '--diff', hex(ref['a_caller'][0]))
    cv = read_compare(cmp_mv)
    check(cv['a_caller'][2] == 'MATCH-ADDR' and '2 BL target' in cv['a_caller'][3],
          'a_caller MATCH-ADDR (%s)' % cv['a_caller'][3])
    check(cv['a_table_sum'][2] == 'MATCH-ADDR' and 'address word' in cv['a_table_sum'][3],
          'a_table_sum MATCH-ADDR via literal pool (%s)' % cv['a_table_sum'][3])
    check(cv['a_local_only'][2] == 'MATCH' and cv['a_tiny'][2] == 'MATCH', 'unaffected fix_a functions MATCH')
    check(cv['b_add'][2] == 'MISMATCH', 'moved b_add MISMATCH at its new address')
    check('## diff a_caller' in out and out.count('\n!') >= 2, '--diff by address marks the two BL lines')
    out = tool('compare.py', '--elf', mv_elf, '--bin', mv_bin, '--dump', dump,
               '--code-end', hex(ref['b_add'][0] + 4))
    check(re.search(r'OUT-OF-IMAGE (\d+)', out) and int(re.search(r'OUT-OF-IMAGE (\d+)', out).group(1)) >= 5,
          'functions beyond --code-end are OUT-OF-IMAGE')

    # --- extract ------------------------------------------------------------------------------------------------
    print('extract')
    datadir = os.path.join(wd, 'data')
    shutil.rmtree(datadir, ignore_errors=True)
    s, e = ref['b_add'][0], ref['b_add'][0] + ref['b_add'][1]
    tool('extract.py', '--dump', dump, '--start', hex(s), '--end', hex(e), '--name', 'b_add', '--datadir', datadir)
    tool('extract.py', '--dump', dump, '--start', hex(s), '--end', hex(e + 2), '--name', 'b_add', '--datadir', datadir)
    tool('extract.py', '--dump', dump, '--start', hex(BASE), '--end', hex(BASE + 0x100), '--name', 'boot_ff',
         '--datadir', datadir)
    blob = open(os.path.join(datadir, 'b_add.bin'), 'rb').read()
    check(blob == ref_bytes[s - BASE - 0x100:e + 2 - BASE - 0x100], 'blob bytes')
    readme = open(os.path.join(datadir, 'README.md'), encoding='utf-8').read()
    check(readme.count('| b_add |') == 1 and '| boot_ff |' in readme and ('| %d |' % (e + 2 - s)) in readme,
          'README row updated in place, second row appended')

    print()
    if failures:
        print('FAILED: %d check(s)' % len(failures))
        for f in failures:
            print(' -', f)
        return 1
    print('all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
