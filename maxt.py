#!/usr/bin/env python3
"""
maxt.py — Westfall-Young maxT family-wise test. Supersedes the count-based
control in perm_null.py, which used the wrong statistic.

WHAT WENT WRONG IN perm_null.py
It counted cells with BOOTSTRAP p < 0.05 under within-week permutation and found
the null grid produced as many as the real grid, concluding "no effect". But the
bootstrap p tests dEV > 0, and under within-week permutation dEV is NOT centred
on zero -- measured null medians were +0.098 (R4), +0.143 (CL), +0.184 (CL&TL).
These masks fire more often in weeks when options paid anyway, so a test of
"dEV > 0" flags null cells constantly. The count comparison was therefore
measuring week-concentration, not selection skill, in BOTH arms.

THE RIGHT TEST
Standardise every cell against its OWN permutation null:
    z_c = (dEV_c - mean_c) / sd_c
then compare the real max-z across all cells to the distribution of max-z from
the same permutations. That is Westfall-Young: it controls family-wise error
across correlated hypotheses without assuming independence, and it automatically
absorbs the per-cell bias that broke the previous version.

R4 is included as a positive control. If the procedure cannot detect R4 it is
too strict and its verdict on the channel lines means nothing.
"""
import numpy as np, pandas as pd
from channel_full import build_events, attach, variants
from rules_test import ev

NPERM=400; KEEP_MIN,KEEP_MAX=0.02,0.50

def dev(y,m,T): return ev(y[m].mean(),T)-ev(y.mean(),T)

if __name__=="__main__":
    e=build_events((2.0,20.0)); e=attach(e,["events_cgrid.parquet","events_sch.parquet"])
    ai=pd.concat([pd.read_parquet(f"events_ctx/{s}.parquet",
                  columns=["event_id","cx240_always_in"]) for s in ("BTC","ETH")])
    ai=ai.groupby("event_id").first().reset_index()
    e=e.merge(ai,on="event_id",how="left")
    bull=(e.ty=="C").to_numpy(); wk=e.week.to_numpy()
    names=[]; M=[]
    # positive control first
    r4=np.where(bull,e.cx240_always_in==1,e.cx240_always_in==-1)
    names.append("R4 always-in [CONTROL]"); M.append(r4)
    for pre,tag in variants(set(e.columns)):
        bcl=e[f"{pre}_bull_cl{tag}"].to_numpy(); ecl=e[f"{pre}_bear_cl{tag}"].to_numpy()
        btl=e[f"{pre}_bull_tl{tag}"].to_numpy(); etl=e[f"{pre}_bear_tl{tag}"].to_numpy()
        CL=np.where(bull,bcl==1,ecl==1); TL=np.where(bull,etl==1,btl==1)
        for rn,m in (("CL",CL),("TL",TL),("CLandTL",CL&TL)):
            if KEEP_MIN<=m.mean()<=KEEP_MAX: names.append(f"{pre}|{rn}"); M.append(m)
    M=np.array(M); print(f"events {len(e):,}  weeks {len(np.unique(wk))}  cells {len(M)}",flush=True)
    weeks=np.unique(wk); idx=[np.where(wk==w)[0] for w in weeks]
    for T in (25,100):
        y=e[f"h{T}"].to_numpy()
        real=np.array([dev(y,m,T) for m in M])
        rng=np.random.default_rng(11)
        null=np.empty((NPERM,len(M)))
        for s in range(NPERM):
            yp=y.copy()
            for ix in idx: yp[ix]=y[rng.permutation(ix)]
            null[s]=[dev(yp,m,T) for m in M]
            if (s+1)%100==0: print(f"   {T}x perm {s+1}/{NPERM}",flush=True)
        mu=null.mean(0); sd=null.std(0); sd=np.where(sd>0,sd,np.nan)
        z=(real-mu)/sd
        zn=(null-mu)/sd
        maxz=np.nanmax(zn,axis=1)
        print(f"\n=== TARGET {T}x — Westfall-Young maxT over {len(M)} cells, {NPERM} perms ===")
        order=np.argsort(-z)
        print(f"{'cell':<26} {'keep':>6} {'dEV':>8} {'nullmu':>8} {'z':>7} {'FWER p':>8}")
        for i in order[:12]:
            fw=(maxz>=z[i]).mean()
            print(f"{names[i]:<26} {100*M[i].mean():5.2f}% {real[i]:>+8.3f} {mu[i]:>+8.3f} "
                  f"{z[i]:>7.2f} {fw:>8.3f} {'**' if fw<0.05 else ''}")
        nsig=sum(1 for i in range(len(M)) if (maxz>=z[i]).mean()<0.05)
        print(f"  cells surviving family-wise correction: {nsig} of {len(M)}")
        ch=[i for i in range(len(M)) if names[i]!="R4 always-in [CONTROL]"]
        bi=max(ch,key=lambda i:z[i])
        print(f"  best CHANNEL cell: {names[bi]}  z {z[bi]:.2f}  FWER p {(maxz>=z[bi]).mean():.3f}")
