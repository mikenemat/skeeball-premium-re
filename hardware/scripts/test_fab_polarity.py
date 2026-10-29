"""Self-test for fab_release.py's diode polarity check (2026-10-27, DECISIONS #23): it maps the LCSC symbol's A / K pin
names onto our A / K nets and must FAIL a genuinely reversed diode, whatever the dot does.

    python test_fab_polarity.py      (CPython; uses the cached LCSC footprints C2286 / C12624 / C84268 / C83333)

Cases on a KiCad LED_0603 (pad 1 = K at -0.79 mm, pad 2 = A at +0.79 mm, nets LED_K / LED_A), each part at KiCad
rotation 0 and 90:
  correct CPL (fit_part + cpl_rotation)              -> PASS (C2286: dot on the anode; C12624 / C84268: dot on the cathode)
  CPL rotation + 180 (JLC would place it reversed)   -> FAIL
  our footprint's A / K swapped on the board          -> FAIL with the CPL fitted to the unswapped board
  LCSC A / K names swapped (a library error)          -> FAIL with the CPL fitted to the real names
  C83333 TVS (LCSC pins named 1 / 2): dot rule        -> PASS; + 180 -> FAIL"""
import copy
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fab_release as FR  # noqa: E402
import jlc_footprints as JF  # noqa: E402


def board_fp(ref, kic_rot, fn1="K", fn2="A", x=50.0, y=-30.0, dx=0.79, w=0.9, h=0.95):
    pads = []
    for num, lx, fn in (("1", -dx, fn1), ("2", dx, fn2)):
        px, py = FR.rot(lx, 0.0, kic_rot)
        bw, bh = (w, h) if kic_rot % 180 == 0 else (h, w)
        pads.append({"num": num, "net": f"LED_{fn}" if fn in "AK" else f"N{num}", "fn": fn, "x": x + px, "y": y + py,
                     "w": bw, "h": bh})
    return {"ref": ref, "x": x, "y": y, "rot": kic_rot, "bottom": False, "fpid": "LED_SMD:LED_0603_1608Metric",
            "pads": pads}


def placed(fp, lc):
    off, (tx, ty), res, n, how = FR.fit_part(fp, lc)
    r = JF.cpl_rotation(fp["rot"], off, fp["bottom"])
    mx, my = FR.rot(tx, ty, fp["rot"])
    return r, (fp["x"] + mx, fp["y"] + my), how


def main():
    fails = []

    def expect(name, ok_want, ok, text):
        tag = "ok " if ok == ok_want else "BAD"
        print(f"{tag} {name}: {'PASS' if ok else 'FAIL'} ({text})")
        if ok != ok_want:
            fails.append(name)

    for c in ("C2286", "C12624", "C84268"):
        lc = JF.footprint(c)
        for kr in (0, 90):
            fp = board_fp("D2", kr)
            r, mid, how = placed(fp, lc)
            ok, t = FR.diode_polarity(fp, lc, r, mid)
            expect(f"{c} rot {kr} correct ({how})", True, ok, t)
            ok, t = FR.diode_polarity(fp, lc, (r + 180) % 360, mid)
            expect(f"{c} rot {kr} CPL +180", False, ok, t)
            ok, t = FR.diode_polarity(board_fp("D2", kr, fn1="A", fn2="K"), lc, r, mid)
            expect(f"{c} rot {kr} board A/K swapped", False, ok, t)
            bad_lc = copy.deepcopy(lc)
            bad_lc["pins"] = {n: {"A": "K", "K": "A"}.get(v, v) for n, v in lc["pins"].items()}
            ok, t = FR.diode_polarity(fp, bad_lc, r, mid)
            expect(f"{c} rot {kr} LCSC names swapped", False, ok, t)
    lc = JF.footprint("C83333")                       # SMB TVS, LCSC pins named '1' / '2'
    fp = board_fp("D1", 90, fn1="1", fn2="2", dx=2.15, w=1.8, h=2.2)
    r, mid, how = placed(fp, lc)
    ok, t = FR.diode_polarity(fp, lc, r, mid)
    expect(f"C83333 dot rule correct ({how})", True, ok, t)
    ok, t = FR.diode_polarity(fp, lc, (r + 180) % 360, mid)
    expect("C83333 dot rule CPL +180", False, ok, t)
    print(f"{'ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
