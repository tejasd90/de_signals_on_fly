"""Hourly option OI over the final 8 days of every FRIDAY (weekly/monthly) expiry since 2024,
strikes within +-10% of spot 8 days out. For the positioning test (oi_positioning.py): does OI
build in cheap OTM options while price is quiet, before the move?
Output data/opt_oi_week.parquet (asset, expiry, typ, K, t, oi). Resumable; compact."""
import os, re, sys, pandas as pd
from concurrent.futures import ThreadPoolExecutor
from fetch_opt_oi import get, spot_close, SYM
OUT = "data/opt_oi_week.parquet"; H = 8*24

def main():
    have, parts = set(), []
    if os.path.exists(OUT):
        o = pd.read_parquet(OUT); parts.append(o); have = set(zip(o.asset, o.expiry))
    for asset in ("BTC", "ETH"):
        exps = [e for e in sorted(os.listdir(f"data/candles/{asset}")) if not e.startswith(".") and e >= "2024-01-01"
                and pd.Timestamp(e).weekday() == 4 and pd.Timestamp(e) < pd.Timestamp.now() - pd.Timedelta(days=1)]
        for i, e in enumerate(exps):
            if (asset, e) in have: continue
            settle = int(pd.Timestamp(e).timestamp()) + 43200
            S = spot_close(asset, settle - H*3600); d = f"data/candles/{asset}/{e}/60"
            if S is None or not os.path.isdir(d): continue
            syms = [(fn[:-5], m.group(1), float(m.group(3))) for fn in os.listdir(d)
                    for m in [SYM.match(fn)] if m and abs(float(m.group(3))/S - 1) <= 0.10]
            with ThreadPoolExecutor(max_workers=8) as ex:
                res = list(ex.map(lambda s: get(s[0], settle - (H+1)*3600, settle), syms))
            rows = [(asset, e, typ, K, int(c["time"]) + 3600, float(c["close"]))
                    for (sym, typ, K), rr in zip(syms, res) for c in rr if c.get("close") is not None]
            if rows: parts.append(pd.DataFrame(rows, columns=["asset","expiry","typ","K","t","oi"]))
            if (i+1) % 20 == 0:
                pd.concat(parts, ignore_index=True).to_parquet(OUT); print(f"{asset} {i+1}/{len(exps)}", flush=True)
    P = pd.concat(parts, ignore_index=True); P.to_parquet(OUT)
    print(f"wrote {OUT}: {len(P):,} rows, {P.groupby(['asset','expiry']).ngroups} expiries")

if __name__ == "__main__": main()
