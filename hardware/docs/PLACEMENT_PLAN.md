# Footprint and placement plan (parametric - not routed)

Source of the numbers: `scripts/layout_const.py` (reads the photo estimate `docs/records/photo_estimate/estimate.json`;
the owner's measurements go into its `MEASURED` table and replace every estimate). Renders, rasterized and inspected:
`renders/placement/placement_plan.png`, `renders/placement/rj45_zone_study.png` (`python scripts/render_placement.py`).

## Fixed by the stock board (R-2, R-3)
**Measured (owner 2026-10-26, exact):** outline **116.68 x 85.73 mm**, square corners, 1.6 mm; the **four corner holes**
H1-H4 (3.57 mm drill) at 3.97 mm in from both edges = (3.97, 3.97), (112.71, 3.97), (112.71, 81.76), (3.97, 81.76); and
**every harness connector pad centre from the owner's 300 dpi bottom-side scan** (table below, +-0.1 mm). All of it is
drawn in `hardware/main/skeeball-controller.kicad_pcb` (`python scripts/pcb_build.py`; render
`renders/pcb/sbc1-outline.png`: outline, holes, pad circles and body boxes on User.Comments). Nothing added grows the
outline. Single-sided assembly (as stock).

## Measured connector pad centres (300 dpi bottom scan, component-side coordinates, +-0.1 mm)
Source `docs/records/scan_extract/pads.json` (`python scripts/scan_extract.py`). Origin = board top-left, x right, y
down, component side up (the scan is un-mirrored by the hole fit). Scale check: the four measured hole centres fit
the scan with 0.008 mm residual; the scan's hole spacing implies 11.88 px/mm (board y) and 11.96 px/mm (board x) vs
the scanner's declared 11.81 - i.e. +0.6 % / +1.2 %; the owner's caliper hole spacing is taken as truth.

| Connector | Pin | x (mm) | y (mm) | Notes |
|---|---|---:|---:|---|
| PWR 1x3 RA (Molex 39-30-3035) | 1 (5 V) | 95.40 | 10.71 | pitch 4.16; board-lock pegs at (95.2, 3.6) and (103.7, 3.6) |
| | 2 (NC) | 99.48 | 10.83 | |
| | 3 (GND) | 103.72 | 10.59 | |
| J18 micro-USB shell anchors | a | 58.69 | 2.15 | 4 anchors; receptacle centre x = **61.43**, mouth 1 mm past the top edge |
| | b | 64.19 | 2.17 | |
| | c | 58.92 | 5.10 | |
| | d | 63.91 | 5.06 | |
| PLAYFIELD 2-pin RA | upper (FET) | 4.95 | 11.74 | pitch **3.38 +-0.15** - family open (M-C4) |
| | lower (+5 V) | 4.98 | 15.12 | |
| RGB 1x4 vertical (Molex 39-30-1049) | 1 (+5 V) | 4.12 | 37.87 | pitch 4.09 (solder-covered: +-0.2); board-lock peg at (5.9, 32.7) |
| | 2 | 7.99 | 37.75 | |
| | 3 | 12.31 | 37.82 | |
| | 4 | 16.32 | 37.93 | |
| BUTTONS 2x4 (Molex 39281083) signal row | 1-4 | 3.71 / 7.80 / 12.00 / 16.17 | 56.1-56.3 | pitch 4.16 |
| BUTTONS GND row (latch side) | 1-4 | 3.85 / 7.90 / 12.19 / 16.44 | 61.6-61.9 | rows 5.5 mm apart |
| SPEAKER 2x1 RA (Molex 39291028) | outer | 99.88 | 48.27 | rows 5.5 mm apart; peg hole at (112.6, 48.3) |
| | inner | 105.38 | 48.23 | |
| J11 1x9 (Molex KK 254 22-23-2091) | 1 ('*', GND) | 68.57 | 64.98 | scan pitch 2.51-2.54 was ambiguous; owner calipers on the plug housing (22.88 mm) = KK 254 |
| | 2-9 | 65.62 / 63.29 / 60.86 / 58.40 / 55.84 / 53.29 / 50.69 / 48.33 | 64.9-65.2 | solder-covered: +-0.2 |
| reference: J5 / J7 (1x4, dropped) | | 3.7-16.3 | 26.0 / 48.2 | 4.17 pitch |
| reference: J19 (1x3 2.54, dropped) | | 64.35 / 66.88 / 69.47 | 49.7 | |
| reference: J2 (2x5 4.2 mm, dropped) | | 96.2-112.9 | 57.2 / 62.7 | |
| reference: modular jacks (dropped) | | 12.6 ... 104.2 | 80.25 | 8 jacks, pin pairs at y 71.3 / 74.0 |
| reference: stock inner holes (dropped) | | 29.4 / 87.2 | 4.1 | |



## Footprints
| Part | Footprint | State |
|---|---|---|
| all ICs, passives, LEDs, switches, JST SH, micro-USB, HR911105A | KiCad 10 stock libraries (names in `design.py`) | resolve (`python scripts/qa_footprints.py`) |
| Buttons 2x4 Mini-Fit Jr, speaker 2x1 right-angle Mini-Fit Jr | KiCad `Connector_Molex` 5566-08A / 5569-02A1 | resolved (owner photos 2026-10-26) |
| J11 Molex KK 254 22-23-2091 friction-lock vertical | KiCad `Connector_Molex:Molex_KK-254_AE-6410-09A_1x09_P2.54mm_Vertical` | resolved (LCSC footprint of C587032 agrees) |
| Playfield Molex KK 396 26-60-5020 right-angle | KiCad `Connector_Molex:Molex_KK-396_A-41792-0002_1x02_P3.96mm_Horizontal` (that exact part) | resolved |
| power Molex Mini-Fit Jr 39-30-3035 1x3 RA | `skeeball:Molex_Mini-Fit_Jr_39-30-3035_1x03_P4.20mm_Horizontal` | drawn (`fpgen.py`): LCSC C505179 footprint + scan pegs |
| RGB Molex Mini-Fit Jr 39-30-1049 1x4 vertical | `skeeball:Molex_Mini-Fit_Jr_39-30-1049_1x04_P4.20mm_Vertical` | drawn: LCSC C587488 footprint, diagonal pegs confirmed on the scan |
| vertical USB-C HRO TYPE-C-31-D-06 | `skeeball:USB_C_Receptacle_HRO_TYPE-C-31-D-06_Vertical` | drawn from the HRO recommended layout |
| lane-ID DIP XKB DSIC04LS-P | `skeeball:SW_DIP_XKB_DSIC04LS-P` | drawn from the XKB PCB layout (1.10 x 1.70 pads, rows 9.30 c-c) |
| HanRun HR963380AE vertical RJ45 | `skeeball:RJ45_HanRun_HR963380AE_Vertical` | drawn from HanRun p.3 recommended layout |

Placement rule (owner 2026-10-26): SMD parts on the TOP side only unless absolutely critical; THT through. Renders of
the 7 footprints: `renders/footprints/` (inspected).

## Function groups (proposed; see the render)
G1 RP2350B (QFN-80, 10 x 10 mm) + flash + crystal in the stock MCU area (QSPI / crystal / decoupling per the RP2350 hardware guide); G2 power
next to PWR; G3 light FETs between the light connectors and the MCU; G4 score input ESD + RC in-line above J11 (where
the stock C9-C18 row is); G5 button inputs beside Buttons; G6 audio next to J20; G7 USB host parts behind J18; the
former modular-jack strip (bottom, now empty) holds G8 USB-C + CH340N, G9 RESET / BOOTSEL / DIP, G10 LEDs, G11 SWD, G12
test points - all reachable and visible from above (to confirm: M-Z3). The W5500 group sits beside whichever RJ45
zone is picked (`W5500_GROUP` in layout_const).

## RJ45: owner decision 2026-10-26 = zone a, vertical (study kept below)
HanRun HR963380AE at x 23.4-39.6, y 8.4-24.9 mm (centred on the stock model-number silk area), the W5500 group G13
directly below it (x 23-43, y 27-36) so the MDI pairs stay short; light FETs G3 sit below that (y 42-51). Open on the owner
list: M-Z1 (headroom over zone a: 16.85 mm jack + plug + cable bend). M-Z4 is closed.

### The 2 x 2 study that led to it
| Option | Body (mm) / height | Placement (x, y mm) | Nearest features (edge gap) | Notes |
|---|---|---|---|---|
| a + right-angle HR911105A (C12074, stock 69,833) | 15.9 x 21.3 / 13.5 | x 23.6-39.5, opening at the top edge | RGB 11.9, Playfield 13.5 | cable leaves the top edge with the USB and power plugs |
| **a + vertical HR963380AE (C19724763, stock 154) - CHOSEN** | 16.2 x 16.5 / 16.85 | x 23.4-39.6, y 8.4-24.9 | RGB 7.8, Playfield 13.3 | plug from above; headroom confirmed fine (M-Z1) |
| b + right-angle HR911105A | 15.9 x 21.3 / 13.5 | x 96.4-117.7, y 20.2-36.1, opening at the right edge | PWR 8.2, SPEAKER 9.6 | cable leaves the right edge |
| b + vertical HR963380AE | 16.2 x 16.5 / 16.85 | x 96.7-112.9, y 19.9-36.4 | PWR 8.0, SPEAKER 9.2 | plug from above |

All four fit the measured outline with >= 7 mm to every stock feature (photo +-1 mm). The owner picked **a +
vertical**; `RJ45_OPTION = "V"` in `design.py` (the "RA" branch stays as the fallback if the part runs out).

## Layout rules carried into routing (from the references)
RP2350B: QSPI traces short and equal, crystal + caps tight with the 1 k at XOUT, decoupling at each pin, USB 27 R at the
chip and a 90 Ohm pair to J18 (Hardware design with RP2350, section 2). W5500: equal-length MDI pairs, no planes under
the magjack's line side, damping-resistor footprints kept, power jack not next to the RJ45 (WIZnet notes a-g). MAX98357A:
short, wide OUTP/OUTN, ferrites at the connector. TLV62569 / TPS2595: SLVSDG1C / SLVSE57C layout sections (tight SW
loop, ILM / dVdt at the pin). 2-layer, GND pour both sides with stitching.
