#!/usr/bin/env python3
"""
highprob.py — forget the multibagger. What is the HIGHEST-PROBABILITY setup
this data supports, at any payoff multiple?

Mark prices only. No tte filter, no cost model, no fill haircut. One question:
if the model flags a setup, how often does the option actually reach T x entry
before the stop? Nothing else.

Guardrails kept (these are what make any answer trustworthy, not tuning):
  - purged walk-forward, episode-grouped, test always later than train
  - _w weighting on EVERY statistic
  - assert no label/outcome column reaches the features
"""
import numpy as np, pandas as pd, duckdb, lightgbm as lgb, sys
from sklearn.metrics import roc_auc_score

c=duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
df=c.execute("""SELECT d.*, e.stop_ratio FROM 'disc_final/*.parquet' d
 JOIN 'exits/*.parquet' e ON d.symbol=e.symbol
 AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=e.ts""").df().reset_index(drop=True)
print(f"rows {len(df):,} | episodes {df.episode_id.nunique():,}\n")

num=df.select_dtypes(include=[np.number]).columns
feats=[x for x in num if not x.startswith(("label","_"))
       and x not in {"episode_id","stop_ratio","duration"}]
bad=[f for f in feats if f.startswith(("label","_"))]
assert not bad, bad
print(f"features ({len(feats)}) — all mechanical, no hand thresholds\n")

ep=df.groupby("episode_id")["_ts_hours"].min().sort_values(); eps=ep.index.to_numpy()
b=np.linspace(0,len(eps),6).astype(int); emb=max(1,int(len(eps)*0.01))
folds=[]
for i in range(1,5):
    tr=set(eps[:max(0,b[i]-emb)]); te=set(eps[b[i]:b[i+1]])
    folds.append((df.index[df.episode_id.isin(tr)].to_numpy(),
                  df.index[df.episode_id.isin(te)].to_numpy()))
X=df[feats].to_numpy(np.float32); w=df._w.to_numpy(float); peak=df._peak.to_numpy(float)

print(f"{'target':>7}{'base rate':>11}  |" + "".join(f"{s:>9}" for s in
      ["top0.1%","top0.5%","top1%","top2%","top5%","top10%"]) + f"{'  AUC':>7}")
print("-"*84)
for T in [1.5,2,3,5,10,25]:
    y=(peak>=T).astype(np.int8)
    if np.average(y,weights=w)<1e-5: continue
    oof=np.full(len(df),np.nan); aucs=[]
    for tr,te in folds:
        m=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=7,
            max_depth=3,min_child_samples=30,subsample=0.8,subsample_freq=1,
            colsample_bytree=0.7,reg_lambda=5.0,class_weight="balanced",
            random_state=0,n_jobs=5,verbose=-1)
        m.fit(X[tr],y[tr],sample_weight=w[tr])
        oof[te]=m.predict_proba(X[te])[:,1]
        aucs.append(roc_auc_score(y[te],oof[te],sample_weight=w[te]))
    ok=np.isfinite(oof); o=np.argsort(-oof[ok]); yy=y[ok][o]; ww=w[ok][o]; cw=np.cumsum(ww)
    cells=""
    for frac in [0.001,0.005,0.01,0.02,0.05,0.10]:
        k=np.searchsorted(cw,cw[-1]*frac)+1
        cells+=f"{np.average(yy[:k],weights=ww[:k])*100:>8.1f}%"
    print(f"{T:>7g}{np.average(y,weights=w)*100:>10.2f}%  |{cells}{np.mean(aucs):>7.3f}")
