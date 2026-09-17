#!/usr/bin/env python3
"""
liq_surface.py — the exact leverage/liquidation surface from spot paths.

The question: "with what certainty can I place what size at what leverage so it
is NOT liquidated, and what return in what time?"

Liquidation is arithmetic, not a model. At leverage L with isolated margin, an
adverse move of ~(1/L - mmr) wipes the margin. So for every entry bar we need
the FIRST time price crosses each adverse level, and the FIRST time it crosses
each favourable level. Whichever comes first decides the trade.

Trick that makes this cheap: running min-of-low is monotonically DECREASING and
running max-of-high is monotonically INCREASING as the window extends. So first
crossing time = searchsorted on those running extremes. O(H) to build per bar,
O(log H) per threshold, instead of a scan per (threshold, bar).

No lookahead by construction: everything is forward-looking OUTCOME, and the
features that predict it are computed separately (brooks_spot.parquet).
"""
import json, os, sys, time
import numpy as np, pandas as pd

def load_spot(base, spot, duration="60"):
    d = os.path.join(base, spot, duration); rows = []
    for fn in sorted(os.listdir(d)):
        try: rows.extend(json.load(open(os.path.join(d, fn))))
        except Exception: continue
    a = np.asarray(rows, dtype=float); a = a[np.argsort(a[:, 0])]
    _, k = np.unique(a[:, 0], return_index=True)
    return a[np.sort(k)]

def surface(h, l, c, t, H, adverse, favour, direction):
    """
    For each entry i: first-crossing bar of each adverse/favourable level
    within H bars. Returns (n, len(adverse)) and (n, len(favour)) int arrays,
    H+1 meaning 'never crossed inside the window'.
    direction: +1 long (adverse = down), -1 short (adverse = up)
    """
    n = len(c)
    na, nf = len(adverse), len(favour)
    t_adv = np.full((n, na), H + 1, np.int32)
    t_fav = np.full((n, nf), H + 1, np.int32)
    for i in range(n - 1):
        e = min(n, i + 1 + H)
        if e <= i + 1: continue
        hi = np.maximum.accumulate(h[i + 1:e])      # increasing
        lo = np.minimum.accumulate(l[i + 1:e])      # decreasing
        p = c[i]
        if direction > 0:
            dn = (p - lo) / p                        # increasing adverse excursion
            up = (hi - p) / p                        # increasing favourable
        else:
            dn = (hi - p) / p
            up = (p - lo) / p
        # first index where excursion >= threshold; both arrays are non-decreasing
        t_adv[i] = np.searchsorted(dn, adverse, side="left") + 1
        t_fav[i] = np.searchsorted(up, favour,  side="left") + 1
        t_adv[i][t_adv[i] > len(dn)] = H + 1
        t_fav[i][t_fav[i] > len(up)] = H + 1
    return t_adv, t_fav

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=168)     # hours
    ap.add_argument("--mmr", type=float, default=0.005)     # maintenance margin
    ap.add_argument("--out", default="liq")
    a = ap.parse_args()
    # Decouple path arithmetic from the exchange's margin model: compute a RAW
    # grid of adverse thresholds, then map leverage -> threshold at analysis
    # time. Typical isolated-margin liquidation is at (1 - mm)/L adverse with
    # mm ~ 0.5 of initial margin, i.e. 0.5/L; that mapping is a presentation
    # choice, not something to bake into the scan.
    ADV = np.array([0.0025,0.005,0.01,0.02,0.03,0.05,0.075,0.10,0.15,0.25])
    LEV = 0.5 / ADV
    FAV = np.array([0.005, 0.01, 0.02, 0.03, 0.05, 0.10, 0.20])  # price targets
    os.makedirs(a.out, exist_ok=True)
    print("adverse grid -> implied leverage (liq at 0.5/L):")
    for L, x in zip(LEV, ADV): print(f"   {x*100:>6.3f}% adverse  ~ {L:>6.1f}x")
    print(f"targets: {[f'{x*100:g}%' for x in FAV]}\n")
    for spot in sorted(os.listdir("data/spot_candles")):
        if not os.path.isdir(os.path.join("data/spot_candles", spot)): continue
        t0 = time.time(); arr = load_spot("data/spot_candles", spot)
        o_, h_, l_, c_, t_ = arr[:,1], arr[:,2], arr[:,3], arr[:,4], arr[:,0]
        for d, dn in [(1, "long"), (-1, "short")]:
            ta, tf = surface(h_, l_, c_, t_, a.horizon, ADV, FAV, d)
            df = pd.DataFrame({"ts": t_.astype(np.int64)})
            for j, X in enumerate(ADV): df[f"tadv_{X*100:g}pct"] = ta[:, j]
            for j, F in enumerate(FAV): df[f"tfav_{F*100:g}pct"] = tf[:, j]
            df["spot"] = spot; df["dir"] = dn
            df.to_parquet(f"{a.out}/{spot}_{dn}.parquet", index=False)
        print(f"  {spot}: {len(arr):,} bars, both directions ({time.time()-t0:.1f}s)", flush=True)
    print("done")
