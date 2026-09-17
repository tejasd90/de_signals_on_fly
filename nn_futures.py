#!/usr/bin/env python3
"""
DOES A NEURAL NET BEAT THE TREES? Measured, not asserted.

HANDOFF section 4 says "trees, not neural nets" with a reason but no number.
Same dataset, same label, same purged walk-forward folds, same metrics as
step1b.py -- only the model varies.

  1. LightGBM    105 Brooks features  <- the 0.7024 baseline, reproduced
  2. MLP         105 Brooks features  <- same input, different function class
  3. 1D-CNN      raw 96-bar OHLCV     <- learns its own features
  4. GRU         raw 96-bar OHLCV     <- the "RNN for timeseries" claim
  5. LSTM        raw 96-bar OHLCV

MEMORY: 8GB machine. Fold-sized arrays are NEVER copied -- training slices one
batch at a time straight out of the shared arrays. An earlier version copied
each fold three times per model per seed and the OS killed it.
"""
import gc, os, time, numpy as np, pandas as pd, lightgbm as lgb, torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

torch.set_num_threads(6)
DEV = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
H, STRIDE, L = 24, 2, 96
A, F = 0.15, 0.05
LEV = 1.0/A
SYMS = ["BTCUSD", "ETHUSD"]
SEEDS = [0, 1]
print(f"device {DEV} | horizon {H}h | lookback {L} | stop -{A*100:g}%/+{F*100:g}%", flush=True)

frames, candles = [], {}
for s in SYMS:
    m = (pd.read_parquet(f"perp_liq_24/{s}.parquet")
           .merge(pd.read_parquet(f"perp_brooks/{s}.parquet"), on=["sym","ts"], how="inner"))
    frames.append(m[(m.ts//3600) % STRIDE == 0])
    candles[s] = (pd.read_parquet(f"data/perp_candles/{s}.parquet")
                    .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))
m = pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)
del frames
m["is_long"] = (m["dir"] == "long").astype(np.int8)
feats = [c for c in m.columns if c.startswith("bk_")]

ta = m[f"tadv_{A*100:g}pct"].to_numpy(); tf = m[f"tfav_{F*100:g}pct"].to_numpy()
win = (tf < ta) & (tf <= H); liq = (ta < tf) & (ta <= H)
held = np.where(win, tf, np.where(liq, ta, H)).astype(np.float32)
sg = np.where(m.is_long == 1, 1.0, -1.0).astype(np.float32)
tret = (m.tret.to_numpy()*sg).astype(np.float32)
Y = win.astype(np.int8); TS = m.ts.to_numpy()
NET = (np.where(win, LEV*F, np.where(liq, -1.0, LEV*tret))
       - LEV*0.0001*(held/8.0) - LEV*0.0004).astype(np.float32)
XTAB = np.ascontiguousarray(m[feats].to_numpy(np.float32))
XTAB[~np.isfinite(XTAB)] = np.nan
D = m.is_long.to_numpy(np.float32)
XLGB = np.column_stack([XTAB, D])
print(f"rows {len(m):,}  positives {Y.mean()*100:.1f}%", flush=True)

SEQ = np.zeros((len(m), L, 5), np.float32); OKS = np.zeros(len(m), bool)
for s in SYMS:
    c = candles[s]; cts = c.ts.to_numpy()
    o,h,l,cl,v = (c.o.to_numpy(), c.h.to_numpy(), c.l.to_numpy(), c.c.to_numpy(), c.v.to_numpy())
    lr = np.zeros(len(c)); lr[1:] = np.log(np.maximum(cl[1:],1e-9)/np.maximum(cl[:-1],1e-9))
    base = np.column_stack([lr, np.log(np.maximum(h,1e-9)/np.maximum(cl,1e-9)),
                            np.log(np.maximum(l,1e-9)/np.maximum(cl,1e-9)),
                            np.log(np.maximum(cl,1e-9)/np.maximum(o,1e-9)),
                            np.log1p(np.maximum(v,0))]).astype(np.float32)
    idx = np.where((m.sym == s).to_numpy())[0]
    pos = np.searchsorted(cts, TS[idx])
    for r, p in zip(idx, pos):
        if p < L or p >= len(c): continue
        w = base[p-L:p]
        sd = w.std(0); sd[sd == 0] = 1.0
        SEQ[r] = (w - w.mean(0))/sd
        OKS[r] = True
del candles, m
gc.collect()
print(f"sequences for {OKS.mean()*100:.1f}% of rows ({SEQ.nbytes/1e6:.0f} MB)", flush=True)

class MLP(nn.Module):
    def __init__(s, d, hid=128):
        super().__init__()
        s.f = nn.Sequential(nn.Linear(d,hid), nn.BatchNorm1d(hid), nn.ReLU(), nn.Dropout(0.3),
                            nn.Linear(hid,64), nn.BatchNorm1d(64), nn.ReLU(), nn.Dropout(0.3),
                            nn.Linear(64,1))
    def forward(s,x,d): return s.f(torch.cat([x,d[:,None]],1)).squeeze(-1)

class CNN(nn.Module):
    def __init__(s, ch=5, k=32):
        super().__init__()
        s.c = nn.Sequential(nn.Conv1d(ch,k,5,padding=2), nn.BatchNorm1d(k), nn.ReLU(), nn.MaxPool1d(2),
                            nn.Conv1d(k,k*2,5,padding=2), nn.BatchNorm1d(k*2), nn.ReLU(), nn.MaxPool1d(2),
                            nn.Conv1d(k*2,k*2,3,padding=1), nn.BatchNorm1d(k*2), nn.ReLU(),
                            nn.AdaptiveAvgPool1d(1))
        s.h = nn.Sequential(nn.Linear(k*2+1,64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64,1))
    def forward(s,x,d): return s.h(torch.cat([s.c(x.transpose(1,2)).squeeze(-1), d[:,None]],1)).squeeze(-1)

class RNNet(nn.Module):
    def __init__(s, kind="GRU", ch=5, hid=64):
        super().__init__()
        s.r = (nn.GRU if kind=="GRU" else nn.LSTM)(ch, hid, batch_first=True)
        s.d = nn.Dropout(0.2)
        s.h = nn.Sequential(nn.Linear(hid+1,64), nn.ReLU(), nn.Dropout(0.3), nn.Linear(64,1))
    def forward(s,x,d): return s.h(torch.cat([s.d(s.r(x)[0][:,-1]), d[:,None]],1)).squeeze(-1)

def fit_predict(make, SRC, fit_i, val_i, te_i, seed, epochs=35, bs=512, lr=1e-3, pat=7):
    """SRC is the SHARED array. Only one batch is ever materialised."""
    torch.manual_seed(seed); np.random.seed(seed)
    mdl = make().to(DEV)
    opt = torch.optim.AdamW(mdl.parameters(), lr=lr, weight_decay=1e-4)
    yf = Y[fit_i].astype(np.float32)
    pw = torch.tensor([(len(yf)-yf.sum())/max(yf.sum(),1.0)], dtype=torch.float32, device=DEV)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pw)
    def infer(idx, chunk=4096):
        mdl.eval(); out=[]
        with torch.no_grad():
            for i in range(0, len(idx), chunk):
                b = idx[i:i+chunk]
                xb = torch.from_numpy(SRC[b]).to(DEV); db = torch.from_numpy(D[b]).to(DEV)
                out.append(torch.sigmoid(mdl(xb, db)).cpu().numpy())
                del xb, db
        return np.concatenate(out) if out else np.array([])
    yva = Y[val_i]; best, bstate, bad = -1.0, None, 0
    for ep in range(epochs):
        mdl.train(); perm = np.random.permutation(len(fit_i))
        for i in range(0, len(perm), bs):
            b = fit_i[perm[i:i+bs]]
            if len(b) < 16: continue
            xb = torch.from_numpy(SRC[b]).to(DEV)
            db = torch.from_numpy(D[b]).to(DEV)
            yb = torch.from_numpy(Y[b].astype(np.float32)).to(DEV)
            opt.zero_grad(); lossf(mdl(xb, db), yb).backward(); opt.step()
            del xb, db, yb
        a = roc_auc_score(yva, infer(val_i)) if len(np.unique(yva)) > 1 else 0.5
        if a > best:
            best, bad = a, 0
            bstate = {k: v.detach().cpu().clone() for k, v in mdl.state_dict().items()}
        else:
            bad += 1
            if bad >= pat: break
    mdl.load_state_dict(bstate); mdl.to(DEV)
    p = infer(te_i)
    del mdl, opt, bstate
    gc.collect()
    if DEV.type == "mps": torch.mps.empty_cache()
    return p

MODELS = ["LightGBM(105 Brooks)","MLP(105 Brooks)","CNN(raw OHLCV)","GRU(raw OHLCV)","LSTM(raw OHLCV)"]
oof = {k: [np.full(len(Y), np.nan, np.float32)
           for _ in (SEEDS if "LightGBM" not in k else [0])] for k in MODELS}
edges = np.quantile(TS, np.linspace(0,1,6)); t0 = time.time()
for i in range(1,5):
    te = (TS>=edges[i]) & (TS<edges[i+1]); tr = TS < (edges[i]-H*3600)
    if tr.sum()<5000 or te.sum()<1000: continue
    tri = np.where(tr)[0]; cut = int(len(tri)*0.85)
    fit_i, val_i, te_i = tri[:cut], tri[cut:], np.where(te)[0]
    print(f"\n fold {i}: train {len(fit_i):,} val {len(val_i):,} test {len(te_i):,}", flush=True)

    g = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, max_depth=4,
        min_child_samples=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.6,
        reg_lambda=20.0, random_state=0, n_jobs=6, verbose=-1)
    g.fit(XLGB[tri], Y[tri])
    oof["LightGBM(105 Brooks)"][0][te_i] = g.predict_proba(XLGB[te_i])[:,1]
    del g; gc.collect()
    print(f"   LightGBM ({time.time()-t0:.0f}s)", flush=True)

    sc = StandardScaler().fit(np.nan_to_num(XTAB[fit_i]))
    XS = np.ascontiguousarray(np.clip(sc.transform(np.nan_to_num(XTAB)), -8, 8).astype(np.float32))
    for si, sd in enumerate(SEEDS):
        oof["MLP(105 Brooks)"][si][te_i] = fit_predict(lambda: MLP(XS.shape[1]+1), XS,
                                                        fit_i, val_i, te_i, sd)
    del XS, sc; gc.collect()
    print(f"   MLP ({time.time()-t0:.0f}s)", flush=True)

    f_s = fit_i[OKS[fit_i]]; v_s = val_i[OKS[val_i]]; t_s = te_i[OKS[te_i]]
    for nm, mk in [("CNN(raw OHLCV)", lambda: CNN()),
                   ("GRU(raw OHLCV)", lambda: RNNet("GRU")),
                   ("LSTM(raw OHLCV)", lambda: RNNet("LSTM"))]:
        for si, sd in enumerate(SEEDS):
            oof[nm][si][t_s] = fit_predict(mk, SEQ, f_s, v_s, t_s, sd)
        print(f"   {nm} ({time.time()-t0:.0f}s)", flush=True)

print("\n" + "="*92)
print("ROUND 1 — identical folds, label and metrics. EV is top-5%, maker/maker net.")
print("="*92)
print(f"{'model':<24}{'AUC':>18}{'top5% win%':>13}{'top5% EV':>20}")
for name, arr in oof.items():
    A_,E_,W_ = [],[],[]
    for o in arr:
        ok = np.isfinite(o)
        if ok.sum() < 1000: continue
        A_.append(roc_auc_score(Y[ok], o[ok]))
        thr = np.quantile(o[ok], 0.95); sel = ok & (o >= thr)
        E_.append(NET[sel].mean()); W_.append(Y[sel].mean()*100)
    if not A_: continue
    a=np.array(A_); e=np.array(E_)
    sa = f"{a.mean():.4f}" + (f" +-{a.std():.4f}" if len(a)>1 else "")
    se = f"{e.mean():+.4f}" + (f" +-{e.std():.4f}" if len(e)>1 else "")
    print(f"{name:<24}{sa:>18}{np.mean(W_):>12.1f}%{se:>20}")
print("\nreference (FINDINGS 22): LightGBM BTC+ETH 24h = AUC 0.7024")
np.savez_compressed("runs/nn_futures_oof.npz", Y=Y, TS=TS, NET=NET,
    **{k.split("(")[0]+"_"+str(j): v[j] for k,v in oof.items() for j in range(len(v))})
print(f"total {time.time()-t0:.0f}s -> runs/nn_futures_oof.npz")
