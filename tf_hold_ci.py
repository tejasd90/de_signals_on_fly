"""CIs for the hold filter. Two contrasts, expiry-block bootstrap:
  filter : wait W & HELD   vs  wait W regardless   (what the hold condition itself adds)
  vs now : wait W & HELD   vs  enter at the signal  (the decision he faces)
Plus the same split by time (first/second half of expiries)."""
import numpy as np, pandas as pd
R = pd.read_parquet("data/tf_hold.parquet")
R["grp"] = pd.cut(R.duration, [0, 60, 180, 2000], labels=["low 30-60m", "mid 90-180m", "high 4h-1d"])
mid = np.sort(R.expiry.unique())[len(R.expiry.unique())//2]
def ci(g, W, K, n=600):
    ex = g.expiry.values; u = np.unique(ex); ix = {e: np.where(ex == e)[0] for e in u}
    h = g[f"held_{W}"].astype(bool).values; vW = g[f"v{K}_{W}"].values; v0 = g[f"v{K}_0"].values
    rng = np.random.default_rng(0); f, nw = [], []
    for _ in range(n):
        s = np.concatenate([ix[e] for e in rng.choice(u, len(u))])
        hh = h[s]; a = vW[s][hh].mean()
        f.append(a - vW[s].mean()); nw.append(a - v0[s].mean())
    return np.percentile(f, [2.5, 50, 97.5]), np.percentile(nw, [2.5, 50, 97.5])
fmt = lambda x: f"{x[1]:+.3f} [{x[0]:+.3f},{x[2]:+.3f}]"
for K in (25, 100):
    print(f"\n=== {K}x ===   {'filter (held - wait any)':>30}   {'held - enter now':>30}   halves (held - now): 1st / 2nd")
    for gname, g in R.groupby("grp", observed=True):
        for W in (2, 3, 5):
            a, b = ci(g, W, K)
            hv = []
            for half in (g[g.expiry < mid], g[g.expiry >= mid]):
                h = half[f"held_{W}"].astype(bool)
                hv.append(half.loc[h, f"v{K}_{W}"].mean() - half[f"v{K}_0"].mean())
            print(f"  {gname:<12} W={W}   {fmt(a):>30}   {fmt(b):>30}   {hv[0]:+.3f} / {hv[1]:+.3f}")
