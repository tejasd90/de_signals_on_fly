"""Checks for the merged dashboard (dash_server.py + dashboard.html), against the spec.

Run with the server up:  venv/bin/python test_dashboard.py [--base http://127.0.0.1:8777]

Each check recomputes something INDEPENDENTLY of dash_api rather than re-reading its output:
  slots      immediate / next / weekly per candle, from the expiry list alone
  numbers    the 1:100 required moves, re-solved from raw option candles with optreq
  alignment  grid rows sit exactly on candle timestamps, one per slot per candle
  events     price-action points inside the chart range; their attached 1:100 = the
             immediate slot at that time
  setups     window de-duplication, direction-matched signals, chart links identical to
             chart_url.js (the :4000 viewer's link builder)
  proximity  states consistent with their ATR thresholds
  live       live slots follow the same rule as history
  inputs     bad parameters rejected
"""
import json, os, random, subprocess, sys, urllib.request, urllib.error
import numpy as np, pandas as pd
from optreq import required_moves

BASE = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://127.0.0.1:8777"
random.seed(int(os.environ.get('SEED', 7)))
FAIL = []
def _strict(c):  # parse like a browser: NaN / Infinity are not JSON
    raise ValueError(f"non-JSON constant {c} in response")
def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r: return r.status, json.loads(r.read(), parse_constant=_strict)
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read(), parse_constant=_strict)
def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not ok: FAIL.append(name)

def expected_slots(asset, ts, exps):
    """Expiries alive at ts = the candle's CLOSE (settles strictly after it) -> slots."""
    alive = sorted(e for e in exps if pd.Timestamp(e).timestamp() + 43200 > ts)
    out = {}
    if alive: out["immediate"] = alive[0]
    if len(alive) > 1: out["next"] = alive[1]
    fri = [e for e in alive[2:] if pd.Timestamp(e).weekday() == 4]
    if fri: out["weekly"] = fri[0]
    return out

def raw_req(asset, expiry, ts, src_res):
    """Re-solve the 1:100 moves at one bar from raw option candles (MARK) and spot."""
    d = f"data/candles/{asset}/{expiry}/{src_res}"
    C, P = {}, {}
    for fn in os.listdir(d):
        if not fn.endswith(".json"): continue
        typ, _, k, _ = fn[:-5].split("-")
        for r in json.load(open(os.path.join(d, fn))):
            if int(r[0]) == ts and r[4] is not None: (C if typ == "C" else P)[float(k)] = float(r[4])
    S = None   # day files are IST dates: look in the bar's IST day and its neighbours
    ist = pd.Timestamp(ts, unit="s") + pd.Timedelta(hours=5, minutes=30)
    for dd in (-1, 0, 1):
        fp = f"data/spot_candles/{asset}/{src_res}/{(ist + pd.Timedelta(days=dd)).strftime('%Y-%m-%d')}"
        if not os.path.exists(fp): continue
        for r in json.load(open(fp)):
            if int(r[0]) == ts: S = float(r[4])
    tte = (pd.Timestamp(expiry).timestamp() + 43200 - (ts + int(src_res)*60)) / (365*86400)   # from the bar close
    out = {}
    for typ, book, call in (("c", C, True), ("p", P, False)):
        ks = np.array(sorted(book)); pm = np.array([[book[k] for k in ks]])
        me, mn, _, _ = required_moves(pm, ks, np.array([S]), np.array([tte]), call=call)
        out[f"{typ}_exp"], out[f"{typ}_now"] = float(me[0]), float(mn[0])
    return out

for asset in ("BTC", "ETH"):
    for res in ("15", "60", "240", "1440"):
        print(f"\n== {asset} {res}m")
        st, p = get(f"/api/payload?asset={asset}&res={res}&limit=400")
        check("payload 200", st == 200 and "candles" in p, p.get("error", "") if isinstance(p, dict) else "")
        if st != 200: continue
        C = p["candles"]; ts = [int(t) for t in C["ts"]]; req = p["req"]
        check("candles ascending, no duplicates", ts == sorted(set(ts)))
        check("candle OHLC sane", all(l <= min(o, c) and h >= max(o, c) for o, h, l, c in zip(C["o"], C["h"], C["l"], C["c"])))
        R = pd.DataFrame(req)
        check("grid rows exist", len(R) > 0, f"{len(R)} rows")
        if not len(R): continue
        check("grid rows sit on candle timestamps", set(R.ts.astype(int)) <= set(ts))
        check("one row per slot per candle", not R.duplicated(["ts", "slot"]).any())
        cov = R.groupby("slot").ts.nunique() / len(ts)
        check("immediate slot covers most candles", cov.get("immediate", 0) > 0.9, f"coverage {cov.round(2).to_dict()}")
        # slot rule, independently, at 25 random candles
        src = {"1440": "240"}.get(res, res)
        exps = sorted({f.rsplit("_", 1)[1][:-8] for f in os.listdir("data/dashreq") if f.startswith(f"{asset}_{src}_")})
        bad = 0; tested = 0
        closed = sorted(set(R.ts.astype(int)) - {ts[-1]})          # the last candle may still be forming
        for t in random.sample(closed, min(25, len(closed))):
            got = {r.slot: r.expiry for r in R[R.ts == t].itertuples()}
            exp = expected_slots(asset, t + int(res)*60, exps)     # alive = settles after the candle CLOSES
            # a slot may be legitimately missing if that expiry had no chain row at t
            for s_, e_ in got.items():
                tested += 1
                if exp.get(s_) != e_:
                    bad += 1; badd = f"{pd.Timestamp(t, unit='s')} {s_}: got {e_}, expected {exp.get(s_)}"
        check("slot rule matches an independent recompute", bad == 0, f"{bad}/{tested} mismatches" + (f"; e.g. {badd}" if bad else ""))
        # numbers: re-solve 6 random (ts, slot) cells from raw candles (only where the grid
        # resolution equals the source resolution, so the bar is the same bar)
        if res != "1440":
            errs = []
            for r in R.sample(min(6, len(R)), random_state=1).itertuples():
                try: x = raw_req(asset, r.expiry, int(r.ts), src)
                except Exception as ex: errs.append(f"{r.expiry}@{int(r.ts)}: {type(ex).__name__}"); continue
                for k in ("c_now", "c_exp", "p_now", "p_exp"):
                    a, b = getattr(r, k), x[k]
                    if (a is None or not np.isfinite(a)) and not np.isfinite(b): continue
                    if a is None or not np.isfinite(b) or abs(a - b) > 1e-6 + 1e-6*abs(b): errs.append(f"{k} {a} vs {b}")
            check("1:100 numbers re-solved from raw candles", not errs, "; ".join(errs[:3]))
        # events
        ev = p["events"]
        check("events inside the chart range", all(ts[0] <= e["ts"] <= ts[-1] + 86400 for e in ev), f"{len(ev)} events")
        imm = R[R.slot == "immediate"].set_index("ts")
        mism = [e for e in ev if e.get("c_now") is not None and int(e["ts"]) in imm.index
                and abs(imm.loc[int(e["ts"]), "c_now"] - e["c_now"]) > 1e-9]
        check("event 1:100 = immediate slot at that candle", not mism, f"{len(mism)} mismatches")
        # proximity
        bad = [r for r in p["proximity"] if (r["state"] == "TESTING" and abs(r["dist_atr"]) > 0.4)
               or (r["state"] == "APPROACHING" and not (0.4 < abs(r["dist_atr"]) <= 1.5))]
        check("proximity states match thresholds", not bad, f"{len(p['proximity'])} rows")
        # setups over the loaded window
        st, su = get(f"/api/setups?asset={asset}&t0={ts[0]}&t1={ts[-1]}")
        check("setups 200", st == 200)
        keys = [(s["ts"], s["tf"], s["name"], s["dir"]) for s in su]
        check("setups de-duplicated", len(keys) == len(set(keys)), f"{len(su)} setups")
        check("setups inside window", all(ts[0] <= s["ts"] <= ts[-1] for s in su))
        wrong = [g for s in su for g in s["signals"] if (s["dir"] == "long") != (g["ty"] == "C")]
        check("setup signals match direction (long->C, short->P)", not wrong)

    # sheet vs the original :4000 data, and chart links vs chart_url.js
    print(f"\n== {asset} setup review sheet")
    st, ex = get(f"/api/setup_expiries?asset={asset}")
    check("expiries listed, newest first", st == 200 and ex == sorted(ex, reverse=True) and len(ex) > 900, f"{len(ex)}")
    e = "2026-10-02" if asset == "BTC" else ex[len(ex)//3]
    st, sh = get(f"/api/sheet?asset={asset}&expiry={e}")
    raw = json.load(open(f"data/setup_review/{asset}/{e}.json"))
    check("sheet row count = source file", len(sh["setups"]) == len(raw["setups"]), f"{len(sh['setups'])} rows for {e}")
    links = [(e, sym, g["iso"], g["dur"], g["url"][sym]) for s in sh["setups"] for g in s["signals"] for sym in g["syms"]][:5]
    if links:
        js = "const c=require('./chart_url');" + "".join(
            f"console.log(c.chartUrl('{asset}','{a}','{b}',new Date('{c_}').getTime(),{d}));" for a, b, c_, d, _ in links)
        node = subprocess.run(["node", "-e", js], capture_output=True, text=True, env=dict(os.environ, DE_NO_LOG_DIR="1")).stdout.split()
        ok = node == [x[4] for x in links]
        check("chart links identical to chart_url.js", ok, "" if ok else f"py {links[0][4]} vs js {node[:1]}")
    else:
        check("chart links identical to chart_url.js", True, "no signals on this expiry to compare")

print("\n== live")
for asset in ("BTC", "ETH"):
    st, lv = get(f"/api/live?asset={asset}")
    rows = lv.get("rows", [])
    names = [r["slot"] for r in rows]
    check(f"{asset} live slots", st == 200 and names[:2] == ["immediate", "next"], str([(r['slot'], r['expiry']) for r in rows]))
    if len(rows) == 3:
        e = [r["expiry"] for r in rows]
        check(f"{asset} weekly = first Friday after the two above", pd.Timestamp(e[2]).weekday() == 4 and e[2] > e[1])

print("\n== inputs")
for q, code in (("/api/payload?asset=XRP", 400), ("/api/payload?asset=BTC&res=7", 400),
                ("/api/sheet?asset=BTC&expiry=../../x", 400), ("/api/setups?asset=BTC", 400),
                ("/api/payload?asset=BTC&res=60&limit=abc", 400)):
    st, _ = get(q); check(f"{q} -> {code}", st == code, f"got {st}")

print(f"\n{'ALL PASSED' if not FAIL else f'{len(FAIL)} FAILED: ' + ', '.join(FAIL)}")
sys.exit(1 if FAIL else 0)
