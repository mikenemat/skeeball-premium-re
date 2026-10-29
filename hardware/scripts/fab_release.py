"""SBC-1 release package (CPython + kicad-cli; q5 2026-10-27). Method ported from din-relay-8ch
scripts/assembly_exports.py + qa_jlc_rotation.py (C:/work/din-relay-8ch): JLC places the LCSC / EasyEDA footprint of each
C-number, turned counter-clockwise (top view) by the CPL Rotation about ITS origin, with that origin on the CPL Mid X/Y.
So the CPL is NOT KiCad's position file: per placement the LCSC footprint (bom/easyeda_cache, jlc_footprints.py) is fitted
onto our footprint's pads (rotation snapped to 90 deg + translation, pads matched by number, polarised two-pad parts by
the LCSC symbol's anode / cathode / + names), and the CPL row = KiCad orientation + fitted offset, Mid = KiCad position +
the rotated origin offset (jlc_footprints.cpl_rotation, the din-relay formula). Every row is then verified the way
qa_jlc_rotation does: the LCSC pads, transformed by the CPL row exactly as JLC does, must land on our board pads of the
same number / function (centre error <= TOL_MM; q6: the landed pad's number - or its net, for EP / shell / tactile pairs -
is checked, not just "some pad"). A D ref passes polarity when the LCSC symbol's ANODE pad lands on our anode net and its
CATHODE pad on our cathode net (2026-10-27, DECISIONS #23: by pin names, not by the dot - C2286's layer-101 dot marks the
anode); the dot is reported, and decides only when the LCSC pins carry no A / K names (dot must be on our cathode).
Parts with no LCSC footprint get a CONFIRM row at their body centre. Self-test: test_fab_polarity.py.

    python fab_release.py BOARD OUT_DIR

Writes OUT_DIR/{gerbers/, sbc1-gerbers-drills-<date>.zip, sbc1-jlc-bom.csv, sbc1-jlc-cpl.csv, sbc1-cpl-qa.txt}; exit 1
when any placement fails the overlay check. bom.py report must have run (fab/assembly/sbc1-jlc-bom.csv)."""
import csv
import json
import math
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import jlc_footprints as JF  # noqa: E402

KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
KPY = r"C:/Program Files/KiCad/10.0/bin/python.exe"
TOL_MM = 0.25
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
DUMP = r'''
import json, sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); out = []
o = b.GetDesignSettings().GetAuxOrigin()
for fp in b.GetFootprints():
    pads = []
    for p in fp.Pads():
        if not p.IsOnCopperLayer():
            continue
        pos = p.GetPosition()
        pads.append({"num": p.GetNumber(), "net": p.GetNetname(), "fn": p.GetPinFunction(), "x":pcbnew.ToMM(pos.x - o.x), "y": -pcbnew.ToMM(pos.y - o.y),
                     "w": pcbnew.ToMM(p.GetBoundingBox().GetWidth()), "h": pcbnew.ToMM(p.GetBoundingBox().GetHeight())})
    q = fp.GetPosition()
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    bb = cy.BBox() if cy.OutlineCount() else fp.GetBoundingBox(False)
    c = bb.Centre()
    out.append({"ref": fp.GetReference(), "x": pcbnew.ToMM(q.x - o.x), "y": -pcbnew.ToMM(q.y - o.y),
                "cx": pcbnew.ToMM(c.x - o.x), "cy": -pcbnew.ToMM(c.y - o.y),
                "rot": fp.GetOrientationDegrees() % 360, "bottom": fp.GetLayer() == pcbnew.B_Cu,
                "fpid": fp.GetFPIDAsString(), "pads": pads})
json.dump(out, open(sys.argv[2], "w"))
'''


def rot(x, y, deg):
    a = math.radians(deg)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def pol_class(name):
    n = (name or "").strip().upper()
    if n in ("K", "C", "-", "CATHODE", "NEG") or n.startswith("K"):
        return "neg"
    if n in ("A", "+", "ANODE", "POS") or n.startswith("A"):
        return "pos"
    return None


def netlist_pins(net_path):
    """{(ref, pin): (pinfunction, net)} from the KiCad netlist the schematic build writes (hardware/main/*.net): the
    board's pads carry no pin function, the netlist carries the symbol pin names (Device:LED -> 'K_1' / 'A_2')"""
    import re
    out = {}
    if not net_path.exists():
        return out
    txt = net_path.read_text(encoding="utf-8")
    for m in re.finditer(r'\(net\s+\(code "[^"]*"\)\s+\(name "((?:[^"\\]|\\.)*)"\)(.*?)\n\t\t\)', txt, re.S):
        for n in re.finditer(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)(?:\s+\(pinfunction "([^"]*)"\))?', m.group(2)):
            out[(n.group(1), n.group(2))] = (n.group(3) or "", m.group(1))
    return out


def our_pol(fp):
    """{pad number: 'pos' / 'neg'} for our two-pad polarised parts, or {}. A D ref whose schematic pin names (the pads'
    pin functions = the symbol's A / K) give both classes uses them, so the map follows our A / K NETS (2026-10-27,
    DECISIONS #23); else the KiCad convention (LED_ / D_ pad 1 = cathode; polarised capacitor pad 1 = +)."""
    nums = sorted({p["num"] for p in fp["pads"]})
    if len(nums) != 2:
        return {}
    if fp["ref"].startswith("D"):
        by_fn = {p["num"]: pol_class(p.get("fn")) for p in fp["pads"]}
        if set(by_fn.values()) == {"pos", "neg"}:
            return by_fn
        return {n: "neg" if n == "1" else "pos" for n in nums}
    if "CP_Elec" in fp["fpid"]:
        return {n: "pos" if n == "1" else "neg" for n in nums}
    return {}


def our_class(fp, num):
    return our_pol(fp).get(num)


def lcsc_pol(lc):
    """{LCSC pad number: 'pos' / 'neg'} from the LCSC symbol's pin names (A / K / + / -), or {} when they do not
    name both polarities (e.g. a TVS whose pins are '1' / '2')"""
    cls = {num: pol_class(name) for num, name in (lc.get("pins") or {}).items()}
    return cls if set(v for v in cls.values() if v) >= {"pos", "neg"} else {}


def diode_polarity(fp, lc, r_cpl, mid):
    """(ok, text) for a D ref: transform the LCSC pads by the CPL row exactly as JLC does and require the LCSC ANODE pad
    on our anode net and the LCSC CATHODE pad on our cathode net (pin names, not the dot). The layer-101 dot is then
    reported as what it marks on this part. Without A / K names in the LCSC symbol the dot rule applies (the dot must
    sit on our cathode pad)."""
    ours = our_pol(fp)
    net_cls = {p["net"]: ours.get(p["num"]) for p in fp["pads"]}
    lpol = lcsc_pol(lc)
    name = {"pos": "anode", "neg": "cathode", None: "?"}

    def land(x, y):
        px, py = rot(x, y, r_cpl)
        return on_pad(px + mid[0], py + mid[1], fp["pads"])
    dot = ""
    if lc["marks"]:
        mxk, myk = rot(*lc["marks"][0], r_cpl)
        mxk, myk = mxk + mid[0], myk + mid[1]
        near = min(fp["pads"], key=lambda p: math.hypot(p["x"] - mxk, p["y"] - myk))
        lq = min((q for q in lc["pads"] if q["num"].strip()),
                 key=lambda q: math.hypot(q["x"] - lc["marks"][0][0], q["y"] - lc["marks"][0][1]))
        dot = (f"dot on LCSC pad {lq['num']} ({name[lpol.get(lq['num'])] if lpol else 'unnamed'}) -> our pad "
               f"{near['num']} ({name[ours.get(near['num'])]}, {near['net']})")
    if lpol:
        bad = []
        for q in lc["pads"]:
            c = lpol.get(q["num"])
            if c is None:
                continue
            hit = land(q["x"], q["y"])
            if hit is None or net_cls.get(hit["net"]) != c:
                bad.append(f"LCSC {name[c]} pad {q['num']} -> "
                           f"{'no pad' if hit is None else 'our ' + name[net_cls.get(hit['net'])] + ' ' + hit['net']}")
        if bad:
            return False, "POLARITY FAIL (pin names): " + "; ".join(bad) + (f"; {dot}" if dot else "")
        return True, "polarity by pin names: LCSC A -> our anode net, K -> our cathode net" + (f"; {dot}" if dot else "")
    if not dot:
        return False, "POLARITY FAIL: LCSC symbol names no A / K and the footprint has no polarity dot"
    if " (cathode, " not in dot.split("-> our pad")[1]:
        return False, f"POLARITY FAIL (dot rule, no A / K names): {dot}"
    return True, f"polarity by dot rule (LCSC pins unnamed): {dot}"


def fit_part(fp, lc):
    """best (offset deg, (tx, ty) LCSC origin in our local frame, residual mm, matched pairs, how) or None"""
    ours = {}
    for p in fp["pads"]:                               # our pads in the footprint's LOCAL frame (y up, unrotated)
        lx, ly = rot(p["x"] - fp["x"], p["y"] - fp["y"], -fp["rot"])
        ours.setdefault(p["num"], []).append((lx, ly, p))
    lcp = [p for p in lc["pads"] if p["num"].strip()]
    pairs_by_num = []
    two_pol = len(ours) == 2 and bool(our_pol(fp))
    cls_of = lcsc_pol(lc)
    if two_pol and cls_of:
        for q in lcp:
            c = cls_of.get(q["num"])
            tgt = next((n for n in ours if our_class(fp, n) == c), None)
            if tgt:
                pairs_by_num.append((q, tgt))
        how = "polarity names"
    if not pairs_by_num:
        pairs_by_num = [(q, q["num"]) for q in lcp if q["num"] in ours]
        how = "pad numbers"
    best = None
    for off in (0, 90, 180, 270):
        if not pairs_by_num:
            break
        src = [rot(q["x"], q["y"], off) for q, _ in pairs_by_num]
        # translation = mean (our pad - rotated LCSC pad), using the nearest same-number pad
        dst = []
        for (q, n), (sx, sy) in zip(pairs_by_num, src):
            dst.append(min(((x, y) for x, y, _ in ours[n]), key=lambda d: (d[0] - sx) ** 2 + (d[1] - sy) ** 2))
        tx = sum(d[0] - s[0] for d, s in zip(dst, src)) / len(src)
        ty = sum(d[1] - s[1] for d, s in zip(dst, src)) / len(src)
        res = max(math.hypot(s[0] + tx - d[0], s[1] + ty - d[1]) for d, s in zip(dst, src))
        if best is None or res < best[2] - 1e-6:
            best = (off, (tx, ty), res, len(src), how)
    if best is None or best[2] > 1.0:                  # repeated / foreign pad numbers (tactile switch): geometric
        allo = [(x, y) for v in ours.values() for x, y, _ in v]
        for off in (0, 90, 180, 270):
            src = [rot(q["x"], q["y"], off) for q in lcp]
            tx = sum(x for x, _ in allo) / len(allo) - sum(x for x, _ in src) / len(src)
            ty = sum(y for _, y in allo) / len(allo) - sum(y for _, y in src) / len(src)
            res = max(min(math.hypot(sx + tx - x, sy + ty - y) for x, y in allo) for sx, sy in src)
            if best is None or res < best[2] - 1e-6:
                best = (off, (tx, ty), res, len(src), "geometry (centroid, nearest pads)")
    return best


def on_pad(px, py, pads, slack=0.1):
    """the board pad whose box holds (px, py) (+ slack), else None"""
    hit = [p for p in pads if abs(px - p["x"]) <= p["w"] / 2 + slack and abs(py - p["y"]) <= p["h"] / 2 + slack]
    return min(hit, key=lambda p: math.hypot(px - p["x"], py - p["y"])) if hit else None


def main():
    board, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    g = out / "gerbers"
    if g.exists():
        shutil.rmtree(g)
    g.mkdir()
    subprocess.run([KCLI, "pcb", "export", "gerbers", "--output", str(g) + "/", "--layers", LAYERS,
                    "--subtract-soldermask", "--use-drill-file-origin", str(board)], check=True, capture_output=True)
    subprocess.run([KCLI, "pcb", "export", "drill", "--output", str(g) + "/", "--format", "excellon",
                    "--excellon-units", "mm", "--excellon-separate-th", "--drill-origin", "plot",
                    "--generate-map", "--map-format", "gerberx2", str(board)], check=True, capture_output=True)
    z = out / f"sbc1-gerbers-drills-{stamp}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(g.iterdir()):
            zf.write(f, f.name)
    shutil.copyfile(ROOT / "fab" / "assembly" / "sbc1-jlc-bom.csv", out / "sbc1-jlc-bom.csv")
    # CPL: board dump (KiCad python) + LCSC fit
    dump = out / "_board.json"
    tmp = out / "_dump.py"
    tmp.write_text(DUMP, encoding="utf-8")
    subprocess.run([KPY, str(tmp), str(board), str(dump)], check=True, capture_output=True)
    tmp.unlink()
    fps = {f["ref"]: f for f in json.loads(dump.read_text())}
    dump.unlink()
    # our A / K: the schematic pin names from the netlist (a D pad whose net disagrees with the netlist FAILs below)
    npins = netlist_pins(board.with_suffix(".net"))
    for f_ in fps.values():
        for p_ in f_["pads"]:
            fn, nnet = npins.get((f_["ref"], p_["num"]), ("", None))
            if not p_.get("fn"):
                p_["fn"] = fn
            p_["net_sch"] = nnet
    bom = json.loads((ROOT / "bom" / "bom.json").read_text(encoding="utf-8"))
    code = {}
    for l in bom["lines"]:
        for r in l["refs"]:
            code[r] = (l.get("jlc") or {}).get("code") or l.get("lcsc_design")
    rows, qa, bad = [], [], 0
    with open(out / "sbc1-jlc-bom.csv", encoding="utf-8") as fh:
        placed = [r.strip() for row in csv.DictReader(fh) for r in row["Designator"].split(",") if r.strip()]
    for ref in sorted(placed, key=lambda r: (r.rstrip("0123456789"), int("".join(c for c in r if c.isdigit()) or 0))):
        fp, c = fps.get(ref), code.get(ref)
        if fp is None:
            qa.append(f"FAIL {ref}: not on the board"); bad += 1
            continue
        try:
            lc = JF.footprint(c)
        except KeyError:
            lc = "missing"
        if lc is None or lc == "missing":
            # q6 (coordinator QA C3 / mfg m4): no LCSC footprint -> Mid = the part BODY centre (courtyard centre), not
            # the KiCad origin (the jacks' origin sits on the peg line), so JLC's engineer places the body where it is
            rows.append((ref, fp["cx"], fp["cy"], "Bottom" if fp["bottom"] else "Top", fp["rot"]))
            qa.append(f"CONFIRM {ref} {c}: no LCSC footprint ({'not cached' if lc == 'missing' else 'JLC has none'})"
                      f" -> body centre ({fp['cx']:.3f}, {fp['cy']:.3f}) / KiCad rotation {fp['rot']:.0f}; check in "
                      f"JLC's placement preview")
            continue
        f = fit_part(fp, lc)
        if f is None:
            rows.append((ref, fp["x"], fp["y"], "Top", fp["rot"]))
            qa.append(f"FAIL {ref} {c}: no pads in common with {lc['title']}"); bad += 1
            continue
        off, (tx, ty), res, n, how = f
        r_cpl = JF.cpl_rotation(fp["rot"], off, fp["bottom"])
        mx, my = rot(tx, ty, fp["rot"])
        mid = (fp["x"] + mx, fp["y"] + my)
        rows.append((ref, mid[0], mid[1], "Bottom" if fp["bottom"] else "Top", r_cpl))
        # verify: JLC's transform of every LCSC pad (rotate by the CPL rotation, put the origin on Mid)
        worst, miss, wrong, mech = 0.0, [], [], []
        # q6 (coordinator QA C5 / mfg m7): the pad an LCSC pad lands on must be the SAME pad: its number (or, for a
        # polarity-name fit, the pad of that polarity), else a pad of the same net (same function: EP / shell /
        # mounting / tactile pairs); a landing on another net's pad FAILs
        cls_of = lcsc_pol(lc)
        net_of = {}
        for p_ in fp["pads"]:
            net_of.setdefault(p_["num"], p_["net"])
        for q in lc["pads"]:
            if not q["num"].strip():
                continue
            px, py = rot(q["x"], q["y"], r_cpl)
            px, py = px + mid[0], py + mid[1]
            hit = on_pad(px, py, fp["pads"])
            if hit is None:
                miss.append(q["num"])
                continue
            worst = max(worst, math.hypot(px - hit["x"], py - hit["y"]))
            want = q["num"]
            if how == "polarity names":
                want = next((n for n in net_of if our_class(fp, n) == cls_of.get(q["num"])), q["num"])
            if hit["num"] == want or hit["net"] == net_of.get(want, "\0"):
                continue
            if (want not in net_of and not hit["num"].isdigit()) or how.startswith("geometry"):
                mech.append(f"{q['num']}->{hit['num']}")      # LCSC shell / mounting pad on our SH / MP pad, or the
            else:                                             # tactile switch pair map (repeated pad numbers)
                wrong.append(f"{q['num']}->{hit['num']}")
        mark, pol_bad = "", False
        if ref.startswith("D"):
            # 2026-10-27 (DECISIONS #23): a D ref is checked by the LCSC symbol's A / K pin names landing on our A / K
            # nets, not by where the dot sits (C2286's dot marks the ANODE, KENTO pad 1 = '+'); the dot is reported
            ok_pol, mark = diode_polarity(fp, lc, r_cpl, mid)
            drift = [p_["num"] for p_ in fp["pads"] if p_.get("net_sch") is not None and p_["net_sch"] != p_["net"]]
            if drift:
                ok_pol, mark = False, mark + f"; POLARITY FAIL: board net != netlist on pad {','.join(drift)}"
            pol_bad = not ok_pol
        elif lc["marks"] and any(p["num"] == "1" for p in fp["pads"]):
            mxk, myk = rot(*lc["marks"][0], r_cpl)
            mxk, myk = mxk + mid[0], myk + mid[1]
            near = min(fp["pads"], key=lambda p: math.hypot(p["x"] - mxk, p["y"] - myk))
            mark = f"mark->pad {near['num']}"
            polar = ref[0] in "UQ" or "CP_Elec" in fp["fpid"]
            if polar and near["num"] != "1" and not ref.startswith("Q"):
                mark += " (POLARITY?)"
        ok = not miss and not wrong and not pol_bad
        bad += not ok
        qa.append(f"{'PASS' if ok else 'FAIL'} {ref} {c} {lc['title']}: KiCad {fp['rot']:.0f} + offset {off} = CPL "
                  f"{r_cpl:.0f}, Mid shift ({mx:+.3f}, {my:+.3f}), fit by {how} ({n} pads), every LCSC pad centre on a "
                  f"board pad (worst centre offset {worst:.3f} mm){' MISSING ' + ','.join(miss) if miss else ''}"
                  f"{' WRONG PAD ' + ','.join(wrong) if wrong else ', pad numbers / functions match'}"
                  f"{' (mechanical / pair pads: ' + ','.join(mech) + ')' if mech else ''} {mark}")
    with open(out / "sbc1-jlc-cpl.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref, x, y, side, r in rows:
            w.writerow([ref, f"{x:.4f}mm", f"{y:.4f}mm", side, f"{r % 360:.1f}"])
    (out / "sbc1-cpl-qa.txt").write_text("\n".join(qa) + "\n", encoding="utf-8")
    print(f"release: {len(rows)} CPL rows, {bad} FAIL, "
          f"{sum(1 for q in qa if q.startswith('CONFIRM'))} confirm-in-preview -> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
