# ported from din8r-chassis-thermal/scripts/test_qa_silk.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/test_qa_silk.py (C:/work/din-relay-8ch), adapted for CT (4-layer MAIN, no generator / branding)
"""Fixtures for scripts/qa_silk.py, the CT silkscreen gate (placement marks first, DIN-8R owner 2026-10-05).

Every fixture is a board built in memory, saved with its own .kicad_pro under .runtime/tmp/<unique dir> and checked
through the real gate; each class has a NEGATIVE fixture (it must fire) and a POSITIVE control (it must not):
  PIN1-MISSING     SOIC-8 with a pin-1 dot, a diode with a cathode bar, an SOT-23 Q without a mark (not required) |
                   the SOIC without its dot, the diode with symmetric lines only, the dot under a neighbour's courtyard;
                   CT: a transformer (T) and an active buzzer (BZ) without a mark FAIL, with one they pass
  GUIDE-CLIPPED    the dot intact | the dot on its own pad 1 (mask opening), the dot under another part's courtyard
  OVER-PAD / MASK  a reference beside its part | a reference across a pad; a label across a board F.Mask opening
  OVERLAP          two refs apart; a footprint outline whose own segments cross (one drawing) | two refs on top of each
                   other (no priority between them: move None); a reference on a pin-1 dot: FAIL against the
                   REFERENCE (move = the ref, keep = the mark) and the dot is neither GUIDE-CLIPPED nor missing
  EDGE             a label 0.5 mm inside the edge | 0.1 mm inside, outside the board, 0.1 mm from an NPTH hole
  TEXT-SIZE        1.0 mm / 0.15 mm text | a 0.8 mm label, a 0.12 mm stroke reference, CT's 0.6 / 0.1 mm refs
  REF-MISSING      a visible ref on its side; a DNP part, an MH and a CT H mounting hole with none; a back part with a
                   mirrored B.SilkS ref | a hidden ref, a ref on F.Fab, a back part with its ref on F.SilkS, a ref off
                   the board
  REF omission     (DIN-8R owner 2026-10-07 dense-board disposition, CT root D-LAYOUT-GATES #5) a hidden ref listed in
                   a hash-valid <board stem>.silk_omit.json passes (info ref_omitted) | an unlisted hidden ref, a stale
                   sha256, a malformed manifest, a listed ref that is visible, DNP or not on the board; a listed ref
                   never excuses a missing pin-1 mark
  REF-AMBIGUOUS    a ref next to its own part | a ref against a neighbour's courtyard, far from its own part;
                   SILK_AMBIG_ACCEPT is empty on CT; a listed ref goes to info, marks are never accepted
  UNDER-PART       a ref under another part's courtyard: WARN (status PASS) | a board label under a part: FAIL
  DRC report       a real kicad-cli DRC of the overlap / pad fixture: KiCad's items merge with the geometry (source
                   'both'), a KiCad-only item is added (source 'kicad'); a report for another board or older than the
                   board is a tool error (CLI exit 2)
  board            a 2-layer board is a tool error (CT MAIN has 4); SILK-BRANDING is reported not applicable
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KICAD_PYTHON = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_const as LC  # noqa: E402

import pcbnew  # noqa: E402

import qa_silk as gate  # noqa: E402
import silk_marks  # noqa: E402

KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
TMP = None
mm = pcbnew.FromMM
F_S, B_S = pcbnew.F_SilkS, pcbnew.B_SilkS
ALL = gate.CHECKS


def setup_module():
    global TMP
    base = LC.ROOT / ".runtime" / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    TMP = Path(tempfile.mkdtemp(prefix="test_qa_silk_", dir=str(base)))


def teardown_module():
    if TMP is not None:
        shutil.rmtree(TMP, ignore_errors=True)


def tmp():
    if TMP is None:
        setup_module()
    return TMP


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def seg(parent, layer, a, c, w=0.15):
    s = pcbnew.PCB_SHAPE(parent)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*a))
    s.SetEnd(V(*c))
    s.SetLayer(layer)
    s.SetWidth(mm(w))
    parent.Add(s)
    return s


class Fx:
    def __init__(self, edge=(0, 0, 60, 40), layers=2):     # SBC-1: 2 copper layers (CT: 4)
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(layers)
        x0, y0, x1, y1 = edge
        for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            seg(self.b, pcbnew.Edge_Cuts, a, c, 0.1)

    def part(self, ref, x, y, pads, silk=(), dots=(), crt=None, ref_at=None, ref_layer=F_S, ref_visible=True,
             ref_size=1.0, ref_w=0.15, back=False, dnp=False, npth=()):
        """pads [(num, dx, dy, w, h)]; silk [((dx, dy), (dx, dy))] segments; dots [(dx, dy, r)] filled circles; crt
        (dx0, dy0, dx1, dy1) courtyard (default: pads + 0.5); ref_at (dx, dy) or None; all relative to (x, y)."""
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference(ref)
        self.b.Add(fp)
        fp.SetPosition(V(x, y))
        for num, dx, dy, w, h in pads:
            p = pcbnew.PAD(fp)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECTANGLE)
            p.SetSize(pcbnew.F_Cu, V(w, h))
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetLayerSet(p.SMDMask())
            p.SetNumber(num)
            fp.Add(p)
            p.SetFPRelativePosition(V(dx, dy))
        for dx, dy, d in npth:
            p = pcbnew.PAD(fp)
            p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_CIRCLE)
            p.SetSize(pcbnew.F_Cu, V(d, d))
            p.SetDrillSize(V(d, d))
            p.SetLayerSet(p.UnplatedHoleMask())
            fp.Add(p)
            p.SetFPRelativePosition(V(dx, dy))
        for a, c in silk:
            seg(fp, F_S, (x + a[0], y + a[1]), (x + c[0], y + c[1]))
        for dx, dy, r in dots:
            s = pcbnew.PCB_SHAPE(fp)
            s.SetShape(pcbnew.SHAPE_T_CIRCLE)
            s.SetCenter(V(x + dx, y + dy))
            s.SetEnd(V(x + dx + r, y + dy))
            s.SetFilled(True)
            s.SetWidth(mm(0.1))
            s.SetLayer(F_S)
            fp.Add(s)
        if crt is None:
            xs = [dx for _, dx, _, _, _ in pads] or [0]
            ys = [dy for _, _, dy, _, _ in pads] or [0]
            m = max([max(w, h) for *_, w, h in pads] or [1]) / 2 + 0.5
            crt = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
        c0x, c0y, c1x, c1y = crt
        for a, c in (((c0x, c0y), (c1x, c0y)), ((c1x, c0y), (c1x, c1y)), ((c1x, c1y), (c0x, c1y)),
                     ((c0x, c1y), (c0x, c0y))):
            seg(fp, pcbnew.F_CrtYd, (x + a[0], y + a[1]), (x + c[0], y + c[1]), 0.05)
        r = fp.Reference()
        r.SetLayer(ref_layer)
        r.SetVisible(ref_visible)
        r.SetTextSize(V(ref_size, ref_size))
        r.SetTextThickness(mm(ref_w))
        r.SetPosition(V(x + (ref_at or (0, 0))[0], y + (ref_at or (0, 0))[1]))
        fp.Value().SetVisible(False)
        if dnp:
            fp.SetDNP(True)
        if back:
            fp.Flip(V(x, y), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        return fp

    def soic(self, ref, x, y, dot=True, **kw):
        pads = [(str(k + 1), -1.905 + 1.27 * k, -2.5, 0.6, 1.5) for k in range(4)] + \
               [(str(k + 5), 1.905 - 1.27 * k, 2.5, 0.6, 1.5) for k in range(4)]
        silk = [((-2.0, -1.6), (2.0, -1.6)), ((-2.0, 1.6), (2.0, 1.6))]
        return self.part(ref, x, y, pads, silk=silk, dots=[(-2.9, -3.5, 0.25)] if dot is True else dot or (),
                         crt=(-3.4, -3.9, 3.4, 3.9), ref_at=kw.pop("ref_at", (0, 0)), **kw)

    def diode(self, ref, x, y, bar=True, **kw):
        pads = [("1", -1.65, 0, 0.9, 1.2), ("2", 1.65, 0, 0.9, 1.2)]
        silk = ([((-2.4, -1.0), (1.65, -1.0)), ((-2.4, 1.0), (1.65, 1.0)), ((-2.4, -1.0), (-2.4, 1.0))] if bar else
                [((-1.65, -1.0), (1.65, -1.0)), ((-1.65, 1.0), (1.65, 1.0))])
        return self.part(ref, x, y, pads, silk=silk, crt=(-2.7, -1.3, 2.6, 1.3), ref_at=kw.pop("ref_at", (0, -2.2)),
                         **kw)

    def res(self, ref, x, y, **kw):
        return self.part(ref, x, y, [("1", -0.8, 0, 0.8, 0.9), ("2", 0.8, 0, 0.8, 0.9)], crt=(-1.5, -0.75, 1.5, 0.75),
                         ref_at=kw.pop("ref_at", (0, -1.6)), **kw)

    def text(self, s, x, y, size=1.0, w=0.15, layer=F_S):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetLayer(layer)
        t.SetPosition(V(x, y))
        t.SetTextSize(V(size, size))
        t.SetTextThickness(mm(w))
        if layer == B_S:
            t.SetMirrored(True)
        self.b.Add(t)
        return t

    def mask_rect(self, x0, y0, x1, y1):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_RECT)
        s.SetStart(V(x0, y0))
        s.SetEnd(V(x1, y1))
        s.SetFilled(True)
        s.SetWidth(0)
        s.SetLayer(pcbnew.F_Mask)
        self.b.Add(s)

    def save(self, name):
        path = tmp() / f"{name}.kicad_pcb"
        self.b.Save(str(path))
        pro = {"board": {"design_settings": {
            "rules": {"min_clearance": 0.2, "min_copper_edge_clearance": 0.3, "min_silk_clearance": 0.0,
                      "min_text_height": 1.0, "min_text_thickness": 0.15},
            "rule_severities": {"silk_over_copper": "error", "silk_overlap": "error", "silk_edge_clearance": "error"}}}}
        path.with_suffix(".kicad_pro").write_text(json.dumps(pro), encoding="utf-8")
        return path

    def run(self, name, drc_report=None):
        return gate.check(self.save(name), drc_report=drc_report)


def expect(res, name, must_fail=(), must_pass=()):
    for c in must_fail:
        assert res["fails"][c], f"{name}: {c} did not fire: {res['counts']}"
    for c in must_pass:
        assert not res["fails"][c], f"{name}: {c} fired unexpectedly: {res['fails'][c][:3]}"
    return res


def others(*fired):
    return [c for c in ALL if c not in fired]


# ------------------------------------------------------------------------------------------------ clean board
def test_clean_board_passes():
    f = Fx()
    f.soic("U1", 15, 15)
    f.diode("D1", 35, 15)
    f.res("R1", 15, 30)
    f.part("Q1", 45, 30, [("1", -0.95, 1.0, 0.6, 0.7), ("2", 0.95, 1.0, 0.6, 0.7), ("3", 0, -1.0, 0.6, 0.7)],
           crt=(-1.7, -1.7, 1.7, 1.7), ref_at=(0, -2.6))                       # Q with no mark: not required
    f.part("MH1", 55, 35, [], npth=[(0, 0, 2.0)], ref_layer=pcbnew.F_Fab)       # NO_SILK_REF: no ref needed
    f.part("H1", 5, 35, [], npth=[(0, 0, 2.2)], ref_layer=pcbnew.F_Fab)         # CT mounting hole: no ref needed
    f.res("R9", 30, 32, dnp=True, ref_visible=False)                           # DNP: no ref needed
    f.text("DIN8-CT TEST", 30, 37)
    res = expect(f.run("clean"), "clean", [], ALL)
    assert res["status"] == "PASS" and res["info"]["marks_found"]["U1"] >= 1 and res["info"]["marks_found"]["D1"] >= 1, \
        res["info"]
    assert res["info"]["marks_found"].get("Q1") == 0, res["info"]["marks_found"]
    assert "SILK-BRANDING" in res["info"]["not_applicable"]


# ------------------------------------------------------------------------------------------------ PIN1 / GUIDE
def test_pin1_missing():
    f = Fx()
    f.soic("U1", 15, 15, dot=False)
    res = expect(f.run("pin1_no_dot"), "pin1_no_dot", ["SILK-PIN1-MISSING"], others("SILK-PIN1-MISSING"))
    assert "no pin-1" in res["fails"]["SILK-PIN1-MISSING"][0]["reason"], res["fails"]["SILK-PIN1-MISSING"]
    f = Fx()
    f.diode("D1", 30, 20, bar=False)
    expect(f.run("diode_no_bar"), "diode_no_bar", ["SILK-PIN1-MISSING"], others("SILK-PIN1-MISSING"))


def test_pin1_dot_covered_by_neighbour():
    f = Fx()
    f.soic("U1", 15, 15)
    f.res("R1", 10.6, 11.5, ref_at=(-3.0, 0))                                   # R1 courtyard over U1's dot
    res = expect(f.run("dot_covered"), "dot_covered", ["SILK-PIN1-MISSING", "SILK-GUIDE-CLIPPED"])
    g = res["fails"]["SILK-GUIDE-CLIPPED"][0]
    assert g["part"] == "U1" and any("courtyard R1" in x for x in g["by"]), g


def test_guide_clipped_by_own_pad():
    f = Fx()
    f.soic("U1", 15, 15, dot=[(-1.905, -2.5, 0.25), (-2.9, -3.5, 0.25)])      # one dot on the pad, one intact
    res = expect(f.run("dot_on_pad"), "dot_on_pad", ["SILK-GUIDE-CLIPPED"], ["SILK-PIN1-MISSING", "SILK-OVER-PAD"])
    assert any("U1.1" in x for x in res["fails"]["SILK-GUIDE-CLIPPED"][0]["by"]), res["fails"]["SILK-GUIDE-CLIPPED"]


def _transformer(f, ref, x, y, dot):
    """an SMD-16-like transformer (8 + 8 pads, symmetric): only a dot breaks the symmetry"""
    pads = [(str(k + 1), -4.445 + 1.27 * k, 4.25, 0.6, 2.0) for k in range(8)] + \
           [(str(16 - k), -4.445 + 1.27 * k, -4.25, 0.6, 2.0) for k in range(8)]
    silk = [((-5.5, -2.8), (5.5, -2.8)), ((-5.5, 2.8), (5.5, 2.8))]
    return f.part(ref, x, y, pads, silk=silk, dots=[(-5.6, 4.9, 0.25)] if dot else (), crt=(-6.2, -5.6, 6.2, 5.6),
                  ref_at=(0, 0))


def test_ct_transformer_and_buzzer_need_marks():
    """CT adaptation (silk_marks MARK_REQUIRED + T, BZ): a transformer assembled rotated swaps its windings across
    the PRI / SEC barrier; an active buzzer reversed stays silent"""
    f = Fx()
    _transformer(f, "T1", 20, 15, dot=False)
    f.part("BZ1", 45, 15, [("1", -3.8, 0, 1.5, 1.5), ("2", 3.8, 0, 1.5, 1.5)],
           silk=[((-5.5, -5.0), (5.5, -5.0)), ((-5.5, 5.0), (5.5, 5.0))], crt=(-6, -6, 6, 6), ref_at=(0, 0))
    res = expect(f.run("t_bz_no_mark"), "t_bz_no_mark", ["SILK-PIN1-MISSING"])
    assert sorted(e["part"] for e in res["fails"]["SILK-PIN1-MISSING"]) == ["BZ1", "T1"], res["fails"]
    f = Fx()
    _transformer(f, "T1", 20, 15, dot=True)
    f.part("BZ1", 45, 15, [("1", -3.8, 0, 1.5, 1.5), ("2", 3.8, 0, 1.5, 1.5)],
           silk=[((-5.5, -5.0), (5.5, -5.0)), ((-5.5, 5.0), (5.5, 5.0))], dots=[(-3.8, -2.0, 0.3)],
           crt=(-6, -6, 6, 6), ref_at=(0, 0))
    res = expect(f.run("t_bz_marked"), "t_bz_marked", [], ["SILK-PIN1-MISSING", "SILK-GUIDE-CLIPPED"])
    assert res["info"]["marks_found"]["T1"] >= 1 and res["info"]["marks_found"]["BZ1"] >= 1, res["info"]["marks_found"]


# ------------------------------------------------------------------------------------------------ OVER-PAD / MASK
def test_over_pad_and_mask():
    f = Fx()
    f.res("R1", 20, 20, ref_at=(0.8, 0))                                        # ref across pad 2
    res = expect(f.run("ref_on_pad"), "ref_on_pad", ["SILK-OVER-PAD"], ["SILK-OVER-MASK"])
    assert "R1.2" in res["fails"]["SILK-OVER-PAD"][0]["openings"], res["fails"]["SILK-OVER-PAD"]
    f = Fx()
    f.mask_rect(28, 28, 32, 32)
    f.text("LABEL", 30, 30)
    expect(f.run("text_on_mask"), "text_on_mask", ["SILK-OVER-MASK"], ["SILK-OVER-PAD"])


# ------------------------------------------------------------------------------------------------ OVERLAP + priority
def test_overlap_refs_stacked():
    f = Fx()
    f.res("R1", 20, 20)
    f.res("R2", 20, 23, ref_at=(0, -4.6))                                       # R2's ref on top of R1's
    res = expect(f.run("refs_stacked"), "refs_stacked", ["SILK-OVERLAP"])
    o = res["fails"]["SILK-OVERLAP"][0]
    assert o["move"] is None and o["roles"] == ["reference", "reference"], o


def test_overlap_own_outline_is_one_drawing():
    f = Fx()
    f.part("U5", 30, 20, [("1", -1, 0, 0.6, 0.6), ("2", 1, 0, 0.6, 0.6)],
           silk=[((-2, -1.5), (2, 1.5)), ((-2, 1.5), (2, -1.5))], ref_at=(0, -3))
    expect(f.run("own_outline_cross"), "own_outline_cross", [], ["SILK-OVERLAP"])


def test_overlap_ref_on_pin1_dot_moves_the_ref():
    f = Fx()
    f.soic("U1", 15, 15, ref_at=(0, 0))
    f.res("R1", 25, 12, ref_at=(15 - 2.9 - 25, 15 - 3.5 - 12))                  # R1's ref drawn over U1's dot
    res = expect(f.run("ref_on_dot"), "ref_on_dot", ["SILK-OVERLAP"], ["SILK-PIN1-MISSING", "SILK-GUIDE-CLIPPED"])
    o = next(x for x in res["fails"]["SILK-OVERLAP"] if "placement-mark" in x["roles"])
    assert o["move"].startswith("R1 ref") and o["keep"].startswith("U1 fpshape"), o
    assert silk_marks.SILK_PRIORITY[0] == "placement-mark"


# ------------------------------------------------------------------------------------------------ EDGE
def test_edge():
    f = Fx()
    f.text("EDGE", 10, 0.5 + 0.5 + 0.075)                                         # text box ~0.5 mm inside
    expect(f.run("edge_ok"), "edge_ok", [], ["SILK-EDGE"])
    f = Fx()
    f.text("EDGE", 10, 0.1 + 0.5 + 0.075)
    res = expect(f.run("edge_close"), "edge_close", ["SILK-EDGE"])
    assert "board edge" in res["fails"]["SILK-EDGE"][0]["why"][0], res["fails"]["SILK-EDGE"]
    f = Fx()
    f.text("OFF", 10, 41.5)
    res = expect(f.run("edge_off"), "edge_off", ["SILK-EDGE"])
    assert "outside" in res["fails"]["SILK-EDGE"][0]["why"][0], res["fails"]["SILK-EDGE"]
    f = Fx()
    f.part("MH1", 30, 20, [], npth=[(0, 0, 3.0)], ref_layer=pcbnew.F_Fab)
    f.text("HOLE", 30, 20 + 1.5 + 0.1 + 0.575)
    res = expect(f.run("edge_hole"), "edge_hole", ["SILK-EDGE"])
    assert "NPTH" in res["fails"]["SILK-EDGE"][0]["why"][0], res["fails"]["SILK-EDGE"]


# ------------------------------------------------------------------------------------------------ TEXT-SIZE
def test_text_size():
    f = Fx()
    f.text("SMALL", 30, 20, size=0.8, w=0.15)
    f.res("R1", 30, 30, ref_w=0.12)
    res = expect(f.run("text_small"), "text_small", ["SILK-TEXT-SIZE"])
    assert len(res["fails"]["SILK-TEXT-SIZE"]) == 2, res["fails"]["SILK-TEXT-SIZE"]
    f = Fx()
    f.res("R1", 30, 30, ref_size=0.6, ref_w=0.1)                                  # CT rev A refs (QA_LOG QA-SILK)
    res = expect(f.run("text_ct_refs"), "text_ct_refs", ["SILK-TEXT-SIZE"])
    e = res["fails"]["SILK-TEXT-SIZE"][0]
    assert e["height_mm"] == 0.6 and e["stroke_mm"] == 0.1 and e["part"] == "R1", e
    assert gate.TEXT_MIN_H_MM == 1.0 and gate.TEXT_MIN_W_MM == 0.15     # the JLC limit is not lowered
    f = Fx()
    f.res("R1", 30, 30)                                                          # 1.0 / 0.15 passes
    expect(f.run("text_ok"), "text_ok", [], ["SILK-TEXT-SIZE"])


# ------------------------------------------------------------------------------------------------ REF-MISSING
def test_ref_missing():
    for name, kw in (("ref_hidden", dict(ref_visible=False)), ("ref_on_fab", dict(ref_layer=pcbnew.F_Fab)),
                     ("ref_off_board", dict(ref_at=(0, 25)))):
        f = Fx()
        f.res("R1", 20, 20, **kw)
        res = expect(f.run(name), name, ["SILK-REF-MISSING"])
        assert res["fails"]["SILK-REF-MISSING"][0]["part"] == "R1", res["fails"]["SILK-REF-MISSING"]


def test_ref_back_side():
    f = Fx()
    f.res("R1", 20, 20, back=True)                                              # flipped: ref goes to B.SilkS mirrored
    expect(f.run("ref_back_ok"), "ref_back_ok", [], ["SILK-REF-MISSING"])
    f = Fx()
    fp = f.res("R1", 20, 20, back=True)
    fp.Reference().SetLayer(F_S)                                                # back part, ref on the front
    fp.Reference().SetMirrored(False)
    expect(f.run("ref_back_wrong_side"), "ref_back_wrong_side", ["SILK-REF-MISSING"])


# ------------------------------------------------------------------------------------------------ REF omission manifest
def _omit(path, refs, sha=None):
    """write <board stem>.silk_omit.json (scripts/pcb_silk.py's manifest) for `refs`, bound to the board's sha256"""
    import hashlib
    m = {"schema": "ct-silk-omit/1", "sha256": sha or hashlib.sha256(Path(path).read_bytes()).hexdigest(),
         "refs": {r: {"side": "F", "why": "fixture"} for r in refs}}
    Path(path).with_suffix(gate.OMIT_SUFFIX).write_text(json.dumps(m), encoding="utf-8")


def test_ref_omission_manifest_accepts_listed_hidden_refs():
    """a hidden reference listed in a hash-valid manifest passes and is reported in info ref_omitted"""
    assert gate.OMIT_SUFFIX == ".silk_omit.json"
    f = Fx()
    f.res("R1", 20, 20, ref_visible=False)
    f.res("R2", 30, 20)
    fp = f.res("R3", 40, 20, back=True)
    fp.Reference().SetVisible(False)
    path = f.save("omit_ok")
    _omit(path, ["R1", "R3"])
    res = expect(gate.check(path), "omit_ok", [], ALL)
    assert res["status"] == "PASS" and sorted(res["info"]["ref_omitted"]) == ["R1", "R3"], res["info"]
    assert res["info"]["ref_omit_manifest"]["valid"] and res["info"]["ref_omit_manifest"]["listed"] == 2
    assert gate.main([str(path)]) == 0


def test_ref_omission_manifest_rejects():
    # an unlisted hidden reference still fails (only the exact recorded set is accepted)
    f = Fx()
    f.res("R1", 20, 20, ref_visible=False)
    f.res("R3", 30, 20, ref_visible=False)
    path = f.save("omit_unlisted")
    _omit(path, ["R1"])
    res = expect(gate.check(path), "omit_unlisted", ["SILK-REF-MISSING"])
    assert [e["part"] for e in res["fails"]["SILK-REF-MISSING"]] == ["R3"], res["fails"]["SILK-REF-MISSING"]
    assert res["info"]["ref_omitted"] == ["R1"]
    # a stale manifest (another board / the board changed after pcb_silk.py) accepts nothing and fails itself
    f = Fx()
    f.res("R1", 20, 20, ref_visible=False)
    path = f.save("omit_stale")
    _omit(path, ["R1"], sha="0" * 64)
    res = expect(gate.check(path), "omit_stale", ["SILK-REF-MISSING"])
    e = res["fails"]["SILK-REF-MISSING"]
    assert any("stale" in x["why"] for x in e) and any(x["part"] == "R1" for x in e), e
    assert not res["info"]["ref_omit_manifest"]["valid"] and "ref_omitted" not in res["info"]
    assert gate.main([str(path)]) == 1
    # a malformed manifest fails
    f = Fx()
    f.res("R1", 20, 20)
    path = f.save("omit_bad")
    path.with_suffix(gate.OMIT_SUFFIX).write_text("{not json", encoding="utf-8")
    res = expect(gate.check(path), "omit_bad", ["SILK-REF-MISSING"])
    assert "unreadable" in res["fails"]["SILK-REF-MISSING"][0]["why"], res["fails"]["SILK-REF-MISSING"]
    # a listed reference that is actually visible on the silk fails (the manifest lists hidden references only)
    f = Fx()
    f.res("R1", 20, 20)
    path = f.save("omit_visible")
    _omit(path, ["R1"])
    res = expect(gate.check(path), "omit_visible", ["SILK-REF-MISSING"])
    e = res["fails"]["SILK-REF-MISSING"]
    assert len(e) == 1 and e[0]["part"] == "R1" and "visible" in e[0]["why"], e
    # a listed DNP part or a designator that is not on the board fails
    f = Fx()
    f.res("R1", 20, 20)
    f.res("R9", 30, 20, dnp=True, ref_visible=False)
    path = f.save("omit_dnp")
    _omit(path, ["R9", "R77"])
    res = expect(gate.check(path), "omit_dnp", ["SILK-REF-MISSING"])
    e = res["fails"]["SILK-REF-MISSING"]
    assert sorted(x["part"] for x in e) == ["R77", "R9"] and all("not an assembled part" in x["why"] for x in e), e


def test_ref_omission_never_excuses_marks():
    """placement / pin-1 / polarity cues are never omitted: a listed IC without its dot still fails PIN1-MISSING"""
    f = Fx()
    f.soic("U1", 15, 15, dot=False, ref_visible=False)
    path = f.save("omit_no_mark")
    _omit(path, ["U1"])
    res = expect(gate.check(path), "omit_no_mark", ["SILK-PIN1-MISSING"], others("SILK-PIN1-MISSING"))
    assert res["info"]["ref_omitted"] == ["U1"] and res["status"] == "FAIL"


# ------------------------------------------------------------------------------------------------ REF-AMBIGUOUS
def test_ref_ambiguous():
    f = Fx()
    f.res("R1", 20, 20)
    f.soic("U1", 30, 20, ref_at=(0, 0))
    expect(f.run("amb_ok"), "amb_ok", [], ["SILK-REF-AMBIGUOUS"])
    f = Fx()
    f.res("R1", 20, 20, ref_at=(5.2, 0))                                        # R1's ref against U1's courtyard
    f.soic("U1", 30, 20, ref_at=(0, 0))
    res = expect(f.run("amb_ref"), "amb_ref", ["SILK-REF-AMBIGUOUS"])
    a = res["fails"]["SILK-REF-AMBIGUOUS"][0]
    assert a["part"] == "R1" and a["nearest"] == "U1", a


def test_ambig_accept_list_and_marks_never_accepted():
    assert gate.SILK_AMBIG_ACCEPT == {}, "CT has no accepted ambiguous designators"
    saved = dict(gate.SILK_AMBIG_ACCEPT)
    try:
        gate.SILK_AMBIG_ACCEPT["R1"] = "fixture"
        f = Fx()
        f.res("R1", 20, 20, ref_at=(5.2, 0))
        f.soic("U1", 26, 20, ref_at=(0, -4.6))
        res = expect(f.run("amb_listed"), "amb_listed", [], ["SILK-REF-AMBIGUOUS"])
        assert [x["part"] for x in res["info"].get("ref_ambiguous_accepted", [])] == ["R1"], res["info"]
        gate.SILK_AMBIG_ACCEPT["U1"] = "fixture"                                 # marks stay strict
        f = Fx()
        f.soic("U1", 15, 15, dot=False)
        expect(f.run("amb_listed_no_mark"), "amb_listed_no_mark", ["SILK-PIN1-MISSING"])
        f = Fx()
        f.soic("U1", 15, 15)
        f.res("R1", 30, 30, ref_at=(15 - 2.9 - 30, 15 - 3.5 - 30))              # R1's designator on U1's pin-1 dot
        res = expect(f.run("amb_listed_ref_on_mark"), "amb_listed_ref_on_mark", ["SILK-OVERLAP"])
        assert any(x.get("keep") and "U1" in x["keep"] for x in res["fails"]["SILK-OVERLAP"]), res["fails"]
    finally:
        gate.SILK_AMBIG_ACCEPT.clear()
        gate.SILK_AMBIG_ACCEPT.update(saved)


# ------------------------------------------------------------------------------------------------ UNDER-PART
def test_under_part():
    f = Fx()
    f.soic("U1", 30, 20, ref_at=(0, -5))
    f.res("R1", 20, 20, ref_at=(10, 0))                                         # R1's ref inside U1's courtyard
    res = expect(f.run("under_ref"), "under_ref", [], ["SILK-UNDER-PART"])
    assert res["warns"]["SILK-UNDER-PART"] and res["warns"]["SILK-UNDER-PART"][0]["under"] == ["U1"], res["warns"]
    f = Fx()
    f.soic("U1", 30, 20, ref_at=(0, -5))
    f.text("LINE", 30, 20)                                                      # a board label under U1's body
    res = expect(f.run("under_label"), "under_label", ["SILK-UNDER-PART"])
    assert res["status"] == "FAIL" and res["fails"]["SILK-UNDER-PART"][0]["level"] == "FAIL"


# ------------------------------------------------------------------------------------------------ board / tool errors
def test_four_layer_board_is_a_tool_error():
    f = Fx(layers=4)
    f.res("R1", 20, 20)
    path = f.save("four_layer")
    try:
        gate.check(path)
        raise AssertionError("a 4-layer board was accepted as SBC-1 main")
    except ValueError as e:
        assert "copper layers" in str(e)
    assert gate.main([str(path)]) == 2


# ------------------------------------------------------------------------------------------------ KiCad DRC report
def _drc(path, out):
    from local_run import environment
    r = subprocess.run([KCLI, "pcb", "drc", "--format", "json", "--severity-all", "-o", str(out), str(path)],
                       capture_output=True, text=True, timeout=300, env=environment())
    assert out.exists(), r.stdout + r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_drc_report_merge_and_identity():
    f = Fx()
    f.res("R1", 20, 20, ref_at=(0.8, 0))                                        # silk_over_copper
    f.res("R2", 40, 20)
    f.res("R3", 40, 23, ref_at=(0, -4.6))                                       # silk_overlap
    path = f.save("drc_fx")
    time.sleep(1.1)                                                             # the report's 1 s date after the save
    rep = tmp() / "drc_fx-drc.json"
    kv = [v["type"] for v in _drc(path, rep)["violations"]]
    assert "silk_over_copper" in kv and "silk_overlap" in kv, kv
    res = gate.check(path, drc_report=rep)
    srcs = {c: {e["source"] for e in res["fails"][c]} for c in ("SILK-OVER-PAD", "SILK-OVERLAP")}
    assert "both" in srcs["SILK-OVER-PAD"] and "both" in srcs["SILK-OVERLAP"], srcs
    # a KiCad-only finding (an item pair the geometry does not see) is kept, source 'kicad'
    data = json.loads(rep.read_text(encoding="utf-8"))
    b = pcbnew.LoadBoard(str(path))
    u1, u2 = (b.FindFootprintByReference(x).Reference().m_Uuid.AsString() for x in ("R1", "R2"))
    data["violations"].append({"type": "silk_overlap", "severity": "error", "description": "Silkscreen clearance",
                               "items": [{"uuid": u1, "description": "Reference field of R1"},
                                         {"uuid": u2, "description": "Reference field of R2"}]})
    extra = tmp() / "drc_extra.json"
    extra.write_text(json.dumps(data), encoding="utf-8")
    res = gate.check(path, drc_report=extra)
    assert any(e["source"] == "kicad" for e in res["fails"]["SILK-OVERLAP"]), res["fails"]["SILK-OVERLAP"]
    # a report for another board: tool error
    data["source"] = "other-board.kicad_pcb"
    extra.write_text(json.dumps(data), encoding="utf-8")
    try:
        gate.check(path, drc_report=extra)
        raise AssertionError("a DRC report for another board was accepted")
    except ValueError as e:
        assert "DRC-WRONG-BOARD" in str(e)
    assert gate.main([str(path), "--drc-report", str(extra)]) == 2
    # the board changed after the DRC: stale report, tool error
    t = time.time() + 5
    os.utime(path, (t, t))
    try:
        gate.check(path, drc_report=rep)
        raise AssertionError("a stale DRC report was accepted")
    except ValueError as e:
        assert "DRC-STALE" in str(e)
    assert gate.main([str(path), "--drc-report", str(rep)]) == 2
