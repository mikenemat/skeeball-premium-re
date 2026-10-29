# ported from din8r-chassis-thermal/scripts/layout_gates.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
"""Board layout QA gates for SBC-1 (ported from CT), one runner (CPython): every gate ported from DIN-8R, on any board file.

    py scripts/layout_gates.py [BOARD] [--only g1,g2] [--out DIR] [--drc-report PATH] [--reuse]

Gates (each its own subprocess, JSON report in OUT/<gate>.json; KiCad Python ones through scripts/local_run.py):
  drc_coverage    drc_check_coverage.py  the DRC report the gates rely on covers every physical check, names this
                                         board, is not older than it, ran with all severities
  copper_landing  qa_copper_landing.py   NO UNCONNECTED PAD OR LOOSE TRACE (PAD-OPEN / PAD-LAND / POUR-PAD / TRACK-END /
                                         VIA-LAND / LOOP / PLANE-ISLAND) + clean checks (TRACK-DUP, VIA-PADEDGE / -PARTIAL /
                                         -BARE, TRACK-ORPHAN, TRACK-JOG, PAD-CENTRE, TRACK-WIDTH)
  layout_quality  qa_layout_quality.py   via-in-pad / pad gap, F-B stacks, folds / acute angles, threads, power-pad and
                                         via current, stitching, decap loops, series terms, crystals, diff pairs, plane
                                         slots, fiducials, pad axis, via hops, placement (pin passives / IC orientation)
  placement       qa_placement.py        via sites, diff-pair passives, fiducial spread, EP via pattern, TVS ground,
                                         stacked ICs (UNDERSAT warn)
  decoupling      qa_decoupling.py       bypass caps per IC power pin (the ECO's qa_power_layout DECAP table is the one
                                         distance rule for the pins it lists)
  silk            qa_silk.py             pin-1 / polarity marks first, silk over pads / overlaps / edge / size / refs
  footprints      qa_footprints_board.py footprints exist, cover the symbol pins, board FPIDs = design.py
SBC-1 port: CT's twoside (no bottom-side parts: SMD top only, owner 2026-10-26; no project enclosure), isolation / crosslayer (PoE PRI-SEC barrier) and si (CT's W5500 / GX112S SI models) are not ported
(SBC-1 is SELV only; its SI gate would need SBC-1's own net models - open item).
Exit 0 = every selected gate PASS, 1 = any FAIL, 2 = a tool error / timeout / cannot-evaluate and no FAIL (fail closed).
DRC report: --drc-report, else for the adopted board .runtime/drc.json (scripts/qa_drc.py writes it), else (any other
board) a fresh `kicad-cli pcb drc --severity-all` of that board into OUT (its .kicad_pro must sit next to it).
--reuse: return the stored summary when the board, its project, the DRC report, the gate code (scripts/*.py), the
power budget and the board mechanics are byte-identical to the last run (fab_outputs.py uses it after run_gates.py).
--evidence DIR [--label L]: also write DIR/L.json (every finding, bulky fields dropped) and DIR/L-findings.md (per gate
and class, one line per finding with its coordinates) for a record (docs/records/layout_gates/).
run(board, ...) is the python entry point (returns the summary dict).
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import board_const as K  # noqa: E402

KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
GATE_TIMEOUT_S = 3600                       # per gate; a timeout never passes
# name -> (runner, argv template[, report path template when the gate does not take --json]). {board} {json} {drc}
# {dir} are substituted.
GATES = {
    "drc_coverage": ("py", ["drc_check_coverage.py", "{drc}", "--board", "{board}", "--json", "{json}"]),
    "copper_landing": ("kicad", ["qa_copper_landing.py", "{board}", "--json", "{json}"]),
    "layout_quality": ("kicad", ["qa_layout_quality.py", "{board}", "--json", "{json}"]),
    "placement": ("kicad", ["qa_placement.py", "{board}", "--json", "{json}"]),
    "decoupling": ("kicad", ["qa_decoupling.py", "{board}", "--json", "{json}"]),
    "silk": ("kicad", ["qa_silk.py", "{board}", "--json", "{json}", "--drc-report", "{drc}"]),
    "footprints": ("kicad", ["qa_footprints_board.py", "--board", "{board}", "--json", "{json}"]),
}
STATUS = {0: "PASS", 1: "FAIL"}


def sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def drc_sha(p):
    """the DRC report's content without its run date (qa_drc.py rewrites it on every run)"""
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    d.pop("date", None)
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def code_sha():
    h = hashlib.sha256()
    for p in sorted(HERE.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    for p in (K.BOARD_MECHANICS,):                    # SBC-1: no power_budget.json / mechanics file (None)
        h.update(p.read_bytes() if p and Path(p).is_file() else b"-")
    return h.hexdigest()


def drc_report_for(board, out_dir, given=None):
    """the DRC report the gates use (see the module doc)"""
    if given:
        return Path(given).resolve()
    if Path(board).resolve() == K.MAIN_PCB.resolve():
        return K.DRC_JSON
    if not Path(board).with_suffix(".kicad_pro").is_file():
        raise SystemExit(f"{board}: no .kicad_pro next to it - its DRC would use KiCad's default rules")
    from local_run import environment
    rep = Path(out_dir) / "drc.json"
    subprocess.run([KCLI, "pcb", "drc", "--severity-all", "--format", "json", "-o", str(rep), str(board)],
                   capture_output=True, env=environment(), timeout=GATE_TIMEOUT_S)
    if not rep.is_file():
        raise SystemExit(f"kicad-cli DRC produced no report for {board}")
    return rep


def gate_counts(path):
    """the failing-class counts a gate JSON reports (copper_landing / layout_quality style 'counts', else a guess)"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(d, dict) and isinstance(d.get("counts"), dict):
        return {k: v for k, v in d["counts"].items() if v}
    return {k: len(v) for k, v in (d.get("fails") or {}).items() if v} if isinstance(d, dict) and \
        isinstance(d.get("fails"), dict) else None


def run_gate(name, board, out_dir, drc):
    runner, tmpl, *rep = GATES[name]
    js = Path(rep[0].format(dir=str(out_dir))) if rep else Path(out_dir) / f"{name}.json"
    js.unlink(missing_ok=True)
    args = [a.format(board=str(board), json=str(js), drc=str(drc), dir=str(out_dir)) for a in tmpl]
    script = HERE / args[0]
    if runner == "kicad":
        cmd = [sys.executable, str(HERE / "local_run.py"), str(script), *args[1:]]
    else:
        cmd = [sys.executable, str(script), *args[1:]]
    t0 = time.time()
    if not script.is_file():
        return {"status": "ERROR", "rc": None, "s": 0.0, "detail": f"{script.name} missing", "json": None}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=GATE_TIMEOUT_S, cwd=str(ROOT))
        rc, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = None, f"timeout after {GATE_TIMEOUT_S} s"
    (Path(out_dir) / f"{name}.log").write_text(out[-400000:], encoding="utf-8")
    lines = [x for x in out.strip().splitlines() if x.strip() and "duplicate image handler" not in x]
    status = STATUS.get(rc, "ERROR")
    if status == "FAIL" and not js.is_file():          # a crash (Python exits 1 too) left no report: a tool error
        status = "ERROR"
    return {"status": status, "rc": rc, "s": round(time.time() - t0, 1),
            "json": str(js) if js.is_file() else None, "counts": gate_counts(js) if js.is_file() else None,
            "tail": [x[:300] for x in lines[-3:]]}


def run(board=None, out_dir=None, only=None, drc_report=None, reuse=False, echo=True):
    board = Path(board or K.MAIN_PCB).resolve()
    out_dir = (Path(out_dir) if out_dir else K.GATE_OUT / board.stem).resolve()   # absolute: KiCad gates run in scripts/
    out_dir.mkdir(parents=True, exist_ok=True)
    names = list(GATES) if not only else [n for n in GATES if n in set(only)]
    unknown = set(only or ()) - set(GATES)
    if unknown:
        raise SystemExit(f"unknown gates: {sorted(unknown)}")
    drc = drc_report_for(board, out_dir, drc_report)
    key = {"board_sha256": sha(board), "pro_sha256": sha(board.with_suffix(".kicad_pro")), "drc_sha256": drc_sha(drc),
           "code_sha256": code_sha()}
    summ_path = out_dir / "layout-gates.json"
    if reuse and summ_path.is_file():
        old = json.loads(summ_path.read_text(encoding="utf-8"))
        if all(old.get(k) == v for k, v in key.items()) and all(n in old.get("gates", {}) for n in names):
            old["reused"] = True
            old["gates"] = {n: old["gates"][n] for n in names}
            if echo:
                for n in names:
                    g = old["gates"][n]
                    print(f"[{g['status']}] {n} (reused) {json.dumps(g.get('counts'))[:150]}", flush=True)
            return finish(old, echo)
    res = {"board": str(board), **key, "drc_report": str(drc), "gates": {}}
    prev = json.loads(summ_path.read_text(encoding="utf-8")) if summ_path.is_file() else {}
    if prev.get("board_sha256") == key["board_sha256"] and prev.get("code_sha256") == key["code_sha256"]:
        res["gates"] = {n: g for n, g in prev.get("gates", {}).items() if n not in names}   # keep the others' rows
    for n in names:
        g = run_gate(n, board, out_dir, drc)
        res["gates"][n] = g
        if echo:
            print(f"[{g['status']}] {n} ({g['s']} s) {json.dumps(g.get('counts'))[:150] if g.get('counts') else ''}"
                  f"{'' if g['status'] != 'ERROR' else ' ' + ' | '.join(g.get('tail') or [g.get('detail', '')])[:200]}",
                  flush=True)
        summ_path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    res["selected"] = names
    summ_path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return finish({**res, "gates": {n: res["gates"][n] for n in names}}, echo)


def finish(res, echo):
    st = [g["status"] for g in res["gates"].values()]
    res["status"] = "FAIL" if "FAIL" in st else ("ERROR" if any(s != "PASS" for s in st) or not st else "PASS")
    if echo:
        bad = [n for n, g in res["gates"].items() if g["status"] != "PASS"]
        print(f"layout gates {res['status']}: {len(st) - len(bad)}/{len(st)} PASS"
              + (f"; not passing: {', '.join(bad)}" if bad else ""), flush=True)
    return res


def require(board=None, out_dir=None, reuse=True):
    """python callers (fab_outputs): raises unless every gate PASSes"""
    res = run(board, out_dir, reuse=reuse, echo=False)
    if res["status"] != "PASS":
        raise RuntimeError(f"layout gates {res['status']}: " + ", ".join(
            f"{n} {g['status']}" for n, g in res["gates"].items() if g["status"] != "PASS"))
    return res


# ------------------------------------------------------------------------------------------------ records
FIELD_ORDER = ("part", "parts", "pair", "pad", "pads", "pin", "net", "pad_net", "nets", "layer", "layers", "at", "side",
               "what", "reason", "problems", "kind", "class", "len_mm", "loose_mm", "tracks", "width", "required",
               "gap_mm", "angle", "area_mm2", "need", "vias", "cycle_mm", "free_ends", "end_detail", "board",
               "design", "footprint", "value", "move", "required_mm", "spokes_mm", "path_mm", "gnd_via_mm")
DROP = {"uuids", "candidates", "sites", "layout_quality_tried", "propose", "by_rotation", "satellites", "foreign_neck"}


def compact(item, limit=420):
    """one finding as a short line: the identifying / locating fields first"""
    if not isinstance(item, dict):
        return json.dumps(item, default=str)[:limit]
    keys = [k for k in FIELD_ORDER if k in item] + sorted(k for k in item if k not in FIELD_ORDER and k not in DROP)
    parts = []
    for k in keys:
        v = item[k]
        if k == "end_detail" and isinstance(v, list):
            v = "; ".join(f"{x.get('at')} {x.get('class')}" for x in v[:3])
        elif isinstance(v, float):
            v = round(v, 3)
        parts.append(f"{k}={json.dumps(v, default=str) if not isinstance(v, str) else v}")
    return ", ".join(parts)[:limit]


def evidence(res, label, out_dir, per_class=None):
    """compact findings of one run for a record: <out_dir>/<label>.json (every finding, bulky fields dropped) and
    <out_dir>/<label>-findings.md (per gate / class: count and each finding's line; per_class caps the lines)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = {"label": label, "board": res["board"], "board_sha256": res["board_sha256"], "code_sha256": res["code_sha256"],
           "status": res["status"], "gates": {}}
    md = [f"# Layout gate findings - {label}", "",
          f"Board `{Path(res['board']).name}` sha256 {res['board_sha256'][:12]}; gate code {res['code_sha256'][:12]}; "
          f"overall **{res['status']}**. Generated by `py scripts/layout_gates.py ... --evidence` (coordinates in board "
          f"mm, KiCad frame).", ""]
    for name, g in res["gates"].items():
        entry = {"status": g["status"], "counts": g.get("counts"), "findings": {}, "warnings": {}}
        md.append(f"## {name}: {g['status']}" + (f" ({', '.join(f'{k} {v}' for k, v in g['counts'].items())})"
                                                  if g.get("counts") else ""))
        d = {}
        if g.get("json"):
            try:
                d = json.loads(Path(g["json"]).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                d = {}
        if g["status"] == "ERROR" or not isinstance(d, dict):
            md += ["", "    " + " | ".join(g.get("tail") or [g.get("detail", "")]), ""]
        if isinstance(d, dict) and isinstance(d.get("gates"), dict):       # si_gates: per-gate reports with checks
            for sub, sg in d["gates"].items():
                md.append(f"- **{sub}**: {sg.get('status')} {json.dumps(sg.get('summary'))}")
                try:
                    rep = json.loads((ROOT / sg["report"]).read_text(encoding="utf-8")) if sg.get("report") else {}
                except (OSError, ValueError):
                    rep = {}
                for c in rep.get("checks", []) if isinstance(rep, dict) else []:
                    if c.get("status") in ("FAIL", "UNKNOWN"):
                        cls = f"{sub.replace('.py', '')} {c['status']}"
                        row = {k: c.get(k) for k in ("id", "at", "worst", "reason", "value", "limit") if c.get(k)}
                        entry["findings"].setdefault(cls, []).append(row)
                        md.append(f"  - {c['status']} {compact(row)}")
        for key, store in (("fails", "findings"), ("warns", "warnings"), ("warn", "warnings")):
            src = d.get(key) if isinstance(d, dict) else None
            if not isinstance(src, dict):
                continue
            for cls, items in src.items():
                if not items:
                    continue
                items = items if isinstance(items, list) else [items]
                entry[store][cls] = [{k: v for k, v in x.items() if k not in DROP} if isinstance(x, dict) else x
                                     for x in items]
                shown = items if per_class is None else items[:per_class]
                md.append(f"- **{cls}** ({len(items)}{', warning' if store == 'warnings' else ''})")
                md += [f"  - {compact(x)}" for x in shown]
                if len(shown) < len(items):
                    md.append(f"  - ... {len(items) - len(shown)} more in {label}.json")
        md.append("")
        rec["gates"][name] = entry
    (out_dir / f"{label}.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
    (out_dir / f"{label}-findings.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", nargs="?")
    ap.add_argument("--only")
    ap.add_argument("--out")
    ap.add_argument("--drc-report")
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--evidence", metavar="DIR", help="also write compact findings for a record into DIR")
    ap.add_argument("--label", help="record label (default: the board file stem)")
    a = ap.parse_args(argv)
    only = [x.strip() for x in a.only.split(",") if x.strip()] if a.only else None
    res = run(a.board, a.out, only, a.drc_report, a.reuse)
    if a.evidence:
        evidence(res, a.label or Path(res["board"]).stem, a.evidence)
    return {"PASS": 0, "FAIL": 1}.get(res["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
