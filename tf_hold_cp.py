"""Audit fixes for wait-and-hold: (1) 8.26% round-trip cost (COST, as premium_pa.py),
(2) calls vs puts separately (bull drift lifts call residuals), (3) hit-only metric
(target or zero) to reconcile with CONTEXT_PLAN's 'delayed entry all negative'."""
import numpy as np, pandas as pd
COST = 0.0826; W = 3; K = 25
R = pd.read_parquet("data/tf_hold.parquet")
R["typ"] = R.event_id.str[-1]
R["grp"] = pd.cut(R.duration, [0, 60, 180, 2000], labels=["30-60m","90-180m","4h-1d"])
R["yr"] = R.expiry.str[:4]
def ci(g, n=400):
    ex = g.expiry.values; u = np.unique(ex); ix = {e: np.where(ex == e)[0] for e in u}
    h = g[f"held_{W}"].astype(bool).values; vW = g[f"v{K}_{W}"].values; v0 = g[f"v{K}_0"].values
    rng = np.random.default_rng(0); o = []
    for _ in range(n):
        s = np.concatenate([ix[e] for e in rng.choice(u, len(u))]); o.append(vW[s][h[s]].mean() - v0[s].mean())
    return np.percentile(o, [2.5, 97.5])
print(f"W={W}, target {K}x, net of {COST:.2%} round trip. 'hit-only' = {K} if hit else 0.\n")
print(f"{'tf':<9}{'typ':<4}| {'now':>7} {'hold':>7} {'diff':>7} {'CI':>17} | hit-only: {'now':>7} {'hold':>7} | resid@exp now/hold | by year diff")
for (gname, t), g in R.groupby(["grp","typ"], observed=True):
    h = g[f"held_{W}"].astype(bool)
    now = g[f"v{K}_0"].mean()-1-COST; hold = g.loc[h, f"v{K}_{W}"].mean()-1-COST; c = ci(g)
    hn = g[f"h{K}_0"].mean()*K-1-COST; hh = g.loc[h, f"h{K}_{W}"].mean()*K-1-COST
    rn = g.loc[~g[f"h{K}_0"], f"v{K}_0"].mean(); rh = g.loc[h & ~g[f"h{K}_{W}"], f"v{K}_{W}"].mean()
    yrs = " ".join(f"{y[2:]}:{(gy.loc[gy[f'held_{W}'].astype(bool), f'v{K}_{W}'].mean()-gy[f'v{K}_0'].mean()):+.2f}" for y, gy in g.groupby("yr"))
    print(f"{gname:<9}{t:<4}| {now:>+7.3f} {hold:>+7.3f} {hold-now:>+7.3f} [{c[0]:+.3f},{c[1]:+.3f}] | {hn:>+16.3f} {hh:>+7.3f} | {rn:>6.3f} / {rh:>5.3f} | {yrs}")
