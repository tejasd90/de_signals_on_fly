#!/usr/bin/env python3
"""Does the cross-expiry (term-structure) family add anything?

Arms, all with purged walk-forward on episodes and _w weights:
  context  : the 6 non-prefixed columns
  surface  : context + 15 within-expiry surf_   (current best)
  term     : context + 10 NEW cross-expiry features
  surf+term: both
Also a within-timestamp test: given the instant, does term_resid rank WHICH
EXPIRY pays? That is the specific gap the surface features could not see.
"""
import numpy as np,pandas as pd,duckdb,lightgbm as lgb
from sklearn.metrics import roc_auc_score
c=duckdb.connect(); c.execute("SET memory_limit='4GB'; SET threads=5;")
df=c.execute("""
SELECT d.*, t.term_slope_p0,t.term_resid_p0,t.term_r2_p0,
       t.term_slope_p5,t.term_resid_p5,t.term_r2_p5,
       t.term_nexp,t.term_ttrank,t.skew_term_slope,t.skew_term_resid
FROM 'disc_final/*.parquet' d
LEFT JOIN 'term_features.parquet' t
  ON d.spot=t.spot AND d.expiry=t.expiry
 AND substr(d.symbol,1,1)=t.typ
 AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=t.ts
""").df().reset_index(drop=True)
TERM=["term_slope_p0","term_resid_p0","term_r2_p0","term_slope_p5","term_resid_p5",
      "term_r2_p5","term_nexp","term_ttrank","skew_term_slope","skew_term_resid"]
print(f"rows {len(df):,} | term join coverage "
      f"{df.term_slope_p0.notna().mean()*100:.1f}%")
y=df["label_25_0"].astype(np.int8).to_numpy(); w=df["_w"].to_numpy(float)
CTX=["tteHours","cheapness","stdMoneyness","moneynessPct","spotVol"]
SURF=[x for x in df.columns if x.startswith("surf_")]
ep=df.groupby("episode_id")["_ts_hours"].min().sort_values(); eps=ep.index.to_numpy()
b=np.linspace(0,len(eps),6).astype(int); emb=max(1,int(len(eps)*.01))
folds=[]
for i in range(1,5):
    tr=set(eps[:max(0,b[i]-emb)]); te=set(eps[b[i]:b[i+1]])
    folds.append((df.index[df.episode_id.isin(tr)].to_numpy(),
                  df.index[df.episode_id.isin(te)].to_numpy()))
def prec_at(yv,p,wv,rec=0.15):
    o=np.argsort(-p); yy,ww=yv[o],wv[o]
    tp=np.cumsum(ww*yy); tot=(wv*yv).sum()
    k=np.searchsorted(tp,tot*rec)
    if k>=len(o): return np.nan
    return tp[k]/max(np.cumsum(ww)[k],1e-9)
print(f"\n{'arm':<12}{'feats':>7}{'AUC':>9}{'P@15%rec':>11}")
print("-"*40)
res={}
for name,cols in [("context",CTX),("surface",CTX+SURF),("term",CTX+TERM),
                  ("surf+term",CTX+SURF+TERM)]:
    X=df[cols].to_numpy(np.float64); X[~np.isfinite(X)]=np.nan
    oof=np.full(len(df),np.nan)
    for tr,te in folds:
        m=lgb.LGBMClassifier(n_estimators=300,learning_rate=0.03,num_leaves=7,max_depth=3,
            min_child_samples=30,subsample=.8,subsample_freq=1,colsample_bytree=.7,
            reg_lambda=5.0,class_weight="balanced",random_state=0,n_jobs=5,verbose=-1)
        m.fit(X[tr],y[tr],sample_weight=w[tr]); oof[te]=m.predict_proba(X[te])[:,1]
    ok=np.isfinite(oof)
    a=roc_auc_score(y[ok],oof[ok],sample_weight=w[ok]); p=prec_at(y[ok],oof[ok],w[ok])
    res[name]=(a,p)
    print(f"{name:<12}{len(cols):>7}{a:>9.4f}{p:>11.4f}")
print("\n=== within-timestamp: does term_resid rank WHICH EXPIRY pays? ===")
d2=df[np.isfinite(df.term_resid_p5)].copy()
d2["inst"]=d2.spot+"|"+d2._ts_hours.astype(str)+"|"+d2.symbol.str[0]
aucs=[];ws=[]
for k,g in d2.groupby("inst"):
    if g.expiry.nunique()<2 or g["label_25_0"].nunique()<2: continue
    try:
        aucs.append(roc_auc_score(g["label_25_0"],-g.term_resid_p5,sample_weight=g["_w"]))
        ws.append(g["_w"].sum())
    except Exception: pass
if aucs:
    aucs=np.array(aucs);ws=np.array(ws)
    print(f"  instants with mixed outcomes across expiries: {len(aucs):,}")
    print(f"  weighted AUC of -term_resid_p5 (CHEAP expiry pays?): {np.average(aucs,weights=ws):.4f}")
    print(f"  (0.50 = the term residual says nothing about which expiry pays)")
