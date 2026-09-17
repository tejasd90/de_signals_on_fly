#!/usr/bin/env python3
"""
Closing three loose ends.

 (a) sanity: how much of the TRADED slice is the dead chain-cluster? (q4 said
     14% by index; that index was unstable, so measure it by property.)
 (b) the unsupervised SPOT regime, identified by property on the train half and
     applied blind to the held-out half — the same discipline as the chain test.
 (c) the question underneath all of Q1: can regime information lift the
     BETWEEN-EPISODE ranking, which is the 0.5745 that binds the whole project?
"""
import numpy as np, pandas as pd, duckdb, lightgbm as lgb
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import roc_auc_score
from q1_regimes import tag, REG
RNG = np.random.default_rng(21); T = 25.0

o = pd.read_parquet("runs/oof_surface_25.parquet")
o["sp"]=o.symbol.str.split("-").str[1]
o["R"]=np.where(o._peak>=T,T,o.stop_ratio)-0.05
o["hit"]=(o._peak>=T).astype(int)
o["blk"]=(o._ts_hours//(24*7)).astype(int); o["day"]=(o._ts_hours//24).astype(int)
for ax in ["trend20","vol20","pos60","dir20","eff20"]:
    o[ax]="na"
    for sp in o.sp.unique():
        if sp not in REG: continue
        m=(o.sp==sp).to_numpy(); o.loc[m,ax]=tag(sp,o.loc[m,"_ts_hours"].to_numpy(),ax)
c=duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
cols=list(c.execute("DESCRIBE SELECT * FROM 'disc_final/part-00000.parquet' LIMIT 1").df().column_name)
sf=[x for x in cols if x.startswith("surf_")]
S=c.execute(f"SELECT symbol,_ts_hours,{','.join(sf)} FROM 'disc_final/*.parquet'").df()
o=o.merge(S,on=["symbol","_ts_hours"],how="left"); del S
cut=np.quantile(o._ts_hours,0.5); trm=(o._ts_hours<cut).to_numpy()
X=o[sf].to_numpy(np.float32); X=np.where(np.isfinite(X),X,np.nan)
X=np.where(np.isnan(X),np.nanmedian(X,axis=0),X)
Z=StandardScaler().fit(X[trm]).transform(X); np.clip(Z,-8,8,out=Z)
sub=RNG.choice(np.where(trm)[0],min(120000,trm.sum()),replace=False)
km=KMeans(6,n_init=5,random_state=0).fit(Z[sub]); o["ck"]=km.predict(Z)
rate={k:np.average(o.hit.to_numpy()[trm&(o.ck==k).to_numpy()],
                   weights=o._w.to_numpy()[trm&(o.ck==k).to_numpy()])
      for k in range(6) if (trm&(o.ck==k).to_numpy()).sum()>3000}
bad=min(rate,key=rate.get)
gs=o.sort_values("score",ascending=False); POL=gs[np.cumsum(gs._w.to_numpy())<=gs._w.sum()*0.005]
print("(a) DEAD CHAIN-CLUSTER vs THE TRADED SLICE")
print(f"    cluster {bad}: {np.average((o.ck==bad),weights=o._w)*100:.1f}% of the universe, "
      f"25x rate {rate[bad]*100:.4f}% (train)")
print(f"    share of the top-0.5% traded slice: "
      f"{np.average((POL.ck==bad),weights=POL._w)*100:.3f}%")
print("    -> the supervised model already refuses it; the clustering is real but redundant.\n")

print("(b) UNSUPERVISED SPOT REGIME, property-identified, held out")
b=pd.read_parquet("brooks_spot.parquet"); bf=[x for x in b.columns if x.startswith("bk_")]
b["day"]=(b.ts//86400).astype(int)
d=b.sort_values("ts").groupby(["spot","day"]).last().reset_index()
Xd=d[bf].to_numpy(np.float32); Xd=np.where(np.isfinite(Xd),Xd,np.nan)
Xd=np.where(np.isnan(Xd),np.nanmedian(Xd,axis=0),Xd)
dtr=(d.ts.to_numpy()*1.0 < cut*3600)
Zd=StandardScaler().fit(Xd[dtr]).transform(Xd); Pd=PCA(12,random_state=0).fit(Zd[dtr]).transform(Zd)
POLte=POL[~POL._ts_hours.lt(cut)].copy()
def paired(P,mask,nb=3000):
    r,w,bl=P.R.to_numpy(),P._w.to_numpy(),P.blk.to_numpy(); m=np.asarray(mask)
    ub=np.unique(bl); ibb={q:np.where(bl==q)[0] for q in ub}; de=[]
    for _ in range(nb):
        idx=np.concatenate([ibb[q] for q in RNG.choice(ub,len(ub),replace=True)])
        s=idx[m[idx]]
        if len(s)<40: continue
        de.append(np.average(r[s],weights=w[s])-np.average(r[idx],weights=w[idx]))
    return np.array(de)
print(f"    {'k':>3}{'seed':>5}{'dropped':>9}{'trainEV':>10}{'keep%':>7}{'dEV':>9}{'P(<=0)':>8}")
ps=[]
for K in (3,5,7):
    for seed in (0,1):
        lab=KMeans(K,n_init=10,random_state=seed).fit(Pd[dtr]).predict(Pd)
        d["kk"]=lab
        o["kk"]=-1
        for sp,g in d.groupby("spot"):
            g=g.sort_values("day"); m=(o.sp==sp).to_numpy()
            if not m.any(): continue
            j=np.searchsorted(g.day.to_numpy(),o.day.to_numpy()[m],side="left")-1
            ok=j>=0; o.loc[np.where(m)[0][ok],"kk"]=g.kk.to_numpy()[j[ok]]
        POL2=POL.copy(); POL2["kk"]=o["kk"].reindex(POL2.index).to_numpy()
        Ptr=POL2[POL2._ts_hours<cut]; Pte=POL2[POL2._ts_hours>=cut]
        evk={k:np.average(Ptr.R[Ptr.kk==k],weights=Ptr._w[Ptr.kk==k])-1
             for k in range(K) if (Ptr.kk==k).sum()>150}
        if not evk: continue
        worst=min(evk,key=evk.get)
        msk=(Pte.kk!=worst).to_numpy(); de=paired(Pte,msk)
        ps.append((de<=0).mean())
        print(f"    {K:>3}{seed:>5}{worst:>9}{evk[worst]:>+10.4f}"
              f"{Pte._w[msk].sum()/Pte._w.sum()*100:>7.0f}%{de.mean():>+9.4f}{(de<=0).mean():>8.3f}")
print(f"    median P(dEV<=0) over {len(ps)} configs = {np.median(ps):.3f}\n")

print("(c) CAN REGIME LIFT THE BETWEEN-EPISODE RANKING? (the 0.5745 that binds)")
ep=o.groupby("episode_id").apply(lambda g: pd.Series({
    "t":g._ts_hours.min(),"sp":g.sp.iloc[0],
    "y":float(np.average(g.hit,weights=g._w)>0),
    "topR":np.average(g.sort_values("score",ascending=False).head(max(1,int(len(g)*0.05))).R,
                      weights=g.sort_values("score",ascending=False).head(max(1,int(len(g)*0.05)))._w),
    "mscore":g.score.max(),"mnscore":np.average(g.score,weights=g._w)}),
    include_groups=False).reset_index().sort_values("t")
ep["ypay"]=(ep.topR>1).astype(int)
for ax in ["trend20","vol20","pos60","dir20"]:
    ep[ax]=[tag(s,[t],ax)[0] if s in REG else "na" for s,t in zip(ep.sp,ep.t)]
ep["eff20"]=[float(tag(s,[t],"eff20")[0]) if s in REG else np.nan for s,t in zip(ep.sp,ep.t)]
ms=pd.read_parquet("runs/mktstate.parquet"); ep["day"]=(ep.t//24).astype(int)
ep=ep.merge(ms,on="day",how="left")
print(f"    episodes {len(ep):,}  P(top-5% basket profits) {ep.ypay.mean()*100:.1f}%")
cats=["trend20","vol20","pos60","dir20"]
D=pd.get_dummies(ep[cats],drop_first=True).astype(float)
for col in ["eff20","pc1","neff","disp","breadth"]: D[col]=ep[col].to_numpy()
D=D.fillna(D.median())
y=ep.ypay.to_numpy(); tt=ep.t.to_numpy()
edges=np.quantile(tt,np.linspace(0,1,6)); oof=np.full(len(y),np.nan)
for i in range(1,5):
    te=(tt>=edges[i])&(tt<edges[i+1]); tr=tt<edges[i]-72
    if tr.sum()<200 or te.sum()<80: continue
    g=lgb.LGBMClassifier(n_estimators=200,learning_rate=0.03,num_leaves=7,max_depth=3,
        min_child_samples=60,subsample=0.8,subsample_freq=1,colsample_bytree=0.7,
        reg_lambda=20.0,random_state=0,n_jobs=4,verbose=-1)
    g.fit(D[tr],y[tr]); oof[te]=g.predict_proba(D[te])[:,1]
ok=np.isfinite(oof)
auc=roc_auc_score(y[ok],oof[ok])
nul=np.array([roc_auc_score(RNG.permutation(y[ok]),oof[ok]) for _ in range(1000)])
print(f"    regime+market features -> between-episode AUC {auc:.4f}"
      f"   permutation null {nul.mean():.4f} (95th {np.percentile(nul,95):.4f})"
      f"   p={(nul>=auc).mean():.4f}")
print(f"    for reference: the model's own between-episode AUC is 0.5745, and "
      f"arm 4 (105 Brooks features) reached 0.5286 with p=0.150")
for ax in cats:
    sub_=ep.groupby(ax).ypay.agg(["mean","count"])
    print(f"      {ax}: " + "  ".join(f"{k}={v['mean']*100:.0f}%({int(v['count'])})"
                                      for k,v in sub_.iterrows() if v['count']>60))
