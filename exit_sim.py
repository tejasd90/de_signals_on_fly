#!/usr/bin/env python3
"""
exit_sim.py — the missing number: what do you actually GET BACK when stopped?

Everything in this project so far measures P(peak >= T). That is the fill
probability for a limit order at T, which is correct and tradeable. But
expectancy also needs the LOSS side, and nothing computes it:

    R(T) = T                if _peak >= T   (limit at T fills on the way up)
         = stop_ratio       otherwise       (exit at the stop candle's close)

    expectancy(T) = mean(R(T)) - 1     [units of premium staked]

Because the stop rule does not depend on T, ONE new column (stop_ratio) yields
expectancy at every target. That is what this script computes.

Stop rule is byte-identical to discover_build.label_series:
    walk forward from entry i, stop at the first candle that CLOSES below
    low[i], capped at --max-hold candles. Peak = max high strictly BEFORE the
    stop candle.

Output: parquet keyed (symbol, ts) so it joins onto disc_final rows.
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

def sim_series(closes, highs, lows, hold):
    """Returns (peak, stop_ratio, held_bars, stopped) per entry index."""
    n = len(closes)
    peak = np.full(n, np.nan); sr = np.full(n, np.nan)
    held = np.zeros(n, np.int32); stopped = np.zeros(n, bool)
    for i in range(n - 1):
        c = closes[i]
        if not (c > 0):
            continue
        end = min(n, i + 1 + hold)
        lo = lows[i]
        below = np.nonzero(closes[i + 1:end] < lo)[0]
        if len(below):
            stop = i + 1 + int(below[0]); stopped[i] = True
        else:
            stop = end
        # exit price: close of the stop candle; if never stopped, close of the
        # last candle actually held. Both are prices you could transact at.
        exit_idx = stop if stopped[i] else end - 1
        if exit_idx >= n:
            exit_idx = n - 1
        sr[i] = closes[exit_idx] / c
        held[i] = exit_idx - i
        if stop <= i + 1:
            peak[i] = 0.0          # stopped immediately, no upside captured
            continue
        peak[i] = float(highs[i + 1:stop].max() / c)
    return peak, sr, held, stopped

def do_expiry(job):
    spot, expiry, d, path = job
    rows = []
    try:
        files = os.listdir(path)
    except OSError:
        return rows
    for fn in files:
        if not fn.endswith(".json"):
            continue
        try:
            a = np.asarray(json.load(open(os.path.join(path, fn))), dtype=float)
        except Exception:
            continue
        if a.ndim != 2 or a.shape[1] < 5 or len(a) < 3:
            continue
        t, h, l, c = a[:, 0], a[:, 2], a[:, 3], a[:, 4]
        peak, sr, held, st = sim_series(c, h, l, args_hold)
        ok = np.isfinite(peak) & np.isfinite(sr)
        if not ok.any():
            continue
        sym = fn[:-5]
        rows.append(pd.DataFrame({
            "symbol": sym, "spot": spot, "expiry": expiry,
            "duration": int(d), "ts": t[ok].astype(np.int64),
            "entry_px": c[ok].astype(np.float32),
            "peak": peak[ok].astype(np.float32),
            "stop_ratio": sr[ok].astype(np.float32),
            "held": held[ok].astype(np.int16),
            "stopped": st[ok],
        }))
    return rows

def init(hold):
    global args_hold
    args_hold = hold

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--candles", default="data/candles")
    ap.add_argument("--duration", default="60")
    ap.add_argument("--max-hold", type=int, default=72)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="exits")
    ap.add_argument("--flush", type=int, default=400)
    a = ap.parse_args()

    jobs = []
    for spot in sorted(os.listdir(a.candles)):
        sp = os.path.join(a.candles, spot)
        if not os.path.isdir(sp):
            continue
        for expiry in sorted(os.listdir(sp)):
            p = os.path.join(sp, expiry, a.duration)
            if os.path.isdir(p):
                jobs.append((spot, expiry, a.duration, p))
    print(f"{len(jobs)} expiry dirs, duration={a.duration}, hold<={a.max_hold}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time(); buf = []; part = 0; ninstr = 0
    with ProcessPoolExecutor(a.workers, initializer=init,
                             initargs=(a.max_hold,)) as ex:
        for k, rows in enumerate(ex.map(do_expiry, jobs, chunksize=2), 1):
            buf.extend(rows); ninstr += len(rows)
            if len(buf) >= a.flush:
                pd.concat(buf, ignore_index=True).to_parquet(
                    f"{a.out}/part-{part:05d}.parquet", index=False)
                part += 1; buf = []
            if k % 100 == 0:
                el = time.time() - t0
                print(f"  {k}/{len(jobs)} dirs | {ninstr:,} instruments | "
                      f"{el/60:.1f}m | eta {el/k*(len(jobs)-k)/60:.1f}m", flush=True)
    if buf:
        pd.concat(buf, ignore_index=True).to_parquet(
            f"{a.out}/part-{part:05d}.parquet", index=False)
    print(f"done: {ninstr:,} instruments, {part+1} shards, {(time.time()-t0)/60:.1f}m")
