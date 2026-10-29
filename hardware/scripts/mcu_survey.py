"""MCU / Ethernet option survey for docs/ARCHITECTURE.md section 3: JLC stock + price (5-board run) of each
candidate's core chips, via jlc_api.py. Writes docs/records/mcu_survey/survey.json (evidence; re-run to refresh).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import jlc_api as J  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = {
    "A RP2350B + W5500 + W25Q128 (chosen)": ["C42415655", "C32843", "C97521", "C12074"],
    "A' RP2350A (QFN-60, 30 GPIO) - first pick": ["C42411118"],
    "B STM32F407VGT6 + LAN8720A PHY": ["C12345", "C45223", "C12074"],
    "C CH32V307VCT6 (MAC + 10M PHY) + W25Q128": ["C2943979", "C97521", "C12074"],
    "C' CH32V307RCT6 (LQFP-64)": ["C2988083"],
    "D ESP32-S3-WROOM-1-N16R8 + W5500": ["C2913202", "C32843", "C12074"],
    "E WIZnet W55RP20 (RP2040 + W5500 SiP)": ["C44874687"],
}
QTY = 5


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    out = {"fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "qty": QTY, "options": {}}
    for name, codes in OPTIONS.items():
        rows, total = [], 0.0
        for c in codes:
            p = J.by_code(c).part
            price = None
            for lo, hi, pr in p.prices or []:
                if QTY >= lo and (hi is None or QTY <= hi):
                    price = pr
            rows.append({"code": c, "mpn": p.mpn, "stock": p.stock, "buyable": p.buyable, "unit_usd": price,
                         "package": p.package, "page": p.jlc_url})
            total += price or 0
        out["options"][name] = {"parts": rows, "core_usd": round(total, 2)}
        print(f"{name:45} ${total:6.2f}  " + "  ".join(f"{r['mpn']}({r['stock']})" for r in rows))
    d = ROOT / "docs" / "records" / "mcu_survey"
    d.mkdir(parents=True, exist_ok=True)
    (d / "survey.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
