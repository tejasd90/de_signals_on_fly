"""Build the blind chart set, v2 (2026-10-09, his refinements).

One CHART = one (asset, expiry, call/put) at a start moment, shown as a ladder of strikes, because live he
decides from several strikes:
  - the 5 nearest OTM strikes at the start (not deep OTM), plus up to 3 further OTM strikes that he
    may reveal on request (each request is logged);
  - the underlying, with 30 days of history before the start (for context such as consecutive 12h reds).
Candles: 15m MARK from Delta (no 5m). The server offers 1h / 4h / 12h at all times and 15m ONLY on
expiry day (the IST date of settlement).
Start: 40% into the expiry's life (min 24h), with at most 7 days left; premium history up to 7 days.

Sample of 100 scored charts plus 3 practice charts (the ratio is HIDDEN from him):
  A  40  at least one of the 5 strikes offered >= 10x after the start
         (max over t >= start of later high / close_t, on 1h)
  B  30  none did, but my rising-parabola detector (premium_base4) fired on one of them after the start
  C  30  none did
B and C are matched to A on call/put and expiry-life bucket. Expiries 2024-01 -> 2026-08 only; his
examples are excluded.
Outputs: data/charts/<id>.json (served, anonymised), data/key.json (never served), data/manifest.json."""
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

def load1h(asset, expiry, fn, settle):
    try: rows = json.load(open(f"data/candles/{asset}/{expiry}/60/{fn}"))
    except Exception: return None
    a = np.array([[r[0], r[2], r[4]] for r in rows if r[4] is not None and r[0] + 3600 <= settle], float)
    return a if len(a) else None

def mult_after(a, start):
    i = np.searchsorted(a[:, 0], start)
    if i >= len(a) - 1: return 0.0
    c, h = a[i:, 2], a[i:, 1]; fut = np.maximum.accumulate(h[::-1])[::-1]
    return float(np.max(fut[1:] / np.maximum(c[:-1], 1e-9)))

def candidate(asset, expiry, typ):
    settle = int(pd.Timestamp(expiry).timestamp()) + 43200
    d = f"data/candles/{asset}/{expiry}/60"
    S = {}
    for fn in os.listdir(d):
        m = SYM.match(fn)
        if m and m.group(1) == typ:
            a = load1h(asset, expiry, fn, settle)
            if a is not None: S[float(m.group(3))] = (fn[:-5], a)
    if len(S) < 8: return None
    t0 = int(min(a[0, 0] for _, a in S.values())); life = settle - t0
    if life < 86400: return None
    start = max(t0 + int(0.4 * life), settle - 7 * 86400); start -= start % 3600
    spot = SPOT[asset].get(start - 3600) or SPOT[asset].get(start)
    if not spot: return None
    live = {K: v for K, v in S.items() if v[1][0, 0] <= start - 3600 and np.searchsorted(v[1][:, 0], start) < len(v[1]) - 1}
    otm = sorted([K for K in live if (K > spot if typ == "C" else K < spot)], key=lambda K: abs(K - spot))
    if len(otm) < 8: return None
    ladder = otm[:8]
    mults = [mult_after(live[K][1], start) for K in ladder[:5]]
    return dict(asset=asset, expiry=expiry, typ=typ, start=start, t0=t0, settle=settle, life_h=life / 3600, spot0=spot,
                strikes=ladder, symbols=[live[K][0] for K in ladder], mult5=max(mults), mults=mults)

pool = []
for asset in ("BTC", "ETH"):
    for e in sorted(os.listdir(f"data/candles/{asset}")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) and "2024-01-01" <= e <= "2026-08-31" and os.path.isdir(f"data/candles/{asset}/{e}/60"):
            pool += [(asset, e, "C"), (asset, e, "P")]
rnd.shuffle(pool)
C = pd.DataFrame([x for x in (candidate(*p) for p in pool[:1400]) if x])
print(f"candidates {len(C)}; any of 5 strikes >=10x after start {(C.mult5 >= 10).mean():.1%}", flush=True)
D = pd.read_parquet("data/premium_base4.parquet", columns=["asset", "expiry", "typ", "K", "t", "kind"])
D = D[D.kind == "pattern"].groupby(["asset", "expiry", "typ", "K"]).t.apply(np.array).to_dict()
C["det"] = [any(len(v := D.get((r.asset, r.expiry, r.typ, K), [])) and ((v >= r.start) & (v < r.settle)).any() for K in r.strikes[:5]) for r in C.itertuples()]
C["lb"] = pd.cut(C.life_h, [0, 72, 24 * 10, 1e9]).astype(str); C["cell"] = C.typ + C.lb
C = C[~C.apply(lambda r: r.asset == "BTC" and r.expiry in ("2026-10-02", "2026-10-09"), axis=1)]
A = C[C.mult5 >= 10].sample(frac=1, random_state=1).head(40); picked = [{**r, "grp": "A"} for r in A.to_dict("records")]
used = set(A.index)
for grp, n, m in (("B", 30, (C.mult5 < 10) & C.det), ("C", 30, C.mult5 < 10)):
    take = 0
    for cell in A.cell.sample(frac=1, random_state=2).tolist() * 3:
        if take >= n: break
        q = C[m & (C.cell == cell) & ~C.index.isin(used)]
        if q.empty: continue
        ix = q.sample(1, random_state=take).index[0]; picked.append({**C.loc[ix].to_dict(), "grp": grp}); used.add(ix); take += 1
for r in C[~C.index.isin(used)].sample(3, random_state=3).to_dict("records"): picked.append({**r, "grp": "practice"})
print(pd.Series([p["grp"] for p in picked]).value_counts().to_dict(), flush=True)

def fetch(sym, a, b, res="15m", sec=900):
    out, t = [], a
    while t < b:
        e = min(b, t + sec * 1500)
        for k in range(5):
            try:
                with urllib.request.urlopen(f"{API}?symbol={sym}&resolution={res}&start={int(t)}&end={int(e)}", timeout=40) as r:
                    out += json.load(r).get("result") or []
                break
            except Exception: time.sleep(1 + 2 * k)
        t = e
    return [[int(c["time"]), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])]
            for c in sorted({int(c["time"]): c for c in out}.values(), key=lambda c: int(c["time"])) if c.get("close") is not None]

for f in os.listdir(f"{OUT}/charts"): os.remove(f"{OUT}/charts/{f}")
key, manifest = {}, []
order = [p for p in picked if p["grp"] == "practice"] + rnd.sample([p for p in picked if p["grp"] != "practice"], len(picked) - 3)
for n, p in enumerate(order):
    cid = f"c{n:03d}"; h0 = max(p["t0"], p["start"] - 7 * 86400); u0 = p["start"] - 30 * 86400
    spot = fetch(f"MARK:{p['asset']}USD", u0, p["settle"])
    s0 = next((x[4] for x in spot if x[0] >= p["start"] - 900), None)
    prem = [fetch(f"MARK:{s}", h0, p["settle"]) for s in p["symbols"]]
    if s0 is None or any(len(x) < 20 for x in prem[:5]): print("skip", cid, p["symbols"][0]); continue
    strikes = []
    for K, rows in zip(p["strikes"], prem):
        before = [x for x in rows if x[0] < p["start"]]
        sc = 100 / max(x[2] for x in before) if before else 100 / max(rows[0][2], 1e-9)
        strikes.append(dict(K_rel=round(K / s0, 6), pct=1 / sc / (s0 / 100),   # premium % of underlying = rel * pct * 100 / spot_rel
                            rows=[[x[0] - u0] + [round(v * sc, 6) for v in x[1:]] for x in rows]))
    json.dump(dict(id=cid, typ=p["typ"], start=p["start"] - u0, settle=p["settle"] - u0,
                   spot=[[x[0] - u0] + [round(v * 100 / s0, 6) for v in x[1:]] for x in spot], strikes=strikes), open(f"{OUT}/charts/{cid}.json", "w"))
    key[cid] = {k: v for k, v in p.items()}; manifest.append(dict(id=cid, practice=p["grp"] == "practice", t_origin=u0))
    print(cid, p["grp"], p["asset"], p["expiry"], p["typ"], f"{p['mult5']:.1f}", flush=True)
json.dump(key, open(f"{OUT}/key.json", "w"), default=lambda o: o.item() if hasattr(o, "item") else str(o))
json.dump(manifest, open(f"{OUT}/manifest.json", "w")); print("charts", len(manifest))
