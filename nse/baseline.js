// nse/baseline.js
// ─────────────────────────────────────────────────────────────────────────────
// What ORDINARY traded bars did, next to what signal bars did, cell by cell.
// For every index chain, timeframe and contract, each traded bar is put in a cell
//   timeframe | call/put | days to expiry | distance out of the money | option price
// and counted, with how many later reached 10x / 25x / 50x / 100x (later max high ÷ this
// bar's close, same measure as signals_run.js) and the sum of hold-to-expiry value
// (settlement value ÷ this close; settlement = intrinsic value at the index close of expiry day, from
// the index history, because a contract that stops trading keeps a stale last price in the filled
// series). Bars where a signal fired are counted again per signal.
// 'separate' view only. Output: <out>/<expiry>.json  { NAME: { cell: { a:[...], s:{signal:[...]} } } }
//   counts array = [n, n10, n25, n50, n100, sumXEnd]
//
//   node baseline.js --grouped F:\nse\grouped --signals F:\nse\signals --spot F:\nse\spot --out F:\nse\baseline [--expiries a,b] [--force]
// ─────────────────────────────────────────────────────────────────────────────
'use strict';
const fs = require('fs');
const path = require('path');
const rd = require('./read');

const DURS = ['5', '10', '15', '25', '60', '75', '125', '1d', '1w'];
const INDEX = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX'];
const bucket = (v, edges) => { let b = edges[0]; for (const e of edges) if (v >= e) b = e; return b; };
const TTE = [0, 1, 2, 3, 5, 8, 15, 31], MNY = [0, 0.5, 1, 2, 3, 5, 8], PX = [0, 1, 2, 5, 10, 20, 50, 100];
const dayNo = d => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10)) / 86400000;

function cellOf(dur, type, ts, expiry, strike, spot, entry) {
    const tte = bucket(dayNo(expiry) - dayNo(ts), TTE);
    const otm = (type === 'C' ? strike - spot : spot - strike) / spot * 100;
    const mny = otm < 0 ? 'itm' : bucket(otm, MNY);
    return `${dur}|${type}|${tte}|${mny}|${bucket(entry, PX)}`;
}
function add(arr, x, xEnd) { arr[0]++; if (x >= 10) arr[1]++; if (x >= 25) arr[2]++; if (x >= 50) arr[3]++; if (x >= 100) arr[4]++; arr[5] += xEnd; }

function runChain(expiryDir, expiry, name, sigFile, settle) {
    const fired = new Map();                     // sym|dur|ts -> Set(signal)
    if (fs.existsSync(sigFile)) for (const f of JSON.parse(fs.readFileSync(sigFile, 'utf8'))) {
        if (f.view !== 'separate') continue;
        const k = `${f.sym}|${f.dur}|${f.ts}`; let s = fired.get(k); if (!s) fired.set(k, s = new Set()); s.add(f.signal);
    }
    const chain = rd.listChain(expiryDir, name).map(k => Object.assign(k, { data: rd.loadContract(k.file) }));
    const cells = {};
    for (const dur of DURS) {
        const ks = chain.map(k => ({ sym: k.sym, type: k.type, strike: k.strike, candles: rd.toCandles(k.data.c[dur] || [], 'separate') })).filter(k => k.candles.length > 4);
        if (!ks.length) continue;
        const spotByTs = rd.syntheticSpot(ks);
        for (const k of ks) {
            const c = k.candles, n = c.length, last = Math.max(0, k.type === 'C' ? settle - k.strike : k.strike - settle);
            let peak = 0;
            for (let i = n - 2; i >= 0; i--) {
                if (c[i + 1].high > peak) peak = c[i + 1].high;
                const entry = c[i].close;
                if (!(c[i].volume > 0) || !(entry > 0)) continue;
                const sp = spotByTs.get(c[i].dtstring);
                if (!sp) continue;
                const key = cellOf(dur, k.type, c[i].dtstring, expiry, k.strike, sp.close, entry);
                const cell = cells[key] || (cells[key] = { a: [0, 0, 0, 0, 0, 0], s: {} });
                const x = peak / entry, xEnd = last / entry;
                add(cell.a, x, xEnd);
                const f = fired.get(`${k.sym}|${dur}|${c[i].dtstring}`);
                if (f) for (const id of f) add(cell.s[id] || (cell.s[id] = [0, 0, 0, 0, 0, 0]), x, xEnd);
            }
        }
    }
    for (const k in cells) { cells[k].a[5] = +cells[k].a[5].toFixed(3); for (const id in cells[k].s) cells[k].s[id][5] = +cells[k].s[id][5].toFixed(3); }
    return cells;
}

function main() {
    const a = process.argv.slice(2);
    const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
    const grouped = opt('grouped'), signals = opt('signals'), out = opt('out'), spotDir = opt('spot');
    if (!grouped || !signals || !out || !spotDir) { console.log('usage: node baseline.js --grouped <dir> --signals <dir> --spot <dir> --out <dir> [--expiries a,b] [--force]'); process.exit(1); }
    const daily = {};                            // name -> Map(day -> index close)
    const settleOf = (name, e) => {
        if (!daily[name]) { daily[name] = new Map(); const f = path.join(spotDir, name + '.json.gz'); if (fs.existsSync(f)) for (const r of rd.loadContract(f).c['1d']) daily[name].set(r[0].slice(0, 10), r[4]); }
        return daily[name].get(e);
    };
    fs.mkdirSync(out, { recursive: true });
    const list = opt('expiries') ? opt('expiries').split(',') : fs.readdirSync(grouped).filter(d => fs.existsSync(path.join(grouped, d, '_report.json'))).sort();
    for (const e of list) {
        const of = path.join(out, e + '.json');
        if (!a.includes('--force') && fs.existsSync(of)) continue;
        const t0 = Date.now(), res = {};
        const dir = path.join(grouped, e);
        for (const name of rd.underlyings(dir).filter(n => INDEX.includes(n))) {
            const st = settleOf(name, e);
            if (st === undefined) { console.log(`${e} ${name}: no index close for the expiry day, skipped`); continue; }
            res[name] = runChain(dir, e, name, path.join(signals, e, name + '.json'), st);
        }
        fs.writeFileSync(of, JSON.stringify(res));
        console.log(`${e}: ${Object.keys(res).join(',')} ${((Date.now() - t0) / 1000).toFixed(1)}s`);
    }
}
if (require.main === module) main();
module.exports = { cellOf, TTE, MNY, PX };
