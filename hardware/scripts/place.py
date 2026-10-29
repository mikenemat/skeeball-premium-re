"""SBC-1 placement (KiCad python, run AFTER pcb_build.py):
    "C:/Program Files/KiCad/10.0/bin/python.exe" place.py
Loads hardware/main/skeeball-controller.kicad_pcb (outline + holes from pcb_build.py), adds every design.py part's
footprint with its nets (= the netlist import), places it from POS below, saves, then runs KiCad DRC (kicad-cli) and
prints the courtyard / edge / hole findings (unrouted nets are expected at this stage).

Placement rules (owner 2026-10-26): harness headers on the owner's scanned pad centres (layout_const.PADS, +-0.2 mm);
SMD parts on the TOP side only; THT through. Coordinates: mm, origin = board top-left, y down; rot = KiCad degrees
(counter-clockwise as seen from the top). Groups follow docs/PLACEMENT_PLAN.md.
"""
import json
import subprocess
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from design import D  # noqa: E402
import vendor_models as VM  # noqa: E402

BOARD = ROOT / "hardware" / "main" / "skeeball-controller.kicad_pcb"
STOCK = Path(r"C:/Program Files/KiCad/10.0/share/kicad/footprints")
PROJ = ROOT / "hardware" / "lib" / "skeeball.pretty"
KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"

POS = {}


def put(ref, x, y, rot=0):
    POS[ref] = (x, y, rot)


def row(refs, x0, y0, dx, dy=0.0, rot=0):
    for k, r in enumerate(refs):
        put(r, round(x0 + k * dx, 3), round(y0 + k * dy, 3), rot)


# ---- harness headers on the scanned pads (pin 1 = footprint origin) ------------------------------------------------
# TODO-3 (2026-10-26, scan re-anchored on the owner's per-axis hole insets): each origin = least-squares translation fit
# of the footprint's nominal pad pattern to the scanned pads = mean of the scanned pads minus the mean pad offset
put("J1", 95.40, 10.39, 0)        # power Mini-Fit Jr 1x3 RA, mating face toward the top edge, pegs 7.3 up; mean(PWR) - (4.2, 0)
put("J7", 3.81, 37.79, 0)         # RGB Mini-Fit Jr 1x4 vertical, pin 1 (+5 V) left; mean(RGB) - (6.3, 0)
put("J8", 4.885, 15.12, 90)       # playfield KK 396 VERTICAL, pin 1 (+5 V) = lower pin, friction-ramp wall inboard (+x);
                                  # x = mean, y = scanned midpoint + 3.96 / 2
put("J5", 68.47, 65.24, 270)      # J11 score: plain 1x9 2.54 header like stock, pin 1 ('*', GND) at the right end;
                                  # mean(J11 9 pins) + (4 x 2.54, 0)
put("J6", 3.63, 56.36, 0)         # buttons Mini-Fit Jr 2x4: pins 1-4 (D C B START) = row y ~56.3, 5-8 (GND) = latch row
                                  # y ~61.9; mean(8 pads) - (6.3, 2.75)
put("J4", 105.45, 48.31, 270)     # speaker Mini-Fit Jr 5569-02A2: pin 1 outer, peg 7.3 mm further out; mean + (2.75, 0)
put("J9", 61.43, 2.75, 180)       # display micro-B: x = mean of the 4 J18 shell anchors (61.43); y = 'PCB Edge' line on
                                  # y = 0 (footprint, not scan), mouth ~1.2 mm past the edge (M-C7)
put("J3", 31.50, 16.375, 0)       # RJ45 vertical in zone a (owner pick)

# ---- power input + eFuse + 3.3 V buck (top right, below J1) -------------------------------------------------------
put("D1", 88.5, 9.0, 90)
# eFuse re-placed from connectivity (routing pass 2026-10-27): U1 at 180 deg puts IN (pins 4 / 3) at the top-right
# corner under C4 and the D1 feed, EN / DVDT (pins 2 / 1) on the right with R1 / R2 / C6, OUT / FLT / ILM / GND on the
# left with C9 / R3 - no lane crosses another and every DECAP row (qa_power_layout) is a straight <= 2 mm stub
put("U1", 84.0, 17.5, 180)
put("C4", 84.175, 14.6, 180)      # CIN 0.1 uF: pad 1 straight above U1.4 (power_copper neck)
put("C5", 88.7, 14.6, 0)          # +5V_IN bulk, leaf off the D1 feed
put("R1", 87.4, 17.75, 180)       # UVLO top: pad 2 (EN) in line with U1.2
put("R2", 87.4, 19.6, 0)          # UVLO bottom: pad 1 (EN) under R1.2
put("C6", 84.95, 20.4, 270)       # CdVdt under U1.1 (bottom-right pin)
put("R3", 80.9, 18.5, 180)        # RILM, pad 1 beside U1.7
put("C9", 80.9, 16.5, 180)        # OUT 0.1 uF, pad 1 beside U1.5 (pass 5: -0.25 y = a lane for FLT pin 6 at y 17.25)
put("C7", 95.5, 20.0, 0)          # 220 uF polymer, eFuse output
put("C8", 88.4, 22.7, 90)
# pass 5 (2026-10-27, DECAP rows <= 3 mm): U2 at 180 deg puts SW (pin 3) top right next to L1, VIN (pin 4) top left
# under C10, FB (pin 5) bottom left between R5 (top resistor) and R6 (bottom resistor); EN (pin 1) bottom right
put("U2", 76.0, 25.0, 180)
put("C10", 72.9, 23.4, 90)        # C1 4.7 uF: pad 1 (+5V_SYS) 1.9 mm from VIN (pin 4)
put("L1", 80.4, 24.4, 0)          # pad 1 (SW) level with pin 3
put("C11", 81.5, 28.3, 0)         # output cap under L1 pad 2
put("R5", 72.3, 26.5, 0)          # FB top: pad 2 (FB) 1.6 mm from pin 5
put("R6", 74.9, 28.35, 270)       # FB bottom: pad 1 (FB) straight under pin 5
put("C12", 72.3, 28.2, 0)         # feed-forward across R5
# VBUS switch for the display port, next to J9
put("R80", 70.8, 12.1, 0)         # U4 EN 4.7k pull-down (q5, adversarial review F08; q6 4.7k RP2350-E9), pad 1 toward EN pin 3
# q6 (2026-10-27, coordinator QA B1 / B2): PWR_FAULT_N pull-up R81 beside the U5 pin-58 escape, ETH_CS_N pull-up R82
# above-left of U5 (free courtyard spots found by .runtime/route/q6/tools/spot.py on the routed q5 board)
put("R81", 67.5, 32.5, 0)
put("R82", 50.5, 34.0, 0)
put("U4", 69.0, 9.5, 0)
put("C15", 65.4, 8.55, 180)       # IN bypass: pad 1 (+5V_SYS) 1.7 mm left of IN (pin 1) (DECAP, pass 5)
put("R7", 73.0, 9.5, 90)
put("C16", 69.0, 5.6, 180)        # q6: GND pad left, its drop via in the J9 notch (out of the +5V_IN trunk)
# display USB ESD + series resistors between J9 and the MCU USB pins
put("U12", 61.5, 9.5, 0)
# R74 / R75 27R USB source resistors at the RP2350 (RP-008279 5.1; adversarial review L1, q5 2026-10-27): above U5
# pins 66 (DM) / 67 (DP): R75 (DP) vertical between C26 and C25, pad 2 (MCU side) down; R74 (DM) horizontal above C25,
# pad 2 (MCU side) left (one 0603 courtyard fits between C26 and C25)
put("R74", 64.65, 30.9, 180)
put("R75", 62.27, 32.25, 270)

# ---- MCU RP2350B (centre) + flash + 1.1 V LDO + crystal -----------------------------------------------------------
MX, MY = 60.0, 40.0
put("U5", MX, MY, 0)
# decoupling just outside the QFN courtyard next to its power pins (0402)
# pass 3 (2026-10-27): decaps RADIAL to their pins (power pad toward the pin, GND pad outward with room for its drop via
# beyond it) and 2 mm apart, so every side keeps an escape channel between them (2-layer QFN-80 at 0.4 mm)
# q6 (coordinator QA B7, RP2350 DS 6.1.6 "4.7 uF close to the chip's VREG_VIN pin"): C31 (4.7 uF) and C25 (100 nF)
# swap places - same 0402 footprint and nets (+3V3 / GND), so the routed copper is unchanged
put("C31", 64.25, 33.38, 90)      # 4.7 uF +3V3 at VREG_AVDD / VREG_VIN (pins 61 / 64)
put("C25", 52.6, 35.8, 180)       # 100 nF +3V3, outside the left-top corner (pins 1-5 group with C18)
put("C18", 52.6, 37.8, 180)       # pin 5
put("C28", 52.6, 39.8, 180)       # pin 10 +1V1
put("C19", 52.6, 41.8, 180)       # pin 15
put("C20", 57.4, 46.7, 270)       # pin 24
put("C21", 58.8, 46.7, 270)       # pin 29
put("C29", 61.0, 46.7, 270)       # pin 32 +1V1
put("C22", 67.4, 43.8, 0)         # pin 41
put("C23", 67.4, 41.4, 0)         # pin 50
put("C30", 67.4, 39.4, 0)         # pin 51 +1V1
put("C24", 66.62, 36.4, 0)         # pins 59 / 60
put("C26", 61.0, 32.6, 90)        # pins 68 / 69
put("C27", 57.8, 32.8, 90)        # pin 76
put("C32", 66.7, 45.75, 0)        # 4.7 uF +1V1, bottom-right corner (CAP-FAR <= 6 mm from pin 32, pass 5)
put("C33", 70.0, 35.0, 0)         # 10 uF +3V3 bulk
put("U3", 70.5, 41.5, 0)          # TLV74311 1.1 V LDO
put("C13", 69.75, 38.25, 90)      # CIN: pad 1 (+3V3) above IN (pin 1) (DECAP, pass 5)
put("C14", 74.15, 40.6, 0)        # COUT: pad 1 (+1V1) right of OUT (pin 5)
put("U6", 55.5, 27.0, 90)         # W25Q128 above-left (QSPI pins 70-75 on the MCU's top side)
put("C34", 51.58, 23.4, 180)
put("R12", 51.5, 29.0, 90)        # BOOTSEL 1k on QSPI_SS, at the flash (button stub isolated by 1k)
put("Y1", 60.65, 49.85, 270)      # 12 MHz: XIN pad 1 straight under pin 30 (q5 placement wave, 2026-10-27)
put("C35", 57.3, 48.75, 180)     # XIN load: pad 1 beside Y1 pad 1
put("C36", 63.4, 51.0, 270)      # XOUT_X load beside Y1 pad 3
# q6 (coordinator QA B5, logic review L-02): R14 horizontal in the lane between C29 / Y1 pad 4, right of the Y1 courtyard;
# XOUT = locked F.Cu stub, no via (power_copper.Q6_XTAL): down the 0.6 mm lane between XIN and C29, under C29, to R14.1;
# XOUT_X straight down to C36.1 / Y1.3. R14 cannot sit against pin 31: XIN (pin 30) and C29 (DVDD pin 32) flank it
put("R14", 63.45, 47.755, 0)     # 1k XOUT series (courtyard clear of the Y1 courtyard at x 62.445)
# +5V_SYS monitor divider (ADC0 = pin 49, right side)
row(["R8", "R9", "C17"], 73.5, 35.5, 0, 1.75)
# I2S series resistors at the MCU (source end)
row(["R41", "R40", "R39"], 70.4, 46.9, 0, 1.6)     # pass 5: +0.8 x = a lane; DIN / LRCLK / BCLK top -> bottom = the
                                                    # eastward order of U5 pins 40 / 39 / 38 (GPIO32 / 31 / 30, DECISIONS #8)

# ---- Ethernet: W5500 below the jack (MDI pins up), terminations between them --------------------------------------
put("U7", 39.5, 40.0, 270)
# series 0R + RX coupling under the jack; pass 5: R27 / R28 mirrored about the J3 TX pair axis (x 36.9 = between J3
# pins 1 / 2, qa_placement DIFFPAIR-PLACE), straight under their pins
row(["R27", "R28", "R29", "R30", "C52", "C53"], 37.75, 29.1, -1.7, 0, 90)
# top side (pass 5): 0.5 mm closer to the pins (courtyards 0.07 clear of U7) and R22 straight over EXRES (pin 10): in
# p8 / p9 the pin-9 GND drop via took the 0.6 mm lane between pin 10 and R22.1 and ETH_EXRES stayed open; now the
# R22.1 - pin 10 gap (0.6 mm) holds the EXRES stub only
put("C37", 41.0, 33.2, 90)        # pin 4
put("C41", 39.35, 33.2, 90)       # pin 8
put("R22", 37.75, 33.2, 90)       # EXRES 12.4k, pad 1 over pin 10
put("C42", 35.9, 33.2, 90)        # pin 11
# left side (pass 5, DECAP <= 3 mm + a GND drop-via spot outside the pin field): one column hugging the courtyard,
# supply pad inboard (180 deg), GND pad outboard with its via spot at x ~30.9; top -> bottom in pin order
# C39 pin 15, C40 pin 17, C46 TOCAP pin 20, C38 pin 21, C47 1V2 pin 22
put("C39", 32.7, 36.61, 180)
put("C40", 32.7, 38.18, 180)
put("C46", 32.5, 40.0, 180)       # TOCAP 4.7 uF (0805)
put("C38", 32.7, 41.82, 180)
put("C47", 32.7, 43.39, 180)      # 1V2 10 nF
put("C43", 31.8, 45.9, 0)         # 3V3A 10 uF
# crystal group (pass 5): R25 (0R, XO -> XO_X) straight between U7 pin 31 and Y2 pin 3, Y2 / C48 / C49 2 mm lower, the
# 1M R26 under Y2 - the U7 bottom-right corner (SPI pins 32-36 toward U5) is left clear (p8: ETH_MOSI / ETH_INT_N open)
put("C45", 37.4, 46.2, 180)       # pin 28 (digital 3V3): pad 1 under the pin
put("R25", 39.8, 47.3, 270)
put("Y2", 39.0, 51.0, 0)
put("C48", 35.3, 51.0, 180)        # XI cap: pad 1 toward Y2 pin 1, clear of C68
put("C49", 42.6, 51.0, 90)
put("R26", 39.0, 54.0, 0)
# W5500 SPI / RSTn now on U5's top-left pins (GPIO4-9, DECISIONS #8): MISO 33R + RSTn pull-up beside them, the 3V3A
# filter below
put("R24", 48.6, 36.0, 0)         # MISO 33R
put("R23", 48.6, 37.8, 0)         # RSTn pull-up
put("FB1", 49.0, 41.6, 0)
put("C44", 49.0, 44.1, 0)
# TX bias R31 (MDI_TXP) / R32 (MDI_TXN): pass 5 mirrored about the J3 TX pair axis (x 36.9) at the ends of the MDI row
# (DIFFPAIR-PLACE: mirror <= 1.5 mm, equal pin distance); the RX pins 3 / 4 sit next to the TX pins, so the only mirror
# pair of spots clear of the RX lines is outside the row (x 36.9 -/+ 9.35)
put("R31", 46.25, 29.1, 90)
put("R32", 27.55, 29.1, 90)
put("R33", 49.8, 20.0, 0)                                                   # TCT bias (right of the jack)
row(["C50", "R34", "R35"], 43.0, 21.8, 3.4)
put("C51", 43.0, 23.6, 0)
put("R37", 43.0, 9.0, 0)          # LINK LED (jack pin 11)
put("R36", 43.0, 11.0, 0)         # ACT LED (jack pin 13)

# ---- lights: PTCs + bulk top-left, FETs right of the RGB header ------------------------------------------------------
# Power flows top -> down without crossings (2026-10-27 re-place from connectivity): +5V_IN arrives from the top-edge
# trunk to both PTC inputs (pads facing up); F2 -> +5V_PF straight left to J8.1; F1 -> +5V_RGB down to C2 / C1 / J7.1;
# the playfield FET Q4 sits beside J8.2 (its drain is J8.2's only neighbour), Q1-Q3 beside J7 in R / G / B order.
put("F1", 19.8, 13.0, 270)        # 5 A PTC, RGB common: pad 1 (+5V_IN) up, pad 2 (+5V_RGB) down
put("F2", 13.0, 13.5, 270)        # 3 A PTC, playfield common: pad 1 (+5V_IN) up, pad 2 (+5V_PF) down
put("C3", 11.9, 18.6, 0)          # +5V_PF 10 uF, under F2 (pass 5: 0.7 left, GND pad clear of the 2.5 mm +5V_RGB run;
                                  # TODO-3: +0.2 y, clear of the re-registered J8 courtyard)
put("C2", 19.0, 19.0, 0)          # +5V_RGB 10 uF, under F1
put("C1", 14.5, 24.5, 0)          # 220 uF on +5V_RGB
put("Q4", 9.6, 6.9, 180)          # playfield FET: drain toward J8.2 (LED_PF_K); TODO-3: -0.3 y, clear of J8's courtyard
put("R72", 11.4, 4.35, 0)          # gate 100R (TODO-3: -0.3 y with Q4)
put("R73", 14.6, 4.65, 0)         # gate pull-down 10k
for k, (q, rg, rp) in enumerate((("Q1", "R66", "R67"), ("Q2", "R68", "R69"), ("Q3", "R70", "R71"))):
    y = 32.5 + 4.0 * k
    put(q, 22.5, y, 180)           # drain (pin 3) faces J7, gate / source face the gate resistors
    put(rg, 26.5, y, 90)
    put(rp, 28.5, y, 90)

# ---- score inputs: ESD at J11, RC grid between the MCU and J11 ---------------------------------------------------------
put("U9", 61.0, 59.5, 0)
put("U10", 52.0, 59.5, 0)
SC = ["SC_100B", "SC_100A", "SC_50", "SC_40", "SC_30", "SC_20", "SC_10", "SC_GUTTER"]   # left -> right (J11 pins 9 -> 2)
by_net = {}
for p in D.parts.values():
    if p.block == "scores" and p.ref.startswith(("R", "C")):
        by_net.setdefault(p.conns.get("2") if p.value == "4.7k" else p.conns.get("1"), []).append(p.ref)
for k, s in enumerate(SC):
    pu = next(p.ref for p in D.parts.values() if p.block == "scores" and p.value == "2.2k" and p.conns["1"] == s + "_J")
    se = next(p.ref for p in D.parts.values() if p.block == "scores" and p.value == "4.7k" and p.conns["2"] == s)
    cf = next(p.ref for p in D.parts.values() if p.block == "scores" and p.value == "1nF" and p.conns["1"] == s)
    x = 47.0 + 3.2 * k
    # pass 5: grid 1.2 mm lower (bottom courtyard 57.68 vs U9 / U10 57.76) = a wider escape band under U5 / Y1
    put(cf, x, 53.5, 0)
    put(se, x, 55.2, 0)
    put(pu, x, 56.9, 0)

# ---- buttons: ESD + RC beside the header ----------------------------------------------------------------------------
put("U11", 23.5, 57.5, 0)
for k, b in enumerate(["BTN_START", "BTN_B", "BTN_C", "BTN_D"]):
    pu = next(p.ref for p in D.parts.values() if p.block == "buttons" and p.value == "2.2k" and p.conns["1"] == b + "_J")
    se = next(p.ref for p in D.parts.values() if p.block == "buttons" and p.value == "4.7k" and p.conns["2"] == b)
    cf = next(p.ref for p in D.parts.values() if p.block == "buttons" and p.value == "1nF" and p.conns["1"] == b)
    y = 53.0 + 1.7 * k
    put(pu, 28.5, y, 0)
    put(se, 31.7, y, 0)
    put(cf, 34.9, y, 0)

# ---- audio: MAX98357A next to the speaker header -----------------------------------------------------------------------
put("U8", 90.5, 48.5, 0)
put("C55", 91.15, 52.15, 270)     # VDD 0.1 uF: pad 1 under VDD pins 7 / 8 (DECAP, pass 5)
put("C54", 89.3, 52.6, 270)       # VDD 10 uF beside it
put("R38", 90.5, 44.6, 0)
put("FB2", 94.6, 46.8, 0)
put("FB3", 94.6, 50.2, 0)
put("C58", 94.6, 44.6, 0)
put("C59", 94.6, 52.4, 0)
put("C56", 90.5, 58.0, 0)         # 220 uF reservoirs at the amp
put("C57", 79.5, 49.0, 0)

# ---- score jacks across the bottom edge: the stock positions (post midpoints from the owner's scan) -----------------
# (TODO-3: x = midpoint of each scanned post pair, y = mean of the 16 scanned post centres; pads.json modular_jack_holes_y80)
JACK_X = [16.31, 28.31, 40.27, 52.33, 64.36, 76.43, 88.44, 100.49]   # labels 0 10 20 30 40 50 100 100
JACK_Y = 80.63
for k, x in enumerate(JACK_X):
    put(f"J{21 + k}", x, JACK_Y, 0)

# ---- lane DIP + pull-ups (right centre), status LEDs (column by the power section, visible from above) ------------
put("SW3", 82.5, 37.0, 0)
row(["R18", "R19", "R20", "R21"], 90.5, 33.5, 0, 2.0)
for k, (d, r) in enumerate((("D3", "R10"), ("D5", "R17"), ("D2", "R4"), ("D4", "R11"))):
    put(d, 104.0, 27.0 + 3.5 * k, 0)
    put(r, 107.2, 27.0 + 3.5 * k, 0)

# ---- RESET / BOOT, debug USB-C + CH340N (bottom-right pocket above the jacks), SWD (bottom left) -------------------
# RESET / BOOT on the top edge between J3 (courtyard x <= 40.15) and J9 (x >= 56.87) (owner 2026-10-27); TS-1187A
# courtyards ~6.5 mm, >= 0.5 mm from the edge; R13 (RUN to GND, Figure 16 R4) moves with RESET
put("SW1", 44.6, 4.2, 0)          # BOOTSEL
put("SW2", 52.4, 4.2, 0)          # RUN (reset)
put("R13", 56.2, 9.2, 90)        # beside RESET, its label spot below stays free
# CH340N at 180 deg (pass 5): USB D+ / D- (pins 1 / 2) face U13 / J10, VCC / V3 / TXD / RXD (pins 8 / 5 / 6 / 7) face
# left where C72 / C73 sit 2 mm from their pins and R78 / R79 lead the UART toward the MCU
put("U14", 91.5, 65.0, 180)
put("C73", 86.2, 63.1, 180)       # V3 (pin 5)
put("C72", 86.2, 66.9, 180)       # VCC (pin 8)
put("J10", 108.5, 61.0, 0)        # debug USB-C HRO D-15 (vertical, 12 x 5 flange; q6 +1.0 mm x clears U13): plug check below
put("U13", 99.6, 61.0, 0)         # USB ESD beside the receptacle
# q6 (D-15 pin map): CC1 / CC2 5.1k on their pins' axes (qa_layout_quality PLACE-PINPASSIVE proposal): R76 above A5,
# R77 below B5, pad 1 toward the pin
put("R76", 107.0, 56.115, 90)
put("R77", 110.0, 65.885, 270)
put("R78", 83.0, 64.4, 180)       # UART series resistors at the CH340N (TXD pin 6 / RXD pin 7 side)
put("R79", 83.0, 66.0, 0)
# SWD (owner 2026-10-26 fix B): J2 + its series resistors at the lower right, east of the score header, so SWCLK /
# SWDIO (U5 pins 33 / 34) leave the bottom row eastward with the UART / I2S group instead of crossing it westward
put("J2", 76.5, 62.5, 0)          # SWD, JST SH vertical, plug from above
put("R15", 76.5, 56.3, 0)         # SWCLK 100R
put("R16", 76.5, 58.0, 0)         # SWDIO 100R
put("F3", 40.0, 65.5, 0)          # TODO-1 score-jack PTC (+5V_SYS -> +5V_JACK), above the jack strip

W_BOARD, H_BOARD, EDGE_GAP = 116.68, 85.73, 0.4
# function labels on the silk for the parts a user looks for (the reference stays on F.Fab)
FUNC_LABEL = {"D3": "PWR", "D5": "STAT", "D2": "FAULT", "D4": "VBUS", "SW1": "BOOT", "SW2": "RESET", "SW3": "LANE ID",
              "J10": "DEBUG", "J2": "SWD"}
FUNC_LABEL.update({f"J{21 + k}": f"J{21 + k} {lab}" for k, lab in enumerate(["0", "10", "20", "30", "40", "50", "100", "100"])})
# connector ID + purpose (owner 2026-10-26: silk priority = connector purpose names, IDs, human-readable pin maps)
FUNC_LABEL.update({"J1": "J1 5V IN", "J7": "J7 RGB", "J8": "J8 PLAYFIELD", "J5": "J5 SCORES", "J6": "J6 BUTTONS",
                   "J4": "J4 SPEAKER", "J9": "J9 DISPLAY", "J3": "J3 ETHERNET", "J10": "J10 DEBUG", "J2": "J2 SWD"})
# pin labels: ref -> {pad: (text, dx, dy)} offsets from the pad centre, board frame (mm)
PIN_LABELS = {
    "J1": {"1": ("5V", 0, 2.9), "2": ("NC", 0, 2.9), "3": ("GND", 0, 2.9)},
    "J7": {"1": ("5V", 0, 7.0), "2": ("R", 0, 7.0), "3": ("G", 0, 7.0), "4": ("B", 0, 7.0)},
    "J8": {"1": ("5V", -0.3, 3.15), "2": ("LED", -0.3, -2.65)},             # below / above the vertical KK 396 housing
    "J5": {"1": ("* GND", 0, -2.3), "9": ("IN", 0, -2.3)},                   # just above the plain header; "*" =
                                                                             # pin 1 like the stock silk (q6, M-11)
    "J6": {"4": ("START", 0, -5.3), "3": ("B", 0, -5.3), "2": ("C", 0, -5.3), "1": ("D", 0, -5.3), "8": ("GND", 5.2, 0)},
    "J4": {"1": ("SPK+", 0, 4.1), "2": ("SPK-", 0, 4.1)},   # below the J4 courtyard (triage #8, 2026-10-27)
}
JACK_LABEL_Y = 69.0                          # jack numbers in the strip above the jacks, as on the stock board


def trim_edge_silk(board):
    """Edge connectors (power, speaker, playfield, display USB) overhang the outline like the stock parts: drop their
    silk outline segments that leave the board (the fab would clip them anyway)."""
    mm = pcbnew.ToMM
    for fp in board.GetFootprints():
        for it in list(fp.GraphicalItems()):
            if it.GetLayer() != pcbnew.F_SilkS or not isinstance(it, pcbnew.PCB_SHAPE):
                continue
            bb = it.GetBoundingBox()
            if (mm(bb.GetX()) < EDGE_GAP or mm(bb.GetY()) < EDGE_GAP or mm(bb.GetRight()) > W_BOARD - EDGE_GAP
                    or mm(bb.GetBottom()) > H_BOARD - EDGE_GAP):
                fp.Remove(it)


def silk_labels(board):
    """Reference text on F.SilkS only where it is readable: outside every courtyard (a label under a part body is
    invisible after assembly, a label on copper is clipped by the fab), inside the board, and clear of the other labels.
    Tries 8 spots around the part at 1.0 mm (connectors / ICs) or 0.8 mm (small parts); otherwise the silk label is
    hidden and the F.Fab ${REFERENCE} keeps the part identifiable (assembly drawing)."""
    mm, MM = pcbnew.FromMM, pcbnew.ToMM
    courts = []
    for fp in board.GetFootprints():
        cy = fp.GetCourtyard(pcbnew.F_CrtYd)
        bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
        courts.append((fp.GetReference(), MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom())))
    placed, hidden = [], []

    def free(box, own):
        x0, y0, x1, y1 = box
        if x0 < EDGE_GAP or y0 < EDGE_GAP or x1 > W_BOARD - EDGE_GAP or y1 > H_BOARD - EDGE_GAP:
            return False
        for ref, a0, b0, a1, b1 in courts:
            if a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
                return False
        return all(not (a0 < x1 + 0.2 and x0 < a1 + 0.2 and b0 < y1 + 0.2 and y0 < b1 + 0.2)
                   for a0, b0, a1, b1 in placed)

    for ref, pins in PIN_LABELS.items():                                   # pin labels go first, fixed spots
        fp = board.FindFootprintByReference(ref)
        for pad in fp.Pads():
            if pad.GetNumber() not in pins:
                continue
            txt, dx, dy = pins[pad.GetNumber()]
            t = pcbnew.PCB_TEXT(board)
            t.SetText(txt)
            t.SetLayer(pcbnew.F_SilkS)
            t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
            t.SetTextThickness(mm(0.15))
            p = pad.GetPosition()
            t.SetPosition(pcbnew.VECTOR2I(p.x + mm(dx), p.y + mm(dy)))
            board.Add(t)
            bb = t.GetBoundingBox()
            placed.append((MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom())))
    fp = board.FindFootprintByReference("J8")                            # playfield header: label below it,
    fp.Reference().SetVisible(False)                                      # left-aligned at the edge
    t = fp.Value()
    t.SetText(FUNC_LABEL["J8"])
    t.SetLayer(pcbnew.F_SilkS)
    t.SetVisible(True)
    t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
    t.SetTextThickness(mm(0.15))
    t.SetTextAngleDegrees(0)
    t.SetPosition(pcbnew.VECTOR2I(0, mm(19.75)))
    bb = t.GetBoundingBox()
    t.SetPosition(pcbnew.VECTOR2I(mm(0.7) + bb.GetWidth() // 2, mm(19.75)))
    bb = t.GetBoundingBox()
    placed.append((MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom())))
    for k in range(8):
        fp = board.FindFootprintByReference(f"J{21 + k}")
        fp.Reference().SetVisible(False)
        t = fp.Value()
        t.SetText(FUNC_LABEL[fp.GetReference()])
        t.SetLayer(pcbnew.F_SilkS)
        t.SetVisible(True)
        t.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        t.SetTextThickness(mm(0.15))
        t.SetTextAngleDegrees(0)
        t.SetPosition(pcbnew.VECTOR2I(fp.GetPosition().x, mm(JACK_LABEL_Y)))
        bb = t.GetBoundingBox()
        placed.append((MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom())))
    order = sorted((f for f in board.GetFootprints() if not f.GetReference() in [f"J{21 + k}" for k in range(8)] + ["J8"]),
                   key=lambda f: (f.GetReference() not in FUNC_LABEL, -len(f.Pads())))
    # function labels first, then connectors / ICs, then the small parts
    for fp in order:
        ref = fp.GetReference()
        own = next(c for c in courts if c[0] == ref)
        _, cx0, cy0, cx1, cy1 = own
        if ref in FUNC_LABEL:
            fp.Reference().SetVisible(False)
            t = fp.Value()
            t.SetText(FUNC_LABEL[ref])
            t.SetLayer(pcbnew.F_SilkS)
            t.SetVisible(True)
            sizes = (0.8,)
        else:
            t = fp.Reference()
            sizes = (1.0, 0.8) if (len(fp.Pads()) > 8 or ref.startswith(("J", "SW", "H"))) else (0.8,)
        ok = False
        for h in sizes:
            t.SetTextSize(pcbnew.VECTOR2I(mm(h), mm(h)))
            t.SetTextThickness(mm(max(0.15, round(0.15 * h, 2))))
            mx, my = (cx0 + cx1) / 2, (cy0 + cy1) / 2
            sides = ["top", "bottom"]
            if ref.startswith("D"):
                sides.reverse()                                                 # labels below the LED first
            sides += ["left90", "right90", "left", "right"]
            for side in sides:
                t.SetTextAngleDegrees(90 if side.endswith("90") else 0)
                t.SetPosition(pcbnew.VECTOR2I(mm(mx), mm(my)))
                bb = t.GetBoundingBox()                                         # real text box (incl. KiCad margins)
                bx0, by0, bx1, by1 = MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom())
                dx = dy = 0.0
                if side == "top":
                    dy = (cy0 - 0.15) - by1
                elif side == "bottom":
                    dy = (cy1 + 0.15) - by0
                elif side.startswith("left"):
                    dx = (cx0 - 0.15) - bx1
                else:
                    dx = (cx1 + 0.15) - bx0
                t.SetPosition(pcbnew.VECTOR2I(mm(mx + dx), mm(my + dy)))
                box = (bx0 + dx, by0 + dy, bx1 + dx, by1 + dy)
                if free(box, own):
                    placed.append(box)
                    ok = True
                    break
            if ok:
                break
        if not ok:
            t.SetVisible(False)
            hidden.append(ref)
    return hidden


# ---------------------------------------------------------------------------------------------------------------------
# 3D models this KiCad install lacks, mapped to a local model of the SAME package body (stand-ins, named here)
MODEL_SUB = {
    "Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm": "Package_SON.3dshapes/WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm.step",
    "TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm": "Package_DFN_QFN.3dshapes/TQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm.step",
    "Fuse_1812_4532Metric": "Resistor_SMD.3dshapes/R_1812_4532Metric.step",
}


# near all four corners (pass 5: the three-corner triangle left U7 / U1 / J9 outside its hull, FIDUCIAL-SPREAD)
FIDUCIALS = {"FID1": (112.6, 9.0), "FID2": (3.5, 67.0), "FID3": (114.3, 72.0), "FID4": (8.0, 1.5)}


def add_fiducials(board):
    for ref, (x, y) in FIDUCIALS.items():
        fp = pcbnew.FootprintLoad(str(STOCK / "Fiducial.pretty"), "Fiducial_1mm_Mask2mm")
        fp.SetReference(ref)
        fp.SetValue("Fiducial")
        fp.Value().SetVisible(False)
        fp.Reference().SetVisible(False)
        fp.SetBoardOnly(True)
        fp.SetExcludedFromBOM(True)
        fp.SetExcludedFromPosFiles(True)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        board.Add(fp)


# debug USB-C plug envelope (owner 2026-10-27): USB-IF max overmold 12.35 x 6.5 mm centred on the receptacle, rising above
# its top (HRO D-15: 8.8 mm, q6 2026-10-27; D-06 was 6.4); parts taller keep >= J10_PLUG_GAP_MM horizontally, edge >= 0.5 mm
J10_PLUG_WH = (12.35, 6.5)
J10_PLUG_GAP_MM = 5.0
J10_PLUG_EDGE_MM = 0.5
J10_TALL_REFS = tuple(f"J{n}" for n in range(21, 29)) + ("C56", "C57", "J4")   # > 6.4 mm tall near J10 (lead list)


def check_j10_plug(board):
    MM = pcbnew.ToMM
    x, y = POS["J10"][:2]
    w, h = J10_PLUG_WH
    ex0, ey0, ex1, ey1 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
    bad = []
    if ex0 < J10_PLUG_EDGE_MM or ex1 > W_BOARD - J10_PLUG_EDGE_MM or ey0 < J10_PLUG_EDGE_MM or ey1 > H_BOARD - J10_PLUG_EDGE_MM:
        bad.append("board edge")
    for fp in board.GetFootprints():
        if fp.GetReference() not in J10_TALL_REFS:
            continue
        cy = fp.GetCourtyard(pcbnew.F_CrtYd)
        bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
        dx = max(MM(bb.GetX()) - ex1, ex0 - MM(bb.GetRight()), 0.0)
        dy = max(MM(bb.GetY()) - ey1, ey0 - MM(bb.GetBottom()), 0.0)
        d = (dx * dx + dy * dy) ** 0.5
        if d < J10_PLUG_GAP_MM:
            bad.append(f"{fp.GetReference()} {d:.2f} mm")
    if bad:
        sys.exit(f"J10 plug envelope: < {J10_PLUG_GAP_MM} mm clearance / edge: {bad}")


SCH = ROOT / "hardware" / "main" / "skeeball-controller.kicad_sch"


def kicad_nc_nets():
    """(ref, pad) -> KiCad's own net name for every no-connect pin, e.g. 'unconnected-(U3-NC-Pad4)' (pass 5,
    2026-10-27). A no-net pad is a schematic-parity net_conflict (57 of them in p7) AND a different clearance class in
    pfr2 vs plan_check (no-net copper needs 0.2 in plan_check, 0.15 in pfr2's grid): the routed candidates lost ~12
    planned joins per stage in run_stage legalisation, every one beside a no-net pad. Names come from the netlist
    kicad-cli exports from the generated schematic, so they always match the parity check."""
    import re
    import tempfile
    out = Path(tempfile.gettempdir()) / "sbc1_place_netlist.net"
    r = subprocess.run([KCLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode or not out.exists():
        sys.exit(f"netlist export failed: {r.stderr[-500:]}")
    s = out.read_text(encoding="utf-8")
    nc = {}
    for m in re.finditer(r'\(name "(unconnected-[^"]*)"\)(.*?)\n\t\t\)', s, re.S):
        for ref, pin in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', m.group(2)):
            nc[(ref, pin)] = m.group(1)
    return nc


def fp_path(fpid):
    lib, name = fpid.split(":", 1)
    return (str(PROJ) if lib == "skeeball" else str(STOCK / f"{lib}.pretty")), name



# EP paste windowpanes (q6 2026-10-27, coordinator QA C1 / mfg review M2): the library paste windows sat over the plain
# EP thermal vias (DECISIONS #3 / #9: unfilled). Replaced per footprint by rectangles that keep >= 0.1 mm (U1: 0.05 mm, U8: 0.06 mm)
# from every via hole (route_prep.EP_VIAS), in the footprint frame: (x0, y0, x1, y1) mm. Coverage of the EP area:
# U5 3.4 x 3.4, vias 3 x 3 at 1.0: four full-width bars between the via rows = 5.94 / 11.56 = 51 %;
# U1 0.9 x 1.6, vias at y +-0.4 (0.05 mm margin): bars y -0.75 .. -0.6, -0.2 .. 0.2, 0.6 .. 0.75 = 0.56 / 1.44 = 39 %;
# U8 1.23 x 1.23, one centre via (4 do not fit, route_prep.EP_VIAS): 4 squares 0.355 from 0.21 = 0.50 / 1.51 = 33 %
PASTE_WINDOWS = {
    "U5": [(-1.65, y0, 1.65, y1) for y0, y1 in ((-1.65, -1.25), (-0.75, -0.25), (0.25, 0.75), (1.25, 1.65))],
    "U1": [(-0.4, y0, 0.4, y1) for y0, y1 in ((-0.75, -0.6), (-0.2, 0.2), (0.6, 0.75))],
    "U8": [(sx * 0.21, sy * 0.21, sx * 0.565, sy * 0.565) for sx in (-1, 1) for sy in (-1, 1)],
}


# q6 (2026-10-27, coordinator QA D3 / mech review M-10): KK-396 1.14 mm square pin (diagonal 1.61) in the library's
# dia 1.70 drill left 0.09 mm (JLC -0.08 tolerance -> 1.62): 1.80 mm (pad 3.16 x 4.1, ring >= 0.68 mm)
PAD_DRILL = {"J8": {"1": 1.8, "2": 1.8}}

# q6 (2026-10-27, coordinator QA C4 / mfg m2 / mech M-6): JLC minimum silk line 0.15 mm everywhere; connector IDs /
# function labels / pin labels / jack numbers 1.0 mm high where the bigger text stays clear of courtyards, pads, the
# board edge and the other silk text (else they keep the owner-approved 0.8 mm)
SILK_MIN_W = 0.15
LABEL_H = 1.0


def silk_finish(board, fix_refs=()):
    """q6: silk line widths >= SILK_MIN_W; label texts to LABEL_H where free; references named in fix_refs re-spotted
    (8 spots around the courtyard, else hidden - F.Fab keeps ${REFERENCE}). Returns counts."""
    mm, MM = pcbnew.FromMM, pcbnew.ToMM
    n_w = 0
    items = list(board.GetDrawings())
    for fp in board.GetFootprints():
        items += list(fp.GraphicalItems())
    for it in items:
        if it.GetLayer() != pcbnew.F_SilkS:
            continue
        if isinstance(it, pcbnew.PCB_TEXT):
            if MM(it.GetTextThickness()) < SILK_MIN_W - 1e-6:
                it.SetTextThickness(mm(SILK_MIN_W)); n_w += 1
        elif hasattr(it, "GetWidth") and 0 < MM(it.GetWidth()) < SILK_MIN_W - 1e-6:
            it.SetWidth(mm(SILK_MIN_W)); n_w += 1
    for fp in board.GetFootprints():
        for t in (fp.Reference(), fp.Value()):
            if t.GetLayer() == pcbnew.F_SilkS and MM(t.GetTextThickness()) < SILK_MIN_W - 1e-6:
                t.SetTextThickness(mm(SILK_MIN_W)); n_w += 1
    courts, pads = [], []
    for fp in board.GetFootprints():
        cy = fp.GetCourtyard(pcbnew.F_CrtYd)
        bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
        courts.append((fp.GetReference(), MM(bb.GetX()), MM(bb.GetY()), MM(bb.GetRight()), MM(bb.GetBottom())))
        for pd in fp.Pads():
            if pd.IsOnLayer(pcbnew.F_Cu) or pd.IsOnLayer(pcbnew.F_Mask):
                b_ = pd.GetBoundingBox()
                pads.append((MM(b_.GetX()), MM(b_.GetY()), MM(b_.GetRight()), MM(b_.GetBottom())))
    texts = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() == pcbnew.F_SilkS]
    owner = {}
    for fp in board.GetFootprints():
        for t in (fp.Reference(), fp.Value()):
            if t.GetLayer() == pcbnew.F_SilkS and t.IsVisible():
                texts.append(t); owner[id(t)] = fp.GetReference()

    def box(t):
        b_ = t.GetBoundingBox()
        return MM(b_.GetX()), MM(b_.GetY()), MM(b_.GetRight()), MM(b_.GetBottom())

    def clear(t, bx, others):
        x0, y0, x1, y1 = bx
        if x0 < EDGE_GAP or y0 < EDGE_GAP or x1 > W_BOARD - EDGE_GAP or y1 > H_BOARD - EDGE_GAP:
            return False
        own = owner.get(id(t))
        for ref, a0, b0, a1, b1 in courts:
            if ref != own and a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
                return False
        if any(a0 - 0.15 < x1 and x0 < a1 + 0.15 and b0 - 0.15 < y1 and y0 < b1 + 0.15 for a0, b0, a1, b1 in pads):
            return False
        return all(not (a0 < x1 + 0.2 and x0 < a1 + 0.2 and b0 < y1 + 0.2 and y0 < b1 + 0.2) for a0, b0, a1, b1 in others)

    labels = [t for t in texts if owner.get(id(t)) is None]
    for fp in board.GetFootprints():                       # function labels live in the Value field (FUNC_LABEL)
        if fp.GetReference() in FUNC_LABEL:
            v = next((t for t in texts if owner.get(id(t)) == fp.GetReference() and t.GetText() == fp.GetValue()), None)
            if v is not None:
                labels.append(v)
    n_big = 0
    for t in labels:
        if MM(t.GetTextHeight()) >= LABEL_H - 1e-6:
            continue
        old = t.GetTextSize()
        others = [box(o) for o in texts if o is not t]
        t.SetTextSize(pcbnew.VECTOR2I(mm(LABEL_H), mm(LABEL_H)))
        if clear(t, box(t), others):
            n_big += 1
        else:
            t.SetTextSize(old)
    n_fix = n_hid = 0
    for ref in fix_refs:
        fp = board.FindFootprintByReference(ref)
        t = fp.Reference()
        own = next(c for c in courts if c[0] == ref)
        _, cx0, cy0, cx1, cy1 = own
        others = [box(o) for o in texts if o is not t]
        h = MM(t.GetTextHeight())
        ok = False
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            w = MM(t.GetBoundingBox().GetWidth())
            x = (cx0 + cx1) / 2 + dx * ((cx1 - cx0) / 2 + w / 2 + 0.2)
            y = (cy0 + cy1) / 2 + dy * ((cy1 - cy0) / 2 + h / 2 + 0.2)
            t.SetTextAngleDegrees(0)
            t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            if clear(t, box(t), others):
                ok = True
                break
        if ok:
            n_fix += 1
        else:
            t.SetVisible(False); n_hid += 1
    return {"widths_to_0.15": n_w, "labels_1.0mm": n_big, "labels_kept_0.8": len(labels) - n_big,
            "refs_respotted": n_fix, "refs_hidden": n_hid}

def rewrite_paste_windows(path):
    """text pass on a saved board (q6): in each PASTE_WINDOWS footprint, drop the paste-only pads (pad "" smd, layers
    F.Paste only) and write PASTE_WINDOWS[ref] instead (footprint frame; the pad angle = the footprint angle, as KiCad
    stores it). A text pass because a KiCad 10 Python FOOTPRINT.Remove(pad) corrupts the SWIG type table (q6 trial).
    Returns {ref: windows written}."""
    import re
    import uuid
    txt = Path(path).read_text(encoding="utf-8")

    def block_end(t, i):                                  # index after the s-expression starting at t[i] == "("
        depth = 0
        for k in range(i, len(t)):
            if t[k] == "(":
                depth += 1
            elif t[k] == ")":
                depth -= 1
                if depth == 0:
                    return k + 1
        raise ValueError("unbalanced")
    done = {}
    for ref, wins in PASTE_WINDOWS.items():
        m = re.search(r'\(property "Reference" "%s"' % re.escape(ref), txt)
        if not m:
            continue
        st = txt.rfind("\n\t(footprint ", 0, m.start()) + 1
        en = block_end(txt, st)
        fp = txt[st:en]
        ang = re.match(r'\(footprint "[^"]*"\s*\(layer "[^"]*"\)\s*\(uuid "[^"]*"\)\s*\(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)', fp)
        a = float(ang.group(1)) if ang and ang.group(1) else 0.0
        out, k = [], 0
        for mm_ in re.finditer(r'\(pad "" smd ', fp):
            e = block_end(fp, mm_.start())
            body = fp[mm_.start():e]
            if re.search(r'\(layers "F\.Paste"\)', body):
                out.append((mm_.start(), e))
        for b0, b1 in reversed(out):                      # drop the old windows (and their leading whitespace)
            while fp[b0 - 1] in " \t":
                b0 -= 1
            if fp[b0 - 1] == "\n":
                b0 -= 1
            fp = fp[:b0] + fp[b1:]
        add = ""
        for xa, ya, xb, yb in wins:
            x0, x1, y0, y1 = min(xa, xb), max(xa, xb), min(ya, yb), max(ya, yb)
            ats = f"{(x0 + x1) / 2:.4f} {(y0 + y1) / 2:.4f}" + (f" {a:g}" if a else "")
            add += (f'\n\t\t(pad "" smd roundrect\n\t\t\t(at {ats})\n\t\t\t(size {x1 - x0:.4f} {y1 - y0:.4f})\n'
                    f'\t\t\t(layers "F.Paste")\n\t\t\t(roundrect_rratio 0.1)\n\t\t\t(uuid "{uuid.uuid4()}")\n\t\t)')
        cut = fp.rfind(")")
        fp = fp[:cut].rstrip() + add + "\n\t)"
        txt = txt[:st] + fp + txt[en:]
        done[ref] = (len(out), len(wins))
    Path(path).write_text(txt, encoding="utf-8")
    return done


def main():
    board = pcbnew.LoadBoard(str(BOARD))
    for d in list(board.GetDrawings()):                    # idempotent: drop pin labels of a previous run
        if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() == pcbnew.F_SilkS:
            board.Remove(d)
    for fp in list(board.GetFootprints()):                 # idempotent: keep only the holes from pcb_build.py
        if not fp.GetReference().startswith("H"):
            board.Remove(fp)
        else:
            fp.Value().SetVisible(False)
            h = D.parts.get(fp.GetReference())
            if h is not None:                              # = the schematic symbol (parity: value + Note field)
                fp.SetValue(h.value)
                if h.note:
                    fp.SetField("Note", h.note)
                    fp.GetField("Note").SetVisible(False)
    nets = {}
    for n in sorted(D.nets()):
        if n.startswith("NC_"):                            # the schematic leaves these pins unconnected (no-connect)
            continue
        ni = pcbnew.NETINFO_ITEM(board, n)
        board.Add(ni)
        nets[n] = ni
    nc = kicad_nc_nets()                                   # no-connect pins: KiCad's own unconnected-(...) nets
    for name in sorted(set(nc.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni
    missing = [r for r in D.parts if not r.startswith("H") and r not in POS]
    if missing:
        sys.exit(f"no position for: {missing}")
    for ref, p in D.parts.items():
        if ref.startswith("H"):
            continue
        lib, name = fp_path(p.footprint)
        fp = pcbnew.FootprintLoad(lib, name)
        if fp is None:
            sys.exit(f"{ref}: cannot load {p.footprint}")
        fp.SetReference(ref)
        fp.SetValue(p.value)
        fp.Value().SetVisible(False)                       # values live in the BOM / schematic, not on the board
        fp.SetFPIDAsString(p.footprint)
        props = {"MPN": p.mpn, "Manufacturer": p.mfr}          # = gen_schematic's symbol fields (schematic parity)
        props.update({k: v for k, v in p.fields.items() if v})
        if p.note:
            props["Note"] = p.note
        for k, v in props.items():
            if v:
                fp.SetField(k, str(v))
                fp.GetField(k).SetVisible(False)                 # data only: never on the silk
        sub = MODEL_SUB.get(p.footprint.split(":", 1)[1])
        if sub:
            fp.Models().clear()
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KICAD10_3DMODEL_DIR}/" + sub
            fp.Models().push_back(m)
        vm = None if sub else VM.placement(
            p.footprint.split(":", 1)[1],
            {pd.GetNumber(): (pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)) for pd in fp.Pads()},
            all(pd.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for pd in fp.Pads() if pd.GetNumber().strip()),
            [(pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)) for pd in fp.Pads()
             if pd.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)],
            all_pads=[(pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)) for pd in fp.Pads()])
        if vm:                                             # vendor STEP (scripts/vendor_models.py), fitted on the pads
            step, off, rot, res = vm
            if res > 0.4:
                sys.exit(f"{ref}: vendor model pad fit residual {res:.2f} mm")
            fp.Models().clear()
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KIPRJMOD}/../lib/3d/vendor/" + step.name
            m.m_Offset = pcbnew.VECTOR3D(*off)
            m.m_Rotation = pcbnew.VECTOR3D(*rot)
            fp.Models().push_back(m)
        env = ROOT / "hardware" / "lib" / "3d" / (p.footprint.split(":", 1)[1] + ".wrl")
        if not sub and not vm and env.exists():            # envelope model (scripts/model_gen.py) replaces a missing one
            fp.Models().clear()
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = "${KIPRJMOD}/../lib/3d/" + env.name
            fp.Models().push_back(m)
        board.Add(fp)
        x, y, rot = POS[ref]
        fp.SetOrientationDegrees(rot)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        for num, d in PAD_DRILL.get(ref, {}).items():     # q6: drill overrides on library footprints
            for pad in fp.Pads():
                if pad.GetNumber() == num:
                    pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(d), pcbnew.FromMM(d)))
        for pad in fp.Pads():
            n = p.conns.get(pad.GetNumber())
            if n and not n.startswith("NC_"):
                pad.SetNet(nets[n])
            elif (ref, pad.GetNumber()) in nc:
                pad.SetNet(nets[nc[(ref, pad.GetNumber())]])
    add_fiducials(board)
    check_j10_plug(board)
    trim_edge_silk(board)
    hidden = silk_labels(board)
    print("silk finish (q6):", silk_finish(board))
    board.Save(str(BOARD))
    print("EP paste windows (q6):", rewrite_paste_windows(BOARD))
    print(f"placed {len(POS)} parts -> {BOARD.name}; silk labels hidden for lack of room (kept on F.Fab): "
          f"{len(hidden)}")
    rep = ROOT / ".runtime" / "drc_place.json"
    subprocess.run([KCLI, "pcb", "drc", "--format", "json", "--severity-all", "-o", str(rep), str(BOARD)],
                   capture_output=True)
    d = json.loads(rep.read_text(encoding="utf-8"))
    from collections import Counter
    c = Counter(v["type"] for v in d.get("violations", []))
    print("DRC (unrouted expected):", dict(c), "unconnected:", len(d.get("unconnected_items", [])))
    for v in d.get("violations", []):
        if v["type"] in ("courtyards_overlap", "edge_clearance", "hole_clearance", "copper_edge_clearance",
                         "malformed_courtyard", "silk_overlap", "clearance", "hole_to_hole", "shorting_items",
                         "solder_mask_bridge", "pth_inside_courtyard", "npth_inside_courtyard"):
            items = " | ".join(i["description"][:60] for i in v["items"])
            print(f"  {v['type']}: {items}")


if __name__ == "__main__":
    main()
