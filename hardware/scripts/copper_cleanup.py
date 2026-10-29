# ported from din8r-chassis-thermal/scripts/copper_cleanup.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R tools/pfr2/copper_cleanup.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN)
"""Copper cleanup for CT's routed boards: remove routing debris at its source, arbitrated by KiCad DRC and CT's
qa_copper_landing + qa_layout_quality (port of the DIN-8R copper_cleanup v2.1, 2026-10-05; owner: connected is not
clean).

  py scripts/local_run.py copper_cleanup.py BOARD.kicad_pcb REPORT.json [--max-rounds N] [--no-smooth] [--no-bare]
  py scripts/copper_cleanup.py BOARD.kicad_pcb REPORT.json [...]          (plain CPython: the same code)

BOARD is edited IN PLACE (pass a candidate copy; the caller keeps the original); its .kicad_pro must sit beside it (DRC,
net classes). Relative paths are project-root relative. Outputs next to REPORT: REPORT.json (before / after counts of
both gates and DRC, every edit, the blocked edits with reasons, unfixed items with reasons, per-step / per-replay
timing), REPORT.blocked.json (blocked edit keys, bound to the refilled input sha: a rerun on the same input starts from
them); REPORT.work/ (snapshots, plans, worker reports) is removed at the end. Exit 0 = no CLEAN / debris class left,
1 = some left (see the report), 2 = error. --max-rounds (default 2) bounds the fix-point rounds of the round steps and
of smoothing; --no-smooth skips smoothing; --no-bare keeps every VIA-BARE via.

Architecture (CT): this process never imports pcbnew. Every KiCad job is ONE subprocess with ONE pcbnew.LoadBoard
(KiCad 10 may return dead SWIG objects on a second LoadBoard): cu_cleanup/kicad_worker.py dump / apply / gate / lq
through scripts/local_run.py; DRC = `local_run.py --cli pcb drc --severity-all --format json`. The analysis runs on the
dump_geom dict in memory (cu_cleanup/cugraph, smooth, via_site, place_gate), kept in step with every native apply.

CT adaptation (2026-10-17):
  * ONE board kind "main", 4 copper layers; In1.Cu (GND / PRTN plane) is never routed: the cleanup only edits copper
    that exists, so nothing new lands there except the stitch vias' barrels.
  * LOCKED tracks / vias are deliberate hand copper (scripts/eco_advqa2.py / board_finish.py): NEVER deleted, moved,
    reshaped or widened (every detector skips them, commit() drops any edit that would, and the worker refuses).
    "Base geometry" (the parent's pre-route board) = the locked items: every unlocked track / via is router copper.
  * Zones are never deleted (the worker deletes only segment / arc / via items). Power-cell pours ECO_* / VSS_PAD_B are
    fixed obstacles (never pushed back by new copper); every other pour is refilled once at the end.
  * Rule areas (ISOLATION_BARRIER_PRI_SEC, TEMP_SENSOR_ISLAND, EDGE_KEEPOUT, ...) are hard keep-outs: new copper enters no
    rule area its old copper did not already cross, and never a no-track / no-via area.
  * Clearance = cu_cleanup/place_gate.required: CT has no .kicad_dru, so the larger net-class clearance (0.15 mm) or
    pad override, raised to the PRI-SEC isolation distance (2.00 mm, CLAUDE.md / qa_crosslayer) on the same layer AND
    laterally on every other layer.
  * No force nets (board_const.FORCE_NETS is empty): the parent's LINE / NEUTRAL / COM / OUT force logic, --reserve,
    --rips (legacy DRC / width rips), Y600 and MH keep-outs, the UI kind and the m1_protect smoothing exclusions are
    dropped. CT's differential pairs (TRACK-JOG protected by name) are smoothed like any net; the arbiter guards their
    DIFFPAIR findings.

Work list = the gates' own findings, re-read during the run (qa_copper_landing with the TRACK-JOG screen skipped for
the CLEAN classes, qa_layout_quality for TRACK-FOLD / ACUTE / VIA-HOP / POUR-STITCH). Steps (each one native save; a
snapshot before each):
  jog         TRACK-JOG: the copper gate's own CLEAN shortcut for each unprotected staircase site of the refilled input
              (the 3-segment chain replaced by the gate's path), re-checked against the clearance model.
  rounds      TRACK-DUP (joint guard; zero-length pieces held by a via / pad too) + TRACK-ORPHAN deletes (with the
              orphan's own vias on routed nets) + router segments doubling locked copper (within NEAR_DUP_MM); VIA-PADEDGE via
              moves (clear of every SMD pad by PADEDGE_GAP_MM + a stub to the pad centre, or wholly inside a fitting own
              pad; old track ends re-terminated); TRACK-WIDTH widening to current_budget.required_width (the gate's
              "required") where legal (<= NECK_MM necks at narrower pads); PAD-CENTRE extension (trace ends at the pad
              centre); TRACK-END completion (a free end <= ENDS_MAX_MM short of its pad / via / track runs on to it;
              KiCad-dangling micro spurs deleted) -> to a fixpoint.
  smooth      string-pull (octilinear) + collinear merge of router chains (staircases, TRACK-JOG; owner: staircases are
              worse than corners), then the debris / centre steps it re-exposes.
  lqfix       TRACK-FOLD collapses / trims, ACUTE corner cuts (octilinear first) or turn re-anchors, VIA-HOP pair
              removal, LOOP doubled-copper collapses; knots of short doubled segments re-drawn as octilinear paths.
  dead        (after each lqfix) a single-layer track cluster held by one pad only (no via, no own fill) goes whole.
  starved     DRC starved_thermal: a stub from the pad centre into its own pour.
  stitch      POUR-STITCH: through stitch vias where a fragment is short of the density (farthest-point) or the reach
              (the spot covering the most uncovered area; a spot covering nothing new is never placed).
  bare        VIA-BARE: unlocked pour-only vias the gate flags (after the stitches), removed iteratively while every
              island keeps >= 2 links, the POUR-STITCH density and the STITCH_REACH_MM reach (the gate's constants);
              edge-fence vias are never candidates (the gate keeps them). The gate's caution stands: only router-left
              vias, never locked ones (--no-bare keeps them all).
  refill      one native refill of all zones.
Every edit is checked BEFORE it is applied (clearance to all other-net copper incl. pad overrides and fixed pours,
PRI-SEC 2.00 mm on every layer, hole-to-hole, NPTH, edge, rule areas; same-net contacts and T-joints kept; joints
>= 90 deg).
Arbiter (parent / UI B8.1 method): after the run, ONE DRC + both gates on the refilled board (parallel processes). Any
new DRC error / copper warning, connection finding (PAD-OPEN cluster / PAD-LAND / POUR-PAD / TRACK-END / VIA-LAND /
LOOP / VIA-PADEDGE / VIA-PARTIAL / PLANE-ISLAND / PAD-CENTRE, KiCad unconnected per net) or layout finding at a new
location (point classes; POUR-STITCH deficit and DIFFPAIR problems per net) is traced to the nearest edit; that EDIT
(stable key) is blocked and the run replays from the input board, resuming at the first step that emitted a newly
blocked edit.
"""
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
import uuid as _uuid
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE / "cu_cleanup"))
sys.path.insert(0, str(HERE))
import board_const as K  # noqa: E402  (first: tools/pylib shapely when this runs under KiCad's Python)
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

import cugraph  # noqa: E402
import current_budget as cb  # noqa: E402
import place_gate  # noqa: E402
import smooth  # noqa: E402
import via_site  # noqa: E402

LOCAL_RUN = HERE / "local_run.py"
WORKER = HERE / "cu_cleanup" / "kicad_worker.py"
NS = _uuid.UUID("5c1e7a30-2d4b-4e8f-9a61-c7a0d3f1e204")      # CT's own UUID namespace for new items
SAFE = 0.006
ISO = place_gate.ISO_MM
WORKDIR = None            # REPORT.work (set by run())

PADEDGE_MIN_FRAC = via_site.PADEDGE_MIN_FRAC
STITCH_MIN_MM2 = via_site.GATE["STITCH_MIN_MM2"]
STITCH_MM2_PER_VIA = via_site.GATE["STITCH_MM2_PER_VIA"]
STITCH_MIN_VIAS = via_site.GATE["STITCH_MIN_VIAS"]
STITCH_REACH_MM = via_site.GATE["STITCH_REACH_MM"]
STITCH_REACH_TOL_MM2 = via_site.GATE["STITCH_REACH_TOL_MM2"]
ISLAND_MIN_MM2 = via_site.GATE["ISLAND_MIN_MM2"]
PAD_CENTRE_TOL = via_site.GATE["PAD_CENTRE_TOL"]
PE_RMAX, PE_ANGLES = 1.0, 24   # VIA-PADEDGE move search: radius (0.05 mm steps) and directions


# ------------------------------------------------------------------------------------------------- KiCad processes
def _cmd_worker(*args):
    return [sys.executable, str(LOCAL_RUN), str(WORKER), *[str(a) for a in args]]


def _cmd_drc(board, out):
    return [sys.executable, str(LOCAL_RUN), "--cli", "pcb", "drc", "--severity-all", "--format", "json", "-o", str(out),
            str(board)]


def _popen(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")


def _finish(proc, what, out=None):
    so, _ = proc.communicate()
    if proc.returncode != 0 or (out is not None and not Path(out).exists()):
        raise RuntimeError(f"{what} failed (rc {proc.returncode}): " + (so or "")[-3000:])
    return so


def kicad(*args):
    return _finish(_popen(_cmd_worker(*args)), "kicad_worker " + str(args[0]))


def wpath(name):
    return WORKDIR / name


def annotate(G):
    """PRI / SEC side of every net (design.PRI_NETS through board_const.side_of) for the isolation clearance"""
    pri = K.pri_nets()
    for n in G["nets"].values():
        n["side"] = K.side_of(n["name"], pri)
    return G


def dump(board, out):
    kicad("dump", Path(board).resolve(), Path(out).resolve())
    return annotate(cugraph.load(str(out)))


def native_apply(board, delete, moves, adds, widen=None, refill=True, vias=(), dump_out=None):
    """one worker process: deletes by UUID (serialized board), via moves, widths, new tracks / vias, optional refill,
    pcb_rules.apply + SaveBoard (cu_cleanup/kicad_worker.py apply; it refuses any locked item)"""
    plan = {"delete": sorted(delete), "moves": {u: list(xy) for u, xy in moves.items()}, "widen": dict(widen or {}),
            "adds": list(adds), "vias": list(vias), "refill": bool(refill)}
    pf = wpath("plan.json")
    pf.write_text(json.dumps(plan), encoding="utf-8")
    args = ["apply", Path(board).resolve(), pf.resolve()] + (["--dump", Path(dump_out).resolve()] if dump_out else [])
    kicad(*args)


def run_gate(board, fast=True):
    out = wpath(f"gate-{'fast' if fast else 'full'}.json")
    out.unlink(missing_ok=True)
    kicad("gate", Path(board).resolve(), out.resolve(), *(["--fast"] if fast else []))
    return json.loads(out.read_text(encoding="utf-8"))


def run_lq(board):
    out = wpath("lq.json")
    out.unlink(missing_ok=True)
    kicad("lq", Path(board).resolve(), out.resolve())
    return json.loads(out.read_text(encoding="utf-8"))


def parallel_checks(board, fast=True, geom_out=None, tag="chk"):
    """DRC + copper gate + layout gate (+ a geometry dump) of one board as parallel processes -> (gate result, layout
    result, DRC report, geom or None)"""
    board = Path(board).resolve()
    drc_o, g_o, l_o = wpath(f"{tag}-drc.json"), wpath(f"{tag}-gate.json"), wpath(f"{tag}-lq.json")
    for f in (drc_o, g_o, l_o):
        f.unlink(missing_ok=True)
    procs = [("drc", _popen(_cmd_drc(board, drc_o.resolve())), drc_o),
             ("gate", _popen(_cmd_worker("gate", board, g_o.resolve(), *(["--fast"] if fast else []))), g_o),
             ("lq", _popen(_cmd_worker("lq", board, l_o.resolve())), l_o)]
    if geom_out is not None:
        procs.append(("dump", _popen(_cmd_worker("dump", board, Path(geom_out).resolve())), Path(geom_out)))
    for what, p, o in procs:
        _finish(p, what, o)
    G = annotate(cugraph.load(str(geom_out))) if geom_out is not None else None
    return (json.loads(g_o.read_text(encoding="utf-8")), json.loads(l_o.read_text(encoding="utf-8")),
            json.loads(drc_o.read_text(encoding="utf-8")), G)


# ------------------------------------------------------------------------------------------------- geometry helpers
def nets_of(G):
    return {int(k): v for k, v in G["nets"].items()}


def trk_line(t):
    return LineString([t["s"], t["e"]]) if (t["s"][0], t["s"][1]) != (t["e"][0], t["e"][1]) else Point(t["s"])


def trk_cu(t):
    return trk_line(t).buffer(t["w"] / 2, 16)


def via_disc(v):
    return Point(v["x"], v["y"]).buffer(v["d"] / 2, 16)


def vlayers(G, v):
    return cugraph.via_layers(v, G["layers"])


def pad_geo(p):
    out = {}
    for L, rs in p["shapes"].items():
        polys = [cugraph.ring_poly(r) for r in rs]
        out[L] = unary_union(polys) if len(polys) > 1 else (polys[0] if polys else None)
    return out


def is_smd(p):
    return not p.get("drill") and bool(p["shapes"])


def is_pth(p):
    return bool(p.get("drill")) and bool(p["shapes"])


def rec_geom(r):
    return trk_line(r) if "s" in r else Point(r["x"], r["y"])


def new_uuid(*parts):
    return str(_uuid.uuid5(NS, repr(parts)))


def locked_ids(G):
    return {t["uuid"] for t in G["tracks"] if t.get("locked")} | {v["uuid"] for v in G["vias"] if v.get("locked")} | \
           {a["uuid"] for a in G.get("arcs", []) if a.get("locked")}


def centre_landings(G):
    """{(net, layer): [pad centre (x, y)]} of the same-net SMD pads: a track end within PAD_CENTRE_TOL of one is that
    pad's centre landing (qa_copper_landing PAD-CENTRE)"""
    out = defaultdict(list)
    for p in G["pads"]:
        if is_smd(p):
            for L in p["shapes"]:
                out[(p["net"], L)].append((p["x"], p["y"]))
    return out


def lands_centre(t, cl):
    return any(math.dist(q, c) <= PAD_CENTRE_TOL for q in (t["s"], t["e"]) for c in cl.get((t["net"], t["layer"]), ()))


class Index:
    """per-layer STRtrees of pads / tracks / vias of a geom dict (rebuilt after each in-memory edit)"""

    def __init__(self, G):
        self.G = G
        self.nets = nets_of(G)
        self.items = defaultdict(list)          # layer -> [(geom, kind, rec)]
        for p in G["pads"]:
            for L, g in pad_geo(p).items():
                if g is not None and not g.is_empty:
                    self.items[L].append((g, "pad", p))
        for t in G["tracks"]:
            self.items[t["layer"]].append((trk_cu(t), "trk", t))
        for v in G["vias"]:
            d = via_disc(v)
            for L in vlayers(G, v):
                self.items[L].append((d, "via", v))
        self.tree = {L: STRtree([x[0] for x in lst]) for L, lst in self.items.items()}

    def query(self, L, g):
        if L not in self.tree:
            return []
        return [self.items[L][j] for j in self.tree[L].query(g)]

    def query_d(self, L, g, d):
        """items whose geometry lies within d of g (GEOS dwithin: no buffer built)"""
        if L not in self.tree:
            return []
        return [self.items[L][j] for j in self.tree[L].query(g, predicate="dwithin", distance=d)]


# ------------------------------------------------------------------------------------------------------- detectors
def safe_dups(G, uuids):
    """the duplicates whose deletion keeps every joint: a covered / zero-length segment may be the only thing two other
    tracks' ends meet on (qa_copper_landing joins ends within min(w) / 2 and ends on a track body within w / 2); such a
    dup is kept (reported) rather than deleted, so no chain comes loose"""
    by = defaultdict(list)
    for t in G["tracks"]:
        by[(t["net"], t["layer"])].append(t)
    T = {t["uuid"]: t for t in G["tracks"]}
    hubs = defaultdict(list)                       # (net, layer) -> same-net via discs / pad polygons (CT: they hold too)
    for v in G["vias"]:
        for L in vlayers(G, v):
            hubs[(v["net"], L)].append(via_disc(v))
    for p in G["pads"]:
        for L, g in pad_geo(p).items():
            if g is not None and not g.is_empty:
                hubs[(p["net"], L)].append(g)
    cl = centre_landings(G)
    gone = set(uuids)
    out = []
    for u in uuids:
        t = T.get(u)
        if t is None:
            continue
        rest = [o for o in by[(t["net"], t["layer"])] if o["uuid"] not in gone or o["uuid"] == u]
        hb = hubs[(t["net"], t["layer"])]
        ok = True
        for q in (t["s"], t["e"]):              # a pad's centre landing stays unless another end lands there too
            for c in cl.get((t["net"], t["layer"]), ()):
                if math.dist(q, c) <= PAD_CENTRE_TOL and not any(
                        o["uuid"] != u and min(math.dist(o["s"], c), math.dist(o["e"], c)) <= PAD_CENTRE_TOL for o in rest):
                    ok = False
        for q in (t["s"], t["e"]):
            for o in rest:
                if o["uuid"] == u:
                    continue
                for r in (o["s"], o["e"]):
                    if math.dist(q, r) > max(t["w"], o["w"]) / 2 + 1e-6:
                        continue
                    held = any(x["uuid"] not in (u, o["uuid"]) and (
                        trk_line(x).distance(Point(r)) <= x["w"] / 2 + 1e-6 or
                        min(math.dist(r, x["s"]), math.dist(r, x["e"])) <= min(x["w"], o["w"]) / 2)
                        for x in rest) or any(g.distance(Point(r)) < 1e-6 for g in hb)
                    if not held:
                        ok = False
        if ok:
            out.append(u)
        else:
            gone.discard(u)
    return out


def find_padedge(G, ix=None):
    """VIA-PADEDGE / VIA-PARTIAL / VIA-PADGAP by the gate's own padedge_class (via_site) -> [{via, pads: [(pad, layer,
    same_net)], near, foreign}]: pads = SMD pads the disc overlaps with its centre outside them ("edge" same-net sliver,
    "drilled" drill cutting the pad edge, "foreign" pad); near = SMD pads (any net) closer than PADEDGE_GAP_MM ("gap":
    no mask web, solder wicks). An "intentional" pad-edge landing is left (the gate passes it)."""
    ix = ix or Index(G)
    out = []
    for v in G["vias"]:
        d, c = via_disc(v), Point(v["x"], v["y"])
        hits, near = [], []
        for L in vlayers(G, v):
            for g, kind, p in ix.query(L, d.buffer(via_site.PADEDGE_GAP_MM + 1e-3)):
                if kind != "pad" or not is_smd(p) or g.contains(c):
                    continue
                same = p["net"] == v["net"]
                cls = via_site.padedge_class(g, c, v["d"] / 2, same, v["drill"] / 2)[0]
                if cls == "gap":
                    near.append((p, L))
                elif cls in ("edge", "drilled", "foreign"):
                    hits.append((p, L, same))
        if hits or near:
            out.append({"via": v, "pads": hits, "near": near, "foreign": any(not s for _, _, s in hits)})
    return out


def track_components(G):
    """union of same-net tracks / vias whose copper meets on a shared layer -> [(track uuids, via uuids, touches_pad)]"""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)
    per = defaultdict(list)                         # layer -> [(geom, key, net)]
    for t in G["tracks"]:
        if t["net"]:
            per[t["layer"]].append((trk_cu(t), ("t", t["uuid"]), t["net"]))
            find(("t", t["uuid"]))
    for v in G["vias"]:
        if v["net"]:
            d = via_disc(v)
            find(("v", v["uuid"]))
            for L in vlayers(G, v):
                per[L].append((d, ("v", v["uuid"]), v["net"]))
    touched = set()
    padsL = defaultdict(list)
    for p in G["pads"]:
        if p["net"]:
            for L, g in pad_geo(p).items():
                if g is not None and not g.is_empty:
                    padsL[L].append((g, p["net"]))
    for L, lst in per.items():
        tree = STRtree([x[0] for x in lst])
        for i, (g, k, n) in enumerate(lst):
            for j in tree.query(g):
                if j > i and lst[j][2] == n and lst[j][1] != k and g.intersects(lst[j][0]):
                    union(k, lst[j][1])
        if padsL[L]:
            ptree = STRtree([x[0] for x in padsL[L]])
            for g, k, n in lst:
                if any(padsL[L][j][1] == n and padsL[L][j][0].intersects(g) for j in ptree.query(g)):
                    touched.add(k)
    comps = defaultdict(lambda: [[], [], False])
    for k in parent:
        r = find(k)
        comps[r][0 if k[0] == "t" else 1].append(k[1])
        if k in touched:
            comps[r][2] = True
    return list(comps.values())


def fill_islands(G, net_codes=None):
    """-> [(net, layer, polygon)]: one connected own-net fill polygon per layer (zones of a net unioned per layer)"""
    per = defaultdict(list)
    for z in G["zones"]:
        if z["rule_area"] or not z["net"] or (net_codes is not None and z["net"] not in net_codes):
            continue
        for L, rs in z.get("fills", {}).items():
            per[(z["net"], L)].extend(cugraph.ring_poly(r) for r in rs)
    out = []
    for (n, L), polys in sorted(per.items()):
        u = unary_union([q for q in polys if not q.is_empty])
        for g in getattr(u, "geoms", [u]):
            if not g.is_empty and g.area > 1e-6:
                out.append((n, L, g))
    return out


def bare_vias(G, ix=None):
    """vias touching no same-net track / pad on any layer (pour-only vias)"""
    ix = ix or Index(G)
    out = []
    for v in G["vias"]:
        d = via_disc(v)
        hit = False
        for L in vlayers(G, v):
            for g, kind, rec in ix.query(L, d):
                if kind in ("trk", "pad") and rec["net"] == v["net"] and g.intersects(d):
                    hit = True
                    break
            if hit:
                break
        if not hit:
            out.append(v)
    return out


def pad_box(p):
    from shapely.geometry import box
    gs = [g for g in pad_geo(p).values() if g is not None and not g.is_empty]
    return box(*unary_union(gs).bounds) if gs else None


def bare_removals(G, allowed, ix=None):
    """VIA-BARE -> ordered [(via, why)]: the pour-only vias in `allowed` (the gate's VIA-BARE list, unlocked) to delete,
    iteratively, most redundant first. Islands follow qa_copper_landing: own-net fill per layer split into connected
    parts; a part < ISLAND_MIN_MM2 holding no own-net track / pad on that layer is not significant; links = other
    same-net vias and plated holes touching it. A via goes only while every significant island it touches keeps
    >= 2 links, and every outer fragment > STITCH_MIN_MM2 of a net with an inner plane keeps the POUR-STITCH density
    (max(STITCH_MIN_VIAS, area / STITCH_MM2_PER_VIA) plane-reaching links) and its STITCH_REACH_MM reach (uncovered area
    <= STITCH_REACH_TOL_MM2) when it met them before (the gate's constants)."""
    ix = ix or Index(G)
    cands = [v for v in bare_vias(G, ix) if v["uuid"] in allowed]
    if not cands:
        return []
    nets_needed = {v["net"] for v in cands}
    isl = fill_islands(G, nets_needed)
    inner_fill = {}
    for n in nets_needed:
        for L in G["layers"]:
            if L in K.OUTER_LAYERS:
                continue
            g = unary_union([g for n2, L2, g in isl if n2 == n and L2 == L])
            if not g.is_empty:
                inner_fill.setdefault(n, []).append((L, g))
    sig = []
    for n, L, g in isl:
        own = g.area >= ISLAND_MIN_MM2 or any(kind in ("trk", "pad") and rec["net"] == n and og.intersects(g)
                                              for og, kind, rec in ix.query(L, g))
        sig.append(own)
    trees = defaultdict(list)
    for i, (n, L, g) in enumerate(isl):
        trees[(n, L)].append(i)
    st = {k: STRtree([isl[i][2] for i in lst]) for k, lst in trees.items()}

    def touched(net, layers, geom_of):
        s = set()
        for L in layers:
            k = (net, L)
            if k not in st:
                continue
            g = geom_of(L)
            if g is None:
                continue
            for j in st[k].query(g):
                i = trees[k][j]
                if isl[i][2].intersects(g):
                    s.add(i)
        return s
    links = defaultdict(set)                     # island -> link ids
    plinks = defaultdict(dict)                   # outer stitch fragment -> {plane-reaching link id: position}
    touch = {}
    for v in G["vias"]:
        if v["net"] in nets_needed:
            d = via_disc(v)
            ls = vlayers(G, v)
            touch[("v", v["uuid"])] = touched(v["net"], ls, lambda L: d)
            if any(L in ls and g.intersects(d) for L, g in inner_fill.get(v["net"], ())):
                for i in touch[("v", v["uuid"])]:
                    if isl[i][1] in K.OUTER_LAYERS:
                        plinks[i][("v", v["uuid"])] = (v["x"], v["y"])
    for p in G["pads"]:
        if p["net"] in nets_needed and is_pth(p):
            bx = pad_box(p)
            touch[("p", p["uuid"])] = touched(p["net"], list(p["shapes"]), lambda L: bx)
            for i in touch[("p", p["uuid"])]:
                if isl[i][1] in K.OUTER_LAYERS and isl[i][2].intersects(Point(p["x"], p["y"])):
                    plinks[i][("p", p["uuid"])] = (p["x"], p["y"])
    for k, s in touch.items():
        for i in s:
            links[i].add(k)
    stitch_isl = {i for i, (n, L, g) in enumerate(isl) if L in K.OUTER_LAYERS and g.area > STITCH_MIN_MM2
                  and n in inner_fill}

    def need(i):
        return max(STITCH_MIN_VIAS, math.ceil(isl[i][2].area / STITCH_MM2_PER_VIA))

    def far_area(i, drop=None):
        pts = [q for k, q in plinks[i].items() if k != drop]
        g = isl[i][2]
        if not pts:
            return g.area
        return g.difference(unary_union([Point(q).buffer(STITCH_REACH_MM, 16) for q in pts])).area

    reach_ok = {i: far_area(i) <= STITCH_REACH_TOL_MM2 for i in stitch_isl}
    dense_ok = {i: len(plinks[i]) >= need(i) for i in stitch_isl}

    def removable(k):
        for i in touch[k]:
            if i in stitch_isl:
                if dense_ok[i] and len(plinks[i]) - (k in plinks[i]) < need(i):
                    return False
                if reach_ok[i] and k in plinks[i] and far_area(i, k) > STITCH_REACH_TOL_MM2:
                    return False
        return True
    out = []
    alive = {("v", v["uuid"]): v for v in cands}
    stouch = {k: {i for i in touch[k] if sig[i]} for k in alive}

    def drop(k):
        for i in touch[k]:
            links[i].discard(k)
            plinks[i].pop(k, None)
    for k in sorted(alive):                      # links nothing: < 2 significant islands
        if len(stouch[k]) < 2 and removable(k):
            out.append((alive.pop(k), f"touches {len(stouch[k])} significant fill island(s): links nothing"))
            drop(k)
    while alive:
        best = None
        for k in alive:
            if not stouch[k]:
                continue
            score = min(len(links[i]) - 1 - 2 for i in stouch[k])
            if score >= 0 and removable(k) and (best is None or (score, k) > (best[0], best[1])):
                best = (score, k)
        if best is None:
            break
        score, k = best
        v = alive.pop(k)
        out.append((v, f"redundant stitch (each island keeps {score} links over 2; density / reach kept)"))
        drop(k)
    return out


# ---------------------------------------------------------------------------------------------------- legality
NEAR_Q = 0.8              # Legal.copper_ok query radius (every CT net-class clearance and pad override is below it)


class Planned(list):
    """a list of (geom, net) with a 2 mm grid index: near(g, r) yields only entries whose bounds come within r"""

    def __init__(self):
        super().__init__()
        self.grid = defaultdict(list)

    def append(self, x):
        super().append(x)
        x0, y0, x1, y1 = x[0].bounds
        for i in range(int(x0 // 2), int(x1 // 2) + 1):
            for j in range(int(y0 // 2), int(y1 // 2) + 1):
                self.grid[(i, j)].append(len(self) - 1)

    def near(self, g, r):
        x0, y0, x1, y1 = g.bounds
        seen = set()
        for i in range(int((x0 - r) // 2), int((x1 + r) // 2) + 1):
            for j in range(int((y0 - r) // 2), int((y1 + r) // 2) + 1):
                for k in self.grid.get((i, j), ()):
                    if k not in seen:
                        seen.add(k)
                        yield self[k]


class Legal:
    """legality of a new via / segment against foreign copper (place_gate.required: class clearance, pad overrides,
    PRI-SEC 2.00 mm on every layer), fixed power-cell pours (other pours are refilled around new copper), rule areas,
    NPTH, board edge, hole-to-hole"""

    def __init__(self, G, ix):
        self.G, self.ix, self.nets = G, ix, nets_of(G)
        self.fixed_z = defaultdict(list)
        side_items = []
        for z in G["zones"]:
            if z["rule_area"]:
                continue
            sd = self.nets.get(z["net"], {}).get("side")
            for L, rs in z.get("fills", {}).items():
                for r in rs:
                    g = cugraph.ring_poly(r)
                    if smooth.fixed_zone(z):
                        self.fixed_z[L].append((g, z["net"]))
                    if sd is not None and not g.is_empty:
                        side_items.append((g, sd, z["uuid"]))
        self.fz_tree = {L: STRtree([x[0] for x in lst]) for L, lst in self.fixed_z.items()}
        for L, lst in ix.items.items():
            for g, kind, rec in lst:
                sd = self.nets.get(rec["net"], {}).get("side")
                if sd is not None:
                    side_items.append((g, sd, rec["uuid"]))
        self.side_items = side_items
        self.side_tree = STRtree([x[0] for x in side_items]) if side_items else None
        self.areas = []
        for z in G["zones"]:
            if z["rule_area"]:
                for o in z["outline"]:
                    self.areas.append((cugraph.ring_poly(o), set(z.get("layers", [])), z))
        self.atree = STRtree([a[0] for a in self.areas])
        self.edge = unary_union([cugraph.ring_poly(o) for o in G["outline"]]).boundary
        self.drills = [(Point(v["x"], v["y"]), v["drill"], v["uuid"]) for v in G["vias"]] + \
                      [(Point(p["x"], p["y"]), max(p["drill"]), p["uuid"]) for p in G["pads"] if p.get("drill")]
        self.dtree = STRtree([d[0] for d in self.drills])
        self.npth = [Point(p["x"], p["y"]).buffer(max(p["drill"]) / 2) for p in G["pads"] if p.get("drill") and not p["shapes"]]
        self.rules = G.get("rules", {})
        self.extra = defaultdict(Planned)       # layer -> [(geom, net)] copper planned in this pass (grid-indexed)
        self._need = {}
        self.safe = SAFE                        # margin on every clearance (polygonised caps, rounding)
        self.pix = None                         # via_site.PadIndex (built on the first via check)

    def need(self, n, on, L=None, kind=None, okind=None, oclr=None):
        k = (n, on, oclr)
        if k not in self._need:
            a = self.nets.get(n, {"clearance": 0.15})
            b = self.nets.get(on, {"clearance": 0.15})
            self._need[k] = place_gate.required(a, b, clr_b=oclr)
        return self._need[k]

    def area_sig(self, g, layers):
        out = set()
        for j in self.atree.query(g):
            poly, ls, z = self.areas[j]
            if ls & set(layers) and poly.intersects(g):
                out.add((j, poly.contains(g)))
        return out

    def iso_ok(self, n, g, ignore=()):
        """PRI-SEC lateral distance on every layer pair (qa_crosslayer, fills included)"""
        sd = self.nets.get(n, {}).get("side")
        if sd is None:
            return True
        if self.side_tree is not None:
            for j in self.side_tree.query(g, predicate="dwithin", distance=ISO + self.safe):
                og, osd, u = self.side_items[j]
                if osd != sd and u not in ignore:
                    return False
        for L, lst in self.extra.items():
            for og, on in lst.near(g, ISO + self.safe):
                osd = self.nets.get(on, {}).get("side")
                if osd is not None and osd != sd and g.distance(og) < ISO + self.safe:
                    return False
        return True

    def copper_ok(self, n, L, g, kind, ignore=()):
        cand = self.ix.query_d(L, g, NEAR_Q)
        geoms, needs = [], []
        for og, okind, rec in cand:
            if rec["net"] == n or rec["uuid"] in ignore:
                continue
            geoms.append(og)
            needs.append(self.need(n, rec["net"], oclr=rec.get("clr") if okind == "pad" else None) + self.safe)
        if geoms and (shapely.distance(g, geoms) < needs).any():     # one vectorised call
            return False
        if L in self.fz_tree:
            for j in self.fz_tree[L].query(g, predicate="dwithin", distance=NEAR_Q):
                og, on = self.fixed_z[L][j]
                if on != n and g.distance(og) < self.need(n, on) + self.safe:
                    return False
        for og, on in self.extra[L].near(g, NEAR_Q):
            if on != n and g.distance(og) < self.need(n, on) + self.safe:
                return False
        return self.iso_ok(n, g, ignore)

    def seg_ok(self, n, L, a, b, w, old_sig_geo=None):
        if math.dist(a, b) < 1e-6:
            return True
        line = LineString([a, b])
        g = line.buffer(w / 2, 16)
        if line.distance(self.edge) < self.rules.get("edge_clearance", 0.3) + w / 2 + self.safe:
            return False
        hc = self.rules.get("hole_clearance", 0.25)
        if any(line.distance(h) < hc + w / 2 + self.safe for h in self.npth if h.distance(line) < 2):
            return False
        allowed = {j for j, _ in self.area_sig(old_sig_geo, [L])} if old_sig_geo is not None else set()
        for j, _ in self.area_sig(g, [L]):
            if j not in allowed or self.areas[j][2].get("no_tracks"):
                return False
        return self.copper_ok(n, L, g, "trk")

    def via_ok(self, v, c, layers, old_sig):
        d = c.buffer(v["d"] / 2, 16)
        if c.distance(self.edge) < self.rules.get("edge_clearance", 0.3) + v["d"] / 2 + self.safe:
            return False
        h2h = self.rules.get("hole_to_hole", 0.25)
        for j in self.dtree.query(c.buffer(2.0)):
            q, dr, u = self.drills[j]
            if u != v["uuid"] and q.distance(c) - dr / 2 - v["drill"] / 2 < h2h + self.safe:
                return False
        sig = self.area_sig(d, layers)
        if sig != old_sig or any(self.areas[j][2].get("no_vias") for j, _ in sig):
            return False
        # via-edge (pad-edge / half-in-pad vias are defects): wholly inside a fitting own-net SMD pad, or
        # >= PADEDGE_GAP_MM from every SMD pad (via_site: the gate's own padedge_class)
        if self.pix is None:
            self.pix = via_site.PadIndex(self.G)
        if via_site.site_faults(self.pix, v, (c.x, c.y), layers=set(layers)):
            return False
        on = set()                                 # own-net SMD pads the via sits wholly inside (a fitting via-in-pad)
        for L in layers:
            if not self.copper_ok(v["net"], L, d, "via", ignore={v["uuid"]}):
                return False
            for og, kind, rec in self.ix.query(L, d):
                if kind == "pad" and is_smd(rec) and rec["net"] == v["net"] and og.contains(c):
                    on.add((rec["uuid"], L))
        return on


# ---------------------------------------------------------------------------------------------------- fixers
def incl(a, j, b):
    """included angle (deg) at joint j between j->a and j->b (180 = straight on)"""
    u, v = (a[0] - j[0], a[1] - j[1]), (b[0] - j[0], b[1] - j[1])
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu < 1e-9 or nv < 1e-9:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))))


def fix_padedge(G, items, log=print, blocked=(), edits=None):
    """-> (moves {via uuid: (x, y)}, add tracks, unfixed [..]); foreign overlaps first. Each via goes to the cheapest
    legal spot within PE_RMAX (cost = new copper length): clear of every SMD pad (via_site) with a stub from it to its
    same-net pad's CENTRE, or wholly inside a fitting own pad (a true via-in-pad)"""
    ix = Index(G)
    lg = Legal(G, ix)
    nets = nets_of(G)
    moves, adds, unfixed = {}, [], []
    for it in sorted(items, key=lambda x: (not x["foreign"], x["via"]["x"], x["via"]["y"])):
        v = it["via"]
        name = nets.get(v["net"], {}).get("name", "")
        if ("PE", v["uuid"]) in blocked:
            unfixed.append({"via": v["uuid"], "net": name, "at": [v["x"], v["y"]], "why": "blocked by the arbiter"})
            continue
        c0 = Point(v["x"], v["y"])
        d0 = via_disc(v)
        layers = vlayers(G, v)
        old_sig = lg.area_sig(d0, layers)
        att, att_ends = {}, defaultdict(list)
        far_of = defaultdict(list)                     # (layer, end) -> far ends of the tracks ending there
        for L in layers:
            ws = []
            for g, kind, rec in ix.query(L, d0):
                if kind == "trk" and rec["net"] == v["net"] and g.intersects(d0):
                    ws.append(rec["w"])
                    for q in (rec["s"], rec["e"]):
                        if d0.contains(Point(q)) or math.dist(q, (v["x"], v["y"])) <= v["d"] / 2 + 1e-6:
                            att_ends[L].append((tuple(q), rec["w"]))
                            far_of[(L, round(q[0], 4), round(q[1], 4))].append(tuple(rec["e"] if q is rec["s"] else rec["s"]))
            if ws:
                att[L] = min(ws)
        stubs = [(p, L) for p, L, same in it["pads"] if same]
        cls_w = nets.get(v["net"], {}).get("track") or 0.2
        best = None
        for r in [0.05 * k for k in range(1, int(round(PE_RMAX / 0.05)) + 1)]:
            if best is not None and r > best[1] + 0.3:
                break
            for k in range(PE_ANGLES):
                ang = 2 * math.pi * k / PE_ANGLES
                c = Point(v["x"] + r * math.cos(ang), v["y"] + r * math.sin(ang))
                on = lg.via_ok(v, c, layers, old_sig)
                if on is False:
                    continue
                segs, ok = [], True
                # every attached track END that sat in the old via disc is re-terminated to the new via centre (a track
                # that only touched the disc keeps its copper contact through the old-centre connector)
                for L, w in sorted(att.items()):
                    for q, wq in sorted(set(att_ends.get(L, [])) | {((c0.x, c0.y), w)}):
                        if math.dist(q, (c.x, c.y)) > 1e-6 and any(
                                2.0 < incl(f_, q, (c.x, c.y)) < 90.0
                                for f_ in far_of.get((L, round(q[0], 4), round(q[1], 4)), [])
                                if math.dist(f_, q) > 1e-6):
                            ok = False
                            break
                        if not lg.seg_ok(v["net"], L, q, (c.x, c.y), wq, old_sig_geo=d0):
                            ok = False
                            break
                        segs.append((L, q, (c.x, c.y), wq))
                    if not ok:
                        break
                if not ok:
                    continue
                for p, L in stubs:
                    if (p["uuid"], L) in on:
                        continue                   # wholly inside its own pad: a fitting via-in-pad
                    pg = pad_geo(p)[L]
                    pc = Point(p["x"], p["y"]) if pg.contains(Point(p["x"], p["y"])) else pg.representative_point()
                    tgt = (pc.x, pc.y)                 # traces run from the pad CENTRE
                    w = min(att.get(L, cls_w), cls_w)
                    if not lg.seg_ok(v["net"], L, (c.x, c.y), tgt, w, old_sig_geo=d0.union(pg)):
                        ok = False
                        break
                    segs.append((L, (c.x, c.y), tgt, w))
                if not ok:
                    continue
                cost = sum(math.dist(a, b) for _, a, b, _ in segs) + 0.01 * r
                if best is None or cost < best[0] - 1e-9:
                    best = (cost, r, c, segs)
        if best is None:
            unfixed.append({"via": v["uuid"], "net": name, "at": [v["x"], v["y"]],
                            "pads": [f"{p['ref']}.{p['num']} {L}" for p, L, _ in it["pads"]] +
                                    [f"{p['ref']}.{p['num']} {L} (near)" for p, L in it.get("near", [])],
                            "why": f"no legal spot within {PE_RMAX} mm"})
            continue
        _, r, c, segs = best
        moves[v["uuid"]] = (round(c.x, 4), round(c.y, 4))
        e_adds = []
        for L, a, b, w in segs:
            if math.dist(a, b) < 1e-6:
                continue
            t = {"net": name, "layer": L, "s": [round(a[0], 4), round(a[1], 4)], "e": [round(b[0], 4), round(b[1], 4)], "w": w}
            adds.append(t)
            e_adds.append(t)
            lg.extra[L].append((LineString([a, b]).buffer(w / 2), v["net"]))
        for L in layers:
            lg.extra[L].append((c.buffer(v["d"] / 2), v["net"]))
        lg.drills.append((c, v["drill"], v["uuid"] + "#moved"))
        lg.dtree = STRtree([d[0] for d in lg.drills])
        if edits is not None:
            edits.append({"key": ("PE", v["uuid"]), "class": "VIA-PADEDGE", "net": name, "at": [v["x"], v["y"]],
                          "op": f"via moved {r:.2f} mm" + (" (foreign pad)" if it["foreign"] else ""),
                          "moves": {v["uuid"]: moves[v["uuid"]]}, "adds": e_adds})
    log(f"padedge: moved {len(moves)}, stub/connector tracks {len(adds)}, unfixed {len(unfixed)}")
    return moves, adds, unfixed


def along_axis(p, L, a, b, aspect=1.5, tol=10.0):
    """a stub a -> b inside pad p runs along the pad's long axis (or the pad is not elongated)"""
    g = pad_geo(p).get(L)
    if g is None or math.dist(a, b) < 1e-6:
        return True
    r = list(g.minimum_rotated_rectangle.exterior.coords)
    e1, e2 = (r[1][0] - r[0][0], r[1][1] - r[0][1]), (r[2][0] - r[1][0], r[2][1] - r[1][1])
    l1, l2 = math.hypot(*e1), math.hypot(*e2)
    if min(l1, l2) < 1e-9 or max(l1, l2) / min(l1, l2) < aspect:
        return True
    ax = e1 if l1 >= l2 else e2
    d = (b[0] - a[0], b[1] - a[1])
    c = abs(ax[0] * d[0] + ax[1] * d[1]) / (math.hypot(*ax) * math.hypot(*d))
    return math.degrees(math.acos(min(1.0, c))) <= tol


def fix_centres(G, findings, log=print, blocked=(), edits=None):
    """PAD-CENTRE: a trace chain ending on an SMD pad off its centre is extended to the centre: the end segment is
    re-drawn to the centre when the centre lies on its line (collinear merge; never for a LOCKED segment), else a
    segment end -> centre is added (same width; it lies in the pad copper, checked against foreign copper all the same)
    -> (delete, adds, unfixed)"""
    ix = Index(G)
    lg = Legal(G, ix)
    nets = nets_of(G)
    T = {t["uuid"]: t for t in G["tracks"]}
    P = {f"{p['ref']}.{p['num']}": p for p in G["pads"]}
    per = defaultdict(list)
    for f in findings:
        u = f["uuids"][0]
        if u in T and f["pad"] in P:
            per[u].append(f)
    dele, adds, unfixed = [], [], []
    for u, fs in sorted(per.items()):
        t = T[u]
        name = nets[t["net"]]["name"]
        if ("CENTRE", u) in blocked:
            unfixed.append({"net": name, "pads": [f["pad"] for f in fs], "layer": t["layer"], "why": "blocked by the arbiter"})
            continue
        s_, e_ = tuple(t["s"]), tuple(t["e"])
        new_s, new_e, extra, extra_pad = s_, e_, [], []
        for f in fs:
            p = P[f["pad"]]
            c = (p["x"], p["y"])
            q = tuple(f["at"])
            at_e = math.dist(q, e_) <= math.dist(q, s_)
            far = s_ if at_e else e_
            d1 = (q[0] - far[0], q[1] - far[1])
            d2 = (c[0] - q[0], c[1] - q[1])
            n1, n2 = math.hypot(*d1), math.hypot(*d2)
            coll = n1 > 1e-9 and n2 > 1e-9 and abs(d1[0] * d2[1] - d1[1] * d2[0]) / (n1 * n2) < 1e-3
            if (coll or n2 < 1e-9) and not t.get("locked"):
                if at_e:
                    new_e = c
                else:
                    new_s = c
            elif n2 > 1e-9:
                extra.append((q, c))
                extra_pad.append(f["pad"])
        geoms = [LineString([new_s, new_e]).buffer(t["w"] / 2)] + [LineString([a, b]).buffer(t["w"] / 2) for a, b in extra]
        if extra and not all(along_axis(P[pd], t["layer"], a, b) for pd, (a, b) in zip(extra_pad, extra)):
            unfixed.append({"net": name, "pads": [f["pad"] for f in fs], "layer": t["layer"],
                            "why": "stub to the centre would leave an elongated pad off its axis (PAD-AXIS)"})
            continue
        if all(lg.copper_ok(t["net"], t["layer"], g, "trk") for g in geoms):
            n0 = len(adds)
            redraw = (new_s, new_e) != (s_, e_)
            if redraw:
                dele.append(u)
                if math.dist(new_s, new_e) > 1e-4:     # else: a stub from the centre to its free end inside the pad
                    adds.append({"net": name, "layer": t["layer"], "s": list(new_s), "e": list(new_e), "w": t["w"]})
            for a, b in extra:
                adds.append({"net": name, "layer": t["layer"], "s": list(a), "e": list(b), "w": t["w"]})
            if edits is not None and (len(adds) > n0 or redraw):
                edits.append({"key": ("CENTRE", u), "class": "PAD-CENTRE", "net": name, "at": list(fs[0]["at"]),
                              "op": ("re-drawn" if len(adds) > n0 and redraw else "in-pad stub removed" if redraw
                                     else "extended") + " to the centre of "
                                    + ", ".join(sorted({f["pad"] for f in fs})),
                              "dels": [u] if redraw else [], "adds": adds[n0:], "touch": [u]})
            for g in geoms:
                lg.extra[t["layer"]].append((g, t["net"]))
        else:
            unfixed.append({"net": name, "pads": [f["pad"] for f in fs], "layer": t["layer"], "why": "extension not clear"})
    log(f"pad-centre: re-drawn {len(dele)}, added {len(adds)}, unfixed {len(unfixed)}")
    return dele, adds, unfixed


# ------------------------------------------------------------------------------------- in-memory edits of a geom
def g_delete(G, uuids):
    uuids = set(uuids)
    G["tracks"] = [t for t in G["tracks"] if t["uuid"] not in uuids]
    G["vias"] = [v for v in G["vias"] if v["uuid"] not in uuids]


def g_move(G, moves):
    for v in G["vias"]:
        if v["uuid"] in moves:
            v["x"], v["y"] = moves[v["uuid"]]


CLEAN = ("TRACK-DUP", "VIA-PADEDGE", "VIA-PARTIAL", "VIA-BARE", "TRACK-ORPHAN", "TRACK-JOG", "PAD-CENTRE", "TRACK-WIDTH")
DEBRIS = ("TRACK-END", "VIA-LAND", "LOOP")


def gate_uuids(fails, cls):
    out = []
    for x in fails[cls]:
        out += x.get("uuids", [])
    return out


def free_pad_ends(G):
    """chain ends (no other same-net track end / body / via there) whose copper lies on a same-net SMD pad off its
    centre -> [{"uuids": [track], "pad": "ref.num", "at": end}] (PAD-CENTRE findings and near-miss landings)"""
    ix = Index(G)
    ends = defaultdict(list)
    for t in G["tracks"]:
        for q in (t["s"], t["e"]):
            ends[(t["net"], t["layer"])].append((tuple(q), t))
    out = []
    for (n, L), lst in ends.items():
        grid = defaultdict(list)
        for q, t in lst:
            grid[(int(q[0] // 0.5), int(q[1] // 0.5))].append((q, t))
        for q, t in lst:
            gx, gy = int(q[0] // 0.5), int(q[1] // 0.5)
            near_e = [x for dx in (-1, 0, 1) for dy in (-1, 0, 1) for x in grid.get((gx + dx, gy + dy), ())]
            if any(o is not t and math.dist(q, q2) <= min(t["w"], o["w"]) / 2 for q2, o in near_e):
                continue
            pq = Point(q)
            near = ix.query(L, pq.buffer(t["w"] / 2))
            if any(kind == "via" and rec["net"] == n and g.intersects(pq) for g, kind, rec in near):
                continue
            if any(kind == "trk" and rec["net"] == n and rec is not t and trk_line(rec).distance(pq) <= rec["w"] / 2 + 1e-6
                   for g, kind, rec in near):
                continue
            for g, kind, rec in near:
                if kind == "pad" and rec["net"] == n and is_smd(rec) and g.distance(pq) <= t["w"] / 2 - 1e-3 \
                        and math.dist(q, (rec["x"], rec["y"])) > 0.02 and g.contains(Point(rec["x"], rec["y"])):
                    out.append({"uuids": [t["uuid"]], "pad": f"{rec['ref']}.{rec['num']}", "at": list(q)})
                    break
    return out


NECK_MM = cb.NECK_MM      # a below-required piece this long into a same-net pad is a neck (TRACK-WIDTH)
NECK_TOL = via_site.NECK_TOL_MM   # qa_layout_quality NECK-SMALLPAD tolerance


def _across(g, a, b):
    """extent of pad polygon g across the direction a -> b (qa_layout_quality NECK-SMALLPAD)"""
    L = math.dist(a, b)
    n = (-(b[1] - a[1]) / L, (b[0] - a[0]) / L)
    xs = [x * n[0] + y * n[1] for x, y in g.convex_hull.exterior.coords]
    return max(xs) - min(xs)


def widen_plan(G, fails, log=print, blocked=(), edits=None):
    """TRACK-WIDTH: each failing (unlocked) segment to the gate's required width where legal -> ({uuid: w}, [unfixed]).
    At an end on a same-net SMD pad narrower (across the track) than the required width, the last piece keeps its width
    as a <= NECK_MM neck (the gate's TRACK-WIDTH neck rule; a widened end there would be qa_layout_quality NECK-SMALLPAD).
    A short same-net segment the widened copper swallows is the next round's TRACK-DUP delete (joint guard)."""
    ix = Index(G)
    lg = Legal(G, ix)
    T = {t["uuid"]: t for t in G["tracks"]}
    cl = centre_landings(G)
    out, unfixed = {}, []
    for x in fails.get("TRACK-WIDTH", []):
        u = x["uuids"][0]
        t = T.get(u)
        if t is None or x.get("required") in (None, "") or t.get("locked"):
            continue
        w = float(x["required"])
        if w <= t["w"] + 1e-6:
            continue
        rec = {"net": x["net"], "layer": t["layer"], "at": x.get("at"), "width": t["w"], "required": w, "uuid": u}
        if ("WIDTH", u) in blocked:
            unfixed.append(dict(rec, why="blocked by the arbiter"))
            continue
        a, b, L, n = tuple(t["s"]), tuple(t["e"]), t["layer"], t["net"]
        Ls = math.dist(a, b)
        if Ls < 1e-4:
            continue
        cut, bad = {}, False
        for k, q, far in (("s", a, b), ("e", b, a)):
            for g, kind, pr in ix.query(L, Point(q).buffer(w)):
                if kind != "pad" or pr["net"] != n or not is_smd(pr) or g.distance(Point(q)) > t["w"] / 2 + 1e-6:
                    continue
                if w <= _across(g, a, b) + NECK_TOL:
                    continue
                dk = None
                for i in range(1, int(NECK_MM / 0.025) + 1):
                    s_ = 0.025 * i
                    if s_ >= Ls - 0.05:
                        break
                    if not LineString([lerp(q, far, s_), far]).buffer(w / 2, 16).intersects(g):
                        dk = s_
                        break
                if dk is None:
                    bad = True
                else:
                    cut[k] = max(cut.get(k, 0.0), dk)
        ps = lerp(a, b, cut["s"]) if "s" in cut else a
        pe = lerp(b, a, cut["e"]) if "e" in cut else b
        if bad or math.dist(ps, pe) < 0.05:
            unfixed.append(dict(rec, why=f"pad narrower than {w} mm and no room for a <= {NECK_MM} mm neck"))
            continue
        wide = LineString([ps, pe]).buffer(w / 2, 16)
        if any(kind == "trk" and o["net"] == n and o["uuid"] != u and lands_centre(o, cl) and
               wide.buffer(1e-4).contains(og) for og, kind, o in ix.query(L, wide)):
            unfixed.append(dict(rec, why="the widened copper would swallow a pad's centre landing"))
            continue
        if not lg.seg_ok(n, L, ps, pe, w, old_sig_geo=trk_cu(t)):
            unfixed.append(dict(rec, why="no room at the required width (re-route)"))
            continue
        out[u] = w
        lg.extra[L].append((wide, n))
        if edits is None:
            continue
        if not cut:
            edits.append({"key": ("WIDTH", u), "class": "TRACK-WIDTH", "net": x["net"], "at": list(a),
                          "op": f"widen {t['w']} -> {w}", "widen": {u: w}})
        else:
            adds = ([{"net": x["net"], "layer": L, "s": list(a), "e": list(ps), "w": t["w"]}] if "s" in cut else []) + \
                   [{"net": x["net"], "layer": L, "s": list(ps), "e": list(pe), "w": w}] + \
                   ([{"net": x["net"], "layer": L, "s": list(pe), "e": list(b), "w": t["w"]}] if "e" in cut else [])
            edits.append({"key": ("WIDTH", u), "class": "TRACK-WIDTH", "net": x["net"], "at": list(a),
                          "op": f"widen {t['w']} -> {w} with {len(cut)} pad neck(s) <= {NECK_MM} mm", "dels": [u],
                          "adds": adds})
    log(f"widen: {len(out)} segments widened, {len(unfixed)} need a re-route")
    return out, unfixed


def drc_sig(v):
    """an error's identity across edits (re-drawn tracks get new UUIDs): type, the items' kinds / nets and where"""
    return (v["type"], tuple(sorted((re.sub(r", length [0-9.]+ mm", "", i["description"]),
                                     round(i["pos"]["x"] * 2) / 2, round(i["pos"]["y"] * 2) / 2) for i in v["items"])))


def stitch_starved(G, viol, log=print, blocked=(), edits=None):
    """DRC starved_thermal (a pad's thermal relief reaches its pour with fewer spokes than the zone's minimum): stitch
    the pad into its pour with a short track from the pad CENTRE (net class width) in the first of 8 directions whose
    far end lies well inside the pad's own-net fill on that layer and whose copper is clear -> (adds, unfixed)"""
    from shapely.prepared import prep
    ix = Index(G)
    lg = Legal(G, ix)
    nets = nets_of(G)
    P = {p["uuid"]: p for p in G["pads"]}
    fills = {}
    adds, unfixed = [], []
    for v in viol:
        if v["type"] != "starved_thermal":
            continue
        m = re.search(r"layer (\S+);", v["description"])
        pads = [P[i["uuid"]] for i in v["items"] if i.get("uuid") in P]
        if not m or not pads:
            continue
        L, p = m.group(1), pads[0]
        n = p["net"]
        name = nets[n]["name"]
        skey = ("STARVED", f"{p['ref']}.{p['num']}", L)
        if skey in blocked:
            unfixed.append({"pad": skey[1], "layer": L, "why": "blocked by the arbiter"})
            continue
        if (n, L) not in fills:
            u_ = unary_union([cugraph.ring_poly(r) for z in G["zones"] if not z["rule_area"]
                              and z["net"] == n for r in z.get("fills", {}).get(L, [])])
            fills[(n, L)] = (u_, prep(u_.buffer(-1e-3)))
        fz, fz_in = fills[(n, L)]
        pg = pad_geo(p).get(L)
        if pg is None:
            continue
        w = min(nets[n].get("track") or 0.25, 0.3)
        c = (p["x"], p["y"])
        if any(t["net"] == n and t["layer"] == L and min(math.dist(c, t["s"]), math.dist(c, t["e"])) < 0.02
               and fz.contains(Point(t["e"] if math.dist(c, t["s"]) < 0.02 else t["s"])) for t in G["tracks"]):
            continue
        r = max(pg.bounds[2] - pg.bounds[0], pg.bounds[3] - pg.bounds[1]) / 2
        done = False
        for k in range(8):
            a = math.radians(p.get("rot", 0) + 45 * k)
            for ext in (0.4, 0.6, 0.9):
                e = (c[0] + (r + ext) * math.cos(a), c[1] - (r + ext) * math.sin(a))
                if not fz_in.contains(Point(e).buffer(w / 2 + 0.05)):
                    continue
                if lg.seg_ok(n, L, c, e, w, old_sig_geo=pg):
                    t = {"net": name, "layer": L, "s": [round(c[0], 4), round(c[1], 4)], "e": [round(e[0], 4), round(e[1], 4)], "w": w}
                    adds.append(t)
                    lg.extra[L].append((LineString([c, e]).buffer(w / 2), n))
                    if edits is not None:
                        edits.append({"key": skey, "class": "STARVED", "net": name, "at": [c[0], c[1]],
                                      "op": f"pad stitched into its {L} pour", "adds": [t]})
                    done = True
                    break
            if done:
                break
        if not done:
            unfixed.append({"pad": f"{p['ref']}.{p['num']}", "layer": L, "why": "no clear direction into the own pour"})
    log(f"starved thermals: {len(adds)} pads stitched into their pour, {len(unfixed)} without a clear direction")
    return adds, unfixed


# ======================================================================================== layout fixers (parent v2.1)
ACUTE_OK = 91.0           # a corner cut / hop re-route leaves joints at >= this (qa_layout_quality ACUTE_DEG 90 + margin)
STITCH_PAD_GAP = max(0.15, via_site.PADEDGE_GAP_MM)   # a new stitch via keeps this gap to every SMD pad
STITCH_VIA_GAP = max(0.9, via_site.VIA_HOP_MM)        # ... and this centre distance to every other via (no VIA-HOP)
INNER = tuple(L for L in K.COPPER_LAYERS if L not in K.OUTER_LAYERS)


def lerp(a, b, t):
    L = math.dist(a, b)
    return tuple(a) if L < 1e-12 else (a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L)


def other_end(t, k):
    return t["e"] if k == "s" else t["s"]


def joint_busy(ix, net, L, q, excl, tol=1e-3):
    """another same-net track end at q, or a same-net via / pad covering q"""
    pq = Point(q)
    for g, kind, rec in ix.query(L, pq.buffer(0.05)):
        if rec["net"] != net:
            continue
        if kind == "trk" and rec["uuid"] not in excl and min(math.dist(q, rec["s"]), math.dist(q, rec["e"])) < tol:
            return True
        if kind in ("via", "pad") and g.distance(pq) < 1e-6:
            return True
    return False


def ends_on(ix, net, L, line, excl, w, keep=None):
    """same-net track ends (not of excl) lying on `line` within w / 2, or same-net vias / pads touching it (one that
    covers the point `keep`, where the new copper still ends, does not count)"""
    for g, kind, rec in ix.query(L, line.buffer(w / 2 + 0.01)):
        if rec["net"] != net:
            continue
        if kind == "trk" and rec["uuid"] not in excl and \
                any(line.distance(Point(q)) <= w / 2 + 1e-6 for q in (rec["s"], rec["e"])):
            return True
        if kind in ("via", "pad") and g.distance(line) <= w / 2 + 1e-6 and not (keep is not None and g.distance(Point(keep)) < 1e-6):
            return True
    return False


def samenet_touch(ix, net, L, g, excl):
    """new copper g touches unrelated same-net copper (a ring / doubled copper) or a same-net pad"""
    return any(rec["net"] == net and (kind == "pad" or (kind == "trk" and rec["uuid"] not in excl)) and og.intersects(g)
               for og, kind, rec in ix.query(L, g))


OCT_TOL = 0.5             # deg: a direction within this of a multiple of 45 deg is octilinear
JOINT_MIN = 89.5          # a new joint's interior angle at least this (qa_layout_quality ACUTE_DEG 90 - ANGLE_TOL_DEG)


def is_oct(a, b):
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 45.0
    return min(ang, 45.0 - ang) <= OCT_TOL


def oct_paths(a, b):
    """octilinear paths a -> b: straight when a -> b is octilinear, else the two 2-segment (straight + 45 deg) paths"""
    if math.dist(a, b) < 1e-6 or is_oct(a, b):
        return [[tuple(a), tuple(b)]]
    dx, dy = b[0] - a[0], b[1] - a[1]
    m = min(abs(dx), abs(dy))
    dg = (math.copysign(m, dx), math.copysign(m, dy))
    st = (dx - dg[0], dy - dg[1])
    return [[tuple(a), (a[0] + dg[0], a[1] + dg[1]), tuple(b)], [tuple(a), (a[0] + st[0], a[1] + st[1]), tuple(b)]]


def _attach(ix, n, L, q, w, excl):
    """what holds the point q (a track end of width w) besides the excl tracks -> [(kind, rec)] (the gate's joint rule:
    another end within min(w) / 2, q on another track's body within its w / 2, via / pad copper under q's end)"""
    out, pq = [], Point(q)
    for g, kind, rec in ix.query(L, pq.buffer(max(w, 0.05))):
        if rec["net"] != n or (kind == "trk" and rec["uuid"] in excl):
            continue
        if kind == "trk":
            if min(math.dist(q, rec["s"]), math.dist(q, rec["e"])) <= min(w, rec["w"]) / 2 + 1e-6 or \
                    trk_line(rec).distance(pq) <= rec["w"] / 2 + 1e-6:
                out.append((kind, rec))
        elif g.distance(pq) <= w / 2 + 1e-6:
            out.append((kind, rec))
    return out


def _arm_ok(q, d, w, att):
    """a new track leaving q towards d makes no ACUTE with the other arms held at q (the gate grades no joint on a
    pad / via)"""
    if any(kind in ("pad", "via") for kind, _ in att):
        return True
    for kind, rec in att:
        if min(math.dist(q, rec["s"]), math.dist(q, rec["e"])) <= min(w, rec["w"]) / 2 + 1e-6:
            far = rec["e"] if math.dist(q, rec["s"]) <= math.dist(q, rec["e"]) else rec["s"]
            if incl(far, q, d) < JOINT_MIN:
                return False
        else:                                             # q on a trunk body: a T-joint, >= 45 deg to the trunk
            a = incl(rec["s"], q, d)
            if min(a, 180 - a) < 45.0:
                return False
    return True


def micro_links(ix, n, L, pts, w):
    """same-net micro-segments (length <= w / 2) with both ends within w / 2 of the points pts: the gate folds them
    into one joint (no direction), so a rewrite of that joint removes them with it -> [track rec]"""
    out = []
    for q in pts:
        for g, kind, rec in ix.query(L, Point(q).buffer(w)):
            if kind == "trk" and rec["net"] == n and math.dist(rec["s"], rec["e"]) <= w / 2 + 1e-6 and \
                    all(min(math.dist(r, p) for p in pts) <= w / 2 + 1e-6 for r in (rec["s"], rec["e"])) and \
                    rec not in out:
                out.append(rec)
    return out


def collapse_pair(G, ix, lg, A, B, nets):
    """a doubled-back / overlapping same-net same-layer pair A, B (TRACK-FOLD, LOOP doubled copper) -> ((dels, adds,
    op), None) or (None, why). The pair's outer ends (held by other copper) are kept: two outer ends get one
    octilinear path between them (straight, or straight + 45 deg); three or more keep the longer segment and hang the
    shorter one's outer ends on it by a stub inside its copper. No new same-net contact; every pad / via / track the
    pair held stays held; no new acute joint at an outer end"""
    n, L = A["net"], A["layer"]
    mic = [m for m in micro_links(ix, n, L, [tuple(X[k]) for X in (A, B) for k in ("s", "e")], min(A["w"], B["w"]))
           if m["uuid"] not in (A["uuid"], B["uuid"])]
    pair = {A["uuid"], B["uuid"]} | {m["uuid"] for m in mic}
    old = unary_union([trk_cu(A), trk_cu(B)] + [trk_cu(m) for m in mic])
    ends = [(tuple(X[k]), X["w"], X, _attach(ix, n, L, tuple(X[k]), X["w"], pair)) for X in (A, B) for k in ("s", "e")]
    for g, kind, rec in ix.query(L, old):                 # a T-joint on the pair's body (not at an end) must stay
        if kind != "trk" or rec["net"] != n or rec["uuid"] in pair:
            continue
        for q in (rec["s"], rec["e"]):
            if any(trk_line(X).distance(Point(q)) <= X["w"] / 2 + 1e-6 for X in (A, B)) and \
                    not any(math.dist(q, e[0]) <= max(e[1], rec["w"]) / 2 + 1e-6 for e in ends):
                return None, "a T-joint lands on the pair's body"
    ext = []
    for q, w, X, att in ends:
        if att and not any(math.dist(q, e[0]) < 1e-3 for e in ext):
            ext.append((q, w, X, att))
    held = [(kind, g) for g, kind, rec in ix.query(L, old) if kind in ("pad", "via") and rec["net"] == n
            and g.intersects(old)]
    W = max(A["w"], B["w"])
    nm = nets[n]["name"]
    cands = []
    if len(ext) == 2:
        (q0, _, _, a0), (q1, _, _, a1) = ext
        for pts in oct_paths(q0, q1):
            pts = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) > 1e-6]
            if len(pts) < 2:
                continue
            cands.append(([(a, b, W) for a, b in zip(pts, pts[1:])], [A["uuid"], B["uuid"]] + [m["uuid"] for m in mic],
                          f"doubled-back pair collapsed to a {len(pts) - 1}-segment octilinear path",
                          [(q0, pts[1], a0), (q1, pts[-2], a1)]))
    elif len(ext) >= 3:
        K_, S = (A, B) if math.dist(A["s"], A["e"]) >= math.dist(B["s"], B["e"]) else (B, A)
        kl = trk_line(K_)
        segs, ok = [], all(_attach(ix, n, L, tuple(K_[k]), K_["w"], pair) for k in ("s", "e"))
        for q, w, X, att in ext:
            if not ok:
                break
            if X is not S or min(math.dist(q, K_["s"]), math.dist(q, K_["e"])) <= min(w, K_["w"]) / 2 + 1e-6:
                continue
            if kl.distance(Point(q)) > K_["w"] / 2 - 1e-4:
                ok = False
                break
            x = kl.interpolate(kl.project(Point(q))).coords[0]
            if math.dist(q, x) > 1e-4:
                segs.append((q, x, S["w"]))
        if ok:
            cands.append((segs, [S["uuid"]] + [m["uuid"] for m in mic], f"overlapping copy removed, {len(segs)} stub(s) onto the kept segment", []))
    else:
        return None, "the pair is held at fewer than two points"
    why = "no legal octilinear rewrite"
    for segs, dels, op, arms in cands:
        keep = [T for T in [A, B] + mic if T["uuid"] not in dels]
        newg = [LineString([a, b]).buffer(w / 2, 16) for a, b, w in segs] + [trk_cu(T) for T in keep]
        if not newg:
            continue
        new = unary_union(newg)
        bad = False
        for a, b, w in segs:
            g = LineString([a, b]).buffer(w / 2, 16)
            if g.difference(old.buffer(1e-3)).area > 1e-6 and not lg.seg_ok(n, L, a, b, w, old_sig_geo=old):
                bad, why = True, "not clear"
                break
        if not bad:
            for g, kind, rec in ix.query(L, new):         # no new same-net contact (no new ring / doubled copper)
                if rec["net"] == n and not (kind == "trk" and rec["uuid"] in pair) and g.intersects(new) \
                        and not g.intersects(old):
                    bad, why = True, "touches unrelated same-net copper"
                    break
        if not bad and any(not g.intersects(new) for _, g in held):
            bad, why = True, "a pad / via would come loose"
        if not bad:                                       # every track held at an outer end is still held
            nl = [(LineString([a, b]), w, a, b) for a, b, w in segs] + \
                 [(trk_line(T), T["w"], tuple(T["s"]), tuple(T["e"])) for T in keep]
            for q, w, X, att in ext:
                for kind, rec in att:
                    if kind != "trk":
                        continue
                    rs = [r for r in (rec["s"], rec["e"]) if math.dist(r, q) <= max(w, rec["w"]) / 2 + 1e-6]
                    if rs:
                        ok = any(min(math.dist(r, a), math.dist(r, b)) <= min(ww, rec["w"]) / 2 + 1e-6 or
                                 ln.distance(Point(r)) <= ww / 2 + 1e-6 for r in rs for ln, ww, a, b in nl)
                    else:                                 # q sat on rec's body: a new end must still sit there
                        ok = any(trk_line(rec).distance(Point(p)) <= rec["w"] / 2 + 1e-6
                                 for ln, ww, a, b in nl for p in (a, b))
                    if not ok:
                        bad, why = True, "an outer track would come loose"
                        break
                if bad:
                    break
        if bad:
            continue
        if any(not _arm_ok(q, d, W, att) for q, d, att in arms):
            why = "the new path would make an acute joint at an outer end"
            continue
        return (dels, [{"net": nm, "layer": L, "s": list(a), "e": list(b), "w": w} for a, b, w in segs], op), None
    return None, why


def near_joint(t1, t2):
    """the gate's joint (ends within min(w) / 2) of t1, t2 -> (end key of t1, end key of t2) or None"""
    tol = min(t1["w"], t2["w"]) / 2 + 1e-6
    sh = sorted(((math.dist(t1[x], t2[y]), x, y) for x in ("s", "e") for y in ("s", "e")))
    return (sh[0][1], sh[0][2]) if sh[0][0] <= tol else None


def _locked_hit(res, locked):
    return res is not None and bool(set(res[0]) & locked)


def fix_loops(G, loop_fails, blocked=(), edits=None, skip=(), free=lambda t: True, locked=frozenset()):
    """qa_copper_landing LOOP (doubled copper / short rings): on a LOOP net, same-net same-layer near-parallel
    (< 10 deg) segments whose copper overlaps without a plain joint between them are collapsed like a TRACK-FOLD pair"""
    ix, nets = Index(G), nets_of(G)
    lg = Legal(G, ix)
    code = {v["name"]: c for c, v in nets.items()}
    loopnets = {code[x["net"]] for x in loop_fails if x.get("net") in code}
    busy, unfixed = set(skip), []
    by = defaultdict(list)
    for t in G["tracks"]:
        if t["net"] in loopnets and math.dist(t["s"], t["e"]) > 1e-6 and free(t):
            by[(t["net"], t["layer"])].append(t)
    for (n, L), lst in sorted(by.items()):
        geo = [trk_line(t) for t in lst]
        tree = STRtree(geo)
        for i, t in enumerate(lst):
            for j in sorted(tree.query(geo[i].buffer(t["w"]))):
                o = lst[j]
                if j <= i or {t["uuid"], o["uuid"]} & busy:
                    continue
                if geo[i].distance(geo[j]) >= (t["w"] + o["w"]) / 2 - 1e-4:
                    continue
                a = incl(t["e"], t["s"], (t["s"][0] + o["e"][0] - o["s"][0], t["s"][1] + o["e"][1] - o["s"][1]))
                if min(a, 180 - a) > 10.0:
                    continue                                   # a crossing / ordinary bend, not doubled copper
                nj = near_joint(t, o)
                if nj and incl(other_end(t, nj[0]), t[nj[0]], other_end(o, nj[1])) > 10.0:
                    continue                                   # a plain straight-on joint
                key = ("LOOP",) + tuple(sorted((t["uuid"], o["uuid"])))
                if key in blocked:
                    unfixed.append({"net": nets[n]["name"], "at": list(t["s"]), "why": "blocked by the arbiter"})
                    continue
                res, why = collapse_pair(G, ix, lg, t, o, nets)
                if res is None or _locked_hit(res, locked):
                    res, why = try_knot(G, ix, lg, t, o, nets)
                if _locked_hit(res, locked):
                    res, why = None, "the rewrite would delete locked copper"
                if res is not None and busy & set(res[0]):
                    res, why = None, "overlaps an earlier rewrite"
                if res is None:
                    unfixed.append({"net": nets[n]["name"], "at": list(t["s"]), "why": why})
                    continue
                dels, adds, op = res
                busy |= {t["uuid"], o["uuid"]} | set(dels)
                for a_ in adds:
                    lg.extra[L].append((LineString([a_["s"], a_["e"]]).buffer(a_["w"] / 2), n))
                if edits is not None:
                    edits.append({"key": key, "class": "LOOP", "net": nets[n]["name"], "at": list(t["s"]), "op": op,
                                  "dels": dels, "adds": adds, "touch": [t["uuid"], o["uuid"]]})
    return unfixed


def find_dead(G, free=lambda t: True):
    """dead copper: a same-net, single-layer track cluster (copper touching) that no via reaches, that lies in no
    own-net fill and that touches exactly ONE pad. It joins nothing to anything (a ring or stub hanging off one pad:
    collapsing part of it would leave a TRACK-END), so the whole cluster goes. -> [{net, pad, tracks: [uuid]}]"""
    nets = nets_of(G)
    ix = Index(G)
    fz = defaultdict(list)
    for z in G["zones"]:
        if not z["rule_area"] and z["net"]:
            for L, rs in z.get("fills", {}).items():
                fz[(z["net"], L)] += [cugraph.ring_poly(r) for r in rs]
    out = []
    for ts, vs, pad in track_components(G):
        if vs or not pad or not ts:
            continue
        T = [t for t in G["tracks"] if t["uuid"] in set(ts)]
        if len({t["layer"] for t in T}) != 1 or not all(free(t) for t in T):
            continue
        n, L = T[0]["net"], T[0]["layer"]
        cu = unary_union([trk_cu(t) for t in T])
        pads = {rec["uuid"]: rec for g, kind, rec in ix.query(L, cu) if kind == "pad" and rec["net"] == n
                and g.intersects(cu)}
        if len(pads) != 1 or any(g.intersects(cu) for g in fz.get((n, L), ())):
            continue
        if any(kind == "via" and rec["net"] == n and g.intersects(cu) for g, kind, rec in ix.query(L, cu)):
            continue
        p = next(iter(pads.values()))
        out.append({"net": nets[n]["name"], "pad": f"{p.get('ref')}.{p.get('num')}", "tracks": sorted(ts),
                    "at": list(T[0]["s"])})
    return out


KNOT_MAX = 8              # a knot holds at most this many segments
KNOT_SEG_MM = 1.5         # ... each no longer than this (longer runs are the knot's outside)


def knot_of(ix, A, B):
    """the knot around a pair: same-net same-layer segments <= KNOT_SEG_MM whose copper touches it, transitively
    (at most KNOT_MAX); None when it grows past that"""
    n, L = A["net"], A["layer"]
    mem = {A["uuid"]: A, B["uuid"]: B}
    todo = [A, B]
    while todo:
        t = todo.pop()
        g0 = trk_cu(t)
        for g, kind, rec in ix.query(L, g0):
            if kind != "trk" or rec["net"] != n or rec["uuid"] in mem or not g.intersects(g0):
                continue
            if math.dist(rec["s"], rec["e"]) > KNOT_SEG_MM:
                continue
            mem[rec["uuid"]] = rec
            todo.append(rec)
            if len(mem) > KNOT_MAX:
                return None
    return list(mem.values())


def collapse_knot(G, ix, lg, M, nets):
    """a knot M (doubled / folded short segments of one net and layer) -> ((dels, adds, op), None) or (None, why): the
    points where outside copper holds it are joined by octilinear paths along a minimum spanning tree (one path per
    tree edge), width = the knot's widest. Same checks as collapse_pair"""
    n, L = M[0]["net"], M[0]["layer"]
    ids = {t["uuid"] for t in M}
    old = unary_union([trk_cu(t) for t in M])
    W = max(t["w"] for t in M)
    ext = []                                              # (point, attachments)
    for t in M:
        for k in ("s", "e"):
            q = tuple(t[k])
            att = _attach(ix, n, L, q, t["w"], ids)
            if att and not any(math.dist(q, e[0]) <= W / 2 for e in ext):
                ext.append((q, att))
    for g, kind, rec in ix.query(L, old):                 # outside track ends on the knot's copper are held points
        if kind != "trk" or rec["net"] != n or rec["uuid"] in ids:
            continue
        for q in (tuple(rec["s"]), tuple(rec["e"])):
            if old.distance(Point(q)) < 1e-6 and not any(math.dist(q, e[0]) <= W / 2 for e in ext):
                ext.append((q, [("trk", rec)]))
    if len(ext) < 2:
        return None, "the knot is held at fewer than two points"
    if len(ext) > 4:
        return None, "the knot is held at more than four points"
    held = [g for g, kind, rec in ix.query(L, old) if kind in ("pad", "via") and rec["net"] == n and g.intersects(old)]
    inn, edges = {0}, []
    while len(inn) < len(ext):
        i, j = min(((i, j) for i in inn for j in range(len(ext)) if j not in inn),
                   key=lambda ij: math.dist(ext[ij[0]][0], ext[ij[1]][0]))
        edges.append((i, j))
        inn.add(j)
    segs, arms = [], []
    for i, j in edges:
        a, b = ext[i][0], ext[j][0]
        ok = None
        for pts in oct_paths(a, b):
            pts = [p for k, p in enumerate(pts) if k == 0 or math.dist(p, pts[k - 1]) > 1e-6]
            if len(pts) < 2:
                continue
            good = True
            for p, q in zip(pts, pts[1:]):
                g = LineString([p, q]).buffer(W / 2, 16)
                if g.difference(old.buffer(1e-3)).area > 1e-6 and not lg.seg_ok(n, L, p, q, W, old_sig_geo=old):
                    good = False
                    break
            if good:
                ok = pts
                break
        if ok is None:
            return None, "no legal octilinear path between two held points"
        segs += [(p, q) for p, q in zip(ok, ok[1:])]
        arms += [(a, ok[1], ext[i][1]), (b, ok[-2], ext[j][1])]
    segs = [(p, q) for p, q in segs if math.dist(p, q) > 1e-6]
    if not segs:
        return None, "nothing to draw"
    new = unary_union([LineString([p, q]).buffer(W / 2, 16) for p, q in segs])
    for g, kind, rec in ix.query(L, new):
        if rec["net"] == n and not (kind == "trk" and rec["uuid"] in ids) and g.intersects(new) and not g.intersects(old):
            return None, "touches unrelated same-net copper"
    if any(not g.intersects(new) for g in held):
        return None, "a pad / via would come loose"
    if any(not _arm_ok(q, d, W, att) for q, d, att in arms):
        return None, "a path would make an acute joint at a held point"
    nm = nets[n]["name"]
    return ([t["uuid"] for t in M], [{"net": nm, "layer": L, "s": list(p), "e": list(q), "w": W} for p, q in segs],
            f"knot of {len(M)} segments re-drawn as {len(segs)} octilinear segments ({len(ext)} held points)"), None


def try_knot(G, ix, lg, A, B, nets):
    M = knot_of(ix, A, B)
    if M is None or len(M) < 2:
        return None, "knot too big"
    return collapse_knot(G, ix, lg, M, nets)


def fix_folds(G, fails, blocked=(), edits=None, locked=frozenset()):
    """qa_layout_quality TRACK-FOLD: collapse to the pair's outer ends (octilinear), else (a) a spike at a 2-end joint
    (the shorter arm lies on the longer one): the longer arm is re-drawn to end at the shorter arm's far end and the
    shorter arm goes; (b) a partial collinear overlap: the overlapped end of one segment is pulled back to the other's
    end. Locked segments are never rewritten."""
    ix, nets = Index(G), nets_of(G)
    lg = Legal(G, ix)
    T = {t["uuid"]: t for t in G["tracks"]}
    busy, unfixed = set(), []
    for it in fails.get("TRACK-FOLD", []):
        us = [u for u in it.get("uuids", []) if u in T]
        if len(us) != 2 or busy & set(us):
            continue
        key = ("FOLD",) + tuple(sorted(us))
        if key in blocked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "blocked by the arbiter"})
            continue
        t1, t2 = T[us[0]], T[us[1]]
        if t1["layer"] != t2["layer"]:
            continue
        n, L = t1["net"], t1["layer"]
        res, cwhy = collapse_pair(G, ix, lg, t1, t2, nets)
        if res is None or _locked_hit(res, locked):
            res, kwhy = try_knot(G, ix, lg, t1, t2, nets)
        if _locked_hit(res, locked) or (res is not None and busy & set(res[0])):
            res = None
        if res is not None:
            gone, new, op = res
            busy |= set(us) | set(gone)
            for a_ in new:
                lg.extra[L].append((LineString([a_["s"], a_["e"]]).buffer(a_["w"] / 2), n))
            if edits is not None:
                edits.append({"key": key, "class": "TRACK-FOLD", "net": nets[n]["name"], "at": list(it["at"]),
                              "op": op, "dels": gone, "adds": new})
            continue
        ends = [(x, y) for x in ("s", "e") for y in ("s", "e") if math.dist(t1[x], t2[y]) < 1e-3]
        new, gone, op = None, None, None
        if ends:
            x, y = ends[0]
            f1, f2 = other_end(t1, x), other_end(t2, y)
            if math.dist(t1[x], f1) <= math.dist(t2[y], f2):
                sf, long_, lf = f1, t2, f2
            else:
                sf, long_, lf = f2, t1, f1
            J = tuple(t1[x])
            if joint_busy(ix, n, L, J, {t1["uuid"], t2["uuid"]}):
                unfixed.append({"net": it["net"], "at": it["at"], "why": "spike joint is a branch / via / pad"})
                continue
            if LineString([lf, J]).distance(Point(sf)) > min(t1["w"], t2["w"]) / 4:
                unfixed.append({"net": it["net"], "at": it["at"], "why": "arms not collinear"})
                continue
            if LineString([lf, J]).distance(Point(sf)) > 0.01 and \
                    not lg.seg_ok(n, L, tuple(lf), tuple(sf), long_["w"], old_sig_geo=trk_cu(t1).union(trk_cu(t2))):
                unfixed.append({"net": it["net"], "at": it["at"], "why": "near-collinear re-draw not clear"})
                continue
            cut = LineString([sf, J]).difference(Point(sf).buffer(1e-3)) if math.dist(sf, J) > 2e-3 else None
            if cut is not None and not cut.is_empty and ends_on(ix, n, L, cut, {t1["uuid"], t2["uuid"]}, 0.0, keep=sf):
                unfixed.append({"net": it["net"], "at": it["at"], "why": "a T-joint lies on the removed piece"})
                continue
            gone = [t1["uuid"], t2["uuid"]]
            new = [{"net": nets[n]["name"], "layer": L, "s": list(lf), "e": list(sf), "w": long_["w"]}] \
                if math.dist(lf, sf) > 1e-6 else []
            op = "spike removed (shorter arm deleted, longer arm ends at its far end)"
        else:
            for A, B in ((t1, t2), (t2, t1)):
                for ea in ("s", "e"):
                    E = tuple(A[ea])
                    if LineString([B["s"], B["e"]]).distance(Point(E)) > 0.01 or \
                            min(math.dist(E, B["s"]), math.dist(E, B["e"])) < 1e-3:
                        continue
                    F = other_end(A, ea)
                    inner = [q for q in (B["s"], B["e"])
                             if LineString([E, F]).distance(Point(q)) < 0.01 and math.dist(q, E) > 1e-3]
                    if not inner or joint_busy(ix, n, L, E, {A["uuid"], B["uuid"]}):
                        continue
                    X = min(inner, key=lambda q: math.dist(q, E))
                    gone = [A["uuid"]]
                    new = [{"net": nets[n]["name"], "layer": L, "s": list(X), "e": list(F), "w": A["w"]}]
                    op = "overlap trimmed (end moved to the other segment's end)"
                    break
                if new is not None:
                    break
            if new is None:
                unfixed.append({"net": it["net"], "at": it["at"], "why": "no safe trim"})
                continue
        if set(gone) & locked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "the fix would rewrite locked copper"})
            continue
        busy |= set(us)
        if edits is not None:
            edits.append({"key": key, "class": "TRACK-FOLD", "net": nets[n]["name"], "at": list(it["at"]), "op": op,
                          "dels": gone, "adds": new})
    return unfixed


def fix_acute(G, fails, blocked=(), edits=None, locked=frozenset()):
    """qa_layout_quality ACUTE at a 2-end joint off pads / vias (the gate's joint: ends within min(w) / 2): the corner
    is cut by one straight segment between a point on each arm, octilinear cuts first (90 / 135 deg joints), then any
    cut with both new joints >= ACUTE_OK, nearest first; with no legal cut the turn is re-anchored (collapse_pair:
    one octilinear path between the arms' far ends). Pre-checked against foreign copper, keep-outs, unrelated same-net
    copper and T-joints / vias on the removed corner. Locked segments are never rewritten."""
    ix, nets = Index(G), nets_of(G)
    lg = Legal(G, ix)
    T = {t["uuid"]: t for t in G["tracks"]}
    busy, unfixed = set(), []
    grid = [round(0.05 * i, 3) for i in range(1, 31)]
    for it in fails.get("ACUTE", []):
        us = [u for u in it.get("uuids", []) if u in T]
        if len(us) != 2 or busy & set(us) or it.get("ends", 2) != 2:
            continue
        key = ("ACUTE",) + tuple(sorted(us))
        if key in blocked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "blocked by the arbiter"})
            continue
        if set(us) & locked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "locked copper"})
            continue
        t1, t2 = T[us[0]], T[us[1]]
        if t1["layer"] != t2["layer"]:
            continue
        n, L = t1["net"], t1["layer"]
        nj = near_joint(t1, t2)
        if nj is None:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "not an end-to-end joint"})
            continue
        e1, e2 = nj
        J1, J2 = tuple(t1[e1]), tuple(t2[e2])
        J = J1
        P1, P2 = tuple(other_end(t1, e1)), tuple(other_end(t2, e2))
        th = incl(P1, J1, (J1[0] + P2[0] - J2[0], J1[1] + P2[1] - J2[1]))
        mic = [m for m in micro_links(ix, n, L, [J1, J2], min(t1["w"], t2["w"])) if m["uuid"] not in us]
        if {m["uuid"] for m in mic} & locked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "locked copper"})
            continue
        ex = {t1["uuid"], t2["uuid"]} | {m["uuid"] for m in mic}
        if th >= 90.0 or joint_busy(ix, n, L, J1, ex) or joint_busy(ix, n, L, J2, ex):
            continue
        L1, L2 = math.dist(J1, P1), math.dist(J2, P2)
        w = max(t1["w"], t2["w"])
        old = unary_union([trk_cu(t1), trk_cu(t2)] + [trk_cu(m) for m in mic])
        best, why = None, "no legal corner cut"
        u1 = ((P1[0] - J1[0]) / max(L1, 1e-9), (P1[1] - J1[1]) / max(L1, 1e-9))
        u2 = ((P2[0] - J2[0]) / max(L2, 1e-9), (P2[1] - J2[1]) / max(L2, 1e-9))
        cands = []                                 # octilinear cuts first (90 / 135 deg joints), nearest first
        cr = lambda a, b: a[0] * b[1] - a[1] * b[0]  # noqa: E731
        for k8 in range(8):
            c = (math.cos(k8 * math.pi / 4), math.sin(k8 * math.pi / 4))
            den = cr(u2, c)
            if abs(den) < 1e-9:
                continue
            for d1 in [round(0.025 * i, 3) for i in range(1, 61)]:
                if d1 > L1 - 0.05:
                    break
                d2 = (d1 * cr(u1, c) - cr((J2[0] - J1[0], J2[1] - J1[1]), c)) / den
                if 0.025 <= d2 <= L2 - 0.05:
                    cands.append((d1 + d2, 0, d1, d2))
        cands.sort()
        cands += [(a + b, 1, a, b) for a, b in sorted(((a, b) for a in grid if a < L1 - 0.05 for b in grid if b < L2 - 0.05),
                                                       key=lambda x: (x[0] + x[1], abs(x[0] - x[1])))]
        for _, kind, d1, d2 in cands:
            C1, C2 = lerp(J1, P1, d1), lerp(J2, P2, d2)
            lim = JOINT_MIN if kind == 0 else ACUTE_OK
            if math.dist(C1, C2) < 0.05 or incl(P1, C1, C2) < lim or incl(C1, C2, P2) < lim:
                continue
            if ends_on(ix, n, L, LineString([C1, J1]), ex, t1["w"]) or ends_on(ix, n, L, LineString([C2, J2]), ex, t2["w"]):
                why = "a T-joint / via lies on the corner"
                continue
            g = LineString([C1, C2]).buffer(w / 2, 16)
            if samenet_touch(ix, n, L, g, ex):
                why = "touches unrelated same-net copper"
                continue
            if not lg.seg_ok(n, L, C1, C2, w, old_sig_geo=old):
                why = "not clear"
                continue
            best = (C1, C2)
            break
        if best is None and th < 90.0:
            res, cwhy = collapse_pair(G, ix, lg, t1, t2, nets)   # re-anchor the turn: octilinear path P1 -> P2
            if res is None or _locked_hit(res, locked):
                res, kwhy = try_knot(G, ix, lg, t1, t2, nets)
                cwhy += "; knot: " + kwhy if res is None else ""
            if _locked_hit(res, locked):
                res, cwhy = None, "the rewrite would delete locked copper"
            if res is not None and busy & set(res[0]):
                res, cwhy = None, "overlaps an earlier rewrite"
            if res is not None:
                dels, adds, op = res
                busy |= set(us) | set(dels)
                for a_ in adds:
                    lg.extra[L].append((LineString([a_["s"], a_["e"]]).buffer(a_["w"] / 2), n))
                if edits is not None:
                    edits.append({"key": key, "class": "ACUTE", "net": nets[n]["name"], "at": list(J),
                                  "op": f"turn re-anchored ({th:.0f} deg): " + op, "dels": dels, "adds": adds})
                continue
            why += "; re-anchor: " + cwhy
        if best is None:
            unfixed.append({"net": it["net"], "at": it["at"], "angle": round(th, 1), "why": why})
            continue
        C1, C2 = best
        nm = nets[n]["name"]
        busy |= set(us)
        lg.extra[L].append((LineString([C1, C2]).buffer(w / 2), n))
        if edits is not None:
            edits.append({"key": key, "class": "ACUTE", "net": nm, "at": list(J), "op": f"corner cut ({th:.0f} deg)",
                          "dels": [t1["uuid"], t2["uuid"]] + [m["uuid"] for m in mic],
                          "adds": [{"net": nm, "layer": L, "s": list(P1), "e": list(C1), "w": t1["w"]},
                                   {"net": nm, "layer": L, "s": list(C1), "e": list(C2), "w": w},
                                   {"net": nm, "layer": L, "s": list(C2), "e": list(P2), "w": t2["w"]}]})
    return unfixed


def fix_hops(G, fails, blocked=(), edits=None, locked=frozenset()):
    """qa_layout_quality VIA-HOP (two same-net vias < VIA_HOP_MM apart sharing copper on one layer: down and straight
    back up): when each via carries exactly one other track, both on the same layer Y, and the hop layer holds exactly
    the one connecting track, both vias and the hop go and the two Y tracks are joined by a straight or a two-segment L
    run on Y (legal, joints >= ACUTE_OK, no unrelated same-net contact). Vias touching a pad or an own-net fill, and
    locked vias / tracks, are left."""
    ix, nets = Index(G), nets_of(G)
    lg = Legal(G, ix)
    Vd = {v["uuid"]: v for v in G["vias"]}
    fz = defaultdict(list)
    for z in G["zones"]:
        if not z["rule_area"] and z["net"]:
            for L, rs in z.get("fills", {}).items():
                fz[(z["net"], L)] += [cugraph.ring_poly(r) for r in rs]
    busy, unfixed = set(), []
    for it in fails.get("VIA-HOP", []):
        us = [u for u in it.get("uuids", []) if u in Vd]
        if len(us) != 2 or busy & set(us):
            continue
        key = ("HOP",) + tuple(sorted(us))
        if key in blocked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "blocked by the arbiter"})
            continue
        if set(us) & locked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "locked via"})
            continue
        v1, v2 = Vd[us[0]], Vd[us[1]]
        n = v1["net"]
        why = None
        att = {}
        for v in (v1, v2):
            d = via_disc(v)
            tr = defaultdict(list)
            for L in vlayers(G, v):
                for g, kind, rec in ix.query(L, d):
                    if rec["net"] != n or not g.intersects(d) or rec is v:
                        continue
                    if kind == "pad":
                        why = "a via touches a pad"
                    elif kind == "trk":
                        tr[L].append(rec)
                if any(fg.intersects(d) for fg in fz.get((n, L), ())):
                    why = "a via lies in an own-net fill"
            att[v["uuid"]] = tr
        if why:
            unfixed.append({"net": it["net"], "at": it["at"], "why": why})
            continue
        a1, a2 = att[v1["uuid"]], att[v2["uuid"]]
        hop_layers = [L for L in a1 if any(t in a2.get(L, []) for t in a1[L])]
        if len(hop_layers) != 1:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "not a single-track hop"})
            continue
        X = hop_layers[0]
        h = a1[X]
        if len(h) != 1 or a2.get(X) != h or h[0]["uuid"] in locked:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "hop layer carries more than the hop track / locked"})
            continue
        o1 = [t for L, ts in a1.items() if L != X for t in ts]
        o2 = [t for L, ts in a2.items() if L != X for t in ts]
        if len(o1) != 1 or len(o2) != 1 or o1[0]["layer"] != o2[0]["layer"] or o1[0]["uuid"] == o2[0]["uuid"]:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "vias carry more than one other track"})
            continue
        t1, t2, Y = o1[0], o2[0], o1[0]["layer"]
        k1 = "s" if math.dist(t1["s"], (v1["x"], v1["y"])) <= math.dist(t1["e"], (v1["x"], v1["y"])) else "e"
        k2 = "s" if math.dist(t2["s"], (v2["x"], v2["y"])) <= math.dist(t2["e"], (v2["x"], v2["y"])) else "e"
        q1, q2 = tuple(t1[k1]), tuple(t2[k2])
        f1, f2 = tuple(other_end(t1, k1)), tuple(other_end(t2, k2))
        w = min(t1["w"], t2["w"])
        ex = {t1["uuid"], t2["uuid"], h[0]["uuid"]}
        best = None
        for pts in ([q1, q2], [q1, (q1[0], q2[1]), q2], [q1, (q2[0], q1[1]), q2]):
            pts = [p_ for i_, p_ in enumerate(pts) if i_ == 0 or math.dist(p_, pts[i_ - 1]) > 1e-6]
            if len(pts) < 2:
                continue
            seq = [f1] + pts + [f2]
            if any(incl(seq[i - 1], seq[i], seq[i + 1]) < ACUTE_OK for i in range(1, len(seq) - 1)):
                continue
            ok = True
            for a, b in zip(pts, pts[1:]):
                g = LineString([a, b]).buffer(w / 2, 16)
                if samenet_touch(ix, n, Y, g, ex) or not lg.seg_ok(n, Y, a, b, w):
                    ok = False
                    break
            if ok:
                best = pts
                break
        if best is None:
            unfixed.append({"net": it["net"], "at": it["at"], "why": "no legal straight / L run on " + Y})
            continue
        nm = nets[n]["name"]
        busy |= set(us)
        for a, b in zip(best, best[1:]):
            lg.extra[Y].append((LineString([a, b]).buffer(w / 2), n))
        if edits is not None:
            edits.append({"key": key, "class": "VIA-HOP", "net": nm, "at": [v1["x"], v1["y"]],
                          "op": f"hop via pair removed, {len(best) - 1}-segment {Y} run",
                          "dels": [v1["uuid"], v2["uuid"], h[0]["uuid"]],
                          "adds": [{"net": nm, "layer": Y, "s": list(a), "e": list(b), "w": w}
                                   for a, b in zip(best, best[1:])]})
    return unfixed


def stitch_plan(G, fails, blocked=(), edits=None):
    """qa_layout_quality POUR-STITCH (density AND reach, the constants VIA-BARE keeps): each short fragment gets through
    vias of its net (the net's commonest via size) by greedy farthest-point placement on a 0.4 mm grid until it holds
    max(STITCH_MIN_VIAS, area / STITCH_MM2_PER_VIA) plane-reaching links and no point is farther than STITCH_REACH_MM
    from one: disc inside the fragment and inside the net's inner plane fill, clear of all other-net copper on every
    layer (PRI-SEC 2.00 mm included) and of every rule area, >= STITCH_PAD_GAP from every SMD pad, >= STITCH_VIA_GAP
    from every via, hole-to-hole and edge clear. One edit per via (key = net, layer, position)."""
    lg = Legal(G, Index(G))
    code = {v["name"]: int(k) for k, v in G["nets"].items()}
    smd = [g for p in G["pads"] if is_smd(p) for g in pad_geo(p).values() if g is not None and not g.is_empty]
    smd_tree = STRtree(smd) if smd else None
    allv = [(v["x"], v["y"]) for v in G["vias"]]
    unfixed = []
    for it in fails.get("POUR-STITCH", []):
        nm, Lf = it.get("net"), it.get("layer")
        if nm not in code:
            continue
        n = code[nm]
        isl = fill_islands(G, {n})
        at = Point(it["at"])
        frags = [g for _, L_, g in isl if L_ == Lf]
        frag = min(frags, key=lambda g: g.distance(at)) if frags else None
        if frag is None or frag.distance(at) > 0.5:
            unfixed.append({"net": nm, "layer": Lf, "at": it["at"], "why": "fragment not found"})
            continue
        if any(k[0] == "STITCH" and k[1] == nm and k[2] == Lf and frag.distance(Point(k[3], k[4])) < 0.05
               for k in blocked if isinstance(k, tuple) and len(k) == 5):
            unfixed.append({"net": nm, "layer": Lf, "at": it["at"], "why": "a stitch here was blocked by the arbiter"})
            continue
        planes = [unary_union([g for _, L_, g in isl if L_ == L]) for L in INNER]
        planes = [pl for pl in planes if not pl.is_empty]
        sizes = Counter((v["d"], v["drill"]) for v in G["vias"] if v["net"] == n) or Counter({(0.6, 0.3): 1})
        d, drill = sizes.most_common(1)[0][0]
        need = max(STITCH_MIN_VIAS, math.ceil(frag.area / STITCH_MM2_PER_VIA))
        links = [(v["x"], v["y"]) for v in G["vias"] if v["net"] == n and frag.intersects(via_disc(v))
                 and any(pl.intersects(via_disc(v)) for pl in planes)]
        links += [(p["x"], p["y"]) for p in G["pads"] if p["net"] == n and is_pth(p) and frag.intersects(Point(p["x"], p["y"]))]

        def far_region():
            return frag.difference(unary_union([Point(q).buffer(STITCH_REACH_MM, 16) for q in links])) if links else frag

        def short():
            return len(links) < need or far_region().area > STITCH_REACH_TOL_MM2
        inner = frag.buffer(-(d / 2 + 0.02))
        if inner.is_empty or not short():
            if short():
                unfixed.append({"net": nm, "layer": Lf, "at": it["at"], "why": "fragment too thin for a via"})
            continue
        x0, y0, x1, y1 = inner.bounds
        cands = [(round(x0 + i * 0.4, 2), round(y0 + j * 0.4, 2)) for i in range(int((x1 - x0) / 0.4) + 1)
                 for j in range(int((y1 - y0) / 0.4) + 1)]
        if cands:
            ca = np.array(cands)
            cands = [q for q, inside in zip(cands, shapely.contains_xy(inner, ca[:, 0], ca[:, 1])) if inside]
        legal = {}

        def ok(q):
            if q in legal:
                return legal[q]
            c = Point(q)
            disc = c.buffer(d / 2, 16)
            good = any(pl.contains(disc) for pl in planes)
            good = good and c.distance(lg.edge) >= lg.rules.get("edge_clearance", 0.3) + d / 2 + SAFE
            good = good and not any(lg.areas[j][0].intersects(disc) for j in lg.atree.query(disc))
            if good and smd_tree is not None:
                good = not any(smd[j].distance(disc) < STITCH_PAD_GAP for j in smd_tree.query(disc.buffer(STITCH_PAD_GAP)))
            if good:
                h2h = lg.rules.get("hole_to_hole", 0.25)
                good = not any(lg.drills[j][0].distance(c) - lg.drills[j][1] / 2 - drill / 2 < h2h + SAFE
                               for j in lg.dtree.query(c.buffer(2.0)))
            if good:
                good = all(lg.copper_ok(n, L, disc, "via") for L in G["layers"])
            legal[q] = good
            return good
        def usable(q):
            return ("STITCH", nm, Lf, q[0], q[1]) not in blocked and \
                not any(math.dist(q, z) < STITCH_VIA_GAP for z in allv) and ok(q)
        added, cap = 0, need + 30
        while added < cap:
            best = None
            far = far_region()
            if far.area > STITCH_REACH_TOL_MM2 and cands:
                # reach: the legal spot covering the most of the uncovered area (sampled on a 0.25 mm grid, plus one
                # point per uncovered piece); a spot that covers nothing new is never placed (the gate would call it
                # VIA-BARE)
                fx0, fy0, fx1, fy1 = far.bounds
                gx, gy = np.meshgrid(np.arange(fx0, fx1 + 0.25, 0.25), np.arange(fy0, fy1 + 0.25, 0.25))
                gx, gy = gx.ravel(), gy.ravel()
                inside = shapely.contains_xy(far, gx, gy)
                fp = [(x, y) for x, y, i in zip(gx, gy, inside) if i]
                fp += [g.representative_point().coords[0] for g in getattr(far, "geoms", [far]) if not g.is_empty]
                fp = np.array(fp)
                R = STITCH_REACH_MM - 0.01
                near = [q for q in cands if fx0 - R <= q[0] <= fx1 + R and fy0 - R <= q[1] <= fy1 + R]
                if near:
                    ca = np.array(near)
                    gain = np.zeros(len(near), dtype=int)
                    for s in range(0, len(fp), 512):           # bounded memory: candidates x 512 far points at a time
                        f_ = fp[s:s + 512]
                        gain += (((ca[:, 0:1] - f_[None, :, 0]) ** 2 + (ca[:, 1:2] - f_[None, :, 1]) ** 2) < R * R).sum(axis=1)
                    for j in np.argsort(-gain, kind="stable"):
                        if gain[j] <= 0:
                            break
                        q = near[int(j)]
                        if usable(q):
                            best = q
                            break
            elif len(links) < need:              # density only: farthest from every link
                for q in sorted(cands, key=lambda q: (-min([math.dist(q, z) for z in links] or [99.0]), q)):
                    if usable(q):
                        best = q
                        break
            else:
                break
            if best is None:
                break
            q, k = best, ("STITCH", nm, Lf, best[0], best[1])
            links.append(q)
            allv.append(q)
            added += 1
            for L in G["layers"]:
                lg.extra[L].append((Point(q).buffer(d / 2), n))
            if edits is not None:
                edits.append({"key": k, "class": "POUR-STITCH", "net": nm, "at": list(q),
                              "op": f"stitch via {d}/{drill} into the {Lf} fragment ({it.get('area_mm2')} mm2)",
                              "vias": [{"net": nm, "x": q[0], "y": q[1], "d": d, "drill": drill}]})
        if short():
            unfixed.append({"net": nm, "layer": Lf, "at": it["at"], "need": need, "added": added,
                            "why": "no further legal stitch spot"})
    return unfixed


# ======================================================================================== arbitration
LQ_POINT = ("VIA-INPAD", "VIA-PADGAP", "XSTACK", "TRACK-FOLD", "ACUTE", "THREAD", "POWER-PAD-CONN", "VIA-CURRENT",
            "NECK-SMALLPAD", "DECAP-LOOP", "XTAL", "PAD-AXIS", "VIA-HOP", "SERIES-TERM", "PLANE-SLOT")
DRC_WARN_GUARD = {"track_dangling", "via_dangling", "isolated_copper", "connection_width", "copper_sliver",
                  "hole_to_hole", "holes_co_located", "padstack", "net_conflict"}
NEAR_MM, FAR_MM, LQ_FAR_MM = 0.6, 3.0, 5.0     # attribution radii (UI B8.1 method; FAR for refill-mediated effects)
MAX_REPLAYS = 6
POUR_CLR_MM = 0.5          # a pour split: edits within this of the split pour's former fill are suspects
ESCALATE_MM = 1.5          # from the 2nd replay on, a new finding blocks every edit within this of it (fast convergence)


def kjson(k):
    return [list(x) if isinstance(x, tuple) else x for x in k]


def ktuple(k):
    return tuple(tuple(x) if isinstance(x, list) else x for x in k)


def _pt(s):
    return [Point(float(a), float(b)) for a, b in re.findall(r"\(\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)", s or "")]


def _at(x):
    at = x.get("at")
    if isinstance(at, (list, tuple)) and len(at) == 2 and isinstance(at[0], (int, float)):
        return Point(at)
    return None


def drc_guarded(d):
    return [v for v in d.get("violations", []) if v.get("severity") == "error" or
            (v.get("severity") == "warning" and v["type"] in DRC_WARN_GUARD)]


class Ctx:
    """one replay: the board, its geometry, the edits so far (with their copper for attribution) and the step trace
    (a snapshot before each step) that lets the next replay resume at the first step whose edits changed"""

    def __init__(self, board, locked, d0, base_fails, base_full, blocked, snapdir, do_smooth, do_bare, log):
        self.board, self.locked, self.d0, self.base_fails = Path(board), locked, d0, base_fails
        self.base_full = base_full                       # the full copper gate of the refilled input (TRACK-JOG sites)
        self.blocked, self.snapdir, self.do_smooth, self.do_bare, self.log = blocked, Path(snapdir), do_smooth, do_bare, log
        self.src = self.G0 = self.G = None
        self.edits, self.geo, self.unfixed = [], [], {}
        self.trace, self.prev, self.resume_at, self.i = [], None, None, 0
        self.round_gate = None                           # the gate read at the start of a round (its later steps)
        self.locked_skipped = []
        self.pe_cache = {}                               # via uuid -> previous replay's padedge result (re-validated)
        self._gate = (None, None)
        self.times = defaultdict(float)

    def sha(self):
        return hashlib.sha256(self.board.read_bytes()).hexdigest()

    def gate(self):
        h = self.sha()
        if self._gate[0] != h:
            t = time.time()
            self._gate = (h, run_gate(self.board, fast=True)["fails"])
            self.times["gate"] += time.time() - t
        return self._gate[1]

    def lq(self):
        t = time.time()
        r = run_lq(self.board)["fails"]
        self.times["lq"] += time.time() - t
        return r

    def free(self, uuid=None):
        return uuid is None or uuid not in self.locked

    def split_region(self, k, spots):
        """where the refill took fill away from the split pour: the input's own-net fill islands of net k[1] that touch
        the split pads / items, minus that net's fill after the run's refill, per layer (+ POUR_CLR_MM); None if the
        net has no fill there"""
        if not hasattr(self, "_isl"):
            self._G0o, self._isl = json.loads(self.G0), {}
        code = {v["name"]: int(c) for c, v in self._G0o["nets"].items()}.get(k[1])
        if code is None:
            return None
        if code not in self._isl:
            self._isl[code] = fill_islands(self._G0o, {code})
        hit = [(L, g) for _, L, g in self._isl[code] if any(g.distance(sp) < 0.3 for sp in spots)]
        if not hit:
            return None
        after = getattr(self, "after_geom", None)
        if after is None:
            return unary_union([g for _, g in hit]).buffer(POUR_CLR_MM)
        lost = []
        for L in sorted({L for L, _ in hit}):
            now = unary_union([cugraph.ring_poly(r) for z in after["zones"] if not z["rule_area"] and z["net"] == code
                               for r in z.get("fills", {}).get(L, [])])
            lost.append(unary_union([g for L2, g in hit if L2 == L]).difference(now.buffer(1e-3)))
        lost = unary_union(lost)
        return lost.buffer(POUR_CLR_MM) if not lost.is_empty and lost.area > 1e-4 else None

    def step(self, name, fn):
        import copy
        i = self.i
        self.i += 1
        if self.resume_at is not None and i < self.resume_at:
            self.trace.append(self.prev[i])                  # identical to the previous replay (deterministic)
            return self.prev[i]["n"]
        snap = self.snapdir / f"{i:02d}.kicad_pcb"
        if self.resume_at is not None and i == self.resume_at:
            pr = self.prev[i]
            self.board.write_bytes(snap.read_bytes())
            self.edits, self.geo = self.edits[:pr["edits"]], self.geo[:pr["edits"]]
            self.unfixed = copy.deepcopy(pr["unfixed"])
            self.round_gate = pr["round_gate"]
            self.G = dump(self.board, wpath("resume-geom.json"))
            self.resume_at = None
            self.log(f"  resume at step {i} ({name})")
        else:
            shutil.copyfile(self.board, snap)
        rec = {"name": name, "edits": len(self.edits), "unfixed": copy.deepcopy(self.unfixed),
               "round_gate": self.round_gate}
        t = time.time()
        es = fn(self) or []
        n = self.commit(es)
        rec.update({"n": n, "keys": [e["key"] for e in self.edits[rec["edits"]:]], "s": round(time.time() - t, 1)})
        self.times["step " + name.split(":")[0]] += time.time() - t
        self.trace.append(rec)
        self.log(f"  step {i:2d} {name:12s} {n:4d} edits {rec['s']:6.1f} s")
        return n

    def commit(self, es):
        """apply a step's edits (in memory and natively, one save); an edit touching an item an earlier edit of the
        step already consumed waits for the next step; an edit that would delete / move / widen a LOCKED item is
        dropped (CT: locked copper is deliberate hand copper)"""
        G = self.G
        T = {t["uuid"]: t for t in G["tracks"]}
        Vv = {v["uuid"]: v for v in G["vias"]}
        used, out = set(), []
        done = {e["key"] for e in self.edits}            # an edit is made once per replay (a re-listed item stays)
        for e in es:
            k = ktuple(e["key"])
            if k in self.blocked or k in done:
                continue
            # never write a zero-length segment (CT's copper gate cannot project onto one; it is TRACK-DUP debris)
            e["adds"] = [a for a in e.get("adds", []) if math.dist(a["s"], a["e"]) > 1e-4]
            tg = set(e.get("dels", [])) | set(e.get("moves", {})) | set(e.get("widen", {}))
            if not tg and not e["adds"] and not e.get("vias"):
                continue
            if tg & self.locked:
                self.locked_skipped.append({"key": kjson(k), "class": e["class"], "net": e["net"], "at": e.get("at"),
                                            "locked": sorted(tg & self.locked)})
                continue
            if tg & used or any(u not in T and u not in Vv for u in tg):
                continue
            done.add(k)
            used |= tg
            e["key"] = k
            out.append(e)
        if not out:
            return 0
        dels, moves, adds, widen, vias = set(), {}, [], {}, []
        for e in out:
            k = e["key"]
            geo = []
            for u in e.get("dels", []):
                geo.append(trk_cu(T[u]) if u in T else via_disc(Vv[u]))
            for u, xy in e.get("moves", {}).items():
                geo += [via_disc(Vv[u]), Point(xy).buffer(Vv[u]["d"] / 2)]
            for u, w in e.get("widen", {}).items():
                geo.append(trk_line(T[u]).buffer(w / 2))
            for j, a in enumerate(e.get("adds", [])):
                a["uuid"] = new_uuid("add", k, j, tuple(a["s"]), tuple(a["e"]), a["w"])
                geo.append(trk_line(a).buffer(a["w"] / 2))
                adds.append(a)
            for j, v in enumerate(e.get("vias", [])):
                v["uuid"] = new_uuid("via", k, j, v["x"], v["y"])
                geo.append(Point(v["x"], v["y"]).buffer(v["d"] / 2))
                vias.append(v)
            dels |= set(e.get("dels", []))
            moves.update(e.get("moves", {}))
            widen.update(e.get("widen", {}))
            g = unary_union(geo) if geo else Point(e.get("at", (0, 0)))
            self.geo.append(g)
            self.edits.append({"key": k, "class": e["class"], "op": e["op"], "net": e["net"],
                               "at": [round(x, 4) for x in (e.get("at") or g.centroid.coords[0])],
                               "bbox": [round(x, 3) for x in g.bounds]})
        code = {v["name"]: int(c) for c, v in G["nets"].items()}
        g_delete(G, dels)
        g_move(G, moves)
        for t in G["tracks"]:
            if t["uuid"] in widen:
                t["w"] = widen[t["uuid"]]
        for a in adds:
            G["tracks"].append({"uuid": a["uuid"], "net": code[a["net"]], "layer": a["layer"], "s": list(a["s"]),
                                "e": list(a["e"]), "w": a["w"], "locked": False})
        for v in vias:
            G["vias"].append({"uuid": v["uuid"], "net": code[v["net"]], "x": v["x"], "y": v["y"], "d": v["d"],
                              "drill": v["drill"], "type": 3, "top": "F.Cu", "bot": "B.Cu", "locked": False})
        t = time.time()
        native_apply(self.board, dels, moves, adds, widen, refill=False, vias=vias)
        self.times["apply"] += time.time() - t
        return len(out)


# ------------------------------------------------------------------------------------------------ steps
JOG_SAFE = 0.0006           # s_jog margin: the polygonised round caps only (buffer quad 16: < 0.0005 mm at w <= 0.8 mm)


def s_jog(ctx):
    """TRACK-JOG: the copper gate's own CLEAN shortcut per unprotected staircase site (refilled input, full gate),
    applied when its chain is still there, unlocked, and the path passes the clearance model"""
    G = ctx.G
    nets = nets_of(G)
    code = {v["name"]: c for c, v in nets.items()}
    T = {t["uuid"]: t for t in G["tracks"]}
    lg = Legal(G, Index(G))
    lg.safe = JOG_SAFE                          # the gate screened these paths with KiCad's own shapes and epsilon
    out, used = [], set()
    unf = []
    for row in ctx.base_full.get("TRACK-JOG", []):
        for s in row.get("sites", []):
            sc = s.get("shortcut")
            if not sc or not sc.get("path"):
                continue
            ch = list(sc.get("chain_uuids") or [])
            key = ("JOG",) + tuple(sorted(ch))
            if key in ctx.blocked:
                unf.append({"net": s["net"], "at": s["at"], "why": "blocked by the arbiter"})
                continue
            if not ch or any(u not in T for u in ch) or set(ch) & used:
                continue
            if set(ch) & ctx.locked:
                unf.append({"net": s["net"], "at": s["at"], "why": "locked copper in the chain"})
                continue
            n, L, w = code.get(sc["net"]), sc["layer"], float(sc["width_mm"])
            pts = [tuple(p) for p in sc["path"]]
            old = unary_union([trk_cu(T[u]) for u in ch])
            if n is None or not all(lg.seg_ok(n, L, a, b, w, old_sig_geo=old) for a, b in zip(pts, pts[1:])
                                    if LineString([a, b]).buffer(w / 2).difference(old.buffer(1e-3)).area > 1e-6):
                unf.append({"net": s["net"], "at": s["at"], "why": "shortcut no longer clear"})
                continue
            used |= set(ch)
            adds = [{"net": sc["net"], "layer": L, "s": list(a), "e": list(b), "w": w} for a, b in zip(pts, pts[1:])
                    if math.dist(a, b) > 1e-6]
            for a in adds:
                lg.extra[L].append((LineString([a["s"], a["e"]]).buffer(w / 2), n))
            out.append({"key": key, "class": "TRACK-JOG", "net": sc["net"], "at": list(s["start"]),
                        "op": f"gate shortcut ({sc.get('type')}, saves {sc.get('saving_mm')} mm)", "dels": ch,
                        "adds": adds})
    ctx.unfixed["TRACK-JOG"] = unf
    return out


def s_debris(ctx):
    """TRACK-DUP (joint guard) and TRACK-ORPHAN: the gate's own findings. Starts a round: the same gate read is the
    work list of the round's later steps (each re-validates its items on the current geometry)"""
    f, G = ctx.gate(), ctx.G
    ctx.round_gate = f
    nets = nets_of(G)
    T = {t["uuid"]: t for t in G["tracks"]}
    ok = lambda u: u in T and ctx.free(u)  # noqa: E731
    dup = [u for u in gate_uuids(f, "TRACK-DUP") if ok(u) and ("DEL", u) not in ctx.blocked]
    out = [{"key": ("DEL", u), "class": "TRACK-DUP", "net": nets[T[u]["net"]]["name"], "op": "delete covered / zero-length",
            "dels": [u], "at": list(T[u]["s"])} for u in safe_dups(G, dup)]
    comps = None
    pour = set(K.POUR_NETS)
    unf = []
    for x in f["TRACK-ORPHAN"]:
        us_all = [u for u in x.get("uuids", []) if u in T]
        if not us_all:
            continue
        us = sorted(us_all)
        if set(us) & ctx.locked:
            unf.append({"net": x.get("net"), "at": list(T[us[0]]["s"]), "why": "locked copper in the orphan"})
            continue
        if ("ORPH", us[0]) in ctx.blocked:
            continue
        vs = []
        if x.get("net") not in pour:              # a routed net's orphan takes its own (unlocked) vias with it
            if comps is None:
                comps = {t: c for c in track_components(G) for t in c[0]}
            c = comps.get(us[0])
            if c is not None and not c[2]:
                vs = sorted(v for v in c[1] if v not in ctx.locked)
        out.append({"key": ("ORPH", us[0]), "class": "TRACK-ORPHAN", "net": x["net"],
                    "op": f"delete orphan ({len(us)} tracks, {len(vs)} vias)", "dels": us + vs, "at": list(T[us[0]]["s"])})
    ctx.unfixed["TRACK-ORPHAN"] = unf
    for u, k in near_dups(G, ctx.locked, ctx.blocked):
        out.append({"key": ("NDUP", u), "class": "TRACK-DUP", "net": nets[T[u]["net"]]["name"], "dels": [u],
                    "op": f"router segment doubling locked hand copper ({k[:8]}) deleted", "at": list(T[u]["s"])})
    return out


ENDS_MAX_MM = 1.0         # TRACK-END completion: a free end at most this far short of its same-net pad / via / track
NEAR_DUP_MM = 0.08        # router copper lying within this of a locked same-net segment's copper doubles it


def _xy(s):
    q = _pt(s)
    return (q[0].x, q[0].y) if q else None


def s_ends(ctx):
    """TRACK-END completion (DIN-8R owner: a dangling trace ending near a same-net pad is an unfinished link: complete
    it): each free end the gate details as "stops X mm short of pad / via" (X <= ENDS_MAX_MM) gets a segment to that
    pad / via CENTRE; an "edge landing on track" end gets a segment onto the track's centreline; an "edge landing on pad /
    via" end runs on to its centre. Same width as the end's track, clearance-checked, no acute joint (>= 90 deg at the
    end, >= 45 deg onto a trunk), a pad entered along its long axis. The end's own track is never modified (locked ones
    included). Also: a KiCad-dangling micro spur (an unlocked segment no longer than its width) is deleted."""
    f, G = ctx.round_gate or ctx.gate(), ctx.G
    nets = nets_of(G)
    T = {t["uuid"]: t for t in G["tracks"]}
    P = {f"{p['ref']}.{p['num']}": p for p in G["pads"]}
    lg = Legal(G, Index(G))
    out, unf = [], []
    for x in f.get("TRACK-END", []):
        us = [u for u in x.get("uuids", []) if u in T]
        if not us:
            continue
        if x.get("detector", "").startswith("kicad"):
            t = T[us[0]]
            k = ("SPUR", t["uuid"])
            if len(us) == 1 and not t.get("locked") and math.dist(t["s"], t["e"]) <= t["w"] + 1e-6 and k not in ctx.blocked:
                out.append({"key": k, "class": "TRACK-END", "net": x["net"], "op": "dangling micro spur deleted",
                            "dels": [t["uuid"]], "at": list(t["s"])})
            continue
        key = ("END", sorted(us)[0])
        if key in ctx.blocked:
            unf.append({"net": x["net"], "why": "blocked by the arbiter", "free_ends": x.get("free_ends")})
            continue
        adds = []
        for d in x.get("end_detail", []):
            q, L, cls = _xy(d.get("at", "")), d.get("layer"), d.get("class", "")
            if q is None:
                continue
            t = next((T[u] for u in us if T[u]["layer"] == L and min(math.dist(q, T[u]["s"]), math.dist(q, T[u]["e"])) < 2e-3), None)
            if t is None:
                continue
            far = tuple(t["e"]) if math.dist(q, t["s"]) < math.dist(q, t["e"]) else tuple(t["s"])
            q = tuple(t["s"]) if math.dist(q, t["s"]) < math.dist(q, t["e"]) else tuple(t["e"])   # the exact end
            n, w = t["net"], t["w"]
            m = re.match(r"(stops|edge landing on) (?:([0-9.]+) mm short of )?(pad|via|track) (.+?)(?::|$)", cls)
            if not m:
                unf.append({"net": x["net"], "at": list(q), "why": "free stub: no target within 2 mm"})
                continue
            kind, what = m.group(3), m.group(4).strip()
            if m.group(1) == "stops" and float(m.group(2)) > ENDS_MAX_MM:
                unf.append({"net": x["net"], "at": list(q), "why": f"stops {m.group(2)} mm short (> {ENDS_MAX_MM})"})
                continue
            trunk, pad, tgt = None, None, None
            if kind == "pad" and what in P:
                pad = P[what]
                tgt = (pad["x"], pad["y"])
            elif kind == "via":
                tgt = _xy(what)
            elif kind == "track":
                ab = _pt(what)
                if len(ab) == 2:
                    ln = LineString([(ab[0].x, ab[0].y), (ab[1].x, ab[1].y)])
                    pr = ln.interpolate(ln.project(Point(q)))
                    tgt, trunk = (round(pr.x, 4), round(pr.y, 4)), ((ab[0].x, ab[0].y), (ab[1].x, ab[1].y))
            if tgt is None or math.dist(q, tgt) < 1e-4:
                continue
            a_ = incl(far, q, tgt)
            if a_ < JOINT_MIN or (trunk is not None and min(incl(trunk[0], tgt, q), incl(trunk[1], tgt, q)) < 45.0) or \
                    (pad is not None and not along_axis(pad, L, q, tgt)):
                ext = _edge_extension(G, n, L, q, far, kind, pad, tgt, trunk) if m.group(1) == "edge landing on" else None
                if ext is None:
                    unf.append({"net": x["net"], "at": list(q), "why": f"completion to {kind} {what} would make an acute "
                                                                         "joint / leave the pad off its axis"})
                    continue
                tgt = ext                         # collinear run-on into the target copper (no new joint angle)
            old = trk_cu(t)
            if pad is not None and pad_geo(pad).get(L) is not None:
                old = old.union(pad_geo(pad)[L])
            if not lg.seg_ok(n, L, q, tgt, w, old_sig_geo=old):
                unf.append({"net": x["net"], "at": list(q), "why": f"completion to {kind} {what} not clear"})
                continue
            lg.extra[L].append((LineString([q, tgt]).buffer(w / 2), n))
            adds.append({"net": nets[n]["name"], "layer": L, "s": [round(q[0], 4), round(q[1], 4)], "e": list(tgt), "w": w})
        if adds:
            out.append({"key": key, "class": "TRACK-END", "net": x["net"], "at": adds[0]["s"],
                        "op": f"{len(adds)} free end(s) completed to their pad / via / track", "adds": adds})
    ctx.unfixed["TRACK-END"] = unf
    return out


def _edge_extension(G, n, L, q, far, kind, pad, tgt, trunk):
    """An "edge landing" end (the end sits a few hundredths outside its target's copper) whose completion to the target
    centre would be acute / off the pad axis: run the end's own track on, collinear, until it lies 0.01 mm inside the
    target copper (<= 0.15 mm). -> the new end point or None."""
    geo = None
    if kind == "pad" and pad is not None:
        geo = pad_geo(pad).get(L)
    elif kind == "via" and tgt is not None:
        v = next((v for v in G["vias"] if v["net"] == n and math.dist((v["x"], v["y"]), tgt) < 2e-3), None)
        geo = via_disc(v) if v is not None else None
    elif kind == "track" and trunk is not None:
        want = {tuple(round(c, 3) for c in trunk[0]), tuple(round(c, 3) for c in trunk[1])}
        t2 = next((t for t in G["tracks"] if t["net"] == n and t["layer"] == L and
                   {tuple(round(c, 3) for c in t["s"]), tuple(round(c, 3) for c in t["e"])} == want), None)
        geo = trk_cu(t2) if t2 is not None else None
    if geo is None or geo.is_empty:
        return None
    inner = geo.buffer(-0.01)
    d = math.dist(far, q)
    if inner.is_empty or d < 1e-6:
        return None
    ux, uy = (q[0] - far[0]) / d, (q[1] - far[1]) / d
    for k in range(1, 31):
        e = (round(q[0] + ux * 0.005 * k, 4), round(q[1] + uy * 0.005 * k, 4))
        if inner.contains(Point(e)):
            return e
    return None


def near_dups(G, locked, blocked):
    """router (unlocked) segments whose copper lies within NEAR_DUP_MM of one locked same-net same-layer segment's copper:
    they double CT's hand copper (TRACK-FOLD / LOOP / acute knots the rewrites may not touch) -> [(uuid, locked uuid)]"""
    by = defaultdict(list)
    for t in G["tracks"]:
        if t["uuid"] in locked and math.dist(t["s"], t["e"]) > 1e-6:
            by[(t["net"], t["layer"])].append(t)
    out = []
    cl = centre_landings(G)
    for t in G["tracks"]:
        if t["uuid"] in locked or ("NDUP", t["uuid"]) in blocked or lands_centre(t, cl):
            continue
        for k in by.get((t["net"], t["layer"]), ()):
            if trk_line(k).buffer(k["w"] / 2 + NEAR_DUP_MM, 16).contains(trk_cu(t)):
                out.append((t["uuid"], k["uuid"]))
                break
    return out


def s_padedge(ctx):
    f, G = ctx.round_gate or ctx.gate(), ctx.G
    V = {v["uuid"]: v for v in G["vias"]}
    ok = lambda u: u in V and ctx.free(u)  # noqa: E731
    prev = [x for x in ctx.unfixed.get("VIA-PADEDGE", []) if x.get("why", "").startswith("no legal") and x["via"] in V]
    prev += [dict(ctx.pe_cache[u], why=f"no legal spot within {PE_RMAX} mm (cached)") for u in V
             if u in ctx.pe_cache and tuple(ctx.pe_cache[u]["at"]) == (V[u]["x"], V[u]["y"])
             and u not in {x["via"] for x in prev}]
    skip = {x["via"] for x in prev}
    ids = {u for c in ("VIA-PADEDGE", "VIA-PARTIAL") for u in gate_uuids(f, c) if ok(u)} - skip
    pe = [x for x in find_padedge(G) if x["via"]["uuid"] not in skip and
          (x["via"]["uuid"] in ids or (not x["pads"] and x["near"] and ok(x["via"]["uuid"])))]
    es = []
    unf = fix_padedge(G, pe, log=lambda *a: None, blocked=ctx.blocked, edits=es)[2]
    for x in unf:
        if x.get("why", "").startswith("no legal"):
            ctx.pe_cache[x["via"]] = x
    locked_pe = [{"via": u, "why": "locked via"} for u in gate_uuids(f, "VIA-PADEDGE") if u in ctx.locked]
    ctx.unfixed["VIA-PADEDGE"] = prev + unf + locked_pe
    return es


def s_smooth(ctx):
    groups = []
    smooth.plan(ctx.G, ctx.locked, log=lambda *a: None, blocked=ctx.blocked, groups=groups)
    return [{"key": k, "class": "TRACK-JOG", "net": k[1], "op": f"smooth chain {len(dels)} -> {len(adds)} segments",
             "dels": dels, "adds": adds, "at": list(adds[0]["s"]) if adds else None} for k, dels, adds in groups]


def s_centre(ctx):
    f, G = ctx.round_gate or ctx.gate(), ctx.G
    T = {t["uuid"]: t for t in G["tracks"]}
    seen, cf = set(), []
    for x in [x for x in f["PAD-CENTRE"] if x.get("uuids")] + free_pad_ends(G):
        u = x["uuids"][0]
        if u not in T or (u, x["pad"]) in seen:
            continue
        seen.add((u, x["pad"]))
        cf.append({"uuids": [u], "pad": x["pad"], "at": list(x["at"])})
    es = []
    ctx.unfixed["PAD-CENTRE"] = fix_centres(G, cf, log=lambda *a: None, blocked=ctx.blocked, edits=es)[2]
    return es


def s_width(ctx):
    f, G = ctx.round_gate or ctx.gate(), ctx.G
    T = {t["uuid"]: t for t in G["tracks"]}
    fw = {"TRACK-WIDTH": [x for x in f["TRACK-WIDTH"] if x.get("uuids") and x["uuids"][0] in T
                          and ctx.free(x["uuids"][0])]}
    es = []
    _, unf = widen_plan(G, fw, log=lambda *a: None, blocked=ctx.blocked, edits=es)
    unf += [{"net": x.get("net"), "at": x.get("at"), "uuid": x["uuids"][0], "why": "locked track"}
            for x in f["TRACK-WIDTH"] if x.get("uuids") and x["uuids"][0] in ctx.locked]
    ctx.unfixed["TRACK-WIDTH"] = unf
    return es


def s_lqfix(ctx):
    """qa_layout_quality TRACK-FOLD collapses / trims, ACUTE corner cuts / re-anchors, VIA-HOP removal (one LQ read),
    then qa_copper_landing LOOP doubled-copper collapses (items disjoint)"""
    f = ctx.lq()
    es = []
    lk = ctx.locked
    ctx.unfixed["TRACK-FOLD"] = fix_folds(ctx.G, f, ctx.blocked, es, locked=lk)
    busy = {u for e in es for u in e.get("dels", [])}
    f2 = dict(f, ACUTE=[x for x in f.get("ACUTE", []) if not busy & set(x.get("uuids", []))])
    ctx.unfixed["ACUTE"] = fix_acute(ctx.G, f2, ctx.blocked, es, locked=lk)
    ctx.unfixed["VIA-HOP"] = fix_hops(ctx.G, f, ctx.blocked, es, locked=lk)
    busy = {u for e in es for u in e.get("dels", []) + e.get("touch", [])}
    ctx.unfixed["LOOP"] = fix_loops(ctx.G, ctx.gate().get("LOOP", []), ctx.blocked, es, skip=busy,
                                    free=lambda t: ctx.free(t["uuid"]), locked=lk)
    return es


def s_dead(ctx):
    """dead copper (a track cluster held by one pad only, no via, no own fill) left by the lqfix rewrites"""
    out = []
    for x in find_dead(ctx.G, free=lambda t: ctx.free(t["uuid"])):
        k = ("DEAD", x["tracks"][0])
        if k in ctx.blocked:
            continue
        out.append({"key": k, "class": "DEAD", "net": x["net"], "op": f"dead copper off {x['pad']} ({len(x['tracks'])} tracks)",
                    "dels": x["tracks"], "at": x["at"]})
    return out


def s_starved(ctx):
    es = []
    ctx.unfixed["STARVED"] = stitch_starved(ctx.G, ctx.d0, log=lambda *a: None, blocked=ctx.blocked, edits=es)[1]
    return es


def s_bare(ctx):
    if not ctx.do_bare:
        return []
    G = ctx.G
    nets = nets_of(G)
    allowed = {u for u in gate_uuids(ctx.gate(), "VIA-BARE") if ctx.free(u)}
    out = []
    for v, why in bare_removals(G, allowed):
        if ("BARE", v["uuid"]) in ctx.blocked:
            continue
        out.append({"key": ("BARE", v["uuid"]), "class": "VIA-BARE", "net": nets[v["net"]]["name"], "op": "delete: " + why,
                    "dels": [v["uuid"]], "at": [v["x"], v["y"]]})
    return out


def s_stitch(ctx):
    es = []
    ctx.unfixed["POUR-STITCH"] = stitch_plan(ctx.G, ctx.lq(), ctx.blocked, es)
    return es


def s_refill(ctx):
    t = time.time()
    native_apply(ctx.board, set(), {}, [], refill=True)
    ctx.times["refill"] += time.time() - t
    return []


# ---------------------------------------------------------------- pour-net drops / layer-change sites (board finish
# 2026-10-17, root: "fix structurally ... as a cleanup rule, not by hand")
GNDDROP_GRID = 0.05        # drop-via candidate grid (mm)
GNDDROP_PADGAP = 0.10      # = qa_layout_quality VIA-PADGAP: a via outside its own pad keeps this gap to it


def _plane_fill(G, n):
    return unary_union([g for _, L, g in fill_islands(G, {n}) if L in INNER])


def _drop_site_ok(G, lg, n, q, d, drill, plane, own_pads, smd_tree, smd):
    """a through via of net n at q: inside the net's inner plane fill, legal against all foreign copper / rule areas /
    holes / edge, >= GNDDROP_PADGAP from its own SMD pads (never half in a pad) and >= STITCH_PAD_GAP from other SMD pads"""
    c = Point(q)
    disc = c.buffer(d / 2, 16)
    if plane.is_empty or not plane.contains(disc):
        return False
    if c.distance(lg.edge) < lg.rules.get("edge_clearance", 0.3) + d / 2 + SAFE:
        return False
    if any(lg.areas[j][0].intersects(disc) for j in lg.atree.query(disc)):
        return False
    for g in own_pads:
        if g.intersects(disc) or g.distance(disc) < GNDDROP_PADGAP:
            return False
    if smd_tree is not None and any(smd[j][1] != n and smd[j][0].distance(disc) < STITCH_PAD_GAP
                                    for j in smd_tree.query(disc.buffer(STITCH_PAD_GAP))):
        return False
    h2h = lg.rules.get("hole_to_hole", 0.25)
    if any(lg.drills[j][0].distance(c) - lg.drills[j][1] / 2 - drill / 2 < h2h + SAFE for j in lg.dtree.query(c.buffer(2.0))):
        return False
    return all(lg.copper_ok(n, L, disc, "via") for L in G["layers"])


def s_gnddrop(ctx):
    """TRACK-WIDTH on a pour net (GND / PRTN / VSS) that widening could not fix: a pour-net track inside a pour is never
    a leaf, so the copper must be either the required width or ONE <= NECK_MM segment from a pad no wider than required.
    For each such track at a pad: re-make the pad's drop as one straight segment from the pad centre to a new via inside
    NECK_MM (legal site nearest the pad); where the pad sits in its own pour fill, the track is removed instead (the pad
    keeps its zone connection; the arbiter rolls back any edit that opens a connection)."""
    f, G = ctx.round_gate or ctx.gate(), ctx.G
    pour = set(K.BASE_POUR_NETS)
    code = {v["name"]: int(k) for k, v in G["nets"].items()}
    T = {t["uuid"]: t for t in G["tracks"]}
    lg = Legal(G, Index(G))
    smd = [(g, p["net"]) for p in G["pads"] if is_smd(p) for g in pad_geo(p).values() if g is not None and not g.is_empty]
    smd_tree = STRtree([x[0] for x in smd]) if smd else None
    out, done = [], set()
    planes = {}
    for x in f.get("TRACK-WIDTH", []):
        u = (x.get("uuids") or [None])[0]
        if x.get("net") not in pour or u not in T or not ctx.free(u) or u in done:
            continue
        t = T[u]
        n, L = t["net"], t["layer"]
        if n not in planes:
            planes[n] = _plane_fill(G, n)
        ends = [Point(t["s"]), Point(t["e"])]
        pads = [p for p in G["pads"] if p["net"] == n and is_smd(p) and pad_geo(p).get(L) is not None
                and any(pad_geo(p)[L].distance(e) <= t["w"] / 2 + 1e-3 for e in ends)]
        if not pads:
            continue
        p = pads[0]
        pg = pad_geo(p)[L]
        bx0, by0, bx1, by1 = pg.bounds
        pw = min(bx1 - bx0, by1 - by0)
        k = ("GNDDROP", u)
        if k in ctx.blocked:
            continue
        own_fill = unary_union([g for _, L2, g in fill_islands(G, {n}) if L2 == L])
        if not own_fill.is_empty and own_fill.intersects(pg.buffer(-0.01)):
            done.add(u)
            out.append({"key": k, "class": "TRACK-WIDTH", "net": x["net"], "at": [p["x"], p["y"]],
                        "op": f"pour-net track off {p.get('ref', '')}.{p.get('num', '')}: the pad keeps its zone connection",
                        "dels": [u]})
            continue
        sizes = Counter((v["d"], v["drill"]) for v in G["vias"] if v["net"] == n) or Counter({(0.6, 0.3): 1})
        d, drill = sizes.most_common(1)[0][0]
        w = round(min(t["w"], pw), 3)
        own = [g for q2 in G["pads"] if q2["net"] == n and is_smd(q2) for g in pad_geo(q2).values()
               if g is not None and not g.is_empty]
        R = NECK_MM - 0.02
        best = None
        steps = int(R / GNDDROP_GRID)
        cands = sorted(((i * GNDDROP_GRID, j * GNDDROP_GRID) for i in range(-steps, steps + 1)
                        for j in range(-steps, steps + 1)), key=lambda q: q[0] ** 2 + q[1] ** 2)
        for dx, dy in cands:
            if dx * dx + dy * dy > R * R:
                break
            q = (round(p["x"] + dx, 3), round(p["y"] + dy, 3))
            if not _drop_site_ok(G, lg, n, q, d, drill, planes[n], own, smd_tree, smd):
                continue
            if not lg.seg_ok(n, L, (p["x"], p["y"]), q, w):
                continue
            best = q
            break
        if best is None:
            continue
        done.add(u)
        for L2 in G["layers"]:
            lg.extra[L2].append((Point(best).buffer(d / 2), n))
        out.append({"key": k, "class": "TRACK-WIDTH", "net": x["net"], "at": list(best),
                    "op": f"pour-net drop re-made: one {w} mm segment from the pad centre to a via "
                          f"{math.dist(best, (p['x'], p['y'])):.2f} mm away",
                    "dels": [u], "adds": [{"net": x["net"], "layer": L, "s": [p["x"], p["y"]], "e": list(best), "w": w}],
                    "vias": [{"net": x["net"], "x": best[0], "y": best[1], "d": d, "drill": drill}]})
    return out


def s_inpad(ctx):
    """PAD-CENTRE: an UNLOCKED track lying wholly inside one same-net pad on its layer (a router join from a via-in-pad
    to the pad centre: its via-side end is an off-centre end inside the pad) carries nothing the pad copper does not:
    it goes (r24: SW_SEC R17.1, GND C71.2)."""
    G = ctx.G
    out = []
    pads = [(p, pad_geo(p)) for p in G["pads"]]
    # a pad's land = the pad plus the same part's same-net pads overlapping it (U6's L-shaped corner pins are two
    # overlapping pads of one number: the generator's land joins between them lie inside the union, r25 PAD-AXIS)
    land = {}
    by = defaultdict(list)
    for i, (p, geo) in enumerate(pads):
        for L, g in (geo or {}).items():
            if g is not None and not g.is_empty:
                by[(p.get("ref"), p["net"], L)].append((i, g))
    for (_, _, L), lst in by.items():
        for i, g in lst:
            ov = [g2 for j, g2 in lst if j != i and g2.intersects(g)]
            land[(i, L)] = unary_union([g] + ov) if ov else g
    for t in G["tracks"]:
        if not ctx.free(t["uuid"]):
            continue
        k = ("INPAD", t["uuid"])
        if k in ctx.blocked:
            continue
        ln = trk_line(t)
        for i, (p, geo) in enumerate(pads):
            g = land.get((i, t["layer"]))
            if p["net"] == t["net"] and g is not None and not g.is_empty and g.buffer(1e-3).contains(ln):
                out.append({"key": k, "class": "PAD-CENTRE", "net": G["nets"][str(t["net"])]["name"]
                            if str(t["net"]) in G["nets"] else str(t["net"]), "at": list(t["s"]),
                            "op": f"track inside {p.get('ref', '')}.{p.get('num', '')} removed", "dels": [t["uuid"]]})
                break
    return out


def s_gndprune_post(ctx):
    """s_gndprune again after the stitch step, on a fresh gate read: a pour-net chain whose removal opened a pad's fill
    island before (the island had no via yet: PAD-OPEN pour split, r25 U7 decap GND chains) can go once the stitch step
    has given that island its vias (own key: the pre-stitch block does not carry over)."""
    ctx.round_gate = ctx.gate()
    return s_gndprune(ctx, tag="GNDPRUNE2")


def s_gndprune(ctx, tag="GNDPRUNE"):
    """TRACK-WIDTH on a pour net (GND / PRTN / VSS) where the copper is redundant router debris: Freerouting / the
    completion join pour-net pads that already sit in their own pour with thin tracks, and a pour-net track is never a
    leaf, so the gate asks 0.787 mm for it (widening then collides; deleting one segment leaves the rest dangling).
    For every UNLOCKED chain of pour-net tracks (connected on one layer) that holds a flagged track: when every pad the
    chain touches already touches its own net's fill on that layer, the WHOLE chain goes (the pads keep their zone
    connection; the chain's vias stay - they sit in the plane, and the bare step prunes the redundant ones). Locked copper
    is never touched; the arbiter rolls back any chain whose removal opens a connection."""
    f, G = ctx.round_gate or ctx.gate(), ctx.G
    pour = set(K.BASE_POUR_NETS)
    flagged = {(x.get("uuids") or [None])[0] for x in f.get("TRACK-WIDTH", []) if x.get("net") in pour}
    T = {t["uuid"]: t for t in G["tracks"]}
    names = {int(k): v["name"] for k, v in G["nets"].items()}
    out, seen = [], set()
    fills = {}
    for u in sorted(u for u in flagged if u in T):
        if u in seen or not ctx.free(u):
            continue
        t0 = T[u]
        n, L = t0["net"], t0["layer"]
        if names.get(n) not in pour:
            continue
        mem = [t for t in G["tracks"] if t["net"] == n and t["layer"] == L and ctx.free(t["uuid"])]
        geo = {t["uuid"]: trk_cu(t) for t in mem}
        chain, todo = {u}, [u]
        while todo:                                  # the connected unlocked run on this layer
            a = todo.pop()
            for t in mem:
                b = t["uuid"]
                if b not in chain and geo[a].intersects(geo[b]):
                    chain.add(b)
                    todo.append(b)
        seen |= chain
        k = (tag, min(chain))
        if k in ctx.blocked:
            continue
        cu = unary_union([geo[c] for c in chain])
        if (n, L) not in fills:
            fills[(n, L)] = unary_union([g for _, L2, g in fill_islands(G, {n}) if L2 == L])
        own = fills[(n, L)]
        touched = [p for p in G["pads"] if p["net"] == n and pad_geo(p).get(L) is not None
                   and pad_geo(p)[L].intersects(cu)]
        # a chain touching no pad (r25: 6 mm of F.Cu GND between locked copper east of C32) goes when every locked
        # same-net track it touches already lies in the own fill (the arbiter still guards every connection)
        held = [t for t in G["tracks"] if t["net"] == n and t["layer"] == L and not ctx.free(t["uuid"])
                and trk_cu(t).intersects(cu)]
        if own.is_empty or (not touched and not held):
            continue
        if not all(own.intersects(pad_geo(p)[L].buffer(-0.01)) for p in touched) or                 not all(own.intersects(trk_cu(t).buffer(-0.01)) for t in held if not touched):
            continue
        out.append({"key": k, "class": "TRACK-WIDTH", "net": names[n], "at": list(T[u]["s"]),
                    "op": f"redundant pour-net chain ({len(chain)} segments) off "
                          f"{', '.join(str(p.get('ref', '')) + '.' + str(p.get('num', '')) for p in touched)}: every "
                          f"pad keeps its zone connection", "dels": sorted(chain)})
    return out


def s_viacur(ctx):
    """qa_layout_quality VIA-CURRENT on a pour net: a layer-change site carrying more than its vias may. Add vias to the
    site inside the same outer-layer pour (no track between them: never a VIA-HOP), within the gate's VIA_SITE_MM of
    the flagged via, legal like a stitch via."""
    f, G = ctx.lq(), ctx.G
    pour = set(K.BASE_POUR_NETS)
    code = {v["name"]: int(k) for k, v in G["nets"].items()}
    lg = Legal(G, Index(G))
    smd = [(g, p["net"]) for p in G["pads"] if is_smd(p) for g in pad_geo(p).values() if g is not None and not g.is_empty]
    smd_tree = STRtree([x[0] for x in smd]) if smd else None
    allv = [(v["x"], v["y"]) for v in G["vias"]]
    out = []
    site_mm = 1.2                                   # = qa_layout_quality.VIA_SITE_MM
    for x in f.get("VIA-CURRENT", []):
        nm = x.get("net")
        if nm not in pour or nm not in code:
            continue
        n = code[nm]
        vx, vy = x["at"]
        k = ("VIACUR", nm, round(vx, 3), round(vy, 3))
        if k in ctx.blocked:
            continue
        add = max(0, int(x.get("need", 2)) - int(x.get("vias", 1)))
        plane = _plane_fill(G, n)
        outer = [g for _, L, g in fill_islands(G, {n}) if L not in INNER and g.intersects(Point(vx, vy).buffer(0.31))]
        if not outer or add == 0:
            continue
        d, drill = float(x.get("d", 0.6) or 0.6), float(x.get("drill", 0.3) or 0.3)
        own = [g for q2 in G["pads"] if q2["net"] == n and is_smd(q2) for g in pad_geo(q2).values()
               if g is not None and not g.is_empty]
        placed = []
        cands = sorted(((round(vx + i * 0.05, 3), round(vy + j * 0.05, 3)) for i in range(-24, 25) for j in range(-24, 25)),
                       key=lambda q: math.dist(q, (vx, vy)))
        for q in cands:
            if len(placed) >= add:
                break
            dq = math.dist(q, (vx, vy))
            if dq > site_mm - 0.05 or dq < d + 0.15:
                continue
            if any(math.dist(q, z) < d + 0.15 for z in allv + placed if math.dist(z, (vx, vy)) > 1e-3):
                continue
            disc = Point(q).buffer(d / 2, 16)
            if not any(g.contains(disc) for g in outer):
                continue
            if not _drop_site_ok(G, lg, n, q, d, drill, plane, own, smd_tree, smd):
                continue
            placed.append(q)
            for L2 in G["layers"]:
                lg.extra[L2].append((disc, n))
        if len(placed) < add:
            continue
        allv += placed
        out.append({"key": k, "class": "VIA-CURRENT", "net": nm, "at": [vx, vy],
                    "op": f"{len(placed)} more via(s) at the {x.get('vias')}-via site (pour-connected)",
                    "vias": [{"net": nm, "x": q[0], "y": q[1], "d": d, "drill": drill} for q in placed]})
    return out


def run_once(ctx, max_rounds):
    ctx.i, ctx.trace = 0, []
    if ctx.resume_at is None:
        ctx.board.write_bytes(ctx.src)
        ctx.G = json.loads(ctx.G0)
        ctx.edits, ctx.geo, ctx.unfixed = [], [], {}
        ctx.round_gate = None
    ctx.step("jog", s_jog)
    ctx.step("gndprune", s_gndprune)            # redundant pour-net chains go before widening tries to widen them
    ctx.step("inpad", s_inpad)                  # tracks wholly inside one own pad (VIP joins: PAD-CENTRE)
    for rnd in range(max_rounds):               # debris, pad-edge vias, widths, pad centres (to a fixpoint)
        n = ctx.step(f"debris:{rnd}", s_debris)
        n += ctx.step(f"padedge:{rnd}", s_padedge)
        n += ctx.step(f"width:{rnd}", s_width)
        n += ctx.step(f"centre:{rnd}", s_centre)
        n += ctx.step(f"ends:{rnd}", s_ends)
        if n == 0:
            break
    if ctx.step("gnddrop", s_gnddrop):          # pour-net drops widening could not fix -> one neck + via / zone
        ctx.step("debris:g", s_debris)          # the old drop's leftovers
    if ctx.do_smooth:                           # octilinear smoothing, then what it re-exposes
        for rnd in range(max_rounds):
            n = ctx.step(f"smooth:{rnd}", s_smooth)
            if n == 0:
                break
            ctx.step(f"debris:s{rnd}", s_debris)
            ctx.step(f"centre:s{rnd}", s_centre)
    for rnd in range(2):
        n = ctx.step(f"lqfix:{rnd}", s_lqfix)
        n += ctx.step(f"dead:lq{rnd}", s_dead)
        n += ctx.step(f"debris:lq{rnd}", s_debris)
        if n == 0:
            break
    ctx.step("starved", s_starved)
    ctx.step("viacur", s_viacur)                # VIA-CURRENT: more vias at overloaded pour-net layer-change sites
    ctx.step("stitch", s_stitch)                # stitch first: the bare step then also prunes what the stitches made
    if ctx.step("gndprune:post", s_gndprune_post):   # chains the stitched islands no longer need
        ctx.step("debris:post", s_debris)
    ctx.step("bare", s_bare)                    # redundant (the gate's VIA-BARE list after the stitches)
    ctx.step("refill", s_refill)


def findings(gf, lf, drcv, unconn, pads_xy):
    """-> (F {key: [spots]} new when absent before, C {key: (count, [spots])} new when the count rises): everything the
    arbiter guards (gate connection checks + VIA-PADEDGE / VIA-PARTIAL / PLANE-ISLAND, DRC errors and copper warnings,
    KiCad unconnected per net, layout point checks, POUR-STITCH deficit per fragment layer, DIFFPAIR problems)"""
    F, C = {}, {}

    def cnt(k, n, sp):
        n0, s0 = C.get(k, (0, []))
        C[k] = (n0 + n, s0 + sp)
    for chk in ("PAD-LAND", "POUR-PAD"):
        for x in gf.get(chk, []):
            F[(chk, x.get("pad"))] = [Point(x["at"])]
    for x in gf.get("TRACK-END", []):                # per net: loose copper length (a re-drawn loose chain is not new)
        sp = [q for fe in x.get("free_ends", []) for q in _pt(fe)] + _pt(x.get("track", ""))
        cnt(("TRACK-END", x.get("net")), int(round(x.get("loose_mm", x.get("len_mm", 0)) * 100)) + 1, sp)
    for x in gf.get("TRACK-DUP", []):                # an edit never creates doubled copper
        F[("TRACK-DUP", x.get("net"), x.get("track"))] = _pt(x.get("track", "")) or ([_at(x)] if _at(x) else [])
    for x in gf.get("VIA-LAND", []):
        F[("VIA-LAND", x.get("net"), round(x["at"][0], 2), round(x["at"][1], 2))] = [Point(x["at"])]
    for x in gf.get("PAD-CENTRE", []):               # an edit never takes a trace off a pad's centre
        F[("PAD-CENTRE", x.get("pad"), x.get("layer"))] = [Point(x["at"])]
    for c in ("VIA-PADEDGE", "VIA-PARTIAL"):
        for x in gf.get(c, []):
            F[(c, x.get("net"), x.get("pad"), round(x["at"][0], 2), round(x["at"][1], 2))] = [Point(x["at"])]
    for x in gf.get("LOOP", []):
        w = x.get("worst", {})
        C[("LOOP", x.get("net"))] = (x.get("contacts", 0), _pt(w.get("a", "")) + _pt(w.get("b", "")))
    for x in gf.get("PLANE-ISLAND", []):
        cnt(("PLANE-ISLAND", x.get("net")), 1, [_at(x)] if _at(x) else [])
    for x in gf.get("PAD-OPEN", []):
        if "pads" not in x:
            continue
        sp = [Point(pads_xy[p]) for p in x["pads"] if p in pads_xy]
        cnt(("PAD-OPEN", x["net"]), 1, sp)
        F[("PAD-OPEN-SET", x["net"], tuple(sorted(x["pads"])))] = sp
    for v in unconn:
        nm = re.findall(r"\[([^\]]+)\]", " ".join(i["description"] for i in v.get("items", [])))
        cnt(("UNCONNECTED", nm[0] if nm else ""), 1, [Point(i["pos"]["x"], i["pos"]["y"]) for i in v.get("items", [])])
    for v in drcv:
        F[("DRC",) + drc_sig(v)] = [Point(i["pos"]["x"], i["pos"]["y"]) for i in v["items"] if "pos" in i]
    for c in LQ_POINT:
        for x in lf.get(c, []):
            q = _at(x)
            if q is not None:
                F[("LQ", c, x.get("net") or x.get("part") or x.get("pad"), round(q.x / 0.05), round(q.y / 0.05))] = [q]
    for x in lf.get("POUR-STITCH", []):
        deficit = max(0, int(x.get("need", 0)) - int(x.get("vias", 0)))
        reach = 1 if float(x.get("beyond_reach_mm2", 0)) > STITCH_REACH_TOL_MM2 else 0
        cnt(("POUR-STITCH", x.get("net"), x.get("layer")), 1 + deficit + reach, [_at(x)] if _at(x) else [])
    for x in lf.get("DIFFPAIR", []):
        cnt(("DIFFPAIR",) + tuple(x.get("pair", [])), len(x.get("problems", [])), [_at(x)] if _at(x) else [])
    return F, C


def new_findings(base, now):
    (F0, C0), (F1, C1) = base, now
    out = [(k, sp) for k, sp in F1.items() if k not in F0 and k[0] != "PAD-OPEN-SET"]
    for k, (n, sp) in C1.items():
        if n > C0.get(k, (0, []))[0]:
            old = {(round(q.x, 2), round(q.y, 2)) for q in C0.get(k, (0, []))[1]}
            new_sp = [q for q in sp if (round(q.x, 2), round(q.y, 2)) not in old] or sp
            if k[0] == "PAD-OPEN":            # the clusters that changed
                new_sp = [q for kk, s2 in F1.items() if kk[0] == "PAD-OPEN-SET" and kk[1] == k[1] and kk not in F0
                          for q in s2] or new_sp
            out.append((k + (n,), new_sp))
    return out


COSMETIC = ("ACUTE", "FOLD", "LOOP", "DEAD")   # lqfix rewrites: blocked first when they share a finding


def attribute(new, keys, geos, widen=0.0, region_fn=None):
    """-> ({edit key: finding}, [unattributed findings]): each new finding goes to the edit(s) nearest its spots
    (all within NEAR_MM of the nearest + 0.05; beyond that the nearest within FAR_MM, LQ_FAR_MM for layout items)"""
    if not geos:
        return {}, [str(k)[:200] for k, _ in new]
    tree = STRtree(geos)
    cul, un = {}, []
    for k, spots in new:
        far = LQ_FAR_MM if k[0] in ("LQ", "POUR-STITCH", "DIFFPAIR") else FAR_MM
        hit = False
        reg = region_fn(k, spots) if region_fn is not None and k[0] in ("PAD-OPEN", "UNCONNECTED", "PLANE-ISLAND") else None
        if reg is not None and not reg.is_empty:
            # a pour net split by the refill: every edit (any net) inside its former fill there, or within clearance
            for j in tree.query(reg, predicate="intersects"):
                cul.setdefault(keys[j], str(k)[:200] + " (pour split)")
                hit = True
        for sp in spots:
            ds = sorted((geos[j].distance(sp), j) for j in tree.query(sp.buffer(far)))
            if not ds or ds[0][0] > far:
                continue
            dmin = ds[0][0]
            lim = min(NEAR_MM, dmin + 0.05) if dmin <= NEAR_MM else dmin + 0.05
            lim = max(lim, widen) if widen else lim         # later replays: every edit near the spot
            js = [j for d, j in ds if d <= lim]
            cos = [j for j in js if keys[j] and keys[j][0] in COSMETIC]
            for j in (cos or js):                           # a cosmetic rewrite yields first
                cul.setdefault(keys[j], str(k)[:200])
                hit = True
        if not hit:
            un.append(str(k)[:200])
    return cul, un


def arbiter(ctx, base):
    """one DRC + both gates (+ the refilled geometry for pour-split attribution) on the refilled board, as parallel
    processes -> (new findings, (gate fails, layout result, DRC errors, DRC report))"""
    t = time.time()
    gres, lres, d, G = parallel_checks(ctx.board, fast=True, geom_out=wpath("after-geom.json"), tag="arb")
    ctx.times["arbiter"] += time.time() - t
    gf = gres["fails"]
    drcv = drc_guarded(d)
    pads_xy = {f"{p['ref']}.{p['num']}": (p["x"], p["y"]) for p in ctx.G["pads"]}
    now = findings(gf, lres["fails"], drcv, d.get("unconnected_items", []), pads_xy)
    ctx.after_geom = G
    return new_findings(base, now), (gf, lres, drcv, d)


def replay_loop(ctx, max_rounds, base_fn, arbiter_fn, persist=lambda fresh, rp: None):
    """run_once -> arbiter -> block the causing edits -> replay, until no new finding is attributable to an edit.
    Each replay resumes at the first step that emitted a newly blocked edit (every step before it is identical: the
    steps are deterministic and see the same blocked keys). -> (history, (new findings left, payload, unattributed))"""
    history, final = [], None
    for rp in range(MAX_REPLAYS):
        t = time.time()
        run_once(ctx, max_rounds)
        new, payload = arbiter_fn(ctx, base_fn(ctx))
        cul, un = attribute(new, [e["key"] for e in ctx.edits], ctx.geo, widen=ESCALATE_MM if rp >= 1 else 0.0,
                            region_fn=getattr(ctx, "split_region", None))
        fresh = {k: r for k, r in cul.items() if k not in ctx.blocked}
        h = {"replay": rp, "edits": len(ctx.edits), "new_findings": len(new), "blocked_now": len(fresh),
             "unattributed": un, "seconds": round(time.time() - t, 1), "new": [str(k)[:160] for k, _ in new][:80]}
        history.append(h)
        ctx.log(f"replay {rp}: {len(ctx.edits)} edits, {len(new)} new findings, {len(fresh)} edits blocked, "
                f"{len(un)} unattributed, {h['seconds']} s")
        final = (new, payload, un)
        if not fresh:
            break
        ctx.blocked |= set(fresh)
        persist(fresh, rp)
        ctx.prev = ctx.trace
        ctx.resume_at = min(i for i, s in enumerate(ctx.trace) if any(ktuple(k) in fresh for k in s["keys"]))
    return history, final


def angle_hist(G, G0_ids):
    """octilinear check of the copper this run added: count / mm per direction class"""
    h = defaultdict(lambda: [0, 0.0])
    for t in G["tracks"]:
        if t["uuid"] in G0_ids:
            continue
        L = math.dist(t["s"], t["e"])
        if L < 1e-6:
            continue
        a = math.degrees(math.atan2(t["e"][1] - t["s"][1], t["e"][0] - t["s"][0])) % 180.0
        k = next((str(o) for o in (0, 45, 90, 135, 180) if abs(a - o) < 0.5), "free")
        k = "0" if k == "180" else k
        h[k][0] += 1
        h[k][1] += L
    return {k: [v[0], round(v[1], 2)] for k, v in sorted(h.items())}


def drc_counts(d):
    return dict(sorted(Counter(f"{v['type']} ({v['severity']})" for v in d.get("violations", [])).items()))


def run(board, report, max_rounds=2, do_smooth=True, do_bare=True):
    global WORKDIR
    board, report = Path(board).resolve(), Path(report).resolve()
    if not board.with_suffix(".kicad_pro").exists():
        raise SystemExit(f"{board.with_suffix('.kicad_pro')} missing: DRC and the net classes need it beside the board")
    T0 = time.time()
    log = lambda *a: print(*a, flush=True)  # noqa: E731
    WORKDIR = report.with_suffix(".work")
    WORKDIR.mkdir(parents=True, exist_ok=True)
    in_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    # the reference is the REFILLED input (router output carries stale fills: a refill alone changes DRC and the
    # gates, which must not be read as an edit's effect)
    gj = wpath("input-geom.json")
    native_apply(board, set(), {}, [], refill=True, dump_out=gj)
    G0 = annotate(cugraph.load(str(gj)))
    src = board.read_bytes()
    src_sha = hashlib.sha256(src).hexdigest()
    locked = locked_ids(G0)
    log(f"input refilled: {len(G0['tracks'])} tracks, {len(G0['vias'])} vias, {len(locked)} locked items (never edited)")
    t = time.time()
    gres0, lq0, dd0, _ = parallel_checks(board, fast=False, tag="base")
    log(f"base checks {time.time() - t:.0f} s")
    gf0, gc0 = gres0["fails"], gres0["counts"]
    d0 = drc_guarded(dd0)
    log("before", json.dumps({k: v for k, v in gc0.items() if v}))
    pads_xy = {f"{p['ref']}.{p['num']}": (p["x"], p["y"]) for p in G0["pads"]}
    bfile = report.with_suffix(".blocked.json")
    blocked, binfo = set(), {}
    if bfile.exists():
        bj = json.loads(bfile.read_text(encoding="utf-8"))
        if bj.get("input_sha256") == src_sha:
            binfo = {json.dumps(b["key"]): b for b in bj["blocked"]}
            blocked = {ktuple(b["key"]) for b in bj["blocked"]}
    snapdir = WORKDIR / "snap"
    snapdir.mkdir(exist_ok=True)
    ctx = Ctx(board, locked, dd0.get("violations", []), gf0, gf0, blocked, snapdir, do_smooth, do_bare, log)
    ctx.src, ctx.G0 = src, json.dumps(G0)
    base_find = findings(gf0, lq0["fails"], d0, dd0.get("unconnected_items", []), pads_xy)
    base_fn = lambda c: base_find  # noqa: E731

    def persist(fresh, rp):
        for k, r in fresh.items():
            binfo[json.dumps(kjson(k))] = {"key": kjson(k), "replay": rp, "reason": r}
        bfile.write_text(json.dumps({"input_sha256": src_sha, "blocked": list(binfo.values())}, indent=1),
                         encoding="utf-8")
    history, (new, (gf, lres, drcv, dd), un) = replay_loop(ctx, max_rounds, base_fn, arbiter, persist)
    t = time.time()
    gfull = run_gate(board, fast=False)          # the report's after counts: the full gate (TRACK-JOG screened)
    ctx.times["final full gate"] += time.time() - t
    gc1 = gfull["counts"]
    s0 = {drc_sig(v) for v in d0}
    G0o = json.loads(ctx.G0)
    ahist = angle_hist(ctx.G, {t["uuid"] for t in G0o["tracks"]})
    del G0o
    rep = {"board": str(board), "input_sha256": in_sha, "refilled_input_sha256": src_sha,
           "output_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
           "locked_items": len(locked), "locked_edits_dropped": ctx.locked_skipped,
           "added_segment_angles": ahist,
           "gate_before": gc0, "gate_after": gc1, "layout_before": lq0["counts"], "layout_after": lres["counts"],
           "drc_before": drc_counts(dd0), "drc_after": drc_counts(dd),
           "unconnected_before": len(dd0.get("unconnected_items", [])),
           "unconnected_after": len(dd.get("unconnected_items", [])),
           "drc_new": [{"type": v["type"], "severity": v["severity"], "description": v["description"],
                        "items": [(i["description"], i.get("pos")) for i in v["items"]]}
                       for v in drcv if drc_sig(v) not in s0],
           "new_findings_left": [str(k)[:200] for k, _ in new], "unattributed": un,
           "edit_counts": dict(sorted(Counter(e["class"] for e in ctx.edits).items())),
           "edits": [dict(e, key=kjson(e["key"])) for e in ctx.edits], "blocked": list(binfo.values()),
           "unfixed": ctx.unfixed, "replays": history,
           "steps": [{k: v for k, v in s.items() if k not in ("keys", "unfixed", "round_gate")} for s in ctx.trace],
           "times_s": {k: round(v, 1) for k, v in ctx.times.items()}, "wall_s": round(time.time() - T0, 1)}
    report.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    shutil.rmtree(WORKDIR, ignore_errors=True)
    log("after ", json.dumps({k: v for k, v in gc1.items() if v}))
    log("layout before", json.dumps({k: v for k, v in lq0["counts"].items() if v}))
    log("layout after ", json.dumps({k: v for k, v in lres["counts"].items() if v}))
    log("added segment angles (count, mm)", json.dumps(ahist))
    log("drc guarded before", len(d0), "after", len(drcv), "new", len(rep["drc_new"]), "| unconnected",
        rep["unconnected_before"], "->", rep["unconnected_after"], "| edits", len(ctx.edits), "blocked", len(binfo),
        "replays", len(history), "wall", rep["wall_s"], "s")
    return 1 if any(gc1.get(k) for k in CLEAN + DEBRIS) else 0


def _path(p):
    q = Path(p)
    return q if q.is_absolute() or q.exists() else ROOT / q


def main(argv):
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    board, rep = _path(argv[0]), _path(argv[1])
    mr = int(argv[argv.index("--max-rounds") + 1]) if "--max-rounds" in argv else 2
    try:
        return run(board, rep, mr, "--no-smooth" not in argv, "--no-bare" not in argv)
    except Exception:
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
