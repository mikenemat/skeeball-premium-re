# ported from din8r-chassis-thermal/scripts/cu_cleanup/dump_geom.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R tools/pfr2/dump_geom.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN)
"""Dump a KiCad board's copper / rule geometry to JSON for the CPython analysers (scripts/copper_cleanup.py).

KiCad Python:  py scripts/local_run.py cu_cleanup/kicad_worker.py dump BOARD OUT.json   (or dump(board, out) in-process)
Everything in mm, KiCad board frame (y down). Polygons are lists of rings [[x,y],...]; zone / pad shapes give
"outlines": [{"outline": ring, "holes": [ring, ...]}, ...].

CT adaptation (2026-10-17): a function (the caller owns the ONE LoadBoard of its process); net classes from the
board's own .kicad_pro (CT classes Default / Power / Power12 / PowerFan / Rail, scripts/pcb_rules.py); pads carry their
local clearance override ("clr", mm or None) for the cleanup's clearance model; no DIN-8R pickup-rule class merging.
"""
import hashlib
import json
import os

import pcbnew

mm = pcbnew.ToMM


def _ring(o):
    return [[round(mm(o.CPoint(k).x), 5), round(mm(o.CPoint(k).y), 5)] for k in range(o.PointCount())]


def _polyset(ps):
    out = []
    for i in range(ps.OutlineCount()):
        out.append({"outline": _ring(ps.Outline(i)), "holes": [_ring(ps.Hole(i, h)) for h in range(ps.HoleCount(i))]})
    return out


def _opt_mm(v):
    try:
        return None if v is None else mm(int(v))
    except Exception:
        return None


def geom(b, board_path):
    """-> the geometry dict of an already loaded board b (board_path: its file, for the .kicad_pro and sha)"""
    COPPER = [l for l in range(pcbnew.PCB_LAYER_ID_COUNT) if pcbnew.IsCopperLayer(l) and b.IsLayerEnabled(l)]
    LNAME = {l: b.GetLayerName(l) for l in COPPER}
    ds = b.GetDesignSettings()
    pro_path = os.path.splitext(board_path)[0] + ".kicad_pro"
    with open(pro_path, encoding="utf-8") as f:
        pro = json.load(f)
    CLS = {c["name"]: c for c in pro["net_settings"]["classes"]}
    nets = {}
    for code, n in b.GetNetsByNetcode().items():
        try:
            full = n.GetNetClassName()
        except Exception:
            full = "Default"
        cname = full.split(",")[0] if full else "Default"
        c = CLS.get(cname, CLS["Default"])
        allc = sorted(set(x for x in (full or "Default").split(",") if x))
        nets[code] = {"name": n.GetNetname(), "class": cname, "classes": allc, "clearance": c.get("clearance"),
                      "track": c.get("track_width"), "via_d": c.get("via_diameter"), "via_drill": c.get("via_drill")}

    pads, fps = [], []
    for fp in b.GetFootprints():
        cy = {}
        for side, L in (("F", pcbnew.F_CrtYd), ("B", pcbnew.B_CrtYd)):
            try:
                c = fp.GetCourtyard(L)
                if c.OutlineCount():
                    cy[side] = _polyset(c)
            except Exception:
                pass
        pos = fp.GetPosition()
        fps.append({"ref": fp.GetReference(), "fpid": fp.GetFPIDAsString(), "x": mm(pos.x), "y": mm(pos.y),
                    "rot": fp.GetOrientationDegrees(), "side": "B" if fp.IsFlipped() else "F", "courtyard": cy,
                    "locked": fp.IsLocked(), "value": fp.GetValue(), "attr": fp.GetAttributes()})
        for p in fp.Pads():
            q = p.GetPosition()
            shapes = {}
            for L in COPPER:
                if p.IsOnLayer(L) and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                    shapes[LNAME[L]] = _polyset(p.GetEffectivePolygon(L))
            drill = None
            if p.GetDrillSizeX() > 0:
                drill = [mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())]
            try:
                clr = _opt_mm(p.GetLocalClearance())
            except Exception:
                clr = None
            pads.append({"ref": fp.GetReference(), "num": p.GetNumber(), "uuid": p.m_Uuid.AsString(),
                         "net": p.GetNetCode(), "x": mm(q.x), "y": mm(q.y), "attr": int(p.GetAttribute()),
                         "drill": drill, "shapes": shapes, "rot": p.GetOrientationDegrees(), "clr": clr})

    tracks, vias, arcs = [], [], []
    for t in b.GetTracks():
        c = t.GetClass()
        if c == "PCB_VIA":
            p = t.GetPosition()
            top, bot = t.TopLayer(), t.BottomLayer()
            vias.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetCode(), "x": mm(p.x), "y": mm(p.y),
                         "d": mm(t.GetWidth(pcbnew.F_Cu)), "drill": mm(t.GetDrillValue()), "type": int(t.GetViaType()),
                         "top": LNAME.get(top), "bot": LNAME.get(bot), "locked": bool(t.IsLocked())})
        elif c == "PCB_ARC":
            s, m, e = t.GetStart(), t.GetMid(), t.GetEnd()
            arcs.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetCode(), "layer": t.GetLayerName(),
                         "s": [mm(s.x), mm(s.y)], "m": [mm(m.x), mm(m.y)], "e": [mm(e.x), mm(e.y)],
                         "w": mm(t.GetWidth()), "locked": bool(t.IsLocked())})
        else:
            s, e = t.GetStart(), t.GetEnd()
            tracks.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetCode(), "layer": t.GetLayerName(),
                           "s": [mm(s.x), mm(s.y)], "e": [mm(e.x), mm(e.y)], "w": mm(t.GetWidth()),
                           "locked": bool(t.IsLocked())})

    zones = []
    for z in b.Zones():
        rec = {"uuid": z.m_Uuid.AsString(), "net": z.GetNetCode(), "name": z.GetZoneName(),
               "rule_area": bool(z.GetIsRuleArea()), "priority": z.GetAssignedPriority(),
               "layers": [LNAME.get(l, b.GetLayerName(l)) for l in z.GetLayerSet().Seq()],
               "outline": _polyset(z.Outline()), "locked": z.IsLocked()}
        if z.GetIsRuleArea():
            rec.update({"no_tracks": z.GetDoNotAllowTracks(), "no_vias": z.GetDoNotAllowVias(),
                        "no_pads": z.GetDoNotAllowPads(), "no_zones": z.GetDoNotAllowZoneFills(),
                        "no_fp": z.GetDoNotAllowFootprints()})
        else:
            rec["fills"] = {}
            for L in COPPER:
                if z.IsOnLayer(L):
                    rec["fills"][LNAME[L]] = _polyset(z.GetFilledPolysList(L))
            rec["min_width"] = mm(z.GetMinThickness())
            rec["clearance"] = _opt_mm(z.GetLocalClearance())
        zones.append(rec)

    outl = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(outl, True)
    with open(board_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {"board": board_path, "sha256": sha,
            "layers": [LNAME[l] for l in COPPER], "nets": nets, "pads": pads, "footprints": fps, "tracks": tracks,
            "arcs": arcs, "vias": vias, "zones": zones, "outline": _polyset(outl),
            "rules": {"min_clearance": mm(ds.m_MinClearance), "min_track": mm(ds.m_TrackMinWidth),
                      "edge_clearance": mm(ds.m_CopperEdgeClearance), "hole_clearance": mm(ds.m_HoleClearance),
                      "hole_to_hole": mm(ds.m_HoleToHoleMin)}}


def dump(board_path, out_path, b=None):
    b = b if b is not None else pcbnew.LoadBoard(str(board_path))
    out = geom(b, str(board_path))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out
