# ported from din-relay-8ch/tools/pfr2/cugraph.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Copper connectivity graph from a dump_geom.py JSON (CPython + shapely).

Nodes: ("pad", uuid), ("trk", uuid), ("via", uuid), ("zone", uuid, layer, i).
Two items of the SAME net are connected when their copper on a common layer intersects (vias/THT pads span layers).
"""
import json
from collections import defaultdict

from shapely.geometry import Polygon, LineString, Point, MultiPolygon
from shapely.strtree import STRtree
from shapely.ops import unary_union

INNER_PLANES = ("In1.Cu",)  # SBC-1 4-layer (pass 5): In1.Cu GND plane (DIN-8R: In1 / In4)


def ring_poly(rec):
    try:
        p = Polygon(rec["outline"], [h for h in rec["holes"] if len(h) >= 3])
        if not p.is_valid:
            p = p.buffer(0)
        return p
    except Exception:
        return Polygon()


def load(path):
    return json.load(open(path, encoding="utf-8"))


def phys_order(layers):
    """Physical copper stack order (KiCad 10 layer ids are F=0, B=2, In1=4, ...)."""
    def key(n):
        if n == "F.Cu":
            return -1
        if n == "B.Cu":
            return 10 ** 6
        return int(n[2:].split(".")[0])
    return sorted(layers, key=key)


def via_layers(v, layers):
    layers = phys_order(layers)
    i0, i1 = layers.index(v["top"]), layers.index(v["bot"])
    return layers[min(i0, i1):max(i0, i1) + 1]


class Copper:
    """Per-layer copper items with shapely geometry."""

    def __init__(self, g, nets_filter=None):
        self.g = g
        self.layers = phys_order(g["layers"])
        self.items = {}      # key -> dict(net, layer->geom, kind, rec)
        nf = nets_filter
        for p in g["pads"]:
            if nf is not None and p["net"] not in nf:
                continue
            geo = {}
            for L, shp in p["shapes"].items():
                polys = [ring_poly(r) for r in shp]
                geo[L] = unary_union(polys) if len(polys) > 1 else (polys[0] if polys else Polygon())
            self.items[("pad", p["uuid"])] = {"net": p["net"], "geo": geo, "kind": "pad", "rec": p}
        for t in g["tracks"]:
            if nf is not None and t["net"] not in nf:
                continue
            ls = LineString([t["s"], t["e"]]) if t["s"] != t["e"] else Point(t["s"])
            self.items[("trk", t["uuid"])] = {"net": t["net"], "geo": {t["layer"]: ls.buffer(t["w"] / 2, 16)},
                                             "kind": "trk", "rec": t}
        for v in g["vias"]:
            if nf is not None and v["net"] not in nf:
                continue
            c = Point(v["x"], v["y"]).buffer(v["d"] / 2, 16)
            self.items[("via", v["uuid"])] = {"net": v["net"], "geo": {L: c for L in via_layers(v, self.layers)},
                                             "kind": "via", "rec": v}
        for z in g["zones"]:
            if z["rule_area"] or (nf is not None and z["net"] not in nf):
                continue
            for L, fills in z.get("fills", {}).items():
                for i, r in enumerate(fills):
                    self.items[("zone", z["uuid"], L, i)] = {"net": z["net"], "geo": {L: ring_poly(r)}, "kind": "zone",
                                                             "rec": z}

    def graph(self):
        """Adjacency for same-net intersecting items."""
        adj = defaultdict(set)
        bylayer = defaultdict(list)
        for k, it in self.items.items():
            for L, geo in it["geo"].items():
                if not geo.is_empty:
                    bylayer[L].append((k, it["net"], geo))
        for L, lst in bylayer.items():
            tree = STRtree([x[2] for x in lst])
            for i, (k, net, geo) in enumerate(lst):
                for j in tree.query(geo):
                    if j <= i:
                        continue
                    k2, net2, geo2 = lst[j]
                    if net2 == net and geo.intersects(geo2):
                        adj[k].add(k2)
                        adj[k2].add(k)
        for k in self.items:
            adj.setdefault(k, set())
        return adj


def prune_private(adj, items, removed_pads, allow=None):
    """Remove `removed_pads`, then propagate: a track/via adjacent to removed copper is dropped when it has <= 1
    surviving neighbour (it only served the removed pads). Pre-existing dangling items elsewhere are untouched.
    Returns the set of pruned track/via keys."""
    removed = set(removed_pads)
    alive = set(adj) - removed
    pruned = set()
    stack = [n for r in removed for n in adj[r]]
    while stack:
        k = stack.pop()
        if k not in alive or items[k]["kind"] not in ("trk", "via"):
            continue
        if allow is not None and not allow(k):
            continue
        if len(adj[k] & alive) > 1:
            continue
        alive.discard(k)
        pruned.add(k)
        stack.extend(n for n in adj[k] if n in alive)
    return pruned
