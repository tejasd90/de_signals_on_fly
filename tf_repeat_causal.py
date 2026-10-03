"""tf_repeat.py fix (audit): flag a higher-tf event as a repeat when a lower-tf contract
on the same spot/expiry/side had FIRST CROSSED 25x before the higher-tf entry. The old
flag used the PEAK time, which also encodes 'no higher high came later' -- future info
about the same move. First crossing is read from the candle files."""
import json, numpy as np, pandas as pd
K = 25
d = pd.read_parquet("events.parquet", columns=["signal","spot","expiry","duration","symbol","opt_type",
                    "entry_ts","entry_premium","event_id","peak_vs_close","y_10x","y_25x"])
d["t_entry"] = d.entry_ts + d.duration*60
W = d[(d.peak_vs_close >= K) & (d.duration <= 480)].copy()
cross = []
for r in W.itertuples():
    try: c = json.load(open(f"data/candles/{r.spot}/{r.expiry}/{r.duration}/{r.symbol}.json"))
    except Exception: cross.append(np.nan); continue
    t = np.nan
    for x in c:
        if x[0] > r.entry_ts and x[2] >= K*r.entry_premium: t = x[0] + r.duration*60; break
    cross.append(t)
W["t_cross"] = cross
print(f"lower-tf {K}x rows {len(W):,}, crossing found {W.t_cross.notna().mean():.1%}")
lo = W.dropna(subset=["t_cross"]).groupby(["spot","expiry","opt_type","duration"]).t_cross.min().reset_index()
ev = d.groupby(["event_id","spot","expiry","opt_type","duration","t_entry"]).agg(y10=("y_10x","mean"), y25=("y_25x","mean")).reset_index()
hi = ev[ev.duration >= 120].copy()
m = hi.merge(lo, on=["spot","expiry","opt_type"], suffixes=("","_lo"))
m = m[(m.duration_lo*3 <= m.duration) & (m.t_cross <= m.t_entry)]
hi["captured"] = hi.event_id.isin(m.event_id)
hi["tte_h"] = (pd.to_datetime(hi.expiry).astype("int64")//10**9 + 43200 - hi.t_entry)/3600
hi["tb"] = pd.cut(hi.tte_h, [0, 12, 24, 48, 96, 1e4])
print(f"flagged {hi.captured.mean():.1%};  raw P(25x) captured {hi[hi.captured].y25.mean():.3%} vs not {hi[~hi.captured].y25.mean():.3%}")
exp_ = 0; act = 0; n = 0
print(f"{'tte_h':>14} {'captured':>9} {'n':>5} | {'not':>7} {'n':>6}")
for tb, g in hi.groupby("tb", observed=True):
    a, b = g[g.captured], g[~g.captured]
    print(f"{str(tb):>14} {a.y25.mean():>9.3%} {len(a):>5} | {b.y25.mean():>7.3%} {len(b):>6}")
    exp_ += len(a)*b.y25.mean(); act += a.y25.sum(); n += len(a)
print(f"tte-adjusted: captured {act/n:.3%} vs expected {exp_/n:.3%}  -> ratio {act/exp_:.2f}")
# bootstrap the tte-adjusted ratio over expiries
ex = hi.expiry.unique(); rng = np.random.default_rng(0); gi = {e: g for e, g in hi.groupby("expiry")}; rs = []
for _ in range(300):
    s = pd.concat([gi[e] for e in rng.choice(ex, len(ex))]); a_ = e_ = 0
    for tb, g in s.groupby("tb", observed=True):
        c = g[g.captured]; 
        if len(c): a_ += c.y25.sum(); e_ += len(c)*g[~g.captured].y25.mean()
    if e_: rs.append(a_/e_)
print(f"ratio 95% CI [{np.percentile(rs,2.5):.2f}, {np.percentile(rs,97.5):.2f}]")
