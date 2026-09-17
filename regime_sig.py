#!/usr/bin/env python3
"""Regime significance + otm_wall-by-regime + unsupervised clustering."""
import json,os,numpy as np,pandas as pd,duckdb
def spot_daily(sp):
    rows=[]
    for fn in sorted(os.listdir(f"data/spot_candles/{sp}/60")):
        try: rows.extend(json.load(open(f"data/spot_candles/{sp}/60/{fn}")))
        except Exception: pass
    a=np.asarray(rows,float); a=a[np.argsort(a[:,0])]
    d=pd.DataFrame({"T":pd.to_datetime(a[:,0],unit="s"),"h":a[:,2],"l":a[:,3],"c":a[:,4]})
    return d.set_index("T").resample("1D").agg(h=("h","max"),l=("l","min"),c=("c","last")).dropna()
def regime(g):
    ret20=g.c.pct_change(20)
    path=g.c.diff().abs().rolling(20).sum()/g.c
    eff=(g.c-g.c.shift(20)).abs()/g.c/path.replace(0,np.nan)
    r=pd.Series("sideways",index=g.index,dtype=object)
    r[(eff>0.35)&(ret20>0)]="up"; r[(eff>0.35)&(ret20<0)]="down"
    return r
c=duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
m=c.execute("""SELECT d.symbol,d.spot,d._ts_hours,d._w,d._peak,d.episode_id,e.stop_ratio
 FROM 'disc_final/*.parquet' d JOIN 'exits/*.parquet' e ON d.symbol=e.symbol
 AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=e.ts""").df()
o=pd.read_parquet("runs/oof_surface_25.parquet")[["symbol","_ts_hours","score"]]
m=m.merge(o,on=["symbol","_ts_hours"],how="inner")
R={}
for sp in m.spot.unique():
    try:
        r=regime(spot_daily(sp))
        R[sp]=(np.array([x.timestamp() for x in r.index]),r.to_numpy())
    except Exception: pass
def look(sp,th):
    if sp not in R: return "na"
    ts,v=R[sp]; j=np.searchsorted(ts,th*3600)-1
    return v[j] if 0<=j<len(v) else "na"
m["reg"]=[look(sp,t) for sp,t in zip(m.spot,m._ts_hours)]
T=25.0; m["R"]=np.where(m._peak>=T,T,m.stop_ratio)-0.05
m["blk"]=(m._ts_hours//(24*7)).astype(int)
print("=== regime EV, with block bootstrap on weekly blocks ===")
print(f"    {'regime':>10}{'EV top0.5%':>13}{'95% CI':>26}")
rng=np.random.default_rng(0); store={}
for rg,g in m.groupby("reg"):
    if rg=="na" or len(g)<5000: continue
    gs=g.sort_values("score",ascending=False)
    cw=np.cumsum(gs._w.to_numpy()); sl=gs[cw<=cw[-1]*0.005]
    if len(sl)<50: continue
    rr=sl.R.to_numpy(); ww=sl._w.to_numpy(); bb=sl.blk.to_numpy(); ub=np.unique(bb)
    mu=[]
    for _ in range(2000):
        pk=rng.choice(ub,len(ub),replace=True)
        sel=np.isin(bb,pk)
        if sel.sum()>30: mu.append(np.average(rr[sel],weights=ww[sel])-1)
    mu=np.array(mu); store[rg]=mu
    print(f"    {rg:>10}{np.average(rr,weights=ww)-1:>+13.4f}"
          f"   [{np.percentile(mu,2.5):+.4f},{np.percentile(mu,97.5):+.4f}]")
if "down" in store and "sideways" in store:
    d=np.array(store["down"])-np.array(store["sideways"][:len(store["down"])])
    print(f"\n    down MINUS sideways: P(difference <= 0) = {(d<=0).mean():.3f}")
print("\n=== YOUR HYPOTHESIS: does otm_wall do better in SIDEWAYS? ===")
try:
    p=c.execute("""SELECT signal, spot, _ts_hours, ratio, _w FROM 'dataset_parts/*.parquet'
                   WHERE ratio IS NOT NULL""").df()
    p["reg"]=[look(s,t) for s,t in zip(p.spot,p._ts_hours)]
    print(f"    {'signal':>16}{'regime':>10}{'n':>9}{'10x rate':>10}{'25x rate':>10}")
    for (sg,rg),g in p.groupby(["signal","reg"]):
        if rg=="na" or len(g)<400: continue
        print(f"    {sg:>16}{rg:>10}{len(g):>9,}"
              f"{np.average(g.ratio>=10,weights=g._w)*100:>9.2f}%"
              f"{np.average(g.ratio>=25,weights=g._w)*100:>9.2f}%")
except Exception as e:
    print(f"    could not load patterns dataset: {str(e)[:100]}")
