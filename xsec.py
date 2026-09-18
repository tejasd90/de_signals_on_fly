#!/usr/bin/env python3
"""
xsec.py — is there a cross-sectional, market-neutral edge in the 220 perps?

WHY THIS IS A DIFFERENT QUESTION FROM EVERYTHING ELSE HERE
Every test in this project predicts DIRECTION on one or two instruments. The
governing relation for a systematic book is IR ~ IC * sqrt(breadth), and that
design has breadth ~1. A stat-arb desk does not out-predict us per bet -- an IC
of 0.02-0.05 is normal and our 5.96%-vs-4.33% is comparable -- it makes the bet
thousands of times at once, market-neutral.

The standing objection is N_eff 5.8: all crypto moves together. That is an
objection to DIRECTIONAL breadth. Cross-sectional neutrality removes the common
factor by construction, so what matters is the correlation of RESIDUALS, which is
much lower. This measures whether anything survives once the market is removed.

METHOD
Daily bars, 220 perps. Each day, cross-sectionally demean returns (the crude but
robust market-neutralisation) and rank names on causal features. IC = Spearman
rank correlation between today's feature and the forward RESIDUAL return. Then a
decile long/short book with real Delta costs.

COSTS ARE THE WHOLE GAME AT THIS FREQUENCY
maker 0.02% + 18% GST = 0.0236% per side. A long/short book rebalanced weekly
with full turnover pays ~0.094% of gross per rebalance, ~4.9%/yr. Any IC has to
clear that before it means anything.
"""
import glob, os
import numpy as np, pandas as pd
from scipy.stats import spearmanr

FEE=0.0002*1.18

def load_all(min_days=250):
    px={}; vol={}
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        sym=os.path.basename(fp)[:-8]
        d=pd.read_parquet(fp).sort_values("ts")
        d["day"]=(d.ts//86400).astype(int)
        g=d.groupby("day").agg(c=("c","last"),v=("v","sum"))
        if len(g)<min_days: continue
        px[sym]=g.c; vol[sym]=g.v
    P=pd.DataFrame(px).sort_index(); V=pd.DataFrame(vol).sort_index()
    return P,V

def build(P,V):
    R=np.log(P).diff()
    feats={}
    feats["rev5"]   = -R.rolling(5).sum()                      # short-term reversal
    feats["rev1"]   = -R                                       # 1-day reversal
    feats["mom60"]  = R.shift(5).rolling(55).sum()             # momentum, skip last week
    feats["vol20"]  = -R.rolling(20).std()                     # low-vol preference
    feats["dvol"]   = np.log1p(V).rolling(5).mean()-np.log1p(V).rolling(60).mean()
    feats["illiq"]  = -(R.abs()/np.log1p(V)).rolling(20).mean()
    # carry from the stored funding series
    F={}
    for s in P.columns:
        fp=f"data/funding/{s}.parquet"
        if not os.path.exists(fp): continue
        f=pd.read_parquet(fp).sort_values("ts")
        f["day"]=(f.ts//86400).astype(int)
        F[s]=f.groupby("day").rate.mean()
    if F:
        FR=pd.DataFrame(F).reindex(columns=P.columns).reindex(P.index)
        feats["carry"]=-FR.rolling(7).mean()      # short the expensive-to-hold longs
    return R,feats

def xs(z):  # cross-sectional z-score, market-neutral by construction
    return z.sub(z.mean(axis=1),axis=0).div(z.std(axis=1).replace(0,np.nan),axis=0)

if __name__=="__main__":
    P,V=load_all()
    print(f"universe {P.shape[1]} perps, {P.shape[0]} days "
          f"{pd.Timestamp(P.index[0]*86400,unit='s').date()} -> {pd.Timestamp(P.index[-1]*86400,unit='s').date()}")
    R,feats=build(P,V)
    names=P.columns
    print(f"\n=== how correlated ARE the residuals? (the N_eff 5.8 objection) ===")
    raw=R.dropna(how="all")
    res=raw.sub(raw.mean(axis=1),axis=0)
    cr=raw.corr().values; cs=res.corr().values
    iu=np.triu_indices_from(cr,1)
    print(f"  mean pairwise corr, RAW returns      {np.nanmean(cr[iu]):.3f}")
    print(f"  mean pairwise corr, RESIDUAL returns {np.nanmean(cs[iu]):.3f}")
    ev_raw=np.linalg.eigvalsh(np.nan_to_num(cr,nan=0)); ev_res=np.linalg.eigvalsh(np.nan_to_num(cs,nan=0))
    neff=lambda ev:(ev.sum()**2)/ (ev**2).sum()
    print(f"  effective breadth (participation ratio): raw {neff(ev_raw):.1f} -> residual {neff(ev_res):.1f}")

    for H in (1,5,20):
        fwd=R.shift(-H).rolling(H).sum().shift(-0)      # forward H-day log return
        fwd=np.log(P).diff(H).shift(-H)
        fres=fwd.sub(fwd.mean(axis=1),axis=0)           # residual (market removed)
        print(f"\n=== IC vs forward {H}-day RESIDUAL return ===")
        print(f"  {'feature':<10} {'IC mean':>9} {'IC t-stat':>10} {'IC>0 %':>8} {'n days':>7}")
        for nm,f in feats.items():
            ics=[]
            for d in f.index:
                if d not in fres.index: continue
                a=f.loc[d]; b=fres.loc[d]
                ok=a.notna()&b.notna()
                if ok.sum()<30: continue
                ics.append(spearmanr(a[ok],b[ok]).correlation)
            ics=np.array([x for x in ics if np.isfinite(x)])
            if len(ics)<50: continue
            t=ics.mean()/(ics.std()/np.sqrt(len(ics)))
            print(f"  {nm:<10} {ics.mean():>+9.4f} {t:>10.2f} {100*(ics>0).mean():>7.1f}% {len(ics):>7}")

# ─── portfolio test ───────────────────────────────────────────────────────────
def backtest(P,V,feats,sig,reb=5,dec=0.2,fee=FEE):
    """Dollar-neutral long/short, rebalanced every `reb` days, equal weight within
    each side, costed on actual turnover."""
    R=np.log(P).diff()
    z=xs(feats[sig]) if isinstance(sig,str) else xs(sig)
    days=P.index.to_numpy()
    w=pd.DataFrame(0.0,index=P.index,columns=P.columns)
    hold=None
    for k,d in enumerate(days):
        if k%reb==0:
            a=z.loc[d].dropna()
            if len(a)<30: continue
            lo,hi=a.quantile(dec),a.quantile(1-dec)
            L=a[a>=hi].index; S=a[a<=lo].index
            hold=pd.Series(0.0,index=P.columns)
            if len(L): hold[L]=0.5/len(L)
            if len(S): hold[S]=-0.5/len(S)
        if hold is not None: w.loc[d]=hold
    turn=w.diff().abs().sum(axis=1)
    gross=(w.shift(1)*R).sum(axis=1)
    net=gross-turn*fee
    return net,turn,w

if __name__=="__main__" and os.environ.get("XSEC_BT"):
    P,V=load_all(); R,feats=build(P,V)
    comp=xs(feats["vol20"])+xs(feats["illiq"])+xs(feats["mom60"])
    print(f"{'signal':<12} {'reb':>4} {'ann ret':>8} {'ann vol':>8} {'Sharpe':>7} "
          f"{'maxDD':>7} {'turn/reb':>9} {'cost/yr':>8}")
    for nm in ["vol20","illiq","mom60","rev5","rev1","carry"]:
        for reb in (5,20):
            net,turn,w=backtest(P,V,feats,nm,reb=reb)
            net=net.dropna()
            if len(net)<200: continue
            ann=net.mean()*365; vol=net.std()*np.sqrt(365)
            eq=net.cumsum(); dd=(eq-eq.cummax()).min()
            print(f"{nm:<12} {reb:>4} {100*ann:>7.1f}% {100*vol:>7.1f}% {ann/vol if vol>0 else 0:>7.2f} "
                  f"{100*dd:>6.1f}% {turn[turn>0].mean():>9.3f} {100*turn.sum()*FEE/(len(net)/365):>7.1f}%")
    net,turn,w=backtest(P,V,feats,comp,reb=20)
    net=net.dropna(); ann=net.mean()*365; vol=net.std()*np.sqrt(365)
    print(f"{'COMPOSITE':<12} {20:>4} {100*ann:>7.1f}% {100*vol:>7.1f}% {ann/vol:>7.2f}")
    # IS IT JUST 'LONG MAJORS, SHORT ALTS'? correlate holdings with a static tilt
    sz=np.log1p(V).rolling(60).mean()
    static=xs(sz)
    corr=w.corrwith(static.reindex_like(w),axis=1).mean()
    print(f"\n  mean cross-sectional corr(holdings, log-volume rank) = {corr:.3f}")
    print(f"  -> if this is near +1 the 'breadth' is one static bet: long majors, short alts")
    print(f"  turnover per rebalance (composite, 20d): {turn[turn>0].mean():.3f} "
          f"(2.0 = full replacement)")
