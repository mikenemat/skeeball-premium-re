# ported from din8r-chassis-thermal/scripts/drc_check_coverage.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/drc_check_coverage.py (C:/work/din-relay-8ch), adapted for CT (KiCad 10 keys, identity checks)
"""DRC coverage gate: reject a KiCad DRC report that cannot prove the board is clean. CPython or KiCad Python.

    python scripts/drc_check_coverage.py [REPORT] [--board BOARD] [--json OUT]
        REPORT defaults to board_const.DRC_JSON (.runtime/drc.json, written by scripts/qa_drc.py), BOARD to MAIN_PCB.

Parent lesson (DIN-8R fab_outputs gate): a diagnostic DRC run that had a physical check set to 'ignore' reports 0
violations of that kind and looks clean. A KiCad DRC report is only evidence when ALL of these hold (exit 1 = FAIL):
  DRC-INVENTORY       the report carries its ignored-check inventory (`ignored_checks`, a list of {key, ...}) and the
                      included-severity list; missing / malformed = FAIL (cannot prove what was checked)
  DRC-CHECK-DISABLED  no REQUIRED_CHECKS key is in ignored_checks (a disabled physical check proves nothing)
  DRC-SEVERITIES      the run included every severity (REQUIRED_SEVERITIES: kicad-cli --severity-all); a report
                      filtered to errors hides every warning-level physical finding (CT runs track_dangling,
                      via_dangling, isolated_copper, hole_to_hole at 'warning')
  DRC-WRONG-BOARD     the report's `source` names another board file
  DRC-STALE           the report is older than the board file (its `date` before the board's mtime, DRC_DATE_SLACK_S
                      for KiCad's 1 s date resolution): the board changed after the DRC
  DRC-EXCLUDED        a violation of a REQUIRED_CHECKS type carried with severity 'exclusion' (a KiCad per-item
                      exclusion stored in the project file is an undocumented waiver of that check for that item;
                      CT allows no waivers except named, documented constants)
Exit 2 = tool error (report / board missing, not JSON, not a KiCad DRC report). Fail closed either way.

REQUIRED_CHECKS: the parent's set minus `via_diameter` (KiCad 10 has no such check key: a kicad-cli run that sets
every candidate key to 'ignore' lists 62 keys and not via_diameter, see KICAD10_CHECK_KEYS and
test_drc_check_coverage.test_kicad10_key_inventory), plus the KiCad 10 physical checks CT relies on:
  items_not_allowed   the PRI / SEC barrier (ISOLATION_BARRIER_PRI_SEC) and EDGE_KEEPOUT are KiCad rule areas; their
                      track / via / fill violations are reported only under this key
  invalid_outline     a broken Edge.Cuts outline voids every edge-clearance result
  zones_intersect     overlapping zones of different nets on one layer
  holes_co_located, through_hole_pad_without_hole   drill-file faults
Python API for scripts/run_gates.py: check(report, board) -> result dict; require(report, board) raises on FAIL;
require_physical_checks(data) (the parent's API) raises ValueError on a disabled / missing inventory.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as LC  # noqa: E402

SCHEMA = "https://schemas.kicad.org/drc.v1.json"
REQUIRED_CHECKS = frozenset({
    # the parent's set (DIN-8R drc_check_coverage.py) without via_diameter (not a KiCad 10 key)
    'annular_width', 'clearance', 'copper_edge_clearance', 'courtyards_overlap',
    'creepage', 'hole_clearance', 'hole_to_hole', 'isolated_copper',
    'shorting_items', 'starved_thermal', 'track_dangling', 'track_width',
    'tracks_crossing', 'unconnected_items', 'via_dangling',
    'drill_out_of_range', 'solder_mask_bridge',
    # CT additions (module docstring)
    'items_not_allowed', 'invalid_outline', 'zones_intersect', 'holes_co_located', 'through_hole_pad_without_hole',
})
# Every DRC check key KiCad 10.0.6 knows (kicad-cli pcb drc with all of them set to 'ignore', 2026-10-17); the tests
# re-derive it from a live kicad-cli run, so a KiCad upgrade that renames a key fails the test, not silently the gate.
KICAD10_CHECK_KEYS = frozenset({
    'annular_width', 'clearance', 'connection_width', 'copper_edge_clearance', 'copper_sliver', 'courtyards_overlap',
    'creepage', 'diff_pair_gap_out_of_range', 'diff_pair_uncoupled_length_too_long', 'drill_out_of_range',
    'duplicate_footprints', 'extra_footprint', 'footprint', 'footprint_filters_mismatch',
    'footprint_symbol_field_mismatch', 'footprint_symbol_mismatch', 'footprint_type_mismatch', 'hole_clearance',
    'hole_to_hole', 'holes_co_located', 'invalid_outline', 'isolated_copper', 'item_on_disabled_layer',
    'items_not_allowed', 'length_out_of_range', 'lib_footprint_issues', 'lib_footprint_mismatch',
    'malformed_courtyard', 'microvia_drill_out_of_range', 'mirrored_text_on_front_layer', 'missing_courtyard',
    'missing_footprint', 'missing_tuning_profile', 'net_conflict', 'nonmirrored_text_on_back_layer',
    'npth_inside_courtyard', 'padstack', 'pth_inside_courtyard', 'shorting_items', 'silk_edge_clearance',
    'silk_over_copper', 'silk_overlap', 'skew_out_of_range', 'solder_mask_bridge', 'starved_thermal', 'text_height',
    'text_on_edge_cuts', 'text_thickness', 'through_hole_pad_without_hole', 'too_many_vias', 'track_angle',
    'track_dangling', 'track_not_centered_on_via', 'track_on_post_machined_layer', 'track_segment_length',
    'track_width', 'tracks_crossing', 'tuning_profile_track_geometries', 'unconnected_items', 'unresolved_variable',
    'via_dangling', 'zones_intersect',
})
REQUIRED_SEVERITIES = frozenset({"error", "warning", "exclusion"})   # what kicad-cli --severity-all writes (KiCad 10)
DRC_DATE_SLACK_S = 1.0          # KiCad writes the report date with 1 s resolution (truncated); the board mtime is finer
CLASSES = ("DRC-INVENTORY", "DRC-CHECK-DISABLED", "DRC-SEVERITIES", "DRC-WRONG-BOARD", "DRC-STALE", "DRC-EXCLUDED")


def project_path(p, output=False):
    """a CLI path: absolute as given; relative = from the current directory when it exists there, else from the
    project root (local_run.py runs scripts with cwd = scripts/, the lead's command lines are written from the root);
    a relative OUTPUT path is always under the project root"""
    p = Path(p)
    if p.is_absolute():
        return p
    if not output and p.exists():
        return p.resolve()
    return LC.ROOT / p


class ToolError(Exception):
    """report / board missing or not a KiCad DRC report (exit 2)"""


def load(report):
    p = Path(report)
    if not p.is_file():
        raise ToolError(f"DRC report not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ToolError(f"DRC report is not JSON: {p}: {e}") from e
    if not isinstance(data, dict) or data.get("$schema") != SCHEMA:
        raise ToolError(f"not a KiCad DRC report ($schema != {SCHEMA}): {p}")
    return data


def require_physical_checks(data):
    """The parent's API: ValueError on a missing / malformed inventory or a disabled REQUIRED_CHECKS key."""
    ignored = data.get('ignored_checks')
    if not isinstance(ignored, list) or any(
            not isinstance(row, dict) or not isinstance(row.get('key'), str)
            for row in ignored):
        raise ValueError('Missing or malformed DRC ignored-check inventory')
    disabled = REQUIRED_CHECKS.intersection(row['key'] for row in ignored)
    if disabled:
        raise ValueError('Required DRC checks disabled: ' + ', '.join(sorted(disabled)))


def report_date(data):
    """the report's `date` (local time, as KiCad writes it) as an epoch float, or None when missing / unparseable"""
    d = data.get("date")
    if not isinstance(d, str):
        return None
    try:
        return datetime.fromisoformat(d).timestamp()
    except ValueError:
        return None


def identity_problems(data, board):
    """[(class, text)] when the report is not about this board file as it is now: DRC-WRONG-BOARD (`source` names
    another file or is missing), DRC-STALE (no date, or dated before the board's last write)."""
    board = Path(board)
    out = []
    src = data.get("source")
    if not isinstance(src, str) or not src:
        out.append(("DRC-WRONG-BOARD", "report has no 'source' board name"))
    elif Path(src.replace("\\", "/")).name != board.name:
        out.append(("DRC-WRONG-BOARD", f"report is for {Path(src).name}, not {board.name}"))
    t = report_date(data)
    if t is None:
        out.append(("DRC-STALE", f"report has no parseable 'date' ({data.get('date')!r})"))
    else:
        mt = board.stat().st_mtime
        if t + DRC_DATE_SLACK_S < mt:
            out.append(("DRC-STALE", f"report dated {data.get('date')} is older than {board.name} "
                                     f"(modified {datetime.fromtimestamp(mt).isoformat(timespec='seconds')})"))
    return out


def require_identity(data, board):
    """ValueError when the report is for another board or older than it (qa_silk's --drc-report check)"""
    probs = identity_problems(data, board)
    if probs:
        raise ValueError("; ".join(f"{c}: {t}" for c, t in probs))


def check(report=None, board=None):
    """-> {'status': PASS|FAIL, 'report', 'board', 'fails': {class: [text]}, 'info'}; ToolError when unreadable."""
    report = project_path(report or LC.DRC_JSON)
    board = project_path(board or LC.MAIN_PCB)
    if not board.is_file():
        raise ToolError(f"board not found: {board}")
    data = load(report)
    fails = {c: [] for c in CLASSES}
    ignored = data.get("ignored_checks")
    if not isinstance(ignored, list) or any(not isinstance(r, dict) or not isinstance(r.get("key"), str)
                                            for r in ignored):
        fails["DRC-INVENTORY"].append("missing or malformed 'ignored_checks' inventory")
        keys = set()
    else:
        keys = {r["key"] for r in ignored}
        for k in sorted(REQUIRED_CHECKS & keys):
            fails["DRC-CHECK-DISABLED"].append(f"required physical check '{k}' is ignored")
    sev = data.get("included_severities")
    if not isinstance(sev, list) or any(not isinstance(s, str) for s in sev):
        fails["DRC-INVENTORY"].append("missing or malformed 'included_severities'")
    else:
        miss = sorted(REQUIRED_SEVERITIES - set(sev))
        if miss:
            fails["DRC-SEVERITIES"].append(f"report omits severities {miss} (run kicad-cli with --severity-all)")
    for k in ("violations", "unconnected_items"):
        if not isinstance(data.get(k), list):
            fails["DRC-INVENTORY"].append(f"missing or malformed '{k}' section")
            continue
        for v in data[k]:
            if isinstance(v, dict) and v.get("severity") == "exclusion" and v.get("type") in REQUIRED_CHECKS:
                fails["DRC-EXCLUDED"].append(f"{v.get('type')}: {v.get('description', '')} "
                                             f"{[i.get('description', '') for i in v.get('items', [])][:2]}")
    for cls, text in identity_problems(data, board):
        fails[cls].append(text)
    info = {"ignored_checks": sorted(keys), "included_severities": sev, "date": data.get("date"),
            "source": data.get("source"), "kicad_version": data.get("kicad_version"),
            "required_checks": sorted(REQUIRED_CHECKS), "unknown_ignored_keys": sorted(keys - KICAD10_CHECK_KEYS)}
    status = "FAIL" if any(fails.values()) else "PASS"
    return {"status": status, "report": str(report), "board": str(board), "fails": fails, "info": info}


def require(report=None, board=None):
    """run_gates hook: raises RuntimeError on FAIL (ToolError on an unreadable report); returns the result."""
    res = check(report, board)
    if res["status"] != "PASS":
        raise RuntimeError("drc_check_coverage FAILED: " + "; ".join(f"{c}: {t}" for c, ts in res["fails"].items()
                                                                     for t in ts))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", nargs="?", default=str(LC.DRC_JSON))
    ap.add_argument("--board", default=str(LC.MAIN_PCB))
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    t0 = time.time()
    try:
        res = check(a.report, a.board)
    except Exception as e:                                # fail closed
        print(f"drc_check_coverage ERROR: {e}")
        return 2
    if a.json:
        out = project_path(a.json, output=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"drc_check_coverage {res['status']}  {a.report} (board {Path(a.board).name}; "
          f"{round(time.time() - t0, 2)} s)")
    for c in CLASSES:
        n = len(res["fails"][c])
        print(f"  {c:19s} {'FAIL' if n else 'ok':4s} {n}")
        for t in res["fails"][c][:12]:
            print("     ", t)
    print(f"drc_check_coverage {res['status']}: " + (", ".join(f"{c} {len(v)}" for c, v in res["fails"].items() if v)
                                                     or "report covers every required check"))
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
