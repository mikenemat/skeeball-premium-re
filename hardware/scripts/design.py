"""Skee-Ball lane controller (SBC-1), replacement for Bay Tek main board A5CB25502 Rev 2.2: every part, value, MPN,
JLC C-number and net. Imported by build_schematics.py (schematic + ERC + netlist QA) and bom.py.

Every IC block follows its vendor reference design; the reference (document + figure / section) is cited in the
block comment, and docs/ARCHITECTURE.md section 6 lists each deviation with its reason.

Harness-facing pin maps marked CONFIRM are provisional until the owner's continuity check
(docs/MEASUREMENTS_NEEDED.md): change only the *_PINMAP tables below and regenerate.
"""
from netlist_core import Design

D = Design()
D.pkg = "0603"
R, C = D.R, D.C

GND, V5IN, V5, V3, V1 = "GND", "+5V_IN", "+5V_SYS", "+3V3", "+1V1"
V5RGB, V5PF, VBUSH = "+5V_RGB", "+5V_PF", "VBUS_HOST"

FP_R0402, FP_C0402 = "Resistor_SMD:R_0402_1005Metric", "Capacitor_SMD:C_0402_1005Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"

# ---------------------------------------------------------------------------------------------------------------------
# Passive catalogue: JLC basic-library parts (resolved and stock-checked by bom.py through jlc_api.py).
# Resistors: UNI-ROYAL 0603WAF / 0402WGF thick film 1 %; capacitors: Samsung CL series X7R / X5R / C0G.
# ---------------------------------------------------------------------------------------------------------------------
def r_mpn(value, size="0603"):
    """UNI-ROYAL MPN for a 1 % thick-film resistor (0603WAF / 0402WGF series naming)."""
    mult = {"": 1, "k": 1e3, "M": 1e6}
    v = value.rstrip("RkM") if value[-1] in "RkM" else value
    unit = value[-1] if value[-1] in "kM" else ""
    ohms = float(v) * mult[unit]
    pre = "0603WAF" if size == "0603" else "0402WGF"
    if ohms == 0:
        return pre + "0000T5E" if size == "0603" else pre + "0000TCE"
    if ohms < 100:
        code = f"{ohms:.1f}".replace(".", "").rstrip("0")
        code = f"{int(round(ohms * 10)):03d}J"          # e.g. 27R -> 270J, 49.9R -> 499J
    else:
        exp = 0
        m = ohms
        while m >= 1000:
            m /= 10
            exp += 1
        code = f"{int(round(m)):03d}{exp}"            # 3 significant digits + multiplier
    return pre + code + ("T5E" if size == "0603" else "TCE")


CAP = {   # value -> (MPN, maker, footprint)
    "100nF":      ("CC0603KRX7R9BB104", "YAGEO", "Capacitor_SMD:C_0603_1608Metric"),
    "100nF 0402": ("CL05B104KO5NNNC", "Samsung", FP_C0402),
    "1uF":        ("CL10A105KB8NNNC", "Samsung", "Capacitor_SMD:C_0603_1608Metric"),
    "4.7uF 0402": ("CL05A475MP5NRNC", "Samsung", FP_C0402),
    "4.7uF 0805": ("CL21A475KAQNNNE", "Samsung", FP_C0805),
    "10uF":       ("CL21A106KAYNNNE", "Samsung", FP_C0805),
    "22uF":       ("CL21A226MAQNNNE", "Samsung", FP_C0805),     # Samsung NRND (C8 / C16); JLC stock covers 5 boards
    "1nF":        ("CL10B102KB8NNNC", "Samsung", "Capacitor_SMD:C_0603_1608Metric"),
    "6.8nF":      ("0603B682K500NT", "FH", "Capacitor_SMD:C_0603_1608Metric"),
    "10nF":       ("0603B103K500NT", "FH", "Capacitor_SMD:C_0603_1608Metric"),
    "22nF":       ("CL10B223KB8NNNC", "Samsung", "Capacitor_SMD:C_0603_1608Metric"),
    "47nF":       ("CL10B473KB8NNNC", "Samsung", "Capacitor_SMD:C_0603_1608Metric"),
    "15pF C0G":   ("CL10C150JB8NNNC", "Samsung", "Capacitor_SMD:C_0603_1608Metric"),
    "18pF C0G":   ("CL10C180JB8NNNC", "Samsung", "Capacitor_SMD:C_0603_1608Metric"),
    "220uF polymer": ("OVZ221M1ATR-0606", "Lelon", "Capacitor_SMD:CP_Elec_6.3x5.9"),
}


def cap(value, a, b, sheet, note="", **kw):
    mpn, mfr, fp = CAP[value]
    shown = value.replace(" 0402", "").replace(" 0805", "")
    return D.add("C", "Device:C_Polarized" if "polymer" in value else "Device:C", shown, fp, sheet,
                 {"1": a, "2": b}, mpn=mpn, mfr=mfr, note=note, **kw)


def res(value, a, b, sheet, size="0603", note="", **kw):
    fp = "Resistor_SMD:R_0603_1608Metric" if size == "0603" else FP_R0402
    return D.add("R", "Device:R", value, fp, sheet, {"1": a, "2": b}, mpn=r_mpn(value, size), mfr="UNI-ROYAL",
                 note=note, tolerance="1%", **kw)


# =====================================================================================================================
# HARNESS PIN MAPS (provisional: CONFIRM by continuity on the stock board, docs/MEASUREMENTS_NEEDED.md M-P*)
# =====================================================================================================================
SCORES = ["SC_GUTTER", "SC_10", "SC_20", "SC_30", "SC_40", "SC_50", "SC_100A", "SC_100B"]
# GPIO map = escape order of the RP2350B pins (owner 2026-10-26: the firmware is an original implementation, the stock
# RP2040 roles are lifted; DECISIONS #8). The 8 score lines leave the LEFT side top -> bottom in the RC grid's
# left -> right column order (100B .. gutter), so the bundle fans out to the grid without a crossing.
SCORE_GPIO = {"SC_100B": 14, "SC_100A": 15, "SC_50": 16, "SC_40": 17, "SC_30": 18, "SC_20": 19, "SC_10": 20,
              "SC_GUTTER": 21}
J11_PINMAP = {1: GND, 2: "SC_100B", 3: "SC_50", 4: "SC_40", 5: "SC_30", 6: "SC_20", 7: "SC_10", 8: "SC_GUTTER",
              9: "SC_100A"}
# ^ pin 1 = the '*' square pad (right end, top view) = the switches' common = GND (owner continuity 2026-10-26).
#   Score order = owner continuity 2026-10-27, NOT linear: top view, jacks 1-8 left -> right (J21-J28, labels
#   '0 10 20 30 40 50 100 100') and header positions 1-9 left -> right (= our pins 9..1): jacks 1-6 -> positions 2-7,
#   jack 7 (first '100') -> position 1, jack 8 (last '100') -> position 8, GND = position 9. The bottom scan agrees:
#   a bottom-side trace runs from the leftmost header pin along the row to the first '100' jack's contact-2 tail.
#   J11 carries NO 5 V
BUTTONS = ["BTN_START", "BTN_B", "BTN_C", "BTN_D"]
BUTTON_GPIO = {"BTN_START": 10, "BTN_B": 11, "BTN_C": 12, "BTN_D": 13}   # B/C/D = VOLUME/GAME/PLAYERS, order CONFIRM;
# left side above the score lines (outermost of the south-west bundle toward the buttons RC block / U11)
BUTTONS_PINMAP = {1: "BTN_D", 2: "BTN_C", 3: "BTN_B", 4: "BTN_START", 5: GND, 6: GND, 7: GND, 8: GND}
# ^ owner continuity 2026-10-26: the whole bottom row (the latch side, component face up) = GND, the top row = the four
#   button signals (START / GAME / PLAYERS / VOLUME order = firmware), left to right on the board D C B START.
#   Molex 39-28-1083 / KiCad 5566-08A: the latch is on the circuits 5-8 row (KiCad fab + JLC C293503 footprint and 3D
#   model agree; verified 2026-10-27 after the owner saw the latch 180 deg off in the render) -> 5-8 = GND (latch row,
#   scan y 61.7), 1-4 = the signals (scan y 56.2), footprint at 0 deg with pin 1 = the leftmost signal pin
POWER_PINMAP = {1: V5IN, 2: "NC_PWR_MID", 3: GND}  # owner 2026-10-26: middle pin not connected; 1 = 5 V, 3 = GND
RGB_PINMAP = {1: V5RGB, 2: "LED_R_K", 3: "LED_G_K", 4: "LED_B_K"}   # pin 1 (leftmost, square pad, black wire)
# = +5 V by owner continuity 2026-10-26 (common anode confirmed); the R / G / B order of pins 2-4 is a firmware matter
PLAYFIELD_PINMAP = {1: V5PF, 2: "LED_PF_K"}   # pin 1 = the LOWER pin (nearer the RGB connector, farther from
# the top edge, component side up) = +5 V by owner continuity 2026-10-26; the upper pin = low-side FET channel
SPEAKER_PINMAP = {1: "SPK_P", 2: "SPK_N"}                         # bridge-tied load: neither side is ground

# RJ45 (owner decision 2026-10-26): zone a (stock model-number silk area), VERTICAL jack = "V" (HanRun HR963380AE);
# "RA" (HanRun HR911105A right-angle) is kept in the generator only as the fallback if the vertical part runs out.
RJ45_OPTION = "V"

# =====================================================================================================================
# SHEET power: 5 V input protection, eFuse, rails
# =====================================================================================================================
S = "power"
D.block = "pwr_in"
D.add("J", "Connector_Generic:Conn_01x03", "PWR 5V/GND", "skeeball:Molex_Mini-Fit_Jr_39-30-3035_1x03_P4.20mm_Horizontal",
      S, {str(k): v for k, v in POWER_PINMAP.items()}, mpn="39303035", mfr="Molex", LCSC="C505179",
      note="HARNESS (stock location + type): Molex Mini-Fit Jr SINGLE-ROW 1x3 right-angle header 39-30-3035 with "
           "snap-in peg board locks (JLC C505179; the scan shows both peg holes 7.15 mm toward the top edge under pins "
           "1 and 3), plug from the top edge; pin 1 = 5 V, pin 2 not connected, pin 3 = GND (owner 2026-10-26). Pads "
           "at x 95.6 / 99.7 / 104.0, y 10.7 (scan). JLC-placed (the earlier owner-fitted route assumed JLC had none)")
D.add("D", "Device:D_TVS", "SMBJ5.0A", "Diode_SMD:D_SMB", S, {"1": V5IN, "2": GND}, mpn="SMBJ5.0A", mfr="Littelfuse",
      LCSC="C83333", note="input clamp: VRWM 5.0 V, VBR 6.4 V min; absorbs harness / brick transients ahead of the eFuse "
                          "(TPS2595 SLVSE57C 9.2: TVS at IN recommended for inductive input cabling). UNIDIRECTIONAL: "
                          "footprint pad 1 = cathode band = +5V_IN, pad 2 = anode = GND (pad 1 on GND would forward-bias "
                          "it across the supply; fixed 2026-10-26, QA Q-35)")
# Light rails (owner 2026-10-26 loads: RGB = 60 LED/m 5050 analog strip over the 2.06 m alley + ball area, 7-9 A at
# full white uncapped; playfield = one bar ~24 x 5050, 1.2-1.5 A; PSU Mean Well LPV-60-5, 8 A). One high-side PTC per
# harness: it carries the whole strip current, so it also covers a channel wire shorted to the strip's +5 V (FET on).
# Firmware caps the light current (RMS = I_on x sqrt(duty) per channel, ARCHITECTURE 5.13): RGB <= 3.7 A RMS at <= ~45 C
# cabinet ambient (F1 derating below), playfield <= 1.5 A, both together <= 5.0 A.
D.add("F", "Device:Polyfuse", "5A hold", "Fuse:Fuse_2920_7451Metric", S, {"1": V5IN, "2": V5RGB},
      mpn="2920L500/16MR", mfr="Littelfuse", LCSC="C207091",
      note="RGB strip common: 5 A hold / 10 A trip at 20 C, 16 V, R1max 25 mOhm. Littelfuse 2920L derating (reference "
           "data): hold 4.15 A at 40 C, 3.75 A at 50 C, 3.30 A at 60 C (the conservative of the two review sets; the "
           "Littelfuse 2920L table reads 4.25 / 3.88 / 3.50 A) -> firmware RGB cap 3.3 A RMS at <= 50 C local ambient "
           "(owner can raise it in firmware; coordinator QA A9 2026-10-27). Coordination (power review P4): a hard short "
           "is limited by the LPV-60-5 hiccup (8.8-12 A) before F1 trips; F1 covers sustained overloads between hold "
           "and the supply limit (owner decision O2 open). Not upsized (a bigger PTC worsens that coordination); the "
           "stock board feeds the strips unprotected")
D.add("F", "Device:Polyfuse", "3A hold", "Fuse:Fuse_1812_4532Metric", S, {"1": V5IN, "2": V5PF},
      mpn="1812L300MR", mfr="Littelfuse", LCSC="C127824",
      note="playfield bar common: 3 A hold / 5 A trip, 6 V, R1max 40 mOhm; 2x the 1.5 A bar current")
cap("220uF polymer", V5RGB, GND, S, note="RGB rail bulk at the PWM switches: polymer aluminium (replaces the stock "
                                         "aluminium electrolytic, owner 2026-10-26); 2000 h at 105 C")
cap("10uF", V5RGB, GND, S)
cap("10uF", V5PF, GND, S)

D.block = "efuse"
# TI TPS2595 SLVSE57C section 9.2 Typical Application (Figure 47): CIN 0.1 uF, EN/UVLO divider R1/R2, dVdt cap,
# ILM resistor, FLT pull-up, COUT. TPS259531 = 5.7 V OV clamp (5.2-5.7 V out while clamping), auto-retry.
D.add("U", "skeeball:TPS259531DSG", "TPS259531DSGR", "Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm", S,
      {"IN": V5IN, "OUT": V5, "EN/UVLO": "EFUSE_EN", "dVdt": "EFUSE_DVDT", "~{FLT}": "PWR_FAULT_N",
       "ILM": "EFUSE_ILM", "GND": GND, "PAD": GND}, mpn="TPS259531DSGR", mfr="Texas Instruments", LCSC="C2155674",
      note="logic / audio / sensor / USB rail. Current limit 2.8-3.2 A (RILM 680R: 2030 A.Ohm / RILM per the SLVSE57C "
           "7.5 table points 487R -> 4.17 A, 1780R -> 1.17 A). Over-voltage: +5V_SYS follows +5V_IN up to the OV threshold "
           "VOVC 5.5-5.9 V and is clamped to 5.2-5.7 V above it (SLVSE57C p.7), so under a supply fault +5V_SYS can "
           "reach 5.9 V: above the 5.5 V recommended maximum of the TLV62569 / MAX98357A, under their 6.0 V absolute "
           "maximum (coordinator QA A9 2026-10-27; was '<= 5.7 V')")
cap("100nF", V5IN, GND, S, note="CIN 0.1 uF (Figure 47 note 1)")
cap("10uF", V5IN, GND, S, note="input bulk at the header (brick lead inductance)")
res("100k", V5IN, "EFUSE_EN", S, note="UVLO divider (SLVSE57C 9.2.2.2, Eq. 1) with R2 47k: rising typ 1.2 V x "
                                       "(1 + 100k / 47k) = 3.75 V; worst high (VUVLO(R) max 1.27 V, both 1 %, IEN "
                                       "0.1 uA x 101k) 4.04 V, worst low 3.48 V; falling (1.03-1.17 V) 3.17-3.72 V, typ "
                                       "3.44 V. Was 39k (worst rising 4.60 V = the LPV-60-5 -8 % floor, adversarial "
                                       "review F04 2026-10-27). +5V_SYS loads run from 2.5 V (U2 TLV62569 / U8 "
                                       "MAX98357A 2.5-5.5 V, U4 TPS2553 2.5-6.5 V)")
res("47k", "EFUSE_EN", GND, S)
cap("47nF", "EFUSE_DVDT", GND, S, note="CdVdt = 42000 pF / SR (V/ms) (Eq. 3): 47 nF -> 0.89 V/ms; inrush into "
                                        "~0.6 mF = 0.54 A, 5.6 ms ramp (Eq. 8/9: 1.4 W for 5.6 ms)")
res("680", "EFUSE_ILM", GND, S, note="current limit ~3.0 A (see U note); 1 %")
D.add("D", "Device:LED", "FAULT red", "LED_SMD:LED_0603_1608Metric", S, {"A": "LED_FAULT_A", "K": "PWR_FAULT_N"},
      mpn="KT-0603R", mfr="Hubei KENTO", LCSC="C2286",
      note="FAULT LED on the wired-OR open-drain fault line (eFuse FLT + TPS2553 FAULT): lit = over-current / "
           "over-temperature / OV clamp on a rail; the line is also read on GPIO47. Hubei KENTO KT-0603R, JLC basic "
           "(Economic-PCBA eligible; NationStar NCD0603R1 C84263 is Standard-PCBA-only per JLC's assembly review "
           "2026-10-27). KENTO drawing: pad 1 = '+' (anode); C2286's LCSC symbol / footprint agree (pin 1 = A, "
           "layer-101 polarity dot on pad 1), so JLC's preview dot marks the ANODE on this part; fab_release.py maps "
           "it by the LCSC A / K pin names onto our A / K nets (DECISIONS #23)")
res("1k", V3, "LED_FAULT_A", S, note="FAULT LED current ~1.3 mA (LED in series: this is NOT the line's pull-up, R81 is)")
D.add("R81", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", S, {"1": V3, "2": "PWR_FAULT_N"},
      mpn=r_mpn("10k"), mfr="UNI-ROYAL", tolerance="1%", fixed_ref=True,
      note="PWR_FAULT_N pull-up (TPS2595 SLVSE57C pin table: FLT open drain, 'requires an external pull up "
           "resistance'; logic review L-01 2026-10-27): the line idles at 3.3 V (RP2350 VIH 2.0 V); the FAULT LED "
           "still lights at ~1.3 mA when a FLT / FAULT pin pulls low. Fixed ref after R80 (routed board refs stay)")
cap("220uF polymer", V5, GND, S, note="+5V_SYS bulk at the eFuse output; polymer (owner 2026-10-26)")
cap("22uF", V5, GND, S)
cap("100nF", V5, GND, S)

D.block = "buck3v3"
# TI TLV62569 SLVSDG1C section 8.2 Typical Application (Figure 5): C1 4.7 uF in, L1 2.2 uH, C2 10 uF out,
# R1/R2 divider (Eq. 2, R2 <= 200 k) and the feed-forward C3 across R1. 3.3 V: R1 100k / R2 22k (both JLC basic);
# C3 keeps Figure 5's R1 x C3 time constant (200k x 6.8 pF = 1.36 us): 100k x 15 pF = 1.5 us.
D.add("U", "Regulator_Switching:TLV62569DBV", "TLV62569DBVR", "Package_TO_SOT_SMD:SOT-23-5", S,
      {"VIN": V5, "EN": V5, "GND": GND, "SW": "SW_3V3", "FB": "FB_3V3"}, mpn="TLV62569DBVR",
      mfr="Texas Instruments", LCSC="C141836",
      note="5 V -> 3.3 V, 2 A sync buck. 3.3 V budget ~0.35 A (RP2350 + W5500 132 mA + flash + CH340N + pull-ups); "
           "replaces the stock NCP1117 LDO (0.6 W of heat at that load, 1.1 V dropout)")
cap("4.7uF 0805", V5, GND, S, note="C1 (Table 3: 4.7 uF X7R 0805); fitted CL21A475KAQNNNE is X5R 25 V (adversarial "
                                     "review 2026-10-27): at 5 V / <= 85 C the X5R tolerance band is adequate for the "
                                     "buck input")
D.add("L", "Device:L", "2.2uH", "Inductor_SMD:L_Sunlord_SWPA4030S", S, {"1": "SW_3V3", "2": V3},
      mpn="SWPA4030S2R2MT", mfr="Sunlord", LCSC="C36409",
      note="L1 2.2 uH 4x4 mm (Table 3 value; Table 4 LC matrix: 2.2 uH + 10 uF checked)")
cap("10uF", V3, GND, S, note="C2 10 uF X5R 0805")
res("100k", V3, "FB_3V3", S, note="R1: VOUT = 0.6 V x (1 + 100k / 22k) = 3.327 V (Eq. 2; 3.26-3.39 V at 1 % + "
                                   "the 0.588-0.612 V FB spread)")
res("22k", "FB_3V3", GND, S, note="R2")
cap("15pF C0G", V3, "FB_3V3", S, note="C3 feed-forward (see block note)")

D.block = "ldo1v1"
# RP2350 datasheet section 'External core supply with on-chip regulator disabled' (Figure 24): DVDD from an external
# 1.1 V supply; VREG_VIN + VREG_AVDD still powered from 3.3 V with one 4.7 uF; VREG_FB to GND; inductor omitted.
D.add("U", "skeeball:TLV74311PDBV", "TLV74311PDBVR", "Package_TO_SOT_SMD:SOT-23-5", S,
      {"IN": V3, "EN": V3, "GND": GND, "OUT": V1, "NC": "NC_LDO4"}, mpn="TLV74311PDBVR", mfr="Texas Instruments",
      LCSC="C485147",
      note="RP2350 DVDD 1.1 V +-1.4 % (1.085-1.115 V) inside the 1.05-1.16 V DVDD range (RP2350 DS table 1435). "
           "DEVIATION from the Minimal design's internal switcher: its only specified inductor "
           "(Abracon AOTA-B201610S3R3-101-T) has JLC stock 1 (2026-10-26); Figure 24 is the vendor's own alternative")
cap("1uF", V3, GND, S, note="TLV743P CIN 1 uF (SBVS254 8.1)")
cap("1uF", V1, GND, S, note="TLV743P COUT 1 uF")

D.block = "switches"
# TI TPS2553 SLVS841F section 10.2 Typical Application: 0.1 uF at IN, RILIM to GND, FAULT pull-up, output cap.
for name, out, note in (("VBUS_HOST", VBUSH, "display USB VBUS (host port)"),):
    D.add("U", "skeeball:TPS2553DBV", "TPS2553DBVR", "Package_TO_SOT_SMD:SOT-23-6", S,
          {"IN": V5, "EN": "VBUS_HOST_EN", "GND": GND, "OUT": out, "~{FAULT}": "PWR_FAULT_N", "ILIM": f"ILIM_{name}"},
          mpn="TPS2553DBVR", mfr="Texas Instruments", LCSC="C55266",
          note=f"{note}; limit 0.43-0.52 A (RILIM 49.9k, SLVS841F 7.5); EN = GPIO46 (VBUS_HOST_EN, active high) with a "
               "100k pull-down: VBUS_HOST stays off through reset / BOOTSEL until firmware enables it (adversarial "
               "review F08 2026-10-27: EN on +3V3 sourced VBUS into a PC on the BOOTSEL recovery cable)")
    cap("100nF", V5, GND, S, note="IN bypass 0.1 uF (10.2)")
    res("49.9k", f"ILIM_{name}", GND, S)
    cap("22uF", out, GND, S, note="output cap (TI recommends a large output cap for transient loads)")
D.add("R80", "Device:R", "4.7k", "Resistor_SMD:R_0603_1608Metric", S, {"1": "VBUS_HOST_EN", "2": GND},
      mpn=r_mpn("4.7k"), mfr="UNI-ROYAL", tolerance="1%", fixed_ref=True,
      note="U4 EN pull-down: TPS2553 off while GPIO46 is high-Z (RP2350 reset state: output Hi-Z, pulled low, DS 9.3). "
           "4.7k (<= 8.2k) so a GPIO turned from driven-high to input with IE set cannot hold the pad at ~2.2 V "
           "(RP2350-E9, DS D.5.1; logic review L-10 2026-10-27; was 100k); 0.7 mA while EN is driven high. "
           "Fixed ref R80 = after the last auto-numbered resistor (R79), so the routed board's refs do not shift")

D.block = "pwr_mon"
res("100k", V5, "VSYS_SENSE", S, note="+5V_SYS monitor: 5.9 V -> 1.89 V at ADC0 (GPIO40); firmware logs the rail")
res("47k", "VSYS_SENSE", GND, S)
cap("100nF", "VSYS_SENSE", GND, S)
D.block = "pwr_led"
D.add("D", "Device:LED", "PWR green", "LED_SMD:LED_0603_1608Metric", S, {"A": "LED_PWR_A", "K": GND},
      mpn="KT-0603G", mfr="Hubei KENTO", LCSC="C12624")
res("1k", V3, "LED_PWR_A", S, note="3.3 V power indicator (owner 2026-10-26 diagnostic LED set)")
D.add("D", "Device:LED", "VBUS yellow", "LED_SMD:LED_0603_1608Metric", S, {"A": "LED_VBUS_A", "K": GND},
      mpn="NCD0603Y1", mfr="NationStar", LCSC="C84268", note="display-port VBUS on (owner diagnostic LED set). "
      "NationStar NCD0603Y1 (datasheet datasheets/dl/c2/NCD0603Y1.pdf p.2: pad 1 = cathode): LCSC footprint C84268 "
      "self-consistent (dot = K = silk = pad 1; coordinator QA C2 2026-10-27; KT-0603Y C2287's dot sat on the anode); "
      "extended, no basic 0603 yellow in JLC's library")
res("1.5k", VBUSH, "LED_VBUS_A", S)

# =====================================================================================================================
# SHEET mcu: RP2350B (QFN-80, 48 GPIO) per Raspberry Pi 'Hardware design with RP2350' (RP-008279), Minimal design
# RP2350B (Figure 16 / Appendix B), except the core supply (Figure 24 of the RP2350 datasheet, see block ldo1v1).
# RP2350B instead of RP2350A (coordinator / owner 2026-10-26): the A's 30 GPIOs ran out once the lane-ID DIP was added;
# the B gives the W5500 its MCU-driven RSTn / INTn back (WIZnet reference), the fault flag a GPIO, and spares.
# =====================================================================================================================
S = "mcu"
D.block = "mcu"
gpio = {f"GPIO{n}": f"NC_GPIO{n}" for n in range(40)}
gpio.update({f"GPIO{n}/ADC{n - 40}": f"NC_GPIO{n}" for n in range(40, 48)})


def g(n, net):
    key = f"GPIO{n}" if n < 40 else f"GPIO{n}/ADC{n - 40}"
    gpio[key] = net


for k, net in enumerate(("LIGHT_R", "LIGHT_G", "LIGHT_B", "LIGHT_PF")):
    g(k, net)                                         # stock GPIO0-3 = the four light outputs (colour order CONFIRM)
for b, n in BUTTON_GPIO.items():
    g(n, b)
for s_, n in SCORE_GPIO.items():
    g(n, s_)
# pin-escape map (DECISIONS #8, RP2350 datasheet Table 3 bank-0 functions checked per pin):
#   left side, top: W5500 on SPI0 = GPIO4 RX (MISO) / 5 CSn / 6 SCK / 7 TX (MOSI) (F1), INTn GPIO8, RSTn GPIO9 -> west
#   to U7 above the score / button bundle;
#   bottom right: UART0 TX GPIO28 / RX GPIO29 (F2) -> east to the CH340N; I2S (PIO, GPIOBASE 16 window) BCLK GPIO30,
#   LRCLK GPIO31 (= BCLK + 1, the pico-extras audio_i2s order), DIN GPIO32 -> east to R39-R41 / U8;
#   right side: lane-ID DIP GPIO34-37 -> east to SW3; status LED GPIO44 and the fault flag GPIO47 -> up-right.
g(47, "PWR_FAULT_N")                                   # eFuse / switch fault flag (wired-OR, open drain)
g(9, "ETH_RST_N")                                      # W5500 RSTn, MCU-driven (WIZnet reference)
g(8, "ETH_INT_N")                                      # W5500 INTn
for k in range(4):
    g(34 + k, f"LANE_ID{k}")                           # lane-ID DIP switch (owner 2026-10-26), RP2350B-only pins
g(40, "VSYS_SENSE")                                    # +5V_SYS monitor on ADC0
g(28, "UART0_TX")
g(29, "UART0_RX")
g(4, "ETH_MISO_MCU")
g(5, "ETH_CS_N")
g(6, "ETH_SCK")
g(7, "ETH_MOSI")
g(44, "LED_STATUS")
g(46, "VBUS_HOST_EN")                                  # U4 TPS2553 EN (+ R80 100k pull-down), adversarial review F08;
                                                       # Table 3 GPIO46: SIO / PWM11 A / SPI1 SCK / PIO (pin 57, next to
                                                       # the PWR_FAULT_N pin 58 lane to U4)
g(30, "I2S_BCLK_MCU")
g(31, "I2S_LRCLK_MCU")
g(32, "I2S_DIN_MCU")
pins = {"IOVDD": V3, "DVDD": V1, "VREG_AVDD": V3, "VREG_VIN": V3, "VREG_FB": GND, "VREG_PGND": GND,
        "VREG_LX": "NC_VREG_LX", "USB_OTP_VDD": V3, "QSPI_IOVDD": V3, "ADC_AVDD": V3, "GND": GND,
        "XIN": "XIN", "XOUT": "XOUT", "SWCLK": "SWCLK", "SWDIO": "SWDIO", "RUN": "RUN",
        "USB_DM": "USB_DM", "USB_DP": "USB_DP", "QSPI_SD0": "QSPI_SD0", "QSPI_SD1": "QSPI_SD1",
        "QSPI_SD2": "QSPI_SD2", "QSPI_SD3": "QSPI_SD3", "QSPI_SCLK": "QSPI_SCLK", "~{QSPI_SS}": "QSPI_SS"}
pins.update(gpio)
D.add("U", "MCU_RaspberryPi:RP2350B", "RP2350B", "Package_DFN_QFN:QFN-80-1EP_10x10mm_P0.4mm_EP3.4x3.4mm", S, pins,
      mpn="RP2350B", mfr="Raspberry Pi", LCSC="C42415655",
      note="dual Cortex-M33 150 MHz, 520 KB SRAM, 48 GPIO, USB 1.1 host/device PHY, 5 V-tolerant GPIO when IOVDD is "
           "powered. GPIO 0-29 roles kept from the stock RP2040 firmware (docs/ARCHITECTURE.md GPIO table); 30-47 "
           "= lane ID, spares, ADC")
# decoupling as Figure 16: 100 nF per IOVDD / QSPI_IOVDD / ADC_AVDD / USB_OTP_VDD group (C12-C18, C20, C21 + one),
# 100 nF per DVDD (C8, C10, C11), 4.7 uF on VREG_VIN/VREG_AVDD (Figure 24), 10 uF bulk on 3V3 (C19).
for _ in range(10):
    cap("100nF 0402", V3, GND, S, note="IOVDD x8 / QSPI_IOVDD / ADC_AVDD / USB_OTP_VDD, one per pin group (Figure 16 "
                                       "C12-C18, C20, C21)")
for _ in range(3):
    cap("100nF 0402", V1, GND, S, note="DVDD pins 10 / 32 / 51 (Figure 16 C8, C10, C11)")
cap("4.7uF 0402", V3, GND, S, note="VREG_VIN + VREG_AVDD single input capacitor (RP2350 DS Figure 24)")
cap("4.7uF 0402", V1, GND, S, note="DVDD bulk (in place of Figure 16 C7 on the regulator output)")
cap("10uF", V3, GND, S, note="Figure 16 C19")

D.block = "flash"
D.add("U", "Memory_Flash:W25Q128JVS", "W25Q128JVSIQ", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", S,
      {"~{CS}": "QSPI_SS", "DO/IO_{1}": "QSPI_SD1", "~{WP}/IO_{2}": "QSPI_SD2", "GND": GND, "DI/IO_{0}": "QSPI_SD0",
       "CLK": "QSPI_SCLK", "~{HOLD}/~{RESET}/IO_{3}": "QSPI_SD3", "VCC": V3}, mpn="W25Q128JVSIQ", mfr="Winbond",
      LCSC="C97521", note="16 MB QSPI (Figure 16 U3, same part as the stock board): code + sound bank + settings / "
                          "scores; same footprint family as the stock U2")
cap("100nF 0402", V3, GND, S, note="Figure 16 C2")

D.block = "boot"
res("1k", "QSPI_SS", "BOOTSEL_SW", S, size="0402", note="Figure 16 R6 1k (BOOTSEL)")
D.add("SW", "Switch:SW_Push", "BOOTSEL", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", S,
      {"1": "BOOTSEL_SW", "2": GND}, mpn="TS-1187A-B-A-B", mfr="XKB Connection", LCSC="C318884",
      note="replaces the stock J3 jumper (Figure 16 SW1)")
D.add("SW", "Switch:SW_Push", "RUN", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", S,
      {"1": "RUN", "2": "RUN_SW"}, mpn="TS-1187A-B-A-B", mfr="XKB Connection", LCSC="C318884",
      note="reset (Figure 16 SW2)")
res("1k", "RUN_SW", GND, S, size="0402", note="Figure 16 R4 1k")

D.block = "xosc"
D.add("Y", "Device:Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", S,
      {"1": "XIN", "3": "XOUT_X", "2": GND, "4": GND}, mpn="ABM8-272-T3", mfr="Abracon", LCSC="C20625731",
      note="Figure 16 X1: the crystal Raspberry Pi specifies (CL 10 pF, ESR 50 R)")
cap("15pF C0G", "XIN", GND, S, note="Figure 16 C3 15 pF")
cap("15pF C0G", "XOUT_X", GND, S, note="Figure 16 C4 15 pF")
res("1k", "XOUT", "XOUT_X", S, size="0402", note="Figure 16 R2 1k drive-limit on XOUT")

D.block = "swd"
D.add("J", "Connector_Generic:Conn_01x03", "SWD", "Connector_JST:JST_SH_BM03B-SRSS-TB_1x03-1MP_P1.00mm_Vertical", S,
      {"1": "SWCLK_J", "2": GND, "3": "SWDIO_J"}, mpn="BM03B-SRSS-TB(LF)(SN)", mfr="JST", LCSC="C160389",
      note="Raspberry Pi 3-pin debug connector (RP-003139-SP: 1 SC, 2 GND, 3 SD; JST SH top entry) - plugs straight "
           "into the Raspberry Pi Debug Probe. Flashing + debug")
res("100", "SWCLK", "SWCLK_J", S, size="0402", note="RP-003139-SP: 100R target-side series resistor")
res("100", "SWDIO", "SWDIO_J", S, size="0402", note="RP-003139-SP: 100R target-side series resistor")

D.block = "status"
D.add("D", "Device:LED", "STATUS green", "LED_SMD:LED_0603_1608Metric", S, {"A": "LED_STATUS_A", "K": GND},
      mpn="KT-0603G", mfr="Hubei KENTO", LCSC="C12624", note="heartbeat on GPIO44 (pin-escape map, DECISIONS #8; the stock board used GPIO27)")
res("470", "LED_STATUS", "LED_STATUS_A", S)

D.block = "laneid"
D.add("SW", "Switch:SW_DIP_x04", "LANE ID", "skeeball:SW_DIP_XKB_DSIC04LS-P", S,
      {"1": "LANE_ID0", "2": "LANE_ID1", "3": "LANE_ID2", "4": "LANE_ID3", "5": GND, "6": GND, "7": GND, "8": GND},
      mpn="DSIC04LS-P", mfr="XKB Connection", LCSC="C319038",
      note="4-position lane-ID switch (owner 2026-10-26): lane 1-4 + spares, read at boot; ON = low. 2.54 mm SMD "
           "piano-free slide type, top-actuated")
for k in range(4):
    res("10k", f"LANE_ID{k}", V3, S, note="external pull-up (does not rely on the pad pull-up / erratum E9)")

# =====================================================================================================================
# SHEET ethernet: WIZnet W5500 per 'W5500-Ref-RJ45WithMag' reference schematic v1.1 (2015-09-25) and the W5500
# datasheet v1.1.0 pin table; magjack HanRun HR911105A (default) or HR963380AE (vertical option).
# =====================================================================================================================
S = "ethernet"
D.block = "eth"
V3A = "+3V3A"
w = {"AVDD": V3A, "VDD": V3, "AGND": GND, "GND": GND, "EXRES1": "ETH_EXRES", "VBG": "NC_VBG",
     "TOCAP": "ETH_TOCAP", "1V2O": "ETH_1V2", "23": GND, "38": "NC_W38", "39": "NC_W39", "40": "NC_W40",
     "41": "NC_W41", "42": "NC_W42", "SPDLED": "NC_SPDLED", "DUPLED": "NC_DUPLED", "LINKLED": "ETH_LINKLED",
     "ACTLED": "ETH_ACTLED", "XI/CLKIN": "ETH_XI", "XO": "ETH_XO", "~{SCS}": "ETH_CS_N", "SCLK": "ETH_SCK",
     "MISO": "ETH_MISO", "MOSI": "ETH_MOSI", "~{INT}": "ETH_INT_N", "~{RST}": "ETH_RST_N", "PMODE2": "NC_PM2",
     "PMODE1": "NC_PM1", "PMODE0": "NC_PM0", "12": "NC_W12", "13": "NC_W13", "46": "NC_W46", "47": "NC_W47",
     "DNC": "NC_DNC", "TXN": "ETH_TXN", "TXP": "ETH_TXP", "RXN": "ETH_RXN", "RXP": "ETH_RXP"}
D.add("R82", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", S, {"1": V3, "2": "ETH_CS_N"},
      mpn=r_mpn("10k"), mfr="UNI-ROYAL", tolerance="1%", fixed_ref=True,
      note="ETH_CS_N pull-up (logic review L-09 2026-10-27): during MCU reset / BOOTSEL the RP2350 pad pull-down (DS "
           "9.3) would fight the W5500's internal SCSn pull-up and could leave the chip selected. Fixed ref after R81")
D.add("U", "Interface_Ethernet:W5500", "W5500", "Package_QFP:LQFP-48_7x7mm_P0.5mm", S, w, mpn="W5500", mfr="WIZnet",
      LCSC="C32843", note="hard-wired TCP/IP, 8 sockets, 10/100 PHY, SPI. Pin 23 RSVD tied to GND per the datasheet "
                          "pin table ('must be tied to GND'; the reference sheet leaves it open); 38-42 NC; PMODE "
                          "open = internal pull-ups = all-capable auto-negotiation")
D.add("FB", "Device:FerriteBead", "600R@100MHz", "Inductor_SMD:L_0805_2012Metric", S, {"1": V3, "2": V3A},
      mpn="GZ2012D601TF", mfr="Sunlord", LCSC="C1017",
      note="ref L1: digital 3V3 -> 3V3A. JLC BASIC bead 600 R at 100 MHz, 500 mA, 0.3 R (WIZnet note g: 100-2000 R is "
           "adequate; W5500 total 132 mA -> <= 40 mV drop). Swapped from the extended Murata BLM18PG221SN1D (cost pass "
           "2026-10-26)")
for _ in range(6):
    cap("100nF", V3A, GND, S, note="ref C1-C6")
cap("10uF", V3A, GND, S, note="ref C7")
cap("10uF", V3, GND, S, note="ref C11")
cap("100nF", V3, GND, S, note="ref C12")
res("12.4k", "ETH_EXRES", GND, S, note="ref R10 12.4k 1%")
cap("4.7uF 0805", "ETH_TOCAP", GND, S, note="ref C18; CL21A475KAQNNNE is X5R (not X7R)")
cap("10nF", "ETH_1V2", GND, S, note="ref C17")
res("10k", V3, "ETH_RST_N", S, note="RSTn held high while the RP2350B is in reset (pads high-Z); the MCU drives the "
                                     ">= 500 us reset pulse (W5500 DS 5.5.1) as in the WIZnet reference")
res("33", "ETH_MISO", "ETH_MISO_MCU", S, note="source termination at the W5500 driver")
D.add("Y", "Device:Crystal_GND24", "25MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", S,
      {"1": "ETH_XI", "3": "ETH_XO_X", "2": GND, "4": GND}, mpn="X322525MOB4SI", mfr="YXC", LCSC="C9006",
      note="ref Y1 25 MHz; CL 12 pF -> 18 pF caps as the reference")
cap("18pF C0G", "ETH_XI", GND, S, note="ref C14 18 pF")
cap("18pF C0G", "ETH_XO_X", GND, S, note="ref C13 18 pF")
res("0", "ETH_XO", "ETH_XO_X", S, note="ref R5 0R")
res("1M", "ETH_XI", "ETH_XO_X", S, note="ref R4 1M")
for a, b in (("ETH_TXP", "MDI_TXP"), ("ETH_TXN", "MDI_TXN"), ("ETH_RXP", "MDI_RXP"), ("ETH_RXN", "MDI_RXN")):
    res("0", a, b, S, note="ref R21-R24 damping option (0R; WIZnet note a: 33R if EMI needs it)")
res("49.9", V3A, "MDI_TXP", S, note="ref R1")
res("49.9", V3A, "MDI_TXN", S, note="ref R2")
res("10", V3A, "MDI_TCT", S, note="ref R3 10R")
cap("22nF", "MDI_TCT", GND, S, note="ref C8")
res("49.9", "MDI_RXP", "MDI_RMID", S, note="ref R6")
res("49.9", "MDI_RXN", "MDI_RMID", S, note="ref R7")
cap("10nF", "MDI_RMID", GND, S, note="ref C15")
cap("6.8nF", "MDI_RXP", "RJ_RDP", S, note="ref C9")
cap("6.8nF", "MDI_RXN", "RJ_RDN", S, note="ref C10")
res("330", "ETH_LED_G_K", "ETH_ACTLED", S, note="ref R9 330R (W5500 LED outputs sink)")
res("330", "ETH_LED_Y_K", "ETH_LINKLED", S, note="ref R8 330R")
if RJ45_OPTION == "RA":
    D.add("J", "Connector:RJ45_Hanrun_HR911105A_Horizontal", "HR911105A", "Connector_RJ:RJ45_Hanrun_HR911105A_Horizontal",
          S, {"1": "MDI_TXP", "2": "MDI_TXN", "3": "RJ_RDP", "4": "MDI_TCT", "5": "MDI_RMID", "6": "RJ_RDN",
              "7": "NC_RJ7", "8": GND, "SH": GND, "9": V3, "10": "ETH_LED_G_K", "12": V3, "11": "ETH_LED_Y_K"},
          mpn="HR911105A", mfr="HanRun", LCSC="C12074",
          note="right-angle 10/100 magjack (HanRun datasheet rev A/2: P1 TD+ P2 TD- P3 RD+ P4 TCT P5 RCT P6 RD- "
               "P8 CHS GND 'connect to PCB ground'; green LED 9->10, yellow 12->11: anode pins 9 / 12, CONFIRM at "
               "footprint review). Option V = HR963380AE vertical (PLACEMENT_PLAN)")
else:
    D.add("J", "skeeball:HR963380AE", "HR963380AE", "skeeball:RJ45_HanRun_HR963380AE_Vertical", S,
          {"1": "MDI_TXP", "2": "MDI_TXN", "3": "RJ_RDP", "4": "RJ_RDN", "5": "MDI_TCT", "6": "MDI_TCT",
           "7": "NC_TD3P", "8": "NC_TD3N", "9": "NC_TD4P", "10": "NC_TD4N", "11": "ETH_LED_Y_K", "12": V3,
           "13": "ETH_LED_G_K", "14": V3, "SH": GND},
          mpn="HR963380AE", mfr="HanRun", LCSC="C19724763",
          note="vertical magjack, common centre tap (P5/P6) on all pairs: TX and RX CTs joined (RX is AC-coupled "
               "through ref C9/C10, so the RX CT bias is free); 10/100 uses pairs 1-2 only. LEDs (HanRun rev 00 p.1): orange "
               "12 anode -> 11 cathode, green 14 anode -> 13 cathode; anodes on 3V3, cathodes to the W5500 sinks")

# =====================================================================================================================
# SHEET audio: Analog Devices / Maxim MAX98357A, datasheet 19-6779 Rev 7 'Typical Application Circuit' (p.1) and
# 'SD_MODE and Shutdown Operation' (Table 5/6, Figure 5): replaces the stock PWM -> RC -> analogue amp chain.
# =====================================================================================================================
S = "audio"
D.block = "amp"
D.add("U", "skeeball:MAX98357A_TQFN", "MAX98357AETE+T", "Package_DFN_QFN:TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm", S,
      {"DIN": "I2S_DIN", "BCLK": "I2S_BCLK", "LRCLK": "I2S_LRCLK", "GAIN_SLOT": "NC_GAIN_SLOT", "SD_MODE": "AMP_SD",
       "VDD": V5, "GND": GND, "EP": GND, "OUTP": "AMP_OUTP", "OUTN": "AMP_OUTN", "5": "NC_A5", "6": "NC_A6",
       "12": "NC_A12", "13": "NC_A13"}, mpn="MAX98357AETE+T", mfr="Analog Devices", LCSC="C910544",
      note="I2S class-D, 3.2 W into 4 R at 5 V (10 % THD), filterless, click/pop suppression. GAIN_SLOT "
           "unconnected -> 9 dB (Table 8, modest gain per owner 2026-10-26); firmware caps the digital volume. Speaker "
           "(owner photo 2026-10-26): Stetron DB20-009, Bay Tek AACE8811A, 4 R nominal, power rating unverified, 2-wire "
           "floating -> BTL output OK")
res("510k", V3, "AMP_SD", S, note="SD_MODE pull-up RLARGE for the (L+R)/2 mono mix (Table 5: B0 < VSD_MODE < B1). "
                                  "Re-centred (coordinator QA B4 2026-10-27; 680k sat 30 mV above B0 max): Electrical "
                                  "Characteristics B0 max 0.355 V, B1 typ 0.77 V (no min given), RPD 100k +-8 %; with "
                                  "+3V3 3.26-3.39 V and 1 %: VSD_MODE 0.494-0.597 V (typ 3.3 x 100k / 610k = 0.54 V), "
                                  "margins 0.14 V to B0 max and 0.17 V to B1 typ. JLC basic C23192 (Table 6's 634k is "
                                  "extended). Amp idles in standby without BCLK")
cap("10uF", V5, GND, S, note="VDD 10 uF + 0.1 uF (Typical Application Circuit)")
cap("100nF", V5, GND, S)
for _ in range(2):
    cap("220uF polymer", V5, GND, S, note="amp reservoir: with the eFuse-output 220 uF, 660 uF polymer + the 22 / 10 uF "
                                          "X5R 0805 MLCCs (~30-40 % of nominal at 5 V DC bias, QA A9 2026-10-27) "
                                          "on +5V_SYS hold a 1.2 A audio peak to ~0.15 V droop for 100 us while the "
                                          "brick's loop responds (ARCHITECTURE 5.12)")
for a, b in (("I2S_BCLK_MCU", "I2S_BCLK"), ("I2S_LRCLK_MCU", "I2S_LRCLK"), ("I2S_DIN_MCU", "I2S_DIN")):
    res("33", a, b, S, note="source termination at the RP2350 driver")
for a, b in (("AMP_OUTP", "SPK_P"), ("AMP_OUTN", "SPK_N")):
    D.add("FB", "Device:FerriteBead", "BLM21PG221SN1D", "Inductor_SMD:L_0805_2012Metric", S, {"1": a, "2": b},
          mpn="BLM21PG221SN1D", mfr="Murata", LCSC="C85840",
          note="ferrite + 1 nF output EMI filter for the speaker lead ('Filterless Class D Operation' / "
               "EMI section; the stock board has the same FB1/FB2 + C36/C37 pair); 2 A, 50 mOhm")
    cap("1nF", b, GND, S)
D.add("J", "Connector_Generic:Conn_01x02", "SPEAKER", "Connector_Molex:Molex_Mini-Fit_Jr_5569-02A2_2x01_P4.20mm_Horizontal",
      S, {str(k): v for k, v in SPEAKER_PINMAP.items()}, mpn="39300020", mfr="Molex", LCSC="C240831",
      note="HARNESS (stock J20 location + type, owner photos 2026-10-26): Mini-Fit Jr 2-circuit DUAL-ROW right-angle "
           "header 5569-02A2 (= 39-30-0020) with a snap-in peg, the two pins stacked perpendicular to the board, plug "
           "enters from the RIGHT edge. The owner's scan shows the stock part's single 3.3 mm peg hole on the pin axis "
           "7.28 mm beyond the outer pin = this variant (KiCad 5569-02A2 and LCSC C240831: 7.3 mm); the flange-mount "
           "39291028 used before has two holes 4.5 mm off-axis and is dropped. Speaker Stetron DB20-009 4 R, floating "
           "(BTL). Pins at (100.13, 48.27) / (105.67, 48.23) (scan)")

# =====================================================================================================================
# SHEET io: score inputs (J11), buttons, light drivers
# Input conditioning (same for 8 scores + 4 buttons): the score sensors are mechanical lever microswitches (owner photo
# + audible click 2026-10-26: a wire lever across each hole) closing to J11 pin 1 = GND (owner continuity). Line
# pull-up 2.2k to 3V3 = 1.5 mA wetting current through the closed contact (>= 1 mA for silver microswitch contacts),
# ESD clamp at the connector, 4.7k series + 1 nF at the MCU pin (RC 4.7 us).
# Firmware keeps the stock 10-60 ms debounce.
# =====================================================================================================================
S = "io"
D.block = "scores"
D.add("J", "Connector_Generic:Conn_01x09", "SCORE SENSORS", "Connector_PinHeader_2.54mm:PinHeader_1x09_P2.54mm_Vertical",
      S, {str(k): v + "_J" if v.startswith("SC_") else v for k, v in J11_PINMAP.items()},
      mpn="HC-PZ254-11.5L-1x9PZ", mfr="Hong Cheng", LCSC="C27985193",
      note="HARNESS (stock J11 location: score-sensor harness '25512 CE'): PLAIN unshrouded 1x9 2.54 mm vertical pin "
           "header like the stock J11 (owner 2026-10-27: the stock plug has ribbed finger-grip ears and friction-fits "
           "a plain header; the earlier KK 254 friction-lock wall did not match it, Q-48). Standard 11.5 mm pin "
           "(3.0 tail / 2.5 insulator / 6.0 mating). Square pad = pin 1 = the '*' end (owner back photo) = the "
           "switches' common = GND (owner continuity); pins 2-9 = the 8 inputs. Pads at x 48.27 .. 68.57 (pin 1 at "
           "68.6), y 65.0. Hole-to-pin order = firmware")
# The 8 score jacks across the bottom edge (owner 2026-10-26: replicate the stock board's modular jacks, labelled
# 0 10 20 30 40 50 100 100 left to right). Stock: 6P4C right-angle jacks, 4 tails each, wired to the same score lines
# as J11 (audit docs/records/stock_passives). Here: Molex 95503-2441 4P4C (JLC C3179414; the stock family, geometry
# from the owner's scan), each jack in parallel with its J11 pin, so both harness styles feed the same pull-up / ESD / RC.
# Contact map (owner continuity on the stock board, 2026-10-27, last '100' jack, read from the bottom side; jack pin n =
# contact n of the 4P4C Molex 95503-2441 = our footprint pad n): 1 = 5 V, 2 = the score line (= its J11 pin), 3 = not
# connected, 4 = GND. Matches the 2022 manual's opto sensors (black 5 V / red signal / yellow GND). 5 V comes from
# +5V_SYS (eFuse-protected); no extra protection - the stock board has none at the jacks (owner: "easy on the
# protections").
RJ11_PINMAP = {1: "+5V_JACK", 2: "SIG", 3: None, 4: GND}
# TODO-1 (owner 2026-10-27): the jack 5 V (opto sensors) through its own 0.5 A-hold PTC off +5V_SYS, so a pinched
# sensor cable trips this fuse, not the board's eFuse. Bourns MF-NSMF050-2 (datasheet: I_hold 0.50 A / I_trip 1.00 A
# at 23 C, V_max 13.2 V, I_max 100 A, R_min 0.15 / R1_max 0.70 Ohm, 1206): 8 optos ~ 8 x 20-30 mA < 0.25 A -> drop
# <= 0.18 V at R1_max.
D.add("F", "Device:Polyfuse", "0.5A hold", "Fuse:Fuse_1206_3216Metric", S, {"1": V5, "2": "+5V_JACK"},
      mpn="MF-NSMF050-2", mfr="Bourns", LCSC="C75464",
      note="score-jack +5 V PTC (TODO-1): 0.5 A hold / 1.0 A trip, 13.2 V (Bourns MF-NSMF datasheet); the eight "
           "J21-J28 contact-1 pins only")
JACK_SCORES = ["SC_GUTTER", "SC_10", "SC_20", "SC_30", "SC_40", "SC_50", "SC_100A", "SC_100B"]   # left -> right
JACK_LABELS = ["0", "10", "20", "30", "40", "50", "100", "100"]
for k, (sc, lab) in enumerate(zip(JACK_SCORES, JACK_LABELS)):
    D.add(f"J{21 + k}", "Connector_Generic:Conn_01x04", f"SCORE {lab}", "skeeball:RJ11_6P4C_TopEntry_StockPads",
          S, {str(p): (sc + "_J" if n == "SIG" else n) if n else f"NC_RJ{21 + k}_{p}" for p, n in RJ11_PINMAP.items()},
          mpn="955032441", mfr="Molex", LCSC="C588833", fixed_ref=True,
          note=f"HARNESS (stock score jack '{lab}', bottom edge): Molex 95503-2441 4P4C low-profile TOP-ENTRY jack "
               f"(JLC C588833) = the stock part: Molex SD-95503-003 (datasheets/955032661_sd.pdf) body '95003', mfg ID "
               f"'MXCH' as on the stock jacks; 4 POS: 11.18 wide, posts 7.62 apart 4.96 behind the front face, tails "
               f"6.35 / 8.89 behind the posts = the scanned stock pads (Q-46); plug from above (owner 2026-10-27); in "
               f"parallel with J11 ({sc}); contacts 1 = +5V_JACK (+5V_SYS via the 0.5 A PTC), 2 = score, 3 = NC, 4 = GND (owner continuity 2026-10-27)")
lines = [s + "_J" for s in SCORES] + [b + "_J" for b in BUTTONS]
esd_ch = ["IO1", "IO2", "IO3", "IO4", "IO5"]
for i in range(3):
    chunk = lines[i * 5:(i + 1) * 5]
    pins_ = {"GND": GND}
    for k, ch in enumerate(esd_ch):
        pins_[ch] = chunk[k] if k < len(chunk) else f"NC_ESD{i + 1}_{k + 1}"
    D.add("U", "Power_Protection:ESDA6V1-5SC6", "ESDA6V1-5SC6", "Package_TO_SOT_SMD:SOT-23-6", S, pins_,
          mpn="ESDA6V1-5SC6", mfr="STMicroelectronics", LCSC="C6650",
          note="5-line TVS array at the harness pins (VBR 6.1 V min, IEC 61000-4-2 level 4)")
for s_ in SCORES:
    res("2.2k", s_ + "_J", V3, S, note="line pull-up: 1.5 mA contact wetting current")
    res("4.7k", s_ + "_J", s_, S, note="series: pad-current limit + RC")
    cap("1nF", s_, GND, S)

D.block = "buttons"
D.add("J", "Connector_Generic:Conn_02x04_Odd_Even", "BUTTONS", "Connector_Molex:Molex_Mini-Fit_Jr_5566-08A_2x04_P4.20mm_Vertical",
      S, {str(k): (v + "_J" if v.startswith("BTN_") else v) for k, v in BUTTONS_PINMAP.items()},
      mpn="39281083", mfr="Molex", LCSC="C293503",
      note="HARNESS (stock 'Buttons' location): Mini-Fit Jr 2x4 vertical 5566-08A (= 39-28-1083), owner-confirmed "
           "2026-10-26; plug from above. Latch-side row = GND x4, other row = the 4 button inputs (owner continuity); "
           "row-to-pin-number check at layout; position photo +-1 mm")
for b in BUTTONS:
    res("2.2k", b + "_J", V3, S)
    res("4.7k", b + "_J", b, S)
    cap("1nF", b, GND, S)

D.block = "lights"
# Low-side N-MOSFET per channel (stock: two dual FETs FET1/FET2). AO3416: 20 V, RDS(on) <= 26 mOhm at VGS 2.5 V
# (<= 22 mOhm at 4.5 V; AOS datasheet Rev 5.1), so the 3.3 V GPIO fully enhances it. Channel budget 2 A (firmware cap per
# channel; current_budget LED_*_K, adversarial review F05 2026-10-27: the earlier "~3 A per channel" and "drain copper
# pour" claims are withdrawn - the drains run on 1.0-1.2 mm F.Cu tracks): ~32 mOhm hot x 4 A^2 = 0.13 W per FET.
# AO3400A (48 mOhm at 2.5 V) would be ~0.2 W at 2 A and 0.6 W at 3 A.
# PWM dimming / colour mixing of the EXISTING strips (owner 2026-10-26): GPIO0-3 = PWM slices 0A/0B/1A/1B; Qg ~10 nC
# through 100 R from a 12 mA pad switches in ~1 us, < 0.5 % of a 5 kHz period - negligible switching loss.
for ch, kn in (("LIGHT_R", "LED_R_K"), ("LIGHT_G", "LED_G_K"), ("LIGHT_B", "LED_B_K"), ("LIGHT_PF", "LED_PF_K")):
    D.add("Q", "Transistor_FET:Q_NMOS_GSD", "AO3416", "Package_TO_SOT_SMD:SOT-23", S,
          {"G": ch + "_G", "S": GND, "D": kn}, mpn="AO3416", mfr="Alpha & Omega", LCSC="C43307",
          note="light low-side switch, >= 3 A per channel (owner light loads 2026-10-26); SOT-23 pinout G1 S2 D3")
    res("100", ch, ch + "_G", S, note="gate series")
    res("4.7k", ch + "_G", GND, S, note="gate pull-down: light off while the MCU is in reset; 4.7k (<= 8.2k, RP2350-E9 "
                                         "DS D.5.1, logic review L-10 2026-10-27; was 10k): a pin left as an input with "
                                         "IE set cannot half-enhance the AO3416 (Vth 0.4-1.1 V); 0.7 mA while driven")
D.add("J", "Connector_Generic:Conn_01x04", "RGB LIGHTS", "skeeball:Molex_Mini-Fit_Jr_39-30-1049_1x04_P4.20mm_Vertical",
      S, {str(k): v for k, v in RGB_PINMAP.items()}, mpn="39301049", mfr="Molex", LCSC="C587488",
      note="HARNESS (stock 'RGB Lights' location): Molex Mini-Fit Jr SINGLE-ROW 1x4 vertical header 39-30-1049 with "
           "snap-in peg board locks (JLC C587488; the scan's two filled peg holes match its diagonal pegs). Pin 1 "
           "(leftmost, square pad, black wire) = +5 V strip common (owner continuity 2026-10-26); pins 2-4 = R / G / B "
           "low side, order set in firmware. Pads at x 3.6 .. 16.2, y 37.85 (scan). Strips run on 5 V. Common fed "
           "through its own 5 A PTC (+5V_RGB). JLC-placed (the earlier owner-fitted route assumed JLC had none)")
D.add("J", "Connector_Generic:Conn_01x02", "PLAYFIELD LIGHTS", "Connector_Molex:Molex_KK-396_A-41791-0002_1x02_P3.96mm_Vertical",
      S, {str(k): v for k, v in PLAYFIELD_PINMAP.items()}, mpn="26604020", mfr="Molex", LCSC="C505042",
      note="HARNESS (stock 'Playfield Lights' location): Molex KK 396 2-circuit VERTICAL friction-lock header "
           "26-60-4020 (A-41791-0002; JLC C505042; owner calipers 2026-10-26: 3.96 pitch, 1.14 square pins); the plug "
           "seats from above, friction-ramp wall on the inboard side (owner photo image4 + owner 2026-10-27: 'clearly "
           "vertical' - the earlier right-angle 26-60-5020 was wrong). Lower pin = +5 V strip common, upper pin = FET "
           "channel (owner continuity). Pads 3.96 apart about the scanned midpoint (4.63, 13.43)")

# =====================================================================================================================
# SHEET usb: display host port (micro-B, stock J18 location) + USB-C debug console (CH340N)
# Host port: Hardware design with RP2350 Figure 15 (R7/R8 27R series at the RP2350) + ST USBLC6-2 at the connector.
# Debug port: WCH CH340 datasheet V3C sections 4 + 7 (VCC = V3 = 3.3 V, 0.1 uF each; UD+/UD- direct, no series R)
# + USB-C sink CC 5.1k.
# =====================================================================================================================
S = "usb"
D.block = "usbhost"
D.add("J", "skeeball:USB_B_Micro_Host", "DISPLAY USB", "Connector_USB:USB_Micro-B_Amphenol_10118194-0001LF_Horizontal", S,
      {"VBUS": VBUSH, "D-": "USBH_DM_C", "D+": "USBH_DP_C", "ID": "NC_USBH_ID", "GND": GND, "SH": GND},
      mpn="10118194-0001LF", mfr="Amphenol ICC", LCSC="C132563",
      note="HARNESS (stock J18 location): the display cable's micro-B plug; this board is the USB HOST "
           "(display = HID device VID 0xB337 / PID 0x00EF). Receptacle type CONFIRM vs the stock part (M-C7)")
D.add("U", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", S,
      {"1": "USBH_DM_C", "6": "USBH_DM_C", "3": "USBH_DP_C", "4": "USBH_DP_C", "5": VBUSH, "2": GND},
      mpn="USBLC6-2SC6", mfr="STMicroelectronics", LCSC="C7519", note="ESD at the connector")
res("27", "USBH_DM_C", "USB_DM", S, note="Figure 16 R8 27R, close to the RP2350 (0603: the 0603 part is JLC "
                                           "preferred, the 0402 one extended; cost pass 2026-10-26)")
res("27", "USBH_DP_C", "USB_DP", S, note="Figure 16 R7 27R, close to the RP2350 (0603, see R8)")

D.block = "usbdbg"
D.add("J", "Connector:USB_C_Receptacle_USB2.0_16P", "DEBUG USB-C", "skeeball:USB_C_Receptacle_HRO_TYPE-C-31-D-15_Vertical",
      S, {"A4": "VBUS_DBG", "A9": "VBUS_DBG", "B4": "VBUS_DBG", "B9": "VBUS_DBG", "A1": GND, "A12": GND, "B1": GND,
          "B12": GND, "SH": GND, "A5": "DBG_CC1", "B5": "DBG_CC2", "A6": "DBG_DP", "B6": "DBG_DP",
          "A7": "DBG_DM", "B7": "DBG_DM", "A8": "NC_SBU1", "B8": "NC_SBU2"},
      mpn="TYPE-C-31-D-15", mfr="Korean Hroparts", LCSC="C22464480",
      note="vertical (top-entry) 16-pin USB 2.0 receptacle (owner 2026-10-26), HRO TYPE-C-31-D-15 (8.8 mm tall; "
           "drawing datasheets/dl/j10/C22464480.pdf, 2023-10-27): 4 shell legs 0.90 x 0.30 x 2.20 +-0.25 pass the "
           "1.6 mm board (real THT joint; coordinator QA D1 2026-10-27, DECISIONS #11 - the D-06 legs stopped inside "
           "the slots). JLC has no LCSC footprint for C22464480 (EasyEDA API 404): CPL confirm-in-preview row. "
           "Device / sink: VBUS_DBG powers "
           "nothing on the board (no back-feed); the CH340N runs from +3V3, so the port enumerates while the board is "
           "powered")
res("5.1k", "DBG_CC1", GND, S, note="UFP Rd 5.1k (USB Type-C spec)")
res("5.1k", "DBG_CC2", GND, S, note="UFP Rd 5.1k")
D.add("U", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", S,
      {"1": "DBG_DM", "6": "DBG_DM", "3": "DBG_DP", "4": "DBG_DP", "5": "VBUS_DBG", "2": GND},
      mpn="USBLC6-2SC6", mfr="STMicroelectronics", LCSC="C7519")
D.add("U", "Interface_USB:CH340N", "CH340N", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", S,
      {"VCC": V3, "V3": V3, "GND": GND, "UD+": "DBG_DP", "UD-": "DBG_DM", "TXD": "CH_TXD", "RXD": "CH_RXD",
       "~{RTS}": "NC_RTS"},
      mpn="CH340N", mfr="WCH", LCSC="C2977777",
      note="USB-UART console (RP2350 has one USB controller, used as host). SOP-8, internal clock; 3.3 V mode: V3 "
           "tied to VCC (CH340 DS section 4 pin table). CH340N, not CH340C: JLC lists its CH340C stock as 'no longer "
           "manufactured' / not buyable (2026-10-26). Flashing stays on SWD (+ the RP2350 USB bootloader on the "
           "display port)")
cap("100nF", V3, GND, S, note="CH340 DS 7: C9 0.1 uF VCC")
cap("100nF", V3, GND, S, note="CH340 DS 7: C8 0.1 uF V3")
res("100", "CH_TXD", "UART0_RX", S, note="series, at the CH340N")
res("100", "UART0_TX", "CH_RXD", S, note="series, at the RP2350")

# =====================================================================================================================
# Mechanical: the four corner mounting holes at the stock positions (owner 2026-10-26; MEASURE: M-H1). Netless.
# =====================================================================================================================
S = "power"
D.block = "mech"
for hname in ("H1 TL", "H2 TR", "H3 BR", "H4 BL"):
    D.add("H", "Mechanical:MountingHole", hname.split()[0], "skeeball:MountingHole_3.57mm", S, {},
          note=f"stock {hname.split()[1]} corner hole for the nylon stand-off stud: centres 3.885 mm from the short (left / "
               "right) edges and 3.585 mm from the long edges, "
               "3.57 mm (9/64 in) drill (owner measurements 2026-10-26). Only the 4 corner holes are used")


if __name__ == "__main__":
    issues = D.check()
    print(f"{len(D.parts)} parts, {len(D.nets())} nets, {len(issues)} structural issues")
    for i in issues:
        print("  ", i)
