# ported from din8r-chassis-thermal/scripts/qa_layout_quality.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/qa_layout_quality.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN).
"""Layout quality gate: the defect classes an independent review found on MAIN p2 and UI B8 while every gate passed
CT adaptation (2026-10-17): one board kind "main" (4 layers); every per-board exemption table is EMPTY (no XSTACK,
XTAL, SERIES-TERM, DECAP-PATH, PLANE-SLOT or PLACE-ORIENT exceptions; no RS shunt-ring VIA-PADGAP exemption);
DIFF_PAIRS = the Ethernet MDI / PHY / ETH and USB pairs (no impedance control: own-median gap); REF_LAYERS = In1.Cu
for every signal layer; GROUND_RE = GND / PRTN / VSS; mechanics-pinned parts = J / H / BZ / SW / FID + the light-tube
parts D10-D12, Q22 and the function-pinned ambient sensor U10; current_budget = CT's. Scope corrections (named
constants, they narrow a check to its intent): POWER_PAD_SKIP_LED (an indicator LED is no rail diode),
SERIES_TERM_SKIP_LED (an LED current limiter is no source termination; info series_led_limiters). Deliberate deviation
(CT owner 2026-10-17, "My rule isn't rigid if you can't find any technical reason not to put caps under the chip"):
SERVING_DECAP_ANY_IC_PAD - a back-side serving decap may face any pad of the IC it decouples (signal / NC included).

(docs/records/review/REPORT.md M1-M17 / U1-U7). Owner 2026-10-05: "I shouldn't be catching these"; connected
is not clean, and these must be caught automatically on every cleaning pass. Companion of qa_copper_landing (same CLI,
JSON, exit codes and require()); it gates quality, qa_copper_landing gates connection.

Every check FAILs on its own. No waivers: the only exemptions are the named, documented constants below.
  VIA-INPAD       A via whose centre lies inside an SMD pad FAILs when it does not fit the pad: its disc is not wholly
                  inside the pad copper with >= VIP_MARGIN_MM to spare (e.g. a 0.6 mm via in a 0.3 mm FH12 pad, or an
                  off-centre via leaving its pad), and ANY via in a pad of an 0402 part (NO_VIP_FP_RE on the
                  footprint name; owner 2026-10-05: "absolutely no vias in 0402s...0603 should be ok"). A fitting
                  via-in-pad on any other pad (0603 and up, ICs, exposed pads) is legal, MAIN and UI alike (owner
                  2026-10-05: both boards are ordered with epoxy-filled + capped vias; the former <= 0603 one-pad
                  tombstone FAIL is gone, counted in info vip_one_pad_small2t); counted in info vip_fitting.
                  The same rule as the router's (audit tools/via_site.py) and qa_placement VIA-SITE.
  VIA-PADGAP      A via that does not touch an SMD pad but sits < qa_copper_landing.PADEDGE_GAP_MM from its edge, same or
                  foreign net (no mask dam; solder wicks). The class is qa_copper_landing.padedge_class (one
                  definition, VIA-PADEDGE); it moves into VIA-PADEDGE when PADEDGE_GAP_IN_LANDING is switched on.
  XSTACK          An F.Cu SMD pad and a B.Cu SMD pad of DIFFERENT nets overlapping or < XSTACK_GAP_MM apart in plan
                  when either part is an IC (U), connector (J), crystal / oscillator (X, Y) or has a pad pitch
                  <= FINE_PITCH_MM. XSTACK_ALLOW lists generator-declared intentional stacks (none today; see there).
                  Not defects (owner 2026-10-05): stacking over a no-net connector MP tab, and a SERVING DECAP ("a
                  back-side decoupling cap directly under the IC it decouples ... Yes thats fine"): a two-terminal C*
                  whose two nets both appear on the other part's pads, one a rail / ground (current_budget, RAIL_RE,
                  GND*), whose stacked pads face only pads of that part (CT owner 2026-10-17: ANY of its pads, signal /
                  NC included - SERVING_DECAP_ANY_IC_PAD, a deliberate deviation from the parent's "never a signal
                  pin"), and whose every pad has a same-net via within XSTACK_DECAP_VIA_MM or a fitting via-in-pad
                  (VIA-INPAD rule). Counted in info xstack_serving_decap. Parts under another part's pads, non-cap
                  parts, IC over IC and caps of another part's rails still FAIL.
  TRACK-FOLD      A joint of exactly two same-net same-layer track ends, off any same-net pad / via, whose interior
                  angle is < FOLD_DEG (a spike / hairpin), and two same-net same-layer straight segments that are
                  collinear (< COLLINEAR_DEG), overlap in copper and overlap along their axis by > OVERLAP_MIN_MM without
                  one containing the other (full containment is qa_copper_landing TRACK-DUP).
  ACUTE           At a joint of track ends off pad / via, any two tracks meeting at an interior angle < ACUTE_DEG
                  (2-end joints below FOLD_DEG are TRACK-FOLD), or a branch meeting a through trunk (a T-joint: a
                  track ending on another track's body, or two arms of the joint within TEE_STRAIGHT_DEG of straight)
                  at < ACUTE_T_DEG to it. Acid traps / slivers. No pour exemption (review U5: a GND spur inside the
                  pour passed only through the pour allowance of the older gates).
  THREAD          A foreign-net track (net of none of the part's pads; same outer layer as the part, centreline inside
                  the region by > THREAD_MIN_MM) or a foreign-net via (any layer, centre inside) in the pad hull (convex
                  hull of the part's SMD pads minus the pads) of a two-terminal SMD part no bigger than 1206, or of a
                  part with pad pitch <= FINE_PITCH_MM (ICs and fine-pitch connectors such as FH12). Pin fields of
                  coarser pitch (SOIC 1.27, SOT-23 0.95, relays, terminals, RJ45, test points) are excluded: at >
                  FINE_PITCH_MM a track between pins keeps full clearance and is ordinary routing.
  POWER-PAD-CONN  Power pads connected to their own pour: power-IC exposed pads (an IC's largest pad, >= EP_MIN_MM2),
                  pads of capacitors >= POWER_CAP_MIN_F, inductors and diodes on a current_budget net. Solid (own fill
                  covers >= SOLID_COVER of the pad) passes. On thermal relief: an exposed pad FAILs (it is the heat
                  path); any other pad FAILs when its spokes + same-net track widths are below max(IPC-2152 width of the
                  net's budgeted load / fault current on that copper, POWER_PAD_LAND_FRAC x the pad's narrow side).
  VIA-CURRENT     A layer change (a site = same-net vias within VIA_SITE_MM) of a current_budget net must carry the
                  current that can flow through it: I_site = min(net budget, what the copper on the layers it joins
                  can carry: ampacity of the landing tracks, unlimited for an own-net fill or pad), at the load (DT_LOAD)
                  and at the fault (DT_FAULT) rise. It needs >= ceil(I_site / I_via) vias. I_via is IPC-2152 (the same
                  curve fit as current_budget) for the barrel cross-section pi x drill x VIA_PLATING_UM. FORCE nets are
                  governed by their own gates. Plane nets (GND, GND_ISO, any net with an inner plane; lead 2026-10-05)
                  are bounded by what the site SERVES, not the rail total: I_site also <= the sum, over the pads its
                  local copper reaches (tracks chained from the site's vias, stopping at other vias of the net, and an
                  own-net non-plane fill island it touches, shared pro rata over that island's plane vias), of each
                  pad's part supply current = the largest current_budget load (fault) among the other nets of that
                  pad's footprint (a signal-only part: current_budget.SIGNAL_A).
  NECK-SMALLPAD   A same-net track wider than the SMD pad (of a two-terminal part <= 0603) it enters, measured across
                  the track direction (+ NECK_TOL_MM): solder pull / tombstone.
  POUR-STITCH     An outer-layer fill fragment > STITCH_MIN_MM2 of a net that has an inner plane needs >=
                  max(STITCH_MIN_VIAS, ceil(area / STITCH_MM2_PER_VIA)) vias / plated holes reaching that plane, and no
                  point of it > STITCH_REACH_MM from one.
  DECAP-LOOP      Every decoupling cap (qa_decoupling's pairing: one pad on a supply-like net with a load pin on U / J /
                  L, the other on a ground net): its ground pad needs a ground via within DECAP_GND_VIA_MM of the pad
                  edge or a solid own-net pour connection; caps <= DECAP_HF_MAX_F need a supply copper path <=
                  DECAP_PATH_MM from their supply pad to the nearest load pin (tracks + vias + own-net fill hops).
                  DECAP_PATH_EXEMPT lists documented per-board path exceptions (info decap_path_exempt).
  SERIES-TERM     A series resistor (0 < R <= SERIES_MAX_OHM, both nets signals) sits <= SERIES_PATH_MM copper path from
                  its driver pin. Driver: when only one side's net reaches an IC pin (U), that IC (an IC driving a
                  connector / cable through the resistor, e.g. the UI's M_SCK / M_MOSI); when both sides reach IC pins,
                  the board carries no pin directions, so the resistor must sit at one END of the line (<=
                  SERIES_PATH_MM from an IC pin on either side), never mid-line. SERIES_TERM_EXEMPT lists the
                  owner-declared exceptions (RC EMI filters whose R belongs at the cable connector).
  XTAL            Crystal / oscillator (X*, Y*): every clock net (a crystal / oscillator pad net that is not ground /
                  supply) is <= XTAL_LEN_MM of track (<= XTAL_OSC_LEN_MM for an oscillator output), has no via, and no
                  foreign-net track or via lies within the courtyard + XTAL_KEEPOUT_MM on any layer. XTAL_LEN_EXEMPT
                  lists lead-declared per-ref length limits (that ref and the listed net(s) only; the via and foreign-copper
                  rules still apply; reported in info xtal_len_exempt).
  DIFFPAIR        Declared pairs (DIFF_PAIRS): same layer sequence and via count on both legs, length skew <=
                  DIFF_SKEW_MM, edge gap within +-DIFF_GAP_TOL of nominal over >= DIFF_COUPLED_FRAC of the length away
                  from the pads, >= DIFF_PLANE_FRAC of the length over solid reference plane, width at the
                  current_budget IMPEDANCE width where one is qualified. The skew leaves out the track length inside
                  the pin field of a DIFF_SKEW_PINFIELD part (connector / magnetics: the hull of the pair's pads on
                  it and of the part's net pads within DIFF_PINFIELD_NEIGHBOUR_MM of them, + DIFF_BREAKOUT_MM; info
                  diffpair_pinfield_mm).
  PLANE-SLOT      An SI-critical track (SI_NET_RE) over a void of its reference ground plane (a hole >= PLANE_SLOT_MM in
                  the plane, crossed by > PLANE_CROSS_MM) or over another net's plane region (reference change).
                  REF_POWER_PLANES pours (MAIN In4 +5V) count as reference copper for the void test, so a slot cut into
                  them fails as a void; crossing onto them is still a reference change.
                  PLANE_SLOT_EXEMPT lists documented via-cluster voids per board and net (info plane_slot_exempt).
                  A run inside a PLANE_SLOT_THERMAL_ISLANDS rule area to a pad of its own net in that island is no
                  crossing (info plane_slot_thermal_island).
  FIDUCIAL        Each side carrying a part with pad pitch <= FINE_PITCH_MM needs >= 3 fiducials that span a triangle
                  of >= FID_MIN_TRI_MM2.
  PAD-AXIS        A track leaving a fine-pitch pad (pitch <= FINE_PITCH_MM, pad aspect >= PAD_AXIS_ASPECT) more than
                  PAD_AXIS_DEG off the pad's long axis, unless its direction points away from every other pad of the
                  part within PAD_AXIS_END_PIN_MM (an end pin leaving its row outward; info pad_axis_end_pin).
  VIA-HOP         Two same-net vias < VIA_HOP_MM apart that share copper on exactly one layer (a series hop: down and
                  straight back up). Vias in parallel (sharing copper on >= 2 layers: a current / thermal / stitch
                  array) are not hops.

  PLACE-PINPASSIVE A shunt passive (one pad on a connector pin's signal net with at most one far load, the other on a
                  ground / supply: pull-up / pull-down / termination / filter) sits ON the pin's long axis (signal pad
                  centre within PINPASSIVE_AXIS_MM, pad-to-pad axis within PINPASSIVE_AXIS_DEG), just off its outward end:
                  pad edge gap <= PINPASSIVE_GAP_MM at a connector pin, <= PINPASSIVE_IC_GAP_MM at the far-load IC pin
                  when the part sits nearer that pin; joined by a straight stub once routed (owner 2026-10-05 / -06).
                  FAILs only when an on-axis spot is free (proposed pose); a blocked one is info pinpassive_no_spot.
                  Series parts are SERIES-TERM's (they belong at their driver).
  PLACE-ORIENT    An IC (>= ORIENT_MIN_PINS) whose airwire (pins to the nearest same-net targets off its satellites)
                  another rotation cuts by ORIENT_ROT_GAIN, whose pin links point behind their pins (facing), that sits
                  > ORIENT_POS_MM from a pose halving its airwire, or that is powered from a connector rail and wired to
                  its pins while sitting > IFACE_MM from them (cable interface; owner 2026-10-05, U904).

KiCad Python: local_run.py qa_layout_quality.py BOARD [--json OUT] [--checks A,B]. Exit 0 PASS, 1 FAIL, 2 error (fail
closed). require(board, out_json) raises on any FAIL; counts(board) is the routing driver's per-stage metric hook.
Not wired into fab_outputs / ui_release yet (lead 2026-10-05: after the UI B8.1 release).
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as K  # noqa: E402,F401  (first: tools/pylib shapely for KiCad's Python)
import pcbnew  # noqa: E402
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.prepared import prep  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

import current_budget as cb  # noqa: E402
import qa_copper_landing as QL  # noqa: E402

# ------------------------------------------------------------------------------------------------ named constants
FINE_PITCH_MM = 0.65            # a part with pad pitch <= this is fine pitch (XSTACK, THREAD, FIDUCIAL, PAD-AXIS)
SMALL_2T_SPAN_MM = 2.6          # 2-terminal part "<= 0603": its two pads span <= this (0603 IPC land 2.45, 0805 2.85)
MID_2T_SPAN_MM = 4.3            # 2-terminal part "<= 1206": span <= this (1206 land 4.1) ...
MID_2T_WIDTH_MM = 2.0           # ... and pad width <= this (1210's 2.7 mm pads excluded; SOD-123F 1.1 included)
VIP_MARGIN_MM = 0.05            # VIA-INPAD: the via disc stays this far inside the pad copper
NO_VIP_FP_RE = re.compile(r".")   # SBC-1 (lead 2026-10-26): JLC 2-layer, NO via fill -> no via in ANY pad (EPs too);
                                # CT / DIN-8R: (?<![0-9])0402(?![0-9])|1005Metric with filled vias. Was: "absolutely no vias in
                                # 0402s ... 0603 should be ok" (CT keeps it: epoxy-filled + capped vias, 0603+ only)
# SBC-1 DECISIONS #3 (lead 2026-10-27): the ONE via-in-pad exception - plain thermal vias in these exposed pads (RP2350B
# U5.81 3 x 3 grid per Raspberry Pi's 2-layer reference, MAX98357A U8.17, TPS259531 U1.9); they must still fit (vip_fits)
VIA_INPAD_EP_PADS = frozenset({("U5", "81"), ("U8", "17"), ("U1", "9")})
XSTACK_GAP_MM = 0.30            # XSTACK: F / B pads of different nets closer than this in plan
XSTACK_ALLOW = {}               # XSTACK: generator-declared intentional F / B stacks {(ref_a, ref_b): reason} - none on CT
XSTACK_DECAP_VIA_MM = 1.0       # XSTACK serving decap: each cap pad has a same-net via within this (or a fitting VIP)
# XSTACK serving decap rule (b), DELIBERATE CT DEVIATION from the parent's 2026-10-05 wording ("its own-net, exposed or
# no-net pads, never a signal pin"): CT owner 2026-10-17, "My rule isn't rigid if you can't find any technical reason
# not to put caps under the chip" - root's review found none (4-layer inner planes separate the pads, JLC two-side
# reflow handles 0402s under a QFN, the via path is gated by qa_power_layout DECAP). A back-side decap may therefore face
# ANY pad of the IC it decouples (own-net, EP, NC or signal). Unchanged: (a) both cap nets on that IC, one a rail /
# ground; (c) a same-net via within XSTACK_DECAP_VIA_MM or a fitting via-in-pad (never in an 0402: VIA-INPAD); a part
# under ANOTHER part's pads, IC over IC, a non-cap part or a cap of another part's rails still FAILs. (QA_LOG
# HW-SERVING-DECAP)
SERVING_DECAP_ANY_IC_PAD = True
FOLD_DEG = 10.0                 # TRACK-FOLD: interior angle of a 2-end joint below this is a spike / hairpin
COLLINEAR_DEG = 1.0             # TRACK-FOLD: segments within this of parallel are collinear (or, within FOLD_DEG,
                                # the shorter lies within a quarter of the narrower width of the longer's axis)
OVERLAP_MIN_MM = 0.05           # TRACK-FOLD: collinear same-net segments overlapping along their axis by more than this
ANGLE_TOL_DEG = 0.5             # TRACK-FOLD / ACUTE / PAD-AXIS: angle rounding tolerance (a 90.0 deg L-bend is not acute)
ACUTE_DEG = 90.0                # ACUTE: interior angle between two track ends at a joint
ACUTE_T_DEG = 45.0              # ACUTE: a track ending on another's body at less than this to it
TEE_STRAIGHT_DEG = 5.0          # ACUTE: two arms of a joint within this of straight form a through trunk (a T-joint)
THREAD_MIN_MM = 0.05            # THREAD: a track centreline this far inside the between-pads region
EP_MIN_MM2 = 2.0                # POWER-PAD-CONN: an IC's largest pad at least this big is its exposed / thermal pad
POWER_CAP_MIN_F = 9.9e-6        # POWER-PAD-CONN: bulk caps >= 10 uF
SOLID_COVER = 0.90              # POWER-PAD-CONN / DECAP-LOOP: own fill covering this much of the pad = solid connection
POWER_PAD_LAND_FRAC = 1.0       # POWER-PAD-CONN: thermal connection at least this x the pad's narrow side
SPOKE_RING = (0.03, 0.08)       # POWER-PAD-CONN: spokes measured in this band (mm) beyond the pad edge
VIA_SITE_MM = 1.2               # VIA-CURRENT: same-net vias with centres this close form one layer-change site
VIA_PLATING_UM = 18.0           # VIA-CURRENT: barrel copper, JLCPCB minimum hole-wall copper (IPC-6012 class 2: 20 avg)
NECK_TOL_MM = 0.005             # NECK-SMALLPAD: tolerance on "wider than the pad"
STITCH_MIN_MM2 = QL.STITCH_MIN_MM2           # POUR-STITCH: fragments larger than this are gated
STITCH_MM2_PER_VIA = QL.STITCH_MM2_PER_VIA   # POUR-STITCH: one plane via per this much fragment area ...
STITCH_MIN_VIAS = QL.STITCH_MIN_VIAS         # ... and never fewer than this (shared with VIA-BARE: one source)
STITCH_REACH_MM = QL.STITCH_REACH_MM            # POUR-STITCH: no point of a fragment farther than this from a
STITCH_BACKED_FRAC = 0.9        # POUR-STITCH (D-LAYOUT-GATES #9c): a fragment >= this share over its net's own inner
STITCH_MM2_PER_VIA_BACKED = 50.0  # plane fill is BACKED: one plane via per this much area, reach measured off-plane only,
STITCH_SMALL_MM2 = 25.0         # and a backed pad island <= this needs one plane via (tight F-In1 0.2 mm coupling)
STITCH_REACH_TOL_MM2 = QL.STITCH_REACH_TOL_MM2  # plane via; uncovered area below this is rounding (shared w/ VIA-BARE)
DECAP_GND_VIA_MM = 0.8          # DECAP-LOOP: ground via within this of the ground pad edge
DECAP_HF_MAX_F = 100e-9         # DECAP-LOOP: supply path rule applies to caps up to this value (100 nF)
DECAP_PATH_MM = 3.0             # DECAP-LOOP: supply copper path cap pad -> nearest load pin
SERIES_MAX_OHM = 220.0          # SERIES-TERM: resistors up to this are series terminations
SERIES_PATH_MM = 3.0            # SERIES-TERM: copper path from the driver pin
XTAL_LEN_MM = 5.0               # XTAL: crystal net track length
XTAL_OSC_LEN_MM = 3.0           # XTAL: oscillator output net track length
XTAL_KEEPOUT_MM = 0.5           # XTAL: courtyard grown by this is foreign-copper free on every layer
WHY_Y2 = "D-LAYOUT-GATES XTAL (root-approved, owner-run 2026-10-17): W5500 XI / XO pins 30 / 31 sit next to the SPI pins - the CS lane (pin 32) holds the courtyard below y 28.3 and U9's courtyard holds the centre at x >= 43.5 - and the 3225 land's diagonal signal pads put one net >= 4.9 mm (45 deg) from its pin before the 18 pF / 1 M branches; no via, keep-out clean. Parent: din8r-main Y600 9.52 / 9.43 mm on this gate, X2 5.6 mm"
WHY_Y1 = 'D-LAYOUT-GATES XTAL (root-approved, owner-run 2026-10-17): ESP32-S3 XTAL_P / XTAL_N pins 54 / 53 on the 0.4 mm north row - the crystal sits north of the pin 47-52 escape lanes and east of the eFuse ILM via-in-pad (R34, x 82.97), its GND pad 2 holds the XTAL_P lane at x 84.2; no via, keep-out clean. Parent: Y600 9.52 / 9.43 mm on this gate, X2 5.6 mm'
# XTAL length exceptions {kind: {ref: [{"net", "max_mm", "reason"}, ...]}} (one dict = one net); max_mm = measured + <= 0.1 mm
XTAL_LEN_EXEMPT = {"main": {}}   # SBC-1: none (CT's Y1 / Y2 rows were CT parts)
DIFF_SKEW_MM = 1.27             # DIFFPAIR: |len P - len N|
DIFF_GAP_TOL = 0.5              # DIFFPAIR: edge gap within +-50 % of nominal ...
DIFF_COUPLED_FRAC = 0.90        # ... over this fraction of the length outside the breakout zones
DIFF_BREAKOUT_MM = 1.0          # DIFFPAIR: within this of a pad the pair may split (breakout)
DIFF_PLANE_FRAC = 0.90          # DIFFPAIR: fraction of length over solid reference plane
WHY_PINFIELD = ("D-LAYOUT-GATES #6 (root-approved, owner-run 2026-10-17): connector / magnetics pin field - the "
                "2.54 mm pitch, the RJ45 stagger and the 3 / 6 receive split fix one leg longer there; 100BASE-TX: "
                "~3 mm ~ 20 ps vs an 8 ns symbol; the routed part keeps DIFF_SKEW_MM")
DIFF_SKEW_PINFIELD = {"main": {}}   # SBC-1: no pin-field exemption declared (CT: its J1 / T1)   # DIFFPAIR: skew is measured outside
                                # these parts' pin fields (hull of the pair's pads on the part and the part's
                                # net pads within DIFF_PINFIELD_NEIGHBOUR_MM of them, + DIFF_BREAKOUT_MM)
DIFF_PINFIELD_NEIGHBOUR_MM = 2.1   # DIFFPAIR pin field: + the part's net pads within this (centre) of the pair's
                                # pads - one RJ45 diagonal pitch (2.05 mm): J1's 3 / 6 split spans pins 4 / 5
                                # (D-LAYOUT-GATES #6b, root-reviewed)
PLANE_SLOT_MM = 3.0             # PLANE-SLOT: a plane void at least this long (min rotated rectangle long side)
PLANE_CROSS_MM = 0.2            # PLANE-SLOT: a track over a void / foreign plane for more than this
PLANE_MOAT_MM = 0.35            # PLANE-SLOT: copper-free gap within this of both GND and a REF_POWER_PLANES pour
PLANE_SLOT_THERMAL_ISLANDS = ("TEMP_SENSOR_ISLAND",)   # PLANE-SLOT: declared pour-free thermal islands (rule
                                # areas): a track's run inside one to a pad of its own net there is no slot
                                # crossing (D-LAYOUT-GATES PLANE-SLOT, owner-run 2026-10-17: U10 GX112S I2C)
FID_MIN_TRI_MM2 = 50.0          # FIDUCIAL: the 3 fiducials span at least this triangle area (non-collinear)
PAD_AXIS_DEG = 10.0             # PAD-AXIS: exit direction off the pad's long axis
PAD_AXIS_ASPECT = 1.4           # PAD-AXIS: pads at least this elongated have a long axis
PAD_AXIS_END_PIN_MM = 2.0       # PAD-AXIS: an exit pointing away from every other pad of the part within this
                                # (centre distance) is no finding - the end pin of a row leaving it outward has no
                                # neighbour to bridge to (D-LAYOUT-GATES PAD-AXIS, owner-run 2026-10-17: U1.1 -> C6)
VIA_HOP_MM = 1.2                # VIA-HOP: same-net vias closer than this
DECAP_FANOUT_MAX_F = 1.0e-6     # VIA-CURRENT: ceramic decaps up to this carry only charge current through their fan-out ...
DECAP_FANOUT_A = 0.5            # ... bounded at this (RMS, A)
PINPASSIVE_GAP_MM = 2.0         # PLACE-PINPASSIVE: pad edge gap to the connector pin pad, at most
PINPASSIVE_IC_GAP_MM = 1.0      # PLACE-PINPASSIVE: ... at a far-load IC pin
PINPASSIVE_AXIS_MM = 0.1        # PLACE-PINPASSIVE: the signal pad centre lies on the pin's long axis within this ...
PINPASSIVE_AXIS_DEG = 10.0      # ... and the passive's pad-to-pad axis runs along it within this
PINPASSIVE_SPOT_GAPS = (0.5, 0.3, 0.8, 1.0, 1.5, 2.0)   # PLACE-PINPASSIVE: proposed spot pad edge gaps, tried in order
PINPASSIVE_EXIT_W = 0.2         # PLACE-PINPASSIVE spot search: neighbouring signal pins' straight exit corridors stay open
PINPASSIVE_EXIT_MM = 3.0
PINPASSIVE_NEIGHBOUR_MM = 2.0
ORIENT_MIN_PINS = 6             # PLACE-ORIENT: ICs (ref U) with at least this many numbered pads
ORIENT_BIG_NET = 12             # PLACE-ORIENT: nets with more pads than this are rails (no airwire target)
ORIENT_ROT_GAIN = 0.25          # PLACE-ORIENT: another rotation cuts the airwire by at least this fraction ...
ORIENT_MIN_GAIN_MM = 2.0        # ... and by at least this much (sub-mm noise on tiny parts is not a finding)
ORIENT_FACE_DEG = 120.0         # PLACE-ORIENT facing: a pin link pointing more than this off the pin's outward normal ...
ORIENT_FACE_MM = 2.0            # ... to a partner farther than this is "behind"
ORIENT_FACE_MIN = 2             # PLACE-ORIENT facing: at least this many links behind ...
ORIENT_FACE_FRAC = 0.25         # ... and this fraction of the links, and a turn removing >= ORIENT_FACE_MIN, half of them
ORIENT_FACE_NET_PARTS = 5       # PLACE-ORIENT facing: nets with more parts than this are buses (no link)
ORIENT_POS_GAIN = 0.50          # PLACE-ORIENT: a pose (any rotation) that cuts the airwire by at least this fraction ...
ORIENT_POS_MM = 5.0             # ... lying farther than this from the IC's centre
IFACE_MM = 6.0                  # PLACE-ORIENT cable interface: mean airwire of the cable pins to their connector pins
# PLACE-PINPASSIVE / PLACE-ORIENT: parts pinned by mechanics never move and never count as movable blockers. CT:
# connectors (J), mounting holes (H), buzzer (BZ), push buttons (SW), fiducials, and the enclosure-bound light parts
# (the PWR / SYS / NET LEDs D10-D12 and the ALS Q22 sit under the lid light tubes - RESUME: enclosure-bound parts
# never move)
PLACE_MECH_RE = re.compile(r"^(J|H|BZ|SW|FID)\d")
PLACE_MECH_REFS = set()      # SBC-1: none beyond PLACE_MECH_RE (CT: lid light-tube LEDs, ambient sensor)
# CT scope corrections (named, with reasons; they narrow a check to its intent, never excuse a defect of that class):
POWER_PAD_SKIP_LED = True       # POWER-PAD-CONN "rail diode": an indicator LED (LED_* footprint) carries mA, not its rail's
                                # budget (DECAP-LOOP already treats LED footprints as loads, not power parts)
SERIES_TERM_SKIP_LED = True     # SERIES-TERM: a resistor whose far net reaches only LED pads is the LED's current limiter,
                                # not a source termination (counted in info series_led_limiters)
WHY_U1 = 'D-LAYOUT-GATES cell (root-approved, owner-run 2026-10-17): placed by the HW-ADVQA2 flyback cell (eco_advqa2.py) on the PoE input side for the VPP / VSS / bridge hot path; the far pins are the slow T2P / CTL opto lines (U4 / U3 at the barrier) and RT2P'
WHY_R16 = "D-LAYOUT-GATES cell (root-approved, owner-run 2026-10-17): TPS23751 RVC bias resistor (SLVSB97E 8.2.2.12) on the controller's VC supply pin, not a signal source termination; the U1.12 cluster (C8 / C9 / C14 / R11 / R14) has no 3 mm spot left (qa_power_layout DECAP balance)"
PLACE_ORIENT_EXEMPT = {"main": {}}   # SBC-1: none (CT: flyback cell U1)   # {kind: {ref: reason}} parts placed by a cell / mechanics generator
SERIES_TERM_EXEMPT = {"main": {}}    # SBC-1: none (CT: R16 bias resistor)    # {kind: {ref: reason}} owner-declared non-termination series resistors
DECAP_PATH_EXEMPT = {"main": {}}     # {kind: {ref: reason}} documented supply-path exceptions - none
PLANE_SLOT_EXEMPT = {"main": []}     # documented via-cluster voids - none
# Declared differential pairs (DIFFPAIR). CT orders no impedance control (docs/ORDERING.md item 16), so every nominal
# gap is None: checked against the pair's own length-weighted median gap (uniform coupling, the parent's UI USB rule).
# Ethernet: MDI (RJ45 J1 <-> T1 cable side), PHY (T1 <-> the W5500 network: R / C), ETH (W5500 pins <-> those parts);
# USB: USB_DP / USB_DN (R89 / R90 <-> U7). USB_C_DP / USB_C_DN are the receptacle's duplicated A6/B6, A7/B7 stubs (the
# D+ crossover needs a via on one leg only), not a routed pair - not declared (the parent's UI J2 rule).
DIFF_PAIRS = {"main": [("MDI_TXP", "MDI_TXN", None), ("MDI_RXP", "MDI_RXN", None), ("RJ_RDP", "RJ_RDN", None),
                       ("ETH_TXP", "ETH_TXN", None), ("ETH_RXP", "ETH_RXN", None),
                       ("USB_DP", "USB_DM", None), ("USBH_DP_C", "USBH_DM_C", None)]}
# SBC-1 pairs (2026-10-27): W5500 -> R27-R30 (ETH_*) -> magjack J3 (MDI_* / RJ_RD*); RP2350 USB (USB_D*) -> R74 / R75 ->
# J9 display micro-B (USBH_D*_C). DBG_DP / DBG_DM are the USB-C receptacle's duplicated A6/B6, A7/B7 stubs (CT's rule for
# its USB_C_D*): not declared.
# SI-critical nets (PLANE-SLOT): W5500 SPI, crystals (40 MHz XTAL40_*, 25 MHz ETH_XI / XO), MDI / PHY / ETH pairs,
# USB, I2C
SI_NET_RE = re.compile(r"(SCK|SCLK|MOSI|MISO|_CS\d*$|_CS\d*_|nCS|CS_N|CLK|XI$|XO$|_XI|_XO|XIN|XOUT|XTAL|MDI_|"
                       r"RJ_RD|ETH_(TX|RX)[PN]|USB_D[PM]|USBH_D[PM]|DBG_D[PM]|QSPI_|I2S_|SDA|SCL)")   # SBC-1 nets
# Reference planes per signal layer (PLANE-SLOT / DIFFPAIR): In1.Cu is CT's solid plane layer (GND SEC / PRTN PRI,
# never routed); the parent's 4-layer UI on the same JLC04161H-7628 stack referenced F, In2 AND B to In1 (In2 / B pours
# are cut by routing; In1 is the continuous return)
REF_LAYERS = {"main": {"F.Cu": ["In1.Cu"], "In2.Cu": ["In1.Cu"], "B.Cu": ["In1.Cu"]}}   # SBC-1 4-layer (DECISIONS #7:
# In1 = solid GND plane, never routed; q5 2026-10-27): the 2-layer value F <-> B was left behind by the 4-layer move -
# with no F.Cu GND pour it hid every finding, and any small F.Cu GND patch (GND_J1_F) flagged every B.Cu SI track
REF_POWER_PLANES = {"main": {}}      # designated power reference pours - none on SBC-1
GROUND_RE = re.compile(r"^GND$")   # SBC-1 return: GND only

CHECKS = ("VIA-INPAD", "VIA-PADGAP", "XSTACK", "TRACK-FOLD", "ACUTE", "THREAD", "POWER-PAD-CONN", "VIA-CURRENT",
          "NECK-SMALLPAD", "POUR-STITCH", "DECAP-LOOP", "SERIES-TERM", "XTAL", "DIFFPAIR", "PLANE-SLOT", "FIDUCIAL",
          "PAD-AXIS", "VIA-HOP", "PLACE-PINPASSIVE", "PLACE-ORIENT")
mm = pcbnew.ToMM
P, where, to_shapely = QL.P, QL.where, QL.to_shapely
SMD = (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)


def r3(q):
    return (round(q[0], 3), round(q[1], 3))


def unit(a, b):
    d = math.dist(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d > 1e-9 else None


def angle(u, v):
    """unsigned angle (deg, 0..180) between two direction vectors"""
    return abs(math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])))


def farads(v):
    m = re.match(r"\s*([\d.]+)\s*([pnuµm]?)F", v or "")
    if not m:
        return None
    return float(m.group(1)) * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0}[m.group(2)]


def ohms(v):
    m = re.match(r"\s*([\d.]+)\s*([kKmMR]?)(\d*)", v or "")
    if not m or not m.group(1):
        return None
    base = float(m.group(1) + ("." + m.group(3) if m.group(3) and m.group(2) else ""))
    return base * {"k": 1e3, "K": 1e3, "M": 1e6, "m": 1e-3, "R": 1.0, "": 1.0}[m.group(2)]


def ipc_amps(area_mil2, dt_k):
    """inverse of current_budget.ipc2152_area_mil2: the current a cross-section carries at a rise of dt_k"""
    if area_mil2 <= 0:
        return 0.0
    k1 = 117.555 * dt_k ** -0.913 + 1.15
    k2 = 0.84 * dt_k ** -0.018 + 1.159
    return (area_mil2 / k1) ** (1.0 / k2)


def via_amps(drill_mm, dt_k):
    """IPC-2152 current of a via barrel: cross-section pi x drill x VIA_PLATING_UM"""
    area_mm2 = math.pi * drill_mm * VIA_PLATING_UM / 1000.0
    return ipc_amps(area_mm2 / 0.0254 ** 2, dt_k)


def track_amps(width_mm, cu_um, dt_k):
    return ipc_amps(width_mm * cu_um / 1000.0 / 0.0254 ** 2, dt_k)


class Board:
    """geometry of one loaded board, shared by every check"""

    def __init__(self, pcb):
        self.path = str(pcb)
        b = self.b = pcbnew.LoadBoard(str(pcb))
        self.kind = QL.board_kind(b)
        self.lname = b.GetLayerName
        self.layers = {b.GetLayerName(L): L for L in b.GetEnabledLayers().CuStack()}
        self.outer = (pcbnew.F_Cu, pcbnew.B_Cu)
        self.pour = QL.POUR_NETS[self.kind]
        self.force = QL.FORCE_NETS[self.kind]
        # pads
        self.pads, self.fps = [], {}
        for fp in b.GetFootprints():
            ref = fp.GetReference()
            rec = {"obj": fp, "ref": ref, "fpid": str(fp.GetFPID().GetLibItemName()), "value": fp.GetValue(),
                   "side": pcbnew.B_Cu if fp.IsFlipped() else pcbnew.F_Cu, "pads": []}
            self.fps[ref] = rec
            for p in fp.Pads():
                smd = p.GetAttribute() in SMD
                lays = [L for L in p.GetLayerSet().CuStack() if L in self.layers.values()]
                poly = {L: to_shapely(p.GetEffectivePolygon(L)) for L in lays if L in self.outer or not smd}
                if not poly:
                    continue
                sz = p.GetSize(lays[0])
                d = {"obj": p, "i": len(self.pads), "ref": ref, "num": p.GetNumber(), "net": p.GetNetname(),
                     "smd": smd, "pth": p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH, "layers": lays, "poly": poly,
                     "pos": P(p.GetPosition()), "w": mm(sz.x), "h": mm(sz.y),
                     "rot": p.GetOrientation().AsDegrees(), "fp": rec}
                d["area"] = next(iter(poly.values())).area
                self.pads.append(d)
                rec["pads"].append(d)
        for rec in self.fps.values():
            self._classify(rec)
        # tracks / vias
        self.tracks, self.vias = [], []
        for t in b.GetTracks():
            if t.GetNetCode() <= 0:
                continue
            if t.Type() == pcbnew.PCB_VIA_T:
                q = P(t.GetPosition())
                d = mm(t.GetWidth(pcbnew.F_Cu))
                self.vias.append({"obj": t, "i": len(self.vias), "net": t.GetNetname(), "pos": q, "d": d,
                                  "drill": mm(t.GetDrillValue()), "disc": Point(q).buffer(d / 2),
                                  "layers": [L for L in t.GetLayerSet().CuStack() if L in self.layers.values()]})
                continue
            a, e = P(t.GetStart()), P(t.GetEnd())
            arc = t.Type() == pcbnew.PCB_ARC_T
            m = P(t.GetMid()) if arc else None
            line = LineString([a, m, e]) if arc else (LineString([a, e]) if a != e else Point(a))
            w = mm(t.GetWidth())
            self.tracks.append({"obj": t, "i": len(self.tracks), "net": t.GetNetname(), "layer": t.GetLayer(),
                                "a": a, "e": e, "mid": m, "arc": arc, "w": w, "len": mm(t.GetLength()),
                                "line": line, "cu": line.buffer(w / 2)})
        self.t_tree = STRtree([t["cu"] for t in self.tracks])
        self.v_tree = STRtree([v["disc"] for v in self.vias])
        self.p_tree = {}
        self.p_list = {}
        for L in self.layers.values():
            lst = [p for p in self.pads if L in p["poly"]]
            self.p_list[L] = lst
            self.p_tree[L] = STRtree([p["poly"][L] for p in lst]) if lst else None
        self.zones = defaultdict(list)
        for z in b.Zones():
            if not z.GetIsRuleArea() and z.GetNetCode() > 0:
                self.zones[z.GetNetname()].append(z)
        self._fill = {}
        self.cls_w = {}
        pro = Path(self.path).with_suffix(".kicad_pro")
        if pro.exists():
            self.cls_w = {c["name"]: c.get("track_width") for c in
                          json.loads(pro.read_text(encoding="utf-8")).get("net_settings", {}).get("classes", [])}
        self._joints()

    # ---------------------------------------------------------------- helpers
    def _classify(self, rec):
        ps = [p for p in rec["pads"] if p["smd"] and p["num"]]
        rec["smd_pads"] = ps
        rec["two_term"] = len(rec["pads"]) == 2 and len(ps) == 2
        rec["span"] = rec["width"] = None
        rec["pitch"] = None
        if len(ps) >= 2:
            areas = sorted(p["area"] for p in ps)
            med = areas[len(areas) // 2]
            sig = [p for p in ps if p["area"] <= 2.0 * med]          # pin pads (an EP / mounting pad excluded)
            ds = [math.dist(a["pos"], c["pos"]) for i, a in enumerate(sig) for c in sig[i + 1:]
                  if a["layers"] == c["layers"]]
            rec["pitch"] = min(ds) if ds else None
        if rec["two_term"]:
            u = unary_union([next(iter(p["poly"].values())) for p in ps])
            mr = u.minimum_rotated_rectangle
            xs = list(mr.exterior.coords)
            e1, e2 = math.dist(xs[0], xs[1]), math.dist(xs[1], xs[2])
            rec["span"] = max(e1, e2)
            rec["width"] = min(e1, e2)
        rec["small2t"] = rec["two_term"] and rec["span"] <= SMALL_2T_SPAN_MM
        rec["mid2t"] = rec["two_term"] and rec["span"] <= MID_2T_SPAN_MM and rec["width"] <= MID_2T_WIDTH_MM
        rec["fine"] = len(ps) >= 4 and rec["pitch"] is not None and rec["pitch"] <= FINE_PITCH_MM + 1e-3
        rec["sensitive"] = rec["fine"] or rec["ref"][:1] in ("U", "J", "X", "Y")

    def fill(self, net, L):
        k = (net, L)
        if k not in self._fill:
            zs = [z for z in self.zones.get(net, ()) if z.IsOnLayer(L)]
            g = unary_union([to_shapely(z.GetFilledPolysList(L)) for z in zs]) if zs else Polygon()
            self._fill[k] = (g, prep(g))
        return self._fill[k]

    def pads_near(self, L, geom):
        if self.p_tree.get(L) is None:
            return []
        return [self.p_list[L][i] for i in self.p_tree[L].query(geom)]

    def pad_ref(self, p):
        return f"{p['ref']}.{p['num']}"

    def flash(self, v, L):
        o = v["obj"]
        return L in v["layers"] and (not hasattr(o, "FlashLayer") or o.FlashLayer(L))

    def on_pad_or_via(self, net, L, q):
        pt = Point(q)
        if any(p["net"] == net and p["poly"][L].intersects(pt) for p in self.pads_near(L, pt)):
            return True
        return any(self.vias[i]["net"] == net and L in self.vias[i]["layers"] and self.vias[i]["disc"].intersects(pt)
                   for i in self.v_tree.query(pt))

    def _joints(self):
        """track ends of the same net / layer within each other's copper are one joint (qa_copper_landing rule)"""
        uf = QL.UF()
        ends = defaultdict(list)
        for t in self.tracks:
            for q in (t["a"], t["e"]):
                ends[(t["net"], t["layer"])].append((q, t["w"], t["i"]))
                uf.find((t["layer"], q))
        for (net, L), lst in ends.items():
            grid = defaultdict(list)
            for q, w, i in lst:
                grid[(int(q[0] // 0.25), int(q[1] // 0.25))].append((q, w, i))
            for (gx, gy), cell in grid.items():
                near = [x for dx in (-1, 0, 1) for dy in (-1, 0, 1) for x in grid.get((gx + dx, gy + dy), ())]
                for q, w, i in cell:
                    for q2, w2, i2 in near:
                        if i2 != i and q2 != q and math.dist(q, q2) <= min(w, w2) / 2:
                            uf.union((L, q), (L, q2))
        self.joint = defaultdict(list)            # joint id -> [(track idx, end point, far direction point)]
        for t in self.tracks:
            if t["len"] < 1e-4:
                continue
            ja, je = uf.find((t["layer"], t["a"])), uf.find((t["layer"], t["e"]))
            if ja == je:
                continue                          # a micro-segment inside one joint has no direction out of it
            for q, far, j in ((t["a"], t["mid"] or t["e"], ja), (t["e"], t["mid"] or t["a"], je)):
                self.joint[(t["net"], t["layer"], j)].append((t["i"], q, far))
        self.ends = ends
        self.J = lambda L, q: uf.find((L, q))

    def neighbours(self, t, L=None):
        L = t["layer"] if L is None else L
        return [self.tracks[i] for i in self.t_tree.query(t["cu"]) if i != t["i"]
                and self.tracks[i]["layer"] == L and self.tracks[i]["net"] == t["net"]]


# ==================================================================================================== checks
def vip_fits_poly(poly, c, r):
    """VIA-INPAD fit rule: the via disc (centre c, radius r) wholly inside the pad copper with >= VIP_MARGIN_MM to spare
    (1 um rounding slack)"""
    return poly.buffer(-VIP_MARGIN_MM + 1e-3).contains(Point(c).buffer(r))


def vip_fits(p, v, L):
    return vip_fits_poly(p["poly"][L], v["pos"], mm(v["obj"].GetWidth(L)) / 2)


def chk_via_inpad(B, fails, info):
    fit = defaultdict(int)
    per_pad = defaultdict(int)                 # fitting / any VIP per pad (small 2-terminal asymmetry)
    for v in B.vias:
        c = Point(v["pos"])
        for L in B.outer:
            if not B.flash(v, L):
                continue
            for p in B.pads_near(L, c):
                if not p["smd"] or not p["poly"][L].contains(c):
                    continue
                per_pad[p["i"]] += 1
                if NO_VIP_FP_RE.search(p["fp"]["fpid"]) and (p["ref"], p["num"]) not in VIA_INPAD_EP_PADS:
                    fails["VIA-INPAD"].append({"net": v["net"], "pad": B.pad_ref(p), "pad_net": p["net"],
                                               "layer": B.lname(L), "at": v["pos"], "via_d": v["d"],
                                               "fp": p["fp"]["fpid"], "what": "via in a pad (SBC-1: no via fill, "
                                               "EP thermal vias only - DECISIONS #3)", "uuids": [v["obj"].m_Uuid.AsString()]})
                elif not vip_fits(p, v, L):
                    fails["VIA-INPAD"].append({"net": v["net"], "pad": B.pad_ref(p), "pad_net": p["net"],
                                               "layer": B.lname(L), "at": v["pos"], "via_d": v["d"],
                                               "pad_wh": [round(p["w"], 3), round(p["h"], 3)],
                                               "what": f"via does not fit the pad (d > pad min dimension - 2 x "
                                                       f"{VIP_MARGIN_MM} mm, or its disc leaves the pad)",
                                               "uuids": [v["obj"].m_Uuid.AsString()]})
                else:
                    fit["shunt" if p["ref"].startswith("RS") else "exposed / large pad" if p["area"] >= EP_MIN_MM2
                        else "small land"] += 1
    one = 0                                    # owner 2026-10-05: a fitting VIP is legal on any pad size (info only)
    for rec in B.fps.values():
        if rec["small2t"]:
            n = [per_pad[p["i"]] for p in rec["smd_pads"]]
            one += (n[0] == 0) != (n[1] == 0)
    info["vip_fitting"] = dict(fit)
    info["vip_one_pad_small2t"] = one


def chk_via_padgap(B, fails, info):
    for v in B.vias:
        c = Point(v["pos"])
        for L in B.outer:
            if not B.flash(v, L):
                continue
            r = mm(v["obj"].GetWidth(L)) / 2
            hit = False
            for p in B.pads_near(L, c.buffer(r + QL.PADEDGE_GAP_MM)):
                if not p["smd"]:
                    continue
                cls, ov, gap = QL.padedge_class(p["poly"][L], c, r, p["net"] == v["net"])
                if cls == "gap":
                    fails["VIA-PADGAP"].append({"net": v["net"], "pad": B.pad_ref(p), "pad_net": p["net"],
                                                "layer": B.lname(L), "at": v["pos"], "gap_mm": round(gap, 3),
                                                "uuids": [v["obj"].m_Uuid.AsString()]})
                    hit = True
                    break
            if hit:
                break


def chk_xstack(B, fails, info):
    fp_ = [p for p in B.p_list[pcbnew.F_Cu] if p["smd"] and p["fp"]["side"] == pcbnew.F_Cu]
    bp_ = [p for p in B.p_list[pcbnew.B_Cu] if p["smd"] and p["fp"]["side"] == pcbnew.B_Cu]
    if not fp_ or not bp_:
        return
    tree = STRtree([p["poly"][pcbnew.B_Cu] for p in bp_])
    pairs = defaultdict(list)
    for p in fp_:
        g = p["poly"][pcbnew.F_Cu]
        for k in tree.query(g.buffer(XSTACK_GAP_MM)):
            q = bp_[k]
            if q["net"] == p["net"] and p["net"]:
                continue
            if not (p["fp"]["sensitive"] or q["fp"]["sensitive"]):
                continue
            # owner 2026-10-05: a stack is "only an issue if it's a functional / quality problem". A no-net mechanical
            # anchor pad (a connector's MP solder tab) carries no signal, blocks no via that a net needs and has no
            # isolation to keep, so stacking over it is not a defect (UI B8: C2012 / R2001 / U2011 over J1.MP)
            if any(not x["net"] and B.pad_ref(x).split(".")[-1].upper().startswith("MP") for x in (p, q)):
                info["xstack_mech_tab_skipped"] = info.get("xstack_mech_tab_skipped", 0) + 1
                continue
            d = g.distance(q["poly"][pcbnew.B_Cu])
            if d >= XSTACK_GAP_MM:
                continue
            key = tuple(sorted((p["ref"], q["ref"])))
            if key in XSTACK_ALLOW:
                info.setdefault("xstack_allowed", []).append(key)
                continue
            pairs[key].append((B.pad_ref(p), B.pad_ref(q), round(d, 3), p["net"], q["net"], p["pos"], p, q))
    for (a, c), lst in sorted(pairs.items()):
        if serving_decap(B, lst):
            info["xstack_serving_decap"] = info.get("xstack_serving_decap", 0) + 1
            info.setdefault("xstack_serving_decap_pairs", []).append([a, c])
            continue
        lst.sort(key=lambda x: x[2])
        fails["XSTACK"].append({"parts": [a, c], "pad_pairs": len(lst), "worst": lst[0][:5], "at": lst[0][5],
                                "what": "F / B pads of different nets " + ("overlap" if lst[0][2] == 0 else
                                                                            f"{lst[0][2]} mm apart")})


def is_rail(B, net):
    return bool(net) and (bool(GROUND_RE.match(net)) or bool(cb.RAIL_RE.match(net)) or net in cb.BUDGET[B.kind])


def serving_decap(B, lst):
    """XSTACK: is this stacked part pair a decoupling cap under the part it serves (owner 2026-10-05)?
    lst: the pair's stacked pad pairs (.., F pad, B pad)"""
    p0, q0 = lst[0][6], lst[0][7]
    recs = (p0["fp"], q0["fp"])
    caps = [r for r in recs if r["ref"][:1] == "C" and r["two_term"]]
    if len(caps) != 1:
        return False
    cap = caps[0]
    ic = recs[1] if cap is recs[0] else recs[0]
    cnets = {x["net"] for x in cap["smd_pads"]}
    inets = {x["net"] for x in ic["pads"]}
    if len(cnets) != 2 or not cnets <= inets or not any(is_rail(B, n) for n in cnets):
        return False                                    # (a) the cap's two nets are a supply / ground pair of the part
    own = [x for x in ic["smd_pads"] if ic["side"] in x["poly"]]
    ep = max(own, key=lambda x: x["area"]) if own else None
    for *_, p, q in lst:                                # (b) the stacked pads face only pads of the decoupled IC
        ip = p if p["fp"] is ic else q                  # (lst holds this cap / IC pair only); the parent (2026-10-05)
        if ip["fp"] is not ic:                          # also demanded own-net / EP / no-net pads - CT owner
            return False                                # 2026-10-17 lifted that: SERVING_DECAP_ANY_IC_PAD
        if not SERVING_DECAP_ANY_IC_PAD and ip["net"] and ip["net"] not in cnets and \
                not (ip is ep and ip["area"] >= EP_MIN_MM2):
            return False
    L = cap["side"]
    for cp in cap["smd_pads"]:                          # (c) each cap pad has a legal via site
        poly = cp["poly"][L]
        near = [B.vias[i] for i in B.v_tree.query(poly.buffer(XSTACK_DECAP_VIA_MM)) if B.vias[i]["net"] == cp["net"]]
        ok = any(not poly.contains(Point(v["pos"])) and poly.distance(v["disc"]) <= XSTACK_DECAP_VIA_MM for v in near)
        ok = ok or any(poly.contains(Point(v["pos"])) and vip_fits(cp, v, L) for v in near)
        if not ok:
            return False
    return True


def joint_arms(B):
    """off-pad / off-via joints -> (net, layer, point, [(track idx, unit dir)])"""
    out = []
    for (net, L, j), arms in B.joint.items():
        if len(arms) < 2:
            continue
        q = arms[0][1]
        if B.on_pad_or_via(net, L, q):
            continue
        seen_far, dirs = set(), []
        for i, q0, far in arms:                  # an exact duplicate arm is qa_copper_landing TRACK-DUP, not an angle
            u = unit(q0, far)
            if u is not None and r3(far) not in seen_far:
                seen_far.add(r3(far))
                dirs.append((i, u))
        if len(dirs) == 1 and len({i for i, _, _ in arms}) >= 2:
            dirs = [(i, unit(q0, far)) for i, q0, far in arms[:2]]     # a segment doubled straight back: a spike
        out.append((net, L, q, dirs))
    return out


def chk_fold_acute(B, fails, info):
    for net, L, q, dirs in joint_arms(B):
        ang = {}
        for x in range(len(dirs)):
            for y in range(x + 1, len(dirs)):
                if dirs[x][0] != dirs[y][0]:
                    ang[(x, y)] = angle(dirs[x][1], dirs[y][1])
        if not ang:
            continue
        trunk = {k for xy, a in ang.items() if a >= 180 - TEE_STRAIGHT_DEG for k in xy} if len(dirs) >= 3 else set()
        worst, pair, kind = 181.0, None, None
        for (x, y), a in ang.items():
            lim = ACUTE_T_DEG if (x in trunk) != (y in trunk) else ACUTE_DEG
            if a < lim - ANGLE_TOL_DEG and (pair is None or a < worst):
                worst, pair, kind = a, (dirs[x][0], dirs[y][0]), "acute T-joint" if lim == ACUTE_T_DEG else "acute joint"
        mn = min(ang.values())
        if len(dirs) == 2 and mn < FOLD_DEG - ANGLE_TOL_DEG:
            i, k = dirs[0][0], dirs[1][0]
            fails["TRACK-FOLD"].append({"net": net, "layer": B.lname(L), "at": r3(q), "angle": round(mn, 1),
                                        "what": "spike / hairpin: the track folds back on itself",
                                        "uuids": [B.tracks[i]["obj"].m_Uuid.AsString(),
                                                  B.tracks[k]["obj"].m_Uuid.AsString()]})
        elif pair is not None:
            fails["ACUTE"].append({"net": net, "layer": B.lname(L), "at": r3(q), "angle": round(worst, 1),
                                   "ends": len(dirs), "what": kind,
                                   "uuids": [B.tracks[i]["obj"].m_Uuid.AsString() for i in pair]})
    # T-joints: a track end on another same-net track's body, away from its ends and off pad / via
    for t in B.tracks:
        if t["len"] < 1e-4:
            continue
        for q, far in ((t["a"], t["mid"] or t["e"]), (t["e"], t["mid"] or t["a"])):
            pt = Point(q)
            for o in B.neighbours(t):
                if o["arc"] or o["len"] < 1e-4 or o["line"].distance(pt) > o["w"] / 2 + 1e-6:
                    continue
                if B.J(t["layer"], q) in (B.J(o["layer"], o["a"]), B.J(o["layer"], o["e"])):
                    continue
                u, d = unit(q, far), unit(o["a"], o["e"])
                if u is None or d is None:
                    continue
                sp = (q[0] - o["a"][0]) * d[0] + (q[1] - o["a"][1]) * d[1]
                if not o["w"] / 2 < sp < o["len"] - o["w"] / 2:
                    continue                      # not on the body (an end region / a micro-segment: joint rules)
                if B.on_pad_or_via(t["net"], t["layer"], q):
                    continue
                a = angle(u, d)
                a = min(a, 180 - a)
                if COLLINEAR_DEG < a < ACUTE_T_DEG - ANGLE_TOL_DEG:     # collinear on a body: TRACK-FOLD overlap
                    fails["ACUTE"].append({"net": t["net"], "layer": B.lname(t["layer"]), "at": r3(q),
                                           "angle": round(a, 1), "what": "acute T-joint",
                                           "uuids": [t["obj"].m_Uuid.AsString(), o["obj"].m_Uuid.AsString()]})
    # partial collinear overlaps of same-net segments
    seen = set()
    for t in B.tracks:
        if t["arc"] or t["len"] < 1e-4:
            continue
        ut = unit(t["a"], t["e"])
        for o in B.neighbours(t):
            if o["arc"] or o["len"] < 1e-4 or (o["i"], t["i"]) in seen:
                continue
            seen.add((t["i"], o["i"]))
            uo = unit(o["a"], o["e"])
            a = angle(ut, uo)
            sh, lg = (t, o) if t["len"] <= o["len"] else (o, t)
            ul = unit(lg["a"], lg["e"])
            lat = max(abs((q[0] - lg["a"][0]) * -ul[1] + (q[1] - lg["a"][1]) * ul[0]) for q in (sh["a"], sh["e"]))
            a = min(a, 180 - a)
            if a > FOLD_DEG or (a > COLLINEAR_DEG and lat > min(t["w"], o["w"]) / 4):
                continue                          # neither parallel nor a short piece lying along the other
            if lat > min(t["w"], o["w"]) / 2:
                continue
            # lateral offset small: overlap along the axis
            s = sorted(((o["a"][0] - t["a"][0]) * ut[0] + (o["a"][1] - t["a"][1]) * ut[1],
                        (o["e"][0] - t["a"][0]) * ut[0] + (o["e"][1] - t["a"][1]) * ut[1]))
            off = max(abs((o["a"][0] - t["a"][0]) * -ut[1] + (o["a"][1] - t["a"][1]) * ut[0]),
                      abs((o["e"][0] - t["a"][0]) * -ut[1] + (o["e"][1] - t["a"][1]) * ut[0]))
            if off > (t["w"] + o["w"]) / 2:
                continue
            ov = min(t["len"], s[1]) - max(0.0, s[0])
            if ov <= OVERLAP_MIN_MM:
                continue
            if o["cu"].buffer(1e-4).contains(t["cu"]) or t["cu"].buffer(1e-4).contains(o["cu"]):
                continue                                   # full containment: qa_copper_landing TRACK-DUP
            fails["TRACK-FOLD"].append({"net": t["net"], "layer": B.lname(t["layer"]), "at": r3(t["a"]),
                                        "overlap_mm": round(ov, 3), "what": "partially overlapping collinear segments",
                                        "uuids": [t["obj"].m_Uuid.AsString(), o["obj"].m_Uuid.AsString()]})


def thread_regions(B):
    """[(footprint, layer, region polygon, nets of its pads, what)]: the pad hull minus the pads"""
    out = []
    for rec in B.fps.values():
        L = rec["side"]
        if not (rec["mid2t"] or rec["fine"]):
            continue
        ps = [p for p in rec["smd_pads"] if L in p["poly"]]
        if len(ps) < 2:
            continue
        u = unary_union([p["poly"][L] for p in ps])
        reg = u.convex_hull.difference(u)
        if reg.area > 1e-3:
            out.append((rec, L, reg, {p["net"] for p in rec["pads"]},
                        "between the terminals" if rec["mid2t"] else "inside the fine-pitch pad hull"))
    return out


def chk_thread(B, fails, info):
    hits = {}
    for rec, L, reg, nets, what in thread_regions(B):
        preg = prep(reg)
        for i in B.t_tree.query(reg):
            t = B.tracks[i]
            if t["layer"] != L or t["net"] in nets or not preg.intersects(t["line"]):
                continue
            ln = t["line"].intersection(reg).length
            if ln > THREAD_MIN_MM:
                key = ("track", rec["ref"], t["net"], B.lname(L))
                if key not in hits or hits[key]["len_mm"] < ln:
                    c = t["line"].intersection(reg)
                    c = c.interpolate(0.5, normalized=True) if hasattr(c, "interpolate") else c.representative_point()
                    hits[key] = {"part": rec["ref"], "fp": rec["fpid"], "net": t["net"], "layer": B.lname(L),
                                 "len_mm": round(ln, 3), "at": r3((c.x, c.y)), "what": "track " + what,
                                 "uuids": [t["obj"].m_Uuid.AsString()]}
        for i in B.v_tree.query(reg):
            v = B.vias[i]
            if v["net"] in nets or not preg.contains(Point(v["pos"])):
                continue
            hits[("via", rec["ref"], v["net"], v["pos"])] = {"part": rec["ref"], "fp": rec["fpid"], "net": v["net"],
                                                              "at": v["pos"], "what": "via " + what,
                                                              "uuids": [v["obj"].m_Uuid.AsString()]}
    fails["THREAD"].extend(hits.values())


def power_pads(B):
    """[(pad, role)] candidate power pads (POWER-PAD-CONN)"""
    out = []
    budget = cb.BUDGET[B.kind]
    for rec in B.fps.values():
        pre = rec["ref"][:1]
        own = [p for p in rec["smd_pads"] if rec["side"] in p["poly"]]
        if pre == "U" and own:
            big = max(own, key=lambda p: p["area"])      # on the part's own side (a footprint's B.Cu EP copy is not it)
            if big["area"] >= EP_MIN_MM2 and big["net"]:
                out.append((big, "exposed pad"))
            continue
        role = None
        if pre == "C" and (farads(rec["value"]) or 0) >= POWER_CAP_MIN_F:
            role = "bulk cap"
        elif pre == "L":
            role = "inductor"
        elif pre == "D" and not (POWER_PAD_SKIP_LED and "LED" in rec["fpid"].upper()):
            role = "rail diode"
        if role:
            out += [(p, role) for p in rec["smd_pads"] if p["net"] in budget]
    return [(p, r) for p, r in out if p["net"] not in B.force]


def zone_connection(B, p, L):
    """the connection KiCad's filler applies to pad p in its own net's zone on L: pad override, else footprint
    override, else the zone's pad connection (an SMD pad in a THT_THERMAL zone connects FULL)"""
    for c in (p["obj"].GetLocalZoneConnection(), p["fp"]["obj"].GetLocalZoneConnection()):
        if c != pcbnew.ZONE_CONNECTION_INHERITED:
            return c
    zs = [z for z in B.zones.get(p["net"], ()) if z.IsOnLayer(L)]
    c = zs[0].GetPadConnection() if zs else pcbnew.ZONE_CONNECTION_NONE
    return pcbnew.ZONE_CONNECTION_FULL if c == pcbnew.ZONE_CONNECTION_THT_THERMAL and p["smd"] else c


def spoke_width(B, p, L):
    """thermal spoke width (mm) the filler uses for pad p on L: pad override, else its own-net zone's"""
    try:
        o = p["obj"].GetLocalThermalSpokeWidthOverride()
        if o:
            return mm(o)
    except Exception:
        pass
    zs = [z for z in B.zones.get(p["net"], ()) if z.IsOnLayer(L)]
    return mm(zs[0].GetThermalReliefSpokeWidth()) if zs else None


def pad_connection(B, p, L):
    """(solid?, cover fraction, spoke width mm, landing track width mm) of a pad to its own net's fill on layer L, or
    None when the pad is not on L / the net has no fill there. Solid = the fill reaches the pad and either the zone
    connects it FULL (zone_connection) or the fill covers >= SOLID_COVER of it (KiCad draws spokes from the pad
    centre, so a thermal pad is partly covered by its own spokes, never 90 %)."""
    if L not in p["poly"]:
        return None
    g, pg = B.fill(p["net"], L)
    poly = p["poly"][L]
    if g.is_empty:
        return None
    cover = poly.intersection(g).area / poly.area if poly.area else 0.0
    d0, d1 = SPOKE_RING
    ring = poly.buffer(d1).difference(poly.buffer(d0))
    cut = ring.intersection(g)
    spoke = cut.area / (d1 - d0)              # crossing width (an oblique spoke reads wider than it is) ...
    pieces = [x for x in getattr(cut, "geoms", [cut]) if x.area > 1e-5]
    w = spoke_width(B, p, L)
    if w:                                     # ... so never credit more than n_spokes x the spoke width
        spoke = min(spoke, len(pieces) * w)
    trk = sum(B.tracks[i]["w"] for i in B.t_tree.query(poly) if B.tracks[i]["net"] == p["net"]
              and B.tracks[i]["layer"] == L and B.tracks[i]["cu"].intersects(poly))
    solid = cover >= SOLID_COVER or (spoke > 1e-3 and zone_connection(B, p, L) == pcbnew.ZONE_CONNECTION_FULL)
    return solid, cover, spoke, trk


def chk_power_pad(B, fails, info):
    solid = 0
    for p, role in power_pads(B):
        L = p["fp"]["side"] if p["fp"]["side"] in p["poly"] else next(iter(p["poly"]))
        con = pad_connection(B, p, L)
        if con is None:
            continue
        is_solid, cover, spoke, trk = con
        if is_solid:
            solid += 1
            continue
        if spoke < 1e-3:
            continue                                   # not connected to the pour at all: a track-fed pad
        rec = {"pad": B.pad_ref(p), "role": role, "net": p["net"], "layer": B.lname(L), "at": p["pos"],
               "cover": round(cover, 2), "spokes_mm": round(spoke, 3), "tracks_mm": round(trk, 3)}
        if role == "exposed pad":
            fails["POWER-PAD-CONN"].append({**rec, "what": "exposed pad on thermal relief: it is the heat path, "
                                                           "connect it solid"})
            continue
        req = max(cb.required_width(B.kind, p["net"], True, None),
                  POWER_PAD_LAND_FRAC * min(p["w"], p["h"]))
        if spoke + trk < req - 1e-3:
            fails["POWER-PAD-CONN"].append({**rec, "required_mm": round(req, 3),
                                            "what": "thermal-relief connection narrower than max(IPC-2152 width of "
                                                    "the net's budget, the pad's narrow side)"})
    info["power_pads_solid"] = solid


def chk_via_current(B, fails, info):
    budget = cb.BUDGET[B.kind]
    st = cb.STACKUP[B.kind]
    vs = [v for v in B.vias if v["net"] in budget and v["net"] not in B.force]
    uf = QL.UF()
    for v in vs:
        uf.find(v["i"])
        for k in B.v_tree.query(Point(v["pos"]).buffer(VIA_SITE_MM)):
            o = B.vias[k]
            if o["net"] == v["net"] and math.dist(o["pos"], v["pos"]) <= VIA_SITE_MM:
                uf.union(v["i"], k)
    sites = defaultdict(list)
    for v in vs:
        sites[uf.find(v["i"])].append(v)
    n_sites = 0
    planes = plane_layers(B)
    for site in sites.values():
        net = site[0]["net"]
        load, fault, _ = cb.budget(B.kind, net)
        if net in planes:
            sl, sf = served_current(B, site, planes[net])
            load, fault = min(load, sl), (min(fault, sf) if fault else None)
        caps = {}                                   # layer -> (load amps, fault amps) the copper there can carry
        for L in set(x for v in site for x in v["layers"]):
            cu = st["outer_um" if L in B.outer else "inner_um"]
            unlimited = False
            tids = set()
            for v in site:
                if L not in v["layers"]:
                    continue
                if B.fill(net, L)[1].intersects(v["disc"]):
                    unlimited = True
                if any(p["net"] == net and p["poly"][L].intersects(v["disc"]) for p in B.pads_near(L, v["disc"])):
                    unlimited = True
                tids |= {i for i in B.t_tree.query(v["disc"]) if B.tracks[i]["net"] == net
                         and B.tracks[i]["layer"] == L and B.tracks[i]["cu"].intersects(v["disc"])}
            if unlimited:
                caps[L] = (math.inf, math.inf)
            elif tids:
                caps[L] = (sum(track_amps(B.tracks[i]["w"], cu, cb.DT_LOAD_K) for i in tids),
                           sum(track_amps(B.tracks[i]["w"], cu, cb.DT_FAULT_K) for i in tids))
        if len(caps) < 2:
            continue
        n_sites += 1

        def through(k):
            c = sorted(x[k] for x in caps.values())
            return c[-2] if math.isinf(c[-1]) and math.isinf(c[-2]) else sum(c) - c[-1]
        need = []
        for k, (amps, dt) in enumerate(((load, cb.DT_LOAD_K), (fault, cb.DT_FAULT_K))):
            if not amps:
                continue
            i_site = min(amps, through(k))
            i_via = min(via_amps(v["drill"], dt) for v in site)
            n = math.ceil(i_site / i_via - 1e-9) if i_site > 0 else 0
            if n > len(site):
                need.append({"case": "load" if k == 0 else "fault", "amps": round(i_site, 3),
                             "via_amps": round(i_via, 3), "need": n})
        if need:
            v = site[0]
            fails["VIA-CURRENT"].append({"net": net, "at": v["pos"], "vias": len(site), "drill": v["drill"],
                                         "need": max(x["need"] for x in need), "cases": need,
                                         "uuids": [x["obj"].m_Uuid.AsString() for x in site]})
    info["via_current_sites"] = n_sites
    info["via_current_plane_nets"] = sorted(n for n in planes if n in budget)
    info["via_amps_0.3_drill_10K"] = round(via_amps(0.3, cb.DT_LOAD_K), 3)


def is_decap_fanout(p):
    rec = p["fp"]
    f = farads(rec["value"]) if rec["ref"][:1] == "C" and rec["two_term"] else None
    return f is not None and f <= DECAP_FANOUT_MAX_F


def part_supply(B, p):
    """(load, fault) A of the part behind pad p: the largest current_budget value among the other nets of its
    footprint (a part with no budgeted other net: current_budget.SIGNAL_A). A decoupling capacitor (two-terminal C up to
    DECAP_FANOUT_MAX_F) passes no DC load current, only its charge current: DECAP_FANOUT_A, never its rail's trunk budget
    (review-M4 m3: single decap fan-out GND vias were held to the +3V3 / +5V trunk budget). A part with its own
    current_budget.part_return() entry on that net (D-LAYOUT-GATES #7: U10 / U6 GND) is charged exactly that."""
    own = cb.part_return(B.kind, p["net"], p["ref"])
    if own is not None:                            # D-LAYOUT-GATES #7: the part's own return current (U10 / U6 GND)
        return own
    if is_decap_fanout(p):
        return DECAP_FANOUT_A, DECAP_FANOUT_A
    ld, fl = cb.SIGNAL_A, cb.SIGNAL_A
    for q in p["fp"]["pads"]:
        if q["net"] and q["net"] != p["net"]:
            a, f, _ = cb.budget(B.kind, q["net"])
            ld, fl = max(ld, a), max(fl, f if f else a)
    return ld, fl


def served_current(B, site, plane_ls):
    """(load, fault) A a plane-net via site serves: pads reached by its local copper (VIA-CURRENT)"""
    net = site[0]["net"]
    ids = {v["i"] for v in site}
    pads, todo, seen = {}, [], set()
    share = []                                     # (island pads, fraction of the island's plane vias in this site)
    for v in site:
        for L in v["layers"]:
            if L in plane_ls:
                continue
            for p in B.pads_near(L, v["disc"]):
                if p["net"] == net and p["poly"][L].intersects(v["disc"]):
                    pads[p["i"]] = p
            todo += [i for i in B.t_tree.query(v["disc"]) if B.tracks[i]["net"] == net
                     and B.tracks[i]["layer"] == L and B.tracks[i]["cu"].intersects(v["disc"])]
            g = B.fill(net, L)[0]
            for isl in getattr(g, "geoms", [g]):
                if isl.is_empty or not isl.intersects(v["disc"]) or (L, isl.wkb) in seen:
                    continue
                seen.add((L, isl.wkb))
                pi = prep(isl)
                ip = [p for p in B.pads_near(L, isl) if p["net"] == net and pi.intersects(p["poly"][L])]
                pv = [x for x in B.vias if x["net"] == net and L in x["layers"] and pi.intersects(x["disc"])
                      and any(PL in x["layers"] and B.fill(net, PL)[1].intersects(x["disc"]) for PL in plane_ls)]
                share.append((ip, sum(1 for x in pv if x["i"] in ids) / max(1, len(pv))))
    done = set()
    while todo:
        i = todo.pop()
        if i in done:
            continue
        done.add(i)
        t = B.tracks[i]
        L = t["layer"]
        for p in B.pads_near(L, t["cu"]):
            if p["net"] == net and p["poly"][L].intersects(t["cu"]):
                pads[p["i"]] = p
        if any(B.vias[k]["net"] == net and B.vias[k]["i"] not in ids and B.vias[k]["disc"].intersects(t["cu"])
               for k in B.v_tree.query(t["cu"])):
            continue                               # another via of the net: the current beyond it has its own path
        todo += [o["i"] for o in B.neighbours(t) if o["i"] not in done and o["cu"].intersects(t["cu"])]
    ld = sum(part_supply(B, p)[0] for p in pads.values())
    fl = sum(part_supply(B, p)[1] for p in pads.values())
    if len(site) == 1 and pads and all(is_decap_fanout(p) for p in pads.values()):
        return ld, fl                              # a decap's own fan-out via: its stub serves the cap, not the pour
    for ip, frac in share:
        ld += frac * sum(part_supply(B, p)[0] for p in ip if p["i"] not in pads)
        fl += frac * sum(part_supply(B, p)[1] for p in ip if p["i"] not in pads)
    return ld, fl


def chk_neck_smallpad(B, fails, info):
    for rec in B.fps.values():
        if not rec["small2t"]:
            continue
        for p in rec["smd_pads"]:
            for L, poly in p["poly"].items():
                for i in B.t_tree.query(poly):
                    t = B.tracks[i]
                    if t["net"] != p["net"] or t["layer"] != L or not t["cu"].intersects(poly) or t["len"] < 1e-4:
                        continue
                    u = unit(t["a"], t["e"])
                    n = (-u[1], u[0])
                    xs = [x * n[0] + y * n[1] for x, y in poly.exterior.coords]
                    across = max(xs) - min(xs)
                    if t["w"] > across + NECK_TOL_MM:
                        fails["NECK-SMALLPAD"].append({"net": t["net"], "pad": B.pad_ref(p), "layer": B.lname(L),
                                                       "at": p["pos"], "width": t["w"], "pad_across": round(across, 3),
                                                       "uuids": [t["obj"].m_Uuid.AsString()]})
                        break


# ---------------------------------------------------------------------------------------------- set 2
def plane_layers(B):
    """net -> [inner layers holding a fill of that net] (its planes)"""
    if getattr(B, "_planes", None) is not None:
        return B._planes
    out = B._planes = defaultdict(list)
    for net, zs in B.zones.items():
        for name, L in B.layers.items():
            if L in B.outer:
                continue
            if any(z.IsOnLayer(L) for z in zs) and not B.fill(net, L)[0].is_empty:
                out[net].append(L)
    return out


def chk_pour_stitch(B, fails, info):
    planes = plane_layers(B)
    pth = [p for p in B.pads if p["pth"]]
    n_frag = 0
    for net, pls in planes.items():
        if net in B.force:
            continue
        for L in B.outer:
            g = B.fill(net, L)[0]
            for frag in getattr(g, "geoms", [g]):
                if frag.is_empty or frag.area <= STITCH_MIN_MM2:
                    continue
                n_frag += 1
                pf = prep(frag)
                links = []
                for i in B.v_tree.query(frag):
                    v = B.vias[i]
                    if v["net"] == net and L in v["layers"] and pf.intersects(v["disc"]) and \
                            any(PL in v["layers"] and B.fill(net, PL)[1].intersects(v["disc"]) for PL in pls):
                        links.append(v["pos"])
                links += [p["pos"] for p in pth if p["net"] == net and pf.intersects(Point(p["pos"]))]
                need = max(STITCH_MIN_VIAS, math.ceil(frag.area / STITCH_MM2_PER_VIA))
                far = frag.difference(unary_union([Point(q).buffer(STITCH_REACH_MM, 16) for q in links])) \
                    if links else frag
                plane = unary_union([B.fill(net, PL)[0] for PL in pls])
                backed = (not plane.is_empty) and frag.intersection(plane).area >= STITCH_BACKED_FRAC * frag.area
                if backed:                                   # D-LAYOUT-GATES #9c
                    need = max(STITCH_MIN_VIAS, math.ceil(frag.area / STITCH_MM2_PER_VIA_BACKED))
                    if frag.area <= STITCH_SMALL_MM2 and any(p["net"] == net and L in p["poly"] and
                                                             pf.intersects(p["poly"][L]) for p in B.pads):
                        need = 1
                    far = far.difference(plane)
                    info.setdefault("stitch_backed", []).append(r3(frag.representative_point().coords[0]))
                far_a = far.area
                if len(links) < need or far_a > STITCH_REACH_TOL_MM2:
                    c = far.representative_point() if far_a > STITCH_REACH_TOL_MM2 else frag.representative_point()
                    fails["POUR-STITCH"].append({"net": net, "layer": B.lname(L), "area_mm2": round(frag.area, 1),
                                                 "vias": len(links), "need": need,
                                                 "beyond_reach_mm2": round(far_a, 2), "at": r3((c.x, c.y))})
    info["stitch_fragments"] = n_frag


class NetGraph:
    """same-net copper path graph: track joints, pads (centres), vias; own-net fill islands join what they touch
    (straight-line hop between the two items, a lower bound on the path through the pour)"""

    def __init__(self, B, net):
        self.B, self.net = B, net
        self.G = defaultdict(list)
        ts = [t for t in B.tracks if t["net"] == net]
        for t in ts:
            a, e = ("j", t["layer"], B.J(t["layer"], t["a"])), ("j", t["layer"], B.J(t["layer"], t["e"]))
            self.link(a, e, t["len"])
        self.items = []
        for p in B.pads:
            if p["net"] == net:
                self.items.append((("p", p["i"]), p["pos"], p["poly"], None))
        for v in B.vias:
            if v["net"] == net:
                self.items.append((("v", v["i"]), v["pos"], {L: v["disc"] for L in v["layers"]}, None))
        for node, q, polys, _ in self.items:
            for L, g in polys.items():
                for i in B.t_tree.query(g):
                    t = B.tracks[i]
                    if t["net"] != net or t["layer"] != L:
                        continue
                    for e in (t["a"], t["e"]):
                        if g.distance(Point(e)) <= t["w"] / 2:
                            self.link(node, ("j", L, B.J(L, e)), math.dist(q, e))
        # via-in-pad (owner 2026-10-05: filled + capped vias, VIP allowed wholly inside an own-net pad): a via whose
        # disc overlaps a same-net pad on a shared layer is joined to that pad (centre-to-centre), track or no track
        pads_ = [it for it in self.items if it[0][0] == "p"]
        for vnode, vq, vpolys, _ in [it for it in self.items if it[0][0] == "v"]:
            for pnode, pq, ppolys, _ in pads_:
                if math.dist(vq, pq) > 5.0:
                    continue
                if any(L in ppolys and ppolys[L].intersects(g) for L, g in vpolys.items()):
                    self.link(vnode, pnode, math.dist(vq, pq))
        if net in B.pour or plane_layers(B).get(net):
            for L in B.layers.values():
                g = B.fill(net, L)[0]
                if g.is_empty:
                    continue
                isl = list(getattr(g, "geoms", [g]))
                tree = STRtree(isl)
                members = defaultdict(list)
                for node, q, polys, _ in self.items:
                    if L in polys:
                        for k in tree.query(polys[L]):
                            if isl[k].intersects(polys[L]):
                                members[k].append((node, q))
                for lst in members.values():
                    for x in range(len(lst)):
                        for y in range(x + 1, len(lst)):
                            self.link(lst[x][0], lst[y][0], math.dist(lst[x][1], lst[y][1]))

    def link(self, a, b, d):
        self.G[a].append((b, d))
        self.G[b].append((a, d))

    def dist(self, src, dsts, cap=math.inf):
        import heapq
        D, h, n = {src: 0.0}, [(0.0, 0, src)], 0
        while h:
            d, _, u = heapq.heappop(h)
            if u in dsts:
                return d, u
            if d > D.get(u, math.inf) or d > cap:
                continue
            for x, l in self.G[u]:
                nd = d + l
                if nd < D.get(x, math.inf):
                    D[x] = nd
                    n += 1
                    heapq.heappush(h, (nd, n, x))
        return math.inf, None


# CT supply-like nets besides "+..." rails: W5500 1V2O / TOCAP, ESP32 VDD_SPI, the PoE input VPP, the TPS23751
# VC / VB bias rails, USB VBUS, the buck input and the six switched fan-port rails (header bypass caps)
SUPPLY_RE = re.compile(r"VINT|REF|VCAP|TOCAP|1V2|VISO|VDD|VCC|KEEP|^VBUS\w*$|^ETH_1V2$")   # SBC-1 supply-like nets


def chk_decap_loop(B, fails, info):
    loads = defaultdict(set)
    for p in B.pads:
        r = p["ref"]
        if r[:1] in ("U", "J", "L") or (r.startswith("D") and "LED" in p["fp"]["fpid"].upper()):
            loads[p["net"]].add(p["i"])
    graphs = {}
    n = 0
    for rec in B.fps.values():
        if rec["ref"][:1] != "C" or not rec["two_term"]:
            continue
        ps = rec["smd_pads"]
        nets = [p["net"] for p in ps]
        sup = [p for p in ps if p["net"] and not GROUND_RE.match(p["net"])
               and (p["net"].startswith("+") or SUPPLY_RE.search(p["net"]))]
        gnd = [p for p in ps if GROUND_RE.match(p["net"] or "")]
        if len(sup) != 1 or len(gnd) != 1 or not loads.get(sup[0]["net"]):
            continue
        n += 1
        s, g = sup[0], gnd[0]
        L = rec["side"]
        poly = g["poly"][L]
        dv = min([poly.distance(B.vias[i]["disc"]) for i in B.v_tree.query(poly.buffer(DECAP_GND_VIA_MM + 0.5))
                  if B.vias[i]["net"] == g["net"]] or [math.inf])
        con = pad_connection(B, g, L)
        solid = bool(con and con[0])
        if dv > DECAP_GND_VIA_MM and not solid:
            fails["DECAP-LOOP"].append({"part": rec["ref"], "value": rec["value"], "pad": B.pad_ref(g),
                                        "net": g["net"], "at": g["pos"],
                                        "gnd_via_mm": None if math.isinf(dv) else round(dv, 2),
                                        "what": f"no ground via within {DECAP_GND_VIA_MM} mm and no solid pour"})
        f = farads(rec["value"])
        if f is not None and f <= DECAP_HF_MAX_F * 1.01:
            net = s["net"]
            if net not in graphs:
                graphs[net] = NetGraph(B, net)
            G = graphs[net]
            d, hit = G.dist(("p", s["i"]), {("p", i) for i in loads[net] if B.pads[i]["ref"] != rec["ref"]},
                            cap=DECAP_PATH_MM * 4)
            if d > DECAP_PATH_MM and rec["ref"] in DECAP_PATH_EXEMPT.get(B.kind, {}):
                info.setdefault("decap_path_exempt", []).append([rec["ref"], None if math.isinf(d) else round(d, 2)])
            elif d > DECAP_PATH_MM:
                fails["DECAP-LOOP"].append({"part": rec["ref"], "value": rec["value"], "pad": B.pad_ref(s),
                                            "net": net, "at": s["pos"],
                                            "path_mm": None if math.isinf(d) else round(d, 2),
                                            "what": f"supply copper path to the nearest load pin > {DECAP_PATH_MM} mm"})
    info["decaps"] = n


def led_only_net(B, net, rec):
    """SERIES-TERM scope (CT): the net joins this resistor to LED pads only (an LED current limiter)"""
    others = [q for q in B.pads if q["net"] == net and q["fp"] is not rec]
    return bool(others) and all(q["ref"][:1] == "D" and "LED" in q["fp"]["fpid"].upper() for q in others)


def chk_series_term(B, fails, info):
    ic_pads = defaultdict(list)
    for q in B.pads:
        if q["ref"][:1] == "U" and q["net"]:
            ic_pads[q["net"]].append(q)
    n = 0
    for rec in B.fps.values():
        if rec["ref"][:1] != "R" or not rec["two_term"]:
            continue
        r = ohms(rec["value"])
        if r is None or not 0 < r <= SERIES_MAX_OHM:
            continue
        ps = rec["smd_pads"]
        if any(not p["net"] or GROUND_RE.match(p["net"]) or p["net"].startswith(("+", "-")) or p["net"] in B.pour
               for p in ps):
            continue
        driven = [(p, ic_pads[p["net"]]) for p in ps if ic_pads.get(p["net"])]
        if not driven:
            continue
        if SERIES_TERM_SKIP_LED and any(led_only_net(B, p["net"], rec) for p in ps):
            info.setdefault("series_led_limiters", []).append(rec["ref"])
            continue
        if rec["ref"] in SERIES_TERM_EXEMPT.get(B.kind, {}):
            info.setdefault("series_exempt", []).append(rec["ref"])
            continue
        n += 1
        best = math.inf
        for p, drv in driven:
            d, hit = NetGraph(B, p["net"]).dist(("p", p["i"]), {("p", q["i"]) for q in drv}, cap=SERIES_PATH_MM * 20)
            best = min(best, d)
        if best > SERIES_PATH_MM:
            p = driven[0][0]
            q = min((q for _, drv in driven for q in drv), key=lambda q: math.dist(q["pos"], p["pos"]))
            fails["SERIES-TERM"].append({"part": rec["ref"], "value": rec["value"], "nets": [x["net"] for x in ps],
                                         "driver": B.pad_ref(q) if len(driven) == 1 else None,
                                         "nearest_ic_pin": B.pad_ref(q), "at": P(rec["obj"].GetPosition()),
                                         "path_mm": None if math.isinf(best) else round(best, 2),
                                         "straight_mm": round(math.dist(q["pos"], p["pos"]), 2),
                                         "what": "series resistor away from its driver" if len(driven) == 1 else
                                                 "series resistor mid-line (not at either IC end)"})
    info["series_terms"] = n


def chk_xtal(B, fails, info):
    for rec in B.fps.values():
        if rec["ref"][:1] not in ("X", "Y"):
            continue
        osc = "Oscillator" in rec["fpid"]
        nets = {p["net"] for p in rec["pads"] if p["net"]}
        clk = sorted(n for n in nets if not GROUND_RE.match(n) and not n.startswith("+"))
        ex = XTAL_LEN_EXEMPT.get(B.kind, {}).get(rec["ref"])
        exs = {e["net"]: e for e in ([ex] if isinstance(ex, dict) else (ex or []))}
        for net in clk:
            ln = sum(t["len"] for t in B.tracks if t["net"] == net)
            lim = XTAL_OSC_LEN_MM if osc else XTAL_LEN_MM
            ex = exs.get(net)
            if ex:
                lim = ex["max_mm"]
                info.setdefault("xtal_len_exempt", []).append({"part": rec["ref"], "net": net, "len_mm": round(ln, 2),
                                                               "limit": lim, "reason": ex["reason"]})
            nv = sum(1 for v in B.vias if v["net"] == net)
            if ln > lim or nv:
                fails["XTAL"].append({"part": rec["ref"], "net": net, "len_mm": round(ln, 2), "limit": lim,
                                      "vias": nv, "at": P(rec["obj"].GetPosition()),
                                      "what": "clock net too long / through vias"})
        fp = rec["obj"]
        cy = unary_union([to_shapely(fp.GetCourtyard(L)) for L in (pcbnew.F_CrtYd, pcbnew.B_CrtYd)])
        if cy.is_empty:
            continue
        keep = cy.buffer(XTAL_KEEPOUT_MM)
        foreign = defaultdict(set)
        for i in B.t_tree.query(keep):
            t = B.tracks[i]
            if t["net"] not in nets and keep.intersects(t["cu"]):
                foreign[t["net"]].add(B.lname(t["layer"]))
        for i in B.v_tree.query(keep):
            v = B.vias[i]
            if v["net"] not in nets and keep.intersects(v["disc"]):
                foreign[v["net"]].add("via")
        if foreign:
            fails["XTAL"].append({"part": rec["ref"], "at": P(fp.GetPosition()),
                                  "foreign": {k: sorted(v) for k, v in sorted(foreign.items())},
                                  "what": f"foreign copper inside the courtyard + {XTAL_KEEPOUT_MM} mm"})


def ref_fill(B, L):
    """ground fill on the reference layer(s) of signal layer L, and every other net's fill there"""
    refs = REF_LAYERS[B.kind].get(B.lname(L), [])
    gnd, other = [], []
    for name in refs:
        RL = B.layers[name]
        for net in B.zones:
            g = B.fill(net, RL)[0]
            if g.is_empty:
                continue
            (gnd if GROUND_RE.match(net) else other).append(g)
    return unary_union(gnd) if gnd else Polygon(), unary_union(other) if other else Polygon()


def power_ref_fill(B, L):
    """fill of the designated power reference pours (REF_POWER_PLANES) on the reference layer(s) of signal layer L"""
    out = []
    for name in REF_LAYERS[B.kind].get(B.lname(L), []):
        for net in REF_POWER_PLANES.get(B.kind, {}).get(name, []):
            g = B.fill(net, B.layers[name])[0]
            if not g.is_empty:
                out.append(g)
    return unary_union(out) if out else Polygon()


def diff_pinfield(B, P_, N_):
    """union of the pin fields of the DIFF_SKEW_PINFIELD parts that hold pads of BOTH legs: the convex hull of those
    pads and of the part's other net pads within DIFF_PINFIELD_NEIGHBOUR_MM (centre distance) of them (all layers),
    grown by DIFF_BREAKOUT_MM"""
    zones = []
    for ref in DIFF_SKEW_PINFIELD.get(B.kind, {}):
        own = [p for p in P_["pads"] + N_["pads"] if p["ref"] == ref]
        if not any(p["ref"] == ref for p in P_["pads"]) or not any(p["ref"] == ref for p in N_["pads"]):
            continue
        field = own + [q for q in B.pads if q["ref"] == ref and q["net"] and all(q is not p for p in own)
                       and any(math.dist(q["pos"], p["pos"]) <= DIFF_PINFIELD_NEIGHBOUR_MM for p in own)]
        zones.append(unary_union([g for q in field for g in q["poly"].values()]).convex_hull.buffer(DIFF_BREAKOUT_MM))
    return unary_union(zones) if zones else Polygon()


def chk_diffpair(B, fails, info):
    for pn, nn, gap0 in DIFF_PAIRS[B.kind]:
        legs = {}
        for net in (pn, nn):
            ts = [t for t in B.tracks if t["net"] == net]
            if not ts:
                break
            vs = [v for v in B.vias if v["net"] == net]
            legs[net] = {"tracks": ts, "len": sum(t["len"] for t in ts), "vias": len(vs),
                         "layers": sorted({B.lname(t["layer"]) for t in ts}),
                         "pads": [p for p in B.pads if p["net"] == net]}
        if len(legs) < 2:
            continue
        P_, N_ = legs[pn], legs[nn]
        probs = []
        if P_["layers"] != N_["layers"]:
            probs.append(f"layers {P_['layers']} vs {N_['layers']}")
        if P_["vias"] != N_["vias"]:
            probs.append(f"vias {P_['vias']} vs {N_['vias']}")
        pf = diff_pinfield(B, P_, N_)
        if pf.is_empty:
            skew = abs(P_["len"] - N_["len"])
        else:
            lp = sum(t["line"].difference(pf).length for t in P_["tracks"])
            ln = sum(t["line"].difference(pf).length for t in N_["tracks"])
            info.setdefault("diffpair_pinfield_mm", {})[f"{pn}/{nn}"] = [round(P_["len"] - lp, 3),
                                                                          round(N_["len"] - ln, 3)]
            skew = abs(lp - ln)
        if skew > DIFF_SKEW_MM:
            probs.append(f"skew {skew:.2f} mm" + ("" if pf.is_empty else " (outside the pin fields)"))
        # coupling: P centreline sampled; edge gap to the nearest N copper on the same layer
        pads = unary_union([g.buffer(DIFF_BREAKOUT_MM) for p in P_["pads"] + N_["pads"] for g in p["poly"].values()])
        tot = good = over = 0.0
        refcache = {}
        samples = []
        for t in P_["tracks"]:
            L = t["layer"]
            ncu = [o for o in N_["tracks"] if o["layer"] == L]
            if L not in refcache:
                refcache[L] = ref_fill(B, L)[0]
            seg = t["line"]
            steps = max(1, int(seg.length / 0.1))
            for k in range(steps):
                q = seg.interpolate((k + 0.5) / steps, normalized=True)
                dl = seg.length / steps
                if not refcache[L].is_empty and refcache[L].contains(q):
                    over += dl
                if pads.contains(q):
                    continue
                tot += dl
                if not ncu:
                    continue
                d, w2 = min((o["line"].distance(q), o["w"]) for o in ncu)
                samples.append((d - t["w"] / 2 - w2 / 2, dl))
        nominal = gap0
        if nominal is None and samples:              # no qualified gap: the pair's own length-weighted median
            srt = sorted(samples)
            acc, half = 0.0, sum(x[1] for x in srt) / 2
            for g, dl in srt:
                acc += dl
                if acc >= half:
                    nominal = max(g, 0.05)
                    break
        good = sum(dl for g, dl in samples if nominal is not None and abs(g - nominal) <= DIFF_GAP_TOL * nominal)
        if tot > 0 and good / tot < DIFF_COUPLED_FRAC:
            probs.append(f"coupled {100 * good / tot:.0f} % of {tot:.1f} mm (nominal gap "
                         f"{None if nominal is None else round(nominal, 3)}{'' if gap0 else ', own median'})")
        if P_["len"] > 0 and over / P_["len"] < DIFF_PLANE_FRAC:
            probs.append(f"over solid plane {100 * over / P_['len']:.0f} %")
        for net in (pn, nn):
            for t in legs[net]["tracks"]:
                imp = cb.impedance_width(B.kind, net, t["layer"] in B.outer)
                if imp is not None and (imp[0] is None or abs(t["w"] - imp[0]) > imp[1]):
                    probs.append(f"{net} width {t['w']} on {B.lname(t['layer'])} (qualified {imp[0]})")
                    break
        if probs:
            fails["DIFFPAIR"].append({"pair": [pn, nn], "len_mm": [round(P_["len"], 2), round(N_["len"], 2)],
                                      "problems": probs, "at": P_["tracks"][0]["a"]})


def plane_slot_exempt(B, net, h):
    """is void h a documented PLANE_SLOT_EXEMPT cluster for this crossing net (every listed via present and in it)"""
    for e in PLANE_SLOT_EXEMPT.get(B.kind, []):
        if e["net"] != net:
            continue
        ok = True
        for vn, q in e["vias"]:
            hit = [v for v in B.vias if v["net"] == vn and math.dist(v["pos"], q) <= 0.05]
            if not hit or h.distance(Point(q)) > 1e-3:
                ok = False
                break
        if ok:
            return True
    return False


def chk_plane_slot(B, fails, info):
    try:
        ps = pcbnew.SHAPE_POLY_SET()
        B.b.GetBoardPolygonOutlines(ps, True)
        outline = to_shapely(ps)
    except Exception:
        outline = None
    cache = {}
    agg = {}
    islands = []                                   # (rule-area polygon, nets with a pad inside it)
    for z in B.b.Zones():
        if z.GetIsRuleArea() and z.GetZoneName() in PLANE_SLOT_THERMAL_ISLANDS:
            poly = to_shapely(z.Outline())
            islands.append((poly, {p["net"] for p in B.pads if p["net"] and poly.contains(Point(p["pos"]))}))
    for t in B.tracks:
        if not SI_NET_RE.search(t["net"]) or t["len"] < 1e-3:
            continue
        L = t["layer"]
        if B.lname(L) not in REF_LAYERS[B.kind]:
            continue
        if L not in cache:
            gnd, other = ref_fill(B, L)
            pwr = power_ref_fill(B, L)
            ref = gnd if pwr.is_empty else unary_union([gnd, pwr])
            voids = []
            if outline is not None and not ref.is_empty:
                hole = outline.difference(ref)
                if not pwr.is_empty and not gnd.is_empty:      # the GND | power-pour clearance moat is the reference
                    hole = hole.difference(gnd.buffer(PLANE_MOAT_MM).intersection(pwr.buffer(PLANE_MOAT_MM)))  # change
                for h in getattr(hole, "geoms", [hole]):
                    if h.is_empty or h.area < 1e-3:
                        continue
                    mr = h.minimum_rotated_rectangle
                    xs = list(mr.exterior.coords) if mr.geom_type == "Polygon" else []
                    ext = max(math.dist(xs[0], xs[1]), math.dist(xs[1], xs[2])) if xs else 0.0
                    if ext >= PLANE_SLOT_MM:
                        voids.append(h)
            cache[L] = (voids, other)
        voids, other = cache[L]
        ex = [h for h in voids if plane_slot_exempt(B, t["net"], h)]
        if ex:
            ln = t["line"].intersection(unary_union(ex)).length
            if ln > 0:
                e = info.setdefault("plane_slot_exempt", {})
                k = f'{t["net"]} {B.lname(L)}'
                e[k] = round(e.get(k, 0.0) + ln, 2)
        voids = unary_union([h for h in voids if not any(h is x for x in ex)]) if voids else Polygon()
        seg = t["line"]
        own = [poly for poly, nets in islands if t["net"] in nets]
        if own:
            cut = unary_union(own)
            inside = seg.intersection(cut).length
            if inside > 0:
                e = info.setdefault("plane_slot_thermal_island", {})
                k = f'{t["net"]} {B.lname(L)}'
                e[k] = round(e.get(k, 0.0) + inside, 2)
            seg = seg.difference(cut)
        for g, what in ((other, "over another net's plane region (reference change)"),
                        (voids, f"over a reference-plane void >= {PLANE_SLOT_MM} mm")):
            if g.is_empty:
                continue
            ln = seg.intersection(g).length
            if ln > PLANE_CROSS_MM:
                key = (t["net"], B.lname(L), what)
                a = agg.setdefault(key, {"net": t["net"], "layer": B.lname(L), "what": what, "len_mm": 0.0,
                                         "at": None})
                a["len_mm"] = round(a["len_mm"] + ln, 2)
                if a["at"] is None:
                    c = seg.intersection(g)
                    c = c.interpolate(0.5, normalized=True) if hasattr(c, "interpolate") else c.representative_point()
                    a["at"] = r3((c.x, c.y))
    fails["PLANE-SLOT"].extend(agg.values())


def chk_fiducial(B, fails, info):
    for side, name in ((pcbnew.F_Cu, "F"), (pcbnew.B_Cu, "B")):
        fine = sorted(r for r, rec in B.fps.items() if rec["side"] == side and rec["fine"])
        if not fine:
            continue
        fid = [P(rec["obj"].GetPosition()) for rec in B.fps.values() if rec["side"] == side
               and ("fiducial" in rec["fpid"].lower() or rec["ref"].startswith("FID"))]
        best = 0.0
        for i in range(len(fid)):
            for j in range(i + 1, len(fid)):
                for k in range(j + 1, len(fid)):
                    (x1, y1), (x2, y2), (x3, y3) = fid[i], fid[j], fid[k]
                    best = max(best, abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2)
        if len(fid) < 3 or best < FID_MIN_TRI_MM2:
            fails["FIDUCIAL"].append({"side": name, "fiducials": len(fid), "triangle_mm2": round(best, 1),
                                      "fine_pitch_parts": fine[:12]})


def chk_pad_axis(B, fails, info):
    for rec in B.fps.values():
        if not rec["fine"]:
            continue
        for p in rec["smd_pads"]:
            if p["net"] in B.force or p["area"] >= EP_MIN_MM2:
                continue
            lo, hi = sorted((p["w"], p["h"]))
            if hi / max(lo, 1e-3) < PAD_AXIS_ASPECT:
                continue
            th = math.radians(p["rot"])
            ax = (math.cos(th), -math.sin(th)) if p["w"] >= p["h"] else (math.sin(th), math.cos(th))
            for L, poly in p["poly"].items():
                for i in B.t_tree.query(poly):
                    t = B.tracks[i]
                    if t["net"] != p["net"] or t["layer"] != L or t["len"] < 1e-4:
                        continue
                    for q, far in ((t["a"], t["e"]), (t["e"], t["a"])):
                        if not poly.contains(Point(q)) or poly.contains(Point(far)):
                            continue
                        a = angle(unit(q, far), ax)
                        a = min(a, 180 - a)
                        if a > PAD_AXIS_DEG + ANGLE_TOL_DEG:
                            d = unit(q, far)
                            near = [o for o in rec["smd_pads"] if o is not p
                                    and math.dist(o["pos"], p["pos"]) <= PAD_AXIS_END_PIN_MM]
                            if near and all(d[0] * (o["pos"][0] - p["pos"][0]) + d[1] * (o["pos"][1] - p["pos"][1]) < 0
                                            for o in near):
                                info.setdefault("pad_axis_end_pin", []).append([B.pad_ref(p), round(a, 1)])
                                continue
                            fails["PAD-AXIS"].append({"pad": B.pad_ref(p), "net": p["net"], "layer": B.lname(L),
                                                      "at": r3(q), "angle": round(a, 1),
                                                      "uuids": [t["obj"].m_Uuid.AsString()]})


def chk_via_hop(B, fails, info):
    def shared(a, c):
        n = 0
        for L in set(a["layers"]) & set(c["layers"]):
            win = box(min(a["pos"][0], c["pos"][0]) - 2, min(a["pos"][1], c["pos"][1]) - 2,
                      max(a["pos"][0], c["pos"][0]) + 2, max(a["pos"][1], c["pos"][1]) + 2)
            net = a["net"]
            parts = [B.tracks[i]["cu"] for i in B.t_tree.query(win) if B.tracks[i]["net"] == net
                     and B.tracks[i]["layer"] == L]
            parts += [p["poly"][L] for p in B.pads_near(L, win) if p["net"] == net]
            f = B.fill(net, L)[0]
            if not f.is_empty:
                parts.append(f.intersection(win))
            if not parts:
                continue
            cu = unary_union(parts)
            for g in getattr(cu, "geoms", [cu]):
                if g.intersects(a["disc"]) and g.intersects(c["disc"]):
                    n += 1
                    break
        return n
    seen = set()
    for a in B.vias:
        if a["net"] in B.force:
            continue
        for k in B.v_tree.query(Point(a["pos"]).buffer(VIA_HOP_MM)):
            c = B.vias[k]
            if k <= a["i"] or c["net"] != a["net"]:
                continue
            d = math.dist(a["pos"], c["pos"])
            if d >= VIA_HOP_MM or (a["i"], k) in seen:
                continue
            seen.add((a["i"], k))
            n = shared(a, c)
            if n == 1:
                fails["VIA-HOP"].append({"net": a["net"], "at": a["pos"], "b": c["pos"], "dist_mm": round(d, 3),
                                         "uuids": [a["obj"].m_Uuid.AsString(), c["obj"].m_Uuid.AsString()]})


# ---------------------------------------------------------------------------------------------- placement checks
def place_supply(B, n):
    """a ground / supply / pour / no-net (PLACE-PINPASSIVE shunt end, PLACE-ORIENT non-target)"""
    return (not n) or n.startswith("unconnected") or is_rail(B, n) or n.startswith(("+", "-")) or n in B.pour


def place_mech(B, rec):
    return bool(PLACE_MECH_RE.match(rec["ref"])) or rec["ref"] in PLACE_MECH_REFS or \
        any(p["net"] in B.force for p in rec["pads"])


def place_passive(rec):
    return rec["two_term"] and (rec["ref"][:1] in ("R", "C", "L") or rec["ref"][:2] == "FB")


def net_pads(B):
    if not hasattr(B, "_net_pads"):
        d = defaultdict(list)
        for p in B.pads:
            if p["net"] and p["num"]:
                d[p["net"]].append(p)
        B._net_pads = d
    return B._net_pads


def fp_courtyard(B, rec):
    if "cy" not in rec:
        L = pcbnew.B_CrtYd if rec["side"] == pcbnew.B_Cu else pcbnew.F_CrtYd
        try:
            g = to_shapely(rec["obj"].GetCourtyard(L))
        except Exception:                                    # noqa: BLE001 - no courtyard: fall back below
            g = Polygon()
        if g.is_empty:
            ps = [next(iter(p["poly"].values())) for p in rec["pads"]]
            g = unary_union(ps).convex_hull.buffer(0.25) if ps else Polygon()
        rec["cy"] = g
    return rec["cy"]


def board_outline(B):
    if not hasattr(B, "_outline"):
        ps = pcbnew.SHAPE_POLY_SET()
        B.b.GetBoardPolygonOutlines(ps, True)
        B._outline = to_shapely(ps)
        try:
            B._edge_clr = mm(B.b.GetDesignSettings().m_CopperEdgeClearance)
        except Exception:                                    # noqa: BLE001
            B._edge_clr = 0.4
    return B._outline


def pad_clr(p, L):
    try:
        return max(mm(p["obj"].GetOwnClearance(L)), 0.2)
    except Exception:                                        # noqa: BLE001
        return 0.2


def ccw_deg(v):
    """KiCad orientation of a direction (screen y down, counter-clockwise positive)"""
    return math.degrees(math.atan2(-v[1], v[0]))


def pinpassive_spot(B, c, crec, prec, s, o, gaps=PINPASSIVE_SPOT_GAPS):
    """the on-axis pose of passive prec (signal pad s, other pad o) at pin pad c: the passive on the pin's long axis,
    its signal pad a gap from c's outward end (the first legal of `gaps`, laterally within +-0.15 mm) -> (pose,
    blockers). Blockers are what does not move for it: the board edge (copper edge clearance), the host's other pads,
    the pads of every IC / crystal (U, X, Y) and the pads / courtyards of mechanically pinned parts (PLACE_MECH_RE, force
    parts), footprint keep-out rule areas, and the host's own courtyard."""
    from shapely import affinity
    L = crec["side"]
    cp = c["poly"][L]
    xs = list(cp.minimum_rotated_rectangle.exterior.coords)
    e1, e2 = (xs[0], xs[1]), (xs[1], xs[2])
    long_e = e1 if math.dist(*e1) >= math.dist(*e2) else e2
    u = unit(*long_e)
    half = math.dist(*long_e) / 2
    pins = [p for p in crec["pads"] if p["num"] and L in p["poly"]]
    cen = (sum(p["pos"][0] for p in pins) / len(pins), sum(p["pos"][1] for p in pins) / len(pins))
    t = (c["pos"][0] - cen[0]) * u[0] + (c["pos"][1] - cen[1]) * u[1]
    ends = [1.0 if t >= 0 else -1.0] if abs(t) > 0.05 * half else [1.0, -1.0]
    Lp = prec["side"]
    sp0, op0, cy0 = s["poly"][Lp], o["poly"][Lp], fp_courtyard(B, prec)
    a = unit(s["pos"], o["pos"])
    inner = board_outline(B).buffer(-B._edge_clr)
    best = None
    lats = (0.0, 0.05, -0.05, 0.1, -0.1, 0.15, -0.15)
    for sg in ends:
        w = (u[0] * sg, u[1] * sg)
        lv = (-w[1], w[0])
        dang = math.degrees(math.atan2(w[1], w[0]) - math.atan2(a[1], a[0]))
        rot = [affinity.rotate(g, dang, origin=s["pos"]) for g in (sp0, op0, cy0, Point(o["pos"]))]
        tmin = min((q[0] - s["pos"][0]) * w[0] + (q[1] - s["pos"][1]) * w[1] for q in rot[0].exterior.coords)
        end = (c["pos"][0] + w[0] * half, c["pos"][1] + w[1] * half)
        for gp in gaps:
            for lt in lats:
                k = -tmin + gp
                sc = (end[0] + w[0] * k + lv[0] * lt, end[1] + w[1] * k + lv[1] * lt)
                dx, dy = sc[0] - s["pos"][0], sc[1] - s["pos"][1]
                sp, op, cy, oc = (affinity.translate(g, dx, dy) for g in rot)
                cu = unary_union([sp, op])
                why = []
                if not inner.contains(cu):
                    why.append("board edge")
                for q in B.pads_near(L, cu.buffer(1.0)):
                    if q is c or q["fp"] is prec or not (q["fp"] is crec or place_mech(B, q["fp"])
                                                         or q["ref"][:1] in ("U", "X", "Y")):
                        continue
                    for g, gn, gpad in ((sp, s["net"], s), (op, o["net"], o)):
                        if q["net"] != gn and g.distance(q["poly"][L]) < max(pad_clr(q, L), pad_clr(gpad, L)) - 1e-4:
                            why.append(f"pad {B.pad_ref(q)}")
                for r in B.fps.values():
                    if r is prec or r["side"] != L or not (r is crec or place_mech(B, r)):
                        continue
                    if fp_courtyard(B, r).intersects(cy):
                        why.append(f"courtyard {r['ref']}")
                for g_ in neighbour_exits(B, c, crec, pins, cen, s["net"]):
                    if g_[1].intersects(cu):
                        why.append(f"exit {g_[0]}")
                for z in B.b.Zones():
                    if z.GetIsRuleArea() and z.GetDoNotAllowFootprints() and z.IsOnLayer(L) and to_shapely(z.Outline()).intersects(cy):
                        why.append(f"keep-out {z.GetZoneName()}")
                rot_deg = (prec["obj"].GetOrientation().AsDegrees() + ccw_deg(w) - ccw_deg(a) + 180) % 360 - 180
                pose = {"x": round((sc[0] + oc.x) / 2, 3), "y": round((sc[1] + oc.y) / 2, 3), "rot": round(rot_deg, 1),
                        "side": "B" if L == pcbnew.B_Cu else "F", "gap_mm": round(gp, 2), "lateral_mm": lt,
                        "pads": {s["num"]: r3(sc), o["num"]: r3((oc.x, oc.y))}}
                if not why:
                    return pose, []
                best = best or (pose, sorted(set(why)))
    return best


def neighbour_exits(B, c, crec, pins, cen, own_net):
    """[(pad ref, corridor)] the straight outward axis-exit corridors of the connector's other netted signal pins near
    pin c (PINPASSIVE_NEIGHBOUR_MM): from each pad's outward end along its long axis, PINPASSIVE_EXIT_MM long,
    PINPASSIVE_EXIT_W / 2 + the pin's clearance either side. Supply / ground / pour pins and the pull's own net excluded."""
    L = crec["side"]
    out = []
    for q in pins:
        n = q["net"]
        if q is c or not n or n == own_net or place_supply(B, n) or math.dist(q["pos"], c["pos"]) > PINPASSIVE_NEIGHBOUR_MM:
            continue
        xs = list(q["poly"][L].minimum_rotated_rectangle.exterior.coords)
        e1, e2 = (xs[0], xs[1]), (xs[1], xs[2])
        le = e1 if math.dist(*e1) >= math.dist(*e2) else e2
        uq = unit(*le)
        half = math.dist(*le) / 2
        t = (q["pos"][0] - cen[0]) * uq[0] + (q["pos"][1] - cen[1]) * uq[1]
        sg = 1.0 if t >= 0 else -1.0
        w = (uq[0] * sg, uq[1] * sg)
        a = (q["pos"][0] + w[0] * half, q["pos"][1] + w[1] * half)
        e = (a[0] + w[0] * PINPASSIVE_EXIT_MM, a[1] + w[1] * PINPASSIVE_EXIT_MM)
        out.append((B.pad_ref(q), LineString([a, e]).buffer(PINPASSIVE_EXIT_W / 2 + pad_clr(q, L), cap_style=2)))
    return out


def pin_axis_fit(c, crec, s, o):
    """(lateral offset mm of the signal pad centre from pin c's long axis, angle deg between the passive's pad-to-pad
    axis and that axis); math.inf when the signal pad lies inward of the pin centre"""
    L = crec["side"]
    xs = list(c["poly"][L].minimum_rotated_rectangle.exterior.coords)
    e1, e2 = (xs[0], xs[1]), (xs[1], xs[2])
    u = unit(*(e1 if math.dist(*e1) >= math.dist(*e2) else e2))
    v = (s["pos"][0] - c["pos"][0], s["pos"][1] - c["pos"][1])
    along = v[0] * u[0] + v[1] * u[1]
    lat = abs(v[0] * u[1] - v[1] * u[0])
    a = unit(s["pos"], o["pos"])
    if a is None:
        return math.inf, math.inf
    ang = math.degrees(math.acos(min(1.0, abs(a[0] * u[0] + a[1] * u[1]))))
    if abs(along) < 1e-6 or (a[0] * u[0] + a[1] * u[1]) * along < 0:     # other pad must lie farther out than the signal pad
        return lat, math.inf
    return lat, ang


def chk_place_pinpassive(B, fails, info):
    """PLACE-PINPASSIVE: a shunt passive (pull-up / pull-down / termination / filter: one pad on a connector pin's
    signal net, the other on a ground / supply) that serves that pin sits on the pin's axis just off its end"""
    NP = net_pads(B)
    n_ok, no_spot, far, series = 0, [], [], set()
    for crec in B.fps.values():
        if crec["ref"][:1] != "J" or len([p for p in crec["pads"] if p["num"]]) < 4:
            continue
        for c in crec["pads"]:
            n = c["net"]
            if not c["smd"] or not c["num"] or crec["side"] not in c["poly"] or place_supply(B, n):
                continue
            if any(q["fp"] is crec and q is not c for q in NP[n]):
                continue                                   # a net on two pins of the connector: no single pin
            shunts, others = [], []
            for q in NP[n]:
                r = q["fp"]
                if r is crec:
                    continue
                if place_passive(r):
                    o = [x for x in r["smd_pads"] if x is not q]
                    if o and place_supply(B, o[0]["net"]):
                        shunts.append((r, q, o[0]))
                        continue
                    if o and r["ref"][:1] == "R":
                        series.add(f"{r['ref']}@{B.pad_ref(c)}")
                others.append(q)
            if not shunts or len(others) > 1:
                continue
            cands = []
            for r, s, o in shunts:
                same = r["side"] == crec["side"]
                gap = s["poly"][r["side"]].distance(c["poly"][crec["side"]]) if same else math.inf
                d_far = min((math.dist(s["pos"], q["pos"]) for q in others), default=math.inf)
                cands.append((not math.dist(s["pos"], c["pos"]) <= d_far, gap, r["ref"], r, s, o, same))
            cands.sort(key=lambda x: x[:3])
            not_at_conn, gap, _, r, s, o, same = cands[0]
            end, erec, lim = c, crec, PINPASSIVE_GAP_MM
            if not_at_conn:                                # the pull sits at its far load: it belongs at THAT pin
                q = min(others, key=lambda q: math.dist(s["pos"], q["pos"]))
                if q["ref"][:1] != "U" or not q["smd"] or q["fp"]["side"] not in q["poly"]:
                    far.append(f"{r['ref']}@{B.pad_ref(q)}")
                    continue
                end, erec, lim = q, q["fp"], PINPASSIVE_IC_GAP_MM
                same = r["side"] == erec["side"]
                gap = s["poly"][r["side"]].distance(q["poly"][erec["side"]]) if same else math.inf
            lat, ang = pin_axis_fit(end, erec, s, o) if same else (math.inf, math.inf)
            if gap <= lim and lat <= PINPASSIVE_AXIS_MM and ang <= PINPASSIVE_AXIS_DEG:
                n_ok += 1
                continue
            pose, why = pinpassive_spot(B, end, erec, r, s, o, tuple(g for g in PINPASSIVE_SPOT_GAPS if g <= lim))
            item = {"part": r["ref"], "pin": B.pad_ref(end), "connector_pin": B.pad_ref(c), "net": n, "value": r["value"],
                    "gap_mm": None if math.isinf(gap) else round(gap, 2), "same_side": same, "limit_mm": lim,
                    "axis_offset_mm": None if math.isinf(lat) else round(lat, 3),
                    "axis_angle_deg": None if math.isinf(ang) else round(ang, 1),
                    "at": P(r["obj"].GetPosition()), "far_load": [B.pad_ref(q) for q in others], "propose": pose}
            if why:
                item["blocked_by"] = why
                no_spot.append(item)
            else:
                item["what"] = ("other side" if not same else
                                f"{round(gap, 2)} mm gap, "
                                + ("no pin axis" if math.isinf(lat) else f"{round(lat, 2)} mm / "
                                   + ("reversed" if math.isinf(ang) else f"{round(ang)} deg") + " off the pin axis")) + \
                    f" at {B.pad_ref(end)} (limit {lim} mm gap, on axis); on-axis spot free"
                fails["PLACE-PINPASSIVE"].append(item)
    info["pinpassive_on_axis"] = n_ok
    info["pinpassive_no_spot"] = no_spot
    info["pinpassive_at_far_load"] = sorted(far)
    info["pinpassive_series_not_scope"] = sorted(series)


def orient_model(B, rec):
    """PLACE-ORIENT: (satellites, {pin num: (pad, [target pads])}) of IC rec. Satellites move with the IC: two-terminal
    passives on its nets whose signal nets reach no other IC (pull-ups, series parts, RC parts), and rail decaps whose
    nearest IC on that rail is this one. A pin's targets are the same-net pads off the IC and its satellites; a pin
    that only reaches satellites looks through a series satellite to the next net (one hop). Ground / pour nets and
    rails with more than ORIENT_BIG_NET pads have no target."""
    NP = net_pads(B)
    big = lambda n: len(NP.get(n, ())) > ORIENT_BIG_NET
    ground = lambda n: (not n) or n.startswith("unconnected") or bool(GROUND_RE.match(n)) or n in B.pour
    xn = {p["net"] for p in rec["pads"] if not ground(p["net"])}
    sats = set()
    for r in B.fps.values():
        if r is rec or not place_passive(r):
            continue
        ns = [p["net"] for p in r["smd_pads"]]
        if not any(n in xn for n in ns):
            continue
        sig = [n for n in ns if not place_supply(B, n) and not big(n)]
        if sig:
            if all(any(q["fp"] is rec for q in NP[n]) or not any(q["ref"][:1] == "U" and q["fp"] is not rec for q in NP[n])
                   for n in sig):
                sats.add(r["ref"])
        else:
            pos = P(r["obj"].GetPosition())
            best = min(((math.dist(q["pos"], pos), q["ref"]) for n in ns if not ground(n) and n in xn for q in NP[n]
                        if q["ref"][:1] == "U"), default=None)
            if best and best[1] == rec["ref"]:
                sats.add(r["ref"])
    T = {}
    for p in rec["pads"]:
        n = p["net"]
        if not p["num"] or ground(n) or big(n):
            continue
        cand = [q for q in NP[n] if q["fp"] is not rec and q["ref"] not in sats]
        if not cand:
            for sref in sorted(sats):
                ps = B.fps[sref]["smd_pads"]
                if any(q["net"] == n for q in ps):
                    m = [q["net"] for q in ps if q["net"] != n]
                    if m and not place_supply(B, m[0]) and not big(m[0]):
                        cand += [q for q in NP[m[0]] if q["fp"] is not rec and q["ref"] not in sats]
        if cand:
            T.setdefault(p["num"], (p, cand))
    return sats, T


def _xing(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def _turn(p, ctr, k):
    dx, dy = p["pos"][0] - ctr[0], p["pos"][1] - ctr[1]
    for _ in range(k):                                    # screen-clockwise 90 deg (y down): east -> south
        dx, dy = -dy, dx
    return dx, dy


def orient_eval(T, ctr, at, k):
    """(airwire length, own crossings) of the pins in T with the IC centre moved ctr -> at, turned k x 90 deg
    screen-clockwise; each pin to its nearest target"""
    segs, tot = [], 0.0
    for p, cand in T.values():
        dx, dy = _turn(p, ctr, k)
        a = (at[0] + dx, at[1] + dy)
        q = min(cand, key=lambda q: math.dist(a, q["pos"]))
        tot += math.dist(a, q["pos"])
        segs.append((a, q["pos"], p["net"]))
    x = sum(1 for i in range(len(segs)) for j in range(i + 1, len(segs))
            if segs[i][2] != segs[j][2] and _xing(segs[i][0], segs[i][1], segs[j][0], segs[j][1]))
    return tot, x


def orient_median(T, ctr, k):
    """the IC centre (turned k) minimising the airwire to the targets nearest now: geometric median (Weiszfeld)"""
    pts = []
    for p, cand in T.values():
        dx, dy = _turn(p, ctr, k)
        q = min(cand, key=lambda q: math.dist((ctr[0] + dx, ctr[1] + dy), q["pos"]))
        pts.append((q["pos"][0] - dx, q["pos"][1] - dy))
    x, y = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    for _ in range(100):
        w = [1.0 / max(math.dist((x, y), p), 1e-3) for p in pts]
        x, y = sum(wi * p[0] for wi, p in zip(w, pts)) / sum(w), sum(wi * p[1] for wi, p in zip(w, pts)) / sum(w)
    return (x, y)


def orient_links(B, rec):
    """PLACE-ORIENT facing (review-M4 facing.py): per signal pin, the nearest pad of every other part on its net (nets
    with at most ORIENT_FACE_NET_PARTS parts, no rail / ground), except a two-terminal passive hanging only on this pin
    (it moves with the IC)"""
    NP = net_pads(B)
    out = []
    for p in rec["pads"]:
        n = p["net"]
        if not p["num"] or place_supply(B, n):
            continue
        others = defaultdict(list)
        for q in NP[n]:
            if q["fp"] is not rec:
                others[q["ref"]].append(q)
        if not others or len(others) > ORIENT_FACE_NET_PARTS:
            continue
        for r2, qs in others.items():
            r = B.fps[r2]
            if place_passive(r):
                o = [x for x in r["smd_pads"] if x["net"] != n]
                if o and (place_supply(B, o[0]["net"]) or len({x["ref"] for x in NP[o[0]["net"]]}) <= 2):
                    continue
            out.append((p, min(qs, key=lambda q: math.dist(p["pos"], q["pos"]))))
    return out


def orient_behind(links, ctr, k):
    """pins (turned k x 90 deg screen-clockwise about ctr) whose partner lies > ORIENT_FACE_DEG off the pin's outward
    normal (centre -> pin) and farther than ORIENT_FACE_MM"""
    cmax = math.cos(math.radians(ORIENT_FACE_DEG))
    out = []
    for p, q in links:
        dx, dy = _turn(p, ctr, k)
        px, py = ctr[0] + dx, ctr[1] + dy
        vx, vy = q["pos"][0] - px, q["pos"][1] - py
        d, nr = math.hypot(vx, vy), math.hypot(dx, dy) or 1.0
        if d > ORIENT_FACE_MM and (dx * vx + dy * vy) / (nr * d) < cmax:
            out.append(f"{p['num']}->{B_ref(q)}")
    return out


def B_ref(q):
    return f"{q['ref']}.{q['num']}"


def chk_place_orient(B, fails, info):
    """PLACE-ORIENT: an IC turned or placed against its own airwires, or a cable-domain interface IC away from its
    connector"""
    n = 0
    conns = [r for r in B.fps.values() if r["ref"][:1] == "J" and len([p for p in r["pads"] if p["num"]]) >= 4]
    for rec in B.fps.values():
        if rec["ref"][:1] != "U" or len([p for p in rec["pads"] if p["num"]]) < ORIENT_MIN_PINS:
            continue
        if rec["ref"] in PLACE_ORIENT_EXEMPT.get(B.kind, {}):
            info.setdefault("orient_exempt", []).append(rec["ref"])
            continue
        if place_mech(B, rec):
            continue
        sats, T = orient_model(B, rec)
        if len(T) < 2:
            continue
        n += 1
        ctr = P(rec["obj"].GetPosition())
        rot0 = rec["obj"].GetOrientation().AsDegrees()
        turn = lambda k: round((rot0 - 90 * k + 180) % 360 - 180, 1)
        ev = [orient_eval(T, ctr, ctr, k) for k in range(4)]
        L0, X0 = ev[0]
        near = [min(c, key=lambda q: math.dist(p["pos"], q["pos"]))["pos"] for p, c in T.values()]
        cen = (sum(t[0] for t in near) / len(near), sum(t[1] for t in near) / len(near))
        base = {"part": rec["ref"], "value": rec["value"], "at": ctr, "rot": round(rot0, 1), "airwire_mm": round(L0, 1),
                "crossings": X0, "pins": len(T), "target_centroid_mm": round(math.dist(ctr, cen), 1),
                "satellites": sorted(sats), "by_rotation": [[90 * k, round(e[0], 1), e[1]] for k, e in enumerate(ev)]}
        kb = min(range(1, 4), key=lambda k: ev[k])
        if L0 - ev[kb][0] >= max(ORIENT_ROT_GAIN * L0, ORIENT_MIN_GAIN_MM):
            fails["PLACE-ORIENT"].append(dict(base, kind="rotation", propose={"rot": turn(kb), "airwire_mm": round(ev[kb][0], 1), "crossings": ev[kb][1]},
                                              what=f"turning {90 * kb} deg screen-clockwise cuts the airwire {round(L0, 1)} -> {round(ev[kb][0], 1)} mm"))
        else:
            links = orient_links(B, rec)
            if len(links) >= ORIENT_FACE_MIN:
                fb = [len(orient_behind(links, ctr, k)) for k in range(4)]
                kf = min(range(1, 4), key=lambda k: (fb[k], ev[k][0]))
                if (fb[0] >= ORIENT_FACE_MIN and fb[0] >= ORIENT_FACE_FRAC * len(links) and fb[0] - fb[kf] >= ORIENT_FACE_MIN
                        and fb[kf] <= fb[0] / 2):
                    fails["PLACE-ORIENT"].append(dict(base, kind="facing", links=len(links), behind=fb[0],
                                                      behind_pins=orient_behind(links, ctr, 0),
                                                      propose={"rot": turn(kf), "behind": fb[kf], "airwire_mm": round(ev[kf][0], 1)},
                                                      what=f"{fb[0]} of {len(links)} pin links point behind their pins; turning {90 * kf} deg screen-clockwise leaves {fb[kf]}"))
        best = None
        for k in range(4):
            at = orient_median(T, ctr, k)
            Lk = orient_eval(T, ctr, at, k)[0]
            if best is None or Lk < best[0]:
                best = (Lk, at, k)
        moved = math.dist(best[1], ctr)
        if best[0] <= (1 - ORIENT_POS_GAIN) * L0 and moved > ORIENT_POS_MM and L0 - best[0] >= ORIENT_MIN_GAIN_MM:
            fails["PLACE-ORIENT"].append(dict(base, kind="position", what=f"a pose {round(moved, 1)} mm away halves the airwire ({round(L0, 1)} -> {round(best[0], 1)} mm)",
                                              propose={"x": round(best[1][0], 2), "y": round(best[1][1], 2), "rot": turn(best[2]), "airwire_mm": round(best[0], 1)}))
        # cable-domain interface (owner 2026-10-05, U904): an IC powered from a connector's supply pin AND wired to that
        # connector's signal pins lives in the cable's domain: it sits at the connector
        for crec in conns:
            cnets = {p["net"] for p in crec["pads"] if p["net"]}
            mine = [p for p in rec["pads"] if p["num"] and p["net"] in cnets and not GROUND_RE.match(p["net"]) and p["net"] not in B.pour]
            rails = [p for p in mine if place_supply(B, p["net"]) and len(net_pads(B)[p["net"]]) <= ORIENT_BIG_NET]
            sigs = [p for p in mine if not place_supply(B, p["net"])]
            if not rails or not sigs:
                continue
            d = [min(math.dist(p["pos"], q["pos"]) for q in crec["pads"] if q["net"] == p["net"]) for p in rails + sigs]
            mean = sum(d) / len(d)
            if mean > IFACE_MM:
                fails["PLACE-ORIENT"].append(dict(base, kind="cable-interface", connector=crec["ref"], cable_mean_mm=round(mean, 1),
                                                  cable_pins=[B.pad_ref(p) for p in rails + sigs],
                                                  what=f"powered from {crec['ref']} ({', '.join(sorted({p['net'] for p in rails}))}) and wired to its signal pins, "
                                                       f"but its cable pins are {round(mean, 1)} mm (mean) from them (> {IFACE_MM})"))
    info["orient_ics"] = n


RUN = {"VIA-INPAD": chk_via_inpad, "VIA-PADGAP": chk_via_padgap, "XSTACK": chk_xstack,
       "TRACK-FOLD": chk_fold_acute, "ACUTE": chk_fold_acute, "THREAD": chk_thread, "POWER-PAD-CONN": chk_power_pad,
       "VIA-CURRENT": chk_via_current, "NECK-SMALLPAD": chk_neck_smallpad, "POUR-STITCH": chk_pour_stitch,
       "DECAP-LOOP": chk_decap_loop, "SERIES-TERM": chk_series_term, "XTAL": chk_xtal, "DIFFPAIR": chk_diffpair,
       "PLANE-SLOT": chk_plane_slot, "FIDUCIAL": chk_fiducial, "PAD-AXIS": chk_pad_axis, "VIA-HOP": chk_via_hop,
       "PLACE-PINPASSIVE": chk_place_pinpassive, "PLACE-ORIENT": chk_place_orient}


def check(pcb, checks=CHECKS):
    unknown = set(checks) - set(CHECKS)
    if unknown or not checks:
        raise ValueError(f"unknown / empty checks: {sorted(unknown)}")
    B = Board(pcb)
    fails = {k: [] for k in CHECKS}
    info = {}
    done = set()
    for c in CHECKS:
        if c in checks and RUN[c] not in done:
            done.add(RUN[c])
            RUN[c](B, fails, info)
    for c in CHECKS:                                   # a shared pass (TRACK-FOLD / ACUTE) reports only what was asked
        if c not in checks:
            fails[c] = []
    consts = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float))}
    return {"board": str(pcb), "kind": B.kind, "checks": list(checks), "constants": consts,
            "status": "FAIL" if any(fails[c] for c in checks) else "PASS",
            "counts": {k: len(v) for k, v in fails.items()}, "fails": fails, "info": info}


def require(pcb, out_json, checks=CHECKS):
    """fab_outputs / routing / candidate-validation hook (KiCad Python): raises on any FAIL."""
    res = check(pcb, checks)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if res["status"] != "PASS":
        raise RuntimeError(f"qa_layout_quality FAILED {res['counts']} (report: {out_json})")
    return out_json


def counts(pcb, out_json=None, checks=CHECKS):
    """routing-driver hook (KiCad Python): per-check finding counts for a stage log; never raises on findings."""
    res = check(pcb, checks)
    if out_json:
        Path(out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return {k: res["counts"][k] for k in checks}


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
        print(f"qa_layout_quality ERROR: {e!r}")
        return 2
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"qa_layout_quality {res['status']}  {a.board}  ({res['kind']})")
    for k in CHECKS:
        items = res["fails"][k]
        state = ("FAIL" if items else "ok") if k in res["checks"] else "(not gated)"
        print(f"  {k:14s} {state:4s} {len(items)}")
        for it in items[:12]:
            print("     ", json.dumps({x: y for x, y in it.items() if x != "uuids"}, default=str)[:240])
    print(f"  info: {json.dumps(res['info'], default=str)[:600]}")
    bad = ", ".join(f"{k} {len(res['fails'][k])}" for k in CHECKS if res["fails"][k] and k in res["checks"])
    print(f"qa_layout_quality {res['status']}" + (f": {bad}" if bad else ""))           # last line: the run_gates summary
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
