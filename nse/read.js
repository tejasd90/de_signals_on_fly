// nse/read.js
// ─────────────────────────────────────────────────────────────────────────────
// Readers for the files group.js writes, the two views of the 15:30-15:40 minutes,
// and a spot series made from the option chain itself.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const cal = require('./calendar');

function loadContract(file) { return JSON.parse(zlib.gunzipSync(fs.readFileSync(file)).toString()); }

/** NIFTY26N1725300CE / NIFTY26NOV26000PE / NIFTY26NOVFUT -> { name, type: 'C'|'P'|'F', strike } */
function parseSymbol(sym) {
    let m = /^([A-Z0-9&-]+?)(\d{2})([A-Z]{3}|[1-9OND]\d{2})(\d+(?:\.\d+)?)(CE|PE)$/.exec(sym);
    if (m) return { name: m[1], type: m[5] === 'CE' ? 'C' : 'P', strike: +m[4] };
    m = /^([A-Z0-9&-]+?)(\d{2})([A-Z]{3})FUT$/.exec(sym);
    return m ? { name: m[1], type: 'F', strike: 0 } : null;
}

/**
 * rows [ts,o,h,l,c,v,oi] -> candle objects the crypto signal modules take.
 * view 'separate': as stored (15:30-15:40 is its own bar on the 5/10/15/25/75/125 grids).
 * view 'merged'  : bars starting at or after 15:30 are folded into the bar before them, same day.
 */
function toCandles(rows, view = 'separate') {
    const out = [];
    for (const r of rows) {
        const ts = r[0];
        if (view === 'merged' && out.length && ts.slice(11, 16) >= '15:30' && ts.slice(0, 10) >= cal.LONG_CLOSE_FROM) {
            const p = out[out.length - 1];
            if (p.dtstring.slice(0, 10) === ts.slice(0, 10)) {
                if (r[2] > p.high) p.high = r[2];
                if (r[3] < p.low) p.low = r[3];
                p.close = r[4]; p.volume += r[5]; p.oi = r[6];
                continue;
            }
        }
        out.push({ dtstring: ts, open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5], oi: r[6] });
    }
    return out;
}

/** Close-to-close view: each bar's open is the previous bar's close (his 20 Nov variant). */
function closeToClose(candles) {
    const out = [];
    for (let i = 1; i < candles.length; i++) {
        const c = candles[i], o = candles[i - 1].close;
        out.push({ dtstring: c.dtstring, open: o, high: Math.max(c.high, o), low: Math.min(c.low, o), close: c.close, volume: c.volume, oi: c.oi });
    }
    return out;
}

/** All contracts of one underlying in an expiry folder: [{ sym, token, type, strike, file }]. */
function listChain(expiryDir, name) {
    const out = [];
    for (const f of fs.readdirSync(expiryDir)) {
        if (!f.endsWith('.json.gz')) continue;
        const base = f.slice(0, -8), us = base.lastIndexOf('_');
        const sym = us > 0 ? base.slice(0, us) : base;
        const p = parseSymbol(sym);
        if (p && p.name === name && p.type !== 'F') out.push({ sym, token: base.slice(us + 1), type: p.type, strike: p.strike, file: path.join(expiryDir, f) });
    }
    return out;
}

function underlyings(expiryDir) {
    const s = new Set();
    for (const f of fs.readdirSync(expiryDir)) if (f.endsWith('.json.gz')) { const p = parseSymbol(f.slice(0, f.lastIndexOf('_'))); if (p) s.add(p.name); }
    return [...s].sort();
}

/**
 * Spot from the chain: at each bar, the three strikes where call and put closes are nearest
 * give strike + call - put; the median is used. This is the forward to expiry, within a
 * few points of the index for weeklies. Only bars where both sides traded are used.
 * @param chain [{ type, strike, candles }]  @returns Map<dtstring, { close }>
 */
function syntheticSpot(chain) {
    const byTs = new Map();                      // ts -> Map(strike -> [C, P])
    for (const k of chain) for (const c of k.candles) {
        if (!(c.volume > 0)) continue;
        let m = byTs.get(c.dtstring); if (!m) byTs.set(c.dtstring, m = new Map());
        let e = m.get(k.strike); if (!e) m.set(k.strike, e = [null, null]);
        e[k.type === 'C' ? 0 : 1] = c.close;
    }
    const spot = new Map();
    let last = null;
    for (const ts of [...byTs.keys()].sort()) {
        const cand = [];
        for (const [K, e] of byTs.get(ts)) if (e[0] !== null && e[1] !== null) cand.push([Math.abs(e[0] - e[1]), K + e[0] - e[1]]);
        if (cand.length) { cand.sort((a, b) => a[0] - b[0]); const top = cand.slice(0, 3).map(x => x[1]).sort((a, b) => a - b); last = top[Math.floor(top.length / 2)]; }
        if (last !== null) spot.set(ts, { close: last });
    }
    return spot;
}

module.exports = { loadContract, parseSymbol, toCandles, closeToClose, listChain, underlyings, syntheticSpot };
