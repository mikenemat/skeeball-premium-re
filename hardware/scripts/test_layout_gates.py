# ported from din8r-chassis-thermal/scripts/test_layout_gates.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
"""CPython tests of scripts/layout_gates.py (the board QA gate runner) and its wiring (py -m pytest).

  registry      every registered gate script exists; the runner's registry and run_gates.py's BLOCKING step list are
                the same gates in the same order (nothing registered but not run, nothing run twice)
  fab_outputs   fab_outputs.py gates its export on layout_gates.py
  status        finish(): any FAIL -> FAIL; else any ERROR / missing / empty -> ERROR (fail closed); all PASS -> PASS
  drc_sha       the DRC report key ignores only the run date (qa_drc.py rewrites the report on every run)
  compact       a finding line leads with its identifying / locating fields and drops bulky ones
  missing       a gate whose script is missing is an ERROR, never a pass
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import layout_gates as LG  # noqa: E402


def test_registry_scripts_exist():
    for name, (runner, tmpl, *rep) in LG.GATES.items():
        assert runner in ("py", "kicad"), name
        assert (HERE / tmpl[0]).is_file(), f"{name}: {tmpl[0]} missing"


# test_run_gates_runs_every_gate_once: dropped in the SBC-1 port 2026-10-27 - run_gates.py / fab_outputs.py are not ported (no release flow yet)


# test_fab_outputs_gates_on_layout: dropped in the SBC-1 port 2026-10-27 - run_gates.py / fab_outputs.py are not ported (no release flow yet)


def test_finish_status_fail_closed():
    def res(*st):
        return {"gates": {f"g{i}": {"status": s} for i, s in enumerate(st)}}
    assert LG.finish(res("PASS", "PASS"), False)["status"] == "PASS"
    assert LG.finish(res("PASS", "ERROR"), False)["status"] == "ERROR"
    assert LG.finish(res("ERROR", "FAIL"), False)["status"] == "FAIL"
    assert LG.finish(res(), False)["status"] == "ERROR"


def test_drc_sha_ignores_date_only():
    d = Path(tempfile.mkdtemp())
    a, b, c = d / "a.json", d / "b.json", d / "c.json"
    a.write_text(json.dumps({"date": "2026-10-17T01:00:00", "violations": [1]}), encoding="utf-8")
    b.write_text(json.dumps({"date": "2026-10-17T02:00:00", "violations": [1]}), encoding="utf-8")
    c.write_text(json.dumps({"date": "2026-10-17T02:00:00", "violations": [2]}), encoding="utf-8")
    assert LG.drc_sha(a) == LG.drc_sha(b) != LG.drc_sha(c)
    assert LG.drc_sha(d / "missing.json") is None


def test_compact_line():
    line = LG.compact({"uuids": ["x"], "what": "via in pad", "net": "GND", "at": [1.0, 2.0], "pad": "U1.1",
                       "candidates": [1, 2, 3], "angle": 45.04321})
    assert line.startswith("pad=U1.1, net=GND, at=[1.0, 2.0], what=via in pad"), line
    assert "uuids" not in line and "candidates" not in line and "angle=45.043" in line


def test_missing_script_is_error():
    saved = dict(LG.GATES)
    LG.GATES["ghost"] = ("py", ["no_such_gate.py", "{board}"])
    try:
        g = LG.run_gate("ghost", HERE / "x.kicad_pcb", Path(tempfile.mkdtemp()), "drc.json")
        assert g["status"] == "ERROR" and "missing" in g["detail"], g
    finally:
        LG.GATES.clear()
        LG.GATES.update(saved)


def test_crash_without_report_is_error():
    """a gate that dies (Python exits 1, like a FAIL) without writing its report is a tool error, not a FAIL"""
    d = Path(tempfile.mkdtemp())
    crash = HERE / "_test_crash_gate.py"
    crash.write_text("raise SystemExit(1)\n", encoding="utf-8")
    saved = dict(LG.GATES)
    LG.GATES["crash"] = ("py", ["_test_crash_gate.py", "{board}", "--json", "{json}"])
    try:
        g = LG.run_gate("crash", HERE / "x.kicad_pcb", d, "drc.json")
        assert g["rc"] == 1 and g["status"] == "ERROR", g
    finally:
        LG.GATES.clear()
        LG.GATES.update(saved)
        crash.unlink()
