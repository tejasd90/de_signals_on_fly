// nse/fetch_stocks.js
// ─────────────────────────────────────────────────────────────────────────────
// Daily candles for every NSE and BSE equity Kite lists today (his rule from
// stocks_multibaggers.js: instrument_type EQ, segment NSE or BSE). NSE first; a BSE
// symbol that also trades on NSE is skipped. Kite's daily history is adjusted for splits
// and bonuses. Only currently listed names exist: delisted companies are missing.
//
//   node fetch_stocks.js --out <dir> --api-key <key> --token-file <file> [--from 2010-01-01] [--rps 3] [--exchanges NSE,BSE]
//
// Writes <out>/1d/<EXCH>/<SYMBOL>_<token>.json.gz  { s, x, t, name, rows: [[YYYY-MM-DD,o,h,l,c,v],...] }
// and <out>/instruments_<date>.csv. Safe to re-run: finished symbols are skipped.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const WINDOW_DAYS = 1990;        // Kite allows 2000 days of day candles per call
const a = process.argv.slice(2);
const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ymd = d => d.toISOString().slice(0, 10);

function parseCsvLine(line) {
    const out = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (q) { if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch; }
        else if (ch === '"') q = true;
        else if (ch === ',') { out.push(cur); cur = ''; }
        else cur += ch;
    }
    out.push(cur);
    return out;
}

async function main() {
    const out = opt('out'), apiKey = opt('api-key') || process.env.KITE_API_KEY, tokenFile = opt('token-file');
    if (!out || !apiKey || !tokenFile) { console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(1, 12).join('\n')); process.exit(1); }
    const from0 = opt('from') || '2010-01-01';
    const rps = +(opt('rps') || 3);
    const exchanges = (opt('exchanges') || 'NSE,BSE').split(',');
    const headers = { 'X-Kite-Version': '3', Authorization: `token ${apiKey}:${fs.readFileSync(tokenFile, 'utf8').trim()}` };
    const log = m => console.log(new Date().toISOString().slice(11, 19) + ' ' + m);
    let nextSlot = 0;
    const slot = async () => { const now = Date.now(); const at = Math.max(now, nextSlot); nextSlot = at + 1000 / rps; if (at > now) await sleep(at - now); };

    async function get(url, asText) {
        for (let t = 1; ; t++) {
            await slot();
            let res, body;
            try { res = await fetch(url, { headers }); body = await res.text(); }
            catch (e) { if (t >= 6) throw e; await sleep(1000 * 2 ** t); continue; }
            if (res.ok) return asText ? body : JSON.parse(body);
            if (res.status === 403) throw new Error('403: the access token is not valid (it is renewed by logging in each morning)');
            if (res.status === 400) return null;                         // no data for this instrument / range
            if (t >= 6) throw new Error(`HTTP ${res.status} ${body.slice(0, 120)}`);
            await sleep(res.status === 429 ? 3000 * t : 1000 * 2 ** t);
        }
    }

    const today = ymd(new Date(Date.now() + 5.5 * 3600 * 1000));
    const csv = await get('https://api.kite.trade/instruments', true);
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, `instruments_${today}.csv`), csv);
    const lines = csv.split(/\r?\n/).filter(Boolean);
    const head = parseCsvLine(lines[0]); const col = n => head.indexOf(n);
    const [iTok, iSym, iName, iType, iSeg] = ['instrument_token', 'tradingsymbol', 'name', 'instrument_type', 'segment'].map(col);
    const all = [];
    for (let i = 1; i < lines.length; i++) { const f = parseCsvLine(lines[i]); if (f[iType] === 'EQ' && exchanges.includes(f[iSeg])) all.push({ token: f[iTok], sym: f[iSym], name: f[iName], x: f[iSeg] }); }
    const nseSyms = new Set(all.filter(i => i.x === 'NSE').map(i => i.sym));
    const list = all.filter(i => i.x === 'NSE').concat(all.filter(i => i.x === 'BSE' && !nseSyms.has(i.sym)));
    log(`${all.filter(i => i.x === 'NSE').length} NSE + ${all.filter(i => i.x === 'BSE').length} BSE equities listed; fetching ${list.length} (BSE symbols also on NSE skipped)`);
    for (const x of exchanges) fs.mkdirSync(path.join(out, '1d', x), { recursive: true });

    let done = 0, skipped = 0, empty = 0, failed = 0, next = 0, stop = false;
    async function worker() {
        while (next < list.length && !stop) {
            const ins = list[next++];
            const file = path.join(out, '1d', ins.x, `${ins.sym.replace(/[^A-Za-z0-9&._-]/g, '_')}_${ins.token}.json.gz`);
            if (fs.existsSync(file)) { skipped++; continue; }
            try {
                const parts = [];
                let to = today;
                while (to >= from0) {
                    let from = ymd(new Date(Date.parse(to + 'T00:00:00Z') - WINDOW_DAYS * 86400000));
                    if (from < from0) from = from0;
                    const j = await get(`https://api.kite.trade/instruments/historical/${ins.token}/day?from=${from}&to=${to}`);
                    const c = j && j.data && j.data.candles ? j.data.candles : [];
                    if (!c.length) break;                                    // before the listing, or never traded
                    parts.push(c);
                    if (from === from0) break;
                    to = ymd(new Date(Date.parse(from + 'T00:00:00Z') - 86400000));
                }
                const seen = new Set(), rows = [];
                for (const p of parts.reverse()) for (const r of p) { const d = String(r[0]).slice(0, 10); if (!seen.has(d)) { seen.add(d); rows.push([d, r[1], r[2], r[3], r[4], r[5] || 0]); } }
                rows.sort((p, q) => (p[0] < q[0] ? -1 : 1));
                if (!rows.length) { empty++; fs.writeFileSync(file, zlib.gzipSync(JSON.stringify({ s: ins.sym, x: ins.x, t: ins.token, name: ins.name, rows: [] }))); continue; }
                fs.writeFileSync(file + '.part', zlib.gzipSync(JSON.stringify({ s: ins.sym, x: ins.x, t: ins.token, name: ins.name, rows })));
                fs.renameSync(file + '.part', file);
                done++;
                if (done % 200 === 0) log(`${done + skipped + empty + failed}/${list.length}: ${done} written, ${empty} empty, ${failed} failed`);
            } catch (e) {
                failed++; log(`FAILED ${ins.x}:${ins.sym}: ${e.message}`);
                if (/403/.test(e.message)) stop = true;
            }
        }
    }
    await Promise.all(Array.from({ length: Math.max(1, Math.ceil(rps)) }, worker));
    log(`${stop ? 'STOPPED (token)' : 'done'}: ${done} written, ${skipped} already there, ${empty} with no candles, ${failed} failed -> ${out}`);
}

main().catch(e => { console.error('ERROR ' + e.message); process.exit(1); });
