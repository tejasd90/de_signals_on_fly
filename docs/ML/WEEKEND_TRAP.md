# Weekend trap (24 Oct 2026)

His words, 7 Oct: *"The reaching till 87-88k upmove was a trap. Trap often happen during weekends ... I did realize
this after it transitioned immediately into the range on Monday morning 0530 candle."* Script: `weekend_trap.py`.
Data: BTC/ETH MARK, Dec 2023 → 23 Oct 2026, 1h and 4h break bars, outcomes on 1h closes. Results:
`data/weekend_trap_events.parquet`, `data/weekend_trap_{a,b,rule}.csv`.

## In plain English

- **Weekend breakouts of a recent range do slip back inside more often. That part is true, but only for range
  breaks on the 1h chart.** A 1h close above the 24h high (or below the 24h low) on Sat/Sun IST is back inside
  within 48h **87% of the time, against 76% for comparable weekday breaks (+11pp, 90% CI +6 to +16, n = 306)**.
  It holds in both halves of the data. It is strong on ETH (+18pp) and weak on BTC (+6pp, CI just touches 0).
- **It does not hold for 4h range breaks (+4 to +5pp, not significant), 7-day ranges, or trendline breaks**
  (trendline breaks on weekends go back inside slightly *less* often).
- **"Going back inside" is not the same as "the move reverses".** 48h after a weekend break, price is not
  significantly lower in the break direction than after a weekday break (−0.3% to −0.6%, every CI includes 0).
  Weekend breaks are small and pop back over the line easily; they do not reliably unwind.
- **His Monday tell is real, but it is mostly a general rule.** If the Monday 05:30–11:30 IST session makes no new
  high (no new low for a down-break), the break goes back inside far more often: 77% vs 51% (1h, 24h range,
  +27pp, CI +13 to +40). The same thing happens on weekdays, only less strongly (+10pp). And most weekend traps
  have **already** gone back inside before Monday 11:30 IST (85–88%), so by the time the tell shows, the trap
  has mostly happened.
- **The trade that is left: fade a weekend break that is still beyond its level at Monday 11:30 IST and whose
  Monday session made no new extreme.** On 1h 24h-range breaks: **+0.7% in 48h (CI −0.3 to +1.7, n = 67, 49
  weekends)**; 4h: **+1.0% (CI −0.0 to +2.0, n = 69)**. The same rule on weekdays makes ~0%. On the rarer 72h-range
  breaks it is **+3.9% (CI +1.5 to +6.1)** but that is **n = 16 events on 12 weekends**, including the 2 Mar 2025
  Sunday pump. Promising, not established. All of it is ETH-heavy and second-half-heavy.
- **His own example would not have been flagged by this rule.** The push to 86,965 came on **Monday** 5 Oct, in the
  06:30 IST bar, inside the Monday session itself (the 05:30 1h bar did not make a new high; the 06:30 one did,
  by 0.2%). By the objective rule the Monday session *extended*. The fade from Monday 11:30 IST still made +1.7%
  in 48h.

## Definitions (all causal)

- **Break**: a close above the highest high (below the lowest low) of the previous 24h / 72h / 168h of bars. One
  event per direction per 24h. Or the first close through a confirmed `levels.trendlines` line (confirmed_i >=
  anchor2 + 5, break after confirmation). Decision = close of the break bar.
- **Weekend**: the break bar closed between Sat 00:00 and Mon 00:00 IST. (A 4h bar closing Sat 01:30 IST counts as
  Saturday, though it is a Friday US-evening bar.)
- **Back inside within H**: any 1h close on the other side of the broken level within H hours.
- **Matched weekday control**: weekday breaks re-weighted to the weekend mix of direction x volatility regime (ATR /
  price vs its own prior 180 days, tertiles) x break size (close beyond level in ATR, tertiles).
- **Monday session**: Mon 05:30–11:30 IST (six 1h bars). **Extends** = a 1h high in the session above every high
  since the break (low below every low for down-breaks). Decision = Mon 11:30 IST.
- **Fade**: from the Mon 11:30 IST close, move against the break direction 24/48/96h later (MARK, before fees).
- CIs: 90%, weekly block bootstrap (2,000 draws). Halves split at 21 May 2025.

## (a) Weekend vs matched weekday breaks: back inside within 48h

| break | spot | weekend | weekday (matched) | diff, pp | 90% CI | n weekend / weekday |
|---|---|---|---|---|---|---|
| 1h, 24h range | pooled | 86.9% | 75.8% | **+11.1** | +6.0 / +16.3 | 306 / 857 |
| | BTC | 84.8% | 78.4% | +6.4 | −0.1 / +13.2 | 158 / 437 |
| | ETH | 89.2% | 71.2% | **+18.0** | +10.6 / +25.5 | 148 / 420 |
| | 1st half / 2nd half | | | +11.5 / +11.4 | both > 0 | 137 / 169 |
| 1h, 72h range | pooled | 84.9% | 72.8% | **+12.2** | +3.4 / +21.8 | 93 / 516 |
| | BTC / ETH | | | +3.8 / +18.4 | ETH only > 0 | 42 / 51 |
| | 1st half / 2nd half | | | +16.8 / +9.7 | 2nd half −7.0 / +25.7 | 47 / 46 |
| 1h, 168h range | pooled | 76.4% | 74.4% | +1.9 | −10.2 / +14.7 | 55 / 301 |
| 4h, 24h range | pooled | 79.9% | 74.8% | +5.1 | −1.5 / +11.5 | 254 / 713 |
| 4h, 72h range | pooled | 77.3% | 73.2% | +4.1 | −4.1 / +13.3 | 88 / 441 |
| 4h, 168h range | pooled | 68.5% | 69.4% | −0.9 | −12.6 / +10.9 | 54 / 258 |
| 1h trendline | pooled | 65.0% | 66.9% | −1.9 | −5.1 / +1.5 | 1,266 / 3,235 |
| 4h trendline | pooled | 60.8% | 61.5% | −0.7 | −6.8 / +5.6 | 245 / 873 |

Move in the break direction 48h later (weekend minus matched weekday): 1h 24h −0.30% (CI −0.80 / +0.19); 1h 72h
−0.60% (−1.59 / +0.38); 4h 72h −0.00%; 1h trendline −0.34% (−0.68 / +0.01). No horizon is significant except 1h
trendline at 96h (−0.53%, −0.99 / −0.07).

By IST day, 1h 24h-range breaks back inside within 48h: Mon 80%, Tue 82%, Wed 75%, Thu 81%, Fri 72%, **Sat 91%
(n = 86), Sun 86% (n = 231)**.

## (b) His Monday tell (weekend breaks only)

Back inside within 48h **after** Mon 11:30 IST, among breaks still beyond their level then:

| break | Monday did NOT extend | Monday extended | diff, pp (90% CI) | same rule on weekdays |
|---|---|---|---|---|
| 1h, 24h range | 77.6% (n 67) | 50.9% (n 112) | **+26.7** (+13.3 / +39.7) | +9.6 (+0.6 / +18.0) |
| 1h, 72h range | 87.5% (n 16) | 40.6% (n 32) | **+46.9** (+25.7 / +66.7) | +24.5 (+14.1 / +34.2) |
| 4h, 24h range | 76.8% (n 69) | 48.4% (n 93) | **+28.4** (+15.6 / +40.9) | +8.0 (−1.0 / +16.5) |
| 4h, 72h range | 70.8% (n 24) | 37.9% (n 29) | **+32.9** (+9.1 / +57.6) | +21.5 (+11.8 / +30.8) |
| 1h trendline | 36.0% (n 559) | 17.8% (n 484) | +18.2 (+11.2 / +25.4) | +3.1 (−1.1 / +7.4) |

Already back inside before Mon 11:30 IST: 88% of non-extending vs 60% of extending weekend breaks (1h 72h);
85% vs 72% (1h 24h). Part of the Monday effect is mechanical: no new extreme means price is nearer the line.

## The trade: fade at Mon 11:30 IST (weekend break, Monday did not extend, still beyond the level)

| break | n (weekends) | fade 24h | fade 48h (90% CI) | fade 96h | 48h in ATR | wins 48h | weekday analog 48h |
|---|---|---|---|---|---|---|---|
| 1h, 24h range | 67 (49) | +0.33% | **+0.74%** (−0.30 / +1.72) | +0.33% | +0.9 | 58% | +0.03% (n 299) |
| 4h, 24h range | 69 (49) | +0.40% | **+1.00%** (−0.02 / +1.96) | +0.55% | +0.4 | 62% | −0.17% (n 284) |
| 1h, 72h range | 16 (12) | +2.23% | **+3.91%** (+1.48 / +6.09) | +4.04% | +5.5 | 81% | +0.57% (n 170) |
| 4h, 72h range | 24 (17) | +0.64% | +2.22% (−0.07 / +4.25) | +2.48% | +1.4 | 67% | +0.56% (n 161) |
| 1h trendline | 559 | +0.08% | +0.26% (−0.31 / +0.85) | +0.55% | +0.2 | 53% | +0.03% |
| 4h trendline | 105 | −0.22% | +0.57% (−0.40 / +1.52) | +0.17% | +0.2 | 58% | +0.09% |

Stability, fade 48h: 1h 24h — BTC +0.00% (n 36), ETH +1.59% (n 31, CI +0.23 / +2.88); 1st half +0.10%, 2nd half
+1.25%. 4h 24h — BTC +0.01%, ETH +2.14%; 1st half −0.25%, 2nd half +1.91%. 1h 72h — both halves ~+3.9%, BTC
+2.7% (n 7), ETH +4.8% (n 9). ATR = the break timeframe's ATR (1h ATR for 1h breaks). Without the "still beyond
at 11:30" filter the fade is +0.46% (1h 72h, n 58, CI −0.87 / +1.77).

## Bounds

- MARK prices, no volume; fades are before fees and slippage.
- The fade cells were chosen from 6 break types x 3 horizons; the one significant cell (1h 72h) has n = 16 on 12
  weekends and includes the 2 Mar 2025 pump (+6.6% BTC, +11.0% ETH). Treat as a candidate for forward logging.
- The effect lives in ETH and in the second half; on BTC alone neither (a) nor the fade is significant.
- "Back inside" is a low bar for weekend breaks, which are small; the net move does not confirm a reversal.
- His 87–88k example is classified "Monday extended": the objective rule would not have caught it on Monday.
