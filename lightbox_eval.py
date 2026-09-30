"""Does the light model add anything -- over volatility, and over pascore?

Judged by the same protocol that the 2026-09-30 audit forced:
  * TIME split, everything chosen on train
  * anti-leak: correlation against the PREVIOUS day's outcome as well as the next
  * per-asset, because pooled results have hidden disagreement three times now
  * measured against a trivial volatility baseline, not against zero

Targets are the futures ones, since that reframe is where signal actually lived:
vol-adjusted range and max favourable excursion, on both the BIG and QUIET sides.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
from pascore_futures import build
from pascore_eval import cols_for
warnings.filterwarnings("ignore")

M = build().sort_values(["spot","day"])
L = pd.read_parquet("data/lightbox.parquet")
L["day"] = pd.to_datetime(L.day)
M = M.merge(L, on=["spot","day"], how="inner")

g = M.groupby("spot")
M["v_absret"] = g["absret"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_range"]  = g["rangeatr"].transform(lambda s: s.shift(1).rolling(5).mean())
M["v_atrpct"] = M.atr_prev / M.c
BASE = ["v_absret","v_range","v_atrpct"]
PAS  = cols_for("harmonic",500,0.002)
LX   = [c for c in M.columns if c.startswith("lx_")]

M = M.dropna(subset=BASE+PAS+LX+["rangeatr","mfe"])
cut = M.day.quantile(0.6)
tr, te = M[M.day < cut], M[M.day >= cut]
print(f"train {len(tr)}  held-out {len(te)}   lightbox features {len(LX)}\n")

def fit(feats, ytr):
    X, Y = tr[feats].to_numpy(), te[feats].to_numpy()
    mu, sd = X.mean(0), X.std(0)+1e-9
    m = LogisticRegression(max_iter=4000, C=0.5).fit((X-mu)/sd, ytr)
    return m.predict_proba((Y-mu)/sd)[:,1]

# ---- anti-leak, first, before anything else is believed ----
print("ANTI-LEAK: light features vs NEXT-day and PREVIOUS-day outcome")
for tgt in ("rangeatr","mfe"):
    thr = tr[tgt].quantile(2/3)
    s = fit(LX, (tr[tgt] > thr).astype(int))
    prev = te.groupby("spot")[tgt].shift(1); ok = prev.notna().to_numpy()
    rn = spearmanr(s, te[tgt]).statistic
    rp = spearmanr(s[ok], prev[ok]).statistic
    flag = "  <-- describes yesterday" if abs(rp) > abs(rn) else ""
    print(f"  {tgt:<10} rho(next) {rn:+.3f}   rho(prev) {rp:+.3f}{flag}")

print(f"\n{'target':<10}{'side':<7}{'base':>7}{'+pascore':>10}{'+light':>9}{'+both':>8}"
      f"{'light gain':>12}   per-asset light gain")
for tgt in ("rangeatr","mfe"):
    for side in ("QUIET","BIG"):
        if side == "BIG":
            thr = tr[tgt].quantile(2/3)
            ytr, yte = (tr[tgt]>thr).astype(int), (te[tgt]>thr).astype(int).to_numpy()
        else:
            thr = tr[tgt].quantile(1/3)
            ytr, yte = (tr[tgt]<thr).astype(int), (te[tgt]<thr).astype(int).to_numpy()
        sb, sp = fit(BASE, ytr), fit(BASE+PAS, ytr)
        sl, sa = fit(BASE+LX, ytr), fit(BASE+PAS+LX, ytr)
        ab, ap = roc_auc_score(yte,sb), roc_auc_score(yte,sp)
        al, aa = roc_auc_score(yte,sl), roc_auc_score(yte,sa)
        per = []
        for spot in ("BTC","ETH"):
            m_ = (te.spot==spot).to_numpy()
            if m_.sum()>60 and len(np.unique(yte[m_]))>1:
                per.append(f"{spot} {roc_auc_score(yte[m_],sl[m_])-roc_auc_score(yte[m_],sb[m_]):+.3f}")
        print(f"{tgt:<10}{side:<7}{ab:>7.3f}{ap:>10.3f}{al:>9.3f}{aa:>8.3f}"
              f"{al-ab:>+12.3f}   " + "  ".join(per))

print("\nalpha sweep, rangeatr QUIET, light features only at each absorption:")
for al_ in (0.001, 0.01, 0.10, 0.50):
    sub = [c for c in LX if c.endswith(f"a{al_}")]
    thr = tr["rangeatr"].quantile(1/3)
    ytr = (tr["rangeatr"]<thr).astype(int); yte = (te["rangeatr"]<thr).astype(int).to_numpy()
    s = fit(BASE+sub, ytr)
    print(f"   alpha={al_:<6} AUC {roc_auc_score(yte,s):.3f}")
