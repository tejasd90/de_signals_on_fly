#!/usr/bin/env python3
"""
build_surfaces.py — the 2-D surface that was never built: STRIKE x EXPIRY.

discover_build.py fits log(premium) vs STRIKE inside a single expiry directory,
so every `surf_` feature is within-expiry. The term-structure axis — how the same
moneyness prices across expiries at one instant — was never crossed.

For each selected event (spot, timestamp) this collects EVERY live option across
ALL expiries and records what it did afterwards. Output feeds a viewer.

Cell value = peak ratio = max(high over forward window) / close at event.
"""
import json,os,glob,sys,time
import numpy as np, pandas as pd

H_FWD = 72   # hours forward

def load_spot_series(spot):
    rows=[]
    for fn in sorted(os.listdir(f"data/spot_candles/{spot}/60")):
        try: rows.extend(json.load(open(f"data/spot_candles/{spot}/60/{fn}")))
        except Exception: pass
    a=np.asarray(rows,float); a=a[np.argsort(a[:,0])]
    _,k=np.unique(a[:,0],return_index=True); return a[np.sort(k)]

def pick_events(spot, n_big=12, n_quiet=6):
    a=load_spot_series(spot); t,c,h,l=a[:,0],a[:,4],a[:,2],a[:,3]
    fwd=np.full(len(c),np.nan)
    for i in range(len(c)-1):
        e=min(len(c),i+1+H_FWD)
        if e>i+1: fwd[i]=h[i+1:e].max()/c[i]-1
    ok=np.isfinite(fwd)
    idx=np.where(ok)[0]
    order=idx[np.argsort(-fwd[idx])]
    big=[]; seen=set()
    for i in order:
        d=int(t[i]//86400)
        if d in seen: continue
        seen.add(d); big.append(i)
        if len(big)>=n_big: break
    mid=idx[np.argsort(np.abs(fwd[idx]-np.median(fwd[idx])))][:n_quiet*40]
    quiet=[]; seen2=set()
    for i in mid:
        d=int(t[i]//86400)
        if d in seen2: continue
        seen2.add(d); quiet.append(i)
        if len(quiet)>=n_quiet: break
    return [(int(t[i]), float(c[i]), float(fwd[i]), "big") for i in big] + \
           [(int(t[i]), float(c[i]), float(fwd[i]), "ordinary") for i in quiet]

def surface_at(spot, ts, spot_px):
    base=f"data/candles/{spot}"
    rows=[]
    for exp in sorted(os.listdir(base)):
        d=os.path.join(base,exp,"60")
        if not os.path.isdir(d): continue
        try: exp_ts=pd.Timestamp(exp).timestamp()+12*3600
        except Exception: continue
        if exp_ts < ts or exp_ts > ts + 45*86400: continue
        for fn in os.listdir(d):
            if not fn.endswith(".json"): continue
            p=fn[:-5].split("-")
            if len(p)<4: continue
            try: strike=float(p[2])
            except ValueError: continue
            try: a=np.asarray(json.load(open(os.path.join(d,fn))),float)
            except Exception: continue
            if a.ndim!=2 or len(a)<2: continue
            j=int(np.searchsorted(a[:,0],ts))
            if j>=len(a) or abs(a[j,0]-ts)>3600: continue
            entry=float(a[j,4])
            if not (entry>0): continue
            e=min(len(a),j+1+H_FWD)
            peak=float(a[j+1:e,2].max())/entry if e>j+1 else np.nan
            rows.append(dict(typ=p[0].upper(),expiry=exp,strike=strike,
                             entry=entry,peak=peak,
                             tte=(exp_ts-ts)/3600.0,
                             mny=(strike-spot_px)/spot_px*100))
    return rows

if __name__=="__main__":
    out=[]
    for spot in ["BTC","ETH"]:
        if not os.path.isdir(f"data/candles/{spot}"): continue
        evs=pick_events(spot)
        print(f"{spot}: {len(evs)} events", flush=True)
        for ts,px,fwd,kind in evs:
            rows=surface_at(spot,ts,px)
            if len(rows)<12: continue
            out.append(dict(spot=spot,ts=ts,
                            when=pd.to_datetime(ts,unit="s").strftime("%Y-%m-%d %H:%M"),
                            spot_px=px, fwd72=fwd, kind=kind, rows=rows))
            print(f"   {pd.to_datetime(ts,unit='s')}  spot {px:,.0f}  "
                  f"fwd72 {fwd*100:+.1f}%  {len(rows)} contracts "
                  f"across {len({r['expiry'] for r in rows})} expiries",flush=True)
    json.dump(out,open("surfaces.json","w"))
    print(f"\nwrote surfaces.json — {len(out)} events")
