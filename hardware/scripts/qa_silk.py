# ported from din8r-chassis-thermal/scripts/qa_silk.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/qa_silk.py (C:/work/din-relay-8ch), adapted for CT (MAIN only, no signature block)
"""SILKSCREEN gate (DIN-8R owner 2026-10-05: "Add a release gate to clean up the silkscreen conflicts ... it needs to
be a production gate"; "if we have any Pin 1 markings used for placement, or other silkscreen placement guides...
those must be prioritized over everything else"). CT MAIN, KiCad Python:

  py scripts/local_run.py qa_silk.py [BOARD] [--json OUT] [--drc-report .runtime/drc.json]

BLOCKING; it never runs a DRC itself. Exit 0 = PASS, 1 = FAIL, 2 = tool error (fail closed).

FAIL classes (each item names the silk item, its owner part and where):
  SILK-PIN1-MISSING   a polarised / orientable part (silk_marks.MARK_REQUIRED prefixes U IC D LED Y X J P CN T BZ,
                      polarised C footprints; Q when its footprint carries a mark) with no pin-1 / polarity mark on its
                      own side's silk that survives: unclipped by pads / mask openings and not under another part's
                      courtyard (lost area <= GUIDE_CLIP_TOL). Marks come from silk_marks.placement_marks(): the
                      footprint's own dot, triangle, chamfer, notch, cathode bar, "+", "1" (a piece that breaks the pad
                      symmetry on the pin-1 side).
  SILK-GUIDE-CLIPPED  any placement mark (pin-1, polarity "+", cathode bar, connector pin-1 number, outline notch) that
                      loses more than GUIDE_CLIP_TOL of its ink to a pad / mask opening (SILK_MASK_CLEARANCE_MM) or to
                      another part's courtyard on its side.
  SILK-OVER-PAD       silk (marks excluded: see GUIDE-CLIPPED) crossing a pad's mask opening (exposed copper): the
                      fab clips it, leaving partial refs. SILK-OVER-MASK: the same for any other mask opening (an
                      untented via, a mask drawing or zone). Overlap > CLIP_MIN_MM2 within SILK_MASK_CLEARANCE_MM.
  SILK-OVERLAP        two silk items overlapping (> OVERLAP_MIN_MM2), e.g. two refs on top of each other. Like KiCad,
                      two graphic shapes of the same footprint (or both board-level) are one compound drawing and do
                      not count. Each item names `move`: the lower-priority item in SILK_PRIORITY, which yields.
  SILK-EDGE           silk closer than SILK_EDGE_MM to the board outline (or outside it), or to a milled slot /
                      unplated hole.
  SILK-TEXT-SIZE      any visible text on F.SilkS / B.SilkS (refs, fields, footprint text, labels) below
                      silk_marks.REF_H (1.0 mm) height or REF_W (0.15 mm) stroke (JLC legibility minimum). CT rev A
                      refs are 0.6 / 0.1 mm (QA_LOG QA-SILK): they FAIL here; the limit is not lowered.
  SILK-REF-MISSING    an assembled part (not NO_SILK_REF NT / MH / FID / H, not DNP, not board-only) with no visible,
                      correctly mirrored reference on its own side's silk inside the board outline. Exception: a part
                      listed in the board's omission manifest <board stem>.silk_omit.json (OMIT_SUFFIX, written by
                      scripts/pcb_silk.py) whose sha256 matches the board file and whose reference is hidden from the
                      silk (info ref_omitted). A stale / malformed manifest, or a listed ref that is not an assembled
                      part or is visible on the silk, is a FAIL here.
  SILK-REF-AMBIGUOUS  a reference whose centre is more than AMBIG_MARGIN_MM closer to another part's courtyard (same
                      side) than to its own: the assembler could read it as that part's. SILK_AMBIG_ACCEPT (empty on
                      CT) would list documented refs with no unambiguous spot (info ref_ambiguous_accepted).
  SILK-UNDER-PART     (WARN) silk under another part's courtyard on the same side (> UNDER_PART_FRAC of its ink),
                      hidden after assembly. FAIL for board-level TEXT (labels, hazard marks, title): those exist to be
                      read on the assembled board (DIN-8R rev B.3 QA moved the hazard marks out from under the relays).
                      Marks under a part are GUIDE-CLIPPED.
Not applicable on CT: SILK-BRANDING (the parent's designer signature block clearances). CT has no board-level silk
text and no signature block; the report says so in info.not_applicable. Board-level text added later is still covered
by OVER-PAD / OVER-MASK / OVERLAP / EDGE / TEXT-SIZE / UNDER-PART (FAIL level).
The parent's MAIN "dense-board disposition" (an omitted-reference allowance, DIN-8R owner 2026-10-07) is adopted for CT
by the root decision of 2026-10-17 (docs/DECISIONS.md D-LAYOUT-GATES, layout_gates REPORT "Root decisions" #5) in a
narrow form: the hash-bound omission manifest above (see OMIT_SUFFIX). Placement marks are never omitted.

PRIORITY ORDER (silk_marks.SILK_PRIORITY, highest first): placement-mark > footprint outline > hazard > label > title >
signature > reference. In every conflict the LOWER item moves or shrinks; a placement mark never does. So a reference
over a pin-1 dot is a SILK-OVERLAP FAIL whose `move` is the reference (the dot stays, and is not GUIDE-CLIPPED: silk on
silk does not remove the dot's ink).

KiCad DRC reuse: with --drc-report (scripts/qa_drc.py's .runtime/drc.json) the KiCad silk_over_copper / silk_overlap /
silk_edge_clearance violations are merged into SILK-OVER-PAD / -MASK (or GUIDE-CLIPPED for a mark), SILK-OVERLAP and
SILK-EDGE (deduplicated by item uuid; source 'kicad', 'geom' or 'both'). The narrow geometric checks always run as well,
so a report produced with silk severities at 'warning' (CT's project) or filtered to errors cannot pass a board. A
report for a different board (its `source`) or older than the board file is a tool error (exit 2;
drc_check_coverage.require_identity).
Fixtures: scripts/test_qa_silk.py.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as LC  # noqa: E402  (first: tools/pylib shapely)

import pcbnew  # noqa: E402
from shapely.geometry import Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

import drc_check_coverage  # noqa: E402
import silk_marks  # noqa: E402
from silk_marks import (NO_SILK_REF, REF_H, REF_W, SILK_PRIORITY, item_geom, mark_policy,  # noqa: E402
                        placement_marks, poly_set_geom)

CHECKS = ("SILK-PIN1-MISSING", "SILK-GUIDE-CLIPPED", "SILK-OVER-PAD", "SILK-OVER-MASK", "SILK-OVERLAP", "SILK-EDGE",
          "SILK-TEXT-SIZE", "SILK-REF-MISSING", "SILK-REF-AMBIGUOUS", "SILK-UNDER-PART")
NOT_APPLICABLE = {"SILK-BRANDING": "CT has no designer signature block (no board-level silk text on rev A); the "
                                   "parent's class checks that block's clearances only"}
WARN_CLASSES = ("SILK-UNDER-PART",)          # its board-text items are FAIL level (see docstring)
SILK_MASK_CLEARANCE_MM = 0.0                 # silk to mask opening; = CT's KiCad min_silk_clearance (0.0)
CLIP_MIN_MM2 = 0.0005                        # silk / opening overlap below this is contact noise, not ink lost
OVERLAP_MIN_MM2 = 0.0005                     # silk / silk overlap below this is contact noise
SILK_EDGE_MM = 0.20                          # silk to board edge / slot / NPTH hole (parent value)
TEXT_MIN_H_MM, TEXT_MIN_W_MM = REF_H, REF_W  # JLC legibility minimum (silk_marks)
AMBIG_MARGIN_MM = 0.25                       # another part's courtyard must be this much nearer than its own
UNDER_PART_FRAC = 0.25                       # share of an item's ink under another part's courtyard
# SILK-REF-AMBIGUOUS documented accepts {ref: reason}: a listed designator with no unambiguous legal 1.0 mm spot is
# reported in info ref_ambiguous_accepted instead. Every entry needs a dated owner / lead decision as its reason.
# EMPTY on CT (no such decision). Placement marks are never accepted here (SILK-PIN1-MISSING / GUIDE-CLIPPED stay strict).
SILK_AMBIG_ACCEPT = {}
# SILK-REF-MISSING omission manifest (narrow amendment 2026-10-17, ct_silk_refs for hw_board_finish). DIN-8R owner
# 2026-10-07 (din-relay-8ch CLAUDE.md "Dense-board silkscreen disposition"): "If you can't place a silkscreen marking so
# be it. This is a dense board. Do your best and move on." - readable references may be omitted from the physical silk
# when they cannot be placed clearly; they stay in the assembly map (iBOM) and fab docs, the exact omitted set is
# recorded, and placement / pin-1 / polarity cues are never omitted. CT root decision 2026-10-17 (docs/DECISIONS.md
# D-LAYOUT-GATES; docs/records/layout_gates/REPORT.md "Root decisions" #5): "Keep the parent's rule as-is: references
# 1.0 / 0.15 mm where they fit, and the parent's dense-board omission rule where they don't." The recorded set is
# <board stem> + OMIT_SUFFIX (scripts/pcb_silk.py writes it): {"sha256": <board file>, "refs": {ref: {...}}}. It is
# accepted only when its sha256 matches the board file; each listed ref must then be an assembled part whose reference
# is hidden from the silk (not visible on F.SilkS / B.SilkS), and is reported in info ref_omitted. Anything else
# (stale / malformed manifest, unknown / unassembled / visible listed ref) is a SILK-REF-MISSING FAIL. Every other
# class (PIN1-MISSING, GUIDE-CLIPPED, ...) is unchanged and strict.
OMIT_SUFFIX = ".silk_omit.json"
GUIDE_CLIP_TOL = 0.10                       # a mark losing more than this share of its ink is clipped / covered
EPS = 1e-6
KICAD_SILK = {"silk_over_copper": "SILK-OVER-PAD", "silk_overlap": "SILK-OVERLAP",
              "silk_edge_clearance": "SILK-EDGE"}
COPPER_LAYERS = len(LC.COPPER_LAYERS)        # CT MAIN: 4
TITLE_PREFIXES = ("DIN8-CT", "DIN8R-CT", "DIN8R CT")   # board-level title text (role 'title'; none on rev A)
SIDES = (("F", pcbnew.F_SilkS, pcbnew.F_Cu, pcbnew.F_Mask, pcbnew.F_CrtYd),
         ("B", pcbnew.B_SilkS, pcbnew.B_Cu, pcbnew.B_Mask, pcbnew.B_CrtYd))


def mm(v):
    return round(pcbnew.ToMM(v), 3)


def at(g):
    c = g.centroid if not g.is_empty else Point(0, 0)
    return [round(c.x, 2), round(c.y, 2)]


def assembled(fp):
    return (silk_marks.prefix(fp.GetReference()) not in NO_SILK_REF and not fp.IsDNP() and not fp.IsBoardOnly())


def courtyard(fp, crt):
    ps = fp.GetCourtyard(crt)
    out = []
    for i in range(ps.OutlineCount()):
        o = ps.Outline(i)
        pts = [(pcbnew.ToMM(o.CPoint(k).x), pcbnew.ToMM(o.CPoint(k).y)) for k in range(o.PointCount())]
        if len(pts) >= 3:
            p = Polygon(pts)
            out.append(p if p.is_valid else p.buffer(0))
    if out:
        return unary_union(out)
    bb = fp.GetBoundingBox(False)
    return box(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))


def role(it):
    """SILK_PRIORITY role of a silk item."""
    if it["mark"]:
        return "placement-mark"
    if it["kind"] in ("ref", "field"):
        return "reference"
    if it["kind"] in ("fpshape", "fptext"):
        return "outline"
    t = (it["text"] or "").upper()
    if "DANGER" in t or "WARNING" in t or "HAZARD" in t:
        return "hazard"
    if it["kind"] == "shape":
        return "label"
    if t.startswith(TITLE_PREFIXES):
        return "title"
    return "label"


def describe(it):
    who = it["owner"] or "board"
    txt = f" '{it['text']}'" if it["text"] else ""
    return f"{who} {it['kind']}{txt} {it['side']}.SilkS @ {at(it['geom'])}"


def collect(b):
    """Every visible silk item on both faces: dict(uuid, side, kind, owner, geom, text, is_text, mark, obj, fp)."""
    items, marks = [], {}
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        mk = placement_marks(fp)
        marks[ref] = mk
        mark_uuids = {m["uuid"] for m in mk}
        for side, silk, *_ in SIDES:
            for f in fp.GetFields():
                if f.GetLayer() == silk and f.IsVisible() and f.GetShownText(False).strip():
                    items.append(dict(uuid=f.m_Uuid.AsString(), side=side, kind="ref" if f.IsReference() else "field",
                                      owner=ref, geom=item_geom(f, silk), text=f.GetShownText(False), is_text=True,
                                      mark=False, obj=f, fp=fp))
            for d in fp.GraphicalItems():
                if d.GetLayer() != silk:
                    continue
                is_text = isinstance(d, (pcbnew.PCB_TEXT, pcbnew.PCB_TEXTBOX))
                if is_text and not d.IsVisible():
                    continue
                uid = d.m_Uuid.AsString()
                items.append(dict(uuid=uid, side=side, kind="fptext" if is_text else "fpshape", owner=ref,
                                  geom=item_geom(d, silk), text=d.GetShownText(False) if is_text else "",
                                  is_text=is_text, mark=uid in mark_uuids, obj=d, fp=fp))
    for d in b.GetDrawings():
        for side, silk, *_ in SIDES:
            if d.GetLayer() != silk:
                continue
            is_text = isinstance(d, (pcbnew.PCB_TEXT, pcbnew.PCB_TEXTBOX))
            if is_text and not d.IsVisible():
                continue
            items.append(dict(uuid=d.m_Uuid.AsString(), side=side, kind="text" if is_text else "shape", owner=None,
                              geom=item_geom(d, silk), text=d.GetShownText(False) if is_text else "",
                              is_text=is_text, mark=False, obj=d, fp=None))
    return [i for i in items if not i["geom"].is_empty], marks


def openings(b, cu, mask):
    """Mask openings on one face: [(geom, kind 'pad'|'mask', label, uuid)]."""
    out = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if not p.IsOnLayer(mask):
                continue
            g = item_geom(p, cu if p.IsOnLayer(cu) else pcbnew.F_Cu)
            if g.is_empty and p.HasHole():
                ps = pcbnew.SHAPE_POLY_SET()
                p.TransformHoleToPolygon(ps, 0, silk_marks.ARC_ERR, pcbnew.ERROR_INSIDE)
                g = poly_set_geom(ps)
            try:
                exp = p.GetSolderMaskExpansion(mask)
            except TypeError:
                exp = p.GetSolderMaskExpansion()
            if exp:
                g = g.buffer(pcbnew.ToMM(exp), join_style=2)
            if not g.is_empty:
                out.append((g, "pad", f"{fp.GetReference()}.{p.GetNumber() or '?'}", p.m_Uuid.AsString()))
        for d in fp.GraphicalItems():
            if d.GetLayer() == mask:
                g = item_geom(d, mask)
                if not g.is_empty:
                    out.append((g, "mask", f"{fp.GetReference()} mask drawing", d.m_Uuid.AsString()))
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA" and not t.IsTented(mask):
            g = item_geom(t, cu)
            if not g.is_empty:
                out.append((g, "mask", f"untented via {t.GetNetname()}", t.m_Uuid.AsString()))
    for d in b.GetDrawings():
        if d.GetLayer() == mask:
            g = item_geom(d, mask)
            if not g.is_empty:
                out.append((g, "mask", "board mask drawing", d.m_Uuid.AsString()))
    for z in b.Zones():
        if not z.GetIsRuleArea() and z.IsOnLayer(mask):
            g = poly_set_geom(z.Outline())
            if not g.is_empty:
                out.append((g, "mask", f"mask zone {z.GetZoneName()}", z.m_Uuid.AsString()))
    return out


def holes(b):
    """Milled slots (any non-round drill) and unplated holes: [(geom, label)]."""
    out = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if not p.HasHole():
                continue
            d = p.GetDrillSize()
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or d.x != d.y:
                ps = pcbnew.SHAPE_POLY_SET()
                p.TransformHoleToPolygon(ps, 0, silk_marks.ARC_ERR, pcbnew.ERROR_INSIDE)
                g = poly_set_geom(ps)
                if not g.is_empty:
                    out.append((g, f"{fp.GetReference()}.{p.GetNumber() or 'hole'} "
                                   f"{'slot' if d.x != d.y else 'NPTH'}"))
    return out


def omit_manifest(pcb):
    """the board's omission manifest (see OMIT_SUFFIX): (path or None, {ref: entry} when hash-valid, [problems])"""
    path = Path(pcb).with_suffix(OMIT_SUFFIX)
    if not path.exists():
        return None, {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return path, {}, [f"unreadable ({e})"]
    refs = data.get("refs") if isinstance(data, dict) else None
    if not isinstance(refs, dict) or not all(isinstance(k, str) and k for k in refs):
        return path, {}, ["no 'refs' mapping {ref: entry}"]
    sha = hashlib.sha256(Path(pcb).read_bytes()).hexdigest()
    if data.get("sha256") != sha:
        return path, {}, [f"stale: sha256 {str(data.get('sha256'))[:12]} != board {sha[:12]} (re-run pcb_silk.py)"]
    return path, refs, []


def read_drc(path, pcb):
    """the KiCad silk violations of a DRC report for THIS board as it is now (ValueError otherwise: tool error)"""
    try:
        data = drc_check_coverage.load(path)
    except drc_check_coverage.ToolError as e:
        raise ValueError(str(e)) from e
    if not isinstance(data.get("violations"), list):
        raise ValueError(f"DRC report has no violations list: {path}")
    drc_check_coverage.require_identity(data, pcb)
    return [v for v in data["violations"] if v.get("type") in KICAD_SILK]


def check(pcb, drc_report=None, checks=CHECKS):
    t0 = time.time()
    pcb = drc_check_coverage.project_path(pcb)
    drc_report = drc_check_coverage.project_path(drc_report) if drc_report else None
    b = pcbnew.LoadBoard(str(pcb))
    if b.GetCopperLayerCount() != COPPER_LAYERS:
        raise ValueError(f"SBC-1 main must have {COPPER_LAYERS} copper layers; {pcb.name} has {b.GetCopperLayerCount()}")
    fails = {c: [] for c in CHECKS}
    warns = {c: [] for c in CHECKS}
    seen = {c: {} for c in CHECKS}          # dedup key -> entry
    info = {"thresholds": {"SILK_MASK_CLEARANCE_MM": SILK_MASK_CLEARANCE_MM, "CLIP_MIN_MM2": CLIP_MIN_MM2,
                           "OVERLAP_MIN_MM2": OVERLAP_MIN_MM2, "SILK_EDGE_MM": SILK_EDGE_MM,
                           "TEXT_MIN_H_MM": TEXT_MIN_H_MM, "TEXT_MIN_W_MM": TEXT_MIN_W_MM,
                           "AMBIG_MARGIN_MM": AMBIG_MARGIN_MM, "UNDER_PART_FRAC": UNDER_PART_FRAC,
                           "GUIDE_CLIP_TOL": GUIDE_CLIP_TOL, "MARK_REACH_MM": silk_marks.MARK_REACH_MM,
                           "MARK_MARGIN_MM": silk_marks.MARK_MARGIN_MM},
            "priority": list(SILK_PRIORITY), "not_applicable": dict(NOT_APPLICABLE)}

    def add(cls, key, entry, level="FAIL"):
        if cls not in checks:
            return
        if key in seen[cls]:
            e = seen[cls][key]
            if entry.get("source") and e.get("source") != entry["source"]:
                e["source"] = "both"
            return
        entry.setdefault("source", "geom")
        entry["level"] = level
        seen[cls][key] = entry
        (fails if level == "FAIL" else warns)[cls].append(entry)

    # DRC report identity first: a report for another / older board is a tool error before any work
    vs = read_drc(drc_report, pcb) if drc_report else None
    items, marks = collect(b)
    by_uuid = {i["uuid"]: i for i in items}
    info["silk_items"] = len(items)
    # omission manifest (OMIT_SUFFIX): hash first, then every listed ref must be an assembled part with a hidden ref
    om_path, om_refs, om_problems = omit_manifest(pcb)
    omit_ok = set()
    if om_path is not None:
        info["ref_omit_manifest"] = {"path": str(om_path), "valid": not om_problems, "listed": len(om_refs)}
    for p in om_problems:
        add("SILK-REF-MISSING", ("omit-manifest", p), {"part": None, "manifest": str(om_path),
                                                       "why": f"omission manifest {p}"})
    for ref in om_refs:
        fp = b.FindFootprintByReference(ref)
        if fp is None or not assembled(fp):
            add("SILK-REF-MISSING", (ref, "omit-unassembled"),
                {"part": ref, "manifest": str(om_path),
                 "why": "listed in the omission manifest but not an assembled part on this board"})
        elif any(i["owner"] == ref and i["is_text"] and i["text"] == ref and i["kind"] in ("ref", "fptext")
                 for i in items):
            add("SILK-REF-MISSING", (ref, "omit-visible"),
                {"part": ref, "manifest": str(om_path),
                 "why": "listed in the omission manifest but its reference is visible on the silk"})
        else:
            omit_ok.add(ref)
    info["board_level_text"] = sum(1 for i in items if i["owner"] is None and i["is_text"])
    outline = Polygon()
    ps = pcbnew.SHAPE_POLY_SET()
    if b.GetBoardPolygonOutlines(ps, True):
        outline = poly_set_geom(ps)
    edge = outline.boundary if not outline.is_empty else None
    info["board_outline_ok"] = edge is not None
    if edge is None:
        raise ValueError(f"{pcb.name}: no closed board outline (Edge.Cuts)")
    fps = list(b.GetFootprints())
    hl = holes(b)
    hl_tree = STRtree([h[0] for h in hl]) if hl else None

    for side, silk, cu, mask, crt in SIDES:
        here = [i for i in items if i["side"] == side]
        side_fps = [f for f in fps if (f.IsFlipped() == (side == "B"))]
        crts = {f.GetReference(): courtyard(f, crt) for f in side_fps}
        hide = {f.GetReference(): crts[f.GetReference()] for f in side_fps if assembled(f)}
        hide_refs = list(hide)
        hide_tree = STRtree([hide[r] for r in hide_refs]) if hide_refs else None
        ops = openings(b, cu, mask)
        ops_g = [o[0].buffer(SILK_MASK_CLEARANCE_MM) if SILK_MASK_CLEARANCE_MM else o[0] for o in ops]
        op_tree = STRtree(ops_g) if ops_g else None

        def covered_by_parts(g, own):
            if hide_tree is None:
                return Polygon(), []
            hit = [hide_refs[k] for k in hide_tree.query(g) if hide_refs[k] != own]
            hit = [r for r in hit if hide[r].intersects(g)]
            return (unary_union([hide[r] for r in hit]) if hit else Polygon()), hit

        def clipped_by_openings(g):
            if op_tree is None:
                return Polygon(), []
            hit = [k for k in op_tree.query(g) if ops_g[k].intersects(g)]
            return (unary_union([ops_g[k] for k in hit]) if hit else Polygon()), hit

        # ---- pin-1 / placement marks (highest priority)
        for f in side_fps:
            ref = f.GetReference()
            can, req, p1 = mark_policy(f)
            if not can:
                continue
            mk = marks.get(ref, [])
            alive = 0
            for m in mk:
                g = m["geom"]
                ou, oh = clipped_by_openings(g)
                cu_, ch = covered_by_parts(g, ref)
                lost = g.intersection(unary_union([ou, cu_])).area / g.area if g.area else 1.0
                if lost > GUIDE_CLIP_TOL:
                    by = [ops[k][2] for k in oh][:6] + [f"courtyard {r}" for r in ch][:6]
                    add("SILK-GUIDE-CLIPPED", (ref, m["uuid"], at(g)[0], at(g)[1]),
                        {"part": ref, "mark": (m["text"] or m["item"].GetClass()), "at": at(g),
                         "lost_frac": round(lost, 3), "by": by})
                else:
                    alive += 1
            info.setdefault("marks_found", {})[ref] = len(mk)
            if alive == 0 and (req or mk):
                add("SILK-PIN1-MISSING", (ref,), {"part": ref, "footprint": str(f.GetFPID().GetLibItemName()),
                                                  "at": at(crts[ref]), "pin1_pad": p1[0].GetNumber(),
                                                  "reason": "all marks clipped / covered" if mk else
                                                  "footprint has no pin-1 / polarity mark on its silk"})

        # ---- silk over pads / mask openings (marks excluded: GUIDE-CLIPPED)
        for it in here:
            g = it["geom"]
            if it["fp"] is not None and marks.get(it["owner"]):
                mg = [m["geom"] for m in marks[it["owner"]] if m["uuid"] == it["uuid"]]
                if mg:
                    g = g.difference(unary_union(mg).buffer(0.01))
                    if g.is_empty:
                        continue
            if op_tree is None:
                continue
            hits = [k for k in op_tree.query(g) if ops_g[k].intersects(g)]
            pad = [(k, g.intersection(ops_g[k]).area) for k in hits if ops[k][1] == "pad"]
            oth = [(k, g.intersection(ops_g[k]).area) for k in hits if ops[k][1] != "pad"]
            for cls, lst in (("SILK-OVER-PAD", pad), ("SILK-OVER-MASK", oth)):
                lst = [(k, a) for k, a in lst if a > CLIP_MIN_MM2]
                if lst:
                    add(cls, (it["uuid"],), {"item": describe(it), "uuid": it["uuid"], "part": it["owner"],
                                             "openings": [ops[k][2] for k, _ in lst][:8],
                                             "area_mm2": round(sum(a for _, a in lst), 4)})

        # ---- silk / silk overlap
        if here:
            tree = STRtree([i["geom"] for i in here])
            for a_i, a in enumerate(here):
                for b_i in tree.query(a["geom"]):
                    if b_i <= a_i:
                        continue
                    c = here[b_i]
                    if not a["is_text"] and not c["is_text"] and a["owner"] == c["owner"]:
                        continue                      # one compound drawing (KiCad's rule)
                    if not a["geom"].intersects(c["geom"]):
                        continue
                    area = a["geom"].intersection(c["geom"]).area
                    if area <= OVERLAP_MIN_MM2:
                        continue
                    ra, rc = SILK_PRIORITY.index(role(a)), SILK_PRIORITY.index(role(c))
                    move = describe(a) if ra > rc else describe(c) if rc > ra else None
                    keep = describe(c) if ra > rc else describe(a) if rc > ra else None
                    add("SILK-OVERLAP", (frozenset((a["uuid"], c["uuid"])),),
                        {"items": [describe(a), describe(c)], "uuids": [a["uuid"], c["uuid"]],
                         "parts": [a["owner"], c["owner"]], "move": move, "keep": keep,
                         "roles": [role(a), role(c)], "area_mm2": round(area, 4)})

        # ---- edge / slots / unplated holes
        for it in here:
            g = it["geom"]
            reasons = []
            if not outline.contains(g):
                reasons.append("outside the board outline")
            else:
                dist = g.distance(edge)
                if dist < SILK_EDGE_MM - EPS:
                    reasons.append(f"{dist:.3f} mm from the board edge")
            if hl_tree is not None:
                for k in hl_tree.query(g.buffer(SILK_EDGE_MM)):
                    dist = g.distance(hl[k][0])
                    if dist < SILK_EDGE_MM - EPS:
                        reasons.append(f"{dist:.3f} mm from {hl[k][1]}")
            if reasons:
                add("SILK-EDGE", (it["uuid"],), {"item": describe(it), "uuid": it["uuid"], "part": it["owner"],
                                                 "why": reasons[:6]})

        # ---- text size
        for it in here:
            if not it["is_text"]:
                continue
            o = it["obj"]
            s = o.GetTextSize()
            h, w = pcbnew.ToMM(min(s.x, s.y)), pcbnew.ToMM(o.GetTextThickness())
            if h < TEXT_MIN_H_MM - EPS or w < TEXT_MIN_W_MM - EPS:
                add("SILK-TEXT-SIZE", (it["uuid"],), {"item": describe(it), "part": it["owner"],
                                                      "height_mm": round(h, 3), "stroke_mm": round(w, 3)})

        # ---- references: missing / ambiguous
        for f in side_fps:
            ref = f.GetReference()
            if not assembled(f):
                continue
            mine = [i for i in here if i["owner"] == ref and i["is_text"] and i["text"] == ref
                    and (i["kind"] in ("ref", "fptext"))]
            ok = []
            for i in mine:
                if hasattr(i["obj"], "IsMirrored") and i["obj"].IsMirrored() != (side == "B"):
                    continue
                if not outline.intersects(i["geom"]):
                    continue
                ok.append(i)
            if not ok and ref in omit_ok and not mine:
                info.setdefault("ref_omitted", []).append(ref)    # hidden + listed in a hash-valid manifest
                continue
            if not ok:
                why = ("reference mirrored for the wrong side" if mine else
                       "no visible reference on " + side + ".SilkS")
                if mine and not any(outline.intersects(i["geom"]) for i in mine):
                    why = "reference outside the board"
                add("SILK-REF-MISSING", (ref,), {"part": ref, "side": side, "at": at(crts[ref]), "why": why})
                continue
            for i in ok:
                c = i["geom"].envelope.centroid
                d_own = c.distance(crts[ref])
                best = None
                for r2, cg in crts.items():
                    if r2 == ref or silk_marks.prefix(r2) in NO_SILK_REF:
                        continue
                    d = c.distance(cg)
                    if best is None or d < best[1]:
                        best = (r2, d)
                if best and best[1] + AMBIG_MARGIN_MM < d_own - EPS and ref in SILK_AMBIG_ACCEPT:
                    info.setdefault("ref_ambiguous_accepted", []).append(
                        {"part": ref, "at": at(i["geom"]), "own_mm": round(d_own, 3), "nearest": best[0],
                         "nearest_mm": round(best[1], 3), "reason": SILK_AMBIG_ACCEPT[ref]})
                elif best and best[1] + AMBIG_MARGIN_MM < d_own - EPS:
                    add("SILK-REF-AMBIGUOUS", (i["uuid"],), {"part": ref, "at": at(i["geom"]), "own_mm": round(d_own, 3),
                                                             "nearest": best[0], "nearest_mm": round(best[1], 3)})

        # ---- under another part (marks: GUIDE-CLIPPED)
        for it in here:
            if it["mark"]:
                continue
            g = it["geom"]
            cov, hit = covered_by_parts(g, it["owner"])
            if not hit or not g.area:
                continue
            frac = g.intersection(cov).area / g.area
            if frac > UNDER_PART_FRAC:
                level = "FAIL" if it["kind"] == "text" else "WARN"
                add("SILK-UNDER-PART", (it["uuid"],), {"item": describe(it), "part": it["owner"], "under": hit[:6],
                                                       "hidden_frac": round(frac, 3)}, level)

    # ---- KiCad's own DRC silk results
    if vs is not None:
        info["drc_report"] = str(drc_report)
        info["drc_silk_violations"] = len(vs)
        for v in vs:
            uu = [x.get("uuid") for x in v.get("items", [])]
            silk_uu = [u for u in uu if u in by_uuid]
            cls = KICAD_SILK[v["type"]]
            desc = [x.get("description", "") for x in v.get("items", [])]
            entry = {"kicad": v.get("description", ""), "items": desc, "uuids": uu, "source": "kicad",
                     "part": by_uuid[silk_uu[0]]["owner"] if silk_uu else None}
            if cls == "SILK-OVER-PAD":
                mk = [u for u in silk_uu if by_uuid[u]["mark"]]
                if mk:
                    it = by_uuid[mk[0]]
                    add("SILK-GUIDE-CLIPPED", (it["owner"], "kicad", frozenset(uu)),
                        dict(entry, part=it["owner"], mark=it["text"] or "shape"))
                    continue
                if not any(d.startswith("Pad") or " pad " in d.lower() for d in desc):
                    cls = "SILK-OVER-MASK"
                add(cls, (silk_uu[0],) if silk_uu else (frozenset(uu),), entry)
            elif cls == "SILK-OVERLAP":
                if len(silk_uu) == 2:
                    a, c = by_uuid[silk_uu[0]], by_uuid[silk_uu[1]]
                    ra, rc = SILK_PRIORITY.index(role(a)), SILK_PRIORITY.index(role(c))
                    entry.update(move=describe(a) if ra > rc else describe(c) if rc > ra else None,
                                 keep=describe(c) if ra > rc else describe(a) if rc > ra else None)
                add(cls, (frozenset(silk_uu),) if len(silk_uu) == 2 else (frozenset(uu),), entry)
            else:
                add(cls, (silk_uu[0],) if silk_uu else (frozenset(uu),), entry)
    else:
        info["drc_report"] = None

    counts = {c: len(fails[c]) for c in CHECKS}
    info["warn_counts"] = {c: len(warns[c]) for c in CHECKS if warns[c]}
    info["by_prefix"] = {c: _by_prefix(fails[c]) for c in CHECKS if fails[c]}
    info["total_s"] = round(time.time() - t0, 1)
    status = "PASS" if not any(counts[c] for c in checks) else "FAIL"
    return {"status": status, "board": str(pcb), "checks": list(checks), "counts": counts,
            "fails": fails, "warns": warns, "info": info}


def _by_prefix(entries):
    """{part prefix: count} of one class's findings ('board' for board-level items, '?' when unknown)"""
    out = {}
    for e in entries:
        parts = e.get("parts") or [e.get("part")]
        for p in {x for x in parts if x} or {None}:
            k = silk_marks.prefix(p) if p else ("board" if e.get("item", "").startswith("board") else "?")
            out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def require(pcb, out_json, drc_report=None):
    """run_gates hook (KiCad Python): writes the report, raises on any FAIL."""
    res = check(pcb, drc_report)
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if res["status"] != "PASS":
        raise RuntimeError(f"qa_silk FAILED {{{', '.join(f'{k}: {v}' for k, v in res['counts'].items() if v)}}} "
                           f"(report: {out_json})")
    return out_json


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", nargs="?", default=str(LC.MAIN_PCB))
    ap.add_argument("--json")
    ap.add_argument("--drc-report")
    a = ap.parse_args(argv)
    try:
        res = check(a.board, a.drc_report)
    except Exception as e:                                # fail closed
        import traceback
        traceback.print_exc()
        print(f"qa_silk ERROR: {e!r}")
        return 2
    if a.json:
        out = drc_check_coverage.project_path(a.json, output=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"qa_silk {res['status']}  {a.board}  (DRC report: {res['info']['drc_report']}; {res['info']['total_s']} s)")
    for k in CHECKS:
        n, w = len(res["fails"][k]), len(res["warns"][k])
        print(f"  {k:19s} {'FAIL' if n else 'ok':4s} {n}" + (f"   (warn {w})" if w else "")
              + (f"   by prefix {res['info']['by_prefix'][k]}" if n else ""))
        for it in res["fails"][k][:6]:
            print("     ", json.dumps(it, default=str)[:240])
    for k, why in NOT_APPLICABLE.items():
        print(f"  {k:19s} n/a  ({why})")
    if res["info"].get("ref_omit_manifest"):
        om = res["info"].get("ref_omitted", [])
        print(f"  references omitted per {res['info']['ref_omit_manifest']['path']}: {len(om)} ({' '.join(om)})")
    print(f"qa_silk {res['status']}: " + (", ".join(f"{k} {v}" for k, v in res["counts"].items() if v) or "0 findings"))
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
