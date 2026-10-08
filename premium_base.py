"""His PREMIUM-BASE pattern (journal entry 16, 9 Oct 2026; context C1 p17/p393/p258):
on the OPTION's own chart, a long decay toward zero, then a PARABOLA OF HIGHER LOWS (the premium
"holding up" and slowly rising), then the explosion. Examples: C-BTC-87000-021026 (2 Oct),
P-BTC-80500/81000-091026 (8 Oct).

Detector on 1h MARK option candles (data/candles/<asset>/<expiry>/60), causal at bar i:
  decay     the first swing low of the window <= DECAY x the highest close of the previous 10 days
  parabola  >= 3 swing lows in the last W bars (a swing low at j = lowest low within +-2 bars, so it is
            only KNOWN at j+2), each strictly HIGHER than the one before; a quadratic through them is
            convex or rising (a >= 0 or end-slope > 0) and the last low >= RISE x the first
  holding   close_i >= the last swing low
  time      >= MIN_TTE_H hours to settlement (12:00 UTC on the expiry date)
One EVENT per contract: the first bar the pattern completes.
Outcome: max high after bar i, to settlement, / close_i  (MARK; a traded check comes after).
CONTROL: first bar where the SAME decay and time conditions hold but there is NO higher-lows
parabola, for every contract that never formed one -- compared within time-to-expiry x moneyness cells.
"""
import json, os, re, sys, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
W, DECAY, RISE, MIN_TTE_H, CHEAP = 48, 0.15, 1.5, 12, 0.0025

def spot_series(asset):
    import glob
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)): m[int(r[0])] = float(r[4])
        except Exception: pass
    return m

def scan(args):
    """v2 (2026-10-09): the parabola as he SEES it -- a U-shaped curve of swing lows (convex fit,
    bottom already passed, >= 2 lows after the bottom all well above it), with a genuinely cheap
    bottom (<= DECAY x the 10-day high close AND <= CHEAP x spot). v1 demanded strictly rising lows,
    which missed his P-80500-091026 (lows 44 -> 31 -> 56 -> 52). A contract may fire again 24 bars
    after a previous event."""
    asset, expiry, fn = args
    m = SYM.match(fn)
    if not m: return []
    typ, K = m.group(1), float(m.group(3))
    try: rows = json.load(open(f"data/candles/{asset}/{expiry}/60/{fn}"))
    except Exception: return []
    a = np.array([[r[0], r[2], r[3], r[4]] for r in rows if r[4] is not None], float)
    if len(a) < W + 30: return []
    t, h, l, c = a[:, 0], a[:, 1], a[:, 2], a[:, 3]; n = len(c)
    settle = pd.Timestamp(expiry).timestamp() + 43200
    sp = SPOT[asset]
    swing = np.array([2 <= j < n - 2 and l[j] == l[j-2:j+3].min() for j in range(n)])
    out, last_ev, ctl_done = [], -10**9, False
    for i in range(W + 2, n - 1):
        tte_h = (settle - (t[i] + 3600)) / 3600
        if tte_h < MIN_TTE_H: break
        S = sp.get(int(t[i]))
        lo = max(0, i - W - 240)
        if not S or i - W <= lo: continue
        prior_max = c[lo:i - W].max()
        js = [j for j in range(i - W, i - 1) if swing[j]]                 # known by bar i
        if len(js) < 3 or prior_max <= 0: continue
        lows = l[js]; kb = int(np.argmin(lows)); bottom = lows[kb]
        cheap = bottom <= DECAY * prior_max and bottom <= CHEAP * S
        if not cheap: continue
        after = lows[kb + 1:]
        x = np.array(js, float) - js[0]; A, B, C0 = np.polyfit(x, lows, 2)
        # still a BASE, not the explosion already under way: close within 3x the bottom
        par = (A > 0 and len(after) >= 2 and after.min() >= RISE * bottom and c[i] >= after[-1] and c[i] <= 3 * bottom)
        fut = h[i+1:]
        rec = dict(asset=asset, expiry=expiry, typ=typ, K=K, t=int(t[i]) + 3600, tte_h=tte_h, prem=c[i], spot=S,
                   peak=(fut.max() / c[i]) if len(fut) and c[i] > 0 else np.nan, bottom=bottom, n_after=len(after))
        if par and i - last_ev >= 24:
            out.append({**rec, "kind": "pattern"}); last_ev = i
        elif not par and not ctl_done and len(after) == 0:              # cheap, still making new lows: no parabola
            out.append({**rec, "kind": "control"}); ctl_done = True
    return out

SPOT = {}
def _init():
    for a_ in ("BTC", "ETH"): SPOT[a_] = spot_series(a_)

def run(assets=("BTC", "ETH"), since="2024-01-01", only=None):
    jobs = []
    for asset in assets:
        for e in sorted(os.listdir(f"data/candles/{asset}")):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) or e < since: continue
            if pd.Timestamp(e) > pd.Timestamp.now() + pd.Timedelta(days=1): continue
            d = f"data/candles/{asset}/{e}/60"
            if not os.path.isdir(d): continue
            for fn in os.listdir(d):
                if fn.endswith(".json") and (only is None or fn[:-5] in only): jobs.append((asset, e, fn))
    out = []
    _init()
    with ProcessPoolExecutor(4, initializer=_init) as ex:
        for r in ex.map(scan, jobs, chunksize=200): out += r
    return pd.DataFrame(out)

if __name__ == "__main__":
    if "--examples" in sys.argv:
        R = run(only={"C-BTC-87000-021026", "P-BTC-80500-091026", "P-BTC-81000-091026", "P-BTC-80000-091026"})
        R["ist"] = pd.to_datetime(R.t, unit="s") + pd.Timedelta(hours=5.5)
        print(R[["expiry", "typ", "K", "kind", "ist", "tte_h", "prem", "bottom", "n_after", "peak"]].round(3).to_string(index=False)); sys.exit()
    R = run(); R.to_parquet("data/premium_base.parquet")
    print(R.kind.value_counts().to_dict())
