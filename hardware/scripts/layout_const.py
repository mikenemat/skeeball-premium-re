"""Placement constants for SBC-1 (docs/PLACEMENT_PLAN.md).

MEASURED (exact, owner 2026-10-26): the outline and the four corner holes (calipers; hole insets re-measured per axis,
M-H1 / TODO-3), and every through-hole pad of the
harness connectors from the owner's 300 dpi flatbed scan of the stock board's bottom side, mapped onto the measured
holes (scripts/scan_extract.py -> docs/records/scan_extract/pads.json; +-0.1 mm, +-0.2 mm for solder-covered pins).
The photo homography (scripts/photo_estimate.py) is kept only for the RJ45 zones and as a cross-check.

Coordinates: mm, component side up, origin = board top-left corner (J11 edge = bottom), x right, y down.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = json.loads((ROOT / "docs/records/scan_extract/pads.json").read_text(encoding="utf-8"))
EST = json.loads((ROOT / "docs/records/photo_estimate/estimate.json").read_text(encoding="utf-8"))

# ---- owner measurements (exact) --------------------------------------------------------------------------------------
MEASURED = {
    "outline": (116.68, 85.73),          # 4-19/32 x 3-3/8 in, square corners, 1.6 mm
    # hole centre insets (owner calipers M-H1 2026-10-26): 2.1 mm from the short edges and 1.8 mm from the long edges
    # to the near hole edge, + the 1.785 mm radius
    "hole_inset_x": 3.885,               # from the short (left / right) edges
    "hole_inset_y": 3.585,               # from the long (top / bottom) edges
    "hole_drill": 3.57,                  # 9/64 in
    "usb_mouth_past_edge": 1.0,          # J18 micro-USB mouth protrudes ~1 mm (M-C7)
    "scan_accuracy_mm": SCAN["accuracy_mm"],
}
OUTLINE = MEASURED["outline"]
_ix, _iy = MEASURED["hole_inset_x"], MEASURED["hole_inset_y"]
HOLES = {"H1": (_ix, _iy), "H2": (round(OUTLINE[0] - _ix, 3), _iy), "H3": (round(OUTLINE[0] - _ix, 3), round(OUTLINE[1] - _iy, 3)),
         "H4": (_ix, round(OUTLINE[1] - _iy, 3))}
HOLE_DRILL = MEASURED["hole_drill"]

# ---- measured pad centres (scan) --------------------------------------------------------------------------------------
_c = {c["name"]: c for c in SCAN["connectors"]}


def _conn(prefix):
    return next(c for n, c in _c.items() if n.startswith(prefix))


PADS = {   # connector -> list of (x, y) pad centres in pin order where the order is known
    "PWR": _conn("PWR 1x3")["measured"],                                      # pin 1 (5 V) .. pin 3 (GND)
    "J18_ANCHORS": _conn("J18 micro-USB")["measured"] + _conn("J18_anchor_row2")["measured"],
    "PLAYFIELD": _conn("PLAYFIELD")["measured"],                               # [upper pin (FET), lower pin (+5 V)]
    "RGB": _conn("RGB 1x4")["measured"],                                      # pin 1 (+5 V) .. pin 4
    "BUTTONS_SIG": _conn("BUTTONS 2x4 row A")["measured"],                    # row y ~56.2 = the 4 signals
    "BUTTONS_GND": _conn("BUTTONS 2x4 row B")["measured"],                    # row y ~61.7 = latch side = GND
    "SPEAKER": _conn("SPEAKER")["measured"],                                  # the two stacked pins, 5.5 mm apart in x
    "J11": list(reversed(_conn("J11 1x9")["measured"])),                      # pin 1 ('*', GND, large x) .. pin 9
}
PITCH = {k: _conn(p)["fit"]["pitch"] for k, p in (("PWR", "PWR 1x3"), ("RGB", "RGB 1x4"), ("BUTTONS", "BUTTONS 2x4 row A"),
                                                     ("J11", "J11 1x9"), ("PLAYFIELD", "PLAYFIELD"))}
J18_CENTER_X = round(sum(p[0] for p in PADS["J18_ANCHORS"]) / 4, 2)
J11_PIN1 = tuple(PADS["J11"][0])
UNUSED_TOP_HOLES = SCAN["unused_top_holes"]                                   # stock inner holes, dropped


def _box(pads, dx, dy0, dy1):
    xs = [p[0] for p in pads]
    ys = [p[1] for p in pads]
    return [round(min(xs) - dx, 1), round(min(ys) - dy0, 1), round(max(xs) + dx, 1), round(max(ys) + dy1, 1)]


# connector body boxes for the renders / placement guides (body outline approximated around the measured pads)
HARNESS = {
    "PWR": _box(PADS["PWR"], 2.8, 10.2, 1.6),                                 # RA body toward the top edge
    "J18 micro-USB": [J18_CENTER_X - 4.0, -MEASURED["usb_mouth_past_edge"], J18_CENTER_X + 4.0, 5.6],
    "PLAYFIELD LIGHTS": [0.0, round(PADS["PLAYFIELD"][0][1] - 2.6, 1), round(PADS["PLAYFIELD"][0][0] + 6.5, 1),
                         round(PADS["PLAYFIELD"][1][1] + 2.6, 1)],
    "RGB LIGHTS": _box(PADS["RGB"], 2.8, 4.8, 4.8),
    "BUTTONS": _box(PADS["BUTTONS_SIG"] + PADS["BUTTONS_GND"], 2.8, 2.6, 2.6),
    "J11 SCORE SENSORS": _box(PADS["J11"], 2.6, 3.0, 3.0),
    "J20 SPEAKER": [round(PADS["SPEAKER"][0][0] - 3.5, 1), round(PADS["SPEAKER"][0][1] - 4.75, 1), OUTLINE[0],
                    round(PADS["SPEAKER"][0][1] + 4.75, 1)],
}
PIN1 = {"PWR pin 1 (5 V)": PADS["PWR"][0], "RGB pin 1 (+5 V)": PADS["RGB"][0], "Playfield +5 V (lower)": PADS["PLAYFIELD"][1],
        "Buttons signal row pin 1": PADS["BUTTONS_SIG"][0], "Speaker outer pin": PADS["SPEAKER"][0],
        "J11 pin 1 ('*', GND)": PADS["J11"][0], "J18 centre x": (J18_CENTER_X, 0.0)}
ZONES = EST["zones_mm"]                                                      # photo (+-1 mm): only the RJ45 zones

# ---- RJ45: owner pick = zone a, vertical HanRun HR963380AE -----------------------------------------------------------
RJ45_PICK = ("a", "V")
RJ45 = {
    "RA": {"part": "HanRun HR911105A (C12074) right-angle, 10/100 magjack, 2 LEDs (fallback only)",
           "body": (15.9, 21.3), "height": 13.5, "faces": "board edge"},
    "V": {"part": "HanRun HR963380AE (C19724763) vertical / top-entry SMD, magjack, 2 LEDs",
          "body": (16.2, 16.5), "height": 16.85, "faces": "up"},
}
RJ45_FITS = {   # (x0, y0, x1, y1) of the jack body, centred in its zone
    ("a", "V"): (23.4, 8.35, 39.6, 24.85),
    ("a", "RA"): (23.6, -1.0, 39.5, 20.3),      # opening at the TOP edge (1 mm overhang, outline unchanged)
    ("b", "RA"): (96.4, 20.15, 117.7, 36.05),   # opening at the RIGHT edge (1 mm overhang)
    ("b", "V"): (96.7, 19.85, 112.9, 36.35),
}
W5500_GROUP = {"a": (23, 27, 43, 36), "b": (74, 27, 90, 42)}   # W5500 + 25 MHz + terminations, right under the jack

# ---- internal function groups (proposed; move freely at layout) -------------------------------------------------------
GROUPS = {   # name -> (x0, y0, x1, y1, note)
    "RP2350B + flash + 12 MHz + decoupling": (47, 23, 70, 45, "stock U3/U2 area; QFN-80 10x10; QSPI + crystal per RP2350 HW guide"),
    "Power: TVS, eFuse, buck, 1V1 LDO, polymer bulk": (74, 14, 91, 26, "next to PWR; the 3 A paths stay short"),
    "Light FETs x4 + PTC": (21, 42, 33, 51, "below the W5500 group, beside RGB Lights"),
    "Score inputs: ESD + R/C x8": (45, 51, 70, 60, "in-line above J11 (the stock C9-C18 row)"),
    "Button inputs: ESD + R/C x4": (22, 53, 34, 64, "beside the Buttons header"),
    "Audio: MAX98357A + filter + reservoir": (86, 54, 99, 64, "next to J20"),
    "USB host: ESD + 27R + TPS2553": (55, 7, 67, 15, "behind J18"),
    "Debug: USB-C (vertical) + CH340N": (94, 67, 108, 78, "former jack strip, reachable from above"),
    "Controls: RESET, BOOTSEL, LANE-ID DIP": (72, 67, 91, 76, "former jack strip, reachable from above"),
    "LEDs: PWR, FAULT, VBUS, STATUS + jack LEDs": (72, 78, 91, 82, "0603 row, visible from above, silk-labelled"),
    "SWD (JST SH)": (36, 70, 44, 76, "Raspberry Pi 3-pin debug"),
    "Labelled test points": (8, 69, 32, 80, "rails + SPI + USB + I2S + UART0"),
}


def clearances(zone, orient):
    """Edge-to-edge gaps (mm) from the RJ45 body to each harness body box and hole (holes as drill circles)."""
    x0, y0, x1, y1 = RJ45_FITS[(zone, orient)]
    out = {}
    for name, (a0, b0, a1, b1) in HARNESS.items():
        dx = max(a0 - x1, x0 - a1, 0)
        dy = max(b0 - y1, y0 - b1, 0)
        out[name] = round((dx ** 2 + dy ** 2) ** 0.5, 1)
    for name, (hx, hy) in HOLES.items():
        dx = max(x0 - hx, hx - x1, 0)
        dy = max(y0 - hy, hy - y1, 0)
        out[name] = round(max((dx ** 2 + dy ** 2) ** 0.5 - HOLE_DRILL / 2, -1.0), 1)
    return out


if __name__ == "__main__":
    for k, v in PADS.items():
        print(f"{k:12} {v}")
    print("pitches", PITCH, "J18 centre x", J18_CENTER_X)
    for k, v in HARNESS.items():
        print(f"{k:18} {v}")
    for k in RJ45_FITS:
        c = clearances(*k)
        print(k, {n: v for n, v in sorted(c.items(), key=lambda t: t[1])[:4]})
