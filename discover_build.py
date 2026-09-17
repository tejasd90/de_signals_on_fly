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

import argparse, json, os, sys, time
from datetime import datetime
import numpy as np
import pandas as pd

_T0 = time.time()


def log(msg, end="\n"):
    """Every line carries wall-clock time and elapsed, so a slow phase is
    obvious from the transcript alone."""
    el = time.time() - _T0
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp} +{int(el)//60:02d}:{int(el)%60:02d}] {msg}",
          end=end, flush=True)

try:
    import pyarrow as pa, pyarrow.parquet as pq
except ImportError:
    sys.exit("ERROR: pip install pyarrow")

W = 8          # candles of history per feature row
EPS = 1e-12


# ------------------------------------------------------------------ spot

def realized_vol(closes, window=24, periods_per_year=8760):
    """Annualised rolling realized volatility from spot log returns.

    Needed for standardized moneyness. Trailing window only — no lookahead.
    Floored/capped to keep the sqrt(T) division well behaved in dead-quiet or
    blow-off regimes.
    """
    lr = np.diff(np.log(np.maximum(closes, EPS)))
    lr = np.insert(lr, 0, 0.0)
    sd = pd.Series(lr).rolling(window).std().fillna(0.0).to_numpy()
    return np.clip(sd * np.sqrt(periods_per_year), 0.10, 5.0)


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
    vol = realized_vol(a[:, 4])
    return a[:, 0], a[:, 4], a[:, 2], a[:, 3], vol   # t, close, high, low, vol


# ------------------------------------------------------------------ label

def label_series(closes, highs, lows, target, max_hold=None):
    """
    For every candle i: walk forward to the first close below low[i]; the
    outcome is the best high before that, over close[i].

    O(n^2) but n is a few hundred per instrument, so it is not the bottleneck.
    """
    n = len(closes)
    out = np.full(n, np.nan)
    # BOUND THE HOLD WINDOW. Without this, a signal 200 candles before expiry
    # gets a 200-candle window while one near expiry gets 5 — the label then
    # measures how much time was left, not what the setup did.
    hold = n if max_hold is None else int(max_hold)
    for i in range(n - 1):
        c = closes[i]
        if not (c > 0):
            continue
        end = min(n, i + 1 + hold)
        stop = end
        lo = lows[i]
        # first j > i whose CLOSE is below the entry candle's low
        below = np.nonzero(closes[i + 1:end] < lo)[0]
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

class LazyChainCache:
    """Compute a timestamp's chain fit only when a row actually asks for it.

    Eager building fitted every timestamp in the grid; at --stride N only
    ~1/N are ever used, so most of that work was thrown away. The grid is the
    UNION of all instruments' timestamps, so it is often far larger than any
    single instrument's series.
    """

    __slots__ = ("strikes", "mat", "n_times", "_c")

    def __init__(self, chain, n_times):
        self._c = {}
        self.n_times = n_times
        if not chain:
            self.strikes = np.array([]); self.mat = None; return
        ks = np.array([k for k, _ in chain], dtype=float)
        mat = np.vstack([col for _, col in chain])
        o = np.argsort(ks)
        self.strikes = ks[o]; self.mat = mat[o]

    def get(self, ti):
        if self.mat is None or ti < 0 or ti >= self.n_times:
            return None
        e = self._c.get(ti, False)
        if e is not False:
            return e
        e = _fit_one(self.strikes, self.mat[:, ti])
        self._c[ti] = e
        return e


def _fit_one(strikes, ps):
    ok = np.isfinite(ps) & (ps > 0)
    if ok.sum() < 4:
        return None
    ks_, ps_ = strikes[ok], ps[ok]
    logp = np.log(ps_)
    e = {"ks": ks_, "ps": ps_, "med": float(np.median(ps_)),
         "n": float(len(ks_)), "disp": float(logp.std()),
         "total": float(ps_.sum()), "width": float(ks_.max() - ks_.min())}
    sd_k = float(ks_.std())
    if sd_k <= EPS:
        return e
    kn = (ks_ - ks_.mean()) / sd_k
    try:
        c2, c1, c0 = np.polyfit(kn, logp, 2)
        resid = logp - np.polyval([c2, c1, c0], kn)
        e.update(slope=float(c1), curv=float(c2),
                 r2=float(1 - resid.var() / max(logp.var(), EPS)),
                 resid=resid, resid_sd=max(float(resid.std()), EPS))
    except Exception:
        pass
    return e


def build_chain_cache(chain, n_times, spot_series=None):
    """
    Precompute the chain fit ONCE PER TIMESTAMP, not once per instrument.

    The skew slope, curvature and dispersion at time t are properties of the
    WHOLE chain — identical for every strike in it. Computing them per row
    repeated the same polyfit 60-200 times per timestamp and was 70% of total
    runtime.

    Returns {ti: dict} with the chain-level numbers plus what a per-strike
    lookup needs.
    """
    cache = {}
    if not chain:
        return cache
    strikes = np.array([k for k, _ in chain], dtype=float)
    mat = np.vstack([col for _, col in chain])          # strikes x time
    order = np.argsort(strikes)
    strikes = strikes[order]
    mat = mat[order]

    for ti in range(n_times):
        ps = mat[:, ti]
        ok = np.isfinite(ps) & (ps > 0)
        if ok.sum() < 4:
            continue
        ks_, ps_ = strikes[ok], ps[ok]
        logp = np.log(ps_)
        e = {"ks": ks_, "ps": ps_, "med": float(np.median(ps_)),
             "n": float(len(ks_)), "disp": float(logp.std()),
             "total": float(ps_.sum()),
             "width": float(ks_.max() - ks_.min())}
        sd_k = float(ks_.std())
        if sd_k <= EPS:          # degenerate chain — nothing to fit
            cache[ti] = e
            continue
        kn = (ks_ - ks_.mean()) / sd_k
        try:
            c2, c1, c0 = np.polyfit(kn, logp, 2)
            resid = logp - np.polyval([c2, c1, c0], kn)
            e.update(slope=float(c1), curv=float(c2),
                     r2=float(1 - resid.var() / max(logp.var(), EPS)),
                     resid=resid, resid_sd=max(float(resid.std()), EPS))
        except Exception:
            pass
        cache[ti] = e
    return cache


def surface_row(cache, ti, my_strike, my_prem, spot_px, lag=4):
    """Per-strike lookup against the chain fit — cheap."""
    e = cache.get(ti)
    f = {}
    if e is None or not (my_prem > 0):
        return f
    ks_, ps_ = e["ks"], e["ps"]
    f["surf_n_strikes"] = e["n"]
    f["surf_prem_rank"] = float((ps_ < my_prem).mean())
    f["surf_strike_rank"] = float((ks_ < my_strike).mean())
    f["surf_prem_vs_med"] = float(my_prem / max(e["med"], EPS))
    f["surf_prem_disp"] = e["disp"]
    f["surf_frac_cheaper"] = f["surf_prem_rank"]
    if "slope" in e:
        f["surf_skew_slope"] = e["slope"]
        f["surf_skew_curv"] = e["curv"]
        f["surf_fit_r2"] = e["r2"]
        j = int(np.argmin(np.abs(ks_ - my_strike)))
        f["surf_resid_z"] = float(e["resid"][j] / e["resid_sd"])
    if spot_px and spot_px > 0:
        f["surf_width_pct"] = float(e["width"] / spot_px * 100)
        f["surf_total_prem"] = float(e["total"] / spot_px)

    prev = cache.get(ti - lag)
    if prev is not None and "slope" in e and "slope" in prev:
        f[f"surf_skew_slope_chg{lag}"] = float(e["slope"] - prev["slope"])
        f[f"surf_skew_curv_chg{lag}"] = float(e["curv"] - prev["curv"])
        f[f"surf_prem_disp_chg{lag}"] = float(e["disp"] - prev["disp"])
    return f


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candles", default=os.path.join("data", "candles"))
    ap.add_argument("--spot-candles", default=os.path.join("data", "spot_candles"))
    ap.add_argument("--targets", default="5,10,25,50,100",
                    help="thresholds to emit labels for. The heavy work "
                         "(candles, shapes, surface fits) is target-"
                         "INDEPENDENT, so one build serves all of them. "
                         "Negative sampling keeps every row above the LOWEST "
                         "target, so higher ones are exact subsets.")
    ap.add_argument("--target", type=float, default=None,
                    help="single target; shorthand for --targets")
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
    ap.add_argument("--max-hold-candles", type=int, default=72,
                    help="cap the forward window so every entry gets the same "
                         "horizon regardless of DTE")
    ap.add_argument("--calibrate", type=int, default=8,
                    help="chains to time before starting, for the ETA "
                         "(0 = skip)")
    ap.add_argument("--estimate-only", action="store_true",
                    help="print the time estimate and exit without processing")
    ap.add_argument("--episode-hours", type=float, default=24.0)
    ap.add_argument("--max-rows-per-episode", type=int, default=400)
    ap.add_argument("--resume", action="store_true",
                    help="reuse parquet shards already in --out and jump "
                         "straight to episodes/sampling. Use after an OOM or "
                         "power cut — the candle scan is the expensive part.")
    ap.add_argument("--memory-limit", default="4GB",
                    help="DuckDB cap; it spills to disk beyond this")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--chunk-episodes", type=int, default=100,
                    help="episodes per output part; lower = less memory")
    ap.add_argument("--flush-rows", type=int, default=25_000,
                    help="rows buffered before writing a parquet part; lower "
                         "if memory is tight")
    ap.add_argument("--out", default="discovery_parts")
    args = ap.parse_args()

    targets = ([args.target] if args.target is not None else
               [float(x) for x in args.targets.split(",") if x.strip()])
    targets = sorted(set(targets))
    args.target = targets[0]          # lowest drives sampling
    if not os.path.isdir(args.candles):
        sys.exit(f"ERROR: no candle dir at {args.candles}. Run from repo root.")

    log("=" * 66)
    log("DISCOVERY — pure candles, no hand-made signals")
    log("=" * 66)
    log(f"targets {', '.join(f'{t:g}x' for t in targets)} | "
        f"stride {args.stride} | hold<={args.max_hold_candles} candles | "
        f"window {W} candles")

    import shutil
    have_shards = (os.path.isdir(args.out) and
                   any(f.endswith(".parquet") for f in os.listdir(args.out)))
    if args.resume and have_shards:
        nparts = len([f for f in os.listdir(args.out)
                      if f.endswith(".parquet")])
        log(f"RESUME: reusing {nparts} existing parquet parts in {args.out}/")
        log("        skipping phases 1-3 (the expensive candle scan)")
    else:
        if os.path.exists(args.out):
            shutil.rmtree(args.out)
        os.makedirs(args.out)

    spots = ([args.spot] if args.spot
             else sorted(d for d in os.listdir(args.candles)
                         if os.path.isdir(os.path.join(args.candles, d))))
    log(f"PHASE 1/5  scanning tree — underlyings {spots}")

    # count the work up front so progress can show an ETA
    log("PHASE 2/5  counting files ...")
    todo = []
    for sp in spots:
        sp_dir = os.path.join(args.candles, sp)
        if not os.path.isdir(sp_dir):
            continue
        for exp in sorted(os.listdir(sp_dir)):
            e_dir = os.path.join(sp_dir, exp)
            if not os.path.isdir(e_dir):
                continue
            for dur in sorted(os.listdir(e_dir)):
                if args.duration and dur != str(args.duration):
                    continue
                d_dir = os.path.join(e_dir, dur)
                if os.path.isdir(d_dir):
                    todo.append((sp, exp, dur, d_dir))
    total_dirs = len(todo)
    total_files = sum(len([f for f in os.listdir(d) if f.endswith(".json")])
                      for _, _, _, d in todo)
    if args.max_instruments:
        total_files = min(total_files, total_dirs * args.max_instruments)
    log(f"  {total_dirs:,} chains, ~{total_files:,} instrument files")
    if total_files > 200_000 and not args.max_instruments:
        log("  ! large run. Consider --max-instruments 40 or --stride 8 "
            "for a first pass.")

    # ---- calibration: time a few real chains, extrapolate ---------------
    if args.resume and have_shards:
        nrow = 1        # real count comes from the shards below
    else:
        log("PHASE 3/5  processing")
        if args.calibrate and total_dirs > args.calibrate:
            log(f"calibrating on {args.calibrate} chains ...")
            # Random sample, not strided: a fixed stride hit unrepresentatively
            # small chains and under-estimated the run by 14x.
            _rng = np.random.default_rng(0)
            idx = _rng.choice(total_dirs, size=min(args.calibrate, total_dirs),
                              replace=False)
            sample = [todo[i] for i in idx]
            cal_files = 0
            t_cal0 = time.time()
            cal_rows = cal_instr = 0
            for sp_, exp_, dur_, dd_ in sample:
                fs = [f for f in os.listdir(dd_) if f.endswith(".json")]
                if args.max_instruments:
                    fs = fs[:args.max_instruments]
                ld = {}
                for fn in fs:
                    try:
                        rr = json.load(open(os.path.join(dd_, fn)))
                    except Exception:
                        continue
                    if not rr or len(rr) < W + 5:
                        continue
                    aa = np.asarray(rr, dtype=float)
                    if aa.ndim == 2 and aa.shape[1] >= 5:
                        ld[fn[:-5]] = aa
                cal_files += len(ld)
                if not ld:
                    continue
                g = np.unique(np.concatenate([v[:, 0] for v in ld.values()]))
                ch = []
                for sn, aa in ld.items():
                    pp = sn.split("-")
                    try:
                        kk_ = float(pp[2])
                    except (IndexError, ValueError):
                        continue
                    col = np.full(len(g), np.nan)
                    col[np.clip(np.searchsorted(g, aa[:, 0]), 0, len(g) - 1)] = aa[:, 4]
                    ch.append((kk_, col))
                cc = LazyChainCache(ch, len(g))
                for sn, aa in ld.items():
                    cal_instr += 1
                    pp = sn.split("-")
                    try:
                        kk_ = float(pp[2])
                    except (IndexError, ValueError):
                        kk_ = 0.0
                    label_series(aa[:, 4], aa[:, 2], aa[:, 3], args.target,
                                 args.max_hold_candles)
                    for i in range(W - 1, len(aa) - 1, args.stride):
                        # mirror the real per-row work: option shape + spot shape
                        # + surface lookup + dict assembly, or the estimate lands
                        # well under the true cost
                        rr_ = shape_features(aa[:, 1], aa[:, 2], aa[:, 3],
                                             aa[:, 4], i, "opt_")
                        rr_.update(shape_features(aa[:, 1], aa[:, 2], aa[:, 3],
                                                  aa[:, 4], i, "spot_"))
                        gi_ = int(np.searchsorted(g, aa[i, 0]))
                        rr_.update(surface_row(cc, min(gi_, len(g) - 1), kk_,
                                               float(aa[i, 4]), 95000.0))
                        rr_.update({"spot": sp_, "expiry": exp_, "symbol": sn,
                                    "duration": 0, "tteHours": 0.0,
                                    "cheapness": 0.0, "stdMoneyness": 0.0,
                                    "moneynessPct": 0.0, "spotVol": 0.0,
                                    "_ts_hours": 0.0, "_peak": 0.0,
                                    "label": 0, "signal": "pure_candles"})
                        cal_rows += 1
            t_cal = time.time() - t_cal0
            if cal_rows and t_cal > 0:
                # Scale by FILE count, which we counted exactly, rather than by
                # chain count — chains vary hugely in how many instruments they
                # hold and how long each series is.
                per_file = t_cal / max(cal_files, 1)
                # +25% for parquet encoding, DuckDB episode pass and file I/O,
                # which the calibration loop does not perform
                est_s = per_file * total_files * 1.25
                est_rows = int(cal_rows / max(cal_files, 1) * total_files)
                log(f"  timed {cal_rows:,} rows from {cal_files:,} files "
                    f"in {t_cal:.1f}s "
                    f"({cal_rows/max(cal_files,1):.0f} rows/file)")
                log("")
                log(f"  ESTIMATE: ~{est_rows:,} rows, "
                    f"~{est_s/60:.1f} minutes ({est_s/3600:.2f} h)  [+/- 25%]")
                log(f"  finishing around "
                    f"{datetime.fromtimestamp(time.time()+est_s).strftime('%H:%M:%S')}")
                log("")
                if est_s > 3600:
                    log("  ! over an hour. To cut it: raise --stride, lower")
                    log("    --max-instruments, or restrict --duration / --spot.")
            if args.estimate_only:
                log("estimate-only requested — stopping here.")
                return

        t_start = time.time()
        spot_cache = {}
        buf, nrow, part, ninstr, n_spot_miss = [], 0, 0, 0, 0

        def flush():
            nonlocal buf, part
            if not buf:
                return
            df = pd.DataFrame(buf)
            buf = []
            # NOTE: 'signal' must be excluded from numeric coercion —
            # turning "pure_candles" into NaN makes a downstream
            # groupby('signal') yield ZERO groups, and the caller then exits
            # silently having trained nothing.
            keep_text = ("symbol", "spot", "expiry", "signal")
            for c in df.columns:
                if df[c].dtype == object and c not in keep_text:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                if pd.api.types.is_float_dtype(df[c]):
                    df[c] = df[c].astype("float32")
            df.replace([np.inf, -np.inf], np.nan, inplace=True)
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                           os.path.join(args.out, f"part-{part:05d}.parquet"),
                           compression="zstd")
            part += 1

        for _di, (sp, exp, dur, d_dir) in enumerate(todo, 1):
                if True:   # (indentation preserved from the original nesting)
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
                        surf_cache = {ty: LazyChainCache(ch, len(grid))
                                      for ty, ch in chains.items()}
                    else:
                        grid, chains, surf_cache = np.array([]), {}, {}

                    for sym, a in loaded.items():
                        t, o, h, l, c = (a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4])
                        ninstr += 1

                        ratios = label_series(c, h, l, args.target,
                                              args.max_hold_candles)
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
                                st, scl, sh, sl, svol = sc
                                j = int(np.searchsorted(st, t[i]))
                                j = min(max(j, W), len(scl) - 1)
                                # Clamping alone would silently reuse the LAST spot
                                # candle for every option row past the end of spot
                                # history, poisoning spot price, vol and moneyness.
                                # Reject the match instead.
                                if abs(st[j] - t[i]) > int(dur) * 60 * 3:
                                    n_spot_miss += 1
                                    j = None
                            if sc is not None and j is not None:
                                spot_px = float(scl[j])
                                # spot "open" is the previous close — spot_store
                                # keeps OHLC but load_spot carries close/high/low
                                row.update(shape_features(
                                    np.roll(scl, 1), sh, sl, scl, j, "spot_"))

                            # --- surface: where this strike sits on the chain now
                            if len(grid) and opt_type in surf_cache:
                                gi = int(np.searchsorted(grid, t[i]))
                                gi = min(gi, len(grid) - 1)
                                row.update(surface_row(
                                    surf_cache[opt_type], gi, strike, c[i], spot_px))

                            tte = (expiry_ts - t[i]) / 3600.0

                            spot_vol = np.nan
                            std_mny = np.nan
                            if sc is not None and spot_px > 0 and np.isfinite(strike):
                                spot_vol = float(svol[j])
                                T_yrs = max(tte, 1e-6) / 8760.0
                                denom = spot_vol * np.sqrt(T_yrs)
                                if denom > 0:
                                    std_mny = float(np.clip(
                                        np.log(strike / spot_px) / denom, -15, 15))
                                    if opt_type == "P":
                                        std_mny = -std_mny
                            row.update({
                                "spot": sp, "expiry": exp, "symbol": sym,
                                "duration": int(dur),
                                "tteHours": tte,
                                "cheapness": (spot_px / c[i]) if c[i] > 0 else np.nan,
                                # STANDARDIZED MONEYNESS: ln(K/S) / (sigma*sqrt(T)).
                                # Raw "5% OTM" is meaningless on its own — 5% OTM
                                # with 6h left and with 30d left are unrelated
                                # trades. This expresses distance in units of the
                                # move the market can actually make in the time
                                # remaining, which is the whole "deep OTM *with
                                # respect to* DTE/vol/spot" idea as one number.
                                "stdMoneyness": std_mny,
                                "moneynessPct": (
                                    (strike - spot_px) / spot_px * 100
                                    if opt_type == "C" else
                                    (spot_px - strike) / spot_px * 100)
                                    if np.isfinite(strike) and spot_px > 0 else np.nan,
                                "spotVol": spot_vol,
                                "_ts_hours": t[i] / 3600.0,
                                "_peak": float(r),
                                "label": int(r >= targets[0]),
                                "signal": "pure_candles",
                            })
                            buf.append(row)
                            nrow += 1

                        # Flush often: each row is a ~160-key Python dict, so a
                        # 200k buffer is gigabytes before pandas ever sees it.
                        if len(buf) >= args.flush_rows:
                            flush()

                    if _di % 20 == 0 or _di == total_dirs:
                        el = time.time() - t_start
                        frac = _di / max(total_dirs, 1)
                        eta = el / max(frac, 1e-9) - el
                        log(f"  chain {_di:,}/{total_dirs:,} ({frac*100:.1f}%)  "
                            f"{ninstr:,} instr  {nrow:,} rows  "
                            f"{part} parts  ETA {eta/60:.1f}m", end="\r")
        flush()
        log(f"  done: {ninstr:,} instruments, {nrow:,} rows, {part} parts"
            + " " * 20)
        if n_spot_miss:
            log(f"  ! {n_spot_miss:,} rows had no aligned spot candle "
                f"(spot features left empty)")

        if nrow == 0:
            sys.exit("\nERROR: no rows produced. Check --candles path and that "
                     "instruments have more than 13 candles each.")

        # ---- episodes + weighted negative sampling, matching step1 -----------
    log("PHASE 4/5  assigning episodes and sampling (DuckDB)")
    import duckdb
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET temp_directory='{os.path.join(args.out + '_tmp')}'")
    src = os.path.join(args.out, "*.parquet").replace("\\", "/")

    lbls = ", ".join(
        f"CASE WHEN _peak >= {t} THEN 1 ELSE 0 END AS label_{str(t).replace('.','_')}"
        for t in targets)
    con.execute(f"""
        CREATE OR REPLACE VIEW v AS
        SELECT * EXCLUDE (label), {lbls},
               CASE WHEN _peak >= {targets[0]} THEN 1 ELSE 0 END AS label,
               spot || '#' || CAST(CAST(FLOOR(_ts_hours /
                 {args.episode_hours}) AS BIGINT) AS VARCHAR) AS episode_id
        FROM read_parquet('{src}', union_by_name=true)
    """)

    log("")
    log("POSITIVES BY TARGET (before sampling)")
    log(f"  {'target':>8}{'rows':>12}{'rate':>9}{'episodes':>11}")
    for t in targets:
        col = f"label_{str(t).replace('.','_')}"
        pr, pe = con.execute(
            f"SELECT sum({col}), count(DISTINCT CASE WHEN {col}=1 "
            f"THEN episode_id END) FROM v").fetchone()
        tot = con.execute("SELECT count(*) FROM v").fetchone()[0]
        flag = "  <- too few to train" if (pe or 0) < 30 else ""
        log(f"  {t:>7g}x{int(pr or 0):>12,}{(pr or 0)/max(tot,1)*100:>8.2f}%"
            f"{int(pe or 0):>11,}{flag}")
    log("")
    n, neps, pos, poseps = con.execute("""
        SELECT count(*), count(DISTINCT episode_id), sum(label),
               count(DISTINCT CASE WHEN label=1 THEN episode_id END) FROM v
    """).fetchone()

    log("-" * 66)
    log(f"rows                 : {n:,}")
    log(f"independent episodes : {neps:,}")
    log(f"positive rows        : {int(pos or 0):,}  "
        f"({(pos or 0)/max(n,1)*100:.2f}%)")
    log(f"positive episodes    : {int(poseps or 0):,}")
    log("-" * 66)

    k = args.max_rows_per_episode
    final_dir = args.out + "_final"
    if os.path.exists(final_dir):
        shutil.rmtree(final_dir)
    os.makedirs(final_dir)

    # CHUNKED SAMPLING.
    # The single-shot version ran two window functions over every row at once —
    # 8.5M rows x ~160 columns is several GB before DuckDB has room to sort.
    # episode_id is a deterministic time bucket, so the work splits cleanly:
    # take a slice of buckets at a time, write one part per slice, bound memory
    # by slice size instead of table size.
    log(f"  sampling in chunks of {args.chunk_episodes} episodes "
        f"(memory cap {args.memory_limit})")
    spots_ = [r[0] for r in con.execute(
        "SELECT DISTINCT spot FROM v ORDER BY 1").fetchall()]
    kept = kept_pos = part_i = 0
    width = args.episode_hours * args.chunk_episodes

    for sp_ in spots_:
        lo_, hi_ = con.execute(
            "SELECT min(_ts_hours), max(_ts_hours) FROM v WHERE spot = ?",
            [sp_]).fetchone()
        if lo_ is None:
            continue
        edges = np.arange(lo_, hi_ + width, width)
        for ei in range(len(edges) - 1):
            a_, b_ = float(edges[ei]), float(edges[ei + 1])
            sel = (f"SELECT * FROM v WHERE spot = '{sp_}' "
                   f"AND _ts_hours >= {a_} AND _ts_hours < {b_}")
            sel = (f"""
                SELECT * EXCLUDE (rn, n_neg),
                       CASE WHEN label = 1 THEN 1.0
                            ELSE GREATEST(1.0, n_neg::DOUBLE / {k}) END AS _w
                FROM (
                    SELECT *,
                      row_number() OVER (PARTITION BY episode_id, label
                                         ORDER BY random()) rn,
                      count(*) FILTER (WHERE label = 0)
                          OVER (PARTITION BY episode_id) n_neg
                    FROM ({sel})
                ) WHERE label = 1 OR rn <= {k}
            """)
            nh = con.execute(f"SELECT count(*) FROM ({sel})").fetchone()[0]
            if not nh:
                continue
            p_ = os.path.join(final_dir, f"part-{part_i:05d}.parquet")
            con.execute(f"COPY ({sel}) TO '{p_}' "
                        f"(FORMAT PARQUET, COMPRESSION ZSTD)")
            kept += nh
            part_i += 1
            if part_i % 10 == 0:
                log(f"    {part_i} parts, {kept:,} rows", end="\r")
    log(f"    {part_i} parts, {kept:,} rows" + " " * 20)

    ds_ = os.path.join(final_dir, "*.parquet").replace("\\", "/")
    wpos, wtot = con.execute(
        f"SELECT sum(_w) FILTER (WHERE label=1), sum(_w) "
        f"FROM read_parquet('{ds_}', union_by_name=true)").fetchone()
    log(f"sampled: {n:,} -> {kept:,} rows "
        f"({n/max(kept,1):.1f}x smaller)")
    log(f"  positive rate {(pos or 0)/max(n,1)*100:.2f}% -> "
        f"{(wpos or 0)/max(wtot or 1,1)*100:.2f}% weighted "
        f"(all positives kept, negatives weighted via _w)")

    log(f"PHASE 5/5  wrote {final_dir}/")
    log(f"TOTAL RUNTIME {(time.time()-_T0)/60:.1f} minutes")
    log("")
    log("next:")
    log(f"  python3 step2_baseline.py --data {final_dir}")
    log(f"  python3 step3_tune.py     --data {final_dir}")


if __name__ == "__main__":
    main()
