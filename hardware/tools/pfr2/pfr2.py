# ported from din-relay-8ch/tools/pfr2/pfr2.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""DIN8R grid router v2 (PathFinder-style negotiated congestion), SBC-1 port (2-layer board model, see the
SBC-1 block below the imports and docs/ROUTING_PLAYBOOK.md).

  python pfr2.py GEOM.json OUT_PLAN.json [--nets N1,N2] [--exclude A,B] [--iters 30] [--res 0.05]

Input: dump_geom JSON of a board whose open connections are to be routed (existing copper is kept, fixed).
Output: plan JSON {"tracks": [{net, layer, s, e, w}], "vias": [{net, x, y, d, drill}], "unrouted": {...},
"neck_boxes": [...]} for pfr_import.py (native KiCad add with guards).

Model (all distances mm):
  * routing layers F.Cu, In2.Cu, In3.Cu, B.Cu (class-allowed subset); through vias F..B. In1 / In4 GND / GND_ISO pours
    are re-filled around new copper and are not obstacles;
  * static legality per net = per-layer SLACK raster: min over foreign copper groups of (distance - required clearance),
    the required clearance of every foreign net from the board's DRU (place_gate.required: class max, ETH_CHASSIS 2.0,
    LINE / SELV 6.5, HV functional rules), plus rule-area keep-outs, MDI corridor, edge 0.4, NPTH 0.25, drill-to-drill;
  * plane nets (pours on In1 / In4): every comp not yet on the plane is joined by the shortest path to a legal via site
    inside the pour ("drop via", via-in-pad allowed: all vias are filled + capped, JLC POFV);
  * power / plane nets are routed first, sequentially, and their copper is drawn into the obstacle rasters (exact
    clearances for everything after them); signal nets then negotiate (present x 1.6 per pass + history);
  * necks: PWR_FAULT nets may narrow (>= 0.5) ONLY inside their PWR_NECK boxes (SMD pad bbox + 1.0, regenerated at
    import); other power nets may narrow to their floor within 0.9 mm of their own pads; every emitted width is clipped
    to the local slack, and track runs wholly inside own copper are trimmed;
  * every new via blocks a hole-to-hole disc for all later vias (0.3 mm edge to edge);
  * 60 Hz pickup rules (scripts/pcb_pickup_rules.py, DEEPDIVE 4.2): an ISLAND_HIZ net (dump_geom 'classes') may not put
    a track into HIZ_OUTER_KO_F / _B (F / B) or HIZ_INNER_KO (In2 / In3), nor a via into any of them (the areas cut
    out every HIZ pad + 1 mm escape; an outer-area via is also legal wholly inside the net's own copper), nor a via into
    HIZ_VIA_KO (4.5 mm around HV copper, only the HIZ pads themselves cut out); RS_VIA_KO is
    an ordinary no-track keep-out (In2 / In3) over the shunt force-land via sites (test_pfr2_pickup.py).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import collections
import json
import math
import sys
import time
from collections import defaultdict
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import cugraph
import place_gate
from shapely.geometry import Point, LineString, box as sbox
from shapely.ops import unary_union, nearest_points
from shapely.strtree import STRtree
import shapely
from pfr_core import astar, astar_ws, stamp, down_any, coarsen_prep, corridor, mask_layers, octile_dt, down_region, corridor_sub
import threading
from pfr_tidy import tidy_run
from pfr_edt import edt as EDT        # pfr2-speed: exact numba EDT (bit-identical to scipy's, nogil)
import os

INNER_SELV = 0.15        # SELV-SELV track / space on the 0.5 oz inner layers (JLC multilayer 0.09 / 0.09 mm;
                         # DRU rule "SELV inner fine pitch"); outer 2 oz layers keep 0.20 / 0.20
# SBC-1 board model (2026-10-27): 2 copper layers, both routing layers. No plane-only layer: PLANE_LAYERS (layers
# where a plane net's own copper is not drawn / reservations ignored) is empty. PLANE_FILL_LAYERS = where a plane
# net's pour fill is the drop-via target: the B.Cu GND pour (every F.Cu GND pad drops a via into it, the classic
# 2-layer decap fan-out; THT GND pads touch it directly). The F.Cu GND pour is soft (refilled) like DIN-8R's planes.
# 4-LAYER (pass 5, owner 2026-10-26): In1.Cu = solid GND plane, never routed (DIN-8R PLANE_LAYERS semantics: the
# plane net's own copper is not drawn there, its fill is the drop-via target); routing on F.Cu / In2.Cu / B.Cu. The
# F.Cu / B.Cu GND pours stay soft (refilled, never connectivity).
ALL_LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
RL = ["F.Cu", "In2.Cu", "B.Cu"]                          # routing layers
PLANE_LAYERS = ("In1.Cu",)
PLANE_FILL_LAYERS = ("In1.Cu",)
SOFT_FILL_CONNECTS = False   # see main(): F.Cu GND fill is not connectivity for the router (SBC-1)
MIN_CLR = 0.15            # SBC-1 pcb_rules: every class clearance 0.15 (QFN-80 0.4 mm pitch); DIN-8R floor was 0.20
MIN_W = 0.15              # SBC-1 pcb_rules m_TrackMinWidth
OUTER = ("F.Cu", "B.Cu")
# class -> (width outer, width inner, via d, via drill, neck floor or None, outer-only)
# SBC-1 classes = scripts/pcb_rules.py CLASS_W (widths) / vias; current nets are raised to current_budget.required_width
# by net_params (e.g. +5V_SYS 2 A -> 1.116 mm, necking to the floor only within NECK_MM of a narrower own pad).
# "SELV" stays as the fallback key (= Default).
CLS = {
    "Default": (0.20, 0.20, 0.6, 0.3, None, False), "SELV": (0.20, 0.20, 0.6, 0.3, None, False),
    "Rail": (0.20, 0.20, 0.6, 0.3, 0.15, False), "Power": (0.40, 0.40, 0.6, 0.3, 0.20, False),
    "Audio": (0.30, 0.30, 0.6, 0.3, 0.20, False), "Power5": (0.50, 0.50, 0.8, 0.4, 0.20, False),
    "PowerLight": (0.60, 0.60, 0.8, 0.4, 0.30, False),
}
# DIN-8R: GND / logic rails on .45 / .20 vias. SBC-1: JLC 2-layer minimum 0.6 / 0.3 everywhere -> none
SMALL_VIA_NETS = set()
NET_OVERRIDE = {}
POWER_CLASSES = {"Power", "Audio", "Power5", "PowerLight"}   # SBC-1 (DIN-8R: POWER_SELV / PWR15 / PWR_FAULT / COIL)
PWR_FAULT_NETS = ()                                       # DIN-8R pcb_power PWR_NECK nets; none on SBC-1
NECK_REACH = 1.0                                          # pcb_power.neck_areas(reach=1.0)
SOFT_ZONES = ("GND",)                           # SBC-1 plane net: the F.Cu / B.Cu GND pours (refilled)
# rev C r4: outer SELV pours that are refilled around new copper (not obstacles; plan_check skips them too). The relay
# band's +V_PULL rail (rail_geom "_KO" zone, a rev-B ML-D keep-out) only feeds 8 coils + the DRV8803s in rev C; its
# continuity to every A1 pad is re-checked after the refill (open joins / unconnected).
SOFT_POURS = ()                                  # DIN-8R +V_PULL; none on SBC-1
MDI_CORRIDOR = None                              # DIN-8R MDI keep-out corridor; flag off on SBC-1
HOLE_TO_HOLE = 0.3
# B1-v2 island rails (owner 2026-10-04, island-place/b1v2): the +-1.2 V follower rails and the reset hold line run
# from the east-end supply cell to all four cells across the whole island; routed FIRST and frozen (sequential, before
# the negotiated signals and the island trunk) so they are never shut out of the passages - the reusable form of the
# rail lane. DC, < 1 mA: ISLAND 0.2 / 0.2, 0.6 / 0.3 vias, any routing layer (not ISLAND_HIZ)
RAIL_NETS = ()                                   # DIN-8R island rails; none on SBC-1
RAIL_WINDOW = 1000.0                      # mm of pad around the rail components = the whole board (bbox_of clamps)
FROZEN_POWER = {"+5V_SYS"} | set(RAIL_NETS)                          # SBC-1: the eFuse output trunk   # routed first and frozen; every other
                                                                       # power net negotiates with the signals
# LINE / COM pour POCKETS (2026-10-04, b1v2 lane trial): LINE / COMk (HV_L / HV_LP) pours carry force current only
# inside FORCE_BAND (y 12..74: the L-bus wire to the shunts / COM pours, island-place/iplace.py FORCE_BAND); outside it
# (the four chip bands) the LINE pour is a dead-end pocket at island potential (NT1 ties GND_ISO to LINE) that the
# refill re-pours around island copper at the HV_L clearance (0.35). For ISLAND-class nets such a pocket is NOT an
# obstacle (the same policy as iplace placement, fill_pullback and trial_merge's refill); the force-band part stays
# hard for every net, and for every non-ISLAND net (SELV creepage) the whole pour stays hard. Without this the router
# found no via site for the cell-1 rail pads (the LINE B.Cu pocket under cell 1) while the planner had escaped them.
POCKET_CLASSES = ("HV_L", "HV_LP")
POCKET_SOFT_FOR = ("ISLAND",)
FORCE_BAND = (12.0, 74.0)
NEG_PLANE = {"GND"}      # plane nets whose drops negotiate with the signals (fine-pitch pin escapes compete for sites)
NET_FLOOR = {}
ORDER_FIRST = ["+5V_SYS", "GND", "+5V_IN", "VBUS_HOST", "AMP_OUTP", "AMP_OUTN", "SPK_P", "SPK_N", "+3V3", "+3V3A",
               "+1V1", "VBUS_DBG"]      # SBC-1
# TRACK WIDTH = THE repo rule (owner 2026-10-05: "a validation rule that looks at trace width for appropriate nets as a
# part of every cleaning pass"): scripts/current_budget.required_width = max(class width, IPC-2152 load / fault width),
# the same function qa_copper_landing TRACK-WIDTH gates with. Before 2026-10-05 this router chose narrower copper in
# four places: (1) the CLS / NET_OVERRIDE table sat below the .kicad_pro class widths (COIL 0.30 vs 0.40, the island
# rails +-1V2_BUF 0.20 vs ISLAND 0.25, inner +15V 0.80 vs its 1.28 mm IPC need), (2) the neck zone was 0.9 mm around
# ANY own pad, (3) exact_fix / width_ok let every power net narrow ANYWHERE to its neck floor (POWER_SELV 0.20, PWR15
# 0.25, COIL 0.20, RLY_SNS / RLY_VCLAMP 0.30) and (4) plan_check.floor_of did the same. Now: every current-carrying net
# routes at >= its required width; it may neck (>= its floor) only on a segment <= NECK_MM long that touches an own
# pad narrower than the required width (the gate's neck allowance), PWR_FAULT additionally inside its PWR_NECK box.
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "scripts"))      # SBC-1 scripts/current_budget.py
import current_budget as cb                                                    # noqa: E402
INNER_MAX = 1.0       # router policy: a current net needing > 1.0 mm on the 0.5 oz inner layers routes outer-only (2 oz)
NECK_MM = cb.NECK_MM
# pfr2-up via policy (router-exp: VIA-INPAD 229 / VIA-PADEDGE 78 were the largest router finding classes). The gates:
# qa_layout_quality VIA-INPAD (a via centre in an SMD pad must fit: d <= pad min dim - 2 x 0.05 and the disc inside the
# pad; never on one pad of a <= 0603 two-terminal part), qa_copper_landing VIA-PADEDGE / VIA-PADGAP (centre outside an
# SMD pad but the disc within 0.10 mm of its edge). Such via sites cost VIA_PEN x via_cost extra (not forbidden: a join
# that has no other site still closes); a fitting via-in-pad (EP, large land) costs nothing extra.
# via-edge 2026-10-05: the gate's own constants (tools/via_site.py compiles them from qa_copper_landing's source)
from via_site import VIP_MARGIN, SMALL_2T_SPAN, PADEDGE_GAP_MM as PADEDGE_GAP, no_vip_refs  # noqa: E402
VIA_PEN = 4.0
ONE_LAYER_VIA_FAC = 1.0   # SELV signal nets whose pads can all be reached on ONE outer layer: via cost factor (A/B
                          # 2026-10-05: 1.5 put more copper on the outer layers - findings / join 0.870 -> 0.917,
                          # ACUTE 15 -> 25, PLANE-SLOT 68 -> 75 - with no open-join gain: off by default)
PAD_AXIS_ASPECT = 1.4     # qa_layout_quality.PAD_AXIS_ASPECT: a pad this elongated is left along its long axis
FINE_PITCH_MM = 0.65      # qa_layout_quality.FINE_PITCH_MM (PAD-AXIS scope)
EP_MIN_MM2 = 2.0          # qa_layout_quality.EP_MIN_MM2 (an exposed pad has no axis rule)
AXIS_BAND_MM = 0.35       # tidy step 2: side band beside a PAD-AXIS pad (and beside its axis exit corridor)
AXIS_EXIT_MM = 0.45       # ... reaching this far past the pad's short ends
AXIS_PEN = 8.0            # ... extra cost per cell there (soft: a join with no axis exit still routes)
VIA_SITE_MM = 1.2         # qa_layout_quality.VIA_SITE_MM (VIA-CURRENT: vias this close form one layer-change site)
POUR_GUARD_MM = 0.45      # pour-guard: new foreign copper this close to a pour-only GND pad (A/B: 131 of 164 such
                          # pad groups were open after the refill of the pfr2-up NEW stage)
TIDY_JMAX = 120           # pfr_tidy pull-tight look-ahead (cells along the path, 6 mm at 0.05)
SI_VOID_PEN = 2.0         # SI nets: extra cost per cell over a reference-plane void >= PLANE_SLOT_MM (PLANE-SLOT)
PLANE_SLOT_MM = 3.0       # qa_layout_quality.PLANE_SLOT_MM
SI_NET_RE = __import__("re").compile(r"(SCK|SCLK|MOSI|MISO|_CS\d*$|_CS\d*_|nCS|CLK|XI$|XO$|_XI|_XO|MDI_|RJ_RD|USB_D|SDA|SCL)")
REF_PLANE = {"F.Cu": "In1.Cu", "In2.Cu": "In1.Cu", "B.Cu": "In1.Cu"}   # SBC-1 4-layer: In1 GND (--si-void-pen only)
JOG_W = 2.0               # qa_copper_landing.JOG_W (a staircase step is shorter than JOG_W x width)


def net_params(name, cls, class_track):
    """(width outer, width inner, via d, via drill, neck floor or None, outer-only, current) for one net: the CLS /
    NET_OVERRIDE entry raised to current_budget.required_width for every current-carrying net; impedance nets at their
    qualified outer width, outer-only."""
    p = list(NET_OVERRIDE.get(name, CLS.get(cls, CLS["SELV"])))
    imp = cb.impedance_width("main", name, True)
    current = False
    if imp is not None:
        p[0] = p[1] = imp[0]
        p[4], p[5] = None, True
    elif cb.is_current_net("main", name, cls):
        current = True
        ro, ri = cb.required_width("main", name, True, class_track), cb.required_width("main", name, False, class_track)
        p[0], p[1] = max(p[0], ro), max(p[1], ri)
        if p[1] > INNER_MAX:
            p[5] = True
        if p[4] is None and name in NET_FLOOR:
            p[4] = NET_FLOOR[name]
    return tuple(p) + (current,)


def narrow_pad(poly, w):
    """an own pad a neck may enter: its smaller side is at or below the required width w (a pad exactly as wide as the
    trace still needs a neck once the clearance margin applies - the W5500 0.3 mm pads; owner OK 2026-10-05)."""
    mrr = poly.minimum_rotated_rectangle
    xs, ys = mrr.exterior.coords.xy
    sides = [math.hypot(xs[k + 1] - xs[k], ys[k + 1] - ys[k]) for k in range(2)]
    return min(sides) <= w + 1e-3


def neck_ok(seg, w, wnom, floor, own_pads, boxes=None):
    """a below-required segment is legal only as the gate's neck: >= floor, <= NECK_MM long, touching an own pad
    narrower than wnom (and, for PWR_FAULT, wholly inside one of its PWR_NECK boxes at its width)."""
    if floor is None or w < floor - 1e-9 or seg.length > NECK_MM + 1e-6:
        return False
    if boxes is not None and not any(b.contains(seg.buffer(w / 2)) for b in boxes):
        return False
    return any(narrow_pad(g, wnom) and g.distance(seg) <= 0.05 for g in own_pads)


# 60 Hz pickup rules (scripts/pcb_pickup_rules.py, pcb_setup.DRU_MAIN_PICKUP; DEEPDIVE 4.2, owner 2026-10-04): the
# ISLAND_HIZ leg nets may not put a TRACK into the named areas on the areas' layers, nor a VIA into HIZ_INNER_KO; a via
# in an outer area (HIZ_OUTER_KO_F on F.Cu / _B on B.Cu) is legal only wholly inside the net's own copper there
# (via-in-pad: no new outer copper). The areas carry no keep-out flags (they bind this class only).
HIZ_CLASS = "ISLAND_HIZ"
HIZ_AREAS = {"HIZ_OUTER_KO_F": "F.Cu", "HIZ_OUTER_KO_B": "B.Cu", "HIZ_INNER_KO": None, "HIZ_VIA_KO": "via"}


def hiz_ids(G, nets):
    """net ids carrying the ISLAND_HIZ class: dump_geom 'classes', else the board's .kicad_pro assignments."""
    if any("classes" in v for v in nets.values()):
        return {k for k, v in nets.items() if HIZ_CLASS in v.get("classes", [])}
    import os
    pro = os.path.splitext(G.get("board", ""))[0] + ".kicad_pro"
    if not os.path.exists(pro):
        return set()
    asg = json.load(open(pro, encoding="utf-8"))["net_settings"].get("netclass_assignments") or {}
    names = {n for n, v in asg.items() if HIZ_CLASS in (v if isinstance(v, list) else [v])}
    return {k for k, v in nets.items() if v["name"] in names}


class Grid:
    def __init__(self, x0, y0, x1, y1, res):
        self.x0, self.y0, self.res = x0, y0, res
        self.W = int(math.ceil((x1 - x0) / res))
        self.H = int(math.ceil((y1 - y0) / res))

    def px(self, x, y):
        return ((x - self.x0) / self.res - 0.5, (y - self.y0) / self.res - 0.5)

    def mm(self, j, i):
        return (self.x0 + (j + 0.5) * self.res, self.y0 + (i + 0.5) * self.res)


def draw_geom(img, grid, geom, val):
    d = ImageDraw.Draw(img)
    for g in getattr(geom, "geoms", [geom]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        d.polygon([grid.px(*c) for c in g.exterior.coords], fill=val, outline=val)
        for h in g.interiors:
            d.polygon([grid.px(*c) for c in h.coords], fill=0, outline=None)


_SCR = {}
NOH = np.zeros((1, 1), np.float32)               # astar_ws: no heuristic map (octile to the target bbox)
LEGACY_COMP = os.environ.get("PFR2_LEGACY_COMP") == "1"   # verification: component masks in set order (pre-fix)
OLD_ASTAR = os.environ.get("PFR2_OLD_ASTAR") == "1"
DEBUG_EXP = int(os.environ.get("PFR2_DEBUG_EXP", "0"))       # verification: allocating astar() + per-join target rebuild
FULL_DRAW = os.environ.get("PFR2_FULL_DRAW") == "1"


def draw_local(arr, grid, geom, val):
    """draw_geom(Image.fromarray(arr), grid, geom, val) IN PLACE, without the full-layer round trip (pfr2-speed: the
    former Image.fromarray(full layer) -> draw -> np.array copied 32 MB twice per track / via / layer). The polygons
    are rasterised in the SAME absolute pixel coordinates on a reusable blank full-size 'L' scratch image (PIL's fill
    is not exactly translation-invariant, so a cropped canvas would differ by an edge pixel now and then): exterior
    = 1, holes = 2 (draw_geom paints holes 0 over everything), in draw_geom's order; only the bbox is read back and
    cleared."""
    if geom.is_empty:
        return
    if FULL_DRAW:                                # verification switch: the former full-layer round trip
        img = Image.fromarray(arr)
        draw_geom(img, grid, geom, val)
        arr[...] = np.array(img, dtype=arr.dtype)
        return
    H, W = arr.shape
    bx = geom.bounds
    (fx0, fy0), (fx1, fy1) = grid.px(bx[0], bx[1]), grid.px(bx[2], bx[3])
    j0, i0 = max(0, int(math.floor(fx0)) - 2), max(0, int(math.floor(fy0)) - 2)
    j1, i1 = min(W, int(math.ceil(fx1)) + 3), min(H, int(math.ceil(fy1)) + 3)
    if j1 <= j0 or i1 <= i0:
        return
    img = _SCR.get((W, H))
    if img is None:
        img = _SCR[(W, H)] = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    for g in getattr(geom, "geoms", [geom]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        d.polygon([grid.px(*c) for c in g.exterior.coords], fill=1, outline=1)
        for h in g.interiors:
            d.polygon([grid.px(*c) for c in h.coords], fill=2, outline=None)
    m = np.array(img.crop((j0, i0, j1, i1)))
    img.paste(0, (j0, i0, j1, i1))
    sub = arr[i0:i1, j0:j1]
    sub[m == 1] = val
    sub[m == 2] = 0


def disk(r_cells):
    r = int(math.ceil(r_cells))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    m = yy * yy + xx * xx <= r_cells * r_cells
    return yy[m].astype(np.int64), xx[m].astype(np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("out")
    ap.add_argument("--nets", default="")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--res", type=float, default=0.05)
    ap.add_argument("--margin", type=float, default=0.04)
    ap.add_argument("--via-cost", type=float, default=12.0)
    ap.add_argument("--max-expand", type=int, default=4_000_000)
    ap.add_argument("--diag", default="", help="comma nets: after the power phase, flood their legal region from every "
                    "comp and write diag-<net>.png next to OUT, then stop")
    ap.add_argument("--probe", default="", help="NET@x,y;x,y : print legality at points (diag mode)")
    ap.add_argument("--srr", type=int, default=0, help="after negotiation: sequential rip-up-and-reroute steps "
                    "(hard legality against every other unit; at most 3 blockers ripped per step, 3 rips per unit)")
    ap.add_argument("--no-exact", action="store_true", help="skip the exact veto rounds (diagnostic runs)")
    ap.add_argument("--threads", type=int, default=1, help="negotiation: route chunks of this many units in parallel "
                    "against the current congestion state, then commit them in order (1 = the sequential PathFinder)")
    ap.add_argument("--par-negotiate", action="store_true", help="experimental: route --threads units per chunk "
                    "in parallel (Jacobi); does not converge in dense regions - off by default")
    # 3 / 5 % (2026-10-04, owner: cap at diminishing returns): on the r5 stage 8 / 3 % took 942 s for 99 open joins,
    # 4 / 5 % 726 s for 98, 3 / 5 % 598 s for 87; earlier logs reach 5 % of the best 8-38 passes before the old stop
    ap.add_argument("--stall", type=int, default=3, help="main negotiation: stop after this many passes without a "
                    "--gain relative improvement of the overlap score")
    ap.add_argument("--gain", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0, help="0 = default signal order; else a deterministic shuffle")
    ap.add_argument("--outer-nets", default="", help="comma nets (or prefix*) routed on F.Cu / B.Cu only")
    ap.add_argument("--f-lane", type=float, default=0.0, help="F-lane rule (mm, default off): F.Cu track / via copper "
                    "of the --f-lane-nets only within this of the net's own F.Cu pads (pad stubs); the rest routes on "
                    "In2 / In3 / B (keeps the F GND pour whole)")
    ap.add_argument("--f-lane-nets", default="", help="comma nets (or prefix*) under --f-lane; default every routed "
                    "signal net (not power class / NET_OVERRIDE / plane nets / GND / GND_ISO / +5V)")
    ap.add_argument("--keepout", default="", help="JSON [{box: [x0, y0, x1, y1], why, layers?}]: space reserved for a "
                    "pending re-placement - no track / via of a net that has no pad inside the box; with layers (e.g. "
                    "[\"B.Cu\"], a part keep-in on one face) tracks are kept out on those layers only, vias on all")
    ap.add_argument("--budget", type=float, default=0.0, help="seconds of wall time for this run (owner performance "
                    "rule): the main negotiation stops at 55 %%, the sequential rip-up at 75 %%; the exact rounds then "
                    "finish the plan from the best state reached (0 = unbounded)")
    ap.add_argument("--reserve", default="", help="escape-reservation JSON {sites: [{x, y, net, d}]} (island-place/b1v2/"
                    "escape_reservations.py): each site is held for its net - drawn as that net's copper (a phantom via "
                    "on every layer) so no other net may route or drop a via there; the owner may use it or not")
    ap.add_argument("--preplan", default="", help="plan JSON of fixed new copper drawn before routing (via farms); "
                    "its tracks / vias are carried into the output")
    # pfr2-up (2026-10-05, router-exp lessons). ALWAYS ON (no routing change): legal checkpoint plans during the exact
    # rounds (a variant killed at its timeout keeps its best legal plan; stage_loop accepts it) and output de-duplication.
    # OPT-IN, off by default (A/B pfr2-up/ab: none met the lead's bar "open joins <= OLD AND every finding class <=
    # OLD" on its own; the SUBB set --exact-clock --rescue --via-policy came closest - see the pfr2-up hand-back):
    ap.add_argument("--exact-clock", action="store_true", help="run the exact veto rounds under the budget clock: "
                    "re-negotiation only until 80 %% of --budget, then the greedy keep (+ --rescue by 95 %%)")
    ap.add_argument("--rescue", action="store_true", help="exact rescue after the greedy keep: every dropped join is "
                    "re-routed one at a time with hard occupancy + exact legality")
    ap.add_argument("--via-policy", action="store_true", help="via-site costs: non-fitting via-in-SMD-pad / pad-edge "
                    "vias (VIA-INPAD / VIA-PADEDGE / VIA-PADGAP), the VIA-INPAD fit margin for the in-pad exemption, and "
                    "--one-layer-via-fac")
    ap.add_argument("--one-layer-via-fac", type=float, default=ONE_LAYER_VIA_FAC, help="via policy: via cost factor "
                    "of SELV signal nets whose pads can all be reached on one outer layer")
    ap.add_argument("--si-void-pen", type=float, default=0.0, help="extra track cost per cell for SI nets "
                    "(qa_layout_quality SI_NET_RE) over a >= 3 mm void of their reference plane (PLANE-SLOT); A/B "
                    f"value {SI_VOID_PEN}; 0 = off")
    ap.add_argument("--pour-guard", action="store_true", help="GND pour-guard drop-via pairs (a GND pad joined to the "
                    "plane only through an outer pour gets its own drop vias when new foreign copper passes within "
                    "POUR_GUARD_MM of it: the refill would cut it off)")
    ap.add_argument("--tidy", action="store_true", help="EXPERIMENTAL: octilinear pull-tight of every routed run "
                    "(pfr_tidy.tidy_run; staircases / detour loops / pad-centre anchors / pad-axis exits)")
    # pfr2-speed (2026-10-05): DETERMINISTIC schedule - work counts instead of wall-clock fractions, so a run is
    # reproducible on a loaded machine (A/B without timing noise); --budget stays as the safety net only
    ap.add_argument("--det", action="store_true", help="deterministic schedule: main negotiation <= --det-neg passes, "
                    "sequential rip-up <= --det-srr steps, exact re-negotiation --det-exact-passes passes after round 0, "
                    "greedy keep (+ --rescue of every lost unit) at round --det-exact-rounds; --budget = safety net")
    ap.add_argument("--det-neg", type=int, default=10)
    ap.add_argument("--det-srr", type=int, default=350)
    ap.add_argument("--det-exact-passes", type=int, default=2)
    ap.add_argument("--det-exact-rounds", type=int, default=1)
    ap.add_argument("--neg-stall3", action="store_true", help="main negotiation stall-stop: unrouted joins not "
                    "improved over 3 passes and overlap cells down < --stall3-gain over them")
    ap.add_argument("--stall3-gain", type=float, default=0.10)
    ap.add_argument("--skip-dead", action="store_true", help="pfr2-speed: units whose open joins are all blocked by "
                    "static legality (reachability-certain) and that overlap nothing are not re-routed in the selective "
                    "negotiation passes nor queued for the sequential rip-up")
    ap.add_argument("--c2f", action="store_true", help="coarse-to-fine A*: 0.1 mm search, then 0.05 mm inside a "
                    "corridor around it (+ full freedom near the pins); fallback to the full fine search")
    ap.add_argument("--c2f-mm", type=float, default=0.8, help="c2f corridor half-width (mm)")
    ap.add_argument("--c2f-hw", type=float, default=2.0, help="c2f coarse A* heuristic weight (2 = admissible: a "
                    "coarse step costs >= 2 x its length)")
    ap.add_argument("--c2f-pin-mm", type=float, default=2.0, help="c2f: fine freedom within this of the pins (mm)")
    ap.add_argument("--axis-pen", type=float, default=None, help="tidy step 2: A* cost per cell in the side bands of "
                    f"PAD-AXIS pads (default {AXIS_PEN} with --tidy, else 0)")
    a = ap.parse_args()
    if a.axis_pen is None:
        a.axis_pen = AXIS_PEN if a.tidy else 0.0
    t0 = time.time()
    PH = {}                                      # pfr2-speed: per-phase wall clock (s), printed at the end

    def phase(name, t_start):
        PH[name] = round(PH.get(name, 0.0) + time.time() - t_start, 1)
    POOL = ThreadPoolExecutor(max(1, a.threads))
    G = cugraph.load(a.geom)
    nets = {int(k): v for k, v in G["nets"].items()}
    name2id = {v["name"]: k for k, v in nets.items()}
    if not SOFT_FILL_CONNECTS:
        # SBC-1: a plane net's fill on a ROUTING layer outside PLANE_FILL_LAYERS (the F.Cu GND pour) is carved by every
        # new F.Cu track and refilled afterwards, so it never counts as connectivity: every F.Cu GND pad gets its drop
        # via into the B.Cu pour (DIN-8R had its planes on unrouted inner layers, where the fill is reliable)
        for z in G["zones"]:
            if not z["rule_area"] and nets.get(z["net"], {}).get("name") in SOFT_ZONES:
                for L in list(z.get("fills", {})):
                    if L not in PLANE_FILL_LAYERS:
                        z["fills"][L] = []
    res, margin = a.res, a.margin
    # ---------------- connectivity groups
    cu = cugraph.Copper(G)
    adj = cu.graph()
    comps = defaultdict(list)
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
        if any(cu.items[u]["kind"] == "pad" for u in comp):
            comps[it["net"]].append(comp)
    excl = set(filter(None, a.exclude.split(",")))
    want = set(filter(None, a.nets.split(",")))
    todo = {n: c for n, c in comps.items() if len(c) > 1 and nets[n]["name"] not in excl
            and (not want or nets[n]["name"] in want) and not nets[n]["name"].startswith("unconnected")}
    print(f"nets to route {len(todo)}, joins {sum(len(c) - 1 for c in todo.values())}", flush=True)
    # ---------------- grid
    ob = unary_union([cugraph.ring_poly(o) for o in G["outline"]])
    bx0, by0, bx1, by1 = ob.bounds
    grid = Grid(bx0, by0, bx1, by1, res)
    H, W = grid.H, grid.W
    print(f"grid {W} x {H} at {res} mm", flush=True)
    # ---------------- label rasters (net id + 1) per layer; GND / GND_ISO pours skipped (refilled)
    lab = {}
    pocket = {}                                  # per layer: LINE / COM pocket fills (net id + 1), soft for ISLAND nets
    band = sbox(-1e4, FORCE_BAND[0], 1e4, FORCE_BAND[1])
    plane_fill = defaultdict(lambda: np.zeros((H, W), bool))
    plane_by = {}                                # (net id, plane layer) -> fill (PLANE-SLOT voids for SI nets)
    for L in ALL_LAYERS:
        img = Image.new("I", (W, H), 0)
        pimg_ = Image.new("I", (W, H), 0)
        for z in G["zones"]:
            if z["rule_area"] or L not in z.get("fills", {}):
                continue
            if nets[z["net"]]["name"] in SOFT_POURS:
                continue
            if nets[z["net"]]["class"] in POCKET_CLASSES:
                for r in z["fills"][L]:
                    g_ = cugraph.ring_poly(r)
                    draw_geom(img, grid, g_.intersection(band), z["net"] + 1)
                    draw_geom(pimg_, grid, g_.difference(band), z["net"] + 1)
                continue
            if nets[z["net"]]["name"] in SOFT_ZONES:
                if L in PLANE_FILL_LAYERS:
                    pimg = Image.new("L", (W, H), 0)
                    for r in z["fills"][L]:
                        draw_geom(pimg, grid, cugraph.ring_poly(r), 1)
                    plane_fill[z["net"]] |= np.array(pimg, bool)
                    plane_by[(z["net"], L)] = plane_by.get((z["net"], L), np.zeros((H, W), bool)) | np.array(pimg, bool)
                continue
            for r in z["fills"][L]:
                draw_geom(img, grid, cugraph.ring_poly(r), z["net"] + 1)
        for k, it in cu.items.items():
            if it["kind"] == "zone" or L not in it["geo"]:
                continue
            draw_geom(img, grid, it["geo"][L], it["net"] + 1 if it["net"] else 32000)
        lab[L] = np.array(img, dtype=np.int32)
        pocket[L] = np.array(pimg_, dtype=np.int32)
        pocket[L][lab[L] != 0] = 0                # items drawn over the pour keep their own label
    # escape reservations (--reserve): a site whose disc (+ its clearance) meets another net's copper on any layer is
    # skipped (stale against this board); the rest are burned in as the owner net's copper
    reserved = []
    rsv_lab = {L: np.zeros((H, W), np.int32) for L in ALL_LAYERS}
    if a.reserve:
        RS = json.load(open(a.reserve))
        n_skip = 0
        for st in RS.get("sites", []):
            n_ = name2id.get(st["net"])
            if n_ is None:
                n_skip += 1
                continue
            g_ = Point(st["x"], st["y"]).buffer(st.get("d", 0.6) / 2)
            gi = grid.px(st["x"], st["y"])
            j_, i_ = int(round(gi[0])), int(round(gi[1]))
            rr_ = st.get("d", 0.6) / 2 + 0.2 - res          # disc + ISLAND clearance, one cell of raster slack
            r_ = int(np.ceil(rr_ / res))
            oy_, ox_ = np.mgrid[-r_:r_ + 1, -r_:r_ + 1]
            disc_ = (oy_ ** 2 + ox_ ** 2) * res * res <= rr_ * rr_
            yy_, xx_ = i_ + oy_[disc_], j_ + ox_[disc_]
            ok_ = (yy_ >= 0) & (yy_ < H) & (xx_ >= 0) & (xx_ < W)
            yy_, xx_ = yy_[ok_], xx_[ok_]
            clash = False
            for L in ALL_LAYERS:
                sub_ = lab[L][yy_, xx_]
                if ((sub_ != 0) & (sub_ != n_ + 1)).any() and not (L in PLANE_LAYERS and nets[n_]["name"] in SOFT_ZONES):
                    clash = True
                    break
            if clash:
                n_skip += 1
                continue
            # held in a SEPARATE raster: an obstacle for every other net (legality), but never the owner's own copper
            # (drawn into lab it made emit() trim the owner's track inside the disc - a 0.6 mm gap, stage M1-s1)
            for L in ALL_LAYERS:
                if L in PLANE_LAYERS and nets[n_]["name"] in SOFT_ZONES:
                    continue
                draw_local(rsv_lab[L], grid, g_, n_ + 1)
            reserved.append((n_, g_))
        print(f"escape reservations: {len(reserved)} sites held, {n_skip} skipped (net missing / clash)", flush=True)
    # --keepout: reserved boxes (dilated by 0.3 mm so copper stays out of them, not just its centreline)
    KO_BOXES = []
    if a.keepout:
        for kb in json.load(open(a.keepout)):
            x0, y0, x1, y1 = kb["box"]
            img_ = Image.new("L", (W, H), 0)
            draw_geom(img_, grid, sbox(x0 - 0.3, y0 - 0.3, x1 + 0.3, y1 + 0.3), 1)
            ex = {p_["net"] for p_ in G["pads"] if x0 <= p_["x"] <= x1 and y0 <= p_["y"] <= y1}
            KO_BOXES.append({"mask": np.array(img_, bool), "exempt": ex, "layers": kb.get("layers")})
        print(f"keep-out boxes: {len(KO_BOXES)}", flush=True)
    # keep-outs
    # rule-area keep-outs: track keep-outs PER LAYER (e.g. MH_KO_TOP is F.Cu only); a through via is blocked by a
    # via keep-out on any layer (it exists on all of them)
    img_tL = {L: Image.new("L", (W, H), 0) for L in RL}
    img_v = Image.new("L", (W, H), 0)
    for z in G["zones"]:
        if not z["rule_area"]:
            continue
        poly = unary_union([cugraph.ring_poly(o) for o in z["outline"]])
        if z.get("no_tracks"):
            for L in z.get("layers", RL):
                if L in img_tL:
                    draw_geom(img_tL[L], grid, poly, 1)
        if z.get("no_vias"):
            draw_geom(img_v, grid, poly, 1)
    if MDI_CORRIDOR:                             # DIN-8R only (SBC-1: None)
        mdi = sbox(*MDI_CORRIDOR)
        for L in RL:
            draw_geom(img_tL[L], grid, mdi, 1)
        draw_geom(img_v, grid, mdi, 1)
    tblockL = {L: np.array(img_tL[L], bool) for L in RL}
    tblock = np.logical_or.reduce([tblockL[L] for L in RL])
    vblock = np.array(img_v, bool)
    # pickup-rule areas (ISLAND_HIZ nets only): per-layer track masks, the inner via mask, the outer via masks
    HIZ = hiz_ids(G, nets)
    hiz_img_t = {L: Image.new("L", (W, H), 0) for L in RL}
    hiz_img_vi = Image.new("L", (W, H), 0)
    hiz_img_vo = {L: Image.new("L", (W, H), 0) for L in OUTER}
    hiz_img_vk = Image.new("L", (W, H), 0)
    n_hiz_areas = 0
    for z in G["zones"]:
        if not z["rule_area"] or z.get("name") not in HIZ_AREAS:
            continue
        n_hiz_areas += 1
        poly = unary_union([cugraph.ring_poly(o) for o in z["outline"]])
        if HIZ_AREAS[z["name"]] == "via":          # HIZ_VIA_KO: vias only (the HIZ pads are cut out of it)
            draw_geom(hiz_img_vk, grid, poly, 1)
            continue
        for L in z.get("layers", []):
            if L in hiz_img_t:
                draw_geom(hiz_img_t[L], grid, poly, 1)
        if HIZ_AREAS[z["name"]] is None:
            draw_geom(hiz_img_vi, grid, poly, 1)
        else:
            draw_geom(hiz_img_vo[HIZ_AREAS[z["name"]]], grid, poly, 1)
    d_hiz_t = {L: (EDT(~np.array(hiz_img_t[L], bool)) * res - 0.036).astype(np.float32)
               for L in RL} if n_hiz_areas else {}
    d_hiz_vi = (EDT(~np.array(hiz_img_vi, bool)) * res - 0.036).astype(np.float32) \
        if n_hiz_areas else None
    d_hiz_vo = {L: (EDT(~np.array(hiz_img_vo[L], bool)) * res - 0.036).astype(np.float32)
                for L in OUTER} if n_hiz_areas else {}
    d_hiz_vk = (EDT(~np.array(hiz_img_vk, bool)) * res - 0.036).astype(np.float32) \
        if n_hiz_areas else None
    if HIZ:
        print(f"pickup rules: {len(HIZ)} ISLAND_HIZ nets, {n_hiz_areas} HIZ areas", flush=True)
    # keep-outs bind the whole copper shape, not just its centre: distance to the nearest keep-out cell
    d_tblock = {L: (EDT(~tblockL[L]) * res - 0.036).astype(np.float32) for L in RL}
    d_vblock = (EDT(~vblock) * res - 0.036).astype(np.float32)
    img_b = Image.new("L", (W, H), 0)
    draw_geom(img_b, grid, ob, 1)
    inside = np.array(img_b, bool)
    d_edge = (EDT(np.pad(inside, 1))[1:-1, 1:-1] * res - 0.036).astype(np.float32)
    img_d = Image.new("L", (W, H), 0)
    npth = Image.new("L", (W, H), 0)
    for v in G["vias"]:
        draw_geom(img_d, grid, Point(v["x"], v["y"]).buffer(v["drill"] / 2), 1)
    for p in G["pads"]:
        if p["drill"]:
            r = max(p["drill"]) / 2
            draw_geom(img_d, grid, Point(p["x"], p["y"]).buffer(r), 1)
            if not p["shapes"]:
                draw_geom(npth, grid, Point(p["x"], p["y"]).buffer(r), 1)
    d_drill = (EDT(~np.array(img_d, bool)) * res).astype(np.float32)
    d_npth = (EDT(~np.array(npth, bool)) * res).astype(np.float32)
    hole_block = np.zeros((H, W), bool)          # hole-to-hole discs of NEW vias (hard for every later via)
    # SI nets: per reference net (GND / GND_ISO) the routing-layer stack of reference-plane voids >= PLANE_SLOT_MM
    void_stack = {}
    if a.si_void_pen > 0:
        for rn in ("GND", "GND_ISO"):
            r_id = name2id.get(rn)
            if r_id is None:
                continue
            per = {}
            for PL in PLANE_FILL_LAYERS:
                fl = plane_by.get((r_id, PL))
                if fl is None:
                    continue
                vd_ = inside & ~fl
                labv, nv_ = ndimage.label(vd_)
                big = np.zeros(nv_ + 1, bool)
                for k_, sl_ in enumerate(ndimage.find_objects(labv), 1):
                    if sl_ is not None and max(sl_[0].stop - sl_[0].start, sl_[1].stop - sl_[1].start) * res >= PLANE_SLOT_MM:
                        big[k_] = True
                per[PL] = big[labv]
            if per:
                void_stack[r_id] = np.stack([per.get(REF_PLANE[L], np.zeros((H, W), bool)) for L in RL])
    print(f"rasters ready {time.time() - t0:.1f}s", flush=True)
    phase("rasters", t0)
    # ---------------- pfr2-up: own SMD pads per (net, outer layer) (via policy, pad-centre anchors)
    fp_pads = defaultdict(list)
    pads_by_net = defaultdict(list)
    for q in G["pads"]:
        fp_pads[q["ref"]].append(q)
        pads_by_net[q["net"]].append(q)
    small2t = set()                              # qa_layout_quality small2t: 2 pads, both SMD, span <= 2.6 mm
    for ref, ps in fp_pads.items():
        if len(ps) == 2 and all(not q["drill"] and q["shapes"] for q in ps):
            try:
                mr = unary_union([cugraph.ring_poly(r) for q in ps for rr in q["shapes"].values() for r in rr]) \
                    .minimum_rotated_rectangle
                xs_ = list(mr.exterior.coords)
                if max(math.dist(xs_[0], xs_[1]), math.dist(xs_[1], xs_[2])) <= SMALL_2T_SPAN:
                    small2t |= {q["uuid"] for q in ps}
            except Exception:
                pass
    smd_own = defaultdict(list)                  # (net id, outer layer) -> [(polygon, x, y, small 2-terminal)]
    no_vip = no_vip_refs(G)                      # owner 2026-10-05: "absolutely no vias in 0402s" (by footprint name)
    no_vip_poly = set()                          # id() of those parts' smd_own polygons
    for q in G["pads"]:
        if q["drill"] or not q["net"]:
            continue
        for L, rr in q["shapes"].items():
            if L in OUTER and rr:
                smd_own[(q["net"], L)].append((unary_union([cugraph.ring_poly(r) for r in rr]), q["x"], q["y"],
                                               q["uuid"] in small2t))
                if q["ref"] in no_vip:
                    no_vip_poly.add(id(smd_own[(q["net"], L)][-1][0]))
    # tidy step 2: PAD-AXIS pads per (net, outer layer) - qa_layout_quality.chk_pad_axis scope: a footprint with >= 4
    # SMD pads and pin pitch <= FINE_PITCH_MM (pitch over pads <= 2 x the median area, same layers), pad area <
    # EP_MIN_MM2, aspect >= PAD_AXIS_ASPECT -> (polygon, centre, unit long axis, half long, half short)
    axis_pads = defaultdict(list)
    for ref, ps in fp_pads.items():
        sp = [q for q in ps if not q["drill"] and q["shapes"] and q.get("num")]
        if len(sp) < 4:
            continue
        polys = {}
        for q in sp:
            polys[q["uuid"]] = {L: unary_union([cugraph.ring_poly(r) for r in rr]) for L, rr in q["shapes"].items() if rr}
        ar = {q["uuid"]: max((g.area for g in polys[q["uuid"]].values()), default=0.0) for q in sp}
        med = sorted(ar.values())[len(ar) // 2]
        sig = [q for q in sp if ar[q["uuid"]] <= 2.0 * med]
        ds = [math.dist((x_["x"], x_["y"]), (y_["x"], y_["y"])) for i_, x_ in enumerate(sig) for y_ in sig[i_ + 1:]
              if set(x_["shapes"]) == set(y_["shapes"])]
        if not ds or min(ds) > FINE_PITCH_MM + 1e-3:
            continue
        for q in sp:
            if not q["net"] or ar[q["uuid"]] >= EP_MIN_MM2:
                continue
            for L, g in polys[q["uuid"]].items():
                if L not in OUTER or g.is_empty:
                    continue
                mr = list(g.minimum_rotated_rectangle.exterior.coords)
                e1 = (mr[1][0] - mr[0][0], mr[1][1] - mr[0][1])
                e2 = (mr[2][0] - mr[1][0], mr[2][1] - mr[1][1])
                l1, l2 = math.hypot(*e1), math.hypot(*e2)
                if max(l1, l2) < PAD_AXIS_ASPECT * max(min(l1, l2), 1e-3):
                    continue
                u = (e1[0] / l1, e1[1] / l1) if l1 >= l2 else (e2[0] / l2, e2[1] / l2)
                c_ = g.centroid
                axis_pads[(q["net"], L)].append((g, (c_.x, c_.y), u, max(l1, l2) / 2, min(l1, l2) / 2))
    # ---------------- per-net parameters
    netcls = {}
    for n in todo:
        cls = nets[n]["class"]
        p = net_params(nets[n]["name"], cls, nets[n].get("track"))
        vd, vdr = (0.45, 0.20) if nets[n]["name"] in SMALL_VIA_NETS else (p[2], p[3])
        outer_only = p[5] or any(nets[n]["name"] == q or (q.endswith("*") and nets[n]["name"].startswith(q[:-1]))
                                 for q in filter(None, a.outer_nets.split(",")))
        # via policy: a SELV signal net whose pads can all be reached on one outer layer pays more per via
        lays = None
        for q in pads_by_net[n]:
            s_ = set(OUTER) if q["drill"] else set(q["shapes"]) & set(OUTER)
            lays = s_ if lays is None else lays & s_
        vfac = a.one_layer_via_fac if (a.via_policy and cls in ("SELV", "Default") and lays) else 1.0
        netcls[n] = {"cls": cls, "wo": p[0], "wi": p[1], "vd": vd, "vdr": vdr, "neck": p[4], "outer": outer_only,
                     "c": max(MIN_CLR, nets[n]["clearance"] or MIN_CLR), "current": p[6], "vfac": vfac}
    need_cache = {}
    si_ref = {}                                  # SI net id -> reference plane net id (ISLAND classes: GND_ISO)
    for n in todo:
        if SI_NET_RE.search(nets[n]["name"]):
            si_ref[n] = name2id.get("GND_ISO" if nets[n]["class"].startswith("ISLAND") else "GND")

    def need(n, f, L=None):
        if f == 31999:                           # no-net copper
            return max(MIN_CLR, nets[n]["clearance"] or MIN_CLR)
        k = (n, f)
        if k not in need_cache:
            need_cache[k] = place_gate.required(nets[n], nets[f], None, None, "trk", "trk")
        v = need_cache[k]
        if L is not None and L not in OUTER and nets[n]["class"] == "SELV" and nets[f]["class"] == "SELV"                 and v <= 0.2 + 1e-9:
            return INNER_SELV
        return v
    # PWR_NECK boxes (pcb_power.neck_areas): SMD pads of PWR_FAULT nets, bbox + 1.0, on the pad layer
    neck_boxes = []
    for p in G["pads"]:
        if nets[p["net"]]["name"] in PWR_FAULT_NETS and not p["drill"]:
            for L, rr in p["shapes"].items():
                if L in OUTER and rr:
                    b = unary_union([cugraph.ring_poly(r) for r in rr]).bounds
                    neck_boxes.append({"net": nets[p["net"]]["name"], "layer": L, "ref": p["ref"], "pad": p["num"],
                                       "box": [b[0] - NECK_REACH, b[1] - NECK_REACH, b[2] + NECK_REACH,
                                               b[3] + NECK_REACH]})
    plane_comp = {}
    for n in todo:
        if n in plane_fill:
            plane_comp[n] = [i for i, c in enumerate(todo[n])
                             if any(k[0] == "zone" and k[2] in PLANE_FILL_LAYERS for k in c)]
    # --f-lane: nets whose F.Cu copper stays within a.f_lane of their own F.Cu pads
    fl_pat = list(filter(None, a.f_lane_nets.split(",")))
    FL_NETS = {n for n in todo if (any(nets[n]["name"] == q or (q.endswith("*") and nets[n]["name"].startswith(q[:-1]))
                                       for q in fl_pat) if fl_pat else
                                   not (netcls[n]["cls"] in POWER_CLASSES or nets[n]["name"] in NET_OVERRIDE
                                        or n in plane_fill or nets[n]["name"] in SOFT_ZONES))} if a.f_lane > 0 else set()
    if FL_NETS:
        print(f"F-lane: {len(FL_NETS)} nets on F.Cu only within {a.f_lane} mm of own F pads", flush=True)

    def flane_dist(n, win):
        """distance (mm) from each window cell centre to the net's own F.Cu pad copper (pads up to f_lane outside)"""
        i0, j0, i1, j1 = win
        m = int(math.ceil(a.f_lane / res)) + 1
        sg = Grid(bx0 + (j0 - m) * res, by0 + (i0 - m) * res, bx0 + (j1 + m) * res, by0 + (i1 + m) * res, res)
        img = Image.new("L", (j1 - j0 + 2 * m, i1 - i0 + 2 * m), 0)
        for q in pads_by_net[n]:
            for r in q["shapes"].get("F.Cu", ()):
                draw_geom(img, sg, cugraph.ring_poly(r), 1)
        pm = np.array(img, bool)
        return (EDT(~pm) * res)[m:-m, m:-m] if pm.any() else np.full((i1 - i0, j1 - j0), 1e9)

    def bbox_of(items, pad):
        xs, ys = [], []
        for u in items:
            for g in cu.items[u]["geo"].values():
                b = g.bounds
                xs += [b[0], b[2]]; ys += [b[1], b[3]]
        x0, x1 = max(bx0, min(xs) - pad), min(bx1, max(xs) + pad)
        y0, y1 = max(by0, min(ys) - pad), min(by1, max(ys) + pad)
        return (int((y0 - by0) / res), int((x0 - bx0) / res), min(H, int((y1 - by0) / res) + 1),
                min(W, int((x1 - bx0) / res) + 1))

    def legality(n, win):
        """trace-ok per routing layer, via-ok, per-layer slack (float32), own-pad proximity, plane via sites."""
        kb_block = []
        i0, j0, i1, j1 = win
        p = netcls[n]
        sh = (i1 - i0, j1 - j0)
        slack = {}
        soft_pk = nets[n]["class"] in POCKET_SOFT_FOR
        for L in ALL_LAYERS:
            sub = lab[L][i0:i1, j0:j1]
            if reserved:
                rs = rsv_lab[L][i0:i1, j0:j1]
                rs_other = (rs != 0) & (rs != n + 1) & (sub == 0)
                if rs_other.any():
                    sub = np.where(rs_other, rs, sub)
            if not soft_pk:
                pk = pocket[L][i0:i1, j0:j1]
                if pk.any():
                    sub = np.where(pk != 0, pk, sub)
            fl = np.unique(sub)
            fl = fl[(fl != 0) & (fl != n + 1)]
            groups = defaultdict(list)
            for f in fl:
                groups[need(n, int(f) - 1, L)].append(int(f))
            s = np.full(sh, 99.0, np.float32)
            for nd, labs in groups.items():
                mk = np.isin(sub, labs)
                s = np.minimum(s, (EDT(~mk) * res - nd).astype(np.float32))
            slack[L] = s
        ed, dd, dn = d_edge[i0:i1, j0:j1], d_drill[i0:i1, j0:j1], d_npth[i0:i1, j0:j1]
        vok = (d_vblock[i0:i1, j0:j1] >= p["vd"] / 2 + margin) & (ed >= 0.4 + p["vd"] / 2 + margin) & \
              (dd >= p["vdr"] / 2 + HOLE_TO_HOLE + margin) & (dn >= 0.25 + p["vd"] / 2 + margin)
        inpad, inpad_hiz = {}, []
        for L in OUTER:
            # via-in-pad: a via wholly inside the net's own copper on an outer layer adds no outer copper there
            # (filled + capped, JLC POFV): only the inner layers' clearance applies at that spot
            own_L = lab[L][i0:i1, j0:j1] == n + 1
            if own_L.any():
                dt = EDT(own_L) * res
                # pfr2-up: the VIA-INPAD fit margin (0.05, + half a cell of raster error) instead of 0.02
                inpad[L] = dt >= p["vd"] / 2 + ((VIP_MARGIN + res / 2) if a.via_policy else 0.02)
                inpad_hiz.append(dt >= p["vd"] / 2 + 0.02 + res)     # + one cell: exact containment (plan_check)
        inpad_any = np.logical_or.reduce(inpad_hiz) if inpad_hiz else None
        for L in ALL_LAYERS:
            ok_L = slack[L] >= p["vd"] / 2 + margin
            if L in inpad:
                ok_L |= inpad[L]
            if n in HIZ and L in d_hiz_vo:                 # pickup rule: near HV only as a (through) via-in-pad
                hz = d_hiz_vo[L][i0:i1, j0:j1] >= p["vd"] / 2 + margin
                ok_L &= (hz | inpad_any) if inpad_any is not None else hz
            vok &= ok_L
        if n in HIZ and d_hiz_vi is not None:
            vok &= d_hiz_vi[i0:i1, j0:j1] >= p["vd"] / 2 + margin
        if n in HIZ and d_hiz_vk is not None:          # HIZ_VIA_KO: no exception beyond the area's own pad cut-outs
            vok &= d_hiz_vk[i0:i1, j0:j1] >= p["vd"] / 2 + margin
        for kb in KO_BOXES:                            # --keepout: reserved space (nets with a pad inside exempt)
            if n in kb["exempt"]:
                continue
            m_ = kb["mask"][i0:i1, j0:j1]
            if m_.any():
                vok &= ~m_
                kb_block.append((m_, kb["layers"]))
        fd = flane_dist(n, win) if n in FL_NETS else None
        if fd is not None:                             # --f-lane: a through via has F.Cu copper too
            vok &= fd <= a.f_lane - p["vd"] / 2
        tok =np.zeros((len(RL),) + sh, bool)
        nominal = np.zeros((len(RL),) + sh, bool)
        nm = nets[n]["name"]
        for li, L in enumerate(RL):
            tb = tblockL[L][i0:i1, j0:j1]
            if p["outer"] and L not in OUTER:
                continue
            w = p["wo"] if L in OUTER else p["wi"]
            base = (d_tblock[L][i0:i1, j0:j1] >= w / 2 + margin) & (ed >= 0.4 + w / 2 + margin) & (dn >= 0.25 + w / 2 + margin)
            for m_, kls in kb_block:
                if kls is None or L in kls:
                    base &= ~m_
            if n in HIZ and L in d_hiz_t:                  # pickup rule areas bind ISLAND_HIZ tracks
                base &= d_hiz_t[L][i0:i1, j0:j1] >= w / 2 + margin
            ok = base & (slack[L] >= w / 2 + margin)
            nominal[li] = ok
            if p["neck"]:
                if nm in PWR_FAULT_NETS:
                    zimg = Image.new("L", (sh[1], sh[0]), 0)
                    sg = Grid(bx0 + j0 * res, by0 + i0 * res, bx0 + j1 * res, by0 + i1 * res, res)
                    sk = p["neck"] / 2 + 0.1
                    for nb in neck_boxes:
                        if nb["net"] == nm and nb["layer"] == L:
                            x0, y0, x1, y1 = nb["box"]
                            draw_geom(zimg, sg, sbox(x0 + sk, y0 + sk, x1 - sk, y1 - sk), 1)
                    zone = ndimage.binary_erosion(np.array(zimg, bool), iterations=1)
                else:
                    own_pad = np.zeros(sh, bool)
                    pimg = Image.new("L", (sh[1], sh[0]), 0)
                    sg = Grid(bx0 + j0 * res, by0 + i0 * res, bx0 + j1 * res, by0 + i1 * res, res)
                    for q in G["pads"]:
                        if q["net"] == n and L in q["shapes"]:
                            for r in q["shapes"][L]:
                                g = cugraph.ring_poly(r)
                                if not p["current"] or narrow_pad(g, w):       # necks only into narrower pads
                                    draw_geom(pimg, sg, g, 1)
                    own_pad = np.array(pimg, bool)
                    zone = EDT(~own_pad) * res <= 0.9 if own_pad.any() else own_pad
                ok |= base & zone & (slack[L] >= p["neck"] / 2 + margin)
            if fd is not None and L == "F.Cu":         # --f-lane: F copper only as stubs at the own F pads
                ok &= fd <= a.f_lane - w / 2
            own = lab[L][i0:i1, j0:j1] == n + 1
            ok |= own & ~tb
            tok[li] = ok
        pv = None
        if n in plane_fill:
            er = ndimage.binary_erosion(plane_fill[n][i0:i1, j0:j1], iterations=max(1, int(round(0.1 / res))))
            pv = er & vok
        # pfr2-up via policy: extra via cost at sites that would fail VIA-INPAD (not fitting the own SMD pad, or in a
        # <= 0603 two-terminal pad) or VIA-PADEDGE / VIA-PADGAP (centre outside, disc < 0.10 mm from the pad edge)
        vpen = None
        # via-edge (owner 2026-10-05: pad-edge / half-in-pad vias are defects): a HARD legality constraint (always):
        # a via disc sits wholly inside its own SMD pad with >= VIP_MARGIN to spare (both boards fill + cap their vias:
        # a fitting via-in-pad is legal and uncosted, except in an 0402's pads: none there) or >= PADEDGE_GAP
        # (= qa_copper_landing.PADEDGE_GAP_MM) from it; foreign pads: DRU clearance >= 0.15. EXACT at the cell
        # centres (a plan via sits on its cell centre, grid.mm): the same geometry as tools/via_site.py (the gate's
        # padedge_class), which land_stubs.py re-checks. --via-policy adds VIA_PEN on the illegal sites (moot: hard).
        vr = p["vd"] / 2
        wx0, wy0 = bx0 + j0 * res, by0 + i0 * res
        wb = sbox(wx0, wy0, bx0 + j1 * res, by0 + i1 * res)
        ext = vr + PADEDGE_GAP + 2 * res
        for L in OUTER:
            for poly, _, _, _ in smd_own.get((n, L), ()):
                b_ = poly.bounds
                ci0, cj0 = max(0, int((b_[1] - ext - wy0) / res)), max(0, int((b_[0] - ext - wx0) / res))
                ci1, cj1 = min(sh[0], int((b_[3] + ext - wy0) / res) + 1), min(sh[1], int((b_[2] + ext - wx0) / res) + 1)
                if ci1 <= ci0 or cj1 <= cj0:
                    continue                           # the pad's reach is outside this window
                ys_, xs_ = np.mgrid[ci0:ci1, cj0:cj1]
                X_, Y_ = wx0 + (xs_ + 0.5) * res, wy0 + (ys_ + 0.5) * res
                inside = shapely.contains_xy(poly, X_, Y_)
                dist = shapely.distance(poly, shapely.points(X_, Y_))
                fit = poly.buffer(-(vr + VIP_MARGIN) - 1e-4)
                bad = ~inside & (dist < vr + PADEDGE_GAP + 1e-4)
                if fit.is_empty or id(poly) in no_vip_poly:
                    bad |= inside                      # no via of this size fits the land, or an 0402 land
                else:
                    bad |= inside & ~shapely.contains_xy(fit, X_, Y_)
                if not bad.any():
                    continue
                vok[ci0:ci1, cj0:cj1][bad] = False
                if pv is not None:
                    pv[ci0:ci1, cj0:cj1][bad] = False
                if a.via_policy:
                    if vpen is None:
                        vpen = np.zeros(sh, np.float32)
                    vpen[ci0:ci1, cj0:cj1][bad] = VIA_PEN
        axpen = None
        if a.axis_pen > 0:
            wx0, wy0 = bx0 + j0 * res, by0 + i0 * res
            wb = sbox(wx0, wy0, bx0 + j1 * res, by0 + i1 * res)
            sg = Grid(wx0, wy0, bx0 + j1 * res, by0 + i1 * res, res)
            for li, L in enumerate(RL):
                lst = [x for x in axis_pads.get((n, L), []) if x[0].intersects(wb)]
                if not lst:
                    continue
                img_b = Image.new("L", (sh[1], sh[0]), 0)
                for g_, (cx_, cy_), u, hl, hs in lst:
                    v = (-u[1], u[0])

                    def rect(a_, b_):
                        return shapely.geometry.Polygon([(cx_ + u[0] * sa * a_ + v[0] * sb * b_,
                                                          cy_ + u[1] * sa * a_ + v[1] * sb * b_)
                                                         for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
                    band = rect(hl + AXIS_EXIT_MM, hs + AXIS_BAND_MM).difference(rect(hl + AXIS_EXIT_MM + 0.01, hs))
                    draw_geom(img_b, sg, band, 1)
                m_ = np.array(img_b, bool) & (lab[L][i0:i1, j0:j1] != n + 1)
                if m_.any():
                    if axpen is None:
                        axpen = np.zeros((len(RL),) + sh, np.float32)
                    axpen[li][m_] = np.float32(a.axis_pen)
        return {"tok": tok, "vok": vok, "slack": slack, "nominal": nominal, "pv": pv, "vpen": vpen, "axpen": axpen}

    def comp_mask(comp, win):
        i0, j0, i1, j1 = win
        m = np.zeros((len(RL), i1 - i0, j1 - j0), bool)
        sg = Grid(bx0 + j0 * res, by0 + i0 * res, bx0 + j1 * res, by0 + i1 * res, res)
        for li, L in enumerate(RL):
            img = Image.new("L", (j1 - j0, i1 - i0), 0)
            # pfr2-speed DETERMINISM: zone fills first, then pads / tracks / vias, each in sorted key order. draw_geom
            # paints a polygon's holes 0, so a zone drawn AFTER a pad sitting in its thermal-relief hole erased that
            # pad from the mask; iterating the set made that depend on PYTHONHASHSEED (run-to-run noise)
            for u in (comp if LEGACY_COMP else sorted(comp, key=lambda k_: (cu.items[k_]["kind"] != "zone", k_))):
                if L in cu.items[u]["geo"] and cu.items[u]["kind"] != "zone":
                    draw_geom(img, sg, cu.items[u]["geo"][L], 1)
                elif L in cu.items[u]["geo"] and cu.items[u]["kind"] == "zone" and L in OUTER:
                    draw_geom(img, sg, cu.items[u]["geo"][L], 1)
            m[li] = np.array(img, bool)
        return m

    # ---------------- dynamic state for negotiated (signal) routing
    sig_nets = [n for n in todo if not (netcls[n]["cls"] in POWER_CLASSES or nets[n]["name"] in NET_OVERRIDE
                                        or n in plane_fill)]
    partner_vr = max([netcls[n]["vd"] / 2 for n in sig_nets] + [0.225])
    occ_t = np.zeros((len(RL), H, W), np.int16)
    occ_v = np.zeros((len(RL), H, W), np.int16)
    hist = np.zeros((len(RL), H, W), np.float32)
    hist_v = np.zeros((H, W), np.float32)          # history cost of via sites
    routed = {}
    out_tracks, out_vias = defaultdict(list), defaultdict(list)

    def halo_offsets(n):
        """per routing layer: tt / tv for this net's track cells, vt for its via cells; vv layer-independent.
        Partners are the negotiated signal nets (SELV: outer w 0.2 / c 0.2, inner w INNER_SELV / c INNER_SELV)."""
        p = netcls[n]
        selv = nets[n]["class"] == "SELV"
        out = {"vv": disk((p["vd"] / 2 + p["c"] + partner_vr + margin) / res)}
        for li, L in enumerate(RL):
            inner = L not in OUTER
            c = INNER_SELV if (inner and selv) else p["c"]
            w = p["wi"] if inner else p["wo"]
            wn = min(w, p["neck"]) if p["neck"] else w        # where the track necks (near own pads / PWR_NECK)
            pw = INNER_SELV / 2 if inner else 0.1
            out[li] = {"tt": disk((w / 2 + c + pw + margin) / res), "tv": disk((w / 2 + c + partner_vr + margin) / res),
                       "vt": disk((p["vd"] / 2 + c + pw + margin) / res),
                       "ttn": disk((wn / 2 + c + pw + margin) / res),
                       "tvn": disk((wn / 2 + c + partner_vr + margin) / res)}
        return out

    def apply_stamps(n, sgn):
        ho = routed[n]["halo"]
        for (li, ys, xs, kind) in routed[n]["cells"]:
            if kind == "t":
                stamp(occ_t[li], ys, xs, ho[li]["tt"][0], ho[li]["tt"][1], sgn)
                stamp(occ_v[li], ys, xs, ho[li]["tv"][0], ho[li]["tv"][1], sgn)
            elif kind == "n":                    # necked cells: the emitted width there is the neck width
                stamp(occ_t[li], ys, xs, ho[li]["ttn"][0], ho[li]["ttn"][1], sgn)
                stamp(occ_v[li], ys, xs, ho[li]["tvn"][0], ho[li]["tvn"][1], sgn)
            else:
                for lj in range(len(RL)):
                    stamp(occ_t[lj], ys, xs, ho[lj]["vt"][0], ho[lj]["vt"][1], sgn)
                    stamp(occ_v[lj], ys, xs, ho["vv"][0], ho["vv"][1], sgn)

    # ---------------- A* wrapper on a window
    hard_state = {"on": False}

    def tidy_path(n, L_, win, ls, yy, xx, drop, src=None):
        """pfr2-up: octilinear pull-tight of every same-layer run (pfr_tidy.tidy_run) inside the cells this net may
        use right now: nominal-width legal (or own copper), not vetoed, outside every other unit's negotiated halo, or
        on the original path, never along this unit's own new copper (src minus existing copper: no TRACK-DUP). A run
        that starts / ends inside an own SMD pad is anchored at the pad CENTRE (emit() then starts the track at the exact
        centre) and leaves / enters it with a straight leg along the pad's long axis that clears the pad (PAD-AXIS)."""
        i0, j0, i1, j1 = win
        Hn, Wn = i1 - i0, j1 - j0

        def centre(li, y, x):
            L = RL[li]
            if L not in OUTER:
                return None
            xm, ym = grid.mm(x + j0, y + i0)
            pt = Point(xm, ym)
            for poly, px_, py_, _ in smd_own.get((n, L), ()):
                if poly.distance(pt) <= 0.75 * res:      # PIL masks include half-cell edge cells
                    cy = int(round((py_ - by0) / res - 0.5)) - i0
                    cx = int(round((px_ - bx0) / res - 0.5)) - j0
                    if 0 <= cy < Hn and 0 <= cx < Wn and (cy, cx) != (y, x) and L_["tok"][li][cy, cx]:
                        b_ = poly.bounds
                        pw, ph = b_[2] - b_[0], b_[3] - b_[1]
                        ex = int(math.ceil(pw / 2 / res)) + 2
                        ey = int(math.ceil(ph / 2 / res)) + 2
                        if pw >= PAD_AXIS_ASPECT * ph:
                            ey = -1
                        elif ph >= PAD_AXIS_ASPECT * pw:
                            ex = -1
                        return cy, cx, ex, ey
                    return None
            return None
        okc = {}

        def okmask(li):
            if li not in okc:
                L = RL[li]
                own = lab[L][i0:i1, j0:j1] == n + 1
                okc[li] = L_["tok"][li] & (L_["nominal"][li] | own) & ((occ_t[li, i0:i1, j0:j1] == 0) | own)
                if src is not None:
                    okc[li] &= ~(src[li] & ~own)
            return okc[li]

        def exit_pt(li, c, ty, tx):
            """elongated pad: the waypoint ex / ey cells from the centre along its long axis, on the side of (ty, tx)"""
            cy, cx, ex, ey = c
            if (ex < 0) == (ey < 0):
                return None                     # square-ish pad: either axis (tidy_run constrains the first leg)
            dy, dx = (0, 1) if ey < 0 else (1, 0)
            d_ = (tx - cx) if dx else (ty - cy)
            sg = 1 if d_ >= 0 else -1
            nn = ex if dx else ey
            om = okmask(li)
            for q in range(1, nn + 1):
                yq, xq = cy + sg * dy * q, cx + sg * dx * q
                if not (0 <= yq < Hn and 0 <= xq < Wn) or not (om[yq, xq] or (lab[RL[li]][yq + i0, xq + j0] == n + 1)):
                    return None
            return cy + sg * dy * nn, cx + sg * dx * nn
        def exit_ref(ls, yy, xx, c, step):
            """the path index that decides the exit side: tidy step 2 - the first cell of the run beyond the pad's
            own copper (where the A* really left it: no turn-back over the pad); a run that never leaves within
            40 cells uses the cell 40 on (~2 mm, the former rule)"""
            k0 = 0 if step > 0 else len(ls) - 1
            L0 = ls[k0]
            r_ = k0
            for q in range(1, 41):
                k = k0 + step * q
                if not (0 <= k < len(ls)) or ls[k] != L0:
                    break
                r_ = k
                cy, cx = c[0], c[1]
                if lab[RL[L0]][yy[k] + i0, xx[k] + j0] != n + 1 and max(abs(yy[k] - cy), abs(xx[k] - cx)) > 1:
                    return k
            return r_
        ls, yy, xx = list(ls), list(yy), list(xx)
        c0 = centre(ls[0], yy[0], xx[0])
        if c0:
            r_ = exit_ref(ls, yy, xx, c0, 1)
            e_ = exit_pt(ls[0], c0, yy[r_], xx[r_])
            ls.insert(0, ls[0]); yy.insert(0, c0[0]); xx.insert(0, c0[1])
            if e_ is not None and len(ls) > 2 and ls[1] == ls[0]:
                ls.insert(1, ls[0]); yy.insert(1, e_[0]); xx.insert(1, e_[1])
        c1 = None
        if not drop:
            c1 = centre(ls[-1], yy[-1], xx[-1])
            if c1:
                r_ = exit_ref(ls, yy, xx, c1, -1)
                e_ = exit_pt(ls[-1], c1, yy[r_], xx[r_])
                if e_ is not None and len(ls) > 2:
                    ls.append(ls[-1]); yy.append(e_[0]); xx.append(e_[1])
                ls.append(ls[-1]); yy.append(c1[0]); xx.append(c1[1])
        ls_a = np.array(ls, np.int64)
        yy_a = np.array(yy, np.int64)
        xx_a = np.array(xx, np.int64)
        out_l, out_y, out_x = [], [], []
        k, m = 0, len(ls_a)
        while k < m:
            k2 = k
            while k2 + 1 < m and ls_a[k2 + 1] == ls_a[k]:
                k2 += 1
            li = int(ls_a[k])
            ys_, xs_ = yy_a[k:k2 + 1], xx_a[k:k2 + 1]
            if k2 - k >= 2:
                okm = okmask(li).copy()
                okm[ys_, xs_] = True
                w = netcls[n]["wo"] if RL[li] in OUTER else netcls[n]["wi"]
                e0 = (c0[2], c0[3]) if (c0 and k == 0) else (0, 0)
                e1 = (c1[2], c1[3]) if (c1 and k2 == m - 1) else (0, 0)
                ys_, xs_, j0_, j1_ = tidy_run(ys_, xs_, okm, TIDY_JMAX, JOG_W * w / res, e0[0], e0[1], e1[0], e1[1])
                tidy_stat["runs"] += 1
                tidy_stat["jogs_raw"] += j0_
                tidy_stat["jogs"] += j1_
            out_l.append(np.full(len(ys_), li, np.int64))
            out_y.append(np.asarray(ys_, np.int64))
            out_x.append(np.asarray(xs_, np.int64))
            k = k2 + 1
        return np.concatenate(out_l), np.concatenate(out_y), np.concatenate(out_x)

    tidy_stat = collections.Counter()

    def astar_prep(n, L_, win, ct=None, cv=None):
        """the A* inputs that do not change between the joins of one route_unit call: trace / via legality (hard
        occupancy included when on), cost arrays (via policy + SI void pen applied), contiguous"""
        i0, j0, i1, j1 = win
        t_ok = L_["tok"]
        v_ok = L_["vok"] & ~hole_block[i0:i1, j0:j1]
        if hard_state["on"]:
            own = np.stack([lab[L][i0:i1, j0:j1] == n + 1 for L in RL])
            t_ok = t_ok & ((occ_t[:, i0:i1, j0:j1] == 0) | own)
            v_ok = v_ok & (occ_v[:, i0:i1, j0:j1].sum(axis=0) == 0)
        t_ok = np.ascontiguousarray(t_ok)
        v_ok = np.ascontiguousarray(v_ok)
        if ct is None:
            ct = np.ones(t_ok.shape, np.float32)
            cv = np.ones(v_ok.shape, np.float32)
        if L_.get("vpen") is not None:              # pfr2-up via policy: VIA-INPAD / VIA-PADEDGE sites cost more
            cv = cv + L_["vpen"]
        rf_ = si_ref.get(n)
        if rf_ is not None and rf_ in void_stack:   # pfr2-up: SI nets stay over solid reference plane (PLANE-SLOT)
            ct = ct + np.float32(a.si_void_pen) * void_stack[rf_][:, i0:i1, j0:j1]
        if L_.get("axpen") is not None:             # tidy step 2: axis exits at the source (PAD-AXIS)
            ct = ct + L_["axpen"]
        return t_ok, v_ok, np.ascontiguousarray(ct), np.ascontiguousarray(cv)

    ws_local = threading.local()
    astat = collections.Counter()                # A* calls / expansions (failures, --max-expand cut-offs)

    def workspace(N):
        """per-thread A* work buffers (pfr_core.astar_ws), grown to the largest window seen"""
        w_ = getattr(ws_local, "w", None)
        if w_ is None or w_[0] < N:
            M = max(N, w_[0] if w_ else 0)
            w_ = (M, np.full(M, np.float32(1e30), np.float32), np.full(M, -1, np.int64), np.zeros(M, np.bool_),
                  np.empty(min(M, 1 << 25), np.float32), np.empty(min(M, 1 << 25), np.int64), np.empty(M, np.int64))
            ws_local.w = w_
        return w_

    # pfr2-speed --c2f COARSE-TO-FINE: the A* first runs on a 0.1 mm grid (2 x 2 fine cells: trace / via legal if
    # ANY fine cell is - optimistic, so a fine path always has a coarse image; cost = the cheapest legal fine cell, x 2
    # per coarse step), then the 0.05 mm A* runs only inside a corridor around the coarse path (--c2f-mm each side, all
    # layers) and, near the pins, inside --c2f-pin-mm of every source / target cell (full fine freedom for the
    # escapes). A corridor search that fails falls back to the full fine search; an exhausted coarse search is a
    # certain failure (no fine path either), a coarse search cut at --max-expand falls back too.
    c2f_cache = {}

    def c2f_coarse(prep):
        k_ = id(prep[0])
        hit_ = c2f_cache.get(k_)
        if hit_ is not None and hit_[0] is prep[0] and hit_[1] is prep[2]:
            return hit_[2]
        t_ok, v_ok, ct_, cv_ = prep
        NL, H, W = t_ok.shape
        out_ = coarsen_prep(t_ok, v_ok, ct_, cv_, (H + 1) // 2, (W + 1) // 2)
        if len(c2f_cache) > 8:
            c2f_cache.clear()
        c2f_cache[k_] = (prep[0], prep[2], out_)
        return out_

    def c2f_search(n, t_ok, v_ok, ct_, cv_, src, tgt, lay, tbox, prep, cs=None):
        """-> (path or None, expansions), or None = not decided (the caller runs the full fine search).
        cs: the caller's coarse (source, target) masks when it maintains them incrementally (route_unit)"""
        NL, H, W = t_ok.shape
        if H < 8 or W < 8:
            return None
        t_c, v_c, c_c, cv_c = c2f_coarse(prep)
        Hc, Wc = t_c.shape[1], t_c.shape[2]
        if cs is not None:
            s_c, g_c = cs
        else:
            s_c, g_c = down_any(np.ascontiguousarray(src), Hc, Wc), down_any(np.ascontiguousarray(tgt), Hc, Wc)
        tb_c = np.array([tbox[0] // 2, tbox[1] // 2, tbox[2] // 2, tbox[3] // 2], dtype=np.int64)
        vc_ = np.float32(a.via_cost * netcls[n].get("vfac", 1.0))
        w_ = workspace(max(t_ok.size, t_c.size))
        hmap = octile_dt(g_c.any(axis=0))       # octile distance (coarse cells) to the nearest target
        pc, ec = astar_ws(t_c, v_c, c_c, cv_c, s_c, g_c, lay, vc_, tb_c, a.max_expand, *w_[1:],
                          np.float32(a.c2f_hw), hmap, True)
        astat["c_calls"] += 1
        astat["c_exp"] += int(ec)
        if DEBUG_EXP and ec > DEBUG_EXP:
            print(f"  c2f big: {nets[n]['name']} win {H}x{W} coarse exp {ec} src {int(s_c.sum())} tgt {int(g_c.sum())} "
                  f"tbox {tb_c.tolist()} path {pc.size}", flush=True)
        if pc.size == 0:
            if ec > a.max_expand:
                astat["c_cap"] += 1
                return None
            astat["c_fail"] += 1
            return None, ec                      # exhausted: no fine path either
        r_ = pc % (Hc * Wc)
        cy, cx = (r_ // Wc).astype(np.int64), (r_ % Wc).astype(np.int64)
        rc = max(1, int(round(a.c2f_mm / (2 * res))))
        rp = int(round(a.c2f_pin_mm / res))
        ends_y = np.array([2 * cy[0], 2 * cy[-1]], np.int64)
        ends_x = np.array([2 * cx[0], 2 * cx[-1]], np.int64)
        # the fine search runs on the corridor's bounding sub-window only (O(corridor), not O(window), per call)
        fy0 = max(0, min(2 * (int(cy.min()) - rc), int(ends_y.min()) - rp))
        fy1 = min(H, max(2 * (int(cy.max()) + rc) + 2, int(ends_y.max()) + rp + 1))
        fx0 = max(0, min(2 * (int(cx.min()) - rc), int(ends_x.min()) - rp))
        fx1 = min(W, max(2 * (int(cx.max()) + rc) + 2, int(ends_x.max()) + rp + 1))
        Hs, Ws = fy1 - fy0, fx1 - fx0
        corr = corridor_sub(cy, cx, Hs, Ws, fy0, fx0, rc, ends_y, ends_x, rp)
        t_f = mask_layers(t_ok[:, fy0:fy1, fx0:fx1], corr)
        v_f = np.ascontiguousarray(v_ok[fy0:fy1, fx0:fx1] & corr)
        s_f = mask_layers(src[:, fy0:fy1, fx0:fx1], corr)
        if not s_f.any():
            return None
        tg_s = np.ascontiguousarray(tgt[:, fy0:fy1, fx0:fx1])
        hf = octile_dt(np.ascontiguousarray(tg_s.any(axis=0)))     # fine: octile distance to the nearest target
        hf[hf > np.float32(1e29)] = 0.0
        tb_s = np.array([0, 0, Hs - 1, Ws - 1], dtype=np.int64)
        pf, ef = astar_ws(t_f, v_f, np.ascontiguousarray(ct_[:, fy0:fy1, fx0:fx1]),
                          np.ascontiguousarray(cv_[fy0:fy1, fx0:fx1]), s_f, tg_s, lay, vc_, tb_s, a.max_expand,
                          *w_[1:], np.float32(1.0), hf, True)
        if pf.size:
            l_ = pf // (Hs * Ws)
            r2 = pf % (Hs * Ws)
            pf = (l_ * H + (r2 // Ws + fy0)) * W + (r2 % Ws + fx0)
        astat["f_calls"] += 1
        astat["f_exp"] += int(ef)
        if pf.size == 0:
            astat["f_fallback"] += 1
            return None
        return pf, ec + ef

    def run_astar(n, L_, win, src, tgt, ct=None, cv=None, drop=False, prep=None, tbox=None, cs=None):
        """prep: astar_prep() of this call's state (route_unit computes it once per unit); tbox: the target cells'
        bounding box when the caller tracks it (else from tgt)"""
        i0, j0, i1, j1 = win
        p = netcls[n]
        lay = np.array([not (p["outer"] and L not in OUTER) for L in RL])
        if prep is None:
            prep = astar_prep(n, L_, win, ct, cv)
        t_ok, v_ok, ct_, cv_ = prep
        if tbox is None:
            ys, xs = np.nonzero(tgt.any(axis=0))
            if ys.size == 0:
                return None
            tbox = np.array([ys.min(), xs.min(), ys.max(), xs.max()], dtype=np.int64)
        if a.c2f and not OLD_ASTAR:
            r_c2f = c2f_search(n, t_ok, v_ok, ct_, cv_, src, tgt, lay, tbox, prep, cs)
            if r_c2f is not None:
                path, exp = r_c2f
                if path is None:
                    return None
                Wn, Hn = j1 - j0, i1 - i0
                ls = path // (Hn * Wn)
                r_ = path % (Hn * Wn)
                out = ls[::-1].copy(), (r_ // Wn)[::-1].copy(), (r_ % Wn)[::-1].copy()
                if a.tidy:
                    out = tidy_path(n, L_, win, *out, drop, src)
                return out
        if OLD_ASTAR:                                # verification switch: the former allocating astar()
            path, exp = astar(t_ok, v_ok, ct_, cv_, np.ascontiguousarray(src), np.ascontiguousarray(tgt), lay,
                              np.float32(a.via_cost * p.get("vfac", 1.0)), tbox, a.max_expand)
            w_ = None
        else:
            w_ = workspace(t_ok.size)
        # --c2f fallback (corridor too tight): the full fine search, guided by the octile distance to the NEAREST target
        hfull = octile_dt(np.ascontiguousarray(tgt.any(axis=0))) if (a.c2f and w_ is not None) else NOH
        path, exp = (path, exp) if w_ is None else astar_ws(t_ok, v_ok, ct_, cv_, np.ascontiguousarray(src), np.ascontiguousarray(tgt), lay,
                             np.float32(a.via_cost * p.get("vfac", 1.0)), tbox, a.max_expand, *w_[1:], np.float32(1.0),
                             hfull, bool(a.c2f and w_ is not None))
        astat["calls"] += 1
        astat["exp"] += int(exp)
        astat["fail"] += int(path.size == 0)
        astat["fail_exp"] += int(exp) if path.size == 0 else 0
        astat["cap"] += int(exp > a.max_expand)
        if path.size == 0:
            return None
        Wn, Hn = j1 - j0, i1 - i0
        ls = path // (Hn * Wn)
        r_ = path % (Hn * Wn)
        out = ls[::-1].copy(), (r_ // Wn)[::-1].copy(), (r_ % Wn)[::-1].copy()      # source -> target
        if a.tidy:
            out = tidy_path(n, L_, win, *out, drop, src)
        return out

    # ---------------- emission of one path (window coordinates) into tracks / vias
    cc_cache = {}

    def centre_at(n, L, gy, gx):
        """exact (x, y) of the own SMD pad whose centre falls in global cell (gy, gx) on L, else None"""
        k_ = (n, L)
        if k_ not in cc_cache:
            cc_cache[k_] = {(int(round((py_ - by0) / res - 0.5)), int(round((px_ - bx0) / res - 0.5))): (px_, py_)
                            for _, px_, py_, _ in smd_own.get(k_, ())}
        return cc_cache[k_].get((gy, gx))

    def emit(n, L_, win, path, drop_via=False):
        i0, j0, i1, j1 = win
        p = netcls[n]
        ls, yy, xx = path
        tr, vi = [], []
        k = 0
        while k < len(ls):
            k2 = k
            while k2 + 1 < len(ls) and ls[k2 + 1] == ls[k]:
                k2 += 1
            li = int(ls[k])
            L = RL[li]
            wnom = p["wo"] if L in OUTER else p["wi"]
            own = lab[L][i0:i1, j0:j1] == n + 1
            cells = list(range(k, k2 + 1))
            # pfr2-up: a path end at an own SMD pad's centre cell (tidy_path anchor) starts / ends at the EXACT centre
            # and is not trimmed (no off-angle landing stub: ACUTE / TRACK-FOLD / PAD-AXIS)
            sa = centre_at(n, L, int(yy[k]) + i0, int(xx[k]) + j0) if (a.tidy and k == 0 and L in OUTER) else None
            ea = centre_at(n, L, int(yy[k2]) + i0, int(xx[k2]) + j0)                 if (a.tidy and k2 == len(ls) - 1 and L in OUTER) else None
            # trim runs inside own copper at both ends (keep one own cell for the connection)
            a_, b_ = 0, len(cells) - 1
            while a_ < b_ and own[yy[cells[a_ + 1]], xx[cells[a_ + 1]]] and own[yy[cells[a_]], xx[cells[a_]]]:
                a_ += 1
            while b_ > a_ and own[yy[cells[b_ - 1]], xx[cells[b_ - 1]]] and own[yy[cells[b_]], xx[cells[b_]]]:
                b_ -= 1

            def straight(c_from, c_to):
                """cells c_from..c_to (indices into ls / yy / xx) lie on one straight step direction"""
                lo_, hi_ = min(c_from, c_to), max(c_from, c_to)
                if hi_ - lo_ < 1:
                    return True
                d0 = (yy[lo_ + 1] - yy[lo_], xx[lo_ + 1] - xx[lo_])
                return all((yy[c + 1] - yy[c], xx[c + 1] - xx[c]) == d0 for c in range(lo_, hi_))
            # an anchored end keeps its exact centre only when the first (last) straight piece runs on from the centre
            # past the trimmed own cells (no off-angle or dangling stub); otherwise the end stays trimmed and
            # land_stubs lands it as before
            if sa is not None and a_ > 0:
                if b_ > a_ and straight(cells[0], cells[a_ + 1]):
                    a_ = 0
                else:
                    sa = None
            if ea is not None and b_ < len(cells) - 1:
                if b_ > a_ and straight(cells[b_ - 1], cells[-1]):
                    b_ = len(cells) - 1
                else:
                    ea = None
            cells = cells[a_:b_ + 1]
            if len(cells) >= 2:
                # split into maximal straight pieces, width per piece clipped to the local slack
                pts = [(yy[c], xx[c]) for c in cells]
                brk = [0]
                for q in range(1, len(pts) - 1):
                    d1 = (pts[q][0] - pts[q - 1][0], pts[q][1] - pts[q - 1][1])
                    d2 = (pts[q + 1][0] - pts[q][0], pts[q + 1][1] - pts[q][1])
                    nom_change = bool(L_["nominal"][li][pts[q]]) != bool(L_["nominal"][li][pts[q + 1]])
                    if d1 != d2 or nom_change:
                        brk.append(q)
                brk.append(len(pts) - 1)
                sl = L_["slack"][L]
                # breakpoints in mm; an anchored end sits on the exact pad centre and its straight exit leg stays
                # exactly axis-parallel (the <= half-cell offset moves to the next corner)
                bp = [list(grid.mm(pts[b][1] + j0, pts[b][0] + i0)) for b in brk]
                if sa is not None:
                    bp[0] = list(sa)
                    if len(bp) > 2:
                        (ya, xa), (yb, xb) = pts[brk[0]], pts[brk[1]]
                        if ya == yb:
                            bp[1][1] = sa[1]
                        elif xa == xb:
                            bp[1][0] = sa[0]
                if ea is not None:
                    bp[-1] = list(ea)
                    if len(bp) > 2:
                        (ya, xa), (yb, xb) = pts[brk[-2]], pts[brk[-1]]
                        if ya == yb:
                            bp[-2][1] = ea[1]
                        elif xa == xb:
                            bp[-2][0] = ea[0]
                for q in range(len(brk) - 1):
                    (ya, xa), (yb, xb) = pts[brk[q]], pts[brk[q + 1]]
                    nseg = max(abs(yb - ya), abs(xb - xa)) + 1
                    cy = np.linspace(ya, yb, nseg).round().astype(int)
                    cx = np.linspace(xa, xb, nseg).round().astype(int)
                    if own[cy, cx].all():
                        continue
                    nown = ~own[cy, cx]
                    smin = float(sl[cy, cx][nown].min()) if nown.any() else 99.0   # own cells: exact pass (plan_check)
                    w = min(wnom, math.floor(2 * (smin - margin) * 1000) / 1000)
                    floor = p["neck"] if p["neck"] else wnom
                    w = max(w, min(floor, wnom))
                    if nets[n]["name"] in PWR_FAULT_NETS and w < wnom:
                        w = p["neck"]
                    (xs_, ys_), (xe_, ye_) = bp[q], bp[q + 1]
                    tr.append({"net": nets[n]["name"], "layer": L, "s": [round(xs_, 4), round(ys_, 4)],
                               "e": [round(xe_, 4), round(ye_, 4)], "w": round(w, 3)})
            if k2 + 1 < len(ls):
                vx, vy = grid.mm(xx[k2 + 1] + j0, yy[k2 + 1] + i0)
                vi.append({"net": nets[n]["name"], "x": round(vx, 4), "y": round(vy, 4), "d": p["vd"],
                           "drill": p["vdr"], "cell": (int(yy[k2 + 1]) + i0, int(xx[k2 + 1]) + j0)})
            k = k2 + 1
        if drop_via:
            vx, vy = grid.mm(xx[-1] + j0, yy[-1] + i0)
            vi.append({"net": nets[n]["name"], "x": round(vx, 4), "y": round(vy, 4), "d": p["vd"], "drill": p["vdr"],
                       "cell": (int(yy[-1]) + i0, int(xx[-1]) + j0), "drop": True})
        return tr, vi

    def draw_copper(n, tr, vi):
        """frozen copper -> obstacle labels (exact clearances for later nets) and hole-to-hole discs."""
        for t in tr:
            g = LineString([t["s"], t["e"]]).buffer(t["w"] / 2)
            draw_local(lab[t["layer"]], grid, g, n + 1)
        for v in vi:
            g = Point(v["x"], v["y"]).buffer(v["d"] / 2)
            for L in ALL_LAYERS:
                if L in PLANE_LAYERS and nets[n]["name"] in SOFT_ZONES:
                    continue
                draw_local(lab[L], grid, g, n + 1)
            r = (v["drill"] / 2 + HOLE_TO_HOLE + 0.15 + margin) / res
            oy, ox = disk(r)
            yy_, xx_ = v["cell"][0] + oy, v["cell"][1] + ox
            m = (yy_ >= 0) & (yy_ < H) & (xx_ >= 0) & (xx_ < W)
            hole_block[yy_[m], xx_[m]] = True

    # ---------------- exact (shapely) obstacle index mirroring the label rasters, for the check-and-veto loop
    ex_obs = defaultdict(list)                   # layer -> [(geom, net id | 31999)]
    for z in G["zones"]:
        if z["rule_area"] or nets[z["net"]]["name"] in SOFT_ZONES + SOFT_POURS:
            continue
        for L, rr in z.get("fills", {}).items():
            for r in rr:
                if nets[z["net"]]["class"] in POCKET_CLASSES:
                    g_ = cugraph.ring_poly(r)
                    for part, pk_ in ((g_.intersection(band), False), (g_.difference(band), True)):
                        if not part.is_empty:
                            ex_obs[L].append((part, z["net"], pk_))
                    continue
                ex_obs[L].append((cugraph.ring_poly(r), z["net"]))
    for k, it in cu.items.items():
        if it["kind"] == "zone":
            continue
        for L, g in it["geo"].items():
            if not g.is_empty:
                ex_obs[L].append((g, it["net"] if it["net"] else 31999))
    for n_, g_ in reserved:                      # held escape sites bind every other net exactly like a via
        for L in ALL_LAYERS:
            if not (L in PLANE_LAYERS and nets[n_]["name"] in SOFT_ZONES):
                ex_obs[L].append((g_, n_))
    ex_tree = {}

    ex_geo, ex_net, ex_pk = {}, {}, {}

    def ex_rebuild(layers=None):
        for L, lst in ex_obs.items():
            if layers is not None and L not in layers:
                continue
            ex_tree[L] = STRtree([o[0] for o in lst])
            ex_geo[L] = np.array([o[0] for o in lst], dtype=object)
            ex_net[L] = np.array([o[1] for o in lst], dtype=np.int64)
            ex_pk[L] = np.array([len(o) > 2 and o[2] for o in lst], dtype=bool)

    nv_cache = {}

    def need_vec(n, L):
        """need(n, f, L) for every net id f as an array indexed by f (31999 = no-net copper -> last slot)."""
        key = (n, L in OUTER)
        if key not in nv_cache:
            ids = sorted(nets)
            arr = np.zeros(max(ids) + 2, np.float64)
            for f in ids:
                arr[f] = need(n, f, L) if f else need(n, 31999, L)
            arr[-1] = need(n, 31999, L)
            nv_cache[key] = arr
        return nv_cache[key]

    def ex_add(n, tr, vi):
        for t in tr:
            ex_obs[t["layer"]].append((LineString([t["s"], t["e"]]).buffer(t["w"] / 2), n))
        for v in vi:
            g = Point(v["x"], v["y"]).buffer(v["d"] / 2)
            for L in ALL_LAYERS:
                if not (L in PLANE_LAYERS and nets[n]["name"] in SOFT_ZONES):
                    ex_obs[L].append((g, n))

    SAFE = 0.005                                 # polygonised pad arcs sit slightly inside the true outline

    own_pad_cache = {}

    def own_pads(n, L):
        k = (n, L)
        if k not in own_pad_cache:
            own_pad_cache[k] = [cugraph.ring_poly(r) for q in G["pads"] if q["net"] == n and L in q["shapes"]
                                for r in q["shapes"][L]]
        return own_pad_cache[k]

    def width_ok(n, L, cl, w):
        p = netcls[n]
        nm = nets[n]["name"]
        wnom = p["wo"] if L in OUTER else p["wi"]
        if p["current"]:                      # current_budget rule: required width, or the gate's neck only
            if w >= wnom - 1e-9:
                return True
            bx = [sbox(*nb["box"]) for nb in neck_boxes if nb["net"] == nm and nb["layer"] == L]                 if nm in PWR_FAULT_NETS else None
            return neck_ok(cl, w, wnom, p["neck"], own_pads(n, L), bx)
        if nm in PWR_FAULT_NETS:              # DRU: < 0.8 only wholly (at its width) inside one PWR_NECK area
            return w >= wnom - 1e-9 or (w >= p["neck"] - 1e-9 and any(
                sbox(*nb["box"]).contains(cl.buffer(w / 2)) for nb in neck_boxes
                if nb["net"] == nm and nb["layer"] == L))
        if nm in NET_FLOOR:
            return w >= NET_FLOOR[nm] - 1e-9
        return w >= max(INNER_SELV if (L not in OUTER and nets[n]["class"] == "SELV") else MIN_W,
                        p["neck"] if p["neck"] else wnom) - 1e-9

    def exact_fix(n, tr, vi, partners=None):
        """narrow widths to the exact clearance where the width rules allow; return violation points
        (partners: optional set collecting the net ids the violations are against)."""
        bad = []
        nm = nets[n]["name"]
        for t in tr:
            L = t["layer"]
            cl = LineString([t["s"], t["e"]])
            w = t["w"]
            hit_pt, hit_net = None, None
            # vectorised over the candidates (same math as the former per-candidate loop: the final width is the
            # smallest floor(2 (d - need)) over the pairs inside the clearance, the hit is the first such minimum)
            idx = ex_tree[L].query(cl.buffer(w / 2 + 6.6)) if L in ex_tree else np.zeros(0, np.int64)
            if idx.size:
                on_ = ex_net[L][idx]
                keep = (on_ != n) & ~(ex_pk[L][idx] & (nets[n]["class"] in POCKET_SOFT_FOR))
                idx, on_ = idx[keep], on_[keep]
            if idx.size:
                nv = need_vec(n, L)
                nd = nv[np.where(on_ == 31999, nv.size - 1, on_)] + SAFE
                d = shapely.distance(cl, ex_geo[L][idx])
                inside = d - w / 2 < nd
                if inside.any():
                    w2 = np.floor(2 * (d[inside] - nd[inside]) * 1000) / 1000
                    k = int(np.argmin(w2))
                    if w2[k] < w:
                        w = float(w2[k])
                        g = ex_geo[L][idx[inside][k]]
                        hit_pt = nearest_points(cl, g)[0]
                        hit_net = int(on_[inside][k])
            if not width_ok(n, L, cl, w):
                p_ = netcls[n]
                if nm in PWR_FAULT_NETS and w >= p_["neck"] and width_ok(n, L, cl, p_["neck"]):
                    w = p_["neck"]
                else:
                    pt = hit_pt or Point(t["s"])
                    bad.append(("t", L, pt.x, pt.y))
                    if partners is not None and hit_net is not None:
                        partners.add(hit_net)
            t["w"] = max(w, 0.0)
        for v in vi:
            g0 = Point(v["x"], v["y"]).buffer(v["d"] / 2)
            for L in ALL_LAYERS:
                if L not in ex_tree:
                    continue
                hit = False
                idx = ex_tree[L].query(g0.buffer(6.6))
                if idx.size:
                    on_ = ex_net[L][idx]
                    keep = (on_ != n) & ~(ex_pk[L][idx] & (nets[n]["class"] in POCKET_SOFT_FOR))
                    idx, on_ = idx[keep], on_[keep]
                if idx.size:
                    nv = need_vec(n, L)
                    nd = nv[np.where(on_ == 31999, nv.size - 1, on_)] + SAFE
                    m = shapely.distance(g0, ex_geo[L][idx]) < nd
                    if m.any():
                        hit = True
                        if partners is not None:
                            partners.add(int(on_[int(np.argmax(m))]))
                if hit:
                    bad.append(("v", L, v["x"], v["y"]))
                    break
        return bad

    vdisk = disk(0.12 / res)

    def veto(L_, win, bad):
        i0, j0, i1, j1 = win
        L_["ver"] = L_.get("ver", 0) + 1         # pfr2-speed: region labels of this legality are stale now
        for kind, L, x, y in bad:
            iy = int(round((y - by0) / res - 0.5)) - i0
            jx = int(round((x - bx0) / res - 0.5)) - j0
            yy_, xx_ = iy + vdisk[0], jx + vdisk[1]
            m = (yy_ >= 0) & (yy_ < i1 - i0) & (xx_ >= 0) & (xx_ < j1 - j0)
            if kind == "t" and L in RL:
                L_["tok"][RL.index(L)][yy_[m], xx_[m]] = False
            else:
                L_["vok"][yy_[m], xx_[m]] = False

    if a.preplan:
        PP = json.load(open(a.preplan))
        for v in PP.get("vias", []):
            n_ = name2id[v["net"]]
            iy = int(round((v["y"] - by0) / res - 0.5)); jx = int(round((v["x"] - bx0) / res - 0.5))
            v2 = dict(v, cell=(iy, jx))
            draw_copper(n_, [], [v2])
            ex_add(n_, [], [v2])
            out_vias[n_].append(v2)
        for t in PP.get("tracks", []):
            n_ = name2id[t["net"]]
            draw_copper(n_, [t], [])
            ex_add(n_, [t], [])
            out_tracks[n_].append(t)
        print(f"preplan: {len(PP.get('vias', []))} vias, {len(PP.get('tracks', []))} tracks", flush=True)
    ex_rebuild()
    unrouted, exact_fail = {}, defaultdict(int)
    fail_detail = []

    def comp_pads(comp):
        return sorted(f"{cu.items[u]['rec']['ref']}.{cu.items[u]['rec']['num']}" for u in comp if cu.items[u]["kind"] == "pad")
    t_power = time.time()
    # ---------------- power / plane nets first, sequential, frozen into the obstacle rasters
    power = [n for n in todo if n not in sig_nets]
    rank = {nm: i for i, nm in enumerate(ORDER_FIRST)}
    power.sort(key=lambda n: (rank.get(nets[n]["name"], 100), -len(todo[n])))

    def try_join(n, L_, win, src, tgt, drop):
        for attempt in range(8):
            path = run_astar(n, L_, win, src, tgt, drop=drop)
            if path is None:
                return None
            tr, vi = emit(n, L_, win, path, drop_via=drop)
            bad = exact_fix(n, tr, vi)
            if not bad:
                return path, tr, vi
            veto(L_, win, bad)
            if drop:
                pv = L_["pv"] & L_["vok"] & ~hole_block[win[0]:win[2], win[1]:win[3]]
                for li in range(len(RL)):
                    tgt[li] = pv
        exact_fail[n] += 1
        return None

    neg_power = []
    for n in power:
        nm = nets[n]["name"]
        cs = todo[n]
        left = 0
        if nm in NEG_PLANE and n in plane_comp and plane_comp[n]:
            print(f"power {nm}: {len(cs) - len(plane_comp[n])} drops deferred to the negotiated phase", flush=True)
            continue
        if nm not in FROZEN_POWER and not (n in plane_comp and plane_comp[n]):
            neg_power.append(n)
            print(f"power {nm}: {len(cs) - 1} joins deferred to the negotiated phase", flush=True)
            continue
        if n in plane_comp and plane_comp[n]:
            on = set(plane_comp[n])
            for ci, comp in enumerate(cs):
                if ci in on:
                    continue
                done = False
                for pad_ in (2.0, 4.0, 8.0):
                    win = bbox_of(comp, pad_)
                    L_ = legality(n, win)
                    src = comp_mask(comp, win)
                    tgt = np.zeros_like(src)
                    pv = L_["pv"] & ~hole_block[win[0]:win[2], win[1]:win[3]]
                    for li in range(len(RL)):
                        tgt[li] = pv
                    res_ = try_join(n, L_, win, src, tgt, True)
                    if res_ is None:
                        continue
                    _, tr, vi = res_
                    out_tracks[n] += tr
                    out_vias[n] += vi
                    draw_copper(n, tr, vi)
                    ex_add(n, tr, vi)
                    ex_rebuild()
                    done = True
                    break
                if not done:
                    left += 1
                    fail_detail.append({"net": nm, "pads": comp_pads(comp)})
        else:
            # the rails' window is the whole board: the island's only top-band <-> bottom-band passage is the left
            # column (x < 16), outside the bbox of the cells + supply (2026-10-04 rails-only check: with bbox + 4 mm
            # all three rails split top band | bottom band + supply, also at 10x the A* budget)
            win = bbox_of(set().union(*cs), RAIL_WINDOW if nm in RAIL_NETS else 4.0)
            L_ = legality(n, win)
            masks = [comp_mask(c, win) for c in cs]
            tree = masks[0].copy()
            seed = 0
            rem = list(range(1, len(masks)))
            while rem:
                tgt = np.zeros_like(tree)
                for j in rem:
                    tgt |= masks[j]
                res_ = try_join(n, L_, win, tree, tgt, False)
                if res_ is None:
                    # forest: this tree reaches nothing more; it stays one open join and the next component seeds a new
                    # tree (a trapped component no longer leaves the whole net unrouted)
                    left += 1
                    fail_detail.append({"net": nm, "left": [comp_pads(cs[seed])]})
                    seed = rem.pop(0)
                    tree = masks[seed].copy()
                    continue
                (ls, yy, xx), tr, vi = res_
                hit = next(j for j in rem if masks[j][ls[-1], yy[-1], xx[-1]])
                rem.remove(hit)
                out_tracks[n] += tr
                out_vias[n] += vi
                draw_copper(n, tr, vi)
                ex_add(n, tr, vi)
                ex_rebuild()
                tree[ls, yy, xx] = True
                tree |= masks[hit]
        if left:
            unrouted[n] = left
        print(f"power {nm}: joins {len(cs) - 1}, left {left} ({time.time() - t0:.0f}s)", flush=True)
    print(f"power phase {time.time() - t_power:.0f}s", flush=True)
    phase("power", t_power)
    if a.probe:
        nm, pts = a.probe.split("@")
        n = name2id[nm]
        win = bbox_of(set().union(*todo[n]), 3.0)
        L_ = legality(n, win)
        i0, j0, i1, j1 = win
        for xy in pts.split(";"):
            x, y = map(float, xy.split(","))
            iy, jx = int(round((y - by0) / res - 0.5)) - i0, int(round((x - bx0) / res - 0.5)) - j0
            row = {L: (bool(L_["tok"][li][iy, jx]), bool(L_["nominal"][li][iy, jx]), round(float(L_["slack"][L][iy, jx]), 3))
                   for li, L in enumerate(RL)}
            gy, gx = iy + i0, jx + j0
            print(f"probe {nm} ({x},{y}) vpen={None if L_.get('vpen') is None else float(L_['vpen'][iy, jx])} vok={bool(L_['vok'][iy, jx])} tblock={bool(tblock[gy, gx])} vblock="
                  f"{bool(vblock[gy, gx])} d_edge={float(d_edge[gy, gx]):.2f} hole_block={bool(hole_block[gy, gx])} "
                  f"lab={ {L: int(lab[L][gy, gx]) - 1 for L in ALL_LAYERS} } {row}", flush=True)
            p_ = netcls[n]
            print(f"   via terms: need r {p_['vd'] / 2 + margin:.3f}; slack "
                  f"{ {L: round(float(L_['slack'][L][iy, jx]), 3) for L in ALL_LAYERS} } d_vblock "
                  f"{float(d_vblock[gy, gx]):.3f} d_drill {float(d_drill[gy, gx]):.3f} (need "
                  f"{p_['vdr'] / 2 + HOLE_TO_HOLE + margin:.3f}) d_npth {float(d_npth[gy, gx]):.3f}", flush=True)
        return
    if a.diag:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from pathlib import Path
        for nm in a.diag.split(","):
            n = name2id[nm]
            if n not in todo:
                print("diag: not open", nm)
                continue
            win = bbox_of(set().union(*todo[n]), 3.0)
            L_ = legality(n, win)
            masks = [comp_mask(c, win) for c in todo[n]]
            i0, j0, i1, j1 = win
            fig, axs = plt.subplots(1, len(RL), figsize=(6 * len(RL), 6 * (i1 - i0) / max(1, j1 - j0) + 1))
            for ci, m in enumerate(masks):
                # flood from comp ci on tok, with via jumps on vok
                reach = m & L_["tok"]
                reach |= m
                for _ in range(400):
                    prev = reach.sum()
                    for li in range(len(RL)):
                        reach[li] = ndimage.binary_dilation(reach[li], mask=L_["tok"][li] | m[li])
                    vj = reach.any(axis=0) & L_["vok"] & ~hole_block[i0:i1, j0:j1]
                    for li in range(len(RL)):
                        reach[li] |= vj & L_["tok"][li]
                    if reach.sum() == prev:
                        break
                hits = [cj for cj, m2 in enumerate(masks) if cj != ci and (reach & m2).any()]
                print(f"diag {nm} comp {ci} pads {sorted(f'{cu.items[u][chr(114)+chr(101)+chr(99)][chr(114)+chr(101)+chr(102)]}' for u in todo[n][ci] if cu.items[u]['kind'] == 'pad')} reaches comps {hits} area {int(reach.sum())}", flush=True)
                for li in range(len(RL)):
                    if ci == 0:
                        axs[li].imshow(L_["tok"][li], cmap="gray", extent=(bx0 + j0 * res, bx0 + j1 * res, by0 + i1 * res, by0 + i0 * res))
                    axs[li].contour(np.linspace(bx0 + j0 * res, bx0 + j1 * res, j1 - j0), np.linspace(by0 + i0 * res, by0 + i1 * res, i1 - i0), reach[li].astype(float), levels=[0.5], colors=[plt.cm.tab10(ci % 10)], linewidths=1)
                    axs[li].contour(np.linspace(bx0 + j0 * res, bx0 + j1 * res, j1 - j0), np.linspace(by0 + i0 * res, by0 + i1 * res, i1 - i0), m[li].astype(float), levels=[0.5], colors=["red"], linewidths=1.5)
            for li in range(len(RL)):
                axs[li].set_title(f"{nm} {RL[li]} (white = legal)")
            plt.tight_layout()
            plt.savefig(str(Path(a.out).with_name(f"diag-{nm}.png")), dpi=70)
            plt.close(fig)
        return
    # ---------------- signals + negotiable plane drops: negotiated congestion over the (now fixed) power copper
    # a routing UNIT is a signal net id (int) or ("drop", net id, comp index) for one off-plane comp of a NEG_PLANE net
    cache = {}
    sig_fail = {}
    unrouted_u, exact_fail_u = {}, defaultdict(int)

    def netof(u):
        return u if isinstance(u, (int, np.integer)) else u[1]

    def costs(win, pres):
        i0, j0, i1, j1 = win
        ct = (1.0 + hist[:, i0:i1, j0:j1] + pres * occ_t[:, i0:i1, j0:j1]).astype(np.float32)
        cv = (1.0 + hist_v[i0:i1, j0:j1] + pres * occ_v[:, i0:i1, j0:j1].sum(axis=0)).astype(np.float32)
        return ct, cv

    def warm(u):
        """fill the unit's window / legality / component masks (independent of the routing state, so the first
        pass can compute them for all units in parallel: the distance transforms release the GIL)"""
        if u in cache:
            return
        n = netof(u)
        if not isinstance(u, (int, np.integer)):
            comp = todo[n][u[2]]
            for pad_ in (2.0, 4.0, 8.0):
                win = bbox_of(comp, pad_)
                L_ = legality(n, win)
                if L_["pv"] is not None and L_["pv"].any():
                    break
            # existing plane-connected copper of the net in the window is a target too (share a via)
            onp = [todo[n][ci] for ci in plane_comp.get(n, [])]
            own = np.zeros((len(RL), win[2] - win[0], win[3] - win[1]), bool)
            for c in onp:
                bx = bbox_of(c, 0.0)
                if bx[2] < win[0] or bx[0] > win[2] or bx[3] < win[1] or bx[1] > win[3]:
                    continue
                own |= comp_mask(c, win)
            cache[u] = (win, L_, [comp_mask(comp, win)], own)
        else:
            win = bbox_of(set().union(*todo[n]), 4.0)
            cache[u] = (win, legality(n, win), [comp_mask(c, win) for c in todo[n]])

    # pfr2-speed REACHABILITY SKIP: an A* whose target lies in no region its source can reach explores the whole
    # reachable window (up to --max-expand) and fails - every pass, for every join that is blocked for good (the
    # "unrouted joins 148" of every SUBB pass). The legal graph is static per unit during negotiation (tok / vok change
    # only by veto, which bumps L_["ver"]), so its connected regions are labelled once per unit and a join whose tree
    # and targets share no region is failed without the search. Exact: the A* moves (4- / 8-neighbour with the
    # squeeze rule = 4-connectivity of trace-ok cells, plus through-via jumps at via-ok cells between allowed layers,
    # source cells pushed even when not trace-ok) are mirrored, and a source / target overlap never skips.
    reg_cache = {}

    def region_labels(n, t_ok, v_ok):
        lay = [not (netcls[n]["outer"] and L not in OUTER) for L in RL]
        NL = t_ok.shape[0]
        labs = np.zeros(t_ok.shape, np.int64)
        off = 0
        for l in range(NL):
            if not lay[l]:
                continue
            lb, k = ndimage.label(t_ok[l])
            labs[l] = np.where(lb > 0, lb + off, 0)
            off += k
        rows, cols = [], []
        al = [l for l in range(NL) if lay[l]]
        for x_, l1 in enumerate(al):
            for l2 in al[x_ + 1:]:
                m = v_ok & (labs[l1] > 0) & (labs[l2] > 0)
                if m.any():
                    rows.append(labs[l1][m])        # duplicate pairs are fine: the csr build sums them
                    cols.append(labs[l2][m])
        if rows:
            from scipy.sparse import coo_matrix
            from scipy.sparse.csgraph import connected_components
            r_, c_ = np.concatenate(rows), np.concatenate(cols)
            _, cid = connected_components(coo_matrix((np.ones(r_.size, np.int32), (r_, c_)), shape=(off + 1, off + 1)),
                                          directed=False)
        else:
            cid = np.arange(off + 1)
        reg = cid[labs]
        reg[labs == 0] = -1
        return reg, np.array(lay, bool)

    def unit_region(u, n, prep):
        if hard_state["on"]:                     # hard occupancy changes per call: never cached
            return region_labels(n, prep[0], prep[1])
        L_ = cache[u][1]
        k_ = reg_cache.get(u)
        if k_ is None or k_[0] != L_.get("ver", 0):
            k_ = (L_.get("ver", 0),) + region_labels(n, prep[0], prep[1])
            reg_cache[u] = k_
        return k_[1], k_[2]

    def src_labels(S, reg, lay, v_ok, bb=None):
        """regions an A* started from source cells S can enter (bb: the cells' bbox, the work is limited to it + 1)"""
        if bb is not None:
            y0_, x0_ = max(0, bb[0] - 1), max(0, bb[1] - 1)
            y1_, x1_ = min(S.shape[1], bb[2] + 2), min(S.shape[2], bb[3] + 2)
            S, reg, v_ok = S[:, y0_:y1_, x0_:x1_], reg[:, y0_:y1_, x0_:x1_], v_ok[y0_:y1_, x0_:x1_]
        S = S & lay[:, None, None]
        nb = S.copy()
        nb[:, 1:, :] |= S[:, :-1, :]
        nb[:, :-1, :] |= S[:, 1:, :]
        nb[:, :, 1:] |= S[:, :, :-1]
        nb[:, :, :-1] |= S[:, :, 1:]
        sv = S.any(axis=0) & v_ok
        out_ = np.unique(np.concatenate([reg[nb], reg[:, sv].ravel()]))
        return set(out_[out_ >= 0].tolist())

    def tgt_labels(T, reg, lay, bb=None):
        if bb is not None:
            T, reg = T[:, bb[0]:bb[2] + 1, bb[1]:bb[3] + 1], reg[:, bb[0]:bb[2] + 1, bb[1]:bb[3] + 1]
        out_ = np.unique(reg[T & lay[:, None, None]])
        return set(out_[out_ >= 0].tolist())

    skip_stat = collections.Counter()

    mbb_cache = {}

    def mask_bbox(u):
        """per component mask of a signal unit: (y0, x0, y1, x1) of its cells over all layers, None when empty"""
        if u not in mbb_cache:
            out_ = []
            for m_ in cache[u][2]:
                ys_, xs_ = np.nonzero(m_.any(axis=0))
                out_.append((int(ys_.min()), int(xs_.min()), int(ys_.max()), int(xs_.max())) if ys_.size else None)
            mbb_cache[u] = out_
        return mbb_cache[u]

    dead = {}                                    # unit -> its open joins are ALL reachability-certain (static legality)

    def route_unit(u, pres):
        sig_fail.pop(u, None)
        n = netof(u)
        if not hard_state["on"]:
            dead.pop(u, None)
        if not isinstance(u, (int, np.integer)):
            comp = todo[n][u[2]]
            warm(u)
            win, L_, masks, own = cache[u]
            ct, cv = costs(win, pres)
            tgt = np.zeros_like(masks[0])
            pv = L_["pv"] & L_["vok"] & ~hole_block[win[0]:win[2], win[1]:win[3]]
            for li in range(len(RL)):
                tgt[li] = pv | (own[li] & L_["tok"][li])
            prep = astar_prep(n, L_, win, ct, cv)
            path = None
            if not OLD_ASTAR:
                reg, lay_ = unit_region(u, n, prep)
                if not (masks[0] & tgt).any() and \
                        not (src_labels(masks[0], reg, lay_, prep[1]) & tgt_labels(tgt, reg, lay_)):
                    skip_stat["drop"] += 1
                    sig_fail[u] = [comp_pads(comp)]
                    if not hard_state["on"]:
                        dead[u] = True
                    return [], [1]
            path = run_astar(n, L_, win, masks[0], tgt, drop=True, prep=prep)
            if path is None:
                sig_fail[u] = [comp_pads(comp)]
                return [], [1]
            return [path], []
        warm(u)
        win, L_, masks = cache[u]
        ct, cv = costs(win, pres)
        # pfr2-speed: the A* inputs once per unit, the target union maintained incrementally (re-OR only inside the
        # removed component's bbox) and its bbox from the component bboxes - the former per-join O(window x
        # components) rebuild dominated big nets (+3V3: 63 joins over a near-whole-board window). Same targets.
        if OLD_ASTAR:                                # verification switch: the former per-join target rebuild
            tree = masks[0].copy()
            seed = 0
            rem = list(range(1, len(masks)))
            paths, failed = [], []
            while rem:
                tgt = np.zeros_like(tree)
                for j in rem:
                    tgt |= masks[j]
                path = run_astar(n, L_, win, tree, tgt, ct, cv)
                if path is None:
                    failed.append(seed)
                    seed = rem.pop(0)
                    tree = masks[seed].copy()
                    continue
                ls, yy, xx = path
                hit = next(j for j in rem if masks[j][ls[-1], yy[-1], xx[-1]])
                rem.remove(hit)
                paths.append(path)
                tree[ls, yy, xx] = True
                tree |= masks[hit]
            if failed:
                sig_fail[u] = [comp_pads(todo[n][j]) for j in failed]
            return paths, failed
        prep = astar_prep(n, L_, win, ct, cv)
        mbb = mask_bbox(u)
        tree = masks[0].copy()
        seed = 0
        rem = list(range(1, len(masks)))
        paths, failed = [], []
        tgt = np.zeros_like(tree)
        for j in rem:
            if mbb[j] is not None:
                y0_, x0_, y1_, x1_ = mbb[j]
                tgt[:, y0_:y1_ + 1, x0_:x1_ + 1] |= masks[j][:, y0_:y1_ + 1, x0_:x1_ + 1]

        def drop_target(k):
            if mbb[k] is None:
                return
            y0_, x0_, y1_, x1_ = mbb[k]
            sub = np.zeros_like(tgt[:, y0_:y1_ + 1, x0_:x1_ + 1])
            for j in rem:
                if mbb[j] is not None:
                    sub |= masks[j][:, y0_:y1_ + 1, x0_:x1_ + 1]
            tgt[:, y0_:y1_ + 1, x0_:x1_ + 1] = sub
        reg, lay_ = unit_region(u, n, prep)
        tl_ = {}

        def tlab(j):
            if j not in tl_:
                tl_[j] = tgt_labels(masks[j], reg, lay_, mbb[j]) if mbb[j] is not None else set()
            return tl_[j]
        reach = src_labels(masks[0], reg, lay_, prep[1], mbb[0]) if mbb[0] is not None else set()
        nskip = 0
        csm = None
        if a.c2f:                                # --c2f: coarse tree / target masks kept in step with the fine ones
            Hc_, Wc_ = (tree.shape[1] + 1) // 2, (tree.shape[2] + 1) // 2
            csm = [down_any(tree, Hc_, Wc_), down_any(tgt, Hc_, Wc_)]

            def c_tgt(k):
                if mbb[k] is not None:
                    y0_, x0_, y1_, x1_ = mbb[k]
                    down_region(csm[1], tgt, y0_, y1_ + 1, x0_, x1_ + 1, True)
        while rem:
            bbs = [mbb[j] for j in rem if mbb[j] is not None]
            path = None
            if bbs:
                if not any(reach & tlab(j) for j in rem) and not any(
                        mbb[j] is not None and (tree[:, mbb[j][0]:mbb[j][2] + 1, mbb[j][1]:mbb[j][3] + 1] &
                                                masks[j][:, mbb[j][0]:mbb[j][2] + 1, mbb[j][1]:mbb[j][3] + 1]).any()
                        for j in rem):
                    skip_stat["join"] += 1        # certain failure: no shared region, no overlap
                    nskip += 1
                else:
                    tb = np.array([min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs),
                                   max(b[3] for b in bbs)], dtype=np.int64)
                    path = run_astar(n, L_, win, tree, tgt, prep=prep, tbox=tb, cs=csm)
            if path is None:
                # the current tree reaches no remaining component: it stays a separate piece (one open join) and the
                # next remaining component seeds a new tree - a trapped pad no longer blocks the rest of its net
                failed.append(seed)
                seed = rem.pop(0)
                drop_target(seed)
                tree = masks[seed].copy()
                reach = src_labels(masks[seed], reg, lay_, prep[1], mbb[seed]) if mbb[seed] is not None else set()
                if csm is not None:
                    c_tgt(seed)
                    csm[0] = down_any(tree, Hc_, Wc_)
                continue
            ls, yy, xx = path
            hit = next(j for j in rem if masks[j][ls[-1], yy[-1], xx[-1]])
            rem.remove(hit)
            drop_target(hit)
            paths.append(path)
            tree[ls, yy, xx] = True
            if csm is not None:
                c_tgt(hit)
                csm[0][ls, yy // 2, xx // 2] = True
                if mbb[hit] is not None:
                    down_region(csm[0], masks[hit], mbb[hit][0], mbb[hit][2] + 1, mbb[hit][1], mbb[hit][3] + 1, False)
            if mbb[hit] is not None:
                y0_, x0_, y1_, x1_ = mbb[hit]
                tree[:, y0_:y1_ + 1, x0_:x1_ + 1] |= masks[hit][:, y0_:y1_ + 1, x0_:x1_ + 1]
                reach |= src_labels(masks[hit], reg, lay_, prep[1], mbb[hit])
        if failed:
            sig_fail[u] = [comp_pads(todo[n][j]) for j in failed]
            if not hard_state["on"]:
                dead[u] = nskip == len(failed)
        return paths, failed

    def is_drop(u):
        return not isinstance(u, (int, np.integer))

    def drop_on_copper(u, ls, yy, xx):
        own = cache[u][3]
        return bool(own[ls[-1], yy[-1], xx[-1]])

    def commit(u, paths):
        n = netof(u)
        win = cache[u][0]
        cells = []
        L_ = cache[u][1]
        for ls, yy, xx in paths:
            gy, gx = yy + win[0], xx + win[1]
            for li in range(len(RL)):
                # cells on the net's OWN existing copper (pads, fixed tracks) are not new copper: no halo / overlap
                m = (ls == li) & (lab[RL[li]][gy, gx] != n + 1)
                if m.any():
                    nom = L_["nominal"][li][yy[m], xx[m]]
                    if nom.all():
                        cells.append((li, gy[m].astype(np.int64), gx[m].astype(np.int64), "t"))
                    else:
                        cells.append((li, gy[m][nom].astype(np.int64), gx[m][nom].astype(np.int64), "t"))
                        cells.append((li, gy[m][~nom].astype(np.int64), gx[m][~nom].astype(np.int64), "n"))
            vy = [yy[k] + win[0] for k in range(1, len(ls)) if ls[k] != ls[k - 1]]
            vx = [xx[k] + win[1] for k in range(1, len(ls)) if ls[k] != ls[k - 1]]
            if is_drop(u) and not drop_on_copper(u, ls, yy, xx):
                vy.append(yy[-1] + win[0])
                vx.append(xx[-1] + win[1])
            if vy:
                cells.append((0, np.array(vy, np.int64), np.array(vx, np.int64), "v"))
        routed[u] = {"paths": paths, "cells": cells, "halo": halo_offsets(n)}
        apply_stamps(u, +1)

    def uncommit(u):
        if u in routed:
            apply_stamps(u, -1)
            del routed[u]

    drop_peers = defaultdict(list)

    def overlaps(u):
        # same-net plane drops may touch each other (one net): take their stamps out while counting
        peers = [v for v in drop_peers[netof(u)] if v != u and v in routed] if is_drop(u) else []
        for v in peers:
            apply_stamps(v, -1)
        apply_stamps(u, -1)
        bad = 0
        for (li, ys, xs, kind) in routed[u]["cells"]:
            if kind in ("t", "n"):
                bad += int((occ_t[li, ys, xs] > 0).sum())
            else:
                bad += int((occ_v[:, ys, xs] > 0).any(axis=0).sum())
        apply_stamps(u, +1)
        for v in peers:
            apply_stamps(v, +1)
        return bad

    def emit_unit(u):
        n = netof(u)
        win, L_ = cache[u][0], cache[u][1]
        trs, vis = [], []
        for path in routed[u]["paths"]:
            tr, vi = emit(n, L_, win, path, drop_via=is_drop(u) and not drop_on_copper(u, *path))
            trs += tr
            vis += vi
        return trs, vis

    state = {"pres": 0.5}

    def negotiate(order, iters, stall=8, gain=0.03, until=None, stall3=False):
        """PathFinder passes; stops early when the overlap has not improved by `gain` (relative) in `stall` passes.
        Every 8th pass re-routes ALL units (settled units yield space too); otherwise only units in conflict.
        stall3 (pfr2-speed --neg-stall3): also stop when the unrouted joins have not improved over the last 3 passes
        AND the overlap cells fell by less than --stall3-gain (10 %) over them."""
        everyone = list(order)
        best, best_it = None, 0
        hist_fc = []
        for it in range(iters):
            fails = 0
            step = max(1, a.threads) if a.par_negotiate else 1
            c0 = 0
            while c0 < len(order):
                # the very first unit runs alone (numba compile / cache warm-up), then chunks of `step`
                chunk = order[c0:c0 + (1 if not state.get("warm") else step)]
                c0 += len(chunk)
                for u in chunk:
                    uncommit(u)
                if len(chunk) == 1:
                    results = [route_unit(chunk[0], state["pres"])]
                else:
                    results = list(POOL.map(lambda u_: route_unit(u_, state["pres"]), chunk))
                state["warm"] = True
                for u, (paths, rem) in zip(chunk, results):
                    commit(u, paths)
                    if rem:
                        unrouted_u[u] = len(rem)
                        fails += len(rem)
                    else:
                        unrouted_u.pop(u, None)
            bad_u, tot_bad = [], 0
            for u in list(routed):
                b = overlaps(u)
                if b:
                    bad_u.append(u)
                    tot_bad += b
                    for (li, ys, xs, kind) in routed[u]["cells"]:
                        if kind in ("t", "n"):
                            hist[li, ys, xs] += 0.3
                        else:
                            hist_v[ys, xs] += 0.3
            print(f"iter {it}: overlapping units {len(bad_u)} (cells {tot_bad}), unrouted joins {fails} "
                  f"({time.time() - t0:.0f}s)", flush=True)
            if it % 10 == 9:                     # congestion snapshot for diagnosis while the run continues
                snap = []
                for u in bad_u:
                    apply_stamps(u, -1)
                    for (li, ys, xs, kind) in routed[u]["cells"]:
                        if kind in ("t", "n"):
                            m = occ_t[li, ys, xs] > 0
                            for y_, x_ in list(zip(ys[m], xs[m]))[::10]:
                                xm, ym = grid.mm(x_, y_)
                                snap.append([round(xm, 2), round(ym, 2), RL[li], nets[netof(u)]["name"]])
                    apply_stamps(u, +1)
                json.dump({"iter": it, "overlap_cells": snap, "unrouted": [str(u) for u in unrouted_u]},
                          open(a.out + ".congestion.json", "w"))
            if not bad_u and not fails:
                return
            if until is not None and time.time() > until:
                print(f"budget: negotiation stopped at pass {it} ({time.time() - t0:.0f}s)", flush=True)
                return
            hist_fc.append((fails, tot_bad))
            if stall3 and it >= 3:
                f3, c3 = hist_fc[-4]
                if fails >= f3 and tot_bad > (1.0 - a.stall3_gain) * c3:
                    print(f"stall3: unrouted {f3} -> {fails}, overlap cells {c3} -> {tot_bad} over 3 passes; "
                          f"stopping at pass {it}", flush=True)
                    return
            score = tot_bad + 200 * fails
            if best is None or score < best * (1 - gain):
                best, best_it = score, it
            elif it - best_it >= stall:
                print(f"stagnated: best {best} at pass {best_it}; stopping at pass {it}", flush=True)
                return
            state["pres"] = min(state["pres"] * 1.5, 200.0)
            if it % 8 == 7:
                order = everyone                 # periodic full rip-up
            else:
                # selective rip-up: only the units in conflict (plus the unrouted ones) are re-routed next pass
                # pfr2-speed --skip-dead: a unit whose open joins are all reachability-certain and that overlaps
                # nothing has nothing to negotiate (soft costs never open a blocked join): not re-routed here
                order = bad_u + [u for u in unrouted_u if u not in bad_u and not (a.skip_dead and dead.get(u))]

    units = []
    for n in todo:
        if nets[n]["name"] in NEG_PLANE and n in plane_comp and plane_comp[n]:
            units += [("drop", n, ci) for ci in range(len(todo[n])) if ci not in set(plane_comp[n])]
    for u in units:
        drop_peers[netof(u)].append(u)
    units += sorted(neg_power, key=lambda n: -sum(len(c) for c in todo[n]))
    sig_order = sorted(sig_nets, key=lambda n: sum(len(c) for c in todo[n]))
    if a.seed:                                   # variant runs: a deterministic shuffle of the signal order
        import random
        random.Random(a.seed).shuffle(sig_order)
    units += sig_order
    print(f"negotiated units: {len(units)} ({sum(1 for u in units if is_drop(u))} plane drops)", flush=True)
    if a.threads > 1:
        tw = time.time()
        list(POOL.map(warm, units))
        print(f"legality warm-up ({a.threads} threads): {time.time() - tw:.1f}s", flush=True)
        phase("warm-up", tw)

    def dedup(trs):
        """drop same-net same-layer tracks whose centreline lies on another one at least as wide (TRACK-DUP).
        pfr2-speed: the same rule per track (any earlier-kept / longer covering track drops it), with a bbox
        prefilter and vectorised distances - the pairwise LineString loop was 12 s per call (5 calls per run)."""
        grp = defaultdict(list)
        for t in trs:
            grp[(t["net"], t["layer"])].append(t)
        out_, gone = [], 0
        for key, lst in grp.items():
            m_ = len(lst)
            S_ = np.array([t["s"] for t in lst], np.float64).reshape(m_, 2)
            E_ = np.array([t["e"] for t in lst], np.float64).reshape(m_, 2)
            W_ = np.array([t["w"] for t in lst], np.float64)
            valid = np.array([t["s"] != t["e"] for t in lst], bool)
            lines = np.array([LineString([t["s"], t["e"]]) if valid[i] else None for i, t in enumerate(lst)], object)
            lens = np.zeros(m_)
            if valid.any():
                lens[valid] = shapely.length(lines[valid])
            e_ = 2e-4
            lx0, lx1 = np.minimum(S_[:, 0], E_[:, 0]) - e_, np.maximum(S_[:, 0], E_[:, 0]) + e_
            ly0, ly1 = np.minimum(S_[:, 1], E_[:, 1]) - e_, np.maximum(S_[:, 1], E_[:, 1]) + e_
            dropped = np.zeros(m_, bool)
            for i in range(m_):
                if not valid[i]:
                    dropped[i] = True
                    continue
                (sx, sy), (ex_, ey) = S_[i], E_[i]
                cand = valid & ~dropped & (W_ >= W_[i] - 1e-9) & (lx0 <= min(sx, ex_)) & (lx1 >= max(sx, ex_)) & \
                    (ly0 <= min(sy, ey)) & (ly1 >= max(sy, ey))
                cand[i] = False
                idx = np.nonzero(cand)[0]
                if idx.size:
                    ok = (shapely.distance(lines[idx], Point(lst[i]["s"])) < 1e-4) & \
                         (shapely.distance(lines[idx], Point(lst[i]["e"])) < 1e-4) & \
                         ((lens[idx] > lens[i] + 1e-9) | (idx < i))
                    if ok.any():
                        dropped[i] = True
            gone += int(dropped.sum())
            out_ += [t for i, t in enumerate(lst) if not dropped[i]]
        return out_, gone

    def unit_joins(u):
        return 1 if is_drop(u) else len(todo[netof(u)]) - 1

    def write_plan(emitted_, excluded, stage):
        """pfr2-up checkpoint: a LEGAL plan of the copper accepted so far (frozen power + preplan + the given units'
        exact-clean copper); excluded / not-emitted units count all their joins unrouted. Atomic (tmp + replace)."""
        ot = [t for n_ in out_tracks for t in out_tracks[n_]]
        ov = [{k: v for k, v in x.items() if k != "cell"} for n_ in out_vias for x in out_vias[n_]]
        for u, (trs, vis) in emitted_.items():
            ot += trs
            ov += [{k: v for k, v in x.items() if k != "cell"} for x in vis]
        ot, _ = dedup(ot)
        unr = defaultdict(int, unrouted)
        for u in units:
            unr[netof(u)] += unit_joins(u) if (u in excluded or u not in emitted_) else unrouted_u.get(u, 0)
        out_ = {"geom": a.geom, "board_sha256": G["sha256"], "res": res, "margin": margin, "tracks": ot, "vias": ov,
                "unrouted": {nets[k]["name"]: v for k, v in unr.items() if v}, "overlapping_nets": [],
                "exact_fail": {}, "fail_detail": fail_detail, "neck_boxes": neck_boxes, "overlap_cells": [],
                "checkpoint": stage, "seconds": round(time.time() - t0, 1)}
        tmp = a.out + ".tmp"
        json.dump(out_, open(tmp, "w"), indent=1)
        os.replace(tmp, a.out)
        print(f"checkpoint ({stage}): {len(ot)} tracks, {len(ov)} vias, unrouted {sum(out_['unrouted'].values())}",
              flush=True)
    write_plan({}, set(units), "power phase")
    t_neg = time.time()
    negotiate(units, min(a.iters, a.det_neg) if a.det else a.iters, stall=a.stall, gain=a.gain,
              until=(t0 + 0.55 * a.budget) if a.budget else None, stall3=a.neg_stall3)
    phase("negotiation", t_neg)
    t_srr = time.time()
    if a.srr:
        from scipy.spatial import cKDTree
        rips = collections.Counter()

        def cells_xy(u):
            pts = [np.stack([ys, xs], axis=1) for (li, ys, xs, kind) in routed[u]["cells"]]
            return np.concatenate(pts) if pts else np.zeros((0, 2), np.int64)

        reach = int(math.ceil(1.6 / res))     # halo radius bound (wide power track + clearance + partner) in cells
        queue = collections.deque([u for u in list(routed) if overlaps(u)] +
                                  [u for u in list(unrouted_u) if not (a.skip_dead and dead.get(u))])
        seenq, steps, fixed_ok, ripped = set(), 0, 0, 0
        while queue and steps < (min(a.srr, a.det_srr) if a.det else a.srr) and                 not (a.budget and time.time() - t0 > 0.75 * a.budget):
            u = queue.popleft()
            steps += 1
            uncommit(u)
            hard_state["on"] = True
            paths, rem = route_unit(u, state["pres"])
            hard_state["on"] = False
            if not rem:
                commit(u, paths)
                unrouted_u.pop(u, None)
                fixed_ok += 1
                continue
            paths_s, rem_s = route_unit(u, state["pres"])
            commit(u, paths_s)
            if rem_s:
                unrouted_u[u] = len(rem_s)
                continue
            uc = cells_xy(u)
            if not len(uc):
                continue
            tree_u = cKDTree(uc)
            y0_, x0_ = uc.min(axis=0) - reach
            y1_, x1_ = uc.max(axis=0) + reach
            b0 = overlaps(u)
            cand = []
            for v in list(routed):
                if v == u or netof(v) == netof(u):
                    continue
                vc = cells_xy(v)
                if not len(vc):
                    continue
                m = (vc[:, 0] >= y0_) & (vc[:, 0] <= y1_) & (vc[:, 1] >= x0_) & (vc[:, 1] <= x1_)
                if m.any() and tree_u.query_ball_point(vc[m], reach, return_length=True).any():
                    cand.append(v)
            # exact blame: v is a blocker when taking its stamps out lowers u's overlap
            blockers = []
            for v in cand:
                apply_stamps(v, -1)
                if overlaps(u) < b0:
                    blockers.append(v)
                apply_stamps(v, +1)
            # keep only true blockers: removing them must clear u's overlaps
            if blockers and len(blockers) <= 5 and all(rips[v] < 4 for v in blockers):
                for v in blockers:
                    uncommit(v)
                if overlaps(u) == 0:
                    for v in blockers:
                        rips[v] += 1
                        queue.append(v)
                        unrouted_u.pop(v, None)
                    ripped += len(blockers)
                    unrouted_u.pop(u, None)
                    continue
                # could not clear: put the blockers back (rerouted as they were) and leave u as it is
                for v in blockers:
                    paths_v, rem_v = route_unit(v, state["pres"])
                    commit(v, paths_v)
        print(f"srr: steps {steps}, routed hard {fixed_ok}, ripped {ripped}, queue left {len(queue)}; "
              f"overlapping {sum(1 for u in routed if overlaps(u))}, unrouted {len(unrouted_u)}", flush=True)
        # anything ripped and never re-queued successfully must not be left uncommitted silently
        for u in units:
            if u not in routed:
                paths, rem = route_unit(u, state["pres"])
                commit(u, paths)
                if rem:
                    unrouted_u[u] = len(rem)
    phase("srr", t_srr)

    def pour_guard(emitted, until):
        """pfr2-up pour guard (A/B: power-group open joins 164 -> 188, all GND): a GND pad group whose only link to
        the In1 / In4 plane is an OUTER GND pour (no own via / plated hole) is cut off when the refill pulls the pour
        back from new foreign copper around it. Every such group with new foreign copper within POUR_GUARD_MM of a pad
        on that pad's layer gets its own drop via (hard occupancy + exact check, via policy applies) - best effort, in
        the time left before 97 % of --budget; nothing is counted unrouted. Each guard is a PAIR of drop vias within
        qa_layout_quality.VIA_SITE_MM of each other (GND uses 0.45 / 0.20 vias: one cannot carry the GND budget -
        VIA-CURRENT) at sites without a via-policy cost (no VIA-INPAD / VIA-PADEDGE); a group that cannot get both
        gets none."""
        t_g = time.time()
        g = name2id.get("GND")
        if g is None or g not in todo:
            return
        subs, seen_ = [], set()
        for k, it in cu.items.items():
            if it["net"] != g or k in seen_ or it["kind"] == "zone":
                continue
            comp, st = set(), [k]
            while st:
                u_ = st.pop()
                if u_ in comp:
                    continue
                comp.add(u_)
                st += [w_ for w_ in adj[u_] - comp if not (cu.items[w_]["kind"] == "zone" and w_[2] in OUTER)]
            seen_ |= comp
            if any(cu.items[u_]["kind"] == "zone" or cu.items[u_]["kind"] == "via" or
                   (cu.items[u_]["kind"] == "pad" and cu.items[u_]["rec"]["drill"]) for u_ in comp):
                continue
            if any(cu.items[u_]["kind"] == "pad" for u_ in comp):
                subs.append(comp)
        newc = defaultdict(list)                 # outer layer -> new copper (foreign, GND)
        for u, (trs, vis) in emitted.items():
            for t in trs:
                if t["layer"] in OUTER and t["s"] != t["e"]:
                    newc[t["layer"]].append((LineString([t["s"], t["e"]]).buffer(t["w"] / 2), netof(u) == g))
            for v in vis:
                for L in OUTER:
                    newc[L].append((Point(v["x"], v["y"]).buffer(v["d"] / 2), netof(u) == g))
        for n_ in out_tracks:
            for t in out_tracks[n_]:
                if t["layer"] in OUTER and t["s"] != t["e"]:
                    newc[t["layer"]].append((LineString([t["s"], t["e"]]).buffer(t["w"] / 2), n_ == g))
        trees = {L: STRtree([x[0] for x in lst]) for L, lst in newc.items() if lst}
        risk = []
        for comp in subs:
            dmin, own_new = 99.0, False
            for u_ in comp:
                if cu.items[u_]["kind"] != "pad":
                    continue
                for L, gp in cu.items[u_]["geo"].items():
                    if L not in trees:
                        continue
                    for i in trees[L].query(gp.buffer(POUR_GUARD_MM)):
                        geo, is_g = newc[L][i]
                        d_ = geo.distance(gp)
                        if is_g and d_ < 1e-6:
                            own_new = True      # this run already joined the group with new GND copper
                        elif not is_g:
                            dmin = min(dmin, d_)
            if dmin < POUR_GUARD_MM and not own_new:
                risk.append((dmin, comp))
        risk.sort(key=lambda r: r[0])
        made = tried = 0
        for dmin, comp in risk:
            if until is not None and time.time() > until:
                print(f"budget: pour guard stopped after {tried} of {len(risk)}", flush=True)
                break
            tried += 1
            u = ("guard", g, tried)
            done = False
            for pad_ in (1.5, 3.0):
                win = bbox_of(comp, pad_)
                L_ = legality(g, win)
                if L_["pv"] is None or not L_["pv"].any():
                    continue
                src = comp_mask(comp, win)
                cache[u] = (win, L_, [src], np.zeros_like(src))
                free = (L_["vpen"] == 0) if L_.get("vpen") is not None else True

                def sites(near=None):
                    pv_ = L_["pv"] & L_["vok"] & ~hole_block[win[0]:win[2], win[1]:win[3]] & free
                    if near is not None:                # the pair's second site: 0.6 .. VIA_SITE_MM - 0.1 from the first
                        yy_, xx_ = np.ogrid[0:win[2] - win[0], 0:win[3] - win[1]]
                        d2 = ((yy_ - near[0]) ** 2 + (xx_ - near[1]) ** 2) * res * res
                        pv_ = pv_ & (d2 >= 0.6 ** 2) & (d2 <= (VIA_SITE_MM - 0.1) ** 2)
                    t_ = np.zeros_like(src)
                    for li in range(len(RL)):
                        t_[li] = pv_
                    return t_

                def one(src_, near=None):
                    tgt = sites(near)
                    for attempt in range(4):
                        if not tgt.any():
                            return None
                        path = run_astar(g, L_, win, src_, tgt, drop=True)
                        if path is None:
                            return None
                        tr, vi = emit(g, L_, win, path, drop_via=True)
                        bad = exact_fix(g, tr, vi)
                        if not bad:
                            return path, tr, vi
                        veto(L_, win, bad)
                        tgt = sites(near)
                    return None
                hard_state["on"] = True
                try:
                    r1 = one(src)
                    r2 = None
                    if r1 is not None:
                        p1 = r1[0]
                        src2 = src.copy()
                        src2[p1[0], p1[1], p1[2]] = True
                        r2 = one(src2, (int(p1[1][-1]), int(p1[2][-1])))
                    if r1 is not None and r2 is not None:
                        tr, vi = r1[1] + r2[1], r1[2] + r2[2]
                        ex_add(g, tr, vi)
                        ex_rebuild(set(ALL_LAYERS))
                        emitted[u] = (tr, vi)
                        commit(u, [r1[0], r2[0]])
                        done = True
                finally:
                    hard_state["on"] = False
                if done:
                    break
            made += done
        print(f"pour guard: {len(subs)} pour-only GND pad groups, {len(risk)} at risk, {made} drop-via pairs added, "
              f"{time.time() - t_g:.0f}s ({time.time() - t0:.0f}s)", flush=True)

    def rescue(pieces, kept, emitted, uprio, until):
        """pfr2-up exact rescue (router-exp: the greedy keep dropped 73 paths, raw unrouted 104 -> 266): every unit
        that lost a path is re-joined ONE join at a time against the kept copper - hard occupancy (no other unit's halo)
        AND the exact shapely check of each new path, veto + retry; accepted copper joins the exact index at once."""
        t_r = time.time()
        kept_k = defaultdict(set)
        for i in kept:
            kept_k[pieces[i][0]].add(pieces[i][1])
        lost = sorted({pieces[i][0] for i in range(len(pieces)) if i not in kept}, key=uprio)
        for u in lost:                           # occupancy = the kept paths only (dropped paths free their space)
            if u in routed:
                pa = routed[u]["paths"]
                uncommit(u)
                commit(u, [p_ for k, p_ in enumerate(pa) if k in kept_k[u]])
        closed = opened = 0
        n_done = 0
        for u in lost:
            if until is not None and time.time() > until:
                print(f"budget: rescue stopped after {n_done} of {len(lost)} units", flush=True)
                break
            n_done += 1
            n = netof(u)
            win, L_ = cache[u][0], cache[u][1]
            paths = list(routed[u]["paths"]) if u in routed else []
            before = unrouted_u.get(u, 0)
            new_paths = []

            def exact_join(src, tgt, drop):
                for attempt in range(4):
                    path = run_astar(n, L_, win, src, tgt, drop=drop)
                    if path is None:
                        return None
                    dv = drop and not bool(cache[u][3][path[0][-1], path[1][-1], path[2][-1]])
                    tr, vi = emit(n, L_, win, path, drop_via=dv)
                    bad = exact_fix(n, tr, vi)
                    if not bad:
                        ex_add(n, tr, vi)
                        ex_rebuild(set(ALL_LAYERS) if vi else {t["layer"] for t in tr})
                        e_ = emitted.setdefault(u, ([], []))
                        e_[0].extend(tr)
                        e_[1].extend(vi)
                        new_paths.append(path)
                        return path
                    veto(L_, win, bad)
                    if drop:
                        pv = L_["pv"] & L_["vok"] & ~hole_block[win[0]:win[2], win[1]:win[3]]
                        for li in range(len(RL)):
                            tgt[li] = pv | (cache[u][3][li] & L_["tok"][li])
                return None
            uncommit(u)
            hard_state["on"] = True
            try:
                if is_drop(u):
                    left = 0
                    if not paths:
                        masks = cache[u][2]
                        tgt = np.zeros_like(masks[0])
                        pv = L_["pv"] & L_["vok"] & ~hole_block[win[0]:win[2], win[1]:win[3]]
                        for li in range(len(RL)):
                            tgt[li] = pv | (cache[u][3][li] & L_["tok"][li])
                        left = 0 if exact_join(masks[0], tgt, True) is not None else 1
                else:
                    masks = cache[u][2]
                    items = list(masks)
                    for ls, yy, xx in paths:
                        pm = np.zeros_like(masks[0])
                        pm[ls, yy, xx] = True
                        items.append(pm)
                    par_ = list(range(len(items)))

                    def find(x):
                        while par_[x] != x:
                            par_[x] = par_[par_[x]]
                            x = par_[x]
                        return x
                    for pi, (ls, yy, xx) in enumerate(paths):
                        idx = len(masks) + pi
                        for (l_, y_, x_) in ((ls[0], yy[0], xx[0]), (ls[-1], yy[-1], xx[-1])):
                            for j, m_ in enumerate(items):
                                if j != idx and m_[l_, y_, x_]:
                                    par_[find(idx)] = find(j)
                    grp = {}
                    for j, m_ in enumerate(items):
                        r_ = find(j)
                        grp[r_] = (grp[r_] | m_) if r_ in grp else m_.copy()
                    tree = grp.pop(find(0))
                    rem = list(grp.values())
                    left = 0
                    while rem:
                        tgt = np.logical_or.reduce(rem)
                        path = exact_join(tree, tgt, False)
                        if path is None:
                            left += 1
                            tree = rem.pop(0)
                            continue
                        ls, yy, xx = path
                        hi = next(k for k, g_ in enumerate(rem) if g_[ls[-1], yy[-1], xx[-1]])
                        tree = tree | rem.pop(hi)
                        tree[ls, yy, xx] = True
            finally:
                hard_state["on"] = False
            commit(u, paths + new_paths)
            if left:
                unrouted_u[u] = left
                exact_fail_u[u] = min(exact_fail_u.get(u, 0), left)
            else:
                unrouted_u.pop(u, None)
                exact_fail_u.pop(u, None)
            closed += max(0, before - left)
            opened += max(0, left - before)
        print(f"rescue: {n_done} of {len(lost)} units, joins closed {closed} (reopened {opened}), "
              f"{time.time() - t_r:.0f}s ({time.time() - t0:.0f}s)", flush=True)

    # exact check of every unit against everything (incl. the other new copper); veto + re-negotiate.
    # pfr2-up: the rounds run under the budget clock (re-negotiation only until 80 % of --budget, then straight to the
    # greedy keep + exact rescue, done by 95 %), and every round writes a LEGAL checkpoint plan (the units without
    # violations) so a variant killed at its timeout still hands back its best legal plan (router-exp v0 lost its whole
    # output overrunning the 1500 s kill in the third exact round).
    base_len = {L: len(v) for L, v in ex_obs.items()}
    emitted, bad_u = {}, {}
    B_ = a.budget

    def late(frac):
        return bool(B_) and time.time() - t0 > frac * B_
    t_ex = time.time()
    for rnd in range(0 if a.no_exact else 3):
        emitted = {u: emit_unit(u) for u in routed}
        for L in list(ex_obs):
            del ex_obs[L][base_len.get(L, 0):]
        for u, (trs, vis) in emitted.items():
            ex_add(netof(u), trs, vis)
        ex_rebuild()
        bad_u = {}
        for u, (trs, vis) in emitted.items():
            b = exact_fix(netof(u), trs, vis)
            if b:
                bad_u[u] = b
        print(f"exact round {rnd}: units with violations {len(bad_u)} "
              f"{[nets[netof(u)]['name'] for u in list(bad_u)[:8]]} ({time.time() - t0:.0f}s)", flush=True)
        write_plan({u: e for u, e in emitted.items() if u not in bad_u}, set(bad_u), f"exact round {rnd}")
        if not bad_u:
            break
        if rnd == 2 or (a.exact_clock and late(0.80)) or (a.det and rnd >= a.det_exact_rounds):
            if rnd < 2:
                print(f"budget: exact re-negotiation stopped after round {rnd} ({time.time() - t0:.0f}s)", flush=True)
            # keep the largest conflict-free set of PATHS (one path = one join of a unit's tree; a big power tree no
            # longer loses all its joins to one conflict); priority power, then drops, then bigger nets
            pieces = []                          # (unit, path index, tracks, vias)
            for u in emitted:
                n_ = netof(u)
                win, L_ = cache[u][0], cache[u][1]
                for k, path in enumerate(routed[u]["paths"]):
                    tr, vi = emit(n_, L_, win, path, drop_via=is_drop(u) and not drop_on_copper(u, *path))
                    pieces.append((u, k, tr, vi))
            for L in list(ex_obs):
                del ex_obs[L][base_len.get(L, 0):]
            for u, k, tr, vi in pieces:
                ex_add(netof(u), tr, vi)
            ex_rebuild()
            partner = {}
            for i, (u, k, tr, vi) in enumerate(pieces):
                ps = set()
                if exact_fix(netof(u), [dict(t) for t in tr], [dict(v) for v in vi], ps):
                    partner[i] = ps
            negp = set(neg_power)

            def uprio(u):
                return (0 if netof(u) in negp else 1 if is_drop(u) else 2, -sum(len(c) for c in todo[netof(u)]))
            prio = sorted(range(len(pieces)), key=lambda i: uprio(pieces[i][0]) + (pieces[i][1],))
            net_pieces = defaultdict(list)
            for i, (u, k, tr, vi) in enumerate(pieces):
                net_pieces[netof(u)].append(i)
            kept, dropped = set(), set()
            for i in prio:
                ps = partner.get(i, set())
                fixed_hit = any(pn not in net_pieces for pn in ps)
                if fixed_hit or any(j in kept for pn in ps for j in net_pieces[pn] if j != i):
                    dropped.add(i)
                else:
                    kept.add(i)
            # confirm on the kept set alone
            for L in list(ex_obs):
                del ex_obs[L][base_len.get(L, 0):]
            for i in kept:
                u, k, tr, vi = pieces[i]
                ex_add(netof(u), tr, vi)
            ex_rebuild()
            still = {i for i in kept if exact_fix(netof(pieces[i][0]), pieces[i][2], pieces[i][3])}
            kept -= still
            dropped |= still
            emitted = defaultdict(lambda: ([], []))
            for i in kept:
                u, k, tr, vi = pieces[i]
                emitted[u][0].extend(tr)
                emitted[u][1].extend(vi)
            emitted = dict(emitted)
            for i in dropped:
                u = pieces[i][0]
                exact_fail_u[u] += 1
                unrouted_u[u] = unrouted_u.get(u, 0) + 1
            print(f"greedy keep (paths): kept {len(kept)}, deferred {len(dropped)} of {len(pieces)} "
                  f"({time.time() - t0:.0f}s)", flush=True)
            if still:                            # 'still' pieces were exact-checked against a superset: re-confirm
                for L in list(ex_obs):
                    del ex_obs[L][base_len.get(L, 0):]
                for u, (trs, vis) in emitted.items():
                    ex_add(netof(u), trs, vis)
                ex_rebuild()
            write_plan(emitted, set(), "greedy keep")
            phase("exact + keep", t_ex)
            t_ex = time.time()
            if a.rescue and dropped:
                rescue(pieces, kept, emitted, uprio, (t0 + 0.95 * B_) if B_ else None)
                phase("rescue", t_ex)
                t_ex = time.time()
            break
        for u, b in bad_u.items():
            veto(cache[u][1], cache[u][0], b)
        negotiate(list(bad_u), a.det_exact_passes if a.det else 4,
                  until=(t0 + 0.80 * B_) if (B_ and a.exact_clock) else None)
    phase("exact + keep", t_ex)
    t_fin = time.time()
    if a.no_exact:
        emitted = {u: emit_unit(u) for u in routed}
    if a.pour_guard and not a.no_exact:
        pour_guard(emitted, (t0 + 0.97 * B_) if B_ else None)
    overlapping = sorted({nets[netof(u)]["name"] for u in routed if overlaps(u)})
    ov_cells = []
    for u in list(routed):
        apply_stamps(u, -1)
        for (li, ys, xs, kind) in routed[u]["cells"]:
            if kind in ("t", "n"):
                m = occ_t[li, ys, xs] > 0
                for y_, x_ in list(zip(ys[m], xs[m]))[::10]:
                    xm, ym = grid.mm(x_, y_)
                    ov_cells.append([round(xm, 2), round(ym, 2), RL[li], nets[netof(u)]["name"]])
        apply_stamps(u, +1)
    for u, (trs, vis) in emitted.items():
        out_tracks[netof(u)] += trs
        out_vias[netof(u)] += vis
    for u, v in unrouted_u.items():
        unrouted[netof(u)] = unrouted.get(netof(u), 0) + v
    for u in exact_fail_u:
        exact_fail[netof(u)] += exact_fail_u[u]
    tracks, n_dup = dedup([t for n in out_tracks for t in out_tracks[n]])
    print(f"dedup: {n_dup} duplicate / covered tracks dropped", flush=True)
    vias = [{k: v for k, v in x.items() if k != "cell"} for n in out_vias for x in out_vias[n]]
    out = {"geom": a.geom, "board_sha256": G["sha256"], "res": res, "margin": margin, "tracks": tracks, "vias": vias,
           "unrouted": {nets[n]["name"]: v for n, v in unrouted.items()}, "overlapping_nets": overlapping,
           "exact_fail": {nets[n]["name"]: v for n, v in exact_fail.items()},
           "fail_detail": fail_detail + [{"net": nets[netof(u)]["name"], "left": v} for u, v in sig_fail.items()],
           "neck_boxes": neck_boxes, "overlap_cells": ov_cells, "checkpoint": "final",
           "seconds": round(time.time() - t0, 1)}
    out["tidy"] = dict(tidy_stat)
    json.dump(out, open(a.out + ".tmp", "w"), indent=1)
    os.replace(a.out + ".tmp", a.out)
    print(f"tidy: {dict(tidy_stat)}", flush=True)
    print(f"reachability skips: {dict(skip_stat)}; astar {dict(astat)}", flush=True)
    phase("finish", t_fin)
    PH["total"] = round(time.time() - t0, 1)
    print(f"phases: {json.dumps(PH)}", flush=True)
    print(f"tracks {len(tracks)}, vias {len(vias)}, unrouted {out['unrouted']}, overlapping {overlapping}, "
          f"exact_fail {out['exact_fail']}", flush=True)


if __name__ == "__main__":
    main()
