"""Generate the project symbol library (hardware/lib/skeeball.kicad_sym). (Pattern copied from din-relay-8ch.)

Box symbols only: pins on left/right, numbered exactly like the footprint pads.
Pin data is transcribed from the datasheets cited in each entry; see docs/QA_LOG.md
for the cross-checks against the PDFs.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "hardware" / "lib" / "skeeball.kicad_sym"

GRID = 2.54


def _prop(key, val, x, y, hide=False):
    h = "\n\t\t\t(hide yes)" if hide else ""
    return (f'\t\t(property "{key}" "{val}"\n\t\t\t(at {x:.2f} {y:.2f} 0){h}\n'
            f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n')


def _pin(ptype, num, name, x, y, rot, length=GRID):
    return (f'\t\t\t(pin {ptype} line\n\t\t\t\t(at {x:.2f} {y:.2f} {rot})\n\t\t\t\t(length {length})\n'
            f'\t\t\t\t(name "{name}"\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n'
            f'\t\t\t\t(number "{num}"\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n')


def box_symbol(name, ref, left, right, footprint="", descr="", datasheet="", value=None, width=None,
               hide_pin_numbers=False):
    """left/right: lists of (number, name, electrical_type) or None for a spacer row."""
    rows = max(len(left), len(right))
    longest = max([len(p[1]) for p in left + right if p] + [4])
    w = width or max(10.16, round((longest * 1.27 * 2 + 5.08) / GRID) * GRID)
    h = (rows + 1) * GRID
    x0, x1 = -w / 2, w / 2
    y0 = h / 2
    s = f'\t(symbol "{name}"\n'
    if hide_pin_numbers:
        s += '\t\t(pin_numbers\n\t\t\t(hide yes)\n\t\t)\n'
    s += '\t\t(pin_names\n\t\t\t(offset 1.016)\n\t\t)\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n'
    s += _prop("Reference", ref, x0, y0 + 1.27)
    s += _prop("Value", value or name, x0, -y0 - 1.27)
    s += _prop("Footprint", footprint, 0, -y0 - 3.81, hide=True)
    s += _prop("Datasheet", datasheet, 0, -y0 - 6.35, hide=True)
    s += _prop("Description", descr, 0, -y0 - 8.89, hide=True)
    s += f'\t\t(symbol "{name}_0_1"\n\t\t\t(rectangle\n\t\t\t\t(start {x0:.2f} {y0:.2f})\n\t\t\t\t(end {x1:.2f} {-y0:.2f})\n'
    s += '\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n\t\t\t\t\t(type default)\n\t\t\t\t)\n\t\t\t\t(fill\n\t\t\t\t\t(type background)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
    s += f'\t\t(symbol "{name}_1_1"\n'
    for i, p in enumerate(left):
        if p:
            s += _pin(p[2], p[0], p[1], x0 - GRID, y0 - GRID * (i + 1), 0)
    for i, p in enumerate(right):
        if p:
            s += _pin(p[2], p[0], p[1], x1 + GRID, y0 - GRID * (i + 1), 180)
    s += '\t\t)\n\t)\n'
    return s


P, I, O, B, PW, PO, NC = "passive", "input", "output", "bidirectional", "power_in", "power_out", "no_connect"
OC = "open_collector"

SYMBOLS = []

# TI TPS2595xx eFuse, WSON-8 DSG + exposed pad - TPS2595 datasheet SLVSE57C section 6 (TPS2595x0/1 pinout):
# 1 dVdt, 2 EN/UVLO, 3 IN, 4 IN, 5 OUT, 6 FLT (open drain), 7 ILM, 8 GND, PAD (9 here) = GND.
SYMBOLS.append(box_symbol(
    "TPS259531DSG", "U",
    left=[("3", "IN", PW), ("4", "IN", P), None, ("2", "EN/UVLO", I), ("1", "dVdt", P), None, ("8", "GND", PW),
          ("9", "PAD", P)],
    right=[("5", "OUT", PO), None, ("6", "~{FLT}", OC), ("7", "ILM", P)],
    footprint="Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm",
    descr="2.7-18 V 4 A 34 mOhm eFuse, 5.7 V overvoltage clamp, auto-retry, active-high EN (TPS259531)",
    datasheet="https://www.ti.com/lit/ds/symlink/tps2595.pdf"))

# TI TLV743P 300 mA LDO, SOT-23-5 DBV - TLV743P datasheet section 5: 1 IN, 2 GND, 3 EN, 4 NC, 5 OUT.
SYMBOLS.append(box_symbol(
    "TLV74311PDBV", "U",
    left=[("1", "IN", PW), ("3", "EN", I), ("2", "GND", PW)],
    right=[("5", "OUT", PO), ("4", "NC", NC)],
    footprint="Package_TO_SOT_SMD:SOT-23-5",
    descr="300 mA LDO, fixed 1.1 V, active discharge (TLV74311P)",
    datasheet="https://www.ti.com/lit/ds/symlink/tlv743p.pdf"))

# TI TPS2553 current-limited power switch, SOT-23-6 DBV - SLVS841F section 6: 1 IN, 2 GND, 3 EN (active high on
# TPS2553), 4 FAULT (open drain, active low), 5 ILIM, 6 OUT.
SYMBOLS.append(box_symbol(
    "TPS2553DBV", "U",
    left=[("1", "IN", PW), ("3", "EN", I), ("2", "GND", PW)],
    right=[("6", "OUT", PO), ("4", "~{FAULT}", OC), ("5", "ILIM", P)],
    footprint="Package_TO_SOT_SMD:SOT-23-6",
    descr="Adjustable 75 mA-1.7 A current-limited power-distribution switch, active-high EN, auto-retry (TPS2553)",
    datasheet="https://www.ti.com/lit/ds/symlink/tps2553.pdf"))

# HanRun HR963380AE vertical (top-entry) SMD RJ45 with integrated magnetics + 2 LEDs - HanRun datasheet rev 00 p.1:
# P1/P2 TD1+/-, P3/P4 TD2+/-, P5/P6 CT (common), P7/P8 TD3+/-, P9/P10 TD4+/-, orange LED 12 (A) -> 11 (K), green LED 14 (A) -> 13 (K),
# shield. Only offered as the vertical RJ45 option (docs/PLACEMENT_PLAN.md); the default schematic uses HR911105A.
SYMBOLS.append(box_symbol(
    "HR963380AE", "J",
    left=[("1", "TD1+", P), ("2", "TD1-", P), ("3", "TD2+", P), ("4", "TD2-", P), ("5", "CT", P), ("6", "CT", P),
          ("7", "TD3+", P), ("8", "TD3-", P), ("9", "TD4+", P), ("10", "TD4-", P)],
    right=[("11", "LEDO_K", P), ("12", "LEDO_A", P), ("13", "LEDG_K", P), ("14", "LEDG_A", P), None, ("SH", "SHIELD", P)],
    footprint="skeeball:RJ45_HanRun_HR963380AE_Vertical",
    descr="RJ45 vertical SMD jack, integrated 1CT:1CT magnetics, Bob-Smith network, orange + green LED (anodes 12 / 14, cathodes 11 / 13: HanRun rev 00 p.1)",
    datasheet="https://www.lcsc.com/datasheet/C19724763.pdf"))


# Micro-B receptacle used on a USB HOST port: the stock Connector:USB_B_Micro marks VBUS / GND as power outputs (device
# view), which collides with the host's VBUS switch in ERC. Same pin numbers (1 VBUS, 2 D-, 3 D+, 4 ID, 5 GND, SH).
SYMBOLS.append(box_symbol(
    "USB_B_Micro_Host", "J",
    left=[("1", "VBUS", P), ("2", "D-", B), ("3", "D+", B), ("4", "ID", P), ("5", "GND", P)],
    right=[("SH", "Shield", P)],
    footprint="Connector_USB:USB_Micro-B_Amphenol_10118194-0001LF_Horizontal",
    descr="USB 2.0 micro-B receptacle, host-side use (passive VBUS / GND pins)"))

# Analog Devices MAX98357A TQFN-16 - datasheet 19-6779 Rev 7 Pin Description (TQFN column): 1 DIN, 2 GAIN_SLOT,
# 3/11/15 GND, 4 SD_MODE, 5/6/12/13 N.C., 7/8 VDD, 9 OUTP, 10 OUTN, 14 LRCLK, 16 BCLK, EP (17) 'connect to ground'.
# (The stock Audio:MAX98357A marks EP 'unspecified', which ERC flags when it is tied to GND.)
SYMBOLS.append(box_symbol(
    "MAX98357A_TQFN", "U",
    left=[("7", "VDD", PW), ("8", "VDD", P), None, ("1", "DIN", I), ("16", "BCLK", I), ("14", "LRCLK", I), None,
          ("4", "SD_MODE", I), ("2", "GAIN_SLOT", P), None, ("3", "GND", PW), ("11", "GND", P), ("15", "GND", P),
          ("17", "EP", P)],
    right=[("9", "OUTP", O), ("10", "OUTN", O), None, ("5", "NC", NC), ("6", "NC", NC), ("12", "NC", NC),
           ("13", "NC", NC)],
    footprint="Package_DFN_QFN:TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm",
    descr="I2S class-D mono amplifier, 3.2 W into 4 R at 5 V",
    datasheet="https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf"))

HEADER = '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "skeeball_symgen")\n\t(generator_version "1.0")\n'


def extra_symbols():
    return []


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(SYMBOLS + extra_symbols())
    OUT.write_text(HEADER + body + ")\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(SYMBOLS) + len(extra_symbols())} symbols)")


if __name__ == "__main__":
    main()
