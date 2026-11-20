// nse/fetch_spot.js
// ─────────────────────────────────────────────────────────────────────────────
// 1-minute index history from Kite (indices do not expire, so this can run any day with a
// valid token), grouped at once into the same timeframes as the options.
// Tokens are his, from explosion_after_premium_eroded_signal/utils.js; INDIA VIX added.
//
//   node fetch_spot.js --out <dir> --api-key <key> --token-file <file> [--from 2022-06-01] [--names NIFTY,SENSEX]
//
// Writes <out>/<NAME>.json.gz  { s, first, last, n1, c: { "5": [[ts,o,h,l,c,0,0],...], ..., "1w": [...] } }
// and <out>/1m/<NAME>.json.gz (the 1-minute rows; needed to resume, small). Re-running fetches only from the last stored day.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { groupContract } = require('./group');

const INDICES = { NIFTY: 256265, BANKNIFTY: 260105, FINNIFTY: 257801, MIDCPNIFTY: 288009, NIFTYNXT50: 270857, SENSEX: 265, BANKEX: 274441, INDIAVIX: 264969 };
const WINDOW_DAYS = 55;       // Kite allows 60 days of minute candles per call

const a = process.argv.slice(2);
const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ymd = d => d.toISOString().slice(0, 10);

async function main() {
    const out = opt('out'), apiKey = opt('api-key') || process.env.KITE_API_KEY, tokenFile = opt('token-file');
    if (!out || !apiKey || !tokenFile) { console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(1, 11).join('\n')); process.exit(1); }
    const headers = { 'X-Kite-Version': '3', Authorization: `token ${apiKey}:${fs.readFileSync(tokenFile, 'utf8').trim()}` };
    const names = opt('names') ? opt('names').split(',') : Object.keys(INDICES);
    const today = ymd(new Date(Date.now() + 5.5 * 3600 * 1000));
    fs.mkdirSync(path.join(out, '1m'), { recursive: true });

    async function get(url) {
        for (let t = 1; ; t++) {
            await sleep(400);
            let res, body;
            try { res = await fetch(url, { headers }); body = await res.text(); }
            catch (e) { if (t >= 6) throw e; await sleep(1000 * 2 ** t); continue; }
            if (res.ok) return JSON.parse(body);
            if (res.status === 403) throw new Error('403: the access token is not valid (it is renewed by logging in each morning)');
            if (t >= 6) throw new Error(`HTTP ${res.status} ${body.slice(0, 120)}`);
            await sleep(res.status === 429 ? 3000 * t : 1000 * 2 ** t);
        }
    }

    for (const name of names) {
        const raw = path.join(out, '1m', name + '.json.gz');
        let rows = fs.existsSync(raw) ? JSON.parse(zlib.gunzipSync(fs.readFileSync(raw)).toString()) : [];
        let from = rows.length ? rows[rows.length - 1][0].slice(0, 10) : (opt('from') || '2022-06-01');
        const seen = new Set(rows.map(r => r[0]));
        let added = 0;
        while (from <= today) {
            const to = ymd(new Date(Date.parse(from + 'T00:00:00Z') + WINDOW_DAYS * 86400000));
            const j = await get(`https://api.kite.trade/instruments/historical/${INDICES[name]}/minute?from=${from}+00:00:00&to=${to}+00:00:00&continuous=0&oi=1`);
            for (const r of (j.data && j.data.candles) || []) if (!seen.has(r[0])) { seen.add(r[0]); rows.push([r[0], r[1], r[2], r[3], r[4], r[5] || 0, r[6] || 0]); added++; }
            from = to;
        }
        rows.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
        if (!rows.length) { console.log(`${name}: no candles`); continue; }
        fs.writeFileSync(raw, zlib.gzipSync(JSON.stringify(rows)));     // needed to resume; small for 8 indices
        const g = groupContract(rows, rows[rows.length - 1][0].slice(0, 10), { spot: true });
        fs.writeFileSync(path.join(out, name + '.json.gz'), zlib.gzipSync(JSON.stringify({ s: name, first: g.first, last: g.last, n1: g.n1, c: g.c })));
        console.log(`${name}: +${added} rows, ${rows.length.toLocaleString()} in all, ${g.first.slice(0, 10)} .. ${g.last.slice(0, 16)}`);
    }
}

main().catch(e => { console.error('ERROR ' + e.message); process.exit(1); });
