#!/usr/bin/env python3
"""
spot_sustain.py — Tejas's sustain/fade claim, tested on spot at positional horizons.

THE CLAIM
"When the market is feeling oversold/overbought and needs to go up/down, it does
not matter what the level is -- it will absorb the opposite side moves, which
gives the calm, and then it will move decisively. When it is overbought/oversold
after a rally/crash, it will be unstable and volatile and won't sustain."

His two Nifty cases: Dec-2023 broke the swing high after a calm stretch, gapped
over the ATH and SUSTAINED for nine months to 26,000. Sep-2024 made the ATH
already extended, faded within weeks and gave it all back to 21,700.

WHY THIS CANNOT BE TESTED ON THE OPTION SET
Two reasons, both measured. (1) Horizon: his moves run for MONTHS; option events
resolve in days. (2) Collinearity: a channel-line break means price is already
far from the line, so "break while NOT extended" had n=0 events. The claim has to
be tested on spot, where the breakout level and the pre-state are separable.

DESIGN
Daily bars from 220 Delta perpetuals (129 with >1y). Event = close breaking the
prior BREAK_N-day extreme. Pre-state measured strictly BEFORE the event bar:
  absorb  = (1 - efficiency) x overlap  -- opposite attempts that failed to
            make progress; his "calm"
  ttr     = prior range in ATR          -- tight trading range
  ext     = (close - ema50)/ATR, signed toward the break -- his "overbought
            after a rally"
Outcomes, signed toward the break, at 5 / 20 / 60 daily bars:
  ret     = forward return
  sustain = price NEVER closes back through the breakout level within H
            (his word: "sustained the breakout")

INDEPENDENCE
Crypto symbols move together -- this project measured N_eff 5.8 across 220 perps.
So the resampling unit is the CALENDAR WEEK across all symbols, never the
symbol-week and never the row.
"""
import glob, os, argparse
import numpy as np, pandas as pd

BREAK_N=20; PRE=20; HORIZONS=(5,20,60)

def daily(fp):
    d=pd.read_parquet(fp).sort_values("ts")   # o=first/c=last need ts order
    d["day"]=(d.ts//86400).astype(int)
    g=d.groupby("day").agg(o=("o","first"),h=("h","max"),l=("l","min"),
                           c=("c","last"),ts=("ts","first")).reset_index()
    return g if len(g)>=250 else None

def atr(h,l,c,n=14):
    pc=np.concatenate([[c[0]],c[:-1]])
    tr=np.maximum(h-l,np.maximum(abs(h-pc),abs(l-pc)))
    return pd.Series(tr).rolling(n,min_periods=2).mean().to_numpy()

def events(g,sym):
    h,l,c=g.h.to_numpy(),g.l.to_numpy(),g.c.to_numpy()
    n=len(c); A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    e50=pd.Series(c).ewm(span=50,adjust=False).mean().to_numpy()
    # prior extremes, strictly before bar i
    ph=pd.Series(h).shift(1).rolling(BREAK_N,min_periods=BREAK_N).max().to_numpy()
    pl=pd.Series(l).shift(1).rolling(BREAK_N,min_periods=BREAK_N).min().to_numpy()
    rng=h-l
    ov=np.concatenate([[np.nan],(np.minimum(h[1:],h[:-1])-np.maximum(l[1:],l[:-1]))/np.maximum(rng[1:],1e-12)])
    ov=np.clip(ov,0,1)
    ovm=pd.Series(ov).shift(1).rolling(PRE,min_periods=5).mean().to_numpy()
    net=np.abs(c-pd.Series(c).shift(PRE).to_numpy())
    tot=pd.Series(np.abs(np.diff(c,prepend=c[0]))).rolling(PRE,min_periods=5).sum().to_numpy()
    eff=net/np.maximum(tot,1e-12)
    eff_p=pd.Series(eff).shift(1).to_numpy()
    ttr=pd.Series((pd.Series(h).rolling(PRE,min_periods=5).max()-
                   pd.Series(l).rolling(PRE,min_periods=5).min())/A).shift(1).to_numpy()
    ext_raw=pd.Series((c-e50)/A).shift(1).to_numpy()
    out=[]
    for i in range(max(BREAK_N,PRE)+55, n-1):
        for d,lvl,hit in ((1,ph[i],c[i]>ph[i]),(-1,pl[i],c[i]<pl[i])):
            if not hit or not np.isfinite(lvl): continue
            row=dict(sym=sym,ts=int(g.ts.iloc[i]),i=i,dirn=d,lvl=lvl,c=c[i],
                     absorb=(1-eff_p[i])*ovm[i], ttr=ttr[i], ext=d*ext_raw[i])
            for H in HORIZONS:
                # FULL horizon only. j=min(i+H,n-1) used to truncate the window
                # near each symbol's series end; a shorter window is easier to
                # "sustain" and damps the return, biasing both upward. Outcomes
                # are NaN when the whole horizon is not available, per horizon,
                # so a 20d result is still kept when only 60d is unavailable.
                j=i+H
                if j>n-1:
                    row[f"ret{H}"]=np.nan; row[f"sus{H}"]=np.nan; continue
                row[f"ret{H}"]=d*(c[j]/c[i]-1)
                seg=c[i+1:j+1]
                row[f"sus{H}"]=float(np.all(seg>lvl) if d>0 else np.all(seg<lvl))
            out.append(row)
    return out

def blockboot(df,col,mask,n=2000,seed=0):
    """Resample CALENDAR WEEKS across all symbols."""
    rng=np.random.default_rng(seed)
    ok=df[col].notna().to_numpy()
    df=df[ok]; mask=np.asarray(mask,bool)[ok]
    wk=df.week.to_numpy(); y=df[col].to_numpy(); m=np.asarray(mask,bool)
    weeks=np.unique(wk); W=len(weeks); idx={w:np.where(wk==w)[0] for w in weeks}
    out=[]
    for _ in range(n):
        pick=rng.choice(weeks,W,replace=True)
        sel=np.concatenate([idx[w] for w in pick])
        yy,mm=y[sel],m[sel]
        if mm.sum()<30 or (~mm).sum()<30: continue
        out.append(yy[mm].mean()-yy[~mm].mean())
    return np.array(out)

if __name__=="__main__":
    rows=[]
    for fp in sorted(glob.glob("data/perp_candles/*.parquet")):
        g=daily(fp)
        if g is None: continue
        rows+=events(g, os.path.basename(fp)[:-8])
    E=pd.DataFrame(rows).dropna(subset=["absorb","ext","ttr"])
    for H in HORIZONS:
        print(f"  horizon {H}d: {int(E[f'sus{H}'].notna().sum()):,} of {len(E):,} events have a full window")
    E["week"]=((E.ts+19800)//604800).astype(int)
    E["d"]=pd.to_datetime(E.ts,unit="s")
    E.to_parquet("spot_breakouts.parquet",index=False)
    print(f"breakouts {len(E):,}  symbols {E.sym.nunique()}  weeks {E.week.nunique()}  "
          f"{E.d.min().date()} -> {E.d.max().date()}")
    print(f"  up {int((E.dirn>0).sum()):,}  down {int((E.dirn<0).sum()):,}\n")
    for H in HORIZONS:
        print(f"=== HORIZON {H} days ===")
        for col,lab in [("ext","EXTENSION before the break (his 'overbought after a rally')"),
                        ("absorb","ABSORPTION before the break (his 'calm')")]:
            E["q"]=pd.qcut(E[col],5,labels=["Q1","Q2","Q3","Q4","Q5"],duplicates="drop")
            print(f"  {lab}")
            print(f"    {'q':<4} {'n':>7} {'P(sustain)':>11} {'mean ret':>10} | "
                  f"{'up n':>6} {'up sus':>7} | {'dn n':>6} {'dn sus':>7}")
            for q in E.q.cat.categories:
                s=E[E.q==q]; u=s[s.dirn>0]; dn=s[s.dirn<0]
                print(f"    {q:<4} {len(s):>7,} {100*s[f'sus{H}'].mean():>10.1f}% "
                      f"{100*s[f'ret{H}'].mean():>9.2f}% | {len(u):>6,} {100*u[f'sus{H}'].mean():>6.1f}% |"
                      f" {len(dn):>6,} {100*dn[f'sus{H}'].mean():>6.1f}%")
            hi=(E[col]>=E[col].quantile(0.8)).to_numpy(); lo=(E[col]<=E[col].quantile(0.2)).to_numpy()
            sub=E[hi|lo].copy(); m=hi[hi|lo]
            for oc in (f"sus{H}",f"ret{H}"):
                b=blockboot(sub,oc,m)
                if len(b)==0: continue
                print(f"      Q5-Q1 on {oc}: {100*np.median(b):+7.3f} "
                      f"[{100*np.percentile(b,5):+.3f},{100*np.percentile(b,95):+.3f}]  "
                      f"P(<=0) {(b<=0).mean():.3f}")
        print()
