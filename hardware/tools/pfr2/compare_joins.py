# ported from din-relay-8ch/tools/pfr2/compare_joins.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""open joins of several geoms: total, by open_groups group, and with a pad in the logic block (x 160-210)"""
import sys
sys.path.insert(0, "C:/work/skeeball-controller/tools/pfr2")
sys.path.insert(0, "C:/work/skeeball-controller/tools/pfr2")
from collections import Counter
import cugraph
from open_joins import open_joins
from open_groups import group

rows = []
for arg in sys.argv[1:]:
    tag, path = arg.split("=", 1)
    G = cugraph.load(path)
    nets = {v["name"]: v for v in G["nets"].values()}
    J = open_joins(G)
    g = Counter(group(j["net"], nets[j["net"]].get("class", ""), nets[j["net"]].get("classes", [])) for j in J)
    blk = [j for j in J if any(160 <= x <= 210 for x in (j["ax"], j["bx"]))]
    gb = Counter(group(j["net"], nets[j["net"]].get("class", ""), nets[j["net"]].get("classes", [])) for j in blk)
    rows.append((tag, len(J), len(blk), dict(g), dict(gb)))
keys = sorted({k for r in rows for k in r[3]})
print(f"{'board':14s} {'total':>5s} {'block':>5s} " + " ".join(f"{k[:12]:>12s}" for k in keys))
for tag, n, nb, g, gb in rows:
    print(f"{tag:14s} {n:5d} {nb:5d} " + " ".join(f"{g.get(k, 0):>5d}({gb.get(k, 0):>3d})" for k in keys))
print("(group: total(of them in the logic block x 160-210))")
