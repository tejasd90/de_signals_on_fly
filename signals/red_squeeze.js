// signals/red_squeeze.js
// ─────────────────────────────────────────────────────────────────────────────
// Stateless, atomic Red Squeeze signal computation.
//
// Given a candle array, returns an array of signal objects for candles
// where the pattern was detected. No state is maintained between calls —
// pass the full candle array each time.
//
// Pattern: N consecutive RED candles with strictly decreasing body lengths
// (the squeeze), immediately followed by a strict GREEN trigger candle.
// Entry at the close of the trigger candle.
//
// Zero-body (doji) candles never participate: they break a sequence in progress
// and cannot act as the trigger. See ZERO-BODY POLICY below for why.
//
// Outcome annotation (for past expiries with full candle history):
//   signalRatio = max(high of all candles after trigger) / trigger close
//   signalState = 'activated' if signalRatio >= SL_FACTOR, else 'slHit'
//
// Each signal object:
//   {
//     dtstring:      string,   — trigger candle timestamp (entry point)
//     close:         number,   — trigger close (entry price)
//     seqLength:     number,   — red candles in the squeeze sequence
//     firstRedBody:  number,
//     lastRedBody:   number,
//     greenBody:     number,   — trigger candle body (min MINIMUM_TICK)
//     patternLow:    number,   — min low across all pattern candles
//     patternStart:  string,   — dtstring of the first red candle in sequence
//     ratio1:        number,   — firstRedBody / lastRedBody
//     ratio2:        number,   — firstRedBody / greenBody
//     signalValue:   number,   — ratio1 + ratio2
//     signalState:   string,   — 'activated' | 'slHit' | 'pending'
//     signalRatio:   number,   — peak multiple from entry (0 if pending)
//   }
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg    = require('../config');
const logger = require('../logger');

const MIN_SEQ  = cfg.RED_SQUEEZE_MIN_SEQ_LENGTH;
const THRESH   = cfg.RED_SQUEEZE_THRESHOLD;
const SL_FACT  = cfg.RED_SQUEEZE_SL_FACTOR;
// NOTE: cfg.RED_SQUEEZE_MINIMUM_TICK is intentionally no longer used.
// Zero-body candles are excluded outright rather than floored to a tick value.
// See the ZERO-BODY POLICY note below.

// ─── Candle helpers ───────────────────────────────────────────────────────────
//
// ZERO-BODY (DOJI) POLICY
// A candle with close === open carries no directional information and must never
// participate in the pattern. It is excluded in both roles:
//
//   As the trigger — the trigger must be a STRICT green (close > open). A flat
//   candle does not signal that premium has stopped falling; only an actual
//   up-close does.
//
//   Inside the red sequence — a zero-body candle BREAKS the sequence. Previously
//   a doji was admitted with its body substituted by MIN_TICK (0.1), which made
//   ratio1 = firstRedBody / 0.1 = firstRedBody * 10. Any doji landing at the end
//   of a sequence with firstRedBody >= 5 therefore cleared the threshold of 50 on
//   ratio1 alone, no matter how weak the real squeeze or the green candle was.
//   Deep-OTM options near expiry are full of flat candles, so this manufactured
//   false positives exactly where they are hardest to spot.
//
// bodyLen() consequently returns the true body with no floor. Callers are
// responsible for never passing a zero-body candle into a ratio denominator;
// the sequence rules below guarantee that.

function bodyLen(c) {
    return Math.abs(c.close - c.open);
}

function isZeroBody(c) { return c.close === c.open; }
function isRed(c)      { return c.close < c.open;  }   // strict red, excludes doji
function isGreen(c)    { return c.close > c.open;  }   // strict green, excludes doji

function r3(n) { return Math.round(n * 1000) / 1000; }

// ─── Signal function ──────────────────────────────────────────────────────────

function signalFn(ratio1, ratio2) {
    return ratio1 + ratio2;
}

// ─── Main compute ─────────────────────────────────────────────────────────────

/**
 * Run red squeeze detection on a full candle array.
 * Stateless — always processes from index 1 (so prevCandle always exists).
 *
 * @param {Object[]} candles   — full candle array, sorted ascending by time
 * @param {string}   instrument — for logging only
 * @returns {Object[]}         — array of signal objects (may be empty)
 */
function computeSignals(candles, instrument = '', opts = {}) {
    // Overridable so the pattern extractor can keep every structural match while
    // normal generation still applies its tuning threshold.
    const minValue = opts.minSignalValue !== undefined ? opts.minSignalValue : THRESH;
    if (!candles || candles.length < MIN_SEQ + 2) return [];

    const signals = [];
    const redSeq  = [];   // current descending red sequence (candle objects)

    for (let i = 1; i < candles.length; i++) {
        const candle = candles[i];

        // Zero-body candle: carries no direction. Breaks any sequence in
        // progress and cannot act as a trigger.
        if (isZeroBody(candle)) {
            redSeq.length = 0;
            continue;
        }

        const body = bodyLen(candle);   // guaranteed > 0 past the check above

        if (isRed(candle)) {
            if (redSeq.length === 0 || body < bodyLen(redSeq[redSeq.length - 1])) {
                redSeq.push(candle);
            } else {
                // Non-decreasing body — reset sequence, this candle starts a new one
                redSeq.length = 0;
                redSeq.push(candle);
            }

        } else if (isGreen(candle) && redSeq.length >= MIN_SEQ) {
            // Strict green trigger after a sufficient squeeze.
            // All bodies below are guaranteed non-zero, so no division by zero.
            const firstRedBody = bodyLen(redSeq[0]);
            const lastRedBody  = bodyLen(redSeq[redSeq.length - 1]);
            const greenBody    = body;

            const ratio1      = firstRedBody / lastRedBody;
            const ratio2      = firstRedBody / greenBody;
            const signalValue = signalFn(ratio1, ratio2);

            if (signalValue >= minValue) {
                const patternCandles = redSeq.concat([candle]);
                const patternLow     = Math.min(...patternCandles.map(c => c.low));

                signals.push({
                    dtstring:     candle.dtstring,
                    close:        candle.close,
                    seqLength:    redSeq.length,
                    firstRedBody: r3(firstRedBody),
                    lastRedBody:  r3(lastRedBody),
                    greenBody:    r3(greenBody),
                    patternLow:   r3(patternLow),
                    patternStart: redSeq[0].dtstring,   // start of the range for integrateRange
                    ratio1:       r3(ratio1),
                    ratio2:       r3(ratio2),
                    signalValue:  r3(signalValue),
                    signalState:  'pending',             // annotated below
                    signalRatio:  0,
                });

                logger.debug('red_squeeze',
                    `Signal fired: ${instrument} at ${candle.dtstring} ` +
                    `sv=${r3(signalValue)} ratio1=${r3(ratio1)} ratio2=${r3(ratio2)}`);
            }

            redSeq.length = 0;  // green always resets

        } else {
            // Green but sequence too short, or something else — reset
            redSeq.length = 0;
        }
    }

    // Annotate outcomes using full candle history
    annotateOutcomes(signals, candles);

    logger.log('red_squeeze',
        `${instrument}: ${signals.length} signals from ${candles.length} candles`);

    return signals;
}

// ─── Outcome annotation ───────────────────────────────────────────────────────

function annotateOutcomes(signals, allCandles) {
    for (const sig of signals) {
        const triggerIdx = allCandles.findIndex(c => c.dtstring === sig.dtstring);
        if (triggerIdx < 0 || triggerIdx === allCandles.length - 1) {
            sig.signalState = 'pending';
            sig.signalRatio = 0;
            continue;
        }

        const after    = allCandles.slice(triggerIdx + 1);
        const peakHigh = Math.max(...after.map(c => c.high));
        sig.signalRatio = r3(peakHigh / sig.close);
        sig.signalState = sig.signalRatio >= SL_FACT ? 'activated' : 'slHit';
    }
}

// ─── Quality summary ─────────────────────────────────────────────────────────

/**
 * Compute quality metrics for a flat array of signal objects.
 * @param {Object[]} signals
 * @returns {{ total, slHit, multibaggers, pct }}
 */
function quality(signals) {
    const total    = signals.length;
    const empty    = () => Object.fromEntries(cfg.MULTIBAGGER_THRESHOLDS.map(t => [`${t}x`, 0]));
    if (total === 0) return { total: 0, slHit: 0, multibaggers: empty(), pct: empty() };

    const slHit        = signals.filter(s => s.signalState === 'slHit').length;
    const multibaggers = {};
    const pct          = {};

    for (const t of cfg.MULTIBAGGER_THRESHOLDS) {
        const count         = signals.filter(s => (s.signalRatio || 0) >= t).length;
        multibaggers[`${t}x`] = count;
        pct[`${t}x`]          = `${((count / total) * 100).toFixed(1)}%`;
    }

    return { total, slHit, multibaggers, pct };
}

module.exports = { computeSignals, quality };
