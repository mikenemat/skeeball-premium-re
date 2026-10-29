# ported from din8r-chassis-thermal/scripts/qa_placement.py, 2026-10-26 (SBC-1: board_const for CT layout_const, project facts adapted)
# Origin: DIN-8R scripts/qa_placement.py (C:/work/din-relay-8ch), adapted for CT (din8r-chassis-thermal MAIN).
"""Pre-route placement gate: the placement defect classes DIN-8R's independent review of its MAIN M4 draft found while
every gate passed (DIN-8R docs/records/review-M4/REPORT.md B1, B2, M1-M6, m2, m8). DIN-8R owner 2026-10-05: every new
class of finding becomes an automated check. Run it on every placement pass, before every placement hand-back and
before routing starts. Companion of qa_copper_landing / qa_layout_quality (same CLI, JSON, exit codes, require() /
counts()); it reuses qa_layout_quality's Board geometry and part classes (imported, never copied).

CT adaptation (2026-10-17): one board kind "main" (4 layers, 37 x 120 mm, double-sided placement owner-approved).
  - VIA-SITE: CT has no .kicad_dru (its absence is handled: no custom rules); a pad's via is its netclass via from the
    .kicad_pro (Default / Rail 0.6 / 0.3, Power 0.8 / 0.4: KiCad's via for that class, the conservative size for the
    power nets), floored at the board minimums (min via 0.6, drill 0.3, annulus 0.15); a .kicad_dru via rule would
    override as on the parent. Clearances: netclass (all 0.15 today), floored at the board minimum. FIXED pours are
    selected by ZONE NAME (FIXED_POUR_ZONE_RE: the HW-ADVQA2 ECO's hand-scripted flyback power-cell zones ECO_*), not
    by the parent's COM / OUT force-net names (CT has no force copper).
  - DIFFPAIR-PLACE: qa_layout_quality.DIFF_PAIRS["main"] (Ethernet MDI / PHY / ETH, USB_DP / USB_DN).
  - FIDUCIAL-SPREAD: CT carries no fiducials today; every side with a fine-pitch part FAILs until they are placed.
  - EP-VIA-PATTERN: identical-cell rule kept as the mechanism; CT has no repeated EP cell today (U1 / U7 are single).
  - PROT-GND: PROT_RE covers CT's D3 SMAJ58A (VSS pad), D7 SMAJ15A (GND pad), U8 USBLC6-2SC6 (GND pin 2); the
    exception table is EMPTY (no documented exceptions on CT).
  - UNDERSAT: CT's transformers (T1 Ethernet magnetics, T2 flyback) count as big parts too; no accepted satellites.
  Dropped parent-only items: FIXED_POUR_RE (COM / OUT force pours), the UI PROT_GND_EXEMPT U6.3 entry, the UI
  UNDERSAT_ACCEPT ZIF entries, the MAIN ISLAND_HIZ DRU in-pad escape wording (the mechanism stays: it only acts when a
  .kicad_dru 'disallow via' area exists, none on CT).

Every check FAILs on its own, except UNDERSAT (WARN level: reported, never gates). No waivers.
  VIA-SITE         Every pad that will need a via has >= VIA_SITE_MIN legal through-via sites (0.1 mm grid points) whose
                   centre lies within VIA_SITE_REACH_MM of the pad edge (the fan-out stub). A pad needs a via when it is
                   not landed yet (no same-net track / via touches it) and either (a) its net has an inner-layer plane
                   (CT: GND and PRTN on In1.Cu) and no own-net fill touches the pad on its outer layer, or (b) its net's
                   airwire (minimum spanning tree between the net's copper clusters, as the review's ratsnest) joins it
                   to a pad on the other face. Plated-hole pads are out of scope, and so is a pad of a pour net without
                   an inner plane (qa_copper_landing POUR_NETS: VSS and the flyback-cell nets VPP / +12V / SW_PRI /
                   PD_CS_RAW / SW_SEC / CLAMP) where its own net's fill touches it on its layer; CT's cell pours cover only
                   the power cell, so elsewhere such a pad is a routed pad under rule (b) (the parent skipped pour nets
                   whole: its pour nets were board-wide floods). A site is legal when the via disc keeps
                     - its own pad (and every same-net pad) >= VIA_SITE_OWN_GAP_MM away (mask dam), or the disc
                       wholly inside the pad itself (a via-in-pad: qa_layout_quality VIA-INPAD rule, >= VIP_MARGIN_MM
                       inside, never in an 0402: epoxy-filled + capped vias, 0603 and up; counted at the pad centre and
                       on the half-step grid; info via_site_pads_with_vip_site);
                     - the clearance of the pad's net to every other net's pad, track, via and FIXED pour on every
                       layer: the last matching .kicad_dru clearance rule (both item orders, its layer clause honoured),
                       else the larger netclass clearance from the .kicad_pro, floored at the board minimum clearance;
                     - the board hole-to-hole minimum to every drill (vias, PTH, NPTH) and the hole clearance to every
                       other net's / unplated drill;
                     - out of every rule area that forbids vias (board and footprint: CT ISOLATION_BARRIER_PRI_SEC,
                       EDGE_KEEPOUT ...), out of every area a .kicad_dru 'disallow via' rule names for this net, and the
                       copper-to-edge clearance inside the board outline.
                   FIXED pours are the zones FIXED_POUR_ZONE_RE names (CT: the ECO_* flyback power-cell copper); every
                   other fill (the GND / PRTN planes and pours, VSS) yields to a new via and is no obstacle. Where a
                   .kicad_dru 'disallow via' area of the pad's net lies within reach, one legal via-in-pad site is the
                   escape and passes (info via_site_dru_vip_escape; no such area on CT). A decoupling cap's ground pad
                   (qa_layout_quality DECAP-LOOP pairing) also needs a legal site whose edge gap to the pad is <=
                   VIA_SITE_DECAP_GAP_MM. Rasterised (a fixed 0.1 mm grid per pad), vectorised (shapely 2 ufuncs over the
                   grid) and STRtree-indexed.
  DIFFPAIR-PLACE   The passives of a declared P / N pair (qa_layout_quality.DIFF_PAIRS): every two-terminal R / C / L /
                   FB on one leg has a counterpart on the other leg (same value and footprint, other net equal or the
                   pair mate), and the two are on the same face, in the same orientation (pad-to-pad axis, mod 180), at
                   mirror positions about the pair axis (the perpendicular bisector of the nearest anchor part's P and N
                   pins) within DIFF_MIRROR_MM, with a pin-distance difference (passive pad to its anchor pin) <=
                   DIFF_PINDIST_MM, and neither part's pads inside the other leg's pin-axis corridor (DIFF_EXIT_MM
                   straight out of the anchor pin along its long axis, plus the straight run from the anchor pin to the
                   passive pad; half-width = class track width / 2 + class clearance).
  FIDUCIAL-SPREAD  Per side carrying a part of pad pitch <= qa_layout_quality.FINE_PITCH_MM: >= FID_MIN fiducials, and
                   their convex hull grown by FID_MARGIN_MM contains every such part's pads.
  EP-VIA-PATTERN   Vias in an IC exposed pad (an IC's largest own-side pad >= qa_layout_quality.EP_MIN_MM2): every via
                   whose disc touches the EP lies inside it with >= EP_MARGIN_MM of EP copper around its disc, is of the
                   EP's net, and keeps >= EP_PITCH_MM centre pitch to the other EP vias; ICs of the same footprint and
                   value (the same cell role) carry the identical pattern (EP-local via offsets within
                   EP_PATTERN_TOL_MM): one finding per cell role whose members differ, naming the members off the
                   majority pattern (all of them when no pattern has a majority).
  PROT-GND         The ground pad of a TVS / ESD part (PROT_RE on its value; ground = qa_layout_quality.GROUND_RE: GND /
                   PRTN / VSS) has >= PROT_MIN_VIAS same-net vias within PROT_VIA_MM of its edge, or a connection to
                   its own net's pour (qa_layout_quality pad_connection: solid, or thermal spokes reaching it).
                   PROT_GND_EXEMPT (per board and pad, documented) lowers that pad's need to PROT_EXEMPT_MIN_VIAS;
                   empty on CT.
  XSTACK-IC        Two ICs (U) on opposite faces whose pin fields (convex hull of their numbered pads) overlap by >=
                   XSTACK_IC_MIN_MM2. Pairs qa_layout_quality XSTACK already FAILs (pads closer than XSTACK_GAP_MM) are
                   not repeated here: they are listed in info xstack_ic_covered_by_XSTACK; this check reports the
                   interleaved stacks XSTACK cannot see.
  UNDERSAT (WARN)  A satellite (R / C / D / FB / L / U / Q) whose courtyard lies >= UNDERSAT_FRAC under the courtyard of
                   an opposite-face SMD IC / crystal / connector / transistor / transformer (plated-hole parts
                   excluded) with which it shares no net but ground: a back-side satellite under the wrong part.
                   UNDERSAT_ACCEPT (owner-accepted satellites, reported in info) is empty on CT.

KiCad Python: py scripts/local_run.py qa_placement.py BOARD [--json OUT] [--checks A,B]. Exit 0 PASS (warnings
allowed), 1 FAIL, 2 error (fail closed). require(board, out_json) raises on any FAIL; counts(board) returns per-check
counts.
"""
import argparse
import fnmatch
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board_const as K  # noqa: E402,F401  (first: tools/pylib shapely + numpy for KiCad's Python)
import numpy as np  # noqa: E402
import pcbnew  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

import qa_copper_landing as QL  # noqa: E402
import qa_layout_quality as LQ  # noqa: E402

# ------------------------------------------------------------------------------------------------ named constants
VIA_SITE_REACH_MM = 1.5          # VIA-SITE: via centre within this of the pad edge (the fan-out stub length)
VIA_SITE_MIN = 3                 # VIA-SITE: legal grid sites needed
VIA_SITE_GRID_MM = 0.1           # VIA-SITE: site grid (fixed, board-aligned)
VIA_SITE_OWN_GAP_MM = QL.PADEDGE_GAP_MM   # VIA-SITE: via disc to its own / same-net pad edge (one source: VIA-PADGAP)
VIA_SITE_DECAP_GAP_MM = 0.5      # VIA-SITE: a decap ground pad needs a legal site this close (disc edge to pad edge)
# VIA-SITE: zones (by NAME) that never yield to a foreign via. CT: the HW-ADVQA2 ECO's hand-scripted flyback power-cell
# copper (scripts/eco_advqa2.py ZONES: ECO_SWPRI_F / ECO_CSRAW_F / ECO_PRTN_F / ECO_VPP_F / ECO_CLAMP_B / ECO_VPP_B /
# ECO_SWSEC_F / ECO_12V_F / ECO_12V_B; TI TPS23751EVM SLVU754A 7.2-7.3). Their shapes ARE the design: the hot-loop area
# qa_power_layout LOOP gates and the D6 heat-spreading copper DIODECU gates; a foreign via punched into them cuts the
# designed loop / spreader (and drops a foreign potential into the SW_PRI / SW_SEC dv/dt nodes), so a site there is not
# legal. The base floods (GND_SEC_* / PRTN_PRI_* / VSS_PRI_F / VSS_PAD_B) yield like the parent's ordinary pours.
FIXED_POUR_ZONE_RE = re.compile(r"^ECO_")
DIFF_MIRROR_MM = 1.5             # DIFFPAIR-PLACE: mirror-position tolerance
DIFF_PINDIST_MM = 1.0            # DIFFPAIR-PLACE: |pin distance P - pin distance N|
DIFF_EXIT_MM = 1.0               # DIFFPAIR-PLACE: pin-axis corridor length out of the anchor pin
DIFF_ORIENT_TOL_DEG = 1.0        # DIFFPAIR-PLACE: orientation equality (mod 180)
# DIFFPAIR-PLACE: extra P / N net mates for the counterpart match only (a passive's far net equals its mate's far net or
# is its P / N mate). CT: USB_C_DP / USB_C_DN, the receptacle side of the USB pair behind R89 / R90 (22 R) and the U8
# flow-through ESD. qa_layout_quality does not declare them a routed pair (J8's duplicated A6 / B6, A7 / B7 stubs), so
# without this mate R90 is not recognised as R89's counterpart and the symmetry checks never run on the USB 22 R pair.
DIFF_PLACE_MATES = {"main": [("USB_C_DP", "USB_C_DN")]}
FID_MIN = 3                      # FIDUCIAL-SPREAD: fiducials per side with fine-pitch parts
FID_MARGIN_MM = 5.0              # FIDUCIAL-SPREAD: hull growth
EP_MARGIN_MM = 0.15              # EP-VIA-PATTERN: EP copper around each via disc
EP_PITCH_MM = 0.9                # EP-VIA-PATTERN: minimum via centre pitch
EP_PATTERN_TOL_MM = 0.05         # EP-VIA-PATTERN: identical-pattern tolerance (EP-local offsets)
PROT_VIA_MM = 1.0                # PROT-GND: via disc within this of the ground pad edge
PROT_MIN_VIAS = 2                # PROT-GND
# PROT-GND: TVS / ESD families by value (CT: SMAJ58A D3, SMAJ15A D7, USBLC6-2SC6 U8; the parent's list kept whole so a
# swapped protection part of another family is still recognised)
PROT_RE = re.compile(r"^(SMAJ|SMBJ|SMCJ|SMLJ|SMF\d|P4SM|P6SM|P6KE|1\.5KE|1\.5SMC|TPSM[ABC]|PESD|ESD|TVS|USBLC|TPD\d|"
                     r"SP0\d|SP3\d|PRTR|RCLAMP|SRV05|SM712|NUP\d|CDSOT)", re.I)
# PROT-GND documented exceptions per board {kind: {"REF.PAD": reason}}: that pad needs PROT_EXEMPT_MIN_VIAS instead of
# PROT_MIN_VIAS (reported in info prot_exempt); a listed pad with fewer still FAILs. CT: none (the mechanism is kept).
PROT_EXEMPT_MIN_VIAS = 1
PROT_GND_EXEMPT = {"main": {}}
XSTACK_IC_MIN_MM2 = 0.5          # XSTACK-IC: pin-field overlap area
UNDERSAT_FRAC = 0.30             # UNDERSAT: share of the satellite's courtyard under the other part
UNDERSAT_SAT_RE = re.compile(r"^(R|C|D|FB|L|U|Q)\d")
# UNDERSAT big parts: the parent's ICs / crystals / oscillators / connectors / transistors, plus CT's SMD transformers
# (T1 B1608S Ethernet magnetics, T2 PA2467NL flyback: big bodies a satellite can hide under; the parent had none)
UNDERSAT_BIG_RE = re.compile(r"^(U|X|Y|J|Q|T)\d")
# UNDERSAT owner-accepted satellites per board {kind: {ref: reason}}: reported in info undersat_accepted, not WARNed.
# CT: none (the mechanism is kept).
UNDERSAT_ACCEPT = {"main": {}}

CHECKS = ("VIA-SITE", "DIFFPAIR-PLACE", "FIDUCIAL-SPREAD", "EP-VIA-PATTERN", "PROT-GND", "XSTACK-IC", "UNDERSAT")
WARN = {"UNDERSAT"}
mm = pcbnew.ToMM
P, r3 = QL.P, LQ.r3
F_Cu, B_Cu = pcbnew.F_Cu, pcbnew.B_Cu


# ======================================================================================================== rules
def _sexpr(text):
    """minimal s-expression reader for .kicad_dru (strings, atoms, nested lists; '#' line comments)"""
    text = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    tok = re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"]+', text)
    stack, cur = [], []
    for t in tok:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return cur


def _num(v):
    m = re.match(r"^\s*([-\d.]+)\s*(mm|mil|in)?\s*$", str(v))
    if not m:
        raise ValueError(f"bad DRU value {v!r}")
    return float(m.group(1)) * {"mm": 1.0, None: 1.0, "mil": 0.0254, "in": 25.4}[m.group(2)]


class AreaPredicate(Exception):
    """a condition needs an area test the caller did not provide"""


class Item:
    """one side of a DRU condition (A or B)"""

    def __init__(self, rules, typ, net, layer=None, fp=None, areas=None):
        self._r, self.Type, self.NetName, self.Net = rules, typ, net, net
        self._cls = rules.classes_of(net)
        self.NetClass = self._cls[0] if self._cls else "Default"
        self.Layer, self._fp, self._areas = layer, fp, areas

    def hasNetclass(self, name):
        return name in self._cls

    def memberOfFootprint(self, ref):
        return bool(self._fp) and fnmatch.fnmatchcase(self._fp, ref)

    def _area(self, name):
        if self._areas is None:
            raise AreaPredicate(name)
        return self._areas(name)

    def intersectsArea(self, name):
        return self._area(name)

    def enclosedByArea(self, name):
        return self._area(name)

    insideArea = intersectsArea


class Rules:
    """the board's own clearance / via rules: .kicad_pro net classes + board minimums, .kicad_dru custom rules"""

    def __init__(self, pcb_path, board):
        p = Path(pcb_path)
        pro = p.with_suffix(".kicad_pro")
        js = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {}
        ns = js.get("net_settings", {})
        self.classes = {c["name"]: c for c in ns.get("classes", [])} or {
            "Default": {"name": "Default", "clearance": 0.2, "via_diameter": 0.6, "via_drill": 0.3}}
        self.assign = {k: (v if isinstance(v, list) else [v]) for k, v in (ns.get("netclass_assignments") or {}).items()}
        self.patterns = [(x.get("pattern", ""), x.get("netclass", "Default")) for x in ns.get("netclass_patterns") or []]
        r = js.get("board", {}).get("design_settings", {}).get("rules", {})
        ds = board.GetDesignSettings()

        def pick(key, attr, dflt):
            if key in r:
                return float(r[key])
            try:
                return mm(getattr(ds, attr))
            except Exception:                                    # noqa: BLE001
                return dflt
        self.min_clearance = pick("min_clearance", "m_MinClearance", 0.0)
        self.hole_to_hole = pick("min_hole_to_hole", "m_HoleToHoleMin", 0.25)
        self.hole_clearance = pick("min_hole_clearance", "m_HoleClearance", 0.25)
        self.edge_clearance = pick("min_copper_edge_clearance", "m_CopperEdgeClearance", 0.3)
        self.min_via_d = pick("min_via_diameter", "m_ViasMinSize", 0.45)
        self.min_drill = pick("min_through_hole_diameter", "m_MinThroughDrill", 0.2)
        self.min_annulus = pick("min_via_annular_width", "m_ViasMinAnnularWidth", 0.1)
        self.dru = []
        dru = p.with_suffix(".kicad_dru")
        self.unparsed = []
        if dru.exists():
            for node in _sexpr(dru.read_text(encoding="utf-8")):
                if not isinstance(node, list) or not node or node[0] != "rule":
                    continue
                rule = {"name": node[1], "cond": None, "layer": None, "cons": []}
                for x in node[2:]:
                    if not isinstance(x, list) or not x:
                        continue
                    if x[0] == "condition":
                        rule["cond"] = x[1]
                    elif x[0] == "layer":
                        rule["layer"] = x[1]
                    elif x[0] == "constraint":
                        kind = x[1]
                        if kind == "disallow":
                            rule["cons"].append(("disallow", set(x[2:])))
                            continue
                        val = next((_num(y[1]) for y in x[2:] if isinstance(y, list) and y[0] in ("min", "opt")),
                                   None)
                        rule["cons"].append((kind, val))
                src = rule["cond"] or "True"
                py = re.sub(r"&&", " and ", src)
                py = re.sub(r"\|\|", " or ", py)
                py = re.sub(r"!(?!=)", " not ", py)
                try:
                    rule["code"] = compile(py, rule["name"], "eval")
                except SyntaxError:
                    self.unparsed.append(rule["name"])
                    continue
                rule["areas"] = set(re.findall(r"(?:intersectsArea|enclosedByArea|insideArea)\('([^']+)'\)", src))
                self.dru.append(rule)
        # names a condition can test: only these enter the cache keys
        conds = " ".join(r["cond"] or "" for r in self.dru)
        self.named_nets = set(re.findall(r"NetName\s*==\s*'([^']+)'", conds))
        self.named_fps = re.findall(r"memberOfFootprint\('([^']+)'\)", conds)
        self.uses_layer = "Layer" in conds
        self._ccache, self._vcache = {}, {}
        self.max_clearance = max([self.min_clearance] + [c.get("clearance") or 0 for c in self.classes.values()]
                                 + [v for r in self.dru for k, v in r["cons"] if k == "clearance" and v])

    def classes_of(self, net):
        if net in self.assign:
            return list(self.assign[net])
        out = [c for pat, c in self.patterns if pat and fnmatch.fnmatchcase(net or "", pat)]
        return out or ["Default"]

    def _eff(self, net, key):
        cls = [self.classes[c] for c in self.classes_of(net) if c in self.classes and self.classes[c].get(key) is not None]
        if not cls:
            return self.classes.get("Default", {}).get(key)
        return min(cls, key=lambda c: c.get("priority", 1 << 31))[key]

    @staticmethod
    def _layer_ok(rule, lname):
        sel = rule["layer"]
        if sel is None or lname is None:
            return True
        if sel == "outer":
            return lname in ("F.Cu", "B.Cu")
        if sel == "inner":
            return lname not in ("F.Cu", "B.Cu")
        return sel == lname

    def _match(self, rule, a, b):
        try:
            return bool(eval(rule["code"], {"__builtins__": {}}, {"A": a, "B": b}))
        except AreaPredicate:
            return False
        except Exception:                                        # noqa: BLE001 - an unknown function: not matched
            if rule["name"] not in self.unparsed:
                self.unparsed.append(rule["name"])
            return False

    def _fpkey(self, fp):
        return fp if fp and any(fnmatch.fnmatchcase(fp, x) for x in self.named_fps) else None

    def clearance(self, net_a, type_a, net_b, type_b, lname, fp_b=None):
        """copper clearance between an item of net_a (no footprint, e.g. a new via) and one of net_b on layer lname"""
        key = (net_a if net_a in self.named_nets else tuple(self.classes_of(net_a)), net_a == net_b, type_a,
               net_b if net_b in self.named_nets else tuple(self.classes_of(net_b)), type_b,
               self._fpkey(fp_b), lname if self.uses_layer or any(r["layer"] for r in self.dru) else None)
        if key in self._ccache:
            return self._ccache[key]
        a = Item(self, type_a, net_a, lname)
        b = Item(self, type_b, net_b, lname, fp_b)
        custom = None
        for rule in self.dru:
            if not self._layer_ok(rule, lname):
                continue
            vals = [v for k, v in rule["cons"] if k == "clearance" and v is not None]
            if vals and (self._match(rule, a, b) or self._match(rule, b, a)):
                custom = vals[-1]                                # the last matching rule wins (KiCad precedence)
        c = custom if custom is not None else max(self._eff(net_a, "clearance") or 0, self._eff(net_b, "clearance") or 0)
        c = max(c, self.min_clearance)
        self._ccache[key] = c
        return c

    def via_size(self, net):
        """(diameter, drill) of the via a fan-out of net gets. CT (no .kicad_dru): the net's netclass via from the
        .kicad_pro (Default / Rail 0.6 / 0.3, Power 0.8 / 0.4), floored at the board minimums (diameter, drill,
        drill + 2 x annulus). The parent read only the board minimums because its DRU set every via size; a matching
        DRU via_diameter / hole_size / annular_width rule still overrides here (area-conditioned rules are not assumed
        to apply)"""
        if net in self._vcache:
            return self._vcache[net]
        a = Item(self, "Via", net)
        d = max(self.min_via_d, float(self._eff(net, "via_diameter") or 0.0))
        h = max(self.min_drill, float(self._eff(net, "via_drill") or 0.0))
        ann = self.min_annulus
        for rule in self.dru:
            if not any(k in ("via_diameter", "hole_size", "annular_width") for k, _ in rule["cons"]):
                continue
            if not self._match(rule, a, a):
                continue
            for k, v in rule["cons"]:
                if v is None:
                    continue
                if k == "via_diameter":
                    d = v
                elif k == "hole_size":
                    h = v
                elif k == "annular_width":
                    ann = v
        out = (round(max(d, h + 2 * ann), 4), round(h, 4))
        self._vcache[net] = out
        return out

    def via_disallow_areas(self, net):
        """names of rule areas a 'disallow via' DRU rule keeps this net's vias out of (monotone in the area tests)"""
        out = set()
        for rule in self.dru:
            dis = [v for k, v in rule["cons"] if k == "disallow"]
            if not dis or not any("via" in s for s in dis) or not rule["areas"]:
                continue
            on = Item(self, "Via", net, areas=lambda n: True)
            off = Item(self, "Via", net, areas=lambda n: False)
            if self._match(rule, on, on) and not self._match(rule, off, off):
                out |= rule["areas"]
        return out


# ======================================================================================================== geometry
class Geo:
    """placement-gate geometry on top of qa_layout_quality.Board"""

    def __init__(self, B):
        self.B = B
        b = B.b
        self.rules = Rules(B.path, b)
        self.outline = LQ.board_outline(B)
        self.inner = [L for L in B.layers.values() if L not in B.outer]
        self.lname = B.lname
        # drill holes: (x, y, radius, net or None for NPTH, plated)
        self.holes = []
        for fp in b.GetFootprints():
            for p in fp.Pads():
                ds = p.GetDrillSize()
                if ds.x <= 0:
                    continue
                plated = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                self.holes.append((*P(p.GetPosition()), mm(min(ds.x, ds.y)) / 2,
                                   p.GetNetname() if plated else None, plated))
        for v in B.vias:
            self.holes.append((*v["pos"], v["drill"] / 2, v["net"], True))
        self.hole_xy = np.array([(h[0], h[1]) for h in self.holes]) if self.holes else np.zeros((0, 2))
        # rule areas: name -> outline; no-via outlines
        self.areas = defaultdict(list)
        self.novia = []
        zs = list(b.Zones()) + [z for fp in b.GetFootprints() for z in fp.Zones()]
        for z in zs:
            if not z.GetIsRuleArea():
                continue
            g = QL.to_shapely(z.Outline())
            if g.is_empty:
                continue
            self.areas[z.GetZoneName()].append(g)
            if z.GetDoNotAllowVias():
                self.novia.append((g, z.GetZoneName()))
        self.areas = {k: unary_union(v) for k, v in self.areas.items()}
        self.plane_nets = {n for n in B.zones if any(not B.fill(n, L)[0].is_empty for L in self.inner)}

    def obstacles(self):
        """[(geom, net, kind, layer name, fp ref, pad idx)] fixed copper for VIA-SITE, and its STRtree"""
        B = self.B
        if hasattr(self, "_obs"):
            return self._obs, self._otree
        obs = []
        for p in B.pads:
            for L, g in p["poly"].items():
                obs.append((g, p["net"], "Pad", self.lname(L), p["ref"], p["i"]))
        for t in B.tracks:
            obs.append((t["cu"], t["net"], "Track", self.lname(t["layer"]), None, None))
        for v in B.vias:
            obs.append((v["disc"], v["net"], "Via", None, None, None))
        self.fixed_zones = []
        for net, zs in B.zones.items():
            for z in zs:
                if not FIXED_POUR_ZONE_RE.match(z.GetZoneName() or ""):
                    continue
                self.fixed_zones.append(z.GetZoneName())
                for L in B.layers.values():
                    if not z.IsOnLayer(L):
                        continue
                    g = QL.to_shapely(z.GetFilledPolysList(L))
                    for piece in getattr(g, "geoms", [g]):
                        if not piece.is_empty:
                            obs.append((piece, net, "Zone", self.lname(L), None, None))
        self._obs, self._otree = obs, STRtree([o[0] for o in obs])
        return self._obs, self._otree


def edge_inner(G, r):
    k = ("edge", round(r, 4))
    if k not in G.__dict__.setdefault("_ecache", {}):
        g = G.outline.buffer(-(G.rules.edge_clearance + r)) if not G.outline.is_empty else Polygon()
        shapely.prepare(g)
        G._ecache[k] = g
    return G._ecache[k]


def airwire_partner_sides(B, skip=()):
    """{pad idx: set of partner faces 'F' / 'B' / 'T'} from an MST between each net's copper clusters (review
    ratsnest.py): clusters from KiCad connectivity over the existing copper, edges by minimum pad-pair distance. Nets in
    skip (planes, pours: VIA-SITE does not ask their airwires) are left out."""
    b = B.b
    b.BuildConnectivity()
    con = b.GetConnectivity()
    uid = {p["obj"].m_Uuid.AsString(): p["i"] for p in B.pads}
    by_net = defaultdict(list)
    for p in B.pads:
        if p["net"] and not p["net"].startswith("unconnected") and p["num"] and p["net"] not in skip:
            by_net[p["net"]].append(p)
    side = {}
    for p in B.pads:
        side[p["i"]] = "T" if p["obj"].GetDrillSize().x > 0 else ("F" if p["fp"]["side"] == F_Cu else "B")
    out = defaultdict(set)
    for net, ps in by_net.items():
        if len(ps) < 2:
            continue
        uf = QL.UF()
        for p in ps:
            uf.find(p["i"])
            for q in con.GetConnectedPads(p["obj"]):
                j = uid.get(q.m_Uuid.AsString())
                if j is not None:
                    uf.union(p["i"], j)
        cl = defaultdict(list)
        for p in ps:
            cl[uf.find(p["i"])].append(p)
        if len(cl) < 2:
            continue
        keys = list(cl)
        xy = {k: np.array([q["pos"] for q in cl[k]]) for k in keys}
        cand = []
        for a in range(len(keys)):
            for c in range(a + 1, len(keys)):
                A, C = xy[keys[a]], xy[keys[c]]
                d = np.hypot(A[:, None, 0] - C[None, :, 0], A[:, None, 1] - C[None, :, 1])
                i, j = np.unravel_index(np.argmin(d), d.shape)
                cand.append((float(d[i, j]), a, c, cl[keys[a]][i]["i"], cl[keys[c]][j]["i"]))
        cand.sort()
        up = list(range(len(keys)))

        def g(a):
            while up[a] != a:
                up[a] = up[up[a]]
                a = up[a]
            return a
        for d, a, c, i, j in cand:
            if g(a) != g(c):
                up[g(a)] = g(c)
                out[i].add(side[j])
                out[j].add(side[i])
    return out


def landed(B, p):
    L = p["fp"]["side"]
    poly = p["poly"].get(L)
    if poly is None:
        return True
    for i in B.t_tree.query(poly):
        t = B.tracks[i]
        if t["net"] == p["net"] and t["layer"] == L and t["cu"].intersects(poly):
            return True
    for i in B.v_tree.query(poly):
        v = B.vias[i]
        if v["net"] == p["net"] and v["disc"].intersects(poly):
            return True
    return False


def decap_ground_pads(B):
    """{pad idx} ground pads of decoupling caps (qa_layout_quality DECAP-LOOP pairing)"""
    loads = defaultdict(int)
    for p in B.pads:
        r = p["ref"]
        if r[:1] in ("U", "J", "L") or (r.startswith("D") and "LED" in p["fp"]["fpid"].upper()):
            loads[p["net"]] += 1
    out = set()
    for rec in B.fps.values():
        if rec["ref"][:1] != "C" or not rec["two_term"]:
            continue
        ps = rec["smd_pads"]
        sup = [p for p in ps if p["net"] and not LQ.GROUND_RE.match(p["net"])
               and (p["net"].startswith("+") or LQ.SUPPLY_RE.search(p["net"]))]
        gnd = [p for p in ps if LQ.GROUND_RE.match(p["net"] or "")]
        if len(sup) == 1 and len(gnd) == 1 and loads.get(sup[0]["net"]):
            out.add(gnd[0]["i"])
    return out


def _legal(G, net, X, Y, idx, r, rh, bounds, ext, nv, own=None):
    """the via-centre candidates idx (into X, Y) that are legal sites for a through via of net (radius r, drill
    radius rh): drill rules, no-via / DRU keep-outs, other nets' fixed copper (class-aware), same-net pads (own-pad
    gap; own="net": a via-in-pad candidate, whose same-net pads are its landing)"""
    R = G.rules
    obs, otree = G.obstacles()
    minx, miny, maxx, maxy = bounds
    # drills: hole-to-hole for every drill, hole clearance for other nets' / unplated drills
    if len(idx) and len(G.hole_xy):
        near = np.nonzero((np.abs(G.hole_xy[:, 0] - (minx + maxx) / 2) < (maxx - minx) / 2 + ext + 2)
                          & (np.abs(G.hole_xy[:, 1] - (miny + maxy) / 2) < (maxy - miny) / 2 + ext + 2))[0]
        for k in near:
            hx, hy, hr, hnet, plated = G.holes[k]
            dc = np.hypot(X[idx] - hx, Y[idx] - hy)
            bad = dc < rh + hr + R.hole_to_hole - 1e-9
            if hnet != net or not plated:
                bad |= dc < r + hr + R.hole_clearance - 1e-9
            idx = idx[~bad]
            if not len(idx):
                return idx
    # no-via rule areas and the DRU 'disallow via' areas of this net
    kg = nv[0]
    if len(idx) and not kg.is_empty:
        idx = idx[~shapely.intersects(kg, shapely.buffer(shapely.points(X[idx], Y[idx]), r, quad_segs=4))]
    if not len(idx):
        return idx
    m = R.max_clearance + r
    for k in otree.query(box(minx - ext - m, miny - ext - m, maxx + ext + m, maxy + ext + m)):
        g, onet, kind, olayer, ofp, opad = obs[k]
        if onet == net:
            if kind != "Pad" or own == "net":
                continue
            req = r + VIA_SITE_OWN_GAP_MM
        else:
            req = r + R.clearance(net, "Via", onet, kind, olayer, ofp)
        gx0, gy0, gx1, gy1 = g.bounds
        px0, px1 = X[idx].min(), X[idx].max()
        py0, py1 = Y[idx].min(), Y[idx].max()
        if gx0 - px1 > req or px0 - gx1 > req or gy0 - py1 > req or py0 - gy1 > req:
            continue
        if kind == "Zone":
            g = g.intersection(box(px0 - req, py0 - req, px1 + req, py1 + req))
            if g.is_empty:
                continue
        idx = idx[shapely.distance(g, shapely.points(X[idx], Y[idx])) >= req - 1e-9]
        if not len(idx):
            break
    return idx


def vip_sites(G, p, poly, r, rh, nv):
    """legal via-in-pad sites of pad p (CT orders epoxy-filled + capped vias, 0603 and up): the qa_layout_quality
    VIA-INPAD rule - the via disc wholly inside the pad with >= VIP_MARGIN_MM to spare, never in an 0402's pad
    (NO_VIP_FP_RE) - at the pad centre and on the fixed half-step grid inside the pad, each legal against keep-outs,
    drills and other nets' clearances (same-net pads are its landing, not obstacles). -> number of such sites"""
    if LQ.NO_VIP_FP_RE.search(p["fp"].get("fpid", "")):
        return 0
    inner = poly.buffer(-(r + LQ.VIP_MARGIN_MM) + 1e-3)
    if inner.is_empty:
        return 0
    step = VIA_SITE_GRID_MM / 2
    x0, y0, x1, y1 = inner.bounds
    xs = np.arange(math.ceil(x0 / step), math.floor(x1 / step) + 1) * step
    ys = np.arange(math.ceil(y0 / step), math.floor(y1 / step) + 1) * step
    X, Y = np.meshgrid(xs, ys) if len(xs) and len(ys) else (np.array([p["pos"][0]]), np.array([p["pos"][1]]))
    X, Y = np.append(X.ravel(), p["pos"][0]), np.append(Y.ravel(), p["pos"][1])
    idx = np.nonzero(shapely.contains_xy(inner, X, Y))[0]
    return len(_legal(G, p["net"], X, Y, idx, r, rh, poly.bounds, 0.0, nv, own="net"))


def dru_vip(G, p, L, poly, r, rh, nv):
    """the DRU-designed via-in-pad escape: the pad's net has a .kicad_dru 'disallow via' area within reach of the pad
    (the parent's ISLAND_HIZ keep-outs, pads cut out: 'no HIZ via (in-pad ok)'; CT has no .kicad_dru, so this never
    acts on CT today) and the pad has a legal via-in-pad site (vip_sites)"""
    if nv[1].is_empty or not nv[1].intersects(poly.buffer(VIA_SITE_REACH_MM)):
        return False
    return vip_sites(G, p, poly, r, rh, nv) > 0


# ======================================================================================================== checks
def chk_via_site(G, fails, info):
    B, R = G.B, G.rules
    t0 = time.time()
    G.obstacles()
    info["via_site_fixed_zones"] = sorted(set(G.fixed_zones))
    info["via_site_plane_nets"] = sorted(G.plane_nets)
    # CT: pour nets keep their airwires (POUR_NETS also holds the flyback-cell nets VPP / +12V / SW_PRI ..., whose
    # cell pours cover only the power cell); a pour-net pad is skipped below only where its own fill touches it
    partners = airwire_partner_sides(B, skip=G.plane_nets | B.force)
    decap_gnd = decap_ground_pads(B)
    novia_cache = {}

    def novia(net):
        if net not in novia_cache:
            names = R.via_disallow_areas(net)
            dru = [G.areas[n] for n in names if n in G.areas]
            kg = unary_union([g for g, _ in G.novia] + dru) if G.novia or dru else Polygon()
            shapely.prepare(kg)
            novia_cache[net] = (kg, unary_union(dru) if dru else Polygon())
        return novia_cache[net]
    reach, step = VIA_SITE_REACH_MM, VIA_SITE_GRID_MM
    need_n = defaultdict(int)
    tight, vip = [], []
    vip_n = 0
    for p in B.pads:
        net = p["net"]
        if not p["smd"] or not p["num"] or not net or net.startswith("unconnected"):
            continue
        L = p["fp"]["side"]
        poly = p["poly"].get(L)
        if poly is None:
            continue
        if net in G.plane_nets:
            g = B.fill(net, L)[0]
            if not g.is_empty and g.intersects(poly):
                continue
            need = "plane"
        elif net in B.force:
            continue
        else:
            if net in B.pour:                      # CT: landed by its own pour here -> out of scope, else a routed pad
                g = B.fill(net, L)[0]
                if not g.is_empty and g.intersects(poly):
                    continue
            other = "B" if L == F_Cu else "F"
            if other not in partners.get(p["i"], ()):
                continue
            need = "other-face partner"
        if landed(B, p):
            continue
        need_n[need] += 1
        d, h = R.via_size(net)
        r, rh = d / 2, h / 2
        minx, miny, maxx, maxy = poly.bounds
        ext = reach
        xs = np.arange(math.ceil((minx - ext) / step), math.floor((maxx + ext) / step) + 1) * step
        ys = np.arange(math.ceil((miny - ext) / step), math.floor((maxy + ext) / step) + 1) * step
        X, Y = np.meshgrid(xs, ys)
        X, Y = X.ravel(), Y.ravel()
        pts = shapely.points(X, Y)
        dpad = shapely.distance(poly, pts)
        keep = (dpad >= r + VIA_SITE_OWN_GAP_MM - 1e-9) & (dpad <= reach + 1e-9)
        keep &= shapely.contains_xy(edge_inner(G, r), X, Y)
        idx = _legal(G, net, X, Y, np.nonzero(keep)[0], r, rh, poly.bounds, ext, novia(net))
        nvip = vip_sites(G, p, poly, r, rh, novia(net))    # legal via-in-pad sites count too (filled + capped vias)
        vip_n += nvip > 0
        n = len(idx) + nvip
        gaps = dpad[idx] - r if len(idx) else np.array([])
        best = 0.0 if nvip else (float(gaps.min()) if len(idx) else None)
        rec = {"pad": B.pad_ref(p), "net": net, "side": "F" if L == F_Cu else "B", "at": r3(p["pos"]), "need": need,
               "via": [d, h], "sites": n, "vip_sites": nvip, "best_gap_mm": None if best is None else round(best, 3)}
        if len(idx):
            j = idx[int(np.argmin(gaps))]
            rec["best_site"] = r3((float(X[j]), float(Y[j])))
        if n < VIA_SITE_MIN and dru_vip(G, p, L, poly, r, rh, novia(net)):
            vip.append(rec["pad"])                      # the DRU's designed escape: a fitting via in the pad
        elif n < VIA_SITE_MIN:
            fails["VIA-SITE"].append({**rec, "what": f"{n} legal via site(s) within {reach} mm (need {VIA_SITE_MIN})"})
        elif p["i"] in decap_gnd and best > VIA_SITE_DECAP_GAP_MM + 1e-9:
            fails["VIA-SITE"].append({**rec, "what": f"decap ground pad: no legal site within "
                                                     f"{VIA_SITE_DECAP_GAP_MM} mm edge gap"})
        elif n <= 2 * VIA_SITE_MIN:
            tight.append(rec["pad"])
    zero =[x for x in fails["VIA-SITE"] if x["sites"] == 0]
    info["via_site_pads_needing_via"] = dict(need_n)
    info["via_site_zero"] = len(zero)
    info["via_site_below_min"] = sum(1 for x in fails["VIA-SITE"] if 0 < x["sites"] < VIA_SITE_MIN)
    info["via_site_decap_far"] = sum(1 for x in fails["VIA-SITE"] if x["sites"] >= VIA_SITE_MIN)
    info["via_site_tight"] = tight[:40]
    info["via_site_dru_vip_escape"] = vip
    info["via_site_pads_with_vip_site"] = vip_n
    info["via_site_s"] = round(time.time() - t0, 1)
    if R.unparsed:
        info["dru_rules_not_evaluated"] = sorted(set(R.unparsed))


def _passive(rec):
    return rec["two_term"] and (rec["ref"][:1] in ("R", "C", "L") or rec["ref"][:2] == "FB")


def _pad_on(rec, net):
    return next((p for p in rec["pads"] if p["net"] == net), None)


def _long_axis(poly):
    xs = list(poly.minimum_rotated_rectangle.exterior.coords)
    e1, e2 = (xs[0], xs[1]), (xs[1], xs[2])
    e = e1 if math.dist(*e1) >= math.dist(*e2) else e2
    return LQ.unit(*e), max(math.dist(*e1), math.dist(*e2))


def _axis_deg(rec):
    """a two-terminal part's pad-to-pad axis direction (deg, mod 180)"""
    a, c = rec["pads"][0]["pos"], rec["pads"][1]["pos"]
    return math.degrees(math.atan2(c[1] - a[1], c[0] - a[0])) % 180


def _reflect(q, m, u):
    """reflect point q across the line through m with direction u"""
    vx, vy = q[0] - m[0], q[1] - m[1]
    t = vx * u[0] + vy * u[1]
    px, py = m[0] + t * u[0], m[1] + t * u[1]
    return (2 * px - q[0], 2 * py - q[1])


def chk_diffpair_place(G, fails, info):
    B, R = G.B, G.rules
    pairs = LQ.DIFF_PAIRS.get(B.kind, [])
    mate = {}
    for pn, nn, _ in pairs:
        mate[pn], mate[nn] = nn, pn
    for pn, nn in DIFF_PLACE_MATES.get(B.kind, []):
        mate.setdefault(pn, nn)
        mate.setdefault(nn, pn)
    seen = set()
    n_pairs = 0
    for pn, nn, _ in pairs:
        legs = {net: [rec for rec in B.fps.values() if _passive(rec) and _pad_on(rec, net)
                      and not _pad_on(rec, mate[net])] for net in (pn, nn)}
        anchors = []
        for rec in B.fps.values():
            if rec["two_term"]:
                continue
            ps, ns = [p for p in rec["pads"] if p["net"] == pn], [p for p in rec["pads"] if p["net"] == nn]
            if ps and ns:
                a, c = min(((a, c) for a in ps for c in ns), key=lambda x: math.dist(x[0]["pos"], x[1]["pos"]))
                anchors.append((rec, a, c))
        used = set()
        for a in sorted(legs[pn], key=lambda r: r["ref"]):
            pa = _pad_on(a, pn)
            oa = next(p["net"] for p in a["pads"] if p is not pa)
            cands = [c for c in legs[nn] if c["ref"] not in used and c["value"] == a["value"] and c["fpid"] == a["fpid"]
                     and next(p["net"] for p in c["pads"] if p is not _pad_on(c, nn)) in (oa, mate.get(oa))]
            if not cands:
                if frozenset((a["ref"],)) not in seen:
                    fails["DIFFPAIR-PLACE"].append({"pair": [pn, nn], "parts": [a["ref"]], "at": P(a["obj"].GetPosition()),
                                                    "what": f"{a['ref']} on {pn} has no counterpart on {nn}"})
                    seen.add(frozenset((a["ref"],)))
                continue
            mid_a = P(a["obj"].GetPosition())
            b = min(cands, key=lambda c: math.dist(mid_a, P(c["obj"].GetPosition())))
            used.add(b["ref"])
            key = frozenset((a["ref"], b["ref"]))
            if key in seen:
                continue
            seen.add(key)
            n_pairs += 1
            pb = _pad_on(b, nn)
            ca, cb_ = P(a["obj"].GetPosition()), P(b["obj"].GetPosition())
            mid = ((ca[0] + cb_[0]) / 2, (ca[1] + cb_[1]) / 2)
            probs = []
            if a["side"] != b["side"]:
                probs.append(f"faces differ ({'F' if a['side'] == F_Cu else 'B'} / {'F' if b['side'] == F_Cu else 'B'})")
            ra, rb = _axis_deg(a), _axis_deg(b)                   # the pad-to-pad axis, mod 180
            dr = min(abs(ra - rb), 180 - abs(ra - rb))
            if dr > DIFF_ORIENT_TOL_DEG:
                probs.append(f"orientations differ (pad axes {ra:.0f} / {rb:.0f} deg)")
            rec = {"pair": [pn, nn], "parts": [a["ref"], b["ref"]], "at": r3(mid)}
            if anchors:
                arec, ap, an = min(anchors, key=lambda x: math.dist(mid, ((x[1]["pos"][0] + x[2]["pos"][0]) / 2,
                                                                         (x[1]["pos"][1] + x[2]["pos"][1]) / 2)))
                m = ((ap["pos"][0] + an["pos"][0]) / 2, (ap["pos"][1] + an["pos"][1]) / 2)
                v = LQ.unit(ap["pos"], an["pos"])
                u = (-v[1], v[0])                                 # the pair axis: perpendicular bisector of P / N pins
                mir = math.dist(_reflect(cb_, m, u), ca)
                rec["anchor"] = arec["ref"]
                rec["mirror_mm"] = round(mir, 2)
                if mir > DIFF_MIRROR_MM:
                    probs.append(f"not mirrored about the {arec['ref']} pair axis ({mir:.2f} mm > {DIFF_MIRROR_MM})")
                dpa, dpb = math.dist(pa["pos"], ap["pos"]), math.dist(pb["pos"], an["pos"])
                rec["pin_mm"] = [round(dpa, 2), round(dpb, 2)]
                if abs(dpa - dpb) > DIFF_PINDIST_MM:
                    probs.append(f"pin distance {dpa:.2f} / {dpb:.2f} mm (difference > {DIFF_PINDIST_MM})")
                for leg, other, pin, lp in ((a, b, ap, pa), (b, a, an, pb)):
                    L = arec["side"]
                    cor = []
                    pin_poly = pin["poly"].get(L)
                    if pin_poly is not None:
                        ux, half = _long_axis(pin_poly)
                        cen = P(arec["obj"].GetPosition())
                        if (pin["pos"][0] - cen[0]) * ux[0] + (pin["pos"][1] - cen[1]) * ux[1] < 0:
                            ux = (-ux[0], -ux[1])
                        s = (pin["pos"][0] + ux[0] * half / 2, pin["pos"][1] + ux[1] * half / 2)
                        cor.append(LineString([s, (s[0] + ux[0] * DIFF_EXIT_MM, s[1] + ux[1] * DIFF_EXIT_MM)]))
                    if leg["side"] == L:
                        cor.append(LineString([pin["pos"], lp["pos"]]))
                    cname = R.classes_of(pin["net"])[0]
                    w = (B.cls_w.get(cname) or B.cls_w.get("Default") or 0.2)
                    hw = w / 2 + R.clearance(pin["net"], "Track", "", "Track", B.lname(L))
                    corr = unary_union([c.buffer(hw, cap_style=2) for c in cor]) if cor else Polygon()
                    hit = [B.pad_ref(q) for q in other["pads"] if q["net"] != pin["net"] and L in q["poly"]
                           and q["poly"][L].intersects(corr)]
                    if hit:
                        probs.append(f"{other['ref']} blocks {B.pad_ref(pin)}'s pin axis ({', '.join(hit)})")
            else:
                info.setdefault("diffpair_no_anchor", []).append([pn, nn])
            if probs:
                fails["DIFFPAIR-PLACE"].append({**rec, "problems": probs})
    info["diffpair_passive_pairs"] = n_pairs


def _fiducials(B, side):
    return [rec for rec in B.fps.values() if rec["side"] == side
            and ("fiducial" in rec["fpid"].lower() or rec["ref"].startswith("FID"))]


def chk_fiducial_spread(G, fails, info):
    B = G.B
    for side, name in ((F_Cu, "F"), (B_Cu, "B")):
        fine = [rec for rec in B.fps.values() if rec["side"] == side and rec["fine"]]
        if not fine:
            continue
        fid = [P(rec["obj"].GetPosition()) for rec in _fiducials(B, side)]
        if len(fid) < FID_MIN:
            fails["FIDUCIAL-SPREAD"].append({"side": name, "fiducials": len(fid), "fine_pitch_parts": len(fine),
                                             "parts": sorted(r["ref"] for r in fine),
                                             "what": f"{len(fid)} fiducial(s) on a side with fine-pitch parts "
                                                     f"(need {FID_MIN})"})
            continue
        hull = MultiPoint(fid).convex_hull.buffer(FID_MARGIN_MM)
        out = []
        for rec in sorted(fine, key=lambda r: r["ref"]):
            g = unary_union([p["poly"][side] for p in rec["pads"] if side in p["poly"]])
            if not hull.contains(g):
                out.append((rec["ref"], round(g.difference(hull).area, 2),
                            round(max(hull.exterior.distance(Point(c)) for c in g.convex_hull.exterior.coords
                                      if not hull.contains(Point(c))) if not g.is_empty else 0.0, 1)))
        if out:
            fails["FIDUCIAL-SPREAD"].append({"side": name, "fiducials": [r3(q) for q in fid], "outside": len(out),
                                             "parts": [x[0] for x in out], "worst_mm": max(x[2] for x in out),
                                             "what": f"{len(out)} fine-pitch part(s) outside the fiducial hull + "
                                                     f"{FID_MARGIN_MM} mm"})


def _ep(rec):
    own = [p for p in rec["smd_pads"] if rec["side"] in p["poly"]]
    if rec["ref"][:1] != "U" or len(own) < 3:
        return None
    ep = max(own, key=lambda p: p["area"])
    return ep if ep["area"] >= LQ.EP_MIN_MM2 else None


def chk_ep_via_pattern(G, fails, info):
    B = G.B
    groups = defaultdict(list)
    n = 0
    for rec in B.fps.values():
        ep = _ep(rec)
        if ep is None:
            continue
        L = rec["side"]
        poly = ep["poly"][L]
        vias = [B.vias[i] for i in B.v_tree.query(poly) if B.vias[i]["disc"].intersects(poly)]
        if not vias:
            groups[(rec["fpid"], rec["value"])].append((rec, ()))
            continue
        n += 1
        probs = []
        inner = poly.buffer(-EP_MARGIN_MM)
        bad_m = [r3(v["pos"]) for v in vias if not inner.contains(v["disc"])]
        if bad_m:
            probs.append(f"{len(bad_m)} via(s) with < {EP_MARGIN_MM} mm EP copper around the disc: {bad_m[:6]}")
        foreign = [r3(v["pos"]) for v in vias if v["net"] != ep["net"]]
        if foreign:
            probs.append(f"{len(foreign)} foreign-net via(s) in the EP: {foreign[:6]}")
        pit = min((math.dist(a["pos"], c["pos"]) for i, a in enumerate(vias) for c in vias[i + 1:]), default=None)
        if pit is not None and pit < EP_PITCH_MM - 1e-6:
            probs.append(f"via pitch {pit:.2f} mm < {EP_PITCH_MM}")
        if probs:
            fails["EP-VIA-PATTERN"].append({"part": rec["ref"], "pad": B.pad_ref(ep), "at": r3(ep["pos"]),
                                            "vias": len(vias), "problems": probs})
        # EP-local pattern (footprint frame: undo rotation and the back-side mirror)
        th = math.radians(rec["obj"].GetOrientationDegrees())
        loc = []
        for v in vias:
            dx, dy = v["pos"][0] - ep["pos"][0], v["pos"][1] - ep["pos"][1]
            x, y = dx * math.cos(th) - dy * math.sin(th), dx * math.sin(th) + dy * math.cos(th)
            if L == B_Cu:
                x = -x
            loc.append((round(x / EP_PATTERN_TOL_MM) * EP_PATTERN_TOL_MM, round(y / EP_PATTERN_TOL_MM) * EP_PATTERN_TOL_MM))
        groups[(rec["fpid"], rec["value"])].append((rec, tuple(sorted((round(a, 3), round(b, 3)) for a, b in loc))))
    for (fpid, value), members in sorted(groups.items()):
        if len(members) < 2:
            continue
        pats = defaultdict(list)
        for rec, pat in members:
            pats[pat].append(rec["ref"])
        if len(pats) < 2:
            continue
        top = max(len(v) for v in pats.values())
        major = [k for k, v in pats.items() if len(v) == top]
        off = sorted(r for k, v in pats.items() for r in v if len(major) > 1 or k != major[0])
        fails["EP-VIA-PATTERN"].append({"cell_role": [fpid, value], "parts": {r: len(k) for k, v in pats.items() for r in v},
                                        "off_pattern": off,
                                        "majority": None if len(major) > 1 else sorted(pats[major[0]]),
                                        "what": "identical cells carry different EP via patterns" + (
                                            " (no majority pattern)" if len(major) > 1 else "")})
    info["ep_ics_with_vias"] = n


def chk_prot_gnd(G, fails, info):
    B = G.B
    seen = []
    for rec in B.fps.values():
        if rec["ref"][:1] not in ("D", "U") or not PROT_RE.match(rec["value"] or ""):
            continue
        gp = [p for p in rec["pads"] if p["net"] and LQ.GROUND_RE.match(p["net"]) and rec["side"] in p["poly"]]
        if not gp:
            continue
        seen.append(rec["ref"])
        for p in gp:
            L = rec["side"]
            poly = p["poly"][L]
            nv = sum(1 for i in B.v_tree.query(poly.buffer(PROT_VIA_MM)) if B.vias[i]["net"] == p["net"]
                     and poly.distance(B.vias[i]["disc"]) <= PROT_VIA_MM + 1e-9)
            con = LQ.pad_connection(B, p, L)
            pour = bool(con and (con[0] or con[2] > 1e-3))
            ex = PROT_GND_EXEMPT.get(B.kind, {}).get(B.pad_ref(p))
            if ex and nv >= PROT_EXEMPT_MIN_VIAS and nv < PROT_MIN_VIAS and not pour:
                info.setdefault("prot_exempt", []).append([B.pad_ref(p), nv, ex])
                continue
            if nv < PROT_MIN_VIAS and not pour:
                fails["PROT-GND"].append({"part": rec["ref"], "value": rec["value"], "pad": B.pad_ref(p), "net": p["net"],
                                          "at": r3(p["pos"]), "vias": nv,
                                          "what": f"{nv} ground via(s) within {PROT_VIA_MM} mm and no own-pour connection "
                                                  f"(need {PROT_MIN_VIAS})"})
    info["prot_parts"] = sorted(seen)


def _pin_field(rec):
    ps = [p["poly"][rec["side"]] for p in rec["pads"] if p["num"] and rec["side"] in p["poly"]]
    return unary_union(ps).convex_hull if ps else Polygon()


def chk_xstack_ic(G, fails, info):
    B = G.B
    xf, xi = {k: [] for k in LQ.CHECKS}, {}
    LQ.chk_xstack(B, xf, xi)
    covered = {tuple(sorted(x["parts"])) for x in xf["XSTACK"]}
    ics = [rec for rec in B.fps.values() if rec["ref"][:1] == "U" and len(rec["pads"]) >= 3]
    fields = {rec["ref"]: _pin_field(rec) for rec in ics}
    top = [r for r in ics if r["side"] == F_Cu and not fields[r["ref"]].is_empty]
    bot = [r for r in ics if r["side"] == B_Cu and not fields[r["ref"]].is_empty]
    if not top or not bot:
        return
    tree = STRtree([fields[r["ref"]] for r in bot])
    dup = []
    for a in top:
        fa = fields[a["ref"]]
        for k in tree.query(fa):
            c = bot[k]
            ov = fa.intersection(fields[c["ref"]]).area
            if ov < XSTACK_IC_MIN_MM2:
                continue
            key = tuple(sorted((a["ref"], c["ref"])))
            if key in covered:
                dup.append(list(key))
                continue
            fails["XSTACK-IC"].append({"parts": list(key), "overlap_mm2": round(ov, 2),
                                       "at": r3(fa.intersection(fields[c["ref"]]).centroid.coords[0]),
                                       "what": "opposite-face IC pin fields overlap (interleaved: XSTACK sees no pad "
                                               "pair closer than its gap)"})
    info["xstack_ic_covered_by_XSTACK"] = dup


def chk_undersat(G, fails, info):
    B = G.B
    nets = defaultdict(set)
    for p in B.pads:
        if p["net"] and not LQ.GROUND_RE.match(p["net"]) and not p["net"].startswith("unconnected"):
            nets[p["ref"]].add(p["net"])
    big = [r for r in B.fps.values() if UNDERSAT_BIG_RE.match(r["ref"]) and not any(p["pth"] for p in r["pads"])]
    cys = {r["ref"]: LQ.fp_courtyard(B, r) for r in big}
    big = [r for r in big if not cys[r["ref"]].is_empty]
    tree = STRtree([cys[r["ref"]] for r in big]) if big else None
    for f in B.fps.values():
        if tree is None or not UNDERSAT_SAT_RE.match(f["ref"]):
            continue
        cf = LQ.fp_courtyard(B, f)
        if cf.is_empty or cf.area <= 0:
            continue
        for k in tree.query(cf):
            g = big[k]
            if g["ref"] == f["ref"] or g["side"] == f["side"]:
                continue
            ov = cf.intersection(cys[g["ref"]]).area / cf.area
            if ov < UNDERSAT_FRAC or nets[f["ref"]] & nets[g["ref"]]:
                continue
            if f["ref"] in UNDERSAT_ACCEPT.get(B.kind, {}):
                info.setdefault("undersat_accepted", []).append([f["ref"], g["ref"]])
                continue
            fails["UNDERSAT"].append({"part": f["ref"], "value": f["value"], "under": g["ref"], "under_value": g["value"],
                                      "overlap": round(ov, 2), "at": P(f["obj"].GetPosition()),
                                      "what": "satellite under an unrelated opposite-face part"})


RUN = {"VIA-SITE": chk_via_site, "DIFFPAIR-PLACE": chk_diffpair_place, "FIDUCIAL-SPREAD": chk_fiducial_spread,
       "EP-VIA-PATTERN": chk_ep_via_pattern, "PROT-GND": chk_prot_gnd, "XSTACK-IC": chk_xstack_ic,
       "UNDERSAT": chk_undersat}


def check(pcb, checks=CHECKS):
    unknown = set(checks) - set(CHECKS)
    if unknown or not checks:
        raise ValueError(f"unknown / empty checks: {sorted(unknown)}")
    t0 = time.time()
    B = LQ.Board(pcb)
    G = Geo(B)
    fails = {k: [] for k in CHECKS}
    info = {"load_s": round(time.time() - t0, 1)}
    for c in CHECKS:
        if c in checks:
            t1 = time.time()
            RUN[c](G, fails, info)
            info.setdefault("check_s", {})[c] = round(time.time() - t1, 1)
    gated = [c for c in checks if c not in WARN]
    consts = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float))}
    info["total_s"] = round(time.time() - t0, 1)
    return {"board": str(pcb), "kind": B.kind, "checks": list(checks), "constants": consts,
            "status": "FAIL" if any(fails[c] for c in gated) else "PASS",
            "counts": {k: len(v) for k, v in fails.items()}, "warn": sorted(WARN), "fails": fails, "info": info}


def require(pcb, out_json, checks=CHECKS):
    """placement hand-back / pre-route hook (KiCad Python): raises on any FAIL (warnings do not raise)."""
    res = check(pcb, checks)
    Path(out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if res["status"] != "PASS":
        raise RuntimeError(f"qa_placement FAILED {res['counts']} (report: {out_json})")
    return out_json


def counts(pcb, out_json=None, checks=CHECKS):
    """placement-loop hook (KiCad Python): per-check finding counts; never raises on findings."""
    res = check(pcb, checks)
    if out_json:
        Path(out_json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return {k: res["counts"][k] for k in checks}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--json")
    ap.add_argument("--checks", default=",".join(CHECKS))
    a = ap.parse_args(argv)
    try:
        res = check(a.board, tuple(x.strip() for x in a.checks.split(",") if x.strip()))
    except Exception as e:                                # fail closed
        import traceback
        traceback.print_exc()
        print(f"qa_placement ERROR: {e!r}")
        return 2
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"qa_placement {res['status']}  {a.board}  ({res['kind']})")
    for k in CHECKS:
        items = res["fails"][k]
        state = ("WARN" if k in WARN else "FAIL") if items else "ok"
        state = state if k in res["checks"] else "(not run)"
        print(f"  {k:15s} {state:4s} {len(items)}")
        for it in items[:40]:
            print("     ", json.dumps(it, default=str)[:260])
    print(f"  info: {json.dumps(res['info'], default=str)[:900]}")
    return 0 if res["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
