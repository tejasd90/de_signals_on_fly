"""Wait-and-hold (W=3) combined with repeat-muting, per signal and timeframe group.
Repeat flag recomputed causally as in tf_repeat.py, for ALL durations (lower tf =
duration <= this/3)."""
import io, contextlib, numpy as np, pandas as pd
R = pd.read_parquet("data/tf_hold.parquet")
d = pd.read_parquet("events.parquet", columns=["spot","expiry","duration","opt_type","entry_ts","event_id","peak_vs_close","bars_to_peak"])
d["t_entry"] = d.entry_ts + d.duration*60; d["t_peak"] = d.t_entry + d.bars_to_peak*d.duration*60
lo = d[d.peak_vs_close >= 25].groupby(["spot","expiry","opt_type","duration"]).t_peak.min().reset_index()
ev = d.drop_duplicates("event_id")[["event_id","spot","expiry","opt_type","duration","t_entry"]]
m = ev.merge(lo, on=["spot","expiry","opt_type"], suffixes=("","_lo"))
rep = set(m[(m.duration_lo*3 <= m.duration) & (m.t_peak <= m.t_entry)].event_id)
R["repeat"] = R.event_id.isin(rep)
R["grp"] = pd.cut(R.duration, [0, 60, 180, 2000], labels=["30-60m","90-180m","4h-1d"])
W = 3
print(f"repeat-flagged rows: {R.repeat.mean():.1%}\n")
print(f"{'signal':<16}{'tf':<9}| {'now':>7} {'n':>6} | {'hold':>7} {'n':>6} | {'hold+no repeat':>14} {'n':>6} | {'trades kept':>11}   (25x expectancy per unit)")
for (s, gname), g in R.groupby(["signal","grp"], observed=True):
    now = g.v25_0.mean()-1; h = g[f"held_{W}"].astype(bool)
    hv = g.loc[h, f"v25_{W}"].mean()-1; hr = g.loc[h & ~g.repeat, f"v25_{W}"].mean()-1
    print(f"{s:<16}{gname:<9}| {now:>+7.3f} {len(g):>6} | {hv:>+7.3f} {h.sum():>6} | {hr:>+14.3f} {(h&~g.repeat).sum():>6} | {(h&~g.repeat).mean():>10.0%}")
