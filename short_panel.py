"""The option-SELLER panel: every strike, every 4h, held to expiry.

Everything before this scored the BUYER. The seller is the same trade with the
sign flipped, so seller P&L = premium - payoff, minus costs the buyer did not
see the same way: the seller fills at the BID (stored candles are MARK), and
fees are charged on notional, capped at 3.5% of premium.

Rows: asset, expiry, typ, K, entry_t, S0, prem (mark, USD per 1 coin), tte_h,
S_T, payoff. All in USD per 1 coin, the same units as (K - S), so no contract
multiplier enters.

Settlement is 12:00 UTC on the expiry date; S_T is the close of the spot bar
ending then. spot_candles is the perp MARK ([[spot-is-mark]]), close enough to
the settlement index for a hold-to-expiry payoff.

Also writes data/spread_snapshot.csv: live bid/ask for every BTC/ETH option, so
the bid-side haircut is measured rather than assumed. One snapshot per run; run
it again at other hours to see whether the spread is time-of-day dependent.
"""
import json, os, re, glob, sys, time, urllib.request
import numpy as np, pandas as pd

SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
STEP_H, MAX_TTE_H = 4, 8 * 24

def spot_series(asset):
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try: rows = json.load(open(p))
        except Exception: continue
        for r in rows:
            if r[4] is not None: m[int(r[0])] = float(r[4])
    return m

def panel(asset):
    spot = spot_series(asset)
    out = []
    base = f"data/candles/{asset}"
    for e in sorted(os.listdir(base)):
        d = f"{base}/{e}/60"
        if not os.path.isdir(d): continue
        exp_t = int(pd.Timestamp(e).timestamp()) + 12 * 3600
        ST = spot.get(exp_t - 3600)
        if ST is None: continue                      # unsettled or spot gap
        for fn in os.listdir(d):
            m = SYM.match(fn)
            if not m: continue
            typ, K = m.group(1), float(m.group(3))
            try: rows = json.load(open(os.path.join(d, fn)))
            except Exception: continue
            for r in rows:
                t = int(r[0]) + 3600                 # bar close time = entry time
                if r[4] is None or t % (STEP_H * 3600): continue
                tte = (exp_t - t) / 3600
                if not (0 < tte <= MAX_TTE_H): continue
                S0 = spot.get(int(r[0]))
                if S0 is None: continue
                pay = max(ST - K, 0) if typ == "C" else max(K - ST, 0)
                out.append((asset, e, typ, K, t, S0, float(r[4]), tte, ST, pay))
    return pd.DataFrame(out, columns=["asset","expiry","typ","K","entry_t","S0",
                                      "prem","tte_h","S_T","payoff"])

def spread_snapshot():
    u = "https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options"
    res = json.load(urllib.request.urlopen(u, timeout=30))["result"]
    now = time.time(); rows = []
    for x in res:
        p = x["symbol"].split("-")
        if p[1] not in ("BTC", "ETH"): continue
        q = x.get("quotes") or {}
        try:
            bid, ask = float(q.get("best_bid") or 0), float(q.get("best_ask") or 0)
            mark, S, K = float(x["mark_price"]), float(x["spot_price"]), float(p[2])
        except Exception: continue
        exp = pd.Timestamp(pd.to_datetime(p[3], format="%d%m%y")).timestamp() + 12*3600
        rows.append(dict(t=int(now), asset=p[1], typ=p[0], K=K, S=S, mark=mark,
                         bid=bid, ask=ask, tte_h=(exp-now)/3600))
    df = pd.DataFrame(rows)
    fp = "data/spread_snapshot.csv"
    df.to_csv(fp, mode="a", header=not os.path.exists(fp), index=False)
    return df

if __name__ == "__main__":
    s = spread_snapshot(); print(f"spread snapshot: {len(s)} quotes", flush=True)
    parts = []
    for a in ("BTC", "ETH"):
        t0 = time.time(); df = panel(a); parts.append(df)
        print(f"{a}: {len(df):,} rows, {df.expiry.nunique()} expiries, {time.time()-t0:.0f}s", flush=True)
    P = pd.concat(parts, ignore_index=True)
    for c in ("K","S0","prem","tte_h","S_T","payoff"): P[c] = P[c].astype("float32")
    P.to_parquet("data/short_panel.parquet")
    print(f"wrote data/short_panel.parquet {len(P):,} rows")
