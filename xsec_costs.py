"""Does the cross-sectional book survive REALISTIC execution costs?

xsec2.py uses FEE = 0.0002*1.18 -- the MAKER fee plus GST, 2.36bps. That assumes
every rebalance leg gets a passive fill across ~200 names. Taker is 0.05% (5.9bps
with GST), 2.5x more, and a book this wide will cross the spread often. Alt perps
also carry spread and impact beyond the fee itself.

Any plan built on this number has to know where it breaks, so: sweep the all-in
per-unit-turnover cost from maker-only to pessimistic, at several rebalance
spacings. Also report annual turnover, which is what actually sets the bill.
"""
import numpy as np, pandas as pd
from xsec2 import load, run, FEE

Pd, Vd, dead = load(include_dead=True)
print(f"universe {Pd.shape[1]} names, {len(Pd)} days\n")

MAKER = 0.0002*1.18
TAKER = 0.0005*1.18
COSTS = [("maker only (as published)", MAKER),
         ("taker", TAKER),
         ("taker + 5bps slippage", TAKER + 0.0005),
         ("taker + 15bps slippage", TAKER + 0.0015),
         ("taker + 30bps slippage", TAKER + 0.0030)]

def ann_stats(net):
    ann = net.mean()*365; vol = net.std()*np.sqrt(365)
    eq = net.cumsum(); dd = (eq-eq.cummax()).min()
    return ann, vol, (ann/vol if vol > 0 else 0), dd

print(f"{'rebalance':<14}{'turnover/yr':>12}" + "".join(f"{c[0][:16]:>18}" for c in COSTS))
for reb, lbl in ((1,"daily"), (5,"5-day (pub)"), (10,"10-day"), (20,"20-day")):
    row = []
    turn_yr = None
    for _, fee in COSTS:
        net, turn, W = run(Pd, Vd, reb=reb, hedge=True, fee=fee)
        a, v, s, d = ann_stats(net)
        if turn_yr is None: turn_yr = turn.mean()*365
        row.append(f"{100*a:+7.1f}% S{s:4.2f}")
    print(f"{lbl:<14}{turn_yr:>11.1f}x" + "".join(f"{r:>18}" for r in row))

print("\nturnover/yr = gross position change per year as a multiple of book size.")
print("Each 1x of turnover costs you (1x * all-in cost) per year.")
