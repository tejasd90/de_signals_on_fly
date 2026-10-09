"""Setup 1 with the premium band removed: does the mark-price advantage of sub-2 premiums survive on
TRADED prices? Same implementable convention as picture_traded_all.py: buy at the close of the first
traded 1h candle opening at/after the signal close (volume > 0), exit at the target on later traded
highs; all rows (no activation filter), per event then the mean. Each symbol is fetched once.
Writes data/picture_traded_sub2.parquet (results only)."""
import io, contextlib, json, time, urllib.request, numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
API = "https://api.india.delta.exchange/v2/history/candles"; COST = 0.0826; TS = [10, 25, 50, 100]
src = open("setup1_relax.py").read().split('print(f"rows')[0].replace(
    '"entry_premium", "peak_vs_trigger", "peak_vs_close"]', '"entry_premium", "peak_vs_trigger", "peak_vs_close", "symbol", "expiry"]')
with contextlib.redirect_stdout(io.StringIO()): exec(src)
pic = (E.wkend <= .3) & (E.rv7 <= .3) & (E.dd7 >= .6)
G = E[E.spot.isin(["BTC", "ETH"]) & (E.opt_type == "C") & (E.pb == "<2") & pic].drop_duplicates(["event_id", "symbol"]).copy()
print(f"rows {len(G)}, events {G.event_id.nunique()}, symbols {G.symbol.nunique()}", flush=True)

def fetch(sym, a, b):
    out, t = [], a
    while t < b:
        e = min(b, t + 3600 * 1500)
        for k in range(5):
            try:
                with urllib.request.urlopen(f"{API}?symbol={sym}&resolution=1h&start={int(t)}&end={int(e)}", timeout=40) as r:
                    out += json.load(r).get("result") or []
                break
            except Exception: time.sleep(1 + 2 * k)
        t = e
    return sorted({int(c["time"]): c for c in out if (c.get("volume") or 0) > 0}.values(), key=lambda c: int(c["time"]))

def per_symbol(item):
    sym, g = item
    settle = int(pd.Timestamp(g.expiry.iloc[0]).timestamp()) + 43200
    cs = fetch(sym, int(g.t.min()) - 3600, settle)
    tt = np.array([int(c["time"]) for c in cs]); res = []
    for r in g.itertuples():
        k = np.searchsorted(tt, int(r.t))
        if k >= len(cs): res.append((r.event_id, sym, np.nan, np.nan)); continue
        fill = float(cs[k]["close"]); hi = max((float(c["high"]) for c in cs[k+1:]), default=fill)
        res.append((r.event_id, sym, fill, hi))
    return res
with ThreadPoolExecutor(8) as ex: out = [x for r in ex.map(per_symbol, G.groupby("symbol")) for x in r]
O = pd.DataFrame(out, columns=["event_id", "symbol", "fill", "thigh"]).merge(G[["event_id", "symbol", "rg", "entry_premium", "week", "spot"]], on=["event_id", "symbol"])
O.to_parquet("data/picture_traded_sub2.parquet")
O["x"] = O.thigh / O.fill
print(f"never traded {O.fill.isna().mean():.1%}; median fill/mark {np.nanmedian(O.fill / O.entry_premium):.2f}")
rng = np.random.default_rng(0)
for lab, m in (("picture, any R5", O.rg.notna()), ("Setup 1 cell: picture & !R5", O.rg != 1)):
    g = O[m]; ev = pd.DataFrame({T: (g.x >= T).groupby(g.event_id).mean() for T in TS}); wk = g.groupby("event_id").week.first()
    u = wk.unique(); ix = {w: np.where(wk.to_numpy() == w)[0] for w in u}; v = ev[25].to_numpy()
    b = [v[np.concatenate([ix[w] for w in rng.choice(u, len(u))])].mean() for _ in range(500)]
    print(f"{lab:<30} events {len(ev)}  " + "  ".join(f"{T}x {ev[T].mean():.2%} ({T*ev[T].mean()-1-COST:+.2f})" for T in TS)
          + f"  25x CI [{np.percentile(b,2.5):.1%},{np.percentile(b,97.5):.1%}]")
    for a, h in g.groupby("spot"):
        e2 = pd.DataFrame({T: (h.x >= T).groupby(h.event_id).mean() for T in TS}); print(f"    {a}: events {len(e2)} 25x {e2[25].mean():.2%} 100x {e2[100].mean():.2%}")
