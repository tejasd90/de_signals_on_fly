"""Walk-forward version of the quiet-day predictor (when_not_to_trade.py), so the straddle-
seller test in quiet_sell.py gets 2+ years of held-out days instead of ~6 months.
Same features and target; the model is refit at the start of every month on all earlier days
(expanding window, minimum 180 days) and scores only that month. Then the 00:00 UTC short
straddle on predicted-quiet days (top 30% of P(quiet) within the training window) vs the rest."""
import io, contextlib, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
with contextlib.redirect_stdout(io.StringIO()):
    import when_not_to_trade as W
M = W.M.copy(); X = W.BASE + W.cols; M["mo"] = pd.to_datetime(M.day).dt.to_period("M")
out = []
for mo in sorted(M.mo.unique()):
    tr = M[M.mo < mo]; te = M[M.mo == mo]
    if tr.day.nunique() < 180 or te.empty: continue
    lo = tr[W.TGT].quantile(1/3); y = (tr[W.TGT] < lo).astype(int)
    mu, sd = tr[X].mean(), tr[X].std() + 1e-9
    m = LogisticRegression(max_iter=3000, C=0.5).fit((tr[X]-mu)/sd, y)
    p_tr = m.predict_proba((tr[X]-mu)/sd)[:, 1]; cut = np.quantile(p_tr, 0.7)
    te = te.assign(pquiet=m.predict_proba((te[X]-mu)/sd)[:, 1]); te["quiet"] = te.pquiet >= cut
    out.append(te[["spot","day","pquiet","quiet",W.TGT]])
Q = pd.concat(out); Q["t"] = (pd.to_datetime(Q.day).astype("int64")//10**9).astype(int)
print(f"walk-forward held-out days: {len(Q)} ({Q.day.min()} .. {Q.day.max()}); flagged quiet {Q.quiet.mean():.0%}")
T = pd.read_parquet("data/short_straddles.parquet").rename(columns={"asset":"spot"})
J = T.merge(Q[["spot","t","quiet"]], on=["spot","t"])
rng = np.random.default_rng(0)
for tb, g in J.groupby("tb", observed=True):
    q, n = g[g.quiet], g[~g.quiet]
    wk = (g.t//(7*86400)).values; u = np.unique(wk); ix = {w: np.where(wk == w)[0] for w in u}; d = []
    for _ in range(3000):
        s = np.concatenate([ix[w] for w in rng.choice(u, len(u))]); qq = g.quiet.values[s]; v = g.net.values[s]
        if qq.sum() and (~qq).sum(): d.append(v[qq].mean() - v[~qq].mean())
    print(f" tte {tb}: QUIET n={len(q)} net {q.net.mean():+.3f}% win {q.win.mean():.0%} worst {q.net.min():+.1f}% p5 {q.net.quantile(.05):+.1f}%"
          f" | rest n={len(n)} net {n.net.mean():+.3f}% worst {n.net.min():+.1f}% p5 {n.net.quantile(.05):+.1f}%"
          f" | diff CI [{np.percentile(d,2.5):+.3f},{np.percentile(d,97.5):+.3f}] P<=0 {(np.array(d)<=0).mean():.3f}")
    g = g.assign(yr=pd.to_datetime(g.t, unit="s").dt.year)
    print("     by year (quiet - rest):", {y: round(h[h.quiet].net.mean() - h[~h.quiet].net.mean(), 3) for y, h in g.groupby("yr")})
