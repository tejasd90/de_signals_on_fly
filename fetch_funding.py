#!/usr/bin/env python3
"""
Pull FUNDING: history for every perp. Same endpoint the project already uses --
only the symbol prefix differs, exactly like the MARK: / OI: discovery.

Paginates BACKWARD: a single request silently caps at ~4000 rows, which is the
trap fetch_perps.py hit and which made every symbol look newly listed.
"""
import json, os, time, urllib.request, urllib.error
import numpy as np, pandas as pd

B = "https://api.india.delta.exchange/v2/history/candles"
OUT = "data/funding"; os.makedirs(OUT, exist_ok=True)

def fetch(sym, start, end, tries=4):
    u = f"{B}?resolution=1h&symbol=FUNDING:{sym}&start={start}&end={end}"
    for a in range(tries):
        try:
            with urllib.request.urlopen(u, timeout=30) as r:
                return json.load(r).get("result") or []
        except Exception:
            time.sleep(1.5 * (a + 1))
    return []

def full(sym, years=2.8):
    end = int(time.time()); floor = end - int(years * 365 * 86400)
    rows, cur = [], end
    while cur > floor:
        ch = fetch(sym, cur - 3500 * 3600, cur)
        if not ch: break
        rows.extend(ch)
        t0 = min(r["time"] for r in ch)
        if t0 >= cur: break
        cur = t0 - 3600
        time.sleep(0.05)
    if not rows: return None
    d = pd.DataFrame(rows).drop_duplicates("time").sort_values("time")
    return d[["time", "close"]].rename(columns={"time": "ts", "close": "rate"})

inv = pd.read_parquet("perp_inventory.parquet")
syms = inv.sym.tolist()
print(f"{len(syms)} perps", flush=True)
t0 = time.time(); ok = 0
for i, s in enumerate(syms, 1):
    p = f"{OUT}/{s}.parquet"
    if os.path.exists(p): ok += 1; continue
    d = full(s)
    if d is None or len(d) < 200: 
        print(f"  ! {s}: {0 if d is None else len(d)} rows", flush=True); continue
    d.to_parquet(p, index=False); ok += 1
    if i % 20 == 0:
        el = time.time() - t0
        print(f"  {i}/{len(syms)}  {el/60:.1f}m  eta {el/i*(len(syms)-i)/60:.1f}m", flush=True)
print(f"done: {ok} symbols in {(time.time()-t0)/60:.1f}m")
