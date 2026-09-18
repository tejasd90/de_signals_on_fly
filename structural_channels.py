#!/usr/bin/env python3
"""
structural_channels.py — channel lines on the STRUCTURAL trend lines.

WHY THIS REPLACES channel_lines.py
The first attempt fitted the channel to the last 4 fractal swings on a 240m
series -- roughly ten days of structure. Tejas's charts draw lines spanning
MONTHS (mid-Aug to Nov, Dec to Mar), and he stressed that the line mattered
BECAUSE it was "more than 10 months old". The diagnostic confirmed the
mismatch: the local CL AND TL rule never fired once during 10-11 Oct 2025, the
very episode he attributed to a channel-line break.

structural_lines.py already solved this for the trend line -- major swings with
an ATR prominence floor, a convex HULL rather than least squares, and the
LONGEST sloping segment rather than the newest. It just never built the
parallel return line. That is what this adds:

    bear line  = upper hull of major swing highs, descending
    bear CHANNEL = that line translated DOWN by the deepest any confirmed swing
                   LOW sat below it, measured over the line's own span
    bear_cl_broken = close BELOW the channel line   <- the downside breakout

    bull line / bull CHANNEL are the mirror; bull_cl_broken = close ABOVE it.

LOOKBACK MUST MATCH THE TIMEFRAME
A 10-month line is ~300 bars on daily, ~1,800 on 240m, ~7,300 on 60m. The old
lookback=250 could not see it outside daily. Lookbacks are set per timeframe so
every view can actually contain a multi-month line.

LINE AGE IS KEPT, not thrown away. Tejas's claim is specifically about OLD
lines, so span is stored and tested as a condition rather than assumed.

SEGMENT SELECTION -- FIXED 2026-09-18
structural_lines.py picks the LONGEST sloping hull segment. Measured on BTC, that
rule degenerates: the returned span equalled the lookback on essentially every
bar (239/243/235/232/241 at lb250; 393/380/400/396/395 at lb400), i.e. it was
selecting the window edge, not a structure. At lb400 the extrapolation went
NEGATIVE on 18 of 72 bars while reporting "broken" throughout.

A trader picks the line price has RESPECTED, not the oldest anchor available. So
segments are now scored by how many confirmed swings TOUCH them (within 0.5 ATR),
with span only as a tie-break, and a line is treated as not in force at all if
its extrapolated level is non-positive or further than MAX_EXT ATR from price.

Causal: swings confirmed at j+k, only confirmed hull points used at bar i, and
the caller still takes only bars CLOSED before entry.
"""
import os, argparse
import numpy as np, pandas as pd
from structural_lines import atr_, major_swings, _upper_hull, _lower_hull
from brooks_context import load_tf


MAX_EXT = 10.0     # a line >10 ATR from price is not being respected; not "in force"

def _level(sg, x):
    (x1,y1),(x2,y2) = sg
    return y2 + (y2-y1)/(x2-x1)*(x-x2)

def _ok(sg, i, ext, idxs, atr, close):
    """A line only counts if its extrapolation to bar i is a sane price that is
    still anywhere near the market. Without this the long-lookback lines ran to
    negative prices and reported 'broken' on every bar."""
    if not np.isfinite(atr) or atr <= 0: return False
    lv = _level(sg, i)
    return lv > 0 and abs(lv - close)/atr <= MAX_EXT

def _score(sg, ext, idxs, atr):
    """Touches first, span second. A trend line is the one price came back to."""
    if not np.isfinite(atr) or atr <= 0: return (0, 0)
    (x1,_),(x2,_) = sg
    t = sum(1 for j in idxs if x1 <= j <= x2
            and abs(ext[j] - _level(sg, j))/atr < 0.5)
    return (t, x2 - x1)

def lines_ch(a, k=5, min_prom=1.0, lookback=250, confirm=None):
    ts, o, h, l, c = a[:,0], a[:,1], a[:,2], a[:,3], a[:,4]
    n = len(c); A = atr_(h,l,c); A = np.where(A>0, A, np.nan)
    if confirm is None: confirm = k
    sh, sl = major_swings(h, l, k, min_prom, A)
    shi, sli = np.where(sh)[0], np.where(sl)[0]
    keys = ("bear_tl_broken","bear_cl_broken","bear_span","bear_chanw","bear_dist",
            "bull_tl_broken","bull_cl_broken","bull_span","bull_chanw","bull_dist")
    out = {x: np.full(n, np.nan) for x in keys}
    for i in range(60, n):
        lo_i = i - lookback
        H = shi[(shi <= i-confirm) & (shi >= lo_i)]
        L = sli[(sli <= i-confirm) & (sli >= lo_i)]
        if len(H) >= 2:
            hull = _upper_hull(list(H), [h[j] for j in H])
            segs = [(hull[q],hull[q+1]) for q in range(len(hull)-1)
                    if hull[q+1][0] > hull[q][0] and hull[q+1][1] <= hull[q][1]]
            segs = [sg for sg in segs if _ok(sg, i, h, H, A[i], c[i])]
            if segs:
                (x1,y1),(x2,y2) = max(segs, key=lambda sg: _score(sg, h, H, A[i]))
                if x2 > x1:
                    m = (y2-y1)/(x2-x1); line = y2 + m*(i-x2)
                    out["bear_tl_broken"][i] = 1.0 if c[i] > line else 0.0
                    out["bear_span"][i] = i - x1
                    out["bear_dist"][i] = (c[i]-line)/A[i]
                    # return line: deepest confirmed swing low below the line,
                    # measured only over the span the line itself covers
                    Ls = L[L >= x1]
                    if len(Ls):
                        off = float(np.nanmax((y2 + m*(Ls-x2)) - l[Ls]))
                        if np.isfinite(off) and off > 0:
                            out["bear_chanw"][i] = off/A[i]
                            out["bear_cl_broken"][i] = 1.0 if c[i] < line-off else 0.0
        if len(L) >= 2:
            hull = _lower_hull(list(L), [l[j] for j in L])
            segs = [(hull[q],hull[q+1]) for q in range(len(hull)-1)
                    if hull[q+1][0] > hull[q][0] and hull[q+1][1] >= hull[q][1]]
            segs = [sg for sg in segs if _ok(sg, i, l, L, A[i], c[i])]
            if segs:
                (x1,y1),(x2,y2) = max(segs, key=lambda sg: _score(sg, l, L, A[i]))
                if x2 > x1:
                    m = (y2-y1)/(x2-x1); line = y2 + m*(i-x2)
                    out["bull_tl_broken"][i] = 1.0 if c[i] < line else 0.0
                    out["bull_span"][i] = i - x1
                    out["bull_dist"][i] = (c[i]-line)/A[i]
                    Hs = H[H >= x1]
                    if len(Hs):
                        off = float(np.nanmax(h[Hs] - (y2 + m*(Hs-x2))))
                        if np.isfinite(off) and off > 0:
                            out["bull_chanw"][i] = off/A[i]
                            out["bull_cl_broken"][i] = 1.0 if c[i] > line+off else 0.0
    g = pd.DataFrame(out); g.insert(0,"ts",ts); return g

# lookback chosen so each timeframe can actually hold a multi-month line
GRID = [(60,  2000, 5, 1.0), (60,  4000, 8, 1.0),
        (240, 500,  5, 1.0), (240, 1500, 5, 1.0), (240, 1500, 8, 1.0), (240, 1500, 5, 0.5),
        (1440,250,  5, 1.0), (1440,400,  5, 1.0), (1440,400,  3, 1.0)]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out", default="events_sch.parquet")
    a=ap.parse_args()
    ev=pd.read_parquet("events.parquet", columns=["spot","entry_ts"]).drop_duplicates()
    parts=[]
    for spot in sorted(ev.spot.unique()):
        e=ev[ev.spot==spot].sort_values("entry_ts").reset_index(drop=True)
        for tf, lb, k, mp in GRID:
            arr=load_tf(spot, tf)
            if arr is None: continue
            g=lines_ch(arr, k=k, min_prom=mp, lookback=lb)
            close_ts=g.ts.to_numpy()+tf*60
            j=np.searchsorted(close_ts, e.entry_ts.to_numpy(), side="right")-1
            ok=j>=0
            tag=f"sc{tf}_l{lb}k{k}p{str(mp).replace('.','')}"
            blk={}
            for col in [x for x in g.columns if x!="ts"]:
                z=np.full(len(e),np.nan,dtype=np.float32)
                z[ok]=g[col].to_numpy(float)[j[ok]].astype(np.float32)
                blk[f"{tag}_{col}"]=z
            e=pd.concat([e,pd.DataFrame(blk,index=e.index)],axis=1)
            print(f"  {spot} tf{tf} lb{lb} k{k} p{mp}: {len(g):,} bars", flush=True)
        parts.append(e)
    d=pd.concat(parts,ignore_index=True); d.to_parquet(a.out,index=False)
    print(f"-> {a.out}  {len(d):,} x {len(d.columns)}  {os.path.getsize(a.out)/1e6:.0f} MB")

if __name__=="__main__": main()
