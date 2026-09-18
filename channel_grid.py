#!/usr/bin/env python3
"""
channel_grid.py — the same channel-line geometry as channel_lines.py, but built
across a GRID of construction parameters instead of one arbitrary choice.

WHY
CONTEXT_PLAN.md:1060 records the lesson: "one parameterisation of the trend-line
idea tried in one day, which is where false positives come from." The CL AND TL
result at 25x was measured at exactly one setting -- n_swings=4, fractal k=2,
240m. If it only lives there it is noise. If it survives the grid it is geometry.

GRID
  timeframe  60 / 240 / 1440 m
  n_swings   3 / 4 / 6      how many recent swing points the line is fitted to
  fractal k  2 / 3          half-width of the swing window (and the lag applied)

18 combinations, all four break flags each. Naming: cz{tf}_s{n}k{k}_{flag}.

The lookahead rules are unchanged and are per-k: a swing at bar j is known only
at j+k, so swing indices are restricted to <= i-k, and the caller still takes
only bars that CLOSED before entry.
"""
import os, argparse
import numpy as np, pandas as pd
from brooks_context import load_tf, atr, fit_line, TFS

def swings_k(h, l, k):
    n=len(h); sh=np.zeros(n,bool); sl=np.zeros(n,bool)
    for j in range(k, n-k):
        if h[j]==h[j-k:j+k+1].max(): sh[j]=True
        if l[j]==l[j-k:j+k+1].min(): sl[j]=True
    return sh, sl

def lines(h, l, c, A, sh_i, sl_i, n_swings, k):
    n=len(c)
    v={x:np.full(n,np.nan) for x in
       ["bull_tl_break","bull_cl_break","bear_tl_break","bear_cl_break"]}
    for i in range(50, n):
        lo_i = sl_i[sl_i <= i-k][-n_swings:]
        hi_i = sh_i[sh_i <= i-k][-n_swings:]
        if len(lo_i) >= 2:
            b,a0,_ = fit_line(lo_i, l[lo_i])
            if b==b:
                tl=a0+b*i
                v["bull_tl_break"][i]=1.0 if c[i]<tl else 0.0
                if len(hi_i)>=1:
                    off=float(np.nanmax(h[hi_i]-(a0+b*hi_i)))
                    if np.isfinite(off) and off>0:
                        v["bull_cl_break"][i]=1.0 if c[i]>tl+off else 0.0
        if len(hi_i) >= 2:
            b,a0,_ = fit_line(hi_i, h[hi_i])
            if b==b:
                tl=a0+b*i
                v["bear_tl_break"][i]=1.0 if c[i]>tl else 0.0
                if len(lo_i)>=1:
                    off=float(np.nanmax((a0+b*lo_i)-l[lo_i]))
                    if np.isfinite(off) and off>0:
                        v["bear_cl_break"][i]=1.0 if c[i]<tl-off else 0.0
    return v

def build(a, grid):
    ts,o,h,l,c = a[:,0],a[:,1],a[:,2],a[:,3],a[:,4]
    A=atr(h,l,c); A=np.where(A>0,A,np.nan)
    out={"ts":ts}
    for k in sorted({g[1] for g in grid}):
        sh,sl = swings_k(h,l,k)
        sh_i,sl_i = np.where(sh)[0], np.where(sl)[0]
        for n_sw,kk in grid:
            if kk!=k: continue
            for name,arr in lines(h,l,c,A,sh_i,sl_i,n_sw,k).items():
                out[f"s{n_sw}k{k}_{name}"]=arr
    return pd.DataFrame(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out", default="events_cgrid.parquet")
    a=ap.parse_args()
    grid=[(n,k) for n in (3,4,6) for k in (2,3)]
    ev=pd.read_parquet("events.parquet", columns=["spot","entry_ts"]).drop_duplicates()
    parts=[]
    for spot in sorted(ev.spot.unique()):
        e=ev[ev.spot==spot].sort_values("entry_ts").reset_index(drop=True)
        for tf in TFS:
            arr=load_tf(spot,tf)
            if arr is None:
                print(f"  {spot} {tf}m: no data",flush=True); continue
            g=build(arr,grid)
            close_ts=g.ts.to_numpy()+tf*60
            j=np.searchsorted(close_ts, e.entry_ts.to_numpy(), side="right")-1
            ok=j>=0
            blk={}
            for col in [x for x in g.columns if x!="ts"]:
                z=np.full(len(e),np.nan,dtype=np.float32)
                z[ok]=g[col].to_numpy(float)[j[ok]].astype(np.float32)
                blk[f"cz{tf}_{col}"]=z
            e=pd.concat([e,pd.DataFrame(blk,index=e.index)],axis=1)
            print(f"  {spot} {tf}m: {len(g):,} bars -> {len(blk)} cols",flush=True)
        parts.append(e)
    d=pd.concat(parts,ignore_index=True)
    d.to_parquet(a.out,index=False)
    print(f"-> {a.out}  {len(d):,} rows x {len(d.columns)} cols  "
          f"{os.path.getsize(a.out)/1e6:.0f} MB")

if __name__=="__main__": main()
