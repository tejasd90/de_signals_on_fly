"""
Where in an option's LIFE does the payoff actually land?

His claim, from the Nifty/BankNifty Sep charts: the market broke the trendline
weeks earlier, drifted, and the premium only exploded near monthly expiry. A
57000 PE went ~500 -> 3100 in two days at the end.

Two readings, and they have opposite trading implications:
  (a) REAL TIMING -- the move itself waits for expiry week.
  (b) GAMMA ARITHMETIC -- near expiry the premium is tiny, so the same spot move
      divides by a smaller number and prints a bigger ratio. Nothing about the
      market waited; the denominator shrank.

(a) says buy early and sit. (b) says buying early is exactly how you bleed, and
the ratio you admire is unreachable because it is paid on a lottery ticket that
usually expires worthless. Ratio cannot tell them apart. EV can.

So report BOTH: the ratio (what the chart shows) and the expectancy of actually
holding the thing (what the account shows), bucketed by hours-to-expiry at entry.

Cost model: COST=0.0826 of premium, round trip incl GST (project standard).
Unit of independence: the WEEK (project standard).
"""
import json, glob, os, re, sys
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone

COST = 0.0826
RES = "15"
STEP = 4                      # sample an entry each hour, limit overlap
MIN_PREM = 0.05               # ignore dust quotes; below this the ratio is noise
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")

HTE_BINS  = [0, 2, 6, 12, 24, 48, 1e9]
HTE_NAMES = ["0-2h", "2-6h", "6-12h", "12-24h", "24-48h", "48h+"]
OTM_BINS  = [-1e9, 0, 2, 5, 10, 1e9]
OTM_NAMES = ["ITM", "0-2% OTM", "2-5% OTM", "5-10% OTM", ">10% OTM"]

def load_spot(asset):
    """ts -> close, 15m."""
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

def scan(asset):
    spot = load_spot(asset)
    if not spot:
        print(f"{asset}: no spot", file=sys.stderr); return None
    recs = []
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
            if len(rows) < 8: continue
            ts = np.array([int(r[0]) for r in rows])
            hi = np.array([np.nan if r[2] is None else float(r[2]) for r in rows])
            cl = np.array([np.nan if r[4] is None else float(r[4]) for r in rows])
            if np.isnan(cl).all(): continue
            exp_ts = ts[-1]
            settle = cl[-1]
            if not np.isfinite(settle): continue
            # running max of FUTURE highs -- peak reachable after each entry
            fut = np.full(len(hi), np.nan)
            run = -np.inf
            for k in range(len(hi) - 1, -1, -1):
                fut[k] = run
                if np.isfinite(hi[k]) and hi[k] > run: run = hi[k]
            for i in range(0, len(cl) - 1, STEP):
                e = cl[i]
                if not np.isfinite(e) or e < MIN_PREM: continue
                sp = spot.get(int(ts[i]))
                if sp is None: continue
                otm = (sp - strike) / sp * 100 if typ == "P" else (strike - sp) / sp * 100
                hte = (exp_ts - ts[i]) / 3600.0
                if hte <= 0: continue
                pk = fut[i]
                if not np.isfinite(pk): continue
                recs.append((week_of(int(ts[i])), hte, otm, pk / e, settle / e))
    return recs

def summarise(recs, title, otm_filter=None):
    if otm_filter:
        lo, hi = otm_filter
        recs = [r for r in recs if lo <= r[2] < hi]
    if not recs:
        print(f"\n{title}: empty"); return
    wk  = np.array([r[0] for r in recs])
    hte = np.array([r[1] for r in recs]); otm = np.array([r[2] for r in recs])
    pkr = np.array([r[3] for r in recs]); str_= np.array([r[4] for r in recs])
    ev  = str_ - 1 - COST                      # hold to settlement, net of cost
    print(f"\n{title}   n={len(recs):,}  weeks={len(set(wk))}")
    print(f"{'bucket':<10}{'n':>9}{'medRatio':>10}{'P>=10x':>9}{'P>=100x':>9}"
          f"{'EV/trade':>10}{'P(EV>0)':>9}{'winrate':>9}")
    idx = np.digitize(hte, HTE_BINS) - 1
    rng = np.random.default_rng(7)
    for b, name in enumerate(HTE_NAMES):
        s = idx == b
        if s.sum() < 50: continue
        e = ev[s]; w = wk[s]
        uw = np.unique(w)
        boot = []
        for _ in range(2000):
            pick = rng.choice(uw, len(uw), replace=True)
            vals = np.concatenate([e[w == u] for u in pick])
            boot.append(vals.mean())
        boot = np.array(boot)
        print(f"{name:<10}{s.sum():>9,}{np.median(pkr[s]):>10.2f}"
              f"{(pkr[s]>=10).mean()*100:>8.2f}%{(pkr[s]>=100).mean()*100:>8.3f}%"
              f"{e.mean():>10.4f}{(boot>0).mean():>9.3f}{(str_[s]>1+COST).mean()*100:>8.1f}%")

if __name__ == "__main__":
    allr = []
    for a in ("BTC", "ETH"):
        r = scan(a)
        if r:
            print(f"{a}: {len(r):,} entry points", file=sys.stderr)
            summarise(r, f"=== {a} : all strikes ===")
            allr += r
    summarise(allr, "=== BTC+ETH : 5-10% OTM (his 'cheap OTM' zone) ===", (5, 10))
    summarise(allr, "=== BTC+ETH : >10% OTM (deep, lottery zone) ===", (10, 1e9))
