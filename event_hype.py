"""Tejas: hyped events (FOMC, NFP...) 'yielded nothing except volatility' and trap retail option
buyers, while the real breakout (Aug 19-21) came without a scheduled event. Testable on the
option market itself: an event straddle's price is the move the market EXPECTS; compare with the
move that came. Short ATM straddles from data/short_straddles.parquet (mark, after bid haircut and
fees, % of spot), entered 16:00 UTC with the next day's 12:00 UTC expiry (tte 20h), so the
straddle spans an 18:00/19:00 UTC FOMC statement, or a 12:30/13:30 UTC NFP release when entered
on the morning of the release (08:00 UTC entry, same-day... uses next-day expiry from 08:00 UTC
the day before is not available, so NFP uses 08:00 UTC entry on release day with 12:00 UTC NEXT-day expiry).
FOMC dates are the Fed's published decision days. NFP = first Friday, which is approximate
(the 2025 shutdown moved some releases), so it is labelled approximate.
"""
import numpy as np, pandas as pd
FOMC = ["2024-01-31","2024-03-20","2024-05-01","2024-06-12","2024-07-31","2024-09-18","2024-11-07","2024-12-18",
        "2025-01-29","2025-03-19","2025-05-07","2025-06-18","2025-07-30","2025-09-17","2025-10-29","2025-12-10",
        "2026-01-28","2026-03-18","2026-04-29","2026-06-17","2026-07-29","2026-09-16"]
days = pd.date_range("2024-01-01", "2026-09-30", freq="D")
NFP = [d for d in days if d.weekday() == 4 and d.day <= 7 and not (d.year == 2025 and d.month in (10, 11))]
T = pd.read_parquet("data/short_straddles.parquet")
P = pd.read_parquet("data/short_panel.parquet", columns=["asset","entry_t","expiry","tte_h"]).drop_duplicates(["asset","entry_t","expiry"])
T["dt"] = pd.to_datetime(T.t, unit="s"); T["day"] = T.dt.dt.normalize(); T["hr"] = T.dt.dt.hour
# implied move = straddle premium; realised = |net| reconstruct: seller net = prem*(1-hc)-payoff-fees; use iv*sqrt(T) proxy
def study(name, dates, hour, tb):
    dset = set(pd.to_datetime(dates))
    near = set(d + pd.Timedelta(days=k) for d in dset for k in (-1, 0, 1))
    S = T[(T.hr == hour) & (T.tb == tb)]
    ev = S[S.day.isin(dset)]; ctl = S[~S.day.isin(near)]
    rng = np.random.default_rng(0)
    b = [rng.choice(ev.net.values, len(ev)).mean() - rng.choice(ctl.net.values, len(ctl)).mean() for _ in range(4000)]
    print(f"{name:<22} event straddles n={len(ev):>3}  seller net {ev.net.mean():+.3f}%  win {ev.win.mean():.0%}  implied vol {ev.iv.median():.2f}"
          f" | other days n={len(ctl):>4} net {ctl.net.mean():+.3f}%  win {ctl.win.mean():.0%}  iv {ctl.iv.median():.2f}"
          f" | diff {ev.net.mean()-ctl.net.mean():+.3f} CI [{np.percentile(b,2.5):+.3f},{np.percentile(b,97.5):+.3f}]")
    return ev
print("Short ATM straddle that SPANS the release vs the same entry hour on ordinary days (excluding +-1 day)\n")
e1 = study("FOMC (16:00 UTC entry)", FOMC, 16, "<=1d")
e2 = study("NFP~ (08:00 UTC entry)", NFP, 8, "<=1d")
print("\nper FOMC event (seller net %, BTC/ETH):")
print(e1.pivot_table(index="day", columns="spot" if "spot" in e1 else "asset", values="net").round(2).to_string())
