# When NOT to trade — a futures-side filter that survives

His reframe (2026-09-30): *"I don't necessarily want a direct answer in terms of
options... Even if we can identify when to trade or when not to trade (perhaps we
can try futures trading also when it is good to trade), that also would mean
something."*

He is right, and it is the better-posed question. Everything before scored against
`y = (a 100x option existed that day)`: rare, option-specific, and carrying the
max-across-strikes oracle. For FUTURES the question avoids option pricing entirely,
which is where edge kept being eaten. And the NEGATIVE side matters more to him --
overtrading is his stated problem, so a dependable "sit today out" is worth more
than a big-move detector.

## Targets, all strictly next-day

| target | definition | meaning |
|---|---|---|
| absret | \|C_D/C_{D-1} - 1\| | is there a move |
| eff | \|C_D - O_D\| / (H_D - L_D) | trend day vs chop day |
| rangeatr | (H_D - L_D) / ATR_{D-1} | did it move MORE than its own vol implied |
| mfe | max(H_D-O_D, O_D-L_D)/ATR | best excursion a futures trade could catch |

## First pass flagged itself

Built-in anti-leak check (rho against the PREVIOUS day's outcome, per
AUDIT_2026-09-30.md):

```
absret     rho(next) +0.117   rho(PREV) +0.151   flagged
rangeatr   rho(next) +0.205   rho(PREV) +0.239   flagged
mfe        rho(next) +0.174   rho(PREV) +0.227   flagged
eff        rho(next) +0.039   rho(PREV) +0.014   AUC 0.524, nothing
```

Not look-ahead -- the features are legitimately known before day D. The dull
explanation: the score is a VOLATILITY GAUGE and volatility clusters, so it looks
predictive by knowing what just happened. Which makes the real test whether it
beats a baseline any chart gives away free.

## Against a plain volatility baseline

BASELINE = 5-day mean \|return\|, 5-day mean range/ATR, ATR/price.

| target | side | baseline | +score | gain | verdict |
|---|---|---:|---:|---:|---|
| absret | BIG | 0.614 | 0.606 | -0.008 | redundant |
| eff | BIG | 0.535 | 0.543 | +0.008 | redundant |
| rangeatr | QUIET | 0.568 | **0.619** | **+0.051** | adds |
| rangeatr | BIG | 0.553 | 0.602 | +0.049 | adds |
| mfe | QUIET | 0.560 | **0.611** | **+0.051** | adds |
| mfe | BIG | 0.538 | 0.583 | +0.044 | adds |

**Raw move size is already owned by volatility.** But VOL-ADJUSTED range is a
different question -- did the market move more than its own volatility implied --
and there the score adds, equally on the quiet side.

Per asset, all four adding cells: BTC +0.033..+0.059, ETH +0.038..+0.076,
P(gain>0) 0.933-0.962. **Eight of eight positive, both assets agreeing in every
cell** -- the check apex and pascore-v1 both failed.

## The decision form

Rank held-out days by P(quiet), skip the top N%:

| skip top | days out | dead avoided | good missed | edge |
|---:|---:|---:|---:|---:|
| 10% | 35 | 16.5% | 6.1% | +10.4pp |
| 20% | 71 | 27.0% | 12.2% | +14.7pp |
| **30%** | 106 | **40.9%** | **17.3%** | **+23.5pp** |
| 40% | 142 | 50.4% | 29.6% | +20.8pp |
| 50% | 178 | 60.0% | 35.7% | +24.3pp |

Per asset at 30%: BTC +15.2pp, ETH +20.7pp. Positive at every threshold.

**Significance:** edge +21.5pp, P(edge>0) **1.000**, 95% CI **[+7.9, +33.9]pp**.
Random-skip control +0.1pp with 95% of draws in [-12.4,+12.3]; the actual filter
beats 100% of random skips.

## What this does NOT say

- **No direction.** `eff` (trend vs chop) is null at 0.524. This says "there will
  be room to move", not "you will make money". Room is necessary, not sufficient.
- `rangeatr` is a proxy for tradeable room, **not P&L**. A wide-range day still
  loses if you are on the wrong side.
- One held-out split, 356 days. The 30% threshold was read off the table, though
  the edge is positive at all five.
- spot_candles is the perp MARK series (see de-signals-spot-is-mark).

## The division of labour this suggests

The filter answers "is today worth showing up for". His journal scoring
(JOURNAL_SCORECARD.md) suggests his STRUCTURAL reads carry direction better than
his biased ones. Those are complementary: the model picks the days, he picks the
side.
