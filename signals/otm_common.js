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
 * Annotate each signal with what happened after the SIGNAL CANDLE.
 *
 * ACTIVATION = price trading above the HIGH of the signal candle.
 *
 * An intrabar touch is enough; the candle need not close above it. That models a
 * resting stop-buy order at the signal candle's high, which fills the moment the
 * level is traded through regardless of where the candle ends.
 *
 *   triggerPrice = signal candle's high
 *   signalRatio  = highest high AFTER the signal candle / triggerPrice
 *   activated    = that highest high exceeded triggerPrice
 *
 * The denominator is the signal candle's HIGH, not its close. That is stricter —
 * the high is above the close, so every ratio is lower than under the previous
 * definition — but it is what you would actually pay on a stop entry, so the
 * number means something you could have achieved rather than a best case.
 *
 * Never truncated at any adverse level. Options decay below any pattern-derived
 * line, so stopping the measurement early would drive every ratio to ~1.
 */
function annotateOutcomes(signals, candles) {
    for (const sig of signals) {
        const i = candles.findIndex(c => c.dtstring === sig.dtstring);

        if (i < 0 || i === candles.length - 1) {
            sig.signalState  = 'pending';
            sig.signalRatio  = 0;
            sig.brokeOut     = false;
            sig.triggerPrice = sig.triggerPrice ?? (i >= 0 ? candles[i].high : 0);
            sig.peakAfter    = 0;
            continue;
        }

        // The trigger is the signal candle's own high. Each signal sets this
        // when it emits; falling back here keeps older callers working.
        const triggerPrice = sig.triggerPrice ?? candles[i].high;

        const after   = candles.slice(i + 1);
        const peak    = Math.max(...after.map(c => c.high));

        sig.triggerPrice = r4(triggerPrice);
        sig.peakAfter    = r4(peak);
        sig.signalRatio  = triggerPrice > 0 ? r3(peak / triggerPrice) : 0;

        // Strictly above: trading exactly AT the high does not prove a fill.
        sig.brokeOut     = peak > triggerPrice;
        sig.signalState  = sig.brokeOut ? 'activated' : 'slHit';
    }
}

module.exports = {
    MIN_SEQ, THRESH, SL_FACTOR,
    bodyLen, isZeroBody, isRed, isGreen, r3, r4,
    isOTM, distancePct, computeStrength, annotateOutcomes,
};
