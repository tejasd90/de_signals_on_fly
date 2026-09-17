#!/usr/bin/env python3
"""
significance.py — Tejas's refined idea: is the price action at the signal point
SIGNIFICANT or REGULAR?

Distinct from the culmination test, which asked a structural question (does this
bar resolve something?) and came back negative. This asks an ENERGY question:
is the market actually moving with force right now? His own example separates
them — 3-4 strong trend bars after a pullback are accumulation STRUCTURALLY but
significant ENERGETICALLY, and they pay because each displaces the option a lot.

WHY THIS IS NOT A THIRTY-FIRST RULE
Every rule tested so far answers "which way?". This answers "how much?". A
multibagger needs both. R4 supplies direction; nothing has supplied magnitude.

MEASURED AT THE SIGNAL'S OWN TIMEFRAME (his requirement)
Spot is only fetched at 8 durations but signals fire on 12, so the six missing
ones come from export_spot_tf.js, which uses the project's own grouper. Verified
lossless against the stored series: 8,463 shared bars, 0 differing.

UNDIRECTED, by his choice. Significance says a big move is underway, not which
way. Direction stays R4's job; the interaction test is where the two meet.
"""
import os, json
import numpy as np, pandas as pd
exec(open('rules_test.py').read().split('if __name__')[0])   # ev, block_boot, report

SG = "data/spot_grouped"
DURS = [30,40,45,60,90,120,180,240,360,480,720,1440]

def load_tf_grouped(spot, dur):
    p = os.path.join(SG, spot, f"{dur}.json")
    if not os.path.exists(p): return None
    a = np.asarray(json.load(open(p)), float)
    return a[np.argsort(a[:,0])]

def atr_(h,l,c,n=14):
    pc=np.concatenate([[c[0]],c[:-1]])
    tr=np.maximum(h-l,np.maximum(np.abs(h-pc),np.abs(l-pc)))
    return pd.Series(tr).rolling(n,min_periods=2).mean().to_numpy()

def sig_features(a):
    ts,o,h,l,c = a[:,0],a[:,1],a[:,2],a[:,3],a[:,4]
    n=len(c); A=atr_(h,l,c); A=np.where(A>0,A,np.nan)
    rng=np.maximum(h-l,1e-12); body=np.abs(c-o)
    F={"ts":ts}
    # ENERGY — how much this bar and the recent few actually moved
    F["bar_atr"]  = rng/A
    F["body_atr"] = body/A
    for L in (3,5,10):
        prev=np.concatenate([np.full(L,np.nan), c[:-L]])
        F[f"disp{L}"]=np.abs(c-prev)/A
    # URGENCY — one-sided, non-overlapping, body-dominated bars
    sgn=np.sign(c-o); run=np.zeros(n)
    for i in range(1,n): run[i]=run[i-1]+1 if sgn[i]==sgn[i-1] and sgn[i]!=0 else 1
    F["run_len"]=run
    ov=np.concatenate([[np.nan],(np.minimum(h[1:],h[:-1])-np.maximum(l[1:],l[:-1]))/np.maximum(rng[1:],1e-12)])
    F["nonoverlap5"]=1-pd.Series(np.clip(ov,0,1)).rolling(5,min_periods=2).mean().to_numpy()
    F["bodyfrac5"]=pd.Series(body/rng).rolling(5,min_periods=2).mean().to_numpy()
    # EXPANSION — is volatility rising
    A20=np.concatenate([np.full(20,np.nan), A[:-20]])
    F["atr_expand"]=A/A20
    F["rng_vs_avg"]=rng/np.maximum(pd.Series(rng).rolling(20,min_periods=3).mean().to_numpy(),1e-12)
    # TRAVEL — distance covered
    F["travel10"]=pd.Series(np.abs(np.diff(c,prepend=c[0]))).rolling(10,min_periods=2).sum().to_numpy()/A
    return pd.DataFrame(F)

COMPONENTS=["bar_atr","body_atr","disp3","disp5","disp10","run_len",
            "nonoverlap5","bodyfrac5","atr_expand","rng_vs_avg","travel10"]

if __name__ == "__main__":
    cols=['spot','opt_type','expiry','duration','entry_ts','event_id','activated',
          'entry_premium','moneyness_pct','y_25x','y_10x','cx240_always_in']
    out=[]
    for sp in ['BTC','ETH']:
        d=pd.read_parquet(f'events_ctx2/{sp}.parquet',columns=cols)
        d=d[d.activated & d.entry_premium.between(2,20)]
        for dur in DURS:
            m=d.duration==dur
            if not m.any(): continue
            a=load_tf_grouped(sp,dur)
            if a is None: continue
            g=sig_features(a)
            # LOOKAHEAD GUARD: last bar that CLOSED at or before entry
            j=np.searchsorted(g.ts.to_numpy()+dur*60, d.loc[m,'entry_ts'].to_numpy(), side='right')-1
            ok=j>=0
            sub=d[m].copy()
            # z-score inside this (spot,duration) series so scales compare across TFs
            for col in COMPONENTS:
                v=g[col].to_numpy(); mu,sd=np.nanmean(v),np.nanstd(v)
                z=np.full(m.sum(),np.nan)
                z[ok]=((v[j[ok]]-mu)/(sd if sd>0 else 1))
                sub[col]=np.clip(z,-4,4)
            out.append(sub)
    d=pd.concat(out,ignore_index=True)
    d['sig_score']=d[COMPONENTS].mean(axis=1)
    e=d.groupby('event_id').agg(ty=('opt_type','first'),ts=('entry_ts','first'),
        dur=('duration','first'), h25=('y_25x','mean'), h10=('y_10x','mean'),
        ai=('cx240_always_in','first'), mny=('moneyness_pct','first'),
        prem=('entry_premium','first'), expiry=('expiry','first'),
        sig=('sig_score','first')).reset_index().dropna(subset=['sig'])
    e['week']=((e.ts+19800)//604800).astype(int)
    e['agree']=np.where(e.ty=='C', e.ai==1, e.ai==-1)
    e['q']=pd.qcut(e.sig,5,labels=['Q1 quiet','Q2','Q3','Q4','Q5 loud'])
    print(f"events {len(e):,}  weeks {e.week.nunique()}  base hit25 {100*e.h25.mean():.2f}%\n")

    print("=== significance quintile (own timeframe, undirected) ===")
    t=e.groupby('q',observed=True).agg(n=('h25','size'),hit25=('h25','mean'),hit10=('h10','mean'))
    t['hit25']=(100*t.hit25).round(2); t['hit10']=(100*t.hit10).round(2); print(t.to_string())

    print("\n=== R4 x significance — direction from R4, magnitude from this? ===")
    t=e.groupby(['agree','q'],observed=True).agg(n=('h25','size'),hit25=('h25','mean'))
    t['hit25']=(100*t.hit25).round(2); print(t.to_string())

    print("\n=== as a filter ===")
    top=pd.Series((e.q=='Q5 loud').to_numpy(),index=e.index)
    ag=pd.Series(e.agree.to_numpy(),index=e.index)
    report(e,"top-quintile significance [standalone]",top,25)
    report(e[ag],"top-quintile significance [marginal to R4]",top[ag],25)
    report(e,"R4 alone (comparison)",ag,25)

    print("\n=== by signal timeframe (lift of Q5 over Q1) ===")
    for dur in DURS:
        s=e[e.dur==dur]
        if len(s)<3000: continue
        a=s[s.q=='Q5 loud'].h25.mean(); b=s[s.q=='Q1 quiet'].h25.mean()
        print(f"  {dur:>5}m  n={len(s):>7,}  Q5 {100*a:5.2f}%  Q1 {100*b:5.2f}%  lift {a/max(b,1e-9):5.2f}x")
