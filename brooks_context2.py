#!/usr/bin/env python3
"""
brooks_context2.py — the structural features brooks_context.py did not build.

Adds the machinery behind the rules that were proposed and never tested:
leg counting (H1/H2/L1/L2), tight trading ranges, micro channels and micro gaps,
breakout strength vs weakness, exhaustion bars and climax counts, three-push /
wedge shapes, tests of a prior extreme, stairs and shrinking stairs, final flags,
and pullback depth.

Same discipline as the first module: pure geometry, ATR-normalised, no raw
prices, swings lagged so a swing at j is only used from j+2, and the joining
step takes the last bar that CLOSED at or before the signal.

NOT BUILDABLE from this data, and excluded rather than faked:
  - anything intrabar ("while forming, the bar stays near its high") — needs ticks
  - volume rules — spot candles here carry volume = null, and Brooks rates volume
    unreliable anyway
  - session/day-type rules (trend from the open, 11am traps) — crypto is 24/7
"""
import os, json, argparse
import numpy as np, pandas as pd
from brooks_context import load_tf, atr, ema, swings, fit_line, TFS

def rolling_max(x, n): return pd.Series(x).rolling(n, min_periods=2).max().to_numpy()
def rolling_min(x, n): return pd.Series(x).rolling(n, min_periods=2).min().to_numpy()

def build2(a, tf):
    ts, o, h, l, c = a[:,0], a[:,1], a[:,2], a[:,3], a[:,4]
    n = len(c)
    A = atr(h,l,c); A = np.where(A>0, A, np.nan)
    e20 = ema(c,20); rng = np.maximum(h-l,1e-12); body = np.abs(c-o)
    F = {"ts": ts}; P = lambda k,v: F.__setitem__(f"cy{tf}_{k}", v)

    # ── legs: H1/H2/L1/L2 counting ────────────────────────────────────────────
    # After a down leg, the 1st bar trading above the prior bar's high is H1, the
    # next such after a further low is H2. Brooks prefers the SECOND entry.
    hh = np.concatenate([[False], h[1:] > h[:-1]])
    ll = np.concatenate([[False], l[1:] < l[:-1]])
    hcount = np.zeros(n); lcount = np.zeros(n)
    hc = lc = 0
    for i in range(1, n):
        if ll[i]: hc = 0                      # a new low restarts the H count
        if hh[i]: hc += 1
        if hh[i]: lc = 0
        if ll[i]: lc += 1
        hcount[i], lcount[i] = hc, lc
    P("h_count", np.minimum(hcount, 4)); P("l_count", np.minimum(lcount, 4))
    P("is_h2", (hcount == 2).astype(float)); P("is_l2", (lcount == 2).astype(float))
    P("is_h1", (hcount == 1).astype(float)); P("is_l1", (lcount == 1).astype(float))

    # ── tight trading range — "trumps everything" ─────────────────────────────
    for L in (10, 20):
        w = (rolling_max(h,L) - rolling_min(l,L)) / A
        P(f"ttr_width_{L}", w)
        P(f"is_ttr_{L}", (w < 2.5).astype(float))       # range < 2.5 ATR over L bars
    dojis = (body/rng < 0.25).astype(float)
    P("doji_rate_10", pd.Series(dojis).rolling(10, min_periods=2).mean().to_numpy())

    # ── micro channel and micro gap ───────────────────────────────────────────
    up_run = np.zeros(n); dn_run = np.zeros(n)
    for i in range(1, n):
        up_run[i] = up_run[i-1]+1 if l[i] >= l[i-1] else 0
        dn_run[i] = dn_run[i-1]+1 if h[i] <= h[i-1] else 0
    P("micro_up", up_run); P("micro_dn", dn_run)
    mg_u = np.zeros(n); mg_d = np.zeros(n)
    mg_u[2:] = (l[2:] >= h[:-2]).astype(float)          # micro gap up = strength
    mg_d[2:] = (h[2:] <= l[:-2]).astype(float)
    P("micro_gap_up", mg_u); P("micro_gap_dn", mg_d)

    # ── breakout strength vs weakness ─────────────────────────────────────────
    hi20 = rolling_max(h,20); lo20 = rolling_min(l,20)
    bo_u = (h > np.concatenate([[np.nan], hi20[:-1]])).astype(float)
    bo_d = (l < np.concatenate([[np.nan], lo20[:-1]])).astype(float)
    P("bo_up", bo_u); P("bo_dn", bo_d)
    # strong: big body, small opposing tail, closes beyond many prior closes
    up_tail = (h-np.maximum(o,c))/rng; dn_tail = (np.minimum(o,c)-l)/rng
    closes_above = np.zeros(n)
    for i in range(5, n):
        closes_above[i] = (c[i] > c[max(0,i-20):i]).sum()
    P("closes_above_20", closes_above)
    P("bo_strength", (body/A) * (1-up_tail) * np.sign(c-o))
    # follow-through: next 2 bars same-direction bodies (shifted so it stays causal)
    ft = np.sign(c-o)
    P("follow_through", pd.Series(ft).rolling(3, min_periods=3).sum().to_numpy())

    # ── exhaustion / climax ───────────────────────────────────────────────────
    avg_rng = pd.Series(rng).rolling(10, min_periods=3).mean().to_numpy()
    P("bar_vs_avg", rng/np.maximum(avg_rng,1e-12))
    P("is_exhaustion", ((rng/np.maximum(avg_rng,1e-12) > 2.0) &
                        (np.abs(c-o)/rng > 0.6)).astype(float))
    clim = (rng/A > 2.0).astype(float)
    P("climax_count_10", pd.Series(clim).rolling(10, min_periods=2).sum().to_numpy())
    P("consec_climax", pd.Series(clim).rolling(3, min_periods=3).sum().to_numpy())

    # ── three-push / wedge, test of extreme, stairs ───────────────────────────
    sh, sl = swings(h,l); shi = np.where(sh)[0]; sli = np.where(sl)[0]
    keys = ["push3_up","push3_dn","wedge_up","wedge_dn","test_hi","test_lo",
            "stairs_shrink","mm_dist","pull_depth"]
    out = {k: np.full(n, np.nan) for k in keys}
    for i in range(60, n):
        H = shi[shi <= i-2][-3:]; L = sli[sli <= i-2][-3:]
        if len(H) == 3:
            up = (h[H[0]] < h[H[1]] < h[H[2]])
            out["push3_up"][i] = 1.0 if up else 0.0
            if up:   # wedge = pushes shrinking (converging)
                d1, d2 = h[H[1]]-h[H[0]], h[H[2]]-h[H[1]]
                out["wedge_up"][i] = 1.0 if d2 < d1 else 0.0
                out["stairs_shrink"][i] = d2/max(d1,1e-9)
            out["test_hi"][i] = (h[i] - h[H[-1]])/A[i]        # ~0 = testing the high
        if len(L) == 3:
            dn = (l[L[0]] > l[L[1]] > l[L[2]])
            out["push3_dn"][i] = 1.0 if dn else 0.0
            if dn:
                d1, d2 = l[L[0]]-l[L[1]], l[L[1]]-l[L[2]]
                out["wedge_dn"][i] = 1.0 if d2 < d1 else 0.0
            out["test_lo"][i] = (l[i] - l[L[-1]])/A[i]
        # measured move: last leg projected forward from the last swing
        if len(H) >= 2 and len(L) >= 1:
            leg = h[H[-1]] - l[L[-1]]
            out["mm_dist"][i] = (c[i] - (h[H[-1]] + leg))/A[i]
        # pullback depth vs the MA — "pullback fails to reach the MA" = strength
        if len(H) >= 1:
            out["pull_depth"][i] = (h[H[-1]] - l[i])/A[i]
    for k,v in out.items(): P(k, v)
    P("above_ma_pull", ((l > e20) & (np.sign(c-o) < 0)).astype(float))

    # ── final flag: a flat, two-sided patch late in a long trend ──────────────
    eff = np.full(n, np.nan)
    for L in (20,):
        net = np.abs(c - np.concatenate([np.full(L,np.nan), c[:-L]]))
        tot = pd.Series(np.abs(np.diff(c,prepend=c[0]))).rolling(L,min_periods=2).sum().to_numpy()
        eff = net/np.maximum(tot,1e-12)
    run = np.zeros(n); side = np.sign(c-e20)
    for i in range(1,n): run[i] = run[i-1]+side[i] if side[i]==side[i-1] else side[i]
    P("final_flag", ((eff < 0.25) & (np.abs(run) >= 6)).astype(float))
    return pd.DataFrame(F)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="events_ctx"); ap.add_argument("--out", default="events_ctx2")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    for spot in ["BTC","ETH","XAUT"]:
        fp = os.path.join(a.src, f"{spot}.parquet")
        if not os.path.exists(fp): continue
        e = pd.read_parquet(fp)
        for tf in TFS:
            arr = load_tf(spot, tf)
            if arr is None: print(f"  {spot} {tf}m: no data"); continue
            g = build2(arr, tf)
            close_ts = g.ts.to_numpy() + tf*60
            j = np.searchsorted(close_ts, e.entry_ts.to_numpy(), side="right") - 1
            ok = j >= 0
            blk = {}
            for col in [x for x in g.columns if x != "ts"]:
                v = np.full(len(e), np.nan, dtype=np.float32)
                v[ok] = g[col].to_numpy(dtype=np.float64)[j[ok]].astype(np.float32)
                blk[col] = v
            e = pd.concat([e, pd.DataFrame(blk, index=e.index)], axis=1)
            print(f"  {spot} {tf}m -> {len(blk)} new features", flush=True)
        e.to_parquet(os.path.join(a.out, f"{spot}.parquet"), index=False)
        ncy = len([c for c in e.columns if c.startswith("cy")])
        print(f"  -> {spot}: {len(e):,} rows, {ncy} new structural features\n", flush=True)
