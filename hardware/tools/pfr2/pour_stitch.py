# ported from din-relay-8ch/tools/pfr2/pour_stitch.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Pour stitching (owner doctrine 2026-10-05 (d): missing / carved pours) - CPython on dump_geom JSON, writes a delta_merge
"add vias" delta. Read-only on the board.

  python pour_stitch.py GEOM.json OUT_DELTA.json [--net GND] [--via 0.45,0.2]

An outer-layer fill fragment of NET (F.Cu / B.Cu) that touches a pad of the net but holds no via / THT pad of the net is
an island cut off from the inner plane by routing: the pads on it count as open. One stitching via goes into each such
fragment, at the legal site nearest to a pad of the fragment: the via disc inside the fragment, over the net's In1 fill
(the plane it stitches to), clear of every other-net item on every layer at the class clearance (place_gate), 0.3 mm
hole-to-hole, outside no-via rule areas. A fragment with no legal site: the unprotected router tracks severing it from the
rest of the pour (in the gap between it and another fill part of the net) are ripped (re-routed next stage) - the
root cause, not the symptom. Pad-less / via-less fragments are counted (island removal drops them at refill).
Only NEEDED stitches are added (cruft-fix 2026-10-05, qa_copper_landing VIA-BARE): a fragment gets a via only when it holds
no via / plated hole of the net at all (0 < 2 links), one via per fragment; copper_cleanup.py (run after pour_stitch in
drive2.sh) removes any stitch that later becomes redundant.
"""
import argparse
import json
import sys
import uuid
sys.path.insert(0, "C:/work/skeeball-controller/tools/pfr2")
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
import cugraph
import place_gate
import via_site

NS = uuid.UUID("6f1d2c1e-4c1b-5b6e-9a51-2a7f4f1c0b15")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("out")
    ap.add_argument("--net", default="GND")
    ap.add_argument("--via", default="0.45,0.2")
    ap.add_argument("--plane", default="In1.Cu")
    a = ap.parse_args()
    vd, vdr = map(float, a.via.split(","))
    G = cugraph.load(a.geom)
    nets = {int(k): v for k, v in G["nets"].items()}
    nn = lambda n: nets.get(n) or {"class": "Default", "clearance": 0.2, "name": ""}
    net = next(k for k, v in nets.items() if v["name"] == a.net)
    cu = cugraph.Copper(G)
    pix = via_site.PadIndex(G)
    fills = {}
    for z in G["zones"]:
        if not z["rule_area"] and z["net"] == net:
            for L, rs in z.get("fills", {}).items():
                fills.setdefault(L, []).extend(cugraph.ring_poly(r) for r in rs)
    plane = unary_union(fills.get(a.plane, []))
    anchors = [Point(v["x"], v["y"]) for v in G["vias"] if v["net"] == net] + \
              [Point(p["x"], p["y"]) for p in G["pads"] if p["net"] == net and p.get("drill")]
    novia = unary_union([cugraph.ring_poly(o) for z in G["zones"] if z["rule_area"] and z.get("no_vias") for o in z["outline"]])
    # other-net zone fills are refilled around a new via (antipad) - only the force pours, whose outlines are fixed, block
    items = [(k, it, g) for k, it in cu.items.items() if it["net"] != net and (it["kind"] in ("pad", "trk", "via") or (
             it["kind"] == "zone" and nn(it["net"])["class"] in ("HV_L", "HV_LP", "HV_OUT", "HV_N")))
             for g in it["geo"].values() if g is not None and not g.is_empty]
    tree = STRtree([x[2] for x in items])
    drills = [(Point(v["x"], v["y"]), v["drill"]) for v in G["vias"]] + \
             [(Point(p["x"], p["y"]), max(p["drill"])) for p in G["pads"] if p.get("drill")]
    dtree = STRtree([d[0] for d in drills])
    pads = [(p, unary_union([cugraph.ring_poly(r) for r in rs]), L) for p in G["pads"] if p["net"] == net
            for L, rs in p["shapes"].items()]
    add, report, placed, ripped = [], [], [], {}
    from m1_protect import Rule
    RU = Rule(G, None)
    dead = sum(1 for L in ("F.Cu", "B.Cu") for f in fills.get(L, []) for q in getattr(f, "geoms", [f])
               if not any(g.intersects(q) for p, g, PL in pads if PL == L) and not any(q.contains(pt) for pt in anchors))
    for L in ("F.Cu", "B.Cu"):
        for frag in (q for f in fills.get(L, []) for q in getattr(f, "geoms", [f])):
            mine = [(p, g) for p, g, PL in pads if PL == L and g.intersects(frag)]
            if not mine or any(frag.contains(pt) for pt in anchors + placed):
                continue
            inner = frag.buffer(-vd / 2)
            if inner.is_empty:
                report.append({"layer": L, "pads": [f"{p['ref']}.{p['num']}" for p, _ in mine][:4], "result": "fragment too thin"})
                continue
            cands = []
            x0, y0, x1, y1 = inner.bounds
            nx, ny = int((x1 - x0) / 0.1) + 1, int((y1 - y0) / 0.1) + 1
            for i in range(nx):
                for j in range(ny):
                    c = Point(x0 + i * 0.1, y0 + j * 0.1)
                    if inner.contains(c):
                        cands.append((min(g.distance(c) for _, g in mine), c))
            cands.sort(key=lambda t: t[0])
            site = None
            for _, c in cands[:4000]:
                g = c.buffer(vd / 2)
                if not plane.contains(g) or novia.intersects(g):
                    continue
                if any(drills[k][0].distance(c) - drills[k][1] / 2 - vdr / 2 < 0.3 for k in dtree.query(c.buffer(1.0))):
                    continue
                if any(Point(q.x, q.y).distance(c) - vdr < 0.3 for q in placed):
                    continue
                # via-edge (owner 2026-10-05): the nearest-to-pad site was a pad-edge via; the gate's own rule
                # (via_site -> qa_copper_landing.padedge_class): wholly in a fitting own pad or >= PADEDGE_GAP_MM clear
                if via_site.site_faults(pix, {"x": c.x, "y": c.y, "d": vd, "drill": vdr, "net": net}):
                    continue
                bad = False
                for k in tree.query(g.buffer(3.0)):
                    kk, it, g2 = items[k]
                    if g.distance(g2) < place_gate.required(nn(net), nn(it["net"]), None, it["rec"].get("ref") if it["kind"] == "pad" else None,
                                                            "via", it["kind"]) - 1e-4:
                        bad = True
                        break
                if not bad:
                    site = c
                    break
            if site is None:
                # root cause: the router track(s) severing this fragment from the rest of the pour - unprotected
                # other-net tracks on the layer inside the gap between this fragment and another fill part of the net
                rest = unary_union([q for f in fills.get(L, []) for q in getattr(f, "geoms", [f]) if not q.equals(frag)])
                gap = frag.buffer(0.6).intersection(rest.buffer(0.6)) if not rest.is_empty else None
                cut = []
                if gap is not None and not gap.is_empty:
                    for k in tree.query(gap):
                        kk, it, g2 = items[k]
                        if kk[0] == "trk" and it["rec"]["layer"] == L and g2.intersects(gap) and RU.why_protected("trk", it["rec"]) in (None, "old base"):
                            cut.append(kk[1])
                for u in dict.fromkeys(cut):
                    if u not in ripped:
                        ripped[u] = {"kind": "trk", "uuid": u, "net": nn(cu.items[("trk", u)]["net"])["name"],
                                     "why": [f"pour_stitch: severs a {a.net} {L} fragment from its pour"]}
                report.append({"layer": L, "pads": [f"{p['ref']}.{p['num']}" for p, _ in mine][:4],
                               "result": f"no legal site: {len(set(cut))} severing tracks ripped"})
                continue
            placed.append(site)
            add.append({"uuid": str(uuid.uuid5(NS, repr((round(site.x, 3), round(site.y, 3))))), "net": a.net,
                        "x": round(site.x, 3), "y": round(site.y, 3), "d": vd, "drill": vdr})
            report.append({"layer": L, "pads": [f"{p['ref']}.{p['num']}" for p, _ in mine][:4], "via": [round(site.x, 3), round(site.y, 3)]})
    json.dump({"moves": {}, "delete": list(ripped.values()), "add": {"tracks": [], "vias": add}, "report": report,
               "dead_fragments": dead}, open(a.out, "w"), indent=1)
    print(f"pour_stitch {a.net}: {len(add)} stitching vias, {sum(1 for r in report if 'result' in r)} fragments without a site, "
          f"{len(ripped)} severing tracks ripped, {dead} dead fragments (pad-less, via-less: KiCad island removal drops them at refill)")
    for r in report:
        print("  ", r)


if __name__ == "__main__":
    main()
