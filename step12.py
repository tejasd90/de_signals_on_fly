#!/usr/bin/env python3
"""
Step 1 (fees) + Step 2 (BTC/ETH only) of Futures_Maximization_With_Hedging.

Step 1: the 24h model's best bucket loses 0.6%/trade against ~0.9% of fees+
funding, i.e. it is +0.3% BEFORE costs. Fee cost on margin = L x fee, so the
levers are (a) maker instead of taker, (b) lower leverage. Test both.

Step 2: hedging exists only for BTC/ETH/XAUT, so the edge must be re-measured on
those alone. Pooling 129 symbols does not tell us about the 2 we can hedge.
"""
import glob,os,numpy as np,pandas as pd,lightgbm as lgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
H=24; STRIDE=2
FEES={"taker/taker 0.10%":0.0010,"maker/taker 0.07%":0.0007,"maker/maker 0.04%":0.0004}
def build(syms=None):
    rows=[]
    for p in sorted(glob.glob("perp_liq_24/*.parquet")):
        s=os.path.basename(p)[:-8]
        if syms and s not in syms: continue
        lq=pd.read_parquet(p); bk=pd.read_parquet(f"perp_brooks/{s}.parquet")
        m=lq.merge(bk,on=["sym","ts"],how="inner")
        m=m[(m.ts//3600)%STRIDE==0]
        if len(m)<200: continue
        rows.append(m)
    return pd.concat(rows,ignore_index=True).sort_values("ts").reset_index(drop=True)
def run(m,A,F,label):
    L=1.0/A
    m=m.copy(); m["is_long"]=(m["dir"]=="long").astype(np.int8)
    feats=[c for c in m.columns if c.startswith("bk_")]+["is_long"]
    ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
    win=((tf<ta)&(tf<=H)); liq=((ta<tf)&(ta<=H))
    held=np.where(win,tf,np.where(liq,ta,H)).astype(np.float32)
    sg=np.where(m.is_long==1,1.0,-1.0).astype(np.float32)
    tret=(m.tret.to_numpy()*sg).astype(np.float32)
    X=m[feats].to_numpy(np.float32); X[~np.isfinite(X)]=np.nan
    ts=m.ts.to_numpy(); y=win.astype(np.int8)
    edges=np.quantile(ts,np.linspace(0,1,6))
    oof=np.full(len(y),np.nan,np.float32); cal=np.full(len(y),np.nan,np.float32)
    for i in range(1,5):
        te=(ts>=edges[i])&(ts<edges[i+1]); tr=ts<(edges[i]-H*3600)
        if tr.sum()<20000 or te.sum()<2000: continue
        tri=np.where(tr)[0]; cut=int(len(tri)*0.8)
        g=lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=31,max_depth=5,
            min_child_samples=300,subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
            reg_lambda=20.0,random_state=0,n_jobs=5,verbose=-1)
        g.fit(X[tri[:cut]],y[tri[:cut]])
        iso=IsotonicRegression(out_of_bounds="clip")
        iso.fit(g.predict_proba(X[tri[cut:]])[:,1],y[tri[cut:]])
        pr=g.predict_proba(X[te])[:,1]; oof[te]=pr; cal[te]=iso.predict(pr)
    ok=np.isfinite(oof)
    auc=roc_auc_score(y[ok],oof[ok])
    out={"label":label,"A":A,"F":F,"L":L,"auc":auc,"n":ok.sum()}
    gross=np.where(win,L*F,np.where(liq,-1.0,L*tret))-L*0.0001*(held/8.0)
    for fname,fee in FEES.items():
        r=gross-L*fee
        p=cal[ok]; q=np.quantile(p[np.isfinite(p)],0.95)
        sel=ok&(cal>=q)
        out[fname]=(r[ok].mean(), r[sel].mean())
    out["ts"]=ts; out["cal"]=cal; out["gross"]=gross; out["ok"]=ok
    return out
print("=== STEP 2: does the edge exist on the HEDGEABLE symbols? ===\n")
res={}
for label,syms in [("ALL 129",None),("BTC+ETH only",{"BTCUSD","ETHUSD"})]:
    m=build(syms)
    print(f"{label}: rows {len(m):,}, symbols {m.sym.nunique()}")
    for A,F in [(0.15,0.05),(0.10,0.03),(0.05,0.02)]:
        o=run(m,A,F,label); res[(label,A,F)]=o
        print(f"   stop -{A*100:g}% ({o['L']:.1f}x) target +{F*100:g}%  AUC {o['auc']:.4f}")
    del m
print("\n=== STEP 1: EV per trade at top-5% confidence, by fee model ===")
print(f"    {'universe':<14}{'config':<20}" + "".join(f"{k:>22}" for k in FEES))
for (label,A,F),o in res.items():
    cells="".join(f"{o[k][1]:>+22.4f}" for k in FEES)
    cfg = "-%g%%/+%g%% %.1fx" % (A*100, F*100, o["L"])
    print(f"    {label:<14}{cfg:<20}{cells}")
np.save("runs/step12_keys.npy",np.array([str(k) for k in res],dtype=object),allow_pickle=True)
import pickle
pickle.dump({k:{kk:vv for kk,vv in v.items() if kk not in ("ts","cal","gross","ok")}
             for k,v in res.items()},open("runs/step12.pkl","wb"))
pickle.dump(res,open("runs/step12_full.pkl","wb"))
print("\nsaved runs/step12_full.pkl")
