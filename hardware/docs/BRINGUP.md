# SBC-1 bring-up and firmware requirements

Source: the first-power checklist of the adversarial review (`C:\work\SKEEBALL-ADVERSARIAL-REVIEW-2026-10-27\REPORT.md`,
"Recovery and qualification limits", and `electrical\REPORT.md` "Firmware/bench conditions"), 2026-10-27, applied to the
board as released (q5), updated for the q6 corrections pass (coordinator QA 2026-10-27b: CORRECTIONS.md A9 / B11 / D4).
These are validation steps still to be done; nothing here is claimed as already measured.

## 1. Before power

1. Visual: D2 (FAULT, red KT-0603R) / D4 (VBUS, yellow NCD0603Y1) / D3 / D5 (green KT-0603G): cathode (green mark)
   on the silk-chamfer side = pad 1; U1-U14 pin 1 against the silkscreen; J10 (HRO TYPE-C-31-D-15) shell legs
   soldered THROUGH the board (visible on the bottom side, DECISIONS #11 / #14).
4. Reversed input: the TVS D1 is the only measure (forward ~1 V puts about -1 V on U1 IN, abs min -0.3 V, and
   reverse-biases the polymer capacitors); the Mini-Fit Jr J1 keying limits the risk - never feed J1 from clip
   leads without checking polarity first (power review M6).
2. Ohmmeter: +5V_IN, +5V_SYS, +3V3, +1V1, +5V_RGB, +5V_PF to GND - none shorted.
3. No harness connected. Do not connect a PC to J9 (display port) at any point of the bring-up.

## 2. First power (current-limited bench supply, not the machine PSU)

| Step | Set / do | Expect |
|---|---|---|
| 2.1 | 5.0 V, limit 0.3 A, into J1 (pin 1 = +5 V, pin 3 = GND) | PWR (green) LED on; supply current < 0.15 A with the MCU unprogrammed |
| 2.2 | Measure +3V3 (C10 / L1 out) and +1V1 at C14 / the DVDD decaps (C28-C30) | 3.26-3.39 V; 1.085-1.115 V, and >= 1.05 V at the DVDD pins |
| 2.3 | Ramp the supply 0 -> 5 V slowly, then 5 V -> 0 | eFuse turns on at 3.48-4.04 V (typ 3.75 V) and off at 3.17-3.72 V (R1 100 k / R2 47 k); repeat 3 times for restart |
| 2.4 | All light outputs during reset (hold RESET) and right after power-up | Q1-Q4 off: no current into a 1 k test load from +5V_RGB / +5V_PF to each LED_*_K pin |
| 2.5 | VBUS_HOST (J9 pin 1) during reset and in BOOTSEL (hold BOOTSEL, tap RESET) | ~0 V from U4 (EN = GPIO46 with R80 4.7 k pull-down). In BOOTSEL with no PC on J9 the RP2350's D+ pull-up leaks ~2 V onto VBUS_HOST through the USBLC6 steering diode and the VBUS LED may glow faintly: accepted (logic review L-11), not a U4 fault |
| 2.6 | SWD (J2, Raspberry Pi Debug Probe): `openocd ... rp2350` / probe-rs identify | RP2350B (A2) found on both cores |
| 2.7 | Flash a known RP2350B test build via SWD | crystal starts (12 MHz; measure with a low-capacitance probe on XOUT_X only - a probe on XIN can stop the oscillator); flash JEDEC ID = W25Q128JV; repeated cold boots |
| 2.8 | Controlled-load heat: light channels at their caps into dummy loads, 30 min | U3 (TLV74311) and Q1-Q4 temperatures recorded; F1 not tripping at the cap (3.3 A RMS) at room temperature |
| 2.9 | Measure the machine supply (LPV-60-5) at J1, no load and full light load | record it: the SMBJ5.0A standoff (5.0 V) is below the supply's +8 % tolerance (5.4 V), so D1 leakage can exceed its 800 uA spec at the top of the band (power review M5); above ~5.3 V check D1's temperature |
| 2.10 | +5V_SYS vs +5V_IN at 5.0 / 5.3 V input (bench only; do not exceed 5.5 V) | +5V_SYS follows +5V_IN: the TPS259531 clamps only above its OV threshold (VOVC 5.5-5.9 V), so a supply fault can put up to 5.9 V on +5V_SYS (TLV62569 / MAX98357A recommended max 5.5 V, abs max 6.0 V; power review M4) |
| 2.11 | Score-jack short: +5V_JACK (any J21-J28 contact 1) to GND through a 0.5 R load, bench supply 5 V / 4 A | F3 trips (0.5 A hold / 1 A trip) and the logic recovers when the short is removed; record whether the eFuse current limit (2.8-3.2 A) thermal-cycles (93 ms auto-retry) before F3 opens (power review M10) |

## 3. Functional (machine harness, after section 2 passes)

1. Every score input and button mechanically, incl. bounce and simultaneous switches; all lane-ID DIP combinations;
   harness open / short cases; correct 100-point left / right mapping on the machine.
2. Display USB host: the self-powered stock display enumerates (HID 0xB337:0x00EF) in both power-up orders and after
   repeated unplug / replug; VBUS does not back-feed from the display.
3. Audio at the accepted firmware volume limit with the real speaker (temperature after a long play).
4. Ethernet: sustained traffic and repeated link resets while all lamps PWM and audio plays; more than one cable / switch.
   Clock startup and USB stability must survive the same load.
5. Rail droop on +5V_SYS / +3V3 during light PWM edges and audio peaks. The 22 / 10 uF X5R 0805 MLCCs keep only
   ~30-40 % of nominal at 5 V DC bias (power review M11): the polymer capacitors carry the hold-up.
6. Fault and ESD tests need their own bounded setup (not part of the first build sign-off).

## 4. Firmware requirements (from the review + the hardware design)

| # | Requirement | Why |
|---|---|---|
| FW-1 | Early in boot write HIZ = 1 in the POWMAN VREG register (offset 0x00c, bit 1; POWMAN password 0x5AFE in bits 31:16) | external 1.1 V core supply (RP2350 DS 6.3.7, Figure 24): the on-chip regulator still powers on and draws ~400 uA until it is put in high-impedance mode |
| FW-2 | GPIO46 `VBUS_HOST_EN` output, low until the display stack starts; drive it low before any software reboot into BOOTSEL (`reset_usb_boot`) | pad isolation latches keep the last pad state through a software reset (DS 9.7); R80 holds EN low only from the reset state |
| FW-3 | RGB current cap **3.3 A RMS** (RMS = I_on x sqrt(duty) per channel, summed on the common) at <= 50 C local ambient (the owner can raise it in firmware); each channel <= 2 A; playfield <= 1.5 A; lights total <= 5.0 A | F1 2920L500 derating, conservative set: 4.15 A at 40 C / 3.75 A at 50 C / 3.30 A at 60 C (Littelfuse table 4.25 / 3.88 / 3.50); the light channel budget is 2 A (q6 coordinator QA A9) |
| FW-4 | GPIO40 analog only (digital input disabled) for the +5V_SYS monitor; light GPIOs 0-3 and GPIO46 preferably not left as enabled inputs with output disabled | RP2350 A2 erratum E9: the q6 4.7 k gate pull-downs and R80 4.7 k (<= 8.2 k) defeat the ~2.2 V latch, so this is now belt-and-braces |
| FW-8 | GPIO47 `PWR_FAULT_N` input, low = fault (eFuse FLT / TPS2553 FAULT); pad pull-up / pull-down optional | R81 10 k is the line's pull-up (q6; the FAULT LED in series was never a pull-up); ETH_CS_N has R82 10 k so the W5500 stays deselected in reset / BOOTSEL |
| FW-5 | W5500 reset: RSTn (GPIO9) low >= 500 us, then wait up to 1 ms for PLL lock before SPI access; start with a modest SPI clock | W5500 DS 5.5.1 |
| FW-6 | PIO I2S with GPIOBASE 16 (BCLK GPIO30, LRCLK GPIO31, DIN GPIO32); volume cap per the speaker test | DECISIONS #8 |
| FW-7 | Score / button inputs: firmware edge qualification + double-count prevention (the RC is noise filtering, not debounce) | review electrical lane |

## 5. Programming and recovery

- **SWD (J2) is the programming and recovery path.** Field updates over Ethernet (A/B partitions), SWD as fallback.
- J9 (display port) USB bootloader: possible only because VBUS_HOST is off in BOOTSEL after a RESET-button (RUN pin)
  reset; still prefer SWD. Never with firmware running VBUS_HOST on.
- J10 (USB-C, CH340N console on UART0): use it only with a powered PC / hub and unplug it when that host is off (the
  CH340N's USB pull-up has no VBUS qualification). J10 is a console only, not an RP2350 USB port.
- RUN (RESET) has only the RP2350's internal pull-up and a 53 mm trace to SW2 (no filter capacitor; logic review
  L-12): if spurious resets appear in the ESD / cabinet tests, add a 100 nF from RUN to GND at U5 pin 35 by rework.

## 6. Installation notes (mechanical review D4)

- **J3 (Ethernet)** is an all-SMT jack held by its SMD joints and two plastic pegs on the tallest part: tie the
  Ethernet cable down within ~10 cm of the jack (mech M-5).
- **J9 (display micro-B)** shell tabs end inside the board (pin-in-paste from the SMD shell pads): watch the joint
  at bring-up; a dab of edge adhesive is an option because the display cable stays plugged in (mech M-8).
- **Mating loads**: the Mini-Fit 8-circuit (~50 N), the 1x4 headers and the jacks are pushed mid-span on edges
  supported only at the corner studs (left edge 78.6 mm, jack edge 108.9 mm span, same as stock): support the board
  behind J6 / J7 / the jacks while plugging (mech M-12).
