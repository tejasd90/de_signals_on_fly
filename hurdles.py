"""HURDLES (Tejas, 2026-10-07): a peak made by a sharp move that reaches prices not traded for a
while, followed by a usually even sharper reversal -- a quick touch. Used three ways:
  support/resistance from price action; where to book out of a trap; a target for options.
Re-entry rule: price going BEYOND the hurdle.

Rule (high hurdles; low hurdles are the mirror), on one timeframe:
  peak     bar i is the highest high within +-K bars                       (local extreme)
  exposed  high[i] above every high of the previous EXPOSE_H hours          (prices long untouched)
  sharp up rise into the peak over <= M bars >= UP_ATR x ATR
  sharper  drop within M bars after the peak >= DOWN_RATIO x that rise       (the reversal)
  quick    bars with a high within TOUCH_ATR of the peak <= MAX_TOUCH       (a touch, not a top)
Relaxed variant: DOWN_RATIO 0.7, MAX_TOUCH 3, EXPOSE_H 24.
"""
import json, glob, os, sys, numpy as np, pandas as pd

def load(asset, res):
    rows = []
    for f in sorted(glob.glob(f"data/spot_candles/{asset}/{res}/*")):
        if os.path.basename(f).startswith("."): continue
        rows += json.load(open(f))
    return pd.DataFrame([r[:5] for r in rows], columns=["t", "o", "h", "l", "c"]).drop_duplicates("t").sort_values("t").reset_index(drop=True)

def atr(d, n=14):
    pc = d.c.shift(1)
    tr = np.maximum(d.h - d.l, np.maximum((d.h - pc).abs(), (d.l - pc).abs()))
    return tr.rolling(n, min_periods=3).mean()

def hurdles(d, res, K=4, EXPOSE_H=72, M=8, UP_ATR=2.0, DOWN_RATIO=1.0, TOUCH_ATR=0.25, MAX_TOUCH=2):
    """Each hurdle is known only after its reversal completes: `known_t` = close of bar i+M."""
    A = atr(d).to_numpy(); h, l = d.h.to_numpy(), d.l.to_numpy(); n = len(d)
    E = max(1, int(EXPOSE_H * 60 / int(res))); step = int(res) * 60; out = []
    for side, x, y, sgn in (("HIGH", h, l, 1), ("LOW", l, h, -1)):
        for i in range(max(K, E, M), n - M):
            a = A[i]
            if not np.isfinite(a) or a <= 0: continue
            win = x[i-K:i+K+1]
            if (sgn == 1 and x[i] < win.max()) or (sgn == -1 and x[i] > win.min()): continue
            prev = x[i-E:i]
            if (sgn == 1 and x[i] <= prev.max()) or (sgn == -1 and x[i] >= prev.min()): continue
            start = y[i-M:i].min() if sgn == 1 else y[i-M:i].max()
            rise = sgn * (x[i] - start)
            after = y[i+1:i+M+1].min() if sgn == 1 else y[i+1:i+M+1].max()
            drop = sgn * (x[i] - after)
            if rise < UP_ATR * a or drop < DOWN_RATIO * rise: continue
            touch = int((np.abs(x[i-M:i+M+1] - x[i]) <= TOUCH_ATR * a).sum())
            if touch > MAX_TOUCH: continue
            out.append(dict(side=side, i=i, t=int(d.t[i]), known_t=int(d.t[i+M]) + step, price=float(x[i]),
                            rise_atr=rise/a, drop_atr=drop/a, touch=touch))
    return pd.DataFrame(out)

if __name__ == "__main__":
    asset = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    for res, kw in (("15", {}), ("5", dict(K=6, M=12, EXPOSE_H=24))):
        d = load(asset, res)
        d = d[d.t >= pd.Timestamp("2026-09-28").timestamp()].reset_index(drop=True)
        for lab, extra in (("strict", {}), ("relaxed", dict(DOWN_RATIO=0.7, MAX_TOUCH=3, EXPOSE_H=24))):
            H = hurdles(d, res, **{**kw, **extra})
            if not len(H): print(f"{asset} {res}m {lab}: none"); continue
            H["ist"] = pd.to_datetime(H.t, unit="s") + pd.Timedelta(hours=5.5)
            print(f"\n{asset} {res}m {lab}: {len(H)} hurdles since 28 Sep")
            print(H[["ist", "side", "price", "rise_atr", "drop_atr", "touch"]].round(1).to_string(index=False))
