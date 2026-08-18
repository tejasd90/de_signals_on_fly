# Bugs found

Kept because most of these are the kind that reappear, and because several would
have been silent — producing plausible-looking wrong numbers rather than errors.

---

## Silent-data bugs

These are the dangerous class: no exception, no log line, just wrong output.

### Grouping chain broke when an intermediate was not active

For a 10-day expiry, active durations were `[20,30,40,45,...]` — 5, 10 and 15 were
not active. But 20 chains `20←10←5`. The code only computed durations in the
target list, so it looked for 10m candles, never found them, and produced **zero
candles for 20m and 40m**.

Most durations would have silently produced no signals. Fixed by expanding each
target into its full chain, then discarding unrequested intermediates.

### Warm-up strip destroyed coarse durations

`SKIP_INITIAL_CANDLES = 20` was calibrated for 5-minute candles. Applied to daily
bars it discarded **20 of 40 days**. Warm-up is now a time window converted per
duration.

### Partial data marked complete

`markCandlesComplete` ran unconditionally. If 50 of 200 instruments failed, the
expiry was still marked done and every later run skipped it — permanent, silent
gaps. Now the expiry is left unmarked and reported as `INCOMPLETE`.

### Truncation passed off as complete

`fetchCandles` caught a failed page and `break`'d, returning whatever had already
succeeded. A partial series was indistinguishable from a complete one downstream.

### Spot lookup found nothing

Exact `dtstring` matching assumed spot and option candles share slot boundaries.
They do not: `getKeyDuration` anchors at 17:30 IST, so a *grouped* 60m series
lands on `:30` while a *directly fetched* one lands on `:00`.

Measured: **498 option candles, 960 spot candles, zero exact matches.** And the
failure mode read as "not OTM", so every signal vanished with no error at all.
Lookup now falls back to a binary search for the last candle at or before the time.

### Spot history capped at ~400 days

Three compounding causes. The marker was rewritten to `now` after every fetch, so
the series could only grow *forwards*. `--force` reset the marker to null, which
just recomputed `now − SPOT_HISTORY_DAYS` — the same date. And `--spot-candles`
ignored `--from` entirely. No combination of flags could reach further back.

### Doji inflated ratio1

A doji was admitted with its body floored to `MIN_TICK` (0.1), so
`ratio1 = firstRedBody × 10`. Any doji ending a run with `firstRedBody >= 5`
cleared a threshold of 50 on `ratio1` alone. With tick-quantised prices, **53% of
candles were zero-body**.

### Empty results were not written

A stricter parameter legitimately produces no signals, but skipping the write left
the previous run's file in place, which `quality.js` reported as current.
Retested 3 → 5 → 3 on `MIN_SEQ_LENGTH`: counts moved 20 → 0 → 20.

### Empty buckets vanished from reports

Only buckets with data were printed. With 11 moneyness bands and partial coverage
you would see 7 and reasonably conclude the wrong bucket set was configured.

### Calls and puts pooled in `quality.js`

The original report split them; a rewrite collected `type` and then never grouped
by it. With calls carrying an 80% pocket and puts flat at 10%, the pooled figure
read **46%** — halving a genuine edge.

---

## Crash bugs

### `cfg.delay is not a function`

`delay` lives in `api.js`, not `config.js`. Two calls in `live_runner.js` had it
wrong. Both sit in the loop *after* the work completes, so the function under test
was clean and the crash lived in code never exercised — I had only ever called
`processLiveExpiry` directly, never `main()`.

Prompted an audit of every cross-module reference in eight files. No others.

### `idx.values is not a function`

`spotIndexFor` returns a custom lookup object, not a `Map`. Added `values()`,
`all()`, `last()`.

### Template-literal escaping

`serve_signals.js` builds its HTML as a template literal, so a `\'` written in the
source was consumed by Node and the browser received a broken string — the page
went blank with `Unexpected identifier 's'`.

The syntax check had been passing because it validated the **source file**, not
what the server emits. Now every viewer is verified by extracting the JS from a
live `curl` of the served page. Escaped quotes and `${` inside those templates
will not survive.

---

## Logic bugs

### Green stairs fired zero

The breakout candle is usually *green* — a run is broken far more often by a
smaller-bodied green than by a red. The first version only tested breakout on
non-green candles, so the run never terminated.

### `bandOf` was order-dependent

A first-match scan silently reversed one of the two band sets: a perfectly flat
market scored band 0 ("wide") because 0 is less than `Infinity`, the first entry.
Now picks the smallest satisfied bound, which is correct for either ordering.

### Merge cap measured the wrong thing

It capped absolute window span rather than how far a merge *extends* one. Six
instruments with near-identical 90h windows — plainly one event — stayed as six
separate rows because each already exceeded the cap.

### Payoff toggle left the summary line stale

Panels reordered but the line above kept showing the other definition's figures —
`67.59x` when the truth under the active setting was `4.88x`. Silently misleading.

### Backwards ratio measurement

`signalRatio` was truncated at the first stop-loss breach. Since options always
decay below any pattern-derived level, that made every ratio ≈ 1.0 and every state
`slHit` — the entire outcome column was meaningless.

---

## Testing lessons

**Validate what the server emits, not the source file.** The escaping bug passed
`node --check` on the source and still broke the page.

**Test the loop, not just the function.** The `cfg.delay` crash lived in code
reached only by running `main()`.

**Plant a known answer.** The holdout was verified by planting a spurious pattern
in the training half only — 94.7% train against 16.9% test. Testing that a tool
*runs* is much weaker than testing that it *finds what you hid*.

**Beware fixtures that mask bugs.** One duplicate-detection run reported false
duplication because the seed data reused the same symbol across four expiries.
Another produced zero true positives because the generator decayed to the tick
floor before the injected explosion. Both looked like code faults and were not.
