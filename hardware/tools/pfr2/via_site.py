_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]   # project root (tools/pfr2/ -> ..)
# ported from din-relay-8ch/tools/pfr2/via_site.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Via-site legality, the ONE rule shared by pfr2 / land_stubs / pour_stitch / copper_cleanup (owner 2026-10-05: pad-edge
and half-in-pad vias are defects, every time).

A via disc either sits WHOLLY inside an SMD pad of its own net, >= VIP_MARGIN inside the land (a true via-in-pad), or
keeps >= qa_copper_landing.PADEDGE_GAP_MM from the copper of every SMD / connector pad (any net) on every layer it
shares. Everything else is a qa_copper_landing VIA-PADEDGE (edge / drilled / foreign / intentional) / VIA-PARTIAL /
qa_layout_quality VIA-PADGAP / VIA-INPAD.
Via-in-pad (owner 2026-10-05): both boards are ordered with epoxy-filled + capped vias, so a fitting via-in-pad is fully
legal on MAIN and UI alike - except in the pads of an 0402 part (owner: "absolutely no vias in 0402s...0603 should be
ok"; qa_layout_quality NO_VIP_FP_RE on the footprint name).

qa_copper_landing imports pcbnew, so CPython cannot import it: padedge_class() and PADEDGE_GAP_MM / PADEDGE_MIN_FRAC are
compiled here from the gate's OWN source text (ast), so router, fixers and gate cannot disagree.

  site_faults(G_or_PadIndex, via, (x, y)) -> [] when legal, else [(class, pad, layer)]   (cugraph dump_geom dicts)
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

QA = (_ROOT / "scripts/qa_copper_landing.py")
QL = (_ROOT / "scripts/qa_layout_quality.py")
SMALL_2T_SPAN = 2.6        # qa_layout_quality small2t (pfr2 tidy / PAD-AXIS scope; no via-in-pad restriction any more)
EPS = 1e-4                 # geometry slack (gate rounding; positions are on a 0.005 mm grid at best)


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


_G = _compile(QA, {"PADEDGE_MIN_FRAC", "PADEDGE_GAP_MM"}, {"padedge_class"})
_L = _compile(QL, {"VIP_MARGIN_MM", "NO_VIP_FP_RE"})
padedge_class = _G["padedge_class"]
PADEDGE_GAP_MM = _G["PADEDGE_GAP_MM"]
PADEDGE_MIN_FRAC = _G["PADEDGE_MIN_FRAC"]
VIP_MARGIN = _L["VIP_MARGIN_MM"]           # via-in-pad: the disc this far inside the land (qa_layout_quality VIA-INPAD)
NO_VIP_FP_RE = _L["NO_VIP_FP_RE"]          # owner 2026-10-05 "absolutely no vias in 0402s": no via in their pads


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


def regression_faults(before, after):
    """New pad/via defects, including old vias affected by a footprint move.

    Existing source defects remain release failures; this comparison only detects
    regressions during an incremental routing step. It is not a release waiver.
    """
    def inventory(g):
        ix = PadIndex(g)
        return {(v['uuid'], kind, p['ref'], p['num'], layer)
                for v in g['vias']
                for kind, p, layer in site_faults(ix, v)}
    return sorted(inventory(after) - inventory(before))
