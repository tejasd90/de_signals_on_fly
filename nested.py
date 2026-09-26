#!/usr/bin/env python3
"""
nested.py — a wedge resolving INTO a much older line.

Tejas's weekly BTC chart: an ascending wedge from mid-2024 rises into the
descending line off the early-2024 high, and the break happens where they meet.
His claim is that this is different from either event alone — the trendline was
not broken just anyhow, it was broken BY a pattern completing.

Operationalised as NESTING: on a break day, a wedge breaks AND a separate line
breaks whose age is at least RATIO times the wedge's own span. The ratio matters
— two lines of similar age breaking together is coincidence; a 30-bar wedge
taking out a 300-day line is structure resolving into structure.
"""
import numpy as np, pandas as pd
import levels as LV, wedge as W

def build(ratio=3.0):
    rows=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,360,240):
            conf,arr=LV.all_levels(spot,tf)
            if arr is None: continue
            wds=W.find_wedges(spot,tf)
            wspan={w["break_i"]: w["overlap_bars"]*tf/1440.0 for w in wds}
            for L in conf:
                i=L["break_i"]
                if not i: continue
                age=(i-L["anchor"][0])*tf/1440.0 if L["type"]=="trendline" else np.nan
                rows.append(dict(day=pd.Timestamp(arr[i,0],unit="s").normalize(),
                    spot=spot,tf=tf,age=age,
                    is_wedge=i in wspan, wedge_span=wspan.get(i,np.nan)))
    B=pd.DataFrame(rows)
    out=[]
    for d,g in B.groupby("day"):
        w=g[g.is_wedge]
        oldest=g.age.max()
        nested=False; detail=None
        if len(w):
            ws=w.wedge_span.min()                       # the tightest wedge that day
            # any line broken the same day at least `ratio` times older than it?
            big=g[(g.age>=ratio*ws)]
            if len(big) and ws==ws:
                nested=True; detail=(ws,big.age.max())
        out.append(dict(day=d, n_wedge=int(g.is_wedge.sum()), oldest=oldest,
                        nested=nested,
                        wedge_span=w.wedge_span.min() if len(w) else np.nan,
                        nest_ratio=(detail[1]/detail[0]) if detail else np.nan))
    return pd.DataFrame(out).set_index("day")

if __name__=="__main__":
    N=build()
    cal=pd.read_csv("daily_break_profile.csv",index_col=0,parse_dates=True).join(N,rsuffix="_n")
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
    b=cal[cal.n_breaks>0]
    print(f"break days {len(b)}   base P(100x within 0-3d) = {100*base:.1f}%")
    print(f"nested days (wedge + a line >=3x its span): {int(b.nested.sum())}")
    print(f"  median nest ratio {b[b.nested].nest_ratio.median():.1f}x "
          f"(wedge span median {b[b.nested].wedge_span.median():.0f}d)\n")
    print(f"{'condition':<46}{'days':>6}{'P(100x)':>10}{'lift':>8}{'P(<=0)':>9}")
    tests={
      "WEDGE only (no old line)":        b[(b.n_wedge>0)&(b.oldest<100)].index,
      "OLD LINE only (no wedge)":        b[(b.n_wedge==0)&(b.oldest>=100)].index,
      "both, but NOT nested":            b[(b.n_wedge>0)&(b.oldest>=100)&(~b.nested)].index,
      "NESTED (wedge into a 3x older line)": b[b.nested].index,
      "wedge >=1 (any)":                 b[b.n_wedge>0].index,
      "old line >=100d (reference)":     b[b.oldest>=100].index,
      "neither":                         b[(b.n_wedge==0)&(b.oldest<100)].index,
    }
    for lab,ix in tests.items():
        m=mk(ix)
        if m.sum()<10: print(f"{lab:<46}{m.sum():>6}  (too few)"); continue
        d,p=boot(m)
        print(f"{lab:<46}{m.sum():>6}{100*(cal[m].n100_3>0).mean():>9.1f}%{100*d:>+7.1f}{p:>9.3f}")
    a=pd.Timestamp("2026-08-17")
    if a in cal.index:
        print(f"\n17 Aug: wedges {int(cal.loc[a,'n_wedge'])}, oldest line {cal.loc[a,'oldest']:.0f}d, "
              f"nested: {bool(cal.loc[a,'nested'])}"
              + (f", ratio {cal.loc[a,'nest_ratio']:.1f}x" if cal.loc[a,'nested'] else ""))
