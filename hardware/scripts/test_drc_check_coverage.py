# ported from din8r-chassis-thermal/scripts/test_drc_check_coverage.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: new for CT (the parent has no fixtures for scripts/drc_check_coverage.py); exercises the ported gate
"""Fixtures for scripts/drc_check_coverage.py (CPython; kicad-cli for the real-report cases).

Each FAIL class has a negative fixture (it must fire) and the clean report is the positive control:
  INVENTORY        ignored_checks missing / not a list / a row without a key; included_severities missing
  CHECK-DISABLED   every REQUIRED_CHECKS key, one at a time, in ignored_checks
  SEVERITIES       a report filtered to errors (kicad-cli --severity-error), and one without exclusions
  WRONG-BOARD      source names another board / no source
  STALE            dated before the board file's last write / no date; inside DRC_DATE_SLACK_S passes
  EXCLUDED         an excluded violation of a required check (a non-required excluded type passes)
  tool errors      missing report, not JSON, wrong $schema -> ToolError and CLI exit 2
  KiCad 10 keys    a live kicad-cli run with every candidate key set to 'ignore' lists exactly KICAD10_CHECK_KEYS
                   (via_diameter is not a KiCad 10 key); REQUIRED_CHECKS is a subset; a real --severity-all report
                   of a fresh board passes, a real --severity-error report FAILs
    py -m pytest scripts/test_drc_check_coverage.py     (or: python scripts/test_drc_check_coverage.py)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import drc_check_coverage as G  # noqa: E402
import board_const as LC  # noqa: E402

TMP = None
KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
MINI_PCB = """(kicad_pcb (version 20240108) (generator "pcbnew") (generator_version "8.0")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
  (gr_rect (start 0 0) (end 20 20) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))
)
"""


def setup_module():
    global TMP
    base = LC.ROOT / ".runtime" / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    TMP = Path(tempfile.mkdtemp(prefix="test_drc_cov_", dir=str(base)))


def teardown_module():
    if TMP is not None:
        shutil.rmtree(TMP, ignore_errors=True)


def tmp():
    if TMP is None:
        setup_module()
    return TMP


def board(name="b.kicad_pcb", age_s=60.0):
    """a board file whose mtime is age_s seconds in the past"""
    p = tmp() / name
    p.write_text(MINI_PCB, encoding="utf-8")
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def report(pcb, **over):
    """a clean report dict for `pcb`, dated now"""
    data = {"$schema": G.SCHEMA, "coordinate_units": "mm", "date": datetime.now().isoformat(timespec="seconds"),
            "ignored_checks": [{"key": "missing_courtyard", "description": "x"},
                               {"key": "track_not_centered_on_via", "description": "x"}],
            "included_severities": ["error", "warning", "exclusion"], "kicad_version": "10.0.6",
            "schematic_parity": [], "source": Path(pcb).name, "unconnected_items": [], "violations": []}
    for k, v in over.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    return data


def write(data, name="r.json"):
    p = tmp() / name
    p.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return p


def run(data, pcb):
    return G.check(write(data), pcb)


def only(res, cls):
    fired = [c for c, v in res["fails"].items() if v]
    assert fired == [cls], (cls, res["fails"])


def test_clean_report_passes():
    pcb = board()
    res = run(report(pcb), pcb)
    assert res["status"] == "PASS", res["fails"]
    assert G.require(write(report(pcb)), pcb)["status"] == "PASS"
    G.require_physical_checks(report(pcb))                   # parent API: no exception


def test_inventory_missing_or_malformed_fails():
    pcb = board()
    for over in ({"ignored_checks": None}, {"ignored_checks": "none"}, {"ignored_checks": [{"description": "no key"}]},
                 {"included_severities": None}, {"violations": None}):
        res = run(report(pcb, **over), pcb)
        only(res, "DRC-INVENTORY")
    try:
        G.require_physical_checks(report(pcb, ignored_checks=None))
        raise AssertionError("parent API accepted a missing inventory")
    except ValueError:
        pass


def test_every_required_check_disabled_fails():
    pcb = board()
    for key in sorted(G.REQUIRED_CHECKS):
        res = run(report(pcb, ignored_checks=[{"key": key, "description": "x"}]), pcb)
        only(res, "DRC-CHECK-DISABLED")
        assert key in res["fails"]["DRC-CHECK-DISABLED"][0]
        try:
            G.require_physical_checks(report(pcb, ignored_checks=[{"key": key}]))
            raise AssertionError(f"parent API accepted {key} disabled")
        except ValueError:
            pass
    try:
        G.require(write(report(pcb, ignored_checks=[{"key": "clearance"}])), pcb)
        raise AssertionError("require() passed a disabled clearance check")
    except RuntimeError:
        pass


def test_non_required_ignored_check_passes():
    pcb = board()
    res = run(report(pcb, ignored_checks=[{"key": "footprint_filters_mismatch"}, {"key": "missing_courtyard"}]), pcb)
    assert res["status"] == "PASS", res["fails"]


def test_severities_filtered_fails():
    pcb = board()
    only(run(report(pcb, included_severities=["error"]), pcb), "DRC-SEVERITIES")
    only(run(report(pcb, included_severities=["error", "warning"]), pcb), "DRC-SEVERITIES")


def test_wrong_board_fails():
    pcb = board()
    only(run(report(pcb, source="other-board.kicad_pcb"), pcb), "DRC-WRONG-BOARD")
    only(run(report(pcb, source=None), pcb), "DRC-WRONG-BOARD")
    res = run(report(pcb, source="C:\\elsewhere\\" + pcb.name), pcb)     # a path in source: the name decides
    assert res["status"] == "PASS", res["fails"]


def test_stale_report_fails():
    pcb = board(age_s=0)                                                  # board written NOW
    old = datetime.fromtimestamp(time.time() - 120).isoformat(timespec="seconds")
    res = run(report(pcb, date=old), pcb)
    only(res, "DRC-STALE")
    only(run(report(pcb, date=None), pcb), "DRC-STALE")
    only(run(report(pcb, date="yesterday"), pcb), "DRC-STALE")
    # KiCad truncates its date to the second: a report written in the same second as the board passes
    t = pcb.stat().st_mtime
    same = datetime.fromtimestamp(int(t)).isoformat(timespec="seconds")
    assert run(report(pcb, date=same), pcb)["status"] == "PASS"
    try:
        G.require_identity(report(pcb, date=old), pcb)
        raise AssertionError("require_identity accepted a stale report")
    except ValueError as e:
        assert "DRC-STALE" in str(e)


def test_excluded_required_violation_fails():
    pcb = board()
    v = {"type": "clearance", "severity": "exclusion", "description": "Clearance violation",
         "items": [{"description": "Track [GND]"}, {"description": "Pad 1 [VPP]"}]}
    only(run(report(pcb, violations=[v]), pcb), "DRC-EXCLUDED")
    v2 = dict(v, type="silk_overlap")                                     # not a required physical check
    assert run(report(pcb, violations=[v2]), pcb)["status"] == "PASS"
    v3 = dict(v, severity="error")                                        # a live violation is qa_drc's job
    assert run(report(pcb, violations=[v3]), pcb)["status"] == "PASS"


def test_tool_errors_exit_2():
    pcb = board()
    for bad in (tmp() / "missing.json", write("{not json", "bad.json"), write(report(pcb, **{"$schema": "x"}), "s.json")):
        try:
            G.check(bad, pcb)
            raise AssertionError(f"accepted {bad}")
        except G.ToolError:
            pass
        assert G.main([str(bad), "--board", str(pcb)]) == 2
    assert G.main([str(write(report(pcb))), "--board", str(tmp() / "no-board.kicad_pcb")]) == 2


def test_cli_exit_codes():
    pcb = board()
    out = tmp() / "cov.json"
    assert G.main([str(write(report(pcb))), "--board", str(pcb), "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "PASS"
    assert G.main([str(write(report(pcb, source="x.kicad_pcb"))), "--board", str(pcb)]) == 1


def test_required_checks_are_kicad10_keys():
    assert G.REQUIRED_CHECKS <= G.KICAD10_CHECK_KEYS, sorted(G.REQUIRED_CHECKS - G.KICAD10_CHECK_KEYS)
    assert "via_diameter" not in G.REQUIRED_CHECKS
    # every parent key except via_diameter is kept
    parent = {'annular_width', 'clearance', 'copper_edge_clearance', 'courtyards_overlap', 'creepage',
              'hole_clearance', 'hole_to_hole', 'isolated_copper', 'shorting_items', 'starved_thermal',
              'track_dangling', 'track_width', 'tracks_crossing', 'unconnected_items', 'via_dangling',
              'drill_out_of_range', 'solder_mask_bridge'}
    assert parent <= G.REQUIRED_CHECKS
    assert "items_not_allowed" in G.REQUIRED_CHECKS         # the PRI / SEC barrier rule area


def _kicad(pcb, out, *flags, pro=None):
    from local_run import environment
    if pro is not None:
        pcb.with_suffix(".kicad_pro").write_text(json.dumps(pro), encoding="utf-8")
    r = subprocess.run([KCLI, "pcb", "drc", *flags, "--format", "json", "-o", str(out), str(pcb)],
                       capture_output=True, text=True, timeout=300, env=environment())
    assert out.exists(), r.stdout + r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_kicad10_key_inventory():
    """live kicad-cli: every candidate key set to 'ignore' -> ignored_checks lists exactly the KiCad 10 key set; keys
    KiCad does not know (via_diameter, a bogus key) are not listed"""
    pcb = board("keys.kicad_pcb")
    cands = set(G.KICAD10_CHECK_KEYS) | {"via_diameter", "hole_size", "bogus_key_xyz"}
    data = _kicad(pcb, tmp() / "keys-drc.json", "--severity-all",
                  pro={"board": {"design_settings": {"rule_severities": {k: "ignore" for k in sorted(cands)}}}})
    keys = {r["key"] for r in data["ignored_checks"]}
    assert keys == set(G.KICAD10_CHECK_KEYS), (sorted(keys - G.KICAD10_CHECK_KEYS),
                                                sorted(G.KICAD10_CHECK_KEYS - keys))
    res = G.check(tmp() / "keys-drc.json", pcb)                       # all disabled -> FAIL
    assert len(res["fails"]["DRC-CHECK-DISABLED"]) == len(G.REQUIRED_CHECKS), res["fails"]


def test_real_reports_all_vs_error_severity():
    pcb = board("real.kicad_pcb")
    pcb.with_suffix(".kicad_pro").unlink(missing_ok=True)
    rep_all = tmp() / "real-all.json"
    _kicad(pcb, rep_all, "--severity-all")
    res = G.check(rep_all, pcb)
    assert res["status"] == "PASS", res["fails"]
    rep_err = tmp() / "real-err.json"
    _kicad(pcb, rep_err, "--severity-error")
    only(G.check(rep_err, pcb), "DRC-SEVERITIES")
    # the board changes after the DRC: stale
    time.sleep(1.2)
    pcb.write_text(MINI_PCB.replace("(end 20 20)", "(end 21 20)"), encoding="utf-8")
    only(G.check(rep_all, pcb), "DRC-STALE")


if __name__ == "__main__":
    setup_module()
    bad = 0
    try:
        for n, f in list(globals().items()):
            if n.startswith("test_") and callable(f):
                try:
                    f()
                    print("PASS", n)
                except Exception as e:                              # noqa: BLE001
                    bad += 1
                    print("FAIL", n, repr(e))
    finally:
        teardown_module()
    sys.exit(1 if bad else 0)
