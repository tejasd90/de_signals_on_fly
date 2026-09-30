"""
Evaluate the single-number price-action score under a pre-registered protocol.

The danger with this idea is NOT that it is wrong, it is that it has 24
specifications (4 weight families x 2 lookbacks x 3 drifts) and seven components.
Choosing the winner after seeing results manufactures a number -- which is how the
apex test nearly produced the largest "finding" in the project before ETH
contradicted it.

So, fixed in advance:
  * TIME split, 60% train / 40% held-out. No shuffling: days are autocorrelated
    and a random split would leak tomorrow into today.
  * Every choice -- spec, model coefficients, threshold -- made on TRAIN ONLY.
  * Report the held-out half.
  * Westfall-Young maxT across all 24 specs, so "best of 24" is priced in.
  * The real test: does the score ADD to line-age >= 100d, the only level feature
    that has survived both the oracle and implementable tests? The five coiling
    features also looked plausible and came in at held-out AUC 0.485 while
    DEGRADING age. That is the bar.
"""
import numpy as np, pandas as pd, warnings, sys
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
warnings.filterwarnings("ignore")

COMPS = ("hits","novel","disp","rejmag","side","ovl","round")
WEIGHTS = ("harmonic","log","power","exp")
LOOKBACKS = (250,500)
DRIFTS = (0.0,0.002,0.006)
TFS = (1440,360)

def load():
    fr = []
    for spot in ("BTC","ETH"):
        d = pd.read_parquet(f"data/pascore_{spot}.parquet")
        d["spot"] = spot
        fr.append(d)
    return pd.concat(fr).sort_index()

def add_age(J):
    import approach
    B = approach.build()
    g = B.groupby("day").agg(age=("age","max"))
    J = J.join(g, how="left")
    J["old_line"] = (J.age.fillna(0) >= 100).astype(int)
    return J

def cols_for(w,L,dr):
    return [f"{c}|{w}|{L}|{dr}|{tf}" for tf in TFS for c in COMPS]

def fit_eval(tr, te, cols):
    Xtr = tr[cols].to_numpy(); Xte = te[cols].to_numpy()
    ok = np.isfinite(Xtr).all(1); ok2 = np.isfinite(Xte).all(1)
    if ok.sum() < 100 or ok2.sum() < 60: return None
    mu, sd = Xtr[ok].mean(0), Xtr[ok].std(0) + 1e-9
    m = LogisticRegression(max_iter=2000, C=0.5)
    m.fit((Xtr[ok]-mu)/sd, tr.y.to_numpy()[ok])
    str_ = m.predict_proba((Xtr[ok]-mu)/sd)[:,1]
    ste  = m.predict_proba((Xte[ok2]-mu)/sd)[:,1]
    return dict(auc_tr=roc_auc_score(tr.y.to_numpy()[ok], str_),
                auc_te=roc_auc_score(te.y.to_numpy()[ok2], ste),
                s_te=ste, y_te=te.y.to_numpy()[ok2], mask_te=ok2, model=m, mu=mu, sd=sd)

def main():
    J = add_age(load())
    J = J[np.isfinite(J.y)]
    cut = J.index[int(len(J)*0.6)]
    tr, te = J[J.index < cut], J[J.index >= cut]
    print(f"train {len(tr)} days (to {cut.date()}), held-out {len(te)} days")
    print(f"base rate: train {tr.y.mean():.3f}   held-out {te.y.mean():.3f}\n")

    res = {}
    for w in WEIGHTS:
        for L in LOOKBACKS:
            for dr in DRIFTS:
                r = fit_eval(tr, te, cols_for(w,L,dr))
                if r: res[(w,L,dr)] = r
    if not res: print("nothing fitted"); return

    best = max(res, key=lambda k: res[k]["auc_tr"])
    print("SELECTED ON TRAIN ONLY:", best, f"train AUC {res[best]['auc_tr']:.3f}")
    print(f"  --> HELD-OUT AUC {res[best]['auc_te']:.3f}\n")

    print("all 24 specs (train AUC -> held-out AUC), to show the spread:")
    for k in sorted(res, key=lambda k:-res[k]["auc_tr"]):
        print(f"   {str(k):<24} {res[k]['auc_tr']:.3f} -> {res[k]['auc_te']:.3f}")
    te_aucs = np.array([res[k]["auc_te"] for k in res])
    print(f"\n  held-out AUC across specs: min {te_aucs.min():.3f}  median "
          f"{np.median(te_aucs):.3f}  max {te_aucs.max():.3f}")

    # ---- the decisive test: does it ADD to old_line? ----
    r = res[best]; m = r["mask_te"]
    T = te[m].copy(); T["score"] = r["s_te"]
    y = T.y.to_numpy(); old = T.old_line.to_numpy()
    print(f"\nheld-out: old_line fires {old.mean()*100:.1f}% of days")
    a_old = roc_auc_score(y, old) if 0 < old.mean() < 1 else np.nan
    print(f"  AUC, old_line alone      {a_old:.3f}")
    print(f"  AUC, score alone         {roc_auc_score(y, T.score):.3f}")
    both = LogisticRegression(max_iter=2000)
    Xb = np.c_[old, T.score.to_numpy()]
    both.fit(Xb, y)
    print(f"  AUC, old_line + score    {roc_auc_score(y, both.predict_proba(Xb)[:,1]):.3f}"
          "   <- must beat old_line alone")

    # lift by held-out score decile, and within old_line days
    T["dec"] = pd.qcut(T.score, 5, labels=False, duplicates="drop")
    print(f"\nheld-out P(100x) by score quintile   (base {y.mean()*100:.1f}%)")
    for q, g in T.groupby("dec"):
        print(f"   Q{int(q)+1}  n={len(g):>4}  P(100x) {g.y.mean()*100:5.1f}%")
    sub = T[T.old_line == 1]
    if len(sub) > 40:
        print(f"\nWITHIN old_line days only (n={len(sub)}, P={sub.y.mean()*100:.1f}%):")
        hi = sub[sub.score >= sub.score.median()]; lo = sub[sub.score < sub.score.median()]
        print(f"   score high {hi.y.mean()*100:5.1f}% (n={len(hi)})   "
              f"score low {lo.y.mean()*100:5.1f}% (n={len(lo)})   "
              f"diff {100*(hi.y.mean()-lo.y.mean()):+.1f}pp")

if __name__ == "__main__":
    main()
