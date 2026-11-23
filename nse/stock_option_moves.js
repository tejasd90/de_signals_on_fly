// nse/stock_option_moves.js
// ─────────────────────────────────────────────────────────────────────────────
// For every monthly expiry: how far did each F&O stock's options run?
// Per contract, the best multiple over its whole life = the largest (later high ÷ earlier close),
// where the earlier bar traded and closed at Rs MIN_ENTRY or more, and the later bar traded.
// Hourly bars cover the whole life; 15-minute bars (kept for the last 8 sessions) are added.
// Per stock and expiry: the best contract, how many contracts reached 5x / 10x / 25x / 100x,
// and the stock's own move (first to last futures-implied... here: synthetic spot from the chain).
//
//   node stock_option_moves.js --grouped F:\nse\grouped --out F:\nse\stock_moves [--expiries a,b] [--min-entry 1] [--force]
// Writes <out>/<expiry>.json: [{ name, contracts, best, bestSym, bestFrom, bestTo, bestEntry, bestPeak, bestSide, n5, n10, n25, n100, bestCall, bestPut, spot0, spot1, range }]
// ─────────────────────────────────────────────────────────────────────────────
'use strict';
const fs = require('fs');
const path = require('path');
const rd = require('./read');
const INDEX = new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX', 'SENSEX50']);
const a = process.argv.slice(2);
const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
const MIN_ENTRY = +(opt('min-entry') || 1);

function bestRun(rows) {                       // rows [ts,o,h,l,c,v,oi] ascending
    let peak = 0, peakTs = null, best = null;
    for (let i = rows.length - 1; i >= 0; i--) {
        const r = rows[i];
        if (peak > 0 && r[5] > 0 && r[4] >= MIN_ENTRY) { const x = peak / r[4]; if (!best || x > best.x) best = { x, from: r[0], entry: r[4], to: peakTs, peak }; }
        if (r[5] > 0 && r[2] > peak) { peak = r[2]; peakTs = r[0]; }
    }
    return best;
}

function main() {
    const grouped = opt('grouped'), out = opt('out');
    if (!grouped || !out) { console.log('usage: node stock_option_moves.js --grouped <dir> --out <dir> [--expiries a,b] [--min-entry 1] [--force]'); process.exit(1); }
    fs.mkdirSync(out, { recursive: true });
    const list = opt('expiries') ? opt('expiries').split(',') : fs.readdirSync(grouped).filter(d => fs.existsSync(path.join(grouped, d, '_report.json'))).sort();
    for (const e of list) {
        const of = path.join(out, e + '.json');
        if (!a.includes('--force') && fs.existsSync(of)) continue;
        const dir = path.join(grouped, e), t0 = Date.now();
        const byName = new Map();
        for (const f of fs.readdirSync(dir)) {
            if (!f.endsWith('.json.gz')) continue;
            const sym = f.slice(0, f.lastIndexOf('_')), p = rd.parseSymbol(sym);
            if (!p || INDEX.has(p.name)) continue;
            let m = byName.get(p.name); if (!m) byName.set(p.name, m = []);
            m.push({ sym, type: p.type, strike: p.strike, file: path.join(dir, f) });
        }
        if (byName.size < 20) continue;            // weekly expiry: no stock contracts
        const res = [];
        for (const [name, ks] of byName) {
            const r = { name, contracts: 0, best: 0, n5: 0, n10: 0, n25: 0, n100: 0, bestCall: 0, bestPut: 0 };
            let fut = null;
            for (const k of ks) {
                let d; try { d = rd.loadContract(k.file); } catch (err) { continue; }
                if (k.type === 'F') { fut = d.c['1d'] || null; continue; }
                r.contracts++;
                let b = bestRun(d.c['60'] || []); const b15 = bestRun(d.c['15'] || []);
                if (b15 && (!b || b15.x > b.x)) b = b15;
                if (!b) continue;
                if (b.x >= 5) r.n5++; if (b.x >= 10) r.n10++; if (b.x >= 25) r.n25++; if (b.x >= 100) r.n100++;
                if (k.type === 'C' && b.x > r.bestCall) r.bestCall = +b.x.toFixed(1);
                if (k.type === 'P' && b.x > r.bestPut) r.bestPut = +b.x.toFixed(1);
                if (b.x > r.best) Object.assign(r, { best: +b.x.toFixed(1), bestSym: k.sym, bestSide: k.type, bestFrom: b.from, bestTo: b.to, bestEntry: b.entry, bestPeak: b.peak });
            }
            if (fut && fut.length) {                // the stock's own path over the contract month, from its future
                let hi = 0, lo = Infinity; for (const x of fut) { if (x[2] > hi) hi = x[2]; if (x[3] < lo) lo = x[3]; }
                r.spot0 = fut[0][1]; r.spot1 = fut[fut.length - 1][4]; r.range = +((hi / lo - 1) * 100).toFixed(1); r.futDays = fut.length;
            }
            res.push(r);
        }
        res.sort((x, y) => y.best - x.best);
        fs.writeFileSync(of, JSON.stringify(res));
        console.log(`${e}: ${res.length} stocks, top ${res.slice(0, 3).map(x => x.name + ' ' + x.best + 'x').join(', ')} | ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    console.log('DONE');
}
main();
