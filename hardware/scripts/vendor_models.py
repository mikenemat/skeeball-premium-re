"""Vendor-shaped 3D models (STEP) for the connectors / switches KiCad has no model for, from the EasyEDA 3D model of
each part's JLC C-number (the model JLC's own assembly preview uses: real latches, keys, polarizing ribs, pegs).
    python vendor_models.py          fetch missing STEPs -> hardware/lib/3d/vendor/<C>.step + <C>.json (bbox sidecar)
    (place.py imports placement() to set each footprint's model offset / rotation)
Alignment: the EasyEDA model sits at the footprint's SVGNODE c_origin (EasyEDA canvas, 10 mil units) in the LCSC
footprint frame; the LCSC pads (jlc_footprints.footprint, mm, y up) are fitted onto our footprint's pads by pad number
(least-squares rotation + translation), and the same transform carries the model anchor into our frame. Height: THT
models already have the board top at z = 0 (pins below); SMD models are lifted so their lowest point sits on the board.
Every model is checked in a render before use (CLAUDE.md drawing QA); per-part corrections live in FIX below.
"""
import json
import math
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jlc_footprints as JF  # noqa: E402

ROOT = HERE.parent
OUT = ROOT / "hardware" / "lib" / "3d" / "vendor"
STEP_URL = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}"
U = 0.254                                      # EasyEDA canvas unit (10 mil) in mm

# footprint name -> JLC C-number whose EasyEDA model is used
VENDOR = {
    "Molex_Mini-Fit_Jr_39-30-3035_1x03_P4.20mm_Horizontal": "C505179",
    "Molex_Mini-Fit_Jr_39-30-1049_1x04_P4.20mm_Vertical": "C587488",
    "Molex_Mini-Fit_Jr_5566-08A_2x04_P4.20mm_Vertical": "C293503",
    "Molex_Mini-Fit_Jr_5569-02A2_2x01_P4.20mm_Horizontal": "C240831",
    "Molex_KK-396_A-41791-0002_1x02_P3.96mm_Vertical": "C505042",
    "USB_Micro-B_Amphenol_10118194-0001LF_Horizontal": "C132563",
    "USB_C_Receptacle_HRO_TYPE-C-31-D-06_Vertical": "C2689964",
    "RJ45_HanRun_HR963380AE_Vertical": "C19724763",
    "SW_DIP_XKB_DSIC04LS-P": "C319038",
    "SW_Push_1P1T_XKB_TS-1187A": "C318884",
}
# per-C-number corrections found in the render check: extra rotation (deg, x y z) and z offset (mm); "z" = model z of
# the board top surface where the model is not drawn with the board top at z = 0 (cross-section profile: the z where
# the section grows from the pin tails to the housing base)
FIX = {"C240831": {"z": 4.9,            # Mini-Fit 5569 RA 2-row: housing base at -4.9, tails / peg to -8.4
                   # q5 2026-10-27 (connector review): the tail fit put the housing face 1.2 mm past KiCad's 5569-02A2
                   # fab outline (board x 120.55 vs 119.35; stock overhang ~2.4 mm = 119.1; the EasyEDA body is not
                   # the Molex drawing's length about its tails): housing onto the fab outline, measured in the render
                   "off": (0.0, -1.2125, 0.0)},
       "C132563": {"z": 1.1},           # micro-B: shell body from -1.1 (legs below)
       "C2689964": {"z": 3.4},          # vertical USB-C: body -3.3 .. 2.9 (6.2 tall, HRO 6.40), legs below
       # HR963380AE (q6 2026-10-27, mech review M-4): the SMD lift sat the model on its locating-peg tips, 1.31 mm high
       # (top 18.16 vs HanRun p.2 16.85, pegs above the board): pegs back into their holes, top at 16.85
       "C19724763": {"z": -1.31}}
# symmetric bodies with repeated pad numbers (tactile switch: two pads per terminal): align the pad centroids only
CENTROID = {"C318884"}


def svgnode(c):
    ee = JF.load(c)["easyeda"]
    for s in ee["shapes"]:
        if s.startswith("SVGNODE"):
            return ee, json.loads(s.split("~", 1)[1])["attrs"]
    raise KeyError(f"{c}: no 3D model node")


def fetch(c):
    OUT.mkdir(parents=True, exist_ok=True)
    step = OUT / f"{c}.step"
    if not step.exists():
        _, a = svgnode(c)
        req = urllib.request.Request(STEP_URL.format(uuid=a["uuid"]), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        if not raw.startswith(b"ISO-10303-21"):
            raise ValueError(f"{c}: not a STEP file")
        step.write_bytes(raw)
    side = OUT / f"{c}.json"
    if not side.exists() or "tails" not in json.loads(side.read_text()):
        bb = step_bbox(step)
        side.write_text(json.dumps({"bbox": bb, "tails": step_tails(step, bb[2] + 0.3)}), encoding="utf-8")
    return step


def step_bbox(step):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    r = STEPControl_Reader()
    r.ReadFile(str(step))
    r.TransferRoots()
    b = Bnd_Box()
    BRepBndLib.Add_s(r.OneShape(), b)
    p, q = b.CornerMin(), b.CornerMax()
    return [round(v, 3) for v in (p.X(), p.Y(), p.Z(), q.X(), q.Y(), q.Z())]


def step_tails(step, z):
    """XY centres of the pin tails: the model cut by the plane z, section edges clustered (1 mm)."""
    from OCP.STEPControl import STEPControl_Reader
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    r = STEPControl_Reader()
    r.ReadFile(str(step))
    r.TransferRoots()
    sec = BRepAlgoAPI_Section(r.OneShape(), gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)))
    sec.Build()
    boxes = []
    e = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
    while e.More():
        b = Bnd_Box()
        BRepBndLib.Add_s(e.Current(), b)
        p, q = b.CornerMin(), b.CornerMax()
        boxes.append([p.X(), p.Y(), q.X(), q.Y()])
        e.Next()
    groups = []
    for bx in boxes:
        for g in groups:
            if bx[0] < g[2] + 1.0 and bx[2] > g[0] - 1.0 and bx[1] < g[3] + 1.0 and bx[3] > g[1] - 1.0:
                g[:] = [min(g[0], bx[0]), min(g[1], bx[1]), max(g[2], bx[2]), max(g[3], bx[3])]
                break
        else:
            groups.append(list(bx))
    return [[round((g[0] + g[2]) / 2, 3), round((g[1] + g[3]) / 2, 3)] for g in groups]


def fit(src, dst):
    """Rotation (deg, CCW, y up) + translation mapping src points onto dst (least squares), and the RMS residual."""
    n = len(src)
    sx, sy = sum(p[0] for p in src) / n, sum(p[1] for p in src) / n
    dx, dy = sum(p[0] for p in dst) / n, sum(p[1] for p in dst) / n
    num = sum((a[0] - sx) * (b[1] - dy) - (a[1] - sy) * (b[0] - dx) for a, b in zip(src, dst))
    den = sum((a[0] - sx) * (b[0] - dx) + (a[1] - sy) * (b[1] - dy) for a, b in zip(src, dst))
    th = math.atan2(num, den)
    if n == 1 or abs(math.degrees(th) / 90 - round(math.degrees(th) / 90)) < 0.05:
        th = math.radians(90 * round(math.degrees(th) / 90))        # snap to the drawing's right angles
    c, s = math.cos(th), math.sin(th)
    tx, ty = dx - (c * sx - s * sy), dy - (s * sx + c * sy)
    res = math.sqrt(sum((c * a[0] - s * a[1] + tx - b[0]) ** 2 + (s * a[0] + c * a[1] + ty - b[1]) ** 2
                        for a, b in zip(src, dst)) / n)
    return math.degrees(th), (tx, ty), res


def placement(fp_name, our_pads, smd, tht_pads=None, all_pads=None):
    """our_pads: {number: (x, y)} in our footprint frame (mm, y DOWN, unrotated); all_pads: every pad position (a part
    with repeated pad numbers - CENTROID - needs all of them). Returns (step path, offset xyz mm
    in KiCad's model frame (y up), rotation xyz deg, fit residual mm) or None when no vendor model is mapped."""
    c = VENDOR.get(fp_name)
    if not c:
        return None
    step = fetch(c)
    lc = JF.footprint(c)
    theirs = {}
    for p in lc["pads"]:
        theirs.setdefault(p["num"], (p["x"], p["y"]))
    common = sorted(k for k in our_pads if k in theirs and k.strip())
    if not common:
        raise ValueError(f"{fp_name}: no pad numbers in common with {c}")
    if c in CENTROID:                                     # every pad on both sides: a {number: pad} map keeps one
        if not all_pads:                                  # pad per number and puts the centroid half a body off
            raise ValueError(f"{fp_name}: CENTROID fit needs all_pads")
        a_, b_ = [(p["x"], p["y"]) for p in lc["pads"]], [(x, -y) for x, y in all_pads]
        th, res = 0.0, 0.0
        tx = sum(p[0] for p in b_) / len(b_) - sum(p[0] for p in a_) / len(a_)
        ty = sum(p[1] for p in b_) / len(b_) - sum(p[1] for p in a_) / len(a_)
    else:
        th, (tx, ty), res = fit([theirs[k] for k in common], [(our_pads[k][0], -our_pads[k][1]) for k in common])
    ee, a = svgnode(c)
    ox, oy = ee["origin"]
    ax, ay = [float(v) for v in a["c_origin"].split(",")]
    mx, my = (ax - ox) * U, -(ay - oy) * U                     # model anchor, LCSC frame (mm, y up)
    cs, sn = math.cos(math.radians(th)), math.sin(math.radians(th))
    off = [cs * mx - sn * my + tx, sn * mx + cs * my + ty, 0.0]
    side = json.loads((OUT / f"{c}.json").read_text())
    tails = FIX.get(c, {}).get("tails", side.get("tails"))   # FIX "tails": the pin tails only (no peg prongs)
    if tht_pads and tails and not smd:                   # pin tails onto our THT pads (EasyEDA anchors can be off)
        tl = [(cs * x - sn * y + off[0], sn * x + cs * y + off[1]) for x, y in tails]
        pads = [(x, -y) for x, y in tht_pads]
        pairs = [(t, min(pads, key=lambda q: (q[0] - t[0]) ** 2 + (q[1] - t[1]) ** 2)) for t in tl]
        pairs = [(t, q) for t, q in pairs if (q[0] - t[0]) ** 2 + (q[1] - t[1]) ** 2 < 16.0]
        if pairs:
            off[0] += sum(q[0] - t[0] for t, q in pairs) / len(pairs)
            off[1] += sum(q[1] - t[1] for t, q in pairs) / len(pairs)
    rx, ry, rz = [float(v) for v in a.get("c_rotation", "0,0,0").split(",")]
    rot = [-rx, -ry, -rz + th]
    if smd:
        off[2] = -side["bbox"][2]
    fx = FIX.get(c, {})
    rot = [r + d for r, d in zip(rot, fx.get("rot", (0, 0, 0)))]
    off[2] += fx.get("z", 0.0)
    off = [o + d for o, d in zip(off, fx.get("off", (0.0, 0.0, 0.0)))]
    return step, off, [r % 360 for r in rot], res


def main():
    for name, c in VENDOR.items():
        print(c, fetch(c).name, json.loads((OUT / f"{c}.json").read_text())["bbox"], name)


if __name__ == "__main__":
    main()
