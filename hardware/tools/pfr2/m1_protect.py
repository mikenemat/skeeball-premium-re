# ported from din-relay-8ch/tools/pfr2/m1_protect.py (Rule.why_protected API only), 2026-10-27
"""SBC-1 never-rip rule for the pfr2 tools (pour_stitch rips): the LOCKED copper (scripts/power_copper.py: +5V_IN trunk,
light rails / cathodes, the +5V_IN via array) is protected; everything else is router copper. DIN-8R's kinds (force /
HV, GND_ISO stitches, rail lanes, Kelvin, leg chains, NT1 tie, old base) do not exist on SBC-1."""


class Rule:
    def __init__(self, G, old_base=None):
        self.nets = {int(k): v for k, v in G["nets"].items()}

    def why_protected(self, kind, item):
        """None = not protected (may be ripped); else the reason"""
        return "locked (power_copper)" if item.get("locked") else None
