#!/usr/bin/env python3
"""
fetch_dead.py — the perps that STOPPED trading, for the survivorship fix.

WHY
xsec.py found a cross-sectional low-volatility edge worth 55%/yr, but 137% of it
came from SHORTING high-volatility alt-coins -- and the universe was built from
`fetch_perps.py`, which pulls symbols LIVE on Delta today. Coins that collapsed
and were delisted are absent entirely. That is a survivorship bias sitting
precisely on the profitable leg, so the number cannot be believed until the dead
names are in.

TWO TRAPS, BOTH HANDLED
1. FROZEN TAIL. After delisting the API keeps serving bars at the last price with
   volume=0 and identical OHLC. Those are not trading and must be cut, or every
   dead coin looks like it went perfectly flat instead of disappearing.
2. RENAMES ARE NOT DEATHS. PEPE/SHIB/BONK/FLOKI/MATIC were re-listed as
   1000PEPE/1000SHIB/1000BONK/1000FLOKI/POL. Counting them as failures would be
   wrong AND would double-count against their live successors. Any expired symbol
   whose base asset still trades live is tagged `rename`, not `dead`.
"""
import json, os, time, urllib.request
import numpy as np, pandas as pd

BASE="https://api.india.delta.exchange/v2"
OUT="data/perp_dead"

def get(u):
    with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"x"}),timeout=45) as r:
        return json.load(r)

def products(state):
    return get(f"{BASE}/products?states={state}&contract_types=perpetual_futures&page_size=500")["result"]

def candles(sym, start, end, res="1d"):
    out={}
    e=end
    for _ in range(8):
        d=get(f"{BASE}/history/candles?resolution={res}&symbol={sym}&start={int(start)}&end={int(e)}").get("result") or []
        if not d: break
        for r in d: out[int(r["time"])]=[int(r["time"]),r["open"],r["high"],r["low"],r["close"],r.get("volume",0)]
        oldest=min(int(r["time"]) for r in d)
        if oldest<=start or len(d)<100: break
        e=oldest-1
    a=np.array(sorted(out.values(),key=lambda x:x[0]),dtype=float)
    return a

def trim_frozen(a):
    """Drop the flat zero-volume tail the API serves after delisting."""
    if len(a)==0: return a
    v=a[:,5]; o,h,l,c=a[:,1],a[:,2],a[:,3],a[:,4]
    frozen=(v<=0)&(h==l)&(o==c)
    i=len(a)-1
    while i>=0 and frozen[i]: i-=1
    return a[:i+1]

if __name__=="__main__":
    os.makedirs(OUT,exist_ok=True)
    live={p["symbol"] for p in products("live")}
    live_base={s.replace("1000","").replace("USD","") for s in live}
    exp=products("expired")
    rows=[]
    for p in exp:
        sym=p["symbol"]; base=sym.replace("1000","").replace("USD","")
        kind="rename" if base in live_base else "dead"
        t0=int(time.mktime(time.strptime(p["launch_time"][:10],"%Y-%m-%d"))) if p.get("launch_time") else 1704067200
        a=candles(sym,t0-86400,int(time.time()))
        n_raw=len(a); a=trim_frozen(a)
        if len(a)<30:
            print(f"  {sym:<14} {kind:<7} too short ({len(a)})"); continue
        pd.DataFrame(a,columns=["ts","o","h","l","c","v"]).to_parquet(f"{OUT}/{sym}.parquet",index=False)
        ret=a[-1,4]/a[0,4]-1
        rows.append(dict(sym=sym,kind=kind,bars=len(a),trimmed=n_raw-len(a),
                         first=pd.Timestamp(a[0,0],unit="s").date(),
                         last=pd.Timestamp(a[-1,0],unit="s").date(),
                         total_ret=ret))
        print(f"  {sym:<14} {kind:<7} {len(a):>4} bars (cut {n_raw-len(a):>3} frozen)  "
              f"{pd.Timestamp(a[0,0],unit='s').date()} -> {pd.Timestamp(a[-1,0],unit='s').date()}  "
              f"total {100*ret:>+8.1f}%", flush=True)
    R=pd.DataFrame(rows)
    R.to_csv("perp_dead_manifest.csv",index=False)
    print(f"\nwrote {len(R)} series to {OUT}/")
    for k,g in R.groupby("kind"):
        print(f"  {k:<7} n={len(g):>2}  median total return {100*g.total_ret.median():>+7.1f}%  "
              f"mean {100*g.total_ret.mean():>+7.1f}%")
