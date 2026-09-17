#!/usr/bin/env python3
"""Which LightGBM config produces the published 0.7024? step1b.py and step12.py
use DIFFERENT hyperparameters and nn_futures.py copied step1b's. If the tree was
handicapped, the NN comparison is unfair to the tree and must be restated."""
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
H,STRIDE,A,F = 24,2,0.15,0.05
rows=[]
for s in ["BTCUSD","ETHUSD"]:
    m=(pd.read_parquet(f"perp_liq_24/{s}.parquet")
        .merge(pd.read_parquet(f"perp_brooks/{s}.parquet"),on=["sym","ts"],how="inner"))
    rows.append(m[(m.ts//3600)%STRIDE==0])
m=pd.concat(rows,ignore_index=True).sort_values("ts").reset_index(drop=True)
m["is_long"]=(m["dir"]=="long").astype(np.int8)
feats=[c for c in m.columns if c.startswith("bk_")]+["is_long"]
ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
y=((tf<ta)&(tf<=H)).astype(np.int8); ts=m.ts.to_numpy()
X=m[feats].to_numpy(np.float32); X[~np.isfinite(X)]=np.nan
edges=np.quantile(ts,np.linspace(0,1,6))
CFG={
 "step1b  (300 trees, 15 leaves, depth 4, mcs 200)":
    dict(n_estimators=300,learning_rate=0.03,num_leaves=15,max_depth=4,min_child_samples=200),
 "step12  (400 trees, 31 leaves, depth 5, mcs 300)":
    dict(n_estimators=400,learning_rate=0.03,num_leaves=31,max_depth=5,min_child_samples=300),
 "bigger  (800 trees, 63 leaves, depth 7, mcs 100)":
    dict(n_estimators=800,learning_rate=0.03,num_leaves=63,max_depth=7,min_child_samples=100),
}
print(f"rows {len(m):,}  positives {y.mean()*100:.1f}%\n")
for name,kw in CFG.items():
    oof=np.full(len(y),np.nan)
    for i in range(1,5):
        te=(ts>=edges[i])&(ts<edges[i+1]); tr=ts<(edges[i]-H*3600)
        if tr.sum()<5000 or te.sum()<1000: continue
        g=lgb.LGBMClassifier(subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
            reg_lambda=20.0,random_state=0,n_jobs=6,verbose=-1,**kw)
        g.fit(X[tr],y[tr]); oof[te]=g.predict_proba(X[te])[:,1]
    ok=np.isfinite(oof)
    print(f"  {name}: AUC {roc_auc_score(y[ok],oof[ok]):.4f}")
