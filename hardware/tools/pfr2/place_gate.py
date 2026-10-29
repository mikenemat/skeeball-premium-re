# ported from din-relay-8ch/tools/pfr2/place_gate.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Exact placement legality gate on a dump_geom JSON (CPython + shapely) - what KiCad DRC would flag for PLACED parts
before any routing: same-side courtyard overlaps, and pad-to-foreign-copper clearance (pads / tracks / vias; zones are
refilled so they are skipped) with the class clearance max(A, B), ETH_CHASSIS 2.0 mm (except inside J2 / C43), LINE
domain vs SELV domain 6.5 mm, and the DRU maker-pad exceptions (Q1, U700, U701, U35, U1100 pad pairs 0.20 mm).

  python place_gate.py GEOM.json [--refs A,B,...] [--json OUT]
--refs limits the pad check to those parts' pads (courtyards are always checked against everything).
Exit 1 when any violation involves a checked part.
"""
import argparse
import json
import sys
from collections import defaultdict
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from shapely.strtree import STRtree
import cugraph

HV = {"HV_L", "HV_LP", "HV_OUT", "HV_N", "HV_DIV", "ISLAND"}
LV = {"SELV", "POWER_SELV", "PWR15", "COIL", "MDI", "PWR_FAULT", "CHASSIS"}
MAKER = set()            # DIN-8R DRU maker-pad exceptions (its Q1 / U700 ...); none on SBC-1 (refs differ)
CHASSIS_EXEMPT = {"J2", "C43"}


def _rules(ca, cb, ref_a, ref_b, kind_a, kind_b):
    """DRU clearance rules in file order (KiCad: the LAST matching rule wins; conditions tried both ways round)."""
    yield "LINE-SELV", ca in HV and cb in LV, 6.5
    yield "HV functional", ca in ("HV_OUT", "HV_N") and cb in ("HV_L", "HV_LP", "HV_OUT", "HV_N", "ISLAND"), 2.5
    yield "N to divider", ca == "HV_N" and cb == "HV_DIV", 0.8
    yield "Divider nodes", ca == "HV_DIV" and cb in ("HV_L", "HV_LP", "HV_OUT", "ISLAND"), 1.5
    yield "L-N", ca == "HV_N" and cb in ("HV_L", "HV_LP", "ISLAND"), 3.0
    yield "ETH_CHASSIS", ca == "CHASSIS" and not (ref_a and ref_a == ref_b and ref_a in CHASSIS_EXEMPT), 2.0
    yield "maker pads", kind_a == kind_b == "pad" and ref_a and ref_a == ref_b and ref_a in MAKER, 0.20


def required(na, nb, ref_a, ref_b, kind_a, kind_b):
    hit = None
    for args in ((na["class"], nb["class"], ref_a, ref_b, kind_a, kind_b),
                 (nb["class"], na["class"], ref_b, ref_a, kind_b, kind_a)):
        for i, (_, ok, v) in enumerate(_rules(*args)):
            if ok and (hit is None or i > hit[0]):
                hit = (i, v)
    return hit[1] if hit else max(na["clearance"], nb["clearance"])


def check(G, refs=None):
    nets = {int(k): v for k, v in G["nets"].items()}
    out = {"courtyard": [], "clearance": []}
    for side in ("F", "B"):
        cys = [(f["ref"], cugraph.ring_poly(r)) for f in G["footprints"] for r in f["courtyard"].get(side, [])]
        tree = STRtree([g for _, g in cys])
        for i, (ra, ga) in enumerate(cys):
            for j in tree.query(ga):
                if j <= i:
                    continue
                rb, gb = cys[j]
                if ra != rb and ga.distance(gb) < 1e-6:           # KiCad flags touching courtyards too
                    out["courtyard"].append({"a": ra, "b": rb, "side": side,
                                             "area": round(ga.intersection(gb).area, 4)})
    if refs is not None:
        import refloor_place
        void = refloor_place.plane_void(G)
        # electrical criterion: every pad over the plane; the body (courtyard) at most 1 mm2 over a void
        padv = defaultdict(float)
        for q in G["pads"]:
            if q["ref"] in refs:
                for L, rr in q["shapes"].items():
                    for r in rr:
                        padv[q["ref"]] += cugraph.ring_poly(r).intersection(void).area
        for f in G["footprints"]:
            if f["ref"] in refs:
                cya = sum(cugraph.ring_poly(r).intersection(void).area for rr in f["courtyard"].values() for r in rr)
                if padv[f["ref"]] > 1e-4 or cya > 1.0:
                    out.setdefault("plane_void", []).append({"ref": f["ref"], "pad_area": round(padv[f["ref"]], 3),
                                                             "courtyard_area": round(cya, 3)})
    cu = cugraph.Copper(G)
    bylayer = {}
    for k, it in cu.items.items():
        if it["kind"] == "zone":
            continue
        for L, g in it["geo"].items():
            if not g.is_empty:
                bylayer.setdefault(L, []).append((k, it, g))
    trees = {L: STRtree([x[2] for x in lst]) for L, lst in bylayer.items()}
    seen = set()
    for k, it in cu.items.items():
        if it["kind"] != "pad" or (refs is not None and it["rec"]["ref"] not in refs):
            continue
        ra = it["rec"]["ref"]
        for L, g in it["geo"].items():
            if g.is_empty:
                continue
            for j in trees[L].query(g.buffer(6.5)):
                k2, it2, g2 = bylayer[L][j]
                if k2 == k or (it2["net"] == it["net"] and it["net"]):
                    continue
                rb = it2["rec"].get("ref") if it2["kind"] == "pad" else None
                need = required(nets[it["net"]], nets[it2["net"]], ra, rb, "pad", it2["kind"])
                d = g.distance(g2)
                if d < need - 1e-4:
                    key = tuple(sorted([str(k), str(k2)])) + (L,)
                    if key in seen:
                        continue
                    seen.add(key)
                    out["clearance"].append({"ref": ra, "pad": it["rec"]["num"], "net": nets[it["net"]]["name"],
                                             "other": (rb or it2["kind"]) + (f".{it2['rec']['num']}" if rb else ""),
                                             "other_net": nets[it2["net"]]["name"], "layer": L,
                                             "need": need, "actual": round(d, 4)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom")
    ap.add_argument("--refs")
    ap.add_argument("--json")
    a = ap.parse_args()
    G = cugraph.load(a.geom)
    refs = set(a.refs.split(",")) if a.refs else None
    out = check(G, refs)
    if refs is not None:
        out["courtyard"] = [c for c in out["courtyard"] if c["a"] in refs or c["b"] in refs]
    for c in out["courtyard"]:
        print("COURTYARD", c)
    for c in out["clearance"]:
        print("CLEARANCE", c)
    for c in out.get("plane_void", []):
        print("PLANE_VOID", c)
    print(f"courtyard overlaps {len(out['courtyard'])}, pad clearance violations {len(out['clearance'])}")
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1)
    sys.exit(1 if (out["courtyard"] or out["clearance"] or out.get("plane_void")) else 0)


if __name__ == "__main__":
    main()
