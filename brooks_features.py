#!/usr/bin/env python3
"""
brooks_features.py — arm 4. Mechanical spot features from Al Brooks' framework.

Spec: BROOKS_FEATURES.md. Design rule D-41: Brooks supplies the STRUCTURE, the
model supplies the THRESHOLDS. Nothing here is a hand-tuned trigger — every
output is a continuous number or a count.

Purpose (2026-09-10): the option-chain model ranks strikes at AUC 0.947 but
ranks MOMENTS at 0.574. Timing information, if it exists, lives on the spot
side, which is currently 70 thin shape columns. This builds the ~100 spot
features that have been specified since ML_SPEC v0.4 and never implemented.

NO LOOKAHEAD. Every feature at bar i uses bars <= i only. Swing points are a
trap here: a swing high at j is only KNOWN at j+1, so swings are only consulted
for j <= i-1. ATR is trailing. All distances are in ATR units so the features
transfer across BTC/ETH/XAUT and later to equities (D-19).
"""
import json, os, sys, time
import numpy as np, pandas as pd

LOOKBACKS = (5, 10, 20, 50)

def load_spot(base, spot, duration="60"):
    d = os.path.join(base, spot, duration)
    rows = []
    for fn in sorted(os.listdir(d)):
        try:
            rows.extend(json.load(open(os.path.join(d, fn))))
        except Exception:
            continue
    a = np.asarray(rows, dtype=float)
    a = a[np.argsort(a[:, 0])]
    _, keep = np.unique(a[:, 0], return_index=True)
    return a[np.sort(keep)]

def atr(h, l, c, n):
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = pd.Series(tr).rolling(n, min_periods=2).mean().to_numpy()
    return out

def swings(h, l):
    """swing high/low index masks. Known only one bar later — caller must lag."""
    n = len(h)
    sh = np.zeros(n, bool); sl = np.zeros(n, bool)
    sh[1:-1] = (h[1:-1] >= h[:-2]) & (h[1:-1] >= h[2:])
    sl[1:-1] = (l[1:-1] <= l[:-2]) & (l[1:-1] <= l[2:])
    return sh, sl

def build(o, h, l, c, t):
    n = len(c)
    F = {}
    a14 = atr(h, l, c, 14); a50 = atr(h, l, c, 50)
    a14s = np.where(a14 > 0, a14, np.nan)
    rng = h - l
    rngs = np.where(rng > 0, rng, np.nan)
    body = c - o
    # ---- 1. bar level, last 5 bars -------------------------------------
    for k in range(1, 6):
        sh_ = lambda x: np.concatenate([np.full(k - 1, np.nan), x[:n - k + 1]])
        F[f"bk_bodyfrac_{k}"]  = sh_(np.abs(body) / rngs)
        F[f"bk_dir_{k}"]       = sh_(np.sign(body))
        F[f"bk_utail_{k}"]     = sh_((h - np.maximum(o, c)) / rngs)
        F[f"bk_ltail_{k}"]     = sh_((np.minimum(o, c) - l) / rngs)
        F[f"bk_closepos_{k}"]  = sh_((c - l) / rngs)
        F[f"bk_barsize_{k}"]   = sh_(rng / a14s)
    # ---- 2. bar to bar --------------------------------------------------
    ph, pl = np.concatenate([[np.nan], h[:-1]]), np.concatenate([[np.nan], l[:-1]])
    po, pc = np.concatenate([[np.nan], o[:-1]]), np.concatenate([[np.nan], c[:-1]])
    inside = (h <= ph) & (l >= pl)
    outside = (h >= ph) & (l <= pl)
    F["bk_inside"] = inside.astype(float)
    F["bk_outside"] = outside.astype(float)
    F["bk_insidedepth"] = ((ph - pl) - rng) / np.where((ph - pl) > 0, ph - pl, np.nan)
    F["bk_inside_body"] = ((np.maximum(o, c) <= np.maximum(po, pc)) &
                           (np.minimum(o, c) >= np.minimum(po, pc))).astype(float)
    run = np.zeros(n)
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if inside[i] else 0
    F["bk_inside_run"] = run                     # ii / iii as a count
    F["bk_gap_up"] = np.maximum(0, (l - ph)) / a14s
    F["bk_gap_dn"] = np.maximum(0, (pl - h)) / a14s
    ov = (np.minimum(h, ph) - np.maximum(l, pl))
    F["bk_overlap"] = np.clip(ov, 0, None) / rngs
    F["bk_pullback_up"] = (l < pl).astype(float)
    F["bk_pullback_dn"] = (h > ph).astype(float)
    # ---- 3. swing structure (lagged: swing at j known at j+1) ----------
    sh, sl = swings(h, l)
    bs_h = np.full(n, np.nan); bs_l = np.full(n, np.nan)
    d_h = np.full(n, np.nan); d_l = np.full(n, np.nan)
    push_up = np.zeros(n); push_dn = np.zeros(n)
    hh = np.full(n, np.nan); hl = np.full(n, np.nan)
    stair = np.full(n, np.nan)
    last_h, last_l = [], []
    for i in range(n):
        j = i - 1                                   # swings are known one bar late
        if j >= 1 and sh[j]:
            last_h.append(j)
        if j >= 1 and sl[j]:
            last_l.append(j)
        if last_h:
            bs_h[i] = i - last_h[-1]; d_h[i] = (h[last_h[-1]] - c[i]) / (a14s[i] or np.nan)
        if last_l:
            bs_l[i] = i - last_l[-1]; d_l[i] = (c[i] - l[last_l[-1]]) / (a14s[i] or np.nan)
        if len(last_h) >= 2:
            hh[i] = 1.0 if h[last_h[-1]] > h[last_h[-2]] else 0.0
        if len(last_l) >= 2:
            hl[i] = 1.0 if l[last_l[-1]] > l[last_l[-2]] else 0.0
        # three pushes + shrinking stairs (ratio of last breakout to prior)
        if len(last_h) >= 3:
            e = [h[k] for k in last_h[-3:]]
            if e[1] > e[0] and e[2] > e[1]:
                push_up[i] = 3
                b1, b2 = e[1] - e[0], e[2] - e[1]
                stair[i] = b2 / b1 if b1 > 0 else np.nan
        if len(last_l) >= 3:
            e = [l[k] for k in last_l[-3:]]
            if e[1] < e[0] and e[2] < e[1]:
                push_dn[i] = 3
                b1, b2 = e[0] - e[1], e[1] - e[2]
                if not np.isfinite(stair[i]):
                    stair[i] = b2 / b1 if b1 > 0 else np.nan
    F["bk_bars_since_sh"] = bs_h; F["bk_bars_since_sl"] = bs_l
    F["bk_dist_sh_atr"] = d_h;   F["bk_dist_sl_atr"] = d_l
    F["bk_higher_high"] = hh;    F["bk_higher_low"] = hl
    F["bk_push_up"] = push_up;   F["bk_push_dn"] = push_dn
    F["bk_stair_ratio"] = stair                    # direct analogue of ratio1
    # ---- 4. trend vs range, per lookback --------------------------------
    cs = pd.Series(c)
    for L in LOOKBACKS:
        hi = pd.Series(h).rolling(L, min_periods=2).max().to_numpy()
        lo = pd.Series(l).rolling(L, min_periods=2).min().to_numpy()
        span = np.where((hi - lo) > 0, hi - lo, np.nan)
        F[f"bk_rangepos_{L}"] = (c - lo) / span
        F[f"bk_width_atr_{L}"] = (hi - lo) / a14s
        net = np.abs(c - cs.shift(L).to_numpy())
        path = pd.Series(np.abs(np.diff(c, prepend=c[0]))).rolling(L, min_periods=2).sum().to_numpy()
        F[f"bk_efficiency_{L}"] = net / np.where(path > 0, path, np.nan)
        F[f"bk_overlap_mean_{L}"] = pd.Series(F["bk_overlap"]).rolling(L, min_periods=2).mean().to_numpy()
        F[f"bk_bodyfrac_mean_{L}"] = pd.Series(np.abs(body) / rngs).rolling(L, min_periods=2).mean().to_numpy()
        F[f"bk_bodyfrac_max_{L}"] = pd.Series(np.abs(body) / rngs).rolling(L, min_periods=2).max().to_numpy()
        F[f"bk_inside_cnt_{L}"] = pd.Series(inside.astype(float)).rolling(L, min_periods=2).sum().to_numpy()
        F[f"bk_ret_atr_{L}"] = (c - cs.shift(L).to_numpy()) / a14s
        F[f"bk_vol_{L}"] = pd.Series(np.diff(np.log(np.maximum(c, 1e-9)), prepend=0.0)).rolling(L, min_periods=2).std().to_numpy()
        # breakout magnitude beyond the L-bar extreme, in ATR units
        F[f"bk_brk_up_{L}"] = (h - pd.Series(h).shift(1).rolling(L, min_periods=2).max().to_numpy()) / a14s
        F[f"bk_brk_dn_{L}"] = (pd.Series(l).shift(1).rolling(L, min_periods=2).min().to_numpy() - l) / a14s
        # channel tightness: gap between fitted high and low lines, ATR units
        F[f"bk_chan_{L}"] = (pd.Series(h).rolling(L, min_periods=2).std().to_numpy()
                             + pd.Series(l).rolling(L, min_periods=2).std().to_numpy()) / a14s
    # trending closes: signed run length
    tc = np.zeros(n)
    for i in range(1, n):
        if c[i] > c[i - 1]:
            tc[i] = tc[i - 1] + 1 if tc[i - 1] > 0 else 1
        elif c[i] < c[i - 1]:
            tc[i] = tc[i - 1] - 1 if tc[i - 1] < 0 else -1
    F["bk_trending_closes"] = tc
    # ---- 5. regime / climax ---------------------------------------------
    F["bk_atr_ratio"] = a14 / np.where(a50 > 0, a50, np.nan)
    F["bk_barsize_accel"] = rng / np.where(
        pd.Series(rng).shift(1).rolling(5, min_periods=2).mean().to_numpy() > 0,
        pd.Series(rng).shift(1).rolling(5, min_periods=2).mean().to_numpy(), np.nan)
    ma_f = cs.rolling(10, min_periods=2).mean().to_numpy()
    ma_s = cs.rolling(50, min_periods=2).mean().to_numpy()
    F["bk_ma_spread_atr"] = (ma_f - ma_s) / a14s
    F["bk_ma_spread_chg"] = np.concatenate([[np.nan], np.diff(F["bk_ma_spread_atr"])])
    F["bk_vol_rank"] = pd.Series(F["bk_vol_20"]).rolling(200, min_periods=20).rank(pct=True).to_numpy()
    F["bk_autocorr_20"] = pd.Series(np.diff(np.log(np.maximum(c, 1e-9)), prepend=0.0)) \
        .rolling(20, min_periods=5).apply(lambda x: pd.Series(x).autocorr(1), raw=False).to_numpy()
    # time since a large move (regime memory / breakout fatigue)
    big = (np.abs(body) / a14s) > 1.5
    since = np.full(n, np.nan); last = -1
    for i in range(n):
        if big[i]: last = i
        since[i] = i - last if last >= 0 else np.nan
    F["bk_since_big_move"] = since
    df = pd.DataFrame(F)
    df.insert(0, "ts", t.astype(np.int64))
    return df

if __name__ == "__main__":
    base = "data/spot_candles"
    out = []
    for spot in sorted(os.listdir(base)):
        if not os.path.isdir(os.path.join(base, spot)):
            continue
        t0 = time.time()
        a = load_spot(base, spot)
        d = build(a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 0])
        d.insert(0, "spot", spot)
        out.append(d)
        print(f"  {spot}: {len(a):,} bars -> {d.shape[1]-2} features "
              f"({time.time()-t0:.1f}s)", flush=True)
    df = pd.concat(out, ignore_index=True)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.to_parquet("brooks_spot.parquet", index=False)
    print(f"wrote brooks_spot.parquet  {df.shape[0]:,} rows x {df.shape[1]-2} features")
