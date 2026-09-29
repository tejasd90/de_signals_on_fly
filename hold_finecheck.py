"""Is `hold` real, or residual direction inside an unbounded tail bucket?

The direction control put `hold` at -2.79 dEV on PUTS in spot quintile 1
(P=0.000) -- the only large effect to survive holding direction fixed. But
quintile 1 runs from -2.1% to -infinity. A put's payoff depends steeply on HOW
FAR spot fell, so if `hold` fires more often in mild declines than violent ones,
that -2.79 is direction leaking through a bucket that is too wide, not a signal.

Fix: re-cut the crash region into NARROW bands and require the effect to hold
inside each. A genuine overpricing signal stays negative band by band. Residual
direction collapses once the band is tight enough to fix the payoff.

Also reports where `hold` fires across bands -- if its firing rate slopes with
depth of decline, that is the leak, visible directly.
"""
import numpy as np
from fastboot import week_codes, boot_diff

COST = 0.0826
z = np.load("data/premium_pa_cache2.npz", allow_pickle=True)
wk, otm, sr, typ, F, sret = z["wk"], z["otm"], z["sr"], z["typ"], z["F"], z["sret"]
ev = sr - 1 - COST
HOLD = F[:, 0]

base = (otm >= 2) & (otm <= 15) & (typ == "P") & np.isfinite(sret)
bands = [(-0.04, -0.021), (-0.06, -0.04), (-0.09, -0.06), (-0.14, -0.09), (-1.0, -0.14)]
print("PUTS, OTM 2-15%, crash region re-cut into narrow bands")
print(f"{'spot band':>16}{'n':>10}{'holdFires':>11}{'rate':>8}{'baseEV':>9}"
      f"{'EV|hold':>10}{'dEV':>9}{'P(dEV>0)':>10}")
for lo, hi in bands:
    m = base & (sret >= lo) & (sret < hi)
    n = int(m.sum())
    if n < 2000: print(f"{f'[{lo*100:.0f}%,{hi*100:.1f}%)':>16}{n:>10}   too few"); continue
    e = ev[m]; s = HOLD[m]
    if s.sum() < 100: print(f"{f'[{lo*100:.0f}%,{hi*100:.1f}%)':>16}{n:>10}{int(s.sum()):>11}   too few fires"); continue
    code, nw = week_codes(wk[m])
    d = boot_diff(e, code, nw, s, 3000, seed=99)
    print(f"{f'[{lo*100:.0f}%,{hi*100:.1f}%)':>16}{n:>10,}{int(s.sum()):>11,}{s.mean()*100:>7.1f}%"
          f"{e.mean():>9.3f}{e[s].mean():>10.3f}{e[s].mean()-e[~s].mean():>9.3f}{(d>0).mean():>10.3f}")

# does hold's firing rate slope with depth? that IS the leak, if present
print("\nfiring-rate slope check (the leak, if any, is visible here):")
for lo, hi in bands:
    m = base & (sret >= lo) & (sret < hi)
    if m.sum() > 2000:
        print(f"  [{lo*100:>4.0f}%,{hi*100:>5.1f}%)  hold fires {HOLD[m].mean()*100:5.2f}%   "
              f"median spot move {np.median(sret[m])*100:+.2f}%")
