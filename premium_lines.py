"""His 26 Oct point, from NIFTY OCT 22600 CE / 22700 CE 15m charts (docs/ML/img/2026-10/2026-10-26_nifty_*):

  "the parabola initial part (prices shrinking part) has trendlines (technically trend channel lines) with flatter
  and flatter slopes. As the lines have more slope initially, the upward price explosions are less powerful, and more
  sideways (sideways movement from a steep falling line is still breaking the trend). As further fall ... seems
  unlikely, and THE TRENDLINES HOLD, we see more powerful explosions (like 1:3, 1:5 ...), and if time and price action
  permits, true multibagger ... 1:3 is also very good here if liquidity is there."

Testable claims, on the OPTION premium chart:
  C1  the steeper the broken falling line, the weaker the move after the break; flatter line -> bigger move.
  C2  a line FLATTER than the previous broken line on the same contract -> bigger move than a steeper one.
  C3  the later lines in the sequence (2nd, 3rd ... break) give bigger moves than the first.

No NIFTY option data here, so BTC/ETH Delta options, 15m MARK, log premium. Lines: levels.trendlines on log OHLC
(descending resistance through >= 3 swing highs, causal confirmation >= anchor2 + 5 bars), last 10 days of each
contract, contracts alive >= 4 days (his charts span ~10 days of a monthly). Break = first close above a
confirmed line. slope_h = line slope in log-premium per hour (more negative = steeper).
Outcomes from the break close: best later high within 24h and to expiry (x), shares >= 2x / 3x / 5x, and value at
expiry. Compared WITHIN strata (asset x call/put x time-to-expiry bucket x premium-%-of-spot quintile), CIs by expiry.
Sample: per expiry and type, the 8 strikes nearest the money at the start of the window."""
import os, re, json, glob, sys, numpy as np, pandas as pd
from multiprocessing import Pool
from levels import atr, trendlines
DAYS = 10; MIN_LIFE_D = 4; N_STRIKES = 8; BPH = 4          # 15m bars per hour
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")

def spot_series(asset):
    rows = []
    for f in sorted(glob.glob(f"data/spot_candles/{asset}/15/*")): rows += json.load(open(f))
    a = np.array([r[:5] for r in rows], float); a = a[np.argsort(a[:, 0])]
    _, k = np.unique(a[:, 0], return_index=True); return a[k]

_SPOT = {}
def contract(args):
    path, asset, typ, K, settle = args
    if asset not in _SPOT: _SPOT[asset] = spot_series(asset)
    spot = _SPOT[asset]
    try: r = np.array([x[:5] for x in json.load(open(path)) if x[4] is not None], float)
    except Exception: return []
    r = r[(r[:, 0] >= settle - DAYS * 86400) & (r[:, 0] + 900 <= settle)]
    if len(r) < 200 or (r[:, 1:5] <= 0).any(): return []
    a = r.copy(); a[:, 1:5] = np.log(r[:, 1:5])
    A = atr(a[:, 2], a[:, 3], a[:, 4]); A = np.where(A > 0, A, np.nan)
    L = [x for x in trendlines(a, A, 15, max_span=300) if x["kind"] == "R" and x["break_i"] is not None]
    L.sort(key=lambda x: x["break_i"]); out = []; prev = None; seq = 0; seen = set()
    for x in L:
        b = x["break_i"]
        if b in seen or b + 1 >= len(r): continue      # one event per break bar
        seen.add(b); seq += 1
        e = r[b, 4]; t = r[b, 0] + 900
        j24 = np.searchsorted(r[:, 0], t + 86400)
        si = np.searchsorted(spot[:, 0], r[b, 0], side="right") - 1
        out.append(dict(asset=asset, typ=typ, strike=K, sym=os.path.basename(path)[:-5], expiry=pd.Timestamp(settle, unit="s").strftime("%Y-%m-%d"),
                        t=t, tte_h=(settle - t) / 3600, prem=e, prem_pct=100 * e / spot[si, 4],
                        mny=(K / spot[si, 4] - 1) * (1 if typ == "C" else -1), slope_h=x["slope"] * BPH,
                        prev_slope_h=prev, seq=seq, touches=x["n_rej"], span_h=(x["anchor"][1] - x["anchor"][0]) / BPH,
                        dist_low=e / r[:b + 1, 3].min(),
                        best24=r[b + 1:j24, 2].max() / e if j24 > b + 1 else np.nan, best_exp=r[b + 1:, 2].max() / e,
                        settle_x=r[-1, 4] / e))
        prev = x["slope"] * BPH
    return out

def jobs():
    J = []
    for asset in ("BTC", "ETH"):
        spot = spot_series(asset)
        for e in sorted(os.listdir(f"data/candles/{asset}")):
            d = f"data/candles/{asset}/{e}/15"
            if not os.path.isdir(d): continue
            settle = pd.Timestamp(e + " 12:00", tz="UTC").timestamp()
            if settle > pd.Timestamp.now(tz="UTC").timestamp(): continue
            t0 = settle - DAYS * 86400; si = np.searchsorted(spot[:, 0], t0)
            if si >= len(spot): continue
            S0 = spot[si, 4]; byt = {"C": [], "P": []}
            for fn in os.listdir(d):
                m = SYM.match(fn)
                if m: byt[m.group(1)].append((abs(float(m.group(3)) / S0 - 1), float(m.group(3)), f"{d}/{fn}"))
            for typ, ks in byt.items():
                for _, K, p in sorted(ks)[:N_STRIKES]:
                    try: first = json.load(open(p))[0][0]
                    except Exception: continue
                    if settle - first < MIN_LIFE_D * 86400: continue
                    J.append((p, asset, typ, K, settle))
    return J

def boot_diff(g, a_mask, b_mask, col, n=500):
    ex = g.expiry.values; u = np.unique(ex); ix = {e: np.where(ex == e)[0] for e in u}
    v = g[col].values; am, bm = a_mask.values, b_mask.values; rng = np.random.default_rng(0); out = []
    for _ in range(n):
        s = np.concatenate([ix[e] for e in rng.choice(u, len(u))])
        out.append(np.nanmean(v[s][am[s]]) - np.nanmean(v[s][bm[s]]))
    return np.nanpercentile(out, [2.5, 50, 97.5])

if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        J = jobs(); print(f"{len(J):,} contracts", flush=True)
        with Pool(4) as p: R = [x for part in p.imap_unordered(contract, J, chunksize=8) for x in part]
        E = pd.DataFrame(R); E.to_parquet("data/premium_lines.parquet"); print(f"wrote {len(E):,} breaks"); sys.exit()
    E = pd.read_parquet("data/premium_lines.parquet")
    E = E[E.tte_h > 1].copy()
    E["tteb"] = pd.cut(E.tte_h, [0, 24, 72, 168, 1e9], labels=["<1d", "1-3d", "3-7d", ">7d"])
    E["pq"] = E.groupby(["asset", "typ", "tteb"], observed=True).prem_pct.transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
    E["stratum"] = E.asset + E.typ + E.tteb.astype(str) + E.pq.astype(str)
    E["slope_t"] = E.groupby("stratum").slope_h.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=["steep", "mid", "flat"]) if len(s) >= 9 else np.nan)
    for k in (2, 3, 5): E[f"x{k}"] = (E.best24 >= k).astype(float); E[f"xe{k}"] = (E.best_exp >= k).astype(float)
    E["kept"] = E.settle_x.clip(upper=25)
    print(f"breaks {len(E):,}  contracts {E.sym.nunique():,}  expiries {E.expiry.nunique()}  ({E.expiry.min()} .. {E.expiry.max()})")
    print(E.slope_h.describe().round(3).to_string())
    cols = ["best24", "x2", "x3", "x5", "xe3", "xe5", "kept"]
    fmt = lambda c: f"{c[1]:+.3f} [{c[0]:+.3f},{c[2]:+.3f}]"
    print("\nC1 slope tertile WITHIN stratum (median best24, shares within 24h / to expiry, value at expiry capped 25):")
    print(E.groupby("slope_t", observed=True).agg(n=("x3", "size"), med_best24=("best24", "median"), **{c: (c, "mean") for c in cols[1:]}).round(3).to_string())
    for c in ("x2", "x3", "x5", "xe5"):
        print(f"  flat - steep {c}: {fmt(boot_diff(E, E.slope_t == 'flat', E.slope_t == 'steep', c))}")
    print("  by tte:")
    for k, g in E.groupby("tteb", observed=True):
        print(f"   {k:<5} n {len(g):>6,}  x3 steep {g[g.slope_t=='steep'].x3.mean():.3f} flat {g[g.slope_t=='flat'].x3.mean():.3f}  diff {fmt(boot_diff(g, g.slope_t=='flat', g.slope_t=='steep', 'x3'))}")
    print("  by asset/type:")
    for k, g in E.groupby(["asset", "typ"]):
        print(f"   {k}  n {len(g):>6,}  x3 diff {fmt(boot_diff(g, g.slope_t=='flat', g.slope_t=='steep', 'x3'))}  x5 diff {fmt(boot_diff(g, g.slope_t=='flat', g.slope_t=='steep', 'x5'))}")
    mid = np.sort(E.expiry.unique())[E.expiry.nunique() // 2]
    for nm, g in (("1st half", E[E.expiry < mid]), ("2nd half", E[E.expiry >= mid])):
        print(f"   {nm} x3 diff {fmt(boot_diff(g, g.slope_t=='flat', g.slope_t=='steep', 'x3'))}")
    F = E[E.prev_slope_h.notna()].copy()
    F["flatter"] = F.slope_h > F.prev_slope_h
    # matched: same stratum and same slope tertile, so "flatter than before" is not just "flat"
    print(f"\nC2 flatter than the previous broken line on the same contract (n {len(F):,}, flatter {F.flatter.mean():.0%}):")
    print(F.groupby("flatter").agg(n=("x3", "size"), med_best24=("best24", "median"), **{c: (c, "mean") for c in cols[1:]}).round(3).to_string())
    print(f"  flatter - steeper x3: {fmt(boot_diff(F, F.flatter, ~F.flatter, 'x3'))}   x5: {fmt(boot_diff(F, F.flatter, ~F.flatter, 'x5'))}")
    for k, g in F.groupby("slope_t", observed=True):
        print(f"   within slope tertile {k:<5} n {len(g):>6,} x3 flatter {g[g.flatter].x3.mean():.3f} vs {g[~g.flatter].x3.mean():.3f}  {fmt(boot_diff(g, g.flatter, ~g.flatter, 'x3'))}")
    E["seqb"] = pd.cut(E.seq, [0, 1, 2, 3, 99], labels=["1st", "2nd", "3rd", "4th+"])
    print("\nC3 order of the break on the contract:")
    print(E.groupby("seqb", observed=True).agg(n=("x3", "size"), med_best24=("best24", "median"), tte=("tte_h", "median"), **{c: (c, "mean") for c in cols[1:]}).round(3).to_string())
    for k in ("2nd", "3rd", "4th+"):
        print(f"  {k} - 1st x3 (same stratum mix not enforced): {fmt(boot_diff(E, E.seqb == k, E.seqb == '1st', 'x3'))}")
    # stratum-adjusted: x3 minus the stratum mean
    E["x3_adj"] = E.x3 - E.groupby("stratum").x3.transform("mean")
    print("  stratum-adjusted x3 by order:", E.groupby("seqb", observed=True).x3_adj.mean().round(4).to_dict())
    print("\nPremium >= 0.1% of spot only (MARK floor check):")
    G = E[E.prem_pct >= 0.1]
    print(f"  n {len(G):,}  x3 flat - steep {fmt(boot_diff(G, G.slope_t=='flat', G.slope_t=='steep', 'x3'))}")

def major(E, min_span_h):
    """Only lines spanning >= min_span_h between anchors (the lines one draws on a 10-day chart); order and the
    previous line's slope are recomputed among those lines only."""
    M = E[E.span_h >= min_span_h].sort_values(["sym", "t"]).copy()
    M["prev_slope_h"] = M.groupby("sym").slope_h.shift(1); M["seq"] = M.groupby("sym").cumcount() + 1
    return M

def summary(E, label):
    E = E[E.tte_h > 1].copy()
    E["tteb"] = pd.cut(E.tte_h, [0, 24, 72, 168, 1e9], labels=["<1d", "1-3d", "3-7d", ">7d"])
    E["pq"] = E.groupby(["asset", "typ", "tteb"], observed=True).prem_pct.transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False))
    E["stratum"] = E.asset + E.typ + E.tteb.astype(str) + E.pq.astype(str)
    E["slope_t"] = E.groupby("stratum").slope_h.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=["steep", "mid", "flat"]) if len(s) >= 9 else np.nan)
    for k in (2, 3, 5): E[f"x{k}"] = (E.best24 >= k).astype(float)
    E["xe3"] = (E.best_exp >= 3).astype(float); E["kept"] = E.settle_x.clip(upper=25)
    fmt = lambda c: f"{c[1]:+.3f} [{c[0]:+.3f},{c[2]:+.3f}]"
    print(f"\n##### {label}: breaks {len(E):,}, contracts {E.sym.nunique():,}, per contract {len(E)/E.sym.nunique():.1f}")
    print(E.groupby("slope_t", observed=True).agg(n=("x3", "size"), slope=("slope_h", "median"), med_best24=("best24", "median"),
          x2=("x2", "mean"), x3=("x3", "mean"), x5=("x5", "mean"), xe3=("xe3", "mean"), kept=("kept", "mean")).round(3).to_string())
    for c in ("x2", "x3", "x5", "xe3", "kept"):
        print(f"  C1 flat - steep {c}: {fmt(boot_diff(E, E.slope_t == 'flat', E.slope_t == 'steep', c))}")
    F = E[E.prev_slope_h.notna()].copy(); F["flatter"] = F.slope_h > F.prev_slope_h
    print(f"  C2 flatter than previous ({F.flatter.mean():.0%} of {len(F):,}): x3 {F[F.flatter].x3.mean():.3f} vs {F[~F.flatter].x3.mean():.3f} "
          f"{fmt(boot_diff(F, F.flatter, ~F.flatter, 'x3'))}; x5 {fmt(boot_diff(F, F.flatter, ~F.flatter, 'x5'))}")
    E["x3_adj"] = E.x3 - E.groupby("stratum").x3.transform("mean")
    E["seqb"] = pd.cut(E.seq, [0, 1, 2, 3, 99], labels=["1st", "2nd", "3rd", "4th+"])
    print("  C3 stratum-adjusted x3 by order:", {k: (round(v, 4), int(n)) for (k, v), n in zip(E.groupby("seqb", observed=True).x3_adj.mean().items(), E.groupby("seqb", observed=True).size())})
    # his full story: a flattening run (each line flatter than the one before, >= 3 lines), break of the latest
    E["flat_run"] = E.groupby("sym").apply(lambda g: (g.slope_h > g.prev_slope_h).astype(int).groupby(((g.slope_h <= g.prev_slope_h) | g.prev_slope_h.isna()).cumsum()).cumsum()).reset_index(level=0, drop=True)
    R = E[E.seq >= 3]
    print(f"  story (>=2 successive flatterings, n {int((R.flat_run>=2).sum())}): x3 {R[R.flat_run>=2].x3.mean():.3f} vs rest {R[R.flat_run<2].x3.mean():.3f} "
          f"adj {R[R.flat_run>=2].x3_adj.mean():+.4f} vs {R[R.flat_run<2].x3_adj.mean():+.4f}  {fmt(boot_diff(R, R.flat_run>=2, R.flat_run<2, 'x3_adj'))}")

def control(args):
    """Same contract, a random 15m close 3-12h before or after the break (not a break bar): does a break beat
    an ordinary moment at nearly the same time to expiry and premium level?"""
    path, rows = args
    r = np.array([x[:5] for x in json.load(open(path)) if x[4] is not None], float)
    rng = np.random.default_rng(len(rows)); out = []
    brk = set(rows.t.values)
    for _, e in rows.iterrows():
        for _ in range(20):
            tc = e.t + rng.choice([-1, 1]) * rng.uniform(3, 12) * 3600
            i = np.searchsorted(r[:, 0], tc - 900) - 1          # bar closing at or before tc
            if i < 0 or i + 1 >= len(r) or r[i, 0] + 900 in brk or r[i, 4] <= 0: continue
            j = np.searchsorted(r[:, 0], r[i, 0] + 900 + 86400)
            out.append(dict(idx=e.name, c_best24=r[i + 1:j, 2].max() / r[i, 4] if j > i + 1 else np.nan,
                            c_prem_ratio=r[i, 4] / e.prem)); break
    return out

def run_control(min_span_h=24):
    E = major(pd.read_parquet("data/premium_lines.parquet"), min_span_h); E = E[E.tte_h > 1]
    E["path"] = "data/candles/" + E.asset + "/" + E.expiry + "/15/" + E.sym + ".json"
    J = [(p, g[["t", "prem"]]) for p, g in E.groupby("path")]
    with Pool(4) as pool: C = pd.DataFrame([x for part in pool.imap_unordered(control, J, chunksize=20) for x in part]).set_index("idx")
    X = E.join(C, how="inner"); X = X[(X.c_prem_ratio > 0.7) & (X.c_prem_ratio < 1.43)]   # control premium within ~±40%
    print(f"\nCONTROL (lines >= {min_span_h}h): same contract, random bar 3-12h away, premium within ±40%; n {len(X):,}")
    for k in (2, 3, 5): print(f"  >= {k}x within 24h: break {(X.best24 >= k).mean():.2%}  control {(X.c_best24 >= k).mean():.2%}")
    X["d3"] = (X.best24 >= 3).astype(float) - (X.c_best24 >= 3).astype(float)
    ex = X.expiry.values; u = np.unique(ex); ix = {e: np.where(ex == e)[0] for e in u}; rng = np.random.default_rng(0)
    b = [X.d3.values[np.concatenate([ix[e] for e in rng.choice(u, len(u))])].mean() for _ in range(500)]
    print("  break - control at 3x: %+.4f [%+.4f, %+.4f]" % (X.d3.mean(), *np.percentile(b, [2.5, 97.5])))
    for t, g in X.groupby("typ"): print(f"  {t}: 3x break {(g.best24 >= 3).mean():.2%} vs control {(g.c_best24 >= 3).mean():.2%}")

if __name__ == "__main__" and sys.argv[1:2] == ["control"]:
    run_control()
