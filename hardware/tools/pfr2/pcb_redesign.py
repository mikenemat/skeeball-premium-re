# ported from din-relay-8ch/scripts/pcb_redesign.py (remove_saved_items only), 2026-10-27, for tools/pfr2
"""Native-text item removal by UUID (KiCad 10 SWIG Remove() corrupts / hangs)."""
import re


def remove_saved_items(text, uuids):
    """Delete complete native-serialized top-level nodes by exact UUID.

    Avoid KiCad10 Remove() SWIG corruption/teardown hangs. Quotes and escapes
    are parsed; UUIDs inside child pads/graphics cannot remove a parent item.
    """
    depth, quoted, escaped, start = 0, False, False, None
    ranges = []
    found = set()
    for index, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quoted and ch == '\\':
            escaped = True
            continue
        if ch == '"':
            quoted = not quoted
        if quoted:
            continue
        if ch == '(':
            if depth == 1:
                start = index
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 1 and start is not None:
                node = text[start:index+1]
                if re.match(r'\((footprint|segment|arc|via|zone|gr_line|gr_arc|gr_poly|gr_rect|gr_circle|gr_text)\b', node):
                    match = re.search(r'\(uuid "([^"]+)"\)', node)
                    if match and match[1] in uuids:
                        ranges.append((start, index+1))
                        found.add(match[1])
                start = None
    if depth != 0 or quoted or escaped:
        raise ValueError('Malformed native board serialization')
    if found != uuids:
        raise ValueError('Not every deletion UUID was uniquely matched: ' + str(sorted(uuids-found)))
    for begin, end in reversed(ranges):
        text = text[:begin] + text[end:]
    return text
