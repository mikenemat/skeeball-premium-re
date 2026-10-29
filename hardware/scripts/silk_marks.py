# ported from din8r-chassis-thermal/scripts/silk_marks.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/pcb_silk.py (C:/work/din-relay-8ch), gate-side subset adapted for CT (no silk generator here)
"""Silkscreen policy + geometry shared by the CT silkscreen gate (scripts/qa_silk.py). KiCad Python.

CT has no silk generator (the parent's pcb_silk.py places designators, labels, hazard marks and the designer's
signature block). This module carries only what the GATE needs, taken from the parent unchanged unless noted:
  NO_SILK_REF, REF_H / REF_W, SILK_PRIORITY, the MARK_* policy, item_geom(), silk_pieces(), mark_policy(),
  placement_marks() (a footprint's own pin-1 / polarity / placement marks).
CT adaptations (each a named decision, see the constants):
  NO_SILK_REF   + "H": CT's mounting holes are H1 / H2 (placement_main.py, MountingHole_2.2mm_M2; the parent's are MH).
  MARK_REQUIRED + "T": T1 (B1608S PoE magnetics) and T2 (PA2467NL flyback) straddle the PRI / SEC barrier; a transformer
                  assembled rotated 180 deg puts its windings on the wrong side of the barrier and reverses the phase
                  dots, so its pin-1 mark is a placement guide like an IC's.
                + "BZ": BZ1 is an ACTIVE 12 V buzzer (GMD12095YB, built-in driver): reversed it stays silent, so its "+"
                  mark is a polarity guide.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const  # noqa: E402,F401  (tools/pylib: shapely for KiCad's Python)

import pcbnew  # noqa: E402

# parts whose reference stays OFF the silk (mechanical / non-assembled): mounting holes, fiducials, net ties.
# Every other part keeps its designator on silk (DIN-8R owner 2026-09-29: "we'd still want those") - small passives too.
NO_SILK_REF = ("NT", "MH", "FID", "H")      # "H": CT mounting holes H1 / H2 (module docstring)
REF_H, REF_W = 1.0, 0.15            # mm: JLC recommended minimum legible silk text height / stroke
# Silk PRIORITY (DIN-8R owner 2026-10-05: "if we have any Pin 1 markings used for placement, or other silkscreen
# placement guides... those must be prioritized over everything else"). Highest first. In every conflict the LOWER item
# moves or shrinks and the higher one stays; a placement mark (a footprint's own pin-1 dot / triangle, polarity "+",
# cathode bar, pin-1 number or outline notch, found by placement_marks()) never moves, shrinks or gets clipped.
# qa_silk.py enforces it (SILK-PIN1-MISSING, SILK-GUIDE-CLIPPED; a SILK-OVERLAP with a mark names the other item).
SILK_PRIORITY = ("placement-mark", "outline", "hazard", "label", "title", "signature", "reference")
MARK_PREFIXES = ("U", "IC", "D", "LED", "Y", "X", "J", "P", "CN", "Q", "C", "T", "BZ")  # can carry a pin-1 / polarity mark
MARK_REQUIRED = ("U", "IC", "D", "LED", "Y", "X", "J", "P", "CN", "T", "BZ")           # ... and must (Q: only if marked)
POLARISED_C_RE = r"^(CP_|C_Elec|CP_Elec|C_Tantal|CP_Tantal)|Tantalum|_Pol"     # a C prefix counts only for these footprints
PIN1_NAMES = ("1", "A1", "K", "+")      # the pad a mark points at, first match wins (cathode K / "+" for 2-pin polar parts)
MARK_REACH_MM = 2.5                     # a mark lies within this of its pin-1 pad
MARK_MARGIN_MM = 0.15                   # ... and this much closer to pin 1 than to pin 1's symmetric image pad
MARK_MATCH_MM = 0.05                    # a silk piece whose symmetric image matches another piece is not a mark
ARC_ERR = 2000                          # nm: polygon approximation error for silk geometry (0.002 mm)


def item_geom(item, layer):
    """Shapely geometry (mm) of a board item on `layer`: strokes for text, the stroked outline for a shape, the pad /
    via shape. Empty when KiCad gives no outline."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, ARC_ERR, pcbnew.ERROR_INSIDE)
    out = []
    for i in range(ps.OutlineCount()):
        def ring(r):
            return [(pcbnew.ToMM(r.CPoint(k).x), pcbnew.ToMM(r.CPoint(k).y)) for k in range(r.PointCount())]
        shell = ring(ps.Outline(i))
        if len(shell) < 3:
            continue
        p = Polygon(shell, [h for h in (ring(ps.Hole(i, j)) for j in range(ps.HoleCount(i))) if len(h) >= 3])
        p = p if p.is_valid else make_valid(p)
        if not p.is_empty:
            out.append(p)
    return unary_union(out) if out else Polygon()


def poly_set_geom(ps):
    """shapely geometry (mm) of a SHAPE_POLY_SET, holes included"""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [(pcbnew.ToMM(o.CPoint(k).x), pcbnew.ToMM(o.CPoint(k).y)) for k in range(o.PointCount())]
        if len(pts) >= 3:
            holes = []
            for j in range(ps.HoleCount(i)):
                h = ps.Hole(i, j)
                hp = [(pcbnew.ToMM(h.CPoint(k).x), pcbnew.ToMM(h.CPoint(k).y)) for k in range(h.PointCount())]
                if len(hp) >= 3:
                    holes.append(hp)
            p = Polygon(pts, holes)
            out.append(p if p.is_valid else p.buffer(0))
    return unary_union(out) if out else Polygon()


def silk_pieces(fp, layer):
    """The footprint's own drawings on `layer` (fields excluded), an unfilled outline split into its edges so a notch
    or a cathode bar drawn as part of one polyline is a piece of its own: [{item, uuid, geom, text}]."""
    from shapely.geometry import LineString
    pieces = []
    for d in fp.GraphicalItems():
        if d.GetLayer() != layer:
            continue
        uid = d.m_Uuid.AsString()
        if isinstance(d, pcbnew.PCB_TEXT):
            if d.IsVisible():
                pieces.append({"item": d, "uuid": uid, "geom": item_geom(d, layer), "text": d.GetShownText(False)})
            continue
        if not isinstance(d, pcbnew.PCB_SHAPE):
            continue
        pts = None
        if d.GetShape() == pcbnew.SHAPE_T_RECT and not d.IsAnyFill():
            pts = list(d.GetRectCorners())
        elif d.GetShape() == pcbnew.SHAPE_T_POLY and not d.IsAnyFill() and d.GetPolyShape().OutlineCount():
            o = d.GetPolyShape().Outline(0)
            pts = [o.CPoint(k) for k in range(o.PointCount())]
        if pts and len(pts) >= 2:
            r = pcbnew.ToMM(d.GetWidth()) / 2
            for a, c in zip(pts, pts[1:] + pts[:1]):
                if a != c:
                    seg = LineString([(pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)), (pcbnew.ToMM(c.x), pcbnew.ToMM(c.y))])
                    pieces.append({"item": d, "uuid": uid, "geom": seg.buffer(max(r, 0.01)), "text": ""})
        else:
            pieces.append({"item": d, "uuid": uid, "geom": item_geom(d, layer), "text": ""})
    return [p for p in pieces if not p["geom"].is_empty]


def prefix(ref):
    return "".join(c for c in ref if c.isalpha())


def mark_policy(fp):
    """(can_carry, required, pin1_pads): does this part get a pin-1 / polarity mark check, and must it have one."""
    import re
    pfx = prefix(fp.GetReference())
    if (pfx not in MARK_PREFIXES or pfx in NO_SILK_REF or fp.IsDNP() or fp.IsBoardOnly()
            or (pfx == "C" and not re.search(POLARISED_C_RE, str(fp.GetFPID().GetLibItemName())))):
        return False, False, []
    pads = list(fp.Pads())
    if len({p.GetNumber() for p in pads if p.GetNumber()}) < 2:
        return False, False, []            # one electrical pin (a single-pole terminal, a test point): no orientation
    for name in PIN1_NAMES:
        p1 = [p for p in pads if p.GetNumber() == name]
        if p1:
            return True, pfx in MARK_REQUIRED or pfx == "C", p1
    return False, False, []


_D4 = (((-1, 0), (0, -1)), ((-1, 0), (0, 1)), ((1, 0), (0, -1)), ((0, 1), (1, 0)), ((0, -1), (-1, 0)),
       ((0, -1), (1, 0)), ((0, 1), (-1, 0)))


def _frame_angle(fp):
    """Rotation (deg) of the footprint's local axes on the board, found from its pads (any flip / sign convention)."""
    import math
    th = fp.GetOrientationDegrees()
    if abs(th / 90.0 - round(th / 90.0)) < 1e-6:
        return 0.0
    o = fp.GetPosition()
    pairs = [((pcbnew.ToMM(p.GetFPRelativePosition().x), pcbnew.ToMM(p.GetFPRelativePosition().y)),
              (pcbnew.ToMM(p.GetPosition().x - o.x), pcbnew.ToMM(p.GetPosition().y - o.y))) for p in fp.Pads()]
    for s in (1, -1):
        a = math.radians(s * th)
        for m in (((1, 0), (0, 1)),) + _D4:
            ok = True
            for (lx, ly), (bx, by) in pairs:
                x, y = m[0][0] * lx + m[0][1] * ly, m[1][0] * lx + m[1][1] * ly
                if math.hypot(x * math.cos(a) - y * math.sin(a) - bx, x * math.sin(a) + y * math.cos(a) - by) > 0.01:
                    ok = False
                    break
            if ok:
                return s * th
    return th


def placement_marks(fp):
    """The footprint's own pin-1 / polarity / placement marks on its own side's silk: [piece] (see silk_pieces).

    A piece is a mark when it lies within MARK_REACH_MM of the pin-1 pad and breaks the pad pattern's symmetry on the
    pin-1 side: for a symmetry g of the pads (D4 about the pad centroid, footprint axes) that moves pin 1 to another
    pad, the piece is MARK_MARGIN_MM closer to pin 1 than to that image pad and g(piece) matches no other piece (a
    dot, triangle, chamfer, notch, cathode bar, "+", a "1"). An outline that the symmetry maps onto itself is not a
    mark. With no such symmetry (the pads alone fix the orientation) a piece that is MARK_MARGIN_MM closer to pin 1
    than to every other pad counts."""
    import math
    from shapely import affinity
    can, _req, p1 = mark_policy(fp)
    if not can:
        return []
    layer = pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS
    cu = pcbnew.B_Cu if fp.IsFlipped() else pcbnew.F_Cu
    pieces = silk_pieces(fp, layer)
    if not pieces:
        return []
    pads = list(fp.Pads())
    pnames = {p.GetNumber() for p in p1}
    geo = {p.m_Uuid.AsString(): item_geom(p, cu if p.IsOnLayer(cu) else pcbnew.F_Cu) for p in pads}
    cen = [(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)) for p in pads]
    cx, cy = sum(x for x, _ in cen) / len(cen), sum(y for _, y in cen) / len(cen)
    size = [tuple(sorted((round(pcbnew.ToMM(p.GetBoundingBox().GetWidth()), 2),
                          round(pcbnew.ToMM(p.GetBoundingBox().GetHeight()), 2)))) for p in pads]
    a = math.radians(_frame_angle(fp))
    ca, sa = math.cos(a), math.sin(a)
    images = []                                     # (affine matrix, image pads) per pad symmetry that moves pin 1
    for g in _D4:
        # board-frame matrix G = R(a) g R(-a)
        r = ((ca, -sa), (sa, ca))
        ri = ((ca, sa), (-sa, ca))

        def mul(m, n):
            return tuple(tuple(sum(m[i][k] * n[k][j] for k in range(2)) for j in range(2)) for i in range(2))
        G = mul(mul(r, g), ri)

        def tf(x, y):
            dx, dy = x - cx, y - cy
            return cx + G[0][0] * dx + G[0][1] * dy, cy + G[1][0] * dx + G[1][1] * dy
        mapping, ok = {}, True
        for i, (x, y) in enumerate(cen):
            tx, ty = tf(x, y)
            j = next((j for j, (u, v) in enumerate(cen) if abs(u - tx) < 0.02 and abs(v - ty) < 0.02
                      and size[j] == size[i]), None)
            if j is None:
                ok = False
                break
            mapping[i] = j
        if not ok:
            continue
        img = [pads[mapping[i]] for i, p in enumerate(pads) if p.GetNumber() in pnames]
        img = [q for q in img if q.GetNumber() not in pnames]
        if img:
            mat = [G[0][0], G[0][1], G[1][0], G[1][1], cx - G[0][0] * cx - G[0][1] * cy, cy - G[1][0] * cx - G[1][1] * cy]
            images.append((mat, img))
    others = [q for q in pads if q.GetNumber() not in pnames and q.GetNumber()]
    marks = []
    for pc in pieces:
        g = pc["geom"]
        d1 = min(g.distance(geo[q.m_Uuid.AsString()]) for q in p1)
        if d1 > MARK_REACH_MM:
            continue
        if images:
            for mat, img in images:
                if d1 + MARK_MARGIN_MM >= min(g.distance(geo[q.m_Uuid.AsString()]) for q in img):
                    continue
                gi = affinity.affine_transform(g, mat)
                if any(gi.hausdorff_distance(q["geom"]) < MARK_MATCH_MM for q in pieces):
                    continue
                marks.append(pc)
                break
        elif others and d1 + MARK_MARGIN_MM < min(g.distance(geo[q.m_Uuid.AsString()]) for q in others):
            marks.append(pc)
    return marks
