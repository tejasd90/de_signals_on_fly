"""His 15 Oct point: booking profits at level-break spikes is the hardest part. When an option's premium
jumps >= J x within one hour (15m MARK high vs the close 4 bars earlier), what happens next?
Exit choices compared, all measured as a multiple of the pre-spike close (the 'entry'):
  peak     the spike bar's high (unreachable; the wick)
  close    sell at the spike bar's close (first price you can act on after seeing it)
  next1h   sell at the close 4 bars later
  hold     hold to settlement (last close before settlement)
  later    the best high after the spike bar (oracle; shows how often more was coming)
One event per contract (the first spike). BTC/ETH, 2024-01 onward, any strike / expiry / time left."""
import json, os, re, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
J = 3.0

def scan(args):
    asset, expiry = args; d = f"data/candles/{asset}/{expiry}/15"; out = []
    settle = pd.Timestamp(expiry).timestamp() + 43200
    for fn in os.listdir(d):
        if not fn.endswith(".json") or fn.startswith("."): continue
        try: rows = json.load(open(f"{d}/{fn}"))
        except Exception: continue
        a = np.array([[r[0], r[2], r[4]] for r in rows if r[4] is not None and r[0] + 900 <= settle], float)
        if len(a) < 10: continue
        t, h, c = a.T
        base = np.r_[np.full(4, np.nan), c[:-4]]
        hit = np.where((base > 0) & (h >= J * base))[0]
        if not len(hit): continue
        i = hit[0]; b = base[i]
        out.append(dict(asset=asset, expiry=expiry, typ=fn[0], tte_h=(settle - t[i]) / 3600, entry=b,
                        peak=h[i] / b, close=c[i] / b, next1h=c[min(i + 4, len(c) - 1)] / b, hold=c[-1] / b,
                        later=(h[i + 1:].max() / b) if i + 1 < len(c) else np.nan))
    return out

if __name__ == "__main__":
    jobs = [(a, e) for a in ("BTC", "ETH") for e in sorted(os.listdir(f"data/candles/{a}"))
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) and e >= "2024-01-01" and os.path.isdir(f"data/candles/{a}/{e}/15")
            and pd.Timestamp(e) + pd.Timedelta(hours=12) < pd.Timestamp.utcnow().tz_localize(None)]
    with ProcessPoolExecutor(4) as ex: R = pd.DataFrame([x for r in ex.map(scan, jobs, chunksize=8) for x in r])
    R.to_parquet("data/spike_retention.parquet")
    R["tteb"] = pd.cut(R.tte_h, [0, 6, 24, 72, 1e9], labels=["<6h", "6-24h", "1-3d", ">3d"])
    print(f"spikes (>= {J}x within 1h, first per contract): {len(R):,}  expiries {R.expiry.nunique()}")
    for g, D in [("all", R)] + list(R.groupby("tteb", observed=True)):
        print(f"\n[{g}] n={len(D):,}")
        for k in ("peak", "close", "next1h", "hold", "later"):
            print(f"  {k:7s} median {D[k].median():6.2f}x  mean {D[k].mean():7.2f}x")
        print(f"  share where holding to settlement beat selling at the spike close: {(D.hold > D.close).mean():.1%}")
        print(f"  share where a later high exceeded 2x the spike close: {(D.later >= 2 * D.close).mean():.1%}")
