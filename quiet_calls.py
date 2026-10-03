"""The Aug-19 picture as a trade. First day of each episode (quiet weekend, low-vol week,
price held near its 7-day high; causal percentiles from bigmoves.py) -> at 00:00 UTC the
next morning buy calls 3-6% OTM with 3-8 days to expiry, hold to expiry, net of the 8.26%
round trip (COST, as premium_pa.py). MARK premiums from data/short_panel.parquet.
Baseline: the same option cell bought at 00:00 UTC on every other day.
Also the PUT side as a control: the picture should not help puts if it is directional."""
import numpy as np, pandas as pd
COST = 0.0826
R = pd.read_parquet("data/bigmoves_precursors.parquet").sort_values(["sym","day"])
m = (R.wkend <= 0.3) & (R.rv7 <= 0.3) & (R.dd7 >= 0.6)
S = R[m].copy(); S["g"] = (S.groupby("sym").day.diff().dt.days.fillna(99) > 3).cumsum()
starts = S.groupby(["sym","g"]).day.min().reset_index()
starts["asset"] = starts.sym.str[:3]
starts["t"] = (starts.day.astype("int64")//10**9).astype(int)       # day d 00:00 UTC (features known at close d-1)
P = pd.read_parquet("data/short_panel.parquet")
P["m"] = np.where(P.typ == "C", (P.K-P.S0)/P.S0, (P.S0-P.K)/P.S0)*100
P = P[(P.m.between(3, 6)) & (P.tte_h.between(72, 192)) & (P.entry_t % 86400 == 0) & (P.prem > 0.0005*P.S0)]
P["r"] = P.payoff/P.prem - 1 - COST
P["day"] = pd.to_datetime(P.entry_t, unit="s").dt.normalize()
key = set(zip(starts.asset, starts.t))
P["ep"] = [(a, t) in key for a, t in zip(P.asset, P.entry_t)]
for typ in ("C", "P"):
    g = P[P.typ == typ]
    e = g[g.ep].groupby(["asset","day"]).r.mean(); b = g[~g.ep].groupby(["asset","day"]).r.mean()
    rng = np.random.default_rng(0)
    bs = [rng.choice(e.values, len(e)).mean() - rng.choice(b.values, len(b)).mean() for _ in range(5000)]
    print(f"{'CALLS' if typ=='C' else 'PUTS (control)'}: episode days {len(e)}  mean return per unit {e.mean():+.2f}  median {e.median():+.2f}  "
          f"hit >=10x {(e>=9).mean():.0%} | all other days {len(b)}  mean {b.mean():+.2f}  hit >=10x {(b>=9).mean():.1%} | diff CI [{np.percentile(bs,2.5):+.2f},{np.percentile(bs,97.5):+.2f}]")
    if typ == "C": print("   per episode:", e.round(1).to_dict())
