"""Render the placement plan and the RJ45 zone study (SVG + PNG via cairosvg) into renders/placement/.
Owner rule: never show a render that was not rasterized and inspected - the PNGs are what gets inspected.
usage: python render_placement.py
"""
import sys
from pathlib import Path

import cairosvg

sys.path.insert(0, str(Path(__file__).parent))
import layout_const as L  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "renders" / "placement"
W, H = L.OUTLINE
FONT = "font-family='DejaVu Sans, Arial, sans-serif'"
C_BOARD, C_HARN, C_HOLE, C_ZONE, C_GRP, C_JACK = "#2f7d4a", "#e8a33d", "#555", "#2a6fdb", "#9aa3ad", "#c0392b"


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, t, size=12, anchor="start", fill="#111", weight="normal"):
    return (f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' text-anchor='{anchor}' fill='{fill}' "
            f"font-weight='{weight}' {FONT}>{esc(t)}</text>")


def rect(x, y, w, h, stroke, fill="none", dash=None, sw=1.5, op=1.0):
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return (f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' stroke='{stroke}' fill='{fill}' "
            f"fill-opacity='{op}' stroke-width='{sw}'{d}/>")


def board(ox, oy, k, holes=True, zones=True, harness=True, harness_labels=True, groups=False):
    """Board drawing at origin (ox, oy), k px/mm. Returns (svg parts, mapping fn)."""
    m = lambda x, y: (ox + x * k, oy + y * k)                      # noqa: E731
    p = [rect(ox, oy, W * k, H * k, C_BOARD, "#eaf4ec", sw=2)]
    if zones:
        for name, (x0, y0, x1, y1) in L.ZONES.items():
            a, b = m(x0, y0), m(x1, y1)
            p.append(rect(a[0], a[1], b[0] - a[0], b[1] - a[1], C_ZONE, "#2a6fdb", dash="6,4", op=0.06))
    if groups:
        for i, (name, (x0, y0, x1, y1, _)) in enumerate(L.GROUPS.items(), 1):
            a, b = m(x0, y0), m(x1, y1)
            p.append(rect(a[0], a[1], b[0] - a[0], b[1] - a[1], C_GRP, "#9aa3ad", op=0.18, sw=1))
            p.append(text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 4, f"G{i}", 11, "middle", "#333", "bold"))
    if harness:
        for name, (x0, y0, x1, y1) in L.HARNESS.items():
            a, b = m(x0, y0), m(x1, y1)
            p.append(rect(a[0], a[1], b[0] - a[0], b[1] - a[1], "#b06d00", C_HARN, op=0.55, sw=1.2))
    if harness:
        for cname, pads in L.PADS.items():
            for i, (px, py) in enumerate(pads):
                c = m(px, py)
                first = i == 0 and cname not in ("J18_ANCHORS", "BUTTONS_GND", "PLAYFIELD")
                first = first or (cname == "PLAYFIELD" and i == 1)
                p.append(f"<circle cx='{c[0]:.1f}' cy='{c[1]:.1f}' r='{0.9 * k:.1f}' fill='{'#7a2a20' if first else 'white'}' "
                         f"stroke='#7a2a20' stroke-width='1'/>")
    if holes:
        for name, (x, y) in L.HOLES.items():
            c = m(x, y)
            p.append(f"<circle cx='{c[0]:.1f}' cy='{c[1]:.1f}' r='{L.HOLE_DRILL / 2 * k:.1f}' fill='white' stroke='{C_HOLE}' "
                     f"stroke-width='1.5'/>")
    return p, m


def placement_plan():
    k = 7.0
    ox, oy = 250, 110
    p, m = board(ox, oy, k, groups=True)
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='1640' height='800' viewBox='0 0 1640 800'>",
           "<rect width='1640' height='800' fill='white'/>",
           text(30, 38, "SBC-1 placement plan - outline, holes and connector pads measured", 22, weight="bold"),
           text(30, 62, f"Outline {W} x {H} mm and corner holes ({L.HOLE_DRILL} mm, {L.MEASURED['hole_inset_x']} mm "
                        f"from the short / {L.MEASURED['hole_inset_y']} mm from the long edges) = owner "
                        "calipers 2026-10-26. Connector pads (dots) = owner's 300 dpi bottom scan, +-0.1 mm.",
                        13, fill="#444"),
           text(30, 80, "Scan mapped onto the holes; bodies drawn around the pads. Origin = top-left, component side "
                        "up; the J11 score-harness edge is the bottom. Pin 1 pads are drawn filled.", 13, fill="#444")]
    out += p
    # the owner's RJ45 pick + the W5500 group that sits with it
    jz, jo = L.RJ45_PICK
    x0, y0, x1, y1 = L.RJ45_FITS[(jz, jo)]
    ja, jb = m(x0, y0), m(x1, y1)
    out.append(rect(ja[0], ja[1], jb[0] - ja[0], jb[1] - ja[1], C_JACK, C_JACK, op=0.35, sw=2))
    out.append(text((ja[0] + jb[0]) / 2, (ja[1] + jb[1]) / 2 + 4, "RJ45", 12, "middle", "#7a1a10", "bold"))
    wx0, wy0, wx1, wy1 = L.W5500_GROUP[jz]
    wa, wb = m(wx0, wy0), m(wx1, wy1)
    out.append(rect(wa[0], wa[1], wb[0] - wa[0], wb[1] - wa[1], C_GRP, "#9aa3ad", op=0.18, sw=1))
    out.append(text((wa[0] + wb[0]) / 2, (wa[1] + wb[1]) / 2 + 4, "G13", 11, "middle", "#333", "bold"))
    # harness labels with leaders, placed outside the board
    lab = {
        "PWR": ("top", 0), "J18 micro-USB": ("top", 0), "PLAYFIELD LIGHTS": ("left", 0),
        "RGB LIGHTS": ("left", 0), "BUTTONS": ("left", 0), "J11 SCORE SENSORS": ("bottom", 0),
        "J20 SPEAKER": ("right", 0),
    }
    for name, (x0, y0, x1, y1) in L.HARNESS.items():
        side, _ = lab[name]
        a, b = m(x0, y0), m(x1, y1)
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if side == "left":
            tx, ty = ox - 18, cy + 4
            out.append(f"<line x1='{a[0]:.1f}' y1='{cy:.1f}' x2='{tx + 4:.1f}' y2='{cy:.1f}' stroke='#b06d00'/>")
            out.append(text(tx, ty, name, 13, "end", "#7a4a00", "bold"))
        elif side == "top":
            tx, ty = cx, oy - 16
            out.append(f"<line x1='{cx:.1f}' y1='{a[1]:.1f}' x2='{cx:.1f}' y2='{ty + 4:.1f}' stroke='#b06d00'/>")
            out.append(text(tx, ty, name, 13, "middle", "#7a4a00", "bold"))
        elif side == "right":
            tx, ty = ox + W * k + 18, cy + 4
            out.append(f"<line x1='{b[0]:.1f}' y1='{cy:.1f}' x2='{tx - 4:.1f}' y2='{cy:.1f}' stroke='#b06d00'/>")
            out.append(text(tx, ty, name, 13, "start", "#7a4a00", "bold"))
        else:
            tx, ty = cx, oy + H * k + 26
            out.append(f"<line x1='{cx:.1f}' y1='{b[1]:.1f}' x2='{cx:.1f}' y2='{ty - 13:.1f}' stroke='#b06d00'/>")
            out.append(text(tx, ty, name + " (9-way latching, pin 1 '*' at the right end)", 13, "middle", "#7a4a00", "bold"))
    # zone labels (inside, top-left corner of each zone)
    for name, (x0, y0, x1, y1) in L.ZONES.items():
        a = m(x0, y0)
        out.append(text(a[0], a[1] - 4, "RJ45 zone " + name.split(":")[0], 12, "start", C_ZONE, "bold"))
    # hole labels: small, offset inward
    for name, (x, y) in L.HOLES.items():
        c = m(x, y)
        short = name.split(" ")[0]
        dx = 1.6 * k + 4 if x < W / 2 else -(1.6 * k + 4)
        out.append(text(c[0] + dx, c[1] + 4, short, 11, "start" if dx > 0 else "end", "#333"))
    # legend + group list
    lx, ly = ox + W * k + 150, 130
    out.append(text(lx, ly, "Legend", 15, weight="bold"))
    items = [(C_HARN, "harness connector (kept at the stock spot)"), ("#9aa3ad", "proposed function group G#"),
             (C_ZONE, "allowed RJ45 zone (owner)")]
    for i, (c, t) in enumerate(items):
        y = ly + 22 + i * 22
        out.append(rect(lx, y - 12, 18, 14, c, c, op=0.5, sw=1))
        out.append(text(lx + 26, y, t, 13))
    y = ly + 22 + 3 * 22
    out.append(f"<circle cx='{lx + 9}' cy='{y - 5}' r='7' fill='white' stroke='{C_HOLE}' stroke-width='1.5'/>")
    out.append(text(lx + 26, y, "corner hole 3.57 mm (nylon stand-off stud; measured)", 13))
    y += 34
    out.append(text(lx, y, "Function groups", 15, weight="bold"))
    for i, (name, g) in enumerate(L.GROUPS.items(), 1):
        y += 20
        out.append(text(lx, y, f"G{i}  {name}", 12))
    y += 20
    out.append(text(lx, y, "G13  W5500 + 25 MHz + MDI terminations (at the RJ45)", 12))
    y += 30
    out.append(text(lx, y, "Removed vs stock: 8 modular jacks, J2, J3,", 12, fill="#444"))
    out.append(text(lx, y + 17, "J5/J7 footprints, J19 (owner 2026-10-26).", 12, fill="#444"))
    out.append(text(lx, y + 34, "The freed jack strip holds G8-G12.", 12, fill="#444"))
    out.append(text(lx, y + 58, "RJ45 (red) = owner pick: zone a, vertical HanRun", 12, fill="#7a2a20"))
    out.append(text(lx, y + 75, "HR963380AE; G13 = W5500 + 25 MHz + terminations.", 12, fill="#7a2a20"))
    out.append(text(lx, y + 99, "Stock inner holes are not used and not kept (owner).", 12, fill="#444"))
    out.append(text(lx, y + 123, "Confirmed by continuity: PWR 1 = 5 V / 2 NC / 3 GND;", 12, fill="#444"))
    out.append(text(lx, y + 140, "RGB pin 1 (left) = +5 V; Playfield lower pin = +5 V.", 12, fill="#444"))
    out.append("</svg>")
    return "\n".join(out)


def rj45_study():
    k = 3.6
    pw, ph = 720, 400
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{2 * pw + 40}' height='{2 * ph + 130}' "
           f"viewBox='0 0 {2 * pw + 40} {2 * ph + 130}'>", f"<rect width='100%' height='100%' fill='white'/>",
           text(24, 36, "RJ45 location study - 2 allowed zones x 2 orientations (owner picks)", 22, weight="bold"),
           text(24, 60, "Outline + holes measured (owner); harness bodies photo +-1 mm. Gaps are body-edge to nearest "
                        "feature edge (holes as 3.2 mm circles).", 13, fill="#444")]
    panels = [("a", "RA"), ("a", "V"), ("b", "RA"), ("b", "V")]
    for i, (z, o) in enumerate(panels):
        px0 = 20 + (i % 2) * (pw + 0)
        py0 = 80 + (i // 2) * ph
        out.append(rect(px0, py0, pw - 10, ph - 10, "#ccc", "none", sw=1))
        ox, oy = px0 + 20, py0 + 68
        p, m = board(ox, oy, k, harness=True, zones=True)
        out += p
        tags = {"PWR": "PWR", "J18 micro-USB": "USB", "PLAYFIELD LIGHTS": "PF", "RGB LIGHTS": "RGB",
                "BUTTONS": "BTN", "J11 SCORE SENSORS": "J11", "J20 SPEAKER": "SPK"}
        for hn, (hx0, hy0, hx1, hy1) in L.HARNESS.items():
            ha, hb = m(hx0, hy0), m(hx1, hy1)
            out.append(text((ha[0] + hb[0]) / 2, (ha[1] + hb[1]) / 2 + 3.5, tags[hn], 9, "middle", "#6b4200", "bold"))
        x0, y0, x1, y1 = L.RJ45_FITS[(z, o)]
        a, b = m(x0, y0), m(x1, y1)
        out.append(rect(a[0], a[1], b[0] - a[0], b[1] - a[1], C_JACK, C_JACK, op=0.35, sw=2))
        jack = L.RJ45[o]
        title = (f"Zone {z} - {'right-angle' if o == 'RA' else 'vertical'}: "
                 f"{jack['part'].split(' (')[0]}")
        out.append(text(px0 + 12, py0 + 26, title, 15, weight="bold"))
        # arrow showing the cable entry direction
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        if o == "RA":
            if z == "a":
                out.append(f"<line x1='{cx:.1f}' y1='{a[1] - 2:.1f}' x2='{cx:.1f}' y2='{a[1] - 14:.1f}' "
                           f"stroke='{C_JACK}' stroke-width='3'/>")
            else:
                out.append(f"<line x1='{b[0] + 2:.1f}' y1='{cy:.1f}' x2='{b[0] + 14:.1f}' y2='{cy:.1f}' "
                           f"stroke='{C_JACK}' stroke-width='3'/>")
        else:
            out.append(f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='6' fill='none' stroke='{C_JACK}' stroke-width='3'/>")
            out.append(f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='1.8' fill='{C_JACK}'/>")
        # clearance list to the right of the board
        tx = ox + W * k + 30
        c = L.clearances(z, o)
        near = sorted(c.items(), key=lambda t: t[1])[:4]
        ty = oy + 14
        out.append(text(tx, ty, f"body {jack['body'][0]} x {jack['body'][1]} mm,", 12))
        out.append(text(tx, ty + 16, f"height {jack['height']} mm, faces {jack['faces']}", 12))
        out.append(text(tx, ty + 34, f"x {x0:.1f}-{x1:.1f}, y {y0:.1f}-{y1:.1f} mm", 12))
        out.append(text(tx, ty + 58, "nearest features (gap):", 12, weight="bold"))
        for j, (n, v) in enumerate(near):
            short = n.split(" (")[0]
            out.append(text(tx, ty + 76 + j * 16, f"{short}: {v:.1f} mm", 12))
        note = {("a", "RA"): ["cable exits the TOP edge (with the", "USB + power plugs)"],
                ("a", "V"): ["plug from above: needs ~17 mm body", "+ plug + cable bend clear overhead"],
                ("b", "RA"): ["cable exits the RIGHT edge:", "check the room to the side wall"],
                ("b", "V"): ["plug from above: needs ~17 mm body", "+ plug + cable bend clear overhead"]}[(z, o)]
        for j, line in enumerate(note):
            out.append(text(tx, ty + 150 + j * 16, line, 12, fill="#7a2a20"))
    out.append("</svg>")
    return "\n".join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, svg, w in (("placement_plan", placement_plan(), 1640), ("rj45_zone_study", rj45_study(), 1480)):
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(OUT / f"{name}.png"), output_width=w)
        print("wrote", OUT / f"{name}.png")


if __name__ == "__main__":
    main()
