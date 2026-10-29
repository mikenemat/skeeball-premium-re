"""Extract the stock board's through-hole pad centres from the owner's 300 dpi flatbed scan of the BOTTOM side
(skeeball-board/photos/2026-10-26_owner/board_back_flatbed_scan_300dpi.jpg, 2550 x 3300 px, long side vertical,
mirrored vs the component side).

Method
  1. Board mask = green pixels; pads / holes = non-green blobs inside the filled board mask (scipy.ndimage).
  2. The four corner holes (the largest round blobs near the corners) are mapped by an affine fit to their EXACT
     component-side positions (owner calipers M-H1: centres 3.885 mm from the short edges and 3.585 mm from the long
     edges of the 116.68 x 85.73 mm board = layout_const.MEASURED hole_inset_x / hole_inset_y). The fit absorbs the
     scan's rotation, the mirror and the x / y scale (hole-derived on BOTH axes), and its residual on the fourth hole is
     the accuracy check. Component frame: origin top-left, x right (toward PWR), y down (toward J11), component side up.
  3. Every other blob is mapped through that affine and assigned to a named connector by its expected neighbourhood;
     pins within a connector are refined by a straight-line / pitch fit.
Accuracy: one scan pixel is 0.084 mm; blob centroids of 2 mm pads are good to ~0.1 mm, solder-covered pins (RGB, J11)
~0.2 mm. Scale cross-check vs the scanner's declared 300 dpi is printed.
Writes docs/records/scan_extract/pads.json (read by layout_const.py).
"""
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
# the owner's 300 dpi bottom-side scan of the stock board (not in the repo); point SKEEBALL_SCAN at it to re-run
SCAN = Path(os.environ.get("SKEEBALL_SCAN", "board_back_flatbed_scan_300dpi.jpg"))
OUT = ROOT / "docs" / "records" / "scan_extract" / "pads.json"
OUTLINE = (116.68, 85.73)
INSET_X, INSET_Y = 3.885, 3.585                     # = layout_const.MEASURED hole_inset_x / hole_inset_y (owner M-H1)
HOLES_MM = {"H1": (INSET_X, INSET_Y), "H2": (OUTLINE[0] - INSET_X, INSET_Y), "H3": (OUTLINE[0] - INSET_X, OUTLINE[1] - INSET_Y),
            "H4": (INSET_X, OUTLINE[1] - INSET_Y)}
DPI_DECLARED = 300 / 25.4


def blobs(a, bm, min_area=15, max_wh=70):
    bm_f = ndi.binary_fill_holes(bm)
    inside = bm_f & ~bm
    lab, n = ndi.label(inside)
    out = []
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        m = lab[sl] == i
        area = int(m.sum())
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if area < min_area or w > max_wh or h > max_wh:
            continue
        cy, cx = ndi.center_of_mass(m)
        out.append({"cx": float(sl[1].start + cx), "cy": float(sl[0].start + cy), "w": w, "h": h, "area": area,
                    "lum": float(a[sl][m].mean())})
    return out


def main():
    im = Image.open(SCAN).convert("RGB")
    a = np.asarray(im).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    board = (g > r + 12) & (g > b + 12)
    lab, n = ndi.label(board)
    bm = lab == (np.argmax(ndi.sum(board, lab, range(1, n + 1))) + 1)
    bl = blobs(a, bm)
    # --- corner holes: the four big round blobs nearest the board-mask corners
    ys, xs = np.where(bm)
    corners = {"TL": (xs.min(), ys.min()), "TR": (xs.max(), ys.min()), "BL": (xs.min(), ys.max()), "BR": (xs.max(), ys.max())}
    big = [p for p in bl if p["w"] >= 40 and p["h"] >= 40 and p["area"] > 1200]
    hole_px = {}
    for k, (cx, cy) in corners.items():
        hole_px[k] = min(big, key=lambda p: (p["cx"] - cx) ** 2 + (p["cy"] - cy) ** 2)
    # scan orientation (bottom view, long side vertical): scan TL hole = component H1 (3.885, 3.585); scan x runs along
    # component y (toward the J11 / jack edge = scan right); scan y runs along component x (toward PWR = scan bottom)
    pairs = {"TL": "H1", "TR": "H4", "BL": "H2", "BR": "H3"}
    A = np.array([[hole_px[k]["cx"], hole_px[k]["cy"], 1.0] for k in pairs])
    B = np.array([HOLES_MM[pairs[k]] for k in pairs])
    M, *_ = np.linalg.lstsq(A, B, rcond=None)
    resid = (A @ M) - B
    # The hole-derived affine is used on BOTH axes (TODO-3, owner M-H1 re-measure 2026-10-26): with the per-axis hole
    # insets its scale sits within 0.5 % of the declared 300 dpi on both axes (printed below as the cross-check).
    # (M maps [px, py, 1] -> [x, y]; column 0 = x, column 1 = y)
    sx = 1 / np.hypot(M[0, 0], M[1, 0]); sy = 1 / np.hypot(M[0, 1], M[1, 1])

    def mm(p):
        return (np.array([p["cx"], p["cy"], 1.0]) @ M).tolist()

    pts = [{"x": round(mm(p)[0], 2), "y": round(mm(p)[1], 2), "w": p["w"], "h": p["h"], "area": p["area"],
            "lum": round(p["lum"]), "px": [round(p["cx"], 1), round(p["cy"], 1)]} for p in bl]

    def near(x, y, tol=1.6, **flt):
        c = [p for p in pts if abs(p["x"] - x) <= tol and abs(p["y"] - y) <= tol]
        return min(c, key=lambda p: (p["x"] - x) ** 2 + (p["y"] - y) ** 2) if c else None

    def row(name, x0, y0, n, pitch, axis="x", tol=1.6, note=""):
        """n pads from (x0, y0) along axis with pitch; returns the measured centres + a least-squares pitch."""
        got = []
        for k in range(n):
            ex, ey = (x0 + k * pitch, y0) if axis == "x" else (x0, y0 + k * pitch)
            p = near(ex, ey, tol)
            got.append(None if p is None else (p["x"], p["y"]))
        idx = [k for k, v in enumerate(got) if v is not None]
        fit = None
        if len(idx) >= 2:
            ks = np.array(idx, float)
            vals = np.array([got[k][0] if axis == "x" else got[k][1] for k in idx])
            slope, icpt = np.polyfit(ks, vals, 1)
            other = float(np.mean([got[k][1] if axis == "x" else got[k][0] for k in idx]))
            fit = {"pitch": round(float(slope), 3), "start": round(float(icpt), 2), "other": round(other, 2)}
        return {"name": name, "axis": axis, "n": n, "nominal_pitch": pitch, "measured": [None if v is None else [round(v[0], 2), round(v[1], 2)] for v in got],
                "fit": fit, "note": note}

    conns = [
        row("PWR 1x3 RA (pin 1 = 5 V at the small-x end)", 95.4, 10.7, 3, 4.2, "x", note="right-angle single-row 4.2 mm; two locating-peg holes at y ~3.6"),
        row("J18 micro-USB shell anchors (4)", 58.7, 2.15, 2, 5.5, "x", note="row 1 of 2; see J18_anchor_row2"),
        row("J18_anchor_row2", 58.9, 5.08, 2, 5.0, "x"),
        row("PLAYFIELD 2-pin RA (lower pin = +5 V)", 4.95, 11.74, 2, 3.4, "y", tol=1.2,
            note="KK 396 (owner calipers: 3.96 mm pitch, 1.14 mm square pins); the scan's two solder-covered pads read "
                 "3.4 mm apart (centroid bias), so the pads are placed 3.96 apart about the scanned midpoint"),
        row("J5 1x4 (unpopulated, dropped)", 3.74, 26.0, 4, 4.2, "x"),
        row("RGB 1x4 vertical (pin 1 = +5 V at the small-x end)", 4.12, 37.85, 4, 4.2, "x", note="soldered pins: +-0.2 mm"),
        row("J7 1x4 (unpopulated, dropped)", 3.54, 48.2, 4, 4.2, "x"),
        row("BUTTONS 2x4 row A (y ~56.2, signals)", 3.7, 56.2, 4, 4.2, "x"),
        row("BUTTONS 2x4 row B (y ~61.7, latch side = GND)", 3.85, 61.7, 4, 4.2, "x"),
        row("J19 1x3 2.54 (dropped)", 64.35, 49.68, 3, 2.54, "x"),
        row("SPEAKER 2x1 RA (two rows 5.5 apart, pins stacked)", 99.88, 48.25, 2, 5.5, "x", note="peg hole at x ~112.6"),
        row("J2 2x5 4.2 mm row A (dropped)", 96.2, 57.2, 5, 4.2, "x"),
        row("J2 2x5 4.2 mm row B (dropped)", 96.2, 62.7, 5, 4.2, "x"),
        row("J11 1x9 (pin 1 '*' = GND at the large-x end)", 48.9, 64.6, 9, 2.51, "x", tol=1.0, note="solder-covered pins: +-0.2 mm; pitch from the 8-pitch span"),
    ]
    # the modular jacks (dropped) and the unused holes, for reference
    jacks = sorted([p for p in pts if p["w"] >= 35 and p["h"] >= 33 and p["y"] > 78], key=lambda p: p["x"])
    unused = [p for p in pts if p["w"] >= 26 and p["h"] >= 30 and p["lum"] < 80 and p["y"] < 6 and 20 < p["x"] < 95]
    out = {
        "source": str(SCAN), "declared_px_per_mm": round(DPI_DECLARED, 3),
        "hole_fit": {"px": {k: [round(v["cx"], 1), round(v["cy"], 1)] for k, v in hole_px.items()},
                     "residual_mm_hole_only_fit": [[round(float(v), 3) for v in rr] for rr in resid],
                     "holes_mm": {k: [round(v[0], 3), round(v[1], 3)] for k, v in HOLES_MM.items()},
                     "scale_note": "hole-derived affine on both axes (owner M-H1 per-axis insets 3.885 / 3.585 mm)",
                     "px_per_mm_component_x": round(float(sx), 3), "px_per_mm_component_y": round(float(sy), 3),
                     "vs_declared_pct": [round((sx / DPI_DECLARED - 1) * 100, 2), round((sy / DPI_DECLARED - 1) * 100, 2)]},
        "connectors": conns,
        "modular_jack_holes_y80": [[p["x"], p["y"]] for p in jacks],
        "unused_top_holes": [[p["x"], p["y"]] for p in unused],
        "accuracy_mm": 0.1,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"holes px {out['hole_fit']['px']}\nhole-only residual mm {out['hole_fit']['residual_mm_hole_only_fit']}\n"
          f"scale {sx:.3f} / {sy:.3f} px/mm vs declared {DPI_DECLARED:.3f} ({out['hole_fit']['vs_declared_pct']} %)\n{out['hole_fit']['scale_note']}")
    for c in conns:
        print(f"{c['name']:58} fit {c['fit']}  pads {c['measured']}")
    print("jacks", out["modular_jack_holes_y80"])
    print("unused top holes", out["unused_top_holes"])


if __name__ == "__main__":
    main()
