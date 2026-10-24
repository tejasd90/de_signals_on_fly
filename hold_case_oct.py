"""His 2 Oct rule, checked on the 23-25 Oct expiries he says paid 1:20 and 1:100:
"the lower timeframes do wait after the signals (a few candles in their respective timeframes) and then give
breakout, whereas in higher timeframes either don't give the breakout or they don't wait ... the condition is
that it should HOLD over the wait period, SL should not get hit at least for some strikes."

Every signal (4 types, every duration) on BTC/ETH expiries 23, 24, 25 Oct. Per strike: candles of the signal's own
timeframe built from 5m MARK (API; 24/25 Oct only have 15/60/240/1440 stored). trigger j = the candle whose
close is the entry (build_events convention), SL = its low. Wait W=3 candles: HELD if no low < SL. Entry now =
close[j]; entry after wait = close[j+3]. best = later high / entry; also TRADED best for the winners.
Output: data/hold_case_oct.parquet + printed table."""
import json, os, glob, time, urllib.request, numpy as np, pandas as pd, datetime as dt
BASE = "https://api.india.delta.exchange/v2"; W = 3
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
EXPS = ("2026-10-23", "2026-10-24", "2026-10-25")
_cache = {}

def get(u):
    for k in range(4):
        try:
            with urllib.request.urlopen(u, timeout=45) as r: return json.load(r)
        except Exception: time.sleep(1 + k)
    raise IOError(u)

def m5(sym, traded=False):
    key = (sym, traded)
    if key not in _cache:
        now = int(time.time()); rows = []
        for a in range(now - 6 * 86400, now, 2000 * 300):          # 2000 bars per page
            d = get(f"{BASE}/history/candles?symbol={'' if traded else 'MARK:'}{sym}&resolution=5m&start={a}&end={min(a + 2000 * 300, now)}")
            rows += d.get("result") or []
        df = pd.DataFrame(rows)
        if len(df):
            df = df.astype({"time": int}).drop_duplicates("time").sort_values("time").set_index("time")[["open", "high", "low", "close"]].astype(float)
            if traded and "volume" in pd.DataFrame(rows): pass
        _cache[key] = df
    return _cache[key]

def bars(df, du):
    if du == 5: return df
    g = (df.index // (du * 60)) * du * 60
    b = df.groupby(g).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    return b.iloc[:-1] if len(b) and b.index[-1] + du * 60 > time.time() else b   # closed bars only

def ts(iso): return int(dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S%z").timestamp())

rows = []
for fp in sorted(glob.glob("data/signals/*/*/*/*.json")):
    sig, asset, du, fn = fp.split("/")[2:]
    if fn[:-5] not in EXPS or not du.isdigit(): continue
    du = int(du); settle = ts(fn[:-5] + "T17:30:00+0530")
    d = json.load(open(fp))
    for typ in ("C", "P"):
        for r in d.get(typ) or []:
            for sym in r[6] or []:
                rows.append(dict(signal=sig, asset=asset, expiry=fn[:-5], du=du, typ=typ, sym=sym, entry_ts=ts(r[1]), settle=settle))
S = pd.DataFrame(rows).drop_duplicates()
S = S[S.entry_ts >= int(time.time()) - 5 * 86400]
print(f"{len(S):,} strike-firings, {S.sym.nunique()} contracts", flush=True)
out = []
for sym, g in S.groupby("sym"):
    df = m5(sym)
    if df.empty: continue
    for du, gg in g.groupby("du"):
        b = bars(df[df.index < gg.settle.iloc[0]], du); t = b.index.to_numpy()
        lo, hi, cl = b.low.to_numpy(), b.high.to_numpy(), b.close.to_numpy()
        for _, r in gg.iterrows():
            j = int(np.searchsorted(t, r.entry_ts, side="right")) - 1
            if j < 0 or r.entry_ts - t[j] > du * 60 or cl[j] <= 0: continue
            rec = dict(r, e0=cl[j], sl=lo[j], best_now=hi[j + 1:].max() / cl[j] if j + 1 < len(t) else np.nan,
                       fin_now=cl[-1] / cl[j] if t[-1] + du * 60 >= r.settle else np.nan)
            if j + W < len(t):
                rec.update(held=bool(lo[j + 1:j + W + 1].min() >= lo[j]), e3=cl[j + W], ran=bool(hi[j + 1:j + W + 1].max() >= 2 * cl[j]),
                           best_w=hi[j + W + 1:].max() / cl[j + W] if j + W + 1 < len(t) else np.nan,
                           fin_w=cl[-1] / cl[j + W] if t[-1] + du * 60 >= r.settle else np.nan,
                           peak_t=t[j + W + 1 + int(np.argmax(hi[j + W + 1:]))] if j + W + 1 < len(t) else np.nan)
            out.append(rec)
O = pd.DataFrame(out); O.to_parquet("data/hold_case_oct.parquet")
print(f"scored {len(O):,}")
