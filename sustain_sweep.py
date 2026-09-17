#!/usr/bin/env python3
"""
sustain_sweep.py — the sustainability test with K tuned instead of guessed.

The first version used K=6 bars with no justification and a 0.7 give-back
threshold picked by eye. This computes every K in one pass and sweeps both, so
the verdict does not rest on two arbitrary numbers.

Reported honestly: the FULL grid, not the best cell. With 8 values of K and 6
thresholds that is 48 tests, so a scattering of P<0.05 is expected by chance.
Only a coherent REGION of the grid — neighbouring cells agreeing — is evidence.
"""
import os, json
from collections import defaultdict
import numpy as np, pandas as pd

KS = [2, 3, 4, 6, 8, 12, 18, 24]
CAN = "data/candles"

ev = pd.read_parquet("events.parquet",
      columns=['spot','expiry','duration','symbol','entry_ts','event_id',
               'activated','entry_premium','trigger_price'])
ev = ev[ev.activated & ev.entry_premium.between(2,20)]
buckets = defaultdict(list)
for r in ev.itertuples(): buckets[(r.spot, r.expiry, r.duration)].append(r)

out = []
for (spot, exp, dur), rows in buckets.items():
    cdir = os.path.join(CAN, spot, exp, str(dur))
    if not os.path.isdir(cdir): continue
    by_sym = defaultdict(list)
    for r in rows: by_sym[r.symbol].append(r)
    for sym, rs in by_sym.items():
        try: arr = np.asarray(json.load(open(os.path.join(cdir, sym + ".json"))), float)
        except Exception: continue
        if arr.ndim != 2 or len(arr) < 3: continue
        t, hi, lo = arr[:,0], arr[:,2], arr[:,3]
        for r in rs:
            j = int(np.searchsorted(t, r.entry_ts, side="right")) - 1
            if j < 0 or t[j] - r.entry_ts > dur*60: continue
            trig = r.trigger_price
            if not (trig > 0) or j + 1 >= len(t): continue
            rec = dict(event_id=r.event_id, ts=r.entry_ts)
            ok = True
            for K in KS:
                if j + 1 + K >= len(t): rec[f'dd{K}'] = np.nan; rec[f'rk{K}'] = np.nan; rec[f'pa{K}'] = np.nan; continue
                w_lo = lo[j+1:j+1+K]; w_hi = hi[j+1:j+1+K]; fwd = hi[j+1+K:]
                if len(fwd) == 0: rec[f'dd{K}'] = np.nan; rec[f'rk{K}'] = np.nan; rec[f'pa{K}'] = np.nan; continue
                rec[f'dd{K}'] = float(w_lo.min())/trig
                rec[f'rk{K}'] = float(w_hi.max())/trig
                rec[f'pa{K}'] = float(fwd.max())/trig
            rec['full'] = float(hi[j+1:].max())/trig
            out.append(rec)
d = pd.DataFrame(out)
d.to_parquet("sustain_sweep.parquet", index=False)
print(f"wrote sustain_sweep.parquet: {len(d):,} rows, K in {KS}")
