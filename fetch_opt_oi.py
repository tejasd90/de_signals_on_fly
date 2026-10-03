"""Option open-interest snapshots before settlement, for the max-pain / pinning tests.

Delta serves historical OI on /v2/history/candles with the `OI:` symbol prefix
(de-signals-delta-oi-iv). For each recent daily expiry, every strike within +-6% of
spot 30h before settlement: hourly OI over the final 30 hours.

Output: data/opt_oi.parquet  (asset, expiry, typ, K, t, oi), t = bar close.
Compact (~a few MB) -- the machine's disk is ~97% full, so nothing per-contract is kept.
Resumable: expiries already in the parquet are skipped.
"""
import json, os, re, sys, time, urllib.request, numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
SYM = re.compile(r"^([CP])-([A-Z]+)-(\d+)-(\d{6})\.json$")
OUT = "data/opt_oi.parquet"
API = "https://api.india.delta.exchange/v2/history/candles"

def get(sym, a, b):
    u = f"{API}?symbol=OI:{sym}&resolution=1h&start={a}&end={b}"
    for k in range(4):
        try:
            with urllib.request.urlopen(u, timeout=45) as r: return json.load(r).get("result") or []
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(2*(k+1)); continue
            return []
        except Exception: time.sleep(1+k)
    return []

def spot_close(asset, t):
    day = pd.Timestamp(t - 3600, unit="s").strftime("%Y-%m-%d")
    try:
        for r in json.load(open(f"data/spot_candles/{asset}/60/{day}")):
            if int(r[0]) == t - 3600: return float(r[4])
    except Exception: pass
    return None

def main(n_per_asset=150, since="2026-03-01"):
    have = set()
    if os.path.exists(OUT):
        o = pd.read_parquet(OUT, columns=["asset","expiry"]); have = set(zip(o.asset, o.expiry))
    parts = [pd.read_parquet(OUT)] if os.path.exists(OUT) else []
    for asset in ("BTC", "ETH"):
        exps = [e for e in sorted(os.listdir(f"data/candles/{asset}")) if since <= e and pd.Timestamp(e) < pd.Timestamp.now() - pd.Timedelta(days=1)]
        exps = exps[-n_per_asset:]
        for i, e in enumerate(exps):
            if (asset, e) in have: continue
            settle = int(pd.Timestamp(e).timestamp()) + 43200
            S = spot_close(asset, settle - 30*3600)
            d = f"data/candles/{asset}/{e}/60"
            if S is None or not os.path.isdir(d): continue
            syms = []
            for fn in os.listdir(d):
                m = SYM.match(fn)
                if m and abs(float(m.group(3))/S - 1) <= 0.06: syms.append((fn[:-5], m.group(1), float(m.group(3))))
            with ThreadPoolExecutor(max_workers=8) as ex:
                res = list(ex.map(lambda s: get(s[0], settle - 31*3600, settle), syms))
            rows = [(asset, e, typ, K, int(c["time"]) + 3600, float(c["close"]))
                    for (sym, typ, K), rr in zip(syms, res) for c in rr if c.get("close") is not None]
            if rows: parts.append(pd.DataFrame(rows, columns=["asset","expiry","typ","K","t","oi"]))
            if (i+1) % 25 == 0:
                pd.concat(parts, ignore_index=True).to_parquet(OUT)
                print(f"{asset} {i+1}/{len(exps)}", flush=True)
    P = pd.concat(parts, ignore_index=True); P.to_parquet(OUT)
    print(f"wrote {OUT}: {len(P):,} rows, {P.groupby(['asset','expiry']).ngroups} expiries")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
