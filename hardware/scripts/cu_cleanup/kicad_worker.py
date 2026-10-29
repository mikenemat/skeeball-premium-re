# ported from din8r-chassis-thermal/scripts/cu_cleanup/kicad_worker.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R tools/pfr2/copper_cleanup.py (C:/work/din-relay-8ch: native_apply / remove_items / gate / dump), adapted for CT (din8r-chassis-thermal MAIN)
"""KiCad-Python worker of scripts/copper_cleanup.py: ONE board, ONE pcbnew.LoadBoard per process (KiCad 10 may hand back
dead SWIG objects on a second LoadBoard), one job per call.

  py scripts/local_run.py cu_cleanup/kicad_worker.py dump  BOARD OUT.json
  py scripts/local_run.py cu_cleanup/kicad_worker.py apply BOARD PLAN.json [--dump GEOM.json]
  py scripts/local_run.py cu_cleanup/kicad_worker.py gate  BOARD OUT.json [--fast]
  py scripts/local_run.py cu_cleanup/kicad_worker.py lq    BOARD OUT.json

apply  PLAN = {"delete": [uuid], "moves": {via uuid: [x, y]}, "widen": {track uuid: w}, "adds": [{uuid, net, layer, s, e,
       w}], "vias": [{uuid, net, x, y, d, drill}], "refill": bool}. Deletes go by UUID in the serialized board (never
       SWIG Remove / Delete), only segment / arc / via items, and NEVER a locked one (the run aborts: CT's locked copper
       is deliberate hand copper); moves (SetPosition) / widths (SetWidth) refuse locked items the same way; new tracks /
       vias get deterministic UUIDs; refill = ONE native refill of all copper zones; pcb_rules.apply() then
       pcbnew.SaveBoard (net classes stay in the .kicad_pro). --dump writes the saved board's geometry (same process).
gate   qa_copper_landing.check itself (all checks) with every uuid of a TRACK-END / TRACK-ORPHAN finding listed (the
       gate truncates to 30; patched in what it REPORTS only); --fast also skips the TRACK-JOG shortcut screen (TRACK-JOG
       then reads 0: the working passes do not use it; the arbiter runs the full gate).
lq     qa_layout_quality.check itself (all checks).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPTS))
import board_const  # noqa: E402,F401  (first: tools/pylib shapely for KiCad's Python)
import pcbnew  # noqa: E402

DELETABLE = re.compile(r'\((segment|arc|via)\b')
UID = re.compile(r'\(uuid "([^"]+)"\)')


class LockedEdit(RuntimeError):
    pass


def remove_items(text, uuids):
    """delete the top-level segment / arc / via items with these UUIDs from a native board serialization (one parse,
    the kept text joined once). Every UUID must match exactly one item; a locked item is never deleted."""
    depth, quoted, escaped, start = 0, False, False, None
    ranges, found = [], set()
    i = 0
    special = re.compile(r'[()"\\]')
    while True:
        m = special.search(text, i)
        if m is None:
            break
        index, ch = m.start(), m.group()
        i = index + 1
        if escaped:
            escaped = False
            continue
        if quoted and ch == "\\":
            i = index + 2
            continue
        if ch == '"':
            quoted = not quoted
        if quoted:
            continue
        if ch == "(":
            if depth == 1:
                start = index
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 1 and start is not None:
                if DELETABLE.match(text, start):
                    u = UID.search(text, start, index + 1)
                    if u and u[1] in uuids:
                        body = text[start:index + 1]
                        if "(locked yes)" in body or re.search(r"\(locked\)", body):
                            raise LockedEdit(f"refusing to delete LOCKED item {u[1]}")
                        if u[1] in found:
                            raise ValueError(f"UUID matched twice: {u[1]}")
                        ranges.append((start, index + 1))
                        found.add(u[1])
                start = None
    if depth != 0 or quoted or escaped:
        raise ValueError("Malformed native board serialization")
    if found != set(uuids):
        raise ValueError("Not every deletion UUID was matched: " + str(sorted(set(uuids) - found)[:10]))
    out, last = [], 0
    for b_, e_ in ranges:
        out.append(text[last:b_])
        last = e_
    out.append(text[last:])
    return "".join(out)


def apply(board, plan, dump_out=None):
    import pcb_rules
    board = Path(board)
    dels = set(plan.get("delete", []))
    if dels:
        board.write_text(remove_items(board.read_text(encoding="utf-8"), dels), encoding="utf-8")
    b = pcbnew.LoadBoard(str(board))
    lid = {b.GetLayerName(l): l for l in range(pcbnew.PCB_LAYER_ID_COUNT) if pcbnew.IsCopperLayer(l)}
    moves, widen = plan.get("moves", {}), plan.get("widen", {})
    if moves or widen:
        hit = set()                     # identical segments under one UUID: set them all
        for t in b.GetTracks():
            u = t.m_Uuid.AsString()
            if u not in moves and u not in widen:
                continue
            if t.IsLocked():
                raise LockedEdit(f"refusing to move / widen LOCKED item {u}")
            if t.Type() == pcbnew.PCB_VIA_T and u in moves:
                t.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(moves[u][0]), pcbnew.FromMM(moves[u][1])))
                hit.add(u)
            elif t.Type() != pcbnew.PCB_VIA_T and u in widen:
                t.SetWidth(pcbnew.FromMM(widen[u]))
                hit.add(u)
        assert hit == set(moves) | set(widen), ("move / widen: not every item found", len(hit), len(moves), len(widen))
    keep = []                           # SWIG wrappers stay referenced until the process ends
    for t in plan.get("adds", []):
        q = pcbnew.PCB_TRACK(b)
        q.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(t["s"][0]), pcbnew.FromMM(t["s"][1])))
        q.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(t["e"][0]), pcbnew.FromMM(t["e"][1])))
        q.SetWidth(pcbnew.FromMM(t["w"]))
        q.SetLayer(lid[t["layer"]])
        net = b.FindNet(t["net"])
        assert net is not None and net.GetNetCode() > 0, ("net missing", t["net"])
        q.SetNet(net)
        q.SetUuidDirect(pcbnew.KIID(t["uuid"]))
        b.Add(q)
        keep.append(q)
    vias = plan.get("vias", [])
    if vias:
        # new through vias (stitches) copy the fill / cap / unconnected-layer settings of an existing via of that size
        refs = {}
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                k = (round(pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)), 3), round(pcbnew.ToMM(t.GetDrillValue()), 3))
                refs.setdefault(k, t)
        for v in vias:
            ref = refs.get((round(v["d"], 3), round(v["drill"], 3))) or next(iter(refs.values()))
            q = pcbnew.PCB_VIA(b)
            q.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(v["x"]), pcbnew.FromMM(v["y"])))
            q.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            q.SetWidth(pcbnew.FromMM(v["d"]))
            q.SetDrill(pcbnew.FromMM(v["drill"]))
            net = b.FindNet(v["net"])
            assert net is not None and net.GetNetCode() > 0, ("net missing", v["net"])
            q.SetNet(net)
            for f in ("SetFillingMode", "SetCappingMode", "SetPrimaryDrillFilledFlag", "SetPrimaryDrillCappedFlag"):
                g = "Get" + f[3:]
                if hasattr(q, f) and hasattr(ref, g):
                    try:
                        getattr(q, f)(getattr(ref, g)())
                    except Exception:
                        pass
            try:
                q.Padstack().SetUnconnectedLayerMode(ref.Padstack().UnconnectedLayerMode())
            except Exception:
                pass
            q.SetUuidDirect(pcbnew.KIID(v["uuid"]))
            b.Add(q)
            keep.append(q)
    if plan.get("refill"):
        pcbnew.ZONE_FILLER(b).Fill([z for z in b.Zones() if not z.GetIsRuleArea()])
    pcb_rules.apply(b)
    pcb_rules.save(b, board)
    if dump_out:
        import dump_geom
        dump_geom.dump(str(board), dump_out, b)
    return keep


_FULL = {}


def full_check(fast=False):
    """qa_copper_landing.check with every uuid of a TRACK-END / TRACK-ORPHAN finding listed (the gate truncates to 30;
    a cut-short delete would leave the rest of the chain as new loose copper): the SAME code, patched only in what it
    reports; fast: the TRACK-JOG shortcut screen is skipped (its sites report nothing)"""
    import inspect
    import qa_copper_landing as Q
    if fast not in _FULL:
        src = inspect.getsource(Q.check)
        pats = [('for i in idx][:30]})', 'for i in idx]})'), ('for x in comp][:30]})', 'for x in comp]})')]
        if fast:
            pats.append(("screen = jog_screen(b, pcb, jog_sites, tracks) if jog_sites else []", "screen = []"))
        for a, b_ in pats:
            if src.count(a) != 1:
                raise RuntimeError(f"qa_copper_landing.check changed: patch point {a!r} not found once")
            src = src.replace(a, b_)
        ns = dict(Q.__dict__)
        exec(compile(src, Q.__file__, "exec"), ns)
        _FULL[fast] = ns["check"]
    return _FULL[fast]


def main(argv):
    cmd, board = argv[0], argv[1]
    if cmd == "dump":
        import dump_geom
        dump_geom.dump(board, argv[2])
    elif cmd == "apply":
        plan = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        dump_out = argv[argv.index("--dump") + 1] if "--dump" in argv else None
        apply(board, plan, dump_out)
    elif cmd == "gate":
        res = full_check("--fast" in argv)(board)
        res["fast"] = "--fast" in argv
        Path(argv[2]).write_text(json.dumps(res, default=str), encoding="utf-8")
    elif cmd == "lq":
        import qa_layout_quality as LQ
        res = LQ.check(board)
        Path(argv[2]).write_text(json.dumps(res, default=str), encoding="utf-8")
    else:
        raise SystemExit(__doc__)
    print("worker ok", cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
