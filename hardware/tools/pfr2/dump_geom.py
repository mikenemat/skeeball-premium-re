# ported from din-relay-8ch/tools/pfr2/dump_geom.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Dump a KiCad board's copper/rule geometry to JSON for the CPython router/analysers.

KiCad Python:  local_run.py dump_geom.py BOARD OUT.json
Everything in mm, KiCad board frame (y down). Polygons are lists of rings [[x,y],...]; zone/pad shapes give
"outlines": [{"outline": ring, "holes": [ring, ...]}, ...].
"""
import json
import sys
import hashlib
import pcbnew

mm = pcbnew.ToMM
board_path, out_path = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(board_path)
COPPER = [l for l in range(pcbnew.PCB_LAYER_ID_COUNT) if pcbnew.IsCopperLayer(l) and b.IsLayerEnabled(l)]
LNAME = {l: b.GetLayerName(l) for l in COPPER}


def ring(o):
    return [[round(mm(o.CPoint(k).x), 5), round(mm(o.CPoint(k).y), 5)] for k in range(o.PointCount())]


def polyset(ps):
    out = []
    for i in range(ps.OutlineCount()):
        out.append({"outline": ring(ps.Outline(i)), "holes": [ring(ps.Hole(i, h)) for h in range(ps.HoleCount(i))]})
    return out


ds = b.GetDesignSettings()
import os
pro = json.load(open(os.path.splitext(board_path)[0] + ".kicad_pro", encoding="utf-8"))
CLS = {c["name"]: c for c in pro["net_settings"]["classes"]}
nets = {}
# every class of a net (KiCad composite "ISLAND,ISLAND_HIZ"; "class" stays the primary one): the pickup rules bind the
# secondary ISLAND_HIZ class (scripts/pcb_pickup_rules.py), read by pfr2.py / plan_check.py
ASSIGN = {k: (v if isinstance(v, list) else [v]) for k, v in (pro["net_settings"].get("netclass_assignments") or {}).items()}
for code, n in b.GetNetsByNetcode().items():
    try:
        full = n.GetNetClassName()
    except Exception:
        full = "Default"
    cname = full.split(",")[0] if full else "Default"
    c = CLS.get(cname, CLS["Default"])
    allc = sorted(set([x for x in (full or "Default").split(",") if x] + ASSIGN.get(n.GetNetname(), [])))
    nets[code] = {"name": n.GetNetname(), "class": cname, "classes": allc, "clearance": c.get("clearance"),
                  "track": c.get("track_width"), "via_d": c.get("via_diameter"), "via_drill": c.get("via_drill")}

pads = []
fps = []
for fp in b.GetFootprints():
    cy = {}
    for side, L in (("F", pcbnew.F_CrtYd), ("B", pcbnew.B_CrtYd)):
        try:
            c = fp.GetCourtyard(L)
            if c.OutlineCount():
                cy[side] = polyset(c)
        except Exception:
            pass
    pos = fp.GetPosition()
    fps.append({"ref": fp.GetReference(), "fpid": fp.GetFPIDAsString(), "x": mm(pos.x), "y": mm(pos.y),
                "rot": fp.GetOrientationDegrees(), "side": "B" if fp.IsFlipped() else "F", "courtyard": cy,
                "locked": fp.IsLocked(), "value": fp.GetValue(), "attr": fp.GetAttributes(),
                "dnp": bool(fp.IsDNP()) if hasattr(fp, "IsDNP") else False})
    for p in fp.Pads():
        q = p.GetPosition()
        shapes = {}
        for L in COPPER:
            if p.IsOnLayer(L) and (p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH):
                # flashed copper on inner layers may be removed (unconnected-layer removal); record the flag
                shapes[LNAME[L]] = polyset(p.GetEffectivePolygon(L))
        drill = None
        if p.GetDrillSizeX() > 0:
            drill = [mm(p.GetDrillSizeX()), mm(p.GetDrillSizeY())]
        pads.append({"ref": fp.GetReference(), "num": p.GetNumber(), "uuid": p.m_Uuid.AsString(),
                     "net": p.GetNetCode(), "x": mm(q.x), "y": mm(q.y), "attr": int(p.GetAttribute()),
                     "drill": drill, "shapes": shapes, "rot": p.GetOrientationDegrees()})

tracks, vias, arcs = [], [], []
for t in b.GetTracks():
    c = t.GetClass()
    if c == "PCB_VIA":
        p = t.GetPosition()
        top, bot = t.TopLayer(), t.BottomLayer()
        vias.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetCode(), "x": mm(p.x), "y": mm(p.y),
                     "d": mm(t.GetWidth(pcbnew.F_Cu)), "drill": mm(t.GetDrillValue()), "type": int(t.GetViaType()),
                     "top": LNAME.get(top), "bot": LNAME.get(bot), "locked": t.IsLocked(),
                     "flags": [int(t.GetFillingMode()), int(t.GetCappingMode()), bool(t.GetPrimaryDrillFilledFlag()),
                               bool(t.GetPrimaryDrillCappedFlag())]})
    elif c == "PCB_ARC":
        s, m, e = t.GetStart(), t.GetMid(), t.GetEnd()
        arcs.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetCode(), "layer": t.GetLayerName(),
                     "s": [mm(s.x), mm(s.y)], "m": [mm(m.x), mm(m.y)], "e": [mm(e.x), mm(e.y)], "w": mm(t.GetWidth()),
                     "locked": t.IsLocked()})
    else:
        s, e = t.GetStart(), t.GetEnd()
        tracks.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetCode(), "layer": t.GetLayerName(),
                       "s": [mm(s.x), mm(s.y)], "e": [mm(e.x), mm(e.y)], "w": mm(t.GetWidth()), "locked": t.IsLocked()})

zones = []
for z in b.Zones():
    rec = {"uuid": z.m_Uuid.AsString(), "net": z.GetNetCode(), "name": z.GetZoneName(),
           "rule_area": bool(z.GetIsRuleArea()), "priority": z.GetAssignedPriority(),
           "layers": [LNAME.get(l, b.GetLayerName(l)) for l in z.GetLayerSet().Seq()],
           "outline": polyset(z.Outline()), "locked": z.IsLocked()}
    if z.GetIsRuleArea():
        rec.update({"no_tracks": z.GetDoNotAllowTracks(), "no_vias": z.GetDoNotAllowVias(),
                    "no_pads": z.GetDoNotAllowPads(), "no_zones": z.GetDoNotAllowZoneFills(),
                    "no_fp": z.GetDoNotAllowFootprints()})
    else:
        rec["fills"] = {}
        for L in COPPER:
            if z.IsOnLayer(L):
                rec["fills"][LNAME[L]] = polyset(z.GetFilledPolysList(L))
        rec["min_width"] = mm(z.GetMinThickness())
        rec["clearance"] = mm(z.GetLocalClearance()) if z.GetLocalClearance() is not None else None
        rec["fill_mode"] = int(z.GetFillMode())
        rec["pad_conn"] = int(z.GetPadConnection())
    zones.append(rec)

edge = b.GetBoardEdgesBoundingBox()
outl = pcbnew.SHAPE_POLY_SET()
b.GetBoardPolygonOutlines(outl, True)
out = {"board": board_path, "sha256": hashlib.sha256(open(board_path, "rb").read()).hexdigest(),
       "layers": [LNAME[l] for l in COPPER], "nets": nets, "pads": pads, "footprints": fps, "tracks": tracks,
       "arcs": arcs, "vias": vias, "zones": zones, "outline": polyset(outl),
       "rules": {"min_clearance": mm(ds.m_MinClearance), "min_track": mm(ds.m_TrackMinWidth),
                 "edge_clearance": mm(ds.m_CopperEdgeClearance), "hole_clearance": mm(ds.m_HoleClearance),
                 "hole_to_hole": mm(ds.m_HoleToHoleMin)}}
json.dump(out, open(out_path, "w"))
print("dumped", len(pads), "pads", len(tracks), "tracks", len(arcs), "arcs", len(vias), "vias", len(zones), "zones")
