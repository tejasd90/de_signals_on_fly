#!/usr/bin/env python3
"""
fetch_oi.py — open interest history, the one Delta data source this project has
never used.

WHY NOW
Two questions failed on candle geometry alone:
  - exhaustion lows ("from where price only goes up") -- every capitulation
    marker was null, and two were anti-predictive
  - real vs fake level breaks -- tightness came out significantly backwards
Both are really questions about POSITIONING, not shape. OI says how much open
risk exists and whether it is being built or unwound, which candles cannot.

The `OI:` prefix on the same candles endpoint returns it (close = OI at the bar
close). Volume is null for these series, as expected.
"""
import json, os, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd

OUT="data/oi"; BASE="https://api.india.delta.exchange/v2/history/candles"

def one(sym, res="1d", start=1704067200):
    fp=f"{OUT}/{sym}.parquet"
    if os.path.exists(fp): return 0
    end=int(time.time()); rows={}
    for _ in range(6):
        u=f"{BASE}?resolution={res}&symbol=OI:{sym}&start={start}&end={end}"
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"x"}),timeout=45) as r:
                d=json.load(r).get("result") or []
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(2); continue
            return 0
        except Exception: time.sleep(1); continue
        if not d: break
        for x in d: rows[int(x["time"])]=[int(x["time"]),x["open"],x["high"],x["low"],x["close"]]
        oldest=min(int(x["time"]) for x in d)
        if oldest<=start or len(d)<100: break
        end=oldest-1
    if len(rows)<100: return 0
    a=np.array(sorted(rows.values(),key=lambda x:x[0]),dtype=float)
    pd.DataFrame(a,columns=["ts","o","h","l","oi"]).to_parquet(fp,index=False)
    return len(a)

if __name__=="__main__":
    os.makedirs(OUT,exist_ok=True)
    syms=[os.path.basename(f)[:-8] for f in sorted(os.listdir("data/perp_candles")) if f.endswith(".parquet")]
    syms=[s for s in syms]
    print(f"fetching OI for {len(syms)} symbols...")
    got=0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n in ex.map(one, syms):
            if n: got+=1
    print(f"wrote {got} OI series to {OUT}/")
