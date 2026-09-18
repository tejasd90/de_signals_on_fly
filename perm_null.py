#!/usr/bin/env python3
"""
perm_null.py — the family-wise control the placebo could not provide.

WHY THE PLACEBO WAS NOT ENOUGH
Flipping the direction convention gave 0 significant cells out of 896 (min p
0.069) against 62 of 826 for the real arm. That looks decisive, but it is the
wrong null: on a DIRECTIONAL feature the flipped rule is an anti-rule, and it is
guaranteed to look bad if the geometry reads direction at all -- which is beta,
not skill. It says nothing about how many of 826 correlated cells would clear
p<0.05 by chance.

THE RIGHT NULL
Permute the OUTCOME within weeks. That destroys any relationship between
geometry and payoff while preserving (a) the weekly clustering that makes 100x
events lumpy and (b) the exact correlation structure across the 27 parameter
variants. Then rerun the entire grid and record how many cells clear p<0.05 and
what the best p-value is. Comparing the real grid's counts to that distribution
is the family-wise test.

Masks that keep more than KEEP_MAX of events are excluded from both arms: the
structural TL flags keep 73-90% of events, which is not a filter but the
baseline wearing a filter's name.
"""
import numpy as np, pandas as pd
from channel_full import build_events, attach, variants
from rules_test import ev

BOOT=300; KEEP_MIN, KEEP_MAX = 0.02, 0.50; NPERM=25

def p_of(wk, y, m, T, rng, n=BOOT):
    weeks=np.unique(wk); W=len(weeks); idx={w:np.where(wk==w)[0] for w in weeks}
    dev=[]; dpw=[]
    for _ in range(n):
        pick=rng.choice(weeks,W,replace=True)
        sel=np.concatenate([idx[w] for w in pick])
        yy,mm=y[sel],m[sel]
        if mm.sum()<30 or (~mm).sum()<30: continue
        eo,ef=ev(yy[mm].mean(),T), ev(yy.mean(),T)
        dev.append(eo-ef); dpw.append(eo*mm.sum()/W-ef*len(yy)/W)
    if not dev: return None
    return float((np.array(dev)<=0).mean()), float(np.median(dpw))

if __name__=="__main__":
    e=build_events((2.0,20.0)); e=attach(e,["events_cgrid.parquet","events_sch.parquet"])
    V=variants(set(e.columns)); bull=(e.ty=="C").to_numpy()
    wk=e.week.to_numpy()
    masks=[]
    for pre,tag in V:
        bcl=e[f"{pre}_bull_cl{tag}"].to_numpy(); ecl=e[f"{pre}_bear_cl{tag}"].to_numpy()
        btl=e[f"{pre}_bull_tl{tag}"].to_numpy(); etl=e[f"{pre}_bear_tl{tag}"].to_numpy()
        CL=np.where(bull,bcl==1,ecl==1); TL=np.where(bull,etl==1,btl==1)
        for rn,m in (("CL",CL),("TL",TL),("CLandTL",CL&TL)):
            if KEEP_MIN <= m.mean() <= KEEP_MAX: masks.append((f"{pre}|{rn}", m))
    print(f"events {len(e):,}  weeks {e.week.nunique()}  usable masks {len(masks)} "
          f"(keep in [{KEEP_MIN:.0%},{KEEP_MAX:.0%}])", flush=True)

    for T in (25,100):
        y=e[f"h{T}"].to_numpy()
        rng=np.random.default_rng(0)
        real=[p_of(wk,y,m,T,rng) for _,m in masks]
        rs=sum(1 for r in real if r and r[0]<0.05 and r[1]>0)
        rmin=min((r[0] for r in real if r), default=1)
        # permute the outcome WITHIN weeks
        order=np.argsort(wk,kind="stable"); bounds=np.searchsorted(wk[order],np.unique(wk))
        counts=[]; mins=[]
        for s in range(NPERM):
            pr=np.random.default_rng(1000+s)
            yp=y.copy()
            for w in np.unique(wk):
                ix=np.where(wk==w)[0]
                yp[ix]=y[pr.permutation(ix)]
            res=[p_of(wk,yp,m,T,pr) for _,m in masks]
            counts.append(sum(1 for r in res if r and r[0]<0.05 and r[1]>0))
            mins.append(min((r[0] for r in res if r), default=1))
            print(f"   perm {s+1}/{NPERM}: sig {counts[-1]:>3}  min p {mins[-1]:.3f}", flush=True)
        counts=np.array(counts); mins=np.array(mins)
        print(f"\n  TARGET {T}x   REAL: {rs} significant of {len(masks)}, best p {rmin:.4f}")
        print(f"  NULL ({NPERM} within-week permutations): sig count "
              f"median {np.median(counts):.0f}  p95 {np.percentile(counts,95):.0f}  max {counts.max()}")
        print(f"                                           best p  median {np.median(mins):.3f}  "
              f"p05 {np.percentile(mins,5):.3f}  min {mins.min():.4f}")
        print(f"  => family-wise p for the COUNT: {(counts>=rs).mean():.3f}   "
              f"for the BEST CELL: {(mins<=rmin).mean():.3f}\n", flush=True)
