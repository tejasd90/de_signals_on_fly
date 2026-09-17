#!/usr/bin/env python3
"""
Q3, done properly. Three corrections to the first pass:

 1. WEIGHTS. Negatives are downsampled 10.7:1, so the top-scored row of the
    SAMPLE is ~10x more likely to be a winner than the top-scored row of the
    POPULATION. An unweighted per-day argmax reports 12% at 25x where the truth
    is ~1.3% (the FINDINGS 13 inflation, in a new costume). Policy sequences
    here are weight-truncated baskets.

 2. DOUBLE COUNTING. One BTC move makes many contracts print 25x on several
    consecutive days. "Wins cluster" is then true by construction and carries no
    information. The model-free test below collapses to DISTINCT MOVE DAYS.

 3. KNOWABILITY. Pressing requires knowing you won BEFORE the next entry. The
    conditional is therefore on realised-and-known outcomes, not on outcomes.
"""
import numpy as np, pandas as pd, duckdb
RNG = np.random.default_rng(7); T = 25.0

o = pd.read_parquet("runs/oof_surface_25.parquet")
o["sp"] = o.symbol.str.split("-").str[1]
o["R"] = np.where(o._peak >= T, T, o.stop_ratio) - 0.05
o["day"] = (o._ts_hours // 24).astype(int)
o["ts"] = np.round(o._ts_hours.astype(float)*3600).astype(np.int64)
c = duckdb.connect(); c.execute("SET memory_limit='3GB'; SET threads=4;")
h = c.execute("SELECT symbol, ts, held FROM 'exits/*.parquet'").df()
o = o.merge(h, on=["symbol","ts"], how="left")
o["hit"] = (o._peak >= T).astype(int)

# ============================================================ A. MODEL-FREE
print("="*78); print("A. ARE 25x EVENTS CLUSTERED IN TIME? (no model, weighted)"); print("="*78)
day = o.groupby(["sp","day"]).apply(
    lambda g: pd.Series({"whit": (g.hit*g._w).sum(), "wn": g._w.sum()}),
    include_groups=False).reset_index()
print(f"  {'level':<34}{'buckets':>9}{'mean':>9}{'var':>10}{'Fano':>8}{'perm p':>9}")

def fano_test(counts, n_per, label):
    """counts = wins per bucket, n_per = trials per bucket. Null keeps the same
    per-bucket trial counts and scatters the same total wins across trials."""
    fano = counts.var()/max(counts.mean(),1e-12)
    tot = counts.sum(); p = tot/n_per.sum()
    null = np.array([ (lambda cc: cc.var()/max(cc.mean(),1e-12))(
                        RNG.binomial(np.maximum(n_per.astype(int),0), p).astype(float))
                      for _ in range(3000)])
    print(f"  {label:<34}{len(counts):>9}{counts.mean():>9.3f}{counts.var():>10.3f}"
          f"{fano:>8.2f}{(null>=fano).mean():>9.4f}")

for sp in ["BTC","ETH"]:
    d = day[day.sp==sp].sort_values("day")
    b = (d.day.to_numpy()-d.day.min())//7
    cnt = np.bincount(b, weights=d.whit.to_numpy()).astype(float)
    npb = np.bincount(b, weights=d.wn.to_numpy()).astype(float)
    fano_test(cnt, npb, f"{sp}: contracts hitting 25x / week")
    # collapse: did ANY contract hit that DAY -> a distinct move
    anyhit = (d.whit.to_numpy() > 0).astype(float)
    cnt2 = np.bincount(b, weights=anyhit); npb2 = np.bincount(b, weights=np.ones(len(d)))
    fano_test(cnt2, npb2, f"{sp}: DAYS with any 25x / week")
    # collapse further: separate move-clusters (>=5 quiet days between)
    hd = d.day.to_numpy()[anyhit>0]
    if len(hd)>3:
        gaps = np.diff(hd); nclust = 1 + (gaps>=5).sum()
        print(f"  {'':<34}-> {len(hd)} hit-days collapse into {nclust} distinct "
              f"move-clusters; median gap between clusters "
              f"{np.median(gaps[gaps>=5]) if (gaps>=5).any() else float('nan'):.0f}d")

# ============================================================ B. POLICY SEQUENCE
print("\n"+"="*78)
print("B. THE 1-D TRADE SEQUENCE (weight-truncated daily basket)"); print("="*78)
def basket(df, key, W=10.0):
    """the top-W POPULATION contracts by score in each bucket, weighted."""
    d = df.sort_values([key,"score"], ascending=[True,False]).copy()
    d["cw"] = d.groupby(key)._w.cumsum()
    s = d[d.cw - d._w < W].copy()
    s["wt"] = np.minimum(s._w, W - (s.cw - s._w))
    g = s.groupby(key).apply(lambda x: pd.Series({
        "R": np.average(x.R, weights=x.wt),
        "hit": np.average(x.hit, weights=x.wt),
        "t": x._ts_hours.min(),
        "know": (x._ts_hours + x.held.fillna(168)).max()}),
        include_groups=False).reset_index().sort_values("t")
    return g

for W,lab in [(1.0,"top-1 contract/day"),(10.0,"top-10 contracts/day")]:
    g = basket(o, "day", W)
    w = (g.R.to_numpy() > 1).astype(int)
    print(f"\n  {lab}: {len(g):,} days | P(basket profits) {w.mean()*100:.2f}% | "
          f"25x rate {g.hit.mean()*100:.3f}% | EV {g.R.mean()-1:+.4f}")
    if w.sum() < 8: print("    too few wins to test"); continue
    print(f"    {'lag':>5}{'P(win)':>9}{'P(win|prev win)':>17}{'lift pp':>9}{'perm p':>9}")
    for lag in (1,2,3,7):
        prev,cur = w[:-lag], w[lag:]
        if prev.sum()<3: continue
        lift = cur[prev==1].mean()-cur.mean()
        null = np.array([cur[RNG.permutation(prev)==1].mean()-cur.mean() for _ in range(4000)])
        print(f"    {lag:>5}{cur.mean()*100:>8.2f}%{cur[prev==1].mean()*100:>16.2f}%"
              f"{lift*100:>+9.2f}{(null>=lift).mean():>9.4f}")
    # strictly tradeable: yesterday won AND the payout landed before today's entry
    t = g.t.to_numpy(); kn = g.know.to_numpy()
    usable = np.zeros(len(g),int)
    usable[1:] = ((w[:-1]==1) & (kn[:-1] <= t[1:])).astype(int)
    if usable.sum()>5:
        lift = w[usable==1].mean()-w.mean()
        null = np.array([w[RNG.permutation(usable)==1].mean()-w.mean() for _ in range(4000)])
        print(f"    TRADEABLE (yesterday won AND cash was in hand): n={usable.sum()}"
              f"  P(win)={w[usable==1].mean()*100:.2f}% vs {w.mean()*100:.2f}%"
              f"  lift {lift*100:+.2f}pp  p={(null>=lift).mean():.4f}")
        print(f"    of the {int((w[:-1]==1).sum())} wins, "
              f"{int(usable.sum())} had paid out before the next entry "
              f"({usable.sum()/max((w[:-1]==1).sum(),1)*100:.0f}%)")

# ============================================================ C. STAKING
print("\n"+"="*78)
print("C. DOES PRESSING PAY? the growth-rate curve settles it"); print("="*78)
gs = o.sort_values("score", ascending=False); cw = np.cumsum(gs._w.to_numpy())
sl = gs[cw <= cw[-1]*0.005]
R = sl.R.to_numpy(); wt = sl._w.to_numpy()
for cap,lab in [(25.0,"marks as measured (25x realised)"),
                (10.0,"realistic capture (10x realised)")]:
    Rc = np.minimum(R, cap-0.05)
    ev = np.average(Rc,weights=wt)-1
    fs = np.linspace(0.002,0.60,400)
    gcurve = np.array([np.average(np.log(np.maximum(1+f*(Rc-1),1e-12)),weights=wt) for f in fs])
    fstar = fs[gcurve.argmax()]
    def gof(f): return np.average(np.log(np.maximum(1+f*(Rc-1),1e-12)),weights=wt)
    print(f"\n  {lab}: EV/trade {ev:+.4f}, hit {np.average(Rc>1,weights=wt)*100:.2f}%")
    print(f"    Kelly f* = {fstar*100:.2f}% of bankroll   g(f*) = {gcurve.max():+.5f}")
    for f in (0.01,0.02,fstar,0.05,0.10,0.20,0.25,0.50):
        mark = "  <- f*" if abs(f-fstar)<1e-9 else ""
        print(f"      f={f*100:>5.2f}%   g={gof(f):+.5f}"
              f"{'   (RUIN: g<0)' if gof(f)<0 else ''}{mark}")
    fruin = fs[np.where(gcurve<0)[0][0]] if (gcurve<0).any() else np.nan
    print(f"    growth turns NEGATIVE above f = {fruin*100:.1f}% of bankroll")
    print(f"    pressing a {cap:.0f}x win on a 1%-of-bankroll base stakes "
          f"~{(cap-0.05)*0.01/1.0*100:.0f}% of bankroll next trade "
          f"= {((cap-0.05)*0.01)/fstar:.1f}x Kelly")
