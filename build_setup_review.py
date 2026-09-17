#!/usr/bin/env python3
"""
build_setup_review.py — one review sheet per expiry.

Inverts the grid viewers. Those start from a SIGNAL and show context; this starts
from a price-action SETUP and shows what happened next, plus any option signals
that fired near it. Far fewer rows than the signal grids, so a whole expiry can
be read at a glance.

Per setup:
  what it is        Brooks' name, direction, timeframe
  what is expected  his claim, and the MEASURED win rate from the 220-perp study
  what spot did     target before stop, max favourable excursion in R units
  what signals did  option firings within a few bars, and the best multiple reached

  data/setup_review/{spot}/{expiry}.json
"""
import os, json, glob
import numpy as np, pandas as pd
import brooks_setups as B

OUT = "data/setup_review"
LIFE_DAYS = 30            # a setup belongs to every expiry alive within this window
LAG = 3                   # signal must fire within +-3 setup-bars
HORIZON = 40

# measured win rates from brooks_perps.parquet, so the sheet states what is
# expected rather than only what Brooks claims
MEASURED = {}
try:
    _m = pd.read_parquet("brooks_perps.parquet")
    for (nm, tf), g in _m.groupby(["setup", "tf"]):
        if len(g) >= 200: MEASURED[(nm, int(tf))] = round(100 * g.win.mean(), 1)
except Exception: pass

EXPECT = {
 "H2 pullback in bull trend":        "second entry with the trend; Brooks expects continuation up",
 "L2 pullback in bear trend":        "second entry with the trend; expects continuation down",
 "failed breakout of range high":    "breakout failed; expects a move back to the range low",
 "failed breakout of range low":     "breakout failed; expects a move back to the range high",
 "strong breakout up":               "big body, small tail; expects follow-through and a measured move",
 "strong breakout down":             "big body, small tail; expects follow-through down",
 "countertrend short in bull trend": "fade against the trend; Brooks says beginners lose 70%+ of these",
 "countertrend long in bear trend":  "fade against the trend; Brooks says beginners lose 70%+ of these",
 "always-in flips UP":               "always-in flipped long; Brooks implies ~60% for an equidistant move",
 "always-in flips DOWN":             "always-in flipped short; ~60% for an equidistant move",
}

def signals_for(spot, expiry):
    """Every option firing on this expiry at >=30m, flattened."""
    out = []
    base = "data/signals"
    for sig in sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))):
        p = os.path.join(base, sig, spot)
        if not os.path.isdir(p): continue
        for dur in sorted(int(x) for x in os.listdir(p) if x.isdigit() and int(x) >= 30):
            fp = os.path.join(p, str(dur), f"{expiry}.json")
            if not os.path.exists(fp): continue
            try: data = json.load(open(fp))
            except Exception: continue
            for ty in ("C", "P"):
                for r in (data.get(ty) or []):
                    try:
                        ts = pd.Timestamp(r[1][:19]).timestamp() - 19800
                    except Exception: continue
                    out.append(dict(ts=ts, iso=r[1], signal=sig, dur=dur, ty=ty,
                                    n=int(r[2] or 0), ratio=float(r[4] or 0),
                                    syms=(r[6] or [])[:3], state=r[5] or ""))
    return out

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for spot in ["BTC", "ETH"]:
        exps = sorted(d for d in os.listdir(f"data/candles/{spot}") if not d.startswith("."))
        # spot setups once per timeframe
        pool = []
        for tf in (240, 1440):
            a = B.load(spot, tf)
            if a is None: continue
            su, h, l, ts = B.setups(a, tf)
            for (i, name, longs, entry, stop) in su:
                R = abs(entry - stop)
                if not (R > 0): continue
                tgt = entry + R if longs else entry - R
                w = B.first_crossing(h, l, i, entry, tgt, stop, longs, HORIZON)
                end = min(len(h), i + 1 + HORIZON)
                mfe = 0.0
                for k in range(i + 1, end):
                    mfe = max(mfe, ((h[k]-entry) if longs else (entry-l[k]))/R)
                pool.append(dict(ts=float(ts[i]), tf=tf, name=name,
                                 dir="long" if longs else "short",
                                 entry=round(float(entry),4), stop=round(float(stop),4),
                                 target=round(float(tgt),4),
                                 result={1:"target",0:"stopped"}.get(w,"unresolved"),
                                 mfe_R=round(float(mfe),2),
                                 measured=MEASURED.get((name,tf)),
                                 expect=EXPECT.get(name,"")))
        pool.sort(key=lambda r: r["ts"])
        pts = np.array([r["ts"] for r in pool])
        os.makedirs(os.path.join(OUT, spot), exist_ok=True)
        written = 0
        for exp in exps:
            try: exp_ts = pd.Timestamp(exp).timestamp() + 12*3600
            except Exception: continue
            lo = exp_ts - LIFE_DAYS*86400
            idx = np.where((pts >= lo) & (pts <= exp_ts))[0]
            if not len(idx): continue
            sigs = signals_for(spot, exp)
            rows = []
            for i in idx:
                s = dict(pool[i]); bar = s["tf"]*60
                near = [g for g in sigs
                        if abs(g["ts"] - s["ts"]) <= LAG*bar
                        and ((s["dir"]=="long" and g["ty"]=="C") or (s["dir"]=="short" and g["ty"]=="P"))]
                near.sort(key=lambda g: -g["ratio"])
                s["signals"] = [dict(signal=g["signal"], dur=g["dur"], ty=g["ty"],
                                     ratio=round(g["ratio"],2), syms=g["syms"],
                                     lag=round((g["ts"]-s["ts"])/bar,1), iso=g["iso"])
                                for g in near[:6]]
                s["best_ratio"] = round(max([g["ratio"] for g in near], default=0.0), 2)
                s["n_signals"] = len(near)
                rows.append(s)
            json.dump({"spot":spot,"expiry":exp,"setups":rows},
                      open(os.path.join(OUT, spot, f"{exp}.json"), "w"), separators=(",",":"))
            written += 1
        print(f"  {spot}: {written} expiry files, {len(pool):,} setups in the pool", flush=True)
    print(f"\nwrote {OUT}")
