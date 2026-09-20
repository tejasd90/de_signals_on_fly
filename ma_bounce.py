#!/usr/bin/env python3
"""
ma_bounce.py — the 44 MA pullback-reversal claim.

THE CLAIM (via a YouTuber, relayed by Tejas)
"A bullish green candle near the 44 MA is a sign of the pullback reversing into
trend continuation" -- approached FROM ABOVE in a bull trend, and a weaker
version from below in a bear trend.

THE TWO CONTROLS THAT DECIDE IT
1. IS THE MA DOING ANY WORK? Most MA-bounce claims are really "buy dips in an
   uptrend", with the average adding nothing. So the comparison is not
   signal-vs-everything, it is signal-vs-GREEN-CANDLE-IN-THE-SAME-UPTREND. If
   the MA touch adds nothing on top of that, the MA is decoration.
2. IS 44 SPECIAL? Swept against 20/30/40/44/50/60/100/200. A real level effect
   should show a PLATEAU (neighbouring lengths behaving alike, as the always-in
   timeframe sweep did); a spike at exactly 44 with 40 and 50 dead would mean
   curve-fitting or folklore, not structure.

Traded perp candles, not the MARK series -- `spot` elsewhere in this project is
MARK:BTCUSD, an exchange fair-value estimate with no volume that diverges from
prints by up to 1012 bp in stress.

Weeks across all symbols are the resampling unit; 158 crypto perps are nowhere
near independent.
"""
import glob, os
import numpy as np, pandas as pd
from spot_sustain import daily, atr, blockboot

def events(g, sym, ma_len, tf_bars=1, tol=0.5, H=(5,10,20)):
    o,h,l,c = g.o.to_numpy(),g.h.to_numpy(),g.l.to_numpy(),g.c.to_numpy()
    n=len(c); A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    ma=pd.Series(c).rolling(ma_len,min_periods=ma_len).mean().to_numpy()
    ma_slope=np.concatenate([[np.nan],np.diff(ma)])
    long_ma=pd.Series(c).rolling(200,min_periods=100).mean().to_numpy()
    green=(c>o)
    # trend state, from the SLOWER average, so it is not the same line being tested
    bull=(c>long_ma)&(ma_slope>0)
    bear=(c<long_ma)&(ma_slope<0)
    # "near the MA, approached from above": the bar's low reaches down to within
    # tol ATR of the MA while the close holds above it
    near_above=(l<=ma+tol*A)&(c>ma)
    near_below=(h>=ma-tol*A)&(c<ma)
    out=[]
    for i in range(max(ma_len,200)+2, n-max(H)-1):
        if not np.isfinite(A[i]) or not np.isfinite(ma[i]): continue
        row=dict(sym=sym, ts=int(g.ts.iloc[i]), i=i,
                 bull=bool(bull[i]), bear=bool(bear[i]), green=bool(green[i]),
                 near_above=bool(near_above[i]), near_below=bool(near_below[i]),
                 dist_ma=(c[i]-ma[i])/A[i])
        for hh in H:
            row[f"r{hh}"]=c[i+hh]/c[i]-1
        out.append(row)
    return out

if __name__=="__main__":
    G={}
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        g=daily(fp)
        if g is not None: G[os.path.basename(fp)[:-8]]=g
    print(f"symbols {len(G)}  (daily bars from traded perp candles)\n")
    print("SETUP: green candle touching the MA from above, in an uptrend")
    print("CONTROL: green candle in the SAME uptrend, NOT near the MA\n")
    print(f"{'MA':>5} {'setup n':>8} {'wks':>4} | {'setup r10':>10} {'control r10':>12} "
          f"{'edge':>8} {'P(<=0)':>7} | {'setup r20':>10} {'ctrl r20':>10} {'edge':>8} {'P':>6}")
    for ma_len in (20,30,40,44,50,60,100,200):
        rows=[]
        for sym,g in G.items(): rows+=events(g,sym,ma_len)
        E=pd.DataFrame(rows)
        if E.empty: continue
        E["week"]=((E.ts+19800)//604800).astype(int)
        U=E[E.bull&E.green]                       # green candles in an uptrend
        setup=U.near_above.to_numpy()
        if setup.sum()<150 or (~setup).sum()<150:
            print(f"{ma_len:>5} (too few: {int(setup.sum())})"); continue
        line=f"{ma_len:>5} {int(setup.sum()):>8,} {U[setup].week.nunique():>4}"
        for hh in (10,20):
            a=U[setup][f"r{hh}"].mean(); b=U[~setup][f"r{hh}"].mean()
            bs=blockboot(U,f"r{hh}",setup)
            p=(bs<=0).mean() if len(bs) else np.nan
            line+=f" | {100*a:>+9.2f}% {100*b:>+11.2f}% {100*(a-b):>+7.2f}% {p:>7.3f}"
        print(line)
