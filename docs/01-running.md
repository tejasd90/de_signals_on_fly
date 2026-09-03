# Running

Node 18+. No `npm install`, no build step. Run every command from `crypto_v2/`.

Timezone does not need to be set — timestamps are computed as IST explicitly
throughout, verified identical across five host timezones.

This document has three parts:

1. **Concepts** — past vs future, and what each marker file means
2. **Diagnosing current state** — how to look at your `data/` folder and know
   exactly where you are, for any of the states it could be in
3. **Commands** — every command, organised by what you're trying to do

---

## Part 1 — Concepts

### Past vs future is not a flag you set — it's computed per expiry, live

There is no "past mode" or "future mode" switch. Every expiry is independently
classified by comparing its settlement time to *now*, at the moment a command
runs:

```
expiry.isExpired(spot, expiryDate)   → true  = PAST   (settled)
                                      → false = FUTURE (still trading)
```

Settlement time is per-spot (BTC/ETH/XAUT don't necessarily share a schedule),
resolved from the exchange API when available, falling back to a configured
default. This means:

- An expiry that is future today will automatically become past once its
  settlement time passes — no command needs to be re-pointed at it.
- `backfill.js` only ever touches **past** expiries (it skips anything not yet
  settled).
- `live_runner.js` only ever touches **future** expiries (it skips anything
  already settled, and drops an expiry mid-run if it settles while running).
- Nothing else in the pipeline needs to know which regime an expiry is in —
  `processor.js`'s core signal logic is shared by both paths.

### The two-marker design — the single most important thing to understand

Every past expiry passes through two **independent** stages, each with its own
completion marker:

| Stage | Marker | Cost to redo | What it means when present |
|---|---|---|---|
| Candles fetched | `data/markers/candles_complete/{spot}/{expiry}` | **Expensive** — real API calls | Every instrument's candles for every active duration are on disk for this expiry |
| Signals computed | `data/markers/signals_complete/{spot}/{expiry}` | **Free** — pure CPU, zero API calls | Signals have been computed from those stored candles |

These are deliberately decoupled. You will spend most of your iteration time
clearing only the second marker — every time you change a signal's logic or a
threshold, you re-run signal computation for free, because the expensive part
(candles) is already sitting on disk.

**Do not confuse "candles complete" with "signals complete."** A `--force` flag
on one does not touch the other. If a change you make only affects signal
logic, you never need to re-fetch candles.

### Marker files, exactly

```
data/markers/candles_complete/{spot}/{expiry}            file exists = done
data/markers/candles_complete/{spot}/{expiry}.progress   JSON, resume state while in progress
data/markers/candles_complete/{spot}/{expiry}.claim      lock file, exists only while a worker owns this expiry

data/markers/signals_complete/{spot}/{expiry}            file exists = done
data/markers/signals_complete/{spot}/{expiry}.claim      lock file

data/markers/spot/{spot}/{duration}/end                  last fetched spot candle timestamp, per duration

data/patterns/_done/{spot}/{expiry}                       patterns.js's own completion marker (separate pipeline, see below)
```

**`.claim` files should never persist after a run finishes.** If you see one
sitting there with no `backfill.js` process running, a previous run crashed or
was killed without cleaning up — see "Stuck claim" in Part 2.

### `patterns.js` is a separate pipeline with its own marker

`patterns.js` (feeding the query tool) reads the *same* stored candles as
`processor.js` but writes to a different tree (`data/patterns/` vs
`data/signals/`) with its own completion marker
(`data/patterns/_done/{spot}/{expiry}`). Running `backfill.js --signals-only`
does **not** update pattern data, and vice versa. If you want both views
current, you run both.

### Directory map, so you know what you're looking at

```
data/
  instruments/{spot}/{expiry}.json          instrument list per expiry
  candles/{spot}/{expiry}/{duration}/{symbol}.json    raw candles, past expiries
  spot_candles/{spot}/{duration}/{date}.json          spot price history
  signals/{signalId}/{spot}/{duration}/{expiry}.json  computed signals (processor.js)
  patterns/{signalId}/{spot}/{expiry}/...             computed patterns (patterns.js)
  live/{spot}/{expiry}/...                            live snapshots (live_runner.js — future only)
  markers/...                                         see above
```

---

## Part 2 — Diagnosing current state

Before running anything, look at what's actually on disk. Here is every state
you could be in, how to recognise it, and what to do next.

### State A — Nothing has ever been fetched

**Symptoms:** `data/` doesn't exist, or is empty.

```bash
ls data/candles 2>/dev/null || echo "no candle data yet"
```

**Next step:** Go to "First-time setup" in Part 3.

---

### State B — Instruments exist but no candles

**Symptoms:** `data/instruments/{spot}/` has files, `data/candles/` is empty
or missing for that spot.

```bash
ls data/instruments/BTC/ | wc -l      # how many expiries known
ls data/candles/BTC/ 2>/dev/null | wc -l    # how many have any candle data
```

**Next step:** Run candle backfill (Part 3, "Backfilling candles").

---

### State C — Candles fetched for some expiries, not others

**Symptoms:** `data/markers/candles_complete/{spot}/` has fewer files than
`data/instruments/{spot}/`.

```bash
echo "known expiries:"
ls data/instruments/BTC/ | sed 's/.json//' | sort > /tmp/known.txt
wc -l /tmp/known.txt

echo "candles-complete expiries:"
ls data/markers/candles_complete/BTC/ 2>/dev/null | grep -v '\.progress$\|\.claim$' | sort > /tmp/done.txt
wc -l /tmp/done.txt

echo "missing:"
comm -23 /tmp/known.txt /tmp/done.txt
```

**Next step:** Re-run the same `backfill.js --candles-only` command you used
before, with the same or a wider `--from`/`--to` range. It will skip anything
already marked complete and only fetch what's missing. This is always safe to
re-run — it never re-fetches completed work.

---

### State D — An expiry is stuck mid-fetch (has a `.progress` file, no completion marker)

**Symptoms:**

```bash
ls data/markers/candles_complete/BTC/*.progress 2>/dev/null
```

If this lists files, those expiries were interrupted partway through (crash,
Ctrl-C, network failure) and have partial candle data.

```bash
cat data/markers/candles_complete/BTC/2025-11-28.progress
# {"done": [...symbols fetched...], "failed": [...], "updatedAt": "..."}
```

**Next step:** Just re-run the same backfill command. Instruments already in
`done` are skipped; the rest are fetched. Progress is flushed after every
single instrument, so at most one instrument's work is ever lost to an
interruption.

---

### State E — An expiry shows `INCOMPLETE` after a run

**Symptoms:** Backfill output said something like
`INCOMPLETE 47/50 ok` for an expiry, and no `candles_complete` marker was
written for it (by design — see Part 1).

**Cause:** Some instruments failed even after retries (rate limits, transient
API errors, a genuinely bad symbol).

```bash
cat data/markers/candles_complete/BTC/2025-11-28.progress
# check the "failed" array
```

**Next step:** Re-run the identical backfill command. It resumes from
`.progress` and retries only the failed instruments. If specific instruments
keep failing across multiple attempts, check the logs
(`logs/{timestamp}_*/fetcher.log`) for the actual error — it may be a genuinely
delisted or malformed instrument worth excluding rather than retrying forever.

---

### State F — A `.claim` file exists but no backfill process is running

**Symptoms:**

```bash
ls data/markers/candles_complete/BTC/*.claim 2>/dev/null
ls data/markers/signals_complete/BTC/*.claim 2>/dev/null
ps aux | grep backfill
```

If claim files exist and `ps` shows no `backfill.js` running, a previous
process was killed (not gracefully stopped) without releasing its claim.

**Next step:** Claims self-heal after 30 minutes automatically — the next
worker to attempt that expiry will detect a stale claim and take over. If you
don't want to wait, you can manually delete the `.claim` file for the specific
expiry (do **not** delete `.progress` or the completion marker, only `.claim`)
and re-run.

---

### State G — Candles complete, signals never computed

**Symptoms:**

```bash
ls data/markers/candles_complete/BTC/ | grep -v '\.' | wc -l   # candles done
ls data/markers/signals_complete/BTC/ | grep -v '\.' | wc -l   # signals done
```

If the first number is much larger than the second, you have candle data
sitting unused.

**Next step:** Run `backfill.js --signals-only` (Part 3). Zero API calls — this
is the cheap, iterate-freely step.

---

### State H — Signals were computed once, but you've since changed thresholds/logic

**Symptoms:** You edited `config.js` (thresholds, `MIN_TTE_HOURS_TO_FIRE`,
`OPPOSITE_DIRECTION_FILTER`, etc.) or a file in `signals/`, but
`data/signals/` still holds output from before the edit.

**This is invisible from the filesystem alone** — the `signals_complete`
marker doesn't know your code changed. You have to remember to force it.

**Next step:** Run `backfill.js --signals-only --force-signals`. Without
`--force-signals`, the marker makes the run skip everything and report
"Nothing to do" — this is the single most common way to think you've
recalibrated when you haven't.

**How to check the fix landed:** compare a signal file's `updatedAt` /
mtime against your edit time:

```bash
stat -f "%Sm" data/signals/red_squeeze/BTC/60/2025-11-28.json   # macOS
stat -c "%y"  data/signals/red_squeeze/BTC/60/2025-11-28.json   # Linux
```

---

### State I — Signals current, but the query tool (`patterns.js`) is stale or empty

**Symptoms:**

```bash
ls data/patterns/_done/BTC/ 2>/dev/null | wc -l
ls data/markers/signals_complete/BTC/ | grep -v '\.' | wc -l
```

`patterns.js` has its own marker and is not updated by `--signals-only`.

**Next step:** Run `patterns.js` (Part 3). If you've already run signals with
new thresholds, run `patterns.js --force` to match.

---

### State J — Live board looks empty or stale

**Symptoms:** `serve_live.js` shows nothing, or clearly outdated data.

```bash
ls data/live/BTC/ 2>/dev/null
```

**Diagnosis:**
- No files at all → `live_runner.js` has never run, or has never reached a
  future expiry for that spot yet (it processes expiries in priority order —
  see below).
- Files exist but old → `live_runner.js` isn't currently running, or it's
  running but stuck (check its terminal/log output).

**Next step:** Make sure `live_runner.js` is running continuously in its own
terminal — it's a long-running process, not a one-shot script. It prioritises
expiries closest to settlement, so if you have many future expiries, the
farthest ones may take a while to get their first pass.

---

### State K — Spot candle data is missing or short

**Symptoms:** OTM-dependent signals (`otm_red_squeeze`, `green_stairs`,
`otm_wall`) fire far less than expected, or not at all.

```bash
ls data/spot_candles/BTC/1440/ 2>/dev/null | sort | head -3   # earliest date stored
ls data/spot_candles/BTC/1440/ 2>/dev/null | sort | tail -3   # latest date stored
```

**Cause:** These signals need spot price context. If spot history doesn't
reach back far enough to cover your option candle range, they can't fire on
the earlier expiries.

**Next step:** Re-run `backfill.js --spot-candles --from <date>` with `--from`
earlier than your earliest option expiry's start of trading (typically 40+
days before that expiry, per `EXPIRY_LISTING_WINDOW_DAYS`).

---

### Quick summary table

| You see... | You are in state... | Do this |
|---|---|---|
| No `data/` folder | A | First-time setup |
| Instruments only | B | Backfill candles |
| Some expiries done, some not | C | Re-run same backfill command |
| `.progress` file, no marker | D | Re-run same backfill command |
| `INCOMPLETE n/m` in output | E | Re-run; check logs if persistent |
| Orphaned `.claim` file | F | Wait 30min, or delete the `.claim` file |
| Candles done, signals not | G | `--signals-only` |
| Edited config, marker unchanged | H | `--signals-only --force-signals` |
| Signals fresh, patterns stale | I | `node patterns.js [--force]` |
| Live board empty/stale | J | Ensure `live_runner.js` is running |
| OTM signals sparse | K | Re-check spot candle coverage |

---

## Part 3 — Commands

### First-time setup, in order

**1. Instruments**

```bash
node -e "require('./instruments').fetchAndStoreInstruments('live')"
node -e "require('./instruments').fetchAndStoreInstruments('expired')"
```

Nothing else works without this. Also records each spot's real settlement
time, so BTC/ETH/XAUT are each handled correctly even if their schedules
differ.

**2. Spot candles**

```bash
node backfill.js --spot-candles --from 2024-01-01
```

Reach back further than you think — see State K above. `--from` extends
backwards past whatever is already stored; without it you get
`SPOT_HISTORY_DAYS` back from today.

**3. Preview the work before committing**

```bash
node backfill.js --from 2025-01-01 --to 2025-12-31 --list
```

`--from`/`--to` filter on **expiry date**, not candle date.

**4. Backfill option candles — the slow, API-bound part**

About 13 requests per instrument. Split across workers on disjoint date
ranges, each with its own `--label` so logs don't collide:

```bash
node backfill.js --from 2025-01-01 --to 2025-04-30 --label Q1 --delay 500 --candles-only
node backfill.js --from 2025-05-01 --to 2025-08-31 --label Q2 --delay 500 --candles-only
node backfill.js --from 2025-09-01 --to 2025-12-31 --label Q3 --delay 500 --candles-only
```

`--delay 500` keeps three concurrent workers at roughly 54% of the rate
limit. Workers take an exclusive claim per expiry, so they never duplicate
each other's work — you can run more workers than this example safely.

Always safe to interrupt and re-run identically (see State D, E).

**5. Compute signals — fast, zero API calls**

```bash
node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only
```

**6. Compute patterns, for the query tool — also zero API calls**

```bash
node patterns.js --from 2025-01-01 --to 2025-12-31
```

Before running this at real scale, read "Loosen structural parameters first"
below — it saves a second full pass later.

---

### Backfilling a specific recent window (e.g. "last 10 days")

Be careful: `--from`/`--to` filter on *expiry date*. To get expiries that
**settled** in the last 10 days:

```bash
node backfill.js --spot-candles --from 2026-06-01          # NOT "10 days ago" — see below
node backfill.js --from 2026-08-06 --to 2026-08-16 --candles-only --delay 500
node backfill.js --from 2026-08-06 --to 2026-08-16 --signals-only
node patterns.js --from 2026-08-06 --to 2026-08-16
```

The spot `--from` needs to reach back to cover the *option* candles' full
window (40+ days before the earliest expiry in range), not just 10 days — see
State K.

---

### Running live (future expiries)

```bash
node live_runner.js      # long-running; leave it in its own terminal
node serve_live.js       # :3200, separate terminal
```

`live_runner.js` is the only live process — it writes both the
historical-format signal files (so `serve_signals.js` also picks up live
expiries) and the live snapshot, from a single fetch pass. `main.js` is
retired and will print an error pointing here if run.

It uses a **weighted scheduler**, not round-robin: expiries closer to
settlement are processed far more often than distant ones, since they move
faster. This means a newly-added far-dated expiry may take a while to get its
first pass — check `data/live/{spot}/{expiry}/` for freshness (State J) before
assuming something is broken.

---

### After changing signal parameters or logic

Any edit to `config.js` thresholds, `MIN_TTE_HOURS_TO_FIRE`,
`OPPOSITE_DIRECTION_FILTER`, or any file under `signals/`:

```bash
node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only --force-signals
node patterns.js --from 2025-01-01 --to 2025-12-31 --force
```

**`--force-signals` and `--force` are not optional here** — without them the
completion markers make both commands report "Nothing to do" (State H). Zero
API calls either way, since this only touches already-stored candles.

| Change | Needs |
|---|---|
| `RED_SQUEEZE_*`, `OTM_*`, `WALL_*` thresholds | `--signals-only --force-signals` |
| `MIN_TTE_HOURS_TO_FIRE` | same |
| `OPPOSITE_DIRECTION_FILTER`, `BIG_CANDLE_BODY_FRACTION` | same |
| `DURATION_TIMES` start window widened | also `--candles-only --force-candles` (new candle range needed) |
| `MULTIBAGGER_THRESHOLDS`, band/colour definitions | nothing — display-only, just refresh the browser |

---

### Loosen structural parameters before a full pattern extraction

Some structural parameters leave a trace in a stored field, meaning you can
run `patterns.js` once at the *loosest* setting and tighten later purely by
query — no second extraction pass:

```js
RED_SQUEEZE_MIN_SEQ_LENGTH   = 2      // then query: seqLength >= 3
OTM_MIN_SEQ_LENGTH           = 2
GREEN_STAIRS_MAX_EQUAL_STEPS = 5      // then query: equalSteps <= 1
```

`WALL_LOOKBACK_CANDLES` and `WALL_CLOSE_MULTIPLE` leave no stored trace, so
changing them always needs a fresh `patterns.js --force` regardless.

---

### Viewers

| Command | Port | Shows |
|---|---|---|
| `node serve_signals.js --signal otm_wall` | 3100 | Strength×payoff matrix, expiry grid |
| `node serve_live.js` | 3200 | Live tape, EMA convergence, volatility map |
| `node serve_multibaggers.js` | 3300 | Ground truth: every move that existed |
| `node serve_trades.js` | 3400 | Trade calendar, all durations stacked |
| `node serve_signals_cal.js` | 3500 | Signal calendar, all durations stacked |
| `node serve_calibrate.js` | 3600 | Fixed-form successes/failures |
| `node serve_query.js` | 3700 | Expression query with holdout |
| `node serve_grids.js` | 3800 | Point-in-time signal heatmaps (**future expiries only** — see note below) |

All accept `--port`, so several instances can run at once
(`--port 3101`, etc). Every viewer binds `0.0.0.0` and prints its LAN address
on startup, so any device on the same network can reach it. Chart links follow
whatever host served the page.

**Note on `serve_grids.js`:** its whole design is "which expiries are alive
*right now* at a chosen moment" — a live/future concept. There is currently no
equivalent past-expiry heatmap; for reviewing settled expiries, use
`serve_signals_cal.js` or `serve_signals.js`.

---

### Analysis commands

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

All read-only against stored data — zero API calls, safe to run anytime signal
data exists (State G or later).

---

## Troubleshooting quick reference

**`INCOMPLETE n/m ok`** — see State E. Re-run identically; check
`logs/*/fetcher.log` if it doesn't resolve after a couple of attempts.

**HTTP 429 in `logs/*/fetcher.log`** — raise `--delay` or `API_CALL_DELAY_MS`
in config.

**OTM signals produce nothing** — see State K.

**`quality.js --by moneyness` excludes most rows** — same root cause as State
K; the tool's own output states the exact percentage excluded and why.

**Signals show `0.00x` for Best ratio** — signal files predate
`universeMaxRatio` being added. Run `--signals-only --force-signals`.

**Matrix has one populated row** — strength bands are wrong for that signal's
scale. Fix `STRENGTH_BANDS_BY_SIGNAL[signalId]` in `config.js`; display-only,
no re-run needed.

**Live tape empty but signal files populated** — signals older than
`LIVE_SIGNAL_WINDOW_HOURS` (48). Expected with long durations; raise the
constant if needed.

**Force one specific expiry to fully recompute:**

```bash
rm data/markers/signals_complete/BTC/2025-11-28
rm data/patterns/_done/BTC/2025-11-28
```

**Force a specific expiry's candles to be re-fetched from scratch** (rarely
needed — usually re-running with `--force-candles` on the whole range is
simpler):

```bash
rm data/markers/candles_complete/BTC/2025-11-28
rm data/markers/candles_complete/BTC/2025-11-28.progress
```

**Start completely clean:**

```bash
rm -rf data logs
```
