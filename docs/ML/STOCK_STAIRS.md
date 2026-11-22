# Green stairs on stocks (22 Nov 2026)

His idea (20 Nov): green stairs work on daily / weekly / monthly charts of STOCKS (ADANIENT, DMART) and could point to
multibaggers; many names are fake or manipulated, so volume checks are needed, fundamentals if possible.

Code: `nse/fetch_stocks.js` (data), `nse/stocks_to_parquet.py`, `nse/stock_stairs.py`. Data: Kite daily candles from 2010 for
every NSE and BSE-only equity listed on 20 Nov 2026: 10,774 symbols with candles, 11.6 million rows
(`data/nse/stocks_1d.parquet`, local).

## Decisions (all open to change)

| decision | value | why |
|---|---|---|
| Bars | daily; weekly Mon–Fri; calendar monthly | built from daily |
| Signal | consecutive green bars, each body (% of open) ≥ the one before; tested when the run reaches 3, reaches 4, is 5+ | the crypto rule without its option-only parts (out-of-the-money test, strength threshold, one-equal-step limit) |
| Entry | next session's open | the bar must be closed |
| Liquidity | median traded value of the last 60 sessions ≥ ₹1 crore; price ≥ ₹10 | measured at the signal, not today |
| Circuit / manipulation | ≤ 10% of the last 60 sessions with high = low; ≤ 5% with zero volume | locked or one-price days |
| Data breaks | a daily move beyond 25% in the last 60 sessions or in the outcome window drops the bar, signal or not | unadjusted corporate actions, bad prints, first days of listing |
| Outcomes | return at 1y (capped at +900% in the mean); 2x at 1y; touched 2x within 1y (by close); −50% at 1y; 3x at 2y; touched 5x within 2y | |
| Control A | every other eligible bar of the same calendar month | removes the market |
| Control B | same month and same decile of 3-bar return | removes "it has simply gone up" |
| Intervals | 90%, bootstrap over months | |
| Fundamentals | not used | none in the data |

2,687 symbols ever pass the filters; 144,586 eligible stock-months, 2,849 of them a monthly "run reaches 3".

## Results

Monthly bars, run reaches 3 (2,548 with a full year after, 179 months):

| outcome | stairs | same month | same month + momentum |
|---|---|---|---|
| mean 1y return | 25.2% | 18.6% (diff +4.5 to +9.2) | 23.3% (−0.2 to +4.1) |
| 2x at 1y | 10.2% | 8.0% (+1.1 to +3.3) | 10.0% (−0.9 to +1.1) |
| touched 2x in 1y | 16.0% | 13.2% (+1.3 to +4.2) | 16.4% (−1.6 to +0.8) |
| −50% at 1y | 3.2% | 4.4% (−1.8 to −0.6) | 4.6% (−2.2 to −0.8) |
| 3x at 2y | 6.4% | 5.1% (+0.5 to +2.2) | 6.3% (−0.7 to +1.0) |
| touched 5x in 2y | 2.9% | 2.1% (+0.2 to +1.5) | 2.9% (−0.6 to +0.7) |

Median 1y return: 10.1% after a monthly stair, 3.8% for all eligible stock-months.

- **Monthly:** stairs beat ordinary stock-months of the same month on every measure. Against stocks that rose as much over the
  same three months without the stair shape, the gain is gone; what remains is fewer halvings (3.2% vs 4.6%).
  Run reaches 4 (360 cases): the same picture, wider intervals. Run of 5+: 38 cases, nothing can be said.
- **Weekly:** run reaches 3 (8,145 cases) is level with its month (2x at 1y 8.3% vs 8.2%) and below momentum-matched bars
  (8.3% vs 9.4%). Run of 5+ (99 cases) looks better (2x 12.1% vs 8.2%) but the interval includes zero.
- **Daily:** at or slightly below ordinary bars on everything (2x at 1y 7.2% vs 7.3%; vs momentum-matched 7.2% vs 8.1%).
- **His examples:** ADANIENT monthly stairs: Dec 2012 (−9% a year later), Jun 2017 (−16%), Jan 2018 (−45%), Oct 2019 (+73%),
  Aug 2020 (+465%), Nov 2020 (+331%), Aug 2022 (−22%). DMART: Jul 2017 (+78%), Jul 2019 (+44%), Dec 2020 (+71%), Apr 2026 (open).
- **Now:** 8 of 1,660 eligible stocks closed October 2026 on a monthly run of 3 or more.

## Read with these

- **Survivorship:** only companies listed today are in the data. Delisted and merged names are missing, so every absolute
  number above is too high, the controls included. Momentum names that later died are missing from the signal side.
- Roughly 8% of liquid stock-months doubling in a year is the level in THIS sample (2010–2026, survivors).
- No costs, no impact, entry at the open after the bar. Corporate-action adjustment is Kite's; the 25% rule is the only guard.
- One stock can fire in consecutive months; the month bootstrap handles time clustering, not that.
- Not tried: volume rising with the stairs, breakout to a multi-year high, base length before the stairs, sector, fundamentals.
