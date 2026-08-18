# Running

Node 18+. No `npm install`. Run everything from the `crypto_v2/` directory.

Timezone does not need to be set — `formatTs` and `getKeyDuration` compute IST
explicitly and were verified byte-identical across five host timezones.

---

## First-time setup, in order

### 1. Instruments

```bash
node -e "require('./instruments').fetchAndStoreInstruments('live')"
node -e "require('./instruments').fetchAndStoreInstruments('expired')"
```

Nothing else works without this. It also records each spot's real settlement
time, which is how XAUT gets handled correctly alongside BTC and ETH.

### 2. Spot candles

```bash
node backfill.js --spot-candles --from 2024-01-01
```

**Reach back further than you think.** An expiry has candles going back
`PRIOR_DAYS` (40) before it, and every one needs a spot price for the OTM check.
Set `--from` at least 60 days before your earliest expiry, or OTM signals will
silently find no spot and produce nothing.

`--from` **extends backwards** past whatever is already stored. Without it you
get `SPOT_HISTORY_DAYS` (1200) back from today.

### 3. Preview the work

```bash
node backfill.js --from 2025-01-01 --to 2025-12-31 --list
```

`--from` / `--to` filter on **expiry date**, not candle date.

### 4. Option candles — the slow part

About 13 API requests per instrument. Three workers on disjoint ranges:

```bash
node backfill.js --from 2025-01-01 --to 2025-04-30 --label Q1 --delay 500 --candles-only
node backfill.js --from 2025-05-01 --to 2025-08-31 --label Q2 --delay 500 --candles-only
node backfill.js --from 2025-09-01 --to 2025-12-31 --label Q3 --delay 500 --candles-only
```

`--delay 500` keeps three workers at roughly 54% of the rate limit. Workers take
an exclusive claim per expiry, so they never duplicate each other's work.

Interruptions resume: progress is flushed after every instrument, and an expiry
with any failure is left unmarked.

### 5. Signals — fast, no API calls

```bash
node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only
```

### 6. Patterns, for the query tool — no API calls

```bash
node patterns.js --from 2025-01-01 --to 2025-12-31
```

Before running this at scale, see **Loosen structural parameters first** below.

---

## Backfilling a short window

For expiries settled in the last 10 days (example dates):

```bash
node backfill.js --spot-candles --from 2026-06-01          # note: NOT 10 days
node backfill.js --from 2026-08-06 --to 2026-08-16 --candles-only --delay 500
node backfill.js --from 2026-08-06 --to 2026-08-16 --signals-only
node patterns.js --from 2026-08-06 --to 2026-08-16
```

---

## Daily running

```bash
node live_runner.js      # the only live process; main.js is retired
node serve_live.js       # :3200
```

`live_runner.js` writes **both** the historical-format signal files and the live
snapshot, from one fetch.

---

## After changing signal parameters

```bash
node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only --force-signals
node patterns.js --from 2025-01-01 --to 2025-12-31 --force
```

**`--force-signals` is essential.** Without it the completion marker makes the
run skip everything and report "Nothing to do".

| Change | Needs |
|---|---|
| `RED_SQUEEZE_*`, `OTM_*`, `WALL_*` | `--signals-only --force-signals` |
| `DURATION_TIMES` start window | also `--candles-only --force-candles` |
| `MULTIBAGGER_THRESHOLDS`, band definitions | nothing — display only |

---

## Viewers

| Command | Port | Shows |
|---|---|---|
| `node serve_signals.js --signal otm_wall` | 3100 | Strength×payoff matrix, expiry grid |
| `node serve_live.js` | 3200 | Live tape, EMA convergence, volatility map |
| `node serve_multibaggers.js` | 3300 | Ground truth: every move that existed |
| `node serve_trades.js` | 3400 | Trade calendar, all durations stacked |
| `node serve_signals_cal.js` | 3500 | Signal calendar, all durations stacked |
| `node serve_calibrate.js` | 3600 | Fixed-form successes/failures |
| `node serve_query.js` | 3700 | Expression query with holdout |

All accept `--port`, so several can run at once.

---

## Analysis commands

```bash
node quality.js --signal otm_wall
node quality.js --signal otm_wall --source fired
node quality.js --signal otm_wall --type C
node quality.js --signal otm_wall --by tte
node quality.js --signal otm_wall --by tte,moneyness
node quality.js --signal otm_wall --by duration,tte,moneyness   # three-way
node quality.js --signal otm_wall --spot BTC --dur 240

node trades.js --from 2025-01-01 --to 2025-12-31 --min 5
node multibaggers.js --min 10 --spot BTC
```

---

## Loosen structural parameters first

Some structural parameters leave a trace in a stored field, so running stage 1 at
the **loosest** setting lets you tighten by query afterwards without
re-extracting:

```js
RED_SQUEEZE_MIN_SEQ_LENGTH   = 2      // then query: seqLength >= 3
OTM_MIN_SEQ_LENGTH           = 2
GREEN_STAIRS_MAX_EQUAL_STEPS = 5      // then query: equalSteps <= 1
```

`WALL_LOOKBACK_CANDLES` and `WALL_CLOSE_MULTIPLE` leave no trace and always need
a re-run.

---

## Troubleshooting

**`INCOMPLETE n/m ok`** — some instruments failed after retries. Re-run the
identical command; it resumes.

**HTTP 429 in `logs/*/fetcher.log`** — raise `--delay` or `API_CALL_DELAY_MS`.

**OTM signals produce nothing** — spot candles do not cover the signal
timestamps. Check `data/spot_candles/{SPOT}/` and re-run step 2 with an earlier
`--from`.

**`quality.js --by moneyness` excludes most rows** — same cause. The output
states the exact percentage excluded.

**Signals show `0.00x` for Best ratio** — signal files predate `universeMaxRatio`.
Run `--signals-only --force-signals`.

**Matrix has one populated row** — strength bands wrong for that signal's scale.
Fix `STRENGTH_BANDS_BY_SIGNAL[signalId]`; display only, no re-run.

**Live tape empty but signal files populated** — signals older than
`LIVE_SIGNAL_WINDOW_HOURS` (48). Expected with long durations.

**Force one expiry to recompute**

```bash
rm data/markers/signals_complete/BTC/2025-11-28
rm data/patterns/_done/BTC/2025-11-28
```

**Start clean**

```bash
rm -rf data logs
```
