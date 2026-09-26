#!/usr/bin/env python3
"""
approach.py — HOW price arrived at the level, not how quiet it was.

Tejas: price drifting SIDEWAYS into a trendline breaks harder than price that
rallied/fell steeply to reach it, because the steep approach already spent the
energy. Testable, and deliberately NOT the squeeze measure that has now failed
four times — squeeze is range CONTRACTION, this is net DIRECTIONAL TRAVEL. A
market can be wide-ranged and still go nowhere, which is "energy conserved" by
his logic and "not compressed" by the old one.

Three ways to measure the approach over the N bars before the break:
  travel   net move toward the level, in ATR      (big = spent energy)
  effic    |net| / summed |moves|                 (high = trended in, low = chopped in)
  slope    per-bar drift toward the level, in ATR
Signed so that positive always means "moved toward the level", i.e. up into a
resistance or down into a support.
"""
import numpy as np, pandas as pd
import levels as LV, wedge as W

def build(N=10):
    rows=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,360,240):
            conf,arr=LV.all_levels(spot,tf)
            if arr is None: continue
            o,h,l,c=arr[:,1],arr[:,2],arr[:,3],arr[:,4]; A=LV.atr(h,l,c)
            dif=np.abs(np.diff(c,prepend=c[0]))
            wd={w["break_i"] for w in W.find_wedges(spot,tf)}   # once per series,
                                                               # not once per level
            for L in conf:
                i=L["break_i"]
                if not i or i<N+2 or A[i]<=0: continue
                sgn = 1.0 if L["kind"]=="R" else -1.0     # toward a resistance = up
                net = sgn*(c[i-1]-c[i-1-N])/A[i]          # approach ENDS the bar before
                tot = dif[i-N:i].sum()/A[i]
                rows.append(dict(day=pd.Timestamp(arr[i,0],unit="s").normalize(),
                    spot=spot,tf=tf,kind=L["kind"],
                    travel=net, effic=abs(net)/max(tot,1e-9), tot=tot,
                    age=(i-L["anchor"][0])*tf/1440.0 if L["type"]=="trendline" else np.nan,
                    wedge=i in wd))
    return pd.DataFrame(rows)

if __name__=="__main__":
    from spot_sustain import blockboot
    B=build()
    # per day take the FLATTEST approach among that day's breaks
    G=B.groupby("day").agg(travel=("travel","min"),effic=("effic","min"),
                           tot=("tot","median"),age=("age","max"))
    cal=pd.read_csv("daily_break_profile.csv",index_col=0,parse_dates=True).join(G,rsuffix="_a")
    cal["week"]=cal.index.isocalendar().week.astype(str)+"-"+cal.index.year.astype(str)
    base=(cal.n100_3>0).mean()
    rng=np.random.default_rng(0); wks=cal.week.unique(); idx={w:np.where(cal.week==w)[0] for w in wks}
    def boot(m):
        y=(cal.n100_3.values>0); dr=[]
        for _ in range(2500):
            sel=np.concatenate([idx[w] for w in rng.choice(wks,len(wks),replace=True)])
            mm=m[sel]; yy=y[sel]
            if mm.sum()<5 or (~mm).sum()<5: continue
            dr.append(yy[mm].mean()-yy[~mm].mean())
        dr=np.array(dr); return (np.median(dr),(dr<=0).mean())
    def mk(ix):
        m=np.zeros(len(cal),bool); m[cal.index.get_indexer(ix)]=True; return m
    brk=cal[cal.n_breaks>0].dropna(subset=["travel"])
    print(f"break days with an approach measured: {len(brk)}   base P(100x,0-3d) = {100*base:.1f}%")
    print(f"travel (net move INTO the level over 10 bars, ATR): "
          f"p25 {brk.travel.quantile(.25):+.2f}  median {brk.travel.median():+.2f}  p75 {brk.travel.quantile(.75):+.2f}\n")
    print(f"{'condition':<44}{'days':>6}{'P(100x)':>10}{'lift':>8}{'P(<=0)':>9}")
    q1,q3=brk.travel.quantile(.25),brk.travel.quantile(.75)
    e1,e3=brk.effic.quantile(.25),brk.effic.quantile(.75)
    tests={
      "SIDEWAYS approach (travel in bottom 25%)": brk[brk.travel<=q1].index,
      "STEEP approach   (travel in top 25%)":     brk[brk.travel>=q3].index,
      "CHOPPY approach  (efficiency bottom 25%)": brk[brk.effic<=e1].index,
      "TRENDED approach (efficiency top 25%)":    brk[brk.effic>=e3].index,
      "sideways AND old line >=100d":             brk[(brk.travel<=q1)&(brk.age>=100)].index,
      "steep AND old line >=100d":                brk[(brk.travel>=q3)&(brk.age>=100)].index,
      "old line >=100d (reference)":              brk[brk.age>=100].index,
    }
    for lab,ix in tests.items():
        m=mk(ix)
        if m.sum()<12: print(f"{lab:<44}{m.sum():>6}  (too few)"); continue
        d,p=boot(m)
        print(f"{lab:<44}{m.sum():>6}{100*(cal[m].n100_3>0).mean():>9.1f}%{100*d:>+7.1f}{p:>9.3f}")
    a=pd.Timestamp("2026-08-17")
    if a in cal.index and cal.loc[a,"travel"]==cal.loc[a,"travel"]:
        print(f"\n17 Aug: approach travel {cal.loc[a,'travel']:+.2f} ATR "
              f"(pctile {100*(brk.travel<cal.loc[a,'travel']).mean():.0f}), "
              f"efficiency {cal.loc[a,'effic']:.2f}")
