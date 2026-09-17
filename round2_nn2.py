#!/usr/bin/env python3
"""
ROUND 2 — the neural nets' BEST SHOT, not a like-for-like rerun.

Round 1 held the input fixed and swapped the model, which is the fair comparison
but also the one most favourable to trees. This round gives the NNs everything a
tree structurally cannot eat:

  * ALL 129 symbols pooled -> ~1.7M samples instead of 46k. NNs are data-hungry
    and the BTC+ETH-only baseline starves them.
  * A learned SYMBOL EMBEDDING, so pooling does not blur symbols together.
  * RAW multi-channel bars (return, hi/cl, lo/cl, cl/op, log volume, realised
    vol) -- volume included, which the Brooks features never used.
  * A 168-bar (one week) lookback instead of a fixed-lookback summary.
  * TWO CROSS-SECTIONAL CHANNELS: the market's median return and its dispersion
    over the same window. A per-row tree cannot see the rest of the market at
    all; this is the one input class that is genuinely new information.
  * A small TRANSFORMER alongside the CNN and GRU, since that is the modern
    answer for sequences.

Baseline to beat: LightGBM on 105 Brooks features, pooled 129 symbols, 24h ->
AUC 0.6840 (FINDINGS 22); BTC+ETH subset 0.7024.
"""
import glob, os, time, numpy as np, pandas as pd, torch, lightgbm as lgb
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import roc_auc_score

torch.set_num_threads(6)
DEV = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
H, L, STRIDE = 24, 168, 6
A, F = 0.15, 0.05
LEV = 1.0/A
C = 8                                   # 6 own channels + 2 market channels
print(f"device {DEV} | lookback {L} bars | {C} channels")

# ---------------------------------------------------------------- per-symbol arrays
inv = pd.read_parquet("perp_inventory.parquet")
syms = [s for s in inv[inv.years >= 1.0].sym if os.path.exists(f"perp_liq_24/{s}.parquet")]
chan, tsarr, sidx = {}, {}, {}
for i, s in enumerate(syms):
    d = pd.read_parquet(f"data/perp_candles/{s}.parquet").drop_duplicates("ts").sort_values("ts")
    d = d[(d.c > 0) & (d.h > 0) & (d.l > 0)]
    if len(d) < 3000: continue
    o,h,l,c,v,t = (d.o.to_numpy(), d.h.to_numpy(), d.l.to_numpy(),
                   d.c.to_numpy(), d.v.to_numpy(), d.ts.to_numpy().astype(np.int64))
    lr = np.zeros(len(d)); lr[1:] = np.log(c[1:]/c[:-1])
    rv = pd.Series(lr).rolling(24).std().fillna(0).to_numpy()
    X = np.column_stack([lr, np.log(h/c), np.log(l/c), np.log(c/o),
                         np.log1p(np.maximum(v,0)), rv]).astype(np.float32)
    chan[s] = X; tsarr[s] = t; sidx[s] = len(sidx)
syms = [s for s in syms if s in chan]
print(f"{len(syms)} symbols loaded ({sum(x.nbytes for x in chan.values())/1e6:.0f} MB)")

# ---------------------------------------------------------------- market channels
grid = np.arange(min(t.min() for t in tsarr.values()),
                 max(t.max() for t in tsarr.values()) + 3600, 3600)
Rm = np.full((len(grid), len(syms)), np.nan, np.float32)
for s in syms:
    j = np.searchsorted(grid, tsarr[s])
    ok = (j >= 0) & (j < len(grid))
    Rm[j[ok], sidx[s]] = chan[s][ok, 0]
mkt_med = np.nan_to_num(np.nanmedian(Rm, axis=1)).astype(np.float32)
mkt_disp = np.nan_to_num(np.nanstd(Rm, axis=1)).astype(np.float32)
del Rm
print(f"market channels on a {len(grid):,}-hour grid")

# ---------------------------------------------------------------- labels
recs = []
for s in syms:
    lq = pd.read_parquet(f"perp_liq_24/{s}.parquet")
    lq = lq[(lq.ts//3600) % STRIDE == 0]
    ta = lq[f"tadv_{A*100:g}pct"].to_numpy(); tf = lq[f"tfav_{F*100:g}pct"].to_numpy()
    win = (tf < ta) & (tf <= H); liqd = (ta < tf) & (ta <= H)
    held = np.where(win, tf, np.where(liqd, ta, H)).astype(np.float32)
    sg = np.where(lq["dir"].to_numpy() == "long", 1.0, -1.0).astype(np.float32)
    tret = lq.tret.to_numpy()*sg
    gross = np.where(win, LEV*F, np.where(liqd, -1.0, LEV*tret)) - LEV*0.0001*(held/8.0)
    pos = np.searchsorted(tsarr[s], lq.ts.to_numpy())
    gpos = np.searchsorted(grid, lq.ts.to_numpy())
    keep = (pos >= L) & (pos < len(tsarr[s])) & (gpos >= L)
    recs.append(pd.DataFrame(dict(
        sid=sidx[s], pos=pos[keep], gpos=gpos[keep], ts=lq.ts.to_numpy()[keep],
        y=win.astype(np.int8)[keep], isl=(sg[keep] > 0).astype(np.float32),
        net=(gross[keep] - LEV*0.0004).astype(np.float32),
        is_be=1 if s in ("BTCUSD","ETHUSD") else 0)))
M = pd.concat(recs, ignore_index=True).sort_values("ts").reset_index(drop=True)
print(f"{len(M):,} labelled samples | positives {M.y.mean()*100:.1f}% | "
      f"BTC+ETH {int(M.is_be.sum()):,}")
CH = [chan[s] for s in syms]
MU = np.concatenate([x[::37] for x in CH]).mean(0); SD = np.concatenate([x[::37] for x in CH]).std(0)
SD[SD == 0] = 1.0
mm, ms = mkt_med.std() or 1.0, mkt_disp.std() or 1.0

class DS(Dataset):
    def __init__(s, idx): s.i = idx.reset_index(drop=True)
    def __len__(s): return len(s.i)
    def __getitem__(s, k):
        r = s.i.iloc[k]
        w = (CH[int(r.sid)][int(r.pos)-L:int(r.pos)] - MU)/SD
        g0 = int(r.gpos)
        a = (mkt_med[g0-L:g0]/mm)[:, None]
        b = (mkt_disp[g0-L:g0]/ms)[:, None]
        if len(a) < L: a = np.zeros((L,1),np.float32); b = np.zeros((L,1),np.float32)
        x = np.concatenate([w, a, b], 1).astype(np.float32)
        return (torch.from_numpy(np.clip(x,-8,8)), int(r.sid),
                np.float32(r.isl), np.float32(r.y))

class Seq(nn.Module):
    def __init__(s, kind, nsym, hid=96, emb=16):
        super().__init__()
        s.kind = kind; s.e = nn.Embedding(nsym, emb)
        if kind == "CNN":
            s.b = nn.Sequential(
                nn.Conv1d(C,hid,5,padding=4,dilation=2), nn.BatchNorm1d(hid), nn.ReLU(),
                nn.Conv1d(hid,hid,5,padding=8,dilation=4), nn.BatchNorm1d(hid), nn.ReLU(),
                nn.Conv1d(hid,hid,5,padding=16,dilation=8), nn.BatchNorm1d(hid), nn.ReLU(),
                nn.AdaptiveAvgPool1d(1))
        elif kind == "GRU":
            s.b = nn.GRU(C, hid, num_layers=2, batch_first=True, dropout=0.2)
        else:
            s.inp = nn.Linear(C, hid)
            s.pe = nn.Parameter(torch.randn(1, L, hid)*0.02)
            s.b = nn.TransformerEncoder(
                nn.TransformerEncoderLayer(hid, 4, hid*2, 0.1, batch_first=True,
                                           norm_first=True), 2)
        s.h = nn.Sequential(nn.Linear(hid+emb+1,96), nn.ReLU(), nn.Dropout(0.2), nn.Linear(96,1))
    def forward(s, x, sid, d):
        if s.kind == "CNN": z = s.b(x.transpose(1,2)).squeeze(-1)
        elif s.kind == "GRU": z = s.b(x)[0][:,-1]
        else: z = s.b(s.inp(x)+s.pe).mean(1)
        return s.h(torch.cat([z, s.e(sid), d[:,None]],1)).squeeze(-1)

def run(kind, tr_i, va_i, te_i, seed, epochs=8, bs=512):
    torch.manual_seed(seed); np.random.seed(seed)
    mdl = Seq(kind, len(syms)).to(DEV)
    opt = torch.optim.AdamW(mdl.parameters(), lr=1e-3, weight_decay=1e-4)
    yt = tr_i.y.to_numpy()
    pw = torch.tensor([(len(yt)-yt.sum())/max(yt.sum(),1)], dtype=torch.float32, device=DEV)
    lf = nn.BCEWithLogitsLoss(pos_weight=pw)
    dl = DataLoader(DS(tr_i), batch_size=bs, shuffle=True, num_workers=0, drop_last=True)
    vl = DataLoader(DS(va_i), batch_size=2048, shuffle=False)
    tl = DataLoader(DS(te_i), batch_size=2048, shuffle=False)
    def pred(loader):
        mdl.eval(); o=[]
        with torch.no_grad():
            for x,sid,d,_ in loader:
                o.append(torch.sigmoid(mdl(x.to(DEV),sid.to(DEV),d.to(DEV))).cpu().numpy())
        return np.concatenate(o)
    best,bstate,bad = -1.0,None,0
    for ep in range(epochs):
        mdl.train()
        for x,sid,d,yb in dl:
            opt.zero_grad()
            lf(mdl(x.to(DEV),sid.to(DEV),d.to(DEV)), yb.to(DEV)).backward(); opt.step()
        a = roc_auc_score(va_i.y.to_numpy(), pred(vl))
        print(f"      {kind} ep{ep+1} val AUC {a:.4f}", flush=True)
        if a>best: best,bad,bstate = a,0,{k:v.detach().cpu().clone() for k,v in mdl.state_dict().items()}
        else:
            bad+=1
            if bad>=3: break
    mdl.load_state_dict(bstate); mdl.to(DEV)
    p = pred(tl)
    del mdl,opt
    if DEV.type=="mps": torch.mps.empty_cache()
    return p

edges=np.quantile(M.ts.to_numpy(), np.linspace(0,1,6))
res={k:{"pool":[], "be":[], "ev":[]} for k in ["CNN","GRU"]}
import json as _j
t0=time.time()
for i in range(1,5):
    lo,hi = edges[i], edges[i+1]
    tem = (M.ts>=lo)&(M.ts<hi); trm = M.ts < (lo-H*3600)
    if trm.sum()<50000 or tem.sum()<20000: continue
    tri=M[trm]; cut=int(len(tri)*0.85)
    tr_i, va_i, te_i = tri.iloc[:cut], tri.iloc[cut:], M[tem]
    if len(tr_i) > 250000: tr_i = tr_i.sample(250000, random_state=0).sort_values('ts')
    print(f"\n fold {i}: train {len(tr_i):,} val {len(va_i):,} test {len(te_i):,}", flush=True)
    yte=te_i.y.to_numpy(); bete=te_i.is_be.to_numpy().astype(bool); nette=te_i.net.to_numpy()
    for kind in ["CNN","GRU"]:
        p=run(kind, tr_i, va_i, te_i, seed=0)
        res[kind]["pool"].append(roc_auc_score(yte,p))
        if bete.sum()>500: res[kind]["be"].append(roc_auc_score(yte[bete],p[bete]))
        thr=np.quantile(p,0.95); res[kind]["ev"].append(nette[p>=thr].mean())
        print(f"   {kind}: pooled AUC {res[kind]['pool'][-1]:.4f}  "
              f"BTC+ETH {res[kind]['be'][-1] if res[kind]['be'] else float('nan'):.4f}"
              f"  ({time.time()-t0:.0f}s)", flush=True)
        _j.dump({k:{kk:[float(x) for x in vv] for kk,vv in v.items()} for k,v in res.items()},
                open("runs/round2_nn_partial.json","w"), indent=1)

print("\n"+"="*84)
print("ROUND 2 — NNs given pooled data, symbol embeddings, volume and market context")
print("="*84)
print(f"{'model':<32}{'pooled AUC':>16}{'BTC+ETH AUC':>16}{'top5% EV':>14}")
for k,v in res.items():
    if not v["pool"]: continue
    pa=np.array(v["pool"]); ba=np.array(v["be"]) if v["be"] else np.array([np.nan])
    ev=np.array(v["ev"]) if v["ev"] else np.array([np.nan])
    print(f"{k:<32}{pa.mean():>10.4f}+-{pa.std():.3f}{ba.mean():>10.4f}+-{ba.std():.3f}"
          f"{np.nanmean(ev):>+14.4f}")
import json; t=json.load(open("runs/round2_tree.json"))
print(f"\nTREE BASELINE measured today: pooled {t['pooled_auc']:.4f} | BTC+ETH subset {t['btceth_auc']:.4f}")
print(f"total {time.time()-t0:.0f}s")
