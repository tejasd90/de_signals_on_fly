#!/usr/bin/env python3
"""
reentry_test.py — does RE-ENTRY rescue the breakout system?

Tejas's point (2026-09-12): the video's system re-entered after a stop-out once
price closed back above the stop level. That is faster than waiting for a fresh
Donchian high, and it is exactly what would have saved the Aug 19 trade, which
was stopped inside the entry hour.

Implemented as: on a stop-out at price S, arm a re-entry. If a later daily close
exceeds S while the original breakout condition is still structurally intact
(price above the D-day high at the time), re-enter 1 unit. Cap re-entries per
trend so it cannot churn forever.
"""
import sys,glob,os,numpy as np,pandas as pd
sys.path.insert(0,".")
from pyramid_backtest import daily
FEE,FUND,ML=0.0004,0.0001,20.0

def run(g,D,U,ct,max_re,shorting=False):
    if shorting:
        g=pd.DataFrame({"o":1/g.o,"h":1/g.l,"l":1/g.h,"c":1/g.c},index=g.index)
        tr=np.maximum(g.h-g.l,np.maximum((g.h-g.c.shift()).abs(),(g.l-g.c.shift()).abs()))
        g["N"]=tr.rolling(20).mean(); g=g.dropna()
    hi=g.h.shift(1).rolling(D).max()
    out=[]; i=0; n=len(g); idx=g.index
    while i<n:
        if not (np.isfinite(hi.iloc[i]) and g.c.iloc[i]>hi.iloc[i]): i+=1; continue
        nre=0; armed_from=i
        while True:
            e=float(g.c.iloc[armed_from]); N=float(g.N.iloc[armed_from])
            if not (N>0): break
            stopd=2*N; lev=min(ML,1.0/((stopd/e)*1.5))
            if lev<1: break
            units=[e]; last=e; stop=e-stopd; peak=e; held=0; j=armed_from+1
            stopped_at=None
            while j<n:
                r=g.iloc[j]; held+=1; peak=max(peak,float(r.h))
                while len(units)<U and float(r.h)>=last+0.5*N:
                    cand=last+0.5*N
                    avg_new=(np.mean(units)*len(units)+cand)/(len(units)+1)
                    ns=max(stop,cand-stopd)
                    if (1.0/lev)<=1.5*((avg_new-ns)/avg_new): break
                    last=cand; units.append(cand); stop=ns
                stop=max(stop,peak-ct*N)
                if float(r.l)<=stop:
                    avg=float(np.mean(units)); gg=(stop-avg)/avg
                    out.append(dict(t0=idx[armed_from],R=gg*lev-lev*FEE-lev*FUND*3*held,
                                    re=nre))
                    stopped_at=(j,stop); break
                j+=1
            else:
                avg=float(np.mean(units)); gg=(float(g.c.iloc[-1])-avg)/avg
                out.append(dict(t0=idx[armed_from],R=gg*lev-lev*FEE-lev*FUND*3*held,re=nre))
                j=n; break
            if stopped_at is None or nre>=max_re: break
            sj,S=stopped_at
            # look for a later daily CLOSE back above the stop that ejected us
            k=sj+1; found=None
            while k<n:
                if float(g.c.iloc[k])>S: found=k; break
                if k-sj>20: break            # give up after 20 days
                k+=1
            if found is None: break
            nre+=1; armed_from=found; j=found
        i=max(j,i+1)
    return out

def summ(tr,lbl):
    if len(tr)<30: print(f"{lbl:<40}{'too few':>10}"); return
    df=pd.DataFrame(tr); R=df.R.to_numpy()
    df["blk"]=(df.t0.astype("int64")//10**9)//(7*86400)
    ub=df.blk.unique(); b=df.blk.to_numpy(); rng=np.random.default_rng(0); mu=[]
    for _ in range(1200):
        pk=rng.choice(ub,len(ub),replace=True)
        v=np.concatenate([R[b==q] for q in pk[:150] if (b==q).any()])
        if len(v)>20: mu.append(v.mean())
    mu=np.array(mu)
    print(f"{lbl:<40}{len(df):>7}{(R>0).mean()*100:>7.1f}%{R.mean():>+10.4f}"
          f"   [{np.percentile(mu,2.5):+.4f},{np.percentile(mu,97.5):+.4f}]")

G={}
for p in sorted(glob.glob("data/perp_candles/*.parquet")):
    g=daily(p)
    if g is not None: G[os.path.basename(p)[:-8]]=g
BE={k:v for k,v in G.items() if k in ("BTCUSD","ETHUSD")}
print(f"{'variant':<40}{'trades':>7}{'win%':>8}{'EV/trade':>10}{'':>3}{'95% CI':>20}")
print("-"*90)
for mr in [0,1,3]:
    tr=[t for s,g in G.items() for t in run(g,20,1,3.0,mr)]
    summ(tr,f"LONG all-perps D=20 U=1 re-entry<={mr}")
print()
for mr in [0,3]:
    tr=[t for s,g in G.items() for t in run(g,20,4,3.0,mr)]
    summ(tr,f"LONG all-perps D=20 U=4 re-entry<={mr}")
print()
for mr in [0,3]:
    tr=[t for s,g in BE.items() for t in run(g,20,1,3.0,mr)]
    summ(tr,f"LONG BTC+ETH D=20 U=1 re-entry<={mr}")
