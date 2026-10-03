"""Two of Tejas's market-design claims (2026-10-03).

A. "If people anticipate an event in either direction, that mostly won't be the outcome."
   The crowd's anticipation, read from prices:
     skew  = log(C/P) for an equidistant pair +-2% OTM at the 1h close, 24-72h to expiry
             (calls bid up vs puts = crowd paying for upside); causal percentile vs the
             previous 60 days of the same measure.
     fund  = perp funding rate, 24h mean (crowd long pays), causal percentile, 365d.
   Outcome: spot return over the next 24h and 72h. His claim predicts a NEGATIVE relation:
   crowd leaning up -> down. Spearman by year, plus the top-vs-bottom decile return gap.

B. "Patterns rotate: one fails many times, which traps people into expecting the last one to
   repeat." Each of the 4 signals' monthly 25x rate (events.parquet, per event). If patterns
   rotate, last month's best signal is NOT this month's best: rank autocorrelation <= 0, and
   'trade last month's winner' does no better than equal weight.
"""
import json, glob, os, numpy as np, pandas as pd
from scipy.stats import spearmanr

def cpct(s, win):
    v = s.to_numpy(); out = np.full(len(v), np.nan)
    for i in range(win//4, len(v)):
        w = v[max(0, i-win):i]; w = w[np.isfinite(w)]
        if len(w) > 20 and np.isfinite(v[i]): out[i] = (w < v[i]).mean()
    return pd.Series(out, index=s.index)

print("A. Does the crowd's lean predict the OPPOSITE?")

P = pd.read_parquet("data/short_panel.parquet", columns=["asset","expiry","typ","K","entry_t","S0","prem","tte_h"])
P = P[P.tte_h.between(24, 72)]
P["m"] = np.where(P.typ == "C", P.K/P.S0 - 1, 1 - P.K/P.S0)
P = P[P.m.between(0.015, 0.025)]
g = P.groupby(["asset","entry_t","typ"]).prem.mean().unstack()
g = g.dropna(); g = g[(g.C > 0) & (g.P > 0)]
sk = np.log(g.C/g.P).rename("skew").reset_index()
out = []
for a, s in sk.groupby("asset"):
    s = s.sort_values("entry_t").set_index("entry_t")
    s["pct"] = cpct(s["skew"], 60*6)            # 4h bars -> 60 days
    sp = {}
    for p in glob.glob(f"data/spot_candles/{a}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)): sp[int(r[0]) + 3600] = float(r[4])
        except Exception: pass
    fund = pd.read_parquet(f"data/funding/{a}USD.parquet"); fund["t"] = (fund.ts//3600*3600 + 3600).astype(int)
    f24 = fund.set_index("t").rate.sort_index().rolling(24, min_periods=6).mean()
    fp = cpct(f24, 24*365)
    for t, r in s.iterrows():
        S = sp.get(t); S1 = sp.get(t + 86400); S3 = sp.get(t + 3*86400)
        if S and S1 and S3 and np.isfinite(r.pct):
            out.append(dict(asset=a, t=t, skew_pct=r.pct, fund_pct=fp.get(t, np.nan), r1=S1/S - 1, r3=S3/S - 1))
O = pd.DataFrame(out); O["yr"] = pd.to_datetime(O.t, unit="s").dt.year
for lab, col in (("option skew (calls rich vs puts)", "skew_pct"), ("funding (longs paying)", "fund_pct")):
    print(f"\n  {lab}:  his claim predicts NEGATIVE")
    for y, g_ in O.dropna(subset=[col]).groupby("yr"):
        r1 = spearmanr(g_[col], g_.r1).correlation; r3 = spearmanr(g_[col], g_.r3).correlation
        top, bot = g_[g_[col] >= 0.9], g_[g_[col] <= 0.1]
        print(f"    {y}: rank corr with next 24h {r1:+.3f}, next 72h {r3:+.3f}  |  crowd most bullish (top 10%) next 72h {top.r3.mean()*100:+.2f}%"
              f"  vs most bearish (bottom 10%) {bot.r3.mean()*100:+.2f}%   (n {len(top)}/{len(bot)})")

print("\nB. Do patterns rotate?")
E = pd.read_parquet("events.parquet", columns=["signal","event_id","entry_ts","y_25x"])
ev = E.groupby(["event_id","signal"]).agg(t=("entry_ts","first"), y=("y_25x","mean")).reset_index()
ev["mo"] = pd.to_datetime(ev.t, unit="s").dt.to_period("M")
M = ev.pivot_table(index="mo", columns="signal", values="y", aggfunc="mean").dropna()
rel = M.sub(M.mean(axis=1), axis=0)                       # each signal vs that month's average
ac = [spearmanr(rel.iloc[i-1], rel.iloc[i]).correlation for i in range(1, len(rel))]
print(f"  {len(M)} months x {M.shape[1]} signals. Month-to-month rank correlation of relative performance: "
      f"mean {np.nanmean(ac):+.3f}  (positive = winners keep winning; <= 0 = rotation)")
best_prev = rel.shift(1).idxmax(axis=1).dropna()
chase = np.mean([M.loc[m, s] for m, s in best_prev.items()]); worst_prev = rel.shift(1).idxmin(axis=1).dropna()
fade = np.mean([M.loc[m, s] for m, s in worst_prev.items()])
print(f"  25x rate trading LAST month's best signal {chase:.2%}  |  last month's worst {fade:.2%}  |  equal weight {M.loc[best_prev.index].mean(axis=1).mean():.2%}")
for lag in (1, 2, 3, 6):
    acl = [spearmanr(rel.iloc[i-lag], rel.iloc[i]).correlation for i in range(lag, len(rel))]
    print(f"    lag {lag} month(s): rank corr {np.nanmean(acl):+.3f}")

print("\n  Same, after removing each signal's own long-run level (rotation = deviations flip sign):")
dev = rel.sub(rel.mean(axis=0), axis=1)
for lag in (1, 2, 3, 6):
    acl = [spearmanr(dev.iloc[i-lag], dev.iloc[i]).correlation for i in range(lag, len(dev))]
    print(f"    lag {lag}: rank corr {np.nanmean(acl):+.3f}   (n months {len(acl)})")
# per-signal autocorrelation of monthly deviation, and the null by shuffling months
rng = np.random.default_rng(0)
obs = np.nanmean([dev[c].autocorr(1) for c in dev])
null = [np.nanmean([pd.Series(rng.permutation(dev[c].values)).autocorr(1) for c in dev]) for _ in range(2000)]
print(f"  per-signal lag-1 autocorrelation of its own deviation: {obs:+.3f}  (shuffled-months null 95%: [{np.percentile(null,2.5):+.3f},{np.percentile(null,97.5):+.3f}])")
print("  how often each signal is the month's best:", (rel.idxmax(axis=1).value_counts()/len(rel)).round(2).to_dict())
