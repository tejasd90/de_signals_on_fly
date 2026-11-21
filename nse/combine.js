'use strict';
/**
 * Per-day 1-minute files -> one file per contract per expiry, in the layout the file server reads:
 *   <out>/<expiry>/<SYMBOL>_<token>.json   {"data":[[ts,o,h,l,c,volume,oi],...]}  sorted, one row per minute
 *
 * Same output as the old combiner (zerodha_combine_and_find_hz/index.js), with three differences:
 *   - damaged files ({key,value} wrappers, /Date(ms)/, UTF-16) are cleaned by group.js readCandleFile;
 *   - duplicate minutes are dropped;
 *   - rows are kept to the real session close (15:40 from 2026-08-03), the old one cut at 15:30.
 *
 * usage: node combine.js --out <combined dir> --tars <dir of expiry.tar.gz> --tmp <scratch> --marks <dir>
 *                        [--expiries a,b | --from d --to d] [--part i/n] [--force]
 * An expiry with a marker file in --marks is skipped.
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { readCandleFile, listContracts } = require('./group');
const cal = require('./calendar');

function combineExpiry(expiry, dir, outDir) {
    const { map } = listContracts(dir, 'days');
    fs.mkdirSync(outDir, { recursive: true });
    const rep = { expiry, contracts: map.size, written: 0, rows: 0, bytes: 0, cleaned: 0, bad: [] };
    for (const [name, paths] of map) {
        const seen = new Map();
        for (const p of paths) {
            try {
                const r = readCandleFile(p);
                if (r.cleaned) rep.cleaned++;
                for (const row of r.rows) {
                    const day = row[0].slice(0, 10), hm = +row[0].slice(11, 13) * 60 + +row[0].slice(14, 16);
                    if (hm < cal.OPEN_MIN || hm >= cal.closeMin(day)) continue;
                    seen.set(row[0], row);
                }
            } catch (e) { if (rep.bad.length < 50) rep.bad.push(path.relative(dir, p) + ': ' + String(e.message).slice(0, 80)); }
        }
        if (!seen.size) continue;
        const rows = [...seen.values()].sort((a, b) => (a[0] > b[0] ? 1 : a[0] < b[0] ? -1 : 0));
        const s = JSON.stringify({ data: rows });
        fs.writeFileSync(path.join(outDir, name), s);
        rep.written++; rep.rows += rows.length; rep.bytes += s.length;
    }
    return rep;
}

function main() {
    const a = process.argv.slice(2);
    const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
    const out = opt('out'), tars = opt('tars'), tmpRoot = opt('tmp'), marks = opt('marks');
    if (!out || !tars || !tmpRoot || !marks) { console.log('usage: node combine.js --out <dir> --tars <dir> --tmp <dir> --marks <dir> [--expiries a,b | --from d --to d] [--part i/n] [--force]'); process.exit(1); }
    fs.mkdirSync(marks, { recursive: true });
    let list = fs.readdirSync(tars).map(f => (/^(\d{4}-\d{2}-\d{2})\.tar\.gz$/.exec(f) || [])[1]).filter(Boolean).sort();
    if (opt('expiries')) { const w = new Set(opt('expiries').split(',')); list = list.filter(e => w.has(e)); }
    if (opt('from')) list = list.filter(e => e >= opt('from'));
    if (opt('to')) list = list.filter(e => e <= opt('to'));
    if (opt('part')) { const [i, n] = opt('part').split('/').map(Number); list = list.filter((_, k) => k % n === i); }
    const force = a.includes('--force');
    let k = 0;
    for (const e of list) {
        k++;
        const mark = path.join(marks, e);
        if (!force && fs.existsSync(mark)) continue;
        const tmp = path.join(tmpRoot, e + '_c' + process.pid);
        const t0 = Date.now();
        try {
            fs.mkdirSync(tmp, { recursive: true });
            execFileSync('tar', ['-xzf', path.join(tars, e + '.tar.gz'), '-C', tmp], { stdio: ['ignore', 'ignore', 'pipe'] });
            const inner = path.join(tmp, e);
            const r = combineExpiry(e, fs.existsSync(inner) ? inner : tmp, path.join(out, e));
            r.seconds = Math.round((Date.now() - t0) / 1000);
            if (!r.bad.length) fs.writeFileSync(mark, JSON.stringify(r));
            console.log(`${new Date().toISOString().slice(11, 19)} [${k}/${list.length}] ${e}: ${r.written}/${r.contracts} files, ${r.rows} rows, ` +
                `${(r.bytes / 1e6).toFixed(0)} MB, ${r.cleaned} cleaned, ${r.bad.length} bad, ${r.seconds}s`);
        } catch (err) {
            console.log(`${e} FAILED: ${err.message}`);
        } finally {
            fs.rmSync(tmp, { recursive: true, force: true });
        }
    }
}

if (require.main === module) main();
module.exports = { combineExpiry };
