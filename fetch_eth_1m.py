#!/usr/bin/env python3
"""
fetch_eth_1m.py — 1-minute ETHUSD perp candles for the whole history.

1m is the finest resolution the API serves for a period this long (seconds data
exists only recently). /v2/history/candles caps a response at ~4000 rows and does
NOT signal truncation, so at 1m that is 2.8 days per request — page backward.

Resumable: re-running only fetches what is missing.
"""
import json, os, time, urllib.request, urllib.error
import numpy as np, pandas as pd

OUT="data/eth_1m.parquet"
BASE="https://api.india.delta.exchange/v2/history/candles"

def win(a,b,tries=4):
    u=f"{BASE}?symbol=ETHUSD&resolution=1m&start={int(a)}&end={int(b)}"
    for k in range(tries):
        try:
            with urllib.request.urlopen(u,timeout=45) as r:
                return json.load(r).get("result") or []
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(1.5*(k+1)); continue
            return []
        except Exception: time.sleep(0.5*(k+1))
    return []

if __name__=="__main__":
    h=pd.read_parquet("data/perp_candles/ETHUSD.parquet")
    t0,t1=int(h.ts.min()), int(h.ts.max())+3600
    have={}
    if os.path.exists(OUT):
        old=pd.read_parquet(OUT)
        have={int(r.ts):[int(r.ts),r.o,r.h,r.l,r.c,r.v] for r in old.itertuples()}
        print(f"resuming with {len(have):,} bars")
    end=t1; n=0
    while end>t0:
        got=win(max(t0,end-4000*60), end)
        if not got: end-=4000*60; continue
        for r in got:
            have[int(r["time"])]=[int(r["time"]),r["open"],r["high"],r["low"],r["close"],r.get("volume",0)]
        oldest=min(int(r["time"]) for r in got)
        n+=1
        if n%40==0: print(f"  {len(have):,} bars, back to {pd.Timestamp(oldest,unit='s').date()}",flush=True)
        if oldest<=t0: break
        end=oldest-1
    a=np.array(sorted(have.values(),key=lambda x:x[0]),dtype=float)
    pd.DataFrame(a,columns=["ts","o","h","l","c","v"]).to_parquet(OUT,index=False)
    print(f"\nwrote {OUT}: {len(a):,} bars  "
          f"{pd.Timestamp(a[0,0],unit='s').date()} -> {pd.Timestamp(a[-1,0],unit='s').date()}")
