"""Seller reframe of when_not_to_trade: the days the buyer should skip (predicted
quiet) are the days a straddle SELLER wants. Held-out days only (the model's
own test split). Entry = the 00:00 UTC straddle of that day, so the prediction
(built from data up to the previous close) is known at entry.

The market already prices quiet into IV, so the honest question is whether
P(quiet) adds over IV: report within IV terciles too."""
import io, contextlib, numpy as np, pandas as pd
with contextlib.redirect_stdout(io.StringIO()):
    import when_not_to_trade as W
te = W.te[["spot","day","pquiet",W.TGT]].copy()
te["t"] = (pd.to_datetime(te.day).astype("int64")//10**9).astype(int)
# anti-leak check 1: same-day vs next-day
te = te.sort_values(["spot","day"]); te["next"] = te.groupby("spot")[W.TGT].shift(-1)
print(f"corr(pquiet, range today) {te.pquiet.corr(te[W.TGT]):+.3f}   corr(pquiet, range tomorrow) {te.pquiet.corr(te.next):+.3f}")
T = pd.read_parquet("data/short_straddles.parquet").rename(columns={"asset":"spot"})
J = T.merge(te[["spot","t","pquiet"]], on=["spot","t"])
print(f"{len(J)} straddles entered 00:00 UTC on held-out days ({J.t.min()} .. {J.t.max()})")
cut = te.pquiet.quantile(.7)
J["quiet"] = J.pquiet >= cut
def boot(a, b, g):
    wk = (g.t//(7*86400)).values; u = np.unique(wk); ix = {w: np.where(wk==w)[0] for w in u}
    rng = np.random.default_rng(0); out = []
    for _ in range(2000):
        s = np.concatenate([ix[w] for w in rng.choice(u, len(u))]); q = g.quiet.values[s]; v = g.net.values[s]
        if q.sum() and (~q).sum(): out.append(v[q].mean() - v[~q].mean())
    return np.percentile(out, [2.5, 97.5]), (np.array(out) <= 0).mean()
for tb, g in J.groupby("tb", observed=True):
    q, n = g[g.quiet], g[~g.quiet]; ci, p = boot(q, n, g)
    print(f"\n tte {tb}: QUIET-predicted n={len(q)} net {q.net.mean():+.3f}% win {q.win.mean():.0%} worst {q.net.min():+.1f}"
          f" | rest n={len(n)} net {n.net.mean():+.3f}% win {n.win.mean():.0%} worst {n.net.min():+.1f}"
          f" | diff CI [{ci[0]:+.3f},{ci[1]:+.3f}] P<=0 {p:.3f}")
    g = g.assign(ivt=pd.qcut(g.iv, 3, labels=["lowIV","midIV","highIV"]))
    for it, h in g.groupby("ivt", observed=True):
        print(f"     {it}: quiet {h[h.quiet].net.mean():+.3f}% (n={h.quiet.sum()})   rest {h[~h.quiet].net.mean():+.3f}% (n={(~h.quiet).sum()})")
