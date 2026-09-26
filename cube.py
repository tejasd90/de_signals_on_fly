#!/usr/bin/env python3
"""
cube.py — success rate and PnL across four dimensions:
    event tier (top 5/10/15% of break days)  x  expiry bucket  x  target multiple

DIRECTION IS NOT ASSUMED. The measured edge says a big move is likelier, never
which way. So each event buys BOTH sides: half a unit in an OTM call and half in
an OTM put. One leg usually expires worthless; the trade pays when the other
reaches the target.

    cost    = 1.0 unit + round-trip fees on both legs
    payoff  = 0.5*T for each leg whose PEAK reaches T (a resting limit order)
    EV      = E[payoff] - 1 - fees
    so break-even needs P(a leg reaches T) around 2/T.

EVENT TIERS are ranked on max_age -- the oldest line broken that day -- because
that is the profile column that measures (+15.8pp at P=0.000, versus break count
at P=0.337).

EXPIRY BUCKETS use real days-to-expiry: 0-2 immediate, 3-9 weekly, 10+ next.
OTM band is 3-15% away from spot, which is where the measured edge lives.
"""
import numpy as np, pandas as pd
from rules_test import COST

def load():
    d=pd.read_parquet("events.parquet",columns=["spot","expiry","opt_type","entry_ts",
        "activated","entry_premium","moneyness_pct","peak_vs_trigger","peak_vs_close",
        "event_id"])
    d=d[d.activated & d.spot.isin(["BTC","ETH"])].copy()
    d["r"]=d.peak_vs_trigger.fillna(d.peak_vs_close)
    d=d.dropna(subset=["r","moneyness_pct","entry_premium"])
    d["day"]=pd.to_datetime(d.entry_ts,unit="s").dt.normalize()
    d["dte"]=(pd.to_datetime(d.expiry)-d.day).dt.days
    d["bucket"]=pd.cut(d.dte,[-1,2,9,10**6],labels=["immediate 0-2d","weekly 3-9d","next 10d+"])
    # SIGN BUG FIXED. moneyness_pct is +OTM for CALLS but -OTM for PUTS
    # (correlation with true distance is +1.000 and -1.000 respectively). The
    # old filter `between(3,15)` therefore selected OTM calls and deep ITM puts
    # -- median premium 18.83 vs 2,524.34 -- so the "both sides" book was never
    # symmetric. OTM is now required on both legs.
    otm = np.where(d.opt_type=="C", d.moneyness_pct, -d.moneyness_pct)
    d = d.assign(otm_pct=otm)
    return d[(d.otm_pct>=3)&(d.otm_pct<=15)]

if __name__=="__main__":
    d=load()
    prof=pd.read_csv("daily_break_profile.csv",index_col=0,parse_dates=True)
    brk=prof[prof.n_breaks>0]
    tiers={}
    for p in (5,10,15):
        thr=brk.max_age.quantile(1-p/100.0)
        tiers[f"top {p}%"]=set(brk[brk.max_age>=thr].index)
    tiers["any break day"]=set(brk.index)
    tiers["NO break that day"]=set(prof[prof.n_breaks==0].index)
    print(f"contracts: {len(d):,}  ({d.day.nunique():,} distinct days, OTM 3-15%)")
    print(f"tier sizes (days): " + ", ".join(f"{k}={len(v)}" for k,v in tiers.items()))
    print(f"\nEV per 1 unit staked on the PAIR. Break-even P(a leg hits T) ~ 2/T.\n")
    for T in (10,25,50,100):
        be=(1.0+COST)/T
        print(f"{'='*100}")
        print(f"TARGET {T}x   break-even per leg = {100*be:.2f}%   "
              f"(staking 1 unit split across an OTM call and an OTM put:")
        print(f"              EV = T x P(leg hits) - 1 - fees, so the bar is the SAME as a single option)")
        print(f"{'tier':<18}{'expiry':<16}{'days':>6}{'legs':>8}{'P(leg hits)':>13}"
              f"{'EV/unit':>10}{'P(EV<=0)':>10}")
        for tname,days in tiers.items():
            for b in ["immediate 0-2d","weekly 3-9d","next 10d+"]:
                s2=d[(d.day.isin(days))&(d.bucket==b)].copy()
                if len(s2)<250: continue
                # one OTM call and one OTM put per (day, spot, expiry), nearest 8% out
                s2["dist"]=(s2.otm_pct-8).abs()
                pick=(s2.sort_values("dist")
                        .groupby(["day","spot","expiry","opt_type"],as_index=False).first())
                y=(pick.r>=T).astype(float).to_numpy()
                p=y.mean(); ev=T*p-1.0-COST
                wk=((pick.entry_ts+19800)//604800).astype(int).to_numpy()
                weeks=np.unique(wk); idx={w:np.where(wk==w)[0] for w in weeks}
                rng=np.random.default_rng(0); dr=[]
                for _ in range(2000):
                    sel=np.concatenate([idx[w] for w in rng.choice(weeks,len(weeks),replace=True)])
                    dr.append(T*y[sel].mean()-1.0-COST)
                dr=np.array(dr)
                star="  **" if (dr<=0).mean()<0.05 else ""
                print(f"{tname:<18}{b:<16}{pick.day.nunique():>6}{len(pick):>8,}"
                      f"{100*p:>12.2f}%{ev:>+10.2f}{(dr<=0).mean():>10.3f}{star}")
        print()
