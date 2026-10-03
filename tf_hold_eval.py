import numpy as np, pandas as pd
R = pd.read_parquet("data/tf_hold.parquet")
R["grp"] = pd.cut(R.duration, [0, 60, 180, 2000], labels=["low 30-60m", "mid 90-180m", "high 4h-1d"])
def boot_diff(a_mask, b_mask, col, g):
    ex = g.expiry.values; u = np.unique(ex); ix = {e: np.where(ex == e)[0] for e in u}
    v = g[col].values; A = a_mask.values; B = b_mask.values; rng = np.random.default_rng(0); out = []
    for _ in range(500):
        s = np.concatenate([ix[e] for e in rng.choice(u, len(u))])
        out.append(v[s][A[s]].mean() - v[s][B[s]].mean())
    return np.percentile(out, [2.5, 97.5])
for K in (25, 100):
    print(f"\n=== target {K}x: expectancy per 1 unit staked (exit at {K}x else hold to expiry), P(hit) ===")
    print(f"{'group':<12}{'W':>2} | {'enter NOW':>16} | {'wait W, any':>16} | {'wait W, HELD':>22} {'held%':>6} | {'SL hit':>14} | {'ran in wait':>11} | held - now (CI)")
    for gname, g in R.groupby("grp", observed=True):
        now = g[f"v{K}_0"].mean()-1; pnow = g[f"h{K}_0"].mean()
        for W in (1, 2, 3, 5):
            h = g[f"held_{W}"].astype(bool); ran = g[f"ran_{W}"].astype(bool)
            dl = g[f"v{K}_{W}"].mean()-1
            eh = g.loc[h, f"v{K}_{W}"].mean()-1; ph = g.loc[h, f"h{K}_{W}"].mean()
            eb = g.loc[~h, f"v{K}_{W}"].mean()-1
            ci = boot_diff(h, pd.Series(True, index=g.index), f"v{K}_{W}", g) if W in (2, 3) else (np.nan, np.nan)
            # held vs NOW on the same rows' W=0 values is the decision; CI on held(W) - all(0):
            diff = eh - now
            print(f"{gname:<12}{W:>2} | {now:>+8.3f} {pnow:>6.2%} | {dl:>+16.3f} | {eh:>+8.3f} {ph:>6.2%}       {h.mean():>6.0%} | {eb:>+14.3f} | {ran.mean():>11.1%} | {diff:+.3f}")
