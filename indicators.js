// indicators.js
// ─────────────────────────────────────────────────────────────────────────────
// Two continuous readings that sit alongside the signals. Neither fires — they
// describe how prices are moving so a signal can be read in context.
//
//   emaSpread          on SPOT. How tightly the 20/50/100/200 EMAs are bunched,
//                      as a percentage of price. Convergence marks a market
//                      that has gone nowhere across every lookback at once —
//                      the compression that precedes a directional move.
//
//   priceVolatility    on OPTIONS. The same body-distance measure otm_wall uses,
//                      but inverted: low is interesting, not high. Divided by
//                      price rather than multiplied, so a low reading at a HIGH
//                      price means premium is holding rather than decaying.
//
// Both are pure functions over candle arrays. Nothing is stored.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const cfg = require('./config');

// ─── Spot: EMA spread ─────────────────────────────────────────────────────────

/**
 * Exponential moving average series. Seeded with the SMA of the first `period`
 * closes, which is the conventional start and avoids the long warm-up bias of
 * seeding from a single value.
 * Entries before the seed are null rather than 0, so "no value yet" cannot be
 * mistaken for "value is zero".
 */
function ema(candles, period) {
    const out = new Array(candles.length).fill(null);
    if (candles.length < period) return out;

    let sum = 0;
    for (let i = 0; i < period; i++) sum += candles[i].close;
    out[period - 1] = sum / period;

    const k = 2 / (period + 1);
    for (let i = period; i < candles.length; i++) {
        out[i] = candles[i].close * k + out[i - 1] * (1 - k);
    }
    return out;
}

/**
 * EMA spread as a percentage of close, per candle.
 *
 *     spread% = (max(EMAs) − min(EMAs)) / close × 100
 *
 * Small means every lookback agrees on price — the market has gone nowhere on
 * all horizons simultaneously. This is the same reading Bollinger width or MACD
 * convergence gestures at, kept in raw form rather than wrapped in an indicator.
 *
 * Bands are logarithmic (1%, 0.1%, 0.01%, 0.001%) because convergence matters
 * across orders of magnitude: 0.05% and 0.005% are very different states, and a
 * linear scale would put both in the same bucket.
 *
 * @returns {Object[]} one entry per candle:
 *   { dtstring, close, emas: {20,50,100,200}, spreadPct, band }
 *   band: 0 = >1% (wide) … 4 = <0.001% (extremely tight); null before warm-up
 */
function emaSpread(candles, periods = cfg.EMA_PERIODS) {
    const series = {};
    for (const p of periods) series[p] = ema(candles, p);

    return candles.map((c, i) => {
        const vals = periods.map(p => series[p][i]).filter(v => v !== null);

        // Every EMA must exist, or the spread is measured over fewer lookbacks
        // than intended and reads artificially tight.
        if (vals.length < periods.length || !(c.close > 0)) {
            return { dtstring: c.dtstring, close: c.close, emas: null, spreadPct: null, band: null };
        }

        const spreadPct = (Math.max(...vals) - Math.min(...vals)) / c.close * 100;
        const emas = {};
        periods.forEach((p, k) => { emas[p] = round(vals[k], 4); });

        return {
            dtstring: c.dtstring,
            close:    c.close,
            emas,
            spreadPct: round(spreadPct, 6),
            band:      bandOf(spreadPct, cfg.EMA_SPREAD_BANDS),
        };
    });
}

// ─── Options: price volatility ────────────────────────────────────────────────

/**
 * Body-distance volatility over the previous N candles, normalised by price.
 *
 *     dist  = Σ |OCmax(i) − OCmax(p)| + |OCmin(i) − OCmin(p)|   over N predecessors
 *     vol   = dist / (open × close)
 *
 * Same `dist` as otm_wall, read the opposite way. otm_wall wants dist LARGE and
 * multiplies by price; here dist should be SMALL and price divides.
 *
 * Dividing rather than multiplying is the whole point: it makes a quiet
 * expensive option score lower than a quiet cheap one. A near-worthless option
 * sitting still is just decayed, whereas a well-priced option sitting still is
 * premium being HELD — nobody is selling it down — which is what precedes a
 * breakout.
 *
 * No log10 here. otm_wall needs logs to compress values spanning many orders of
 * magnitude; this lives in a narrow band near zero where logs would only
 * obscure the differences that matter.
 *
 * @returns {Object[]} one per candle: { dtstring, close, vol5, vol10, band5, band10 }
 */
function priceVolatility(candles, windows = cfg.VOLATILITY_WINDOWS) {
    const maxW = Math.max(...windows);

    return candles.map((c, i) => {
        const out = { dtstring: c.dtstring, close: c.close };

        for (const w of windows) {
            if (i < w || !(c.open > 0) || !(c.close > 0)) {
                out[`vol${w}`]  = null;
                out[`band${w}`] = null;
                continue;
            }

            const curMax = Math.max(c.open, c.close);
            const curMin = Math.min(c.open, c.close);

            let dist = 0;
            for (let k = 1; k <= w; k++) {
                const p = candles[i - k];
                dist += Math.abs(curMax - Math.max(p.open, p.close))
                      + Math.abs(curMin - Math.min(p.open, p.close));
            }

            const vol = dist / (c.open * c.close);
            out[`vol${w}`]  = round(vol, 6);
            out[`band${w}`] = bandOf(vol, cfg.VOLATILITY_BANDS);
        }
        return out;
    });
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Index of the MOST SPECIFIC band containing the value — the one with the
 * smallest `max` that the value still falls under.
 *
 * Order-independent, deliberately. EMA_SPREAD_BANDS runs widest-first and
 * VOLATILITY_BANDS tightest-first, and a naive first-match scan silently gets
 * one of them backwards: a perfectly flat market scored band 0 ("wide") because
 * 0 is less than Infinity, which is the first entry. Picking the smallest
 * satisfied bound is correct for either ordering.
 */
function bandOf(value, bands) {
    let bestIdx = -1;
    let bestMax = Infinity;

    for (let i = 0; i < bands.length; i++) {
        const m = bands[i].max;
        if (value < m && m <= bestMax) { bestMax = m; bestIdx = i; }
    }

    if (bestIdx >= 0) return bestIdx;

    // Above every finite bound: the band whose max is largest.
    let maxIdx = 0;
    for (let i = 1; i < bands.length; i++) {
        if (bands[i].max > bands[maxIdx].max) maxIdx = i;
    }
    return maxIdx;
}

function round(n, dp) {
    const f = Math.pow(10, dp);
    return Math.round(n * f) / f;
}

module.exports = { ema, emaSpread, priceVolatility, bandOf };
