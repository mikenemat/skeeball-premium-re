# ported from din8r-chassis-thermal/scripts/test_qa_copper_landing.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/test_qa_copper_landing.py (C:/work/din-relay-8ch), adapted for CT (one board kind, CT budget).
"""Fixtures for qa_copper_landing.py (KiCad Python, via scripts/conftest.py or
`py scripts/local_run.py kicad_test_runner.py scripts/test_qa_copper_landing.py`).

Owner (DIN-8R, 2026-10-04): BOTH the unconnected pad AND the short / loose trace must be captured, "not either/or".
Every fixture is built in memory, saved to a temporary folder under .runtime/tmp and checked through the real gate, so
each failure mode must be caught by the check named for it (the parent's fixture list, CT nets where the parent used
DIN-8R ones):
  clean / via_midspan_*      positive controls; a via joining a trace midspan feeds a routed branch (no TRACK-END), a
                             copper gap / foreign net / wrong layer / moved pad / dead via / free tail still fail
  d1_repro / short_trace     the D1 case (part moved, pour bridging): PAD-LAND AND TRACK-END; a trace stopping short
  stub / tiny_stub / ring / doubled / via_one_side / via_chain_dead / via_in_pour / pour_pad
  plane_island_*             PLANE-ISLAND alone / tied / via tie / sliver (info) / pads named / short feed
  dup / padedge* / q20 / partial* / pth   TRACK-DUP, VIA-PADEDGE, VIA-PARTIAL classes
  bare* / reach / fence      VIA-BARE heuristics (shared POUR-STITCH density / reach constants), edge fence
  orphan / fed_chain         TRACK-ORPHAN
  jog_*                      TRACK-JOG clean-shortcut screen (blocked / DRU / fill cut / lost via / lost pad-centre),
                             PROTECTED (CT: Ethernet / USB pair names, width-transition chains), protected staircases,
                             the qa_layout_quality screen (PAD-AXIS / PLANE-SLOT / fail closed) and jog_lq_delta units
  width_* / budget_* / path_* / branch_* / neck_*   TRACK-WIDTH: class fallback, CT budget (+12V / +12V_FAN / PoE),
                             no impedance nets, the "budget-path" leaf rule, BRANCHES (synthetic, CT has none) and the
                             foreign-object neck rule (a synthetic low-current net for the (c) cases)
  end_detail                 CT addition: TRACK-END rows classify each free end (edge landing / stops short / free)
  real_ct_move               the adopted CT board with a 2-pad part moved 1.7 mm: a new PAD-LAND AND a new TRACK-END
  pour_nets                  the gate's POUR_NETS / FORCE_NETS are board_const's
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as K  # noqa: E402
import pcbnew  # noqa: E402

import current_budget as cb  # noqa: E402
import qa_copper_landing as gate  # noqa: E402

KICAD_PYTHON = True
ROOT = Path(__file__).resolve().parents[1]
(ROOT / ".runtime" / "tmp").mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="landing_", dir=str(ROOT / ".runtime" / "tmp")))
mm = pcbnew.FromMM


def teardown_module():
    shutil.rmtree(TMP, ignore_errors=True)


def fixture_check(path, *args, **kwargs):
    return gate.check(path, *args, **kwargs)


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class Fixture:
    def __init__(self, layers=4):
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(layers)
        self.nets = {}

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def part(self, ref, x, y, pads):
        """pads: [(number, dx, dy, net)] 1 x 1 mm SMD pads on F.Cu."""
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference(ref)
        self.b.Add(fp)
        for num, dx, dy, net in pads:
            p = pcbnew.PAD(fp)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECTANGLE)
            p.SetSize(pcbnew.F_Cu, V(1.0, 1.0))
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetLayerSet(p.SMDMask())
            p.SetNumber(num)
            p.SetNet(self.net(net))
            p.SetFPRelativePosition(V(dx, dy))
            fp.Add(p)
        fp.SetPosition(V(x, y))
        return fp

    def track(self, x0, y0, x1, y1, net, layer=pcbnew.F_Cu, w=0.25):
        t = pcbnew.PCB_TRACK(self.b)
        t.SetStart(V(x0, y0))
        t.SetEnd(V(x1, y1))
        t.SetWidth(mm(w))
        t.SetLayer(layer)
        t.SetNet(self.net(net))
        self.b.Add(t)
        return t

    def via(self, x, y, net, d=0.6, drill=0.3):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(V(x, y))
        v.SetWidth(mm(d))
        v.SetDrill(mm(drill))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(net))
        self.b.Add(v)
        return v

    def zone(self, net, layer, pts):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        z.SetNet(self.net(net))
        z.SetLocalClearance(mm(0.2))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(mm(x), mm(y))
        self.b.Add(z)
        return z

    def save(self, name):
        if list(self.b.Zones()):
            pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())
        path = TMP / f"{name}.kicad_pcb"
        self.b.Save(str(path))
        return path

    def run(self, name, **kw):
        return fixture_check(self.save(name), **kw)

    def run_pro(self, name, pro_json, **kw):
        """BOARD.Save writes its own .kicad_pro: save under a scratch name, copy the board, then write the project"""
        scratch = self.save(name + "_save")
        path = TMP / f"{name}.kicad_pcb"
        path.write_bytes(scratch.read_bytes())
        path.with_suffix(".kicad_pro").write_text(pro_json, encoding="utf-8")
        return fixture_check(path, **kw)


def pro(track_w, extra_classes="", assignments=""):
    return ('{"net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": %s}%s],'
            ' "meta": {"version": 5}, "netclass_assignments": {%s}, "netclass_patterns": []}}'
            % (track_w, extra_classes, assignments))


def failed(res, check):
    return res["fails"][check]


def expect(res, name, must_fail, must_pass=()):
    for c in must_fail:
        assert failed(res, c), f"{name}: {c} did not fire: {res['counts']}"
    for c in must_pass:
        assert not failed(res, c), f"{name}: {c} fired unexpectedly: {res['fails'][c]}"


CLEAN_OK = ["PAD-OPEN", "PAD-LAND", "TRACK-END", "VIA-LAND"]


def clean(layers=4):
    """R1.1 -- SIG -- R2.1 on F.Cu; SIG2 R1.2 -> via -> B.Cu -> via -> R2.2; GND pads in a GND pour."""
    f = Fixture(layers)
    f.part("R1", 10, 10, [("1", 0, 0, "SIG"), ("2", 0, 3, "SIG2"), ("3", 0, 6, "GND")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG"), ("2", 0, 3, "SIG2"), ("3", 0, 6, "GND")])
    f.track(10, 10, 30, 10, "SIG")
    f.track(10, 13, 13, 13, "SIG2")
    f.via(13, 13, "SIG2")
    f.track(13, 13, 27, 13, "SIG2", pcbnew.B_Cu)
    f.via(27, 13, "SIG2")
    f.track(27, 13, 30, 13, "SIG2")
    f.zone("GND", pcbnew.F_Cu, [(5, 15), (35, 15), (35, 19), (5, 19)])
    return f


def via_midspan(offset=0.015, net="SIG", layer=pcbnew.F_Cu):
    """A retained pad-to-pad F trace feeding R3 through a via at its midspan and a B trace."""
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.part("R3", 20, 20, [("1", 0, 0, "SIG")])
    f.track(10, 10, 30, 10, "SIG", layer)
    f.via(20, 10 + offset, net)
    f.track(20, 10 + offset, 20, 17, "SIG", pcbnew.B_Cu)
    f.via(20, 17, "SIG")
    f.track(20, 17, 20, 20, "SIG")
    return f


# ------------------------------------------------------------------------------------------------ connection checks
def test_clean_passes():
    res = clean().run("clean4")
    assert res["status"] == "PASS", res["fails"]
    assert res["kind"] == "main" and res["pour_nets"] == sorted(K.POUR_NETS)


def test_via_midspan_variants():
    for name, offset in (("via_midspan", 0.015), ("via_midspan_annulus", 0.35)):
        expect(via_midspan(offset).run(name), name, [], ["PAD-OPEN", "PAD-LAND", "TRACK-END", "VIA-LAND", "LOOP"])
    # a 0.05 mm real copper gap must not attach
    expect(via_midspan(0.475).run("via_midspan_gap"), "gap", ["PAD-OPEN", "TRACK-END", "VIA-LAND"], ["PAD-LAND"])
    # physical contact to a foreign-net via is not connectivity of this net
    f = via_midspan(net="OTHER")
    next(iter(f.b.FindFootprintByReference("R3").Pads())).SetNet(f.net("OTHER"))
    for t in f.b.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA) or t.GetStart().x == t.GetEnd().x:
            t.SetNet(f.net("OTHER"))
    res = f.run("via_midspan_foreign")
    expect(res, "foreign", ["TRACK-END", "VIA-LAND"], ["PAD-LAND"])
    assert any(x["net"] == "OTHER" for x in failed(res, "TRACK-END"))
    # a blind F/In1 barrel cannot connect a B branch
    f = via_midspan()
    v = next(v for v in f.b.GetTracks() if isinstance(v, pcbnew.PCB_VIA) and v.GetPosition() == V(20, 10.015))
    v.SetViaType(pcbnew.VIATYPE_BLIND)
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.In1_Cu)
    expect(f.run("via_midspan_wrong_layer"), "wrong_layer", ["PAD-OPEN", "TRACK-END", "VIA-LAND"], ["PAD-LAND"])
    # the via attachment must not mask a moved pad or its now-short trace
    f = via_midspan()
    f.b.FindFootprintByReference("R3").SetPosition(V(20, 21.7))
    res = f.run("via_midspan_moved_pad")
    expect(res, "moved_pad", ["PAD-OPEN", "PAD-LAND", "TRACK-END"], ["VIA-LAND"])
    assert any(x.get("pad") == "R3.1" for x in failed(res, "PAD-LAND"))
    assert any(x["net"] == "SIG" and x.get("loose_mm", 0) >= 9.9 for x in failed(res, "TRACK-END"))
    # a branch ending in a bare via is not anchored by the good source path
    f = via_midspan()
    tail = f.track(20, 10.015, 24, 14.015, "SIG", pcbnew.B_Cu)
    f.via(24, 14.015, "SIG")
    res = f.run("via_midspan_dead_via")
    expect(res, "dead_via", ["TRACK-END", "VIA-LAND"], ["PAD-OPEN", "PAD-LAND"])
    assert any(tail.m_Uuid.AsString() in x.get("uuids", []) for x in failed(res, "TRACK-END"))
    # a track extending beyond its midspan via into empty space still has a dangling tail
    f = via_midspan()
    f.b.Remove(next(t for t in f.b.GetTracks() if not isinstance(t, pcbnew.PCB_VIA) and t.GetLayer() == pcbnew.B_Cu))
    tail = f.track(20, 9, 20, 17, "SIG", pcbnew.B_Cu)
    res = f.run("via_midspan_free_tail")
    expect(res, "free_tail", ["TRACK-END"], ["PAD-OPEN", "PAD-LAND", "VIA-LAND"])
    assert any(tail.m_Uuid.AsString() in x.get("uuids", []) for x in failed(res, "TRACK-END"))


def test_d1_repro_pad_and_trace():
    """the owner's D1 failure: part moved, trace left behind, a same-net pour bridging. Pad AND trace must fail."""
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.track(10, 10, 30, 10, "SIG")
    f.zone("SIG", pcbnew.F_Cu, [(26, 8.5), (34, 8.5), (34, 14), (26, 14)])   # a heat-spreader pour of a routed net
    f.b.FindFootprintByReference("R2").SetPosition(V(30, 11.7))
    res = f.run("d1_repro")
    assert not failed(res, "PAD-OPEN"), "d1_repro must be KiCad-connected (through the pour)"
    expect(res, "d1_repro", ["PAD-LAND", "TRACK-END"])
    assert any(x["pad"] == "R2.1" and "pour" in x["what"] for x in failed(res, "PAD-LAND"))


def test_short_trace():
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.track(10, 10, 29.2, 10, "SIG")                       # 0.3 mm short of R2.1's edge (29.5)
    expect(f.run("short_trace"), "short_trace", ["PAD-OPEN", "PAD-LAND", "TRACK-END"])


def test_stubs_rings_doubled():
    f = clean()
    f.track(20, 10, 20, 7, "SIG")
    expect(f.run("stub"), "stub", ["TRACK-END"], ["PAD-OPEN", "PAD-LAND", "LOOP"])
    f = clean()
    f.track(30.45, 10, 30.55, 10, "SIG", w=0.25)           # shorter than half its width, poking out of a pad
    expect(f.run("tiny_stub"), "tiny_stub", ["TRACK-END"], ["PAD-OPEN", "PAD-LAND", "LOOP"])
    f = clean()
    for seg in ((15, 10, 15, 6), (15, 6, 20, 6), (20, 6, 20, 10)):
        f.track(*seg, "SIG")
    res = f.run("ring")
    expect(res, "ring", ["LOOP"], ["TRACK-END", "PAD-LAND"])
    assert any(x["rings"] for x in failed(res, "LOOP"))
    f = clean()
    f.track(15, 10, 22, 10, "SIG")
    expect(f.run("doubled"), "doubled", ["LOOP"], ["PAD-LAND"])


def test_vias_dead_and_pour():
    f = clean()
    f.track(20, 10, 20, 8, "SIG")
    f.via(20, 8, "SIG")
    res = f.run("via_one_side")
    expect(res, "via_one_side", ["VIA-LAND", "TRACK-END"], ["PAD-OPEN", "PAD-LAND", "LOOP"])
    assert any(x["net"] == "SIG" and x.get("loose_mm", 0) >= 2.0 for x in failed(res, "TRACK-END"))
    f = clean()
    f.track(20, 10, 20, 8, "SIG")
    f.via(20, 8, "SIG")
    f.track(20, 8, 23, 5, "SIG", pcbnew.B_Cu)
    res = f.run("via_chain_dead")
    expect(res, "via_chain_dead", ["TRACK-END"], ["PAD-OPEN", "PAD-LAND", "VIA-LAND", "LOOP"])
    assert sum(x.get("loose_mm", 0) for x in failed(res, "TRACK-END") if x["net"] == "SIG") >= 2.0 + 4.2
    f = clean()
    f.track(10, 16, 10, 22, "GND")
    f.via(10, 22, "GND")
    f.zone("GND", pcbnew.B_Cu, [(5, 20), (15, 20), (15, 24), (5, 24)])
    expect(f.run("via_in_pour"), "via_in_pour", [], ["TRACK-END", "VIA-LAND", "PAD-OPEN", "POUR-PAD", "LOOP"])
    f = clean()
    f.part("R3", 45, 25, [("1", 0, 0, "GND")])
    expect(f.run("pour_pad"), "pour_pad", ["POUR-PAD", "PAD-OPEN"])


# test_pri_pour_nets: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# ------------------------------------------------------------------------------------------------ PLANE-ISLAND
def plane(name, extra):
    """GND trunk R1.1 - R8.1 - R2.1 on F.Cu (3 pads) plus an F.Cu GND pour (40..55) x (5..15), island removal NEVER"""
    f = Fixture()
    for ref, x in (("R1", 10), ("R8", 20), ("R2", 30)):
        f.part(ref, x, 10, [("1", 0, 0, "GND")])
    f.track(10, 10, 30, 10, "GND")
    z = f.zone("GND", pcbnew.F_Cu, [(40, 5), (55, 5), (55, 15), (40, 15)])
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    extra(f)
    return f.run(name)


def test_plane_island():
    assert gate.PLANE_ISLAND_MIN_MM2 == 2.0
    res = plane("island_alone", lambda f: None)
    expect(res, "island_alone", ["PLANE-ISLAND"])
    x = failed(res, "PLANE-ISLAND")[0]
    assert x["net"] == "GND" and x["area_mm2"] > 100 and x["pads"] == [] and 40 < x["at"][0] < 55, x
    expect(plane("island_tied", lambda f: f.track(30, 10, 42, 10, "GND")), "island_tied", [],
           ["PLANE-ISLAND", "PAD-OPEN", "TRACK-END"])

    def via_tie(f):
        f.zone("GND", pcbnew.B_Cu, [(5, 5), (60, 5), (60, 25), (5, 25)])
        f.track(20, 10, 20, 20, "GND")
        f.via(20, 20, "GND")
        f.via(47, 10, "GND")
    expect(plane("island_via_tie", via_tie), "island_via_tie", [], ["PLANE-ISLAND", "PAD-OPEN"])

    def sliver(f):
        f.track(30, 10, 42, 10, "GND")
        z = f.zone("GND", pcbnew.F_Cu, [(60, 5), (61, 5), (61, 6), (60, 6)])
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    res = plane("island_sliver", sliver)
    expect(res, "island_sliver", [], ["PLANE-ISLAND"])
    assert res["info"]["plane_islands_below_min"] == 1, res["info"]
    res = plane("island_short_feed", lambda f: f.track(30.8, 10, 42, 10, "GND"))
    expect(res, "island_short_feed", ["PLANE-ISLAND", "TRACK-END"])


def test_plane_island_names_pads():
    """the parent's +15V HOLDUP case on a CT cell-pour net: an island carrying pads of the net with no tie to the trunk"""
    f = Fixture()
    for ref, x, num in (("T2", 10, "5"), ("C11", 17, "1"), ("C12", 24, "1"), ("C13", 30, "1"), ("C90", 43, "1"),
                        ("C91", 47, "1"), ("D90", 51, "2")):
        f.part(ref, x, 10, [(num, 0, 0, "VPP")])
    f.track(10, 10, 30, 10, "VPP", w=0.6)
    f.zone("VPP", pcbnew.F_Cu, [(40, 5), (55, 5), (55, 15), (40, 15)])
    res = f.run("island_cell")
    expect(res, "island_cell", ["PLANE-ISLAND"])
    x = failed(res, "PLANE-ISLAND")[0]
    assert x["net"] == "VPP" and x["pads"] == ["C90.1", "C91.1", "D90.2"] and x["area_mm2"] > 100, x
    assert "not connected to the VPP main copper (4 pads)" in x["what"], x


# ------------------------------------------------------------------------------------------------ CLEAN checks
def test_track_dup():
    f = clean()
    f.track(10, 10, 30, 10, "SIG")
    f.track(20, 10, 20, 10, "SIG")
    res = f.run("dup")
    expect(res, "dup", ["TRACK-DUP"], ["PAD-OPEN", "PAD-LAND", "VIA-LAND"])
    assert len(failed(res, "TRACK-DUP")) == 2, failed(res, "TRACK-DUP")


def test_via_padedge_partial():
    f = clean()
    f.zone("GND", pcbnew.B_Cu, [(5, 15), (35, 15), (35, 19), (5, 19)])
    f.via(10.7, 16, "GND")                                 # R1.3 edge at x 10.5, via r 0.3
    expect(f.run("padedge"), "padedge", ["VIA-PADEDGE", "VIA-PARTIAL"], CLEAN_OK)
    f = clean()
    f.track(20, 10, 20, 7, "SIG")
    f.via(20, 7, "SIG")
    f.track(20, 7, 25, 7, "SIG", pcbnew.B_Cu)
    f.part("R4", 25, 7.75, [("1", 0, 0, "SIG"), ("2", 0, -1.5, "OTHER")])
    f.via(25.7, 6.25, "SIG")                               # touches OTHER pad R4.2
    res = f.run("padedge_foreign")
    assert any(x["pad_net"] == "OTHER" for x in failed(res, "VIA-PADEDGE")), failed(res, "VIA-PADEDGE")
    assert any(x["pad_net"] == "OTHER" for x in failed(res, "VIA-PARTIAL")), failed(res, "VIA-PARTIAL")
    f = clean()
    f.zone("GND", pcbnew.B_Cu, [(5, 15), (35, 15), (35, 19), (5, 19)])
    f.via(10.55, 16, "GND")                                # ~40 % on the pad, drill cuts the pad edge
    res = f.run("padedge_drilled")
    expect(res, "padedge_drilled", ["VIA-PADEDGE", "VIA-PARTIAL"], ["VIA-BARE"])
    assert failed(res, "VIA-PADEDGE")[0]["what"].startswith("via drill cuts"), failed(res, "VIA-PADEDGE")


def test_q20_repro_power_via():
    """review M4 M1 class on CT's Power-class via (0.8 / 0.4): 0.075 mm outside a SOT-23 pad, 27 % on it"""
    f = Fixture()
    q = f.part("Q90", 30, 30, [("2", 0, 0, "+12V_FAN")])
    list(q.Pads())[0].SetSize(pcbnew.F_Cu, V(0.6, 1.475))
    f.part("C1", 33, 30, [("1", 0, 0, "+12V_FAN")])
    f.track(30, 30, 33, 30, "+12V_FAN")
    f.via(30.375, 30.587, "+12V_FAN", d=0.8, drill=0.4)
    f.track(30.375, 30.587, 33, 30, "+12V_FAN", pcbnew.B_Cu)
    res = f.run("q20_repro")
    expect(res, "q20_repro", ["VIA-PADEDGE", "VIA-PARTIAL"])
    x = failed(res, "VIA-PARTIAL")[0]
    assert x["pad"] == "Q90.2" and x["class"] == "drilled" and abs(x["centre_out_mm"] - 0.075) < 0.002, x


def test_partial_traced_intent_vip_pth():
    f = clean()
    f.track(20, 10, 20, 7, "SIG")
    f.via(20, 7, "SIG")
    f.track(20, 7, 26, 7, "SIG", pcbnew.B_Cu)
    f.via(26, 7, "SIG")
    f.track(26, 7, 26, 9.2, "SIG")
    f.part("R4", 26, 9.75, [("1", 0, 0, "SIG")])
    f.via(26.0, 9.05, "SIG")                               # on the trace, 0.1 mm into R4.1
    assert any(x["pad"] == "R4.1" for x in failed(f.run("partial_traced"), "VIA-PARTIAL"))
    f = clean()
    f.zone("GND", pcbnew.B_Cu, [(5, 15), (35, 15), (35, 19), (5, 19)])
    f.via(10.65, 16, "GND", d=0.8, drill=0.25)             # intentional pad-edge landing, drill clear
    res = f.run("padedge_intent")
    assert gate.PARTIAL_ALLOW_INTENTIONAL
    expect(res, "padedge_intent", [], ["VIA-PADEDGE", "VIA-PARTIAL", "VIA-BARE"])
    assert res["info"].get("padedge_vias_intentional") == 1, res["info"]
    f = clean()
    f.zone("GND", pcbnew.B_Cu, [(5, 15), (35, 15), (35, 19), (5, 19)])
    f.via(10, 16, "GND")
    expect(f.run("via_in_pad"), "via_in_pad", [], ["VIA-PADEDGE", "VIA-PARTIAL", "VIA-BARE"])
    expect(clean().run("via_clear"), "via_clear", [], ["VIA-PADEDGE", "VIA-PARTIAL"])
    for net, must in (("SIG", False), ("OTHER", True)):
        f = clean()
        fp = f.part("J9", 40, 25, [])
        p = pcbnew.PAD(fp)
        p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_CIRCLE)
        p.SetSize(pcbnew.F_Cu, V(1.6, 1.6))
        p.SetDrillSize(V(1.0, 1.0))
        p.SetLayerSet(p.PTHMask())
        p.SetNumber("1")
        p.SetNet(f.net(net))
        fp.Add(p)
        p.SetPosition(V(40, 25))
        f.track(30, 10, 40, 25, "SIG")
        f.via(41.0, 25, "SIG")
        f.track(41.0, 25, 40.5, 25, "SIG")
        res = f.run(f"partial_pth_{net}")
        assert bool(failed(res, "VIA-PARTIAL")) == must, (net, failed(res, "VIA-PARTIAL"))
        assert must or res["info"].get("partial_pth_same_net") == 1, res["info"]


def stitched(n, x1=27):
    f = Fixture()
    f.part("R1", 14, 16, [("3", 0, 0, "GND")])
    for L in (pcbnew.F_Cu, pcbnew.B_Cu):
        f.zone("GND", L, [(13, 15), (x1, 15), (x1, 18), (13, 18)])
    for x in (15, 20, 25)[:n]:
        f.via(x, 17, "GND")
    return f


def test_via_bare_islands_density():
    res = stitched(3).run("bare3")
    expect(res, "bare3", ["VIA-BARE"], CLEAN_OK)
    assert len(failed(res, "VIA-BARE")) == 3
    expect(stitched(2).run("bare2"), "bare2", [], ["VIA-BARE"])
    f = stitched(3)
    for v in f.b.GetTracks():
        if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND":
            v.SetLocked(True)
    expect(f.run("bare3_locked"), "bare3_locked", ["VIA-BARE"])
    expect(stitched(3, x1=43).run("bare3_density"), "bare3_density", [], ["VIA-BARE"])



def test_via_bare_intent():
    """D-LAYOUT-GATES #8: a declared VIA_INTENT via (exact net / position) is counted, not gated; the same position on
    another net, or a via 0.1 mm off, is still judged"""
    def three(net):
        f = Fixture()
        f.part("R1", 14, 16, [("3", 0, 0, net)])
        for L in (pcbnew.F_Cu, pcbnew.B_Cu):
            f.zone(net, L, [(13, 15), (27, 15), (27, 18), (13, 18)])
        for x in (15, 20, 25):
            f.via(x, 17, net)
        return f
    saved = gate.VIA_INTENT["main"]
    try:
        gate.VIA_INTENT["main"] = {("+12V", 15, 17): "t", ("+12V", 20, 17): "t", ("+12V", 25, 17): "t"}
        res = three("+12V").run("intent_all")
        expect(res, "intent_all", [], ["VIA-BARE"])
        assert res["info"]["via_intent"] == 3, res["info"]
        expect(three("VPP").run("intent_other_net"), "intent_other_net", ["VIA-BARE"])
        gate.VIA_INTENT["main"] = {("+12V", 15, 17): "t", ("+12V", 20, 17): "t", ("+12V", 25.1, 17): "t"}
        res = three("+12V").run("intent_off")
        assert [x["at"] for x in failed(res, "VIA-BARE")] == [(25.0, 17.0)], failed(res, "VIA-BARE")
    finally:
        gate.VIA_INTENT["main"] = saved


def test_via_bare_reach_shared():
    def thin(xs):
        f = Fixture()
        f.zone("GND", pcbnew.In1_Cu, [(5, 5), (60, 5), (60, 35), (5, 35)])
        f.zone("GND", pcbnew.F_Cu, [(10, 20), (21, 20), (21, 21.5), (10, 21.5)])
        for x in xs:
            f.via(x, 20.75, "GND")
        return f
    assert gate.STITCH_REACH_MM == 5.0 and gate.STITCH_REACH_TOL_MM2 == 0.05
    expect(thin((10.8, 20.2)).run("bare_reach_ends"), "bare_reach_ends", [], ["VIA-BARE"])
    res = thin((10.8, 15.5, 20.2)).run("bare_reach_mid")
    expect(res, "bare_reach_mid", ["VIA-BARE"])
    assert [x["at"] for x in failed(res, "VIA-BARE")] == [(15.5, 20.75)], failed(res, "VIA-BARE")
    import qa_layout_quality as LQ
    assert LQ.STITCH_REACH_MM is gate.STITCH_REACH_MM and LQ.STITCH_REACH_TOL_MM2 is gate.STITCH_REACH_TOL_MM2
    from shapely.geometry import box as _box
    strip = _box(10, 20, 21, 21.5)
    assert gate.reach_far(strip, [(10.8, 20.75), (20.2, 20.75)]).area <= gate.STITCH_REACH_TOL_MM2
    assert gate.reach_far(strip, [(10.8, 20.75)]).area > 1.0
    assert gate.reach_lost(strip, [(10.8, 20.75), (20.2, 20.75)], (15.5, 20.75)) <= gate.STITCH_REACH_TOL_MM2
    assert gate.reach_lost(strip, [(10.8, 20.75)], (20.2, 20.75)) > gate.STITCH_REACH_TOL_MM2


def edge_rect(f, x0, y0, x1, y1):
    for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        sh = pcbnew.PCB_SHAPE(f.b)
        sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
        sh.SetStart(V(*a))
        sh.SetEnd(V(*c))
        sh.SetLayer(pcbnew.Edge_Cuts)
        sh.SetWidth(mm(0.1))
        f.b.Add(sh)


def test_via_bare_edge_fence():
    def fence(xs, extra=(), strip_h=1.5):
        f = Fixture()
        edge_rect(f, 0, 0, 60, 40)
        f.zone("GND", pcbnew.In1_Cu, [(1, 1), (59, 1), (59, 39), (1, 39)])
        f.zone("GND", pcbnew.F_Cu, [(10, 0.4), (40, 0.4), (40, 0.4 + strip_h), (10, 0.4 + strip_h)])
        for x in xs:
            f.via(x, 0.9, "GND")
        for x, y in extra:
            f.via(x, y, "GND")
        return f
    assert gate.FENCE_EDGE_MM == 1.5 and gate.FENCE_PITCH_MM == 5.0
    res = fence([10.8 + 4.5 * i for i in range(7)]).run("fence_pitch")
    expect(res, "fence_pitch", [], ["VIA-BARE"])
    assert res["info"]["fence_vias"] >= 3, res["info"]
    res = fence([10.8, 19.8, 28.8, 37.8], extra=[(24.3, 1.75)]).run("fence_inner")
    expect(res, "fence_inner", ["VIA-BARE"])
    assert [x["at"] for x in failed(res, "VIA-BARE")] == [(24.3, 1.75)], failed(res, "VIA-BARE")
    res = fence([], extra=[(10.8 + 4.5 * i, 4.5) for i in range(7)] + [(24.3, 0.9)], strip_h=5.0).run("fence_lone")
    expect(res, "fence_lone", ["VIA-BARE"])
    assert (24.3, 0.9) in [x["at"] for x in failed(res, "VIA-BARE")], failed(res, "VIA-BARE")
    assert res["info"]["fence_vias"] == 0, res["info"]


def test_track_orphan():
    f = stitched(2)
    f.track(20, 17, 22, 17, "GND")
    expect(f.run("orphan"), "orphan", ["TRACK-ORPHAN"], ["PAD-OPEN", "PAD-LAND"])
    f = stitched(2)
    f.track(14, 16, 15, 17, "GND")
    expect(f.run("fed_chain"), "fed_chain", [], ["TRACK-ORPHAN"])


def test_pad_centre():
    """a trace ending inside an SMD pad but 0.4 mm off its centre FAILs; one ending at the centre passes"""
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.track(10, 10, 29.6, 10, "SIG")
    res = f.run("pad_centre_off")
    expect(res, "pad_centre_off", ["PAD-CENTRE"], ["PAD-LAND", "TRACK-END"])
    assert failed(res, "PAD-CENTRE")[0]["pad"] == "R2.1" and abs(failed(res, "PAD-CENTRE")[0]["off_mm"] - 0.4) < 1e-3
    expect(clean().run("pad_centre_ok"), "pad_centre_ok", [], ["PAD-CENTRE"])


def test_end_detail_classes():
    """CT addition: a trace stopping AT a pad's edge (its end 0.05 mm outside the pad, copper overlapping) is a
    TRACK-END classed "edge landing"; one stopping 0.5 mm short is "stops ... short"; the class never excuses"""
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.track(10, 10, 29.45, 10, "SIG")                      # pad edge at 29.5; copper (w/2 0.125) overlaps it
    res = f.run("edge_landing")
    expect(res, "edge_landing", ["TRACK-END"], ["PAD-OPEN"])
    det = failed(res, "TRACK-END")[0]["end_detail"]
    assert det and det[0]["edge_landing"] and "edge landing on pad R2.1" in det[0]["class"], det
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.track(10, 10, 29.0, 10, "SIG")
    det = failed(f.run("stops_short"), "TRACK-END")[0]["end_detail"]
    assert det and not det[0]["edge_landing"] and "stops 0.500 mm short of pad R2.1" in det[0]["class"], det
    # a branch whose end stops 0.2 mm from a same-net trunk centreline (outside its copper, copper overlapping): the
    # KiCad-connected "edge landing on a track" - a TRACK-END too
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 10, [("1", 0, 0, "SIG")])
    f.part("R3", 20, 14, [("1", 0, 0, "SIG")])
    f.track(10, 10, 30, 10, "SIG")
    f.track(20, 14, 20, 10.2, "SIG")
    res = f.run("edge_on_track")
    assert not failed(res, "PAD-OPEN"), "KiCad must see the copper overlap as a connection"
    det = [d for x in failed(res, "TRACK-END") for d in x.get("end_detail", [])]
    assert any(d["edge_landing"] and "edge landing on track" in d["class"] for d in det), det


# ------------------------------------------------------------------------------------------------ TRACK-JOG
def jog_board(layers=4, net="SIG"):
    f = Fixture(layers)
    f.part("R1", 10, 10, [("1", 0, 0, net)])
    f.part("R2", 30, 10.3, [("1", 0, 0, net)])
    f.track(10, 10, 18, 10, net)
    f.track(18, 10, 18, 10.3, net)
    f.track(18, 10.3, 30, 10.3, net)
    return f


def jog_u_blockers(f, gap=0.21, net="OTHER"):
    yu, yd = 10 + 0.25 + gap, 10.3 - 0.25 - gap
    f.part("U1", 12, 12.5, [("1", 0, 0, net), ("2", 4, 0, net)])
    f.track(12, 12.5, 12, yu, net)
    f.track(12, yu, 16, yu, net)
    f.track(16, yu, 16, 12.5, net)
    f.part("U2", 20, 7.8, [("1", 0, 0, net + "2"), ("2", 4, 0, net + "2")])
    f.track(20, 7.8, 20, yd, net + "2")
    f.track(20, yd, 24, yd, net + "2")
    f.track(24, yd, 24, 7.8, net + "2")
    return f


def jog_info(res, net="SIG"):
    return [x for x in res["info"].get("jog_screened", []) if x["net"] == net]


def test_jog_basic_and_lbend():
    expect(jog_board().run("jog"), "jog", ["TRACK-JOG"], CLEAN_OK)
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
    f.part("R2", 30, 20, [("1", 0, 0, "SIG")])
    f.track(10, 10, 30, 10, "SIG")
    f.track(30, 10, 30, 20, "SIG")
    expect(f.run("lbend"), "lbend", [], ["TRACK-JOG"] + CLEAN_OK)


def test_jog_clean_blocked_dru():
    res = jog_board().run("jog_clean")
    expect(res, "jog_clean", ["TRACK-JOG"], CLEAN_OK)
    site = failed(res, "TRACK-JOG")[0]["sites"][0]
    assert site["shortcut"]["saving_mm"] > 0 and not site["shortcut"]["hard"], site
    assert site["shortcut"]["layout_quality"]["status"] == "CLEAN", site["shortcut"]["layout_quality"]
    assert not jog_info(res), jog_info(res)
    res = jog_u_blockers(jog_board()).run("jog_blocked")
    expect(res, "jog_blocked", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res)
    assert len(inf) == 1 and inf[0]["disposition"] == "BLOCKED", inf
    res = jog_u_blockers(jog_board(), gap=0.36).run("jog_dru_off")
    expect(res, "jog_dru_off", ["TRACK-JOG"], CLEAN_OK)
    f = jog_u_blockers(jog_board(), gap=0.36)
    dru = TMP / "jog_dru_on.kicad_dru"
    dru.write_text('(version 1)\n# SIG keeps 0.35 mm to OTHER*\n(rule "SIG wide"\n  (condition "A.NetName == \'SIG\' && '
                   'B.NetName == \'OTHER*\'")\n  (constraint clearance (min 0.35mm)))\n', encoding="utf-8")
    res = f.run("jog_dru_on")
    expect(res, "jog_dru_on", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res)
    assert len(inf) == 1 and inf[0]["disposition"] == "BLOCKED", inf
    assert any(h.get("rule") == "SIG wide" for c in inf[0]["candidates"] for h in c["hard"]), inf
    dru.write_text('(version 1)\n(rule "odd" (condition "A.isPlated()") (constraint clearance (min 1mm)))\n',
                   encoding="utf-8")
    try:
        fixture_check(TMP / "jog_dru_on.kicad_pcb")
    except ValueError as e:
        assert "not modelled" in str(e), e
    else:
        raise AssertionError("an unmodelled DRU condition must raise")
    finally:
        dru.unlink()


def test_jog_fillcut_lostvia_lostpad():
    f = jog_board()
    f.zone("GNDA", pcbnew.F_Cu, [(5, 10.35), (35, 10.35), (35, 14), (5, 14)])
    f.zone("GNDB", pcbnew.F_Cu, [(19, 6), (29, 6), (29, 9.95), (19, 9.95)])
    res = f.run("jog_fillcut")
    expect(res, "jog_fillcut", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res)
    assert len(inf) == 1 and inf[0]["disposition"] == "PLANE_CUT", inf

    def stair45(extra):
        f = Fixture()
        f.part("R1", 10, 10, [("1", 0, 0, "SIG")])
        f.part("R2", 20, 20, [("1", 0, 0, "SIG")])
        f.track(10, 10, 15, 15, "SIG")
        f.track(15, 15, 15.3, 15, "SIG")
        f.track(15.3, 15, 20, 20, "SIG")
        extra(f)
        return f

    def lostvia(f):
        f.part("R3", 27, 12, [("1", 0, 0, "SIG")])
        f.via(15.55, 14.75, "SIG")
        f.track(15.55, 14.75, 25, 12, "SIG", pcbnew.B_Cu)
        f.via(25, 12, "SIG")
        f.track(25, 12, 27, 12, "SIG")
    res = stair45(lostvia).run("jog_lostvia")
    expect(res, "jog_lostvia", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res)
    assert len(inf) == 1 and inf[0]["disposition"] == "BLOCKED", inf
    assert any(x["kind"] == "via" for x in inf[0]["candidates"][0]["lost_contacts"]), inf
    expect(stair45(lambda f: None).run("jog_novia"), "jog_novia", ["TRACK-JOG"], CLEAN_OK)

    def lostpad(f):
        fp = f.part("R3", 15.3, 15, [("1", 0, 0, "SIG")])
        fp.Pads()[0].SetSize(pcbnew.F_Cu, V(0.3, 0.3))
    res = stair45(lostpad).run("jog_lostpad")
    expect(res, "jog_lostpad", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res)
    assert any(x.get("pad") == "R3.1" and x.get("centre_landing_lost")
               for x in inf[0]["candidates"][0]["lost_contacts"]), inf


def test_jog_protected_ct_pairs():
    """CT protection: the Ethernet / USB pair names are info PROTECTED although the shortcut is clean, a width-transition
    chain too; an unprotected net with the same jog FAILs (test_jog_clean_blocked_dru)"""
    for net in ("MDI_TX_P", "PHY_RX_N", "ETH_TXP", "USB_DP"):
        res = jog_board(net=net).run(f"jog_prot_{net}")
        inf = jog_info(res, net)
        assert not failed(res, "TRACK-JOG"), (net, failed(res, "TRACK-JOG"))
        assert len(inf) == 1 and inf[0]["disposition"] == "PROTECTED" and "clean shortcut exists" in inf[0]["reason"], \
            (net, inf)
    f = jog_board()
    next(t for t in f.b.GetTracks() if t.GetStart() == V(18, 10)).SetWidth(mm(0.2))
    res = f.run("jog_widthchain")
    inf = jog_info(res)
    assert not failed(res, "TRACK-JOG") and inf and "width-transition" in inf[0]["reason"], inf


def stair_board(net="MDI_TX_P", steps=4, x0=12.0, lead=True):
    f = Fixture()
    x, y = (x0, 10.0) if lead else (10.0, 10.0)
    f.part("R1", 10, 10, [("1", 0, 0, net)])
    if lead:
        f.track(10, 10, x, y, net)
    for _ in range(steps):
        f.track(x, y, x + 0.25, y + 0.25, net)
        f.track(x + 0.25, y + 0.25, x + 0.5, y + 0.25, net)
        x, y = x + 0.5, y + 0.25
    f.track(x, y, x + 2.0, y + 2.0, net)
    f.part("R2", x + 2.0, y + 2.0, [("1", 0, 0, net)])
    return f


def test_jog_protected_staircase():
    """PROTECTED never hides a staircase (staircase jogs are worse than corners)"""
    n = gate.JOG_STAIR_MIN_SITES
    for lead in (True, False):
        res = stair_board(lead=lead).run(f"jog_stair{'' if lead else '_pad'}")
        expect(res, "jog_stair", ["TRACK-JOG"], CLEAN_OK)
        row = failed(res, "TRACK-JOG")[0]
        assert row["net"] == "MDI_TX_P" and row.get("protected_staircase_steps", 0) >= n, row
        assert res["info"]["jog_protected_staircase_fails"] == row["protected_staircase_steps"], res["info"]
    f = Fixture()
    f.part("R1", 10, 10, [("1", 0, 0, "MDI_TX_P")])
    f.track(10, 10, 14, 10, "MDI_TX_P")
    f.track(14, 10, 14.25, 10.25, "MDI_TX_P")
    f.track(14.25, 10.25, 14.5, 10.25, "MDI_TX_P")
    f.track(14.5, 10.25, 17.5, 13.25, "MDI_TX_P")
    f.part("R2", 17.5, 13.25, [("1", 0, 0, "MDI_TX_P")])
    res = f.run("jog_stair_short")
    expect(res, "jog_stair_short", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res, "MDI_TX_P")
    assert 1 <= len(inf) < n and all(x["disposition"] == "PROTECTED" for x in inf), inf
    res = stair_board("SIG").run("jog_stair_sig")
    expect(res, "jog_stair_sig", ["TRACK-JOG"], CLEAN_OK)
    row = failed(res, "TRACK-JOG")[0]
    assert "protected_staircase_steps" not in row and all("shortcut" in s for s in row["sites"]), row


def zone_holes(f, net, layer, outer, holes):
    z = f.zone(net, layer, outer)
    ol = z.Outline()
    for h in holes:
        k = ol.NewHole()
        for x, y in h:
            ol.Append(mm(x), mm(y), 0, k)
    return z


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def padaxis_board():
    f = Fixture()
    fp = f.part("U1", 10, 10, [("1", 0, 0, "SIG"), ("2", -0.5, 0, "SIG"), ("3", -1.0, 0, "SIG"), ("4", -1.5, 0, "SIG"),
                               ("5", 1.2, -0.4, "SIG")])   # exit-side neighbour: PAD-AXIS end-pin scope
    for p in fp.Pads():
        p.SetSize(pcbnew.F_Cu, V(0.3, 1.0))
        if p.GetNumber() != "1":
            p.SetNetCode(0)
    f.part("R2", 11.1, 11.1, [("1", 0, 0, "SIG")])
    f.track(10, 10, 10, 10.8, "SIG")
    f.track(10, 10.8, 10.3, 10.8, "SIG")
    f.track(10.3, 10.8, 11.1, 11.1, "SIG")
    return f


def void_board(side_voids=True):
    f = jog_board(net="ETH_SCLK")
    edge_rect(f, 0, 0, 40, 25)
    holes = [rect(24, 9, 28, 11.5)]
    if side_voids:
        holes += [rect(14.5, 10.05, 17.9, 13), rect(18.1, 7, 21.5, 10.25)]
    zone_holes(f, "GND", pcbnew.In1_Cu, rect(1, 1, 39, 24), holes)
    return f


def test_jog_lq_delta_units():
    d = gate.jog_lq_delta
    pa = {"pad": "U1.1", "net": "S", "layer": "F.Cu", "at": [1, 2], "angle": 45.0}
    ps = {"net": "S", "layer": "F.Cu", "what": "void", "len_mm": 0.8, "at": [5, 5]}
    assert d({"PAD-AXIS": [pa]}, {"PAD-AXIS": [dict(pa)]})["status"] == "CLEAN"
    assert d({"PAD-AXIS": [pa]}, {"PAD-AXIS": [dict(pa, angle=30.0)]})["status"] == "CLEAN"
    assert d({"PAD-AXIS": [pa]}, {"PAD-AXIS": []})["status"] == "CLEAN"
    r = d({"PAD-AXIS": [pa]}, {"PAD-AXIS": [dict(pa, angle=87.7)]})
    assert r["status"] == "DIRTY" and r["worsened"][0]["delta"] == {"angle": [45.0, 87.7]}, r
    assert d({"PAD-AXIS": []}, {"PAD-AXIS": [pa]})["status"] == "DIRTY"
    assert d({"PAD-AXIS": [pa]}, {"PAD-AXIS": [pa, dict(pa, angle=11.0)]})["status"] == "DIRTY"
    sm = {"PLANE-SLOT": {"min_term": 0.2, "terms": (2, 2)}}
    r = d({"PLANE-SLOT": [ps]}, {"PLANE-SLOT": [dict(ps, len_mm=0.9, at=[6, 6])]}, sums=sm)
    assert r["status"] == "DIRTY" and r["worsened"][0]["delta"] == {"len_mm": [0.8, 0.9]}, r
    assert d({"PLANE-SLOT": [ps]}, {"PLANE-SLOT": [dict(ps, len_mm=0.79, at=[6, 6])]}, sums=sm)["status"] == "CLEAN"
    p2 = dict(ps, len_mm=2.34)
    r = d({"PLANE-SLOT": [p2]}, {"PLANE-SLOT": [dict(p2, len_mm=2.35)]},
          sums={"PLANE-SLOT": {"min_term": 0.2, "terms": (5, 2)}})
    assert r["status"] == "UNEVALUATED" and "rounding bound" in r["unevaluable"][0]["why"], r
    assert d({"PLANE-SLOT": [p2]}, {"PLANE-SLOT": [dict(p2, len_mm=2.4)]},
             sums={"PLANE-SLOT": {"min_term": 0.2, "terms": (5, 4)}})["status"] == "DIRTY"
    assert d({"PLANE-SLOT": [ps]}, {"PLANE-SLOT": [dict(ps, len_mm=0.9)]})["status"] == "UNEVALUATED"
    assert d({"PAD-AXIS": [pa]}, {"PAD-AXIS": [dict(pa, angle=30.0, extra="x")]})["status"] == "UNEVALUATED"
    assert d({"NEW-CHECK": []}, {"NEW-CHECK": [{"x": 1}]})["status"] == "UNEVALUATED"
    dl = {"part": "C1", "value": "100nF", "pad": "C1.1", "net": "V", "at": [0, 0], "what": "p", "path_mm": 3.5}
    assert d({"DECAP-LOOP": [dl]}, {"DECAP-LOOP": [dict(dl, path_mm=None)]})["status"] == "DIRTY"
    xt = {"part": "Y1", "at": [0, 0], "what": "foreign", "foreign": {"A": ["F.Cu"]}}
    assert d({"XTAL": [xt]}, {"XTAL": [dict(xt, foreign={"A": ["F.Cu", "B.Cu"]})]})["status"] == "DIRTY"
    assert d({"XTAL": [xt]}, {"XTAL": [dict(xt, foreign={"A": []})]})["status"] == "CLEAN"
    nk = {"net": "+3V3", "pad": "C1.1", "layer": "B.Cu", "at": [0, 0], "width": 0.8, "pad_across": 0.56}
    assert d({"NECK-SMALLPAD": []}, {"NECK-SMALLPAD": [nk]}, net="SIG")["status"] == "CLEAN"
    assert d({"NECK-SMALLPAD": []}, {"NECK-SMALLPAD": [nk]}, net="+3V3")["status"] == "DIRTY"
    ac = {"net": "S", "layer": "F.Cu", "at": [1.0, 1.0], "angle": 45.0, "ends": 2, "what": "acute joint"}
    assert d({"ACUTE": [ac]}, {"ACUTE": [dict(ac, at=[1.05, 1.0], angle=60.0)]})["status"] == "CLEAN"
    assert d({"ACUTE": [ac]}, {"ACUTE": [dict(ac, at=[1.05, 1.0], angle=30.0)]})["status"] == "DIRTY"
    assert d({"ACUTE": [ac]}, {"ACUTE": [dict(ac, at=[2.0, 1.0], angle=60.0)]})["new"]


def test_jog_layout_quality_screen():
    import qa_layout_quality as LQ
    res = padaxis_board().run("jog_lq_padaxis")
    expect(res, "jog_lq_padaxis", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res)
    assert len(inf) == 1 and inf[0]["disposition"] == "LAYOUT_QUALITY", inf
    ev = inf[0]["layout_quality"][0]["layout_quality"]
    assert ev["status"] == "DIRTY" and any(x["check"] == "PAD-AXIS" and x["finding"]["pad"] == "U1.1" for x in ev["new"])
    saved = gate.JOG_LQ_SCHEMA.pop("PAD-AXIS")
    try:
        res = fixture_check(TMP / "jog_lq_padaxis.kicad_pcb")
    finally:
        gate.JOG_LQ_SCHEMA["PAD-AXIS"] = saved
    expect(res, "jog_lq_noschema", ["TRACK-JOG"], CLEAN_OK)
    lq = failed(res, "TRACK-JOG")[0]["sites"][0]["shortcut"]["layout_quality"]
    assert lq["status"] == "UNEVALUATED" and lq["unevaluable"][0]["why"] == "no comparison schema", lq
    res = void_board().run("jog_lq_void")
    expect(res, "jog_lq_void", [], ["TRACK-JOG"] + CLEAN_OK)
    inf = jog_info(res, "ETH_SCLK")
    assert len(inf) == 1 and inf[0]["disposition"] == "LAYOUT_QUALITY", inf
    for t in inf[0]["layout_quality"]:
        w = [x for x in t["layout_quality"]["worsened"] if x["check"] == "PLANE-SLOT"]
        assert w and w[0]["delta"]["len_mm"][0] == 4.0 and w[0]["delta"]["len_mm"][1] > 7.0, t
    path = TMP / "jog_lq_void.kicad_pcb"
    full = [{k: v for k, v in x.items() if k != "uuids"} for x in LQ.check(path, ("PLANE-SLOT",))["fails"]["PLANE-SLOT"]
            if (x["net"], x["layer"]) == ("ETH_SCLK", "F.Cu")]
    jq = gate.JogQuality(path)
    assert full and jq._run(jq.B0, ("ETH_SCLK", "F.Cu"))["PLANE-SLOT"] == gate._lq_json(full), full
    res = void_board(side_voids=False).run("jog_lq_void_equal")
    expect(res, "jog_lq_void_equal", ["TRACK-JOG"], CLEAN_OK)
    assert failed(res, "TRACK-JOG")[0]["sites"][0]["shortcut"]["layout_quality"]["status"] == "CLEAN"
    real = gate._lq_module

    def broken():
        raise ImportError("fixture: qa_layout_quality unavailable")
    jog_board().save("jog_lq_broken")
    gate._lq_module = broken
    try:
        res = fixture_check(TMP / "jog_lq_broken.kicad_pcb")
    finally:
        gate._lq_module = real
    expect(res, "jog_lq_broken", ["TRACK-JOG"], CLEAN_OK)
    lq = failed(res, "TRACK-JOG")[0]["sites"][0]["shortcut"]["layout_quality"]
    assert lq["status"] == "UNEVALUATED" and "unavailable" in lq["error"], lq


# ------------------------------------------------------------------------------------------------ TRACK-WIDTH
def two_pad_run(name, net, w, cls_w, layer=pcbnew.F_Cu, outer_w=None, basis=None):
    """a 20 mm run between two pads of `net` (F.Cu, or F pad -> via -> inner run -> via -> F pad)"""
    f = Fixture()
    for ref, x in (("A", 10), ("B", 30)):
        f.part(f"{ref}1", x, 10, [("1", 0, 0, net)])
    if layer == pcbnew.F_Cu:
        f.track(10, 10, 30, 10, net, w=w)
    else:
        f.via(12, 10, net)
        f.via(28, 10, net)
        f.track(10, 10, 12, 10, net, w=outer_w or w)
        f.track(12, 10, 28, 10, net, layer, w=w)
        f.track(28, 10, 30, 10, net, w=outer_w or w)
    return f.run_pro(name, pro(cls_w), width_basis=basis)


def width_rows(res):
    return sorted({(x["net"], x["layer"]) for x in failed(res, "TRACK-WIDTH")})


def test_width_class_fallback_and_neck():
    """an unbudgeted rail (RAIL_RE: +5V) falls back to its class width (Default 0.5): 0.25 fails, 0.5 passes, a <=
    NECK_MM neck into a 0.3 mm pad passes; a pad as wide as the class: short neck passes, long fails"""
    assert cb.WIDTH_BASIS["main"] == "budget-path" and "+5V" not in cb.BUDGET["main"]
    expect(two_pad_run("width_thin", "+5V", 0.25, 0.5), "width_thin", ["TRACK-WIDTH"], ["PAD-LAND", "TRACK-END"])
    expect(two_pad_run("width_ok", "+5V", 0.5, 0.5), "width_ok", [], ["TRACK-WIDTH"])

    def neck(name, pad_w, neck_w, neck_len):
        f = Fixture()
        f.part("U1", 10, 10, [("1", 0, 0, "+5V")])
        fp = f.part("U2", 30, 10, [("1", 0, 0, "+5V")])
        fp.Pads()[0].SetSize(pcbnew.F_Cu, V(pad_w, 1.0))
        f.track(10, 10, 30 - neck_len, 10, "+5V", w=0.5)
        f.track(30 - neck_len, 10, 30, 10, "+5V", w=neck_w)
        return f.run_pro(name, pro(0.5))
    expect(neck("width_neck", 0.3, 0.25, 0.8), "width_neck", [], ["TRACK-WIDTH"])
    expect(neck("width_eqpad_neck", 0.5, 0.493, 0.8), "width_eqpad_neck", [], ["TRACK-WIDTH"])
    expect(neck("width_eqpad_long", 0.5, 0.493, 6.0), "width_eqpad_long", ["TRACK-WIDTH"], ["PAD-LAND", "TRACK-END"])


# test_width_ct_budget: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# test_width_budget_path_leaf: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# test_width_branches_mechanism: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# test_width_gnd_part_return: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# test_width_branch_pour_ok: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# test_width_foreign_neck_rule: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


# ------------------------------------------------------------------------------------------------ real board
# test_real_ct_move: dropped in the SBC-1 port 2026-10-27 - fixture bound to CT's PoE nets / CT current budget (PRTN, +12V, U6 / U10 branch returns) or CT's adopted board; SBC-1's budget is scripts/current_budget.py


def test_pour_nets_are_layout_const():
    assert gate.POUR_NETS["main"] == set(K.POUR_NETS)
    assert gate.FORCE_NETS["main"] == set(K.FORCE_NETS) == set()
