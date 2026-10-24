#!/usr/bin/env python3
"""approach_energy.py -- does a SIDEWAYS approach to a level break (and blast) more than a steep one?

His words, 26 Sep: "price sideways approaching a trendline is more likely to result into breaking and blast (as not
much effort in sideways movement so energy is there) as opposed to rising/falling to reach the trendline (in which
energy has been spent to reach the trendline). Might also want to check for support/resistance, or 20EMA (I have
observed this too)."  Two claims: it BREAKS more, and the break BLASTS more.

(approach.py, 28 Sep, measured the approach at the BREAK bar against an option 100x outcome: null. This one starts
at the TOUCH, so whether it breaks at all is an outcome, and the outcome is the spot move itself.)

DATA  BTC/ETH perp MARK (no volume), 1h / 4h / 6h bars, incomplete last bar dropped. ATR = levels.atr (14).

LEVELS (each usable only once known)
  tline  levels.trendlines(max_span=400): >= 3 touches, usable from confirmed_i + 1 (confirmed_i >= anchor2 + 5)
         until its first close through. Falling resistance (R) breaks up, rising support (S) breaks down.
  horiz  swing highs (R) / lows (S) from levels.swings (k=5, prominence 1 ATR) clustered within TOL_ATR x ATR
         (levels.horizontal_levels); level = mean of the FIRST TWO swings, usable from 5 bars after the second
         swing (when that swing is visible) until its first close through. Discarded if price closed through it
         before it became usable.
  ema20  EMA(20) of closes, value at bar k = EMA through bar k-1. Side = where bar k-1 closed (above -> support).

TOUCH (episode start, bar k): the bar reaches within BAND = 0.3 ATR of the level from its own side (low <= level +
  0.3 ATR for a support, high >= level - 0.3 ATR for a resistance). First touch only: the previous bar did not
  touch, and since the last touch price has closed >= AWAY_ATR (1.2) ATR away (re-arm). Duplicate lines touching on
  the same bar count once.
APPROACH, bars k-K .. k-1 (all closed before the touch bar opens), K = 6 and 12:
  ER     efficiency = |c[k-1] - c[k-1-K]| / sum |bar-to-bar close changes|      (low = sideways / choppy)
  toward net move toward the level, in ATR(k-1)                                   (low = did not travel)
  SIDEWAYS = bottom tertile, DIRECTIONAL = top tertile (and toward > 0), tertiles within tf x level type x K.
  Robustness: fixed ER < 0.25 vs > 0.6, and the same split on `toward`.
OUTCOMES
  break   a CLOSE beyond the level within the next 24h of bars (k .. k+24h), also within 6 bars.
  blast   after the break close: biggest move in the break direction over the next 24h (bar highs/lows), in
          ATR(break bar) and %; shares >= 2 ATR and >= 3%. Also break-AND-blast per touch (both claims at once).
CONTROL sideways vs directional is compared within strata spot x tf x level type x side (R/S) x weekend (IST day
  of the touch), weighted to the sideways mix; a second version adds start-distance quartiles (how far price was
  from the level K bars earlier) so equal-distance approaches are compared. 90% CIs: weekly block bootstrap.
"""
import time, numpy as np, pandas as pd
from levels import load_tf, atr, trendlines, swings, horizontal_levels, TOL_ATR, AWAY_ATR
from fastboot import week_codes

SPOTS = ("BTC", "ETH"); TFS = (60, 240, 360); KS = (6, 12); BAND = 0.3; IST = 19800; NOW = time.time()

def load(spot, tf):
    a = load_tf(spot, tf); return a[a[:, 0] + tf * 60 <= NOW]

def touches(lv_fn, kind, start, stop, h, l, c, A):
    """first touches of one fixed-side level between bars start..stop-1; returns (k, break_i or None)"""
    out = []; armed = True; prev_touch = False
    for k in range(start, stop):
        if not np.isfinite(A[k]): continue
        lv = lv_fn(k)
        near = (l[k] <= lv + BAND * A[k]) if kind == "S" else (h[k] >= lv - BAND * A[k])
        if near and armed and not prev_touch: out.append(k); armed = False
        away = (c[k] - lv) / A[k] if kind == "S" else (lv - c[k]) / A[k]
        if away >= AWAY_ATR: armed = True
        prev_touch = near
    return out

def build_level_touches(a, A, tf):
    t, h, l, c = a[:, 0], a[:, 2], a[:, 3], a[:, 4]; n = len(c); rows = []
    # trendlines
    for L in trendlines(a, A, tf, max_span=400):
        i2, m, kind = L["anchor"][1], L["slope"], L["kind"]; ext = h if kind == "R" else l
        f = (lambda e, i, s: (lambda x: e[i] + s * (x - i)))(ext, i2, m)
        stop = L["break_i"] + 1 if L["break_i"] is not None else n
        for k in touches(f, kind, L["confirmed_i"] + 1, stop, h, l, c, A):
            rows.append(("tline", kind, k, f, None))
    # horizontal, first two swings
    lv, _ = horizontal_levels(a, tf)
    for L in lv:
        s = sorted(L["seeds"])[:2]; kind = L["kind"]; ext = h if kind == "R" else l
        P = float(np.mean(ext[s])); act = s[1] + 5 + 1
        if act >= n: continue
        cs = c[s[0] + 1:act]
        if ((cs > P) if kind == "R" else (cs < P)).any(): continue
        brk = np.where((c[act:] > P) if kind == "R" else (c[act:] < P))[0]
        stop = act + brk[0] + 1 if len(brk) else n
        f = (lambda P_: (lambda x: P_ + 0 * np.asarray(x, float)))(P)
        for k in touches(f, kind, act, stop, h, l, c, A):
            rows.append(("horiz", kind, k, f, None))
    # EMA20, value at k = EMA through k-1; side from close k-1; split into same-side runs
    ema = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
    E = np.concatenate([[np.nan], ema[:-1]])
    f_e = lambda x: E[np.asarray(x)]
    side = np.where(c > ema, "S", "R")                     # side for the NEXT bar (k) is decided by close k-1
    k = 21
    while k < n:
        kind = side[k - 1]; j = k
        while j < n and side[j - 1] == kind: j += 1          # run of bars whose prior close is on this side
        for kk in touches(f_e, kind, k, j, h, l, c, A):
            rows.append(("ema20", kind, kk, f_e, None))
        k = j
    return rows

def measure(a, A, tf, spot):
    t, h, l, c = a[:, 0], a[:, 2], a[:, 3], a[:, 4]; n = len(c)
    Mh = 24 * 60 // tf; seen = set(); out = []
    dc = np.abs(np.diff(c, prepend=c[0]))
    for typ, kind, k, f, _ in build_level_touches(a, A, tf):
        if (typ, kind, k) in seen or k - 13 < 0 or k + 2 * Mh + 1 >= n: continue
        seen.add((typ, kind, k))
        s = 1 if kind == "R" else -1                        # break direction; toward the level = s
        Ak = A[k - 1]
        if not np.isfinite(Ak) or Ak <= 0: continue
        lv_k = float(f(k))
        r = dict(spot=spot, tf=tf, typ=typ, kind=kind, t=t[k], px=c[k - 1], lv=lv_k,
                 dist0=s * (lv_k - c[k - 1]) / Ak,            # distance left to the level at the touch-bar open
                 line_move=-s * (lv_k - float(f(k - 1))) / Ak)  # ATR per bar the level moves TOWARD price (falling R, rising S)
        for K in KS:
            net = c[k - 1] - c[k - 1 - K]; path = dc[k - K:k].sum()
            r[f"ER{K}"] = abs(net) / path if path > 0 else np.nan
            r[f"tow{K}"] = s * net / Ak
            r[f"start{K}"] = s * (float(f(k - 1 - K)) - c[k - 1 - K]) / Ak if k - 1 - K >= 21 or typ != "ema20" else np.nan
        # break within 24h of bars and within 6 bars
        fut = np.arange(k, k + Mh); lvf = np.asarray(f(fut), float)
        beyond = (s * (c[fut] - lvf)) > 0
        b = k + int(np.argmax(beyond)) if beyond.any() else None
        r["brk24h"] = b is not None
        r["brk6"] = b is not None and b - k < 6
        r["bars_to_brk"] = (b - k) if b is not None else np.nan
        if b is not None:
            seg = slice(b + 1, b + 1 + Mh)
            ex = (h[seg].max() - c[b]) if s > 0 else (c[b] - l[seg].min())
            r["blastA"] = ex / A[b]; r["blastP"] = ex / c[b] * 100
            r["net24P"] = s * (c[b + Mh] / c[b] - 1) * 100
        out.append(r)
    return out

def build():
    rows = []
    for spot in SPOTS:
        for tf in TFS:
            a = load(spot, tf); A = atr(a[:, 2], a[:, 3], a[:, 4]); A = np.where(A > 0, A, np.nan)
            rows += measure(a, A, tf, spot)
    D = pd.DataFrame(rows)
    d = pd.to_datetime(D.t + IST, unit="s")
    D["weekend"] = d.dt.dayofweek >= 5
    D["week"] = (d - pd.to_timedelta(d.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
    D["blast2A"] = np.where(D.brk24h, D.blastA >= 2, np.nan)
    D["blast3P"] = np.where(D.brk24h, D.blastP >= 3, np.nan)
    D["brk_blast2A"] = (D.brk24h & (D.blastA >= 2)).astype(float)
    D["brk_blast3P"] = (D.brk24h & (D.blastP >= 3)).astype(float)
    for K in KS:
        g = D.groupby(["tf", "typ"])
        D[f"erT{K}"] = g[f"ER{K}"].transform(lambda x: pd.qcut(x, 3, labels=False, duplicates="drop"))
        D[f"towT{K}"] = g[f"tow{K}"].transform(lambda x: pd.qcut(x, 3, labels=False, duplicates="drop"))
        D[f"stQ{K}"] = g[f"start{K}"].transform(lambda x: pd.qcut(x, 4, labels=False, duplicates="drop"))
    return D

def strat_diff(D, y, side, strata, n=2000, seed=0):
    """mean(y | sideways) - mean(y | directional), within strata, weighted to the sideways mix; weekly bootstrap."""
    D = D[np.isfinite(D[y].astype(float))]
    st = pd.factorize(pd.MultiIndex.from_frame(D[strata].astype(str)))[0]; nS = st.max() + 1
    code, nw = week_codes(D.week.values); v = D[y].astype(float).values; sw = side.loc[D.index].values
    def sums(m):
        S = np.zeros((nw, nS)); C = np.zeros((nw, nS))
        np.add.at(S, (code[m], st[m]), v[m]); np.add.at(C, (code[m], st[m]), 1); return S, C
    S1, C1 = sums(sw == 1); S0, C0 = sums(sw == 0)
    def stat(s1, c1, s0, c0):
        ok = (c1 > 0) & (c0 > 0); w = np.where(ok, c1, 0)
        r1 = np.divide(s1, c1, out=np.zeros_like(s1), where=c1 > 0); r0 = np.divide(s0, c0, out=np.zeros_like(s0), where=c0 > 0)
        W = w.sum(-1); return (r1 * w).sum(-1) / W, (r0 * w).sum(-1) / W
    a1, a0 = stat(S1.sum(0), C1.sum(0), S0.sum(0), C0.sum(0))
    pick = np.random.default_rng(seed).integers(0, nw, size=(n, nw))
    P = np.zeros((n, nw)); np.add.at(P, (np.repeat(np.arange(n), nw), pick.ravel()), 1)   # times each week drawn
    b1, b0 = stat(P @ S1, P @ C1, P @ S0, P @ C0); d = (b1 - b0)[np.isfinite(b1 - b0)]
    return dict(n_side=int((sw == 1).sum()), n_dir=int((sw == 0).sum()), side=a1, dirn=a0, diff=a1 - a0,
                lo=np.quantile(d, .05), hi=np.quantile(d, .95), p_le0=(d <= 0).mean())

BASE = ["spot", "tf", "typ", "kind", "weekend"]
YS = ("brk24h", "brk6", "blastA", "blastP", "blast2A", "blast3P", "brk_blast2A", "brk_blast3P")

def side_series(D, how, K):
    if how == "ER":       x = D[f"erT{K}"].map({0: 1, 2: 0})
    elif how == "toward": x = D[f"towT{K}"].map({0: 1, 2: 0})
    elif how == "ERfix":  x = pd.Series(np.where(D[f"ER{K}"] < .25, 1, np.where(D[f"ER{K}"] > .6, 0, np.nan)), D.index)
    x = x.where(~((x == 0) & (D[f"tow{K}"] <= 0)))          # a directional approach must have moved TOWARD the level
    return x

if __name__ == "__main__":
    D = build(); D.to_parquet("data/approach_energy_touches.parquet")
    mid = D.t.min() + (D.t.max() - D.t.min()) / 2
    print(f"touches {len(D):,}; by tf x type:\n{D.groupby(['tf', 'typ']).size().unstack()}")
    print(f"halves split at {pd.Timestamp(mid + IST, unit='s').date()}")
    print("\nraw rates by ER tertile (K=12): break24h, blast>=2ATR | break, blast>=3% | break")
    print(D.groupby(["typ", "tf", "erT12"]).agg(n=("brk24h", "size"), brk=("brk24h", "mean"), b2A=("blast2A", "mean"),
                                                 b3P=("blast3P", "mean"), blastA=("blastA", "median")).round(3).to_string())
    out = []
    subsets = {"all": D.index}
    for typ in ("tline", "horiz", "ema20"): subsets[typ] = D.index[D.typ == typ]
    for tf in TFS: subsets[f"{tf}m"] = D.index[D.tf == tf]
    for sp in SPOTS: subsets[sp] = D.index[D.spot == sp]
    subsets["H1"] = D.index[D.t < mid]; subsets["H2"] = D.index[D.t >= mid]
    subsets["weekday"] = D.index[~D.weekend]; subsets["weekend"] = D.index[D.weekend]
    for how in ("ER", "toward", "ERfix"):
        for K in KS:
            sd = side_series(D, how, K)
            for sub, ix in subsets.items():
                if how != "ER" and K != 12 and sub != "all": continue
                for ctrl, strata in (("base", BASE), ("+start", BASE + [f"stQ{K}"])):
                    if ctrl == "+start" and sub not in ("all", "tline", "horiz", "ema20"): continue
                    DD = D.loc[ix]; DD = DD[sd.loc[ix].notna()]
                    if ctrl == "+start": DD = DD[DD[f"stQ{K}"].notna()]
                    for y in YS:
                        r = strat_diff(DD, y, sd, strata)
                        out.append(dict(how=how, K=K, sub=sub, ctrl=ctrl, y=y, **r))
    R = pd.DataFrame(out); R.to_csv("data/approach_energy_results.csv", index=False)
    # geometry check: a sloped line keeps moving into a price that goes sideways, so it gets crossed without any push
    sd = side_series(D, "ER", 12); T = D[(D.typ == "tline") & sd.notna()].copy(); T["side"] = sd[T.index]
    T["moveT"] = T.groupby("tf").line_move.transform(lambda x: pd.qcut(x, 3, labels=["flat", "mid", "steep"]))
    print("\ntrendlines: break24h by how fast the line moves toward price (tertile within tf), sideways vs directional")
    for mv, G in T.groupby("moveT"):
        r = strat_diff(G, "brk24h", G.side, BASE); print(mv, {k: round(float(v), 3) for k, v in r.items()})
    print("\nbreak24h for SIDEWAYS ER12 approaches by line-move tertile:", T[T.side == 1].groupby("moveT").brk24h.mean().round(3).to_dict())
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 2000)
    print(R[R.y.isin(["brk24h", "blast2A", "blast3P", "brk_blast2A"])].round(3).to_string())
