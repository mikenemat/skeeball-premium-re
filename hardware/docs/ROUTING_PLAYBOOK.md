# SBC-1 routing playbook

The one description of how the SBC-1 main board is routed, cleaned and checked. Router and gates are PORTED, never
written here (owner 2026-10-27: "use those before reinventing the wheel"; never Freerouting, never a self-written
router). Router = DIN-8R pfr2 (`tools/pfr2`, from `C:\work\din-relay-8ch\tools\pfr2`); gates + cleanup = the
din8r-chassis-thermal (CT) ports in `scripts/` (CT ported them from DIN-8R). Every ported file names its origin in
line 1. Scratch candidates live in `.runtime/route/<RUN>/`; hardware/main is never routed in place.

## 1. Chain (commands)
```
python scripts/pcb_build.py                                        # outline + holes (lead)
"C:/Program Files/KiCad/10.0/bin/python.exe" scripts/place.py      # placement + silk (lead; never twice on one board)
python scripts/route_stage.py RUN                                  # copy hardware/main -> .runtime/route/RUN/main (+ lib
                                                                   # junction), power_copper.py on the copy (LOCKED heavy
                                                                   # copper), route_prep.py (below), pcb_rules
python tools/pfr2/drive_sbc.py RUN [--stages 3] [--budget 900]     # pfr2 stages + prune + pour_stitch, copper_cleanup
python scripts/qa_drc.py .runtime/route/RUN/best/skeeball-controller.kicad_pcb --details 20
python scripts/layout_gates.py .runtime/route/RUN/best/skeeball-controller.kicad_pcb --out .runtime/route/RUN/gates \
       --drc-report .runtime/route/RUN/best/drc.json
python scripts/render_pcb.py RUN --board .runtime/route/RUN/best/skeeball-controller.kicad_pcb --out .runtime/route/RUN/render \
       --views top,side-top-edge,side-bottom-edge,side-left-edge,side-right-edge   # LOOK at every PNG
```
Never a bare `kicad-cli pcb render`: its default `--quality basic` draws the white connector housings as flat boxes
(QA_LOG Q-54); render_pcb.py renders `--quality high` and stops on a model-load error.
pfr2 planning margin = 0.04 (DECISIONS #6, sweep in QA_LOG Q-55); NC pads carry KiCad's `unconnected-(...)` nets
(place.py) - a no-net pad makes plan_check (0.2) and pfr2 (0.15) disagree and run_stage drops the joins beside it.
`scripts/local_run.py X.py` runs a script under KiCad's Python with a private profile (CT / DIN-8R pattern); absolute
paths only (it runs in scripts/).

**4-LAYER since 2026-10-27 (DECISIONS #7)**: In1.Cu = solid GND plane `GND_IN1` (never routed; pfr2 PLANE_LAYERS /
PLANE_FILL_LAYERS = In1.Cu: every GND pad drops a plain via into it), routing on F.Cu / In2.Cu / B.Cu, B.Cu GND pour
soft; pour_stitch onto In1. Rule areas cover every copper layer. Targeted closure that worked (q1 -> q2): a locked
power_copper escape for a pin the frozen power trunk walls off, rip_local of the few nets at a caged pad, then ONE pfr2
stage with `--srr 300` (srr only rips the plan's own units: useless on a finished board without a rip). copper_cleanup:
time-box it and keep the last snapshot that is DRC clean with refilled zones (`kicad-cli pcb drc --refill-zones`, the
board's own .kicad_pro beside it).

## 2. Board preparation (`scripts/route_prep.py`, idempotent)
- Paused score jacks J21-J28 (`board_const.PAUSED_REFS`) are removed from the routing board; their strip is the
  `JACK_STRIP` no-track / no-via rule area (x 9.8..107.0, y >= 69.3 - courtyards 10.22..106.58 / 69.66..). Their nets
  SC_*_J still route J5 -> conditioning parts.
- `EDGE_KEEPOUT_0..3`: 0.4 mm no-track / no-via band (copper-edge rule 0.3 mm).
- `NPTH_KEEPOUT_*`: every NPTH hole + 0.4 mm (KiCad treats NPTH holes as edges: hole clearance 0.25 / copper-edge 0.3;
  the first trial left VBUS_DBG 0.15 mm from a J10 peg).
- GND pours `GND_F` / `GND_B`, whole outline, priority 0, thermal, island removal always, FILLED before routing
  (pfr2 needs the B.Cu fill as its drop target). power_copper's +5V_IN zones are priority 2.
- `pcb_rules.apply` + `pcbnew.SaveBoard` (net classes live in the .kicad_pro; `board.Save` drops them - CT trap).

## 3. Rules (`scripts/pcb_rules.py`, `scripts/current_budget.py`)
2-layer 1.6 mm 1 oz, JLC 2-layer: vias 0.6 / 0.3 (Power5 / PowerLight 0.8 / 0.4), min track 0.15, clearance 0.15
everywhere (RP2350B QFN-80 0.4 mm pitch has 0.2 mm pad gaps), hole clearance 0.25, copper-edge 0.3, NO via fill ->
no via in any pad (qa_layout_quality NO_VIP_FP_RE = "." ; pfr2 / via_site read it from the gate source) EXCEPT the EP
thermal vias of DECISIONS #3 (route_prep.EP_VIAS, LOCKED: U5 3 x 3, U8 1, U1 2; gate VIA_INPAD_EP_PADS).
Classes: Default 0.20, Rail (+3V3 / +3V3A / +1V1 / VBUS_DBG / GND) 0.20, Power (VBUS_HOST) 0.40, Audio (AMP_OUT* /
SPK_*) 0.30, Power5 (+5V_SYS, +5V_IN) 0.50, PowerLight (+5V_RGB / +5V_PF / LED_*_K, all locked power_copper) 0.60.
current_budget (IPC-2152, dT 20 K load - DECISIONS #5 - 1 oz): +5V_IN trunk 5.5 A 4.53 mm (locked zones only), eFuse
branch D1 / C4 -> U1 2.5 A 0.97 (BRANCHES, DECISIONS #4), R1 / C5 / TP1 leaves 0.1 A; +5V_RGB 4 A 2.43, +5V_PF 1.5 A
0.36, LED_*_K / +5V_SYS 2 A 0.63, VBUS_HOST / SPK / AMP / GND drops 1 A 0.16. pfr2 routes every current net at its
required width and necks (>= class floor) only within NECK_MM (1.0) of a narrower own pad - the gate's neck rule.

## 4. pfr2 port (`tools/pfr2`, DIN-8R 2026-10-05 production flags `--exact-clock --rescue --via-policy --det --tidy`)
Copied: pfr2 / pfr_core / pfr_edt / pfr_tidy / cugraph / place_gate / via_site / dump_geom / plan_check /
native_constraints / via_merge / land_stubs / pfr_import / run_stage / open_joins / open_groups / compare_joins /
pour_stitch / draft_native (prune / add / delete / refill) / stage_loop / drive2.sh (reference) + pcb_redesign
(remove_saved_items only). Board model changes ONLY (the SBC-1 block under pfr2.py's imports):
- `RL = ALL_LAYERS = [F.Cu, B.Cu]`; no plane-only layer (`PLANE_LAYERS = ()`); `PLANE_FILL_LAYERS = (B.Cu,)` is the
  plane-net drop target: every F.Cu GND pad gets a drop via into the B.Cu GND pour; THT GND pads touch it directly.
  `SOFT_FILL_CONNECTS = False`: the F.Cu GND fill never counts as connectivity for the router (it is carved by every
  F.Cu track; DIN-8R's planes sat on unrouted inner layers).
- `CLS` = the SBC-1 classes above; `SMALL_VIA_NETS` / `NET_OVERRIDE` / `NET_FLOOR` / `RAIL_NETS` / `PWR_FAULT_NETS` /
  `SOFT_POURS` empty; `MDI_CORRIDOR = None` (its keep-out drawing is behind that flag); `FROZEN_POWER = {+5V_SYS}`;
  `ORDER_FIRST` = SBC-1 power nets; `MIN_CLR` / `MIN_W` 0.15 (DIN-8R floors 0.20); `current_budget` from scripts/.
- Untouched (no SBC-1 class triggers them): HIZ pickup areas, LINE / COM pockets, FORCE_BAND, INNER_SELV.
- place_gate `MAKER = set()` (DIN-8R ref-specific pad exceptions); pfr_import: plain vias (no fill / cap), FORCE empty,
  an empty neck_boxes list is legal; run_stage: `apply_rules` (DIN-8R DRU generator) -> `scripts/pcb_rules_apply.py`;
  draft_native prune: the never-rip set = LOCKED items (power_copper), DIN-8R m1_protect kinds dropped.
- Locked copper / zones (power_copper) are fixed obstacles and own copper (DIN-8R FORCE treatment): dump_geom carries
  them, pfr_import proves prior copper unchanged, prune never deletes them, cleanup skips locked items.
Driver `tools/pfr2/drive_sbc.py` (drive2.sh's sequence without its DIN-8R M1 lineage): pfr2 -> run_stage (plan_check,
via_merge, land_stubs, legalise, pfr_import, pcb_rules, dump) -> draft_native prune -> pour_stitch GND both ways
(F fragments onto B, B fragments onto F; 0.6 / 0.3) -> open joins; 2 stages without gain stop; best stage ->
scripts/copper_cleanup.py -> refill.

## 5. Gates (`scripts/layout_gates.py`, CT ports; exit 0 PASS / 1 FAIL / 2 cannot evaluate)
drc_coverage, copper_landing (NO UNCONNECTED PAD OR LOOSE TRACE; CLEAN: TRACK-JOG / DUP / ORPHAN / PAD-CENTRE /
TRACK-WIDTH ...), layout_quality, placement, decoupling (qa_power_layout.DECAP = SBC-1 table), twoside, silk,
footprints (`qa_footprints_board.py`: board FPIDs = design.py; PAUSED_REFS excused). Not ported: CT isolation /
crosslayer (PoE barrier) and si (CT net models). `scripts/qa_drc.py`: KiCad DRC + schematic parity, copper rules hard;
parity `missing_footprint` of PAUSED_REFS counted separately (paused, not failing).
A finding is fixed in copper / placement / rules, never by a threshold; a constant changes only with a named reason.

## 6. Traps (kept fixed)
- `pcbnew.SaveBoard` only (net classes in the .kicad_pro). KiCad 10 Python: never `board.Remove()` a locked via
  (segfault) - draft_native deletes by UUID in the saved text; `GetWidth(layer)` on vias; one LoadBoard per process.
- local_run runs scripts with cwd = scripts/: pass absolute board paths (a relative path loads None).
- NPTH holes are edges for DRC: keep-out rings (route_prep).
- hardware/main can be mid-rebuild (pcb_build ran, place.py not yet): route_stage refuses a board with < 100 parts.
- Freerouting was tried first (2026-10-26, pre-correction) and is retired: never run it here.

## 7. Shadow: fastroute (Rust Freerouting port, owner 2026-10-27: comparison only)
`.runtime/fastroute/bin/fastroute-0.1.14-windows-x64/fastroute.exe` (GitHub release v0.1.14, sha256 checked against
SHA256SUMS.txt). Run on a DSN export of the same staged board (`-de main.dsn -do main.ses --max-time=600
--report=report.json`), SES imported into a copy with the locked items restored, then the same gates. Never adopted.
