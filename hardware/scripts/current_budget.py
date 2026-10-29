"""Per-net current budget and required track width, SBC-1 main. Ported from din8r-chassis-thermal/scripts/
current_budget.py, 2026-10-26 (origin DIN-8R; owner 2026-10-05: "a validation rule that looks at trace width for
appropriate nets as a part of every cleaning pass"). The rule and the IPC-2152 fit are the parent's; the budget is
SBC-1's (lead 2026-10-26 load table: +5V_IN 5.5 A, +5V_RGB 4 A, +5V_PF 1.5 A, LED_*_K 2 A, +5V_SYS 2 A, VBUS_HOST 1 A,
SPK / AMP 1 A; the rest from design.py notes).

ONE data source: BUDGET below. required_width() is the ONE width function; qa_copper_landing TRACK-WIDTH and
qa_layout_quality POWER-PAD-CONN / VIA-CURRENT import it.

Rule (per track, per layer):
    required = max(declared class width (.kicad_pro), IPC-2152 width of the net's LOAD current at DT_LOAD_K,
                   IPC-2152 width of its sustained FAULT current at DT_FAULT_K)
  * Adversarial review F05 (2026-10-27), recorded: +5V_IN carries lights AND logic (5.5 A = RGB 4 + PF 1.5 on the trunk;
    the eFuse branch adds up to 2.5 A; measured board input 4 A, M-E2); the light channel budget is 2 A (not the ~3 A
    of earlier notes); the FET drains run on locked 1.0-1.2 mm tracks (no large drain pours); no sustained FAULT
    current is budgeted - the fault envelope is in docs/ARCHITECTURE.md 5.10.
  * LOAD  = the largest continuous (RMS) current any ONE track of the net carries in normal worst-case operation.
  * FAULT = the largest current the upstream protection lets flow indefinitely. SBC-1: None everywhere for now (the
            PTCs F1 / F2 trip, the TPS259531 eFuse and the TPS2553 limit; their sustained envelopes are a lead item).
  * IPC-2152 width: curve fit of IPC-2152 Figure 5-1 (baseline chart, no planes, still air),
    A[mil^2] = (117.555 * dT^-0.913 + 1.15) * I^(0.84 * dT^-0.018 + 1.159), width = A / t.
  * Copper (STACKUP): 2-layer 1.6 mm, 1 oz (35 um) both outer layers (CLAUDE.md section 9).
  * DT_LOAD_K = 20 K (SBC-1 DECISIONS #5; the parent's 10 K), DT_FAULT_K = 40 K (kept).
Basis "budget-path" (parent): the net budget applies to the SUPPLY PATH; a track on a leaf branch that leads only to
R / C pads carries no rail current and is held to its class width. GND is poured on both layers; its tracks are drops.
"""
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DT_LOAD_K = 20.0          # SBC-1 DECISIONS #5 (lead 2026-10-27): 1 oz outer, ventilated cabinet, firmware-capped
                          # light currents (CT / DIN-8R: 10 K)
DT_FAULT_K = 40.0
SIGNAL_A = 0.02
NECK_MM = 1.0             # a below-required segment this long into a same-net pad no wider than required
UM_PER_MIL = 25.4
STACKUP = {"main": {"outer_um": 35.0, "inner_um": 17.5}}          # JLC04161H-7628: 1 oz outer, 0.5 oz inner
OUTER_LAYERS = ("F.Cu", "B.Cu")
IMPEDANCE = {"main": {"nets": set(), "outer_mm": None, "tol_mm": 0.011}}   # no impedance control ordered


def B(load, fault, why):
    return {"load_A": load, "fault_A": fault, "why": why}


_LEAD = "lead 2026-10-26 load table"
MAIN = {
    "+5V_IN": B(5.5, None, f"{_LEAD}: J1 brick input -> PTCs F1 (RGB 4 A) + F2 (playfield 1.5 A) + eFuse U1 (logic)"),
    "+5V_RGB": B(4.0, None, f"{_LEAD}: F1 -> J7 RGB light common (firmware 4 A cap, design.py F1 note)"),
    "+5V_PF": B(1.5, None, f"{_LEAD}: F2 -> J8 playfield bar (design.py F2 note: 1.5 A bar current)"),
    **{n: B(2.0, None, f"{_LEAD}: light channel FET drain -> J7 / J8 cathode pin") for n in
       ("LED_R_K", "LED_G_K", "LED_B_K", "LED_PF_K")},
    "+5V_SYS": B(2.0, None, f"{_LEAD}: TPS259531 eFuse output -> buck U2, USB host switch U4, amp U8, the 8 score jacks (~0.2 A total, lead 2026-10-27)"),
    "VBUS_HOST": B(1.0, None, f"{_LEAD}: TPS2553 U4 -> J9 display USB"),
    **{n: B(1.0, None, f"{_LEAD}: MAX98357A class-D output (3 W / 4 ohm peak ~1 A)") for n in
       ("SPK_P", "SPK_N", "AMP_OUTP", "AMP_OUTN")},
    "SW_3V3": B(0.4, None, "TLV62569 U2 SW / L1: inductor current = the +3V3 load"),
    "+3V3": B(0.4, None, "logic rail: RP2350B + W5500 (~132 mA) + CH340N + LEDs, budgeted 0.4 A"),
    "+3V3A": B(0.132, None, "W5500 analog 3V3 via FB1 (W5500 DS: <= 132 mA)"),
    "+1V1": B(0.2, None, "TLV74311 U3 -> RP2350B DVDD (core), budgeted 0.2 A"),
    "VBUS_DBG": B(0.1, None, "USB-C debug VBUS: only U13 ESD (CH340N runs from +3V3)"),
    "GND": B(1.0, None, "GND drops: the largest single-part return is the MAX98357A (~1 A peak); poured both layers"),
}
BUDGET = {"main": MAIN}
SCREEN_NETS = {"main": ()}
GUARANTEED_FAULT_A = {"main": {}}
EFUSE_BRANCH_A = 2.5      # DECISIONS #4: J1 / D1 / C4 -> U1.3 / U1.4 eFuse input branch (TPS259531 ILIM ~3.0 A, 2 A load)
SIGNAL_LEAF_A = 0.1       # DECISIONS #4: R1 (UVLO divider), C5 (bulk) on +5V_IN are signal level (TP1 removed 2026-10-27)
BRANCHES = {"main": {
    # the 5.5 A trunk is the LOCKED zone copper J1 -> F1 / F2 only; first match wins, so the leaves come first
    "+5V_IN": [
        *({"parts": (r,), "load_A": SIGNAL_LEAF_A, "fault_A": None,
           "why": f"DECISIONS #4: {r} on +5V_IN is signal level"} for r in ("R1", "C5")),
        {"parts": ("D1", "C4", "U1", "R1", "C5"), "load_A": EFUSE_BRANCH_A, "fault_A": None,
         "why": "DECISIONS #4: the eFuse input branch J1 / D1 / C4 -> U1.3 / U1.4 (2.5 A)"},
    ],
    # GND returns at their real current (q5 2026-10-27; part_return() = the part's own return, VIA-CURRENT / width):
    # each light FET source carries its channel (LED_*_K 2 A); J1.3 is the only board GND entry = the whole +5V_IN
    # load (5.5 A); power_copper Q5_FET / GND_J1_F + J1_GND_VIAS size them
    "GND": [
        *({"parts": (q,), "load_A": 2.0, "fault_A": None,
           "why": f"{q} source: light channel return (LED_*_K 2 A, lead 2026-10-26 load table)"}
          for q in ("Q1", "Q2", "Q3", "Q4")),
        {"parts": ("J1",), "load_A": 5.5, "fault_A": None,
         "why": "J1.3: the board's only GND entry returns the whole +5V_IN load (5.5 A)"},
    ],
}}
WIDTH_BASIS = {"main": "budget-path"}
CURRENT_CLASSES = {"Power", "Audio", "Power5", "PowerLight", "Rail"}   # every non-Default netclass of pcb_rules.py
IMPEDANCE_CLASSES = set()
RAIL_RE = re.compile(r"^(GND\w*|[+-]\d+V\d*\w*|\+V_\w+|VBUS\w*|VCC\w*|VDD\w*)$")


def ipc2152_area_mil2(i_a, dt_k):
    """cross-section (mil^2) for i_a amps at dt_k rise: IPC-2152 Figure 5-1 baseline curve fit."""
    if i_a <= 0:
        return 0.0
    return (117.555 * dt_k ** -0.913 + 1.15) * i_a ** (0.84 * dt_k ** -0.018 + 1.159)


def ipc2152_width_mm(i_a, dt_k, cu_um):
    return ipc2152_area_mil2(i_a, dt_k) / (cu_um / UM_PER_MIL) * 0.0254


def budget(kind, net):
    """(load_A, fault_A, why) for a net; unlisted nets are signals at SIGNAL_A."""
    b = BUDGET[kind].get(net)
    return (b["load_A"], b["fault_A"], b["why"]) if b else (SIGNAL_A, None, "signal default")


def is_current_net(kind, net, cls=None):
    """width-gated as current-carrying: in the budget, or (fallback) a current class / rail by name."""
    return net in BUDGET[kind] or cls in CURRENT_CLASSES or bool(RAIL_RE.match(net))


def _ipc_width(kind, load, fault, outer):
    cu = STACKUP[kind]["outer_um" if outer else "inner_um"]
    w = ipc2152_width_mm(load, DT_LOAD_K, cu)
    if fault:
        w = max(w, ipc2152_width_mm(fault, DT_FAULT_K, cu))
    return w


def current_width(kind, net, outer):
    load, fault, _ = budget(kind, net)
    return _ipc_width(kind, load, fault, outer)


def required_width(kind, net, outer, class_width):
    """THE width rule: max(declared class width, IPC-2152 load width, IPC-2152 fault width), mm, rounded up to 1 um."""
    return math.ceil(max(class_width or 0.0, current_width(kind, net, outer)) * 1000 - 1e-6) / 1000


def branch_required_width(kind, branch, outer, class_width):
    w = _ipc_width(kind, branch["load_A"], branch["fault_A"], outer)
    return math.ceil(max(class_width or 0.0, w) * 1000 - 1e-6) / 1000


def part_return(kind, net, ref):
    for br in BRANCHES.get(kind, {}).get(net, []):
        if tuple(br["parts"]) == (ref,):
            return br["load_A"], (br["fault_A"] if br["fault_A"] is not None else br["load_A"])
    return None


def impedance_width(kind, net, outer):
    imp = IMPEDANCE[kind]
    if net not in imp["nets"]:
        return None
    return (imp["outer_mm"] if outer else None), imp["tol_mm"]


def table(kind="main", classes=None):
    rows = []
    for net in sorted(BUDGET[kind]):
        cw = (classes or {}).get(net)
        rows.append({"net": net, "load_A": BUDGET[kind][net]["load_A"], "fault_A": BUDGET[kind][net]["fault_A"],
                     "ipc_outer": round(current_width(kind, net, True), 3),
                     "ipc_inner": round(current_width(kind, net, False), 3), "class_w": cw,
                     "req_outer": required_width(kind, net, True, cw), "req_inner": required_width(kind, net, False, cw),
                     "screen": net in SCREEN_NETS[kind], "why": BUDGET[kind][net]["why"]})
    return rows


def fault_screen_consistency():
    bad = []
    for kind, tab in GUARANTEED_FAULT_A.items():
        for net, g in tab.items():
            b = BUDGET[kind].get(net)
            if b is None or b["fault_A"] is None or b["fault_A"] < g - 1e-9:
                bad.append((kind, net, b and b["fault_A"], g))
    return bad


_bad = fault_screen_consistency()
if _bad:
    raise RuntimeError(f"current_budget: fault below its datasheet-guaranteed envelope: {_bad}")


if __name__ == "__main__":
    print(f"{'net':12s} {'load':>6s} {'fault':>6s} {'out_mm':>7s}")
    for r in table():
        print(f"{r['net']:12s} {r['load_A']:6.3f} {(r['fault_A'] or 0):6.3f} {r['ipc_outer']:7.3f}")
