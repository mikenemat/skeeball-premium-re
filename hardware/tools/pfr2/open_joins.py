# ported from din-relay-8ch/tools/pfr2/open_joins.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""List the open joins of a dump_geom board (CPython): per open net, the nearest pad pair between its copper
components (MST over components), with positions and distance.

  python open_joins.py GEOM.json [--box x0,y0,x1,y1] [--json OUT.json]
"""
import argparse
import collections
import json
import math
import sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import cugraph


def open_joins(G):
    nets = {int(k): v["name"] for k, v in G["nets"].items()}
    cu = cugraph.Copper(G)
    adj = cu.graph()
    comps = collections.defaultdict(list)
    seen = set()
    for k, it in cu.items.items():
        if k in seen or not it["net"]:
            continue
        comp, st = set(), [k]
        while st:
            u = st.pop()
            if u in comp:
                continue
            comp.add(u)
            st.extend(adj[u] - comp)
        seen |= comp
        pads = [cu.items[u]["rec"] for u in comp if cu.items[u]["kind"] == "pad"]
        if pads:
            comps[it["net"]].append(pads)
    out = []
    for n, cs in comps.items():
        if len(cs) < 2 or nets[n].startswith("unconnected"):
            continue
        rem, tree = list(range(1, len(cs))), [0]
        while rem:
            best = None
            for i in tree:
                for j in rem:
                    for p in cs[i]:
                        for q in cs[j]:
                            d = math.hypot(p["x"] - q["x"], p["y"] - q["y"])
                            if best is None or d < best[0]:
                                best = (d, j, p, q)
            tree.append(best[1])
            rem.remove(best[1])
            d, _, p, q = best
            out.append({"net": nets[n], "a": f"{p['ref']}.{p['num']}", "b": f"{q['ref']}.{q['num']}",
                        "ax": p["x"], "ay": p["y"], "bx": q["x"], "by": q["y"], "d": round(d, 2)})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("geom")
    ap.add_argument("--box", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    J = open_joins(cugraph.load(a.geom))
    if a.box:
        x0, y0, x1, y1 = map(float, a.box.split(","))
        J = [j for j in J if any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in ((j["ax"], j["ay"]), (j["bx"], j["by"])))]
    for j in sorted(J, key=lambda j: (j["net"], j["d"])):
        print(f"{j['net']:28s} {j['a']:>9s} ({j['ax']:7.2f},{j['ay']:6.2f}) -> {j['b']:>9s} ({j['bx']:7.2f},{j['by']:6.2f})  {j['d']:6.2f}")
    print("open joins", len(J), "nets", len({j['net'] for j in J}))
    if a.json:
        json.dump(J, open(a.json, "w"), indent=1)
