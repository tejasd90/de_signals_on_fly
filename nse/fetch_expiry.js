// nse/fetch_expiry.js
// ─────────────────────────────────────────────────────────────────────────────
// Downloads the full 1-minute history of every NFO/BFO contract expiring on a date,
// ONE file per contract (all days together), in the same {"data":[[ts,o,h,l,c,v,oi],...]}
// form as combined_js. Replaces generate_candles_weekly_fo.ps1 + the combine step.
// Kite only serves a contract until it expires, so this runs on expiry day after the close.
//
//   node fetch_expiry.js --out <dir> --api-key <key> --token-file <file with today's access token>
//                        [--date YYYY-MM-DD (default today, IST)] [--rps 3] [--instruments-dir <dir>] [--only NIFTY,SENSEX]
//
// Writes <out>/<date>/<TRADINGSYMBOL>_<token>.json. Safe to re-run: finished contracts are
// skipped, a contract is written only when its whole history has been fetched.
// The API key and token are never written anywhere by this program.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const fs = require('fs');
const path = require('path');

const WINDOW_DAYS = 30;          // Kite allows 60 days of minute candles per call; 30 as in the old script
const EMPTY_WINDOWS_TO_STOP = 2; // the old script stopped at the first empty 30 days, which cuts a contract that did not trade for a month
const MAX_TRIES = 6;

const a = process.argv.slice(2);
const opt = k => { const i = a.indexOf('--' + k); return i >= 0 ? a[i + 1] : undefined; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const istNow = () => new Date(Date.now() + 5.5 * 3600 * 1000);
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

// One request slot every 1000/rps ms, shared by all workers.
function makeLimiter(rps) {
    let next = 0;
    return async () => { const now = Date.now(); const at = Math.max(now, next); next = at + 1000 / rps; if (at > now) await sleep(at - now); };
}

async function main() {
    const out = opt('out'), apiKey = opt('api-key') || process.env.KITE_API_KEY, tokenFile = opt('token-file');
    if (!out || !apiKey || !tokenFile) { console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(1, 14).join('\n')); process.exit(1); }
    const date = opt('date') || ymd(istNow());
    const rps = +(opt('rps') || 3);
    const only = opt('only') ? new Set(opt('only').split(',')) : null;
    const headers = { 'X-Kite-Version': '3', Authorization: `token ${apiKey}:${fs.readFileSync(tokenFile, 'utf8').trim()}` };
    const slot = makeLimiter(rps);
    const log = m => console.log(new Date().toISOString().slice(11, 19) + ' ' + m);

    async function get(url, asText) {
        for (let t = 1; ; t++) {
            await slot();
            let res, body;
            try { res = await fetch(url, { headers }); body = await res.text(); }
            catch (e) { if (t >= MAX_TRIES) throw e; await sleep(1000 * 2 ** t); continue; }
            if (res.ok) return asText ? body : JSON.parse(body);
            if (res.status === 403) throw new Error('403: the access token is not valid (it is renewed by logging in each morning)');
            if (/contract not found/i.test(body)) return null;
            if (t >= MAX_TRIES) throw new Error(`HTTP ${res.status} ${body.slice(0, 120)}`);
            await sleep(res.status === 429 ? 3000 * t : 1000 * 2 ** t);
        }
    }

    const csv = await get('https://api.kite.trade/instruments', true);
    if (opt('instruments-dir')) { fs.mkdirSync(opt('instruments-dir'), { recursive: true }); fs.writeFileSync(path.join(opt('instruments-dir'), date + '.csv'), csv); }
    const lines = csv.split(/\r?\n/).filter(Boolean);
    const head = parseCsvLine(lines[0]); const col = n => head.indexOf(n);
    const [iTok, iSym, iName, iExp, iExch] = ['instrument_token', 'tradingsymbol', 'name', 'expiry', 'exchange'].map(col);
    const list = [];
    for (let i = 1; i < lines.length; i++) {
        const f = parseCsvLine(lines[i]);
        if ((f[iExch] === 'NFO' || f[iExch] === 'BFO') && f[iExp] === date && (!only || only.has(f[iName]))) list.push({ token: f[iTok], sym: f[iSym] });
    }
    log(`${list.length} contracts expire on ${date}`);
    const dir = path.join(out, date);
    fs.mkdirSync(dir, { recursive: true });

    const fmt = d => ymd(d) + '+00:00:00';
    let done = 0, skipped = 0, empty = 0, failed = 0, rows = 0, next = 0;
    async function worker() {
        while (next < list.length) {
            const ins = list[next++];
            const file = path.join(dir, `${ins.sym}_${ins.token}.json`);
            if (fs.existsSync(file)) { skipped++; continue; }
            try {
                const parts = [];
                let to = new Date(Date.parse(date + 'T00:00:00Z') + 86400000), emptyRun = 0;
                while (emptyRun < EMPTY_WINDOWS_TO_STOP) {
                    const from = new Date(to.getTime() - WINDOW_DAYS * 86400000);
                    const j = await get(`https://api.kite.trade/instruments/historical/${ins.token}/minute?from=${fmt(from)}&to=${fmt(to)}&continuous=0&oi=1`);
                    const c = j && j.data && j.data.candles ? j.data.candles : [];
                    if (c.length) { parts.push(c); emptyRun = 0; } else emptyRun++;
                    if (j === null) break;                                     // contract not found
                    to = from;
                }
                const seen = new Set(), all = [];
                for (const p of parts.reverse()) for (const r of p) if (!seen.has(r[0])) { seen.add(r[0]); all.push(r); }
                all.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
                if (!all.length) { empty++; continue; }
                fs.writeFileSync(file + '.part', JSON.stringify({ data: all }));
                fs.renameSync(file + '.part', file);
                rows += all.length; done++;
                if (done % 50 === 0) log(`${done + skipped + empty + failed}/${list.length} contracts, ${rows.toLocaleString()} rows`);
            } catch (e) {
                failed++; log(`FAILED ${ins.sym}: ${e.message}`);
                if (/403/.test(e.message)) { next = list.length; }
            }
        }
    }
    await Promise.all(Array.from({ length: Math.max(1, Math.ceil(rps)) }, worker));
    log(`done: ${done} written, ${skipped} already there, ${empty} with no candles, ${failed} failed, ${rows.toLocaleString()} rows -> ${dir}`);
    if (failed) process.exit(2);
}

main().catch(e => { console.error('ERROR ' + e.message); process.exit(1); });
