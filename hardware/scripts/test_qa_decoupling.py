# ported from din8r-chassis-thermal/scripts/test_qa_decoupling.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/test_qa_decoupling.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN).
"""Fixtures for qa_decoupling.py (CT port 2026-10-17). Boards are built in memory (saved under .runtime/tmp only where a
serving-decap stack needs the file); the design is a stand-in (parts: lib_id, value, block, note). Every test pins
qa_power_layout.DECAP to its own rows (default: none) so the live CT table never leaks into a fixture.

  decap_delegation  a DECAP-covered IC pin is judged by qa_power_layout.DECAP with qa_power_layout.MAX_MM read live:
                    its cap at 2.5 mm passes with MAX_MM 3.0 and FAILs (DECAP-ROW) when MAX_MM is monkeypatched to 2.0;
                    at 4.0 mm it FAILs although LIMIT_MM (6.0) would pass it - never a second limit; no IC-NOCAP for it
  decap_row_cap     a DECAP-row cap is judged by its row (MAX_MM), not CAP-FAR's LIMIT_MM; a missing row part FAILs
  decap_note        a row whose part note names another pin of the row's IC FAILs DECAP-NOTE; a matching note passes
  ic_uncovered      an uncovered IC power pin with no cap FAILs IC-NOCAP (fail closed); a declared cap within LIMIT_MM
                    passes; a cap beyond LIMIT_MM FAILs
  ic_declared       a cap serves only its declared ICs: named in its note, else its block's (a block-A cap beside a block-B
                    IC: FAIL), else any IC on the rail
  ic_side           a cap on the other side, not stacked: cannot serve (FAIL); a serving stack can (PASS)
  ic_pin_types      only power pins on supply nets are checked; ground power pins / outputs are not; an unresolvable IC
                    is ic_unresolved (exit 2); stacked passive duplicates of a power_in pin are power pins (ESP32-S3 3 /
                    56 from KiCad's symbol)
  regulator         CT buck (Regulator_Switching symbol): its output cap pairs with its inductor although another IC is
                    nearer; a custom-symbol LDO is recognised by part class; a far input cap is FLAGGED (CAP-FAR)
  loads             a VPP input cap pairs with the flyback transformer winding (T); a +12V bulk cap pairs with the
                    rectifier D6 (BULK_SOURCES); a 100 nF beside an IC of its own block pairs with it
  side_rule         a bottom cap under a top load: SIDE | a serving decap (pads stacked, a via at each pad) passes, also
                    facing the IC's signal pin (CT owner 2026-10-17) | the same without vias, or merely on the other
                    side: SIDE
  exceptions        CT tables are empty; the mechanism: a bound SIDE_EXCEPTIONS entry exempts | an unbound one does not;
                    an exact ACCEPTED entry accepts | a stale one FAILs (STALE)
KiCad Python: py scripts/local_run.py kicad_test_runner.py scripts/test_qa_decoupling.py   (or py -m pytest)
"""
import math
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

import board_const  # noqa: F401  (tools/pylib)
import pcbnew

import qa_decoupling as Q
import qa_power_layout as PL

KICAD_PYTHON = True

ROOT = Path(__file__).resolve().parents[1]
(ROOT / ".runtime" / "tmp").mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="ct_decoup_", dir=str(ROOT / ".runtime" / "tmp")))
mm = pcbnew.FromMM
_SAVED = {}


def setup_module():
    _SAVED["DECAP"], _SAVED["MAX_MM"] = list(PL.DECAP), PL.MAX_MM


def teardown_module():
    PL.DECAP[:] = _SAVED.get("DECAP", PL.DECAP)
    PL.MAX_MM = _SAVED.get("MAX_MM", PL.MAX_MM)
    shutil.rmtree(TMP, ignore_errors=True)


class decap:
    """pin qa_power_layout.DECAP (and optionally MAX_MM) for one fixture, restored afterwards"""

    def __init__(self, rows=(), max_mm=None):
        self.rows, self.max_mm = list(rows), max_mm

    def __enter__(self):
        self.old = (list(PL.DECAP), PL.MAX_MM)
        PL.DECAP[:] = self.rows
        if self.max_mm is not None:
            PL.MAX_MM = self.max_mm
        return self

    def __exit__(self, *exc):
        PL.DECAP[:] = self.old[0]
        PL.MAX_MM = self.old[1]
        return False


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


class Fx:
    def __init__(self):
        self.b = pcbnew.BOARD()
        self.b.SetCopperLayerCount(4)
        self.nets, self.parts = {}, {}

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def part(self, ref, x, y, pads, lib_id, value, block, back=False, note=""):
        fp = pcbnew.FOOTPRINT(self.b)
        fp.SetReference(ref)
        fp.SetValue(value)
        self.b.Add(fp)
        for num, dx, dy, net in pads:
            p = pcbnew.PAD(fp)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECTANGLE)
            p.SetSize(pcbnew.F_Cu, V(0.6, 0.6))
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetLayerSet(p.SMDMask())
            p.SetNumber(num)
            p.SetNet(self.net(net))
            p.SetFPRelativePosition(V(dx, dy))
            fp.Add(p)
        fp.SetPosition(V(x, y))
        if back:
            fp.Flip(V(x, y), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        self.parts[ref] = NS(lib_id=lib_id, value=value, block=block, note=note)
        return fp

    def cap(self, ref, x, y, net, value, block, back=False, note="", gnd="GND"):
        """supply pad 1 at (x, y), ground pad 2 1 mm to the right (mirrored to the left on the bottom)"""
        return self.part(ref, x, y, [("1", 0, 0, net), ("2", 1.0, 0, gnd)], "Device:C", value, block, back, note)

    def via(self, x, y, net):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(V(x, y))
        v.SetWidth(mm(0.6))
        v.SetDrill(mm(0.3))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(net))
        self.b.Add(v)

    def run(self, **kw):
        return Q.check(self.b, NS(parts=self.parts), **kw)

    def run_saved(self, name, **kw):
        """saved and reloaded: the serving-decap test reads the board file through qa_layout_quality.Board"""
        path = TMP / f"{name}.kicad_pcb"
        self.b.Save(str(path))
        return Q.check(pcbnew.LoadBoard(str(path)), NS(parts=self.parts), **kw)


PW2 = {"1": "power_in", "2": "power_in"}


def ic9(f, x=20, y=20, back=False, ref="U21", block="blk"):
    """a test IC: pin 1 +3V3 (power) at (x, y), pin 2 GND (power, ground) 1 mm right, pin 3 a signal 2 mm right"""
    return f.part(ref, x, y, [("1", 0, 0, "+3V3"), ("2", 1.0, 0, "GND"), ("3", 2.0, 0, "SIGX")], "din8r_ct:TEST_IC",
                  "TESTIC", block, back=back)


def ic_bad(res):
    return sorted((x["ic"], x["pin"]) for x in res["fails"]["IC-NOCAP"])


def classes(res):
    return {k for k, v in res["fails"].items() if v}


# ------------------------------------------------------------------------------------------------ DECAP delegation
def _covered(d):
    f = Fx()
    ic9(f)
    f.cap("C21", 20, 20 + d, "+3V3", "100nF", "blk")
    return f


def test_decap_delegation_uses_power_layout_max_mm():
    rows = [("U21", "1", "C21", "fixture: 0.1 uF at the pin")]
    with decap(rows):
        res = _covered(2.5).run(types={"U21": PW2})
        assert res["status"] == "PASS", res["fails"]
        row = next(x for x in res["ic_rows"] if x["ic"] == "U21" and x["pin"] == "1")
        assert row["covered"] and row["ok"] and row["rows"][0][0] == "C21", row
    with decap(rows, max_mm=2.0):                                  # the imported limit, monkeypatched in-process
        res = _covered(2.5).run(types={"U21": PW2})
        r = res["fails"]["DECAP-ROW"]
        assert len(r) == 1 and r[0]["part"] == "C21" and r[0]["max_mm"] == 2.0 and abs(r[0]["d_mm"] - 2.5) < 1e-6, r
        assert not res["fails"]["IC-NOCAP"] and not res["fails"]["CAP-FAR"], res["fails"]
    with decap(rows):                                              # 4.0 mm: LIMIT_MM (6.0) would pass, MAX_MM fails
        res = _covered(4.0).run(types={"U21": PW2})
        assert classes(res) == {"DECAP-ROW"}, res["fails"]
        assert Q.LIMIT_MM > 4.0 > PL.MAX_MM
    with decap(()):                                                # uncovered: the parent's 6.0 mm rule
        res = _covered(4.0).run(types={"U21": PW2})
        assert res["status"] == "PASS", res["fails"]
        row = next(x for x in res["ic_rows"] if x["ic"] == "U21" and x["pin"] == "1")
        assert not row["covered"] and row["cap"] == "C21", row


def test_decap_row_cap_and_missing_part():
    # a DECAP-row cap whose row pin is NOT a power pin (a reference pin): judged by its row only, never CAP-FAR
    f = Fx()
    f.part("U22", 20, 20, [("1", 0, 0, "VREF_X"), ("2", 0, 1, "GND")], "din8r_ct:TEST_IC", "T", "blk")
    f.part("J1", 25, 20, [("1", 0, 0, "VREF_X")], "Connector:Conn", "J", "blk")     # a load for the cap side
    f.cap("C22", 28, 20, "VREF_X", "100nF", "blk")                                  # 8 mm from U22.1, 3 mm from J1
    with decap([("U22", "1", "C22", "fixture: REF cap at the pin")]):
        res = f.run(types={"U22": {"1": "input", "2": "power_in"}})
    assert [x["part"] for x in res["fails"]["DECAP-ROW"]] == ["C22"] and not res["fails"]["CAP-FAR"], res["fails"]
    assert "C22" in res["info"]["decap_row_caps"]
    with decap([("U21", "1", "C99", "fixture: a part that is not on the board")]):
        res = _covered(1.0).run(types={"U21": PW2})
    r = res["fails"]["DECAP-ROW"]
    assert len(r) == 1 and r[0]["what"] == "C99 not on the board", r


def test_decap_note_mismatch():
    def case(note):
        f = Fx()
        f.part("U23", 20, 20, [("2", 0, 0, "+3V3"), ("3", 0, 0.5, "+3V3"), ("9", 1, 0, "GND")], "din8r_ct:TEST_IC",
               "T", "mcu")
        f.cap("C23", 21.0, 20, "+3V3", "100nF", "mcu", note=note)
        with decap([("U23", "2", "C23", "fixture")]):
            return f.run(types={"U23": {"2": "power_in", "3": "power_in", "9": "power_in"}})
    res = case("pin 3 VDD3P3: 0.1 uF within 1.5 mm of the pin")
    assert [(x["pin"], x["part"], x["note_pins"]) for x in res["fails"]["DECAP-NOTE"]] == [("2", "C23", ["3"])], res
    assert not case("pin 2 VDD3P3: 0.1 uF")["fails"]["DECAP-NOTE"]
    assert not case("VDDA pins 2 / 3")["fails"]["DECAP-NOTE"]
    assert not case("U99 pin 3 bypass")["fails"]["DECAP-NOTE"]     # names another IC: its pin numbers are that IC's
    assert Q.note_pins("VDDA pins 55 / 56") == {"55", "56"}


# ------------------------------------------------------------------------------------------------ IC side
def test_ic_uncovered_fail_closed():
    with decap(()):
        f = Fx()
        ic9(f)
        res = f.run(types={"U21": PW2})
        assert ic_bad(res) == [("U21", "1")], res["ic_rows"]                         # no cap at all
        assert "no bypass cap" in res["fails"]["IC-NOCAP"][0]["what"]
        res = _covered(3.0).run(types={"U21": PW2})
        assert not ic_bad(res), res["fails"]
        res = _covered(7.0).run(types={"U21": PW2})
        assert ic_bad(res) == [("U21", "1")] and res["fails"]["IC-NOCAP"][0]["cap"] == "C21", res["fails"]


def test_ic_declared_note_block_rail():
    with decap(()):
        # note: C31 "Decouples U31" beside U32 cannot serve U32; U31 (6.8 mm away) fails, U32 fails (declared U31)
        f = Fx()
        f.part("U31", 10, 10, [("5", 0, 0, "+3V3"), ("2", 0, 1, "GND")], "din8r_ct:TEST_IC", "A", "ade")
        f.part("U32", 15, 15, [("5", 0, 0, "+3V3"), ("3", 0, 1, "GND")], "din8r_ct:TEST_IC", "B", "ade")
        f.cap("C31", 14.0, 15, "+3V3", "100nF", "ade", note="Decouples U31 VCC pin 5")
        res = f.run(types={"U31": {"5": "power_in"}, "U32": {"5": "power_in"}})
        assert ic_bad(res) == [("U31", "5"), ("U32", "5")], res["ic_rows"]
        r = next(x for x in res["ic_rows"] if x["ic"] == "U31")
        assert r["cap"] == "C31" and r["basis"] == "note", r

        def two_blocks(cap_block):
            f = Fx()
            f.part("U25", 10, 10, [("1", 0, 0, "+3V3"), ("2", 0, 1, "GND")], "din8r_ct:TEST_IC", "A", "blkA")
            f.part("U26", 40, 10, [("1", 0, 0, "+3V3"), ("2", 0, 1, "GND")], "din8r_ct:TEST_IC", "B", "blkB")
            f.cap("C25", 11, 10, "+3V3", "100nF", "blkA")
            f.cap("C26", 41, 10, "+3V3", "100nF", cap_block)
            return f.run(types={"U25": PW2, "U26": PW2})
        assert ic_bad(two_blocks("blkA")) == [("U26", "1")]                      # block-A cap beside block-B IC
        assert ic_bad(two_blocks("rails")) == []                                 # a rail cap serves any IC


def test_ic_side_and_serving_stack():
    with decap(()):
        f = Fx()
        ic9(f)
        f.cap("C27", 20, 22, "+3V3", "1uF 16V", "blk", back=True)               # 2 mm away, other side, not stacked
        res = f.run(types={"U21": PW2})
        assert ic_bad(res) == [("U21", "1")], res["ic_rows"]
        f = Fx()
        ic9(f)
        f.cap("C28", 20, 20, "+3V3", "100nF", "blk", back=True)                 # stacked under U21.1 / U21.2,
        f.via(20, 21.0, "+3V3")                                                  # a via at each cap pad
        f.via(21, 21.0, "GND")
        res = f.run_saved("ic_serving", types={"U21": PW2})
        assert not ic_bad(res) and res["info"]["serving_decap"] == [("C28", "U21")], res


def test_ic_pin_types():
    with decap(()):
        f = Fx()
        f.part("U29", 20, 20, [("1", 0, 0, "+3V3"), ("2", 0, 1, "GND"), ("3", 0, 2, "+1V8"), ("4", 0, 3, "+3V3")],
               "din8r_ct:TEST_IC", "T", "blk")
        f.part("U30", 60, 20, [("1", 0, 0, "+3V3")], "din8r_ct:NO_SUCH_SYMBOL_FOR_TEST", "T", "blk")
        res = f.run(types={"U29": {"1": "input", "2": "power_in", "3": "power_out", "4": "power_in"}})
        assert sorted((x["ic"], x["pin"]) for x in res["ic_rows"]) == [("U29", "4")], res["ic_rows"]
        res = f.run()                                                            # library lookup
        assert set(res["ic_unresolved"]) == {"U29", "U30"} and res["status"] == "ERROR", res["ic_unresolved"]
    # stacked duplicates: KiCad's ESP32-S3 symbol marks VDD3P3 pin 3 / VDDA pin 56 passive
    assert Q.power_pin_numbers([("2", "VDD3P3", "power_in"), ("3", "VDD3P3", "passive"), ("4", "CHIP_PU", "input"),
                                ("21", "XTAL_32K_P", "passive")]) == {"2", "3"}
    f = Fx()
    f.part("U7", 20, 20, [("2", 0, 0, "+3V3"), ("3", 0, 0.4, "+3V3"), ("56", 0, 0.8, "+3V3")],
           "MCU_Espressif:ESP32-S3", "ESP32-S3FH4R2", "mcu")
    types, bad = Q.pin_types(f.b, NS(parts=f.parts))
    assert not bad and all(types["U7"][n] == "power_in" for n in ("2", "3", "56")), (types.get("U7"), bad)


# ------------------------------------------------------------------------------------------------ cap side
def _buck():
    f = Fx()
    f.part("U5", 40, 25, [("4", 0, -1, "GND"), ("5", 0, 0, "BUCK_SW"), ("3", 0, 1, "VIN_BUCK")],
           "Regulator_Switching:TPS62933", "TPS62933DRLR", "buck")
    f.part("L1", 30, 25, [("1", 4, 0, "BUCK_SW"), ("2", 0, 0, "+3V3")], "Device:L", "4.7uH", "buck")   # L1.2 (30, 25)
    return f


def row(res, ref):
    return next(x for x in res["cap_rows"] if x["cap"] == ref)


def test_regulator_pairing():
    with decap(()):
        regs = Q.regulators(_buck().b, NS(parts=_buck().parts))
        assert set(regs) == {"U5"} and [r for _, _, r in regs["U5"][1]["+3V3"]] == ["L1"], regs
        f = _buck()
        f.cap("C28", 27.5, 25, "+3V3", "22uF 10V", "buck")
        f.part("U40", 26, 25, [("5", 0, 0, "+3V3"), ("2", 0, 1, "GND")], "din8r_ct:TEST_IC", "T", "other")
        res = f.run(types={"U40": {"5": "power_in"}})
        r = row(res, "C28")
        assert r["load"] == "L1" and r["regulator"] == "U5" and not r["bad"], r
        f = _buck()                                                    # an input cap 8 mm from the buck VIN
        f.cap("C24", 48, 26, "VIN_BUCK", "1uF 25V", "buck")
        res = f.run(types={})
        assert row(res, "C24")["load"] == "U5" and [x["cap"] for x in res["fails"]["CAP-FAR"]] == ["C24"], res
        f = Fx()                                                       # a custom-symbol LDO by part class
        f.part("U41", 60, 10, [("1", 0, 0, "+5V"), ("5", 0, 2, "+3V3"), ("2", 1, 1, "GND")], "din8r_ct:TLV75533",
               "TLV75533PDBVR", "ldo")
        assert set(Q.regulators(f.b, NS(parts=f.parts))) == {"U41"}


def test_loads_transformer_rectifier_block():
    with decap(()):
        f = Fx()
        f.part("T2", 47, 6, [("5", 0, -2.5, "VPP"), ("3", 0, 2.5, "SW_PRI")], "din8r_ct:PA2467NL", "PA2467NL", "fly")
        f.part("U1", 20, 6, [("1", 0, 0, "VPP"), ("16", 0, 1, "VSS")], "din8r_ct:TPS23751", "TPS23751", "pd")
        f.cap("C12", 44.5, 3.5, "VPP", "2.2uF 100V", "pd_bulk", gnd="PRTN")
        res = f.run(types={"U1": {"1": "power_in", "16": "power_in"}})
        assert row(res, "C12")["load"] == "T2" and not row(res, "C12")["bad"], row(res, "C12")
        f = Fx()
        f.part("D6", 66, 11, [("1", 0, -1.5, "+12V"), ("2", 0, 1.5, "SW_SEC")], "Device:D_Schottky", "SS510B", "sec")
        f.part("U6", 95, 15, [("5", 0, 0, "+12V"), ("8", 0, 1, "GND")], "din8r_ct:TPS259470", "TPS259470", "efuse")
        f.cap("C17", 68, 4, "+12V", "100uF 25V", "sec")
        res = f.run(types={"U6": {"5": "power_in", "8": "power_in"}})
        assert row(res, "C17")["load"] == "D6" and not res["fails"]["CAP-FAR"], row(res, "C17")
        f = Fx()
        f.part("U47", 20, 10, [("5", 0, 0, "+5V"), ("2", 0, 1, "GND")], "din8r_ct:TEST_IC", "T", "uv")
        f.cap("C49", 21, 10, "+5V", "100nF", "uv")
        res = f.run(types={"U47": {"5": "power_in"}})
        assert row(res, "C49")["load"] == "U47" and res["status"] == "PASS", res


def test_side_rule_and_serving_decap():
    with decap(()):
        f = _buck()
        f.cap("C25", 41, 26, "VIN_BUCK", "100nF 50V", "buck", back=True)       # bottom, its regulator on top
        res = f.run(types={})
        assert [(x["cap"], x["load"]) for x in res["fails"]["SIDE"]] == [("C25", "U5")], res["fails"]["SIDE"]

        def serving(name, dx=0.0, vias=True, stacked=True):
            f = Fx()
            ic9(f)
            y = 20 if stacked else 30
            f.cap("C90", 20 + dx, y, "+3V3", "100nF", "blk", back=True)       # pad 1 +3V3 at x, pad 2 GND at x + 1
            if vias:
                f.via(20 + dx, y + 1.0, "+3V3")
                f.via(21 + dx, y + 1.0, "GND")
            return f.run_saved(name, types={"U21": PW2})
        res = serving("serving_ok")
        assert res["info"]["serving_decap"] == [("C90", "U21")] and not res["fails"]["SIDE"], res
        # CT owner 2026-10-17 (qa_layout_quality.SERVING_DECAP_ANY_IC_PAD): a stack facing the IC's own signal pin
        # serves it too
        res = serving("serving_signal_pin", dx=1.0)
        assert res["info"]["serving_decap"] == [("C90", "U21")] and not res["fails"]["SIDE"], res
        for name, kw in (("serving_no_vias", {"vias": False}), ("serving_not_stacked", {"stacked": False})):
            res = serving(name, **kw)
            assert [(x["cap"], x["load"]) for x in res["fails"]["SIDE"]] == [("C90", "U21")], (name, res["fails"])
            assert not res["info"]["serving_decap"], name


def test_ct_tables_empty_and_mechanism():
    assert Q.SIDE_EXCEPTIONS == {} and Q.SIDE_BIND == {}, "CT has no side exceptions"
    assert all(not v for v in Q.ACCEPTED.values()), "CT has no owner-accepted findings"

    def cross(exceptions=None, bind=None):
        f = Fx()
        ic9(f)
        f.cap("C77", 20, 22, "+3V3", "1uF 16V", "blk", back=True)
        with decap(()):
            return f.run(exceptions=exceptions, bind=bind, types={"U21": PW2})
    res = cross()
    assert [x["cap"] for x in res["fails"]["SIDE"]] == ["C77"] and ic_bad(res) == [("U21", "1")]
    exc = {"C77": "bulk partner of U21 on B"}
    res = cross(exc, {"C77": ("B", "U21", 2.1, {"U21": 2.1})})              # bound: honoured on both sides
    assert not res["fails"]["SIDE"] and not ic_bad(res) and not res["fails"]["STALE"], res["fails"]
    res = cross(exc, {"C99": ("B", "U21", 5.0, {})})                         # unbound under a binding policy
    assert [x["cap"] for x in res["fails"]["SIDE"]] == ["C77"] and ic_bad(res) == [("U21", "1")], res["fails"]
    saved = dict(Q.SIDE_EXCEPTIONS)
    try:                                         # the module's (empty) tables are bound: an entry without a binding
        Q.SIDE_EXCEPTIONS.update(exc)            # is never honoured, and it is STALE
        res = cross()
        assert [x["cap"] for x in res["fails"]["SIDE"]] == ["C77"] and ic_bad(res) == [("U21", "1")], res["fails"]
        assert [x["key"] for x in res["fails"]["STALE"]] == ["C77"], res["fails"]["STALE"]
    finally:
        Q.SIDE_EXCEPTIONS.clear()
        Q.SIDE_EXCEPTIONS.update(saved)
    # ACCEPTED: an exact entry accepts the finding; an entry whose finding is gone is STALE
    f = Fx()
    ic9(f)
    f.cap("C21", 20, 27.0, "+3V3", "100nF", "blk")                          # 7 mm: IC-NOCAP U21.1 and CAP-FAR
    acc = {"distance": {"C21": ("+3V3", "U21", 7.1, "fixture")}, "side": {}, "ic": {"U21.1": ("+3V3", "C21", 7.1, "fx")}}
    with decap(()):
        res = f.run(types={"U21": PW2}, accepted=acc)
        assert res["status"] == "PASS" and res["info"]["ic_accepted"] == ["U21.1"], res["fails"]
        acc["distance"]["C22"] = ("+3V3", "U21", 7.1, "fixture: no such finding")
        res = f.run(types={"U21": PW2}, accepted=acc)
        assert [x["key"] for x in res["fails"]["STALE"]] == ["C22"], res["fails"]


def test_real_board_runs():
    """the adopted CT board (read only): every IC resolves its pin types (no exit 2) and every IC power pin on a supply
    net is covered by qa_power_layout.DECAP or judged by the IC-side rule"""
    import design
    import qa_layout_quality as LQ
    LB = LQ.Board(board_const.MAIN_PCB)
    res = Q.check(LB.b, design.D, LB=LB)
    assert not res["ic_unresolved"] and res["status"] in ("PASS", "FAIL"), res["ic_unresolved"]
    assert res["info"]["ic_power_pins"] >= 19 and res["info"]["bypass_caps"] >= 30, res["info"]
    assert all(math.isfinite(x["d_mm"]) or x["rule"] == "qa_power_layout.DECAP" for x in res["cap_rows"]
               if x["d_mm"] is not None)
