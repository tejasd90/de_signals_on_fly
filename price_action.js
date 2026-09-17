// price_action.js
// ─────────────────────────────────────────────────────────────────────────────
// Reads the sidecar written by build_price_action.py.
//
//   data/price_action/{spot}/{expiry}.json   event_id -> { l:[codes], r:ratio }
//   data/price_action/_stats.json            code -> { n, hit25, mx, text, tier }
//
// Shared by both grid viewers so the vocabulary and the colour basis cannot
// drift between them — the same reason surface.js and chart_url.js are shared.
//
// The event_id is built the same way build_events.py built it:
//     {signal}|{spot}|{expiry}|{duration}|{entryIso}|{type}
// so node can look a cell up without knowing anything about how the features
// were computed.
//
// WHY THE COLOUR IS A HIT RATE
// The original ask was to shade by max ratio. That cannot work here: the max
// operator does the work, not the signal (DECISION_DOCUMENT), and the largest
// ratios sit on 0.55-premium contracts that are one tick of noise. Every label
// eventually co-occurs with one, so max-shading glows uniformly. `hit25` is
// P(25x) among TRADEABLE events — filled, entry premium 2-20 — and `mx` is
// carried alongside as text so the number is still visible.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs   = require('fs');
const path = require('path');

const BASE = path.join('data', 'price_action');
const _cache = new Map();          // `${spot}|${expiry}` -> object
let _stats = null;

function stats() {
    if (_stats) return _stats;
    const p = path.join(BASE, '_stats.json');
    try { _stats = JSON.parse(fs.readFileSync(p, 'utf8')); }
    catch (_) { _stats = {}; }
    return _stats;
}

/** Whether the sidecar exists at all, so the UI can hide the panel rather than
 *  showing an empty one. */
function available() { return fs.existsSync(path.join(BASE, '_stats.json')); }

function forExpiry(spot, expiry) {
    const key = `${spot}|${expiry}`;
    if (_cache.has(key)) return _cache.get(key);
    let obj = {};
    try { obj = JSON.parse(fs.readFileSync(path.join(BASE, spot, `${expiry}.json`), 'utf8')); }
    catch (_) { obj = {}; }
    // A full history is ~2,000 expiry files across three spots; holding every
    // one would be most of the sidecar in RAM. Oldest-out at 60 keeps the
    // working set (one screen of expiries) resident.
    if (_cache.size > 60) _cache.delete(_cache.keys().next().value);
    _cache.set(key, obj);
    return obj;
}

function eventId(signal, spot, expiry, duration, entryIso, type) {
    return `${signal}|${spot}|${expiry}|${duration}|${entryIso}|${type}`;
}

/** Labels for one cell, already joined to their vocabulary entry. */
function lookup(signal, spot, expiry, duration, entryIso, type) {
    const rec = forExpiry(spot, expiry)[eventId(signal, spot, expiry, duration, entryIso, type)];
    if (!rec) return null;
    const S = stats();
    return {
        ratio: rec.r,
        labels: (rec.l || []).map(code => ({ code, ...(S[code] || { text: code, tier: 'context' }) })),
    };
}

module.exports = { available, stats, forExpiry, eventId, lookup, BASE };
