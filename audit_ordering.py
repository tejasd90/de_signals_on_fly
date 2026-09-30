"""Within a break day, does the BREAK come before the 100x ENTRY?

audit_sameday showed old-line and wedge effects are 60-75% same-day: +16.8pp and
+20.0pp on the day, falling to +6.7pp and +4.8pp shifted one day forward. Same-day
is still tradeable IF the break precedes the payoff -- you see the break, you buy.
If the break lands AFTER the option was already running, the effect is description,
not signal, and no amount of statistics rescues it.

Both timestamps exist: break_ts on the level, entryTs on the multibagger row.
"""
import json, glob
import numpy as np, pandas as pd
import levels as LV, wedge as W

def breaks(spot):
    out = []
    for tf in (1440, 360, 240):
        conf, arr = LV.all_levels(spot, tf)
        if arr is None: continue
        wd = {w["break_i"]: w for w in W.find_wedges(spot, tf)}
        for L in conf:
            i = L["break_i"]
            if not i: continue
            ts = int(arr[i, 0])
            age = (i - L["anchor"][0]) * tf / 1440.0 if L["type"] == "trendline" else np.nan
            out.append(dict(spot=spot, tf=tf, ts=ts,
                            day=pd.Timestamp(ts, unit="s").normalize(),
                            age=age, wedge=i in wd))
    return pd.DataFrame(out)

def entries(spot):
    rows = []
    for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
        try: d = json.load(open(fp))
        except Exception: continue
        for r in d.get("rows", []):
            if r.get("entryTs") and float(r["ratio"]) >= 100:
                t = pd.Timestamp(r["entryTs"])
                rows.append(dict(spot=spot, ets=int(t.timestamp()),
                                 day=t.tz_localize(None).normalize(), ratio=float(r["ratio"])))
    return pd.DataFrame(rows)

allr = []
for spot in ("BTC", "ETH"):
    B, E = breaks(spot), entries(spot)
    if B.empty or E.empty: continue
    # earliest break of each kind on a day vs earliest 100x entry that day
    for lab, sub in (("any break", B), ("old line >=100d", B[B.age >= 100]), ("wedge", B[B.wedge])):
        if sub.empty: continue
        g = sub.groupby("day").ts.min().rename("brk")
        e = E.groupby("day").ets.min().rename("ent")
        m = pd.concat([g, e], axis=1).dropna()
        if len(m) < 15: continue
        before = (m.brk < m.ent).mean()
        lead_h = ((m.ent - m.brk) / 3600.0)
        allr.append((spot, lab, len(m), before, lead_h.median()))

print(f"{'spot':<6}{'feature':<18}{'days':>6}{'break BEFORE entry':>21}{'median lead (h)':>18}")
for spot, lab, n, bef, med in allr:
    print(f"{spot:<6}{lab:<18}{n:>6}{bef*100:>20.1f}%{med:>18.1f}")
print("\n50% would mean the break is no more likely to precede the payoff than follow it.")
