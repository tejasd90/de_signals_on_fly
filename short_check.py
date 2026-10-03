"""Robustness for the two survivors of short_cond.py."""
import numpy as np, pandas as pd, warnings
import levels as LV
import short_cond as SC          # reuses P, trades_for, report (re-runs its tests; fine)
warnings.filterwarnings("ignore")
from short_cond import trades_for, report, HDR, P

print("\n=== A. 'sell behind the break': level vs plain momentum ===\n" + HDR)
rows = []
for spot in ("BTC","ETH"):
    for tf in (1440, 360, 240):
        conf, arr = LV.all_levels(spot, tf)
        if arr is None: continue
        h, l, c = arr[:,2], arr[:,3], arr[:,4]; A = LV.atr(h, l, c)
        for L in conf:
            i = L["break_i"]
            if not i or i < 12 or A[i] <= 0: continue
            if L["type"] == "trendline" and i < L["anchor"][1] + 5: continue      # swing not yet knowable
            rows.append(dict(spot=spot, tf=tf, up=L["kind"]=="R", typ_=L["type"],
                             t=int(arr[i,0]) + tf*60, mom=(c[i]-c[i-10])/A[i]))
B = pd.DataFrame(rows).drop_duplicates(["spot","t","up"])
def run(sel, delay=0, flip=False):
    out = []
    for r in sel.itertuples():
        up = r.up if not flip else not r.up
        x = trades_for(r.spot, r.t + delay, "P" if up else "C")
        if x: out.append(dict(zip(["t","ex","net","win"], x)))
    return pd.DataFrame(out)
report("level break -> sell behind (leak-trimmed)", run(B))
for d in (4, 8, 24):
    report(f"  same, entered +{d}h later", run(B, d*3600))
for ty, g in B.groupby("typ_"): report(f"  only {ty}", run(g))
for tf, g in B.groupby("tf"):  report(f"  only tf {tf}", run(g))
for a, g in B.groupby("spot"): report(f"  only {a}", run(g))

# momentum control: every 4h bar, 10-bar move on the same tf, no level at all
M = []
for spot in ("BTC","ETH"):
    for tf in (1440, 360, 240):
        arr = LV.load_tf(spot, tf); h, l, c = arr[:,2], arr[:,3], arr[:,4]; A = LV.atr(h, l, c)
        mom = (c - np.roll(c, 10))/A
        for i in range(20, len(c)):
            if np.isfinite(mom[i]) and A[i] > 0:
                M.append(dict(spot=spot, tf=tf, t=int(arr[i,0])+tf*60, mom=mom[i]))
M = pd.DataFrame(M)
thr = B.mom.abs().median()
print(f"\n  momentum control (no level), |10-bar move| >= {thr:.2f} ATR = median break-bar momentum:")
big = M[M.mom.abs() >= thr].sample(min(8000, (M.mom.abs()>=thr).sum()), random_state=0)
big = big.assign(up=big.mom > 0)
report("momentum only -> sell behind", run(big))
# breaks vs non-break momentum matched in size
nb = big.merge(B[["spot","t"]], on=["spot","t"], how="left", indicator=True)
nb = nb[nb._merge == "left_only"]
report("momentum WITHOUT a break -> sell behind", run(nb))

print("\n=== B. high-IV straddles: where does it come from? ===")
T = pd.read_parquet("data/short_straddles.parquet")
mid = T.t.median(); cut = T[T.t < mid].iv.quantile(.8)
T["hi"] = T.iv >= cut
T["tte_h"] = pd.cut(T.t.map(lambda x: 0), [-1, 1])  # placeholder
T["hrs"] = (T.t % 86400)/3600
print(f"  IV Q5 cut (first half) = {cut:.2f}")
print(HDR)
T2 = T.copy()
pan = P.drop_duplicates(["asset","entry_t","expiry"])[["asset","entry_t","expiry","tte_h"]]
for tb, g in T[T.hi].groupby("tb", observed=True): report(f"IV Q5, tte {tb}", g)
for a, g in T[T.hi].groupby("asset"): report(f"IV Q5, {a}", g)
T["yr"] = pd.to_datetime(T.t, unit="s").dt.year
for y, g in T[T.hi].groupby("yr"): report(f"IV Q5, {y}", g)
for hh, g in T[T.hi].groupby(pd.cut(T[T.hi].hrs, [-1,3,7,11,15,19,23])): report(f"IV Q5, entry hour UTC {hh}", g)
print(f"\n  IV Q5 straddle net, % spot: p1 {T[T.hi].net.quantile(.01):+.2f}  p5 {T[T.hi].net.quantile(.05):+.2f}  "
      f"median {T[T.hi].net.median():+.2f}  worst {T[T.hi].net.min():+.2f}")
