# 1-minute scalping: +1% / +2% before −0.25% (tested 2026-10-13)

His idea: after a 1m candle closes, catch the cases where price rises 1% (or 2%) before falling 0.25%,
or rises 1% quickly. Learn them from the last 25 candles (price, volume, …) with ML: "earn Rs 1k a
thousand times", closer to how HFT firms work than to beating the market.

**Code:** `scalp_1m.py` (labels, features, walk-forward, simulation) and `scalp_eval.py`. Data: Delta
BTCUSD / ETHUSD TRADED perp 1m candles with volume, Dec 2023 / Feb 2024 → 13 Oct 2026 (~1.4M bars each).

## Setup

**Labels** (from the close, first passage on later highs and lows; a bar touching both counts as the stop):
- **L1:** +1% before −0.25%, within a day;
- **L2:** +2% before −0.25%, within a day;
- **Q1:** +1% within 30 min;
- **Q2:** +2% within 60 min.

**Features:** the last 25 candles (returns, ranges, wicks, volume, each normalised by the trailing day),
plus 5m–1d returns, volatility regime, distance from 25m / 4h / 1d highs and lows, volume regime, hour and
weekday.

**Model:** LightGBM pooled over both assets. Monthly walk-forward (expanding, ≥ 8 months of training, 1-day
embargo). **26 out-of-sample months** (Sep 2024 → Oct 2026).

**Trading:**
- buy at the next bar's open, one position per asset, no overlapping trades;
- **costs:** target by limit order (0.02% + GST); stop and timeout by market (0.05% + GST) + 0.01%
  slippage; a stop gapped through fills at that bar's open;
- **thresholds:** the top 5% / 1% / 0.2% of the training scores.
- **Break-even win rate:** 29.2% at +1%, 16.5% at +2%.

## Results (mean per trade, out of sample, after costs; 1 bp = 0.01%; Rs at Rs 1 lakh notional)

| variant | AUC | random entry | best threshold with ≥ 100 trades | CI |
|---|---|---|---|---|
| L1 +1% within a day | 0.52 | −12.1 bp (win 20.0%) | top 1%: −2.1 bp, win 28.5%, 123 trades | [−12.7, +10.0] |
| Q1 +1% within 30 min | **0.80** | −12.0 bp | top 0.2%: −6.4 bp, win 25.6%, 632 trades | [−11.4, −1.3] |
| L2 +2% within a day | 0.53 | −11.9 bp (win 11.9%) | top 5%: −9.4 bp, 1,903 trades | [−13.3, −4.8] |
| Q2 +2% within 60 min | **0.78** | −12.4 bp | top 1%: −8.0 bp, 1,863 trades | [−11.4, −4.3] |

- **Random entry wins 20.0% at +1% / −0.25%.** That is exactly a coin-flip walk's b / (a + b) = 0.25 / 1.25.
  The 4:1 bracket shape creates no edge by itself, and the fees (≈ 12 bp per trade, Rs ~120 per Rs 1 lakh)
  are the whole loss.
- **"Within a day" is unpredictable** (AUC 0.52). Direction at the 1-minute scale is a coin flip here.
- **"Quickly" is predictable** (AUC 0.78–0.80), but what is predicted is VOLATILITY: when a big move is
  about to happen, not which way. The −0.25% stop is hit as readily in those moments, so the win rate
  rises only to 22–26%, below the 29% needed.
- **The only positive cells are tiny:**
  - Q2 top 0.2% (30 trades, CI [−21, +40]);
  - L1 ETH top 1% (43 trades).

  Nothing is significant.
- **The model cuts the loss from −12 bp to −2 … −6 bp at the strictest thresholds.** It finds
  something, but not enough to pay the fees.

## Why "HFT-like" does not transfer

HFT firms earn the spread and maker rebates, with sub-millisecond latency and fees near zero or negative.
A retail taker paying ~0.12% per round trip gives away 12% of a +1% target on every trade. Below 1% targets
it gets worse: the fee is a fixed toll on every attempt, whatever the size of the move.

## Verdict

**Not viable as specified:** every variant is negative after costs out of sample, and the "quick"
models predict volatility, not direction.

**What could change it** (not tested):
- maker-only entries: cheaper, but the fills are adversely selected;
- larger targets on the volatility signal paired with a direction source that already works (e.g. the
  picture-day bias);
- using the Q-model's volatility forecast for the option buyer (Setup 1 / quiet-day skip) rather than for
  futures scalps.
