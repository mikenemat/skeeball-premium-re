"""QA: compare the netlist KiCad exports from the generated schematic with the design database.

Catches label placement bugs, pin-number mismatches between symbols and the DSL, and missing parts.
usage: python qa_netlist.py <design_module> <schematic.kicad_sch>
"""
import importlib
import re
import subprocess
import sys
from pathlib import Path

KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"


def kicad_netlist(sch: Path) -> dict[str, set[tuple[str, str]]]:
    out = sch.with_suffix(".net")
    subprocess.run([KCLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(sch)],
                   check=True, capture_output=True)
    txt = out.read_text(encoding="utf-8")
    nets = {}
    for m in re.finditer(r'\(net\s+\(code\s+"?\d+"?\)\s+\(name\s+"([^"]*)"\)(.*?)\n\t\t\)', txt, re.S):
        name, body = m.group(1), m.group(2)
        nodes = set(re.findall(r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)', body))
        nets[name.lstrip("/")] = nodes
    return nets


def compare(design, sch: Path) -> list[str]:
    got = kicad_netlist(sch)
    # map by node set (net names in KiCad may be prefixed / auto-named for single-pin nets)
    want = {n: set(p) for n, p in design.nets().items()}
    problems = []
    node_to_net_got = {}
    for n, nodes in got.items():
        for nd in nodes:
            node_to_net_got[nd] = n
    for n, nodes in want.items():
        if n.startswith("NC_"):
            continue
        kicad_names = {node_to_net_got.get(nd) for nd in nodes}
        if None in kicad_names:
            missing = [nd for nd in nodes if nd not in node_to_net_got]
            problems.append(f"{n}: pins missing from KiCad netlist {missing}")
            continue
        if len(kicad_names) != 1:
            problems.append(f"{n}: split across KiCad nets {kicad_names}")
            continue
        kn = kicad_names.pop()
        extra = got[kn] - nodes
        extra = {e for e in extra if not e[0].startswith("#")}
        if extra:
            problems.append(f"{n}: KiCad net {kn} has extra pins {sorted(extra)}")
    return problems


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    mod = importlib.import_module(sys.argv[1])
    design = getattr(mod, "D", None) or getattr(mod, "U")
    probs = compare(design, Path(sys.argv[2]))
    print(f"netlist compare: {len(probs)} problem(s)")
    for p in probs:
        print("  ", p)
    sys.exit(1 if probs else 0)
