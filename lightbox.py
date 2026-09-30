"""Price action as light in a box.

His model: the market sits in a closed box. Light is emitted from the left (the
past) travelling right (towards now). Every candle BODY absorbs a fraction of what
passes through it. How much light reaches today's body?

Why this is better posed than the weighted-hit-count it superficially resembles:

  RECENCY IS FREE. pascore needed an invented weight function -- harmonic, log,
  power, exponential -- four arbitrary choices that became a forking path. Here, a
  bar three days ago that blocks a level makes bars from 200 days ago at that level
  contribute nothing further. Recency falls out of the geometry.

  BODIES, NOT WICKS, is load-bearing. A rejection leaves the wick at the extreme
  and the body back inside the range, so the body stays in shadow. "A rejection is
  not a breakout" is a consequence of the model, not a rule bolted onto it.

  ANGLES UNIFY LEVELS AND TRENDLINES. A horizontal ray measures a horizontal
  level. A sloped ray is a line of sight along a trendline. Same mechanism.

## The maths

Work in LOG price so a slope is a constant % per bar and is scale-free. Discretise
log price into cells. Body of bar j occupies cells B[j,:] between its open and close.

For a ray of slope s arriving at bar i, cell k, the bars it has passed through are
those j < i occupying cell k - s*(i-j). Substituting k' = k - s*i turns this into a
plain cumulative sum in SHEARED coordinates:

    C_s[j, k'] = B[j, k' + s*j]          (shear each row by s*j)
    N_s[i, k'] = sum_{j<i} C_s[j, k']    (cumulative count along the ray)
    T_s[i, k'] = (1 - alpha) ** N_s      (Beer-Lambert attenuation)

Light on bar i's body = mean of T over the cells its body occupies. STRICTLY j < i,
so nothing from bar i or later enters its own score.

Reflection is deliberately omitted in v1: multiple scattering is a linear system
(radiosity) with its own parameters, and it should only be paid for if pure
absorption earns it first.

alpha is the one real free parameter and is swept over his own candidates.
"""
import numpy as np, pandas as pd
from levels import load_tf

CELL   = 0.0025                      # log-price grid, 0.25% per cell
SLOPES = (-0.004, -0.002, -0.001, 0.0, 0.001, 0.002, 0.004)   # log-price per bar
ALPHAS = (0.001, 0.01, 0.10, 0.50)   # his candidates: 0.1%, 1%, 10%, 50%

def bodies(o, c, lo_edge):
    """cell index range of each candle BODY (not the wick)."""
    a = np.log(np.minimum(o, c)); b = np.log(np.maximum(o, c))
    k0 = np.floor((a - lo_edge) / CELL).astype(int)
    k1 = np.floor((b - lo_edge) / CELL).astype(int)
    return k0, np.maximum(k1, k0)

def light(arr, alpha, slopes=SLOPES):
    """Light reaching each bar's body, per slope. Row i uses bars j<i only."""
    o, h, l, c = arr[:,1], arr[:,2], arr[:,3], arr[:,4]
    n = len(c)
    lo_edge = np.log(l.min()) - 0.5
    hi_edge = np.log(h.max()) + 0.5              # the "box": padded above and below
    K = int((hi_edge - lo_edge) / CELL) + 1
    k0, k1 = bodies(o, c, lo_edge)

    B = np.zeros((n, K), np.float32)
    for j in range(n):
        B[j, k0[j]:k1[j]+1] = 1.0

    out = np.full((n, len(slopes)), np.nan, np.float32)
    PAD = K                                        # room for the shear
    for si, s in enumerate(slopes):
        shift = np.round(np.arange(n) * s / CELL).astype(int)
        C = np.zeros((n, K + 2*PAD), np.float32)
        for j in range(n):                         # shear row j by s*j
            a = k0[j] + PAD - shift[j]; b = k1[j] + PAD - shift[j]
            if 0 <= a and b < K + 2*PAD: C[j, a:b+1] = 1.0
        # cumulative count STRICTLY before i
        N = np.cumsum(C, axis=0) - C
        T = (1.0 - alpha) ** N
        for i in range(n):
            a = k0[i] + PAD - shift[i]; b = k1[i] + PAD - shift[i]
            if 0 <= a and b < K + 2*PAD:
                out[i, si] = T[i, a:b+1].mean()
    return out

def features(spot, tf=1440):
    arr = load_tf(spot, tf)
    if arr is None: return None
    day = pd.to_datetime(arr[:,0], unit="s").normalize()
    cols = {}
    for al in ALPHAS:
        L = light(arr, al)
        tag = f"a{al}"
        cols[f"lx_mean|{tag}"] = np.nanmean(L, axis=1)      # light over all angles
        cols[f"lx_flat|{tag}"] = L[:, SLOPES.index(0.0)]    # horizontal only = levels
        cols[f"lx_max|{tag}"]  = np.nanmax(L, axis=1)       # best-lit sight line
        cols[f"lx_rng|{tag}"]  = np.nanmax(L,axis=1) - np.nanmin(L,axis=1)  # angular spread
        # which slope is brightest: the dominant trendline direction
        cols[f"lx_arg|{tag}"]  = np.array(SLOPES)[np.nanargmax(np.nan_to_num(L,nan=-1),axis=1)]
    d = pd.DataFrame(cols); d["day"] = day; d["spot"] = spot
    g = d.groupby(["spot","day"]).last().reset_index()
    # SHIFT: everything must be known BEFORE the day it is asked about.
    fc = [c for c in g.columns if c.startswith("lx_")]
    g[fc] = g.groupby("spot")[fc].shift(1)
    return g

if __name__ == "__main__":
    F = pd.concat([features(s) for s in ("BTC","ETH")])
    F.to_parquet("data/lightbox.parquet")
    print(F.shape, "->", "data/lightbox.parquet")
    print(F[[c for c in F.columns if c.startswith('lx_')]].describe().T[["mean","std","min","max"]].to_string())
