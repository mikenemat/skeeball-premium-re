# ported from din8r-chassis-thermal/scripts/qa_footprints.py, 2026-10-26 as qa_footprints_board.py (SBC-1 keeps its own
# design-only qa_footprints.py; this one adds the board check: board FPIDs = design.py; paused parts board_const.PAUSED_REFS
# are excluded from FP-BOARD-MISSING on routing candidates - they are removed on purpose by route_prep.py)
# Origin: DIN-8R scripts/qa_footprints.py (C:/work/din-relay-8ch), adapted for CT (din8r_ct lib, board-vs-design FPIDs)
"""Footprint QA: every design.py footprint exists and covers its symbol's pins; the board carries exactly those
footprints.

    python scripts/qa_footprints.py [--json OUT]                                design check (CPython)
    py scripts/local_run.py qa_footprints.py --board [BOARD] [--json OUT]       + board check (KiCad Python)
Exit 0 = PASS, 1 = FAIL, 2 = tool error (fail closed).

DESIGN check (the parent's): libraries = CT's hardware/lib/skeeball.pretty + KiCad 10's installed footprint libs.
  FP-NOT-FOUND    a design footprint that exists in no library (or a malformed "lib:name" id)
  FP-PIN-NO-PAD   a symbol pin that the design connects has no pad of that number in the footprint
  FP-EXTRA-PAD    a footprint pad number that is not a symbol pin (unconnected copper nobody declared). Excepted:
                  unnamed pads (mechanical pegs / NPTH, paste apertures) and EXTRA_PAD_OK names (MP: mounting pads)
BOARD check (--board): the routed board must carry the footprints design.py names (DIN-8R lesson: a part / footprint
swap must reach the board; the HW-ADVQA2 ECO swaps footprints, and a board left on the old land must FAIL):
  FP-BOARD-MISMATCH  a board footprint whose FPID (lib:name) differs from design.py's
  FP-BOARD-MISSING   a design part with no footprint on the board
  FP-BOARD-EXTRA     a board footprint that is not a design part, unless it is a mechanical board-only footprint
                     (board-only attribute AND no pad on a copper layer with a net: CT's H1 / H2 mounting holes)
Fixtures: scripts/test_qa_footprints.py.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as LC  # noqa: E402

from netlist_core import symbol_pins  # noqa: E402

FPROOT = Path(r"C:/Program Files/KiCad/10.0/share/kicad/footprints")
PROJ_LIB = "skeeball"
PROJ = LC.ROOT / "hardware" / "lib" / f"{PROJ_LIB}.pretty"
EXTRA_PAD_OK = ("MP",)          # mounting-pad pad name (parent rule); unnamed pads are mechanical / apertures
DESIGN_CLASSES = ("FP-NOT-FOUND", "FP-PIN-NO-PAD", "FP-EXTRA-PAD")
BOARD_CLASSES = ("FP-BOARD-MISMATCH", "FP-BOARD-MISSING", "FP-BOARD-EXTRA")
CLASSES = DESIGN_CLASSES + BOARD_CLASSES


def fp_path(fpid, proj=PROJ, fproot=FPROOT):
    if ":" not in fpid:
        return None
    lib, name = fpid.split(":", 1)
    return (proj if lib == PROJ_LIB else fproot / f"{lib}.pretty") / f"{name}.kicad_mod"


def fp_pads(fpid, proj=PROJ, fproot=FPROOT):
    """the set of pad numbers of a library footprint, or None when it does not exist"""
    path = fp_path(fpid, proj, fproot)
    if path is None or not path.exists():
        return None
    return set(re.findall(r'\(pad\s+"([^"]*)"', path.read_text(encoding="utf-8")))


def design_check(design, proj=PROJ, fproot=FPROOT, pins_of=symbol_pins):
    fails = {c: [] for c in DESIGN_CLASSES}
    for p in sorted(design.parts.values(), key=lambda q: q.ref):
        pads = fp_pads(p.footprint, proj, fproot)
        if pads is None:
            fails["FP-NOT-FOUND"].append({"part": p.ref, "footprint": p.footprint,
                                          "path": str(fp_path(p.footprint, proj, fproot))})
            continue
        pins = {n for n, _, _ in pins_of(p.lib_id)}
        used = set(p.conns)
        missing = sorted((pins & used) - pads)
        if missing:
            fails["FP-PIN-NO-PAD"].append({"part": p.ref, "lib_id": p.lib_id, "footprint": p.footprint,
                                           "pins": missing})
        extra = sorted(x for x in pads - pins if x and x not in EXTRA_PAD_OK)
        if extra:
            fails["FP-EXTRA-PAD"].append({"part": p.ref, "footprint": p.footprint, "pads": extra})
    return fails


def board_check(design, pcb):
    import pcbnew
    fails = {c: [] for c in BOARD_CLASSES}
    b = pcbnew.LoadBoard(str(pcb))
    seen, mech = set(), []
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        fid = fp.GetFPID()
        fpid = f"{fid.GetLibNickname()}:{fid.GetLibItemName()}"
        pos = [round(pcbnew.ToMM(fp.GetPosition().x), 2), round(pcbnew.ToMM(fp.GetPosition().y), 2)]
        part = design.parts.get(ref)
        if part is None:
            netted = [p.GetNumber() for p in fp.Pads() if p.IsOnCopperLayer() and p.GetNetname()]
            if fp.IsBoardOnly() and not netted:
                mech.append(ref)
                continue
            fails["FP-BOARD-EXTRA"].append({"part": ref, "footprint": fpid, "at": pos,
                                            "why": "not board-only" if not fp.IsBoardOnly() else
                                            f"netted pads {netted[:8]}"})
            continue
        if ref in seen:
            fails["FP-BOARD-EXTRA"].append({"part": ref, "footprint": fpid, "at": pos, "why": "duplicate reference"})
            continue
        seen.add(ref)
        if fpid != part.footprint:
            fails["FP-BOARD-MISMATCH"].append({"part": ref, "board": fpid, "design": part.footprint, "at": pos})
    for ref in sorted(set(design.parts) - seen):
        if ref in LC.PAUSED_REFS:                          # removed on purpose for routing (route_prep.py)
            continue
        fails["FP-BOARD-MISSING"].append({"part": ref, "footprint": design.parts[ref].footprint})
    return fails, {"board": str(pcb), "footprints": len(b.GetFootprints()), "mechanical": sorted(mech)}


def check(design=None, board=None):
    t0 = time.time()
    if design is None:
        import design as _design
        design = _design.D
    fails = {c: [] for c in CLASSES}
    fails.update(design_check(design))
    info = {"parts": len(design.parts)}
    if board is not None:
        bf, binfo = board_check(design, board)
        fails.update(bf)
        info["board"] = binfo
    info["total_s"] = round(time.time() - t0, 2)
    return {"status": "FAIL" if any(fails.values()) else "PASS", "counts": {c: len(v) for c, v in fails.items()},
            "fails": fails, "info": info}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", nargs="?", const=str(LC.MAIN_PCB), default=None)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    try:
        board = None
        if a.board:
            board = Path(a.board)
            if not board.is_absolute():
                board = board.resolve() if board.exists() else LC.ROOT / board
            if not board.is_file():
                raise FileNotFoundError(f"board not found: {board}")
        res = check(board=board)
    except Exception as e:                                # fail closed
        import traceback
        traceback.print_exc()
        print(f"qa_footprints_board ERROR: {e!r}")
        return 2
    if a.json:
        out = Path(a.json) if Path(a.json).is_absolute() else LC.ROOT / a.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"qa_footprints_board {res['status']}  {res['info']['parts']} design parts"
          + (f"; board {Path(board).name}: {res['info']['board']['footprints']} footprints, mechanical "
             f"{res['info']['board']['mechanical']}" if board else " (no --board: design check only)"))
    for c in CLASSES if board else DESIGN_CLASSES:
        n = len(res["fails"][c])
        print(f"  {c:18s} {'FAIL' if n else 'ok':4s} {n}")
        for it in res["fails"][c][:12]:
            print("     ", json.dumps(it, default=str)[:220])
    print(f"qa_footprints_board {res['status']} ({'design + board' if board else 'design only'}): "
          + (", ".join(f"{k} {v}" for k, v in res["counts"].items() if v) or "0 findings"))
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
