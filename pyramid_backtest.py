#!/usr/bin/env python3
"""
pyramid_backtest.py — Upward_Pyramyding_On_Breakout_With_Trailing_SL

Turtle-style, verified against theturtletrader.com / tradingblox:
  entry   daily close > highest high of prior D days
  N       20-day ATR (daily)
  size    risk f x equity per unit, unit = risk / (2N)
  pyramid +1 unit per +0.5N favourable, max U units
  stop    2N below the newest unit, AND a chandelier trail (peak - c*N)
  exit    stop hit -> close everything. No profit target (payoff is in the tail).

INVARIANT: liquidation distance >= 1.5 x stop distance, checked after every add.
An add that would break it is REFUSED. This makes leverage derived, not chosen,
and guarantees OUR stop fires before the exchange's.

Costs: fee on notional (so cost on margin = L x fee), funding per 8h held.
Significance: block bootstrap on weekly blocks -- 129 perps share market moves,
so the independent unit is TIME, never the trade.
"""
import glob,os,argparse,numpy as np,pandas as pd

def daily(p):
    d=pd.read_parquet(p)
    if len(d)<24*300: return None
    d["T"]=pd.to_datetime(d.ts,unit="s")
    g=d.set_index("T").resample("1D").agg(o=("o","first"),h=("h","max"),l=("l","min"),
                                          c=("c","last"),v=("v","sum")).dropna()
    if len(g)<150: return None
    tr=np.maximum(g.h-g.l,np.maximum((g.h-g.c.shift()).abs(),(g.l-g.c.shift()).abs()))
    g["N"]=tr.rolling(20).mean()
    return g.dropna()

def backtest(g,D,U,c_trail,fee,fund,maxlev,long_only=True):
    """returns list of trades: dict(entry_t, exit_t, units, avg, exit, R_margin, lev)"""
    hi=g.h.shift(1).rolling(D).max() if D>0 else g.h.shift(1).cummax()
    out=[]; i=0; idx=g.index; n=len(g)
    while i<n:
        if not (g.c.iloc[i]>hi.iloc[i]) or not np.isfinite(hi.iloc[i]):
            i+=1; continue
        e=float(g.c.iloc[i]); N=float(g.N.iloc[i])
        if not (N>0): i+=1; continue
        stopd=2*N
        lev=min(maxlev, 1.0/((stopd/e)*1.5))     # INVARIANT
        if lev<1: i+=1; continue
        units=[e]; last=e; stop=e-stopd; peak=e; held=0; j=i+1
        while j<n:
            r=g.iloc[j]; held+=1
            peak=max(peak,float(r.h))
            while len(units)<U and float(r.h)>=last+0.5*N:
                cand=last+0.5*N
                avg_new=(np.mean(units)*len(units)+cand)/(len(units)+1)
                newstop=max(stop,cand-stopd)
                if (1.0/lev) <= 1.5*((avg_new-newstop)/avg_new):
                    break                         # add would break the invariant
                last=cand; units.append(cand); stop=newstop
            stop=max(stop,peak-c_trail*N)
            if float(r.l)<=stop:
                avg=float(np.mean(units)); ex=stop
                g_=(ex-avg)/avg
                out.append(dict(t0=idx[i],t1=idx[j],u=len(units),avg=avg,ex=ex,
                                lev=lev,held=held,
                                R=g_*lev-lev*fee-lev*fund*3*held))
                break
            j+=1
        else:
            r=g.iloc[-1]; avg=float(np.mean(units)); ex=float(r.c); g_=(ex-avg)/avg
            out.append(dict(t0=idx[i],t1=idx[-1],u=len(units),avg=avg,ex=ex,lev=lev,
                            held=held,R=g_*lev-lev*fee-lev*fund*3*held))
        i=j+1
    return out

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--fee",type=float,default=0.0004)
    ap.add_argument("--fund",type=float,default=0.0001)
    ap.add_argument("--maxlev",type=float,default=20.0)
    a=ap.parse_args()
    files=sorted(glob.glob("data/perp_candles/*.parquet"))
    G={}
    for p in files:
        g=daily(p)
        if g is not None: G[os.path.basename(p)[:-8]]=g
    print(f"{len(G)} symbols with usable daily history\n")
    print(f"{'D':>6}{'U':>4}{'trail':>7}{'trades':>8}{'win%':>7}{'avg u':>7}"
          f"{'medlev':>8}{'EV/trade':>10}{'total R':>10}{'95% CI':>24}")
    print("-"*96)
    for D in [20,55,100,0]:
        for U,ct in [(1,3.0),(4,3.0),(4,2.0)]:
            tr=[]
            for s,g in G.items():
                for t in backtest(g,D,U,ct,a.fee,a.fund,a.maxlev):
                    t["sym"]=s; tr.append(t)
            if len(tr)<50: continue
            df=pd.DataFrame(tr)
            df["blk"]=(df.t0.astype("int64")//10**9)//(7*86400)
            R=df.R.to_numpy(); ub=df.blk.unique(); b=df.blk.to_numpy()
            rng=np.random.default_rng(0); mu=[]
            for _ in range(1500):
                pk=rng.choice(ub,len(ub),replace=True)
                v=np.concatenate([R[b==q] for q in pk[:150] if (b==q).any()])
                if len(v)>30: mu.append(v.mean())
            mu=np.array(mu)
            ci=f"[{np.percentile(mu,2.5):+.4f},{np.percentile(mu,97.5):+.4f}]"
            lbl="ATH" if D==0 else str(D)
            print(f"{lbl:>6}{U:>4}{ct:>7.1f}{len(df):>8}{(R>0).mean()*100:>6.1f}%"
                  f"{df.u.mean():>7.2f}{df.lev.median():>8.1f}{R.mean():>+10.4f}"
                  f"{R.sum():>+10.1f}{ci:>24}")
