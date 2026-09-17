#!/usr/bin/env python3
"""Block-bootstrap the promising BTC+ETH configs. H=24h so blocks are 7 days,
which safely exceeds the label overlap."""
import numpy as np,pandas as pd,lightgbm as lgb
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
edges=np.quantile(ts,np.linspace(0,1,6))
blk=ts//(7*86400); ub=np.unique(blk)
print(f"BTC+ETH rows {len(m):,} | 7-day blocks {len(ub)}\n")
print(f"{'config':>16}{'sel':>7}{'trades':>8}{'win%':>7}{'EV maker':>11}"
      f"{'95% CI':>26}{'P(<=0)':>9}")
print("-"*86)
for A,F in [(0.10,0.03),(0.15,0.10),(0.25,0.05),(0.15,0.05),(0.10,0.05)]:
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
        iso=IsotonicRegression(out_of_bounds="clip"); iso.fit(g.predict_proba(X[tri[cut:]])[:,1],y[tri[cut:]])
        pr=g.predict_proba(X[te])[:,1]; oof[te]=pr; cal[te]=iso.predict(pr)
    ok=np.isfinite(oof)
    gross=np.where(win,L*F,np.where(liq,-1.0,L*tret))-L*0.0001*(held/8.0)
    r=gross-L*0.0004
    for q in [0.99,0.95]:
        thr=np.quantile(cal[ok],q); sel=ok&(cal>=thr)
        if sel.sum()<200: continue
        rs=r[sel]; bs=blk[sel]
        rng=np.random.default_rng(0); mu=[]
        for _ in range(3000):
            pk=rng.choice(ub,len(ub),replace=True)
            v=np.concatenate([rs[bs==b] for b in pk[:100] if (bs==b).any()])
            if len(v)>20: mu.append(v.mean())
        mu=np.array(mu)
        ci=f"[{np.percentile(mu,2.5):+.4f}, {np.percentile(mu,97.5):+.4f}]"
        print(f"{f'-{A*100:g}%/+{F*100:g}% {L:.1f}x':>16}{f'top{(1-q)*100:.0f}%':>7}"
              f"{sel.sum():>8,}{y[sel].mean()*100:>6.1f}%{rs.mean():>+11.4f}"
              f"{ci:>26}{(mu<=0).mean():>9.3f}")
