# ML SPEC — Multibagger OTM Options Signal Model

**Status:** living document. Every decision gets an ID and a state.
**Version:** v0.4 — plan section added; Brooks arm
**Scope:** crypto (Delta Exchange India: BTC, ETH, XAUT) first. Indian F&O (NSE) later,
same architecture.

Decision states: `DECIDED` · `PROPOSED` (awaiting your yes/no) · `OPEN` (needs data first)

---

## 0. PLAN — live TODO

**This section is the working checklist. Everything below it is reference.**
Update states here rather than scrolling the conversation.

States: `TODO` · `DOING` · `DONE` · `BLOCKED` · `WAITING-TEJAS`

### Now

| # | Task | Owner | State | Notes |
|---|---|---|---|---|
| P1 | Random-entry null baseline | Tejas | **WAITING-TEJAS** | "later today". Cheap. Either validates the signal stack or redirects it. D-40 |
| P2 | Answer `08-open-questions.md` §3 — merged-event ratio | Tejas | **WAITING-TEJAS** | max / nearest-the-money / mean across members. **Defines the label** — must settle before training |
| P3 | D-30 — mode 1 as first ML target? | Tejas | **WAITING-TEJAS** | ~10x base rate of mode 3 |
| P4 | D-13 — tradeability floor (min volume, min premium) | Tejas | **WAITING-TEJAS** | prevents labelling untradeable lottery tickets |

### Next — the four-arm experiment

One pipeline, four feature sets. Same label, same folds, same code.
Training is **seconds to minutes**. The branching is in feature design, not compute.

| Arm | Features | Question it answers |
|---|---|---|
| 0 | context only (tteHours, moneyness, duration) | the tautology floor — everything must beat this |
| 1 | context + agnostic candle-shape family | can generic price structure predict this? |
| 2 | context + existing signal columns (`patterns.js`) | **do your patterns carry real information?** |
| 3 | context + both | do they add to each other? |
| 4 | context + Brooks-derived spot features | see `BROOKS_FEATURES.md` |

Arm 1 vs arm 2 is the measurement. Arm 0 stops either from taking credit for
"deep OTM near expiry pays more often."

| # | Task | Owner | State | Est. |
|---|---|---|---|---|
| P5 | Labelled dataset — join `multibaggers.js` output to features; episode collapsing + censoring | Claude | TODO | ~2h write |
| P6 | Agnostic candle feature extractor (~80 numbers, arms 0/1/3) | Claude | TODO | ~3h |
| P7 | Brooks feature extractor (arm 4, ~90–120 numbers) | Claude | TODO | ~4h |
| P8 | Train all arms: logistic → LightGBM, purged walk-forward | Claude | TODO | ~1h write, ~4min run |
| P9 | Comparison table: precision at low recall, per arm | Claude | TODO | the verdict |
| P10 | SHAP + permutation importance on the winner | Claude | TODO | ~1h. Answers "which parameters are inert" (D-37, D-42) |

### Later

| # | Task | State |
|---|---|---|
| P11 | Premium grid (strike × time) — swap cell value from signal-count to premium (D-27) | TODO |
| P12 | IV/OI capture — check if Delta serves history; if not, start capturing live (D-21) | **TODO, ticking clock** |
| P13 | Contract selection optimizer — arithmetic, no ML (D-02 stage 3) | TODO |
| P14 | Paper-trade forward | TODO |
| P15 | Extension to Indian F&O | TODO |

### Retired

- `label_scan.js` — superseded by `multibaggers.js` (D-38). Episode collapsing and
  censoring logic salvaged into P5.

---

## 1. The problem, stated precisely

Given a timestamp `t` and an underlying `S`, predict whether **some tradeable OTM
option** will return ≥ 25x (also 50x, 100x) within a forward window.

### 1.1 The tautology trap — why the naive version fails

**D-01 · DECIDED.** Do not train a classifier directly on "did this contract return 25x"
with premium / moneyness / DTE as features.

Reason: 25x on a long option is mostly a mechanical function of the contract you picked.
A ₹0.40 far-OTM weekly goes 30x on a 2.5% spot move; a ₹180 ATM option goes 3x on the
same move. A model given those features finds that path immediately and converges on
"always buy the cheapest, nearest-expiry, furthest-OTM contract" — which scores well on
AUC and has catastrophic negative expectancy, because the base rate of 25x is a property
of the contract, not a prediction.

### 1.2 The decomposition

**D-02 · DECIDED.** Split into three stages:

| Stage | What it does | Method |
|---|---|---|
| 1. Spot model | P(underlying moves ≥ M in direction D within horizon H) | ML — this is where learnable signal lives |
| 2. Vol model | conditional on that move, does IV expand or crush | ML / heuristic, separable |
| 3. Contract selection | given a spot-path forecast + IV path, which strike maximizes P(25x) | **deterministic optimization, no ML** |

Stage 3 is pricing arithmetic. No model needed. This is why the target of the ML work is
the *move*, not the *multiple*.

Your own framing — "did any OTM option give 25x at this timestamp, given DTE and spot" —
collapses to exactly this: it is a question about the size of the spot move relative to
volatility and time remaining. Good convergence; no conflict between our framings.

### 1.3 Trigger vs veto

**D-03 · DECIDED.** The primary ML target is a **veto/filter**, not a trigger.

From STATE.md 2.1.B: the documented failure was not failing to spot the big move (caught
by eye) — it was buying on ~60 non-setup days beforehand. So the high-value, high-sample
task is "is today ordinary?" (abundant negatives) rather than "is a multibagger imminent?"
(very few positives).

Practical consequence: two models, same features.
- **Veto model** — high sample count, high achievable accuracy, kills non-setup days
- **Trigger model** — few samples, low recall by design, tuned for precision

---

## 2. Labelling

### 2.1 Method

**D-04 · DECIDED.** Triple barrier (Lopez de Prado) with the stop barrier replaced by
"return to origin" (your Al Brooks–derived idea). Applied to **spot** series only, not to
option premium series.

Per bar `i`, per direction:

```
P    = close[i]
arm  = P ± k · ATR_baseline[i]

scan forward j = i+1 .. i+N:
    ARM    when high[j] ≥ arm      (up)  /  low[j]  ≤ arm   (down)
    RETURN when low[j]  ≤ P        (up)  /  high[j] ≥ P     (down)   [only after armed]
    M = max favourable excursion from P, frozen at the return bar
    T = j_return − i, or null if never returned inside N
```

Three outcomes:

| Outcome | Meaning | Role |
|---|---|---|
| `unarmed` | never travelled k·ATR | **ordinary day** → veto-model negatives (abundant) |
| `returned` | armed, then came back to P | **failed breakout** → hard negative |
| `held` | armed, never returned inside N | **positive candidate** |

The `returned` bucket is the critical one: it is the failed breakout that looks *identical
at the decision point*. It gives negatives maximally similar to positives, which is what
forces the model to learn the real distinguishing signal rather than "big move vs calm."

### 2.2 Corrections applied to the original 2.5 spec

**D-05 · DECIDED — episode collapsing.** Consecutive qualifying bars share almost their
entire forward window; they are near-duplicate views of ONE move. One 3-day hourly move
produces ~72 "positive" bars. Bar-level counts overstate independent samples by roughly
the episode length (measured 4.6x on synthetic data). **All sample-size decisions use
episode counts.** Implemented in `label_scan.js`.

**D-06 · DECIDED — direction split.** `M` as `|price − P|` conflates up and down. Calls and
puts are different trades. Scan runs per-direction.

**D-07 · DECIDED — two thresholds (arm + return).** The original "return within tolerance of
P" triggers immediately, since at bar i+1 price is still at P. Fixed by requiring travel
of k·ATR first (arm), then a touch of P counts as return. Side benefit: creates the
`unarmed` bucket, which is exactly the veto-model negative class, for free.

**D-08 · DECIDED — censoring reported separately.** `T = "never within N"` is censored, not
observed. A move returning at N+1 is recorded identically to one that never returns. Bars
with fewer than N bars remaining are excluded, not counted as positives.

**D-09 · DECIDED — gap exclusion.** A data gap inside the forward window can fake a "never
returned" (price left, came back, we never saw it). Bars whose window spans a gap are
excluded.

**D-10 · DECIDED — intrabar conservatism.** When one bar both arms and returns, count it as
`returned`. Within-bar path order is unknowable from OHLC; this can only understate
positives.

### 2.3 What "big" means — SUPERSEDED, now payoff-derived

**D-11 · SUPERSEDED by D-25.** Original plan: pick an ATR multiplier `k` as the yardstick,
using a slow (168-bar) baseline so a tight coil wouldn't distort the target. That required
choosing `k` arbitrarily.

**D-25 · DECIDED (your definition, and it's the better one).** "Big" means *big enough to
pay 25x / 50x / 100x, given the DTE, moneyness, volatility and spot at that moment.*
This is measured **directly from stored option candles**, not proxied through spot.

```
for each (underlying, timestamp t):
    chain = OTM options trading at t, passing the tradeability filter (D-13)
    for each option in chain:
        did premium reach 25x its t-value within the forward window?
    label(t) = 1 if ANY tradeable OTM option did
```

Consequences:

1. **No ATR multiplier to choose.** The threshold is the payoff multiple itself, which you
   already care about. `k` disappears from the design.
2. **The tautology trap (D-01) dissolves.** That trap requires asking "will *this contract*
   go 25x" while feeding the model that contract's own premium/DTE. This label is one value
   per underlying per timestamp — "was a 25x available" — so no per-contract features exist
   at prediction time and the degenerate "buy the cheapest thing" answer isn't reachable.
   Contract choice moves entirely to stage 3 (D-02), which is arithmetic.
3. **The tradeability filter becomes load-bearing, not optional.** Without it, "any option"
   is satisfied by untradeable lottery tickets and the model learns to predict fiction.
   See D-13.
4. **Volatility enters naturally** rather than as an imposed normalizer — the move required
   for 25x is already a function of prevailing volatility and time remaining, because it is
   read off the actual chain.

**D-26 · DECIDED — spot triple-barrier is demoted to cross-check.** `label_scan.js` and the
spot-based scan remain valuable but no longer define success:
- spot history is longer and cleaner than option history → better for the **veto** model,
  which needs abundant "ordinary day" negatives (D-03)
- gives an independent sanity check: do payoff-labelled positives coincide with
  spot-labelled one-way moves? Large disagreement means one of the two is wrong
- the `unarmed` / `returned` / `held` three-bucket structure (§2.1) is still the right shape
  for the veto task

The `ATR_short / ATR_slow` compression ratio survives as a **feature** (§5.3), which was
always its better use.

### 2.4 Random-walk null baseline

**D-12 · DECIDED.** Positive episode count alone is **not** evidence of learnable structure.
Smoke-testing `label_scan.js` on a synthetic random walk produced hundreds of "large M,
never returned" episodes — that's the geometry of a driftless walk over 48 bars, not signal.

Required companion measurement: run the identical scan on the real series with **returns
shuffled** (destroys temporal structure, preserves return distribution).

- real 220 vs shuffled 190 → label mostly measures random-walk geometry; little to learn
- real 220 vs shuffled 60 → genuine clustering; label has teeth

To be added as a `--shuffle` flag after the first real-data counts land.

### 2.5 Tradeability filter

**D-13 · PROPOSED.** "Did *any* OTM option go 25x" can be satisfied by the most extreme
lottery ticket on the board — no bid, no volume, 100% spread. That trains the model to
predict outcomes that were never executable.

Filter at signal time: non-zero volume, premium above a floor, and (when available)
bid-ask spread below a ceiling. Exact thresholds `OPEN` — set from the real chain data.

### 2.6 Combined-timeframe decision

**D-14 · DECIDED (your call).** Do **not** split into separate same-session / multi-session
systems. You have observed the same pattern combination (green_stairs, red_squeeze,
otm_wall) across all success cases at all timeframes. Model it as one system with
timeframe/DTE as features rather than as separate models.

Consequence: DTE and horizon must be *features*, and validation must ensure no single
timeframe dominates the training set.

---

## 3. Effective sample size — the gating question

### 3.1 Rows ≠ events

**D-15 · DECIDED.** Sample size is counted in **independent events**, never in rows.

You have ~35GB now (~100GB projected) for crypto, 2.5 years, 5/15-min candles. That is a
very large number of rows and a very small number of events. One multibagger move
generates:

```
~288 rows (5-min bars in the preceding day)
  × ~200 OTM strikes that all paid off in the same move
  × live expiries
= tens of thousands of labelled rows for ONE event
```

Estimated genuine multibagger-producing moves: ~20–60 per symbol per year → roughly 100
across BTC+ETH over 2.5 years. Likely **under 200 positive episodes**.

**This is firmly gradient-boosted-tree territory and below deep-learning territory.**

### 3.2 Where sample size actually grows

Not from finer candles — that resamples the same events. It grows from **cross-sectional
breadth**: more symbols with genuinely independent moves. The 20,000 Indian stocks plan is
real breadth. Additional Delta pairs (SOL, DOGE, LINK...) are the crypto equivalent.

### 3.3 Correction to STATE.md 2.3

STATE.md says no pretrained foundation model exists for financial time series. That was
true of the framing but is now outdated: Chronos, Moirai, TimesFM and Lag-Llama exist and
are pretrained on large time-series corpora. **However** — they are trained mostly on
electricity demand, traffic, weather and retail sales: seasonal, high signal-to-noise.
Financial returns are the opposite. Transfer to crypto price action is unproven and I'd
expect little. They do **not** rescue the small-sample argument.

*(Unverified — no web search in this session. Worth checking current state of these models.)*

---

### 3.4 Base rate — from your own observation

**D-29 · DECIDED.** Recovered from the prior conversation (not in STATE.md). Three
positional market modes, daily timeframe, your estimates:

| Mode | Description | Frequency | Who profits |
|---|---|---|---|
| 1 | one side melts, other goes sideways | **50–60%** | big capital averaging on the sideways side — 5x achievable |
| 2 | both sides melt | 30–40% | option sellers; very bad for buyers |
| 3 | one side melts, other gives a multibagger | **5–10%, and getting rarer** | the target of this project |

This is the most useful number recovered. Mode 3 at 5–10% means roughly **one expiry in
fifteen** contains the setup. That is the prior any model must beat, and it directly
constrains the achievable precision/recall trade-off (§6, D-23).

**D-30 · PROPOSED — make mode 1 the first ML target, before the multibagger.**

Rationale: mode 1 has ~10x the base rate of mode 3, uses the same features, and you
identified it yourself as where most option-buying money actually is ("Great opportunity to
5x big capital"). It gives a model that can be validated on hundreds of episodes instead of
tens, and a working mode-1 classifier is directly tradeable while the mode-3 work continues.

Sequencing consequence: mode classification (1/2/3) becomes the first supervised task. The
multibagger trigger is then a refinement *within* mode 3, not a needle-in-haystack search
across everything.

---

## 4. Model selection — ranked

Criteria, in your stated priority: correctness first, then time efficiency, simplicity,
compute.

| # | Approach | Train time | Verdict |
|---|---|---|---|
| **1** | **LightGBM** (gradient-boosted trees) | seconds–minutes, CPU | **Primary.** Tabular after feature extraction; no scaling needed; tolerates missing values; ignores irrelevant features; SHAP answers the response-surface question (STATE 2.4.A) directly |
| 2 | CatBoost / XGBoost | seconds–minutes, CPU | Near-equivalent. CatBoost better on categoricals; worth a comparison run, not a substitute |
| 3 | Regularized logistic regression (L1/L2) | < 1 second | **Mandatory baseline.** If LightGBM can't beat this, the features are the problem, not the model. Sometimes wins outright at this sample size |
| 4 | Random Forest | seconds | Robust sanity check; less prone to overfit than boosting, usually slightly worse |
| 5 | Small 1D CNN over candle windows | minutes, CPU/GPU | Only justified for the chain-as-2D-grid idea (STATE 2.4.C). Blocked behind sample-size count |
| 6 | LSTM / GRU | minutes–hours | Sample-hungry, hard to regularize at this scale. Probably not |
| 7 | Transformer | hours, GPU | No. DLinear result plus your sample size makes this indefensible |
| 8 | TS foundation models (Chronos etc.) | fine-tune, GPU | No — domain mismatch, §3.3 |
| 9 | Reinforcement learning | very long | No. Most sample-hungry family; overfits backtest simulators badly |

**D-16 · DECIDED.** LightGBM primary, logistic regression as mandatory baseline. Revisit
CNN only if (a) episode count exceeds a few hundred **and** (b) chain-shape input is built.

**D-17 · DECIDED.** Model choice is ~10% of the outcome. Label quality, feature quality and
validation discipline are the other 90%. A LightGBM on good labels with purged walk-forward
validation beats a transformer on sloppy labels every time — and is debuggable.

### 4.1 Compute at scale

10TB is never loaded into a model. Feature extraction is a **streaming** job (read symbol →
compute features → write Parquet shard → discard). The resulting matrix is
`events × features`; even 5M rows × 150 float32 ≈ 3GB, comfortably in RAM. LightGBM trains
that in minutes on CPU; inference is microseconds per row.

**D-18 · DECIDED.** Convert raw JSON to partitioned Parquet, query via DuckDB. Unglamorous,
and it determines whether the project survives — hour-long iteration cycles kill projects.

---

## 5. Features

**D-28 · DECIDED — working constraint.** Every deliverable is **runnable code** with the
reasoning in comments. No step in the build path requires deriving or manipulating maths by
hand. Where formulas appear in this document (e.g. standardized moneyness in §5.2) they are
notes-to-self for implementation, not prerequisites — they arrive as functions.

**D-19 · DECIDED — three hard rules.**

1. **No raw prices, ever.** BTC at 30k and 100k are different worlds; a tree will split on
   `price < 45000` and learn rules valid only in 2023. Everything scale-free: log returns,
   ATR-normalized distances, ratios.
2. **No lookahead.** Every feature at bar `i` uses only bars ≤ `i`. ATR included.
3. **Structural features only** (your instruction) — the *shape* of the pattern, not tuning
   thresholds. Feed the machine the measurement, let it find the threshold.

### 5.1 What I understand as the structural features from your docs

From `03-signals.md` / STATE.md, the four existing signals: `red_squeeze`,
`otm_red_squeeze`, `green_stairs`, `otm_wall`, plus `universeMaxRatio` and the
`priceVolatility` compression measure.

**D-20 · DECIDED.** These enter as features, not as gates. The first honest ML question is
their *conditional* edge: does `green_stairs` firing actually shift the move-size
distribution, and by how much, under which volatility regime? Convert each from boolean to
continuous where possible — a graded score carries far more information than a flag.

Your two observed premium dynamics, currently unmeasured and worth adding as explicit
features:

- **Rush-to-zero** (STATE 2.1.A): premium *accelerating* toward zero faster than theta
  explains → real selling pressure, capitulation. Measure as the residual of actual premium
  decay against theoretical theta decay.
- **Compression**: premium *holding* while range narrows (coiling). Distinct from the
  above; currently conflated in `otm_wall`/`priceVolatility`.

These are two different precursor signatures and should be two different features.

### 5.2 Your proposed list, with corrections

| You proposed | Verdict |
|---|---|
| Expiry time left (DTE) | Keep. Add `log(DTE)` and `√DTE` — theta effects are nonlinear |
| Moneyness | **Change form** → `log(K/S) / (σ√T)` (standardized moneyness). Raw "5% OTM" is meaningless alone: 5% OTM at 6h and at 30d are unrelated trades. This one transform encodes your whole "deep OTM *with respect to* DTE/vol/spot" intuition as a single number |
| Spot price | **Drop as raw.** Non-stationary — see D-19.1 |
| Past N spot candles | Keep, but normalized: each candle's O/H/L/C expressed as ATR-units from the window's close |
| Past N option candles | Keep, same normalization. Also premium as multiple of its own trailing median |
| green_stairs / red_squeeze / otm_wall | Keep as continuous scores — D-20 |
| Computed volatility | Keep, several forms — below |

### 5.3 Features to add

**Volatility & regime**
- `ATR_short / ATR_slow` — the compression ratio; central to D-11
- Realized vol over multiple windows (6/24/72/168 bars) and their ratios
- Realized vol percentile rank vs trailing 90 days
- Time since last large move (regime memory / breakout fatigue — the very thing that made
  you hesitate)
- Autocorrelation of recent returns (trending vs mean-reverting regime)

**Price structure**
- Range position: where `close` sits in the recent N-bar range, 0–1
- Distance to nearest recent swing high/low, in ATR units
- Consecutive same-direction run length (the general form of `green_stairs`)
- Candle body / total range ratio; upper and lower wick ratios (all ATR-normalized)
- MA convergence: spread between fast/slow MAs in ATR units, and its rate of change
  (you've flagged MA convergence as preceding long trends)

**Volume**
- Volume vs trailing median
- Volume trend over last N bars
- Volume-weighted vs simple price divergence

**Chain shape — fills part of the IV gap**
- **Skew proxy:** slope of `log(premium)` vs strike across the OTM chain. This carries much
  of what IV skew would tell you and needs **no IV data**. You already have the premiums;
  this information is currently unused. Recommended as the highest-value addition.
- Curvature (2nd-order fit) of the same — smile shape proxy
- Call-side vs put-side premium ratio at matched standardized moneyness (directional
  positioning proxy)
- Count of OTM strikes with premium below a floor (chain thinness)
- Total OTM premium as fraction of spot (aggregate priced-in move)

**Cross-sectional**
- BTC/ETH realized correlation, and whether ETH is leading
- Same-day dispersion across available symbols

### 5.4 The strike × time grid — build early, three uses

**D-27 · DECIDED.** Build the premium grid (strikes on one axis, time on the other, premium
as the cell value) as a **data structure**, early, independent of model choice. STATE 2.4.C
filed this as a speculative NN-only extension; that undersold it. It earns its place three
ways:

1. **Tree features (available immediately).** Flatten the grid into summary numbers: slope
   of premium across strikes, curvature, and how both are changing over recent bars. This
   *is* the skew proxy of §5.3, and it is the highest-value feature addition available
   without IV data.
2. **CNN input (option kept open).** If the episode count later justifies a small 1D/2D CNN
   (§4 row 5), the raw grid is exactly the required input format. Building it now avoids a
   rewrite.
3. **Visual verification (matters to you specifically).** The grid renders directly as a
   heatmap. You can look at it and check whether `otm_wall` and the rush-to-zero signature
   appear as recognisable shapes — consistent with your requirement that signals be
   visually verifiable before manual execution.

Grid axes use **standardized** moneyness, not raw strikes, so grids are comparable across
spot levels, expiries and volatility regimes.

**Reconciliation with the cube you already built.** In the prior conversation you designed a
strikes × expiries × time cube with cells coloured by instrument count, then correctly
collapsed the strike axis: *"One strike would fire only once, so why the shades?"* That
reasoning is right **for boolean signal firing** and it shipped as the expiry × time tables
in `serve_grids.js`.

It does **not** apply to premium. Premium is continuous — every cell carries a real value.
Putting **premium** in the cells instead of signal counts restores the strike axis with full
information: the shape of the chain, and how that shape evolves. Same viewer you already
built, different cell value. This is the cheapest high-value item in the whole spec.

### 5.5 Structure only — ML supplies the tuning

**D-41 · DECIDED (your standing instruction, reiterated).** Only the **structural** definition
of each signal is fixed by hand. Every tuning threshold is left to the model.

The repo already implements this: `patterns.js` applies structural rules only and passes
`minSignalValue: 0`, so tuning moved to query time. No architectural change needed — the
decision is now recorded rather than implicit.

**What the model actually returns.** Feeding `ratio1`/`ratio2` as features does not yield
"the ideal threshold is 23." LightGBM learns a **conditional** boundary — in effect
"`ratio1 > 12` matters when `tteHours < 10`, but you need `> 40` when `tteHours > 200`."
That is strictly more expressive than a constant and is what a hand-tuned threshold
structurally cannot represent.

If a single constant is still wanted for `config.js`, SHAP partial dependence gives the
success-rate-vs-value curve per feature and the inflection is read off it. Both outputs are
available; the conditional form is the real gain.

**D-42 · DECIDED — prune the derived parameters, and expect most to be inert.** Your
assessment that the ~40 derived fields may not be useful is likely correct. Most are the same
three or four quantities re-expressed (`ratio1 = firstBody/lastBody`,
`cheapness = spot/avgPrice`, …). Collinear features dilute tree splits and obscure SHAP.
Permutation importance identifies the dead ones; they get dropped.

**D-43 · DECIDED — weight the feature set toward context, not pattern shape.** Following your
own reasoning: in real multibaggers you observed *the structure*, and kept tuning
heuristically. If structure is what carries the information, there may be little left to rank
*within* the set of structural matches — and the flat 15/15/16/17/17% matrix is evidence
**for** that view, not against it. The score may fail to rank not because the formula is
poor but because the pattern is close to binary and the remaining variance lives elsewhere.

Design consequence: prioritise **context** features — `tteHours`, `distancePct`, `duration`,
volatility regime, market mode (D-29), spot-side structure — over additional pattern-shape
statistics. `08-open-questions.md` §4 reached this independently ("What ML is genuinely good
for here: context").

### 5.6 Domain phase model — recovered, use as feature scaffolding

**D-31 · DECIDED.** Four-phase cycle, from the prior conversation. Features should be
designed to locate which phase an instrument is in, since entry is the 2→3 transition and
exit is 3→4.

| Phase | Signature |
|---|---|
| 1 — Equilibrium / accumulation | MA convergence on underlying; Type 1 or Type 2 premium calm; candle ranges contracting. **The compression phase** |
| 2 — Breakout initiation | MA divergence beginning; first clean directional candle breaking the compression range; premium parabola beginning |
| 3 — Trend continuation | staircase on underlying; nested parabolas in premium; gamma walls approached sequentially |
| 4 — Exhaustion | premium parabola steepening unsustainably; staircase failing to make new highs; price into a thick gamma wall. **Where 1:5 stays 1:5 instead of becoming 1:10** |

**Two distinct types of pre-breakout calm** (D-32 · DECIDED — must be separate features,
currently conflated):

- **Type 1** — premium flat or declining slowly *despite significant DTE remaining*; IV rank
  falling gradually; underlying range contracting. Premium is being *held*.
- **Type 2** — premium near zero (< ~0.5% of spot); DTE < 5; underlying moving away from the
  strike for multiple sessions; candle bodies near zero. Premium has been *eaten*.

Type 2 followed by a clean breakout candle is the maximum-asymmetry multibagger setup — and
also the one where most instances simply expire worthless. Distinguishing Type 2 setups that
begin an upward parabola from those that stay flat into expiry is a core model task.

**D-33 · DECIDED — rush-to-zero correction.** Your later observation supersedes the smooth
model: in large crypto trends/reversals it is often **not** smooth decay followed by
expansion, but a *rush* (accelerating expansion) toward zero premium, immediately followed by
expansion upward. Feature: residual of actual premium decay against theoretical theta decay —
decay significantly *faster* than theta explains indicates capitulation, not time passing.

**D-34 · DECIDED — parabola quality surface.** Parabola detection is a multi-resolution
problem: the parabola exists at whichever timeframe optimises signal-to-noise for that
expiry's move characteristics. Do not fix a timeframe. For each instrument × expiry, fit a
degree-2 polynomial across candidate timeframes × rolling windows and output a **matrix of
fit quality** rather than a boolean.

Per-cell metrics: R² of the quadratic fit; sign and magnitude of the second-derivative
coefficient (direction and sharpness); residual behaviour (small/random = intact parabola,
large/systematic = being interrupted — this is the computational form of your "abrupt move
returns to the parabola vs breaks away" observation); recency-weighted fit (weighted least
squares) to distinguish a *newly forming* parabola from a *breaking down* one.

**D-35 · DECIDED — minimum timeframe is hourly.** Your observation: these moves show
themselves in advance only on higher timeframes (hourly minimum). Sub-hourly candles are for
execution refinement, not for the precursor signal.

**D-36 · DECIDED — premium exhaustion heuristic needs its scale fix.** Your formula
`sqrt(1 + DTE) · candle_length / candle_open²` breaks for deep OTM options with very small
open (e.g. 0.03), which is precisely the population of interest. It enters the feature set
only in scale-invariant form. Delivered as code (D-28).

**Calendar**
- Session (Asia / EU / US) — crypto has real session structure
- Day of week; hours-to-expiry as a nonlinear encoding (not just linear DTE)

### 5.7 The IV/OI gap — ticking clock

**D-21 · DECIDED, ACTION REQUIRED.** Pipeline stores OHLCV only: no IV, no OI, no Greeks.
Two contracts at identical price can be in opposite IV states and the data can't tell them
apart.

Every day without capture is unrecoverable history. **Check whether Delta's API serves
historical IV; if not, start capturing live immediately** regardless of other priorities.
This is the one item with a ticking-clock cost. The §5.3 skew proxy mitigates but does not
replace it.

---

## 6. Validation

**D-22 · DECIDED.** Purged walk-forward validation with embargo. Never random splits.

Random k-fold puts the same event in train and test (see §3.1) and will report
spectacular, entirely fake performance. Purging removes training samples whose label window
overlaps the test period; the embargo adds a gap after each test fold. The existing query
tool already does walk-forward with purging at fold boundaries — reuse that logic.

**D-23 · DECIDED — metrics.** Not accuracy, not AUC. Both mislead badly on imbalanced,
convex payoffs.

- **Precision at low recall** — of setups flagged, what fraction worked. This is how you get
  the "high correctness" you want in an achievable form: catching 15% of moves at 70%
  precision is an excellent system; chasing 90% recall drags precision to noise
- **Calibration** — when it says 30%, does it happen ~30% of the time? Plot reliability curves
- **Expectancy after costs** — the only number that finally matters
- Report AUC only as a secondary sanity check

**D-24 · DECIDED.** Report performance per volatility regime, not just in aggregate. A model
that works only in high-vol regimes is useful *if you know that*, and dangerous if you don't.

---

## 7. Build order — REVISED after reading the repo

**Context change (v0.3).** Most of what earlier versions of this spec designed already
exists in `de_signals_on_fly`:

- `patterns.js` stores one row per instrument, unmerged, structural-only at
  `minSignalValue: 0`, ~30 fields (`tteHours`, `distancePct`, `cheapness`, `seqLength`,
  `ratio1/2`, `logJump`, `equalSteps`, `univRatio`, `state`, `peakAfter`, …).
  **This is the ML feature table.** Not a precursor to one.
- `multibaggers.js` computes signal-independent ground truth:
  `peakRatio = max over i of (max(high[i+1..end]) / close[i])` on the finest duration.
  **This is the label source** (supersedes D-25's bespoke labeller).
- Purged walk-forward folds already exist in the query tool.

**D-38 · DECIDED — `label_scan.js` is retired.** Written before the repo was read; duplicates
`multibaggers.js` with a weaker spot-proxy label. Two components survive and move into the
join script (step 3): **episode collapsing** and **gap/censoring exclusion**. Neither exists
in the pipeline today; both are required.

| # | Step | Owner | Notes |
|---|---|---|---|
| 0 | Real backfill | Tejas | **DONE** — real hit rates confirmed, slightly better than the synthetic estimates |
| 1 | `node multibaggers.js` | Tejas | ground truth; yields the real base rate and, critically, the **event count** |
| 1b | **Random-entry null baseline** (D-40) | Tejas + me | the highest-information missing number — see below |
| 2 | `node patterns.js` | Tejas | structural-only feature table |
| 3 | **Join script**: patterns × multibaggers → labelled dataset | me | the one genuine code gap; carries episode collapsing + censoring |
| 4 | Episode count report | me | independent events, not rows — the ML feasibility gate |
| 5 | Logistic baseline → LightGBM, purged walk-forward | me | if LightGBM can't beat logistic, features are the problem |
| 6 | SHAP + permutation importance | me | answers "which parameters don't matter" directly (D-37) |
| 7 | Mode classifier (modes 1/2/3) | me | ~10x base rate of mode 3 (D-30) |
| 8 | Trigger model within mode 3 | me | precision-tuned, low recall by design |
| 9 | Contract selection | me | arithmetic, no ML (D-02 stage 3) |

Steps 3–6 are roughly a day's work. Step 5 runs in under a minute.

### 7.1 The event count, not the hit rate

**D-39 · DECIDED.** The real hit rates are now confirmed and broadly match the synthetic
estimates. That validates the *rate* — it does not supply the number that gates ML.

A 20% hit rate is identical whether it is 20 of 100 events or 2,000 of 10,000. Only the
second is trainable. **Effective sample size is the count of independent events**, and it is
still unmeasured. Step 4 produces it.

### 7.2 Random-entry null baseline — highest-value missing number

**D-40 · DECIDED, DO FIRST.** Deep OTM options near expiry are convex lottery tickets; some
fraction reach 10x regardless of any pattern. Without a null baseline, a 20% hit rate cannot
be distinguished from the unconditional base rate of the instrument class.

```
sample random entry timestamps from the SAME population the signals fire on
    (same OTM filter, same tteHours band, same durations, same expiries)
compute the same forward ratio (multibaggers.js already does this scan)
compare the full distribution, not just the mean
```

- signals ≫ random → the ML work is refinement of something real
- signals ≈ random → the signal selects nothing, and every project number to date measures
  instrument-class convexity rather than edge

Cheap to compute, and it reframes the target: "improve 20% → 32%" only means something
relative to what random gives.

**Note.** Real and synthetic hit rates coming out similar is mildly informative here —
synthetic data contains no genuine predictive structure, so similar performance on both is
consistent with the signal tracking a base rate rather than selecting against it. Not
conclusive, but it raises the priority of this measurement.

Each step is independently verifiable. Do not skip ahead — later steps are meaningless
without earlier numbers.

| # | Step | Output | Blocked by |
|---|---|---|---|
| 0 | **Run `label_scan.js`** on real BTC/ETH spot | episode counts, T×M matrix | nothing — data is on disk |
| 1 | **Shuffled-returns null baseline** (D-12) | real vs shuffled episode counts | step 0 |
| 2 | **Decide DL-vs-trees for real** | go/no-go on §4 row 5+ | steps 0–1 |
| 3 | **Parquet + DuckDB conversion** (D-18) | fast queryable store | nothing; do in parallel |
| 4 | **Feature extraction pass** (§5) | `events × features` Parquet matrix | step 3 |
| 5 | **Logistic regression baseline** (D-16) | first honest performance number | step 4 |
| 6 | **LightGBM veto model** (D-03) | "is today ordinary" classifier | step 5 |
| 6b | **Mode classifier** (D-30) — modes 1/2/3 | tradeable mode-1 signal; ~10x base rate of mode 3 | step 5 |
| 7 | **SHAP / permutation importance** | which features matter, which are inert | step 6 |
| 8 | **LightGBM trigger model**, precision-tuned | low-recall high-precision signal, within mode 3 | steps 6–7 |
| 9 | **Contract selection optimizer** (D-02 stage 3) | strike picks from spot forecast | step 8 |
| 10 | **Paper-trade forward** | live calibration, no capital | step 9 |

**D-37 · DECIDED — step 7 is a stated requirement, not an optional extra.** Your own framing:
*"a distribution of success percentage vs ranges of the values… it should tell parameters which
are not useful, i.e. variation in those would not affect the success percentage much."*

That is exactly what SHAP values and permutation importance produce, and they come free from a
fitted LightGBM. Permutation importance near zero = the parameter is inert and can be dropped.
SHAP partial-dependence gives the success-rate-vs-value-range curve per feature. This also
answers STATE 2.4.A and replaces the manual query-sweep approach with a direct measurement.

**Step sequencing is deliberate.** Every step returns a *number that redirects the work*,
not a pass/fail verdict on the project. Steps 0, 1 and 5 each run in seconds to minutes. A
weak result at step 5 is information about feature construction — it does not invalidate the
observations that generated the features, several of which (three modes, rush-to-zero, Type 1
vs Type 2) are non-obvious and independently useful.

Steps 0–2 are cheap, need no new infrastructure, and gate everything. Step 5 is where you
learn whether this project has an edge at all.

**Runtime expectations:** step 5 under a second. Step 6 seconds to a couple of minutes.
Step 7 minutes. All CPU, all laptop. If anything takes hours, something is wrong.

---

### 7.3 Arm 4 — Brooks-derived features

**D-44 · DECIDED.** Al Brooks' price-action framework enters as **arm 4**, not as a
standalone rule-based system. Hand-coding his guidelines as if-then rules would reproduce
the `red_squeeze` problem exactly: hand-picked thresholds with no way to know whether they
rank anything. Instead his concepts become computed features and LightGBM supplies the
thresholds — D-41 applied to an external source of domain knowledge.

Full specification in `BROOKS_FEATURES.md`. Summary: ~90–120 mechanical spot features
across bar shape, bar-to-bar relationships, swing structure, the trend↔range continuum, and
breakout/follow-through. Explicitly **not** mechanized: always-in, second entries, measured
moves, trend-vs-channel as a verdict — Brooks resists these himself and forcing them would
inject the hand-tuned judgment D-41 excludes.

**Convergence worth recording.** Brooks' **shrinking stairs** — "three or more trending
highs where each breakout to a new extreme is by fewer ticks than the prior breakout,
indicating waning momentum" — is structurally `red_squeeze`, derived independently from spot
charts, and the direct inverse of `green_stairs`. Not proof the signals work, but the first
external corroboration that the *structure* is one experienced traders converge on.

Brooks is spot-only, which is an advantage rather than a limitation: per §1.2 the spot move
is where the learnable signal lives, and the spot side of the current feature set is thin.

---

## 8. Open items

| ID | Item | Needs |
|---|---|---|
| O-01 | Positive episode count, real data | run step 0 |
| O-02 | Real-vs-shuffled ratio | run step 1 |
| O-03 | Tradeability thresholds (D-13) | real chain data |
| O-04 | `k`, `N`, "large M" values | sweep in step 0, don't pre-choose |
| O-05 | Does Delta serve historical IV? (D-21) | API check — **urgent** |
| O-06 | Merged-event ratio uses `max` across strikes (optimistic) | undecided, from STATE §1 |
| O-07 | No real backfill has ever been run on the non-ML pipeline | every existing number is from synthetic fixtures |

**O-07 is worth restating:** per STATE.md §1, the 20%-reaching-10x figure and the
15/15/16/17/17% strength matrix came from synthetic test fixtures, not real history. None
of those numbers should be trusted or cited until a real backfill runs.

---

## 9. Notes on the field

Asked directly, so recorded here.

**On sellers of AI trading systems.** A model with real edge has limited capacity, and
selling it consumes that capacity — so the incentive to sell is strongest exactly where the
edge is weakest. That's adverse selection and it explains most of what's visible on social
media.

The nuance: legitimate published research does exist, because academic work rarely contains
deployable alpha, and because some techniques have no capacity limit and are safe to share.
The dividing line isn't public vs private — it's **method vs signal**. Methods get
published (validation methodology, feature engineering practice, Lopez de Prado's writing).
Signals don't.

**On "ML has no emotions."** A model's structural equivalents of emotion are overfitting
(seeing a setup that isn't there) and retraining-after-drawdown (which reintroduces emotion
through the operator). It is unemotional only if left alone. Retraining discipline is
therefore part of the system design, not an afterthought.

**On "50 data instances might be enough" (Jeremy Howard).** The claim is true, but it is
specifically about **transfer learning** — fine-tuning a backbone already pretrained on
millions of images or documents, which has learned the feature representations. The 50
examples only steer an existing representation; they don't build one.

No equivalent pretrained backbone exists for financial time series (§3.3). Training from
scratch, 50 instances is nowhere near sufficient. The quote is being applied outside the
conditions that make it true. This does not change the conclusion in §4.

**Citations flagged as unverified** (no web search this session — please check before
relying on any of these):
- Grinsztajn, Oyallon & Varoquaux, "Why do tree-based models still outperform deep learning
  on typical tabular data?", NeurIPS 2022 Datasets & Benchmarks
- Zeng et al., "Are Transformers Effective for Time Series Forecasting?", AAAI 2023 (DLinear)
- Chronos / Moirai / TimesFM / Lag-Llama as current TS foundation models

---

## 10. Changelog

**v0.1** — first consolidation. Captures D-01 through D-24, ranked model list, feature
spec, build order. Carries forward STATE.md §2 decisions (veto reframe, triple-barrier
labelling, sample-size gating) and adds: episode collapsing, direction split, arm/return
two-threshold logic, censoring and gap handling, random-walk null baseline, tradeability
filter, standardized moneyness, premium-derived skew proxy, rows-vs-events distinction,
foundation-model correction.

**v0.4** — added §0 PLAN as the live TODO (replaces scrolling the conversation). Added arm 4
and `BROOKS_FEATURES.md` (D-44). Reframed the work as **one pipeline with four/five swappable
feature sets**, not five approaches — training remains seconds to minutes; the branching is in
feature design, not compute.

**v0.3** — after reading `github.com/tejasd90/de_signals_on_fly`. Rewrote the build order
around what already exists (§7): `patterns.js` IS the feature table, `multibaggers.js` IS the
label source, purged walk-forward already implemented. Retired `label_scan.js` (D-38),
salvaging episode collapsing and censoring into the join script. Separated event count from
hit rate (D-39). Added the random-entry null baseline as the top-priority measurement (D-40).
Recorded structure-only/ML-tunes-thresholds as an explicit decision (D-41), with pruning of
derived parameters (D-42) and a context-weighted feature set (D-43).

Signal definitions are now **verified from source**, not provisional: `red_squeeze`,
`otm_red_squeeze`, `green_stairs`, `otm_wall` all exist in `signals/` and are documented in
`../03-signals.md`. The earlier note that `otm_wall`/`green_stairs` were undefined is
withdrawn.

Doc inconsistency found: `03-signals.md` states `OTM_SIGNAL_THRESHOLD` was lowered to 1000;
`08-open-questions.md` still describes it as 10000.

**v0.2** — after parsing the full prior conversation export (170 user / 174 assistant
messages). Superseded D-11 with payoff-derived labelling (D-25); demoted spot triple-barrier
to cross-check (D-26); promoted the strike × time grid to an early deliverable and reconciled
it with the cube viewer already built (D-27); added the no-maths working constraint (D-28);
recovered and added the three market modes and base rate (D-29), mode-1-first sequencing
(D-30), the four-phase model (D-31), Type 1 vs Type 2 calm (D-32), rush-to-zero (D-33),
parabola quality surface (D-34), hourly minimum timeframe (D-35), premium exhaustion scale
fix (D-36), SHAP as stated requirement (D-37); added the Howard transfer-learning correction.

**Correction logged:** only `red_squeeze` is defined in the recovered conversation.
"Staircase" appears there as a *spot* signal in the older Indian F&O code. `otm_wall` and
`green_stairs` do not appear at all and post-date that transcript. Their definitions are
currently **unverified** — treat any spec statement about them as provisional until the repo
code is read.

**Awaiting your decision:**
- **`08-open-questions.md` §3** (your own doc, marked AWAITING YOU, still unanswered) —
  merged events take the max ratio across members. This assumes you always pick the best
  strike on seeing an alert. It sits underneath every number the project has produced and it
  **defines the label**, so it must be settled before training. Alternatives:
  nearest-the-money, or the mean across members.
- **D-30** — mode 1 as first ML target, ahead of the multibagger
- **D-13** — tradeability floor (min volume, min premium)

**Recommended next action:** run the random-entry null baseline (D-40). It is cheap, uses
the existing `multibaggers.js` scan, and either validates the whole signal stack or redirects
it — before any model is built on top.
