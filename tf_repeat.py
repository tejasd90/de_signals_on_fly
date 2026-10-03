"""Tejas's first point: a signal on a HIGHER timeframe after a LOWER timeframe on the
same expiry+side already delivered a multibagger is a repeat of a captured move.

Causal flag: a lower-tf event (duration <= hi_duration/3) on the same spot, expiry
and option type whose PEAK (>= K x entry) printed before the higher-tf event's
entry (trigger close). Using the peak time is conservative: a contract that crossed
K before but peaked after is left unflagged.

Outcome per higher-tf event = mean over its strikes (no best-strike oracle).
Significance: bootstrap over expiries.
"""
import numpy as np, pandas as pd
d = pd.read_parquet("events.parquet", columns=["signal","spot","expiry","duration","opt_type","entry_ts",
                    "event_id","peak_vs_close","bars_to_peak","y_10x","y_25x"])
d["t_entry"] = d.entry_ts + d.duration*60
d["t_peak"] = d.t_entry + d.bars_to_peak*d.duration*60
K = 25
lo = d[(d.peak_vs_close >= K)].groupby(["spot","expiry","opt_type","duration"]).t_peak.min().reset_index()
ev = d.groupby(["event_id","signal","spot","expiry","opt_type","duration","t_entry"]).agg(
        y10=("y_10x","mean"), y25=("y_25x","mean"), peak=("peak_vs_close","median")).reset_index()
hi = ev[ev.duration >= 120].copy()
m = hi.merge(lo, on=["spot","expiry","opt_type"], suffixes=("","_lo"))
m = m[(m.duration_lo*3 <= m.duration) & (m.t_peak <= m.t_entry)]
hi["captured"] = hi.event_id.isin(m.event_id)
def boot(g):
    ex = g.expiry.unique(); rng = np.random.default_rng(0); ix = {e: np.where(g.expiry.values==e)[0] for e in ex}
    c = g.captured.values; y = g.y25.values; out = []
    for _ in range(1000):
        s = np.concatenate([ix[e] for e in rng.choice(ex, len(ex))])
        if c[s].sum() and (~c[s]).sum(): out.append(y[s][c[s]].mean() - y[s][~c[s]].mean())
    return np.percentile(out, [2.5, 97.5])
print(f"higher-tf events (>=120m): {len(hi):,};  flagged as repeat of a captured lower-tf {K}x: {hi.captured.mean():.1%}\n")
print(f"{'duration':>8} {'n':>7} {'flag%':>6} | {'P(25x) captured':>16} {'not':>7} | {'P(10x) cap':>10} {'not':>7} | {'median peak cap':>15} {'not':>6} | diff CI P(25x)")
for dur, g in hi.groupby("duration"):
    if g.captured.sum() < 30: continue
    a, b = g[g.captured], g[~g.captured]; ci = boot(g)
    print(f"{dur:>8} {len(g):>7} {g.captured.mean():>6.1%} | {a.y25.mean():>16.3%} {b.y25.mean():>7.3%} | "
          f"{a.y10.mean():>10.3%} {b.y10.mean():>7.3%} | {a.peak.median():>15.2f} {b.peak.median():>6.2f} | [{ci[0]:+.3%},{ci[1]:+.3%}]")
g = hi; ci = boot(g)
print(f"{'ALL':>8} {len(g):>7} {g.captured.mean():>6.1%} | {g[g.captured].y25.mean():>16.3%} {g[~g.captured].y25.mean():>7.3%} | "
      f"{g[g.captured].y10.mean():>10.3%} {g[~g.captured].y10.mean():>7.3%} | {g[g.captured].peak.median():>15.2f} {g[~g.captured].peak.median():>6.2f} | [{ci[0]:+.3%},{ci[1]:+.3%}]")

# ---- controls: is it the CAPTURE, or just lateness / an earlier lower-tf signal of any outcome? ----
hi["tte_h"] = (pd.to_datetime(hi.expiry).astype("int64")//10**9 + 43200 - hi.t_entry)/3600
anylo = d[d.duration <= 40].groupby(["spot","expiry","opt_type"]).t_entry.min().rename("t_lo").reset_index()
hi = hi.merge(anylo, on=["spot","expiry","opt_type"], how="left")
hi["prior_lo"] = hi.t_lo <= hi.t_entry
hi["tb"] = pd.cut(hi.tte_h, [0, 12, 24, 48, 96, 1e4])
print("\nwithin time-to-expiry bands (P(25x)):")
print(f"{'tte_h':>14} {'captured':>9} {'n':>5} | {'prior lower-tf signal, NOT captured':>36} {'n':>6} | {'no prior':>9} {'n':>6}")
for tb, g in hi.groupby("tb", observed=True):
    a = g[g.captured]; b = g[~g.captured & g.prior_lo]; c = g[~g.captured & ~g.prior_lo]
    print(f"{str(tb):>14} {a.y25.mean():>9.3%} {len(a):>5} | {b.y25.mean():>36.3%} {len(b):>6} | {c.y25.mean():>9.3%} {len(c):>6}")
