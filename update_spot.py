"""Bring data/spot_candles up to date.

The option-candle store and the multibagger files come from a pipeline that is not
in this repo, so this updater covers what the price-action work actually reads:
spot_candles, which levels.py / wedge.py / pascore.py all load through load_tf.

Same conventions as fetch_perps.py: Delta India /v2/history/candles, and CHUNKED
requests, because a one-shot call silently returns only the most recent window
(~4000 rows) and looks like success.

Layout matches the existing store exactly: data/spot_candles/<ASSET>/<RES>/<YYYY-MM-DD>,
one JSON list of [ts,o,h,l,c,vol] per UTC day, so nothing downstream changes.
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

BASE = "https://api.india.delta.exchange/v2/history/candles"
RES_SECS = {"5":300, "15":900, "30":1800, "60":3600, "120":7200,
            "240":14400, "360":21600, "1440":86400}
# The store's directories are named in MINUTES; the API wants Delta's own strings.
# Passing "1440" returns HTTP 400, which the first version swallowed as "no new data".
API_RES = {"5":"5m", "15":"15m", "30":"30m", "60":"1h", "120":"2h",
           "240":"4h", "360":"6h", "1440":"1d"}
ASSETS = {"BTC":"BTCUSD", "ETH":"ETHUSD", "XAUT":"XAUTUSD"}
CHUNK_BARS = 1500          # well under the silent ~4000 cap

def get(sym, res, a, b, tries=4):
    u = f"{BASE}?symbol={sym}&resolution={res}&start={int(a)}&end={int(b)}"
    for k in range(tries):
        try:
            with urllib.request.urlopen(u, timeout=45) as r:
                return json.load(r).get("result") or []
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(2 * (k + 1)); continue
            print(f"    HTTP {e.code} for {sym}/{res}", file=sys.stderr)
            return []
        except Exception:
            time.sleep(1 + k)
    return []

def latest_day(d):
    if not os.path.isdir(d): return None
    days = sorted(f for f in os.listdir(d) if not f.startswith("."))
    return days[-1] if days else None

def update(asset, res):
    sym = ASSETS[asset]
    d = f"data/spot_candles/{asset}/{res}"
    os.makedirs(d, exist_ok=True)
    last = latest_day(d)
    if last is None:
        print(f"  {asset}/{res}: empty, skipping (backfill not this script's job)"); return 0
    # re-fetch the last stored day too: it was probably partial when written
    start = datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    if (end - start).total_seconds() < RES_SECS[res]:
        print(f"  {asset}/{res}: current ({last})"); return 0
    step = RES_SECS[res] * CHUNK_BARS
    rows, a = [], int(start.timestamp())
    stop = int(end.timestamp())
    while a < stop:
        b = min(a + step, stop)
        r = get(sym, API_RES[res], a, b)
        if not r: break
        rows.extend(r)
        a = b + 1
        time.sleep(0.15)
    if not rows:
        print(f"  {asset}/{res}: no new data"); return 0
    by = {}
    for c in rows:
        t = int(c["time"]) if isinstance(c, dict) else int(c[0])
        row = ([t, float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]),
                c.get("volume")] if isinstance(c, dict) else list(c))
        by.setdefault(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), []).append(row)
    n = 0
    for day, rs in sorted(by.items()):
        p = os.path.join(d, day)
        old = []
        if os.path.exists(p):
            try: old = json.load(open(p))
            except Exception: old = []
        merged = {int(r[0]): r for r in old}
        merged.update({int(r[0]): r for r in rs})
        out = [merged[k] for k in sorted(merged)]
        json.dump(out, open(p, "w"))
        n += 1
    print(f"  {asset}/{res}: {last} -> {sorted(by)[-1]}  ({len(rows)} bars, {n} days)")
    return len(rows)

if __name__ == "__main__":
    which = sys.argv[1:] or ["1440","360","240","60","15"]
    tot = 0
    for asset in ASSETS:
        for res in which:
            if os.path.isdir(f"data/spot_candles/{asset}/{res}"):
                tot += update(asset, res)
    print(f"total new bars: {tot}")
