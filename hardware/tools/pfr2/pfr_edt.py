# ported from din-relay-8ch/tools/pfr2/pfr_edt.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Exact Euclidean distance transform (numba, nogil) for pfr2.py - a drop-in for scipy.ndimage.distance_transform_edt
on a 2-D boolean mask with unit sampling: the distance of every cell to the nearest ZERO (False) cell, as float64.

Felzenszwalb-Huttenlocher separable lower envelope on exact integer squared distances, so every value equals
scipy's sqrt(dy^2 + dx^2) bit for bit (both take the float64 sqrt of the same integer). pfr2-speed 2026-10-05:
scipy's feature-transform EDT was the legality hot spot (per unit and layer, per clearance group); this one is ~5x
faster and releases the GIL, so the legality warm-up threads really run in parallel.

  edt(mask) -> float64 (H, W)          (mask True = distance to compute, False = feature cells)
A mask without any False cell gets the same "infinite" treatment as scipy (scipy then measures to the virtual
border beyond the array; pfr2 never relies on that case: callers check .any() first) - see edt() below.
"""
import os
import numpy as np
from numba import njit

BIG = np.int64(1) << 40


@njit(cache=True, nogil=True)
def _edt1d(f, n, d, v, z):
    """1-D squared distance lower envelope (Felzenszwalb-Huttenlocher) of f[0:n] (int64, BIG = no feature) into d."""
    k = 0
    v[0] = 0
    z[0] = -1e30
    z[1] = 1e30
    for q in range(1, n):
        if f[q] >= BIG:
            continue
        if f[v[k]] >= BIG:
            v[k] = q
            continue
        while True:
            p = v[k]
            s = ((f[q] + q * q) - (f[p] + p * p)) / (2.0 * q - 2.0 * p)
            if s <= z[k]:
                k -= 1
                if k < 0:
                    k = 0
                    v[0] = q
                    z[0] = -1e30
                    z[1] = 1e30
                    break
                continue
            k += 1
            v[k] = q
            z[k] = s
            z[k + 1] = 1e30
            break
    if f[v[0]] >= BIG:                      # no feature on this line
        for q in range(n):
            d[q] = BIG
        return
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        p = v[k]
        d[q] = (q - p) * (q - p) + f[p]


@njit(cache=True, nogil=True)
def _sq_edt(mask):
    H, W = mask.shape
    g = np.empty((H, W), np.int64)
    n = max(H, W)
    f = np.empty(n, np.int64)
    d = np.empty(n, np.int64)
    v = np.empty(n, np.int64)
    z = np.empty(n + 1, np.float64)
    # columns
    for x in range(W):
        for y in range(H):
            f[y] = BIG if mask[y, x] else 0
        _edt1d(f, H, d, v, z)
        for y in range(H):
            g[y, x] = d[y]
    # rows
    for y in range(H):
        for x in range(W):
            f[x] = g[y, x]
        _edt1d(f, W, d, v, z)
        for x in range(W):
            g[y, x] = d[x]
    return g


@njit(cache=True, nogil=True)
def _sqrt_into(g, out):
    H, W = g.shape
    for y in range(H):
        for x in range(W):
            out[y, x] = np.sqrt(np.float64(g[y, x]))


CHECK = os.environ.get("PFR2_EDT_CHECK") == "1"    # debug: compare every call with scipy
SCIPY = os.environ.get("PFR2_SCIPY_EDT") == "1"      # verification switch: scipy's EDT (identical output, slower)


def edt(mask):
    """float64 exact EDT of a 2-D boolean mask (distance of each True cell to the nearest False cell; 0 on False)."""
    m = np.ascontiguousarray(mask, dtype=np.bool_)
    if SCIPY or m.size == 0 or m.all():
        from scipy import ndimage                    # no feature cell: scipy's own border semantics
        return ndimage.distance_transform_edt(m)
    g = _sq_edt(m)
    out = np.empty(m.shape, np.float64)
    _sqrt_into(g, out)
    if CHECK:
        from scipy import ndimage
        ref = ndimage.distance_transform_edt(m)
        if not np.array_equal(out, ref):
            np.save(os.environ.get("PFR2_EDT_DUMP", "edt_mismatch.npy"), m)
            raise AssertionError(f"pfr_edt mismatch on {m.shape}: max {np.abs(out - ref).max()}")
    return out
