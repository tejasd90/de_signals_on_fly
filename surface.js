// surface.js
// ─────────────────────────────────────────────────────────────────────────────
// The EXPIRY x STRIKE board as of one chosen moment.
//
// Both grid viewers ask "where does this signal fire" with TIME on the column
// axis. This module answers the other question: a move happened at time T — what
// did it do to the whole board, every expiry and every strike at once?
//
// Shared by serve_grids.js (3800) and serve_grids_past.js (3900) deliberately.
// The two pages render it differently and anchor it differently, but the surface
// itself must be computed once in one place or the two will drift apart and stop
// being comparable.
//
// This is a node port of build_surfaces.py's `surface_at()`, which produced
// surfaces.json. Same definition of a cell, so numbers here and there agree.
//
// TWO MODES, TWO WINDOWS — and they differ on purpose
//   payoff   max(high) over [T, T + horizon) / close at T   ("what the move paid")
//   signals  firings whose ENTRY falls on the selected IST calendar DAY
//
// The payoff needs a forward window: "what did this move go on to do" is not a
// question about one day. The signals layer must NOT use that window, because a
// 72h window overlaps the next two days, so one firing would be counted under
// three different picked dates and every date would look three times as busy as
// it is. Scoping signals to the calendar day makes the rule exact:
// ONE FIRING BELONGS TO ONE DATE. Pick that date and you see it; pick any other
// and you do not.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs   = require('fs');
const path = require('path');
const cfg       = require('./config');
const writer    = require('./writer');
const spotStore = require('./spot_store');
const expiryMod = require('./expiry');
const chart     = require('./chart_url');

// Candle resolution the payoff scan reads. Fixed at 60m because the horizon is
// expressed in HOURS and mixing resolutions inside one window is the oldest trap
// in this project — an hourly and a daily candle at the same timestamp describe
// different spans. Not user-selectable for that reason.
const SCAN_DURATION = 60;

// Expiries further out than this are dropped. A 45-day board is already ~15 rows
// on BTC; past that the grid stops being readable long before it stops being
// cheap. Same bound build_surfaces.py used.
const MAX_HORIZON_DAYS = 45;

// Tolerance when locating T in a candle series. One SCAN_DURATION bar: if the
// nearest candle is further away than that, the contract simply was not trading
// at T and the cell stays empty rather than being filled from a stale bar.
const TS_TOLERANCE_SEC = SCAN_DURATION * 60;

// ─── Small helpers ────────────────────────────────────────────────────────────

/** `C-BTC-74800-150926` -> { type:'C', strike:74800 }. Null if unparseable. */
function parseSymbol(sym) {
    const p = sym.split('-');
    if (p.length < 4) return null;
    const type = p[0].toUpperCase();
    const strike = Number(p[2]);
    if ((type !== 'C' && type !== 'P') || !Number.isFinite(strike)) return null;
    return { type, strike };
}

/**
 * Expiries that had NOT yet settled at T, nearest first, bounded by horizon.
 * Read from the candle tree because that is what the payoff scan needs; the
 * signal tree is a subset of it.
 */
function liveExpiries(spot, tsSec, maxDays = MAX_HORIZON_DAYS) {
    const base = path.join(cfg.CANDLES_BASE_DIR, spot);
    if (!fs.existsSync(base)) return [];
    const tsMs = tsSec * 1000;
    const capMs = tsMs + maxDays * 86400000;

    return fs.readdirSync(base)
        .filter(d => !d.startsWith('.') && !d.startsWith('_'))
        .map(expiry => ({ expiry, ms: expiryMod.expiryMillis(spot, expiry) }))
        .filter(e => Number.isFinite(e.ms) && e.ms > tsMs && e.ms <= capMs)
        .sort((a, b) => a.ms - b.ms)
        .map(e => ({ expiry: e.expiry, tte: (e.ms - tsMs) / 3600000 }));
}

/** Underlying price at T, for the moneyness labels on the strike axis. */
function spotPriceAt(spot, tsSec) {
    const day  = new Date(tsSec * 1000).toISOString().slice(0, 10);
    const prev = new Date((tsSec - 3 * 86400) * 1000).toISOString().slice(0, 10);
    const rows = spotStore.readSpotCandles(spot, SCAN_DURATION, prev, day);
    let best = null;
    for (const c of rows) if (c.time <= tsSec && (!best || c.time > best.time)) best = c;
    return best ? best.close : null;
}

// ─── Payoff surface ───────────────────────────────────────────────────────────
//
// Reads the compact stored arrays directly rather than candle_store.readCandles,
// which rebuilds a dtstring per row. At a few thousand contracts per board that
// formatting cost dominates everything else, and nothing here needs the string.

function payoffCells(spot, tsSec, expiries, horizonHours) {
    const out = { C: new Map(), P: new Map() };
    let files = 0;

    for (const { expiry } of expiries) {
        const dir = path.join(cfg.CANDLES_BASE_DIR, spot, expiry, String(SCAN_DURATION));
        if (!fs.existsSync(dir)) continue;

        for (const fn of fs.readdirSync(dir)) {
            if (!fn.endsWith('.json') || fn.includes('.tmp.')) continue;
            const meta = parseSymbol(fn.slice(0, -5));
            if (!meta) continue;

            let a;
            try { a = JSON.parse(fs.readFileSync(path.join(dir, fn), 'utf8')); }
            catch (_) { continue; }
            if (!Array.isArray(a) || a.length < 2) continue;
            files++;

            // Last bar at or before T.
            let lo = 0, hi = a.length - 1, j = -1;
            while (lo <= hi) {
                const mid = (lo + hi) >> 1;
                if (a[mid][0] <= tsSec) { j = mid; lo = mid + 1; } else hi = mid - 1;
            }
            if (j < 0 || tsSec - a[j][0] > TS_TOLERANCE_SEC) continue;

            const entry = a[j][4];
            if (!(entry > 0)) continue;

            // horizonHours <= 0 means "entry price only": a LIVE board has no
            // elapsed window to take a peak over, but it still needs the entry
            // premium so the min-premium floor can work there too.
            let peak = null;
            if (horizonHours > 0) {
                const end = Math.min(a.length, j + 1 + horizonHours);
                for (let i = j + 1; i < end; i++) {
                    const h = a[i][2];
                    if (Number.isFinite(h) && (peak === null || h > peak)) peak = h;
                }
                if (peak === null) continue;
            }
            out[meta.type].set(`${expiry}|${meta.strike}`,
                { peak: peak === null ? null : peak / entry, entry });
        }
    }
    return { cells: out, files };
}

// ─── Signal surface ───────────────────────────────────────────────────────────
//
// Merged ranges are [startTs, endTs, count, maxSignalValue, maxSignalRatio,
// state, instruments, universeMaxRatio, universeMaxSymbol] — see
// docs/02-architecture.md. Index 1 (endTs) is the ENTRY, so that is what decides
// whether a firing belongs to this window.
//
// Split per duration, same as the time-axis view: a 30m staircase and a daily
// staircase are different claims and averaging them hides which one fired.
// Returns { byDur: Map<duration, {C,P}>, durations }.

function signalCells(signalId, spot, fromMs, toMs, expiries, minDuration) {
    const byDur = new Map();
    const from = fromMs, to = toMs;

    const durDir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot);
    if (!fs.existsSync(durDir)) return { byDur, durations: [] };

    const durations = fs.readdirSync(durDir)
        .filter(x => !x.startsWith('.') && !x.startsWith('_') && !isNaN(x))
        .map(Number).filter(d => d >= minDuration).sort((a, b) => a - b);

    for (const duration of durations) {
        const out = { C: new Map(), P: new Map() };
        for (const { expiry } of expiries) {
            const data = writer.readSignals(signalId, spot, duration, expiry);
            for (const type of ['C', 'P']) {
                for (const r of (data[type] || [])) {
                    const entryMs = new Date(r[1]).getTime();
                    if (!(entryMs >= from && entryMs < to)) continue;
                    for (const sym of (r[6] || [])) {
                        const meta = parseSymbol(sym);
                        if (!meta || meta.type !== type) continue;
                        const k = `${expiry}|${meta.strike}`;
                        let c = out[type].get(k);
                        if (!c) { c = { n: 0, syms: [], urls: [], ratio: 0, iso: r[1] }; out[type].set(k, c); }
                        c.n++;
                        if (r[4] > c.ratio) c.ratio = r[4];   // signal's own maxSignalRatio
                        if (c.syms.length < 8 && !c.syms.includes(sym)) {
                            c.syms.push(sym);
                            c.urls.push(chart.chartUrl(spot, expiry, sym, entryMs, duration));
                        }
                    }
                }
            }
        }
        if (out.C.size || out.P.size) byDur.set(duration, out);
    }
    return { byDur, durations };
}

// ─── Assembly ─────────────────────────────────────────────────────────────────

/**
 * @param {string} spot
 * @param {number} tsSec        the moment the move starts — column anchor
 * @param {object} opts
 *        signalId     which signal to count (null = payoff layer only)
 *        horizonHours forward window, default 72 (build_surfaces.py's H_FWD)
 *        bandPct      keep strikes within +-this % of spot, 0 = keep all
 *        minDuration  duration floor for the signal boards
 *        minPremium   drop contracts cheaper than this at entry — see below
 *        withPayoff   false on a live board, where the window has not elapsed
 *
 * MIN PREMIUM
 * A contract marked at 0.5 that ticks to 11 is a "20x" that nobody could trade.
 * Measured on this very board: during the 2026-08-19 squeeze the puts that fired
 * split cleanly by premium — entry 0.56 -> 20.5x and 1.04 -> 13.2x, against
 * entry 7.5 -> 1.1x and 58.0 -> 1.4x for the ones priced like real options. The
 * cheap ones are sub-tick noise, not a signal pointing the wrong way. ML_SPEC P4
 * measured the edge surviving a floor up to 2.0 and the label being dominated by
 * artifacts below ~0.25, which is where the default comes from.
 *
 * The floor needs an entry premium, so it only bites when the payoff layer ran.
 * On a live board (withPayoff:false) there is nothing to filter on and it is
 * inert — stated in the UI rather than silently ignored.
 */
function buildSurface(spot, tsSec, opts = {}) {
    const horizonHours = opts.horizonHours || 72;
    const bandPct      = opts.bandPct == null ? 30 : opts.bandPct;
    const minDuration  = opts.minDuration || 0;
    const minPremium   = opts.minPremium  || 0;
    const withPayoff   = opts.withPayoff !== false;

    const expiries = liveExpiries(spot, tsSec, opts.maxDays || MAX_HORIZON_DAYS);
    const spotPx   = spotPriceAt(spot, tsSec);

    // On a live board we still scan for entry premiums when a floor is set —
    // otherwise the noise filter would silently do nothing there.
    const pay = withPayoff       ? payoffCells(spot, tsSec, expiries, horizonHours)
              : minPremium > 0   ? payoffCells(spot, tsSec, expiries, 0)
              : { cells: { C: new Map(), P: new Map() }, files: 0 };
    // IST calendar day containing the anchor. Delta stores IST wall-clock, and
    // the picked date on the calendar is an IST date, so the day must be cut in
    // IST or firings near midnight land under the wrong date.
    const IST = 19800;
    const dayFrom = (Math.floor((tsSec + IST) / 86400) * 86400 - IST) * 1000;
    const dayTo   = dayFrom + 86400000;

    const sig = opts.signalId
        ? signalCells(opts.signalId, spot, dayFrom, dayTo, expiries, minDuration)
        : { byDur: new Map(), durations: [] };

    // Apply the premium floor to the payoff layer first, so it also governs which
    // signal cells survive — a firing on a contract we just rejected as untradeable
    // must not reappear on the signals board.
    if (minPremium > 0) {
        for (const type of ['C', 'P'])
            for (const [k, v] of [...pay.cells[type]])
                if (!(v.entry >= minPremium)) pay.cells[type].delete(k);
    }
    const tradeable = type => (minPremium > 0 ? pay.cells[type] : null);

    // Shared axes across every board, computed once. If the columns moved between
    // durations or between shade modes the boards would stop being comparable,
    // which is the only reason to show them stacked.
    const lo = spotPx && bandPct ? spotPx * (1 - bandPct / 100) : -Infinity;
    const hi = spotPx && bandPct ? spotPx * (1 + bandPct / 100) :  Infinity;

    const keys = { C: new Set(), P: new Set() };
    for (const type of ['C', 'P']) {
        for (const k of pay.cells[type].keys()) keys[type].add(k);
        for (const [, cells] of sig.byDur)
            for (const k of cells[type].keys()) {
                const ok = tradeable(type);
                if (!ok || ok.has(k)) keys[type].add(k);
            }
    }

    const cols = {}, payGrid = {};
    const result = { spot, ts: tsSec, spotPx, horizonHours, withPayoff, minPremium,
                     signalDayFrom: dayFrom, signalDayTo: dayTo,
                     rows: expiries, cols, grid: payGrid, boards: [],
                     max: { payoff: 0, signals: 0 },
                     scanned: { files: pay.files, expiries: expiries.length,
                                durations: sig.durations } };

    for (const type of ['C', 'P']) {
        const strikes = [...new Set([...keys[type]].map(k => Number(k.split('|')[1])))]
                        .filter(s => s >= lo && s <= hi).sort((a, b) => a - b);
        cols[type] = strikes;
        payGrid[type] = expiries.map(({ expiry }) => strikes.map(s => {
            const c = pay.cells[type].get(`${expiry}|${s}`);
            if (!c) return null;
            if (c.peak > result.max.payoff) result.max.payoff = c.peak;
            return c;
        }));
    }

    // One board per duration, longest last so the caller can reverse as the
    // time-axis view does.
    for (const [duration, cells] of sig.byDur) {
        const board = { duration, grid: {}, max: 0, total: { C: 0, P: 0 } };
        for (const type of ['C', 'P']) {
            const ok = tradeable(type);
            board.grid[type] = expiries.map(({ expiry }) => cols[type].map(s => {
                const k = `${expiry}|${s}`;
                if (ok && !ok.has(k)) return null;
                const c = cells[type].get(k);
                if (!c) return null;
                const e = pay.cells[type].get(k);
                if (c.n > board.max) board.max = c.n;
                board.total[type] += c.n;
                return { n: c.n, syms: c.syms, urls: c.urls, ratio: c.ratio, iso: c.iso,
                         peak: e ? e.peak : null, entry: e ? e.entry : null };
            }));
        }
        if (board.total.C || board.total.P) result.boards.push(board);
        if (board.max > result.max.signals) result.max.signals = board.max;
    }
    return result;
}

module.exports = { buildSurface, liveExpiries, spotPriceAt, parseSymbol,
                   SCAN_DURATION, MAX_HORIZON_DAYS };
