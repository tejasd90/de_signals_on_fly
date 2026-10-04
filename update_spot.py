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
# MARK: prefix. data/spot_candles is the perp MARK series (see de-signals-spot-is-mark) and
# node's spot_store.js writes it that way. The plain symbol returns TRADED candles; from
# 2026-09-26 this script wrote those into the MARK store (found 2026-10-04, repaired with
# --repair-since 2026-09-25).
ASSETS = {"BTC":"MARK:BTCUSD", "ETH":"MARK:ETHUSD", "XAUT":"MARK:XAUTUSD"}
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

IST = timezone(timedelta(hours=5, minutes=30))
def ist_day(t):
    """Day files are IST dates, as node's spot_store.js writes them. This script used UTC
    dates, so bars between 18:30 and 24:00 UTC landed in two files."""
    return datetime.fromtimestamp(t, tz=IST).strftime("%Y-%m-%d")

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
        by.setdefault(ist_day(t), []).append(row)
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

def repair(asset, res, since):
    """Rewrite every day file from `since` (IST date) onward from MARK candles alone,
    filed by IST day. Bars the fetch does not return are kept from the old files only if
    they are MARK (volume null); traded strays and cross-day duplicates are dropped."""
    sym = ASSETS[asset]; d = f"data/spot_candles/{asset}/{res}"
    a = int(datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=IST).timestamp())
    stop = int(datetime.now(timezone.utc).timestamp()); step = RES_SECS[res] * CHUNK_BARS
    fetched = {}
    while a < stop:
        b = min(a + step, stop)
        for c in get(sym, API_RES[res], a, b):
            t = int(c["time"]); fetched[t] = [t, float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]), c.get("volume")]
        a = b + 1; time.sleep(0.15)
    if not fetched:
        print(f"  {asset}/{res}: repair fetched nothing -- left untouched", file=sys.stderr); return
    keep = {}
    for f in sorted(os.listdir(d)):
        if f.startswith(".") or f < since: continue
        try:
            for r in json.load(open(os.path.join(d, f))):
                if r[5] is None: keep.setdefault(int(r[0]), r)         # old MARK bars only
        except Exception: pass
    keep.update(fetched)                                                  # fresh MARK wins
    by = {}
    for t, r in keep.items():
        if ist_day(t) >= since: by.setdefault(ist_day(t), []).append(r)
    for f in sorted(os.listdir(d)):
        if not f.startswith(".") and f >= since and f not in by: os.remove(os.path.join(d, f))
    for day, rs in by.items():
        tmp = os.path.join(d, day + ".tmp")
        json.dump(sorted(rs, key=lambda r: r[0]), open(tmp, "w")); os.replace(tmp, os.path.join(d, day))
    print(f"  {asset}/{res}: repaired {len(by)} days from {since}, {len(fetched)} MARK bars fetched")

if __name__ == "__main__":
    if "--repair-since" in sys.argv:
        since = sys.argv[sys.argv.index("--repair-since") + 1]
        for asset in ("BTC", "ETH"):
            for res in sorted(os.listdir(f"data/spot_candles/{asset}"), key=int):
                if res in API_RES: repair(asset, res, since)
        sys.exit(0)
    which = sys.argv[1:] or ["1440","360","240","60","15"]
    tot = 0
    for asset in ASSETS:
        for res in which:
            if os.path.isdir(f"data/spot_candles/{asset}/{res}"):
                tot += update(asset, res)
    print(f"total new bars: {tot}")
