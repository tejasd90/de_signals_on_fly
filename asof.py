#!/usr/bin/env python3
"""
asof.py — replay the live dashboard at a past date, using ONLY bars that had
closed by then. Answers "what would I actually have seen that morning".
"""
import numpy as np, pandas as pd
import levels as LV, wedge as W

_real_load = LV.load_tf
def freeze(cutoff):
    cut = pd.Timestamp(cutoff).timestamp()
    def loader(spot, tf):
        a = _real_load(spot, tf)
        if a is None: return None
        a = a[a[:,0] + tf*60 <= cut]        # bar must have CLOSED by the cutoff
        return a if len(a) > 250 else None
    LV.load_tf = loader
def unfreeze(): LV.load_tf = _real_load

def snapshot(cutoff, day, near_atr=4.0):
    freeze(cutoff)
    try:
        live=[]; broke_today=[]; wedges=[]
        cut=pd.Timestamp(day).normalize()   # the DAY in question, not the cutoff
        for spot in ("BTC","ETH"):
            for tf in (1440,360,240):
                conf,arr = LV.all_levels(spot,tf)
                if arr is None: continue
                A=LV.atr(arr[:,2],arr[:,3],arr[:,4]); n=len(arr); last=arr[-1,4]
                wd_bars={w["break_i"] for w in W.find_wedges(spot,tf)}
                for L in conf:
                    lv=W.line_at(L,arr,n-1)
                    if lv<=0: continue
                    if L["break_i"]:
                        bd=pd.Timestamp(L["break_ts"],unit="s").normalize()
                        if bd==cut:
                            broke_today.append(dict(spot=spot,tf=tf,kind=L["kind"],
                                level=W.line_at(L,arr,L["break_i"]),n_rej=L["n_rej"],
                                age=(L["break_i"]-L["anchor"][0])*tf/1440 if L["type"]=="trendline" else np.nan,
                                wedge=L["break_i"] in wd_bars))
                    else:
                        live.append(dict(spot=spot,tf=tf,kind=L["kind"],level=lv,last=last,
                            pct=100*(lv/last-1),atr=abs(last-lv)/A[-1] if A[-1]>0 else np.nan,
                            n_rej=L["n_rej"]))
        return pd.DataFrame(live), pd.DataFrame(broke_today)
    finally:
        unfreeze()

if __name__=="__main__":
    import sys
    for day in sys.argv[1:] or ["2026-08-16","2026-08-17","2026-08-18"]:
        L,B = snapshot(pd.Timestamp(day)+pd.Timedelta(days=1), day)  # after that day's close
        print("="*86)
        print(f"DASHBOARD AS IT WOULD HAVE READ AFTER THE {day} CLOSE")
        print("="*86)
        if len(B):
            B=B.sort_values("age",ascending=False)
            print(f"\n  *** BROKE TODAY — {len(B)} level(s) ***")
            print(f"  {'spot':<5}{'tf':>6}{'dir':>4}{'level':>11}{'rej':>5}{'age(d)':>8}{'WEDGE':>7}")
            for _,r in B.head(12).iterrows():
                print(f"  {r['spot']:<5}{r.tf:>6}{r['kind']:>4}{r.level:>11,.1f}{r.n_rej:>5}"
                      f"{r.age:>8.0f}{'YES' if r.wedge else '-':>7}")
            nw=int(B.wedge.sum())
            print(f"\n  -> {nw} of these were WEDGE breaks"
                  f"{'  <-- the high-conviction flag' if nw else ''}")
        else:
            print("\n  nothing broke today")
        if len(L):
            near=L[L.atr<=4.0].sort_values("atr")
            print(f"\n  IN PLAY (within 4 ATR): {len(near)}")
            for _,r in near.head(8).iterrows():
                print(f"    {r['spot']} {r.tf:>5}m {r['kind']} at {r.level:>10,.1f}  "
                      f"{r.pct:+6.2f}% away ({r.atr:.1f} ATR), rejected {r.n_rej}x")
        print()
