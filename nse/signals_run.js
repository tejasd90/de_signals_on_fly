// nse/signals_run.js
// ─────────────────────────────────────────────────────────────────────────────
// Runs the CRYPTO signal modules (../signals/*.js, unchanged) on grouped NSE/BSE option
// candles, in both views of the 15:30-15:40 minutes, plus the close-to-close variant of
// otm_red_squeeze. Writes every firing with what the option did afterwards.
//
//   node signals_run.js --grouped F:\nse\grouped --out F:\nse\signals --expiries 2026-11-17[,...] [--names NIFTY,SENSEX]
//
// Outcome per firing, measured on the same timeframe's bars after the trigger bar:
//   x    = highest later high / trigger close        xEnd = last close / trigger close
// Spot for the out-of-the-money test comes from the chain (read.syntheticSpot).
// Not applied here: the processor's merging of strikes, opposite-direction filter and
// minimum time to expiry. Every raw firing is kept.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';
process.env.DE_QUIET_LOGS = process.env.DE_QUIET_LOGS || '1';
process.env.DE_NO_LOG_DIR = process.env.DE_NO_LOG_DIR || '1';

const fs = require('fs');
const path = require('path');
const rd = require('./read');

const MODULES = [require('../signals/otm_red_squeeze'), require('../signals/green_stairs'), require('../signals/otm_wall')];
const SQUEEZE = MODULES[0];
const DURS = ['5', '10', '15', '25', '60', '75', '125', '1d', '1w'];
const INDEX = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX'];

function runChain(expiryDir, expiry, name) {
    const chain = rd.listChain(expiryDir, name).map(k => Object.assign(k, { data: rd.loadContract(k.file) }));
    const fired = [];
    for (const dur of DURS) for (const view of ['separate', 'merged']) {
        const ks = chain.map(k => ({ sym: k.sym, type: k.type, strike: k.strike, candles: rd.toCandles(k.data.c[dur] || [], view) })).filter(k => k.candles.length > 4);
        if (!ks.length) continue;
        const spotByTs = rd.syntheticSpot(ks);
        for (const k of ks) {
            const inst = { symbol: k.sym, type: k.type, strike: k.strike };
            const runs = MODULES.map(m => [m.id, m, k.candles]);
            runs.push(['otm_red_squeeze_c2c', SQUEEZE, rd.closeToClose(k.candles)]);
            for (const [id, mod, candles] of runs) {
                let sigs;
                try { sigs = mod.computeSignals(candles, inst, { spotByTs }) || []; } catch (e) { sigs = []; }
                for (const s of sigs) {
                    const i = candles.findIndex(c => c.dtstring === s.dtstring);
                    if (i < 0) continue;
                    let peak = 0, peakTs = null;
                    for (let j = i + 1; j < candles.length; j++) if (candles[j].high > peak) { peak = candles[j].high; peakTs = candles[j].dtstring; }
                    const entry = candles[i].close;
                    const sp = spotByTs.get(s.dtstring);
                    fired.push({ expiry, name, sym: k.sym, type: k.type, strike: k.strike, dur, view, signal: id, ts: s.dtstring,
                        patternStart: s.patternStart, entry, vol: candles[i].volume, spot: sp ? Math.round(sp.close * 100) / 100 : null,
                        signalValue: s.signalValue, seq: s.seqLength, peak, peakTs,
                        x: entry > 0 ? Math.round(peak / entry * 100) / 100 : 0,
                        xEnd: entry > 0 ? Math.round(candles[candles.length - 1].close / entry * 100) / 100 : 0 });
                }
            }
        }
    }
    return fired;
}

function main() {
    const a = process.argv.slice(2);
    const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
    const grouped = opt('grouped'), out = opt('out');
    if (!grouped || !out || !(opt('expiries') || a.includes('--all'))) { console.log('usage: node signals_run.js --grouped <dir> --out <dir> (--expiries a,b | --all) [--names NIFTY,SENSEX] [--force]'); process.exit(1); }
    const names = opt('names') ? opt('names').split(',') : INDEX;
    const list = a.includes('--all') ? fs.readdirSync(grouped).filter(d => fs.existsSync(path.join(grouped, d, '_report.json'))).sort() : opt('expiries').split(',');
    for (const e of list) {
        const dir = path.join(grouped, e);
        if (!a.includes('--force') && a.includes('--all') && fs.existsSync(path.join(out, e, '_done'))) continue;
        for (const name of rd.underlyings(dir).filter(n => names.includes(n))) {
            const t0 = Date.now();
            const fired = runChain(dir, e, name);
            fs.mkdirSync(path.join(out, e), { recursive: true });
            fs.writeFileSync(path.join(out, e, name + '.json'), JSON.stringify(fired));
            const traded = fired.filter(f => f.vol > 0);
            const n = t => traded.filter(f => f.x >= t).length;
            console.log(`${e} ${name}: ${fired.length} firings (${traded.length} on a traded bar) | >=10x ${n(10)} | >=25x ${n(25)} | >=100x ${n(100)} | ${((Date.now() - t0) / 1000).toFixed(1)}s`);
        }
        fs.mkdirSync(path.join(out, e), { recursive: true });
        fs.writeFileSync(path.join(out, e, '_done'), '');
    }
}

if (require.main === module) main();
module.exports = { runChain };
