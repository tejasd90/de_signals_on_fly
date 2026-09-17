#!/usr/bin/env python3
"""
phase3_model.py — Phase 3 of docs/ML/CONTEXT_PLAN.md.

LightGBM on the 168 context features. The bar it must clear is not "better than
chance" — it is **better than R4**, a one-line rule. If it cannot beat one line
of Brooks, the rule ships and the model does not.

LEAKAGE GUARDS (each one has cost this project a run before)
  - no column starting with y_ / peak / ratio / label / _   (HANDOFF 3.6)
  - `activated` and `state` describe what happened AFTER entry. They define the
    POPULATION here, never a feature.
  - no raw prices. entry_premium and strike are levels; a tree splitting on
    strike < 67000 has learned a date range. Premium enters only as a ratio to
    spot, which is scale-free.
  - bars_to_peak / n_fwd_bars / trigger_price / ratio_oracle are all outcome-side.

PURGED WALK-FORWARD
Test blocks are always later than train. A training event whose option is still
alive when the test block opens has an outcome that overlaps the test period, so
it is PURGED — dropped, not merely separated by an embargo. Weekly blocks are the
unit throughout, because 142 weeks is the real sample size.
"""
import numpy as np, pandas as pd, lightgbm as lgb, os, json
from sklearn.metrics import roc_auc_score

COST = 0.0826
BAN_PREFIX = ("y_", "peak", "ratio", "label", "_")
BAN_EXACT = {"event_id","spot","expiry","symbol","entry_iso","entry_ts","state",
             "activated","merged_count","bars_to_peak","n_fwd_bars","trigger_price",
             "spot_at_entry","strike","entry_premium","exp_ts","week","year","fwd",
             "ts","h10","h25","ty"}

def ev(hit, T): return hit*(T-1) - (1-hit) - COST

def load():
    cols = None
    parts = []
    for s in ["BTC","ETH"]:
        d = pd.read_parquet(f"events_ctx/{s}.parquet")
        d = d[d.activated & d.entry_premium.between(2,20)]
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["exp_ts"] = pd.to_datetime(d.expiry).astype("int64")//10**9 + 12*3600
    d["tte_h"]  = (d.exp_ts - d.entry_ts)/3600.0
    d["otm"]    = np.where(d.opt_type=="C", d.moneyness_pct, -d.moneyness_pct)
    d["prem_rel"] = d.entry_premium / d.spot_at_entry      # scale-free, not a level
    d["is_call"]  = (d.opt_type=="C").astype(int)
    d["agree4"]   = np.where(d.opt_type=="C", d.cx240_always_in==1, d.cx240_always_in==-1).astype(int)
    # one row per EVENT, REAL convention (mean across the strikes actually bought)
    feat = [c for c in d.columns if c.startswith("cx")] + \
           ["duration","tte_h","otm","prem_rel","is_call","signal_value","agree4"]
    agg = {c: (c,"first") for c in feat}
    agg.update(y25=("y_25x","mean"), y10=("y_10x","mean"),
               ts=("entry_ts","first"), expt=("exp_ts","max"), sig=("signal","first"))
    e = d.groupby("event_id").agg(**agg).reset_index()
    e["week"] = ((e.ts+19800)//604800).astype(int)
    return e, feat

def folds(weeks, n=4, embargo=1):
    u = np.sort(np.unique(weeks)); cut = np.array_split(u, n+1)
    for k in range(1, n+1):
        te = cut[k]; tr_end = te.min() - embargo
        yield np.concatenate(cut[:k]), te, tr_end

def run(e, feat, target="y25", T=25, use_strength=True, topk=0.25, seed=0):
    F = [f for f in feat if use_strength or f != "signal_value"]
    bad = [c for c in F if c.startswith(BAN_PREFIX) or c in BAN_EXACT]
    assert not bad, f"leaky features: {bad}"
    rows = []
    for tr_w, te_w, tr_end in folds(e.week.to_numpy()):
        tr = e[e.week.isin(tr_w)]
        te = e[e.week.isin(te_w)]
        # PURGE: drop training events still alive when the test block opens
        t0 = te.ts.min()
        tr = tr[tr.expt <= t0]
        if len(tr) < 5000 or len(te) < 2000: continue
        y = (tr[target] > 0).astype(int)
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.04, num_leaves=15,
                               max_depth=4, min_child_samples=200, subsample=0.8,
                               colsample_bytree=0.6, reg_lambda=5.0,
                               random_state=seed, verbose=-1)
        m.fit(tr[F], y)
        p = m.predict_proba(te[F])[:,1]
        auc = roc_auc_score((te[target]>0).astype(int), p) if te[target].nunique()>1 else np.nan
        thr = np.quantile(p, 1-topk)
        sel = p >= thr
        W = te.week.nunique()
        ev_model = ev(te[sel][target].mean(), T)
        ev_r4    = ev(te[te.agree4==1][target].mean(), T)
        ev_base  = ev(te[target].mean(), T)
        rows.append(dict(fold=len(rows)+1, n_tr=len(tr), n_te=len(te), weeks=W, auc=auc,
            model_hit=100*te[sel][target].mean(), r4_hit=100*te[te.agree4==1][target].mean(),
            base_hit=100*te[target].mean(),
            model_ev=ev_model, r4_ev=ev_r4, base_ev=ev_base,
            model_pw=ev_model*sel.sum()/W, r4_pw=ev_r4*(te.agree4==1).sum()/W,
            base_pw=ev_base*len(te)/W))
    return pd.DataFrame(rows), m, F

if __name__ == "__main__":
    e, feat = load()
    print(f"events {len(e):,}  weeks {e.week.nunique()}  features {len(feat)}")
    print(f"base hit25 {100*(e.y25>0).mean():.2f}%   R4 keeps {100*(e.agree4==1).mean():.1f}%\n")
    for T, tgt in ((25,"y25"), (10,"y10")):
        for strength in (True, False):
            r, m, F = run(e, feat, tgt, T, use_strength=strength)
            tag = "with strength" if strength else "NO strength"
            print(f"=== target {T}x, {tag} ({len(F)} features) ===")
            print(r[['fold','n_tr','n_te','auc','base_hit','r4_hit','model_hit']].round(3).to_string(index=False))
            print(f"  MEAN  auc {r.auc.mean():.4f} | EV/trade  base {r.base_ev.mean():+.3f}  "
                  f"R4 {r.r4_ev.mean():+.3f}  model {r.model_ev.mean():+.3f}")
            print(f"        profit/week  base {r.base_pw.mean():+.1f}  "
                  f"R4 {r.r4_pw.mean():+.1f}  model {r.model_pw.mean():+.1f}")
            print(f"        model beats R4 on EV in {int((r.model_ev>r.r4_ev).sum())}/{len(r)} folds, "
                  f"on profit/wk in {int((r.model_pw>r.r4_pw).sum())}/{len(r)}\n")
    imp = pd.Series(m.feature_importances_, index=F).sort_values(ascending=False)
    print("top 18 features (last fit):"); print(imp.head(18).to_string())
