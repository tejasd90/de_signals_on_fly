"""Backfill the option-candle store so history meets live.

The store ends 2026-09-16 while spot runs to today, leaving a two-week hole in
which the dashboard's middle pane has nothing to show. Both halves of the fix are
available from the API: expired contracts still serve candles, and
/v2/products?states=expired lists what existed.

Writes into the existing layout exactly -- data/candles/<ASSET>/<EXPIRY>/<RES>/<SYMBOL>.json,
a list of [ts,o,h,l,c,volume] -- so nothing downstream changes.

NOTE the API returns rows OUTSIDE a contract's life (flat last price, volume 0)
for already-expired symbols, so bars after settlement are dropped; otherwise a
dead contract would look like it still had a quote.
"""
import json, os, sys, time, urllib.request, urllib.error
import datetime as dt

BASE = "https://api.india.delta.exchange/v2"
API_RES = {"15": "15m", "60": "1h", "240": "4h", "1440": "1d"}
ASSETS = ("BTC", "ETH")

def get(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(2*(k+1)); continue
            return None
        except Exception:
            time.sleep(1+k)
    return None

def products():
    out = []
    for state in ("live", "expired"):
        page = None
        while True:
            u = f"{BASE}/products?states={state}&contract_types=call_options,put_options&page_size=200"
            if page: u += f"&after={page}"
            d = get(u)
            if not d: break
            res = d.get("result") or []
            out += res
            page = (d.get("meta") or {}).get("after")
            if not page or not res: break
    return out

def fetch(sym, res, a, b):
    d = get(f"{BASE}/history/candles?symbol={sym}&resolution={API_RES[res]}&start={int(a)}&end={int(b)}")
    return (d or {}).get("result") or []

def main(since_days=30, resolutions=("15","60","240","1440")):
    prods = products()
    print(f"products listed: {len(prods)}", flush=True)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    todo = []
    for p in prods:
        sym = p.get("symbol") or ""
        parts = sym.split("-")
        if len(parts) != 4 or parts[1] not in ASSETS: continue
        st = p.get("settlement_time")
        if not st: continue
        try: settle = dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
        except Exception: continue
        if settle < cutoff: continue
        todo.append((parts[1], settle, sym))
    print(f"contracts in the last {since_days}d: {len(todo)}", flush=True)
    n_new = 0
    for i, (asset, settle, sym) in enumerate(sorted(todo, key=lambda x: x[1])):
        expdir = settle.date().isoformat()
        for res in resolutions:
            d = f"data/candles/{asset}/{expdir}/{res}"
            fp = os.path.join(d, f"{sym}.json")
            if os.path.exists(fp) and os.path.getsize(fp) > 40: continue
            a = int((settle - dt.timedelta(days=45)).timestamp())
            b = int(settle.timestamp())
            rows = fetch(sym, res, a, b)
            if not rows: continue
            out = []
            for c in rows:
                t = int(c["time"])
                if t > b: continue                      # drop post-settlement filler
                out.append([t, float(c["open"]), float(c["high"]),
                            float(c["low"]), float(c["close"]), c.get("volume")])
            if len(out) < 3: continue
            os.makedirs(d, exist_ok=True)
            json.dump(sorted(out, key=lambda r: r[0]), open(fp, "w"))
            n_new += 1
            time.sleep(0.08)
        if (i+1) % 25 == 0:
            print(f"  {i+1}/{len(todo)} contracts, {n_new} files written", flush=True)
    print(f"done: {n_new} files written", flush=True)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    main(since_days=a.days)
