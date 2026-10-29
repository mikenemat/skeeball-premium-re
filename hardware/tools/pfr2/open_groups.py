_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]   # project root (tools/pfr2/ -> ..)
# ported from din-relay-8ch/tools/pfr2/open_groups.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Open joins of a MAIN routing stage by net group and region (CPython).

  python open_groups.py GEOM.json [--json OUT.json] [--plan PLAN.json]

Groups (first match): rails (+-1V2_BUF, BUF_GOOD_N, the B1-v2 supply-cell nets), high-Z (ISLAND_HIZ class),
follower-local (SENSE*_OUT, ADEk_IBP / IBN), island SPI (I_* bus, ADEk_SCLK / MOSI / MISO / MISOB / CS, I_ZX),
power (pfr2 power classes, plane nets, supply rails), SELV logic (class SELV / Default signals), other.
Region: where the join's midpoint sits (island top band y < 16, island bottom band y > 69 and x < 150, isolator row,
SELV side x > 150, HV middle). With --plan also the pfr2 fail_detail / exact_fail per group.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
sys.path.insert(0, str(_ROOT / "tools/pfr2"))
import cugraph
from open_joins import open_joins

RAILS = {"+1V2_BUF", "-1V2_BUF", "BUF_GOOD_N", "-VRAW_BUF", "BUF_INV_IN", "BUF_UV_SNS", "BUF_NEG_SNS"}
SPI = re.compile(r"^(I_(SCK|MOSI|MISO|CS\d|ZX)(_R)?|ADE\d_(SCLK|MOSI|MISO|MISOB|CS))$")
FOLLOW = re.compile(r"^(SENSE\d_[PN]_OUT|ADE\d_IB[PN])$")
POWER_NAMES = re.compile(r"^(GND|GND_ISO|\+.*|VISO.*|.*VCLAMP.*|VBUS.*)$")


def group(nm, cls, classes):
    if nm in RAILS or nm.startswith("BUF_CFLY"):
        return "rails"
    if "ISLAND_HIZ" in classes:
        return "high-Z"
    if FOLLOW.match(nm):
        return "follower-local"
    if SPI.match(nm):
        return "island SPI"
    if POWER_NAMES.match(nm) or cls in ("PWR_FAULT", "CHASSIS", "COIL", "POWER_SELV", "PWR15"):
        return "power"
    if cls in ("SELV", "Default"):
        return "SELV logic"
    return "other"


def region(x, y):
    if x > 150 and 45 < y < 64:
        return "isolator row"
    if x > 150:
        return "SELV side"
    if y < 16:
        return "island top band"
    if y > 69:
        return "island bottom band"
    if x < 16:
        return "left column"
    return "HV middle"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geom"); ap.add_argument("--json"); ap.add_argument("--plan")
    a = ap.parse_args()
    G = cugraph.load(a.geom)
    nets = {v["name"]: v for v in G["nets"].values()}
    oj = open_joins(G)
    by = Counter()
    reg = defaultdict(Counter)
    netc = defaultdict(Counter)
    for j in oj:
        n = nets.get(j["net"], {})
        g = group(j["net"], n.get("class", ""), n.get("classes", []))
        r = region((j["ax"] + j["bx"]) / 2, (j["ay"] + j["by"]) / 2)
        by[g] += 1
        reg[g][r] += 1
        netc[g][j["net"]] += 1
    rep = {"open": len(oj), "groups": {g: {"open": c, "regions": dict(reg[g].most_common()),
                                           "top_nets": netc[g].most_common(6)} for g, c in by.most_common()}}
    if a.plan:
        P = json.load(open(a.plan))
        rep["router_unrouted"] = sum(P["unrouted"].values())
        rep["router_exact_fail"] = P.get("exact_fail", {})
    print(f"open joins {len(oj)}")
    for g, d in rep["groups"].items():
        print(f"  {g:15s} {d['open']:4d}  regions {d['regions']}  top {d['top_nets'][:4]}")
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
