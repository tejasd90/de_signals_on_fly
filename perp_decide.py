#!/usr/bin/env python3
"""
perp_decide.py — the pre-registered decision test on 129 perps.

Rules fixed BEFORE seeing the result (stated to Tejas 2026-09-11):
  AUC ~0.60 AND calibration monotonic AND half-Kelly CI clears zero -> real
  AUC holds but calibration broken                                  -> not sizeable yet
  AUC decays toward 0.55                                            -> was noise

Cross-sectional data does NOT add independent time periods, so folds are cut on
TIME (every symbol in a period stays together) and the bootstrap blocks on time.
Entries are strided 4h: with a 168h horizon, adjacent hours are near-duplicates.
"""
import glob, os, sys, time
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

import os as _os
H=int(_os.environ.get("HZ","168")); LIQDIR=_os.environ.get("LIQDIR","perp_liq")
FEE=0.0010; FUND=0.0001; STRIDE=int(_os.environ.get("STRIDE","4"))
A,F = 0.15, 0.05           # stop -15% (6.7x), target +5%
L, B = 1.0/A, (1.0/A)*F

rows=[]
for p in sorted(glob.glob(f"{LIQDIR}/*.parquet")):
    s=os.path.basename(p)[:-8]
    lq=pd.read_parquet(p)
    bk=pd.read_parquet(f"perp_brooks/{s}.parquet")
    m=lq.merge(bk,on=["sym","ts"],how="inner") if "sym" in lq.columns else \
      lq.assign(sym=s).merge(bk,on=["sym","ts"],how="inner")
    m=m[(m.ts//3600)%STRIDE==0]
    if len(m)<200: continue
    rows.append(m)
m=pd.concat(rows,ignore_index=True).sort_values("ts").reset_index(drop=True)
del rows
m["is_long"]=(m["dir"]=="long").astype(np.int8)
feats=[c for c in m.columns if c.startswith("bk_")]+["is_long"]
print(f"rows {len(m):,} | symbols {m.sym.nunique()} | features {len(feats)}")
print(f"span {pd.to_datetime(m.ts.min(),unit='s').date()} .. "
      f"{pd.to_datetime(m.ts.max(),unit='s').date()}")

ta=m[f"tadv_{A*100:g}pct"].to_numpy(); tf=m[f"tfav_{F*100:g}pct"].to_numpy()
win=((tf<ta)&(tf<=H)); liq=((ta<tf)&(ta<=H))
held=np.where(win,tf,np.where(liq,ta,H)).astype(np.float32)
sgn=np.where(m.is_long==1,1.0,-1.0).astype(np.float32)
tret=(m.tret.to_numpy()*sgn).astype(np.float32)
R=(np.where(win,L*F,np.where(liq,-1.0,L*tret))-L*FEE-L*FUND*(held/8.0)).astype(np.float32)
X=m[feats].to_numpy(np.float32)
X[~np.isfinite(X)]=np.nan
ts=m.ts.to_numpy(); y=win.astype(np.int8)
del m
print(f"base win {y.mean():.3f} | liq {liq.mean():.3f} | mean R {R.mean():+.4f}\n")

# folds cut on TIME
edges=np.quantile(ts,np.linspace(0,1,6))
oof=np.full(len(y),np.nan,np.float32); cal=np.full(len(y),np.nan,np.float32)
for i in range(1,5):
    te=(ts>=edges[i])&(ts<edges[i+1])
    tr=ts<(edges[i]-H*3600)
    if tr.sum()<50000 or te.sum()<5000: continue
    tri=np.where(tr)[0]; cut=int(len(tri)*0.8)
    f1,f2=tri[:cut],tri[cut:]
    g=lgb.LGBMClassifier(n_estimators=400,learning_rate=0.03,num_leaves=31,max_depth=5,
        min_child_samples=500,subsample=0.8,subsample_freq=1,colsample_bytree=0.6,
        reg_lambda=20.0,random_state=0,n_jobs=5,verbose=-1)
    g.fit(X[f1],y[f1])
    iso=IsotonicRegression(out_of_bounds="clip")
    iso.fit(g.predict_proba(X[f2])[:,1],y[f2])
    pr=g.predict_proba(X[te])[:,1]
    oof[te]=pr; cal[te]=iso.predict(pr)
    print(f"  fold {i}: train {tr.sum():,} test {te.sum():,} "
          f"AUC {roc_auc_score(y[te],pr):.4f}",flush=True)
ok=np.isfinite(oof)
print(f"\nOVERALL AUC {roc_auc_score(y[ok],oof[ok]):.4f}   n={ok.sum():,}")
p=cal[ok]; yy=y[ok]; rr=R[ok]; tt=ts[ok]
print("\n=== CALIBRATION (isotonic, fitted on train only) ===")
qs=np.quantile(p,np.linspace(0,1,9))
print(f"    {'pred':>8}{'actual':>9}{'n':>10}{'mean R':>9}")
for i in range(8):
    s=(p>=qs[i])&(p<=qs[i+1] if i==7 else p<qs[i+1])
    if s.sum()<200: continue
    print(f"    {p[s].mean():>8.3f}{yy[s].mean():>9.3f}{s.sum():>10,}{rr[s].mean():>+9.3f}")
np.savez(_os.environ.get("OOF","runs/perp_oof.npz"),p=p,y=yy,r=rr,ts=tt)
print("\nwrote runs/perp_oof.npz")
