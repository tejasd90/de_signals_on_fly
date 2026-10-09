"""v4 (2026-10-09, his correction to v3): ONLY the RISING parabola matters; no decay is required.
Pattern = the trailing run of consecutive higher lows (>= 3) ending at the newly confirmed low is
CONVEX (a quadratic through the run opens upward: each step up tends to be bigger). 'accel' also
records the stricter last-gap > first-gap. The decay ratio is recorded for reporting, never filtered.

Premium-base parabola, v3 (2026-10-09): the IDEA only, with no time-to-expiry, timeframe or
absolute-cheapness assumptions (his correction to v2).

Parabola, in words: the premium's dips (swing lows) trace a bowl. They come down to a bottom and
flatten, and every dip after the bottom stays above it, curving up. Measured as a quadratic through
the swing lows that opens upward, with >= 2 lows after the bottom, all higher than it. Two shapes:
  bowl   the above (the lows after the bottom need only be higher than the bottom)
  arm    the rising arm only: >= 3 consecutive higher lows whose gaps grow (accelerating)
Decay toward zero: the bottom is <= DECAY x the highest close of the contract before the window.
Evaluated at the moment a new swing low is CONFIRMED (2 bars after it), the instant the shape
becomes visible, with close >= that low. Every timeframe in TFS, window W bars, any time to expiry
(at least one bar must remain for an outcome). The control is the same moment (a new swing low just
confirmed, decayed the same) where the shape is NOT present. Both kinds are sampled at most once per
W bars per contract.

His chain point (Nifty example): the shape is clearest on one strike and flattens further along the
chain. For every pattern event the next 3 strikes FURTHER OTM are recorded at the same bar: their
premium, their own outcome, and whether they show the shape too."""
import json, os, re, sys, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
TFS = (5, 15, 60, 240); W = 48; DECAY = 0.15

def spot_series(asset):
    import glob
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)): m[int(r[0])] = float(r[4])
        except Exception: pass
    return m
SPOT = {}
def _init():
    for a_ in ("BTC", "ETH"): SPOT[a_] = spot_series(a_)

def rising(l, js):
    """(convex rising run, accelerating, run length) for the swing lows js."""
    lows = l[js]; r = 1
    while r < len(lows) and lows[-r - 1] < lows[-r]: r += 1
    if r < 3: return False, False, r
    run = lows[-r:]; x = np.array(js[-r:], float) - js[-r]
    A = np.polyfit(x, run, 2)[0]; d = np.diff(run)
    return bool(A > 0), bool(d[-1] > d[0]), r

def shape(l, js, i):
    """(bowl, arm, rise) for the swing lows js (indices) known at bar i."""
    lows = l[js]; kb = int(np.argmin(lows)); bottom = lows[kb]; after = lows[kb + 1:]
    x = np.array(js, float) - js[0]; A = np.polyfit(x, lows, 2)[0] if len(js) >= 3 else 0
    bowl = A > 0 and len(after) >= 2 and after.min() > bottom
    d = np.diff(lows[-3:]) if len(lows) >= 3 else np.array([0])
    arm = len(lows) >= 3 and (d > 0).all() and d[-1] > d[0]
    return bowl, arm, (lows[-1] / bottom if bottom > 0 else np.nan), bottom

def scan(args):
    asset, expiry, tf = args
    d = f"data/candles/{asset}/{expiry}/{tf}"
    settle = pd.Timestamp(expiry).timestamp() + 43200; sp = SPOT[asset]
    C = {}
    for fn in os.listdir(d):
        m = SYM.match(fn)
        if not m: continue
        try: rows = json.load(open(f"{d}/{fn}"))
        except Exception: continue
        a = np.array([[r[0], r[2], r[3], r[4]] for r in rows if r[4] is not None and r[0] + tf * 60 <= settle], float)
        if len(a) >= W + 10: C[(m.group(1), float(m.group(3)))] = a
    out = []
    for (typ, K), a in C.items():
        t, h, l, c = a.T; n = len(c)
        sw = [j for j in range(2, n - 2) if l[j] == l[j-2:j+3].min()]
        cm = np.maximum.accumulate(c); last = {"pattern": -10**9, "control": -10**9}
        for j in sw:
            i = j + 2
            if i >= n - 1 or i - W < 1: continue
            prior = cm[i - W - 1]; js = [s for s in sw if i - W <= s <= j]
            if len(js) < 3 or prior <= 0 or c[i] < l[j]: continue
            bowl, arm, rise, bottom = shape(l, js, i)
            conv, accel, runlen = rising(l, js)
            kind = "pattern" if conv else "control"
            if i - last[kind] < W: continue
            last[kind] = i
            tc = t[i] + tf * 60; S = sp.get(int(tc // 3600 * 3600 - 3600))
            if not S or c[i] <= 0: continue
            rec = dict(asset=asset, expiry=expiry, tf=tf, typ=typ, K=K, t=int(tc), tte_h=(settle - tc) / 3600, prem=c[i],
                       spot=S, bottom=bottom, decay=bottom / prior, rise=rise, bowl=bowl, arm=arm, accel=accel, runlen=runlen, kind=kind,
                       peak=h[i+1:].max() / c[i])
            if kind == "pattern":                                     # neighbours further OTM, same bar
                ks = sorted(k for (ty, k) in C if ty == typ)
                ks = [k for k in ks if k > K] if typ == "C" else [k for k in ks[::-1] if k < K]
                for s, k2 in enumerate(ks[:3], 1):
                    b = C[(typ, k2)]; ix = np.searchsorted(b[:, 0], t[i])
                    if ix < len(b) - 1 and b[ix, 0] == t[i] and b[ix, 3] > 0:
                        sw2 = [q for q in range(max(2, ix - W), ix - 1) if q + 2 < len(b) and b[q, 2] == b[q-2:q+3, 2].min()]
                        sh = (rising(b[:, 2], sw2)[0], False) if len(sw2) >= 3 else (False, False)
                        rec[f"n{s}_prem"] = b[ix, 3]; rec[f"n{s}_peak"] = b[ix+1:, 1].max() / b[ix, 3]
                        rec[f"n{s}_shape"] = bool(sh[0] or sh[1])
            out.append(rec)
    return out

def run(since="2024-01-01", tfs=TFS):
    jobs = []
    for asset in ("BTC", "ETH"):
        for e in sorted(os.listdir(f"data/candles/{asset}")):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) or e < since: continue
            if pd.Timestamp(e) + pd.Timedelta(hours=12) > pd.Timestamp.utcnow().tz_localize(None): continue   # settled only
            for tf in tfs:
                if os.path.isdir(f"data/candles/{asset}/{e}/{tf}"): jobs.append((asset, e, tf))
    out = []; _init()
    with ProcessPoolExecutor(4, initializer=_init) as ex:
        for k, r in enumerate(ex.map(scan, jobs, chunksize=4)):
            out += r
            if k % 500 == 0: print(k, len(jobs), len(out), flush=True)
    return pd.DataFrame(out)

if __name__ == "__main__":
    if "--one" in sys.argv:
        _init(); R = pd.DataFrame(scan(("BTC", sys.argv[2], int(sys.argv[3]))))
        print(R.kind.value_counts().to_dict()); print(R[R.kind == "pattern"].head(8).round(2).to_string()); sys.exit()
    R = run(); R.to_parquet("data/premium_base4.parquet"); print(R.groupby(["tf", "kind"]).size())
