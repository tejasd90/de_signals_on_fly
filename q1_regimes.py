#!/usr/bin/env python3
"""
Q1 — REGIME CONDITIONING, done so the answer can be trusted.

Three things have to hold before "it works better in regime X" is usable:
  (1) the regime label must be CAUSAL  -> built from completed prior days only
  (2) the difference must be SIGNIFICANT -> weekly block bootstrap, not row counts
  (3) the regime must PERSIST longer than it takes to name it -> measured, not assumed

Four independent regime axes are tested so a single lucky threshold cannot carry
the result, and the number of cells tested is reported for multiple-comparison
honesty.
"""
import json, os, sys, numpy as np, pandas as pd

RNG = np.random.default_rng(0)
SPOTS = ["BTC", "ETH", "XAUT"]

# ---------------------------------------------------------------- spot dailies
def spot_daily(sp):
    rows = []
    d = f"data/spot_candles/{sp}/60"
    for fn in sorted(os.listdir(d)):
        try: rows.extend(json.load(open(f"{d}/{fn}")))
        except Exception: pass
    a = np.asarray([r[:5] for r in rows], float)
    a = a[np.argsort(a[:, 0])]
    df = pd.DataFrame({"T": pd.to_datetime(a[:, 0], unit="s"),
                       "o": a[:,1], "h": a[:,2], "l": a[:,3], "c": a[:,4]})
    g = (df.set_index("T").resample("1D")
           .agg(o=("o","first"), h=("h","max"), l=("l","min"), c=("c","last"))
           .dropna())
    return g

def regimes(g):
    """All labels are shifted one full day: the value carried into day d uses
    only bars that closed on or before the end of day d-1."""
    c = g.c
    lr = np.log(c).diff()
    out = pd.DataFrame(index=g.index)

    # axis 1 - direction x efficiency, 20d
    for w, tag in [(20, "20"), (5, "5")]:
        net  = (c - c.shift(w)).abs() / c
        path = c.diff().abs().rolling(w).sum() / c
        eff  = net / path.replace(0, np.nan)
        ret  = c.pct_change(w)
        thr  = 0.35 if w == 20 else 0.45
        r = pd.Series("sideways", index=g.index, dtype=object)
        r[(eff > thr) & (ret > 0)] = "up"
        r[(eff > thr) & (ret < 0)] = "down"
        out["trend" + tag] = r
        out["eff" + tag] = eff

    # axis 2 - realised vol vs its own expanding median (causal percentile)
    rv = lr.rolling(20).std() * np.sqrt(365)
    med = rv.expanding(120).median()
    out["vol20"] = np.where(rv.isna() | med.isna(), "na",
                    np.where(rv > med, "highvol", "lowvol"))

    # axis 3 - where price sits in its own 60d range
    hi = c.rolling(60).max(); lo = c.rolling(60).min()
    pos = (c - lo) / (hi - lo).replace(0, np.nan)
    out["pos60"] = np.where(pos.isna(), "na",
                     np.where(pos > 0.80, "near-high",
                      np.where(pos < 0.30, "deep-dd", "mid-range")))

    # axis 4 - 20d simple direction, no efficiency gate (the plainest possible)
    r20 = c.pct_change(20)
    out["dir20"] = np.where(r20.isna(), "na", np.where(r20 > 0, "bull", "bear"))

    return out.shift(1)          # <- the causal shift. nothing here sees day d.

AXES = ["trend20", "trend5", "vol20", "pos60", "dir20"]

REG = {}
for sp in SPOTS:
    try:
        g = spot_daily(sp)
        R = regimes(g)
        REG[sp] = (np.array([x.timestamp() for x in R.index]), R)
    except Exception as e:
        print(f"  ! {sp}: {e}")

def tag(sp, ts_hours, axis):
    if sp not in REG: return "na"
    ts, R = REG[sp]
    j = np.searchsorted(ts, np.asarray(ts_hours) * 3600.0, side="right") - 1
    v = R[axis].to_numpy(dtype=object)
    j = np.clip(j, 0, len(v) - 1)
    out = v[j]
    return np.where((j < 0), "na", out)

if __name__ == "__main__":
    # ------------------------------------------------------- (b) persistence first
    print("=" * 78)
    print("(b) CAN A REGIME BE NAMED IN TIME? persistence of each causal label")
    print("=" * 78)
    print(f"\n  {'axis':>9} {'symbol':>6} {'states':>7} {'mean blk':>9} {'med blk':>8}"
          f" {'P(same +1d)':>12} {'P(same +7d)':>12} {'P(same +14d)':>13}")
    for axis in AXES:
        for sp in ["BTC", "ETH"]:
            v = REG[sp][1][axis].to_numpy(dtype=object)
            v = np.array([x for x in v if x not in ("na", None) and x == x], dtype=object)
            if len(v) < 100: continue
            chg = np.concatenate([[True], v[1:] != v[:-1]])
            blk = np.diff(np.concatenate([np.where(chg)[0], [len(v)]]))
            cells = []
            for k in (1, 7, 14):
                cells.append((v[k:] == v[:-k]).mean())
            # base rate of agreeing by chance
            p = pd.Series(v).value_counts(normalize=True).to_numpy()
            print(f"  {axis:>9} {sp:>6} {len(set(v)):>7} {blk.mean():>9.1f} "
                  f"{np.median(blk):>8.0f}" + "".join(f"{c:>12.3f}" for c in cells[:2])
                  + f"{cells[2]:>13.3f}   (chance {(p**2).sum():.3f})")

    # ---------------------------------------------------------------- option side
    print("\n" + "=" * 78)
    print("(a) OPTION MODEL (surface, 25x) — top-0.5% EV BY REGIME, weighted,")
    print("    95% CI from bootstrap over NON-OVERLAPPING WEEKLY BLOCKS")
    print("=" * 78)

    o = pd.read_parquet("runs/oof_surface_25.parquet")
    o["sp"] = o.symbol.str.split("-").str[1]
    T = 25.0
    o["R"] = np.where(o._peak >= T, T, o.stop_ratio) - 0.05
    o["blk"] = (o._ts_hours // (24 * 7)).astype(int)
    for axis in AXES:
        o[axis] = "na"
        for sp in SPOTS:
            s = o.sp == sp
            if s.any(): o.loc[s, axis] = tag(sp, o.loc[s, "_ts_hours"].to_numpy(), axis)

    def slice_top(g, frac=0.005):
        gs = g.sort_values("score", ascending=False)
        cw = np.cumsum(gs._w.to_numpy())
        return gs[cw <= cw[-1] * frac]

    def boot(sl, n=3000):
        r, w, b = sl.R.to_numpy(), sl._w.to_numpy(), sl.blk.to_numpy()
        ub = np.unique(b); mu = []
        for _ in range(n):
            pk = RNG.choice(ub, len(ub), replace=True)
            # resample blocks WITH multiplicity
            idx = np.concatenate([np.where(b == q)[0] for q in pk])
            if len(idx) < 30: continue
            mu.append(np.average(r[idx], weights=w[idx]) - 1)
        return np.array(mu)

    overall = slice_top(o)
    mu0 = boot(overall)
    print(f"\n  BASELINE all regimes: EV {np.average(overall.R, weights=overall._w)-1:+.4f}"
          f"  [{np.percentile(mu0,2.5):+.4f},{np.percentile(mu0,97.5):+.4f}]"
          f"  n={len(overall):,} weeks={overall.blk.nunique()}")

    cells_tested = 0
    store = {}
    for axis in AXES:
        print(f"\n  --- {axis} ---")
        print(f"  {'state':>12}{'rows':>10}{'25x base':>10}{'top.5% hit':>12}"
              f"{'top.5% EV':>12}{'95% CI':>26}{'wks':>5}")
        for st, g in o.groupby(axis):
            if st == "na" or len(g) < 20000: continue
            sl = slice_top(g)
            if len(sl) < 100: continue
            mu = boot(sl); store[(axis, st)] = mu
            cells_tested += 1
            ev = np.average(sl.R, weights=sl._w) - 1
            print(f"  {st:>12}{len(g):>10,}"
                  f"{np.average(g._peak>=T, weights=g._w)*100:>9.3f}%"
                  f"{np.average(sl._peak>=T, weights=sl._w)*100:>11.2f}%"
                  f"{ev:>+12.4f}"
                  f"   [{np.percentile(mu,2.5):+.4f},{np.percentile(mu,97.5):+.4f}]"
                  f"{sl.blk.nunique():>5}")

    print(f"\n  cells tested: {cells_tested}  -> Bonferroni alpha for 0.05 is "
          f"{0.05/max(cells_tested,1):.4f}")

    print("\n  --- pairwise differences within each axis (paired on bootstrap draws) ---")
    print(f"  {'axis':>9}  {'A vs B':<26}{'diff':>10}{'P(diff<=0)':>12}")
    for axis in AXES:
        ks = [k for k in store if k[0] == axis]
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = store[ks[i]], store[ks[j]]
                n = min(len(a), len(b))
                d = a[:n] - b[:n]
                print(f"  {axis:>9}  {ks[i][1]+' - '+ks[j][1]:<26}{d.mean():>+10.4f}"
                      f"{(d<=0).mean():>12.3f}")
