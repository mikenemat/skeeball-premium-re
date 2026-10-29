"""QA: every footprint named in design.py resolves - a KiCad 10 stock footprint, or a project footprint in
hardware/lib/skeeball.pretty. Project footprints that are not drawn yet (they need the owner's measurements or a maker
drawing) must be listed in PENDING with the reason; anything else missing FAILS.
usage: python qa_footprints.py      (exit 0 = PASS)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from design import D  # noqa: E402

KICAD_FP = Path(r"C:/Program Files/KiCad/10.0/share/kicad/footprints")
PROJ_FP = Path(__file__).resolve().parents[1] / "hardware" / "lib" / "skeeball.pretty"

PENDING = {   # footprint -> what it needs before it can be drawn (none: every footprint is drawn, 2026-10-26)
}


def exists(fp):
    lib, name = fp.split(":", 1)
    base = PROJ_FP if lib == "skeeball" else KICAD_FP / f"{lib}.pretty"
    return (base / f"{name}.kicad_mod").exists()


def main():
    bad, pend = [], []
    for p in D.parts.values():
        if exists(p.footprint):
            continue
        (pend if p.footprint in PENDING else bad).append((p.ref, p.footprint))
    for ref, fp in sorted(pend):
        print(f"PENDING {ref:6} {fp}  - {PENDING[fp]}")
    for ref, fp in sorted(bad):
        print(f"FAIL    {ref:6} {fp}  - not found")
    print(f"footprints: {len(D.parts)} parts, {len(bad)} missing, {len(pend)} pending (listed)")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
