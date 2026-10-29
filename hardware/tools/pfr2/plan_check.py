# ported from din-relay-8ch/tools/pfr2/plan_check.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Exact (shapely) legality pass over a pfr2.py plan against the board it was routed on; narrows track widths where the
grid could not see the exact geometry (pad entries) and reports what is still illegal.

  python plan_check.py GEOM.json PLAN.json OUT_PLAN.json [--json REPORT.json]

Checks (DRU semantics, place_gate.required for the pair clearance):
  * new track / via vs foreign copper on the same layer (existing pads / tracks / vias, force pours (never refilled),
    other new copper). SELV pours (GND / GND_ISO planes, +V_PULL etc.) are refilled around new copper: skipped;
  * track width: narrowed to 2 x (centre-line distance - need) - 2 um when needed; never below the floor: a
    current-carrying net its scripts/current_budget required width (pfr2.net_params), except the gate's neck
    (<= NECK_MM touching a narrower own pad, PWR_FAULT also inside a PWR_NECK box) at its neck floor; signals the pfr2
    class floor (SELV 0.2 outer / 0.15 inner, or 0.2);
  * via hole-to-hole 0.3 (edge to edge, all drills incl. same net), via / track to board edge 0.4;
Writes the narrowed plan; exit 1 when any violation remains.
"""
import argparse
import json
import sys
from collections import defaultdict
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from shapely.geometry import Point, LineString, box as sbox
from shapely.strtree import STRtree
from shapely.ops import unary_union
import shapely
import numpy as np
import cugraph
import place_gate
import pfr2
import native_constraints

FORCE = {"LINE", "NEUTRAL", "L_PSU"} | {f"OUT{i}" for i in range(1, 9)} | {f"COM{i}" for i in range(1, 9)}
NET_FLOOR = {"RLY_VCLAMP_1": 0.3, "RLY_VCLAMP_2": 0.3, "RLY_SNS": 0.3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--json")
    ap.add_argument("--drop-violations", action="store_true", help="pfr2-up (run_stage legalisation): leave every "
                    "violating track / via OUT of the written plan (exit code unchanged); land_stubs --peel-only then "
                    "removes the chains they leave loose and plan_check runs again")
    a = ap.parse_args()
    G = cugraph.load(a.geom)
    P = json.load(open(a.plan))
    nets = {int(k): v for k, v in G["nets"].items()}
    nid = {v["name"]: k for k, v in nets.items()}
    cu = cugraph.Copper(G)
    # obstacles per layer: (geom, net id, kind, key)
    obs = defaultdict(list)
    pad_local=native_constraints.pad_overrides(G)
    override={}
    band = sbox(-1e4, pfr2.FORCE_BAND[0], 1e4, pfr2.FORCE_BAND[1])
    for k, it in cu.items.items():
        if it["kind"] == "zone" and nets[it["net"]]["name"] not in FORCE:
            continue
        for L, g in it["geo"].items():
            if not g.is_empty:
                if it["kind"] == "zone" and nets[it["net"]]["class"] in pfr2.POCKET_CLASSES:
                    # pfr2 pocket policy: the out-of-band LINE / COM pour is a dead-end pocket the refill re-pours
                    # around ISLAND copper ("pocket" obstacles bind only non-ISLAND nets)
                    for part, kd in ((g.intersection(band), "zone"), (g.difference(band), "pocket")):
                        if not part.is_empty:
                            obs[L].append((part, it["net"], kd, ("old",) + tuple(map(str, k))))
                    continue
                obs[L].append((g, it["net"], it["kind"], ("old",) + tuple(map(str, k))))
                if it['kind']=='pad':override[("old",)+tuple(map(str,k))]=pad_local.get(it['rec']['uuid'],0)
    for p in G['pads']:
        hole=native_constraints.npth_shape(p)
        if hole is not None:
            key=('npth',p['uuid']);override[key]=.25
            for L in pfr2.ALL_LAYERS:obs[L].append((hole,0,'hole',key))
    new = []
    for i, t in enumerate(P["tracks"]):
        new.append(("t", i, t))
    for i, v in enumerate(P["vias"]):
        new.append(("v", i, v))
    for kind, i, x in new:
        if kind == "t":
            g = LineString([x["s"], x["e"]]).buffer(x["w"] / 2)
            obs[x["layer"]].append((g, nid[x["net"]], "trk", ("new", "t", i)))
        else:
            g = Point(x["x"], x["y"]).buffer(x["d"] / 2)
            for L in pfr2.ALL_LAYERS:
                obs[L].append((g, nid[x["net"]], "via", ("new", "v", i)))
    trees = {L: STRtree([o[0] for o in lst]) for L, lst in obs.items()}
    garr = {L: np.array([o[0] for o in lst], dtype=object) for L, lst in obs.items()}
    gbox = {L: shapely.bounds(garr[L]) for L in garr}
    gnet = {L: np.array([o[1] for o in lst], dtype=np.int64) for L, lst in obs.items()}
    nrow_c = {}

    def need_row(n, L):
        """the largest pair clearance of net n vs every net id (0 = no net -> 0.2) on L: a bbox-prefilter bound"""
        k_ = (n, L not in pfr2.OUTER)
        if k_ not in nrow_c:
            r_ = np.full(max(nets) + 1, max([.2]+list(override.values())))
            for f in nets:
                if f:
                    r_[f] = max(r_[f],need(n, f, L, "trk", "trk"))
            nrow_c[k_] = r_
        return nrow_c[k_]
    own_pad_c, own_old_c = {}, {}                 # pfr2-speed: per-net unions (were rebuilt per via from every obstacle)

    def own_pad_of(n):
        if n not in own_pad_c:
            own_pad_c[n] = {L: unary_union([og for og, on, okind, key in obs[L] if on == n and okind == "pad"])
                            for L in pfr2.OUTER}
        return own_pad_c[n]

    def own_old_of(n):
        if n not in own_old_c:
            own_old_c[n] = [unary_union([og for og, on, okind, key in obs[L] if on == n and key[0] == "old"])
                            for L in pfr2.OUTER]
        return own_old_c[n]
    outline = unary_union([cugraph.ring_poly(o) for o in G["outline"]])
    edge = outline.boundary
    boxes = defaultdict(list)
    for nb in P.get("neck_boxes", []):
        boxes[(nb["net"], nb["layer"])].append(sbox(*nb["box"]))
    report = {"narrowed": [], "violations": []}
    bad_ids = set()                              # id() of every violating plan track / via dict (--drop-violations)
    zl = [t for t in P["tracks"] if abs(t["s"][0] - t["e"][0]) < 1e-6 and abs(t["s"][1] - t["e"][1]) < 1e-6]
    P["tracks"] = [t for t in P["tracks"] if t not in zl]   # zero-length: a dot of copper, never needed
    report["dropped_zero_length"] = len(zl)

    need_c = {}
    MAXN = max([6.5] + [float(v.get("clearance") or 0) for v in nets.values()])   # largest pair clearance

    def need(a_, b_, L, ka, kb):
        """DRU pair clearance on layer L (incl. rule 'SELV inner fine pitch': SELV-SELV 0.15 on inner layers).
        pfr2-speed: cached per (net pair, inner / outer, kinds) - place_gate.required was 2 M calls / 7 s per run."""
        # place_gate.required reads only the two nets' class / clearance here (refs None: the kind-dependent
        # "maker pads" rule needs a ref), so the cache key is the class signature pair
        key = (nets[a_]["class"], nets[a_]["clearance"], nets[b_]["class"], nets[b_]["clearance"], L not in pfr2.OUTER)
        v = need_c.get(key)
        if v is None:
            v = place_gate.required(nets[a_], nets[b_], None, None, ka, kb)
            if L not in pfr2.OUTER and nets[a_]["class"] == "SELV" and nets[b_]["class"] == "SELV" and v <= 0.2 + 1e-9:
                v = pfr2.INNER_SELV
            need_c[key] = v
        return v

    own_pads = defaultdict(list)                  # (net id, layer) -> pad polygons (current_budget neck allowance)
    for k, it in cu.items.items():
        if it["kind"] == "pad":
            for L, g in it["geo"].items():
                if not g.is_empty:
                    own_pads[(it["net"], L)].append(g)

    def floor_of(t, seg):
        nm = t["net"]
        n = nid[nm]
        p = pfr2.net_params(nm, nets[n]["class"], nets[n].get("track"))
        if p[6]:                                  # current net: THE width rule (scripts/current_budget.py), as pfr2
            wnom = p[0] if t["layer"] in pfr2.OUTER else p[1]
            bx = boxes[(nm, t["layer"])] if nm in pfr2.PWR_FAULT_NETS else None
            neck = p[4] is not None and pfr2.neck_ok(seg, p[4], wnom, p[4], own_pads[(n, t["layer"])], bx)
            return p[4] if neck else wnom
        if nm in NET_FLOOR:
            return NET_FLOOR[nm]
        if nm in pfr2.PWR_FAULT_NETS:          # < 0.8 only when wholly inside one PWR_NECK box AT ITS WIDTH
            return p[4] if any(b.contains(seg.buffer(t["w"] / 2)) for b in boxes[(nm, t["layer"])]) else p[0]
        if nets[n]["class"] == "SELV":
            return pfr2.INNER_SELV if t["layer"] not in pfr2.OUTER else 0.2
        return p[4] if p[4] else 0.2

    # tracks: narrow to the exact clearance
    for i, t in enumerate(P["tracks"]):
        n = nid[t["net"]]
        L = t["layer"]
        cl = LineString([t["s"], t["e"]])
        w = t["w"]
        # pfr2-speed: the same candidates in the same order; distances vectorised (shapely.distance) and only the
        # candidates inside the clearance at the starting width visited (w only shrinks: no other one can bind)
        idx = trees[L].query(cl.buffer(w / 2 + 6.6))
        if len(idx):
            # bbox-gap lower bound: a candidate whose bbox is already beyond its pair clearance cannot bind
            cb = cl.bounds
            bb = gbox[L][idx]
            gap = np.hypot(np.maximum(0.0, np.maximum(bb[:, 0] - cb[2], cb[0] - bb[:, 2])),
                           np.maximum(0.0, np.maximum(bb[:, 1] - cb[3], cb[1] - bb[:, 3])))
            idx = idx[gap - w / 2 < need_row(n, L)[gnet[L][idx]] + 0.003 + 1e-9]
        if len(idx):
            d_all = shapely.distance(cl, garr[L][idx])
            soft = nets[n]["class"] in pfr2.POCKET_SOFT_FOR
            for j, d in zip(idx.tolist(), d_all.tolist()):
                if d - w / 2 >= MAXN + 0.003:
                    continue
                g, on, okind, key = obs[L][j]
                if on == n and on:
                    continue
                if okind == "pocket" and soft:
                    continue
                if key == ("new", "t", i):
                    continue
                nd = max(need(n, on, L, "trk", okind) if on else 0.2,override.get(key,0))
                if d - w / 2 < nd + 0.003:
                    w = round(2 * (d - nd - 0.003) - 0.001, 3)
        fl = floor_of(t, cl)
        if w < t["w"]:
            report["narrowed"].append({"i": i, "net": t["net"], "layer": L, "from": t["w"], "to": w, "floor": fl})
            if w < fl - 1e-6:
                bad_ids.add(id(t))
                report["violations"].append({"type": "clearance/width", "net": t["net"], "layer": L, "s": t["s"],
                                             "e": t["e"], "w_needed": w, "floor": fl})
            t["w"] = max(w, 0.0)
        elif t["w"] < fl - 1e-6:
            bad_ids.add(id(t))
            report["violations"].append({"type": "width-floor", "net": t["net"], "layer": L, "s": t["s"], "e": t["e"],
                                         "w": t["w"], "floor": fl})
        if cl.distance(edge) - t["w"] / 2 < 0.4 - 1e-4:
            bad_ids.add(id(t))
            report["violations"].append({"type": "edge", "net": t["net"], "layer": L, "s": t["s"]})
    # vias: clearance on every layer, hole-to-hole, edge
    drills = [(Point(v["x"], v["y"]), v["drill"] / 2, ("old", v["uuid"])) for v in G["vias"]]
    drills += [(Point(p["x"], p["y"]), max(p["drill"]) / 2, ("pad", p["uuid"])) for p in G["pads"] if p["drill"]]
    drills += [(Point(v["x"], v["y"]), v["drill"] / 2, ("new", i)) for i, v in enumerate(P["vias"])]
    dtree = STRtree([d[0] for d in drills])
    for i, v in enumerate(P["vias"]):
        n = nid[v["net"]]
        c = Point(v["x"], v["y"])
        g = c.buffer(v["d"] / 2)
        own_pad = own_pad_of(n)
        for L in pfr2.ALL_LAYERS:
            if L in pfr2.OUTER and own_pad[L].buffer(1e-4).contains(g):
                continue                     # via-in-pad: no new outer copper here
            idx = trees[L].query(g.buffer(6.6))
            d_all = shapely.distance(g, garr[L][idx]).tolist() if len(idx) else []
            for j, d in zip(idx.tolist(), d_all):
                if d >= MAXN:
                    continue
                og, on, okind, key = obs[L][j]
                if (on == n and on) or key == ("new", "v", i):
                    continue
                if okind == "pocket" and nets[n]["class"] in pfr2.POCKET_SOFT_FOR:
                    continue
                if L in pfr2.PLANE_LAYERS and nets[on]["name"] in pfr2.SOFT_ZONES:
                    continue
                nd = max(need(n, on, L, "via", okind) if on else 0.2,override.get(key,0))
                if d < nd - 1e-4:
                    bad_ids.add(id(v))
                    report["violations"].append({"type": "via-clearance", "net": v["net"], "at": [v["x"], v["y"]],
                                                 "layer": L, "other": nets[on]["name"], "d": round(d, 4),
                                                 "need": nd})
                    break
        for j in dtree.query(c.buffer(2.0)):
            pt, r, key = drills[j]
            if key == ("new", i):
                continue
            gap = c.distance(pt) - r - v["drill"] / 2
            if gap < 0.3 - 1e-4:
                if key[0] != "new" or key[1] > i:      # of a new-new pair, drop the later via only
                    bad_ids.add(id(v))
                report["violations"].append({"type": "hole-to-hole", "net": v["net"], "at": [v["x"], v["y"]],
                                             "gap": round(gap, 4), "other": key[0]})
        if c.distance(edge) - v["d"] / 2 < 0.4 - 1e-4:
            bad_ids.add(id(v))
            report["violations"].append({"type": "edge", "net": v["net"], "at": [v["x"], v["y"]]})
    # rule-area keep-outs (no_tracks / no_vias) bind the whole copper shape
    ko_tL = {L: unary_union([cugraph.ring_poly(o) for z in G["zones"] if z["rule_area"] and z.get("no_tracks")
                             and L in z.get("layers", [L]) for o in z["outline"]]) for L in pfr2.ALL_LAYERS}
    ko_v = unary_union([cugraph.ring_poly(o) for z in G["zones"] if z["rule_area"] and z.get("no_vias")
                        for o in z["outline"]])
    for t in P["tracks"]:
        if LineString([t["s"], t["e"]]).buffer(t["w"] / 2).intersection(ko_tL[t["layer"]]).area > 1e-6:
            bad_ids.add(id(t))
            report["violations"].append({"type": "keepout-track", "net": t["net"], "layer": t["layer"], "s": t["s"]})
    for v in P["vias"]:
        if Point(v["x"], v["y"]).buffer(v["d"] / 2).intersection(ko_v).area > 1e-6:
            bad_ids.add(id(v))
            report["violations"].append({"type": "keepout-via", "net": v["net"], "at": [v["x"], v["y"]]})
    # 60 Hz pickup rule areas (pfr2.HIZ_AREAS; pcb_setup.DRU_MAIN_PICKUP): ISLAND_HIZ tracks never in an area on its
    # layers, vias never in HIZ_INNER_KO, and in an outer area only wholly inside the net's own copper on that layer
    hiz = pfr2.hiz_ids(G, nets)
    if hiz:
        hz = defaultdict(list)
        for z in G["zones"]:
            if z["rule_area"] and z.get("name") in pfr2.HIZ_AREAS:
                hz[z["name"]].append(unary_union([cugraph.ring_poly(o) for o in z["outline"]]))
        hz = {k: unary_union(v) for k, v in hz.items()}
        # approved / as-built leg copper is grandfathered (pcb_pickup_rules.leg_copper; the areas apply to NEW copper)
        sys.path.insert(0, "C:/work/skeeball-controller/scripts")
        import pcb_pickup_rules as _PR
        _LC = _PR.leg_copper()
        _foot = defaultdict(list)
        for _t in _LC["tracks"]:
            _foot[(_t["net"], _t["layer"])].append((LineString([_t["s"], _t["e"]]) if _t["s"] != _t["e"]
                                                    else Point(_t["s"])).buffer(_t["w"] / 2 + 0.03))
        _foot = {k: unary_union(v) for k, v in _foot.items()}
        _vk = {(v_["net"], round(v_["x"], 2), round(v_["y"], 2)) for v_ in _LC["vias"]}

        def leg_ok(x):
            if "layer" in x:
                f_ = _foot.get((x["net"], x["layer"]))
                g_ = (LineString([x["s"], x["e"]]) if x["s"] != x["e"] else Point(x["s"])).buffer(x["w"] / 2)
                return f_ is not None and f_.contains(g_)
            return (x["net"], round(x["x"], 2), round(x["y"], 2)) in _vk
        t_area = {L: unary_union([g for k, g in hz.items() if pfr2.HIZ_AREAS[k] != "via" and L in next((
                  z.get("layers", []) for z in G["zones"] if z["rule_area"] and z.get("name") == k), [])]) for L in pfr2.ALL_LAYERS}
        for t in P["tracks"]:
            if nid[t["net"]] in hiz and t["w"] > 0:
                if leg_ok(t):
                    continue                          # approved / as-built leg copper: grandfathered (pcb_pickup_rules)
                if LineString([t["s"], t["e"]]).buffer(t["w"] / 2).intersection(t_area[t["layer"]]).area > 1e-6:
                    bad_ids.add(id(t))
                    report["violations"].append({"type": "pickup-area-track", "net": t["net"], "layer": t["layer"],
                                                 "s": t["s"], "e": t["e"]})
        for v in P["vias"]:
            n = nid[v["net"]]
            if n not in hiz:
                continue
            g = Point(v["x"], v["y"]).buffer(v["d"] / 2)
            if leg_ok(v):
                continue
            bad = any(k in hz and g.intersection(hz[k]).area > 1e-6 for k in ("HIZ_INNER_KO", "HIZ_VIA_KO"))
            own_any = own_old_of(n)
            in_pad = any(o.buffer(1e-4).contains(g) for o in own_any if not o.is_empty)
            for name in ("HIZ_OUTER_KO_F", "HIZ_OUTER_KO_B"):
                if name in hz and g.intersection(hz[name]).area > 1e-6 and not in_pad:
                    bad = True
            if bad:
                bad_ids.add(id(v))
                report["violations"].append({"type": "pickup-area-via", "net": v["net"], "at": [v["x"], v["y"]]})
    if a.drop_violations:
        nt, nv = len(P["tracks"]), len(P["vias"])
        P["tracks"] = [t for t in P["tracks"] if id(t) not in bad_ids]
        P["vias"] = [v for v in P["vias"] if id(v) not in bad_ids]
        report["dropped"] = {"tracks": nt - len(P["tracks"]), "vias": nv - len(P["vias"])}
        print("dropped (--drop-violations):", report["dropped"])
    P["tracks"] = [t for t in P["tracks"] if t["w"] > 0]
    json.dump(P, open(a.out, "w"), indent=1)
    from collections import Counter
    print("narrowed", len(report["narrowed"]), Counter((r["net"]) for r in report["narrowed"]).most_common(8))
    print("violations", len(report["violations"]), Counter(r["type"] for r in report["violations"]))
    for r in report["violations"][:25]:
        print("  ", r)
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)
    sys.exit(1 if report["violations"] else 0)


if __name__ == "__main__":
    main()
