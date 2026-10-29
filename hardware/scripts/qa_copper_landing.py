# ported from din8r-chassis-thermal/scripts/qa_copper_landing.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/qa_copper_landing.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN).
"""Copper landing gate: every pad is reached by its copper, and every trace end lands (owner rule 2026-10-04).

CT adaptation (2026-10-17): one board kind ("main", 4 layers); POUR_NETS / FORCE_NETS from scripts/board_const.py
(GND / PRTN / VSS planes + the HW-ADVQA2 flyback-cell pours; no force copper); the TRACK-WIDTH budget is CT's
scripts/current_budget.py (basis "budget-path"); the parent's MAIN via-intent manifest (qa_copper_retention, seven
reviewed DIN-8R vias) does not apply - VIA-BARE reports the raw heuristic; TRACK-JOG protects CT's differential pairs
(Ethernet MDI / PHY, USB) by name instead of the parent's HV / Kelvin / MDI netclasses. Everything else is the parent's
check, constant for constant.

Trigger (parent): on the UI B8 work board, a mounting-hole move shifted D1 by 1.7 mm. Its +5V_UI trace was left ending
1.7 mm short of the cathode pad, under the diode body. Only D1's heat-spreader pour still joined them, so KiCad
connectivity and DRC reported nothing. Owner: "It is NEVER acceptable to have errors like an unconnected pad or trace
happen without triggering a serious error", and "Make sure BOTH the unconnected PAD and the short/loose trace are well
captured in testing. Not either/or."

Each check FAILs on its own. A zone fill never stands in for a trace that should reach a pad:
  PAD-OPEN   KiCad connectivity over the stored fills (the board as fabricated): an unconnected item, or a pad on a
             multi-pad net that shares no copper cluster with any other pad of its net.
  PAD-LAND   A pad on a routed net (not in POUR_NETS) with no same-net track / arc or via touching its copper.
  POUR-PAD   A pad on a POUR_NETS net with no track / arc / via landing and no own-net fill touching it.
  TRACK-END  Loose track copper, from two independent detectors; either one firing FAILs. (1) KiCad's own
             TestTrackEndpointDangling (the DRC track_dangling test). (2) Anchored-leaf pruning: ends of different tracks
             within each other's copper are one joint (a track's own two ends never merge), and an end on another track's
             copper is a T-joint. A via is a CONNECTOR, not an end: it joins track copper at endpoints or midspan on
             every layer it spans, and it
             anchors only if a same-net pad touches it or (POUR_NETS) its own net's fill reaches it on one of its layers
             (owner 2026-10-05: a trace into a via that connects to nothing else and lands in no pour is dangling).
             Leaves that are not on a same-net pad or an anchored via are pruned repeatedly; what goes was on no path
             between anchors. This covers a trace that stops short (also inside a pour), a dangling stub, a trace or
             chain ending in a dead via, and an isolated piece. The one allowance: a POUR_NETS track end fully inside
             its own net's fill on that layer (a stitch into the pour), counted in the report.
  VIA-LAND   A via with landings on fewer than two layers: a same-net track / arc or pad touching it, or for POUR_NETS
             an own-net fill.
  LOOP       Same-net, same-layer track copper touching itself where the copper path between the two pieces is longer
             than LOOP_MM (pads and vias are hubs). That is a closed excursion or a doubled-back run.
  PLANE-ISLAND  A filled pour / plane island (stored fills, as fabricated: whatever the zone's island-removal setting
             left) of >= PLANE_ISLAND_MIN_MM2 whose copper component (its pads, tracks, vias and the other islands it
             reaches through them) is not the net's main component (the one with the most pads). Owner 2026-10-06:
             MAIN's +15V HOLDUP plane (C1200-C1205 + Q20.2) was a whole-plane island never tied to the +15V trunk and
             DRC showed it only as one "unconnected" item among many. Every net with zones is checked (no exclusions:
             an intentional split is a separate net name); smaller off-main islands are counted in info.
CLEAN checks (owner 2026-10-05: "Why am I finding ALL of these quality issues": connected is not clean; each of these
passed every check above on the M1 candidate and the owner found them by eye):
  TRACK-DUP     A zero-length segment, or one lying entirely inside another same-net same-layer segment.
  VIA-PADEDGE   A via whose copper overlaps an SMD pad with its centre outside the pad, by a sliver of less than
                PADEDGE_MIN_FRAC of its disc (an accidental kiss landing with no stub), whose DRILL cuts the pad edge
                ("drilled": review M4 M1, the +15V via 0.075 mm outside Q20.2), or touching a FOREIGN pad (a short). A
                same-net via at least that much on the pad with its drill clear of the pad is an intentional pad-edge
                landing (owner 2026-10-05: "a great use of space if INTENTIONAL"), counted in info, not failed. Root
                cause of the Q20 miss (2026-10-05): the intentional class tested the copper overlap only, and for every
                via the boards use (0.45 / 0.20, 0.6 / 0.3, 0.8 / 0.4) a disc >= 25 % on the pad with its centre
                outside can only happen with the drill breaking the pad edge, so the exemption admitted exactly that
                defect. padedge_class() is the ONE
                definition; it also classes a via that does not touch the pad but sits < PADEDGE_GAP_MM from its edge
                ("gap": no room for a mask dam, solder wicks into the via; review M4 / U4). That class is gated by
                qa_layout_quality VIA-PADGAP and joins this check when PADEDGE_GAP_IN_LANDING is switched on (lead,
                after the UI B8.1 release that runs on the current gate set).
  VIA-BARE      A pour-only via with no demonstrated role under the island/density/reach/fence heuristics: every island it touches keeps >= 2 other inter-layer links without it (and, on a fragment >
                STITCH_MIN_MM2, the qa_layout_quality POUR-STITCH density and, for a net with an inner plane, its
                STITCH_REACH_MM reach to a plane-reaching via: same constants). This flags a FUNCTIONAL REVIEW,
                not proof of redundancy: local signal-return, converter/EMI and thermal roles are not modeled.
                Never delete a via solely to clear this finding. FORCE_NETS current-sharing arrays are counted in info, not gated. A locked
                via is NOT exempt (locked legacy fan-out vias outlived their tracks on MAIN). An EDGE-FENCE via (a
                plane-reaching pour-only via within FENCE_EDGE_MM of the board outline with another one within
                FENCE_PITCH_MM: the GND edge guard, lead 2026-10-06) is kept and counted (info fence_vias). A
                VIA_INTENT via (generator-declared, exact net / position, with its function) is counted in info
                via_intent, not gated.
  VIA-PARTIAL   Any via whose copper disc overlaps the copper of an SMD / connector pad (any net), or of a FOREIGN
                plated-hole pad, on a layer where both have copper while its centre lies outside that pad (review M4
                M1; lead 2026-10-05). A via is either in the land (qa_layout_quality VIA-INPAD rules) or clear of it,
                never half on it. A same-net via merging with a plated-hole annulus (no SMT land, no paste) is counted
                in info partial_pth_same_net (UI B8.1: one GND via kissing the USB-C J2.SH shell annulus). This
                excludes VIA-PADEDGE's intentional class (PARTIAL_ALLOW_INTENTIONAL, owner 2026-10-05; an owner
                call: M4 and UI B8.1 hold no intentional pad-edge via with its drill clear of the pad).
  TRACK-ORPHAN  A connected piece of track copper (joined through vias) touching no pad of its net, e.g. a GND chain
                from a pour-only via into the pour. FORCE_NETS generator copper excepted.
  TRACK-JOG     A staircase step (a segment shorter than JOG_W x its width between two bends of opposite turn) that
                FAILs only where a CLEAN local shortcut exists (owner J1, 2026-10-09), evaluated live on every run from
                the native board, its .kicad_dru and netclasses - no allowlist, UUID manifest or waiver (jog_screen):
                the flagged track and its two neighbours are replaced by straight / 45-start / 45-end paths with the
                far endpoints fixed, the max original width, same layer and net. CLEAN = saves > JOG_SAVE_MM, no hard
                violation (native shapes vs foreign tracks / vias / pads under the JogRules DRU + netclass pair model
                incl. local overrides; board edge; foreign / NPTH holes; no-track rule areas; DRU disallow / width),
                no lost same-net pad / via / track overlap or pad-centre landing, no new clearance cut (> JOG_PLANE_CUT_MM2)
                into any foreign stored fill, and an unprotected net / chain (JOG_PROTECTED_*: HV / fault / MDI / coil
                / chassis classes, ISLAND_HIZ, Kelvin / metering names, the +-1V2_BUF / BUF_GOOD_N lanes, width-
                transition chains). Owner option (a), 2026-10-09: a CLEAN shortcut must also add no new
                qa_layout_quality finding and worsen no existing one (jog_quality: qa_layout_quality's own Board and
                check functions, run live on an in-memory copy of the board with the chain replaced, compared with the
                unmodified board under JOG_LQ_SCHEMA over the findings that name the shortcut's net). A site whose
                every clearance-clean shortcut does is info LAYOUT_QUALITY with the exact new / worsened findings.
                PROTECTED never hides a staircase (2026-10-09, owner: staircase jogs are worse than corners): protected
                sites WITH a clean shortcut that chain (shared tracks, same net / layer) into a run of >=
                JOG_STAIR_MIN_SITES steps FAIL as a protected staircase, to be re-routed (pfr2 / smoothing), never
                auto-shortcut. Every other site is an info.jog_screened record with its exact reason (PROTECTED,
                PLANE_CUT, BLOCKED, NO_SAVING, LAYOUT_QUALITY) and per-shortcut evidence. Uncertainty leans to FAIL: a zero-area touch is
                not a contact, unmodelled relaxations (creepage) are ignored, an unmodelled DRU construct makes the
                check error out (exit 2), and a layout-quality comparison that cannot be evaluated or demonstrate a
                worsening (error, schema drift, a rise within rounding) leaves the shortcut CLEAN.
  PAD-CENTRE    A trace terminating on an SMD pad away from the pad centre (> PAD_CENTRE_TOL): traces run FROM THE
                CENTRE of a pad (owner 2026-10-05), never stop at its edge. FORCE_NETS pads excepted.
  TRACK-WIDTH   Current-carrying copper below its REQUIRED width, except a <= NECK_MM neck-down into a same-net pad no wider
                than the required width (FORCE_NETS: their manifest). Basis current_budget.WIDTH_BASIS: CT "budget-path":
                every net in current_budget.BUDGET (PoE input, flyback primary / secondary, +12V, fan rail and ports,
                VBUS / buck / +3V3, GND) at required_width() = max(class width from the board's .kicad_pro, IPC-2152
                width of its load current at 10 K and of its sustained fault current at 40 K, per outer / inner copper
                weight) on its SUPPLY PATH; a track on a leaf branch leading only to R / C pads (decoupling, pull-ups)
                keeps its class width (budget_leaf_tracks); an unbudgeted current class / rail falls back to its class
                width; a track that alone feeds a current_budget.BRANCHES entry's parts is sized for that branch (none
                on CT rev A); impedance nets at their qualified width (none on CT rev A: no impedance control). KiCad
                DRC never enforces class widths (owner 2026-10-05: "a validation rule that looks at trace width for
                appropriate nets as a part of every cleaning pass").
                FOREIGN-OBJECT NECK (owner LVW-NECKS-20261009, budget bases only, evaluated live, no list): a piece
                below its required width is excused only if ALL hold: (a) it is <= NECK_FOREIGN_MM long; (b) its width
                is >= NECK_FOREIGN_MIN_FRAC x required; (c) the 1-D conduction rise I^2 rho L^2 / (c k A^2) of its
                whole NECK RUN (every touching same-net same-layer piece below its required width: summed length,
                narrowest section, largest gate current max(load, fault) of the pieces' own budget, the gate's
                current_budget.STACKUP thickness; c = 8 only when every run end lands on a same-net track at full
                required width, else 2) is <= NECK_FOREIGN_MAX_DT_K; (d) the piece re-drawn natively at the required
                width on its own centreline Collides with a FOREIGN track / via / pad within its required clearance
                (JogRules pair model, local overrides) + the board DRC epsilon, or its hole within the hole clearance
                + epsilon - a genuine neck. Excused pieces are listed in info width_foreign_necks; a failing
                candidate's row carries its foreign_neck evaluation. Everything else FAILs.
No waivers. KiCad Python: local_run.py qa_copper_landing.py BOARD [--json OUT] [--checks A,B]. Exit 0 PASS, 1 FAIL,
2 error. Releases and adoptions run ALL checks. --checks exists only for a board that is not routed yet (the merged MAIN
build before routing): TRACK-END,VIA-LAND,LOOP prove the part moves left no loose or looped copper. PAD-OPEN and PAD-LAND
then wait for the routed board.
"""
import argparse
import copy
import heapq
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as K  # noqa: E402  (first: tools/pylib shapely for KiCad's Python)
import pcbnew  # noqa: E402
import current_budget as cb  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box  # noqa: E402
from shapely.ops import substring, unary_union  # noqa: E402
from shapely.prepared import prep  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

LOOP_MM = 1.0
# Nets whose pads may connect through a pour (board_const.POUR_NETS: GND / PRTN / VSS planes and pours, and the
# deliberate flyback-cell pours of the HW-ADVQA2 ECO). Every other net is routed: each pad needs a trace or via
# landing; a zone of a routed net (a heat spreader) never stands in for it (the parent's D1 case).
POUR_NETS = {"main": set(K.POUR_NETS)}
HOLE_MM2 = 0.01                                   # a cycle whose copper encloses more open area than this is a ring
# Generator high-current copper (the parent's force pours): none on CT
FORCE_NETS = {"main": set(K.FORCE_NETS)}
JOG_W = 2.0                                       # TRACK-JOG: a step shorter than this many track widths
PAD_CENTRE_TOL = 0.02                             # PAD-CENTRE: a trace end on a pad within this of its centre
PADEDGE_MIN_FRAC = 0.25                          # VIA-PADEDGE: a same-net via this much on the pad is deliberate
PADEDGE_GAP_MM = 0.10                            # VIA-PADEDGE: a via disc this close to an SMD pad edge (no overlap)
PADEDGE_GAP_IN_LANDING = False                   # gap class gated here too (lead switches on after UI B8.1)
PARTIAL_ALLOW_INTENTIONAL = True                 # VIA-PARTIAL: exempt VIA-PADEDGE's intentional class (owner 2026-10-05: "pad-edge vias can be a great use of space if INTENTIONAL"; drilled-edge vias still FAIL)
# Stitch density, shared with qa_layout_quality POUR-STITCH (it imports these): VIA-BARE keeps any via a fragment needs
# to reach max(STITCH_MIN_VIAS, area / STITCH_MM2_PER_VIA) links (B8.1: the two gates demanded and forbade the same vias)
STITCH_MIN_MM2 = 5.0
STITCH_MM2_PER_VIA = 25.0
STITCH_MIN_VIAS = 2
# Stitch REACH, shared the same way (lead 2026-10-05): on a net with an inner plane, VIA-BARE keeps a pour-only via whose
# removal would leave a point of an outer fragment > STITCH_MIN_MM2 farther than STITCH_REACH_MM from every
# plane-reaching via / plated hole (B8.1 cleanup deleted reach-only stitches that POUR-STITCH then demanded)
STITCH_REACH_MM = 5.0
STITCH_REACH_TOL_MM2 = 0.05                     # uncovered area below this is rounding
ISLAND_MIN_MM2 = 1.0                            # VIA-BARE: smaller pad/track-less fill fragments need no stitch
# VIA-BARE edge fence (lead 2026-10-06: a 2.4 GHz board wants its GND edge guard stitched at <= lambda/20 ~ 6 mm, which
# the reach rule alone calls redundant): a pour-only via that reaches the net's inner plane, sits within FENCE_EDGE_MM of
# the board outline (outer edge, slot or cut-out) and has another such via within FENCE_PITCH_MM is a fence via, kept
# and counted (info fence_vias). A lone near-edge via, or one farther in, is judged by the island rules as before.
FENCE_EDGE_MM = 1.5
FENCE_PITCH_MM = 5.0
# VIA-BARE via intent (D-LAYOUT-GATES #8, root-reviewed): generator-declared pour-only vias of the HW-ADVQA2 power
# cell whose function the island heuristics cannot see (current sharing, hot-loop return); exact net / position
# (+-VIA_INTENT_TOL_MM), counted in info via_intent, never a finding. Anything else stays judged.
WHY_12V = 'D6 cathode copper ECO_12V_F <-> ECO_12V_B current site (VIA-CURRENT: 1.673 A / 2.1 A, 2 x 0.3 mm per site)'
WHY_VPP = 'T2.5 / C12 / C13 -> bottom RCD clamp copper (primary RMS 0.985 / 1.817 A, clamp heat path)'
WHY_PRTN = 'flyback cell return -> In1 PRTN plane (hot-loop return, low loop inductance; qa_power_layout loop budget)'
WHY_GNDW = 'W5500 in-body GND site partner of (39.45, 28.9) (VIA-CURRENT: GND budget 1.673 A, 2 x 0.3 mm per site)'
WHY_GNDNE = 'release-candidate GND via pair NE of Q13 (r27p): a 2-via VIA-CURRENT site; deleting either one re-opens VIA-CURRENT and leaves a 9 mm2 B.Cu GND fragment with 0 vias (POUR-STITCH)'
VIA_INTENT = {"main": {}}   # SBC-1: none declared (CT's rows were CT power-cell positions)
VIA_INTENT_TOL_MM = 0.01
# TRACK-WIDTH: the width rule and the per-net current budget live in current_budget.py (ONE source, also read by the
# MAIN router pfr2.py). Basis per board = current_budget.WIDTH_BASIS: MAIN "budget" (required = max(class width,
# IPC-2152 load / fault width)), UI "class" (current classes / rails by name never below the class width, impedance
# classes at it; kept for the B8.1 release, lead 2026-10-05).
CURRENT_CLASSES = cb.CURRENT_CLASSES
IMPEDANCE_CLASSES = cb.IMPEDANCE_CLASSES
RAIL_RE = cb.RAIL_RE
NECK_MM = cb.NECK_MM                              # TRACK-WIDTH: a neck-down this long into a narrower same-net pad
# TRACK-WIDTH foreign-object neck (owner LVW-NECKS-20261009). NECK_FOREIGN_MM: 1.2 mm = the in-plane thermal healing
# length sqrt(k_cu t d / (2 k_FR4)) of the thinnest MAIN copper (inner at the IPC-6012 Class 2 floor, 11.4 um; planes
# d = 0.2 mm away on both faces; k_cu 390, k_FR4 0.3 W/mK) = 1.217 mm, rounded DOWN to 0.1 mm (nominal 15.2 um inner:
# 1.41 mm; 70 um outer: 3.0 mm). A piece no longer than that is a local feature whose ends are held by the adjacent
# full-width copper, the regime of the end-anchored 1-D bound in (c); it also covers the longest owner-cited In4 neck
# piece (1.16 mm). NECK_FOREIGN_MIN_FRAC: 0.94 - even as an infinitely long conductor such a section rises <= ~43.8 K on
# the gate's own IPC-2152 fit where 40 K is required (live: ipc_rise_k), and 6 % lies inside the +-10 % conductor-width
# tolerance the PROCESS screen already carries; the owner-cited necks are >= 0.947. NECK_FOREIGN_MAX_DT_K: owner, 1 K.
# 1-D constants as the owner-cited main_lv_fault_hold_closure necks_vias.py (0.22 K for 1.029 x 1.16 mm at 2.24 A):
# rho(20 C) 1.724e-8 Ohm m, alpha 0.00393 / K at NECK_CU_T_C 125 C (60 C box + 40 K fault rise + margin), k 380 W/mK.
NECK_FOREIGN_MM = 1.2
NECK_FOREIGN_MIN_FRAC = 0.94
NECK_FOREIGN_MAX_DT_K = 1.0
NECK_CU_T_C = 125.0
CU_RHO20 = 1.724e-8
CU_ALPHA = 0.00393
CU_K = 380.0
PLANE_ISLAND_MIN_MM2 = 2.0                        # PLANE-ISLAND: smaller off-main fill islands (thermal slivers) are
                                                  # counted in info (plane_islands_below_min), not failed
CHECKS = ("PAD-OPEN", "PAD-LAND", "POUR-PAD", "TRACK-END", "VIA-LAND", "LOOP", "PLANE-ISLAND",
          "TRACK-DUP", "VIA-PADEDGE", "VIA-PARTIAL", "VIA-BARE", "TRACK-ORPHAN", "TRACK-JOG", "PAD-CENTRE", "TRACK-WIDTH")
mm = pcbnew.ToMM


def board_kind(b):
    """CT has one board kind; a board without copper layers is a tool error"""
    if b.GetCopperLayerCount() < 2:
        raise ValueError(f"board has {b.GetCopperLayerCount()} copper layers")
    return K.KIND


def V(q):
    return pcbnew.VECTOR2I(pcbnew.FromMM(q[0]), pcbnew.FromMM(q[1]))


def P(v):
    return (round(mm(v.x), 4), round(mm(v.y), 4))


def where(q):
    return f"({q[0]:.3f}, {q[1]:.3f})"


def to_shapely(ps):
    polys = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        shell = [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
        holes = [[(mm(h.CPoint(k).x), mm(h.CPoint(k).y)) for k in range(h.PointCount())]
                 for h in (ps.Hole(i, j) for j in range(ps.HoleCount(i)))]
        if len(shell) >= 3:
            polys.append(Polygon(shell, [h for h in holes if len(h) >= 3]).buffer(0))
    return unary_union(polys) if polys else Polygon()


def pad_ref(p):
    return f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"


def padedge_class(pad_poly, centre, radius, same_net, drill_r=None):
    """VIA-PADEDGE: one via disc (centre Point, radius mm; drill radius drill_r when known) against one SMD pad polygon
    on one shared copper layer. -> (class, overlap_mm2, gap_mm); class None = clean (no contact and >= PADEDGE_GAP_MM
    away, or centre in the pad: via-in-pad is qa_layout_quality VIA-INPAD), "intentional" (same net, >=
    PADEDGE_MIN_FRAC of the disc on the pad, drill clear of the pad), "drilled" (same net, that much on the pad, but the
    drill cuts the pad edge), "edge" (same-net sliver), "foreign" (touches a foreign pad), "gap" (no overlap, edge gap
    < PADEDGE_GAP_MM). A caller passing no drill_r (qa_layout_quality VIA-PADGAP) uses only the "gap" class."""
    if pad_poly.contains(centre):
        return None, 0.0, 0.0
    disc = centre.buffer(radius)
    ov = pad_poly.intersection(disc).area
    if ov <= 1e-4:
        gap = max(0.0, pad_poly.distance(centre) - radius)
        return ("gap" if gap < PADEDGE_GAP_MM else None), ov, gap
    if same_net and ov >= PADEDGE_MIN_FRAC * disc.area:
        if drill_r and pad_poly.intersects(centre.buffer(drill_r)):
            return "drilled", ov, 0.0
        return "intentional", ov, 0.0
    return ("edge" if same_net else "foreign"), ov, 0.0


# ---------------------------------------------------------------- TRACK-JOG native rule model (owner J1, 2026-10-09)
# A jog FAILs only where a CLEAN local shortcut exists, evaluated live on every run from the native board, its
# .kicad_dru and its netclasses (no allowlist, no UUID manifest, no waiver). Protected nets / chains are reported in
# info, never shortened by this gate's demand.
# CT: no protected netclasses (its classes are PoE / Power / Rail / Default); the differential pairs are protected by
# name (a one-leg shortcut changes the pair skew - the parent protected its MDI class for the same reason): Ethernet
# MDI (cable side of T1), PHY (T1 <-> W5500 side) and USB D+ / D-. Their staircases still FAIL (JOG_STAIR_MIN_SITES).
JOG_PROTECTED_CLASSES = set()
JOG_PROTECTED_NET_RE = re.compile(r"^(MDI_(TX|RX)_[PN]|PHY_(TX|RX)_[PN]|ETH_(TX|RX)[PN]|USB_(C_)?D[PN])$")
JOG_PROTECTED_NETS = set()
JOG_SAVE_MM = 1e-6                                # a shortcut must save more than this
JOG_STAIR_MIN_SITES = 3                           # PROTECTED jogs with a clean shortcut chained into a run of this
                                                  # many steps are a staircase: FAIL (re-route, never auto-shortcut)
JOG_PLANE_CUT_MM2 = 1e-4                          # new clearance cut into a foreign stored fill above this is a cut
JOG_KEEPOUT_MM2 = 1e-6                            # new copper inside a no-track rule area above this is a violation
_DRU_UNITS = {"mm": 1.0, "mil": 0.0254, "in": 25.4, "um": 0.001}
# constraint types that never bind a new track against another item (via / hole sizes) or are dominated by the
# matching clearance (creepage >= the same-valued clearance on one layer; unmodelled = lenient = the jog FAILs)
_DRU_IGNORED = {"via_diameter", "hole_size", "annular_width", "creepage", "via_count", "length", "skew",
                "diff_pair_gap", "diff_pair_uncoupled", "thermal_relief_gap", "thermal_spoke_width",
                "min_resolved_spokes", "zone_connection", "silk_clearance", "text_height", "text_thickness",
                "courtyard_clearance", "solder_mask_expansion", "solder_paste_abs_margin",
                "solder_paste_rel_margin", "hole_to_hole", "microvia_diameter", "microvia_drill"}


class _KStr(str):
    """KiCad expression string: case-insensitive, wildcard (* ?) equality."""
    __hash__ = str.__hash__

    def __eq__(self, other):
        import fnmatch
        o = str(other).lower()
        s = str.lower(self)
        return fnmatch.fnmatchcase(s, o) or fnmatch.fnmatchcase(o, s)

    def __ne__(self, other):
        return not self.__eq__(other)


def _sexp(text):
    text = "\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#"))
    stack = [[]]
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"|(\()|(\))|([^\s()"]+)', text):
        if m.group(2):
            stack.append([])
        elif m.group(3):
            if len(stack) < 2:
                raise ValueError("DRU: unbalanced ')'")
            x = stack.pop()
            stack[-1].append(x)
        elif m.group(1) is not None:
            stack[-1].append(_KStr(m.group(1)))
        else:
            stack[-1].append(m.group(4))
    if len(stack) != 1:
        raise ValueError("DRU: unbalanced '('")
    return stack[0]


def _dru_value(s):
    m = re.fullmatch(r"([-+]?[0-9]*\.?[0-9]+)(mm|mil|in|um)", str(s).strip())
    if not m:
        raise ValueError(f"DRU value not modelled: {s!r}")
    return float(m.group(1)) * _DRU_UNITS[m.group(2)]


_COND_TOK = re.compile(r"\s*(?:(?P<s>'[^']*')|(?P<op>&&|\|\||==|!=|!|\(|\))|(?P<id>[AB]\.[A-Za-z_]+))")
_COND_FUNCS = {"hasNetclass", "memberOfFootprint", "intersectsFrontCourtyard", "intersectsBackCourtyard",
               "intersectsCourtyard", "intersectsArea", "enclosedByArea"}
_COND_PROPS = {"Type", "Net", "NetName", "Layer"}


def _compile_cond(src):
    """KiCad rule condition -> (code, sides used). Anything outside the modelled subset raises (fail closed)."""
    out, pos, uses, src = [], 0, set(), str(src).strip()
    while pos < len(src):
        m = _COND_TOK.match(src, pos)
        if not m or m.end() == pos:
            raise ValueError(f"DRU condition not modelled at {src[pos:pos + 40]!r}")
        pos = m.end()
        if m.group("s"):
            out.append(f"_KStr({m.group('s')[1:-1]!r})")
        elif m.group("op"):
            out.append({"&&": " and ", "||": " or ", "!": " not "}.get(m.group("op"), m.group("op")))
        else:
            side, attr = m.group("id").split(".")
            uses.add(side)
            if attr in _COND_FUNCS:
                m2 = re.compile(r"\s*\(\s*'([^']*)'\s*\)").match(src, pos)
                if not m2:
                    raise ValueError(f"DRU condition not modelled: {attr} arguments")
                pos = m2.end()
                out.append(f"{side}.f({attr!r}, {m2.group(1)!r})")
            elif attr in _COND_PROPS:
                out.append(f"{side}.p({attr!r})")
            else:
                raise ValueError(f"DRU condition not modelled: {side}.{attr}")
        while pos < len(src) and src[pos].isspace():
            pos += 1
    expr = "".join(out)
    return compile(expr or "True", "<kicad_dru>", "eval"), uses


class _RuleItem:
    """One item as the DRU expressions see it."""

    def __init__(self, env, kind, net_code, net_name, classes, layer, ref=None, geo=None, layers=()):
        self.env, self.kind, self.net_code, self.net_name = env, kind, net_code, net_name
        self.classes, self.layer, self.ref, self._geo, self.layers = classes, layer, ref, geo, set(layers)

    def geo(self):
        g = self._geo() if callable(self._geo) else self._geo
        self._geo = g
        return g

    def p(self, name):
        if name == "Type":
            return _KStr(self.kind)
        if name == "Net":
            return self.net_code
        if name == "NetName":
            return _KStr(self.net_name)
        return _KStr(self.env.lname(self.layer))

    def f(self, fn, arg):
        if fn == "hasNetclass":
            return any(_KStr(c) == arg for c in self.classes)
        if fn == "memberOfFootprint":
            return self.ref is not None and _KStr(self.ref) == arg
        if fn in ("intersectsFrontCourtyard", "intersectsBackCourtyard", "intersectsCourtyard"):
            sides = {"intersectsFrontCourtyard": ("F",), "intersectsBackCourtyard": ("B",)}.get(fn, ("F", "B"))
            return any(self.geo().intersects(c) for s in sides for c in self.env.courtyards(arg, s))
        areas = self.env.areas(arg)
        if fn == "intersectsArea":
            return any(self.layers & ls and self.geo().intersects(g) for g, ls in areas)
        return any(self.layers & ls and g.buffer(1e-6).contains(self.geo()) for g, ls in areas)     # enclosedByArea


class JogRules:
    """Native pair-rule model for the TRACK-JOG shortcut screen: the board's .kicad_dru (KiCad semantics: the LAST
    matching rule of a constraint type wins, conditions tried both ways round, layer clauses honoured), netclass
    clearances, native local clearance overrides (which take precedence, floored at the board minimum), zone
    clearances for stored fills, board edge / hole clearances. A construct outside the modelled subset raises
    (fail closed: the check errors). An unmodelled clearance relaxation can only make a jog FAIL."""

    def __init__(self, b, pcb):
        self.b, self.lname = b, b.GetLayerName
        ds = b.GetDesignSettings()
        self.min_clear = mm(ds.m_MinClearance)
        self.hole_clear = mm(ds.m_HoleClearance)
        self.edge_clear = mm(ds.m_CopperEdgeClearance)
        self.eps = mm(ds.GetDRCEpsilon())
        self.ns = ds.m_NetSettings
        self.rules = []
        dru = Path(str(pcb)).with_suffix(".kicad_dru")
        if dru.exists():
            self._parse(dru.read_text(encoding="utf-8"))
        self._nc, self._cy, self._ar = {}, {}, {}
        self.max_rule = max([c[1] for r in self.rules for c in r["constraints"] if c[0] == "clearance"] + [0.0])

    def _parse(self, text):
        for node in _sexp(text):
            if not isinstance(node, list) or not node or node[0] != "rule":
                if isinstance(node, list) and node and node[0] == "version":
                    continue
                raise ValueError(f"DRU: unexpected top-level {node!r}")
            rule = {"name": str(node[1]), "layer": None, "cond": None, "uses": set(), "constraints": []}
            for x in node[2:]:
                if not isinstance(x, list) or not x:
                    raise ValueError(f"DRU rule {rule['name']}: unexpected {x!r}")
                if x[0] == "layer":
                    rule["layer"] = str(x[1])
                elif x[0] == "condition":
                    rule["cond"], rule["uses"] = _compile_cond(x[1])
                elif x[0] == "severity":
                    continue
                elif x[0] == "constraint":
                    kind = str(x[1])
                    if kind == "disallow":
                        rule["constraints"].append(("disallow", {str(y) for y in x[2:]}))
                    elif kind in ("clearance", "track_width"):
                        mins = [_dru_value(y[1]) for y in x[2:] if isinstance(y, list) and y[0] == "min"]
                        if mins:
                            rule["constraints"].append((kind, mins[0]))
                    elif kind not in _DRU_IGNORED:
                        raise ValueError(f"DRU constraint not modelled for TRACK-JOG: {kind} ({rule['name']})")
                else:
                    raise ValueError(f"DRU rule {rule['name']}: unexpected clause {x[0]!r}")
            self.rules.append(rule)

    def layer_ok(self, rule, layer):
        sel = rule["layer"]
        if sel is None:
            return True
        outer = layer in (pcbnew.F_Cu, pcbnew.B_Cu)
        if sel == "outer":
            return outer
        if sel == "inner":
            return not outer
        return _KStr(sel) == self.lname(layer)

    def match(self, rule, a, b, layer):
        if not self.layer_ok(rule, layer):
            return False
        if rule["cond"] is None:
            return True
        env = {"_KStr": _KStr, "A": a, "B": b}
        if b is None and "B" in rule["uses"]:
            raise ValueError(f"DRU rule {rule['name']}: single-item constraint reads B")
        return bool(eval(rule["cond"], {"__builtins__": {}}, env))

    def nc_clearance(self, classes):
        key = tuple(classes)
        if key not in self._nc:
            best = None
            for c in classes:
                nc = self.ns.GetNetClassByName(c)
                if nc is not None and nc.HasClearance() and (best is None or nc.GetPriority() < best[0]):
                    best = (nc.GetPriority(), mm(nc.GetClearance()))
            if best is None:
                best = (0, mm(self.ns.GetDefaultNetclass().GetClearance()))
            self._nc[key] = best[1]
        return self._nc[key]

    def clearance(self, a, b, layer, override=None, zone_clear=None):
        """Required copper clearance between new item a and foreign item b on layer (mm)."""
        if override:
            return max(max(override), self.min_clear), "local override"
        val = None
        for r in self.rules:
            for kind, v in r["constraints"]:
                if kind == "clearance" and (self.match(r, a, b, layer) or self.match(r, b, a, layer)):
                    val = (v, r["name"])
        if val is None:
            v = max(self.nc_clearance(a.classes), self.nc_clearance(b.classes), zone_clear or 0.0)
            val = (v, "netclass" if not zone_clear or zone_clear <= v - 1e-9 else "zone clearance")
        return max(val[0], self.min_clear), val[1]

    def single(self, a, layer, width):
        """Disallow / track_width violations of new track a alone."""
        out = []
        for r in self.rules:
            for kind, v in r["constraints"]:
                if kind == "disallow" and "track" in v and self.match(r, a, None, layer):
                    out.append({"kind": "rule disallow", "rule": r["name"]})
        tw = [(v, r["name"]) for r in self.rules for kind, v in r["constraints"]
              if kind == "track_width" and self.match(r, a, None, layer)]
        if tw and width < tw[-1][0] - 1e-6:
            out.append({"kind": "rule track_width", "rule": tw[-1][1], "min_mm": tw[-1][0]})
        return out

    def courtyards(self, ref, side):
        k = (str(ref).lower(), side)
        if k not in self._cy:
            polys = []
            for fp in self.b.GetFootprints():
                if _KStr(fp.GetReference()) == ref:
                    ps = fp.GetCourtyard(pcbnew.F_CrtYd if side == "F" else pcbnew.B_CrtYd)
                    g = to_shapely(ps)
                    if not g.is_empty:
                        polys.append(g)
            self._cy[k] = polys
        return self._cy[k]

    def areas(self, name):
        k = str(name).lower()
        if k not in self._ar:
            self._ar[k] = [(to_shapely(z.Outline()), set(z.GetLayerSet().CuStack())) for z in self.b.Zones()
                           if _KStr(z.GetZoneName()) == name]
        return self._ar[k]


def _arc_line(t, n=48):
    """Polyline through a native arc (start -> end via mid), for indexing / reporting only."""
    import cmath
    a, m, e = (complex(*P(x)) for x in (t.GetStart(), t.GetArcMid() if hasattr(t, "GetArcMid") else t.GetMid(),
                                        t.GetEnd()))
    c = complex(*P(t.GetCenter()))
    r = abs(a - c)
    t0, t1, tm = (cmath.phase(z - c) for z in (a, e, m))

    def norm(x):
        return x % (2 * math.pi)
    sweep = norm(t1 - t0)
    if norm(tm - t0) > sweep:
        sweep -= 2 * math.pi
    pts = [c + r * cmath.exp(1j * (t0 + sweep * k / n)) for k in range(n + 1)]
    return LineString([(z.real, z.imag) for z in pts])


def _edge_lines(b):
    """Edge.Cuts geometry at zero width (as KiCad's edge-clearance test uses it), board and footprint items."""
    out = []
    items = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    for fp in b.GetFootprints():
        items += [d for d in fp.GraphicalItems() if d.GetLayer() == pcbnew.Edge_Cuts]
    for d in items:
        st = d.GetShape()
        if st == pcbnew.SHAPE_T_SEGMENT:
            out.append(LineString([P(d.GetStart()), P(d.GetEnd())]))
        elif st == pcbnew.SHAPE_T_ARC:
            out.append(_arc_line(d, 256))
        elif st == pcbnew.SHAPE_T_CIRCLE:
            out.append(Point(P(d.GetCenter())).buffer(mm(d.GetRadius()), 256).exterior)
        elif st == getattr(pcbnew, "SHAPE_T_RECTANGLE", getattr(pcbnew, "SHAPE_T_RECT", None)):
            x0, y0 = P(d.GetStart())
            x1, y1 = P(d.GetEnd())
            out.append(LineString([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]))
        elif st == pcbnew.SHAPE_T_POLY:
            out.append(to_shapely(d.GetPolyShape()).boundary)
        else:
            raise ValueError(f"TRACK-JOG: Edge.Cuts shape {d.GetShapeStr()} not modelled")
    return out


def jog_screen(b, pcb, sites, tracks):
    """TRACK-JOG CLEAN-shortcut screen (owner J1, 2026-10-09). For each jog (flagged segment + its two neighbours,
    far endpoints fixed, max original width, same layer / net) try straight, 45-start and 45-end. A shortcut is
    CLEAN when it saves length, breaks no hard clearance (foreign tracks / vias / pads with native shapes and the
    JogRules pair model; board edge; foreign / NPTH holes; no-track rule areas; DRU disallow / width rules), loses no
    same-net pad / via / track contact or pad-centre landing, and cuts no new clearance into any foreign stored fill.
    -> per site {"status": "FAIL" (clean shortcut, unprotected) | "PROTECTED" | "PLANE_CUT" | "BLOCKED" |
    "NO_SAVING", ...evidence}."""
    rules = JogRules(b, pcb)
    lname = b.GetLayerName
    eps_iu = b.GetDesignSettings().GetDRCEpsilon()

    def classes_of(item):
        return tuple(x for x in item.GetNetClassName().split(",") if x) or ("Default",)

    objs = []                                     # every copper item, any net (net 0 included)
    per_layer = defaultdict(list)
    holes = []

    def add(kind_, o, layers, geos, ref=None, num=None, override=None):
        rec = {"kind": kind_, "obj": o, "net_code": o.GetNetCode(), "net": o.GetNetname(), "classes": classes_of(o),
               "ref": ref, "num": num, "uuid": o.m_Uuid.AsString(), "override": override, "layers": set(layers)}
        objs.append(rec)
        for L, g in geos.items():
            per_layer[L].append((len(objs) - 1, g))
        return rec

    for t in b.GetTracks():
        lays = list(t.GetLayerSet().CuStack())
        if t.Type() == pcbnew.PCB_VIA_T:
            c = Point(P(t.GetPosition()))
            add("Via", t, lays, {L: c.buffer(mm(t.GetWidth(L)) / 2) for L in lays if t.FlashLayer(L)})
            holes.append((len(objs) - 1, c.buffer(mm(t.GetDrillValue()) / 2), t.GetEffectiveHoleShape()))
        else:
            line = _arc_line(t) if t.Type() == pcbnew.PCB_ARC_T else LineString([P(t.GetStart()), P(t.GetEnd())])
            add("Track", t, lays, {t.GetLayer(): line.buffer(mm(t.GetWidth()) / 2)})
    for fp in b.GetFootprints():
        for p in fp.Pads():
            lays = list(p.GetLayerSet().CuStack())
            geos = {L: to_shapely(p.GetEffectivePolygon(L)) for L in lays if p.FlashLayer(L)}
            add("Pad", p, lays, geos, fp.GetReference(), p.GetNumber(), p.GetClearanceOverrides(None))
            if p.GetDrillSize().x > 0:
                r = mm(min(p.GetDrillSize().x, p.GetDrillSize().y)) / 2
                holes.append((len(objs) - 1, Point(P(p.GetPosition())).buffer(r), p.GetEffectiveHoleShape()))
    for rec in objs:
        rec["proxy"] = _RuleItem(rules, rec["kind"], rec["net_code"], rec["net"], rec["classes"], None, rec["ref"],
                                 None, rec["layers"])
    trees = {L: STRtree([g for _, g in lst]) for L, lst in per_layer.items()}
    hole_tree = STRtree([g for _, g, _ in holes]) if holes else None
    fills, keepouts = defaultdict(list), defaultdict(list)
    for z in b.Zones():
        for L in z.GetLayerSet().CuStack():
            if z.GetIsRuleArea():
                if z.GetDoNotAllowTracks():
                    keepouts[L].append((z.GetZoneName(), to_shapely(z.Outline())))
            elif z.HasFilledPolysForLayer(L):
                g = to_shapely(z.GetFilledPolysList(L))
                if not g.is_empty:
                    zc = z.GetLocalClearance()
                    fills[L].append((z, g, mm(zc) if zc is not None else 0.0,
                                     _RuleItem(rules, "Zone", z.GetNetCode(), z.GetNetname(), classes_of(z), L, None,
                                               g, set(z.GetLayerSet().CuStack()))))
    edges = _edge_lines(b)
    edge_geo = unary_union(edges) if edges else None
    reach = max([rules.max_rule, rules.hole_clear, rules.edge_clear]
                + [rules.nc_clearance(r["classes"]) for r in objs]
                + [zc for lst in fills.values() for _, _, zc, _ in lst]) + 0.05

    def short(rec):
        d = {"kind": rec["kind"].lower(), "net": rec["net"], "uuid": rec["uuid"]}
        if rec["ref"] is not None:
            d["pad"] = f"{rec['ref']}.{rec['num']}"
        return d

    out = []
    for site, idx, fars in sites:
        chain = [tracks[i] for i in idx]
        t0 = chain[1]
        net, L = t0["net"], t0["layer"]
        net_code = t0["obj"].GetNetCode()
        cls = classes_of(t0["obj"])
        w = max(t["w"] for t in chain)
        chain_ids = {t["obj"].m_Uuid.AsString() for t in chain}
        chain_uuids = [t["obj"].m_Uuid.AsString() for t in chain]
        old_cu = unary_union([t["cu"] for t in chain])
        a, e = fars
        paths = [("straight", [a, e])]
        dx, dy = e[0] - a[0], e[1] - a[1]
        s = min(abs(dx), abs(dy))
        sx, sy = (1 if dx >= 0 else -1), (1 if dy >= 0 else -1)
        for name, c in (("45-start", (a[0] + sx * s, a[1] + sy * s)), ("45-end", (e[0] - sx * s, e[1] - sy * s))):
            c = (round(c[0], 6), round(c[1], 6))
            path = [a, c, e]
            if math.dist(c, a) > 1e-6 and math.dist(c, e) > 1e-6 and path not in [x[1] for x in paths]:
                paths.append((name, path))
        protected = []
        hit_cls = sorted(set(cls) & JOG_PROTECTED_CLASSES)
        if hit_cls:
            protected.append("protected netclass " + ",".join(hit_cls))
        if JOG_PROTECTED_NET_RE.match(net):
            protected.append("Kelvin / metering net")
        if net in JOG_PROTECTED_NETS:
            protected.append("protected rail lane")
        if len({round(t["w"], 6) for t in chain}) != 1:
            protected.append("width-transition chain")
        # same-net contacts of the original chain (native shapes), excluding the chain itself
        old_contacts, centres = {}, {}
        for j in (trees[L].query(old_cu.buffer(0.01)) if L in trees else []):
            k, g = per_layer[L][j]
            rec = objs[k]
            if rec["net_code"] != net_code or rec["uuid"] in chain_ids:
                continue
            sh = rec["obj"].GetEffectiveShape(L)
            if any(t["obj"].GetEffectiveShape(L).Collide(sh, 0) for t in chain):
                old_contacts[k] = sh
                if rec["kind"] == "Pad":
                    pc = Point(P(rec["obj"].GetPosition()))
                    if any(t["line"].distance(pc) <= t["w"] / 2 + 1e-6 for t in chain):
                        centres[k] = pc
        cands = []
        for name, path in paths:
            segs = []
            for p0, p1 in zip(path, path[1:]):
                nt = pcbnew.PCB_TRACK(b)
                nt.SetStart(V(p0))
                nt.SetEnd(V(p1))
                nt.SetWidth(pcbnew.FromMM(w))
                nt.SetLayer(L)
                segs.append(nt)
            shapes = [x.GetEffectiveShape(L) for x in segs]
            line = LineString(path)
            new_cu = line.buffer(w / 2)
            new_px = _RuleItem(rules, "Track", net_code, net, cls, L, None, new_cu, {L})
            saving = sum(t["len"] for t in chain) - line.length
            hard, cuts, lost, gained, rule_v = [], [], [], [], []
            margin = None
            for j in (trees[L].query(new_cu.buffer(reach)) if L in trees else []):
                k, g = per_layer[L][j]
                rec = objs[k]
                if rec["uuid"] in chain_ids:
                    continue
                if rec["net_code"] == net_code:
                    if k not in old_contacts and any(sh.Collide(rec["obj"].GetEffectiveShape(L), 0) for sh in shapes):
                        gained.append(short(rec))
                    continue
                rec["proxy"].layer = L
                rec["proxy"]._geo = g
                req, src = rules.clearance(new_px, rec["proxy"], L,
                                           override=[mm(x) for x in (rec["override"],) if x is not None])
                d = g.distance(line) - w / 2
                if margin is None or d - req < margin[0]:
                    margin = (round(d - req, 5), short(rec))
                osh = rec["obj"].GetEffectiveShape(L)
                clr = pcbnew.FromMM(req) - eps_iu
                if clr > 0 and any(sh.Collide(osh, clr) for sh in shapes):
                    hard.append({**short(rec), "required_mm": round(req, 4), "rule": src, "actual_mm": round(d, 4)})
            for k, sh in old_contacts.items():
                if not any(x.Collide(sh, 0) for x in shapes):
                    lost.append(short(objs[k]))
                elif k in centres and line.distance(centres[k]) > w / 2 + 1e-6:
                    lost.append({**short(objs[k]), "centre_landing_lost": True})
            if hole_tree is not None:
                for j in hole_tree.query(new_cu.buffer(rules.hole_clear + 0.05)):
                    k, hg, hs = holes[j]
                    rec = objs[k]
                    if rec["net_code"] == net_code and net_code > 0:
                        continue
                    clr = pcbnew.FromMM(rules.hole_clear) - eps_iu
                    if any(sh.Collide(hs, clr) for sh in shapes):
                        hard.append({**short(rec), "hole": True, "required_mm": rules.hole_clear,
                                     "actual_mm": round(hg.distance(line) - w / 2, 4)})
            if edge_geo is not None:
                d = edge_geo.distance(line) - w / 2
                if d < rules.edge_clear - mm(eps_iu):
                    hard.append({"kind": "board edge", "required_mm": rules.edge_clear, "actual_mm": round(d, 4)})
            added = new_cu.difference(old_cu.buffer(1e-6))
            for zname, poly in keepouts.get(L, ()):
                ar = added.intersection(poly).area
                if ar > JOG_KEEPOUT_MM2:
                    rule_v.append({"kind": "rule area no-tracks", "area": zname, "added_mm2": round(ar, 6)})
            rule_v += rules.single(new_px, L, w)
            for z, g, zc, zpx in fills.get(L, ()):
                if z.GetNetCode() == net_code and net_code > 0:
                    continue
                if g.distance(new_cu) > reach:
                    continue
                req, src = rules.clearance(new_px, zpx, L, zone_clear=zc)
                ar = line.buffer(w / 2 + req).intersection(g).area
                if ar > JOG_PLANE_CUT_MM2:
                    cuts.append({"zone_net": z.GetNetname(), "zone": z.GetZoneName() or None,
                                 "zone_uuid": z.m_Uuid.AsString(), "required_mm": round(req, 4), "rule": src,
                                 "new_cut_mm2": round(ar, 5)})
            cands.append({"type": name, "path": [list(p) for p in path], "width_mm": w, "saving_mm": round(saving, 6),
                          "hard": hard, "plane_cuts": cuts, "lost_contacts": lost, "rule_violations": rule_v,
                          "gained_contacts": gained, "min_hard_margin_mm": margin[0] if margin else None,
                          "limiting": margin[1] if margin else None})
        ok = [c for c in cands if c["saving_mm"] > JOG_SAVE_MM
              and not (c["hard"] or c["plane_cuts"] or c["lost_contacts"] or c["rule_violations"])]
        geo_ok = [c for c in cands if c["saving_mm"] > JOG_SAVE_MM
                  and not (c["hard"] or c["lost_contacts"] or c["rule_violations"])]
        if ok and not protected:
            # preference order (stable: max() picks the same first); jog_quality() takes the first one that adds or
            # worsens no qa_layout_quality finding
            ranked = sorted(ok, key=lambda c: (c["saving_mm"], c["min_hard_margin_mm"] or 0), reverse=True)
            best = ranked[0]
            out.append({"status": "FAIL", "shortcut": {**best, "chain_uuids": chain_uuids, "layer": lname(L),
                                                      "net": net},
                        "clean": [{**c, "chain_uuids": chain_uuids, "layer": lname(L), "net": net} for c in ranked],
                        "candidates": [{k: (v[:6] if isinstance(v, list) and k != "path" else v) for k, v in c.items()}
                                       for c in cands]})
            continue
        if protected:
            st, why = "PROTECTED", "; ".join(protected) + ("; a clean shortcut exists" if ok else "")
        elif geo_ok:
            st, why = "PLANE_CUT", "every contact-preserving, clearance-clean shortcut cuts a foreign stored fill"
        elif not any(c["saving_mm"] > JOG_SAVE_MM for c in cands):
            st, why = "NO_SAVING", "no tested shortcut is shorter"
        else:
            st, why = "BLOCKED", "every shorter shortcut breaks a clearance / keep-out / rule or loses a contact"
        out.append({"status": st, "reason": why, "protected": protected, "chain_uuids": chain_uuids,
                    "clean_shortcut": bool(ok),
                    "candidates": [{k: (v[:6] if isinstance(v, list) and k != "path" else v) for k, v in c.items()}
                                   for c in cands]})
    return out


# TRACK-JOG layout-quality screen (owner option a, 2026-10-09): a shortcut is CLEAN only if it adds no new
# qa_layout_quality finding and worsens no existing one. The findings come from qa_layout_quality itself (its Board and
# RUN check functions, its constants), never a copy. JOG_LQ_SCHEMA only says how two findings of one check are compared:
# check -> (identity fields, {metric: +1 larger is worse | -1 smaller is worse | "set" | "cases"}, ignored fields).
# A changed finding with a field outside the schema, a check without a schema, or any evaluation error is UNEVALUATED,
# which leaves the shortcut CLEAN (the site FAILs): only a demonstrated new / worsened finding excuses a jog.
# Only findings that name the shortcut's net are compared (jog_lq_nets): every qa_layout_quality check reads the tracks
# of the finding's own net(s) only, so a change confined to one net cannot alter another net's finding, while the
# STRtree / list order a removed and added track perturbs can (NECK-SMALLPAD reports the first failing track found).
# Dropping a finding can only make a shortcut look cleaner, never excuse it. An "at" identity matches within
# JOG_LQ_AT_TOL_MM (a joint is reported at its first arm's end; ends within half a width are one joint).
JOG_LQ_AT_TOL_MM = 0.25
# ("sum", lsb): a total re-rounded to lsb after every term (PLANE-SLOT len_mm: round(total + crossing, 2) per track) is
# not monotonic in the exact total. Each term is > the check's minimum term (qa_layout_quality.PLANE_CROSS_MM), so a
# total R holds at most k = min(scope tracks, floor(R / (min term - lsb / 2))) terms and errs by <= k x lsb / 2; a
# rise within the two totals' bound is not demonstrated (UNEVALUATED), only one beyond it is worse.
JOG_LQ_SCHEMA = {
    "VIA-INPAD": (("net", "pad", "pad_net", "layer", "at", "via_d", "pad_wh", "fp", "what"), {}, ()),
    "VIA-PADGAP": (("net", "pad", "pad_net", "layer", "at"), {"gap_mm": -1}, ()),
    "XSTACK": (("parts",), {"pad_pairs": +1}, ()),
    "TRACK-FOLD": (("net", "layer", "at", "what"), {"angle": -1, "overlap_mm": +1}, ()),
    "ACUTE": (("net", "layer", "at", "what"), {"angle": -1}, ()),             # ends: no badness order
    "THREAD": (("part", "fp", "net", "layer", "what"), {"len_mm": +1}, ("at",)),
    "POWER-PAD-CONN": (("pad", "role", "net", "layer", "at", "what", "required_mm"),
                       {"cover": -1, "spokes_mm": -1, "tracks_mm": -1}, ()),
    "VIA-CURRENT": (("net", "at", "vias", "drill"), {"need": +1, "cases": "cases"}, ()),
    "NECK-SMALLPAD": (("net", "pad", "layer", "at"), {}, ()),     # width / across: of the first failing track found
    "POUR-STITCH": (("net", "layer", "at"), {"area_mm2": +1, "vias": -1, "need": +1, "beyond_reach_mm2": +1}, ()),
    "DECAP-LOOP": (("part", "value", "pad", "net", "at", "what"), {"gnd_via_mm": +1, "path_mm": +1}, ()),
    "SERIES-TERM": (("part", "value", "nets", "at", "what"), {"path_mm": +1},
                    ("driver", "nearest_ic_pin", "straight_mm")),
    "XTAL": (("part", "net", "limit", "at", "what"), {"len_mm": +1, "vias": +1, "foreign": "set"}, ()),
    "DIFFPAIR": (("pair",), {}, ()),
    "PLANE-SLOT": (("net", "layer", "what"), {"len_mm": ("sum", 0.01)}, ("at",)),   # per-track round(.., 2) sum
    "FIDUCIAL": (("side",), {"fiducials": -1, "triangle_mm2": -1}, ()),
    "PAD-AXIS": (("pad", "net", "layer", "at"), {"angle": +1}, ()),
    "VIA-HOP": (("net", "at", "b"), {}, ()),
    "PLACE-PINPASSIVE": (("part", "pin", "net"), {}, ()),
    "PLACE-ORIENT": (("part", "kind"), {}, ()),
}
_MISSING = object()


def _lq_module():
    import qa_layout_quality                      # lazy: qa_layout_quality imports this module (QL)
    return qa_layout_quality


class _LoaderView:
    """pcbnew as qa_layout_quality's Board constructor sees it, LoadBoard returning an in-memory board"""

    def __init__(self, board):
        self._board = board

    def LoadBoard(self, path):
        return self._board

    def __getattr__(self, k):
        return getattr(pcbnew, k)


def _lq_json(x):
    return json.loads(json.dumps(x, default=str))


def _lq_key(x):
    return json.dumps(x, sort_keys=True, default=str)


def _lq_num(v):
    return math.inf if v is None else v


def _lq_sum_terms(total, n, min_term, lsb):
    k = n if n is not None else math.inf
    if min_term:
        k = min(k, math.floor(total / (min_term - lsb / 2) + 1e-9))
    return k


def _lq_compare(f, g, spec, sums=None):
    """candidate finding f vs baseline finding g of one identity -> (worse {field: delta}, unknown [field]).
    sums: {"min_term": x, "terms": (baseline scope tracks, candidate scope tracks)} for a ("sum", lsb) metric."""
    ident, metrics, ignored = spec
    worse, unknown = {}, []
    for k in sorted(set(f) | set(g)):
        if k in ident or k in ignored:
            continue
        a, b = g.get(k, _MISSING), f.get(k, _MISSING)
        if a == b:
            continue
        d = metrics.get(k)
        if d is None or a is _MISSING or b is _MISSING:
            unknown.append(k)
        elif d == "set":                                        # {net: [layers]}: any added pair is worse
            if not (isinstance(a, dict) and isinstance(b, dict)):
                unknown.append(k)
                continue
            pa = {(n, x) for n, v in a.items() for x in v}
            add = sorted(f"{n} {x}" for n, v in b.items() for x in v if (n, x) not in pa)
            if add:
                worse[k] = {"added": add}
        elif d == "cases":                                      # VIA-CURRENT cases: amps / need per case
            ca = {c.get("case"): c for c in a} if isinstance(a, list) else None
            cb_ = {c.get("case"): c for c in b} if isinstance(b, list) else None
            if ca is None or cb_ is None:
                unknown.append(k)
                continue
            for name, c in cb_.items():
                o = ca.get(name)
                if o is None:
                    worse[f"{k}.{name}"] = {"added": c}
                    continue
                for m in sorted(set(c) | set(o)):
                    if c.get(m) == o.get(m) or m == "case":
                        continue
                    if m in ("amps", "need") and isinstance(c.get(m), (int, float)) \
                            and isinstance(o.get(m), (int, float)):
                        if c[m] > o[m] + 1e-9:
                            worse[f"{k}.{name}.{m}"] = [o[m], c[m]]
                    else:
                        unknown.append(f"{k}.{name}.{m}")
        elif isinstance(d, tuple) and d[0] == "sum":
            if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
                unknown.append(k)
                continue
            if b - a <= 1e-9:
                continue                                  # not higher: never a demonstrated worsening
            if not sums:
                unknown.append(f"{k} (+{round(b - a, 6)}: a re-rounded sum without a term bound)")
                continue
            lsb, (nb, nc) = d[1], sums["terms"]
            tol = lsb / 2 * (_lq_sum_terms(a, nb, sums.get("min_term"), lsb)
                             + _lq_sum_terms(b, nc, sums.get("min_term"), lsb))
            if b - a > tol + 1e-9:
                worse[k] = [a, b]
            else:
                unknown.append(f"{k} (+{round(b - a, 6)} within the rounding bound {round(tol, 6)})")
        else:
            va, vb = _lq_num(a), _lq_num(b)
            if not (isinstance(va, (int, float)) and isinstance(vb, (int, float))):
                unknown.append(k)
            elif (vb - va) * d > 1e-9:
                worse[k] = [a, b]
    return worse, unknown


def jog_lq_nets(f):
    """the nets a qa_layout_quality finding names"""
    nets = {f.get("net"), f.get("pad_net")}
    for k in ("nets", "pair"):
        if isinstance(f.get(k), list):
            nets |= set(f[k])
    if isinstance(f.get("foreign"), dict):
        nets |= set(f["foreign"])
    return nets - {None}


def _lq_at_close(f, g):
    a, b = f.get("at"), g.get("at")
    if a is None or b is None:
        return a is None and b is None
    try:
        return math.dist(a, b) <= JOG_LQ_AT_TOL_MM
    except (TypeError, ValueError):
        return a == b


def jog_lq_delta(base, cand, net=None, schema=None, sums=None):
    """qa_layout_quality findings {check: [finding]} of the unmodified board (base) and of the board with the shortcut
    (cand) -> {"status": CLEAN | DIRTY (a new or worsened finding) | UNEVALUATED, "new", "worsened", "unevaluable"}.
    Unchanged findings (equal apart from track UUIDs) and removed / improved ones never count. net: compare only the
    findings naming it (see JOG_LQ_SCHEMA). sums: {check: _lq_compare sums} for ("sum", lsb) metrics."""
    schema = JOG_LQ_SCHEMA if schema is None else schema
    if net is not None:
        base = {c: [f for f in lst if net in jog_lq_nets(f)] for c, lst in base.items()}
        cand = {c: [f for f in lst if net in jog_lq_nets(f)] for c, lst in cand.items()}
    out = {"new": [], "worsened": [], "unevaluable": []}
    for chk in sorted(set(base) | set(cand)):
        pool = defaultdict(int)
        for g in base.get(chk, []):
            pool[_lq_key(g)] += 1
        rest_c = []
        for f in cand.get(chk, []):
            k = _lq_key(f)
            if pool[k] > 0:
                pool[k] -= 1
            else:
                rest_c.append(f)
        if not rest_c:
            continue
        left_b = []
        for g in base.get(chk, []):
            k = _lq_key(g)
            if pool[k] > 0:
                pool[k] -= 1
                left_b.append(g)
        spec = schema.get(chk)
        if spec is None:
            out["unevaluable"] += [{"check": chk, "finding": f, "why": "no comparison schema"} for f in rest_c]
            continue
        ident = spec[0]
        fuzzy = "at" in ident
        gb, gc = defaultdict(list), defaultdict(list)
        for g in left_b:
            gb[_lq_key([g.get(x) for x in ident if x != "at"])].append(g)
        for f in rest_c:
            gc[_lq_key([f.get(x) for x in ident if x != "at"])].append(f)
        for k, fs in gc.items():
            gs = gb.get(k, [])
            if len(fs) > len(gs):                         # more findings of this identity than before: new
                out["new"] += [{"check": chk, "finding": f, "baseline_same_identity": gs} for f in fs]
                continue
            for f in fs:
                near = [g for g in gs if not fuzzy or _lq_at_close(f, g)]
                if not near:
                    out["new"].append({"check": chk, "finding": f, "baseline_same_identity": gs})
                    continue
                res = [(g,) + _lq_compare(f, g, spec, (sums or {}).get(chk)) for g in near]
                if any(not w and not u for _, w, u in res):
                    continue                              # no worse than a baseline counterpart (improved)
                hit = next(((g, w) for g, w, u in res if w and not u), None)
                if hit:
                    out["worsened"].append({"check": chk, "finding": f, "baseline": hit[0], "delta": hit[1]})
                else:
                    out["unevaluable"].append({"check": chk, "finding": f, "baseline": near,
                                               "why": "changed fields not comparable (outside the schema / within "
                                                      "rounding): " + ",".join(sorted({x for _, _, u in res for x in u}))})
    out["status"] = "DIRTY" if out["new"] or out["worsened"] else ("UNEVALUATED" if out["unevaluable"] else "CLEAN")
    return out


class JogQuality:
    """qa_layout_quality's own findings on the board and on in-memory copies with one jog chain replaced. Every
    check runs on the whole board, except PLANE-SLOT (by far the slowest): its findings are per (net, layer) sums of
    per-track crossings of fill-derived voids, and a shortcut changes the tracks of exactly one (net, layer), so it runs on
    that (net, layer)'s tracks only, for the baseline and the candidate alike (the other aggregates are unchanged), in
    the baseline order with the new segments in the chain's place."""

    def __init__(self, pcb):
        self.pcb = str(pcb)
        self.LQ = _lq_module()
        if self.LQ.pcbnew is not pcbnew:
            raise RuntimeError("qa_layout_quality does not use this pcbnew module")
        if [k for k, fn in self.LQ.RUN.items() if fn is self.LQ.RUN["PLANE-SLOT"]] != ["PLANE-SLOT"]:
            raise RuntimeError("qa_layout_quality PLANE-SLOT shares its check function: scope restriction invalid")
        self.B0 = self._board(pcbnew.LoadBoard(self.pcb))
        self.base = self._run(self.B0, None)
        self.base_ps = {}

    def _board(self, b):
        LQ = self.LQ
        LQ.pcbnew = _LoaderView(b)
        try:
            return LQ.Board(self.pcb)
        finally:
            LQ.pcbnew = pcbnew

    def _run(self, B, scope, tracks=None):
        """scope None: every check but PLANE-SLOT; scope (net, layer name): PLANE-SLOT on those tracks only (tracks: the
        same tracks in an explicit order; its crossing sum is rounded per track, so the order is kept canonical)"""
        LQ = self.LQ
        fails = {k: [] for k in LQ.CHECKS}
        info = {}
        if scope is None:
            done = {LQ.RUN["PLANE-SLOT"]}
            for c in LQ.CHECKS:
                if LQ.RUN[c] not in done:
                    done.add(LQ.RUN[c])
                    LQ.RUN[c](B, fails, info)
            fails.pop("PLANE-SLOT")
        else:
            view = copy.copy(B)
            view.tracks = [t for t in B.tracks if (t["net"], B.lname(t["layer"])) == scope] if tracks is None else tracks
            LQ.RUN["PLANE-SLOT"](view, fails, info)
            if any((f.get("net"), f.get("layer")) != scope for f in fails["PLANE-SLOT"]):
                raise RuntimeError("PLANE-SLOT finding outside its (net, layer) scope")
            fails = {"PLANE-SLOT": fails["PLANE-SLOT"]}
        return {c: [_lq_json({k: v for k, v in f.items() if k != "uuids"}) for f in lst] for c, lst in fails.items()}

    def evaluate(self, c):
        """c: a clearance-clean shortcut (path, width_mm, chain_uuids, layer, net) -> jog_lq_delta() record"""
        scope = (c["net"], c["layer"])
        if scope not in self.base_ps:
            self.base_ps[scope] = self._run(self.B0, scope)
        n_base = sum((t["net"], self.B0.lname(t["layer"])) == scope for t in self.B0.tracks)
        b = pcbnew.LoadBoard(self.pcb)                # a fresh copy: untouched tracks keep their order
        want = set(c["chain_uuids"])
        chain = [t for t in b.GetTracks() if t.m_Uuid.AsString() in want]
        if len(chain) != len(want) or any(t.GetNetname() != c["net"] for t in chain):
            raise RuntimeError("jog chain not found on the board copy")
        L = b.GetLayerID(c["layer"])
        ni = chain[0].GetNet()
        new_ids = []
        for t in chain:
            b.Remove(t)
            t.thisown = False                         # detached and leaked on purpose: freeing it corrupts the copy
        for p0, p1 in zip(c["path"], c["path"][1:]):
            nt = pcbnew.PCB_TRACK(b)
            nt.SetStart(V(p0))
            nt.SetEnd(V(p1))
            nt.SetWidth(pcbnew.FromMM(c["width_mm"]))
            nt.SetLayer(L)
            nt.SetNet(ni)
            b.Add(nt)
            nt.thisown = False                        # the board owns it now (a Python-side delete would free it twice)
            new_ids.append(nt.m_Uuid.AsString())
        B = self._board(b)
        # PLANE-SLOT tracks in the baseline order, the new segments where the chain was
        mine = {t["obj"].m_Uuid.AsString(): t for t in B.tracks if (t["net"], B.lname(t["layer"])) == scope}
        seq, placed = [], False
        for t in self.B0.tracks:
            if (t["net"], self.B0.lname(t["layer"])) != scope:
                continue
            u = t["obj"].m_Uuid.AsString()
            if u in want:
                if not placed:
                    seq += [mine[x] for x in new_ids]
                    placed = True
                continue
            seq.append(mine[u])
        if len(seq) != len(mine):
            raise RuntimeError("PLANE-SLOT scope order does not cover the candidate's tracks")
        cand = {**self._run(B, None), **self._run(B, scope, seq)}
        res = jog_lq_delta({**self.base, **self.base_ps[scope]}, cand, net=c["net"],
                           sums={"PLANE-SLOT": {"min_term": self.LQ.PLANE_CROSS_MM, "terms": (n_base, len(seq))}})
        res["plane_slot_scope"] = list(scope)
        return res


def _lq_brief(ev):
    """one line per new / worsened finding"""
    out = []
    for x in ev.get("new", []):
        f = x["finding"]
        out.append(f"new {x['check']} " + " ".join(f"{k}={f[k]}" for k in ("pad", "part", "net", "layer", "at",
                                                                       "angle", "len_mm", "path_mm", "what") if k in f))
    for x in ev.get("worsened", []):
        f = x["finding"]
        out.append(f"worse {x['check']} " + " ".join(f"{k}={f[k]}" for k in ("pad", "part", "net", "layer", "what")
                                                       if k in f) + f" {json.dumps(x['delta'], default=str)}")
    return out


def jog_quality(pcb, screen):
    """owner option (a): re-screen every clearance-clean (FAIL) site against qa_layout_quality. The first ranked shortcut
    that is CLEAN or UNEVALUATED stays the FAIL's shortcut; a site whose every one is DIRTY becomes LAYOUT_QUALITY."""
    try:
        jq, err = JogQuality(pcb), None
    except Exception as e:                                # fail closed: nothing excused
        jq, err = None, f"baseline: {e!r}"[:400]
    for res in screen:
        if res["status"] != "FAIL":
            continue
        tried, chosen = [], None
        for c in res.pop("clean"):
            if jq is None:
                ev = {"status": "UNEVALUATED", "error": err}
            else:
                try:
                    ev = jq.evaluate(c)
                except Exception as e:
                    ev = {"status": "UNEVALUATED", "error": repr(e)[:400]}
            tried.append({"type": c["type"], "path": c["path"], "layout_quality": ev})
            if ev["status"] != "DIRTY":
                chosen = {**c, "layout_quality": ev}
                break
        if chosen is not None:
            res["shortcut"] = chosen
            res["layout_quality_tried"] = tried
            continue
        lines = [f"{t['type']}: " + "; ".join(_lq_brief(t["layout_quality"])) for t in tried]
        res.update(status="LAYOUT_QUALITY", protected=[], chain_uuids=res["shortcut"]["chain_uuids"],
                   reason="every clearance-clean shortcut adds or worsens a qa_layout_quality finding: "
                          + " | ".join(lines),
                   layout_quality=tried)
        res.pop("shortcut")
    return screen


# ---------------------------------------------------------------- TRACK-WIDTH foreign-object neck (LVW-NECKS-20261009)
def neck_rise_1d(i_a, length_mm, width_mm, cu_um, anchored=True):
    """1-D conduction bound (no lateral loss: conservative) of a conductor's rise above its end copper, K:
    I^2 rho L^2 / (c k A^2), c = 8 with both ends held by full-width copper, 2 with an end not held."""
    rho = CU_RHO20 * (1 + CU_ALPHA * (NECK_CU_T_C - 20.0))
    a = width_mm * 1e-3 * cu_um * 1e-6
    return i_a ** 2 * rho * (length_mm * 1e-3) ** 2 / ((8.0 if anchored else 2.0) * CU_K * a * a)


def ipc_rise_k(i_a, width_mm, cu_um):
    """rise (K) at which the gate's IPC-2152 fit (current_budget.ipc2152_width_mm) needs exactly width_mm: evidence only"""
    if i_a <= 0 or width_mm <= 0:
        return 0.0
    lo, hi = 1e-3, 1e4
    if cb.ipc2152_width_mm(i_a, hi, cu_um) > width_mm:
        return float("inf")
    for _ in range(200):
        m = math.sqrt(lo * hi)
        if cb.ipc2152_width_mm(i_a, m, cu_um) > width_mm:
            lo = m
        else:
            hi = m
    return hi


class NeckBlockers:
    """TRACK-WIDTH (d): the FOREIGN objects a piece would hit at its required width. The piece is re-drawn natively at
    the required width on its own centreline (round ends, same layer / net); a foreign track / arc / via / pad (any other
    net, net 0 included) blocks it when the native shapes Collide within the required clearance (JogRules: board DRU +
    netclass pair model, local overrides, board minimum) + the board DRC epsilon; a foreign or non-plated hole blocks it
    within the board hole clearance + epsilon. Zone fills are not blockers (a fill yields to the track), nor are the
    board edge or rule areas (not foreign objects). An unmodelled DRU construct raises (fail closed)."""

    def __init__(self, b, pcb):
        self.b = b
        self.rules = JogRules(b, pcb)
        self.eps_iu = b.GetDesignSettings().GetDRCEpsilon()
        self.objs, self.per_layer, self.holes = [], defaultdict(list), []

        def classes_of(item):
            return tuple(x for x in item.GetNetClassName().split(",") if x) or ("Default",)

        def add(kind_, o, layers, geos, ref=None, num=None, override=None):
            rec = {"kind": kind_, "obj": o, "net_code": o.GetNetCode(), "net": o.GetNetname(), "classes": classes_of(o),
                   "ref": ref, "num": num, "uuid": o.m_Uuid.AsString(), "override": override}
            rec["proxy"] = _RuleItem(self.rules, kind_, rec["net_code"], rec["net"], rec["classes"], None, ref, None,
                                     set(layers))
            self.objs.append(rec)
            for L, g in geos.items():
                self.per_layer[L].append((len(self.objs) - 1, g))
            return len(self.objs) - 1
        for t in b.GetTracks():
            lays = list(t.GetLayerSet().CuStack())
            if t.Type() == pcbnew.PCB_VIA_T:
                c = Point(P(t.GetPosition()))
                k = add("Via", t, lays, {L: c.buffer(mm(t.GetWidth(L)) / 2) for L in lays if t.FlashLayer(L)})
                self.holes.append((k, c.buffer(mm(t.GetDrillValue()) / 2), t.GetEffectiveHoleShape()))
            else:
                line = _arc_line(t) if t.Type() == pcbnew.PCB_ARC_T else LineString([P(t.GetStart()), P(t.GetEnd())])
                add("Track", t, lays, {t.GetLayer(): line.buffer(mm(t.GetWidth()) / 2)})
        for fp in b.GetFootprints():
            for p in fp.Pads():
                lays = list(p.GetLayerSet().CuStack())
                geos = {L: to_shapely(p.GetEffectivePolygon(L)) for L in lays if p.FlashLayer(L)}
                k = add("Pad", p, lays, geos, fp.GetReference(), p.GetNumber(), p.GetClearanceOverrides(None))
                if p.GetDrillSize().x > 0:
                    r = mm(min(p.GetDrillSize().x, p.GetDrillSize().y)) / 2
                    self.holes.append((k, Point(P(p.GetPosition())).buffer(r), p.GetEffectiveHoleShape()))
        self.trees = {L: STRtree([g for _, g in lst]) for L, lst in self.per_layer.items()}
        self.hole_tree = STRtree([g for _, g, _ in self.holes]) if self.holes else None
        self.reach = max([self.rules.max_rule, self.rules.hole_clear, self.rules.min_clear]
                         + [self.rules.nc_clearance(r["classes"]) for r in self.objs]) + 0.05

    def at(self, t, req):
        """blocking foreign objects of track record t (qa_copper_landing track dict) at width req (mm)"""
        o, L = t["obj"], t["layer"]
        full = pcbnew.PCB_ARC(self.b) if o.Type() == pcbnew.PCB_ARC_T else pcbnew.PCB_TRACK(self.b)
        full.SetStart(o.GetStart())
        if o.Type() == pcbnew.PCB_ARC_T:
            full.SetMid(o.GetMid())
        full.SetEnd(o.GetEnd())
        full.SetWidth(pcbnew.FromMM(req))
        full.SetLayer(L)
        sh = full.GetEffectiveShape(L)
        net_code = o.GetNetCode()
        cls = tuple(x for x in o.GetNetClassName().split(",") if x) or ("Default",)
        line = t["line"]
        full_cu = line.buffer(req / 2)
        new_px = _RuleItem(self.rules, "Track", net_code, t["net"], cls, L, None, full_cu, {L})
        out = []
        for j in (self.trees[L].query(full_cu.buffer(self.reach)) if L in self.trees else []):
            k, g = self.per_layer[L][j]
            rec = self.objs[k]
            if rec["net_code"] == net_code and net_code > 0:
                continue
            rec["proxy"].layer = L
            rec["proxy"]._geo = g
            clr, src = self.rules.clearance(new_px, rec["proxy"], L,
                                            override=[mm(x) for x in (rec["override"],) if x is not None])
            if sh.Collide(rec["obj"].GetEffectiveShape(L), pcbnew.FromMM(clr) + self.eps_iu):
                d = g.distance(line)
                out.append({"kind": rec["kind"].lower(), "net": rec["net"], "uuid": rec["uuid"],
                            **({"pad": f"{rec['ref']}.{rec['num']}"} if rec["ref"] is not None else {}),
                            "required_mm": round(clr, 4), "rule": src,
                            "gap_at_required_mm": round(d - req / 2, 4), "gap_at_neck_mm": round(d - t["w"] / 2, 4)})
        if self.hole_tree is not None:
            hc = self.rules.hole_clear
            for j in self.hole_tree.query(full_cu.buffer(hc + 0.05)):
                k, hg, hs = self.holes[j]
                rec = self.objs[k]
                if rec["net_code"] == net_code and net_code > 0:
                    continue
                if hc > 0 and sh.Collide(hs, pcbnew.FromMM(hc) + self.eps_iu):
                    d = hg.distance(line)
                    out.append({"kind": rec["kind"].lower() + " hole", "net": rec["net"], "uuid": rec["uuid"],
                                "required_mm": round(hc, 4), "rule": "hole clearance",
                                "gap_at_required_mm": round(d - req / 2, 4), "gap_at_neck_mm": round(d - t["w"] / 2, 4)})
        return sorted(out, key=lambda x: (x["gap_at_required_mm"] - x["required_mm"], x["uuid"]))


def neck_runs(tracks, narrow):
    """NECK RUNS of the below-required pieces narrow ({track idx: required mm}): pieces of one net and layer whose
    copper touches at an end (an end within the other's copper) form one run (union-find). -> {idx: run id}"""
    par = {i: i for i in narrow}

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    idx = sorted(narrow)
    tree = STRtree([tracks[i]["cu"] for i in idx]) if idx else None
    for i in idx:
        t = tracks[i]
        for q in (t["a"], t["e"]):
            for j in tree.query(Point(q)):
                k = idx[j]
                o = tracks[k]
                if k != i and o["net"] == t["net"] and o["layer"] == t["layer"] and \
                        o["line"].distance(Point(q)) <= o["w"] / 2 + 1e-6:
                    par[find(i)] = find(k)
    return {i: find(i) for i in idx}


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, c):
        self.p[self.find(a)] = self.find(c)


def reach_far(isl, links):
    """The part of an outer fill fragment isl farther than STITCH_REACH_MM from every plane link in links ((x, y) of
    plane-reaching vias / plated holes). Shared by VIA-BARE's reach keep rule and by stitch-via placement (the B8.1
    cleanup: placement and pruning must evaluate reach the same way, or they churn)."""
    return isl.difference(unary_union([Point(q).buffer(STITCH_REACH_MM, 16) for q in links])) if links else isl


def reach_lost(isl, others, q):
    """Area of isl that only a plane link at q reaches within STITCH_REACH_MM, given the other links: VIA-BARE keeps a
    pour-only via when this exceeds STITCH_REACH_TOL_MM2."""
    return reach_far(isl, others).intersection(Point(q).buffer(STITCH_REACH_MM, 16)).area


LEAF_PREFIXES = ("R", "C")        # budget-path: pads of these two-terminal parts draw no rail current (pull-up /
                                 # bias resistors, decoupling caps): a branch that serves only them is a leaf


def _net_graph(net, idx, tracks, vias, v_geo, all_pads, pad_poly, fill):
    """one net's copper graph (budget_leaf_tracks / budget_branch_tracks): nodes are joints (track ends joined where they
    touch, split where a track end lands mid-segment), each pad, each via and the net's fills as one node; edges are the
    track pieces. Returns (edges [(u, v, track i)], load nodes, {node: {part refs}}, fill node or None)."""
    from collections import defaultdict as _dd
    import re as _re
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def union(x, y):
        par[find(x)] = find(y)
    ends = [(i, k, tracks[i][k]) for i in idx for k in ("a", "e")]
    ept = STRtree([Point(q) for _, _, q in ends])
    splits = _dd(list)                                  # track i -> [(param, node)] mid-segment landings
    joins = []                                          # (distance, end node, joint end node) end-on-copper contacts
    for i in idx:
        t = tracks[i]
        for k2 in ept.query(t["cu"]):
            j, kk, q = ends[k2]
            if j == i or tracks[j]["layer"] != t["layer"]:
                continue
            d = t["line"].distance(Point(q))
            if d > max(t["w"], tracks[j]["w"]) / 2 + 1e-3:
                continue
            pa = t["line"].project(Point(q))
            if pa <= 1e-3:
                joins.append((round(d, 6), ("j", j, kk), ("j", i, "a")))
            elif pa >= t["line"].length - 1e-3:
                joins.append((round(d, 6), ("j", j, kk), ("j", i, "e")))
            else:
                splits[i].append((pa, ("j", j, kk)))
    # Joints, closest contacts first. A contact that would put BOTH ends of one track into one joint is refused (as the
    # TRACK-END joint graph never merges a track's own two ends): a collinear piece shorter than w/2 (a neck split) has
    # its far end inside its neighbour's copper, and merging it would contract the piece to nothing, dropping it from
    # BRANCHES (budget_branch_tracks). The refused contact is parallel to that track's own edge (the track joins the same
    # two joints), so connectivity and every OTHER track's bridge / far-side test are unchanged; the kept track carries
    # at most the current across the cut it spans, which is what its classification sizes it for. Contraction through
    # a via / pad / fill node below is unchanged (a track wholly inside one keeps the net budget: fail closed).
    own = {("j", i, k): {i} for i in idx for k in ("a", "e")}
    for _, x, y in sorted(joins):
        rx, ry = find(x), find(y)
        if rx == ry or own.get(rx, set()) & own.get(ry, set()):
            continue
        par[rx] = ry
        own[ry] = own.get(rx, set()) | own.get(ry, set())
    load = set()
    zn = ("z", net)
    for vi, v in enumerate(vias):
        if v.GetNetname() != net:
            continue
        for i in idx:
            t = tracks[i]
            if not v.IsOnLayer(t["layer"]):
                continue
            for k in ("a", "e"):
                if v_geo[vi].intersects(Point(t[k])):
                    union(("j", i, k), ("v", vi))
        if any(fill(net, L)[1].intersects(v_geo[vi]) for L in v.GetLayerSet().CuStack()):
            union(("v", vi), zn)
    for pi, p in enumerate(all_pads):
        if p.GetNetname() != net:
            continue
        ref = p.GetParentFootprint().GetReference()
        m = _re.match(r"^[A-Z]+", ref)
        node = ("p", pi)
        find(node)
        if not (m and m[0] in LEAF_PREFIXES):
            load.add(node)
        for L in p.GetLayerSet().CuStack():
            pg = pad_poly(p, L)
            for i in idx:
                t = tracks[i]
                if t["layer"] != L:
                    continue
                for k in ("a", "e"):
                    if pg.distance(Point(t[k])) <= t["w"] / 2 + 1e-3:
                        union(("j", i, k), node)
            if fill(net, L)[1].intersects(pg):
                union(node, zn)
        for vi, v in enumerate(vias):
            if v.GetNetname() == net and any(v.IsOnLayer(L) and v_geo[vi].intersects(pad_poly(p, L))
                                             for L in p.GetLayerSet().CuStack()):
                union(node, ("v", vi))
    for i in idx:
        if fill(net, tracks[i]["layer"])[1].intersects(tracks[i]["cu"]):
            union(("j", i, "a"), zn)
    loads = {find(x) for x in load}
    if zn in par:
        loads.add(find(zn))
    edges = []                                          # (node u, node v, track i)
    for i in idx:
        pts = [find(("j", i, "a"))] + [find(nd) for _, nd in sorted(splits[i])] + [find(("j", i, "e"))]
        for u, v in zip(pts, pts[1:]):
            if u != v:
                edges.append((u, v, i))
    refs = _dd(set)
    for pi, p in enumerate(all_pads):
        if p.GetNetname() == net and ("p", pi) in par:
            refs[find(("p", pi))].add(p.GetParentFootprint().GetReference())
    return edges, loads, refs, (find(zn) if zn in par else None)


def budget_leaf_tracks(b, tracks, vias, v_geo, all_pads, pad_poly, fill):
    """indices of tracks on LEAF branches of their net: copper that leads only to pads of R / C parts (pull-ups,
    decoupling). The net's copper is a graph - nodes are joints (track ends joined where they touch, split where a
    track end lands mid-segment), each pad, each via and the net's fills (planes / pours) as one node; edges are the
    track pieces - and dead ends that are not a load are pruned repeatedly. Loads: pads of every other part and the
    fill node (the rail's distribution). A track is a leaf when all of its pieces were pruned."""
    from collections import defaultdict as _dd
    by_net = _dd(list)
    for i, t in enumerate(tracks):
        by_net[t["net"]].append(i)
    leaf = set()
    for net, idx in by_net.items():
        edges, loads, _, _ = _net_graph(net, idx, tracks, vias, v_geo, all_pads, pad_poly, fill)
        inc = _dd(set)
        for k, (u, v, i) in enumerate(edges):
            inc[u].add(k)
            inc[v].add(k)
        alive = set(range(len(edges)))
        stack = [n for n in inc if len(inc[n]) <= 1 and n not in loads]
        while stack:
            n = stack.pop()
            live = [k for k in inc[n] if k in alive]
            if len(live) > 1 or n in loads:
                continue
            for k in live:
                alive.discard(k)
                u, v, _ = edges[k]
                o = v if u == n else u
                if o not in loads and len([q for q in inc[o] if q in alive]) <= 1:
                    stack.append(o)
        keep = {edges[k][2] for k in alive}
        leaf |= {i for i in idx if i not in keep and any(e[2] == i for e in edges)}
    return leaf


def budget_branch_tracks(kind, tracks, vias, v_geo, all_pads, pad_poly, fill):
    """{track index: BRANCHES entry} for tracks whose far side holds only that branch's parts (current_budget.BRANCHES):
    with the track's pieces removed, its ends fall into >= 2 parts of the net's copper graph; every part but at most one
    (the supply side) must hold no fill node and only pads of the branch's parts, and at least one such part must hold
    one of them. A track in a loop (not a bridge), or one whose far side reaches another load or the net's pour, keeps
    the net budget."""
    out = {}
    for net, branches in cb.BRANCHES.get(kind, {}).items():
        idx = [i for i, t in enumerate(tracks) if t["net"] == net]
        if not idx:
            continue
        edges, _, refs, zn = _net_graph(net, idx, tracks, vias, v_geo, all_pads, pad_poly, fill)
        nodes = {n for u, v, _ in edges for n in (u, v)}
        for i in idx:
            mine = [(u, v) for u, v, j in edges if j == i]
            if not mine:
                continue
            par = {}

            def find(x):
                par.setdefault(x, x)
                while par[x] != x:
                    par[x] = par[par[x]]
                    x = par[x]
                return x
            for u, v, j in edges:
                if j != i:
                    par[find(u)] = find(v)
            sides = {find(n) for e in mine for n in e}
            if len(sides) < 2:
                continue
            members = {}
            for n in nodes:
                r = find(n)
                if r in sides:
                    members.setdefault(r, set()).add(n)
            for br in branches:
                parts = set(br["parts"])
                clean, dirty = 0, 0
                for r in sides:
                    ms = members.get(r, set())
                    rs = set().union(*(refs.get(n, set()) for n in ms))
                    if zn in ms or not rs <= parts:
                        dirty += 1
                    elif rs:
                        clean += 1
                if clean and dirty <= 1:
                    out[i] = br
                    break
        # D-LAYOUT-GATES #9a: a "pour_ok" branch also sizes a run (tracks joined end to end on one layer) whose touched
        # pads are only that branch's parts' pads and R / C leaf pads, with at least one branch part, although the pads
        # touch the net's pour (the bridge test above cannot see through the pour node)
        for br in branches:
            if not br.get("pour_ok"):
                continue
            parts = set(br["parts"])
            rp = {}

            def rfind(x):
                rp.setdefault(x, x)
                while rp[x] != x:
                    rp[x] = rp[rp[x]]
                    x = rp[x]
                return x
            for a in idx:
                for c in idx:
                    if c <= a or tracks[a]["layer"] != tracks[c]["layer"]:
                        continue
                    lim = max(tracks[a]["w"], tracks[c]["w"]) / 2 + 1e-3
                    if any(Point(tracks[a][k1]).distance(Point(tracks[c][k2])) <= lim
                           for k1 in ("a", "e") for k2 in ("a", "e")):
                        rp[rfind(a)] = rfind(c)
            comps = {}
            for a in idx:
                comps.setdefault(rfind(a), []).append(a)
            for comp in comps.values():
                rs = set()
                for p in all_pads:
                    if p.GetNetname() != net:
                        continue
                    for a in comp:
                        L = tracks[a]["layer"]
                        if p.IsOnLayer(L) and pad_poly(p, L).distance(tracks[a]["line"]) <= tracks[a]["w"] / 2 + 1e-3:
                            rs.add(p.GetParentFootprint().GetReference())
                            break
                leaf = {r for r in rs if re.match(r"^[A-Z]+", r) and re.match(r"^[A-Z]+", r)[0] in LEAF_PREFIXES}
                if rs & parts and rs <= parts | leaf:
                    for a in comp:
                        out.setdefault(a, br)
    return out


def check(pcb, checks=CHECKS, width_basis=None):
    """width_basis: override current_budget.WIDTH_BASIS for TRACK-WIDTH (reports only; gates use the default)."""
    unknown = set(checks) - set(CHECKS)
    if unknown or not checks:
        raise ValueError(f"unknown / empty checks: {sorted(unknown)}")
    b = pcbnew.LoadBoard(str(pcb))
    kind = board_kind(b)
    pour = POUR_NETS[kind]
    lname = b.GetLayerName
    fails = {k: [] for k in CHECKS}
    info = {}

    # ---------------------------------------------------------------- collect
    pads_by_net, all_pads = defaultdict(list), []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() > 0:
                pads_by_net[p.GetNetname()].append(p)
                all_pads.append(p)
    tracks, vias = [], []
    for t in b.GetTracks():
        if t.GetNetCode() <= 0:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            vias.append(t)
            continue
        a, e = P(t.GetStart()), P(t.GetEnd())
        line = LineString([a, P(t.GetMid()), e]) if t.Type() == pcbnew.PCB_ARC_T else (
            LineString([a, e]) if a != e else Point(a))
        w = mm(t.GetWidth())
        tracks.append({"obj": t, "net": t.GetNetname(), "layer": t.GetLayer(), "a": a, "e": e, "w": w,
                       "len": mm(t.GetLength()), "line": line, "cu": line.buffer(w / 2)})
    zones = defaultdict(list)
    for z in b.Zones():
        if not z.GetIsRuleArea() and z.GetNetCode() > 0:
            zones[z.GetNetname()].append(z)
    fill_cache = {}

    def fill(net, layer):
        k = (net, layer)
        if k not in fill_cache:
            g = unary_union([to_shapely(z.GetFilledPolysList(layer)) for z in zones.get(net, ())
                             if z.IsOnLayer(layer)]) if zones.get(net) else Polygon()
            fill_cache[k] = (g, prep(g))
        return fill_cache[k]

    pad_poly_cache = {}

    def pad_poly(p, layer):
        k = (id(p), layer)
        if k not in pad_poly_cache:
            pad_poly_cache[k] = to_shapely(p.GetEffectivePolygon(layer))
        return pad_poly_cache[k]

    def pbox(p):
        bb = p.GetBoundingBox()
        return box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))

    t_tree = STRtree([t["cu"] for t in tracks])
    p_tree = STRtree([pbox(p) for p in all_pads])
    v_geo = [Point(P(v.GetPosition())).buffer(mm(v.GetWidth(pcbnew.F_Cu)) / 2) for v in vias]
    v_tree = STRtree(v_geo)

    def collide(item, other, layer):
        return item.GetEffectiveShape(layer).Collide(other.GetEffectiveShape(layer), 0)

    # ---------------------------------------------------------------- PAD-OPEN
    b.BuildConnectivity()
    con = b.GetConnectivity()
    con.RecalculateRatsnest()
    n_unconn = con.GetUnconnectedCount(True)
    if n_unconn:
        fails["PAD-OPEN"].append({"what": f"KiCad connectivity reports {n_unconn} unconnected item(s)"})
    multi = {n: ps for n, ps in pads_by_net.items() if len(ps) >= 2 and not n.startswith("unconnected-")}
    for net, ps in multi.items():
        left, clusters = list(ps), []
        while left:
            members = {pad_ref(x) for x in con.GetConnectedItems(left[0]) if x.GetClass() == "PAD"} | {pad_ref(left[0])}
            grp = [x for x in left if pad_ref(x) in members]
            clusters.append(grp)
            left = [x for x in left if pad_ref(x) not in members]
        if len(clusters) > 1:
            clusters.sort(key=len, reverse=True)
            for grp in clusters[1:]:
                fails["PAD-OPEN"].append({"net": net, "pads": [pad_ref(x) for x in grp],
                                          "what": f"not joined to the rest of {net} ({len(clusters[0])} pads)"})

    # ---------------------------------------------------------------- PAD-LAND / POUR-PAD
    for net, ps in multi.items():
        for p in ps:
            bb = pbox(p)
            lays = list(p.GetLayerSet().CuStack())
            landed = any(tracks[i]["net"] == net and p.IsOnLayer(tracks[i]["layer"])
                         and collide(p, tracks[i]["obj"], tracks[i]["layer"]) for i in t_tree.query(bb))
            landed = landed or any(vias[i].GetNetname() == net and any(
                vias[i].IsOnLayer(L) and collide(p, vias[i], L) for L in lays) for i in v_tree.query(bb))
            if landed:
                continue
            in_fill = any(fill(net, L)[1].intersects(pad_poly(p, L)) for L in lays)
            pos = P(p.GetPosition())
            if net in pour:
                if not in_fill:
                    fails["POUR-PAD"].append({"net": net, "pad": pad_ref(p), "at": pos,
                                              "what": "no trace, via or own-net fill reaches this pad"})
            else:
                fails["PAD-LAND"].append({"net": net, "pad": pad_ref(p), "at": pos,
                                          "what": "no trace or via lands on this pad"
                                                  + (" (only a pour touches it)" if in_fill else "")})

    # ---------------------------------------------------------------- joint graph
    # endpoints on the same net / layer within each other's copper are one joint (union-find)
    uf = UF()
    ends = defaultdict(list)                     # (net, layer) -> [(q, w, track idx)]
    for i, t in enumerate(tracks):
        for q in (t["a"], t["e"]):
            ends[(t["net"], t["layer"])].append((q, t["w"], i))
            uf.find((t["layer"], q))
    for (net, layer), lst in ends.items():
        grid = defaultdict(list)
        for q, w, i in lst:
            grid[(int(q[0] // 0.25), int(q[1] // 0.25))].append((q, w, i))
        for (gx, gy), cell in grid.items():
            near = [x for dx in (-1, 0, 1) for dy in (-1, 0, 1) for x in grid.get((gx + dx, gy + dy), ())]
            for q, w, i in cell:
                for q2, w2, i2 in near:
                    # never merge a track's own two ends: a stub shorter than half its width would hide its free end
                    if i2 != i and q2 != q and math.dist(q, q2) <= min(w, w2) / 2:
                        uf.union((layer, q), (layer, q2))

    def J(layer, q):
        return uf.find((layer, q))

    anchor = {}                                   # joint -> "pad X" | "pour-stitch" (vias: see via_anchor below)
    tee = defaultdict(set)                        # track idx -> joints lying on its copper (T-joints)
    via_joints = defaultdict(set)                 # track idx -> via nodes touching its copper, including midspan
    for i, t in enumerate(tracks):
        net, L = t["net"], t["layer"]
        for q in (t["a"], t["e"]):
            j = J(L, q)
            cap = Point(q).buffer(t["w"] / 2)
            for k in p_tree.query(cap):
                p = all_pads[k]
                if p.GetNetname() == net and p.IsOnLayer(L) and pad_poly(p, L).intersects(Point(q)):
                    anchor.setdefault(j, "pad " + pad_ref(p))
            for k in t_tree.query(Point(q)):
                o = tracks[k]
                if k != i and o["net"] == net and o["layer"] == L and o["line"].distance(Point(q)) <= o["w"] / 2 + 1e-6:
                    if J(L, o["a"]) != j and J(L, o["e"]) != j:
                        tee[k].add(j)
            if j not in anchor and net in pour and fill(net, L)[1].contains(cap):
                anchor[j] = "pour-stitch"

    # A true same-layer X crossing is an electrical junction even when neither
    # track has an endpoint there. Register the intersection on both tracks;
    # this is a connector, not an anchor, so open branches remain detectable.
    # Collinear overlaps stay with the duplicate/doubled-copper checks.
    for i, t in enumerate(tracks):
        if t["obj"].GetClass() != "PCB_TRACK":
            continue
        for k in t_tree.query(t["cu"]):
            if k <= i:
                continue
            o = tracks[k]
            if o["obj"].GetClass() != "PCB_TRACK" or o["net"] != t["net"] or o["layer"] != t["layer"]:
                continue
            crossing = t["line"].intersection(o["line"])
            points = [crossing] if crossing.geom_type == "Point" else list(crossing.geoms) if crossing.geom_type == "MultiPoint" else []
            for pt in points:
                q = (round(pt.x, 6), round(pt.y, 6))
                j = J(t["layer"], q)
                for idx, tr in ((i, t), (k, o)):
                    if j not in {J(tr["layer"], tr["a"]), J(tr["layer"], tr["e"])}:
                        tee[idx].add(j)

    def joints(i):
        t = tracks[i]
        return {J(t["layer"], t["a"]), J(t["layer"], t["e"])} | tee.get(i, set()) | via_joints.get(i, set())

    # vias: a via joins every joint it touches, on any of its layers, into one node; that node is an anchor only when a
    # same-net pad touches the via or (POUR_NETS) its own net's fill reaches it. A via reached by nothing but the
    # trace(s) of one dead branch is therefore a leaf like any free end (owner 2026-10-05).
    vuf = UF()
    for i, t in enumerate(tracks):
        net, L = t["net"], t["layer"]
        # A via can join the interior of a track without enclosing either endpoint. Use native copper collision
        # (and its bounding box for arc candidates), not endpoint proximity. This adds a connector, never an anchor;
        # leave both track ends distinct so a real free tail still fails pruning and the native dangling detector.
        for k in v_tree.query(pbox(t["obj"])):
            v = vias[k]
            if v.GetNetname() == net and v.IsOnLayer(L) and collide(v, t["obj"], L):
                via_joints[i].add(("via", k))
                for q in (t["a"], t["e"]):
                    if v_geo[k].intersects(Point(q)):
                        vuf.union(J(L, q), ("via", k))
    via_anchor = {}
    for k, v in enumerate(vias):
        net, lays = v.GetNetname(), list(v.GetLayerSet().CuStack())
        on_pad = next((pad_ref(all_pads[i]) for i in p_tree.query(v_geo[k]) if all_pads[i].GetNetname() == net
                       and any(all_pads[i].IsOnLayer(L) and collide(v, all_pads[i], L) for L in lays)), None)
        if on_pad:
            via_anchor[k] = "via on pad " + on_pad
        elif net in pour and any(fill(net, L)[1].intersects(v_geo[k]) for L in lays):
            via_anchor[k] = "via in own pour"

    def K(j):
        return vuf.find(j)

    anchor_k = {}
    for j, a in anchor.items():
        anchor_k.setdefault(K(j), a)
    for k, a in via_anchor.items():
        anchor_k.setdefault(K(("via", k)), a)

    def kjoints(i):
        return {K(x) for x in joints(i)}

    adj = defaultdict(set)
    for i in range(len(tracks)):
        for j in kjoints(i):
            adj[j].add(i)

    # ---------------------------------------------------------------- TRACK-END: prune unanchored leaves
    deg = {j: len(s) for j, s in adj.items()}
    alive = set(range(len(tracks)))
    stack = [j for j, d in deg.items() if d <= 1 and j not in anchor_k]
    while stack:
        j = stack.pop()
        if j in anchor_k or deg.get(j, 0) > 1:
            continue
        for i in [i for i in adj[j] if i in alive]:
            alive.discard(i)
            for x in kjoints(i):
                deg[x] -= 1
                if deg[x] <= 1 and x not in anchor_k:
                    stack.append(x)
    loose = set(range(len(tracks))) - alive
    seen = set()
    for i in sorted(alive):                       # whole pieces with no anchor at all
        if i in seen:
            continue
        comp, todo, ok = set(), [i], False
        while todo:
            k = todo.pop()
            if k in comp:
                continue
            comp.add(k)
            for x in kjoints(k):
                ok = ok or x in anchor_k
                todo.extend(adj[x] - comp)
        seen |= comp
        if not ok:
            loose |= comp
    by_net = defaultdict(list)
    for i in loose:
        by_net[tracks[i]["net"]].append(i)

    def free_end_detail(net, idx):
        """CT addition (report only, never excuses): what each free end of a loose piece sits next to - a same-net
        pad / via its copper touches with the END outside it ("edge landing": the trace stops at the target's edge
        instead of running to its centre), a same-net pad / via it stops short of, or nothing (a free stub)"""
        out = []
        for i in idx:
            t = tracks[i]
            L = t["layer"]
            for q in (t["a"], t["e"]):
                j = K(J(L, q))
                if len(adj[j]) > 1 or j in anchor_k:          # a true free end: the only track at its joint
                    continue
                pt = Point(q)
                best = None
                for k in p_tree.query(pt.buffer(2.0)):
                    p = all_pads[k]
                    if p.GetNetname() != net or not p.IsOnLayer(L):
                        continue
                    pg = pad_poly(p, L)
                    d = pg.distance(pt)
                    if best is None or d < best[0]:
                        best = (d, "pad " + pad_ref(p), pg.intersects(t["cu"]))
                for k in v_tree.query(pt.buffer(2.0)):
                    v = vias[k]
                    if v.GetNetname() != net or not v.IsOnLayer(L):
                        continue
                    d = v_geo[k].distance(pt)
                    if best is None or d < best[0]:
                        best = (d, f"via {where(P(v.GetPosition()))}", v_geo[k].intersects(t["cu"]))
                cap = pt.buffer(t["w"] / 2)
                for k in t_tree.query(cap):                  # another same-net track's copper touched off its centreline
                    o = tracks[k]
                    if k == i or o["net"] != net or o["layer"] != L or not o["cu"].intersects(cap):
                        continue
                    d = max(0.0, o["line"].distance(pt) - o["w"] / 2)
                    if best is None or d < best[0] or not best[2]:
                        best = (d, f"track {where(o['a'])}-{where(o['e'])}", True)
                if best is None:
                    cls = "free stub (no same-net pad / via within 2 mm)"
                elif best[2]:
                    cls = f"edge landing on {best[1]}: end {best[0]:.3f} mm outside it, copper overlap only"
                else:
                    cls = f"stops {best[0]:.3f} mm short of {best[1]}"
                out.append({"at": where(q), "layer": lname(L), "class": cls, "edge_landing": bool(best and best[2])})
        return out

    for net, idx in sorted(by_net.items()):
        free = sorted({where(q) + " " + lname(tracks[i]["layer"]) for i in idx for q in (tracks[i]["a"], tracks[i]["e"])
                       if len(adj[K(J(tracks[i]["layer"], q))] & alive) == 0
                       and K(J(tracks[i]["layer"], q)) not in anchor_k})
        fails["TRACK-END"].append({"net": net, "loose_mm": round(sum(tracks[i]["len"] for i in idx), 3),
                                   "tracks": len(idx), "free_ends": free[:6],
                                   "end_detail": free_end_detail(net, idx)[:6],
                                   "inside_own_pour": any(fill(net, tracks[i]["layer"])[1].intersects(tracks[i]["cu"])
                                                          for i in idx),
                                   "uuids": [tracks[i]["obj"].m_Uuid.AsString() for i in idx][:30]})
    # second, independent detector: KiCad's own endpoint test (what DRC's track_dangling uses). Zones count as
    # connections there, so it cannot see the D1 case; the pruning above can. Either one firing is a FAIL.
    k_dangling = [t for t in tracks if con.TestTrackEndpointDangling(t["obj"], False)]
    pruned_ids = {id(tracks[i]["obj"]) for i in loose}
    for t in k_dangling:
        if id(t["obj"]) not in pruned_ids:
            fails["TRACK-END"].append({"net": t["net"], "detector": "kicad TestTrackEndpointDangling",
                                       "track": f"{lname(t['layer'])} {where(t['a'])}-{where(t['e'])}",
                                       "len_mm": round(t["len"], 4), "uuids": [t["obj"].m_Uuid.AsString()]})
    info["kicad_dangling_tracks"] = len(k_dangling)
    info["pour_stitch_joints"] = sum(1 for a in anchor.values() if a == "pour-stitch")
    info["anchored_vias"] = len(via_anchor)

    # ---------------------------------------------------------------- VIA-LAND
    for k, v in enumerate(vias):
        net = v.GetNetname()
        hit = set()
        for L in v.GetLayerSet().CuStack():
            if any(tracks[i]["net"] == net and tracks[i]["layer"] == L and collide(v, tracks[i]["obj"], L)
                   for i in t_tree.query(v_geo[k])):
                hit.add(L)
            elif any(all_pads[i].GetNetname() == net and all_pads[i].IsOnLayer(L) and collide(v, all_pads[i], L)
                     for i in p_tree.query(v_geo[k])):
                hit.add(L)
            elif net in pour and fill(net, L)[1].intersects(v_geo[k]):
                hit.add(L)
        if len(hit) < 2:
            fails["VIA-LAND"].append({"net": net, "at": P(v.GetPosition()), "landings": [lname(L) for L in sorted(hit)]})

    # ---------------------------------------------------------------- PLANE-ISLAND (owner 2026-10-06)
    # Per net with zones: union-find over its pads, tracks, vias and every stored fill island (one node per polygon of
    # the layer's fill union). Copper joins where it touches on a shared layer; islands on different layers join only
    # through vias / plated pads. A component holding an island >= PLANE_ISLAND_MIN_MM2 that is not the net's main
    # component (most pads; ties -> most fill area) FAILs, with its pads / vias named.
    cu_layers = list(b.GetEnabledLayers().CuStack())
    pi_small = pi_count = 0
    for net in sorted(zones):
        isl = [(L, g) for L in cu_layers for g in getattr(fill(net, L)[0], "geoms", [fill(net, L)[0]])
               if not g.is_empty and g.area > 0]
        if not isl:
            continue
        pi_count += len(isl)
        u = UF()
        n_pads = [j for j, p in enumerate(all_pads) if p.GetNetname() == net]
        n_vias = [k for k, v in enumerate(vias) if v.GetNetname() == net]
        n_trk = [i for i, t in enumerate(tracks) if t["net"] == net]
        for x in [("p", j) for j in n_pads] + [("v", k) for k in n_vias] + [("t", i) for i in n_trk]:
            u.find(x)
        for i in n_trk:
            t, L = tracks[i], tracks[i]["layer"]
            for k in t_tree.query(t["cu"]):
                o = tracks[k]
                if k > i and o["net"] == net and o["layer"] == L and t["cu"].intersects(o["cu"]):
                    u.union(("t", i), ("t", k))
            for j in p_tree.query(t["cu"]):
                p = all_pads[j]
                if p.GetNetname() == net and p.IsOnLayer(L) and pad_poly(p, L).intersects(t["cu"]):
                    u.union(("t", i), ("p", j))
            for k in v_tree.query(t["cu"]):
                if vias[k].GetNetname() == net and vias[k].IsOnLayer(L) and v_geo[k].intersects(t["cu"]):
                    u.union(("t", i), ("v", k))
        for k in n_vias:
            for j in p_tree.query(v_geo[k]):
                p = all_pads[j]
                if p.GetNetname() == net and any(vias[k].IsOnLayer(L) and pad_poly(p, L).intersects(v_geo[k])
                                                 for L in p.GetLayerSet().CuStack()):
                    u.union(("v", k), ("p", j))
        for j in n_pads:
            p = all_pads[j]
            for j2 in p_tree.query(pbox(p)):
                q = all_pads[j2]
                if j2 > j and q.GetNetname() == net and any(
                        q.IsOnLayer(L) and pad_poly(p, L).intersects(pad_poly(q, L)) for L in p.GetLayerSet().CuStack()):
                    u.union(("p", j), ("p", j2))
        for n, (L, g) in enumerate(isl):
            node, pg = ("z", n), prep(g)
            u.find(node)
            for i in t_tree.query(g):
                if tracks[i]["net"] == net and tracks[i]["layer"] == L and pg.intersects(tracks[i]["cu"]):
                    u.union(node, ("t", i))
            for j in p_tree.query(g):
                p = all_pads[j]
                if p.GetNetname() == net and p.IsOnLayer(L) and pg.intersects(pad_poly(p, L)):
                    u.union(node, ("p", j))
            for k in v_tree.query(g):
                if vias[k].GetNetname() == net and vias[k].IsOnLayer(L) and pg.intersects(v_geo[k]):
                    u.union(node, ("v", k))
        comp = defaultdict(lambda: {"pads": [], "vias": [], "isl": []})
        for j in n_pads:
            comp[u.find(("p", j))]["pads"].append(j)
        for k in n_vias:
            comp[u.find(("v", k))]["vias"].append(k)
        for n in range(len(isl)):
            comp[u.find(("z", n))]["isl"].append(n)
        main_c = max(comp, key=lambda c: (len(comp[c]["pads"]), sum(isl[n][1].area for n in comp[c]["isl"])))
        n_main = len(comp[main_c]["pads"])
        for c, m in comp.items():
            if c == main_c or not m["isl"]:
                continue
            big = [n for n in m["isl"] if isl[n][1].area >= PLANE_ISLAND_MIN_MM2]
            if not big:
                pi_small += len(m["isl"])
                continue
            pi_small += len(m["isl"]) - len(big)
            geo = unary_union([isl[n][1] for n in big])
            area = sum(isl[n][1].area for n in big)
            cen = (round(geo.centroid.x, 3), round(geo.centroid.y, 3))
            bb = tuple(round(x, 3) for x in geo.bounds)
            pads = sorted(pad_ref(all_pads[j]) for j in m["pads"])
            fails["PLANE-ISLAND"].append({
                "net": net, "area_mm2": round(area, 2), "at": cen, "bbox": bb,
                "layers": sorted({lname(isl[n][0]) for n in big}), "islands": len(big), "pads": pads,
                "vias": [P(vias[k].GetPosition()) for k in m["vias"]][:20], "n_vias": len(m["vias"]),
                "what": f"{net} plane island {area:.0f} mm2 at {where(cen)}: {', '.join(pads[:12]) or 'no pads'}"
                        f" - not connected to the {net} main copper ({n_main} pads)"})
    info["plane_islands"] = pi_count
    info["plane_islands_below_min"] = pi_small

    # ---------------------------------------------------------------- CLEAN checks (owner 2026-10-05)
    # Connected is not clean: each of these passed every gate above on the M1 candidate and the owner found it by eye.
    force = FORCE_NETS[kind]

    def flash(v, L):
        return v.IsOnLayer(L) and (not hasattr(v, "FlashLayer") or v.FlashLayer(L))

    # TRACK-DUP: zero-length copper, or a segment lying entirely inside another same-net same-layer segment
    for i, t in enumerate(tracks):
        if t["line"].geom_type == "Point" or t["len"] < 1e-4:
            fails["TRACK-DUP"].append({"net": t["net"], "layer": lname(t["layer"]), "at": where(t["a"]),
                                       "what": "zero-length segment", "uuids": [t["obj"].m_Uuid.AsString()]})
            continue
        for k in t_tree.query(t["cu"]):
            o = tracks[k]
            if k == i or o["net"] != t["net"] or o["layer"] != t["layer"] or o["len"] < 1e-4:
                continue
            if o["cu"].buffer(1e-4).contains(t["cu"]) and (not t["cu"].buffer(1e-4).contains(o["cu"]) or k < i):
                fails["TRACK-DUP"].append({"net": t["net"], "layer": lname(t["layer"]),
                                           "track": f"{where(t['a'])}-{where(t['e'])}",
                                           "what": "covered by " + f"{where(o['a'])}-{where(o['e'])}",
                                           "uuids": [t["obj"].m_Uuid.AsString()]})
                break

    # VIA-PADEDGE: a via whose copper overlaps an SMD pad on a shared layer with its centre outside the pad (a kiss
    # landing with no stub, a solder-wicking via in the pad edge, or a short when the pad is foreign)
    for k, v in enumerate(vias):
        c = Point(P(v.GetPosition()))
        for i in p_tree.query(v_geo[k].buffer(PADEDGE_GAP_MM)):
            p = all_pads[i]
            if p.GetAttribute() not in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN):
                continue
            for L in p.GetLayerSet().CuStack():
                if not flash(v, L):
                    continue
                pp = pad_poly(p, L)
                cls, ov, gap = padedge_class(pp, c, mm(v.GetWidth(L)) / 2, p.GetNetname() == v.GetNetname(),
                                             mm(v.GetDrillValue()) / 2)
                if cls is None or (cls == "gap" and not PADEDGE_GAP_IN_LANDING):
                    continue
                if cls == "intentional":
                    info["padedge_vias_intentional"] = info.get("padedge_vias_intentional", 0) + 1
                    break                                  # a deliberate pad-edge landing (owner: a good use of space)
                fails["VIA-PADEDGE"].append({"net": v.GetNetname(), "at": P(v.GetPosition()), "pad": pad_ref(p),
                                             "pad_net": p.GetNetname(), "layer": lname(L),
                                             "overlap_mm2": round(ov, 4), "gap_mm": round(gap, 4),
                                             "what": {"edge": "via in the pad edge",
                                                      "drilled": "via drill cuts the pad edge (centre outside the pad)",
                                                      "foreign": "via copper touches a FOREIGN pad",
                                                      "gap": f"via < {PADEDGE_GAP_MM} mm from the pad edge"}[cls],
                                             "uuids": [v.m_Uuid.AsString()]})
                break

    # VIA-PARTIAL (review M4 M1, lead 2026-10-05): a via is in a land or clear of it, never half on it. An SMD /
    # connector pad (any net) or a foreign plated-hole pad with copper on a layer the via flashes, overlapped by the disc
    # while the via centre is outside it, FAILs; the padedge class is reported (intentional / drilled / edge / foreign).
    pth_kiss = set()
    for k, v in enumerate(vias):
        c = Point(P(v.GetPosition()))
        hit = None
        for i in p_tree.query(v_geo[k]):
            p = all_pads[i]
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                continue
            for L in p.GetLayerSet().CuStack():
                if not flash(v, L) or (hasattr(p, "FlashLayer") and not p.FlashLayer(L)):
                    continue
                pp = pad_poly(p, L)
                if pp.is_empty or pp.contains(c):
                    continue
                r = mm(v.GetWidth(L)) / 2
                ov = pp.intersection(c.buffer(r)).area
                if ov <= 1e-4:
                    continue
                same = p.GetNetname() == v.GetNetname()
                if p.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN):
                    cls = padedge_class(pp, c, r, same, mm(v.GetDrillValue()) / 2)[0]
                elif same:                     # a same-net via merging with a plated-hole annulus: stitching, no land
                    pth_kiss.add((k, pad_ref(p)))
                    continue
                else:
                    cls = "foreign"
                if cls == "intentional" and PARTIAL_ALLOW_INTENTIONAL:
                    continue
                hit = {"net": v.GetNetname(), "at": P(v.GetPosition()), "pad": pad_ref(p), "pad_net": p.GetNetname(),
                       "layer": lname(L), "overlap_mm2": round(ov, 4), "overlap_frac": round(ov / (math.pi * r * r), 3),
                       "centre_out_mm": round(pp.distance(c), 3), "class": cls,
                       "what": "via disc overlaps the pad with its centre outside it", "uuids": [v.m_Uuid.AsString()]}
                break
            if hit:
                break
        if hit:
            fails["VIA-PARTIAL"].append(hit)
    info["partial_pth_same_net"] = len(pth_kiss)

    # VIA-BARE: a via touching no same-net track or pad on any layer is a pour stitch; it is kept only where it is a
    # geometrically needed stitch: some own-net fill island it touches has fewer than 2 other inter-layer links (vias or plated
    # holes). Only the generator force-current via arrays (FORCE_NETS) are reported, not gated. A lock is NOT intent:
    # the owner's orphan GND via at (183.875, 43.45) was a locked revC-A1 fan-out via whose track move_rip removed.
    # A remaining finding is unresolved functional review, not permission to remove useful return/EMI stitching.
    pth = [p for p in all_pads if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    pth_tree = STRtree([pbox(p) for p in pth]) if pth else None
    bare_exempt = 0
    via_intent = 0
    inner = [L for L in b.GetEnabledLayers().CuStack() if L not in (pcbnew.F_Cu, pcbnew.B_Cu)]

    def plane_links(net, isl, L):
        """[(via idx or None, (x, y))] plane-reaching vias and plated holes of the net on outer island isl (POUR-STITCH)"""
        planes = [PL for PL in inner if not fill(net, PL)[0].is_empty]
        if not planes:
            return None
        pi = prep(isl)
        out = [(j, P(vias[j].GetPosition())) for j in v_tree.query(isl) if vias[j].GetNetname() == net
               and vias[j].IsOnLayer(L) and pi.intersects(v_geo[j])
               and any(vias[j].IsOnLayer(PL) and fill(net, PL)[1].intersects(v_geo[j]) for PL in planes)]
        if pth_tree is not None:
            out += [(None, P(pth[j].GetPosition())) for j in pth_tree.query(isl) if pth[j].GetNetname() == net
                    and pi.intersects(Point(P(pth[j].GetPosition())))]
        return out
    # edge-fence candidates: vias within FENCE_EDGE_MM of the board outline that reach their net's inner plane fill
    edge = None
    ops = pcbnew.SHAPE_POLY_SET()
    if b.GetBoardPolygonOutlines(ops, True):
        og = to_shapely(ops)
        edge = og.boundary if not og.is_empty else None
    fence_cand = defaultdict(list)
    if edge is not None:
        for k, v in enumerate(vias):
            q = P(v.GetPosition())
            if edge.distance(Point(q)) <= FENCE_EDGE_MM and any(
                    v.IsOnLayer(PL) and fill(v.GetNetname(), PL)[1].intersects(v_geo[k]) for PL in inner):
                fence_cand[v.GetNetname()].append((k, q))
    fence_kept = 0
    for k, v in enumerate(vias):
        net = v.GetNetname()
        lays = list(v.GetLayerSet().CuStack())
        if any(tracks[i]["net"] == net and tracks[i]["layer"] in lays and collide(v, tracks[i]["obj"], tracks[i]["layer"])
               for i in t_tree.query(v_geo[k])):
            continue
        if any(all_pads[i].GetNetname() == net and any(all_pads[i].IsOnLayer(L) and collide(v, all_pads[i], L)
                                                          for L in lays) for i in p_tree.query(v_geo[k])):
            continue
        if net in force:
            bare_exempt += 1
            continue
        q0 = P(v.GetPosition())
        if any(n2 == net and abs(q0[0] - x2) <= VIA_INTENT_TOL_MM and abs(q0[1] - y2) <= VIA_INTENT_TOL_MM
               for n2, x2, y2 in VIA_INTENT.get(kind, {})):
            via_intent += 1
            continue
        needed = []
        for L in lays:
            g = fill(net, L)[0]
            for isl in getattr(g, "geoms", [g]):
                if isl.is_empty or not isl.intersects(v_geo[k]):
                    continue
                pi = prep(isl)
                # a fragment no bigger than ISLAND_MIN_MM2 that carries no pad or track of its own exists only around
                # the via (e.g. a GND via flash inside the In4 +5V region); it needs nothing
                if isl.area < ISLAND_MIN_MM2 and not any(
                        tracks[i]["net"] == net and tracks[i]["layer"] == L and pi.intersects(tracks[i]["cu"])
                        for i in t_tree.query(isl)) and not any(
                        all_pads[i].GetNetname() == net and all_pads[i].IsOnLayer(L) and pi.intersects(pad_poly(all_pads[i], L))
                        for i in p_tree.query(isl)):
                    continue
                links = sum(1 for j in v_tree.query(isl) if j != k and vias[j].GetNetname() == net
                            and vias[j].IsOnLayer(L) and pi.intersects(v_geo[j]))
                if pth_tree is not None:
                    links += sum(1 for j in pth_tree.query(isl) if pth[j].GetNetname() == net and pi.intersects(pbox(pth[j])))
                # an island needs 2 links, and a fragment > STITCH_MIN_MM2 needs the POUR-STITCH density of
                # qa_layout_quality (same constants: the two gates may never demand and forbid the same via)
                # (POUR-STITCH gates outer fragments only; an inner plane island keeps the 2-link rule)
                outer_frag = isl.area > STITCH_MIN_MM2 and L in (pcbnew.F_Cu, pcbnew.B_Cu)
                need = max(STITCH_MIN_VIAS, math.ceil(isl.area / STITCH_MM2_PER_VIA)) if outer_frag else 2
                if links < need:
                    needed.append(f"{lname(L)} island {isl.area:.1f} mm2, {links} other link(s) of {need}")
                elif L in (pcbnew.F_Cu, pcbnew.B_Cu) and isl.area > STITCH_MIN_MM2:
                    pl = plane_links(net, isl, L)
                    if pl and any(j == k for j, _ in pl):           # this via reaches the plane: is it needed by reach?
                        others = [q for j, q in pl if j != k]
                        lost = reach_lost(isl, others, P(v.GetPosition()))
                        if lost > STITCH_REACH_TOL_MM2:
                            needed.append(f"{lname(L)} island {isl.area:.1f} mm2: {lost:.2f} mm2 only it reaches "
                                          f"within {STITCH_REACH_MM} mm")
        if not needed:
            q = P(v.GetPosition())
            cand = fence_cand.get(net, [])
            if any(j == k for j, _ in cand) and any(j != k and math.dist(q, q2) <= FENCE_PITCH_MM for j, q2 in cand):
                fence_kept += 1                           # an edge-fence via (FENCE_EDGE_MM / FENCE_PITCH_MM)
                continue
            fails["VIA-BARE"].append({"net": net, "at": P(v.GetPosition()),
                                      "what": "pour-only via: island heuristics do not establish a role; review signal-return, EMI and thermal function before removal",
                                      "uuids": [v.m_Uuid.AsString()]})
    info["bare_vias_exempt_force"] = bare_exempt
    info["via_intent"] = via_intent
    info["fence_vias"] = fence_kept

    # TRACK-ORPHAN: a connected piece of a net's track copper (joined through vias) touching no pad of its net, e.g. a
    # GND chain from a pour-only via into the pour; FORCE_NETS generator copper excepted
    tvia = defaultdict(set)
    for k, v in enumerate(vias):
        for L in v.GetLayerSet().CuStack():
            for i in t_tree.query(v_geo[k]):
                if tracks[i]["net"] == v.GetNetname() and tracks[i]["layer"] == L and collide(v, tracks[i]["obj"], L):
                    tvia[i].add(k)
    vtr = defaultdict(set)
    for i, ks in tvia.items():
        for k in ks:
            vtr[k].add(i)
    padded = set()
    for i, t in enumerate(tracks):
        if any(all_pads[j].GetNetname() == t["net"] and all_pads[j].IsOnLayer(t["layer"])
               and collide(all_pads[j], t["obj"], t["layer"]) for j in p_tree.query(t["cu"])):
            padded.add(i)
    via_padded = {k for k, a in via_anchor.items() if a.startswith("via on pad")}
    seen = set()
    for i in range(len(tracks)):
        if i in seen or tracks[i]["net"] in force:
            continue
        comp, todo, ok = set(), [i], False
        while todo:
            x = todo.pop()
            if x in comp:
                continue
            comp.add(x)
            ok = ok or x in padded or bool(tvia[x] & via_padded)
            for j in kjoints(x):
                todo.extend(adj[j] - comp)
            for kv in tvia[x]:
                todo.extend(vtr[kv] - comp)
        seen |= comp
        if not ok:
            fails["TRACK-ORPHAN"].append({"net": tracks[i]["net"], "tracks": len(comp),
                                          "mm": round(sum(tracks[x]["len"] for x in comp), 3),
                                          "at": where(tracks[i]["a"]), "layers": sorted({lname(tracks[x]["layer"]) for x in comp}),
                                          "uuids": [tracks[x]["obj"].m_Uuid.AsString() for x in comp][:30]})

    # PAD-CENTRE: a trace that terminates on an SMD pad must terminate at the pad's centre (owner 2026-10-05: "traces
    # run from the edge of the pads. They should run FROM THE CENTER OF THE PADS"). A chain end inside the pad copper
    # but off its centre (no other same-layer track continuing from that joint) FAILs; FORCE_NETS pads excepted.
    for (net, L), lst in ends.items():
        if net in force:
            continue
        # Count the same-layer/net tracks continuing through each joint, including
        # midspan T/X joins. A branch inside a pad is not a chain end when another
        # track continues from that joint to the pad centre. Vias/other layers or
        # mere pad overlap do not supply this same-layer continuation.
        per_joint = defaultdict(set)
        for i in {i for q, w, i in lst}:
            for j in joints(i):
                per_joint[j].add(i)
        for q, w, i in lst:
            if len(per_joint[J(L, q)]) != 1:
                continue
            for k in p_tree.query(Point(q)):
                p = all_pads[k]
                if p.GetNetname() != net or not p.IsOnLayer(L) or \
                        p.GetAttribute() not in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN):
                    continue
                if not pad_poly(p, L).contains(Point(q)):
                    continue
                c = P(p.GetPosition())
                d = math.dist(q, c)
                if d > PAD_CENTRE_TOL:
                    fails["PAD-CENTRE"].append({"net": net, "pad": pad_ref(p), "layer": lname(L), "at": q,
                                                "off_mm": round(d, 3), "uuids": [tracks[i]["obj"].m_Uuid.AsString()]})
                break

    # TRACK-WIDTH (owner 2026-10-05: "a validation rule that looks at trace width for appropriate nets as a part of every
    # cleaning pass"): KiCad DRC never enforces a net-class width, so the router narrowed power copper silently. The
    # required width comes from current_budget (MAIN: max(class width, IPC-2152 load / fault width); UI: class width);
    # a neck-down of <= NECK_MM into a same-net pad no wider than the required width is allowed, and (budget bases) a
    # foreign-object neck meeting all of (a)-(d) (owner LVW-NECKS-20261009; see the module docstring).
    pro = Path(str(pcb)).with_suffix(".kicad_pro")
    cls_w = {}
    if pro.exists():
        cls_w = {c["name"]: c.get("track_width") for c in
                 json.loads(pro.read_text(encoding="utf-8")).get("net_settings", {}).get("classes", [])}
    basis = width_basis or cb.WIDTH_BASIS[kind]
    info["width_classes"] = len(cls_w)
    info["width_basis"] = basis
    leaf_tracks = set()
    branch_tracks = {}
    if basis in ("budget", "budget-path"):          # current_budget.BRANCHES: the branch's own load / fault
        branch_tracks = budget_branch_tracks(kind, tracks, vias, v_geo, all_pads, pad_poly, fill)
        info["width_branch_tracks"] = len(branch_tracks)
    if basis == "budget-path":          # report basis (lead 2026-10-06, UI B8.1 final): the rail width applies to the
        leaf_tracks = budget_leaf_tracks(b, tracks, vias, v_geo, all_pads, pad_poly, fill)   # supply path only
        info["width_leaf_tracks"] = len(leaf_tracks)
    unbudgeted = set()
    outer_layers = {pcbnew.F_Cu, pcbnew.B_Cu}
    narrow = {}                                   # track idx -> (required, gate current A or None): below required
    pending = []                                  # (track idx, its FAIL row) foreign-neck candidates
    for i, t in enumerate(tracks):
        o = t["obj"]
        net = t["net"]
        cur = None
        cname = (o.GetNetClassName() or "Default").split(",")[0].strip()
        cw = cls_w.get(cname) or cls_w.get("Default")
        if net in force:
            continue
        outer = t["layer"] in outer_layers
        rec = {"net": net, "class": cname, "layer": lname(t["layer"]), "at": where(t["a"]), "len_mm": round(t["len"], 3),
               "width": t["w"], "uuids": [o.m_Uuid.AsString()]}
        if basis in ("budget", "budget-path"):
            imp = cb.impedance_width(kind, net, outer)
            if imp is not None:
                w_imp, tol = imp
                if w_imp is None or abs(t["w"] - w_imp) > tol:
                    fails["TRACK-WIDTH"].append({**rec, "required": w_imp, "what": (
                        "impedance net on a layer with no qualified geometry" if w_imp is None else
                        "impedance net off its qualified width")})
                continue
            if not cb.is_current_net(kind, net, cname):
                continue
            if net in cb.BUDGET[kind] and i in leaf_tracks:
                req, why = cw, "leaf branch to pull-up / decoupling pads only, below its class width"
            elif i in branch_tracks:
                req = cb.branch_required_width(kind, branch_tracks[i], outer, cw)
                why = "below max(class width, IPC-2152 branch load / fault width) (current_budget.BRANCHES)"
                cur = max(branch_tracks[i]["load_A"], branch_tracks[i]["fault_A"] or 0.0)
            elif net in cb.BUDGET[kind]:
                req = cb.required_width(kind, net, outer, cw)
                why = "below max(class width, IPC-2152 load / fault width)"
                load_a, fault_a, _ = cb.budget(kind, net)
                cur = max(load_a, fault_a or 0.0)
            else:
                unbudgeted.add(net)
                req, why = cw, "current class / rail (not in current_budget) below its class width"
        else:
            if not cw:
                continue
            if cname in IMPEDANCE_CLASSES:
                if abs(t["w"] - cw) > 0.011:
                    fails["TRACK-WIDTH"].append({**rec, "required": cw, "what": "impedance class off its width"})
                continue
            if not (cname in CURRENT_CLASSES or RAIL_RE.match(net)):
                continue
            req, why = cw, "current-carrying copper below its class width"
        if not req or t["w"] >= req - 1e-3:
            continue
        narrow[i] = (req, cur)
        neck = False
        if t["len"] <= NECK_MM:
            for k in p_tree.query(t["cu"].buffer(0.05)):
                p = all_pads[k]
                if p.GetNetname() == net and p.IsOnLayer(t["layer"]) and                         min(mm(p.GetSize(t["layer"]).x), mm(p.GetSize(t["layer"]).y)) <= req + 1e-3 and                         pad_poly(p, t["layer"]).distance(t["line"]) <= 1e-3:
                    neck = True
                    break
        if not neck:
            row = {**rec, "required": req, "class_w": cw, "what": why}
            fails["TRACK-WIDTH"].append(row)
            pending.append((i, row))
    if basis in ("budget", "budget-path"):
        info["width_unbudgeted_current_nets"] = sorted(unbudgeted)
        # FOREIGN-OBJECT NECK (owner LVW-NECKS-20261009): evaluated live for every candidate; excused only if (a)-(d) hold
        excused = []
        if pending:
            blockers = NeckBlockers(b, pcb)
            run_of = neck_runs(tracks, narrow)
            runs = defaultdict(list)
            for k, r in run_of.items():
                runs[r].append(k)
            run_eval = {}

            def evaluate_run(r):
                members = sorted(runs[r])
                req_run = max(narrow[k][0] for k in members)
                curs = [narrow[k][1] for k in members]
                lay = tracks[members[0]]["layer"]
                cu = cb.STACKUP[kind]["outer_um" if lay in outer_layers else "inner_um"]
                ends_open, ends_held = 0, 0
                for k in members:
                    for q in (tracks[k]["a"], tracks[k]["e"]):
                        pt = Point(q)
                        if any(m != k and tracks[m]["line"].distance(pt) <= tracks[m]["w"] / 2 + 1e-6 for m in members):
                            continue                  # internal joint of the run
                        held = any(n not in narrow and tracks[n]["net"] == tracks[k]["net"] and tracks[n]["layer"] == lay
                                   and tracks[n]["w"] >= req_run - 1e-3
                                   and tracks[n]["line"].distance(pt) <= tracks[n]["w"] / 2 + 1e-6
                                   for n in t_tree.query(pt))
                        ends_held += held
                        ends_open += not held
                anchored = ends_held > 0 and ends_open == 0
                length = sum(tracks[k]["len"] for k in members)
                w_min = min(tracks[k]["w"] for k in members)
                ev = {"uuids": [tracks[k]["obj"].m_Uuid.AsString() for k in members], "len_mm": round(length, 4),
                      "w_min": w_min, "required": req_run, "cu_um": cu, "ends_held": ends_held, "ends_open": ends_open,
                      "c": 8 if anchored else 2}
                if any(c is None for c in curs):
                    ev.update(I_A=None, dT_1d_K=None)
                else:
                    i_a = max(curs)
                    ev.update(I_A=i_a, dT_1d_K=round(neck_rise_1d(i_a, length, w_min, cu, anchored), 4),
                              ipc_rise_K=round(ipc_rise_k(i_a, w_min, cu), 2),
                              ipc_rise_full_K=round(ipc_rise_k(i_a, req_run, cu), 2))
                return ev
            for i, row in pending:
                t = tracks[i]
                req = narrow[i][0]
                r = run_of[i]
                if r not in run_eval:
                    run_eval[r] = evaluate_run(r)
                run = run_eval[r]
                blk = blockers.at(t, req)
                why_not = []
                if t["len"] > NECK_FOREIGN_MM + 1e-6:
                    why_not.append(f"(a) piece {t['len']:.3f} mm > {NECK_FOREIGN_MM} mm")
                if t["w"] < NECK_FOREIGN_MIN_FRAC * req - 1e-6:
                    why_not.append(f"(b) width {t['w']:.4f} < {NECK_FOREIGN_MIN_FRAC} x required {req}")
                if run["dT_1d_K"] is None:
                    why_not.append("(c) no budget current for the run (class / leaf / unbudgeted width)")
                elif run["dT_1d_K"] > NECK_FOREIGN_MAX_DT_K:
                    why_not.append(f"(c) 1-D run rise {run['dT_1d_K']} K > {NECK_FOREIGN_MAX_DT_K} K")
                if not blk:
                    why_not.append("(d) no foreign object within clearance + epsilon of the required-width outline")
                ev = {"excused": not why_not, "why_not": why_not, "ratio": round(t["w"] / req, 4),
                      "run": run, "blockers": blk[:4]}
                if why_not:
                    row["foreign_neck"] = ev
                else:
                    lst = fails["TRACK-WIDTH"]
                    del lst[next(n for n, x in enumerate(lst) if x is row)]
                    excused.append({k: row[k] for k in ("net", "layer", "at", "len_mm", "width", "required", "uuids")}
                                   | {"ratio": ev["ratio"], "run": run, "blockers": blk[:4]})
        info["width_foreign_necks"] = excused

    # TRACK-JOG: a staircase step, i.e. a segment shorter than JOG_W x its width between two bends of opposite turn,
    # that FAILs only where a CLEAN local shortcut exists (owner J1, 2026-10-09), screened live by jog_screen().
    jogs = defaultdict(list)
    jog_sites = []
    for (net, L), lst in ends.items():
        at_joint = defaultdict(list)
        for q, w, i in lst:
            at_joint[J(L, q)].append((i, q))
        for i, t in enumerate(tracks):
            if t["net"] != net or t["layer"] != L or t["line"].geom_type != "LineString" or t["len"] >= JOG_W * t["w"] \
                    or tee.get(i):
                continue
            turns, nbs, fars = [], [], []
            for q, other_end in ((t["a"], t["e"]), (t["e"], t["a"])):
                nb = [x for x in at_joint[J(L, q)] if x[0] != i]
                if len(nb) != 1 or tracks[nb[0][0]]["line"].geom_type != "LineString" or tee.get(nb[0][0]):
                    break
                n = tracks[nb[0][0]]
                far = n["e"] if J(L, n["a"]) == J(L, q) else n["a"]
                u = (q[0] - far[0], q[1] - far[1])                 # neighbour direction into the joint
                s = (other_end[0] - q[0], other_end[1] - q[1])      # this segment, leaving the joint
                turns.append(u[0] * s[1] - u[1] * s[0])
                nbs.append(nb[0][0])
                fars.append(far)
            if len(turns) == 2:
                # walking the chain: turn at a is cross(n_a -> a, a -> e); at e it is cross(a -> e, e -> n_e) = -turns[1]
                ta, te = turns[0], -turns[1]
                if abs(ta) > 1e-6 and abs(te) > 1e-6 and (ta > 0) != (te > 0):
                    jog_sites.append(({
                        "net": net, "layer": lname(L),
                        "at": where(t["a"]), "start": t["a"], "end": t["e"],
                        "uuid": t["obj"].m_Uuid.AsString(), "width_mm": t["w"], "length_mm": t["len"],
                        "neighbours": [tracks[x]["obj"].m_Uuid.AsString() for x in nbs]}, [nbs[0], i, nbs[1]], fars))
    screen = jog_screen(b, pcb, jog_sites, tracks) if jog_sites else []
    if any(r["status"] == "FAIL" for r in screen):
        jog_quality(pcb, screen)                    # owner option (a): no new / worsened qa_layout_quality finding
    # PROTECTED staircases (2026-10-09; owner: "staircase jogs are worse than corners"). PROTECTED keeps the automatic
    # shortcut off Kelvin / HIZ / rail-lane / fault nets, where a single step can be deliberate; it must never hide a
    # staircase. Gap found on MAIN r26: SENSE3_N_CLAMP (ISLAND_HIZ) In2.Cu staircases of 0.25 mm steps (87.1, 9.9) ->
    # (90.0, 16.2) and (91.5, 18.35) -> (100.5, 23.85) - 39 PROTECTED sites, every one with a clean local shortcut,
    # reported as info only. Protected sites WITH a clean shortcut that share chain tracks (same net / layer) form a run;
    # a run of >= JOG_STAIR_MIN_SITES steps FAILs (fix: re-route the run with pfr2 / the copper_cleanup smoothing pass
    # under the net's own rules; never an automatic shortcut).
    stair = {}
    prot = [k for k, res in enumerate(screen) if res["status"] == "PROTECTED" and res.get("clean_shortcut")]
    parent = {k: k for k in prot}

    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    owner = {}
    for k in prot:
        key = (jog_sites[k][0]["net"], jog_sites[k][0]["layer"])
        for u in screen[k]["chain_uuids"]:
            if (key, u) in owner:
                parent[root(k)] = root(owner[(key, u)])
            else:
                owner[(key, u)] = k
    runs = defaultdict(list)
    for k in prot:
        runs[root(k)].append(k)
    for r_, ks in runs.items():
        if len(ks) >= JOG_STAIR_MIN_SITES:
            for k in ks:
                stair[k] = len(ks)
    held = defaultdict(int)
    for n_, ((site, idx, fars), res) in enumerate(zip(jog_sites, screen)):
        if n_ in stair:
            jogs[(site["net"], site["layer"])].append({**site, "staircase_steps": stair[n_], "protected": res["protected"],
                                                       "chain_uuids": res["chain_uuids"], "candidates": res["candidates"]})
            continue
        if res["status"] == "FAIL":
            jogs[(site["net"], site["layer"])].append({**site, "shortcut": res["shortcut"],
                                                       "candidates": res["candidates"],
                                                       "layout_quality_tried": res.get("layout_quality_tried", [])})
        else:
            held[res["status"]] += 1
            info.setdefault("jog_screened", []).append({**site, **{k: v for k, v in res.items() if k != "status"},
                                                        "disposition": res["status"]})
    if jog_sites:
        info["jog_sites"] = len(jog_sites)
        info["jog_clean_shortcut_fails"] = sum(len(v) for v in jogs.values())
        info["jog_info_by_reason"] = dict(sorted(held.items()))
        info["jog_protected_staircase_fails"] = len(stair)
    for (net, L), sites in sorted(jogs.items()):
        st_ = [s for s in sites if "staircase_steps" in s]
        row = {"net": net, "layer": L, "jogs": len(sites), "at": [s["at"] for s in sites[:6]],
               "uuids": [s["uuid"] for s in sites], "sites": sites}
        if len(st_) < len(sites):
            row["review"] = ("A CLEAN local shortcut exists for each site (native rule screen: saves "
                             "length, no hard clearance / keep-out / rule violation, no lost contact, "
                             "no new cut into a foreign stored fill, unprotected net, no new or "
                             "worsened qa_layout_quality finding). Apply it.")
        if st_:
            row["protected_staircase_steps"] = len(st_)
            row["review_staircase"] = (f"PROTECTED net staircase: {len(st_)} chained steps of >= {JOG_STAIR_MIN_SITES}, each "
                                       "with a clean local shortcut. Re-route the run (pfr2 production flags / the "
                                       "copper_cleanup smoothing pass) under the net's own rules; no automatic shortcut.")
        fails["TRACK-JOG"].append(row)

    # ---------------------------------------------------------------- LOOP
    G = defaultdict(list)

    def link(u, w_, d):
        G[u].append((w_, d))
        G[w_].append((u, d))

    for i, t in enumerate(tracks):
        a, e = J(t["layer"], t["a"]), J(t["layer"], t["e"])
        link(a, e, t["len"])
        for j in tee.get(i, ()):
            s = t["line"].project(Point(j[1])) if t["line"].geom_type == "LineString" else 0.0
            link(j, a, s)
            link(j, e, max(0.0, t["line"].length - s))
        for k in p_tree.query(t["cu"]):
            p = all_pads[k]
            if p.GetNetname() == t["net"] and p.IsOnLayer(t["layer"]) and collide(p, t["obj"], t["layer"]):
                poly = pad_poly(p, t["layer"])
                for q in (t["a"], t["e"]):
                    link(J(t["layer"], q), ("pad", pad_ref(p)), poly.distance(Point(q)))
    for k, v in enumerate(vias):
        q = P(v.GetPosition())
        for L in v.GetLayerSet().CuStack():
            for i in t_tree.query(v_geo[k]):
                t = tracks[i]
                if t["net"] == v.GetNetname() and t["layer"] == L and collide(v, t["obj"], L):
                    for qq in (t["a"], t["e"]):
                        link(J(L, qq), ("via", q), max(0.0, v_geo[k].distance(Point(qq))))

    def within(srcs, dsts, cap):
        D = {s: 0.0 for s in srcs}
        h = [(0.0, n, s) for n, s in enumerate(srcs)]
        heapq.heapify(h)
        n = len(h)
        while h:
            d, _, u = heapq.heappop(h)
            if u in dsts:
                return True
            if d > D.get(u, math.inf):
                continue
            for x, l in G[u]:
                nd = d + l
                if nd <= cap and nd < D.get(x, math.inf):
                    D[x] = nd
                    n += 1
                    heapq.heappush(h, (nd, n, x))
        return False

    loops = defaultdict(list)
    # (1) closed cycles inside one layer's track copper (T-joints included, pads / vias NOT used as hubs, so the
    #     intended F / B parallel force paths never count): an excursion that re-joins itself, a doubled-back run
    pieces = defaultdict(list)                    # (net, layer) -> [(u, v, length, track idx)]
    for i, t in enumerate(tracks):
        a, e = J(t["layer"], t["a"]), J(t["layer"], t["e"])
        if t["line"].geom_type != "LineString" or not tee.get(i):
            pieces[(t["net"], t["layer"])].append((a, e, t["len"], i))
            continue
        stops = sorted([(0.0, a), (t["line"].length, e)] + [(t["line"].project(Point(j[1])), j) for j in tee[i]])
        for (s0, u), (s1, v) in zip(stops, stops[1:]):
            pieces[(t["net"], t["layer"])].append((u, v, s1 - s0, i))
    for (net, layer), es in pieces.items():
        nbr = defaultdict(list)
        for n_, (u, v, l, i) in enumerate(es):
            nbr[u].append((v, l, n_))
            nbr[v].append((u, l, n_))
        parent, depth, dist, tree_edges = {}, {}, {}, set()
        for root in list(nbr):
            if root in parent:
                continue
            parent[root], depth[root], dist[root] = None, 0, 0.0
            todo = [root]
            while todo:
                u = todo.pop()
                for v, l, n_ in nbr[u]:
                    if v not in parent:
                        parent[v], depth[v], dist[v] = (u, n_), depth[u] + 1, dist[u] + l
                        tree_edges.add(n_)
                        todo.append(v)
        def piece_cu(n_):
            u, v, l, i = es[n_]
            t = tracks[i]
            if t["line"].geom_type != "LineString":
                return t["cu"]
            s0 = t["line"].project(Point(u[1]))
            s1 = t["line"].project(Point(v[1]))
            return substring(t["line"], min(s0, s1), max(s0, s1)).buffer(t["w"] / 2)
        for n_, (u, v, l, i) in enumerate(es):
            if n_ in tree_edges:
                continue
            x, y, cyc, members = u, v, l, [n_]   # walk both ends up to their common ancestor
            while x != y:
                if depth[x] >= depth[y]:
                    cyc += dist[x] - dist[parent[x][0]]
                    members.append(parent[x][1])
                    x = parent[x][0]
                else:
                    cyc += dist[y] - dist[parent[y][0]]
                    members.append(parent[y][1])
                    y = parent[y][0]
            if cyc <= LOOP_MM:
                continue
            cu = unary_union([piece_cu(m) for m in members])
            hole = sum(Polygon(r).area for g in getattr(cu, "geoms", [cu]) for r in getattr(g, "interiors", []))
            t = tracks[i]
            loops[net].append({"layer": lname(layer), "kind": "ring" if hole > HOLE_MM2 else "doubled copper",
                               "cycle_mm": round(cyc, 2), "hole_mm2": round(hole, 3),
                               "a": f"{where(t['a'])}-{where(t['e'])}"})
    # (2) copper of two pieces touching without a modelled joint, far apart along the copper path
    for i, t in enumerate(tracks):
        for k in t_tree.query(t["cu"]):
            if k <= i:
                continue
            o = tracks[k]
            if o["net"] != t["net"] or o["layer"] != t["layer"] or not t["cu"].intersects(o["cu"]):
                continue
            if t["line"].distance(o["line"]) >= (t["w"] + o["w"]) / 2 - 1e-4:
                continue
            ja, jb = joints(i), joints(k)
            if ja & jb or within(list(ja), jb, LOOP_MM):
                continue
            loops[t["net"]].append({"layer": lname(t["layer"]), "a": f"{where(t['a'])}-{where(t['e'])}",
                                    "b": f"{where(o['a'])}-{where(o['e'])}"})
    for net, items in sorted(loops.items()):
        rings = [x for x in items if x.get("kind") != "doubled copper"]
        fails["LOOP"].append({"net": net, "contacts": len(items), "rings": len(rings),
                              "worst": max(items, key=lambda x: (x.get("kind") != "doubled copper", x.get("cycle_mm", 99)))})

    # (the parent's MAIN via-intent manifest, qa_copper_retention, is DIN-8R-specific: CT reports VIA-BARE raw)
    return {"board": str(pcb), "kind": kind, "pour_nets": sorted(pour), "loop_mm": LOOP_MM, "checks": list(checks),
            "status": "FAIL" if any(fails[c] for c in checks) else "PASS",
            "counts": {k: len(v) for k, v in fails.items()}, "fails": fails, "info": info}


def require(pcb, out_json, checks=CHECKS):
    """fab_outputs.py / routing / candidate-validation hook (KiCad Python): raises on any FAIL."""
    res = check(pcb, checks)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if res["status"] != "PASS":
        raise RuntimeError(f"qa_copper_landing FAILED {res['counts']} (report: {out_json})")
    return out_json


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--json")
    ap.add_argument("--checks", default=",".join(CHECKS))
    a = ap.parse_args(argv)
    # local_run.py runs KiCad-side scripts with cwd = scripts/: relative paths are project-root relative
    a.board = str(Path(a.board) if Path(a.board).is_absolute() or Path(a.board).exists() else K.ROOT / a.board)
    if a.json and not Path(a.json).is_absolute():
        a.json = str(K.ROOT / a.json)
    try:
        res = check(a.board, tuple(x.strip() for x in a.checks.split(",") if x.strip()))
    except Exception as e:                                # fail closed
        import traceback
        traceback.print_exc()
        print(f"qa_copper_landing ERROR: {e!r}")
        return 2
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"qa_copper_landing {res['status']}  {a.board}  ({res['kind']}, pour nets {res['pour_nets']})")
    for k in CHECKS:
        items = res["fails"][k]
        state = ("FAIL" if items else "ok") if k in res["checks"] else "(not gated)"
        print(f"  {k:9s} {state:4s} {len(items)}")
        for it in items[:40]:
            print("     ", json.dumps({x: y for x, y in it.items() if x != "uuids"}, default=str)[:260])
    print(f"  info: {res['info']}")
    bad = ", ".join(f"{k} {len(res['fails'][k])}" for k in CHECKS if res["fails"][k] and k in res["checks"])
    print(f"qa_copper_landing {res['status']}" + (f": {bad}" if bad else ""))           # last line: the run_gates summary
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
