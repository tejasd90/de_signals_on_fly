// signals/otm_wall.js
// ─────────────────────────────────────────────────────────────────────────────
// A wall candle after a narrow range, on OUT OF THE MONEY options.
//
// Ported from the spike-after-flats signal in the original group.js (indices 11
// and 12), with the moving-average, volume and expiry/spot normalisation terms
// removed.
//
// WHAT IT LOOKS FOR
// Five candles that barely deviate from one another, then one that departs
// sharply. Note this is about NARROWNESS OF RANGE, not cheapness: near expiry
// the flat run is usually tiny premiums, but a move well before expiry shows the
// same shape at ordinary prices — five near-identical candles, then a wall.
//
// HOW NARROWNESS IS MEASURED
// `dist` sums how far the current candle's body sits from each of the previous
// five bodies. It is therefore large in exactly two situations that matter:
// the previous five were tightly clustered, or the current one departed hard.
// Both together is the signal.
//
// Because narrowness is captured implicitly by dist, the predecessors are never
// separately tested for being "small" — deliberately, matching the original. A
// fixed size threshold would only work at one price level, whereas dist scales
// with whatever range the instrument happens to be trading in.
//
// SCORING
// signalValue is the log10 JUMP between this candle's value and a recent one:
//
//     value(i) = log10(open × close × dist²)
//     jump     = value(i) − value(prev)
//
// A jump of 2 means the value grew a hundredfold. That is the original's
// `durCandle[11] - prevDurCandle[11] >= 2` condition, kept as the threshold.
//
// The original's −4·log10(DTE+1) and −4·log10(1+spot/10000) terms are dropped:
// both are near-identical for adjacent candles and therefore cancel in the
// difference, while making the raw value incomparable across expiries.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg    = require('../config');
const c      = require('./otm_common');
const logger = require('../logger');

const LOOKBACK   = cfg.WALL_LOOKBACK_CANDLES;     // 5, from the original
const JUMP_THRESH = cfg.WALL_JUMP_THRESHOLD;      // 2 => a hundredfold jump
const CLOSE_MULT  = cfg.WALL_CLOSE_MULTIPLE;      // 1.35, from the original

function ocMax(x) { return Math.max(x.open, x.close); }
function ocMin(x) { return Math.min(x.open, x.close); }

/** A candle that never traded: flat at one price. */
function isDead(x) {
    return x.open === x.high && x.high === x.low && x.low === x.close;
}

/**
 * How far this candle's body sits from each of the previous five.
 * Large when the predecessors were tightly clustered and this one departed.
 */
function bodyDistance(candles, i) {
    const curMax = ocMax(candles[i]);
    const curMin = ocMin(candles[i]);

    let dist = 0;
    for (let k = 1; k <= LOOKBACK; k++) {
        const p = candles[i - k];
        dist += Math.abs(curMax - ocMax(p)) + Math.abs(curMin - ocMin(p));
    }
    return dist;
}

/**
 * Per-candle value, or null when the candle cannot carry one.
 *
 * Null when dist is zero (nothing moved) or when all five predecessors were
 * dead. A first real print after a run of untraded candles produces a huge dist
 * but means only that the instrument started trading, not that a wall formed.
 */
function candleValue(candles, i) {
    const dist = bodyDistance(candles, i);
    if (dist <= 0) return null;

    let allDead = true;
    for (let k = 1; k <= LOOKBACK; k++) {
        if (!isDead(candles[i - k])) { allDead = false; break; }
    }
    if (allDead) return null;

    const cur = candles[i];
    const mag = cur.open * cur.close * dist * dist;
    if (!(mag > 0)) return null;

    return { value: Math.log10(mag), dist };
}

/**
 * @param {Object[]} candles     option candles, ascending
 * @param {Object}   instrument  { symbol, type, strike }
 * @param {Object}   ctx         { spotByTs }
 */
function computeSignals(candles, instrument, ctx, opts = {}) {
    // Overridable: see red_squeeze.js.
    const minValue = opts.minSignalValue !== undefined ? opts.minSignalValue
                   : (typeof c !== 'undefined' ? c.THRESH : JUMP_THRESH);
    if (!candles || candles.length < LOOKBACK + 2) return [];
    const spotByTs = (ctx && ctx.spotByTs) || new Map();

    // Values are needed for the current candle and its two predecessors, so
    // compute the series once rather than three times per candle.
    const values = new Array(candles.length).fill(null);
    for (let i = LOOKBACK; i < candles.length; i++) {
        values[i] = candleValue(candles, i);
    }

    const signals = [];

    for (let i = LOOKBACK; i < candles.length; i++) {
        const cur = values[i];
        if (!cur) continue;

        const candle = candles[i];

        // Price gates from the original, minus everything volume-based.
        // A wall downward is not what this hunts, so it must be green.
        if (candle.close <= candle.open) continue;

        // Compare against BOTH the previous candle and the one before it,
        // taking whichever gives the larger jump. The flat run does not always
        // end exactly one candle before the wall — a small transitional candle
        // in between is common, and comparing only to prev1 would miss those.
        let best = null;
        for (const k of [1, 2]) {
            const prev = values[i - k];
            if (!prev) continue;

            const jump = cur.value - prev.value;
            if (jump < minValue) continue;

            // The wall must also be a real price move, not just a big dist.
            if (candle.close < CLOSE_MULT * candles[i - k].close) continue;

            if (!best || jump > best.jump) {
                best = { jump, prevValue: prev.value, comparedTo: `prev${k}` };
            }
        }
        if (!best) continue;

        // OTM at pattern start — the first candle of the narrow run.
        const startCandle = candles[i - LOOKBACK];
        const spotAtStart = spotByTs.get(startCandle.dtstring);
        if (!c.isOTM(instrument.type, instrument.strike, spotAtStart)) continue;

        const window = candles.slice(i - LOOKBACK, i + 1);

        signals.push({
            dtstring:     candle.dtstring,          // the wall candle is the entry
            close:        candle.close,
            patternStart: startCandle.dtstring,
            patternHigh:  Math.max(...window.map(x => x.high)),
            patternLow:   c.r4(Math.min(...window.map(x => x.low))),
            seqLength:    LOOKBACK,
            dist:         c.r4(cur.dist),
            value:        c.r3(cur.value),
            prevValue:    c.r3(best.prevValue),
            comparedTo:   best.comparedTo,
            spotAtStart:  c.r3(spotAtStart.close),
            distancePct:  c.distancePct(instrument.type, instrument.strike, spotAtStart),
            signalValue:  c.r3(best.jump),          // orders of magnitude
            signalState:  'pending',
            signalRatio:  0,
            brokeOut:     false,
        });
    }

    c.annotateOutcomes(signals, candles);

    if (signals.length) {
        logger.debug('otm_wall',
            `${instrument.symbol}: ${signals.length} signals from ${candles.length} candles`);
    }
    return signals;
}

module.exports = {
    id: 'otm_wall',
    requiresSpot: true,
    otmOnly:      true,
    computeSignals,
};
