# Pseudocode

Signal-detection logic lives in `03-signals.md`. This covers everything else.

---

# Fetching

## `api.js`

```
apiFetch(path, query):
    FOR attempt = 1..API_MAX_RETRIES (5):
        TRY:
            response = fetch(url)
            IF !response.ok:  THROW error WITH httpStatus
            IF !data.success: THROW error WITH httpStatus = 200   // server answered
            SLEEP(API_CALL_DELAY_MS)
            RETURN data
        CATCH err:
            retryable = no httpStatus        (transport failure)
                     OR httpStatus == 429    (rate limited)
                     OR httpStatus >= 500    (exchange fault)
            IF NOT retryable: THROW now      // a 4xx will fail identically
            IF last attempt:  BREAK
            wait = BASE_DELAY × 2^(attempt-1)
            IF 429: wait = MAX(wait, RATE_LIMIT_BACKOFF)   // 30s floor
            SLEEP(wait)
    THROW lastError

fetchCandles(symbol, resolution, start, end):
    currentEnd = end
    WHILE currentEnd > start:
        currentStart = MAX(currentEnd − MAX_CANDLES × resolutionSecs, start)
        response = apiFetch(...)              // deliberately NOT wrapped
        IF empty: BREAK
        APPEND parsed
        currentEnd = currentStart − resolutionSecs
    SORT ascending, attach dtstring
```

Not wrapping the page fetch is intentional: a swallowed error returns a silently
truncated series that downstream cannot distinguish from a complete one.

## `expiry.js`

```
resolve(spot, expiryDate):
    1. settlement time learned from API product.settlement_time   ← authoritative
    2. SETTLEMENT_TIME_BY_SPOT[spot]                              ← fallback
    3. DEFAULT_SETTLEMENT_TIME (17:30:00+0530)

expiryUnix / expiryMillis / isExpired / hoursToExpiry all derive from this
```

Because step 1 reads the exchange's own field, a new listing with a different
schedule works with no code change.

## `grouper.js`

```
sourceFor(duration):
    IF directly fetchable: RETURN itself
    RETURN largest direct duration that divides it evenly

getKeyDuration(durationMins, dtstring):
    istMs  = parse(dtstring) + IST_OFFSET
    anchor = 17:30 IST on that IST calendar day     // computed via UTC getters
    slot   = floor((istMs − anchor) / durationMins)
    RETURN format(anchor + slot × durationMins)

groupCandles(candles, duration):
    bucket by getKeyDuration
    open = earliest candle's open,  close = latest candle's close
    high = max,  low = min,  volume = sum

stripWarmup(candles, durationMins):
    drop leading candles until low > 0.1
    warmupCandles = ceil(SKIP_INITIAL_CANDLES × 5 / durationMins)   // TIME-scaled
    drop that many more
```

Time-scaling the warm-up matters: a fixed 20 candles discards 20 **days** of
daily bars.

## `spot_store.js`

```
fetchSpotCandles(spot, duration, {force, fromDate}):
    from = marker ? marker − OVERLAP_MINUTES
                  : now − SPOT_HISTORY_DAYS
    IF fromDate: from = MIN(from, fromDate)        // EXTENDS BACKWARDS
    fetch, store partitioned by date, write marker = now

spotIndexFor(spot, duration):
    IF cached: RETURN                              // 727ms → 0.01ms
    base = read stored sourceFor(duration)
    IF empty: fall back to ANY stored base dividing duration
    candles = (base == duration) ? base : groupCandles(base, duration)
    RETURN makeSpotLookup(candles)

makeSpotLookup(candles):
    get(dtstring):
        exact match
        ELSE binary search for the last candle at or before that time
```

The fallback and the binary search both fix real bugs — see `07-bugs-found.md`.

---

# Signal generation

## `processor.js`

```
getActiveDurations(spot, expiry):
    tte = hoursToExpiry(spot, expiry)
    RETURN durations WHERE tte < DURATION_TIMES[d][0] + 1

buildFetchPlan(targetDurations):
    FOR EACH target:
        src = sourceFor(target)
        plan[src].targets.APPEND(target)
        plan[src].hoursNeeded = MAX(existing, DURATION_TIMES[target][0])
    // deduplicated: 5m feeds 5/10/20/40 in ONE download

fetchAndDeriveDurations(symbol, spot, expiry, plan):
    FOR EACH (src, {resolution, hoursNeeded, targets}):
        fetchTo = MIN(expirySettlement, now)     // never request the future
        window  = MIN(hoursNeeded + warmupMargin, PRIOR_DAYS)
        raw     = fetchCandles(...)
        clean   = stripWarmup(raw, src)
        grouped = buildGroupedCandles(clean, src, targets)
    RETURN Map: targetDuration → candles

runSignalsOverCandles(spot, expiry, activeDurations, candlesBySymbol):
    FOR EACH signalDef IN registry:
        IF requiresSpot AND no spot candles: SKIP with warning
        spotIndexByDur = {dur → spotIndexFor(spot, dur)}      // once per duration

        FOR EACH (symbol, durMap), FOR EACH duration:
            candles = filterByDteWindow(durMap[duration], ...)
            sigs    = signalDef.computeSignals(candles, instrument, ctx)
            byDuration[duration][symbol] = sigs

        FOR EACH duration:
            IF UNIVERSE_MAX_ENABLED:
                index = buildUniverseIndex(candlesBySymbol, duration)
                FOR EACH signal:
                    best = universeMaxAt(index, sig.dtstring, type, strike,
                                         {otmOnly: def.otmOnly, spotCandle})
                    sig.universeRatio  = best.ratio
                    sig.universeSymbol = best.symbol

            callRanges = mergeSignals(instrSignals, 'C')
            putRanges  = mergeSignals(instrSignals, 'P')
            writeSignals(...)                    // WRITTEN EVEN IF EMPTY

        removeStaleDurations(...)
        writeExpirySummary(...)

    RETURN {written, bySignal}
```

Empty writes matter: a stricter parameter legitimately produces nothing, and
skipping the write leaves stale files that read as current.

```
buildUniverseIndex(candlesBySymbol, duration):
    FOR EACH symbol:
        tsIndex[dtstring]  = position               // O(1) existence check
        suffixMaxHigh[i]   = max high strictly AFTER i
                             // single backward pass; makes peak lookup O(1)

universeMaxAt(index, signalTs, firingType, firingStrike, {otmOnly, spotCandle}):
    FOR EACH indexed instrument:
        SKIP if type ≠ firingType
        IF otmOnly AND spotCandle:
            SKIP calls with strike <= spot, puts with strike >= spot
        i = tsIndex[signalTs]
        SKIP if undefined            // strike listed later — was not buyable
        ratio = suffixMaxHigh[i] / candles[i].close
        track best
```

## `merger.js`

```
integrateRange(ranges, incoming):
    find ranges overlapping in time
    IF none: insert in place
    ELSE:
        mergeStart = MIN, mergeEnd = MAX
        count += SUM
        maxSignalValue, maxSignalRatio, universeMaxRatio = MAX
        state = priority  activated > pending > slHit
        universeMaxSymbol travels WITH universeMaxRatio
            // else the symbol would be paired with someone else's max
        instruments = concat
```

## `writer.js`

```
writeSignals(...):     temp file + rename        // atomic; a viewer may be reading
removeStaleDurations:  delete files for durations no longer in DURATION_TIMES
writeExpirySummary:    gather across duration dirs → {firedC,firedP,univC,univP,counts}

claimPastExpiry(spot, expiry):
    fs.openSync(path, 'wx')        // exclusive create, atomic at OS level
    IF EEXIST:
        IF claim older than 30 min: unlink and retry     // crashed owner
        ELSE RETURN false
```

Verified: 8 processes racing for one expiry → exactly 1 winner.

---

# Orchestration

## `scheduler.js`

```
weight += 1 / ceil(daysToExpiry)     each iteration
sort DESC by weight, take [0], reset its weight to 0
```

Nearer expiries surface far more often, matching how fast they change.

## `backfill.js`

```
--spot-candles  → fetchAllSpotCandles, honours --from, extends backwards
--candles-only  → phase 1 only, API bound
--signals-only  → phase 2 only, ZERO API calls

FOR EACH (spot, expiry) in range, PAST only:
    IF NOT claimPastExpiry(): SKIP
    TRY:
        phase 1: resume from .progress, skip completed symbols
                 flush progress after EVERY instrument
                 IF any failed: DO NOT mark complete, report INCOMPLETE
        phase 2: computeSignalsFromDisk
    FINALLY: releasePastExpiry()

SIGINT/SIGTERM: release the current claim, exit 130
```

## `live_runner.js`

```
LOOP:
    {future} = scheduler.next()                 // weighted, not round-robin
    FOR EACH spot:
        fetchAllSpotCandles(spot)
        IF isExpired(spot, expiry): SKIP        // rolled over mid-run

        fetch every instrument to MEMORY, bounded concurrency
        {written, bySignal} = runSignalsOverCandles(...)   // writes signal files

        emaByDur = {dur → emaSpread(spotSeries)}
        volByDur = {dur → per-strike priceVolatility, EVERY strike incl. ITM}
        liveSignals = flatten bySignal, keep last LIVE_SIGNAL_WINDOW_HOURS

        WRITE data/live/{spot}/{expiry}.json      // atomic
    every 20 iterations: prune settled snapshots, refresh instruments
    SLEEP(LIVE_LOOP_DELAY_MS)
```

One call does both jobs — the historical signal files and the live snapshot —
because computing them separately ran every signal twice over identical candles.

## `indicators.js`

```
emaSpread(candles, [20,50,100,200]):
    ema seeded with the SMA of the first `period` closes
    entries before the seed are null, not 0
    spreadPct = (max(EMAs) − min(EMAs)) / close × 100
    band = LOG buckets: >1%, 1–0.1%, 0.1–0.01%, 0.01–0.001%, <0.001%

priceVolatility(candles, [5,10]):
    dist = SAME measure as otm_wall
    vol  = dist / (open × close)          // DIVIDED, not multiplied
    // a low reading at a HIGH price means premium HELD, not decayed
    // no log10: this lives in a narrow band near zero where logs obscure

bandOf(value, bands):
    RETURN index of the SMALLEST max the value falls under
    // order-independent: EMA bands run widest-first, volatility tightest-first
```

---

# Analysis

## `quality.js`

```
moneynessOf(range, spot, expiry, duration):
    spotCandle = spotIndexFor(spot, duration).get(range.startTs)
    IF none: RETURN null            // counted and reported, never bucketed
    strike = parse(range[8] ?? instruments[0])
    RETURN (type=='C' ? 1 : -1) × (strike − spot) / spot × 100

payoffOf(range) = RATIO_SOURCE=='universe' ? range[7] : range[4]

collectRanges: settled expiries only, apply --type filter,
               tag each row with tteBucket and mnyBucket

BY.length == 1 → one row per bucket, ALL configured buckets shown
BY.length == 2 → cross-tab, full axes on both sides
BY.length == 3 → one cross-tab per value of dim 1, ONE global best star

cells below QUALITY_MIN_CELL_SAMPLE (30) parenthesised, never starred
```

Showing all configured buckets matters: an absent bucket previously vanished,
making the output look like a different bucket set was configured.

## `trades.js`

```
findTrades(candles):                     // iterative with an explicit stack
    stack = [[0, len-1]]
    WHILE stack not empty:
        [lo, hi] = pop
        IF hi − lo < 1: CONTINUE
        highIdx = argmax(high) in [lo,hi]
        IF highIdx == lo: push [lo+1, hi]; CONTINUE      // nothing before it
        lowIdx = argmin(low) in [lo, highIdx−1]          // STRICTLY before
        RECORD {lowIdx, highIdx, ratio = high/low}
        push [lo, lowIdx−1]                              // trade consumes its own
        push [highIdx+1, hi]

// Split is INDEPENDENT of the threshold; filtering happens afterwards.
// 10, 100, 0.1, 50 gives 10x at top level but 500x in the right partition —
// filtering during recursion would prune the branch containing it.

// Iterative because a monotonic decline over 11,500 candles would recurse
// deep enough to blow the call stack.

mergeTrades(entries, durationMinutes):
    sort by start; merge overlapping
    REFUSE a merge that would EXTEND the window beyond
        TRADE_MAX_MERGE_SPAN_CANDLES × duration
    // caps the EXTENSION, not absolute span: a single trade can legitimately
    // run for days, and capping span left six identical 90h windows unmerged
```

Strictly-before is required because within one candle there is no way to know
whether the low preceded the high.

## `multibaggers.js`

```
bestTrade(candles):                       // O(n), one backward pass
    runMax = −inf
    FOR i = len−1 DOWN TO 0:
        IF i < len−1 AND close[i] > 0:
            ratio = runMax / close[i]     // runMax covers only candles AFTER i
            track best
        IF high[i] > runMax: runMax = high[i]; runMaxIdx = i
```

Order inside the loop is the subtle part: the ratio is computed **before**
folding candle `i` into `runMax`. Reverse them and an entry could sell into its
own candle's high.

Perfect hindsight, deliberately — it is the ceiling, and the denominator that
makes recall computable.

---

# Query pipeline

## `patterns.js` — stage 1

```
FOR EACH (spot, expiry) in range, PAST only:
    IF _done marker exists AND NOT --force: SKIP

    FOR EACH duration:
        read candles ONCE into candlesBySymbol      // reading dominates cost
        spotIdx = spotIndexFor(spot, duration)

        FOR EACH signalDef:
            FOR EACH (symbol, candles):
                sigs = signalDef.computeSignals(
                          candles, instrument, ctx,
                          {minSignalValue: 0})       // ← keeps EVERY match
                rows.APPEND(toRow(sig, ctx))
            WRITE patterns/{signalId}/{spot}/{duration}/{expiry}.json

    WRITE _done marker
```

Rows are **unmerged**, one per instrument, with every field the signal computed —
38 queryable fields. Merging is lossy and would discard exactly what a query
wants. See `05-query-tool.md` for the row shape and the language.
