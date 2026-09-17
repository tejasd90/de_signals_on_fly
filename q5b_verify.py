#!/usr/bin/env python3
"""
q5_verify.py part 1 was invalid: k-means cluster INDICES are not stable across
runs, so "ck != 2" in one script names a different group than in another. The
q4 result and its 'verification' were comparing different clusters.

Fixed here: the cluster is identified by a PROPERTY measured on the training
half only -- the cluster whose weighted 25x rate is lowest -- and then that
cluster is excluded on the held-out half, which is the honest test.
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
o["trend20"] = "na"
for sp in o.sp.unique():
    if sp not in REG: continue
    m = (o.sp == sp).to_numpy()
    o.loc[m,"trend20"] = tag(sp, o.loc[m,"_ts_hours"].to_numpy(), "trend20")
c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
cols = list(c.execute("DESCRIBE SELECT * FROM 'disc_final/part-00000.parquet' LIMIT 1")
            .df().column_name)
sf = [x for x in cols if x.startswith("surf_")]
ctx = [x for x in ["tteHours","cheapness","stdMoneyness","distancePct","type"] if x in cols]
S = c.execute(f"SELECT symbol,_ts_hours,{','.join(sf+ctx)} FROM 'disc_final/*.parquet'").df()
o = o.merge(S, on=["symbol","_ts_hours"], how="left"); del S

cut = np.quantile(o._ts_hours, 0.5); trm = (o._ts_hours < cut).to_numpy()
X = o[sf].to_numpy(np.float32); X = np.where(np.isfinite(X), X, np.nan)
X = np.where(np.isnan(X), np.nanmedian(X,axis=0), X)
Z = StandardScaler().fit(X[trm]).transform(X); np.clip(Z,-8,8,out=Z)

def policy(df, frac=0.005):
    gs = df.sort_values("score", ascending=False)
    return gs[np.cumsum(gs._w.to_numpy()) <= gs._w.sum()*frac].copy()

def paired(POL, mask, nb=4000):
    r,w,b = POL.R.to_numpy(), POL._w.to_numpy(), POL.blk.to_numpy()
    m = np.asarray(mask); ub=np.unique(b); ibb={q:np.where(b==q)[0] for q in ub}
    de=[]
    for _ in range(nb):
        idx=np.concatenate([ibb[q] for q in RNG.choice(ub,len(ub),replace=True)])
        sel=idx[m[idx]]
        if len(sel)<40: continue
        de.append(np.average(r[sel],weights=w[sel])-np.average(r[idx],weights=w[idx]))
    return np.array(de)

print("HELD-OUT TEST. Clustering fitted on the first half; the cluster to drop is")
print("chosen by its 25x rate in the first half; both are then applied blind to the")
print("second half. Repeated at several k and several seeds — a rule that only")
print("works at one k is a coincidence.\n")
print(f"  {'k':>3}{'seed':>5}{'dropped cluster':>16}{'train 25x':>11}{'test 25x':>10}"
      f"{'keep%':>7}{'EV base':>9}{'EV filt':>9}{'dEV':>9}{'P(<=0)':>8}")
POL_test = policy(o[~trm])
res=[]
for K in (4,6,8):
    for seed in (0,1,2):
        sub = RNG.choice(np.where(trm)[0], min(120000,trm.sum()), replace=False)
        km = KMeans(K, n_init=5, random_state=seed).fit(Z[sub])
        lab = km.predict(Z)
        tr_rate = {k: np.average(o.hit.to_numpy()[trm & (lab==k)],
                                 weights=o._w.to_numpy()[trm & (lab==k)])
                   for k in range(K) if (trm & (lab==k)).sum() > 3000}
        bad = min(tr_rate, key=tr_rate.get)
        te = (~trm) & (lab==bad)
        te_rate = np.average(o.hit.to_numpy()[te], weights=o._w.to_numpy()[te]) if te.sum() else np.nan
        lp = lab[POL_test.index.to_numpy()] if False else km.predict(Z[o.index.get_indexer(POL_test.index)])
        msk = lp != bad
        de = paired(POL_test, msk)
        keep = POL_test._w[msk].sum()/POL_test._w.sum()*100
        ev0 = np.average(POL_test.R,weights=POL_test._w)-1
        evf = np.average(POL_test.R[msk],weights=POL_test._w[msk])-1
        res.append((de<=0).mean())
        print(f"  {K:>3}{seed:>5}{bad:>16}{tr_rate[bad]*100:>10.4f}%{te_rate*100:>9.4f}%"
              f"{keep:>7.0f}%{ev0:>+9.4f}{evf:>+9.4f}{de.mean():>+9.4f}{(de<=0).mean():>8.3f}")
print(f"\n  9 configurations: median P(dEV<=0) = {np.median(res):.3f}; "
      f"{sum(p<0.05 for p in res)} of 9 below 0.05")

print("\n" + "="*84)
print("The same held-out test for the REGIME filter (no fitting involved at all)")
print("="*84)
for name,msk in [("trend20 != up", (POL_test.trend20!="up").to_numpy())]:
    de = paired(POL_test, msk)
    print(f"  {name}: keep {POL_test._w[msk].sum()/POL_test._w.sum()*100:.0f}%  "
          f"EV {np.average(POL_test.R[msk],weights=POL_test._w[msk])-1:+.4f} vs "
          f"{np.average(POL_test.R,weights=POL_test._w)-1:+.4f}  "
          f"dEV {de.mean():+.4f} [{np.percentile(de,2.5):+.4f},{np.percentile(de,97.5):+.4f}]"
          f"  P(<=0)={(de<=0).mean():.4f}")
