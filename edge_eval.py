#!/usr/bin/env python3
"""
edge_eval.py — is there a VERIFIABLE EDGE, measured in money?

Everything upstream measures P(peak >= T). This measures expectancy:

    R(T) = T           if peak >= T   (limit at T fills on the way up)
         = stop_ratio  otherwise      (exit at the stop candle's close)

Costs are charged on both legs as a fraction of premium staked.

VALIDATION: purged walk-forward. Every test block is later in time than its
training data and no episode spans the boundary. All numbers reported are
out-of-fold. The random-entry row is the SAME population unfiltered, which is
the honest null: disc_final is a mechanical sweep, not signal-fired rows.
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd, duckdb
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

# "label" (bare) is disc_final's 5x label and does NOT match "label_".
# Match the PREFIX "label", not "label_", or it walks straight into the model.
LEAK_PREFIX = ("label", "_")
DROP = {"symbol","expiry","spot","signal","duration","episode_id",
        "stop_ratio","entry_px","held","stopped","peak_sim",
        # `y` is the label. It is numeric and matches no prefix rule, so it
        # slips into the feature list and yields AUC exactly 1.000 (HANDOFF 3.6).
        "y","peak","ts"}

def load(arm, memlimit="4GB"):
    c = duckdb.connect(); c.execute(f"SET memory_limit='{memlimit}'; SET threads=5;")
    q = """SELECT d.*, e.stop_ratio, e.entry_px, e.held, e.stopped
           FROM 'disc_final/*.parquet' d
           JOIN 'exits/*.parquet' e ON d.symbol=e.symbol
            AND CAST(round(CAST(d._ts_hours AS DOUBLE)*3600) AS BIGINT)=e.ts"""
    df = c.execute(q).df()
    assert len(df) == 942769, f"join lost rows: {len(df)}"
    return df

def pick_features(df, arm):
    num = df.select_dtypes(include=[np.number]).columns
    feats = [x for x in num if not x.startswith(LEAK_PREFIX) and x not in DROP]
    ctx = [x for x in feats if not x.startswith(("opt_","spot_","surf_"))]
    surf = [x for x in feats if x.startswith("surf_")]
    sp  = [x for x in feats if x.startswith("spot_")]
    op  = [x for x in feats if x.startswith("opt_")]
    return {"context":ctx, "surface":ctx+surf, "spot_shape":ctx+sp,
            "signals":ctx+op, "all":ctx+surf+sp+op,
            "surface_only":surf, "nocheap":[x for x in ctx if x!="cheapness"]+surf}[arm]

def purged_folds(df, n_folds=5, embargo_frac=0.01):
    ep = df.groupby("episode_id")["_ts_hours"].min().sort_values()
    eps = ep.index.to_numpy(); n = len(eps)
    bounds = np.linspace(0, n, n_folds+1).astype(int)
    embargo = max(1, int(n*embargo_frac))
    out=[]
    for i in range(1, n_folds):
        tr_eps=set(eps[:max(0,bounds[i]-embargo)]); te_eps=set(eps[bounds[i]:bounds[i+1]])
        if not tr_eps or not te_eps: continue
        out.append((df.index[df.episode_id.isin(tr_eps)].to_numpy(),
                    df.index[df.episode_id.isin(te_eps)].to_numpy()))
    return out

def expectancy(peak, stop_ratio, w, T, cost):
    """Mean R per unit premium staked, minus round-trip cost."""
    hit = peak >= T
    R = np.where(hit, float(T), stop_ratio) - cost
    return np.average(R, weights=w), np.average(hit, weights=w)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--arm", default="surface")
    ap.add_argument("--target", type=float, default=25.0)
    ap.add_argument("--cost", type=float, default=0.02,
                    help="round-trip cost as fraction of premium staked")
    ap.add_argument("--out", default=None)
    a=ap.parse_args()

    t0=time.time()
    print(f"loading + joining exits ...", flush=True)
    df = load(a.arm)
    lab = f"label_{str(a.target).replace('.','_')}"
    df["y"] = df[lab].astype(np.int8)
    feats = pick_features(df, a.arm)
    bad = [f for f in feats if f.startswith("label") or f.startswith("_")
           or f in ("y","peak","stop_ratio","entry_px","held","stopped")]
    assert not bad, f"LABEL/OUTCOME LEAKED INTO FEATURES: {bad}"
    print(f"  features: {feats}")
    print(f"rows {len(df):,} | arm '{a.arm}' | {len(feats)} features | target {a.target}x")
    print(f"episodes {df.episode_id.nunique():,} | positive episodes "
          f"{df.groupby('episode_id')['y'].max().sum():,}")

    folds = purged_folds(df)
    oof = np.full(len(df), np.nan)
    for k,(tr,te) in enumerate(folds,1):
        m = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=63,
                               min_child_samples=200, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, reg_lambda=1.0,
                               n_jobs=5, verbose=-1)
        m.fit(df.loc[tr,feats], df.loc[tr,"y"], sample_weight=df.loc[tr,"_w"])
        oof[te] = m.predict_proba(df.loc[te,feats])[:,1]
        print(f"  fold {k}: train {len(tr):,} test {len(te):,} "
              f"AUC {roc_auc_score(df.loc[te,'y'], oof[te], sample_weight=df.loc[te,'_w']):.4f}",
              flush=True)
    df["score"]=oof
    ev = df[np.isfinite(df.score)].copy()
    print(f"\nout-of-fold rows: {len(ev):,}")

    w  = ev["_w"].to_numpy(float)
    pk = ev["_peak"].to_numpy(float)
    sr = ev["stop_ratio"].to_numpy(float)
    sc = ev["score"].to_numpy(float)
    order = np.argsort(-sc)

    print(f"\n{'='*86}")
    print(f"EXPECTANCY BY SELECTIVITY — target {a.target:g}x, cost {a.cost:.1%} of premium")
    print(f"{'='*86}")
    print(f"{'slice':>10}{'rows':>10}{'hit%':>9}{'meanR':>9}{'exp/trade':>11}"
          f"{'stop@miss':>11}{'edge vs rnd':>13}")
    print("-"*86)
    base_R, base_hit = expectancy(pk, sr, w, a.target, a.cost)
    rows=[]
    for frac in [0.001,0.002,0.005,0.01,0.02,0.05,0.10,0.20]:
        k=max(1,int(len(order)*frac)); idx=order[:k]
        R,hit = expectancy(pk[idx], sr[idx], w[idx], a.target, a.cost)
        miss = pk[idx] < a.target
        sm = np.average(sr[idx][miss], weights=w[idx][miss]) if miss.any() else float('nan')
        rows.append((frac,k,hit,R,sm))
        print(f"{frac:>9.1%}{k:>10,}{hit*100:>9.3f}{R:>9.4f}{R-1:>+11.4f}"
              f"{sm:>11.4f}{(R-base_R):>+13.4f}")
    print("-"*86)
    miss=pk<a.target
    sm=np.average(sr[miss],weights=w[miss])
    print(f"{'RANDOM':>9}{len(order):>10,}{base_hit*100:>9.3f}{base_R:>9.4f}"
          f"{base_R-1:>+11.4f}{sm:>11.4f}{0.0:>+13.4f}")
    print(f"\nBreak-even hit rate at {a.target:g}x needs P > "
          f"{(1+a.cost-sm)/(a.target-sm):.4%}  (given {sm:.3f} recovered on misses)")
    if a.out:
        ev[["symbol","_ts_hours","score","_peak","stop_ratio","_w","episode_id"]]\
            .to_parquet(a.out, index=False)
        print(f"wrote {a.out}")
    print(f"\n{(time.time()-t0)/60:.1f} min")

if __name__=="__main__":
    main()
