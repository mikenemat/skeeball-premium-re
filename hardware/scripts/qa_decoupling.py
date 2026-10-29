# ported from din8r-chassis-thermal/scripts/qa_decoupling.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/qa_decoupling.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN).
"""Decoupling / support-part proximity gate (KiCad Python):

    py scripts/local_run.py qa_decoupling.py [BOARD] [--json OUT]        exit 0 PASS, 1 FAIL, 2 tool error

ONE decoupling-distance rule on CT (lead / HW-ADVQA2 owner 2026-10-17): scripts/qa_power_layout.py (QA_LOG HW-ADVQA2
H9, wired into run_gates.py) owns DECAP = [(IC, pin, part, datasheet reason)] for U1 / U5 / U6 / U7 / U9 / U10 and
MAX_MM (3.0 mm pad centre to pad centre, either side). This gate IMPORTS that table and that limit (read live at every
run: qa_power_layout.DECAP / qa_power_layout.MAX_MM) and never sets a second distance limit for a pin or a cap the
table covers; it adds what the table does not cover, the parent's checks adapted to CT:

  DECAP-ROW  A qa_power_layout.DECAP row this gate depends on - the row of an IC power pin (below), or a row whose part
             is a bypass cap - is not met: the part is not on the board, has no pad on the pin's net, or its pad on that
             net is > qa_power_layout.MAX_MM from the pin pad (centre to centre, either side: the table's own rule,
             evaluated exactly as qa_power_layout does). Reported once per row; a covered IC pin / row cap is "covered".
  DECAP-NOTE The table and design.py disagree: a row's part names in its design note ("pin 3 VDD3P3", "pins 55 / 56")
             pins of the row's IC and the row's pin is not among them (both are +3V3 pins, so the distance alone would
             pass the wrong pairing). One source is wrong; fix it there.
  IC-NOCAP   IC side (DIN-8R DEC-GATE-20261009: the cap-side pairing lets a cap beside the WRONG IC on a shared rail
             pass): every IC (U*, X*) power pin on a supply net that the table does NOT cover needs a bypass cap that
             may serve it within LIMIT_MM (pad centre to cap supply-pad centre; a bulk cap counts only within LIMIT_MM):
             on the IC's side, or stacked under it as a serving decap (serving_stack -> qa_layout_quality.serving_decap,
             the ONE definition), or a documented SIDE_EXCEPTIONS cap whose text names that IC (none on CT). A cap
             serves only the ICs it is DECLARED for (declared_ics): the U / X refs its design note names that are on its
             net; with none named, the ICs of its own design block on that net; with none of those, any IC on the net.
             Power pin = schematic pin type power_in, plus (CT) a passive pin that repeats the name of a power_in pin of
             the same symbol (KiCad marks stacked supply pins passive: ESP32-S3 VDD3P3 3 / VDDA 56, W5500 AVDD 8 / 11 /
             15 / 17 / 21 - each is a physical supply pin). Fail closed: an uncovered power pin with no cap that may
             serve it FAILs.
  CAP-FAR    Cap side: every bypass cap (Device:C*, one pad on a supply net, the other on a ground net, the supply net
             reaching a load) that is not a DECAP-row part: its supply pad to its paired load's nearest same-net pad
             <= LIMIT_MM (BULK_LIMIT_MM for bulk caps >= 10 uF). Loads: ICs (U), connectors (J), inductors (L), CT's
             transformer windings (T, LOAD_PREFIXES) and LEDs; bulk caps also pair with transistors (Q, the parent's
             rail switches) and the BULK_SOURCES (CT: the flyback rectifier D6, the +12V source). Regulator pairing
             (DIN-8R lead 2026-10-05): a cap of a regulator's design block on one of the regulator's nets (its own
             pads, plus a switcher's inductor output) pairs with that regulator / its inductor, or another load of its
             OWN block on that net when nearer - never the nearest load IC of another block on the rail.
  SIDE       Same-side rule (DIN-8R owner 2026-09-30, bottom-side SMT): a bypass cap sits on the same side as the SMD
             load it serves (its regulator, else its own block's load, else the nearest; a DECAP-row cap: the row's
             IC); a THT load has pads on both sides. On the other side it passes only as a SERVING decap (DIN-8R owner
             2026-10-05: "a back-side decoupling cap directly under the IC it decouples ... Yes thats fine"): stacked
             under that load (pads within qa_layout_quality.XSTACK_GAP_MM in plan) and accepted by
             qa_layout_quality.serving_decap (both cap nets on the load, one a rail / ground; the stacked pads face only
             the load's own pads - any of them, signal / NC included, CT owner 2026-10-17 SERVING_DECAP_ANY_IC_PAD; each
             cap pad has a same-net via within XSTACK_DECAP_VIA_MM or a fitting via-in-pad). qa_power_layout's "either side" is a distance rule only; this side rule applies on top.
Exceptions: SIDE_EXCEPTIONS / SIDE_BIND / ACCEPTED are EMPTY on CT (no owner acceptances); the parent's mechanism is
kept (bound exceptions, exact accepted findings, a stale entry FAILs), so a future owner acceptance has one home.
Pin types: the lib_symbols embedded in the board's schematic set (hardware/main/*.kicad_sch), else the symbol libraries
(hardware/lib/din8r_ct.kicad_sym + KiCad 10's, via netlist_core.symbol_pins). An IC whose pin types cannot be
resolved is ic_unresolved and exit 2 (fail closed). Design = scripts/design.py (D.parts: lib_id, value, note, block).
Dropped parent-only parts: the MAIN rev C design loader (bom_design), the relay coil-diode report (no relays), every
MAIN / UI SIDE_EXCEPTIONS / SIDE_BIND / ACCEPTED entry.
"""
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_const as K  # noqa: E402  (first: tools/pylib shapely for KiCad's Python)
import pcbnew  # noqa: E402

import qa_layout_quality as LQ  # noqa: E402
import qa_power_layout as PL  # noqa: E402  (DECAP / MAX_MM: the one decoupling-distance rule, read live)

# ------------------------------------------------------------------------------------------------ named constants
LIMIT_MM = 6.0                   # bypass cap / IC power pin limit (parent default), for what DECAP does not cover
BULK_LIMIT_MM = 15.0             # bulk caps (>= 10 uF) on the cap side (parent default)
BULK_MIN_F = 9.9e-6              # bulk: >= 10 uF ("10uF" parses to 9.999...e-6)
IC_PREFIXES = ("U", "X")
# loads a supply cap can serve: ICs, connectors (module / cable supply pins), the parent's regulator inductors (L), and
# CT's transformer windings (T: T2's VPP primary is the flyback input caps' load - C12 / C13 in the primary hot loop,
# TPS23751EVM SLVU754A 7.3; the converter magnetic plays the parent's L role); LEDs by lib_id
LOAD_PREFIXES = ("U", "J", "L", "T")
BULK_PARTNER_PREFIXES = ("PS", "Q")   # parent: bulk caps also serve supply-module outputs (PS) and rail switches (Q)
# CT bulk-cap partners by ref: the parts that SOURCE a rail held up by bulk caps (the parent's PS1 +Vo role)
BULK_SOURCES = {
    "D6": "flyback secondary rectifier SS510B: the +12V source; C17-C20 are its output caps (their loop area is "
          "qa_power_layout LOOP secondary's rule, their distance this pairing)",
}
STACKED_POWER_PINS = True        # IC side: passive pins repeating a power_in pin's name are power pins (see IC-NOCAP)
# regulator part classes recognised by value / MPN when the symbol is a custom one: TI TLV7xx / TPS7xx / TPS6xx / TPS5xx
# LDOs and bucks, LMR5 bucks, LM317, LP59xx (parent list; CT U5 TPS62933 is a Regulator_Switching symbol anyway)
REGULATOR_RE = re.compile(r"^(TLV7\d|TPS7|TPS6|TPS5|LMR5|LM317|LP59)", re.I)
# a U / X ref named in a design note ("Decouples U12", "U47 VDD bypass"; the parent's doubled-U spelling), never a ref
# inside a net name ("VREF_U37")
NOTE_REF_RE = re.compile(r"(?<![A-Za-z0-9_])U?([UX]\d+)(?![0-9A-Za-z])")
NOTE_PIN_RE = re.compile(r"(?<![A-Za-z0-9_])pins?\s+(\d+(?:\s*(?:/|,|and)\s*\d+)*)", re.I)   # DECAP-NOTE
# bypass caps allowed on the other side than their load: ref -> the documented short path (a text naming an IC lets
# the cap serve that IC on the IC side). CT: none - the mechanism is kept (empty).
SIDE_EXCEPTIONS = {}
# exceptions are bound (parent MAIN policy): cap -> (cap side "F" / "B", side-rule load, max mm, {IC served across
# sides: max mm}); an exception without a binding is never honoured. CT: none.
SIDE_BIND = {}
# owner-accepted findings, each matching ONE live finding exactly ("distance": cap -> (net, load, max mm, reason);
# "side": cap -> (load, max mm, reason); "ic": "IC.pin" -> (net, cap, max mm, reason)); stale entries FAIL. CT: none.
ACCEPTED = {"distance": {}, "side": {}, "ic": {}}

CLASSES = ("DECAP-ROW", "DECAP-NOTE", "IC-NOCAP", "CAP-FAR", "SIDE", "STALE")
T = pcbnew.ToMM


def farads(v):
    m = re.match(r"\s*([\d.]+)\s*([pnuµ])F", v or "")
    if not m:
        return None
    return float(m.group(1)) * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6}[m.group(2)]


def is_ground(n):
    return bool(n) and bool(LQ.GROUND_RE.match(n))


def is_supply(n):
    """a supply / reference / internal-regulator net: qa_layout_quality's definition (DECAP-LOOP), one source"""
    return bool(n) and not is_ground(n) and (n.startswith("+") or bool(LQ.SUPPLY_RE.search(n)))


def xy(p):
    q = p.GetPosition()
    return (T(q.x), T(q.y))


def is_load(ref, DB):
    led = ref.startswith("D") and "LED" in (DB.parts[ref].lib_id if ref in DB.parts else "")
    return ref.startswith(LOAD_PREFIXES) or led


# ======================================================================================================== pairing
def regulators(b, DB):
    """{ref: (block, {net: [(x, y, ref)] the regulator's and its inductor's pads on that net})}"""
    pads = {fp.GetReference(): [(p.GetNetname(), *xy(p)) for p in fp.Pads()] for fp in b.GetFootprints()}
    ind = {r: ps for r, ps in pads.items() if r.startswith("L")}
    out = {}
    for r, ps in pads.items():
        part = DB.parts.get(r)
        if not r.startswith("U") or part is None:
            continue
        nets = {n for n, _, _ in ps if n}
        sw = [(lr, lps) for lr, lps in ind.items() if any(n in nets and not is_supply(n) and not is_ground(n)
                                                           for n, _, _ in lps)]
        if not (part.lib_id.startswith("Regulator_") or REGULATOR_RE.match(part.value or "") or sw):
            continue
        at = {}
        for n, x, y in ps:
            if n:
                at.setdefault(n, []).append((x, y, r))
        for lr, lps in sw:                       # a switcher's output is the inductor's other net
            for n, x, y in lps:
                at.setdefault(n, []).append((x, y, lr))
        out[r] = (part.block, at)
    return out


def bypass_cap(fp, DB):
    """(supply net, supply pad) of a bypass cap (Device:C*, one supply pad, one ground pad), else None"""
    part = DB.parts.get(fp.GetReference())
    if part is None or not part.lib_id.startswith("Device:C"):
        return None
    nets = [p.GetNetname() for p in fp.Pads()]
    sup = [n for n in nets if is_supply(n)]
    if len(sup) != 1 or not any(is_ground(n) for n in nets):
        return None
    return sup[0], [p for p in fp.Pads() if p.GetNetname() == sup[0]][0]


def declared_ics(DB, cap, net, ics_on_net):
    """(ICs the cap may serve, basis): the U / X refs its note names that are on its net ("note"); else the ICs of its
    design block on the net ("block"); else every IC on the net ("rail")"""
    part = DB.parts[cap]
    named = {r for r in NOTE_REF_RE.findall(getattr(part, "note", "") or "") if r in ics_on_net}
    if named:
        return named, "note"
    blk = {r for r in ics_on_net if r in DB.parts and DB.parts[r].block and DB.parts[r].block == part.block}
    if blk:
        return blk, "block"
    return set(ics_on_net), "rail"


# ======================================================================================================== pin types
def _sch_pins(board_path):
    """lib_id -> [(number, name, etype)] from the lib_symbols embedded in the schematic set beside the board"""
    from netlist_core import PIN_RE, _symbol_block
    text = "".join(p.read_text(encoding="utf-8") for p in sorted(Path(board_path).parent.glob("*.kicad_sch")))

    def get(lib_id):
        blk = _symbol_block(text, lib_id) if text else None
        return None if blk is None else [(num, nm, et) for et, nm, num in PIN_RE.findall(blk)]
    return get


def power_pin_numbers(pins):
    """{pin number} of the power pins of a symbol pin table [(number, name, etype)]: power_in, plus (STACKED_POWER_PINS)
    a passive pin carrying the name of a power_in pin of the same symbol"""
    pw_names = {nm for _, nm, et in pins if et == "power_in"}
    return {num for num, nm, et in pins
            if et == "power_in" or (STACKED_POWER_PINS and et == "passive" and nm in pw_names)}


def pin_types(b, DB):
    """({ref: {pad number: 'power' | other}} for every U / X footprint of the design, [unresolved refs]): the board's
    schematic set first (the native source the board was built from), else the symbol library"""
    from netlist_core import symbol_pins
    sch = _sch_pins(b.GetFileName()) if b.GetFileName() else (lambda lib_id: None)
    out, bad = {}, []
    for fp in b.GetFootprints():
        r = fp.GetReference()
        part = DB.parts.get(r)
        if part is None or not r.startswith(IC_PREFIXES):
            continue
        pins = sch(part.lib_id)
        if pins is None:
            try:
                pins = symbol_pins(part.lib_id)
            except (KeyError, OSError, ValueError):
                pins = None
        if not pins:
            bad.append(r)
            continue
        pw = power_pin_numbers(pins)
        out[r] = {num: ("power_in" if num in pw else et) for num, _, et in pins}
    return out, bad


# ======================================================================================================== DECAP table
def decap_rows():
    """qa_power_layout.DECAP read live: {(ic, pin): [(part, why)]}, {part: [(ic, pin, why)]}"""
    by_pin, by_part = {}, {}
    for ic, pin, part, why in PL.DECAP:
        by_pin.setdefault((ic, pin), []).append((part, why))
        by_part.setdefault(part, []).append((ic, pin, why))
    return by_pin, by_part


def decap_row(b, ic, pin, part):
    """one qa_power_layout DECAP row, evaluated exactly as qa_power_layout does: (net, d mm | None, problem | None)"""
    fic, fpart = b.FindFootprintByReference(ic), b.FindFootprintByReference(part)
    if fic is None:
        return None, None, f"IC {ic} not on the board"
    pp = next((p for p in fic.Pads() if p.GetNumber() == pin), None)
    if pp is None:
        return None, None, f"{ic} has no pin {pin}"
    net = pp.GetNetname()
    if fpart is None:
        return net, None, f"{part} not on the board"
    cand = [p for p in fpart.Pads() if p.GetNumber() and p.GetNetname() == net]
    if not cand:
        return net, None, f"no pad of {part} on {net}"
    d = min(math.dist(xy(pp), xy(q)) for q in cand)
    return net, d, (None if d <= PL.MAX_MM else f"{d:.2f} mm > qa_power_layout.MAX_MM {PL.MAX_MM}")


def note_pins(note):
    """pin numbers a design note names ("pin 2 VDD3P3", "VDDA pins 55 / 56")"""
    out = set()
    for grp in NOTE_PIN_RE.findall(note or ""):
        out |= set(re.findall(r"\d+", grp))
    return out


# ======================================================================================================== geometry
def pad_dist(b, cap_fp, net, load):
    """mm from cap_fp's pad on net to the nearest pad of footprint load on that net (inf when none)"""
    lf = b.FindFootprintByReference(load)
    cps = [p for p in cap_fp.Pads() if p.GetNetname() == net]
    if lf is None or not cps:
        return math.inf
    c = xy(cps[0])
    return min([math.dist(xy(p), c) for p in lf.Pads() if p.GetNetname() == net] or [math.inf])


def bound_ok(b, cap_fp, net, bind, load, ic=False):
    """a SIDE_EXCEPTIONS entry is bound (SIDE_BIND: cap side, the side-rule load and its max pad distance, and the ICs
    the cap may serve across sides with theirs); an unbound list (a fixture's) keeps the plain rule"""
    if bind is None:
        return True
    side, side_load, side_mx, serves = bind
    if side != ("B" if cap_fp.IsFlipped() else "F"):
        return False
    mx = serves.get(load) if ic else (side_mx if load == side_load else None)
    return mx is not None and pad_dist(b, cap_fp, net, load) <= mx + 1e-6


def serving_stack(LB, cap, load):
    """qa_layout_quality.serving_decap() on the stacked pad pairs of cap and load (qa_layout_quality.Board LB): False
    when they are not stacked at all (a cap merely on the other side is not 'directly under' its load)"""
    c, u = LB.fps.get(cap), LB.fps.get(load)
    if c is None or u is None or c["side"] == u["side"]:
        return False
    lst = []
    for cp in c["smd_pads"]:
        for up in u["pads"]:
            if not up["smd"] or c["side"] not in cp["poly"] or u["side"] not in up["poly"]:
                continue
            d = cp["poly"][c["side"]].distance(up["poly"][u["side"]])
            if d < LQ.XSTACK_GAP_MM:
                fpad, bpad = (cp, up) if c["side"] == pcbnew.F_Cu else (up, cp)
                lst.append((LB.pad_ref(fpad), LB.pad_ref(bpad), round(d, 3), fpad["net"], bpad["net"], fpad["pos"],
                            fpad, bpad))
    return bool(lst) and LQ.serving_decap(LB, lst)


def accept_match(acc, kind, key, **got):
    """the owner-accepted entry ACCEPTED[kind][key] when the live finding matches it exactly, else None"""
    e = acc.get(kind, {}).get(key)
    if e is None:
        return None
    if kind == "side":
        load, mx, _ = e
        return e if got["load"] == load and got["d"] <= mx + 1e-6 else None
    net, who, mx, _ = e
    return e if got["net"] == net and got["who"] == who and got["d"] is not None and got["d"] <= mx + 1e-6 else None


# ======================================================================================================== check
def check(b, DB, limit=None, bulk_limit=None, exceptions=None, types=None, bind=None, accepted=None, LB=None):
    """-> report dict (see main / the module doc). b: a pcbnew board (loaded from its file when serving stacks are to
    be recognised; LB: its qa_layout_quality.Board when the caller has one, else built lazily from b's file).
    exceptions / bind / accepted default to this module's tables (empty on CT); types: {ref: {pad: etype}} (default
    pin_types(b, DB))."""
    limit = LIMIT_MM if limit is None else limit
    bulk_limit = BULK_LIMIT_MM if bulk_limit is None else bulk_limit
    # the module's tables are a BOUND policy even while empty: an exception without a SIDE_BIND entry is never honoured
    # (fail closed); an explicit exception list without bind (a fixture) keeps the plain rule
    bound = exceptions is None or bind is not None
    if exceptions is None:
        exceptions, bind = SIDE_EXCEPTIONS, (SIDE_BIND if bind is None else bind)
    bind = {} if bind is None else bind
    accepted = ACCEPTED if accepted is None else accepted
    used, exc_used = set(), set()
    lbs = [LB] if LB is not None else []

    def lb_get():
        if not lbs and b.GetFileName():
            lbs.append(LQ.Board(b.GetFileName()))
        return lbs[0] if lbs else None

    def exc_ok(cfp, net, load, ic=False):
        c = cfp.GetReference()
        if c not in exceptions or (ic and load not in NOTE_REF_RE.findall(exceptions[c])):
            return False
        if bound and (c not in bind or not bound_ok(b, cfp, net, bind[c], load, ic)):
            return False
        exc_used.add(c)
        return True

    fails = {k: [] for k in CLASSES}
    info = {"limit_mm": limit, "bulk_limit_mm": bulk_limit, "decap_max_mm": PL.MAX_MM}
    by_pin, by_part = decap_rows()
    unresolved = []
    if types is None:
        types, unresolved = pin_types(b, DB)

    # ------------------------------------------------------------------ the DECAP rows this gate depends on
    power_pins = []                             # (ic fp, pad) power pins on supply nets
    for fp in b.GetFootprints():
        r = fp.GetReference()
        if r not in types:
            continue
        for pd in fp.Pads():
            if types[r].get(pd.GetNumber()) == "power_in" and is_supply(pd.GetNetname()):
                power_pins.append((fp, pd))
    caps = {}                                    # ref -> (fp, supply net, supply pad)
    for fp in b.GetFootprints():
        bc = bypass_cap(fp, DB)
        if bc is not None:
            caps[fp.GetReference()] = (fp, *bc)
    want = set()
    for fp, pd in power_pins:
        for part, _ in by_pin.get((fp.GetReference(), pd.GetNumber()), []):
            want.add((fp.GetReference(), pd.GetNumber(), part))
    for part in caps:
        for ic, pin, _ in by_part.get(part, []):
            want.add((ic, pin, part))
    row_res = {}
    for ic, pin, part in sorted(want):
        net, d, prob = decap_row(b, ic, pin, part)
        row_res[(ic, pin, part)] = (net, d, prob)
        if prob:
            fp = b.FindFootprintByReference(ic)
            pp = next((p for p in fp.Pads() if p.GetNumber() == pin), None) if fp else None
            fails["DECAP-ROW"].append({"ic": ic, "pin": pin, "part": part, "net": net,
                                       "d_mm": None if d is None else round(d, 3), "max_mm": PL.MAX_MM,
                                       "at": None if pp is None else LQ.r3(xy(pp)), "what": prob})
    info["decap_rows_used"] = len(want)
    info["decap_rows_owned_by_qa_power_layout_only"] = len(PL.DECAP) - len(
        {(ic, pin, part) for ic, pin, part, _ in PL.DECAP} & want)
    # DECAP-NOTE: the row's part note names pins of the row's IC that exclude the row's pin
    for ic, pin, part, _ in PL.DECAP:
        p = DB.parts.get(part)
        if p is None:
            continue
        note = getattr(p, "note", "") or ""
        named = note_pins(note)
        if set(NOTE_REF_RE.findall(note)) - {ic}:
            continue                             # the note names another IC: its pin numbers may be that IC's
        if named and pin not in named:
            fails["DECAP-NOTE"].append({"ic": ic, "pin": pin, "part": part, "note_pins": sorted(named, key=int),
                                        "what": f"qa_power_layout.DECAP pairs {part} with {ic}.{pin}; its design note "
                                                f"names pin(s) {', '.join(sorted(named, key=int))}"})

    # ------------------------------------------------------------------ cap side
    regs = regulators(b, DB)
    block = {r: p.block for r, p in DB.parts.items()}
    load_pads, bulk_pads = {}, {}
    for fp in b.GetFootprints():
        rf = fp.GetReference()
        if is_load(rf, DB):
            for p in fp.Pads():
                load_pads.setdefault(p.GetNetname(), []).append((*xy(p), rf))
        if rf.startswith(BULK_PARTNER_PREFIXES) or rf in BULK_SOURCES:
            for p in fp.Pads():
                bulk_pads.setdefault(p.GetNetname(), []).append((*xy(p), rf))
    rows, side_bad, side_acc, serving, covered_caps = [], [], [], [], []
    for r, (fp, net, sp) in sorted(caps.items()):
        part = DB.parts[r]
        x, y = xy(sp)
        bulk = (farads(part.value) or 0) >= BULK_MIN_F
        reg_g = None
        if r in by_part:                         # a DECAP-row cap: the table's rows are its distance rule
            rr = [(row_res.get((ic, pin, r)), ic, pin) for ic, pin, _ in by_part[r]]
            covered_caps.append(r)
            u = by_part[r][0][0]
            ds = [x_[0][1] for x_ in rr if x_[0] and x_[0][1] is not None]
            d = max(ds) if ds else math.inf
            rows.append({"cap": r, "value": part.value, "net": net, "load": u, "d_mm": d, "bulk": bulk,
                         "regulator": None, "rule": "qa_power_layout.DECAP", "bad": False})   # verdict: DECAP-ROW
            side_load = u
        else:
            if net not in load_pads and not (bulk and net in bulk_pads):
                continue
            reg = [(g, at[net]) for g, (blk, at) in sorted(regs.items()) if blk == part.block and net in at]
            if reg:     # a cap of a regulator's block: the regulator, or another load of its OWN block
                loads = reg[0][1] + [q for q in load_pads.get(net, []) if block.get(q[2]) == part.block]
            else:
                loads = load_pads.get(net, []) + (bulk_pads.get(net, []) if bulk else [])
            d, u = min((math.hypot(x - a, y - c), ref) for a, c, ref in loads)
            lim = bulk_limit if bulk else limit
            reg = [g for g in reg if u in (g[0], *(q[2] for q in g[1]))]
            reg_g = reg[0][0] if reg else None
            rec = {"cap": r, "value": part.value, "net": net, "load": u, "d_mm": d, "bulk": bulk, "regulator": reg_g,
                   "rule": f"{'bulk ' if bulk else ''}limit {lim} mm", "bad": d > lim + 1e-9}
            rows.append(rec)
            own = [(math.hypot(x - a, y - c), ref) for a, c, ref in load_pads.get(net, []) if block.get(ref) == part.block]
            side_load = u if reg_g else (min(own)[1] if own else u)
        # same-side rule: the SMD load it serves (THT loads have pads on both sides)
        ufp = b.FindFootprintByReference(side_load)
        smd_load = ufp is not None and not any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in ufp.Pads())
        if smd_load and ufp.IsFlipped() != fp.IsFlipped() and not exc_ok(fp, net, side_load):
            lb = lb_get()
            if lb is not None and serving_stack(lb, r, side_load):
                serving.append((r, side_load))
                continue
            sb = {"cap": r, "load": side_load, "cap_side": "bottom" if fp.IsFlipped() else "top",
                  "load_side": "bottom" if ufp.IsFlipped() else "top", "net": net, "at": LQ.r3((x, y)),
                  "d_mm": round(pad_dist(b, fp, net, side_load), 3),
                  "what": "bypass cap on the other side than its load, not a serving stack under it"}
            if accept_match(accepted, "side", r, load=side_load, d=pad_dist(b, fp, net, side_load)):
                side_acc.append(sb)
                used.add(("side", r))
                continue
            side_bad.append(sb)
    for x in rows:
        if x["bad"]:
            if accept_match(accepted, "distance", x["cap"], net=x["net"], who=x["load"], d=x["d_mm"]):
                info.setdefault("cap_accepted", []).append(x["cap"])
                used.add(("distance", x["cap"]))
            else:
                fails["CAP-FAR"].append({**x, "d_mm": round(x["d_mm"], 3),
                                         "at": LQ.r3(xy(caps[x["cap"]][2])),
                                         "what": f"supply pad {x['d_mm']:.2f} mm from {x['load']} ({x['rule']})"})
    fails["SIDE"] = side_bad

    # ------------------------------------------------------------------ IC side
    ics_on = {}
    for fp in b.GetFootprints():
        if fp.GetReference().startswith(IC_PREFIXES):
            for p in fp.Pads():
                ics_on.setdefault(p.GetNetname(), set()).add(fp.GetReference())
    capl = []
    for r, (fp, net, sp) in caps.items():
        ics, basis = declared_ics(DB, r, net, ics_on.get(net, set()))
        capl.append((fp, net, *xy(sp), ics, basis))
    ic_rows = []
    for fp, pd in power_pins:
        r, pin, n = fp.GetReference(), pd.GetNumber(), pd.GetNetname()
        x, y = xy(pd)
        if (r, pin) in by_pin:                  # covered: the table decides (DECAP-ROW), never a second limit
            rr = [(part, row_res.get((r, pin, part), (None, None, "not evaluated"))) for part, _ in by_pin[(r, pin)]]
            ok = all(v[2] is None for _, v in rr)
            ic_rows.append({"ic": r, "pin": pin, "net": n, "covered": True, "ok": ok,
                            "rows": [[part, None if v[1] is None else round(v[1], 3), v[2]] for part, v in rr]})
            continue
        best = None
        for cfp, net, cx, cy, ics, basis in sorted(capl, key=lambda c: math.hypot(c[2] - x, c[3] - y)):
            if net != n or r not in ics:
                continue
            cref = cfp.GetReference()
            if cfp.IsFlipped() != fp.IsFlipped() and not exc_ok(cfp, net, r, ic=True):
                lb = lb_get()
                if lb is None or not serving_stack(lb, cref, r):
                    continue                     # the other side, not stacked under it: cannot serve it
            best = (math.hypot(cx - x, cy - y), cref, basis)
            break
        bad = best is None or best[0] > limit + 1e-9
        row = {"ic": r, "pin": pin, "net": n, "covered": False, "ok": not bad,
               "cap": best[1] if best else None, "d_mm": round(best[0], 3) if best else None,
               "basis": best[2] if best else None}
        ic_rows.append(row)
        if bad:
            if accept_match(accepted, "ic", f"{r}.{pin}", net=n, who=best[1] if best else None,
                            d=best[0] if best else None):
                info.setdefault("ic_accepted", []).append(f"{r}.{pin}")
                used.add(("ic", f"{r}.{pin}"))
                continue
            fails["IC-NOCAP"].append({**row, "at": LQ.r3((x, y)),
                                      "what": (f"nearest cap that may serve it: {best[1]} {best[0]:.2f} mm > {limit}"
                                               if best else "no bypass cap may serve it (declared, same side or "
                                                            "serving stack)")})
    # stale entries (bound policy): an accepted finding that is gone, or a bound exception that covered nothing
    for k, key in sorted((k, key) for k, es in accepted.items() for key in es if (k, key) not in used):
        fails["STALE"].append({"table": f"ACCEPTED[{k!r}]", "key": key, "what": "its finding is gone or changed"})
    for c in (sorted(set(exceptions) - exc_used) if bound else []):
        fails["STALE"].append({"table": "SIDE_EXCEPTIONS", "key": c, "what": "covers no cross-side load / IC"})
    info.update({"bypass_caps": len(caps), "decap_row_caps": sorted(covered_caps), "serving_decap": serving,
                 "side_accepted": [x["cap"] for x in side_acc], "regulator_pairs": {
                     x["cap"]: x["regulator"] for x in rows if x["regulator"]},
                 "ic_power_pins": len(ic_rows), "ic_power_pins_covered": sum(1 for x in ic_rows if x["covered"])})
    status = "ERROR" if unresolved else ("FAIL" if any(fails[c] for c in CLASSES) else "PASS")
    return {"board": b.GetFileName(), "status": status, "counts": {k: len(v) for k, v in fails.items()},
            "fails": fails, "ic_unresolved": unresolved, "cap_rows": [{**x, "d_mm": None if math.isinf(x["d_mm"])
                                                                        else round(x["d_mm"], 3)} for x in rows],
            "ic_rows": ic_rows, "info": info,
            "constants": {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float))}}


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    jout = a[a.index("--json") + 1] if "--json" in a else None
    pos = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--json")]
    pcb = Path(pos[0]) if pos else K.MAIN_PCB
    try:
        import design
        LB = LQ.Board(pcb)                       # one load: KiCad 10 may hand back a dead object on a second LoadBoard
        res = check(LB.b, design.D, LB=LB)
    except Exception as e:                       # fail closed
        import traceback
        traceback.print_exc()
        print(f"qa_decoupling ERROR: {e!r}")
        return 2
    if jout:
        Path(jout).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    i = res["info"]
    print(f"qa_decoupling {res['status']}  {pcb}  ({i['bypass_caps']} bypass caps, {i['ic_power_pins']} IC power pins "
          f"of which {i['ic_power_pins_covered']} covered by qa_power_layout.DECAP; limits: DECAP {PL.MAX_MM} mm, "
          f"bypass {i['limit_mm']} mm, bulk {i['bulk_limit_mm']} mm)")
    for k in CLASSES:
        items = res["fails"][k]
        print(f"  {k:10s} {'FAIL' if items else 'ok':4s} {len(items)}")
        for it in items[:60]:
            print("     ", json.dumps(it, default=str)[:240])
    for r, u in i["serving_decap"]:
        print(f"  serving decap {r} directly under its load {u} (qa_layout_quality.serving_decap): ok")
    if res["ic_unresolved"]:
        print(f"  ERROR: pin types unresolved for {res['ic_unresolved']} (no symbol in the schematic or the library)")
        return 2
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
