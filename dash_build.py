"""Precompute the 1:100 required-move grids for the dashboard.

Layout of the source store is what makes this tractable:
  data/candles/<ASSET>/<EXPIRY-DATE>/<RES>/<SYMBOL>.json
with the day-directory being the EXPIRY and each file holding one contract's
entire life. So an expiry can be loaded as a single (time x strike) grid and the
whole required-move calculation vectorised over it.

Cached per (asset, expiry, resolution) in data/dashreq/, so this is resumable and
incremental: re-running only touches expiries whose source files are newer than
their cache. The first full pass is the expensive one, as agreed.
"""
import json, os, re, sys, glob, time
import numpy as np, pandas as pd
from optreq import required_moves

SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
OUT = "data/dashreq"
RESOLUTIONS = ("15", "60", "240", "1440")
ASSETS = ("BTC", "ETH")

def spot_map(asset, res):
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/{res}/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def load_expiry(asset, expiry, res):
    """-> (ts array, strikes, call grid, put grid)"""
    d = f"data/candles/{asset}/{expiry}/{res}"
    if not os.path.isdir(d): return None
    C, P = {}, {}
    for fn in os.listdir(d):
        m = SYM.match(fn)
        if not m: continue
        typ, _, k, _ = m.groups(); k = float(k)
        try: rows = json.load(open(os.path.join(d, fn)))
        except Exception: continue
        s = pd.Series({int(r[0]): (np.nan if r[4] is None else float(r[4])) for r in rows})
        (C if typ == "C" else P)[k] = s
    if not C and not P: return None
    ks = sorted(set(C) | set(P))
    idx = sorted(set().union(*[set(s.index) for s in list(C.values())+list(P.values())]))
    cg = pd.DataFrame({k: C.get(k, pd.Series(dtype=float)) for k in ks}, index=idx)
    pg = pd.DataFrame({k: P.get(k, pd.Series(dtype=float)) for k in ks}, index=idx)
    return np.array(idx), np.array(ks, float), cg.to_numpy(), pg.to_numpy()

def build_expiry(asset, expiry, res, spot):
    L = load_expiry(asset, expiry, res)
    if L is None: return None
    ts, ks, cg, pg = L
    S = np.array([spot.get(int(t), np.nan) for t in ts])
    exp_ts = pd.Timestamp(expiry).timestamp() + 12*3600   # settlement, not the last stored bar
    # Prices are the bar's CLOSE, so time-to-expiry is measured from the close too. It was
    # from the open, which gave every row one extra bar of time value (4h on 4h bars) and
    # biased the implied vol behind the "now" column low. The bar that closes AT settlement
    # has no time left, so it drops out and the next expiry becomes "immediate" there.
    tte = (exp_ts - (ts + int(res)*60)) / (365.0*86400.0)
    ok = np.isfinite(S) & (tte > 0)
    if ok.sum() < 3: return None
    ts, S, tte, cg, pg = ts[ok], S[ok], tte[ok], cg[ok], pg[ok]
    cme, cmn, cke, ckn = required_moves(cg, ks, S, tte, call=True)
    pme, pmn, pke, pkn = required_moves(pg, ks, S, tte, call=False)
    return pd.DataFrame(dict(ts=ts, spot=S, tte_d=tte*365.0,
                             c_exp=cme, c_now=cmn, c_k_exp=cke, c_k_now=ckn,
                             p_exp=pme, p_now=pmn, p_k_exp=pke, p_k_now=pkn))

def newest_source(asset, expiry, res):
    d = f"data/candles/{asset}/{expiry}/{res}"
    if not os.path.isdir(d): return 0
    try: return max(os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)) 
    except ValueError: return 0

def run(assets=ASSETS, resolutions=RESOLUTIONS, limit=None, force_since=None):
    os.makedirs(OUT, exist_ok=True)
    for asset in assets:
        base = f"data/candles/{asset}"
        if not os.path.isdir(base): continue
        exps = sorted(d for d in os.listdir(base) if not d.startswith("."))
        if limit: exps = exps[-limit:]
        for res in resolutions:
            t0 = time.time(); built = skipped = 0
            for e in exps:
                cp = f"{OUT}/{asset}_{res}_{e}.parquet"
                # the cache key is the OPTION files' mtime; spot changes are invisible to it,
                # so a spot repair needs --force-since
                forced = force_since is not None and e >= force_since
                if not forced and os.path.exists(cp) and os.path.getmtime(cp) >= newest_source(asset, e, res):
                    skipped += 1; continue
                if not built: spot = spot_map(asset, res)     # load lazily, once
                df = build_expiry(asset, e, res, spot)
                if df is not None and len(df): df.to_parquet(cp)
                built += 1
                if built % 50 == 0:
                    print(f"  {asset}/{res}: {built} built, {skipped} cached, "
                          f"{time.time()-t0:.0f}s", file=sys.stderr, flush=True)
            print(f"{asset}/{res}: built {built}, cached {skipped}, {time.time()-t0:.0f}s",
                  file=sys.stderr, flush=True)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default=None, help="comma list, default all")
    ap.add_argument("--assets", default=None)
    ap.add_argument("--limit", type=int, default=None, help="only the N most recent expiries")
    ap.add_argument("--force-since", default=None, help="rebuild expiries on/after YYYY-MM-DD even if cached")
    a = ap.parse_args()
    run(assets=tuple(a.assets.split(",")) if a.assets else ASSETS,
        resolutions=tuple(a.res.split(",")) if a.res else RESOLUTIONS,
        limit=a.limit, force_since=a.force_since)
