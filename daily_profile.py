#!/usr/bin/env python3
"""
daily_profile.py — a break profile for EVERY day in history, so "was 17 Aug odd?"
has a measured answer instead of an impression.

WHAT A DAY'S PROFILE IS
  n_breaks    how many confirmed levels gave way that day, across BTC/ETH and
              1440/360/240m
  max_age     age in days of the OLDEST line broken — the structural weight
  n_wedges    how many of the breaks were wedge breaks (the subset that carries
              the measured edge)
  agree       share of the day's breaks pointing the same way. A day where ten
              resistance levels break is a different animal from one where five
              break up and five break down.
  max_rej     the most-defended level that broke

CAUSALITY NOTE
Break attribution is causal by construction: a level's anchors precede its
touches, which precede its break. The one thing full-history detection gives
that a live run would not is swing confirmation within k bars of the break date,
so a handful of anchors very close to a break would be invisible in real time.
That makes this profile very slightly optimistic, never the reverse.
"""
import glob, json, os
import numpy as np, pandas as pd
import levels as LV, wedge as W

def build():
    rows=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,360,240):
            conf,arr = LV.all_levels(spot,tf)
            if arr is None: continue
            wd={w["break_i"] for w in W.find_wedges(spot,tf)}
            for L in conf:
                if not L["break_ts"]: continue
                age=(L["break_i"]-L["anchor"][0])*tf/1440.0 if L["type"]=="trendline" \
                    else (L["break_i"]-L.get("anchor_i",L["break_i"]))*tf/1440.0
                rows.append(dict(spot=spot, tf=tf, kind=L["kind"], n_rej=L["n_rej"],
                    age=age, wedge=L["break_i"] in wd,
                    day=pd.Timestamp(L["break_ts"],unit="s").normalize()))
    B=pd.DataFrame(rows)
    g=B.groupby("day").agg(n_breaks=("kind","size"), max_age=("age","max"),
        n_wedges=("wedge","sum"), max_rej=("n_rej","max"),
        n_spots=("spot","nunique"))
    agree=B.groupby("day")["kind"].apply(lambda s: max((s=="R").mean(),(s=="S").mean()))
    g["agree"]=agree
    return B,g

def payoff(spot):
    rows=[]
    for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
        try: d=json.load(open(fp))
        except Exception: continue
        for r in d.get("rows",[]):
            if r.get("entryTs"): rows.append((r["entryTs"][:10],float(r["ratio"])))
    x=pd.DataFrame(rows,columns=["day","ratio"])
    g=x.groupby("day").agg(best=("ratio","max"),n100=("ratio",lambda s:(s>=100).sum()))
    g.index=pd.to_datetime(g.index); return g

if __name__=="__main__":
    B,G=build()
    pay=(payoff("BTC").add(payoff("ETH"),fill_value=0))
    cal=pd.DataFrame(index=pd.date_range(min(G.index.min(),pay.index.min()),
                                         max(G.index.max(),pay.index.max()),freq="D"))
    cal=cal.join(G).join(pay[["best","n100"]]).fillna(0)
    cal["best3"]=cal.best.rolling(4).max().shift(-3)
    cal["n100_3"]=cal.n100.rolling(4).max().shift(-3)
    # PHANTOM-ZERO GUARD. multibaggers lags the candle data, so the most recent
    # days have best=0 because nothing was computed, not because nothing moved.
    # Left in, they count as breaks that paid nothing and dilute every lift.
    last = cal[cal.best>0].index.max()
    n_cut = int((cal.index>last).sum())
    if n_cut:
        print(f"  trimming {n_cut} tail days with no multibagger data "
              f"(after {last.date()}) — they would score as false zeroes")
        cal = cal[cal.index<=last]
    cal.to_csv("daily_break_profile.csv")
    print(f"wrote daily_break_profile.csv — {len(cal):,} days, "
          f"{int((cal.n_breaks>0).sum()):,} with at least one break\n")
    d17=pd.Timestamp("2026-08-17")
    print("WHERE DOES 17 AUG 2026 SIT?  (rank 1 = most extreme of all days)\n")
    print(f"{'metric':<14}{'17 Aug':>9}{'median':>9}{'p90':>8}{'p99':>8}{'rank':>14}{'percentile':>12}")
    for c,lab in (("n_breaks","breaks"),("max_age","oldest line"),("n_wedges","wedges"),
                  ("max_rej","most-rejected"),("agree","one-directional")):
        v=cal.loc[d17,c]; s=cal[c]
        rank=int((s>v).sum())+1
        print(f"{lab:<14}{v:>9.0f}{s.median():>9.1f}{s.quantile(.9):>8.1f}{s.quantile(.99):>8.1f}"
              f"{f'{rank} of {len(s)}':>14}{100*(s<v).mean():>11.1f}%")
    print("\nTOP 12 DAYS BY BREAK COUNT (all history):")
    print(f"{'day':>12}{'breaks':>8}{'oldest':>8}{'wedges':>8}{'agree':>7}{'best 0-3d':>11}")
    for d,r in cal.nlargest(12,"n_breaks").iterrows():
        mark=" <<<" if d==d17 else ""
        print(f"{str(d.date()):>12}{r.n_breaks:>8.0f}{r.max_age:>8.0f}{r.n_wedges:>8.0f}"
              f"{r.agree:>7.2f}{r.best3:>10,.0f}x{mark}")
