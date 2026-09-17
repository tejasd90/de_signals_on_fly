#!/usr/bin/env python3
"""
FINDINGS 22 says "the edge is STRONGEST on the hedgeable pair: BTC+ETH alone at
24h gives AUC 0.7024 vs 0.6840 pooled." The pooled number reproduces (0.6855).
BTC+ETH-alone does NOT (0.66). But the pooled model SCORED ON the BTC+ETH subset
gives 0.7319 -- which is probably what 0.7024 actually was.

If so the conclusion inverts: pooling does not dilute the BTC+ETH edge, it is
what CREATES it, and the advice becomes "train on all 129, trade the two".

Head-to-head on IDENTICAL folds and IDENTICAL BTC+ETH test rows. Only the
TRAINING SET differs.
"""
import gc, os, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score
H,STRIDE,A,F = 24,2,0.15,0.05
inv=pd.read_parquet("perp_inventory.parquet")
syms=[s for s in inv[inv.years>=1.0].sym if os.path.exists(f"perp_liq_24/{s}.parquet")
      and os.path.exists(f"perp_brooks/{s}.parquet")]
Xs,ys,tss,bes=[],[],[],[]
for s in syms:
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
    del m
X=np.concatenate(Xs); del Xs; gc.collect()
y=np.concatenate(ys); ts=np.concatenate(tss); be=np.concatenate(bes)
o=np.argsort(ts); X,y,ts,be=X[o],y[o],ts[o],be[o]
edges=np.quantile(ts,np.linspace(0,1,6))        # ONE set of folds for both arms
print(f"pooled {len(y):,} rows | BTC+ETH {be.sum():,} | positives "
      f"pooled {y.mean()*100:.1f}% vs BTC+ETH {y[be].mean()*100:.1f}%\n", flush=True)
def mk(): return lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=31,
    max_depth=5,min_child_samples=300,subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
    reg_lambda=20.0,random_state=0,n_jobs=6,verbose=-1)
oofP=np.full(len(y),np.nan); oofS=np.full(len(y),np.nan)
for i in range(1,5):
    te=(ts>=edges[i])&(ts<edges[i+1]); tr=ts<(edges[i]-H*3600)
    if tr.sum()<20000 or te.sum()<2000: continue
    g=mk(); g.fit(X[tr],y[tr]); oofP[te]=g.predict_proba(X[te])[:,1]; del g
    trS=tr&be
    g=mk(); g.fit(X[trS],y[trS]); oofS[te]=g.predict_proba(X[te])[:,1]; del g
    gc.collect(); print(f"  fold {i} (pool train {tr.sum():,} | solo train {trS.sum():,})", flush=True)
m_=np.isfinite(oofP)&be
print(f"\n{'training set':<34}{'AUC on the SAME BTC+ETH test rows':>36}")
print(f"{'BTC+ETH only (~46k rows)':<34}{roc_auc_score(y[m_],oofS[m_]):>36.4f}")
print(f"{'all 129 symbols (~1.7M rows)':<34}{roc_auc_score(y[m_],oofP[m_]):>36.4f}")
print(f"\n{'':34}{'n test rows':>36} {m_.sum():,}")
mp=np.isfinite(oofP)
print(f"\npooled-model AUC on ALL symbols: {roc_auc_score(y[mp],oofP[mp]):.4f}")
