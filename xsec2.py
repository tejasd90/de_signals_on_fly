#!/usr/bin/env python3
"""
xsec2.py — Steps 1 and 2: the cross-sectional book with the DEAD coins included,
liquidity-capped, and beta-hedged.

STEP 1 (survivorship). xsec.py's universe came from symbols LIVE on Delta today,
so the 22 perps that collapsed and were delisted were absent -- and 137% of the
strategy's profit came from shorting exactly that kind of name. fetch_dead.py
recovers them (median total return -74% over their listed life, frozen
post-delisting bars trimmed, renames tagged so PEPE/SHIB/BONK/FLOKI are not
double-counted against their live 1000x successors).

Naively this should HELP a short-the-wild-ones book. The honest question is
whether it helps for a reason you could have traded, which Step 2 addresses.

STEP 2 (tradeability). Three things the first version assumed away:
  - size:  positions capped at a fraction of each name's dollar volume, so the
           test cannot assume fills that would not have happened
  - beta:  the book carried -0.203 beta to the market and -0.600 correlation. It
           was not neutral; part of the return was a short-the-market bet during
           a falling tape. Beta is now hedged out explicitly each rebalance.
  - delisting: a name is dropped from the tradeable universe N days BEFORE its
           last bar, because liquidity dies before a delisting and you would not
           have been able to hold, let alone short, into it.
"""
import glob, os
import numpy as np, pandas as pd

FEE=0.0002*1.18
DELIST_BUFFER=10        # drop a name this many days before its final bar

def load(include_dead=True, include_renames=False, min_days=120):
    px={}; vol={}
    src=sorted(glob.glob("data/perp_candles/*.parquet"))
    dead=set()
    if include_dead and os.path.exists("perp_dead_manifest.csv"):
        man=pd.read_csv("perp_dead_manifest.csv")
        keep=man if include_renames else man[man.kind=="dead"]
        for s in keep.sym:
            fp=f"data/perp_dead/{s}.parquet"
            if os.path.exists(fp): src.append(fp); dead.add(s)
    for fp in src:
        sym=os.path.basename(fp)[:-8]
        d=pd.read_parquet(fp).sort_values("ts")
        d["day"]=(d.ts//86400).astype(int)
        g=d.groupby("day").agg(c=("c","last"),v=("v","sum"))
        if len(g)<min_days: continue
        if sym in dead and DELIST_BUFFER>0:      # unhold-able before delisting
            g=g.iloc[:-DELIST_BUFFER]
            if len(g)<min_days: continue
        px[sym]=g.c; vol[sym]=g.v
    return pd.DataFrame(px).sort_index(), pd.DataFrame(vol).sort_index(), dead

def xs(z): return z.sub(z.mean(axis=1),axis=0).div(z.std(axis=1).replace(0,np.nan),axis=0)

def run(P,V,reb=5,dec=0.2,cap=None,hedge=False,fee=FEE,book=1e6):
    R=np.log(P).diff()
    sig=xs(-R.rolling(20).std())
    dollar=(V*P).rolling(20).mean()          # 20d average dollar volume
    beta=R.rolling(60).cov(R.mean(axis=1)).div(R.mean(axis=1).rolling(60).var(),axis=0)
    days=P.index.to_numpy(); W=pd.DataFrame(0.0,index=P.index,columns=P.columns); hold=None
    for k,d in enumerate(days):
        if k%reb==0:
            a=sig.loc[d].dropna()
            a=a[P.loc[d].notna()]
            if len(a)<30: continue
            lo,hi=a.quantile(dec),a.quantile(1-dec)
            L,S=a[a>=hi].index,a[a<=lo].index
            h=pd.Series(0.0,index=P.columns)
            if len(L): h[L]= 0.5/len(L)
            if len(S): h[S]=-0.5/len(S)
            if cap is not None:
                # BUGFIX: the first version clipped WEIGHTS (fractions of the
                # book) against a DOLLAR limit, so the cap never bound and the
                # liquidity test was vacuous. The limit has to be expressed as a
                # weight, which requires knowing the book size:
                #     max weight = (cap x average daily dollar volume) / book
                lim=(cap*dollar.loc[d]/book).reindex(h.index).fillna(0.0)
                h=h.clip(lower=-lim,upper=lim)
                if h.abs().sum()>0: h=h/h.abs().sum()   # renormalise to 1x gross
            if hedge:
                b=beta.loc[d].reindex(h.index).fillna(0)
                net_b=(h*b).sum()
                mkt_w=-net_b                    # offsetting market exposure
                h=h.copy(); h.attrs["mkt"]=mkt_w
            hold=h
        if hold is not None: W.loc[d]=hold
    turn=W.diff().abs().sum(axis=1)
    gross=(W.shift(1)*R).sum(axis=1)
    if hedge:
        mkt=R.mean(axis=1); b=(W.shift(1)*beta.shift(1)).sum(axis=1)
        gross=gross-b*mkt                       # remove the market component
    return (gross-turn*fee), turn, W

def stats(net,label,turn=None):
    net=net.dropna()
    if len(net)<200: return
    ann=net.mean()*365; vol=net.std()*np.sqrt(365)
    eq=net.cumsum(); dd=(eq-eq.cummax()).min()
    s=net.copy(); s.index=pd.to_datetime(s.index*86400,unit="s")
    wk=s.groupby([s.index.year,s.index.isocalendar().week]).sum()
    rng=np.random.default_rng(0)
    dr=np.array([rng.choice(wk.values,len(wk),replace=True).mean()*52 for _ in range(4000)])
    print(f"  {label:<34} ann {100*ann:>+7.1f}%  vol {100*vol:>5.1f}%  Sharpe {ann/vol if vol>0 else 0:>5.2f}  "
          f"maxDD {100*dd:>6.1f}%  P(<=0) {(dr<=0).mean():.4f}  CI[{100*np.percentile(dr,5):+.0f},{100*np.percentile(dr,95):+.0f}]")

if __name__=="__main__":
    Pl,Vl,_=load(include_dead=False)
    Pd,Vd,dead=load(include_dead=True)
    print(f"live-only universe : {Pl.shape[1]} names")
    print(f"with dead included : {Pd.shape[1]} names  (+{len(dead)} delisted, "
          f"dropped {DELIST_BUFFER}d before their last bar)\n")
    print("STEP 1 — does survivorship explain the result?")
    for lbl,(P,V) in {"live-only (original)":(Pl,Vl),"+ delisted names":(Pd,Vd)}.items():
        net,turn,W=run(P,V,reb=5); stats(net,lbl,turn)
    print("\nSTEP 2a — beta hedge and rebalance frequency")
    for lbl,kw in {"as-is":dict(),"beta-hedged":dict(hedge=True),
                   "beta-hedged, weekly reb":dict(hedge=True,reb=20)}.items():
        net,turn,W=run(Pd,Vd,**kw); stats(net,lbl,turn)

    print("\nSTEP 2b — CAPACITY: cap each position at 0.5% of that name's 20d")
    print("           average dollar volume, for a range of book sizes")
    for book in (1e4,1e5,1e6,5e6,2e7,1e8):
        net,turn,W=run(Pd,Vd,cap=0.005,hedge=True,book=book)
        stats(net,f"book ${book:,.0f}",turn)

    print("\nSTEP 2c — where does the money come from now?")
    R=np.log(Pd).diff()
    net,turn,W=run(Pd,Vd,cap=0.005,hedge=True,book=1e6)
    L=(W.clip(lower=0).shift(1)*R).sum(axis=1).dropna()
    S=(W.clip(upper=0).shift(1)*R).sum(axis=1).dropna()
    tot=L.mean()+S.mean()
    print(f"  long leg  (calm coins)  ann {100*L.mean()*365:>+7.1f}%")
    print(f"  short leg (wild coins)  ann {100*S.mean()*365:>+7.1f}%")
    print(f"  short leg is {100*S.mean()/tot:.0f}% of the total")
    d2=set(W.columns)&set(dead)
    wd=W[list(d2)].abs().sum(axis=1)/W.abs().sum(axis=1).replace(0,np.nan)
    print(f"  delisted names are {100*wd.mean():.1f}% of gross exposure on average")
