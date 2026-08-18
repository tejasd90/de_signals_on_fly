// signals/green_stairs.js
// ─────────────────────────────────────────────────────────────────────────────
// Ascending green staircase on OUT OF THE MONEY options.
//
// MIN_SEQ or more consecutive green candles with non-decreasing bodies, followed
// by a candle that CLOSES above the high of the whole run.
//
// The mirror image of otm_red_squeeze. Where the squeeze reads exhaustion — the
// sellers running out — the staircase reads accumulation: each step larger than
// the last, buyers stepping up rather than one spike.
//
// EQUAL STEPS
// A body may merely equal its predecessor at most GREEN_STAIRS_MAX_EQUAL_STEPS
// times (default 1). Real chains often contain one flat step and rejecting them
// outright loses good patterns, but allowing many lets a run of identical
// candles — which is not a staircase at all — pass as one.
//
// ENTRY IS THE BREAKOUT, NOT THE LAST STEP
// The staircase is the setup; the breakout is the confirmation. Entry is the
// close of the candle that breaks above the run's high, matching the original
// stairs implementation which measured its ratio from the activating close.
// This differs from otm_red_squeeze, where entry is the trigger itself — so
// ratios between the two signals are not directly comparable.
//
// Because a signal only exists once the breakout has happened, signalState is
// 'activated' by construction. slHit is retained for later use.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg = require('../config');
const c   = require('./otm_common');
const logger = require('../logger');

const MAX_EQUAL = cfg.GREEN_STAIRS_MAX_EQUAL_STEPS;

function computeSignals(candles, instrument, ctx, opts = {}) {
    // Overridable: see red_squeeze.js.
    const minValue = opts.minSignalValue !== undefined ? opts.minSignalValue
                   : (typeof c !== 'undefined' ? c.THRESH : JUMP_THRESH);
    if (!candles || candles.length < c.MIN_SEQ + 2) return [];
    const spotByTs = (ctx && ctx.spotByTs) || new Map();

    const signals = [];
    let seq       = [];
    let equalUsed = 0;

    const resetSeq = () => { seq = []; equalUsed = 0; };

    // Fire the signal if `breakCandle` ends a long enough run by closing above it.
    const tryFire = (breakCandle) => {
        if (seq.length < c.MIN_SEQ) return;

        const patternHigh = Math.max(...seq.map(x => x.high));

        // Activation needs a CLOSE above the run's high. Trading through it
        // intrabar is not enough: a long upper wick closing back inside is
        // rejection, not a breakout.
        if (breakCandle.close <= patternHigh) return;

        const startCandle = seq[0];
        const spotAtStart = spotByTs.get(startCandle.dtstring);
        if (!c.isOTM(instrument.type, instrument.strike, spotAtStart)) return;

        const { avgPrice, signalValue } =
            c.computeStrength(seq, breakCandle.close, spotAtStart.close);
        if (signalValue < minValue) return;

        signals.push({
            dtstring:     breakCandle.dtstring,     // breakout candle = entry
            close:        breakCandle.close,
            patternStart: startCandle.dtstring,
            patternHigh,
            patternLow:   c.r4(Math.min(...seq.map(x => x.low))),
            seqLength:    seq.length,
            equalSteps:   equalUsed,
            avgPrice,
            spotAtStart:  c.r3(spotAtStart.close),
            distancePct:  c.distancePct(instrument.type, instrument.strike, spotAtStart),
            signalValue,
            signalState:  'pending',
            signalRatio:  0,
            brokeOut:     true,
        });
    };

    for (let i = 1; i < candles.length; i++) {
        const candle = candles[i];

        // A zero-body candle ends the run. It can still be the breakout: what
        // matters is where it CLOSED, not that it had no body.
        if (c.isZeroBody(candle)) { tryFire(candle); resetSeq(); continue; }

        const body = c.bodyLen(candle);

        // Does this candle CONTINUE the ascent?
        let continues = false;
        if (c.isGreen(candle)) {
            if (seq.length === 0) {
                continues = true;
            } else {
                const prevBody = c.bodyLen(seq[seq.length - 1]);
                if (body > prevBody) {
                    continues = true;
                } else if (body === prevBody && equalUsed < MAX_EQUAL) {
                    equalUsed++;
                    continues = true;
                }
            }
        }

        if (continues) { seq.push(candle); continue; }

        // The ascent ends here, so this candle is the breakout candidate.
        //
        // Note it is usually GREEN: an ascending run is broken by a green candle
        // with a smaller body far more often than by a red one. An earlier
        // version only tested non-green candles and therefore almost never fired.
        tryFire(candle);
        resetSeq();

        // A green candle that ended one run begins the next.
        if (c.isGreen(candle)) seq.push(candle);
    }

    c.annotateOutcomes(signals, candles);

    // annotateOutcomes derives brokeOut by looking forward from entry, but here
    // the breakout IS entry, so restore it.
    for (const s of signals) {
        s.brokeOut = true;
        if (s.signalState === 'slHit' && s.signalRatio >= c.SL_FACTOR) s.signalState = 'activated';
    }

    if (signals.length) {
        logger.debug('green_stairs',
            `${instrument.symbol}: ${signals.length} signals from ${candles.length} candles`);
    }
    return signals;
}

module.exports = {
    id: 'green_stairs',
    requiresSpot: true,
    otmOnly:      true,
    computeSignals,
};
