"""LCSC / EasyEDA footprint + symbol cache (copied from din-relay-8ch; C-number set = this project's bom.json):
    python jlc_footprints.py              fetch every missing C-number into bom/easyeda_cache/<C>.json
    python jlc_footprints.py --refresh    re-fetch all of them
    python jlc_footprints.py --list       print the C-number set and the cache status (no network)
    python jlc_footprints.py C123 C456    fetch (or re-fetch) just these
JLC places each part with the LCSC/EasyEDA footprint of its C-number (not ours), so qa_jlc_rotation.py needs that
footprint's pads. The cache is committed: the gate runs offline and is reproducible, and a changed LCSC footprint
shows up as a diff when the cache is refreshed.
C-number set = every JLC C-number in bom/bom.json (parts[MPN].jlc) whose line is SMD-assembled (smd_assembly, from the
native footprints of the pinned MAIN rev C / UI B7 designs) + EXTRA_CNUMS (pending choices, fallbacks and planned
swaps, so a JLC mapping change does not need a new study) + every jlc_pn in bom/jlc_rotation_verified.csv.
Per C-number the cache keeps:
  easyeda: status ok | no_footprint (API 404 / no packageDetail: JLC has no footprint for it - the gate then needs a
           confirm_in_placement row), url, sha256 of the raw response, component title, footprint title, footprint
           origin (canvas units), every footprint shape string (PAD / TRACK / ARC / CIRCLE / SOLIDREGION / TEXT, raw),
           symbol pins [{num, name, spice}] (number = the footprint pad it connects to)
  jlc:     brand / model / package / library type / stock from JLC's parts API (which part the C-number really is)
Footprint API: https://easyeda.com/api/products/<C>/components?version=6.4.19.5 (EasyEDA std v6: canvas units of
10 mil = 0.254 mm, canvas y points DOWN). footprint(c) below returns pads in mm, y UP, relative to the LCSC footprint
origin - the point JLC puts on the CPL Mid X/Y.
"""
import csv
import hashlib
import json
import math
import re
import socket
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CACHE = ROOT / "bom" / "easyeda_cache"
U = 0.254                                   # EasyEDA canvas unit (10 mil) in mm
EE_URL = "https://easyeda.com/api/products/{c}/components?version=6.4.19.5"
# pending / fallback / planned C-numbers (owner + lead, 2026-09-29) - covered before they reach the BOM mapping (bom.json)
EXTRA_CNUMS = {
    "C427525": "TI LP5024RSMR - the stock fallback for UI U5 LP5018RSMR (same RSM footprint; QA UI-3, 2026-09-30)",
    "C43772752": "WSK12162L000FEA 2 mOhm shunt RS1-RS8 (owner's choice, consign)",
    "C844476": "WSK12161L000FEA 1 mOhm - footprint PROXY for C43772752 only; NEVER fit it (PGA 4 would halve every reading)",
    "C2169427": "KEMET C0603C153F3GACTU 15 nF C0G +-1 % (the BOM part)",
    "C22418931": "KEMET C0603C153G3GACTU 15 nF C0G (BOM MPN)",
    "C20250761": "Vishay TNPV1206330KBEEA",
    "C151255": "Littelfuse SMBJ16CA",
    "C71870": "SMBJ16CA fallback",
    "C403268": "Panasonic ERJ-3EKF5362V (MON divider)",
    "C509090": "Panasonic ERA-3ARB102V",
    "C844891": "Vishay TNPW06031K00BEEA",
    "C191884": "TI TPS54202DDCR SOT-23-6 (rejected U1 candidate - kept for the record)",
    "C116592": "TI TPS563201DDCR (former MAIN U1, replaced by LMR51420XDDCR C5246146)",
    "C23654": "TI SN74LVC1G125DBVR (DBVT backup)",
    "C504571": "TI UCC12050DVER (reel of the BOM part)",
    "C201530": "TI PCA9538PWR (design-level backup)",
    # UI D13 green: the earlier C5478413's LCSC library contradicts itself (symbol / doc marks: pad 1 = anode; polarity
    # dot + silk corner: pad 1 = marked end) - self-consistent candidates, gate-checked 2026-09-29. Chosen: AA3528ZGSK
    # C6727481 (now the BOM MPN and its exact JLC mapping); C5364133 kept cached as the rejected comparison
    "C6727481": "Kingbright AA3528ZGSK green PLCC-2 (D13, BOM MPN since 2026-09-29)",
    "C5364133": "Wurth 150141VS73100 PLCC-2 (D13 candidate, rejected: 570 nm yellow-green AlInGaP)",
}


def cpl_rotation(kicad_rot, offset, bottom):
    """JLC CPL Rotation for a placement: THE one formula, shared by every CPL writer (assembly_exports.py,
    hardware/ui/release/tools/assembly_package.py) and the gate (qa_jlc_rotation.cpl_expect / cpl_expect_bottom).
    JLC turns the C-number's LCSC footprint counter-clockwise by Rotation - on the top side as seen from above, on the
    BOTTOM side as seen from BELOW (measured from JLC's own UI B8.1 bottom preview, 2026-10-06:
    docs/records/jlc-preview/AUDIT.md - the only convention that fits J1, J4, U6 and U800 at once).
    KiCad shows a bottom footprint at orientation K turned 180 - K as seen from below (qa_jlc_rotation.bottom_view), so
      top:    (K + offset) mod 360
      bottom: (180 - K + offset) mod 360
    The old bottom formula K + offset agrees only when 2K = 180 (mod 360), i.e. K = 90 / 270 (J4); at K = 0 / 180 it
    put every polarised bottom part 180 deg wrong (J1, U6, U800)."""
    k = float(kicad_rot)
    return ((180.0 - k if bottom else k) + float(offset)) % 360


def _rows(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def cnumber_set():
    """{C-number: why}: every JLC C-number in this project's bom/bom.json (design lcsc codes)."""
    import json
    b = json.loads((ROOT / "bom" / "bom.json").read_text(encoding="utf-8"))
    return {l["lcsc_design"]: f"bom.json {l['mpn']}" for l in b["lines"] if re.fullmatch(r"C\d+", l.get("lcsc_design") or "")}


def _get(url, data=None):
    socket.setdefaulttimeout(30)
    hdr = {"User-Agent": "curl/8.5.0", "Accept": "application/json"}
    if data is not None:
        hdr["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=30).read()


def _jlc_info(c):
    """Which part the C-number really is, via jlc_api.py (the one sanctioned JLC client: shared lock + spacing, cache,
    bounded retries) - never an inline call to JLC's endpoint."""
    sys.path.insert(0, str(HERE))
    import jlc_api
    r = jlc_api.by_code(c)
    if r.status == "error":                                     # informational only
        return {"status": f"error: {r.error}"}
    if r.part is None:
        return {"status": r.status}
    x = r.part
    return {"status": "ok", "brand": x.maker, "model": x.mpn, "package": x.package, "library": x.library,
            "stock": x.stock, "describe": x.description}


def _symbol_pins(r):
    """[{num, name, spice}] from the EasyEDA symbol (all sub-parts). Pin string: P~show~electric~spicePin~x~y~rot~id~
    locked^^dot^^path^^name^^number^^..., name/number segments = visible~x~y~rot~TEXT~anchor~..."""
    docs = [r.get("dataStr") or {}] + [(s.get("dataStr") or {}) for s in (r.get("subparts") or [])]
    pins = []
    for d in docs:
        for s in d.get("shape") or []:
            if not s.startswith("P~"):
                continue
            seg = s.split("^^")
            head = seg[0].split("~")
            name = seg[3].split("~")[4] if len(seg) > 3 and len(seg[3].split("~")) > 4 else ""
            num = seg[4].split("~")[4] if len(seg) > 4 and len(seg[4].split("~")) > 4 else head[3]
            pins.append({"num": num, "name": name, "spice": head[3]})
    return pins


def fetch(c):
    url = EE_URL.format(c=c)
    raw, err = None, ""
    for attempt in range(4):
        try:
            raw = _get(url)
            break
        except Exception as e:
            err = str(e)
            # easyeda.com answers 403 after a burst of requests: back off properly, then retry
            time.sleep(90 if "403" in err else 3 + 3 * attempt)
    rec = {"c": c, "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "jlc": _jlc_info(c)}
    if raw is None:
        rec["easyeda"] = {"status": f"fetch_error: {err}", "url": url}
        return rec
    rec["easyeda"] = parse_raw(raw, url)
    return rec


def parse_raw(raw, url):
    """The cached 'easyeda' record from one raw API response (bytes)."""
    j = json.loads(raw)
    r = j.get("result") if isinstance(j.get("result"), dict) else None
    pk = (r or {}).get("packageDetail") or {}
    ds = pk.get("dataStr") or {}
    ee = {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "api_success": j.get("success"),
          "api_code": j.get("code")}
    if not j.get("success") or r is None or not ds.get("shape"):
        ee["status"] = "no_footprint"
        ee["note"] = "EasyEDA API returned no footprint (JLC has none for this C-number)"
    else:
        head = ds["head"]
        ee.update(status="ok", title=r.get("title"), package_title=pk.get("title"),
                  c_para={k: v for k, v in (r.get("dataStr", {}).get("head", {}).get("c_para") or {}).items()
                          if k in ("name", "package", "Manufacturer", "Manufacturer Part", "Supplier Part")},
                  origin=[float(head["x"]), float(head["y"])], shapes=ds["shape"], symbol_pins=_symbol_pins(r))
    return ee


def load(c):
    p = CACHE / f"{c}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def footprint(c):
    """LCSC footprint of C-number c from the cache: {title, pads: [{num, shape, x, y, poly, w, h, layer}]} in mm, y UP,
    relative to the LCSC origin (poly = pad outline, same frame). None when the cache says no_footprint; KeyError
    when c is not cached at all (run jlc_footprints.py)."""
    rec = load(c)
    if rec is None:
        raise KeyError(c)
    ee = rec["easyeda"]
    if ee.get("status") != "ok":
        return None
    ox, oy = ee["origin"]

    def P(x, y):
        return ((float(x) - ox) * U, -(float(y) - oy) * U)
    pads = []
    for s in ee["shapes"]:
        f = s.split("~")
        if f[0] != "PAD":
            continue
        shape, x, y, w, h, layer, num = f[1], f[2], f[3], float(f[4]) * U, float(f[5]) * U, f[6], f[8]
        rot = float(f[11]) if len(f) > 11 and f[11] not in ("",) else 0.0
        pts = [float(v) for v in f[10].split()] if len(f) > 10 and f[10].strip() else []
        cx, cy = P(x, y)
        if shape in ("RECT", "POLYGON") and len(pts) >= 6:
            poly = [P(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
        else:                                  # ELLIPSE / OVAL: the w x h box turned by the pad rotation (EasyEDA
            a = math.radians(-rot)             # rot is clockwise on the y-down canvas; a box turned by a multiple of
            c_, s_ = math.cos(a), math.sin(a)  # 90 deg is the same either way)
            poly = [(cx + dx * c_ - dy * s_, cy + dx * s_ + dy * c_)
                    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
        pads.append({"num": num, "shape": shape, "x": cx, "y": cy, "poly": poly, "layer": layer, "rot": rot})
    # layer 101 = EasyEDA 'ComponentPolarityLayer': the dot JLC's placement preview draws for the package's pin-1 /
    # cathode mark (every cached LCSC footprint has exactly one, as a CIRCLE)
    marks = []
    for s in ee["shapes"]:
        f = s.split("~")
        if f[0] == "CIRCLE" and len(f) > 5 and f[5] == "101":
            marks.append(P(f[1], f[2]))
    return {"title": ee.get("package_title"), "component": ee.get("title"), "pads": pads, "marks": marks,
            "pins": {p["num"]: p["name"] for p in ee.get("symbol_pins", [])},
            "describe": (rec.get("jlc") or {}).get("describe") or ""}


def main(argv):
    CACHE.mkdir(parents=True, exist_ok=True)
    if argv[:1] == ["--list"]:
        for c, why in sorted(cnumber_set().items(), key=lambda kv: int(kv[0][1:])):
            rec = load(c)
            st = rec["easyeda"]["status"] if rec else "NOT CACHED"
            print(f"{c:11s} {st:14s} {(rec or {}).get('easyeda', {}).get('package_title') or '':44s} {why}")
        return 0
    refresh = argv[:1] == ["--refresh"]
    todo = [a for a in argv if re.fullmatch(r"C\d+", a)] or sorted(cnumber_set(), key=lambda c: int(c[1:]))
    explicit = any(re.fullmatch(r"C\d+", a) for a in argv)
    bad = []
    for c in todo:
        p = CACHE / f"{c}.json"
        if p.exists() and not (refresh or explicit):
            continue
        rec = fetch(c)
        st = rec["easyeda"]["status"]
        if st.startswith("fetch_error"):
            bad.append(c)
            print(f"{c}: {st} - cache NOT written")
            continue
        p.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        j = rec["jlc"]
        print(f"{c}: {st:12s} {rec['easyeda'].get('package_title') or '-':44s} JLC {j.get('brand')} {j.get('model')} "
              f"{j.get('package')}")
        time.sleep(4.0)
    missing = [c for c in cnumber_set() if not (CACHE / f"{c}.json").exists()]
    nofp = sorted(c for c in cnumber_set() if (CACHE / f"{c}.json").exists()
                  and load(c)["easyeda"]["status"] == "no_footprint")
    print(f"cache: {len(cnumber_set()) - len(missing)} C-numbers cached, NO LCSC FOOTPRINT: {' '.join(nofp) or 'none'}"
          + (f"; NOT CACHED: {' '.join(missing)}" if missing else ""))
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
