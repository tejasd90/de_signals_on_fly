#!/usr/bin/env python3
"""
pyramid.py — scaling INTO a pullback: 1 unit now, 2 at -1%, 3 at -2%, ...

THE STRUCTURE
Level k (k=0,1,2,...) buys (k+1) units at P0*(1-k*step). After filling levels
0..K the position is the triangular number N = (K+1)(K+2)/2, which is why this
gets dangerous fast: surviving a 16% pullback at 1% steps means holding 153 units
against the 1 you started with.

THE ARITHMETIC THAT DECIDES EVERYTHING
Average entry after K levels, as a fraction of P0:
    avg/P0 = [ S1 - step*S2 ] / S1,  S1 = sum(k+1), S2 = sum(k(k+1))
Liquidation is when equity falls under maintenance margin:
    capital + N*CV*(P - avg)  <  MM * N*CV*P
so the capital needed to survive down to price P is
    C(P) = N*CV*[ avg - P*(1 - MM) ]
which is exact, not simulated.

WHAT THIS REVEALS
C is expressed in multiples of the FIRST lot's notional. If surviving 16% needs
8.5x the opening notional in cash, then the opening trade can be levered at most
1/8.5 = 0.12x. The ladder does not let you use leverage -- it consumes it. Every
"leverage" number below is therefore the MAXIMUM opening leverage consistent with
surviving that pullback, which is the honest way round.

Delta specifics: MM 0.25%, and max_leverage_notional is $100,000 on ETHUSD, so
200x is unavailable above that size regardless of what this table says.
"""
import argparse
import numpy as np, pandas as pd

MM=0.0025

def ladder(K, step, shape="linear"):
    k=np.arange(K+1)
    q=(k+1.0) if shape=="linear" else np.ones(K+1) if shape=="flat" else (k+1.0)**2
    px=1.0-step*k                      # price as a fraction of P0
    N=q.sum()
    avg=(q*px).sum()/N
    return N, avg, q, px

def table(step=0.01, shape="linear", depths=(2,4,6,8,10,12,16,20,25,30)):
    rows=[]
    for d in depths:
        K=int(round(d/ (step*100)))
        N,avg,q,px=ladder(K,step,shape)
        P=1.0-d/100.0                        # price at the bottom, fraction of P0
        unreal=N*(P-avg)                     # in units of CV*P0
        notional=N*P
        cap=N*(avg-P*(1-MM))                 # capital needed, in CV*P0 units
        rows.append(dict(pullback_pct=d, levels=K+1, units=N,
                         avg_entry_pct=100*(avg-1), price_pct=-d,
                         notional_x=notional, unreal_x=unreal, capital_x=cap,
                         max_open_lev=1.0/cap if cap>0 else np.inf,
                         lev_at_bottom=notional/cap if cap>0 else np.inf))
    return pd.DataFrame(rows)

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--step",type=float,default=1.0,help="ladder spacing in %%")
    ap.add_argument("--price",type=float,default=2480.0)
    ap.add_argument("--cv",type=float,default=0.01,help="contract value (ETH/lot)")
    ap.add_argument("--capital-inr",type=float,default=None)
    ap.add_argument("--usdinr",type=float,default=88.0)
    a=ap.parse_args()
    step=a.step/100.0
    print(f"LADDER: 1 unit at P0, 2 units at -{a.step}%, 3 at -{2*a.step}%, ...")
    print(f"maintenance margin {100*MM}%   (all X columns are multiples of the FIRST lot's notional)\n")
    t=table(step)
    print(f"{'pullback':>9} {'levels':>7} {'units':>7} {'avg entry':>10} {'notional':>9} "
          f"{'unrealised':>11} {'CAPITAL':>9} {'max open':>9} {'lev at':>7}")
    print(f"{'':9} {'filled':>7} {'held':>7} {'vs P0':>10} {'x':>9} {'x':>11} {'x':>9} "
          f"{'leverage':>9} {'bottom':>7}")
    for _,r in t.iterrows():
        print(f"{r.pullback_pct:>8.0f}% {int(r.levels):>7} {r.units:>7.0f} "
              f"{r.avg_entry_pct:>9.2f}% {r.notional_x:>9.1f} {r.unreal_x:>11.1f} "
              f"{r.capital_x:>9.2f} {r.max_open_lev:>8.3f}x {r.lev_at_bottom:>6.1f}x")

    print(f"\nWORKED IN MONEY — ETH at ${a.price:,.0f}, {a.cv} ETH/lot, 1 unit = 1 lot")
    one=a.cv*a.price
    print(f"  one lot notional = ${one:,.2f}")
    print(f"{'pullback':>9} {'lots held':>10} {'notional':>13} {'capital needed':>16} "
          f"{'liq price':>11} {'capital INR':>13}")
    for _,r in t.iterrows():
        cap=r.capital_x*one
        liq=a.price*(1.0-r.pullback_pct/100.0)
        print(f"{r.pullback_pct:>8.0f}% {r.units:>10.0f} {r.notional_x*one:>12,.0f}$ "
              f"{cap:>15,.0f}$ {liq:>10,.1f}$ {cap*a.usdinr/1e5:>12.2f}L")

# ─── empirical: does the ladder actually pay after an upmove? ────────────────
def backtest(g, sym, step=0.01, trig=0.15, lookback=10, H=60, max_levels=30, mm=MM):
    """Fire after an upmove, then run the ladder. Report the deepest level
    reached, whether price got back to the ladder's average entry, and the PnL."""
    import numpy as np
    o,h,l,c=g.o.to_numpy(),g.h.to_numpy(),g.l.to_numpy(),g.c.to_numpy()
    n=len(c); out=[]
    up=pd.Series(c).pct_change(lookback).to_numpy()
    i=lookback+1
    while i<n-H-1:
        if not (np.isfinite(up[i]) and up[i]>trig): i+=1; continue
        P0=c[i]
        lows=l[i+1:i+H+1]; closes=c[i+1:i+H+1]
        deepest=(P0-lows.min())/P0
        K=min(int(np.floor(deepest/step)), max_levels)
        N,avg_f,q,px=ladder(K,step)
        avg=avg_f*P0
        # did price return to the average entry within the window, after the
        # deepest fill? that is the ladder's exit condition
        recovered=bool((closes>avg).any())
        capital_x=N*(avg_f-(1-deepest)*(1-mm))          # in first-lot notionals
        out.append(dict(sym=sym, ts=int(g.ts.iloc[i]), up=up[i], deepest=deepest,
                        levels=K+1, units=N, avg_pct=100*(avg_f-1),
                        recovered=recovered, capital_x=max(capital_x,0.0),
                        end_pct=100*(closes[-1]/P0-1),
                        pnl_x=N*(closes[-1]-avg)/P0))    # in first-lot notionals
        i+=H//2                                          # avoid overlapping episodes
    return out

if __name__=="__main__" and __import__("os").environ.get("PYR_BT"):
    import glob, os
    from exhaustion import daily_v
    rows=[]
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        g=daily_v(fp)
        if g is not None: rows+=backtest(g, os.path.basename(fp)[:-8])
    E=pd.DataFrame(rows); E["week"]=((E.ts+19800)//604800).astype(int)
    print(f"\n\nEMPIRICAL — ladder fired after a >15% 10-day upmove, 60-day window")
    print(f"episodes {len(E):,}  symbols {E.sym.nunique()}  weeks {E.week.nunique()}\n")
    print("How deep does the pullback go before continuation?")
    for d in (2,4,6,8,10,12,16,20,25,30):
        print(f"  reached -{d:>2}% : {100*(E.deepest>=d/100).mean():>5.1f}% of episodes")
    print(f"\n  median deepest pullback {100*E.deepest.median():.1f}%   "
          f"p90 {100*E.deepest.quantile(.9):.1f}%   max {100*E.deepest.max():.1f}%")
    print(f"  price returned to the ladder's average entry: {100*E.recovered.mean():.1f}%")
    print(f"\nCAPITAL ACTUALLY CONSUMED (multiples of the first lot's notional)")
    print(f"  median {E.capital_x.median():.2f}x   p90 {E.capital_x.quantile(.9):.1f}x   "
          f"p99 {E.capital_x.quantile(.99):.1f}x   max {E.capital_x.max():.1f}x")
    print(f"\nOUTCOME after 60 days, in first-lot notionals")
    print(f"  ladder PnL   mean {E.pnl_x.mean():>+8.2f}x  median {E.pnl_x.median():>+7.2f}x  "
          f"p5 {E.pnl_x.quantile(.05):>+8.2f}x")
    print(f"  buy 1 & hold mean {(E.end_pct/100).mean():>+8.2f}x  "
          f"median {(E.end_pct/100).median():>+7.2f}x  p5 {(E.end_pct/100).quantile(.05):>+8.2f}x")
    print(f"\n  RETURN ON CAPITAL AT RISK (ladder PnL / capital consumed):")
    ok=E[E.capital_x>0.01]
    print(f"    median {(ok.pnl_x/ok.capital_x).median():+.3f}   "
          f"mean {(ok.pnl_x/ok.capital_x).mean():+.3f}")
