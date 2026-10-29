"""(Copied from C:/work/din-relay-8ch/scripts/gen_schematic.py.) Generate the KiCad schematic (multi-sheet, global labels) from scripts/design.py.

Every pin that carries a net gets a global label at its connection point, oriented away from
the symbol. Pins on NC_* nets get a no-connect flag. Rails get PWR_FLAGs for ERC.
Verification: kicad-cli netlist export is compared against the design database (qa_netlist.py).
"""
import math
import re
import sys
import uuid
from functools import lru_cache
from pathlib import Path

import kicad_sch_api as ksa

sys.path.insert(0, str(Path(__file__).parent))
from netlist_core import symbol_pins, symbol_extent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GRID = 2.54


def snap(v):
    return round(v / GRID) * GRID


def _label_block(net, x, y, angle):
    just = "left" if angle in (0, 90) else "right"
    return (f'\t(global_label "{net}"\n\t\t(shape passive)\n\t\t(at {x:.4f} {y:.4f} {angle})\n'
            f'\t\t(fields_autoplaced yes)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify {just})\n\t\t)\n\t\t(uuid "{uuid.uuid4()}")\n'
            f'\t\t(property "Intersheetrefs" "${{INTERSHEET_REFS}}"\n\t\t\t(at {x:.4f} {y:.4f} 0)\n'
            f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n\t)\n')


def _nc_block(x, y):
    return f'\t(no_connect\n\t\t(at {x:.4f} {y:.4f})\n\t\t(uuid "{uuid.uuid4()}")\n\t)\n'


def _text_block(txt, x, y, size=2.5):
    return (f'\t(text "{txt}"\n\t\t(exclude_from_sim no)\n\t\t(at {x:.3f} {y:.3f} 0)\n\t\t(effects\n\t\t\t(font\n'
            f'\t\t\t\t(size {size} {size})\n\t\t\t\t(bold yes)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n'
            f'\t\t(uuid "{uuid.uuid4()}")\n\t)\n')


def _clean(s: str) -> str:
    """Drop kicad-sch-api's visible hierarchy_path property; hide every field except Reference/Value."""
    out, i = [], 0
    while True:
        j = s.find('(property "', i)
        if j < 0:
            out.append(s[i:])
            break
        out.append(s[i:j])
        depth, k, quoted, esc, at_pos = 0, j, False, False, -1   # quote-aware: values may contain "(" / ")"
        while True:
            ch = s[k]
            if quoted:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    quoted = False
            elif ch == '"':
                quoted = True
            elif ch == '(':
                depth += 1
                if depth == 2 and at_pos < 0 and s.startswith("(at ", k):
                    at_pos = k - j
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        blk = s[j:k + 1]
        name = blk[len('(property "'):blk.index('"', len('(property "'))]
        if name == "hierarchy_path":
            # also eat the preceding indentation/newline
            while out and out[-1] and out[-1][-1] in "\t":
                out[-1] = out[-1][:-1]
        elif (name not in ("Reference", "Value", "Sheetname", "Sheetfile")   # SBC-1: root sheet names stay visible
              and "(hide yes)" not in blk and s[max(0, j - 3):j] == "\n\t\t"):
            at_end = blk.index(")", at_pos) + 1          # the property's own (at x y r), never text in its value
            blk = blk[:at_end] + " (hide yes)" + blk[at_end:]
            out.append(blk)
        else:
            out.append(blk)
        i = k + 1
    return "".join(out)


# kicad-sch-api 0.5.5 re-serialises a KiCad 10 "private" library property (KLC notes, e.g. Device:Crystal_GND24 since
# xtal-fix) as `(property "private" "KLC_S3.3" The rectangle is not ...` - the keyword quoted as a name and the text
# unquoted - which eeschema cannot parse: the whole sheet fails to load and its parts drop out of the netlist. Restore
# the library syntax `(property private "NAME" "TEXT"` (the text re-quoted, KiCad escaping).
_PRIVATE_BROKEN = re.compile(r'\(property "private" "((?:[^"\\]|\\.)*)" (?!")([^\n]*?)[ \t]*(?=\n)')


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fix_private_properties(s: str) -> tuple:
    """(fixed text, count) - see _PRIVATE_BROKEN. A correct `(property private "N" "T"` is left alone."""
    return _PRIVATE_BROKEN.subn(lambda m: f'(property private "{m.group(1)}" {_quote(m.group(2).strip())}', s)


def inject(path: Path, blocks: list[str]):
    s = _clean(fix_private_properties(path.read_text(encoding="utf-8"))[0])
    i = s.rstrip().rfind(")")
    s = s[:i] + "".join(blocks) + s[i:]
    path.write_text(s, encoding="utf-8")


def _mark_dnp(path: Path, refs: set, nobom: set = frozenset()):
    """Set (dnp yes) / (in_bom no) on the symbols of DNP parts (kicad-sch-api's dnp setter is not reliable), so
    the board's DNP attributes (pcb_fields.py) match the schematic in the parity check; test points: (in_bom no)
    only (their footprints are excluded from the BOM)."""
    if not refs and not nobom:
        return
    allrefs = set(refs) | set(nobom)
    s = path.read_text(encoding="utf-8")
    out, pos = [], 0
    for m in re.finditer(r'\(reference "([^"]+)"\)', s):
        if m.group(1) not in allrefs:
            continue
        start = s.rfind("\n\t(symbol\n", 0, m.start())
        if start < pos:
            continue
        seg = s[start:m.start()]
        seg = seg.replace("(in_bom yes)", "(in_bom no)", 1)
        if m.group(1) in refs:
            seg = seg.replace("(dnp no)", "(dnp yes)", 1)
        out.append(s[pos:start])
        out.append(seg)
        pos = m.start()
    out.append(s[pos:])
    path.write_text("".join(out), encoding="utf-8")


@lru_cache(maxsize=None)
def symbol_units(lib_id):
    """Default-body pins per positive KiCad unit, with shared unit0 pins.

    The API's flattened pins/units do not preserve this distinction: units also
    counts common graphic unit0, and list_component_pins overlays every unit.
    Read the resolved library definition, including inherited stock symbols.
    """
    definition = ksa.get_symbol_cache().get_symbol(lib_id)
    if definition is None:
        raise ValueError('Missing symbol '+lib_id)
    by_unit = {}
    for block in definition.raw_kicad_data:
        if not isinstance(block, list) or not block or str(block[0]) != 'symbol':
            continue
        suffix = re.search(r'_(\d+)_(\d+)$', str(block[1]))
        if suffix is None:
            continue
        unit, style = map(int, suffix.groups())
        if style not in (0, 1):
            continue  # De Morgan variants are not selected by this generator.
        pins = by_unit.setdefault(unit, {})
        for item in block[2:]:
            if not isinstance(item, list) or not item or str(item[0]) != 'pin':
                continue
            fields = {str(v[0]): v[1:] for v in item[1:] if isinstance(v, list) and v}
            number = str(fields['number'][0])
            at = fields['at']
            geo = (float(at[0]), float(at[1]), float(at[2]) if len(at) > 2 else 0.0)
            if number in pins and pins[number][:2] != geo[:2]:
                raise ValueError(f'{lib_id} unit{unit} conflicting pin{number}')
            pins[number] = geo
    units = sorted(u for u in by_unit if u > 0) or [1]
    common = by_unit.get(0, {})
    return tuple((u, tuple({**common, **by_unit.get(u, {})}.items())) for u in units)



def _stable_uuids(root_path, sheet_names, namespace):
    """Canonicalize generated UUID definitions and all hierarchy references.

    Ref/unit identities remain stable across value/field changes. Other objects
    use their deterministic structural position within their sheet. The seed
    is independent of output directory and root filename.
    """
    import sexpdata as sx
    seed = uuid.uuid5(uuid.NAMESPACE_URL, namespace)
    mapping, texts = {}, {}
    for path in [root_path, *[root_path.parent/(n+'.kicad_sch') for n in sheet_names]]:
        text = path.read_text(encoding='utf-8'); texts[path] = text
        tree = sx.loads(text)
        document = '_root' if path == root_path else path.stem
        def walk(node, key):
            if not isinstance(node, list) or not node: return
            head = str(node[0])
            if head == 'lib_symbols': return
            if head == 'uuid':
                old = str(node[1]); new = str(uuid.uuid5(seed, key))
                if old in mapping and mapping[old] != new: raise ValueError('Ambiguous UUID definition')
                mapping[old] = new
                return
            for i, child in enumerate(node):
                if isinstance(child, list): walk(child, key+'/'+str(i))
        for i, obj in enumerate(tree):
            if not isinstance(obj, list) or not obj: continue
            head = str(obj[0]); key = document+'/'+str(i)
            if head == 'uuid': key = document+'/document'
            elif head == 'symbol':
                props = {str(n[1]):str(n[2]) for n in obj if isinstance(n,list) and str(n[0])=='property'}
                units = [str(n[1]) for n in obj if isinstance(n,list) and str(n[0])=='unit']
                if 'Reference' in props and units: key = document+'/symbol/'+props['Reference']+'/'+units[0]
            elif head == 'sheet':
                props = {str(n[1]):str(n[2]) for n in obj if isinstance(n,list) and str(n[0])=='property'}
                key = document+'/sheet/'+props['Sheetfile']
            walk(obj, key)
    pattern = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
    for path,text in texts.items():
        path.write_text(pattern.sub(lambda m: mapping.get(m[0],m[0]), text), encoding='utf-8')


# SBC-1 change: field positions per symbol where the stock library positions collide with this generator's labels.
# (name, dx, dy, rotation, justify-left) relative to the symbol anchor, schematic coordinates (y down).
_VERT2 = [("Reference", 2.54, 0.0, 90, False), ("Value", 4.445, 0.0, 90, False)]
_FIELD_RULES = {
    "Device:R": _VERT2, "Device:FerriteBead": [("Reference", 4.4, 0.0, 90, False), ("Value", 6.3, 0.0, 90, False)],
    "Connector_Generic:Conn_01x02": [("Reference", 2.8, 0.0, 0, True), ("Value", 0.0, -3.6, 0, False)],
    "Connector_Generic:Conn_01x03": [("Reference", 2.8, 0.0, 0, True), ("Value", 0.0, -4.9, 0, False)],
    "Connector_Generic:Conn_01x04": [("Reference", 2.8, 1.27, 0, True), ("Value", 0.0, -4.9, 0, False)],
    "Interface_USB:CH340N": [("Reference", 2.0, 9.2, 0, True), ("Value", 2.0, 10.9, 0, True)],
    "Regulator_Switching:TLV62569DBV": [("Reference", 2.0, 5.6, 0, True), ("Value", 2.0, 7.3, 0, True)], "Device:Polyfuse": _VERT2, "Device:L": _VERT2,
    "Power_Protection:USBLC6-2SC6": [("Reference", 1.8, -6.6, 0, True), ("Value", 1.8, -4.8, 0, True)],
    "Power_Protection:ESDA6V1-5SC6": [("Reference", 7.8, 1.0, 0, True), ("Value", 7.8, -1.0, 0, True)],
    "Jumper:SolderJumper_3_Open": [("Reference", 0.0, -3.2, 0, False), ("Value", 3.2, 3.0, 0, True)],
    "Switch:SW_Push": [("Reference", 0.0, 2.8, 0, False), ("Value", 0.0, -4.2, 0, False)],
    "Switch:SW_DIP_x04": [("Reference", 0.0, -8.6, 0, False), ("Value", 0.0, 7.3, 0, False)],
    "Connector:TestPoint": [("Reference", 1.6, -4.6, 0, True), ("Value", 1.6, -2.9, 0, True)],
}


def _place_fields(path):
    """Text-only edit of the saved sheet: move Reference / Value per _FIELD_RULES (keeps text off bodies and labels)."""
    s = path.read_text(encoding="utf-8")
    out, pos = [], 0
    head = re.compile(r'\n\t\(symbol\n\t\t\(lib_id "([^"]+)"\)\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)')
    for m in head.finditer(s):
        rules = _FIELD_RULES.get(m.group(1))
        if not rules:
            continue
        cx, cy = float(m.group(2)), float(m.group(3))
        end = s.find("\n\t)\n", m.end())
        blk = s[m.start():end]
        for name, dx, dy, rot, left in rules:
            i = blk.find(f'(property "{name}"')
            if i < 0:
                continue
            j = blk.find("\n\t\t)", i)
            prop = blk[i:j]
            prop = re.sub(r'\(at [-\d.]+ [-\d.]+ [-\d.]+\)', f"(at {cx + dx:.3f} {cy + dy:.3f} {rot})", prop, count=1)
            prop = re.sub(r'\n\t\t\t\t\(justify [a-z ]+\)', "", prop)
            if left:
                prop = prop.replace("(size 1.27 1.27)\n\t\t\t\t)", "(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left)", 1)
            blk = blk[:i] + prop + blk[j:]
        out.append(s[pos:m.start()])
        out.append(blk)
        pos = end
    out.append(s[pos:])
    path.write_text("".join(out), encoding="utf-8")


def build(design, proj_name, out_dir: Path, sheet_titles: dict, paper_for=lambda n: "A3", flags=(),
          *, revision="A", uuid_namespace=None, symbol_library=None, company="Skee-Ball lane controller"):
    ksa.get_symbol_cache().add_library_path(str(symbol_library or ROOT / "hardware/lib/skeeball.kicad_sym"))
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for p in design.parts.values():
        sheets.setdefault(p.sheet, []).append(p)

    root = ksa.create_schematic(proj_name)
    root.set_title_block(title=proj_name, company=company, rev=revision)
    order = [s for s in sheet_titles if s in sheets] + [s for s in sheets if s not in sheet_titles]
    sheet_ids = {}
    for i, sname in enumerate(order):
        col, row = i % 4, i // 4
        su = root.add_sheet(name=sheet_titles.get(sname, sname), filename=f"{sname}.kicad_sch",
                            position=(25.4 + col * 60.96, 30.48 + row * 40.64), size=(50.8, 30.48),
                            project_name=proj_name, page_number=str(i + 2))
        sheet_ids[sname] = su
    root_path = out_dir / f"{proj_name}.kicad_sch"
    root.save(str(root_path))

    for sname in order:
        parts = sheets[sname]
        ch = ksa.create_schematic(sheet_titles.get(sname, sname))
        ch.set_hierarchy_context(root.uuid, sheet_ids[sname])
        n = sum(len(symbol_units(p.lib_id)) for p in parts)
        paper = paper_for(n)
        ch.set_paper_size(paper)
        pw = {"A4": 297, "A3": 420, "A2": 594, "A1": 841}[paper]
        blocks = [_text_block(sheet_titles.get(sname, sname), 12.7, 12.7, 3.0)]
        x, y, rowh = 20.32, 30.48, 0.0
        placed = []
        for p, unit, unit_pins in ((p, unit, pins) for p in parts for unit, pins in symbol_units(p.lib_id)):
            xs, ys = [xy[0] for _, xy in unit_pins], [xy[1] for _, xy in unit_pins]
            xmin, xmax = (min(xs), max(xs)) if xs else (0, 0)
            ymin, ymax = (min(ys), max(ys)) if ys else (0, 0)
            nets = list(p.conns.values())
            lab = max([len(n) for n in nets] + [3]) * 1.15 + 4.0
            pins = {pn for pn in p.conns}
            left_allow = lab if xmin < 0 or (xmin == xmax == 0) else 3.0
            right_allow = lab if xmax > 0 or (xmin == xmax == 0) else 3.0
            vert = (xmin == xmax)          # two-pin vertical parts: labels go up/down
            top_allow = lab if vert else 5.0
            bot_allow = lab if vert else 5.0
            w = (xmax - xmin) + left_allow + right_allow
            w = max(w, left_allow - xmin + len(p.value) * 1.1 + 4.0)   # SBC-1 change: room for a wide value text
            h = (ymax - ymin) + top_allow + bot_allow
            if x + w > pw - 20:
                x, y, rowh = 20.32, y + rowh + 7.62, 0.0
            cx, cy = snap(x + left_allow - xmin), snap(y + top_allow + ymax)
            from bom import resolve_mpn            # same resolution as the BOM: resistors get their ERJ MPN too
            mpn, mfr = resolve_mpn(p)
            props = {"MPN": mpn, "Manufacturer": mfr}
            props.update({k: v for k, v in p.fields.items() if v})
            if p.note:
                props["Note"] = p.note
            comp = ch.components.add(p.lib_id, reference=p.ref, value=p.value, position=(cx, cy),
                                     footprint=p.footprint, unit=unit, **{k: v for k, v in props.items() if v})
            if p.dnp:
                try:
                    comp.dnp = True
                except Exception:
                    pass
            placed.append((p, cx, cy, unit_pins))
            x += w + 2.54
            rowh = max(rowh, h)
        path = out_dir / f"{sname}.kicad_sch"
        ch.save(str(path))
        # labels
        for p, cx, cy, unit_pins in placed:
            for pin, (lx, ly, lrot) in unit_pins:
                net = p.conns.get(pin)
                if net is None:
                    continue
                px, py = cx + lx, cy - ly  # libraryY-up -> schematicY-down
                if net.startswith("NC_"):
                    blocks.append(_nc_block(px, py))
                    continue
                # SBC-1 change: the label points away from the body along the pin's own direction (library pin
                # rotation 0 = pin runs right into the body -> label to the left, etc.), not by position relative to
                # the symbol origin (that put corner pins' labels on top of each other, e.g. RP2350A GPIO0-3)
                ang = {0: 180, 180: 0, 90: 270, 270: 90}[int(round(lrot)) % 360]
                blocks.append(_label_block(net, px, py, ang))
        inject(path, blocks)
        _place_fields(path)
        _mark_dnp(path, {p.ref for p, _, _, _ in placed if p.dnp},
                  {p.ref for p, _, _, _ in placed if p.lib_id.startswith("Connector:TestPoint")})
    # PWR_FLAGs on the root sheet
    if flags:
        rs = ksa.load_schematic(str(root_path))
        fx = 25.4
        fblocks = []
        for i, net in enumerate(flags):
            ref = f"#FLG{i + 1:02d}"
            rs.components.add("power:PWR_FLAG", reference=ref, value="PWR_FLAG", position=(fx + i * 15.24, 170.18))
        rs.save(str(root_path))
        rs = ksa.load_schematic(str(root_path))
        for i, net in enumerate(flags):
            for pin, pt in rs.list_component_pins(f"#FLG{i + 1:02d}"):
                fblocks.append(_label_block(net, pt.x, pt.y, 270))
        inject(root_path, fblocks)
    if uuid_namespace:
        _stable_uuids(root_path, order, uuid_namespace)
    return root_path
