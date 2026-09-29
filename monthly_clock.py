"""
MONTHLY-expiry crypto options: the instrument class this project never examined.

His Nifty/BankNifty Sep screenshots show a setup that needs a long-dated contract:
break the trendline, let the market drift for weeks, and collect the payoff in
expiry week when gamma is enormous. A 57000 PE ran ~500 -> 3100 at the end.

Every previous result here sits on Delta's 2-day contracts -- 96.8% of expiries by
count -- so the monthlies (3.2%, 38-day life, last Friday of the month) were
drowned out. They are exactly the instrument his setup requires.

Two questions, and the second is the one that decides whether it is tradeable:

  1. WHEN does the lifetime peak land? If his reading is right, peaks cluster in
     the final days. This is a composition question, immune to the small-denominator
     objection -- it asks where in the contract's own life the high occurred.

  2. Does buying EARLY and holding actually pay? Ratio flatters late entries
     because the denominator shrinks. Expectancy does not. Report EV of holding
     to settlement, net of COST, bucketed by days-to-expiry at entry.

A pattern can be real in (1) and still lose money in (2). That is the usual fate
of "buy cheap OTM and wait".
"""
import json, os, re, glob, sys
import numpy as np
from datetime import datetime, timezone

COST = 0.0826
RES = "60"
MIN_PREM = 0.05
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
MIN_LIFE_D = 21          # monthly class

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

def collect():
    peaks, entries = [], []
    for asset in ("BTC", "ETH"):
        spot = load_spot(asset)
        if not spot: continue
        for day in sorted(d for d in os.listdir(f"data/candles/{asset}") if not d.startswith(".")):
            dd = f"data/candles/{asset}/{day}/{RES}"
            if not os.path.isdir(dd): continue
            fns = [f for f in os.listdir(dd) if SYM.match(f)]
            if not fns: continue
            # monthly? probe one contract
            try: probe = json.load(open(os.path.join(dd, fns[0])))
            except Exception: continue
            if len(probe) < 2: continue
            if (probe[-1][0] - probe[0][0]) / 86400.0 < MIN_LIFE_D: continue
            for fn in fns:
                m = SYM.match(fn); typ, _, strike, _ = m.groups(); strike = float(strike)
                try: rows = json.load(open(os.path.join(dd, fn)))
                except Exception: continue
                if len(rows) < 48: continue
                ts = np.array([int(r[0]) for r in rows])
                hi = np.array([np.nan if r[2] is None else float(r[2]) for r in rows])
                cl = np.array([np.nan if r[4] is None else float(r[4]) for r in rows])
                if np.isnan(cl).all(): continue
                exp_ts, settle = ts[-1], cl[-1]
                if not np.isfinite(settle): continue
                life_d = (exp_ts - ts[0]) / 86400.0

                # (1) where in life is the lifetime peak?
                if np.isfinite(hi).any():
                    k = int(np.nanargmax(hi))
                    peaks.append((asset, day, typ, (exp_ts - ts[k]) / 86400.0, life_d))

                # (2) entries, hourly, held to settlement
                fut = np.full(len(hi), np.nan); run = -np.inf
                for k in range(len(hi) - 1, -1, -1):
                    fut[k] = run
                    if np.isfinite(hi[k]) and hi[k] > run: run = hi[k]
                for i in range(0, len(cl) - 1, 6):        # every 6h
                    e = cl[i]
                    if not np.isfinite(e) or e < MIN_PREM: continue
                    sp = spot.get(int(ts[i]))
                    if sp is None: continue
                    otm = (sp - strike) / sp * 100 if typ == "P" else (strike - sp) / sp * 100
                    dte = (exp_ts - ts[i]) / 86400.0
                    if dte <= 0 or not np.isfinite(fut[i]): continue
                    entries.append((week_of(int(ts[i])), dte, otm, typ, fut[i] / e, settle / e))
    return peaks, entries

DTE_BINS  = [0, 1, 3, 7, 14, 21, 1e9]
DTE_NAMES = ["<1d", "1-3d", "3-7d", "7-14d", "14-21d", "21d+"]

def main():
    peaks, entries = collect()
    print(f"monthly contracts: {len(peaks):,}   entry points: {len(entries):,}")
    if not peaks: return

    print("\n--- (1) WHERE THE LIFETIME PEAK LANDS ---")
    pd_ = np.array([p[3] for p in peaks]); life = np.array([p[4] for p in peaks])
    frac = 1 - pd_ / life                      # 0 = start of life, 1 = expiry
    print(f"days-to-expiry at peak: median {np.median(pd_):.1f}   p25 {np.percentile(pd_,25):.1f}   p75 {np.percentile(pd_,75):.1f}")
    print(f"peak position in life (0=listing, 1=expiry): median {np.median(frac):.3f}")
    print("  if peaks were uniform over life, median would be 0.500")
    for lo, hi, nm in ((0,1,"final day"),(0,3,"final 3 days"),(0,7,"final week"),(7,1e9,"earlier than a week out")):
        print(f"  peak in {nm:<24} {((pd_>=lo)&(pd_<hi)).mean()*100:5.1f}%"
              + (f"   (uniform would give {min(hi,38)/38*100:4.1f}%)" if hi<1e9 else ""))

    print("\n--- (2) DOES BUYING EARLY PAY? held to settlement, net of cost ---")
    wk  = np.array([e[0] for e in entries]); dte = np.array([e[1] for e in entries])
    otm = np.array([e[2] for e in entries]); pkr = np.array([e[4] for e in entries])
    ev  = np.array([e[5] for e in entries]) - 1 - COST
    rng = np.random.default_rng(5)
    for label, sel in (("all strikes", np.ones(len(ev), bool)),
                       ("OTM 2-15%", (otm >= 2) & (otm <= 15)),
                       ("deep OTM >15%", otm > 15)):
        print(f"\n  [{label}]  n={sel.sum():,}")
        print(f"  {'entered at':<12}{'n':>8}{'medPeakX':>10}{'P>=10x':>9}{'EV/trade':>10}{'P(EV>0)':>10}{'win%':>8}")
        idx = np.digitize(dte, DTE_BINS) - 1
        for b, nm in enumerate(DTE_NAMES):
            s = sel & (idx == b)
            if s.sum() < 40: continue
            e_, w_ = ev[s], wk[s]; uw = np.unique(w_)
            boot = np.array([np.concatenate([e_[w_ == u] for u in rng.choice(uw, len(uw), True)]).mean()
                             for _ in range(1500)]) if len(uw) > 1 else np.array([e_.mean()])
            print(f"  {nm:<12}{s.sum():>8,}{np.median(pkr[s]):>10.2f}{(pkr[s]>=10).mean()*100:>8.2f}%"
                  f"{e_.mean():>10.4f}{(boot>0).mean():>10.3f}{(ev[s]>0).mean()*100:>7.1f}%")

if __name__ == "__main__":
    main()
