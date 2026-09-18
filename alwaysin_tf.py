#!/usr/bin/env python3
"""
alwaysin_tf.py — was 4h the right timeframe for R4, or just the one available?

R4 ("the signal agrees with the always-in direction") is the single most robust
rule in this project. But the timeframe was never chosen on merit. brooks_context.py
fixes the ladder at 60/240/1440 for a DATA reason, stated in its own docstring:
six of the twelve signal durations have no stored spot series, so a fixed
1h/4h/1d ladder was the only one computable for every event. Within that ladder
4h beat 1h and 1d. 6h, 8h, 12h and weekly were never candidates.

data/spot_grouped/ does carry 60/120/240/360/480/720/1440/10080, so the question
is answerable. Always-in is unchanged from brooks_context.py:201 --
  +1 if close > EMA20 > EMA50, -1 if close < EMA20 < EMA50, else 0
-- so only the bar size varies. Same events, same controls, same break-even.

MULTIPLICITY: eight timeframes is eight tries. The ladder is reported whole, not
just its maximum, and a neighbouring-timeframe check matters more than any single
P -- a real effect should degrade smoothly, not spike at one bar size.
"""
import json, os
import numpy as np, pandas as pd
from rules_test import ev, block_boot, COST
from channel_full import build_events

TFS=[60,120,240,360,480,720,1440,10080]

def ai_series(spot, tf):
    p=f"data/spot_grouped/{spot}/{tf}.json"
    if not os.path.exists(p): return None
    a=np.asarray([r[:5] for r in json.load(open(p))],float)
    a=a[np.argsort(a[:,0])]
    ts,c=a[:,0],a[:,4]
    e20=pd.Series(c).ewm(span=20,adjust=False).mean().to_numpy()
    e50=pd.Series(c).ewm(span=50,adjust=False).mean().to_numpy()
    ai=np.where((c>e20)&(e20>e50),1.0,np.where((c<e20)&(e20<e50),-1.0,0.0))
    return ts, ai

if __name__=="__main__":
    e=build_events((2.0,20.0))
    for tf in TFS:
        col=np.full(len(e),np.nan)
        for spot in ("BTC","ETH"):
            s=ai_series(spot,tf)
            if s is None: continue
            ts,ai=s
            m=(e.spot==spot).to_numpy()
            # the bar must have CLOSED before entry
            j=np.searchsorted(ts+tf*60, e.ts.to_numpy()[m], side="right")-1
            ok=j>=0
            v=np.full(m.sum(),np.nan); v[ok]=ai[j[ok]]
            col[m]=v
        e[f"ai{tf}"]=col
    bull=(e.ty=="C").to_numpy()
    print(f"events {len(e):,}  weeks {e.week.nunique()}  base hit25 {100*e.h25.mean():.2f}%  "
          f"break-even 4.33%   base hit100 {100*e.h100.mean():.3f}%  BE 1.083%\n")
    print(f"{'timeframe':>10} {'cover':>6} {'keep':>6} {'wks':>4} | {'hit25':>7} {'dEV':>8} "
          f"{'P':>6} {'$/wk':>7} | {'hit100':>7} {'dEV100':>8} {'P100':>6}")
    for tf in TFS:
        a=e[f"ai{tf}"]
        m=np.where(bull, a==1, a==-1)
        if m.sum()<300: print(f"{tf:>9}m (too few: {int(m.sum())})"); continue
        out=[f"{tf:>9}m {100*a.notna().mean():>5.1f}% {100*m.mean():>5.1f}% "
             f"{e[m].week.nunique():>4}"]
        for T in (25,100):
            h=e[m][f"h{T}"].mean()
            dv,dp=block_boot(e,pd.Series(m,index=e.index),T)
            if len(dv)==0: out.append(" |   -"); continue
            if T==25:
                out.append(f" | {100*h:>6.2f}% {np.median(dv):>+8.3f} {(dv<=0).mean():>6.3f} {np.median(dp):>+7.1f}")
            else:
                out.append(f" | {100*h:>6.3f}% {np.median(dv):>+8.3f} {(dv<=0).mean():>6.3f}")
        print("".join(out))

    print("\n=== combinations (agreement across adjacent timeframes) ===")
    combos={"4h only (current R4)":[240],"6h only":[360],"12h only":[720],"daily only":[1440],
            "4h AND 6h":[240,360],"6h AND 12h":[360,720],"4h AND 12h":[240,720],
            "6h AND daily":[360,1440],"4h AND 6h AND 12h":[240,360,720],
            "12h AND daily":[720,1440],"12h AND weekly":[720,10080]}
    for nm,tfs in combos.items():
        m=np.ones(len(e),bool)
        for tf in tfs:
            a=e[f"ai{tf}"]; m=m & np.where(bull,a==1,a==-1)
        if m.sum()<300: print(f"  {nm:<24} (too few)"); continue
        h=e[m].h25.mean(); dv,dp=block_boot(e,pd.Series(m,index=e.index),25)
        print(f"  {nm:<24} keep {100*m.mean():>5.1f}%  wks {e[m].week.nunique():>3}  "
              f"hit {100*h:>5.2f}%  dEV {np.median(dv):>+7.3f}  P {(dv<=0).mean():.3f}  "
              f"$/wk {np.median(dp):>+7.1f}")
