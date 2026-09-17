#!/usr/bin/env python3
"""
timing_test.py — can arm 4 (Brooks spot features) predict WHICH EPISODES pay?

The chain model ranks strikes at AUC 0.947 and moments at 0.574. This asks
whether spot structure moves the 0.574. One row per EPISODE (the unit of
independence), purged walk-forward, test always later than train.

Baseline to beat: 0.5745.
"""
import numpy as np, pandas as pd, duckdb, lightgbm as lgb
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score

c = duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
ep = c.execute("""
SELECT episode_id, any_value(spot) AS spot,
       min(_ts_hours) AS t0,
       max(label_10_0) AS y10, max(label_25_0) AS y25, max(label_50_0) AS y50,
       count(*) AS nrows, sum(_w) AS w
FROM 'disc_final/*.parquet' GROUP BY episode_id""").df()
print(f"episodes {len(ep):,} | base rates: 10x {ep.y10.mean():.3f} "
      f"25x {ep.y25.mean():.3f} 50x {ep.y50.mean():.3f}")

bk = pd.read_parquet("brooks_spot.parquet")
bk["th"] = (bk.ts / 3600.0).round().astype(np.int64)
ep["th"] = ep.t0.astype(float).round().astype(np.int64)
m = ep.merge(bk, on=["spot", "th"], how="inner")
print(f"joined to Brooks spot features: {len(m):,} episodes "
      f"({len(m)/len(ep)*100:.0f}%)\n")

feats = [x for x in m.columns if x.startswith("bk_")]
m = m.sort_values("t0").reset_index(drop=True)
X = m[feats].to_numpy(np.float64)
X = np.where(np.isfinite(X), X, np.nan)

def folds(n, k=5, emb=0.01):
    b = np.linspace(0, n, k + 1).astype(int); e = max(1, int(n * emb))
    return [(np.arange(0, max(0, b[i] - e)), np.arange(b[i], b[i + 1]))
            for i in range(1, k)]

for tgt in ["y10", "y25", "y50"]:
    y = m[tgt].to_numpy(int)
    oof_l = np.full(len(m), np.nan); oof_g = np.full(len(m), np.nan)
    for tr, te in folds(len(m)):
        if len(tr) < 100 or y[tr].sum() < 10: continue
        lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                           LogisticRegression(max_iter=3000, C=0.05,
                                              class_weight="balanced"))
        lr.fit(X[tr], y[tr]); oof_l[te] = lr.predict_proba(X[te])[:, 1]
        g = lgb.LGBMClassifier(n_estimators=250, learning_rate=0.03, num_leaves=7,
                               max_depth=3, min_child_samples=40, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.6,
                               reg_lambda=10.0, class_weight="balanced",
                               random_state=0, n_jobs=5, verbose=-1)
        g.fit(X[tr], y[tr]); oof_g[te] = g.predict_proba(X[te])[:, 1]
    ok = np.isfinite(oof_g)
    print(f"{tgt}  (base {y.mean():.3f}, {y.sum()} positive episodes)")
    print(f"   logistic  AUC {roc_auc_score(y[ok], oof_l[ok]):.4f}")
    print(f"   LightGBM  AUC {roc_auc_score(y[ok], oof_g[ok]):.4f}")
    o = np.argsort(-oof_g[ok]); yy = y[ok][o]
    for f in [0.1, 0.2, 0.5]:
        k = int(len(o) * f)
        print(f"     top {f:>4.0%} of episodes -> {yy[:k].mean()*100:>5.1f}% contain a "
              f"mover  (base {y.mean()*100:.1f}%)")
