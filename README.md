# skeeball-premium-re

Reverse engineering of the Bay Tek **Skee-Ball Home Arcade Premium** electronics, and an open replacement for its main
board (A5CB25502 Rev 2.2).

The replacement board, **SBC-1**, is a drop-in swap: the same outline, mounting holes and harness connector positions as
the stock board, so the machine's existing wiring plugs straight in. On top of the stock functions it adds wired
Ethernet, so several lanes can share high scores and play together.

| Folder | What |
|---|---|
| [`hardware/`](hardware/) | SBC-1: KiCad 10 project, design-as-code scripts, BOM, routed 4-layer board, manufacturing files, design records |

## SBC-1 at a glance
- **MCU:** Raspberry Pi RP2350B with 16 MB QSPI flash.
- **Network:** WIZnet W5500 10/100 Ethernet (HanRun magjack).
- **Audio:** MAX98357A I2S class-D amplifier to the stock speaker.
- **Display:** USB host port for the stock score display.
- **Lights:** PWM low-side drivers on the existing RGB and playfield LED strips.
- **Power:** protected 5 V input (TVS, eFuse, resettable fuses).
- **Debug:** USB-C serial console and SWD.
- **Setup:** lane-ID DIP switch, status LEDs.
- **PCB:** 4-layer, 116.68 x 85.73 mm, assembled by JLCPCB (all parts from JLC stock).

**Status:** the first batch of boards is in production. Firmware for the new board is an original implementation and
is not published yet. See [`hardware/README.md`](hardware/README.md) for the project layout, how to regenerate
everything, and what is deliberately not in the repository. See [`hardware/docs/BRINGUP.md`](hardware/docs/BRINGUP.md)
for first power-up.

## Notes
- This is an independent hobby project. It is not affiliated with or endorsed by Bay Tek Entertainment. Skee-Ball is a
  trademark of its owner.
- The repository contains no Bay Tek firmware, binaries or decompiled code. Stock-board facts here come from
  measurements, photos and continuity tests of the owner's own machines.
- Third-party datasheets and vendor 3D models are not redistributed. The setup notes in `hardware/README.md` say
  how to fetch them.
