#!/usr/bin/env python3
"""
Q3 — DO SUCCESSES COME IN CHUNKS, AND DOES PRESSING A WINNER PAY?

Two separate claims are tangled in the question and they need separating:
  (i)  do wins CLUSTER in time?          -> dispersion / autocorrelation tests
  (ii) if they do, does pressing pay?    -> that needs P(win | you ALREADY KNOW
       you won), which is a different and much harder condition, because a 25x
       exit is only known when the GTC limit fills, often days after entry.

And a third thing decides it regardless of (i) and (ii): the Kelly fraction.
Pressing a 25x win into the next ticket bets ~80% of bankroll on a ~3% shot.
"""
import numpy as np, pandas as pd, duckdb
RNG = np.random.default_rng(7)
T = 25.0

o = pd.read_parquet("runs/oof_surface_25.parquet")
o["sp"] = o.symbol.str.split("-").str[1]
o["R"] = np.where(o._peak >= T, T, o.stop_ratio) - 0.05
o["day"] = (o._ts_hours // 24).astype(int)

# fill/realisation delay: how long after entry do you LEARN the outcome?
c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
h = c.execute("""SELECT symbol, ts, held, stopped FROM 'exits/*.parquet'""").df()
o["ts"] = np.round(o._ts_hours.astype(float) * 3600).astype(np.int64)
o = o.merge(h, left_on=["symbol","ts"], right_on=["symbol","ts"], how="left")
print(f"rows {len(o):,}   held known for {o.held.notna().mean()*100:.1f}%")

# ---------------------------------------------------- the merged 1-D sequences
def daily_top1(df):
    """one trade per calendar day: the single highest-scored contract on the
    board that day. This is the 1-D sequence a person would actually trade."""
    i = df.groupby("day").score.idxmax()
    s = df.loc[i].sort_values("day").reset_index(drop=True)
    return s

def episode_top1(df):
    i = df.groupby("episode_id").score.idxmax()
    s = df.loc[i].sort_values("_ts_hours").reset_index(drop=True)
    return s

for name, seq in [("daily top-1", daily_top1(o)), ("episode top-1", episode_top1(o))]:
    w = (seq.R > 1).to_numpy().astype(int)
    print(f"\n{'='*78}\n{name}: {len(seq):,} trades  wins {w.sum()}  "
          f"({w.mean()*100:.2f}%)  EV {seq.R.mean()-1:+.4f}\n{'='*78}")
    if w.sum() < 5: 
        print("  too few wins to test clustering"); continue

    # --- (i) clustering in TIME: dispersion of counts per bucket vs Poisson ---
    print("  (i) are the wins over-dispersed (= clustered) vs a Poisson process?")
    t = seq.day.to_numpy() if "day" in seq else (seq._ts_hours//24).astype(int)
    print(f"      {'bucket':>10}{'n buckets':>11}{'mean':>8}{'var':>8}"
          f"{'Fano':>8}{'p(Fano>=obs)':>14}")
    for B in (7, 14, 30):
        b = (t - t.min()) // B
        cnt = np.bincount(b, weights=w, minlength=b.max()+1)
        fano = cnt.var() / max(cnt.mean(), 1e-9)
        # null: same number of wins scattered uniformly over the same trades
        null = []
        for _ in range(4000):
            ww = RNG.permutation(w)
            cc = np.bincount(b, weights=ww, minlength=b.max()+1)
            null.append(cc.var()/max(cc.mean(),1e-9))
        null = np.array(null)
        print(f"      {str(B)+'d':>10}{len(cnt):>11}{cnt.mean():>8.3f}"
              f"{cnt.var():>8.3f}{fano:>8.3f}{(null>=fano).mean():>14.4f}")

    # --- (ii) autocorrelation of the win indicator -------------------------
    print("\n  (ii) does a win raise the odds of the NEXT trade winning?")
    print(f"      {'lag':>5}{'P(win)':>9}{'P(win|prev win)':>17}{'lift(pp)':>10}{'perm p':>9}")
    for lag in (1, 2, 3, 5):
        prev, cur = w[:-lag], w[lag:]
        if prev.sum() < 3: continue
        lift = cur[prev == 1].mean() - cur.mean()
        null = np.array([cur[RNG.permutation(prev) == 1].mean() - cur.mean()
                         for _ in range(4000)])
        print(f"      {lag:>5}{cur.mean()*100:>8.2f}%{cur[prev==1].mean()*100:>16.2f}%"
              f"{lift*100:>+10.2f}{(null>=lift).mean():>9.4f}")

    # --- (iia) the version that is actually tradeable ----------------------
    # a win is only KNOWN at entry_ts + held hours. Condition on knowledge.
    hh = seq.held.to_numpy(dtype=float)
    know = seq._ts_hours.to_numpy() + np.where(np.isnan(hh), 168.0, hh)
    ent  = seq._ts_hours.to_numpy()
    known_win = np.zeros(len(seq), int)
    for i in range(len(seq)):
        m = (know < ent[i]) & (w == 1)          # wins already realised
        if m.any():
            j = np.where(m)[0]
            known_win[i] = 1 if (ent[i] - know[j].max()) <= 72 else 0
    if known_win.sum() > 5:
        lift = w[known_win==1].mean() - w.mean()
        null = np.array([w[RNG.permutation(known_win)==1].mean() - w.mean()
                         for _ in range(4000)])
        print(f"\n      TRADEABLE version: 'a 25x paid out in the last 72h'")
        print(f"      n={known_win.sum():,}  P(win|that) = "
              f"{w[known_win==1].mean()*100:.2f}%  vs base {w.mean()*100:.2f}%"
              f"  lift {lift*100:+.2f}pp  p={(null>=lift).mean():.4f}")
    print(f"      median hours from entry to knowing the outcome: "
          f"{np.nanmedian(hh):.0f}h  (p90 {np.nanpercentile(hh,90):.0f}h)")

# ------------------------------------------------------- (iii) staking sim
print("\n" + "="*78)
print("(iii) STAKING: flat vs press-the-winner, on the REAL top-slice sequence")
print("="*78)
gs = o.sort_values("score", ascending=False)
cw = np.cumsum(gs._w.to_numpy())
sl = gs[cw <= cw[-1]*0.005].sort_values("_ts_hours")
R = sl.R.to_numpy(); wt = sl._w.to_numpy()
p_win = np.average(R > 1, weights=wt)
print(f"  slice: {len(sl):,} trades, hit {p_win*100:.2f}%, "
      f"mean R {np.average(R,weights=wt):.4f}")

# Kelly on the empirical distribution
def kelly(Rv, wv):
    fs = np.linspace(0.001, 0.30, 300)
    g = [np.average(np.log(np.maximum(1 + f*(Rv-1), 1e-9)), weights=wv) for f in fs]
    return fs[int(np.argmax(g))], max(g)
f_star, g_star = kelly(R, wt)
print(f"  full-Kelly fraction on this distribution: {f_star*100:.2f}% of bankroll"
      f"   (log-growth {g_star:+.5f}/trade)")
print(f"  pressing a 25x win means staking ~{24.95:.0f}x the base unit on the "
      f"next ticket = {24.95/ (1/f_star):.0f}x Kelly if base = full Kelly")

# simulate 366-trade paths (~1 per day for a year), resampling weekly blocks
sl2 = sl.copy(); sl2["blk"] = (sl2._ts_hours//(24*7)).astype(int)
blks = {b: g.R.to_numpy() for b, g in sl2.groupby("blk")}
keys = list(blks)
def path(n=366):
    out = []
    while len(out) < n:
        out.extend(blks[keys[RNG.integers(len(keys))]])
    return np.array(out[:n])

BASE = 0.01                      # 1% of starting bankroll per flat ticket
res = {"flat": [], "press": [], "kelly": []}
for _ in range(4000):
    r = path()
    # flat: constant 1% of STARTING bankroll
    W = 1.0
    for x in r: W += BASE*(x-1)
    res["flat"].append(max(W, 0))
    # press: base stake, but after a win roll the whole payout into the next one
    W = 1.0; carry = 0.0
    for x in r:
        stake = min(BASE + carry, W)
        if stake <= 0: break
        W += stake*(x-1)
        carry = stake*x - BASE if x > 1 else 0.0     # roll the winnings only
        if W <= 0: W = 0; break
    res["press"].append(max(W, 0))
    # fractional Kelly on current bankroll (the comparison that matters)
    W = 1.0
    for x in r:
        W *= (1 + f_star*(x-1))
        if W <= 1e-9: W = 0; break
    res["kelly"].append(W)
print(f"\n  4,000 simulated 366-trade years (weekly block resample):")
print(f"  {'scheme':>8}{'mean':>10}{'median':>10}{'p05':>9}{'p95':>11}"
      f"{'P(<1.0)':>10}{'P(<0.5)':>10}")
for k in ("flat", "press", "kelly"):
    v = np.array(res[k])
    print(f"  {k:>8}{v.mean():>10.3f}{np.median(v):>10.3f}{np.percentile(v,5):>9.3f}"
          f"{np.percentile(v,95):>11.3f}{(v<1).mean():>10.3f}{(v<0.5).mean():>10.3f}")
