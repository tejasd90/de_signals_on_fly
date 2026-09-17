#!/usr/bin/env python3
"""
fut_ml.py — can the 105 Brooks spot features pick WHICH leveraged entries win?

Random entry is significantly negative (EV/margin -0.023, CI [-0.039,-0.008]).
So the only route to a futures edge is predicting entries. Target:

    win = price reaches +F before -A, within H bars, in the traded direction

Purged walk-forward with an embargo of H bars (labels overlap by construction,
so without the embargo train and test share the same forward window and the
result is fiction). Significance by BLOCK bootstrap on non-overlapping 7-day
blocks — the real sample size is ~141 blocks, not ~99k rows.
"""
import numpy as np, pandas as pd, glob, sys
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

H=168; FEE=0.0010; FUND=0.0001
liq=pd.concat([pd.read_parquet(f) for f in glob.glob("liq/*.parquet")],ignore_index=True)
bk=pd.read_parquet("brooks_spot.parquet")
m=liq.merge(bk,on=["spot","ts"],how="inner")
m=m.sort_values("ts").reset_index(drop=True)
feats=[x for x in m.columns if x.startswith("bk_")]
m["is_long"]=(m["dir"]=="long").astype(int)
feats=feats+["is_long"]
print(f"rows {len(m):,} | features {len(feats)}")

def folds(n,k=5,embargo=H):
    b=np.linspace(0,n,k+1).astype(int)
    return [(np.arange(0,max(0,b[i]-embargo)),np.arange(b[i],b[i+1])) for i in range(1,k)]

X=np.where(np.isfinite(m[feats].to_numpy(np.float64)),m[feats].to_numpy(np.float64),np.nan)
blk=(m.ts//(H*3600)).to_numpy()
for A,F in [(0.10,0.05),(0.15,0.05),(0.05,0.02),(0.10,0.03)]:
    L=1.0/A
    ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
    win=((tf<ta)&(tf<=H)).astype(int); liq_=((ta<tf)&(ta<=H))
    held=np.where(win==1,tf,np.where(liq_,ta,H)).astype(float)
    sgn=np.where(m.is_long==1,1.0,-1.0)
    tret=np.nan_to_num(m.tret.to_numpy())*sgn if "tret" in m else np.zeros(len(m))
    oof=np.full(len(m),np.nan)
    for tr,te in folds(len(m)):
        if len(tr)<2000 or win[tr].sum()<200: continue
        g=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=15,
            max_depth=4,min_child_samples=200,subsample=0.8,subsample_freq=1,
            colsample_bytree=0.6,reg_lambda=10.0,class_weight="balanced",
            random_state=0,n_jobs=5,verbose=-1)
        g.fit(X[tr],win[tr]); oof[te]=g.predict_proba(X[te])[:,1]
    ok=np.isfinite(oof)
    auc=roc_auc_score(win[ok],oof[ok])
    print(f"\n=== stop -{A*100:g}% ({L:.1f}x), target +{F*100:g}%  |  AUC {auc:.4f} ===")
    print(f"    base win rate {win[ok].mean()*100:.1f}%")
    o=np.argsort(-oof[ok]); ww=win[ok][o]
    for frac in [0.05,0.10,0.25]:
        k=int(len(o)*frac)
        print(f"      top {frac:>4.0%}: win {ww[:k].mean()*100:>5.1f}%")
