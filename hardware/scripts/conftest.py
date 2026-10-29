# ported from din8r-chassis-thermal/scripts/conftest.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
"""CPython pytest bridge for the board QA gate tests (py -m pytest scripts/test_qa_*.py).

A test module that needs KiCad's pcbnew declares `KICAD_PYTHON = True` at module level. Under CPython (no pcbnew) such
a module is not imported: its test_* function names are read from the source (AST), the whole module runs ONCE under
KiCad 10's Python (scripts/local_run.py -> scripts/kicad_test_runner.py, JSON results), and every test function is
reported as its own pytest item (pass / fail with the KiCad-side traceback). Modules without the flag run natively.
A module that fails to import under KiCad fails every one of its items (fail closed); a test the runner did not report
fails too.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
KICAD_TIMEOUT_S = 7200


def _have_pcbnew():
    try:
        import pcbnew  # noqa: F401
        return True
    except ImportError:
        return False


def _scan(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    kicad, names = False, []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "KICAD_PYTHON"
                                                for t in node.targets):
            kicad = bool(getattr(node.value, "value", False))
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            names.append(node.name)
    return kicad, names


class KicadFailure(Exception):
    pass


class KicadModule(pytest.File):
    def collect(self):
        _, names = _scan(self.path)
        for n in names:
            yield KicadItem.from_parent(self, name=n)

    def results(self):
        if getattr(self, "_results", None) is None:
            tmp = ROOT / ".runtime" / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            fd, out = tempfile.mkstemp(prefix="kicad_tests_", suffix=".json", dir=str(tmp))
            os.close(fd)
            Path(out).unlink(missing_ok=True)
            cmd = [sys.executable, str(HERE / "local_run.py"), str(HERE / "kicad_test_runner.py"), str(self.path),
                   "--json", out]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=KICAD_TIMEOUT_S, cwd=str(ROOT))
                log = (r.stdout or "")[-20000:] + (r.stderr or "")[-5000:]
            except subprocess.TimeoutExpired as e:
                log = f"KiCad test run timed out after {KICAD_TIMEOUT_S} s: {e}"
            try:
                self._results = json.loads(Path(out).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._results = {"import_error": "no result file from the KiCad runner\n" + log, "tests": {}}
            finally:
                Path(out).unlink(missing_ok=True)
            self._log = log
        return self._results


class KicadItem(pytest.Item):
    def runtest(self):
        res = self.parent.results()
        if res.get("import_error"):
            raise KicadFailure("module failed under KiCad's Python:\n" + res["import_error"])
        r = res["tests"].get(self.name)
        if r is None:
            raise KicadFailure("not reported by the KiCad runner\n" + getattr(self.parent, "_log", ""))
        if not r["ok"]:
            raise KicadFailure(r["trace"])

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, KicadFailure):
            return str(excinfo.value)
        return super().repr_failure(excinfo)

    def reportinfo(self):
        return self.path, None, f"{self.path.name}::{self.name} [KiCad Python]"


def pytest_pycollect_makemodule(module_path, parent):
    if Path(module_path).parent.resolve() != HERE or _have_pcbnew():
        return None
    kicad, _ = _scan(module_path)
    if kicad:
        return KicadModule.from_parent(parent, path=Path(module_path))
    return None
