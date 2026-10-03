"""Tejas (C1 p365): mode 1 "one side melts, other sideways" is ~60% of expiries (measured
59.6%, decay_modes.py), and "easily capital would be able to make at least 5x through
averaging" there. Two questions:
 1. Can the surviving (non-melting) side be told apart EARLY, by day 1-3 of the last week?
 2. Does averaging into it pay, net of cost?

Friday expiries with >= 7 days of life (MARK, 60m). Day 0 = 7 days before settlement, 12:00 UTC.
A 5%-OTM call and put are fixed at day 0. On day 1 the STRONGER side is whichever premium has
held up better since day 0 (no future information). Averaging: equal money on day 1, 2 and 3
closes (6, 5, 4 DTE). Exit when the side's high reaches 2x the average cost (his "2x, 3x"),
otherwise at the day-4 close (3 DTE, before the 2-3 DTE decay he warned about). A
hold-to-expiry variant is shown too. 8.26% round-trip cost on every buy. Controls: the
WEAKER side with the same rule, and a coin-flip side.
"""
import numpy as np, pandas as pd, os
from decay_modes import load, spot
COST = 0.0826
rows = []
for asset in ("BTC", "ETH"):
    sp = spot(asset)
    for e in sorted(os.listdir(f"data/candles/{asset}")):
        if e.startswith(".") or e < "2024-01-01" or pd.Timestamp(e).weekday() != 4: continue
        if pd.Timestamp(e) > pd.Timestamp.now() - pd.Timedelta(days=1): continue
        C, P = load(asset, e)
        if len(C) < 5 or len(P) < 5: continue
        settle = int(pd.Timestamp(e).timestamp()) + 43200; d0 = settle - 7*86400; S0 = sp.get(d0)
        if S0 is None: continue
        kc, kp = np.array(sorted(C)), np.array(sorted(P))
        sides = {}
        for nm, book, ks, sgn in (("C", C, kc, 1), ("P", P, kp, -1)):
            k = ks[np.abs(ks - S0*(1 + sgn*0.05)).argmin()]; ser = book[k]
            if d0 not in ser or ser[d0][1] <= 0: break
            sides[nm] = ser
        if len(sides) < 2: continue
        d = [d0 + i*86400 for i in range(5)]
        if not all(x in sides["C"] and x in sides["P"] for x in d): continue
        held = {nm: s[d[1]][1]/s[d0][1] for nm, s in sides.items()}
        strong = max(held, key=held.get); weak = min(held, key=held.get)
        def trade(nm, hold_to_expiry=False):
            s = sides[nm]; buys = [s[d[i]][1] for i in (1, 2, 3)]
            if min(buys) <= 0: return np.nan
            units = [1/b for b in buys]; avg = 3/sum(units)
            end = settle if hold_to_expiry else d[4]
            # exit at 2x avg once all three buys are in (from day 3 onward), else at the end close
            for t in sorted(x for x in s if d[3] < x <= end):
                if s[t][0] >= 2*avg: return 2*1 - 1 - COST          # whole position sold at 2x avg
            last = [x for x in sorted(s) if x <= end][-1]
            return s[last][1]*sum(units)/3 - 1 - COST
        fin = {nm: (lambda s: [s[x] for x in sorted(s)][-1][1]/s[d0][1])(s) for nm, s in sides.items()}
        mode = "melt+side" if min(fin.values()) <= 0.2 and max(fin.values()) > 0.2 else "other"
        rows.append(dict(asset=asset, expiry=e, strong=strong, mode=mode,
                         strong_survives=fin[strong] > fin[weak],
                         s_ret=trade(strong), w_ret=trade(weak), r_ret=trade(np.random.default_rng(len(rows)).choice(["C", "P"])),
                         s_exp=trade(strong, True), w_exp=trade(weak, True)))
R = pd.DataFrame(rows)
print(f"{len(R)} Friday expiries; mode 1 (one melts, other survives) {(R['mode']=='melt+side').mean():.0%}")
print(f"Q1: the side that held better on day 1 is the one still standing at expiry in {R.strong_survives.mean():.0%} of expiries"
      f" ({R[R['mode']=='melt+side'].strong_survives.mean():.0%} within mode-1 expiries)\n")
rng = np.random.default_rng(0)
def ci(x):
    x = x.dropna().to_numpy(); b = [rng.choice(x, len(x)).mean() for _ in range(4000)]
    return f"{x.mean():+.3f}  [{np.percentile(b,2.5):+.3f},{np.percentile(b,97.5):+.3f}]  win {np.mean(x>0):.0%}"
print("Q2: averaging day 1-3, exit 2x avg or at 3 DTE (per unit of total money, net of cost)")
print(f"   STRONGER side : {ci(R.s_ret)}")
print(f"   weaker side   : {ci(R.w_ret)}")
print(f"   coin-flip side: {ci(R.r_ret)}")
print("   same, held to expiry instead of exiting at 3 DTE:")
print(f"   STRONGER side : {ci(R.s_exp)}")
print(f"   weaker side   : {ci(R.w_exp)}")
R["yr"] = R.expiry.str[:4]
print("\n   stronger-side, exit at 3 DTE, by year:", R.groupby("yr").s_ret.mean().round(3).to_dict())
