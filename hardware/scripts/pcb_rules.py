"""THE board rule set (KiCad Python). Ported from din8r-chassis-thermal/scripts/pcb_rules.py, 2026-10-26.
Applied by scripts/route_prep.py / pcb_rules_apply.py (pfr2 run_stage) and persisted with pcbnew.SaveBoard() (KiCad 8+ keeps net
classes and design rules in the .kicad_pro next to the board - board.Save() alone drops them, which made DRC judge
everything against KiCad's 0.2 mm defaults: CT trap 2026-10-16).

SBC-1 (adapted): 2-layer 1.6 mm, 1 oz both sides (JLC 2-layer standard), no via fill -> vias 0.6 / 0.3 mm, never in a
pad. Clearance 0.15 mm everywhere: the finest pad gaps are RP2350B QFN-80 0.4 mm pitch (0.2 mm pads -> 0.2 mm gap),
W5500 LQFP-48 0.5 mm (0.3 mm pads), MAX98357A TQFN-16 / TPS259531 WSON-8 0.5 mm (0.25 mm pads); a class clearance
above the pad gap makes the router refuse those pins.
Class widths fit the FINEST pad their nets touch (CT rule; pfr2 raises current nets to current_budget and necks <= NECK_MM):
  Power     VBUS_HOST (J9 micro-B pin 1 0.40 mm)                                       0.40 mm (1 A needs 0.286)
  Audio     AMP_OUTP / AMP_OUTN / SPK_P / SPK_N (U8 TQFN 0.25 mm pads, 0.5 mm pitch)    0.30 mm (1 A needs 0.286)
  Power5    +5V_SYS (2 A eFuse output; U1 WSON / U8 TQFN 0.25 mm pads are reached by the completion router's neck)
            and +5V_IN while it is routed (no power_copper zone yet)                   0.50 mm
  PowerLight +5V_RGB / +5V_PF / LED_*_K: placeholder until the lead's power_copper.py lays them as LOCKED wide copper
            (2-4 A); the router never touches locked items                             0.60 mm
  Rail      +3V3 / +3V3A / +1V1 (<= 0.3 A; must enter the QFN-80 0.2 mm pads)          0.20 mm
  Default   signals                                                                    0.20 mm (0.15 with SBC_NARROW=1)
Required widths per net: scripts/current_budget.py (IPC-2152) - qa_copper_landing TRACK-WIDTH checks them.
"""
import os

import pcbnew

NARROW = os.environ.get("SBC_NARROW") == "1"     # experiment switch: narrower default tracks for routability


def mm(v):
    return pcbnew.FromMM(v)


POWER = ["VBUS_HOST"]
AUDIO = ["AMP_OUTP", "AMP_OUTN", "SPK_P", "SPK_N"]
POWER5 = ["+5V_SYS", "+5V_IN"]
POWER_LIGHT = ["+5V_RGB", "+5V_PF", "LED_R_K", "LED_G_K", "LED_B_K", "LED_PF_K"]
RAIL = ["+3V3", "+3V3A", "+1V1", "VBUS_DBG", "GND"]
CLASS_W = {"Power": 0.4, "Audio": 0.3, "Power5": 0.5, "PowerLight": 0.6, "Rail": 0.2,
           "Default": 0.15 if NARROW else 0.2}


def apply(board):
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(4)                  # JLC04161H-7628 4-layer 1.6 mm (pass 5, owner 2026-10-26)
    board.SetCopperLayerCount(4)
    ds.SetBoardThickness(mm(1.6))
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_MinClearance = mm(0.15)
    ds.m_ViasMinSize = mm(0.6)
    ds.m_ViasMinAnnularWidth = mm(0.15)
    ds.m_MinThroughDrill = mm(0.3)
    ds.m_HoleClearance = mm(0.25)
    ds.m_HoleToHoleMin = mm(0.25)
    ds.m_CopperEdgeClearance = mm(0.3)
    ds.m_MinResolvedSpokes = 1                 # small 0402 pads may only reach the pour with one spoke
    ds.m_MinSilkTextHeight = mm(0.6)
    ds.m_MinSilkTextThickness = mm(0.1)
    ns = ds.m_NetSettings
    d = ns.GetDefaultNetclass()
    d.SetClearance(mm(0.15))
    d.SetTrackWidth(mm(CLASS_W["Default"]))
    d.SetViaDiameter(mm(0.6))
    d.SetViaDrill(mm(0.3))

    def mk(name, clr=0.15, via=0.6, drill=0.3):
        nc = pcbnew.NETCLASS(name)
        nc.SetTrackWidth(mm(CLASS_W[name]))
        nc.SetClearance(mm(clr))
        nc.SetViaDiameter(mm(via))
        nc.SetViaDrill(mm(drill))
        ns.SetNetclass(name, nc)
    mk("Power")
    mk("Audio")
    mk("Power5", via=0.8, drill=0.4)
    mk("PowerLight", via=0.8, drill=0.4)
    mk("Rail")
    ns.ClearNetclassPatternAssignments()
    for cls, nets in (("Power", POWER), ("Audio", AUDIO), ("Power5", POWER5), ("PowerLight", POWER_LIGHT),
                      ("Rail", RAIL)):
        for n in nets:
            ns.SetNetclassPatternAssignment(n, cls)
    ns.RecomputeEffectiveNetclasses()
    board.SynchronizeNetsAndNetClasses(True)


def save(board, path):
    if not pcbnew.SaveBoard(str(path), board):
        raise SystemExit(f"SaveBoard failed: {path}")
