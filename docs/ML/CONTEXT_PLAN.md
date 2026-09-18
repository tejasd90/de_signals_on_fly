# CONTEXT PLAN — grade a signal by the price action around it

**Written 2026-09-16.** Tejas's proposal: stop treating a signal as self-contained.
Score it by the SPOT context at the moment it fired, keep the ones in good
context, veto the rest. Drop the tuning parameters and strength values entirely —
keep the signal STRUCTURE and add CONTEXT.

This is `ML_SPEC` **D-03**, the veto reframe, which HANDOFF §5 flagged as the right
target and then noted "the work has drifted off it". It is now back on it.

---

## 1. The two examples, and why they are the whole design

| | context | Brooks says | verdict |
|---|---|---|---|
| **ETH, 15 Sep** | rangebound on HTF since 21 Aug; rejection from above 2600, i.e. the range extreme | `02-trading-ranges` C: *"Large trend bars into the range extremes are signals to fade, not to chase."* Mantra: buy low, sell high | **TAKE** — paid ~1:20 |
| **The localhost one** | pullback in a strong uptrend, no trend-line break | `00-core-concepts` §10: *"Don't trade against a trend until after the channel is broken, with a strong signal bar."* | **SKIP** |

Same signal (`otm_red_squeeze`), opposite conclusions, and **the second one had the
higher strength value** — which is the case against strength values, made by Tejas's
own eye before any model.

The discriminator between those two rows is exactly one thing: **is the market in a
trend or a range, and has the trend line been broken?** That is a geometry question,
not a learning question.

---

## 2. Do we need ML to find trend lines? No — and using it would be a mistake

Swing points, trend lines, channel lines, breakouts, failed breakouts, bar bodies
and tails, and bar-to-bar overlap are all **deterministic geometry**. You compute
them; there is nothing to learn. This is the project's own standing rule, HANDOFF
§4: **structure by hand, thresholds by model.**

The stronger argument is budget. The binding constraint on every result in this
project is **144 independent weeks** (measured again for this population, §4).
Spending that scarce statistical budget teaching a model to rediscover what a trend
line is — something that can be written down in an afternoon — instead of spending
it on the only question that actually needs fitting ("which contexts pay") is the
worst possible allocation.

**ML enters at exactly one place: the final keep/skip decision**, on top of context
features that were computed, not learned. And even there it only earns its place if
it beats two hand-written Brooks rules (§6, Phase 2).

---

## 3. Why this is NOT a re-run of the falsified arm 4

Arm 4 (105 Brooks spot features) came back null: AUC 0.5286, p=0.150, bootstrap CI
[0.4865, 0.5668]. The memory rule says do not propose more spot-side timing features
at hourly resolution. Three things make this a different experiment:

1. **Different population.** Arm 4 ran on `disc_final`, whose `signal` column is
   **100% NULL** — it is the random-entry population, every contract at every moment.
   This conditions on **a signal having fired**. That population has never been the
   subject of an ML study in this project.
2. **Different target.** Arm 4 was a GENERATOR: "will this episode's top-10 strikes
   pay". This is a VETO on events that already exist. HANDOFF §5 argues the veto is
   the better-posed problem because it has thousands of clean negatives instead of a
   few hundred positives — and §4 confirms that is true here.
3. **Different features.** `brooks_features.py:150` computes "channel" as
   `rolling(L).std()` — a volatility proxy. **There is no fitted trend line or
   channel line anywhere in the 105 features.** `BROOKS_FEATURES.md:145` lists
   trend-line fitting as the one specified item never implemented. It is also the
   FIRST tool Brooks names, and the exact thing that separates the two examples.

### The encouraging prior

Example 2 is, in cruder form, **the one regime filter that already survived**:
`trend20 != up` — skip deep-OTM in clean uptrends. dEV **+0.0609**, P(dEV≤0)=0.010
on a paired weekly-block bootstrap, keeps 82% of trades, same sign in all three
years. A blunt 20-day trend label already paid. Tejas is proposing the precise
version of the same idea, and arrived at it independently from the charts.

That is the best reason to expect this to work — not novelty, but that a crude
version of it is already a measured, surviving result.

---

## 4. The population, counted before any modelling

Signal firings at durations **≥30m** (Tejas's floor; matches `MIN_DURATION_MINUTES`):

| signal | merged firings | strike-firings | strikes per firing | days |
|---|---|---|---|---|
| red_squeeze | 153,782 | 619,821 | 4.0 | 986 |
| otm_red_squeeze | 133,127 | 397,275 | 3.0 | 984 |
| green_stairs | 59,977 | 132,212 | 2.2 | 984 |
| **otm_wall** | **54,766** | **516,211** | **9.4** | **985** |
| **TOTAL** | **401,652** | **1,665,519** | 4.1 | **988** |

`otm_wall` regenerated 2026-09-16 after the fix below: 1,993 (spot, expiry) pairs,
0 errors, 17.7 min, using the new `backfill.js --signal` flag so the other three
were not rewritten.

**`otm_wall` is structurally different from its siblings and this matters.** It has
the FEWEST merged firings but the SECOND-MOST strike-firings — **9.4 strikes per
firing against 2.2–4.0 for the others.** That is the signal's nature: a wall bar is
a spot move, so the whole chain lights up at once, whereas a squeeze or a staircase
is more strike-specific.

Consequence for the study: `otm_wall` events are **broader but not more numerous**.
Counting its strike-firings as independent samples would inflate its weight ~2.4x
relative to the others — HANDOFF §3.2's 6,920x episode-inflation trap in miniature.
**Weight by merged firing, not by strike-firing, whenever the four are pooled.**

**142 distinct weeks.** Rows are abundant; independent time is not, as always. For a
veto this is a better shape than it looks: conditional effect sizes will be tightly
measured, and the open question is stability across the 144 weeks — which is what
the weekly block bootstrap is for.

### `otm_wall` never fired — root-caused and FIXED 2026-09-16

Not a 30m-floor artifact. On BTC it had **988 signal files in every one of its 16
durations, 5m through 1440m, and zero firings in any of them.**

**The bug**, `signals/otm_wall.js:106`:

```js
const minValue = opts.minSignalValue !== undefined ? opts.minSignalValue
               : (typeof c !== 'undefined' ? c.THRESH : JUMP_THRESH);
```

`c` is a module-level `require('./otm_common')`, so `typeof c !== 'undefined'` is
**always true** and the `JUMP_THRESH` branch is dead code. Every run therefore
gated on `c.THRESH` = `OTM_SIGNAL_THRESHOLD` = **1000**.

But `otm_wall` is on a different scale from its siblings. `green_stairs` and
`otm_red_squeeze` score with `spot / mean(pattern lows)`, which runs in the
thousands — 1000 is the right gate for them. `otm_wall` scores with a **log10
jump**, which ranges ~0–8. The test `if (jump < 1000) continue;` skipped every
candle in the dataset. Silent, total, and for the entire history.

This is HANDOFF §3.7 exactly: *a stage that can do zero work must say so loudly.*

**Fix:** default to `JUMP_THRESH` (`WALL_JUMP_THRESHOLD` = 2). Verified against
Tejas's two charted examples, which now fire with no override:

| contract | duration | fires at |
|---|---|---|
| `C-BTC-66000-200826` | 90m | 2026-08-19 19:00 IST |
| `C-BTC-68000-210826` | 120m | 2026-08-19 19:30 IST |

Both land on the wall bar he pointed at. The dead `typeof c` guard was also
removed from `green_stairs` and `otm_red_squeeze` — behaviour-preserving there,
but it was a landmine referencing an undefined `JUMP_THRESH`.

**Scale after the fix:** a 6-expiry / 6-duration sample gives 394 firings from
2,090 contract-durations, projecting to roughly **130,000 firings on BTC alone** —
a fourth event family larger than `green_stairs` or `otm_red_squeeze`.

**Requires a signal regeneration** (`backfill.js --signals-only --force-signals`)
before it appears in any stored data or viewer. That is free of API calls but
slow. Not yet run.

---

## 4b. Volume policy — settled

- **Options: no volume.** Stored option candles are `MARK:` prices with volume
  `null` everywhere. Even the traded series is thin — median 77.7% of hourly bars
  have any print at all, and depth is unmeasured. Brooks' own view (volume is not
  a reliable indicator) points the same way. **Do not build option volume
  features.**
- **Futures/perps: use volume.** `data/perp_candles/` are traded candles with
  real volume in a median 90% of bars. Round 2 of the NN work got part of its
  0.5029 → 0.6630 gain from feeding raw sequences *including* volume.

So volume is a futures-side input only. Nothing in this plan needs it.

## 4c. Timeframes below 30m — to be pruned, noted not scheduled

Tejas's call: phase out sub-30m durations from candles, signals and viewers
entirely. Already enforced at the display layer (`MIN_DURATION_MINUTES = 30`) and
in this plan's population. The deeper prune — `DURATION_TIMES` in `config.js`,
then re-extraction — is **deliberately deferred**, recorded here so it is not lost.
Reclaims disk and removes the noisiest end of the data.

## 4d. Chart-image CNNs — real, parked, and the right time is later

Rendering candles to images and training a CNN is a genuine published approach,
not a fringe idea. Two reasons it is wrong *here* and right *later*:

- **Wrong here.** Rendering to pixels *discards* information — it quantises price
  to pixel rows and throws away exact OHLC — while adding parameters. Measured in
  this project: a CNN on raw OHLCV lost to trees in 4 of 4 folds, and a
  Transformer was worst and 84 min/fold. At **144 independent weeks** the binding
  constraint is evidence, not representation.
- **Right later.** The published results that work use enormous cross-sections —
  decades of US equities, millions of images. That is precisely the regime
  `INDIA_PLAN.md` describes: 10–20k stocks x up to 30 years. If that data lands
  and Phase 0 there shows a real N_eff, an image CNN becomes a reasonable arm.

Park it against INDIA_PLAN, not this one.

## 5. Which Brooks source wins — both, with different jobs

- **`Brooks/0{0,1,2,3}-*.md` supersede for CONCEPTS.** They distil the trilogy,
  which Brooks himself treats as authoritative over the 2009 book (~5% survives).
  They define the new STRUCTURAL layer: trend/range state, spike-vs-channel,
  always-in, trend-line break, range extremes, breakout failure rates.
- **`brooks_features.py` stays as the BAR layer.** Its 105 features already cover
  two of the six tools in Tejas's quote — body/tail sizes, and current bar versus
  the prior several bars. That code works and is verified (0 all-NaN, 0
  zero-variance). Deleting it to rewrite the same thing would be waste.

So: keep the bar layer, add the structural layer on top. The structural layer is
what is missing.

---

## 6. The plan

### Phase 0 — build the event table (~1 day)
One row per signal firing at ≥30m: signal, spot, expiry, symbol, duration, entry
timestamp, entry premium, and the outcome.

- Outcome from **traded** candles (plain symbol, no `MARK:` prefix), not mark.
- Apply the **≥2.0 entry premium floor** — measured on the 2026-08-19 squeeze,
  contracts at 0.5 premium produce 20x "wins" that are one tick of noise.
- Carry `_w` if anything is sampled. Assert no column starts with `label` or `_`.

**Gate:** print events per week and per regime. If any later cell has <30 weeks of
support, it cannot be claimed.

### Phase 0 RESULT — built 2026-09-16, gate PASSES

`build_events.py` -> `events.parquet`: **1,658,837 rows x 28 cols, 400,688 events,
126,276 contracts, 97 MB**, spanning 2023-12-29 to 2026-09-15. 99.6% of
strike-firings resolved; the rest lost to missing candles or an entry outside the
one-bar timestamp tolerance.

**The gate.** Every signal appears in all **142 weeks**. Median events per week:
red_squeeze 1,104 · otm_red_squeeze 952 · green_stairs 422 · otm_wall 387 ·
**pooled 2,894**. Thin weeks exist (min 2-4) but no signal is absent from any
week. There is ample support for conditional estimates; the constraint remains
142 independent weeks for significance, exactly as expected.

**Fill rate.** `activated` is true for **73.5% of rows and 81.1% of events**. So
roughly a fifth of "signals" never trigger at all. Those are not trades. This also
splits the research question usefully: *does context predict whether it even
fills* is a cleaner and easier question than *does context predict the payoff*,
and both are now answerable from this table.

**Base rates on FILLED rows (peak vs trigger):**

| signal | events | median premium | 2x | 5x | 10x | 25x |
|---|---|---|---|---|---|---|
| green_stairs | 48,712 | 9.5 | 32.7% | 13.3% | 7.8% | **3.55%** |
| otm_red_squeeze | 105,312 | 3.5 | 34.5% | 14.0% | 7.8% | **3.40%** |
| red_squeeze | 127,987 | 124.9 | 32.4% | 10.1% | 4.5% | 1.54% |
| otm_wall | 42,966 | 199.1 | 32.2% | 9.1% | 3.3% | **0.84%** |

### The trap hiding in that table — read before comparing signals

The 25x column spans 4.2x between best and worst, and it is **almost entirely a
premium artifact, not signal quality.** The rank order of 25x rate is the exact
inverse of the rank order of median entry premium: 3.5 and 9.5 for the two
high-scoring signals, 125 and 199 for the two low-scoring ones. A cheap option
reaches 25x far more easily than an expensive one, and `red_squeeze` is not even
OTM-restricted.

This is the same effect as `cheapness` topping permutation importance while
**losing money on its own** (-0.047, hitting 25x less often than random). Raw hit
rate tracks cheapness, and cheapness is not edge.

**Therefore: never compare signals, or contexts, on raw hit rate. Stratify by
entry premium, or compare within a premium band.** Applies to every Phase 2 rule
and to the Phase 3 model. The premium floor sweep shows the same thing from the
other side — floor 0 -> 2 drops 25x from 1.89% to 1.52% while removing 27% of
events, i.e. the floor is removing exactly the cheap lottery tickets whose hit
rate is unearned.

### Phase 1 — context features, computed not learned (~2 days)
Organised by Brooks' own list from Tejas's quote. Target ~60–80 features on the
signal's own duration **and** on the next 2 timeframes up (his "rangebound on HTF,
rejection on LTF" framing; core-concepts §1: most trends are ranges on a HTF).

1. **Trend lines** — least squares on SWING points (the never-implemented item).
   Slope, R², bars since last touch, distance in ATR, and **broken or not**.
2. **Trend channel lines** — parallel line on opposite swings; overshoot count/size.
3. **Prior highs and lows** — distance in ATR to nearest swing high/low, prior
   day/week extremes; **is price AT a range extreme** (the example-1 context).
4. **Breakouts and failed breakouts** — attempts in last N bars, and how many
   failed. Brooks: ~80% of range breakouts fail.
5. **Bar bodies and tails** — reuse `brooks_features.py`.
6. **Current bar vs prior several bars** — overlap %, micro gaps. Partly exists.
7. **Trend/range state** — trend-bar %, body overlap, MA slope and flatness,
   consecutive closes on one side of the MA, bars in the middle third. Produces a
   position on the core-concepts §1 spectrum.
8. **Always-in direction, and whether the signal agrees with it.** Single most
   important feature for example 2.

All ATR-normalised, no raw prices, no lookahead — swing at bar *j* is known at
*j+1*, and `brooks_features.py` already handles that lag correctly.

### Phase 2 — the Brooks rules as explicit filters, BEFORE any model (~2 days)

This phase exists so that if hand-written rules work, no model is needed. Each is
a one-line predicate over Phase 1 features. R1 and R2 are Tejas's two examples;
the rest come from the same four summary files and are testable on the same table.

| # | rule | source | decision |
|---|---|---|---|
| **R1** | countertrend signal in a strong trend with **no trend-line break** | core §10 | SKIP |
| **R2** | fade at a **range extreme** while state = range | 02 §C | TAKE |
| **R3** | with-breakout entry out of a range | 02 §A — *~80% of range breakouts fail* | SKIP unless breakout strength > reversal strength (core §3) |
| **R4** | signal disagrees with the **always-in** direction | core §4 | SKIP unless a trend-line break has happened |
| **R5** | **first** countertrend attempt | core §5 — the market tries things twice | SKIP; require a second entry (H2/L2) |
| **R6** | countertrend signal during the **spike** phase | 01 §B | SKIP — pullback trades do not work in spikes; allow in the channel phase |
| **R7** | signal after a **3-push wedge** with a trend-channel-line overshoot | 03-reversals | TAKE — Brooks' canonical reversal |
| **R8** | signal at a **magnet** (prior swing, measured-move target, MA, breakout point) | core §7 | context only — magnets are not reasons by themselves |
| **R9** | **a good-looking countertrend signal bar inside a strong trend** | core §9, 01 §A | SKIP — treat bar quality as a TRAP flag, not a positive |
| **R10** | Brooks' **two-reasons** rule: require ≥2 independent accepts | core §6 | TAKE only when two rules agree |

**R9 is the formal version of what Tejas noticed by eye.** Brooks: *"In strong
trends, with-trend signal bars often look bad and countertrend ones look good,
and that is exactly how traders get trapped."* His skip example had the **higher**
strength value. So in a strong-trend context, signal strength should enter with a
**negative** sign. That is a sharp, falsifiable prediction, and it is the single
most interesting thing to test in this phase.

Report for every rule: **dEV per trade AND profit per week** — both, always
(DECISION_DOCUMENT trap #10: four regime filters raised EV/trade and every one of
them lost on profit/week). Matched null, paired weekly block bootstrap, stability
by year, and the count of trades each rule removes.

Also report each rule **standalone and marginal** — a rule that only repeats R1
is not a second reason, and R10 depends on the rules being genuinely independent.

### Phase 2 RESULT — run 2026-09-16. One rule survives, one is falsified.

`rules_test.py` on 113,803 filled, premium-matched (2-20) events over 142 weeks.
EV is a fixed take-profit at T with total loss otherwise, minus the measured
8.26% round-trip option cost. Significance is a PAIRED bootstrap over weekly
blocks. Base rates: 8.72% at 10x, 3.84% at 25x.

| rule | keep | hit25 vs 3.84% | dEV(25x) | profit/wk | P(dEV<=0) |
|---|---|---|---|---|---|
| **R4 agrees with 4h always-in** | 25.5% | **5.94%** | **+0.520** | **+185** | **0.000** |
| R4x agrees on 1h+4h+1d | 7.3% | 7.03% | +0.782 | +140 | 0.004 |
| R4d agrees with 1d always-in | 26.5% | 5.18% | +0.333 | +148 | 0.014 |
| R2 favourable range extreme | 17.7% | 5.07% | +0.305 | +126 | 0.004 |
| R10 R4 AND R1 (two reasons) | 5.7% | 6.29% | +0.597 | +123 | 0.004 |
| eff low (range context) | 73.9% | 4.16% | +0.081 | +75 | 0.001 |
| R1 opposing trend line broken | 18.9% | 4.32% | +0.103 | +97 | 0.252 |
| R7 channel line overshoot | 15.2% | 3.76% | -0.024 | +85 | 0.590 |
| R6 not in a spike bar | 94.0% | 3.83% | -0.003 | +4 | 0.595 |
| **R2b Brooks fade at extreme** | 32.0% | **2.45%** | **-0.345** | **-19** | **1.000** |

### The direction control — the one that decides it

Phase 1 warned that always-in agreement looked like directional beta, being
perfectly mirrored between calls and puts. So each rule was re-measured inside
**joint buckets of realised forward spot return x option type** — conditioning on
a future quantity, which is illegitimate for trading and exactly right as a
control. If a rule were only reading direction, its lift must collapse to 1.0x.

| rule | cells | median lift | cells > 1.0 | verdict |
|---|---|---|---|---|
| **R4 always-in agreement** | 10 | **1.91x** | **9/10** | **SURVIVES** |
| R2 favourable extreme | 10 | 1.42x | 7/10 | partial |
| R1 trend line broken | 10 | 1.08x | 6/10 | **does not survive** |

**R4 nearly doubles the 25x rate with realised direction AND option type held
fixed.** It is not beta. The always-in read carries information beyond which way
the market subsequently went.

### Three findings worth keeping

**1. Brooks' "single most important rule" does not hold here.** R1 — do not trade
against a trend until the channel is broken — is not significant raw (P=0.252)
and collapses to 1.08x under control. Tested properly, it is not established on
this data. Reported as a negative, not buried.

**2. Brooks' fade-the-range-extreme rule is FALSIFIED, and its inverse works.**
R2b (buy calls low in the range, puts high — the classic fade) returns
**dEV -0.345 with P(dEV<=0) = 1.000** and is the only rule with negative profit
per week. The inverse — calls near the range HIGH, puts near the LOW — is
positive (+0.305, P=0.004). This is momentum, not mean reversion.

*This contradicts the reading of the ETH example that motivated the plan.* That
trade paid 1:20, and the aggregate over 113,803 events says the pattern loses.
One good instance does not make a rule; separating those two is what this phase
is for.

**3. Trap #10 fired again, exactly as the decision document predicts.** R4x
(agreement on all three timeframes) has the best dEV per trade at **+0.782** but
keeps only 7.3% of events, giving **+140/week**. Plain R4 has a lower dEV
(+0.520) and a higher **+185/week**. Same for R10: better per trade, worse per
week. **The best rule per trade is not the best rule.** Had only dEV been
reported, the wrong one would have been adopted.

### R4 — full control CLOSED 2026-09-16, it survives

`r4_control.py`. R4 re-measured inside joint cells of **option type x realised
forward return x OTM distance x time-to-expiry**:

| target | cells | median lift | above 1.0 | p25 | p75 |
|---|---|---|---|---|---|
| 25x | 38 | **1.92x** | **31/38** | 1.32x | 3.16x |
| 10x | 40 | **1.52x** | **35/40** | 1.21x | 2.28x |

The lift is **unchanged** from the direction-only control (1.91x -> 1.92x), which
is the strongest available evidence that the extra controls absorb nothing. R4 is
not a moneyness proxy and not a tte proxy.

The residual confounds also run the WRONG way for it. Agreeing events sit closer
to the money (OTM 6.4% vs 9.4%) and have less time (tte 36h vs 47h) — both of
which make a 25x HARDER, not easier. R4 wins despite them.

**A bug was found closing this control.** `moneyness_pct` was 100% NaN in
`events.parquet`: `build_events.py` used the same `.json` filter on spot candle
files, which are named by date with no extension, so `load_spot` returned nothing
and every `spot_at_entry` was silently NaN. Fixed, and both columns were patched
onto the existing tables rather than rebuilding 1.66M rows. Phases 1 and 2 are
unaffected — they never read moneyness, and the context features came from
`brooks_context.py`, whose loader was already fixed.

### Timeframe hierarchy — "does the higher timeframe dominate?" No. Confluence does.

Tejas's hypothesis: a failing signal means a higher-timeframe structure is
holding against it. Measured directly.

**Which single timeframe's always-in read is most informative?**

| timeframe | keep | hit25 on / off | lift |
|---|---|---|---|
| 1h | 25.6% | 5.18% / 3.38% | 1.53x |
| **4h** | 25.5% | **5.94% / 3.13%** | **1.90x** |
| 1d | 26.5% | 5.18% / 3.36% | 1.54x |

**Not monotonic in timeframe — the MIDDLE one wins.** Higher is not better.

**When the 1h and 1d reads conflict (34.7% of events), whose side pays?**

| state | n | hit25 |
|---|---|---|
| both agree | 9,877 | **6.68%** |
| 1d agrees, 1h does not | 20,311 | 4.46% |
| 1h agrees, 1d does not | 19,213 | 4.41% |
| neither agrees | 64,402 | **3.05%** |

**In conflict it is a coin flip — 4.46% vs 4.41%.** The higher timeframe does not
win. The hypothesis is not supported.

What matters is **alignment, not hierarchy**: both-agree beats neither-agree by
**2.19x**. So when a signal fails it is not that a higher timeframe was holding
against it — it is that the timeframes disagreed, and disagreement is genuinely
uninformative about direction. That is a more useful rule than the original
intuition, and it is why R4x (all three timeframes) had the best dEV per trade.

### Phase 3 RESULT — run 2026-09-16. The model LOSES to the rule. Ship the rule.

`phase3_model.py`. LightGBM on the 168 context features plus tte, OTM, premium
ratio, type and signal strength. Purged walk-forward on weekly blocks: a training
event whose option is still alive when the test block opens is DROPPED, not
merely embargoed. 4 folds.

| arm | features | EV/trade (25x) | profit/wk | beats R4 |
|---|---|---|---|---|
| unfiltered signals | — | **-0.150** | -126 | — |
| **R4 alone (one line)** | 1 | **+0.414** | **+78.8** | — |
| 7-feature model | 7 | +0.504 | +104.1 | **1/4 folds** |
| full model | 175 | +0.117 | +21.8 | **1/4 folds** |

Model AUC 0.573 (25x) / 0.588 (10x) — weakly predictive, not enough.

**Verdict by the kill criterion: the model does not beat the rule out-of-sample,
so the rule ships and the model does not.** The 7-feature variant has the better
MEAN, but wins only 1 of 4 folds — the same "one fold drives the mean" pattern
that was correctly rejected in the neural-network round-2 work. A mean that good
folds disagree with is not an edge.

### Three things Phase 3 established

**1. The unfiltered signals LOSE money. R4 is what makes them tradeable.**
EV per trade goes **-0.150 -> +0.414** and profit per week **-126 -> +79**. This is
the clearest economic statement the project has produced about these signals: on
their own they are negative after the measured 8.26% round trip; filtered by one
line of context they are positive.

**2. More features made it dramatically WORSE — 175 features gave +0.117, 7 gave
+0.504.** Dropping 168 features quadrupled EV. At 142 independent weeks the data
cannot support 175 parameters, and `agree4` — the one feature that works — ranks
**29th of 175** by split count (47 splits against 246 for the top). The model
buries the signal among 174 distractors. Same data-starvation story as every
other arm in this project.

**3. Signal strength adds nothing, confirming Tejas's instinct to drop it.**
With strength: AUC 0.5732, EV +0.117. Without: AUC 0.5732, EV +0.158. Identical.
The tuning parameters and strength values can go, as he asked, at zero measured
cost — the signal STRUCTURE defines the event and CONTEXT does the grading.

### Follow-ups from Tejas, 2026-09-16 — `r9_and_tolerance.py`

**A. Overshoot tolerance — the correction is REAL, and it moves R1 but not over the line.**

Brooks: everything overshoots or undershoots by a few ticks, so a break must not
be declared on an exact touch. Phase 2 tested `close < trendline`, a hard binary
on a 1-tick penetration — exactly the brittleness he warns about. Re-tested by
requiring the break to exceed the line by X ATR:

| tolerance | keep | hit25 | dEV(25x) | P(dEV<=0) |
|---|---|---|---|---|
| 0.0 ATR (Phase 2) | 18.9% | 4.32% | +0.103 | 0.252 |
| 0.25 ATR | 15.6% | 4.47% | +0.138 | 0.231 |
| 0.5 ATR | 12.8% | 4.53% | +0.150 | 0.252 |
| **1.0 ATR** | 8.4% | **4.97%** | **+0.269** | **0.095** |

**Monotone in the tolerance** — hit rate and dEV both rise at every step. That
monotonicity is itself a genuine-signal signature (the same shape that made the
futures classifier credible). So the hard-binary break WAS diluting R1, and
Tejas's correction is measurable.

It still does not clear significance: P=0.095 at best, and at 1 ATR it keeps only
8.4% of events for +110/week against R4's +185. **Verdict: upgraded from "nothing"
to "suggestive, not established."** Any future break test must carry a tolerance.

**B. R9, the trap rule — FALSIFIED, and redundant anyway.**

Brooks predicts a countertrend signal in a strong trend with HIGH strength is the
worst cell. Measured (strength ranked within each signal, since raw values run
15..800,000 for red_squeeze against 1,000+ for the OTM signals):

| context | weak half | strong | top 10% |
|---|---|---|---|
| countertrend + strong trend | 2.48% | 2.82% | **3.34%** |
| with-trend + strong trend | 5.84% | 5.51% | **4.35%** |

**Strength rises with hit rate in exactly the cell Brooks says it is a trap**, and
falls in the with-trend cell. The predicted sign is inverted.

And it is redundant: `R4 AND not-trap` is **identical to R4 alone** — same 25.5%
kept, same dEV +0.520. The trap cell sits entirely inside what R4 already
rejects, so R9 adds nothing on top.

Tejas's original observation still holds as an observation: countertrend-in-a-
strong-trend *is* below base rate (2.5-3.3% against 3.84%). But that is R4 doing
the work, not the strength value.

**C. "Some structure is only clear retrospectively" — untested, not refuted.**

Tejas's point: a channel line cannot be predicted before it forms, but once
formed it projects forward targets. Proxied here by the R^2 of the swing-point
fit — a tight fit meaning a line the market respects:

| | Q1 loose | Q2 | Q3 | Q4 tight |
|---|---|---|---|---|
| agrees with always-in | 6.62% | 7.65% | 3.58% | 5.73% |
| disagrees | 2.59% | 4.34% | 2.24% | 3.27% |

**Non-monotone and noisy — no relationship.** But R^2 of a 4-swing regression is a
weak proxy for what Brooks means, which is *touches and rejections*, not goodness
of fit. A proper test needs a touch-count feature that does not exist yet. **Record
this as untested, not as refuted.**

### ALL RULES BUILT AND TESTED — `brooks_context2.py` + `rules_all.py`, 2026-09-16

Tejas asked for the complete set. **30 rules extracted from `Brooks/*.md` and
tested** — the 29 below plus R9 (tested separately, falsified). 105 new
structural features were built to support them: leg counting (H1/H2/L1/L2),
tight trading ranges, micro channels and micro gaps, breakout strength/weakness,
exhaustion bars and climax counts, three-push and wedge shapes, tests of a prior
extreme, stairs and shrinking stairs, final flags, measured-move distance and
pullback depth. Total context features: **273**.

**Excluded as unbuildable from this data, rather than faked:** intrabar
behaviour ("while forming the bar stays near its high" — needs ticks), all
volume rules (spot candles carry volume = null, and Brooks rates volume
unreliable anyway), and session/day-type rules (crypto is 24/7, so "trend from
the open" and the 11am trap have no meaning).

### The result, in one line: nothing adds to R4.

| | standalone dEV | P | **marginal to R4** | **P** |
|---|---|---|---|---|
| R4 always-in agrees (4h) | **+0.515** | **0.000** | — | — |
| R4x agrees on 1h+4h+1d | +0.788 | 0.004 | +0.272 | 0.145 |
| DJ many dojis (choppy) | +0.328 | 0.019 | +0.167 | 0.326 |
| R2 favourable range extreme | +0.316 | 0.004 | +0.040 | 0.383 |
| CA closes above many prior | +0.282 | 0.001 | +0.018 | 0.411 |
| R1 trend line broken (1 ATR) | +0.260 | 0.086 | -0.107 | 0.637 |
| TE testing prior extreme | +0.197 | 0.011 | -0.024 | 0.565 |
| RG range context (low eff) | +0.078 | 0.001 | +0.041 | 0.324 |
| SS shrinking stairs | +0.124 | 0.209 | **+0.390** | 0.184 |
| BB big bar vs average | +0.087 | 0.170 | +0.203 | 0.204 |
| **R2b Brooks fade at extreme** | **-0.340** | **1.000** | — | — |
| **TR trend context (high eff)** | **-0.226** | **0.998** | -0.106 | 0.696 |

(19 further rules — second entry, breakouts, micro gaps, follow-through,
exhaustion, climaxes, three-push, wedges, final flags, micro channels, channel
overshoot, pullback depth, measured moves — all non-significant standalone.)

**Seven rules are significant standalone. ZERO are significant marginal to R4.**
The best marginal P-value across all 29 is **0.145**. Every standalone winner is
a re-expression of the same underlying fact: they look informative alone and add
nothing once R4 is applied.

Worse, several go materially NEGATIVE when stacked on R4 — breakout-in-our-
direction (-0.254), three-push (-0.228), follow-through (-0.225), wedge (-0.318).
Adding them to R4 actively hurts.

### Two honest caveats on this sweep

**TTR was not really tested.** "Tight trading range trumps everything" is one of
Brooks' strongest claims, but the feature as calibrated (< 2.5 ATR over 20 bars)
fires on only 0.3% of bars, so the rule keeps 99.7% and tests nothing. His
heuristic is "range <= 25% of average DAILY range", which does not translate
cleanly to an ATR multiple on a 4h chart. **Re-calibrate before concluding
anything about TTR.**

**Thin cells.** Strong breakout (3.8% kept), exhaustion (3.6%), consecutive
climaxes (2.4%) and measured-move proximity (5.8%) ran, but on few events. Absence
of significance there is weak evidence, not a refutation.

### What this settles

The context study is complete. **R4 is not the best of several rules — it is the
only one.** Brooks' framework contains a great deal that is true about markets and
almost none of it survives as an incremental, tradeable filter on top of a single
always-in check, on this data, at this sample size.

That is a deflationary result and it is the honest one. It also means the
deliverable is simpler than hoped: one line, not a checklist.
### Culmination vs accumulation — Tejas's idea, tested 2026-09-16 (`culmination.py`)

His framing, not from the books: *"some bars are price-action CULMINATION bars;
most are ACCUMULATION bars"* — and in a rejection off a range high the BAR is the
active thing, whereas in a pullback the bar is passive and the TREND is active.

**He was right that nothing encoded this.** Every label in
`build_price_action.py` is a flat presence flag, so a rejection off an extreme
and a lazy pullback were weighted identically. Now built:

- **culmination** — rejection at an N-bar extreme (poked through, closed back
  inside), failed breakout, exhaustion bar, or a large reversal bar against the
  prior three. Scored in the SIGNAL's direction: a rejection off a HIGH is
  culmination for a put, not a call.
- **accumulation** — small relative to ATR, heavy overlap with the prior bar,
  inside bar.

**Result: not supported, and mildly inverted.**

| band | n | hit25 |
|---|---|---|
| accumulation | 39,076 | 3.79% |
| neither | 63,854 | 3.96% |
| **culmination** | 10,871 | **3.32%** |

Standalone dEV **-0.133** (P=0.866); marginal to R4, -0.182 (P=0.648).

**The fairer re-test, matching his ETH example exactly.** The first test measured
the rejection and the range on the same timeframe. His case was cross-timeframe —
rangebound on the 4h, rejection off that range on the 1h. Rebuilt that way:

| | n | hit25 |
|---|---|---|
| no rejection | 111,797 | 3.88% |
| **1h rejection of a 4h range extreme** | 2,006 | **1.96%** |

dEV **-0.476**, 95% CI [-0.729, -0.193], **P(dEV<=0) = 0.990.** Significantly
NEGATIVE — it is less than half the base rate.

### Why, and it ties the whole study together

Only **6 events** survive when this is intersected with R4. The two are nearly
mutually exclusive **by construction**: a rejection off a range extreme is
countertrend, and R4 requires agreement with the trend. They are opposite
strategies, and they cannot both be right.

Three independent measurements now say the same thing:

| test | result |
|---|---|
| R2b Brooks fade at extreme | dEV -0.345, P=1.000 |
| R2 momentum at extreme (the inverse) | dEV +0.305, P=0.004 |
| cross-TF rejection of a range extreme | dEV -0.476, P=0.990 |

**Fading extremes loses on this data; going with the move pays.** The ETH trade
that motivated this whole plan paid 1:20 and remains a real trade, but its
pattern is measurably one of the worst cells available.

### Limits worth stating

"Culmination" as Brooks reads it uses context a four-feature OHLC proxy cannot
see. This measures that *these specific geometries* do not pay — not that the
concept is empty. And the cross-TF rejection fires on only 1.76% of signals, so
per-week support is thin even across 142 weeks.

### Significance vs regular — Tejas's refined idea, tested 2026-09-17 (`significance.py`)

His correction to the culmination test: significance is not a structural question
but an ENERGY one. *"3-4 strong trend bars after a pullback are continuation
structurally, but still significant — each would give multibagger ratios."*

**This was the only idea tested that is not about direction.** Every one of the 30
rules answers "which way?"; this answers "how much?", and a multibagger needs
both. Genuinely orthogonal, so worth running despite the run of negatives.

Built at **each signal's own timeframe**, as he asked. Spot is fetched at 8
durations but signals fire on 12, so the six missing ones come from
`export_spot_tf.js` using the project's own `grouper.groupCandles` — verified
lossless against the stored series (8,463 shared bars, **0 differing**).
Undirected, by his choice. Eleven components across energy, urgency, expansion
and travel; z-scored within each (spot, duration) series; global quintiles.

**Result: inverted, monotone, and significantly so.**

| quintile | n | hit25 | hit10 |
|---|---|---|---|
| Q1 quiet | 22,761 | **4.02%** | 8.83% |
| Q2 | 22,760 | 4.14% | 9.14% |
| Q3 | 22,762 | 3.78% | 8.75% |
| Q4 | 22,759 | 3.81% | 8.63% |
| **Q5 loud** | 22,761 | **3.47%** | 8.27% |

Top quintile standalone: dEV **-0.094**, P(dEV<=0) = **0.956**. And it holds
across timeframes — Q5 beats Q1 on only **1 of 8** durations.

### The mechanism, identified

Not noise. Premium was controlled in ABSOLUTE terms (2-20) but not in volatility
terms, and that is the whole story:

| quintile | median OTM | median tte | median premium | hit25 |
|---|---|---|---|---|
| Q1 quiet | **7.12%** | 37.3h | 5.22 | 4.00% |
| Q5 loud | **9.72%** | 49.5h | 5.85 | 3.64% |

**Same ~$5, and a loud market buys you a strike 36% further out of the money.**
The extra time (49.5h vs 37.3h) does not compensate. This is the volatility risk
premium in concrete form: buying when the market is already moving means paying
up for movement that is already in the price.

Volatility clustering is real — loud moments really are followed by bigger moves.
It is simply already priced, which is why the raw effect is negative rather than
absent.

### The inverse is real but still does not beat R4

| | keep | hit25 | dEV | profit/wk | P |
|---|---|---|---|---|---|
| quiet half [standalone] | 40.0% | 4.08% | +0.057 | +80 | **0.041** |
| quiet half [marginal to R4] | 41.8% | 6.30% | +0.088 | -38 | 0.156 |
| quietest quintile [marginal to R4] | 21.2% | 6.53% | +0.145 | -56 | 0.170 |
| **R4 alone** | 25.5% | 5.94% | +0.520 | **+185** | 0.000 |
| R4 AND quiet half | 10.6% | 6.30% | **+0.603** | **+144** | 0.000 |

Buying into quiet markets is weakly real on its own (P=0.041) but **does not add
significantly to R4** (P=0.156). And `R4 AND quiet` is trap #10 again: better dEV
per trade (+0.603 vs +0.520), **worse profit per week** (+144 vs +185), because
it halves the trade count.

**Running total: 33 things tested, R4 is still the only one.**
### R5 — the 20-day regime filter ADDS to R4 (2026-09-17). First thing in 34 that does.

Tejas asked whether always-in is just the regime detection that underperformed
earlier. It is not, and the answer produced a second rule.

**They differ on three axes.** Always-in is a **4-HOUR** read used as a
**direction match** (calls when up, puts when down). The earlier regime work was a
**20-DAY** label used as a **pooled veto** (skip deep-OTM in clean uptrends,
regardless of type).

**The timescale is essential, not incidental.** Direction-matching at 20 days,
same logic as R4, on the same events:

| formulation | keep | hit25 | dEV | P |
|---|---|---|---|---|
| direction-match at 20 DAYS | 8.8% | 3.17% | **-0.166** | 0.799 |
| **direction-match at 4 HOURS (R4)** | 25.5% | **5.94%** | **+0.520** | 0.000 |

The identical rule at the slower timescale **fails**. They agree on 76% of events;
the disagreeing quarter does all the work.

**But the old regime finding was right, and it is orthogonal.** Split by option
type — which the pooled rule never did:

| 20d trend | calls | puts |
|---|---|---|
| down | 1.11% | 4.76% |
| **sideways** | **4.44%** | **4.62%** |
| up | 2.23% | 1.25% |

Sideways is the best regime for BOTH types. A clean daily uptrend is bad for
everything — grinding moves and falling realised vol are poison for deep-OTM
buying whichever side you are on. That is a different mechanism from direction,
so it stacks.

**R5 = R4 AND the 20-day trend is not a clean uptrend.**

| | keep | hit25 | dEV | profit/wk | P |
|---|---|---|---|---|---|
| R4 alone | 25.5% | 5.94% | +0.520 | +184.9 | 0.000 |
| skip-20d-up, MARGINAL to R4 | 86.3% | 6.55% | **+0.150** | — | **0.001** |
| **R4 AND not-20d-up** | 22.0% | **6.55%** | **+0.668** | **+200.8** | 0.000 |

**It improves profit per week as well as per trade** (+200.8 vs +184.9) — the
first combination to escape trap #10, because it only discards 14% of R4's events
rather than half of them.

The four cells show why: R4 in a clean daily uptrend collapses to **2.09%**, worse
than base. Everywhere else it holds at 5.6-6.7%.

| | 20d down | sideways | 20d up |
|---|---|---|---|
| R4 agrees | 5.59% | **6.66%** | **2.09%** |
| R4 disagrees | 1.37% | 3.75% | 1.44% |

**Checks:** beats R4 in all three years (7.96 vs 6.95 / 5.26 vs 5.24 / 6.19 vs
5.41), and under the joint type x realised-direction x OTM x tte control the lift
is **2.45x median, 7/7 cells above 1.0**.

**Caveats, stated because they matter:** 2025 shows essentially no gain
(5.26 vs 5.24), and the control has only **7 cells** — inside R4 the sample is
small enough that most cells are too thin to read. Weaker evidence than R4's
38 cells. Treat R5 as promising rather than established.
### Structural trend lines, R1 re-test, and sustainability (2026-09-17)

**Tooling: KEEP. Rule: DROP.** Two separate verdicts.

#### The old trend lines were wrong, not merely weak

`brooks_context.py` least-squares-fits the last 4 fractal swings. On ETH daily at
the July 2026 breakout that gave a **bear line with slope +0.101 spanning 30
days** — a rising line labelled as falling. The real 372-day descending line from
the 2025 highs was invisible, and `bear_broken` fired spuriously in July and
August when no structural line had broken.

`structural_lines.py` replaces it. Three things had to be right:

1. **Convex hull, not least squares.** Brooks draws a line TOUCHING highs with
   price below it. A regression cuts through price and is "broken" constantly.
2. **Longest segment, not the most recent.** The hull's last segment is by
   construction the newest pair — after a breakout a 20-30 bar local line, the
   same myopia as before.
3. **Slope-sign constraint.** Without it the longest segment on a long window is
   often the RISING run into the all-time high; ETH weekly gave a "bear line"
   with slope +0.108.

Plus major swings only: a 2k+1 fractal window with an ATR prominence floor.

Validated against Tejas's chart. ETH **daily**: slope -0.029, span 372 bars,
dist -3.06 -> **-0.025 on 07-06 (touch)** -> **+0.056 on 07-10 (break)** -> +3.0.
ETH **weekly**: slope -0.045, span 66 weeks, 3 touches, breaking 2026-08-17 —
about five weeks after the daily, which is why the weekly reads cleaner.

**Weekly spot had to be built by hand.** `grouper.sourceFor(10080)` returns 1440,
so weekly grouping LOOKS supported. It is not: asking for 10080 returned 991 bars
at DAILY spacing with 7 different week offsets. `getKeyDuration` recomputes its
17:30 IST anchor per calendar day, so `floor(diffMins/10080)` is 0 for almost
every candle and each day becomes its own bucket. **Any duration above one day
silently degenerates into daily.** Built explicitly instead, anchored Monday
00:00 UTC = Monday 05:30 IST: matches Delta's own chart, and one weekly is
exactly seven dailies.

#### R1 re-tested properly — the original verdict holds

I suspected the earlier R1 negative was a measurement failure. It was not.

| line | rule | dEV | P |
|---|---|---|---|
| daily structural | break, tol 0-1 ATR | -0.03 to -0.05 | ~0.70 |
| daily structural | broke within 10 bars | +0.318 | **0.158** |
| weekly structural | broke within 2 bars | **-0.400** | **0.991** |

Not significant on daily at any tolerance or window; **significantly harmful** on
weekly. By the time a weekly structural line has broken, the move is priced.

*Note:* the first weekly run used `broken` as a persistent STATE, which is
confounded with R5 (price above a broken bear line = an uptrend). The numbers
above are the break as an EVENT, which is what Brooks means.

#### Sustainability — informative, NOT actionable. A correction.

Tejas's idea: after the initial move, what matters is whether it sustains.

**The signal is real.** Drawdown at bar 6 forecasts remaining upside, monotonically:

| gave back by bar 6 | n | 25x STILL to come |
|---|---|---|
| < 0.5 (collapsed) | 44,697 | 2.55% |
| 0.85-0.95 | 7,472 | **6.41%** |

**The action is wrong, and I reported it backwards first.** I compared sustained
vs faded on their REMAINING peak — a conditional statement, not a strategy. The
strategy test is hold-vs-cut on the SAME events:

| | hit 25x | EV | profit/wk |
|---|---|---|---|
| R4+R5, hold blindly | **6.83%** | **+0.625** | **+87.2** |
| R4+R5, cut at bar 6 if faded | 3.18% | -0.287 | -40.1 |

dEV of cutting: -0.507 / -0.835 / -0.896 on everything / R4 / R4+R5, **P(<=0) =
1.000** in all three. Every threshold loses (>50%: -1.12pp, >70%: -0.45pp,
>90%: -0.08pp).

**Why:** faders are 72.3% of events but **60.6% of all 25x outcomes** — 3.35% of
them reach 25x anyway. Cutting saves a premium already down 30%+ and forfeits a
convex tail worth more. The same lesson as "small profit targets have negative
expectancy", arriving from the exit side.

#### The two rules DO stack

| | keep | hit25 | EV | profit/wk |
|---|---|---|---|---|
| everything | 100% | 4.03% | -0.076 | -48.0 |
| **R4** | 25.3% | 6.26% | +0.482 | +77.6 |
| **R4 + R5** | 21.9% | **6.83%** | **+0.625** | **+87.2** |

R4 vs everything dEV **+0.550** (P=0.000); R5 marginal to R4 **+0.140**
(P=0.004). Both add on EV **and** profit per week. Then **hold to expiry.**
### CONTAINMENT — Tejas's squeeze rule. The first pattern SHAPE feature to survive.

Proposed and implemented 2026-09-17 for `red_squeeze` and `otm_red_squeeze`:

> the green trigger must close **and** top out below the first (largest) red candle

Both tests are required. Close alone lets a long upper wick through; high alone
lets a bar that closed strongly through. Rationale, in his words and confirmed by
the data: a green that pokes above the first red's high has already retraced the
whole squeeze, so the compression the pattern is built on is gone — what remains
is an ordinary bounce, not a coiled one.

**Selectivity:** of 5,455 green triggers after a >=3-red squeeze, 71.3% are
contained and **28.7% rejected**.

**Direct A/B**, same expiries, same candles, split only by containment:

| | n | hit 25x | hit 10x |
|---|---|---|---|
| **contained** | 3,548 | **4.34%** | 9.61% |
| **rejected** | 551 | **2.00%** | 4.90% |

**2.17x on the 25x rate.** Block-bootstrapped on 141 weekly blocks:
**+2.31pp, 90% CI [0.59, 3.95], P(<=0) = 0.014.**

**Why this matters beyond the rule.** Every pattern-shape feature tested before
came back inert — `ratio1`, `ratio2`, `seqLength`, `equalSteps`, and ~140
mechanical encodings in the discovery arm. HANDOFF sec 2.1's verdict was that
shape carries nothing. **Containment is the first exception.** It is a
RELATIONAL feature (this candle versus that one) rather than a magnitude feature
(how big is this body), which is the distinction the earlier work never tested.

**Aggregate effect is modest and should not be oversold.** After regenerating
full history:

| signal | events | | hit25 | |
|---|---|---|---|---|
| red_squeeze | 40,806 -> **32,504** (-20.3%) | | 3.52% -> **3.59%** | |
| otm_red_squeeze | 40,552 -> **32,751** (-19.2%) | | 3.93% -> **4.05%** | |
| green_stairs | 18,219 -> 18,219 | | 4.05% -> 4.05% | *control, untouched* |
| otm_wall | 15,819 -> 15,819 | | 2.58% -> 2.58% | *control, untouched* |

It removes ~20% of events that hit at half the rate, but they are only 20%, so
the pooled base rate moves +2-3% relative. A real filter on a small slice: fewer
trades at better quality, not a transformed hit rate.

**Method note.** The two untouched signals came back byte-identical, which is
what validates the comparison — and is why the `--signal` flag on `backfill.js`
was worth adding. A first pass compared row-level old numbers against an
event-level calculation and appeared to show red_squeeze jumping 1.54% -> 3.93%.
That was an artifact; the controls caught it.
### THE SYNTHESIS — states pay, events do not (2026-09-17)

Sorting every result by WHAT KIND OF THING was measured produces the clearest
pattern in the project.

**Works — a state is INTACT or ALIGNED**

| | effect |
|---|---|
| always-in agreement (R4) | dEV +0.550 |
| not a clean 20-day uptrend (R5) | +0.140 marginal |
| containment — the squeeze NOT yet undone | 2.17x, P=0.014 |
| price AT an unbroken structural line | 13.29% vs 3.89% base |

**Fails — an event has ALREADY HAPPENED**

breakout in our direction (-0.254) · trend line broken (null on daily,
significantly harmful on weekly) · follow-through (-0.225) · three-push (-0.228) ·
wedge (-0.318) · exhaustion bar · consecutive climaxes · culmination bars (3.26%
vs 3.84%) · high energy (inverted, monotone) · fade at extreme (-0.345) · delayed
entry (15/15 negative) · cutting faders (48/48 negative)

**Ten event features fail. Four state features work.**

**The mechanism is measured, not assumed.** In a loud market the same ~$5 premium
buys a strike **36% further out of the money** (OTM 7.12% -> 9.72%). By the time
a chart event is visible it is in the option price. **You are paid for potential
energy, not kinetic energy.**

This reframes several separate results as one:
- Containment worked where ~140 shape features failed because it is the only one
  measuring INTACTNESS rather than magnitude.
- Sustainability forecasts but cannot be acted on, because every action converts
  a state into an event — cutting and delayed entry both destroy value.
- Energy is inverted for the same reason.
- Brooks' framework is largely event-based, which is why 29 of 30 rules failed.

**FALSIFIABLE TEST, RUN.** The pattern predicts that a state which has PERSISTED
longer is more priced and should pay less. Confirmed on 2 of 3 measures:

| persisted for | 25x (all) | within R5 |
|---|---|---|
| <=2 bars | 4.32% | 7.70% |
| 20+ bars | **2.80%** | **4.81%** |

Bars since touching the MA: 4.41% -> **1.94%**, monotone. The third measure
(micro channel, 1-8 bars) went the OTHER way, which sharpens it to *fresh
alignment beats stale* rather than *newer is always better*.

**But freshness FAILS as a rule.** Standalone 7.43% vs 3.89% (P=0.002), yet
marginal to R5 every threshold is **P = 0.13-0.24** with negative profit/week,
and the direction/OTM control gives **1.07x median, 8/16 cells**. The gradient is
real and already inside R5.

**Status: explanatory, not actionable.** And the narrative was built AFTER seeing
the results, which is exactly when a story is most seductive. It earns its place
only because the prediction it generated was tested and 2 of 3 held.

**What it suggests looking for:** not more patterns — more ways to measure "this
has not happened yet". The untested candidate: the option's own premium relative
to its recent range. Has the chain repriced, or is it still asleep?

### Sustainability, fully swept — 63 cells, all negative

8 holding periods x 6 give-back thresholds for CUTTING (48 cells), plus 5 x 3 for
DELAYED ENTRY (15 cells). **Every one negative.** Best cut cell -0.075 at K=2;
delayed entry -0.117 to -1.339, all P(<=0)=1.000.

The forecast strengthens with K — at K=24 the spread is 1.84% (collapsed) vs
9.21% (never dipped), a 5x gradient — while the action gets worse. Holding from
the trigger on those same sustainers gives **10.03%**; entering at bar 24 gives
5.12%. You pay for the confirmation, and the confirmation is what you would have
been paid for.

### Structural line PROXIMITY — the strongest cell found, and undersampled

Decomposing by distance rather than broken/not-broken, on the WEEKLY line:

| position | n | 25x |
|---|---|---|
| broken, >1 ATR past | 32,615 | 2.29% |
| just broken | 5,445 | 1.86% |
| **AT the line (+-0.25 ATR)** | 1,741 | **13.29%** |
| 1-2 ATR of room | 7,953 | 7.10% |
| 2-5 ATR of room | 2,522 | 6.85% |

**3.4x base, monotone decay with distance, collapse on the break.** Line AGE does
not help (a 372-bar line broken gives 3.88%, i.e. base) and TOUCH COUNT runs the
WRONG way (2 touches 2.44% -> 4+ touches 1.45%).

**Not established.** At 2-3% kept the CIs are enormous ([-1.21,+3.35]) and the
one cell reaching P=0.049 has profit/week **-60.5**. It was also the fifth
parameterisation of the trend-line idea tried in one day, which is where false
positives come from. **The SHAPE of the gradient is the finding; the significance
is not.** Logged forward instead of sliced again.

### Strike selection within a qualifying signal — worth ~0.5pp at most

The old work found a near-perfect strike picker (within-episode AUC 0.947) and a
poor timer. R4+R5 is a timer, so combining them looked promising. It is not:
median strikes per qualifying event is **1**, and the hindsight ORACLE reaches
only 7.04% against 6.55% for taking the first. Cheapest-premium gives 6.87%.
The 0.947 was measured on EPISODES pooling many strikes, not on single firings.
## 7. Kill criteria

| gate | pass | fail |
|---|---|---|
| Phase 0 events/week | continue | too thin to claim anything; say so |
| Rule A vs unfiltered | dEV>0 and profit/week not worse, CI excludes 0 | Brooks' own most important rule does not hold here — a real finding, publish it |
| Rule B vs unfiltered | same | range-extreme fades are not special here |
| Phase 3 vs Phase 2 | model beats both rules out-of-sample | ship the rules, drop the model |
| everything vs matched null | survives | stop |

---

## 8. What gets dropped, and why that is safe

Tejas wants the tuning parameters and strength values gone. The evidence already
supports it:

- Every pattern-shape feature (`ratio1`, `ratio2`, `seqLength`, `equalSteps`) is
  **inert under permutation importance in all four signals**.
- `signalValue` for the three OTM signals is literally `spot / mean(pattern lows)`
  — i.e. cheapness — and **cheapness alone LOSES** (−0.047, hitting 25x less often
  than random).

So dropping them costs nothing that was ever measured to be worth anything. Keep
the signal's STRUCTURE (it defines the event) and let CONTEXT do the grading.

---

## Channel lines and the tail target (2026-09-18) — Tejas's four episodes

He supplied four dated crypto episodes and one sharp claim:

> "a strong indication of immediate breakout-breakdown is channel line break.
>  Trendlines breaking only break the trend, but channel line breaks are breakouts."

### The episodes are real, and real on TRADED prices

| episode | ≥100x | max | note |
|---|---:|---:|---|
| A · 19–22 Sep 25 range break | 5 | 560x | entries 21 Sep 20:10, 22 Sep 01:20 |
| B · 23 Sep–6 Oct 25 reversal | 42 | 1,088x | 100x days 25 Sep → 6 Oct |
| C · 10–11 Oct 25 bloodbath | 204 | 15,435x | **mark-price artifact**, entries pinned at the 0.100 floor |
| D · 16 Jan–6 Feb 26 bear leg | 59 | 6,652x | 10 contracts ≥100x on TRADED prices with 3M volume |

Episode C's biggest ratios are **calls entered 11 Oct 02:45** — the bounce off
the crash low, not the crash. Episode D validates on traded candles, so the
tails are genuinely tradeable and not a mark-price story.

### Two gaps his claim exposed

1. `brooks_context.py` builds only ONE channel line — the bull channel's upper
   return line — and measures only OVERSHOOT of it (R7, dEV −0.024, P=0.590).
   That is Brooks' exhaustion reading. The **bear channel's lower return line**,
   which is what his Oct 10 and Jan 30 examples are about, was never constructed
   (the bear branch at `brooks_context.py:173` fits the trend line and stops).
   Now built in `channel_lines.py` → `events_cl.parquet`.
2. Every prior result targeted **25x**; his episodes are 100x–9,000x. Added.

### Result: the distinction is real, but NOT the way he framed it

At 25x, premium 2–20, 240m context, 97,909 events, 142 weeks, base hit 3.89%,
break-even 4.33%:

| rule | keep | hit | dEV | dProfit/wk | P |
|---|---:|---:|---:|---:|---:|
| CL only (no TL) | 2.3% | 4.20% | +0.073 | +77.96 | 0.365 |
| TL only (no CL) | 13.1% | 3.90% | −0.025 | +67.66 | 0.546 |
| **CL AND TL** | 5.8% | 5.71% | **+0.447** | +92.24 | **0.025** |
| R4 alone | 25.7% | 5.96% | +0.510 | +151.52 | 0.000 |
| **R4 AND CL AND TL** | 2.4% | **9.64%** | **+1.397** | +100.46 | **0.001** |

Neither break works alone. **Only the conjunction pays** — which is exactly his
Oct 10 account: the bull trend line broke on Oct 7, and the Oct 10 17:30 bar
then broke the bear channel line. Sequence, not either event.

Survives the direction control (lift 1.90/1.66/0.79/1.15/1.53 across realised
forward-return quintiles) and survives marginality to R4 on EV (+0.887, P=0.029)
— though **inside R4 it fails profit/week (−47.97)**, trap #10 again. The usable
form is the conjunction R4 ∧ CL ∧ TL, positive on both numbers.

### Two findings that cut against it

**It decays, and is gone in 2026.** 2024 dEV +0.783 (P=0.033) · 2025 +0.440
(P=0.082) · **2026 −0.091 (P=0.593)**. Tejas's own read — markets "constantly in
trapping mode" now — matches the data. Do not trade this on 2024 evidence.

**The tail re-target found nothing.** At 100x the rules are dead: CL −0.170
(P=0.680) in the 2–20 band, and in the cheap band every rule has NEGATIVE
profit/week. The cheap band itself is where the tail lives — premium <2 hits
1.14–1.21% against a 1.083% break-even, while the 2–20 band the whole project
used is BELOW break-even at 100x (1.012%). But no price-action rule improved it.
100x events cluster ferociously: only 49 of 140 weeks contain one, and the top
10 days hold 30% of them (8 in a single Aug-2026 week).

Caveat: ~32 rule × band × target cells were examined. P=0.025 is not impressive
against that count on its own; the conjunction earns its keep by being
pre-specified from his Oct 10 description and by surviving both controls.
