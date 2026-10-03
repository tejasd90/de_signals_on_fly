"""Is the daily 13:30-14:30 IST (08:00-09:00 UTC) premium cliff on Delta the Deribit settlement?
Deribit's public DVOL index (30-day implied vol) at 1h. If implied vol re-marks at Deribit's
08:00 UTC daily expiry, DVOL's mean hourly change should dip in that hour as well."""
import json, time, urllib.request, numpy as np, pandas as pd
def dvol(cur, a, b):
    u = f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency={cur}&start_timestamp={a*1000}&end_timestamp={b*1000}&resolution=3600"
    with urllib.request.urlopen(u, timeout=30) as r: return json.load(r)["result"]["data"]
for cur in ("BTC", "ETH"):
    end = int(time.time()); rows = []
    for k in range(8):                               # ~ 8 x 40 days of hourly points
        b = end - k*40*86400; a = b - 40*86400
        try: rows += dvol(cur, a, b)
        except Exception as ex: print(cur, "fetch failed", ex); break
        time.sleep(0.3)
    d = pd.DataFrame(rows, columns=["ts","o","h","l","c"]).drop_duplicates("ts").sort_values("ts")
    d["dt"] = pd.to_datetime(d.ts, unit="ms"); d["ch"] = np.log(d.c).diff()*100
    d["hr"] = d.dt.dt.hour                             # bar OPEN hour, UTC
    prof = d.groupby("hr").ch.agg(["mean", "count"])
    print(f"\n{cur} DVOL, {d.dt.min().date()} .. {d.dt.max().date()}: mean hourly log-change (%) by UTC hour the bar OPENS")
    print("  " + "  ".join(f"{h:02d}:{prof.loc[h,'mean']:+.2f}" for h in prof.index))
    m = prof["mean"]; print(f"  08:00 UTC bar {m.loc[8]:+.3f}%  vs median hour {m.median():+.3f}%  (rank {int((m < m.loc[8]).sum())+1} of 24, lowest = 1)")
