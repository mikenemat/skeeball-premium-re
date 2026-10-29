# SBC-1 - Skee-Ball lane controller: requirements, architecture and design decisions

Drop-in replacement for the Bay Tek main board **A5CB25502 Rev 2.2** in the owner's four Skee-Ball Home Arcade
Premium machines, adding wired Ethernet so the lanes can be networked (shared high scores, synced start, multi-lane
play). Internal project (owner's home arcade). Status 2026-10-26: **schematic + parts done; outline + holes measured and drawn; connector positions photo +-1 mm (good
enough to place); open: J11 pitch, Playfield pitch, the single-row 4.2 mm header sourcing** (`docs/MEASUREMENTS_NEEDED.md`).

Design of record: `scripts/design.py` (every part, value, MPN, LCSC code and net, with the reference each block
follows). Schematic: `hardware/main/skeeball-controller.kicad_sch` (generated; ERC clean, netlist == design).
BOM: `bom/bom.json` (`docs/ORDERING.md`). Placement: `docs/PLACEMENT_PLAN.md`.

## 1. Requirements

| # | Requirement | Source | Status |
|---|---|---|---|
| R-1 | Same game functionality as the stock hardware: 8 score inputs, 4 buttons, RGB + playfield lights, speaker, display link | owner | designed |
| R-1a | Single-sided assembly like the stock board (keeps JLC cost down); two-sided allowed only if the outline needs it | owner 2026-10-26 | planned single-sided |
| R-2 | Same location for every connector the harness uses: power, Buttons, RGB Lights, Playfield Lights, Speaker, display micro-USB, J11 score header | owner | positions = photo +-1 mm anchored on the measured holes (acceptable, cables float); exact pad positions from the requested 600 dpi scan |
| R-3 | Board outline identical to the stock board; the four corner mounting holes (nylon stand-off studs) at their exact stock positions, the stock inner holes dropped; added parts never grow the board | owner 2026-10-26 | **measured**: 116.68 x 85.73 mm, holes 3.57 mm at 3.97 mm in; drawn in the board file |
| R-4 | Wired Ethernet. **No PoE** (not designed, costed or footprinted) | owner 2026-10-26 | designed (W5500) |
| R-5 | The 8 modular jacks and every unpopulated stock footprint (J2, J5, J7, J19) are removed; the score harness is J5 (stock J11), a PLAIN 1x9 2.54 mm vertical pin header like stock (owner 2026-10-27; the friction-lock pick was wrong) | owner 2026-10-26 / 2026-10-27 | done |
| R-6 | Every part 100 % in JLCPCB stock, checked live and dated (5-board run) | owner 2026-10-26 | done (section 7) |
| R-7 | RJ45: **zone a (stock model-number silk area), vertical jack with integrated magnetics + LEDs** - owner decision 2026-10-26 after the 2 x 2 study | owner 2026-10-26 | designed (HanRun HR963380AE) |
| R-8 | USB-C debug / programming port, **vertical** receptacle, device role, 5.1 k CC pull-downs | owner 2026-10-26 | designed (CH340N console) |
| R-9 | Every IC block follows its vendor reference design; deviations written down | owner 2026-10-26 | section 5 |
| R-10 | MCU = RP2350 + external QSPI flash + WIZnet W5500; **RP2350B (QFN-80, 48 GPIO)** after the GPIO count ran out on the A (coordinator follow-up 2026-10-26) | owner decision 2026-10-26 | designed |
| R-11 | Diagnostic LEDs (3.3 V power, heartbeat, Ethernet link / activity, USB VBUS on) and RESET + BOOTSEL buttons, reachable installed | owner 2026-10-26 | designed (+ FAULT LED) |
| R-12 | 4-position lane-ID DIP switch read by firmware | owner 2026-10-26 | designed |
| R-13 | PWM-capable light channels for the existing strips only (no addressable output, no extra light hardware) | owner 2026-10-26 | designed |
| R-14 | Protected sensor 5 V and light-strip supply (cheap: polyfuse or current-limited switch) | owner 2026-10-26 | designed: one PTC per light harness; sensor 5 V not needed (mechanical switches, M-E3) |
| R-15 | No reverse-polarity circuit (polarised connector); keep the TVS. No expansion header | owner 2026-10-26 | done |
| R-16 | 16 MB QSPI flash (W25Q128JV family); MAC address from the RP2350 unique ID (no MAC EEPROM) | owner 2026-10-26 | done / firmware |
| R-17 | ~~Labelled test points on every rail and on W5500 SPI, USB D+/D-, I2S, UART0~~ REMOVED: no test points (owner 2026-10-27) | owner 2026-10-26 / 2026-10-27 | removed |
| R-18 | Aluminium electrolytics replaced by polymer / MLCC; similar component-quality upgrades noted | owner 2026-10-26 | section 5.13 |

## 2. I/O and GPIO map

Stock GPIO roles are from the lane-1 firmware dump (`skeeball-board/analysis/FIRMWARE_FINDINGS.md`). **2026-10-27
(owner, DECISIONS #8): the firmware is an original implementation, so SBC-1 no longer keeps the stock roles** - the GPIO
column below is the PCB pin-escape map (each group leaves the RP2350B on the side facing its destination, in the order
of its destination), checked per pin against RP2350 datasheet Table 3 (bank-0 functions).

| Function | Harness connector (kept at the stock spot) | Stock GPIO | SBC-1 GPIO / net | Conditioning |
|---|---|---|---|---|
| Score: gutter (0) | J5 pin 2 (stock J11; plain 1x9 2.54 mm header, **pin 1 = square pad = '*' = GND common**, pins 2-9 = inputs) | 9 | GPIO21 `SC_GUTTER` | 2.2 k pull-up to 3V3 at the pin (1.5 mA wetting), ESD array, 4.7 k series + 1 nF at the MCU |
| Score: 10 / 20 / 30 / 40 / 50 | J5 pins 3-7 | 10-14 | GPIO20 / 19 / 18 / 17 / 16 `SC_10` / `SC_20` / `SC_30` / `SC_40` / `SC_50` | same |
| Score: 100 A / 100 B | J5 pins 8-9 | 15 / 18 | GPIO15 `SC_100A` / GPIO14 `SC_100B` | same |
| J5 common | J5 pin 1 | - | GND (owner continuity 2026-10-26; J5 carries no 5 V) | the sensors are mechanical lever microswitches (owner 2026-10-26): no sensor 5 V, the +5V_SENS switch is removed |
| START, VOLUME, GAME, PLAYERS | Buttons 2x4 Mini-Fit Jr: latch-side row = GND x4, other row = the 4 signals (owner continuity) | 4, 5, 6, 8 | GPIO10 / 11 / 12 / 13 (`BTN_START`, `BTN_B/C/D`; order CONFIRM) | same as the scores |
| RGB strip R / G / B (common anode: pin 1 = +5 V, owner continuity) | RGB Lights 1x4, pin 1 = leftmost / square pad | 0-3 (on/off) | GPIO0-2, PWM 0A/0B/1A | AO3416 low side, 100 R gate, 10 k pull-down; common via 5 A PTC; Molex Mini-Fit Jr 39-30-1049 |
| Playfield strip | Playfield Lights 2-pin, lower pin = +5 V (owner continuity) | (one of 0-3) | GPIO3, PWM 1B | same |
| Speaker 3.5-4 R | SPEAKER J4 (stock J20) 2-pin | 28 (PWM audio) | I2S (PIO, GPIOBASE 16): GPIO30 BCLK, GPIO31 LRCLK (= BCLK + 1), GPIO32 DIN | MAX98357A, BTL, ferrite + 1 nF filter |
| Display (USB HID device 0xB337:0x00EF) | micro-USB J18 | native USB (host) | RP2350 USB, host mode | 27 R series, USBLC6, TPS2553 VBUS 0.5 A |
| Status LED | - | 27 (heartbeat; stock firmware analysis) | GPIO44 heartbeat | - |
| Ethernet (new) | RJ45 (zone a or b) | - | SPI0 (F1): GPIO4 MISO (RX), 5 CSn, 6 SCK, 7 MOSI (TX); GPIO9 RSTn, GPIO8 INTn | W5500 per the WIZnet reference (MCU-driven reset + interrupt) |
| Debug console (new) | USB-C vertical | - | UART0 (F2): GPIO28 TX, GPIO29 RX | CH340N, 100 R series |
| Lane ID (new) | DIP x4 | - | GPIO34-37 (RP2350B-only pins) | 10 k pull-ups, switch to GND |
| Power fault flag (new) | - | - | GPIO47 `PWR_FAULT_N` | wired-OR open drain from the eFuse + the VBUS TPS2553; also drives the FAULT LED |
| +5V_SYS monitor (new) | - | - | GPIO40 / ADC0 | 100 k / 47 k divider, 100 nF |
| Display VBUS enable (new, 2026-10-27) | - | - | GPIO46 `VBUS_HOST_EN` (Table 3: SIO / PWM11 A / SPI1 SCK / PIO) | U4 TPS2553 EN, R80 100 k pull-down: VBUS_HOST off through reset / BOOTSEL until firmware drives GPIO46 high (adversarial review F08) |
| Spares | - | - | - (test points removed, Q-51) | GPIO22-27, 33, 38, 39, 41-43, 45 unconnected |
| Flash / debug | - | QSPI, SWD | QSPI (16 MB), SWD on JST SH | Raspberry Pi 3-pin debug connector |

38 of the RP2350B's 48 GPIOs are used (GPIO46 VBUS_HOST_EN added 2026-10-27) (GPIO 0-29 exactly as the stock RP2040 firmware expects, 30-40 for the
additions); the first RP2350A draft had run out of pins and had pushed the W5500 reset / interrupt and the fault flag
into hardware - DECISIONS #1, resolved by the RP2350B.

## 3. MCU / Ethernet comparison (owner chose A on 2026-10-26)

Capabilities verified from manufacturer documents in `datasheets/dl/` (RP2350 datasheet; ST STM32F405/407 datasheet;
WCH's CH32V307 README on its official GitHub; Espressif ESP32-S3 / ESP32 / ESP32-P4 datasheets; WIZnet W5500 datasheet).
Prices: JLC assembly price at 5 boards, `docs/records/mcu_survey/survey.json` (2026-10-26).

| | **A RP2350B + W5500 + W25Q128 (chosen)** | B STM32F407VG + LAN8720A | C CH32V307 | D ESP32-S3 module + W5500 | E W55RP20 |
|---|---|---|---|---|---|
| (1) USB host for the display | yes: 'USB 1.1 controller and PHY, with host and device support'; host pull-downs internal. The stock firmware already drives this display with TinyUSB host on the RP2040 | yes: OTG FS 'device/host/OTG' with on-chip PHY | yes: USB 2.0 FS OTG + HS host/device | yes: 'Full-speed USB OTG' | yes (RP2040 inside) |
| (2) Ethernet | SPI controller with hard-wired TCP/IP + 10/100 PHY; offloads the stack; ~$2.8 | MAC on chip + external RMII PHY (50 MHz ref, more routing) | MAC + **10 Mbit-only** integrated PHY (100M PHY only on CH32V317) | none on chip, so W5500 again | integrated W5500 |
| (3) 5 V inputs | GPIO tolerate 5.5 V when IOVDD is powered (DS table 1673) | 5 V-tolerant FT pins (most) | some pins FT | **not** 5 V tolerant: dividers needed | RP2040: not 5 V tolerant |
| (4) Sound storage | external 16 MB QSPI (XIP) | 1 MB internal + external flash needed | 256 KB internal + external flash needed | 16 MB in module | **2 MB only** (sound bank alone ~1.3 MB) |
| (5) Software for us | Pico SDK + TinyUSB host (what the stock firmware uses) + WIZnet ioLibrary; SWD with the Raspberry Pi Debug Probe; A/B OTA partitions in the boot ROM | STM32Cube + lwIP + TinyUSB; mature | MounRiver / WCH EVT, smaller community, closed WCHNET stack | ESP-IDF USB host + esp_eth W5500; Wi-Fi bonus | Pico SDK |
| GPIO count vs the 37 needed | 48 (QFN-80 10 x 10 mm); the RP2350A's 30 were 7 short | 82 | 80 | ~33 usable on the module | 30 (RP2040) |
| (6) Core chip cost (5 pcs), JLC stock | $8.42 incl. flash + jack; RP2350B 3,477 (RP2350A 5,711, same price) | $7.66 + external flash ($2.58) + 50 MHz clock; F407 3,483 | $7.72 incl. flash + jack; 1,637 | $9.91; 23,692 | $11.11; **stock 0** |
| Second USB for a debug port | no (single controller) - CH340N console + SWD | yes (OTG HS) | yes | yes (USB-Serial/JTAG) | no |
| Verdict | **chosen** (B package): keeps the stock pin roles and the proven TinyUSB host path; 5 V-tolerant inputs; cheapest robust Ethernet; enough pins for every addition | runner-up: native MAC + second USB, but RMII layout, external flash anyway, not pin-compatible with the stock firmware | 10 Mbit + weaker toolchain | needs input dividers; no reuse of the stock firmware | out of stock; 2 MB too small |

ESP32 (classic): has an EMAC but no USB OTG at all (its datasheet lists no USB peripheral), so it fails criterion 1.
ESP32-P4: EMAC (external PHY) + USB 2.0 OTG, but a much larger power / package design for no gain here.
The USB-C debug port was weighed as one factor (owner); it favours B / D but did not outweigh the rest.

## 4. Architecture

```
5 V PSU -> PWR header -> SMBJ5.0A TVS -+-> 2920 PTC 5 A -> +5V_RGB -> RGB strip common (3 x AO3416 low side, PWM)
                                       +-> 1812 PTC 3 A -> +5V_PF -> playfield bar common (1 x AO3416 low side, PWM)
                                       +-> TPS259531 eFuse (3 A limit, 5.7 V OV clamp, UVLO 3.75 V typ, soft start) -> +5V_SYS
+5V_SYS -> TLV62569 buck -> +3V3 -> TLV74311 LDO -> +1V1 (RP2350 DVDD)
        -> TPS2553 0.5 A -> VBUS_HOST (display micro-USB)
        -> MAX98357A I2S class-D -> speaker
RP2350B --QSPI-- W25Q128 16 MB | --SPI0 + RSTn/INTn-- W5500 -- HR963380AE vertical magjack (zone a) | --USB host-- display
        --UART0-- CH340N -- vertical USB-C (console) | --SWD-- JST SH | 8 score + 4 button inputs (ESD + RC)
        lane-ID DIP, RESET, BOOTSEL, LEDs (PWR, FAULT, VBUS, STATUS, jack LINK/ACT)
```

4-layer, 1.6 mm, JLC04161H-7628 (DECISIONS #7; stock is 2-layer, no bottom parts); single-sided SMT assembly; THT
harness connectors.

## 5. Block decisions, references and deviations

### 5.1 Power input and protection
- **Input header**: pin 1 = 5 V, pin 2 not connected, pin 3 = GND (owner continuity 2026-10-26).
- **TVS** SMBJ5.0A (Littelfuse) across the input, ahead of the eFuse. Kept per owner (R-15); no reverse-polarity stage.
- **eFuse TPS259531DSGR** - TI SLVSE57C section 9.2 Typical Application: CIN 0.1 uF, EN/UVLO divider (100 k / 47 k:
  rising typ 3.75 V, worst case 3.48-4.04 V with VUVLO(R) 1.13-1.27 V, 1 % parts and the 0.1 uA EN leakage; falling
  3.17-3.72 V; was 100 k / 39 k = 4.60 V worst case = the LPV-60-5's -8 % output floor, adversarial review F04
  2026-10-27; every +5V_SYS load runs from 2.5 V), CdVdt 47 nF (Eq. 3: 0.89 V/ms, ~0.54 A inrush into ~0.6 mF), RILM 680 R (~3.0 A; datasheet points
  487 R -> 4.17 A, 1780 R -> 1.17 A), FLT open drain. Why: the stock board has no input protection; a failing brick or a
  short now trips the eFuse instead of the traces. Over-voltage: +5V_SYS follows +5V_IN up to the OV threshold
  (VOVC 5.5-5.9 V) and is clamped to 5.2-5.7 V above it, so a supply fault can put up to 5.9 V on +5V_SYS (above
  the TLV62569 / MAX98357A 5.5 V recommended maximum, under their 6.0 V absolute maximum; q6 QA A9 - was
  '<= 5.7 V'). Reversed input: the TVS is the only measure (owner R-15); the Mini-Fit Jr keying limits the risk.
- **Light rails** (owner loads 2026-10-26, section 5.13): one high-side PTC per light harness, so each also covers a
  channel wire shorted to its strip's +5 V. RGB common: Littelfuse 2920L500/16MR, 5 A hold / 10 A trip, 25 mOhm max
  (Littelfuse derating, reference data: hold 4.15 A at 40 C, 3.75 A at 50 C, 3.30 A at 60 C - the earlier "4.2 A at
  50 C" read the 40 C column, adversarial review F03; the Littelfuse table reads 4.25 / 3.88 / 3.50 A - the lower set is
  used) -> **firmware RGB cap 3.3 A RMS at <= 50 C local ambient** (q6 QA A9; the owner can raise it in firmware)
  (RMS = I_on x sqrt(duty) per channel, summed over the common); the PTC is not upsized (a larger PTC worsens the
  short-circuit coordination with the 8 A supply). Coordination (power review P4): a hard short is limited by the
  LPV-60-5's hiccup (8.8-12 A) before F1 trips; F1 covers sustained overloads between hold and the supply limit
  (owner decision O2 open). Trunk J1 -> F1 / F2 (q6): B.Cu + In2.Cu pours, connectivity-aware min cut 4.58 mm 1 oz
  equivalent at the J1.1 thermal spokes (5.70 mm along the trunk), In2 carries ~1/3 of the current. Playfield common: Littelfuse 1812L300MR, 3 A hold / 5 A trip
  (2 x the 1.5 A bar). Lights bypass the eFuse so a strip inrush cannot brown out the logic.
- **Bulk**: polymer aluminium 220 uF 10 V (Lelon OVZ, 2000 h at 105 C): 1 on +5V_RGB (+ 10 uF; 10 uF on +5V_PF), 1 at the eFuse output and 2
  at the amplifier (sized in 5.12), plus MLCCs. Replaces the stock aluminium electrolytics (owner direction).

### 5.2 Rails
- **3.3 V: TLV62569 buck** - TI SLVSDG1C section 8.2 Figure 5: C1 4.7 uF, L 2.2 uH 4x4 mm (Sunlord SWPA4030), C2 10 uF,
  R1 100 k / R2 22 k (3.327 V), C3 15 pF feed-forward. Deviation: divider and C3 values rescaled to JLC basic parts with
  the same R1 x C3 time constant as Figure 5 (1.5 us vs 1.36 us). Why a buck: the stock NCP1117 LDO would burn ~0.6 W at
  the new 0.35 A load (W5500 alone is 132 mA, its DS 5.4).
- **1.1 V: TLV74311P LDO** for RP2350 DVDD - RP2350 datasheet 'External core supply with on-chip regulator disabled'
  (Figure 24): VREG_VIN + VREG_AVDD on 3.3 V with one 4.7 uF, VREG_FB to GND, no inductor. **Deviation from the
  Minimal design's internal switcher**, reason: its only qualified inductor (Abracon AOTA-B201610S3R3-101-T, C42411119)
  has JLC stock **1** (2026-10-26), and Raspberry Pi warn that other 0806 inductors are 'at your own risk' (polarity).
  TLV74311: 1.1 V +-1.4 % = 1.085-1.115 V inside the DVDD range 1.05-1.16 V.

### 5.3 RP2350B core - Raspberry Pi 'Hardware design with RP2350', Minimal design RP2350B (Figure 16 / Appendix B)
Followed: 100 nF per IOVDD / QSPI_IOVDD / ADC_AVDD / USB_OTP_VDD (C12-C18, C20, C21), 100 nF per DVDD (C8/C10/C11), 10 uF on 3V3
(C19), W25Q128JVS on QSPI with 100 nF (U3, C2), ABM8-272-T3 12 MHz with 15 pF + 1 k on XOUT (X1, C3, C4, R2), BOOTSEL =
1 k from QSPI_SS to a switch (R6, SW1), RUN switch with 1 k (SW2, R4), 27 R on USB_DP/DM at the chip (R7, R8), 0402
decoupling at the pins. Layout rules of section 2 (QSPI short and matched, crystal tight, decoupling at the pins) apply
at layout. Deviations: core supply (5.2); SWD on the Raspberry Pi 3-pin JST SH with the specified 100 R target
resistors (RP-003139-SP) instead of the header J4; RP2350 GPIO 5 V tolerance is used for the inputs (5.9). Package:
RP2350B QFN-80 (JLC C42415655, 3,477 in stock at $1.28 on 2026-10-26, same price as the A) - the A's 30 GPIOs were 7 short.

### 5.4 Boot, programming, debug
- RESET + BOOTSEL tactile switches (XKB TS-1187A) replace the stock J3 jumper. **Programming and recovery = SWD (J2)**
  (adversarial review F08, 2026-10-27). The USB bootloader on the display port J9 (BOOTSEL + RESET, a PC cable instead of
  the display cable) is usable only because U4's EN is now GPIO46 with a 100 k pull-down: after a RUN-pin reset the
  pad is Hi-Z / pulled low (RP2350 DS 9.3), so VBUS_HOST stays off and the board never sources VBUS into the PC. A
  software reboot into BOOTSEL keeps GPIO46's last level in the pad isolation latches (DS 9.7) -> firmware drives
  GPIO46 low before `reset_usb_boot()`. J10 (CH340N console) has no VBUS qualification of its pull-up: use it only with
  a powered PC / hub and unplug it when the host is off.
- SWD: Raspberry Pi 3-pin debug connector (JST BM03B-SRSS-TB, top entry) = the Debug Probe plugs straight in.
- Field updates: over Ethernet into the RP2350's A/B flash partitions (boot ROM feature), SWD as the fallback.

### 5.5 Ethernet - WIZnet 'W5500-Ref-RJ45WithMag' v1.1 + W5500 datasheet v1.1.0
Followed: 3V3 -> ferrite -> 3V3A with 6 x 100 nF + 10 uF, 10 uF + 100 nF on VDD, EXRES1 12.4 k 1 %, TOCAP 4.7 uF, 1V2O
10 nF, 25 MHz crystal with 0 R + 1 M + 2 x 18 pF (YXC X322525MOB4SI, CL 12 pF), TX 49.9 R to 3V3A + TCT 10 R / 22 nF, RX
6.8 nF AC coupling + 2 x 49.9 R to a 10 nF midpoint on RCT, 0 R damping positions (33 R if EMI needs), 330 R LED
resistors, PMODE open (all-capable auto-negotiation), **RSTn and INTn driven / read by the MCU** (GPIO9 / GPIO8, DECISIONS #8; a 10 k
pull-up keeps RSTn high while the RP2350B pads are high-Z in reset). Deviations: **RSVD pin 23 tied to GND** (the
datasheet pin table says 'must be tied to GND'; the reference sheet leaves it open); magjack = **HanRun HR963380AE
vertical** (owner pick: 1CT:1CT magnetics, Bob-Smith network, 2 LEDs; its single common centre tap P5/P6 serves both
pairs - acceptable because the RX side is AC-coupled through C9/C10 as in the reference, so only the TX tap carries the
3V3A bias); bead FB1 = Sunlord GZ2012D601TF 600 R (JLC basic; WIZnet note g allows 100-2000 R) instead of the
reference's 120 R HH-1M1608-121JT. **Stock watch:** HR963380AE had 154 pieces at JLC on 2026-10-26 (enough for the
5-board run ~20x over; reserve 10 at order time). JLC lists **no other vertical jack with integrated magnetics**; the
backup if it runs out is the vertical shielded XUNPU RJ45-408-050-11 (C7421421, 3,556, 2 LEDs, no magnetics) plus a
discrete Pulse HX1188NL 10/100 transformer (C6176011, 1,770) wired per WIZnet's 'RJ45 with transformer' reference sheet
- a different footprint pair, so it is a layout change, not a drop-in. MAC address: locally-administered, derived from the RP2350 unique ID (firmware; no EEPROM, owner).

### 5.6 Display USB host port
Micro-B receptacle (Amphenol 10118194-0001LF) at the stock J18 spot so the existing cable plugs in. The RP2350 is the
host; its PHY applies the host pull-downs itself (DS 12.7.3). VBUS through a TPS2553 current-limited switch (0.43-0.52 A;
TI SLVS841F 10.2: 0.1 uF in, RILIM, output cap, FAULT open drain) so a damaged cable cannot load the 5 V rail; USBLC6-2SC6
at the connector; yellow VBUS-on LED. **Display power:** per the 2022 service manual (p.17 system diagram) the display
board is fed 5 V from the brick directly (harness AACE25503), not over the USB cable, so VBUS to the display is only a
'host present' signal; if the owner's display-current measurement (M-E6) confirms it is self-powered, the firmware can
leave the VBUS switch off: **TPS2553 EN = GPIO46 `VBUS_HOST_EN` + R80 100 k pull-down (2026-10-27)**, so the firmware
switches VBUS_HOST and it is off in reset / BOOTSEL. (A custom symbol with passive VBUS / GND pins replaces KiCad's device-view
USB_B_Micro, ERC only.)

### 5.7 USB-C debug console
Vertical 16-pin USB 2.0 receptacle HRO TYPE-C-31-D-06 (C2689964, 6.4 mm tall), sink Rd 5.1 k on CC1 / CC2, USBLC6-2SC6,
**CH340N** USB-UART on UART0 (WCH CH340 DS V3C sections 4 and 7: 3.3 V mode with V3 tied to VCC, 0.1 uF each, UD+/UD- with
no series resistors, internal clock). CH340N rather than CH340C: JLC lists its CH340C stock as 'no longer manufactured /
not buyable' (2026-10-26). Flashing stays on SWD (single USB controller, owner). VBUS_DBG powers nothing (no back-feed);
the console is live while the board is powered.

### 5.8 Audio - MAX98357A, datasheet 19-6779 Rev 7 Typical Application Circuit
I2S from PIO (GPIO30-32, DECISIONS #8), 10 uF + 0.1 uF + a 220 uF polymer reservoir on VDD, SD_MODE through 634 k from 3V3 (RLARGE,
Table 6 -> (L+R)/2 mono), **GAIN_SLOT unconnected = 9 dB** (Table 8, modest gain per owner) with the firmware capping
digital volume, ferrite + 1 nF on each output (the stock board's FB1/FB2 + C36/C37 arrangement). Replaces the stock
PWM -> RC -> analogue amp chain: no PWM-ripple filter to tune, 16-bit audio. **Speaker (owner photo 2026-10-26):
Stetron DB20-009, Bay Tek AACE8811A (10000856), 4 Ohm nominal (manual: 3.5-4 Ohm), power rating unverified** - a small
(~2-3 in) paper-cone driver, 2-wire floating so the BTL output is fine (the 2022 manual's BOSS BRS52B is not what our
units have). The amp therefore stays in the ~3 W class at a modest gain with a firmware volume cap (section 5.12).

### 5.9 Score and button inputs
Switch-to-GND model: the score sensors are **mechanical lever microswitches** (owner photo 2026-10-26: a wire lever
across each hole, audible click; no optos) closing to J11 pin 1 = GND (owner continuity); the Buttons header's
latch-side row is GND. Per line a 2.2 k pull-up to 3.3 V at the connector pin (1.5 mA wetting current through the
closed contact, >= 1 mA for silver microswitch contacts), ST ESDA6V1-5SC6 5-line TVS
array at the connector (3 arrays for 12 lines), 4.7 k series + 1 nF at the MCU pin (4.7 us), firmware debounce as stock
(10-60 ms menu setting). J11 carries no 5 V and the switches need none: the +5V_SENS TPS2553 is removed (M-E3 closed).

### 5.10 Lights
4 x AO3416 (AOS, 20 V, RDS(on) <= 26 mOhm at 2.5 V / <= 22 mOhm at 4.5 V gate) low side with 100 R gate resistors
and 4.7 k pull-downs (off during reset; <= 8.2 k for RP2350-E9, q6). **Channel budget 2 A** (current_budget LED_*_K / Q1-Q4 source returns; the
earlier "~3 A per channel" is not a rating this board qualifies: the drains run on 1.0-1.2 mm F.Cu tracks
(power_copper.py), not large drain pours, and the AO3416 headline / typical RthJA are for another test board; adversarial
review F05). At 2 A: ~32 mOhm hot -> 0.13 W per FET. AO3400A
(48 mOhm at 2.5 V, basic) would dissipate ~0.6 W in SOT-23 - kept-extended reason in ORDERING.md. PWM on GPIO0-3 (PWM
slices 0A/0B/1A/1B) for dimming / colour mixing of the existing strips; ~10 nC gate charge through 100 R switches in
~1 us, negligible at a few kHz. **Firmware light cap** (RMS = I_on x sqrt(duty) per channel): RGB <= 3.3 A RMS at <=
50 C local ambient (F1 derating, q6), each channel <= 2 A, playfield <= 1.5 A, both <= 5.0 A. No addressable output
(owner). A channel wire shorted to +5 V is not limited below the supply's overload point (power review P2, owner
decision O1 open).

**Fault envelope (adversarial review F05, recorded 2026-10-27; not closed by firmware).** +5V_IN carries the lights AND
the logic: current_budget's 5.5 A trunk = RGB 4 A + PF 1.5 A; the eFuse branch adds up to 2.5 A (limit 2.8-3.2 A), so
the J1 / trunk copper and J1.3's GND return are sized for 5.5 A continuous with the measured board input 4 A (M-E2). A
drain-to-supply or harness short on a light channel is cleared only by its PTC: F1 trips at 10 A (20 C), F2 at 5 A,
and the LPV-60-5 (8 A, overload 110-150 %, hiccup) may fold back before delivering F1's trip current - the sustained
fault then sits in the supply's overload envelope, not on a trace rating. No sustained-fault (DT 40 K) widths are
claimed (current_budget FAULT = None). U1's OV clamp can activate up to 5.9 V vs the 6 V abs max of U2 / U8: compatible
with the stock supply, not shown for every input transient. Firmware brightness limits do not protect against shorts.

### 5.11 Diagnostics and controls
LEDs (0603, visible from above): PWR (3.3 V), STATUS (GPIO44 heartbeat), VBUS (display port), FAULT (red, on the
wired-OR open-drain fault line of the eFuse and the VBUS TPS2553: lights on over-current / over-temperature / OV clamp,
and read by GPIO47), plus the RJ45's LINK / ACT LEDs driven by the W5500. +5V_SYS is monitored on ADC0 (GPIO40). Buttons RESET + BOOTSEL; lane-ID DIP (XKB
DSIC04LS-P, 2.54 mm SMD, ON = low). No test points (owner 2026-10-27); GPIO34-37 are unused.

### 5.12 5 V power budget and the audio ceiling
Typical = game running, music at normal level; peak = simultaneous worst case. 3.3 V loads are referred to 5 V through
the TLV62569 at ~88 % (estimate from its efficiency curves). **est.** = estimate, **meas.** = owner to measure.

| Consumer | Rail | Typical | Peak | Basis |
|---|---|---:|---:|---|
| RP2350B @ 150 MHz + W25Q128 flash | 3.3 V | 0.06 A | 0.10 A | est. (RP2350 DS 14.9.7 current tables; flash read current) |
| W5500, 100 Mbit link | 3.3 V | 0.13 A | 0.13 A | W5500 DS 5.4: 132 mA |
| CH340N console bridge (only with USB-C plugged in) | 3.3 V | 0.00 A | 0.02 A | est. |
| Pull-ups (12 inputs + 4 DIP), LEDs PWR / STATUS / FAULT, RJ45 LEDs | 3.3 V | 0.01 A | 0.02 A | resistor values |
| **3.3 V total, referred to 5 V** | 5 V | **0.16 A** | **0.21 A** | x 3.3 / (5 x 0.88) |
| Display USB VBUS (display has its own 5 V; VBUS = detect) + VBUS LED | 5 V | 0.01 A | 0.52 A limit | TPS2553, RILIM 49.9 k |
| MAX98357A into 4 Ohm | 5 V | 0.25 A | 1.2 A | 3.2 W peak; idle 2.4 mA |
| **eFuse branch (+5V_SYS)** | 5 V | **0.45 A** | **1.4 A realistic; 1.9 A with the VBUS switch at its limit** | eFuse limit 2.8-3.2 A |
| Light strips: RGB 60 LED/m 5050 (7-9 A uncapped full white), playfield bar ~24 x 5050 (1.2-1.5 A) | 5 V | game-dependent | **5.0 A firmware cap** (RGB <= 4.0, PF <= 1.5) | owner photos; PTCs 5 A / 3 A hold |
| **Board + lights from the PSU** | 5 V | | **~6.4 A** (1.4 + 5.0) | leaves ~1.6 A of the 8 A for the display (M-E6) |
| Display board (own feed from the PSU, measured ~1 A, M-E6) | 5 V | ~1.0 A | ~1.0 A | owner clamp 2026-10-26 |
| **PSU total** | 5 V | stock measured ~5.7 A | **~7.4 A at the caps** of 8 A | owner clamp: RGB 3.7, PF 0.5, board input 4 A |

PSU (owner 2026-10-26): **Mean Well LPV-60-5, 5 V, 8 A rated (0-8 A), 40 W, overload 110-150 %** (datasheet
`datasheets/dl/LPV-60-spec.pdf`). **The light figures above are superseded:** the RGB strip is a 60 LED/m 5050 analog
strip over the 2.06 m alley + ball area (7-9 A at full white) and the playfield bar ~24 x 5050 (1.2-1.5 A); the light
channels are AO3416 FETs (~3 A each) with one PTC per harness, and the firmware caps total light current so that
board (1.4 A realistic peak) + lights (5.0 A cap) + display stay inside the 8 A; the cap is re-set once the display
current is measured (M-E6). Old text for the record: Brick
Bay Tek AAPS25500, rating unknown. The manual's whole-game input figure,
max 0.3 A at 100-120 VAC (<= 36 VA), bounds its 5 V output to roughly 5 A at ~80 % conversion efficiency (estimate),
and the display board's LED matrix shares it (its current is not known: M-E6). The margin is stated once the label and
the display current are in; the board's own worst case is already capped by the eFuse (3 A) and the light polyfuse
(3 A hold).

Bulk capacitance for audio peaks: the brick's regulation loop responds in roughly 100 us (estimate for a small SMPS);
the local reservoir carries the amplifier until then. +5V_SYS holds 3 x 220 uF polymer + ~0.1 mF of MLCC = ~0.76 mF:
a 1.2 A peak for 100 us droops 1.2 A x 100 us / 0.76 mF = 0.16 V (MAX98357A PSRR 77 dB at 1 kHz; a 0.16 V dip only
trims the peak slightly). The eFuse soft start charges it at 0.89 V/ms = 0.68 A. Lower-frequency current comes from the
brick through the harness (IR drop ~0.1 V at 1.2 A for ~0.1 Ohm round trip, est.).

Audio ceiling on a 5 V rail into 4 Ohm (MAX98357A electrical characteristics, 12 dB setting): **3.2 W at 10 % THD+N,
2.5 W at 1 % THD+N** (clean). Chosen **GAIN_SLOT unconnected = 9 dB**: full-scale digital (2.1 dBV + 9 dB = 3.6 V rms)
already reaches the rail's clip point (3.6 V rms into 4 Ohm = 3.2 W), so more gain would only clip sooner. The
firmware caps the digital volume (e.g. -3 dBFS = ~1.6 W) for the unrated Stetron driver. More acoustic output would
need a higher rail (not planned).

### 5.13 Component-quality upgrades vs the stock board

| Stock | SBC-1 | Why |
|---|---|---|
| Large 5 V aluminium electrolytic (C3) + SMD electrolytics (C10, C31 ...) | 4 x 220 uF polymer aluminium (3 on +5V_SYS, 1 on the light rail) + X5R/X7R MLCCs | no dry-out, low ESR, 2000 h at 105 C rating (~10x per 20 C cooler) |
| NCP1117-3.3 LDO | TLV62569 sync buck + TLV74311 core LDO | ~0.6 W less heat at 0.35 A; the core supply avoids a 1-unit-stock inductor |
| no input protection | TVS + TPS259531 eFuse (current limit, OV clamp 5.2-5.7 V above VOVC 5.5-5.9 V, UVLO, soft start) + light-harness PTCs | logic-rail faults are contained; light shorts: see O1 / O2 |
| HC-49 SMD 12 MHz crystal | Abracon ABM8-272-T3 (Raspberry Pi's specified part) | guaranteed RP2350 oscillator start-up |
| PWM audio + RC + analogue amp | MAX98357A I2S class-D | cleaner sound, fewer tuned parts |
| on/off light FETs | PWM-capable AO3416 per channel (2 A budget), 4.7 k gate pull-downs, one PTC per light harness, firmware current cap | dimming / colour mixing; lights stay off in reset; a sustained overload trips the PTC |
| BOOTSEL jumper, unpopulated SWD header | RESET + BOOTSEL buttons, JST SH SWD, USB-C console | service without tools |
| no ESD on harness lines | TVS arrays on every input, USBLC6 on both USB ports | long harness leads in a cabinet |

## 6. Removed vs the stock board
8 modular jacks (score sensors now arrive on J11 on the owner's machines), J2 'JButton' 2x5, the unpopulated 4-pin
footprints J5 / J7 beside RGB Lights / Buttons, J19, J3 jumper. No expansion header, no PoE, no MAC EEPROM, no
addressable-LED output (owner 2026-10-26).

## 7. Parts availability and cost (details: `docs/ORDERING.md`, generated)
- Every placed line is in JLC stock with >= 2 x (5-board need + attrition): `python scripts/bom.py check` = 0 fails
  (2026-10-26 21:13 UTC). Method: JLC's parts-library API (the backend of the jlcpcb.com part page), one timestamped
  observation per line in `bom/bom.json`; spot-checked on the rendered live part pages the same evening: RP2350A 5,711 in
  stock / $1.2947, TPS259531DSGR 2,161 / $0.8773, ABM8-272-T3 2,730 / $0.6580, RP2350B 3,477 / $1.2833 - all equal to
  the API values.
- Every line passes the >= 2 x (need + attrition) gate for the 5-board run (J11 Molex 22232091: 50 in stock, need 5).
  RP2350B stepping on the JLC reel is not stated (A2 vs A4). Erratum RP2350-E9 (A2: an input-enabled pad leaks ~120 uA
  and settles near 2.2 V unless driven by <= 8.2 k) does not matter here: every input has an external 4.7 k / 10 k
  pull-up, and the light gates are driven outputs whose 10 k pull-downs only act while the pad is reset (input
  disabled), so the board works on either stepping (QA_LOG Q-5).
- Cost per board at the 5-board run, parts only (`docs/ORDERING.md`): placed parts **$19.52** + harness headers
  (all six genuine Molex, JLC-placed) **$2.93** + JLC extended-part fees (**31** lines x $3 per order = **$18.60 /
  board**) = **$41.05**. The cost pass (owner 2026-10-26) moved 3 lines to JLC basic / preferred parts. Swaps and the lines deliberately kept extended are listed at the end of `docs/ORDERING.md`. PCB fabrication, assembly labour and the THT harness connectors' hand / wave solder
  charge are quoted by JLC at order time (not included). Core chips: W5500 $2.83, HR963380AE $2.73, W25Q128 $2.58,
  MAX98357A $1.32, RP2350B $1.28.

## 8. Open items
See `docs/MEASUREMENTS_NEEDED.md` (owner) and `docs/WORK_STATE.md` (next steps).

## q6 corrections notes (coordinator QA 2026-10-27b, CORRECTIONS B10 / B11)

- **Y2 (YXC X322525MOB4SI, C9006) load capacitance**: YXC's series datasheet (YSX321SL, datasheets/dl/y2/
  X322525MOB4SI.pdf) lists CL "10 pF, 20 pF, or specify", C0 <= 3 pF, ESR <= 50 R at 16-31 MHz, drive 10-200 uW; the
  part-number-specific CL = **12 pF** comes from the LCSC / JLC listing of C9006 ("12pF 25MHz +-10ppm"). The 18 pF load
  caps give 18 x 18 / 36 = 9 pF + ~3 pF stray = 12 pF (W5500 DS 5.5.3 shows 18 pF caps for the same case). Verified.
- **BOOTSEL D+ leak (logic L-11, accepted)**: in BOOTSEL device mode with no PC attached the RP2350's D+ pull-up feeds
  VBUS_HOST through the USBLC6 I/O -> VBUS steering diode (~2 V on J9 VBUS, D4 glows faintly). Harmless; documented
  in BRINGUP 2.5.
- **RUN (logic L-12, accepted)**: internal pull-up only, 53 mm to SW2, no filter capacitor; rework option in BRINGUP 5.
- **Net-name nit**: net ETH_LED_Y_K drives HanRun's ORANGE LED (pins 12 / 11); the name is kept (renaming would churn the
  routed board for no electrical change).
- **Ethernet termination (logic L-03, accepted)**: R31-R35 / C50 / C51 stay where q5 put them (stubs 8.5-19.2 mm); 10/100
  BASE-TX tolerates them; link-test at 100 m cable (BRINGUP 3.4). The q6 pass did not move them (time box spent on the
  power / mechanical items); USB host pair coupling (L-06) and Y2 (L-08) likewise accepted.

