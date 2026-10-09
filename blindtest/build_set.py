"""Build the blind chart set (2026-10-09, his design).

Each chart = one option contract (premium, MARK) plus its underlying (MARK), on 5m bars fetched
from Delta, from the chart's history start to settlement. Stripped of price, strike, asset and date.
The server reveals bars only up to his cursor.

Start point: 40% into the contract's life (min life 24h), with at most 7 days left at the start and
at most 7 days of history before it. The life is measured from its first stored 1h bar to settlement.

Sample of 100 scored charts, plus 3 practice charts that are not scored. The ratio is HIDDEN from him:
  A  40  a >= 10x was available after the start: max over t >= start of (later high / close_t)
  B  30  no >= 10x, but my rising-parabola detector (premium_base4) fired after the start
  C  30  no >= 10x, no detector constraint
B and C are matched to A on option type, moneyness at the start and life bucket, so 'it is far OTM'
is not a tell. Excluded: expiries after 2026-08-31 (he lived through them) and his examples.
Outputs: blindtest/data/charts/<id>.json (served), key.json (NOT served), manifest.json."""
import json, os, re, random, time, urllib.request, numpy as np, pandas as pd
API = "https://api.india.delta.exchange/v2/history/candles"
OUT = "blindtest/data"; os.makedirs(f"{OUT}/charts", exist_ok=True)
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
rnd = random.Random(20261009)

def spot_series(asset):
    import glob
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)): m[int(r[0])] = float(r[4])
        except Exception: pass
    return m
SPOT = {a: spot_series(a) for a in ("BTC", "ETH")}

def candidate(asset, expiry, fn):
    m = SYM.match(fn); typ, K = m.group(1), float(m.group(3))
    try: rows = json.load(open(f"data/candles/{asset}/{expiry}/60/{fn}"))
    except Exception: return None
    settle = int(pd.Timestamp(expiry).timestamp()) + 43200
    a = np.array([[r[0], r[2], r[4]] for r in rows if r[4] is not None and r[0] + 3600 <= settle], float)
    if len(a) < 24: return None
    t0 = int(a[0, 0]); life = settle - t0
    if life < 86400: return None
    start = t0 + int(0.4 * life); start = max(start, settle - 7 * 86400); start -= start % 3600
    hist0 = max(t0, start - 7 * 86400)
    i = np.searchsorted(a[:, 0], start)
    if i >= len(a) - 2: return None
    c, h = a[i:, 2], a[i:, 1]
    fut = np.maximum.accumulate(h[::-1])[::-1]                     # max high from bar k on
    mult = np.nanmax(fut[1:] / np.maximum(c[:-1], 1e-9)) if len(c) > 1 else 0
    S = SPOT[asset].get(start - 3600) or SPOT[asset].get(start)
    if not S or c[0] <= 0: return None
    otm = (K / S - 1) * 100 if typ == "C" else (1 - K / S) * 100
    return dict(asset=asset, expiry=expiry, symbol=fn[:-5], typ=typ, K=K, start=start, hist0=hist0, settle=settle,
                life_h=life / 3600, mult=float(mult), otm=otm, prem0=float(c[0]))

pool = []
for asset in ("BTC", "ETH"):
    exps = [e for e in sorted(os.listdir(f"data/candles/{asset}")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) and "2024-01-01" <= e <= "2026-08-31"]
    for e in exps:
        d = f"data/candles/{asset}/{e}/60"
        if not os.path.isdir(d): continue
        fns = [f for f in os.listdir(d) if SYM.match(f)]
        for fn in rnd.sample(fns, min(6, len(fns))): pool.append((asset, e, fn))
rnd.shuffle(pool)
C = pd.DataFrame([x for x in (candidate(*p) for p in pool) if x])
print(f"candidates {len(C)}; >=10x after start {(C.mult >= 10).mean():.1%}", flush=True)
D = pd.read_parquet("data/premium_base4.parquet", columns=["asset", "expiry", "typ", "K", "t", "kind"])
D = D[D.kind == "pattern"].groupby(["asset", "expiry", "typ", "K"]).t.apply(np.array).to_dict()
C["det"] = [bool(len(v := D.get((r.asset, r.expiry, r.typ, r.K), [])) and ((v >= r.start) & (v < r.settle)).any()) for r in C.itertuples()]
C["mb"] = pd.cut(C.otm, [-1e9, 0, 2, 5, 10, 1e9]).astype(str); C["lb"] = pd.cut(C.life_h, [0, 72, 24*10, 1e9]).astype(str)
C["cell"] = C.typ + C.mb + C.lb
C = C[~C.symbol.isin(["C-BTC-87000-021026", "P-BTC-80500-091026", "P-BTC-81000-091026"])]
A = C[C.mult >= 10].sample(frac=1, random_state=1)
picked, used = [], set()
for r in A.itertuples():
    if len([p for p in picked if p["grp"] == "A"]) >= 40: break
    picked.append({**r._asdict(), "grp": "A"}); used.add(r.symbol)
cells = pd.Series([p["cell"] for p in picked])
for grp, n, m in (("B", 30, (C.mult < 10) & C.det), ("C", 30, C.mult < 10)):
    take = 0
    for cell in cells.sample(frac=1, random_state=2).tolist() * 3:
        if take >= n: break
        q = C[m & (C.cell == cell) & ~C.symbol.isin(used)]
        if q.empty: continue
        r = q.sample(1, random_state=take).iloc[0].to_dict(); picked.append({**r, "grp": grp}); used.add(r["symbol"]); take += 1
prac = C[~C.symbol.isin(used)].sample(3, random_state=3)
for r in prac.to_dict("records"): picked.append({**r, "grp": "practice"})
print(pd.Series([p["grp"] for p in picked]).value_counts().to_dict(), flush=True)

def fetch(sym, a, b):
    out, t = [], a
    while t < b:
        e = min(b, t + 300 * 1500)
        for k in range(5):
            try:
                with urllib.request.urlopen(f"{API}?symbol={sym}&resolution=5m&start={int(t)}&end={int(e)}", timeout=40) as r:
                    out += json.load(r).get("result") or []
                break
            except Exception: time.sleep(1 + 2 * k)
        t = e
    return [[int(c["time"]), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])]
            for c in sorted({int(c["time"]): c for c in out}.values(), key=lambda c: int(c["time"])) if c.get("close") is not None]

key, manifest = {}, []
order = [p for p in picked if p["grp"] == "practice"] + rnd.sample([p for p in picked if p["grp"] != "practice"], len([p for p in picked if p["grp"] != "practice"]))
for n, p in enumerate(order):
    cid = f"c{n:03d}"
    prem = fetch(f"MARK:{p['symbol']}", p["hist0"], p["settle"]); spot = fetch(f"MARK:{p['asset']}USD", p["hist0"], p["settle"])
    if len(prem) < 50 or len(spot) < 50: print("skip (no data)", p["symbol"]); continue
    s0 = next((x[4] for x in spot if x[0] >= p["start"] - 300), spot[0][4])
    sc = 100 / max(x[2] for x in prem if x[0] < p["start"]) if any(x[0] < p["start"] for x in prem) else 100 / prem[0][2]
    rel = lambda rows, f: [[r[0] - p["hist0"]] + [round(v * f, 6) for v in r[1:]] for r in rows]   # times relative, values rescaled
    # prem_pct (premium as % of underlying) is added afterwards by refetching the first bar; see README
    # weekday/time-of-day of every bar is derivable on the server from hist0; the date itself never leaves it
    json.dump(dict(id=cid, typ=p["typ"], K_rel=round(p["K"] / s0, 6), start=p["start"] - p["hist0"], settle=p["settle"] - p["hist0"],
                   prem=rel(prem, sc), spot=rel(spot, 100 / s0)), open(f"{OUT}/charts/{cid}.json", "w"))
    key[cid] = {k: (v if not isinstance(v, (np.floating, np.integer)) else v.item()) for k, v in p.items() if k not in ("Index",)}
    manifest.append(dict(id=cid, practice=p["grp"] == "practice", hist0_dow_tod=p["hist0"]))
    print(cid, p["grp"], p["symbol"], len(prem), flush=True)
json.dump(key, open(f"{OUT}/key.json", "w"), default=str); json.dump(manifest, open(f"{OUT}/manifest.json", "w"))
print("charts", len(manifest))
