#!/usr/bin/env python3
"""
Do SUCCESSES CLUSTER? If yes, pressing a winner into the next trade beats flat
staking. If outcomes are iid, every staking scheme has identical expectancy and
only variance changes — so this is the whole question.

Criterion: P(win | previous win) > P(win), tested per instrument-stream so we
never chain across unrelated symbols.
"""
import numpy as np,pandas as pd,duckdb
from scipy import stats
c=duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
m=c.execute("""SELECT d.symbol,d.spot,d._ts_hours,d._w,d._peak,d.episode_id,d.tteHours,
 e.stop_ratio FROM 'disc_final/*.parquet' d JOIN 'exits/*.parquet' e
 ON d.symbol=e.symbol AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=e.ts
""").df()
o=pd.read_parquet("runs/oof_surface_25.parquet")[["symbol","_ts_hours","score"]]
m=m.merge(o,on=["symbol","_ts_hours"],how="inner")
T=25.0
# merged 1-D trade = one EPISODE: take the top-K real contracts by score, basket return
d=m.sort_values(["episode_id","score"],ascending=[True,False]).copy()
d["cw"]=d.groupby("episode_id")._w.cumsum()
s=d[d.cw-d._w<10].copy(); s["wt"]=np.minimum(s._w,10)
s["R"]=np.where(s._peak>=T,T,s.stop_ratio)-0.05
ep=s.groupby("episode_id").apply(lambda x: pd.Series({
    "R":np.average(x.R,weights=x.wt),"t":x._ts_hours.min(),"spot":x.spot.iloc[0]}),
    include_groups=False).reset_index().sort_values("t")
ep["win"]=(ep.R>1).astype(int)
print(f"merged 1-D trades (episodes): {len(ep):,}  |  base win rate {ep.win.mean()*100:.2f}%\n")
print("=== DO WINS CLUSTER? per-underlying sequence, no chaining across symbols ===")
rows=[]
for sp,g in ep.groupby("spot"):
    g=g.sort_values("t"); w=g.win.to_numpy()
    if len(w)<60: continue
    prev,cur=w[:-1],w[1:]
    pw=cur.mean()
    p_ww=cur[prev==1].mean() if (prev==1).any() else np.nan
    p_wl=cur[prev==0].mean() if (prev==0).any() else np.nan
    # runs test for randomness
    runs=1+np.sum(w[1:]!=w[:-1]); n1,n0=w.sum(),len(w)-w.sum()
    exp_r=1+2*n1*n0/len(w); var_r=(exp_r-1)*(exp_r-2)/max(len(w)-1,1)
    z=(runs-exp_r)/np.sqrt(max(var_r,1e-9))
    rows.append((sp,len(w),pw,p_ww,p_wl,p_ww-pw,z,
                 np.corrcoef(prev,cur)[0,1] if len(prev)>3 else np.nan))
r=pd.DataFrame(rows,columns=["spot","n","P(win)","P(win|win)","P(win|loss)",
                             "lift","runs_z","lag1_corr"])
print(r.to_string(index=False,float_format=lambda v:f"{v:,.4f}"))
print("\n  runs_z < 0 => fewer runs than random => CLUSTERED")
print("  lift > 0   => a win makes the next win more likely")
# pooled significance via block bootstrap on time
allw=[];allp=[]
for sp,g in ep.groupby("spot"):
    w=g.sort_values("t").win.to_numpy()
    if len(w)<60: continue
    allp.append(w[:-1]); allw.append(w[1:])
prev=np.concatenate(allp); cur=np.concatenate(allw)
lift=cur[prev==1].mean()-cur.mean()
rng=np.random.default_rng(0); null=[]
for _ in range(5000):
    pp=rng.permutation(prev)
    null.append(cur[pp==1].mean()-cur.mean())
null=np.array(null)
print(f"\n  POOLED: P(win)={cur.mean()*100:.2f}%  P(win|win)={cur[prev==1].mean()*100:.2f}%"
      f"  lift={lift*100:+.2f}pp")
print(f"  permutation null: mean {null.mean()*100:+.3f}pp sd {null.std()*100:.3f}pp")
print(f"  p-value (lift <= 0 by chance): {(null>=lift).mean():.4f}")
print("\n=== same question on the FUTURES trades (cleaner outcomes) ===")
import glob,os,sys
sys.path.insert(0,".")
from pyramid_backtest import daily,backtest
G={}
for p in sorted(glob.glob("data/perp_candles/*.parquet"))[:60]:
    g=daily(p)
    if g is not None: G[os.path.basename(p)[:-8]]=g
tr=[]
for sname,g in G.items():
    for t in backtest(g,20,1,3.0,0.0004,0.0001,20.0):
        t["sym"]=sname; tr.append(t)
f=pd.DataFrame(tr).sort_values("t0")
f["win"]=(f.R>0).astype(int)
pv=[];cv=[]
for sname,g in f.groupby("sym"):
    w=g.sort_values("t0").win.to_numpy()
    if len(w)<8: continue
    pv.append(w[:-1]); cv.append(w[1:])
pv=np.concatenate(pv); cv=np.concatenate(cv)
lf=cv[pv==1].mean()-cv.mean()
null2=np.array([cv[rng.permutation(pv)==1].mean()-cv.mean() for _ in range(3000)])
print(f"  trades {len(f):,} | P(win)={cv.mean()*100:.2f}%  "
      f"P(win|win)={cv[pv==1].mean()*100:.2f}%  lift={lf*100:+.2f}pp  "
      f"p={(null2>=lf).mean():.4f}")
