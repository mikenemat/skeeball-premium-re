# ported from din8r-chassis-thermal/scripts/cu_cleanup/smooth.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R tools/pfr2/smooth.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN)
"""Post-route smoothing of router-made tracks (dump_geom JSONs) -> a replace plan (scripts/copper_cleanup.py step).

  import smooth; smooth.plan(G, base_ids, exclude=lambda net_rec: bool)

CT adaptation (2026-10-17): base_ids = the LOCKED tracks / vias (CT's deliberate hand copper from eco_advqa2.py /
board_finish.py: never touched); every unlocked track is router copper. Clearance = cu_cleanup/place_gate.required
(net-class clearance, pad overrides, PRI-SEC 2.00 mm on the same layer AND laterally on every other layer, CT's
qa_crosslayer rule). Fixed zone fills (power-cell pours ECO_* / VSS_PAD_B, never pushed back) are obstacles like the
parent's force pours; every other pour is refilled around new copper. Edge / hole clearances from the board's rules.

Per net and layer, router-made tracks of one width are chained between junctions (pads, vias, track ends of degree
!= 2, width changes); each chain is string-pulled: from each kept point jump to the farthest later point whose
octilinear path (same width) keeps the clearance to all foreign copper (the board's AND every replacement segment
already planned for another chain), the rule-area keep-outs of that layer, every rule area the old chain did not
already cross, NPTH and the board edge. Collinear points are then merged (a chain of >= 2 collinear segments becomes
one). Every same-net contact of the old chain must survive. Copper of the same net is never a conflict.
"""
import hashlib
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shapely.geometry import LineString, Point  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402
import cugraph  # noqa: E402
import place_gate  # noqa: E402

SAFE = 0.006
OUTER = ("F.Cu", "B.Cu")


def fixed_zone(z):
    """power-cell copper the cleanup never pushes back (CT brief: ECO_* zones and VSS_PAD_B are never removed)"""
    nm = z.get("name") or ""
    return not z.get("rule_area") and (nm.startswith("ECO_") or nm == "VSS_PAD_B")


def key(p):
    return (round(p[0], 4), round(p[1], 4))


OCTILINEAR = True       # string-pull to 0 / 45 / 90 deg segments
OCT_TOL = 1e-3          # mm: |dx| or |dy| or ||dx| - |dy|| below this is octilinear
FREE_MAX = 1.0          # a free-angle replacement segment only below this length (and only when no octilinear path)
DEV_MAX = 1.0           # a replacement path stays within this of the original chain (Hausdorff)


def is_octi(a, b):
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    return dx < OCT_TOL or dy < OCT_TOL or abs(dx - dy) < OCT_TOL


def octi_paths(a, b):
    """candidate replacements a -> b (points after a): the straight segment when octilinear, else the two 45 + 0 / 90
    L paths (diagonal first, orthogonal first), then a free-angle straight when shorter than FREE_MAX"""
    if math.dist(a, b) < 1e-9:
        return []
    if is_octi(a, b):
        return [[b]]
    dx, dy = b[0] - a[0], b[1] - a[1]
    m = min(abs(dx), abs(dy))
    d = (math.copysign(m, dx), math.copysign(m, dy))
    c1 = (round(a[0] + d[0], 4), round(a[1] + d[1], 4))
    c2 = (round(b[0] - d[0], 4), round(b[1] - d[1], 4))
    out = [[c1, b], [c2, b]]
    if math.dist(a, b) < FREE_MAX:
        out.append([b])
    return out


def same_dir(u, v):
    nu, nv = math.hypot(*u), math.hypot(*v)
    return nu > 1e-9 and nv > 1e-9 and abs(u[0] * v[1] - u[1] * v[0]) / (nu * nv) < 2e-2 and u[0] * v[0] + u[1] * v[1] > 0


def joint_deg(a, j, b):
    u, v = (a[0] - j[0], a[1] - j[1]), (b[0] - j[0], b[1] - j[1])
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu < 1e-9 or nv < 1e-9:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))))


def collinear_merge(pts, tol=1e-4):
    """drop interior points that lie on the straight line of their neighbours (same copper, fewer segments)"""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        L = math.dist(a, c)
        if L > 1e-9:
            cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / L
            dot = (b[0] - a[0]) * (c[0] - a[0]) + (b[1] - a[1]) * (c[1] - a[1])
            if cross < tol and 0 <= dot <= L * L:
                continue
        out.append(b)
    out.append(pts[-1])
    return out


def chain_key(net_name, L, uuids):
    """a smoothed chain's stable edit key (copper_cleanup arbitration: blocked chains are skipped on replay)"""
    return ("SMOOTH", net_name, L, hashlib.sha1("|".join(sorted(uuids)).encode()).hexdigest()[:16])


def plan(G, base_ids, exclude=None, log=print, skip_track=None, blocked=(), groups=None):
    """-> (delete uuids, add track dicts {net(name), layer, s, e, w}); `exclude(net_rec)` True = never touched;
    `skip_track(track, net_rec)` True = that track is never touched; `blocked`: chain_key()s never smoothed; `groups`
    (a list): receives (chain_key, delete uuids, add dicts) per smoothed chain"""
    nets = {int(k): v for k, v in G["nets"].items()}
    mine = [t for t in G["tracks"] if t["uuid"] not in base_ids and not t.get("locked")
            and not (exclude and exclude(nets.get(t["net"], {"name": "", "class": "Default"})))
            and not (skip_track and skip_track(t, nets.get(t["net"], {"name": ""})))]
    log(f"smooth: router-made candidate tracks {len(mine)} of {len(G['tracks'])}")
    pad_clr = {p["uuid"]: p.get("clr") for p in G["pads"]}
    rules = G.get("rules", {})
    edge_clr = rules.get("edge_clearance", 0.3)
    hole_clr = rules.get("hole_clearance", 0.25)

    def need(a, b, k=None):
        if b is None:
            return nets[a].get("clearance") or 0.15
        oc = pad_clr.get(k[1]) if k is not None and k[0] == "pad" else None
        return place_gate.required(nets[a], nets[b], clr_b=oc)

    cu = cugraph.Copper(G)
    zrec = {z["uuid"]: z for z in G["zones"]}
    obs = defaultdict(list)
    side_items = []                                  # (geom, side, key): every sided copper item, any layer
    for k, it in cu.items.items():
        sd = nets.get(it["net"], {}).get("side")
        for L, g in it["geo"].items():
            if g.is_empty:
                continue
            if sd is not None:
                side_items.append((g, sd, k))
            if it["kind"] == "zone" and not fixed_zone(zrec[k[1]]):
                continue          # signal / plane pours are refilled around tracks
            obs[L].append((g, it["net"] or None, k))
    trees = {L: STRtree([o[0] for o in lst]) for L, lst in obs.items()}
    side_tree = STRtree([x[0] for x in side_items]) if side_items else None
    areas = defaultdict(list)                        # layer -> [(rule area poly, hard keep-out?)]
    for z in G["zones"]:
        if z["rule_area"]:
            for L in z.get("layers", []):
                for o in z["outline"]:
                    areas[L].append((cugraph.ring_poly(o), bool(z.get("no_tracks"))))
    atree = {L: STRtree([a[0] for a in lst]) for L, lst in areas.items()}
    edge = unary_union([cugraph.ring_poly(o) for o in G["outline"]]).boundary
    npth = unary_union([Point(p["x"], p["y"]).buffer(max(p["drill"]) / 2) for p in G["pads"]
                        if p["drill"] and not p["shapes"]])
    added = defaultdict(lambda: defaultdict(list))   # layer -> grid cell -> [(geom, net)] planned replacements
    GR = 2.0
    REACH = place_gate.ISO_MM + 0.6

    def cells(g):
        x0, y0, x1, y1 = g.bounds
        return [(i, j) for i in range(int(x0 // GR) - 1, int(x1 // GR) + 2) for j in range(int(y0 // GR) - 1, int(y1 // GR) + 2)]

    def legal(n, L, a, b, w, skip, crossed):
        seg = LineString([a, b])
        g = seg.buffer(w / 2)
        if seg.distance(edge) < edge_clr + w / 2 or (not npth.is_empty and seg.distance(npth) < hole_clr + w / 2):
            return False
        for j in atree[L].query(g) if L in atree else ():
            poly, hard = areas[L][j]
            if poly.intersects(g) and (hard or j not in crossed):
                return False
        for j in trees[L].query(g.buffer(REACH)):
            og, on, k = obs[L][j]
            if on == n or k in skip:
                continue
            if seg.distance(og) - w / 2 < need(n, on, k) + SAFE:
                return False
        sd = nets[n].get("side")
        if sd is not None and side_tree is not None:         # PRI-SEC lateral distance on every layer pair
            for j in side_tree.query(g, predicate="dwithin", distance=place_gate.ISO_MM + SAFE):
                og, osd, k = side_items[j]
                if osd != sd and k not in skip:
                    return False
        seen = set()
        for c in cells(g.buffer(REACH)) if added[L] else ():
            for og, on in added[L].get(c, ()):
                if on == n or id(og) in seen:
                    continue
                seen.add(id(og))
                if seg.distance(og) - w / 2 < need(n, on) + SAFE:
                    return False
        return True

    plan_del, plan_add = [], []
    by = defaultdict(list)
    for t in mine:
        by[(t["net"], t["layer"])].append(t)
    allby = defaultdict(list)
    for t in G["tracks"]:
        allby[(t["net"], t["layer"])].append(t)
    vias_by = defaultdict(set)
    vias_geo = defaultdict(list)
    vias_ctr = defaultdict(list)
    for v in G["vias"]:
        vias_by[v["net"]].add(key((v["x"], v["y"])))
        vias_geo[v["net"]].append(Point(v["x"], v["y"]).buffer(v["d"] / 2))
        vias_ctr[v["net"]].append(Point(v["x"], v["y"]))
    pads_by = defaultdict(list)
    for k, it in cu.items.items():
        if it["kind"] == "pad":
            for L, g in it["geo"].items():
                pads_by[(it["net"], L)].append(g)
    for (n, L), ts in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        deg = defaultdict(int)
        for t in allby[(n, L)]:
            deg[key(t["s"])] += 1
            deg[key(t["e"])] += 1
        pins = vias_by[n]
        pad_geo = pads_by[(n, L)]
        adj = defaultdict(list)
        for t in ts:
            adj[key(t["s"])].append(t)
            adj[key(t["e"])].append(t)
        used = set()

        vdiscs = vias_geo[n]
        oends = [(Point(t["s"]), Point(t["e"]), t) for t in allby[(n, L)]]
        olines = [(LineString([t["s"], t["e"]]) if t["s"] != t["e"] else Point(t["s"]), t) for t in allby[(n, L)]]
        otree = STRtree([x[0] for x in olines])
        etree = STRtree([q for a_, b_, t in oends for q in (a_, b_)])
        eown = [t for a_, b_, t in oends for q in (a_, b_)]

        def is_junction(p):
            # the joint semantics of qa_copper_landing: a vertex inside (or within 0.01 mm of) a same-net pad or via
            # disc, or where another same-net track's end lands, anchors the chain there and stays a vertex
            if deg[p] != 2 or p in pins:
                return True
            q = Point(p)
            if any(g.distance(q) < 0.01 for g in pad_geo) or any(d.distance(q) < 1e-6 for d in vdiscs):
                return True
            # a T-joint onto another same-net track, or another track's end merging with the vertex; tracks of the
            # same run near the vertex (walking the chain up to ~1.5 x width) are the run itself, not a joint
            own = set()
            for t0_ in adj[p]:
                cur, node, run = t0_, p, 0.0
                while cur is not None and run <= 1.5 * cur["w"] and id(cur) not in own:
                    own.add(id(cur))
                    nxt_node = key(cur["e"]) if key(cur["s"]) == node else key(cur["s"])
                    run += math.dist(cur["s"], cur["e"])
                    cand = [x for x in adj[nxt_node] if x is not cur]
                    cur, node = (cand[0], nxt_node) if len(cand) == 1 else (None, None)
            for j in otree.query(q.buffer(0.6)):
                g, t = olines[j]
                if id(t) not in own and g.distance(q) <= t["w"] / 2 + 1e-6:
                    return True
            for j in etree.query(q.buffer(0.6)):
                t = eown[j]
                if id(t) not in own and etree.geometries[j].distance(q) <= t["w"] / 2 + 1e-6:
                    return True
            return False
        for t0 in sorted(ts, key=lambda t: t["uuid"]):
            if t0["uuid"] in used:
                continue
            chain = [t0]
            used.add(t0["uuid"])
            ends = [key(t0["s"]), key(t0["e"])]
            for side in (0, 1):
                p = ends[side]
                while not is_junction(p):
                    nxt = [t for t in adj[p] if t["uuid"] not in used and abs(t["w"] - t0["w"]) < 1e-6]
                    if len(nxt) != 1:
                        break
                    t = nxt[0]
                    used.add(t["uuid"])
                    chain.append(t)
                    p = key(t["e"]) if key(t["s"]) == p else key(t["s"])
                ends[side] = p
            if len(chain) < 2:
                continue
            seg_by = defaultdict(list)
            for t in chain:
                seg_by[key(t["s"])].append(t)
                seg_by[key(t["e"])].append(t)
            pts, cur, seen_t = [ends[0]], ends[0], set()
            while True:
                nx = [t for t in seg_by[cur] if t["uuid"] not in seen_t]
                if not nx:
                    break
                t = nx[0]
                seen_t.add(t["uuid"])
                cur = key(t["e"]) if key(t["s"]) == cur else key(t["s"])
                pts.append(cur)
            if len(seen_t) != len(chain) or len(pts) < 3 or pts[0] == pts[-1]:
                continue
            ckey = chain_key(nets[n]["name"], L, [t["uuid"] for t in chain])
            if ckey in blocked:
                continue
            w = t0["w"]
            skip = {("trk", t["uuid"]) for t in chain}
            old_g = unary_union([LineString([t["s"], t["e"]]).buffer(t["w"] / 2) for t in chain])
            crossed = {j for j in (atree[L].query(old_g) if L in atree else ()) if areas[L][j][0].intersects(old_g)}
            chain_ids0 = {t["uuid"] for t in chain}

            def overlaps_own(a_, b_):
                """the new segment runs along / over another same-net track of this layer (doubled copper: DUP / FOLD)
                other than at its own end points"""
                ln = LineString([a_, b_])
                for j_ in otree.query(ln.buffer(w)):
                    g_, t_ = olines[j_]
                    if t_["uuid"] in chain_ids0:
                        continue
                    if any(min(math.dist(q_, a_), math.dist(q_, b_)) < 1e-3 for q_ in (t_["s"], t_["e"])):
                        continue
                    if g_.distance(ln) < (w + t_["w"]) / 2 - 1e-3:
                        return True
                return False
            out_pts = [pts[0]]
            i = 0
            # a chain end on a pad keeps the router's pad exit direction (qa_layout_quality PAD-AXIS)
            at_pad = [any(g.distance(Point(q)) < 0.01 for g in pad_geo) for q in (pts[0], pts[-1])]
            d_first = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            d_last = (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
            while i < len(pts) - 1:
                if not OCTILINEAR:
                    j = min(len(pts) - 1, i + 80)          # bounded look-ahead keeps long chains fast
                    while j > i + 1 and not legal(n, L, pts[i], pts[j], w, skip, crossed):
                        j -= 1
                    out_pts.append(pts[j])
                    i = j
                    continue
                # octilinear pull: the farthest later point reachable by a straight octilinear segment or a 2-segment
                # diagonal + orthogonal L, legal, within DEV_MAX of the old path and with no joint below 90 deg; a
                # free-angle straight only when it is < FREE_MAX long and no octilinear path exists; else the
                # original segment stays
                prev = out_pts[-2] if len(out_pts) >= 2 else None
                got = None
                for j in range(min(len(pts) - 1, i + 80), i, -1):
                    for path in octi_paths(pts[i], pts[j]):
                        seq = [pts[i]] + path
                        if prev is not None and joint_deg(prev, seq[0], seq[1]) < 90.0 - 1e-6:
                            continue
                        if any(joint_deg(seq[k - 1], seq[k], seq[k + 1]) < 90.0 - 1e-6 for k in range(1, len(seq) - 1)):
                            continue
                        if i == 0 and at_pad[0] and not same_dir(d_first, (seq[1][0] - seq[0][0], seq[1][1] - seq[0][1])):
                            continue
                        if j == len(pts) - 1 and at_pad[1] and \
                                not same_dir(d_last, (seq[-1][0] - seq[-2][0], seq[-1][1] - seq[-2][1])):
                            continue
                        if j > i + 1 and LineString(pts[i:j + 1]).hausdorff_distance(LineString(seq)) > DEV_MAX:
                            continue
                        if any(overlaps_own(a_, b_) for a_, b_ in zip(seq, seq[1:])):
                            continue
                        if all(legal(n, L, a_, b_, w, skip, crossed) for a_, b_ in zip(seq, seq[1:])):
                            got = (j, path)
                            break
                    if got:
                        break
                if got is None:
                    out_pts.append(pts[i + 1])
                    i += 1
                else:
                    out_pts += got[1]
                    i = got[0]
            out_pts = collinear_merge(out_pts)
            if len(out_pts) - 1 >= len(chain):
                continue
            # keep every same-net contact of the old chain (T-junctions onto its body, pads, vias, other tracks)
            new_g = unary_union([LineString([a_, b_]).buffer(w / 2) for a_, b_ in zip(out_pts, out_pts[1:])])
            chain_ids = {t["uuid"] for t in chain}
            lost = False
            for j in trees[L].query(old_g):
                og, on, k2 = obs[L][j]
                if on != n or (k2[0] == "trk" and k2[1] in chain_ids):
                    continue
                if og.intersects(old_g) and not og.intersects(new_g):
                    lost = True
                    break
            # T-joints (gate semantics): every other same-net track END lying on the old centreline (within w / 2)
            # must lie on the new one too
            if not lost:
                old_line = unary_union([LineString([t["s"], t["e"]]) for t in chain])
                new_line = LineString(out_pts)
                for a_, b_, t in oends:
                    if t["uuid"] in chain_ids:
                        continue
                    for q in (a_, b_):
                        if old_line.distance(q) <= w / 2 - 1e-4 and new_line.distance(q) > w / 2 - 1e-4:
                            lost = True
                            break
                    if lost:
                        break
            if not lost:
                # KiCad anchors: a same-net via whose centre lay on the old centreline, or a same-net pad holding an
                # old chain vertex, must keep that on the new path (copper overlap alone is not a KiCad connection)
                new_line = LineString(out_pts)
                old_line = unary_union([LineString([t["s"], t["e"]]) for t in chain])
                for vc in vias_ctr[n]:
                    if old_line.distance(vc) <= w / 2 - 1e-4 and new_line.distance(vc) > w / 2 - 1e-4:
                        lost = True
                        break
                if not lost:
                    for g in pad_geo:
                        if any(g.distance(Point(q)) < 1e-6 for q in pts) and \
                                not any(g.distance(Point(q)) < 1e-6 for q in out_pts):
                            lost = True
                            break
            if lost:
                continue
            plan_del += [t["uuid"] for t in chain]
            g_add = []
            for a_, b_ in zip(out_pts, out_pts[1:]):
                plan_add.append({"net": nets[n]["name"], "layer": L, "s": [a_[0], a_[1]], "e": [b_[0], b_[1]], "w": w})
                g_add.append(plan_add[-1])
                g = LineString([a_, b_]).buffer(w / 2)
                for c in cells(g):
                    added[L][c].append((g, n))
            if groups is not None:
                groups.append((ckey, [t["uuid"] for t in chain], g_add))
    log(f"smooth: deleted {len(plan_del)} segments, added {len(plan_add)}")
    return plan_del, plan_add
