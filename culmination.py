#!/usr/bin/env python3
"""
culmination.py — Tejas's idea, not from the books.

"Some bars are price-action CULMINATION bars; most are ACCUMULATION bars."
And: in a rejection off a range high the BAR is the active thing; in a pullback
inside a trend the bar is passive and the TREND is the active entity.

Nothing built so far encodes this. Every label in build_price_action.py is a flat
presence flag, so a rejection off an extreme and a lazy pullback are weighted the
same. This tests whether the distinction pays.

CULMINATION — the bar resolves something
  rejection at an extreme  made a new N-bar extreme and closed back inside
  failed breakout          closed back through the level it broke
  exhaustion               unusually large bar ending a run
  reversal bar             large body against the prior several bars

ACCUMULATION — the bar contributes to something still building
  small relative to ATR, heavy overlap with the prior bar, inside bar,
  continuing an existing run

DIRECTION MATTERS. A rejection off a HIGH is culmination for a PUT, not a call.
Scored in the signal's own direction throughout.
"""
import os, json
import numpy as np, pandas as pd
from brooks_context import load_tf, atr, ema
exec(open('rules_test.py').read().split('if __name__')[0])   # ev, block_boot, report

def culm_features(a, tf):
    ts,o,h,l,c = a[:,0],a[:,1],a[:,2],a[:,3],a[:,4]
    n=len(c); A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    rng=np.maximum(h-l,1e-12); body=np.abs(c-o)
    hi20=pd.Series(h).rolling(20,min_periods=2).max().shift(1).to_numpy()
    lo20=pd.Series(l).rolling(20,min_periods=2).min().shift(1).to_numpy()
    close_pos=(c-l)/rng

    # --- culmination, direction-specific -------------------------------------
    # rejection off the top: poked above the 20-bar high, closed in the lower third
    rej_hi = ((h > hi20) & (close_pos < 0.35)).astype(float)
    rej_lo = ((l < lo20) & (close_pos > 0.65)).astype(float)
    # failed breakout: broke the level, closed back inside it
    fbo_hi = ((h > hi20) & (c < hi20)).astype(float)
    fbo_lo = ((l < lo20) & (c > lo20)).astype(float)
    # exhaustion: >2x the recent average range with a dominant body
    avg=pd.Series(rng).rolling(10,min_periods=3).mean().to_numpy()
    exh = ((rng/np.maximum(avg,1e-12) > 2.0) & (body/rng > 0.6)).astype(float)
    # reversal bar: big body opposing the prior 3 bars' direction
    d3 = pd.Series(np.sign(c-o)).rolling(3,min_periods=3).sum().shift(1).to_numpy()
    rev_up = ((c>o) & (body/A>1.0) & (d3<=-2)).astype(float)
    rev_dn = ((c<o) & (body/A>1.0) & (d3>= 2)).astype(float)

    # --- accumulation: the bar is subordinate to something larger ------------
    ov=np.concatenate([[np.nan],(np.minimum(h[1:],h[:-1])-np.maximum(l[1:],l[:-1]))/np.maximum(rng[1:],1e-12)])
    inside=np.concatenate([[0.],((h[1:]<=h[:-1])&(l[1:]>=l[:-1])).astype(float)])
    small=(rng/A < 0.7).astype(float)
    acc = np.clip(np.nan_to_num(small)+np.nan_to_num(np.clip(ov,0,1))+inside, 0, 3)/3.0

    return pd.DataFrame({"ts":ts,
        f"k{tf}_rej_hi":rej_hi, f"k{tf}_rej_lo":rej_lo,
        f"k{tf}_fbo_hi":fbo_hi, f"k{tf}_fbo_lo":fbo_lo,
        f"k{tf}_exh":exh, f"k{tf}_rev_up":rev_up, f"k{tf}_rev_dn":rev_dn,
        f"k{tf}_acc":acc, f"k{tf}_bar_atr":rng/A})

if __name__ == "__main__":
    cols=['spot','opt_type','entry_ts','event_id','activated','entry_premium',
          'y_25x','y_10x','cx240_always_in']
    parts=[]
    for sp in ['BTC','ETH']:
        d=pd.read_parquet(f'events_ctx2/{sp}.parquet',columns=cols)
        d=d[d.activated & d.entry_premium.between(2,20)]
        for tf in (240,):
            g=culm_features(load_tf(sp,tf),tf)
            j=np.searchsorted(g.ts.to_numpy()+tf*60, d.entry_ts.to_numpy(), side='right')-1
            ok=j>=0
            for col in [x for x in g.columns if x!='ts']:
                v=np.full(len(d),np.nan); v[ok]=g[col].to_numpy()[j[ok]]
                d[col]=v
        parts.append(d)
    d=pd.concat(parts,ignore_index=True)
    call=(d.opt_type=='C').to_numpy()
    # direction-aware: for a CALL the active bar is a rejection off a LOW
    d['culm'] = np.where(call,
        np.fmax.reduce([d.k240_rej_lo, d.k240_fbo_lo, d.k240_rev_up, d.k240_exh]),
        np.fmax.reduce([d.k240_rej_hi, d.k240_fbo_hi, d.k240_rev_dn, d.k240_exh]))
    e=d.groupby('event_id').agg(ty=('opt_type','first'), ts=('entry_ts','first'),
        h25=('y_25x','mean'), h10=('y_10x','mean'), ai=('cx240_always_in','first'),
        culm=('culm','first'), acc=('k240_acc','first'), bar=('k240_bar_atr','first'),
        rej=('k240_rej_hi','first'), rejl=('k240_rej_lo','first')).reset_index()
    e['week']=((e.ts+19800)//604800).astype(int)
    e['agree']=np.where(e.ty=='C', e.ai==1, e.ai==-1)
    e=e.dropna(subset=['culm','acc'])
    print(f"events {len(e):,}  weeks {e.week.nunique()}  base hit25 {100*e.h25.mean():.2f}%")
    print(f"culmination bars: {100*(e.culm>0).mean():.1f}% of signals\n")

    print("=== CULMINATION vs ACCUMULATION ===")
    e['band']=np.where(e.culm>0,'culmination',np.where(e.acc>=0.55,'accumulation','neither'))
    t=e.groupby('band').agg(n=('h25','size'),hit25=('h25','mean'),hit10=('h10','mean'))
    t['hit25']=(100*t.hit25).round(2); t['hit10']=(100*t.hit10).round(2); print(t.to_string())

    print("\n=== as filters, standalone and MARGINAL to R4 ===")
    ag=pd.Series(e.agree.to_numpy(),index=e.index)
    for nm,m in [("culmination bar", e.culm>0),
                 ("NOT an accumulation bar", e.acc<0.55),
                 ("culmination AND not accumulation", (e.culm>0)&(e.acc<0.55))]:
        m=pd.Series(m.to_numpy(),index=e.index)
        report(e,nm+" [standalone]",m,25)
        sub=e[ag]
        report(sub,nm+" [marginal to R4]",m[ag],25)
