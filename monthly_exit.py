"""
The exit rule is the whole trade.

monthly_clock.py showed: monthly OTM options held TO SETTLEMENT lose in every
days-to-expiry bucket. But nobody holds a 6-bagger to settlement -- he would have
sold the 57000 PE at 3100. And P(peak>=10x) is 3.8-10.3% in those same buckets,
so the spikes are real. Hold-to-settle EV therefore measures the wrong trade.

The honest question: with an exit rule fixed IN ADVANCE -- no peak-picking, no
hindsight -- does the trade pay? Rules tested, all causal:

  target Nx   sell the instant premium first touches N x entry, else settle
  trail P%    sell when premium falls P% from its running max since entry
  timestop D  sell D days before expiry regardless

Entry is every 6h across the contract's life, so a "strategy" here is: buy this
strike at this moment, apply this rule, take what it gives. Weekly block bootstrap;
COST=0.0826 charged once on the round trip.
"""
import json, os, re, glob
import numpy as np
from datetime import datetime, timezone

COST = 0.0826
RES = "60"
MIN_PREM = 0.05
MIN_LIFE_D = 21
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")

def load_spot(a):
    m = {}
    for p in glob.glob(f"data/spot_candles/{a}/{RES}/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def week_of(ts):
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{d.isocalendar()[0]}W{d.isocalendar()[1]:02d}"

TARGETS = [2.0, 3.0, 5.0, 10.0]
TRAILS  = [0.30, 0.50]
TIMESTOPS = [7, 3]

def run():
    rows_out = []
    for asset in ("BTC", "ETH"):
        spot = load_spot(asset)
        if not spot: continue
        for day in sorted(d for d in os.listdir(f"data/candles/{asset}") if not d.startswith(".")):
            dd = f"data/candles/{asset}/{day}/{RES}"
            if not os.path.isdir(dd): continue
            fns = [f for f in os.listdir(dd) if SYM.match(f)]
            if not fns: continue
            try: probe = json.load(open(os.path.join(dd, fns[0])))
            except Exception: continue
            if len(probe) < 2 or (probe[-1][0]-probe[0][0])/86400.0 < MIN_LIFE_D: continue
            for fn in fns:
                m = SYM.match(fn); typ, _, strike, _ = m.groups(); strike = float(strike)
                try: rr = json.load(open(os.path.join(dd, fn)))
                except Exception: continue
                if len(rr) < 48: continue
                ts = np.array([int(r[0]) for r in rr])
                hi = np.array([np.nan if r[2] is None else float(r[2]) for r in rr])
                lo = np.array([np.nan if r[3] is None else float(r[3]) for r in rr])
                cl = np.array([np.nan if r[4] is None else float(r[4]) for r in rr])
                exp_ts = ts[-1]
                if not np.isfinite(cl[-1]): continue
                n = len(cl)
                for i in range(0, n-1, 6):
                    e = cl[i]
                    if not np.isfinite(e) or e < MIN_PREM: continue
                    sp = spot.get(int(ts[i]))
                    if sp is None: continue
                    otm = (sp-strike)/sp*100 if typ=="P" else (strike-sp)/sp*100
                    if not (2 <= otm <= 15): continue
                    dte = (exp_ts-ts[i])/86400.0
                    if not (7 <= dte <= 21): continue      # the only zone that was not clearly losing
                    H, L, C = hi[i+1:], lo[i+1:], cl[i+1:]
                    if len(C) < 2: continue
                    fin = C[-1] if np.isfinite(C[-1]) else e
                    res = {}
                    for t in TARGETS:
                        k = np.where(np.isfinite(H) & (H >= e*t))[0]
                        res[f"target{t:g}x"] = t if len(k) else fin/e
                    for p in TRAILS:
                        rm, out = e, None
                        for k in range(len(C)):
                            if np.isfinite(H[k]): rm = max(rm, H[k])
                            if np.isfinite(L[k]) and L[k] <= rm*(1-p):
                                out = max(rm*(1-p), L[k]); break
                        res[f"trail{int(p*100)}%"] = (out if out is not None else fin)/e
                    for d_ in TIMESTOPS:
                        k = np.where((exp_ts-ts[i+1:])/86400.0 <= d_)[0]
                        v = C[k[0]] if len(k) and np.isfinite(C[k[0]]) else fin
                        res[f"timestop{d_}d"] = v/e
                    res["hold"] = fin/e
                    rows_out.append((week_of(int(ts[i])), typ, res))
    return rows_out

def main():
    R = run()
    print(f"entries: {len(R):,}   (monthly, OTM 2-15%, 7-21d to expiry)")
    if not R: return
    wk = np.array([r[0] for r in R]); ty = np.array([r[1] for r in R])
    keys = list(R[0][2].keys())
    rng = np.random.default_rng(13)
    for label, sel in (("ALL", np.ones(len(R), bool)),
                       ("PUTS", ty == "P"), ("CALLS", ty == "C")):
        print(f"\n[{label}]  n={sel.sum():,}")
        print(f"  {'rule':<12}{'EV/trade':>10}{'P(EV>0)':>10}{'win%':>8}{'medX':>8}{'p95X':>8}")
        w_ = wk[sel]; uw = np.unique(w_)
        for k in keys:
            x = np.array([r[2][k] for r in R])[sel]
            ev = x - 1 - COST
            boot = np.array([np.concatenate([ev[w_ == u] for u in rng.choice(uw, len(uw), True)]).mean()
                             for _ in range(1500)])
            print(f"  {k:<12}{ev.mean():>10.4f}{(boot>0).mean():>10.3f}"
                  f"{(ev>0).mean()*100:>7.1f}%{np.median(x):>8.2f}{np.percentile(x,95):>8.2f}")

if __name__ == "__main__":
    main()
