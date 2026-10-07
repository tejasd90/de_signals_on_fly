"""The practical form: how many days do you sit out, and what do you give up?

pascore_vs_vol showed the score adds ~0.05 AUC over a plain volatility baseline
for vol-adjusted range, on BOTH assets, on both the BIG and the QUIET side. AUC is
not a decision. This turns it into one:

  rank held-out days by P(quiet). Skip the top N%. Report what you AVOID (quiet
  days, where a futures trade has no room) against what you MISS (big days).

A filter is worth having only if it avoids materially more dead days than the
opportunities it costs. The break-even line is the base rate: skipping days at
random avoids and misses in equal proportion.

Overtrading is his stated problem, so the asymmetry matters more than the AUC:
a filter that cuts 30% of days and removes 40% of the dead ones while costing 20%
of the good ones is worth real money even at AUC 0.62.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from pascore_futures import build
from pascore_eval import cols_for
warnings.filterwarnings("ignore")

SPEC = ("harmonic", 500, 0.002)
TGT = "rangeatr"
M = build().sort_values(["spot","day"])
cols = cols_for(*SPEC)
g = M.groupby("spot")
M["v_absret"] = g["absret"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_range"]  = g["rangeatr"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_atrpct"] = M.atr_prev / g["c"].shift(1)        # previous close: day D's close is not known at D's open (review D4)
BASE = ["v_absret","v_range","v_atrpct"]
M = M.dropna(subset=cols+BASE+[TGT])
cut = M.day.quantile(0.6)
tr, te = M[M.day < cut], M[M.day >= cut]

lo, hi = tr[TGT].quantile(1/3), tr[TGT].quantile(2/3)
ytr = (tr[TGT] < lo).astype(int)
Xtr, Xte = tr[BASE+cols].to_numpy(), te[BASE+cols].to_numpy()
mu, sd = Xtr.mean(0), Xtr.std(0)+1e-9
m = LogisticRegression(max_iter=3000, C=0.5).fit((Xtr-mu)/sd, ytr)
te = te.copy(); te["pquiet"] = m.predict_proba((Xte-mu)/sd)[:,1]
te["dead"] = (te[TGT] < lo).astype(int)     # no room for a futures trade
te["good"] = (te[TGT] > hi).astype(int)     # the days worth showing up for

nd, ng = te.dead.sum(), te.good.sum()
print(f"held-out {len(te)} days:  {nd} dead ({nd/len(te)*100:.0f}%)  "
      f"{ng} good ({ng/len(te)*100:.0f}%)   target={TGT}\n")
print(f"{'skip top':<10}{'days sat out':>14}{'dead avoided':>15}{'good missed':>14}"
      f"{'edge':>8}   {'median range/ATR kept':>22}")
for frac in (0.1, 0.2, 0.3, 0.4, 0.5):
    k = int(len(te)*frac)
    skip = te.nlargest(k, "pquiet")
    keep = te.drop(skip.index)
    da, gm = skip.dead.sum()/nd, skip.good.sum()/ng
    print(f"{frac*100:>7.0f}%{k:>14}{da*100:>14.1f}%{gm*100:>13.1f}%"
          f"{(da-gm)*100:>+7.1f}pp{keep[TGT].median():>22.3f}")
print("\nedge = dead avoided minus good missed. 0 = no better than skipping at random.")

print("\nper asset, skipping the top 30%:")
for spot in ("BTC","ETH"):
    s = te[te.spot == spot]
    if len(s) < 60: continue
    k = int(len(s)*0.3); sk = s.nlargest(k, "pquiet")
    d_, g_ = s.dead.sum(), s.good.sum()
    if d_ and g_:
        print(f"  {spot}: dead avoided {sk.dead.sum()/d_*100:5.1f}%   "
              f"good missed {sk.good.sum()/g_*100:5.1f}%   edge "
              f"{(sk.dead.sum()/d_ - sk.good.sum()/g_)*100:+.1f}pp")

# ---------- is the asymmetry luck? ----------
print("\n=== significance of the skip-30% edge (weekly blocks) ===")
rng = np.random.default_rng(11)
wk = (te.day.dt.isocalendar().year.astype(str)+"W"+te.day.dt.isocalendar().week.astype(str)).to_numpy()
uw = np.unique(wk); ix = {w: np.where(wk == w)[0] for w in uw}
edges = []
for _ in range(4000):
    p = np.concatenate([ix[w] for w in rng.choice(uw, len(uw), True)])
    s = te.iloc[p]
    k = int(len(s)*0.3)
    sk = s.nlargest(k, "pquiet")
    d_, g_ = s.dead.sum(), s.good.sum()
    if d_ and g_: edges.append(sk.dead.sum()/d_ - sk.good.sum()/g_)
edges = np.array(edges)
print(f"  edge {edges.mean()*100:+.1f}pp   P(edge>0) {(edges>0).mean():.3f}"
      f"   95% CI [{np.percentile(edges,2.5)*100:+.1f}, {np.percentile(edges,97.5)*100:+.1f}]pp")

# random-skip control: same number of days, chosen at random
ctrl = []
for _ in range(4000):
    k = int(len(te)*0.3)
    sk = te.iloc[rng.choice(len(te), k, replace=False)]
    ctrl.append(sk.dead.sum()/nd - sk.good.sum()/ng)
ctrl = np.array(ctrl)
print(f"  random-skip control: {ctrl.mean()*100:+.1f}pp  (95% of draws within "
      f"[{np.percentile(ctrl,2.5)*100:+.1f}, {np.percentile(ctrl,97.5)*100:+.1f}]pp)")
real = te.nlargest(int(len(te)*0.3),"pquiet")
r = real.dead.sum()/nd - real.good.sum()/ng
print(f"  actual {r*100:+.1f}pp -> beats {100*(r>ctrl).mean():.1f}% of random skips")
