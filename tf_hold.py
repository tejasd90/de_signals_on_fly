"""Tejas's second point: after a signal, WAIT a few candles of its own timeframe.
If the premium HOLDS (no close... no LOW below the trigger candle's low = the SL)
enter at the end of the wait. His hunch: on lower timeframes this wait-and-hold is
more reliable, higher timeframes either never break out or don't wait.

Per row (one strike of one signal), from the option's own candles at that duration:
  j      = trigger candle (entry_ts); SL = its low; e0 = its close
  W      = 0 (enter at signal), 1, 2, 3, 5 bars
  held   = min(low[j+1..j+W]) >= SL
  ran    = max(high[j+1..j+W]) >= 2*e0     (it already went -- "didn't wait")
  entry  = close[j+W]; target exit at K x entry if the later high reaches it,
           otherwise held to the last bar (mark at expiry ~ intrinsic).
Three populations at each W: HELD, BROKE (SL hit), and DELAYED-ANY (wait W bars
regardless) -- the last separates "waiting" from "the hold filter".
"""
import json, os, sys, numpy as np, pandas as pd
from multiprocessing import Pool
WS = (1, 2, 3, 5); KS = (10, 25, 100)

def work(args):
    f, rows = args
    try: c = np.asarray(json.load(open(f)), dtype=object)
    except Exception: return []
    ts = c[:,0].astype(np.int64); lo = c[:,3].astype(float); hi = c[:,2].astype(float); cl = c[:,4].astype(float)
    pos = {t: i for i, t in enumerate(ts)}; out = []
    for r in rows:
        j = pos.get(r[0])
        if j is None or j + 6 >= len(ts): continue
        e0, sl = cl[j], lo[j]
        if e0 <= 0: continue
        rec = dict(idx=r[1])
        for W in (0,) + WS:
            ent = cl[j+W]
            if ent <= 0: continue
            pk = hi[j+W+1:].max() / ent; fin = cl[-1] / ent
            for K in KS:
                rec[f"v{K}_{W}"] = K if pk >= K else min(fin, K)
                rec[f"h{K}_{W}"] = pk >= K
            if W:
                rec[f"held_{W}"] = lo[j+1:j+W+1].min() >= sl
                rec[f"ran_{W}"] = hi[j+1:j+W+1].max() >= 2*e0
        out.append(rec)
    return out

if __name__ == "__main__":
    d = pd.read_parquet("events.parquet", columns=["signal","spot","expiry","duration","symbol","entry_ts","event_id"])
    d = d.sample(frac=float(sys.argv[1]) if len(sys.argv) > 1 else 0.35, random_state=0)
    d["f"] = "data/candles/" + d.spot + "/" + d.expiry + "/" + d.duration.astype(str) + "/" + d.symbol + ".json"
    jobs = [(f, list(zip(g.entry_ts, g.index))) for f, g in d.groupby("f")]
    print(f"{len(d):,} rows in {len(jobs):,} files", flush=True)
    with Pool(4) as p: res = [x for part in p.imap_unordered(work, jobs, chunksize=200) for x in part]
    R = pd.DataFrame(res).set_index("idx").join(d[["signal","spot","expiry","duration","event_id"]])
    R.to_parquet("data/tf_hold.parquet"); print(f"wrote {len(R):,}")
