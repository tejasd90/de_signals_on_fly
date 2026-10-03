"""Does informed positioning leave an OI footprint before the move? (Tejas: forces leave
signatures, some in OI; emulate the smart money without their trade logs.)

At every 4h point from 7 days to 1 day before each Friday expiry (data/opt_oi_week.parquet):
  cflow = OI added over the last 24h in OTM CALLS 2-8% above spot / total chain OI 24h ago
  pflow = the same for OTM PUTS 2-8% below
  net   = cflow - pflow                 (someone building upside vs downside)
  quiet = trailing 24h realised vol in the lowest third of that asset's history (causal)
Outcome: buy the 3-6% OTM call (put) of the SAME expiry at that point, hold to expiry, net of
the 8.26% round trip (MARK premiums, data/short_panel.parquet). Also spot max-up / max-down
over the next 72h.
If informed money builds before moves, high cflow (esp. while quiet) -> better call returns,
and high pflow -> better put returns. The control that matters: OI also rises mechanically
when price drifts toward strikes, so the trailing 24h spot move is reported alongside.
Bootstrap over expiries.
"""
import json, glob, os, numpy as np, pandas as pd
from scipy.stats import spearmanr
COST = 0.0826
O = pd.read_parquet("data/opt_oi_week.parquet")
P = pd.read_parquet("data/short_panel.parquet")
P["m"] = np.where(P.typ == "C", P.K/P.S0 - 1, 1 - P.K/P.S0)*100
P = P[P.m.between(3, 6) & (P.prem > 0.0005*P.S0)]
P["r"] = P.payoff/P.prem - 1 - COST
opt = P.groupby(["asset", "expiry", "entry_t", "typ"]).r.mean().unstack()

def spot(asset):
    m = {}
    for p in glob.glob(f"data/spot_candles/{asset}/60/*"):
        if os.path.basename(p).startswith("."): continue
        try:
            for r in json.load(open(p)):
                if r[4] is not None: m[int(r[0]) + 3600] = (float(r[2]), float(r[3]), float(r[4]))
        except Exception: pass
    return m

rows = []
for asset in ("BTC", "ETH"):
    sp = spot(asset)
    ts = np.array(sorted(sp)); cl = np.array([sp[t][2] for t in ts])
    lr = pd.Series(np.log(cl)).diff(); rv24 = pd.Series((lr**2).rolling(24).sum().pipe(np.sqrt).values, index=ts)
    for e, g in O[O.asset == asset].groupby("expiry"):
        settle = int(pd.Timestamp(e).timestamp()) + 43200
        g = g.sort_values("t")
        piv = g.pivot_table(index="t", columns=["typ", "K"], values="oi").sort_index().ffill()
        for t in range(settle - 7*86400, settle - 86400 + 1, 4*3600):
            if t not in sp or (t - 86400) not in sp: continue
            S, S0 = sp[t][2], sp[t - 86400][2]
            a = piv[piv.index <= t]; b = piv[piv.index <= t - 86400]
            if a.empty or b.empty: continue
            now, then = a.iloc[-1], b.iloc[-1]
            tot = then.sum()
            if not tot or not np.isfinite(tot) or tot <= 0: continue
            def flow(typ, lo, hi):
                ks = [k for (ty, k) in now.index if ty == typ and lo <= (k/S - 1 if typ == "C" else 1 - k/S) <= hi]
                return ((now[[(typ, k) for k in ks]] - then[[(typ, k) for k in ks]]).sum())/tot if ks else np.nan
            fut = [sp[x] for x in range(t + 3600, t + 72*3600 + 1, 3600) if x in sp]
            if not fut: continue
            o = opt.loc[(asset, e, t)] if (asset, e, t) in opt.index else None
            rows.append(dict(asset=asset, expiry=e, t=t, cflow=flow("C", .02, .08), pflow=flow("P", .02, .08),
                             mv24=S/S0 - 1, rv24=rv24.get(t - 3600, np.nan),
                             up72=max(f[0] for f in fut)/S - 1, dn72=1 - min(f[1] for f in fut)/S,
                             rc=np.nan if o is None else o.get("C", np.nan), rp=np.nan if o is None else o.get("P", np.nan)))
R = pd.DataFrame(rows).dropna(subset=["cflow", "pflow"])
R["net"] = R.cflow - R.pflow
R["quiet"] = R.groupby("asset").rv24.transform(lambda s: s.rank(pct=True)) <= 1/3
R.to_parquet("data/oi_positioning.parquet")
print(f"{len(R):,} points, {R.expiry.nunique()} expiries; option outcomes on {R.rc.notna().sum():,}\n")

def boot(a, b, n=3000):
    rng = np.random.default_rng(0); ea, eb = a.expiry.unique(), b.expiry.unique()
    ga = {e: x for e, x in a.groupby("expiry")}; gb = {e: x for e, x in b.groupby("expiry")}
    out = []
    for _ in range(n):
        A = pd.concat([ga[e] for e in rng.choice(ea, len(ea))]); B_ = pd.concat([gb[e] for e in rng.choice(eb, len(eb))])
        out.append((A.y.mean(), B_.y.mean()))
    d = np.array([x - y for x, y in out]); return np.percentile(d, [2.5, 97.5]), (d <= 0).mean()

print(f"{'condition':<44}{'n':>6}{'call ret':>10}{'put ret':>9}{'up72':>8}{'dn72':>8}{'trail mv24':>12}")
def line(lab, s):
    print(f"{lab:<44}{len(s):>6}{s.rc.mean():>+10.2f}{s.rp.mean():>+9.2f}{s.up72.mean()*100:>7.2f}%{s.dn72.mean()*100:>7.2f}%{s.mv24.mean()*100:>+11.2f}%")
line("all", R)
for q_lab, s in (("CALL building: cflow top 10%", R[R.cflow >= R.cflow.quantile(.9)]),
                 ("  ...and price QUIET", R[(R.cflow >= R.cflow.quantile(.9)) & R.quiet]),
                 ("PUT building: pflow top 10%", R[R.pflow >= R.pflow.quantile(.9)]),
                 ("  ...and price QUIET", R[(R.pflow >= R.pflow.quantile(.9)) & R.quiet]),
                 ("net toward CALLS top 10%", R[R.net >= R.net.quantile(.9)]),
                 ("net toward PUTS bottom 10%", R[R.net <= R.net.quantile(.1)])):
    line(q_lab, s)
print()
for lab, sel, col in (("call ret | call building & quiet vs rest", (R.cflow >= R.cflow.quantile(.9)) & R.quiet, "rc"),
                      ("put ret  | put building & quiet vs rest", (R.pflow >= R.pflow.quantile(.9)) & R.quiet, "rp"),
                      ("call ret | call building vs rest", R.cflow >= R.cflow.quantile(.9), "rc"),
                      ("put ret  | put building vs rest", R.pflow >= R.pflow.quantile(.9), "rp")):
    a = R[sel].assign(y=R[col]).dropna(subset=["y"]); b = R[~sel].assign(y=R[col]).dropna(subset=["y"])
    ci, p = boot(a, b)
    print(f"{lab:<44} {a.y.mean():+.2f} vs {b.y.mean():+.2f}  diff CI [{ci[0]:+.2f},{ci[1]:+.2f}]  P<=0 {p:.3f}  (expiries {a.expiry.nunique()})")
print("\nrank corr with next-72h direction (up72 - dn72), controlling nothing:")
for c in ("cflow", "pflow", "net", "mv24"):
    print(f"   {c:<6} {spearmanr(R[c], R.up72 - R.dn72).correlation:+.3f}")
