// writer.js
// ─────────────────────────────────────────────────────────────────────────────
// Write signal results to disk and manage past-complete markers.
//
// Signal output structure:
//   data/signals/{signalId}/{spot}/{duration}/{expiryDate}.json
//
// Each file contains:
//   {
//     C: [ mergedRange, ... ],   — call signals
//     P: [ mergedRange, ... ],   — put signals
//     updatedAt: ISO string,
//   }
//
// Past-complete markers:
//   data/markers/past_complete/{spot}/{expiryDate}
//   Presence means: this past expiry is fully processed, skip re-fetching.
//   Delete the marker to force reprocessing.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs     = require('fs');
const path   = require('path');
const cfg    = require('./config');
const logger = require('./logger');

// ─── Signal files ─────────────────────────────────────────────────────────────

function signalFilePath(signalId, spot, duration, expiryDate) {
    return path.join(cfg.SIGNALS_BASE_DIR, signalId, spot, String(duration), `${expiryDate}.json`);
}

/**
 * Write merged signal ranges for one (signalId, spot, duration, expiry).
 *
 * The write is ATOMIC: content goes to a unique temp file in the same directory,
 * then rename() swaps it into place. rename() within a filesystem is atomic, so a
 * concurrent reader (quality.js, or another worker) always sees either the old
 * complete file or the new complete file — never a half-written one. A plain
 * writeFileSync can be observed mid-write and yields unparseable JSON.
 *
 * @param {string}  signalId
 * @param {string}  spot
 * @param {number}  duration
 * @param {string}  expiryDate
 * @param {Array[]} callRanges — merged C ranges from merger.mergeSignals
 * @param {Array[]} putRanges  — merged P ranges
 */
function writeSignals(signalId, spot, duration, expiryDate, callRanges, putRanges) {
    const filePath = signalFilePath(signalId, spot, duration, expiryDate);
    fs.mkdirSync(path.dirname(filePath), { recursive: true });

    const output = {
        C:         callRanges,
        P:         putRanges,
        updatedAt: new Date().toISOString(),
    };

    // Temp name includes pid so two processes never collide on the temp file
    const tmpPath = `${filePath}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmpPath, JSON.stringify(output));
        fs.renameSync(tmpPath, filePath);
    } catch (err) {
        try { if (fs.existsSync(tmpPath)) fs.unlinkSync(tmpPath); } catch (_) {}
        throw err;
    }

    logger.log('signal_writer',
        `Wrote ${signalId}/${spot}/${duration}/${expiryDate}: ` +
        `C=${callRanges.length} P=${putRanges.length} ranges`);
}

/**
 * Read an existing signal file. Returns { C: [], P: [] } if absent or unreadable.
 */
function readSignals(signalId, spot, duration, expiryDate) {
    const filePath = signalFilePath(signalId, spot, duration, expiryDate);
    if (!fs.existsSync(filePath)) return { C: [], P: [] };
    try {
        return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch (err) {
        logger.error('signal_writer', `readSignals failed: ${filePath}`, err);
        return { C: [], P: [] };
    }
}

/**
 * Delete signal files for durations that are no longer active.
 *
 * Without this, removing a duration from DURATION_TIMES (or narrowing its start
 * window so it stops applying) leaves its last-written file on disk forever, and
 * quality.js keeps reporting those stale numbers as if they were current.
 */
function removeStaleDurations(signalId, spot, expiryDate, activeDurations) {
    const spotDir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot);
    if (!fs.existsSync(spotDir)) return;

    const active = new Set(activeDurations.map(String));

    for (const dur of fs.readdirSync(spotDir)) {
        if (dur.startsWith('.') || active.has(dur)) continue;
        const f = path.join(spotDir, dur, `${expiryDate}.json`);
        if (fs.existsSync(f)) {
            fs.unlinkSync(f);
            logger.log('signal_writer',
                `Removed stale duration file: ${signalId}/${spot}/${dur}/${expiryDate}`);
        }
    }
}

// ─── Per-expiry summary ───────────────────────────────────────────────────────
//
// A calendar view needs one number per side per expiry: the best ratio anywhere
// in that expiry. Deriving it live would mean reading every duration file for
// every expiry — roughly 16,000 reads on a full history, on every page load.
//
// Signals live at {spot}/{duration}/{expiry}.json, so a per-expiry summary has
// to be gathered ACROSS duration directories, unlike trades.js where an expiry
// is already its own directory.
//
// Both ratio definitions are stored, because the viewer can toggle between them
// and recomputing on toggle would defeat the point.
//
//   data/signals/{signalId}/{spot}/_summary/{expiry}.json

function summaryPath(signalId, spot, expiry) {
    return path.join(cfg.SIGNALS_BASE_DIR, signalId, spot, '_summary', `${expiry}.json`);
}

function buildExpirySummary(signalId, spot, expiry) {
    const spotDir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot);
    if (!fs.existsSync(spotDir)) return null;

    const durations = fs.readdirSync(spotDir)
        .filter(d => !d.startsWith('.') && !d.startsWith('_') && !isNaN(d))
        .map(Number).sort((a, b) => a - b);

    const out = {
        expiry, durations: [],
        firedC: 0, firedP: 0,      // maxSignalRatio  (index 4)
        univC:  0, univP:  0,      // universeMaxRatio (index 7)
        cCount: 0, pCount: 0,
    };

    for (const d of durations) {
        const f = path.join(spotDir, String(d), `${expiry}.json`);
        if (!fs.existsSync(f)) continue;

        let data;
        try { data = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (_) { continue; }

        let any = false;
        for (const [type, fk, uk, ck] of
             [['C', 'firedC', 'univC', 'cCount'], ['P', 'firedP', 'univP', 'pCount']]) {
            const rows = data[type] || [];
            if (rows.length) any = true;
            out[ck] += rows.length;
            for (const r of rows) {
                const fired = Number(r[4]) || 0;
                const univ  = Number(r[7]) || 0;
                if (fired > out[fk]) out[fk] = fired;
                if (univ  > out[uk]) out[uk] = univ;
            }
        }
        if (any || fs.existsSync(f)) out.durations.push(d);
    }

    return out;
}

/** Build and persist the summary for one (signalId, spot, expiry). */
function writeExpirySummary(signalId, spot, expiry) {
    const s = buildExpirySummary(signalId, spot, expiry);
    if (!s) return null;

    const p = summaryPath(signalId, spot, expiry);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(s));
        fs.renameSync(tmp, p);
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        logger.error('signal_writer', `writeExpirySummary failed: ${p}`, err);
    }
    return s;
}

function readExpirySummary(signalId, spot, expiry) {
    const p = summaryPath(signalId, spot, expiry);
    if (!fs.existsSync(p)) return null;
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}

// ─── Signals-complete marker ──────────────────────────────────────────────────
//
// Deliberately separate from candle_store's candles_complete marker. The two
// answer different questions:
//
//   candles_complete — candles are on disk. Expensive (API calls). Never redone
//                      unless explicitly forced.
//   signals_complete — signals have been computed from those candles. Cheap
//                      (pure CPU). Must be redone whenever a signal parameter
//                      changes: MIN_SEQ_LENGTH, THRESHOLD, signalFn, DURATION_TIMES.
//
// Clearing signals_complete alone gives a full recompute with zero API calls.
// That separation is the whole reason candles are stored.

function signalsCompleteMarkerPath(spot, expiryDate) {
    return path.join(cfg.SIGNALS_COMPLETE_MARKERS_DIR, spot, expiryDate);
}

function isSignalsComplete(spot, expiryDate) {
    return fs.existsSync(signalsCompleteMarkerPath(spot, expiryDate));
}

function markSignalsComplete(spot, expiryDate) {
    const p = signalsCompleteMarkerPath(spot, expiryDate);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, new Date().toISOString());
    logger.log('signal_writer', `Signals complete: ${spot}/${expiryDate}`);
}

function clearSignalsComplete(spot, expiryDate) {
    const p = signalsCompleteMarkerPath(spot, expiryDate);
    if (fs.existsSync(p)) fs.unlinkSync(p);
}

// ─── Cooperative claims (safe concurrency between main.js and backfill.js) ────
//
// Both main.js and backfill.js process PAST expiries. Without coordination they
// can pick the same (spot, expiry) at the same moment: both see no completion
// marker, both fetch the same candles, both write the same files. That wastes
// the one genuinely scarce resource — API calls.
//
// A claim is an exclusive-create lockfile. fs.openSync with the 'wx' flag fails
// if the path already exists, and that check-and-create is atomic at the OS
// level, so exactly one process can win a claim no matter how the two interleave.
//
// Claims are advisory and self-healing: a stale claim left behind by a crashed
// process expires after CLAIM_TTL_MS and is reclaimed automatically.

const CLAIM_TTL_MS = 30 * 60 * 1000;   // 30 minutes

function claimPath(spot, expiryDate) {
    return path.join(cfg.SIGNALS_COMPLETE_MARKERS_DIR, spot, `${expiryDate}.claim`);
}

/**
 * Try to take exclusive ownership of a (spot, expiry) for processing.
 *
 * @returns {boolean} true if this process now owns it, false if another
 *                    process holds a live claim.
 */
function claimPastExpiry(spot, expiryDate) {
    const p = claimPath(spot, expiryDate);
    fs.mkdirSync(path.dirname(p), { recursive: true });

    try {
        // 'wx' = create exclusively; throws EEXIST if the file already exists.
        const fd = fs.openSync(p, 'wx');
        fs.writeSync(fd, JSON.stringify({ pid: process.pid, at: new Date().toISOString() }));
        fs.closeSync(fd);
        return true;
    } catch (err) {
        if (err.code !== 'EEXIST') {
            logger.error('signal_writer', `claimPastExpiry failed: ${spot}/${expiryDate}`, err);
            return false;
        }
    }

    // A claim exists — take it over only if it is stale (owner likely died).
    try {
        const ageMs = Date.now() - fs.statSync(p).mtimeMs;
        if (ageMs > CLAIM_TTL_MS) {
            logger.log('signal_writer',
                `Reclaiming stale claim (${Math.round(ageMs / 60000)}m old): ${spot}/${expiryDate}`);
            fs.unlinkSync(p);
            return claimPastExpiry(spot, expiryDate);
        }
    } catch (_) {
        // Claim vanished between the EEXIST and the stat — another process
        // finished and released it. Leave it to the next iteration.
    }

    return false;
}

/**
 * Release a claim taken by claimPastExpiry. Safe to call if absent.
 * Must be called in a finally block so a failed run does not block retries.
 */
function releasePastExpiry(spot, expiryDate) {
    try {
        const p = claimPath(spot, expiryDate);
        if (fs.existsSync(p)) fs.unlinkSync(p);
    } catch (err) {
        logger.error('signal_writer', `releasePastExpiry failed: ${spot}/${expiryDate}`, err);
    }
}

module.exports = {
    writeSignals,
    readSignals,
    removeStaleDurations,
    writeExpirySummary,
    readExpirySummary,
    buildExpirySummary,
    summaryPath,
    isSignalsComplete,
    markSignalsComplete,
    clearSignalsComplete,
    claimPastExpiry,
    releasePastExpiry,
};
