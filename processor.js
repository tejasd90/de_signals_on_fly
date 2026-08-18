// processor.js
// ─────────────────────────────────────────────────────────────────────────────
// Two entry points, one shared signal core.
//
//   processFutureExpiry — live expiries. Candles are fetched to MEMORY and
//                         discarded after use. Nothing is persisted except the
//                         resulting signals, because a live expiry's candles are
//                         still changing and would be stale the moment they hit
//                         disk. Called by main.js.
//
//   processPastExpiry   — settled expiries, in two independent phases:
//                           Phase 1 (fetchAndStorePastCandles): fetch base
//                             candles once, write to disk, mark candles_complete.
//                             Expensive — API bound.
//                           Phase 2 (computeSignalsFromDisk): read from disk,
//                             group, run signals, write, mark signals_complete.
//                             Cheap — CPU bound, zero API calls.
//                         Phase 2 can be re-run any number of times after a
//                         parameter change without repeating phase 1.
//                         Called by backfill.js.
//
// Both paths converge on runSignalsOverCandles(), so a signal behaves identically
// whether its candles came from the network or from disk.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg         = require('./config');
const logger      = require('./logger');
const api         = require('./api');
const instr       = require('./instruments');
const grouper     = require('./grouper');
const registry    = require('./signal_registry');
const spotStore   = require('./spot_store');
const merger      = require('./merger');
const writer      = require('./writer');
const expiryMod   = require('./expiry');
const candleStore = require('./candle_store');

// ─── Concurrency limiter ──────────────────────────────────────────────────────

async function runWithConcurrency(tasks, limit) {
    const results = [];
    let i = 0;

    async function worker() {
        while (i < tasks.length) {
            const idx = i++;
            results[idx] = await tasks[idx]();
        }
    }

    const workers = Array.from({ length: Math.min(limit, tasks.length) }, worker);
    await Promise.all(workers);
    return results;
}

// ─── Duration planning ────────────────────────────────────────────────────────

/**
 * Durations whose start window is currently reachable for this (spot, expiry).
 * For a settled expiry time-to-expiry is negative, so every duration qualifies.
 */
function getActiveDurations(spot, expiryDate) {
    const tteHours = expiryMod.hoursToExpiry(spot, expiryDate);

    return Object.entries(cfg.DURATION_TIMES)
        .filter(([, window]) => tteHours < (window[0] ?? Infinity) + 1)
        .map(([dur]) => parseInt(dur))
        .sort((a, b) => a - b);
}

/**
 * Build the fetch plan: which source durations to fetch, over what window, and
 * which target durations each one produces.
 *
 * Sources are DEDUPLICATED. Several targets often share a source (5m feeds 5,
 * 10, 20 and 40), so the source is fetched once over the widest window any of
 * its targets needs, and every target is derived from that one download. Left
 * un-deduplicated this would be 22 requests per instrument; deduplicated it is 13.
 *
 * @param {number[]} targetDurations
 * @returns {Map<number, {resolution:string, hoursNeeded:number, targets:number[]}>}
 */
function buildFetchPlan(targetDurations) {
    const plan = new Map();

    for (const dur of targetDurations) {
        const src = grouper.sourceFor(dur);
        if (src === null) continue;

        const resolution = cfg.DIRECT_DURATIONS[src];
        if (!resolution) {
            logger.error('scheduler', `No resolution for source ${src}m (target ${dur}m)`);
            continue;
        }

        // Each target needs its own window of SOURCE history to be built from.
        const hoursNeeded = cfg.DURATION_TIMES[dur]?.[0] ?? 0;
        const existing    = plan.get(src);

        if (!existing) {
            plan.set(src, { resolution, hoursNeeded, targets: [dur] });
        } else {
            existing.hoursNeeded = Math.max(existing.hoursNeeded, hoursNeeded);
            existing.targets.push(dur);
        }
    }

    return plan;
}

// ─── Fetching ─────────────────────────────────────────────────────────────────

/**
 * Fetch one instrument's base candles from the API.
 *
 * The fetch END is clamped to now(): requesting candles beyond the present for a
 * live expiry only wastes paginated requests.
 *
 * @returns {Map<number, Object[]>} sourceDuration → cleaned candles
 */
async function fetchSourceCandles(symbol, spot, expiryDate, fetchPlan) {
    const expiryS = expiryMod.expiryUnix(spot, expiryDate);
    const nowS    = Math.floor(Date.now() / 1000);
    const fetchTo = Math.min(expiryS, nowS);
    const result  = new Map();

    for (const [srcDur, { resolution, hoursNeeded }] of fetchPlan) {
        const warmupMargin = cfg.SKIP_INITIAL_CANDLES * 5 * 60;   // seconds
        const windowSecs   = Math.min(
            hoursNeeded * 3600 + warmupMargin,
            cfg.PRIOR_DAYS * 24 * 3600
        );
        const fetchFrom = fetchTo - windowSecs;

        // No try/catch: api.fetchCandles has already exhausted its retries, so a
        // throw here is final. Swallowing it would store a partial series and let
        // the expiry be marked complete with missing data — silent and permanent.
        // The caller records the failure and leaves the expiry resumable instead.
        const raw   = await api.fetchCandles(`MARK:${symbol}`, resolution, fetchFrom, fetchTo);
        const clean = grouper.stripWarmup(raw, srcDur);
        result.set(srcDur, clean);

        logger.log('fetcher',
            `${symbol} src=${srcDur}m (${resolution}) window=${(windowSecs / 86400).toFixed(1)}d: ` +
            `${raw.length} raw -> ${clean.length} after warmup strip`);
    }

    return result;
}

// ─── DTE window filter ────────────────────────────────────────────────────────

/**
 * Keep candles no further from expiry than this duration's start window.
 * No end cutoff — candles run right up to expiry, because genuine multibaggers
 * do occur in the final hours.
 */
function filterByDteWindow(candles, spot, expiryDate, durationMins) {
    const startHours = cfg.DURATION_TIMES[durationMins]?.[0] ?? Infinity;
    const expiryMs   = expiryMod.expiryMillis(spot, expiryDate);

    return candles.filter(c => {
        const tteHours = (expiryMs - new Date(c.dtstring).getTime()) / 3600000;
        return tteHours <= startHours + 1;
    });
}

// ─── Universe max ratio ───────────────────────────────────────────────────────

/**
 * Build a lookup index over every instrument's candles at one duration.
 *
 * For each symbol:
 *   tsIndex      — dtstring -> candle position, so "does a candle exist at the
 *                  signal timestamp" is O(1)
 *   suffixMaxHigh[i] — highest high across candles AFTER position i, so the peak
 *                  reachable from an entry at i is also O(1)
 *
 * Built once per duration. Without it, scoring every signal against every
 * instrument would rescan candle arrays and turn quadratic.
 */
function buildUniverseIndex(candlesBySymbol, duration) {
    const index = new Map();

    for (const [symbol, byDuration] of candlesBySymbol) {
        const candles = byDuration.get(duration);
        if (!candles || candles.length < 2) continue;

        const parsed = instr.parseSymbol(symbol);
        if (!parsed.type || !isFinite(parsed.strike)) continue;

        const tsIndex = new Map();
        for (let i = 0; i < candles.length; i++) tsIndex.set(candles[i].dtstring, i);

        // Backward pass: suffixMaxHigh[i] = max high strictly after i.
        const suffixMaxHigh = new Float64Array(candles.length);
        let running = -Infinity;
        for (let i = candles.length - 1; i >= 0; i--) {
            suffixMaxHigh[i] = running;
            if (candles[i].high > running) running = candles[i].high;
        }

        index.set(symbol, {
            candles, tsIndex, suffixMaxHigh,
            type: parsed.type, strike: parsed.strike,
        });
    }

    return index;
}

/**
 * Best payoff available at `signalTs` across all eligible instruments.
 *
 * Entry is that instrument's own close at the signal timestamp; the payoff is its
 * highest subsequent high divided by that close. Same measurement as
 * red_squeeze's signalRatio, just applied to instruments that never fired.
 *
 * @returns {{ratio:number, symbol:string|null}}
 */
function universeMaxAt(universeIndex, signalTs, firingType, firingStrike, opts = {}) {
    // otmOnly: for a signal that only fires on OTM options, reporting an ITM
    // strike's payoff as "what was available" would undercut the restriction.
    const { otmOnly = false, spotCandle = null } = opts;
    let bestRatio  = 0;
    let bestSymbol = null;

    for (const [symbol, e] of universeIndex) {
        if (e.type !== firingType) continue;

        if (cfg.UNIVERSE_MAX_MODE === 'further_otm') {
            // Further from the money than the strike that fired. Higher strikes
            // for calls, lower for puts. The firing strike itself is included,
            // so this can only ever match or beat maxSignalRatio.
            if (firingType === 'C' && e.strike < firingStrike) continue;
            if (firingType === 'P' && e.strike > firingStrike) continue;
        }

        if (otmOnly && spotCandle) {
            const sp = spotCandle.close;
            if (e.type === 'C' && e.strike <= sp) continue;
            if (e.type === 'P' && e.strike >= sp) continue;
        }

        // Must have been buyable at the signal: a strike listed later was not.
        const i = e.tsIndex.get(signalTs);
        if (i === undefined) continue;

        const entry = e.candles[i].close;
        if (!(entry > 0)) continue;

        const peak = e.suffixMaxHigh[i];
        if (!isFinite(peak)) continue;

        const ratio = peak / entry;
        if (ratio > bestRatio) { bestRatio = ratio; bestSymbol = symbol; }
    }

    return { ratio: Math.round(bestRatio * 1000) / 1000, symbol: bestSymbol };
}

// ─── Shared signal core ───────────────────────────────────────────────────────

/**
 * Run the signal over already-grouped candles, merge across instruments, write.
 *
 * Takes candles keyed by TARGET duration, not by source. Both callers do their
 * own grouping first — the disk path does none at all, because every duration is
 * stored directly. This keeps behaviour identical for live and historical runs.
 *
 * @param {string}   spot
 * @param {string}   expiryDate
 * @param {number[]} activeDurations
 * @param {Map<string, Map<number, Object[]>>} candlesBySymbol
 *        symbol -> (targetDuration -> candles)
 * Returns both the file count AND the computed signals. live_runner needs the
 * same signals for its snapshot, and recomputing them there would run every
 * signal twice over identical candles for no reason.
 *
 * @returns {{ written:number, bySignal:Map<string,Map<number,Map<string,Object[]>>> }}
 *          bySignal: signalId -> duration -> symbol -> signals[]
 */
function runSignalsOverCandles(spot, expiryDate, activeDurations, candlesBySymbol, opts = {}) {
    const signalDefs = registry.activeSignals(opts.signalIds || null);
    let written = 0;
    const bySignal = new Map();

    for (const def of signalDefs) {
        // Spot candles are grouped per duration, so load them once per duration
        // rather than once per instrument.
        const spotIndexByDur = new Map();
        if (def.requiresSpot) {
            if (!spotStore.hasSpotCandles(spot)) {
                logger.log('scheduler',
                    `${def.id}: no spot candles stored for ${spot} — skipping. ` +
                    `Run backfill.js --spot-candles first.`);
                continue;
            }
            for (const dur of activeDurations) {
                spotIndexByDur.set(dur, spotStore.spotIndexFor(spot, dur));
            }
        }

        // durationMins -> Map<symbol, signals[]>
        const byDuration = new Map();
        for (const dur of activeDurations) byDuration.set(dur, new Map());

        for (const [symbol, durMap] of candlesBySymbol) {
            const parsed = instr.parseSymbol(symbol);
            const instrument = { symbol, type: parsed.type, strike: parsed.strike };

            for (const dur of activeDurations) {
                const raw = durMap.get(dur);
                if (!raw || raw.length === 0) continue;

                const candles = filterByDteWindow(raw, spot, expiryDate, dur);
                if (candles.length < 2) continue;

                const ctx = {
                    spotByTs:   spotIndexByDur.get(dur) || new Map(),
                    duration:   dur,
                    expiryDate,
                    spot,
                };

                let sigs = [];
                try {
                    sigs = def.computeSignals(candles, instrument, ctx) || [];
                } catch (err) {
                    logger.error('scheduler',
                        `${def.id} threw on ${symbol} ${dur}m`, err);
                    continue;
                }
                if (sigs.length) byDuration.get(dur).set(symbol, sigs);
            }
        }

        // Universe max, then merge and write — per duration.
        for (const dur of activeDurations) {
            const instrSignals = byDuration.get(dur);

            if (cfg.UNIVERSE_MAX_ENABLED && instrSignals.size) {
                const universeIndex = buildUniverseIndex(candlesBySymbol, dur);
                const spotByTs      = spotIndexByDur.get(dur) || new Map();

                for (const [symbol, sigs] of instrSignals) {
                    const p = instr.parseSymbol(symbol);
                    for (const sig of sigs) {
                        const best = universeMaxAt(universeIndex, sig.dtstring, p.type, p.strike, {
                            otmOnly:    def.otmOnly,
                            spotCandle: spotByTs.get(sig.dtstring) || null,
                        });
                        sig.universeRatio  = best.ratio;
                        sig.universeSymbol = best.symbol;
                    }
                }
            }

            const callRanges = instrSignals.size ? merger.mergeSignals(instrSignals, 'C') : [];
            const putRanges  = instrSignals.size ? merger.mergeSignals(instrSignals, 'P') : [];

            // Written even when empty: a stricter parameter legitimately produces
            // nothing where a previous run produced signals, and skipping the
            // write would leave stale results in place.
            writer.writeSignals(def.id, spot, dur, expiryDate, callRanges, putRanges);
            if (callRanges.length || putRanges.length) written++;
        }

        writer.removeStaleDurations(def.id, spot, expiryDate, activeDurations);

        // Written after every duration for this expiry has been persisted, so it
        // reflects the complete set rather than a partial one.
        writer.writeExpirySummary(def.id, spot, expiryDate);

        bySignal.set(def.id, byDuration);
    }

    return { written, bySignal };
}

/**
 * Fetch sources for one instrument and derive every target duration from them.
 * Shared by the live path and the storage path.
 *
 * @returns {Map<number, Object[]>} targetDuration -> candles
 */
async function fetchAndDeriveDurations(symbol, spot, expiryDate, fetchPlan) {
    const sourceCandles = await fetchSourceCandles(symbol, spot, expiryDate, fetchPlan);
    const byDuration    = new Map();

    for (const [srcDur, { targets }] of fetchPlan) {
        const src = sourceCandles.get(srcDur) || [];
        if (src.length === 0) continue;

        const grouped = grouper.buildGroupedCandles(src, srcDur, targets);
        for (const [dur, candles] of grouped) byDuration.set(dur, candles);
    }

    return byDuration;
}

// ─── FUTURE path (in memory) ──────────────────────────────────────────────────

/**
 * Process a live expiry. Candles are fetched to memory, used, and discarded.
 *
 * Rollover guard: an expiry can settle between the scheduler selecting it and
 * this function running. If that has happened, bail out and leave it to the
 * past path, which will fetch the complete history and store it properly.
 */
async function processFutureExpiry(spot, expiryDate) {
    if (expiryMod.isExpired(spot, expiryDate)) {
        logger.log('scheduler',
            `Rolled over to past during scheduling, skipping future path: ${spot}/${expiryDate}`);
        return { skipped: 'rolled_over' };
    }

    const activeDurations = getActiveDurations(spot, expiryDate);
    if (activeDurations.length === 0) {
        logger.log('scheduler', `${spot}/${expiryDate}: no active durations`);
        return { skipped: 'no_durations' };
    }

    const instrumentsObj = instr.loadInstruments(spot, expiryDate);
    const symbols        = Object.keys(instrumentsObj).filter(s => s !== '-');
    if (symbols.length === 0) {
        logger.log('scheduler', `${spot}/${expiryDate}: no instruments`);
        return { skipped: 'no_instruments' };
    }

    const fetchPlan = buildFetchPlan(activeDurations);

    logger.log('scheduler',
        `FUTURE ${spot}/${expiryDate}: ${symbols.length} instruments, ` +
        `durations=[${activeDurations.join(',')}]`);

    const tasks = symbols.map(symbol => async () => ({
        symbol,
        byDuration: await fetchAndDeriveDurations(symbol, spot, expiryDate, fetchPlan),
    }));

    const fetched = await runWithConcurrency(tasks, cfg.MAX_CONCURRENT_INSTRUMENT_FETCHES);

    const candlesBySymbol = new Map();
    for (const { symbol, byDuration } of fetched) candlesBySymbol.set(symbol, byDuration);

    const { written } = runSignalsOverCandles(spot, expiryDate, activeDurations, candlesBySymbol);
    logger.log('scheduler', `FUTURE ${spot}/${expiryDate}: wrote ${written} duration files`);

    return { written };
}

// ─── PAST path, phase 1: fetch and store ──────────────────────────────────────

/**
 * Fetch every instrument's base candles for a settled expiry and write them to
 * disk. Idempotent: does nothing if candles_complete is already set, unless
 * `force` is passed.
 *
 * Uses the FULL PRIOR_DAYS window (fullWindow = true) rather than the current
 * DURATION_TIMES needs, so that widening a window later does not force a refetch.
 */
async function fetchAndStorePastCandles(spot, expiryDate, { force = false } = {}) {
    if (!force && candleStore.isCandlesComplete(spot, expiryDate)) {
        return { skipped: 'already_stored' };
    }

    if (!expiryMod.isExpired(spot, expiryDate)) {
        logger.log('scheduler', `Not yet settled, refusing to store: ${spot}/${expiryDate}`);
        return { skipped: 'not_expired' };
    }

    const instrumentsObj = instr.loadInstruments(spot, expiryDate);
    const symbols        = Object.keys(instrumentsObj).filter(s => s !== '-');
    if (symbols.length === 0) return { skipped: 'no_instruments' };

    // Store EVERY configured duration, each trimmed to its own DURATION_TIMES
    // window. Sources are fetched deduplicated and discarded after grouping —
    // only the target durations reach disk.
    const allDurations = Object.keys(cfg.DURATION_TIMES).map(Number);
    const fetchPlan    = buildFetchPlan(allDurations);

    logger.log('candle_store',
        `STORE ${spot}/${expiryDate}: ${symbols.length} instruments, ` +
        `sources=[${[...fetchPlan.keys()].join(',')}] -> durations=[${allDurations.join(',')}]`);

    // Resume: skip symbols a previous interrupted run already completed.
    const progress  = force ? { done: [], failed: [] }
                            : candleStore.readProgress(spot, expiryDate);
    const doneSet   = new Set(progress.done);
    const todo      = symbols.filter(sym => !doneSet.has(sym));

    if (doneSet.size > 0) {
        logger.log('candle_store',
            `RESUME ${spot}/${expiryDate}: ${doneSet.size} instruments already done, ` +
            `${todo.length} remaining`);
    }

    // Shared mutable progress, flushed after every instrument so an interruption
    // at any point loses at most one instrument's work.
    const state = { done: [...progress.done], failed: [] };
    let totalCandles = 0;

    const tasks = todo.map(symbol => async () => {
        try {
            const byDuration = await fetchAndDeriveDurations(symbol, spot, expiryDate, fetchPlan);

            let stored = 0;
            for (const [dur, candles] of byDuration) {
                if (candles.length === 0) continue;

                // Trim to this duration's own window before writing. A source
                // fetched wide enough for its longest-window target would
                // otherwise persist far more history than the shorter-window
                // targets ever read — this trim is the ~79% disk saving.
                const trimmed = filterByDteWindow(candles, spot, expiryDate, dur);
                if (trimmed.length === 0) continue;

                candleStore.writeCandles(spot, expiryDate, dur, symbol, trimmed);
                stored += trimmed.length;
            }

            totalCandles += stored;
            state.done.push(symbol);
        } catch (err) {
            // Retries already exhausted inside api.fetchCandles.
            state.failed.push({ symbol, error: err.message.substring(0, 200) });
            logger.error('candle_store', `Instrument failed: ${spot}/${expiryDate}/${symbol}`, err);
        }

        candleStore.writeProgress(spot, expiryDate, state);
    });

    await runWithConcurrency(tasks, cfg.MAX_CONCURRENT_INSTRUMENT_FETCHES);

    const mb = (candleStore.diskUsage(spot, expiryDate) / 1048576).toFixed(1);

    // CRITICAL: only declare the expiry complete when every instrument succeeded.
    // Marking it complete with failures present would make the gap permanent —
    // every later run skips the expiry, and the missing instruments are never
    // noticed because nothing distinguishes them from instruments that genuinely
    // had no data.
    if (state.failed.length > 0) {
        logger.error('candle_store',
            `INCOMPLETE ${spot}/${expiryDate}: ${state.failed.length} of ${symbols.length} ` +
            `instruments failed — NOT marked complete, re-run to resume`);
        return {
            incomplete: true,
            instruments: symbols.length,
            succeeded:   state.done.length,
            failed:      state.failed.length,
            candles:     totalCandles,
            mb,
        };
    }

    candleStore.markCandlesComplete(spot, expiryDate, {
        instruments: symbols.length,
        candles:     totalCandles,
        priorDays:   cfg.PRIOR_DAYS,
    });
    candleStore.clearProgress(spot, expiryDate);

    logger.log('candle_store',
        `STORE ${spot}/${expiryDate} done: ${totalCandles} candles, ${mb} MB`);

    return { instruments: symbols.length, candles: totalCandles, mb };
}

// ─── PAST path, phase 2: signals from disk ────────────────────────────────────

/**
 * Compute signals for a settled expiry using candles already on disk.
 * Zero API calls. Safe to re-run after any signal parameter change.
 */
function computeSignalsFromDisk(spot, expiryDate) {
    if (!candleStore.isCandlesComplete(spot, expiryDate)) {
        return { skipped: 'no_candles' };
    }

    const activeDurations = getActiveDurations(spot, expiryDate);
    if (activeDurations.length === 0) return { skipped: 'no_durations' };

    const storedDurations = candleStore.storedDurations(spot, expiryDate);

    const missing = activeDurations.filter(d => !storedDurations.includes(d));
    if (missing.length > 0) {
        // Happens when DURATION_TIMES gained a duration after these candles were
        // stored. Surfaced rather than silently under-reporting.
        logger.log('candle_store',
            `${spot}/${expiryDate}: durations [${missing.join(',')}] not stored — ` +
            `re-run with --candles-only --force-candles to add them`);
    }

    // Every duration is stored directly, so there is NO grouping on this path.
    // symbol -> (duration -> candles)
    const candlesBySymbol = new Map();
    for (const dur of storedDurations) {
        if (!activeDurations.includes(dur)) continue;
        for (const symbol of candleStore.storedSymbols(spot, expiryDate, dur)) {
            if (!candlesBySymbol.has(symbol)) candlesBySymbol.set(symbol, new Map());
            candlesBySymbol.get(symbol)
                .set(dur, candleStore.readCandles(spot, expiryDate, dur, symbol));
        }
    }

    if (candlesBySymbol.size === 0) return { skipped: 'no_stored_candles' };

    logger.log('scheduler',
        `SIGNALS ${spot}/${expiryDate}: ${candlesBySymbol.size} instruments from disk, ` +
        `durations=[${activeDurations.join(',')}]`);

    const { written } = runSignalsOverCandles(spot, expiryDate, activeDurations, candlesBySymbol);

    writer.markSignalsComplete(spot, expiryDate);
    return { instruments: candlesBySymbol.size, written };
}

// ─── PAST path: both phases ───────────────────────────────────────────────────

/**
 * Convenience wrapper: store candles if needed, then compute signals.
 *
 * @param {object} opts
 *   forceCandles — refetch candles even if already stored
 *   forceSignals — recompute signals even if signals_complete is set
 */
async function processPastExpiry(spot, expiryDate, opts = {}) {
    const { forceCandles = false, forceSignals = false } = opts;

    const stored = await fetchAndStorePastCandles(spot, expiryDate, { force: forceCandles });

    if (!forceSignals && writer.isSignalsComplete(spot, expiryDate)) {
        return { ...stored, signals: 'already_complete' };
    }

    const signals = computeSignalsFromDisk(spot, expiryDate);
    return { ...stored, signals };
}

module.exports = {
    fetchAndDeriveDurations,
    buildUniverseIndex,
    universeMaxAt,
    processFutureExpiry,
    processPastExpiry,
    fetchAndStorePastCandles,
    computeSignalsFromDisk,
    runSignalsOverCandles,
    getActiveDurations,
    buildFetchPlan,
};
