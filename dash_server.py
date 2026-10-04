"""Dashboard server + the background update loop.

One dashboard serves both past and live: the same panes, the same computation.
Scrolling left walks into history with the expiries that were live THEN, because
slots are resolved per bar (see dash_api.assign_slots).

The loop exists because of the live pane: every INTERVAL minutes it refreshes spot
candles, tops up near-dated option candles (fetch_options --live), rebuilds the most recent expiries' required-move grids, and re-reads the
live option chain. Default 15 minutes, settable with --interval.
"""
import json, math, os, sys, threading, time, subprocess, urllib.request, shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import numpy as np

import dash_api, dash_setups, re
ASSETS = ("BTC", "ETH")
RESOLUTIONS = ("15", "60", "240", "1440")
from optreq import required_moves

HERE = os.path.dirname(os.path.abspath(__file__))
TICKERS = "https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options"
_cache, _lock = {}, threading.Lock()
NODE = shutil.which("node") or "/opt/homebrew/opt/node@20/bin/node"
# The live option top-up rewrites near-dated files in place (a few MB a day), so its floor
# is low; without it the newest grid columns go stale. The heavy research refresh has its
# own 4 GB floor in daily_jobs.py.
MIN_FREE_GB = 1.0

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
            free_gb = shutil.disk_usage(HERE).free / 1e9
            low = free_gb < MIN_FREE_GB
            if low:
                print(f"[loop] DISK LOW: {free_gb:.1f} GB free < {MIN_FREE_GB} GB -- "
                      f"skipping option fetch; spot, signals and paper log still run", flush=True)
            steps = [(["update_spot.py", "15", "60", "240", "1440"], 600)]
            if not low: steps.append((["fetch_options.py", "--live"], 1800))
            steps += [(["dash_build.py", "--limit", "12"], 1800),
                      # forward test: R4/R5 state needs fresh spot_grouped; log signals the
                      # live runner wrote BEFORE their outcome is known, resolve settled ones
                      (["@node", "export_spot_tf.js"], 300),
                      (["paper_log.py", "--run", "--hours", "3"], 600),
                      (["paper_log.py", "--resolve"], 1800)]
            for cmd, to in steps:
                argv = [NODE] + cmd[1:] if cmd[0] == "@node" else [sys.executable] + cmd
                env = dict(os.environ, DE_NO_LOG_DIR="1") if cmd[0] == "@node" else None
                r = subprocess.run(argv, cwd=HERE, capture_output=True, text=True, timeout=to, env=env)
                if r.returncode:
                    print(f"[loop] {cmd[0]} exit {r.returncode}: {r.stderr.strip()[-300:]}", flush=True)
                elif cmd[0] == "paper_log.py" and "logged" in r.stdout:
                    print(f"[loop] {r.stdout.strip().splitlines()[-1]}", flush=True)
            # once per UTC day (marker file inside): forward report, journal watch, research
            # refresh. Detached, because the research refresh can take hours.
            subprocess.Popen([sys.executable, "daily_jobs.py"], cwd=HERE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            with _lock: _cache.clear()
            print(f"[loop] refreshed {time.strftime('%H:%M:%S')}", flush=True)
        except Exception as ex:
            print(f"[loop] {type(ex).__name__}: {ex}", flush=True)
        time.sleep(interval_min * 60)

def _clean(o):
    """NaN/Infinity are not JSON. Python's json.dumps writes them anyway and browsers then
    reject the whole payload (found by the headless self-test: 4h/1d views never loaded).
    Map them to null, and dump with allow_nan=False so any that slip through fail loudly."""
    if isinstance(o, float): return o if math.isfinite(o) else None
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if isinstance(o, np.floating): return _clean(float(o))
    if isinstance(o, np.integer): return int(o)
    return o

def jdump(o): return json.dumps(_clean(o), allow_nan=False)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_POST(self):
        # /api/selftest: dashboard_selftest.js reports its PASS/FAIL lines here (only used
        # by the headless browser test); written to logs/selftest.txt
        if urlparse(self.path).path != "/api/selftest": self.send_response(404); self.end_headers(); return
        n = min(int(self.headers.get("Content-Length", 0)), 200_000)
        body = self.rfile.read(n).decode("utf-8", "replace")
        with open(os.path.join(HERE, "logs", "selftest.txt"), "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + body)
        self._send(jdump({"ok": True}))
    def _bad(self, msg):
        b = json.dumps({"error": msg}).encode()
        self.send_response(400); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        # Every parameter that reaches a file path is whitelisted.
        a = q.get("asset", ["BTC"])[0]
        if a not in ASSETS: return self._bad("asset must be BTC or ETH")
        if u.path in ("/", "/index.html"):
            return self._send(open(os.path.join(HERE, "dashboard.html"), "rb").read(), "text/html")
        if u.path == "/selftest.js":          # only requested when the page is opened with ?selftest
            return self._send(open(os.path.join(HERE, "dashboard_selftest.js"), "rb").read(), "application/javascript")
        if u.path == "/api/setups":
            try: t0, t1 = int(q["t0"][0]), int(q["t1"][0])
            except Exception: return self._bad("t0 and t1 (unix seconds) required")
            return self._send(jdump(dash_setups.window(a, t0, t1)))
        if u.path == "/api/setup_expiries":
            return self._send(jdump(dash_setups.expiries(a)))
        if u.path == "/api/sheet":
            e = q.get("expiry", [""])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e): return self._bad("expiry must be YYYY-MM-DD")
            return self._send(jdump(dash_setups.sheet(a, e)))
        if u.path == "/api/payload":
            r = q.get("res", ["60"])[0]
            if r not in RESOLUTIONS: return self._bad("res must be one of " + ",".join(RESOLUTIONS))
            try: n = max(50, min(int(q.get("limit", ["800"])[0]), 6000))
            except ValueError: return self._bad("limit must be an integer")
            key = (a, r, n)
            with _lock: hit = _cache.get(key)
            if hit is None:
                hit = dash_api.payload(a, r, limit=n)
                with _lock: _cache[key] = hit
            return self._send(jdump(hit))
        if u.path == "/api/live":
            try: return self._send(jdump({"asset": a, "rows": live_chain(a),
                                               "t": int(time.time())}))
            except Exception as ex: return self._send(jdump({"error": str(ex)}))
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
