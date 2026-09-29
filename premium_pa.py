"""
Price action ON THE PREMIUM SERIES, not on the underlying.

Every feature in this project so far reads spot: trendlines, ATR, wedges, always-in.
The option enters only as a payoff to be scored. So his five named signals --
premium rebounce, premium holding, stairs, wall, red squeeze -- were never
representable, because they describe the OPTION CHART's own behaviour.

That gap matters more than it looks. docs record that Delta serves historical OI
but NOT historical IV. The premium series is the only surviving record of IV. An
option that refuses to decay while time passes and spot moves against it is an
option whose IV is being bid -- information no spot feature can carry.

Operationalised (H = lookback bars, 15m each):
  hold    premium flat/up while spot moved ADVERSELY and theta ran. The IV proxy.
  rebounce premium bounced >=REB off a local low without regaining its prior high.
  stairs  >=2 up-legs, each a higher high, separated by low-range consolidation.
  wall    a premium level touched >=3x from below and never exceeded.
  squeeze premium's own range contracting vs H bars ago, majority red candles.

Each is measured at entry using ONLY bars up to and including i. Scored on EV of
holding to settlement, net of COST, with the week as the unit of independence.
"""
import json, glob, os, re, sys
import numpy as np
from datetime import datetime, timezone

COST = 0.0826
RES = "15"
STEP = 4
MIN_PREM = 0.05
H = 16                 # 4h of premium history
REB = 0.25
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")

def load_spot(asset):
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/{RES}/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def week_of(ts):
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{d.isocalendar()[0]}W{d.isocalendar()[1]:02d}"

def feats(o, h, l, c, sp, typ, i):
    """All windows end at i. No forward bars touched."""
    a, b = i - H + 1, i + 1
    if a < 0: return None
    P, Ph, Pl = c[a:b], h[a:b], l[a:b]
    S = sp[a:b]
    if not (np.isfinite(P).all() and np.isfinite(S).all()): return None
    if P[0] <= 0 or S[0] <= 0: return None

    # adverse spot move for this option type, in %
    sm = (S[-1] - S[0]) / S[0] * 100
    adverse = (-sm) if typ == "C" else sm      # >0 means spot went against it
    pchg = (P[-1] - P[0]) / P[0]

    # HOLD: spot moved against it, time passed, premium did not fall
    hold = (adverse > 0.15) and (pchg > -0.02)

    # REBOUNCE: bounced off the window low, still under the window high
    lo, hi = Pl.min(), Ph.max()
    reb = False
    if lo > 0:
        k = int(np.argmin(Pl))
        reb = (k < H - 2) and (P[-1] / lo - 1 >= REB) and (P[-1] < hi * 0.98)

    # STAIRS: legs of higher highs split by quiet stretches
    rng = (Ph - Pl) / np.maximum(P, 1e-9)
    quiet = rng < np.median(rng)
    legs, run_hi, last = 0, -np.inf, False
    for k in range(H):
        if quiet[k]:
            last = True
        elif Ph[k] > run_hi and last:
            legs += 1; run_hi = Ph[k]; last = False
        run_hi = max(run_hi, Ph[k])
    stairs = legs >= 2

    # WALL: a level touched >=3x from below, never cleared
    wall = False
    if hi > 0:
        near = np.abs(Ph - hi) / hi < 0.03
        wall = near.sum() >= 3 and P[-1] < hi

    # SQUEEZE: premium's own range compressing, mostly red
    r1 = rng[-H // 2:].mean(); r0 = rng[:H // 2].mean()
    red = (P < o[a:b]).mean()
    squeeze = (r0 > 0) and (r1 / r0 < 0.7) and (red > 0.5)

    return dict(hold=hold, rebounce=reb, stairs=stairs, wall=wall, squeeze=squeeze)

def scan(asset, recs):
    spot = load_spot(asset)
    if not spot: return
    days = sorted(d for d in os.listdir(f"data/candles/{asset}") if not d.startswith("."))
    for day in days:
        dd = f"data/candles/{asset}/{day}/{RES}"
        if not os.path.isdir(dd): continue
        for fn in os.listdir(dd):
            m = SYM.match(fn)
            if not m: continue
            typ, _, strike, _ = m.groups(); strike = float(strike)
            try: rows = json.load(open(os.path.join(dd, fn)))
            except Exception: continue
            if len(rows) < H + 6: continue
            ts = np.array([int(r[0]) for r in rows])
            o  = np.array([np.nan if r[1] is None else float(r[1]) for r in rows])
            h  = np.array([np.nan if r[2] is None else float(r[2]) for r in rows])
            l  = np.array([np.nan if r[3] is None else float(r[3]) for r in rows])
            c  = np.array([np.nan if r[4] is None else float(r[4]) for r in rows])
            sp = np.array([spot.get(int(t), np.nan) for t in ts])
            if np.isnan(c).all() or np.isnan(sp).all(): continue
            settle, exp_ts = c[-1], ts[-1]
            if not np.isfinite(settle): continue
            for i in range(H, len(c) - 1, STEP):
                e = c[i]
                if not np.isfinite(e) or e < MIN_PREM: continue
                s0 = sp[i]
                if not np.isfinite(s0): continue
                f = feats(o, h, l, c, sp, typ, i)
                if f is None: continue
                otm = (s0 - strike) / s0 * 100 if typ == "P" else (strike - s0) / s0 * 100
                recs.append((week_of(int(ts[i])), (exp_ts - ts[i]) / 3600.0, otm,
                             settle / e, f["hold"], f["rebounce"], f["stairs"],
                             f["wall"], f["squeeze"]))

NAMES = ["hold", "rebounce", "stairs", "wall", "squeeze"]

def report(recs, title, filt=None):
    R = recs if filt is None else [r for r in recs if filt(r)]
    if len(R) < 200: print(f"\n{title}: too few ({len(R)})"); return
    wk = np.array([r[0] for r in R])
    ev = np.array([r[3] for r in R]) - 1 - COST
    F  = {n: np.array([r[4 + k] for r in R], bool) for k, n in enumerate(NAMES)}
    rng = np.random.default_rng(11); uw = np.unique(wk)
    base = ev.mean()
    print(f"\n{title}   n={len(R):,}  weeks={len(uw)}  base EV={base:+.4f}")
    print(f"{'signal':<10}{'n':>9}{'fires':>8}{'EV':>10}{'dEV':>10}{'P(dEV>0)':>10}{'win%':>8}")
    for n in NAMES:
        s = F[n]
        if s.sum() < 100: 
            print(f"{n:<10}{s.sum():>9,}{'--':>8}{'':>10}{'':>10}{'':>10}{'':>8}"); continue
        boot = []
        for _ in range(2000):
            pick = rng.choice(uw, len(uw), replace=True)
            m = np.isin(wk, pick)
            a, b = ev[m & s], ev[m & ~s]
            if len(a) and len(b): boot.append(a.mean() - b.mean())
        boot = np.array(boot)
        print(f"{n:<10}{s.sum():>9,}{s.mean()*100:>7.1f}%{ev[s].mean():>10.4f}"
              f"{ev[s].mean()-ev[~s].mean():>10.4f}{(boot>0).mean():>10.3f}"
              f"{(ev[s]>0).mean()*100:>7.1f}%")

if __name__ == "__main__":
    recs = []
    for a in ("BTC", "ETH"):
        scan(a, recs); print(f"{a}: {len(recs):,} cumulative", file=sys.stderr)
    report(recs, "=== ALL ===")
    report(recs, "=== OTM only (2-15%) ===", lambda r: 2 <= r[2] <= 15)
    report(recs, "=== OTM 2-15%, >=12h to expiry ===", lambda r: 2 <= r[2] <= 15 and r[1] >= 12)
    report(recs, "=== OTM 2-15%, <12h to expiry ===", lambda r: 2 <= r[2] <= 15 and r[1] < 12)
