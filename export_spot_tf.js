// export_spot_tf.js
// ─────────────────────────────────────────────────────────────────────────────
// Writes the spot series for EVERY signal duration to one place, so the python
// feature code can read a signal's OWN timeframe.
//
// WHY THIS EXISTS
// Option candles are grouped to all 16 durations by processor.js. Spot candles
// are only FETCHED at 8 (5/15/30/60/120/240/360/1440), so six of the durations
// signals fire on — 40, 45, 90, 180, 480, 720 — have no spot series at all.
//
// spot_store.spotIndexFor() already derives any duration via grouper.groupCandles.
// Verified identical to the stored series for 30/60/120/240/1440 over three
// months: 8,463 shared timestamps, 8,463 identical OHLC, 0 differing. So this is
// lossless, and using the project's own grouper means no chance of a python
// re-implementation drifting from it.
//
// Written to its own directory rather than into data/spot_candles/, so backfill
// never mistakes a derived series for a fetched one.
//
//   data/spot_grouped/{SPOT}/{duration}.json   [[ts,o,h,l,c], ...]  ascending
// ─────────────────────────────────────────────────────────────────────────────

'use strict';
const fs = require('fs'), path = require('path');
const ss = require('./spot_store');

const DURATIONS = [30, 40, 45, 60, 90, 120, 180, 240, 360, 480, 720, 1440];

// WEEKLY IS BUILT BY HAND, NOT BY THE GROUPER.
// grouper.sourceFor(10080) returns 1440, but groupCandles cannot actually build
// it — asking for 10080 yields 991 bars at DAILY spacing with 7 different week
// offsets, i.e. silently not weekly at all. 10080 is not in DURATION_TIMES and
// getKeyDuration has no bucket for it.
//
// ANCHOR: Monday 00:00 UTC = Monday 05:30 IST.
// Two reasons. (1) It matches Delta's own chart, so a weekly line drawn by eye
// on the exchange is the same line the model fits — which matters because the
// point of weekly here is to see multi-month trend lines the way a trader does.
// (2) Our daily bars start at 00:00 UTC, so a Monday-anchored week is EXACTLY
// seven daily bars. Anchoring at 17:30 IST instead would put the week 12h out of
// phase with the day and 1 weekly would no longer equal 7 dailies.
const WEEKLY = 10080;

function buildWeekly(daily) {
    // bucket by ISO week: the Monday 00:00 UTC at or before each daily bar
    const byWeek = new Map();
    for (const c of daily) {
        const d = new Date(c.time * 1000);
        const dow = (d.getUTCDay() + 6) % 7;                 // Mon=0 .. Sun=6
        const monday = Math.floor(c.time / 86400) * 86400 - dow * 86400;
        if (!byWeek.has(monday)) byWeek.set(monday, []);
        byWeek.get(monday).push(c);
    }
    return [...byWeek.entries()].sort((a, b) => a[0] - b[0]).map(([t, bars]) => [
        t,
        bars[0].open,
        Math.max(...bars.map(b => b.high)),
        Math.min(...bars.map(b => b.low)),
        bars[bars.length - 1].close,
    ]);
}
const OUT = path.join('data', 'spot_grouped');

for (const spot of ['BTC', 'ETH', 'XAUT']) {
    if (!ss.hasSpotCandles(spot)) { console.log(`  ${spot}: no spot candles`); continue; }
    fs.mkdirSync(path.join(OUT, spot), { recursive: true });
    // weekly first, from the stored daily series
    const daily = ss.spotIndexFor(spot, 1440).all();
    if (daily.length) {
        const wk = buildWeekly(daily);
        fs.writeFileSync(path.join(OUT, spot, `${WEEKLY}.json`), JSON.stringify(wk));
        console.log(`  ${spot} ${String(WEEKLY).padStart(5)}m: ${String(wk.length).padStart(6)} bars (weekly, Mon 00:00 UTC)`);
    }
    for (const d of DURATIONS) {
        const rows = ss.spotIndexFor(spot, d).all()
            .map(c => [c.time, c.open, c.high, c.low, c.close]);
        if (!rows.length) { console.log(`  ${spot} ${d}m: empty`); continue; }
        fs.writeFileSync(path.join(OUT, spot, `${d}.json`), JSON.stringify(rows));
        console.log(`  ${spot} ${String(d).padStart(4)}m: ${String(rows.length).padStart(6)} bars`);
    }
}
console.log('\nwrote ' + OUT);
