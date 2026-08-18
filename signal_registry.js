// signal_registry.js
// ─────────────────────────────────────────────────────────────────────────────
// THE ONLY FILE TO EDIT WHEN ADDING A SIGNAL.
//
// processor.js runs every signal listed here against the same candles, so a new
// signal costs one require and one array entry — no changes to fetching,
// grouping, merging, storage or the viewer.
//
// A signal module must export:
//
//   id            string   filesystem-safe; becomes data/signals/{id}/...
//   requiresSpot  boolean  true if computeSignals needs ctx.spotByTs. Signals
//                          that need spot are skipped, with a warning, when no
//                          spot candles are stored — rather than silently
//                          producing nothing.
//   otmOnly       boolean  restricts universeMaxRatio to OTM strikes. An
//                          OTM-only signal reporting an ITM strike's payoff
//                          would undercut the whole point of the restriction.
//   computeSignals(candles, instrument, ctx) -> signal[]
//                          instrument = { symbol, type, strike }
//                          ctx        = { spotByTs, duration, expiryDate, spot }
//
// Each returned signal needs at least: dtstring (entry), close (entry price),
// patternStart, signalValue, signalState, signalRatio.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const SIGNALS = [
    require('./signals/red_squeeze_adapter'),   // original, no spot needed
    require('./signals/otm_red_squeeze'),
    require('./signals/green_stairs'),
    require('./signals/otm_wall'),
];

/** All registered signals, or only those named in --signal / SIGNAL_IDS. */
function activeSignals(filterIds = null) {
    if (!filterIds || filterIds.length === 0) return SIGNALS;
    const want = new Set(filterIds);
    return SIGNALS.filter(s => want.has(s.id));
}

function byId(id) {
    return SIGNALS.find(s => s.id === id) || null;
}

module.exports = { SIGNALS, activeSignals, byId };
