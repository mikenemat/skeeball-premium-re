# ported from din-relay-8ch/tools/pfr2/land_stubs.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Landing repair of a pfr2 plan before import (CPython) - the stub-repair stage of run_stage.py.

  python land_stubs.py GEOM.json PLAN.json OUT_PLAN.json [--reach 1.0]

pfr2 trims a route where its raster sees the net's own copper and keeps one own cell; the exact end can then sit just
outside the pad / via / track it was meant to join (M1 C13: 7 track ends 0.004 - 0.9 mm short of a pad edge, which
qa_copper_landing reports as TRACK-END / PAD-LAND). For every plan track end that lies on NO same-net copper (board pads,
vias, tracks, zone fills of the net + every other plan track / via) the nearest same-net pad or via within --reach gets a
stub from the end to its CENTRE (owner 2026-10-05: traces run from the centre of the pads), or the nearest same-net
track a stub onto its centreline (width = the track's width). A plan chain end that lands inside an SMD pad off its
centre gets a stub on to the pad centre (qa_copper_landing PAD-CENTRE).
An end with nothing of its net within --reach is router debris: that track and the loose chain it leaves are NOT
imported (the join stays open for the next stage; never loose copper on the board); with --strict it fails the import
(exit 1). The stubs are clearance-checked by the plan_check.py run that follows (run_stage.py).
"""
import argparse
import json
import math
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
import numpy as np
import shapely
import cugraph
import via_site

EPS = 1e-4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--reach", type=float, default=1.0)
    ap.add_argument("--strict", action="store_true", help="a dangling end fails the import (exit 1) instead of being "
                    "left out with its loose chain")
    ap.add_argument("--peel-only", action="store_true", help="pfr2-up (run_stage legalisation, after plan_check "
                    "--drop-violations): add NO stubs; every unlanded plan end is debris and its loose chain is peeled")
    a = ap.parse_args()
    G = cugraph.load(a.geom)
    P = json.load(open(a.plan))
    nid = {v["name"]: int(k) for k, v in G["nets"].items()}
    # via-edge backstop (owner 2026-10-05: pad-edge / half-in-pad vias are defects): every plan via is re-checked with
    # the gate's exact geometry (via_site -> qa_copper_landing.padedge_class). An illegal one is left out; the track ends
    # it held land below like any other unlanded end (a stub to a same-net pad CENTRE / via) or peel as debris (the join
    # stays open for the next stage). pfr2 makes these sites hard-illegal, so this only catches raster escapes.
    pix = via_site.PadIndex(G)
    bad_v = [v for v in P["vias"] if via_site.site_faults(pix, dict(v, net=nid[v["net"]]))]
    if bad_v:
        P["vias"] = [v for v in P["vias"] if not any(v is b for b in bad_v)]
        print(f"land_stubs: {len(bad_v)} pad-edge / partial plan vias left out (via_site)")
    cu = cugraph.Copper(G)
    # same-net copper per (net, layer): (geometry, anchor point or line, kind)
    items = {}
    for k, it in cu.items.items():
        for L, g in it["geo"].items():
            if g is None or g.is_empty:
                continue
            if it["kind"] in ("pad", "via"):
                r = it["rec"]
                anchor = Point(r["x"], r["y"])
            elif it["kind"] == "trk":
                r = it["rec"]
                anchor = LineString([r["s"], r["e"]]) if r["s"] != r["e"] else Point(r["s"])
            else:
                anchor = None                      # zone fill: copper, no stub target
            items.setdefault((it["net"], L), []).append((g, anchor, it["kind"]))
    for t in P["tracks"]:
        g = (LineString([t["s"], t["e"]]) if t["s"] != t["e"] else Point(t["s"])).buffer(t["w"] / 2)
        items.setdefault((nid[t["net"]], t["layer"]), []).append(
            (g, LineString([t["s"], t["e"]]) if t["s"] != t["e"] else Point(t["s"]), "plan-trk"))
    layers = list(G["layers"])
    for v in P["vias"]:
        g = Point(v["x"], v["y"]).buffer(v["d"] / 2)
        for L in layers:
            items.setdefault((nid[v["net"]], L), []).append((g, Point(v["x"], v["y"]), "plan-via"))
    trees = {k: STRtree([x[0] for x in v]) for k, v in items.items()}
    board_items = {}
    for k, it in cu.items.items():
        for L, g in it["geo"].items():
            if g is not None and not g.is_empty:
                board_items.setdefault((it["net"], L), []).append(g)
    board_trees = {k: STRtree(v) for k, v in board_items.items()}

    def landed_on_board(net, layer, q):
        key = (nid[net], layer)
        if key not in board_trees:
            return False
        p_ = Point(q)
        return any(board_items[key][j].distance(p_) < EPS for j in board_trees[key].query(p_.buffer(EPS)))
    smd_c = {(p_["x"], p_["y"]) for p_ in G["pads"] if not p_.get("drill") and p_["shapes"]}
    from collections import Counter
    plan_ends = Counter((t["net"], t["layer"], round(q[0], 4), round(q[1], 4)) for t in P["tracks"] for q in (t["s"], t["e"]))
    stubs, dangling = [], []
    for i, t in enumerate(P["tracks"]):
        n = nid[t["net"]]
        key = (n, t["layer"])
        own = LineString([t["s"], t["e"]]) if t["s"] != t["e"] else Point(t["s"])
        for end in (t["s"], t["e"]):
            q = Point(end)
            lst = items.get(key, [])
            hits = [lst[j] for j in trees[key].query(q.buffer(EPS))] if key in trees else []
            # landed: inside a same-net item other than this track itself
            if any(g.distance(q) < EPS and not (k_ == "plan-trk" and anc.equals(own)) for g, anc, k_ in hits):
                # landed. A chain end inside an SMD pad runs on to the pad CENTRE (owner 2026-10-05: "traces run from
                # the edge of the pads. They should run FROM THE CENTER OF THE PADS"; qa_copper_landing PAD-CENTRE)
                if a.peel_only:
                    continue
                pc = next((anc for g, anc, k_ in hits if k_ == "pad" and g.contains(q) and (anc.x, anc.y) in smd_c), None)
                if pc is not None and pc.distance(q) > 0.02 and plan_ends[(t["net"], t["layer"], round(q.x, 4), round(q.y, 4))] == 1                         and not any(k_ in ("via", "plan-via") and g.distance(q) < EPS for g, anc, k_ in hits):
                    stubs.append({"net": t["net"], "layer": t["layer"], "s": [round(q.x, 4), round(q.y, 4)],
                                  "e": [round(pc.x, 4), round(pc.y, 4)], "w": t["w"], "landing_stub": "pad-centre"})
                continue
            if a.peel_only:
                dangling.append({"net": t["net"], "layer": t["layer"], "at": end})
                continue
            best = None
            for j in (trees[key].query(q.buffer(a.reach)) if key in trees else []):
                g, anc, k_ = lst[j]
                if anc is None or (k_ == "plan-trk" and anc.equals(own)):
                    continue
                d = g.distance(q)
                if d > a.reach:
                    continue
                if k_ in ("pad", "via", "plan-via"):
                    tgt = anc                              # a pad / via is landed at its CENTRE (owner 2026-10-05)
                else:
                    tgt = anc.interpolate(anc.project(q)) if anc.geom_type == "LineString" else anc
                if best is None or d < best[0]:
                    best = (d, tgt, k_)
            if best is None:
                dangling.append({"net": t["net"], "layer": t["layer"], "at": end})
                continue
            tgt = best[1]
            if q.distance(tgt) < EPS:
                continue
            stubs.append({"net": t["net"], "layer": t["layer"], "s": [round(q.x, 4), round(q.y, 4)],
                          "e": [round(tgt.x, 4), round(tgt.y, 4)], "w": t["w"], "landing_stub": best[2]})
    # pfr2-up: a stub whose centreline already lies on a same-net plan track (pfr2 starts tracks at the exact pad
    # centre) is not added (TRACK-DUP); exact / covered duplicates among the plan tracks are dropped too
    # pfr2-speed: the same first-match rule, with each group's centrelines built once and the distances vectorised
    # (it built a LineString per PAIR: 1.1 M constructions / 11 s per stage)
    def covered_in(t, lst, lines, excl=None):
        """index of the first o in lst (not t, not excluded, same net / layer by construction, at least as wide,
        non-degenerate) whose centreline passes within 1e-3 of both of t's ends, else None"""
        wv, valid = lines
        cand = valid & (wv >= t["w"] - 1e-9)
        if excl:
            cand[list(excl)] = False
        if not cand.any():
            return None
        ci = np.nonzero(cand)[0]
        la = lines_all[id(lst)][ci]
        ok = (shapely.distance(la, Point(t["s"])) < 1e-3) & (shapely.distance(la, Point(t["e"])) < 1e-3)
        hit = np.nonzero(ok)[0]
        return int(ci[hit[0]]) if hit.size else None
    by_nl = {}
    for t in P["tracks"]:
        by_nl.setdefault((t["net"], t["layer"]), []).append(t)
    lines_nl, lines_all = {}, {}
    for k_, lst in by_nl.items():
        lines_all[id(lst)] = np.array([LineString([o["s"], o["e"]]) if o["s"] != o["e"] else None for o in lst],
                                      dtype=object)
        lines_nl[k_] = (np.array([o["w"] for o in lst], float), np.array([o["s"] != o["e"] for o in lst], bool))
    stubs = [s_ for s_ in stubs if (s_["net"], s_["layer"]) not in by_nl or
             covered_in(s_, by_nl[(s_["net"], s_["layer"])], lines_nl[(s_["net"], s_["layer"])]) is None]
    keep_, n_dup = [], 0
    for key_, lst in by_nl.items():
        gone = set()
        for i_, t in enumerate(lst):
            j = covered_in(t, lst, lines_nl[key_], gone | {i_})
            o = lst[j] if j is not None else None
            if o is not None and (math.dist(o["s"], o["e"]) > math.dist(t["s"], t["e"]) + 1e-9 or
                                  lst.index(o) < i_):
                gone.add(i_)
        n_dup += len(gone)
        keep_ += [t for i_, t in enumerate(lst) if i_ not in gone]
    P["tracks"] = keep_ + stubs
    if n_dup:
        print(f"land_stubs: {n_dup} duplicate / covered plan tracks dropped")
    peeled = []
    if dangling and not a.strict:
        # a plan end with nothing of its net within --reach is router debris (a rip-up left a later path ending on
        # copper that no longer exists): that track and the chain it leaves loose are NOT imported - the join stays open
        # for the next stage (never loose copper on the board)
        dang = {(d["net"], d["layer"], round(d["at"][0], 4), round(d["at"][1], 4)) for d in dangling}
        keep = list(P["tracks"])
        while True:
            ends = {}
            for t in keep:
                for q in (t["s"], t["e"]):
                    ends[(t["net"], t["layer"], round(q[0], 4), round(q[1], 4))] = ends.get(
                        (t["net"], t["layer"], round(q[0], 4), round(q[1], 4)), 0) + 1
            vias_at = {(v["net"], round(v["x"], 4), round(v["y"], 4)) for v in P["vias"]}
            drop = [t for t in keep if any((t["net"], t["layer"], round(q[0], 4), round(q[1], 4)) in dang for q in (t["s"], t["e"]))]
            if not drop:
                break
            for t in drop:
                keep.remove(t)
                peeled.append(t)
                for q in (t["s"], t["e"]):
                    k = (t["net"], t["layer"], round(q[0], 4), round(q[1], 4))
                    if k in dang:
                        continue
                    # the other end: loose now if no other plan track / via shares it and nothing landed it before
                    # loose if at most one OTHER plan track shares that end (the next link of the chain)
                    if ends.get(k, 0) - 1 <= 1 and (t["net"], k[2], k[3]) not in vias_at and not landed_on_board(t["net"], t["layer"], q):
                        dang.add(k)
        P["tracks"] = keep
    json.dump(P, open(a.out, "w"), indent=1)
    print(f"land_stubs: {len(stubs)} landing stubs added, {len(dangling)} dangling ends"
          + (f", {len(peeled)} plan tracks of their loose chains not imported" if peeled else ""))
    for d in dangling[:20]:
        print("  DANGLING", d)
    return 1 if (dangling and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
