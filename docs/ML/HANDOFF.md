# HANDOFF — multibagger options ML

Read this first. It carries the reasoning behind decisions that look arbitrary
in the code, and the traps that have already cost real time.

Companion docs: `ML_SPEC.md` (43 numbered decisions), `BROOKS_FEATURES.md`,
`../RUNBOOK.md`. Repo: `github.com/tejasd90/de_signals_on_fly`.

---

## 1. What the project is

Find, from historical option candles, what precedes a deep-OTM option returning
25x/50x/100x — and turn that into a screen Tejas reviews manually before
executing. Crypto first (Delta Exchange India: BTC, ETH, XAUT), Indian F&O later.

Two pipelines exist:

| pipeline | input | purpose |
|---|---|---|
| **patterns** | `data/patterns/` from `patterns.js` | tests the four hand-built signals |
| **discovery** | raw `data/candles/` | signal-free; mechanical features + chain surface |

Scripts: `step1_prepare.py` → `step2_baseline.py` → `step3_tune.py` for patterns;
`discover_build.py` → `step2` → `step3` for discovery. Plus `make_random.py`
(null baseline) and `gaps.py` (waiting-time distribution).

---

## 2. Findings so far — do not re-derive these

### 2.1 The four hand-built signals

Measured on real data, per signal, weighted, out-of-sample:

| signal | Q1 → Q5 25x rate | verdict |
|---|---|---|
| green_stairs | 0.19% → 2.82% | ranks well |
| otm_red_squeeze | 0.53% → 2.92% | ranks well |
| red_squeeze | 0.72% → 1.28% | weak |
| otm_wall | 1.68% → 1.35% | **ranks nothing**, and it is 39% of all rows |

**But** — `signalValue` for the three OTM signals is literally
`spot / mean(pattern lows)`, i.e. **cheapness**. Confirmed in
`signals/otm_common.js`. So that ranking measures how cheap the option is, not
the pattern shape.

Every pattern-shape feature (`ratio1`, `ratio2`, `seqLength`, `equalSteps`) came
back **inert** under permutation importance, in all four signals. Shuffling them
does not hurt the model.

**What predicts instead:** `cheapness`, `distancePct`, `tteHours`. All of these
are *which contract you buy*, not *when*. Contract selection appears to be the
edge; timing has not yet shown any.

Caveat worth keeping: inert means *that encoding* carries nothing. `ratio1` is a
raw body ratio; Brooks measures the same idea in ATR units. The discovery
pipeline exists to test whether a better encoding changes the answer.

### 2.2 Real base rates (patterns dataset, unfiltered)

5x 10.9% · 10x 4.4% · 25x 1.3% · 50x 0.5% · 100x 0.2%

Best out-of-sample precision achieved: ~4.7% at 15% recall against a 1.28% base
rate. About 4x lift. Unglamorous and probably real.

### 2.3 Discovery dataset (built, ready)

8.5M rows, 141,153 instruments, 1,973 episodes. Positive episodes: 1,919 at 5x,
1,635 at 10x, 1,021 at 25x, 605 at 50x, 314 at 100x. Comfortably trainable at
every target.

**Open question, never yet answered:** does the `surface` arm beat `context`?
That is the one hypothesis in this project that has never had a number attached
to it. Run `step3_tune.py --data disc_final --target {10,25,100}` and compare.

### 2.4 Still missing

- **The random-entry null baseline.** `make_random.py` is written and tested but
  has not been run. Everything above is *relative* ranking within signal-fired
  rows. Nothing yet shows the signals beat buying a random cheap OTM contract at
  the same moment. This is the decisive number.
- IV and OI are not stored anywhere. Ticking clock — every day uncaptured is
  unrecoverable. `surf_skew_slope` is a partial substitute.

---

## 3. Traps — every one of these has already bitten

### 3.1 The label is `ratio`, NOT `peakAfter`

From `query_lang.js`:

```
ratio     : 'Peak high after entry / entry close'      <- the MULTIPLE
peakAfter : 'Highest price after the signal candle'    <- an absolute PRICE
```

Using `peakAfter >= 25` asks "did the price reach Rs.25", which a Rs.250 option
satisfies at entry and a Rs.0.06 option never can. It produces a hit rate that
climbs monotonically with premium and measures nothing. Cost: two full runs.

### 3.2 Episodes are keyed on the UNDERLYING, not the contract

In patterns rows, `symbol` is the option contract and `spot` is the underlying.
Grouping on `symbol` treats twenty strikes firing on one BTC move as twenty
independent events. Measured inflation: **6,920x** on real data.

Episodes are fixed time buckets per underlying, **not** gaps in firing. Gap-based
grouping assumed sparse firing; with ~200 instruments across many live expiries
signals fire continuously, so no 24h silence ever occurs and everything collapsed
into **4 episodes** across the whole dataset.

Episodes are the unit of independence for CV folds. Rows are what trains.
Effective sample size sits between the two.

### 3.3 Never mix candle durations in a window function

Another tool built the label as
`LEAD(close_opt, 24) OVER (PARTITION BY symbol ORDER BY timestamp)` with three
durations in one table. A daily candle's close is the price 24h later; an hourly
candle's close at the same timestamp is the price 1h later. LEAD then picks up
prices from *before* the daily close — the label reads backwards in time.

Result: 100% hit rate at 2x and 5x, 99.84% at 10x, and 100% of the top slice was
`duration = 1440`. Always partition by `(symbol, duration)`.

### 3.4 Perfect scores are a bug signature

An overfitting audit compares train to test. It **cannot** detect a corrupted
label, because the corruption is identical in both halves. Train/test agreement
is evidence of consistency, not correctness.

When one value of one feature accounts for ~100% of the top predictions, that
feature is the finding — and a plumbing field like candle duration must never be
it.

### 3.5 Sampling must keep every positive

Base rates are ~1%. Sampling 50 rows/episode at random discarded **444 of 774**
positive episodes. Current design keeps every positive row, samples negatives,
and carries `_w` so weighted statistics match the full data. **All metrics
downstream must use `_w`** or they describe the sample, not the market.

### 3.6 Leakage guards in `step3_tune.py`

Excluded from features: all six `outcome: true` fields from `query_lang.js`;
every `label_*` column; anything starting with `_` (notably `_w`, which is
derived from the label); `episode_id` (the CV key, and it rises with time);
and raw price levels (`spotPrice`, `entryPrice`, `triggerPrice`, `patternHigh`,
`patternLow`, `avgPrice`, `logValue`) which are non-stationary — a tree splitting
on `spotPrice < 67000` has learned a **date range**.

Adding `ratio` to the feature set once produced AUC exactly 1.000.

### 3.7 Silent failures seen so far

- `signal` column coerced to NaN → `groupby` yields zero groups → script exits
  clean having trained nothing
- spot index clamped when spot history ran short → last spot candle reused for
  every later row, poisoning price, vol and moneyness with no error
- pandas <3 parses timestamps to ns, pandas 3.x to us — a hardcoded divisor made
  3-day gaps read as 0.07 hours and collapsed 3,297 rows into 2 episodes

A stage that can do zero work must say so loudly.

### 3.8 Memory

8.5M rows x ~160 columns is several GB. Both `step1_prepare.py` and
`discover_build.py` stream to parquet shards and chunk the DuckDB window
functions. Do not "simplify" either back to a single-shot query. Flags:
`--memory-limit`, `--threads`, `--chunk-episodes`, `--flush-rows`.

`discover_build.py --resume` reuses existing shards and skips the ~40 minute
candle scan.

---

## 4. Method rules

- **Structure by hand, thresholds by model.** `patterns.js` already stores at
  `minSignalValue: 0`. Loosen structural params in `config.js` *before* running
  `patterns.js`, or the ML tunes inside a set the old thresholds already
  filtered.
- **Purged walk-forward only.** Test blocks always later than train, no episode
  spans both, embargo between. Random k-fold reports ~0.95 AUC and is fiction.
- **Precision at low recall and calibration**, never accuracy or AUC alone.
  Payoffs are convex and classes are imbalanced.
- **Thresholds must be picked on train and measured on test.** `step3_tune.py`
  prints both columns and a `HOLDS` / `does NOT hold` tag.
- **No raw prices as features.** Everything scale-free.
- **Trees, not neural nets.** ~1,000-2,000 independent episodes is firmly
  gradient-boosting territory. Training takes seconds to minutes. Revisit only
  if the chain-as-grid input is built and episode counts grow.

---

## 5. Context on the person

Full-stack developer, self-taught trading intuition from chart observation rather
than statistics. Prefers runnable code with reasoning in comments; no hand-maths
explanations. Catches design errors quickly and pushes back well — the
too-good-to-be-true result in §3.3 was caught by his own estimate of how often
such setups occur, before any code review.

Estimates 10-20 genuinely high-conviction moments in two years, which matches an
independent estimate of 5-10% of expiries. If true, the right target is a **veto**
(is today ordinary?) rather than a signal generator — thousands of clean
negatives instead of a few hundred positives. This is `D-03` in the spec and the
work has drifted off it.

Stated that overtrading, driven by expecting regular income from an irregular
strategy, is the real problem. `gaps.py` exists to make dry spells legible rather
than to predict them.

---

## 6. Suggested next actions

1. `step3_tune.py --data disc_final --target {10,25,100}` — **surface vs context**
2. `make_random.py` then `step2_baseline.py --random` — the decisive null baseline
3. `gaps.py --target 10` — waiting-time distribution
4. Re-run patterns `step3` with out-of-sample thresholds; keep only `HOLDS`
5. Only then consider the veto reframe (spec `D-03`, `D-30`)
