"""Does the SAME bug class sit under the results that already survived?

pascore failed because a feature computed at bar i was scored against a 100x
entry that could occur EARLIER in day i. Line-age >=100d and wedge breaks are
scored the same way: the break is detected at bar i (confirmed only at that bar's
close) and the target is a 100x entry on the same calendar day, which may have
happened hours before.

If those effects are real forecasts they survive being shifted one day forward.
If they are descriptions of a move already underway, they die.

This does not prove the day-0 results wrong -- a break and a payoff genuinely can
share a day -- but a same-day-only effect is not tradeable, which is the thing
that matters.
"""
import numpy as np, pandas as pd
import approach

B = approach.build()
G = B.groupby("day").agg(age=("age","max"), wedge=("wedge","max"))
cal = pd.read_csv("daily_break_profile.csv", index_col=0, parse_dates=True)
J = cal.join(G, how="left")
J["old"]   = (J.age.fillna(0) >= 100).astype(int)
J["wedge"] = J.wedge.fillna(0).astype(int)
y = (J.n100_0 > 0).astype(int) if "n100_0" in J else (J.n100_3 > 0).astype(int)
J["y"] = y
J["y_next"] = J.y.shift(-1)
J["week"] = J.index.isocalendar().year.astype(str) + "W" + J.index.isocalendar().week.astype(str)

def boot(J, feat, tgt, n=4000, seed=0):
    d = J.dropna(subset=[tgt])
    a = d[d[feat] == 1][tgt].to_numpy(); b = d[d[feat] == 0][tgt].to_numpy()
    wa = d[d[feat] == 1].week.to_numpy(); wb = d[d[feat] == 0].week.to_numpy()
    if len(a) < 20 or len(b) < 20: return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    ua, ub = np.unique(wa), np.unique(wb)
    ia = {w: np.where(wa == w)[0] for w in ua}; ib = {w: np.where(wb == w)[0] for w in ub}
    out = []
    for _ in range(n):
        s1 = a[np.concatenate([ia[w] for w in rng.choice(ua, len(ua), True)])]
        s2 = b[np.concatenate([ib[w] for w in rng.choice(ub, len(ub), True)])]
        out.append(s1.mean() - s2.mean())
    out = np.array(out)
    return a.mean(), b.mean(), (out > 0).mean()

print(f"days={len(J)}  base P(100x) same-day {J.y.mean()*100:.1f}%\n")
print(f"{'feature':<12}{'target':<12}{'fires':>7}{'P(100x)':>10}{'no-fire':>10}{'diff':>9}{'P(diff>0)':>11}")
for feat in ("old", "wedge"):
    for tgt, lab in (("y", "SAME day"), ("y_next", "NEXT day")):
        a, b, p = boot(J, feat, tgt)
        if np.isnan(a): print(f"{feat:<12}{lab:<12} too few"); continue
        print(f"{feat:<12}{lab:<12}{int(J[feat].sum()):>7}{a*100:>9.1f}%{b*100:>9.1f}%"
              f"{100*(a-b):>+8.1f}pp{p:>11.3f}")
