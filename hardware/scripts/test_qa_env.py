# ported from din8r-chassis-thermal/scripts/test_qa_env.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
"""Environment + shared-constant guards for the board QA gates (KiCad Python, via scripts/conftest.py).

  pcbnew / shapely      KiCad 10's Python imports pcbnew and (through board_const.use_pylib) shapely 2
  pour_nets            board_const.POUR_NETS is exactly the set of nets that own a copper zone on the adopted board
                       (a new pour net must be added deliberately: PAD-LAND / POUR-PAD / TRACK-END depend on it)
  barrier_pins         every BARRIER_PINS side holds only PRI (resp. SEC / NC) nets of design.py, every pin of the
                       part is on one side, and the barrier parts are exactly the parts with both PRI and SEC pins
  standoff             enclosure.py STANDOFF is readable (qa_twoside bottom-height rule)
"""
import board_const as K

KICAD_PYTHON = True


def test_pcbnew_shapely():
    import pcbnew
    import shapely
    from shapely.geometry import Point
    assert pcbnew.FromMM(1.0) == 1000000
    assert shapely.__version__.startswith("2.")
    assert abs(Point(0, 0).buffer(1.0, 64).area - 3.14) < 0.01


def test_pour_nets_cover_board_zones():
    import pcbnew
    b = pcbnew.LoadBoard(str(K.MAIN_PCB))      # hardware/main: GND pours exist only on routed candidates
    nets = {z.GetNetname() for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetCode() > 0}
    assert nets <= set(K.POUR_NETS), f"zone nets not declared in POUR_NETS: {sorted(nets - set(K.POUR_NETS))}"


# CT-only tests dropped in the SBC-1 port (2026-10-27): barrier pins (no PoE barrier), enclosure standoff (no
# project enclosure)


def test_current_classes_cover_pcb_rules():
    """every non-Default netclass pcb_rules.py defines (Power / Power12 / PowerFan / Rail ...) is a current class of
    current_budget, so an unbudgeted net of that class still gets its class width gated (TRACK-WIDTH fallback)"""
    import re
    import current_budget as cb
    src = (K.SCRIPTS / "pcb_rules.py").read_text(encoding="utf-8")
    classes = set(re.findall(r'mk\("([^"]+)"', src))
    assert classes and classes <= cb.CURRENT_CLASSES, f"netclasses not in CURRENT_CLASSES: {sorted(classes - cb.CURRENT_CLASSES)}"
