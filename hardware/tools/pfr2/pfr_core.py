# ported from din-relay-8ch/tools/pfr2/pfr_core.py, 2026-10-27 (SBC-1 board model adapted; see docs/ROUTING_PLAYBOOK.md)
"""Numba kernels for the DIN8R grid router (pfr.py): multi-source / multi-target A* on a (layer, y, x) grid with
through vias, and halo stamping for negotiated congestion.

Grid conventions: arrays shaped (NL, H, W) over the routing layers; node id = (l * H + y) * W + x.
"""
import numpy as np
from numba import njit

INF = np.float32(1e30)
DX = np.array([1, -1, 0, 0, 1, 1, -1, -1], dtype=np.int64)
DY = np.array([0, 0, 1, -1, 1, -1, 1, -1], dtype=np.int64)
DC = np.array([1.0, 1.0, 1.0, 1.0, 1.41421356, 1.41421356, 1.41421356, 1.41421356], dtype=np.float32)


@njit(cache=True, nogil=True)
def _heap_push(hk, hv, n, key, val):
    i = n
    hk[i] = key
    hv[i] = val
    while i > 0:
        p = (i - 1) >> 1
        if hk[p] <= hk[i]:
            break
        hk[p], hk[i] = hk[i], hk[p]
        hv[p], hv[i] = hv[i], hv[p]
        i = p
    return n + 1


@njit(cache=True, nogil=True)
def _heap_pop(hk, hv, n):
    key, val = hk[0], hv[0]
    n -= 1
    hk[0] = hk[n]
    hv[0] = hv[n]
    i = 0
    while True:
        l = 2 * i + 1
        if l >= n:
            break
        r = l + 1
        m = l if (r >= n or hk[l] <= hk[r]) else r
        if hk[i] <= hk[m]:
            break
        hk[i], hk[m] = hk[m], hk[i]
        hv[i], hv[m] = hv[m], hv[i]
        i = m
    return key, val, n


@njit(cache=True, nogil=True)
def astar(trace_ok, via_ok, cost_t, cost_v, src, tgt, lay_allowed, via_cost, tbox, max_expand):
    """trace_ok (NL,H,W) bool, via_ok (H,W) bool, cost_t (NL,H,W) float32 per-cell multiplier (>= 1),
    cost_v (H,W) float32 via multiplier, src / tgt (NL,H,W) bool, lay_allowed (NL,) bool.
    tbox = (y0, x0, y1, x1) of the target cells (heuristic). Returns the path as node ids (target -> source) or empty."""
    NL, H, W = trace_ok.shape
    N = NL * H * W
    g = np.full(N, INF, dtype=np.float32)
    par = np.full(N, -1, dtype=np.int64)
    closed = np.zeros(N, dtype=np.bool_)
    cap = min(N, 1 << 25)                 # heap sized to the window (finer grids need more than 4M entries)
    hk = np.empty(cap, dtype=np.float32)
    hv = np.empty(cap, dtype=np.int64)
    n = 0
    ty0, tx0, ty1, tx1 = tbox
    for l in range(NL):
        if not lay_allowed[l]:
            continue
        for y in range(H):
            for x in range(W):
                if src[l, y, x]:
                    v = (l * H + y) * W + x
                    g[v] = 0.0
                    dy = max(ty0 - y, 0, y - ty1)
                    dx = max(tx0 - x, 0, x - tx1)
                    h = max(dx, dy) + 0.41421356 * min(dx, dy)
                    if n < cap:
                        n = _heap_push(hk, hv, n, np.float32(h), v)
    expanded = 0
    goal = -1
    while n > 0:
        key, v, n = _heap_pop(hk, hv, n)
        if closed[v]:
            continue
        closed[v] = True
        expanded += 1
        if expanded > max_expand:
            break
        l = v // (H * W)
        rem = v - l * H * W
        y = rem // W
        x = rem - y * W
        if tgt[l, y, x]:
            goal = v
            break
        gv = g[v]
        for k in range(8):
            nx = x + DX[k]
            ny = y + DY[k]
            if nx < 0 or ny < 0 or nx >= W or ny >= H:
                continue
            if not trace_ok[l, ny, nx]:
                continue
            if k >= 4 and not (trace_ok[l, y, nx] or trace_ok[l, ny, x]):
                continue          # no diagonal squeeze between two blocked cells
            u = (l * H + ny) * W + nx
            if closed[u]:
                continue
            ng = gv + DC[k] * cost_t[l, ny, nx]
            if ng < g[u]:
                g[u] = ng
                par[u] = v
                dy = max(ty0 - ny, 0, ny - ty1)
                dx = max(tx0 - nx, 0, nx - tx1)
                h = max(dx, dy) + 0.41421356 * min(dx, dy)
                if n < cap:
                    n = _heap_push(hk, hv, n, np.float32(ng + h), u)
        if via_ok[y, x]:
            vc = via_cost * cost_v[y, x]
            for l2 in range(NL):
                if l2 == l or not lay_allowed[l2] or not trace_ok[l2, y, x]:
                    continue
                u = (l2 * H + y) * W + x
                if closed[u]:
                    continue
                ng = gv + vc
                if ng < g[u]:
                    g[u] = ng
                    par[u] = v
                    dy = max(ty0 - y, 0, y - ty1)
                    dx = max(tx0 - x, 0, x - tx1)
                    h = max(dx, dy) + 0.41421356 * min(dx, dy)
                    if n < cap:
                        n = _heap_push(hk, hv, n, np.float32(ng + h), u)
    if goal < 0:
        return np.empty(0, dtype=np.int64), expanded
    out = []
    v = goal
    while v >= 0:
        out.append(v)
        v = par[v]
    return np.array(out, dtype=np.int64), expanded


@njit(cache=True, nogil=True)
def stamp(grid, ys, xs, offy, offx, val):
    """grid[y+offy, x+offx] += val for every (y, x) in (ys, xs) - unique cells per stamp call. The dedup mask covers
    only the stamp's bounding box (a full-board mask per call cost ~8 MB of zeroing each time)."""
    H, W = grid.shape
    if ys.shape[0] == 0:
        return
    y0 = ys.min() + offy.min()
    y1 = ys.max() + offy.max()
    x0 = xs.min() + offx.min()
    x1 = xs.max() + offx.max()
    mark = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.bool_)
    for i in range(ys.shape[0]):
        for k in range(offy.shape[0]):
            yy = ys[i] + offy[k]
            xx = xs[i] + offx[k]
            if 0 <= yy < H and 0 <= xx < W and not mark[yy - y0, xx - x0]:
                mark[yy - y0, xx - x0] = True
                grid[yy, xx] += val


@njit(cache=True, nogil=True)
def astar_ws(trace_ok, via_ok, cost_t, cost_v, src, tgt, lay_allowed, via_cost, tbox, max_expand,
             g, par, closed, hk, hv, touched, hw, hmap, use_h):
    """astar() on caller-owned work buffers (pfr2-speed): g (>= N, all INF), par (>= N, all -1), closed (>= N, all
    False), hk / hv (>= min(N, 2^25)), touched (>= N). Every node whose g leaves INF is recorded in touched and reset
    before returning, so the buffers are clean again for the next call: no O(N) allocation / fill per call (a
    whole-board window is 32 M nodes, ~1 GB of fresh arrays per astar() call). Same search, same tie order, same
    result as astar(). hw: heuristic weight (pfr2 --c2f coarse grid: 2, every coarse step costs >= 2 x its length,
    so the weighted octile bound stays admissible and consistent there). use_h: the heuristic is hw x hmap[y, x]
    (pfr2 --c2f: the Euclidean distance to the NEAREST target cell - the octile distance to the target BBOX is ~0
    for a big tree inside the bbox of its remaining components, and the search degenerates to Dijkstra)."""
    NL, H, W = trace_ok.shape
    N = NL * H * W
    cap = min(N, 1 << 25)
    n = 0
    nt = 0
    ty0, tx0, ty1, tx1 = tbox
    for l in range(NL):
        if not lay_allowed[l]:
            continue
        for y in range(H):
            for x in range(W):
                if src[l, y, x]:
                    v = (l * H + y) * W + x
                    if g[v] >= INF:
                        touched[nt] = v
                        nt += 1
                    g[v] = 0.0
                    dy = max(ty0 - y, 0, y - ty1)
                    dx = max(tx0 - x, 0, x - tx1)
                    h = hw * hmap[y, x] if use_h else hw * (max(dx, dy) + 0.41421356 * min(dx, dy))
                    if n < cap:
                        n = _heap_push(hk, hv, n, np.float32(h), v)
    expanded = 0
    goal = -1
    while n > 0:
        key, v, n = _heap_pop(hk, hv, n)
        if closed[v]:
            continue
        closed[v] = True
        expanded += 1
        if expanded > max_expand:
            break
        l = v // (H * W)
        rem = v - l * H * W
        y = rem // W
        x = rem - y * W
        if tgt[l, y, x]:
            goal = v
            break
        gv = g[v]
        for k in range(8):
            nx = x + DX[k]
            ny = y + DY[k]
            if nx < 0 or ny < 0 or nx >= W or ny >= H:
                continue
            if not trace_ok[l, ny, nx]:
                continue
            if k >= 4 and not (trace_ok[l, y, nx] or trace_ok[l, ny, x]):
                continue          # no diagonal squeeze between two blocked cells
            u = (l * H + ny) * W + nx
            if closed[u]:
                continue
            ng = gv + DC[k] * cost_t[l, ny, nx]
            if ng < g[u]:
                if g[u] >= INF:
                    touched[nt] = u
                    nt += 1
                g[u] = ng
                par[u] = v
                dy = max(ty0 - ny, 0, ny - ty1)
                dx = max(tx0 - nx, 0, nx - tx1)
                h = hw * hmap[ny, nx] if use_h else hw * (max(dx, dy) + 0.41421356 * min(dx, dy))
                if n < cap:
                    n = _heap_push(hk, hv, n, np.float32(ng + h), u)
        if via_ok[y, x]:
            vc = via_cost * cost_v[y, x]
            for l2 in range(NL):
                if l2 == l or not lay_allowed[l2] or not trace_ok[l2, y, x]:
                    continue
                u = (l2 * H + y) * W + x
                if closed[u]:
                    continue
                ng = gv + vc
                if ng < g[u]:
                    if g[u] >= INF:
                        touched[nt] = u
                        nt += 1
                    g[u] = ng
                    par[u] = v
                    dy = max(ty0 - y, 0, y - ty1)
                    dx = max(tx0 - x, 0, x - tx1)
                    h = hw * hmap[y, x] if use_h else hw * (max(dx, dy) + 0.41421356 * min(dx, dy))
                    if n < cap:
                        n = _heap_push(hk, hv, n, np.float32(ng + h), u)
    if goal < 0:
        out = np.empty(0, dtype=np.int64)
    else:
        cnt = 0
        v = goal
        while v >= 0:
            cnt += 1
            v = par[v]
        out = np.empty(cnt, dtype=np.int64)
        v = goal
        i = 0
        while v >= 0:
            out[i] = v
            i += 1
            v = par[v]
    for i in range(nt):
        u = touched[i]
        g[u] = INF
        par[u] = -1
        closed[u] = False
    return out, expanded


@njit(cache=True, nogil=True)
def down_any(m, Hc, Wc):
    """(NL, H, W) bool -> (NL, Hc, Wc) bool: a coarse cell is set when any of its 2 x 2 fine cells is (pfr2 --c2f)"""
    NL, H, W = m.shape
    out = np.zeros((NL, Hc, Wc), np.bool_)
    for l in range(NL):
        for y in range(H):
            yc = y >> 1
            for x in range(W):
                if m[l, y, x]:
                    out[l, yc, x >> 1] = True
    return out


@njit(cache=True, nogil=True)
def coarsen_prep(t_ok, v_ok, ct, cv, Hc, Wc):
    """coarse legality (any fine cell legal) and costs (2 x the cheapest legal fine cell; 1 where nothing is legal)"""
    NL, H, W = t_ok.shape
    t_c = np.zeros((NL, Hc, Wc), np.bool_)
    c_c = np.full((NL, Hc, Wc), np.float32(3e38), np.float32)
    v_c = np.zeros((Hc, Wc), np.bool_)
    cv_c = np.full((Hc, Wc), np.float32(3e38), np.float32)
    for l in range(NL):
        for y in range(H):
            yc = y >> 1
            for x in range(W):
                if t_ok[l, y, x]:
                    xc = x >> 1
                    t_c[l, yc, xc] = True
                    if ct[l, y, x] < c_c[l, yc, xc]:
                        c_c[l, yc, xc] = ct[l, y, x]
    for l in range(NL):
        for yc in range(Hc):
            for xc in range(Wc):
                c_c[l, yc, xc] = c_c[l, yc, xc] * np.float32(2.0) if t_c[l, yc, xc] else np.float32(1.0)
    for y in range(H):
        yc = y >> 1
        for x in range(W):
            if v_ok[y, x]:
                xc = x >> 1
                v_c[yc, xc] = True
                if cv[y, x] < cv_c[yc, xc]:
                    cv_c[yc, xc] = cv[y, x]
    for yc in range(Hc):
        for xc in range(Wc):
            if not v_c[yc, xc]:
                cv_c[yc, xc] = np.float32(1.0)
    return t_c, v_c, c_c, cv_c


@njit(cache=True, nogil=True)
def corridor(cy, cx, H, W, rc, ends_y, ends_x, rp):
    """fine (H, W) corridor: every fine cell within rc coarse cells (square) of a coarse path cell, plus a square of
    rp fine cells around each given fine end point (pin escapes)"""
    corr = np.zeros((H, W), np.bool_)
    for k in range(cy.shape[0]):
        y0 = max(0, 2 * (cy[k] - rc))
        y1 = min(H, 2 * (cy[k] + rc) + 2)
        x0 = max(0, 2 * (cx[k] - rc))
        x1 = min(W, 2 * (cx[k] + rc) + 2)
        for y in range(y0, y1):
            for x in range(x0, x1):
                corr[y, x] = True
    for k in range(ends_y.shape[0]):
        for y in range(max(0, ends_y[k] - rp), min(H, ends_y[k] + rp + 1)):
            for x in range(max(0, ends_x[k] - rp), min(W, ends_x[k] + rp + 1)):
                corr[y, x] = True
    return corr


@njit(cache=True, nogil=True)
def mask_layers(t_ok, corr):
    NL, H, W = t_ok.shape
    out = np.zeros((NL, H, W), np.bool_)
    for l in range(NL):
        for y in range(H):
            for x in range(W):
                out[l, y, x] = t_ok[l, y, x] and corr[y, x]
    return out


@njit(cache=True, nogil=True)
def octile_dt(tgt2):
    """(H, W) bool -> float32 octile distance (steps 1 / sqrt 2) of every cell to the nearest True cell (two-pass
    chamfer, exact for the 8-neighbour octile metric): the --c2f A* heuristic map - the same metric and tie
    behaviour as the octile-to-bbox bound, without its blindness inside the targets' bbox."""
    H, W = tgt2.shape
    D = np.full((H, W), np.float32(1e30), np.float32)
    S2 = np.float32(1.41421356)
    for y in range(H):
        for x in range(W):
            if tgt2[y, x]:
                D[y, x] = 0.0
    for y in range(H):
        for x in range(W):
            d = D[y, x]
            if x > 0 and D[y, x - 1] + 1.0 < d:
                d = D[y, x - 1] + np.float32(1.0)
            if y > 0:
                if D[y - 1, x] + 1.0 < d:
                    d = D[y - 1, x] + np.float32(1.0)
                if x > 0 and D[y - 1, x - 1] + S2 < d:
                    d = D[y - 1, x - 1] + S2
                if x + 1 < W and D[y - 1, x + 1] + S2 < d:
                    d = D[y - 1, x + 1] + S2
            D[y, x] = d
    for y in range(H - 1, -1, -1):
        for x in range(W - 1, -1, -1):
            d = D[y, x]
            if x + 1 < W and D[y, x + 1] + 1.0 < d:
                d = D[y, x + 1] + np.float32(1.0)
            if y + 1 < H:
                if D[y + 1, x] + 1.0 < d:
                    d = D[y + 1, x] + np.float32(1.0)
                if x + 1 < W and D[y + 1, x + 1] + S2 < d:
                    d = D[y + 1, x + 1] + S2
                if x > 0 and D[y + 1, x - 1] + S2 < d:
                    d = D[y + 1, x - 1] + S2
            D[y, x] = d
    return D


@njit(cache=True, nogil=True)
def down_region(dst, m, y0, y1, x0, x1, reset):
    """coarse dst[:, y0//2 .. , x0//2 ..] from fine m over the fine rows y0..y1-1 / cols x0..x1-1 (expanded to whole
    coarse cells): reset = recompute those coarse cells exactly, else OR the fine cells in"""
    NL, H, W = m.shape
    ya, yb = (y0 // 2) * 2, min(H, ((y1 + 1) // 2) * 2)
    xa, xb = (x0 // 2) * 2, min(W, ((x1 + 1) // 2) * 2)
    if reset:
        for l in range(NL):
            for yc in range(ya // 2, (yb + 1) // 2):
                for xc in range(xa // 2, (xb + 1) // 2):
                    dst[l, yc, xc] = False
    for l in range(NL):
        for y in range(ya, yb):
            for x in range(xa, xb):
                if m[l, y, x]:
                    dst[l, y >> 1, x >> 1] = True


@njit(cache=True, nogil=True)
def corridor_sub(cy, cx, Hs, Ws, oy, ox, rc, ends_y, ends_x, rp):
    """corridor() on the fine sub-window [oy, oy + Hs) x [ox, ox + Ws)"""
    corr = np.zeros((Hs, Ws), np.bool_)
    for k in range(cy.shape[0]):
        y0 = max(0, 2 * (cy[k] - rc) - oy)
        y1 = min(Hs, 2 * (cy[k] + rc) + 2 - oy)
        x0 = max(0, 2 * (cx[k] - rc) - ox)
        x1 = min(Ws, 2 * (cx[k] + rc) + 2 - ox)
        for y in range(y0, y1):
            for x in range(x0, x1):
                corr[y, x] = True
    for k in range(ends_y.shape[0]):
        for y in range(max(0, ends_y[k] - rp - oy), min(Hs, ends_y[k] + rp + 1 - oy)):
            for x in range(max(0, ends_x[k] - rp - ox), min(Ws, ends_x[k] + rp + 1 - ox)):
                corr[y, x] = True
    return corr
