"""3D renders of the main board (kicad-cli pcb render) -> renders/pcb/<stage>/sbc1-<stage>-{top,iso}.png.
Owner rule: every render is rasterized and inspected before it is shown (CLAUDE.md drawing QA).
usage: python render_pcb.py [stage] [--board PCB] [--out DIR] [--views top,bottom,side-top-edge,...] [--layer-plots]
       --layer-plots: also F.Cu / In1.Cu / In2.Cu / B.Cu plots (kicad-cli export svg + cairosvg, board area, white bg)
       stage = placement (default) | routed | any name (file prefix); routed scratch candidates:
       python render_pcb.py p8 --board .runtime/route/p8/best/skeeball-controller.kicad_pcb --out .runtime/route/p8/render
Always --quality high: kicad-cli's default 'basic' draws the white connector housings as flat white boxes.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "hardware" / "main" / "skeeball-controller.kicad_pcb"
KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
VIEWS = {"top": ["--side", "top", "--zoom", "1.05"],
         "bottom": ["--side", "bottom", "--zoom", "1.05"],
         "iso": ["--side", "top", "--rotate", "-40,0,30", "--perspective", "--zoom", "0.95"],
         # close views of the connector faces (owner 2026-10-26: latches / keys / polarity must be readable)
         "near-top-edge": ["--side", "top", "--rotate", "-60,0,0", "--perspective", "--zoom", "1.6", "--pan", "0,-2,0"],
         "near-bottom-edge": ["--side", "top", "--rotate", "-60,0,180", "--perspective", "--zoom", "1.6", "--pan",
                              "0,-2,0"],
         # each edge dead on, orthographic (owner 2026-10-27): connector faces / overhangs / heights
         "side-top-edge": ["--side", "back", "--zoom", "2.2"],
         "side-bottom-edge": ["--side", "front", "--zoom", "2.2"],
         "side-left-edge": ["--side", "left", "--zoom", "2.7"],
         "side-right-edge": ["--side", "right", "--zoom", "2.7"]}   # 2.7: J3 top clear of the frame


def main():
    # --board / --out (2026-10-27): routed scratch candidates (.runtime/route/RUN/best) render through THIS script, so
    # they get the same --quality high as the placement renders. Root cause of the "white box" connectors in the p7
    # routed render: a bare `kicad-cli pcb render` defaults to --quality basic, which draws the white nylon Mini-Fit /
    # KK housings (J1 / J4 / J6 / J7 / J8) as flat unshaded white - the vendor STEPs DID resolve.
    # --views a,b,c limits the set (e.g. top,side-top-edge,side-bottom-edge,side-left-edge,side-right-edge).
    argv = sys.argv[1:]

    def opt(name, default=None):
        if name in argv:
            i = argv.index(name)
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        return default
    board = Path(opt("--board", str(BOARD))).resolve()
    out_opt = opt("--out")
    views = opt("--views")
    layer_plots = "--layer-plots" in argv
    if layer_plots:
        argv.remove("--layer-plots")
    stage = argv[0] if argv else "placement"
    short = {"placement": "place"}.get(stage, stage)
    out = Path(out_opt).resolve() if out_opt else ROOT / "renders" / "pcb" / stage
    out.mkdir(parents=True, exist_ok=True)
    for name, args in VIEWS.items():
        if views and name not in views.split(","):
            continue
        png = out / f"sbc1-{short}-{name}.png"
        h = "900" if name.startswith("side") else "1800"            # edge views: a wide strip
        r = subprocess.run([KCLI, "pcb", "render", "-o", str(png), "-w", "3200", "-h", h, "--quality", "high",
                            "--background", "opaque", *args, str(board)], capture_output=True, text=True)
        bad = [ln for ln in (r.stdout + r.stderr).splitlines()
               if any(k in ln.lower() for k in ("could not", "not found", "error", "cannot"))]
        if r.returncode or bad:
            raise SystemExit(f"render {name} failed ({r.returncode}): {bad[:5]}")
        print("render:", png)
    if layer_plots:
        plot_layers(board, out, short)


# copper layer plots (owner 2026-10-27, 4-layer): each copper layer + the outline, board area only, as PNG
LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")


def plot_layers(board, out, short):
    import cairosvg
    for L in LAYERS:
        svg = out / f"sbc1-{short}-layer-{L.replace('.', '_')}.svg"
        r = subprocess.run([KCLI, "pcb", "export", "svg", "--layers", f"{L},Edge.Cuts", "--mode-single",
                            "--page-size-mode", "2", "--exclude-drawing-sheet", "--check-zones", "--drill-shape-opt", "2",
                            "-o", str(svg), str(board)], capture_output=True, text=True)
        if r.returncode or not svg.exists():
            raise SystemExit(f"layer plot {L} failed: {(r.stdout + r.stderr)[-400:]}")
        png = svg.with_suffix(".png")
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=3200, background_color="white")
        svg.unlink()
        print("layer plot:", png)


if __name__ == "__main__":
    main()
