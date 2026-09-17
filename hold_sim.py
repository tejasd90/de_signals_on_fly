#!/usr/bin/env python3
"""
hold_sim.py — NO STOP LOSS. Buy, rest a GTC limit at the target, walk away.

Policy being measured (Tejas's, 2026-09-10):
  - no stop. If it goes to zero, it goes to zero.
  - exit is a RESTING GTC LIMIT at T x entry, live for the option's whole
    remaining life. So "did it ever trade through T" is the fill test, and
    there is nothing to monitor.
  - if it never reaches T, it is held to expiry and settles at whatever it is.

NOTE ON PRICES: these are MARK prices, not trade prices, and they diverge from
trade prices near expiry. peak_full is therefore an UPPER BOUND on fill
probability, not a fill probability. Pair every number here with the capture
haircut in the analysis (what fraction of the marked move you must realize).

Emits per entry candle i:
  peak_full = max(high[i+1..expiry]) / close[i]  -> GTC fill test, no stop
  peak_72   = max(high[i+1..i+72])   / close[i]  -> if you gave up after 72
  terminal  = close[last] / close[i]             -> what you keep if it never fills
"""
import argparse, json, os, time
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor

def do_expiry(job):
    spot, expiry, path = job
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
        t, h, c = a[:, 0], a[:, 2], a[:, 4]
        n = len(c)
        # suffix max: sufmax[i] = max(high[i..n-1]); no stop, so the whole
        # remaining life is in play -- this is the point of the policy
        sufmax = np.maximum.accumulate(h[::-1])[::-1]
        idx = np.arange(n - 1)
        cc = c[:-1]
        ok = cc > 0
        if not ok.any():
            continue
        idx = idx[ok]; cc = cc[ok]
        pf = sufmax[idx + 1] / cc
        p72 = np.array([h[i + 1:min(n, i + 73)].max() for i in idx]) / cc
        term = c[-1] / cc
        rows.append(pd.DataFrame({
            "symbol": fn[:-5], "spot": spot, "expiry": expiry,
            "ts": t[idx].astype(np.int64),
            "peak_full": pf.astype(np.float32),
            "peak_72": p72.astype(np.float32),
            "terminal": term.astype(np.float32)}))
    return rows

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--candles", default="data/candles")
    ap.add_argument("--duration", default="60")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="holds")
    ap.add_argument("--flush", type=int, default=400)
    a = ap.parse_args()
    jobs = []
    for spot in sorted(os.listdir(a.candles)):
        sp = os.path.join(a.candles, spot)
        if not os.path.isdir(sp):
            continue
        for ex in sorted(os.listdir(sp)):
            p = os.path.join(sp, ex, a.duration)
            if os.path.isdir(p):
                jobs.append((spot, ex, p))
    os.makedirs(a.out, exist_ok=True)
    print(f"{len(jobs)} expiry dirs", flush=True)
    t0 = time.time(); buf = []; part = 0; n = 0
    with ProcessPoolExecutor(a.workers) as ex:
        for k, rows in enumerate(ex.map(do_expiry, jobs, chunksize=2), 1):
            buf.extend(rows); n += len(rows)
            if len(buf) >= a.flush:
                pd.concat(buf, ignore_index=True).to_parquet(
                    f"{a.out}/part-{part:05d}.parquet", index=False)
                part += 1; buf = []
            if k % 400 == 0:
                el = time.time() - t0
                print(f"  {k}/{len(jobs)} | {el/60:.1f}m | eta {el/k*(len(jobs)-k)/60:.1f}m", flush=True)
    if buf:
        pd.concat(buf, ignore_index=True).to_parquet(
            f"{a.out}/part-{part:05d}.parquet", index=False)
    print(f"done {n:,} instruments, {(time.time()-t0)/60:.1f}m")
