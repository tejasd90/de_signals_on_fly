#!/usr/bin/env python3
"""
brooks_context.py — Phase 1 of docs/ML/CONTEXT_PLAN.md.

The SPOT price-action context around each signal, computed not learned.
Brooks' own list of the useful tools, from the quote that started this:
  trend lines, trend channel lines, prior highs and lows, breakouts and failed
  breakouts, body/tail sizes, and the current bar vs the prior several bars.

Nothing here is fitted. Every feature is geometry. The only thing a model is
asked to do later is decide which combinations of these are worth trading.

TIMEFRAME LADDER — fixed at 60m / 240m / 1440m
Six of the twelve signal durations (40, 45, 90, 180, 480, 720) have no stored
spot series, and resampling each would introduce a different approximation per
duration. A fixed 1h/4h/1d ladder is stored for every spot, is the standard
read, and gives every event the same three views — which is what makes the
"rangebound on the higher timeframe, rejection on the lower" comparison
meaningful across events.

NO LOOKAHEAD, TWICE OVER
1. A swing high at bar j is only KNOWN at j+1, so all swing-derived features are
   lagged one bar. Same rule brooks_features.py already follows.
2. The bar CONTAINING the entry has not closed yet at entry time. Using it would
   leak. Features are taken from the last bar that CLOSED at or before entry.

Everything is ATR-normalised or a ratio. No raw prices — a tree splitting on
spotPrice < 67000 has learned a date range (HANDOFF 3.6).
"""
import os, json, argparse
import numpy as np, pandas as pd

TFS = [60, 240, 1440]
SPOT_DIR = "data/spot_candles"

# ─── loading ──────────────────────────────────────────────────────────────────

def load_tf(spot, tf):
    d = os.path.join(SPOT_DIR, spot, str(tf))
    if not os.path.isdir(d): return None
    rows = []
    # Spot candle files are named by DATE with no extension — unlike option
    # candles, which are `{symbol}.json`. Filtering on .json here silently
    # yielded zero files and a None series.
    for fn in sorted(os.listdir(d)):
        if fn.startswith(".") or ".tmp." in fn: continue
        try: rows.extend(json.load(open(os.path.join(d, fn))))
        except Exception: pass
    if len(rows) < 250: return None
    a = np.asarray([r[:5] for r in rows], float)
    a = a[np.argsort(a[:, 0])]
    _, k = np.unique(a[:, 0], return_index=True)
    return a[np.sort(k)]        # ts, o, h, l, c

# ─── primitives ───────────────────────────────────────────────────────────────

def atr(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=2).mean().to_numpy()

def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()

def swings(h, l, k=2):
    """Fractal swing highs/lows: extreme of a 2k+1 window centred on j.
    KNOWN only at j+k, so the caller must lag by k."""
    n = len(h); sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    for j in range(k, n - k):
        if h[j] == h[j - k:j + k + 1].max(): sh[j] = True
        if l[j] == l[j - k:j + k + 1].min(): sl[j] = True
    return sh, sl

def fit_line(idx, val):
    """Least squares on SWING POINTS — BROOKS_FEATURES.md item 145, the one
    specified feature never implemented. Returns (slope, intercept, r2)."""
    if len(idx) < 2: return np.nan, np.nan, np.nan
    x = np.asarray(idx, float); y = np.asarray(val, float)
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    if sxx <= 0: return np.nan, np.nan, np.nan
    b = ((x - xm) * (y - ym)).sum() / sxx
    a = ym - b * xm
    yh = a + b * x
    ss = ((y - ym) ** 2).sum()
    r2 = 1.0 - ((y - yh) ** 2).sum() / ss if ss > 0 else np.nan
    return b, a, r2

# ─── the feature grid, one row per bar ────────────────────────────────────────

def build(a, tf, n_swings=4, look=20):
    ts, o, h, l, c = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    n = len(c)
    A = atr(h, l, c); A = np.where(A > 0, A, np.nan)
    e20, e50 = ema(c, 20), ema(c, 50)
    rng = np.maximum(h - l, 1e-12); body = np.abs(c - o)

    F = {"ts": ts}
    P = lambda k, v: F.__setitem__(f"cx{tf}_{k}", v)

    # --- 5. bodies and tails, 6. this bar vs the prior several -----------------
    P("body_frac", body / rng)
    P("uptail",  (h - np.maximum(o, c)) / rng)
    P("dntail",  (np.minimum(o, c) - l) / rng)
    P("close_pos", (c - l) / rng)
    P("bar_atr", rng / A)
    prev_rng = np.concatenate([[np.nan], rng[:-1]])
    ov = np.concatenate([[np.nan],
         (np.minimum(h[1:], h[:-1]) - np.maximum(l[1:], l[:-1])) / np.maximum(rng[1:], 1e-12)])
    P("overlap_prev", np.clip(ov, 0, 1))
    P("bar_vs_prev", rng / np.maximum(prev_rng, 1e-12))
    tb = np.sign(c - o)
    for L in (5, 10, 20):
        P(f"trendbar_{L}", pd.Series(tb).rolling(L, min_periods=2).mean().to_numpy())
        P(f"overlap_{L}",  pd.Series(np.clip(ov, 0, 1)).rolling(L, min_periods=2).mean().to_numpy())
        P(f"bodyfrac_{L}", pd.Series(body / rng).rolling(L, min_periods=2).mean().to_numpy())

    # --- 7. trend vs range state ----------------------------------------------
    P("ema20_slope", np.concatenate([[np.nan], np.diff(e20)]) / A)
    P("ema50_slope", np.concatenate([[np.nan], np.diff(e50)]) / A)
    P("c_vs_ema20", (c - e20) / A)
    P("c_vs_ema50", (c - e50) / A)
    side = np.sign(c - e20)
    run = np.zeros(n)
    for i in range(1, n):
        run[i] = run[i - 1] + side[i] if side[i] == side[i - 1] else side[i]
    P("ema20_run", run)                       # consecutive closes one side of MA
    touch = np.zeros(n)
    for i in range(1, n):
        touch[i] = 0 if (l[i] <= e20[i] <= h[i]) else touch[i - 1] + 1
    P("bars_since_ma", touch)                 # Brooks' "20 MA gap bars"
    for L in (10, 20, 50):
        hi = pd.Series(h).rolling(L, min_periods=2).max().to_numpy()
        lo = pd.Series(l).rolling(L, min_periods=2).min().to_numpy()
        P(f"range_pos_{L}", (c - lo) / np.maximum(hi - lo, 1e-12))   # 0 low, 1 high
        P(f"range_atr_{L}", (hi - lo) / A)
        P(f"dist_hi_{L}", (hi - c) / A)
        P(f"dist_lo_{L}", (c - lo) / A)
    # efficiency: net move / summed move. High = trend, low = range.
    for L in (10, 20):
        net = np.abs(c - np.concatenate([np.full(L, np.nan), c[:-L]]))
        tot = pd.Series(np.abs(np.diff(c, prepend=c[0]))).rolling(L, min_periods=2).sum().to_numpy()
        P(f"efficiency_{L}", net / np.maximum(tot, 1e-12))

    # --- 1+2. trend lines and channel lines on SWING POINTS --------------------
    sh, sl = swings(h, l)
    sh_i = np.where(sh)[0]; sl_i = np.where(sl)[0]
    keys = ["bull_slope","bull_r2","bull_dist","bull_broken",
            "bear_slope","bear_r2","bear_dist","bear_broken",
            "chan_width","chan_overshoot","bars_since_sh","bars_since_sl",
            "dist_last_sh","dist_last_sl"]
    out = {k: np.full(n, np.nan) for k in keys}
    for i in range(50, n):
        lo_i = sl_i[sl_i <= i - 2][-n_swings:]     # lag 2: swing known k bars later
        hi_i = sh_i[sh_i <= i - 2][-n_swings:]
        if len(lo_i) >= 2:
            b, a0, r2 = fit_line(lo_i, l[lo_i])
            if b == b:
                line = a0 + b * i
                out["bull_slope"][i] = b / A[i]
                out["bull_r2"][i] = r2
                out["bull_dist"][i] = (c[i] - line) / A[i]
                out["bull_broken"][i] = 1.0 if c[i] < line else 0.0
                if len(hi_i) >= 1:
                    # Trend CHANNEL line: the trend line translated up by the
                    # largest deviation any swing high made from it. Brooks
                    # draws it parallel; the overshoot of that line is the
                    # exhaustion signal, so it is kept as its own feature.
                    off = float(np.nanmax(h[hi_i] - (a0 + b * hi_i)))
                    if np.isfinite(off):
                        out["chan_width"][i] = off / A[i]
                        out["chan_overshoot"][i] = (h[i] - (line + off)) / A[i]
        if len(hi_i) >= 2:
            b, a0, r2 = fit_line(hi_i, h[hi_i])
            if b == b:
                line = a0 + b * i
                out["bear_slope"][i] = b / A[i]
                out["bear_r2"][i] = r2
                out["bear_dist"][i] = (c[i] - line) / A[i]
                out["bear_broken"][i] = 1.0 if c[i] > line else 0.0
        if len(hi_i): out["bars_since_sh"][i] = i - hi_i[-1]; out["dist_last_sh"][i] = (c[i]-h[hi_i[-1]])/A[i]
        if len(lo_i): out["bars_since_sl"][i] = i - lo_i[-1]; out["dist_last_sl"][i] = (c[i]-l[lo_i[-1]])/A[i]
    for k, v in out.items(): P(k, v)

    # --- 4. breakouts and failed breakouts ------------------------------------
    for L, W in ((20, 5),):
        hi = pd.Series(h).rolling(L, min_periods=2).max().shift(1).to_numpy()
        lo = pd.Series(l).rolling(L, min_periods=2).min().shift(1).to_numpy()
        up = (h > hi).astype(float); dn = (l < lo).astype(float)
        fail_u = np.zeros(n); fail_d = np.zeros(n)
        for i in range(n):
            if up[i] and i + W < n and c[i + 1:i + 1 + W].min() < hi[i]: fail_u[i] = 1
            if dn[i] and i + W < n and c[i + 1:i + 1 + W].max() > lo[i]: fail_d[i] = 1
        # shift by W so only RESOLVED breakouts are visible at bar i
        for nm, arr in (("bo_up", up), ("bo_dn", dn)):
            P(f"{nm}_{L}", pd.Series(arr).rolling(L, min_periods=1).sum().shift(1).to_numpy())
        P("bo_failrate", pd.Series(np.where(up + dn > 0, fail_u + fail_d, np.nan))
              .rolling(L, min_periods=2).mean().shift(W + 1).to_numpy())

    # --- 8. always-in, and 3. spike vs channel --------------------------------
    ai = np.where((c > e20) & (e20 > e50), 1.0, np.where((c < e20) & (e20 < e50), -1.0, 0.0))
    P("always_in", ai)
    big = pd.Series(rng / A).rolling(20, min_periods=2).max().to_numpy()
    P("spike_max20", big)
    P("is_spike", (rng / A > 2.0).astype(float))
    return pd.DataFrame(F)

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="events.parquet")
    ap.add_argument("--out", default="events_ctx")
    a = ap.parse_args()

    ev = pd.read_parquet(a.events)
    print(f"events {len(ev):,}", flush=True)
    os.makedirs(a.out, exist_ok=True)

    # Written per spot, context columns downcast to float32. The machine has 8 GB
    # and has been OOM-killed twice; concatenating 1.66M rows x ~200 float64
    # columns would be ~2.6 GB before pandas overhead. Downstream reads the
    # directory, which pandas/duckdb both handle as one table.
    for spot in sorted(ev.spot.unique()):
        e = ev[ev.spot == spot].copy()
        added = []
        for tf in TFS:
            arr = load_tf(spot, tf)
            if arr is None:
                print(f"  {spot} {tf}m: no data", flush=True); continue
            g = build(arr, tf)
            # LOOKAHEAD GUARD: only bars that have CLOSED by entry_ts.
            close_ts = g.ts.to_numpy() + tf * 60
            j = np.searchsorted(close_ts, e.entry_ts.to_numpy(), side="right") - 1
            ok = j >= 0
            cols = [c for c in g.columns if c != "ts"]
            block = {}
            for col in cols:
                v = np.full(len(e), np.nan, dtype=np.float32)
                v[ok] = g[col].to_numpy(dtype=np.float64)[j[ok]].astype(np.float32)
                block[col] = v
            e = pd.concat([e, pd.DataFrame(block, index=e.index)], axis=1)
            added += cols
            print(f"  {spot} {tf}m: {len(g):,} bars -> {len(cols)} features", flush=True)
        bad = [c for c in e.columns if c.startswith("label") or c.startswith("_")]
        assert not bad, bad
        fp = os.path.join(a.out, f"{spot}.parquet")
        e.to_parquet(fp, index=False)
        print(f"  -> {fp}  {len(e):,} rows x {len(e.columns)} cols "
              f"({len(added)} context)", flush=True)
        del e

if __name__ == "__main__":
    main()
