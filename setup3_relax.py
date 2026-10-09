"""Setup 3 with the analyst-added restrictions removed (2026-10-09, his request).
Kept rule: walk-forward quiet model, threshold 70th pct of in-sample P(quiet), ATM straddle, 1-3d to
expiry, 00:00 UTC. Here: every tte bucket (<=1d, 1-3d, 3-8d; straddles rebuilt from short_panel
exactly as short_cond.py), every 4h entry slot (the day's forecast is known at 00:00 UTC, so later
slots the same day are causal), thresholds 50/60/70/80/90. Net of the bid haircut and fees, % of spot.
CI: week-block bootstrap of quiet minus rest."""
import io, contextlib, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from short_base import load
with contextlib.redirect_stdout(io.StringIO()):
    import when_not_to_trade as W
P = load()
st = []
for a in ("BTC", "ETH"):
    Q = P[P.asset == a]; Q = Q.assign(dist=(Q.K - Q.S0).abs())
    Q = Q.loc[Q.groupby(["entry_t", "expiry", "typ"]).dist.idxmin()]
    for (t, e), g in Q.groupby(["entry_t", "expiry"]):
        if set(g.typ) != {"C", "P"} or g.K.nunique() != 1: continue
        st.append(dict(spot=a, t=int(t), tb=str(g.tb.iloc[0]), net=g.net.sum()))
T = pd.DataFrame(st); T["day"] = pd.to_datetime(T.t, unit="s").dt.normalize(); T["hr"] = pd.to_datetime(T.t, unit="s").dt.hour
M = W.M.copy(); X = W.BASE + W.cols; M["mo"] = pd.to_datetime(M.day).dt.to_period("M")
out = []
for mo in sorted(M.mo.unique()):
    tr = M[M.mo < mo]; te = M[M.mo == mo]
    if tr.day.nunique() < 180 or te.empty: continue
    y = (tr[W.TGT] < tr[W.TGT].quantile(1/3)).astype(int); mu, sd = tr[X].mean(), tr[X].std() + 1e-9
    m = LogisticRegression(max_iter=3000, C=0.5).fit((tr[X]-mu)/sd, y)
    p_tr = m.predict_proba((tr[X]-mu)/sd)[:, 1]
    te = te.assign(pq=m.predict_proba((te[X]-mu)/sd)[:, 1])
    for q in (.5, .6, .7, .8, .9): te[f"q{int(q*100)}"] = te.pq >= np.quantile(p_tr, q)
    out.append(te)
Qd = pd.concat(out); Qd["day"] = pd.to_datetime(Qd.day).dt.normalize()
J = T.merge(Qd[["spot", "day"] + [f"q{k}" for k in (50, 60, 70, 80, 90)]], on=["spot", "day"])
print(f"straddles held out: {len(J):,}  {J.day.min().date()} -> {J.day.max().date()}")
rng = np.random.default_rng(0)
def cmp(g, col):
    q, n = g[g[col]], g[~g[col]]
    if len(q) < 15 or len(n) < 15: return f"n {len(q)}: too few"
    wk = (g.t // (7*86400)).values; u = np.unique(wk); ix = {w: np.where(wk == w)[0] for w in u}; d = []
    for _ in range(800):
        s = np.concatenate([ix[w] for w in rng.choice(u, len(u))]); qq = g[col].values[s]; v = g.net.values[s]
        if qq.sum() and (~qq).sum(): d.append(v[qq].mean() - v[~qq].mean())
    d = np.array(d)
    return f"quiet {q.net.mean():+.3f}% (n {len(q):>4}) rest {n.net.mean():+.3f}%  diff CI [{np.percentile(d,2.5):+.2f},{np.percentile(d,97.5):+.2f}] P<=0 {(d<=0).mean():.3f}"
print("\nA. tte x entry hour, threshold 70 (kept rule = 1-3d @ 00)")
for tb in ("<=1d", "1-3d", "3-8d"):
    for hr in (0, 4, 8, 12, 16, 20):
        print(f"  {tb:<5} {hr:02d}:00  {cmp(J[(J.tb == tb) & (J.hr == hr)], 'q70')}")
    print(f"  {tb:<5} all hrs {cmp(J[J.tb == tb], 'q70')}")
print("\nB. threshold sweep, all entry hours pooled")
for tb in ("<=1d", "1-3d", "3-8d"):
    for k in (50, 60, 70, 80, 90): print(f"  {tb:<5} q{k}  {cmp(J[J.tb == tb], f'q{k}')}")
print("\nC. kept rule cell (1-3d @ 00) by threshold")
for k in (50, 60, 70, 80, 90): print(f"  q{k}  {cmp(J[(J.tb == '1-3d') & (J.hr == 0)], f'q{k}')}")
