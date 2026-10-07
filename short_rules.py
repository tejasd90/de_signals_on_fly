"""The two survivors as tradeable rules, scored OUT OF SAMPLE (second half of
time, thresholds fixed on the first half). P&L in % of spot notional per trade;
equity summed per calendar day (all trades that day), no compounding.

  A  high-IV straddle: first 4h bar of the day whose ATM 1-3d straddle implies
     IV >= first-half 80th pct -> sell it. Max one per asset per day.
  B  trendline break: sell the slight-OTM (0.25-2%) option BEHIND the break,
     nearest 1-3d expiry, one strike (the closest to 0.75% OTM).
"""
import numpy as np, pandas as pd, warnings
import levels as LV
from short_base import load
warnings.filterwarnings("ignore")
P = load(); P = P[P.tb == "1-3d"]
T = pd.read_parquet("data/short_straddles.parquet"); T = T[T.tb == "1-3d"]
mid = T.t.median(); cut = T[T.t < mid].iv.quantile(.8)

def stats(lab, E):
    E = E.sort_values("t"); d = E.groupby(E.t // 86400).net.sum()
    d = d.reindex(range(int(d.index.min()), int(d.index.max()) + 1), fill_value=0.0)   # flat days count (review D5)
    eq = d.cumsum(); dd = (eq - eq.cummax()).min()
    yrs = (E.t.max() - E.t.min())/(365*86400)
    sh = d.mean()/d.std()*np.sqrt(365) if d.std() > 0 else np.nan
    print(f"{lab:<34} trades {len(E):>5}  win {E.net.gt(0).mean():.0%}  mean {E.net.mean():+.3f}%  "
          f"per yr {eq.iloc[-1]/yrs:+.1f}%  maxDD {dd:.1f}%  worst trade {E.net.min():.1f}%  "
          f"worst day {d.min():.1f}%  Sharpe(daily) {sh:.2f}  ret/maxDD {eq.iloc[-1]/yrs/abs(dd):.2f}")
    return d

# A
A = T[(T.iv >= cut)].copy(); A["day"] = A.t // 86400
A = A.sort_values("t").drop_duplicates(["asset","day"])
# B
rows = []
for spot in ("BTC","ETH"):
    for tf in (1440, 360, 240):
        conf, arr = LV.all_levels(spot, tf)
        for L in conf:
            i = L["break_i"]
            if L["type"] != "trendline" or not i or i < L["anchor"][1] + 5: continue
            rows.append((spot, L["kind"] == "R", int(arr[i,0]) + tf*60))
Bv = pd.DataFrame(rows, columns=["spot","up","te"]).drop_duplicates()
key = P.set_index(["asset","entry_t","typ"]).sort_index(); out = []
for r in Bv.itertuples():
    t = int(np.ceil(r.te/14400)*14400)
    try: g = key.loc[(r.spot, t, "P" if r.up else "C")]
    except KeyError: continue
    g = g[(g.m >= .25) & (g.m <= 2)]
    if g.empty: continue
    g = g[g.expiry == g.expiry.min()]
    x = g.iloc[(g.m - .75).abs().argmin()]
    out.append(dict(t=t, net=x.net, asset=r.spot))
B = pd.DataFrame(out).drop_duplicates(["t","asset"])
mB = B.t.median()
print(f"IV cut {cut:.2f}\n")
for lab, E, m in (("A high-IV straddle", A, mid), ("B sell behind trendline break", B, mB)):
    stats(lab + "  [in-sample]", E[E.t < m]); stats(lab + "  [OUT-of-sample]", E[E.t >= m])
dA = stats("A, all", A); dB = stats("B, all", B)
C = pd.concat([A[["t","net"]], B[["t","net"]]]); stats("A+B together, all", C)
print(f"\ncorrelation of daily P&L A vs B: {pd.concat([dA,dB],axis=1).fillna(0).corr().iloc[0,1]:+.2f}")
