#!/usr/bin/env python3
"""
fetch_traded.py — pull TRADED option candles for the contracts R4+R5 selects.

WHY THIS IS THE DECISIVE STEP
Every number in the context study is computed on MARK prices. processor.js:141
hardcodes a `MARK:` prefix, so a "25x" in the stored data is the exchange's
fair-value estimate touching 25x, not a price anyone paid. The same endpoint
returns real traded OHLCV for the PLAIN symbol. If the edge survives on prints
it is tradeable; if it does not, nothing else in the study matters.

Only the contracts R4+R5 actually selects are fetched — 9,276 of them rather
than the ~119,000 in the full table, which is what makes this affordable now and
was not before.

Paginates backward: /v2/history/candles silently caps a response at ~4000 rows
and does not signal truncation. Resumable — an existing file is skipped.
"""
import os, json, time, argparse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd

BASE = "https://api.india.delta.exchange/v2/history/candles"
OUT  = "data/traded_candles"

def fetch_window(sym, res, a, b, tries=4):
    u = f"{BASE}?symbol={sym}&resolution={res}&start={int(a)}&end={int(b)}"
    for k in range(tries):
        try:
            with urllib.request.urlopen(u, timeout=45) as r:
                return json.load(r).get("result") or []
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(1.5 * (k + 1)); continue
            return []
        except Exception:
            time.sleep(0.5 * (k + 1))
    return []

def one(job):
    spot, exp, sym, t0, t1 = job
    d = os.path.join(OUT, spot, exp); os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, sym + ".json")
    if os.path.exists(fp): return 0
    rows, end = [], t1
    for _ in range(6):                       # page backward past the ~4000 cap
        got = fetch_window(sym, "1h", t0, end)
        if not got: break
        rows.extend(got)
        oldest = min(int(r["time"]) for r in got)
        if oldest <= t0 or len(got) < 3500: break
        end = oldest - 1
    out = sorted({int(r["time"]): [int(r["time"]), r["open"], r["high"],
                                   r["low"], r["close"], r.get("volume", 0)]
                  for r in rows}.values(), key=lambda x: x[0])
    with open(fp, "w") as f: json.dump(out, f)
    return len(out)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    import significance as S
    def trend20(spot):
        arr = S.load_tf_grouped(spot, 1440); ts, c = arr[:, 0], arr[:, 4]
        ret = np.concatenate([np.full(20, np.nan), c[20:] / c[:-20] - 1])
        net = np.abs(np.concatenate([np.full(20, np.nan), c[20:] - c[:-20]]))
        tot = pd.Series(np.abs(np.diff(c, prepend=c[0]))).rolling(20, min_periods=2).sum().to_numpy()
        eff = net / np.maximum(tot, 1e-12)
        return ts, np.where((eff > .35) & (ret > 0), 1,
                     np.where((eff > .35) & (ret < 0), -1, 0)).astype(float)
    jobs = {}
    for sp in ["BTC", "ETH"]:
        d = pd.read_parquet(f"events_ctx2/{sp}.parquet",
             columns=['spot','opt_type','expiry','symbol','entry_ts','activated',
                      'entry_premium','cx240_always_in'])
        d = d[d.activated & d.entry_premium.between(2, 20)]
        ts, lab = trend20(sp)
        j = np.searchsorted(ts + 86400, d.entry_ts.to_numpy(), side="right") - 1
        v = np.full(len(d), np.nan); ok = j >= 0; v[ok] = lab[j[ok]]
        call = (d.opt_type == "C").to_numpy()
        keep = np.where(call, d.cx240_always_in == 1, d.cx240_always_in == -1) & (v != 1)
        for r in d[keep].itertuples():
            k = (sp, r.expiry, r.symbol)
            exp_ts = int(pd.Timestamp(r.expiry).timestamp()) + 12 * 3600
            lo = min(jobs.get(k, (0, 0, 0, 1 << 62, 0))[3], int(r.entry_ts) - 7 * 86400)
            jobs[k] = (sp, r.expiry, r.symbol, lo, exp_ts + 3600)
    jobs = list(jobs.values())
    print(f"contracts to fetch: {len(jobs):,}", flush=True)
    n = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, got in enumerate(ex.map(one, jobs), 1):
            n += got
            if i % 500 == 0: print(f"  {i:,}/{len(jobs):,}  {n:,} bars", flush=True)
    print(f"done: {len(jobs):,} contracts, {n:,} traded bars")
