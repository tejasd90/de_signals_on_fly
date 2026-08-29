# Architecture

## Code

```
crypto_v2/
│
│  ── ENTRY POINTS ──────────────────────────────────────────────
├── live_runner.js         live expiries: signals + indicators, one fetch
├── backfill.js            past expiries + spot candles
├── patterns.js            stage 1 of the query pipeline
├── trades.js              recursive trade partitioning
├── multibaggers.js        ground truth, signal-independent
├── quality.js             CLI quality report
├── dryrun.js              offline pipeline test, no API
├── main.js                RETIRED — prints replacement commands, exits 1
│
│  ── VIEWERS ───────────────────────────────────────────────────
├── serve_signals.js       :3100   matrix + grid + tree
├── serve_live.js          :3200   live board
├── serve_multibaggers.js  :3300   ground-truth table
├── serve_trades.js        :3400   trade calendar
├── serve_signals_cal.js   :3500   signal calendar
├── serve_calibrate.js     :3600   fixed-form calibration
├── serve_query.js         :3700   expression query + holdout
├── serve_grids.js         :3800   signal heatmaps, expiry x time
│
│  ── CONFIG / REGISTRIES ───────────────────────────────────────
├── config.js              everything tunable
├── signal_registry.js     add a signal here; nothing else changes
├── query_lang.js          tokeniser, parser, field + function registries
│
│  ── INFRASTRUCTURE ────────────────────────────────────────────
├── api.js                 HTTP, retries, backoff
├── logger.js              per-execution log directories
├── netinfo.js             LAN addresses for startup banners
├── expiry.js              per-spot settlement times
├── instruments.js         instrument lists
├── scheduler.js           weighted expiry priority
├── grouper.js             candle grouping, sourceFor()
├── merger.js              overlapping-range merge
├── candle_store.js        option candles on disk
├── spot_store.js          spot candles on disk
├── indicators.js          emaSpread, priceVolatility
├── processor.js           orchestration
├── writer.js              signal files, markers, claims, summaries
│
└── signals/
    ├── red_squeeze.js            original, no spot needed
    ├── red_squeeze_adapter.js    registry wrapper for it
    ├── otm_common.js             shared OTM helpers
    ├── otm_red_squeeze.js
    ├── green_stairs.js
    └── otm_wall.js
```

---

## Data

```
data/
├── instruments/{SPOT}/{expiry}.json              {symbol: productId}
│
├── candles/{SPOT}/{expiry}/{duration}/{symbol}.json
│       [[time,o,h,l,c,v], ...]  — compact arrays, dtstring rebuilt on read
│       EVERY duration stored, each trimmed to its own window
│
├── spot_candles/{SPOT}/{duration}/{YYYY-MM-DD}
│       continuous, not per-expiry — hence a separate tree
│
├── signals/{signalId}/{SPOT}/{duration}/{expiry}.json
│       { C: [mergedRange...], P: [...], updatedAt }
│   └── {signalId}/{SPOT}/_summary/{expiry}.json    calendar summary
│
├── patterns/{signalId}/{SPOT}/{duration}/{expiry}.json
│       [rowObject, ...]  — UNMERGED, one row per instrument
│   └── _done/{SPOT}/{expiry}                       resume marker
│
├── trades/{SPOT}/{expiry}/{duration}.json
│   └── {SPOT}/{expiry}/_summary.json
│
├── multibaggers/{SPOT}/{expiry}.json
│
├── live/{SPOT}/{expiry}.json                       overwritten each pass
│
└── markers/
    ├── candles_complete/{SPOT}/{expiry}            [.progress for resume]
    ├── signals_complete/{SPOT}/{expiry}            [.claim for concurrency]
    └── spot/{SPOT}/{duration}/end

logs/{timestamp}_{label}_pid{N}/
        scheduler.log  fetcher.log  candle_store.log  spot_store.log
        live.log  signal_writer.log  quality.log
        *.debug                     only when DEBUG_ENABLED
```

---

## The two-marker design

This is the load-bearing idea in the whole pipeline.

| Marker | Means | Cost to redo |
|---|---|---|
| `candles_complete` | candles on disk | expensive — API bound |
| `signals_complete` | signals computed from them | cheap — pure CPU |

Clearing only `signals_complete` gives a full recompute with **zero API calls**.
That is why candles are stored at all, and why parameter tuning is practical.

Candle storage deliberately grabs the full `PRIOR_DAYS` window rather than only
what the current `DURATION_TIMES` needs, so widening a window later does not
force a refetch.

---

## The merged range format

Stored in `data/signals/`, a 9-element array:

| # | Field | Meaning |
|---|---|---|
| 0 | `startTs` | earliest `patternStart` across merged instruments |
| 1 | `endTs` | latest trigger timestamp — the entry |
| 2 | `count` | how many instrument signals merged here |
| 3 | `maxSignalValue` | highest strength among them |
| 4 | `maxSignalRatio` | best multiple among instruments that **fired** |
| 5 | `signalState` | `activated` / `slHit` / `pending` |
| 6 | `instruments` | symbols that fired |
| 7 | `universeMaxRatio` | best multiple on **any** same-type strike |
| 8 | `universeMaxSymbol` | which strike reached it |

Indices 7–8 were appended, so older files still parse — those fields read as
`undefined` and display as `0.00x` until a `--force-signals` run.

**This format is lossy.** Per-instrument `ratio1`, `ratio2`, `seqLength` are
discarded at merge time. That is why `patterns.js` exists and stores unmerged.

---

## Duration sourcing

Each duration is built in **one** grouping step from the largest direct-fetch
duration that divides it:

```
5m → 5, 10, 20, 40          15m → 15, 45
30m → 30, 90                60m → 60, 180
120m → 120, 360             240m → 240, 480
720m → 720                  1440m → 1440
```

Sources are fetched **once** and shared across their targets — 13 API requests
per instrument rather than 22.

`sourceFor()` computes this; there is no hand-maintained chain, so adding a
duration needs no config edit.

---

## Rate limits

- ~13 requests per instrument for a full store
- 200 instruments → ~2,600 requests per expiry
- `API_CALL_DELAY_MS = 150` → ~6.6 req/sec, one worker
- three workers at `--delay 500` → ~6 req/sec combined, ~54% of the ceiling

All workers share one exchange limit. Claims prevent duplicated *work*, not
duplicated *budget*.
