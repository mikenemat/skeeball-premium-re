# ported from din8r-chassis-thermal/scripts/kicad_test_runner.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
"""Run one test module's test_* functions under KiCad 10's Python (pcbnew) and report each result.

    py scripts/local_run.py kicad_test_runner.py scripts/test_qa_copper_landing.py [--json OUT] [-k SUBSTR]

The board QA gate tests build synthetic boards with pcbnew, which only KiCad's bundled Python has (no pytest there).
scripts/conftest.py (the CPython pytest bridge) runs each such module ONCE through this runner and turns every
test_* function into its own pytest item. Standalone it prints one line per test. Exit 0 = all passed, 1 = a test
failed, 2 = the module did not import (fail closed).
Test functions take no arguments; a module may define setup_module() / teardown_module().
"""
import argparse
import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_const  # noqa: E402,F401  (tools/pylib for shapely)


def run(path, select=None):
    path = Path(path)
    if not path.is_absolute() and not path.exists():      # local_run runs us with cwd = scripts/
        path = HERE.parent / path
    path = path.resolve()
    sys.path.insert(0, str(path.parent))
    out = {"module": str(path), "tests": {}, "import_error": None}
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = mod
        spec.loader.exec_module(mod)
    except BaseException:                                   # noqa: BLE001 - reported, fail closed
        out["import_error"] = traceback.format_exc()
        return out
    names = [n for n, f in vars(mod).items() if n.startswith("test_") and callable(f)]
    names.sort(key=lambda n: getattr(getattr(mod, n), "__code__", None).co_firstlineno
               if hasattr(getattr(mod, n), "__code__") else 0)
    if select:
        names = [n for n in names if select in n]
    if hasattr(mod, "setup_module"):
        mod.setup_module()
    try:
        for n in names:
            t0 = time.time()
            try:
                getattr(mod, n)()
                out["tests"][n] = {"ok": True, "s": round(time.time() - t0, 2)}
            except BaseException:                           # noqa: BLE001
                out["tests"][n] = {"ok": False, "s": round(time.time() - t0, 2), "trace": traceback.format_exc()}
    finally:
        if hasattr(mod, "teardown_module"):
            mod.teardown_module()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("module")
    ap.add_argument("--json")
    ap.add_argument("-k")
    a = ap.parse_args(argv)
    res = run(a.module, a.k)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    if res["import_error"]:
        print(res["import_error"])
        print(f"IMPORT ERROR {a.module}")
        return 2
    bad = [n for n, r in res["tests"].items() if not r["ok"]]
    for n, r in res["tests"].items():
        print(f"{'PASS' if r['ok'] else 'FAIL'} {n} ({r['s']} s)")
        if not r["ok"]:
            print(r["trace"])
    print(f"{len(res['tests']) - len(bad)} passed, {len(bad)} failed ({Path(a.module).name})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
