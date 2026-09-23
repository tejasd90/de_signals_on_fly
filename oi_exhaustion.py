#!/usr/bin/env python3
"""
oi_exhaustion.py — exhaustion lows, retested with OPEN INTEREST.

Candle geometry failed completely on this: every capitulation marker was null and
two (long lower tail, close-near-high) were anti-predictive. But Tejas's stated
mechanism is not about bar shape — "the down move is out of liquidity and fresh
strong liquidity appears" is a claim about POSITIONING, which OI measures and
candles cannot.

The two readings that matter:
  price down + OI DOWN  = existing longs being forced out (liquidation). When OI
                          stops falling, the forced sellers are gone.
  price down + OI UP    = new shorts being built -- fuel for a squeeze, not a
                          bottom by itself.

Target unchanged and unchanged in strictness: buy THIS CLOSE and never be
underwater within H bars.
"""
import glob, os
import numpy as np, pandas as pd
from spot_sustain import atr, blockboot
from exhaustion import daily_v

def oi_daily(sym):
    fp=f"data/oi/{sym}.parquet"
    if not os.path.exists(fp): return None
    d=pd.read_parquet(fp).sort_values("ts")
    d["day"]=(d.ts//86400).astype(int)
    return d.groupby("day").oi.last()

def scan(g, oi, sym, H=20):
    g=g.copy(); g["oi"]=g.day.map(oi)
    if g.oi.isna().mean()>0.5: return []
    o,h,l,c,v = g.o.values,g.h.values,g.l.values,g.c.values,g.v.values
    OI=g.oi.values
    n=len(c); A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    ma50=pd.Series(c).rolling(50,min_periods=50).mean().to_numpy()
    ret20=pd.Series(c).pct_change(20).to_numpy()
    oi_c5 =pd.Series(OI).pct_change(5).to_numpy()
    oi_c20=pd.Series(OI).pct_change(20).to_numpy()
    oi_max20=pd.Series(OI).rolling(20,min_periods=10).max().to_numpy()
    oi_dd=OI/np.where(oi_max20>0,oi_max20,np.nan)-1        # OI vs its 20d peak
    # is the OI bleed DECELERATING? (forced sellers running out)
    oi_c5_prev=pd.Series(oi_c5).shift(5).to_numpy()
    decel=oi_c5-oi_c5_prev
    out=[]
    for i in range(60,n-H-1):
        if not np.isfinite(A[i]) or not np.isfinite(ma50[i]) or not np.isfinite(ret20[i]): continue
        if not np.isfinite(OI[i]) or not np.isfinite(oi_c20[i]): continue
        if not (c[i]<ma50[i] and ret20[i]<-0.10): continue
        fwd_low=l[i+1:i+H+1].min()
        out.append(dict(sym=sym, ts=int(g.ts.iloc[i]),
            perm=float(fwd_low>c[i]), r=c[i+H]/c[i]-1,
            oi_c5=oi_c5[i], oi_c20=oi_c20[i], oi_dd=oi_dd[i], oi_decel=decel[i],
            # the joint state: price falling with OI falling = liquidation
            liq=float(ret20[i]<0 and oi_c20[i]<0),
            shorts=float(ret20[i]<0 and oi_c20[i]>0),
            px_oi=ret20[i]*np.sign(oi_c20[i]) if np.isfinite(oi_c20[i]) else np.nan))
    return out

if __name__=="__main__":
    rows=[]
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        sym=os.path.basename(fp)[:-8]
        g=daily_v(fp); oi=oi_daily(sym)
        if g is None or oi is None: continue
        rows+=scan(g,oi,sym)
    E=pd.DataFrame(rows).replace([np.inf,-np.inf],np.nan)
    E["week"]=((E.ts+19800)//604800).astype(int)
    print(f"candidate bars in real down-moves WITH OI: {len(E):,}  "
          f"symbols {E.sym.nunique()}  weeks {E.week.nunique()}")
    print(f"BASE RATE (buy the close, never underwater 20d): {100*E.perm.mean():.2f}%")
    print(f"   return when it is a permanent low {100*E[E.perm>0].r.mean():+.1f}%  "
          f"when not {100*E[E.perm==0].r.mean():+.2f}%\n")
    print(f"{'OI feature':<22} {'quintile':<10} {'n':>7} {'P(permanent)':>13} {'fwd 20d':>9}")
    for f,lab in [("oi_c5","OI change 5d"),("oi_c20","OI change 20d"),
                  ("oi_dd","OI vs 20d peak"),("oi_decel","OI bleed decelerating")]:
        s=E.dropna(subset=[f])
        if len(s)<1000: continue
        try: s=s.assign(q=pd.qcut(s[f],5,labels=["Q1","Q2","Q3","Q4","Q5"],duplicates="drop"))
        except Exception: continue
        for j,(q,t) in enumerate(s.groupby("q",observed=True)):
            print(f"{lab if j==0 else '':<22} {str(q):<10} {len(t):>7,} "
                  f"{100*t.perm.mean():>12.2f}% {100*t.r.mean():>+8.2f}%")
        hi=(s[f]>=s[f].quantile(.8)).to_numpy(); lo=(s[f]<=s[f].quantile(.2)).to_numpy()
        sub=s[hi|lo].copy(); m=hi[hi|lo]
        b=blockboot(sub,"perm",m)
        if len(b): print(f"{'':<22} {'Q5-Q1':<10} {'':>7} {100*np.median(b):>+11.2f}pp  P {(b<=0).mean():.3f}")
        print()
    print("JOINT STATE (price falling, what is OI doing?)")
    for nm,m in {"liquidation (OI falling too)":E.liq==1,"shorts building (OI rising)":E.shorts==1}.items():
        s=E[m]
        if len(s)<300: continue
        print(f"  {nm:<32} n={len(s):>7,}  P(permanent) {100*s.perm.mean():>5.2f}%  "
              f"fwd {100*s.r.mean():>+6.2f}%")
