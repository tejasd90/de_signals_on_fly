"""Do HURDLES (hurdles.py) behave the way he says? Tested on 1m TRADED and 5m MARK candles.

HURDLE  exposed local extreme (beyond everything of the last E hours), sharp move in (>= 2 ATR within M
        bars), sharper-ish reversal out (>= 0.7 x the move in, within M bars), a quick touch (<= 3 bars
        near it). Known only once the reversal completes (bar i+M).
CONTROL exposed local extremes of the same kind that rolled over SLOWLY (reversal < 0.5 x the move in):
        the ordinary swing highs/lows a hurdle is claimed to be stronger than.
From the moment each level is known, for 3 days:
  retest   price comes back within 0.1 ATR of it
  reject   after the retest, price moves 1.5 ATR away before any CLOSE beyond it (+0.1 ATR)
  break    a close beyond it first -- his re-entry trigger
  carry    after a break, the max move beyond the level over the next 2 hours, in ATR
Bootstrap by day for every hurdle-vs-control difference.
"""
import sys, numpy as np, pandas as pd

def load(asset, res):
    if res == "1":
        d = pd.read_parquet(f"data/{asset.lower()}_1m.parquet").rename(columns={"ts": "t"})
    else:
        from hurdles import load as L5
        d = L5(asset, res)
    return d[["t", "o", "h", "l", "c"]].astype(float).sort_values("t").drop_duplicates("t").reset_index(drop=True)

def levels(d, res, K, M, E_H, UP=2.0):
    h, l, c = d.h.to_numpy(), d.l.to_numpy(), d.c.to_numpy()
    pc = np.r_[c[0], c[:-1]]
    A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14, min_periods=3).mean().to_numpy()
    E = max(1, int(E_H * 60 / int(res))); out = []
    for side, x, y, sgn in (("HIGH", h, l, 1), ("LOW", l, h, -1)):
        s = pd.Series(sgn * x); sy = pd.Series(sgn * y)
        loc = (s == s.rolling(2*K + 1, center=True).max()).to_numpy()
        exposed = (s > s.shift(1).rolling(E).max()).to_numpy()
        start = sy.shift(1).rolling(M).min().to_numpy()               # lowest low of the M bars before (for HIGH)
        after = sy[::-1].shift(1).rolling(M).min()[::-1].to_numpy()   # lowest low of the M bars after
        cand = np.where(loc & exposed & np.isfinite(A) & (A > 0) & np.isfinite(start) & np.isfinite(after))[0]
        for i in cand:
            if i + M >= len(d): continue
            a = A[i]; xi = sgn * x[i]
            rise = (xi - start[i]) / a; drop = (xi - after[i]) / a
            if rise < UP: continue
            touch = int((np.abs(x[max(0, i-M):i+M+1] - x[i]) <= 0.25 * a).sum())
            kind = "hurdle" if (drop >= 0.7 * rise and touch <= 3) else ("control" if drop < 0.5 * rise else None)
            if kind: out.append((side, sgn, i, i + M, x[i], a, kind))
    return pd.DataFrame(out, columns=["side", "sgn", "i", "known", "level", "atr", "kind"]), (h, l, c)

def follow(L, hlc, res, horizon_h=72, carry_h=2):
    h, l, c = hlc; n = len(c); H = int(horizon_h * 60 / int(res)); Cn = int(carry_h * 60 / int(res))
    rows = []
    for r in L.itertuples():
        s, lv, a = r.sgn, r.level, r.atr
        seg = slice(r.known + 1, min(n, r.known + 1 + H))
        x = h[seg] if s == 1 else l[seg]
        near = np.where(s * (x - lv) >= -0.1 * a)[0]                 # came back within 0.1 ATR
        res_ = dict(kind=r.kind, side=r.side, i=r.i, retest=False, outcome=None, carry=np.nan)
        if len(near):
            j = r.known + 1 + near[0]; res_["retest"] = True
            for k in range(j, min(n, j + H)):
                if s * (c[k] - lv) > 0.1 * a:
                    res_["outcome"] = "break"
                    end = min(n, k + 1 + Cn)
                    ext = (h[k+1:end].max() - lv) if s == 1 else (lv - l[k+1:end].min())
                    res_["carry"] = ext / a if end > k + 1 else np.nan
                    break
                if s * (lv - (l[k] if s == 1 else h[k])) >= 1.5 * a:
                    res_["outcome"] = "reject"; break
        rows.append(res_)
    return pd.DataFrame(rows)

def boot_diff(a, b, n=2000):
    a, b = np.asarray(a, float), np.asarray(b, float); rng = np.random.default_rng(0)
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n)]
    return np.percentile(d, 2.5), np.percentile(d, 97.5)

def report(name, F):
    F = F.copy()
    print(f"\n== {name}: {int((F.kind=='hurdle').sum())} hurdles, {int((F.kind=='control').sum())} control peaks")
    hu, co = F[F.kind == "hurdle"], F[F.kind == "control"]
    print(f"   retested within 3 days   hurdle {hu.retest.mean():.1%}   control {co.retest.mean():.1%}")
    hr, cr = hu[hu.outcome.notna()], co[co.outcome.notna()]
    a, b = (hr.outcome == "reject"), (cr.outcome == "reject")
    lo, hi = boot_diff(a, b)
    print(f"   REJECTED on retest       hurdle {a.mean():.1%} (n {len(hr)})   control {b.mean():.1%} (n {len(cr)})   diff CI [{lo:+.1%},{hi:+.1%}]")
    hb, cb = hu[hu.outcome == "break"].carry.dropna(), co[co.outcome == "break"].carry.dropna()
    lo, hi = boot_diff(hb >= 3, cb >= 3)
    print(f"   after a CLOSE beyond it: carry >= 3 ATR in 2h   hurdle {(hb>=3).mean():.1%} (n {len(hb)})   control {(cb>=3).mean():.1%}   diff CI [{lo:+.1%},{hi:+.1%}];  median carry {hb.median():.2f} vs {cb.median():.2f} ATR")

if __name__ == "__main__":
    runs = [("ETH", "1", dict(K=10, M=20, E_H=12)), ("BTC", "1", dict(K=10, M=20, E_H=12)),
            ("BTC", "5", dict(K=6, M=12, E_H=24)), ("ETH", "5", dict(K=6, M=12, E_H=24))]
    only = sys.argv[1:]
    for asset, res, kw in runs:
        if only and f"{asset}{res}" not in only: continue
        try: d = load(asset, res)
        except FileNotFoundError: print(f"\n== {asset} {res}m: no data yet"); continue
        L, hlc = levels(d, res, **kw)
        F = follow(L, hlc, res)
        report(f"{asset} {res}m ({'TRADED' if res=='1' else 'MARK'}), {pd.to_datetime(d.t.min(),unit='s').date()}..{pd.to_datetime(d.t.max(),unit='s').date()}", F)

def robust(asset, res, kw):
    """Same comparison, but only levels price had clearly LEFT (>= 1.5 ATR away at the bar the level
    became known), so a 'retest' is a genuine return for both groups; and split by time."""
    d = load(asset, res); L, hlc = levels(d, res, **kw); h, l, c = hlc
    away = L.sgn * (L.level - c[L.known.to_numpy()]) / L.atr >= 1.5
    F = follow(L[away].reset_index(drop=True), hlc, res)
    F["t"] = d.t.to_numpy()[F.i.to_numpy()]
    report(f"{asset} {res}m, levels price had LEFT by >= 1.5 ATR", F)
    mid = F.t.median()
    for lab, g in (("first half", F[F.t < mid]), ("second half", F[F.t >= mid])):
        hu, co = g[g.kind == "hurdle"], g[g.kind == "control"]
        r1 = (hu.outcome == "reject")[hu.outcome.notna()].mean(); r2 = (co.outcome == "reject")[co.outcome.notna()].mean()
        c1 = (hu[hu.outcome == "break"].carry >= 3).mean(); c2 = (co[co.outcome == "break"].carry >= 3).mean()
        print(f"     {lab}: reject {r1:.1%} vs {r2:.1%}   carry>=3ATR {c1:.1%} vs {c2:.1%}")
