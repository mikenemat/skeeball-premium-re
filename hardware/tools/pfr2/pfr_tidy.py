# ported from din-relay-8ch/tools/pfr2/pfr_tidy.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Octilinear pull-tight of one same-layer grid run (numba; pfr2.py tidiness at the source, pfr2-up 2026-10-05).

The A* in pfr_core returns an 8-connected cell path whose equal-cost ties make 0.05 mm staircases (E, NE, E, NE ...)
and, after negotiation moves a blocker away, small detour loops. tidy_run() re-draws one run between its fixed ends
(pad / via / target cells) as a chain of one-bend octilinear connections (a 45 deg leg + a 0 / 90 deg leg) through the
farthest reachable anchors of the original path, then removes short opposite-turn steps (qa_copper_landing TRACK-JOG:
a segment shorter than JOG_W x width between two bends of opposite turn) where a wider one-bend re-fit is legal.

Legality is the caller's boolean mask `ok` (H, W) in window cells: every cell a track centre may occupy (pfr2: nominal-
width legal | own copper, minus other nets' negotiated halos, plus the original path cells). A diagonal step needs one
of its two orthogonal neighbours legal (the A* squeeze rule). The result never has more cells than the input + the two
optional centre anchors.
"""
import numpy as np
from numba import njit

SQ2 = 1.41421356


@njit(cache=True, nogil=True)
def _sgn(v):
    return 1 if v > 0 else (-1 if v < 0 else 0)


@njit(cache=True, nogil=True)
def _legs(y0, x0, y1, x1, mode):
    """one-bend octilinear from (y0, x0) to (y1, x1): mode 0 diagonal leg first, 1 straight leg first.
    -> (ly1, lx1, n1, ly2, lx2, n2)"""
    dy = y1 - y0
    dx = x1 - x0
    ady = abs(dy)
    adx = abs(dx)
    d = min(ady, adx)
    s = max(ady, adx) - d
    sy = _sgn(dy)
    sx = _sgn(dx)
    if ady > adx:
        ty, tx = sy, 0
    else:
        ty, tx = 0, sx
    if mode == 0:
        return sy, sx, d, ty, tx, s
    return ty, tx, s, sy, sx, d


@njit(cache=True, nogil=True)
def _leg_ok(ok, y, x, ly, lx, n):
    for k in range(n):
        ny = y + ly
        nx = x + lx
        if not ok[ny, nx]:
            return False
        if ly != 0 and lx != 0 and not (ok[y, nx] or ok[ny, x]):
            return False
        y = ny
        x = nx
    return True


@njit(cache=True, nogil=True)
def conn_ok(ok, y0, x0, y1, x1, mode):
    a = _legs(y0, x0, y1, x1, mode)
    if not _leg_ok(ok, y0, x0, a[0], a[1], a[2]):
        return False
    return _leg_ok(ok, y0 + a[0] * a[2], x0 + a[1] * a[2], a[3], a[4], a[5])


@njit(cache=True, nogil=True)
def _jog_at(vy, vx, nv, k, jogc):
    """segment k (v[k] -> v[k+1]) is a staircase step: shorter than jogc (cell units, diagonal x sqrt 2) between two
    bends of opposite turn"""
    if k < 1 or k + 2 > nv - 1:
        return False
    dy = vy[k + 1] - vy[k]
    dx = vx[k + 1] - vx[k]
    n = max(abs(dy), abs(dx))
    ln = n * (SQ2 if (dy != 0 and dx != 0) else 1.0)
    if ln >= jogc:
        return False
    ay = vy[k] - vy[k - 1]
    ax = vx[k] - vx[k - 1]
    by = vy[k + 2] - vy[k + 1]
    bx = vx[k + 2] - vx[k + 1]
    t1 = ax * dy - ay * dx
    t2 = dx * by - dy * bx
    return t1 != 0 and t2 != 0 and (t1 > 0) != (t2 > 0)


@njit(cache=True, nogil=True)
def _count_jogs(vy, vx, nv, jogc):
    c = 0
    for k in range(1, nv - 2):
        if _jog_at(vy, vx, nv, k, jogc):
            c += 1
    return c


@njit(cache=True, nogil=True)
def _merge(vy, vx, nv):
    """drop zero-length and collinear interior vertices (in place) -> new count"""
    m = 1
    for k in range(1, nv):
        if vy[k] == vy[m - 1] and vx[k] == vx[m - 1]:
            continue
        if m >= 2:
            ay = _sgn(vy[m - 1] - vy[m - 2])
            ax = _sgn(vx[m - 1] - vx[m - 2])
            by = _sgn(vy[k] - vy[m - 1])
            bx = _sgn(vx[k] - vx[m - 1])
            if ay == by and ax == bx:
                vy[m - 1] = vy[k]
                vx[m - 1] = vx[k]
                continue
        vy[m] = vy[k]
        vx[m] = vx[k]
        m += 1
    return m


@njit(cache=True, nogil=True)
def _sharp(ay, ax, by, bx):
    """a turn of more than 90 deg between direction a and the next direction b (interior angle < 90: ACUTE / FOLD)"""
    return ay * by + ax * bx < 0


@njit(cache=True, nogil=True)
def _count_sharp(vy, vx, nv):
    c = 0
    for k in range(1, nv - 1):
        if _sharp(vy[k] - vy[k - 1], vx[k] - vx[k - 1], vy[k + 1] - vy[k], vx[k + 1] - vx[k]):
            c += 1
    return c


@njit(cache=True, nogil=True)
def _exit_ok(ly, lx, n, exx, exy):
    """a straight pad-exit leg: along x needs n >= exx (exx < 0: x forbidden), along y n >= exy"""
    if n <= 0 or (ly != 0 and lx != 0):
        return False
    if lx != 0:
        return exx >= 0 and n >= exx
    return exy >= 0 and n >= exy


@njit(cache=True, nogil=True)
def _turn_bad(ay, ax, by, bx):
    return _sharp(ay, ax, by, bx)


@njit(cache=True, nogil=True)
def fix_exit_turn(vy, vx, nv, ok, smax):
    """tidy step 2 (pfr2-speed): the joint right after a constrained pad-exit leg (v0 -> v1) turns back by more than
    90 deg (ACUTE / TRACK-FOLD): replace it - keeping the exit leg - by a 90 deg step sideways (toward the side the
    run continues to) of 1..smax cells followed by a one-bend connection to a later vertex, so that no joint of the new
    stretch turns by more than 90 deg (90 + 45 or 45 + 45 instead of one turn-back). -> new vertex count (in place)."""
    if nv < 3:
        return nv
    dy0 = _sgn(vy[1] - vy[0])
    dx0 = _sgn(vx[1] - vx[0])
    d1y = vy[2] - vy[1]
    d1x = vx[2] - vx[1]
    if not _sharp(dy0, dx0, d1y, d1x):
        return nv
    cr = dy0 * d1x - dx0 * d1y                   # side the run continues to (cross product sign)
    for side in range(2):
        sg = (1 if cr >= 0 else -1) * (1 if side == 0 else -1)
        py = -dx0 * sg                            # the 90 deg turn of (dy0, dx0) to that side
        px = dy0 * sg
        if py == 0 and px == 0:
            continue
        for t in range(1, smax + 1):
            qy = vy[1] + py * t
            qx = vx[1] + px * t
            if not _leg_ok(ok, vy[1], vx[1], py, px, t):
                break
            for b in range(2, min(nv, 8)):
                for mode in range(2):
                    if not conn_ok(ok, qy, qx, vy[b], vx[b], mode):
                        continue
                    a = _legs(qy, qx, vy[b], vx[b], mode)
                    fy, fx = (a[0], a[1]) if a[2] > 0 else (a[3], a[4])
                    if (fy == 0 and fx == 0) or _sharp(py, px, fy, fx):
                        continue
                    ly, lx = (a[3], a[4]) if a[5] > 0 else (a[0], a[1])
                    if b + 1 < nv and _sharp(ly, lx, vy[b + 1] - vy[b], vx[b + 1] - vx[b]):
                        continue
                    # rebuild: v0, v1, q, [bend], v[b], ...
                    tmy = np.empty(nv + 3, np.int64)
                    tmx = np.empty(nv + 3, np.int64)
                    m = 0
                    tmy[m] = vy[0]
                    tmx[m] = vx[0]
                    m += 1
                    tmy[m] = vy[1]
                    tmx[m] = vx[1]
                    m += 1
                    tmy[m] = qy
                    tmx[m] = qx
                    m += 1
                    if a[2] > 0 and a[5] > 0:
                        tmy[m] = qy + a[0] * a[2]
                        tmx[m] = qx + a[1] * a[2]
                        m += 1
                    for k in range(b, nv):
                        tmy[m] = vy[k]
                        tmx[m] = vx[k]
                        m += 1
                    if m > vy.shape[0]:
                        continue
                    m = _merge(tmy, tmx, m)
                    if _count_sharp(tmy, tmx, m) >= _count_sharp(vy, vx, nv):
                        continue
                    for k in range(m):
                        vy[k] = tmy[k]
                        vx[k] = tmx[k]
                    return m
    return nv


@njit(cache=True, nogil=True)
def tidy_run(ys, xs, ok, jmax, jogc, ex0x, ex0y, ex1x, ex1y):
    """ys, xs: int64 cell path of one run (fixed ends); ok: bool (H, W).
    ex0x / ex0y (ex1x / ex1y): when either is > 0 the run starts (ends) at a pad CENTRE and must leave (enter) it with
    a straight leg of at least that many cells along x / y (-1: that axis is not the pad's long axis) - PAD-AXIS; a
    constrained end that cannot be met falls back to the free pull. No joint turns by more than 90 deg where an
    alternative exists (ACUTE / TRACK-FOLD). -> (ys2, xs2, n_jogs_before, n_jogs_after)"""
    m = ys.shape[0]
    if m < 3:
        return ys.copy(), xs.copy(), 0, 0
    cap = 2 * m + 8
    vy = np.empty(cap, np.int64)
    vx = np.empty(cap, np.int64)
    ry = ys.copy()
    rx = xs.copy()
    nr = _merge(ry, rx, m)
    j0 = _count_jogs(ry, rx, nr, jogc)
    c0 = ex0x > 0 or ex0y > 0
    c1 = ex1x > 0 or ex1y > 0
    vy[0] = ys[0]
    vx[0] = xs[0]
    nv = 1
    i = 0
    ldy = 0
    ldx = 0
    while i < m - 1:
        bj = i + 1
        bm = -1
        jend = min(m - 1, i + jmax)
        for strict in range(2):
            for j in range(jend, i, -1):
                a = _legs(ys[i], xs[i], ys[j], xs[j], 0)
                pref = 0 if (a[0] == ldy and a[1] == ldx) else 1
                for t in range(2):
                    mode = pref if t == 0 else 1 - pref
                    a = _legs(ys[i], xs[i], ys[j], xs[j], mode)
                    if strict == 0:
                        if i == 0 and c0 and not (mode == 1 and _exit_ok(a[0], a[1], a[2], ex0x, ex0y)):
                            continue
                        if j == m - 1 and c1 and not (mode == 0 and _exit_ok(a[3], a[4], a[5], ex1x, ex1y)):
                            continue
                        fy, fx = (a[0], a[1]) if a[2] > 0 else (a[3], a[4])
                        if (ldy != 0 or ldx != 0) and _sharp(ldy, ldx, fy, fx):
                            continue
                    if conn_ok(ok, ys[i], xs[i], ys[j], xs[j], mode):
                        bj = j
                        bm = mode
                        break
                if bm >= 0:
                    break
            if bm >= 0:
                break
        if bm < 0:
            bm = 0                                   # the original step (always kept)
        a = _legs(ys[i], xs[i], ys[bj], xs[bj], bm)
        if a[2] > 0 and a[5] > 0:
            vy[nv] = ys[i] + a[0] * a[2]
            vx[nv] = xs[i] + a[1] * a[2]
            nv += 1
        vy[nv] = ys[bj]
        vx[nv] = xs[bj]
        nv += 1
        if a[5] > 0:
            ldy, ldx = a[3], a[4]
        elif a[2] > 0:
            ldy, ldx = a[0], a[1]
        i = bj
    nv = _merge(vy, vx, nv)
    # de-jog: re-fit a window of vertices around each staircase step / sharp turn with one bend when that lowers
    # (jogs + sharp turns); the constrained pad-exit / pad-entry legs are never re-fitted
    wy = np.empty(cap, np.int64)
    wx = np.empty(cap, np.int64)
    lo = 1 if c0 else 0
    for _ in range(200):
        cur = _count_jogs(vy, vx, nv, jogc) + _count_sharp(vy, vx, nv)
        if cur == 0:
            break
        improved = False
        for k in range(1, nv - 1):
            if not (_jog_at(vy, vx, nv, k, jogc) or _sharp(vy[k] - vy[k - 1], vx[k] - vx[k - 1],
                                                          vy[k + 1] - vy[k], vx[k + 1] - vx[k])):
                continue
            for w in range(4):
                a0 = k - 1 - (w & 1)
                b0 = k + 2 + (w >> 1)
                if a0 < lo or b0 > nv - 1 - (1 if c1 else 0):
                    continue
                for mode in range(2):
                    if not conn_ok(ok, vy[a0], vx[a0], vy[b0], vx[b0], mode):
                        continue
                    a = _legs(vy[a0], vx[a0], vy[b0], vx[b0], mode)
                    nw = 0
                    for q in range(a0 + 1):
                        wy[nw] = vy[q]
                        wx[nw] = vx[q]
                        nw += 1
                    if a[2] > 0 and a[5] > 0:
                        wy[nw] = vy[a0] + a[0] * a[2]
                        wx[nw] = vx[a0] + a[1] * a[2]
                        nw += 1
                    for q in range(b0, nv):
                        wy[nw] = vy[q]
                        wx[nw] = vx[q]
                        nw += 1
                    nw = _merge(wy, wx, nw)
                    if _count_jogs(wy, wx, nw, jogc) + _count_sharp(wy, wx, nw) < cur:
                        for q in range(nw):
                            vy[q] = wy[q]
                            vx[q] = wx[q]
                        nv = nw
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
        if not improved:
            break
    # tidy step 2: a turn-back right after a constrained pad-exit (or right before a pad-entry) leg is split into a
    # 90 deg step + a <= 90 deg connection (fix_exit_turn); the end is handled on the reversed vertex list
    if c0:
        nv = fix_exit_turn(vy, vx, nv, ok, 12)
    if c1:
        for k in range(nv // 2):
            vy[k], vy[nv - 1 - k] = vy[nv - 1 - k], vy[k]
            vx[k], vx[nv - 1 - k] = vx[nv - 1 - k], vx[k]
        nv = fix_exit_turn(vy, vx, nv, ok, 12)
        for k in range(nv // 2):
            vy[k], vy[nv - 1 - k] = vy[nv - 1 - k], vy[k]
            vx[k], vx[nv - 1 - k] = vx[nv - 1 - k], vx[k]
    j1 = _count_jogs(vy, vx, nv, jogc)
    tot = 1
    for k in range(nv - 1):
        tot += max(abs(vy[k + 1] - vy[k]), abs(vx[k + 1] - vx[k]))
    oy = np.empty(tot, np.int64)
    ox = np.empty(tot, np.int64)
    oy[0] = vy[0]
    ox[0] = vx[0]
    c = 1
    for k in range(nv - 1):
        sy = _sgn(vy[k + 1] - vy[k])
        sx = _sgn(vx[k + 1] - vx[k])
        n = max(abs(vy[k + 1] - vy[k]), abs(vx[k + 1] - vx[k]))
        y = vy[k]
        x = vx[k]
        for q in range(n):
            y += sy
            x += sx
            oy[c] = y
            ox[c] = x
            c += 1
    return oy, ox, j0, j1
