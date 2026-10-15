# Reversal at a known line (13 Oct) and a "new price" / stale-range indicator (15 Oct 2026)

## 13 Oct: his breakdown trade that reversed
Both lows came in the 05:30 IST hour: BTC 80,993, ETH 2,407.9; by 09:30 BTC 83,420, ETH 2,517.
- BTC: a 6h rising line (15 Sep → 8 Oct, 3 touches, `levels.trendlines`) was CONFIRMED at 23:30 IST 12 Oct, six
  hours before the low, and sat at ~81,475. The low pierced it by 0.6% and the hour closed back near it.
- ETH: the low was 1.9 above the 8 Oct low (2,406), a retest of a horizontal level (only one prior rejection,
  so below the 3-rejection rule). The 6h line from 28 Aug was only confirmed AT this low.
So the reversal point was visible in advance for both. But LINE_HOVER.md shows a known line says WHERE a
reaction can happen, not WHETHER it holds (66% of touches end in a close-through). Practical use: a level the
move is heading into is where to book at least part (see SPIKE_RETENTION.md), not a reason to expect a stop.

## Stale range / new price (`new_price.py`)
NEW PRICE = an hourly close above the highest or below the lowest of the previous N closes. STALE = hours since
the last one. Next 24h, BTC+ETH MARK hourly, 2024-03 onward:

| hours since a new 72h close | share of hours | median biggest 24h excursion | excursion >= 3% |
|---|---|---|---|
| new price now | 9.7% | 3.20% | 54.1% |
| 1-6h | 22.2% | 2.97% | 49.4% |
| 6-24h | 32.6% | 2.72% | 44.0% |
| 1-2 days | 21.5% | 2.65% | 42.4% |
| 2-4 days | 12.8% | 2.86% | 47.0% |

- **Narrow range (bottom third of its own history) AND stale > 24h:** 14% of hours, ≥3% excursion 35% vs 48%
  otherwise. This is the same quietness found in WHEN_NOT_TO_TRADE, reached from his angle.
- A new price says "bigger move more likely", not which way: continued >= 1% the same way 70% (N=72) vs a
  random hour's 58% (BTC) / 70% (ETH) chance of a 1% move in a given direction.
- Staleness alone is not monotone (2-4 days is back to 47%); the narrow-range condition does the work.
