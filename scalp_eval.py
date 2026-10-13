"""Evaluate scalp_1m.py trades: per variant and threshold, out of sample, non-overlapping, after fees.
pnl is a fraction of notional. Rupees shown for a Rs 1,00,000 notional per trade (a +1% win is ~Rs 1,000).
CI: week-block bootstrap of the mean pnl per trade."""
import sys, numpy as np, pandas as pd
rng = np.random.default_rng(0)
for name in sys.argv[1:] or ("L1", "Q1", "L2", "Q2"):
    try: R = pd.read_parquet(f"data/scalp_{name}.parquet"); A = pd.read_csv(f"data/scalp_{name}_auc.csv")
    except FileNotFoundError: continue
    days = (R.ts.max() - R.ts.min()) / 86400
    print(f"\n===== {name}  months {len(A)}  AUC mean {A.auc.mean():.3f} (min {A.auc.min():.3f}, max {A.auc.max():.3f})  base rate {A.base.mean():.2%}")
    print(f"{'threshold':<10}{'asset':<6}{'trades':>7}{'/day':>6}{'win':>7}{'mean bps':>9}{'CI':>18}{'Rs/trade':>9}{'Rs total':>11}{'worst mo':>10}{'+ months':>9}")
    for q, g0 in R.groupby(R.q.astype(str)):
        for a, g in [("both", g0)] + list(g0.groupby("asset")):
            if len(g) < 5: continue
            wk = (g.ts // (7 * 86400)).to_numpy(); u = np.unique(wk); ix = {w: np.flatnonzero(wk == w) for w in u}; v = g.pnl.to_numpy()
            bs = [v[np.concatenate([ix[w] for w in rng.choice(u, len(u))])].mean() for _ in range(1000)]
            mo = g.groupby("mo").pnl.sum()
            print(f"{q:<10}{a:<6}{len(g):>7}{len(g)/days:>6.1f}{(g.pnl > 0).mean():>7.1%}{g.pnl.mean()*1e4:>9.1f}"
                  f"   [{np.percentile(bs,2.5)*1e4:+6.1f},{np.percentile(bs,97.5)*1e4:+6.1f}]{g.pnl.mean()*1e5:>9.0f}{g.pnl.sum()*1e5:>11,.0f}{mo.min()*1e5:>10,.0f}{(mo > 0).mean():>9.0%}")
