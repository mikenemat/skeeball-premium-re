"""Board constants of the SBC-1 routing + QA pipeline (the role CT's scripts/layout_const.py plays there).
Ported from din8r-chassis-thermal/scripts/layout_const.py, 2026-10-26. SBC-1's own scripts/layout_const.py is the
harness geometry (owner calipers + scan) and is a different module; the routing / gate scripts import THIS one as K.

SBC-1 main: one board, 2 copper layers (1.6 mm, 1 oz both sides, JLC 2-layer, no via fill), 116.68 x 85.73 mm, SELV
only (no isolation barrier: the CT PRI / SEC machinery is reduced to "everything is SEC").

KiCad 10's bundled Python has no shapely: use_pylib() puts tools/pylib (shapely 2.1.2 + numpy, cp311, copied from CT
tools/pylib) on sys.path. Every gate imports this module before shapely.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PYLIB = ROOT / "tools" / "pylib"


def use_pylib():
    """shapely / numpy for KiCad's Python (it ignores PYTHONPATH); harmless under CPython (already importable there)"""
    try:
        import shapely  # noqa: F401
        return
    except ImportError:
        pass
    if PYLIB.is_dir() and str(PYLIB) not in sys.path:
        sys.path.insert(0, str(PYLIB))


use_pylib()
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# ------------------------------------------------------------------------------------------------ board / reports
MAIN_PCB = ROOT / "hardware" / "main" / "skeeball-controller.kicad_pcb"
DRC_JSON = ROOT / ".runtime" / "drc.json"         # written by scripts/qa_drc.py for MAIN_PCB
GATE_OUT = ROOT / ".runtime" / "gates"            # per-gate JSON reports of scripts/layout_gates.py
ROUTE_DIR = ROOT / ".runtime" / "route"           # scratch candidates (scripts/route_stage.py)
KIND = "main"
COPPER_LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")   # 4-layer (pass 5)
OUTER_LAYERS = ("F.Cu", "B.Cu")
OUTLINE = (116.68, 85.73)                         # = layout_const.OUTLINE (owner calipers); origin top-left
L, W = OUTLINE                                    # CT placement_main names (x extent, y extent)
EDGE_BAND_MM = 0.4                                # EDGE_KEEPOUT: copper-edge rule 0.3 mm + margin (CT trap: Freerouting
                                                  # keeps only the class clearance to the outline)

# ------------------------------------------------------------------------------------------------ paused parts
# Paused parts removed from routing candidates (route_prep.py): none since 2026-10-27 - the score jacks J21-J28 are
# released (contact map known: pin 1 +5V_SYS, 2 score line, 3 NC, 4 GND) and routed; the JACK_STRIP keep-out is gone.
PAUSED_REFS = ()

# ------------------------------------------------------------------------------------------------ nets
# Nets whose pads may connect through a pour. GND: both layers poured (owner: GND as pours, not traces). +5V_IN: the
# lead's locked power copper (scripts/power_copper.py: B.Cu strip J1 -> F1 / F2, F.Cu zone + via array at F1 / F2) is
# a pour net ONLY when such a zone exists on the board (pour_nets(board)); before power_copper lands it is routed.
BASE_POUR_NETS = frozenset({"GND"})
CELL_POUR_NETS = frozenset({"+5V_IN"})
POUR_NETS = BASE_POUR_NETS | CELL_POUR_NETS
FORCE_NETS = frozenset()
GROUND_NETS = frozenset({"GND"})


def pour_nets(board=None):
    """the pour nets of THIS board: GND always, a CELL net only if the board carries a (non rule-area) zone of it"""
    if board is None:
        return set(POUR_NETS)
    zn = {z.GetNetname() for z in board.Zones() if not z.GetIsRuleArea()}
    return set(BASE_POUR_NETS) | {n for n in CELL_POUR_NETS if n in zn}


# ------------------------------------------------------------------------------------------------ isolation (none)
ISOLATION_RULE_AREA = None
ISO_LATERAL_MM = 0.0
BARRIER_PINS = {}
BARRIER_PARTS = frozenset()
SEC_GROUND = "GND"
PRI_GROUND = None


def pri_nets():
    return set()


def side_of(net, pri=None):
    """SBC-1 is SELV only: every named net is 'SEC' (CT API kept for the ported gates)"""
    if not net or net.startswith(("unconnected-", "NC_")):
        return None
    return "SEC"


# ------------------------------------------------------------------------------------------------ mechanics
ENCLOSURE_PY = None          # the board mounts in the stock machine on 4 standoffs (no project enclosure)
BOARD_MECHANICS = None
STANDOFF_MM = None


def enclosure_standoff_mm():
    raise ValueError("SBC-1 has no project enclosure (stock machine standoffs)")
