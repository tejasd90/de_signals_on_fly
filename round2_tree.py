#!/usr/bin/env python3
"""Pooled tree baseline for round 2, run as its OWN process so its ~1GB feature
matrix is released before the NNs start. Also checks the FINDINGS 22 figure
(pooled 0.6840), since the BTC+ETH 0.7024 did not reproduce."""
import gc, json, os, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
H,STRIDE,A,F = 24,2,0.15,0.05
inv=pd.read_parquet("perp_inventory.parquet")
syms=[s for s in inv[inv.years>=1.0].sym if os.path.exists(f"perp_liq_24/{s}.parquet")
      and os.path.exists(f"perp_brooks/{s}.parquet")]
print(f"{len(syms)} symbols", flush=True)
Xs,ys,tss,bes=[],[],[],[]
for k,s in enumerate(syms):
    m=(pd.read_parquet(f"perp_liq_24/{s}.parquet")
        .merge(pd.read_parquet(f"perp_brooks/{s}.parquet"),on=["sym","ts"],how="inner"))
    m=m[(m.ts//3600)%STRIDE==0]
    if len(m)<200: continue
    ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
    ys.append(((tf<ta)&(tf<=H)).astype(np.int8)); tss.append(m.ts.to_numpy())
    bes.append(np.full(len(m), s in ("BTCUSD","ETHUSD"), bool))
    f=[c for c in m.columns if c.startswith("bk_")]
    x=m[f].to_numpy(np.float32); x[~np.isfinite(x)]=np.nan
    Xs.append(np.column_stack([x,(m["dir"].to_numpy()=="long").astype(np.float32)]))
    del m; 
    if k%30==0: gc.collect(); print(f"  {k}/{len(syms)}", flush=True)
X=np.concatenate(Xs); del Xs; gc.collect()
y=np.concatenate(ys); ts=np.concatenate(tss); be=np.concatenate(bes)
o=np.argsort(ts); X,y,ts,be = X[o],y[o],ts[o],be[o]
print(f"pooled rows {len(y):,} ({X.nbytes/1e9:.2f} GB)  positives {y.mean()*100:.1f}%", flush=True)
edges=np.quantile(ts,np.linspace(0,1,6)); oof=np.full(len(y),np.nan)
for i in range(1,5):
    te=(ts>=edges[i])&(ts<edges[i+1]); tr=ts<(edges[i]-H*3600)
    if tr.sum()<20000 or te.sum()<2000: continue
    g=lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=31,max_depth=5,
        min_child_samples=300,subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
        reg_lambda=20.0,random_state=0,n_jobs=6,verbose=-1)
    g.fit(X[tr],y[tr]); oof[te]=g.predict_proba(X[te])[:,1]
    del g; gc.collect()
    print(f"  fold {i} done", flush=True)
ok=np.isfinite(oof)
res={"pooled_auc":float(roc_auc_score(y[ok],oof[ok])),
     "btceth_auc":float(roc_auc_score(y[ok&be],oof[ok&be])),
     "n":int(ok.sum()),"edges":[float(e) for e in edges]}
print(f"\npooled AUC {res['pooled_auc']:.4f}   BTC+ETH subset {res['btceth_auc']:.4f}")
print("reference FINDINGS 22: pooled 0.6840 | BTC+ETH 0.7024")
json.dump(res,open("runs/round2_tree.json","w"),indent=1)
np.savez_compressed("runs/round2_tree_oof.npz",oof=oof,y=y,ts=ts,be=be)
