# ported from din8r-chassis-thermal/scripts/qa_drc.py, 2026-10-26 (SBC-1: any board path, report beside a candidate,
# paused-part parity findings split out)
"""Board gate: KiCad DRC (schematic parity included) summarised, with DIN-8R's copper rules as hard failures.

    python scripts/qa_drc.py [BOARD] [--details N]      exit 0 = PASS

Adapted from DIN-8R scripts/drc_summary.py. DIN-8R lesson (CLAUDE.md "NO UNCONNECTED PAD OR LOOSE TRACE, EVER",
owner 2026-10-04): an unconnected pad, a dangling track, a dangling via or an isolated copper island is never
acceptable and never waived -> unconnected_items, track_dangling, via_dangling, isolated_copper, and every
clearance / short / hole / edge violation FAIL. Silkscreen-only findings are cosmetic (reported, not failing).
Parity: --schematic-parity compares the board with skeeball-controller.kicad_sch (footprints, values, nets); the
board's schematic must sit beside it (scripts/route_stage.py copies it).
SBC-1: BOARD defaults to hardware/main (report .runtime/drc.json = board_const.DRC_JSON); any other board writes
<board dir>/drc.json. PAUSED: parity 'missing_footprint' items naming a board_const.PAUSED_REFS part (the score jacks,
removed from routing candidates on purpose by route_prep.py) are counted separately, not failing - every other parity
item fails.
"""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from local_run import environment  # noqa: E402
import board_const as K  # noqa: E402

KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
PCB = K.MAIN_PCB
COSMETIC = {"silk_overlap", "silk_over_copper", "silk_edge_clearance", "text_height", "text_thickness",
            "silk_mask_clearance", "lib_footprint_issues", "lib_footprint_mismatch", "footprint_symbol_mismatch",
            "text_on_edge_cuts"}
WARN_ONLY = {"courtyards_overlap"}      # reviewed per instance
_PAUSED_RE = re.compile(r"\b(" + "|".join(K.PAUSED_REFS) + r")\b") if K.PAUSED_REFS else None   # none since 2026-10-27


def report_path(pcb):
    return K.DRC_JSON if Path(pcb).resolve() == K.MAIN_PCB.resolve() else Path(pcb).parent / "drc.json"


def run(pcb=PCB, details=0):
    out = report_path(pcb)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([KCLI, "pcb", "drc", "--severity-all", "--schematic-parity", "--format", "json", "-o",
                    str(out), str(pcb)], capture_output=True, env=environment())
    rep = json.loads(out.read_text(encoding="utf-8"))
    items = rep.get("violations", []) + rep.get("unconnected_items", []) + rep.get("schematic_parity", [])

    def kind(v):
        if v["type"] == "missing_footprint" and _PAUSED_RE is not None and _PAUSED_RE.search(v.get("description", "") + " ".join(
                i.get("description", "") for i in v.get("items", []))):
            return "paused:missing_footprint"
        return v["type"]
    kinds = Counter(kind(v) for v in items)
    fail = {k: n for k, n in kinds.items() if k not in COSMETIC and k not in WARN_ONLY and not k.startswith("paused:")}
    print(f"DRC {Path(pcb).name} ({out}): {sum(fail.values())} failing, "
          f"{sum(kinds[k] for k in kinds if k in WARN_ONLY)} warn-only, "
          f"{sum(kinds[k] for k in kinds if k in COSMETIC)} cosmetic, "
          f"{sum(kinds[k] for k in kinds if k.startswith('paused:'))} paused-part parity")
    for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        tag = "FAIL" if k in fail else ("warn" if k in WARN_ONLY else ("paus" if k.startswith("paused:") else "cosm"))
        print(f"   {tag} {n:5d} {k}")
    shown = 0
    for v in items:
        if kind(v) in fail and shown < details:
            print("   ---", v["type"], v.get("description", ""), [i.get("description", "") for i in v.get("items", [])],
                  [(i.get("pos", {}).get("x"), i.get("pos", {}).get("y")) for i in v.get("items", [])][:2])
            shown += 1
    return fail


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    d = 0
    if "--details" in args:
        i = args.index("--details")
        d = int(args[i + 1])
        del args[i:i + 2]
    raise SystemExit(1 if run(Path(args[0]).resolve() if args else PCB, d) else 0)
