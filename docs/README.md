# crypto_v2 — options signal research pipeline

Systematic search for cheap OTM crypto options that become multibaggers, on
Delta Exchange data.

Node 18+. No dependencies, no build step, no `package.json`.

---

## Documents

| File | What is in it |
|---|---|
| [`01-running.md`](01-running.md) | Every command, in order. Start here. |
| [`02-architecture.md`](02-architecture.md) | File map, data layout, how the pieces fit |
| [`03-signals.md`](03-signals.md) | The four signals, exact conditions |
| [`04-pseudocode.md`](04-pseudocode.md) | Logic of every module |
| [`05-query-tool.md`](05-query-tool.md) | Query language, fields, functions, holdout |
| [`06-decisions.md`](06-decisions.md) | Why things are the way they are |
| [`07-bugs-found.md`](07-bugs-found.md) | Bugs caught in testing, and the lessons |
| [`08-open-questions.md`](08-open-questions.md) | Unresolved, with the options |

---

## Thirty-second version

Two independent halves.

**Historical** — fetch candles for settled expiries, store them once, then run
signals over stored candles as often as parameters change. Signal re-runs cost
zero API calls, which is the whole reason candles are stored.

```
node backfill.js --spot-candles --from 2024-01-01
node backfill.js --from 2025-01-01 --to 2025-12-31 --candles-only --delay 500
node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only
```

**Live** — one process for future expiries. Candles are held in memory and
discarded; only signals and a snapshot are written.

```
node live_runner.js
node serve_live.js
```

Then browse: `serve_signals_cal.js` (:3500), `serve_query.js` (:3700),
`serve_trades.js` (:3400).

---

## Where the numbers stand

Roughly **20% of signals reach 10x**, measured on peak-from-entry with perfect
exit. Strength scores barely rank: the observed hit rate across strength bands
was 15/15/16/17/17%, which says the *pattern* may carry an edge while the
*scoring* of it does not.

That flatness is what the query tool exists to attack — and why every result it
shows carries a held-out number beside it.

---

## Reading order if you are new to this

1. `01-running.md` — get data on disk
2. `03-signals.md` — what is being detected
3. `05-query-tool.md` — how to interrogate it
4. `06-decisions.md` — when something looks odd, the reason is probably here
