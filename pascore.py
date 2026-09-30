"""
Reducing price action at a bar to a single number.

His idea, in four parts:
  1. draw a horizontal line at the current price; count the past bars it hits,
     weighting recent bars more (harmonic / log / polynomial to be decided);
  2. allow tolerance that GROWS with age, so a slightly sloped line still catches
     a range from seven months ago that a perfectly flat line would miss;
  3. after a breakout the nearest hit is far back in time -- so multiply by some
     function of that distance;
  4. fold in how the current bar sits against the last few: a run of small,
     barely-overlapping bars each taking out the prior extreme means something.

Two changes to his spec, both preserving the intent:

  NORMALISE the hit sum. A raw sum scales with how much history exists and how
  volatile the era was. Dividing by the total weight of the lookback turns it into
  "what fraction of the weighted past does this price touch" -- bounded, and
  comparable across assets and epochs.

  TOLERANCE AS DRIFT, NOT DEGREES. A 1-degree slope is ~0.0175 price-units per
  bar; over 200 bars that is 3.5x price and every level hits everything. Same idea
  expressed safely: tau(age) = ATR * (TOL0 + DRIFT*age), with DRIFT in ATR/bar.
  Equivalent to "some line within +/- theta hits it", but it cannot explode.

Added here, beyond his four:

  DISPERSION -- and I think it matters more than the recency weight. Twenty
  touches inside one week is a RANGE, which is weak. Five touches across three
  separate epochs is a level the market keeps rediscovering, which is strong. Pure
  recency weighting scores the tight recent range higher, which is backwards.
  Counts distinct time-CLUSTERS, not raw bars.

  REJECTION MAGNITUDE -- three 2-ATR reversals is not the same object as three
  0.2-ATR grazes. levels.py counts touches and throws this away.

  SIDE ASYMMETRY -- touched only from below is resistance; from both sides is a
  pivot. Different objects.

  ROUND NUMBERS -- 80,000 on BTC.

PROTOCOL, fixed before any result is looked at. 4 weight families x 3 drifts x 2
lookbacks = 24 specifications, and picking the winner post hoc would manufacture a
number (as the apex test nearly did). So: choose EVERYTHING on the training half,
report the held-out half, and require the score to ADD to line-age >= 100d rather
than merely correlate with it. The five coiling features looked fine casually and
came in at held-out AUC 0.485 while DEGRADING age. That is the bar.
"""
import json, glob, sys
import numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv
from levels import load_tf, atr

LOOKBACKS = (250, 500)
DRIFTS    = (0.0, 0.002, 0.006)          # ATR per bar of allowed level drift
WEIGHTS   = ("harmonic", "log", "power", "exp")
TOL0      = 0.60                          # matches levels.py's swept tolerance
CLUSTER   = 20                            # bars per epoch, for dispersion
OVL_K     = 5                             # bars in the overlap run
REJ_FWD   = 10                            # bars to measure a rejection's size

def wfun(name, age, L):
    age = np.maximum(age, 1.0)
    if name == "harmonic": return 1.0 / age
    if name == "log":      return 1.0 / np.log1p(age)
    if name == "power":    return age ** -0.5
    if name == "exp":      return np.exp(-age / (L / 4.0))
    raise ValueError(name)

def components(arr, L, drift, wname):
    """Causal per-bar score components. Row i uses bars < i only."""
    ts, o, h, l, c = arr[:,0], arr[:,1], arr[:,2], arr[:,3], arr[:,4]
    n = len(c)
    A = atr(h, l, c)
    out = {k: np.full(n, np.nan) for k in
           ("hits","novel","disp","rejmag","side","ovl","round")}
    if n < L + 20: return out, A

    age = np.arange(L, 0, -1).astype(float)          # oldest .. newest (age L..1)
    w   = wfun(wname, age, L); w /= w.sum()

    Hw = swv(h, L)[:-1]        # window ending at i-1, for i = L..n-1
    Lw = swv(l, L)[:-1]
    idx = np.arange(L, n)
    P   = c[idx][:, None]
    a_i = A[idx][:, None]
    a_i = np.where(np.isfinite(a_i) & (a_i > 0), a_i, np.nan)

    tau = a_i * (TOL0 + drift * age[None, :])
    hit = (Lw <= P + tau) & (Hw >= P - tau)

    out["hits"][idx] = (hit * w[None, :]).sum(1)

    # distance back to the nearest hit -- his rule 3
    anyhit = hit.any(1)
    nearest = np.where(anyhit, L - np.argmax(hit[:, ::-1], axis=1), L)
    out["novel"][idx] = np.log1p(nearest) / np.log1p(L)

    # dispersion: distinct epochs touched, not raw bar count
    nc = L // CLUSTER
    hc = hit[:, :nc * CLUSTER].reshape(len(idx), nc, CLUSTER).any(2)
    wc = wfun(wname, np.arange(nc, 0, -1) * CLUSTER, L); wc /= wc.sum()
    out["disp"][idx] = (hc * wc[None, :]).sum(1)

    # rejection magnitude: how far price left the level after touching it
    # LOOK-AHEAD BUG, FIXED. fwd[j] measured the move over bars j+1..j+REJ_FWD, and
    # the window ends at i-1, so fwd[i-1] read bars i..i+REJ_FWD-1 -- at and after
    # the decision bar. Under harmonic weights those bars carry 43-48% of the total
    # weight, so this was not a rounding error. Shifting by REJ_FWD means the
    # latest usable term is the rejection that had already COMPLETED by bar i-1.
    fmax = pd.Series(h).rolling(REJ_FWD).max().shift(-REJ_FWD).to_numpy()
    fmin = pd.Series(l).rolling(REJ_FWD).min().shift(-REJ_FWD).to_numpy()
    with np.errstate(invalid="ignore"):
        fwd = np.maximum(fmax - c, c - fmin) / np.where(A > 0, A, np.nan)
    fwd = np.roll(fwd, REJ_FWD); fwd[:REJ_FWD] = np.nan
    Fw = swv(np.nan_to_num(fwd, nan=0.0), L)[:-1]
    denom = (hit * w[None, :]).sum(1)
    out["rejmag"][idx] = np.where(denom > 0, (hit * Fw * w[None, :]).sum(1) / np.maximum(denom, 1e-12), 0.0)

    # side asymmetry: |above - below| / total, 0 = pivot, 1 = one-sided
    above = ((Lw > P) & hit); below = ((Hw < P) & hit)
    na = (above * w[None,:]).sum(1); nb = (below * w[None,:]).sum(1)
    out["side"][idx] = np.where(na + nb > 0, np.abs(na - nb) / (na + nb), 0.0)

    # his rule 4: small, barely-overlapping bars each taking out the prior extreme
    hi_p, lo_p = np.roll(h, 1), np.roll(l, 1)
    inter = np.minimum(h, hi_p) - np.maximum(l, lo_p)
    rng = np.maximum(h - l, 1e-12)
    ov = np.clip(inter / rng, 0, 1)
    newext = ((h > hi_p) | (l < lo_p)).astype(float)
    run = pd.Series((1 - ov) * newext).rolling(OVL_K).mean().to_numpy()
    out["ovl"] = np.roll(run, 1)          # shift: use bars strictly before i

    # round numbers
    with np.errstate(invalid="ignore"):
        for mag in (1000.0,):
            step = 10 ** np.floor(np.log10(np.maximum(c, 1)) - 1)
            d = np.abs(c - np.round(c / step) * step) / np.where(A > 0, A, np.nan)
            out["round"] = np.exp(-np.clip(d, 0, 10))
    return out, A

def daily_frame(spot, tfs=(1440, 360)):
    """Per-day components, one row per calendar day, max over TFs."""
    frames = []
    for tf in tfs:
        arr = load_tf(spot, tf)
        if arr is None: continue
        for wname in WEIGHTS:
            for L in LOOKBACKS:
                for dr in DRIFTS:
                    comp, _ = components(arr, L, dr, wname)
                    day = pd.to_datetime(arr[:, 0], unit="s").normalize()
                    df = pd.DataFrame(comp); df["day"] = day
                    # LOOK-AHEAD BUG, FIXED. P was c[i], the bar's OWN close, and the
                    # target is whether a 100x entry happened DURING that day. On a
                    # big-move day the close sits far from every prior bar, so `hits`
                    # collapsed -- and `hits` carried the largest (negative) coefficient.
                    # Diagnostic before the fix: corr(score, SAME-day |ret|) was +0.41 /
                    # +0.31 against +0.07 / +0.09 for NEXT-day. It was describing the
                    # move, not predicting it. shift(1) makes every input known BEFORE
                    # the day it is asked about. The weekly-block shuffle control did
                    # not catch this: permuting labels leaves the same-day relationship
                    # intact inside each block.
                    g = df.groupby("day").max().shift(1)
                    g.columns = [f"{c}|{wname}|{L}|{dr}|{tf}" for c in g.columns]
                    frames.append(g)
    return pd.concat(frames, axis=1) if frames else None

def target(spot):
    rows = []
    for fp in glob.glob(f"data/multibaggers/{spot}/*.json"):
        try: d = json.load(open(fp))
        except Exception: continue
        for r in d.get("rows", []):
            if r.get("entryTs"): rows.append((r["entryTs"][:10], float(r["ratio"])))
    x = pd.DataFrame(rows, columns=["day", "ratio"])
    g = x.groupby("day").agg(best=("ratio","max"), n100=("ratio", lambda s:(s>=100).sum()))
    g.index = pd.to_datetime(g.index)
    return g

if __name__ == "__main__":
    for spot in ("BTC","ETH"):
        F = daily_frame(spot)
        if F is None: print(f"{spot}: no data"); continue
        T = target(spot)
        J = F.join(T, how="inner").dropna(subset=["n100"])
        J["y"] = (J.n100 > 0).astype(int)
        J.to_parquet(f"data/pascore_{spot}.parquet")
        print(f"{spot}: {len(J)} days, {F.shape[1]} component-specs, base rate {J.y.mean():.3f}")
