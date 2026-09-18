#!/usr/bin/env python3
"""
spike_range_break.py — the setup Tejas is calling live on ETH and SOL:
a large up-spike, then a tight range that HOLDS most of the spike, then a break
above the range. His confirmation is explicitly "sustaining over the trading
range", which is the same sustain measure spot_sustain.py already defines.

This is a narrower, better-specified pattern than the generic 20-day breakout,
and worth measuring on its own because the generic version is unpromising:
up-breaks sustain 21.4% at 20d and 13.1% at 60d, with mean 60d return -5.49%.

Everything is causal: the spike and the range are measured strictly before the
trigger bar, and the outcome strictly after. Calendar weeks across all symbols
remain the resampling unit.
"""
import glob, os
import numpy as np, pandas as pd
from spot_sustain import daily, atr, blockboot

SPIKE_W=5; MIN_RANGE=12; MAX_RANGE=45

def find(g, sym, spike_pct, hold_frac, tight_frac):
    h,l,c=g.h.to_numpy(),g.l.to_numpy(),g.c.to_numpy()
    n=len(c); out=[]
    for s in range(SPIKE_W, n-MIN_RANGE-61):
        base=c[s-SPIKE_W]
        top=c[s]
        if base<=0 or (top/base-1) < spike_pct: continue
        size=top-base
        # consolidation must hold the gain and stay tight, for at least MIN_RANGE bars
        for L in range(MIN_RANGE, min(MAX_RANGE, n-s-61)):
            seg_h=h[s+1:s+1+L]; seg_l=l[s+1:s+1+L]
            if seg_l.min() < base + hold_frac*size: break        # gave the spike back
            if (seg_h.max()-seg_l.min()) > tight_frac*size: break # not a tight range
            i=s+1+L
            if i>=n-61: break
            if c[i] > seg_h.max():                                # break above the range
                lvl=seg_h.max()
                row=dict(sym=sym, ts=int(g.ts.iloc[i]), spike=top/base-1, rangelen=L,
                         tight=(seg_h.max()-seg_l.min())/size, lvl=lvl)
                for H in (20,60):
                    j=min(i+H,n-1); seg=c[i+1:j+1]
                    row[f"ret{H}"]=c[j]/c[i]-1
                    row[f"sus{H}"]=float(np.all(seg>lvl)) if len(seg) else np.nan
                out.append(row); break
    return out

if __name__=="__main__":
    G={}
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        g=daily(fp)
        if g is not None: G[os.path.basename(fp)[:-8]]=g
    print(f"symbols with >=250 daily bars: {len(G)}\n")
    base=pd.read_parquet("spot_breakouts.parquet")
    up=base[base.dirn>0]
    print(f"BASELINE, any 20-day up-break: n={len(up):,}  "
          f"sustain20 {100*up.sus20.mean():.1f}%  sustain60 {100*up.sus60.mean():.1f}%  "
          f"ret20 {100*up.ret20.mean():+.2f}%  ret60 {100*up.ret60.mean():+.2f}%\n")
    print(f"{'spike':>6} {'hold':>5} {'tight':>6} | {'n':>5} {'wks':>4} {'sus20':>7} {'sus60':>7} "
          f"{'ret20':>8} {'ret60':>8} | {'vs base ret60':>14}")
    for spike_pct in (0.15,0.20,0.25):
        for hold_frac in (0.4,0.6):
            for tight_frac in (0.8,1.2):
                rows=[]
                for sym,g in G.items(): rows+=find(g,sym,spike_pct,hold_frac,tight_frac)
                if len(rows)<25:
                    print(f"{spike_pct:>6.0%} {hold_frac:>5.1f} {tight_frac:>6.1f} | "
                          f"{len(rows):>5} {'(too few)':>50}"); continue
                E=pd.DataFrame(rows); E["week"]=((E.ts+19800)//604800).astype(int)
                comb=pd.concat([E.assign(g=1), up.assign(g=0)[["week","ret60","sus60","ret20","sus20"]]],
                               ignore_index=True)
                comb["g"]=comb.g.fillna(0)
                b=blockboot(comb,"ret60",(comb.g==1).to_numpy())
                pv=f"{(b<=0).mean():.3f}" if len(b) else " - "
                d=f"{100*np.median(b):+6.2f}%" if len(b) else "   -  "
                print(f"{spike_pct:>6.0%} {hold_frac:>5.1f} {tight_frac:>6.1f} | "
                      f"{len(E):>5} {E.week.nunique():>4} {100*E.sus20.mean():>6.1f}% "
                      f"{100*E.sus60.mean():>6.1f}% {100*E.ret20.mean():>+7.2f}% "
                      f"{100*E.ret60.mean():>+7.2f}% | {d} P{pv}")
