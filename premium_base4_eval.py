"""Evaluate premium_base4.py (RISING parabola only, no decay required; decay is a matching cell and a
reported slice, never a filter). Derived from premium_base3_eval.py.

Evaluate premium_base3.py: the parabola vs the same moment without it, matched within
timeframe x time-to-expiry x moneyness x decay cells (and, separately, also on how far the premium has
already recovered from its bottom). Reported per timeframe, with no tte or cheapness restriction. Plus
his chain point: the recognisable strike vs the next 1-3 strikes further OTM at the same bar.
MARK outcome: max high after the bar to settlement / close. EV = P*T - 1 - 0.0826."""
import numpy as np, pandas as pd
COST = 0.0826
R = pd.read_parquet("data/premium_base4.parquet")
R["otm"] = np.where(R.typ == "C", R.K / R.spot - 1, 1 - R.K / R.spot) * 100
R["rec"] = R.prem / R.bottom
R["tb"] = pd.cut(R.tte_h, [0, 6, 24, 72, 168, 1e5]).astype(str)
R["mb"] = pd.cut(R.otm, [-100, -2, 0, 1, 2, 4, 8, 100]).astype(str)
R["db"] = pd.cut(R.decay.clip(upper=1), [-0.01, .02, .05, .1, .15, .3, .6, 1.0]).astype(str)
R["rb"] = pd.cut(R.rec, [0, 1.1, 1.5, 2, 3, 1e9]).astype(str)
R["week"] = pd.to_datetime(R.t, unit="s").dt.to_period("W").astype(str); R["yr"] = pd.to_datetime(R.t, unit="s").dt.year
rng = np.random.default_rng(0)

def compare(df, cells, T, boot=True):
    df = df.assign(cell=df[cells].astype(str).agg("|".join, axis=1))
    P, C = df[df.kind == "pattern"], df[df.kind == "control"]
    w = P.cell.value_counts(normalize=True); cc = C.cell.value_counts(normalize=True)
    C = C[C.cell.isin(w.index)]; C = C.assign(w=C.cell.map(w / cc))
    P = P[P.cell.isin(cc.index)]
    if len(P) < 30 or len(C) < 30: return None
    a = (P.peak >= T).mean(); b = np.average(C.peak >= T, weights=C.w)
    ci = ""
    if boot:
        wk = df.week.unique(); gp = {k: g for k, g in P.groupby("week")}; gc = {k: g for k, g in C.groupby("week")}
        d = []
        for _ in range(200):
            s = rng.choice(wk, len(wk)); pp = [gp[k] for k in s if k in gp]; q = [gc[k] for k in s if k in gc]
            if pp and q:
                pp = pd.concat(pp); q = pd.concat(q); d.append((pp.peak >= T).mean() - np.average(q.peak >= T, weights=q.w))
        d = np.array(d); ci = f"diff CI [{np.percentile(d,2.5):+.1%},{np.percentile(d,97.5):+.1%}] P(<=0) {(d<=0).mean():.2f}"
    return len(P), len(C), a, b, ci

base = ["tf", "tb", "mb", "db"]
for lab, cells in (("A. matched on timeframe, time-to-expiry, moneyness, decay", base),
                   ("B. ...and on how far it has already recovered from the bottom", base + ["rb"])):
    print(f"\n{lab}")
    for T in (5, 10, 25, 100):
        r = compare(R, cells, T, boot=T in (10, 25))
        print(f"  {T:>3}x  pattern {r[2]:6.2%} (n {r[0]})  control {r[3]:6.2%} (n {r[1]})  EV {T*r[2]-1-COST:+.2f} vs {T*r[3]-1-COST:+.2f}  {r[4]}")
print("\nper timeframe / type / shape / year, 10x and 25x, matched as in A")
for col in ("tf", "typ", "yr", "asset", "tb", "mb", "db"):
    for k, g in R.groupby(col):
        r10 = compare(g, base, 10, False); r25 = compare(g, base, 25, False)
        if r10: print(f"  {col}={k:<14} n {r10[0]:>6}  10x {r10[2]:5.1%} vs {r10[3]:5.1%}   25x {r25[2]:5.2%} vs {r25[3]:5.2%}")
for lab, m in (("accelerating", R.accel), ("not accel.", ~R.accel), ("run of 3", R.runlen == 3), ("run 4-5", R.runlen.between(4, 5)), ("run 6+", R.runlen >= 6)):
    g = R[(R.kind == "control") | m]; r = compare(g, base, 25, False); r10 = compare(g, base, 10, False)
    print(f"  shape={lab:<10} n {r[0]:>6}  10x {r10[2]:5.1%} vs {r10[3]:5.1%}   25x {r[2]:5.2%} vs {r[3]:5.2%}")

print("\nDid his examples fire? (1h)")
ex = R[(R.kind == "pattern") & (R.tf == 60) & R.expiry.isin(["2026-10-02", "2026-10-09"]) & R.K.isin([80500, 81000, 87000]) & (R.asset == "BTC")]
print((ex.assign(ist=pd.to_datetime(ex.t, unit="s") + pd.Timedelta(hours=5.5))[["expiry", "typ", "K", "ist", "tte_h", "prem", "runlen", "accel", "peak"]].round(2).to_string(index=False)))
print("\nHis chain point: the strike showing the shape vs 1-3 strikes further OTM, same bar")
P = R[R.kind == "pattern"]
for s in (1, 2, 3):
    m = P[f"n{s}_prem"].notna()
    print(f"  +{s} strike: has the shape too {P.loc[m, f'n{s}_shape'].mean():.0%}   premium {np.median(P.loc[m, f'n{s}_prem'] / P.loc[m, 'prem']):.2f}x of the shown strike"
          f"   10x {(P.loc[m, f'n{s}_peak'] >= 10).mean():.1%} vs shown {(P.loc[m, 'peak'] >= 10).mean():.1%}   25x {(P.loc[m, f'n{s}_peak'] >= 25).mean():.2%} vs {(P.loc[m, 'peak'] >= 25).mean():.2%}")
m = P.n1_prem.notna()
for lab, mm in (("neighbour flat (no shape)", m & ~P.n1_shape.fillna(False).astype(bool)), ("neighbour shows it too", m & P.n1_shape.fillna(False).astype(bool))):
    g = P[mm]; print(f"  {lab:<26} n {len(g):>6}: shown strike 25x {(g.peak>=25).mean():.2%}, +1 strike 25x {(g.n1_peak>=25).mean():.2%}")
