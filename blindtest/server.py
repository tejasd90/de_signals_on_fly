"""Blind chart test server (port 8790). Server-authoritative: the browser only ever receives bars up to
his cursor, so the future cannot be peeked at. Every action is appended to data/responses.jsonl with a
wall-clock time; data/session.json holds the resumable state. No outcomes are ever served.
Run: venv/bin/python blindtest/server.py   then open http://127.0.0.1:8790"""
import json, os, time, numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
HERE = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(HERE, "data")
CFG = {"meta": True, "port": 8790}
if os.path.exists(os.path.join(D, "config.json")): CFG.update(json.load(open(os.path.join(D, "config.json"))))
MAN = json.load(open(os.path.join(D, "manifest.json")))
TFS = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
IST = timezone(timedelta(hours=5, minutes=30))
_cache = {}
def chart(cid):
    if cid not in _cache:
        c = json.load(open(os.path.join(D, "charts", f"{cid}.json")))
        c["P"] = np.array(c["prem"], float); c["S"] = np.array(c["spot"], float); _cache.clear(); _cache[cid] = c
    return _cache[cid]

SP = os.path.join(D, "session.json")
def load_state():
    if os.path.exists(SP): return json.load(open(SP))
    return {"i": 0, "cursor": None, "tf": "1h", "ended": False, "steps": 0, "candles": 0}
def save_state(s): json.dump(s, open(SP + ".tmp", "w")); os.replace(SP + ".tmp", SP)
def log(ev): open(os.path.join(D, "responses.jsonl"), "a").write(json.dumps({**ev, "wall": time.time()}) + "\n")

def agg(a, cur, tf, hist0):
    """5m rows [t_rel,o,h,l,c] with t_rel < cur -> tf candles aligned to absolute UTC (last one forming)."""
    a = a[a[:, 0] < cur]
    if not len(a): return []
    b = ((a[:, 0] + hist0) // (tf * 60)).astype(np.int64)
    out = []; idx = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
    for k, s in enumerate(idx):
        e = idx[k + 1] if k + 1 < len(idx) else len(a); g = a[s:e]
        out.append([int(b[s]), g[0, 1], g[:, 2].max(), g[:, 3].min(), g[-1, 4]])
    return out

def view(s):
    if s["i"] >= len(MAN): return {"done": True, "n": len(MAN)}
    m = MAN[s["i"]]; c = chart(m["id"]); hist0 = m["hist0_dow_tod"]
    if s["cursor"] is None: s["cursor"] = c["start"]; save_state(s)
    tf = TFS[s["tf"]]; cur = s["cursor"]
    P = agg(c["P"], cur, tf, hist0); S = agg(c["S"], cur, tf, hist0)
    v = {"done": False, "i": s["i"], "n": len(MAN), "n_practice": sum(x["practice"] for x in MAN), "practice": m["practice"],
         "tf": s["tf"], "ended": s["ended"], "expired": cur >= c["settle"], "prem": P, "spot": S, "steps": s["steps"], "candles": s["candles"]}
    if CFG["meta"]:
        sp = c["S"][c["S"][:, 0] < cur]; spot_now = sp[-1, 4] if len(sp) else 100
        k = c["K_rel"] * 100
        v["meta"] = {"type": "CALL" if c["typ"] == "C" else "PUT",
                     "otm": round((k / spot_now - 1) * 100 if c["typ"] == "C" else (1 - k / spot_now) * 100, 2),
                     "tte_h": round((c["settle"] - cur) / 3600, 2),
                     "prem_pct": round(c["P"][c["P"][:, 0] < cur][-1, 4] * c.get("prem_pct", float("nan")) * 100 / spot_now, 4) if (c["P"][:, 0] < cur).any() else None,
                     "clock": datetime.fromtimestamp(hist0 + cur, IST).strftime("%a %H:%M IST")}
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
        base = {"chart": m["id"], "practice": m["practice"], "cursor": s["cursor"], "tf": s["tf"], "steps": s["steps"], "candles": s["candles"]}
        if act == "step" and not s["ended"]:
            n = int(a.get("n", 1))
            if n not in (1, 3, 10): return self.send(400, {"error": "step must be 1, 3 or 10"})
            new = min(c["settle"], s["cursor"] + n * TFS[s["tf"]] * 60)
            s["candles"] += round((new - s["cursor"]) / (TFS[s["tf"]] * 60)); s["steps"] += 1; s["cursor"] = new
            log({**base, "action": "step", "n": n, "cursor_after": new})
            if new >= c["settle"]: s["ended"] = True; log({**base, "action": "expired_no_call", "cursor": new})
        elif act == "tf" and a.get("tf") in TFS and not s["ended"]:
            s["tf"] = a["tf"]; log({**base, "action": "tf", "to": a["tf"]})
        elif act == "call" and not s["ended"]:
            tgt = a.get("target")
            if tgt not in ("5x", "10x", "25x", "50x", "100x+"): return self.send(400, {"error": "bad target"})
            s["ended"] = True; log({**base, "action": "call", "target": tgt, "note": str(a.get("note", ""))[:2000]})
        elif act == "leave" and not s["ended"]:
            s["ended"] = True; log({**base, "action": "leave", "note": str(a.get("note", ""))[:2000]})
        elif act == "next" and s["ended"]:
            s = {"i": s["i"] + 1, "cursor": None, "tf": s["tf"], "ended": False, "steps": 0, "candles": 0}
        else: return self.send(400, {"error": "action not allowed now"})
        save_state(s); self.send(200, view(s))

if __name__ == "__main__":
    print(f"blind test on http://127.0.0.1:{CFG['port']}  ({len(MAN)} charts)")
    ThreadingHTTPServer(("127.0.0.1", CFG["port"]), H).serve_forever()
