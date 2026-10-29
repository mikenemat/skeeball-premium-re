# ported from din8r-chassis-thermal/scripts/test_qa_placement.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/test_qa_placement.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN).
"""Fixtures for qa_placement.py (DIN-8R's M4 review placement classes as pre-route gates; CT port 2026-10-17).

Every check has a NEGATIVE fixture for each failure mode it names (it must FAIL with the right class, through the real
gate, on a board built in memory and saved with its own .kicad_pro - and a .kicad_dru only where a fixture needs one; CT
has none - to a temporary folder under .runtime/tmp) and a POSITIVE control:
  VIA-SITE         a GND pad (In1 plane, no outer pour) in open space; an F pad whose airwire partner is on B | the
                   same pad boxed in by foreign pads, inside a no-via rule area, between big NPTH holes, inside a FIXED
                   ECO_* power-cell zone (a base VSS_PRI_F pour there yields: passes), next to a pad whose class clearance
                   comes from the .kicad_pro, and from a .kicad_dru rule (both FAIL; Default clearance passes); a decap
                   ground pad whose only sites are > 0.5 mm away; the DRU in-pad escape mechanism (1206 / 0603 pass, 0402
                   FAILs); a boxed-in 0603 ground pad passes on its legal in-pad sites. Sites keep the 0.10 mm own-pad gap
                   and the CT via size (netclass: GND 0.6 / 0.3, a Power-class net 0.8 / 0.4; no .kicad_dru).
  DIFFPAIR-PLACE   PHY_TX_P / PHY_TX_N 49.9 R terminations (CT R98 / R99): mirrored pair passes | opposite faces,
                   crossed orientation, off the mirror position, unequal pin distance, one part in the other leg's
                   pin-axis corridor, no counterpart; the USB 22 R pair (R89 / R90 via DIFF_PLACE_MATES) pairs | without
                   the mate it has no counterpart
  FIDUCIAL-SPREAD  3 spread fiducials around a 0.5 mm pitch IC | fiducials clustered away from it, only 2, none (CT today)
  EP-VIA-PATTERN   three identical ICs with the same 2 x 2 EP grid | a via at the EP edge, 0.6 mm pitch, a foreign-net
                   via, one cell off the majority pattern (named), two cells with different patterns (no majority)
  PROT-GND         SMAJ15A ground pad with 2 vias within 1 mm, or in its own pour | with 1 via, with none; SMAJ58A's VSS
                   pad (PRI return) is a ground pad too; a documented PROT_GND_EXEMPT pad with 1 via passes (info) | with
                   none, or another pad listed, FAILs
  XSTACK-IC        interleaved opposite-face IC pin fields FAIL | the same ICs apart pass; an overlapping stack XSTACK
                   already FAILs is listed as covered, not repeated
  UNDERSAT         a cap under an unrelated opposite-face IC WARNs (status still PASS), also under a transformer (T) |
                   one sharing a net does not; an UNDERSAT_ACCEPT entry is info
  rules reader     DRU precedence / layer scope / netclass fallback; no DRU: netclass via sizes floored at board minimums
  real board       the adopted CT board runs (no tool error, < 60 s); with no fiducial on it, FIDUCIAL-SPREAD FAILs on F
KiCad Python: py scripts/local_run.py kicad_test_runner.py scripts/test_qa_placement.py   (or py -m pytest)
"""
import json
import shutil
import tempfile
from pathlib import Path

import board_const as K
import pcbnew

import qa_placement as gate

KICAD_PYTHON = True

ROOT = Path(__file__).resolve().parents[1]
(ROOT / ".runtime" / "tmp").mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="ct_placeq_", dir=str(ROOT / ".runtime" / "tmp")))
mm = pcbnew.FromMM
F, B_ = pcbnew.F_Cu, pcbnew.B_Cu
# CT's board rules (hardware/main/skeeball-controller.kicad_pro design_settings.rules)
RULES = {"min_clearance": 0.15, "min_hole_to_hole": 0.25, "min_hole_clearance": 0.25, "min_copper_edge_clearance": 0.3,
         "min_via_diameter": 0.6, "min_through_hole_diameter": 0.3, "min_via_annular_width": 0.15}
CT_CLASSES = [{"name": "Power", "clearance": 0.15, "track_width": 0.4, "via_diameter": 0.8, "via_drill": 0.4,
               "priority": -1},
              {"name": "Rail", "clearance": 0.15, "track_width": 0.2, "via_diameter": 0.6, "via_drill": 0.3,
               "priority": -1}]
CT_PATTERNS = [{"netclass": "Power", "pattern": n} for n in ("+12V", "VPP", "VSS", "PRTN", "SW_PRI", "SW_SEC")] + \
              [{"netclass": "Rail", "pattern": n} for n in ("+3V3", "+3V3A", "GND")]


def teardown_module():
    shutil.rmtree(TMP, ignore_errors=True)


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class Fx:
    def __init__(self, layers=4, edge=(0, 0, 60, 40)):
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(layers)
        self.nets, self.classes, self.assign, self.dru = {}, [], {}, ""
        x0, y0, x1, y1 = edge
        for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            s = pcbnew.PCB_SHAPE(self.b)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(V(*a))
            s.SetEnd(V(*c))
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(mm(0.1))
            self.b.Add(s)

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def part(self, ref, x, y, pads, value="", fpid="", back=False, rot=0, npth=()):
        """pads: [(num, dx, dy, net, w, h)] SMD rectangles; npth: [(dx, dy, drill)] unplated holes"""
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference(ref)
        fp.SetValue(value)
        if fpid:
            fp.SetFPID(pcbnew.LIB_ID("fx", fpid))
        self.b.Add(fp)
        for num, dx, dy, net, w, h in pads:
            p = pcbnew.PAD(fp)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECTANGLE)
            p.SetSize(pcbnew.F_Cu, V(w, h))
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetLayerSet(p.SMDMask())
            p.SetNumber(num)
            if net:
                p.SetNet(self.net(net))
            p.SetFPRelativePosition(V(dx, dy))
            fp.Add(p)
        for dx, dy, d in npth:
            p = pcbnew.PAD(fp)
            p.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_CIRCLE)
            p.SetSize(pcbnew.F_Cu, V(d, d))
            p.SetDrillSize(V(d, d))
            p.SetLayerSet(p.UnplatedHoleMask())
            p.SetFPRelativePosition(V(dx, dy))
            fp.Add(p)
        fp.SetPosition(V(x, y))
        if rot:
            fp.SetOrientationDegrees(rot)
        if back:
            fp.Flip(V(x, y), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        return fp

    def two(self, ref, x, y, n1, n2, size="0402", value="", back=False, vertical=False):
        w, h, d = {"0402": (0.56, 0.62, 0.48), "0603": (0.9, 1.0, 0.8), "0805": (1.0, 1.45, 0.95),
                   "1206": (1.15, 1.8, 1.475)}[size]
        pads = ([("1", 0, -d, n1, h, w), ("2", 0, d, n2, h, w)] if vertical else
                [("1", -d, 0, n1, w, h), ("2", d, 0, n2, w, h)])
        return self.part(ref, x, y, pads, value=value, fpid=f"R_{size}", back=back)

    def ic(self, ref, x, y, nets, pitch=0.5, pw=0.3, ph=1.0, row_dy=2.0, back=False, ep=None, value="", fpid=""):
        n = len(nets) // 2
        pads = []
        for k, net in enumerate(nets):
            row, col = divmod(k, n)
            pads.append((str(k + 1), (col - (n - 1) / 2) * pitch, -row_dy if row == 0 else row_dy, net, pw, ph))
        if ep:
            pads.append((str(len(nets) + 1), 0, 0, ep[0], ep[1], ep[2]))
        return self.part(ref, x, y, pads, back=back, value=value, fpid=fpid)

    def via(self, x, y, net, d=0.6, drill=0.3, free=False):
        """free=True: KiCad 10 re-nets a non-free via that sits in a pad to the pad's net on load; a foreign-net via
        fixture inside a pad must be a free via to keep its net"""
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(V(x, y))
        v.SetWidth(mm(d))
        v.SetDrill(mm(drill))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(net))
        if free:
            v.SetIsFree(True)
        self.b.Add(v)

    def zone(self, net, layer, pts, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(net))
        z.SetLocalClearance(mm(0.2))
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x), mm(y))
        self.b.Add(z)
        return z

    def plane(self, net="GND", layer=pcbnew.In1_Cu):
        return self.zone(net, layer, [(1, 1), (59, 1), (59, 39), (1, 39)], name=f"{net}_PLANE")

    def rule_area(self, name, pts, no_vias=True):
        z = pcbnew.ZONE(self.b)
        z.SetIsRuleArea(True)
        z.SetZoneName(name)
        z.SetLayerSet(pcbnew.LSET.AllCuMask())
        z.SetDoNotAllowVias(no_vias)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowZoneFills(False)
        z.SetDoNotAllowPads(False)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x), mm(y))
        self.b.Add(z)

    def netclass(self, name, clearance, nets, via=(0.6, 0.3)):
        self.classes.append({"name": name, "clearance": clearance, "track_width": 0.25, "via_diameter": via[0],
                             "via_drill": via[1], "priority": 5})
        for n in nets:
            self.assign[n] = [name]

    def save(self, name):
        if [z for z in self.b.Zones() if not z.GetIsRuleArea()]:
            pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        path = TMP / f"{name}.kicad_pcb"
        self.b.Save(str(path))
        pro = {"board": {"design_settings": {"rules": RULES}},
               "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.2,
                                             "via_diameter": 0.6, "via_drill": 0.3, "priority": 2147483647}]
                                + CT_CLASSES + self.classes, "netclass_assignments": self.assign,
                                "netclass_patterns": CT_PATTERNS}}
        path.with_suffix(".kicad_pro").write_text(json.dumps(pro), encoding="utf-8")
        dru = path.with_suffix(".kicad_dru")
        if self.dru:
            dru.write_text("(version 1)\n" + self.dru, encoding="utf-8")
        elif dru.exists():
            dru.unlink()
        return path

    def run(self, name, checks=gate.CHECKS):
        return gate.check(self.save(name), checks)


def expect(res, name, must_fail=(), must_pass=()):
    for c in must_fail:
        assert res["fails"][c], f"{name}: {c} did not fire: {res['counts']}"
    for c in must_pass:
        assert not res["fails"][c], f"{name}: {c} fired unexpectedly: {res['fails'][c][:3]}"
    return res


def find(res, check, **kw):
    return [x for x in res["fails"][check] if all(x.get(k) == v for k, v in kw.items())]


# ------------------------------------------------------------------------------------------------ VIA-SITE
def _gnd_cap(f, n1="SIGA", size="0402"):
    """C1 (n1 / GND) at (20, 20) on F; GND is an In1 plane net with no outer pour: C1.2 needs a via"""
    f.plane()
    f.two("C1", 20.0, 20.0, n1, "GND", size=size)


def _site_case(name, extra=None, n1="SIGA"):
    f = Fx()
    _gnd_cap(f, n1)
    if extra:
        extra(f)
    return f.run(name, ("VIA-SITE",))


def test_via_site_open_and_size():
    res = expect(_site_case("site_open"), "site_open", [], ["VIA-SITE"])
    assert res["info"]["via_site_pads_needing_via"].get("plane") == 1, res["info"]
    f = Fx()
    _gnd_cap(f)
    gate.VIA_SITE_MIN, keep = 10 ** 6, gate.VIA_SITE_MIN       # force a report row
    try:
        r = f.run("site_gap", ("VIA-SITE",))["fails"]["VIA-SITE"][0]
    finally:
        gate.VIA_SITE_MIN = keep
    assert r["via"] == [0.6, 0.3] and r["best_gap_mm"] >= gate.VIA_SITE_OWN_GAP_MM - 1e-9, r   # GND: Rail class


def test_via_site_power_class_via():
    """a Power-class net (CT .kicad_pro: +12V / VPP ... 0.8 / 0.4) gets the bigger via; +12V is a CT pour net (the
    flyback-cell pours) but a pad its fill does not touch is a routed pad: it needs a via to its B partner"""
    f = Fx()
    f.two("R1", 20, 20, "+12V", "SIGC", size="0603")
    f.two("R2", 30, 20, "+12V", "SIGD", size="0603", back=True)
    gate.VIA_SITE_MIN, keep = 10 ** 6, gate.VIA_SITE_MIN
    try:
        res = f.run("site_power_via", ("VIA-SITE",))
    finally:
        gate.VIA_SITE_MIN = keep
    rows = find(res, "VIA-SITE", net="+12V")
    assert rows and all(r["via"] == [0.8, 0.4] and r["need"] == "other-face partner" for r in rows), rows


def test_via_site_pour_net_landed_by_own_fill():
    """a pour-net pad its own fill touches is out of scope (landed by the pour); the same pad without the fill needs a
    via (other-face partner)"""
    def case(name, fill):
        f = Fx()
        f.two("R1", 20, 20, "+5V_IN", "SIGC", size="0603")
        f.two("R2", 30, 20, "+5V_IN", "SIGD", size="0603", back=True)
        if fill:
            f.zone("+5V_IN", F, [(17, 17), (19.9, 17), (19.9, 23), (17, 23)], name="PWR_5VIN_PTC_F")
        return f.run(name, ("VIA-SITE",))
    gate.VIA_SITE_MIN, keep = 10 ** 6, gate.VIA_SITE_MIN       # force a report row per pad that needs a via
    try:
        landed = {x["pad"] for x in case("site_pour_landed", True)["fails"]["VIA-SITE"]}
        open_ = {x["pad"] for x in case("site_pour_not_landed", False)["fails"]["VIA-SITE"]}
    finally:
        gate.VIA_SITE_MIN = keep
    assert landed == {"R2.1"} and open_ == {"R1.1", "R2.1"}, (landed, open_)


def test_via_site_boxed_fails():
    def boxed(f):
        """foreign pads ringing C1.2 (20.48, 20) so no via fits within 1.5 mm"""
        k = 0
        for x in [18.2 + 0.7 * i for i in range(10)]:
            for y in [18.0 + 0.7 * j for j in range(7)]:
                if abs(x - 20.48) < 0.6 and abs(y - 20) < 0.6 or abs(x - 19.52) < 0.6 and abs(y - 20) < 0.6:
                    continue
                k += 1
                f.part(f"X{k}", x, y, [("1", 0, 0, f"N{k}", 0.5, 0.5)])
    res = expect(_site_case("site_boxed", boxed), "site_boxed", ["VIA-SITE"])
    assert find(res, "VIA-SITE", pad="C1.2"), res["fails"]["VIA-SITE"]


def test_via_site_keepout():
    expect(_site_case("site_keepout", lambda f: f.rule_area("KO", [(17, 17), (24, 17), (24, 23), (17, 23)])),
           "site_keepout", ["VIA-SITE"])
    expect(_site_case("site_keepout_far", lambda f: f.rule_area("KO", [(40, 17), (44, 17), (44, 23), (40, 23)])),
           "site_keepout_far", [], ["VIA-SITE"])


def test_via_site_holes():
    def holes(f):
        f.part("MH1", 20.48, 20, [], npth=[(0, -2.1, 3.4), (0, 2.1, 3.4), (2.1, 0, 3.4), (-1.6, -1.6, 1.2),
                                         (-1.6, 1.6, 1.2), (-3.0, 0, 2.4)])
    expect(_site_case("site_holes", holes), "site_holes", ["VIA-SITE"])


def test_via_site_fixed_cell_zone_vs_base_pour():
    """an ECO_* power-cell zone never yields (FIXED_POUR_ZONE_RE); a base VSS pour of the same extent yields"""
    def pour(net, name):
        def add(f):
            f.zone(net, F, [(15, 15), (26, 15), (26, 25), (15, 25)], name=name)
        return add
    res = expect(_site_case("site_fixed_cell", pour("SW_PRI", "ECO_SWPRI_F")), "site_fixed_cell", ["VIA-SITE"])
    assert res["info"]["via_site_fixed_zones"] == ["ECO_SWPRI_F"], res["info"]
    res = expect(_site_case("site_base_pour_yields", pour("VSS", "VSS_PRI_F")), "site_base_pour_yields", [],
                 ["VIA-SITE"])
    assert res["info"]["via_site_fixed_zones"] == [], res["info"]


def _hv_pad(how):
    def add(f):                                           # an HVN frame ~1.3 mm around C1: sites only at 0.2 mm
        f.part("H1", 20, 20, [("1", -2.1, 0, "HVN", 0.6, 8.0), ("2", 3.2, 0, "HVN", 0.6, 8.0),
                              ("3", 0.5, -2.4, "HVN", 8.0, 0.6), ("4", 0.5, 2.4, "HVN", 8.0, 0.6)])
        if how == "pro":
            f.netclass("HVX", 2.2, ["HVN"])
        elif how == "dru":
            f.netclass("HVX", 0.15, ["HVN"])
            f.dru += '(rule "hv" (condition "A.hasNetclass(\'HVX\') && B.NetName == \'GND\'")' \
                     ' (constraint clearance (min 2.2mm)))\n'
    return add


def test_via_site_class_clearance():
    expect(_site_case("site_class_default", _hv_pad(None)), "site_class_default", [], ["VIA-SITE"])
    expect(_site_case("site_class_pro", _hv_pad("pro")), "site_class_pro", ["VIA-SITE"])
    expect(_site_case("site_class_dru", _hv_pad("dru")), "site_class_dru", ["VIA-SITE"])


def test_via_site_decap_ground_pad():
    def decap(block):
        def add(f):
            f.ic("U1", 20, 28, ["+3V3"] + [f"U{k}" for k in range(7)])
            if block:
                for k, (x, y) in enumerate([(21.3, 20), (20.48, 19.0), (20.48, 21.0), (21.2, 19.2), (21.2, 20.8),
                                            (19.5, 19.0), (19.5, 21.0)]):
                    f.part(f"X{k}", x, y, [("1", 0, 0, f"B{k}", 0.5, 0.5)])
        return add
    expect(_site_case("site_decap_open", decap(False), n1="+3V3"), "site_decap_open", [], ["VIA-SITE"])
    res = expect(_site_case("site_decap_far", decap(True), n1="+3V3"), "site_decap_far", ["VIA-SITE"])
    assert any("decap ground pad" in x["what"] for x in res["fails"]["VIA-SITE"]), res["fails"]["VIA-SITE"]


def test_via_site_other_face_partner():
    def partner(back):
        f = Fx()
        f.two("R1", 20, 20, "SIGB", "SIGC", size="0603")
        f.two("R2", 30, 20, "SIGB", "SIGD", size="0603", back=back)
        f.part("Y1", 20.0, 21.5, [("1", 0, 0, "Q1", 3.0, 1.2)])          # a blocker so the count matters
        return f.run(f"site_partner_{back}", ("VIA-SITE",))
    r = partner(True)
    assert r["info"]["via_site_pads_needing_via"].get("other-face partner", 0) >= 2, r["info"]
    r = partner(False)
    assert not r["info"]["via_site_pads_needing_via"].get("other-face partner"), r["info"]


def _hiz(size):
    f = Fx()
    f.netclass("HIZ", 0.2, ["HZ"])
    f.dru += '(rule "hiz vias" (condition "A.hasNetclass(\'HIZ\') && A.Type == \'Via\' && ' \
             'A.intersectsArea(\'HKO\')") (constraint disallow via))\n'
    f.two("R1", 20, 20, "HZ", "HZ2", size=size)
    f.two("R2", 40, 20, "HZ", "HZ3", size=size, back=True)
    w, h, d = {"0402": (0.56, 0.62, 0.48), "0603": (0.9, 1.0, 0.8), "1206": (1.15, 1.8, 1.475)}[size]
    x0, x1, y0, y1 = 20 - d - w / 2 - 0.1, 20 - d + w / 2 + 0.1, 20 - h / 2 - 0.1, 20 + h / 2 + 0.1
    for pts in ([(10, 10), (30, 10), (30, y0), (10, y0)], [(10, y1), (30, y1), (30, 30), (10, 30)],
                [(10, y0), (x0, y0), (x0, y1), (10, y1)], [(x1, y0), (30, y0), (30, y1), (x1, y1)]):
        f.rule_area("HKO", pts, no_vias=False)              # R1.1 cut out of the keep-out (pad + 0.1 mm)
    return f.run(f"site_hiz_{size}", ("VIA-SITE",))


# test_via_site_dru_inpad_escape: dropped in the SBC-1 port 2026-10-27 - SBC-1 has no via fill: no via-in-pad site ever counts (NO_VIP_FP_RE = ".")


# test_via_site_vip_counts_0603_not_0402: dropped in the SBC-1 port 2026-10-27 - SBC-1 has no via fill: no via-in-pad site ever counts (NO_VIP_FP_RE = ".")


# ------------------------------------------------------------------------------------------------ DIFFPAIR-PLACE
def _dp_case(name, r2=(25.0, 21.0), back=False, vertical=False, only_one=False):
    f = Fx()
    # anchor (T1-like): pins 1 / 2 (PHY_TX_P / PHY_TX_N) at x 22 (right column), the rest at x 18: pin axis +x, pair
    # axis y 20; CT R98 / R99: 49.9 R from each leg to +3V3A
    pads = [("1", 2, -0.25, "PHY_TX_P", 1.0, 0.3), ("2", 2, 0.25, "PHY_TX_N", 1.0, 0.3)]
    pads += [(str(k + 3), -2, -0.75 + 0.5 * k, f"A{k}", 1.0, 0.3) for k in range(4)]
    f.part("T1", 20, 20, pads, value="B1608S")
    f.two("R98", 25.0, 19.0, "PHY_TX_P", "+3V3A", size="0805", value="49.9 1%")
    if not only_one:
        f.two("R99", *r2, "PHY_TX_N", "+3V3A", size="0805", value="49.9 1%", back=back, vertical=vertical)
    return f.run(name, ("DIFFPAIR-PLACE",))


def _dp_probs(res):
    return " | ".join(p for x in res["fails"]["DIFFPAIR-PLACE"] for p in x.get("problems", [x.get("what", "")]))


def test_diffpair_mirrored_passes():
    res = expect(_dp_case("dp_mirrored"), "dp_mirrored", [], ["DIFFPAIR-PLACE"])
    assert res["info"]["diffpair_passive_pairs"] == 1, res["info"]


def test_diffpair_defects():
    for name, kw, word in (("dp_faces", {"back": True}, "faces differ"),
                           ("dp_orient", {"vertical": True}, "orientations differ"),
                           ("dp_mirror", {"r2": (25.0, 23.5)}, "not mirrored"),
                           ("dp_pindist", {"r2": (26.2, 21.0)}, "pin distance"),
                           ("dp_block", {"r2": (23.9, 20.6)}, "blocks T1.1"),
                           ("dp_alone", {"only_one": True}, "no counterpart")):
        res = expect(_dp_case(name, **kw), name, ["DIFFPAIR-PLACE"])
        assert word in _dp_probs(res), (name, _dp_probs(res))
    res = _dp_case("dp_pindist_only", r2=(26.2, 21.0))
    assert "not mirrored" not in _dp_probs(res), _dp_probs(res)       # the pin-distance case is isolated


def _usb(name):
    """CT USB: U8-like anchor with USB_DP / USB_DN pins; R89 / R90 22 R between USB_C_Dx and USB_Dx, mirrored"""
    f = Fx()
    pads = [("6", 2, -0.25, "USB_DP", 1.0, 0.3), ("4", 2, 0.25, "USB_DN", 1.0, 0.3),
            ("1", -2, -0.25, "USB_C_DP", 1.0, 0.3), ("3", -2, 0.25, "USB_C_DN", 1.0, 0.3)]
    f.part("U8", 20, 20, pads, value="USBLC6-2SC6")
    f.two("R89", 25.0, 19.0, "USB_C_DP", "USB_DP", size="0402", value="22")
    f.two("R90", 25.0, 21.0, "USB_C_DN", "USB_DN", size="0402", value="22")
    return f.run(name, ("DIFFPAIR-PLACE",))


def test_diffpair_usb_mates():
    res = expect(_usb("dp_usb_mates"), "dp_usb_mates", [], ["DIFFPAIR-PLACE"])
    assert res["info"]["diffpair_passive_pairs"] == 1, res["info"]
    saved = {k: list(v) for k, v in gate.DIFF_PLACE_MATES.items()}
    try:
        gate.DIFF_PLACE_MATES["main"] = []
        res = expect(_usb("dp_usb_no_mates"), "dp_usb_no_mates", ["DIFFPAIR-PLACE"])
        assert "no counterpart" in _dp_probs(res), _dp_probs(res)
    finally:
        gate.DIFF_PLACE_MATES.clear()
        gate.DIFF_PLACE_MATES.update(saved)


# ------------------------------------------------------------------------------------------------ FIDUCIAL-SPREAD
def _fid_case(name, fids):
    f = Fx()
    f.ic("U1", 30, 20, [f"N{k}" for k in range(8)])
    for k, (x, y) in enumerate(fids):
        f.part(f"FID{k + 1}", x, y, [("1", 0, 0, "", 1.0, 1.0)], fpid="Fiducial_1mm_Mask2mm")
    return f.run(name, ("FIDUCIAL-SPREAD",))


def test_fiducial_spread():
    expect(_fid_case("fid_spread_ok", [(5, 5), (55, 5), (5, 35)]), "fid_spread_ok", [], ["FIDUCIAL-SPREAD"])
    res = expect(_fid_case("fid_clustered", [(45, 30), (55, 30), (55, 38)]), "fid_clustered", ["FIDUCIAL-SPREAD"])
    assert res["fails"]["FIDUCIAL-SPREAD"][0]["parts"] == ["U1"], res["fails"]["FIDUCIAL-SPREAD"]
    expect(_fid_case("fid_two", [(5, 5), (55, 35)]), "fid_two", ["FIDUCIAL-SPREAD"])
    res = expect(_fid_case("fid_none", []), "fid_none", ["FIDUCIAL-SPREAD"])
    r = res["fails"]["FIDUCIAL-SPREAD"][0]
    assert r["side"] == "F" and r["fiducials"] == 0 and r["parts"] == ["U1"], r


# ------------------------------------------------------------------------------------------------ EP-VIA-PATTERN
GRID = [(-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)]


def _ep_case(name, pats, net="GND"):
    f = Fx()
    for k, pat in enumerate(pats):
        x = 12 + 15 * k
        f.ic(f"U{k + 1}", x, 20, [f"P{k}_{j}" for j in range(8)], pitch=0.5, row_dy=2.6, ep=("GND", 3.0, 3.0),
             value="QFNX", fpid="QFN_test")
        for dx, dy in pat:
            f.via(x + dx, 20 + dy, net, free=net != "GND")
    return f.run(name, ("EP-VIA-PATTERN",))


def test_ep_pattern_ok():
    res = expect(_ep_case("ep_ok", [GRID, GRID, GRID]), "ep_ok", [], ["EP-VIA-PATTERN"])
    assert res["info"]["ep_ics_with_vias"] == 3, res["info"]


def test_ep_margin_pitch_net():
    res = expect(_ep_case("ep_margin", [GRID + [(1.3, 0.0)]]), "ep_margin", ["EP-VIA-PATTERN"])
    assert "EP copper" in res["fails"]["EP-VIA-PATTERN"][0]["problems"][0], res["fails"]["EP-VIA-PATTERN"]
    res = expect(_ep_case("ep_pitch", [[(-0.3, 0.0), (0.3, 0.0)]]), "ep_pitch", ["EP-VIA-PATTERN"])
    assert "pitch" in " ".join(res["fails"]["EP-VIA-PATTERN"][0]["problems"]), res["fails"]["EP-VIA-PATTERN"]
    res = expect(_ep_case("ep_foreign", [GRID], net="+3V3"), "ep_foreign", ["EP-VIA-PATTERN"])
    assert "foreign-net" in " ".join(res["fails"]["EP-VIA-PATTERN"][0]["problems"]), res["fails"]["EP-VIA-PATTERN"]


def test_ep_identical_cells():
    res = expect(_ep_case("ep_odd_cell", [GRID, GRID, GRID[:3]]), "ep_odd_cell", ["EP-VIA-PATTERN"])
    assert res["fails"]["EP-VIA-PATTERN"][0]["off_pattern"] == ["U3"], res["fails"]["EP-VIA-PATTERN"]
    res = expect(_ep_case("ep_no_majority", [GRID, GRID[:3]]), "ep_no_majority", ["EP-VIA-PATTERN"])
    assert res["fails"]["EP-VIA-PATTERN"][0]["off_pattern"] == ["U1", "U2"], res["fails"]["EP-VIA-PATTERN"]


# ------------------------------------------------------------------------------------------------ PROT-GND
def _prot_case(name, vias=(), pour=False, value="SMAJ15A", sup="+12V", gnd="GND"):
    f = Fx()
    f.part("D7", 20, 20, [("1", -2.15, 0, sup, 2.5, 2.3), ("2", 2.15, 0, gnd, 2.5, 2.3)], value=value)
    for x, y in vias:
        f.via(x, y, gnd)
    if pour:
        f.zone(gnd, F, [(21, 17), (26, 17), (26, 23), (21, 23)], name=f"{gnd}_POUR")
    return f.run(name, ("PROT-GND",))


def test_prot_gnd_pass():
    expect(_prot_case("prot_two_vias", [(24.2, 19.5), (24.2, 20.5)]), "prot_two_vias", [], ["PROT-GND"])
    expect(_prot_case("prot_pour", pour=True), "prot_pour", [], ["PROT-GND"])


def test_prot_gnd_fail():
    expect(_prot_case("prot_one_via", [(24.2, 20.0)]), "prot_one_via", ["PROT-GND"])
    res = expect(_prot_case("prot_none"), "prot_none", ["PROT-GND"])
    assert res["fails"]["PROT-GND"][0]["pad"] == "D7.2", res["fails"]["PROT-GND"]
    # SMAJ58A across VPP / VSS (CT D3): the VSS pad is its ground pad (PRI return, qa_layout_quality.GROUND_RE)
    res = expect(_prot_case("prot_vss_none", value="SMAJ58A", sup="VPP", gnd="VSS"), "prot_vss_none", ["PROT-GND"])
    assert res["fails"]["PROT-GND"][0]["net"] == "VSS", res["fails"]["PROT-GND"]
    expect(_prot_case("prot_vss_two", [(24.2, 19.5), (24.2, 20.5)], value="SMAJ58A", sup="VPP", gnd="VSS"),
           "prot_vss_two", [], ["PROT-GND"])


def test_prot_gnd_exempt_mechanism():
    assert gate.PROT_GND_EXEMPT == {"main": {}}, "CT has no documented PROT-GND exceptions"
    saved = {k: dict(v) for k, v in gate.PROT_GND_EXEMPT.items()}
    try:
        gate.PROT_GND_EXEMPT["main"] = {"D7.2": "fixture: flow-through"}
        res = expect(_prot_case("prot_exempt_one", [(24.2, 20.0)]), "prot_exempt_one", [], ["PROT-GND"])
        assert res["info"].get("prot_exempt") == [["D7.2", 1, "fixture: flow-through"]], res["info"]
        expect(_prot_case("prot_exempt_none"), "prot_exempt_none", ["PROT-GND"])
        gate.PROT_GND_EXEMPT["main"] = {"D7.1": "fixture: another pad"}
        expect(_prot_case("prot_exempt_other", [(24.2, 20.0)]), "prot_exempt_other", ["PROT-GND"])
    finally:
        gate.PROT_GND_EXEMPT.clear()
        gate.PROT_GND_EXEMPT.update(saved)


# ------------------------------------------------------------------------------------------------ XSTACK-IC
def _xic_case(name, dx, dy=0.0):
    f = Fx()
    f.ic("U1", 20, 20, [f"A{k}" for k in range(8)], pitch=2.0, pw=0.5, ph=1.0, row_dy=2.0)
    f.ic("U2", 20 + dx, 20 + dy, [f"B{k}" for k in range(8)], pitch=2.0, pw=0.5, ph=1.0, row_dy=2.0, back=True)
    return f.run(name, ("XSTACK-IC",))


def test_xstack_ic():
    res = expect(_xic_case("xic_interleaved", 1.0), "xic_interleaved", ["XSTACK-IC"])
    assert res["fails"]["XSTACK-IC"][0]["parts"] == ["U1", "U2"], res["fails"]["XSTACK-IC"]
    expect(_xic_case("xic_apart", 20.0), "xic_apart", [], ["XSTACK-IC"])
    res = expect(_xic_case("xic_xstack_covered", 0.0), "xic_xstack_covered", [], ["XSTACK-IC"])
    assert res["info"]["xstack_ic_covered_by_XSTACK"] == [["U1", "U2"]], res["info"]


# ------------------------------------------------------------------------------------------------ UNDERSAT
def _usat_case(name, nets, big="U1"):
    f = Fx()
    f.ic(big, 20, 20, [f"A{k}" for k in range(8)], pitch=0.65, pw=0.4, ph=1.2, row_dy=2.7)
    f.two("C1", 20, 20, *nets, size="0402", back=True)
    return f.run(name, ("UNDERSAT",))


def test_undersat_warns_not_fails():
    res = expect(_usat_case("usat_unrelated", ("Z1", "GND")), "usat_unrelated", ["UNDERSAT"])
    assert res["status"] == "PASS", "UNDERSAT is WARN level: it must not fail the gate"
    expect(_usat_case("usat_related", ("A3", "GND")), "usat_related", [], ["UNDERSAT"])
    res = expect(_usat_case("usat_transformer", ("Z1", "GND"), big="T2"), "usat_transformer", ["UNDERSAT"])
    assert res["fails"]["UNDERSAT"][0]["under"] == "T2", res["fails"]["UNDERSAT"]


def test_undersat_accept_mechanism():
    assert gate.UNDERSAT_ACCEPT == {"main": {}}, "CT has no accepted satellites"
    saved = {k: dict(v) for k, v in gate.UNDERSAT_ACCEPT.items()}
    try:
        gate.UNDERSAT_ACCEPT["main"] = {"C1": "fixture: owner-accepted"}
        res = expect(_usat_case("usat_accepted", ("Z1", "GND")), "usat_accepted", [], ["UNDERSAT"])
        assert res["info"].get("undersat_accepted") == [["C1", "U1"]], res["info"]
        gate.UNDERSAT_ACCEPT["main"] = {"C2": "fixture: another part"}
        expect(_usat_case("usat_accepted_other", ("Z1", "GND")), "usat_accepted_other", ["UNDERSAT"])
    finally:
        gate.UNDERSAT_ACCEPT.clear()
        gate.UNDERSAT_ACCEPT.update(saved)


# ------------------------------------------------------------------------------------------------ rules reader
def test_rules_dru_and_netclass():
    f = Fx()
    f.netclass("HVX", 2.2, ["HVN"])
    f.dru = '(rule "a" (condition "A.hasNetclass(\'HVX\') && B.hasNetclass(\'Default\')") ' \
            '(constraint clearance (min 3.0mm)))\n(rule "b" (layer inner) (condition "A.hasNetclass(\'HVX\')") ' \
            '(constraint clearance (min 1.0mm)))\n(rule "gv" (condition "A.Type == \'Via\' && A.NetName == \'GV\'") ' \
            '(constraint via_diameter (min 0.7mm)) (constraint hole_size (min 0.35mm)))\n'
    path = f.save("rules")
    R = gate.Rules(path, pcbnew.LoadBoard(str(path)))
    assert R.clearance("SIG", "Via", "HVN", "Pad", "F.Cu") == 3.0                 # custom rule, both item orders
    assert R.clearance("SIG", "Via", "HVN", "Track", "In2.Cu") == 1.0             # the later, layer-scoped rule wins
    assert R.clearance("SIG", "Via", "OTHER", "Pad", "F.Cu") == 0.15               # netclass fallback (CT 0.15)
    assert R.via_size("GV") == (0.7, 0.35)                                         # a DRU via rule overrides


def test_rules_no_dru_netclass_vias():
    f = Fx()
    path = f.save("rules_nodru")
    assert not path.with_suffix(".kicad_dru").exists()
    R = gate.Rules(path, pcbnew.LoadBoard(str(path)))
    assert not R.dru and not R.unparsed
    assert R.via_size("SIG") == (0.6, 0.3) and R.via_size("GND") == (0.6, 0.3)    # Default / Rail
    assert R.via_size("+12V") == (0.8, 0.4) and R.via_size("VPP") == (0.8, 0.4)    # Power class
    assert R.clearance("SIG", "Via", "+12V", "Pad", "F.Cu") == 0.15


# ------------------------------------------------------------------------------------------------ real board
def test_real_board_runs():
    """the adopted CT board (read only): the gate runs without a tool error in < 60 s; a board without fiducials but
    with fine-pitch parts on F (CT today: U7 QFN-56, U9 LQFP-48, U6, J8 ...) FAILs FIDUCIAL-SPREAD on F"""
    assert K.MAIN_PCB.exists(), K.MAIN_PCB
    res = gate.check(K.MAIN_PCB)
    assert res["kind"] == "main" and res["status"] in ("PASS", "FAIL"), res["status"]
    assert res["info"]["total_s"] < 60, res["info"]["total_s"]
    b = pcbnew.LoadBoard(str(K.MAIN_PCB))
    fids = [fp for fp in b.GetFootprints() if "fiducial" in str(fp.GetFPID().GetLibItemName()).lower()
            or fp.GetReference().startswith("FID")]
    if not fids:
        assert {x["side"] for x in res["fails"]["FIDUCIAL-SPREAD"]} >= {"F"}, res["fails"]["FIDUCIAL-SPREAD"]


def test_every_check_has_fixtures():
    covered = {"VIA-SITE", "DIFFPAIR-PLACE", "FIDUCIAL-SPREAD", "EP-VIA-PATTERN", "PROT-GND", "XSTACK-IC", "UNDERSAT"}
    assert covered == set(gate.CHECKS), f"checks without fixtures: {set(gate.CHECKS) - covered}"
