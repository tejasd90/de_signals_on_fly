"""Lead from the 2026-10-07 review: his quiet-before-the-storm PICTURE x his CALL signals.

Picture day d (bigmoves.py precursors, causal percentiles known at the close of d-1):
  quiet weekend (wkend <= 0.3) AND low-vol week (rv7 <= 0.3) AND held up (dd7 >= 0.6).
Signals: his four signals from events.parquet whose trigger CLOSES on day d (UTC), one row per event
(strikes averaged, no best-strike oracle), activated only. Outcome y_25x / y_10x (MARK peak).
Robustness:
  - episodes = consecutive picture days (gap <= 3 days) for each asset; leave-one-episode-out
  - with and without the review's premium filter (2-20)
  - puts on the same days as a direction control
  - week-block bootstrap of the picture-minus-other difference
"""
import numpy as np, pandas as pd
R = pd.read_parquet("data/bigmoves_precursors.parquet")
R["spot"] = R.sym.str.replace("USD", ""); R["day"] = pd.to_datetime(R.day).dt.normalize()
R["pic"] = (R.wkend <= 0.3) & (R.rv7 <= 0.3) & (R.dd7 >= 0.6)
R = R.sort_values(["spot", "day"])
P = R[R.pic].copy(); P["ep"] = (P.groupby("spot").day.diff().dt.days.fillna(99) > 3).cumsum()
R = R.merge(P[["spot", "day", "ep"]], on=["spot", "day"], how="left")
E = pd.read_parquet("events.parquet", columns=["signal", "spot", "opt_type", "entry_ts", "duration", "event_id",
                                               "activated", "entry_premium", "y_10x", "y_25x"])
E = E[E.activated]
E["close_t"] = E.entry_ts + E.duration * 60
E["day"] = pd.to_datetime(E.close_t, unit="s").dt.normalize()
ev = E.groupby("event_id").agg(spot=("spot", "first"), ty=("opt_type", "first"), day=("day", "first"),
                               prem=("entry_premium", "median"), y10=("y_10x", "mean"), y25=("y_25x", "mean"),
                               signal=("signal", "first")).reset_index()
ev = ev.merge(R[["spot", "day", "pic", "ep"]], on=["spot", "day"])
ev["week"] = ev.day.dt.to_period("W").astype(str)
rng = np.random.default_rng(0)

def week_boot(g, n=3000):
    wk = g.week.to_numpy(); u = np.unique(wk); ix = {w: np.where(wk == w)[0] for w in u}
    y, p = g.y25.to_numpy(), g.pic.to_numpy(); out = []
    for _ in range(n):
        s = np.concatenate([ix[w] for w in rng.choice(u, len(u))])
        if p[s].sum() and (~p[s]).sum(): out.append(y[s][p[s]].mean() - y[s][~p[s]].mean())
    out = np.array(out); return np.percentile(out, [2.5, 97.5]), (out <= 0).mean()

for lab, f in (("premium 2-20 (review's filter)", ev.prem.between(2, 20)), ("all premiums", ev.prem > 0)):
    print(f"\n== {lab}")
    for ty in ("C", "P"):
        g = ev[f & (ev.ty == ty)]
        a, b = g[g.pic], g[~g.pic]
        ci, p = week_boot(g)
        print(f"  {'CALLS' if ty=='C' else 'PUTS '}: picture days 25x {a.y25.mean():.2%} (n {len(a)}, {a.day.nunique()} days, {a.ep.nunique()} episodes)"
              f"  other days {b.y25.mean():.2%} (n {len(b)})  diff CI [{ci[0]:+.2%},{ci[1]:+.2%}] P<=0 {p:.3f}   10x {a.y10.mean():.1%} vs {b.y10.mean():.1%}")
        if ty == "C":
            per = a.groupby(["spot", "ep"]).agg(first=("day", "min"), n=("y25", "size"), r25=("y25", "mean")).sort_values("r25", ascending=False)
            print("   per episode (top 8 by 25x rate):"); print(per.head(8).round(3).to_string())
            loo = [a[~((a.spot == s) & (a.ep == e))].y25.mean() for s, e in per.index]
            print(f"   leave-one-episode-out: picture 25x rate ranges {min(loo):.2%} .. {max(loo):.2%} (other days {b.y25.mean():.2%})")
            drop2 = a[~a.set_index(["spot", "ep"]).index.isin(per.index[:2])].y25.mean()
            print(f"   without the 2 best episodes: {drop2:.2%};  episodes with any 25x hit: {(per.r25 > 0).sum()} of {len(per)}")

print("\n== Which part does the work? CALLS, premium 2-20, 25x rate by component")
g = ev[ev.prem.between(2, 20) & (ev.ty == "C")].merge(R[["spot", "day", "wkend", "rv7", "dd7"]], on=["spot", "day"])
g["quiet"] = (g.wkend <= 0.3) & (g.rv7 <= 0.3); g["held"] = g.dd7 >= 0.6
print(g.pivot_table(index="quiet", columns="held", values="y25", aggfunc=["mean", "size"]).round(4).to_string())
for lab, m in (("held up, NOT quiet", g.held & ~g.quiet), ("quiet, NOT held up", g.quiet & ~g.held), ("both (the picture)", g.held & g.quiet)):
    x = g[m]; rest = g[~(g.held & g.quiet)]
    print(f"   {lab:<22} 25x {x.y25.mean():.2%}  n {len(x)}  days {x.day.nunique()}")
