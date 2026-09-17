#!/usr/bin/env python3
"""
grid_eth.py — Tejas's 200x ETH grid, on 1-minute data since inception.

THE SPEC AS GIVEN
  200x leverage. Start long 10,000 lots. Sell 100 lots every 6 points up, buy
  100 lots every 6 points down. ~100 live orders each side. Every fill seeds the
  opposite order 6 points away. Earning from vibrations, with a positive view.

  Note 10,000 lots is exactly 100 sell orders x 100 lots — the opening block is
  the sell-side ammunition, so the two halves of the spec are consistent.

THE GAPS, AND HOW THEY ARE FILLED

  1. INTRABAR PATH. OHLC does not say whether a level was touched once or
     round-tripped ten times. Counting both the high AND the low as separate
     sweeps of every level manufactures round trips that never happened, and is
     the single largest source of fake grid profits. Rule used here: every level
     inside [low, high] is touched ONCE per bar, in the direction of open->close.
     This is a LOWER bound on grid income and the number to trust.
     --optimistic walks o->h->l->c (or o->l->h->c), roughly an upper bound.

  2. WHAT HAPPENS WHEN THE 10,000 LOTS RUN OUT going up. Selling past zero makes
     you short, which contradicts the stated positive view, so selling stops at
     flat. --allow-short gives the classic two-sided grid instead.

  3. ONCE EXHAUSTED, DOES THE GRID FOLLOW PRICE? This is the fork that decides
     the capital answer, and the spec does not settle it:
       following (default) - "100 orders on each side AT ALL TIMES" taken
            literally: the band re-centres, so every 6-point decline anywhere
            buys 100 lots. Accumulation tracks total downside PATH.
       --anchored - the ladder is fixed to the start price. Above the exhaustion
            level there are no orders at all, so a rally beyond it is dead space
            and the walk back down re-fills from the exhaustion level, not from
            the high. Accumulation tracks NET displacement only.
     Both are reported.

  4. GAPS. One 66.7h outage exists in the series. Levels are not filled across
     any gap longer than --max-gap minutes; the ladder is simply re-based.

ACCOUNTING
  Total PnL is convention-free: net cashflow over all fills, plus open inventory
  marked to the last price, minus fees and funding. Position/average entry are
  kept Delta-style (weighted average) for margin and liquidation. A separate
  LIFO pass reports matched round trips, i.e. how much of the PnL is vibration
  income rather than direction.

COSTS
  maker 0.02% + 18% GST on notional per fill. Funding every 8h from the stored
  ETHUSD series (Delta quotes it per 8h, as a percentage).
"""
import argparse, os
import numpy as np, pandas as pd

CV = 0.01       # ETH per lot
MM = 0.0025     # maintenance margin at 200x

def simulate(bars, spacing, lots, initial, fee_rate, funding, mode,
             allow_short, max_gap, optimistic, anchored=False):
    ts = bars[:,0]; o=bars[:,1]; h=bars[:,2]; l=bars[:,3]; c=bars[:,4]
    start = o[0]
    lvl = lambda p: int(np.floor((p-start)/spacing))

    pos = float(initial); avg = start
    cash = -pos*CV*start                 # opening block bought at the open
    fees = pos*CV*start*fee_rate
    fund = 0.0
    stack = [(start, pos)]               # LIFO lots, for round-trip accounting
    rt_profit = 0.0; rt_count = 0
    last = lvl(o[0]); n_buy = n_sell = 0
    max_pos = pos; max_notional = pos*CV*start
    cap_need = 0.0; cap_when = ts[0]
    worst_eq = 0.0
    next_fund = ts[0] + 8*3600
    curve = []

    def sweep(lo_l, hi_l, up):
        """Fill every level between lo_l and hi_l in one direction.
        Returns the level the ladder ends up at. In anchored mode that stops at
        the first unfillable sell level: with no orders resting above, price
        running further up is dead space the grid never sees."""
        nonlocal pos, avg, cash, fees, stack, rt_profit, rt_count, n_buy, n_sell
        # No bounds check against [bar_lo, bar_hi]. Price is continuous between
        # bars, so every level from the ladder's current position to this bar's
        # extreme WAS traversed, even the ones sitting in the gap between the
        # previous close and this bar's low. Guarding on the bar's own range
        # drops ~89% of genuine crossings.
        rng = range(last+1, hi_l+1) if up else range(last-1, lo_l-1, -1)
        reached = last
        for k in rng:
            price = start + k*spacing
            if up:
                q = lots if allow_short else min(lots, max(pos, 0.0))
                if q <= 0:
                    if anchored: return reached
                    reached = k; continue
                cash += price*q*CV; pos -= q; n_sell += 1
                rem = q                              # LIFO match
                while rem > 0 and stack:
                    ep, eq = stack[-1]
                    m = min(rem, eq)
                    rt_profit += (price-ep)*m*CV; rt_count += 1
                    rem -= m
                    if m == eq: stack.pop()
                    else: stack[-1] = (ep, eq-m)
                if rem > 0: stack.append((price, -rem))
            else:
                q = lots
                cash -= price*q*CV
                avg = (avg*pos + price*q)/(pos+q) if abs(pos+q) > 1e-9 else price
                pos += q; n_buy += 1
                stack.append((price, q))
            fees += q*CV*price*fee_rate
            reached = k
        return reached

    for i in range(len(c)):
        if i and ts[i]-ts[i-1] > max_gap*60:
            last = lvl(o[i])                      # re-base across the outage
        lo_l, hi_l = lvl(l[i]), lvl(h[i])
        up = c[i] >= o[i]
        if optimistic:
            # walk the full excursion: out to the far extreme, back to the near
            # one, then on to the close. Roughly an upper bound on fills.
            for d in ([False, True] if up else [True, False]):
                last = sweep(lo_l, hi_l, d)
        else:
            last = sweep(lo_l, hi_l, up)

        while ts[i] >= next_fund:
            r = 0.01
            if funding is not None:
                j = np.searchsorted(funding[:,0], next_fund)-1
                if j >= 0: r = funding[j,1]
            fund += pos*CV*c[i]*(r/100.0)         # long pays when rate > 0
            next_fund += 8*3600

        notional = abs(pos)*CV*c[i]
        if abs(pos) > max_pos: max_pos = abs(pos)
        if notional > max_notional: max_notional = notional
        pnl = cash + pos*CV*c[i] - fees - fund
        if pnl < worst_eq: worst_eq = pnl
        need = MM*notional - pnl
        if need > cap_need: cap_need, cap_when = need, ts[i]
        if i % 1440 == 0: curve.append((ts[i], pnl, pos, c[i]))

    pnl = cash + pos*CV*c[-1] - fees - fund
    return dict(pnl=pnl, cash=cash, fees=fees, funding=fund, pos=pos, avg=avg,
                mtm=pos*CV*c[-1], rt_profit=rt_profit, rt_count=rt_count,
                n_buy=n_buy, n_sell=n_sell, max_pos=max_pos,
                max_notional=max_notional, cap_need=cap_need, cap_when=cap_when,
                worst_eq=worst_eq, last=c[-1], first=o[0], curve=curve, mode=mode)

def load(path="data/eth_1m.parquet"):
    d = pd.read_parquet(path).sort_values("ts")
    f = None
    if os.path.exists("data/funding/ETHUSD.parquet"):
        fd = pd.read_parquet("data/funding/ETHUSD.parquet").sort_values("ts")
        f = fd[["ts","rate"]].to_numpy(float)
    return d[["ts","o","h","l","c"]].to_numpy(float), f

def show(r, X):
    cr = lambda u: f"{u*X/1e7:>9.2f} cr"
    print(f"\n=== {r['mode']} ===")
    print(f"  fills                 {r['n_buy']+r['n_sell']:>13,}  ({r['n_buy']:,} buy / {r['n_sell']:,} sell)")
    print(f"  matched round trips   {r['rt_count']:>13,}  -> {r['rt_profit']:>12,.0f} USD {cr(r['rt_profit'])}   <- vibration income")
    print(f"  fees                  {-r['fees']:>26,.0f} USD {cr(-r['fees'])}")
    print(f"  funding               {-r['funding']:>26,.0f} USD {cr(-r['funding'])}")
    print(f"  open {r['pos']:>10,.0f} lots  ({r['pos']*CV:,.0f} ETH @ avg {r['avg']:,.1f} vs {r['last']:,.1f})")
    print(f"  " + "-"*62)
    print(f"  TOTAL PnL             {r['pnl']:>26,.0f} USD {cr(r['pnl'])}")
    print(f"\n  peak position         {r['max_pos']:>13,.0f} lots = {r['max_pos']*CV:,.0f} ETH")
    print(f"  peak notional         {r['max_notional']:>26,.0f} USD {cr(r['max_notional'])}")
    print(f"  worst equity dip      {r['worst_eq']:>26,.0f} USD {cr(r['worst_eq'])}")
    print(f"  CAPITAL to survive    {r['cap_need']:>26,.0f} USD {cr(r['cap_need'])}"
          f"   (binds {pd.Timestamp(r['cap_when'],unit='s').date()})")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spacing", type=float, default=6.0)
    ap.add_argument("--lots", type=int, default=100)
    ap.add_argument("--initial", type=int, default=10000)
    ap.add_argument("--usdinr", type=float, default=88.0)
    ap.add_argument("--fee", type=float, default=0.0002)
    ap.add_argument("--gst", type=float, default=1.18)
    ap.add_argument("--max-gap", type=float, default=10)
    ap.add_argument("--optimistic", action="store_true")
    ap.add_argument("--allow-short", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    bars, f = load()
    print(f"ETH 1m  {len(bars):,} bars  {pd.Timestamp(bars[0,0],unit='s').date()} -> "
          f"{pd.Timestamp(bars[-1,0],unit='s').date()}   {bars[0,1]:,.1f} -> {bars[-1,4]:,.1f}"
          f"   (low {bars[:,3].min():,.1f}, high {bars[:,2].max():,.1f})")
    fr = a.fee*a.gst
    if a.sweep:
        print(f"\n{'spacing':>8} {'fills':>10} {'roundtrips':>11} {'PnL USD':>14} {'PnL cr':>9} {'capital cr':>11}")
        for sp in [3,4,6,8,10,15,20,30,50]:
            r = simulate(bars, sp, a.lots, a.initial, fr, f, "following", False, a.max_gap, False, False)
            print(f"{sp:>8} {r['n_buy']+r['n_sell']:>10,} {r['rt_count']:>11,} {r['pnl']:>14,.0f} "
                  f"{r['pnl']*a.usdinr/1e7:>9.2f} {r['cap_need']*a.usdinr/1e7:>11.2f}")
        raise SystemExit
    for mode, anch in [("FOLLOWING - band re-centres on price", False),
                       ("ANCHORED - ladder fixed to the start price", True)]:
        show(simulate(bars, a.spacing, a.lots, a.initial, fr, f, mode,
                      a.allow_short, a.max_gap, a.optimistic, anch), a.usdinr)
