// backfill.js
// ─────────────────────────────────────────────────────────────────────────────
// Standalone backfill of PAST expiries only. Designed to be run as several
// non-overlapping processes in parallel, each owning a slice of the calendar.
//
// WHY THIS EXISTS
// main.js deliberately throttles past backfill (MAX_PAST_EXPIRIES_PER_ITERATION)
// so the live expiry keeps getting fresh signals. That is right for steady-state
// operation but makes a cold historical backfill very slow. This script does the
// opposite: it ignores live expiries entirely and works through history as fast
// as the rate limit allows.
//
// WHY PARALLEL IS SAFE HERE
// Each (spot, expiry) writes only to paths that contain both the spot and the
// expiry date:
//     data/signals/red_squeeze/{spot}/{duration}/{expiry}.json
//     data/markers/past_complete/{spot}/{expiry}
// Give two workers disjoint date ranges and they can never touch the same file.
// The one shared resource is the exchange rate limit — see the warning below.
//
// USAGE
//   node backfill.js --from 2025-01-01 --to 2025-06-30
//   node backfill.js --from 2025-01-01 --to 2025-06-30 --spot BTC
//   node backfill.js --from 2025-07-01 --to 2025-12-31 --label H2
//   node backfill.js --list                       (show what would run, fetch nothing)
//   node backfill.js --from ... --to ... --force  (redo already-complete expiries)
//
// PARALLEL EXAMPLE (two halves of 2025, in separate terminals)
//   TZ=Asia/Kolkata node backfill.js --from 2025-01-01 --to 2025-06-30 --label H1
//   TZ=Asia/Kolkata node backfill.js --from 2025-07-01 --to 2025-12-31 --label H2
//
// RATE LIMIT WARNING
// Every worker shares one exchange rate limit. Running N workers multiplies the
// request rate by N. Either raise API_CALL_DELAY_MS to roughly N times its
// single-worker value, or pass --delay to override it for this process only.
// With the default 150ms, two workers means ~13 req/sec combined, which is
// likely over the unauthenticated ceiling. --delay 300 with 2 workers keeps the
// combined rate the same as one worker at 150ms.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

// ─── CLI parsing (must happen before requiring config-dependent modules) ──────

function parseArgs(argv) {
    const args = {};
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (!a.startsWith('--')) continue;
        const key = a.slice(2);
        const next = argv[i + 1];
        if (next === undefined || next.startsWith('--')) {
            args[key] = true;               // flag
        } else {
            args[key] = next;               // value
            i++;
        }
    }
    return args;
}

const args = parseArgs(process.argv.slice(2));

if (args.help) {
    console.log(`
backfill.js — process PAST expiries only, in a date slice

  --from   YYYY-MM-DD   start of expiry range (inclusive)
  --to     YYYY-MM-DD   end of expiry range (inclusive)
  --spot   SYMBOL       restrict to one spot (default: all)
  --label  TEXT         label for the log directory (e.g. H1, H2)
  --delay  MS           override API_CALL_DELAY_MS for this process
  --list                print the work plan and exit
  --help                this message

SPOT CANDLES
  --spot-candles   fetch/refresh spot candles only, then exit. Required once
                   before any OTM signal can run: moneyness cannot be judged
                   without spot. Cheap — one extra instrument per spot.
                   Honours --from, and extends BACKWARDS past what is stored:
                     node backfill.js --spot-candles --from 2024-01-01

PHASES (default: both)
  --candles-only   phase 1 only: fetch candles and store them. API bound.
  --signals-only   phase 2 only: recompute signals from stored candles.
                   Zero API calls. Use after changing any signal parameter.

FORCING
  --force-candles  refetch candles even if already stored (rarely needed)
  --force-signals  recompute signals even if already computed
  --force          both of the above

TYPICAL USE
  # once, before any OTM signal: spot candles
  node backfill.js --spot-candles

  # one-off: pull history down (slow, API bound)
  node backfill.js --from 2025-01-01 --to 2025-06-30 --candles-only

  # after changing MIN_SEQ_LENGTH / THRESHOLD / signalFn (fast, no API)
  node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only --force-signals

Parallel example:
  TZ=Asia/Kolkata node backfill.js --from 2025-01-01 --to 2025-06-30 --label H1 --delay 300
  TZ=Asia/Kolkata node backfill.js --from 2025-07-01 --to 2025-12-31 --label H2 --delay 300
`);
    process.exit(0);
}

// Label the log directory before logger.js is loaded, so parallel workers
// get separate log dirs instead of interleaving into one.
if (args.label) process.env.WORKER_LABEL = String(args.label);

const cfg = require('./config');

// --delay overrides the configured rate limit for this process only.
// Done by mutating the loaded config object before anything reads it.
if (args.delay) {
    const d = parseInt(args.delay, 10);
    if (!Number.isNaN(d) && d >= 0) cfg.API_CALL_DELAY_MS = d;
}

const logger    = require('./logger');
const instr     = require('./instruments');
const expiryMod = require('./expiry');
const processor = require('./processor');
const writer      = require('./writer');
const candleStore = require('./candle_store');
const spotStore   = require('./spot_store');

// ─── Work plan ────────────────────────────────────────────────────────────────

/**
 * Build the list of (spot, expiryDate) pairs this worker owns.
 * Only past expiries within [from, to] are included.
 */
function buildPlan({ from, to, spotFilter, phase, forceCandles, forceSignals }) {
    const spots = spotFilter
        ? [spotFilter.toUpperCase()]
        : instr.getSpots();

    const plan           = [];
    const skipped        = [];
    const missingCandles = [];

    for (const spot of spots) {
        for (const expiryDate of instr.getExpiries(spot)) {
            if (from && expiryDate < from) continue;
            if (to   && expiryDate > to)   continue;

            // Past only. Uses the per-spot settlement time, so a spot that
            // settles earlier in the day is classified correctly.
            if (!expiryMod.isExpired(spot, expiryDate)) continue;

            // Which completion marker gates this pair depends on the phase.
            // 'both' is only fully done when candles AND signals are done.
            const candlesDone = candleStore.isCandlesComplete(spot, expiryDate);
            const signalsDone = writer.isSignalsComplete(spot, expiryDate);

            let done;
            if (phase === 'candles')      done = candlesDone && !forceCandles;
            else if (phase === 'signals') done = signalsDone && !forceSignals;
            else                          done = candlesDone && signalsDone
                                                 && !forceCandles && !forceSignals;

            if (done) {
                skipped.push({ spot, expiryDate });
                continue;
            }

            // Phase 2 cannot run without stored candles.
            if (phase === 'signals' && !candlesDone) {
                missingCandles.push({ spot, expiryDate });
                continue;
            }

            plan.push({ spot, expiryDate });
        }
    }

    // Newest first: recent expiries are usually the ones you care about.
    plan.sort((a, b) => (a.expiryDate < b.expiryDate ? 1 : -1));

    return { plan, skipped, missingCandles };
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
    const from       = args.from || null;
    const to         = args.to   || null;
    const spotFilter = args.spot || null;

    // Spot candles are continuous, not per-expiry, so this phase ignores the
    // date range entirely and just brings each spot's series up to date.
    if (args['spot-candles']) {
        const spots = spotFilter ? [spotFilter.toUpperCase()] : instr.getSpots();
        console.log(`Fetching spot candles for: ${spots.join(', ') || '(none)'}`);
        if (from) {
            console.log(`  reaching back to ${from} (extends whatever is already stored)`);
        } else {
            console.log(`  default reach-back: ${cfg.SPOT_HISTORY_DAYS} days. ` +
                        `Pass --from to go further.`);
        }
        for (const sp of spots) {
            const res = await spotStore.fetchAllSpotCandles(sp, {
                force:    !!args['force-candles'],
                fromDate: from,           // --from now applies to spot too
            });
            const summary = Object.entries(res)
                .map(([d, r]) => `${d}m:${r.skipped || r.error || (r.stored + ' stored')}`)
                .join('  ');
            console.log(`  ${sp}  ${summary}`);
        }
        console.log('\nDone. OTM signals can now run.');
        return;
    }

    const candlesOnly  = !!args['candles-only'];
    const signalsOnly  = !!args['signals-only'];
    const forceAll     = !!args.force;
    const forceCandles = forceAll || !!args['force-candles'];
    const forceSignals = forceAll || !!args['force-signals'];

    if (candlesOnly && signalsOnly) {
        console.error('--candles-only and --signals-only are mutually exclusive.');
        process.exit(1);
    }

    const phase = candlesOnly ? 'candles' : signalsOnly ? 'signals' : 'both';

    console.log('');
    console.log('backfill.js — past expiries only');
    console.log(`  range   : ${from || '(no lower bound)'} .. ${to || '(no upper bound)'}`);
    console.log(`  spot    : ${spotFilter || 'all'}`);
    console.log(`  phase   : ${phase}` +
        (phase === 'signals' ? '  (no API calls)' : ''));
    if (phase !== 'signals') console.log(`  delay   : ${cfg.API_CALL_DELAY_MS}ms per API call`);
    if (forceCandles || forceSignals) {
        console.log(`  force   : candles=${forceCandles} signals=${forceSignals}`);
    }
    if (!args.list) console.log(`  logs    : ${logger.sessionDir()}`);
    console.log('');

    if (instr.getSpots().length === 0) {
        console.error('No instruments on disk. Run main.js once first, or:');
        console.error("  node -e \"require('./instruments').fetchAndStoreInstruments('expired')\"");
        process.exit(1);
    }

    const { plan, skipped, missingCandles } =
        buildPlan({ from, to, spotFilter, phase, forceCandles, forceSignals });

    if (missingCandles.length) {
        console.log(`Cannot run signals — candles not stored: ${missingCandles.length} pairs`);
        console.log('  run with --candles-only first for those expiries');
    }

    if (skipped.length) {
        console.log(`Already complete, skipping: ${skipped.length} (use --force to redo)`);
    }

    if (plan.length === 0) {
        console.log('Nothing to do in this range.');
        return;
    }

    // Group for a readable plan summary
    const bySpot = {};
    for (const { spot, expiryDate } of plan) {
        (bySpot[spot] = bySpot[spot] || []).push(expiryDate);
    }
    console.log(`Work plan: ${plan.length} (spot, expiry) pairs`);
    for (const [spot, expiries] of Object.entries(bySpot)) {
        console.log(`  ${spot.padEnd(6)} ${expiries.length} expiries  ` +
                    `[${expiries[expiries.length - 1]} .. ${expiries[0]}]`);
    }
    console.log('');

    if (args.list) {
        console.log('--list given, exiting without fetching.');
        return;
    }

    logger.log('scheduler',
        `backfill start: ${plan.length} pairs, range=${from}..${to}, spot=${spotFilter || 'all'}`);

    const started = Date.now();
    let done = 0, failed = 0, skippedClaimed = 0, incomplete = 0;

    for (const { spot, expiryDate } of plan) {
        const t0 = Date.now();
        const n  = done + failed + skippedClaimed + 1;
        let lastDetail = '';

        process.stdout.write(
            `[${String(n).padStart(4)}/${plan.length}] ${spot} ${expiryDate} ... `);

        // Exclusive claim: if main.js or a sibling backfill worker is already
        // on this expiry, move on rather than duplicating the fetch.
        if (!writer.claimPastExpiry(spot, expiryDate)) {
            skippedClaimed++;
            console.log('skipped (claimed by another process)');
            continue;
        }
        currentClaim = { spot, expiryDate };

        try {
            if (phase === 'candles') {
                const r = await processor.fetchAndStorePastCandles(
                    spot, expiryDate, { force: forceCandles });
                if (r.incomplete) {
                    incomplete++;
                    lastDetail = `INCOMPLETE ${r.succeeded}/${r.instruments} ok, ` +
                                 `${r.failed} failed — re-run to resume`;
                } else {
                    lastDetail = r.skipped ? r.skipped : `${r.candles} candles, ${r.mb} MB`;
                }
            } else if (phase === 'signals') {
                // Pure CPU — no await needed, no API calls made.
                const r = processor.computeSignalsFromDisk(spot, expiryDate);
                lastDetail = r.skipped ? r.skipped : `${r.written} duration files`;
            } else {
                const r = await processor.processPastExpiry(
                    spot, expiryDate, { forceCandles, forceSignals });
                const sig = r.signals;
                lastDetail = (sig && sig.written !== undefined)
                    ? `${sig.written} duration files`
                    : (typeof sig === 'string' ? sig : (r.skipped || 'ok'));
            }
            done++;

            const secs    = ((Date.now() - t0) / 1000).toFixed(1);
            const elapsed = (Date.now() - started) / 1000;
            const rate    = (done + failed) / elapsed;                 // pairs per second
            const remain  = plan.length - (done + failed + skippedClaimed);
            const etaMin  = rate > 0 ? (remain / rate / 60).toFixed(1) : '?';

            console.log(`${lastDetail} — ${secs}s   (eta ${etaMin} min)`);
        } catch (err) {
            failed++;
            console.log(`FAILED: ${err.message}`);
            logger.error('scheduler', `backfill failed: ${spot}/${expiryDate}`, err);
        } finally {
            writer.releasePastExpiry(spot, expiryDate);
            currentClaim = null;
        }
    }

    const totalMin = ((Date.now() - started) / 60000).toFixed(1);
    console.log('');
    console.log(`Backfill finished: ${done} processed, ${failed} errored, ` +
                `${skippedClaimed} skipped (claimed), ${totalMin} min total`);

    if (incomplete > 0) {
        console.log('');
        console.log(`  ${incomplete} expiries are INCOMPLETE — some instruments could not`);
        console.log('  be fetched after all retries. They were NOT marked complete.');
        console.log('  Re-run the same command; it resumes from where it stopped.');
    }
    if (failed > 0) {
        console.log(`  ${failed} expiries errored outright — see the log for details.`);
    }
    logger.log('scheduler',
        `backfill finished: done=${done} failed=${failed} incomplete=${incomplete} ` +
        `skippedClaimed=${skippedClaimed} minutes=${totalMin}`);
}

// Ctrl-C / kill: release the claim on the expiry currently being processed so a
// re-run is not blocked waiting for the 30-minute stale-claim TTL. Per-instrument
// progress is already flushed to disk after every instrument, so the run resumes
// from the last completed instrument regardless.
let currentClaim = null;
for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, () => {
        console.log(`\n${sig} received — releasing claim and exiting.`);
        if (currentClaim) {
            try { writer.releasePastExpiry(currentClaim.spot, currentClaim.expiryDate); } catch (_) {}
        }
        console.log('Progress is saved. Re-run the same command to resume.');
        process.exit(130);
    });
}

main().catch(err => {
    console.error('Fatal error:', err);
    logger.error('scheduler', 'Fatal error in backfill.js', err);
    process.exit(1);
});
