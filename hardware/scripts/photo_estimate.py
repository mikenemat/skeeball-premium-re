"""Photo estimate of the stock board A5CB25502 Rev 2.2 connector positions ("photo +-1 mm"), anchored on the OWNER'S
MEASUREMENTS (2026-10-26): outline 116.68 x 85.73 mm, four corner holes 3.97 mm in from both edges (spacing
108.74 x 77.79 mm), hole 3.57 mm. The outline and holes are exact (layout_const.MEASURED); only the connector bodies /
pin-1 positions and the RJ45 zones come from the photo.

Method: plane homography from the four hole centres in skeeball-board/photos/2026-10-26_owner/board_front_straight.jpg
to their exact mm positions (no scale assumption at all: the earlier fit scaled from the J11 pitch and came out 5 %
short in x - QA_LOG Q-18). Origin = board top-left corner, x right, y down (J11 edge = bottom).
Checks printed: the mapped board edges vs the measured outline, the RP2040 body (7.00 mm) and the J11 pin span.
Writes docs/records/photo_estimate/estimate.json.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

# ---- owner measurements (exact) --------------------------------------------------------------------------------------
OUTLINE = (116.68, 85.73)
HOLE_INSET, HOLE_DRILL = 3.97, 3.57
HOLES_MM = {"H1 TL": (HOLE_INSET, HOLE_INSET), "H2 TR": (OUTLINE[0] - HOLE_INSET, HOLE_INSET),
            "H3 BR": (OUTLINE[0] - HOLE_INSET, OUTLINE[1] - HOLE_INSET), "H4 BL": (HOLE_INSET, OUTLINE[1] - HOLE_INSET)}

# ---- pixel readings in board_front_straight.jpg (3-4x zoom crops, 2026-10-26) ----------------------------------------
HOLE_PX = {"H1 TL": (263, 108), "H2 TR": (1508, 133), "H3 BR": (1588, 1028), "H4 BL": (203, 1070)}
U3_PX = [(909.5, 410), (992.5, 410), (992.5, 491.25), (909.5, 491.25)]        # RP2040 body corners
J11_PX = {"pin9": (781.25, 843.75), "pin1": (1048.75, 843.75)}                  # pin 1 = '*' end (right)
EDGE_PX = {"TL": (220, 75), "TR": (1543, 97), "BR": (1618, 1077), "L_low": (158, 1100)}
REGIONS_PX = {   # on-board footprint area of each kept harness connector (x0, y0, x1, y1)
    "PWR (3-pin right-angle, plug from the top edge)": (1300, 120, 1460, 215),
    "J18 micro-USB (display)": (895, 75, 985, 135),
    "PLAYFIELD LIGHTS (2-pin right-angle, plug from the left)": (222, 140, 330, 265),
    "RGB LIGHTS (1x4 4.2 mm vertical)": (222, 420, 425, 535),
    "BUTTONS (2x4 4.2 mm vertical)": (222, 690, 415, 830),
    "J11 SCORE SENSORS (9-way)": (768, 822, 1062, 862),
    "J20 SPEAKER (2-pin right-angle, plug from the right)": (1370, 590, 1595, 655),
}
PIN1_PX = {   # pin-1 pad centres read from the photo (harness connectors; +-1 mm is acceptable: cables float)
    "PWR pin 1 (5 V, left pin)": (1322, 205), "RGB pin 1 (left, square)": (247, 517),
    "BUTTONS pin 1 (top-left, square)": (247, 712), "PLAYFIELD upper pin (FET channel; +5 V = lower pin)": (262, 173),
    "SPEAKER pin 1 (left pad)": (1398, 622), "J18 micro-USB centre (x)": (940, 100),
}
ZONES_PX = {"a: model-number text area": (440, 145, 745, 365), "b: between PWR and SPEAKER": (1300, 235, None, 550)}
UNUSED_HOLES_PX = {"top, above model text": (568, 113), "top, left of PWR": (1225, 125)}


def homography(src, dst):
    a = []
    for (x, y), (u, v) in zip(src, dst):
        a += [[x, y, 1, 0, 0, 0, -u * x, -u * y, -u], [0, 0, 0, x, y, 1, -v * x, -v * y, -v]]
    return np.linalg.svd(np.array(a, float))[2][-1].reshape(3, 3)


def apply(h, p):
    q = h @ np.array([p[0], p[1], 1.0])
    return q[:2] / q[2]


def main():
    order = ("H1 TL", "H2 TR", "H3 BR", "H4 BL")
    hm = homography([HOLE_PX[k] for k in order], [HOLES_MM[k] for k in order])

    def mm(p):
        q = apply(hm, p)
        return round(float(q[0]), 1), round(float(q[1]), 1)

    def box(b, right_edge=False):
        x0, y0, x1, y1 = b
        a = mm((x0, y0))
        c = mm((x1 if x1 is not None else EDGE_PX["TR"][0], y1))
        if right_edge:
            c = (OUTLINE[0], c[1])
        return [max(a[0], 0.0), max(a[1], 0.0), min(c[0], OUTLINE[0]), min(c[1], OUTLINE[1])]

    u = [apply(hm, p) for p in U3_PX]
    checks = {
        "mapped edges (TL, TR, BR, left-low) vs outline 116.68 x 85.73": [mm(EDGE_PX[k]) for k in ("TL", "TR", "BR", "L_low")],
        "RP2040 body width / height (should be 7.00)": [round(float(u[1][0] - u[0][0]), 2), round(float(u[3][1] - u[0][1]), 2)],
        "J11 pin1 - pin9 span (8 pitches: 20.32 = KK 2.54, 20.00 = XH 2.5)": round(float(apply(hm, J11_PX["pin1"])[0] - apply(hm, J11_PX["pin9"])[0]), 2),
    }
    out = {
        "status": "outline + holes EXACT (owner 2026-10-26); connector bodies / pin-1 = photo +-1 mm (replace by the 600 dpi scan if it arrives)",
        "source": "skeeball-board/photos/2026-10-26_owner/board_front_straight.jpg, homography anchored on the four measured hole centres",
        "outline_mm": list(OUTLINE), "hole_drill_mm": HOLE_DRILL, "holes_mm": {k: list(v) for k, v in HOLES_MM.items()},
        "checks": checks,
        "unused_holes_mm": {k: mm(v) for k, v in UNUSED_HOLES_PX.items()},
        "regions_mm": {k: box(v) for k, v in REGIONS_PX.items()},
        "pin1_mm": {k: mm(v) for k, v in PIN1_PX.items()},
        "zones_mm": {k: box(v, right_edge=v[2] is None) for k, v in ZONES_PX.items()},
        "pins_mm": {"J11 pin 9 (left end)": mm(J11_PX["pin9"]), "J11 pin 1 '*' (right end)": mm(J11_PX["pin1"])},
    }
    d = ROOT / "docs" / "records" / "photo_estimate"
    d.mkdir(parents=True, exist_ok=True)
    (d / "estimate.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
