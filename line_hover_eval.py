"""Evaluate line_hover.py outputs. Near-duplicate lines produce the same event several times, so episodes and
breaks are clustered: same spot / side / outcome ending within 24h of each other count once (the earliest kept).
CIs: 90% block bootstrap by calendar week."""
import numpy as np, pandas as pd
rng = np.random.default_rng(0)
def cluster(D, key=("spot", "kind", "outcome"), gap=24 * 3600):
    D = D.sort_values("end_t"); keep = []
    for _, g in D.groupby(list(key)):
        last = -1e18
        for i, r in g.iterrows():
            if r.end_t - last > gap: keep.append(i); last = r.end_t
    return D.loc[keep]
def boot(D, f, n=500):
    wk = (D.end_t // (7 * 86400)).to_numpy(); u = np.unique(wk); idx = {w: np.where(wk == w)[0] for w in u}; v = []
    for _ in range(n):
        s = np.concatenate([idx[w] for w in rng.choice(u, len(u))]); v.append(f(D.iloc[s]))
    return np.nanpercentile(v, [5, 95])

E = pd.read_parquet("data/line_hover_episodes.parquet").reset_index(drop=True); E = cluster(E)
print(f"episodes after clustering: {len(E)} (break {(E.outcome == 'break').sum()}, reject {(E.outcome == 'reject').sum()})")
print("\n(1) Does hovering predict the break? Among episodes STILL at the line after H hours, share that end in a break:")
for H in (0, 6, 12, 24, 48, 72):
    D = E[E.hover_h > H]; p = (D.outcome == "break").mean(); lo, hi = boot(D, lambda x: (x.outcome == "break").mean())
    print(f"  hovering > {H:>2}h: n={len(D):4d}  break {p:.0%}  [{lo:.0%}, {hi:.0%}]   median hours left until it resolves {(D.hover_h - H).median():.0f}")
print("  by side, hover > 24h vs <= 24h:")
for k, g in E.groupby("kind"):
    print(f"    {'support (down-break)' if k == 'S' else 'resistance (up-break)'}: >24h {(g[g.hover_h > 24].outcome == 'break').mean():.0%} (n={(g.hover_h > 24).sum()})  "
          f"<=24h {(g[g.hover_h <= 24].outcome == 'break').mean():.0%} (n={(g.hover_h <= 24).sum()})")

F = pd.read_parquet("data/line_hover_breaks.parquet").reset_index(drop=True); F["outcome"] = "break"; F = cluster(F)
print(f"\n(2) After the break ({len(F)} clustered breaks): move in the break direction, % (median / share positive), reclaimed within 48h")
def show(g, lab):
    print(f"  {lab:34s} n={len(g):3d}  24h {g.f24.median():+.2f} ({(g.f24 > 0).mean():.0%})  48h {g.f48.median():+.2f} ({(g.f48 > 0).mean():.0%})  "
          f"96h {g.f96.median():+.2f} ({(g.f96 > 0).mean():.0%})  reclaimed {g.reclaimed48.mean():.0%}")
for k, g in F.groupby("kind"): show(g, "support broken DOWN" if k == "S" else "resistance broken UP")
S = F[F.kind == "S"]
for lab, m in [("  hover before break > 24h", S.hover_h > 24), ("  hover <= 24h", S.hover_h <= 24),
               ("  line age > 30 days", S.age_d > 30), ("  line age <= 30 days", S.age_d <= 30),
               ("  touches >= 5", S.touches >= 5), ("  touches 3-4", S.touches < 5),
               ("  6h line", S.tf == 360), ("  4h line", S.tf == 240)]:
    show(S[m], lab)
for lab, m in [("not reclaimed in 48h", ~S.reclaimed48.astype(bool)), ("reclaimed in 48h", S.reclaimed48.astype(bool))]:
    show(S[m], "  support, " + lab)
lo, hi = boot(S, lambda x: x.f96.median()); print(f"  support breaks, 96h median 90% CI [{lo:+.2f}, {hi:+.2f}]")
d = lambda x: x[x.hover_h > 24].f96.median() - x[x.hover_h <= 24].f96.median()
lo, hi = boot(S, d); print(f"  support: long-hover minus short-hover 96h median {d(S):+.2f}  CI [{lo:+.2f}, {hi:+.2f}]")

O = pd.read_parquet("data/line_hover_options.parquet")
O["end_t"] = O.at_t; O["outcome"] = O.what
print("\n(3) Which expiry? first-OTM option on the break side, MARK, x of entry premium (median best later / share best >= 3x / median at settlement / mean at settlement)")
for (what, kind), g in O.groupby(["what", "kind"]):
    g = g.copy(); g["outcome"] = g["rank"].astype(str); print(f"  {what:8s} {'puts' if kind == 'S' else 'calls'}")
    for r, gg in g.groupby("rank"):
        gg = cluster(gg.assign(outcome=what), key=("spot", "kind", "outcome"))
        print(f"     expiry {r}: n={len(gg):3d}  tte {gg.tte_h.median():5.0f}h  prem {gg.prem_pct.median():.2f}%  best {gg.best.median():5.2f}x  >=3x {(gg.best >= 3).mean():4.0%}  "
              f"48h {gg.v48.median():.2f}x  settle median {gg.settle_x.median():.2f}x mean {gg.settle_x.mean():.2f}x")
