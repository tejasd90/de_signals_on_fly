// dryrun.js
// ─────────────────────────────────────────────────────────────────────────────
// Runs the REAL pipeline (scheduler -> processor -> grouper -> red_squeeze ->
// merger -> writer -> quality) with ONLY the HTTP layer stubbed.
//
// Everything below api.fetchCandles / api.fetchProducts is genuine production
// code. This validates integration without needing exchange connectivity.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs   = require('fs');
const path = require('path');
const api  = require('./api');
const cfg  = require('./config');

// ─── Deterministic PRNG so runs are reproducible ─────────────────────────────
let _seed = 42;
function rnd() { _seed = (_seed * 1103515245 + 12345) & 0x7fffffff; return _seed / 0x7fffffff; }

// ─── Synthetic option candle generator ───────────────────────────────────────
// Models a realistic OTM option: premium decays toward expiry, with an
// injected red-squeeze-then-explosion in a configurable fraction of instruments.
function genCandles(symbol, resolutionSecs, startS, endS, injectSqueeze) {
    const n = Math.floor((endS - startS) / resolutionSecs);
    if (n <= 0) return [];

    const candles = [];
    let price = 200 + rnd() * 300;           // starting premium
    const decayPerCandle = Math.pow(0.02 / price, 1 / Math.max(n, 1));

    // Where to inject the squeeze (only if requested)
    const squeezeAt = injectSqueeze ? Math.floor(n * (0.55 + rnd() * 0.25)) : -1;
    let inExplosion = 0;

    for (let i = 0; i < n; i++) {
        const t = startS + i * resolutionSecs;
        let open = price, close, high, low;

        if (squeezeAt > 0 && i >= squeezeAt - 6 && i < squeezeAt) {
            // Descending red bodies — the squeeze
            const step = squeezeAt - i;                 // 6,5,4,3,2,1
            const body = Math.max(0.4, price * 0.28 * (step / 6));
            close = Math.max(0.2, open - body);
            high  = open * 1.01;
            low   = close * 0.985;
        } else if (squeezeAt > 0 && i === squeezeAt) {
            // Tiny green trigger
            close = open * 1.02;
            high  = close * 1.01;
            low   = open * 0.995;
            inExplosion = 8;
        } else if (inExplosion > 0) {
            // Explosion upward
            close = open * (1.6 + rnd() * 0.9);
            high  = close * 1.15;
            low   = open * 0.97;
            inExplosion--;
        } else {
            // Normal decay + noise
            const drift = decayPerCandle * (0.97 + rnd() * 0.06);
            close = Math.max(0.05, open * drift);
            high  = Math.max(open, close) * (1 + rnd() * 0.03);
            low   = Math.min(open, close) * (1 - rnd() * 0.03);
        }

        candles.push({
            time: t,
            dtstring: api.formatTs(t),
            open:  +open.toFixed(2),
            high:  +high.toFixed(2),
            low:   +Math.max(0.01, low).toFixed(2),
            close: +close.toFixed(2),
            volume: Math.floor(rnd() * 500) + 10,
        });
        price = close;
    }
    return candles;
}

// ─── Stub the HTTP layer ─────────────────────────────────────────────────────
let apiCallCount = 0;
const resSecs = { '3m':180,'5m':300,'15m':900,'30m':1800,'1h':3600,
                  '2h':7200,'4h':14400,'12h':43200,'1d':86400 };

api.fetchCandles = async function (fullSymbol, resolution, start, end) {
    apiCallCount++;
    const symbol = fullSymbol.replace('MARK:', '');
    // ~35% of instruments carry a squeeze pattern
    const inject = (symbol.split('-')[2] | 0) % 3 === 0;
    return genCandles(symbol, resSecs[resolution], start, end, inject);
};

api.fetchProducts = async function () { return []; };   // instruments come from disk

// ─── Seed instrument files on disk (what fetch_instruments would write) ──────
function seedInstruments() {
    const now      = Math.floor(Date.now() / 1000);
    const pastExp   = new Date((now - 6 * 86400) * 1000).toISOString().substring(0, 10);
    const futureExp = new Date((now + 9 * 86400) * 1000).toISOString().substring(0, 10);

    const expiryMod = require('./expiry');
    for (const [expiry, tag] of [[pastExp,'past'], [futureExp,'future']]) {
        for (const [spot, base] of [['BTC',90000], ['XAUT',3000]]) {
            const obj = {};
            for (let k = 0; k < 5; k++) {
                const strike = base + k * (base/40);
                obj[`C-${spot}-${strike}-${expiry.replace(/-/g,'').substring(2)}`] = 1000 + k;
                obj[`P-${spot}-${strike}-${expiry.replace(/-/g,'').substring(2)}`] = 2000 + k;
            }
            const dir = path.join(cfg.INSTRUMENTS_BASE_DIR, spot);
            fs.mkdirSync(dir, { recursive: true });
            fs.writeFileSync(path.join(dir, `${expiry}.json`), JSON.stringify(obj));
        }
        // XAUT settles 4h earlier than BTC — as the API would report
        expiryMod.recordSettlementTime('XAUT', expiry, `${expiry}T08:00:00Z`);
        expiryMod.recordSettlementTime('BTC',  expiry, `${expiry}T12:00:00Z`);
    }
    return { pastExp, futureExp };
}

// ─── Run ─────────────────────────────────────────────────────────────────────
(async () => {
    const processor = require('./processor');
    const writer    = require('./writer');
    const Scheduler = require('./scheduler');

    const { pastExp, futureExp } = seedInstruments();
    console.log(`Seeded instruments: past=${pastExp}  future=${futureExp}\n`);

    // Scheduler picks the priority expiry, exactly as main.js does
    const sched = new Scheduler();
    const { future, past } = sched.next();
    console.log('Scheduler -> future expiry:', future ? future.expiryDate : '(none)');
    console.log('Scheduler -> past expiries :', past.map(p => p.expiryDate).join(', ') || '(none)');
    console.log('');

    console.log('Active durations (future):', processor.getActiveDurations('BTC', futureExp).join(','));
    console.log('Active durations (past)  :', processor.getActiveDurations('BTC', pastExp).join(','));
    console.log('');

    const expiryMod2 = require('./expiry');
    console.log('Settlement times in use:', JSON.stringify(expiryMod2.knownSettlementTimes()));
    console.log('');

    for (const spot of ['BTC','XAUT']) {
        console.log(`── FUTURE expiry, spot=${spot} (settles ${expiryMod2.expiryTimestamp(spot, futureExp)}) ──`);
        console.log(`   active durations: ${processor.getActiveDurations(spot, futureExp).join(',')}`);
        let t0 = Date.now(), c0 = apiCallCount;
        await processor.processFutureExpiry(spot, futureExp);
        console.log(`   done in ${((Date.now()-t0)/1000).toFixed(1)}s, ${apiCallCount-c0} API calls\n`);
    }

    for (const spot of ['BTC','XAUT']) {
        console.log(`── PAST expiry, spot=${spot} ──`);
        let t0 = Date.now(), c0 = apiCallCount;
        await processor.processPastExpiry(spot, pastExp);
        console.log(`   done in ${((Date.now()-t0)/1000).toFixed(1)}s, ${apiCallCount-c0} API calls`);
        console.log(`   past-complete marker: ${writer.isSignalsComplete(spot, pastExp)}\n`);
    }

    console.log(`TOTAL API calls: ${apiCallCount}`);
    fs.writeFileSync('dryrun_expiries.json', JSON.stringify({ pastExp, futureExp }));
})();
