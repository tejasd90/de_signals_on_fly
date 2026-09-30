"""Does the score actually PAY? Held-out expectancy, not AUC.

The score is direction-agnostic -- it claims "a big move is likely", not which
way. So the natural trade is a basket of BOTH calls and puts, 2-15% OTM, which is
exactly what day_option_ev.parquet averages. Days are equal-weighted: one decision
per day, buy the basket or do not.

Everything below is HELD-OUT. The spec, the model coefficients and the split were
all fixed before this file existed.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from pascore_eval import load, add_age, cols_for
warnings.filterwarnings("ignore")

BEST = ("harmonic", 500, 0.002)
COST = 0.0826

J = add_age(load()); J = J[np.isfinite(J.y)]
cut = J.index[int(len(J)*0.6)]
cols = cols_for(*BEST)
tr, te = J[J.index < cut], J[J.index >= cut]

Xtr, Xte = tr[cols].to_numpy(), te[cols].to_numpy()
a, b = np.isfinite(Xtr).all(1), np.isfinite(Xte).all(1)
mu, sd = Xtr[a].mean(0), Xtr[a].std(0)+1e-9
m = LogisticRegression(max_iter=2000, C=0.5).fit((Xtr[a]-mu)/sd, tr.y.to_numpy()[a])
T = te[b].copy(); T["score"] = m.predict_proba((Xte[b]-mu)/sd)[:,1]

EV = pd.read_parquet("data/day_option_ev2.parquet")
T = T.reset_index().rename(columns={"index":"day"})
if "day" not in T.columns: T = T.rename(columns={T.columns[0]:"day"})
T["day"] = pd.to_datetime(T["day"])
M = T.merge(EV, on=["spot","day"], how="inner")
M = M[M.n >= 5]
print(f"held-out days with option data: {len(M)}   base medianEV {M.evcap.median():+.4f}  meanEV {M.evcap.mean():+.4f}")

wk = (M.day.dt.isocalendar().year.astype(str)+"W"+M.day.dt.isocalendar().week.astype(str)).to_numpy()
uw = np.unique(wk); ix = {w: np.where(wk==w)[0] for w in uw}
rng = np.random.default_rng(3)
def boot(vals_sel, vals_rest, n=4000):
    out=[]
    for _ in range(n):
        p = np.concatenate([ix[w] for w in rng.choice(uw, len(uw), True)])
        A_, B_ = vals_sel[p], vals_rest[p]
        sa, sb = A_[~np.isnan(A_)], B_[~np.isnan(B_)]
        if len(sa) and len(sb): out.append(sa.mean()-sb.mean())
    return np.array(out)

M["q"] = pd.qcut(M.score, 5, labels=False, duplicates="drop")
# MEDIAN and share-positive lead. The mean is shown last and small, because on a
# lottery payoff it is the statistic that a single broken mark can capture -- which
# is exactly what happened with the uncapped version (one day = 53% of the total).
print(f"\n{'quintile':<9}{'days':>6}{'medianEV':>11}{'%days+':>9}{'meanEV':>10}{'P(100x day)':>13}")
for q,g in M.groupby("q"):
    print(f"Q{int(q)+1:<8}{len(g):>6}{g.evcap.median():>11.4f}{g.pos.mean()*100:>8.1f}%"
          f"{g.evcap.mean():>10.4f}{g.y.mean()*100:>12.1f}%")

top = M.q == M.q.max()
sel = np.where(top, M.evcap, np.nan); rest = np.where(~top, M.evcap, np.nan)
d = boot(sel, rest)
print(f"\ntop quintile MEDIAN EV {M.evcap[top].median():+.4f}  vs rest {M.evcap[~top].median():+.4f}")
print(f"top quintile %days+ {M.pos[top].mean()*100:.1f}%  vs rest {M.pos[~top].mean()*100:.1f}%")
print(f"top quintile mean EV {M.evcap[top].mean():+.4f}  vs rest {M.evcap[~top].mean():+.4f}"
      f"   diff {M.evcap[top].mean()-M.evcap[~top].mean():+.4f}   P(diff>0) {(d>0).mean():.3f}")
# rank test: immune to the outlier problem entirely
from scipy.stats import mannwhitneyu
u = mannwhitneyu(M.evcap[top], M.evcap[~top], alternative="greater")
print(f"Mann-Whitney (rank-based, outlier-immune): p={u.pvalue:.4f}")

# is the top quintile positive in ABSOLUTE terms -- the only thing that matters
e = M.evcap[top].to_numpy(); wt = wk[top.to_numpy()]
uw2 = np.unique(wt); ix2 = {w: np.where(wt==w)[0] for w in uw2}
bb = np.array([e[np.concatenate([ix2[w] for w in rng.choice(uw2,len(uw2),True)])].mean() for _ in range(4000)])
print(f"top quintile absolute EV {e.mean():+.4f}   P(EV>0) {(bb>0).mean():.3f}"
      f"   95% CI [{np.percentile(bb,2.5):+.4f},{np.percentile(bb,97.5):+.4f}]")

# and combined with the one surviving feature
both = M[(M.q==M.q.max()) & (M.old_line==1)]
if len(both) > 15:
    e2 = both.evcap.to_numpy()
    w2 = (both.day.dt.isocalendar().year.astype(str)+"W"+both.day.dt.isocalendar().week.astype(str)).to_numpy()
    u2 = np.unique(w2); i2 = {w: np.where(w2==w)[0] for w in u2}
    b2 = np.array([e2[np.concatenate([i2[w] for w in rng.choice(u2,len(u2),True)])].mean() for _ in range(4000)])
    print(f"\ntop quintile AND old_line: n={len(both)}  medianEV {np.median(e2):+.4f}  "
          f"%days+ {both.pos.mean()*100:.1f}%  meanEV {e2.mean():+.4f}  "
          f"P(mean>0) {(b2>0).mean():.3f}   P(100x day) {both.y.mean()*100:.1f}%")
