// nse/group.js
// ─────────────────────────────────────────────────────────────────────────────
// 1-minute Kite candles  ->  5m, 10m, 15m, 25m, 1h, 75m, 125m, 1d, 1w, one small
// gzip file per contract. Run with no arguments for usage.
//
// Rules (his, from explosion_after_premium_eroded_signal, plus what he asked on 20 Nov 2026):
//   - only normal sessions: holidays, Muhurat and Saturday special sessions are dropped
//     (calendar.js); pre-open minutes are dropped;
//   - session 09:15-15:30, and 09:15-15:40 from 2026-08-03;
//   - the leading candles before the first TRADED minute (volume 0, a stale reference
//     price) are dropped;
//   - a missing bar inside the contract's life is filled flat at the previous close,
//     volume 0, previous OI, up to the close of the last session on or before expiry;
//   - bars are anchored at 09:15 each day. After 2026-08-03 the minutes 15:30-15:39 form
//     their own bar on the 5/10/15/25/75/125 grids (the "separate" view). The "merged"
//     view (those minutes folded into the bar before) is made when reading: read.js;
//   - small timeframes are kept only near expiry (KEEP_DAYS), as in the crypto config.
//
// Input files may be Kite's {"data":[[ts,o,h,l,c,v,oi],...]}, or the Windows-PowerShell
// damaged form where arrays became {"value":[...],"Count":n} and dates "/Date(ms)/",
// in UTF-8 or UTF-16. All are read; nothing is written back to the source.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { execFileSync } = require('child_process');
const cal = require('./calendar');

// duration -> trading days before expiry that are kept (Infinity = the whole life)
const KEEP_DAYS = { 5: 2, 10: 4, 15: 8, 25: 16, 60: Infinity, 75: Infinity, 125: Infinity, '1d': Infinity, '1w': Infinity };
const INTRADAY = [5, 10, 15, 25, 60, 75, 125];
const IST_MS = 5.5 * 3600 * 1000;

// ─── Reading and cleaning ─────────────────────────────────────────────────────

function decode(buf) {
    if (buf.length >= 2 && buf[0] === 0xFF && buf[1] === 0xFE) return buf.toString('utf16le', 2);
    if (buf.length >= 3 && buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF) return buf.toString('utf8', 3);
    if (buf.length >= 2 && buf[1] === 0x00) return buf.toString('utf16le');      // UTF-16 without BOM
    return buf.toString('utf8');
}

/** {"value":[...],"Count":n} -> [...] , at any depth it occurs. */
function unwrap(x) {
    while (x && !Array.isArray(x) && typeof x === 'object' && x.value !== undefined) x = x.value;
    return x;
}

function istString(ms) { return new Date(ms + IST_MS).toISOString().slice(0, 19) + '+05:30'; }

function normTs(t) {
    if (typeof t === 'string') {
        if (t.length === 25 && t.charCodeAt(10) === 84 && t.endsWith('+05:30')) return t;
        const m = /Date\((-?\d+)/.exec(t);
        if (m) return istString(+m[1]);
        const ms = Date.parse(t);
        return Number.isNaN(ms) ? null : istString(ms);
    }
    if (typeof t === 'number') return istString(t);
    t = unwrap(t);
    if (t && typeof t === 'object' && t.DateTime) { const ms = Date.parse(t.DateTime); return Number.isNaN(ms) ? null : istString(ms); }
    return typeof t === 'string' ? normTs(t) : null;
}

/** Returns { rows, cleaned } ; rows are [ts, o, h, l, c, v, oi], unsorted. */
function readCandleFile(file) {
    const j = JSON.parse(decode(fs.readFileSync(file)));
    let data = j.data;
    let cleaned = false;
    if (data && !Array.isArray(data)) { data = unwrap(data.candles !== undefined ? data.candles : data); cleaned = true; }
    if (!Array.isArray(data)) return { rows: [], cleaned };
    const rows = [];
    for (let r of data) {
        if (!Array.isArray(r)) { r = unwrap(r); cleaned = true; }
        if (!Array.isArray(r) || r.length < 5) continue;
        const ts0 = r[0];
        const ts = normTs(ts0);
        if (ts === null) continue;
        if (ts !== ts0) cleaned = true;
        rows.push([ts, +unwrap(r[1]), +unwrap(r[2]), +unwrap(r[3]), +unwrap(r[4]), +unwrap(r[5]) || 0, +unwrap(r[6]) || 0]);
    }
    return { rows, cleaned };
}

// ─── Calendar for one expiry ──────────────────────────────────────────────────

/** Session days from `from` to `to` inclusive, by the rules in calendar.js. */
function sessionDays(from, to) {
    const days = [];
    for (let d = from; d <= to; d = cal.addDays(d, 1)) if (cal.isSessionDay(d)) days.push(d);
    return days;
}

// ─── Grouping ────────────────────────────────────────────────────────────────

/**
 * @param rows    1-minute rows of ONE contract (any order, duplicates allowed)
 * @param expiry  'YYYY-MM-DD'
 * @returns null if the contract never traded in a normal session, else
 *          { first, last, n1, c: { '5': [[ts,o,h,l,c,v,oi]...], ..., '1d': [...], '1w': [...] } }
 */
function groupContract(rows, expiry, opts = {}) {      // opts.spot: an index (no volume, keep every bar)
    // in-session rows, last write wins on a duplicated minute
    const byTs = new Map();
    for (const r of rows) {
        const ts = r[0], day = ts.slice(0, 10);
        if (day > expiry || !cal.isSessionDay(day)) continue;
        const mod = (+ts.slice(11, 13)) * 60 + (+ts.slice(14, 16));
        if (mod < cal.OPEN_MIN || mod >= cal.closeMin(day)) continue;
        byTs.set(ts, r);
    }
    let keys = [...byTs.keys()].sort();
    let s = 0;
    while (!opts.spot && s < keys.length && !(byTs.get(keys[s])[5] > 0)) s++;       // drop the untraded lead-in
    if (s === keys.length) return null;
    keys = s ? keys.slice(s) : keys;

    const firstDay = keys[0].slice(0, 10);
    const days = sessionDays(firstDay, expiry);                          // fill runs to the expiry session
    const dayIdx = new Map(days.map((d, i) => [d, i]));
    const firstMod = (+keys[0].slice(11, 13)) * 60 + (+keys[0].slice(14, 16));

    const out = {};
    const durs = INTRADAY.concat(['1d', '1w']);
    // slot id: intraday di*1000+bucket, daily di, weekly index of the week
    const weekOf = days.map(d => cal.weekStart(d));
    const weekIdx = []; { let w = -1, prev = null; for (const ws of weekOf) { if (ws !== prev) { w++; prev = ws; } weekIdx.push(w); } }

    for (const dur of durs) {
        const agg = new Map();
        for (const k of keys) {
            const r = byTs.get(k);
            const di = dayIdx.get(k.slice(0, 10));
            let slot;
            if (dur === '1d') slot = di;
            else if (dur === '1w') slot = weekIdx[di];
            else slot = di * 1000 + Math.floor(((+k.slice(11, 13)) * 60 + (+k.slice(14, 16)) - cal.OPEN_MIN) / dur);
            const a = agg.get(slot);
            if (!a) agg.set(slot, [r[1], r[2], r[3], r[4], r[5], r[6]]);
            else { if (r[2] > a[1]) a[1] = r[2]; if (r[3] < a[2]) a[2] = r[3]; a[3] = r[4]; a[4] += r[5]; a[5] = r[6]; }
        }
        const keep = opts.spot ? Infinity : KEEP_DAYS[dur];
        const minDi = keep === Infinity ? 0 : Math.max(0, days.length - keep);
        const bars = [];
        let prev = null;
        const emit = (slot, ts, di) => {
            let a = agg.get(slot);
            if (!a) { if (!prev) return; a = [prev[3], prev[3], prev[3], prev[3], 0, prev[5]]; }
            prev = a;
            if (di >= minDi) bars.push([ts, a[0], a[1], a[2], a[3], a[4], a[5]]);
        };
        if (dur === '1d') {
            for (let di = 0; di < days.length; di++) emit(di, cal.tsOf(days[di], cal.OPEN_MIN), di);
        } else if (dur === '1w') {
            for (let di = 0; di < days.length; di++) if (di === 0 || weekIdx[di] !== weekIdx[di - 1]) {
                let last = di; while (last + 1 < days.length && weekIdx[last + 1] === weekIdx[di]) last++;
                emit(weekIdx[di], cal.tsOf(days[di], cal.OPEN_MIN), last);       // kept if its last day is inside the window
            }
        } else {
            for (let di = 0; di < days.length; di++) {
                const nb = Math.ceil((cal.closeMin(days[di]) - cal.OPEN_MIN) / dur);
                const b0 = di === 0 ? Math.floor((firstMod - cal.OPEN_MIN) / dur) : 0;
                for (let b = b0; b < nb; b++) emit(di * 1000 + b, cal.tsOf(days[di], cal.OPEN_MIN + b * dur), di);
            }
        }
        out[dur] = bars;
    }
    return { first: keys[0], last: keys[keys.length - 1], n1: keys.length, c: out };
}

// ─── One expiry ───────────────────────────────────────────────────────────────

const isCandleName = f => f.endsWith('.json') && !f.startsWith('._');
const isDay = f => /^\d{4}-\d{2}-\d{2}$/.test(f);

/** name -> [paths]; from <dir>/<day>/<file> (kind 'days') or <dir>/<file> (kind 'combined'). */
function listContracts(dir, kind) {
    const map = new Map();
    const dayDirs = [];
    if (kind === 'combined') {
        for (const f of fs.readdirSync(dir)) if (isCandleName(f)) map.set(f, [path.join(dir, f)]);
    } else {
        for (const d of fs.readdirSync(dir).filter(isDay).sort()) {
            dayDirs.push(d);
            for (const f of fs.readdirSync(path.join(dir, d))) if (isCandleName(f)) {
                const a = map.get(f); if (a) a.push(path.join(dir, d, f)); else map.set(f, [path.join(dir, d, f)]);
            }
        }
    }
    return { map, dayDirs };
}

function processExpiry(expiry, dir, kind, outRoot) {
    const t0 = Date.now();
    const { map, dayDirs } = listContracts(dir, kind);
    const outDir = path.join(outRoot, expiry);
    fs.mkdirSync(outDir, { recursive: true });
    const rep = { expiry, source: kind, contracts: map.size, written: 0, neverTraded: 0, cleanedFiles: 0, badFiles: [],
        rows1m: 0, bytesOut: 0, underlyings: {} };
    for (const [name, paths] of map) {
        let rows = [];
        for (const p of paths) {
            try { const r = readCandleFile(p); if (r.cleaned) rep.cleanedFiles++; rows = rows.length ? rows.concat(r.rows) : r.rows; }
            catch (e) { if (rep.badFiles.length < 50) rep.badFiles.push(path.relative(dir, p) + ': ' + String(e.message).slice(0, 80)); }
        }
        const g = groupContract(rows, expiry);
        if (!g) { rep.neverTraded++; continue; }
        const base = name.replace(/\.json$/, '');
        const us = base.lastIndexOf('_');
        const sym = us > 0 ? base.slice(0, us) : base, token = us > 0 ? base.slice(us + 1) : '';
        const buf = zlib.gzipSync(JSON.stringify({ s: sym, t: token, e: expiry, first: g.first, last: g.last, n1: g.n1, c: g.c }), { level: 6 });
        fs.writeFileSync(path.join(outDir, base + '.json.gz'), buf);
        rep.written++; rep.rows1m += g.n1; rep.bytesOut += buf.length;
        const u = (/^([A-Z0-9&-]+?)\d{2}(?:[A-Z]{3}|[1-9OND]\d{2})/.exec(sym) || [0, sym])[1];
        rep.underlyings[u] = (rep.underlyings[u] || 0) + 1;
    }
    if (kind === 'days' && dayDirs.length) {
        rep.days = dayDirs.length;
        rep.dayDirsDropped = dayDirs.filter(d => !cal.isSessionDay(d) || d > expiry);                    // special sessions etc.
        const have = new Set(dayDirs);
        rep.sessionDaysWithoutData = sessionDays(dayDirs[0], expiry).filter(d => !have.has(d));          // holiday list gaps show up here
    }
    rep.seconds = Math.round((Date.now() - t0) / 100) / 10;
    fs.writeFileSync(path.join(outDir, '_report.json'), JSON.stringify(rep, null, 1));
    return rep;
}

// ─── CLI ──────────────────────────────────────────────────────────────────────

function main() {
    const a = process.argv.slice(2);
    const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
    const out = opt('out');
    if (!out || !(opt('days') || opt('combined') || opt('tars'))) {
        console.log(`usage: node group.js --out <dir> [--days <dir of expiry/day/files>] [--combined <dir of expiry/files>]
                     [--tars <dir of expiry.tar.gz> --tmp <scratch dir>] [--expiries a,b,c | --from d --to d] [--part i/n] [--force]
  Sources are tried per expiry in the order: --tars, --days, --combined. An expiry with _report.json in --out is skipped unless --force.`);
        process.exit(1);
    }
    const src = {};
    if (opt('tars')) for (const f of fs.readdirSync(opt('tars'))) { const m = /^(\d{4}-\d{2}-\d{2})\.tar\.gz$/.exec(f); if (m) src[m[1]] = ['tar', path.join(opt('tars'), f)]; }
    for (const [k, kind] of [['days', 'days'], ['combined', 'combined']]) if (opt(k))
        for (const d of fs.readdirSync(opt(k)).filter(isDay)) if (!src[d]) src[d] = [kind, path.join(opt(k), d)];
    let list = Object.keys(src).sort();
    if (opt('expiries')) { const w = new Set(opt('expiries').split(',')); list = list.filter(e => w.has(e)); }
    if (opt('from')) list = list.filter(e => e >= opt('from'));
    if (opt('to')) list = list.filter(e => e <= opt('to'));
    if (opt('part')) { const [i, n] = opt('part').split('/').map(Number); list = list.filter((_, k) => k % n === i); }
    const force = a.includes('--force');
    let done = 0;
    for (const e of list) {
        if (!force && fs.existsSync(path.join(out, e, '_report.json'))) { done++; continue; }
        let [kind, p] = src[e], tmp = null;
        try {
            if (kind === 'tar') {
                tmp = path.join(opt('tmp') || path.join(out, '_tmp'), e + '_' + process.pid);
                fs.mkdirSync(tmp, { recursive: true });
                execFileSync('tar', ['-xzf', p, '-C', tmp], { stdio: ['ignore', 'ignore', 'pipe'] });
                const inner = path.join(tmp, e);
                p = fs.existsSync(inner) ? inner : tmp; kind = 'days';
            }
            const r = processExpiry(e, p, kind, out);
            done++;
            console.log(`${new Date().toISOString().slice(11, 19)} [${done}/${list.length}] ${e} ${src[e][0]}: ${r.written}/${r.contracts} contracts, ` +
                `${r.neverTraded} never traded, ${r.cleanedFiles} cleaned, ${r.badFiles.length} bad, ${(r.bytesOut / 1e6).toFixed(1)} MB, ${r.seconds}s` +
                (r.dayDirsDropped && r.dayDirsDropped.length ? ` | dropped days ${r.dayDirsDropped.join(',')}` : '') +
                (r.sessionDaysWithoutData && r.sessionDaysWithoutData.length ? ` | NO DATA on ${r.sessionDaysWithoutData.join(',')}` : ''));
        } catch (err) {
            console.log(`${e} FAILED: ${err.message}`);
        } finally {
            if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
        }
    }
}

if (require.main === module) main();
module.exports = { readCandleFile, groupContract, processExpiry, listContracts, KEEP_DAYS, INTRADAY, decode, unwrap, normTs };
