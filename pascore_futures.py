"""Not "is there a 100x option today" -- "is today worth trading at all".

His reframe, and it is the better question. Everything so far scored against
y = (a 100x option existed that day): rare, option-specific, and carrying the
max-across-strikes oracle. For FUTURES the question is simpler and the answer is
not eaten by option pricing:

  Is there a move to catch, and is it directional or chop?

And the more valuable half is the NEGATIVE one. His stated problem is overtrading,
so a dependable "sit today out" filter is worth more than a big-move detector --
and reliably-quiet days are an easier target than explosive ones.

TARGETS on day D, all computed from bars strictly after the features are known:
  absret    |C_D / C_{D-1} - 1|            is there a move
  eff       |C_D - O_D| / (H_D - L_D)      trend day vs chop day (Brooks-ish)
  rangeatr  (H_D - L_D) / ATR_{D-1}        is the range worth the risk
  mfe       max(H_D - O_D, O_D - L_D)/ATR  best excursion a futures trade could catch

FEATURES are the pascore components, which since the 2026-09-30 fix are shifted
one day, so every input is known BEFORE day D opens.

Anti-leak checks are built in rather than bolted on: every target is reported
against the PREVIOUS day too. A feature that explains day D-1 as well as day D is
describing, not predicting. That is the check that was missing on 2026-09-29.
"""
import numpy as np, pandas as pd, warnings
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
from levels import load_tf, atr
from pascore_eval import load, cols_for, COMPS, TFS
warnings.filterwarnings("ignore")

SPEC = ("harmonic", 500, 0.002)

def futures_targets(spot):
    arr = load_tf(spot, 1440)
    if arr is None: return None
    d = pd.DataFrame({"day": pd.to_datetime(arr[:,0], unit="s").normalize(),
                      "o": arr[:,1], "h": arr[:,2], "l": arr[:,3], "c": arr[:,4]})
    d = d.groupby("day").agg(o=("o","first"), h=("h","max"), l=("l","min"), c=("c","last"))
    A = atr(d.h.to_numpy(), d.l.to_numpy(), d.c.to_numpy())
    d["atr_prev"] = np.roll(A, 1); d.iloc[0, d.columns.get_loc("atr_prev")] = np.nan
    d["absret"]   = (d.c / d.c.shift(1) - 1).abs()
    d["eff"]      = (d.c - d.o).abs() / (d.h - d.l).replace(0, np.nan)
    d["rangeatr"] = (d.h - d.l) / d.atr_prev
    d["mfe"]      = np.maximum(d.h - d.o, d.o - d.l) / d.atr_prev
    d["spot"] = spot
    return d.reset_index()

def build():
    F = load()                       # pascore components, already 1-day shifted
    T = pd.concat([futures_targets(s) for s in ("BTC","ETH")])
    F = F.reset_index().rename(columns={F.reset_index().columns[0]: "day"})
    F["day"] = pd.to_datetime(F["day"])
    M = F.merge(T, on=["spot","day"], how="inner")
    return M.sort_values("day")

TARGETS = ["absret", "eff", "rangeatr", "mfe"]

if __name__ == "__main__":
    M = build()
    cols = cols_for(*SPEC)
    M = M.dropna(subset=cols + TARGETS)
    cut = M.day.quantile(0.6)
    tr, te = M[M.day < cut], M[M.day >= cut]
    print(f"train {len(tr)}  held-out {len(te)}   (split {cut.date()})\n")

    for tgt in TARGETS:
        # classify the top tercile of the target: "a day worth trading"
        thr = tr[tgt].quantile(2/3)
        ytr, yte = (tr[tgt] > thr).astype(int), (te[tgt] > thr).astype(int)
        Xtr, Xte = tr[cols].to_numpy(), te[cols].to_numpy()
        mu, sd = Xtr.mean(0), Xtr.std(0)+1e-9
        m = LogisticRegression(max_iter=2000, C=0.5).fit((Xtr-mu)/sd, ytr)
        s = m.predict_proba((Xte-mu)/sd)[:,1]
        auc = roc_auc_score(yte, s)
        rho = spearmanr(s, te[tgt]).statistic
        # ANTI-LEAK: same feature against the PREVIOUS day's outcome
        prev = te.groupby("spot")[tgt].shift(1)
        ok = prev.notna().to_numpy()
        rho_prev = spearmanr(s[ok], prev[ok]).statistic
        print(f"{tgt:<10} held-out AUC {auc:.3f}   rho(next-day) {rho:+.3f}   "
              f"rho(PREV-day) {rho_prev:+.3f}" + ("   <-- LEAK" if abs(rho_prev) > abs(rho) else ""))
        for spot in ("BTC","ETH"):
            m_ = (te.spot == spot).to_numpy()
            if m_.sum() > 60:
                print(f"           {spot}: AUC {roc_auc_score(yte[m_], s[m_]):.3f}")
        q = pd.qcut(pd.Series(s, index=te.index), 5, labels=False, duplicates="drop")
        g = te.groupby(q)[tgt].median()
        print("           quintile medians: " + "  ".join(f"Q{i+1} {v:.3f}" for i, v in enumerate(g)))
        print()
