# ported from din8r-chassis-thermal/scripts/qa_power_layout.py, 2026-10-26 (SBC-1 DECAP table; CT LOOP / DIODECU dropped)
"""Power-layout gate: the reference-design placement rule that DRC / parity cannot see (CT origin: QA_LOG HW-ADVQA2 H9).
SBC-1 port 2026-10-27: CT's flyback LOOP and D6 DIODECU checks are dropped (no flyback / no D6 on SBC-1); the DECAP
table below is SBC-1's (pairings from design.py notes; "one per pin group" caps paired with the pin place.py put them
at - LEAD TO CONFIRM).

    py scripts/local_run.py qa_power_layout.py [board] [--report]        exit 0 = PASS

DECAP - every decoupling / bias / filter part listed is <= MAX_MM from its pin, measured along the copper (CT root
        2026-10-17: "the path from its pad, through its via, to the pin"): from the centre of the part's pad on the
        pin's net along that net's tracks and vias (any layer) to where the copper enters the IC pin pad; a part joined
        only through a zone falls back to the straight pad-centre distance (marked "zone").
"""
import math
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "hardware" / "main" / "skeeball-controller.kicad_pcb"
MAX_MM = 3.0

# (IC, pin, part, why) - the part's pad on the pin's net must be within MAX_MM of the pin
DECAP = [
    # TPS259531 eFuse (SLVSE57C Figure 47: CIN 0.1 uF at IN, CdVdt at DVDT, RILM at ILM; OUT 0.1 uF)
    ("U1", "3", "C4", "CIN 0.1 uF (Figure 47 note 1)"), ("U1", "1", "C6", "CdVdt at DVDT"),
    ("U1", "7", "R3", "RILM at ILM"), ("U1", "5", "C9", "OUT 0.1 uF"),
    # TLV62569 buck (SLVSDF8: C1 at VIN, L at SW, FB divider at FB)
    ("U2", "4", "C10", "C1 4.7 uF at VIN (Table 3)"), ("U2", "3", "L1", "inductor at SW"),
    ("U2", "5", "R5", "FB divider top"), ("U2", "5", "R6", "FB divider bottom"),
    # TLV743P LDO (SBVS254 8.1: CIN / COUT 1 uF at the pins)
    ("U3", "1", "C13", "CIN 1 uF"), ("U3", "5", "C14", "COUT 1 uF"),
    # TPS2553 (10.2: IN bypass 0.1 uF; RILIM at ILIM)
    ("U4", "1", "C15", "IN bypass 0.1 uF (10.2)"), ("U4", "5", "R7", "RILIM at ILIM"),
    # RP2350B (RP2350 DS Figure 16: one 100 nF per IOVDD / QSPI_IOVDD / ADC_AVDD / USB_OTP_VDD group, 100 nF per DVDD)
    ("U5", "5", "C18", "IOVDD 100 nF"), ("U5", "15", "C19", "IOVDD 100 nF"), ("U5", "24", "C20", "IOVDD 100 nF"),
    ("U5", "29", "C21", "IOVDD 100 nF"), ("U5", "41", "C22", "IOVDD 100 nF"), ("U5", "50", "C23", "IOVDD 100 nF"),
    ("U5", "59", "C24", "IOVDD group 100 nF"), ("U5", "61", "C31", "VREG_AVDD / VREG_VIN 4.7 uF (RP2350 DS 6.1.6; q6 C25 / C31 swap)"),
    ("U5", "64", "C26", "IOVDD group 100 nF"), ("U5", "76", "C27", "IOVDD 100 nF"),
    ("U5", "10", "C28", "DVDD 100 nF (Figure 16 C8)"), ("U5", "32", "C29", "DVDD 100 nF (C10)"),
    ("U5", "51", "C30", "DVDD 100 nF (C11)"),
    # W25Q128JV: 0.1 uF at VCC
    ("U6", "8", "C34", "VCC 0.1 uF"),
    # W5500 (W5500-Ref-ExternalMag: 0.1 uF per AVDD pin, VDD 0.1 uF, TOCAP 4.7 uF, 1V2O 10 nF, EXRES 12.4k)
    ("U7", "4", "C37", "AVDD 0.1 uF"), ("U7", "8", "C41", "AVDD 0.1 uF"), ("U7", "11", "C42", "AVDD 0.1 uF"),
    ("U7", "15", "C39", "AVDD 0.1 uF"), ("U7", "17", "C40", "AVDD 0.1 uF"), ("U7", "21", "C38", "AVDD 0.1 uF"),
    ("U7", "28", "C45", "VDD 0.1 uF (ref C12)"), ("U7", "20", "C46", "TOCAP 4.7 uF"), ("U7", "22", "C47", "1V2O 10 nF"),
    ("U7", "10", "R22", "EXRES 12.4k"),
    # MAX98357A (Typical Application Circuit: 10 uF + 0.1 uF at VDD)
    ("U8", "7", "C55", "VDD 0.1 uF"), ("U8", "7", "C54", "VDD 10 uF"),
    # CH340N (DS 7: 0.1 uF at VCC and at V3)
    ("U14", "8", "C72", "VCC 0.1 uF (C9)"), ("U14", "5", "C73", "V3 0.1 uF (C8)"),
]


def mm(v):
    return pcbnew.ToMM(v)


def centre(pad):
    p = pad.GetPosition()
    return (mm(p.x), mm(p.y))


def copper_path_len(b, net, src, dst):
    """Shortest copper path (mm) on `net` from the centre of pad `src` to pad `dst` (entry into the pad), through
    tracks and vias on any layer; None if the two pads are not joined by tracks / vias."""
    import heapq
    items = [t for t in b.GetTracks() if t.GetNetname() == net]
    nodes, layer, edges = [], [], {}

    def add(pt, lay):
        nodes.append(pt)
        layer.append(lay)
        return len(nodes) - 1

    def link(u, v, w):
        edges.setdefault(u, []).append((w, v))
        edges.setdefault(v, []).append((w, u))
    segs, vias = [], []
    for t in items:
        if t.GetClass() == "PCB_VIA":
            vias.append((add((mm(t.GetPosition().x), mm(t.GetPosition().y)), None), mm(t.GetWidth(pcbnew.F_Cu)) / 2))
        else:
            a = add((mm(t.GetStart().x), mm(t.GetStart().y)), t.GetLayer())
            c = add((mm(t.GetEnd().x), mm(t.GetEnd().y)), t.GetLayer())
            link(a, c, math.dist(nodes[a], nodes[c]))
            segs.append((a, c, mm(t.GetWidth()) / 2, t.GetLayer()))

    def seg_dist(pt, a, c):
        (x1, y1), (x2, y2) = nodes[a], nodes[c]
        L2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        u = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - x1) * (x2 - x1) + (pt[1] - y1) * (y2 - y1)) / L2))
        q = (x1 + u * (x2 - x1), y1 + u * (y2 - y1))
        return math.dist(pt, q), q
    ends = [k for k in range(len(nodes)) if layer[k] is not None]
    for k in ends:                                   # track ends touching other tracks (same layer) or vias
        for a, c, hw, lay in segs:
            if lay != layer[k] or k in (a, c):
                continue
            dd, q = seg_dist(nodes[k], a, c)
            if dd <= hw + 0.01:
                link(k, a, math.dist(q, nodes[a]))
                link(k, c, math.dist(q, nodes[c]))
        for v, r in vias:
            if math.dist(nodes[k], nodes[v]) <= r + 0.01:
                link(k, v, 0.0)
    S, T = add(centre(src), None), add(centre(dst), None)
    for k in range(len(nodes) - 2):
        pt = pcbnew.VECTOR2I(pcbnew.FromMM(nodes[k][0]), pcbnew.FromMM(nodes[k][1]))
        lay_ok = (lambda pd: layer[k] is None or pd.IsOnLayer(layer[k]))
        if lay_ok(src) and src.HitTest(pt):
            link(S, k, math.dist(nodes[S], nodes[k]))
        if lay_ok(dst) and dst.HitTest(pt):
            link(k, T, 0.0)
    dist, heap = {S: 0.0}, [(0.0, S)]
    while heap:
        d0, u = heapq.heappop(heap)
        if u == T:
            return d0
        if d0 > dist.get(u, 1e18):
            continue
        for w, v in edges.get(u, []):
            if d0 + w < dist.get(v, 1e18):
                dist[v] = d0 + w
                heapq.heappush(heap, (d0 + w, v))
    return None


def shoelace(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    report = "--report" in sys.argv
    b = pcbnew.LoadBoard(str(Path(args[0]) if args else PCB))
    fps = {fp.GetReference(): fp for fp in b.GetFootprints()}

    def pad(ref, num):
        return next(p for p in fps[ref].Pads() if p.GetNumber() == num)

    def pads(ref, net=None):
        return [p for p in fps[ref].Pads() if p.GetNumber() and (net is None or p.GetNetname() == net)]
    fails = []
    print("== DECAP (part pad -> copper path -> IC pin, max %.1f mm)" % MAX_MM)
    for ic, pin, part, why in DECAP:
        pp = pad(ic, pin)
        if part not in fps:
            fails.append(f"DECAP {ic}.{pin} {part}: part not on the board")
            print(f"   FAIL {ic}.{pin:3s} {pp.GetNetname()[:10]:10s} {part:4s} missing  {why}")
            continue
        cand = pads(part, pp.GetNetname())
        if not cand:
            fails.append(f"DECAP {ic}.{pin} {part}: no pad of {part} on {pp.GetNetname()}")
            continue
        how = "path"
        paths = [x for x in (copper_path_len(b, pp.GetNetname(), q, pp) for q in cand) if x is not None]
        if paths:
            d = min(paths)
        else:
            d, how = min(math.dist(centre(pp), centre(q)) for q in cand), "zone"
        ok = d <= MAX_MM
        if not ok:
            fails.append(f"DECAP {ic}.{pin} {part} {d:.2f} mm > {MAX_MM}")
        if report or not ok:
            side = "B" if fps[part].IsFlipped() else "F"
            tgt = ""
            print(f"   {'PASS' if ok else 'FAIL'} {ic}.{pin:3s} {pp.GetNetname()[:10]:10s} {part:4s} ({side}) "
                  f"{d:5.2f} mm {how}{tgt}  {why}")
    print(f"power layout: {len(DECAP)} decap rows - {len(fails)} FAIL")
    for f in fails:
        print("  FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
