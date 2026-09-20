#!/usr/bin/env python3
"""
exhaustion.py — "points in a pullback/crash/downtrend from where price will only
go up and won't come back."

MADE PRECISE
Tejas's phrase has an exact meaning: bar i is a PERMANENT LOW over horizon H if
no bar in (i, i+H] trades below low[i]. The down-move ran out of sellers there
and never revisited. His reasoning is liquidity exhaustion.

THE TWO THINGS THAT DECIDE WHETHER THIS IS FINDABLE
1. THE BASE RATE. Permanent lows are not rare by construction -- every running
   minimum is one. If 25% of bars in a downtrend already qualify, a "signal" that
   hits 30% is noise. The base rate is printed first, always.
2. FULL WINDOW ONLY. i+H must exist. Truncating the window near a series end
   makes late bars look permanent for free -- the exact bug that corrupted the
   earlier sustain study.

CONTEXT: only bars already in a real down-move are candidates (below the 50-day
average AND down at least 10% over 20 days), because "will only go up from here"
is a claim about bottoms, not about bars in general.

FEATURES TESTED are the standard capitulation markers: volume spike, range
expansion, long lower tail (sellers absorbed intrabar), depth below the average,
consecutive red bars, and how far price has already fallen.
"""
import glob, os
import numpy as np, pandas as pd
from spot_sustain import atr, blockboot

def daily_v(fp, min_days=250):
    """spot_sustain.daily() drops volume; capitulation needs it."""
    d=pd.read_parquet(fp).sort_values("ts")
    d["day"]=(d.ts//86400).astype(int)
    g=d.groupby("day").agg(o=("o","first"),h=("h","max"),l=("l","min"),
                           c=("c","last"),v=("v","sum"),ts=("ts","first")).reset_index()
    return g if len(g)>=min_days else None

def scan(g, sym, H=20):
    o,h,l,c,v = (g.o.to_numpy(),g.h.to_numpy(),g.l.to_numpy(),
                 g.c.to_numpy(),g.v.to_numpy())
    n=len(c); A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    ma50=pd.Series(c).rolling(50,min_periods=50).mean().to_numpy()
    vma =pd.Series(v).rolling(20,min_periods=10).mean().to_numpy()
    rng=h-l
    ret20=pd.Series(c).pct_change(20).to_numpy()
    red=(c<o).astype(float)
    red_run=np.zeros(n)
    for i in range(1,n): red_run[i]=red_run[i-1]+1 if red[i] else 0
    hi60=pd.Series(h).rolling(60,min_periods=30).max().to_numpy()
    out=[]
    for i in range(60, n-H-1):
        if not np.isfinite(A[i]) or not np.isfinite(ma50[i]) or not np.isfinite(ret20[i]): continue
        if not (c[i]<ma50[i] and ret20[i]<-0.10): continue      # a real down-move
        fwd_low=l[i+1:i+H+1].min()
        # DEFINITION FIX. The first version asked whether the bar's LOW was
        # revisited, which a wide bar closing near its high satisfies for free --
        # its low is simply far away. That made close_pos and rng_atr look
        # predictive while their forward returns were the WORST in the sample.
        # What Tejas means, and what a trader can use, is: buy at THIS CLOSE and
        # never go underwater.
        out.append(dict(
            sym=sym, ts=int(g.ts.iloc[i]),
            perm=float(fwd_low>c[i]),                            # never underwater
            perm_low=float(fwd_low>l[i]),                        # old, kept for contrast
            r=c[i+H]/c[i]-1,
            vspike=v[i]/vma[i] if vma[i]>0 else np.nan,
            rng_atr=rng[i]/A[i],
            lower_tail=(min(o[i],c[i])-l[i])/max(rng[i],1e-12),
            below_ma=(ma50[i]-c[i])/A[i],
            red_run=red_run[i],
            drawdown=c[i]/hi60[i]-1,
            close_pos=(c[i]-l[i])/max(rng[i],1e-12)))
    return out

if __name__=="__main__":
    rows=[]
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        g=daily_v(fp)
        if g is not None: rows+=scan(g, os.path.basename(fp)[:-8])
    E=pd.DataFrame(rows).replace([np.inf,-np.inf],np.nan)
    E["week"]=((E.ts+19800)//604800).astype(int)
    print(f"candidate bars inside real down-moves: {len(E):,}  "
          f"symbols {E.sym.nunique()}  weeks {E.week.nunique()}")
    print(f"\nBASE RATE — buy at the close, never underwater within 20 bars: "
          f"{100*E.perm.mean():.1f}%")
    print(f"  (old, flawed definition — bar LOW never revisited: {100*E.perm_low.mean():.1f}%)")
    print(f"  mean forward 20d return from these bars: {100*E.r.mean():+.2f}%")
    print(f"  ... and when it IS a permanent low:      {100*E[E.perm>0].r.mean():+.2f}%")
    print(f"  ... when it is NOT:                      {100*E[E.perm==0].r.mean():+.2f}%\n")
    print("Can any capitulation marker raise that base rate?")
    print(f"{'feature':<14} {'quintile':<9} {'n':>7} {'P(permanent)':>13} {'fwd 20d':>9}")
    for f in ["vspike","rng_atr","lower_tail","below_ma","red_run","drawdown","close_pos"]:
        s=E.dropna(subset=[f])
        if len(s)<1000: continue
        try: s=s.assign(q=pd.qcut(s[f],5,labels=["Q1","Q2","Q3","Q4","Q5"],duplicates="drop"))
        except Exception: continue
        for q in s.q.cat.categories:
            t=s[s.q==q]
            print(f"{f if q=='Q1' else '':<14} {str(q):<9} {len(t):>7,} "
                  f"{100*t.perm.mean():>12.1f}% {100*t.r.mean():>+8.2f}%")
        hi=(s[f]>=s[f].quantile(0.8)).to_numpy(); lo=(s[f]<=s[f].quantile(0.2)).to_numpy()
        sub=s[hi|lo].copy(); m=hi[hi|lo]
        b=blockboot(sub,"perm",m)
        if len(b): print(f"{'':<14} {'Q5-Q1':<9} {'':>7} {100*np.median(b):>+11.1f}pp  P(<=0) {(b<=0).mean():.3f}")
        print()
