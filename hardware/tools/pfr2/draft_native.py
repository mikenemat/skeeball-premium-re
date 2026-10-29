_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]   # project root (tools/pfr2/ -> ..)
# ported from din-relay-8ch/tools/pfr2/draft_native.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Merged MAIN draft: native board steps (KiCad Python via local_run.py). Driven by build_draft.py.

  local_run.py draft_native.py place PLAN.json SRC_DIR OUT_DIR   copy revC-A1, swap / insert / move every part, nets +
                                                                 fields per the generator, rip / re-land copper
  local_run.py draft_native.py refill BOARD                      native refill of every copper zone
  local_run.py draft_native.py peel BOARD REPORT.json [--loops]  qa_copper_landing-driven peel of loose copper (TRACK-END,
                                                                 VIA-LAND) and, with --loops, LOOP breaking
  local_run.py draft_native.py delete BOARD PLAN.json            delete an apply_plan-style delete list by UUID
  local_run.py draft_native.py y600ko BOARD                      Y600 "no foreign copper" rule area + DRU rule
  local_run.py draft_native.py linecut BOARD REPORT.json REFS     re-cut the LINE zone holes around new / moved pads
  local_run.py draft_native.py paths BOARD NETLIST.net DESIGN     footprint KIID paths + NC pin nets from a netlist

Native edits only: items are deleted by UUID in the serialized board (pcb_redesign.remove_saved_items, never SWIG
Remove / Delete), added with board.Add, saved with pcbnew.SaveBoard. No KiCad CLI --save-board.
"""
import hashlib
import json
import math
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "tools/pfr2"))
import pcbnew as p
import board_const  # noqa: F401  (SBC-1: tools/pylib shapely for KiCad's Python)
from pcb_redesign import remove_saved_items
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

BOARD = "skeeball-controller.kicad_pcb"
TOOLS = Path(__file__).resolve().parent.parent / "tools"
if not TOOLS.exists():                         # a sandbox copy (pfr2-speed): the live tools folder
    TOOLS = (_ROOT / "tools/pfr2")
MM, mm = p.FromMM, p.ToMM
KLIB = Path("C:/Program Files/KiCad/10.0/share/kicad/footprints")
HERE = Path(__file__).resolve().parent
DIN8R_LIB = HERE / "lib" / "din8r.pretty"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def V(x, y):
    return p.VECTOR2I(MM(x), MM(y))


def to_shapely(ps):
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        ring = [(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
        holes = [[(mm(ps.Hole(i, h).CPoint(k).x), mm(ps.Hole(i, h).CPoint(k).y)) for k in range(ps.Hole(i, h).PointCount())]
                 for h in range(ps.HoleCount(i))]
        if len(ring) >= 3:
            g = Polygon(ring, [x for x in holes if len(x) >= 3])
            out.append(g if g.is_valid else g.buffer(0))
    return unary_union(out) if out else Polygon()


def cu_layers(b):
    return [L for L in range(p.PCB_LAYER_ID_COUNT) if p.IsCopperLayer(L) and b.IsLayerEnabled(L)]


def pad_polys(pad, layers):
    """{layer name: shapely polygon} of a pad's copper on the layers it occupies."""
    b = pad.GetBoard()
    out = {}
    for L in layers:
        if pad.IsOnLayer(L) and pad.GetAttribute() != p.PAD_ATTRIB_NPTH:
            g = to_shapely(pad.GetEffectivePolygon(L))
            if not g.is_empty:
                out[b.GetLayerName(L)] = g
    return out


def lib_path(fpid):
    lib, name = fpid.split(":", 1)
    return (DIN8R_LIB if lib == "din8r" else KLIB / f"{lib}.pretty"), name


def load_fp(fpid):
    lp, name = lib_path(fpid)
    fp = p.FootprintLoad(str(lp), name)
    if fp is None:
        raise RuntimeError(f"footprint not found: {fpid} ({lp})")
    fp.SetFPID(p.LIB_ID(fpid.split(":", 1)[0], name))
    return fp


def pad_err(f, exp):
    return max(math.hypot(mm(q.GetPosition().x) - exp[q.GetNumber()][0], mm(q.GetPosition().y) - exp[q.GetNumber()][1])
               for q in f.Pads() if q.GetNumber() in exp)


def pose(f, x, y, side, pads=None, rot=None):
    """put footprint f at (x, y) on side; orientation from the planned pad centres (asserted <= 0.01 mm) or rot."""
    want_b = side == "B"
    if f.IsFlipped() != want_b:
        f.Flip(f.GetPosition(), p.FLIP_DIRECTION_LEFT_RIGHT)
    f.SetPosition(V(x, y))
    if not pads:
        f.SetOrientationDegrees(rot or 0.0)
        return 0.0
    cands = ([rot] if rot is not None else []) + [0.0, 90.0, 180.0, 270.0]
    best = None
    for r in cands:
        f.SetOrientationDegrees(r)
        e = pad_err(f, pads)
        if best is None or e < best[0]:
            best = (e, r)
    f.SetOrientationDegrees(best[1])
    return best[0]


def get_net(b, name, cache):
    if not name:
        return None
    n = b.FindNet(name)
    if n is None:
        n = p.NETINFO_ITEM(b, name)
        b.Add(n)
        cache.append(name)
    return n


def board_mpn(part):
    """MPN / maker as the schematic generator writes them (gen_schematic -> bom_design.resolve_mpn: a resistor with no
    MPN in the design gets its Panasonic ERJ MPN), so DRC schematic parity sees the same fields."""
    from bom_design import resolve_mpn
    from netlist_core import Part
    return resolve_mpn(Part(**{k: v for k, v in part.items() if k in Part.__dataclass_fields__}))


def set_fields(f, part, keep_extra=None):
    """Reference / Value / MPN / Manufacturer / Note / generator fields per the design part."""
    f.SetReference(part["ref"])
    f.SetValue(part["value"])
    mpn, mfr = board_mpn(part)
    flds = {"MPN": mpn, "Manufacturer": mfr}
    flds.update(part.get("fields") or {})
    if keep_extra:
        for k, v in keep_extra.items():
            flds.setdefault(k, v)
    for k, v in flds.items():
        if k == "Datasheet":
            f.SetField("Datasheet", v)
            continue
        f.SetField(k, v)
    if part.get("note"):
        f.SetField("Note", part["note"])
    elif f.HasField("Note"):
        try:
            f.RemoveField("Note")
        except Exception:
            f.SetField("Note", "")


def project_copy(src, out, plan):
    out.mkdir(parents=True, exist_ok=False)
    for q in src.iterdir():
        if q.is_file() and (q.suffix in (".kicad_pcb", ".kicad_pro", ".kicad_dru") and q.stem == "skeeball-controller"
                            or q.name == "sym-lib-table"):
            shutil.copy2(q, out / q.name)
    rows = (src / "fp-lib-table").read_text(encoding="utf-8")
    old = "C:/work/audit/redesign/revc/lib/din8r.pretty"
    if old not in rows:                        # P7: repo fixture boards name the migrated library directly
        old = DIN8R_LIB.as_posix()
    assert old in rows, "fp-lib-table din8r row moved"
    (out / "fp-lib-table").write_text(rows.replace(old, DIN8R_LIB.as_posix()), encoding="utf-8")
    # net classes: add the generator's assignments for the nets the project lacks (never change an existing one)
    pro = out / "skeeball-controller.kicad_pro"
    pj = json.loads(pro.read_text(encoding="utf-8"))
    cur = pj["net_settings"].get("netclass_assignments") or {}
    added, conflicts = {}, {}
    for net, cls in sorted(plan["net_classes"].items()):
        have = cur.get(net)
        have = have[0] if isinstance(have, list) and have else have
        if have is None:
            cur[net] = [cls]
            added[net] = cls
        elif have != cls:
            conflicts[net] = [have, cls]
    pj["net_settings"]["netclass_assignments"] = cur
    pro.write_text(json.dumps(pj, indent=2), encoding="utf-8")
    return added, conflicts


def class_info(pro_path):
    pj = json.loads(Path(pro_path).read_text(encoding="utf-8"))
    cls = {c["name"]: c for c in pj["net_settings"]["classes"]}
    asg = pj["net_settings"].get("netclass_assignments") or {}

    def info(net):
        c = asg.get(net)
        c = (c[0] if isinstance(c, list) and c else c) or "Default"
        return {"class": c, "clearance": cls.get(c, cls["Default"]).get("clearance") or 0.2}
    return info


# ------------------------------------------------------------------------------------------------------------- place
def cmd_place(plan_path, src, out):
    t0 = time.time()
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    src, out = Path(src), Path(out)
    assert sha(src / BOARD) == plan["source_sha256"], "source board changed"
    added_cls, cls_conf = project_copy(src, out, plan)
    (out / "main-design.json").write_text(json.dumps(plan["design"], indent=1), encoding="utf-8")
    D = {q["ref"]: q for q in plan["design"]}
    T = plan["targets"]                      # ref -> {x, y, side, rot, pads, src}
    dst = out / BOARD
    b = p.LoadBoard(str(dst))
    layers = cu_layers(b)
    LN = {L: b.GetLayerName(L) for L in layers}
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    # ---- classify every design part
    swap, new, moved, renet, old = set(), set(), set(), set(), {}
    for r, part in D.items():
        f = fps.get(r)
        if f is None:
            new.add(r)
            continue
        if f.GetFPIDAsString() != part["footprint"]:
            swap.add(r)
        if any(q.GetNumber() in part["conns"] and q.GetNetname() != part["conns"][q.GetNumber()]
               and not (part["conns"][q.GetNumber()].startswith("NC_") and (q.GetNetname() == "" or q.GetNetname().startswith("unconnected-")))
               for q in f.Pads()):
            renet.add(r)
        if r in T:
            t = T[r]
            side = "B" if f.IsFlipped() else "F"
            cur = {q.GetNumber(): (mm(q.GetPosition().x), mm(q.GetPosition().y)) for q in f.Pads()}
            if t["side"] != side or r in swap or any(math.dist(cur.get(n, (1e9, 1e9)), xy) > 0.01 for n, xy in t["pads"].items()):
                moved.add(r)
    changed = swap | moved | renet
    for r in changed:
        f = fps[r]
        old[r] = {"uuid": f.m_Uuid.AsString(), "path": f.GetPath().AsString(), "sheetname": f.GetSheetname(),
                  "sheetfile": f.GetSheetfile(), "locked": f.IsLocked(), "fpid": f.GetFPIDAsString(),
                  "fields": {x.GetName(): x.GetText() for x in f.GetFields()},
                  "x": mm(f.GetPosition().x), "y": mm(f.GetPosition().y), "rot": f.GetOrientationDegrees(),
                  "side": "B" if f.IsFlipped() else "F",
                  "pads": [{"num": q.GetNumber(), "net": q.GetNetname(), "c": (mm(q.GetPosition().x), mm(q.GetPosition().y)),
                            "poly": {L: g.wkt for L, g in pad_polys(q, layers).items()}} for q in f.Pads()]}
    # ---- delete: swapped footprints (re-added from the library), retired crystal pre-route, NT1 old stub
    have = {t.m_Uuid.AsString() for t in b.GetTracks()}
    retire = [u for u in plan["retire_uuids"] if u in have]
    retire_missing = [u for u in plan["retire_uuids"] if u not in have]
    pre = [u for u in plan.get("pre_delete", []) if u in have]           # island plan: trunk-rip-plan + rip-A1
    pre_missing = [u for u in plan.get("pre_delete", []) if u not in have]
    del b, fps
    text = dst.read_text(encoding="utf-8")
    text = remove_saved_items(text, {old[r]["uuid"] for r in swap} | set(retire) | set(pre))
    dst.write_text(text, encoding="utf-8")
    b = p.LoadBoard(str(dst))
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    newnets, placed, problems = [], {}, []
    # ---- add swapped + new footprints
    for r in sorted(swap | new):
        part = D[r]
        f = load_fp(part["footprint"])
        b.Add(f)
        o = old.get(r)
        if o:
            f.SetPath(p.KIID_PATH(o["path"]))
            f.SetSheetname(o["sheetname"])
            f.SetSheetfile(o["sheetfile"])
        set_fields(f, part)
        fps[r] = f
        if r in T:
            t = T[r]
            e = pose(f, t["x"], t["y"], t["side"], t["pads"], t.get("rot"))
        else:          # swapped in place: the new land at the old centre / orientation / side (swap_fp semantics)
            e = pose(f, o["x"], o["y"], o["side"], None, o["rot"])
        placed[r] = {"how": "new" if r in new else "swap", "pad_err": round(e, 4)}
        if e > 0.01:
            problems.append(f"{r}: planned pad centres not reachable ({e:.3f} mm)")
        if o:
            f.SetLocked(o["locked"])
    # ---- move the kept footprints
    for r in sorted(moved - swap):
        t = T[r]
        f = fps[r]
        e = pose(f, t["x"], t["y"], t["side"], t["pads"], t.get("rot"))
        placed[r] = {"how": "move", "pad_err": round(e, 4)}
        if e > 0.01:
            problems.append(f"{r}: planned pad centres not reachable ({e:.3f} mm)")
    # ---- nets + fields of every design part, models
    import main_model_assignments as MMA
    from pcb_field_visibility import normalize_metadata_fields
    n_models = 0
    for r, part in D.items():
        f = fps[r]
        for q in f.Pads():
            want = part["conns"].get(q.GetNumber())
            if want is None:
                if q.GetNumber() and q.GetNetname() and r in swap | new:
                    q.SetNetCode(0)
                continue
            if want.startswith("NC_"):
                if not (q.GetNetname() == "" or q.GetNetname().startswith("unconnected-")):
                    q.SetNetCode(0)
                continue
            if q.GetNetname() != want:
                q.SetNet(get_net(b, want, newnets))
        have = {x.GetName(): x.GetText() for x in f.GetFields()}
        mpn_r, mfr_r = board_mpn(part)
        want = dict(part.get("fields") or {}, MPN=mpn_r, Manufacturer=mfr_r)
        if r in swap | new or r in renet or f.GetValue() != part["value"] \
                or any(have.get(k, "") != v for k, v in want.items() if k != "Datasheet" or v) \
                or have.get("Note", "") != (part.get("note") or ""):
            set_fields(f, part)
        try:
            n_models += MMA.apply(f)
        except RuntimeError as e:
            problems.append(f"{r}: model {e}")
        normalize_metadata_fields(f)
    # ---- NT1 GND_ISO vias (island-place/nt1_plan.py)
    for v in plan.get("add_vias", []):
        via = p.PCB_VIA(b)
        via.SetViaType(p.VIATYPE_THROUGH)
        via.SetLayerPair(p.F_Cu, p.B_Cu)
        via.SetPosition(V(v["x"], v["y"]))
        via.SetWidth(p.F_Cu, MM(v["d"]))
        via.SetDrill(MM(v["drill"]))
        via.SetNet(get_net(b, v["net"], newnets))
        b.Add(via)
    # ---- rule areas of the island plan (LINE_NECK_CH7_KO: no vias, all copper layers)
    areas_added = []
    for a in plan.get("rule_areas", []):
        z = p.ZONE(b)
        z.SetIsRuleArea(True)
        ls = p.LSET()
        for L in layers:
            ls.AddLayer(L)
        z.SetLayerSet(ls)
        ko = a.get("keepout", {})
        z.SetDoNotAllowVias(bool(ko.get("vias")))
        z.SetDoNotAllowTracks(bool(ko.get("tracks")))
        z.SetDoNotAllowPads(bool(ko.get("pads")))
        z.SetDoNotAllowZoneFills(bool(ko.get("zones")))
        z.SetDoNotAllowFootprints(bool(ko.get("footprints")))
        z.SetZoneName(a["name"])
        ps = p.SHAPE_POLY_SET()
        ps.NewOutline()
        for x, y in a["outline"]:
            ps.Append(MM(x), MM(y))
        z.Outline().RemoveAllContours()
        z.Outline().Append(ps)
        b.Add(z)
        areas_added.append(a["name"])
    p.SaveBoard(str(dst), b)
    # ---- rip / re-land analysis on the placed board
    rip, stubs, why = rip_plan(b, old, swap, moved, renet, new, plan, out / "skeeball-controller.kicad_pro")
    del b, fps
    text = dst.read_text(encoding="utf-8")
    text = remove_saved_items(text, set(rip))
    dst.write_text(text, encoding="utf-8")
    b = p.LoadBoard(str(dst))
    for s in stubs:
        t = p.PCB_TRACK(b)
        t.SetStart(V(*s["s"]))
        t.SetEnd(V(*s["e"]))
        t.SetWidth(MM(s["w"]))
        t.SetLayer(b.GetLayerID(s["layer"]))
        t.SetNet(b.FindNet(s["net"]))
        b.Add(t)
    p.SaveBoard(str(dst), b)
    # ---- verify every design pad net
    b = p.LoadBoard(str(dst))
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    bad = []
    for r, part in D.items():
        f = fps.get(r)
        if f is None:
            bad.append((r, "missing"))
            continue
        if f.GetFPIDAsString() != part["footprint"]:
            bad.append((r, "fpid", f.GetFPIDAsString()))
        for q in f.Pads():
            want = part["conns"].get(q.GetNumber())
            if want and not want.startswith("NC_") and q.GetNetname() != want:
                bad.append((r, q.GetNumber(), q.GetNetname(), want))
        for n, xy in (T.get(r, {}).get("pads") or {}).items():
            q = next((x for x in f.Pads() if x.GetNumber() == n), None)
            if q is None or math.dist((mm(q.GetPosition().x), mm(q.GetPosition().y)), xy) > 0.011:
                bad.append((r, n, "pad position"))
    from collections import Counter
    rep = {"plan": str(plan_path), "plan_sha256": sha(plan_path), "source_sha256": plan["source_sha256"],
           "output": str(dst), "output_sha256": sha(dst), "parts_on_board": len(fps),
           "design_parts": len(D), "new": sorted(new), "swapped": sorted(swap), "moved": sorted(moved),
           "renetted": sorted(renet), "placed": placed, "new_nets": sorted(newnets), "netclasses_added": added_cls,
           "netclass_conflicts": cls_conf, "models_set": n_models, "retired_xtal_uuids": retire,
           "retire_uuids_not_on_board": retire_missing, "island_pre_deleted": len(pre),
           "island_pre_delete_not_on_board": pre_missing, "rule_areas_added": areas_added, "ripped": len(rip),
           "ripped_by_reason": dict(Counter(w for w in why.values())), "stubs_added": len(stubs),
           "verify_mismatches": bad, "problems": problems, "seconds": round(time.time() - t0, 1)}
    (out / "place-report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (out / "rip-list.json").write_text(json.dumps({"delete": [{"uuid": u, "why": why[u]} for u in sorted(why)],
                                                   "stubs": stubs}, indent=1), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, (list, dict)) or len(v) < 12 else f"[{len(v)}]")
                      for k, v in rep.items()}, indent=1))
    if bad or problems:
        print("PROBLEMS", bad[:20], problems[:20])
    return 0


def rip_plan(b, old, swap, moved, renet, new, plan, pro_path):
    """Copper to rip and stubs to add.
    * old pads of MOVED parts: every same-net track whose end lies on the old pad, every same-net via on it -> rip;
    * old pads of SWAPPED-in-place / RE-NETTED parts: a track end / via still on a same-net new pad stays; else a
      straight stub to the new pad centre is added when it lies inside the old + new pad copper (re-land, no new
      clearance exposure); else rip. A pad whose net changed: its old-net copper is ripped;
    * other-net tracks / vias within the clearance (place_gate.required: class + DRU HV rules) of any new / moved /
      swapped / re-netted pad -> rip.
    Loose copper this leaves is peeled afterwards (peel)."""
    import place_gate
    from shapely import wkt
    info = class_info(pro_path)
    layers = cu_layers(b)
    LN = {L: b.GetLayerName(L) for L in layers}
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    tracks, vias = [], []
    for t in b.GetTracks():
        if t.GetNetCode() <= 0:
            continue
        u = t.m_Uuid.AsString()
        if t.Type() == p.PCB_VIA_T:
            c = (mm(t.GetPosition().x), mm(t.GetPosition().y))
            vias.append({"uuid": u, "net": t.GetNetname(), "c": c, "r": mm(t.GetWidth(p.F_Cu)) / 2,
                         "layers": [LN[L] for L in layers if t.IsOnLayer(L)]})
        else:
            a, e = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
            tracks.append({"uuid": u, "net": t.GetNetname(), "layer": t.GetLayerName(), "a": a, "e": e,
                           "w": mm(t.GetWidth()), "arc": t.Type() == p.PCB_ARC_T,
                           "mid": (mm(t.GetMid().x), mm(t.GetMid().y)) if t.Type() == p.PCB_ARC_T else None})
    rip, why, stubs = set(), {}, []

    def kill(u, w):
        if u not in rip:
            rip.add(u)
            why[u] = w
    newpads = {}
    for r in swap | moved | renet | new:
        newpads[r] = [{"num": q.GetNumber(), "net": q.GetNetname(), "c": (mm(q.GetPosition().x), mm(q.GetPosition().y)),
                       "poly": pad_polys(q, layers)} for q in fps[r].Pads()]
    # ---- copper attached to old pads
    tl = {}
    for t in tracks:
        tl.setdefault(t["layer"], []).append(t)
    for r, o in old.items():
        for op in o["pads"]:
            for L, gw in op["poly"].items():
                g = wkt.loads(gw)
                cands = [np_ for np_ in newpads[r] if np_["num"] == op["num"]] + \
                        [np_ for np_ in newpads[r] if np_["num"] != op["num"]]
                for t in tl.get(L, []):
                    if t["net"] != op["net"] or t["uuid"] in rip:
                        continue
                    for end in ("a", "e"):
                        q = Point(t[end])
                        if not g.buffer(t["w"] / 2 + 1e-4).contains(q):
                            continue
                        if r in moved:
                            kill(t["uuid"], f"old-pad {r}.{op['num']} (part moved)")
                            break
                        same = [np_ for np_ in cands if np_["net"] == t["net"] and L in np_["poly"]]
                        if any(np_["poly"][L].contains(q) for np_ in same):
                            continue            # still lands
                        ok = False
                        for np_ in same:
                            c = np_["c"]
                            stub = LineString([t[end], c]).buffer(t["w"] / 2)
                            if stub.within(g.union(np_["poly"][L]).buffer(0.01)):
                                stubs.append({"s": list(t[end]), "e": list(c), "w": t["w"], "layer": L, "net": t["net"],
                                              "for": f"{r}.{np_['num']}", "src": t["uuid"]})
                                ok = True
                                break
                        if not ok:
                            kill(t["uuid"], f"old-pad {r}.{op['num']} (" + ("re-netted" if r in renet and
                                 not same else "new land does not reach") + ")")
                            break
            for v in vias:
                if v["net"] != op["net"] or v["uuid"] in rip:
                    continue
                hitL = [L for L, gw in op["poly"].items() if L in v["layers"]
                        and wkt.loads(gw).intersects(Point(v["c"]).buffer(v["r"]))]
                if not hitL:
                    continue
                if r in moved:
                    kill(v["uuid"], f"old-pad via {r}.{op['num']} (part moved)")
                    continue
                same = [np_ for np_ in newpads[r] if np_["net"] == v["net"]]
                if any(L in np_["poly"] and np_["poly"][L].intersects(Point(v["c"]).buffer(v["r"])) for np_ in same
                       for L in v["layers"]):
                    continue
                ok = False
                for np_ in same:
                    for L in hitL:
                        if L not in np_["poly"]:
                            continue
                        g = wkt.loads(op["poly"][L])
                        stub = LineString([v["c"], np_["c"]]).buffer(0.125)
                        if stub.within(g.union(np_["poly"][L]).union(Point(v["c"]).buffer(v["r"])).buffer(0.01)):
                            stubs.append({"s": list(v["c"]), "e": list(np_["c"]), "w": 0.25, "layer": L,
                                          "net": v["net"], "for": f"{r}.{np_['num']} (via)", "src": v["uuid"]})
                            ok = True
                            break
                    if ok:
                        break
                if not ok:
                    kill(v["uuid"], f"old-pad via {r}.{op['num']} (" + ("re-netted" if not same else
                                                                         "new land does not reach") + ")")
    # ---- other-net copper within clearance of the new / moved / swapped / re-netted pads
    trees = {}
    for L, lst in tl.items():
        geoms = []
        for t in lst:
            pts = [t["a"], t["mid"], t["e"]] if t["arc"] else [t["a"], t["e"]]
            geoms.append(LineString(pts).buffer(t["w"] / 2) if pts[0] != pts[-1] else Point(t["a"]).buffer(t["w"] / 2))
        trees[L] = (STRtree(geoms), geoms, lst)
    vgeo = [Point(v["c"]).buffer(v["r"]) for v in vias]
    vtree = STRtree(vgeo)
    for r, pads in newpads.items():
        for np_ in pads:
            na = info(np_["net"]) if np_["net"] else {"class": "Default", "clearance": 0.2}
            for L, g in np_["poly"].items():
                if L in trees:
                    tree, geoms, lst = trees[L]
                    for i in tree.query(g.buffer(3.2)):
                        t = lst[i]
                        if t["net"] == np_["net"] or t["uuid"] in rip:
                            continue
                        need = place_gate.required(na, info(t["net"]), r, None, "pad", "trk")
                        if g.distance(geoms[i]) < need - 1e-3:
                            kill(t["uuid"], f"clearance to new pad {r}.{np_['num']} ({g.distance(geoms[i]):.3f} < {need})")
                for i in vtree.query(g.buffer(3.2)):
                    v = vias[i]
                    if v["net"] == np_["net"] or v["uuid"] in rip or L not in v["layers"]:
                        continue
                    need = place_gate.required(na, info(v["net"]), r, None, "pad", "via")
                    if g.distance(vgeo[i]) < need - 1e-3:
                        kill(v["uuid"], f"clearance to new pad {r}.{np_['num']} ({g.distance(vgeo[i]):.3f} < {need})")
    # stubs whose source track / via was ripped anyway are dropped
    stubs = [s for s in stubs if s["src"] not in rip]
    return rip, stubs, why


# ------------------------------------------------------------------------------------------------------------ refill
def cmd_refill(board):
    t0 = time.time()
    b = p.LoadBoard(str(board))
    zones = [z for z in b.Zones() if not z.GetIsRuleArea()]
    p.ZONE_FILLER(b).Fill(zones)
    p.SaveBoard(str(board), b)
    print(json.dumps({"refilled_zones": len(zones), "seconds": round(time.time() - t0, 1), "sha256": sha(board)}))
    return 0


# -------------------------------------------------------------------------------------------------------------- peel
FORCE_NETS = set()       # DIN-8R force nets; none on SBC-1


def full_check():
    """qa_copper_landing.check with every loose uuid listed (the gate truncates to 30 per net) and the track uuids of
    every LOOP finding: the SAME code, patched only in what it reports."""
    import inspect
    import qa_copper_landing as Q
    src = inspect.getsource(Q.check)
    pats = [('for i in idx][:30]})', 'for i in idx]})'),
            ('"a": f"{where(t[\'a\'])}-{where(t[\'e\'])}"})',
             '"a": f"{where(t[\'a\'])}-{where(t[\'e\'])}", "members": [tracks[es[m][3]]["obj"].m_Uuid.AsString() '
             'for m in members], "lens": [tracks[es[m][3]]["len"] for m in members]})'),
            ('"b": f"{where(o[\'a\'])}-{where(o[\'e\'])}"})',
             '"b": f"{where(o[\'a\'])}-{where(o[\'e\'])}", "pair": [t["obj"].m_Uuid.AsString(), '
             'o["obj"].m_Uuid.AsString()], "pair_len": [t["len"], o["len"]]})'),
            ('"worst": max(items,', '"all": items, "worst": max(items,')]
    for a, b_ in pats:
        assert src.count(a) == 1, ("qa_copper_landing changed; patch target missing", a)
        src = src.replace(a, b_)
    ns = dict(Q.__dict__)
    exec(compile(src, Q.__file__, "exec"), ns)
    return ns["check"]


def cmd_peel(board, report, loops=False, max_iter=60, nets_re=None):
    """Delete what qa_copper_landing flags as loose (TRACK-END: every pruned track, KiCad dangling tracks) and vias with
    < 2 landings (VIA-LAND), repeatedly; with --loops, once nothing is loose, break every LOOP (break_loops) and peel
    again. Fills are not touched here (refill after)."""
    check = full_check()
    hist, broken = [], []
    board = Path(board)
    for it in range(max_iter):
        res = check(board, ("TRACK-END", "VIA-LAND", "LOOP"))
        f = res["fails"]
        dels = set()
        for x in f["TRACK-END"]:
            dels |= set(x.get("uuids", []))
        b = p.LoadBoard(str(board))
        vland = {(round(x["at"][0], 4), round(x["at"][1], 4), x["net"]) for x in f["VIA-LAND"]}
        for t in b.GetTracks():
            if t.Type() == p.PCB_VIA_T:
                k = (round(mm(t.GetPosition().x), 4), round(mm(t.GetPosition().y), 4), t.GetNetname())
                if k in vland:
                    dels.add(t.m_Uuid.AsString())
        gp = geo_peel(b) if (dels or it == 0) else set()
        dels |= gp
        dels |= chain_back(b, dels)
        if nets_re is not None:
            # restricted peel (leg_restore.py): only items of the matching nets are touched
            import re as _re
            rx = _re.compile(nets_re)
            net_of = {t.m_Uuid.AsString(): t.GetNetname() for t in b.GetTracks()}
            dels = {u for u in dels if rx.match(net_of.get(u, ""))}
        nloop = 0
        lf = [x for x in f["LOOP"] if nets_re is None or __import__("re").match(nets_re, x["net"])]
        if loops and not dels and lf:
            lp = break_loops(lf)
            nloop = len(lp)
            broken += sorted(lp)
            dels |= lp
        hist.append({"iter": it, "counts": {k: res["counts"][k] for k in ("TRACK-END", "VIA-LAND", "LOOP")},
                     "deleted": len(dels), "geo_peel": len(gp), "loop_breaks": nloop})
        print(hist[-1], flush=True)
        del b
        if not dels:
            break
        txt = board.read_text(encoding="utf-8")
        board.write_text(remove_saved_items(txt, dels), encoding="utf-8")
    left = res["fails"]["LOOP"]
    Path(report).write_text(json.dumps({"board": str(board), "history": hist, "final": res["counts"],
                                        "final_status_subset": "PASS" if not any(res["fails"][c] for c in
                                        ("TRACK-END", "VIA-LAND", "LOOP")) else "FAIL",
                                        "loop_tracks_deleted": broken,
                                        "loops_left": [{k: v for k, v in x.items() if k != "all"} for x in left],
                                        "track_end_left": res["fails"]["TRACK-END"][:40]}, indent=1), encoding="utf-8")
    return 0


def protected_why(t, nt1_polys):
    """m1_protect.Rule's never-rip kinds, natively: None = may be pruned; else the reason"""
    # SBC-1: the never-rip set is the LOCKED copper (scripts/power_copper.py: +5V_IN trunk, light rails / cathodes)
    if t.IsLocked():
        return "locked (power_copper)"
    return None
    nm = t.GetNetname()
    try:
        cls = t.GetNetClassName()
    except Exception:
        cls = ""
    cls = cls.split(",")[0] if cls else ""
    if cls in HV_KEEP:
        return "force / HV"
    if nm == "GND_ISO" and t.Type() == p.PCB_VIA_T:
        return "plane stitch"
    if nm in RAILS:
        return "rail lane"
    if kelvin(nm):
        return "Kelvin"
    if LEG.match(nm):
        return "leg chain"
    if nt1_polys:
        g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)) if t.Type() == p.PCB_VIA_T else \
            LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
        if any(z.intersects(g) for z in nt1_polys):
            return "NT1 tie"
    return None


def cmd_prune(board, report, max_iter=40, reach=1.0):
    """Debris prune (owner / lead 2026-10-05, lean): (1) LAND every qa_copper_landing short end that KiCad connects - a
    TRACK-END free end with same-net pad / via copper within `reach` on its layer gets a stub to its CENTRE
    (land_stubs' rule, on board copper); (2) DELETE, to a fixpoint, the tracks / vias whose KiCad connectivity cluster
    holds no pad (pour-only clusters of POUR_NETS kept), KiCad-dangling tracks, and qa VIA-LAND vias, each with the dead
    chain behind it (chain_back); (3) a PROTECTED item (m1_protect kinds) is never deleted - reported, and the prune
    FAILS. Then the gate: qa TRACK-END / VIA-LAND, and KiCad's unconnected count must not rise."""
    import re
    import qa_copper_landing as Q
    check = full_check()
    board = Path(board)
    b0 = p.LoadBoard(str(board))
    b0.BuildConnectivity()
    unc0 = b0.GetConnectivity().GetUnconnectedCount(True)
    del b0
    # (1) landing stubs for the qa-short ends KiCad connects
    res = check(board, ("TRACK-END",))
    b = p.LoadBoard(str(board))
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    layers = cu_layers(b)
    byu = {t.m_Uuid.AsString(): t for t in b.GetTracks()}
    stubs = []
    for x in res["fails"]["TRACK-END"]:
        tr = [byu[u] for u in x.get("uuids", []) if u in byu]
        if not tr:
            continue
        cl = conn.GetConnectedItems(tr[0])
        if not any(c.GetClass() == "PAD" for c in cl):
            continue                                   # a pad-less cluster: debris, step 2 deletes it
        net = tr[0].GetNetname()
        for fe in x.get("free_ends", []):
            m = re.match(r"\(([-0-9.]+), ([-0-9.]+)\) (\S+)", fe)
            if not m:
                continue
            q = Point(float(m.group(1)), float(m.group(2)))
            L = b.GetLayerID(m.group(3))
            best = None
            for fpx in b.GetFootprints():
                for pd in fpx.Pads():
                    if pd.GetNetname() != net or not pd.IsOnLayer(L):
                        continue
                    g = pad_polys(pd, layers).get(m.group(3))
                    if g is None or g.distance(q) > reach or g.distance(q) < 1e-4:
                        continue
                    if best is None or g.distance(q) < best[0]:
                        best = (g.distance(q), g, Point(mm(pd.GetPosition().x), mm(pd.GetPosition().y)))
            for v in b.GetTracks():
                if v.Type() == p.PCB_VIA_T and v.GetNetname() == net:
                    c = Point(mm(v.GetPosition().x), mm(v.GetPosition().y))
                    g = c.buffer(mm(v.GetWidth(L)) / 2)
                    if 1e-4 < g.distance(q) <= reach and (best is None or g.distance(q) < best[0]):
                        best = (g.distance(q), g, c)
            if best is None:
                continue
            tgt = (best[2].x, best[2].y)            # land at the pad / via CENTRE (owner 2026-10-05, qa PAD-CENTRE)
            w = min(mm(t.GetWidth()) for t in tr if t.Type() != p.PCB_VIA_T and t.IsOnLayer(L)) if any(
                t.Type() != p.PCB_VIA_T and t.IsOnLayer(L) for t in tr) else 0.25
            st = p.PCB_TRACK(b)
            st.SetStart(V(q.x, q.y)); st.SetEnd(V(*tgt)); st.SetWidth(p.FromMM(w)); st.SetLayer(L)
            st.SetNet(b.FindNet(net))
            b.Add(st)
            stubs.append({"net": net, "layer": m.group(3), "s": [round(q.x, 4), round(q.y, 4)], "e": [round(tgt[0], 4), round(tgt[1], 4)]})
    if stubs:
        p.SaveBoard(str(board), b)
    del b
    # (2) delete debris to a fixpoint, (3) never a protected item
    hist, kept = [], {}
    for it in range(max_iter):
        res = check(board, ("TRACK-END", "VIA-LAND"))
        b = p.LoadBoard(str(board))
        b.BuildConnectivity()
        conn = b.GetConnectivity()
        seen, dels = set(), set()
        pour = Q.POUR_NETS["main"]
        for t in b.GetTracks():
            u = t.m_Uuid.AsString()
            if u in seen:
                continue
            cl = list(conn.GetConnectedItems(t)) + [t]
            ids = {c.m_Uuid.AsString() for c in cl if c.GetClass() in ("PCB_TRACK", "PCB_VIA", "PCB_ARC")}
            seen |= ids
            if any(c.GetClass() == "PAD" for c in cl):
                continue
            if t.GetNetname() in pour and any(c.GetClass() == "ZONE" for c in cl):
                continue                               # stitched into its own pour (pour nets)
            dels |= ids
        for t in b.GetTracks():
            if t.Type() != p.PCB_VIA_T:
                try:
                    if conn.TestTrackEndpointDangling(t, False):
                        dels.add(t.m_Uuid.AsString())
                except TypeError:
                    if conn.TestTrackEndpointDangling(t):
                        dels.add(t.m_Uuid.AsString())
        vland = {(round(x["at"][0], 4), round(x["at"][1], 4), x["net"]) for x in res["fails"]["VIA-LAND"]}
        for t in b.GetTracks():
            if t.Type() == p.PCB_VIA_T and (round(mm(t.GetPosition().x), 4), round(mm(t.GetPosition().y), 4),
                                             t.GetNetname()) in vland:
                dels.add(t.m_Uuid.AsString())
        # qa TRACK-END chains (e.g. stubs ending inside their own pour, pad-less rings): candidates too - the
        # connectivity_safe filter below spares any net whose open joins would rise
        for x in res["fails"]["TRACK-END"]:
            dels |= set(x.get("uuids", []))
        dels |= chain_back(b, dels)
        nt1 = []
        for z in b.Zones():
            if z.GetIsRuleArea() and "NT1" in z.GetZoneName().upper():
                nt1 += qc_polys(z.Outline())
        byu = {t.m_Uuid.AsString(): t for t in b.GetTracks()}
        prot = {}
        for u in list(dels):
            t = byu.get(u)
            w_ = protected_why(t, nt1) if t is not None else None
            if w_:
                prot[u] = {"net": t.GetNetname(), "why": w_, "kind": "via" if t.Type() == p.PCB_VIA_T else "trk",
                           "at": [round(mm(t.GetPosition().x), 3), round(mm(t.GetPosition().y), 3)]}
        dels -= set(prot)
        kept.update(prot)
        dels, spared = connectivity_safe(board, dels)
        hist.append({"iter": it, "counts": {k: res["counts"][k] for k in ("TRACK-END", "VIA-LAND")},
                     "deleted": len(dels), "protected_loose": len(prot), "spared_nets": spared})
        print(hist[-1], flush=True)
        del b
        if not dels:
            break
        board.write_text(remove_saved_items(board.read_text(encoding="utf-8"), dels), encoding="utf-8")
    b1 = p.LoadBoard(str(board))
    b1.BuildConnectivity()
    unc1 = b1.GetConnectivity().GetUnconnectedCount(True)
    del b1
    gate = res["counts"]
    status = "PASS" if not kept and unc1 <= unc0 and not gate["TRACK-END"] and not gate["VIA-LAND"] else "FAIL"
    Path(report).write_text(json.dumps({"board": str(board), "landing_stubs": stubs, "history": hist,
                                        "deleted": sum(h["deleted"] for h in hist), "protected_loose": list(kept.values()),
                                        "kicad_unconnected": [unc0, unc1], "gate": gate,
                                        "track_end_left": res["fails"]["TRACK-END"][:40],
                                        "via_land_left": res["fails"]["VIA-LAND"][:40], "status": status}, indent=1),
                            encoding="utf-8")
    print(json.dumps({"prune": status, "stubs": len(stubs), "deleted": sum(h["deleted"] for h in hist),
                      "protected_loose": len(kept), "kicad_unconnected": [unc0, unc1], "gate": gate}))
    return 0 if status == "PASS" else 1


def connectivity_safe(board, dels):
    """drop from a deletion set every net whose open joins (cugraph copper model, = KiCad's ratsnest within a few) would
    rise if its candidates went: debris never carries a connection, so such a net's candidates are live copper that
    some rule mis-flagged -> (kept deletion set, [spared nets])"""
    import subprocess
    sys.path.insert(0, str(TOOLS))
    import cugraph
    from open_joins import open_joins
    from collections import Counter
    if not dels:
        return dels, []
    gj = board.with_suffix(".prune-geom.json")
    subprocess.run([sys.executable, str(TOOLS / "dump_geom.py"), str(board), str(gj)],
                   capture_output=True, text=True, check=True)
    G = cugraph.load(str(gj))
    nets = {int(k): v["name"] for k, v in G["nets"].items()}
    # pfr2-speed: open joins are per net (same-net copper graph), so only the nets that own a candidate are counted -
    # the same before / after counts for them as on the whole board, without building the whole-board graph twice
    # per prune iteration (36 s of a 150 s prune)
    ids = {t["net"] for t in G["tracks"] if t["uuid"] in dels} | {v["net"] for v in G["vias"] if v["uuid"] in dels}
    G = dict(G, pads=[q for q in G["pads"] if q["net"] in ids], tracks=[t for t in G["tracks"] if t["net"] in ids],
             vias=[v for v in G["vias"] if v["net"] in ids], zones=[z for z in G["zones"] if z["net"] in ids])
    before = Counter(j["net"] for j in open_joins(G))
    net_of = {t["uuid"]: nets.get(t["net"], "") for t in G["tracks"]}
    net_of.update({v["uuid"]: nets.get(v["net"], "") for v in G["vias"]})
    H = dict(G, tracks=[t for t in G["tracks"] if t["uuid"] not in dels], vias=[v for v in G["vias"] if v["uuid"] not in dels])
    after = Counter(j["net"] for j in open_joins(H))
    worse = {n for n in set(after) | set(before) if after.get(n, 0) > before.get(n, 0)}
    gj.unlink(missing_ok=True)
    return {u for u in dels if net_of.get(u, "") not in worse}, sorted(worse)


def qc_polys(sps):
    import qa_crosslayer as qc
    return qc.polygons(sps)


def chain_back(b, seeds):
    """Extend each loose track to the whole dead stretch behind it: from its free end, follow exact-endpoint nodes
    shared by exactly two tracks (no via / pad there) until a junction, via or pad. The router's 0.025-0.07 mm
    segment runs otherwise peel one segment per gate pass (KiCad's dangling test sees only the last one)."""
    from collections import defaultdict
    tr, node_t = {}, defaultdict(set)
    vias = defaultdict(list)
    for t in b.GetTracks():
        if t.GetNetCode() <= 0:
            continue
        if t.Type() == p.PCB_VIA_T:
            vias[t.GetNetname()].append(((mm(t.GetPosition().x), mm(t.GetPosition().y)), mm(t.GetWidth(p.F_Cu)) / 2))
            continue
        u = t.m_Uuid.AsString()
        a = (round(mm(t.GetStart().x), 4), round(mm(t.GetStart().y), 4))
        e = (round(mm(t.GetEnd().x), 4), round(mm(t.GetEnd().y), 4))
        tr[u] = (t.GetNetname(), t.GetLayerName(), a, e)
        node_t[(t.GetNetname(), t.GetLayerName(), a)].add(u)
        node_t[(t.GetNetname(), t.GetLayerName(), e)].add(u)
    pads = defaultdict(list)
    layers = cu_layers(b)
    for f in b.GetFootprints():
        for q in f.Pads():
            if q.GetNetCode() > 0:
                for L, g in pad_polys(q, layers).items():
                    pads[(q.GetNetname(), L)].append(g)

    def via_at(net, xy):
        return any(math.dist(xy, c) <= r for c, r in vias[net])

    def pad_at(net, L, xy):
        return next((g for g in pads[(net, L)] if g.contains(Point(xy))), None)
    out = set()
    for s in seeds:
        if s not in tr:
            continue
        net, L, a, e = tr[s]
        for start in (a, e):
            if len(node_t[(net, L, start)]) != 1 or via_at(net, start):
                continue          # not a free end
            cur, node = s, (e if start == a else a)
            while True:
                ts = node_t[(net, L, node)] - {cur}
                if len(ts) != 1 or via_at(net, node):
                    break
                nxt = next(iter(ts))
                g = pad_at(net, L, node)
                if g is not None and not (g.contains(Point(tr[nxt][2])) and g.contains(Point(tr[nxt][3]))):
                    break         # the copper leaves the pad here: live side
                if nxt in out or nxt in seeds:
                    break
                out.add(nxt)
                _, _, na, ne = tr[nxt]
                cur, node = nxt, (ne if node == na else na)
    return out


def geo_peel(b):
    """Copper-graph peel (the cugraph / pcb_pickup_rules.violations construction, natively): nodes = tracks, vias, pads
    and own-net zone fills; same-net items whose copper intersects on a common layer are joined. Tracks / vias with at
    most one neighbour are removed repeatedly (dangling stubs, via-anchored dead-end trees), and every copper piece
    that reaches no pad goes. Pads and fills are never removed. Returns the uuids."""
    from collections import defaultdict
    layers = cu_layers(b)
    LN = {L: b.GetLayerName(L) for L in layers}
    nodes, geo = {}, defaultdict(list)          # key -> (kind, net); layer -> [(key, geom)]
    for t in b.GetTracks():
        if t.GetNetCode() <= 0:
            continue
        k = ("v" if t.Type() == p.PCB_VIA_T else "t", t.m_Uuid.AsString())
        nodes[k] = t.GetNetCode()
        g = to_shapely_track(t)
        for L in layers:
            if t.IsOnLayer(L):
                geo[LN[L]].append((k, g))
    for f in b.GetFootprints():
        for q in f.Pads():
            if q.GetNetCode() <= 0:
                continue
            k = ("p", f.GetReference() + "." + q.GetNumber() + "#" + q.m_Uuid.AsString())
            nodes[k] = q.GetNetCode()
            for L, g in pad_polys(q, layers).items():
                geo[L].append((k, g))
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() <= 0:
            continue
        for L in layers:
            if z.IsOnLayer(L):
                g = to_shapely(z.GetFilledPolysList(L))
                for i, part in enumerate(getattr(g, "geoms", [g])):
                    if not part.is_empty:
                        k = ("z", z.m_Uuid.AsString() + f"/{LN[L]}/{i}")
                        nodes[k] = z.GetNetCode()
                        geo[LN[L]].append((k, part))
    adj = defaultdict(set)
    for L, lst in geo.items():
        tree = STRtree([g for _, g in lst])
        for i, (k, g) in enumerate(lst):
            if k[0] in ("z",):
                continue
            for j in tree.query(g):
                k2, g2 = lst[j]
                if k2 != k and nodes[k2] == nodes[k] and g.intersects(g2):
                    adj[k].add(k2)
                    adj[k2].add(k)
    alive = set(nodes)
    stack = [k for k in nodes if k[0] in "tv" and len(adj[k]) <= 1]
    dead = set()
    while stack:
        k = stack.pop()
        if k not in alive or len(adj[k] & alive) > 1:
            continue
        alive.discard(k)
        dead.add(k)
        stack.extend(n for n in adj[k] if n in alive and n[0] in "tv")
    seen = set()
    for k in list(alive):                      # pieces with no pad
        if k in seen or k[0] not in "tv":
            continue
        comp, todo, pad = set(), [k], False
        while todo:
            u = todo.pop()
            if u in comp:
                continue
            comp.add(u)
            pad = pad or u[0] == "p"
            todo.extend(n for n in adj[u] if n in alive and n not in comp)
        seen |= comp
        if not pad:
            dead |= {u for u in comp if u[0] in "tv"}
    return {k[1] for k in dead}


def break_loops(loop_fails):
    """One track per LOOP finding: for a closed cycle the shortest member track (a cycle edge: the rest of the cycle
    keeps every joint connected); for two pieces touching without a joint the shorter of the two (peeled after).
    Force nets on F.Cu / B.Cu are never touched (HIGH-CURRENT OUTER PATHS); they stay reported."""
    out = set()
    for x in loop_fails:
        net = x["net"]
        for it in x.get("all", [x["worst"]]):
            if net in FORCE_NETS and it["layer"] in ("F.Cu", "B.Cu"):
                continue
            if "members" in it:
                cand = sorted(zip(it["lens"], it["members"]))
                if cand:
                    out.add(cand[0][1])
            elif "pair" in it:
                out.add(it["pair"][0] if it["pair_len"][0] <= it["pair_len"][1] else it["pair"][1])
            break                  # one break per net per round: the next check re-evaluates the cycles
    return out


# ------------------------------------------------------------------------------------------------------------ delete
def cmd_delete(board, plan_path):
    board = Path(board)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    b = p.LoadBoard(str(board))
    have = {t.m_Uuid.AsString() for t in b.GetTracks()}
    del b
    dels = {d["uuid"] for d in plan["delete"]}
    hit = dels & have
    txt = board.read_text(encoding="utf-8")
    board.write_text(remove_saved_items(txt, hit), encoding="utf-8")
    print(json.dumps({"requested": len(dels), "deleted": len(hit), "not_on_board": len(dels - have)}))
    return 0


def cmd_add(board, plan_path):
    """add tracks / vias natively with their GIVEN uuids (leg_restore.py: the as-built revC-A1 leg copper keeps its
    revC-A1 identity); an item whose uuid is already on the board is skipped."""
    board = Path(board)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    b = p.LoadBoard(str(board))
    have = {t.m_Uuid.AsString() for t in b.GetTracks()}
    lid = {b.GetLayerName(l): l for l in range(p.PCB_LAYER_ID_COUNT) if p.IsCopperLayer(l)}
    mm = p.FromMM
    n_t = n_v = skip = 0
    for t in plan.get("tracks", []):
        if t["uuid"] in have:
            skip += 1
            continue
        q = p.PCB_TRACK(b)
        q.SetStart(p.VECTOR2I(mm(t["s"][0]), mm(t["s"][1])))
        q.SetEnd(p.VECTOR2I(mm(t["e"][0]), mm(t["e"][1])))
        q.SetWidth(mm(t["w"]))
        q.SetLayer(lid[t["layer"]])
        net = b.FindNet(t["net"])
        assert net is not None and net.GetNetCode() > 0, ("net missing", t["net"])
        q.SetNet(net)
        q.SetUuidDirect(p.KIID(t["uuid"]))
        b.Add(q)
        n_t += 1
    for v in plan.get("vias", []):
        if v["uuid"] in have:
            skip += 1
            continue
        q = p.PCB_VIA(b)
        q.SetPosition(p.VECTOR2I(mm(v["x"]), mm(v["y"])))
        q.SetViaType(p.VIATYPE_THROUGH)
        q.SetLayerPair(lid[v.get("top", "F.Cu")], lid[v.get("bot", "B.Cu")])
        q.SetWidth(p.F_Cu, mm(v["d"]))
        q.SetDrill(mm(v["drill"]))
        net = b.FindNet(v["net"])
        assert net is not None and net.GetNetCode() > 0, ("net missing", v["net"])
        q.SetNet(net)
        q.SetUuidDirect(p.KIID(v["uuid"]))
        b.Add(q)
        n_v += 1
    p.SaveBoard(str(board), b)
    print(json.dumps({"added_tracks": n_t, "added_vias": n_v, "skipped_present": skip, "sha256": sha(board)}))
    return 0


def cmd_legloops(board, report, nets_re, max_steps=80, per_finding=14):
    """LOOP repair of the leg nets with qa_copper_landing as the ONLY oracle (lead 2026-10-04): leg_normalize proposes
    steps (drop a cycle track / merge doubled runs / drop a remnant / connector / split-join); each is applied to the
    board and KEPT only if the gate then shows fewer LOOP findings on the leg nets and no new PAD-OPEN / PAD-LAND /
    TRACK-END finding on them; otherwise the board text is restored and the next candidate is tried."""
    import re as _re
    import leg_normalize as LN
    board = Path(board)
    rx = _re.compile(nets_re)
    check = full_check()
    ALL = ("PAD-OPEN", "PAD-LAND", "TRACK-END", "VIA-LAND", "LOOP")

    def leg_state(res):
        f = res["fails"]
        loops = [x for x in f["LOOP"] if rx.match(x.get("net", ""))]
        other = set()
        for k in ("PAD-OPEN", "PAD-LAND", "TRACK-END", "VIA-LAND"):
            for x in f[k]:
                if rx.match(x.get("net", "") or ""):
                    other.add((k, json.dumps({kk: vv for kk, vv in x.items() if kk in ("net", "pads", "pad", "free_ends", "at")},
                                             sort_keys=True)))
        return loops, other

    def score(loops):
        """LOOP findings on the leg nets: every contact of every net (a step may fix one of a net's contacts)"""
        return sum(max(1, int(x.get("contacts", 1))) for x in loops)

    def net_items(net):
        b = p.LoadBoard(str(board))
        lays = cu_layers(b)
        tr, vi, pads = [], [], []
        for t in b.GetTracks():
            if t.GetNetname() != net:
                continue
            if t.Type() == p.PCB_VIA_T:
                vi.append({"uuid": t.m_Uuid.AsString(), "x": mm(t.GetPosition().x), "y": mm(t.GetPosition().y),
                           "d": mm(t.GetWidth(p.F_Cu))})
            elif t.Type() == p.PCB_TRACE_T:
                tr.append({"uuid": t.m_Uuid.AsString(), "net": net, "layer": b.GetLayerName(t.GetLayer()),
                           "s": [round(mm(t.GetStart().x), 4), round(mm(t.GetStart().y), 4)],
                           "e": [round(mm(t.GetEnd().x), 4), round(mm(t.GetEnd().y), 4)], "w": round(mm(t.GetWidth()), 4)})
        for f in b.GetFootprints():
            for q in f.Pads():
                if q.GetNetname() == net:
                    pp = pad_polys(q, lays)
                    if pp:
                        pads.append(pp)
        return tr, vi, pads

    def apply(old, new):
        ou, nu = {t["uuid"] for t in old}, {t["uuid"] for t in new}
        txt = board.read_text(encoding="utf-8")
        if ou - nu:
            board.write_text(remove_saved_items(txt, ou - nu), encoding="utf-8")
        add = [t for t in new if t["uuid"] not in ou]
        if add:
            b = p.LoadBoard(str(board))
            lid = {b.GetLayerName(l): l for l in range(p.PCB_LAYER_ID_COUNT) if p.IsCopperLayer(l)}
            for t in add:
                q = p.PCB_TRACK(b)
                q.SetStart(p.VECTOR2I(p.FromMM(t["s"][0]), p.FromMM(t["s"][1])))
                q.SetEnd(p.VECTOR2I(p.FromMM(t["e"][0]), p.FromMM(t["e"][1])))
                q.SetWidth(p.FromMM(t["w"]))
                q.SetLayer(lid[t["layer"]])
                q.SetNet(b.FindNet(t["net"]))
                q.SetUuidDirect(p.KIID(t["uuid"]))
                b.Add(q)
            p.SaveBoard(str(board), b)
        return txt

    res = check(board, ALL)
    loops, other = leg_state(res)
    hist = [{"step": 0, "leg_loops": len(loops), "contacts": score(loops), "other": len(other)}]
    accepted, rejected = [], []
    for step in range(1, max_steps + 1):
        if not loops:
            break
        progressed = False
        for lf in loops:
            tr, vi, pads = net_items(lf["net"])
            ref = LN.connectivity(tr, vi, pads)
            n_try = 0
            import itertools
            arcs = itertools.chain.from_iterable(LN.arc_candidates(tr, vi, pads, it_["members"])
                                                 for it_ in lf.get("all", []) if "members" in it_)
            stubs_ = itertools.chain.from_iterable(LN.stub_candidates(tr, vi, pads, x_.get("uuids", []))
                                                   for x_ in res["fails"]["TRACK-END"] if x_.get("net") == lf["net"])
            for trial, entry in itertools.chain(stubs_, LN.qa_candidates(tr, vi, pads, lf), arcs,
                                                LN.candidates(tr, vi, pads, ref)):
                n_try += 1
                if n_try > per_finding:
                    break
                backup = apply(tr, trial)
                res2 = check(board, ALL)
                loops2, other2 = leg_state(res2)
                if score(loops2) < score(loops) and other2 <= other:
                    accepted.append(dict(entry, net=lf["net"], loops_after=len(loops2)))
                    res, loops, other, progressed = res2, loops2, other2, True
                    print(json.dumps({"step": step, "kept": entry, "net": lf["net"], "leg_loops": len(loops)}), flush=True)
                    break
                board.write_text(backup, encoding="utf-8")       # revert
                rejected.append(dict(entry, net=lf["net"], why=f"loop contacts {score(loops2)} vs {score(loops)}, new findings "
                                                            f"{sorted(other2 - other)[:2]}"))
            if progressed:
                break
        hist.append({"step": step, "leg_loops": len(loops), "contacts": score(loops), "other": len(other)})
        if not progressed:
            break
    # leg TRACK-END stubs (as-built pieces the kicad detector flags): dropped when connectivity is unchanged and the gate
    # then shows fewer leg findings, no new one and no more LOOP contacts
    for x in [x for x in res["fails"]["TRACK-END"] if rx.match(x.get("net", "") or "") and x.get("uuids")]:
        tr, vi, pads = net_items(x["net"])
        for trial, entry in LN.stub_candidates(tr, vi, pads, x["uuids"]):
            backup = apply(tr, trial)
            res2 = check(board, ALL)
            loops2, other2 = leg_state(res2)
            if other2 < other and score(loops2) <= score(loops):
                accepted.append(dict(entry, net=x["net"]))
                res, loops, other = res2, loops2, other2
                print(json.dumps({"kept": entry, "net": x["net"]}), flush=True)
            else:
                board.write_text(backup, encoding="utf-8")
                rejected.append(dict(entry, net=x["net"], why="stub drop did not reduce the leg findings"))
    hist.append({"step": "track-end pass", "leg_loops": len(loops), "contacts": score(loops), "other": len(other)})
    Path(report).write_text(json.dumps({"board": str(board), "history": hist, "accepted": accepted,
                                        "rejected": rejected[:60], "leg_loops_left": loops}, indent=1),
                            encoding="utf-8")
    print(json.dumps({"leg_loops_left": len(loops), "leg_other_findings": len(other), "accepted": len(accepted),
                      "rejected": len(rejected)}))
    return 0 if not loops else 1


# ------------------------------------------------------------------------------------------------------------ y600ko
Y600_RULE = """
# >>> merged-draft Y600 no-foreign-copper (MERGED-BOARD-CHECKLIST item 5; refloor-logic xtal_place.py: no foreign-net
# copper under the crystal courtyard on F.Cu / In2.Cu / In3.Cu)
(rule "Y600 no foreign copper"
 (condition "A.intersectsArea('Y600_NO_FOREIGN') && (A.Type == 'Track' || A.Type == 'Via') && A.NetName != 'ETH_XI' && A.NetName != 'ETH_XO' && A.NetName != 'GND'")
 (constraint disallow track via))
# <<< merged-draft Y600 no-foreign-copper
"""


def cmd_y600ko(board, rip=False):
    board = Path(board)
    b = p.LoadBoard(str(board))
    old = {z.m_Uuid.AsString() for z in b.Zones() if z.GetIsRuleArea() and z.GetZoneName() == "Y600_NO_FOREIGN"}
    f = b.FindFootprintByReference("Y600")
    cy = f.GetCourtyard(p.B_CrtYd if f.IsFlipped() else p.F_CrtYd)
    g = to_shapely(cy)
    del b
    if old:
        board.write_text(remove_saved_items(board.read_text(encoding="utf-8"), old), encoding="utf-8")
    b = p.LoadBoard(str(board))
    z = p.ZONE(b)
    z.SetIsRuleArea(True)
    ls = p.LSET()
    for L in ("F.Cu", "In2.Cu", "In3.Cu"):
        ls.AddLayer(b.GetLayerID(L))
    z.SetLayerSet(ls)
    for fl in ("SetDoNotAllowTracks", "SetDoNotAllowVias", "SetDoNotAllowPads", "SetDoNotAllowZoneFills",
               "SetDoNotAllowFootprints"):
        getattr(z, fl)(False)
    z.SetZoneName("Y600_NO_FOREIGN")
    ps = p.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in list(g.exterior.coords)[:-1]:
        ps.Append(MM(x), MM(y))
    z.Outline().RemoveAllContours()
    z.Outline().Append(ps)
    b.Add(z)
    p.SaveBoard(str(board), b)
    dru = board.with_suffix(".kicad_dru")
    txt = dru.read_text(encoding="utf-8")
    i, j = txt.find("# >>> merged-draft Y600"), txt.find("# <<< merged-draft Y600")
    if i >= 0 and j > i:
        txt = txt[:i] + txt[txt.find("\n", j) + 1:]
    dru.write_text(txt.rstrip("\n") + "\n" + Y600_RULE, encoding="utf-8")
    # foreign copper there now (reported; the routing restart clears it)
    b = p.LoadBoard(str(board))
    bad = []
    for t in b.GetTracks():
        if t.GetNetname() in ("ETH_XI", "ETH_XO", "GND"):
            continue
        L = [b.GetLayerName(x) for x in (p.F_Cu, b.GetLayerID("In2.Cu"), b.GetLayerID("In3.Cu")) if t.IsOnLayer(x)]
        if not L:
            continue
        sh = to_shapely_track(t)
        if sh.intersects(g):
            bad.append({"uuid": t.m_Uuid.AsString(), "net": t.GetNetname(), "layers": L})
    del b
    if rip and bad:       # Y600 was swapped / moved: the foreign copper under its new courtyard is ripped (peeled after)
        board.write_text(remove_saved_items(board.read_text(encoding="utf-8"), {x["uuid"] for x in bad}),
                         encoding="utf-8")
    print(json.dumps({"area_mm2": round(g.area, 2), "bounds": [round(x, 2) for x in g.bounds], "replaced": len(old),
                      "foreign_copper_inside": bad, "ripped": bool(rip and bad)}))
    return 0


def to_shapely_track(t):
    if t.Type() == p.PCB_VIA_T:
        return Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth(p.F_Cu)) / 2)
    a, e = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
    return (LineString([a, e]) if a != e else Point(a)).buffer(mm(t.GetWidth()) / 2)


# ----------------------------------------------------------------------------------------------------------- linecut
def cmd_linecut(board, report, refs_csv, band=(12.0, 74.0), grow=0.4, exempt=("NT1",)):
    """MERGED-BOARD-CHECKLIST item 10: the LINE zones carry per-pad holes (pad + 0.4 mm, the A1 generator's rule, measured
    on revC-A1) around the island parts in the chip bands. Add the same holes for every pad of REFS (new / moved
    parts) on that zone's layer that lies inside the LINE zone outline outside the force band (y 12-74), so the refill
    does not re-pour LINE around them. Existing holes are kept. Zone OUTLINE edit, natively (SHAPE_POLY_SET)."""
    board = Path(board)
    refs = set(refs_csv.split(",")) - set(exempt)
    b = p.LoadBoard(str(board))
    layers = cu_layers(b)
    out = {}
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetname() != "LINE":
            continue
        L = [x for x in layers if z.IsOnLayer(x)]
        if len(L) != 1:
            continue
        Ln = b.GetLayerName(L[0])
        zone = to_shapely(z.Outline())
        cut = []
        for f in b.GetFootprints():
            if f.GetReference() not in refs:
                continue
            for q in f.Pads():
                if q.GetNetname() == "LINE" or not q.IsOnLayer(L[0]):
                    continue
                cy = mm(q.GetPosition().y)
                if band[0] <= cy <= band[1]:
                    continue
                g = to_shapely(q.GetEffectivePolygon(L[0])).buffer(grow, 8)
                if g.intersection(zone).area > 1e-4:
                    cut.append((f.GetReference() + "." + q.GetNumber(), g))
        if not cut:
            out[z.GetZoneName()] = {"layer": Ln, "pads": 0}
            continue
        newz = zone.difference(unary_union([g for _, g in cut]))
        area = zone.area - newz.area
        ps = p.SHAPE_POLY_SET()
        for part in getattr(newz, "geoms", [newz]):
            if part.geom_type != "Polygon" or part.area < 1e-3:
                continue
            ps.NewOutline()
            for x, y in list(part.exterior.coords)[:-1]:
                ps.Append(MM(x), MM(y))
            for h in part.interiors:
                ps.NewHole()
                for x, y in list(h.coords)[:-1]:
                    ps.Append(MM(x), MM(y), -1, ps.HoleCount(ps.OutlineCount() - 1) - 1)
        z.Outline().RemoveAllContours()
        z.Outline().Append(ps)
        out[z.GetZoneName()] = {"layer": Ln, "pads": len(cut), "cut_mm2": round(area, 2),
                                "pads_list": [n for n, _ in cut]}
    p.SaveBoard(str(board), b)
    Path(report).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "pads_list"} for k, v in out.items()}))
    return 0


# ------------------------------------------------------------------------------------------------------------ fields
GEN_FP_LIB = (_ROOT / "scripts/footprints_candidate")      # the generator's footprint library


def cmd_fpimport(board, delta_path, report):
    """footprint part of a merge delta (delta_merge.py; lead 2026-10-05 hold-up swap): delete footprints by reference,
    add footprints loaded from the GENERATOR's library entry (scripts/footprints_candidate/<name>.kicad_mod for din8r:,
    never a hand-built pad set) posed so their pads land on the delta's planned pad centres (<= 0.01 mm, asserted, and
    each pad on the planned copper layer), nets and Reference / Value / MPN / Manufacturer set. Saves natively."""
    board = Path(board)
    D = json.loads(Path(delta_path).read_text(encoding="utf-8"))
    F = D.get("footprints") or {}
    b = p.LoadBoard(str(board))
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    gone = {fps[r].m_Uuid.AsString() for r in F.get("delete", [])}
    missing = [r for r in F.get("delete", []) if r not in fps]
    if missing:
        raise SystemExit(f"fpimport: footprints to delete not on the board: {missing}")
    del b
    if gone:
        board.write_text(remove_saved_items(board.read_text(encoding="utf-8"), gone), encoding="utf-8")
    b = p.LoadBoard(str(board))
    have = {f.GetReference() for f in b.GetFootprints()}
    rows, newnets = [], []
    for a in F.get("add", []):
        if a["ref"] in have:
            raise SystemExit(f"fpimport: {a['ref']} already on the board")
        lib, name = a["footprint"].split(":", 1)
        gen = GEN_FP_LIB / f"{name}.kicad_mod"
        if lib == "din8r" and gen.exists():
            # KiCad loads footprints only from a *.pretty library: stage the generator's file into one beside the board
            # (the source of record stays the generator file; its sha is reported)
            pretty = board.parent / "fpimport-gen.pretty"
            pretty.mkdir(exist_ok=True)
            shutil.copy2(gen, pretty / gen.name)
            fp = p.FootprintLoad(str(pretty), name)
            src = gen
        else:
            fp = load_fp(a["footprint"])
            src = lib_path(a["footprint"])[0] / f"{name}.kicad_mod"
        if fp is None:
            raise SystemExit(f"fpimport: footprint {a['footprint']} not found")
        fp.SetFPID(p.LIB_ID(lib, name))
        b.Add(fp)              # KiCad 10: Flip() of a footprint with no parent board crashes (access violation)
        side = "B" if a["layer"] == "B.Cu" else "F"
        pads = {n: [q["x"], q["y"]] for n, q in a["pads"].items()}
        err = pose(fp, a["x"], a["y"], side, pads=pads, rot=a.get("rot"))
        if err > 0.01:
            raise SystemExit(f"fpimport: {a['ref']} pads land {err:.3f} mm off the planned centres")
        for q in fp.Pads():
            want = a["pads"].get(q.GetNumber())
            if want is None:
                continue
            if not q.IsOnLayer(b.GetLayerID(a["layer"])):
                raise SystemExit(f"fpimport: {a['ref']}.{q.GetNumber()} is not on {a['layer']}")
            q.SetNet(get_net(b, want["net"], newnets))
        fp.SetReference(a["ref"])
        fp.SetValue(a["value"])
        if a.get("mpn"):
            fp.SetField("MPN", a["mpn"])
        if a.get("mfr"):
            fp.SetField("Manufacturer", a["mfr"])
        rows.append({"ref": a["ref"], "footprint": a["footprint"], "source": str(src),
                     "source_sha256": hashlib.sha256(Path(src).read_bytes()).hexdigest(), "pad_err_mm": round(err, 4)})
    p.SaveBoard(str(board), b)
    Path(report).write_text(json.dumps({"deleted": F.get("delete", []), "added": rows, "nets_added": newnets}, indent=1),
                            encoding="utf-8")
    print(json.dumps({"fp_deleted": F.get("delete", []), "fp_added": [r["ref"] for r in rows], "nets_added": newnets}))
    return 0


def cmd_deadzones(board, report):
    """drop dead copper zones (tools/dead_zones.py: no fill part touches a pad / via of the zone's own net - floating
    copper, e.g. revC-A1's corner PLANE_GND_ISO_In1.Cu_0 / In4.Cu_0) by UUID in the saved board, then refill"""
    sys.path.insert(0, str(TOOLS))
    from dead_zones import dead_zones
    from shapely.geometry import Point
    import qa_crosslayer as qc
    from shapely.ops import unary_union
    board = Path(board)
    b = p.LoadBoard(str(board))
    rows = []
    for z in b.Zones():
        if z.GetIsRuleArea() or not z.GetNetname():
            continue
        net, parts, anchors = z.GetNetname(), [], []
        for L in z.GetLayerSet().CuStack():
            if z.HasFilledPolysForLayer(L):
                parts += qc.polygons(z.GetFilledPolysList(L))
            for t in b.GetTracks():
                if t.GetNetname() == net and t.IsOnLayer(L):
                    if t.GetClass() == "PCB_VIA":
                        anchors.append(Point(p.ToMM(t.GetPosition().x), p.ToMM(t.GetPosition().y)).buffer(p.ToMM(t.GetWidth(L)) / 2))
                    else:
                        ps = p.SHAPE_POLY_SET()
                        t.TransformShapeToPolygon(ps, L, 0, p.FromMM(0.005), p.ERROR_OUTSIDE)
                        anchors.append(unary_union(qc.polygons(ps)))
            for q in b.GetPads():
                if q.GetNetname() == net and q.IsOnLayer(L):
                    ps = p.SHAPE_POLY_SET()
                    q.TransformShapeToPolygon(ps, L, 0, p.FromMM(0.005), p.ERROR_OUTSIDE)
                    anchors.append(unary_union(qc.polygons(ps)))
        rows.append({"uuid": z.m_Uuid.AsString(), "name": z.GetZoneName(), "parts": parts, "anchors": anchors})
    dead = dead_zones(rows)
    del b
    if dead:
        txt = board.read_text(encoding="utf-8")
        board.write_text(remove_saved_items(txt, {u for u, _, _ in dead}), encoding="utf-8")
        cmd_refill(board)
    Path(report).write_text(json.dumps({"dead_zones": [{"uuid": u, "name": n, "fill_mm2": a} for u, n, a in dead]}, indent=1),
                            encoding="utf-8")
    print(json.dumps({"dead_zones_dropped": [(n, a) for _, n, a in dead]}))
    return 0


def cmd_fields(board, design_json):
    """metadata-only sync of every design footprint (Value, MPN / Manufacturer as resolved, Note, generator fields);
    copper, poses and nets untouched."""
    from pcb_field_visibility import normalize_metadata_fields
    D = {q["ref"]: q for q in json.loads(Path(design_json).read_text(encoding="utf-8"))}
    b = p.LoadBoard(str(board))
    n = []
    for f in b.GetFootprints():
        part = D.get(f.GetReference())
        if not part:
            continue
        have = {x.GetName(): x.GetText() for x in f.GetFields()}
        mpn_r, mfr_r = board_mpn(part)
        want = dict(part.get("fields") or {}, MPN=mpn_r, Manufacturer=mfr_r)
        if f.GetValue() != part["value"] or any(have.get(k, "") != v for k, v in want.items() if k != "Datasheet" or v)                 or have.get("Note", "") != (part.get("note") or ""):
            set_fields(f, part)
            normalize_metadata_fields(f)
            n.append(f.GetReference())
    p.SaveBoard(str(board), b)
    print(json.dumps({"fields_synced": len(n), "refs": n[:40]}))
    return 0


# ------------------------------------------------------------------------------------------------------------- paths
def cmd_paths(board, netfile, design_json):
    """footprint KIID paths from a regenerated schematic's netlist; NC pins get the netlist's unconnected-(...) net."""
    import pcb_build
    board = Path(board)
    comps, nets = pcb_build.parse_netlist(Path(netfile))
    wanted = {(ref, pin): net.lstrip("/") for net, nodes in nets.items() for ref, pin in nodes}
    D = {q["ref"]: q for q in json.loads(Path(design_json).read_text(encoding="utf-8"))}
    b = p.LoadBoard(str(board))
    newnets, set_paths, bad = [], 0, []
    for f in b.GetFootprints():
        r = f.GetReference()
        if r not in comps:
            continue
        f.SetPath(p.KIID_PATH(comps[r]["path"]))
        set_paths += 1
        part = D.get(r)
        for q in f.Pads():
            exp = wanted.get((r, q.GetNumber()))
            if exp is None:
                continue
            if q.GetNetname() != exp:
                if part and part["conns"].get(q.GetNumber(), "").startswith("NC_"):
                    q.SetNet(get_net(b, exp, newnets))
                else:
                    bad.append((r, q.GetNumber(), q.GetNetname(), exp))
    p.SaveBoard(str(board), b)
    print(json.dumps({"paths_set": set_paths, "nc_nets_added": len(newnets), "net_mismatch": bad[:40],
                      "net_mismatch_count": len(bad)}))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "place":
        sys.exit(cmd_place(*args[:3]))
    if cmd == "refill":
        sys.exit(cmd_refill(args[0]))
    if cmd == "peel":
        nre = args[args.index("--nets-re") + 1] if "--nets-re" in args else None
        sys.exit(cmd_peel(args[0], args[1], "--loops" in args, nets_re=nre))
    if cmd == "delete":
        sys.exit(cmd_delete(args[0], args[1]))
    if cmd == "add":
        sys.exit(cmd_add(args[0], args[1]))
    if cmd == "legloops":
        sys.exit(cmd_legloops(args[0], args[1], args[2]))
    if cmd == "y600ko":
        sys.exit(cmd_y600ko(args[0], "--rip" in args))
    if cmd == "linecut":
        sys.exit(cmd_linecut(args[0], args[1], args[2]))
    if cmd == "fields":
        sys.exit(cmd_fields(args[0], args[1]))
    if cmd == "deadzones":
        sys.exit(cmd_deadzones(args[0], args[1]))
    if cmd == "fpimport":
        sys.exit(cmd_fpimport(args[0], args[1], args[2]))
    if cmd == "prune":
        sys.exit(cmd_prune(args[0], args[1]))
    if cmd == "paths":
        sys.exit(cmd_paths(args[0], args[1], args[2]))
    raise SystemExit(f"unknown command {cmd}")
