// trades.js
// ─────────────────────────────────────────────────────────────────────────────
// Every tradeable move that existed, found by recursive partitioning, then
// merged across instruments into market events. Past expiries only.
//
//   node trades.js --from 2025-01-01 --to 2025-12-31
//   node trades.js --spot BTC --min 5
//   node trades.js --from 2025-06-01 --to 2025-06-30 --force
//
// THE ALGORITHM
// On one instrument, within a window:
//   1. Find the highest high.
//   2. Find the lowest low STRICTLY BEFORE that candle. Strictly, because within
//      a single candle there is no way to know whether the low came before or
//      after the high — so a same-candle pair is not a tradeable round trip.
//   3. That pair is a trade. It consumes its own candles and splits what remains
//      into two windows: everything before the low, everything after the high.
//   4. Recurse into both.
//
// The split is INDEPENDENT of the threshold — every trade is recorded and the
// filter is applied at the end. This matters: a window's top-level trade is not
// necessarily its largest. Prices 10, 100, 0.1, 50 give 10x at the top level,
// but the right-hand partition holds a 500x. Filtering during recursion would
// prune the branch containing it.
//
// MERGING
// The same market move shows up on many strikes, each with slightly different
// candle boundaries. Trades whose windows overlap in time are merged into one
// event carrying every contributing instrument, so the output reads as market
// events rather than per-strike duplicates.
//
// Output: data/trades/{spot}/{expiry}/{duration}.json
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs        = require('fs');
const path      = require('path');
const cfg       = require('./config');
const logger    = require('./logger');
const instr     = require('./instruments');
const expiryMod = require('./expiry');
const candleStore = require('./candle_store');
const spotStore   = require('./spot_store');

const OUT_DIR = path.join(cfg.DATA_BASE_DIR, 'trades');

// ─── CLI ──────────────────────────────────────────────────────────────────────

const args  = process.argv.slice(2);
const argOf = k => {
    const i = args.indexOf('--' + k);
    return i >= 0 && args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : null;
};

if (args.includes('--help')) {
    console.log(`
trades.js — every tradeable move, by recursive partitioning

  --from YYYY-MM-DD   start of expiry range
  --to   YYYY-MM-DD   end of expiry range
  --spot SYMBOL       restrict to one spot
  --min  N            minimum ratio for a trade to qualify (default ${cfg.TRADE_MIN_RATIO})
  --force             recompute expiries already done
  --list              show the work plan and exit

View: node serve_trades.js
`);
    process.exit(0);
}

const FROM        = argOf('from');
const TO          = argOf('to');
const FILTER_SPOT = argOf('spot');
const MIN_RATIO   = parseFloat(argOf('min') || String(cfg.TRADE_MIN_RATIO));
const FORCE       = args.includes('--force');
const LIST_ONLY   = args.includes('--list');

// ─── Recursive trade finding ──────────────────────────────────────────────────

/**
 * All trades on one instrument.
 *
 * Iterative with an explicit stack rather than recursive: 5-minute candles over
 * 40 days is ~11,500 bars, and a pathological shape (monotonic decline, where
 * each split shortens the window by one) would recurse deep enough to blow the
 * call stack.
 *
 * @param {Object[]} candles
 * @returns {Object[]} { lowIdx, highIdx, lowTs, highTs, lowPrice, highPrice,
 *                       ratio, holdCandles }
 */
function findTrades(candles) {
    if (!candles || candles.length < 2) return [];

    const out   = [];
    const stack = [[0, candles.length - 1]];

    while (stack.length && out.length < cfg.TRADE_MAX_PER_INSTRUMENT) {
        const [lo, hi] = stack.pop();
        if (hi - lo < 1) continue;                 // need two candles

        // Highest high in this window.
        let highIdx = lo;
        for (let i = lo + 1; i <= hi; i++) {
            if (candles[i].high > candles[highIdx].high) highIdx = i;
        }

        // With the high on the first candle there is nothing before it to buy,
        // so no trade here — but the rest of the window may still hold one.
        if (highIdx === lo) { stack.push([lo + 1, hi]); continue; }

        // Lowest low STRICTLY BEFORE the high candle.
        let lowIdx = lo;
        for (let i = lo + 1; i < highIdx; i++) {
            if (candles[i].low < candles[lowIdx].low) lowIdx = i;
        }

        const lowPrice  = candles[lowIdx].low;
        const highPrice = candles[highIdx].high;

        if (lowPrice > 0 && highPrice > 0) {
            out.push({
                lowIdx, highIdx,
                lowTs:  candles[lowIdx].dtstring,
                highTs: candles[highIdx].dtstring,
                lowPrice, highPrice,
                ratio: Math.round((highPrice / lowPrice) * 100) / 100,
                holdCandles: highIdx - lowIdx,
            });
        }

        // The trade consumes its own candles; the two remaining windows are
        // everything before the low and everything after the high.
        stack.push([lo, lowIdx - 1]);
        stack.push([highIdx + 1, hi]);
    }

    return out;
}

// ─── Merging across instruments ───────────────────────────────────────────────

/**
 * Merge trades whose windows overlap in time.
 *
 * One market move appears on many strikes with slightly different boundaries;
 * merging turns those duplicates into a single event.
 *
 * A span cap guards against chained merging: A overlaps B, B overlaps C, but A
 * and C do not touch, and without a cap the chain can swallow most of an expiry.
 * A merge that would exceed TRADE_MAX_MERGE_SPAN_CANDLES is refused and the
 * trade starts its own event instead.
 *
 * @param {Array} entries  { symbol, trade }
 * @param {number} durationMinutes
 */
function mergeTrades(entries, durationMinutes) {
    const spanCapMs = cfg.TRADE_MAX_MERGE_SPAN_CANDLES * durationMinutes * 60000;

    // The cap limits how far merging may EXTEND a window, not how long a window
    // may be. A single trade can legitimately run for days — a slow grind from
    // the low to the eventual high — and capping absolute span would refuse to
    // merge two near-identical long windows that are plainly the same event.
    // Observed directly: six instruments each with a ~90h window, obviously one
    // move, left as six separate events by an absolute 15h cap.
    const extensionOf = (last, it) =>
        Math.max(0, Math.max(last.endMs, it.endMs) - last.endMs) +
        Math.max(0, last.startMs - it.startMs);

    const items = entries.map(({ symbol, trade }) => ({
        startMs: new Date(trade.lowTs).getTime(),
        endMs:   new Date(trade.highTs).getTime(),
        symbol, trade,
    })).sort((a, b) => a.startMs - b.startMs);

    const events = [];

    for (const it of items) {
        const last = events[events.length - 1];

        const overlaps = last && it.startMs <= last.endMs;

        if (overlaps && extensionOf(last, it) <= spanCapMs) {
            last.endMs = Math.max(last.endMs, it.endMs);
            last.members.push({ symbol: it.symbol, trade: it.trade });
        } else {
            events.push({
                startMs: it.startMs,
                endMs:   it.endMs,
                members: [{ symbol: it.symbol, trade: it.trade }],
            });
        }
    }

    return events.map(ev => {
        // The single best member defines the event's headline ratio, and its
        // symbol is what the viewer bolds.
        let best = ev.members[0];
        for (const m of ev.members) if (m.trade.ratio > best.trade.ratio) best = m;

        const holds = ev.members.map(m => m.trade.holdCandles);

        return {
            startTs: best.trade.lowTs <= ev.members[0].trade.lowTs
                ? new Date(ev.startMs).toISOString() : new Date(ev.startMs).toISOString(),
            startMs: ev.startMs,
            endMs:   ev.endMs,
            maxRatio:    best.trade.ratio,
            maxSymbol:   best.symbol,
            maxLowPrice: best.trade.lowPrice,
            maxHighPrice: best.trade.highPrice,
            count:       ev.members.length,
            holdCandles: Math.round(holds.reduce((a, b) => a + b, 0) / holds.length),
            instruments: ev.members
                .sort((a, b) => b.trade.ratio - a.trade.ratio)
                .map(m => ({
                    symbol: m.symbol,
                    ratio:  m.trade.ratio,
                    lowTs:  m.trade.lowTs,
                    highTs: m.trade.highTs,
                })),
        };
    }).sort((a, b) => b.maxRatio - a.maxRatio);
}

// ─── One (spot, expiry, duration) ─────────────────────────────────────────────

function computeDuration(spot, expiry, duration) {
    const symbols = candleStore.storedSymbols(spot, expiry, duration);
    if (!symbols.length) return null;

    const spotIdx = spotStore.spotIndexFor(spot, duration);

    // Calls and puts are separate universes — a call move and a put move at the
    // same instant are opposite events, so merging them would be meaningless.
    const byType = { C: [], P: [] };
    let scanned = 0, rawTrades = 0;

    for (const symbol of symbols) {
        const parsed = instr.parseSymbol(symbol);
        if (!byType[parsed.type]) continue;

        const candles = candleStore.readCandles(spot, expiry, duration, symbol);
        if (candles.length < 2) continue;
        scanned++;

        for (const t of findTrades(candles)) {
            rawTrades++;
            if (t.ratio < MIN_RATIO) continue;      // filter AFTER the split
            byType[parsed.type].push({ symbol, trade: t });
        }
    }

    const result = { spot, expiry, duration, scanned, rawTrades, minRatio: MIN_RATIO };

    for (const type of ['C', 'P']) {
        const events = mergeTrades(byType[type], duration);

        // Moneyness of the headline instrument, for context in the table.
        for (const ev of events) {
            const sp = spotIdx && spotIdx.size ? spotIdx.get(new Date(ev.startMs).toISOString()) : null;
            const parsed = instr.parseSymbol(ev.maxSymbol);
            ev.strike = parsed.strike;
            if (sp && sp.close) {
                ev.spotAtStart = Math.round(sp.close * 100) / 100;
                ev.distancePct = Math.round(((type === 'C' ? 1 : -1) *
                    (parsed.strike - sp.close) / sp.close * 100) * 10) / 10;
                ev.otm = type === 'C' ? parsed.strike > sp.close : parsed.strike < sp.close;
            }
        }
        result[type] = events;
    }

    result.computedAt = new Date().toISOString();
    return result;
}

// ─── Storage ──────────────────────────────────────────────────────────────────

function outPath(spot, expiry, duration) {
    return path.join(OUT_DIR, spot, expiry, `${duration}.json`);
}

function summaryPath(spot, expiry) {
    return path.join(OUT_DIR, spot, expiry, '_summary.json');
}

/**
 * Tiny per-expiry summary: the best call and put ratio across all durations.
 *
 * The calendar view needs one number per side per expiry. Deriving that by
 * reading every duration file would mean ~16 reads per expiry and ~16,000 for a
 * full history on every page load, which is far too slow. This reduces it to one
 * small read per expiry.
 */
function writeSummary(spot, expiry) {
    const dir = path.join(OUT_DIR, spot, expiry);
    if (!fs.existsSync(dir)) return null;

    const durations = fs.readdirSync(dir)
        .filter(f => f.endsWith('.json') && !f.startsWith('_') && !f.includes('.tmp.'))
        .map(f => parseInt(f.replace('.json', '')))
        .filter(n => !isNaN(n))
        .sort((a, b) => a - b);

    const summary = { expiry, durations, C: 0, P: 0, cCount: 0, pCount: 0 };

    for (const d of durations) {
        let data;
        try { data = JSON.parse(fs.readFileSync(outPath(spot, expiry, d), 'utf8')); }
        catch (_) { continue; }

        for (const type of ['C', 'P']) {
            for (const ev of (data[type] || [])) {
                if (ev.maxRatio > summary[type]) summary[type] = ev.maxRatio;
            }
            summary[type === 'C' ? 'cCount' : 'pCount'] += (data[type] || []).length;
        }
    }

    const p = summaryPath(spot, expiry);
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(summary));
        fs.renameSync(tmp, p);
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
    }
    return summary;
}

function write(spot, expiry, duration, payload) {
    const p = outPath(spot, expiry, duration);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(payload));
        fs.renameSync(tmp, p);           // atomic: the viewer may be reading
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        throw err;
    }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
    console.log('');
    console.log('trades — every tradeable move, recursive partitioning');
    console.log(`  range     : ${FROM || '(any)'} .. ${TO || '(any)'}`);
    console.log(`  min ratio : ${MIN_RATIO}x`);
    console.log(`  merge cap : ${cfg.TRADE_MAX_MERGE_SPAN_CANDLES} candles`);
    console.log('');

    const spots = FILTER_SPOT ? [FILTER_SPOT.toUpperCase()] : instr.getSpots();
    if (!spots.length) { console.log('No instruments on disk.'); return; }

    const plan = [];
    for (const spot of spots) {
        for (const expiry of instr.getExpiries(spot)) {
            if (FROM && expiry < FROM) continue;
            if (TO   && expiry > TO)   continue;
            if (!expiryMod.isExpired(spot, expiry)) continue;   // settled only
            plan.push({ spot, expiry });
        }
    }

    console.log(`Work plan: ${plan.length} (spot, expiry) pairs`);
    if (LIST_ONLY) { console.log('--list given, exiting.'); return; }
    console.log('');

    let done = 0, skipped = 0, totalEvents = 0;

    for (const { spot, expiry } of plan) {
        const durations = candleStore.storedDurations(spot, expiry);
        if (!durations.length) { skipped++; continue; }

        let expiryEvents = 0, wrote = 0;
        for (const duration of durations) {
            if (!FORCE && fs.existsSync(outPath(spot, expiry, duration))) continue;

            const res = computeDuration(spot, expiry, duration);
            if (!res) continue;

            write(spot, expiry, duration, res);
            wrote++;
            expiryEvents += res.C.length + res.P.length;
        }

        if (wrote === 0) { skipped++; continue; }
        writeSummary(spot, expiry);
        done++;
        totalEvents += expiryEvents;
        console.log(`  ${spot} ${expiry}  ${String(wrote).padStart(2)} durations  ` +
                    `${String(expiryEvents).padStart(5)} events`);
    }

    console.log('');
    console.log(`Done: ${done} expiries, ${skipped} skipped, ${totalEvents} merged events.`);
    console.log('View: node serve_trades.js');
    logger.log('scheduler', `trades: ${done} expiries, ${totalEvents} events`);
}

if (require.main === module) main();

module.exports = { findTrades, mergeTrades, computeDuration, outPath, summaryPath, writeSummary, OUT_DIR };
