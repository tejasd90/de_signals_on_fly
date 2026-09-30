"""Funding: the one cost the cross-sectional book never modelled.

The book's return is 117% short leg -- it is short high-volatility alts. For a
short, funding is not automatically a cost: when the rate is positive, longs pay
shorts, and hot alts usually carry positive funding. So this could be a TAILWIND.
It has never been measured here, and a plan cannot quote +59%/yr without knowing.

Units are unverified (docs note many symbols clamp at 0.01), so the magnitude is
reported under both plausible readings rather than asserted. The SIGN and the
relative size are the decision-relevant parts and those are robust to the units.

Convention assumed: rate > 0 means longs pay shorts. Weight W > 0 is long, so
funding P&L = -W * rate.
"""
import glob, os
import numpy as np, pandas as pd
from xsec2 import load, run, FEE

Pd, Vd, dead = load(include_dead=True)
net, turn, W = run(Pd, Vd, reb=5, hedge=True)

# daily funding accrual per symbol
acc = {}
for fp in glob.glob("data/funding/*.parquet"):
    sym = os.path.basename(fp)[:-8]
    if sym not in W.columns: continue
    d = pd.read_parquet(fp)
    d["day"] = (d.ts // 86400).astype(int)
    acc[sym] = d.groupby("day")["rate"].sum()      # summed over the day
F = pd.DataFrame(acc).reindex(index=W.index, columns=W.columns)
print(f"funding coverage: {F.notna().any().sum()} of {W.shape[1]} names, "
      f"{100*F.notna().mean().mean():.0f}% of name-days\n")

fund_raw = (-W.shift(1) * F.fillna(0)).sum(axis=1)     # per day, in raw rate units
longs  = (-W.clip(lower=0).shift(1) * F.fillna(0)).sum(axis=1)
shorts = (-W.clip(upper=0).shift(1) * F.fillna(0)).sum(axis=1)

print("Funding P&L in RAW rate units (sign is what matters):")
print(f"  total  mean/day {fund_raw.mean():+.6f}   -> x365 = {fund_raw.mean()*365:+.4f}")
print(f"  long leg  {longs.mean()*365:+.4f}      short leg  {shorts.mean()*365:+.4f}")
print(f"  share of days positive: {100*(fund_raw>0).mean():.1f}%\n")

base = net.mean()*365
print(f"price-only return: {100*base:+.1f}%/yr\n")
print(f"{'units assumption':<34}{'funding/yr':>12}{'total/yr':>11}{'Sharpe':>9}")
for lbl, scale in (("rate is already a fraction", 1.0),
                   ("rate is in PERCENT (/100)", 0.01),
                   ("rate is bps (/10000)", 0.0001)):
    f = fund_raw * scale
    tot = net + f
    ann = tot.mean()*365; vol = tot.std()*np.sqrt(365)
    print(f"{lbl:<34}{100*f.mean()*365:>+11.1f}%{100*ann:>+10.1f}%{ann/vol if vol>0 else 0:>9.2f}")
print("\nIf the sign is positive the short-alt book is PAID to hold its shorts,")
print("and the published +59%/yr is conservative rather than optimistic.")
