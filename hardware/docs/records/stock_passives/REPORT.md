# Stock A5CB25502 Rev 2.2 - passive component audit (2026-10-26)

Owner request (2026-10-26): "explain the purpose (or speculate as best as possible) to every passive component you saw
on the board, replicating its functionality if it is still needed." Report only; SBC-1 changes that came out of it are
listed at the end.

## Method
- Sources: owner photos of the stock board (kept outside this repo) (the 4032 /
  5712 px close-ups of the centre were sharpest; `board_front_straight.jpg` for positions). The 300 dpi bottom scan
  shows no parts on the back (near-solid pour): every passive is on the top side. Cited crops: `crops/`.
- Positions: mm from the component-side top-left corner (x right, y down), from a homography on the four measured hole
  centres; cross-check J11 pin 1 69.3 / 64.6 (scan 68.6 / 65.0), speaker pin 100.2 / 47.7 (scan 100.1 / 48.3); +-1.5 mm.
- Connections traced on top copper in the photos only (no meter). RP2040 QFN-56: pin 1 at the dot (top-left of U3),
  counter-clockwise. Each connection is **seen** (trace visible in a crop) or **inferred** (position / reference design).
- Values: resistor markings read where printed (3-digit or EIA-96); MLCCs and 0402 resistors carry no marking ->
  **unreadable**; typical values given for them are inferences.
- Confidence: **known** = marking or trace seen and the function is unambiguous; **likely** = position + reference-design
  convention; **speculative** = best guess.
- Spot-check by root: crop 09 confirms R1-R4 marked `01D` (100 k) next to FET1 / FET2.

## Counts
| Kind | Populated | Designators |
|---|---|---|
| Resistors | 19 | R1-R10, R12-R20 |
| Capacitors | 42 | C1-C42: 4 aluminium electrolytics (C3 radial THT; C6, C10, C31 SMD Wurth 100 uF / 35 V), 38 MLCCs. **C28 inferred** (silk hidden; the only gap in the numbering and one cap has no label, U3 bottom edge) |
| Ferrite beads | 2 | FB1, FB2 |
| Crystal | 1 | Y1 (12 MHz, HC-49 SMD `A120G19`) |
| Fuses / PTCs / TVS / diodes | 0 | none (no D1 anywhere; D2 is the status LED) |
| **Total populated passives** | **64** | (+ D2 LED as part of the D2 + R15 network) |
| **Unpopulated passive footprints** | **1** | **R11** (0402, bare pads, beside R5 at U2) |

Unpopulated non-passive footprints (context): J2 `JButton` 2x5, J5 / J7 1x4, J19 3-pin - all removed in SBC-1
(ARCHITECTURE R-5 / section 6). The J2 filter caps C38-C42 are populated although J2 is not.

## Power input
| Ref | Pos (x, y) | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| C3 | 102, 16 | radial THT aluminium electrolytic, blue sleeve, ~10-12.5 mm can; value unreadable; stripe toward the GND pin. [crop 15](crops/15_power_c3_c4.jpg) | across the power header 5 V / GND; the wide 5 V trace leaves from here (seen) | **Main 5 V reservoir** at the input: brick-lead inductance, light switching and audio peaks (likely: the only large can, at the input) | Replicated per rail: C5 10 uF + C4 on +5V_IN, C1 220 uF polymer on +5V_RGB, C7 / C56 / C57 220 uF polymer on +5V_SYS |
| C4 | 95, 16 | SMD MLCC half under C3; unreadable | one pad on a via (GND, inferred), the other on 5 V (inferred) | **HF bypass** at the 5 V input (likely: 100 nF beside a bulk can) | C4 100 nF on +5V_IN |
| (none) | - | - | - | no fuse, TVS or reverse-polarity part | SBC-1 adds D1 SMBJ5.0A, U1 eFuse, F1 / F2 PTCs |

## 3.3 V regulator (U1, NCP1117-3.3 class) and display VBUS
| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| C6 | 69, 6 | SMD Al electrolytic `WE / 100 / ASSH-J41 / 035` = Wurth 100 uF, 35 V (inferred from `035`). [crop 13](crops/13_J18_C6.jpg), [crop 02](crops/02_ldo_U1_C6_C10.jpg) | + pad beside J18 pin 1 (VBUS); the 5 V trunk runs here (seen); U1 VIN adjacent (inferred) | **5 V bulk for the LDO input and J18 VBUS** (likely; the RP2040 is the USB host, so J18 VBUS = board 5 V) | C16 22 uF on VBUS_HOST (behind TPS2553 U4), C10 4.7 uF buck input, C7 / C8 / C9 on +5V_SYS. See W1 |
| C10 | 70.5, 23 | same Wurth 100 uF / 35 V | below U1's tab (VOUT); + pad on the 3.3 V pour (seen) | **NCP1117 output capacitor** (needs >= 10 uF for stability) + 3.3 V bulk (known function, likely net) | buck output set: C11 10 uF (TLV62569 COUT), C33 / C44 10 uF on +3V3 |

## MCU (U3 RP2040) decoupling, flash, boot, crystal, reset, status LED
Reference: Raspberry Pi *Hardware design with RP2040* minimal design (100 nF per IOVDD / DVDD / USB_VDD / ADC_AVDD,
1 uF on VREG_VIN / VREG_VOUT, 100 nF at the flash, 1 k BOOTSEL, 1 k XOUT, 27 R USB series).

| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| C21, C27 | 61.0 / 62.2, 26.1 | 0402 MLCC, unreadable. [crop 03](crops/03_mcu_top_C21-C30_R13_R14.jpg) | U3 top edge, pins ~49-50 (IOVDD / DVDD) (inferred) | decoupling, 100 nF typical (likely) | C18-C27 (100 nF x10, +3V3), C28-C30 (DVDD) |
| C22, C24 | 65.6 / 66.6, 26.4 | 0402 MLCC, unreadable | top edge right of the USB pins: USB_VDD (48) / ADC_AVDD (43) (inferred) | decoupling 100 nF (likely) | as above |
| C29, C30 | 67.6, 28.7 / 29.7 | 0603 MLCC, unreadable | top-right corner, VREG_VIN (44) / VREG_VOUT (45) (inferred) | **1 uF in / out caps of the RP2040 internal 1.1 V LDO** (likely-speculative: size + position) | C31 4.7 uF; DVDD from the external TLV74311 with C13 / C14 / C32 |
| C26 | 56.7, 30.8 | 0603 MLCC, unreadable | left edge near IOVDD pin 1 (inferred) | decoupling (likely) | C18-C27 |
| C23 | 56.7, 34.5 | 0603 MLCC, unreadable | left edge near IOVDD pin 10 (inferred) | decoupling (likely) | C18-C27 |
| C25 | 67.3, 33.3 | 0603 MLCC, unreadable. [crop 05](crops/05_status_D2_R15_C25.jpg) | right edge, IOVDD 33 / 42 (inferred) | decoupling (likely) | C18-C27 |
| C28 (inferred ref), C20 | 62.1 / 63.1, 38.7 | 0402 MLCC, unreadable. [crop 04](crops/04_mcu_bottom_R12_C28_C20_R10_C1_C5.jpg) | bottom edge pins ~22-23 (IOVDD / DVDD) (inferred) | decoupling (likely) | C18-C30 |
| C7 | 58.6, 17.2 | MLCC, unreadable. [crop 01](crops/01_flash_bootsel_R5_R11_C7.jpg) | U2 (W25Q128JV) pin 8 VCC; other pad to a GND via (seen) | **flash VCC decoupling** 100 nF (known function) | C34 100 nF |
| R5 | 51.3, 16.9 | 0402, unmarked | U2 pin 1 (/CS = QSPI_SS) side -> J3 (trace toward J3 seen) | **BOOTSEL 1 k series**: the J3 jumper pulls QSPI_SS low at reset -> USB bootloader (likely; the lane-1 dump used exactly this) | R12 1 k + SW1 BOOTSEL button |
| R11 | 52.4, 16.8 | **DNP** | beside R5 on /CS | optional QSPI_SS pull-up or alternate BOOTSEL value (speculative) | not needed: unpopulated on stock, absent from the minimal design |
| Y1 | 61.6, 43.2 | `A120G19` HC-49 SMD = 12.000 MHz | XIN (20) / XOUT (21) | system clock (known) | Y1 12 MHz ABM8-272-T3 |
| C1, C5 | 58.9 / 62.9, 40.2 | 0603 MLCC, unreadable | one on each Y1 pad to GND (seen) | **crystal load caps**, 15-27 pF C0G typical (known function) | C35 / C36 15 pF C0G |
| R12 | 61.0, 38.7 | 0402, unmarked | bottom edge at XOUT (21) toward Y1 (inferred) | **XOUT drive-limit 1 k** (likely) | R14 1 k |
| R10 | 65.0, 38.7 | 0402, unmarked | U3 bottom-right corner (RUN 26 / GPIO16-17 area), toward J19 (trace not resolved) | **RUN pull-up** (10 k class) or an SWD series resistor (speculative) | covered either way: RUN internal pull-up + SW2 / R13 + TP13; SWD R15 / R16 100 R |
| D2 + R15 | 70.4, 33.4 / 34.7 | D2 ~0805 LED; R15 0402 unmarked | U3 right edge; heartbeat GPIO27 (stock firmware analysis) | **heartbeat LED + current limit** (known) | D5 + R17 470 R (GPIO25) |

## USB (J18 micro-B, RP2040 = host)
| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| R13, R14 | 63.3 / 64.5, 26.3 | 0402, unmarked | above U3 pins 46 / 47 (USB_DM / DP); traces straight to J18 (seen) | **USB 27 R series termination** (likely; minimal design) | R74 / R75 27 R + U12 USBLC6 (stock had no USB ESD) |

## Light drivers (FET1 / FET2 SOT-23-6, dual N-MOSFET likely; 4 channels)
[crop 09](crops/09_light_fets_R1-R9.jpg)

| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| R7, R6 | 32.2, 34.8 / 36.8 | 0402, unmarked | FET1 pins (seen) <-> long traces to U3 GPIO0-3 | **gate series resistors** (likely) | R66 / R68 / R70 / R72 100 R |
| R9, R8 | 32.3, 40.1 / 41.8 | 0402, unmarked | same on FET2 | gate series (likely) | as above |
| R1, R3 | 32.2, 33.4 / 38.6 | 0603 `01D` = **100 k** (EIA-96) | FET1 gate nodes to GND (inferred) | **gate pull-downs**: lights off while GPIO float at reset (likely) | R67 / R69 / R71 / R73 10 k |
| R2, R4 | 37.1, 40.1 / 41.8 | 0603 `01D` = **100 k** | FET2 gate nodes to GND (inferred) | gate pull-downs (likely) | as above |

## Score inputs (J11 9-pin, also wired to the 8 modular jacks)
[crop 11](crops/11_score_caps_J11.jpg)

| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| C18, C17, C16, C14, C13, C12, C9, C11 (left -> right) | 52.1-69.7 (2.5 pitch), 60.3 | 0402 MLCC x8, unreadable | each on one score line between J11 and U3 (GPIO9-15, 18), other pad on a GND via (seen); per-pin order not traced | **line-to-GND filter cap per score switch**: shunts harness noise and, with the ~50 k internal pull-up, some hardware debounce (known function, value unknown). No series R, no external pull-up, no ESD | replicated and improved: R42-R57 (2.2 k pull-up for 1.5 mA wetting + 4.7 k series), C60-C67 1 nF at the MCU, U9 / U10 ESDA6V1-5SC6 |

## Buttons (2x4 header: START, PLAYERS, VOLUME, GAME)
[crop 10](crops/10_button_caps_C2_C8_C15_C19.jpg)

| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| C8, C2, C19, C15 | 22.6-22.9, 48.2 / 50.7 / 53.4 / 56.1 | 0402 MLCC x4, unreadable | one per Buttons signal to U3 (GPIO4 / 5 / 6 / 8), other pad on GND via (seen) | **button-line filter caps**, same pattern (known function); internal pull-ups only | R58-R65 + C68-C71 1 nF + U10 / U11 ESD |

## JButton (J2 2x5, unpopulated)
[crop 12](crops/12_jbutton_caps_C38-C42.jpg)

| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| C41, C40, C39, C42, C38 | 100.4 / 108.3 / 112.3, 53.3; 91.6, 55.3; 91.4, 59.8 | 0402 MLCC x5, unreadable | five J2 lines to U3 (right-side bus or the alternate GPIO2-6 group; unresolved) | **filter caps for an alternate button header** (likely) | not needed: J2 unpopulated, no harness, removed (ARCHITECTURE R-5) |

## Audio (GPIO28 PWM -> RC filter -> U4 MSOP-8 class-D -> J20 speaker)
U4 MSOP-8 with exposed pad; pin use seen (1 -> pull-up, 3 / 4 -> input resistors, 5 / 8 -> beads, C32 at 6 / 7)
matches TI TPA2005D1 (DGN) / Diodes PAM8302A (1 SD, 3 IN+, 4 IN-, 5 VO+, 6 VDD, 7 GND, 8 VO-); marking unreadable
(identity speculative). [crop 06](crops/06_audio_input_R16-R19_C33-C35.jpg), [crop 07](crops/07_R16_marking.jpg),
[crop 08](crops/08_audio_amp_U4_R20_C32_FB_C36_C37.jpg), [crop 14](crops/14_C31_label.jpg)

| Ref | Pos | Value / marking | Connects to | Purpose | SBC-1 |
|---|---|---|---|---|---|
| R16 | 79.3, 31.6 | 0603 `221` read inverted -> **220 R** (upright `122` = 1.2 k; orientation ambiguous) | from U3 GPIO28 (PWM audio, inferred) to the C33 node (seen) | **PWM reconstruction low-pass, R** (known function) | not needed: I2S audio (MAX98357A) |
| C33 | 81.1, 33.2 | 0603 MLCC, unreadable | R16 / R17 node to GND via (seen) | **low-pass C** stripping the ~15.6 kHz PWM carrier (known function) | not needed |
| R17 | 84.4, 31.9 | 0603 `182` = **1.8 k** | C33 node -> C34 (seen) | second series element: lowers the drive level / second pole (likely) | not needed (digital gain + GAIN_SLOT 9 dB) |
| C34 | 86.3, 31.5 | 0603 MLCC, unreadable | R17 -> R18 (seen) | **DC-blocking input cap**, IN+ (known function) | not needed |
| R18 | 89.7, 30.8 | 0402, unmarked | C34 -> U4 pin 3 IN+ (seen) | **amp input resistor Ri** (gain = 2 x 150 k / Ri style) (likely) | not needed |
| C35 | 86.8, 33.2 | 0603 MLCC, unreadable | GND via -> R19 (seen) | **AC ground of the inverting input** (single-ended drive) (likely) | not needed |
| R19 | 89.1, 32.8 | 0402, unmarked | C35 -> U4 pin 4 IN- (seen) | matched Ri for IN- (likely) | not needed |
| R20 | 95.1, 33.9 | 0603 `01D` = **100 k** | U4 pin 1 (SD) -> 5 V side (inferred) | **shutdown pull-up**: amp always enabled (likely) | R38 680 k SD_MODE pull-up (enable + channel select) |
| C31 | 95.7, 28.6 | Wurth 100 uF / 35 V SMD electrolytic | amp 5 V (inferred) | **amplifier supply reservoir** (likely) | C56 / C57 220 uF polymer (+ C7) on +5V_SYS |
| C32 | 92.1, 40.3 | 0603 MLCC, unreadable | under U4 pins 6 / 7 (seen) | **amp VDD decoupling** (likely) | C54 10 uF + C55 100 nF |
| FB1, FB2 | 96.7, 42.7 / 96.5, 38.6 | 0805 ferrite beads | U4 VO+ / VO- (pairing inferred) -> J20 | **class-D output EMI filter, bead** (likely; TI filterless class-D note) | FB2 / FB3 BLM21PG221SN1D |
| C36, C37 | 97.9, 37.0 / 98.1, 41.0 | 0603 / 0805 MLCC, unreadable | speaker side of the beads -> GND (inferred) | **EMI filter, cap ~1 nF** (likely) | C58 / C59 1 nF |

## Misc
No other passives on either side: nothing at the jacks, J5 / J7 / J19, Playfield or RGB headers, nothing on the bottom.

## Gaps (function still needed, missing in SBC-1)
**None confirmed.** Every stock passive whose function survives has an SBC-1 counterpart, mostly stronger; the rest
belong to removed blocks (PWM audio -> I2S, J2 / JButton and the R11 option dropped, NCP1117 -> buck). Checked, not gaps:
- **W1 VBUS bulk at J18**: stock ~100 uF (C6, if on VBUS); SBC-1 C16 22 uF behind the TPS2553. USB 2.0 7.2.4.1 asks
  >= 120 uF on a downstream port for hot-plug of bus-powered devices; here the display cable is fixed, the display takes
  its 5 V from the harness and the TPS2553 isolates VBUS. No change (optional: C16 -> 100 uF for strict compliance).
- **W2 score / button hardware time constant**: stock cap values unreadable (with ~50 k internal pull-ups they may give
  ms of debounce); SBC-1 = 2.2 k + 4.7 k / 1 nF + firmware debounce, as the stock firmware already does (DEBOUNCE menu,
  default 50 ms). No change.
- **W3 R10** (possibly a RUN pull-up): RP2350 RUN has an internal pull-up + SW2 / TP13. No change.

## Unsure (a clearer photo or an owner meter / continuity check settles it)
1. All unmarked values (MLCCs, R5-R10, R12-R15, R18, R19); most useful: score / button caps C9-C18, C33, R18 / R19,
   R13 / R14, R12 (in-circuit LCR / meter on a spare board).
2. R16: 220 R or 1.2 k (one ohmmeter reading).
3. R10 net: continuity to U3 pin 26 (RUN), J19 or 3.3 V.
4. C6 net: continuity C6+ to J18 pin 1 (VBUS) and U1 pin 3 (VIN).
5. C3 value / voltage (side photo of the sleeve).
6. U4 part number (raking-light macro of the marking) -> with R18 / R19, the stock gain.
7. FET part and gate mapping (which 100 k pairs with which series R / channel).
8. C28 designator (silk hidden; ref inferred).
9. J11 vs the modular jacks: parallel per pin? per-pin order of C9-C18.
10. C38-C42 destinations (U3 pins 30-36 or GPIO2-6).
11. D1: confirm no footprint is hidden under C3 or the power header.

## SBC-1 follow-ups from this audit (root, 2026-10-26)
- ARCHITECTURE section 2: the stock status-LED GPIO corrected to 27 (stock firmware analysis); the I/O table's score
  pull-up corrected to 2.2 k (matches design.py and section 5.9). design.py D5 note corrected.
- No circuit change: no confirmed gap.
