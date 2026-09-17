#!/usr/bin/env python3
"""Sweep leverage x selectivity on BTC+ETH. Fee drag on margin = L x fee, so
if the gross edge is real, LOW leverage should keep more of it."""
import glob,os,numpy as np,pandas as pd,lightgbm as lgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
H=24
rows=[]
for s in ["BTCUSD","ETHUSD"]:
    lq=pd.read_parquet(f"perp_liq_24/{s}.parquet")
    bk=pd.read_parquet(f"perp_brooks/{s}.parquet")
    rows.append(lq.merge(bk,on=["sym","ts"],how="inner"))
m=pd.concat(rows,ignore_index=True).sort_values("ts").reset_index(drop=True)
m["is_long"]=(m["dir"]=="long").astype(np.int8)
feats=[c for c in m.columns if c.startswith("bk_")]+["is_long"]
X=m[feats].to_numpy(np.float32); X[~np.isfinite(X)]=np.nan
ts=m.ts.to_numpy(); sg=np.where(m.is_long==1,1.0,-1.0).astype(np.float32)
tret=(m.tret.to_numpy()*sg).astype(np.float32)
print(f"BTC+ETH rows {len(m):,}  span {pd.to_datetime(ts.min(),unit='s').date()}"
      f" .. {pd.to_datetime(ts.max(),unit='s').date()}\n")
edges=np.quantile(ts,np.linspace(0,1,6))
CFG=[(0.25,0.10),(0.25,0.05),(0.15,0.10),(0.15,0.05),(0.10,0.05),(0.10,0.03),(0.075,0.03),(0.05,0.02)]
print(f"{'stop/target':>16}{'lev':>7}{'AUC':>8}{'sel':>7}{'win%':>7}"
      f"{'GROSS EV':>10}{'maker .04%':>12}{'taker .10%':>12}")
print("-"*82)
for A,F in CFG:
    L=1.0/A
    ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
    win=((tf<ta)&(tf<=H)); liq=((ta<tf)&(ta<=H))
    held=np.where(win,tf,np.where(liq,ta,H)).astype(np.float32)
    y=win.astype(np.int8)
    oof=np.full(len(y),np.nan,np.float32); cal=np.full(len(y),np.nan,np.float32)
    for i in range(1,5):
        te=(ts>=edges[i])&(ts<edges[i+1]); tr=ts<(edges[i]-H*3600)
        if tr.sum()<5000 or te.sum()<1000: continue
        tri=np.where(tr)[0]; cut=int(len(tri)*0.8)
        g=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=15,max_depth=4,
            min_child_samples=200,subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
            reg_lambda=20.0,random_state=0,n_jobs=5,verbose=-1)
        g.fit(X[tri[:cut]],y[tri[:cut]])
        iso=IsotonicRegression(out_of_bounds="clip")
        iso.fit(g.predict_proba(X[tri[cut:]])[:,1],y[tri[cut:]])
        pr=g.predict_proba(X[te])[:,1]; oof[te]=pr; cal[te]=iso.predict(pr)
    ok=np.isfinite(oof); auc=roc_auc_score(y[ok],oof[ok])
    gross=np.where(win,L*F,np.where(liq,-1.0,L*tret))-L*0.0001*(held/8.0)
    for q in [0.90,0.95,0.99]:
        thr=np.quantile(cal[ok],q); sel=ok&(cal>=thr)
        if sel.sum()<300: continue
        g0=gross[sel].mean()
        print(f"{f'-{A*100:g}%/+{F*100:g}%':>16}{L:>6.1f}x{auc:>8.4f}"
              f"{f'top{(1-q)*100:.0f}%':>7}{y[sel].mean()*100:>6.1f}%"
              f"{g0:>+10.4f}{g0-L*0.0004:>+12.4f}{g0-L*0.0010:>+12.4f}")
    print()
