_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]   # project root (tools/pfr2/ -> ..)
# ported from din-relay-8ch/tools/pfr2/pfr_import.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Import a pfr.py routing plan into a copy of the board (KiCad Python via local_run.py).

  local_run.py pfr_import.py SRC_DIR PLAN.json OUT_DIR
Adds the plan's tracks / vias natively (deterministic UUIDs; SBC-1: plain through vias, NO fill / cap - JLC 2-layer),
proves all prior copper unchanged and all new copper still on its net after refill / save / reload, refills only the
SELV zones (force pours and GND_ISO untouched). Writes OUT_DIR/import.json.
"""
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path
import pcbnew as p

NS = uuid.UUID("0c6b8f4e-2d0a-4d84-9a1e-6f0f2d5b7a11")
FORCE = set()        # SBC-1: no force pours; the LOCKED power_copper +5V_IN zones refill like any zone (unchanged)
MM = p.FromMM



def stale_rule_areas(areas):
    """[(uuid, name)] of the board's rule areas -> the ones this import replaces: ONLY PWR_NECK (regenerated from the
    plan's neck boxes). Every other rule area is preserved, empty or not (M1 2026-10-04: the two V_PULL_LEAF_VIP areas
    were stripped for holding no via, and apply_rules then pruned their DRU rule; fixture test_pfr_import_areas.py)."""
    return [(u, nm) for u, nm in areas if nm == "PWR_NECK"]

def snap(b):
    out = {}
    for t in b.GetTracks():
        v = t.GetClass() == "PCB_VIA"
        out[t.m_Uuid.AsString()] = (t.GetNetname(), t.GetLayer() if not v else -1, t.GetStart().x, t.GetStart().y,
                                    t.GetEnd().x, t.GetEnd().y, t.GetWidth(p.F_Cu) if v else t.GetWidth(),
                                    (int(t.GetFillingMode()), int(t.GetCappingMode())) if v else None)
    return out


def main():
    src_dir, plan_p, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    BOARD = "skeeball-controller.kicad_pcb"
    out.mkdir(parents=True, exist_ok=False)
    for q in src_dir.iterdir():
        if q.is_file() and (q.suffix == ".kicad_sch" or q.name in ("main-design.json", "fp-lib-table", "sym-lib-table")
                            or (q.suffix in (".kicad_pro", ".kicad_dru") and q.stem == "skeeball-controller")):
            shutil.copy2(q, out / q.name)
    shutil.copy2(src_dir / BOARD, out / BOARD)
    dst = out / BOARD
    plan = json.loads(plan_p.read_text())
    # a plan without neck boxes (e.g. smooth.py) would silently strip every PWR_NECK area and re-add none
    assert "neck_boxes" in plan, "plan has no neck_boxes key: copy it from the stage's pfr2 plan (same pads)"
    # SBC-1: no PWR_NECK nets, so an empty list is legal
    # rule areas bound to part positions: PWR_NECK only (regenerated from the plan's boxes = pcb_power.neck_areas on the
    # current pads); every other rule area - via-in-pad exception areas included, even with no via yet - is preserved
    b = p.LoadBoard(str(dst))
    stale = stale_rule_areas([(z.m_Uuid.AsString(), z.GetZoneName()) for z in b.Zones() if z.GetIsRuleArea()])
    del b
    if stale:
        sys.path.insert(0, str(_ROOT / "scripts"))
        from pcb_redesign import remove_saved_items
        txt = dst.read_text(encoding="utf-8")
        txt2 = remove_saved_items(txt, {u for u, _ in stale})
        txt2 = txt2[0] if isinstance(txt2, tuple) else txt2
        dst.write_text(txt2, encoding="utf-8")
    b = p.LoadBoard(str(dst))
    assert not any(z.GetIsRuleArea() and z.GetZoneName() == "PWR_NECK" for z in b.Zones()), "PWR_NECK not stripped"
    old = snap(b)
    lid = {b.GetLayerName(l): l for l in range(p.PCB_LAYER_ID_COUNT) if p.IsCopperLayer(l)}
    added = []
    for t in plan["tracks"]:
        q = p.PCB_TRACK(b)
        q.SetStart(p.VECTOR2I(MM(t["s"][0]), MM(t["s"][1])))
        q.SetEnd(p.VECTOR2I(MM(t["e"][0]), MM(t["e"][1])))
        q.SetWidth(MM(t["w"]))
        q.SetLayer(lid[t["layer"]])
        q.SetNet(b.FindNet(t["net"]))
        u = str(uuid.uuid5(NS, json.dumps(["t", t["net"], t["layer"], t["s"], t["e"], t["w"]])))
        q.SetUuidDirect(p.KIID(u))
        b.Add(q)
        added.append((u, t["net"]))
    for v in plan["vias"]:
        q = p.PCB_VIA(b)
        q.SetPosition(p.VECTOR2I(MM(v["x"]), MM(v["y"])))
        q.SetViaType(p.VIATYPE_THROUGH)
        q.SetLayerPair(p.F_Cu, p.B_Cu)
        q.SetWidth(p.F_Cu, MM(v["d"]))
        q.SetDrill(MM(v["drill"]))
        q.SetNet(b.FindNet(v["net"]))
        u = str(uuid.uuid5(NS, json.dumps(["v", v["net"], v["x"], v["y"], v["d"], v["drill"]])))
        q.SetUuidDirect(p.KIID(u))
        b.Add(q)
        added.append((u, v["net"]))
    for nb in plan.get("neck_boxes", []):
        z = p.ZONE(b)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowZoneFills(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetZoneName("PWR_NECK")
        z.SetLayer(lid[nb["layer"]])
        x0, y0, x1, y1 = nb["box"]
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            ol.Append(MM(x), MM(y))
        z.SetUuidDirect(p.KIID(str(uuid.uuid5(NS, json.dumps(["neck", nb["net"], nb["layer"], nb["ref"], nb["pad"]])))))
        b.Add(z)
    p.SaveBoard(str(dst), b)
    b = p.LoadBoard(str(dst))
    p.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() not in FORCE])
    p.SaveBoard(str(dst), b)
    b = p.LoadBoard(str(dst))
    b.BuildConnectivity()
    now = snap(b)
    assert all(now.get(k) == v for k, v in old.items()), "prior copper changed"
    bad = [(u, n, now.get(u, ("missing",))[0]) for u, n in added if now.get(u, ("missing",))[0] != n]
    assert not bad, ("new copper re-netted / missing", bad[:5])
    rep = {"source": str(src_dir / BOARD), "source_sha256": hashlib.sha256((src_dir / BOARD).read_bytes()).hexdigest(),
           "plan": str(plan_p), "plan_sha256": hashlib.sha256(plan_p.read_bytes()).hexdigest(),
           "added_tracks": len(plan["tracks"]), "added_vias": len(plan["vias"]),
           "unconnected": b.GetConnectivity().GetUnconnectedCount(True), "output": str(dst),
           "rule_areas_removed": stale, "neck_boxes_added": len(plan.get("neck_boxes", [])),
           "output_sha256": hashlib.sha256(dst.read_bytes()).hexdigest()}
    (out / "import.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
