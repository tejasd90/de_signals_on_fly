// spot_store.js
// ─────────────────────────────────────────────────────────────────────────────
// Spot (underlying) candles: fetching, storage and lookup.
//
// WHY SEPARATE FROM candle_store
// Option candles belong to an expiry and die with it. Spot is continuous — one
// series per (spot, duration) spanning all expiries — so it cannot live under
// data/candles/{spot}/{expiry}/. It gets its own tree, matching the layout of
// the original fetch_spot_candles.js:
//
//   data/spot_candles/{spot}/{duration}/{YYYY-MM-DD}     date-partitioned
//   data/markers/spot/{spot}/{duration}/end              last fetched timestamp
//
// Symbol follows the original getSpotSymbol(): BTC -> MARK:BTCUSD.
//
// WHY IT IS NEEDED AGAIN
// Signals that require an option to be OTM cannot determine moneyness without
// spot. A call is OTM when strike > spot, a put when strike < spot — and which
// instruments qualify changes with every spot tick, so the check has to be made
// per candle, not once per expiry.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs     = require('fs');
const path   = require('path');
const cfg    = require('./config');
const logger = require('./logger');
const api    = require('./api');
const grouper = require('./grouper');

// ─── Paths ────────────────────────────────────────────────────────────────────

function spotDir(spot, duration) {
    return path.join(cfg.SPOT_CANDLES_BASE_DIR, spot, String(duration));
}

function spotMarkerPath(spot, duration) {
    return path.join(cfg.SPOT_MARKERS_BASE_DIR, spot, String(duration), 'end');
}

/** BTC -> MARK:BTCUSD, matching the original getSpotSymbol(). */
function spotSymbol(spot) {
    return `MARK:${spot}USD`;
}

// ─── Storage ──────────────────────────────────────────────────────────────────

/**
 * Write spot candles, partitioned by date and merged with anything already
 * stored for that date. Compact array form, same as candle_store.
 */
function storeSpotCandles(spot, duration, candles) {
    if (!candles || candles.length === 0) return 0;

    const dir = spotDir(spot, duration);
    fs.mkdirSync(dir, { recursive: true });

    const byDate = {};
    for (const c of candles) {
        const d = c.dtstring.substring(0, 10);
        (byDate[d] = byDate[d] || []).push(c);
    }

    let written = 0;
    for (const [date, dayCandles] of Object.entries(byDate)) {
        const file = path.join(dir, date);

        // Merge with existing: a re-fetch overlaps the tail of the last run.
        const merged = new Map();
        if (fs.existsSync(file)) {
            try {
                for (const a of JSON.parse(fs.readFileSync(file, 'utf8'))) merged.set(a[0], a);
            } catch (_) {}
        }
        for (const c of dayCandles) {
            merged.set(c.time, [c.time, c.open, c.high, c.low, c.close, c.volume]);
        }

        const out = [...merged.values()].sort((a, b) => a[0] - b[0]);
        const tmp = `${file}.tmp.${process.pid}`;
        try {
            fs.writeFileSync(tmp, JSON.stringify(out));
            fs.renameSync(tmp, file);
            written += out.length;
        } catch (err) {
            try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
            logger.error('spot_store', `storeSpotCandles failed: ${file}`, err);
        }
    }
    return written;
}

/**
 * Read stored spot candles for a duration over a date range (inclusive).
 * @returns {Object[]} rehydrated candle objects, ascending by time
 */
function readSpotCandles(spot, duration, fromDate = '', toDate = '') {
    const dir = spotDir(spot, duration);
    if (!fs.existsSync(dir)) return [];

    const files = fs.readdirSync(dir)
        .filter(f => !f.startsWith('.') && !f.includes('.tmp.'))
        .filter(f => (!fromDate || f >= fromDate) && (!toDate || f <= toDate))
        .sort();

    const out = [];
    for (const f of files) {
        try {
            for (const [time, open, high, low, close, volume] of
                 JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'))) {
                out.push({ time, dtstring: api.formatTs(time), open, high, low, close, volume });
            }
        } catch (err) {
            logger.error('spot_store', `readSpotCandles failed: ${dir}/${f}`, err);
        }
    }
    return out;
}

// ─── Derived-series cache ─────────────────────────────────────────────────────
//
// Spot is continuous and expiry-independent, so the grouped series for a given
// (spot, duration) is identical no matter which expiry is being processed.
// Without a cache, processor.js rebuilds it once per signal per expiry: measured
// at 727ms per pass over 16 durations with only 40 days stored, which at the
// configured 400 days and a thousand expiries becomes hours of pure re-grouping.
//
// Cached by (spot, duration). Memory is bounded by the number of spots times
// durations — one series each, not one per expiry. Call clearCache() if a long
// run needs the memory back.
const _indexCache = new Map();

function cacheKey(spot, duration, fromDate, toDate) {
    return `${spot}|${duration}|${fromDate}|${toDate}`;
}

/** Drop cached spot series. */
function clearCache() {
    _indexCache.clear();
}

/**
 * Spot candles for a duration, as a Map keyed by dtstring.
 *
 * Signals need "what was spot at this option candle's timestamp", which is a
 * hot lookup inside a per-candle loop — hence a Map rather than a scan.
 *
 * Durations are derived by grouping the stored base series, so only base
 * durations need fetching. sourceFor() gives the largest direct-fetch duration
 * that divides the target, so this is always one grouping step.
 */
function spotIndexFor(spot, duration, fromDate = '', toDate = '') {
    const key = cacheKey(spot, duration, fromDate, toDate);
    const hit = _indexCache.get(key);
    if (hit) return hit;

    // Preferred source, then any other stored base that divides the target.
    // fetchAllSpotCandles stores every base, but a partial fetch — or one
    // interrupted midway — would otherwise silently yield an empty index and
    // make every OTM signal quietly produce nothing.
    let src  = grouper.sourceFor(duration);
    let base = src === null ? [] : readSpotCandles(spot, src, fromDate, toDate);

    if (base.length === 0) {
        const dir = path.join(cfg.SPOT_CANDLES_BASE_DIR, spot);
        const stored = fs.existsSync(dir)
            ? fs.readdirSync(dir).filter(d => !isNaN(d)).map(Number)
            : [];

        // Largest divisor first: fewer source candles for the same span.
        const usable = stored.filter(b => duration % b === 0).sort((a, b) => b - a);
        for (const b of usable) {
            base = readSpotCandles(spot, b, fromDate, toDate);
            if (base.length > 0) { src = b; break; }
        }
    }

    if (base.length === 0) {
        logger.log('spot_store',
            `No spot candles usable for ${spot} at ${duration}m — OTM signals will skip it`);
        // Cached too: a missing series stays missing until candles are fetched,
        // and re-reading an empty directory thousands of times is pure waste.
        _indexCache.set(key, makeSpotLookup([]));
        return _indexCache.get(key);
    }

    const candles = (src === duration) ? base : grouper.groupCandles(base, duration);

    const index = makeSpotLookup(candles);

    logger.debug('spot_store',
        `Built spot index ${spot} ${duration}m from ${src}m: ${index.size} candles (cached)`);

    _indexCache.set(key, index);
    return index;
}

/**
 * Map-like lookup that tolerates misaligned candle boundaries.
 *
 * WHY NOT A PLAIN MAP
 * Exact dtstring matching assumes spot and option candles share slot boundaries.
 * They often do not. getKeyDuration anchors grouped candles at 17:30 IST, so a
 * grouped 60m series lands on :30 while a directly-fetched 60m series lands on
 * :00. Observed directly in testing: 498 option candles, 960 spot candles,
 * ZERO exact matches — and because a miss just means "not OTM", every signal
 * silently vanished with no error.
 *
 * So: try the exact key first, and otherwise binary-search for the last spot
 * candle at or before the requested time. That is the candle in force at that
 * instant, which is what moneyness actually needs.
 *
 * Exposes .get() and .size so callers use it exactly like the Map it replaces.
 */
function makeSpotLookup(candles) {
    const exact  = new Map();
    const sorted = candles.slice().sort((a, b) => a.time - b.time);
    for (const c of sorted) exact.set(c.dtstring, c);

    const times = sorted.map(c => c.time);

    return {
        size: sorted.length,

        /**
         * All candles, ascending by time. Present because callers reasonably
         * expect a Map-like object to be iterable — live_runner needs the
         * series for EMAs and the latest price, and reached for .values()
         * before this existed.
         */
        values() { return sorted; },
        all()    { return sorted; },
        last()   { return sorted.length ? sorted[sorted.length - 1] : null; },

        get(dtstring) {
            const hit = exact.get(dtstring);
            if (hit) return hit;
            if (sorted.length === 0) return undefined;

            const t = Math.floor(new Date(dtstring).getTime() / 1000);
            if (Number.isNaN(t) || t < times[0]) return undefined;

            // Last candle at or before t.
            let lo = 0, hi = times.length - 1, ans = -1;
            while (lo <= hi) {
                const mid = (lo + hi) >> 1;
                if (times[mid] <= t) { ans = mid; lo = mid + 1; }
                else hi = mid - 1;
            }
            return ans >= 0 ? sorted[ans] : undefined;
        },
        has(dtstring) { return this.get(dtstring) !== undefined; },
    };
}

// ─── Fetching ─────────────────────────────────────────────────────────────────

function readMarker(spot, duration) {
    const p = spotMarkerPath(spot, duration);
    if (!fs.existsSync(p)) return null;
    const v = parseInt(fs.readFileSync(p, 'utf8').trim(), 10);
    return Number.isNaN(v) ? null : v;
}

function writeMarker(spot, duration, unixSeconds) {
    const p = spotMarkerPath(spot, duration);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, String(unixSeconds));
}

/**
 * Fetch and store spot candles for one spot at one base duration.
 *
 * Incremental: resumes from the stored marker minus a small overlap, so a
 * partially-formed candle at the boundary is refetched rather than frozen.
 * With no marker it reaches back SPOT_HISTORY_DAYS.
 */
async function fetchSpotCandles(spot, duration, { force = false, fromDate = null } = {}) {
    const resolution = cfg.DIRECT_DURATIONS[duration];
    if (!resolution) {
        logger.error('spot_store', `${duration}m is not directly fetchable`);
        return { skipped: 'not_direct' };
    }

    const nowUnix = Math.floor(Date.now() / 1000);
    const marker  = force ? null : readMarker(spot, duration);

    // Default reach-back when there is no marker.
    let from = marker
        ? marker - cfg.SPOT_REFETCH_OVERLAP_MINUTES * 60
        : nowUnix - cfg.SPOT_HISTORY_DAYS * 24 * 3600;

    // An explicit start date always wins, and EXTENDS BACKWARDS past whatever is
    // already stored.
    //
    // This closes a trap that silently capped history. The marker is rewritten to
    // now after every successful fetch, so `from` was only ever `marker - 30min`
    // — the series could grow forwards but never backwards. --force reset the
    // marker to null, but that just recomputed `now - SPOT_HISTORY_DAYS`, landing
    // on the same start date again. With the 400-day default that pinned every
    // spot series to a fixed floor roughly 400 days before the first run, and no
    // combination of flags could reach past it.
    if (fromDate) {
        const requested = Math.floor(new Date(`${fromDate}T00:00:00+0530`).getTime() / 1000);
        if (!Number.isNaN(requested)) from = Math.min(from, requested);
    }

    if (from >= nowUnix) return { skipped: 'up_to_date' };

    try {
        const raw = await api.fetchCandles(spotSymbol(spot), resolution, from, nowUnix);
        if (raw.length === 0) return { skipped: 'no_data' };

        const stored = storeSpotCandles(spot, duration, raw);
        writeMarker(spot, duration, nowUnix);

        logger.log('spot_store',
            `${spot} ${duration}m: fetched ${raw.length}, stored ${stored} ` +
            `(from ${api.formatTs(from).substring(0, 10)})`);
        return { fetched: raw.length, stored };
    } catch (err) {
        // Retries are already exhausted inside api.fetchCandles. Leave the
        // marker untouched so the next run refetches this window.
        logger.error('spot_store', `fetchSpotCandles failed: ${spot} ${duration}m`, err);
        return { failed: true, error: err.message };
    }
}

/**
 * Fetch every base duration that any configured duration derives from.
 * Only base durations are stored; the rest are grouped on read.
 */
async function fetchAllSpotCandles(spot, opts = {}) {
    // Any change to the stored range invalidates cached derived series.
    clearCache();
    const bases = new Set();
    for (const d of Object.keys(cfg.DURATION_TIMES).map(Number)) {
        const src = grouper.sourceFor(d);
        if (src !== null) bases.add(src);
    }

    const results = {};
    for (const base of [...bases].sort((a, b) => a - b)) {
        results[base] = await fetchSpotCandles(spot, base, opts);
    }
    return results;
}

/** True if any spot candles are stored for this spot. */
function hasSpotCandles(spot) {
    const dir = path.join(cfg.SPOT_CANDLES_BASE_DIR, spot);
    if (!fs.existsSync(dir)) return false;
    return fs.readdirSync(dir).some(d => {
        const sub = path.join(dir, d);
        return fs.statSync(sub).isDirectory() && fs.readdirSync(sub).length > 0;
    });
}

module.exports = {
    spotSymbol,
    storeSpotCandles,
    readSpotCandles,
    spotIndexFor,
    clearCache,
    fetchSpotCandles,
    fetchAllSpotCandles,
    hasSpotCandles,
};
