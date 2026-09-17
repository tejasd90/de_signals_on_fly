#!/usr/bin/env python3
"""
perp_pipeline.py — Brooks features + liquidation surface for every perp.

Reuses brooks_features.build() and liq_surface.surface() unchanged; only the
loader differs (parquet per symbol instead of the daily-JSON spot layout).

Cross-correlation note: adding symbols does NOT add independent TIME periods
(still ~141 weeks), it reduces within-week estimation noise. All significance
testing downstream must therefore still block by time, never by row.
"""
import os, sys, time, argparse
import numpy as np, pandas as pd
sys.path.insert(0, ".")
from brooks_features import build as brooks_build
from liq_surface import surface

ADV = np.array([0.0025,0.005,0.01,0.02,0.03,0.05,0.075,0.10,0.15,0.25])
FAV = np.array([0.005,0.01,0.02,0.03,0.05,0.10,0.20])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-years", type=float, default=1.0)
    ap.add_argument("--horizon", type=int, default=168)
    ap.add_argument("--src", default="data/perp_candles")
    ap.add_argument("--out-bk", default="perp_brooks")
    ap.add_argument("--out-liq", default="perp_liq")
    a = ap.parse_args()
    inv = pd.read_parquet("perp_inventory.parquet")
    syms = inv[inv.years >= a.min_years].sym.tolist()
    os.makedirs(a.out_bk, exist_ok=True); os.makedirs(a.out_liq, exist_ok=True)
    print(f"{len(syms)} symbols with >= {a.min_years}y history", flush=True)
    t0 = time.time()
    for k, s in enumerate(syms, 1):
        pb = f"{a.out_bk}/{s}.parquet"; pl = f"{a.out_liq}/{s}.parquet"
        if os.path.exists(pb) and os.path.exists(pl):
            continue
        d = pd.read_parquet(f"{a.src}/{s}.parquet")
        d = d[(d.c > 0) & (d.h > 0) & (d.l > 0)].sort_values("ts")
        # drop duplicate timestamps and require a clean hourly-ish grid
        d = d.drop_duplicates("ts")
        if len(d) < 3000:
            continue
        o,h,l,c,t = (d.o.to_numpy(), d.h.to_numpy(), d.l.to_numpy(),
                     d.c.to_numpy(), d.ts.to_numpy().astype(float))
        try:
            bk = brooks_build(o, h, l, c, t)
        except Exception as e:
            print(f"  ! {s} brooks failed: {e}", flush=True); continue
        bk.insert(0, "sym", s)
        bk.replace([np.inf,-np.inf], np.nan, inplace=True)
        bk.to_parquet(pb, index=False)
        frames = []
        for dirn, dn in [(1,"long"), (-1,"short")]:
            ta, tf = surface(h, l, c, t, a.horizon, ADV, FAV, dirn)
            f = pd.DataFrame({"ts": t.astype(np.int64)})
            for j,X in enumerate(ADV): f[f"tadv_{X*100:g}pct"] = ta[:,j]
            for j,F in enumerate(FAV): f[f"tfav_{F*100:g}pct"] = tf[:,j]
            idx = np.minimum(np.arange(len(c)) + a.horizon, len(c)-1)
            f["tret"] = c[idx]/c - 1.0
            f["sym"] = s; f["dir"] = dn
            frames.append(f)
        pd.concat(frames, ignore_index=True).to_parquet(pl, index=False)
        if k % 20 == 0:
            el = time.time()-t0
            print(f"  {k}/{len(syms)} | {el/60:.1f}m | eta "
                  f"{el/k*(len(syms)-k)/60:.1f}m", flush=True)
    print(f"done {(time.time()-t0)/60:.1f}m")

if __name__ == "__main__":
    main()
