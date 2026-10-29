# Measurements and confirmations - received and still open

Board as photographed: the J11 / former modular-jack edge = **bottom**, power header = **top right**; origin = the
board's top-left corner (x right, y down), component side up. Received items are in `scripts/layout_const.py`
(`MEASURED`, `PADS`) and `scripts/design.py` (pin maps, connector parts). **Connector positions are now from the
owner's 300 dpi bottom-side flatbed scan** (`scripts/scan_extract.py`, +-0.1 mm; table in `docs/PLACEMENT_PLAN.md`).

## Received (owner 2026-10-26)
| ID | Result | Used as |
|---|---|---|
| M-O1 | Board **4-19/32 x 3-3/8 in = 116.68 x 85.73 mm**, 1.6 mm (owner 100 % sure of the length; the first photo estimate was 8 mm short) | outline in `layout_const.MEASURED`, drawn in `hardware/main/skeeball-controller.kicad_pcb` |
| M-O2 | Square corners | outline |
| M-H1 | Four corner holes (owner calipers 2026-10-26, edge -> near hole edge + 1.785 mm radius): **3.885 mm from the short (left / right) edges, 3.585 mm from the long (top / bottom) edges** -> (3.885, 3.585), (112.795, 3.585), (112.795, 82.145), (3.885, 82.145); spacing 108.91 x 78.56 (supersedes the first 3.97 / 3.97 reading) | H1-H4 in the board file: TODO-3 (applied at adoption) |
| M-H2 | Hole diameter **9/64 in = 3.57 mm** (nylon snap-in studs) | project footprint `skeeball:MountingHole_3.57mm` |
| M-C1 / M-P1 | Power: **Molex Mini-Fit Jr single-row 1x3 right-angle 0039303035** (board-lock pegs seen in the scan); pin 1 = 5 V at (95.40, 10.71), **middle pin NC**, pin 3 = GND at (103.72, 10.59) | `POWER_PINMAP`; Molex 39-30-3035, JLC C505179 (JLC-placed) |
| M-C2 / M-P2 | Buttons: **Mini-Fit Jr 2x4 vertical** 39281083; **latch-side row (y 61.7) = GND, top row (y 56.2) = the 4 signals**; pads x 3.7 / 7.8 / 12.0 / 16.2 | `BUTTONS_PINMAP` rows (row-to-pin-number check at layout) |
| M-C3 / M-P3 | RGB: **Molex Mini-Fit Jr single-row 1x4 vertical 0039301049** (board-lock peg seen); pin 1 (+5 V) at (4.12, 37.87), pins at 4.1 / 8.0 / 12.3 / 16.3 | `RGB_PINMAP`; Molex 39-30-1049, JLC C587488 (JLC-placed) |
| M-C4 / M-P4 | Playfield: **Molex KK 396 2-circuit right-angle friction-lock** (owner calipers: pins 5.10 mm outside-to-outside = 3.96 pitch + 1.14 square pins); lower pin = +5 V; scanned pad midpoint (4.63, 13.43) -> pads at y 11.45 / 15.41 (the scan's 3.38 reading is solder-blob bias) | Molex 26-60-5020 right-angle friction lock, JLC C587092 (JLC-placed; 0026644020 was a vertical part) |
| M-C5 / M-P5 | Speaker J20: **Mini-Fit Jr 2-circuit dual-row right-angle** 39291028; pads at (99.88, 48.27) and (105.38, 48.23), peg hole (112.6, 48.3); plug from the right edge | JLC-placed |
| M-C6 / M-P6 | J11: **plug housing 22.88 x 4.96 mm = 9 x 2.54 -> Molex KK 254** (owner calipers; the scan's 2.51-2.54 mm pitch could not separate XH from KK). Pin 1 ('*') at (68.57, 64.98), pin 9 at (48.27, 64.95) | fitted: genuine Molex KK 254 friction-lock vertical 22-23-2091, JLC C587032 (CJT A2541WV-9P dropped: plain pin header, no lock) |
| M-P7 | J11: **pin 1 ('*', square pad) = the common = GND** (full continuity to the power GND; no other pin to GND); pins 2-9 = the 8 sensor inputs; **J11 carries no 5 V** | `J11_PINMAP`, JP1 removed, inputs modelled switch-to-GND; hole-to-pin order = firmware |
| M-C7 / M-P8 | Micro-USB: shell anchors at (58.7, 2.2) / (64.2, 2.2) / (58.9, 5.1) / (63.9, 5.1) -> receptacle centre x = 61.43; mouth ~1 mm past the edge | `MEASURED`, `J18_CENTER_X` |
| M-E1 (deduced) | Light strips run on **5 V** (the stock board has only a 5 V input and a 3.3 V LDO) | FET / PTC rating; confirm with a meter when convenient |
| M-E4 | Machine PSU = **Mean Well LPV-60-5**: 5 V, 8 A rated (0-8 A), 40 W, overload 110-150 % (datasheet `datasheets/dl/LPV-60-spec.pdf`) | power budget source |
| M-E5 | Same speaker (Stetron DB20-009) in all four machines | amp gain / volume cap |
| M-E2 / M-E6 | **Owner DC clamp, 2026-10-26, stock board in attract mode (single readings; attract animates, clamp +-~0.2 A):** PSU output ~5.7 A; board 5 V input ~4 A; RGB strips (common wire) ~3.7 A; playfield bar ~0.5 A; display board ~1 A (fed from the PSU directly, not over USB). Loads sum to 5.2 A vs 5.7 total; board input 4 A ~= RGB + playfield + logic. Stock lights are on/off, so 3.7 A = the RGB strips at full on | firmware caps: RGB 4.0 A covers stock brightness; playfield cap 1.5 A (stock 0.5 A); budget board+lights 6.4 A + display 1.0 A = 7.4 A of 8 A. No hardware change |
| M-E2 | Light loads (owner photos 2026-10-26): RGB = 4-wire 60 LED/m 5050 analog strip over the 2.06 m alley + the ball-holder lip (7-9 A at full white uncapped), playfield = one rigid bar ~24 x 5050 (1.2-1.5 A) | AO3416 FETs, 5 A / 3 A PTCs, firmware light cap 5.0 A (ARCHITECTURE 5.10 / 5.13) |
| M-E3 | Score sensors = **mechanical lever microswitches** (owner photo + audible click 2026-10-26: a wire lever across each hole), closing to J11 pin 1 = GND | no sensor 5 V: +5V_SENS switch removed; 2.2 k pull-ups (1.5 mA wetting) |
| M-Z1 | Headroom over zone a is fine | vertical RJ45 stays |
| M-Z3 | A hand reaches anywhere on the installed board | RESET / BOOTSEL / DIP / USB-C on the bottom strip OK |
| M-Z4 | RJ45 = zone a, vertical | done |
| - | J5 / J7 beside Playfield / RGB are unpopulated 1x4 footprints | dropped (R-5) |

## Still open
| ID | What | Why it matters |
|---|---|---|

## Harness headers: all JLC-placed (2026-10-26)
JLC does stock the genuine single-row Mini-Fit Jr headers (the earlier search used the zero-padded MPNs, which only hit
discontinued listings): power 39-30-3035 (C505179), RGB 39-30-1049 (C587488); playfield KK 396 RA 26-60-5020
(C587092); J11 KK 254 friction lock 22-23-2091 (C587032). Option (b), the owner-fitted DigiKey order, is retired.

Open now: none (M-E2 / M-E6 measured 2026-10-26).
optional. Placement and routing proceed on the measured outline and pad positions.
