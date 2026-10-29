# ported from din-relay-8ch/tools/pfr2/via_merge.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Merge same-net NEW vias that violate hole-to-hole (0.3 mm edge to edge) in a pfr2 plan (CPython).

  python via_merge.py PLAN.json OUT_PLAN.json
For each offending pair (A kept, B removed - B = the later one): every plan track with an end at B's centre gets a
short same-net stub on its layer from B's centre to A's centre (width = that track's width); B is deleted. A spans
F..B, so every layer B served is still joined. Run plan_check.py afterwards (the stubs are checked like any track).
"""
import json
import math
import sys

P = json.load(open(sys.argv[1]))
vias = P["vias"]
removed = set()
stubs = []
for i in range(len(vias)):
    if i in removed:
        continue
    for j in range(i + 1, len(vias)):
        if j in removed or vias[i]["net"] != vias[j]["net"]:
            continue
        a, b = vias[i], vias[j]
        gap = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) - a["drill"] / 2 - b["drill"] / 2
        if gap >= 0.3 - 1e-4:
            continue
        removed.add(j)
        if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < 1e-6:
            continue                          # coincident: B's track ends already touch A (no zero-length stub)
        for t in P["tracks"]:
            if t["net"] != b["net"]:
                continue
            for end in ("s", "e"):
                if abs(t[end][0] - b["x"]) < 1e-3 and abs(t[end][1] - b["y"]) < 1e-3:
                    stubs.append({"net": b["net"], "layer": t["layer"], "s": [b["x"], b["y"]], "e": [a["x"], a["y"]],
                                  "w": t["w"]})
        if a.get("drop") or b.get("drop"):
            a["drop"] = True
P["vias"] = [v for k, v in enumerate(vias) if k not in removed]
# de-duplicate stubs (both ends of a pair may be found twice)
seen, uniq = set(), []
for s in stubs:
    key = (s["layer"], tuple(s["s"]), tuple(s["e"]))
    if key not in seen:
        seen.add(key)
        uniq.append(s)
P["tracks"] += uniq
json.dump(P, open(sys.argv[2], "w"), indent=1)
print(f"merged {len(removed)} vias, added {len(uniq)} stubs")
