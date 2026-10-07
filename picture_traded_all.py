"""Fix for the verification finding of 2026-10-07.

picture_traded.py kept only ACTIVATED rows. 'activated' means the MARK later broke the signal bar's high --
future information. The TRADED convention (fill at the first traded close after the signal) cannot filter
on it, so the traded rates were selected on the future. This fetches traded outcomes for the NON-activated
CALL rows (premium 2-20) on picture days and recomputes every traded rate over ALL rows, per event.
Writes data/picture_traded_nonact.parquet."""
import json, time, urllib.request, numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
API = "https://api.india.delta.exchange/v2/history/candles"
COST = 0.0826; TS = [2, 5, 10, 25, 50, 100, 200, 500]

def traded(sym, a, b):
    out, t = [], a
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

def one(r):
    settle = int(pd.Timestamp(r.expiry).timestamp()) + 43200
    cs = [c for c in traded(r.symbol, int(r.close_t), settle) if (c.get("volume") or 0) > 0 and int(c["time"]) >= int(r.close_t)]
    if not cs: return (np.nan, np.nan)
    return (float(cs[0]["close"]), max(float(c["high"]) for c in cs[1:]) if len(cs) > 1 else float(cs[0]["close"]))

if __name__ == "__main__":
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import r5_picture as RP                     # states (ai, rg) + picture flag per event (activated rows)
    Rp = pd.read_parquet("data/bigmoves_precursors.parquet")
    Rp["spot"] = Rp.sym.str.replace("USD", ""); Rp["day"] = pd.to_datetime(Rp.day).dt.normalize()
    Rp["pic"] = (Rp.wkend <= 0.3) & (Rp.rv7 <= 0.3) & (Rp.dd7 >= 0.6)
    E = pd.read_parquet("events.parquet", columns=["spot", "opt_type", "expiry", "symbol", "entry_ts", "duration", "event_id",
                                                   "activated", "entry_premium"])
    E = E[(E.opt_type == "C") & E.entry_premium.between(2, 20)].copy()
    E["close_t"] = E.entry_ts + E.duration * 60; E["day"] = pd.to_datetime(E.close_t, unit="s").dt.normalize()
    E = E.merge(Rp[["spot", "day", "pic"]], on=["spot", "day"]); E = E[E.pic]
    # R5 state for every picture event (activated or not), computed the same way as r5_picture
    parts = []
    for sp, g in E.groupby("spot"):
        ai_t, ai, rg_t, rg = RP.states(sp)
        j = np.searchsorted(rg_t, g.close_t.to_numpy(), side="right") - 1
        parts.append(g.assign(rg=np.where(j >= 0, rg[np.clip(j, 0, None)], 0)))
    E = pd.concat(parts)
    NA = E[~E.activated].drop_duplicates(["event_id", "symbol"]).reset_index(drop=True)
    print(f"non-activated picture-day call rows to fetch: {len(NA)}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex: res = list(ex.map(one, NA.itertuples()))
    NA["fill"], NA["thigh"] = zip(*res)
    NA.to_parquet("data/picture_traded_nonact.parquet")
    A = pd.read_parquet("data/picture_traded.parquet"); A = A[A.pic].drop_duplicates(["event_id", "symbol"])
    A = A.merge(E[["event_id", "symbol", "rg"]].drop_duplicates(["event_id", "symbol"]), on=["event_id", "symbol"], how="left")
    ALL = pd.concat([A[["event_id", "symbol", "fill", "thigh", "rg", "activated"]], NA[["event_id", "symbol", "fill", "thigh", "rg", "activated"]]])
    ALL["x"] = ALL.thigh / ALL.fill
    for lab, m in (("picture (any R5)", ALL.rg.notna()), ("Setup 1: picture & not R5", ALL.rg != 1)):
        g = ALL[m]
        for scope, gg in (("activated only (biased)", g[g.activated]), ("ALL rows (implementable)", g)):
            ev = pd.DataFrame({f"t{T}": (gg.x >= T).groupby(gg.event_id).mean() for T in TS})
            cells = "  ".join(f"{T}x {ev[f't{T}'].mean():6.2%} ({T*ev[f't{T}'].mean()-1-COST:+.2f})" for T in TS)
            print(f"{lab:<28} {scope:<26} events {len(ev):>5}  never traded {gg.fill.isna().mean():.1%}\n   {cells}")
