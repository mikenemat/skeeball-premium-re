# ported from din8r-chassis-thermal/scripts/test_qa_layout_quality.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/test_qa_layout_quality.py (C:/work/din-relay-8ch), adapted for CT (one board kind, CT nets).
"""Fixtures for qa_layout_quality.py (KiCad Python, via scripts/conftest.py or
`py scripts/local_run.py kicad_test_runner.py scripts/test_qa_layout_quality.py`).

Every check has a NEGATIVE fixture for each failure mode it names (it must FAIL through the real gate on a board built
in memory and saved under .runtime/tmp) and a POSITIVE control (the compliant variant passes that check) - the parent's
fixture set with CT nets (+12V / +3V3 / GND / PRTN budget, ETH_SCLK SI net, MDI pairs without impedance control). The
per-board exemption tables are EMPTY on CT: their mechanisms are still tested with synthetic entries (listed -> info,
unlisted / other ref -> FAIL). CT scope corrections tested: LED parts are not POWER-PAD-CONN rail diodes and LED current
limiters are not SERIES-TERM terminations; U10 (ambient sensor, function-pinned) is skipped by PLACE-ORIENT; the
parent's RS shunt-ring VIA-PADGAP exemption is gone. The last test runs the gate on the adopted CT board.
"""
import math
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as K  # noqa: E402
import pcbnew  # noqa: E402

import qa_copper_landing as QL  # noqa: E402
import qa_layout_quality as gate
import current_budget as cb  # noqa: E402

KICAD_PYTHON = True
ROOT = Path(__file__).resolve().parents[1]
(ROOT / ".runtime" / "tmp").mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="layoutq_", dir=str(ROOT / ".runtime" / "tmp")))
mm = pcbnew.FromMM
F, B_ = pcbnew.F_Cu, pcbnew.B_Cu


def teardown_module():
    shutil.rmtree(TMP, ignore_errors=True)


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class Fx:
    def __init__(self, layers=4, edge=(0, 0, 60, 40)):
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(layers)
        self.nets = {}
        if edge:
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

    def part(self, ref, x, y, pads, value="", fpid="", back=False, courtyard=None):
        """pads: [(num, dx, dy, net, w, h)] SMD rectangles on F.Cu (back=True: the part is flipped to B.Cu)"""
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
        if courtyard:
            cx0, cy0, cx1, cy1 = courtyard
            for a, c in (((cx0, cy0), (cx1, cy0)), ((cx1, cy0), (cx1, cy1)), ((cx1, cy1), (cx0, cy1)),
                         ((cx0, cy1), (cx0, cy0))):
                s = pcbnew.PCB_SHAPE(fp)
                s.SetShape(pcbnew.SHAPE_T_SEGMENT)
                s.SetStart(V(*a))
                s.SetEnd(V(*c))
                s.SetLayer(pcbnew.F_CrtYd)
                s.SetWidth(mm(0.05))
                fp.Add(s)
        fp.SetPosition(V(x, y))
        if back:
            fp.Flip(V(x, y), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        return fp

    def two(self, ref, x, y, n1, n2, size="0402", value="", back=False, vertical=False, fpid=None):
        w, h, d = {"0402": (0.56, 0.62, 0.48), "0603": (0.9, 0.95, 0.8), "0805": (1.0, 1.45, 0.95),
                   "1206": (1.15, 1.8, 1.475), "1210": (1.15, 2.7, 1.475)}[size]
        pads = [("1", 0, -d, n1, h, w), ("2", 0, d, n2, h, w)] if vertical else [("1", -d, 0, n1, w, h),
                                                                               ("2", d, 0, n2, w, h)]
        metric = {"0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216", "1210": "3225"}[size]
        return self.part(ref, x, y, pads, value=value, back=back, fpid=fpid or f"{ref[:1]}_{size}_{metric}Metric")

    def ic(self, ref, x, y, nets, pitch=0.5, pw=0.3, ph=1.0, row_dy=2.0, back=False, ep=None):
        n = len(nets) // 2
        pads = []
        for k, net in enumerate(nets):
            row, col = divmod(k, n)
            pads.append((str(k + 1), (col - (n - 1) / 2) * pitch, -row_dy if row == 0 else row_dy, net, pw, ph))
        if ep:
            pads.append((str(len(nets) + 1), 0, 0, ep[0], ep[1], ep[2]))
        return self.part(ref, x, y, pads, back=back)

    def track(self, x0, y0, x1, y1, net, layer=F, w=0.25):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(V(x0, y0))
        t.SetEnd(V(x1, y1))
        t.SetWidth(mm(w))
        t.SetLayer(layer)
        t.SetNet(self.net(net))
        self.b.Add(t)
        return t

    def path(self, pts, net, layer=F, w=0.25):
        for a, c in zip(pts, pts[1:]):
            self.track(*a, *c, net, layer, w)

    def via(self, x, y, net, d=0.6, drill=0.3):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(V(x, y))
        v.SetWidth(mm(d))
        v.SetDrill(mm(drill))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(net))
        self.b.Add(v)
        return v

    def zone(self, net, layer, pts, conn=None, spoke=None, gap=None):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(net))
        z.SetLocalClearance(mm(0.2))
        if conn is not None:
            z.SetPadConnection(conn)
        if spoke is not None:
            z.SetThermalReliefSpokeWidth(mm(spoke))
        if gap is not None:
            z.SetThermalReliefGap(mm(gap))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x), mm(y))
        self.b.Add(z)
        return z

    def plane(self, net="GND", layer=pcbnew.In1_Cu, box=(1, 1, 59, 39)):
        x0, y0, x1, y1 = box
        return self.zone(net, layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    def save(self, name):
        if list(self.b.Zones()):
            pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        path = TMP / f"{name}.kicad_pcb"
        self.b.Save(str(path))
        return path

    def run(self, name, checks=gate.CHECKS):
        return gate.check(self.save(name), checks)


def expect(res, name, must_fail=(), must_pass=()):
    for c in must_fail:
        assert res["fails"][c], f"{name}: {c} did not fire: {res['counts']}"
    for c in must_pass:
        assert not res["fails"][c], f"{name}: {c} fired unexpectedly: {res['fails'][c][:3]}"


class swap:
    """temporarily replace gate.<table>["main"] (CT's per-board exemption tables are empty)"""

    def __init__(self, table, value):
        self.t, self.v = getattr(gate, table), value

    def __enter__(self):
        self.saved = self.t.get("main")
        self.t["main"] = self.v

    def __exit__(self, *a):
        self.t["main"] = self.saved


def test_exemption_tables_empty():
    """CT declares no per-board exemption; the generator-stack and mechanics tables hold only documented CT entries"""
    for name in ("DECAP_PATH_EXEMPT",):
        assert getattr(gate, name) == {"main": {}}, name
    # the owner-run D-LAYOUT-GATES cell entries only
    assert set(gate.PLACE_ORIENT_EXEMPT["main"]) == {"U1"} and set(gate.PLACE_ORIENT_EXEMPT) == {"main"}
    assert set(gate.SERIES_TERM_EXEMPT["main"]) == {"R16"} and set(gate.SERIES_TERM_EXEMPT) == {"main"}
    # XTAL length: the owner-run D-LAYOUT-GATES entries only (both nets of Y1 / Y2, measured + <= 0.1 mm)
    xt = {ref: {e["net"]: e["max_mm"] for e in ents} for ref, ents in gate.XTAL_LEN_EXEMPT["main"].items()}
    assert xt == {"Y1": {"XTAL40_P": 8.80, "XTAL40_N": 8.50}, "Y2": {"ETH_XI": 8.05, "ETH_XO": 9.05}}, xt
    assert set(gate.XTAL_LEN_EXEMPT) == {"main"}
    assert gate.PLANE_SLOT_EXEMPT == {"main": []} and gate.XSTACK_ALLOW == {} and gate.REF_POWER_PLANES == {"main": {}}
    assert gate.PLACE_MECH_REFS == {"D10", "D11", "D12", "Q22", "U10"}
    assert not hasattr(gate, "SHUNT_LAND_RE")


# test_via_inpad: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's filled-via rule (0603+ via-in-pad), CT budget (+12V / U10 returns) or CT's adopted board


def test_via_padgap():
    def case(name, dx, net, ref="R1"):
        f = Fx()
        f.part(ref, 20, 20, [("1", 0, 0, "A", 1.0, 1.0)])
        f.via(20.5 + 0.3 + dx, 20, net)
        return f.save(name)
    for name, dx, net in (("padgap_same", 0.05, "A"), ("padgap_foreign", 0.05, "B")):
        res = gate.check(case(name, dx, net), ("VIA-PADGAP",))
        expect(res, name, ["VIA-PADGAP"])
        assert abs(res["fails"]["VIA-PADGAP"][0]["gap_mm"] - 0.05) < 2e-3
        landing = QL.check(case(name + "_l", dx, net), ("VIA-PADEDGE",))
        assert not landing["fails"]["VIA-PADEDGE"], "VIA-PADEDGE must not change until PADEDGE_GAP_IN_LANDING"
        QL.PADEDGE_GAP_IN_LANDING = True
        try:
            landing = QL.check(case(name + "_l2", dx, net), ("VIA-PADEDGE",))
        finally:
            QL.PADEDGE_GAP_IN_LANDING = False
        assert any("from the pad edge" in x["what"] for x in landing["fails"]["VIA-PADEDGE"]), landing["fails"]
    expect(gate.check(case("padgap_ok", 0.15, "A"), ("VIA-PADGAP",)), "padgap_ok", [], ["VIA-PADGAP"])
    # CT: no RS shunt-ring exemption - an RS-named land with a same-net via at its edge still FAILs
    expect(gate.check(case("padgap_rs", 0.05, "A", "RS3"), ("VIA-PADGAP",)), "padgap_rs", ["VIA-PADGAP"])


def test_xstack():
    def case(name, dy, ic=True, allow=None):
        f = Fx()
        if ic:
            f.ic("U1", 20, 20, [f"N{k}" for k in range(8)])
        else:
            f.two("R9", 20, 18, "N0", "N1", size="1206")
        f.two("R1", 19.25, 18 + dy, "X", "Y", size="0402", back=True)
        old = dict(gate.XSTACK_ALLOW)
        if allow:
            gate.XSTACK_ALLOW[allow] = "fixture"
        try:
            return f.run(name, ("XSTACK",))
        finally:
            gate.XSTACK_ALLOW.clear()
            gate.XSTACK_ALLOW.update(old)
    expect(case("xstack_overlap", 0.0), "xstack_overlap", ["XSTACK"])
    expect(case("xstack_near", 0.5 + 0.31 + 0.2), "xstack_near", ["XSTACK"])
    expect(case("xstack_far", 0.5 + 0.31 + 0.4), "xstack_far", [], ["XSTACK"])
    expect(case("xstack_passive", 0.0, ic=False), "xstack_passive", [], ["XSTACK"])
    res = case("xstack_allow", 0.0, allow=("R1", "U1"))
    expect(res, "xstack_allow", [], ["XSTACK"])
    assert res["info"].get("xstack_allowed")

    def conn(name, rx):
        f = Fx()
        f.part("J1", 20, 20, [("1", -0.25, 0, "S0", 0.3, 1.0), ("2", 0.25, 0, "S1", 0.3, 1.0),
                              ("MP", 3.0, 0, "", 1.5, 2.0)])
        f.two("R1", rx, 20, "X", "Y", size="0402", back=True)
        return f.run(name, ("XSTACK",))
    res = conn("xstack_mp_tab", 23.25)
    expect(res, "xstack_mp_tab", [], ["XSTACK"])
    assert res["info"].get("xstack_mech_tab_skipped")
    expect(conn("xstack_conn_pin", 19.75), "xstack_conn_pin", ["XSTACK"])

    def decap(name, y=18.0, cnets=("+3V3", "GND"), vias=True, ic_under=False, ref="C1", foreign_ic=False):
        f = Fx()
        f.ic("U1", 20, 20, ["+3V3", "GND", "+3V3", "GND", "S1", "S2", "S3", "S4"], pitch=0.65)
        if foreign_ic:                                   # U2 does not carry the cap's rail: the cap sits under it
            f.ic("U2", 40, 20, ["+12V", "GND", "+12V", "GND", "T1", "T2", "T3", "T4"], pitch=0.65)
        if ic_under:
            f.ic("U2", 20, 20, ["+3V3", "GND", "+3V3", "GND", "T1", "T2", "T3", "T4"], pitch=0.65, back=True)
        else:
            x = 40 if foreign_ic else 20
            f.two(ref, x, y, cnets[0], cnets[1], value="100nF" if ref[0] == "C" else "10k", back=True)
            if vias:
                f.via(x - 0.48, y + 1.0, cnets[0], d=0.45, drill=0.2)
                f.via(x + 0.48, y + 1.0, cnets[1], d=0.45, drill=0.2)
                f.track(x - 0.48, y, x - 0.48, y + 1.0, cnets[0], B_)
                f.track(x + 0.48, y, x + 0.48, y + 1.0, cnets[1], B_)
        return f.run(name, ("XSTACK",))
    res = decap("xstack_decap_ok")
    expect(res, "xstack_decap_ok", [], ["XSTACK"])
    assert res["info"].get("xstack_serving_decap") == 1, res["info"]
    # CT owner 2026-10-17 (SERVING_DECAP_ANY_IC_PAD): a decap under its own IC facing that IC's SIGNAL pins serves it
    assert gate.SERVING_DECAP_ANY_IC_PAD
    res = decap("xstack_decap_signal", y=22.0)
    expect(res, "xstack_decap_signal", [], ["XSTACK"])
    assert res["info"].get("xstack_serving_decap") == 1, res["info"]
    # ... still failing: under a FOREIGN IC (not carrying the cap's rail), a resistor (not a cap) under the IC, a cap of
    # another rail, no via, IC over IC
    expect(decap("xstack_decap_foreign_ic", y=22.0, foreign_ic=True), "xstack_decap_foreign_ic", ["XSTACK"])
    expect(decap("xstack_resistor_under", y=22.0, ref="R1"), "xstack_resistor_under", ["XSTACK"])
    expect(decap("xstack_decap_other_rail", cnets=("+12V", "GND")), "xstack_decap_other_rail", ["XSTACK"])
    expect(decap("xstack_decap_novia", vias=False), "xstack_decap_novia", ["XSTACK"])
    expect(decap("xstack_ic_over_ic", ic_under=True), "xstack_ic_over_ic", ["XSTACK"])
    # the parent's stricter wording is still available (and FAILs the signal-pin stack) with the CT deviation off
    gate.SERVING_DECAP_ANY_IC_PAD = False
    try:
        expect(decap("xstack_decap_signal_parent", y=22.0), "xstack_decap_signal_parent", ["XSTACK"])
    finally:
        gate.SERVING_DECAP_ANY_IC_PAD = True


def two_pads():
    f = Fx()
    f.part("R1", 10, 20, [("1", 0, 0, "S", 1.0, 1.0)])
    f.part("R2", 30, 20, [("1", 0, 0, "S", 1.0, 1.0)])
    return f


def test_fold_acute():
    f = two_pads()
    f.path([(10, 20), (20, 20)], "S")
    f.path([(20, 20), (15, 20 + 5 * math.tan(math.radians(5)))], "S")
    f.path([(15, 20 + 5 * math.tan(math.radians(5))), (15, 25), (30, 25), (30, 20)], "S")
    expect(f.run("fold_spike", ("TRACK-FOLD",)), "fold_spike", ["TRACK-FOLD"])
    f = two_pads()
    f.track(10, 20, 22, 20, "S")
    f.track(20, 20, 30, 20, "S")
    res = f.run("fold_overlap", ("TRACK-FOLD",))
    assert any("overlapping" in x["what"] for x in res["fails"]["TRACK-FOLD"])
    f = two_pads()
    f.path([(10, 20), (15, 20), (18, 23), (25, 23), (28, 20), (30, 20)], "S")
    expect(f.run("fold_ok", ("TRACK-FOLD", "ACUTE")), "fold_ok", [], ["TRACK-FOLD", "ACUTE"])
    f = two_pads()
    f.path([(10, 20), (20, 20), (20 - 5 * math.cos(math.radians(60)), 20 + 5 * math.sin(math.radians(60))),
            (30, 24.33), (30, 20)], "S")
    expect(f.run("acute_60", ("ACUTE",)), "acute_60", ["ACUTE"])
    f = two_pads()
    f.path([(10, 20), (20, 20), (20, 25), (30, 25), (30, 20)], "S")
    expect(f.run("acute_90", ("ACUTE",)), "acute_90", [], ["ACUTE"])

    def tee(name, deg, as_joint=False):
        f = two_pads()
        r = 10 / math.sin(math.radians(deg))
        x = 20 + r * math.cos(math.radians(deg))
        f.part("R3", x, 30, [("1", 0, 0, "S", 1.0, 1.0)])
        if as_joint:
            f.track(10, 20, 20, 20, "S")
            f.track(20, 20, 30, 20, "S")
        else:
            f.track(10, 20, 30, 20, "S")
        f.track(20, 20, x, 30, "S")
        return f.run(name, ("ACUTE",))
    res = tee("acute_tee30", 30)
    assert any(x["what"] == "acute T-joint" for x in res["fails"]["ACUTE"])
    expect(tee("acute_tee30_joint", 30, True), "acute_tee30_joint", ["ACUTE"])
    expect(tee("acute_tee45", 45), "acute_tee45", [], ["ACUTE"])
    expect(tee("acute_tee45_joint", 45, True), "acute_tee45_joint", [], ["ACUTE"])


def test_thread():
    def base():
        f = Fx()
        f.two("R1", 20, 20, "A", "B", size="0805")
        f.part("P1", 10, 20, [("1", 0, 0, "Z", 1.0, 1.0)])
        f.part("P2", 30, 20, [("1", 0, 0, "Z", 1.0, 1.0)])
        return f
    f = base()
    f.track(10, 20, 30, 20, "Z", w=0.15)
    expect(f.run("thread_track", ("THREAD",)), "thread_track", ["THREAD"])
    f = base()
    f.path([(10, 20), (12, 22), (28, 22), (30, 20)], "Z")
    f.via(20, 20, "Q")
    res = f.run("thread_via", ("THREAD",))
    expect(res, "thread_via", ["THREAD"])
    assert all("via" in x["what"] for x in res["fails"]["THREAD"]), res["fails"]["THREAD"]
    f = base()
    f.path([(10, 20), (12, 22), (28, 22), (30, 20)], "Z")
    expect(f.run("thread_around", ("THREAD",)), "thread_around", [], ["THREAD"])

    def pins(name, pitch):
        f = Fx()
        f.ic("U1", 20, 20, [f"N{k}" for k in range(8)], pitch=pitch, pw=0.6 if pitch > 1 else 0.3, ph=1.5, row_dy=2.7)
        f.part("P1", 20, 10, [("1", 0, 0, "Z", 1.0, 1.0)])
        f.part("P2", 20, 30, [("1", 0, 0, "Z", 1.0, 1.0)])
        f.track(20, 10, 20, 30, "Z", w=0.12)
        return f.run(name, ("THREAD",))
    expect(pins("thread_fine", 0.5), "thread_fine", ["THREAD"])
    expect(pins("thread_soic", 1.27), "thread_soic", [], ["THREAD"])


def test_power_pad_conn():
    def cap(name, conn, spoke, ref="C1", value="22uF 25V", fpid=""):
        f = Fx()
        f.part(ref, 20, 20, [("1", -1.6, 0, "+12V", 1.6, 2.0), ("2", 1.6, 0, "GND", 1.6, 2.0)], value=value,
               fpid=fpid)
        f.track(18.4, 20, 10, 20, "+12V", w=0.8)
        f.part("J1", 10, 20, [("1", 0, 0, "+12V", 2.0, 2.0)])
        f.zone("GND", F, [(20, 14), (30, 14), (30, 26), (20, 26)], conn=conn, spoke=spoke, gap=0.3)
        return f.run(name, ("POWER-PAD-CONN",))
    res = cap("ppc_cap_spokes", pcbnew.ZONE_CONNECTION_THERMAL, 0.3)
    expect(res, "ppc_cap_spokes", ["POWER-PAD-CONN"])
    assert res["fails"]["POWER-PAD-CONN"][0]["pad"] == "C1.2"
    res = cap("ppc_cap_solid", pcbnew.ZONE_CONNECTION_FULL, 0.3)
    expect(res, "ppc_cap_solid", [], ["POWER-PAD-CONN"])
    assert res["info"]["power_pads_solid"] >= 1
    # CT scope: a rectifier diode on GND thermal spokes FAILs (rail diode); an indicator LED does not
    assert gate.POWER_PAD_SKIP_LED
    expect(cap("ppc_diode", pcbnew.ZONE_CONNECTION_THERMAL, 0.3, ref="D1", value="SS56B", fpid="D_SMB"),
           "ppc_diode", ["POWER-PAD-CONN"])
    expect(cap("ppc_led", pcbnew.ZONE_CONNECTION_THERMAL, 0.3, ref="D1", value="KT-0603B",
               fpid="LED_0603_1608Metric"), "ppc_led", [], ["POWER-PAD-CONN"])

    def ep(name, conn):
        f = Fx()
        f.ic("U1", 20, 20, ["A", "GND", "B", "C", "D", "E", "GND", "F"], pitch=0.65, pw=0.4, ph=1.2, row_dy=2.4,
             ep=("GND", 2.0, 2.4))
        f.zone("GND", F, [(14, 14), (26, 14), (26, 26), (14, 26)], conn=conn, spoke=0.3, gap=0.3)
        return f.run(name, ("POWER-PAD-CONN",))
    res = ep("ppc_ep_thermal", pcbnew.ZONE_CONNECTION_THERMAL)
    expect(res, "ppc_ep_thermal", ["POWER-PAD-CONN"])
    assert res["fails"]["POWER-PAD-CONN"][0]["role"] == "exposed pad"
    expect(ep("ppc_ep_solid", pcbnew.ZONE_CONNECTION_FULL), "ppc_ep_solid", [], ["POWER-PAD-CONN"])


# test_via_current: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's filled-via rule (0603+ via-in-pad), CT budget (+12V / U10 returns) or CT's adopted board


# test_vcur_part_return: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's filled-via rule (0603+ via-in-pad), CT budget (+12V / U10 returns) or CT's adopted board


# test_vcur_decap_fanout: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's filled-via rule (0603+ via-in-pad), CT budget (+12V / U10 returns) or CT's adopted board


def test_neck_smallpad():
    def case(name, w):
        f = Fx()
        f.two("C1", 20, 20, "+3V3", "GND")
        f.part("J1", 10, 20, [("1", 0, 0, "+3V3", 2.0, 2.0)])
        f.track(10, 20, 19.52, 20, "+3V3", w=w)
        return f.run(name, ("NECK-SMALLPAD",))
    expect(case("neck_wide", 0.8), "neck_wide", ["NECK-SMALLPAD"])
    expect(case("neck_ok", 0.3), "neck_ok", [], ["NECK-SMALLPAD"])


def test_pour_stitch():
    def case(name, vias, net="GND"):
        f = Fx()
        f.plane(net, box=(1, 1, 59, 18.5))         # D-LAYOUT-GATES #9c: 85 % backed = the unbacked rule
        f.zone(net, F, [(20, 10), (30, 10), (30, 20), (20, 20)])
        for x, y in vias:
            f.via(x, y, net)
        return f.run(name, ("POUR-STITCH",))
    res = case("stitch_one", [(25, 15)])
    expect(res, "stitch_one", ["POUR-STITCH"])
    assert res["fails"]["POUR-STITCH"][0]["need"] == 4
    res = case("stitch_far", [(21, 11), (22, 11), (21, 12), (22, 12)])
    assert res["fails"]["POUR-STITCH"][0]["beyond_reach_mm2"] > 1
    expect(case("stitch_ok", [(22.5, 12.5), (27.5, 12.5), (22.5, 17.5), (27.5, 17.5)]), "stitch_ok", [],
           ["POUR-STITCH"])
    expect(case("stitch_prtn", [(25, 15)], "PRTN"), "stitch_prtn", ["POUR-STITCH"])     # PRI plane net too


def test_pour_stitch_backed():
    """D-LAYOUT-GATES #9c: a pour backed by its own inner plane needs area / 50 vias and no off-plane reach; the same
    clustered vias over a plane covering only a third of the pour fail as before"""
    def case(name, vias, plane_box):
        f = Fx()
        f.plane("GND", box=plane_box)
        f.zone("GND", F, [(20, 10), (30, 10), (30, 20), (20, 20)])
        for x, y in vias:
            f.via(x, y, "GND")
        return f.run(name, ("POUR-STITCH",))
    cl = [(21, 11), (22, 11)]
    res = case("stitch_backed", cl, (1, 1, 59, 39))
    expect(res, "stitch_backed", [], ["POUR-STITCH"])
    assert res["info"].get("stitch_backed"), res["info"]
    expect(case("stitch_part_backed", cl, (1, 1, 23, 39)), "stitch_part_backed", ["POUR-STITCH"])


def test_decap_loop():
    def case(name, gvia, path, gnd="GND", sup="+3V3"):
        f = Fx()
        f.plane(gnd)
        f.part("U1", 20, 20, [("1", 0, 0, sup, 0.6, 0.6), ("2", 0, 3, gnd, 0.6, 0.6)])
        f.via(20, 24, gnd)
        f.track(20, 23, 20, 24, gnd)
        f.two("C1", 20 - path, 20, sup, gnd, value="100nF", vertical=True)
        f.path([(20 - path, 19.52), (20 - path, 19.0), (20, 19.0), (20, 20)], sup)
        if gvia:
            f.via(20 - path, 21.3, gnd)
            f.track(20 - path, 20.48, 20 - path, 21.3, gnd)
        return f.run(name, ("DECAP-LOOP",))
    res = case("decap_novia", False, 1.5)
    assert any("ground via" in x["what"] for x in res["fails"]["DECAP-LOOP"])
    res = case("decap_far", True, 6.0)
    expect(res, "decap_far", ["DECAP-LOOP"])
    assert all("supply copper path" in x["what"] for x in res["fails"]["DECAP-LOOP"])
    expect(case("decap_ok", True, 1.0), "decap_ok", [], ["DECAP-LOOP"])
    # CT PRI decaps: a TPS23751 VC cap (PD_VC -> PRTN) is a decap too (GROUND_RE / SUPPLY_RE)
    res = case("decap_pri_novia", False, 1.5, gnd="PRTN", sup="PD_VC")
    assert any("ground via" in x["what"] for x in res["fails"]["DECAP-LOOP"]), res["fails"]
    with swap("DECAP_PATH_EXEMPT", {"C1": "fixture"}):
        res = case("decap_far_exempt", True, 6.0)
        expect(res, "decap_far_exempt", [], ["DECAP-LOOP"])
        assert res["info"]["decap_path_exempt"][0][0] == "C1", res["info"]
        expect(case("decap_exempt_novia", False, 6.0), "decap_exempt_novia", ["DECAP-LOOP"])
    with swap("DECAP_PATH_EXEMPT", {"C9": "fixture: other ref"}):
        expect(case("decap_far_other", True, 6.0), "decap_far_other", ["DECAP-LOOP"])


def test_series_term():
    def case(name, rx, load_ic=False, value="33"):
        f = Fx()
        f.part("U1", 10, 20, [("1", 0, 0, "SCK_E", 0.6, 0.6)])
        if load_ic:
            f.part("U2", 40, 20, [("1", 0, 0, "SCK", 0.6, 0.6)])
        else:
            f.part("J1", 40, 20, [("1", 0, 0, "SCK", 1.0, 1.0)])
        f.two("R1", rx, 20, "SCK_E", "SCK", value=value)
        f.track(10, 20, rx - 0.48, 20, "SCK_E")
        f.track(rx + 0.48, 20, 40, 20, "SCK")
        return f.run(name, ("SERIES-TERM",))
    res = case("series_far", 20)
    expect(res, "series_far", ["SERIES-TERM"])
    assert res["fails"]["SERIES-TERM"][0]["driver"] == "U1.1"
    res = case("series_midline", 25, load_ic=True)
    assert "mid-line" in res["fails"]["SERIES-TERM"][0]["what"]
    expect(case("series_ok", 12), "series_ok", [], ["SERIES-TERM"])
    expect(case("series_150", 20, value="150"), "series_150", ["SERIES-TERM"])
    expect(case("series_330", 20, value="330"), "series_330", [], ["SERIES-TERM"])
    with swap("SERIES_TERM_EXEMPT", {"R1": "fixture"}):
        res = case("series_exempt", 20)
        expect(res, "series_exempt", [], ["SERIES-TERM"])
        assert res["info"].get("series_exempt") == ["R1"], res["info"]
    with swap("SERIES_TERM_EXEMPT", {"R9": "fixture: other ref"}):
        expect(case("series_exempt_other", 20), "series_exempt_other", ["SERIES-TERM"])

    def vip(name, vx):
        f = Fx()
        f.part("U1", 10, 20, [("1", 0, 0, "SCK_E", 0.9, 1.5)])
        f.part("J1", 40, 20, [("1", 0, 0, "SCK", 1.0, 1.0)])
        f.two("R1", vx + 1.5, 20, "SCK_E", "SCK", value="33", back=True)
        f.via(vx, 20, "SCK_E")
        f.track(vx, 20, vx + 1.02, 20, "SCK_E", B_)
        f.track(vx + 1.98, 20, vx + 3.0, 20, "SCK", B_)
        f.via(vx + 3.0, 20, "SCK")
        f.track(vx + 3.0, 20, 40, 20, "SCK")
        return f.run(name, ("SERIES-TERM",))
    expect(vip("series_vip", 10.0), "series_vip", [], ["SERIES-TERM"])
    expect(vip("series_vip_off", 14.0), "series_vip_off", ["SERIES-TERM"])


def test_series_term_led_limiter():
    """CT scope: R108-style LED current limiter (U pin -> 150 R -> LED) is no source termination (info); the same R
    to a non-LED load still FAILs"""
    def case(name, led):
        f = Fx()
        f.part("U1", 10, 20, [("1", 0, 0, "LED_SYS", 0.6, 0.6)])
        f.two("R1", 20, 20, "LED_SYS", "LED_SYS_A", value="150")
        f.two("D1" if led else "Q1", 30, 20, "LED_SYS_A", "GND", size="0603",
              fpid="LED_0603_1608Metric" if led else "Q_0603_1608Metric")
        f.track(10, 20, 19.52, 20, "LED_SYS")
        f.track(20.48, 20, 29.2, 20, "LED_SYS_A")
        return f.run(name, ("SERIES-TERM",))
    assert gate.SERIES_TERM_SKIP_LED
    res = case("series_led", True)
    expect(res, "series_led", [], ["SERIES-TERM"])
    assert res["info"].get("series_led_limiters") == ["R1"], res["info"]
    expect(case("series_not_led", False), "series_not_led", ["SERIES-TERM"])


def test_xtal():
    def case(name, load_x=13.0, via=False, foreign=False):
        f = Fx()
        f.part("Y1", 20, 20, [("1", -1.1, 0.8, "XTAL40_P", 1.4, 1.15), ("2", 1.1, 0.8, "GND", 1.4, 1.15),
                              ("3", 1.1, -0.8, "XTAL40_N", 1.4, 1.15), ("4", -1.1, -0.8, "GND", 1.4, 1.15)],
               fpid="Crystal_SMD_3225-4Pin", courtyard=(-2.2, -1.8, 2.2, 1.8))
        f.part("U2", 40 - load_x, 19.2, [("1", 0, 0, "XTAL40_N", 0.6, 0.6)])
        if via:
            f.track(18.9, 20.8, 16, 20.8, "XTAL40_P")
            f.via(16, 20.8, "XTAL40_P")
            f.track(16, 20.8, load_x, 20.8, "XTAL40_P", B_)
            f.part("U1", load_x, 20.8, [("1", 0, 0, "XTAL40_P", 0.6, 0.6)], back=True)
        else:
            f.part("U1", load_x, 20.8, [("1", 0, 0, "XTAL40_P", 0.6, 0.6)])
            f.track(18.9, 20.8, load_x, 20.8, "XTAL40_P")
        f.track(21.1, 19.2, 40 - load_x, 19.2, "XTAL40_N")
        if foreign:
            f.part("P1", 20, 10, [("1", 0, 0, "Z", 1.0, 1.0)])
            f.part("P2", 20, 30, [("1", 0, 0, "Z", 1.0, 1.0)])
            f.track(20, 10, 20, 30, "Z", layer=pcbnew.In2_Cu)
            f.via(20, 10, "Z")
            f.via(20, 30, "Z")
        return f.run(name, ("XTAL",))
    with swap("XTAL_LEN_EXEMPT", {}):                 # the generic rule, without the board's entries
        res = case("xtal_long", load_x=12.0)
        assert any(x.get("len_mm", 0) > gate.XTAL_LEN_MM for x in res["fails"]["XTAL"])
        res = case("xtal_via", load_x=17.0, via=True)
        assert any(x.get("vias") and x["len_mm"] <= gate.XTAL_LEN_MM for x in res["fails"]["XTAL"]), res["fails"]["XTAL"]
        res = case("xtal_foreign", load_x=17.0, foreign=True)
        assert any("foreign" in x for x in res["fails"]["XTAL"])
        expect(case("xtal_ok", load_x=17.0), "xtal_ok", [], ["XTAL"])
    ent = {"net": "XTAL40_P", "max_mm": 6.0, "reason": "fixture"}
    with swap("XTAL_LEN_EXEMPT", {"Y1": ent}):
        res = case("xtal_listed", load_x=13.2)                 # 5.7 mm on XTAL40_P
        assert not [x for x in res["fails"]["XTAL"] if x.get("net") == "XTAL40_P"], res["fails"]["XTAL"]
        assert any(x["part"] == "Y1" for x in res["info"].get("xtal_len_exempt", [])), res["info"]
        res = case("xtal_listed_longer", load_x=12.0)          # 6.9 mm
        assert [x for x in res["fails"]["XTAL"] if x.get("net") == "XTAL40_P"], res["fails"]["XTAL"]
    entn = {"net": "XTAL40_N", "max_mm": 6.0, "reason": "fixture"}
    with swap("XTAL_LEN_EXEMPT", {"Y1": [ent, entn]}):          # list form: both nets listed
        res = case("xtal_listed_both", load_x=13.2)
        assert not [x for x in res["fails"]["XTAL"] if x.get("net") in ("XTAL40_P", "XTAL40_N")], res["fails"]["XTAL"]
        assert len([x for x in res["info"].get("xtal_len_exempt", []) if x["part"] == "Y1"]) == 2, res["info"]
        res = case("xtal_listed_both_via", load_x=13.2, via=True)   # a via still fails on a listed net
        assert any(x.get("vias") for x in res["fails"]["XTAL"]), res["fails"]["XTAL"]
        res = case("xtal_listed_both_foreign", load_x=13.2, foreign=True)   # the keep-out still applies
        assert any("foreign" in x for x in res["fails"]["XTAL"]), res["fails"]["XTAL"]
    with swap("XTAL_LEN_EXEMPT", {"Y1": [entn]}):               # only N listed: the 5.7 mm P net fails
        res = case("xtal_listed_other", load_x=13.2)
        assert [x for x in res["fails"]["XTAL"] if x.get("net") == "XTAL40_P"], res["fails"]["XTAL"]


def test_diffpair():
    pitch = 0.2 + 0.2

    def case(name, via_p=False, skew=0.0, apart=False):
        f = Fx()
        f.plane()
        yp, yn = 20.0, 20.0 + pitch
        f.part("U1", 10, yp, [("1", 0, 0, "MDI_TX_P", 0.3, 0.3), ("2", 0, pitch, "MDI_TX_N", 0.3, 0.3)])
        f.part("J1", 40, yp, [("1", 0, 0, "MDI_TX_P", 0.3, 0.3), ("2", 0, pitch, "MDI_TX_N", 0.3, 0.3)])
        if via_p:
            f.track(10, yp, 25, yp, "MDI_TX_P", F, 0.2)
            f.via(25, yp, "MDI_TX_P", d=0.45, drill=0.2)
            f.via(27, yp, "MDI_TX_P", d=0.45, drill=0.2)
            f.track(25, yp, 27, yp, "MDI_TX_P", B_, 0.2)
            f.track(27, yp, 40, yp, "MDI_TX_P", F, 0.2)
        else:
            f.track(10, yp, 40, yp, "MDI_TX_P", F, 0.2)
        if skew:
            f.path([(10, yn), (30, yn), (30, yn + skew / 2), (31, yn + skew / 2), (31, yn), (40, yn)], "MDI_TX_N", F,
                   0.2)
        elif apart:                                            # the N leg wanders 3 mm away over half the run
            f.path([(10, yn), (12, yn), (12, yn + 3), (28, yn + 3), (28, yn), (40, yn)], "MDI_TX_N", F, 0.2)
        else:
            f.track(10, yn, 40, yn, "MDI_TX_N", F, 0.2)
        return f.run(name, ("DIFFPAIR",))
    res = case("diff_via", via_p=True)
    assert any("vias" in p for p in res["fails"]["DIFFPAIR"][0]["problems"])
    res = case("diff_skew", skew=2.0)
    assert any("skew" in p for p in res["fails"]["DIFFPAIR"][0]["problems"])
    res = case("diff_apart", apart=True)
    assert any("coupled" in p for p in res["fails"]["DIFFPAIR"][0]["problems"]), res["fails"]["DIFFPAIR"]
    expect(case("diff_ok"), "diff_ok", [], ["DIFFPAIR"])


def test_diffpair_pinfield():
    """D-LAYOUT-GATES #6: skew inside a DIFF_SKEW_PINFIELD part's pin field (RJ45 stagger) is left out; the same
    geometry at an unlisted part, and skew in the routed part, still fail"""
    pitch = 0.2 + 0.2

    def case(name, conn="J1", route_skew=0.0):
        f = Fx()
        f.plane()
        yp, yn = 20.0, 20.0 + pitch
        f.part("U1", 10, yp, [("1", 0, 0, "MDI_TX_P", 0.3, 0.3), ("2", 0, pitch, "MDI_TX_N", 0.3, 0.3)])
        # staggered connector pins (RJ45-like): N pad 1.78 mm further on and 1.02 mm down
        f.part(conn, 40, yp, [("1", 0, 0, "MDI_TX_P", 1.5, 1.5), ("2", 1.78, 1.02, "MDI_TX_N", 1.5, 1.5)])
        f.track(10, yp, 40, yp, "MDI_TX_P", F, 0.2)
        pts = [(10, yn), (40, yn), (41.78, yp + 1.02)]
        if route_skew:
            pts = [(10, yn), (20, yn), (20, yn + route_skew / 2), (21, yn + route_skew / 2), (21, yn), (40, yn),
                   (41.78, yp + 1.02)]
        f.path(pts, "MDI_TX_N", F, 0.2)
        return f.run(name, ("DIFFPAIR",))
    res = case("pf_j1")
    assert not any("skew" in p for x in res["fails"]["DIFFPAIR"] for p in x["problems"]), res["fails"]["DIFFPAIR"]
    assert res["info"].get("diffpair_pinfield_mm"), res["info"]
    res = case("pf_unlisted", conn="U5")
    assert any("skew" in p for x in res["fails"]["DIFFPAIR"] for p in x["problems"]), res["fails"]["DIFFPAIR"]
    res = case("pf_routed_skew", route_skew=2.0)
    assert any("skew" in p and "outside the pin fields" in p for x in res["fails"]["DIFFPAIR"] for p in x["problems"]), \
        res["fails"]["DIFFPAIR"]


def test_diffpair_pinfield_neighbours():
    """D-LAYOUT-GATES #6b: an RJ45-like 3 / 6 split - the far leg comes down beside the connector's own neighbouring
    pins (outside the two-pad capsule) to meet its partner; with the neighbour pads in the pin field that run is left
    out of the skew; without the neighbours (an unlisted part) it still fails"""
    def case(name, conn="J1", neighbour_net="NBR"):
        f = Fx()
        f.plane()
        f.part(conn, 10, 20, [("3", 0, 0, "MDI_RX_P", 1.5, 1.5), ("6", 1.78, -3.06, "MDI_RX_N", 1.5, 1.5),
                              ("4", 1.78, -1.02, neighbour_net, 1.5, 1.5), ("5", 0, -2.04, neighbour_net, 1.5, 1.5),
                              ("2", 1.78, 1.02, "OTHER", 1.5, 1.5)])
        f.part("U1", 50, 20, [("1", 0, 0, "MDI_RX_P", 0.3, 0.3), ("2", 0, -0.3, "MDI_RX_N", 0.3, 0.3)])
        f.track(10, 20, 50, 20, "MDI_RX_P", F, 0.15)
        f.path([(11.78, 16.94), (11.78, 16.0), (13.4, 16.0), (13.4, 19.4), (13.1, 19.7), (50, 19.7)], "MDI_RX_N", F, 0.15)
        return f.run(name, ("DIFFPAIR",))
    res = case("pfn_j1")
    assert not any("skew" in p for x in res["fails"]["DIFFPAIR"] for p in x["problems"]), res["fails"]["DIFFPAIR"]
    res = case("pfn_unlisted", conn="U5")
    assert any("skew" in p for x in res["fails"]["DIFFPAIR"] for p in x["problems"]), res["fails"]["DIFFPAIR"]
    with_nb = case("pfn_nb")["info"]["diffpair_pinfield_mm"]["MDI_RX_P/MDI_RX_N"]
    gate_n = gate.DIFF_PINFIELD_NEIGHBOUR_MM
    gate.DIFF_PINFIELD_NEIGHBOUR_MM = 0.0                     # #6 alone (two-pad capsule): less of the split excluded
    try:
        two_pad = case("pfn_two_pad_only")["info"]["diffpair_pinfield_mm"]["MDI_RX_P/MDI_RX_N"]
    finally:
        gate.DIFF_PINFIELD_NEIGHBOUR_MM = gate_n
    assert with_nb[1] - with_nb[0] > two_pad[1] - two_pad[0] + 0.5, (with_nb, two_pad)


def slot_planes(f):
    f.zone("GND", pcbnew.In1_Cu, [(1, 1), (24.7, 1), (24.7, 39), (1, 39)])
    f.zone("GND", pcbnew.In1_Cu, [(25.3, 1), (59, 1), (59, 39), (25.3, 39)])
    f.zone("GND", pcbnew.In1_Cu, [(24, 1), (26, 1), (26, 16), (24, 16)])
    f.zone("GND", pcbnew.In1_Cu, [(24, 24), (26, 24), (26, 39), (24, 39)])


def test_plane_slot():
    def case(name, net, slot=True, foreign=False):
        f = Fx()
        if slot:
            slot_planes(f)
        else:
            f.plane()
            if foreign:
                f.zone("+12V", pcbnew.In1_Cu, [(22, 15), (28, 15), (28, 25), (22, 25)])
                f.b.Zones()[-1].SetAssignedPriority(5)
        f.part("U1", 10, 20, [("1", 0, 0, net, 1.0, 1.0)])
        f.part("U2", 40, 20, [("1", 0, 0, net, 1.0, 1.0)])
        f.track(10, 20, 40, 20, net)
        return f.run(name, ("PLANE-SLOT",))
    expect(case("slot_sck", "ETH_SCLK"), "slot_sck", ["PLANE-SLOT"])
    res = case("slot_foreign", "ETH_SCLK", slot=False, foreign=True)
    assert any("reference change" in x["what"] for x in res["fails"]["PLANE-SLOT"])
    expect(case("slot_solid", "ETH_SCLK", slot=False), "slot_solid", [], ["PLANE-SLOT"])
    expect(case("slot_slow", "LED_SYS"), "slot_slow", [], ["PLANE-SLOT"])
    expect(case("slot_xtal", "XTAL40_P"), "slot_xtal", ["PLANE-SLOT"])          # CT crystal / pair names are SI
    expect(case("slot_phy", "PHY_TX_P"), "slot_phy", ["PLANE-SLOT"])

    def cluster(name, vias):
        f = Fx()
        slot_planes(f)
        for n, (x, y) in vias:
            f.via(x, y, n)
        f.part("U1", 10, 20, [("1", 0, 0, "ETH_SCLK", 1.0, 1.0)])
        f.part("U2", 40, 20, [("1", 0, 0, "ETH_SCLK", 1.0, 1.0)])
        f.track(10, 20, 40, 20, "ETH_SCLK")
        return f.run(name, ("PLANE-SLOT",))
    vs = [("SIGA", (25.0, 17.0)), ("SIGB", (25.0, 23.0))]
    with swap("PLANE_SLOT_EXEMPT", [{"net": "ETH_SCLK", "vias": vs, "reason": "fixture"}]):
        res = cluster("slot_exempt", vs)
        expect(res, "slot_exempt", [], ["PLANE-SLOT"])
        assert res["info"].get("plane_slot_exempt"), res["info"]
        expect(cluster("slot_exempt_missing", vs[:1]), "slot_exempt_missing", ["PLANE-SLOT"])
    with swap("PLANE_SLOT_EXEMPT", [{"net": "ETH_MOSI", "vias": vs, "reason": "fixture: other net"}]):
        expect(cluster("slot_exempt_net", vs), "slot_exempt_net", ["PLANE-SLOT"])

    def pwr(name, slot):
        f = Fx()
        f.plane()
        rects = ([[(22, 15), (24.7, 15), (24.7, 25), (22, 25)], [(25.3, 15), (28, 15), (28, 25), (25.3, 25)]] if slot
                 else [[(22, 15), (28, 15), (28, 25), (22, 25)]])
        for r in rects:
            f.zone("+3V3", pcbnew.In1_Cu, r)
            f.b.Zones()[-1].SetAssignedPriority(5)
        f.part("U1", 10, 20, [("1", 0, 0, "ETH_SCLK", 1.0, 1.0)])
        f.part("U2", 40, 20, [("1", 0, 0, "ETH_SCLK", 1.0, 1.0)])
        f.track(10, 20, 40, 20, "ETH_SCLK")
        return f.run(name, ("PLANE-SLOT",))

    def void(res):
        return [x for x in res["fails"]["PLANE-SLOT"] if "void" in x["what"]]
    with swap("REF_POWER_PLANES", {"In1.Cu": ["+3V3"]}):
        res = pwr("pwr_solid", False)
        assert not void(res) and any("reference change" in x["what"] for x in res["fails"]["PLANE-SLOT"]), res["fails"]
        assert void(pwr("pwr_slot", True))
    assert void(pwr("pwr_unlisted", False)), "an unlisted power region in the plane stays a void"


def test_plane_slot_thermal_island():
    def island(f, name, box=(40, 17, 46, 23)):
        z = pcbnew.ZONE(f.b)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        ls = pcbnew.LSET()
        for lid in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
            ls.AddLayer(lid)
        z.SetLayerSet(ls)
        z.SetZoneName(name)
        o = z.Outline()
        o.NewOutline()
        x0, y0, x1, y1 = box
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(mm(x), mm(y))
        f.b.Add(z)

    def case(name, zone_name, through=False):
        f = Fx()
        f.plane()
        island(f, zone_name)
        f.part("U1", 10, 20, [("1", 0, 0, "I2C_SDA", 1.0, 1.0)])
        if through:                                   # crosses the island to a pad beyond it
            f.part("U2", 52, 20, [("1", 0, 0, "I2C_SDA", 1.0, 1.0)])
            f.track(10, 20, 52, 20, "I2C_SDA")
        else:                                         # ends on its own pad inside the island
            f.part("U2", 43, 20, [("1", 0, 0, "I2C_SDA", 1.0, 1.0)])
            f.track(10, 20, 43, 20, "I2C_SDA")
        return f.run(name, ("PLANE-SLOT",))
    res = case("island_own_pad", "TEMP_SENSOR_ISLAND")
    expect(res, "island_own_pad", [], ["PLANE-SLOT"])
    assert res["info"].get("plane_slot_thermal_island"), res["info"]
    expect(case("island_through", "TEMP_SENSOR_ISLAND", through=True), "island_through", ["PLANE-SLOT"])
    expect(case("island_other_void", "OTHER_KEEPOUT"), "island_other_void", ["PLANE-SLOT"])


def test_fiducial():
    def case(name, fids):
        f = Fx()
        f.ic("U1", 30, 20, [f"N{k}" for k in range(8)])
        for k, (x, y) in enumerate(fids):
            f.part(f"FID{k + 1}", x, y, [("1", 0, 0, "", 1.0, 1.0)], fpid="Fiducial_1mm_Mask2mm")
        return f.run(name, ("FIDUCIAL",))
    expect(case("fid_none", []), "fid_none", ["FIDUCIAL"])
    expect(case("fid_collinear", [(5, 5), (30, 5), (55, 5)]), "fid_collinear", ["FIDUCIAL"])
    expect(case("fid_ok", [(5, 5), (55, 5), (5, 35)]), "fid_ok", [], ["FIDUCIAL"])


def test_pad_axis():
    # U1 row 0: pins N0..N3 at x 19.25 / 19.75 / 20.25 / 20.75, y 18 (N0 = the west end pin); deg > 0 leans west
    def case(name, deg, x0=19.25, net="N0"):
        f = Fx()
        f.ic("U1", 20, 20, [f"N{k}" for k in range(8)])
        x1, y1 = x0 - 5 * math.sin(math.radians(deg)), 18 - 5 * math.cos(math.radians(deg))
        f.part("P1", x1, y1, [("1", 0, 0, net, 1.0, 1.0)])
        f.track(x0, 18, x1, y1, net, w=0.2)
        return f.run(name, ("PAD-AXIS",))
    expect(case("axis_45_toward_neighbour", -45), "axis_45_toward_neighbour", ["PAD-AXIS"])
    expect(case("axis_45_middle_pin", 45, x0=19.75, net="N1"), "axis_45_middle_pin", ["PAD-AXIS"])
    expect(case("axis_45_middle_pin_east", -45, x0=19.75, net="N1"), "axis_45_middle_pin_east", ["PAD-AXIS"])
    res = case("axis_45_end_pin_out", 45)                     # end pin leaving its row outward: no finding
    expect(res, "axis_45_end_pin_out", [], ["PAD-AXIS"])
    assert res["info"].get("pad_axis_end_pin") and res["info"]["pad_axis_end_pin"][0][0] == "U1.1", res["info"]
    expect(case("axis_0", 0), "axis_0", [], ["PAD-AXIS"])


def test_via_hop():
    f = two_pads()
    f.track(10, 20, 20, 20, "S")
    f.via(20, 20, "S")
    f.track(20, 20, 20.8, 20, "S", B_)
    f.via(20.8, 20, "S")
    f.track(20.8, 20, 30, 20, "S")
    expect(f.run("hop", ("VIA-HOP",)), "hop", ["VIA-HOP"])
    f = Fx()
    f.part("R1", 10, 20, [("1", 0, 0, "S", 1.0, 1.0)])
    f.part("R2", 30, 20, [("1", 0, 0, "S", 1.0, 1.0)], back=True)
    f.track(10, 20, 20.8, 20, "S", w=0.8)
    f.via(20, 20, "S")
    f.via(20.8, 20, "S")
    f.track(20, 20, 30, 20, "S", B_, w=0.8)
    expect(f.run("hop_parallel", ("VIA-HOP",)), "hop_parallel", [], ["VIA-HOP"])


def conn2(f, ref="J1", x=20.0, y=20.0, nets=None, n=6):
    nets = nets or {}
    pads = []
    for k in range(n):
        num = 2 * k + 1
        pads.append((str(num), k * 1.0, 0.0, nets.get(str(num), f"{ref}_A{k}"), 0.6, 1.5))
        pads.append((str(num + 1), k * 1.0 + 0.5, -3.0, nets.get(str(num + 1), f"{ref}_B{k}"), 0.6, 1.5))
    return f.part(ref, x, y, pads)


def test_place_pinpassive():
    def case(name, ry=None, rx=21.0, horizontal=False, ic_gap=None, series=False, edge=False):
        f = Fx()
        cy = 38.0 if edge else 20.0
        conn2(f, y=cy, nets={"3": "SIG", "5": "SIG2"})
        f.ic("U1", 45, 30, ["SIG", "SIG2", "N3", "N4", "N5", "N6", "N7", "N8"], pitch=0.65)
        if series:
            f.two("R1", 21.0, cy + 3.0, "SIG", "SIGX", value="1k", vertical=True)
        elif ry is not None:
            f.two("R1", rx, ry, "SIG", "GND", value="100k", vertical=not horizontal)
        if ic_gap is not None:
            f.two("R2", 44.675, 27.5 - ic_gap - 0.28 - 0.48, "GND", "SIG2", value="10k", vertical=True)
        return f.run(name, ("PLACE-PINPASSIVE",))

    def on_axis(gap):
        return 20.75 + gap + 0.28 + 0.48
    res = case("pp_far", ry=on_axis(2.5))
    expect(res, "pp_far", ["PLACE-PINPASSIVE"])
    x = res["fails"]["PLACE-PINPASSIVE"][0]
    assert x["part"] == "R1" and x["pin"] == "J1.3" and abs(x["propose"]["x"] - 21.0) < 0.01, x
    res = case("pp_touch", ry=on_axis(-0.02))
    expect(res, "pp_touch", [], ["PLACE-PINPASSIVE"])
    assert res["info"]["pinpassive_on_axis"] >= 1, res["info"]
    expect(case("pp_gap1", ry=on_axis(1.0)), "pp_gap1", [], ["PLACE-PINPASSIVE"])
    res = case("pp_turned", ry=21.5, rx=21.0 + 2.24 + 0.48, horizontal=True)
    assert res["fails"]["PLACE-PINPASSIVE"][0]["axis_offset_mm"] > 2.0, res["fails"]["PLACE-PINPASSIVE"]
    expect(case("pp_offaxis", ry=on_axis(0.47), rx=21.25), "pp_offaxis", ["PLACE-PINPASSIVE"])
    res = case("pp_ic_far", ic_gap=3.0)
    assert res["fails"]["PLACE-PINPASSIVE"][0]["pin"] == "U1.2", res["fails"]["PLACE-PINPASSIVE"]
    expect(case("pp_ic_near", ic_gap=0.5), "pp_ic_near", [], ["PLACE-PINPASSIVE"])
    res = case("pp_series", series=True)
    expect(res, "pp_series", [], ["PLACE-PINPASSIVE"])
    assert any(s.startswith("R1@") for s in res["info"]["pinpassive_series_not_scope"]), res["info"]
    res = case("pp_nospot", ry=38.0 - 3.0 - 2.0, edge=True)
    expect(res, "pp_nospot", [], ["PLACE-PINPASSIVE"])
    assert res["info"]["pinpassive_no_spot"] and "board edge" in res["info"]["pinpassive_no_spot"][0]["blocked_by"]


def _place_orient_cases():
    def parts(f, pts):
        for k, (net, x, y) in enumerate(pts):
            f.part(f"U{k + 30}", x, y, [("1", 0, 0, net, 0.6, 0.6)])
    nets = [f"A{k}" for k in range(4)] + [f"B{k}" for k in range(4)]

    def rot_case(name, ref):
        f = Fx()
        f.ic(ref, 30, 20, nets, pitch=0.65)
        parts(f, [(f"A{k}", 29 + k, 30) for k in range(4)] + [(f"B{k}", 29 + k, 10) for k in range(4)])
        return f.run(name, ("PLACE-ORIENT",))
    res = rot_case("or_rot", "U1")
    assert any(x["kind"] == "rotation" and abs(x["propose"]["rot"]) == 180.0 for x in res["fails"]["PLACE-ORIENT"])
    with swap("PLACE_ORIENT_EXEMPT", {"U1": "fixture: mechanics-fixed"}):
        res = rot_case("or_exempt", "U1")
        expect(res, "or_exempt", [], ["PLACE-ORIENT"])
        assert res["info"]["orient_exempt"] == ["U1"], res["info"]
        expect(rot_case("or_exempt_other", "U2"), "or_exempt_other", ["PLACE-ORIENT"])
    # CT: U10 (the function-pinned ambient sensor) is never asked to move; the same part as U11 is
    expect(rot_case("or_u10_pinned", "U10"), "or_u10_pinned", [], ["PLACE-ORIENT"])
    expect(rot_case("or_u11", "U11"), "or_u11", ["PLACE-ORIENT"])
    f = Fx()
    pads = [(str(k + 1), -2.0, (k - 1.5) * 0.65, f"L{k}", 1.0, 0.35) for k in range(4)]
    pads += [(str(k + 5), 2.0, (k - 1.5) * 0.65, f"R{k}", 1.0, 0.35) for k in range(4)]
    f.part("U1", 25, 20, pads)
    parts(f, [(f"L{k}", 47, 18 + k * 1.2) for k in range(4)] + [(f"R{k}", 3, 18 + k * 1.2) for k in range(4)])
    res = f.run("or_facing", ("PLACE-ORIENT",))
    assert any(x["kind"] == "facing" and x["behind"] == 8 for x in res["fails"]["PLACE-ORIENT"]), res["fails"]
    f = Fx()
    f.ic("U1", 8, 8, nets, pitch=0.65)
    parts(f, [(n, 40 + 0.7 * k, 32) for k, n in enumerate(nets)])
    res = f.run("or_pos", ("PLACE-ORIENT",))
    assert any(x["kind"] == "position" for x in res["fails"]["PLACE-ORIENT"]), res["fails"]

    def cable(name, ux):
        f = Fx()
        conn2(f, x=10, y=10, nets={"3": "VBUS", "5": "USB_C_DP", "7": "USB_C_DN"})
        f.ic("U1", ux, 14, ["VBUS", "USB_C_DP", "USB_C_DN", "GND", "N5", "N6", "N7", "N8"], pitch=0.65)
        parts(f, [("N5", ux + 0.5, 20), ("N6", ux + 1.0, 20), ("N7", ux + 1.5, 20), ("N8", ux + 2.0, 20)])
        return f.run(name, ("PLACE-ORIENT",))
    res = cable("or_cable_far", 32)
    assert any(x["kind"] == "cable-interface" and x["connector"] == "J1" for x in res["fails"]["PLACE-ORIENT"])
    res = cable("or_cable_near", 13)
    assert not any(x["kind"] == "cable-interface" for x in res["fails"]["PLACE-ORIENT"]), res["fails"]
    f = Fx()
    f.ic("U1", 30, 20, nets, pitch=0.65)
    parts(f, [(f"A{k}", 29 + k, 15) for k in range(4)] + [(f"B{k}", 29 + k, 25) for k in range(4)])
    expect(f.run("or_ok", ("PLACE-ORIENT",)), "or_ok", [], ["PLACE-ORIENT"])


def test_place_orient():
    with swap("PLACE_ORIENT_EXEMPT", {}):              # the generic rule, without the board's U1 entry
        _place_orient_cases()


def test_every_check_has_fixtures():
    covered = {"VIA-INPAD", "VIA-PADGAP", "XSTACK", "TRACK-FOLD", "ACUTE", "THREAD", "POWER-PAD-CONN", "VIA-CURRENT",
               "NECK-SMALLPAD", "POUR-STITCH", "DECAP-LOOP", "SERIES-TERM", "XTAL", "DIFFPAIR", "PLANE-SLOT",
               "FIDUCIAL", "PAD-AXIS", "VIA-HOP", "PLACE-PINPASSIVE", "PLACE-ORIENT"}
    assert covered == set(gate.CHECKS), f"checks without fixtures: {set(gate.CHECKS) - covered}"


# test_real_ct_board_runs: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's filled-via rule (0603+ via-in-pad), CT budget (+12V / U10 returns) or CT's adopted board


