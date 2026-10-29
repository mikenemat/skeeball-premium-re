"""SBC-1 BOM - the ONLY writer of bom/bom.json (same rule as din-relay-8ch: one JSON, one writer; viewer bom/bom.html).

    python bom.py build      design.py -> BOM lines (keeps the stored JLC observations of unchanged lines)
    python bom.py refresh    JLC stock / price / library for every line through jlc_api.py (the sanctioned client)
    python bom.py check      gates: every placed line found, buyable, in JLC stock >= 2 x (need + attrition)
    python bom.py report     docs/ORDERING.md + bom/sbc1-bom.csv + fab/assembly/sbc1-jlc-bom.csv (JLC-placed lines)

Stock source: JLC's own parts-library API (the backend of jlcpcb.com/parts, the live part page); each observation
carries its UTC timestamp and the part-page URL. Price = JLC assembly unit price at the break for (need + attrition).
"""
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parents[1]
BOM = ROOT / "bom" / "bom.json"
RUN_BOARDS = 5            # 4 machines + 1 spare (JLC PCBA minimum is 2)
EXTENDED_FEE_USD = 3.0    # JLC 'extended part' feeder fee per unique extended line per order (JLC published rate;
                          # re-check at quote time)
NOT_PLACED_PREFIX = ("H", "TP", "JP")   # mounting holes, test pads, solder jumpers: copper only
# Basic-library swaps made in the cost pass (owner 2026-10-26); printed into ORDERING.md
BASIC_SWAPS = [
    ("FB1 W5500 3V3A bead", "Murata BLM18PG221SN1D 220 R 0603 (extended)", "Sunlord GZ2012D601TF 600 R 0805 (basic, C1017)",
     "WIZnet note g: 100-2000 R at 100 MHz is adequate; 500 mA rating vs 132 mA load"),
    ("R37 MAX98357A SD_MODE pull-up", "634 k 0603 (extended)", "510 k 0603WAF5103T5E (basic, C23192)",
     "VSD_MODE 0.49-0.60 V: centred in the B0 max 0.355 V .. B1 typ 0.77 V (L+R)/2 window with the internal 100 k +-8 % "
     "(q6 2026-10-27; the cost pass's 680 k left 30 mV to B0 max)"),
    ("R73 / R74 USB host 27 R", "0402WGF270JTCE (extended)", "0603WAF270JT5E (preferred, C25190)",
     "same value; 0603 footprint instead of 0402"),
]
KEPT_EXTENDED = [
    ("OVZ221M1ATR-0606 220 uF polymer x4", "no polymer capacitor in the JLC basic library (owner: no aluminium electrolytics)"),
    ("KT-0603G green LED x2", "no green 0603 LED in basic (red / yellow 0603 are); owner asked for 0603"),
    ("NCD0603Y1 yellow LED", "chosen in the q6 pass (mfg review M1) over the basic KT-0603Y, whose LCSC dot marks the "
     "anode; kept because JLC's assembly review did not flag it (D2 red went back to the basic KT-0603R C2286 on "
     "2026-10-27: NCD0603R1 is Standard-PCBA-only)"),
    ("SMBJ5.0A TVS, 1812L300MR + 2920L500/16MR polyfuses, SWPA4030S2R2MT 2.2 uH", "no basic-library equivalents found (TVS / PTC / 4x4 power inductor)"),
    ("AO3416 light FETs x4", "replaced basic AO3400A (48 mOhm at 2.5 V gate, ~0.6 W at 3 A in SOT-23): the owner's strips draw up to ~3 A per channel; no basic FET is specified <= 26 mOhm at 2.5 V"),
    ("BLM21PG221SN1D speaker beads x2", "basic beads are rated <= 800 mA; the speaker peaks at ~0.9 A rms"),
    ("ESDA6V1-5SC6 x3, USBLC6-2SC6 x2", "no ESD arrays in the basic library"),
    ("0603WAF1242T5E 12.4 k", "value specified by WIZnet (EXRES1 12.4 k 1 %); no basic / preferred listing"),
    ("ABM8-272-T3 12 MHz", "the crystal Raspberry Pi specifies for the RP2350"),
    ("ICs and connectors", "not swapped (owner rule)"),
]


def resolve_mpn(p):
    """(MPN, maker) for the schematic fields - imported by gen_schematic.py."""
    return p.mpn, p.mfr


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def design_lines():
    from design import D
    groups = {}
    for p in D.parts.values():
        if p.ref.startswith(NOT_PLACED_PREFIX) or not p.mpn:
            continue
        key = p.mpn
        gl = groups.setdefault(key, {"key": key, "mpn": p.mpn, "mfr": p.mfr, "value": p.value,
                                     "footprint": p.footprint, "refs": [], "lcsc_design": p.fields.get("LCSC", ""),
                                     "sheet": p.sheet, "note": ""})
        gl["refs"].append(p.ref)
        if p.ref.startswith("J") and "HARNESS" in p.note:
            gl["harness"] = True
            gl["provisional"] = "PROVISIONAL" in p.note or p.mpn.startswith("TBD")
    for gl in groups.values():
        gl["refs"].sort(key=lambda r: (r.rstrip("0123456789"), int("".join(c for c in r if c.isdigit()) or 0)))
        gl["qty_per_board"] = len(gl["refs"])
    src = (Path(__file__).parent / "design.py").read_bytes()
    return sorted(groups.values(), key=lambda x: (x["refs"][0][0], x["mpn"])), hashlib.sha256(src).hexdigest()


def load():
    return json.loads(BOM.read_text(encoding="utf-8")) if BOM.exists() else {"lines": []}


def save(b):
    BOM.parent.mkdir(parents=True, exist_ok=True)
    b["updated_utc"] = _now()
    BOM.write_text(json.dumps(b, indent=1, ensure_ascii=False), encoding="utf-8")


def cmd_build():
    old = {l["key"]: l for l in load().get("lines", [])}
    lines, sha = design_lines()
    for l in lines:
        if l["key"] in old and "jlc" in old[l["key"]]:
            l["jlc"] = old[l["key"]]["jlc"]
            l["history"] = old[l["key"]].get("history", [])
    b = {"project": "SBC-1 Skee-Ball lane controller", "run_boards": RUN_BOARDS, "design_sha256": sha,
         "lines": lines}
    save(b)
    print(f"bom.json: {len(lines)} lines, design {sha[:8]}")


def cmd_refresh(only=None):
    import jlc_api as J
    b = load()
    for l in b["lines"]:
        if only and l["key"] not in only:
            continue
        if l["mpn"].startswith("TBD"):
            l["status"] = "TBD"
            continue
        need = l["qty_per_board"] * b["run_boards"]
        try:
            lk = J.by_code(l["lcsc_design"]) if l["lcsc_design"] else J.by_mpn(l["mpn"], maker=l["mfr"] or None)
        except J.JlcError as e:
            print("LOOKUP FAILED", l["key"], e)
            continue
        p = lk.part
        if p is None:
            l["jlc"] = {"fetched_utc": _now(), "found": False, "status_text": lk.status, "note": lk.note}
            print(f"  {l['key']:28} NOT FOUND ({lk.status})")
            continue
        attr = J.attrition(need, p.loss)
        order = need + attr
        price = None
        for lo, hi, pr in p.prices or []:
            if order >= lo and (hi is None or order <= hi):
                price = pr
        if price is None and p.prices:
            price = p.prices[0][2]
        obs = {"fetched_utc": _now(), "found": True, "code": p.code, "mpn": p.mpn, "maker": p.maker,
               "stock": p.stock, "library": p.library_label, "preferred": p.preferred, "package": p.package,
               "presale": p.presale, "buyable": p.buyable, "prices": p.prices, "need": need, "attrition": attr,
               "order_qty": order, "unit_price_usd": price, "part_page": p.jlc_url, "datasheet": p.datasheet}
        l["jlc"] = obs
        l.setdefault("history", []).append({k: obs[k] for k in ("fetched_utc", "stock", "unit_price_usd")})
        l["history"] = l["history"][-10:]
        print(f"  {l['key']:28} {p.code:10} stock {p.stock:>8} {p.library_label:8} ${price}")
    save(b)


def status(l, run):
    if l["mpn"].startswith("TBD"):
        return "TBD"
    j = l.get("jlc")
    if not j or not j.get("found"):
        return "NOT_FOUND"
    if not j.get("buyable"):
        return "NOT_BUYABLE"
    need = j["need"] + j["attrition"]
    if j["stock"] < need:
        return "OUT"
    if j["stock"] < 2 * need:                     # owner rule: >= 2 x (need + attrition); run = 5 boards max
        return "THIN"
    return "OK"


def _norm_mpn(s):
    """MPN identity key: upper case alphanumerics, leading zeros dropped (JLC lists Molex 0039301049 as 39301049)"""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper()).lstrip("0")


def identity_fails(l):
    """adversarial review F02 (2026-10-27): D4 KT-0603Y on a 0603 land was ordered as C2296 = KT-0805Y (0805) and the
    check said OK. The JLC part behind the C-number must be the design MPN, and for a footprint with a size code
    (R / C / L / LED / Fuse _<imperial>_<metric>Metric) the JLC package must name that size."""
    j = l.get("jlc") or {}
    if not j.get("found"):
        return []
    out = []
    if _norm_mpn(j.get("mpn")) != _norm_mpn(l["mpn"]):
        out.append(f"{l['key']}: JLC {j.get('code')} is {j.get('mpn')!r}, design MPN {l['mpn']!r}")
    m = re.search(r"_(\d{4})_(\d{4})Metric", l["footprint"])
    pk = j.get("package") or ""
    if m and m.group(1) not in pk and m.group(2) not in pk:
        out.append(f"{l['key']}: JLC {j.get('code')} package {pk!r} vs footprint {l['footprint'].split(':')[-1]}")
    return out


def cmd_check():
    b = load()
    lines, sha = design_lines()
    fails = []
    if sha != b.get("design_sha256"):
        fails.append("bom.json is stale vs design.py (run: bom.py build && bom.py refresh)")
    for l in b["lines"]:
        st = status(l, b["run_boards"])
        idf = identity_fails(l)
        if idf and st == "OK":
            st = "IDENTITY"
        l["status"] = st
        if st in ("NOT_FOUND", "NOT_BUYABLE", "OUT") and not l.get("provisional"):
            fails.append(f"{l['key']}: {st}")
        fails += idf
    save(b)
    for f in fails:
        print("FAIL", f)
    thin = [l["key"] for l in b["lines"] if l.get("status") == "THIN"]
    tbd = [l["key"] for l in b["lines"] if l.get("status") == "TBD" or l.get("provisional")]
    print(f"check: {len(b['lines'])} lines, {len(fails)} fail, thin = {thin}, harness TBD/provisional = {tbd}")
    return 0 if not fails else 1


def cost(b):
    placed = sum((l.get("jlc") or {}).get("unit_price_usd") or 0 for l in b["lines"] for _ in range(l["qty_per_board"])
                 if not l.get("harness"))
    harness = sum((l.get("jlc") or {}).get("unit_price_usd") or 0 for l in b["lines"]
                  for _ in range(l["qty_per_board"]) if l.get("harness"))
    ext = sorted({l["key"] for l in b["lines"] if (l.get("jlc") or {}).get("library") == "extended"})
    return placed, harness, ext


def cmd_report():
    b = load()
    placed, harness, ext = cost(b)
    run = b["run_boards"]
    rows = []
    for l in b["lines"]:
        j = l.get("jlc") or {}
        tag = "harness, provisional" if l.get("provisional") else ("harness" if l.get("harness") else "")
        rows.append([", ".join(l["refs"]), l["qty_per_board"], l["value"], l["mpn"], l["mfr"], j.get("code", ""),
                     j.get("library", ""), j.get("stock", ""), j.get("unit_price_usd", ""),
                     (j.get("fetched_utc") or "")[:10], l.get("status", ""), tag])
    hdr = ["Refs", "Qty/board", "Value", "MPN", "Maker", "LCSC", "JLC library", "JLC stock", "Unit USD (JLC)",
           "Checked (UTC)", "Status", "Notes"]
    with open(ROOT / "bom" / "sbc1-bom.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)
    fab = ROOT / "fab" / "assembly"
    fab.mkdir(parents=True, exist_ok=True)
    with open(fab / "sbc1-jlc-bom.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for l in b["lines"]:
            j = l.get("jlc") or {}
            w.writerow([f"{l['value']} {l['mpn']}", ",".join(l["refs"]), l["footprint"].split(":")[-1], j.get("code", "")])
    fee = EXTENDED_FEE_USD * len(ext)
    pcb_note = ("PCB + assembly service (2-layer 1.6 mm, ~109 x 85 mm, 5 pcs, single-sided assembly) is quoted at "
                "order time on jlcpcb.com; not included above.")
    md = ["# ORDERING - generated by `python scripts/bom.py report` (do not edit)", "",
          f"Data: bom/bom.json updated {b.get('updated_utc', '?')} (JLC parts-library API = live part-page data).",
          f"Run: {run} boards (4 machines + 1 spare).", "",
          "## Cost per board (parts at the JLC assembly price for the run quantity)", "",
          f"| Item | USD / board |", "|---|---:|",
          f"| Placed parts (all non-harness lines) | {placed:.2f} |",
          f"| Harness connectors (genuine Molex at the stock-board locations) | {harness:.2f} |",
          f"| JLC extended-part fees: {len(ext)} lines x ${EXTENDED_FEE_USD:.0f} / order, spread over {run} boards | "
          f"{fee / run:.2f} |",
          f"| **Parts total (one JLC order = the full board)** | **{placed + harness + fee / run:.2f}** |",
          "", pcb_note, "",
          "The JLC assembly order covers every line below (SMT + the through-hole harness headers); nothing is "
          "owner-fitted.", "",
          "## Lines", "", "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    md += ["", "Status: OK = JLC stock >= 2 x (run need + attrition) and >= 100; THIN = enough for this run but below "
           "that margin; TBD = harness part waiting for the owner's connector identification.", "",
           "## Basic-library swaps (cost pass, owner 2026-10-26)", "",
           "JLC charges the extended-part fee per unique extended line and order; 'preferred' extended parts are listed "
           "by JLC as fee-exempt (re-check on the quote screen). Lines swapped, with the reason it is a drop-in:", "",
           "| Line | Was | Now | Why a drop-in |", "|---|---|---|---|"]
    md += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in BASIC_SWAPS]
    md += ["", "Extended lines kept, and why:", "", "| Line(s) | Reason |", "|---|---|"]
    md += [f"| {a} | {b} |" for a, b in KEPT_EXTENDED]
    md += ["", f"Extended-part fees: {len(ext)} lines x ${EXTENDED_FEE_USD:.0f} = ${fee:.0f} per order -> "
           f"${fee / run:.2f} / board at {run} boards."]
    (ROOT / "docs" / "ORDERING.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"report: JLC placed {placed:.2f} + harness {harness:.2f} + ext fees {fee / run:.2f} = "
          f"{placed + harness + fee / run:.2f} USD/board at {run}; {len(ext)} extended lines")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "build":
        cmd_build()
    elif cmd == "refresh":
        cmd_refresh(set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None)
    elif cmd == "check":
        sys.exit(cmd_check())
    elif cmd == "report":
        cmd_report()
    else:
        print(__doc__)
