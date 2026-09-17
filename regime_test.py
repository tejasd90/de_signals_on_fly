#!/usr/bin/env python3
"""
Q1 REGIMES. Two parts, and the second is the one that decides usability:
  (a) does performance differ by regime?
  (b) HOW SOON can a regime be identified, vs how long it lasts?
A regime you can only name in hindsight is worth nothing.
"""
import json,os,numpy as np,pandas as pd,duckdb
def spot_daily(sp):
    rows=[]
    for fn in sorted(os.listdir(f"data/spot_candles/{sp}/60")):
        try: rows.extend(json.load(open(f"data/spot_candles/{sp}/60/{fn}")))
        except Exception: pass
    a=np.asarray(rows,float); a=a[np.argsort(a[:,0])]
    d=pd.DataFrame({"T":pd.to_datetime(a[:,0],unit="s"),"h":a[:,2],"l":a[:,3],"c":a[:,4]})
    g=d.set_index("T").resample("1D").agg(h=("h","max"),l=("l","min"),c=("c","last")).dropna()
    return g
def label_regime(g):
    """trend = |20d net move| large vs path; sideways = low efficiency. Causal only."""
    ret20=g.c.pct_change(20)
    path=g.c.diff().abs().rolling(20).sum()/g.c
    eff=(g.c-g.c.shift(20)).abs()/g.c/path.replace(0,np.nan)
    r=pd.Series("sideways",index=g.index,dtype=object)
    r[(eff>0.35)&(ret20>0)]="up"
    r[(eff>0.35)&(ret20<0)]="down"
    return r,eff
print("=== (b) REGIME PERSISTENCE vs DETECTION LAG ===")
print("    how many days does a regime last, once you can first name it?\n")
for sp in ["BTC","ETH"]:
    g=spot_daily(sp); r,eff=label_regime(g)
    r=r.dropna()
    blocks=[];cur=None;n=0
    for v in r:
        if v==cur: n+=1
        else:
            if cur is not None: blocks.append((cur,n))
            cur=v;n=1
    blocks.append((cur,n))
    b=pd.DataFrame(blocks,columns=["regime","days"])
    print(f"  {sp}: {len(b)} regime blocks over {len(r)} days")
    print("    " + b.groupby("regime").days.agg(["count","median","mean"]).to_string().replace("\n","\n    "))
    print(f"    detection lag = 20 days (the lookback). median block "
          f"{b.days.median():.0f} days -> usable window "
          f"{max(b.days.median()-20,0):.0f} days\n")
print("=== (a) DOES THE MODEL PERFORM DIFFERENTLY BY REGIME? ===")
c=duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
m=c.execute("""SELECT d.symbol,d.spot,d._ts_hours,d._w,d._peak,d.episode_id,e.stop_ratio
 FROM 'disc_final/*.parquet' d JOIN 'exits/*.parquet' e ON d.symbol=e.symbol
 AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=e.ts""").df()
o=pd.read_parquet("runs/oof_surface_25.parquet")[["symbol","_ts_hours","score"]]
m=m.merge(o,on=["symbol","_ts_hours"],how="inner")
reg={}
for sp in m.spot.unique():
    try:
        g=spot_daily(sp); r,_=label_regime(g)
        reg[sp]=(np.array([x.timestamp() for x in r.index]),r.to_numpy())
    except Exception: pass
def look(sp,th):
    if sp not in reg: return "na"
    ts,vals=reg[sp]; j=np.searchsorted(ts,th*3600)-1
    return vals[j] if 0<=j<len(vals) else "na"
m["reg"]=[look(sp,t) for sp,t in zip(m.spot,m._ts_hours)]
T=25.0
m["R"]=np.where(m._peak>=T,T,m.stop_ratio)-0.05
print(f"\n    {'regime':>10}{'rows':>10}{'25x base':>10}{'top0.5% hit':>13}{'top0.5% EV':>12}")
for rg,g in m.groupby("reg"):
    if len(g)<5000 or rg=="na": continue
    gs=g.sort_values("score",ascending=False)
    cw=np.cumsum(gs._w.to_numpy()); sl=gs[cw<=cw[-1]*0.005]
    if len(sl)<50: continue
    print(f"    {rg:>10}{len(g):>10,}{np.average(g._peak>=T,weights=g._w)*100:>9.3f}%"
          f"{np.average(sl._peak>=T,weights=sl._w)*100:>12.2f}%"
          f"{np.average(sl.R,weights=sl._w)-1:>+12.4f}")
print("\n=== (a2) do the FOUR HAND SIGNALS differ by regime? (otm_wall hypothesis) ===")
try:
    p=c.execute("""SELECT signal, count(*) n FROM 'dataset_parts/*.parquet' GROUP BY 1""").df()
    print(p.to_string(index=False))
except Exception as e:
    print(f"    patterns dataset not queryable here: {str(e)[:80]}")
