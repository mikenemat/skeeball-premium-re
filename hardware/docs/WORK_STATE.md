# LIVE RESUME - 2026-10-27 ~13:35 (D2 BOM change -> release-2026-10-27c; no order placed)

CURRENT RELEASE: fab/release-2026-10-27c/ (supersedes -b). Only change: D2 = KENTO KT-0603R C2286 (basic; NCD0603R1
  C84263 is Standard-PCBA-only, order is Economic PCBA). Board = q6 + D2 fields (sha256 13729afbc822dc86..; q6 board +
  .kicad_pro backed up in .runtime/hardware_main_backup_20261027_d2kento). ERC 0, netlist 0, bom check PASS, DRC 0 errors /
  0 unconnected, CPL 199 PASS / 0 FAIL / 9 CONFIRM; gerbers = -b apart from date lines. fab_release diode polarity is by
  LCSC A / K pin names (DECISIONS #23, QA_LOG Q-61; C2286's dot marks the ANODE - order remark in the -c README).
  The q6 text below is history where it names release-b as current.
  GOTCHAS: build_schematics.py overwrites hardware/main/*.kicad_pro with a 90-byte stub (net classes / rules lost) -
  restore the full .kicad_pro after every run; the .kicad_pcb is CRLF - a Python text patch must write CRLF back.

STATE: hardware/main = q6 final (ADOPTED 2026-10-27; backup of q5 in .runtime/hardware_main_backup_20261027_q5; board
  sha256 144c86a2e7d0e69c..). KiCad DRC (refilled zones + schematic parity) 0 failing / 0 unconnected; 347 routed vias
  (+56 locked), 3096 mm routed track (F 1654 / In2 706 / B 735) + 177 mm locked (q5: 346 + 46 / 3089 + 142).
  Schematic regenerated twice (2nd = notes only, DECISIONS #17): ERC 0, netlist 0, bom.py check PASS (76 lines).
  Renders + layer plots renders/pcb/final-2026-10-27b/ (inspected as full-resolution tiles). RELEASE
  fab/release-2026-10-27b/ (gerbers + drills zip, JLC BOM, CPL 199 PASS / 0 FAIL / 9 CONFIRM J10 + J21-J28, README).
WORK ORDER RESULT (C:\work\SKEEBALL-QA-2026-10-27b\CORRECTIONS.md; QA_LOG Q-60, DECISIONS #11-R, #14-#19, CHECKPOINT q6):
  A1 DONE (In2 pour one piece, carries ~1/3; min cut 1.70-1.90 -> 4.58 mm 1 oz-eq at the J1 thermal spokes, 5.70 along
  the trunk) / A2 PARTLY (7.5 not reached) / A3 DONE / A4 DONE (0.7 / 0.44 tracks, not a zone) / A5 PARTLY (6 of 9
  +5V_SYS vias doubled, 42 segments 1.0 mm) / A6 PARTLY (U8 keeps 1 via: 4 do not fit the rules; paste windowed) / A7
  PARTLY (SW land 0.6 mm; GND loop limited by the DBV pinout) / A8 DONE (4 x 1.0 mm spokes, cut 4.58 >= 4.5) / A9 DONE
  B1-B4 DONE (R81, R82, 4.7k x 5, 510k) / B5 PARTLY (XOUT 5.5 mm F.Cu no via, R14 cannot touch pin 31) / B6 DONE (2 vias)
  / B7 DONE (C31 <-> C25 swap) / B8 B9 ACCEPTED / B10 DONE / B11 DONE. C1 DONE / C2 DONE (NationStar) / C3 C5 DONE
  (fab_release) / C4 DONE (639 strokes -> 0.15, 17 labels 1.0 mm, "* GND") / C6 C7 DONE. D1 DONE (HRO D-15, no LCSC
  footprint -> CONFIRM row; slot + peg merged, DECISIONS #14) / D2 D3 DONE / D4 DONE (BRINGUP 6) / D5 = owner O3.
OPEN OWNER DECISIONS: O1 + O2 ACCEPTED by the owner 2026-10-27 (DECISIONS #20 / #21); O3 CLOSED by the owner (caliper facts authoritative, DECISIONS #22). No open owner decisions (jack edge
  ~0.4 mm, H1-H2) - options + recommendations in the q6 report.
GOTCHAS (new, q6): place.rewrite_paste_windows is a TEXT pass (KiCad 10 FOOTPRINT.Remove(pad) corrupts SWIG) and must
  write positive sizes (a negative pad size made pcbnew.LoadBoard hang while kicad-cli still loaded the file);
  draft_native delete removes tracks / vias only - zones need pcb_redesign.remove_saved_items; a +5V_IN zone at a branch
  part makes qa_copper_landing size the branch for the trunk (5.5 A); copper_cleanup = stop after step 19 (viacur), use
  cleanup.work/snap/20; pfr2 --keepout needs a Windows path (C:/...), not /c/...
RESUME PROMPT (paste after the reset):
  Resume SBC-1 in C:\work\skeeball-premium-re\hardware: read CLAUDE.md, docs/WORK_STATE.md (live block), docs/DECISIONS.md #11-R
  and #14-#19, the tail of .runtime/route/CHECKPOINT.md and fab/release-2026-10-27b/README.md. hardware/main = q6 final
  (released, not ordered). Remaining work = the owner decisions O1-O3.
OWNER RULES: 5 boards max; SMD TOP side only unless absolutely critical, THT through; deliver files (SendUserFile);
  route with pfr2 (+ fastroute shadow), never Freerouting; reuse the C:\work tools before writing new ones; every
  harness connector checked against the reference photos + independent review before the owner sees it.
OWNER ACTIONS: none. Release package ready to order (owner places the order).
NEXT (historical, pre-q5 - superseded by the live block above):
  1. RJ11 jacks DONE (Q-47 part, Q-52 contact map + J11 order): route them now (route_prep must stop removing
     J21-J28 and drop the jack-strip keep-out).
  2. Review the pfr2 candidate (gates, DRC, renders), adopt into hardware/main, then fab outputs.
  3. Connector QA vs stock DONE (Q-46): all OK except the jacks (Q-45) and J5 fit (stock plain header vs our
     friction-lock wall on -y) -> owner photos OWNER-ASKS 4-7 (P-J5, C-RJ11 tail continuity, P-J3 headroom, P-JACK).
RESUME PROCEDURE: read CLAUDE.md, this file, RUNNING-LOG tail, docs/ROUTING_PLAYBOOK.md (once written); rebuild with the
  chain above.
GOTCHAS: kicad-sch-api field positions are library defaults - add a `_FIELD_RULES` rule for a colliding new symbol;
  JLC listings can be 'not buyable' with stock > 0; search JLC by the Molex MPN WITHOUT leading zeros; molex.com
  blocks scripted fetches - use the LCSC footprint (`jlc_footprints.py`) / KiCad footprints / DigiKey parameters;
  `bom.py refresh MPN[,MPN]` (positional, no --only); write patch scripts with the file tool (heredoc apostrophes);
  KiCad python = "C:/Program Files/KiCad/10.0/bin/python.exe"; a stray bisect.py in %TEMP% breaks CPython started
  there (run with -I from another folder); EasyEDA pad numbers can disagree with the contact order (check the posts /
  latch in the render); EasyEDA model heights vary - check a cross-section profile (vendor_models FIX).
LIVE PLAN CHECKLIST:
 [x] requirements + decisions (ARCHITECTURE)   [x] MCU comparison   [x] schematic + ERC + netlist QA
 [x] BOM, all in JLC stock, dated              [x] placement plan + RJ45 study (rendered, inspected)
 [x] measurement request list                  [x] owner measurements (M-H1 -> TODO-3; M-E2 / M-E6 measured)
 [x] light-driver redesign (Q-28)              [x] project footprints (Q-30)   [x] placement (Q-37)
 [x] stock passive audit (Q-38)   [~] score jacks (Q-45: type / part / contact map open, paused)
 [x] silk labels (Q-40)   [x] vendor 3D models (Q-42)   [x] connector QA vs reference (Q-46; J5 fit open)
 [~] routing (pfr2 port running)               [ ] fab outputs          [ ] order (owner)
