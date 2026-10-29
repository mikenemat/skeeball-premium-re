# ported from din-relay-8ch/tools/pfr2/stage_loop.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Automated MAIN routing stages (CPython orchestration; KiCad steps via local_run.py).

  python stage_loop.py START_BOARD_DIR START_GEOM START_PLAN BASE_GEOM PREFIX [--stages 6] [--patience 2]
                       [--radius 2.5] [--srr 3000] [--iters 40]

Per stage i (board B_i, geom G_i, the pfr2 plan P_i that produced it):
  rip_local(G_i, P_i) -> move_rip(G_i, BASE, --rip) [BASE copper protected, floating islands dropped]
  -> apply_plan -> dump_geom -> pfr2 (--srr) -> run_stage -> B_{i+1}, G_{i+1}; open joins counted (open_joins.py).
Stops after --patience stages without a new best; prints the best stage. Logs: route/pfr2/<PREFIX>-s<i>.log.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

T = Path(__file__).resolve().parent
ROOT = T.parent
KPY = "C:/Program Files/KiCad/10.0/bin/python.exe"
LOCAL = "C:/work/skeeball-controller/scripts/local_run.py"
MR = Path("C:/work/skeeball-controller/.runtime/route/stage-boards")


def run(args, kicad=False, log=None):
    cmd = ([KPY, LOCAL] if kicad else [sys.executable]) + [str(a) for a in args]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n> {' '.join(map(str, args))}  ({time.time() - t0:.0f}s, exit {r.returncode})\n{out[-4000:]}\n")
    if r.returncode != 0:
        raise SystemExit(f"step failed: {args[0]} (exit {r.returncode})\n{out[-2000:]}")
    return out


def open_count(geom):
    sys.path.insert(0, str(T))
    import cugraph
    from open_joins import open_joins
    return len(open_joins(cugraph.load(str(geom))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board"); ap.add_argument("geom"); ap.add_argument("plan"); ap.add_argument("base")
    ap.add_argument("prefix")
    ap.add_argument("--stages", type=int, default=6)
    ap.add_argument("--patience", type=int, default=2)
    ap.add_argument("--radius", default="2.5")
    ap.add_argument("--srr", default="3000")
    ap.add_argument("--iters", default="40")
    ap.add_argument("--variants", type=int, default=4, help="router variants raced per stage (parallel processes)")
    ap.add_argument("--threads", type=int, default=4, help="per variant: legality warm-up threads")
    ap.add_argument("--stall", default="8")
    ap.add_argument("--gain", default="0.03")
    ap.add_argument("--reserve", default="", help="pfr2 --reserve: escape-reservation JSON held for its nets "
                    "(island-place/b1v2/escape-reservations.json)")
    ap.add_argument("--out", default="", help="put every stage artefact (logs, plans, boards, geoms) under this dir "
                    "instead of route/pfr2 + main-routing + geom")
    ap.add_argument("--rip-island", default="", metavar="OLD_BASE",
                    help="rip_local --island --old-base OLD_BASE (M1 lead decision: ISLAND cage copper may be ripped; "
                         "m1_protect.py never-rip set); use with a BASE built by m1_protect.py")
    ap.add_argument("--cage-selv", action="store_true", help="with --rip-island: start-board SELV tracks in a cage wall "
                    "are ripped too (rip_local --cage-selv, move_rip --allow-cage)")
    ap.add_argument("--cage-rails", action="store_true"); ap.add_argument("--cage-coil", action="store_true")
    ap.add_argument("--budget", default="", help="pfr2 --budget (seconds of router wall time per variant)")
    ap.add_argument("--keepout", default="", help="pfr2 --keepout: reserved boxes JSON")
    ap.add_argument("--pfr2-args", default="", help="extra pfr2 flags, space-separated (pfr2-up opt-ins, e.g. "
                    "\"--exact-clock --rescue --via-policy\")")
    ap.add_argument("--variant-timeout", type=float, default=0.0, help="seconds: kill router variants still running "
                    "after this (the stage keeps the variants that finished; owner budget 25 min / stage)")
    a = ap.parse_args()
    board, geom, plan = Path(a.board), ROOT / a.geom, ROOT / a.plan
    RT = Path(a.out) if a.out else ROOT / "route" / "pfr2"
    BD = Path(a.out) / "boards" if a.out else MR
    GD = Path(a.out) / "geom" if a.out else ROOT / "geom"
    for d_ in (RT, BD, GD):
        d_.mkdir(parents=True, exist_ok=True)
    base = ROOT / a.base
    best = (open_count(geom), 0, board, geom)
    print(f"stage 0: {board.name} open {best[0]}", flush=True)
    stale = 0
    for i in range(1, a.stages + 1):
        tag = f"{a.prefix}-s{i}"
        ts = time.time()
        log = RT / f"{tag}.log"
        rip = RT / f"{tag}-rip.json"
        mplan = RT / f"{tag}-plan.json"
        bd_r = BD / f"revC-{tag}r"
        g_r = GD / f"revC-{tag}r.json"
        P = RT / f"{tag}.json"
        bd_n = BD / f"revC-{tag}"
        g_n = GD / f"revC-{tag}.json"
        run([T / "rip_local.py", geom, plan, rip, "--radius", a.radius] +
            (["--island", "--old-base", a.rip_island] if a.rip_island else []) +
            (["--cage-selv"] if a.cage_selv else []) + (["--cage-rails"] if a.cage_rails else []) +
            (["--cage-coil"] if a.cage_coil else []), log=log)
        run([T / "move_rip.py", geom, base, mplan, "--rip", rip] +
            (["--allow-cage"] if (a.cage_selv or a.cage_rails or a.cage_coil) else []), log=log)
        run([T / "apply_plan.py", mplan, board, bd_r], kicad=True, log=log)
        run([T / "dump_geom.py", bd_r / "skeeball-controller.kicad_pcb", g_r], kicad=True, log=log)
        # race --variants router runs in parallel (seed 0 = default order, then deterministic order shuffles) and
        # keep the plan with the fewest open joins (then fewer vias)
        procs, outs = [], []
        for v in range(a.variants):
            Pv = P.with_name(P.stem + f"-v{v}.json")
            cmd = [sys.executable, str(T / "pfr2.py"), str(g_r), str(Pv), "--iters", a.iters, "--srr", a.srr,
                   "--threads", str(a.threads), "--stall", str(a.stall), "--gain", str(a.gain), "--seed", str(v * 7919)]
            if a.reserve:
                cmd += ["--reserve", a.reserve]
            if a.budget:
                cmd += ["--budget", a.budget]
            if a.keepout:
                cmd += ["--keepout", a.keepout]
            cmd += a.pfr2_args.split()
            lf = open(P.with_name(P.stem + f"-v{v}.log"), "w", encoding="utf-8")
            procs.append((subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT), lf))
            outs.append(Pv)
        t0 = time.time()
        for pr, lf in procs:
            left = a.variant_timeout - (time.time() - t0) if a.variant_timeout else None
            try:
                pr.wait(timeout=max(1.0, left) if left is not None else None)
            except subprocess.TimeoutExpired:
                pr.kill()
                pr.wait()
                print(f"stage {i}: a router variant overran {a.variant_timeout:.0f} s and was killed", flush=True)
            lf.close()
        scored = []
        for v, Pv in enumerate(outs):
            if not Pv.exists():
                continue
            # pfr2-up: a variant killed at its timeout keeps its last LEGAL checkpoint plan (pfr2 writes them
            # atomically, key "checkpoint"); a failed run without one is skipped
            try:
                J = json.load(open(Pv))
            except ValueError:
                continue
            if procs[v][0].returncode != 0 and "checkpoint" not in J:
                continue
            scored.append((sum(J["unrouted"].values()), len(J["vias"]), v, Pv))
        if not scored:
            raise SystemExit("every router variant failed")
        scored.sort()
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\nvariants ({time.time() - t0:.0f}s): " + ", ".join(
                f"v{v} open {o} vias {nv}" for o, nv, v, _ in sorted(scored, key=lambda x: x[2])) + "\n")
        P.write_bytes(scored[0][3].read_bytes())
        print(f"stage {i}: router variants {[(v, o) for o, _, v, _ in sorted(scored, key=lambda x: x[2])]} -> v{scored[0][2]}",
              flush=True)
        run([T / "run_stage.py", bd_r, P, bd_n, g_n], log=log)
        n = open_count(g_n)
        print(f"stage {i}: {bd_n.name} open {n} (best {best[0]} at stage {best[1]}) in {time.time() - ts:.0f} s",
              flush=True)
        if n < best[0]:
            best, stale = (n, i, bd_n, g_n), 0
        else:
            stale += 1
        board, geom, plan = bd_n, g_n, P
        if stale >= a.patience:
            break
    print(f"BEST stage {best[1]}: {best[2]} open {best[0]} ({best[3]})", flush=True)


if __name__ == "__main__":
    main()
