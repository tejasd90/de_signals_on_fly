#!/usr/bin/env python3
"""
brooks_perps.py — Brooks' setups across all 220 Delta perpetuals.

WHY
Testing on BTC+ETH alone gave 13,602 HOURLY setups but only 502 daily and 41
weekly — so the timeframes Brooks actually trades were untested, and the little
evidence there ran TOWARD his claims (51.2% daily, 58.5% weekly) rather than
away. Setups scale with bars, and 2.7 years is only 142 weekly bars per symbol.
220 symbols is the cheap way to populate the daily and weekly cells.

WHAT IT DOES NOT FIX
More symbols add ROWS, not independent TIME. Mean pairwise correlation across
these perps is 0.385 and N_eff is 5.8 of 129 — so a weekly bootstrap must resample
WEEKS, never rows, and a tight confidence interval here is still bounded by ~142
independent periods. Reported accordingly.

These are TRADED candles with real volume, unlike the option chain.
"""
import os, glob, argparse
import numpy as np, pandas as pd
import brooks_setups as B

def resample(df, minutes):
    """Group hourly perp bars onto a clean UTC grid. Daily lands at 00:00 UTC and
    weekly on Monday 00:00 UTC, matching data/spot_grouped."""
    sec = minutes * 60
    ts = df.ts.to_numpy()
    if minutes == 10080:
        dow = ((ts // 86400) + 4) % 7          # 1970-01-01 was a Thursday
        key = (ts // 86400 - dow) * 86400
    else:
        key = (ts // sec) * sec
    g = pd.DataFrame({"k": key, "o": df.o, "h": df.h, "l": df.l, "c": df.c}).groupby("k")
    out = g.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()
    return np.column_stack([out.k, out.o, out.h, out.l, out.c]).astype(float)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", default="240,1440,10080")
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--rr", type=float, default=1.0)
    ap.add_argument("--min-bars", type=int, default=120)
    a = ap.parse_args()
    TFS = [int(x) for x in a.tfs.split(",")]

    files = sorted(glob.glob("data/perp_candles/*.parquet"))
    print(f"symbols: {len(files)}", flush=True)
    rows = []
    for n, fp in enumerate(files, 1):
        sym = os.path.basename(fp)[:-8]
        try: df = pd.read_parquet(fp).sort_values("ts")
        except Exception: continue
        if len(df) < 500: continue
        for tf in TFS:
            arr = resample(df, tf)
            if len(arr) < a.min_bars: continue
            su, h, l, ts = B.setups(arr, tf)
            for (i, name, longs, entry, stop) in su:
                R = abs(entry - stop)
                if not (R > 0): continue
                tgt = entry + a.rr * R if longs else entry - a.rr * R
                w = B.first_crossing(h, l, i, entry, tgt, stop, longs, a.horizon)
                if w is None: continue
                rows.append((sym, tf, ts[i], name, w))
        if n % 50 == 0: print(f"  {n}/{len(files)}  {len(rows):,} setups", flush=True)
    d = pd.DataFrame(rows, columns=["sym", "tf", "ts", "setup", "win"])
    d.to_parquet("brooks_perps.parquet", index=False)
    print(f"\nwrote brooks_perps.parquet: {len(d):,} setups")
