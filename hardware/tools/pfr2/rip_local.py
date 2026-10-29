# ported from din-relay-8ch/tools/pfr2/rip_local.py, 2026-10-27 (SBC-1: rip_region shim, SBC-1 classes, LOCKED copper never ripped; --island paths need DIN-8R m1_protect.static_cages and are not used)
"""Local rip-up for caged joins (CPython): from a pfr2 plan's fail_detail, rip the copper of ripable nets that lies
near the caged pads, so the next pfr2 run can route both the caged joins and the ripped nets.

  python rip_local.py GEOM.json PLAN.json OUT_PLAN.json [--radius 2.5] [--prev PREV_RIP.json]

Ripable = signal classes (SELV, Default) not in rip_region.KEEP_NETS, plus GND tracks (never GND vias: plane
stitches); every track / via of a ripable net that comes within --radius of a caged pad (all pads of the unreached
comps, and for power trees the pads of the unreached comps too) is deleted, and then that net's whole REGION copper
is deleted too (no half-ripped nets). --prev merges a previous rip plan (rounds accumulate on the same source board).
Output: rip_region-style plan (source, source_sha256, moves {}, delete [...]) for apply_plan.py.
"""
import argparse
import json
import sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from shapely.geometry import Point
from shapely.strtree import STRtree
import cugraph
from rip_region import REGION, KEEP_NETS, KEEP_CLASSES

RIP_CLASSES = {"SELV", "Default", "Rail", "Audio", "Power"}   # SBC-1 signal + small-current classes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--radius", type=float, default=2.5)
    ap.add_argument("--prev")
    ap.add_argument("--island", action="store_true", help="M1 lead decision 2026-10-04: also rip ISLAND-class copper "
                    "that cages a pad (m1_protect.Rule: never plane stitches, force / HV, NT1, rails, Kelvin pairs)")
    ap.add_argument("--old-base", default="", help="with --island: the old protected base (m1_protect)")
    ap.add_argument("--cage-rails", action="store_true", help="with --island: rail-lane router copper in a cage wall is "
                    "ripped (re-routed first and frozen by pfr2)")
    ap.add_argument("--cage-coil", action="store_true", help="with --island: COIL tracks in a cage wall are ripped and "
                    "re-routed (lead-approved; force / HV stays never-rip)")
    ap.add_argument("--cage-selv", action="store_true", help="with --island: SELV / POWER_SELV / Default TRACKS of the "
                    "start board that form a cage wall are ripped too (lead approval needed; COIL / force / HV / GND "
                    "vias and the m1_protect never-rip set stay); move_rip --allow-cage passes them")
    a = ap.parse_args()
    G = cugraph.load(a.geom)
    P = json.load(open(a.plan))
    nets = {int(k): v for k, v in G["nets"].items()}
    pads = {f"{p['ref']}.{p['num']}": p for p in G["pads"]}
    caged = set()
    for fd in P.get("fail_detail", []):
        for grp in (fd.get("left") or ([fd["pads"]] if "pads" in fd else [])):
            caged |= set(grp)
    pts = [Point(pads[c]["x"], pads[c]["y"]) for c in caged if c in pads]
    cu = cugraph.Copper(G)
    items = [(k, it) for k, it in cu.items.items() if it["kind"] in ("trk", "via")]

    def ripable(it):
        if it["rec"].get("locked"):
            return False                         # SBC-1: power_copper / EP vias (LOCKED) never ripped
        nm, cls = nets[it["net"]]["name"], nets[it["net"]]["class"]
        if nm == "GND":
            return it["kind"] == "trk"
        return cls in RIP_CLASSES and cls not in KEEP_CLASSES and nm not in KEEP_NETS
    geoms = [list(it["geo"].values())[0] for _, it in items]
    tree = STRtree(geoms)
    hit_nets = set()
    for pt in pts:
        for j in tree.query(pt.buffer(a.radius)):
            k, it = items[j]
            if ripable(it) and geoms[j].distance(pt) <= a.radius:
                hit_nets.add(it["net"])
    dele = {}
    for k, it in items:
        if it["net"] in hit_nets and ripable(it):
            g = list(it["geo"].values())[0]
            if REGION.contains(g.centroid):
                dele[k[1]] = {"kind": k[0], "uuid": k[1], "net": nets[it["net"]]["name"], "why": ["rip-local"]}
    kelvin_cage, isl_nets, static_cage_pads = [], set(), []
    if a.island:
        # ISLAND items within --radius of a caged pad that m1_protect does not protect are ripped (+ the dangling copper
        # they leave); a Kelvin item in a cage is reported, not ripped
        from m1_protect import Rule
        RU = Rule(G, a.old_base or None)
        adj = cu.graph()
        from m1_protect import static_cages
        # candidates: every pad of an open join of this board (pfr2's forest fail_detail names the SEED component of a
        # tree that failed, which is usually the free side - M1r-s1: X1.3 recorded, U19.18 caged) + the fail_detail pads
        from open_joins import open_joins
        cand = set(caged)
        for j in open_joins(G):
            cand |= {j["a"], j["b"]}
        cages = static_cages(G, cu, sorted(cand), radius=a.radius)
        seeds, selv_seeds = set(), set()
        for cname, wall in cages.items():
            for k in wall:
                it = cu.items[k]
                if k[0] not in ("trk", "via"):
                    continue                         # pads / pours in a wall stay (placement / force copper)
                n = nets[it["net"]]
                if n["class"] != "ISLAND":
                    if a.cage_selv and k[0] == "trk" and n["class"] in ("SELV", "POWER_SELV", "Default")                             and RU.why_protected(k[0], it["rec"]) in (None, "old base"):
                        selv_seeds.add(k)
                    # (lead 2026-10-04 d) COIL tracks in a cage wall are re-routed (not deleted: the router re-takes
                    # them with their class); force / HV copper stays never-rip
                    if a.cage_coil and k[0] == "trk" and n["class"] == "COIL":
                        selv_seeds.add(k)
                    continue
                why = RU.why_protected(k[0], it["rec"])
                if why == "rail lane" and a.cage_rails and k[0] in ("trk", "via"):
                    selv_seeds.add(k)                # (lead 2026-10-04 b) rails re-routed first and frozen next pass
                    continue
                if why is None:
                    seeds.add(k)
                elif why == "Kelvin":
                    kelvin_cage.append({"pad": cname, "net": n["name"], "item": k[1]})
        static_cage_pads = sorted(cages)
        # the cage items themselves, then the copper they leave dangling is peeled leaf by leaf (an unprotected track /
        # via of a ripped net with fewer than two remaining same-net neighbours - pads, planes, copper): no loose stub
        # is left, nothing beyond the cage's own branch is taken
        gone = set(seeds)
        hit_isl = {cu.items[k]["net"] for k in seeds}
        while True:
            more = set()
            for u, it in cu.items.items():
                if u in gone or it["kind"] not in ("trk", "via") or it["net"] not in hit_isl:
                    continue
                if RU.why_protected(it["kind"], it["rec"]) is not None:
                    continue
                nb = [w for w in adj[u] if w not in gone and cu.items[w]["net"] == it["net"]]
                if len(nb) < 2:
                    more.add(u)
            if not more:
                break
            gone |= more
        for u in selv_seeds:
            dele[u[1]] = {"kind": u[0], "uuid": u[1], "net": nets[cu.items[u]["net"]]["name"],
                          "why": ["rip-local selv cage wall"]}
        for u in gone:
            isl_nets.add(nets[cu.items[u]["net"]]["name"])
            dele[u[1]] = {"kind": u[0], "uuid": u[1], "net": nets[cu.items[u]["net"]]["name"],
                          "why": ["rip-local island cage"]}
    if a.prev:
        for d in json.load(open(a.prev))["delete"]:
            dele.setdefault(d["uuid"], d)
    plan = {"source": G["board"], "source_sha256": G["sha256"], "moves": {}, "delete": list(dele.values()),
            "ripped_nets": sorted(nets[n]["name"] for n in hit_nets), "caged_pads": sorted(caged),
            "island_ripped_nets": sorted(isl_nets), "kelvin_cage": kelvin_cage,
            "static_cage_pads": static_cage_pads if a.island else []}
    json.dump(plan, open(a.out, "w"), indent=1)
    print(f"caged pads {len(caged)}, ripped nets {len(hit_nets)}: {plan['ripped_nets']}, island cage nets "
          f"{len(isl_nets)}, Kelvin items in a cage {len(kelvin_cage)}, delete {len(dele)}")


if __name__ == "__main__":
    main()
