#!/usr/bin/env python3
"""The round-2 table reports top-5% EV for the NNs but not for the tree, which
makes the EV column unreadable. Recompute the pooled tree WITH net returns on the
same folds so both columns mean the same thing. Stable sort so ties in ts order
identically to the NN path."""
import gc, os, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
H,STRIDE,A,F = 24,2,0.15,0.05
LEV=1.0/A
inv=pd.read_parquet("perp_inventory.parquet")
syms=[s for s in inv[inv.years>=1.0].sym if os.path.exists(f"perp_liq_24/{s}.parquet")
      and os.path.exists(f"perp_brooks/{s}.parquet")]
Xs,ys,tss,bes,nets=[],[],[],[],[]
for s in syms:
    m=(pd.read_parquet(f"perp_liq_24/{s}.parquet")
        .merge(pd.read_parquet(f"perp_brooks/{s}.parquet"),on=["sym","ts"],how="inner"))
    m=m[(m.ts//3600)%STRIDE==0]
    if len(m)<200: continue
    ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
    win=(tf<ta)&(tf<=H); liq=(ta<tf)&(ta<=H)
    held=np.where(win,tf,np.where(liq,ta,H)).astype(np.float32)
    sg=np.where(m["dir"].to_numpy()=="long",1.0,-1.0).astype(np.float32)
    tret=m.tret.to_numpy()*sg
    nets.append((np.where(win,LEV*F,np.where(liq,-1.0,LEV*tret))
                 -LEV*0.0001*(held/8.0)-LEV*0.0004).astype(np.float32))
    ys.append(win.astype(np.int8)); tss.append(m.ts.to_numpy())
    bes.append(np.full(len(m), s in ("BTCUSD","ETHUSD"), bool))
    f=[c for c in m.columns if c.startswith("bk_")]
    x=m[f].to_numpy(np.float32); x[~np.isfinite(x)]=np.nan
    Xs.append(np.column_stack([x,(sg>0).astype(np.float32)]))
    del m
X=np.concatenate(Xs); del Xs; gc.collect()
y=np.concatenate(ys); ts=np.concatenate(tss); be=np.concatenate(bes); net=np.concatenate(nets)
o=np.argsort(ts,kind="stable"); X,y,ts,be,net = X[o],y[o],ts[o],be[o],net[o]
edges=np.quantile(ts,np.linspace(0,1,6)); oof=np.full(len(y),np.nan)
for i in range(1,5):
    te=(ts>=edges[i])&(ts<edges[i+1]); tr=ts<(edges[i]-H*3600)
    if tr.sum()<20000 or te.sum()<2000: continue
    g=lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=31,max_depth=5,
        min_child_samples=300,subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
        reg_lambda=20.0,random_state=0,n_jobs=6,verbose=-1)
    g.fit(X[tr],y[tr]); oof[te]=g.predict_proba(X[te])[:,1]; del g; gc.collect()
    print(f"  fold {i}", flush=True)
ok=np.isfinite(oof)
evs=[]
for i in range(1,5):
    te=(ts>=edges[i])&(ts<edges[i+1])&ok
    if te.sum()<2000: continue
    thr=np.quantile(oof[te],0.95); sel=te&(oof>=thr)
    evs.append(net[sel].mean())
print(f"\nTREE pooled: AUC {roc_auc_score(y[ok],oof[ok]):.4f} | "
      f"BTC+ETH {roc_auc_score(y[ok&be],oof[ok&be]):.4f}")
print(f"TREE top-5% EV per fold: {[f'{e:+.4f}' for e in evs]}")
print(f"TREE top-5% EV mean {np.mean(evs):+.4f} +-{np.std(evs):.4f}")
