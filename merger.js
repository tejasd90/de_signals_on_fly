// merger.js
// ─────────────────────────────────────────────────────────────────────────────
// Merges per-instrument signals into consolidated time-range signals.
//
// When multiple instruments fire red_squeeze at overlapping time windows,
// they are merged into a single range representing one market event.
//
// A signal's time range is [patternStart, dtstring] — from the first red
// candle of the squeeze to the green trigger candle. Overlapping ranges
// across instruments are merged using the integrateRange logic from the
// original stairs_3d_processor_1.js.
//
// Merged range format (array):
//   [
//     startTs,        string  — earliest patternStart across merged instruments
//     endTs,          string  — latest trigger dtstring across merged instruments
//     count,          number  — number of instrument signals merged here
//     maxSignalValue, number  — highest signalValue across merged instruments
//     maxSignalRatio, number  — highest signalRatio (multibagger) achieved
//     signalState,    string  — 'activated'|'slHit'|'pending'
//     instruments,    string[] — list of instrument symbols
//     universeMaxRatio,  number — best payoff across all ELIGIBLE instruments at
//                                 the signal instant, whether or not they fired.
//                                 Always >= maxSignalRatio in 'further_otm' mode,
//                                 because the firing strike is itself eligible.
//     universeMaxSymbol, string — which instrument reached it
//   ]
//
// Indices 7 and 8 are appended, so signal files written before universeMaxRatio
// existed still parse — those fields simply read as undefined.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const logger = require('./logger');

// ─── integrateRange ───────────────────────────────────────────────────────────

// Direct port of integrateRange from stairs_3d_processor_1.js.
// Merges rangeToMerge into the sorted ranges array, combining any overlaps.
//
// rangeToMerge: [startTs, endTs, count, maxSignalValue, maxSignalRatio, state,
//                instruments[], universeMaxRatio, universeMaxSymbol]
function integrateRange(ranges, rangeToMerge) {
    const [dtStart, dtEnd] = [rangeToMerge[0], rangeToMerge[1]];
    let i = 0;

    // Find first range that ends at or after our start
    while (i < ranges.length && ranges[i][1] < dtStart) i++;

    // No overlap — insert
    if (i === ranges.length || ranges[i][0] > dtEnd) {
        ranges.splice(i, 0, rangeToMerge);
        return ranges;
    }

    // Find all overlapping ranges
    let j = i;
    while (j < ranges.length && ranges[j][0] <= dtEnd) j++;

    // Merge
    const mergeStart = ranges[i][0] < dtStart ? ranges[i][0] : dtStart;
    const mergeEnd   = ranges[j-1][1] > dtEnd  ? ranges[j-1][1] : dtEnd;

    let newCount       = rangeToMerge[2];
    let newMaxSigVal   = rangeToMerge[3];
    let newMaxSigRatio = rangeToMerge[4];
    let newState       = rangeToMerge[5];
    let newInstruments = [...rangeToMerge[6]];
    let newUnivRatio   = rangeToMerge[7] || 0;
    let newUnivSymbol  = rangeToMerge[8] || null;

    for (const r of ranges.slice(i, j)) {
        newCount       += r[2];
        newMaxSigVal    = Math.max(newMaxSigVal,   r[3]);
        newMaxSigRatio  = Math.max(newMaxSigRatio, r[4]);
        // State priority: activated > pending > slHit
        if (r[5] === 'activated' || newState === 'activated') newState = 'activated';
        else if (r[5] === 'pending'   || newState === 'pending')   newState = 'pending';
        newInstruments = newInstruments.concat(r[6]);

        // Keep the symbol alongside its own ratio, not the max of one and the
        // symbol of the other.
        if ((r[7] || 0) > newUnivRatio) {
            newUnivRatio  = r[7];
            newUnivSymbol = r[8] || null;
        }
    }

    ranges.splice(i, j - i, [mergeStart, mergeEnd, newCount, newMaxSigVal, newMaxSigRatio,
                             newState, newInstruments, newUnivRatio, newUnivSymbol]);
    return ranges;
}

// ─── Merge signals for one (spot, expiry, duration) ──────────────────────────

/**
 * Given a map of instrument → signal[], produce a merged range array.
 *
 * @param {Map<string, Object[]>} instrumentSignals
 *        Map of instrument symbol → array of signal objects from red_squeeze.computeSignals
 * @param {'C'|'P'} type   — call or put
 * @returns {Array[]}       — sorted array of merged ranges
 */
function mergeSignals(instrumentSignals, type) {
    let ranges = [];

    for (const [instrument, signals] of instrumentSignals) {
        // Only process matching option type
        const instrType = instrument.startsWith('C') ? 'C' : 'P';
        if (instrType !== type) continue;

        for (const sig of signals) {
            const range = [
                sig.patternStart,   // start of red sequence
                sig.dtstring,       // green trigger candle (end of pattern)
                1,
                sig.signalValue,
                sig.signalRatio,
                sig.signalState,
                [instrument],
                sig.universeRatio  || 0,
                sig.universeSymbol || null,
            ];
            ranges = integrateRange(ranges, range);
        }
    }

    logger.log('red_squeeze',
        `mergeSignals type=${type}: ${ranges.length} merged ranges from ${instrumentSignals.size} instruments`);

    return ranges;
}

module.exports = { integrateRange, mergeSignals };
