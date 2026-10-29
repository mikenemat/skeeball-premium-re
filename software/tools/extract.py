#!/usr/bin/env python3
"""extract.py - copy an image address range to <datadir>/<name>.bin and record its hash in README.md.

    extract.py --dump image.bin [--base 0x10000000] --start 0x... --end 0x... --name <name> --datadir <dir>
"""
import argparse
import hashlib
import os
import re

HEADER = ['# Extracted data (local inputs; keep private)',
          '',
          'Source: the image and address range supplied on the command line. `end` is exclusive. Written by `tools/extract.py`.',
          '',
          '| name | start | end | size | sha256 |',
          '|---|---|---|---:|---|']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dump', required=True)
    ap.add_argument('--base', type=lambda x: int(x, 0), default=0x10000000)
    ap.add_argument('--start', type=lambda x: int(x, 0), required=True)
    ap.add_argument('--end', type=lambda x: int(x, 0), required=True, help='exclusive')
    ap.add_argument('--name', required=True)
    ap.add_argument('--datadir', required=True, help='destination directory for the extracted file and hash record')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.name):
        ap.error('--name: letters, digits, _ . - only')
    with open(args.dump, 'rb') as fh:
        dump = fh.read()
    lo, hi = args.start - args.base, args.end - args.base
    if not (0 <= lo < hi <= len(dump)):
        ap.error('range 0x%X-0x%X outside the dump (0x%X-0x%X)' % (args.start, args.end, args.base,
                                                                    args.base + len(dump)))
    blob = dump[lo:hi]
    sha = hashlib.sha256(blob).hexdigest()
    os.makedirs(args.datadir, exist_ok=True)
    out = os.path.join(args.datadir, args.name + '.bin')
    with open(out, 'wb') as fh:
        fh.write(blob)

    readme = os.path.join(args.datadir, 'README.md')
    lines = HEADER[:]
    if os.path.exists(readme):
        with open(readme, encoding='utf-8') as fh:
            lines = fh.read().rstrip('\n').split('\n')
        if not any(l.startswith('| name |') for l in lines):
            lines += ['', HEADER[-2], HEADER[-1]]
    row = '| %s | 0x%08X | 0x%08X | %d | %s |' % (args.name, args.start, args.end, len(blob), sha)
    pat = re.compile(r'^\|\s*%s\s*\|' % re.escape(args.name))
    for i, l in enumerate(lines):
        if pat.match(l):
            lines[i] = row
            break
    else:
        last = max(i for i, l in enumerate(lines) if l.startswith('|'))
        lines.insert(last + 1, row)
    with open(readme, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('%s: 0x%08X-0x%08X %d bytes sha256 %s' % (out, args.start, args.end, len(blob), sha))


if __name__ == '__main__':
    main()
