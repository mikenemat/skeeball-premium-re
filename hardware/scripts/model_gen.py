"""Envelope 3D models (VRML) for the footprints this KiCad install has no model for: one box per part body at the
maker's drawing dimensions (outline + height), so the 3D view / enclosure checks see every part. Replace with the
vendor STEP when one is available. Output: hardware/lib/3d/<footprint>.wrl (KiCad VRML units = 2.54 mm; model y up).
    python model_gen.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "hardware" / "lib" / "3d"
U = 2.54
# footprint name -> (x0, y0, x1, y1 in the footprint frame (mm, y down), height mm, RGB, source of the numbers)
BODIES = {
    "Molex_Mini-Fit_Jr_39-30-3035_1x03_P4.20mm_Horizontal": ((-2.7, -13.55, 11.1, -1.1), 9.6, (0.95, 0.95, 0.9), "LCSC C505179 outline"),
    "Molex_Mini-Fit_Jr_39-30-1049_1x04_P4.20mm_Vertical": ((-2.72, -7.33, 15.32, 5.75), 12.8, (0.95, 0.95, 0.9), "LCSC C587488 outline, 12.8 tall"),
    "RJ45_HanRun_HR963380AE_Vertical": ((-8.1, -7.98, 8.1, 8.43), 13.5, (0.75, 0.75, 0.78), "HanRun p.2 16.2 x 16.5"),
    "USB_C_Receptacle_HRO_TYPE-C-31-D-06_Vertical": ((-4.47, -1.58, 4.47, 1.58), 6.4, (0.8, 0.8, 0.82), "HRO drawing 8.94 x 3.16 x 6.40"),
    "SW_DIP_XKB_DSIC04LS-P": ((-5.08, -3.05, 5.08, 3.05), 3.55, (0.1, 0.1, 0.1), "XKB drawing 10.16 x 6.10 x 3.55"),
    "Molex_Mini-Fit_Jr_5566-08A_2x04_P4.20mm_Vertical": ((-3.05, -2.6, 15.65, 8.1), 9.6, (0.95, 0.95, 0.9), "KiCad fab outline"),
    "Molex_Mini-Fit_Jr_5569-02A2_2x01_P4.20mm_Horizontal": ((-2.7, -13.9, 2.7, -1.1), 12.6, (0.95, 0.95, 0.9), "KiCad 5569 fab outline"),
    "USB_Micro-B_Amphenol_10118194-0001LF_Horizontal": ((-3.65, -1.55, 3.65, 3.98), 2.6, (0.8, 0.8, 0.82), "KiCad fab outline"),
    "SW_Push_1P1T_XKB_TS-1187A": ((-2.55, -2.55, 2.55, 2.55), 1.5, (0.2, 0.2, 0.2), "XKB TS-1187A 5.1 x 5.1 x 1.5"),
    "QFN-80-1EP_10x10mm_P0.4mm_EP3.4x3.4mm": ((-5.0, -5.0, 5.0, 5.0), 0.9, (0.08, 0.08, 0.08), "RP2350B QFN-80 10 x 10 x 0.9"),
    "Fuse_2920_7451Metric": ((-3.7, -2.55, 3.7, 2.55), 1.6, (0.85, 0.7, 0.2), "2920 PTC body"),
}


def wrl(box, h, rgb):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, -(y0 + y1) / 2                     # model frame: y up
    return ("#VRML V2.0 utf8\n"
            f"Transform {{ translation {cx / U:.4f} {cy / U:.4f} {h / 2 / U:.4f} children [ Shape {{\n"
            f"  appearance Appearance {{ material Material {{ diffuseColor {rgb[0]} {rgb[1]} {rgb[2]} }} }}\n"
            f"  geometry Box {{ size {(x1 - x0) / U:.4f} {(y1 - y0) / U:.4f} {h / U:.4f} }} }} ] }}\n")


# composite models: footprint name -> boxes (x0, y0, z0, x1, y1, z1 in the footprint frame, mm, y down; RGB)
BLACK, GOLD, TIN = (0.08, 0.08, 0.08), (0.85, 0.65, 0.2), (0.75, 0.75, 0.75)
# score jack J21-J28 = Molex 95503-2441 4P4C low-profile top-entry (SD-95503-003, 4 POS): 11.18 W x 15.08 L x 15.70 H,
# the inboard 4.00 mm a 12.70 step; front face 4.96 in front of the posts (board edge side, +y); plug opening 9.50 long
# from 0.80 behind the front face, latch notch in the front wall, 4 contacts on the inboard wall (no EasyEDA model exists)
_J = [(-5.59, -10.12, 0, 5.59, 4.96, 2.0, BLACK),                                     # floor
      (-5.59, -6.12, 2.0, -4.0, 4.96, 15.7, BLACK), (4.0, -6.12, 2.0, 5.59, 4.96, 15.7, BLACK),   # side walls
      (-4.0, -6.12, 2.0, 4.0, -5.34, 15.7, BLACK),                                    # contact carrier wall
      (-5.59, -10.12, 2.0, 5.59, -6.12, 12.7, BLACK),                                 # inboard 12.70 step
      (-4.0, 4.16, 2.0, -1.35, 4.96, 15.7, BLACK), (1.35, 4.16, 2.0, 4.0, 4.96, 15.7, BLACK),     # front wall
      (-1.35, 4.16, 2.0, 1.35, 4.96, 6.0, BLACK)]                                     # latch notch (open above)
_J += [(c - 0.2, -5.34, 4.0, c + 0.2, -4.95, 13.0, GOLD) for c in (-1.53, -0.51, 0.51, 1.53)]     # contacts
_J += [(x - 0.25, y - 0.25, -3.3, x + 0.25, y + 0.25, 0, TIN) for x, y in ((-1.905, -6.35), (-0.635, -8.89),
                                                                          (0.635, -6.35), (1.905, -8.89))]
_J += [(x - 1.2, -1.2, -3.0, x + 1.2, 1.2, 0, BLACK) for x in (-3.81, 3.81)]                      # posts
# HRO TYPE-C-31-D-15 (no EasyEDA model; drawing 2023-10-27): flange 12.00 x 5.00 x 2.10, shell 8.94 x 3.16 to 8.8 mm
# (H), opening 8.34 x 2.56 (darker), 4 shell legs 0.90 x 0.30 to -2.20, 2 pegs dia 0.70 x 0.70 (q6 2026-10-27)
_C15 = [(-6.0, -2.5, 0, 6.0, 2.5, 2.1, BLACK), (-4.47, -1.58, 2.1, 4.47, 1.58, 8.8, TIN),
        (-4.17, -1.28, 8.8, 4.17, 1.28, 8.82, BLACK)]
_C15 += [(x - 0.45, y - 0.15, -2.2, x + 0.45, y + 0.15, 0, TIN) for x in (-4.225, 4.225) for y in (-1.43, 1.43)]
_C15 += [(x - 0.35, y - 0.35, -0.7, x + 0.35, y + 0.35, 0, BLACK) for x, y in ((5.41, 1.5), (-5.41, -1.5))]
COMPOSITES = {"RJ11_6P4C_TopEntry_StockPads": _J, "USB_C_Receptacle_HRO_TYPE-C-31-D-15_Vertical": _C15}


def wrl_boxes(boxes):
    out = ["#VRML V2.0 utf8"]
    for x0, y0, z0, x1, y1, z1, rgb in boxes:
        out.append(f"Transform {{ translation {(x0 + x1) / 2 / U:.4f} {-(y0 + y1) / 2 / U:.4f} {(z0 + z1) / 2 / U:.4f} "
                   f"children [ Shape {{ appearance Appearance {{ material Material {{ diffuseColor {rgb[0]} {rgb[1]} "
                   f"{rgb[2]} }} }} geometry Box {{ size {(x1 - x0) / U:.4f} {(y1 - y0) / U:.4f} {(z1 - z0) / U:.4f} }} }} ] }}")
    return "\n".join(out) + "\n"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (box, h, rgb, _src) in BODIES.items():
        (OUT / f"{name}.wrl").write_text(wrl(box, h, rgb), encoding="utf-8")
    for name, boxes in COMPOSITES.items():
        (OUT / f"{name}.wrl").write_text(wrl_boxes(boxes), encoding="utf-8")
    print(f"wrote {len(BODIES)} envelope + {len(COMPOSITES)} composite models to {OUT}")


if __name__ == "__main__":
    main()
