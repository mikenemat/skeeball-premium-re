"""Stage a scratch routing candidate (new in SBC-1, 2026-10-26; the role of CT's DIN8R_CT_PCB_OUT scratch boards).

    python scripts/route_stage.py RUN [--from BOARD]

Copies hardware/main (board, .kicad_pro, schematic sheets, lib tables) into .runtime/route/RUN/main/ and junctions
.runtime/route/RUN/lib -> hardware/lib, so ${KIPRJMOD}/../lib resolves (footprint library, 3D models) and kicad-cli DRC
with --schematic-parity works on the copy. Then runs scripts/route_prep.py on the copy (KiCad Python: paused parts
removed (none since 2026-10-27), EDGE_KEEPOUT / NPTH rule areas, pcb_rules), after the lead's scripts/power_copper.py (LOCKED
heavy-current copper) when it exists. hardware/main is never written.
Prints the candidate board path.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "hardware" / "main"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--from", dest="src", default=None, help="board to start from (default hardware/main)")
    ap.add_argument("--no-power-copper", action="store_true", help="skip scripts/power_copper.py")
    a = ap.parse_args()
    run = ROOT / ".runtime" / "route" / a.run
    dst = run / "main"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for f in SRC.iterdir():
        if f.suffix in (".kicad_pcb", ".kicad_pro", ".kicad_sch") or f.name in ("fp-lib-table", "sym-lib-table"):
            shutil.copy2(f, dst / f.name)
    if a.src:
        shutil.copy2(a.src, dst / "skeeball-controller.kicad_pcb")
        pro = Path(a.src).with_suffix(".kicad_pro")
        if pro.exists():
            shutil.copy2(pro, dst / pro.name)
    lib = run / "lib"
    if not lib.exists():
        subprocess.check_call(["cmd", "/c", "mklink", "/J", str(lib), str(ROOT / "hardware" / "lib")],
                              stdout=subprocess.DEVNULL)
    board = dst / "skeeball-controller.kicad_pcb"
    nfp = board.read_text(encoding="utf-8").count("\n\t(footprint ")
    if nfp < 100:                                    # hardware/main mid-rebuild (pcb_build ran, place.py not yet)
        raise SystemExit(f"{board}: only {nfp} footprints - not a placed board; re-run after place.py")
    pc = HERE / "power_copper.py"                    # the lead's LOCKED heavy-current copper, after place.py
    if pc.exists() and not a.no_power_copper:
        rc = subprocess.call([sys.executable, str(HERE / "local_run.py"), str(pc), str(board)])
        if rc:
            raise SystemExit(f"power_copper.py failed ({rc})")
    rc = subprocess.call([sys.executable, str(HERE / "local_run.py"), "route_prep.py", str(board)])
    if rc:
        raise SystemExit(rc)
    print(board)


if __name__ == "__main__":
    main()
