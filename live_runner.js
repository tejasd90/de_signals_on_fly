// live_runner.js
// ─────────────────────────────────────────────────────────────────────────────
// The single live process for FUTURE expiries. Run: node live_runner.js
//
// Absorbs what main.js used to do. Both were fetching the same live candles and
// running the same signals, so keeping them separate doubled the API cost for
// one set of results. Now one pass produces both outputs:
//
//   data/signals/{id}/{spot}/{dur}/{expiry}.json   the historical format, so
//                                                  serve_signals sees live
//                                                  expiries alongside settled
//   data/live/{spot}/{expiry}.json                 the live snapshot: recent
//                                                  signals plus both indicators
//
// Candles are fetched into memory, used, and discarded — nothing is persisted
// except a compact snapshot per (spot, expiry). A live expiry's candles are
// still forming, so storing them would only ever serve stale data.
//
// SCHEDULING
// Expiries are not processed round-robin. The weighted scheduler is reused from
// the historical pipeline: weight accumulates as 1/ceil(daysToExpiry), so the
// nearest expiry comes up far more often. That matches how fast each one
// actually changes — a 7-DTE contract on 5m candles moves constantly, while a
// 60-DTE contract on 4h candles barely shifts between passes, and polling both
// equally would spend most of the rate limit on the one that needs it least.
//
// OUTPUT
//   data/live/{spot}/{expiry}.json
//     { updatedAt, spot, expiry, hoursToExpiry, spotPrice,
//       signals:    [ recent signals across all registered signals ],
//       emaSpread:  { duration -> recent series },
//       volatility: { duration -> [ per-strike rows ] } }
//
// Each pass overwrites its own file, so the snapshot is always current rather
// than an ever-growing log.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs        = require('fs');
const path      = require('path');
const cfg       = require('./config');
const logger    = require('./logger');
const api       = require('./api');
const instr     = require('./instruments');
const grouper   = require('./grouper');
const expiryMod = require('./expiry');
const spotStore = require('./spot_store');
const indicators = require('./indicators');
const Scheduler = require('./scheduler');
const processor = require('./processor');

const LIVE_DIR = path.join(cfg.DATA_BASE_DIR, 'live');

// ─── Concurrency ──────────────────────────────────────────────────────────────

async function runWithConcurrency(tasks, limit) {
    const results = [];
    let i = 0;
    async function worker() {
        while (i < tasks.length) { const k = i++; results[k] = await tasks[k](); }
    }
    await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, worker));
    return results;
}

// ─── Snapshot IO ──────────────────────────────────────────────────────────────

function snapshotPath(spot, expiry) {
    return path.join(LIVE_DIR, spot, `${expiry}.json`);
}

function writeSnapshot(spot, expiry, payload) {
    const p = snapshotPath(spot, expiry);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(payload));
        fs.renameSync(tmp, p);         // atomic: the viewer may be reading
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        logger.error('live', `writeSnapshot failed: ${p}`, err);
    }
}

/** Drop snapshots for expiries that have settled. */
function pruneSettled() {
    if (!fs.existsSync(LIVE_DIR)) return;
    for (const spot of fs.readdirSync(LIVE_DIR)) {
        const dir = path.join(LIVE_DIR, spot);
        if (!fs.statSync(dir).isDirectory()) continue;
        for (const f of fs.readdirSync(dir)) {
            const exp = f.replace(/\.json$/, '');
            if (expiryMod.isExpired(spot, exp)) {
                try { fs.unlinkSync(path.join(dir, f)); } catch (_) {}
                logger.log('live', `Pruned settled snapshot ${spot}/${exp}`);
            }
        }
    }
}

// ─── One pass over one (spot, expiry) ─────────────────────────────────────────

async function processLiveExpiry(spot, expiry) {
    if (expiryMod.isExpired(spot, expiry)) return { skipped: 'settled' };

    const activeDurations = processor.getActiveDurations(spot, expiry);
    if (activeDurations.length === 0) return { skipped: 'no_durations' };

    const instruments = instr.loadInstruments(spot, expiry);
    const symbols     = Object.keys(instruments).filter(s => s !== '-');
    if (symbols.length === 0) return { skipped: 'no_instruments' };

    const fetchPlan = processor.buildFetchPlan(activeDurations);

    // Fetch every instrument into memory. Bounded concurrency: the live loop
    // shares one rate limit with any backfill that happens to be running.
    const tasks = symbols.map(sym => async () => {
        try {
            return { symbol: sym, byDuration: await processor.fetchAndDeriveDurations(sym, spot, expiry, fetchPlan) };
        } catch (err) {
            logger.error('live', `fetch failed ${sym}`, err);
            return { symbol: sym, byDuration: new Map() };
        }
    });
    const fetched = await runWithConcurrency(tasks, cfg.MAX_CONCURRENT_INSTRUMENT_FETCHES);

    const candlesBySymbol = new Map();
    for (const { symbol, byDuration } of fetched) {
        if (byDuration && byDuration.size) candlesBySymbol.set(symbol, byDuration);
    }
    if (candlesBySymbol.size === 0) return { skipped: 'no_candles' };

    // ── Spot: latest price and EMA spread per duration ──
    const spotPriceNow = latestSpotPrice(spot);
    const emaByDur = {};
    for (const dur of activeDurations) {
        const idx = spotStore.spotIndexFor(spot, dur);
        if (!idx || idx.size === 0) continue;
        const series = idx.values();      // already ascending by time
        const spread = indicators.emaSpread(series)
            .filter(r => r.spreadPct !== null)
            .slice(-cfg.LIVE_SERIES_POINTS);
        if (spread.length) emaByDur[dur] = spread;
    }

    // ── Options: volatility heatmap, EVERY strike including ITM ──
    const volByDur = {};
    for (const dur of activeDurations) {
        const rows = [];
        for (const [symbol, durMap] of candlesBySymbol) {
            const candles = durMap.get(dur);
            if (!candles || candles.length < Math.max(...cfg.VOLATILITY_WINDOWS) + 1) continue;

            const last   = indicators.priceVolatility(candles).slice(-1)[0];
            const parsed = instr.parseSymbol(symbol);
            rows.push({
                symbol,
                type:   parsed.type,
                strike: parsed.strike,
                close:  last.close,
                vol5:   last.vol5,  band5:  last.band5,
                vol10:  last.vol10, band10: last.band10,
                // Moneyness relative to live spot, so the viewer can mark ATM
                // and separate ITM from OTM without recomputing it.
                otm: spotPriceNow
                    ? (parsed.type === 'C' ? parsed.strike > spotPriceNow : parsed.strike < spotPriceNow)
                    : null,
            });
        }
        if (rows.length) {
            rows.sort((a, b) => a.strike - b.strike);
            volByDur[dur] = rows;
        }
    }

    // ── Signals ──
    // One call does both jobs: it writes the historical-format files (which is
    // what main.js existed for) and hands back the computed signals for the
    // snapshot. Computing them separately for the tape would run every signal
    // twice over identical candles.
    //
    // It also fills in universeMaxRatio, which the previous inline version in
    // this file did not — so the live tape now carries it too.
    const { written, bySignal } =
        processor.runSignalsOverCandles(spot, expiry, activeDurations, candlesBySymbol);

    const cutoff = Date.now() - cfg.LIVE_SIGNAL_WINDOW_HOURS * 3600 * 1000;
    const liveSignals = [];

    for (const [signalId, byDuration] of bySignal) {
        for (const [dur, instrSignals] of byDuration) {
            for (const [symbol, sigs] of instrSignals) {
                const parsed = instr.parseSymbol(symbol);
                for (const sg of sigs) {
                    if (new Date(sg.dtstring).getTime() < cutoff) continue;
                    liveSignals.push({
                        signal: signalId, duration: dur, symbol,
                        type: parsed.type, strike: parsed.strike,
                        dtstring: sg.dtstring, close: sg.close,
                        signalValue: sg.signalValue,
                        state: sg.signalState, ratio: sg.signalRatio,
                        univRatio:  sg.universeRatio  ?? null,
                        univSymbol: sg.universeSymbol ?? null,
                        distancePct: sg.distancePct ?? null,
                    });
                }
            }
        }
    }

    // Newest first: on a live board the most recent signal is the actionable one.
    liveSignals.sort((a, b) => (a.dtstring < b.dtstring ? 1 : -1));

    writeSnapshot(spot, expiry, {
        updatedAt:     new Date().toISOString(),
        spot, expiry,
        hoursToExpiry: Math.round(expiryMod.hoursToExpiry(spot, expiry) * 10) / 10,
        spotPrice:     spotPriceNow,
        durations:     activeDurations,
        instruments:   candlesBySymbol.size,
        signals:       liveSignals.slice(0, cfg.LIVE_MAX_SIGNALS),
        emaSpread:     emaByDur,
        volatility:    volByDur,
    });

    return { signals: liveSignals.length, instruments: candlesBySymbol.size, written };
}

/** Most recent stored spot close, from the finest available series. */
function latestSpotPrice(spot) {
    for (const dur of [5, 15, 30, 60]) {
        const idx = spotStore.spotIndexFor(spot, dur);
        const last = idx && idx.size ? idx.last() : null;
        if (last) return last.close;
    }
    return null;
}

// ─── Main loop ────────────────────────────────────────────────────────────────

async function main() {
    console.log('');
    console.log('live_runner — FUTURE expiries only');
    console.log(`Log directory : ${logger.sessionDir()}`);
    console.log(`Snapshots     : ${LIVE_DIR}/{spot}/{expiry}.json`);
    console.log('');

    try {
        await instr.fetchAndStoreInstruments('live');
    } catch (err) {
        logger.error('live', 'Instrument fetch failed at startup', err);
    }

    for (const spot of instr.getSpots()) {
        if (!spotStore.hasSpotCandles(spot)) {
            console.log(`  WARNING ${spot}: no spot candles. OTM signals and the EMA`);
            console.log(`          indicator will be skipped. Run:`);
            console.log(`            node backfill.js --spot-candles --spot ${spot}`);
        }
    }

    const scheduler = new Scheduler();
    let iteration = 0;

    while (true) {
        iteration++;

        // Weighted, not round-robin: the nearest expiry surfaces most often.
        const { future } = scheduler.next();
        if (!future) {
            console.log(`[${new Date().toISOString()}] No live expiries. Waiting 60s.`);
            await api.delay(60000);
            continue;
        }

        for (const spot of future.spots) {
            const t0 = Date.now();
            try {
                // Spot moves continuously, so refresh it before reading EMAs.
                await spotStore.fetchAllSpotCandles(spot);

                const res = await processLiveExpiry(spot, future.expiryDate);
                const secs = ((Date.now() - t0) / 1000).toFixed(1);

                console.log(`[${new Date().toISOString()}] #${iteration} ${spot}/${future.expiryDate} ` +
                    (res.skipped ? `skipped (${res.skipped})`
                                 : `${res.signals} signals, ${res.instruments} instruments, ` +
                      `${res.written} files, ${secs}s`));
            } catch (err) {
                logger.error('live', `processLiveExpiry failed ${spot}/${future.expiryDate}`, err);
                console.error(`  ${spot}: ERROR ${err.message}`);
            }
        }

        if (iteration % 20 === 0) {
            pruneSettled();
            try { await instr.fetchAndStoreInstruments('live'); }
            catch (err) { logger.error('live', 'Instrument refresh failed', err); }
        }

        await api.delay(cfg.LIVE_LOOP_DELAY_MS);
    }
}

if (require.main === module) {
    main().catch(err => {
        console.error('Fatal:', err);
        logger.error('live', 'Fatal error in live_runner', err);
        process.exit(1);
    });
}

module.exports = { processLiveExpiry, snapshotPath, LIVE_DIR };
