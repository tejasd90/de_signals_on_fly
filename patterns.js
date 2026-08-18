// patterns.js
// ─────────────────────────────────────────────────────────────────────────────
// STAGE 1 of the query pipeline: extract every structural pattern match, with no
// tuning filter applied, and store one row per instrument — unmerged.
//
//   node patterns.js --from 2025-01-01 --to 2025-12-31
//   node patterns.js --signal otm_wall --spot BTC --force
//
// STRUCTURAL vs TUNING
// A structural parameter defines what the pattern IS — MIN_SEQ_LENGTH, the
// requirement that reds shrink, that the trigger is green. Without it there is
// no pattern to store. A tuning parameter filters patterns already found:
// RED_SQUEEZE_THRESHOLD, OTM_SIGNAL_THRESHOLD, WALL_JUMP_THRESHOLD.
//
// Structural is applied here. Tuning is NOT — it moves to query time, so a
// threshold can be explored in both directions without regenerating anything.
// That is the entire point: raising a threshold was always possible by filtering
// stored data, but lowering it needed a full re-run.
//
// WHY UNMERGED
// Merging is lossy: it keeps maxima and discards per-instrument ratio1, ratio2,
// seqLength and the rest — exactly the fields a query wants. So rows are stored
// per instrument and merging, if wanted, happens after filtering. Note this
// changes results: filter-then-merge and merge-then-filter give different
// ranges, and the numbers here will not reconcile with the old pipeline's.
//
// Output: data/patterns/{signalId}/{spot}/{duration}/{expiry}.json
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs        = require('fs');
const path      = require('path');
const cfg       = require('./config');
const logger    = require('./logger');
const instr     = require('./instruments');
const grouper   = require('./grouper');
const expiryMod = require('./expiry');
const registry  = require('./signal_registry');
const candleStore = require('./candle_store');
const spotStore   = require('./spot_store');
const processor   = require('./processor');

const OUT_DIR = path.join(cfg.DATA_BASE_DIR, 'patterns');

// ─── CLI ──────────────────────────────────────────────────────────────────────

const args  = process.argv.slice(2);
const argOf = k => {
    const i = args.indexOf('--' + k);
    return i >= 0 && args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : null;
};

if (args.includes('--help')) {
    console.log(`
patterns.js — STAGE 1: every structural pattern match, no tuning filter

  --from YYYY-MM-DD  start of expiry range
  --to   YYYY-MM-DD  end of expiry range
  --spot SYMBOL      restrict to one spot
  --signal ID        restrict to one signal
  --force            recompute expiries already done
  --list             show the work plan and exit

Then: node serve_query.js
`);
    process.exit(0);
}

const FROM   = argOf('from');
const TO     = argOf('to');
const SPOTF  = argOf('spot');
const SIGF   = argOf('signal');
const FORCE  = args.includes('--force');
const LIST   = args.includes('--list');

// ─── Row shape ────────────────────────────────────────────────────────────────

/**
 * Flatten one signal object into a query row.
 *
 * Deliberately over-stores. A field absent here cannot be queried later without
 * re-running this stage over candles, which is the expensive step — whereas disk
 * at these volumes is cheap. Anything a signal computes is worth keeping.
 */
function toRow(sig, ctx) {
    const { signalId, spot, expiry, duration, symbol, type, strike, spotPrice } = ctx;

    const tteHours = (expiryMod.expiryMillis(spot, expiry) -
                      new Date(sig.patternStart || sig.dtstring).getTime()) / 3600000;

    return {
        signal: signalId, spot, expiry, duration, symbol, type, strike,

        entryTs:     sig.dtstring,
        patternStart: sig.patternStart || sig.dtstring,
        entryPrice:  sig.close,
        tteHours:    Math.round(tteHours * 100) / 100,
        spotPrice:   sig.spotAtStart ?? spotPrice ?? null,
        distancePct: sig.distancePct ?? null,
        otm:         sig.distancePct == null ? null : sig.distancePct > 0,

        seqLength:   sig.seqLength   ?? null,
        patternHigh: sig.patternHigh ?? null,
        patternLow:  sig.patternLow  ?? null,

        // red_squeeze family
        ratio1:      sig.ratio1       ?? null,
        ratio2:      sig.ratio2       ?? null,
        firstBody:   sig.firstRedBody ?? null,
        lastBody:    sig.lastRedBody  ?? null,
        triggerBody: sig.greenBody    ?? null,

        // otm_* cheapness
        avgPrice:    sig.avgPrice ?? null,
        cheapness:   (sig.avgPrice && sig.spotAtStart) ? sig.spotAtStart / sig.avgPrice : null,

        // otm_wall
        dist:        sig.dist      ?? null,
        logValue:    sig.value     ?? null,
        logJump:     sig.signalValue ?? null,

        // green_stairs
        equalSteps:  sig.equalSteps ?? null,

        signalValue: sig.signalValue,

        // Outcomes — banned in filters, available for the success expression.
        ratio:       sig.signalRatio,
        univRatio:   sig.universeRatio ?? sig.signalRatio,
        univSymbol:  sig.universeSymbol ?? null,
        state:       sig.signalState,
        brokeOut:    sig.brokeOut ?? null,
        holdCandles: sig.holdCandles ?? null,
    };
}

// ─── Per-expiry extraction ────────────────────────────────────────────────────

function outPath(signalId, spot, duration, expiry) {
    return path.join(OUT_DIR, signalId, spot, String(duration), `${expiry}.json`);
}

function write(signalId, spot, duration, expiry, rows) {
    const p = outPath(signalId, spot, duration, expiry);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tmp = `${p}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmp, JSON.stringify(rows));
        fs.renameSync(tmp, p);
    } catch (err) {
        try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch (_) {}
        throw err;
    }
}

function extractExpiry(spot, expiry, signalDefs) {
    const durations = candleStore.storedDurations(spot, expiry);
    if (!durations.length) return { skipped: 'no_candles' };

    let written = 0, rowCount = 0;

    for (const duration of durations) {
        const symbols = candleStore.storedSymbols(spot, expiry, duration);
        if (!symbols.length) continue;

        const spotIdx = spotStore.spotIndexFor(spot, duration);

        // Candles are read once and reused across every signal, since reading
        // dominates the cost here.
        const candlesBySymbol = new Map();
        for (const sym of symbols) {
            const c = candleStore.readCandles(spot, expiry, duration, sym);
            if (c.length >= 3) candlesBySymbol.set(sym, c);
        }
        if (!candlesBySymbol.size) continue;

        // Built once per duration and shared by every signal, since it scans
        // the whole chain and is the expensive part of this stage.
        const universeIndex = cfg.UNIVERSE_MAX_ENABLED
            ? processor.buildUniverseIndex(
                new Map([...candlesBySymbol].map(([k, v]) => [k, new Map([[duration, v]])])),
                duration)
            : null;

        for (const def of signalDefs) {
            if (def.requiresSpot && (!spotIdx || spotIdx.size === 0)) continue;

            const rows = [];
            for (const [symbol, candles] of candlesBySymbol) {
                const parsed = instr.parseSymbol(symbol);
                const instrument = { symbol, type: parsed.type, strike: parsed.strike };

                let sigs = [];
                try {
                    // minSignalValue 0 keeps every structural match.
                    sigs = def.computeSignals(
                        candles, instrument,
                        { spotByTs: spotIdx || new Map(), duration, expiryDate: expiry, spot },
                        { minSignalValue: 0 }
                    ) || [];
                } catch (err) {
                    logger.error('scheduler', `${def.id} threw on ${symbol} ${duration}m`, err);
                    continue;
                }

                // Same cutoff as the signal pipeline, so patterns and signals
                // stay comparable.
                sigs = processor.applyFiringCutoff(sigs, spot, expiry);
                sigs = processor.applyOppositeDirectionFilter(
                    sigs, parsed.type, spotIdx || new Map());

                // universeMaxRatio: the best move available on any eligible
                // strike at the signal's instant. Independent of merging — it is
                // a scan across the chain, not an aggregation, which is why an
                // earlier version that omitted this left univRatio equal to ratio.
                if (universeIndex) {
                    for (const s of sigs) {
                        const best = processor.universeMaxAt(
                            universeIndex, s.dtstring, parsed.type, parsed.strike, {
                                otmOnly:    def.otmOnly,
                                spotCandle: spotIdx ? spotIdx.get(s.dtstring) : null,
                            });
                        s.universeRatio  = best.ratio;
                        s.universeSymbol = best.symbol;
                    }
                }

                const sp = spotIdx ? spotIdx.get(candles[0].dtstring) : null;
                for (const s of sigs) {
                    rows.push(toRow(s, {
                        signalId: def.id, spot, expiry, duration,
                        symbol, type: parsed.type, strike: parsed.strike,
                        spotPrice: sp ? sp.close : null,
                    }));
                }
            }

            write(def.id, spot, duration, expiry, rows);
            written++; rowCount += rows.length;
        }
    }

    return { written, rowCount };
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
    const signalDefs = registry.activeSignals(SIGF ? [SIGF] : null);
    if (!signalDefs.length) {
        console.log(`No signal matches --signal ${SIGF}. Available: ` +
            registry.SIGNALS.map(s => s.id).join(', '));
        return;
    }

    console.log('');
    console.log('patterns — STAGE 1: structural matches, no tuning filter');
    console.log(`  signals : ${signalDefs.map(s => s.id).join(', ')}`);
    console.log(`  range   : ${FROM || '(any)'} .. ${TO || '(any)'}`);
    console.log('');

    const spots = SPOTF ? [SPOTF.toUpperCase()] : instr.getSpots();
    const plan = [];
    for (const spot of spots) {
        for (const expiry of instr.getExpiries(spot)) {
            if (FROM && expiry < FROM) continue;
            if (TO   && expiry > TO)   continue;
            if (!expiryMod.isExpired(spot, expiry)) continue;
            plan.push({ spot, expiry });
        }
    }

    console.log(`Work plan: ${plan.length} (spot, expiry) pairs`);
    if (LIST) { console.log('--list given, exiting.'); return; }
    console.log('');

    let done = 0, skipped = 0, totalRows = 0;
    const started = Date.now();

    for (const { spot, expiry } of plan) {
        // One marker file stands for the whole expiry across every signal.
        const marker = path.join(OUT_DIR, '_done', spot, expiry);
        if (!FORCE && fs.existsSync(marker)) { skipped++; continue; }

        const res = extractExpiry(spot, expiry, signalDefs);
        if (res.skipped) { skipped++; continue; }

        fs.mkdirSync(path.dirname(marker), { recursive: true });
        fs.writeFileSync(marker, new Date().toISOString());

        done++; totalRows += res.rowCount;
        console.log(`  ${spot} ${expiry}  ${String(res.written).padStart(3)} files  ` +
                    `${String(res.rowCount).padStart(7)} rows`);
    }

    const mins = ((Date.now() - started) / 60000).toFixed(1);
    console.log('');
    console.log(`Done: ${done} expiries, ${skipped} skipped, ${totalRows.toLocaleString()} rows, ${mins} min.`);
    console.log('View: node serve_query.js');
    logger.log('scheduler', `patterns: ${done} expiries, ${totalRows} rows`);
}

if (require.main === module) main();

module.exports = { extractExpiry, toRow, outPath, OUT_DIR };
