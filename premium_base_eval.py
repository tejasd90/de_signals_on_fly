"""Evaluate premium_base.py events: parabola-of-higher-lows bases vs cheap options still making new lows,
matched on time-to-expiry x moneyness x cheapness cells (controls reweighted to the pattern's mix).
MARK peaks (max high after the bar, to settlement) / close at the bar. EV = p*T - 1 - 0.0826."""
import numpy as np, pandas as pd
COST = 0.0826; TS = [5, 10, 25, 50, 100]
R = pd.read_parquet("data/premium_base.parquet").dropna(subset=["peak"])
R["otm"] = np.where(R.typ == "C", R.K / R.spot - 1, 1 - R.K / R.spot) * 100
R["cheap"] = R.prem / R.spot * 100
R["tb"] = pd.cut(R.tte_h, [12, 24, 48, 96, 1e4]); R["mb"] = pd.cut(R.otm, [-50, 0, 1, 2, 4, 50]); R["cb"] = pd.cut(R.cheap, [0, .02, .05, .1, .2, 10])
R["cell"] = R.tb.astype(str) + "|" + R.mb.astype(str) + "|" + R.cb.astype(str)
R["week"] = pd.to_datetime(R.t, unit="s").dt.to_period("W").astype(str); R["yr"] = pd.to_datetime(R.t, unit="s").dt.year
P, C = R[R.kind == "pattern"], R[R.kind == "control"]
w = P.cell.value_counts(normalize=True); cc = C.cell.value_counts(normalize=True)
C = C[C.cell.isin(w.index)].copy(); C["w"] = C.cell.map(w / cc)
def rate(df, T, wcol=None):
    x = (df.peak >= T).astype(float)
    return np.average(x, weights=df[wcol]) if wcol else x.mean()
print(f"pattern events {len(P)}  matched controls {len(C)} (cells {P.cell.nunique()})")
print(f"{'target':>7} {'pattern':>9} {'control (matched)':>18} {'EV pattern':>11} {'EV control':>11}")
for T in TS:
    a, b = rate(P, T), rate(C, T, "w")
    print(f"{T:>6}x {a:>9.2%} {b:>18.2%} {T*a-1-COST:>+11.2f} {T*b-1-COST:>+11.2f}")
rng = np.random.default_rng(0); wk = R.week.unique(); gp = {k: g for k, g in P.groupby("week")}; gc = {k: g for k, g in C.groupby("week")}
for T in (10, 25):
    d = []
    for _ in range(1500):
        s = rng.choice(wk, len(wk))
        pp = pd.concat([gp[k] for k in s if k in gp]); cc_ = pd.concat([gc[k] for k in s if k in gc])
        d.append(rate(pp, T) - rate(cc_, T, "w"))
    print(f"  {T}x difference, week-block CI [{np.percentile(d,2.5):+.2%},{np.percentile(d,97.5):+.2%}]  P<=0 {(np.array(d)<=0).mean():.3f}")
print("\nby type / year / asset (25x and 10x, pattern vs matched control):")
for col in ("typ", "yr", "asset"):
    for k, g in P.groupby(col):
        cg = C[C[col] == k]
        print(f"  {col}={k}: pattern n {len(g):>4}  10x {rate(g,10):.1%} vs {rate(cg,10,'w') if len(cg) else np.nan:.1%}   25x {rate(g,25):.2%} vs {rate(cg,25,'w') if len(cg) else np.nan:.2%}")
print("\npattern events per week:", round(len(P) / R.week.nunique(), 1), " distinct (asset, day):", P.assign(d=pd.to_datetime(P.t, unit='s').dt.date).groupby(['asset','d']).ngroups)
