# The parabolic otm_red_squeeze on high timeframes: does it predict 1:100? (11 Nov 2026)

His hypothesis (11 Nov, after switching models):

> "I sincerely believe that the parabolic otm_red_squeeze is something (of course, coupled with price action
> context ... Also, the otm_wall and green_stairs also do help, maybe on smaller timeframes as part of the bigger
> otm_red_squeeze signal) which should predict 1:100 trades with high probability."

His points, tested as stated:
1. Parabolic, ideally bounded from above and below by a parabola.
2. "The squeeze should not be part of a move in the opposite direction, otherwise it is a countertrend set-up
   and false flat."
3. otm_wall / green_stairs on smaller timeframes as part of the bigger squeeze.
4. Money management: "2:20k, 4:80k, 16:320k, 80:1.6m", at least one such trade a month on BTC.
5. Labeling by images: "at least millions just for 1w, 1d, 12h, 6h".

Script: `htf_squeeze.py` (`build`, then no argument, `context`, `robust`, `ml`, `staged`, `ladder`, `traded`,
`traded_show`). Rows: `data/htf_squeeze/` (not committed). Logs: `logs/htf_*.log`.

## In plain English

- **You are right that the trades exist, and that they come every month.** On BTC, 34 of 35 months had at least
  one 6h+ squeeze firing with a strike that later marked 25x, and 16 of 35 months had one that marked 100x.
- **The squeeze does not pick them.** It fires about 135 times a month on BTC at 6h and above, and about 4 of
  those pay 25x. An ordinary bar on the same kind of option (same asset, side, time left, distance, cheapness)
  pays just as often: 3.5% vs about 3% at 25x, 0.9% vs 0.6% at 100x, no difference outside noise on any timeframe
  from 4h to 1w.
- **The parabola adds nothing as coded.** Highs and lows both on a convex curve (R² ≥ 0.9): 3.8% vs 3.9% at 25x.
- **Your point 2 is right, and it is the one result that holds up.** Measure the spot move over the last 20 bars
  in the option's direction. Options bought with that move reach 25x 4.3% of the time and keep 1.32 of each 1
  paid; options bought against it reach 25x 1.6% and keep 0.57. Inside the squeeze the gap is wider: 5.7% vs 1.0%
  at 25x, 1.4% vs 0.2% at 100x. It holds for calls and puts, BTC and ETH, 2024 and 2026 (weaker in 2025), and
  with a price floor. But it is true of **every** bar, squeeze or not: it is a property of the market, not of the
  pattern. A counter-trend squeeze is your "false flat".
- **It survives traded prices.** On 6,000 sampled bars with real prints: with-trend 5.0% at 25x and 1.50 kept per
  1 paid (CI 1.12–1.93, above 1 in 2024, 2025 and 2026); counter-trend 2.2% and 0.73. This is a backtest on prints,
  not fills.
- **Smaller-timeframe otm_wall / green_stairs do not confirm the bigger squeeze.** Inside the squeeze bar: +0.9pp,
  not significant. Following it: 2.84% vs 2.90% at 25x.
- **Waiting three bars for the premium to hold does not help on 6h+**, once the entry is taken after the wait.
- **Machine learning on all of it finds nothing more.** 30 pattern and parabola features add nothing to time left,
  distance and cheapness (AUC 0.63 vs 0.62). Its top 1% of moments pays 25x 3–7% of the time, not 30%.
- **"High probability" is not there.** The honest number is about 5% at 25x for with-trend entries against 1–2% for
  counter-trend ones. That is a filter with positive expectancy, not a 1:100 predictor.
- **Labeling is thousands, not millions.** Every 6h+ squeeze in the whole history is 9,008 firings: 6h 4,120,
  8h 2,851, 12h 1,429, 1d 588, 1w 20. Daily plus 12h is about 2,000 charts.

## What was built

- Every BTC/ETH option contract, Jan 2024–10 Nov 2026 (1,046 expiries), from 1h MARK candles rebuilt into 4h,
  6h, 8h, 12h, 1d and 1w bars (00:00 UTC anchored, as Delta's).
- The signal re-implemented bar for bar and checked against the real `signals/otm_red_squeeze.js`: 160 of 160
  firings match on six asset/expiry/timeframe sets.
- Universe: options that are OTM and cheap (premium ≤ spot/300), at least 1.5h from expiry. 836,772 rows:
  - every green bar after at least one red bar, with the squeeze firings marked;
  - a 15% random sample of all other bars ("any moment").
- Entry = the trigger bar's close. Outcome = later high ÷ entry (to the contract's end), and what is left at the end.
  "Value kept" = 25 if it reached 25x, else the final value, per 1 paid, before the 8.26% cost.
- Comparisons are within asset × call/put × time to expiry × moneyness × cheapness; CIs by resampling expiries.
- Definitions were fixed before looking at outcomes:
  - **PAR**: arc from the highest high of the last 30 bars to the trigger, at least 5 bars; quadratics through the
    highs and through the lows both convex with R² ≥ 0.9.
  - **NCT** (not counter-trend): spot moved against the option by less than 0.5 sigma over the pattern.
    **CT**: more than 1 sigma against.
  - **WT** (with-trend): spot's move over the last 20 bars of that timeframe, in the option's direction, above
    0.5 sigma.
  - **QUIET**: 7-day realised volatility below 0.8 × the 30-day.
  - **LTF**: an otm_wall or green_stairs on ≤ 60m on the same strike during the trigger bar.

## Results

### 1. The squeeze by timeframe (MARK)

| timeframe | strike-rows | firings | ≥5x | ≥10x | ≥25x | ≥100x |
|---|---|---|---|---|---|---|
| 4h | 17,353 | 7,065 | 11.4% | 6.6% | 2.90% | 0.67% |
| 6h | 9,804 | 4,120 | 12.4% | 7.7% | 3.65% | 0.81% |
| 8h | 6,644 | 2,851 | 10.9% | 6.6% | 3.01% | 0.86% |
| 12h | 3,139 | 1,429 | 12.9% | 7.8% | 4.33% | 1.15% |
| 1d | 1,570 | 588 | 11.0% | 6.6% | 2.93% | 1.08% |
| 1w | 54 | 20 | 9.3% | 3.7% | 1.85% | 0.00% |

Against matched controls, every CI includes 0 except 4h at 100x, where the squeeze is worse than other
green-after-red bars (−0.25pp [−0.45, −0.05]). Best case: 12h vs a random bar at 25x, 4.34% vs 3.14%, +1.21pp
[−0.14, +2.55]. Daily: 2.93% vs 3.24% for a random bar.

### 2. His conditions inside the 6h+ squeeze (on vs off, matched)

| condition | share on | 25x on vs off | diff [95% CI] | 100x on vs off |
|---|---|---|---|---|
| PAR, both-bounded parabola | 39% | 3.81 vs 3.93 | −0.12 [−1.46, +1.22] | level |
| NCT, not counter-trend | 53% | 3.92 vs 2.78 | +1.13 [−0.12, +2.27] | **1.12 vs 0.48, +0.64 [+0.21, +0.99]** |
| CT, counter-trend | 26% | 2.82 vs 3.12 | −0.30 [−1.72, +1.40] | **0.32 vs 0.88, −0.57 [−1.01, −0.15]** |
| WT, with-trend | 15% | 5.83 vs 3.32 | **+2.51 [+0.38, +4.65]** | 1.60 vs 0.76, +0.84 [−0.04, +1.76] |
| QUIET | 20% | 4.81 vs 3.03 | +1.79 [−0.24, +3.77] | 2.08 vs 0.67, +1.41 [+0.04, +3.17] |
| LTF wall/stairs in the bar | 82% | 3.43 vs 2.49 | +0.94 [−0.17, +1.95] | |
| big opposite spot bar | 6% | 1.46 vs 2.84 | **−1.39 [−2.39, −0.34]** | 0.26 vs 0.81 (the live filter already drops these) |

The log-price parabola and the pattern-level versions (highs only, lows only) are also level.

### 3. The same conditions on bars that are NOT squeezes

The lifts are the same size on every kind of bar, so they do not belong to the squeeze:

| condition (25x, on − off) | squeeze | green after ≥3 reds, no squeeze | green after 1–2 reds | random bar |
|---|---|---|---|---|
| NCT | +1.13 | **+1.82 [+1.03, +2.61]** | **+1.46 [+0.62, +2.58]** | n/a |
| WT | **+2.51** | **+1.73 [+0.30, +3.21]** | **+1.58 [+0.45, +2.82]** | **+1.32 [+0.53, +2.22]** |
| QUIET | +1.79 | **+2.27 [+0.13, +4.61]** | +2.35 [−0.30, +4.95] | **+1.64 [+0.06, +3.21]** |

Stacked rates, 25x / 100x: squeeze NCT+WT 6.54% / 1.92% (2,294 rows, 356 expiries); green after ≥3 reds NCT+WT
5.18% / 1.17%; green after 1–2 reds 4.51% / 0.90%; random bar WT 3.90% / 0.72%. Squeeze NCT+QUIET 5.91% / 2.81%;
the other two green populations 6.03% / 2.05% and 5.49% / 2.45%.

### 4. How solid are the two context effects?

**Trend in the option's direction: solid.** A staircase, on every kind of bar:

| trend over 20 bars (sigmas, option's direction) | random bar 25x | green-after-red 25x | 100x | value kept |
|---|---|---|---|---|
| below −1 | 1.66% | 1.58% | 0.16–0.19% | 0.48–0.55 |
| −1 to −0.5 | 2.47% | 2.79% | 0.6% | 0.80–0.86 |
| −0.5 to 0 | 3.27% | 3.71% | 0.8–0.9% | 1.03–1.11 |
| 0 to 0.5 | 3.25% | 3.75% | 0.8–1.0% | 1.05–1.17 |
| 0.5 to 1 | 3.87% | 4.42% | 0.9–1.0% | 1.21–1.34 |
| above 1 | 3.94% | 4.77% | 0.5–0.8% | 1.22–1.49 |

With-trend (above 0.5) against counter-trend (below −1), matched, all 6h+ bars (88,496 vs 108,767):

| slice | 25x with vs against | diff [95% CI] | 100x diff | value kept with vs against |
|---|---|---|---|---|
| all | 4.28 vs 1.58 | **+2.70 [+1.43, +4.01]** | **+0.61 [+0.21, +1.03]** | 1.32 vs 0.57, **+0.75 [+0.41, +1.10]** |
| calls | 4.18 vs 1.39 | **+2.80 [+0.87, +4.98]** | **+0.81 [+0.16, +1.57]** | 1.29 vs 0.52 |
| puts | 4.42 vs 1.84 | **+2.58 [+1.21, +4.09]** | **+0.35 [+0.11, +0.66]** | 1.36 vs 0.62 |
| BTC | 4.20 vs 1.71 | **+2.50 [+0.81, +4.31]** | **+0.65 [+0.06, +1.34]** | 1.33 vs 0.62 |
| ETH | 4.43 vs 1.36 | **+3.07 [+1.75, +4.53]** | **+0.54 [+0.29, +0.82]** | 1.30 vs 0.48 |
| 2024 | 5.21 vs 1.16 | **+4.04 [+1.87, +6.73]** | **+0.92 [+0.22, +2.06]** | 1.54 vs 0.41 |
| 2025 | 2.97 vs 2.11 | +0.86 [−0.52, +2.28] | +0.16 [−0.02, +0.38] | 1.06 vs 0.77 |
| 2026 | 4.54 vs 1.19 | **+3.35 [+1.10, +5.50]** | +0.63 [−0.46, +1.33] | 1.33 vs 0.51 |
| entry above the floor | 4.26 vs 1.57 | **+2.69 [+1.38, +3.94]** | **+0.51 [+0.24, +0.82]** | 1.32 vs 0.56 |
| ≥ 24h to expiry | 4.90 vs 1.85 | **+3.04 [+1.48, +4.93]** | **+0.72 [+0.20, +1.38]** | 1.43 vs 0.61 |
| squeeze firings only | 5.66 vs 1.01 | **+4.65 [+2.49, +6.97]** | **+1.20 [+0.39, +2.28]** | 1.52 vs 0.30 |

Same on every timeframe (6h 4.05 vs 1.60, 8h 4.05 vs 1.52, 12h 5.27 vs 2.12, 1d 4.51 vs 0.94; weekly too few)
and at every time to expiry (best with more than 7 days left: 6.02 vs 1.84).

**Quiet: not established.**
- No staircase: the 0.6–0.8 band is the best (5.5% at 25x), the quietest band (below 0.6) is the worst (1.5%).
- Concentrated: the NCT+QUIET squeeze's 100x hits come from 13 expiries; three months hold 66% of them (Aug 2026,
  Sep 2024, Feb 2025), one expiry 32%.
- With months as the resampling unit the CIs include 0 (25x [−0.32, +4.03], 100x [−0.02, +3.65]).

### 5. Smaller timeframes after the squeeze (his point 3)

An otm_wall / green_stairs on ≤ 60m, on a cheap OTM strike, whose trigger closes within one higher-timeframe bar
after a 6h+ squeeze on that strike (57,024 of 970,252 such signals), measured from the low-timeframe close:

| | 10x | 25x | 100x |
|---|---|---|---|
| after a 6h+ squeeze | 7.04% | 2.84% | 0.51% |
| matched, no squeeze before | 6.62% | 2.90% | 0.66% |
| diff [95% CI] | +0.42 [−0.58, +1.60] | −0.06 [−0.55, +0.53] | −0.16 [−0.38, +0.06] |

After a 12h+ squeeze it is worse (25x −0.82pp [−1.67, −0.03]). After a not-counter-trend squeeze: +0.29pp
[−0.39, +1.07].

### 6. Wait three bars, buy only if the trigger low held

13,612 squeeze rows with three later bars; 13% hold; 24% have already doubled during the wait.
- Buy at the squeeze close: 25x 3.97%, value kept 1.04.
- Held, buy after the wait: 25x 3.63%, value kept 1.03.
- Broke, buy after the wait: 25x 2.84%, value kept 0.87.

No gain from waiting on 6h+, as `TF_REPEAT_HOLD.md` found for 4h+. (Measuring a held squeeze from the squeeze
close gives 10.3%, but that uses three bars of the future. It is not a result.)

### 7. Machine learning (walk-forward, four half-year test blocks, 336,806 out-of-sample bars)

Gradient boosting, trained only on contracts that expired before each test block.

| features | AUC | top 10% at 25x | top 1% at 25x | top 0.2% at 25x |
|---|---|---|---|---|
| base: asset, side, timeframe, time left, moneyness, cheapness | 0.622 | 4.52% | 6.62% | 10.2% (35 expiries, 0 at 100x) |
| + context: quiet, trend, arc depth and length | 0.635 | 4.88% | 2.64% | 1.5% |
| + 24 pattern / parabola / squeeze features | 0.629 | 4.37% | 3.35% | 1.6% |

Base rate 2.92%. The pattern features lower the score; nothing concentrates the winners. This is the same verdict
as the earlier arms (timing AUC 0.57).

### 8. His ladder (point 4)

Read as: stake 2k for 10x (20k); then 4k for 20x (80k); 16k for 20x (320k); 80k for 20x (1.6m). Rungs 2–4 are
paid from the previous win; when that runs out, start again with fresh 2k stakes. 1,000 campaigns of up to 400
trades each, outcomes drawn from the real rows, selling exactly at the target on MARK:

| trades drawn from | 10x | 20x | campaigns reaching 1.6m | median trades to get there | money out ÷ fresh money in |
|---|---|---|---|---|---|
| squeeze 6h+, all | 7.3% | 4.3% | 12.6% | 196 | 0.55 |
| squeeze, not counter-trend | 8.9% | 5.1% | 19.2% | 220 | 0.86 |
| squeeze NCT + with-trend | 13.9% | 8.0% | 62.1% | 168 | 3.96 |
| squeeze NCT + quiet | 10.8% | 7.0% | 42.8% | 180 | 2.15 |
| random bar, quiet | 8.9% | 5.1% | 26.7% | 193 | 1.25 |
| random bar | 7.1% | 3.6% | 9.1% | 190 | 0.45 |

- The ladder does keep each loss small, as he says. It does not create an edge: at the plain squeeze's rates it
  returns 55 paise per rupee.
- It needs four wins, and rungs 2–4 get about five tries each. At the plain squeeze's rates a 400-trade campaign
  puts in about ₹5.9 lakh of fresh 2k stakes and takes out ₹3.3 lakh; one campaign in eight reaches 1.6m, after
  about 200 trades. That is not one trade a month.
- The rows above 1.0 are MARK prices, random draws (real wins cluster in a few weeks) and conditions chosen after
  looking. Treat them as an upper bound.

### 9. With-trend vs counter-trend on TRADED prices

6,000 green-after-red bars (6h+, entry above the floor), 3,000 with-trend and 3,000 counter-trend, seeded sample.
Fill = the first traded 1h close after the bar closed, if within 6h. Hit = a later traded high at K × the fill.
Value at the end uses the final mark (settlement) over the fill.

| | filled within 6h | ≥10x | ≥25x | ≥100x | value kept [95% CI by expiry] |
|---|---|---|---|---|---|
| with-trend | 79% | 11.9% | 4.98% | 0.80% | **1.50 [1.12, 1.93]** |
| counter-trend | 67% | 7.3% | 2.20% | 0.30% | 0.73 [0.46, 1.03] |
| matched diff | | **+4.39 [+1.07, +7.81]** | **+3.20 [+1.47, +4.89]** | +0.32 [−0.14, +0.70] | **+0.71 [+0.23, +1.16]** |

- The gap is as large on prints as on mark (25x: 4.71% vs 1.51% matched; mark on the same rows 4.41% vs 1.05%).
- With-trend value kept by year: 2024 1.61, 2025 1.25, 2026 1.67. Calls 1.19, puts 1.84. By month as the resampling
  unit: 1.50 [1.06, 1.98].
- 118 rows reached 25x, in 61 expiries. The top 5 expiries hold 25% of the value; without them 1.17.
- Before 2026: 25x +2.20pp [+0.42, +4.49]. In 2026: +4.47pp [+0.72, +7.71].
- Squeeze firings alone in this sample: 8.2% vs 2.4% at 25x, but only 85 vs 91 rows (CI [−1.2, +13.6]).
- After the 8.26% cost, with-trend keeps about 1.4 per 1 paid on these prints; counter-trend loses a third.

What this does not show: a print is not your fill (size and depth are unknown), one bar in five did not trade
within 6h, the exit at 25x is a print at that price, and this is a backtest. It needs the forward log.

## Bounds

- **MARK prices.** Multiples on near-worthless options are inflated; the comparisons between groups are more
  reliable than the levels. With a price floor (BTC entry ≥ $2, ETH ≥ $0.2) the with-trend result holds
  (25x +1.53pp [+0.62, +2.53]).
- **The parabola is my coding of his words.** Quadratics through highs and lows of the last ≤30 bars. His eye may
  mean something else; labeling is the only way to find out (2,000 charts for daily + 12h).
- **No news or event context.** None is stored historically.
- **Crypto only.** NIFTY monthlies live for weeks with deep liquidity; the 1:500 cases are not in this data.
- **The store.** `data/signals` merges strikes and keeps the latest trigger, and drops firings on a big opposite
  spot bar, so it lists fewer firings than the candle scan. One gap is unexplained: the BTC 30 Oct daily puts
  that fire on 24 Sep in the code (six strikes, 36 days before expiry) are not in the store.
- **No confirmed example of the pattern on crypto (checked 11 Nov, after his reply).** The seven crypto
  contracts he has named as examples (C-BTC-87000-021026, P-BTC-81000/80500-091026, P-ETH-2400-161026,
  P-BTC-81000-231026, C-BTC-66000-200826, C-BTC-68000-210826) all carry `otm_red_squeeze`, `otm_wall` or
  `green_stairs` on 5m–4h in `data/signals`. A 6h+ `otm_red_squeeze` that includes the strike exists on only two
  of the seven (80500 put, 8h, 6 Oct 09:30 IST; 68000 call, 6h, 15 Aug 05:30 IST). So his examples so far are
  low-timeframe cases, and the 6h+ definition here has never been checked against a moment he would call
  "this is it". Before more testing: 10–20 cases from him (contract, timeframe, the bar), crypto or NIFTY, and
  check whether the detector fires there.
