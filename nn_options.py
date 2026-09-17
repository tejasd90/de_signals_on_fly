#!/usr/bin/env python3
"""
Same question on the OPTIONS side, plus one bonus test the futures data cannot run.

  1. LightGBM on the surface arm   <- the published baseline (AUC 0.9173, P@15% 0.0307)
  2. MLP on the same 20 features
  3. GRU / CNN on the 8-BAR OPTION CANDLE SEQUENCE (opt_body/uwick/lwick/rng _1.._8)
     plus context.

Test 3 matters. FINDINGS 1 says option-candle shape scored WORSE than context
alone (0.012 vs 0.019 precision) and HANDOFF 2.1 says every pattern-shape feature
was inert under permutation importance. Both used hand-built encodings fed to a
tree. Those 32 columns are literally an 8-step time series, so a sequence model is
the fair re-test: if pattern shape carries anything, a GRU on the raw bars is the
best chance it will ever get.

Also reported: the within-episode / between-episode AUC split, because a headline
AUC on this dataset hides which of the two halves moved.
"""
import numpy as np, pandas as pd, duckdb, lightgbm as lgb, torch, time
import torch.nn as nn
from sklearn.metrics import roc_auc_score, precision_recall_curve
from sklearn.preprocessing import StandardScaler

torch.set_num_threads(6)
DEV = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
OUTCOMES = {"ratio","univratio","state","brokeout","holdcandles","peakafter"}
NONSTAT = {"episodeid","spotprice","entryprice","triggerprice","patternhigh",
           "patternlow","avgprice","logvalue"}
LEAK = ({"_peak","label","episode_id","_episode_time","_ts_hours","_w","symbol",
         "timestamp","entryts","expiry","strike","mbratio","peakratio","maxratio",
         "peak","forwardratio","signalvalue","univsymbol","_key","signal"}
        | OUTCOMES | NONSTAT)

c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=6;")
schema = c.execute("DESCRIBE SELECT * FROM 'disc_final/part-00000.parquet' LIMIT 1").df()
numcols = [r.column_name for _, r in schema.iterrows()
           if r.column_type in ("FLOAT","DOUBLE","INTEGER","BIGINT","TINYINT","SMALLINT")]
feats_all = [x for x in numcols
             if not x.startswith("_") and x.lower().replace("_","") not in LEAK]
ctx  = [x for x in feats_all if not x.startswith(("opt_","spot_","surf_"))]
surf = [x for x in feats_all if x.startswith("surf_")]
optc = [x for x in feats_all if x.startswith("opt_")]
SEQ_BASE = ["opt_body","opt_uwick","opt_lwick","opt_rng"]
seqcols = [[f"{b}_{i}" for b in SEQ_BASE] for i in range(1, 9)]
seqflat = [x for grp in seqcols for x in grp]
missing = [x for x in seqflat if x not in optc]
print(f"context {len(ctx)}: {ctx}")
print(f"surface {len(surf)} | option-shape {len(optc)} | seq cols usable "
      f"{len(seqflat)-len(missing)}/32")

need = sorted(set(ctx + surf + seqflat) - set(missing)) + ["_peak","_w","_ts_hours","episode_id"]
df = c.execute(f"SELECT {','.join(need)} FROM 'disc_final/*.parquet'").df()
df["y"] = (df._peak >= 25.0).astype(np.int8)
df = df.sort_values("_ts_hours").reset_index(drop=True)
ts = df._ts_hours.to_numpy(); y = df.y.to_numpy(); w = df._w.to_numpy()
ep = df.episode_id.to_numpy()
print(f"rows {len(df):,}  episodes {df.episode_id.nunique():,}  "
      f"weighted 25x rate {np.average(y,weights=w)*100:.3f}%")

SURF_ARM = ctx + surf
Xs = df[SURF_ARM].to_numpy(np.float32); Xs[~np.isfinite(Xs)] = np.nan
Xc = df[ctx].to_numpy(np.float32); Xc[~np.isfinite(Xc)] = np.nan
S = np.stack([df[[x for x in grp if x not in missing]].to_numpy(np.float32)
              for grp in seqcols], axis=1)          # (n, 8, 4)
S[~np.isfinite(S)] = 0.0
print(f"surface arm {Xs.shape} | option sequence {S.shape}")

edges = np.quantile(ts, np.linspace(0, 1, 6))
EMB = 72.0        # hours of embargo between train and test

class MLP(nn.Module):
    def __init__(s, d, hid=128):
        super().__init__()
        s.f = nn.Sequential(nn.Linear(d,hid), nn.BatchNorm1d(hid), nn.ReLU(), nn.Dropout(0.3),
                            nn.Linear(hid,hid//2), nn.BatchNorm1d(hid//2), nn.ReLU(), nn.Dropout(0.3),
                            nn.Linear(hid//2,1))
    def forward(s,x,e=None): return s.f(x).squeeze(-1)

class SeqNet(nn.Module):
    """8-bar option candle sequence -> GRU (or CNN) -> concat context -> head."""
    def __init__(s, nctx, kind="GRU", ch=4, hid=48):
        super().__init__()
        s.kind = kind
        if kind == "GRU": s.r = nn.GRU(ch, hid, batch_first=True)
        else: s.r = nn.Sequential(nn.Conv1d(ch,hid,3,padding=1), nn.BatchNorm1d(hid),
                                  nn.ReLU(), nn.Conv1d(hid,hid,3,padding=1),
                                  nn.BatchNorm1d(hid), nn.ReLU(), nn.AdaptiveAvgPool1d(1))
        s.h = nn.Sequential(nn.Linear(hid+nctx,96), nn.BatchNorm1d(96), nn.ReLU(),
                            nn.Dropout(0.3), nn.Linear(96,1))
    def forward(s, x, e):
        z = s.r(x)[0][:,-1] if s.kind == "GRU" else s.r(x.transpose(1,2)).squeeze(-1)
        return s.h(torch.cat([z, e], 1)).squeeze(-1)

def _pred(mdl, A, E, bs=8192):
    o=[]
    with torch.no_grad():
        for i in range(0,len(A),bs):
            o.append(torch.sigmoid(mdl(A[i:i+bs].to(DEV), E[i:i+bs].to(DEV))).cpu().numpy())
    return np.concatenate(o)

def train_nn(make, Atr,Etr,ytr, Ava,Eva,yva, Ate,Ete, seed, epochs=25, bs=2048, lr=1e-3):
    torch.manual_seed(seed); np.random.seed(seed)
    mdl = make().to(DEV)
    opt = torch.optim.AdamW(mdl.parameters(), lr=lr, weight_decay=1e-4)
    pw = torch.tensor([(len(ytr)-ytr.sum())/max(ytr.sum(),1)], dtype=torch.float32, device=DEV)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    Atr_c=torch.from_numpy(Atr); Etr_c=torch.from_numpy(Etr); ytr_c=torch.from_numpy(ytr.astype(np.float32))
    Ava_c=torch.from_numpy(Ava); Eva_c=torch.from_numpy(Eva)
    Ate_c=torch.from_numpy(Ate); Ete_c=torch.from_numpy(Ete)
    best,bstate,bad = -1.0,None,0
    for epch in range(epochs):
        mdl.train(); perm = torch.randperm(len(ytr))
        for i in range(0,len(ytr),bs):
            b=perm[i:i+bs]
            if len(b)<16: continue
            xb=Atr_c[b].to(DEV); eb=Etr_c[b].to(DEV); yb=ytr_c[b].to(DEV)
            opt.zero_grad(); lossf(mdl(xb,eb), yb).backward(); opt.step()
            del xb,eb,yb
        mdl.eval(); pv=_pred(mdl,Ava_c,Eva_c)
        a = roc_auc_score(yva,pv) if len(np.unique(yva))>1 else 0.5
        if a>best: best,bad,bstate = a,0,{k:v.detach().cpu().clone() for k,v in mdl.state_dict().items()}
        else:
            bad+=1
            if bad>=5: break
    mdl.load_state_dict(bstate); mdl.to(DEV); mdl.eval()
    p=_pred(mdl,Ate_c,Ete_c)
    del mdl,opt
    if DEV.type=="mps": torch.mps.empty_cache()
    return p

SEEDS=[0,1,2]
MODELS = ["LightGBM(surface,20)","MLP(surface,20)","GRU(opt 8-bar seq)","CNN(opt 8-bar seq)"]
oof = {k: [np.full(len(y),np.nan,np.float32) for _ in (SEEDS if "LightGBM" not in k else [0])]
       for k in MODELS}
t0=time.time()
for i in range(1,5):
    te = (ts>=edges[i]) & (ts<edges[i+1]); tr = ts < (edges[i]-EMB)
    if tr.sum()<50000 or te.sum()<10000: continue
    tri=np.where(tr)[0]; cut=int(len(tri)*0.85); fit,val = tri[:cut],tri[cut:]
    tei=np.where(te)[0]
    print(f"\n fold {i}: train {len(fit):,} val {len(val):,} test {len(tei):,}", flush=True)

    g=lgb.LGBMClassifier(n_estimators=400,learning_rate=0.05,num_leaves=31,max_depth=6,
        min_child_samples=100,subsample=0.8,subsample_freq=1,colsample_bytree=0.8,
        reg_lambda=5.0,random_state=0,n_jobs=6,verbose=-1)
    g.fit(Xs[tri],y[tri],sample_weight=w[tri])
    oof["LightGBM(surface,20)"][0][tei]=g.predict_proba(Xs[tei])[:,1]
    print(f"   LightGBM done ({time.time()-t0:.0f}s)", flush=True)

    sc=StandardScaler().fit(np.nan_to_num(Xs[fit]))
    Z=np.clip(sc.transform(np.nan_to_num(Xs)),-8,8).astype(np.float32)
    scc=StandardScaler().fit(np.nan_to_num(Xc[fit]))
    Zc=np.clip(scc.transform(np.nan_to_num(Xc)),-8,8).astype(np.float32)
    mu,sd = S[fit].mean((0,1)), S[fit].std((0,1)); sd[sd==0]=1
    Sz=np.clip((S-mu)/sd,-8,8).astype(np.float32)

    for si,sdd in enumerate(SEEDS):
        oof["MLP(surface,20)"][si][tei] = train_nn(lambda: MLP(Z.shape[1]),
            Z[fit],Z[fit],y[fit], Z[val],Z[val],y[val], Z[tei],Z[tei], sdd)
    print(f"   MLP done ({time.time()-t0:.0f}s)", flush=True)
    for nm,kind in [("GRU(opt 8-bar seq)","GRU"),("CNN(opt 8-bar seq)","CNN")]:
        for si,sdd in enumerate(SEEDS):
            oof[nm][si][tei] = train_nn(lambda: SeqNet(Zc.shape[1],kind),
                Sz[fit],Zc[fit],y[fit], Sz[val],Zc[val],y[val], Sz[tei],Zc[tei], sdd)
        print(f"   {nm} done ({time.time()-t0:.0f}s)", flush=True)

def p_at_recall(yy,pp,ww,rec=0.15):
    o=np.argsort(-pp); yy,ww=yy[o],ww[o]
    tp=np.cumsum(yy*ww); tot=(yy*ww).sum()
    k=np.searchsorted(tp, tot*rec)
    if k>=len(yy): return np.nan
    return tp[k]/np.cumsum(ww)[k]

def split_auc(yy,pp,ee,ww):
    within=[]
    for e in np.unique(ee):
        m=ee==e
        if m.sum()<20 or len(np.unique(yy[m]))<2: continue
        within.append(roc_auc_score(yy[m],pp[m]))
    d=pd.DataFrame({"e":ee,"y":yy,"p":pp,"w":ww})
    a=d.groupby("e").apply(lambda x: pd.Series({
        "y":float((x.y*x.w).sum()>0),"p":np.average(x.p,weights=x.w)}),include_groups=False)
    bet=roc_auc_score(a.y,a.p) if a.y.nunique()>1 else np.nan
    return (np.mean(within) if within else np.nan), bet

print("\n"+"="*100)
print("OPTIONS SIDE — same folds, weighted metrics")
print("="*100)
print(f"{'model':<24}{'AUC':>16}{'P@15%rec':>16}{'within-ep AUC':>16}{'between-ep AUC':>16}")
for k,arr in oof.items():
    A,P,W,B=[],[],[],[]
    for o in arr:
        ok=np.isfinite(o)
        if ok.sum()<10000: continue
        A.append(roc_auc_score(y[ok],o[ok],sample_weight=w[ok]))
        P.append(p_at_recall(y[ok],o[ok],w[ok]))
        a1,a2=split_auc(y[ok],o[ok],ep[ok],w[ok]); W.append(a1); B.append(a2)
    if not A: continue
    f=lambda v: f"{np.mean(v):.4f}"+(f" +-{np.std(v):.4f}" if len(v)>1 else "        ")
    print(f"{k:<24}{f(A):>16}{f(P):>16}{f(W):>16}{f(B):>16}")
print(f"\nreference from FINDINGS: surface arm AUC 0.9173, P@15% 0.0307, "
      f"within-ep 0.9469, between-ep 0.5745")
print(f"total {time.time()-t0:.0f}s")
