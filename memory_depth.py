"""Does the Tier-2 filter actually need its long memory?

The light-box result (LIGHTBOX.md) found performance rising monotonically as the
model grew MORE opaque, best at ~7 bodies of memory -- and five separate
formulations of long-range structure have now failed. But Tier 2 of the plan is
built on pascore components with a 500-bar lookback, and it beat the volatility
baseline by ~0.05. Those two facts sit awkwardly together.

So hold the feature DEFINITIONS fixed and vary only the memory depth: 20, 60, 250,
500 bars. If short lookbacks match long ones, the plan should use the short version
-- fewer bars, faster to compute, and honest about where the signal lives. If long
genuinely wins, then "the market's memory is short" is too broad a conclusion and
the light-box failed for its own reasons rather than for that one.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from pascore_futures import build
from pascore_eval import COMPS, TFS
warnings.filterwarnings("ignore")

M = build().sort_values(["spot","day"])
g = M.groupby("spot")
M["v_absret"] = g["absret"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_range"]  = g["rangeatr"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_atrpct"] = M.atr_prev / M.c
BASE = ["v_absret","v_range","v_atrpct"]

def cols(L, w="harmonic", dr=0.002):
    return [f"{c}|{w}|{L}|{dr}|{tf}" for tf in TFS for c in COMPS]

LOOKS = (20, 60, 250, 500)
need = BASE + [c for L in LOOKS for c in cols(L)] + ["rangeatr","mfe"]
M = M.dropna(subset=[c for c in need if c in M.columns])
cut = M.day.quantile(0.6)
tr, te = M[M.day < cut], M[M.day >= cut]
print(f"train {len(tr)}  held-out {len(te)}\n")

def fit(feats, ytr):
    X, Y = tr[feats].to_numpy(), te[feats].to_numpy()
    mu, sd = X.mean(0), X.std(0)+1e-9
    m = LogisticRegression(max_iter=4000, C=0.5).fit((X-mu)/sd, ytr)
    return m.predict_proba((Y-mu)/sd)[:,1]

print(f"{'target':<10}{'side':<7}{'baseline':>9}" + "".join(f"{'L='+str(L):>9}" for L in LOOKS)
      + f"{'ALL':>9}   per-asset gain at best L")
for tgt in ("rangeatr","mfe"):
    for side in ("QUIET","BIG"):
        q = tr[tgt].quantile(1/3 if side=="QUIET" else 2/3)
        ytr = (tr[tgt] < q).astype(int) if side=="QUIET" else (tr[tgt] > q).astype(int)
        yte = ((te[tgt] < q) if side=="QUIET" else (te[tgt] > q)).astype(int).to_numpy()
        sb = fit(BASE, ytr); ab = roc_auc_score(yte, sb)
        row, best, bl = [], -1, None
        for L in LOOKS:
            s = fit(BASE + cols(L), ytr); a = roc_auc_score(yte, s)
            row.append(a)
            if a > best: best, bl, sbest = a, L, s
        sall = fit(BASE + [c for L in LOOKS for c in cols(L)], ytr)
        per = []
        for spot in ("BTC","ETH"):
            m_ = (te.spot == spot).to_numpy()
            if m_.sum() > 60 and len(np.unique(yte[m_])) > 1:
                per.append(f"{spot} {roc_auc_score(yte[m_],sbest[m_])-roc_auc_score(yte[m_],sb[m_]):+.3f}")
        print(f"{tgt:<10}{side:<7}{ab:>9.3f}" + "".join(f"{a:>9.3f}" for a in row)
              + f"{roc_auc_score(yte,sall):>9.3f}   best L={bl}: " + "  ".join(per))
