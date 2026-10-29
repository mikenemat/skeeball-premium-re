"""Scripted heavy-current copper (LOCKED, so the router and the cleanup keep it): run with KiCad's Python after place.py,
before routing (docs/ROUTING_PLAYBOOK.md).
    "C:/Program Files/KiCad/10.0/bin/python.exe" power_copper.py [BOARD]
What it adds (owner 2026-10-26 / 2026-10-27; currents from design.py notes, widths per IPC-2152 1 oz external):
  +5V_IN trunk  J1 (top right) -> PTCs F1 / F2 (top left), up to 5.5 A: a B.Cu zone strip along the top edge (dips
                under the J9 shell pegs, tongue at the PTCs), an F.Cu zone joining both PTC inputs, 18 vias between
                them; J1.1 -> D1 (TVS) -> C4 (eFuse input) on F.Cu.
                The eFuse input branch D1 -> C4 -> U1.4 / U1.3 (DECISIONS #4); C5 / R1 signal-level leaves.
  +5V_RGB       F1 -> C2 -> C1 -> J7.1, 2.5 mm (4 A cap, 20 K budget: DECISIONS #5), clear of the J7 peg keep-out.
  +5V_PF        F2 -> J8.1 1.2 mm (1.5 A cap) + C3.
(routing agent pass 2026-10-27, handed over by the lead: 20 K widths, pad-centre ends, eFuse neck, leaves.)
  LED_*_K       FET drains -> J7 / J8 cathode pins, 1.2 / 1.0 mm, one planar fan (Q1..Q3 = R, G, B top to bottom).
Coordinates follow place.py's POS (re-check here when a part of this group moves: each path asserts its end pads).
"""
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
BOARD = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "hardware" / "main" / "skeeball-controller.kicad_pcb"
mm = pcbnew.FromMM

# zones: name, net, layer, priority, outline (mm, board frame)
ZONES = [
    # q6 (2026-10-27, coordinator QA A1 / A2; power review P1): necks widened - strip bottom 5.4 -> 6.8 (x 23.4 .. 86),
    # J9 dip 53.8 .. 69.2 x 9.6 -> 51.0 .. 72.0 x 11.4 (notch-corner diagonals 1.84 -> ~4.6 mm), J1 leg left edge
    # 93.2 -> 90.0 (around the J1 peg keep-out); x 86 .. 90 stays at 5.4 for the D1 GND patch vias (D1_GND_VIAS)
    ("PWR_5VIN_TRUNK_B", "+5V_IN", pcbnew.B_Cu, 2,
     [(11.8, 0.6), (55.6, 0.6), (55.6, 5.8), (67.4, 5.8), (67.4, 0.6), (98.0, 0.6), (98.0, 13.2), (90.0, 13.2),
      (90.0, 5.4), (86.0, 5.4), (86.0, 6.8), (72.0, 6.8), (72.0, 11.4), (51.0, 11.4), (51.0, 6.8), (23.4, 6.8),
      (23.4, 8.8), (11.8, 8.8)]),
    ("PWR_5VIN_PTC_F", "+5V_IN", pcbnew.F_Cu, 2,
     [(11.8, 6.5), (22.7, 6.5), (22.7, 10.9), (15.4, 10.9), (15.4, 12.2), (11.8, 12.2)]),
]
# current capacity (pass 5 (C), mirrored here q5 2026-10-27): a parallel +5V_IN pour on In2.Cu with the B.Cu trunk's
# outline (B 1 oz + In2 0.5 oz over the J9 notch, where the B strip is 3.7 mm: >= 4.5 mm 1 oz equivalent for 5.5 A),
# joined by the J1.1 THT pad and the F1 / F2 via array
ZONES.append(("PWR_5VIN_TRUNK_IN2", "+5V_IN", pcbnew.In2_Cu, 2, ZONES[0][4]))
# J1.3 = the only board GND entry (5.5 A return, current_budget BRANCHES GND): solid F.Cu GND patch around the pad
# (priority 1 over the soft GND_F pour, so routing never carves it) + 6 stitching vias into the In1 plane / B pour,
# and the pad's zone connection solid on every layer (pass 5 (B): no thermal spokes)
ZONES.append(("GND_J1_F", "GND", pcbnew.F_Cu, 1, [(101.4, 7.2), (106.2, 7.2), (106.2, 13.7), (101.4, 13.7)]))
SOLID_PADS = []
# q6 (coordinator QA A8, power review M9): J1 pins 1 / 3 on 4-spoke thermal reliefs, 1.0 mm spokes, every layer (a solid
# 1.8 mm hole into the trunk / plane risks poor THT fill); kept because the connectivity-aware min cut stays >= 4.5 mm
# 1 oz-equivalent (q6 measurement: the trunk limit 5.7 mm sits under J9, not at J1)
THERMAL_PADS = {"J1.1": (1.0, 0.0), "J1.3": (1.0, 0.0)}      # spoke width mm, spoke angle deg (0 = 4 spokes at 0/90)
# U3 TLV74311 (SOT-23-5, no EP) heat copper (adversarial review L4, q5 2026-10-27): F.Cu GND under the body from pin 2
# (its drop via inside) and an OUT (+1V1) land pin 5 -> C14.1; clear of pins 1 / 3 / 4 by >= 0.2 mm
ZONES.append(("U3_GND_F", "GND", pcbnew.F_Cu, 1, [(68.6, 41.05), (70.85, 41.05), (70.85, 42.0), (68.6, 42.0)]))
ZONES.append(("U3_OUT_F", "+1V1", pcbnew.F_Cu, 1, [(71.1, 40.1), (73.8, 40.1), (73.8, 41.0), (71.1, 41.0)]))
# q6 (coordinator QA A3, power review P3: the TVS return was a 0.2 mm stub to one via): solid F.Cu GND patch under
# D1.2 (priority 1, full pad connection) + 5 vias into the In1 plane (D1_GND_VIAS), clear of D1.1 (+5V_IN, y >= 9.9)
ZONES.append(("D1_GND_F", "GND", pcbnew.F_Cu, 1, [(85.9, 5.0), (90.2, 5.0), (90.2, 9.45), (85.9, 9.45)]))

J1_GND_VIAS = [("GND", x, y, 0.6, 0.3) for x, y in ((101.85, 9.2), (101.85, 11.6), (105.75, 9.2), (105.75, 11.6),
                                                    (103.8, 7.75), (103.8, 13.1))]
# via array joining the two +5V_IN zones (inside both outlines, clear of F1.1's pad edge at y 8.66)
VIAS = [("+5V_IN", 12.6 + 1.2 * i, y, 0.6, 0.3) for y in (7.0, 7.9) for i in range(9)] + J1_GND_VIAS
D1_GND_VIAS = [("GND", x, y, 0.6, 0.3) for x, y in ((86.75, 6.3), (86.75, 7.4), (86.75, 8.5), (87.9, 8.95), (89.1, 8.95))]
VIAS += D1_GND_VIAS
# tracks: net, width, layer, polyline, (start pad, end pad) asserted on the net (None = a via / own track end)
# widths: current_budget at DT_LOAD_K 20 K (DECISIONS #5): +5V_RGB 4 A 2.43 -> 2.5; LED_*_K 2 A 0.63; +5V_PF 1.5 A 0.36;
# +5V_IN eFuse branch 2.5 A 0.97 (DECISIONS #4); every end at its pad centre (qa_copper_landing PAD-CENTRE)
F, B = pcbnew.F_Cu, pcbnew.B_Cu
# GND drop vias the router cannot reach (closure pass 5, 2026-10-27): U2 (TLV62569, 180 deg) has its GND pin 2 between SW
# (pin 3, facing L1.1 at 0.55 mm) and EN (pin 1, +5V_SYS): in p8-p10 pfr2 ran the +5V_SYS EN feed past it and pin 2
# was left with no fill and no via. One 0.6 / 0.3 via under the body centre (0.18 mm to the pin rows) + a 0.3 mm stub
# from the pad centre = the TI layout's GND via at pin 2. (ref pad, via xy)
GND_DROPS = [("U2.2", (76.0, 25.0), 0.5),    # q6 (QA A7): stub 0.3 -> 0.5 mm (0.4 mm to pins 1 / 3)
             # q5 (2026-10-27): U5 pin 62 (GND, top row) straight up between pins 61 / 63 to a via clear of C25.1
             ("U5.62", (63.4, 34.05)),
             # q6 (2026-10-27): C29.2 (DVDD pin-32 decap GND) is ringed by the Q6_XTAL XOUT stub (left / below), so its
             # drop sits right of the pad, 0.15 mm above the XOUT stub (pfr2 left it caged: open join C29.2 - Y1.4)
             ("C29.2", (61.8, 47.2)),
             # q6 (coordinator QA A2): drops moved out of the widened +5V_IN trunk dip (they cut the east neck to ~3.3 mm):
             # C16 (VBUS_HOST cap, now 180 deg) GND into the J9 notch; R7.2 right of R7, east of the dip wall (x 72)
             ("C16.2", (66.6, 5.0)), ("R7.2", (73.95, 8.68))]
TRACKS = [
    ("+5V_IN", 1.5, F, [(95.40, 10.39), (88.5, 11.15)], ("J1.1", "D1.1")),       # J1.1 = TODO-3 scan re-anchor
    # eFuse input branch (DECISIONS #4, 2.5 A -> 0.97 mm; place.py 2026-10-27: U1 at 180 deg, IN pins 4 / 3 at its
    # top-right corner straight under C4): D1 -> C4.1 at 1.0 mm, C4.1 -> U1.4 1.0 mm then the <= 1.0 mm 0.25 neck into
    # the 0.25 mm pin (current_budget neck), U1.4 -> U1.3 along the pad column
    ("+5V_IN", 1.0, F, [(88.5, 11.15), (86.8, 12.85), (84.95, 12.85), (84.95, 14.6)], ("D1.1", "C4.1")),

    # signal-level +5V_IN leaves (DECISIONS #4: 0.1 A): bulk C5 off the D1 feed corner, the UVLO divider top R1 off C5
    ("+5V_IN", 0.6, F, [(86.8, 12.85), (87.75, 13.8), (87.75, 14.6)], (None, "C5.1")),
    ("+5V_IN", 0.3, F, [(87.75, 14.6), (87.75, 17.275), (88.225, 17.75)], ("C5.1", "R1.1")),
    ("+5V_RGB", 2.5, F, [(19.8, 16.387), (18.6, 16.387), (11.7, 23.287), (11.7, 24.5)], ("F1.2", "C1.1")),   # p7 short: clear of C2.2 / C3.2
    ("+5V_RGB", 1.0, F, [(18.05, 19.0), (17.02, 17.97)], ("C2.1", None)),
    # clear of the J7 peg's NPTH keep-out (hole r 1.5 + 0.4 at (5.91, 32.24)): the run sits at x 2.2
    # (J7 / J8 / J1 pad ends follow the TODO-3 scan re-anchor 2026-10-26: J7.1-4 at x 3.81 + 4.2 k, y 37.79; J8.1
    # (4.885, 15.12), J8.2 (4.885, 11.16); J1.1 (95.40, 10.39))
    ("+5V_RGB", 2.5, F, [(11.7, 24.5), (9.9, 26.3), (2.2, 26.3), (2.2, 37.79), (3.81, 37.79)], ("C1.1", "J7.1")),
    ("+5V_PF", 1.2, F, [(13.0, 15.637), (12.483, 15.12), (4.885, 15.12)], ("F2.2", "J8.1")),
    ("+5V_PF", 1.0, F, [(10.95, 15.12), (10.95, 18.6)], (None, "C3.1")),          # C3 at (11.9, 18.6) (TODO-3)
    ("LED_PF_K", 1.0, F, [(8.662, 6.9), (5.8, 10.4), (4.885, 11.16)], ("Q4.3", "J8.2")),  # Q4 at y 6.9 (TODO-3)
    ("LED_R_K", 1.2, F, [(21.56, 32.5), (9.8, 32.5), (8.01, 34.29), (8.01, 37.79)], ("Q1.3", "J7.2")),
    ("LED_G_K", 1.2, F, [(21.56, 36.5), (21.0, 36.5), (19.0, 34.5), (13.5, 34.5), (12.21, 35.79), (12.21, 37.79)],
     ("Q2.3", "J7.3")),
    ("LED_B_K", 1.2, F, [(21.56, 40.5), (21.0, 40.5), (19.4, 38.9), (17.52, 38.9), (16.41, 37.79)], ("Q3.3", "J7.4")),
    # MAX98357A VDD pins 7 / 8 (0.25 mm pads at 0.5 mm pitch): pfr2 never bridges two adjacent pins of a current net
    # (every pass left U8.7 - U8.8 open); a 0.25 mm pad-centre bridge = the current_budget neck between two own pads
    ("+5V_SYS", 0.25, F, [(90.75, 49.938), (91.25, 49.938)], ("U8.7", "U8.8")),
    # eFuse FLT (U1.6) escape (4-layer q1, 2026-10-27): the frozen +5V_SYS trunk leaves OUT (pin 5) across the FLT /
    # ILM pin fronts, so pfr2 never reached pin 6 (q1 stages 1-3). FLT leaves straight left through the C9 / R3 lane
    # (C9 at y 16.5, place.py) to a via 0.2 mm clear of both pads; PWR_FAULT_N continues on any layer from there.
    ("PWR_FAULT_N", 0.2, F, [(83.05, 17.25), (81.5, 17.25), (80.9, 17.45)], ("U1.6", None)),
]
# q5 placement wave (2026-10-27): crystal + decap escapes pfr2 kept detouring (XIN 11.6 mm / 2 vias, C20 / C21 / C24 loops 3.2-7.5 mm). Straight pad-centre stubs, locked, on the place.py
# positions (Y1 270 deg under U5 pin 30, C21 at x 58.8; the Y2 group move caged the button nets west of U5 - reverted). Kept as its own list so
# .runtime/route/add_locked.py can add exactly these to an already routed board (a KiCad 10 Remove of locked copper
# corrupts the board object, so this script cannot be re-run on a routed board).
Q5_STUBS = [
    ("XIN", 0.2, F, [(59.8, 44.95), (59.8, 48.75)], ("U5.30", "Y1.1")),
    ("XIN", 0.2, F, [(59.8, 48.75), (58.075, 48.75)], ("Y1.1", "C35.1")),
    ("+3V3", 0.2, F, [(57.4, 44.95), (57.4, 46.22)], ("U5.24", "C20.1")),
    ("+3V3", 0.2, F, [(59.4, 44.95), (59.4, 45.62), (58.8, 46.22)], ("U5.29", "C21.1")),
    ("+3V3", 0.2, F, [(64.95, 36.6), (65.55, 36.6), (65.75, 36.4), (66.14, 36.4)], ("U5.59", "C24.1")),
    ("+3V3", 0.2, F, [(64.95, 36.2), (65.55, 36.2), (65.75, 36.4)], ("U5.60", None)),
]
TRACKS += Q5_STUBS
# light FET source returns (current_budget BRANCHES GND: 2 A per channel): >= 1.2 mm F.Cu from each Q1-Q3 source pad
# to 2 GND vias (+ pfr2's own drop via = 3 per FET); Q4 (playfield) 1.0 / 0.8 mm (its gate feed LIGHT_PF_G runs 0.2 mm
# beside the pad column, R72.1 above) to 3 vias (+ pfr2's). Pass 5 (A) added the Q1 / Q4 vias on the routed board;
# q5 (2026-10-27) completed Q2 / Q3 and moved all of them here.
Q5_FET_VIAS = [("GND", x, y, 0.6, 0.3) for x, y in (
    (23.4375, 30.8), (23.4375, 32.3), (23.4375, 34.6), (24.9, 35.55), (23.4375, 38.6), (24.9, 39.55),
    (9.588, 4.9), (10.5375, 6.65))]
VIAS += Q5_FET_VIAS
Q5_FET = [
    ("GND", 1.2, F, [(23.4375, 31.55), (23.4375, 30.8)], ("Q1.2", None)),
    ("GND", 1.2, F, [(23.4375, 31.55), (23.4375, 32.3)], ("Q1.2", None)),
    ("GND", 1.2, F, [(23.4375, 35.55), (23.4375, 34.6)], ("Q2.2", None)),
    ("GND", 1.2, F, [(23.4375, 35.55), (24.9, 35.55)], ("Q2.2", None)),
    ("GND", 1.2, F, [(23.4375, 39.55), (23.4375, 38.6)], ("Q3.2", None)),
    ("GND", 1.2, F, [(23.4375, 39.55), (24.9, 39.55)], ("Q3.2", None)),
    ("GND", 1.0, F, [(10.5375, 5.95), (10.5375, 6.65)], ("Q4.2", None)),
    ("GND", 0.8, F, [(10.5375, 5.95), (9.588, 4.9)], ("Q4.2", None)),
]
TRACKS += Q5_FET
# J9 micro-B shell lands (adversarial review L3 / F07, q5 2026-10-27): every shell land joined on F.Cu to a GND land
# with a via (the inner top shell pads 60.43 / 62.43 carry the GND vias, pin 5 = GND); 0.4 mm
Q5_J9 = [
    ("GND", 0.4, F, [(58.41, 1.45), (60.43, 1.45)], (None, None)),
    ("GND", 0.4, F, [(64.45, 1.45), (62.43, 1.45)], (None, None)),
    ("GND", 0.4, F, [(58.93, 4.15), (60.13, 4.15)], (None, "J9.5")),
    ("GND", 0.4, F, [(63.93, 4.15), (64.45, 1.45)], (None, None)),
]
TRACKS += Q5_J9
# q6 crystal drive (2026-10-27, coordinator QA B5 / logic review L-02: XOUT was 13.1 mm with 3 vias): XOUT pin 31 straight
# down the lane between the locked XIN stub (x 59.8) and C29 (pads from x 60.69), under C29.2 / above the Y1 pads
# (y 47.755: 0.2 mm to both), to R14.1; XOUT_X from R14.2 down to C36.1 and on to Y1.3. All F.Cu, no via.
Q6_XTAL = [
    ("XOUT", 0.2, F, [(60.2, 44.95), (60.2, 47.755), (62.94, 47.755)], ("U5.31", "R14.1")),
    ("XOUT_X", 0.2, F, [(63.96, 47.755), (63.96, 49.665), (63.4, 50.225)], ("R14.2", "C36.1")),
    ("XOUT_X", 0.2, F, [(63.4, 50.225), (62.675, 50.95), (61.5, 50.95)], ("C36.1", "Y1.3")),
]
TRACKS += Q6_XTAL
# q6 eFuse input (coordinator QA A4): C4.1 -> the U1_IN_F land over pins 4 + 3 at 1.0 mm (was 1.0 + two 0.25 necks)
# The land is tracks, not a zone: a +5V_IN fill at U1 made qa_copper_landing see the trunk on both sides of the eFuse
# branch (budget 5.5 A instead of DECISIONS #4's 2.5 A). Widths: 0.7 mm into pin 4 (0.15 mm from the EP at x 84.45),
# 0.44 mm pin 4 -> pin 3 (its round end 0.15 mm from pin 2): the widest tracks the pin row allows (was 0.25 / 0.25)
Q6_EFUSE_IN = [("+5V_IN", 1.0, F, [(84.95, 14.6), (84.95, 16.1)], ("C4.1", None)),
               ("+5V_IN", 0.7, F, [(84.95, 16.1), (84.95, 16.75)], (None, "U1.4")),
               ("+5V_IN", 0.44, F, [(84.95, 16.75), (84.95, 17.25)], ("U1.4", "U1.3"))]
TRACKS += Q6_EFUSE_IN
# J10 (HRO D-15) GND pins A1 / A12 / B1 / B12 overlap the shell slot pads (same net, as the HRO layout draws it); a
# pad-centre stub each so the GND joint is explicit copper (qa_copper_landing POUR-PAD), q6 2026-10-27
Q6_J10 = [("GND", 0.3, F, [(105.0, 59.635), (103.7325, 59.535)], ("J10.A1", "J10.SH")),
          ("GND", 0.3, F, [(112.0, 59.635), (112.725, 59.57)], ("J10.A12", "J10.SH")),
          ("GND", 0.3, F, [(105.0, 62.365), (104.275, 62.43)], ("J10.B12", "J10.SH")),
          ("GND", 0.3, F, [(112.0, 62.365), (113.2675, 62.465)], ("J10.B1", "J10.SH"))]
TRACKS += Q6_J10
# TLV62569 switch node (q6, coordinator QA A7 / power review M8: 0.2 mm, 3.3 mm, looping): one 0.6 mm land U2.3 -> L1.1
# (0.22 mm from the GND pin 2 pad). The input loop stays C10 -> In1 -> the U2.2 drop: the DBV pinout puts VIN (pin 4)
# and GND (pin 2) on opposite sides and the 0.94 mm gap between the pin rows holds one via
Q6_U2 = [("SW_3V3", 0.6, F, [(77.1375, 24.05), (78.9, 24.4)], ("U2.3", "L1.1"))]
TRACKS += Q6_U2
# display USB D+ ESD in line (q6, coordinator QA B6 / logic review L-05: U12.3 / .4 hung on a 7 mm branch off a T on
# the J9 -> R75 run). J9's pin order (D+ left of D-) and the USBLC6 pairs (D- top row 1 / 6, D+ bottom row 3 / 4) put
# the in-line D- lane (U12.1 -> down at x 59.38) between J9.3 and U12.3, so D+ crosses it once on B.Cu below the
# trunk dip (y 12.2): J9.3 -> F down x 58.825 (0.155 mm between RUN and the D- lane) -> via -> B -> via -> up into U12.3; U12.3 -> U12.4 below the body
# (y 11.2, clear of the U12.2 GND drop); pfr2 routes R75 onto that bridge
Q6_USB = [("USBH_DP_C", 0.2, F, [(61.43, 4.15), (61.43, 5.175), (58.825, 7.78), (58.825, 12.2)], ("J9.3", None)),
          ("USBH_DP_C", 0.2, B, [(58.825, 12.2), (60.36, 12.2)], (None, None)),
          ("USBH_DP_C", 0.2, F, [(60.36, 12.2), (60.36, 10.45)], (None, "U12.3")),
          ("USBH_DP_C", 0.2, F, [(60.36, 11.2), (62.64, 11.2), (62.64, 10.45)], (None, "U12.4"))]
TRACKS += Q6_USB
Q6_USB_VIAS = [("USBH_DP_C", 58.825, 12.2, 0.6, 0.3), ("USBH_DP_C", 60.36, 12.2, 0.6, 0.3)]
VIAS += Q6_USB_VIAS
VIAS.append(("PWR_FAULT_N", 80.9, 17.45, 0.6, 0.3))


def pad(board, spec):
    ref, num = spec.split(".")
    fp = board.FindFootprintByReference(ref)
    if fp is None:
        sys.exit(f"power_copper: {ref} missing")
    return next(p for p in fp.Pads() if p.GetNumber() == num)


def main():
    board = pcbnew.LoadBoard(str(BOARD))
    drop_xy = {(round(d[1][0], 3), round(d[1][1], 3)) for d in GND_DROPS}
    drop_xy |= {(round(x, 3), round(y, 3)) for n, x, y, *_ in VIAS if n == "GND"}       # own GND vias / track ends
    drop_xy |= {(round(x, 3), round(y, 3)) for n, _, _, pts, _ in TRACKS if n == "GND" for x, y in pts[-1:]}

    def own_drop(t):                                        # this script's GND drop via / stub (by position)
        return t.GetNetname() == "GND" and (
            (round(pcbnew.ToMM(t.GetPosition().x), 3), round(pcbnew.ToMM(t.GetPosition().y), 3)) in drop_xy
            or (round(pcbnew.ToMM(t.GetEnd().x), 3), round(pcbnew.ToMM(t.GetEnd().y), 3)) in drop_xy)
    old_zones = [z for z in board.Zones() if z.GetZoneName() in {n for n, *_ in ZONES}]   # before any Remove (a Remove
    # invalidates the SWIG zone list on a routed board: q5 2026-10-27)
    for t in list(board.GetTracks()):                       # idempotent: drop a previous run's items (ONE pass:
        if t.IsLocked() and (t.GetNetname() in {n for n, *_ in TRACKS} - {"GND"} | {"+5V_IN"} or own_drop(t)):  # 2nd
            t.SetLocked(False)                              # GetTracks after Remove breaks the SWIG list)
            board.Remove(t)
    for z in old_zones:
        board.Remove(z)
    nets = board.GetNetsByName()
    for name, net, layer, prio, pts in ZONES:
        z = pcbnew.ZONE(board)
        z.SetZoneName(name)
        z.SetLayer(layer)
        z.SetNetCode(nets[net].GetNetCode())
        z.SetAssignedPriority(prio)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetMinThickness(mm(0.25))
        z.SetLocalClearance(mm(0.3))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x), mm(y))
        z.SetLocked(True)
        board.Add(z)
    vias, tracks = VIAS, TRACKS
    for net, x, y, d, dr in vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(d))
        v.SetDrill(mm(dr))
        v.SetNetCode(nets[net].GetNetCode())
        v.SetLocked(True)
        board.Add(v)
    for net, w, layer, pts, (a, b) in tracks:
        for spec, xy in ((a, pts[0]), (b, pts[-1])):        # each end must land in its pad, on the net
            if spec is None:
                continue
            p = pad(board, spec)
            if p.GetNetname() != net or not p.HitTest(pcbnew.VECTOR2I(mm(xy[0]), mm(xy[1]))):
                sys.exit(f"power_copper: {net} end {xy} does not land in {spec} ({p.GetNetname()})")
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
            t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
            t.SetWidth(mm(w))
            t.SetLayer(layer)
            t.SetNetCode(nets[net].GetNetCode())
            t.SetLocked(True)
            board.Add(t)
    for spec, (x, y), *w in GND_DROPS:
        p = pad(board, spec)
        if p.GetNetname() != "GND":
            sys.exit(f"power_copper: GND drop {spec} is {p.GetNetname()}")
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetWidth(mm(0.6))
        v.SetDrill(mm(0.3))
        v.SetNetCode(nets["GND"].GetNetCode())
        v.SetLocked(True)
        board.Add(v)
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(p.GetPosition())
        t.SetEnd(pcbnew.VECTOR2I(mm(x), mm(y)))
        t.SetWidth(mm(w[0] if w else 0.3))
        t.SetLayer(F)
        t.SetNetCode(nets["GND"].GetNetCode())
        t.SetLocked(True)
        board.Add(t)
    for spec in SOLID_PADS:                                 # solid zone connection (no thermal spokes)
        pad(board, spec).SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    for spec, (w, ang) in THERMAL_PADS.items():             # q6: thermal reliefs with wide spokes
        pd = pad(board, spec)
        pd.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        pd.SetLocalThermalSpokeWidthOverride(mm(w))
        pd.SetThermalSpokeAngleDegrees(ang)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(BOARD), board)                     # SaveBoard keeps the project's net classes
    print(f"power_copper: {len(ZONES)} zones, {len(vias)} vias, "
          f"{sum(len(p) - 1 for _, _, _, p, _ in tracks)} track segments (locked) -> {BOARD.name}")


if __name__ == "__main__":
    main()
