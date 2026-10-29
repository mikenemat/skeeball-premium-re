"""Build the SBC-1 board file hardware/main/skeeball-controller.kicad_pcb: the measured outline + the four corner holes
(owner 2026-10-26). Everything else (footprints, placement, copper) is added by later passes; nothing in the file is
hand-edited (din-relay-8ch rule). After writing, the board is exported to SVG / PNG for the mandatory visual check.
usage: python pcb_build.py
"""
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import layout_const as L  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "hardware" / "main" / "skeeball-controller.kicad_pcb"
KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
VERSION = 20260206
FP = ROOT / "hardware" / "lib" / "skeeball.pretty" / f"MountingHole_{L.HOLE_DRILL:.2f}mm.kicad_mod"


def gr_line(x0, y0, x1, y1, layer="Edge.Cuts", w=0.1):
    return (f"\t(gr_line\n\t\t(start {x0:.3f} {y0:.3f})\n\t\t(end {x1:.3f} {y1:.3f})\n\t\t(stroke\n\t\t\t(width {w})\n"
            f"\t\t\t(type default)\n\t\t)\n\t\t(layer \"{layer}\")\n\t\t(uuid \"{uuid.uuid4()}\")\n\t)\n")


def gr_text(txt, x, y, layer="Cmts.User", size=2.0):
    return (f"\t(gr_text \"{txt}\"\n\t\t(at {x:.3f} {y:.3f} 0)\n\t\t(layer \"{layer}\")\n\t\t(uuid \"{uuid.uuid4()}\")\n"
            f"\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {size} {size})\n\t\t\t\t(thickness 0.2)\n\t\t\t)\n\t\t\t(justify left)\n\t\t)\n\t)\n")


def hole_footprint(ref, x, y):
    """The project MountingHole footprint, embedded as a placed footprint."""
    body = FP.read_text(encoding="utf-8")
    name = body.split('"', 2)[1]
    inner = body[body.index("\n") + 1:body.rstrip().rfind(")")]        # everything between the header and the last ')'
    inner = inner.replace('(property "Reference" "REF**"', f'(property "Reference" "{ref}"')
    ry = 3.4 if y < 40 else -3.4                     # label toward the board centre (above H1 / H2 it fell off the board)
    inner = re.sub(r'(\(property "Reference" "[^"]*" \(at) [-\d.]+ [-\d.]+', rf'\1 0 {ry}', inner, count=1)
    return (f'\t(footprint "skeeball:{name}"\n\t\t(layer "F.Cu")\n\t\t(uuid "{uuid.uuid4()}")\n\t\t(at {x:.3f} {y:.3f})\n'
            + "\n".join("\t" + ln for ln in inner.splitlines() if ln.strip() and not ln.strip().startswith(("(version", "(generator")))
            + "\n\t)\n")


from stackup import STACKUP  # noqa: E402  JLC04161H-7628 (q5 2026-10-27)


def main():
    W, H = L.OUTLINE
    parts = [f'(kicad_pcb\n\t(version {VERSION})\n\t(generator "skeeball_pcb_build")\n\t(generator_version "1.0")\n'
             '\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n\t(paper "A4")\n'
             '\t(title_block\n\t\t(title "SBC-1 Skee-Ball lane controller")\n\t\t(rev "A-draft")\n'
             '\t\t(comment 1 "Outline + 4 corner holes = owner measurements 2026-10-26; no placement yet")\n\t)\n'
             '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(4 "In1.Cu" power)\n\t\t(6 "In2.Cu" mixed)\n\t\t(2 "B.Cu" signal)\n\t\t(9 "F.Adhes" user "F.Adhesive")\n'
             '\t\t(11 "B.Adhes" user "B.Adhesive")\n\t\t(13 "F.Paste" user)\n\t\t(15 "B.Paste" user)\n'
             '\t\t(5 "F.SilkS" user "F.Silkscreen")\n\t\t(7 "B.SilkS" user "B.Silkscreen")\n\t\t(1 "F.Mask" user)\n'
             '\t\t(3 "B.Mask" user)\n\t\t(17 "Dwgs.User" user "User.Drawings")\n\t\t(19 "Cmts.User" user "User.Comments")\n'
             '\t\t(21 "Eco1.User" user "User.Eco1")\n\t\t(23 "Eco2.User" user "User.Eco2")\n\t\t(25 "Edge.Cuts" user)\n'
             '\t\t(27 "Margin" user)\n\t\t(31 "F.CrtYd" user "F.Courtyard")\n\t\t(29 "B.CrtYd" user "B.Courtyard")\n'
             '\t\t(35 "F.Fab" user)\n\t\t(33 "B.Fab" user)\n\t)\n'
             '\t(setup\n' + STACKUP + '\t\t(pad_to_mask_clearance 0)\n\t\t(allow_soldermask_bridges_in_footprints no)\n'
             '\t\t(pcbplotparams\n\t\t\t(layerselection 0x00000000_00000000_55555555_5755f5ff)\n\t\t\t(plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000)\n'
             '\t\t\t(disableapertmacros no)\n\t\t\t(usegerberextensions no)\n\t\t\t(usegerberattributes yes)\n\t\t\t(usegerberadvancedattributes yes)\n'
             '\t\t\t(creategerberjobfile yes)\n\t\t\t(dashed_line_dash_ratio 12.000000)\n\t\t\t(dashed_line_gap_ratio 3.000000)\n'
             '\t\t\t(svgprecision 4)\n\t\t\t(plotframeref no)\n\t\t\t(mode 1)\n\t\t\t(useauxorigin no)\n\t\t\t(hpglpennumber 1)\n'
             '\t\t\t(hpglpenspeed 20)\n\t\t\t(hpglpendiameter 15.000000)\n\t\t\t(pdf_front_fp_property_popups yes)\n'
             '\t\t\t(pdf_back_fp_property_popups yes)\n\t\t\t(pdf_metadata yes)\n\t\t\t(pdf_single_document no)\n\t\t\t(dxfpolygonmode yes)\n'
             '\t\t\t(dxfimperialunits yes)\n\t\t\t(dxfusepcbnewfont yes)\n\t\t\t(psnegative no)\n\t\t\t(psa4output no)\n'
             '\t\t\t(plot_black_and_white yes)\n\t\t\t(sketchpadsonfab no)\n\t\t\t(plotpadnumbers no)\n\t\t\t(hidednponfab no)\n'
             '\t\t\t(sketchdnponfab yes)\n\t\t\t(crossoutdnponfab yes)\n\t\t\t(subtractmaskfromsilk no)\n\t\t\t(outputformat 1)\n'
             '\t\t\t(mirror no)\n\t\t\t(drillshape 1)\n\t\t\t(scaleselection 1)\n\t\t\t(outputdirectory "")\n\t\t)\n\t)\n'
             '\t(net 0 "")\n']
    # outline (square corners, owner M-O2)
    parts += [gr_line(0, 0, W, 0), gr_line(W, 0, W, H), gr_line(W, H, 0, H), gr_line(0, H, 0, 0)]
    for ref, (x, y) in L.HOLES.items():
        parts.append(hole_footprint(ref, x, y))
    # reference notes for the layout pass (User.Comments)
    parts.append(gr_text(f"SBC-1 outline {W} x {H} mm, holes {L.HOLE_DRILL} mm at {L.MEASURED['hole_inset_x']} mm (x) / "
                         f"{L.MEASURED['hole_inset_y']} mm (y) in (owner 2026-10-26); connector pad centres from the "
                         "300 dpi bottom scan (+-0.1 mm)", 2.0, H + 4.0))
    # no scan-guide circles at the scanned pads (TODO-2, owner 2026-10-26: on Cmts.User they rendered light-blue like
    # B.Cu and read as offset copper rings); the harness body boxes below stay as layout guides
    for name, (x0, y0, x1, y1) in L.HARNESS.items():
        parts += [gr_line(x0, y0, x1, y0, "Cmts.User", 0.1), gr_line(x1, y0, x1, y1, "Cmts.User", 0.1),
                  gr_line(x1, y1, x0, y1, "Cmts.User", 0.1), gr_line(x0, y1, x0, y0, "Cmts.User", 0.1),
                  gr_text(name, x0 + 0.5, y0 + 1.6, "Cmts.User", 1.2)]
    parts.append(")\n")
    OUT.write_text("".join(parts), encoding="utf-8")
    print("wrote", OUT)
    svg = ROOT / "renders" / "pcb"
    svg.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([KCLI, "pcb", "export", "svg", "--layers", "Edge.Cuts,Cmts.User,F.Cu,F.SilkS", "--page-size-mode", "2",
                        "--exclude-drawing-sheet", "-o", str(svg / "sbc1-outline.svg"), str(OUT)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    print("svg export:", r.returncode, (r.stdout + r.stderr).strip()[-300:])
    import cairosvg
    cairosvg.svg2png(url=str(svg / "sbc1-outline.svg"), write_to=str(svg / "sbc1-outline.png"), output_width=1400,
                     background_color="white")
    print("png:", svg / "sbc1-outline.png")


if __name__ == "__main__":
    main()
