# SBC-1 - what the agent is waiting on from the owner (2026-10-26)

| # | ID | What I need | How to get it | What it unblocks | Blocking? |
|---|---|---|---|---|---|

No measurements or design decisions are waiting on you (M-H1, M-E2, M-E6 closed 2026-10-26). Closed today from your photos: M-E3 (score sensors = mechanical lever
microswitches -> sensor 5 V switch removed, 2.2 k pull-ups) and the ball-holder strip type (4-wire 60 LED/m 5050).

## Deferred design TODO (owner 2026-10-27: after routing is complete, do NOT interrupt routing)
- **DONE 2026-10-27 (DECISIONS #10: F3 Bourns MF-NSMF050-2, +5V_JACK; applied before the 4-layer route per owner) TODO-1: resettable fuse (~0.5 A hold PTC) on the score-jack +5 V feed** (J21-J28 pin 1, today straight off
  +5V_SYS). Keeps opto-sensor compatibility (3-wire optos on the jacks) without a pinched sensor cable tripping the
  board's main eFuse. Apply only once the board is fully routed and adopted; re-route the affected area then.
- **TODO-2: DONE 2026-10-27 (Q-56)** - scan-guide circles removed at the source (pcb_build.py); the rebuilt board has no gr_circle on Cmts.User.
- **TODO-3: DONE 2026-10-27 (Q-56)** - holes at (3.885, 3.585) / (112.795, 3.585) / (112.795, 82.145) / (3.885, 82.145), scan re-anchored in both axes (+0.46 / +0.23 % vs 300 dpi), harness connectors re-registered on the unrouted placement (shifts <= 0.26 mm x / 0.38 mm y), placement DRC clean.
