"""AUC is not money. Convert the price-action score into expectancy.

pascore survives per-asset replication, a weekly-block shuffle control, and adds
to line-age >= 100d (0.586 -> 0.627 held-out). But the standing instruction in
this project is to report EXPECTANCY, not AUC -- a 0.60 AUC can be worth nothing
once the option's cost is paid, and "high win rate, negative expectancy" has
already been the outcome of several arms here.

So: build per-DAY option expectancy over the whole population (not just the
multibagger winners, which would be a selection oracle), join it to the held-out
score, and ask whether the score's top quintile actually pays after COST=0.0826.
"""
import json, os, re, glob, sys
import numpy as np, pandas as pd
from datetime import datetime, timezone

COST = 0.0826
RES = "60"
# DUST FLOOR, scaled to spot. The first version used an absolute 0.05, which on
# ETH at ~$2,300 is dust: such a mark settling at $17 prints 340x that nobody
# could trade at size. ETH 2024-02-05 (13 contracts, ALL >=10x, median peak 357x)
# alone supplied 53% of the summed EV across 1,943 days.
MIN_PREM_FRAC = 0.0005          # premium must be >= 0.05% of spot
CAP = 10.0                      # realistic take-profit; you do not ride a mark to 1400x
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
OUT = "data/day_option_ev2.parquet"

def load_spot(a):
    m = {}
    for p in glob.glob(f"data/spot_candles/{a}/{RES}/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def build():
    rec = []
    for asset in ("BTC", "ETH"):
        spot = load_spot(asset)
        if not spot: continue
        for day in sorted(d for d in os.listdir(f"data/candles/{asset}") if not d.startswith(".")):
            dd = f"data/candles/{asset}/{day}/{RES}"
            if not os.path.isdir(dd): continue
            for fn in os.listdir(dd):
                m = SYM.match(fn)
                if not m: continue
                typ, _, strike, _ = m.groups(); strike = float(strike)
                try: rr = json.load(open(os.path.join(dd, fn)))
                except Exception: continue
                if len(rr) < 6: continue
                ts = np.array([int(r[0]) for r in rr])
                hi = np.array([np.nan if r[2] is None else float(r[2]) for r in rr])
                cl = np.array([np.nan if r[4] is None else float(r[4]) for r in rr])
                if not np.isfinite(cl[-1]): continue
                settle = cl[-1]
                # running max of FUTURE highs, for a peak-exit upper bound
                fut = np.empty(len(hi)); run = -np.inf
                for k in range(len(hi)-1, -1, -1):
                    fut[k] = run
                    if np.isfinite(hi[k]) and hi[k] > run: run = hi[k]
                for i in range(0, len(cl)-1, 6):
                    e = cl[i]
                    if not np.isfinite(e): continue
                    sp = spot.get(int(ts[i]))
                    if sp is None or e < MIN_PREM_FRAC * sp: continue
                    otm = (sp-strike)/sp*100 if typ == "P" else (strike-sp)/sp*100
                    if not (2 <= otm <= 15): continue
                    if not np.isfinite(fut[i]): continue
                    # capped exit: sell at CAP x if ever touched, else settle.
                    # Fixed in advance, causal, and the same family of rule as
                    # monthly_exit.py's target-Nx.
                    ratio_cap = CAP if fut[i] >= e * CAP else settle / e
                    rec.append((asset,
                                datetime.fromtimestamp(int(ts[i]), tz=timezone.utc).strftime("%Y-%m-%d"),
                                typ, settle/e - 1 - COST, fut[i]/e,
                                ratio_cap - 1 - COST))
        print(f"{asset}: {len(rec):,}", file=sys.stderr)
    d = pd.DataFrame(rec, columns=["spot","day","typ","ev","peak","evcap"])
    # MEDIAN and share-positive alongside the mean. On a lottery payoff the sample
    # mean does not converge in 1,943 days -- which is precisely what "one day
    # supplies 53% of the total" means. The mean is kept only to show the damage.
    g = d.groupby(["spot","day"]).agg(ev=("ev","mean"), evmed=("ev","median"),
                                      evcap=("evcap","mean"), evcapmed=("evcap","median"),
                                      pos=("evcap", lambda s:(s>0).mean()),
                                      peak=("peak","median"),
                                      p10=("peak", lambda s:(s>=10).mean()), n=("ev","size"))
    g = g.reset_index(); g["day"] = pd.to_datetime(g.day)
    g.to_parquet(OUT); return g

if __name__ == "__main__":
    g = build() if not os.path.exists(OUT) else pd.read_parquet(OUT)
    print(f"day-option-EV rows: {len(g)}  span {g.day.min().date()} .. {g.day.max().date()}")
