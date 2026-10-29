"""Build the SBC-1 schematic from scripts/design.py, run KiCad ERC and the netlist comparison.
Same flow as C:/work/din-relay-8ch/scripts/build_schematics.py (generator -> ERC gate -> netlist QA).
usage: python build_schematics.py        (exit 0 = schematic written, ERC clean, netlist == design)
"""
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gen_schematic as g          # noqa: E402
import qa_netlist                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KCLI = r"C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"
OUT = ROOT / "hardware" / "main"
PROJ = "skeeball-controller"
SHEETS = {   # titles <= 45 characters: they must fit the KiCad title block
    "power": "Power: protection, eFuse, rails, switches",
    "mcu": "RP2350B, QSPI flash, crystal, boot, SWD",
    "ethernet": "W5500 Ethernet + RJ45 magjack",
    "audio": "MAX98357A audio amplifier + speaker",
    "io": "Score sensors, buttons, light drivers",
    "usb": "Display USB host + USB-C debug console",
}
# rails whose drivers have no power-output pin in the symbols (passive / connector / FET / switch outputs)
FLAGS = ["+5V_IN", "GND", "+5V_RGB", "+5V_PF", "+3V3", "+3V3A", "VBUS_DBG"]   # +5V_SYS, +1V1, VBUS_HOST are
# driven by power-output pins (eFuse / LDO / switch OUT); +3V3 comes from the buck inductor (passive)
NON_ELECTRICAL_IGNORES = {"single_global_label", "four_way_junction", "simulation_model_issue", "footprint_filter",
                          "lib_symbol_mismatch", "lib_symbol_issues", "footprint_link_issues"}


def erc_gate(data):
    """Accept only a complete report with every electrical check enabled (din-relay-8ch erc_gate)."""
    if not isinstance(data.get("sheets"), list) or not data["sheets"]:
        raise ValueError("ERC report is missing sheet results")
    violations = [v for s in data["sheets"] for v in s.get("violations", [])]
    real = [v for v in violations if v.get("type") not in NON_ELECTRICAL_IGNORES]
    return not real, real, violations


def write_project_files():
    (OUT / f"{PROJ}.kicad_pro").write_text(json.dumps({"meta": {"filename": f"{PROJ}.kicad_pro", "version": 3}},
                                                     indent=2), encoding="utf-8")
    (OUT / "sym-lib-table").write_text(
        '(sym_lib_table (version 7)\n  (lib (name "skeeball")(type "KiCad")(uri "${KIPRJMOD}/../lib/skeeball.kicad_sym")'
        '(options "")(descr "SBC-1 project symbols"))\n)\n', encoding="utf-8")
    (OUT / "fp-lib-table").write_text(
        '(fp_lib_table (version 7)\n  (lib (name "skeeball")(type "KiCad")(uri "${KIPRJMOD}/../lib/skeeball.pretty")'
        '(options "")(descr "SBC-1 project footprints"))\n)\n', encoding="utf-8")


def main():
    from design import D
    issues = D.check()
    if issues:
        print("design check FAILED:", *issues, sep="\n  ")
        return 1
    for f in OUT.glob("*.kicad_sch"):
        f.unlink()
    write_project_files()
    sch = g.build(D, PROJ, OUT, SHEETS, flags=FLAGS, revision="A-draft", uuid_namespace="skeeball-controller/main",
                  symbol_library=ROOT / "hardware/lib/skeeball.kicad_sym", company="Skee-Ball lane controller SBC-1",
                  paper_for=lambda n: "A2" if n > 50 else "A3")
    audit = ROOT / ".runtime" / "erc" / uuid.uuid4().hex
    audit.mkdir(parents=True)
    rep = audit / "erc.json"
    r = subprocess.run([KCLI, "sch", "erc", "--severity-all", "--format", "json", "-o", str(rep), str(sch)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    if r.returncode:
        print("kicad-cli ERC failed:", (r.stdout + r.stderr)[-2000:])
        return 1
    data = json.loads(rep.read_text(encoding="utf-8"))
    ok, real, allv = erc_gate(data)
    print(f"ERC: {len(allv)} messages, {len(real)} electrical; evidence {rep}")
    for v in real[:40]:
        print("   ", v.get("type"), "|", v.get("description"), "|",
              "; ".join(i.get("description", "") for i in v.get("items", []))[:200])
    shutil.copy(rep, OUT / "erc-report.json")
    probs = qa_netlist.compare(D, sch)
    print(f"netlist compare: {len(probs)} problem(s)")
    for p in probs[:30]:
        print("   ", p)
    return 0 if ok and not probs else 1


if __name__ == "__main__":
    sys.exit(main())
