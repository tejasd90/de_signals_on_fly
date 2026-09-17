#!/usr/bin/env python3
"""
Q1 part 2 — the two things the first script did not cover:
  (A) Tejas's actual hypothesis: does otm_wall (or any hand signal) work better
      in a SIDEWAYS market? Measured on the patterns dataset, same causal labels.
  (B) The strategy that is actually still alive — the 24h futures classifier —
      conditioned on BTC regime. Reuses runs/step12_full.pkl, no retraining.
"""
import pickle, numpy as np, pandas as pd, duckdb
from q1_regimes import tag, AXES, REG          # reuse the causal labels

RNG = np.random.default_rng(1)
print("\n" + "=" * 78)
print("(A) THE HAND SIGNALS BY REGIME  — 'otm_wall works in sideways'")
print("=" * 78)
c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
p = c.execute("""SELECT signal, spot, _ts_hours, ratio, _w, tteHours, cheapness
                 FROM 'dataset_parts/*.parquet' WHERE ratio IS NOT NULL""").df()
print(f"  patterns rows {len(p):,}  weighted {p._w.sum():,.0f}")
p["blk"] = (p._ts_hours // (24*7)).astype(int)
for axis in ["trend20", "vol20", "pos60"]:
    p[axis] = "na"
    for sp in p.spot.unique():
        s = p.spot == sp
        if sp in REG: p.loc[s, axis] = tag(sp, p.loc[s, "_ts_hours"].to_numpy(), axis)

def wboot(g, col, thr, n=2000):
    y = (g[col].to_numpy() >= thr).astype(float); w = g._w.to_numpy()
    b = g.blk.to_numpy(); ub = np.unique(b); out = []
    for _ in range(n):
        pk = RNG.choice(ub, len(ub), replace=True)
        idx = np.concatenate([np.where(b == q)[0] for q in pk])
        if len(idx) < 50: continue
        out.append(np.average(y[idx], weights=w[idx]))
    return np.array(out)

for axis in ["trend20", "pos60"]:
    print(f"\n  --- {axis} ---")
    print(f"  {'signal':>16}{'state':>12}{'rows':>9}{'10x':>8}{'25x':>8}"
          f"{'25x 95% CI':>22}")
    for sg, gg in p.groupby("signal"):
        base10 = np.average(gg.ratio >= 10, weights=gg._w) * 100
        base25 = np.average(gg.ratio >= 25, weights=gg._w) * 100
        print(f"  {sg:>16}{'ALL':>12}{len(gg):>9,}{base10:>7.2f}%{base25:>7.2f}%")
        for st, g in gg.groupby(axis):
            if st == "na" or len(g) < 1500: continue
            bs = wboot(g, "ratio", 25)
            print(f"  {'':>16}{st:>12}{len(g):>9,}"
                  f"{np.average(g.ratio>=10, weights=g._w)*100:>7.2f}%"
                  f"{np.average(g.ratio>=25, weights=g._w)*100:>7.2f}%"
                  f"   [{np.percentile(bs,2.5)*100:5.2f}%,{np.percentile(bs,97.5)*100:5.2f}%]")
del p

print("\n" + "=" * 78)
print("(B) THE 24h FUTURES CLASSIFIER BY BTC REGIME  (BTC+ETH, maker fees)")
print("=" * 78)
res = pickle.load(open("runs/step12_full.pkl", "rb"))
keys = [k for k in res if k[0] == "BTC+ETH only"]
btc_ts, btc_R = REG["BTC"]
def btag(ts_sec, axis):
    j = np.searchsorted(btc_ts, ts_sec.astype(float), side="right") - 1
    v = btc_R[axis].to_numpy(dtype=object)
    return np.where(j < 0, "na", v[np.clip(j, 0, len(v)-1)])

for k in keys:
    o = res[k]; L = o["L"]
    ts, cal, gross, ok = o["ts"], o["cal"], o["gross"], o["ok"]
    net = gross - L * 0.0004                      # maker/maker
    thr = np.quantile(cal[ok], 0.95)
    sel = ok & (cal >= thr)
    print(f"\n  --- stop -{o['A']*100:g}% / target +{o['F']*100:g}%  {L:.1f}x  "
          f"AUC {o['auc']:.4f}  (top-5%, maker) ---")
    for axis in ["trend20", "vol20", "pos60", "dir20"]:
        rg = btag(ts, axis)
        print(f"    {axis}:")
        for st in sorted(set(rg[sel])):
            if st == "na": continue
            m = sel & (rg == st)
            if m.sum() < 400: continue
            r = net[m]; b = (ts[m] // (7*86400)).astype(int); ub = np.unique(b)
            mu = np.array([r[np.isin(b, RNG.choice(ub, len(ub), replace=True))].mean()
                           for _ in range(2000)])
            print(f"      {st:>12}  n={m.sum():>6,}  EV {r.mean():>+8.4f}"
                  f"  [{np.percentile(mu,2.5):+.4f},{np.percentile(mu,97.5):+.4f}]"
                  f"  wks={len(ub):>4}")
