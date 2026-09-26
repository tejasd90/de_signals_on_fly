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

### Full test of the channel-line claim (2026-09-18, supersedes the section above)

The first report of "CL AND TL, dEV +0.447, P=0.025" was one cell out of many,
measured before any multiplicity control, at a construction that never fired
during the episode the claim came from. The complete test changed the answer
three times; all three states are recorded because the sequence is the lesson.

**Build.** `channel_grid.py` (18 local constructions: n_swings x fractal k x
timeframe) and `structural_channels.py` (hull lines + the parallel return line,
lookbacks sized so each timeframe can hold a multi-month line). Two real bugs
were found in the structural selection and fixed: "longest sloping hull segment"
degenerated to the window edge (returned span equalled the lookback on nearly
every bar), and extrapolation was unbounded (negative prices on 18 of 72 bars at
lb400, reporting "broken" throughout).

**Control 1, placebo — insufficient.** Flipping the direction convention gave
0/896 significant vs 62/826 real (placebo min p 0.069). Decisive-looking, but the
wrong null: on a directional feature the flipped rule is an anti-rule, guaranteed
to look bad if the geometry reads direction at all — which is beta, not skill.

**Control 2, count of bootstrap-significant cells under permutation — WRONG.**
It reported family-wise p = 0.520 and "dead". The error: under within-week
permutation dEV is not centred on zero (null medians +0.098 R4, +0.184 CL&TL),
because these masks fire more in weeks when options paid anyway. Counting cells
with bootstrap p<0.05 therefore flags null cells constantly.

**Control 3, Westfall-Young maxT (`maxt.py`) — correct.** Standardising each cell
against its own permutation null: R4 positive control z=17.09 (FWER p<0.001), and
24 of 64 cells survive family-wise correction at 25x. The geometry does carry
real within-week selection.

**Variance decomposition, the number that matters.** Within-week permutation sd
0.0504; weekly block bootstrap sd 0.3334 — **6.6x**. The permutation z-scores are
large because they hold weeks fixed. Between-week variation dominates and is what
decides whether a rule repeats, which is why maxT says "real" while the block
bootstrap says P=0.060.

**Where the effect actually lives: PUTS ONLY.**

| side | keep | hit | base | dEV | dProfit/wk | P |
|---|---:|---:|---:|---:|---:|---:|
| calls | 5.4% | 3.05% | 3.79% | **-0.179** | +47.12 | 0.702 |
| puts | 6.6% | **8.18%** | 3.99% | **+1.006** | +51.68 | **0.011** |

Puts clear the direction control in all five realised-forward-return buckets
(2.23 / 1.19 / 2.48 / 2.15 / 2.14x). Calls are below 1.0 in four of five
(0.00 / 0.36 / 0.42 / 0.27 / 1.40x) — actively harmful. Downside breaks cascade
through liquidations; upside breaks get faded.

**Held-out 2026, put side:** `cz1440_s6k3` CL&TL hit 8.63% vs 2.58% base,
dEV +1.349, dProfit/wk +176.53, **P=0.043** — the only thing in this whole study
significant out of sample in the live regime.

**Caveats that stop this being a green light.** Parameter fragility is real:
`cz240_s4k2` is significant in 2024-25 (P=0.042) and dead in 2026 (P=0.303),
while `cz1440_s6k2` is the reverse. On the put-only maxT only 4 of 64 cells
survive family-wise, and `cz1440_s6k3|CL` is not among them (FWER p=0.713) even
though it wins on the bootstrap. No single construction is robustly best.

**Tejas's actual claim is NOT supported.** He argued channel-line breaks are
categorically different from trend-line breaks. Pooled across the grid, TL is at
least as strong as CL (TL 34/324 significant vs CL 13/268), and the conjunction
is not reliably better than either. What survived is not "channel lines are
special" but "downside break geometry predicts, upside break geometry does not".

### Sustain vs fade: the "absorption / overbought" claim (2026-09-18)

Tejas's Nifty pair — Dec-2023 broke a swing high after a calm stretch, gapped the
ATH and SUSTAINED nine months to 26,000; Sep-2024 made the ATH already extended
and gave it all back by April. His mechanism: the market ABSORBS opposite-side
attempts (which produces the calm) before a move that sustains, and is unstable
and won't sustain when already overbought/oversold.

**It cannot be tested on the option set**, for two measured reasons. Horizon:
his moves run months, option events resolve in days. Collinearity: a break means
price is already far from the line, so "break while NOT extended" had **n=0**.

`spot_sustain.py` tests it on its own terms — 8,252 daily 20-day breakouts across
158 Delta perpetuals, 121 weeks. Pre-state measured strictly before the event
bar; outcomes at 5/20/60 days; resampling unit is the CALENDAR WEEK across all
symbols (N_eff 5.8 makes symbol-weeks fiction). Extension quintile is nearly
collinear with direction (Q1 = 1,160 up/491 down, Q5 = 200 up/1,451 down), so
everything is run WITHIN direction.

**Half the claim fails, half survives.**

| | up breaks | down breaks |
|---|---|---|
| extension → sustain, 60d | +3.48pp, P=0.212 | **−7.06pp, P=0.974** |
| extension → return, 20d | −2.67%, P=0.637 | **−7.50%, P=0.967** |
| absorption → sustain, 60d | +0.76pp, P=0.428 | +1.23pp, P=0.350 |
| absorption → return, 20d | +4.34%, P=0.188 | +2.71%, P=0.213 |

1. **ABSORPTION IS NULL EVERYWHERE.** All P between 0.188 and 0.826, no
   consistent sign across horizon or direction. His proposed *mechanism* — that
   absorbing opposite attempts produces a calm that precedes a decisive move — is
   not supported. This also matches the earlier option-side result, where
   "call breaks, absorbed first" hit 0.12% against a 3.78% base.
2. **"OVERBOUGHT/OVERSOLD WON'T SUSTAIN" HOLDS, BUT ONLY DOWNSIDE.** Down-breaks
   made while already extended down sustain far less: 60d sustain falls
   monotonically 19.0 → 23.0 → 20.4 → 14.7 → 11.7% across extension quintiles.
3. **NOTHING ON UP BREAKS** — which is exactly where both his Nifty examples
   live. The Dec-2023-sustains vs Sep-2024-fades distinction does not reproduce.

**The reconciliation with the option result.** There, "put breaks, already
extended down" was the BEST cell (dEV +1.130, P=0.036) at option horizons of
days. Here, extended down-breaks sustain WORST at 60 days. Both are true and
together they say something usable: a crash into an already-oversold tape gives a
sharp continuation over DAYS, then mean-reverts over MONTHS. Buy the puts, do not
hold the view.

Multiplicity: 16 cells (2 vars x 2 directions x 2 horizons x 2 outcomes); two are
significant, both the same variable and direction with consistent sign across
horizons. Coherent, but ~0.5 cells would be expected by chance, so this is mild
evidence, not a result to size on.

---

## Audit of the whole session (2026-09-18) — bugs found, claims corrected

### BUG 1 (material): truncated forward windows in `spot_sustain.py`

`j=min(i+H,n-1)` silently shortened the outcome window for breakouts near each
symbol's series end. A shorter window is easier to "sustain" and damps the return,
biasing both upward. It touched **963 of 8,252 events at 60d (11.7%)**.

Consequence — the up-break baseline I quoted was wrong:

| | reported | corrected |
|---|---:|---:|
| up-break sustain 60d | 13.1% | **9.1%** |
| up-break ret60 | −5.49% | **−7.22%** |

Fixed: outcomes are NaN per horizon when the full window is unavailable, so a 20d
result is still kept when only 60d is missing. `blockboot` now drops NaN rows.

### BUG 2 (latent): `daily()` aggregated `o=first`/`c=last` without sorting

Correct only because the perp parquets happen to be ts-ordered. Hardened.

### CORRECTION 1: the spike→range→break verdict was half artifact

`spike_range_break.py` guarded its own windows correctly, so **clean** setup
events were compared against a **contaminated** baseline. Against the corrected
baseline the gap roughly halves and every P moves toward 0.5:

| | before | after |
|---|---|---|
| setup vs base, ret60 | −3.5 to −9.8%, P 0.65–0.87 | **−1.6 to −7.8%, P 0.56–0.82** |
| setup sus60 vs base | 4–9% vs 13.1% | 3.6–8.6% vs **9.1%** |

So the setup is **not clearly worse** than a generic up-break at 60 days. What
survives is the 20-day advantage: 25–31% sustain vs 21.1%.

### CORRECTION 2: the 2026 out-of-sample put result is thinner than stated

It survives dropping January 2026 (dEV +0.535, P=0.044 vs +1.349, P=0.043 full),
but **the rule fires in only 7 of 37 weeks in 2026**, and in only 5 months of 9
(none at all in Apr, Jul, Aug, Sep). That P-value rests on seven firing weeks.

### CORRECTION 3 (in the other direction): the full-period put result is robust

Leave-one-month-out never breaks it — ex Jan-2026 +0.703 (P=0.027), ex Dec-2024
+1.283 (P=0.002), ex May-2025 +0.990 (P=0.011), ex Feb-2026 +1.022 (P=0.013).
18 distinct firing months, top-3 hold 47% of hit weight. I over-stressed fragility.

### CORRECTION 4: absorption before an UP break is now clearly adverse

After the window fix, up-break absorption Q5−Q1 on ret60 moved from −5.69%
(P=0.826) to **−8.53% (P=0.920)**. Tejas's "calm before the decisive move" is not
merely null on the up side; it leans actively negative.

### UNDER-CLAIMED: the grid backtest is on TRADED prices

`fetch_eth_1m.py` pulls `symbol=ETHUSD` with **no `MARK:` prefix**, and 96.4% of
the 1.36M bars carry nonzero volume. Given the mark-price blocker that bounds most
option work here, the grid conclusions rest on firmer data than the option ones.

### NEW: the grid and the put edge are opposite sides of one trade

A grid is SHORT gamma; buying puts on downside breaks is LONG gamma. Measured
overlap between the ETH grid's daily PnL and put-rule firing days:

| grid PnL decile | grid PnL | put rule fires |
|---|---:|---:|
| 1 (worst) | −$4,633 | **24.2%** of days |
| 7–10 (best) | +$1,024 to +$5,504 | 6.3–8.5% |

The rule fires ~3x more often on the grid's worst days than its best
(correlation −0.075; −$600 avg grid day when firing vs +$590 when not). Because
the put rule is +EV standalone (dEV +1.006), it is a **positive-carry hedge for
the grid's left tail** — the ₹8 crore one-way-fall scenario — rather than
protection that costs carry. This is the one genuinely new result of the audit.

### The two-broker grid, settled by the path-length law

His opening question. Grid gross = path length x size, independent of spacing and
of how the book is split. Splitting the same size across two brokers cannot
create harvest; it duplicates the fee bill per unit of path and fragments margin
into two independent liquidation points instead of one netted one. The funding
does differ, because a long-on-A/short-on-B pair carries different net exposure
than a single netted book — so the two are not the same position, and the
comparison should be made at equal net exposure, not equal gross size.

### Consolidated hit rates, and what survives on TRADED prices (2026-09-18)

Break-even at 25x is 4.33% of premium. MARK prices, full population, 142 weeks:

| rule | keep | firing weeks | hit25 | dEV | P | hit100 | P |
|---|---:|---:|---:|---:|---:|---:|---:|
| base (every activated) | 100% | 142 | 3.89% | −0.110 | — | 1.026% | — |
| **R4** always-in | 25.7% | **142** | 5.96% | +0.510 | **0.000** | 1.799% | **0.002** |
| CL&TL | 6.0% | 70 | 5.82% | +0.478 | 0.060 | 1.647% | 0.159 |
| **CL&TL puts** | 3.2% | 36 | **8.18%** | +1.058 | **0.012** | 2.329% | 0.075 |
| R4 + CL&TL puts | 2.4% | 36 | 8.36% | +1.090 | 0.029 | 2.626% | 0.102 |
| CL&TL puts + extended down | 2.1% | 30 | **8.98%** | +1.226 | 0.029 | 3.033% | 0.062 |
| CL&TL **calls** | 2.7% | 36 | **3.05%** | −0.210 | 0.752 | 0.844% | 0.620 |

Three readings that matter more than the maximum:
- **R4 is the only rule significant at BOTH targets and the only one firing in all
  142 weeks.** Every high-percentage put rule fails at 100x (P > 0.06).
- Stacking R4 onto the put rule buys almost nothing (8.18 → 8.36%) and *worsens*
  significance (0.012 → 0.029): they read overlapping information.
- R4 splits evenly by side (puts 5.95%, calls 5.97%); CL&TL does not at all
  (8.18% vs 3.05%). On calls the break geometry is BELOW the 3.89% base rate.

**TRADED-PRICE CHECK — and the trap in it.** `fetch_traded.py` fetched only "the
contracts R4+R5 actually selects". So that subset IS the R4+R5 population, and
computing a "base rate" or re-testing R4 inside it conditions on the selection.
My first pass did exactly that and produced two artifacts: a 6.34% "base rate"
(which is really R4+R5's own hit rate on prints, consistent with the documented
6.01%) and R4 appearing to *lose* (−0.117, P=0.831) because it was being applied
twice.

What the subset legitimately tests is a marginal addition inside R4+R5:

| within R4+R5, on prints | keep | wks | hit25 | dEV | P |
|---|---:|---:|---:|---:|---:|
| R4+R5 population itself | 100% | 141 | 6.34% | +0.503 | — |
| + CL&TL, puts only | 7.2% | 36 | **8.78%** | +0.575 | **0.160** |
| + CL&TL, calls only | 3.7% | 25 | 4.55% | −0.470 | 0.767 |

**So the put refinement is NOT confirmed on traded prices.** Right sign, good
point estimate (6.34 → 8.78%), but P=0.160 on 36 firing weeks. The call side is
negative on prints too, which is at least consistent.

**Bottom line on "best percentage":** the only figure backed by prints remains
**~6.0–6.3% from R4+R5(+containment)** against a 4.33% break-even. The 8.2–9.0%
put numbers are mark-price only, rest on 30–36 firing weeks, and their traded
counterpart is unproven.

### Was 4h the right timeframe for R4? (2026-09-18)

R4's timeframe was never chosen on merit. `brooks_context.py` fixes the ladder at
60/240/1440 for a DATA reason stated in its own docstring — six of the twelve
signal durations have no stored spot series — and 4h simply won within that
ladder. 6h, 8h, 12h and weekly were never candidates. `data/spot_grouped/` does
carry all of them, so `alwaysin_tf.py` answers it. Always-in is unchanged
(`close > EMA20 > EMA50`); only the bar size varies.

| timeframe | keep | hit25 | dEV | P | hit100 | P100 |
|---|---:|---:|---:|---:|---:|---:|
| 1h | 25.6% | 5.33% | +0.354 | 0.000 | 1.557% | 0.001 |
| 2h | 25.6% | 5.27% | +0.336 | 0.000 | 1.581% | 0.003 |
| **4h (current)** | 25.7% | 5.96% | +0.510 | 0.000 | **1.799%** | **0.002** |
| 6h | 26.0% | 5.87% | +0.486 | 0.000 | 1.784% | 0.027 |
| 8h | 26.4% | 5.95% | +0.504 | 0.000 | 1.732% | 0.041 |
| **12h** | 26.6% | **6.04%** | **+0.538** | 0.000 | 1.778% | 0.033 |
| daily | 26.8% | 5.23% | +0.333 | 0.015 | 1.440% | 0.138 |
| weekly | 32.6% | **2.40%** | **−0.368** | **0.999** | 0.639% | 0.876 |

**A broad plateau from 4h to 12h with smooth degradation on both sides.** Too
fast is noise, too slow is stale. That shape — not any single P — is the evidence
the effect is real. Weekly is not merely useless but ACTIVELY HARMFUL (2.40%
against a 3.89% base), consistent with the standing note that weekly trend-line
breaks are measurably harmful.

**Answering the question directly: no, 6h/12h/daily do not improve it.** 12h edges
4h at 25x (6.04 vs 5.96%) by an amount well inside noise; 4h is better at 100x;
daily is clearly worse; weekly is harmful.

**The combination is more interesting, and still not an improvement.** Requiring
agreement on 4h AND 12h gives 6.76% vs 5.96%, dEV +0.705 vs +0.510, and at 100x
2.18% vs 1.80%. But:

- **Marginal test fails.** Inside the 4h population, adding 12h is dEV +0.196 at
  **P=0.058**, with **dProfit/wk −0.22** — literally zero added weekly profit.
- **It is less stable.** 4h alone is significant in all three years (2024 P=0.007,
  2025 P=0.002, 2026 P=0.036). 4h AND 12h loses 2026 (P=0.106).

Both survive the direction control in all five forward-return buckets, and both
work on both sides (4h: calls P=0.002, puts P=0.009).

**Verdict: keep 4h.** The combination buys no extra profit and is weaker in the
live year. The ONE reason to prefer it is trade reduction — same weekly profit
from 16.9% of events instead of 25.7%, a 34% cut in trade count. Given that
overtrading is the stated real problem, that is a genuine practical argument even
though it is not a statistical improvement.

Multiplicity: 8 timeframes + 11 combinations = 19 cells. The plateau shape is
what should be believed, not the maximum.

---

## What quant funds actually do, and the one structural thing missing here (2026-09-18)

Tejas asked how ML-driven funds make money and whether the same approach applies.

**They make money four ways, and only one resembles this project.** Market making
(the largest by volume — earns spread and rebates; the ML is defensive, predicting
the next ticks to avoid adverse selection; needs colocation). Statistical
arbitrage (rank thousands of names on weak signals, long/short, market-neutral;
per-name IC of 0.02-0.05 is normal). Execution alpha. Risk-premia harvesting.

**The thing missing here is BREADTH, not features.** IR ~ IC x sqrt(breadth).
This project predicts direction on 1-2 instruments over 142 weeks: breadth ~1. A
desk with IDENTICAL skill gets a vastly higher Sharpe by making the bet thousands
of times at once. Our 5.96%-vs-4.33% is a perfectly respectable IC; the design
around it is the problem.

**The N_eff 5.8 objection does not apply to cross-sectional trading.** Measured
on 158 perps with >=250 days:

| | mean pairwise corr | effective breadth |
|---|---:|---:|
| raw returns | 0.434 | **4.3** |
| residual (market removed) | −0.006 | **58.2** |

Market-neutralising converts 4.3 effective bets into 58.2 — a 13.5x gain, worth
sqrt(13.5) ~ 3.7x on IR for the same skill. N_eff 5.8 measured RAW returns.

### Measured (`xsec.py`): the low-volatility anomaly is present in crypto perps

IC vs forward residual return, and a dollar-neutral decile book with real costs:

| signal | IC(5d) | ann ret | Sharpe | maxDD | turnover/reb | cost/yr |
|---|---:|---:|---:|---:|---:|---:|
| vol20 (prefer low vol) | +0.107 | **55.4%** | **2.06** | −23.1% | 0.409 | 0.6% |
| illiq (prefer liquid) | +0.096 | 49.5% | 1.94 | −18.5% | 0.381 | 0.6% |
| mom60 | +0.046 | 24.8% | 1.09 | −14.7% | 0.471 | 0.7% |
| rev1 | +0.033 | 19.4% | 0.88 | −21.0% | 1.518 | 2.3% |
| carry | −0.009 | **−5.8%** | −0.37 | −48.0% | 0.495 | 0.7% |

Weekly block bootstrap on vol20, 142 weeks: **+54.8% ann [+28.6, +80.4],
P(<=0)=0.0003.** Stable by year (Sharpe 1.69 / 2.11 / 2.77). Survives equal-RISK
weighting (2.06 -> 1.73), so it is not a leverage artifact. It is NOT a size tilt
— corr(vol20 rank, log-volume rank) = +0.044. This is Frazzini-Pedersen
betting-against-beta, replicated in crypto.

`carry` coming out negative independently reproduces the funding-carry
falsification, which is a useful internal consistency check.

### Why this is not yet tradeable

- **The short leg is 137% of the total.** Long (low-vol) −20.7%/yr, short
  (high-vol) +76.6%/yr. The entire profit is shorting high-vol alts.
- **Survivorship and listing bias sit exactly on that leg.** `fetch_perps.py`
  pulls symbols LIVE on Delta today, so failed/delisted coins are absent, and
  Delta lists coins after they have already run. Both flatter a short-alts book.
- **Not actually neutral:** beta to market −0.203, correlation −0.600. Worst
  months are market melt-ups (2024-09: −11.9% while market +20.1%). Short gamma.
- **Execution:** the 0.02% maker assumption is least credible on illiquid alt
  perps, which is where all the profit is.

**Verdict:** the breadth argument is right and the effect is real and documented,
but the implementable version is far weaker than the headline. The honest next
step is a delisted-inclusive universe and a liquidity-capped, beta-hedged version
— not sizing the 55%.

---

## Steps 1-3 on the cross-sectional direction (2026-09-19)

### Step 1 — survivorship does NOT explain the perp edge

`fetch_dead.py` recovered the 22 delisted perps (median total return **-74%** over
their listed life). Two traps handled: the API serves frozen zero-volume bars at
the last price after delisting (trimmed), and PEPE/SHIB/BONK/FLOKI are RENAMES of
live 1000x contracts, not deaths (tagged, not counted as failures).

| universe | ann | Sharpe | maxDD |
|---|---:|---:|---:|
| live-only (original) | +61.6% | 2.27 | -23.1% |
| + 22 delisted | **+60.6%** | 2.24 | -27.5% |

Almost no change — the dead names are only **4.6% of gross exposure**. My main
worry was wrong. **The fix is PARTIAL though:** Delta retains only 26 expired
perps, so names delisted long ago are purged and unrecoverable. Older
survivorship cannot be ruled out.

### Step 2 — tradeability

**Beta-hedging IMPROVES it**: +58.4%, Sharpe 2.44, maxDD -27.5% -> **-18.2%**. The
residual -0.203 market beta was hurting, not flattering. Capacity degrades
gracefully with a 0.5%-of-ADV position cap: $1M book 76.3%, $20M 57.4%, $100M
47.6%. The cap *helps* at small size by excluding untradeable microcaps.

BUGFIX: the first cap clipped portfolio WEIGHTS against a DOLLAR limit, so it
never bound and the liquidity test was vacuous.

Still **119% of profit from the short leg** (long -10.6%, short +65.7%).

### Step 3 — relative value in options: FAILED

The hypothesis: this project measured AUC 0.95 for ranking contracts WITHIN an
episode against 0.57 between episodes, so a market-neutral book should use the
ranking skill and skip the timing skill.

`opt_xsec.py` computes EXACT terminal values (European, cash-settled:
`max(0, S_T-K)`), which also gives a number never measured here — buy-and-hold to
expiry: mean **+20.9%**, median **-104%**, **77.6% expire worthless**. The mean is
useless on a distribution this skewed.

Long/short within the same spot+expiry+instant+type, 32,979 groups, 141 weeks:

| ranking | spread | P(<=0) |
|---|---:|---:|
| long near-the-money, short far-OTM | **+44.2%** | 0.005 |
| long cheap premium, short rich | -6.3% | 0.586 |
| signal_value cheapness | -5.5% | 0.771 |

**The cheapness rankings do nothing** (P 0.41-0.77) — which is the actual Step 3
hypothesis, and it is refuted. The only thing that works is moneyness, which is
not our model's skill but the known structural over-pricing of far-OTM options.

**And it is untradeable anyway:**
- worst single short leg **184,517% of premium** (1,845x)
- a shorted contract returns >1000% in **1.48%** of groups, >3000% in 0.60%
- year by year: 2024 +23.2% (P=0.004), **2025 -13.7% (P=0.896)**, 2026 +156.6%

**LIMITATION:** I tested `entry_premium` and `signal_value` as cheapness proxies,
NOT the trained model's score that produced AUC 0.95. A fair test of Step 3 needs
the model's own predictions as the ranking. What is refuted is the proxy version.

**RETRACTION:** a line printed during this run asserted "the average cheap OTM
option is a loser held to expiry". The numbers in the same output contradict it —
premium 0-5 has mean held-to-expiry return **+60.6%** and premium >20 has
**-8.5%**. Both are means on a wildly skewed distribution and neither is a claim
worth making without the weekly bootstrap.

---

## Three answers (2026-09-20)

### What "spot" means in this project

`spot_store.js:14` — `getSpotSymbol(): BTC -> MARK:BTCUSD`. So **`data/spot_candles/`
is the perpetual future's MARK price**: not the underlying spot index, and not
traded prices. It carries NO volume and is the same series whose use for option
candles is the standing mark-price blocker.

Against traded perp candles (`data/perp_candles/`, plain symbol, has volume):
median difference 0.32 bp (BTC) / 0.47 bp (ETH), identical to 0.01% on 82.5% /
74.5% of hourly bars — but p99 is 281 / 22 bp and the max is **1012 bp**. They
agree in calm and diverge in stress, which is when signals fire. New spot-side
work should use `data/perp_candles/`.

### The 44 MA pullback-reversal claim: REFUTED

Setup: green candle touching the MA from above, in an uptrend (defined off the
200-day average, so it is not the line being tested). Control: green candle in
the SAME uptrend, NOT near the MA — because most MA-bounce claims are really
"buy dips in an uptrend" with the average adding nothing.

**44 is not special.** Sweeping 20/30/40/44/50/60/100/200 gives a perfectly smooth
curve of edges (−1.50, −2.11, −2.12, **−1.82**, −2.17, −2.29, −3.21, −4.27 at
10 days). Nothing distinguishes 44 from 40 or 50. A real level effect would show
a plateau, as the always-in timeframe sweep did.

**And the sign is wrong.** Market-adjusted (cross-sectional mean removed), the
setup UNDERPERFORMS its control: −0.15% at 5d (P=0.61), −0.45% at 10d (P=0.71),
**−1.46% at 20d (P=0.964)**. It worsens monotonically with MA length, which is
economically sensible: a pullback deep enough to reach the average is evidence
the trend is weakening, not that it is about to resume.

The bear version ("from below", his weaker case) is null — and the sign is wrong
there too: a useful short would fall MORE than its control, and it falls less.

### Exhaustion lows: they exist, are hugely valuable, and are not findable

Made precise: bar i qualifies if you buy THE CLOSE and never go underwater within
H bars. Candidates restricted to real down-moves (below the 50-day average and
down >10% over 20 days). 33,570 candidates, 158 symbols, 118 weeks.

**DEFINITION BUG CAUGHT MID-RUN.** The first version asked whether the bar's LOW
was revisited. A wide bar closing near its high satisfies that for free — its low
is simply far away. That made `close_pos` and `rng_atr` look strongly predictive
(base 9.9%, Q5 17.8%) while their forward returns were the WORST in the sample,
which is what exposed it.

| horizon | base rate | return if permanent | if not | best marker |
|---:|---:|---:|---:|---|
| 3d | 3.40% | +10.9% | −0.58% | +0.80pp, P=0.101 |
| 5d | 2.52% | +14.5% | −0.77% | +0.73pp, P=0.098 |
| 20d | 1.02% | **+37.5%** | −2.56% | +0.63pp, P=0.032 |
| 40d | 0.67% | **+64.9%** | −3.60% | +0.38pp, P=0.121 |

The prize is real and enormous. Nothing finds it. Volume spike −0.0pp (P=0.541),
depth below MA +0.0pp (P=0.425), drawdown-so-far +0.4pp (P=0.165). The best is
range expansion at +0.6pp — moving 1-in-200 to 1-in-83.

**Two classic capitulation markers point the WRONG way:** long lower tail
(1.5% → 0.9%, P=0.876) and closing near the high (1.6% → 0.5%). The "hammer"
and "absorption" readings are anti-predictive here, consistent with the earlier
finding that absorption is null-to-adverse.

---

## Scaling into a pullback: the 1-2-3 ladder (2026-09-20)

Tejas's proposal: after an upmove, buy 1 unit, then 2 units at -1%, 3 at -2%, and
so on — to get size without a small pullback wiping out a levered entry.

### The arithmetic (`pyramid.py`)

After K levels the position is the triangular number N=(K+1)(K+2)/2. Liquidation
is when `capital + N*CV*(P-avg) < MM*N*CV*P`, so the capital needed to survive to
price P is exactly `C = N*CV*[avg - P*(1-MM)]`.

| pullback | levels | units held | avg entry | notional | **capital needed** | **max opening leverage** |
|---:|---:|---:|---:|---:|---:|---:|
| 8% | 9 | 45 | −5.33% | 41.4x | 1.30x | 0.77x |
| 12% | 13 | 91 | −8.00% | 80.1x | 3.84x | 0.26x |
| **16%** | **17** | **153** | **−10.67%** | **128.5x** | **8.48x** | **0.118x** |
| 20% | 21 | 231 | −13.33% | 184.8x | 15.86x | 0.063x |
| 30% | 31 | 496 | −20.00% | 347.2x | 50.47x | 0.020x |

All X columns are multiples of the FIRST lot's notional. **The ladder consumes
leverage rather than using it**: surviving 16% requires holding 8.5x the opening
lot in cash, i.e. opening at 0.118x leverage. The stated goal — size with
leverage — is unreachable by this structure.

### The empirical premise is false

Ladder fired after a >15% ten-day upmove, 60-day window:

| universe | episodes | median deepest pullback | reaches −16% | capital consumed (med / p90) |
|---|---:|---:|---:|---:|
| all 158 perps | 1,490 | **34.9%** | 81.8% | 75.5x / 241.5x |
| BTC+ETH only | 16 | **18.5%** | 56.2% | 12.8x / 101.9x |
| top-20 by volume | 91 | 24.8% | 63.7% | 29.2x / 161.3x |

Pullbacks after an upmove are not shallow. Even on the majors the MEDIAN is
18.5%, deeper than the 16% the ladder was sized for. On the full universe the
ladder returns mean −12.46x against −0.09x for simply buying one unit and
holding, with a 5th percentile of −200.72x. (Majors samples are 16–30 episodes;
their positive means are noise, not evidence.)

### The structural flaw, and the fix

A RISING ladder puts the smallest size where the thesis is most likely right
(the entry, if the trend continues) and the largest size at the worst price. It
inverts the sizing you want. Capital to survive a given depth, by shape and step:

| shape | step | 16% | 20% | 30% | 40% |
|---|---:|---:|---:|---:|---:|
| **rising (his)** | 1% | 8.5 | 15.9 | **50.5** | 116.1 |
| rising | 5% | 0.6 | 1.0 | 2.8 | 6.1 |
| flat | 2% | 0.7 | 1.1 | 2.4 | 4.2 |
| **flat** | **5%** | 0.3 | 0.5 | **1.1** | 1.8 |
| falling | 5% | 0.2 | 0.3 | 0.6 | 0.8 |

**Flat size at 5% steps survives 30% on 1.1x capital where the rising 1% ladder
needs 50.5x — a 46-fold difference for identical protection.** In practice, for
₹1L of capital on ETH, surviving 30% means opening **0.9 lots** with the rising
ladder versus **43.2 lots** flat-5%. Same capital, same protection, 48x the
opening size — which is precisely the "large quantity" the proposal wanted.

Sizing formula: `base_lots = capital / (need(D) x contract_value x P0)`.

---

## Levels rejected 3+ times, and what their breaks pay (2026-09-21)

Tejas's idea: a level the market has turned away from three or more times is one
it has repeatedly agreed on, so breaking it should be a bigger event than
breaking an undefended level — and the option expiry that breaks it should carry
the outsized multiples.

`levels.py` finds three kinds — horizontal clusters of major swings, convex-hull
trendlines, and channel lines — with a deliberately asymmetric test:
**rejection** = came within 0.6 ATR, did NOT close beyond, then travelled 1.2 ATR
away (wicks through are fine); **break** = a CLOSE beyond. A level is confirmed
only from its THIRD rejection, never retroactively, which is exactly the timing
Tejas described for the Oct-2025 line (unknowable in October, two touches by
February, confirmed by the June rejection).

### It works, and it replicates

Break days vs all other days, P(a >=100x option move starts that day):

| | break days | on | off | lift | P(<=0) | median best multiple |
|---|---:|---:|---:|---:|---:|---|
| BTC daily, >=3 rej | 119 | **32.8%** | 18.4% | 1.78x | **0.001** | 61.4x vs 34.8x |
| ETH daily, >=3 rej | 127 | **37.0%** | 20.4% | 1.81x | **0.001** | 70.9x vs 37.9x |
| ETH daily, >=5 rej | 51 | **39.2%** | 21.7% | 1.81x | 0.013 | **86.0x** vs 38.5x |
| ETH 4h, >=8 rej | 66 | 36.4% | 21.6% | 1.68x | 0.004 | 60.2x vs 39.5x |

Consistent across both symbols, both timeframes, and most rejection thresholds.
Across all 1,848 broken levels the median best multiple on a break day is 45x and
27% of breaks coincide with a >=100x move.

Caveat: `data/multibaggers` takes the max across strikes, so this is an INDICATOR
that a large move occurred, not a tradeable return. It says a big move is likelier
— not the direction, strike or expiry.

### Imminence: only proximity and (inversely) rejection count

Conditional on being within 3 ATR of a confirmed unbroken level, P(break within
5 bars), by quartile:

| factor | Q1 -> Q4 |
|---|---|
| distance to level | 55.9% -> 27.6% -> 14.0% -> **6.7%** |
| range compression | 27.5% -> 26.0% -> 24.9% -> 25.7% (**flat**) |
| bars since confirmation | 32.2% -> 23.8% -> 26.3% -> 21.7% |
| **rejection count** | **40.6%** -> 23.7% -> 16.2% -> **9.2%** |

Compression is flat — the "coil before the break" idea fails again, as it did in
the quiet-range and absorption tests. The useful finding is the INVERSION: levels
with more rejections break less often but pay more when they do (86x vs 70.9x
median). Heavily-defended levels are rarer, slower and bigger, which is exactly
the profile the "each expiry is a game to break it" framing wants.

### Dashboards

`levels_dash.py --build` writes `dash_past.txt` (every broken level ranked by what
the break paid) and `dash_live.txt` (confirmed levels still unbroken, distance in
% and ATR, rejection count, last rejection date).

**Live at the time of writing:** the ETH descending line (5 rejections) and the
BTC descending line (4 rejections) BOTH broke on 2026-09-18 and have held above
for four consecutive daily closes (ETH 2,714 vs line 2,507; BTC 84,308 vs 79,872).

### Level breaks, corrected framing (2026-09-21)

Tejas challenged the framing, correctly. Two corrections resulted.

**1. The 32.8% is a max-across-chain oracle, not a tradeable rate.** Per CONTRACT
on break days: P(2x) 34.1%, P(5x) 11.6%, P(25x) 2.20%, P(100x) 0.59% — against
32.1% / 10.7% / 1.66% / 0.25% off break days. So 1-in-45 for 25x, not 1-in-3.

**Where it IS tradeable** (event level, weekly block bootstrap):

| slice | n | hit | dEV | P(<=0) |
|---|---:|---:|---:|---:|
| all contracts, break day, 25x | 151,066 | 3.51% | +0.138 | 0.002 |
| >10% OTM, break day, 25x | 37,455 | 4.66% | +0.394 | 0.059 |
| **>10% OTM, break day, 100x** | 37,455 | **2.22%** | **+1.340** | **0.022** |
| >10% OTM, NON-break day, 100x | 28,675 | 0.38% | −0.379 | 0.995 |

The same strikes are +EV on break days and clearly −EV otherwise. The edge lives
at the 100x target on deep OTM, not at 25x.

**2. "Play every day from the 3rd rejection" reframing.** 261 confirmed levels,
6,264 live days, 258 break days = **4.1% of live days**. Median time from
confirmation to break is only **6 days**, and 98.9% eventually break — partly
geometric, since a converging trendline meets price soon after its third touch.

**Fakeouts: 67% of breaks close back within 10 bars** (74.1% at exactly 3
rejections, 62.2% at 6+). **But it does not matter to an option buyer:** hit100
on >10% OTM is 2.23% when the break holds and 2.21% when it fakes out. A trap is
still a big move. This is the key practical finding.

**Tightness before the break is significantly BACKWARDS.** 5d/20d compression:
tightest quartile traps 74.5%, loosest 58.9%, difference +15.5pp at P=0.000. The
10-bar range version is null (−4.9pp, P=0.893). Third failure for the
coil-before-break idea and the first that is significantly inverted. What DOES
separate real from fake is how far the breaking close travels past the level:
most decisive quartile traps 42.9% vs 78.8% for the most marginal (P=0.000).

Data refreshed through 2026-09-21 (spot candles and all 220 perps).

---

## Wedges, and the Aug-17 reading (2026-09-25)

Tejas pushed back on ranking break days by raw option multiples, pointed at the
BTC daily structure, and proposed a WEDGE + expiry-proximity setup from an
ADANIENT precedent (19 May 2023, week before the 25 May monthly expiry, 1:100).

### His structural reading was correct in every detail

Same line my detector found (anchored 2025-10-06, broke 2026-08-17 at 63,880):

| date | high | line | gap | |
|---|---:|---:|---:|---|
| 2026-05-06 | 82,808.7 | 84,253.5 | −0.77 ATR | his 2nd point; my TOL_ATR is 0.60 so I score it a miss |
| 2026-08-09 | 65,462.6 | 65,462.6 | 0.00 | his "small rejection a few days before" |
| 2026-08-17 | — | 63,880.2 | close above | the break |
| 2026-08-18 | low 64,012 | 63,682 | — | **low tagged the line from above and held** |

Then 19 Aug closed at 69,318. So the real sequence is **break → retest → run**,
which exposed a flaw in the payoff test: it asked "did a 100x start ON the break
day", giving 17 Aug no credit and attributing the 19th to whatever weaker line
broke that day. The window is now 0..3 days after the break.

### With that window, the WEDGE carries everything

`wedge.py` requires a confirmed descending resistance AND a confirmed support,
both live, overlapping >=40 bars, with the gap narrowing to <80% of its start.

| | n | P(100x, 0–3d) | median best | vs base | P(<=0) |
|---|---:|---:|---:|---:|---:|
| **BTC wedge break** | 31 | **71.0%** | 158.7x | **+18.1pp** | **0.024** |
| BTC non-wedge break | 486 | 54.1% | 113.0x | +0.5pp | 0.434 |
| **ETH wedge break** | 27 | **77.8%** | 148.3x | **+22.3pp** | **0.022** |
| ETH non-wedge break | 475 | 58.3% | 119.6x | +3.4pp | 0.177 |

**This revises the earlier finding.** Over 0–3 days an ordinary confirmed-level
break adds nothing; the wedge subset hiding inside it was carrying the result.

### The expiry half is not supported

| | n | P(100x) | P(<=0) |
|---|---:|---:|---:|
| BTC wedge, <=10d to MONTHLY expiry | 9 | 66.7% | 0.177 |
| BTC wedge, >10d | 22 | 72.7% | 0.035 |
| ETH wedge, <=10d to MONTHLY expiry | 8 | 50.0% | 0.590 |
| ETH wedge, >10d | 19 | **89.5%** | **0.001** |

Wedge breaks FAR from monthly expiry pay more. n=8–9 near expiry, so this is weak
either way — but it is certainly not the amplifier the ADANIENT case suggested.
Note the first attempt at this test was vacuous: Delta has weekly expiries, so
every day is within 10 days of *an* expiry. Monthly expiries only (the last in
each calendar month) make it bind — 37% of days.

**Still untested:** whether a break that is retested-and-held (as 18 Aug was)
pays more than one that is not. That is the natural next measurement.

### Daily break profile: is 17 Aug actually odd? (2026-09-25)

`daily_profile.py` writes `daily_break_profile.csv` — one row per day for all
1,000 days (696 with at least one break) carrying n_breaks, max_age, n_wedges,
max_rej and directional agreement.

**17 Aug 2026 against the full distribution:**

| metric | 17 Aug | median | p90 | rank | pct |
|---|---:|---:|---:|---:|---:|
| breaks | 10 | 2.0 | 8.0 | 50 of 1000 | 93.7% |
| **oldest line** | **315** | 15.1 | 138.9 | **27** | **97.3%** |
| **wedges** | **3** | 0.0 | 0.0 | **17** | **97.2%** |
| most-rejected | 8 | 4.0 | 8.0 | 60 | 89.8% |
| one-directional | 1.00 | 1.00 | — | — | 42.1% |

Genuinely odd — top 3% on age and wedges — but not unique. Two honest points:
directional agreement does NOT discriminate (most break days are one-directional),
and 19 Aug still outscores it on the profile (16 breaks, 292d, **10 wedges**,
14,603x best). The break→retest→run structure that makes the 17th the signal is
not captured by any of these columns.

**Which columns actually predict** (base P(100x within 0-3d) = 69.3%):

| metric | days | P(100x) | lift | P(<=0) |
|---|---:|---:|---:|---:|
| **max_age >= 100** | 146 | 82.9% | **+15.8pp** | **0.000** |
| **n_wedges >= 1** | 52 | 86.5% | **+18.6pp** | **0.001** |
| n_wedges >= 3 | 28 | 85.7% | +17.3pp | 0.010 |
| max_age >= 250 | 40 | 85.0% | +16.9pp | 0.028 |
| n_breaks >= 8 | 108 | 75.0% | +6.5pp | 0.063 |
| **n_breaks >= 15** | 15 | 73.3% | +4.6pp | **0.337** |
| max_rej >= 8 | 102 | 74.5% | +5.8pp | 0.124 |

**Line AGE and WEDGE presence predict; break COUNT does not.** This corrects the
earlier emphasis — comparing "16 breaks on the 19th vs 10 on the 17th" was
reading a column with no predictive value. Combining the two survivors is worse
than either alone (25 days, P=0.065), so use them separately.

`levels_dash.py` now emits a BROKE IN THE LAST 3 SESSIONS block carrying age and
wedge, with break count deliberately demoted.

### The cube: event tier x expiry x target (2026-09-25)

`cube.py`. Direction is never assumed — each event stakes 1 unit split across an
OTM call and an OTM put (3–15% out, nearest 8%). Note the algebra: with ½ unit
per leg and a leg paying T× its own stake, EV = T·P(leg hits) − 1 − fees, so
**buying both sides does NOT lower the break-even per leg**. It halves variance
and guarantees one leg dies. Break-even stays (1+COST)/T.

Tiers rank days by `max_age` (the profile column that measures, P=0.000).

**TARGET 100x — break-even 1.08%/leg**

| tier | expiry | days | legs | P(leg) | EV/unit | P(EV<=0) |
|---|---|---:|---:|---:|---:|---:|
| **top 5%** | **weekly 3-9d** | 33 | 141 | **4.26%** | **+3.17** | 0.258 |
| top 5% | immediate 0-2d | 33 | 260 | 1.54% | +0.46 | 0.367 |
| top 10% | weekly 3-9d | 68 | 277 | 2.53% | +1.44 | 0.274 |
| top 15% | weekly 3-9d | 102 | 404 | 1.73% | +0.65 | 0.355 |
| any break day | weekly 3-9d | 685 | 2,512 | 0.64% | −0.45 | 0.768 |
| **NO break day** | weekly 3-9d | 291 | 1,022 | **0.00%** | −1.08 | 1.000 |

At 50x the same shape holds (top-5% weekly 4.26%, EV +1.05). At **25x and 10x
almost everything is negative** — those bars (4.33% and 10.8%) are too high for
OTM contracts even on the best days.

**Three readings:**
1. **The gradient is monotone in every column** — top5 > top10 > top15 > any break
   > no break, at every target and expiry. Fifteen cells ordering correctly is
   not what noise looks like.
2. **Weekly (3–9d) beats the immediate expiry**, 4.26% vs 1.54% at 100x on top-5%
   days. A 0–2 DTE contract often cannot survive the 2-day break→retest→run
   sequence.
3. **The no-break control is the strongest evidence**: 0.00%, zero of 1,022 legs,
   against 4.26%.

**But no cell is significant** — best P(EV<=0) is 0.258 on 33 days / 141 legs.
Shape right, size promising, power absent. Do not size on this.

### Multi-timeframe: not cheating, and the retest is scale-dependent

Using a lower timeframe to resolve a retest is legitimate — it was available in
real time. It becomes a search problem only if the timeframe is chosen after
seeing which one confirms. `levels.py` runs 1440/360/240m and `daily_profile.py`
aggregates all three, so lower timeframes are already in.

The 18-Aug retest is the SAME bar at every resolution (low 64,012.3). What
changes is ATR scaling: 0.32 ATR on daily, 0.85 on 6h, 0.88 on 4h, 1.37 on 1h.
So in normalised terms it is CLEAREST on the daily; what the lower timeframe adds
is the shape of the touch, not a closer approach. A first attempt at this test
used a 0.25 ATR cutoff and reported "retest invisible at every timeframe" — a
threshold artifact, corrected.

### What ATR means here, and candle quality (2026-09-25)

**ATR** is the average true range over 14 bars — the size of a typical recent bar,
in price units. On BTC daily in May 2026 it was 1,875 points (2.30% of price), so
0.6 ATR = 1,125 points and 0.77 ATR = 1,444. On ETH daily it was 72 points. It is
a ruler that rescales with volatility, so "near the line" means the same thing in
a quiet market and a violent one, and on BTC and ETH alike. It has **no relation
to the trendline** — purely a property of recent bars.

**The break test uses no ATR at all.** In `levels.py` a break is `close > line`,
full stop. ATR enters only when counting TOUCHES, i.e. deciding whether a line has
been defended three times and is worth watching. Tejas's worry that the 17 Aug
break was "rejected because of ATR" does not apply — that break was detected and
is the top row of the day's output.

**Multiple valid fits are already embraced.** The detector enumerates every pair
of major swing highs and keeps each line reaching 3+ touches — 128 confirmed lines
on BTC daily alone. It never picks one canonical line.

**His actual point — candle quality should count on its own — is CONFIRMED:**

| rule (top quartile of break days) | days | P(100x,0-3d) | lift | P(<=0) |
|---|---:|---:|---:|---:|
| **big breaking bar (range/ATR)** | 174 | 83.3% | **+17.1pp** | **0.000** |
| solid body, not a wick | 174 | 76.4% | +8.7pp | 0.003 |
| oldest line >= 100d | 146 | 82.9% | +15.8pp | 0.000 |
| at least one wedge | 52 | 86.5% | +18.4pp | 0.001 |
| **big bar AND old line** | **63** | **90.5%** | **+22.7pp** | **0.000** |

The conjunction is the strongest cell found in the level work. 17 Aug qualifies:
bar 2.73 ATR (87th pctile), body 0.87 (84th), oldest line 315d.

**Two non-predictors that sharpen the definition:**
- *how far past the line it closed*: +1.1pp, P=0.397 — null for payoff, even
  though the same measure strongly predicts fewer TRAPS (42.9% vs 78.8%). Both
  hold, and they fit: traps do not matter to an option buyer, who is paid for the
  move either way.
- *closed near its high*: −0.9pp, P=0.579 — null, as it was in the exhaustion test.

So "quality" means the SIZE of the breaking bar, not its close position or how
far it cleared the line. A big bar is itself the move being bought.

### Candle quality does NOT improve the cube (2026-09-25)

Re-tiering the cube on the candle-quality rules, weekly 3–9d expiry, OTM both sides:

| tier | days | legs | 100x hit / EV | 200x hit / EV |
|---|---:|---:|---|---|
| **top 5% by line AGE (existing)** | 33 | 141 | **4.26% / +3.17** | **2.84% / +4.59** |
| top 10% by age | 68 | 277 | 2.53% / +1.44 | 1.44% / +1.81 |
| big bar + old line | 61 | 238 | 1.68% / +0.60 | 1.26% / +1.44 |
| big bar + wedge | 30 | 105 | 2.86% / +1.77 | 1.90% / +2.73 |
| big bar only | 171 | 686 | 0.87% / −0.21 | 0.73% / +0.38 |
| any break day | 685 | 2,512 | 0.64% / −0.45 | 0.44% / −0.21 |
| NO break day | 291 | 1,022 | 0.00% / −1.08 | 0.00% / −1.08 |

**Line age alone still wins.** Candle quality makes the cube worse.

**Why, and it matters:** the +17.1pp candle-quality result was measured against
`data/multibaggers`, which takes the MAX ACROSS THE WHOLE CHAIN — it answers "did
a 100x exist somewhere that day". The cube buys ONE specified contract (8% OTM,
weekly). A big breaking bar predicts the former and not the latter. This is the
strike-oracle gap ([[de-signals-optimal-strike-oracle]]) reappearing, and it is
why both measures are kept. **Candle quality is real on the oracle measure and
does not survive the move to an implementable one.**

Practical consequence: the trading rule is unchanged — **top-5% break day BY LINE
AGE → weekly expiry → 8% OTM both sides → limit at 200x.** Candle quality belongs
in the dashboard as context, not in the tier definition.

### Zones: pooling rejections across nearby levels (2026-09-26)

Tejas: a support/resistance level is a ZONE, not a price. If 2–3 nearby levels
each got rejected a couple of times, those rejections belong to the same wall.
Implemented as price-confluence: on each break day, cluster the broken levels by
price (within 1 ATR, same direction) and pool their rejection counts.

**On the oracle measure it rescues a dead metric:**

| rule | days | P(100x,0-3d) | lift | P(<=0) |
|---|---:|---:|---:|---:|
| OLD: single level's rejections >=8 | 102 | 74.5% | +5.8pp | **0.115** |
| **NEW: pooled rejections >=12** | 306 | 74.8% | +8.0pp | **0.001** |
| NEW: pooled rejections >=20 | 147 | 76.9% | +8.8pp | 0.003 |
| NEW: zone has >=3 levels | 326 | 74.8% | +8.3pp | 0.002 |
| oldest line >=100d (reference) | 143 | 82.5% | +15.6pp | 0.000 |
| zone>=3 AND old line | 98 | **84.7%** | +17.3pp | 0.000 |

Per-line counting gave P=0.115; pooling the same information gives P=0.001.
17 Aug 2026: a zone of **7 levels with 36 pooled rejections**, against a
single-level max of 8.

**But it does not improve the tradeable cube** (weekly 3–9d, OTM both sides):

| tier | days | 100x hit / EV | 200x hit / EV |
|---|---:|---|---|
| **top 5% by line AGE** | 33 | **4.26% / +3.17** | 2.84% / +4.59 (P=12%) |
| top 5% by pooled rejections | 36 | 3.57% / +2.49 | 2.86% / +4.63 (P=37%) |
| **top 5% by ZONE SIZE** | 36 | **0.00% / −1.08** | **0.00% / −1.08** |
| zone>=5 AND old line | 37 | 2.74% / +1.66 | 1.37% / +1.66 |

Pooled rejections ties age on EV at 200x but with a far worse P-value; zone size
alone is catastrophic.

**THE PATTERN WORTH NAMING.** This is the SECOND consecutive feature to win on
the oracle measure and fail on the implementable one (candle quality was the
first). `data/multibaggers` asks "did a 100x exist ANYWHERE in the chain that
day", which is close to a measure of how violent the day was — so anything
correlated with "big day" scores well. Choosing WHICH CONTRACT to buy needs
different information. **Line age is so far the only feature that survives both
tests**, which suggests it is reporting something about the structure being
broken rather than about the day being loud.

Practical: keep zone pooling as a DESCRIPTION in the dashboard (it characterises
a level far better than a per-line count), not as a tier.

### Reverse search: what the level system MISSES (2026-09-26)

`events_browser.py` reads the day table two ways.

    python events_browser.py --top 25                 rank days by age+wedges
    python events_browser.py --reverse --target 100   start from paying days
    python events_browser.py --day 2026-08-17         one day in detail

Forward, the top of the table is **2026-08-19 (#1)** and **2026-08-17 (#3)** out
of all 1,000 days, ranked on line age plus wedge count.

**Reverse — every day a >=100x option move BEGAN (301 days):**

| what the level system saw | share of paying days | share of ALL days |
|---|---:|---:|
| a level broke | 76.4% | 69.6% |
| **an OLD line (>=100d) broke** | **26.6%** | **14.3%** |
| a wedge broke | 9.3% | — |
| a big bar (>=2 ATR) | 42.2% | — |
| **NOTHING broke at all** | **23.6%** | — |

Two things fall out.

**"A level broke" is nearly useless as a filter** — 76.4% of paying days against
69.6% of all days. Levels break on seven days in ten, so the event carries almost
no information. Only the AGE qualifier discriminates (26.6% vs 14.3%, a 1.86x
enrichment), which is the same conclusion the forward test reached.

**About one paying day in five is invisible to the system.** Checked against a
warm-up artifact — the detector is live from Jan-2024 and restricting to
post-2024-05 only moves the figure from 23.6% to 21.6%, so this is real blindness,
not start-up. Biggest genuine misses: 2025-04-04 (6,095x, 19 contracts), 2026-02-07
(1,660x, 52 contracts), 2026-02-28 (1,466x, 49), 2026-03-18 (1,389x).

Note 2026-02-07 sits inside Tejas's episode D: the system caught 31 Jan (8 breaks,
a 739-day line) and missed 7 Feb entirely.

**So the level system is a PARTIAL detector.** It is not wrong — old-line breaks
really do enrich — but it sees one kind of setup and a fifth of the big days
arrive by some other route. Worth pointing the same reverse search at
`data/trades/` (`trades.js` merges moves across instruments into market events,
a richer source than `multibaggers`) to characterise what those other routes are.

### Reverse search on MERGED MARKET EVENTS — the honest coverage (2026-09-26)

`trades_reverse.py`. `data/multibaggers` is per-contract, so one move is counted
dozens of times; `trades.js` merges moves across instruments into events carrying
maxRatio, participant count, hold time and — the new lever — a DIRECTION. The
level system knows whether a RESISTANCE or SUPPORT line broke, so for the first
time we can ask whether the break pointed the same way as the move.

804 merged events reaching >=100x (377 calls, 427 puts), against proper per-spot
base rates:

| | on paying days | base | enrichment |
|---|---:|---:|---:|
| any break | 56.3% | 52.1% | **1.08x** |
| break in the SAME direction | 32.5% | 28.3% | **1.15x** |
| **old line (>=100d), same direction** | **7.2%** | **4.4%** | **1.65x** |
| NOTHING broke | **43.7%** | — | — |

**Direction is near-random: 32.5% same-direction vs 29.2% OPPOSITE.** A break
pointing the wrong way is almost as common before a big move as one pointing the
right way. Consistent across targets (100x/200x/500x) and across sides.

**44% of big market events have no break at all** — nearly double the 23.6% the
per-contract measure suggested. The per-contract version flattered itself because
days with breaks have more participating contracts, so they were weighted more
heavily; merging removes that and the coverage estimate roughly halves.

**What survives:** only the old-line qualifier enriches, at 1.65x — real, and
close to the 1.86x the per-contract reverse search found, so that part is robust.
But it covers just **7.2% of big events**.

**Net reading of the level work.** It is a low-coverage, direction-blind,
weak-enrichment detector. Old-line breaks genuinely concentrate big moves (1.65x)
but catch one event in fourteen, and the break's own direction does not predict
the move's. That is a much more modest claim than the forward tests implied, and
the merged-event measure is the one to quote.

---

## SIGN BUG in moneyness_pct, and the full audit (2026-09-26)

`build_events.py:176` defines `moneyness_pct = (strike - spot)/spot * 100`.
Signed, so it is **+OTM for CALLS and −OTM for PUTS** (measured correlation with
true distance: +1.000 and **−1.000**). Any filter like `between(3,15)` applied to
both sides therefore selects OTM calls and **deep ITM puts** — median premium
18.83 vs **2,524.34**.

Found while investigating a null skew result, which was itself invalid for the
same reason.

### Audit of all six users

| script | status |
|---|---|
| `build_events.py` | source; correct by its own convention |
| `r4_control.py` | **clean** — already did `np.where(opt_type=='C', mny, -mny)` |
| `phase3_model.py` | **clean** — same |
| `significance.py` | stores `mny` (line 99), never filters on it — benign |
| `cube.py` | **broken → fixed** |
| `opt_xsec.py` | **broken → fixed, claim RETRACTED** |

### Consequences

**1. `cube.py` — survives, composition changes.** Top-5%-by-age, weekly, 100x:

| | legs | hit | EV |
|---|---:|---:|---:|
| blended (old, calls + ITM puts) | 141 | 4.26% | +3.17 |
| **blended (fixed, both OTM)** | 173 | 3.47% | +2.39 |
| — **calls** | 88 | **6.82%** | **+5.74** |
| — puts | 85 | 0.00% | −1.08 |

The edge is on the CALL leg. The old 4.26% was OTM calls averaged with ITM puts,
which are expensive and cannot 100x by construction.

**2. The ">10% OTM on a break day" headline — survives and IMPROVES.**
Break day @100x: old 2.16% dEV +0.910 P=0.043 → fixed 1.74% dEV **+0.557
P=0.005** on a 67% larger sample. No-break day stays −ve (0.61%, P=0.112).

**3. `opt_xsec.py` Step-3 result — RETRACTED.** "Long near-the-money, short
far-OTM" was +44.2% at P=0.0055; corrected it is **+22.1% at P=0.204**. The put
leg **flips sign** (+21.1% → −21.1%). Only the call side survives (+64.3%,
P=0.026) and it was never affected.

### The puts-0% question

Not a bug. OTM puts reach 100x at 0.584% over 204,045 legs (max 5,009x) against
calls at 0.554%. Eighty-five legs implies 0.5 expected hits, so zero is
unremarkable; **6 of 88 calls is the anomaly**. Under a null of equal rates, all
six landing on the call side has probability ≈(88/173)^6 ≈ 2% — suggestive, but
the split was examined post hoc, so the call/put asymmetry is UNPROVEN.

This is the third measurement artifact of the week, after the strike oracle and
the per-contract weighting in the reverse search. All three inflated a result.

### Can the five "stored energy" features combine? No (2026-09-26)

`approach.py`, `combine5.py`. Five operationalisations of "coiled energy precedes
the move", each null on its own:

| feature | what it measures | result alone |
|---|---|---|
| comp | 5-bar / 20-bar range (squeeze) | null, then **significantly backwards** (+15.5pp more traps) |
| ttr | prior 10-bar range in ATR | null |
| overlap | mean bar overlap (absorption) | null; adverse on up-breaks |
| travel | net directional move INTO the level | **null** (−0.3pp, P=0.534) |
| effic | \|net\| / summed path into the level | **null** (+0.2pp, P=0.484) |

The last two were built deliberately DIFFERENT from the squeeze — range
contraction versus directional travel, since a market can be wide-ranged and
still go nowhere. They failed anyway. Notably **steep** approaches are marginally
BETTER (+5.9pp, P=0.062), the opposite of the energy-conservation thesis.

**Combined, three ways:**

1. **Correlation** — effective dimensionality **2.89 of 5**. comp/ttr/overlap
   cluster (|r| 0.36–0.52), travel/effic cluster (0.48). Three things, not five.
2. **One pre-specified composite** (equal-weight z, sign-aligned to the thesis):
   top quartile 73.0%, **+4.4pp, P=0.134** — not significant, against age's
   +15.4pp at P=0.000.
3. **Model with a time split** (fit 2024-25, score 2026 untouched):

| features | train AUC | HELD-OUT 2026 AUC |
|---|---:|---:|
| five energy features | 0.547 | **0.485** |
| **age only** | 0.588 | **0.575** |
| five + age | 0.601 | **0.566** |

The five score **below chance out of sample**, and adding them to age DEGRADES
age (0.575 → 0.566) while improving it in training (0.588 → 0.601) — textbook
overfitting.

**Verdict: "coiled energy precedes the break" is FALSIFIED**, in five independent
operationalisations, individually and combined. Do not retry it in another form.

Aug-17 remains a genuine instance (approach travel −1.36 ATR, 10th percentile,
efficiency 0.07) — the reading of that chart is accurate, it just does not
generalise.

### Nested structure: a wedge resolving INTO an older line (2026-09-26)

Tejas's weekly BTC chart: an ascending wedge rises into the descending line off
the early-2024 high, and the break happens where they meet. His claim is that the
trendline "was not broken just anyhow, it was broken BY a pattern completing."

`nested.py` operationalises it as a RATIO, not mere co-occurrence: a wedge breaks
AND a separate line breaks whose age is >=3x the wedge's own span. Two lines of
similar age breaking together is coincidence; a 13-day wedge taking out a 300-day
line is structure resolving into structure. Median observed nest ratio 7.4x.

**Oracle measure (P(100x within 0-3d), base 69.3%):**

| condition | days | P(100x) | lift | P(<=0) |
|---|---:|---:|---:|---:|
| **NESTED** | 40 | **90.0%** | **+21.9pp** | **0.001** |
| wedge only (no old line) | 27 | 88.9% | +20.4pp | 0.003 |
| **both, but NOT nested** | 25 | **84.0%** | +15.5pp | 0.066 |
| old line only (no wedge) | 118 | 82.2% | +14.9pp | 0.002 |
| **neither** | 525 | **66.3%** | **−6.4pp** | 0.969 |

Nested (90.0%) beats merely-coincident (84.0%), which is exactly his distinction.

**And it SURVIVES the cube** — the first pattern-composition idea this session to
pass both measures (candle quality and zone pooling each passed the oracle and
failed here):

| tier | days | legs | 100x EV | 200x EV | P(200x) |
|---|---:|---:|---:|---:|---:|
| **top 5% by line AGE** | 33 | 173 | **+2.39** | **+3.54** | **14%** |
| NESTED | 40 | 194 | +1.49 | +3.04 | 37% |
| wedge, any | 52 | 249 | +0.93 | +2.13 | 38% |
| old line >=100d | 140 | 701 | +0.06 | +0.06 | 54% |
| **neither** | 518 | 2,446 | **−0.76** | −0.67 | **99%** |

**Verdict.** Composition is real — nested beats either component alone on both
measures. But it does NOT beat line age (near-tied EV at 200x, far worse P), so
it confirms the structure story rather than improving the tier.

**The most usable output is the NEGATIVE filter:** "neither a wedge nor an old
line" covers 518 days — three-quarters of all break days — at EV −0.76, P=0.99.
Knowing when not to look is the most confident thing in the table.

17 Aug 2026: 3 wedges, a 315-day line, **nest ratio 39.4x**.

### Full audit, round 2 (2026-09-26)

Hunted the four bug classes that have already bitten this project.

**BUG (minor, fixed): phantom zeroes at the tail.** `data/multibaggers` lags the
candle data, so the most recent days carried `best=0` because nothing had been
computed, not because nothing moved — 16 days, **12 of which had a level break**,
counted as breaks that paid nothing. Trimming them actually STRENGTHENS the
result (old-line lift +15.9 → +17.3pp). A guard now trims the tail in
`daily_profile.py`.

**Clean:** `find_wedges` has no look-ahead (0 of 6 wedges lacked a confirmed
support line before the break). No other signed field shows a per-side asymmetry
— `moneyness_pct` was the only one. `multibaggers` covers 96.4% of days, so
`fillna(0)` is otherwise legitimate.

**Known and accepted:** the 0–3d outcome autocorrelates at 0.675 (lag 1) by
construction, since adjacent days share up to 3 of their 4 outcome days. The
weekly block bootstrap absorbs this because weeks, not days, are resampled.

### MISSED 1 — the outcome window was never swept, and 0–3d was the wrong choice

| window | base | old-line lift | P | wedge lift | P |
|---|---:|---:|---:|---:|---:|
| **day 0** | **30.6%** | **+32.4pp** | **0.000** | **+25.1pp** | 0.001 |
| 0–1d | 47.9% | +25.5pp | 0.000 | +16.5pp | 0.029 |
| 0–3d (adopted 2026-09-25) | 70.2% | +17.7pp | 0.000 | +17.5pp | 0.002 |
| 0–5d | 82.4% | +9.1pp | 0.001 | +9.0pp | 0.048 |
| 0–8d | 92.6% | +2.8pp | 0.073 | +2.0pp | 0.289 |

The window was widened to 0–3d on the strength of the break→retest→run
observation. The narrative was right but the measurement got WORSE: day 0 gives a
2x enrichment (63% vs 30.6%) against 1.25x at 0–3d, because the base inflates
toward 100% as the window widens. **Day 0 is the correct measurement window.**
Reported lifts at 0–3d are therefore CONSERVATIVE, not inflated.

### MISSED 2 — R4 INVERTS on break days

| slice | legs | hit100 | EV | hit200 | EV |
|---|---:|---:|---:|---:|---:|
| top-5% break day, all | 185 | 3.24% | +2.16 | 2.16% | +3.24 |
| + **R4 agrees** | 78 | 1.28% | +0.20 | 0.00% | −1.08 |
| + **R4 DISagrees** | 122 | **4.92%** | **+3.84** | **3.28%** | **+5.47** |

Opposite to R4's standalone behaviour. Coherent reading: an old resistance line
breaking while the 4h always-in is still DOWN means the trend has not turned yet
— you are early in the reversal. R4 agreement means the turn already happened and
you are late. The break IS the reversal signal; R4 measures what is being
reversed.

**Caveats:** 122 vs 78 legs, and this was found by testing a combination rather
than predicting it. Treat as a lead, not a result. Needs the Westfall-Young
treatment before it earns a place in TOP10.

### The unforecastable class, bounded (2026-09-26)

Tejas raised the other side: moves with no prior price action at all. His example
is 2026-09-04 12:30 UTC — BTC 81,324 -> 79,608, **2.49% in 15 minutes**, almost
certainly a long-stop cascade into a near expiry. Nothing to react to.

**Flash risk is overwhelmingly downside: 11 of the 12 largest 15-minute bars in
BTC history are DOWN** (largest 9.69%, 2025-10-10).

Classifying the 804 merged >=100x events by how fast the move completed:

| speed (candles to peak) | events | share | any break | **old-line warning** | median ratio |
|---|---:|---:|---:|---:|---:|
| FLASH <=3 | 256 | 31.8% | 49.2% | **3.5%** | 183x |
| fast 4–10 | 180 | 22.4% | 53.9% | 3.9% | 225x |
| normal 11–30 | 166 | 20.6% | 58.4% | 5.4% | 274x |
| slow >30 | 202 | 25.1% | 65.8% | **16.3%** | 246x |

**The warning rate scales with duration — 3.5% to 16.3%, a 4.7x span.** The level
system is a structure detector and is blind to liquidation mechanics by
construction, not by failure.

**The unreachable share is BOUNDED at 16.2%**: 130 of 804 events are flash moves
with no break of any kind. Roughly one in six. Missing those is not a skill gap.

### "Should I buy cheap deep OTM every day?" — measured, and no

| strategy | hit100 | break-even | EV | P(EV<=0) |
|---|---:|---:|---:|---:|
| 3–15% OTM daily | 0.755% | 1.08% | −0.36 | **0.927** |
| 15–50% OTM daily | 1.318% | 1.08% | +0.17 | 0.370 |
| **>50% OTM daily ("cheap")** | **0.269%** | 1.08% | **−0.83** | **0.995** |

The cheapest strikes are the worst — >50% OTM bleeds at P=0.995. The bleed-trap
instinct is right, and it is MOST right for exactly the strikes that look most
tempting after watching a flash move. Only 15–50% clears break-even, and not
significantly.

**Note for the journal.** The psychological asymmetry Tejas describes is
structural, not irrational: a flash you were absent for arrives as pure loss with
no counter-evidence, while a move you watched build arrives with context. The
measured shape is that flashes are a sixth of big events and slow structural
moves are a quarter, with a 4.7x higher warning rate.

### BUG: the wedge detector was one-directional (2026-09-26)

`find_wedges` looped only over R-line breaks, so **every wedge result reported
before this covered UPWARD breaks only** and the downward half of the population
was invisible. Fixed to scan both sides and tag `dirn`.

**The missing half is the stronger half.** Day-0 window, base 30.6%:

| set | days | P(100x) | lift | P(<=0) |
|---|---:|---:|---:|---:|
| UP only (what was measured) | 52 | 53.8% | +24.6pp | 0.002 |
| **DOWN only (was invisible)** | 51 | **62.7%** | **+33.8pp** | **0.000** |
| both | 103 | 58.3% | **+31.0pp** | 0.000 |

### Do wedge breaks trap? Median yes, tail no

Tejas: wedge breaks often trap and give huge moves the OTHER way, so buy cheap
OTM both directions. Measured over the 10 bars after the break:

| break | n | median move WITH | median move AGAINST | trap rate |
|---|---:|---:|---:|---:|
| UP | 78 | 1.47% | 1.22% | 47.4% |
| DOWN | 72 | 1.86% | 1.52% | 43.1% |

45.3% overall. So it is NOT a reversal bias (which would mean fading); the break
direction simply carries little information about the MEDIAN move.

**But the option payoff is strongly directional** (weekly 3-9d, OTM):

| | calls hit100 / EV | puts hit100 / EV |
|---|---|---|
| wedge UP break | **4.13% / +3.05** | 0.00% / −1.08 |
| wedge DOWN break | 0.75% / −0.34 | 0.78% / −0.31 |
| any wedge | 2.35% / +1.27 | 0.39% / −0.69 |

**Resolution: the median move is roughly symmetric, the TAIL is not.** A 1.22%
counter-move does not take an OTM option to 100x; the moves that do reach 100x
follow the break direction. So the practical rule is the opposite of "buy both
sides" — on a wedge break, buy the BREAK DIRECTION, because you are buying the
tail and the tail is directional even when the median is not.

Caveats: puts at 0.00% is 128 legs against ~0.8 expected hits, i.e. sample size
rather than proof. And down-break wedges pay NEITHER side at 100x despite being
the stronger half on the oracle measure — the oracle-vs-implementable gap again.
