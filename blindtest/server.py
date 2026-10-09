"""Blind chart test server, v2 (port 8790). Server-authoritative: the browser only ever receives bars up to
his cursor. Each chart is a strike ladder: 5 nearest-OTM strikes, up to 3 further ones on request, and the
underlying. Timeframes 1h / 4h / 12h, and 15m only on expiry day (IST date of settlement). Every action
goes to data/responses.jsonl with a wall-clock time; data/session.json makes it resumable.
Config (data/config.json): {"meta": true, "time": true}. "meta" shows call/put and per-strike % OTM and
premium as % of the underlying; "time" shows the time to expiry and the weekday / IST clock.
Run: venv/bin/python blindtest/server.py   then open http://127.0.0.1:8790"""
import json, os, time, numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
CFG = {"meta": True, "time": True, "port": 8790}
if os.path.exists(os.path.join(D, "config.json")): CFG.update(json.load(open(os.path.join(D, "config.json"))))
MAN = json.load(open(os.path.join(D, "manifest.json")))
TFS = {"15m": 15, "1h": 60, "4h": 240, "12h": 720}
IST = timezone(timedelta(hours=5, minutes=30)); BASE, EXTRA = 5, 3
_cache = {}
def chart(cid):
    if cid not in _cache:
        c = json.load(open(os.path.join(D, "charts", f"{cid}.json")))
        c["S"] = np.array(c["spot"], float)
        for s in c["strikes"]: s["A"] = np.array(s["rows"], float)
        _cache.clear(); _cache[cid] = c
    return _cache[cid]

SP = os.path.join(D, "session.json")
def fresh(i, tf="1h"): return {"i": i, "cursor": None, "tf": tf, "ended": False, "steps": 0, "candles": 0, "extra": 0}
def load_state(): return json.load(open(SP)) if os.path.exists(SP) else fresh(0)
def save_state(s): json.dump(s, open(SP + ".tmp", "w")); os.replace(SP + ".tmp", SP)
def log(ev): open(os.path.join(D, "responses.jsonl"), "a").write(json.dumps({**ev, "wall": time.time()}) + "\n")

def expiry_day(c, origin, cur):
    return datetime.fromtimestamp(origin + cur, IST).date() == datetime.fromtimestamp(origin + c["settle"], IST).date()

def agg(a, cur, tf, origin):
    a = a[a[:, 0] < cur]
    if not len(a): return []
    b = ((a[:, 0] + origin) // (tf * 60)).astype(np.int64)
    idx = np.flatnonzero(np.r_[True, b[1:] != b[:-1]]); out = []
    for k, s in enumerate(idx):
        e = idx[k + 1] if k + 1 < len(idx) else len(a); g = a[s:e]
        out.append([int(b[s]), g[0, 1], g[:, 2].max(), g[:, 3].min(), g[-1, 4]])
    return out

def view(s):
    if s["i"] >= len(MAN): return {"done": True, "n": len(MAN)}
    m = MAN[s["i"]]; c = chart(m["id"]); org = m["t_origin"]
    if s["cursor"] is None: s["cursor"] = c["start"]; save_state(s)
    cur = s["cursor"]; ed = expiry_day(c, org, cur)
    if s["tf"] == "15m" and not ed: s["tf"] = "1h"; save_state(s)
    tf = TFS[s["tf"]]
    sp = c["S"][c["S"][:, 0] < cur]; spot_now = sp[-1, 4] if len(sp) else 100.0
    panels = []
    for j, st in enumerate(c["strikes"][:BASE + s["extra"]]):
        p = {"label": f"strike {j + 1}" + (" (extra)" if j >= BASE else ""), "bars": agg(st["A"], cur, tf, org)}
        if CFG["meta"]:
            k = st["K_rel"] * 100; seen = st["A"][st["A"][:, 0] < cur]
            p["otm"] = round((k / spot_now - 1) * 100 if c["typ"] == "C" else (1 - k / spot_now) * 100, 2)
            p["pct"] = round(seen[-1, 4] * st["pct"] * 100 / spot_now, 4) if len(seen) else None
        panels.append(p)
    v = {"done": False, "i": s["i"], "n": len(MAN), "n_practice": sum(x["practice"] for x in MAN), "practice": m["practice"],
         "tf": s["tf"], "tfs": [t for t in TFS if t != "15m" or ed], "ended": s["ended"], "expired": cur >= c["settle"],
         "spot": agg(c["S"], cur, tf, org), "panels": panels, "extra": s["extra"], "extra_max": min(EXTRA, len(c["strikes"]) - BASE),
         "steps": s["steps"], "candles": s["candles"]}
    if CFG["meta"]: v["type"] = "CALL" if c["typ"] == "C" else "PUT"
    if CFG["time"]: v["time"] = {"tte_h": round((c["settle"] - cur) / 3600, 2), "clock": datetime.fromtimestamp(org + cur, IST).strftime("%a %H:%M IST")}
    return v

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in ("/", "/index.html"): return self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html")
        if self.path == "/api/state": return self.send(200, view(load_state()))
        self.send(404, {"error": "not found"})
    def do_POST(self):
        if self.path != "/api/act": return self.send(404, {"error": "not found"})
        try: a = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except Exception: return self.send(400, {"error": "bad json"})
        s = load_state()
        if s["i"] >= len(MAN): return self.send(200, view(s))
        m = MAN[s["i"]]; c = chart(m["id"]); act = a.get("action")
        if s["cursor"] is None: s["cursor"] = c["start"]
        base = {k: s[k] for k in ("cursor", "tf", "steps", "candles", "extra")}; base.update(chart=m["id"], practice=m["practice"])
        live = not s["ended"] and s["cursor"] < c["settle"]
        if act == "step" and live:
            n = int(a.get("n", 1))
            if n not in (1, 3, 10): return self.send(400, {"error": "step must be 1, 3 or 10"})
            new = min(c["settle"], s["cursor"] + n * TFS[s["tf"]] * 60)
            s["candles"] += round((new - s["cursor"]) / (TFS[s["tf"]] * 60)); s["steps"] += 1; s["cursor"] = new
            log({**base, "action": "step", "n": n, "cursor_after": new})
            if new >= c["settle"]: s["ended"] = True; log({**base, "cursor": new, "action": "expired_no_call"})
        elif act == "tf" and live and a.get("tf") in TFS:
            if a["tf"] == "15m" and not expiry_day(c, m["t_origin"], s["cursor"]): return self.send(400, {"error": "15m is available on expiry day only"})
            s["tf"] = a["tf"]; log({**base, "action": "tf", "to": a["tf"]})
        elif act == "more" and live:
            if s["extra"] >= min(EXTRA, len(c["strikes"]) - BASE): return self.send(400, {"error": "no more strikes"})
            s["extra"] += 1; log({**base, "action": "more", "extra_after": s["extra"]})
        elif act == "call" and live:
            tgt, ks = a.get("target"), a.get("strikes")
            if tgt not in ("5x", "10x", "25x", "50x", "100x+"): return self.send(400, {"error": "bad target"})
            if not isinstance(ks, list) or not ks or any(not isinstance(k, int) or k < 0 or k >= BASE + s["extra"] for k in ks):
                return self.send(400, {"error": "pick at least one shown strike"})
            s["ended"] = True; log({**base, "action": "call", "target": tgt, "strikes": sorted(set(ks)), "note": str(a.get("note", ""))[:2000]})
        elif act == "leave" and live:
            s["ended"] = True; log({**base, "action": "leave", "note": str(a.get("note", ""))[:2000]})
        elif act == "next" and (s["ended"] or s["cursor"] >= c["settle"]):
            s = fresh(s["i"] + 1, s["tf"] if s["tf"] != "15m" else "1h")
        else: return self.send(400, {"error": "action not allowed now"})
        save_state(s); self.send(200, view(s))

if __name__ == "__main__":
    print(f"blind test on http://127.0.0.1:{CFG['port']}  ({len(MAN)} charts)")
    ThreadingHTTPServer(("127.0.0.1", CFG["port"]), H).serve_forever()
