"""Does the score beat plain recent volatility, or just restate it?

pascore_futures flagged that the score explains YESTERDAY's range better than
tomorrow's (rho +0.239 vs +0.205 for rangeatr, +0.227 vs +0.174 for mfe). Nothing
is being peeked at -- the features are legitimately known before the day. The
likely story is duller: the score is a VOLATILITY GAUGE, and volatility clusters,
so it looks predictive only by knowing what just happened.

If so it is redundant with a baseline any chart gives away free. The test:

  BASELINE   recent |return|, recent range/ATR, ATR/price -- 3 trivial features
  +SCORE     baseline plus the 14 pascore components

If +SCORE does not beat BASELINE out of sample, the idea adds nothing over ATR,
however good its standalone AUC looks.

Reported for both directions of the question, because the negative side is the one
he actually needs: predicting QUIET days (bottom tercile) matters more than
predicting explosive ones, given overtrading is the stated problem.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from pascore_futures import build, TARGETS
from pascore_eval import cols_for
warnings.filterwarnings("ignore")

SPEC = ("harmonic", 500, 0.002)
M = build()
cols = cols_for(*SPEC)

# trivial baseline, known before day D
M = M.sort_values(["spot","day"])
g = M.groupby("spot")
M["v_absret"]  = g["absret"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_range"]   = g["rangeatr"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_atrpct"]  = g.apply(lambda d: (d.atr_prev / d.c).shift(0), include_groups=False).reset_index(level=0, drop=True)
BASE = ["v_absret", "v_range", "v_atrpct"]

M = M.dropna(subset=cols + BASE + TARGETS)
cut = M.day.quantile(0.6)
tr, te = M[M.day < cut], M[M.day >= cut]
print(f"train {len(tr)}  held-out {len(te)}\n")

def auc_for(feats, ytr, yte):
    Xtr, Xte = tr[feats].to_numpy(), te[feats].to_numpy()
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    m = LogisticRegression(max_iter=3000, C=0.5).fit((Xtr-mu)/sd, ytr)
    return roc_auc_score(yte, m.predict_proba((Xte-mu)/sd)[:,1])

print(f"{'target':<10}{'side':<8}{'baseline':>10}{'+score':>9}{'gain':>8}   verdict")
for tgt in TARGETS:
    for side in ("BIG", "QUIET"):
        if side == "BIG":
            thr = tr[tgt].quantile(2/3)
            ytr, yte = (tr[tgt] > thr).astype(int), (te[tgt] > thr).astype(int)
        else:
            thr = tr[tgt].quantile(1/3)
            ytr, yte = (tr[tgt] < thr).astype(int), (te[tgt] < thr).astype(int)
        if ytr.nunique() < 2 or yte.nunique() < 2: continue
        a = auc_for(BASE, ytr, yte)
        b = auc_for(BASE + cols, ytr, yte)
        v = "adds" if b - a > 0.02 else ("redundant" if b - a > -0.02 else "HURTS")
        print(f"{tgt:<10}{side:<8}{a:>10.3f}{b:>9.3f}{b-a:>+8.3f}   {v}")

# ---------- the checks that killed apex and pascore-v1 ----------
print("\n=== PER ASSET + weekly-block significance, for the two targets that added ===")
from fastboot import week_codes
def fit_scores(feats, ytr):
    Xtr, Xte = tr[feats].to_numpy(), te[feats].to_numpy()
    mu, sd = Xtr.mean(0), Xtr.std(0)+1e-9
    m = LogisticRegression(max_iter=3000, C=0.5).fit((Xtr-mu)/sd, ytr)
    return m.predict_proba((Xte-mu)/sd)[:,1]

def boot_gain(y, sa, sb, weeks, n=3000, seed=0):
    """P(AUC(+score) > AUC(baseline)) under weekly resampling."""
    rng = np.random.default_rng(seed)
    uw = np.unique(weeks); ix = {w: np.where(weeks == w)[0] for w in uw}
    out = []
    for _ in range(n):
        p = np.concatenate([ix[w] for w in rng.choice(uw, len(uw), True)])
        yy = y[p]
        if yy.min() == yy.max(): continue
        out.append(roc_auc_score(yy, sb[p]) - roc_auc_score(yy, sa[p]))
    return np.array(out)

wk = (te.day.dt.isocalendar().year.astype(str)+"W"+te.day.dt.isocalendar().week.astype(str)).to_numpy()
for tgt in ("rangeatr", "mfe"):
    for side in ("QUIET", "BIG"):
        if side == "BIG":
            thr = tr[tgt].quantile(2/3)
            ytr, yte = (tr[tgt] > thr).astype(int), (te[tgt] > thr).astype(int).to_numpy()
        else:
            thr = tr[tgt].quantile(1/3)
            ytr, yte = (tr[tgt] < thr).astype(int), (te[tgt] < thr).astype(int).to_numpy()
        sa, sb = fit_scores(BASE, ytr), fit_scores(BASE+cols, ytr)
        d = boot_gain(yte, sa, sb, wk)
        line = (f"{tgt:<9}{side:<7} pooled gain {roc_auc_score(yte,sb)-roc_auc_score(yte,sa):+.3f}"
                f"  P(gain>0) {(d>0).mean():.3f}   ")
        per = []
        for spot in ("BTC","ETH"):
            m_ = (te.spot == spot).to_numpy()
            if m_.sum() > 60 and len(np.unique(yte[m_])) > 1:
                per.append(f"{spot} {roc_auc_score(yte[m_],sb[m_])-roc_auc_score(yte[m_],sa[m_]):+.3f}")
        print(line + "  ".join(per))
