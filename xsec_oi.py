#!/usr/bin/env python3
"""
xsec_oi.py — open interest as a CROSS-SECTIONAL signal.

Two threads join here. The strongest structural finding in this project is that
market-neutralising the 220 perps lifts effective breadth from 4.3 to 58.2, so a
weak signal becomes usable. And OI is the one Delta data source never tested.

OI failed to time exhaustion lows (P 0.26-0.90, base rate unmoved) but it did
RANK forward returns there: price-falling-with-OI-falling gave -3.47% over 20d
against -1.09% for price-falling-with-OI-rising. Ranking is exactly what a
cross-sectional book consumes.

Signals, all causal, all cross-sectionally z-scored so the market factor is gone:
  oi_mom    OI growth        -- crowding
  oi_rev    -OI growth       -- the other sign, tested honestly rather than assumed
  oi_px     OI growth x price return -- the classic four-quadrant read
  oi_turn   OI relative to its own 60d level
  oi_vol    OI volatility    -- positioning instability
"""
import glob, os
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from xsec2 import load, xs, stats, FEE, run

def oi_panel(cols, index):
    d={}
    for s in cols:
        fp=f"data/oi/{s}.parquet"
        if not os.path.exists(fp): continue
        x=pd.read_parquet(fp).sort_values("ts")
        x["day"]=(x.ts//86400).astype(int)
        d[s]=x.groupby("day").oi.last()
    return pd.DataFrame(d).reindex(index).reindex(columns=cols)

if __name__=="__main__":
    P,V,dead=load(include_dead=True)
    OI=oi_panel(list(P.columns), P.index)
    cov=OI.notna().mean().mean()
    print(f"universe {P.shape[1]} names, {P.shape[0]} days; OI coverage {100*cov:.0f}%\n")
    R=np.log(P).diff()
    g=np.log(OI.where(OI>0)).diff()
    F={}
    F["oi_mom"]  = g.rolling(5).sum()
    F["oi_rev"]  = -g.rolling(5).sum()
    F["oi_mom20"]= g.rolling(20).sum()
    F["oi_px"]   = g.rolling(20).sum()*np.sign(R.rolling(20).sum())
    F["oi_turn"] = np.log(OI.where(OI>0)) - np.log(OI.where(OI>0)).rolling(60).mean()
    F["oi_vol"]  = -g.rolling(20).std()
    for H in (5,20):
        fwd=np.log(P).diff(H).shift(-H)
        fres=fwd.sub(fwd.mean(axis=1),axis=0)
        print(f"=== IC vs forward {H}-day RESIDUAL return ===")
        print(f"  {'signal':<10} {'IC mean':>9} {'t':>7} {'IC>0':>7} {'days':>6}")
        for nm,f in F.items():
            ics=[]
            for d in f.index:
                if d not in fres.index: continue
                a=f.loc[d]; b=fres.loc[d]; ok=a.notna()&b.notna()
                if ok.sum()<30: continue
                ics.append(spearmanr(a[ok],b[ok]).correlation)
            ics=np.array([x for x in ics if np.isfinite(x)])
            if len(ics)<50: continue
            print(f"  {nm:<10} {ics.mean():>+9.4f} {ics.mean()/(ics.std()/np.sqrt(len(ics))):>7.2f} "
                  f"{100*(ics>0).mean():>6.1f}% {len(ics):>6}")
        print()
    print("=== decile long/short books, beta-hedged, costed ===")
    for nm,f in F.items():
        z=xs(f)
        net,turn,W=run(P,V,reb=5,hedge=True)   # placeholder to reuse plumbing
        # rebuild with this signal
        days=P.index.to_numpy(); Wn=pd.DataFrame(0.0,index=P.index,columns=P.columns); hold=None
        beta=R.rolling(60).cov(R.mean(axis=1)).div(R.mean(axis=1).rolling(60).var(),axis=0)
        for k,d in enumerate(days):
            if k%5==0:
                a=z.loc[d].dropna(); a=a[P.loc[d].notna()]
                if len(a)<30: continue
                lo,hi=a.quantile(0.2),a.quantile(0.8)
                L,S=a[a>=hi].index,a[a<=lo].index
                h=pd.Series(0.0,index=P.columns)
                if len(L): h[L]= 0.5/len(L)
                if len(S): h[S]=-0.5/len(S)
                hold=h
            if hold is not None: Wn.loc[d]=hold
        gr=(Wn.shift(1)*R).sum(axis=1); tr=Wn.diff().abs().sum(axis=1)
        b=(Wn.shift(1)*beta.shift(1)).sum(axis=1)
        netn=(gr-b*R.mean(axis=1)-tr*FEE)
        stats(netn,nm)
