"""Tejas, 2026-10-03: "smart money" defends option levels at important points, and price
returns to where retail is at break-even before reversing. We only ever hear about the
cases that get caught. A statistical FINGERPRINT can be tested on every expiry instead.

Uses data/opt_oi.parquet (fetch_opt_oi.py): hourly OI per strike over the final 30h.

1. MAX-PAIN PULL. MP_h = the settlement price that minimises what option HOLDERS collect,
   from OI h hours before settlement. If writers steer settlement, S_T lands nearer MP than
   chance. Control: the MIRROR point 2*S_h - MP, the same distance from spot on the other
   side. With no pull, S_T is equally likely to land near either one. Compared in the final
   window (h -> 0) and in an earlier non-settlement window of the same length (24h -> 12h),
   so a generic "mean reversion" effect shows up in both, while an expiry effect shows only in the last.
2. DEFENDED WALLS. The highest-OI call strike above spot and put strike below, 24h out.
   P(spot settles beyond the wall) vs beyond the mirror level at the same distance.
Week-block/expiry bootstrap for every difference.
"""
import json, os, numpy as np, pandas as pd

def spot_at(asset, t):
    day = pd.Timestamp(t - 3600, unit="s").strftime("%Y-%m-%d")
    try:
        for r in json.load(open(f"data/spot_candles/{asset}/60/{day}")):
            if int(r[0]) == t - 3600: return float(r[4]), float(r[2]), float(r[3])
    except Exception: pass
    return None

def path(asset, a, b):
    hi, lo = -np.inf, np.inf
    for t in range(a + 3600, b + 1, 3600):
        x = spot_at(asset, t)
        if x: hi, lo = max(hi, x[1]), min(lo, x[2])
    return hi, lo

def max_pain(snap):
    ks = np.sort(snap.K.unique())
    c = snap[snap.typ == "C"].groupby("K").oi.sum(); p = snap[snap.typ == "P"].groupby("K").oi.sum()
    pay = [(c * np.maximum(X - c.index.values, 0)).sum() + (p * np.maximum(p.index.values - X, 0)).sum() for X in ks]
    return ks[int(np.argmin(pay))]

O = pd.read_parquet("data/opt_oi.parquet")
rows = []
for (asset, e), g in O.groupby(["asset", "expiry"]):
    settle = int(pd.Timestamp(e).timestamp()) + 43200
    ST = spot_at(asset, settle)
    if ST is None: continue
    rec = dict(asset=asset, expiry=e, ST=ST[0])
    for h in (24, 6, 3):     # 12h = 00:00 UTC, where OI bars are systematically absent
        t = settle - h*3600
        snap = g[(g.t <= t) & (g.t > t - 6*3600)].sort_values("t").groupby(["typ", "K"]).tail(1)   # last OI known at t
        S = spot_at(asset, t)
        if S is None or snap.oi.sum() <= 0 or snap.K.nunique() < 8: continue
        rec[f"S{h}"] = S[0]; rec[f"MP{h}"] = max_pain(snap)
        if h == 24:
            near = (snap.K/S[0] - 1).abs().between(0.005, 0.025)          # strikes it could matter to defend
            above = snap[near & (snap.typ == "C") & (snap.K > S[0])].groupby("K").oi.sum()
            below = snap[near & (snap.typ == "P") & (snap.K < S[0])].groupby("K").oi.sum()
            if len(above) and len(below):
                rec["cwall"], rec["pwall"] = above.idxmax(), below.idxmax()
                rec["hi24"], rec["lo24"] = path(asset, t, settle)
    rows.append(rec)
R = pd.DataFrame(rows)
print(f"{len(R)} expiries ({R.asset.value_counts().to_dict()}), {R.expiry.min()} .. {R.expiry.max()}\n")

def boot(v, n=4000):
    v = v[np.isfinite(v)]; rng = np.random.default_rng(0)
    b = np.array([rng.choice(v, len(v)).mean() for _ in range(n)])
    return v.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5), (b <= 0).mean(), len(v)

print("1. MAX-PAIN PULL  (positive = price ended CLOSER to max pain than to its mirror point; % of spot)")
print(f"   {'window':<26}{'mean':>8}{'CI':>20}{'P<=0':>7}{'n':>5}{'closer to MP':>14}")
for lab, h0, h1 in (("final 24h  (24 -> settle)", 24, 0), ("final 6h   (6 -> settle)", 6, 0),
                    ("final 3h   (3 -> settle)", 3, 0), ("CONTROL: 24h -> 6h", 24, 6)):
    S0, MP = R[f"S{h0}"], R[f"MP{h0}"]
    S1 = R.ST if h1 == 0 else R[f"S{h1}"]
    mirror = 2*S0 - MP
    ok = (MP - S0).abs()/S0 > 0.001                          # pull only identifiable if MP is off-spot
    adv = ((S1 - mirror).abs() - (S1 - MP).abs())/S0*100
    m, lo, hi, p, n = boot(adv[ok].to_numpy())
    closer = ((S1 - MP).abs() < (S1 - mirror).abs())[ok].mean()
    print(f"   {lab:<26}{m:>+8.3f}   [{lo:+.3f},{hi:+.3f}]{p:>7.3f}{n:>5}{closer:>13.0%}")

print("\n2. DEFENDED WALLS  (24h before settlement: biggest call-OI strike above spot, put-OI strike below)")
W = R.dropna(subset=["cwall", "pwall"]).copy()
for side, wall, sgn in (("call wall (above)", "cwall", 1), ("put wall (below)", "pwall", -1)):
    d = (W[wall] - W.S24)                                     # signed distance to the wall
    mirror = W.S24 - d
    beyond_w = (sgn*(W.ST - W[wall]) > 0); beyond_m = (-sgn*(W.ST - mirror) > 0)
    touch_w = (W.hi24 >= W[wall]) if sgn == 1 else (W.lo24 <= W[wall])
    touch_m = (W.lo24 <= mirror) if sgn == 1 else (W.hi24 >= mirror)
    held = (touch_w & ~beyond_w).sum()/max(touch_w.sum(), 1); held_m = (touch_m & ~beyond_m).sum()/max(touch_m.sum(), 1)
    m, lo, hi, p, n = boot((beyond_m.astype(float) - beyond_w.astype(float)).to_numpy())
    print(f"   {side:<18} median distance {(d.abs()/W.S24*100).median():.2f}%   settles beyond: wall {beyond_w.mean():.1%} vs mirror {beyond_m.mean():.1%}"
          f"   diff {m:+.3f} [{lo:+.3f},{hi:+.3f}]")
    print(f"   {'':<18} touched: wall {touch_w.mean():.1%} vs mirror {touch_m.mean():.1%};  of those touched, held (did not settle beyond): wall {held:.0%} vs mirror {held_m:.0%}")
