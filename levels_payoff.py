#!/usr/bin/env python3
"""
levels_payoff.py — do breaks of 3x-rejected levels actually produce the big
option multiples?

THE TEST
Build, per (spot, day), the best option multiple achieved by any move ENTERED
that day (from data/multibaggers, which is signal-independent: every qualifying
move, whether or not anything fired). Then compare days on which a confirmed
level broke against every other day.

CAUSALITY: a level is only usable from its THIRD rejection onward, and a break is
by definition later than that, so no break event uses information from its own
future. Many levels break on the same day; events are deduped to (spot, day).

WEEKS are the resampling unit, as everywhere else in this project.
"""
import glob, json, os
import numpy as np, pandas as pd
import levels as LV

def daily_best(spot):
    """Per day: the best ratio among moves ENTERED that day, and how many
    contracts cleared 100x."""
    rows=[]
    for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
        try: d=json.load(open(fp))
        except Exception: continue
        for r in d.get("rows",[]):
            if not r.get("entryTs"): continue
            rows.append((r["entryTs"][:10], float(r["ratio"])))
    if not rows: return None
    x=pd.DataFrame(rows,columns=["day","ratio"])
    g=x.groupby("day").agg(best=("ratio","max"), n10=("ratio","size"),
                           n100=("ratio",lambda s:(s>=100).sum()))
    g.index=pd.to_datetime(g.index)
    return g

if __name__=="__main__":
    allev=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,240):
            conf,arr=LV.all_levels(spot,tf)
            for L in conf:
                if not L["break_ts"]: continue
                allev.append(dict(spot=spot, tf=tf, type=L["type"], kind=L["kind"],
                    n_rej=L["n_rej"], day=pd.Timestamp(L["break_ts"],unit="s").normalize()))
    E=pd.DataFrame(allev)
    print(f"break events: {len(E):,}  ->  deduped to (spot, day, tf): "
          f"{E.drop_duplicates(['spot','day','tf']).shape[0]:,}\n")
    for spot in ("BTC","ETH"):
        g=daily_best(spot)
        if g is None: continue
        cal=pd.DataFrame(index=pd.date_range(g.index.min(),g.index.max(),freq="D"))
        cal=cal.join(g).fillna({"best":0,"n10":0,"n100":0})
        cal["week"]=cal.index.isocalendar().week.astype(str)+"-"+cal.index.year.astype(str)
        print(f"=== {spot} === {len(cal):,} days, base rates:")
        print(f"    a >=100x move started on {100*(cal.n100>0).mean():.1f}% of days; "
              f"median best ratio {cal.best.median():.1f}x")
        for tf in (1440,240):
            for min_rej in (3,5,8):
                brk=E[(E.spot==spot)&(E.tf==tf)&(E.n_rej>=min_rej)].day.unique()
                m=cal.index.isin(brk)
                if m.sum()<15: continue
                on,off=cal[m],cal[~m]
                # weekly block bootstrap on the difference in P(a 100x day)
                rng=np.random.default_rng(0)
                wks=cal.week.unique(); idx={w:np.where(cal.week==w)[0] for w in wks}
                dr=[]
                for _ in range(2000):
                    pick=rng.choice(wks,len(wks),replace=True)
                    sel=np.concatenate([idx[w] for w in pick])
                    mm=m[sel]; y=(cal.n100.values>0)[sel]
                    if mm.sum()<5 or (~mm).sum()<5: continue
                    dr.append(y[mm].mean()-y[~mm].mean())
                dr=np.array(dr)
                p=(dr<=0).mean() if len(dr) else np.nan
                print(f"    tf{tf:<5} >={min_rej} rej : {m.sum():>4} break days | "
                      f"P(100x day) {100*(on.n100>0).mean():>5.1f}% vs {100*(off.n100>0).mean():>5.1f}%  "
                      f"lift {(on.n100>0).mean()/max((off.n100>0).mean(),1e-9):>4.2f}x  "
                      f"P(<=0) {p:.3f} | median best {on.best.median():>6.1f}x vs {off.best.median():>5.1f}x")
        print()
