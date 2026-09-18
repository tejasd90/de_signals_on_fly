#!/usr/bin/env python3
"""
channel_full.py — the complete test of Tejas's channel-line claim.

WHAT WENT WRONG THE FIRST TIME
CL AND TL was measured at exactly ONE construction (4 local swings, 240m) and
came out at P=0.025. The diagnostic then showed that construction never fired
during 10-11 Oct 2025 -- the episode the claim came from. A rule that misses its
own motivating example, at one untested parameter setting, is a candidate false
positive, not a finding.

WHAT THIS DOES
1. GRID, not a point. Every channel construction available is tested:
   local least-squares (channel_grid.py, 18 settings) AND structural hull lines
   (structural_channels.py, 9 settings x timeframe/lookback/prominence).
2. PLACEBO of identical size. Every rule is re-run with the direction convention
   FLIPPED -- calls demand the put-side break and vice versa. Under the null
   that these breaks carry no directional information, the placebo grid must
   produce significant cells at the same rate as the real grid. Comparing the
   two counts is the family-wise control; a single P=0.025 among 100 cells is
   not evidence, a 10:1 excess over the matched placebo is.
3. BOTH numbers, always: dEV per trade AND profit per week (trap #10).
4. OUT OF SAMPLE BY TIME. 2024-25 is the discovery sample, 2026 is held out and
   reported separately. Nothing is selected on 2026.
5. Weekly block bootstrap throughout -- weeks are the unit of independence.
"""
import os, glob, itertools
import numpy as np, pandas as pd
from rules_test import ev, fwd_spot_return, COST

BOOT = 1000

def boot_p(df, mask, T, n=BOOT, seed=0):
    rng=np.random.default_rng(seed)
    wk=df.week.to_numpy(); y=df[f"h{T}"].to_numpy(); m=np.asarray(mask,bool)
    weeks=np.unique(wk); W=len(weeks)
    idx={w:np.where(wk==w)[0] for w in weeks}
    dev=[]; dpw=[]
    for _ in range(n):
        pick=rng.choice(weeks,W,replace=True)
        sel=np.concatenate([idx[w] for w in pick])
        yy,mm=y[sel],m[sel]
        if mm.sum()<30 or (~mm).sum()<30: continue
        e_on,e_off=ev(yy[mm].mean(),T), ev(yy.mean(),T)
        dev.append(e_on-e_off); dpw.append(e_on*mm.sum()/W - e_off*len(yy)/W)
    if not dev: return None
    dev=np.array(dev); dpw=np.array(dpw)
    return dict(dev=float(np.median(dev)), dpw=float(np.median(dpw)),
                p=float((dev<=0).mean()))

def build_events(band):
    d=pd.read_parquet("events.parquet", columns=[
        "spot","opt_type","entry_ts","event_id","activated","entry_premium",
        "peak_vs_trigger","peak_vs_close"])
    d=d[d.activated & d.spot.isin(["BTC","ETH"])].copy()
    d["r"]=d.peak_vs_trigger.fillna(d.peak_vs_close)
    d=d.dropna(subset=["r","entry_premium"])
    d=d[d.entry_premium.between(*band)]
    for T in (25,100): d[f"y{T}"]=(d.r>=T).astype(float)
    agg={"ty":("opt_type","first"),"ts":("entry_ts","first"),
         "h25":("y25","mean"),"h100":("y100","mean"),"spot":("spot","first")}
    e=d.groupby("event_id").agg(**agg).reset_index()
    e["week"]=((e.ts+19800)//604800).astype(int)
    e["year"]=pd.to_datetime(e.ts,unit="s").dt.year
    return e

def attach(e, files):
    for fp in files:
        if not os.path.exists(fp): continue
        f=pd.read_parquet(fp)
        e=e.merge(f, left_on=["spot","ts"], right_on=["spot","entry_ts"], how="left")
        if "entry_ts" in e.columns: e=e.drop(columns=["entry_ts"])
    return e

def variants(cols):
    """Every (prefix) that has all four break flags present."""
    out=[]
    for c in cols:
        for suf in ("_bull_cl_break","_bull_cl_broken"):
            if c.endswith(suf):
                pre=c[:-len(suf)]
                tag="_break" if suf.endswith("break") else "_broken"
                need=[f"{pre}_{a}_{b}{tag}" for a in ("bull","bear") for b in ("cl","tl")]
                if all(x in cols for x in need): out.append((pre,tag))
    return sorted(set(out))

if __name__=="__main__":
    import sys
    rows=[]
    for band in [(0.1,2.0),(2.0,20.0)]:
        e=build_events(band)
        e=attach(e, ["events_cgrid.parquet","events_sch.parquet"])
        V=variants(set(e.columns))
        print(f"\nband {band}  events {len(e):,}  weeks {e.week.nunique()}  "
              f"variants {len(V)}  base25 {100*e.h25.mean():.2f}%  base100 {100*e.h100.mean():.3f}%",
              flush=True)
        bull=(e.ty=="C").to_numpy()
        for pre,tag in V:
            bcl=e[f"{pre}_bull_cl{tag}"].to_numpy(); ecl=e[f"{pre}_bear_cl{tag}"].to_numpy()
            btl=e[f"{pre}_bull_tl{tag}"].to_numpy(); etl=e[f"{pre}_bear_tl{tag}"].to_numpy()
            # REAL: call wants upside break, put wants downside break
            CL=np.where(bull, bcl==1, ecl==1); TL=np.where(bull, etl==1, btl==1)
            # PLACEBO: direction flipped. Same geometry, wrong side.
            CLp=np.where(bull, ecl==1, bcl==1); TLp=np.where(bull, btl==1, etl==1)
            for arm,(cl,tl) in {"real":(CL,TL),"placebo":(CLp,TLp)}.items():
                for rname,m in {"CL":cl,"TL":tl,"CLandTL":cl&tl}.items():
                    for T in (25,100):
                        for scope,sub in {"all":e,"disc2024_25":e[e.year<2026],
                                          "oos2026":e[e.year==2026]}.items():
                            mm=pd.Series(m,index=e.index).loc[sub.index].to_numpy()
                            if mm.sum()<150 or (~mm).sum()<150: continue
                            r=boot_p(sub, mm, T)
                            if r is None: continue
                            rows.append(dict(band=f"{band[0]}-{band[1]}", variant=pre,
                                arm=arm, rule=rname, T=T, scope=scope,
                                keep=100*mm.mean(), hit=100*sub[f"h{T}"].to_numpy()[mm].mean(),
                                base=100*sub[f"h{T}"].mean(), **r))
            print(f"  {pre} done ({len(rows)} cells)", flush=True)
    R=pd.DataFrame(rows); R.to_csv("channel_full_results.csv", index=False)
    print(f"\nwrote channel_full_results.csv  {len(R):,} cells")
