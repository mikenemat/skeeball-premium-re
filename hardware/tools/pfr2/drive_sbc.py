"""SBC-1 routing driver (CPython): the DIN-8R drive2.sh stage sequence on one SBC-1 scratch candidate. New 2026-10-27
(drive2.sh is DIN-8R-specific: M1 lineage, rip_island cages, delta_merge); every step below is a ported pfr2 tool.

  python tools/pfr2/drive_sbc.py RUN [--stages 4] [--budget 1200] [--pfr2-args "..."]

RUN = .runtime/route/RUN (made by scripts/route_stage.py: placed board + power_copper + rule areas + GND pours).
Per stage i (from board B_{i-1}, geom G_{i-1}):
  pfr2 G_{i-1} -> plan_i (PRODUCTION flags: --exact-clock --rescue --via-policy --det --tidy, --budget s, killed at
  budget + 10 min) -> run_stage (plan_check / via_merge / land_stubs / legalise / pfr_import / pcb_rules / dump) ->
  draft_native prune (land short ends, delete debris; LOCKED copper never) -> pour_stitch GND (F fragments onto the
  B.Cu pour, then B fragments onto F.Cu) applied with draft_native add / delete + refill -> dump -> open joins.
Stages >= 2 first rip (rip_local, DIN-8R stage_loop practice) the ripable copper of every net near the pads the previous
plan left caged, on a copy of the best board so far. Stops after 2 stages without a new best or --stages. The best stage board is copied to RUN/best/.
Then (once, on the best board): scripts/copper_cleanup.py (CT port, the gates' own CLEAN shortcuts), refill.
Freerouting is never used (owner 2026-10-27).
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
ROOT = T.parents[1]
LR = ROOT / "scripts" / "local_run.py"
BOARD = "skeeball-controller.kicad_pcb"
PROD = "--exact-clock --rescue --via-policy --det --tidy"


def run(args, kicad=False, log=None, check=True, timeout=None):
    cmd = ([sys.executable, str(LR)] if kicad else [sys.executable]) + [str(a) for a in args]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc, out = None, f"TIMEOUT after {timeout} s\n{(e.stdout or b'')[-2000:]!r}"
    msg = f"> {' '.join(str(a) for a in args[:3])}  ({time.time() - t0:.0f}s, exit {rc})"
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n{msg}\n{out[-6000:]}\n")
    print(msg, flush=True)
    if check and rc != 0:
        raise SystemExit(f"step failed: {args[0]} (exit {rc})\n{out[-3000:]}")
    return rc, out


def opens(geom):
    sys.path.insert(0, str(T))
    import cugraph
    from open_joins import open_joins
    return len(open_joins(cugraph.load(str(geom))))


def stitch(board, geom, work, tag, log):
    """pour_stitch: outer GND pour fragments onto the In1.Cu GND plane (4-layer, pass 5)"""
    for plane in ("In1.Cu",):
        d = work / f"{tag}-stitch-{plane[0]}.json"
        run([T / "pour_stitch.py", geom, d, "--net", "GND", "--via", "0.6,0.3", "--plane", plane], log=log)
        D = json.loads(d.read_text(encoding="utf-8"))
        if D["delete"]:
            run([T / "draft_native.py", "delete", board, d], kicad=True, log=log)
        if D["add"]["vias"]:
            run([T / "draft_native.py", "add", board, d], kicad=True, log=log)
        if D["delete"] or D["add"]["vias"]:
            run([T / "draft_native.py", "refill", board], kicad=True, log=log)
            run([T / "dump_geom.py", board, geom], kicad=True, log=log)
        print(f"  pour_stitch {plane}: +{len(D['add']['vias'])} vias, -{len(D['delete'])} ripped", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--stages", type=int, default=4)
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--pfr2-args", default=PROD)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--start-geom", default="", help="reuse a dumped geom of the start board")
    ap.add_argument("--start-plan", default="", help="stage 1: reuse this pfr2 plan instead of routing")
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--no-rip", action="store_true", help="stages >= 2 route on the previous board unchanged")
    ap.add_argument("--radius", default="2.5", help="rip_local radius around caged pads (mm)")
    a = ap.parse_args()
    R = ROOT / ".runtime" / "route" / a.run
    work = R / "drive"
    work.mkdir(parents=True, exist_ok=True)
    log = work / "drive.log"
    bdir = R / "main"
    g = Path(a.start_geom) if a.start_geom else work / "g0.json"
    if not a.start_geom:
        run([T / "dump_geom.py", bdir / BOARD, g], kicad=True, log=log)
    best = (opens(g), 0, bdir, g)
    best_plan = None
    print(f"stage 0: open joins {best[0]}", flush=True)
    stall = 0
    prev_plan = None
    for i in range(1, a.stages + 1):
        ts = time.time()
        plan = work / f"plan{i}.json"
        if i >= 2 and prev_plan is not None and not a.no_rip:
            # DIN-8R stage_loop practice (rip_local): rip the ripable copper of every net within --radius of the pads the
            # previous plan left caged (LOCKED copper never), on a copy of the stage board, then route again
            rd = work / f"r{i}"
            if rd.exists():
                shutil.rmtree(rd)
            shutil.copytree(bdir, rd)
            rip = work / f"rip{i}.json"
            run([T / "rip_local.py", g, prev_plan, rip, "--radius", a.radius], log=log)
            if json.loads(rip.read_text(encoding="utf-8"))["delete"]:
                run([T / "draft_native.py", "delete", rd / BOARD, rip], kicad=True, log=log)
                run([T / "draft_native.py", "refill", rd / BOARD], kicad=True, log=log)
            bdir = rd
            g = work / f"g{i}r.json"
            run([T / "dump_geom.py", bdir / BOARD, g], kicad=True, log=log)
        if i == 1 and a.start_plan:
            shutil.copy2(a.start_plan, plan)
        else:
            rc, _ = run([T / "pfr2.py", g, plan, "--budget", a.budget, "--threads", a.threads] + a.pfr2_args.split(),
                        log=work / f"pfr2-{i}.log", check=False, timeout=a.budget + 600)
            if not plan.exists():
                print(f"stage {i}: pfr2 wrote no plan (rc {rc})", flush=True)
                break
        nd, ng = work / f"s{i}", work / f"g{i}.json"
        if nd.exists():
            shutil.rmtree(nd)
        run([T / "run_stage.py", bdir, plan, nd, ng], log=log)
        for f in bdir.iterdir():                       # schematic + lib tables travel with the board (DRC parity)
            if f.suffix == ".kicad_sch" or f.name in ("fp-lib-table", "sym-lib-table"):
                shutil.copy2(f, nd / f.name)
        run([T / "draft_native.py", "prune", nd / BOARD, work / f"prune{i}.json"], kicad=True, log=log, check=False)
        run([T / "dump_geom.py", nd / BOARD, ng], kicad=True, log=log)
        stitch(nd / BOARD, ng, work, f"s{i}", log)
        n = opens(ng)
        J = json.loads(plan.read_text(encoding="utf-8"))
        print(f"stage {i}: open joins {n} (plan unrouted {sum(J['unrouted'].values())}, +{len(J['tracks'])} tracks, "
              f"+{len(J['vias'])} vias) in {time.time() - ts:.0f} s", flush=True)
        if n < best[0]:
            best, stall = (n, i, nd, ng), 0
        else:
            stall += 1
        bdir, g = (nd, ng) if n <= best[0] else (best[2], best[3])
        prev_plan = plan if n <= best[0] else best_plan
        if n <= best[0]:
            best_plan = plan
        if n == 0 or stall >= 2:
            break
    out = R / "best"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(best[2], out)
    print(f"BEST stage {best[1]}: open joins {best[0]} -> {out}", flush=True)
    if not a.no_cleanup:
        rc, o = run([ROOT / "scripts" / "copper_cleanup.py", out / BOARD, work / "cleanup.json"], log=log, check=False,
                    timeout=3600)
        print("copper_cleanup:", "\n".join(o.strip().splitlines()[-6:]), flush=True)
        run([T / "draft_native.py", "refill", out / BOARD], kicad=True, log=log)
    print(out / BOARD)


if __name__ == "__main__":
    main()
