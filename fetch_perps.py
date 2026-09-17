#!/usr/bin/env python3
"""
fetch_perps.py — backfill hourly candles for every live perpetual future.

Delta's /v2/history/candles caps a single response (~4000 rows), so a naive
one-shot request silently returns only the most recent window and every symbol
looks like it launched on the same day. This paginates BACKWARD until the API
stops returning new data, exactly like api.js fetchCandles does.

These are TRADED perp candles (plain symbol, no MARK: prefix), so unlike the
option chain they carry real volume.

Resumable: a symbol whose parquet already covers up to --end is skipped.
"""
import argparse, json, os, time, urllib.request, urllib.error
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE = "https://api.india.delta.exchange/v2/history/candles"

def fetch_window(sym, res, a, b, tries=4):
    u = f"{BASE}?symbol={sym}&resolution={res}&start={int(a)}&end={int(b)}"
    for k in range(tries):
        try:
            with urllib.request.urlopen(u, timeout=45) as r:
                return json.load(r).get("result") or []
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (k + 1)); continue
            if e.code >= 500:
                time.sleep(1.0 * (k + 1)); continue
            return []
        except Exception:
            time.sleep(1.0 * (k + 1))
    return []

def fetch_all(sym, res, start, end, delay=0.12):
    """Paginate backward from `end` until the API returns nothing new."""
    out = {}
    cur = end
    for _ in range(200):                      # hard stop; 200 pages is plenty
        rows = fetch_window(sym, res, start, cur)
        if not rows:
            break
        new = 0
        for c in rows:
            t = int(c["time"])
            if t not in out:
                out[t] = (t, float(c["open"]), float(c["high"]), float(c["low"]),
                          float(c["close"]), float(c.get("volume") or 0))
                new += 1
        oldest = min(int(c["time"]) for c in rows)
        if new == 0 or oldest <= start:
            break
        cur = oldest - 1                       # step strictly back
        time.sleep(delay)
    if not out:
        return None
    a = np.array([out[k] for k in sorted(out)], dtype=float)
    return pd.DataFrame(a, columns=["ts", "o", "h", "l", "c", "v"])

def job(args):
    sym, res, start, end, outdir = args
    p = os.path.join(outdir, f"{sym}.parquet")
    if os.path.exists(p):
        try:
            d = pd.read_parquet(p)
            if len(d) and d.ts.max() >= end - 7200:      # already current
                return sym, len(d), "skip"
        except Exception:
            pass
    d = fetch_all(sym, res, start, end)
    if d is None or len(d) < 200:
        return sym, 0 if d is None else len(d), "thin"
    d["ts"] = d.ts.astype(np.int64)
    d.to_parquet(p, index=False)
    return sym, len(d), "ok"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="perp_symbols.json")
    ap.add_argument("--resolution", default="1h")
    ap.add_argument("--from-ts", type=int, default=1672531200)   # 2023-01-01
    ap.add_argument("--out", default="data/perp_candles")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    syms = json.load(open(a.symbols))
    os.makedirs(a.out, exist_ok=True)
    end = int(time.time())
    print(f"{len(syms)} symbols | {a.resolution} | "
          f"to {time.strftime('%Y-%m-%d %H:%M', time.gmtime(end))} UTC", flush=True)
    t0 = time.time(); done = ok = thin = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for sym, n, st in ex.map(job, [(s, a.resolution, a.from_ts, end, a.out) for s in syms]):
            done += 1
            if st in ("ok", "skip"): ok += 1
            else: thin += 1
            if done % 20 == 0 or st == "thin":
                el = time.time() - t0
                print(f"  {done}/{len(syms)} | {sym} {n:,} {st} | {el/60:.1f}m "
                      f"| eta {el/done*(len(syms)-done)/60:.1f}m", flush=True)
    print(f"done: {ok} usable, {thin} thin/failed, {(time.time()-t0)/60:.1f}m")
