# Brooks tested on his own terms — spot, not options

**2026-09-17/18.** A separate study from `CONTEXT_PLAN.md`. That one grades option
signals by the price action around them. This one tests Brooks' setups as setups,
on SPOT, judged by whether price did what he says it does.

---

## 1. Why the earlier test was weak, and Tejas was right to say so

The context study took option-signal firings as the population and asked whether
spot context predicted the OPTION's payoff. Three problems:

- the sample is "wherever an option signal happened to fire" — an odd, biased set
  of moments, not the moments Brooks points at;
- the outcome is routed through moneyness, time to expiry and the volatility
  premium, none of which he claims to forecast;
- it uses only signal bars. Every other bar is discarded.

His proposal: run the setups directly on spot, score them by what price does, and
trade futures on any that pay. Better on all three counts, and it uses spot data
we already hold.

## 2. The yardstick is his own

`00-core-concepts.md` sec 6 — the **trader's equation**:

> "Is there a >=60% chance of making at least your risk?"

Implemented literally as a first-crossing test: from a stop-entry beyond the
signal bar, is +1R reached BEFORE -1R? That is how a trade actually resolves,
unlike a terminal return. His own benchmarks give things to falsify:

| claim | source |
|---|---|
| an always-in flip implies roughly >=60% | core sec 4 |
| directional probability hovers near 50% most of the day | core sec 6 |
| ~80% of trading-range breakouts FAIL | ranges sec A |
| beginners lose on ~70%+ of countertrend channel scalps | reversals sec A |

Ten setups implemented in `brooks_setups.py`: H2/L2 pullbacks, failed breakouts
of a 20-bar range both ways, strong breakouts both ways, countertrend scalps both
ways, and always-in flips both ways.

## 3. A bug worth recording — the entry must FILL

The first run gave 38.34% pooled, far below the ~50% a symmetric 1:1 test should
produce. That was not a finding, it was a bug: **the stop-entry was assumed to
fill**. A setup where price immediately reversed was scored a LOSS even though the
trade never happened.

Fixed, the pooled figure moved to **47.09%** — the sane range. Identical in kind
to the option-side finding that 19.3% of mark-activated signals never traded
above their trigger. *An unfilled order is not a loss.*

## 4. BTC+ETH first, and why it was not enough

| timeframe | setups | win% |
|---|---|---|
| 60m | 13,602 | 47.17% |
| 240m | 3,347 | 46.16% |
| 1440m | **502** | **51.20%** |
| 10080m | **41** | **58.54%** |

**78% of the sample was hourly** — close to the opposite of where Brooks says to
look, and of where his blog now focuses. Daily and weekly hinted his way but on
502 and 41 samples, which is nothing. Setups scale with bars, and 2.7 years is
142 weekly bars per symbol.

## 5. The 220-perp expansion — and the hints did not survive

`brooks_perps.py`. 242,462 setups, 220 symbols, 140 weeks.

| timeframe | setups | win% |
|---|---|---|
| 240m | 212,981 | 49.25% |
| 1440m | 28,756 | **48.29%** |
| 10080m | 725 | 48.83% |

**Daily went 51.20% -> 48.29% with 57x more data. Weekly 58.54% -> 48.83%.** Both
were small-sample noise, and only expanding the sample revealed it.

Daily, with weekly-block CIs — **not one clears 50%**:

| setup | n | win% | 90% CI |
|---|---|---|---|
| strong breakout up | 1,184 | 53.66% | [48.48, 58.78] |
| always-in flips DOWN | 3,784 | 50.01% | [45.07, 54.99] |
| L2 pullback in bear trend | 6,056 | 49.54% | [44.87, 54.02] |
| H2 pullback in bull trend | 1,630 | 44.77% | [40.13, 49.45] |
| **always-in flips UP** | 1,890 | **44.31%** | [40.96, 48.10] |
| **failed breakout of range high** | 1,291 | **41.56%** | [36.02, 47.45] |

Two have CIs entirely BELOW 50. Brooks says an always-in flip implies ~60%; on
daily, flipping up is a measurably losing 1:1 trade. His with-trend pullbacks
(44.8%, 49.5%) are no better than the countertrend scalps he says beginners lose
70% on (47.5%, 49.6%) — the distinction at the centre of his method is not
visible here.

**Caveat that must travel with these numbers:** 220 symbols add ROWS, not
independent TIME. Mean pairwise correlation 0.385, N_eff 5.8 of 129. The
bootstrap resamples weeks for exactly this reason.

## 6. The reward-multiple sweep — the fair test of the METHOD

Testing only 1:1 tests his 60% CLAIM. He argues explicitly that a 40% trade with
a large reward is fine, so `brooks_rr.py` sweeps the multiple. Efficient trick:
record the max favourable excursion in R units before the stop, so one pass
answers every multiple (a trade wins at m iff MFE >= m).

Costs in R units: a futures round trip is taker 0.05% x2 + 18% GST = 0.118% of
notional, so cost in R = 0.00118 x entry / R. Tight stops are expensive, wide
ones cheap — invisible if you work in R alone. Median here: **0.0405 R**.

**EV in R units, net of cost. 258,402 setups, 141 weeks.**

| | R=1 | R=1.5 | R=2 | R=3 | R=5 |
|---|---|---|---|---|---|
| 240m pooled | -0.108 | -0.094 | -0.097 | -0.128 | -0.253 |
| 1440m pooled | -0.086 | -0.098 | -0.127 | -0.207 | -0.362 |

**All 100 cells negative** (10 setups x 5 multiples x 2 timeframes). Best in the
grid: strong breakout up, daily, R=1, **EV -0.002**, 90% CI [-0.103, +0.095],
**P(EV<=0) = 0.524**.

EV gets WORSE as the multiple rises, monotonically past R=1.5 — nothing runs far
enough often enough to pay for the stops taken on the way. And **costs are not
what kills it**: 0.04R of cost against 0.09-0.36R of loss. Removing costs
entirely leaves almost every cell negative.

## 7. Verdict

**Brooks' price action, implemented mechanically and tested on its own terms
across 220 instruments, 141 weeks, 258,402 setups, two timeframes and five reward
multiples, has no edge on spot direction.** Not at 60%, not at 40%-with-big-
reward, not before costs.

This is a stronger statement than the option-side work could support, because it
is his claim tested his way.

### Two limits that are real

**These are mechanical readings.** Two failures this week turned out to be
mis-specification, not refutation (trend lines were 30-day regressions; the tight
range fired on 0.3% of bars). An "H2 pullback" found by leg-counting is not
necessarily what he would point at, and he insists CONTEXT decides — which a
detector firing on every qualifying bar cannot supply.

**Weekly is still thin.** 725 setups over 68 weeks from 43 symbols, excluded from
the sweep. That is the timeframe he and Tejas both favour, and it remains
untested rather than refuted. Only elapsed time or equities fixes it.

## 8. The inverse test — signals NEAR setups

Tejas's follow-up: instead of signal -> context, look for signals firing near a
setup. His 1:20 ETH trade had both on the same candle.

Genuinely different from the context study, which measured point-in-time STATES
at the signal bar and never asked whether a named setup had just fired.

| co-occurrence | keep | hit25 | marginal to R4+R5 | P |
|---|---|---|---|---|
| **same bar** | 4.9% | **4.96%** vs 3.89% | +0.256 | 0.172 |
| same or previous bar | 24.5% | 4.06% | +0.211 | 0.088 |
| within 3 bars before | 43.3% | 4.00% | +0.053 | 0.323 |
| within 3 bars after (LOOKAHEAD) | 42.6% | 4.57% | — | — |

**Same-bar is significant standalone** (dEV +0.266, P=0.004) and the effect decays
sharply as the window widens — the shape of a real effect. But it does not
survive on top of R4+R5 (P=0.172) and profit/week goes to -83 because it keeps
3.7% of trades.

The lookahead row is a sanity check: knowing the future helps (4.57% vs 4.00%),
which confirms the detector marks moments where price moves, and confirms you
cannot trade on it.

**On the 40% hope:** best cell anywhere is R4+R5 AND same-bar setup = **7.54%**.
Break-even is 4.33%. 40% would be ~9x that, and would mean 2 in 5 deep-OTM
options going 25x — a market-wide mispricing, not an edge. Nothing in 350,000
events approaches it.

## 9. The review viewer — port 4000

`build_setup_review.py` -> `data/setup_review/{spot}/{expiry}.json`, served by
`serve_setups.js`. One sheet per expiry, 1,924 files.

Inverts the grid viewers: starts from a SETUP, shows what happened next, and
lists option signals that fired within 3 bars in the same direction. A few dozen
rows per expiry instead of thousands of cells.

Every row carries the MEASURED win rate beside Brooks' expectation, so the claim
never stands unqualified.

**What the first sheet already shows:** on BTC 2026-08-28, all 66 setups had a
signal within 3 bars. Signals fire often enough that nearly any setup has one
nearby — which is why same-bar co-occurrence (4.9% of signals) behaves so
differently from +-3 bars (43.3%).

**`best_ratio` is an ORACLE number** — the best strike in hindsight, on mark
prices. Read it as "what was available here", never "what you would have earned".
