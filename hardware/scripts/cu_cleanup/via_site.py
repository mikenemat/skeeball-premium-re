# ported from din8r-chassis-thermal/scripts/cu_cleanup/via_site.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R tools/pfr2/via_site.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN)
"""Via-site legality, the ONE rule shared with the gates (DIN-8R owner 2026-10-05: pad-edge and half-in-pad vias are
defects, every time).

CT adaptation (2026-10-17): the gate constants and padedge_class() are compiled from CT's OWN gates
(scripts/qa_copper_landing.py, scripts/qa_layout_quality.py), never the parent's.

A via disc either sits WHOLLY inside an SMD pad of its own net, >= VIP_MARGIN inside the land (a true via-in-pad), or
keeps >= qa_copper_landing.PADEDGE_GAP_MM from the copper of every SMD / connector pad (any net) on every layer it
shares. Everything else is a qa_copper_landing VIA-PADEDGE / VIA-PARTIAL / qa_layout_quality VIA-PADGAP / VIA-INPAD.
No via in the pads of an 0402 part (qa_layout_quality NO_VIP_FP_RE on the footprint name).

qa_copper_landing imports pcbnew, so CPython cannot import it: padedge_class() and PADEDGE_GAP_MM / PADEDGE_MIN_FRAC are
compiled here from the gate's own source text (ast), so fixer and gate cannot disagree.

  site_faults(G_or_PadIndex, via, (x, y)) -> [] when legal, else [(class, pad, layer)]   (dump_geom dicts)
"""
import ast
import math
import re
import sys
from pathlib import Path

from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cugraph  # noqa: E402
from cugraph import ring_poly  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
QA = SCRIPTS / "qa_copper_landing.py"
QL = SCRIPTS / "qa_layout_quality.py"
EPS = 1e-4                 # geometry slack (gate rounding)


def _compile(path, names, funcs=()):
    """the named module-level assignments / functions of a gate script, compiled from its source (no pcbnew import)"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [n for n in tree.body if (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name in funcs)]
    ns = {"Point": Point, "math": math, "re": re}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)
    missing = (set(names) | set(funcs)) - set(ns)
    assert not missing, f"{path.name}: {missing} not found"
    return ns


_G = _compile(QA, {"PADEDGE_MIN_FRAC", "PADEDGE_GAP_MM", "STITCH_MIN_MM2", "STITCH_MM2_PER_VIA", "STITCH_MIN_VIAS",
                   "STITCH_REACH_MM", "STITCH_REACH_TOL_MM2", "ISLAND_MIN_MM2", "FENCE_EDGE_MM", "FENCE_PITCH_MM",
                   "PAD_CENTRE_TOL"},
              {"padedge_class"})
_L = _compile(QL, {"VIP_MARGIN_MM", "NO_VIP_FP_RE", "VIA_HOP_MM", "NECK_TOL_MM"})
padedge_class = _G["padedge_class"]
PADEDGE_GAP_MM = _G["PADEDGE_GAP_MM"]
PADEDGE_MIN_FRAC = _G["PADEDGE_MIN_FRAC"]
GATE = {k: v for k, v in _G.items() if k.isupper()}      # the copper gate's stitch / island / fence constants
VIP_MARGIN = _L["VIP_MARGIN_MM"]           # via-in-pad: the disc this far inside the land (qa_layout_quality VIA-INPAD)
NO_VIP_FP_RE = _L["NO_VIP_FP_RE"]          # "absolutely no vias in 0402s": no via in their pads
VIA_HOP_MM = _L["VIA_HOP_MM"]
NECK_TOL_MM = _L["NECK_TOL_MM"]


def no_vip_refs(G):
    """refs whose footprint name is an 0402 / 1005 metric (qa_layout_quality NO_VIP_FP_RE): no via-in-pad at all"""
    return {f["ref"] for f in G.get("footprints", []) if NO_VIP_FP_RE.search(f.get("fpid", ""))}


def via_layers(v, layers):
    """a plan via (no top / bot) is a through via"""
    if "top" not in v or "bot" not in v:
        return set(layers)
    return set(cugraph.via_layers(v, layers))


class PadIndex:
    """SMD / connector pad polygons per copper layer of a geom dict"""

    def __init__(self, G):
        self.layers = G["layers"]
        self.no_vip = no_vip_refs(G)
        self.items = []                       # (poly, layer, pad)
        for p in G["pads"]:
            if p.get("drill") or not p["shapes"]:
                continue                      # SMD / connector lands only (a same-net PTH annulus kiss is no land)
            for L, rs in p["shapes"].items():
                polys = [ring_poly(r) for r in rs]
                g = unary_union(polys) if len(polys) > 1 else (polys[0] if polys else None)
                if g is not None and not g.is_empty:
                    self.items.append((g, L, p))
        self.tree = STRtree([x[0] for x in self.items]) if self.items else None

    def near(self, g):
        return [self.items[i] for i in self.tree.query(g)] if self.tree is not None else []


def vip_fits(g, c, r):
    """a via disc (centre c, radius r) wholly inside pad polygon g with >= VIP_MARGIN to spare"""
    return g.buffer(-VIP_MARGIN + EPS).contains(c.buffer(r))


def site_faults(ix, v, at=None, layers=None, net=None):
    """-> [] when a via of v's size / net / layer span at `at` is legal by the rule above, else [(class, pad, layer)].
    ix: a PadIndex (or a geom dict). class: the gate's padedge_class (edge / drilled / foreign / intentional / gap) or
    "inpad-unfit" (centre in an own pad, disc not >= VIP_MARGIN inside) / "inpad-0402" (any via in an 0402's pad)"""
    if not isinstance(ix, PadIndex):
        ix = PadIndex(ix)
    x, y = at if at is not None else (v["x"], v["y"])
    c = Point(x, y)
    r = v["d"] / 2
    dr = (v.get("drill") or 0) / 2 or None
    net = v["net"] if net is None else net
    layers = layers or via_layers(v, ix.layers)
    out = []
    for g, L, p in ix.near(c.buffer(r + PADEDGE_GAP_MM + EPS)):
        if L not in layers:
            continue
        same = p["net"] == net
        if g.contains(c):
            if not same:
                out.append(("foreign", p, L))
            elif p["ref"] in ix.no_vip:
                out.append(("inpad-0402", p, L))
            elif not vip_fits(g, c, r):
                out.append(("inpad-unfit", p, L))
            continue
        cls = padedge_class(g, c, r, same, dr)[0]
        if cls is None and g.distance(c) - r < PADEDGE_GAP_MM - EPS:
            cls = "gap"                       # the gate's own rounding margin, kept on the safe side
        if cls is not None:
            out.append((cls, p, L))
    return out


def legal(ix, v, at=None, **kw):
    return not site_faults(ix, v, at, **kw)
