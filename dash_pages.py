"""One server, one list of pages. The home page (/) is rendered from PAGES, so every page that exists is listed there.

Older viewers (the serve_*.js research pages and the blind chart test) were separate servers on their own ports. They are
now reached under /old/<name>/ on this server: dash_server starts the viewer in the background the first time its page is
opened, passes requests through, and stops it after IDLE_MIN minutes without use. Nothing needs starting by hand.
"""
import os, sys, time, socket, subprocess, threading, shutil, html, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
NODE = shutil.which("node") or "/opt/homebrew/opt/node@20/bin/node"
IDLE_MIN = 20

# (group, url, title, purpose)
PAGES = [
    ("Crypto (Delta Exchange)", "/crypto", "Price action → 1:100", "Main BTC/ETH dashboard: spot price action, the 1:100 required-move grid, live option chain, and the setup review sheet per expiry."),
    ("Indian market (NSE / BSE)", "/nse", "Index signals", "Every signal firing on NIFTY, SENSEX, BANKNIFTY and the other index chains, per expiry and timeframe, with what the option did after; click a strike for the index and option chart."),
    ("Indian market (NSE / BSE)", "/nse/stocks", "Stock option moves", "For each monthly expiry, every F&O stock ranked by how far its options ran (calls, puts or either); sortable, with an all-months summary per stock."),
    ("Indian market (NSE / BSE)", "/nse/contracts", "Contract finder", "Pick an expiry and an underlying to get each strike's SYMBOL_token file name (click to copy) and a ready link into the chart app."),
]
# name -> (command, internal port, title, purpose, former port)
OLD = {
    "signals":      ([NODE, "serve_signals.js"], 18100, "Signals browser", "Research view of settled crypto signals: merged ranges, strength against payoff, expiry-by-duration grid.", 3100),
    "live":         ([NODE, "serve_live.js"], 18200, "Live board", "Monitor of live crypto signals for unexpired contracts, from the snapshots the live runner writes.", 3200),
    "multibaggers": ([NODE, "serve_multibaggers.js"], 18300, "Multibaggers table", "Ground truth: every big crypto option move that existed, with no signal involved (the denominator for capture rates).", 3300),
    "trades":       ([NODE, "serve_trades.js"], 18400, "Trades browser", "The biggest crypto option moves per expiry, to inspect what the candles looked like before the low.", 3400),
    "calendar":     ([NODE, "serve_signals_cal.js"], 18500, "Signals calendar", "Calendar layout of the same crypto signals, one expiry at a time.", 3500),
    "calibrate":    ([NODE, "serve_calibrate.js"], 18600, "Calibration workbench", "One signal at a time: successes and failures side by side, to tune thresholds.", 3600),
    "query":        ([NODE, "serve_query.js"], 18700, "Pattern query", "Filter the extracted signal patterns and score them on held-out expiries.", 3700),
    "grids":        ([NODE, "serve_grids.js"], 18800, "Signal heatmaps (live expiries)", "Expiry × time heatmaps of how many strikes fired, per timeframe and side.", 3800),
    "grids-past":   ([NODE, "serve_grids_past.js"], 18900, "Signal heatmaps (settled expiries)", "The same heatmaps for settled expiries, against time to expiry.", 3900),
    "blindtest":    ([sys.executable, os.path.join("blindtest", "server.py")], 8790, "Blind chart test", "The blind chart-reading test of October 2026 (finished; kept for review).", 8790),
}
_proc, _last, _lock = {}, {}, threading.Lock()

def _open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0

def ensure(name):
    """Start the viewer if it is not answering; return its port."""
    cmd, port = OLD[name][0], OLD[name][1]
    with _lock:
        _last[name] = time.time()
        if _open(port): return port
        args = cmd if name == "blindtest" else cmd + ["--port", str(port)]
        log = open(os.path.join(HERE, "logs", f"old_{name}.log"), "ab")
        _proc[name] = subprocess.Popen(args, cwd=HERE, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        for _ in range(240):                                   # big histories take a while to load
            if _open(port): return port
            if _proc[name].poll() is not None: raise RuntimeError(f"{name} viewer exited at start; see logs/old_{name}.log")
            time.sleep(0.25)
        raise RuntimeError(f"{name} viewer did not come up in 60s")

def reaper():
    while True:
        time.sleep(60)
        with _lock:
            for name, p in list(_proc.items()):
                if p.poll() is None and time.time() - _last.get(name, 0) > IDLE_MIN * 60: p.terminate()
                if p.poll() is not None: _proc.pop(name, None)

def proxy(name, rest, method="GET", body=None, ctype=None):
    """-> (status, content type, bytes) from the viewer; its own /api/ calls are pointed back under /old/<name>/."""
    port = ensure(name)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{rest}", data=body, method=method, headers={"Content-Type": ctype} if ctype else {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r: status, ct, data = r.status, r.headers.get("Content-Type", "application/octet-stream"), r.read()
    except urllib.error.HTTPError as e: status, ct, data = e.code, e.headers.get("Content-Type", "text/plain"), e.read()
    if "html" in ct:
        pre = f"/old/{name}/api/".encode()
        for q in (b"'", b'"', b"`"): data = data.replace(q + b"/api/", q + pre)
        bar = (f'<div style="position:fixed;right:10px;bottom:10px;z-index:99999;background:#161b22;border:1px solid #30363d;border-radius:6px;padding:4px 10px;font:12px -apple-system,sans-serif">'
               f'<a href="/" style="color:#d4823f;text-decoration:none">⌂ all pages</a></div>').encode()
        i = data.lower().rfind(b"</body>")
        data = data[:i] + bar + data[i:] if i >= 0 else data + bar
    return status, ct, data

def home():
    e = html.escape
    out = ['<!doctype html><html><head><meta charset="utf-8"><title>All pages</title><style>',
           ':root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#d4823f}',
           'body{background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:22px 28px;max-width:1100px}',
           'h1{font-size:18px;margin:0 0 4px} h2{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:26px 0 8px}',
           'p{color:var(--muted);margin:0 0 6px} table{border-collapse:collapse;width:100%} td{padding:8px 10px;border-bottom:1px solid #1b212c;vertical-align:top}',
           'td.t{white-space:nowrap;font-weight:600} td.u{white-space:nowrap;font-family:ui-monospace,Menlo,monospace;font-size:12.5px} a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}',
           'td.d{color:var(--muted)}</style></head><body><h1>All pages</h1><p>Everything is served from this one address. Each row is a page: its name, its URL, and what it is for.</p>']
    groups = []
    for g, url, title, why in PAGES:
        if g not in groups: groups.append(g)
    for g in groups:
        out.append(f"<h2>{e(g)}</h2><table>")
        for gg, url, title, why in PAGES:
            if gg == g: out.append(f'<tr><td class="t"><a href="{e(url)}">{e(title)}</a></td><td class="u"><a href="{e(url)}">{e(url)}</a></td><td class="d">{e(why)}</td></tr>')
        out.append("</table>")
    out.append(f"<h2>Older research viewers (were separate servers; start by themselves when opened, stop after {IDLE_MIN} idle minutes)</h2><table>")
    for name, (cmd, port, title, why, was) in OLD.items():
        u = f"/old/{name}/"
        out.append(f'<tr><td class="t"><a href="{u}">{e(title)}</a></td><td class="u"><a href="{u}">{u}</a></td><td class="d">{e(why)} <span style="opacity:.7">Formerly port {was}.</span></td></tr>')
    out.append("</table></body></html>")
    return "".join(out)
