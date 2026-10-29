# DECISIONS (controversial calls only - PCB_DESIGN_AGENT.md 1.4)

#1 (root, 2026-10-26) **RESOLVED the same day by moving to the RP2350B** (QFN-80, 48 GPIO, JLC C42415655, 3,477 in
  stock at $1.28 = same price as the A): W5500 RSTn (GPIO19) and INTn (GPIO24) are MCU-driven / read as in the WIZnet
  reference again, the fault flag is on GPIO7, the lane-ID DIP has GPIO30-33, the 5 V monitor is on ADC0, and GPIO34-37
  go to spare test pads. The original call, kept for the record: W5500 RSTn on an RC power-on reset + software reset,
  INTn unused (polled), instead of the reference's MCU-driven RSTn / INTn. Why: all 30 RP2350A GPIOs are taken once the owner's lane-ID DIP is added; RC 10 k x
  1 uF = 10 ms meets the 500 us TRC minimum (W5500 DS 5.5.1); WIZnet's ioLibrary polls by default. Sacrifice: no hardware
  re-reset of the W5500 without a full board reset if its SPI interface ever locks up (the board-level RESET / watchdog
  still covers it); a few ms of extra latency on network events. Alternatives: read the DIP with an ADC resistor ladder
  on GPIO29 (frees 3 pins, less obvious); drop the DIP. Undo: move LANE_ID1 / LANE_ID2 back to ETH_RST_N / ETH_INT_N.

#2 (root, 2026-10-26) RP2350 core supply from an external TLV74311P LDO (RP2350 DS Figure 24) instead of the Minimal
  design's on-chip switcher. Why: its only specified inductor has JLC stock 1, and other 0806 inductors are 'at your own
  risk' per Raspberry Pi. Sacrifice: ~(3.3 - 1.1) V x core current (~0.1 W at 150 MHz) of heat vs the switcher; none
  functionally. Undo: restore L1 + C7 + the 33 R / 4.7 uF VREG_AVDD filter when the Abracon part is stocked.

#3 (lead, 2026-10-27; recorded by the routing agent) EP thermal vias are the ONE via-in-pad exception on SBC-1 (no via
  fill on the JLC order; written for the 2-layer board, unchanged on the 4-layer JLC04161H-7628 board). Plain 0.6 / 0.3 vias in the exposed pads of U5 (RP2350B, 3 x 3 grid as in Raspberry
  Pi's 2-layer RP2350 reference), U8 (MAX98357A EP) and U1 (TPS259531 EP, as many as fit), placed as LOCKED copper by
  scripts/route_prep.py; paste windowed per the vendor reference. Why: without them the RP2350B EP (its only GND for the
  core) and GND pins 62 / 65 cannot connect on 2 layers (first routed candidate: 3 GND opens there). Gate:
  qa_layout_quality VIA_INPAD_EP_REFS exempts exactly these EP pads (named constant + this reason); every other pad
  stays via-free. Sacrifice: a little solder wicking into the unfilled barrels (EP paste windowing compensates).

#4 (lead, 2026-10-27) +5V_IN width by budget path: the 5.5 A trunk is the LOCKED zone copper J1 -> F1 / F2 only; the
  eFuse branch J1 / D1 / C4 -> U1.3 / U1.4 carries 2.5 A; R1 / C5 / TP1 are signal level (0.1 A)
  (current_budget.BRANCHES). +5V_SYS stays in pfr2's FROZEN_POWER at its 2 A budget.

#5 (lead, 2026-10-27) current_budget DT_LOAD_K = 20 K for SBC-1 (CT / DIN-8R: 10 K). Why: 1 oz outer copper in a
  ventilated cabinet, light currents capped by firmware; the 10 K rule asked 4.4 mm for the 4 A RGB rail and 8.2 mm for
  the trunk. power_copper.py widths follow the 20 K budget (F.Cu zones where a track would not fit).

#6 (routing agent, 2026-10-27) pfr2 planning margin stays 0.04 mm (measured, not assumed): a sweep 0.04 / 0.06 / 0.08 /
  0.10 / 0.12 on the same staged board gave 34 / 57 / 58 / 61 / 85 open joins after run_stage (QA_LOG Q-55). The
  legalisation drops it was meant to stop came from no-net NC pads (plan_check 0.2 vs pfr2 0.15), removed at the source
  by naming every NC pad with KiCad's unconnected-(...) net in place.py.

#7 (owner 2026-10-26 ~23:05, lead threshold) 4-LAYER board. The 2-layer route stalled at 13 open joins (p11/best,
  archived as the fallback): every remaining join sat on the RP2350B pin ring (escape capacity + pin-order crossings),
  and the targeted closure batches p11-p13 only moved the failure between neighbouring nets. Stack: JLC standard
  4-layer 1.6 mm (JLC04161H-7628), 1 oz outer / 0.5 oz inner: F.Cu signals + parts; In1.Cu solid GND plane, never
  routed (every GND pad drops a plain via into it); In2.Cu routing (power + signals; power pours on In2 after the route
  closes); B.Cu signals + soft GND pour. Vias 0.6 / 0.3 through. The tools are multi-layer by origin (pfr2 = DIN-8R
  6-layer, copper_cleanup = CT 4-layer): only the SBC-1 2-layer constants changed (pfr2 RL / PLANE_LAYERS /
  PLANE_FILL_LAYERS / REF_PLANE, cugraph INNER_PLANES, board_const, pcb_rules, pcb_build, route_prep, current_budget
  inner 17.5 um). The whole board is routed from scratch: only power_copper's LOCKED copper is carried over.

#8 (owner 2026-10-26 ~23:12) GPIO pin-escape map (the stock RP2040 roles are lifted: original firmware). Each group
  leaves the RP2350B on the side that faces its destination, in its destination's order (RP2350 datasheet Table 3
  checked per pin): left side top W5500 on SPI0 (GPIO4 MISO / 5 CSn / 6 SCK / 7 MOSI, F1) + INTn GPIO8 / RSTn GPIO9 ->
  west to U7; buttons GPIO10-13 then scores GPIO14-21 (100B, 100A, 50, 40, 30, 20, 10, gutter = the RC grid's left ->
  right column order) -> south-west; bottom right UART0 GPIO28 TX / 29 RX (F2) -> CH340N, I2S on PIO (GPIOBASE 16)
  BCLK GPIO30 / LRCLK GPIO31 (= BCLK + 1, the pico-extras audio_i2s order) / DIN GPIO32 -> R39-R41 (now DIN / LRCLK /
  BCLK top -> bottom); right side lane-ID GPIO34-37 -> SW3, status LED GPIO44, PWR_FAULT_N GPIO47 -> up-right. USB,
  QSPI, XIN / XOUT, RUN, SWD unchanged (fixed function); LIGHT_R/G/B/PF stay GPIO0-3 (PWM 0A/0B/1A/1B). With it, J2
  (SWD) + R15 / R16 moved to the lower right (owner fix B) so SWCLK / SWDIO leave eastward with the UART / I2S group.
  Schematic regenerated: ERC 0, netlist == design; BOM unchanged by the remap.

#9 (owner 2026-10-26 ~23:25, HARD) No epoxy-filled / capped vias (no JLC POFV): JLC via covering = Tented. No via in or
  partly in any SMD pad except the DECISIONS #3 EP thermal vias (plain 0.6 / 0.3, unfilled, tented on B.Cu: U5 3 x 3,
  U8 1, U1 2). q6 evidence (coordinator QA 2026-10-27b): the owner's live JLC quote PDF (2026-10-27) shows Tented
  greyed out for this 4-layer build, so the order uses **Plugged**; JLC's Plugged process does NOT ink-plug holes in
  pads or vias < 0.35 mm from a pad, so the EP thermal vias stay open (their paste is windowed between them, place.py
  PASTE_WINDOWS) and the near-pad vias draw an engineering question to accept. Enforced by qa_layout_quality
  NO_VIP_FP_RE = '.' + VIA_INPAD_EP_PADS (pfr2 / via_site read the same
  constants: no_vip_refs = every footprint) and qa_copper_landing VIA-PADEDGE / VIA-PADGAP. No part needs a filled
  via-in-pad: the QFN / TQFN / WSON EPs take the plain thermal vias, the TLV62569 SOT-23-5 has no EP.

#10 (owner TODO-1, 2026-10-27) Score-jack 5 V on its own PTC: F3 Bourns MF-NSMF050-2 (JLC C75464, 0.5 A hold /
  1.0 A trip, 13.2 V, 1206) from +5V_SYS to +5V_JACK (J21-J28 contact 1), so a pinched opto-sensor cable trips F3, not
  the board eFuse.

#11 (agent under the owner's 2026-10-27 J10 approval, fallback branch) **J10 stays HRO TYPE-C-31-D-06 (C2689964) with
  pin-in-paste shell slots**, because no JLC-stocked vertical 16-pin USB 2.0 receptacle has a drawing that specifies a
  1.6 mm board (checked 2026-10-27 10:50-10:55 UTC through scripts/jlc_api.py = JLC's live part pages; drawings from
  LCSC in datasheets/dl/j10/, rendered and read): SHOU HAN TYPE-C 16P LTH6.8 C5187468 (49,496 stock) and 16PLT-H6.5
  C3151748 (30,745) "RECOMMENDED PCB THICKNESS 0.8+-0.10"; XYECONN TYPE-C-F08-2TDW C22385226 (572) "THICKNESS 0.8";
  HRO TYPE-C-31-E-17 C7424785 (1,051) "THICKNESS 0.8"; HRO TYPE-C-31-D-11 C5370448 (340) leg H 1.2 (D-11A 0.8), no
  board note; HRO TYPE-C-31-D-15 C22464480 (469, 8.8 mm tall) layout "T:1.00mm" with 2.20 +-0.25 mm shell legs; hanxia
  HX TYPE-C 16P LC H10.0 C25168811 (1,770, all-THT, 2.0 mm tails, 10 mm tall) no board note; SHOU HAN 16PFS LCH6.8
  IPX8 C3020048 (342, panel-flange waterproof) no board note. Rule (owner queue item 5): pin-in-paste on the old part
  only when no qualified part exists -> fpgen.usbc_hro_31d06: the 4 SH slots get a top paste aperture (pad + 0.1 mm,
  solder_paste_margin) so reflow fills the barrels from the top; footprint delta = paste layer only (copper, drills,
  courtyard, 3D fit, Q-50 envelope unchanged). Sacrifice: the 0.95 mm legs end 0.65 mm inside the 1.6 mm slots, so
  retention rests on a partial barrel fill + top fillet, not a through joint. OWNER DECISION (open): switch to HRO
  TYPE-C-31-D-15 (legs pass the board; 8.8 mm tall; drawing's layout note 1.0 mm) - see the final report.

#12 (agent, 2026-10-27, gate constant with a named reason) qa_layout_quality REF_LAYERS = In1.Cu for F / In2 / B. The
  2-layer value (F <-> B) survived the 4-layer move (DECISIONS #7): with no F.Cu GND pour it measured nothing real, and
  the first F.Cu GND patch (GND_J1_F) flagged every B.Cu SI track (PLANE-SLOT 40 -> 58). In1 is the solid GND plane
  and the CT parent's value on the same JLC04161H-7628 stack. PLANE-SLOT after the fix: 22 -> 21 (the J3 plane void
  adds MDI_TCT over the deliberate void).

#13 (agent, 2026-10-27, adversarial review S2 / S3) U1 UVLO divider 100k / 47k (worst rising 4.04 V, typ 3.75 V,
  falling 3.17-3.72 V; was 4.60 V worst = the LPV-60-5 floor) and U4 EN on GPIO46 + R80 100k pull-down (VBUS_HOST off
  in reset / BOOTSEL; firmware FW-2 in docs/BRINGUP.md drives it low before a software BOOTSEL reboot because the pad
  isolation latches hold the last level, RP2350 DS 9.7). Undo: R2 39k; EN back to +3V3 and remove R80.

#11-R (q6, resolution of #11) **RESOLVED 2026-10-27 (coordinator decision under the owner's approval, CORRECTIONS D1): J10 = HRO
  TYPE-C-31-D-15 (C22464480, 469 in JLC stock 2026-10-27 12:0x UTC via scripts/jlc_api.py)**: 4 shell legs 0.90 x 0.30
  x 2.20 +-0.25 mm pass the 1.6 mm board (a through joint), 8.8 mm tall. JLC has no LCSC footprint for it (EasyEDA API
  404): fpgen.usbc_hro_31d15 is drawn from HRO's drawing alone and the CPL carries a CONFIRM row. J10 moved +1.0 mm in x
  (108.5, 61.0) for the 12 x 5 flange; the Q-50 plug envelope check passes. The pin-in-paste D-06 footprint stays in
  the library (not used).

#14 (agent q6, 2026-10-27) HRO D-15 footprint: the drawing's own layout leaves a 0.135 mm web between each shell slot
  end (4.225 + 0.60) and the dia 0.90 peg hole beside it (5.41 - 0.45); no copper ring survives that (first q6 DRC: 8
  hole_clearance at the pad-to-NPTH 0.25 mm rule). At the two diagonal peg corners the leg and the dia 0.70 peg share
  ONE plated GND slot 0.80 x 2.185 mm (leg 3.775 .. 4.675 + peg 5.06 .. 5.76 along the long axis, 0.1 mm each); the
  other two slots are 0.55 x 1.25 (CORRECTIONS D1). Sacrifice: the pegs locate in a plated oval instead of a round NPTH
  (location +-0.05 mm across, slot-length along). Undo: two NPTH dia 0.90 if JLC accepts a 0.135 mm web.

#15 (agent q6, 2026-10-27) EP thermal vias / paste: U8 (MAX98357A, EP 1.23 mm) keeps ONE 0.6 / 0.3 via. CORRECTIONS
  A6 asked for 4-5; four 0.6 mm vias (min_via_diameter 0.6, hole 0.3, hole-to-hole 0.25) cannot sit inside a 1.23 mm
  pad with qa_layout_quality's 0.05 mm via-in-pad margin (tried at +-0.31: 4 VIA-INPAD findings). Paste windowpanes
  (place.py PASTE_WINDOWS, text pass rewrite_paste_windows): U5 4 bars 51 %, U1 3 bars 39 %, U8 4 squares 33 %, none
  over a via hole (>= 0.1 / 0.05 / 0.06 mm). Undo for U8: smaller vias (0.45 / 0.2) if the project via rule changes.

#16 (agent q6, 2026-10-27) Power copper trade-offs: (a) the eFuse input land over U1 pins 4 + 3 is tracks (1.0 mm into
  a 0.7 mm piece to pin 4, 0.44 mm pin 4 -> 3), not a zone: a +5V_IN fill at U1 made qa_copper_landing see the trunk
  on both sides of the eFuse branch (budget 5.5 A instead of DECISIONS #4's 2.5 A); 0.44 / 0.7 mm are the widest tracks
  the EP (0.15 mm) and pin 2 (0.15 mm) allow. (b) J1.1 / J1.3 on 4-spoke 1.0 mm thermal reliefs (CORRECTIONS A8): the
  connectivity-aware min cut J1.1 -> the F1 / F2 via array drops from 5.70 to 4.58 mm 1 oz-equivalent (>= the 4.5 A1
  target, so kept); the A2 7.5 mm goal is not reached (owner decision O2). Undo (b): power_copper THERMAL_PADS = {}.

#17 (agent q6, 2026-10-27) Two design.py regenerations instead of one: the first (B1 R81, B2 R82, B3 4.7 k, B4 510 k,
  C2 NationStar LEDs, D1 J10 D-15) and a second, note-text-only one (A9 corrections in the F1 / U1 / 220 uF / R4
  notes, found while writing the docs). Both: ERC 0, netlist compare 0, bom.py check PASS (76 lines); the board's
  fields were re-synced (DRC parity 0 failing).

#18 (agent q6, 2026-10-27) Y1 XOUT (CORRECTIONS B5): R14 cannot sit against U5 pin 31 - XIN (pin 30, locked straight
  stub) and C29 (DVDD pin 32 decap) flank it and the ABM8 pads are diagonal. XOUT is now a locked F.Cu stub with no
  via: down the 0.6 mm lane between XIN and C29, under C29 / above the Y1 pads, to R14.1 (R14 at 63.45, 47.755): 5.5 mm
  pad to pad (was 13.1 mm, 3 vias); XOUT_X 4.7 mm F.Cu to C36 / Y1.3. C29.2's GND drop moved beside the pad.

#19 (agent q6, 2026-10-27) Display D+ ESD in line (CORRECTIONS B6): J9's pin order (D+ left of D-) and the USBLC6 pin
  pairs (D- top row, D+ bottom row) put the in-line D- lane between J9.3 and U12.3, so D+ crosses it once on B.Cu (2
  vias, below the trunk dip): J9.3 -> U12.3 -> bridge -> R75; no ESD stub. Full-speed USB tolerates the vias.
#20 (OWNER 2026-10-27) O1 ACCEPTED: no per-channel short protection on the light FETs. A channel wire shorted to +5 V can
  destroy its AO3416, the same exposure as the stock board. Mitigation: check the harness at install. Reason: lift-and-shift
  parity, and the risk is small for a 5-board run.
#21 (OWNER 2026-10-27) O2 ACCEPTED: keep the F1 / F2 PTCs (no high-side eFuse). Fault coordination relies on the +5V_IN trunk
  copper (4.58 mm min, 5.70 mm along the strip, 1 oz-equivalent), the LPV-60-5 overload hiccup (8.8-12 A), and the firmware RGB
  cap of 3.3 A RMS.
  O3 (caliper re-check: overall 3-3/8 in, H3 / H4 to the jack edge, H1-H2 outer-to-outer) is still OPEN (owner: "tbd") and gates
  the order.
#22 (OWNER 2026-10-27) O3 CLOSED, no re-measure: "the original dimensions of the board were perfectly accurate". The
  caliper outline (116.68 x 85.73 mm) and the hole insets (3.885 / 3.585 mm) are authoritative. The flatbed-scan edge
  disagreement (~0.4 mm at the jack edge) is scanner shading / stretch and is disregarded. Rule for future reviews: don't
  re-open owner caliper facts from scan or photo estimates. No open owner decisions remain; the release package
  fab/release-2026-10-27b is ready to order.
#23 (agent, 2026-10-27, coordinator order) D2 FAULT red = Hubei KENTO KT-0603R, LCSC C2286 (JLC basic), replacing NationStar
  NCD0603R1 C84263: JLC's assembly review says C84263 is Standard-PCBA-only and the order is Economic PCBA (single board, no
  rails). Same 0603 footprint / nets; D4 NCD0603Y1 stays (not flagged). C2286's LCSC symbol + footprint name pad 1 = A and
  put the layer-101 dot on it (KENTO drawing: pad 1 = '+'), so the dot marks the ANODE on this part. fab_release.py now checks
  diode polarity by the LCSC A / K pin names onto our A / K nets (netlist pin functions), not by the dot; the dot rule stays
  only for LCSC symbols without A / K names (D1 TVS). A reversed diode still FAILs (scripts/test_fab_polarity.py). Order
  remark in fab/release-2026-10-27c/README.md asks JLC to confirm D2 in the placement preview. Supersedes release-b.
#24 (OWNER 2026-10-27) ORDER BUILD = release-2026-10-27b files uploaded to JLC, with D2 swapped to C2286 (KT-0603R) through
  JLC's in-UI part override. This is equivalent to fab/release-2026-10-27c: identical gerbers apart from dates, and only the
  D2 BOM line differs. The owner checked the JLC placement preview: D2 "+" is on the anode (LED_FAULT_A) pad.
  release-2026-10-27c is the record of what was built.
#25 (OWNER 2026-10-28) JLC order 13673858A_Y27: the PCB production file and the PCBA placement are both APPROVED by the owner.
  Audits: QA_LOG Q-62 (production file) and Q-63 (placement shots). Build = fab/release-2026-10-27c equivalent (DECISIONS #24).
  Next on arrival: docs/BRINGUP.md (current-limited first power-up, rails, SWD ID, lights off in reset, then every
  channel) and the original firmware (VREG HIZ, GPIO46 display VBUS enable, RGB cap 3.3 A RMS).
