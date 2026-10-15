# Booking profits at a spike (15 Oct 2026, journal entry 27)

> **Review 2026-10-15:** the "holding ≈ selling" average was carried by ~60 lottery contracts. With MARK peaks capped at 10x/20x/50x, hold minus sell is −1.8/−1.5/−1.0 (all CIs below 0). By time to expiry: <6h −1.03 [−1.71, −0.39], 6–24h −0.48 [−0.85, −0.06], 1–3d ≈0, >3d n.s. **Book at the first 3x within 24h of expiry; further out it is a coin flip.**

His words: level-break moments are the most vulnerable; exiting causes huge FOMO; "the toughest part of my
entire trading journey has not been strategy, or even SL, but booking profits, and targets."

Live case, 15 Oct 07:45 IST (15m MARK): ETH 2,406 → 2,316.6 and back to ~2,370 within 30 min; BTC 81,411 →
80,207 → 81,288. P-ETH-2400-161026 (his entry-25 chart, 26.44): high 90.1 (3.4x), 15m close 69.9, then 47.4
fifteen minutes later. P-ETH-2350 9.8 → 54 → 24. P-BTC-80000 292 → 757 → 394.

Test (`spike_retention.py`): every BTC/ETH option since 2024-01, the FIRST time its premium jumps >= 3x within
one hour (15m high vs the close 4 bars earlier). 60,459 spikes. Multiples of the pre-spike close:

| exit | median | mean |
|---|---|---|
| spike high (the wick, unreachable) | 3.61x | 5.65x |
| **sell at the spike bar's close** | **2.97x** | **3.96x** |
| sell 1 hour later | 2.50x | 4.16x |
| hold to settlement | 0.02x | 3.58x |
| half and half | ~1.6x | ~3.8x |
| best later high (hindsight) | 5.62x | 14.6x |

- Holding beat selling at the spike close only 16.8% of the time, but in 43.5% a later high was >= 2x the
  spike close. That 43.5% is the FOMO: it is real and visible on the chart afterwards.
- On average holding pays about the same as selling: hold minus sell = −0.36x per spike, 90% CI
  [−1.33, +0.44] (expiry bootstrap). Same in every year and for calls and puts. Holding just
  converts a ~3x into a lottery ticket that is usually worthless.
- So booking at the spike (all, or half) costs nothing in expectation and removes most of the variance.
  A pre-set rule ("sell at least half on the first 3x-in-an-hour bar's close") does the hard part for him.

Caveats: MARK prices (traded fills at a spike are worse, and the wick is never fillable); first spike per
contract only; the entry is the pre-spike close, i.e. it assumes he is already holding.
