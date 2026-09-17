#!/usr/bin/env python3
"""
The cash-and-carry is dead on Delta (no hedge for the symbols that pay). But the
funding data says something else: the MEDIAN perp has NEGATIVE carry (-10.9%/yr)
and only 35% are positive. So the money is not "short everything and collect" --
it is a CROSS-SECTIONAL spread, and a spread needs no spot leg at all:

    SHORT the perps paying the most funding   (you receive it)
    LONG  the perps paying the most negative  (shorts pay you)

Both legs are perps, so it is roughly market-neutral and needs no spot, no
transfer, no second venue. The obvious objection is that the carry is just
compensation for adverse price moves -- you would be long the dying tokens.
That is exactly what this measures: total = PRICE p&l + FUNDING p&l.
"""
import glob, os, numpy as np, pandas as pd
RNG = np.random.default_rng(5)
FEE = 0.0005          # 0.05% taker per leg per side; 2 legs in + 2 out per rebal

px, fu = {}, {}
for p in glob.glob("data/perp_candles/*.parquet"):
    s = os.path.basename(p)[:-8]
    d = pd.read_parquet(p)[["ts","c"]].drop_duplicates("ts").sort_values("ts")
    if len(d) > 2000: px[s] = d
for p in glob.glob("data/funding/*.parquet"):
    s = os.path.basename(p)[:-8]
    d = pd.read_parquet(p).drop_duplicates("ts").sort_values("ts")
    d = d[(d.ts % (8*3600)) == 0]
    if len(d) > 300: fu[s] = d
syms = sorted(set(px) & set(fu))
print(f"{len(syms)} symbols with both price and 8h funding history")

t0 = max(min(px[s].ts.min() for s in syms), min(fu[s].ts.min() for s in syms))
t1 = min(max(px[s].ts.max() for s in syms), max(fu[s].ts.max() for s in syms))
MONTH = 30*86400
edges = np.arange(t0 + MONTH, t1, MONTH)
print(f"span {pd.to_datetime(t0,unit='s').date()} .. {pd.to_datetime(t1,unit='s').date()}"
      f"  -> {len(edges)-1} monthly rebalances\n")

def price_at(s, t):
    d = px[s]; i = np.searchsorted(d.ts.to_numpy(), t) - 1
    return d.c.to_numpy()[i] if 0 <= i < len(d) else np.nan
def fund_sum(s, a, b):
    d = fu[s]; t = d.ts.to_numpy()
    m = (t >= a) & (t < b)
    return d.rate.to_numpy()[m].sum()/100.0 if m.sum() else np.nan
def fund_mean_prior(s, t, look=30*86400):
    d = fu[s]; tt = d.ts.to_numpy()
    m = (tt >= t-look) & (tt < t)
    return d.rate.to_numpy()[m].mean() if m.sum() >= 30 else np.nan

recs = []
for k in range(len(edges)-1):
    a, b = edges[k], edges[k+1]
    cand = []
    for s in syms:
        sig = fund_mean_prior(s, a)
        p0, p1 = price_at(s, a), price_at(s, b)
        f = fund_sum(s, a, b)
        if not np.isfinite([sig, p0, p1, f]).all() or p0 <= 0: continue
        cand.append((s, sig, p1/p0 - 1.0, f))
    if len(cand) < 40: continue
    C = pd.DataFrame(cand, columns=["sym","sig","pret","fsum"]).sort_values("sig")
    n = max(5, len(C)//10)
    lo = C.head(n)      # most NEGATIVE funding -> go LONG, shorts pay you
    hi = C.tail(n)      # most POSITIVE funding -> go SHORT, longs pay you
    # side = +1 long, -1 short.  funding pnl = -side * fsum
    lp = lo.pret.mean();            lf = (-1)*(+1)*lo.fsum.mean()
    sp = (-1)*hi.pret.mean();       sf = (-1)*(-1)*hi.fsum.mean()
    gross = 0.5*(lp+sp) + 0.5*(lf+sf)
    recs.append(dict(t=a, n=len(C), k=n,
                     price=0.5*(lp+sp), fund=0.5*(lf+sf),
                     gross=gross, net=gross - 2*FEE*2,
                     long_only_f=lf, short_only_f=sf,
                     long_p=lp, short_p=sp))
M = pd.DataFrame(recs)
print(f"{len(M)} monthly periods, median {M.n.median():.0f} eligible symbols, "
      f"decile size ~{M.k.median():.0f} per leg\n")
print("="*80)
print("MARKET-NEUTRAL FUNDING-CARRY SPREAD, monthly rebalanced, equal weight")
print("="*80)
print(f"  {'component':<34}{'mean/month':>13}{'annualised':>13}")
for lab, col in [("FUNDING collected", "fund"), ("PRICE p&l", "price"),
                 ("GROSS total", "gross"), ("NET of 0.20% round-trip", "net")]:
    print(f"  {lab:<34}{M[col].mean()*100:>+12.2f}%{((1+M[col].mean())**12-1)*100:>+12.1f}%")
print(f"\n  {'leg detail':<34}{'funding':>13}{'price':>13}")
print(f"  {'LONG leg (negative funders)':<34}{M.long_only_f.mean()*100:>+12.2f}%"
      f"{M.long_p.mean()*100:>+12.2f}%")
print(f"  {'SHORT leg (positive funders)':<34}{M.short_only_f.mean()*100:>+12.2f}%"
      f"{M.short_p.mean()*100:>+12.2f}%")
r = M.net.to_numpy()
bs = np.array([RNG.choice(r, len(r), replace=True).mean() for _ in range(5000)])
print(f"\n  NET mean {r.mean()*100:+.2f}%/month   95% CI "
      f"[{np.percentile(bs,2.5)*100:+.2f}%,{np.percentile(bs,97.5)*100:+.2f}%]"
      f"   P(<=0) = {(bs<=0).mean():.3f}")
print(f"  months positive: {(r>0).mean()*100:.0f}%   "
      f"worst {r.min()*100:+.1f}%   best {r.max()*100:+.1f}%   sd {r.std()*100:.1f}%")
print(f"\n  NOTE: survivorship — only symbols alive at both ends of a month are")
print(f"  eligible, which flatters the LONG leg (delisted tokens drop out).")
M.to_csv("runs/carry_portfolio.csv", index=False)
print("  saved runs/carry_portfolio.csv")
