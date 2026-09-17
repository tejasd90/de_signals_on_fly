# RUNBOOK — raw data to tuned thresholds

Run everything from the repo root (`crypto_v2/` or wherever `patterns.js` lives).
Node 18+, and a Python venv with `pandas numpy scikit-learn lightgbm scipy pyarrow duckdb`.

Only **step 4** makes API calls in the option pipeline. Everything else there
is CPU and safe to re-run. The perp pipeline at the bottom also hits the API,
but it is unauthenticated, resumable and finishes in ~2.5 minutes.

---

## STEP 0 — Loosen structural thresholds FIRST

**Do this before step 6. It is a correctness requirement, not an optimisation.**

If `patterns.js` runs at current settings, the hand-picked thresholds have
already filtered the data. The model then tunes *within* the set those
thresholds selected, and cannot recover what they excluded — so the "tuned"
values it returns are conditional on the guesses we are trying to replace.

In `config.js`:

```js
RED_SQUEEZE_MIN_SEQ_LENGTH   = 2    // then query seqLength >= 3 later
OTM_MIN_SEQ_LENGTH           = 2
GREEN_STAIRS_MAX_EQUAL_STEPS = 5    // then query equalSteps <= 1 later
```

These leave a trace in stored fields (`seqLength`, `equalSteps`), so tightening
afterwards is a **query**, not a re-extraction.

`WALL_LOOKBACK_CANDLES` and `WALL_CLOSE_MULTIPLE` leave **no** stored trace —
set them loose too, because changing them later forces a full re-extraction.

Cost of loosening: more rows, slower `patterns.js`, larger files.
Cost of not loosening: the tuning answers the wrong question.

---

## STEP 1-3 — One-time setup (skip if `data/` is already populated)

```bash
node -e "require('./instruments').fetchAndStoreInstruments('live')"
node -e "require('./instruments').fetchAndStoreInstruments('expired')"

node backfill.js --spot-candles --from 2023-06-01
```

Spot `--from` must reach **40+ days before your earliest expiry**, not just
before your date range — option candle windows extend backwards.

Preview before committing to the slow part:

```bash
node backfill.js --from 2024-01-01 --to 2025-12-31 --list
```

`--from` / `--to` filter on **expiry date**, not candle date.

---

## STEP 4 — Option candles (slow, API-bound)

Skip if already backfilled. ~13 requests per instrument.

```bash
node backfill.js --from 2024-01-01 --to 2024-12-31 --label Y24 --delay 500 --candles-only
node backfill.js --from 2025-01-01 --to 2025-12-31 --label Y25 --delay 500 --candles-only
```

Run several in parallel on disjoint ranges with distinct `--label`s. Workers
claim expiries exclusively, so they never duplicate work. Always safe to
interrupt and re-run identically.

---

## STEP 5 — Signals (free, no API)

```bash
node backfill.js --from 2024-01-01 --to 2025-12-31 --signals-only --force-signals
```

`--force-signals` is **required** after any `config.js` change. Without it the
completion markers make this report "Nothing to do" and you would tune on the
old filtered data without noticing.

---

## STEP 6 — Patterns (free, no API)

Only after STEP 0.

```bash
node patterns.js --from 2024-01-01 --to 2025-12-31 --force
```

Writes `data/patterns/{signal}/{spot}/{duration}/{expiry}.json`.
`--force` is required for the same marker reason as above.

---

## STEP 7 — Ground truth (free, no API)

```bash
node multibaggers.js --min 10
```

Writes `data/multibaggers/{spot}/{expiry}.json`. Signal-independent: every move
that existed, whether or not anything fired.

Use `--min 10` rather than 25 — it captures the smaller multiples too, which
matters if 25x turns out to be under-sampled.

---

## STEP 8 — Labelled dataset

```bash
python3 step1_prepare.py --patterns data/patterns --target 25 --out dataset.parquet
```

Filters, if wanted: `--signal red_squeeze --spot BTC --duration 60`

To label from ground truth instead of the in-row `peakAfter`:

```bash
python3 step1_prepare.py --patterns data/patterns \
                         --multibaggers data/multibaggers --target 25
```

**Read the `positive EPISODES` line, not the row count.** Rows are many views of
the same moves — episodes are the real sample size. Expect an inflation factor
of 10-50x.

If under 30 positive episodes: re-run with `--target 10`. If the structure holds
at 10x, it is probably real at 25x but under-sampled.

---

## STEP 9 — Null baseline

```bash
python3 step2_baseline.py --data dataset.parquet
```

With a random-entry file (better — this is the decisive version):

```bash
python3 step2_baseline.py --data dataset.parquet --random random_entries.csv
```

To build `random_entries.csv`: sample timestamps from the same OTM/DTE
population the signals fire on, run the same forward scan `multibaggers.js`
already does, save with a peak-ratio column.

Answers: does the signal beat random on the same instruments, or is 20% just the
convexity of cheap OTM options?

---

## STEP 10 — Tuning

```bash
python3 step3_tune.py --data dataset.parquet
```

Outputs `tuned_config.json` plus, on stdout:

- **arm comparison** — context vs signals vs both. If `signals` > `context`, the
  patterns carry information beyond contract selection
- **precision at 15% recall** — compare against the base rate printed below it
- **permutation importance** — features with ~zero AUC drop are inert
- **tuned thresholds** — hit rate per sixth of each feature's range, best marked

Where two features both show lift, require **both**. That conjunction is the
conditional tuning a flat threshold cannot express.

---

## After tuning

Tighten `config.js` to the ranges step 10 found, then:

```bash
node backfill.js --from 2024-01-01 --to 2025-12-31 --signals-only --force-signals
node patterns.js --from 2024-01-01 --to 2025-12-31 --force
```

Re-run steps 8-10 to confirm the tightened settings reproduce the expected hit
rate on held-out folds.

---

## The perp pipeline — separate from everything above

Steps 0-10 build the **option** dataset (candles -> signals -> patterns ->
tuning). The futures research runs on a different, much smaller dataset that
shares no code with them.

```bash
# 1. symbol list (220 live Delta India perpetuals)
python3 fetch_perps.py --symbols perp_symbols.json --resolution 1h \
                       --from-ts 1672531200 --out data/perp_candles --workers 4

# 2. funding-rate history (FUNDING: prefix on the same endpoint)
python3 fetch_funding.py

# 3. derived layers
python3 brooks_features.py       # 105 mechanical spot features -> perp_brooks/
python3 liq_surface.py           # exact first-crossing liquidation surface -> perp_liq/
```

**This is 70 MB total and takes ~2.5 minutes.** It is unauthenticated, resumable
(a symbol whose parquet already reaches `--end` is skipped), and safe to re-run.
So there is never a reason to copy `data/perp_candles/` between machines — clone
the repo and run step 1.

Unlike `data/candles/`, these are **traded** candles with real volume (plain
symbol, no `MARK:` prefix — see `02-architecture.md`). That is the whole reason
the futures work can make claims the options work cannot.

Everything downstream (`fut_ml.py`, `round2_tree.py`, `nn_round2.py`,
`pyramid_backtest.py`, `carry_portfolio.py`, `grid_sim.py`) reads those parquets
and is pure CPU.

---

## Quick reference

| Change | Needs |
|---|---|
| `RED_SQUEEZE_*`, `OTM_*`, `WALL_*` thresholds | step 5 + 6 with force flags |
| `MIN_TTE_HOURS_TO_FIRE` | same |
| `DURATION_TIMES` start window widened | also step 4 with `--force-candles` |
| `MULTIBAGGER_THRESHOLDS`, colours | nothing — display only |
