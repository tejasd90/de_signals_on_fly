"""Is the 13:30-14:30 IST strangle drop in TRADED prices, or only in Delta's MARK?
Sample 2026 expiry-days at 1-5 DTE; strikes +-2% OTM at 07:00 UTC; compare the change over the
08:00-09:00 UTC bar (13:30-14:30 IST) with the 06:00-07:00 UTC bar as a control, on MARK: and
plain (traded, volume>0) 1h candles."""
import json, os, re, time, urllib.request, random, numpy as np, pandas as pd
from decay_modes import spot
API = "https://api.india.delta.exchange/v2/history/candles"
def c1h(sym, a, b):
    for k in range(3):
        try:
            with urllib.request.urlopen(f"{API}?symbol={sym}&resolution=1h&start={a}&end={b}", timeout=30) as r:
                return {int(x["time"]): x for x in json.load(r).get("result") or []}
        except Exception: time.sleep(1+k)
    return {}
random.seed(0); rows = []
for asset in ("BTC", "ETH"):
    sp = spot(asset)
    exps = [e for e in sorted(os.listdir(f"data/candles/{asset}")) if e.startswith("2026") and pd.Timestamp(e) < pd.Timestamp("2026-09-30")]
    for e in random.sample(exps, 45):
        exp_t = int(pd.Timestamp(e).timestamp()) + 43200
        for dte in (1, 2, 3):
            day0 = exp_t - 43200 - dte*86400                       # 00:00 UTC, dte days before
            S = sp.get(day0 + 7*3600)
            if S is None: continue
            ks = sorted({float(f.split("-")[2]) for f in os.listdir(f"data/candles/{asset}/{e}/60") if f.endswith(".json")})
            if not ks: continue
            ks = np.array(ks); Kc = ks[np.abs(ks - S*1.02).argmin()]; Kp = ks[np.abs(ks - S*0.98).argmin()]
            tag = pd.Timestamp(e).strftime("%d%m%y")
            legs = [f"C-{asset}-{int(Kc)}-{tag}", f"P-{asset}-{int(Kp)}-{tag}"]
            for kind, pre in (("mark", "MARK:"), ("traded", "")):
                cs = [c1h(pre + s, day0 + 5*3600, day0 + 10*3600) for s in legs]
                def val(t):   # close of the bar OPENING at t, both legs
                    v = []
                    for c in cs:
                        x = c.get(t)
                        if x is None or (kind == "traded" and not (x.get("volume") or 0)): return None
                        v.append(float(x["close"]))
                    return sum(v)
                a6, a7, a8 = val(day0 + 6*3600), val(day0 + 7*3600), val(day0 + 8*3600)
                rows.append(dict(asset=asset, e=e, dte=dte, kind=kind,
                                 ctrl=np.log(a7/a6) if a6 and a7 else np.nan,      # 06-07 -> 07-08 UTC bar
                                 cliff=np.log(a8/a7) if a7 and a8 else np.nan))     # 07-08 -> 08-09 UTC bar
R = pd.DataFrame(rows)
print(R.groupby(["kind", "dte"])[["ctrl", "cliff"]].agg(["mean", "count"]).mul([100, 1, 100, 1]).round(2))
