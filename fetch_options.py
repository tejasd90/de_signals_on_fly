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
import json, os, sys, time, glob, urllib.request, urllib.error
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
    # MARK: prefix, as processor.js does for the whole historic store. The plain
    # symbol returns TRADED candles (flat zero-volume filler in no-trade hours, padded
    # to expiry for live contracts), which mixed two price series in one store.
    d = get(f"{BASE}/history/candles?symbol=MARK:{sym}&resolution={API_RES[res]}&start={int(a)}&end={int(b)}")
    return (d or {}).get("result") or []

def live_products():
    out, page = [], None
    while True:
        u = f"{BASE}/products?states=live&contract_types=call_options,put_options&page_size=200"
        if page: u += f"&after={page}"
        d = get(u)
        if not d: break
        res = d.get("result") or []
        out += res
        page = (d.get("meta") or {}).get("after")
        if not page or not res: break
    return out

def refresh_live(horizon_days=10, settled_days=2, resolutions=("15","60","240","1440")):
    """Incremental top-up for the loop: unlike main(), existing files ARE updated.

    Covers open contracts settling within horizon_days (enough to reach the weekly
    slot) plus files for expiries settled in the last settled_days, so a contract
    that expired between two runs still gets its final bars. Listing expired
    products pages through all history and takes minutes, so those are found from
    the store instead; their settlement is 12:00 UTC on the expiry date.
    """
    now = dt.datetime.now(dt.timezone.utc)
    todo = {}
    for p in live_products():
        parts = (p.get("symbol") or "").split("-")
        if len(parts) != 4 or parts[1] not in ASSETS or not p.get("settlement_time"): continue
        settle = dt.datetime.fromisoformat(p["settlement_time"].replace("Z", "+00:00"))
        if settle - now <= dt.timedelta(days=horizon_days):
            todo[p["symbol"]] = (parts[1], settle)
    for asset in ASSETS:
        base = f"data/candles/{asset}"
        if not os.path.isdir(base): continue
        for e in os.listdir(base):
            try: settle = dt.datetime.combine(dt.date.fromisoformat(e), dt.time(12), dt.timezone.utc)
            except ValueError: continue
            if not (now - dt.timedelta(days=settled_days) <= settle <= now): continue
            for res in resolutions:
                d = f"{base}/{e}/{res}"
                if os.path.isdir(d):
                    for fn in os.listdir(d):
                        if fn.endswith(".json"): todo.setdefault(fn[:-5], (asset, settle))
    jobs = []
    for sym, (asset, settle) in todo.items():
        b = int(min(settle, now).timestamp())
        for res in resolutions:
            d = f"data/candles/{asset}/{settle.date().isoformat()}/{res}"
            fp = os.path.join(d, f"{sym}.json")
            old = []
            if os.path.exists(fp):
                try: old = json.load(open(fp))
                except Exception: old = []
            old = [r for r in old if r[0] <= b]          # drop any padding past now
            last = max((r[0] for r in old), default=None)
            if last is not None and last >= b - int(res)*60: continue   # nothing new can exist yet
            a = last if last is not None else int((settle - dt.timedelta(days=45)).timestamp())
            jobs.append((sym, res, a, b, fp, old))
    # ~0.7s per request round trip, so serial took 9 min for one top-up; threads bring it near 1.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: fetch(*j[:4]), jobs))
    n_upd = 0
    for (sym, res, a, b, fp, old), rows in zip(jobs, results):
        if not rows: continue
        m = {r[0]: r for r in old}
        for c in rows:                      # re-fetch from `last` so a still-forming bar is overwritten
            t = int(c["time"])
            if t > b: continue
            m[t] = [t, float(c["open"]), float(c["high"]), float(c["low"]),
                    float(c["close"]), c.get("volume")]
        if len(m) < 3: continue
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        tmp = fp + ".tmp"
        json.dump(sorted(m.values(), key=lambda r: r[0]), open(tmp, "w"))
        os.replace(tmp, fp)
        n_upd += 1
    print(f"live refresh: {len(todo)} contracts, {n_upd} files updated", flush=True)

def remark(assets=ASSETS):
    """One-off repair: files written before the MARK: fix hold TRADED candles (numeric
    volume). Re-fetch each as MARK over the same contract window, never past now."""
    from concurrent.futures import ThreadPoolExecutor
    now = int(time.time()); jobs = []
    for asset in assets:
        for fp in glob.glob(f"data/candles/{asset}/*/*/*.json"):
            try: rows = json.load(open(fp))
            except Exception: continue
            if not rows or all(r[5] is None for r in rows[:50]): continue      # already MARK
            parts = fp.split("/"); expiry, res, sym = parts[3], parts[4], parts[5][:-5]
            if res not in API_RES: continue
            settle = int(dt.datetime.combine(dt.date.fromisoformat(expiry), dt.time(12), dt.timezone.utc).timestamp())
            jobs.append((fp, sym, res, settle - 45*86400, min(settle, now)))
    print(f"remark: {len(jobs)} traded files to rewrite", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda j: fetch(j[1], j[2], j[3], j[4]), jobs))
    n = 0
    for (fp, sym, r_, a, b), rows in zip(jobs, res):
        out = sorted([[int(c["time"]), float(c["open"]), float(c["high"]), float(c["low"]),
                       float(c["close"]), c.get("volume")] for c in rows if int(c["time"]) <= b], key=lambda x: x[0])
        if len(out) < 3: continue
        tmp = fp + ".tmp"; json.dump(out, open(tmp, "w")); os.replace(tmp, fp); n += 1
    print(f"remark: rewrote {n}", flush=True)

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
            b = int(min(settle, dt.datetime.now(dt.timezone.utc)).timestamp())   # never past now
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
    ap.add_argument("--live", action="store_true", help="incremental top-up of near-dated contracts (for the loop)")
    ap.add_argument("--remark", action="store_true", help="one-off: rewrite TRADED files (numeric volume) as MARK")
    ap.add_argument("--horizon", type=int, default=10, help="--live: days ahead to cover")
    a = ap.parse_args()
    if a.remark: remark()
    elif a.live: refresh_live(horizon_days=a.horizon)
    else: main(since_days=a.days)
