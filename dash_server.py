"""Dashboard server + the background update loop.

One dashboard serves both past and live: the same panes, the same computation.
Scrolling left walks into history with the expiries that were live THEN, because
slots are resolved per bar (see dash_api.assign_slots).

The loop exists because of the live pane: every INTERVAL minutes it refreshes spot
candles, rebuilds the most recent expiries' required-move grids, and re-reads the
live option chain. Default 15 minutes, settable with --interval.
"""
import json, os, sys, threading, time, subprocess, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import numpy as np

import dash_api
from optreq import required_moves

HERE = os.path.dirname(os.path.abspath(__file__))
TICKERS = "https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options"
_cache, _lock = {}, threading.Lock()

def live_chain(asset):
    """Current required moves straight from the live chain (uses its own IV)."""
    with urllib.request.urlopen(TICKERS, timeout=30) as r:
        res = json.load(r).get("result") or []
    rows = [x for x in res if x.get("symbol", "").split("-")[1:2] == [asset]]
    if not rows: return []
    spot = float(rows[0].get("spot_price") or 0) or None
    if not spot: return []
    import collections, datetime as dt
    by = collections.defaultdict(list)
    for x in rows:
        p = x["symbol"].split("-")
        try:
            k = float(p[2]); e = dt.datetime.strptime(p[3], "%d%m%y").date()
            mp = float(x.get("mark_price") or 0)
        except Exception: continue
        if mp > 0: by[e].append((p[0], k, mp))
    today = dt.date.today()
    exps = sorted(e for e in by if e >= today)
    slots = {}
    if exps: slots["immediate"] = exps[0]
    if len(exps) > 1: slots["next"] = exps[1]
    taken = set(slots.values())
    fri = [e for e in exps if e.weekday() == 4 and e not in taken]
    if fri: slots["weekly"] = fri[0]
    out = []
    now = dt.datetime.now(dt.timezone.utc)
    for name, e in slots.items():
        tte = max((dt.datetime.combine(e, dt.time(12, 0), dt.timezone.utc) - now).total_seconds(), 60) / (365*86400)
        rec = dict(slot=name, expiry=str(e), tte_d=tte*365, spot=spot)
        for typ, call in (("c", True), ("p", False)):
            sel = [(k, m) for t, k, m in by[e] if t == ("C" if call else "P")]
            if not sel: continue
            ks = np.array([k for k, _ in sel], float)
            pm = np.array([[m for _, m in sel]], float)
            me, mn, ke, kn = required_moves(pm, ks, np.array([spot]), np.array([tte]), call=call)
            rec.update({f"{typ}_exp": float(me[0]), f"{typ}_now": float(mn[0]),
                        f"{typ}_k_exp": float(ke[0]), f"{typ}_k_now": float(kn[0])})
        out.append(rec)
    return out

def refresh(interval_min):
    while True:
        try:
            subprocess.run([sys.executable, "update_spot.py", "15", "60", "240", "1440"],
                           cwd=HERE, capture_output=True, timeout=600)
            subprocess.run([sys.executable, "dash_build.py", "--limit", "6"],
                           cwd=HERE, capture_output=True, timeout=1800)
            with _lock: _cache.clear()
            print(f"[loop] refreshed {time.strftime('%H:%M:%S')}", flush=True)
        except Exception as ex:
            print(f"[loop] {type(ex).__name__}: {ex}", flush=True)
        time.sleep(interval_min * 60)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._send(open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html")
        if u.path == "/api/payload":
            a = q.get("asset", ["BTC"])[0]; r = q.get("res", ["60"])[0]
            n = int(q.get("limit", ["1200"])[0])
            key = (a, r, n)
            with _lock: hit = _cache.get(key)
            if hit is None:
                hit = dash_api.payload(a, r, limit=n)
                with _lock: _cache[key] = hit
            return self._send(json.dumps(hit))
        if u.path == "/api/live":
            a = q.get("asset", ["BTC"])[0]
            try: return self._send(json.dumps({"asset": a, "rows": live_chain(a),
                                               "t": int(time.time())}))
            except Exception as ex: return self._send(json.dumps({"error": str(ex)}))
        self.send_response(404); self.end_headers()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--interval", type=int, default=15, help="refresh minutes (15 and upwards)")
    ap.add_argument("--no-loop", action="store_true")
    a = ap.parse_args()
    if not a.no_loop:
        threading.Thread(target=refresh, args=(max(a.interval, 15),), daemon=True).start()
    print(f"dashboard: http://127.0.0.1:{a.port}   refresh every {a.interval}m", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
