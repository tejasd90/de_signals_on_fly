"""Theory says a grid on a DRIFTLESS walk must be ~0 EV. grid_diag showed it
positive. Find out whether that is a real effect or an accounting artifact by
scaling vol: if net ~ sigma^2 it is the constant-notional/log-vs-simple
convexity (Jensen), i.e. an artifact that inflates every number in the table."""
import numpy as np
from grid_sim import run_grid
rng = np.random.default_rng(3); n = 22000; base = 0.005   # ~BTC hourly sigma
print(f"{'sigma':>8}{'x base':>8}{'net mean':>11}{'SE':>8}{'realized':>11}{'unreal':>11}{'peak':>7}{'net/s^2':>10}")
for m in [0.25, 0.5, 1.0, 2.0]:
    s = base*m; R=[];RE=[];UN=[];PK=[]
    for _ in range(40):
        r = run_grid(100*np.exp(np.cumsum(rng.normal(0, s, n))), fee_pct=0.0)
        R.append(r['net']); RE.append(r['realized']); UN.append(r['unreal']); PK.append(r['peak'])
    R=np.array(R)
    print(f"{s:>8.4f}{m:>8.2f}{R.mean():>11.1f}{R.std()/np.sqrt(len(R)):>8.1f}"
          f"{np.mean(RE):>11.1f}{np.mean(UN):>11.1f}{np.mean(PK):>7.0f}{R.mean()/(s*s):>10.0f}")
