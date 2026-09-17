#!/usr/bin/env python3
"""
brooks_setups.py — test Brooks' setups as setups, on SPOT, on their own terms.

WHY THIS IS DIFFERENT FROM EVERYTHING BEFORE
The context study took option-signal firings as the population and asked whether
spot context predicted the OPTION's payoff. That is a weak test of Brooks: the
sample is "wherever an option signal fired", and the outcome is routed through
moneyness, time to expiry and the volatility premium. He never claimed his setups
forecast option payoffs — he claims they forecast PRICE.

So: every bar is a candidate, the outcome is spot movement, and the yardstick is
his own — the TRADER'S EQUATION.

  "Is there a >=60% chance of making at least your risk?"  (core-concepts sec 6)

Implemented literally: from the signal bar, is the +1R target reached BEFORE the
-1R stop, where R is the setup's own risk (stop beyond the signal bar). That is
a first-crossing test, not a terminal return, so it matches how a trade actually
resolves.

Brooks' benchmarks, which give us something to falsify against:
  - a clear always-in flip implies roughly >=60% for an equidistant move
  - directional probability hovers near 50% most of the time
  - ~80% of trading-range breakouts FAIL
  - beginners lose on ~70%+ of countertrend channel scalps
"""
import json, os
import numpy as np, pandas as pd

def load(spot, tf):
    p = f"data/spot_grouped/{spot}/{tf}.json"
    if not os.path.exists(p): return None
    a = np.asarray(json.load(open(p)), float)
    return a[np.argsort(a[:, 0])]

def atr(h, l, c, n=14):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=2).mean().to_numpy()

def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()

def first_crossing(h, l, i, entry, target, stop, longside, horizon):
    """Did the target come before the stop?

    ENTRY MUST FILL FIRST. These are stop-entries beyond the signal bar, so the
    trade only exists once price trades through `entry`. Counting an immediate
    reversal as a LOSS — which the first version did — makes every setup look
    like a ~38% loser and is the same activation mistake the option work found
    (19% of mark-activated signals never traded above their trigger).

    Returns None if the entry never fills or neither level is reached in the
    horizon. Target and stop hit on the same bar counts as a LOSS, conservatively.
    """
    end = min(len(h), i + 1 + horizon)
    filled = False
    for k in range(i + 1, end):
        if not filled:
            if (longside and h[k] >= entry) or ((not longside) and l[k] <= entry):
                filled = True
                # the same bar can fill and then run; fall through to check it
            else:
                continue
        if longside:
            if l[k] <= stop: return 0
            if h[k] >= target: return 1
        else:
            if h[k] >= stop: return 0
            if l[k] <= target: return 1
    return None

def setups(a, tf):
    """Locate Brooks' named setups. Returns rows of (i, name, longside, entry, stop)."""
    ts, o, h, l, c = a[:,0], a[:,1], a[:,2], a[:,3], a[:,4]
    n = len(c); A = atr(h,l,c); A = np.where(A>0, A, np.nan)
    e20, e50 = ema(c,20), ema(c,50)
    body = np.abs(c-o); rng = np.maximum(h-l,1e-12)
    bull = c > o; bear = c < o
    hi20 = pd.Series(h).rolling(20,min_periods=5).max().shift(1).to_numpy()
    lo20 = pd.Series(l).rolling(20,min_periods=5).min().shift(1).to_numpy()
    # always-in, the same mechanical read used elsewhere
    ai = np.where((c>e20)&(e20>e50),1,np.where((c<e20)&(e20<e50),-1,0))
    # leg counting for H1/H2 and L1/L2
    hh = np.concatenate([[False], h[1:]>h[:-1]]); ll = np.concatenate([[False], l[1:]<l[:-1]])
    hc = lc = 0; hcnt = np.zeros(n); lcnt = np.zeros(n)
    for i in range(1,n):
        if ll[i]: hc = 0
        if hh[i]: hc += 1
        if hh[i]: lc = 0
        if ll[i]: lc += 1
        hcnt[i], lcnt[i] = hc, lc
    out = []
    for i in range(60, n-1):
        if not np.isfinite(A[i]): continue
        R = A[i]
        # 1. H2 / L2 pullback WITH the trend  (core sec 5, trends sec G)
        if ai[i]==1 and hcnt[i]==2 and bull[i]:
            out.append((i,"H2 pullback in bull trend",1,h[i],l[i]-0.05*R))
        if ai[i]==-1 and lcnt[i]==2 and bear[i]:
            out.append((i,"L2 pullback in bear trend",0,l[i],h[i]+0.05*R))
        # 2. FAILED BREAKOUT of a 20-bar range (ranges sec A: ~80% fail)
        if h[i]>hi20[i] and c[i]<hi20[i] and bear[i]:
            out.append((i,"failed breakout of range high",0,l[i],h[i]+0.05*R))
        if l[i]<lo20[i] and c[i]>lo20[i] and bull[i]:
            out.append((i,"failed breakout of range low",1,h[i],l[i]-0.05*R))
        # 3. BREAKOUT with follow-through (ranges sec G: big body, small tail)
        if h[i]>hi20[i] and body[i]/rng[i]>0.7 and bull[i] and (h[i]-c[i])/rng[i]<0.2:
            out.append((i,"strong breakout up",1,h[i],l[i]-0.05*R))
        if l[i]<lo20[i] and body[i]/rng[i]>0.7 and bear[i] and (c[i]-l[i])/rng[i]<0.2:
            out.append((i,"strong breakout down",0,l[i],h[i]+0.05*R))
        # 4. COUNTERTREND scalp — Brooks says beginners lose 70%+ of these
        if ai[i]==1 and bear[i] and body[i]/rng[i]>0.5:
            out.append((i,"countertrend short in bull trend",0,l[i],h[i]+0.05*R))
        if ai[i]==-1 and bull[i] and body[i]/rng[i]>0.5:
            out.append((i,"countertrend long in bear trend",1,h[i],l[i]-0.05*R))
        # 5. ALWAYS-IN FLIP — Brooks: roughly >=60%
        if i>0 and ai[i]==1 and ai[i-1]!=1:
            out.append((i,"always-in flips UP",1,h[i],l[i]-0.05*R))
        if i>0 and ai[i]==-1 and ai[i-1]!=-1:
            out.append((i,"always-in flips DOWN",0,l[i],h[i]+0.05*R))
    return out, h, l, ts

def run(spots=("BTC","ETH"), tfs=(60,240,1440), horizon=20, rr=1.0):
    rows=[]
    for sp in spots:
        for tf in tfs:
            a=load(sp,tf)
            if a is None: continue
            su,h,l,ts=setups(a,tf)
            A=atr(a[:,2],a[:,3],a[:,4])
            for (i,name,longs,entry,stop) in su:
                R=abs(entry-stop)
                if not (R>0): continue
                tgt = entry + rr*R if longs else entry - rr*R
                w=first_crossing(h,l,i,entry,tgt,stop,longs,horizon)
                if w is None: continue
                rows.append(dict(spot=sp,tf=tf,ts=ts[i],setup=name,longside=longs,win=w))
    return pd.DataFrame(rows)

if __name__=="__main__":
    d=run()
    d["week"]=((d.ts+19800)//604800).astype(int)
    print(f"setups found: {len(d):,}   weeks {d.week.nunique()}\n")
    print("=== Brooks' trader's equation: P(+1R before -1R), 20-bar horizon ===")
    print("   his benchmark: >=60% is a good trade, ~50% is a coin flip\n")
    t=d.groupby("setup").agg(n=("win","size"),win=("win","mean"))
    t=t[t.n>=200].sort_values("win",ascending=False)
    t["win"]=(100*t.win).round(2)
    print(t.to_string())
    print(f"\n  ALL setups pooled: {100*d.win.mean():.2f}%  (n={len(d):,})")
