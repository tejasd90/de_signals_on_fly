"""
Does a wedge that breaks AT THE APEX pay more than one that breaks wide?

His BankNifty weekly: a descending line off the Sep-2024 and Feb-2026 highs and a
rising line off the Oct-2025 and Apr-2026 lows, converging near 57,500 around
Sep 2026 -- and price resolved DOWN essentially at the crossing, to 53,890. His
words: "patternish behaviour plus some significant price action to hold on to."

wedge.py already carries the quantity that decides this: width_atr, the gap
between the two lines at the break bar measured in ATR. Small width = the lines
had nearly met, i.e. a break at the apex. Large width = a break with the wedge
still wide open. Adding gap_lo/gap_hi/span lets us also express it as BARS TO
APEX, which is scale-free.

This is a conditioner on an already-surviving result (wedge breaks, +24.6pp up /
+33.8pp down), so it is a second look at the same population -- treat P values
accordingly and check the sample size before believing any split.
"""
import json, glob
import numpy as np, pandas as pd
from wedge import active_lines, find_wedges, daily_best, expiries

def build(spot):
    g = daily_best(spot)
    cal = pd.DataFrame(index=pd.date_range(g.index.min(), g.index.max(), freq="D")).join(g).fillna(0)
    cal["best0"] = cal.best
    cal["n100_0"] = cal.n100
    W = []
    for tf in (1440, 360, 240):
        for w in find_wedges(spot, tf):
            span, gl, gh = w["span"], w["gap_lo"], w["gap_hi"]
            rate = (gl - gh) / span if span > 0 else np.nan          # gap closed per bar
            b2a = gh / rate if (rate and rate > 0) else np.nan       # bars still to apex
            W.append(dict(day=pd.Timestamp(w["break_ts"], unit="s").normalize(),
                          tf=tf, dirn=w["dirn"], width_atr=w["width_atr"],
                          squeeze=w["squeeze"], bars_to_apex=b2a,
                          overlap=w["overlap_bars"]))
    return cal, pd.DataFrame(W)

def boot_diff(cal, daysA, daysB, n=4000, seed=17):
    """Weekly block bootstrap on P(100x) difference between two day sets."""
    rng = np.random.default_rng(seed)
    a = cal.loc[cal.index.isin(daysA), "n100_0"] > 0
    b = cal.loc[cal.index.isin(daysB), "n100_0"] > 0
    if len(a) < 8 or len(b) < 8: return np.nan, np.nan, np.nan
    wa = pd.Index(daysA).to_period("W"); wb = pd.Index(daysB).to_period("W")
    ua, ub = wa.unique(), wb.unique()
    d = []
    for _ in range(n):
        sa = np.concatenate([a.values[wa == u] for u in rng.choice(ua, len(ua), True)])
        sb = np.concatenate([b.values[wb == u] for u in rng.choice(ub, len(ub), True)])
        if len(sa) and len(sb): d.append(sa.mean() - sb.mean())
    d = np.array(d)
    return a.mean(), b.mean(), (d > 0).mean()

if __name__ == "__main__":
    for spot in ("BTC", "ETH"):
        cal, W = build(spot)
        if W.empty: print(f"{spot}: no wedges"); continue
        W = W.dropna(subset=["width_atr"])
        base = (cal.n100_0 > 0).mean()
        print(f"\n=== {spot} ===  {len(W)} wedges   base P(100x) {100*base:.1f}%")
        for dlabel, dsel in (("ALL", W.index == W.index), ("UP breaks", W.dirn > 0), ("DOWN breaks", W.dirn < 0)):
            sub = W[dsel]
            if len(sub) < 20: print(f"  {dlabel}: too few ({len(sub)})"); continue
            q = sub.width_atr.quantile([1/3, 2/3]).values
            narrow = sub[sub.width_atr <= q[0]].day.unique()
            wide   = sub[sub.width_atr >= q[1]].day.unique()
            pa, pb, p = boot_diff(cal, narrow, wide)
            print(f"  {dlabel:<12} n={len(sub):>3}   "
                  f"AT-APEX (narrowest 1/3, n={len(narrow)}) P(100x) {100*pa:5.1f}%   "
                  f"WIDE (widest 1/3, n={len(wide)}) {100*pb:5.1f}%   "
                  f"diff {100*(pa-pb):+5.1f}pp   P(diff>0) {p:.3f}")
            # scale-free cross-check
            # TERCILES, matching the width_atr split above. The first version used
            # a median split here, which compared middling wedges to middling ones
            # and is not a like-for-like contrast with the tercile extremes.
            s2 = sub.dropna(subset=["bars_to_apex"])
            if len(s2) >= 20:
                qq = s2.bars_to_apex.quantile([1/3, 2/3]).values
                m = qq[0]
                na = s2[s2.bars_to_apex <= qq[0]].day.unique()
                fa = s2[s2.bars_to_apex >= qq[1]].day.unique()
                pa2, pb2, p2 = boot_diff(cal, na, fa, seed=23)
                print(f"  {'':<12}       bars-to-apex: near (<= {m:.0f}) {100*pa2:5.1f}%  "
                      f"far {100*pb2:5.1f}%   diff {100*(pa2-pb2):+5.1f}pp   P {p2:.3f}")
