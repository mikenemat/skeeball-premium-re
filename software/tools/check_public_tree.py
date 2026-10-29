#!/usr/bin/env python3
"""Check the software index; --worktree also checks visible working-tree candidates.
This is a path/type guard, not a secret scanner or legal/provenance review.
"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "software/"
LIMIT = 256 * 1024

def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worktree", action="store_true")
    args = ap.parse_args()
    entries = {}
    for row in git("ls-files", "--stage", "-z", "--", "software").split(b"\0"):
        if not row:
            continue
        head, path = row.split(b"\t", 1)
        mode, oid, stage = head.decode("ascii").split()
        entries[path.decode("utf-8")] = (mode, oid, stage)
    policy = PREFIX + "public-files.txt"
    if policy in entries:
        allowed_text = git("cat-file", "blob", entries[policy][1]).decode("utf-8")
    else:
        allowed_text = (ROOT / policy).read_text(encoding="utf-8")
    allowed = {PREFIX + line.strip() for line in allowed_text.splitlines()
               if line.strip() and not line.lstrip().startswith("#")}
    errors = []
    def inspect(path, data, mode="100644", stage="0"):
        relative = path[len(PREFIX):]
        if "internal" in relative.lower().split("/"):
            errors.append(path + ": private internal path")
        elif path not in allowed:
            errors.append(path + ": not listed in public-files.txt")
        if mode not in ("100644", "100755") or stage != "0":
            errors.append(path + ": link, submodule or unresolved index entry")
        if len(data) > LIMIT or b"\0" in data:
            errors.append(path + ": binary or oversized content")
        else:
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(path + ": non-UTF-8 content")
    for path, (mode, oid, stage) in entries.items():
        if "internal" in path.lower().split("/"):
            errors.append(path + ": private internal path")
            continue
        if mode not in ("100644", "100755") or stage != "0":
            errors.append(path + ": link, submodule or unresolved index entry")
            continue
        inspect(path, git("cat-file", "blob", oid), mode, stage)
    if args.worktree:
        paths = set(entries)
        paths.update(p.decode("utf-8") for p in
                     git("ls-files", "--others", "--exclude-standard", "-z", "--", "software").split(b"\0") if p)
        for path in sorted(paths):
            if "internal" in path.lower().split("/"):
                continue
            p = ROOT / path
            if p.is_symlink():
                errors.append(path + ": working-tree symlink")
            elif p.is_file():
                inspect(path, p.read_bytes())
    if errors:
        print("Publication guard FAILED:", file=sys.stderr)
        for error in sorted(set(errors)):
            print("  " + error, file=sys.stderr)
        return 1
    print("Publication guard PASS (%d indexed software files%s)." %
          (len(entries), "; visible working-tree candidates checked" if args.worktree else ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
