"""Is width_atr measuring the APEX, or just ATR?

apex.py showed +33.3pp on BTC (P=0.995) and -3.2pp on ETH -- opposite signs, so
the split is noise. But the scale-free version (bars_to_apex) was null on BTC too,
which points at a specific culprit: width_atr = gap / ATR, so "narrow" fires both
when the lines nearly met AND when ATR is simply large. Large ATR means a volatile
regime, and volatile regimes produce more 100x events for reasons that have
nothing to do with wedge geometry.

If that is right, width_atr should correlate with ATR far more than with the
geometric bars-to-apex.
"""
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from wedge import active_lines, find_wedges

for spot in ("BTC", "ETH"):
    rows = []
    for tf in (1440, 360, 240):
        conf, arr, A = active_lines(spot, tf)
        if arr is None: continue
        for w in find_wedges(spot, tf):
            bi, span, gl, gh = w["break_i"], w["span"], w["gap_lo"], w["gap_hi"]
            rate = (gl - gh) / span if span > 0 else np.nan
            b2a = gh / rate if (rate and rate > 0) else np.nan
            px = arr[bi] if np.ndim(arr) == 1 else np.nan
            rows.append((w["width_atr"], b2a, A[bi], A[bi] / px if px else np.nan))
    d = pd.DataFrame(rows, columns=["width_atr", "bars_to_apex", "atr", "atr_pct"]).dropna(subset=["width_atr"])
    if len(d) < 20: print(f"{spot}: too few"); continue
    r1 = spearmanr(d.width_atr, d.atr, nan_policy="omit")
    d2 = d.dropna(subset=["bars_to_apex"])
    r2 = spearmanr(d2.width_atr, d2.bars_to_apex) if len(d2) > 10 else (np.nan, np.nan)
    print(f"{spot}: n={len(d)}")
    print(f"  spearman(width_atr, ATR)          = {r1.statistic:+.3f}  p={r1.pvalue:.4f}")
    print(f"  spearman(width_atr, bars_to_apex) = {r2[0]:+.3f}  p={r2[1]:.4f}   n={len(d2)}")
