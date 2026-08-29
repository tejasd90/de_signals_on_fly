// signals/otm_red_squeeze.js
// ─────────────────────────────────────────────────────────────────────────────
// Red squeeze, restricted to OUT OF THE MONEY options, scored on cheapness.
//
// Same shape as red_squeeze: MIN_SEQ or more consecutive red candles with
// strictly decreasing bodies, then a strict green trigger. Two differences:
//
//   1. The option must be OTM at PATTERN START. ITM premium carries intrinsic
//      value that melts hard, so a clean pattern there says little — which is
//      exactly the weakness of the unrestricted red_squeeze.
//
//   2. Scoring drops ratio1 + ratio2 entirely. Squeeze geometry turned out not
//      to separate winners from ordinary decay: across the observed data the
//      worst false positive scored 5757 and the weakest true positive 51. This
//      scores CHEAPNESS instead — spot divided by the average of the trigger
//      close and every pattern low — on the claim that the same shape on a
//      near-worthless option is worth more than on an expensive one.
//
// Entry is the green trigger's close, as in the original red_squeeze.
// Activation is a later candle CLOSING above the pattern high, which for this
// shape is usually the first (largest) red candle's high.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg = require('../config');
const c   = require('./otm_common');
const logger = require('../logger');

/**
 * @param {Object[]} candles     option candles, ascending
 * @param {Object}   instrument  { symbol, type, strike }
 * @param {Object}   ctx         { spotByTs: Map<dtstring, spotCandle> }
 */
function computeSignals(candles, instrument, ctx, opts = {}) {
    // Overridable: see red_squeeze.js.
    const minValue = opts.minSignalValue !== undefined ? opts.minSignalValue
                   : (typeof c !== 'undefined' ? c.THRESH : JUMP_THRESH);
    if (!candles || candles.length < c.MIN_SEQ + 2) return [];
    const spotByTs = (ctx && ctx.spotByTs) || new Map();

    const signals = [];
    const redSeq  = [];

    for (let i = 1; i < candles.length; i++) {
        const candle = candles[i];

        // A zero-body candle carries no direction: it cannot extend the
        // sequence and cannot trigger.
        if (c.isZeroBody(candle)) { redSeq.length = 0; continue; }

        const body = c.bodyLen(candle);

        if (c.isRed(candle)) {
            if (redSeq.length === 0 || body < c.bodyLen(redSeq[redSeq.length - 1])) {
                redSeq.push(candle);
            } else {
                redSeq.length = 0;
                redSeq.push(candle);       // non-decreasing body starts a new run
            }
            continue;
        }

        if (!c.isGreen(candle) || redSeq.length < c.MIN_SEQ) { redSeq.length = 0; continue; }

        // ── Green trigger after a long enough squeeze ──
        const patternStartCandle = redSeq[0];
        const spotAtStart        = spotByTs.get(patternStartCandle.dtstring);

        // Moneyness at pattern start — the looser test, so an instrument that
        // drifts across the money mid-pattern is kept.
        if (!c.isOTM(instrument.type, instrument.strike, spotAtStart)) {
            redSeq.length = 0;
            continue;
        }

        const patternCandles = redSeq.concat([candle]);

        // Squeeze geometry is RECORDED but not used to fire. It was removed from
        // scoring deliberately — it failed to rank in the unrestricted
        // red_squeeze — but whether it ranks WITHIN the OTM population is a
        // different and untested question, and it cannot be asked if the numbers
        // are never stored.
        const firstRedBody = c.bodyLen(redSeq[0]);
        const lastRedBody  = c.bodyLen(redSeq[redSeq.length - 1]);
        const greenBody    = c.bodyLen(candle);
        const ratio1 = lastRedBody > 0 ? firstRedBody / lastRedBody : 0;
        const ratio2 = greenBody   > 0 ? firstRedBody / greenBody   : 0;
        const { avgPrice, signalValue } =
            c.computeStrength(patternCandles, candle.close, spotAtStart.close);

        if (signalValue >= minValue) {
            signals.push({
                dtstring:     candle.dtstring,                       // entry
                close:        candle.close,                          // entry price
                patternStart: patternStartCandle.dtstring,
                patternHigh:  Math.max(...patternCandles.map(x => x.high)),
                patternLow:   c.r4(Math.min(...patternCandles.map(x => x.low))),
                seqLength:    redSeq.length,

                // Descriptive only — see above.
                firstRedBody: c.r3(firstRedBody),
                lastRedBody:  c.r3(lastRedBody),
                greenBody:    c.r3(greenBody),
                ratio1:       c.r3(ratio1),
                ratio2:       c.r3(ratio2),

                avgPrice,
                spotAtStart:  c.r3(spotAtStart.close),
                distancePct:  c.distancePct(instrument.type, instrument.strike, spotAtStart),
                signalValue,
                triggerPrice: c.r4(candle.high),   // ACTIVATION LEVEL
                signalState:  'pending',
                signalRatio:  0,
                brokeOut:     false,
            });
        }

        redSeq.length = 0;   // a green always ends the run, signal or not
    }

    c.annotateOutcomes(signals, candles);

    if (signals.length) {
        logger.debug('otm_red_squeeze',
            `${instrument.symbol}: ${signals.length} signals from ${candles.length} candles`);
    }
    return signals;
}

module.exports = {
    id: 'otm_red_squeeze',
    requiresSpot: true,
    otmOnly:      true,      // restricts universeMaxRatio to OTM strikes too
    computeSignals,
};
