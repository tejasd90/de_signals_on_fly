# Option selling — the seller's side of everything

Tejas, 2026-10-02: every test so far scored the BUYER. Sellers win ~2/3 of the
time and the market is mostly sideways; Delta's short-option margin is low. Score
his signals, the price-action work and the ML from the seller's side.

**Data as of 2026-10-02:** expiries 2023-12-29 → 2026-10-01 (1001 BTC, 969 ETH).
The rerun on 2 Oct matched to the 3rd decimal, because no expiry had settled since. Bid/ask
haircut now from 2 live snapshots (1 and 2 Oct, 1,784 quotes). Option candles keep
updating through the dashboard loop (`fetch_options.py --live`), so `python short_panel.py && python short_rules.py`
picks up every new expiry. Candles written by that loop were TRADED prices until 2026-10-02; they are now MARK and the traded ones were rewritten (`fetch_options.py --remark`).

**In plain English:** selling options wins often but earns nothing on average,
because the occasional big loss eats the frequent small wins. Two situations do pay
a little: (1) after a trendline breaks, sell the option on the side the price came
FROM; (2) sell straddles when options are unusually expensive. Both earn about half
as much on newer data as on older data. Never size by Delta's low margin: one bad
day can lose 4x the margin.

Scripts: `short_panel.py` (2.7M short trades: every strike, every 4h, last 8 days
before expiry, BTC+ETH, Dec-2023 to now, held to expiry) · `short_base.py`
(baseline) · `short_cond.py` (conditions) · `short_check.py` (controls) ·
`short_fills.py` (mark vs traded) · `short_rules.py` (rules, out of sample).

Costs: the seller fills at the BID. The haircut `(mark-bid)/mark` comes from a
live snapshot of all 866 BTC/ETH quotes (`data/spread_snapshot.csv`), median per
moneyness × tenor: ~0.5–1.3% of premium near the money, 44% for deep-OTM dailies.
Fees: 0.01% of notional capped at 3.5% of premium, +18% GST, charged at entry and
again at settlement when the option settles ITM. P&L is in **% of spot notional**.

## 1. Unconditional selling: wins often, earns nothing

| sold option, ≤1d | win | net % of spot |
|---|---|---|
| ATM | 67% | −0.012 |
| OTM 0.25–0.75% | 76% | −0.001 |
| OTM 0.75–2% | 84% | +0.004 |
| OTM 2–5% | 92% | +0.017 |

At mark the seller earns only ~+0.02% of spot. The bid haircut plus fees cost
about the same. It's net ~0 in every moneyness × tenor cell and every year. The 2/3 win
rate is real, but it's already in the price: the losses pay for it. It's the
mirror of `de-signals-no-highprob-setup`.

Deep ITM (to "capture direction") is worse: ITM 2–5% ≤1d nets −0.075%
(t = −5.5). A deep-ITM short is a short future that pays option spread and fees
on a large premium. **For direction, use the future.**

## 2. His ideas, seller frame

Excess = net minus the unconditional mean of the same asset × type × moneyness ×
tenor cell. Entry at the first 4h bar after the event's bar CLOSES. The CI comes
from a week-block bootstrap.

| condition | events | excess % | P(≤0) |
|---|---|---|---|
| steep approach → sell BEYOND the level (his claim) | 506 | **−0.336** | 0.976 |
| sideways approach → sell BEHIND (his claim) | 506 | +0.077 | 0.167 |
| **any trendline break → sell BEHIND** | 1908 | **+0.116** | 0.001 |
| any break → sell beyond (fade) | 2016 | −0.183 | 0.976 |
| opposite side of green_stairs / red_squeeze / otm_red_squeeze | ~11k each | −0.02 | ~0.7 |
| opposite side of otm_wall | 7563 | +0.023 | 0.201 |

"A steep approach won't push further" is **inverted**: steep approaches carry
through, and selling beyond them is the worst condition tested. "A sideways
approach won't fall back" points the right way, but the approach isn't what does
it. Selling behind ANY trendline break works, steep or flat. The opposite-side
trades on the premium signals contain nothing.

Controls on the break result:
- **Delay:** entering +4h later gives +0.099 and +8h gives +0.110. By +24h it's +0.072, no longer significant. That's a fading signal, not a leak.
- **Momentum:** the same 10-bar move without a level gives +0.03, not significant. The level adds something.
- **Consistency:** it holds for BTC and ETH, on the 240 and 360 timeframes, and in both halves of time.
- **Horizontal levels:** only 73 breaks, too few to judge.
- **Swing anchors:** trendline anchors are 5-bar swings, so breaks within 5 bars of the anchor were dropped.

Corrected 2026-10-02: the first run entered the opposite-side trades at the
trigger candle's OPEN (on 240m+ every entry came before the signal candle closed)
and deduplicated across assets. Fixed; the conclusion (nothing) is unchanged.

**Rule B by break side** (`short_side.py`): sell the PUT after an up-break, +0.117
(P = 0.023, halves +0.21 / +0.02); sell the CALL after a down-break, +0.102
(P = 0.076, halves +0.03 / +0.18). Both sides contribute, and neither is reliable
alone. The channel-line prediction (down-breaks cascade, so the call side should
dominate) is not confirmed.

## 2b. Quiet-day predictor as a seller filter (`quiet_sell.py`)

The days `when_not_to_trade.py` tells a BUYER to skip are the days a straddle
SELLER wants. Held-out days only, with the straddle entered at 00:00 UTC.

| straddle tenor | predicted quiet (top 30%) | other days | difference |
|---|---|---|---|
| 1–3 days | **+0.25%**, win 63%, worst **−6.9%** | −0.19%, win 58%, worst −21.5% | P = 0.039, CI [−0.05, +1.06] |
| same day | +0.01% | −0.00% | nothing |

- **Within IV terciles,** quiet beats the rest in all three for 1–3d.
- **Leak check:** corr with today's range −0.21, with tomorrow's −0.17. That is a forecast, not a description.
- **Thin:** only ~6 months of held-out days, 214 quiet straddles.
- **What matters for stress-free trading:** it cut the worst loss from −21.5% to −6.9% of spot.
- **Walk-forward rebuild (`quiet_wf.py`, 2026-10-03):** refit monthly on all earlier days and scored only
  on the next month. That gives 544 held-out asset-days, Dec 2025 – Sep 2026 (the features need
  history, so this is as far back as it goes). 1–3d straddle on predicted-quiet days: **+0.146% vs
  −0.271%, CI [+0.067, +0.770], P = 0.008**, and the same sign in 2025 and 2026. Worst −17.7% vs −21.5%,
  p5 −3.7% vs −4.8%. Same-day straddles: still nothing. **This is the strongest seller filter so far.**

## 3. Implied vs realised

Short ATM straddles (33k), with IV backed out of the straddle premium.

| | excess % | P(≤0) |
|---|---|---|
| IV top quintile | **+0.455** | 0.000 (halves +0.53 / +0.38) |
| IV/RV top quintile (the textbook rule) | −0.191 | 0.874 |

What pays is selling when options are expensive, not when they are rich relative
to recent realised vol. It's concentrated in 1–3 day tenors. **2026 alone is +0.10,
not significant.** Mark is sellable: on 786 sampled legs the median traded/mark
ratio is 1.004 in the top quintile and 1.002 elsewhere.

## 4. As rules, out of sample (thresholds from the first half only)

| rule | trades | win | mean/trade | worst trade | max DD | Sharpe |
|---|---|---|---|---|---|---|
| A high-IV straddle, in-sample | 328 | 64% | +0.39% | −20.6% | −43% | 2.33 |
| **A high-IV straddle, OUT** | 210 | 63% | **+0.17%** | −12.0% | −51% | 1.02 |
| B sell behind trendline break, in-sample | 912 | 75% | +0.14% | −12.2% | −45% | 1.90 |
| **B sell behind trendline break, OUT** | 912 | 73% | **+0.07%** | −9.4% | −30% | 1.25 |

Drawdown and return are in % of ONE position's notional, summed. B holds about 4
positions at once, so on capital that fully covers them that is roughly +12%/yr
against a ~−8% drawdown. A and B are uncorrelated (daily ρ = −0.01).

Both halve out of sample. **B is the more robust one.** A's out-of-sample
return/drawdown of 0.54 is not tradeable on its own.

## 5. Margin is the trap, not the opportunity

The product sheet shows `initial_margin 5`, `leverage 20`: about 5% of notional.
The worst single trade here loses **20% of spot, 4× that margin**. The p1 loss on
high-IV straddles is −10% of spot. Low margin lets you hold a position whose
normal tail liquidates you. **Size by the tail (−12 to −20% of notional per
position), not by the margin.**

## Bounds

- **Spread:** one live snapshot of the spread (1–2 Oct 2026). Spreads at historical moments, especially high-IV ones, are not measured.
- **Exits:** hold to expiry only. No stops, no rolling.
- **Spot:** S_T is the perp mark, not Delta's settlement index.
- **Size:** fill size and depth are unmeasured.
- **Data:** candles from 2026-09-17 onward (the audit found 1.3% of panel rows) were written by `fetch_options.py`, which uses the plain symbol, so those are TRADED prices. Earlier ones are MARK. That's two weeks of data, which doesn't move these results.

**Correction 2026-10-07 (review D5):** the Sharpe ratios in §4 were computed over trade days only.
- **Corrected (all calendar days, flat days included):** out-of-sample A 0.64 (was 1.02) and B 1.07
  (was 1.25).
- **Selection:** both rules were picked from ~25 conditions on the full sample.
- **Stacking the filters:** the quiet-day filter and the high-IV filter are ANTI-additive. Quiet &
  high-IV gives −0.84%, quiet & not-high gives +0.29% (`REVIEW_2026-10-07.md`).
