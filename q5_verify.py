#!/usr/bin/env python3
"""
VERIFICATION of the two filters that cleared the paired test in q4_filters.py.

Three things have to hold before either is worth using:
  1. it must survive on the HALF OF TIME the clustering never saw
  2. it must not be a single lucky year
  3. we must be able to say WHAT it is -- a filter you cannot describe is a
     filter you cannot trust to keep working
"""
import numpy as np, pandas as pd, duckdb
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from q1_regimes import tag, REG
RNG = np.random.default_rng(13); T = 25.0

o = pd.read_parquet("runs/oof_surface_25.parquet")
o["sp"]  = o.symbol.str.split("-").str[1]
o["R"]   = np.where(o._peak >= T, T, o.stop_ratio) - 0.05
o["hit"] = (o._peak >= T).astype(int)
o["blk"] = (o._ts_hours // (24*7)).astype(int)
o["year"] = pd.to_datetime(o._ts_hours*3600, unit="s").dt.year
for axis in ["trend20","pos60"]:
    o[axis] = "na"
    for sp in o.sp.unique():
        if sp not in REG: continue
        m = (o.sp == sp).to_numpy()
        o.loc[m, axis] = tag(sp, o.loc[m, "_ts_hours"].to_numpy(), axis)

c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
cols = c.execute("DESCRIBE SELECT * FROM 'disc_final/part-00000.parquet' LIMIT 1").df().column_name
sf = [x for x in cols if x.startswith("surf_")]
ctx = [x for x in ["tteHours","cheapness","stdMoneyness","distancePct","type"] if x in list(cols)]
S = c.execute(f"SELECT symbol,_ts_hours,{','.join(sf+ctx)} FROM 'disc_final/*.parquet'").df()
o = o.merge(S, on=["symbol","_ts_hours"], how="left"); del S
cut = np.quantile(o._ts_hours, 0.5)
trm = (o._ts_hours < cut).to_numpy()
X = o[sf].to_numpy(np.float32); X = np.where(np.isfinite(X), X, np.nan)
X = np.where(np.isnan(X), np.nanmedian(X, axis=0), X)
sc = StandardScaler().fit(X[trm]); Z = sc.transform(X); np.clip(Z,-8,8,out=Z)
sub = RNG.choice(np.where(trm)[0], min(120000, trm.sum()), replace=False)
km = KMeans(6, n_init=5, random_state=0).fit(Z[sub])
o["ck"] = km.predict(Z)
print(f"train half ends {pd.to_datetime(cut*3600,unit='s').date()}   "
      f"rows {len(o):,}  ({trm.sum():,} fit / {(~trm).sum():,} held out)")

def policy(df, frac=0.005):
    gs = df.sort_values("score", ascending=False)
    cw = np.cumsum(gs._w.to_numpy())
    return gs[cw <= cw[-1]*frac].copy()

def paired(POL, mask, nb=4000):
    r,w,b = POL.R.to_numpy(), POL._w.to_numpy(), POL.blk.to_numpy()
    m = np.asarray(mask); ub = np.unique(b)
    ibb = {q: np.where(b==q)[0] for q in ub}
    de=[]
    for _ in range(nb):
        pk = RNG.choice(ub, len(ub), replace=True)
        idx = np.concatenate([ibb[q] for q in pk]); sel = idx[m[idx]]
        if len(sel) < 40: continue
        de.append(np.average(r[sel],weights=w[sel]) - np.average(r[idx],weights=w[idx]))
    return np.array(de)

print("\n" + "="*84)
print("1. OUT-OF-SAMPLE HALF ONLY (clustering never saw these weeks)")
print("="*84)
for lab, sub_df in [("FULL sample", o), ("HELD-OUT half", o[~trm])]:
    POL = policy(sub_df)
    ev0 = np.average(POL.R, weights=POL._w)-1
    print(f"\n  {lab}: {len(POL):,} trades, {POL.blk.nunique()} weeks, EV {ev0:+.4f}")
    for name, msk in [("ck != 2", (POL.ck!=2).to_numpy()),
                      ("trend20 != up", (POL.trend20!="up").to_numpy()),
                      ("both", ((POL.ck!=2)&(POL.trend20!="up")).to_numpy())]:
        de = paired(POL, msk)
        keep = POL._w[msk].sum()/POL._w.sum()*100
        evf = np.average(POL.R[msk], weights=POL._w[msk])-1
        print(f"    {name:<16} keep {keep:>4.0f}%  EV {evf:>+.4f}  dEV {de.mean():>+.4f}"
              f"  [{np.percentile(de,2.5):+.4f},{np.percentile(de,97.5):+.4f}]"
              f"  P(<=0)={(de<=0).mean():.4f}")

print("\n" + "="*84)
print("2. YEAR BY YEAR — is it one lucky year?")
print("="*84)
POL = policy(o)
print(f"  {'year':>6}{'trades':>8}{'EV all':>10}{'EV ck!=2':>11}{'EV !up':>10}{'EV both':>10}")
for y, g in POL.groupby("year"):
    if len(g) < 300: continue
    def ev(m): 
        gg = g[m]
        return np.average(gg.R, weights=gg._w)-1 if len(gg)>50 else np.nan
    print(f"  {y:>6}{len(g):>8,}{ev(np.ones(len(g),bool)):>+10.4f}"
          f"{ev((g.ck!=2).to_numpy()):>+11.4f}{ev((g.trend20!='up').to_numpy()):>+10.4f}"
          f"{ev(((g.ck!=2)&(g.trend20!='up')).to_numpy()):>+10.4f}")

print("\n" + "="*84)
print("3. WHAT IS CLUSTER 2? (the shape the model over-buys and that never pays)")
print("="*84)
o["is2"] = (o.ck==2)
print(f"  cluster 2 is {o.is2.mean()*100:.0f}% of rows, "
      f"{np.average(o.is2, weights=o._w)*100:.0f}% by weight; "
      f"25x rate {np.average(o.hit[o.is2],weights=o._w[o.is2])*100:.4f}% "
      f"vs {np.average(o.hit[~o.is2],weights=o._w[~o.is2])*100:.4f}% elsewhere")
print(f"\n  {'feature':>22}{'cluster2 mean':>15}{'rest mean':>12}{'std-diff':>10}")
for f in sf + [x for x in ctx if x != "type"]:
    a = o.loc[o.is2, f].astype(float); b_ = o.loc[~o.is2, f].astype(float)
    s = o[f].astype(float).std()
    if not np.isfinite(s) or s == 0: continue
    dd = (a.mean()-b_.mean())/s
    if abs(dd) > 0.45:
        print(f"  {f:>22}{a.mean():>15.4f}{b_.mean():>12.4f}{dd:>+10.2f}")
if "type" in o:
    print("\n  type mix: cluster2 " +
          str((o.loc[o.is2,"type"].value_counts(normalize=True)*100).round(0).to_dict())
          + "  rest " +
          str((o.loc[~o.is2,"type"].value_counts(normalize=True)*100).round(0).to_dict()))
print("\n  tteHours quartiles: cluster2 "
      f"{np.nanpercentile(o.loc[o.is2,'tteHours'],[25,50,75]).round(0)} "
      f"rest {np.nanpercentile(o.loc[~o.is2,'tteHours'],[25,50,75]).round(0)}")
