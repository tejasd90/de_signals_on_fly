#!/usr/bin/env python3
"""
THE DECIDING TEST for Q1+Q2. Conditioning tables are not decisions. The decision
is: take the policy that is actually traded (global top-0.5% by score), apply a
filter, and ask whether the SAME WEEKS do better with it than without.

Paired weekly-block bootstrap -- the filtered and unfiltered arms are evaluated
on identical resampled weeks, so week-to-week noise cancels and the CI is on the
DIFFERENCE, which is the only quantity that can justify a rule.

Also reported: trades retained, and profit per WEEK (filtering buys per-trade EV
by giving up opportunities, and the objective is the product, not the factor).
"""
import os, numpy as np, pandas as pd, duckdb
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from q1_regimes import tag, REG
RNG = np.random.default_rng(11); T = 25.0

o = pd.read_parquet("runs/oof_surface_25.parquet")
o["sp"]  = o.symbol.str.split("-").str[1]
o["R"]   = np.where(o._peak >= T, T, o.stop_ratio) - 0.05
o["hit"] = (o._peak >= T).astype(int)
o["day"] = (o._ts_hours // 24).astype(int)
o["blk"] = (o._ts_hours // (24*7)).astype(int)
for axis in ["trend20","vol20","pos60","dir20"]:
    o[axis] = "na"
    for sp in o.sp.unique():
        if sp not in REG: continue
        m = (o.sp == sp).to_numpy()
        o.loc[m, axis] = tag(sp, o.loc[m, "_ts_hours"].to_numpy(), axis)

# unsupervised labels, refit here (fit on first half of time only)
b = pd.read_parquet("brooks_spot.parquet")
bf = [c for c in b.columns if c.startswith("bk_")]
b["day"] = (b.ts // 86400).astype(int)
d = b.sort_values("ts").groupby(["spot","day"]).last().reset_index()
X = d[bf].to_numpy(np.float32); X = np.where(np.isfinite(X), X, np.nan)
X = np.where(np.isnan(X), np.nanmedian(X, axis=0), X)
cut = np.quantile(d.ts, 0.5); tr = d.ts.to_numpy() < cut
Z = StandardScaler().fit(X[tr]).transform(X)
P = PCA(12, random_state=0).fit(Z[tr]).transform(Z)
d["km5"] = KMeans(5, n_init=10, random_state=0).fit(P[tr]).predict(P)
o["km5"] = -1
for sp, g in d.groupby("spot"):
    g = g.sort_values("day"); m = (o.sp == sp).to_numpy()
    if not m.any(): continue
    j = np.searchsorted(g.day.to_numpy(), o.day.to_numpy()[m], side="left") - 1
    ok = j >= 0
    o.loc[np.where(m)[0][ok], "km5"] = g.km5.to_numpy()[j[ok]]

c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
sf = [x for x in c.execute("DESCRIBE SELECT * FROM 'disc_final/part-00000.parquet' LIMIT 1"
      ).df().column_name if x.startswith("surf_")]
S = c.execute(f"SELECT symbol,_ts_hours,{','.join(sf)} FROM 'disc_final/*.parquet'").df()
o = o.merge(S, on=["symbol","_ts_hours"], how="left")
Xs = o[sf].to_numpy(np.float32); Xs = np.where(np.isfinite(Xs), Xs, np.nan)
Xs = np.where(np.isnan(Xs), np.nanmedian(Xs, axis=0), Xs)
trm = (o._ts_hours*3600 < cut).to_numpy()
Z2 = StandardScaler().fit(Xs[trm]).transform(Xs); np.clip(Z2, -8, 8, out=Z2)
sub = RNG.choice(np.where(trm)[0], min(120000, trm.sum()), replace=False)
o["ck"] = KMeans(6, n_init=5, random_state=0).fit(Z2[sub]).predict(Z2)
del S, Xs, Z2

# ------------------------------------------- the policy: global top 0.5% by score
gs = o.sort_values("score", ascending=False)
cw = np.cumsum(gs._w.to_numpy())
POL = gs[cw <= cw[-1]*0.005].copy()
print(f"policy = global top-0.5% by score: {len(POL):,} sampled trades, "
      f"{POL._w.sum():,.0f} population trades, {POL.blk.nunique()} weeks, "
      f"EV {np.average(POL.R,weights=POL._w)-1:+.4f}, "
      f"hit {np.average(POL.hit,weights=POL._w)*100:.2f}%")
print("\ncomposition of the traded slice (does the model already avoid these?)")
for col in ["trend20","pos60","dir20","km5","ck"]:
    sh = POL.groupby(col)._w.sum()/POL._w.sum()
    al = o.groupby(col)._w.sum()/o._w.sum()
    j = pd.DataFrame({"in slice": sh, "in universe": al}).dropna()
    j["tilt"] = j["in slice"]/j["in universe"]
    print(f"  {col}: " + "  ".join(f"{k}={v['in slice']*100:.0f}%(x{v['tilt']:.2f})"
                                    for k, v in j.iterrows()))

FILTERS = {
    "trend20 != up"          : POL.trend20 != "up",
    "trend20 in {down,side}" : POL.trend20.isin(["down","sideways"]),
    "pos60 == deep-dd"       : POL.pos60 == "deep-dd",
    "pos60 != near-high"     : POL.pos60 != "near-high",
    "dir20 == bear"          : POL.dir20 == "bear",
    "vol20 == highvol"       : POL.vol20 == "highvol",
    "km5 != 1  (unsup)"      : POL.km5 != 1,
    "chain ck != 2"          : POL.ck != 2,
    "ck!=2 AND trend20!=up"  : (POL.ck != 2) & (POL.trend20 != "up"),
    "ck!=2 AND pos60!=nh"    : (POL.ck != 2) & (POL.pos60 != "near-high"),
}
r_all = POL.R.to_numpy(); w_all = POL._w.to_numpy(); b_all = POL.blk.to_numpy()
ub = np.unique(b_all)
NB = 4000
draws = [RNG.choice(ub, len(ub), replace=True) for _ in range(NB)]
idx_by_blk = {q: np.where(b_all == q)[0] for q in ub}

def paired(mask):
    m = mask.to_numpy()
    base_w_per_week = w_all.sum()/len(ub)
    de, dp = [], []
    for pk in draws:
        idx = np.concatenate([idx_by_blk[q] for q in pk])
        sel = idx[m[idx]]
        if len(sel) < 40: continue
        ev_f = np.average(r_all[sel], weights=w_all[sel]) - 1
        ev_u = np.average(r_all[idx], weights=w_all[idx]) - 1
        de.append(ev_f - ev_u)
        # profit per week, same resample: EV x population trades / weeks
        dp.append((ev_f*w_all[sel].sum() - ev_u*w_all[idx].sum())/len(pk))
    return np.array(de), np.array(dp)

print(f"\n{'filter':<26}{'keep%':>7}{'EV':>9}{'dEV':>9}{'P(dEV<=0)':>11}"
      f"{'d profit/wk':>13}{'P(dP<=0)':>10}")
print("-"*85)
ev0 = np.average(r_all, weights=w_all)-1
print(f"{'(unfiltered)':<26}{100.0:>6.0f}%{ev0:>+9.4f}")
for name, msk in FILTERS.items():
    de, dp = paired(msk)
    if len(de) == 0: continue
    keep = POL._w[msk].sum()/POL._w.sum()*100
    evf = np.average(POL.R[msk], weights=POL._w[msk])-1
    print(f"{name:<26}{keep:>6.0f}%{evf:>+9.4f}{de.mean():>+9.4f}{(de<=0).mean():>11.3f}"
          f"{dp.mean():>+13.1f}{(dp<=0).mean():>10.3f}")

# ---------------------------------------------------- Q3 constructive follow-up
print("\n" + "="*85)
print("Q3 follow-up: instead of a BIGGER stake after a win, does the day AFTER a")
print("known payout carry a higher EV (i.e. trade MORE tickets, same fraction)?")
print("="*85)
h = c.execute("SELECT symbol, ts, held FROM 'exits/*.parquet'").df()
POL["ts"] = np.round(POL._ts_hours.astype(float)*3600).astype(np.int64)
POL = POL.merge(h, on=["symbol","ts"], how="left")
POL["know"] = POL._ts_hours + POL.held.fillna(168)
dayagg = POL.groupby("day").apply(lambda g: pd.Series({
    "n": len(g), "w": g._w.sum(),
    "ev": np.average(g.R, weights=g._w)-1,
    "won": float((g.hit*g._w).sum() > 0),
    "know_by": g.know.max()}), include_groups=False).reset_index().sort_values("day")
dd = dayagg.day.to_numpy(); won = dayagg.won.to_numpy(); ev = dayagg.ev.to_numpy()
kb = dayagg.know_by.to_numpy()
prev_paid = np.zeros(len(dd), int)
for i in range(1, len(dd)):
    j = np.where((dd < dd[i]) & (dd >= dd[i]-3) & (won == 1) & (kb <= dd[i]*24))[0]
    prev_paid[i] = 1 if len(j) else 0
w_ = dayagg.w.to_numpy()
for lab, m in [("day after a KNOWN payout (<=3d)", prev_paid == 1),
               ("all other days", prev_paid == 0)]:
    print(f"  {lab:<36} days={m.sum():>4}  EV/trade "
          f"{np.average(ev[m], weights=w_[m]):>+8.4f}")
diff = (np.average(ev[prev_paid==1], weights=w_[prev_paid==1])
        - np.average(ev[prev_paid==0], weights=w_[prev_paid==0]))
bw = (dd//7)
nb = []
for _ in range(3000):
    pk = RNG.choice(np.unique(bw), len(np.unique(bw)), replace=True)
    ii = np.concatenate([np.where(bw==q)[0] for q in pk])
    a, bb = ii[prev_paid[ii]==1], ii[prev_paid[ii]==0]
    if len(a) < 20 or len(bb) < 20: continue
    nb.append(np.average(ev[a], weights=w_[a]) - np.average(ev[bb], weights=w_[bb]))
nb = np.array(nb)
print(f"  difference {diff:+.4f}   95% CI [{np.percentile(nb,2.5):+.4f},"
      f"{np.percentile(nb,97.5):+.4f}]   P(diff<=0)={(nb<=0).mean():.3f}")
