#!/usr/bin/env python3
"""
tune_rules.py — tune the parameters that were picked by eye.

R4's always-in is "close above EMA20 and EMA50 with EMA20>EMA50, on 4h". R5's
regime is "20-day efficiency>0.35 and 20-day return>0". None of those five
numbers was chosen by measurement.

DISCIPLINE. Sweeping many parameters over many rules manufactures significance:
at P<0.05 roughly 1 in 20 cells is a false positive. So full grids are printed
and only a COHERENT REGION counts — neighbouring cells agreeing. An isolated
good cell is noise, and is reported as noise.
"""
import json, numpy as np, pandas as pd
COST=0.0826
def EV(p,T=25): return p*(T-1)-(1-p)-COST

def load(spot,tf):
    a=np.asarray(json.load(open(f'data/spot_grouped/{spot}/{tf}.json')),float)
    return a[np.argsort(a[:,0])]

def ema(x,n): return pd.Series(x).ewm(span=n,adjust=False).mean().to_numpy()

def always_in(a, fast, slow):
    c=a[:,4]; ef,es=ema(c,fast),ema(c,slow)
    return np.where((c>ef)&(ef>es),1.0,np.where((c<ef)&(ef<es),-1.0,0.0))

def regime(a, lb, thr):
    c=a[:,4]
    ret=np.concatenate([np.full(lb,np.nan), c[lb:]/c[:-lb]-1])
    net=np.abs(np.concatenate([np.full(lb,np.nan), c[lb:]-c[:-lb]]))
    tot=pd.Series(np.abs(np.diff(c,prepend=c[0]))).rolling(lb,min_periods=2).sum().to_numpy()
    eff=net/np.maximum(tot,1e-12)
    return np.where((eff>thr)&(ret>0),1.0,np.where((eff>thr)&(ret<0),-1.0,0.0))

def join(ev, spot, tf, series):
    a=load(spot,tf)
    j=np.searchsorted(a[:,0]+tf*60, ev.entry_ts.to_numpy(), side='right')-1
    v=np.full(len(ev),np.nan); ok=j>=0; v[ok]=series[j[ok]]
    return v

if __name__=="__main__":
    base=[]
    for sp in ['BTC','ETH']:
        d=pd.read_parquet(f'events_ctx2/{sp}.parquet',
            columns=['spot','opt_type','entry_ts','event_id','activated','entry_premium','y_25x'])
        d=d[d.activated & d.entry_premium.between(2,20)]
        base.append(d)
    ev_=pd.concat(base,ignore_index=True)
    print(f"rows {len(ev_):,}  events {ev_.event_id.nunique():,}")

    # ---- R4: sweep timeframe and EMA pair --------------------------------
    print("\n=== R4: always-in definition. hit25 when the signal AGREES ===")
    print(f"  {'tf':>6}{'fast/slow':>12}{'keep':>8}{'hit25':>9}{'EV':>9}")
    res={}
    for tf in (60,240,480,1440):
        for fast,slow in ((10,20),(20,50),(20,100),(50,200)):
            cols=[]
            for sp in ['BTC','ETH']:
                s=ev_[ev_.spot==sp]
                cols.append(pd.Series(join(s,sp,tf,always_in(load(sp,tf),fast,slow)),index=s.index))
            ai=pd.concat(cols).sort_index()
            call=(ev_.opt_type=='C').to_numpy()
            agree=np.where(call, ai==1, ai==-1)
            g=ev_.assign(a=agree).groupby('event_id').agg(a=('a','first'),h=('y_25x','mean'))
            k=g[g.a]; h=k.h.mean()
            res[(tf,fast,slow)]=(len(k)/len(g),h)
            print(f"  {tf:>6}{f'{fast}/{slow}':>12}{100*len(k)/len(g):>7.1f}%{100*h:>8.2f}%{EV(h):>9.3f}")
    bt=max(res,key=lambda k:EV(res[k][1]))
    print(f"  best: tf={bt[0]} ema {bt[1]}/{bt[2]}  hit {100*res[bt][1]:.2f}%  (current: tf=240 ema 20/50)")
