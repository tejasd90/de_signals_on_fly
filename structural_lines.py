#!/usr/bin/env python3
"""
structural_lines.py — trend lines the way a trader draws them.

WHY THE OLD ONES WERE WRONG
brooks_context.py least-squares-fits the last 4 fractal swings. On ETH daily at
2026-07-28 those four swings spanned 30 days and were ASCENDING, so the "bear
trend line" had a slope of +0.101 — a bull line. The multi-month descending line
from the 2025 highs, which is the actual structure, was invisible. That means R1
("trend line broken") was never really tested: it measured breaks of 30-day local
fits, not of the lines anyone draws.

WHAT THIS DOES INSTEAD
1. MAJOR swings only — a wider fractal window plus a prominence floor in ATR, so
   noise swings do not anchor a line.
2. A CONVEX HULL, not least squares. Brooks draws a bear line touching two highs
   with price staying below it; that is the upper hull of the swing highs, not a
   regression through them. A regression cuts through price and is broken
   constantly; a hull line is only broken when structure actually gives way.
3. Causal throughout: a swing at bar j is confirmed at j+k, and only hull points
   confirmed by bar i are used to draw the line in force at bar i.
"""
import numpy as np, pandas as pd


def atr_(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=2).mean().to_numpy()


def major_swings(h, l, k=5, min_prom=1.0, A=None):
    """Fractal extremes over a 2k+1 window, kept only if they stand out from the
    surrounding window by at least `min_prom` ATR. The prominence filter is what
    separates a structural pivot from a one-bar wiggle."""
    n = len(h)
    sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    for j in range(k, n - k):
        w_h = h[j - k:j + k + 1]; w_l = l[j - k:j + k + 1]
        a = A[j] if A is not None and np.isfinite(A[j]) and A[j] > 0 else 1.0
        if h[j] == w_h.max() and (h[j] - w_h.min()) / a >= min_prom: sh[j] = True
        if l[j] == w_l.min() and (w_l.max() - l[j]) / a >= min_prom: sl[j] = True
    return sh, sl


def _upper_hull(idx, val):
    """Monotone chain upper hull: the tightest set of points such that every
    other point lies BELOW the connecting segments. The last segment, extended,
    is the trend line currently in force."""
    hull = []
    for i, v in zip(idx, val):
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            # drop hull[-1] if it sits below the line from hull[-2] to (i, v)
            if (y2 - y1) * (i - x1) >= (v - y1) * (x2 - x1): hull.pop()
            else: break
        hull.append((i, v))
    return hull


def _lower_hull(idx, val):
    return [(x, -y) for x, y in _upper_hull(idx, [-v for v in val])]


def lines(a, k=5, min_prom=1.0, lookback=250, confirm=None):
    """Active bear (from highs) and bull (from lows) structural lines per bar."""
    ts, o, h, l, c = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    n = len(c)
    A = atr_(h, l, c); A = np.where(A > 0, A, np.nan)
    if confirm is None: confirm = k
    sh, sl = major_swings(h, l, k, min_prom, A)
    shi = np.where(sh)[0]; sli = np.where(sl)[0]

    out = {key: np.full(n, np.nan) for key in
           ("bear_slope","bear_dist","bear_broken","bear_span","bear_touch",
            "bull_slope","bull_dist","bull_broken","bull_span","bull_touch")}

    for i in range(60, n):
        lo_i = i - lookback
        # only swings CONFIRMED by bar i
        H = shi[(shi <= i - confirm) & (shi >= lo_i)]
        L = sli[(sli <= i - confirm) & (sli >= lo_i)]
        if len(H) >= 2:
            hull = _upper_hull(list(H), [h[j] for j in H])
            if len(hull) >= 2:
                # THE LONGEST segment, not the most recent one. The hull's last
                # segment is by construction the newest pair, which after a
                # breakout is a 20-30 bar local line — exactly the myopia that
                # made the old least-squares version useless. The structural line
                # is the one spanning the most bars.
                # Longest segment that actually SLOPES DOWN. Without the sign
                # constraint the longest hull segment on a long window is often
                # the RISING run into the all-time high — on ETH weekly that gave
                # a "bear line" with slope +0.108. A bear trend line is
                # descending by definition.
                segs = [(hull[q], hull[q + 1]) for q in range(len(hull) - 1)
                        if hull[q + 1][0] > hull[q][0]
                        and hull[q + 1][1] <= hull[q][1]]
                if not segs: continue
                (x1, y1), (x2, y2) = max(segs, key=lambda s: s[1][0] - s[0][0])
                if x2 > x1:
                    m = (y2 - y1) / (x2 - x1)
                    line = y2 + m * (i - x2)
                    out["bear_slope"][i]  = m / A[i]
                    out["bear_dist"][i]   = (c[i] - line) / A[i]
                    out["bear_broken"][i] = 1.0 if c[i] > line else 0.0
                    out["bear_span"][i]   = i - x1
                    out["bear_touch"][i]  = sum(
                        abs(h[j] - (y2 + m * (j - x2))) / A[i] < 0.5 for j in H)
        if len(L) >= 2:
            hull = _lower_hull(list(L), [l[j] for j in L])
            if len(hull) >= 2:
                segs = [(hull[q], hull[q + 1]) for q in range(len(hull) - 1)
                        if hull[q + 1][0] > hull[q][0]
                        and hull[q + 1][1] >= hull[q][1]]      # bull line rises
                if not segs: continue
                (x1, y1), (x2, y2) = max(segs, key=lambda s: s[1][0] - s[0][0])
                if x2 > x1:
                    m = (y2 - y1) / (x2 - x1)
                    line = y2 + m * (i - x2)
                    out["bull_slope"][i]  = m / A[i]
                    out["bull_dist"][i]   = (c[i] - line) / A[i]
                    out["bull_broken"][i] = 1.0 if c[i] < line else 0.0
                    out["bull_span"][i]   = i - x1
                    out["bull_touch"][i]  = sum(
                        abs(l[j] - (y2 + m * (j - x2))) / A[i] < 0.5 for j in L)
    out["ts"] = ts
    return pd.DataFrame(out)
