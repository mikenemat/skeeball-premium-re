"""Tiny netlist DSL (copied from C:/work/din-relay-8ch/scripts/netlist_core.py, library name changed): parts, pins, nets. Single source of truth for schematic, PCB and BOM.

Pins are given by number or by unique pin name; names are resolved against the symbol's
pin table (KiCad stock libraries or hardware/lib/skeeball.kicad_sym).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

KICAD_SYM = Path(r"C:/Program Files/KiCad/10.0/share/kicad/symbols")
ROOT = Path(__file__).resolve().parents[1]
PROJ_SYM = ROOT / "hardware" / "lib" / "skeeball.kicad_sym"
PROJ_LIB = "skeeball"

_pin_cache: dict[str, list[tuple[str, str, str]]] = {}

MPN_REPLACE: dict = {}   # (din8r catalogue fixes not carried over)
MPN_0603: dict = {}


def _symbol_block(text: str, name: str) -> str | None:
    key = f'(symbol "{name}"'
    i = text.find(key)
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


PIN_RE = re.compile(r'\(pin\s+(\w+)\s+\w+.*?\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"', re.S)
PIN_GEO_RE = re.compile(r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)\s*\(length\s+([-\d.]+)\)'
                        r'.*?\(name\s+"([^"]*)"', re.S)
_geo_cache: dict[str, tuple[float, float, float, float, int, int]] = {}


def symbol_extent(lib_id: str):
    """(xmin, xmax, ymin, ymax, max_left_name, max_right_name) of pin connection points, symbol units (y up)."""
    if lib_id in _geo_cache:
        return _geo_cache[lib_id]
    lib, name = lib_id.split(":", 1)
    path = PROJ_SYM if lib == PROJ_LIB else KICAD_SYM / f"{lib}.kicad_sym"
    text = path.read_text(encoding="utf-8")
    blk = _symbol_block(text, name)
    m = re.search(r'\(extends\s+"([^"]+)"', blk or "")
    if m:
        res = symbol_extent(f"{lib}:{m.group(1)}")
    else:
        pts = [(float(x), float(y)) for x, y, r, l, n in PIN_GEO_RE.findall(blk)]
        if not pts:
            pts = [(0.0, 0.0)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        res = (min(xs), max(xs), min(ys), max(ys), 0, 0)
    _geo_cache[lib_id] = res
    return res


def symbol_pins(lib_id: str) -> list[tuple[str, str, str]]:
    """Return [(number, name, etype)] for a lib_id like 'Device:R' or 'skeeball:TPS2553DBV'."""
    if lib_id in _pin_cache:
        return _pin_cache[lib_id]
    lib, name = lib_id.split(":", 1)
    path = PROJ_SYM if lib == PROJ_LIB else KICAD_SYM / f"{lib}.kicad_sym"
    text = path.read_text(encoding="utf-8")
    blk = _symbol_block(text, name)
    if blk is None:
        raise KeyError(f"symbol {lib_id} not found in {path}")
    m = re.search(r'\(extends\s+"([^"]+)"', blk)
    if m:
        pins = symbol_pins(f"{lib}:{m.group(1)}")
    else:
        pins = [(num, nm, et) for et, nm, num in PIN_RE.findall(blk)]
    _pin_cache[lib_id] = pins
    return pins


@dataclass
class Part:
    ref: str
    lib_id: str
    value: str
    footprint: str
    sheet: str
    mpn: str = ""
    mfr: str = ""
    dnp: bool = False
    note: str = ""
    conns: dict[str, str] = field(default_factory=dict)  # pin number -> net
    fields: dict[str, str] = field(default_factory=dict)
    block: str = ""


class Design:
    def __init__(self):
        self.block = ""                      # current placement block; stamped onto every part added
        self.pkg = "0805"                    # default passive size for R()/C() without an explicit footprint
        self.parts: dict[str, Part] = {}
        self._counters: dict[str, int] = {}
        self.net_classes: dict[str, str] = {}   # net -> class name

    # ---- parts -------------------------------------------------------------
    def next_ref(self, prefix: str, start: int = 1) -> str:
        n = max(self._counters.get(prefix, start - 1) + 1, start)
        self._counters[prefix] = n
        return f"{prefix}{n}"

    def add(self, prefix_or_ref: str, lib_id: str, value: str, footprint: str, sheet: str, pins: dict,
            mpn: str = "", mfr: str = "", dnp: bool = False, note: str = "", fixed_ref: bool = False,
            **fields) -> Part:
        ref = prefix_or_ref if fixed_ref else self.next_ref(prefix_or_ref)
        if ref in self.parts:
            raise ValueError(f"duplicate ref {ref}")
        if mpn in MPN_REPLACE:
            old_mpn = mpn
            mpn, mfr = MPN_REPLACE[mpn]
            if value in (old_mpn, old_mpn.split(",")[0]) and not old_mpn.startswith("2N7002"):
                value = mpn                      # a value that named the old part names the new one
        p = Part(ref, lib_id, value, footprint, sheet, mpn, mfr, dnp, note, fields=dict(fields), block=self.block)
        table = symbol_pins(lib_id)
        by_num = {n: (n, nm, et) for n, nm, et in table}
        for key, net in pins.items():
            key = str(key)
            if key in by_num:
                nums = [key]
            else:
                nums = [n for n, nm, _ in table if nm == key]
                if not nums:
                    raise KeyError(f"{ref} ({lib_id}): no pin '{key}'. Pins: {[(n, nm) for n, nm, _ in table]}")
            for n in nums:
                if n in p.conns and p.conns[n] != net:
                    raise ValueError(f"{ref} pin {n} assigned twice ({p.conns[n]} vs {net})")
                p.conns[n] = net
        self.parts[ref] = p
        return p

    # ---- passives shorthand ---------------------------------------------------
    # Default passive size follows self.pkg ("0805" or "0603"). 0603 is used only in the space-critical blocks
    # (metering islands, relay drivers, sensing); a capacitor whose 0805 MPN has no vetted 0603 twin (e.g. 10 uF,
    # where DC-bias derating in 0603 is poor) stays 0805.
    def R(self, value, a, b, sheet, fp=None, mpn="", mfr="", tol="1%", **kw):
        if fp is None:
            fp = "Resistor_SMD:R_0603_1608Metric" if self.pkg == "0603" else "Resistor_SMD:R_0805_2012Metric"
            if self.pkg == "0603":
                mpn = MPN_0603.get(mpn, mpn)
        return self.add("R", "Device:R", value, fp, sheet, {"1": a, "2": b}, mpn=mpn, mfr=mfr, tolerance=tol, **kw)

    def C(self, value, a, b, sheet, fp=None, mpn="", mfr="", **kw):
        if fp is None:
            if self.pkg == "0603" and (mpn in MPN_0603 or not mpn):
                fp, mpn = "Capacitor_SMD:C_0603_1608Metric", MPN_0603.get(mpn, mpn)
            else:
                fp = "Capacitor_SMD:C_0805_2012Metric"
        return self.add("C", "Device:C", value, fp, sheet, {"1": a, "2": b}, mpn=mpn, mfr=mfr, **kw)

    # ---- queries -------------------------------------------------------------
    def nets(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = {}
        for p in self.parts.values():
            for pin, net in p.conns.items():
                out.setdefault(net, []).append((p.ref, pin))
        return out

    def check(self) -> list[str]:
        """Structural checks: single-pin nets, unconnected non-NC pins."""
        issues = []
        for net, pins in self.nets().items():
            if len(pins) < 2 and not net.startswith("NC_") and not net.startswith("TP_"):
                issues.append(f"net {net} has only {pins}")
            if net.startswith("NC_") and len(pins) > 1:      # a shared NC name silently joins pins (rev B.3: it
                issues.append(f"NC net {net} joins {pins}")  # joined a SELV and an island LDO pin across the barrier)
        for p in self.parts.values():
            for n, nm, et in symbol_pins(p.lib_id):
                if n not in p.conns and et != "no_connect":
                    issues.append(f"{p.ref} pin {n} ({nm}) unconnected")
        return issues
