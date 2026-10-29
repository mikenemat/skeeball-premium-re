# ported from din-relay-8ch/tools/pfr2/run_stage.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""One routing stage on a MAIN working board (orchestrates the replayable tools; CPython).

  python run_stage.py BOARD_DIR PLAN.json OUT_BOARD_DIR OUT_GEOM.json
plan_check (exact, narrows widths) -> via_merge (same-net hole-to-hole) -> land_stubs (every track end lands on its
net's copper; debris chains are left out) -> plan_check again; pfr2-up 2026-10-05: when it still finds violations
(router-exp A: 3 stub widths + 1 via clearance discarded the whole stage) ONLY the offending tracks / vias are left
out (plan_check --drop-violations), the chains they leave loose are peeled (land_stubs --peel-only; those joins stay
open for the next stage) and plan_check runs again (3 legalisation rounds, then it must be clean) ->
pfr_import (native add, PWR_NECK regenerated) -> apply_rules (current pcb_setup DRU) -> dump_geom of the new board.
Stops on the first failure.
"""
import subprocess
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
KP = r"C:\Program Files\KiCad\10.0\bin\python.exe"
LR = r"C:\work\skeeball-controller\scripts\local_run.py"
board_dir, plan, out_dir, out_geom = (Path(x).resolve() for x in sys.argv[1:5])
geom_in = Path(str(out_geom).replace(".json", "-src.json"))


def run(args, kicad=False, check=True):
    cmd = ([KP, LR] if kicad else [sys.executable]) + [str(a) for a in args]
    print(">", " ".join(cmd[-4:]), flush=True)
    t_ = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
    print("\n".join("   " + x for x in tail), flush=True)
    print(f"   ({time.time() - t_:.1f} s, exit {r.returncode})", flush=True)
    if check and r.returncode != 0:
        raise SystemExit(f"stage step failed: {args[0]}")
    return r.returncode


run([T / "dump_geom.py", board_dir / "skeeball-controller.kicad_pcb", geom_in], kicad=True)
chk1 = plan.with_name(plan.stem + "-chk1.json")
merged = plan.with_name(plan.stem + "-m.json")
chk2 = plan.with_name(plan.stem + "-ok.json")
subprocess.run([sys.executable, str(T / "plan_check.py"), str(geom_in), str(plan), str(chk1)])   # narrows; may flag h2h
run([T / "via_merge.py", chk1, merged])
landed = plan.with_name(plan.stem + "-land.json")
run([T / "land_stubs.py", geom_in, merged, landed])          # stub repair: every track end lands (or the stage fails)
cur = landed
for k in range(4):
    # pfr2-up legalisation: drop only the offending stubs / tracks / vias, peel the chains they leave loose, re-check.
    # pfr2-speed: ONE plan_check per round - with --drop-violations it writes the legal plan and still exits 1 on any
    # violation (none: byte-identical to a plain check), so the former second (drop) run per round is gone
    legal = plan.with_name(plan.stem + f"-legal{k}.json")
    if run([T / "plan_check.py", geom_in, cur, legal] + (["--drop-violations"] if k < 3 else []),
           check=(k == 3)) == 0:
        chk2.write_bytes(legal.read_bytes())
        break
    peeled = plan.with_name(plan.stem + f"-peel{k}.json")
    run([T / "land_stubs.py", geom_in, legal, peeled, "--peel-only"])
    cur = peeled
run([T / "pfr_import.py", board_dir, chk2, out_dir], kicad=True)
# SBC-1: no .kicad_dru generator (DIN-8R apply_rules / pcb_setup); THE rule set is scripts/pcb_rules.py
run([Path(LR).parent / "pcb_rules_apply.py", out_dir / "skeeball-controller.kicad_pcb"], kicad=True)
run([T / "dump_geom.py", out_dir / "skeeball-controller.kicad_pcb", out_geom], kicad=True)
print("stage done:", out_dir, out_geom)
