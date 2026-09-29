#!/usr/bin/env python3
"""
wedge.py — converging wedges, and two corrections Tejas's Aug-17 reading forced.

THE STRUCTURE HE POINTS AT
Not a single line but a WEDGE: a confirmed descending resistance and a confirmed
rising (or flatter-falling) support, converging over months, broken close to an
expiry. His crypto case is Aug-2026; his equity precedent is ADANIENT on
19 May 2023, a week before the 25 May monthly expiry, which paid 1:100.

TWO FIXES THIS FORCED

1. PAYOFF WINDOW. The old test asked "did a 100x start ON the break day". His
   BTC sequence was break 17 Aug -> retest and hold 18 Aug -> run 19 Aug. Under
   the old window the 17th gets no credit and the 19th is attributed to whatever
   weaker line happened to break that day. The window is now days 0..N after the
   break, which is what a trader actually holds.

2. RETEST. A break whose next bars come back and TAG the broken line from above
   without closing back through is the classic hold. Measured separately, since
   67% of breaks are traps and this is the thing that supposedly sorts them.

Expiry proximity is taken from the real expiry dates present in
data/multibaggers, not from a weekday rule.
"""
import glob, json, os
import numpy as np, pandas as pd
import levels as LV

def active_lines(spot, tf):
    conf, arr = LV.all_levels(spot, tf)
    if arr is None: return [], None, None
    A = LV.atr(arr[:,2], arr[:,3], arr[:,4])
    return conf, arr, A

def line_at(L, arr, i):
    if L["type"]=="horizontal": return L["price"]
    i1,i2=L["anchor"]; ext=arr[:,2] if L["kind"]=="R" else arr[:,3]
    return ext[i2]+L["slope"]*(i-i2)

def expiries(spot):
    out=set()
    for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
        out.add(pd.Timestamp(os.path.basename(fp)[:-5]))
    return sorted(out)

def find_wedges(spot, tf, min_overlap=40):
    """A wedge at the break bar: a confirmed R line and a confirmed S line, both
    live, converging, and overlapping for at least min_overlap bars."""
    conf, arr, A = active_lines(spot, tf)
    if arr is None: return []
    R=[L for L in conf if L["kind"]=="R" and L["type"]=="trendline"]
    S=[L for L in conf if L["kind"]=="S" and L["type"]=="trendline"]
    out=[]
    # BOTH DIRECTIONS. The original looped only over R-line breaks, so every
    # wedge result up to 2026-09-26 covered UPWARD breaks only and the downward
    # half of the population was invisible.
    for brk_side, others, dirn in (("R", S, +1), ("S", R, -1)):
        prim = R if brk_side=="R" else S
        for p in prim:
            if not p["break_i"]: continue
            bi=p["break_i"]
            for q in others:
                lo=max(p["confirmed_i"], q["confirmed_i"])
                hi=min(bi, q["break_i"] if q["break_i"] else len(arr)-1)
                if hi-lo < min_overlap: continue
                r_,s_ = (p,q) if brk_side=="R" else (q,p)
                gap_lo=line_at(r_,arr,lo)-line_at(s_,arr,lo)
                gap_hi=line_at(r_,arr,bi)-line_at(s_,arr,bi)
                if not (gap_lo>0 and gap_hi>0 and gap_hi<gap_lo*0.8): continue
                # gap_lo/gap_hi/span are additive: they let apex.py derive how
                # many bars remained to the apex without re-deriving the lines.
                out.append(dict(spot=spot,tf=tf,break_i=bi,break_ts=p["break_ts"],
                    dirn=dirn,
                    n_rej_R=r_["n_rej"], n_rej_S=s_["n_rej"],
                    overlap_bars=hi-lo, squeeze=gap_hi/gap_lo,
                    gap_lo=gap_lo, gap_hi=gap_hi, span=bi-lo,
                    width_atr=gap_hi/A[bi] if A[bi]>0 else np.nan))
    # one wedge per break bar, the longest-overlapping
    best={}
    for w in out:
        k=w["break_i"]
        if k not in best or w["overlap_bars"]>best[k]["overlap_bars"]: best[k]=w
    return list(best.values())

def daily_best(spot):
    rows=[]
    for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
        try: d=json.load(open(fp))
        except Exception: continue
        for r in d.get("rows",[]):
            if r.get("entryTs"): rows.append((r["entryTs"][:10], float(r["ratio"])))
    x=pd.DataFrame(rows,columns=["day","ratio"])
    g=x.groupby("day").agg(best=("ratio","max"), n100=("ratio",lambda s:(s>=100).sum()))
    g.index=pd.to_datetime(g.index); return g

if __name__=="__main__":
    for spot in ("BTC","ETH"):
        g=daily_best(spot); exp=expiries(spot)
        cal=pd.DataFrame(index=pd.date_range(g.index.min(),g.index.max(),freq="D")).join(g).fillna(0)
        # rolling window: best multiple starting within N days of a given day
        for N in (0,3):
            cal[f"best{N}"]=cal.best.rolling(N+1).max().shift(-N)
            cal[f"n100_{N}"]=cal.n100.rolling(N+1).max().shift(-N)
        allb=[]; wed=[]
        for tf in (1440,360,240):
            conf,arr,A=active_lines(spot,tf)
            for L in conf:
                if L["break_ts"]: allb.append(pd.Timestamp(L["break_ts"],unit="s").normalize())
            for w in find_wedges(spot,tf): wed.append(pd.Timestamp(w["break_ts"],unit="s").normalize())
        allb=pd.DatetimeIndex(sorted(set(allb))); wed=pd.DatetimeIndex(sorted(set(wed)))
        days_to_exp=pd.Series([min([ (e-d).days for e in exp if (e-d).days>=0 ] or [999])
                               for d in cal.index], index=cal.index)
        print(f"=== {spot} === {len(allb)} break days, {len(wed)} of them WEDGE breaks")
        for N in (0,3):
            base=(cal[f"n100_{N}"]>0).mean()
            mb=cal.index.isin(allb); mw=cal.index.isin(wed)
            print(f"  window 0..{N} days after the break:")
            print(f"    base                     P(100x) {100*base:>5.1f}%   median best "
                  f"{cal[f'best{N}'].median():>6.1f}x")
            for lbl,m in (("any confirmed break",mb),("WEDGE break",mw),
                          ("wedge break, <=10d to expiry",mw&(days_to_exp<=10).to_numpy())):
                if m.sum()<10: print(f"    {lbl:<25}(too few: {m.sum()})"); continue
                s=cal[m]
                print(f"    {lbl:<25}P(100x) {100*(s[f'n100_{N}']>0).mean():>5.1f}%   "
                      f"median best {s[f'best{N}'].median():>6.1f}x   n={m.sum()}")
        print()
