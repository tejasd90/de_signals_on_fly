// signals/otm_common.js
// ─────────────────────────────────────────────────────────────────────────────
// Shared machinery for the OTM signals (otm_red_squeeze, green_stairs).
//
// Both require the option to be out of the money, score strength the same way,
// and define activation as a close above the pattern high. Keeping that in one
// place means the two signals stay comparable — if scoring drifted between them,
// their percentages could not be read against each other.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg = require('../config');

const MIN_SEQ   = cfg.OTM_MIN_SEQ_LENGTH;
const THRESH    = cfg.OTM_SIGNAL_THRESHOLD;
const SL_FACTOR = cfg.OTM_SL_FACTOR;

// ─── Candle predicates ────────────────────────────────────────────────────────

function bodyLen(c)    { return Math.abs(c.close - c.open); }
function isZeroBody(c) { return c.close === c.open; }
function isRed(c)      { return c.close < c.open; }
function isGreen(c)    { return c.close > c.open; }

function r3(n) { return Math.round(n * 1000) / 1000; }
function r4(n) { return Math.round(n * 10000) / 10000; }

// ─── Moneyness ────────────────────────────────────────────────────────────────

/**
 * Is this option out of the money against the given spot candle?
 *
 * Calls are OTM above spot, puts below. Judged on the spot CLOSE at the same
 * timestamp as the option candle.
 */
function isOTM(type, strike, spotCandle) {
    if (!spotCandle) return false;
    const s = spotCandle.close;
    return type === 'C' ? strike > s : strike < s;
}

/** How far out of the money, as a percentage of spot. Negative means ITM. */
function distancePct(type, strike, spotCandle) {
    if (!spotCandle || !spotCandle.close) return 0;
    const s   = spotCandle.close;
    const raw = ((strike - s) / s) * 100;
    return r3(type === 'C' ? raw : -raw);
}

// ─── Strength ─────────────────────────────────────────────────────────────────

/**
 * signalValue = spot / mean(triggerClose, low of every pattern candle)
 *
 * Dimensionless, so one threshold serves every spot. Higher means a cheaper
 * option relative to spot — the reliability claim being made is that the same
 * shape on a near-worthless option is worth more than on an expensive one.
 *
 * @param {Object[]} patternCandles  every candle in the sequence
 * @param {number}   triggerClose    close of the candle that completes it
 * @param {number}   spotPrice       spot close at pattern start
 */
function computeStrength(patternCandles, triggerClose, spotPrice) {
    const values = patternCandles.map(c => c.low);
    values.push(triggerClose);

    const avg = values.reduce((a, b) => a + b, 0) / values.length;
    if (!(avg > 0) || !(spotPrice > 0)) return { avgPrice: 0, signalValue: 0 };

    return { avgPrice: r4(avg), signalValue: r3(spotPrice / avg) };
}

// ─── Outcome ──────────────────────────────────────────────────────────────────

/**
 * Annotate each signal with what happened after entry.
 *
 *   signalRatio — highest high after entry divided by the entry close. Measured
 *                 over ALL subsequent candles and never truncated: options decay
 *                 to zero, so stopping at the first adverse close would make
 *                 every ratio read ~1.
 *   brokeOut    — did a later candle CLOSE above the pattern high? This is the
 *                 activation condition. For green_stairs it is true by
 *                 construction, since the breakout is what fires the signal.
 *   signalState — 'activated' when it broke out, 'slHit' when it did not,
 *                 'pending' when there is no data after entry yet. slHit is
 *                 retained for later use rather than acted on now.
 */
function annotateOutcomes(signals, candles) {
    for (const sig of signals) {
        const i = candles.findIndex(c => c.dtstring === sig.dtstring);
        if (i < 0 || i === candles.length - 1) {
            sig.signalState = 'pending';
            sig.signalRatio = 0;
            sig.brokeOut    = false;
            continue;
        }

        const after = candles.slice(i + 1);
        sig.signalRatio = r3(Math.max(...after.map(c => c.high)) / sig.close);
        sig.brokeOut    = after.some(c => c.close > sig.patternHigh);
        sig.signalState = sig.brokeOut ? 'activated'
                        : (sig.signalRatio >= SL_FACTOR ? 'activated' : 'slHit');
    }
}

module.exports = {
    MIN_SEQ, THRESH, SL_FACTOR,
    bodyLen, isZeroBody, isRed, isGreen, r3, r4,
    isOTM, distancePct, computeStrength, annotateOutcomes,
};
