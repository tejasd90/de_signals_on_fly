// nse/stock_option_moves.js
// ─────────────────────────────────────────────────────────────────────────────
// For every monthly expiry: how far did each F&O stock's options run?
// Per contract, the best multiple over its whole life = the largest (later high ÷ earlier close),
// where the earlier bar traded and closed at Rs MIN_ENTRY or more, and the later bar traded.
// Hourly bars cover the whole life; 15-minute bars (kept for the last 8 sessions) are added.
// Per stock and expiry, for calls and puts separately: the best contract and how many contracts reached
// 5x / 10x / 25x / 100x; plus the stock's own move inside the series, from its future.
//
//   node stock_option_moves.js --grouped F:\nse\grouped --out F:\nse\stock_moves [--expiries a,b] [--min-entry 1] [--force]
// Writes <out>/<expiry>.json: [{ name, C: {n, best, sym, strike, from, to, entry, peak, n5, n10, n25, n100}, P: {...}, open, close, chg, range, days }]
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
    const all = fs.readdirSync(grouped).filter(d => fs.existsSync(path.join(grouped, d, '_report.json'))).sort();
    const list = opt('expiries') ? opt('expiries').split(',') : all;
    let prevMonthly = null;
    for (const e of all) {
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
        const prev = prevMonthly; prevMonthly = e;
        const of = path.join(out, e + '.json');
        if (!list.includes(e) || (!a.includes('--force') && fs.existsSync(of))) continue;
        const res = [];
        for (const [name, ks] of byName) {
            const side = () => ({ n: 0, best: 0, n5: 0, n10: 0, n25: 0, n100: 0 });
            const r = { name, C: side(), P: side() };
            let fut = null;
            for (const k of ks) {
                let d; try { d = rd.loadContract(k.file); } catch (err) { continue; }
                if (k.type === 'F') { fut = d.c['1d'] || null; continue; }
                const s = r[k.type]; s.n++;
                let b = bestRun(d.c['60'] || []); const b15 = bestRun(d.c['15'] || []);
                if (b15 && (!b || b15.x > b.x)) b = b15;
                if (!b) continue;
                if (b.x >= 5) s.n5++; if (b.x >= 10) s.n10++; if (b.x >= 25) s.n25++; if (b.x >= 100) s.n100++;
                if (b.x > s.best) Object.assign(s, { best: +b.x.toFixed(1), sym: k.sym, strike: k.strike, from: b.from.slice(0, 16), to: b.to.slice(0, 16), entry: b.entry, peak: b.peak });
            }
            if (fut) {                              // the stock's own path inside this series (after the previous monthly expiry)
                const m = fut.filter(x => x[0].slice(0, 10) <= e && (!prev || x[0].slice(0, 10) > prev));
                if (m.length) {
                    let hi = 0, lo = Infinity; for (const x of m) { if (x[2] > hi) hi = x[2]; if (x[3] < lo) lo = x[3]; }
                    Object.assign(r, { open: m[0][1], close: m[m.length - 1][4], chg: +((m[m.length - 1][4] / m[0][1] - 1) * 100).toFixed(1), range: +((hi / lo - 1) * 100).toFixed(1), days: m.length });
                }
            }
            res.push(r);
        }
        fs.writeFileSync(of, JSON.stringify(res));
        const top = res.slice().sort((x, y) => Math.max(y.C.best, y.P.best) - Math.max(x.C.best, x.P.best)).slice(0, 3);
        console.log(`${e}: ${res.length} stocks, top ${top.map(x => x.name + ' ' + Math.max(x.C.best, x.P.best) + 'x').join(', ')} | ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
    console.log('DONE');
}
main();
