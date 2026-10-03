"""Were high-IV straddle premiums actually printable? Mark vs traded close.

The panel prices entries at MARK. For a random sample of IV-Q5 and of other
straddles, fetch the TRADED 1h candle (plain symbol, not MARK:) at the entry bar
and compare. If traded/mark is systematically below 1 only in Q5, the edge is
partly a mark artefact.
"""
import json, time, urllib.request, numpy as np, pandas as pd
from short_base import load
T = pd.read_parquet("data/short_straddles.parquet")
cut = T[T.t < T.t.median()].iv.quantile(.8); T["hi"] = T.iv >= cut
P = load(); P = P.assign(dist=(P.K-P.S0).abs())
atm = P.loc[P.groupby(["asset","entry_t","expiry","typ"]).dist.idxmin()][["asset","entry_t","expiry","typ","K","prem"]]
rng = np.random.default_rng(1)
S = pd.concat([T[T.hi].sample(80, random_state=1), T[~T.hi].sample(80, random_state=1)])
def traded(sym, t):
    u = f"https://api.india.delta.exchange/v2/history/candles?symbol={sym}&resolution=1h&start={t-7200}&end={t}"
    try: r = json.load(urllib.request.urlopen(u, timeout=30)).get("result") or []
    except Exception: return None
    r = [x for x in r if int(x["time"]) == t-3600 and (x.get("volume") or 0) > 0]
    return float(r[0]["close"]) if r else None
out = []
for s in S.itertuples():
    legs = atm[(atm.asset==s.asset)&(atm.entry_t==s.t)]
    for l in legs.itertuples():
        if pd.Timestamp(l.expiry).timestamp()+43200 - s.t > 3*86400: continue
        sym = f"{l.typ}-{l.asset}-{int(l.K)}-{pd.Timestamp(l.expiry).strftime('%d%m%y')}"
        tp = traded(sym, s.t); time.sleep(0.05)
        out.append(dict(hi=s.hi, sym=sym, mark=l.prem, traded=tp))
O = pd.DataFrame(out); O["ratio"] = O.traded/O.mark
for h, g in O.groupby("hi"):
    v = g.ratio.dropna()
    print(f"{'IV Q5' if h else 'IV Q1-4'}: legs {len(g)}, traded in entry hour {len(v)} ({len(v)/len(g):.0%}); "
          f"traded/mark median {v.median():.3f}, mean {v.mean():.3f}, p25 {v.quantile(.25):.3f}, p75 {v.quantile(.75):.3f}")
O.to_csv("data/short_fills_sample.csv", index=False)
