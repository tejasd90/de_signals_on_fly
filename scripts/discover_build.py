#!/usr/bin/env python3
"""
discover_build.py — find what precedes a multibagger, using NO hand-made signals.

Everything so far has tested one particular encoding of your patterns
(ratio1, seqLength, ...) and found it inert. That does not prove the shapes
are meaningless — it proves those numbers are the wrong way to measure them.

This scans raw option candles directly and emits a MECHANICAL, OPINION-FREE
family of shape features: every body ratio across every lag, run lengths, wick
fractions, position in range, volatility ratios, and the same set computed on
spot. `ratio1` and `ratio2` are inside the span of what this produces, so if
the red_squeeze hypothesis is right the model can rediscover it — but nothing
here asserts it.

LABEL — your stop rule, as you described it:

    from entry candle i, walk forward. Stop at the first candle that CLOSES
    below low[i]. The outcome is the highest high reached before that stop,
    divided by close[i].

    ratio = max(high[i+1 .. stop-1]) / close[i]

That is a trade you could actually have held, not a peak you would have had to
time perfectly.

Output schema matches step1, so the existing tools work unchanged:

    python3 discover_build.py --out discovery_parts
    python3 step2_baseline.py --data discovery_parts
    python3 step3_tune.py     --data discovery_parts

Layout read (from config.js):
    data/candles/{spot}/{expiry}/{duration}/{symbol}.json  [[t,o,h,l,c,v],...]
    data/spot_candles/{spot}/{duration}/{date}             [[t,o,h,l,c,v],...]
"""

import argparse, json, os, sys
import numpy as np
import pandas as pd

try:
    import pyarrow as pa, pyarrow.parquet as pq
except ImportError:
    sys.exit("ERROR: pip install pyarrow")

W = 8          # candles of history per feature row
EPS = 1e-12


# ------------------------------------------------------------------ spot

def load_spot(base, spot, duration):
    """-> (times, closes) sorted, or None."""
    d = os.path.join(base, str(spot), str(duration))
    if not os.path.isdir(d):
        return None
    rows = []
    for f in sorted(os.listdir(d)):
        if f.startswith(".") or ".tmp." in f:
            continue
        try:
            rows.extend(json.load(open(os.path.join(d, f))))
        except Exception:
            continue
    if not rows:
        return None
    a = np.asarray(rows, dtype=float)
    a = a[np.argsort(a[:, 0])]
    return a[:, 0], a[:, 4], a[:, 2], a[:, 3]     # t, close, high, low


# ------------------------------------------------------------------ label

def label_series(closes, highs, lows, target):
    """
    For every candle i: walk forward to the first close below low[i]; the
    outcome is the best high before that, over close[i].

    O(n^2) but n is a few hundred per instrument, so it is not the bottleneck.
    """
    n = len(closes)
    out = np.full(n, np.nan)
    for i in range(n - 1):
        c = closes[i]
        if not (c > 0):
            continue
        stop = n
        lo = lows[i]
        # first j > i whose CLOSE is below the entry candle's low
        below = np.nonzero(closes[i + 1:] < lo)[0]
        if len(below):
            stop = i + 1 + int(below[0])
        if stop <= i + 1:
            out[i] = 0.0            # stopped immediately, no upside captured
            continue
        out[i] = float(highs[i + 1:stop].max() / c)
    return out


# ------------------------------------------------------------------ features

def shape_features(o, h, l, c, i, prefix):
    """
    Agnostic candle-shape family over the W candles ending at i.
    Everything scale-free: fractions and ratios only, never a price level.
    """
    s = slice(i - W + 1, i + 1)
    O, H, L, C = o[s], h[s], l[s], c[s]
    rng = np.maximum(H - L, EPS)
    body = C - O
    absb = np.abs(body)
    f = {}

    # per-candle shape, newest = _1
    for k in range(W):
        idx = W - 1 - k
        f[f"{prefix}body_{k+1}"] = float(body[idx] / rng[idx])
        f[f"{prefix}uwick_{k+1}"] = float((H[idx] - np.maximum(O[idx], C[idx])) / rng[idx])
        f[f"{prefix}lwick_{k+1}"] = float((np.minimum(O[idx], C[idx]) - L[idx]) / rng[idx])

    # range profile, normalised by the window median
    medr = max(float(np.median(rng)), EPS)
    for k in range(W):
        f[f"{prefix}rng_{k+1}"] = float(rng[W - 1 - k] / medr)

    # EVERY body-magnitude ratio across lags — ratio1/ratio2 live in here
    medb = max(float(np.median(absb)), EPS)
    for a in range(W):
        for b in range(a + 1, W):
            ia, ib = W - 1 - a, W - 1 - b
            f[f"{prefix}bodyratio_{a+1}_{b+1}"] = float(
                (absb[ia] + EPS) / (absb[ib] + EPS))
    f[f"{prefix}bodymed"] = float(absb[-1] / medb)

    # run lengths (the general form of "stairs")
    sign = np.sign(body)
    run_up = run_dn = shrink = 0
    for k in range(W - 1, -1, -1):
        if sign[k] > 0 and run_dn == 0:
            run_up += 1
        else:
            break
    for k in range(W - 1, -1, -1):
        if sign[k] < 0 and run_up == 0:
            run_dn += 1
        else:
            break
    for k in range(W - 1, 0, -1):
        if absb[k] < absb[k - 1]:
            shrink += 1
        else:
            break
    f[f"{prefix}sequp"] = float(run_up)
    f[f"{prefix}seqdown"] = float(run_dn)
    f[f"{prefix}seqshrink"] = float(shrink)

    # position of the last close inside the window range
    wlo, whi = float(L.min()), float(H.max())
    f[f"{prefix}posinrange"] = float((C[-1] - wlo) / max(whi - wlo, EPS))

    # log returns, scaled by their own dispersion
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.diff(np.log(np.maximum(C, EPS)))
    sd = max(float(lr.std()), EPS)
    f[f"{prefix}ret1z"] = float(lr[-1] / sd) if len(lr) else 0.0
    f[f"{prefix}retsum z"] = float(lr.sum() / (sd * np.sqrt(max(len(lr), 1))))
    f[f"{prefix}volratio"] = float(
        (np.abs(lr[-3:]).mean() + EPS) / (np.abs(lr).mean() + EPS)) if len(lr) >= 3 else 1.0
    # directional efficiency: 1 = clean trend, 0 = chop
    f[f"{prefix}efficiency"] = float(
        abs(C[-1] - C[0]) / max(np.abs(np.diff(C)).sum(), EPS))
    return f



# ------------------------------------------------------------------ surface

def surface_features(chain, ti, my_strike, my_prem, spot_px):
    """
    CROSS-SECTIONAL features: where this contract sits on the chain RIGHT NOW,
    relative to every other strike in the same (spot, expiry, duration, type).

    Everything above treated each contract in isolation, which ignores the one
    thing an option chain actually is: a surface. `cheapness` compares premium
    to spot; none of it compared premium to its NEIGHBOURS.

    chain: list of (strike, closes_array) for the same type/expiry/duration,
           all aligned to the same time index ti.
    """
    ks, ps = [], []
    for k, arr in chain:
        if ti < len(arr) and np.isfinite(arr[ti]) and arr[ti] > 0:
            ks.append(k); ps.append(arr[ti])
    f = {}
    if len(ks) < 4 or not (my_prem > 0):
        return f
    ks = np.asarray(ks, float); ps = np.asarray(ps, float)
    order = np.argsort(ks); ks, ps = ks[order], ps[order]
    logp = np.log(np.maximum(ps, EPS))

    f["surf_n_strikes"] = float(len(ks))
    f["surf_prem_rank"] = float((ps < my_prem).mean())
    f["surf_strike_rank"] = float((ks < my_strike).mean())
    f["surf_prem_vs_med"] = float(my_prem / max(np.median(ps), EPS))
    f["surf_prem_disp"] = float(logp.std())
    f["surf_frac_cheaper"] = float((ps < my_prem).mean())

    # SKEW PROXY: slope of log(premium) vs strike. Carries much of what an IV
    # skew would tell you, and needs no IV data at all.
    kn = (ks - ks.mean()) / max(ks.std(), EPS)
    try:
        c2, c1, c0 = np.polyfit(kn, logp, 2)
        f["surf_skew_slope"] = float(c1)
        f["surf_skew_curv"] = float(c2)
        pred = np.polyval([c2, c1, c0], kn)
        resid = logp - pred
        f["surf_fit_r2"] = float(1 - resid.var() / max(logp.var(), EPS))
        # is THIS strike rich or cheap versus the fitted chain shape?
        j = int(np.argmin(np.abs(ks - my_strike)))
        f["surf_resid_z"] = float(resid[j] / max(resid.std(), EPS))
    except Exception:
        pass

    if spot_px and spot_px > 0:
        f["surf_width_pct"] = float((ks.max() - ks.min()) / spot_px * 100)
        f["surf_total_prem"] = float(ps.sum() / spot_px)
    return f


def surface_change(chain, ti, lag, my_strike):
    """How the chain SHAPE is moving — skew steepening or flattening."""
    if ti - lag < 0:
        return {}
    a = surface_features(chain, ti, my_strike, 1.0, None)
    b = surface_features(chain, ti - lag, my_strike, 1.0, None)
    out = {}
    for k in ("surf_skew_slope", "surf_skew_curv", "surf_prem_disp"):
        if k in a and k in b:
            out[f"{k}_chg{lag}"] = float(a[k] - b[k])
    return out


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candles", default=os.path.join("data", "candles"))
    ap.add_argument("--spot-candles", default=os.path.join("data", "spot_candles"))
    ap.add_argument("--target", type=float, default=25.0)
    ap.add_argument("--stride", type=int, default=4,
                    help="use every Nth candle as an entry (1 = all). "
                         "Adjacent candles are near-duplicates anyway.")
    ap.add_argument("--duration", default=None, help="only this duration")
    ap.add_argument("--spot", default=None, help="only this underlying")
    ap.add_argument("--max-instruments", type=int, default=0,
                    help="cap instruments per expiry (0 = all); use for a "
                         "quick first pass")
    ap.add_argument("--min-entry-price", type=float, default=0.0,
                    help="tradeability floor on the entry candle's close")
    ap.add_argument("--episode-hours", type=float, default=24.0)
    ap.add_argument("--max-rows-per-episode", type=int, default=400)
    ap.add_argument("--out", default="discovery_parts")
    args = ap.parse_args()

    if not os.path.isdir(args.candles):
        sys.exit(f"ERROR: no candle dir at {args.candles}. Run from repo root.")

    print("=" * 70)
    print("DISCOVERY — pure candles, no hand-made signals")
    print("=" * 70)

    if os.path.exists(args.out):
        import shutil
        shutil.rmtree(args.out)
    os.makedirs(args.out)

    spots = ([args.spot] if args.spot
             else sorted(d for d in os.listdir(args.candles)
                         if os.path.isdir(os.path.join(args.candles, d))))
    print(f"\nunderlyings: {spots}")

    spot_cache = {}
    buf, nrow, part, ninstr = [], 0, 0, 0

    def flush():
        nonlocal buf, part
        if not buf:
            return
        df = pd.DataFrame(buf)
        buf = []
        for c in df.columns:
            if df[c].dtype == object and c not in ("symbol", "spot", "expiry"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            if pd.api.types.is_float_dtype(df[c]):
                df[c] = df[c].astype("float32")
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                       os.path.join(args.out, f"part-{part:05d}.parquet"),
                       compression="zstd")
        part += 1

    for sp in spots:
        sp_dir = os.path.join(args.candles, sp)
        expiries = sorted(d for d in os.listdir(sp_dir)
                          if os.path.isdir(os.path.join(sp_dir, d)))
        for exp in expiries:
            e_dir = os.path.join(sp_dir, exp)
            durs = sorted(os.listdir(e_dir))
            if args.duration:
                durs = [d for d in durs if d == str(args.duration)]
            for dur in durs:
                d_dir = os.path.join(e_dir, dur)
                if not os.path.isdir(d_dir):
                    continue
                files = [f for f in os.listdir(d_dir) if f.endswith(".json")]
                if args.max_instruments:
                    files = files[:args.max_instruments]

                key = (sp, dur)
                if key not in spot_cache:
                    spot_cache[key] = load_spot(args.spot_candles, sp, dur)
                sc = spot_cache[key]

                # Load the WHOLE directory first: surface features need every
                # strike present at the same instant, not one contract at a time.
                loaded = {}
                for fn in files:
                    try:
                        raw = json.load(open(os.path.join(d_dir, fn)))
                    except Exception:
                        continue
                    if not raw or len(raw) < W + 5:
                        continue
                    arr = np.asarray(raw, dtype=float)
                    if arr.ndim != 2 or arr.shape[1] < 5:
                        continue
                    loaded[fn[:-5]] = arr

                # index every series onto one shared time grid so "same
                # instant" is well defined across strikes
                if loaded:
                    grid = np.unique(np.concatenate(
                        [v[:, 0] for v in loaded.values()]))
                    chains = {}
                    for sname, arr in loaded.items():
                        p_ = sname.split("-")
                        ty = p_[0].upper() if p_ else "C"
                        try:
                            kk = float(p_[2])
                        except (IndexError, ValueError):
                            continue
                        col = np.full(len(grid), np.nan)
                        pos = np.searchsorted(grid, arr[:, 0])
                        pos = np.clip(pos, 0, len(grid) - 1)
                        col[pos] = arr[:, 4]
                        chains.setdefault(ty, []).append((kk, col))
                else:
                    grid, chains = np.array([]), {}

                for sym, a in loaded.items():
                    t, o, h, l, c = (a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4])
                    ninstr += 1

                    ratios = label_series(c, h, l, args.target)
                    expiry_ts = float(t[-1])

                    parts_ = sym.split("-")
                    opt_type = parts_[0].upper() if parts_ else "C"
                    try:
                        strike = float(parts_[2])
                    except (IndexError, ValueError):
                        strike = np.nan

                    for i in range(W - 1, len(c) - 1, args.stride):
                        r = ratios[i]
                        if not np.isfinite(r):
                            continue
                        if args.min_entry_price and c[i] < args.min_entry_price:
                            continue

                        row = shape_features(o, h, l, c, i, "opt_")

                        # spot context, aligned to this candle
                        spot_px = np.nan
                        if sc is not None:
                            st, scl, sh, sl = sc
                            j = int(np.searchsorted(st, t[i]))
                            j = min(max(j, W), len(scl) - 1)
                            spot_px = float(scl[j])
                            row.update(shape_features(
                                np.roll(scl, 1), sh, sl, scl, j, "spot_"))

                        # --- surface: where this strike sits on the chain now
                        if len(grid) and opt_type in chains:
                            gi = int(np.searchsorted(grid, t[i]))
                            gi = min(gi, len(grid) - 1)
                            row.update(surface_features(
                                chains[opt_type], gi, strike, c[i], spot_px))
                            row.update(surface_change(
                                chains[opt_type], gi, 4, strike))

                        tte = (expiry_ts - t[i]) / 3600.0
                        row.update({
                            "spot": sp, "expiry": exp, "symbol": sym,
                            "duration": int(dur),
                            "tteHours": tte,
                            "cheapness": (spot_px / c[i]) if c[i] > 0 else np.nan,
                            "moneynessPct": (
                                (strike - spot_px) / spot_px * 100
                                if opt_type == "C" else
                                (spot_px - strike) / spot_px * 100)
                                if np.isfinite(strike) and spot_px > 0 else np.nan,
                            "_ts_hours": t[i] / 3600.0,
                            "_peak": float(r),
                            "label": int(r >= args.target),
                            "signal": "pure_candles",
                        })
                        buf.append(row)
                        nrow += 1

                    if len(buf) >= 200_000:
                        flush()
                        print(f"  {ninstr:,} instruments, {nrow:,} rows, "
                              f"{part} parts", end="\r", flush=True)
    flush()
    print(f"  {ninstr:,} instruments, {nrow:,} rows, {part} parts" + " " * 15)

    if nrow == 0:
        sys.exit("\nERROR: no rows produced. Check --candles path and that "
                 "instruments have more than 13 candles each.")

    # ---- episodes + weighted negative sampling, matching step1 -----------
    import duckdb
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=4")
    src = os.path.join(args.out, "*.parquet").replace("\\", "/")

    con.execute(f"""
        CREATE OR REPLACE VIEW v AS
        SELECT *, spot || '#' || CAST(CAST(FLOOR(_ts_hours /
                 {args.episode_hours}) AS BIGINT) AS VARCHAR) AS episode_id
        FROM read_parquet('{src}', union_by_name=true)
    """)
    n, neps, pos, poseps = con.execute("""
        SELECT count(*), count(DISTINCT episode_id), sum(label),
               count(DISTINCT CASE WHEN label=1 THEN episode_id END) FROM v
    """).fetchone()

    print("\n" + "-" * 70)
    print(f"rows                 : {n:,}")
    print(f"independent episodes : {neps:,}")
    print(f"positive rows        : {int(pos or 0):,}  "
          f"({(pos or 0)/max(n,1)*100:.2f}%)")
    print(f"positive episodes    : {int(poseps or 0):,}")
    print("-" * 70)

    k = args.max_rows_per_episode
    final_dir = args.out + "_final"
    if os.path.exists(final_dir):
        import shutil
        shutil.rmtree(final_dir)
    os.makedirs(final_dir)
    con.execute(f"""
        COPY (
            SELECT * EXCLUDE (rn, n_neg), CASE WHEN label=1 THEN 1.0
                   ELSE GREATEST(1.0, n_neg::DOUBLE / {k}) END AS _w
            FROM (
                SELECT *, row_number() OVER (PARTITION BY episode_id, label
                                             ORDER BY random()) rn,
                       count(*) FILTER (WHERE label=0)
                           OVER (PARTITION BY episode_id) n_neg
                FROM v
            ) WHERE label = 1 OR rn <= {k}
        ) TO '{final_dir}' (FORMAT PARQUET, PARTITION_BY (spot),
                            COMPRESSION ZSTD, OVERWRITE_OR_IGNORE)
    """)
    kept = con.execute(
        f"SELECT count(*) FROM read_parquet('{final_dir}/**/*.parquet', "
        f"union_by_name=true)").fetchone()[0]
    print(f"\nsampled: {n:,} -> {kept:,} rows (all positives kept, "
          f"negatives weighted via _w)")
    print(f"\nwrote {final_dir}/")
    print(f"\nnext:")
    print(f"  python3 step2_baseline.py --data {final_dir}")
    print(f"  python3 step3_tune.py     --data {final_dir}")


if __name__ == "__main__":
    main()
