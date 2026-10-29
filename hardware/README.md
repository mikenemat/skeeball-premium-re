# SBC-1 - Skee-Ball lane controller

Networked drop-in replacement for the Bay Tek **A5CB25502 Rev 2.2** main board of the Skee-Ball Home Arcade Premium:
RP2350B + 16 MB QSPI flash, WIZnet W5500 wired Ethernet, MAX98357A I2S class-D audio, USB host port for the stock
display, protected 5 V input (TVS + eFuse), PWM light drivers, USB-C debug console, lane-ID DIP. Same outline, holes and
harness connector positions as the stock board.

**Status (2026-10-29):** ordered. Five boards are in production at JLCPCB (4-layer, Economic PCBA). The KiCad board in
`hardware/main/` is the build: routed with 0 open connections and DRC clean. `fab/release-2026-10-27c/` is the
manufacturing record (Gerbers, drills, JLC BOM and CPL). Bring-up instructions are in `docs/BRINGUP.md`. The firmware is
a separate, original implementation (not in this folder yet).

| Path | What |
|---|---|
| `docs/ARCHITECTURE.md` | requirements, I/O + GPIO map, MCU comparison, every block's reference + deviations, cost |
| `docs/MEASUREMENTS_NEEDED.md` | the caliper measurements / confirmations the layout needs |
| `docs/PLACEMENT_PLAN.md` | footprints, function groups, the RJ45 zone study |
| `docs/ORDERING.md` | BOM with LCSC codes, JLC stock, price, check date (generated) |
| `docs/WORK_STATE.md` | live state + next steps; `RUNNING-LOG.md`, `QA_LOG.md`, `DECISIONS.md` |
| `scripts/design.py` | design of record (parts, nets, references) |
| `hardware/main/` | KiCad 10 project: generated schematic (6 sheets) and the routed 4-layer board |
| `hardware/lib/` | project symbols (`skeeball.kicad_sym`) and footprints (`skeeball.pretty`) |
| `bom/bom.json`, `bom/bom.html` | single-writer BOM + viewer (`python -m http.server` in `bom/`, open bom.html) |
| `renders/` | schematic PDF, footprint / placement renders, final board renders (`renders/pcb/final-2026-10-27b/`) |
| `fab/release-2026-10-27c/` | manufacturing record: Gerber + drill zip, JLC BOM, JLC CPL (rotations fitted to JLC footprints) |
| `tools/pfr2/` | the autorouter and its gate / cleanup tools used for the copper |
| `datasheets/` | vendor documents used (not committed: download them from the manufacturers) |

## Setup (what is not in the repository)
These are git-ignored, because they are third-party, machine-specific or regenerable:
- `datasheets/`: manufacturer PDFs referenced in `design.py` notes and `docs/ARCHITECTURE.md`. Download them from the
  vendors.
- `hardware/lib/3d/vendor/`: the vendor STEP models. `python scripts/vendor_models.py` fetches them by JLC part number.
  The project's own envelope models (`hardware/lib/3d/*.wrl`) are committed.
- `tools/pylib/`: shapely + numpy for KiCad's bundled Python (KiCad 10 ships without shapely). Install them with
  `"C:/Program Files/KiCad/10.0/bin/python.exe" -m pip install --target tools/pylib shapely==2.1.2 numpy`.
- `bom/.jlc_api_cache/`, `bom/easyeda_cache/`: JLC / EasyEDA API caches, rebuilt on demand.
- `.runtime/`: router runs, gate outputs, scratch boards and backups.
- `scripts/scan_extract.py` needs the 300 dpi scan of the stock board's bottom side (not published). Set `SKEEBALL_SCAN`
  to its path. Its measured output is committed in `docs/records/scan_extract/`.

Tool versions: KiCad 10.0.6 (kicad-cli + its Python for `pcbnew` scripts), CPython 3.13 with numpy, scipy, pillow,
shapely, cairosvg and kicad-sch-api 0.5.5.

## Regenerate (CPython 3.13, KiCad 10.0.6)
```
cd scripts
python symgen.py                 # hardware/lib/skeeball.kicad_sym
python build_schematics.py       # schematic + KiCad ERC gate + netlist compare against design.py
python qa_footprints.py          # every footprint resolves (or is listed as pending with its reason)
python bom.py build && python bom.py refresh && python bom.py check && python bom.py report
python mcu_survey.py             # MCU option prices (docs/records/mcu_survey)
python fpgen.py                  # hardware/lib/skeeball.pretty (project footprints)
python scan_extract.py           # harness pad centres from the owner's 300 dpi bottom scan -> docs/records/scan_extract
python jlc_footprints.py C...     # JLC / EasyEDA footprint of a C-number -> bom/easyeda_cache (footprint cross-check)
python model_gen.py              # envelope 3D models for footprints without a KiCad model -> hardware/lib/3d
python photo_estimate.py && python render_placement.py   # placement plan + RJ45 study renders
python pcb_build.py              # board file: measured outline + 4 holes (+ SVG / PNG render)
"C:/Program Files/KiCad/10.0/bin/python.exe" place.py   # netlist import + placement + silk labels + KiCad DRC
"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe" sch export pdf -o ../renders/schematic/skeeball-controller-schematic.pdf ../hardware/main/skeeball-controller.kicad_sch
```
Scripts reused from the owner's earlier din-relay-8ch project: `jlc_api.py` (unchanged), `netlist_core.py`, `gen_schematic.py`,
`qa_netlist.py`, `symgen.py` (library name / label direction / field placement adapted), the build -> ERC -> netlist QA
flow and the one-JSON / one-writer BOM.
