# RUNNING LOG (append-only)

- Root 2026-10-26: project created from the brief (replace A5CB25502 Rev 2.2, same harness connector positions, wired
  Ethernet). Workflow copied from `C:\work\din-relay-8ch` (PCB_DESIGN_AGENT.md, jlc_api.py, netlist_core / gen_schematic /
  qa_netlist / symgen, one-JSON BOM).
- OWNER 2026-10-26 (via coordinator), in order: no PoE at all; replace aluminium electrolytics with polymer / MLCC and
  note every quality upgrade; score sensors use J11, eliminate the 8 modular jacks and every unpopulated footprint (J2,
  J5/J7, J19), add the J11 pinout to the confirmation list; any MCU allowed, document a comparison; every part 100 % in
  JLC stock checked live and dated; RJ45 in zone a or zone b, vertical or right-angle open; USB-C debug port (device,
  5.1 k CC), weighed as one factor; vertical USB-C receptacle; every IC per its vendor reference with deviations cited;
  MCU = RP2350 + QSPI flash + W5500; diagnostic LEDs + RESET / BOOTSEL; lane-ID DIP x4, PWM lights only, protected sensor
  / light power, no reverse-polarity circuit, no expansion header, 16 MB flash, MAC from the unique ID, labelled test
  points; speaker = BOSS BRS52B 4 R (manual photo), modest gain; outline + holes identical to stock.
- Root 2026-10-26: datasheets fetched to `datasheets/dl/` (RP2350 DS + hardware guide, W5500 DS + WIZnet reference,
  ESP32 / S3 / P4, STM32F405/407, MAX98357A, TPS2595, TPS2553, TLV62569, TLV743P, CH340, HanRun HR911105A / HR963380AE,
  HRO TYPE-C-31-D-06, XKB DSIC04LS-P). Reference schematics rendered to PNG and read.
- Root 2026-10-26: design.py written; ERC fixes (QA Q-1), generator readability fixes (Q-2), CH340N (Q-3), external core
  LDO (Q-4, DECISIONS #2), lane-ID DIP pins freed (DECISIONS #1), passives to JLC basic (Q-8, Q-9). Schematic ERC 0
  electrical, netlist == design; BOM check 0 fail; parts ~$37.9 / board at 5 boards (incl. $18 extended-part fees).
- Root 2026-10-26: placement plan + RJ45 zone study rendered and inspected (Q-6); measurement list written.
- OWNER 2026-10-26 (via coordinator): only the four corner holes are used (nylon studs), inner holes dropped; new photos
  board_front_straight / board_back / speaker_label: J11 = 9 pads, square pad = pin 1 = '*', 8 capped inputs + 1 common;
  single-sided assembly OK; speaker = Stetron DB20-009 (AACE8811A), 4 Ohm, rating unverified; add a 5 V power budget and
  the audio ceiling.
- Root 2026-10-26: geometry re-estimated from the straight photo with a plane homography (Q-10); Buttons = 2x4 (Q-11);
  speaker corrected (Q-12); second polymer reservoir at the amp (power budget, ARCHITECTURE 5.12); generator fixes
  (Q-13). Final: ERC 0 electrical, netlist == design, BOM check 0 fail, parts ~$35.5 / board + harness at 5 boards.
- COORDINATOR 2026-10-26 (follow-up on DECISIONS #1): evaluate the RP2350B as the fix; note the display is brick-powered
  per the 2022 manual. OWNER: J11 plug = black 9-way latching housing (KK 254 / XH style) -> shrouded friction-lock
  vertical header, pitch 2.54 vs 2.5 to confirm.
- Root 2026-10-26: RP2350B in stock at JLC (3,477, $1.2833, same as the A) -> switched (Q-14, DECISIONS #1 resolved):
  W5500 RSTn / INTn on GPIO19 / 24, PWR_FAULT_N on GPIO7, lane ID on GPIO30-33, +5V_SYS monitor on ADC0, spares GPIO34-37
  on TP19-22; decoupling per Figure 16. J11 = CJT A2541WV-9P (Q-15), JST B9B-XH-A alternate. Rebuilt: ERC 0 electrical,
  netlist == design, BOM 73 lines 0 fail, ~$36.2 / board + ~$2 harness TBD. Renders re-done (G1 = QFN-80).
- COORDINATOR 2026-10-26: cost pass on the 28 extended lines (basic drop-ins only; no ICs / connectors / reference-
  specified parts). OWNER: RJ45 = zone a, vertical (HR963380AE or an in-stock equivalent); M-Z4 closed, M-Z1 stays.
- Root 2026-10-26: 3 swaps (Q-17) -> 25 extended lines; RJ45_OPTION = V, HR911105A out of the BOM, W5500 group G13 under
  the jack, renders redone (Q-16). HR963380AE 154 in stock (live), no second vertical magjack at JLC: backup named
  (XUNPU jack + HX1188NL). Parts: $19.61 + $0.83 + fees $15.00 = ~$35.4 / board at 5 (+~$2 TBD harness); ~$24.2 at 20.
- OWNER 2026-10-26 (via coordinator): measurements - outline 116.68 x 85.73 mm (exact), square corners, 1.6 mm; four
  corner holes 3.97 mm in, 3.57 mm; power middle pin NC; J11 edge span 20.64 mm (pitch open); micro-USB 1 mm proud;
  strips on 5 V (deduced); same speaker x4; headroom over zone a fine; hand reaches everywhere. Continuity: RGB leftmost
  pin = +5 V; Playfield lower pin = +5 V. Open: Buttons pin map, J11 pitch / pin map / common, header families, strip
  current, brick label, display current; a 600 dpi bottom scan is requested.
- Root 2026-10-26: photo homography re-anchored on the measured holes (Q-18; the J11-pitch scaling had been 5 % short);
  `layout_const.MEASURED` filled; board file written with the outline + 4 holes (pcb_build.py, Q-20); pin maps fixed
  (Q-19); MEASUREMENTS_NEEDED split into received / open; renders + schematic + BOM rebuilt (ERC 0 electrical, netlist ==
  design, BOM 0 fail).
- OWNER 2026-10-26 (via coordinator), continuity + edge photos: speaker = Mini-Fit Jr 2-circuit dual-row RA (5569-02A1
  class), power = 4.2 mm single-row 1x3 RA, Buttons = 2x4 Mini-Fit Jr (latch-side row all GND, other row = signals),
  RGB = 4.2 mm single-row 1x4 (leftmost = +5 V), Playfield = black 2-pin friction-lock RA (~3.96 mm?, lower pin +5 V);
  J11 pin 1 ('*') = GND common, pins 2-9 inputs, no 5 V on J11.
- Root 2026-10-26: design.py updated (J11 pin 1 GND, JP1 removed, Buttons rows, speaker 39291028 + Buttons 39281083 on
  KiCad Molex footprints; +5V_SENS kept unloaded); JLC has no single-row 4.2 mm 1x4 / only a thin 1x3 RA (Molex 42817 /
  42818 at JLC are Mini-Fit Sr 10 mm) -> owner options written in MEASUREMENTS_NEEDED (Q-23). Rebuilt: ERC 0 electrical,
  netlist == design, BOM 73 lines 0 fail, 26 extended lines, ~$36.6 + ~$1.5 / board at 5.
- OWNER 2026-10-26: 300 dpi bottom-side flatbed scan delivered; decision (b) on the single-row headers: owner-fitted
  from a separate DigiKey BOM.
- Root 2026-10-26: scan_extract.py (hole-anchored affine, +-0.1 mm) -> all harness pad centres (Q-24); J11 = XH 2.5 mm
  (JST B9B-XH-A at JLC); Playfield pitch 3.38 (family open); genuine Molex single-row Mini-Fit Jr headers found at
  DigiKey (Q-25) -> owner-fitted lines with Assembly="owner" in design.py, `bom.py digikey` writes DIGIKEY_BOM.md + CSV
  and ORDERING.md shows both orders; layout_const / renders / board file now use the scanned pads; photo estimate
  retired to the RJ45 zones.
- OWNER 2026-10-26 (calipers / photos): J11 plug = KK 254 (housing 22.88 x 4.96) -> CJT A2541WV-9P kept, XH dropped;
  Playfield = KK 396 2-ckt RA friction lock -> Molex 0026644020 owner-fitted; PSU = Mean Well LPV-60-5 (8 A / 40 W,
  verified on the datasheet); RGB strip 60 LED/m 5050 over >2 m (7-9 A full white) + playfield bar ~24 x 5050 -> light
  FETs to >= 3 A parts, per-channel PTCs, firmware current cap (NOT yet applied: WORK_STATE item 3-4).
- Root 2026-10-26: scan x scale switched to the declared 300 dpi (the 4.2 mm connectors prove it; implied hole inset
  3.64 on the short edges -> owner re-check M-H1); pads.json / layout_const / board file / renders regenerated; DigiKey
  BOM now 3 lines ($2.34 / board at 5); JLC $35.85 -> total $38.19 / board at 5, $26.59 at 20. Usage cut-off: full
  hand-over in docs/WORK_STATE.md.
- OWNER 2026-10-26 (photos): playfield score sensors = mechanical lever microswitches (wire lever across each hole,
  audible click); ball-holder lip strip = 4-wire 60 LED/m 5050 analog RGB.
- Root 2026-10-26 (resumed after the usage cut-off): light redesign (Q-28) - AO3416 x4, +5V_RGB 5 A PTC (2920L500/16MR)
  + +5V_PF 3 A PTC, firmware light cap RGB 4.0 / PF 1.5 / total 5.0 A; +5V_SENS switch removed and pull-ups 2.2 k (Q-29).
  Rebuilt: ERC 0 electrical, netlist == design, BOM 75 lines 0 fail, 28 extended; JLC $37.73 + DigiKey $2.34 = $40.07 /
  board at 5, $27.12 at 20. Schematic pages re-rendered and read.
- OWNER 2026-10-26: 5 boards tops (no quantity analysis beyond that); SMD parts top side only unless absolutely
  critical, THT through.
- Root 2026-10-26: footprint pass - all 7 pending footprints drawn / resolved (Q-30); harness headers now genuine Molex
  and JLC-placed (Q-31), J11 latching header fixed (Q-32), playfield right-angle part fixed (Q-33), RJ45 LED polarity
  fixed (Q-34); DigiKey path removed. Rebuilt: ERC 0, netlist == design, BOM 75 lines 0 fail, 31 extended; $41.05 /
  board at 5 (one JLC order).
- OWNER 2026-10-26: start the real placement (harness headers on the scanned pads, then the groups, SMD top only);
  explain every stock passive and replicate it where still needed; ballpark for re-adding the 8 RJ11 jacks (answered:
  ~$3.5-4.5 / board, space on the bottom strip is the real cost; not added).
- Root 2026-10-26: placement in the record (`scripts/place.py`, Q-37); D1 TVS polarity fixed (Q-35); speaker header
  -> 39300020 peg variant matching the stock part (Q-36); stock passive audit (Q-38, sub-agent, root spot-checked).
  ERC 0, netlist == design, BOM 0 fail, $41.07 / board at 5; DRC placement-clean.
- OWNER 2026-10-26: missing footprints / 3D models; add the 8 RJ11 jacks as on the stock board (slight shift OK);
  silk priority = connector purpose / IDs / pin maps; scatter test points; poll usage, stop at 90 %.
- Root 2026-10-26: jacks J21-J28 Molex 95501-2641 at the stock positions (Q-39, contact map provisional); silk labels +
  pin maps (Q-40); envelope / stand-in 3D models for every part (Q-41). ERC 0, netlist == design, BOM 76 lines 0 fail,
  DRC placement-clean (12 lib_footprint_mismatch = edge-silk trim + model swaps). Stopped at 85 % (5-hour) per the
  owner's 90 % rule; resume block in WORK_STATE.
- OWNER 2026-10-27: RJ11 contact map (1 = 5 V, 2 = signal to J11 pin k+2, 3 = NC, 4 = GND) wants visual proof; jacks must be
  vertical; pause RJ11 wiring / routing; connector renders must show polarity; J6 180 deg off; J8 is vertical; QA vs the
  reference board "atrocious"; route with pfr2 (+ fastroute shadow), never Freerouting; reuse the C:\work tools.
- Root 2026-10-27: vendor 3D models for every connector / switch (Q-42); J6 latch + pin map fixed (Q-43); J8 -> vertical
  26-60-4020 (Q-44); jack type / part open (Q-45); light power group re-placed from connectivity (F1 / F2 inputs up, Q4
  beside J8, Q1-Q3 drains toward J7); scripts/power_copper.py (locked +5V_IN trunk zones + via array, +5V_RGB / +5V_PF /
  LED_*_K tracks); sub-agent porting pfr2 (2-layer) + the CT / DIN-8R gates; independent connector reviewer running (Q-46).
  ERC 0, netlist == design, BOM 76 lines 0 fail ($48.95 / board at 5), placement DRC clean.
- Routing agent pass 5 (2026-10-26/27): routed-render white boxes = kicad-cli default --quality basic (render_pcb.py
  --board/--out/--views/--layer-plots, Q-54); run_stage drops = no-net NC pads (place.py unconnected-(...) nets, margin
  sweep kept 0.04, Q-55 / DECISIONS #6); 2-layer closure p8-p13 plateaued at 13 (U5 pin ring) -> owner: 4-LAYER
  (DECISIONS #7), GPIO pin-escape remap (#8), J2 to the lower right, no filled vias (#9), F3 jack PTC (#10), TODO-2/3
  (Q-56, sub-agent). 4-layer from scratch: q1 4 -> 2 open, targeted FLT escape (power_copper) + local QSPI rip + --srr
  -> q2 0 open, DRC clean; 15-min cleanup box -> q3, adopted into hardware/main. Renders renders/pcb/routed-2026-10-27.
- 2026-10-27 q6 (hardware agent, coordinator QA corrections 2026-10-27b): A1-D5 applied on .runtime/route/q6 (pfr2 + gates only, every step DRC refilled + parity 0 / 0), adopted into hardware/main (q5 backup .runtime/hardware_main_backup_20261027_q5); release fab/release-2026-10-27b; renders final-2026-10-27b; QA_LOG Q-60, DECISIONS #11-R / #14-#19. Owner decisions O1-O3 open.
