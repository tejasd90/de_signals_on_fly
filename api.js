// api.js
// ─────────────────────────────────────────────────────────────────────────────
// Thin wrapper around the Delta Exchange REST API.
// Reuses the apiFetch + fetchCandles pattern from the original utils.js.
// Adds configurable per-call delay to stay within rate limits.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg    = require('./config');
const logger = require('./logger');

// ─── Delay ───────────────────────────────────────────────────────────────────

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// ─── Error classification ─────────────────────────────────────────────────────

/**
 * Is this failure worth retrying?
 *
 * Retryable — the request was fine, the world was temporarily not:
 *   network errors (DNS, connection reset, timeout — power cuts, wifi drops)
 *   HTTP 429  rate limited
 *   HTTP 5xx  exchange-side fault
 *
 * Not retryable — repeating it will fail identically and just burn quota:
 *   HTTP 4xx other than 429 (bad symbol, malformed range, auth)
 */
function isRetryable(err) {
    if (err && err.httpStatus !== undefined) {
        return err.httpStatus === 429 || err.httpStatus >= 500;
    }
    return true;   // no status => transport-level failure => retry
}

// ─── Core fetch ───────────────────────────────────────────────────────────────

/**
 * One HTTP GET against the API, with bounded retries and exponential backoff.
 *
 * The original code had utils.fetchWithRetry (5 attempts); this was dropped in an
 * earlier rewrite and is restored here. Without it a single dropped packet during
 * a multi-hour backfill aborts that instrument silently.
 *
 * Backoff doubles each attempt from API_RETRY_BASE_DELAY_MS, with a longer floor
 * for 429 so a rate-limit breach is not immediately re-triggered.
 *
 * Throws only after every attempt is exhausted, or immediately for a
 * non-retryable error. Callers can therefore treat a throw as final.
 */
async function apiFetch(path, queryObj = {}) {
    const queryString = Object.keys(queryObj).length
        ? '?' + new URLSearchParams(queryObj).toString()
        : '';
    const url = cfg.API_BASE_URL + path + queryString;

    let lastErr;

    for (let attempt = 1; attempt <= cfg.API_MAX_RETRIES; attempt++) {
        try {
            const headers = { 'Accept': 'application/json' };
            if (cfg.API_KEY) {
                const crypto    = require('crypto');
                const timestamp = Math.floor(Date.now() / 1000);
                const message   = 'GET' + timestamp + path + queryString;
                headers['api-key']   = cfg.API_KEY;
                headers['timestamp'] = timestamp;
                headers['signature'] = crypto.createHmac('sha256', cfg.API_SECRET)
                    .update(message).digest('hex');
            }

            const response = await fetch(url, { method: 'GET', headers });

            if (!response.ok) {
                const body = await response.text();
                const e = new Error(`HTTP ${response.status}: ${body.substring(0, 200)}`);
                e.httpStatus = response.status;
                throw e;
            }

            const data = await response.json();
            if (!data.success) {
                const e = new Error(`API error: ${JSON.stringify(data.error)}`);
                e.httpStatus = 200;          // server answered; do not retry
                throw e;
            }

            await delay(cfg.API_CALL_DELAY_MS);
            return data;

        } catch (err) {
            lastErr = err;

            if (!isRetryable(err)) {
                logger.error('fetcher', `Non-retryable, giving up: ${url}`, err);
                throw err;
            }

            if (attempt === cfg.API_MAX_RETRIES) break;

            // Exponential backoff; 429 gets a higher floor.
            let wait = cfg.API_RETRY_BASE_DELAY_MS * Math.pow(2, attempt - 1);
            if (err.httpStatus === 429) {
                wait = Math.max(wait, cfg.API_RATE_LIMIT_BACKOFF_MS);
            }

            logger.log('fetcher',
                `Attempt ${attempt}/${cfg.API_MAX_RETRIES} failed (${err.message.substring(0, 80)}), ` +
                `retrying in ${wait}ms`);
            await delay(wait);
        }
    }

    logger.error('fetcher',
        `All ${cfg.API_MAX_RETRIES} attempts failed: ${url}`, lastErr);
    throw lastErr;
}

// ─── Candle fetch ─────────────────────────────────────────────────────────────

/**
 * Fetch all candles for one instrument over a time range.
 * Paginates backward automatically (same logic as original utils.fetchCandles).
 *
 * @param {string} symbol      — e.g. 'MARK:C-BTC-92400-271125'
 * @param {string} resolution  — API resolution string e.g. '5m', '1h', '4h'
 * @param {number} start       — unix seconds
 * @param {number} end         — unix seconds
 * @returns {Object[]}         — candles sorted ascending by time
 *                               { time, open, high, low, close, volume }
 */
async function fetchCandles(symbol, resolution, start, end) {
    // Compute seconds per candle from resolution string
    const resolutionSeconds = parseResolutionToSeconds(resolution);
    const maxWindow = cfg.MAX_CANDLES_PER_REQUEST * resolutionSeconds;

    let allCandles = [];
    let currentEnd = end;

    while (currentEnd > start) {
        const currentStart = Math.max(currentEnd - maxWindow, start);
        const query = { symbol, resolution, start: currentStart, end: currentEnd };

        // Deliberately NOT wrapped in try/catch. Previously a failed page was
        // caught and the loop broke, returning whatever pages had already
        // succeeded — a silently truncated candle series that downstream code
        // could not distinguish from a complete one, and which then got stored
        // and marked complete. A partial series is worse than no series, so the
        // error propagates and the caller decides.
        const response = await apiFetch('/v2/history/candles', query);

        const candles = response.result || [];
        if (candles.length === 0) break;

        const parsed = candles.map(c => ({
            time:   c.time,
            open:   parseFloat(c.open),
            high:   parseFloat(c.high),
            low:    parseFloat(c.low),
            close:  parseFloat(c.close),
            volume: parseFloat(c.volume),
        }));

        allCandles = allCandles.concat(parsed);
        currentEnd = currentStart - resolutionSeconds;
    }

    // Sort ascending and add dtstring (matches original utils pattern)
    allCandles.sort((a, b) => a.time - b.time);
    allCandles.forEach(c => { c.dtstring = formatTs(c.time); });

    logger.debug('fetcher', `fetchCandles ${symbol} ${resolution}: ${allCandles.length} candles`);
    return allCandles;
}

// ─── Instrument list ──────────────────────────────────────────────────────────

/**
 * Fetch all option products (call + put) for a given state.
 * Paginates automatically using the meta.before/after cursor.
 *
 * @param {string} state — 'live' or 'expired'
 * @returns {Object[]}  — raw product objects from the API
 */
async function fetchProducts(state) {
    let products   = [];
    let nextMarker = '';

    do {
        const query = {
            contract_types: 'call_options,put_options',
            states:         state,
            page_size:      2000,
        };
        if (nextMarker) {
            if (state === 'expired') query.after  = nextMarker;
            else                     query.before = nextMarker;
        }

        let data;
        try {
            data = await apiFetch('/v2/products', query);
        } catch (err) {
            logger.error('fetcher', `fetchProducts failed for state=${state}`, err);
            break;
        }

        products   = products.concat(data.result || []);
        nextMarker = state === 'expired' ? data.meta?.after : data.meta?.before;

    } while (nextMarker);

    return products;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function parseResolutionToSeconds(res) {
    const map = {
        '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
        '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600,
        '12h': 43200, '1d': 86400, '1w': 604800,
    };
    if (!map[res]) throw new Error(`Unknown resolution: ${res}`);
    return map[res];
}

// IST is UTC+5:30. Kept as a constant so every timestamp helper agrees.
const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;

/**
 * Format unix seconds as an IST datetime string: 'YYYY-MM-DDTHH:MM:SS+0530'.
 *
 * TIMEZONE-INDEPENDENT BY CONSTRUCTION.
 * The original (inherited from utils.getFormattedDateTimeString) read LOCAL
 * clock fields — getFullYear, getHours and so on — while hardcoding the '+0530'
 * suffix. On a machine set to IST that happens to be right; anywhere else it
 * silently produces a timestamp whose label disagrees with its value, shifting
 * every candle by the offset and corrupting slot assignment and DTE filtering.
 *
 * The fix: shift the instant by the IST offset and read UTC fields. getUTC* is
 * unaffected by the host timezone, so the result is identical whether the process
 * runs under IST, UTC, or anything else — and no TZ environment variable is needed.
 */
function formatTs(t) {
    const ist = new Date(t * 1000 + IST_OFFSET_MS);
    const pad = n => String(n).padStart(2, '0');
    return `${ist.getUTCFullYear()}-${pad(ist.getUTCMonth() + 1)}-${pad(ist.getUTCDate())}` +
           `T${pad(ist.getUTCHours())}:${pad(ist.getUTCMinutes())}:${pad(ist.getUTCSeconds())}+0530`;
}

function dateToUnix(dateStr) {
    return Math.floor(new Date(dateStr).getTime() / 1000);
}

module.exports = { apiFetch, fetchCandles, fetchProducts, formatTs, dateToUnix, delay, IST_OFFSET_MS };
