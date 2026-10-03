"""Replace 'last candle in the file' with true settlement intrinsic (spot at 12:00 UTC
on expiry), then recompute held-vs-now, net of cost, by call/put."""
import numpy as np, pandas as pd, json
from short_panel import spot_series
COST = 0.0826; W = 3; K = 25
R = pd.read_parquet("data/tf_hold.parquet")
E = pd.read_parquet("events.parquet", columns=["symbol","entry_premium"])
R = R.join(E)
p = R.symbol.str.split("-", expand=True); R["typ"] = p[0]; R["K"] = p[2].astype(float)
ST = {}
for a in ("BTC","ETH"):
    s = spot_series(a)
    for e in R.loc[R.spot == a, "expiry"].unique():
        ST[(a, e)] = s.get(int(pd.Timestamp(e).timestamp()) + 12*3600 - 3600)
R["S_T"] = [ST.get(k) for k in zip(R.spot, R.expiry)]
R = R.dropna(subset=["S_T"])
R["intr"] = np.where(R.typ == "C", (R.S_T - R.K).clip(lower=0), (R.K - R.S_T).clip(lower=0))
# entry prices: e0 = entry_premium; eW unknown here -> recover from v at W? store ratio instead:
# v{K}_W = K if hit else min(fin_W, K) where fin_W = last/eW. We need eW: re-derive via fin ratio of W=0.
# fin_0 = last/e0 and fin_W = last/eW  =>  eW = e0 * fin_0 / fin_W  (valid when neither hit)
nh = ~R[f"h{K}_0"] & ~R[f"h{K}_{W}"] & (R[f"v{K}_{W}"] > 0)
R["eW"] = np.where(nh, R.entry_premium * R[f"v{K}_0"] / R[f"v{K}_{W}"].replace(0, np.nan), np.nan)
R["last_vs_intr"] = R[f"v{K}_0"]*R.entry_premium - R.intr       # last candle minus true settlement, per coin
print(f"rows {len(R):,}; last-candle value minus true settlement (non-hits): median {R.loc[nh,'last_vs_intr'].median():.2f}, "
      f"mean ratio last/entry {R.loc[nh, f'v{K}_0'].mean():.3f} vs intrinsic/entry {(R.loc[nh,'intr']/R.loc[nh,'entry_premium']).mean():.3f}")
R["v0s"] = np.where(R[f"h{K}_0"], K, (R.intr/R.entry_premium).clip(upper=K))
R["vWs"] = np.where(R[f"h{K}_{W}"], K, (R.intr/R.eW).clip(upper=K))
R["grp"] = pd.cut(R.duration, [0, 60, 180, 2000], labels=["30-60m","90-180m","4h-1d"])
print(f"\n{'tf':<9}{'typ':<4}| {'now':>7} {'hold':>7} {'diff':>7}   (settlement intrinsic, net of cost; hold rows with recoverable entry only)")
for (g_, t), g in R.groupby(["grp","typ"], observed=True):
    h = g[f"held_{W}"].astype(bool) & g.vWs.notna()
    now = g.v0s.mean()-1-COST; hold = g.loc[h, "vWs"].mean()-1-COST
    print(f"{g_:<9}{t:<4}| {now:>+7.3f} {hold:>+7.3f} {hold-now:>+7.3f}   n_hold {h.sum()}")
