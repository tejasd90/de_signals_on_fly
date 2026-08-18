// multibaggers.js
// ─────────────────────────────────────────────────────────────────────────────
// Ground truth: every multibagger that EXISTED, independent of any signal.
//
//   node multibaggers.js
//   node multibaggers.js --spot BTC --from 2025-01-01 --to 2025-12-31
//   node multibaggers.js --min 10          only instruments reaching 10x+
//
// WHY THIS IS SEPARATE FROM quality.js
// quality.js answers "of the signals I fired, how many paid" — precision. It
// cannot answer "of the moves that were there, how many did I catch" — recall —
// because it only ever sees instruments a signal picked. This scans every stored
// instrument with no signal involved, giving the denominator that makes recall
// computable.
//
// WHAT "BEST TRADE" MEANS HERE
// For each instrument: over every candle as a possible entry, the highest
// subsequent high divided by that entry's close, then the maximum of those.
//
//     peakRatio = max over i of ( max(high[i+1..end]) / close[i] )
//
// This is PERFECT HINDSIGHT — it buys the exact bottom and sells the exact top.
// No strategy can reach it. That is deliberate: it is an upper bound, the
// ceiling against which a real strategy's capture rate is measured. A signal
// catching 20% of this number is doing well; the figure is not meant to be
// achievable.
//
// Computed on the FINEST stored duration, since a coarse candle hides the intra-
// candle bottom and would understate what was available.
//
// Output: data/multibaggers/{spot}/{expiry}.json
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs        = require('fs');
const path      = require('path');
const cfg       = require('./config');
const logger    = require('./logger');
const api       = require('./api');
const instr     = require('./instruments');
const expiryMod = require('./expiry');
const candleStore = require('./candle_store');
const spotStore   = require('./spot_store');

const OUT_DIR = path.join(cfg.DATA_BASE_DIR, 'multibaggers');

// ─── CLI ──────────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const argOf = k => {
    const i = args.indexOf('--' + k);
    return i >= 0 && args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : null;
};

if (args.includes('--help')) {
    console.log(`
multibaggers.js — every multibagger that existed, signal-independent

  --spot SYMBOL     restrict to one spot
  --from YYYY-MM-DD start of expiry range
  --to   YYYY-MM-DD end of expiry range
  --min  N          only report instruments reaching Nx or more (default 2)
  --force           recompute expiries already done
`);
    process.exit(0);
}

const FILTER_SPOT = argOf('spot');
const FROM        = argOf('from');
const TO          = argOf('to');
const MIN_RATIO   = parseFloat(argOf('min') || '2');
const FORCE       = args.includes('--force');

// ─── Core computation ─────────────────────────────────────────────────────────

/**
 * Best trade available on one instrument.
 *
 * Single backward pass carrying the running max high, so this is O(n) rather
 * than the O(n²) the naive "for each entry, scan forward" would cost. At
 * hundreds of instruments times thousands of candles that difference decides
 * whether a full history takes seconds or hours.
 *
 * @returns {Object|null} null when fewer than 2 candles or no positive close
 */
function bestTrade(candles) {
    if (!candles || candles.length < 2) return null;

    let bestRatio = 0, bestEntryIdx = -1, bestPeakIdx = -1;

    // Walk backwards holding (highest high seen so far, where it was).
    let runMax = -Infinity, runMaxIdx = -1;

    for (let i = candles.length - 1; i >= 0; i--) {
        // runMax currently covers candles strictly after i — the sell window.
        if (i < candles.length - 1) {
            const entry = candles[i].close;
            if (entry > 0 && runMax > 0) {
                const ratio = runMax / entry;
                if (ratio > bestRatio) {
                    bestRatio    = ratio;
                    bestEntryIdx = i;
                    bestPeakIdx  = runMaxIdx;
                }
            }
        }
        if (candles[i].high > runMax) { runMax = candles[i].high; runMaxIdx = i; }
    }

    if (bestEntryIdx < 0) return null;

    const e = candles[bestEntryIdx];
    const p = candles[bestPeakIdx];

    return {
        ratio:      Math.round(bestRatio * 100) / 100,
        entryTs:    e.dtstring,
        entryPrice: e.close,
        peakTs:     p.dtstring,
        peakPrice:  p.high,
        holdCandles: bestPeakIdx - bestEntryIdx,
        holdHours:  Math.round((p.time - e.time) / 3600 * 10) / 10,
        firstTs:    candles[0].dtstring,
        candles:    candles.length,
    };
}

/** Finest stored duration for an expiry — the coarser ones hide the true bottom. */
function finestDuration(spot, expiry) {
    const durs = candleStore.storedDurations(spot, expiry);
    return durs.length ? Math.min(...durs) : null;
}

/** One (spot, expiry): best trade for every instrument, plus a summary. */
function computeExpiry(spot, expiry) {
    const duration = finestDuration(spot, expiry);
    if (!duration) return { skipped: 'no_candles' };

    const symbols = candleStore.storedSymbols(spot, expiry, duration);
    if (!symbols.length) return { skipped: 'no_symbols' };

    // Spot at each instrument's entry, so moneyness can be reported. Absent
    // spot is not fatal — the ratio is still valid, only the OTM flag is unknown.
    const spotIdx = spotStore.spotIndexFor(spot, duration);

    const rows = [];
    for (const symbol of symbols) {
        const candles = candleStore.readCandles(spot, expiry, duration, symbol);
        const t = bestTrade(candles);
        if (!t || t.ratio < MIN_RATIO) continue;

        const parsed = instr.parseSymbol(symbol);
        const sp     = spotIdx && spotIdx.size ? spotIdx.get(t.entryTs) : null;

        rows.push({
            symbol,
            type:   parsed.type,
            strike: parsed.strike,
            ...t,
            spotAtEntry: sp ? Math.round(sp.close * 100) / 100 : null,
            otm: sp ? (parsed.type === 'C' ? parsed.strike > sp.close
                                           : parsed.strike < sp.close) : null,
            distancePct: sp && sp.close
                ? Math.round(((parsed.type === 'C' ? 1 : -1) *
                    (parsed.strike - sp.close) / sp.close * 100) * 10) / 10
                : null,
        });
    }

    rows.sort((a, b) => b.ratio - a.ratio);

    const counts = {};
    for (const t of cfg.MULTIBAGGER_THRESHOLDS) {
        counts[`${t}x`] = rows.filter(r => r.ratio >= t).length;
    }

    return {
        spot, expiry, duration,
        instruments: symbols.length,      // all scanned
        qualifying:  rows.length,         // those reaching MIN_RATIO
        counts,
        best: rows[0] || null,
        rows,
        computedAt: new Date().toISOString(),
    };
}

// ─── Storage ──────────────────────────────────────────────────────────────────

function outPath(spot, expiry) {
    return path.join(OUT_DIR, spot, `${expiry}.json`);
}

function write(spot, expiry, payload) {
    const p = outPath(spot, expiry);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(payload));
        fs.renameSync(tmp, p);          // atomic: the viewer may be reading
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        throw err;
    }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
    console.log('');
    console.log('multibaggers — ground truth, signal-independent');
    console.log(`  min ratio : ${MIN_RATIO}x`);
    console.log(`  range     : ${FROM || '(any)'} .. ${TO || '(any)'}`);
    console.log('');
    console.log('  Perfect-hindsight entry: buys the exact bottom, sells the exact top.');
    console.log('  An upper bound, not an achievable target.');
    console.log('');

    const spots = FILTER_SPOT ? [FILTER_SPOT.toUpperCase()] : instr.getSpots();
    if (!spots.length) { console.log('No instruments on disk.'); return; }

    let done = 0, skipped = 0;
    const grand = {};
    for (const t of cfg.MULTIBAGGER_THRESHOLDS) grand[`${t}x`] = 0;

    for (const spot of spots) {
        for (const expiry of instr.getExpiries(spot)) {
            if (FROM && expiry < FROM) continue;
            if (TO   && expiry > TO)   continue;
            if (!expiryMod.isExpired(spot, expiry)) continue;   // settled only

            if (!FORCE && fs.existsSync(outPath(spot, expiry))) { skipped++; continue; }

            const res = computeExpiry(spot, expiry);
            if (res.skipped) { skipped++; continue; }

            write(spot, expiry, res);
            done++;

            for (const k of Object.keys(grand)) grand[k] += res.counts[k] || 0;

            const b = res.best;
            console.log(`  ${spot} ${expiry}  ${String(res.qualifying).padStart(4)} of ` +
                `${String(res.instruments).padStart(4)}  best ` +
                (b ? `${String(b.ratio).padStart(8)}x  ${b.symbol}` : '—'));
        }
    }

    console.log('');
    console.log(`Done: ${done} expiries computed, ${skipped} skipped.`);
    console.log('Instruments reaching:', Object.entries(grand).map(([k, v]) => `${k}=${v}`).join('  '));
    console.log('');
    console.log('View: node serve_multibaggers.js');
    logger.log('scheduler', `multibaggers: ${done} expiries, ${JSON.stringify(grand)}`);
}

if (require.main === module) main();

module.exports = { bestTrade, computeExpiry, outPath, OUT_DIR };
