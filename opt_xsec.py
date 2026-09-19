#!/usr/bin/env python3
"""
opt_xsec.py — Step 3: a market-neutral RELATIVE-VALUE book in options.

THE ARGUMENT
This project measured, and then treated as a disappointment, that the model is
an excellent strike PICKER and a poor TIMER: AUC 0.95 for ranking contracts
WITHIN an episode, 0.57 for telling one episode from another. Directional option
buying needs the timing skill we do not have. Cross-sectional relative value
needs only the ranking skill we do -- long the contracts that look cheap against
their siblings, short the ones that look rich, same spot and same expiry, no view
on direction at all.

WHY TERMINAL PAYOFFS, NOT PEAKS
Every existing number is "did the mark touch 25x at some point", which assumes a
resting limit order got filled. You cannot short to a peak. Delta options are
European and cash-settled, so the terminal value is exact arithmetic:
    call  max(0, S_T - K)      put  max(0, K - S_T)
This also yields something never measured here: what BUYING AND HOLDING these
contracts to expiry actually returns.

COSTS
Delta charges 0.010% of notional capped at 3.5% of premium, plus 18% GST, and the
same again on the settled side unless it expires worthless. Applied per leg.
"""
import os, json, glob
import numpy as np, pandas as pd

GST=1.18
def fee(premium, spot_px, cap=0.035, rate=0.0001):
    return np.minimum(rate*spot_px, cap*premium)*GST

def spot_close_series(spot):
    d=os.path.join("data/spot_candles",spot,"60"); rows=[]
    for fn in sorted(os.listdir(d)):
        if fn.startswith(".") or ".tmp." in fn: continue
        try: rows.extend(json.load(open(os.path.join(d,fn))))
        except Exception: pass
    a=np.asarray([r[:5] for r in rows],float); a=a[np.argsort(a[:,0])]
    return a[:,0], a[:,4]

if __name__=="__main__":
    d=pd.read_parquet("events.parquet", columns=["spot","expiry","opt_type","strike",
        "entry_premium","spot_at_entry","entry_ts","event_id","activated","signal",
        "duration","moneyness_pct","signal_value"])
    d=d[d.spot.isin(["BTC","ETH"])].copy()
    # settlement spot: last hourly close on the expiry date (Delta settles 17:30 IST)
    S={}
    for s in ("BTC","ETH"): S[s]=spot_close_series(s)
    exp_ts=(pd.to_datetime(d.expiry)+pd.Timedelta(hours=12)).astype("int64")//10**9
    d["exp_ts"]=exp_ts
    st=np.full(len(d),np.nan)
    for s in ("BTC","ETH"):
        m=(d.spot==s).to_numpy(); ts,c=S[s]
        j=np.searchsorted(ts,d.exp_ts.to_numpy()[m],side="right")-1
        ok=j>=0; v=np.full(m.sum(),np.nan); v[ok]=c[j[ok]]; st[m]=v
    d["S_T"]=st
    d=d.dropna(subset=["S_T","entry_premium","strike"])
    d=d[d.entry_premium>0]
    d["payoff"]=np.where(d.opt_type=="C", np.maximum(0,d.S_T-d.strike),
                                           np.maximum(0,d.strike-d.S_T))
    f_in =fee(d.entry_premium,d.spot_at_entry)
    f_out=np.where(d.payoff>0, fee(d.payoff,d.S_T), 0.0)
    d["ret"]=(d.payoff-d.entry_premium-f_in-f_out)/d.entry_premium
    d["week"]=((d.entry_ts+19800)//604800).astype(int)
    print(f"contracts with an exact terminal value: {len(d):,}  "
          f"({d.event_id.nunique():,} events, {d.week.nunique()} weeks)\n")
    print("=== NEVER MEASURED HERE: what does BUY-AND-HOLD-TO-EXPIRY return? ===")
    print(f"  mean return {100*d.ret.mean():>+8.1f}%   median {100*d.ret.median():>+7.1f}%   "
          f"expired worthless {100*(d.payoff<=0).mean():.1f}%")
    for lo,hi in [(0,1),(1,2),(2,5),(5,20),(20,1e9)]:
        s=d[d.entry_premium.between(lo,hi)]
        if len(s)<500: continue
        print(f"    premium {lo:>4}-{hi:<6g} n={len(s):>7,}  mean {100*s.ret.mean():>+8.1f}%  "
              f"worthless {100*(s.payoff<=0).mean():>5.1f}%")
    d.to_parquet("opt_terminal.parquet",index=False)
    print("\nwrote opt_terminal.parquet")

# ─── relative value within (spot, expiry, timestamp) ─────────────────────────
def xs_book(d, rank_col, ascending=True, min_n=6, q=0.34):
    """Long the cheap-ranked contracts, short the rich-ranked, SAME spot, SAME
    expiry, SAME instant. Premium-weighted, so the book costs nothing net at
    entry. Returns the per-group long-short spread."""
    out=[]
    for key,g in d.groupby(["spot","expiry","entry_ts","opt_type"]):
        if len(g)<min_n: continue
        g=g.sort_values(rank_col,ascending=ascending)
        k=max(1,int(len(g)*q))
        L=g.head(k); S=g.tail(k)
        out.append(dict(spot=key[0],expiry=key[1],ts=key[2],ty=key[3],n=len(g),
                        L=L.ret.mean(), S=S.ret.mean(), spread=L.ret.mean()-S.ret.mean(),
                        week=g.week.iloc[0], worst_short=S.ret.max()))
    return pd.DataFrame(out)

def boot(x, n=4000, seed=0):
    rng=np.random.default_rng(seed)
    wk=x.week.to_numpy(); y=x.spread.to_numpy()
    weeks=np.unique(wk); idx={w:np.where(wk==w)[0] for w in weeks}
    dr=[]
    for _ in range(n):
        pick=rng.choice(weeks,len(weeks),replace=True)
        sel=np.concatenate([idx[w] for w in pick])
        dr.append(y[sel].mean())
    dr=np.array(dr)
    return np.median(dr), np.percentile(dr,5), np.percentile(dr,95), (dr<=0).mean()

if __name__=="__main__" and os.environ.get("OPT_XS"):
    d=pd.read_parquet("opt_terminal.parquet")
    d=d[d.entry_premium.between(0.5,50)]
    print(f"universe {len(d):,} contracts\n")
    print("Long/short WITHIN the same spot+expiry+instant+type — no directional view.")
    print(f"{'ranking':<34} {'groups':>7} {'wks':>4} {'long':>8} {'short':>8} "
          f"{'spread':>9} {'P(<=0)':>7} {'worst short':>12}")
    tests=[("cheap first: low premium",       "entry_premium", True),
           ("rich first: high premium",       "entry_premium", False),
           ("far OTM first",                  "moneyness_pct", False),
           ("near the money first",           "moneyness_pct", True),
           ("signal_value high (cheapness)",  "signal_value",  False)]
    for lbl,col,asc in tests:
        if col not in d.columns: continue
        x=xs_book(d.dropna(subset=[col]),col,ascending=asc)
        if len(x)<200: print(f"{lbl:<34} (too few)"); continue
        m,lo,hi,p=boot(x)
        print(f"{lbl:<34} {len(x):>7,} {x.week.nunique():>4} {100*x.L.mean():>+7.1f}% "
              f"{100*x.S.mean():>+7.1f}% {100*m:>+8.1f}% {p:>7.3f} {100*x.worst_short.min():>11,.0f}%")
    print("\nTHE RISK THE AVERAGE HIDES: a short option's loss is unbounded.")
    x=xs_book(d,"entry_premium",True)
    print(f"  worst single short leg in the sample: {100*x.worst_short.min():,.0f}% of premium")
    print(f"  groups where the short leg lost >10x premium: "
          f"{100*(x.worst_short<-10).mean():.2f}%")
    print(f"  spread percentiles: p1 {100*x.spread.quantile(.01):>+8.0f}%  "
          f"p50 {100*x.spread.median():>+6.1f}%  p99 {100*x.spread.quantile(.99):>+7.0f}%")
