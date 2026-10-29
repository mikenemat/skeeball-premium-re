# ported from din-relay-8ch/tools/pfr2/rip_region.py (constants only), 2026-10-27, for rip_local.py
"""SBC-1 rip constants: the whole board is the rip region; no keep-nets / keep-classes beyond LOCKED copper (rip_local
skips locked items) and the PowerLight class (all locked power_copper)."""
from shapely.geometry import box

REGION = box(-1.0, -1.0, 118.0, 87.0)
KEEP_CLASSES = {"PowerLight"}
KEEP_NETS = set()
