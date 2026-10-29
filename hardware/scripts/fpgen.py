"""Generate the project footprint library hardware/lib/skeeball.pretty (pattern from din-relay-8ch/scripts/fpgen.py).
Every land pattern below cites its source: the maker's drawing where it has one (datasheets/dl/), cross-checked against
the LCSC / EasyEDA footprint JLC places with (scripts/jlc_footprints.py, bom/easyeda_cache/) and, for the harness
headers, against the owner's 300 dpi scan of the stock board (docs/records/scan_extract/pads.json).
KiCad frame: mm, y down, component side; THT connectors have pin 1 at the origin, SMD parts are centred.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "hardware" / "lib" / "skeeball.pretty"
VERSION = 20260206
SILK_W, FAB_W, CRT_W = 0.12, 0.10, 0.05


def mounting_hole(drill, name=None):
    """Plated-free mounting hole for the owner's nylon stand-off studs (drill = measured 3.57 mm, M-H2)."""
    name = name or f"MountingHole_{drill:.2f}mm"
    r = drill / 2 + 0.8
    return name, f'''(footprint "{name}"
	(version {VERSION})
	(generator "skeeball_fpgen")
	(generator_version "1.0")
	(layer "F.Cu")
	(descr "Mounting hole {drill:.2f} mm, no annular ring (nylon snap-in stand-off stud; owner measurement 2026-10-26)")
	(tags "mounting hole {drill:.2f}mm")
	(attr exclude_from_pos_files exclude_from_bom)
	(property "Reference" "REF**" (at 0 {-r - 1.2:.2f} 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
	(property "Value" "{name}" (at 0 {r + 1.2:.2f} 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
	(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))
	(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1.27 1.27) (thickness 0.15))))
	(fp_circle (center 0 0) (end {r:.2f} 0) (stroke (width 0.15) (type solid)) (fill no) (layer "Cmts.User"))
	(fp_circle (center 0 0) (end {r + 0.5:.2f} 0) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
	(pad "" np_thru_hole circle (at 0 0) (size {drill:.2f} {drill:.2f}) (drill {drill:.2f}) (layers "*.Cu" "*.Mask"))
)
'''


# ---- small s-expression helpers ------------------------------------------------------------------------------------
def f(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if v != 0 else "0"


def tht(num, x, y, w, h, drill, shape="oval", slot=None, paste_margin=None):
    """Plated through-hole pad; slot = (dx, dy) gives an oval drill; paste_margin (mm) = pin-in-paste: a top paste
    aperture of the pad size grown by that margin (reflow fills the barrel from the top)."""
    dr = f"(drill oval {f(slot[0])} {f(slot[1])})" if slot else f"(drill {f(drill)})"
    rr = " (roundrect_rratio 0.15)" if shape == "roundrect" else ""
    lay = '"*.Cu" "*.Mask"' if paste_margin is None else '"*.Cu" "*.Mask" "F.Paste"'
    pm = "" if paste_margin is None else f" (solder_paste_margin {f(paste_margin)})"
    return (f'\t(pad "{num}" thru_hole {shape} (at {f(x)} {f(y)}) (size {f(w)} {f(h)}) {dr} '
            f'(layers {lay}){rr}{pm})\n')


def npth(x, y, d, slot=None):
    if slot:
        return (f'\t(pad "" np_thru_hole oval (at {f(x)} {f(y)}) (size {f(slot[0])} {f(slot[1])}) '
                f'(drill oval {f(slot[0])} {f(slot[1])}) (layers "*.Cu" "*.Mask"))\n')
    return f'\t(pad "" np_thru_hole circle (at {f(x)} {f(y)}) (size {f(d)} {f(d)}) (drill {f(d)}) (layers "*.Cu" "*.Mask"))\n'


def smd(num, x, y, w, h, shape="roundrect"):
    rr = " (roundrect_rratio 0.15)" if shape == "roundrect" else ""
    return (f'\t(pad "{num}" smd {shape} (at {f(x)} {f(y)}) (size {f(w)} {f(h)}) '
            f'(layers "F.Cu" "F.Paste" "F.Mask"){rr})\n')


def rect(x0, y0, x1, y1, layer, w):
    return (f'\t(fp_rect (start {f(x0)} {f(y0)}) (end {f(x1)} {f(y1)}) (stroke (width {w}) (type solid)) '
            f'(fill no) (layer "{layer}"))\n')


def line(x0, y0, x1, y1, layer="F.SilkS", w=SILK_W):
    return f'\t(fp_line (start {f(x0)} {f(y0)}) (end {f(x1)} {f(y1)}) (stroke (width {w}) (type solid)) (layer "{layer}"))\n'


def text(kind, s, x, y, layer, hide=False):
    h = " (hide yes)" if hide else ""
    return (f'\t(property "{kind}" "{s}" (at {f(x)} {f(y)} 0) (layer "{layer}"){h} '
            f'(effects (font (size 1 1) (thickness 0.15))))\n')


def silk_box(x0, y0, x1, y1, pads, gap=0.3):
    """Silk rectangle 0.11 mm outside the body, with every segment cut where it would cross a pad's copper + gap."""
    x0, y0, x1, y1 = x0 - 0.11, y0 - 0.11, x1 + 0.11, y1 + 0.11
    out = ""
    for a, b, horiz, c in ((x0, x1, True, y0), (x0, x1, True, y1), (y0, y1, False, x0), (y0, y1, False, x1)):
        cuts = []
        for (px, py, pw, ph) in pads:
            lo, hi, olo, ohi = ((px - pw / 2, px + pw / 2, py - ph / 2, py + ph / 2) if horiz
                                else (py - ph / 2, py + ph / 2, px - pw / 2, px + pw / 2))
            if olo - gap <= c <= ohi + gap:
                cuts.append((lo - gap, hi + gap))
        segs, cur = [], a
        for lo, hi in sorted(cuts):
            if lo > cur:
                segs.append((cur, min(lo, b)))
            cur = max(cur, hi)
        if cur < b:
            segs.append((cur, b))
        for s0, s1 in segs:
            if s1 - s0 > 0.2:
                out += line(s0, c, s1, c) if horiz else line(c, s0, c, s1)
    return out


def footprint(name, descr, tags, attr, body, pads_txt, pad_boxes, pin1, extra="", ref_y=None, val_y=None, crt=0.5):
    """body = (x0, y0, x1, y1) on F.Fab; courtyard = body U pads + 0.5 mm (connectors); pin1 = (x, y) silk mark."""
    bx0, by0, bx1, by1 = body
    cx0 = min([bx0] + [p[0] - p[2] / 2 for p in pad_boxes]) - crt
    cy0 = min([by0] + [p[1] - p[3] / 2 for p in pad_boxes]) - crt
    cx1 = max([bx1] + [p[0] + p[2] / 2 for p in pad_boxes]) + crt
    cy1 = max([by1] + [p[1] + p[3] / 2 for p in pad_boxes]) + crt
    cx0, cy0, cx1, cy1 = (round(v * 20) / 20 for v in (cx0, cy0, cx1, cy1))       # 0.05 mm courtyard grid
    mid = (bx0 + bx1) / 2
    s = (f'(footprint "{name}"\n\t(version {VERSION})\n\t(generator "skeeball_fpgen")\n\t(generator_version "1.0")\n'
         f'\t(layer "F.Cu")\n\t(descr "{descr}")\n\t(tags "{tags}")\n')
    s += text("Reference", "REF**", mid, cy0 - 0.8 if ref_y is None else ref_y, "F.SilkS")
    s += text("Value", name, mid, cy1 + 0.8 if val_y is None else val_y, "F.Fab")
    s += text("Datasheet", "", 0, 0, "F.Fab", hide=True)
    s += text("Description", "", 0, 0, "F.Fab", hide=True)
    s += f"\t(attr {attr})\n"
    s += rect(bx0, by0, bx1, by1, "F.Fab", FAB_W)
    s += rect(cx0, cy0, cx1, cy1, "F.CrtYd", CRT_W)
    s += silk_box(bx0, by0, bx1, by1, pad_boxes)
    px, py = pin1
    s += f'\t(fp_circle (center {f(px)} {f(py)}) (end {f(px + 0.25)} {f(py)}) (stroke (width {SILK_W}) (type solid)) (fill solid) (layer "F.SilkS"))\n'
    fs = min(1.0, round(0.25 * (by1 - by0), 1))                                    # Fab reference fits the body
    s += (f'\t(fp_text user "${{REFERENCE}}" (at {f(mid)} {f((by0 + by1) / 2)} 0) (layer "F.Fab") '
          f'(effects (font (size {fs} {fs}) (thickness {round(0.15 * fs, 2)}))))\n')
    s += extra + pads_txt + ")\n"
    return name, s


# ---- the project footprints ----------------------------------------------------------------------------------------
def minifit_1x04_vertical():
    """Molex Mini-Fit Jr 39-30-1049 (1x4 vertical, snap-in peg PCB lock), JLC C587488.
    Pins / pegs: LCSC footprint CONN-TH_4P-P4.20_39301049 (pin 1 at +6.3, pegs (-6.3, -3.85) and (4.2, 5.55), dia 3.0)
    turned 180 deg so pin 1 is the origin and the row runs +x; the owner's scan of the stock board shows the same two
    filled peg holes at (+1.96, -5.19) / (+12.39, +4.03) from pin 1 (+-0.2). Pin drill 1.4 / pad 2.7 x 3.3 = KiCad's
    Mini-Fit Jr 5566 vertical (Molex drawing 039281043). Body = the LCSC silk outline (18.04 x 13.08)."""
    pins = [(k + 1, 4.2 * k, 0.0) for k in range(4)]
    pads = "".join(tht(n, x, y, 2.7, 3.3, 1.4, "roundrect" if n == 1 else "oval") for n, x, y in pins)
    pads += npth(2.1, -5.55, 3.0) + npth(12.6, 3.85, 3.0)
    boxes = [(x, y, 2.7, 3.3) for _, x, y in pins] + [(2.1, -5.55, 3.0, 3.0), (12.6, 3.85, 3.0, 3.0)]
    return footprint("Molex_Mini-Fit_Jr_39-30-1049_1x04_P4.20mm_Vertical",
                     "Molex Mini-Fit Jr single row vertical header 39-30-1049, 4 circuits, snap-in peg PCB lock "
                     "(LCSC C587488 footprint; pegs confirmed on the owner's stock-board scan)",
                     "Molex Mini-Fit Jr 5566 single row vertical 39301049", "through_hole",
                     (-2.72, -7.33, 15.32, 5.75), pads, boxes, (-2.0, 2.3))


def minifit_1x03_horizontal():
    """Molex Mini-Fit Jr 39-30-3035 (1x3 right-angle, snap-in peg PCB lock), JLC C505179.
    LCSC footprint CONN-TH_39303035: pins 4.2 apart, pegs dia 3.0 under pins 1 and 3, 7.3 toward the mating face, body
    1.10 .. 13.55 from the pin row; turned 180 deg (pin 1 = origin, row +x, mating face toward -y = KiCad's 5569
    convention). Owner scan: pegs 7.15 +-0.15 from the pins under pins 1 and 3. Pin drill 1.8 / pad 2.7 x 3.7 = KiCad's
    Mini-Fit Jr 5569 right-angle (Molex drawing 039300020)."""
    pins = [(k + 1, 4.2 * k, 0.0) for k in range(3)]
    pads = "".join(tht(n, x, y, 2.7, 3.7, 1.8, "roundrect" if n == 1 else "oval") for n, x, y in pins)
    pads += npth(0, -7.3, 3.0) + npth(8.4, -7.3, 3.0)
    boxes = [(x, y, 2.7, 3.7) for _, x, y in pins] + [(0, -7.3, 3.0, 3.0), (8.4, -7.3, 3.0, 3.0)]
    return footprint("Molex_Mini-Fit_Jr_39-30-3035_1x03_P4.20mm_Horizontal",
                     "Molex Mini-Fit Jr single row right-angle header 39-30-3035, 3 circuits, snap-in peg PCB lock, "
                     "mating face toward -y (LCSC C505179 footprint; pegs confirmed on the owner's stock-board scan)",
                     "Molex Mini-Fit Jr 5569 single row right angle 39303035", "through_hole",
                     (-2.7, -13.55, 11.1, -1.1), pads, boxes, (-2.0, 1.4), ref_y=-14.9, val_y=3.3)


def rj45_hr963380ae():
    """HanRun HR963380AE vertical SMD magjack: HanRun datasheet rev 00 p.3 'Recommended PCB layout (Component Side
    View)': origin = midpoint of the two 1.40 mm locating holes (+-7.00); pins 1-10 0.85 x 2.90 at 1.35 pitch, outer
    edge 10.05 below the holes (centre +8.60), pin 1 at +6.075; LED pins 11 / 12 / 13 / 14 1.10 x 4.20 at +6.55 / +4.01 /
    -4.01 / -6.55, outer edge 10.05 above (centre -7.95); shield tab 2.50 x 2.60 at (0, -8.75). Body 16.20 x 16.50
    (p.2). The LCSC footprint (C19724763) is identical with its origin 0.075 mm lower."""
    pads = "".join(smd(k, 6.075 - 1.35 * (k - 1), 8.60, 0.85, 2.90, "rect") for k in range(1, 11))
    for n, x in ((11, 6.55), (12, 4.01), (13, -4.01), (14, -6.55)):
        pads += smd(n, x, -7.95, 1.10, 4.20, "rect")
    pads += smd("SH", 0, -8.75, 2.50, 2.60, "rect")
    pads += npth(-7.0, 0, 1.40) + npth(7.0, 0, 1.40)
    boxes = ([(6.075 - 1.35 * (k - 1), 8.60, 0.85, 2.90) for k in range(1, 11)]
             + [(x, -7.95, 1.10, 4.20) for x in (6.55, 4.01, -4.01, -6.55)] + [(0, -8.75, 2.5, 2.6)])
    return footprint("RJ45_HanRun_HR963380AE_Vertical",
                     "HanRun HR963380AE vertical (tab-up) SMD RJ45 with integrated magnetics and 2 LEDs "
                     "(HanRun datasheet rev 00 p.3 recommended layout)",
                     "RJ45 vertical SMD magjack HanRun HR963380AE", "smd",
                     (-8.10, -7.98, 8.10, 8.43), pads, boxes, (7.3, 9.6), ref_y=-11.7, val_y=11.8)


def usbc_hro_31d06():
    """HRO TYPE-C-31-D-06 vertical 16-pin USB 2.0 receptacle: HRO drawing (2020-11-02) 'Recommended PCB layout (top
    view)': A row (A1 .. A12) 0.30 x 0.87 pads 1.30 - 0.435 = 0.865 above the centre line, B row mirrored below; x =
    +-2.75 (A1 / A12 / B12 / B1) and the 0.50-pitch inner six; shell: 4 plated slots 0.85 x 0.60 in 1.35 x 1.10 pads at
    (+-2.40, +-2.15); locating holes: dia 0.52 at -3.75 and a 0.72 x 0.52 slot (R0.26) at +3.75. Housing 8.94 x 3.16.
    The LCSC footprint (C2689964) agrees (it rounds the slot to a 0.72 circle)."""
    pads = ""
    boxes = []
    for row, y, names in (("A", -0.865, ["A1", "A4", "A5", "A6", "A7", "A8", "A9", "A12"]),
                          ("B", 0.865, ["B12", "B9", "B8", "B7", "B6", "B5", "B4", "B1"])):
        for n, x in zip(names, (-2.75, -1.25, -0.75, -0.25, 0.25, 0.75, 1.25, 2.75)):
            pads += smd(n, x, y, 0.30, 0.87, "rect")
            boxes.append((x, y, 0.30, 0.87))
    for x in (-2.40, 2.40):
        for y in (-2.15, 2.15):
            # pin-in-paste (q5 2026-10-27, adversarial review F01): the HRO drawing asks a 0.8 mm board, so the
            # 0.95 mm shell legs end inside this 1.6 mm board's slots; a top paste aperture (pad + 0.1 mm) lets the
            # reflow fill the slot barrel from the top (no JLC vertical 16-pin part drawn for 1.6 mm: DECISIONS #11)
            pads += tht("SH", x, y, 1.35, 1.10, None, "oval", slot=(0.85, 0.60), paste_margin=0.1)
            boxes.append((x, y, 1.35, 1.10))
    pads += npth(-3.75, 0, 0.52) + npth(3.75, 0, None, slot=(0.72, 0.52))
    return footprint("USB_C_Receptacle_HRO_TYPE-C-31-D-06_Vertical",
                     "HRO TYPE-C-31-D-06 vertical (top-entry) USB 2.0 Type-C receptacle, 16 pins + 4 shell slots "
                     "(HRO recommended PCB layout, top view)",
                     "USB C Type-C receptacle vertical HRO TYPE-C-31-D-06", "smd",
                     (-4.47, -1.58, 4.47, 1.58), pads, boxes, (-5.0, -0.865), ref_y=-3.9, val_y=4.1)


def usbc_hro_31d15():
    """HRO TYPE-C-31-D-15 vertical 16-pin USB 2.0 receptacle, 8.8 mm (q6 2026-10-27, coordinator QA D1 / DECISIONS #11):
    HRO drawing 2023-10-27 (datasheets/dl/j10/C22464480.pdf) 'Recommended P.C.B. layout (T: 1.00 mm)', drawn here
    rotated 90 deg so the A row is on top with A1 at the left, like the D-06 it replaces (the drawing's top view: A01
    top-left, B12 bottom-left). Signal pads 0.50 x 1.59 ((4.32 - 1.14) / 2) at 1.00 pitch, pad-row centres +-1.365
    (1.14 / 2 + 1.59 / 2); x = -3.5 .. 3.5 for A1 A4 A5 A6 A7 A8 A9 A12 (B12 B9 .. B1 below). Shell: 4 plated slots
    at (+-4.225, +-1.43) (8.45 x 2.86); the drawing's 0.45 x 1.20 slot is widened to 0.55 x 1.25 (JLC plated-slot
    minimum; legs 0.90 x 0.30, length 2.20 +-0.25 = through the 1.6 mm board) in a 0.95 x 1.65 pad; the slot pads touch
    the A1 / A12 / B1 / B12 GND pads as in the drawing (same net). Locating pegs dia 0.70 at (+5.41, +1.5) /
    (-5.41, -1.5) (10.82 x 3.00, diagonal): each shares a plated slot with the shell leg beside it (see below).
    Flange 12.00 x 5.00, housing 8.94 x 3.16.
    JLC has no LCSC footprint for C22464480 (EasyEDA API 404, 2026-10-27): the drawing is the only source."""
    pads = ""
    boxes = []
    for y, names in ((-1.365, ["A1", "A4", "A5", "A6", "A7", "A8", "A9", "A12"]),
                     (1.365, ["B12", "B9", "B8", "B7", "B6", "B5", "B4", "B1"])):
        for n, x in zip(names, (-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5)):
            pads += smd(n, x, y, 0.50, 1.59, "rect")
            boxes.append((x, y, 0.50, 1.59))
    # The drawing's own pattern leaves a 0.135 mm web between each slot end (4.225 + 0.60) and the peg hole beside it
    # (5.41 - 0.45): no copper ring fits (pad-to-NPTH 0.25 mm, first q6 DRC: 8 hole_clearance). At the two peg corners
    # the shell leg and the dia 0.70 peg share ONE plated GND slot 0.80 x 2.185 (leg 3.775 .. 4.675 and peg 5.06 ..
    # 5.76 along x, each + 0.1; y spans leg -1.43 +-0.15 and peg -1.5 +-0.35); the other two corners keep 0.55 x 1.25
    for x, y in ((-4.225, 1.43), (4.225, -1.43)):
        pads += tht("SH", x, y, 1.65, 0.95, None, "oval", slot=(1.25, 0.55))
        boxes.append((x, y, 1.65, 0.95))
    for sx in (-1, 1):
        x, y = sx * 4.7675, sx * 1.465
        pads += tht("SH", x, y, 2.485, 1.10, None, "oval", slot=(2.185, 0.80))
        boxes.append((x, y, 2.485, 1.10))
    return footprint("USB_C_Receptacle_HRO_TYPE-C-31-D-15_Vertical",
                     "HRO TYPE-C-31-D-15 vertical (top-entry) USB 2.0 Type-C receptacle 8.8 mm, 16 pins + 4 through "
                     "shell legs (HRO recommended PCB layout 2023-10-27, rotated 90 deg; slots widened to 0.55 x 1.25)",
                     "USB C Type-C receptacle vertical HRO TYPE-C-31-D-15", "smd",
                     (-6.0, -2.5, 6.0, 2.5), pads, boxes, (-3.5, -3.0), ref_y=-3.8, val_y=3.8)


def dip_dsic04ls():
    """XKB DSIC04LS-P 4-position SMD DIP switch: XKB drawing X-DSIC04LS-P rev A1 'P.C.B LAYOUT': pads 1.10 x 1.70,
    2.54 pitch, 7.60 between the two rows' inner edges (rows 9.30 apart); body 10.16 x 6.10. DIP numbering: 1-4 along
    the bottom row left to right, 5-8 back along the top row (switch k joins k and 9-k). The LCSC footprint (C319038)
    uses longer 2.29 x 1.52 pads 8.75 apart; the maker's drawing is followed."""
    pads, boxes = "", []
    for k in range(4):
        x = -3.81 + 2.54 * k
        pads += smd(k + 1, x, 4.65, 1.10, 1.70)
        pads += smd(8 - k, x, -4.65, 1.10, 1.70)
        boxes += [(x, 4.65, 1.10, 1.70), (x, -4.65, 1.10, 1.70)]
    return footprint("SW_DIP_XKB_DSIC04LS-P",
                     "XKB DSIC04LS-P 4-position SMD DIP switch, 2.54 mm pitch, projection actuators "
                     "(XKB drawing X-DSIC04LS-P PCB layout)",
                     "DIP switch SPST 4 SMD XKB DSIC04LS", "smd",
                     (-5.08, -3.05, 5.08, 3.05), pads, boxes, (-5.05, 4.65))


def rj11_topentry_stock():
    """Molex 95503-2441 4P4C low-profile TOP-ENTRY jack (Molex SD-95503-003, datasheets/955032661_sd.pdf: 4 POS = A
    11.18 body, B 7.62 posts, D 3.81 tails; posts 4.96 behind the front face, tail rows 6.35 / 8.89 behind the posts)
    = the stock part ('95003' body, mfg ID 'MXCH', photo image4; independent check
    Q-46: our pattern = the stock pads incl. the pin-1 corner). Geometry = the owner's 300 dpi scan of the stock board
    (8 identical jacks, +-0.1 mm): two 3.25 mm locating posts 7.62 mm apart; 4 tails on 1.27 mm pitch in two rows 6.35 /
    8.89 mm behind the post line (scan: 3.3 mm posts 7.66 apart, rows 6.25 / 8.89, tails at -1.9 / -0.6 / +0.6 / +1.9);
    pin 1 = square pad, near row, left (scan). Origin = midpoint of the posts; the plug enters from ABOVE, latch slot
    toward +y (board edge 5.48 mm out), contacts on the -y side; body 11.5 wide (stock 12.08 mm jack pitch)."""
    pins = [(1, -1.905, -6.35), (2, -0.635, -8.89), (3, 0.635, -6.35), (4, 1.905, -8.89)]
    pads = "".join(tht(n, x, y, 1.5, 1.5, 0.9, "roundrect" if n == 1 else "circle") for n, x, y in pins)
    pads += npth(-3.81, 0, 3.25) + npth(3.81, 0, 3.25)
    boxes = [(x, y, 1.5, 1.5) for _, x, y in pins] + [(-3.81, 0, 3.25, 3.25), (3.81, 0, 3.25, 3.25)]
    return footprint("RJ11_6P4C_TopEntry_StockPads",
                     "6P4C top-entry modular jack on the stock SBC pads (stock 'MXCH 95003'), plug from above, latch slot "
                     "toward +y (board edge)", "RJ11 6P4C modular jack top entry vertical", "through_hole",
                     (-5.59, -10.12, 5.59, 4.96), pads, boxes, (-3.2, -6.35), crt=0.1)   # stock pitch 12.08


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for name, body in (mounting_hole(3.57), minifit_1x04_vertical(), minifit_1x03_horizontal(), rj45_hr963380ae(),
                       usbc_hro_31d06(), usbc_hro_31d15(), dip_dsic04ls(), rj11_topentry_stock()):
        (OUT / f"{name}.kicad_mod").write_text(body, encoding="utf-8")
        n += 1
    print(f"wrote {n} footprint(s) to {OUT}")


if __name__ == "__main__":
    main()
