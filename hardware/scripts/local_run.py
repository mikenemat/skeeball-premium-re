# ported from din8r-chassis-thermal/scripts/local_run.py, 2026-10-26 (project lib name din8r_ct -> skeeball)
"""Run a project script under KiCad's Python, or kicad-cli, with all writable state inside this project's .runtime/.

    python scripts/local_run.py script.py [args]      (KiCad 10 bundled Python: pcbnew available)
    python scripts/local_run.py --cli [kicad-cli args]

Modelled on DIN-8R scripts/local_run.py: a private KiCad profile (KICAD_CONFIG_HOME = .runtime/kicad-config) whose
global sym/fp library tables list the INSTALLED KiCad 10 libraries (read only) plus this project's skeeball libs, so
nothing outside the project is written and the user's KiCad profile is never touched.
"""
import os
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICAD = Path("C:/Program Files/KiCad/10.0")
SHARE = KICAD / "share" / "kicad"
STATE = ROOT / ".runtime"


def environment():
    env = os.environ.copy()
    for name in ("tmp", "kicad-config"):
        (STATE / name).mkdir(parents=True, exist_ok=True)
    conf = STATE / "kicad-config" / "10.0"
    conf.mkdir(parents=True, exist_ok=True)
    lib = ROOT / "hardware" / "lib"
    fps = sorted(p.stem for p in (SHARE / "footprints").glob("*.pretty"))
    syms = sorted(p.stem for p in (SHARE / "symbols").glob("*.kicad_sym"))
    fp_rows = [(n, (SHARE / "footprints" / f"{n}.pretty").as_posix()) for n in fps] + \
              [("skeeball", (lib / "skeeball.pretty").as_posix())]
    sym_rows = [(n, (SHARE / "symbols" / f"{n}.kicad_sym").as_posix()) for n in syms] + \
               [("skeeball", (lib / "skeeball.kicad_sym").as_posix())]
    for file, kind, rows in (("fp-lib-table", "fp_lib_table", fp_rows), ("sym-lib-table", "sym_lib_table", sym_rows)):
        text = f"({kind}\n (version 7)\n" + "".join(
            f' (lib (name "{n}")(type "KiCad")(uri "{u}")(options "")(descr ""))\n' for n, u in rows) + ")\n"
        (conf / file).write_text(text, encoding="utf-8")
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", KICAD_CONFIG_HOME=str(STATE / "kicad-config"),
               KICAD10_FOOTPRINT_DIR=str(SHARE / "footprints"), KICAD10_SYMBOL_DIR=str(SHARE / "symbols"),
               KICAD10_3DMODEL_DIR=str(SHARE / "3dmodels"), TEMP=str(STATE / "tmp"), TMP=str(STATE / "tmp"))
    return env


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    env = environment()
    args = sys.argv[1:]
    if args[0] == "--entry":
        os.environ.update(env)
        script = Path(args[1]).resolve()
        sys.path[:0] = [str(script.parent)]
        sys.argv = [str(script), *args[2:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    if args[0] == "--cli":
        return subprocess.call([str(KICAD / "bin" / "kicad-cli.exe"), *args[1:]], cwd=ROOT, env=env)
    script = Path(args[0])
    if not script.is_absolute():
        script = script.resolve() if script.exists() else Path(__file__).parent / script
    return subprocess.call([str(KICAD / "bin" / "python.exe"), str(Path(__file__).resolve()), "--entry",
                            str(script.resolve()), *args[1:]], cwd=script.parent, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
