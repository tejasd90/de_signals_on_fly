#!/usr/bin/env python3
"""
coil_test.py — does volatility compression predict the NEXT big move?

Tejas's claim (2026-09-12): the Aug 19 squeeze was telegraphed by an extreme
coil on Aug 15-18. Verified for that instance (Aug 15 range = 1.1st percentile
of 90 days). Question now: does it generalise?

H1 MAGNITUDE: does an extreme-low range percentile predict a large move soon?
H2 DIRECTION: conditional on a coil, is the BREAK DIRECTION predictable?

H1 is the well-known volatility-clustering effect and should hold. H2 is the one
that decides whether you can pre-position instead of chase -- a coil that breaks
either way is only tradeable with a straddle, which we retired.

Blocked bootstrap on time; 129 perps share market-wide moves.
"""
import glob,os,numpy as np,pandas as pd
K=10           # forward window, days
rows=[]
for p in sorted(glob.glob("data/perp_candles/*.parquet")):
    s=os.path.basename(p)[:-8]
    d=pd.read_parquet(p)
    if len(d)<24*400: continue
    d["T"]=pd.to_datetime(d.ts,unit="s")
    g=d.set_index("T").resample("1D").agg(o=("o","first"),h=("h","max"),l=("l","min"),
                                          c=("c","last"),v=("v","sum")).dropna()
    if len(g)<200: continue
    g["rng"]=(g.h-g.l)/g.l
    g["pct"]=g.rng.rolling(90).rank(pct=True)          # compression: low = coiled
    g["volz"]=(g.v-g.v.rolling(20).mean())/g.v.rolling(20).std()
    tr=np.maximum(g.h-g.l,np.maximum((g.h-g.c.shift()).abs(),(g.l-g.c.shift()).abs()))
    g["atr"]=tr.rolling(20).mean()/g.c
    # forward: max favourable/adverse excursion over K days, in % of close
    fh=g.h.shift(-1).rolling(K).max().shift(-(K-1))
    fl=g.l.shift(-1).rolling(K).min().shift(-(K-1))
    g["up"]=(fh-g.c)/g.c
    g["dn"]=(g.c-fl)/g.c
    g["absmove"]=np.maximum(g.up,g.dn)
    g["signed"]=np.where(g.up>g.dn,1,0)                 # which side broke further
    g["ret3"]=g.c.pct_change(3)                         # prior push (directional clue)
    g["sym"]=s
    rows.append(g.reset_index()[["T","sym","pct","volz","atr","up","dn","absmove","signed","ret3"]])
x=pd.concat(rows,ignore_index=True).dropna()
print(f"observations: {len(x):,} symbol-days | symbols {x.sym.nunique()}\n")
print("=== H1 MAGNITUDE: forward 10-day max move, by TODAY's range percentile ===")
x["bin"]=pd.cut(x.pct,[0,.05,.10,.25,.50,.75,1.0],
                labels=["<5th","5-10th","10-25th","25-50th","50-75th",">75th"])
t=x.groupby("bin",observed=True).agg(n=("absmove","size"),
      med_move=("absmove","median"),mean_move=("absmove","mean"),
      p90=("absmove",lambda v:np.percentile(v,90)),atr=("atr","median"))
t["move_in_ATR"]=t.med_move/t.atr
print(t.to_string(float_format=lambda v:f"{v:,.4f}"))
print("\n  -> if coiled days had BIGGER forward moves, med_move would rise as the")
print("     percentile falls. Compare 'move_in_ATR' which normalises for regime.")
print("\n=== H2 DIRECTION: given a coil (<10th pct), which way does it break? ===")
c=x[x.pct<0.10].copy()
print(f"  coiled observations: {len(c):,}")
print(f"  broke UP further: {c.signed.mean()*100:.1f}%   (50% = no directional info)")
print(f"\n  split by the PRIOR 3-day push (the Aug 17 'accumulation' clue):")
c["push"]=pd.cut(c.ret3,[-1,-0.05,-0.02,0.02,0.05,1],
                 labels=["<-5%","-5..-2%","flat","+2..+5%",">+5%"])
print(c.groupby("push",observed=True).agg(n=("signed","size"),
      broke_up_pct=("signed",lambda v:v.mean()*100),
      med_up=("up","median"),med_dn=("dn","median")).to_string(
      float_format=lambda v:f"{v:,.3f}"))
print("\n  split by VOLUME z-score during the coil:")
c["vz"]=pd.cut(c.volz,[-9,-1,0,1,9],labels=["<-1 (dry)","-1..0","0..1",">1 (heavy)"])
print(c.groupby("vz",observed=True).agg(n=("signed","size"),
      broke_up_pct=("signed",lambda v:v.mean()*100),
      med_absmove=("absmove","median")).to_string(float_format=lambda v:f"{v:,.3f}"))
