#!/usr/bin/env python3
"""
Q2 — UNSUPERVISED. Three things a clustering can honestly be asked for here:

  P1 REGIME DISCOVERY. Let k-means find the regimes instead of hand-picking an
     efficiency threshold. Fitted on the FIRST HALF of time only, applied to the
     second half, so the cluster definitions cannot see the data they are scored on.

  P2 A MARKET-WIDE STATE THAT NO SINGLE-SYMBOL FEATURE CAN SEE. Every feature in
     the project is computed on one instrument. The 129-perp panel supports
     cross-sectional summaries -- correlation concentration (PC1 share),
     dispersion, breadth -- which are unsupervised by construction. This is the
     one genuinely new information channel available without new data.

  P3 CHAIN-STATE CLUSTERING. Cluster the option surface shape itself and ask
     whether some shapes pay and others do not.
"""
import os, glob, numpy as np, pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
RNG = np.random.default_rng(3); T = 25.0

o = pd.read_parquet("runs/oof_surface_25.parquet")
o["sp"] = o.symbol.str.split("-").str[1]
o["R"] = np.where(o._peak >= T, T, o.stop_ratio) - 0.05
o["hit"] = (o._peak >= T).astype(int)
o["day"] = (o._ts_hours // 24).astype(int)
o["blk"] = (o._ts_hours // (24*7)).astype(int)

def slice_top(g, frac=0.005):
    gs = g.sort_values("score", ascending=False)
    cw = np.cumsum(gs._w.to_numpy())
    return gs[cw <= cw[-1]*frac]

def boot(sl, n=2000):
    r,w,b = sl.R.to_numpy(), sl._w.to_numpy(), sl.blk.to_numpy()
    ub = np.unique(b); out=[]
    for _ in range(n):
        idx = np.concatenate([np.where(b==q)[0] for q in RNG.choice(ub,len(ub),replace=True)])
        if len(idx)<30: continue
        out.append(np.average(r[idx],weights=w[idx])-1)
    return np.array(out)

def report(df, col, title, minrows=15000):
    print(f"\n  --- {title} ---")
    print(f"  {'state':>14}{'rows':>10}{'25x base':>10}{'top.5% hit':>12}"
          f"{'top.5% EV':>12}{'95% CI':>24}{'wks':>5}")
    st = {}
    for k,g in df.groupby(col):
        if len(g) < minrows: continue
        sl = slice_top(g)
        if len(sl) < 80: continue
        mu = boot(sl); st[k]=mu
        print(f"  {str(k):>14}{len(g):>10,}{np.average(g.hit,weights=g._w)*100:>9.3f}%"
              f"{np.average(sl.hit,weights=sl._w)*100:>11.2f}%"
              f"{np.average(sl.R,weights=sl._w)-1:>+12.4f}"
              f"  [{np.percentile(mu,2.5):+.4f},{np.percentile(mu,97.5):+.4f}]"
              f"{sl.blk.nunique():>5}")
    ks=list(st)
    for i in range(len(ks)):
        for j in range(i+1,len(ks)):
            a,b_=st[ks[i]],st[ks[j]]; n=min(len(a),len(b_)); d=a[:n]-b_[:n]
            print(f"      {str(ks[i])+' - '+str(ks[j]):<24}{d.mean():>+10.4f}"
                  f"   P(diff<=0)={(d<=0).mean():.3f}")
    return st

# ================================================================= P1
print("="*78); print("P1. UNSUPERVISED REGIMES from 105 Brooks spot features"); print("="*78)
b = pd.read_parquet("brooks_spot.parquet")
feat = [c for c in b.columns if c.startswith("bk_")]
b["day"] = (b.ts // 86400).astype(int)
d = b.sort_values("ts").groupby(["spot","day"]).last().reset_index()   # last bar of day
X = d[feat].to_numpy(np.float32)
X = np.where(np.isfinite(X), X, np.nan)
col_med = np.nanmedian(X, axis=0); X = np.where(np.isnan(X), col_med, X)
cut = np.quantile(d.ts, 0.5)
tr = d.ts.to_numpy() < cut
print(f"  daily spot states: {len(d):,}  fit on {tr.sum():,} (to "
      f"{pd.to_datetime(cut,unit='s').date()}), score on {(~tr).sum():,}")
sc = StandardScaler().fit(X[tr]); Z = sc.transform(X)
pca = PCA(n_components=12, random_state=0).fit(Z[tr]); P = pca.transform(Z)
print(f"  PCA on the fitted half: PC1 {pca.explained_variance_ratio_[0]*100:.1f}% "
      f"PC1-3 {pca.explained_variance_ratio_[:3].sum()*100:.1f}% "
      f"PC1-12 {pca.explained_variance_ratio_.sum()*100:.1f}%")
for K in (3, 5):
    km = KMeans(K, n_init=10, random_state=0).fit(P[tr])
    d[f"km{K}"] = km.predict(P)
    # persistence, out of sample only
    oo = d[~tr].sort_values(["spot","day"])
    pers=[]
    for sp,g in oo.groupby("spot"):
        v=g[f"km{K}"].to_numpy()
        if len(v)>30: pers.append(((v[1:]==v[:-1]).mean(), (v[7:]==v[:-7]).mean()))
    pers=np.array(pers)
    print(f"  k={K}: OOS persistence P(same +1d)={pers[:,0].mean():.3f} "
          f"P(same +7d)={pers[:,1].mean():.3f}  (chance {1/K:.3f})")

# map option rows to the PREVIOUS day's cluster (causal), OOS half only
oos = o[o._ts_hours*3600 >= cut].copy()
print(f"\n  option rows in the scored half: {len(oos):,} "
      f"({oos.blk.nunique()} weeks)")
for K in (3,5):
    lut = {}
    for sp,g in d.groupby("spot"):
        g=g.sort_values("day"); lut[sp]=(g.day.to_numpy(), g[f"km{K}"].to_numpy())
    lab = np.full(len(oos), -1)
    for sp in oos.sp.unique():
        if sp not in lut: continue
        m = (oos.sp==sp).to_numpy(); days, vals = lut[sp]
        j = np.searchsorted(days, oos.day.to_numpy()[m], side="left") - 1  # prior day
        ok = j >= 0
        idx = np.where(m)[0][ok]
        lab[idx] = vals[j[ok]]
    oos[f"km{K}"] = lab
    report(oos[oos[f"km{K}"]>=0], f"km{K}", f"k-means k={K} (OOS half only)", 8000)

# ================================================================= P2
print("\n"+"="*78)
print("P2. MARKET-WIDE CROSS-SECTIONAL STATE from the 129-perp panel")
print("="*78)
CACHE="runs/mktstate.parquet"
if os.path.exists(CACHE):
    ms = pd.read_parquet(CACHE)
else:
    inv = pd.read_parquet("perp_inventory.parquet")
    syms = inv[inv.years>=1.0].sym.tolist()
    cl={}
    for s in syms:
        p=f"data/perp_candles/{s}.parquet"
        if not os.path.exists(p): continue
        x=pd.read_parquet(p)[["ts","c"]].drop_duplicates("ts").sort_values("ts")
        x["day"]=(x.ts//86400).astype(int)
        cl[s]=x.groupby("day").c.last()
    C=pd.DataFrame(cl).sort_index()
    print(f"  panel {C.shape[0]} days x {C.shape[1]} symbols")
    Rm=np.log(C).diff()
    rows=[]
    days=C.index.to_numpy()
    for i in range(30,len(days)):
        w=Rm.iloc[i-20:i]                      # strictly prior 20 days
        w=w.dropna(axis=1, thresh=18)
        if w.shape[1]<20: continue
        A=w.fillna(0.0).to_numpy()
        A=A-A.mean(0)
        sd=A.std(0); sd[sd==0]=1; An=A/sd
        ev=np.linalg.svd(An, compute_uv=False)**2
        pc1=ev[0]/ev.sum()
        neff=(ev.sum()**2)/ (ev**2).sum()
        disp=np.nanstd(Rm.iloc[i-1].to_numpy())          # yesterday's cross-sec dispersion
        ma20=C.iloc[i-20:i].mean(); brd=float((C.iloc[i-1]>ma20).mean())
        rows.append((days[i], pc1, neff, disp, brd))
    ms=pd.DataFrame(rows,columns=["day","pc1","neff","disp","breadth"])
    ms.to_parquet(CACHE,index=False)
print(f"  market-state days: {len(ms):,}  "
      f"pc1 {ms.pc1.mean():.3f}+-{ms.pc1.std():.3f} | "
      f"neff {ms.neff.mean():.2f} | breadth {ms.breadth.mean():.2f}")
q = {c: ms[c].quantile([0.33,0.66]).to_numpy() for c in ["pc1","neff","disp","breadth"]}
for c in ["pc1","neff","disp","breadth"]:
    ms[c+"_b"] = np.where(ms[c]<=q[c][0], f"{c}:low",
                  np.where(ms[c]>=q[c][1], f"{c}:high", f"{c}:mid"))
oo = o.merge(ms[["day"]+[c+"_b" for c in ["pc1","neff","disp","breadth"]]],
             on="day", how="inner")
print(f"  option rows matched to a market state: {len(oo):,} "
      f"({oo.blk.nunique()} weeks)")
for c in ["pc1","neff","disp","breadth"]:
    report(oo, c+"_b", f"market {c}")

# ================================================================= P3
print("\n"+"="*78)
print("P3. CHAIN-SHAPE CLUSTERING (surf_ features), fit on first half")
print("="*78)
import duckdb
c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
cols = c.execute("DESCRIBE SELECT * FROM 'disc_final/part-00000.parquet' LIMIT 1").df()
sfeat = [x for x in cols.column_name if x.startswith("surf_")]
print(f"  surface features: {len(sfeat)}")
q2 = f"SELECT symbol, _ts_hours, {','.join(sfeat)} FROM 'disc_final/*.parquet'"
S = c.execute(q2).df()
m = o.merge(S, on=["symbol","_ts_hours"], how="inner")
print(f"  joined rows {len(m):,}")
Xs = m[sfeat].to_numpy(np.float32)
Xs = np.where(np.isfinite(Xs), Xs, np.nan)
cm = np.nanmedian(Xs,axis=0); Xs=np.where(np.isnan(Xs),cm,Xs)
trm = (m._ts_hours*3600 < cut).to_numpy()
sc2=StandardScaler().fit(Xs[trm]); Z2=sc2.transform(Xs)
np.clip(Z2,-8,8,out=Z2)
km2=KMeans(6,n_init=5,random_state=0).fit(Z2[trm][RNG.choice(trm.sum(),min(120000,trm.sum()),replace=False)])
m["chain_k"]=km2.predict(Z2)
report(m[~trm], "chain_k", "chain-shape cluster (OOS half)", 5000)
