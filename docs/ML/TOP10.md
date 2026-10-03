# Findings, ranked

**Updated 2026-09-26.** Data current to 2026-09-25 (spot, 220 perps, OI).
**Annotated 2026-10-02:** rows 1, 4, 5, 7 and 11 carry dated notes. Rows 4, 5, 7 are
NOT standing as forecasts after AUDIT_2026-09-30.md; read them as descriptions of a
move in progress. For the current list of what survives see README.md "State as
of 2026-10-02".
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
| 1 | **Cross-sectional low-vol perp book** | +58.4%/yr, Sharpe 2.44, maxDD −18.2% (**updated 2026-10-02:** +59.4%/yr, Sharpe 2.48, maxDD −18.2%, CI [+34, +84]; short leg 117%) | **0.0003** | 142 weeks, 207 names | survivorship fix, equal-risk, beta-hedge, $100M capacity (+45.9%, Sharpe 1.87), taker+30bps (+50.8%, Sharpe 2.13) |
| 2 | **Breadth is the structural lever** | effective bets 4.3 → 58.2 (~3.7x IR) | — | 158 names | arithmetic, not a fitted result |
| 3 | **R4 — agree with the 4h trend** | 5.96% vs 3.89% base (BE 4.33%) | **0.000** | all 142 weeks | works at 100x too (1.799%, P=0.002); only rule with traded-price backing |
| 4 | **Line age ≥100d on a break day** | +15.8pp on P(100x within 0–3d) | **0.000** | 146 days | the only level feature surviving BOTH oracle and implementable tests. **Qualified 2026-10-02:** not standing as a forecast — same-day +16.8pp, next-day +6.7pp (P=0.908); break before entry on only 38% of BTC days. See AUDIT_2026-09-30.md §2–3 |
| 5 | **>10% OTM on a break day, 100x** | 1.74% vs 0.61% on no-break days | **0.005** | 59,852 events | improved after the sign-bug fix (was P=0.043). **Qualified 2026-10-02:** scored SAME-day, the class the audit found mostly co-occurrence; never re-run next-day. For "any break" the median lead is only +0.5h (BTC) / +0.7h (ETH), and a daily-close trigger enters after it. Untested as tradeable — see AUDIT_2026-09-30.md |
| 6 | **Break geometry pays on PUTS only** | puts dEV +1.006, calls −0.179 | **0.011** | 142 weeks | direction control 5/5 buckets; leave-one-month-out |
| 7 | **Wedge breaks** | BTC +18.1pp, ETH +22.3pp | **0.022–0.024** | n=31, n=27 | replicates independently on both symbols. **Qualified 2026-10-02:** not standing as a forecast — same-day +20.0pp, next-day +4.8pp (P=0.804); break arrives 2.5–3.9h AFTER the option is running. See AUDIT_2026-09-30.md §2–3 |
| 8 | **Containment rule (yours)** | 2.17x lift, 4.34% vs 2.00% | **0.014** | 28.7% of triggers | only pattern-SHAPE feature ever to survive here |
| 9 | **Grid path-length law** | gross = path × size, spacing-independent | exact | all spacings 2–50 | arithmetic; kills every tight-grid variant |
| 10 | **Fakeouts don't matter to option buyers** | 2.23% held vs 2.21% trapped | — | 1,848 breaks | explains why "push past line" predicts traps but not payoff |

### Secondary, useful, weaker

| # | finding | effect | P | note |
|---|---|---|---|---|
| 11 | Cube: the edge is the CALL leg | OTM calls 6.82%, EV +5.74 at 100x | 0.14 (200x) | 88 legs. Puts 0/85 — sample size, not a bug. **Reconciled 2026-10-02:** see note below the table — the call/put split here is post hoc and UNPROVEN (6 hits); row 6 is the tested side result |
| 12 | Grid and puts are one position | put rule fires on 24.2% of grid's worst days vs 8.4% best | — | positive-carry left-tail hedge |
| 13 | Horizon reconciles two results | best option cell at days, worst sustain at 60d | 0.036 / 0.962 | crashes continue for days, revert over months |
| 14 | 200x beats 100x as a target | EV +4.59 vs +3.17 | 0.12 | EV still rises to 500x but on 2 observations |
| 15 | Weekly (3–9d) beats immediate expiry | 4.26% vs 1.54% at 100x | — | 0–2 DTE can't survive break→retest→run |

**Note 2026-10-02 — rows 6 and 11 are different tests and do not contradict, but
row 11's label overstates it.** Row 6 is channel/trend-line break geometry as a
weekly put/call selection filter (CONTEXT_PLAN "Where the effect actually lives:
PUTS ONLY"): puts dEV +1.006, P=0.011, direction control 5/5 buckets, held-out 2026
P=0.043; calls −0.179 and below 1.0x in 4/5 buckets. Row 11 is the line-AGE cube
(top 5% by age, weekly, 100x): 6 hits in 88 call legs vs 0 in 85 put legs, where
0.5 put hits were expected. CONTEXT_PLAN's own sign-bug section says that split
"was examined post hoc, so the call/put asymmetry is UNPROVEN". Read row 11 as
"the cube's few hits happened to be calls", not "the edge is the call leg". It also
rests on line age, which the audit qualifies (row 4). The side result that stands
is row 6: **puts**.

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

---

## Approach path — FALSIFIED (2026-09-28)

Hypothesis (his, from the weekly chart): the PATH a market takes into a level
matters — a quiet, coiled, sideways approach loads more energy into the break.

`approach.py`, 696 break days with a measurable approach, base P(100x, 0-3d) = 69.3%.

| condition | days | P(100x) | lift | P |
|---|---:|---:|---:|---:|
| SIDEWAYS approach (travel bottom 25%) | 174 | 69.0% | -0.3 | 0.534 |
| STEEP approach (travel top 25%) | 174 | 74.1% | +5.9 | 0.062 |
| CHOPPY (efficiency bottom 25%) | 174 | 69.5% | +0.2 | 0.484 |
| TRENDED (efficiency top 25%) | 174 | 70.7% | +1.9 | 0.325 |
| **old line >=100d (reference)** | 143 | **82.5%** | **+15.5** | **0.001** |
| sideways AND old line >=100d | 18 | 88.9% | +20.4 | 0.008 |
| steep AND old line >=100d | 52 | 86.5% | +18.3 | 0.001 |

**Null on its own.** Three of four cells are flat. The single flicker (steep,
+5.9pp P=0.062) points the OPPOSITE way from the hypothesis — a fast run in, not
a quiet one.

**The combinations do not beat line age alone.** 88.9% on n=18 and 86.5% on n=52
against an 82.5% reference are both well inside noise at those counts. The
approach path adds nothing to line age; line age already holds what there is.

**His 17 Aug example measured travel -1.36 ATR (10th pctile), efficiency 0.07** —
a textbook coiled approach, sitting squarely in the 69.0% / P=0.534 cell. The
setup that generated the hypothesis falls in the deadest bucket in the table.

This is the SIXTH operationalisation of "coiled energy precedes the break" to
return null, after compression, quiet-range, absorption, net travel and path
efficiency. Six independent framings, no survivors: treat as falsified, not
unmeasured.

---

## Apex proximity — REJECTED (2026-09-29)

Hypothesis (his, from the BankNifty weekly): a descending line off the Sep-2024
and Feb-2026 highs and a rising line off the Oct-2025 and Apr-2026 lows converged
near 57,500 around Sep 2026, and price resolved DOWN essentially at the crossing,
to 53,890. Does breaking AT the apex beat breaking while the wedge is still wide?

Conditioner on the surviving wedge result. Two measures, matched terciles:

| | width_atr | bars-to-apex |
|---|---:|---:|
| BTC all (n=81) | +33.3pp (P=0.995) | +15.8pp (P=0.830) |
| BTC down breaks | +45.5pp (P=0.991) | +22.0pp (P=0.840) |
| ETH all (n=69) | -3.2pp (P=0.407) | -20.6pp (P=0.070) |
| ETH down breaks | -16.7pp (P=0.132) | **-33.0pp (P=0.037)** |

**Rejected.** The two measures agree WITHIN each asset, so the metric is sound.
The assets disagree with EACH OTHER, and on ETH breaking FAR from the apex is
nominally significant in the opposite direction. Two assets, opposite signs, one
nominally significant each way, n=8-24 per cell: the signature of no effect plus
small samples. BTC alone would have been the largest number in this project.

**A wrong mechanism, recorded because the correction is the useful part.** The
first explanation offered was that width_atr = gap/ATR is an ATR proxy, firing on
volatile regimes rather than geometry. `apex_debunk.py` refutes it:
spearman(width_atr, bars_to_apex) = +0.74 BTC / +0.78 ETH, while
spearman(width_atr, ATR) = -0.24 / +0.28 -- weak and OPPOSITE signs. width_atr
measures the apex well. The effect simply is not there.

Note the wedge break ITSELF still survives (+24.6pp up, +33.8pp down). What fails
is conditioning on WHERE in the convergence the break happens.


---

## QUALIFICATION on the level/wedge results (2026-09-30 audit)

`audit_sameday.py` and `audit_ordering.py` (see AUDIT_2026-09-30.md) show the two
surviving level results are largely SAME-DAY co-occurrence, not forecasts:

| feature | same day | next day |
|---|---:|---:|
| old line >=100d | +16.8pp (P=0.999) | +6.7pp (P=0.908) |
| wedge break | +20.0pp (P=1.000) | +4.8pp (P=0.804) |

And within a break day, the break usually arrives AFTER the option is already
running: BTC wedges 25.9% before (median lead -2.5h), ETH wedges 35.7% (-3.9h),
BTC old lines 38.2% (-0.7h).

**These entries remain in the table but are NOT tradeable as stated.** A signal
whose median lead is negative is a description of a move in progress. The
forecastable residual is the next-day figure, and neither is significant.
