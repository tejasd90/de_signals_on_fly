#!/usr/bin/env python3
"""Same sweep, but also expectancy: win T, lose to stop_ratio. Mark prices only."""
import numpy as np, pandas as pd, duckdb, lightgbm as lgb
c=duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
df=c.execute("""SELECT d.*, e.stop_ratio FROM 'disc_final/*.parquet' d
 JOIN 'exits/*.parquet' e ON d.symbol=e.symbol
 AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=e.ts""").df().reset_index(drop=True)
num=df.select_dtypes(include=[np.number]).columns
feats=[x for x in num if not x.startswith(("label","_")) and x not in {"episode_id","stop_ratio","duration"}]
assert not [f for f in feats if f.startswith(("label","_"))]
ep=df.groupby("episode_id")["_ts_hours"].min().sort_values(); eps=ep.index.to_numpy()
b=np.linspace(0,len(eps),6).astype(int); emb=max(1,int(len(eps)*0.01))
folds=[]
for i in range(1,5):
    tr=set(eps[:max(0,b[i]-emb)]); te=set(eps[b[i]:b[i+1]])
    folds.append((df.index[df.episode_id.isin(tr)].to_numpy(),
                  df.index[df.episode_id.isin(te)].to_numpy()))
X=df[feats].to_numpy(np.float32); w=df._w.to_numpy(float)
peak=df._peak.to_numpy(float); sr=df.stop_ratio.to_numpy(float)
COST=0.05
print(f"{'target':>7}{'slice':>8}{'win%':>8}{'lose->keep':>12}{'exp/trade':>11}{'random exp':>12}")
print("-"*60)
for T in [1.5,2,3,5,10,25]:
    y=(peak>=T).astype(np.int8)
    oof=np.full(len(df),np.nan)
    for tr,te in folds:
        m=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=7,max_depth=3,
            min_child_samples=30,subsample=0.8,subsample_freq=1,colsample_bytree=0.7,
            reg_lambda=5.0,class_weight="balanced",random_state=0,n_jobs=5,verbose=-1)
        m.fit(X[tr],y[tr],sample_weight=w[tr]); oof[te]=m.predict_proba(X[te])[:,1]
    ok=np.isfinite(oof); o=np.argsort(-oof[ok])
    pk=peak[ok][o]; ss=sr[ok][o]; ww=w[ok][o]; cw=np.cumsum(ww)
    rnd=np.average(np.where(peak[ok]>=T,T,sr[ok])-COST,weights=w[ok])-1
    for frac in [0.005,0.01,0.05]:
        k=np.searchsorted(cw,cw[-1]*frac)+1
        hit=pk[:k]>=T
        R=np.where(hit,T,ss[:k])-COST
        keep=np.average(ss[:k][~hit],weights=ww[:k][~hit]) if (~hit).any() else np.nan
        print(f"{T:>7g}{frac:>8.1%}{np.average(hit,weights=ww[:k])*100:>8.1f}{keep:>12.3f}"
              f"{np.average(R,weights=ww[:k])-1:>+11.4f}{rnd:>+12.4f}")
    print("-"*60)
