# SBC-1 Skee-Ball lane controller - rules for agents

Replacement main board for Bay Tek A5CB25502 Rev 2.2 (Skee-Ball Home Arcade Premium), 4 machines, adds wired Ethernet.
Reverse-engineering source material (owner photos, scans, measurements) lives outside this repo; the measured
results it produced are in `scripts/layout_const.py` and `docs/records/`.

Workflow, doctrine and record set follow `PCB_DESIGN_AGENT.md` (copied from `C:\work\din-relay-8ch`, section 9 below
holds this project's facts). Project rules override it where they differ.

## Standing rules
- **Generated outputs are never hand-edited.** Schematic, BOM, ORDERING, renders come from `scripts/`; change the
  generator and re-run (README "Regenerate").
- **Design of record = `scripts/design.py`.** Every part carries its MPN, maker, LCSC code and a note citing the
  vendor reference it follows. Every IC block follows its vendor reference design / datasheet typical application;
  any deviation is written in `docs/ARCHITECTURE.md` section 5 with its reason (owner 2026-10-26).
- **JLC data only via `scripts/jlc_api.py`** (copied from din-relay-8ch; never an ad-hoc scraper). Every placed part must
  be in JLC stock with >= 2 x (need + attrition); `python scripts/bom.py check` must pass. No consignment, pre-order or
  out-of-stock parts (owner 2026-10-26). The run is 5 boards max (owner): no other quantity analysis.
- **Drawing QA (owner, hard):** never present a schematic page, render or drawing that was not rasterized to PNG and
  inspected for overlapping text, clipping, wrong labels / leaders. A misaligned drawing is a defect.
- **Harness geometry is measured, not guessed.** `scripts/layout_const.py` holds the owner's calipers (outline + holes)
  and the pad centres extracted from the owner's 300 dpi bottom scan (`scripts/scan_extract.py`, +-0.1 mm). The photo
  estimate is history (RJ45 zones only).
- **Git (owner 2026-10-29):** this folder is `hardware/` of the public repo `skeeball-premium-re`. `.runtime/`,
  datasheets, vendor STEP models, vendored Python libs and API caches are git-ignored (see `README.md` Setup). Never
  commit secrets, owner-private data or stock-firmware material.
- Bounded network: timeouts <= 60 s, no CAPTCHA, stop on a block.
- **Connector QA vs the stock board (owner 2026-10-27, after four wrong connectors):** every harness connector is
  checked against the owner's reference photos - type (vertical / right-angle / top-entry), plug direction, latch /
  ramp / key side, pin 1 + order, position, overhang - with vendor 3D models rendered top + all four edges, and an
  independent reviewer agent repeats the check before the owner sees it. design.py notes are claims, not evidence.

## Owner decisions (2026-10-26)
MCU RP2350B (QFN-80; the A ran out of GPIO) + 16 MB QSPI W25Q128JV + WIZnet W5500 (SPI). No PoE (no footprint). Modular jacks + all unpopulated stock
footprints removed; J11 (9-pin) = score harness on a PLAIN 1x9 2.54 mm vertical pin header like stock (owner 2026-10-27; the friction-lock pick was wrong). Score jacks = Molex 95503-2441 4P4C top-entry, the stock part (owner 2026-10-27). Outline + holes identical to stock; added parts never grow the board.
USB-C debug = vertical receptacle, CH340-class console, flashing via SWD. Diagnostic LEDs + RESET / BOOTSEL buttons.
Lane-ID DIP x4. PWM on the existing 4 light channels only (no addressable output). Sensor 5 V + light rail protected
(cheap). No reverse-polarity circuit (keep the TVS), no expansion header, MAC from the RP2350 unique ID. No test points
(owner 2026-10-27; the labelled test points of 2026-10-26 were removed). Polymer / MLCC instead of aluminium electrolytics. Speaker gain modest
(9 dB), firmware caps volume. RJ45: zone a (model-number silk area), VERTICAL HanRun HR963380AE (owner 2026-10-26).
Cost pass 2026-10-26: swap to JLC basic / preferred only where a true drop-in exists; never ICs, connectors or
reference-specified parts; record swaps + kept-extended reasons in ORDERING.md (bom.py BASIC_SWAPS / KEPT_EXTENDED).
Every part incl. the THT harness headers is JLC-placed (genuine Molex; one JLC order = the full board; the DigiKey /
owner-fitted path was removed 2026-10-26). Placement: SMD parts on the TOP side only unless absolutely critical; THT
through (owner 2026-10-26). Footprints: `scripts/fpgen.py` from the maker drawings, cross-checked against JLC's own
footprints (`scripts/jlc_footprints.py` -> `bom/easyeda_cache/`) and the owner's scan.

## 9. PROJECT FACTS
```
PROJECT:            SBC-1 - Skee-Ball lane controller, 5 V, SELV only, 4-layer
PROJECT ROOT:       C:\work\skeeball-controller
VERSION CONTROL:    none (no Git commands)
BOARDS:             main: schematic hardware/main/skeeball-controller.kicad_sch (generated, ERC clean); PCB placed
                    (scripts/place.py) + locked heavy copper (scripts/power_copper.py), routed (pfr2), q6 adopted;
                    design of record scripts/design.py
LAYERS / STACKUP:   4-layer 1.6 mm JLC04161H-7628 (1 oz outer / 0.5 oz inner; In1 = solid GND), green, ENIG,
                    via covering Plugged (Tented not offered for this build), no epoxy fill / capping
FAB / ASSEMBLER:    JLCPCB PCBA, single-sided SMT; THT harness connectors + RJ45 by JLC THT or hand
ORDERED PARTS:      none
TOOLS:              python = CPython 3.13 ; KiCad 10.0.6 (kicad-cli) ; kicad-sch-api 0.5.5 ; cairosvg ; PyMuPDF
                    schematic = python scripts/build_schematics.py ; BOM = python scripts/bom.py build|refresh|check|report
                    footprints = python scripts/qa_footprints.py ; placement renders = python scripts/render_pcb.py
                    board = pcb_build.py -> KiCad-python place.py -> KiCad-python power_copper.py
                    3D = scripts/vendor_models.py (EasyEDA STEP per JLC C-number, fitted on pads + pin tails)
ROUTING TOOLS:      pfr2 (ported from din-relay-8ch/tools/pfr2 into tools/pfr2) + the DIN-8R / CT gates; fastroute as a
                    shadow only; NEVER Freerouting or a self-written router (owner 2026-10-27); playbook
                    docs/ROUTING_PLAYBOOK.md
RECORDS:            docs/WORK_STATE.md (live block), docs/RUNNING-LOG.md, docs/DECISIONS.md, docs/QA_LOG.md,
                    docs/ARCHITECTURE.md, docs/MEASUREMENTS_NEEDED.md, docs/PLACEMENT_PLAN.md, docs/ORDERING.md
OWNER PREFERENCES:  internal project; fastest path; equal-or-better part swaps decided by the agent
```
