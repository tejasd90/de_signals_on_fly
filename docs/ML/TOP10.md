# Findings, ranked

**Updated 2026-09-26.** Data current to 2026-09-25 (spot, 220 perps, OI).
Supersedes the 2026-09-23 version, which pre-dated the wedge work, the reverse
search and the `moneyness_pct` sign bug.

Sorted by **evidence strength** — a combination of P-value, sample size and
whether the result survived an out-of-sample or implementable-measure test.
Every row carries its own numbers so you can re-sort on whichever column matters.

Reference: an option needs **4.33%** at a 25x target, **1.08%** at 100x, or
**0.54%** at 200x to cover the Delta round trip.

---

## A. Standing results

| # | finding | effect | P | sample | survived |
|---|---|---|---|---|---|
| 1 | **Cross-sectional low-vol perp book** | +58.4%/yr, Sharpe 2.44, maxDD −18.2% | **0.0003** | 142 weeks, 207 names | survivorship fix, equal-risk, beta-hedge, $100M capacity |
| 2 | **Breadth is the structural lever** | effective bets 4.3 → 58.2 (~3.7x IR) | — | 158 names | arithmetic, not a fitted result |
| 3 | **R4 — agree with the 4h trend** | 5.96% vs 3.89% base (BE 4.33%) | **0.000** | all 142 weeks | works at 100x too (1.799%, P=0.002); only rule with traded-price backing |
| 4 | **Line age ≥100d on a break day** | +15.8pp on P(100x within 0–3d) | **0.000** | 146 days | the only level feature surviving BOTH oracle and implementable tests |
| 5 | **>10% OTM on a break day, 100x** | 1.74% vs 0.61% on no-break days | **0.005** | 59,852 events | improved after the sign-bug fix (was P=0.043) |
| 6 | **Break geometry pays on PUTS only** | puts dEV +1.006, calls −0.179 | **0.011** | 142 weeks | direction control 5/5 buckets; leave-one-month-out |
| 7 | **Wedge breaks** | BTC +18.1pp, ETH +22.3pp | **0.022–0.024** | n=31, n=27 | replicates independently on both symbols |
| 8 | **Containment rule (yours)** | 2.17x lift, 4.34% vs 2.00% | **0.014** | 28.7% of triggers | only pattern-SHAPE feature ever to survive here |
| 9 | **Grid path-length law** | gross = path × size, spacing-independent | exact | all spacings 2–50 | arithmetic; kills every tight-grid variant |
| 10 | **Fakeouts don't matter to option buyers** | 2.23% held vs 2.21% trapped | — | 1,848 breaks | explains why "push past line" predicts traps but not payoff |

### Secondary, useful, weaker

| # | finding | effect | P | note |
|---|---|---|---|---|
| 11 | Cube: the edge is the CALL leg | OTM calls 6.82%, EV +5.74 at 100x | 0.14 (200x) | 88 legs. Puts 0/85 — sample size, not a bug |
| 12 | Grid and puts are one position | put rule fires on 24.2% of grid's worst days vs 8.4% best | — | positive-carry left-tail hedge |
| 13 | Horizon reconciles two results | best option cell at days, worst sustain at 60d | 0.036 / 0.962 | crashes continue for days, revert over months |
| 14 | 200x beats 100x as a target | EV +4.59 vs +3.17 | 0.12 | EV still rises to 500x but on 2 observations |
| 15 | Weekly (3–9d) beats immediate expiry | 4.26% vs 1.54% at 100x | — | 0–2 DTE can't survive break→retest→run |

---

## B. Retracted or superseded

| claim | was | now |
|---|---|---|
| **Long ATM / short far-OTM options** | +44.2%, P=0.0055 | **RETRACTED** — +22.1%, P=0.204 after the sign fix; put leg flipped +21.1% → −21.1% |
| **"Breaks of 3x-rejected levels pay"** | +18pp headline | **SUPERSEDED** — over 0–3 days ordinary breaks add nothing (P=0.43); the wedge subset carried it |
| Candle quality improves selection | +17.1pp, P=0.000 | **oracle only** — makes the implementable cube worse |
| Zone pooling improves selection | +8.0pp, P=0.001 | **oracle only** — cube unchanged; zone SIZE alone is 0.00% |
| Break count ranks days | used throughout | **dead** — P=0.337 at ≥15 breaks |

## C. Known coverage limits

Measured on merged market events (`trades.js`), which is the honest unit:

- **44% of ≥100x market events have NO level break at all.**
- Break **direction is near-random**: 32.5% same-direction vs 29.2% opposite.
- Only the age qualifier enriches, at **1.65x**, covering **7.2%** of big events.

So the level system is a low-coverage, direction-blind, weak-enrichment detector.
It is real but small. The cross-sectional perp book (row 1) is the only result
here with both strong evidence and enough breadth to trade continuously.

## D. Dead — do not retry

Absorption / "calm before the move" (null, then **significantly backwards**:
+15.5pp more traps in the most compressed quartile). 44 MA bounce (44 not
special; setup underperforms its own control, P=0.964). Exhaustion lows (1.0%
base rate; nothing finds them — not candle shape, not open interest). Open
interest generally (orthogonal to price-vol, P=0.116). Buy-and-hold cheap OTM
(P 0.31–0.87). Options relative value on cheapness (P 0.41–0.77). Rising-size
pyramids (8.5x capital for 16%; median pullback is 18.5%). Funding carry
(reproduced independently at −5.8%). Expiry proximity (inverts). Weekly
always-in (actively harmful, dEV −0.368).

## E. Three measurement artifacts, all of which inflated a result

Worth knowing because they recur: the **max-across-strikes oracle** (32.8% became
2.2% per contract), **per-contract weighting** in the reverse search (24% missed
became 44% on merged events), and the **`moneyness_pct` sign convention**
(+OTM for calls, −OTM for puts — filters caught ITM puts).

None of the three ever deflated a result. The cheap guard is a one-line sanity
check on any new field — median premium by side, in the last case — before it is
used in a filter.
