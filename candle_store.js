// candle_store.js
// ─────────────────────────────────────────────────────────────────────────────
// Durable storage of BASE candles for PAST expiries.
//
// WHY THIS EXISTS
// Signal parameters change often (MIN_SEQ_LENGTH, THRESHOLD, signalFn, the
// DURATION_TIMES windows). Before this file, every such change meant re-fetching
// every candle from the exchange — hours of API calls to answer a question that
// is pure CPU. Now candles for a settled expiry are fetched exactly once and
// kept; re-running signals against them costs no API calls at all.
//
// WHAT IS STORED
// EVERY duration in DURATION_TIMES, each trimmed to its OWN window.
//
// An earlier version stored only the direct-fetch base durations, but at the
// full PRIOR_DAYS span so a base could feed the longest chain built on it. That
// meant keeping 40 days of 5m candles (11,520) purely so 40m could be derived,
// when the 5m signal itself only ever looks back 2 days (576). Storing each
// duration at its own window instead cut disk per instrument from ~19,000
// candles to ~7,900 — and reading is simpler, since no grouping is needed at all
// on the signal path.
//
// Sources are still fetched deduplicated (5m feeds 5/10/20/40 in one download)
// but only the target durations reach disk; the wide source array is discarded
// once grouping is done.
//
// Past expiries only. Live expiries stay in memory (main.js), because their
// candles are still changing and would be stale the moment they were written.
//
// FETCH WINDOW
// Each duration is stored for exactly its DURATION_TIMES window. Widening a
// window later therefore DOES require a refetch of that duration
// (--candles-only --force-candles). That is the deliberate trade for the disk
// saving; window changes are rare, signal-parameter changes are not, and those
// remain free.
//
// ON-DISK FORMAT
// Candles are stored as compact arrays [time, open, high, low, close, volume]
// rather than objects. At ~11,500 five-minute candles per instrument over 40
// days, the object form costs roughly 100 bytes per candle; the array form is
// closer to 40. Across hundreds of instruments and many expiries that is the
// difference between tens and hundreds of gigabytes. dtstring is rebuilt on
// read from `time`, so nothing is lost.
//
// LAYOUT
//   data/candles/{spot}/{expiry}/{duration}/{symbol}.json
//   data/markers/candles_complete/{spot}/{expiry}
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs     = require('fs');
const path   = require('path');
const cfg    = require('./config');
const logger = require('./logger');
const api    = require('./api');

// ─── Paths ────────────────────────────────────────────────────────────────────

function candleDir(spot, expiryDate, duration) {
    return path.join(cfg.CANDLES_BASE_DIR, spot, expiryDate, String(duration));
}

function candleFile(spot, expiryDate, duration, symbol) {
    // Symbols contain '-' but no path separators, so they are safe as filenames.
    return path.join(candleDir(spot, expiryDate, duration), `${symbol}.json`);
}

function candlesCompleteMarker(spot, expiryDate) {
    return path.join(cfg.CANDLES_COMPLETE_MARKERS_DIR, spot, expiryDate);
}

// ─── Write ────────────────────────────────────────────────────────────────────

/**
 * Persist one instrument's base candles.
 *
 * Written atomically (temp file + rename) so a concurrent reader — quality.js,
 * or another worker — never observes a half-written file.
 *
 * @param {string}   spot
 * @param {string}   expiryDate
 * @param {number}   duration      — minutes, any duration in DURATION_TIMES
 * @param {string}   symbol
 * @param {Object[]} candles       — [{ time, open, high, low, close, volume }]
 */
function writeCandles(spot, expiryDate, duration, symbol, candles) {
    if (!candles || candles.length === 0) return;

    const file = candleFile(spot, expiryDate, duration, symbol);
    fs.mkdirSync(path.dirname(file), { recursive: true });

    // Compact array form — see ON-DISK FORMAT note above.
    const compact = candles.map(c => [c.time, c.open, c.high, c.low, c.close, c.volume]);

    const tmp = `${file}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(compact));
        fs.renameSync(tmp, file);
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        throw err;
    }
}

// ─── Read ─────────────────────────────────────────────────────────────────────

/**
 * Read one instrument's stored base candles, rehydrated to full objects.
 * Returns [] when nothing is stored.
 */
function readCandles(spot, expiryDate, duration, symbol) {
    const file = candleFile(spot, expiryDate, duration, symbol);
    if (!fs.existsSync(file)) return [];

    try {
        const compact = JSON.parse(fs.readFileSync(file, 'utf8'));
        return compact.map(([time, open, high, low, close, volume]) => ({
            time,
            dtstring: api.formatTs(time),   // rebuilt, not stored
            open, high, low, close, volume,
        }));
    } catch (err) {
        logger.error('candle_store', `readCandles failed: ${file}`, err);
        return [];
    }
}

/**
 * Which durations have stored candles for this (spot, expiry).
 */
function storedDurations(spot, expiryDate) {
    const dir = path.join(cfg.CANDLES_BASE_DIR, spot, expiryDate);
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
        .filter(d => !d.startsWith('.') && !isNaN(d))
        .map(Number)
        .sort((a, b) => a - b);
}

/**
 * Which instrument symbols have stored candles at this duration.
 */
function storedSymbols(spot, expiryDate, duration) {
    const dir = candleDir(spot, expiryDate, duration);
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
        .filter(f => !f.startsWith('.') && f.endsWith('.json') && !f.includes('.tmp.'))
        .map(f => f.replace(/\.json$/, ''));
}

// ─── Completion marker ────────────────────────────────────────────────────────
//
// Deliberately separate from the SIGNALS-complete marker. The two answer
// different questions:
//
//   candles_complete — every instrument's candles are on disk. Expensive to
//                      produce (API calls), so never redone unless forced.
//   signals_complete — signals have been computed from those candles. Cheap to
//                      redo, and must be redone whenever signal parameters change.
//
// Clearing signals_complete alone triggers a full recompute with zero API calls.

function isCandlesComplete(spot, expiryDate) {
    return fs.existsSync(candlesCompleteMarker(spot, expiryDate));
}

function markCandlesComplete(spot, expiryDate, meta = {}) {
    const p = candlesCompleteMarker(spot, expiryDate);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, JSON.stringify({ at: new Date().toISOString(), ...meta }));
    logger.log('candle_store', `Candles complete: ${spot}/${expiryDate}`);
}

// ─── Progress state (crash / outage resumability) ─────────────────────────────
//
// A store run over hundreds of instruments will sometimes be interrupted: a
// power cut, Ctrl-C, an outage longer than the retry budget. Without a record of
// what finished, the only safe response is to redo the whole expiry.
//
// After each instrument completes, its symbol is appended here. A re-run reads
// the file and skips those symbols, so an interrupted run resumes rather than
// restarts. The file is deleted once the expiry is marked complete.
//
//   data/markers/candles_complete/{spot}/{expiry}.progress
//     { done: [symbol...], failed: [{symbol, error}...], updatedAt }

function progressPath(spot, expiryDate) {
    return path.join(cfg.CANDLES_COMPLETE_MARKERS_DIR, spot, `${expiryDate}.progress`);
}

function readProgress(spot, expiryDate) {
    const p = progressPath(spot, expiryDate);
    if (!fs.existsSync(p)) return { done: [], failed: [] };
    try {
        const j = JSON.parse(fs.readFileSync(p, 'utf8'));
        return { done: j.done || [], failed: j.failed || [] };
    } catch (err) {
        logger.error('candle_store', `Corrupt progress file, starting fresh: ${p}`, err);
        return { done: [], failed: [] };
    }
}

function writeProgress(spot, expiryDate, progress) {
    const p = progressPath(spot, expiryDate);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify({ ...progress, updatedAt: new Date().toISOString() }));
        fs.renameSync(tmp, p);
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        logger.error('candle_store', `writeProgress failed: ${p}`, err);
    }
}

function clearProgress(spot, expiryDate) {
    const p = progressPath(spot, expiryDate);
    if (fs.existsSync(p)) fs.unlinkSync(p);
}

function clearCandlesComplete(spot, expiryDate) {
    const p = candlesCompleteMarker(spot, expiryDate);
    if (fs.existsSync(p)) fs.unlinkSync(p);
}

// ─── Disk usage helper ────────────────────────────────────────────────────────

/**
 * Approximate bytes on disk for one (spot, expiry). Useful for capacity checks
 * before committing to a long backfill.
 */
function diskUsage(spot, expiryDate) {
    const dir = path.join(cfg.CANDLES_BASE_DIR, spot, expiryDate);
    if (!fs.existsSync(dir)) return 0;

    let total = 0;
    for (const dur of storedDurations(spot, expiryDate)) {
        const d = candleDir(spot, expiryDate, dur);
        for (const f of fs.readdirSync(d)) {
            try { total += fs.statSync(path.join(d, f)).size; } catch (_) {}
        }
    }
    return total;
}

module.exports = {
    readProgress,
    writeProgress,
    clearProgress,
    writeCandles,
    readCandles,
    storedDurations,
    storedSymbols,
    isCandlesComplete,
    markCandlesComplete,
    clearCandlesComplete,
    diskUsage,
    candleDir,
    candleFile,
};
