"""Minimum spot move required for a 1:100 option return.

Two numbers per (bar, type, expiry), which is what the dashboard's 6-cell bars show:

  AT EXPIRY   intrinsic only. A call needs S_T = K + 100*P; a put S_T = K - 100*P.
              Required move = that spot divided by spot now, minus 1.

  RIGHT NOW   the option must be worth 100*P with time value still on it. Imply
              IV from the current premium, then solve for the spot that reprices
              the option at 100*P with time-to-expiry and IV held fixed. This is
              always the easier hurdle, and the gap between the two is the time
              value you are being handed.

Taken as the MINIMUM across strikes -- his "max would be computed across all
strikes", i.e. the best strike available, so the smallest move that gets there.

Units check against the live chain: P-BTC-99000-271126 marked 14,787.70 with spot
84,313.9, intrinsic 14,686.10, time value 101.60. Premium is quoted in the same
units as (K - S), so no contract multiplier enters the ratio maths.

Everything is vectorised over a (time x strike) grid per expiry; bisection rather
than Newton because the payoff is monotone in spot and bisection cannot diverge.
"""
import numpy as np

SQ2 = np.sqrt(2.0)

def _ncdf(x):
    return 0.5 * (1.0 + np.vectorize(np.math.erf)(x / SQ2)) if False else 0.5*(1.0+_erf(x/SQ2))

def _erf(x):
    # Abramowitz-Stegun 7.1.26, vectorised; |eps| < 1.5e-7, ample for this use
    s = np.sign(x); x = np.abs(x)
    t = 1.0/(1.0+0.3275911*x)
    y = 1.0-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*np.exp(-x*x)
    return s*y

def bs(S, K, T, sig, call):
    """Black-Scholes, zero rate. Arrays broadcast. T in years."""
    S = np.asarray(S, float); K = np.asarray(K, float)
    T = np.maximum(np.asarray(T, float), 1e-9)
    sig = np.maximum(np.asarray(sig, float), 1e-9)
    v = sig*np.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S/K) + 0.5*v*v)/v
    d2 = d1 - v
    c = S*_ncdf(d1) - K*_ncdf(d2)
    p = K*_ncdf(-d2) - S*_ncdf(-d1)
    return np.where(call, c, p)

def implied_vol(P, S, K, T, call, lo=1e-3, hi=5.0, iters=60):
    """Bisection on sigma. P, S, K, T broadcast to a common shape."""
    a = np.full(np.broadcast(P, S, K, T).shape, lo)
    b = np.full(a.shape, hi)
    for _ in range(iters):
        m = 0.5*(a+b)
        too_low = bs(S, K, T, m, call) < P
        a = np.where(too_low, m, a)
        b = np.where(too_low, b, m)
    return 0.5*(a+b)

def spot_for_target(target, S, K, T, sig, call, span=6.0, iters=70):
    """Spot at which the option is worth `target`, with T and sigma fixed.

    Monotone increasing in S for calls, decreasing for puts, so bisect on the
    appropriate bracket. span=6 means search up to 6x spot (calls) or down to
    spot/6 (puts), which comfortably covers any 100x that is reachable at all.
    """
    if call:
        a = np.array(S, float); b = np.asarray(S, float)*span
    else:
        a = np.asarray(S, float)/span; b = np.array(S, float)
    for _ in range(iters):
        m = 0.5*(a+b)
        v = bs(m, K, T, sig, call)
        if call:
            lo_side = v < target
            a = np.where(lo_side, m, a); b = np.where(lo_side, b, m)
        else:
            lo_side = v < target          # puts: value falls as spot rises
            b = np.where(lo_side, m, b); a = np.where(lo_side, a, m)
    return 0.5*(a+b)

def required_moves(prem, strikes, spot, tte_yrs, call, mult=100.0):
    """Per-bar minimum |move| for a `mult`x return, at expiry and right now.

    prem    (T x K) premium grid, NaN where the contract was not quoted
    strikes (K,)    strike per column
    spot    (T,)    spot at each bar
    tte_yrs (T,)    time to expiry in years at each bar
    Returns (move_expiry_pct, move_now_pct, best_strike_expiry, best_strike_now).
    Values are SIGNED: positive = spot must rise, negative = must fall.
    """
    prem = np.asarray(prem, float)
    K = np.asarray(strikes, float)[None, :]
    S = np.asarray(spot, float)[:, None]
    T = np.asarray(tte_yrs, float)[:, None]
    ok = np.isfinite(prem) & (prem > 0) & np.isfinite(S) & (T > 0)

    tgt = mult*prem
    # --- at expiry: intrinsic only ---
    s_exp = (K + tgt) if call else (K - tgt)
    mv_exp = np.where(ok & (s_exp > 0), s_exp/S - 1.0, np.nan)

    # --- right now: reprice with time value ---
    sig = implied_vol(np.where(ok, prem, 1e-9), S, K, T, call)
    s_now = spot_for_target(np.where(ok, tgt, 1e9), S, K, T, sig, call)
    mv_now = np.where(ok, s_now/S - 1.0, np.nan)
    # unreachable inside the search bracket -> not achievable
    cap = 5.5 if call else -0.82
    mv_now = np.where(np.abs(mv_now) > abs(cap)*0.99, np.nan, mv_now)

    def pick(mv):
        a = np.abs(mv)
        allnan = np.all(~np.isfinite(a), axis=1)
        idx = np.where(allnan, 0, np.nanargmin(np.where(np.isfinite(a), a, np.inf), axis=1))
        val = np.where(allnan, np.nan, mv[np.arange(len(mv)), idx])
        ks  = np.where(allnan, np.nan, K[0, idx])
        return val, ks
    me, ke = pick(mv_exp)
    mn, kn = pick(mv_now)
    return me*100.0, mn*100.0, ke, kn
