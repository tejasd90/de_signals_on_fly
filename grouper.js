// grouper.js
// ─────────────────────────────────────────────────────────────────────────────
// Pure in-memory candle grouping. No disk I/O.
// Reuses the getDurationCandles + getKeyDuration logic from the original utils.js
// with one change: intermediate grouped candles are not retained after use.
//
// Sourcing is computed, not configured: see sourceFor(). Each duration is built
// in ONE step from the largest direct-fetch duration that divides it.
//   (direct durations: 5, 15, 30, 60, 120, 240, 720, 1440)
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg    = require('./config');
const api    = require('./api');
const logger = require('./logger');

// ─── Key duration computation ─────────────────────────────────────────────────

// TIMEZONE-INDEPENDENT slot assignment.
//
// The original anchored slots with `new Date(dtstring).setHours(17, 30, 0, 0)`,
// which resolves 17:30 in the HOST's timezone. Under IST that is the intended
// anchor; under UTC it is a different absolute instant, so every candle lands in
// a different slot and grouped candles silently disagree between machines. This
// was observed directly: regrouping the same stored candles produced 266
// mismatches under UTC and 0 under IST.
//
// Here the instant is shifted by the IST offset and UTC getters are used, so the
// 17:30 IST anchor is computed identically no matter what timezone the process
// runs in. Parsing `dtstring` is already safe because it carries an explicit
// +0530 offset.
function getKeyDuration(durationMins, dtstring) {
    const MINUTE_MS = 60000;

    // Absolute instant, then shifted so UTC getters read IST wall-clock fields.
    const istMs = new Date(dtstring).getTime() + api.IST_OFFSET_MS;
    const d     = new Date(istMs);

    // 17:30 IST on the same IST calendar day as this candle.
    const anchorMs = Date.UTC(
        d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 17, 30, 0, 0
    );

    const diffMins = Math.floor((istMs - anchorMs) / MINUTE_MS);
    const slot     = Math.floor(diffMins / durationMins);
    const slotMs   = anchorMs + slot * durationMins * MINUTE_MS;

    const s   = new Date(slotMs);
    const pad = n => String(n).padStart(2, '0');
    return `${s.getUTCFullYear()}-${pad(s.getUTCMonth() + 1)}-${pad(s.getUTCDate())}` +
           `T${pad(s.getUTCHours())}:${pad(s.getUTCMinutes())}:00+0530`;
}

// ─── Grouping ─────────────────────────────────────────────────────────────────

/**
 * Group an array of fine-grained candles into target-duration candles.
 * Identical to original utils.getDurationCandles.
 *
 * @param {Object[]} candles     — source candles with { dtstring, open, high, low, close, volume }
 * @param {number}   durationMins
 * @returns {Object[]}           — grouped candles, sorted ascending by dtstring
 */
function groupCandles(candles, durationMins) {
    const groups = {};

    for (const c of candles) {
        const key = getKeyDuration(durationMins, c.dtstring);
        if (!groups[key]) {
            groups[key] = { open: c.open, high: c.high, low: c.low, close: c.close,
                            volume: c.volume, openDt: c.dtstring, closeDt: c.dtstring };
        } else {
            const g = groups[key];
            if (c.dtstring < g.openDt)  { g.open = c.open;   g.openDt  = c.dtstring; }
            if (c.dtstring > g.closeDt) { g.close = c.close; g.closeDt = c.dtstring; }
            if (c.high > g.high) g.high = c.high;
            if (c.low  < g.low || g.low === 0) g.low = c.low;
            g.volume += c.volume;
        }
    }

    return Object.entries(groups)
        .sort(([a], [b]) => a < b ? -1 : 1)
        .map(([key, g]) => ({
            dtstring: key,
            time:     api.dateToUnix(key),
            open:     g.open,
            high:     g.high,
            low:      g.low,
            close:    g.close,
            volume:   g.volume,
        }));
}

// ─── Strip warm-up candles ────────────────────────────────────────────────────

/**
 * Remove leading warm-up candles from a freshly-fetched instrument.
 *
 * Two steps, matching the original code's intent:
 *   1. Drop everything up to and including the last candle with low <= 0.1
 *      (the instrument had not really started trading yet).
 *   2. Drop a further warm-up window where broker prices are unreliable.
 *
 * IMPORTANT: the original SKIP_INITIAL_CANDLES (20) was calibrated for 5-minute
 * base candles, i.e. a 100-minute warm-up window. Applying a fixed count of 20
 * to coarse durations would discard 20 days of 1d candles. So the warm-up is
 * expressed as a TIME window and converted to a candle count per duration:
 *
 *     warmupCandles = ceil(SKIP_INITIAL_CANDLES * 5 / durationMins)
 *
 *   5m  -> 20 candles (100 min)  — identical to original behaviour
 *   15m ->  7 candles
 *   1h  ->  2 candles
 *   1d  ->  1 candle
 *
 * @param {Object[]} candles
 * @param {number}   durationMins — duration of the candles being stripped
 * @returns {Object[]}            — [] if not enough candles remain
 */
function stripWarmup(candles, durationMins = 5) {
    if (!candles || candles.length === 0) return [];

    // Step 1: find the last leading candle that is still untraded (low <= 0.1)
    const firstRealIdx = candles.findIndex(c => c.low > 0.1);
    if (firstRealIdx < 0) return [];
    const after = candles.slice(firstRealIdx);

    // Step 2: time-scaled warm-up skip
    const warmupMinutes = cfg.SKIP_INITIAL_CANDLES * 5;
    const warmupCandles = Math.max(1, Math.ceil(warmupMinutes / durationMins));

    if (after.length <= warmupCandles) return [];
    return after.slice(warmupCandles);
}

// ─── Build full duration map for one instrument ───────────────────────────────

/**
 * The source duration that `duration` should be built from: the LARGEST
 * direct-fetch duration that divides it evenly.
 *
 * This replaces the old hand-maintained GROUPING_CHAIN. Two advantages:
 *
 *   Fewer steps. Every duration is now exactly one grouping away from its
 *   source. The chain took 360m through 15 -> 45 -> 90 -> 180 -> 360; the
 *   largest divisor of 360 among direct durations is 120, so it is one step.
 *
 *   Less to fetch. A larger source means fewer source candles for the same
 *   span — 90m built from 30m reads a third as many candles as from 15m.
 *
 * Returns the duration itself when it is directly fetchable.
 * Returns null if nothing divides it, which means DIRECT_DURATIONS needs an
 * entry — surfaced loudly rather than silently producing no candles.
 */
function sourceFor(duration) {
    if (cfg.DIRECT_DURATIONS[duration]) return duration;

    const divisors = Object.keys(cfg.DIRECT_DURATIONS)
        .map(Number)
        .filter(s => duration % s === 0);

    if (divisors.length === 0) {
        logger.error('grouper',
            `No direct-fetch duration divides ${duration}m — add a divisor to DIRECT_DURATIONS`);
        return null;
    }
    return Math.max(...divisors);
}

/**
 * Group `targetDurations` from a single source candle array.
 *
 * Every target must have sourceFor(target) === sourceDuration; with the divisor
 * rule that is always a one-step grouping, so no intermediate durations are
 * created and nothing needs discarding.
 *
 * @param {Object[]} sourceCandles
 * @param {number}   sourceDuration
 * @param {number[]} targetDurations
 * @returns {Map<number, Object[]>} duration -> candles (includes the source
 *          itself when it appears in targetDurations)
 */
function buildGroupedCandles(sourceCandles, sourceDuration, targetDurations) {
    const result = new Map();

    for (const target of targetDurations) {
        if (target === sourceDuration) {
            result.set(target, sourceCandles);
            continue;
        }
        if (sourceFor(target) !== sourceDuration) {
            logger.error('grouper',
                `${target}m does not derive from ${sourceDuration}m — skipped`);
            continue;
        }
        const grouped = groupCandles(sourceCandles, target);
        result.set(target, grouped);
        logger.debug('grouper',
            `Grouped ${sourceDuration}m -> ${target}m: ${sourceCandles.length} -> ${grouped.length}`);
    }

    return result;
}

module.exports = {
    groupCandles,
    stripWarmup,
    buildGroupedCandles,
    getKeyDuration,
    sourceFor,
};
