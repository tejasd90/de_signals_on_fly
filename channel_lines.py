#!/usr/bin/env python3
"""
channel_lines.py — the trend CHANNEL line geometry brooks_context.py never built,
plus the quiet-range-break features Tejas's episodes are actually made of.

WHY THIS EXISTS
brooks_context.py fits both trend lines (bull on swing lows, bear on swing highs)
but constructs only ONE channel line: the bull channel's upper return line, and
it measures only OVERSHOOT of it (`chan_overshoot`, brooks_context.py:171). That
was tested as R7 and died (dEV -0.024, P=0.590).

But R7 is not the claim under test. Brooks reads an overshoot of the upper line
in a BULL channel as exhaustion -> reversal. Tejas's claim is the mirror image
and the opposite sign: a BEAR channel's LOWER return line being broken DOWNWARD
is a breakout with immediate follow-through. His words:

    "a strong indication of immediate breakout-breakdown is channel line break.
     Trendlines breaking only break the trend, but channel line breaks are
     breakouts."

That line -- the bear channel's lower return line -- does not exist anywhere in
the codebase. Neither does its bull twin (upper trendline break vs lower channel
line). So the distinction has never been measured. This builds all four:

    bull_tl_break   close BELOW the bull trend line   (trend over)
    bull_cl_break   close ABOVE the bull channel line (upside breakout)
    bear_tl_break   close ABOVE the bear trend line   (trend over)
    bear_cl_break   close BELOW the bear channel line (downside breakout)  <-- new

If Tejas is right, cl_break should carry forward tail risk that tl_break does not.
If the project's prior finding holds instead -- states pay, events don't -- both
break flags will be null and only the persistent regime features will matter.

THE QUIET-RANGE BREAK
Three of his four episodes start the same way: a flat, low-volatility stretch
whose extreme then gives way ("the almost flattish and low-volatility curve of
19-22 September", "the weekend calm", "the extreme bearish calm on 16-17 Jan").
That is a volatility contraction followed by a range break, so both halves are
stored separately -- contraction alone was already falsified as coil compression,
and the question is whether the BREAK of a quiet range is different.

Lookahead discipline is inherited: swing points lag 2 bars, and the caller takes
only bars that have CLOSED by entry_ts.
"""
import os, argparse
import numpy as np, pandas as pd
from brooks_context import load_tf, atr, swings, fit_line, TFS

def build(a, tf, n_swings=4):
    ts, o, h, l, c = a[:,0], a[:,1], a[:,2], a[:,3], a[:,4]
    n = len(c); A = atr(h, l, c); A = np.where(A > 0, A, np.nan)
    out = {}
    def P(k, v): out[k] = np.asarray(v, float)

    keys = ["bull_tl_dist","bull_tl_break","bull_cl_dist","bull_cl_break","bull_chan_w","bull_r2",
            "bear_tl_dist","bear_tl_break","bear_cl_dist","bear_cl_break","bear_chan_w","bear_r2"]
    v = {k: np.full(n, np.nan) for k in keys}
    sh, sl = swings(h, l)
    sh_i, sl_i = np.where(sh)[0], np.where(sl)[0]
    for i in range(50, n):
        lo_i = sl_i[sl_i <= i-2][-n_swings:]
        hi_i = sh_i[sh_i <= i-2][-n_swings:]
        # BULL channel: trend line on swing LOWS, return line parallel ABOVE it
        if len(lo_i) >= 2:
            b, a0, r2 = fit_line(lo_i, l[lo_i])
            if b == b:
                tl = a0 + b*i
                v["bull_tl_dist"][i]  = (c[i] - tl)/A[i]
                v["bull_tl_break"][i] = 1.0 if c[i] < tl else 0.0
                v["bull_r2"][i] = r2
                if len(hi_i) >= 1:
                    off = float(np.nanmax(h[hi_i] - (a0 + b*hi_i)))
                    if np.isfinite(off) and off > 0:
                        cl = tl + off
                        v["bull_chan_w"][i]   = off/A[i]
                        v["bull_cl_dist"][i]  = (c[i] - cl)/A[i]
                        v["bull_cl_break"][i] = 1.0 if c[i] > cl else 0.0
        # BEAR channel: trend line on swing HIGHS, return line parallel BELOW it.
        # Breaking that lower line downward is the event Tejas is pointing at.
        if len(hi_i) >= 2:
            b, a0, r2 = fit_line(hi_i, h[hi_i])
            if b == b:
                tl = a0 + b*i
                v["bear_tl_dist"][i]  = (c[i] - tl)/A[i]
                v["bear_tl_break"][i] = 1.0 if c[i] > tl else 0.0
                v["bear_r2"][i] = r2
                if len(lo_i) >= 1:
                    off = float(np.nanmax((a0 + b*lo_i) - l[lo_i]))
                    if np.isfinite(off) and off > 0:
                        cl = tl - off
                        v["bear_chan_w"][i]   = off/A[i]
                        v["bear_cl_dist"][i]  = (c[i] - cl)/A[i]
                        v["bear_cl_break"][i] = 1.0 if c[i] < cl else 0.0
    for k in keys: P(k, v[k])

    # --- quiet / cleanliness -------------------------------------------------
    rng = h - l
    a5  = pd.Series(rng).rolling(5,  min_periods=2).mean().to_numpy()
    a20 = pd.Series(rng).rolling(20, min_periods=5).mean().to_numpy()
    P("quiet_ratio", a5/np.maximum(a20, 1e-12))          # <1 = contracting
    ov = np.concatenate([[np.nan],
         (np.minimum(h[1:],h[:-1]) - np.maximum(l[1:],l[:-1]))/np.maximum(rng[1:],1e-12)])
    ov = np.clip(ov, 0, 1)
    # "hairiness": high overlap between consecutive bars = choppy/hairy.
    P("hairy_10", pd.Series(ov).rolling(10, min_periods=3).mean().to_numpy())

    # --- quiet-range break ---------------------------------------------------
    # Extremes of the K bars ENDING ONE BAR AGO, so the current close breaking
    # them is a genuine break and not a tautology.
    for K in (10, 20):
        hi = pd.Series(h).shift(1).rolling(K, min_periods=3).max().to_numpy()
        lo = pd.Series(l).shift(1).rolling(K, min_periods=3).min().to_numpy()
        wasquiet = (pd.Series((hi-lo)/A).shift(0).to_numpy())
        P(f"qwidth_{K}", wasquiet)                        # prior range in ATR
        P(f"qbreak_up_{K}", (c > hi).astype(float))
        P(f"qbreak_dn_{K}", (c < lo).astype(float))
    g = pd.DataFrame(out); g.insert(0, "ts", ts)
    return g

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="events.parquet")
    ap.add_argument("--out", default="events_cl.parquet")
    a = ap.parse_args()
    ev = pd.read_parquet(a.events, columns=["spot","entry_ts"]).drop_duplicates()
    print(f"distinct (spot, entry_ts): {len(ev):,}")
    parts = []
    for spot in sorted(ev.spot.unique()):
        e = ev[ev.spot == spot].sort_values("entry_ts").reset_index(drop=True)
        for tf in TFS:
            arr = load_tf(spot, tf)
            if arr is None:
                print(f"  {spot} {tf}m: no data", flush=True); continue
            g = build(arr, tf)
            close_ts = g.ts.to_numpy() + tf*60          # bar must have CLOSED
            j = np.searchsorted(close_ts, e.entry_ts.to_numpy(), side="right") - 1
            ok = j >= 0
            blk = {}
            for col in [x for x in g.columns if x != "ts"]:
                z = np.full(len(e), np.nan, dtype=np.float32)
                z[ok] = g[col].to_numpy(float)[j[ok]].astype(np.float32)
                blk[f"cz{tf}_{col}"] = z
            e = pd.concat([e, pd.DataFrame(blk, index=e.index)], axis=1)
            print(f"  {spot} {tf}m: {len(g):,} bars -> {len(blk)} features", flush=True)
        parts.append(e)
    d = pd.concat(parts, ignore_index=True)
    d.to_parquet(a.out, index=False)
    print(f"-> {a.out}  {len(d):,} rows x {len(d.columns)} cols")

if __name__ == "__main__":
    main()
