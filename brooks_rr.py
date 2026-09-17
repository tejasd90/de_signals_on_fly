#!/usr/bin/env python3
"""
brooks_rr.py — sweep the reward multiple, not just the literal 1:1.

Brooks' trader's equation is "probability x reward > (1-probability) x risk", and
he argues explicitly that a 40%-probability trade with a large reward is fine.
Testing only 1:1 tests his 60% CLAIM, not his METHOD. This tests the method.

EFFICIENT: instead of re-running the crossing test per R multiple, record the
MAXIMUM FAVOURABLE EXCURSION (in R units) reached BEFORE the stop is hit. A trade
then wins at multiple m if and only if MFE >= m, so one pass answers every m.

COSTS ARE IN R UNITS. A futures round trip is taker 0.05% x2 plus 18% GST =
0.118% of NOTIONAL. R is a price distance, so the cost in R units is
0.00118 x entry / R — which means tight stops are expensive and wide ones are
cheap. That asymmetry is invisible if you work in R alone.
"""
import os, glob, argparse
import numpy as np, pandas as pd
import brooks_setups as B
from brooks_perps import resample

RT_COST = 0.0005 * 2 * 1.18        # taker both ways + GST, on notional

def mfe_before_stop(h, l, i, entry, stop, longside, horizon):
    """Max favourable excursion in R units before the stop, or None if unfilled."""
    R = abs(entry - stop)
    if not (R > 0): return None
    end = min(len(h), i + 1 + horizon)
    filled = False; best = 0.0
    for k in range(i + 1, end):
        if not filled:
            if (longside and h[k] >= entry) or ((not longside) and l[k] <= entry):
                filled = True
            else:
                continue
        if longside:
            if l[k] <= stop: return best
            best = max(best, (h[k] - entry) / R)
        else:
            if h[k] >= stop: return best
            best = max(best, (entry - l[k]) / R)
    return best if filled else None

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfs", default="240,1440"); ap.add_argument("--horizon", type=int, default=40)
    a = ap.parse_args()
    TFS = [int(x) for x in a.tfs.split(",")]
    rows = []
    files = sorted(glob.glob("data/perp_candles/*.parquet"))
    for n, fp in enumerate(files, 1):
        sym = os.path.basename(fp)[:-8]
        try: df = pd.read_parquet(fp).sort_values("ts")
        except Exception: continue
        if len(df) < 500: continue
        for tf in TFS:
            arr = resample(df, tf)
            if len(arr) < 120: continue
            su, h, l, ts = B.setups(arr, tf)
            for (i, name, longs, entry, stop) in su:
                m = mfe_before_stop(h, l, i, entry, stop, longs, a.horizon)
                if m is None: continue
                R = abs(entry - stop)
                rows.append((sym, tf, ts[i], name, m, RT_COST * entry / R))
        if n % 60 == 0: print(f"  {n}/{len(files)}  {len(rows):,}", flush=True)
    d = pd.DataFrame(rows, columns=["sym","tf","ts","setup","mfe","cost_R"])
    d.to_parquet("brooks_rr.parquet", index=False)
    print(f"wrote brooks_rr.parquet: {len(d):,} setups")
