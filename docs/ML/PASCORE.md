# Price action as a single number (his idea, 2026-09-30)

His proposal: at the current bar draw a horizontal line, count the past bars it
hits, weight recent bars more; let tolerance GROW with age so a slightly sloped
line still catches a range from seven months ago; after a breakout the nearest hit
is far back, so multiply by a function of that distance; and fold in how the
current bar sits against the last few (small, barely-overlapping bars taking out
prior extremes).

Two changes preserving intent. **Normalise** the hit sum by total lookback weight,
so it is bounded and comparable across eras. **Tolerance as ATR-drift per bar, not
degrees** -- 1 degree over 200 bars is 3.5x price and everything would hit
everything; tau(age) = ATR*(TOL0 + DRIFT*age) says the same thing safely.

Added: **dispersion** (distinct time-clusters touched, not raw bars -- twenty
touches in one week is a weak RANGE, five across three epochs is a level the
market keeps rediscovering), **rejection magnitude**, **side asymmetry**, **round
numbers**.

## Protocol, fixed before any result

60/40 TIME split, no shuffling. Spec, coefficients and threshold chosen on TRAIN
only. All 24 specifications (4 weight families x 2 lookbacks x 3 drifts) reported
together so best-of-24 is visible.

## Does it predict? YES

| check | result |
|---|---|
| held-out AUC (train-selected spec) | **0.604** |
| across all 24 specs | 0.555 - 0.628, median 0.597 |
| BTC alone | 0.575 (P=0.959) |
| ETH alone | 0.580 (P=0.985) |
| weekly-block shuffle control | mean 0.503, real beats 100% of 25 |
| line-age >=100d alone | 0.586 |
| **line-age + score** | **0.627** |
| within old-line days | +20.1pp (P=0.992) |

Both assets agree in sign AND magnitude -- the check that killed the apex result.
Compare the five coiling features at held-out 0.485.

**His hit-count rule works INVERTED**: more weighted touches at the current price
means LESS chance of a big move, which is sensible -- it marks a well-worn range.
Second time in two days one of his observations measured real with the sign
flipped (cf. `hold` in PREMIUM_SIGNALS.md). Added components carry ~2/3 of the
coefficient weight, though multicollinearity makes that attribution soft.

## Does it pay? PARTLY -- and a measurement failure worth recording

**First attempt was invalid and was retracted.** With a MIN_PREM floor of 0.05
absolute, a mean day EV of +0.99 was reported. On ETH at ~$2,300 a $0.05 mark is
dust; ETH 2024-02-05 (13 contracts, ALL >=10x, median peak 357x -- a broken mark
series) alone supplied **53.3% of the summed EV across 1,943 days**. Every
expectancy figure from that run is withdrawn. The implausible base rate was
visible before the result was printed and was not checked.

Rebuilt with a spot-scaled dust floor (premium >= 0.05% of spot), a fixed 10x
take-profit, and MEDIAN plus share-positive as headline statistics. Top day then
contributes 11.5% instead of 53.3%.

| quintile | days | medianEV | %days+ | meanEV | P(100x day) |
|---|---:|---:|---:|---:|---:|
| Q1 | 143 | **-0.066** | 20.1% | +0.465 | 21.7% |
| Q2 | 142 | -0.656 | 12.8% | -0.271 | 21.8% |
| Q3 | 143 | -0.679 | 11.8% | -0.356 | 15.4% |
| Q4 | 142 | -0.431 | 15.5% | -0.036 | 27.5% |
| Q5 | 143 | **-0.046** | 19.1% | +0.252 | 42.0% |

Top quintile median EV **-0.046 vs -0.558** for the rest, Mann-Whitney
**p=0.0000** -- a RANK test, so it cannot be an outlier artifact. The score
separates days on the median, which is the statistic an account experiences.

**But the shape is a U, not a ranking.** Q1 is as good as Q5. That breaks "one
number" as stated.

### The two-regime explanation was offered, tested, and REFUTED

Proposed reading: Q5 = move likely but priced in; Q1 = well-worn quiet range so
options are CHEAP and a move pays more per rupee. `pascore_ushape.py` measures
median premium/spot in a fixed 4-8% OTM band:

| quintile | median premium/spot | P(100x day) |
|---|---:|---:|
| Q1 | **0.298%** | 21.7% |
| Q2 | 0.216% | 21.8% |
| Q3 | 0.310% | 15.4% |
| Q4 | 0.270% | 27.5% |
| Q5 | **0.217%** | 42.0% |

Q1 options are MORE expensive, not cheaper (Mann-Whitney p=0.944 against the
hypothesis). The story is dead, and backwards -- the same failure mode as his own
two inverted rules.

**The flip favours Q5.** It carries the highest big-move rate AND the cheapest
options: high probability at low cost, better than assumed. Q2 is equally cheap
(0.216%) with only 21.8% big-move days, so cheapness alone is not the mechanism.

**Q1 remains unexplained** -- expensive options, few big moves, decent median EV.

CAVEAT on the refutation itself: premium/spot at fixed moneyness is IV x sqrt(time),
so a day loaded with longer-dated contracts looks expensive without higher IV. That
confound could explain Q1's premium AND its EV together (more time to reach the 10x
cap). Two-regime is unsupported; the test is not clean enough to call it closed.
Next test: days-to-expiry mix by quintile.

Limits: Q5 absolute EV +0.25 with 95% CI [-0.04, +0.58] -- "better than the rest"
is established, "profitable" is not. Q5 AND old-line (n=46, median +0.59, 54.3%
big-move days) is an intersection found AFTER seeing both parts work: suggestive,
not validated. Everything rests on MARK prices via load_tf; 9,276 traded
contract-days exist for a re-check.
