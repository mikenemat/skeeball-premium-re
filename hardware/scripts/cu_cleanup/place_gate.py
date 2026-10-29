# ported from din8r-chassis-thermal/scripts/cu_cleanup/place_gate.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R tools/pfr2/place_gate.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN)
"""CT clearance model for the copper cleanup (CPython or KiCad Python, no pcbnew): required(net_a, net_b, ...) -> mm.

CT adaptation (2026-10-17): the parent's DRU rule table (LINE-SELV 6.5, HV functional, ETH_CHASSIS, maker pads) is
DIN-8R-only; CT has NO .kicad_dru, so KiCad's clearance is the larger net-class clearance (scripts/pcb_rules.py: every
class 0.15 mm) or a larger pad local override. On top of that the CT self-imposed isolation rule (CLAUDE.md
"Isolation barrier", board_const.ISO_LATERAL_MM = 2.00 mm, gated by scripts/qa_crosslayer.py on every layer pair): PRI
(design.PRI_NETS) copper keeps 2.00 mm laterally from SEC copper. The parent's placement check() is not needed by
the cleanup and is not ported.

Net records are dump_geom nets with "side" ('PRI' | 'SEC' | None) added by scripts/copper_cleanup.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import board_const as K  # noqa: E402

ISO_MM = K.ISO_LATERAL_MM


def cross_side(na, nb):
    a, b = na.get("side"), nb.get("side")
    return a is not None and b is not None and a != b


def required(na, nb, ref_a=None, ref_b=None, kind_a=None, kind_b=None, clr_a=None, clr_b=None):
    """same-layer clearance (mm) KiCad DRC applies between copper of net records na / nb (+ pad local overrides),
    raised to the PRI-SEC isolation distance across the barrier"""
    v = max(na.get("clearance") or 0.15, nb.get("clearance") or 0.15, clr_a or 0.0, clr_b or 0.0)
    if cross_side(na, nb):
        v = max(v, ISO_MM)
    return v
