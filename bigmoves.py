"""What was visible BEFORE the biggest moves, and how often the same picture led nowhere.

Tejas: before Aug 19-21 "the weekend before was much more quiet than usual... the market did
hold up over the week, volatility was less". Signatures are clear in hindsight. The question
that decides tradeability is the false-positive rate: how often the same picture came with
no move.

Delta perp hourly with real volume (data/perp_candles), OI (data/oi). Big move = |3-day
return| from the close of day d-1 to the close of d+2, the top 15 non-overlapping per asset.
Every precursor is computed from data up to the close of d-1 and expressed as a CAUSAL
percentile against the previous 365 days only.
"""
import numpy as np, pandas as pd
K = 15

def daily(sym):
    h = pd.read_parquet(f"data/perp_candles/{sym}.parquet")
    h["dt"] = pd.to_datetime(h.ts, unit="s"); h = h.set_index("dt").sort_index()
    h["lr"] = np.log(h.c).diff()
    d = h.resample("1D").agg(o=("o", "first"), hi=("h", "max"), lo=("l", "min"), c=("c", "last"), v=("v", "sum"),
                             rv=("lr", lambda x: np.sqrt((x**2).sum())))
    oi = pd.read_parquet(f"data/oi/{sym}.parquet"); oi["dt"] = pd.to_datetime(oi.ts, unit="s").dt.normalize()
    d = d.join(oi.groupby("dt").oi.last()).dropna(subset=["c"])
    d["rng"] = (d.hi - d.lo)/d.c
    return d

def cpct(s, win=365):
    """causal percentile of s[t] among s[t-win..t-1]"""
    v = s.to_numpy(); out = np.full(len(v), np.nan)
    for i in range(60, len(v)):
        w = v[max(0, i-win):i]; w = w[np.isfinite(w)]
        if len(w) >= 60 and np.isfinite(v[i]): out[i] = (w < v[i]).mean()
    return pd.Series(out, index=s.index)

rows = []
for sym in ("BTCUSD", "ETHUSD"):
    d = daily(sym)
    f = pd.DataFrame(index=d.index)
    f["rv7"] = d.rv.rolling(7).mean()                                   # realised vol, last week
    f["rng5"] = (d.hi.rolling(5).max() - d.lo.rolling(5).min())/d.c     # 5-day range: compression
    wk = d.rng.where(d.index.weekday >= 5)                              # Sat/Sun daily ranges
    f["wkend"] = wk.rolling(7, min_periods=1).mean()                    # the most recent weekend
    f["vol3"] = d.v.rolling(3).sum()
    f["oi7"] = d.oi.pct_change(7)
    f["ret7"] = d.c.pct_change(7)                                       # "held up"
    f["dd7"] = d.c/d.c.rolling(7).max() - 1
    P = f.apply(cpct).shift(1)                                          # as known at the close of d-1
    fwd = d.c.shift(-2)/d.c.shift(1) - 1                                # close d-1 -> close d+2
    big = fwd.abs()
    picks, used = [], set()
    for t in big.dropna().sort_values(ascending=False).index:
        if any(abs((t - u).days) < 5 for u in used): continue
        if not np.isfinite(P.loc[t]).all(): continue
        used.add(t); picks.append(t)
        if len(picks) == K: break
    thr = big.loc[picks].min()
    for t in P.index:
        if not np.isfinite(P.loc[t]).all() or not np.isfinite(big.get(t, np.nan)): continue
        rows.append(dict(sym=sym, day=t, move=fwd.loc[t], big=t in picks, bigthr=big.loc[t] >= thr, **P.loc[t].to_dict()))
R = pd.DataFrame(rows)
B = R[R.big]
feats = ["rv7", "rng5", "wkend", "vol3", "oi7", "ret7", "dd7"]
print(f"{len(R):,} days, {len(B)} big moves (3-day |move| >= {R[R.big].move.abs().min():.1%}); base rate of a move that big: {R.bigthr.mean():.1%} of days\n")
print("Percentile of each precursor on the day BEFORE each big move (0 = lowest of the past year, 1 = highest)")
show = B.sort_values("day")[["sym", "day", "move"] + feats].copy()
show["move"] = (show.move*100).round(1)
print(show.round(2).to_string(index=False))
print("\nmedian percentile before big moves:", B[feats].median().round(2).to_dict())
print("\nFalse positives: for each extreme, how often a big move followed, vs the base rate")
print(f"{'condition':<34}{'days':>6}{'of which big':>14}{'P(big)':>9}{'lift':>7}{'big moves caught':>18}")
base = R.bigthr.mean()
conds = {"quiet weekend (wkend <= 0.2)": R.wkend <= 0.2, "low vol week (rv7 <= 0.2)": R.rv7 <= 0.2,
         "compressed range (rng5 <= 0.2)": R.rng5 <= 0.2, "held up (dd7 >= 0.8)": R.dd7 >= 0.8,
         "OI building (oi7 >= 0.8)": R.oi7 >= 0.8, "volume high (vol3 >= 0.8)": R.vol3 >= 0.8,
         "AUG-19 PICTURE: quiet weekend & low vol & held up": (R.wkend <= 0.3) & (R.rv7 <= 0.3) & (R.dd7 >= 0.6)}
for lab, m in conds.items():
    s = R[m]
    print(f"{lab:<34}{len(s):>6}{int(s.bigthr.sum()):>14}{s.bigthr.mean():>9.1%}{s.bigthr.mean()/base:>7.2f}{int(s.big.sum()):>12} of {len(B)}")
R.to_parquet("data/bigmoves_precursors.parquet")
