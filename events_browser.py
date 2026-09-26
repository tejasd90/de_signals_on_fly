#!/usr/bin/env python3
"""
events_browser.py — look at the day table two ways.

FORWARD   rank every day by what broke, so 17/19 Aug surface on their own.
REVERSE   start from the days that actually PAID (a 100x/200x move began) and
          ask what, if anything, the level system saw beforehand. That is the
          honest coverage test: it counts the big days we MISSED, which no
          forward test can show.

  python events_browser.py --top 25
  python events_browser.py --reverse --target 100
  python events_browser.py --day 2026-08-17
"""
import glob, json, argparse
import numpy as np, pandas as pd
import levels as LV, wedge as W

def break_table():
    rows=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,360,240):
            conf,arr=LV.all_levels(spot,tf)
            if arr is None: continue
            o,h,l,c=arr[:,1],arr[:,2],arr[:,3],arr[:,4]; A=LV.atr(h,l,c)
            wd={w["break_i"] for w in W.find_wedges(spot,tf)}
            for L in conf:
                i=L["break_i"]
                if not i or A[i]<=0: continue
                rng=max(h[i]-l[i],1e-9)
                rows.append(dict(day=pd.Timestamp(arr[i,0],unit="s").normalize(),
                    spot=spot,tf=tf,kind=L["kind"],type=L["type"],
                    level=W.line_at(L,arr,i), n_rej=L["n_rej"], wedge=i in wd,
                    age=(i-L["anchor"][0])*tf/1440.0 if L["type"]=="trendline" else np.nan,
                    barsize=rng/A[i]))
    return pd.DataFrame(rows)

def payoff_table():
    rows=[]
    for spot in ("BTC","ETH"):
        for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
            try: d=json.load(open(fp))
            except Exception: continue
            for r in d.get("rows",[]):
                if r.get("entryTs"):
                    rows.append((pd.Timestamp(r["entryTs"][:10]),spot,float(r["ratio"]),
                                 r.get("symbol",""),r.get("entryPrice",np.nan)))
    return pd.DataFrame(rows,columns=["day","spot","ratio","symbol","entry"])

def day_profile(B):
    g=B.groupby("day").agg(breaks=("kind","size"),oldest=("age","max"),
        wedges=("wedge","sum"),max_rej=("n_rej","max"),bar=("barsize","max"))
    return g

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--top",type=int); ap.add_argument("--reverse",action="store_true")
    ap.add_argument("--target",type=float,default=100); ap.add_argument("--day")
    a=ap.parse_args()
    B=break_table(); P=payoff_table(); G=day_profile(B)
    pay=P.groupby("day").agg(best=("ratio","max"),n=("ratio","size"))
    cal=pd.DataFrame(index=pd.date_range(min(G.index.min(),pay.index.min()),
                                          max(G.index.max(),pay.index.max()),freq="D"))
    cal=cal.join(G).join(pay).fillna({"breaks":0,"wedges":0,"best":0,"n":0})
    cal["best3"]=cal.best.rolling(4).max().shift(-3)

    if a.day:
        d=pd.Timestamp(a.day)
        print(f"=== {d.date()} ===")
        s=B[B.day==d].sort_values("age",ascending=False)
        print(f"  {len(s)} level(s) broke   oldest {s.age.max() if len(s) else 0:.0f}d   "
              f"wedges {int(s.wedge.sum()) if len(s) else 0}   biggest bar "
              f"{s.barsize.max() if len(s) else 0:.2f} ATR")
        for _,r in s.head(12).iterrows():
            print(f"    {r['spot']:<4}{r.tf:>6}m {r['kind']} {r.level:>11,.1f}  "
                  f"{r.n_rej} rej  {r.age if r.age==r.age else 0:>5.0f}d  "
                  f"{'WEDGE' if r.wedge else ''}")
        q=P[P.day==d].nlargest(6,"ratio")
        print(f"  option moves starting that day: {len(P[P.day==d])} >=10x, "
              f"best {P[P.day==d].ratio.max() if len(P[P.day==d]) else 0:,.0f}x")
        for _,r in q.iterrows():
            print(f"    {r.ratio:>9,.0f}x  {r.symbol}  entry {r.entry:.3f}")

    elif a.reverse:
        T=a.target
        hits=P[P.ratio>=T].groupby("day").agg(best=("ratio","max"),n=("ratio","size"))
        hits=hits.join(G)
        hits["breaks"]=hits.breaks.fillna(0); hits["wedges"]=hits.wedges.fillna(0)
        print(f"REVERSE SEARCH — every day a >={T:.0f}x option move BEGAN ({len(hits)} days)")
        print(f"What did the level system see that day?\n")
        cov=pd.Series({
          "a level broke":            (hits.breaks>0).mean(),
          "an OLD line (>=100d) broke":(hits.oldest>=100).mean(),
          "a WEDGE broke":            (hits.wedges>0).mean(),
          "a big bar (>=2 ATR)":      (hits.bar>=2).mean(),
          "NOTHING broke at all":     (hits.breaks==0).mean()})
        for k,v in cov.items(): print(f"    {k:<30}{100*v:>6.1f}% of paying days")
        base_any=(cal.breaks>0).mean(); base_old=(cal.oldest>=100).mean()
        print(f"\n  for comparison, across ALL days: a level broke on {100*base_any:.1f}%, "
              f"an old line on {100*base_old:.1f}%")
        print(f"\n  TOP 15 PAYING DAYS AND WHAT PRECEDED THEM")
        print(f"{'day':>12}{'best':>11}{'#hits':>7}{'breaks':>8}{'oldest':>8}{'wedge':>7}{'bar':>7}")
        for d,r in hits.nlargest(15,"best").iterrows():
            print(f"{str(d.date()):>12}{r.best:>10,.0f}x{int(r.n):>7}{int(r.breaks):>8}"
                  f"{0 if r.oldest!=r.oldest else r.oldest:>8.0f}{int(r.wedges):>7}"
                  f"{0 if r.bar!=r.bar else r.bar:>7.2f}")
    else:
        n=a.top or 25
        c=cal[cal.breaks>0].copy()
        c["score"]=c.oldest.fillna(0).rank(pct=True)+c.wedges.rank(pct=True)
        print(f"TOP {n} DAYS by (line age + wedge count), all history\n")
        print(f"{'day':>12}{'breaks':>8}{'oldest':>8}{'wedges':>8}{'maxrej':>8}"
              f"{'bar/ATR':>9}{'best 0-3d':>12}")
        for d,r in c.nlargest(n,"score").iterrows():
            mk=" <<<" if d in (pd.Timestamp("2026-08-17"),pd.Timestamp("2026-08-19")) else ""
            print(f"{str(d.date()):>12}{int(r.breaks):>8}{0 if r.oldest!=r.oldest else r.oldest:>8.0f}"
                  f"{int(r.wedges):>8}{0 if r.max_rej!=r.max_rej else r.max_rej:>8.0f}"
                  f"{0 if r.bar!=r.bar else r.bar:>9.2f}{r.best3:>11,.0f}x{mk}")
