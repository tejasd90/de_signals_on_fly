#!/usr/bin/env python3
"""
term_structure.py — the CROSS-EXPIRY features discover_build never computed.

discover_build fits log(premium) vs strike inside one expiry dir, so every
surf_ feature is within-expiry. This adds the second axis: at each instant,
how does the SAME moneyness price across the live expiries?

Pass 1: per (spot, expiry, ts) summarise the chain -> premium interpolated at
        fixed moneyness points, plus the within-expiry skew/curv already known.
Pass 2: per (spot, ts) fit log(premium) vs log(tte) ACROSS expiries at matched
        moneyness. The per-expiry RESIDUAL from that fit is the headline
        feature: "is my expiry rich or cheap versus the rest of the board".

No lookahead: everything is measured at the instant, nothing forward-looking.
"""
import json,os,sys,time,glob
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

MNY=[0.0,2.5,5.0,10.0]          # % OTM points to evaluate each expiry at

def spot_series(spot):
    rows=[]
    for fn in sorted(os.listdir(f"data/spot_candles/{spot}/60")):
        try: rows.extend(json.load(open(f"data/spot_candles/{spot}/60/{fn}")))
        except Exception: pass
    a=np.asarray(rows,float); a=a[np.argsort(a[:,0])]
    _,k=np.unique(a[:,0],return_index=True); a=a[np.sort(k)]
    return a[:,0],a[:,4]

def do_expiry(job):
    spot,exp,d,st,sv=job
    try: exp_ts=pd.Timestamp(exp).timestamp()+12*3600
    except Exception: return []
    files=[f for f in os.listdir(d) if f.endswith(".json")]
    if len(files)<6: return []
    series={}
    for fn in files:
        p=fn[:-5].split("-")
        if len(p)<4: continue
        try: k=float(p[2])
        except ValueError: continue
        try: a=np.asarray(json.load(open(os.path.join(d,fn))),float)
        except Exception: continue
        if a.ndim!=2 or len(a)<3: continue
        series[(p[0].upper(),k)]=a
    if not series: return []
    grid=np.unique(np.concatenate([a[:,0] for a in series.values()]))
    if len(grid)<5: return []
    out=[]
    # build type -> (strikes, matrix[strike, time])
    for typ in ("C","P"):
        items=[(k,a) for (t,k),a in series.items() if t==typ]
        if len(items)<5: continue
        ks=np.array([k for k,_ in items],float)
        mat=np.full((len(items),len(grid)),np.nan)
        for i,(k,a) in enumerate(items):
            pos=np.searchsorted(grid,a[:,0]); pos=np.clip(pos,0,len(grid)-1)
            mat[i,pos]=a[:,4]
        o=np.argsort(ks); ks=ks[o]; mat=mat[o]
        sj=np.searchsorted(st,grid); sj=np.clip(sj,0,len(sv)-1)
        spx=sv[sj]
        for ti in range(len(grid)):
            ps=mat[:,ti]; S=spx[ti]
            ok=np.isfinite(ps)&(ps>0)&np.isfinite(S)&(S>0)
            if ok.sum()<5: continue
            k_,p_=ks[ok],ps[ok]
            mny=(k_-S)/S*100.0 if typ=="C" else (S-k_)/S*100.0
            srt=np.argsort(mny); mny=mny[srt]; lp=np.log(p_[srt])
            tte=(exp_ts-grid[ti])/3600.0
            if tte<=1: continue
            rec={"spot":spot,"expiry":exp,"ts":int(grid[ti]),"typ":typ,
                 "tte":tte,"nk":int(ok.sum())}
            for m in MNY:
                rec[f"p{m:g}"]=float(np.exp(np.interp(m,mny,lp))/S) if (mny.min()<=m<=mny.max()) else np.nan
            try:
                c2,c1,c0=np.polyfit((mny-mny.mean())/max(mny.std(),1e-9),lp,2)
                rec["skew"]=float(c1); rec["curv"]=float(c2)
            except Exception:
                rec["skew"]=np.nan; rec["curv"]=np.nan
            out.append(rec)
    return out

if __name__=="__main__":
    jobs=[]; sp_cache={}
    for spot in sorted(os.listdir("data/candles")):
        sd=f"data/candles/{spot}"
        if not os.path.isdir(sd): continue
        if not os.path.isdir(f"data/spot_candles/{spot}/60"): continue
        st,sv=spot_series(spot); sp_cache[spot]=(st,sv)
        for exp in sorted(os.listdir(sd)):
            d=os.path.join(sd,exp,"60")
            if os.path.isdir(d): jobs.append((spot,exp,d,st,sv))
    print(f"{len(jobs)} (spot,expiry) chains",flush=True)
    t0=time.time(); rows=[]; part=0
    os.makedirs("term_parts",exist_ok=True)
    with ProcessPoolExecutor(5) as ex:
        for i,r in enumerate(ex.map(do_expiry,jobs,chunksize=4),1):
            rows.extend(r)
            if len(rows)>400_000:
                pd.DataFrame(rows).to_parquet(f"term_parts/p{part:04d}.parquet",index=False)
                part+=1; rows=[]
            if i%200==0:
                el=time.time()-t0
                print(f"  {i}/{len(jobs)} | {el/60:.1f}m | eta {el/i*(len(jobs)-i)/60:.1f}m",flush=True)
    if rows: pd.DataFrame(rows).to_parquet(f"term_parts/p{part:04d}.parquet",index=False)
    print(f"done {(time.time()-t0)/60:.1f}m -> term_parts/")
