# ported from din-relay-8ch/tools/pfr2/native_constraints.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Read-only supplemental constraints omitted from legacy geometry dumps.

Native KiCad DRC remains authoritative. No project rule or native file is changed.
"""
import functools,os,re
from pathlib import Path
from shapely.geometry import Point,LineString
from shapely.affinity import rotate

@functools.lru_cache(maxsize=12)
def _pad_overrides(path,stamp):
    text=Path(path).read_text(encoding='utf-8');out={}
    fps=re.findall(r'(?ms)^\t\(footprint .*?^\t\)',text)
    if not fps:raise ValueError('Expected native-formatted KiCad footprints')
    for f in fps:
        parent=re.search(r'(?m)^\t\t\(clearance ([\d.eE+\-]+)\)',f)
        fc=float(parent.group(1)) if parent else 0.0
        for p in re.findall(r'(?ms)^\t\t\(pad .*?^\t\t\)',f):
            u=re.search(r'(?m)^\t\t\t\(uuid "([^"]+)"\)',p)
            if not u:raise ValueError('Pad UUID absent in native constraint read')
            c=re.search(r'(?m)^\t\t\t\(clearance ([\d.eE+\-]+)\)',p)
            out[u.group(1)]=max(fc,float(c.group(1)) if c else 0.0)
    return out

def pad_overrides(G):
    if 'pad_clearance_overrides' in G:return G['pad_clearance_overrides']
    path=os.path.normpath(os.path.abspath(G['board']))
    if os.path.normcase(os.path.commonpath([path,'C:/work']))!=os.path.normcase(os.path.normpath('C:/work')):
        raise ValueError('Native constraint access is restricted to C:/work')
    vals=_pad_overrides(path,Path(path).stat().st_mtime_ns)
    if any(p['uuid'] not in vals for p in G['pads']):raise ValueError('Native/geometry pad inventory mismatch')
    return vals

def npth_shape(p):
    if p.get('attr')!=3 or not p.get('drill'):return None
    dx,dy=p['drill'];r=min(dx,dy)/2;x,y=p['x'],p['y']
    if abs(dx-dy)<1e-9:return Point(x,y).buffer(r,32)
    extent=abs(dx-dy)/2
    ends=[(x-extent,y),(x+extent,y)] if dx>dy else [(x,y-extent),(x,y+extent)]
    return rotate(LineString(ends).buffer(r,32),-p.get('rot',0),origin=(x,y))
