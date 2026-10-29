"""Apply THE rule set (scripts/pcb_rules.py) to a board and SaveBoard it (KiCad Python) - SBC-1's stand-in for DIN-8R
tools/pfr2/apply_rules.py (which wrote DIN-8R's generated .kicad_dru) in tools/pfr2/run_stage.py. New 2026-10-27.

    python scripts/local_run.py pcb_rules_apply.py BOARD
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pcb_rules  # noqa: E402

b = pcbnew.LoadBoard(sys.argv[1])
pcb_rules.apply(b)
pcb_rules.save(b, sys.argv[1])
print("pcb_rules applied:", sys.argv[1])
