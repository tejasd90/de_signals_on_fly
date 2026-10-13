"""Volatility-regime cycles on the option premium (his 13 Oct 2026 NIFTY 22600CE example).

His description: high volatility at a high price, then a QUIET DECAY, then a spike followed by high
volatility again (smaller in points because the price is lower), then quiet decay, and so on; the last
quiet decay finally gives ~15x. Idea only: the more quiet-decay -> spike cycles a contract has already
been through, the likelier the NEXT quiet decay ends in a big move. No time-to-expiry, strike or
cheapness restriction; every timeframe in TFS.

Per contract and timeframe, using only bars up to i:
  size_i   = mean |log return| over the last W bars (candle activity, in % so a lower price is fair)
  quiet_i  = size_i in the lowest third of the contract's own sizes so far AND close below close W bars ago
  phase    = a run of >= Q consecutive quiet bars; the EVENT is the bar the run reaches Q (one per phase)
  cycle    = a phase followed, within Q bars of its last quiet bar, by a spike bar: log return
             >= max(3 x the phase's size, log 1.3)
Each event records how many cycles were COMPLETED before it (0, 1, 2, 3+). Outcome: the highest later
high (to settlement) / the event bar's close. The 0-cycle quiet decays are the control."""
import json, os, re, sys, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
TFS = (15, 60, 240); W = 8; Q = 4

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

def events(c):
    """(bar index, prior completed cycles) for each quiet-decay phase in close series c."""
    r = np.diff(np.log(np.maximum(c, 1e-9)), prepend=np.nan)
    size = pd.Series(np.abs(r)).rolling(W).mean().to_numpy()
    out, run, cycles, pend = [], 0, 0, None          # pend = (last quiet bar, phase size) awaiting a spike
    for i in range(3 * W, len(c)):
        hist = size[W:i + 1]; hist = hist[~np.isnan(hist)]
        quiet = len(hist) >= 2 * W and size[i] <= np.quantile(hist, 1 / 3) and c[i] < c[i - W]
        if pend and i - pend[0] <= Q and r[i] >= max(3 * pend[1], np.log(1.3)):
            cycles += 1; pend = None
        elif pend and i - pend[0] > Q: pend = None
        if quiet:
            run += 1
            if run == Q: out.append((i, cycles))
            if run >= Q: pend = (i, size[i])
        else: run = 0
    return out

def scan(args):
    asset, expiry, tf = args
    d = f"data/candles/{asset}/{expiry}/{tf}"
    settle = pd.Timestamp(expiry).timestamp() + 43200; sp = SPOT[asset]; out = []
    for fn in os.listdir(d):
        m = SYM.match(fn)
        if not m: continue
        try: rows = json.load(open(f"{d}/{fn}"))
        except Exception: continue
        a = np.array([[r[0], r[2], r[4]] for r in rows if r[4] is not None and r[0] + tf * 60 <= settle], float)
        if len(a) < 4 * W: continue
        t, h, c = a.T
        for i, k in events(c):
            if i >= len(c) - 1 or c[i] <= 0: continue
            tc = t[i] + tf * 60; S = sp.get(int(tc // 3600 * 3600 - 3600))
            if not S: continue
            out.append(dict(asset=asset, expiry=expiry, tf=tf, typ=m.group(1), K=float(m.group(3)), t=int(tc),
                            tte_h=(settle - tc) / 3600, prem_pct=100 * c[i] / S, cycles=k, peak=h[i + 1:].max() / c[i]))
    return out

def run(since="2024-01-01"):
    jobs = []
    for asset in ("BTC", "ETH"):
        for e in sorted(os.listdir(f"data/candles/{asset}")):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) or e < since: continue
            if pd.Timestamp(e) + pd.Timedelta(hours=12) > pd.Timestamp.utcnow().tz_localize(None): continue
            for tf in TFS:
                if os.path.isdir(f"data/candles/{asset}/{e}/{tf}"): jobs.append((asset, e, tf))
    out = []; _init()
    with ProcessPoolExecutor(4, initializer=_init) as ex:
        for k, r in enumerate(ex.map(scan, jobs, chunksize=4)):
            out += r
            if k % 500 == 0: print(k, len(jobs), len(out), flush=True)
    return pd.DataFrame(out)

def evaluate(R):
    R = R.copy(); R["cyc"] = R.cycles.clip(upper=3)
    R["tteb"] = pd.cut(R.tte_h, [0, 6, 24, 72, 1e9]); R["premb"] = pd.qcut(np.log(R.prem_pct), 5, labels=False)
    for T in (5, 10, 25): R[f"h{T}"] = R.peak >= T
    print(f"events {len(R):,}  by cycles {R.cyc.value_counts().sort_index().to_dict()}\n")
    print("Raw hit rates by prior cycles:"); print(R.groupby("cyc")[["h5", "h10", "h25"]].mean().map("{:.2%}".format).to_string())
    # matched: compare each cycles>=1 level to 0 within tf x type x tte x premium strata, weighted by the pattern counts
    rng = np.random.default_rng(0); exps = R.expiry.unique()
    def diff(D, lev, T):
        s = D.groupby(["tf", "typ", "tteb", "premb", "cyc"], observed=True)[f"h{T}"].agg(["mean", "size"]).unstack("cyc")
        s = s.dropna(subset=[("mean", 0), ("mean", lev)])
        w = s[("size", lev)]; return float(((s[("mean", lev)] - s[("mean", 0)]) * w).sum() / w.sum()), float(s[("mean", 0)].mul(w).sum() / w.sum())
    print("\nMatched vs 0-cycle quiet decays (same tf, call/put, tte bucket, premium quintile); 90% CI by expiry bootstrap:")
    for T in (10, 25):
        for lev in (1, 2, 3):
            d0, base = diff(R, lev, T); bs = []
            for _ in range(200):
                D = R.set_index("expiry").loc[rng.choice(exps, len(exps))].reset_index()
                bs.append(diff(D, lev, T)[0])
            lo, hi = np.percentile(bs, [5, 95])
            print(f"  >= {T}x  cycles {'3+' if lev == 3 else lev}: {base + d0:.2%} vs control {base:.2%}  diff {d0:+.2%}  CI [{lo:+.2%}, {hi:+.2%}]")
    print("\nBy timeframe, >=10x (cycles 2+ vs 0, raw):")
    print(R.assign(g=np.where(R.cyc >= 2, "2+", np.where(R.cyc == 0, "0", "1"))).pivot_table("h10", "tf", "g").map("{:.2%}".format).to_string())

if __name__ == "__main__":
    if "--eval" in sys.argv: evaluate(pd.read_parquet("data/regime_cycles.parquet")); sys.exit()
    R = run(); R.to_parquet("data/regime_cycles.parquet"); print(len(R)); evaluate(R)
