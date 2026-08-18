// signals/red_squeeze_adapter.js
// ─────────────────────────────────────────────────────────────────────────────
// Wraps the original red_squeeze in the registry interface.
//
// red_squeeze predates the registry: its computeSignals takes (candles, symbol)
// and needs no spot or instrument metadata. Rather than edit a signal whose
// results are already backfilled — which would risk changing them — this adapts
// the call shape and leaves the logic untouched.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const redSqueeze = require('./red_squeeze');

module.exports = {
    id: 'red_squeeze',
    requiresSpot: false,
    otmOnly:      false,
    computeSignals(candles, instrument, ctx, opts) {
        return redSqueeze.computeSignals(candles, instrument.symbol, opts);
    },
};
