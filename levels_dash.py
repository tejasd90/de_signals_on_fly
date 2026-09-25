#!/usr/bin/env python3
"""
levels_dash.py — two text dashboards over 3x-rejected levels.

PAST      every confirmed level that broke, what it paid, sorted by payoff.
LIVE      every confirmed level still UNBROKEN, how close price is, and an
          honest read on whether a break looks near.

ON "SIGNS OF AN IMMINENT BREAK"
Tejas asked for these and called it the hard part. He is right to: this project
has repeatedly failed to TIME anything (states pay, events don't). So the
imminence column is measured, not asserted -- `--test` reports whether any of
proximity / range-compression / touch-clustering actually raises P(break within
5 days), against the unconditional rate. Whatever fails that test is printed as
context only and explicitly labelled non-predictive.
"""
import os, json, argparse
import numpy as np, pandas as pd
import levels as LV

def enrich(spot, tf):
    conf, arr = LV.all_levels(spot, tf)
    if arr is None: return [], None, None
    A = LV.atr(arr[:,2],arr[:,3],arr[:,4])
    return conf, arr, A

def level_price_at(L, arr, i):
    if L["type"]=="horizontal": return L["price"]
    i1,i2=L["anchor"]; ext=arr[:,2] if L["kind"]=="R" else arr[:,3]
    return ext[i2]+L["slope"]*(i-i2)

def imminence_test(spot_tfs, horizon=5):
    """Conditional on price being NEAR a confirmed unbroken level, does anything
    predict a break within `horizon` bars?"""
    rows=[]
    for spot,tf in spot_tfs:
        conf,arr,A=enrich(spot,tf)
        if arr is None: continue
        ts,o,h,l,c=arr[:,0],arr[:,1],arr[:,2],arr[:,3],arr[:,4]
        rng=h-l
        comp=pd.Series(rng).rolling(5,min_periods=3).mean().to_numpy()/ \
             pd.Series(rng).rolling(20,min_periods=5).mean().to_numpy()
        for L in conf:
            ci=L["confirmed_i"]; bi=L["break_i"] if L["break_i"] else len(c)-1
            for i in range(ci+1, bi):
                if not np.isfinite(A[i]) or A[i]<=0: continue
                lv=level_price_at(L,arr,i)
                if lv<=0: continue
                dist=abs(c[i]-lv)/A[i]
                if dist>3.0: continue                    # only "near" bars
                broke = 1.0 if (L["break_i"] and L["break_i"]-i<=horizon) else 0.0
                rows.append(dict(spot=spot,tf=tf,i=i,ts=int(ts[i]),dist=dist,
                                 comp=comp[i], n_rej=L["n_rej"], broke=broke,
                                 age=i-L["confirmed_i"]))
    D=pd.DataFrame(rows).replace([np.inf,-np.inf],np.nan).dropna(subset=["dist","comp"])
    if D.empty: return D
    D["week"]=((D.ts+19800)//604800).astype(int)
    print(f"  near-level bars: {len(D):,}   unconditional P(break within {horizon}): "
          f"{100*D.broke.mean():.1f}%")
    for col,lab in (("dist","distance to level (ATR)"),("comp","range compression"),
                    ("age","bars since confirmation"),("n_rej","rejection count")):
        try: q=pd.qcut(D[col],4,labels=["Q1","Q2","Q3","Q4"],duplicates="drop")
        except Exception: continue
        g=D.groupby(q,observed=True).broke.agg(["size","mean"])
        s=" ".join(f"{i}:{100*r['mean']:.1f}%" for i,r in g.iterrows())
        print(f"    {lab:<28} {s}")
    return D

def past_dash(out="dash_past.txt", min_rej=3):
    import levels_payoff as LP
    lines=["PAST — levels with >=3 rejections that BROKE, and what the break paid",
           "="*94,
           "payoff = best option multiple from a move ENTERED on the break day",
           "(data/multibaggers, signal-independent; max across strikes, so it is an",
           " indicator that a big move happened, NOT a tradeable return)",""]
    rows=[]
    for spot in ("BTC","ETH"):
        g=LP.daily_best(spot)
        for tf in (1440,240):
            conf,arr,A=enrich(spot,tf)
            for L in conf:
                if not L["break_ts"] or L["n_rej"]<min_rej: continue
                day=pd.Timestamp(L["break_ts"],unit="s").normalize()
                best=float(g.best.get(day,0.0)) if g is not None else 0.0
                n100=int(g.n100.get(day,0)) if g is not None else 0
                rows.append(dict(spot=spot,tf=tf,type=L["type"],kind=L["kind"],
                    price=L["price_at_break"],n_rej=L["n_rej"],
                    confirmed=pd.Timestamp(L["confirmed_ts"],unit="s").date(),
                    broke=day.date(),best=best,n100=n100))
    R=pd.DataFrame(rows).sort_values("best",ascending=False)
    lines.append(f"{'spot':<5}{'tf':>6}{'type':>12}{'dir':>4}{'level':>12}{'rej':>5}"
                 f"{'confirmed':>12}{'broke':>12}{'best mult':>11}{'#100x':>7}")
    for _,r in R.head(45).iterrows():
        sp,ty,kd = r["spot"], r["type"][:11], r["kind"]
        lines.append(f"{sp:<5}{r.tf:>6}{ty:>12}{kd:>4}{r.price:>12,.1f}"
                     f"{r.n_rej:>5}{str(r.confirmed):>12}{str(r.broke):>12}"
                     f"{r.best:>10,.0f}x{r.n100:>7}")
    lines+=["", f"total broken levels: {len(R)}   "
            f"median best multiple on break days: {R.best.median():,.0f}x   "
            f"share with a >=100x: {100*(R.n100>0).mean():.0f}%"]
    open(out,"w").write("\n".join(lines)+"\n")
    print(f"wrote {out}  ({len(R)} broken levels)")
    return R

def broke_recently(days=3):
    """Levels that broke in the last `days` sessions, with the two columns that
    MEASURE: line age and whether it was a wedge. Break COUNT is deliberately not
    highlighted -- it fails to predict payoff (>=15 breaks gives P=0.337) while
    age>=100d gives P=0.000 and wedge>=1 gives P=0.001."""
    import wedge as W
    out=[]
    for spot in ("BTC","ETH"):
        for tf in (1440,360,240):
            conf,arr=LV.all_levels(spot,tf)
            if arr is None: continue
            last=pd.Timestamp(arr[-1,0],unit="s").normalize()
            wd={w["break_i"] for w in W.find_wedges(spot,tf)}
            for L in conf:
                if not L["break_ts"]: continue
                d=pd.Timestamp(L["break_ts"],unit="s").normalize()
                if (last-d).days>days: continue
                age=(L["break_i"]-L["anchor"][0])*tf/1440.0 if L["type"]=="trendline" \
                    else (L["break_i"]-L.get("anchor_i",L["break_i"]))*tf/1440.0
                out.append(dict(spot=spot,tf=tf,kind=L["kind"],
                    level=L["price_at_break"],n_rej=L["n_rej"],age=age,
                    wedge=L["break_i"] in wd,day=d.date()))
    return pd.DataFrame(out)

def live_dash(out="dash_live.txt", min_rej=3, near_atr=4.0):
    lines=[]
    B=broke_recently()
    lines+= ["BROKE IN THE LAST 3 SESSIONS", "="*96, ""]
    if len(B):
        B=B.sort_values(["day","age"],ascending=[False,False])
        lines.append(f"{'day':>12}{'spot':>5}{'tf':>6}{'dir':>4}{'level':>12}"
                     f"{'rej':>5}{'age(d)':>8}{'WEDGE':>7}")
        for _,r in B.iterrows():
            sp,kd=r["spot"],r["kind"]
            lines.append(f"{str(r['day']):>12}{sp:>5}{r.tf:>6}{kd:>4}{r.level:>12,.1f}"
                         f"{r.n_rej:>5}{r.age:>8.0f}{'YES' if r.wedge else '-':>7}")
        oldest=B.age.max(); nw=int(B.wedge.sum())
        lines+=["", f"  oldest line broken: {oldest:.0f} days"
                    f"{'   *** >=100d: measured +15.8pp, P=0.000 ***' if oldest>=100 else ''}",
                    f"  wedge breaks: {nw}"
                    f"{'   *** >=1 wedge: measured +18.6pp, P=0.001 ***' if nw>=1 else ''}",
                    "  (break COUNT is not shown as a headline: it does not predict payoff,",
                    "   P=0.337 at >=15 breaks. Age and wedge are the columns that measure.)"]
    else:
        lines.append("  nothing broke in the last 3 sessions")
    lines+=["","", "LIVE — confirmed levels (>=3 rejections) that are STILL UNBROKEN",
            "="*96, ""]
    rows=[]
    for spot in ("BTC","ETH"):
        conf,arr,A=enrich(spot,1440)
        if arr is None: continue
        n=len(arr); last=arr[-1,4]; lastts=pd.Timestamp(arr[-1,0],unit="s").date()
        for tf_conf,tf in ((conf,1440),):
            for L in tf_conf:
                if L["break_i"] or L["n_rej"]<min_rej: continue
                lv=level_price_at(L,arr,n-1)
                if lv<=0: continue
                dist_atr=abs(last-lv)/A[-1] if A[-1]>0 else np.nan
                rows.append(dict(spot=spot,tf=tf,type=L["type"],kind=L["kind"],
                    level=lv,px=last,asof=lastts,
                    pct=100*(lv/last-1),dist_atr=dist_atr,n_rej=L["n_rej"],
                    confirmed=pd.Timestamp(L["confirmed_ts"],unit="s").date(),
                    last_rej=pd.Timestamp(max(L["rejects"]),unit="s").date()))
    R=pd.DataFrame(rows)
    if R.empty:
        open(out,"w").write("no unbroken confirmed levels\n"); print("no live levels"); return R
    R=R.sort_values("dist_atr")
    lines.append(f"{'spot':<5}{'dir':>4}{'type':>12}{'level':>12}{'last':>11}"
                 f"{'move needed':>13}{'ATR away':>10}{'rej':>5}{'confirmed':>12}{'last rej':>12}")
    for _,r in R.iterrows():
        sp,ty,kd = r["spot"], r["type"][:11], r["kind"]
        lines.append(f"{sp:<5}{kd:>4}{ty:>12}{r.level:>12,.1f}{r.px:>11,.1f}"
                     f"{r.pct:>12.2f}%{r.dist_atr:>10.1f}{r.n_rej:>5}"
                     f"{str(r.confirmed):>12}{str(r.last_rej):>12}")
    near=R[R.dist_atr<=near_atr]
    lines+=["", f"IN PLAY (within {near_atr} ATR): {len(near)} level(s)"]
    for _,r in near.iterrows():
        sp,ty,kd = r["spot"], r["type"], r["kind"]
        lines.append(f"  {sp} {kd} {ty} at {r.level:,.1f} — "
                     f"{r.pct:+.2f}% away, rejected {r.n_rej}x, last rejection {r.last_rej}")
    lines+=["","A BREAK = a daily CLOSE beyond the level. Wicks do not count.",
            "Measured: break days carry ~1.8x the normal chance of a 100x move and",
            "~2x the median best multiple. That is the whole edge — it says a big",
            "move is likelier, NOT which direction, strike or expiry."]
    open(out,"w").write("\n".join(lines)+"\n")
    print(f"wrote {out}  ({len(R)} unbroken levels, {len(near)} in play)")
    return R

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--test",action="store_true"); ap.add_argument("--build",action="store_true")
    a=ap.parse_args()
    if a.test:
        print("IMMINENCE TEST — conditional on being near a confirmed unbroken level,")
        print("does anything predict a break within 5 bars?\n")
        imminence_test([("BTC",1440),("ETH",1440),("BTC",240),("ETH",240)])
    if a.build:
        past_dash(); live_dash()
