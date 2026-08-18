// expiry.js
// ─────────────────────────────────────────────────────────────────────────────
// Single source of truth for settlement (expiry) times.
//
// WHY THIS FILE EXISTS
// Different underlyings settle at different times of day on Delta Exchange.
// BTC and ETH options settle at 17:30 IST; XAUT (tokenised gold) follows a
// different schedule. The original code hardcoded 'T17:30:00+0530' in six
// separate places, which silently mis-times every window for any spot that
// does not settle at 17:30.
//
// Getting this wrong is not cosmetic. The settlement timestamp drives:
//   - the scheduler's past/future classification and priority weights
//   - the candle fetch END boundary
//   - the [startHours, endHours] DTE window per duration
//   - the past-complete decision
// A few hours of error shifts every one of those.
//
// HOW IT RESOLVES, in priority order:
//   1. A settlement time learned from the API (authoritative — see
//      recordSettlementTime, populated by instruments.js from
//      product.settlement_time).
//   2. A per-spot override in SETTLEMENT_TIME_BY_SPOT below.
//   3. DEFAULT_SETTLEMENT_TIME.
//
// Because step 1 reads the exchange's own settlement_time, XAUT and any future
// listing are handled with no code change. The overrides are a fallback for
// when instrument data has not been fetched yet.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const logger = require('./logger');

// Fallback used when nothing better is known.
// Format: 'HH:MM:SS±HHMM'
const DEFAULT_SETTLEMENT_TIME = '17:30:00+0530';

// Per-spot overrides, used only when the API has not supplied a settlement
// time for that (spot, expiry). Keys are uppercase spot symbols.
//
// NOTE: these are fallbacks, not assertions. If the API reports a different
// time, the API wins. Add entries here only if you want correct behaviour
// before the first instrument fetch completes.
const SETTLEMENT_TIME_BY_SPOT = {
    BTC:  '17:30:00+0530',
    ETH:  '17:30:00+0530',
    // XAUT settles on a different schedule to BTC/ETH. The value below is a
    // placeholder fallback only — the real time is taken from the API's
    // settlement_time field as soon as instruments are fetched.
    // Update this if you want the fallback itself to be accurate.
    XAUT: '17:30:00+0530',
};

// ─── Learned settlement times (populated from the API) ────────────────────────

// Map: 'SPOT|expiryDate' → 'HH:MM:SS±HHMM'
// Populated by instruments.js when it parses product.settlement_time.
const _learned = new Map();

// Map: 'SPOT' → 'HH:MM:SS±HHMM'  (most recently seen time for that spot,
// used for expiries whose exact settlement time was never recorded)
const _learnedBySpot = new Map();

/**
 * Record a settlement time observed from the API.
 * Called by instruments.js for every product it processes.
 *
 * @param {string} spot            — e.g. 'XAUT'
 * @param {string} expiryDate      — 'YYYY-MM-DD'
 * @param {string} settlementIso   — full ISO timestamp from the API,
 *                                   e.g. '2026-08-07T12:00:00Z'
 */
function recordSettlementTime(spot, expiryDate, settlementIso) {
    if (!spot || !expiryDate || !settlementIso) return;

    const d = new Date(settlementIso);
    if (isNaN(d.getTime())) return;

    // Express the settlement instant as a time-of-day in IST (+0530), so the
    // resulting string composes correctly with a YYYY-MM-DD date and matches
    // the format used everywhere else in the codebase.
    const ist = new Date(d.getTime() + (5 * 60 + 30) * 60 * 1000);
    const pad = n => String(n).padStart(2, '0');
    const timeStr = `${pad(ist.getUTCHours())}:${pad(ist.getUTCMinutes())}:` +
                    `${pad(ist.getUTCSeconds())}+0530`;

    const key      = `${spot.toUpperCase()}|${expiryDate}`;
    const previous = _learned.get(key);

    _learned.set(key, timeStr);
    _learnedBySpot.set(spot.toUpperCase(), timeStr);

    if (previous && previous !== timeStr) {
        logger.log('scheduler',
            `Settlement time changed for ${spot}/${expiryDate}: ${previous} -> ${timeStr}`);
    }
}

/**
 * Resolve the settlement time-of-day string for a (spot, expiryDate).
 * @returns {string} e.g. '17:30:00+0530'
 */
function settlementTimeFor(spot, expiryDate) {
    const S = (spot || '').toUpperCase();

    const exact = _learned.get(`${S}|${expiryDate}`);
    if (exact) return exact;

    const bySpotLearned = _learnedBySpot.get(S);
    if (bySpotLearned) return bySpotLearned;

    if (SETTLEMENT_TIME_BY_SPOT[S]) return SETTLEMENT_TIME_BY_SPOT[S];

    return DEFAULT_SETTLEMENT_TIME;
}

// ─── Public helpers (these replace every hardcoded 'T17:30:00+0530') ──────────

/**
 * Full settlement timestamp string for a (spot, expiryDate).
 * @returns {string} e.g. '2026-08-07T17:30:00+0530'
 */
function expiryTimestamp(spot, expiryDate) {
    return `${expiryDate}T${settlementTimeFor(spot, expiryDate)}`;
}

/**
 * Settlement instant as unix seconds.
 */
function expiryUnix(spot, expiryDate) {
    return Math.floor(new Date(expiryTimestamp(spot, expiryDate)).getTime() / 1000);
}

/**
 * Settlement instant as unix milliseconds.
 */
function expiryMillis(spot, expiryDate) {
    return new Date(expiryTimestamp(spot, expiryDate)).getTime();
}

/**
 * True if this (spot, expiry) has already settled.
 */
function isExpired(spot, expiryDate) {
    return expiryUnix(spot, expiryDate) < Math.floor(Date.now() / 1000);
}

/**
 * True if this (spot, expiry) is still live.
 */
function isLive(spot, expiryDate) {
    return !isExpired(spot, expiryDate);
}

/**
 * Hours remaining until settlement (negative if already settled).
 */
function hoursToExpiry(spot, expiryDate) {
    return (expiryUnix(spot, expiryDate) - Math.floor(Date.now() / 1000)) / 3600;
}

/**
 * Diagnostic: every settlement time currently known, for logging at startup.
 */
function knownSettlementTimes() {
    const out = {};
    for (const [spot, time] of _learnedBySpot) out[spot] = `${time} (from API)`;
    for (const [spot, time] of Object.entries(SETTLEMENT_TIME_BY_SPOT)) {
        if (!out[spot]) out[spot] = `${time} (config fallback)`;
    }
    return out;
}

module.exports = {
    recordSettlementTime,
    settlementTimeFor,
    expiryTimestamp,
    expiryUnix,
    expiryMillis,
    isExpired,
    isLive,
    hoursToExpiry,
    knownSettlementTimes,
    DEFAULT_SETTLEMENT_TIME,
    SETTLEMENT_TIME_BY_SPOT,
};
