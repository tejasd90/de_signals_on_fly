"""Try to break the price-action score.

pascore_eval gave held-out AUC 0.604, all 24 specs in 0.555-0.628, and +20.1pp
inside old-line days. Before any of that is believed it has to survive the checks
that killed the apex result yesterday -- where BTC said +33pp and ETH said the
opposite, and only a per-asset split exposed it.

  1. PER ASSET. Pooled results hide disagreement. If BTC and ETH point different
     ways, it is noise, however good the pooled number looks.
  2. SIGNIFICANCE with weeks as the unit, not days. Adjacent days share setups.
  3. WHICH COMPONENTS carry it -- and specifically whether his own rules do the
     work or whether the additions (dispersion, rejection magnitude) do.
  4. A SHUFFLE control: same pipeline, labels permuted in weekly blocks. Should
     return AUC ~0.5. If it does not, the pipeline leaks.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from pascore_eval import load, add_age, cols_for, COMPS, TFS
warnings.filterwarnings("ignore")

BEST = ("harmonic", 500, 0.002)      # chosen on TRAIN in pascore_eval; kept fixed

def fit(tr, te, cols):
    Xtr, Xte = tr[cols].to_numpy(), te[cols].to_numpy()
    a, b = np.isfinite(Xtr).all(1), np.isfinite(Xte).all(1)
    mu, sd = Xtr[a].mean(0), Xtr[a].std(0) + 1e-9
    m = LogisticRegression(max_iter=2000, C=0.5).fit((Xtr[a]-mu)/sd, tr.y.to_numpy()[a])
    return m, mu, sd, b, m.predict_proba((Xte[b]-mu)/sd)[:,1]

def wboot_auc(y, s, weeks, n=3000, seed=0):
    rng = np.random.default_rng(seed)
    uw = np.unique(weeks); idx = {w: np.where(weeks == w)[0] for w in uw}
    out = []
    for _ in range(n):
        pick = np.concatenate([idx[w] for w in rng.choice(uw, len(uw), True)])
        yy = y[pick]
        if 0 < yy.mean() < 1: out.append(roc_auc_score(yy, s[pick]))
    return np.array(out)

J = add_age(load()); J = J[np.isfinite(J.y)]
cut = J.index[int(len(J)*0.6)]
cols = cols_for(*BEST)

print("=== 1. PER ASSET (the check that killed apex) ===")
for spot in ("BTC","ETH"):
    Js = J[J.spot == spot]
    tr, te = Js[Js.index < cut], Js[Js.index >= cut]
    if len(te) < 80: print(f"  {spot}: too few"); continue
    _,_,_, b, s = fit(tr, te, cols)
    T = te[b]; y = T.y.to_numpy()
    wk = (T.index.isocalendar().year.astype(str)+"W"+T.index.isocalendar().week.astype(str)).to_numpy()
    bt = wboot_auc(y, s, wk)
    print(f"  {spot}: held-out n={len(T)}  base {y.mean():.3f}  AUC {roc_auc_score(y,s):.3f}"
          f"   P(AUC>0.5) {(bt>0.5).mean():.3f}   95% CI [{np.percentile(bt,2.5):.3f},{np.percentile(bt,97.5):.3f}]")

print("\n=== 2. POOLED significance, weeks as unit ===")
tr, te = J[J.index < cut], J[J.index >= cut]
_,_,_, b, s = fit(tr, te, cols)
T = te[b]; y = T.y.to_numpy()
wk = (T.index.isocalendar().year.astype(str)+"W"+T.index.isocalendar().week.astype(str)).to_numpy()
bt = wboot_auc(y, s, wk)
print(f"  AUC {roc_auc_score(y,s):.3f}   P(AUC>0.5) {(bt>0.5).mean():.3f}"
      f"   95% CI [{np.percentile(bt,2.5):.3f},{np.percentile(bt,97.5):.3f}]")

old = T.old_line.to_numpy()
sub = T[old==1]
if len(sub) > 40:
    hi = (sub.score if "score" in sub else pd.Series(s[old==1], index=sub.index))
    med = np.median(s[old==1]); ys = sub.y.to_numpy(); ss = s[old==1]
    wks = (sub.index.isocalendar().year.astype(str)+"W"+sub.index.isocalendar().week.astype(str)).to_numpy()
    rng = np.random.default_rng(1); uw = np.unique(wks); ix = {w: np.where(wks==w)[0] for w in uw}
    d = []
    for _ in range(3000):
        p = np.concatenate([ix[w] for w in rng.choice(uw, len(uw), True)])
        a_, b_ = ys[p][ss[p]>=med], ys[p][ss[p]<med]
        if len(a_) and len(b_): d.append(a_.mean()-b_.mean())
    d = np.array(d)
    print(f"  within old_line (n={len(sub)}): hi {ys[ss>=med].mean()*100:.1f}% vs "
          f"lo {ys[ss<med].mean()*100:.1f}%  diff {100*(ys[ss>=med].mean()-ys[ss<med].mean()):+.1f}pp"
          f"   P(diff>0) {(d>0).mean():.3f}")

print("\n=== 3. WHICH COMPONENTS carry it (standardised coefs) ===")
m, mu, sd, _, _ = fit(tr, te, cols)
names = [f"{c}|{tf}" for tf in TFS for c in COMPS]
co = sorted(zip(names, m.coef_[0]), key=lambda t: -abs(t[1]))
for nm, v in co: print(f"   {nm:<16}{v:+.3f}")
his  = sum(abs(v) for nm,v in co if nm.split("|")[0] in ("hits","novel","ovl"))
mine = sum(abs(v) for nm,v in co if nm.split("|")[0] in ("disp","rejmag","side","round"))
print(f"   |coef| from HIS rules (hits/novel/ovl): {his:.2f}")
print(f"   |coef| from ADDED    (disp/rejmag/side/round): {mine:.2f}")

print("\n=== 4. SHUFFLE CONTROL (weekly-block permuted labels; must give ~0.5) ===")
rng = np.random.default_rng(7)
aucs = []
for _ in range(25):
    Jp = J.copy()
    wkall = (Jp.index.isocalendar().year.astype(str)+"W"+Jp.index.isocalendar().week.astype(str)).to_numpy()
    uw = np.unique(wkall)
    perm = dict(zip(uw, rng.permutation(uw)))
    src = {w: Jp.y.to_numpy()[wkall==w] for w in uw}
    newy = np.concatenate([np.resize(src[perm[w]], (wkall==w).sum()) for w in uw])
    order = np.concatenate([np.where(wkall==w)[0] for w in uw])
    yy = np.empty(len(Jp)); yy[order] = newy; Jp["y"] = yy
    trp, tep = Jp[Jp.index < cut], Jp[Jp.index >= cut]
    try:
        _,_,_, bb, ss2 = fit(trp, tep, cols)
        aucs.append(roc_auc_score(tep[bb].y.to_numpy(), ss2))
    except Exception: pass
aucs = np.array(aucs)
print(f"  shuffled held-out AUC: mean {aucs.mean():.3f}  min {aucs.min():.3f}  max {aucs.max():.3f}")
print(f"  real AUC {roc_auc_score(y,s):.3f}  -> beats {100*(roc_auc_score(y,s)>aucs).mean():.0f}% of shuffles")
