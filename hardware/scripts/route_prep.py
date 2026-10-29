"""Prepare a placed SBC-1 board for routing (KiCad Python; new in SBC-1, 2026-10-26, from CT placement_main.py
edge_keepout()). Idempotent.

    python scripts/local_run.py route_prep.py BOARD

* paused parts (board_const.PAUSED_REFS, none since 2026-10-27) are removed from the routing board;
* EDGE_KEEPOUT: no-track / no-via band board_const.EDGE_BAND_MM wide along every edge (CT trap: a router keeps only
  the class clearance to the outline; the copper-edge rule is 0.3 mm). Pads are allowed (J9 / J1 sit at the edge);
* pcb_rules.apply + pcbnew.SaveBoard (net classes live in the .kicad_pro).
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as K  # noqa: E402
import pcb_rules  # noqa: E402

import math  # noqa: E402

# DECISIONS #3: (ref, EP pad, via offsets in the pad frame) - U5 3 x 3 at 1.0 mm (Raspberry Pi 2-layer RP2350 reference),
# U8 one via (1.23 mm EP), U1 two along the 1.6 mm axis (0.9 x 1.6 EP; disc 0.05 inside the pad)
EP_VIAS = [("U5", "81", [(dx, dy) for dx in (-1.0, 0.0, 1.0) for dy in (-1.0, 0.0, 1.0)]),
           # q6 QA A6 tried 4 (2 x 2 at +-0.31): a 0.6 / 0.3 via (min_via_diameter 0.6, hole 0.3, hole-to-hole
           # 0.25) cannot sit 4 times inside the 1.23 mm EP with the gate's 0.05 mm margin -> one stays
           ("U8", "17", [(0.0, 0.0)]),
           ("U1", "9", [(0.0, -0.4), (0.0, 0.4)])]
GRAVE = []          # KiCad 10 Python: keep removed items referenced until exit (CT GRAVE)


def mm(v):
    return pcbnew.FromMM(v)


def rule_area(board, name, rect, poly=None):
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetZoneName() == name:
            return 0
    if poly is None:
        x0, y0, x1, y1 = rect
        poly = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowZoneFills(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    for L in board.GetEnabledLayers().CuStack():     # every copper layer (4-layer, pass 5: In1 / In2 too)
        ls.AddLayer(L)
    z.SetLayerSet(ls)
    z.SetZoneName(name)
    o = z.Outline()
    o.NewOutline()
    for x, y in poly:
        o.Append(mm(x), mm(y))
    board.Add(z)
    return 1


# plane voids (adversarial review L1 / F06, q5 2026-10-27): WIZnet hardware design guide + HanRun magjack practice = no
# GND / power plane under the transformer / jack body. J3 (HR963380AE vertical, origin (31.5, 16.375)): the body
# between its LED / shield row (y <= 10.6) and its contact-pin row (y >= 23.4) gets no zone fill on In1 / In2 / B
# (tracks allowed; the pin rows keep their reference plane)
PLANE_VOIDS = [("J3_PLANE_VOID", (23.0, 11.5, 40.0, 22.8), ("In1.Cu", "In2.Cu", "B.Cu"))]


def plane_void(board, name, rect, layers):
    if any(z.GetIsRuleArea() and z.GetZoneName() == name for z in board.Zones()):
        return 0
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    for nm in layers:
        ls.AddLayer(board.GetLayerID(nm))
    z.SetLayerSet(ls)
    z.SetZoneName(name)
    o = z.Outline()
    o.NewOutline()
    x0, y0, x1, y1 = rect
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(mm(x), mm(y))
    board.Add(z)
    return 1


def main():
    path = Path(sys.argv[1])
    b = pcbnew.LoadBoard(str(path))
    gone = [fp for fp in b.GetFootprints() if fp.GetReference() in K.PAUSED_REFS]
    for fp in gone:
        b.Remove(fp)
        GRAVE.append(fp)
    L, W, e = K.L, K.W, K.EDGE_BAND_MM
    n = 0
    for k, r in enumerate(((0, 0, L, e), (0, W - e, L, W), (0, 0, e, W), (L - e, 0, L, W))):
        n += rule_area(b, f"EDGE_KEEPOUT_{k}", r)
    # NPTH keep-outs: a router keeps only the class clearance (0.15) to a non-plated hole, KiCad wants the hole
    # clearance 0.25 and treats the hole as a board edge (copper-edge 0.3): r1h left VBUS_DBG 0.15 mm from J10's pegs
    import math
    for fp in b.GetFootprints():
        for pd in fp.Pads():
            if pd.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                continue
            ds = pd.GetDrillSize()
            r = pcbnew.ToMM(max(ds.x, ds.y)) / 2 + K.EDGE_BAND_MM          # = the edge band (0.3 rule + margin)
            cx, cy = pcbnew.ToMM(pd.GetPosition().x), pcbnew.ToMM(pd.GetPosition().y)
            n += rule_area(b, f"NPTH_KEEPOUT_{fp.GetReference()}_{pd.GetNumber() or 'x'}_{cx:.2f}_{cy:.2f}", None,
                           [(cx + r / math.cos(math.pi / 16) * math.cos(2 * math.pi * k / 16),
                             cy + r / math.cos(math.pi / 16) * math.sin(2 * math.pi * k / 16)) for k in range(16)])
    # EP thermal vias (DECISIONS #3, the one via-in-pad exception; qa_layout_quality.VIA_INPAD_EP_PADS): plain 0.6 / 0.3
    # vias, LOCKED (the router / cleanup keep them, like CT's EP via grids); offsets in the pad frame (mm)
    have_v = {(t.GetPosition().x, t.GetPosition().y) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T}
    nv = 0
    for ref, num, offs in EP_VIAS:
        fp = b.FindFootprintByReference(ref)
        pad = next(p for p in fp.Pads() if p.GetNumber() == num)
        ang = math.radians(-pad.GetOrientationDegrees())
        for dx, dy in offs:
            x = pad.GetPosition().x + mm(dx * math.cos(ang) - dy * math.sin(ang))
            y = pad.GetPosition().y + mm(dx * math.sin(ang) + dy * math.cos(ang))
            if (x, y) in have_v:
                continue
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(x, y))
            v.SetWidth(mm(0.6))
            v.SetDrill(mm(0.3))
            v.SetNet(pad.GetNet())
            v.SetLocked(True)
            b.Add(v)
            nv += 1
    print(f"route_prep: {nv} EP thermal vias (locked)")
    for name, rect, layers in PLANE_VOIDS:
        n += plane_void(b, name, rect, layers)
    # 4-layer (pass 5): GND_IN1 = the solid In1.Cu GND plane (never routed; every GND pad's drop via lands in it, solid
    # via connection), + the B.Cu GND pour (soft, refilled). No F.Cu pour (F.Cu = signals + parts, owner stack-up).
    # All priority 0 (the lead's +5V_IN zones are priority 2), filled BEFORE routing (pfr2's plane model needs the fill)
    have = {z.GetZoneName() for z in b.Zones() if not z.GetIsRuleArea()}
    for name, lay in (("GND_IN1", b.GetLayerID("In1.Cu")), ("GND_B", pcbnew.B_Cu)):
        if name in have:
            continue
        z = pcbnew.ZONE(b)
        z.SetLayer(lay)
        z.SetNet(b.FindNet("GND"))
        z.SetZoneName(name)
        z.SetAssignedPriority(0)
        z.SetLocalClearance(mm(0.25))
        z.SetMinThickness(mm(0.25))
        z.SetThermalReliefGap(mm(0.3))
        z.SetThermalReliefSpokeWidth(mm(0.4))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if name == "GND_IN1" else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        o = z.Outline()
        o.NewOutline()
        for x, y in ((0, 0), (K.L, 0), (K.L, K.W), (0, K.W)):
            o.Append(mm(x), mm(y))
        b.Add(z)
        n += 1
    pcb_rules.apply(b)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcb_rules.save(b, path)
    print(f"route_prep: removed {len(gone)} paused parts ({' '.join(f.GetReference() for f in gone)}), "
          f"{n} rule areas added -> {path.name}")


if __name__ == "__main__":
    main()
