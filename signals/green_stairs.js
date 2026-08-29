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
// THE SIGNAL CANDLE IS THE LAST STEP
// The staircase completing IS the signal. A separate breakout candle is no
// longer required to fire — activation is now defined uniformly across every
// signal as price trading above the SIGNAL CANDLE's high, which for a staircase
// is the last step.
//
// This replaced an earlier design where the signal only existed once a later
// candle CLOSED above the run high. That made green_stairs fire strictly later,
// less often, and at a worse price than the other signals, and made its ratios
// incomparable with theirs. Now all three share one activation rule.
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

    // Fire when a run of at least MIN_SEQ ends. The candle that ENDS the run is
    // not part of it — the signal candle is the last STEP, and its high is the
    // activation level.
    const tryFire = () => {
        if (seq.length < c.MIN_SEQ) return;

        const lastStep    = seq[seq.length - 1];
        const startCandle = seq[0];
        const patternHigh = Math.max(...seq.map(x => x.high));

        const spotAtStart = spotByTs.get(startCandle.dtstring);
        if (!c.isOTM(instrument.type, instrument.strike, spotAtStart)) return;

        const { avgPrice, signalValue } =
            c.computeStrength(seq, lastStep.close, spotAtStart.close);
        if (signalValue < minValue) return;

        // Descriptive only — the staircase's steepness. Not used to fire.
        const firstBody = c.bodyLen(seq[0]);
        const lastBody  = c.bodyLen(lastStep);
        const stepRatio = firstBody > 0 ? lastBody / firstBody : 0;

        signals.push({
            dtstring:     lastStep.dtstring,        // SIGNAL CANDLE = last step
            close:        lastStep.close,
            triggerPrice: c.r4(lastStep.high),      // ACTIVATION LEVEL
            patternStart: startCandle.dtstring,
            patternHigh,
            patternLow:   c.r4(Math.min(...seq.map(x => x.low))),
            seqLength:    seq.length,
            equalSteps:   equalUsed,

            firstRedBody: c.r3(firstBody),
            lastRedBody:  c.r3(lastBody),
            greenBody:    c.r3(lastBody),
            ratio1:       c.r3(stepRatio),
            ratio2:       0,

            avgPrice,
            spotAtStart:  c.r3(spotAtStart.close),
            distancePct:  c.distancePct(instrument.type, instrument.strike, spotAtStart),
            signalValue,
            signalState:  'pending',
            signalRatio:  0,
            brokeOut:     false,
        });
    };

    for (let i = 1; i < candles.length; i++) {
        const candle = candles[i];

        if (c.isZeroBody(candle)) { tryFire(); resetSeq(); continue; }

        const body = c.bodyLen(candle);

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

        // The ascent ends here. Fire on the run that just completed, then start
        // a new one if this candle is itself green.
        tryFire();
        resetSeq();
        if (c.isGreen(candle)) seq.push(candle);
    }

    // A run still ascending at the end of the data can still fire; its outcome
    // will simply be 'pending'.
    tryFire();

    c.annotateOutcomes(signals, candles);

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
