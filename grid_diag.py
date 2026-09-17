"""Is the grid's profit MEAN REVERSION, or just drift + fat tails?
Three nested controls, each destroying one thing:
  real          : actual path
  shuffled      : same returns, random order   -> kills autocorrelation, KEEPS drift
  shuf+demeaned : same returns, no drift       -> kills autocorrelation AND drift
  gaussian      : same vol, no drift, no tails -> pure driftless GBM (theory says ~0)
"""
import numpy as np, pandas as pd
from grid_sim import run_grid

rng = np.random.default_rng(7)
print(f"{'symbol':<9}{'real':>9}{'shuffled':>20}{'shuf+demean':>20}{'gaussian':>20}   {'peak':>6} {'ann%/peak':>9}")
for s in ["BTCUSD","ETHUSD","SOLUSD","XRPUSD","DOGEUSD"]:
    d = pd.read_parquet(f"data/perp_candles/{s}.parquet")
    c = d.sort_values(d.columns[0])["c"].to_numpy()
    r = np.diff(np.log(c)); n = len(c); yrs = n/24/365.25
    real = run_grid(c)
    def mc(gen, k=25):
        v = np.array([run_grid(c[0]*np.exp(np.cumsum(np.r_[0, gen()])))['net'] for _ in range(k)])
        return v.mean(), v.std()
    sh   = mc(lambda: rng.permutation(r))
    shdm = mc(lambda: rng.permutation(r - r.mean()))
    ga   = mc(lambda: rng.normal(0, r.std(), n-1))
    ann  = real['net']/real['peak']/yrs*100
    print(f"{s:<9}{real['net']:>9.0f}{sh[0]:>12.0f}+-{sh[1]:<6.0f}{shdm[0]:>12.0f}+-{shdm[1]:<6.0f}"
          f"{ga[0]:>12.0f}+-{ga[1]:<6.0f}   {real['peak']:>6d} {ann:>8.1f}%")
