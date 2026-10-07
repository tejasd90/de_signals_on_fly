"""Traded-price check of the lead: picture-day CALL signals vs other-day CALL signals.

Mark multiples on cheap options can be fiction (forward log: mark 0.11 vs lowest print 0.6). For each
strike-row of a call signal (premium 2-20, activated):
  fill   = the first TRADED 1h close after the trigger candle closed (the price you could have paid),
           and the traded high after that, to settlement
  y25_tr = traded high / fill >= 25          (target fill on prints, not on mark)
Picture-day rows: all. Other days: a random sample of the same size (seeded).
Writes data/picture_traded.parquet; resumable is not needed (one pass, ~10 min).
"""
import json, time, urllib.request, numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
API = "https://api.india.delta.exchange/v2/history/candles"

def traded(sym, a, b):
    out = []
    t = a
    while t < b:
        e = min(b, t + 3600 * 1500)
        for k in range(4):
            try:
                with urllib.request.urlopen(f"{API}?symbol={sym}&resolution=1h&start={int(t)}&end={int(e)}", timeout=40) as r:
                    out += json.load(r).get("result") or []
                break
            except Exception: time.sleep(1 + 2 * k)
        t = e
    return sorted({int(c["time"]): c for c in out}.values(), key=lambda c: int(c["time"]))

R = pd.read_parquet("data/bigmoves_precursors.parquet")
R["spot"] = R.sym.str.replace("USD", ""); R["day"] = pd.to_datetime(R.day).dt.normalize()
R["pic"] = (R.wkend <= 0.3) & (R.rv7 <= 0.3) & (R.dd7 >= 0.6)
E = pd.read_parquet("events.parquet", columns=["spot", "opt_type", "expiry", "symbol", "entry_ts", "duration", "event_id",
                                               "activated", "entry_premium", "y_25x", "peak_vs_close"])
E = E[E.activated & (E.opt_type == "C") & E.entry_premium.between(2, 20)].copy()
E["close_t"] = E.entry_ts + E.duration * 60
E["day"] = pd.to_datetime(E.close_t, unit="s").dt.normalize()
E = E.merge(R[["spot", "day", "pic"]], on=["spot", "day"])
pic = E[E.pic]; oth = E[~E.pic].sample(len(pic), random_state=0)
S = pd.concat([pic, oth]).reset_index(drop=True)
print(f"rows: picture {len(pic)}, other (sample) {len(oth)}", flush=True)

def one(r):
    settle = int(pd.Timestamp(r.expiry).timestamp()) + 43200
    cs = traded(r.symbol, int(r.close_t), settle)
    cs = [c for c in cs if (c.get("volume") or 0) > 0 and int(c["time"]) >= int(r.close_t)]
    if not cs: return (np.nan, np.nan)
    fill = float(cs[0]["close"]); hi = max(float(c["high"]) for c in cs[1:]) if len(cs) > 1 else fill
    return (fill, hi)

with ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(one, S.itertuples()))
S["fill"], S["thigh"] = zip(*res)
S["traded_any"] = S.fill.notna()
S["y25_tr"] = (S.thigh / S.fill >= 25) & S.traded_any
S.to_parquet("data/picture_traded.parquet")
ev = S.groupby("event_id").agg(pic=("pic", "first"), y25_mark=("y_25x", "mean"), y25_tr=("y25_tr", "mean"),
                               traded=("traded_any", "mean"), week=("day", "first"))
ev["week"] = pd.to_datetime(ev.week).dt.to_period("W").astype(str)
rng = np.random.default_rng(0)
for col in ("y25_mark", "y25_tr"):
    wk = ev.week.to_numpy(); u = np.unique(wk); ix = {w: np.where(wk == w)[0] for w in u}
    y, p = ev[col].to_numpy(), ev.pic.to_numpy(); d = []
    for _ in range(3000):
        s = np.concatenate([ix[w] for w in rng.choice(u, len(u))])
        if p[s].sum() and (~p[s]).sum(): d.append(y[s][p[s]].mean() - y[s][~p[s]].mean())
    print(f"{col:<9} picture {ev[ev.pic][col].mean():.2%}  other {ev[~ev.pic][col].mean():.2%}  diff CI [{np.percentile(d,2.5):+.2%},{np.percentile(d,97.5):+.2%}]")
print(f"share of strike-rows that ever traded after the signal: picture {S[S.pic].traded_any.mean():.0%}, other {S[~S.pic].traded_any.mean():.0%}")
print(f"median fill / mark entry: picture {(S[S.pic].fill/S[S.pic].entry_premium).median():.2f}, other {(S[~S.pic].fill/S[~S.pic].entry_premium).median():.2f}")
