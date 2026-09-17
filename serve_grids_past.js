// serve_grids_past.js
// ─────────────────────────────────────────────────────────────────────────────
// Signal heatmaps for SETTLED expiries: expiry x time-to-expiry.
// Run: node serve_grids_past.js   (port 3900)
//
//   rows  = expiries that have already settled, newest first
//   cols  = candles BEFORE that row's own settlement
//   cell  = how many STRIKES fired the selected signal there
//
// The sibling of serve_grids.js (3800), reading the same signal files, but
// asking the opposite question. 3800 is a point-in-time snapshot of what was
// ALIVE at a chosen moment — a monitor's view, outcome unknown. This one only
// ever shows expiries whose outcome is already final, which changes two things.
//
// WHY COLUMNS ARE TIME-TO-EXPIRY, NOT WALL-CLOCK TIME
// On 3800 every row shares one clock, because every row is alive at the same
// instant. Here the rows settled on different days, so a shared wall clock would
// put each expiry's firings in a different column and the grid would read as a
// diagonal smear. Aligning every row on its OWN settlement makes the columns
// comparable: column k is "k candles before expiry" for every row, which is the
// only axis on which two settled expiries can be compared at all.
// It also bounds the grid — a 90-day window at 5m candles is 25,920 wall-clock
// slots and unreadable; time-to-expiry stays at whatever "candles back" says.
//
// WHY THERE IS A PAYOFF SHADING MODE
// For a settled expiry maxSignalRatio (merged-range index 4) is known, so the
// cell can be shaded by what the firing actually PAID rather than by how many
// strikes fired. Count answers "where does this signal fire", payoff answers
// "where does firing it work", and those are different pictures. 3800 cannot
// offer this at all: its rows have not settled, so their ratios are still moving.
//
// Date selection is a month calendar rather than a dropdown — a full history is
// ~980 expiries and a select of that length is not navigable.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg       = require('./config');
const netinfo   = require('./netinfo');
const writer    = require('./writer');
const instr     = require('./instruments');
const expiryMod = require('./expiry');
const surfaceMod = require('./surface');
const chart      = require('./chart_url');
const pa         = require('./price_action');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3900;

// Candle slots shown before settlement. Same control as 3800 so the two pages
// mean the same thing by "candles back".
const DEFAULT_CANDLES_BACK = 40;

// Expiries shown at once. The window is chosen in days, and a 90-day window on
// BTC is ~90 rows; past that the grid stops being readable before it stops
// being cheap, so the cap is about legibility rather than cost.
const MAX_ROWS = 80;

// Symbols carried per cell for the hover readout, as on 3800.
const MAX_SYMBOLS_PER_CELL = 14;

// Shortest signal duration these grids will show. Deliberate floor, applied at
// DISPLAY time only — the 5m/10m/15m/20m signal files are still written, still
// on disk, and still visible in every other viewer. Only this page and its
// sibling hide them. Set to 0 to get them back; nothing needs re-extracting.
const MIN_DURATION_MINUTES = 30;

// Cell shading for the payoff mode. Deliberately finer than cfg.RATIO_BANDS,
// which is built for a 5-column matrix; the interesting structure here is all
// between 1x and 5x and the config bands put every bit of it in one bucket.
const PAYOFF_STOPS = [1, 1.5, 2, 3, 5, 10, 25];

// ─── Listing ──────────────────────────────────────────────────────────────────

function listSignals() {
    if (!fs.existsSync(cfg.SIGNALS_BASE_DIR)) return [];
    return fs.readdirSync(cfg.SIGNALS_BASE_DIR)
        .filter(d => !d.startsWith('.') &&
                     fs.statSync(path.join(cfg.SIGNALS_BASE_DIR, d)).isDirectory())
        .sort();
}

function listSpots(signalId) {
    const r = path.join(cfg.SIGNALS_BASE_DIR, signalId);
    if (!fs.existsSync(r)) return [];
    return fs.readdirSync(r)
        .filter(d => !d.startsWith('.') && !d.startsWith('_') &&
                     fs.statSync(path.join(r, d)).isDirectory())
        .sort();
}

function listDurations(signalId, spot) {
    const d = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot);
    if (!fs.existsSync(d)) return [];
    return fs.readdirSync(d)
        .filter(x => !x.startsWith('.') && !x.startsWith('_') && !isNaN(x))
        .map(Number)
        .filter(x => x >= MIN_DURATION_MINUTES)
        .sort((a, b) => a - b);
}

// ─── Calendar ─────────────────────────────────────────────────────────────────
//
// One number per expiry per side, read from the _summary files writer.js keeps
// for exactly this purpose. Deriving it from the duration files would be ~16,000
// reads per page load; the summaries are one small file per expiry.

const _calCache = new Map();

function calendar(signalId, spot) {
    const key = `${signalId}|${spot}`;
    if (_calCache.has(key)) return _calCache.get(key);

    const dir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot, '_summary');
    const days = {};
    let lo = null, hi = null;

    if (fs.existsSync(dir)) {
        const nowMs = Date.now();
        for (const f of fs.readdirSync(dir)) {
            if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
            const expiry = f.replace(/\.json$/, '');

            // A summary can exist for an expiry that has not settled yet, since
            // it is rewritten as signals arrive. Those belong on 3800, not here.
            if (expiryMod.expiryMillis(spot, expiry) > nowMs) continue;

            const s = writer.readExpirySummary(signalId, spot, expiry);
            if (!s) continue;

            days[expiry] = {
                c:  s.cCount | 0,
                p:  s.pCount | 0,
                fc: Number(s.firedC) || 0,
                fp: Number(s.firedP) || 0,
                uc: Number(s.univC)  || 0,
                up: Number(s.univP)  || 0,
            };
            if (lo === null || expiry < lo) lo = expiry;
            if (hi === null || expiry > hi) hi = expiry;
        }
    }

    const out = { days, first: lo, last: hi, count: Object.keys(days).length };
    _calCache.set(key, out);
    return out;
}

// ─── Firing extraction ────────────────────────────────────────────────────────
//
// Cached per (signal, spot, duration, EXPIRY) rather than per duration as on
// 3800. That page needs every expiry at once to decide which were alive; here
// the window already names its rows, so reading a whole history to show thirty
// days of it would be wasted work on every date click.

const _fireCache = new Map();

function firingsFor(signalId, spot, duration, expiry) {
    const key = `${signalId}|${spot}|${duration}|${expiry}`;
    if (_fireCache.has(key)) return _fireCache.get(key);

    const out = { C: [], P: [] };
    const data = writer.readSignals(signalId, spot, duration, expiry);

    for (const type of ['C', 'P']) {
        for (const r of (data[type] || [])) {
            const ts    = r[1];                       // entry (trigger) candle
            const sv    = Number(r[3]) || 0;          // maxSignalValue
            const fired = Number(r[4]) || 0;          // maxSignalRatio
            const univ  = Number(r[7]) || 0;          // universeMaxRatio
            const state = r[5] || '';
            const tsMs  = new Date(ts).getTime();
            if (Number.isNaN(tsMs)) continue;

            for (const sym of (r[6] || [])) {
                const p = instr.parseSymbol(sym);
                if (!isFinite(p.strike)) continue;
                out[type].push({ ts, tsMs, strike: p.strike, symbol: sym,
                                 signalValue: sv, fired, univ, state });
            }
        }
    }

    _fireCache.set(key, out);
    return out;
}

// ─── Rows ─────────────────────────────────────────────────────────────────────

/** Days back from `endDate`, inclusive, as a YYYY-MM-DD string. */
function shiftDate(endDate, days) {
    const d = new Date(`${endDate}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10);
}

/**
 * Settled expiries in the window ending at `endDate`, newest first.
 *
 * Newest first because the question asked of a past board is almost always
 * "what just happened", and a descending list puts that at the top of the page
 * instead of the bottom of a scroll.
 */
function rowsFor(signalId, spot, endDate, lookbackDays) {
    const cal   = calendar(signalId, spot);
    const start = shiftDate(endDate, Math.max(0, lookbackDays - 1));
    const nowMs = Date.now();

    return Object.keys(cal.days)
        .filter(e => e >= start && e <= endDate &&
                     expiryMod.expiryMillis(spot, e) <= nowMs)
        .sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))
        .slice(0, MAX_ROWS);
}

// ─── Grid ─────────────────────────────────────────────────────────────────────

/**
 * One heatmap, rows aligned on their own settlement.
 *
 * Column j sits `n - 1 - j` candles before settlement, so the rightmost column
 * is the settlement candle itself and reading left is reading backwards in the
 * expiry's life. A cell counts DISTINCT STRIKES for the same reason 3800 does:
 * one strike appearing in two overlapping merged ranges is one strike, and
 * counting it twice makes a broad moment look like a deep one.
 *
 * Slots are computed arithmetically from settlement rather than by walking a
 * candle grid, so an expiry whose stored candles are incomplete still places its
 * firings in the right column.
 */
function buildGrid(signalId, spot, duration, type, expiries, opts) {
    const n     = opts.candlesBack > 0 ? opts.candlesBack : DEFAULT_CANDLES_BACK;
    const msPer = duration * 60000;

    const cells = {};
    const rowBest = expiries.map(() => 0);
    let max = 0, total = 0, maxRatio = 0;

    expiries.forEach((expiry, ri) => {
        const settleMs = expiryMod.expiryMillis(spot, expiry);
        if (!isFinite(settleMs)) return;

        const bySlot = new Map();

        for (const f of firingsFor(signalId, spot, duration, expiry)[type]) {
            if (opts.minValue && f.signalValue < opts.minValue) continue;

            const back = Math.floor((settleMs - f.tsMs) / msPer);
            if (back < 0 || back > n - 1) continue;
            const ci = n - 1 - back;

            if (!bySlot.has(ci)) bySlot.set(ci, { syms: new Set(), at: new Map(), r: 0, u: 0, st: '', iso: f.ts });
            const s = bySlot.get(ci);
            s.syms.add(f.symbol);
            if (!s.at.has(f.symbol)) s.at.set(f.symbol, f.tsMs);
            if (f.fired > s.r) { s.r = f.fired; s.st = f.state; }
            if (f.univ  > s.u) s.u = f.univ;

            const rr = opts.ratioSource === 'universe' ? f.univ : f.fired;
            if (rr > rowBest[ri]) rowBest[ri] = rr;
        }

        for (const [ci, s] of bySlot) {
            const syms = [...s.syms].sort();
            const r = opts.ratioSource === 'universe' ? s.u : s.r;
            const shown = syms.slice(0, MAX_SYMBOLS_PER_CELL);
            cells[`${ri},${ci}`] = { n: syms.length, syms: shown,
                                     urls: shown.map(sym =>
                                        chart.chartUrl(spot, expiry, sym, s.at.get(sym), duration)),
                                     r: Math.round(r * 1000) / 1000, st: s.st, iso: s.iso };
            if (syms.length > max) max = syms.length;
            if (r > maxRatio) maxRatio = r;
            total += syms.length;
        }
    });

    // Column labels as time before expiry. Candle counts are the honest unit —
    // a column is one candle — but nobody reasons in candles, so the label is
    // the wall-clock equivalent and the corner states the candle size.
    //
    // The unit is fixed ONCE per grid, from the candle size, rather than chosen
    // per column. Choosing per column made a 12h grid read
    // "-468h, -19d, -444h", because 456h happens to divide into days and its
    // neighbours do not — three different units in three adjacent headers.
    // A duration that does not divide into hours (90m, 45m) would otherwise
    // label its far columns "-3510m", so once the span passes ten hours the
    // label switches to hours with one decimal — same unit for every column,
    // just a readable one.
    const span = (n - 1) * duration;
    const unit = duration % 1440 === 0 ? ['d', 1440]
               : duration % 60   === 0 ? ['h', 60]
               : span >= 600          ? ['h', 60]
               : ['m', 1];
    const times = [];
    for (let j = 0; j < n; j++) {
        const back = n - 1 - j;
        const v = (back * duration) / unit[1];
        times.push(back === 0 ? 'exp'
            : `-${Number.isInteger(v) ? v : v.toFixed(1)}${unit[0]}`);
    }

    return { expiries, times, cells, max, total, maxRatio, rowBest };
}

function buildAll(signalId, spot, endDate, opts) {
    const expiries = endDate ? rowsFor(signalId, spot, endDate, opts.lookbackDays) : [];

    const grids = [];
    let hidden = 0;

    // Longest duration first, as on 3800: it covers the most calendar time per
    // column and is therefore the widest view of the same window.
    for (const duration of listDurations(signalId, spot).slice().reverse()) {
        const C = buildGrid(signalId, spot, duration, 'C', expiries, opts);
        const P = buildGrid(signalId, spot, duration, 'P', expiries, opts);
        if (!C.total && !P.total && !opts.showEmpty) { hidden++; continue; }
        grids.push({ duration, C, P });
    }

    return { expiries, grids, hidden, window: {
        from: endDate ? shiftDate(endDate, Math.max(0, opts.lookbackDays - 1)) : null,
        to: endDate, capped: expiries.length >= MAX_ROWS } };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Settled signal heatmaps</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{--ground:#14161c;--surface:#1c1f28;--raised:#242833;--line:#2e3340;
        --text:#c8ccd8;--muted:#6b7183;--accent:#d4703a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1{font-family:'Space Grotesk',system-ui,sans-serif;margin:0;font-size:17px;font-weight:700}
  h1 .k{color:var(--accent)}
  .wrap{max-width:1700px;margin:0 auto;padding:20px 18px 60px}
  header{padding-bottom:12px;border-bottom:1px solid var(--line);margin-bottom:14px}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;max-width:900px}

  .bar{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
  label{color:var(--muted);font-size:10px;letter-spacing:.07em;text-transform:uppercase}
  select,input{background:var(--surface);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:5px 8px;font-family:inherit;font-size:12px}
  .radios{display:flex;gap:4px;flex-wrap:wrap}
  .radios button{background:var(--surface);color:var(--muted);border:1px solid var(--line);
    border-radius:3px;padding:5px 11px;font-family:inherit;font-size:11.5px;cursor:pointer}
  .radios button[aria-pressed=true]{background:var(--raised);color:var(--accent);border-color:var(--accent)}

  /* Calendar. A full history is ~980 expiries; a dropdown of that length is not
     navigable, and a slider cannot be aimed at a date you already have in mind. */
  .cal{background:var(--surface);border:1px solid var(--line);border-radius:3px;
       padding:10px 13px;margin-bottom:14px;display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}
  .calNav{display:flex;gap:4px;align-items:center;margin-bottom:7px}
  .calNav button{background:var(--raised);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:3px 8px;font-family:inherit;font-size:11px;cursor:pointer}
  .calNav button:disabled{opacity:.32;cursor:default}
  .calNav .m{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:13px;
             color:var(--accent);min-width:104px;text-align:center}
  table.cal7{border-collapse:separate;border-spacing:2px}
  table.cal7 th{color:#5a6070;font-weight:500;font-size:9px;padding:0 0 2px}
  table.cal7 td{width:27px;height:23px;padding:0;text-align:center;font-size:10.5px;
                border:1px solid transparent;border-radius:2px;color:#4e5464;font-variant-numeric:tabular-nums}
  table.cal7 td.has{color:#0d0f14;font-weight:700;cursor:pointer;
                    border-color:rgba(200,206,222,0.30)}
  table.cal7 td.has:hover{outline:2px solid var(--accent);outline-offset:1px}
  table.cal7 td.sel{outline:2px solid var(--accent);outline-offset:1px}
  .calSide{flex:1;min-width:230px;color:var(--muted);font-size:11px}
  .calSide b{color:var(--text)}
  .calSide .pick{font-family:'Space Grotesk',sans-serif;font-size:15px;font-weight:700;color:var(--accent)}

  .durRow{margin-bottom:14px;border:1px solid var(--line);border-radius:3px;background:var(--surface)}
  .durHead{display:flex;align-items:baseline;gap:10px;padding:5px 11px;flex-wrap:wrap;
           background:var(--raised);border-bottom:1px solid var(--line)}
  .durHead .d{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:13px}
  .durHead .c{color:var(--muted);font-size:10.5px}
  .pair{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line)}
  @media(max-width:1100px){.pair{grid-template-columns:1fr}}
  .pane{background:var(--surface);padding:7px 8px;min-width:0}
  .pane .t{color:var(--muted);font-size:10px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px}

  .gridScroll{overflow-x:auto;padding-bottom:4px}
  table.hm{border-collapse:separate;border-spacing:2px}
  table.hm th{color:var(--muted);font-weight:500;font-size:9px;padding:0;white-space:nowrap}
  table.hm th.rowh{text-align:right;padding-right:6px;font-size:10px;position:sticky;left:0;
                   background:var(--surface);z-index:1}
  table.hm th.corner{position:sticky;left:0;z-index:2;background:var(--surface);
                     text-align:right;padding-right:6px;font-size:9px;color:#5a6070;
                     white-space:nowrap;vertical-align:bottom}
  table.hm th.colh{writing-mode:vertical-rl;text-orientation:mixed;height:52px;
                   font-size:8.5px;color:#5a6070}
  table.hm th.best{font-size:9px;color:#5a6070;padding-left:7px;text-align:left}
  table.hm td{width:22px;height:22px;padding:0;text-align:center;font-size:9.5px;
              border:2px solid rgba(200,206,222,0.34);border-radius:2px;
              color:#0d0f14;font-weight:700;cursor:default}
  table.hm td.zero{border-color:rgba(70,76,92,0.30);background:#171a21;color:transparent}
  table.hm td.bestc{width:auto;border:none;background:none;color:var(--muted);
                    text-align:left;padding-left:7px;font-weight:400;
                    font-variant-numeric:tabular-nums;white-space:nowrap}
  table.hm td.bestc.hit{color:var(--accent);font-weight:700}
  table.hm td:hover{outline:2px solid var(--accent);outline-offset:1px}
  table.hm td.bestc:hover{outline:none}

  .readout{margin-top:6px;min-height:32px;color:var(--accent);font-size:11px;
           font-variant-numeric:tabular-nums;line-height:1.35}
  .readout .syms{color:var(--muted);font-size:10.5px;word-break:break-all}
  .readout .syms a{color:var(--accent);text-decoration:none;border-bottom:1px dotted currentColor;margin-right:9px}
  .readout .syms a:hover{color:#fff;border-bottom-style:solid}
  /* Floats with the viewport rather than sitting above the grids. The boards
     stack by duration and get tall, so a panel anchored to the document meant
     scrolling back to the top to read it. Docked to whichever side was NOT
     clicked, so it never covers the cell you just picked. */
  .pa{display:none;position:fixed;top:80px;width:352px;max-height:74vh;overflow-y:auto;
      padding:11px 13px;border:1px solid var(--line);border-radius:7px;
      background:var(--surface);z-index:60;box-shadow:0 10px 30px rgba(0,0,0,.6)}
  .pa.on{display:block}
  @media(max-width:900px){.pa{left:8px!important;right:8px!important;width:auto;max-height:52vh}}
  .pa h4{margin:0 0 3px;font-family:'Space Grotesk',sans-serif;font-size:13px;color:var(--accent)}
  .pa .meta{color:var(--muted);font-size:11px;margin-bottom:8px}
  .pa .tier{margin-top:7px;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;color:#5a6070}
  .pa .row{display:flex;align-items:center;gap:9px;padding:2.5px 0;font-size:11.5px}
  .pa .sw{width:26px;height:11px;border-radius:2px;flex:none}
  .pa .hit{color:var(--muted);font-size:10.5px;margin-left:auto;white-space:nowrap}
  .pa .note{color:#5a6070;font-size:10px;margin-top:9px;line-height:1.5}
  .pa .x{float:right;cursor:pointer;color:var(--muted);font-size:15px;line-height:1}
  .legend{display:flex;gap:13px;flex-wrap:wrap;font-size:10.5px;color:var(--muted);margin-top:10px}
  .legend .k{display:inline-flex;align-items:center;gap:5px}
  .sw{width:13px;height:13px;border-radius:2px;display:inline-block;
      border:2px solid rgba(200,206,222,0.34)}
  .empty{color:var(--muted);padding:16px;font-size:12px}
  .note{color:var(--muted);font-size:11px;padding:6px 2px 10px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="k">settled signal heatmaps</span> — expiry × time to expiry</h1>
    <div class="sub">Every row here has SETTLED, so what the firing paid is final. Rows are
      expiries in the chosen window, newest first; columns are candles before that row's
      own settlement, so column positions mean the same thing on every row. Shade by how
      many strikes fired, or by what the firing actually paid. Calls and puts share rows.
      Pick a date on the calendar — it is the end of the window, not a single expiry.</div>
  </header>

  <div class="bar">
    <span><label for="spot">Spot</label><br><select id="spot"></select></span>
    <span><label>Signal</label><div class="radios" id="sigs"></div></span>
    <span><label>Layout</label><div class="radios" id="layout">
      <button data-v="time" aria-pressed="true">expiry × time</button>
      <button data-v="strike" aria-pressed="false">expiry × strike</button></div></span>
    <span><label>Shade by</label><div class="radios" id="shade">
      <button data-v="count" aria-pressed="true">strikes fired</button>
      <button data-v="payoff" aria-pressed="false">payoff</button></div></span>
    <span><label>Ratio</label><div class="radios" id="rsrc">
      <button data-v="fired" aria-pressed="true">fired</button>
      <button data-v="universe" aria-pressed="false">universe</button></div></span>
    <span><label for="lookback">Window</label><br>
      <select id="lookback">
        <option value="7">7 days</option>
        <option value="14">14 days</option>
        <option value="30" selected>30 days</option>
        <option value="60">60 days</option>
        <option value="90">90 days</option>
      </select></span>
    <span><label for="candles">Candles back</label><br>
      <select id="candles">
        <option value="20">20</option>
        <option value="40" selected>40</option>
        <option value="80">80</option>
        <option value="150">150</option>
      </select></span>
    <span><label for="minVal">Min strength</label><br>
      <input type="number" id="minVal" value="0" step="1" style="width:110px"></span>
    <span class="surfOnly"><label for="hour">Hour of day</label><br>
      <select id="hour"></select></span>
    <span class="surfOnly"><label for="horizon">Payoff window</label><br>
      <select id="horizon">
        <option value="24">24h</option>
        <option value="48">48h</option>
        <option value="72" selected>72h</option>
        <option value="168">168h</option>
      </select></span>
    <span class="surfOnly"><label for="minprem">Min premium</label><br>
      <select id="minprem">
        <option value="0">all</option>
        <option value="0.25">0.25</option>
        <option value="1">1</option>
        <option value="2" selected>2</option>
        <option value="5">5</option>
      </select></span>
    <span class="surfOnly"><label for="band">Strike band</label><br>
      <select id="band">
        <option value="10">±10%</option>
        <option value="20">±20%</option>
        <option value="30" selected>±30%</option>
        <option value="0">all</option>
      </select></span>
    <span class="timeOnly"><label for="empty">Empty durations</label><br>
      <label style="text-transform:none;letter-spacing:0;font-size:11.5px;color:var(--text);cursor:pointer">
        <input type="checkbox" id="empty" style="vertical-align:-1px"> show</label></span>
  </div>

  <div class="cal">
    <div>
      <div class="calNav">
        <button id="py" title="previous year">◀◀</button>
        <button id="pm" title="previous month">◀</button>
        <span class="m" id="monthLabel">—</span>
        <button id="nm" title="next month">▶</button>
        <button id="ny" title="next year">▶▶</button>
        <button id="latest" title="jump to the most recent settled expiry">latest</button>
      </div>
      <div id="calGrid"></div>
    </div>
    <div class="calSide">
      <div class="pick" id="pickLabel">—</div>
      <div id="pickInfo"></div>
      <div id="calHint" style="margin-top:6px"></div>
    </div>
  </div>

  <div id="pa" class="pa"></div>
  <div id="grids"></div>
  <div class="legend" id="legend"></div>
</div>

<script>
// Sequential scale: pale blue through to orange, ordered by luminance so the
// value reads even without looking at the legend. Shared with 3800 so a colour
// means the same thing on both pages.
const SCALE=['#2b3648','#3a5570','#4d7a91','#6a9d7f','#9db866','#c9b053','#d4823f','#d4703a'];
const PAYOFF_STOPS=${JSON.stringify(PAYOFF_STOPS)};
const DOW=['S','M','T','W','T','F','S'];
const $=id=>document.getElementById(id);
${chart.CLIENT_HELPER}
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

let CAL={days:{},first:null,last:null,count:0};
let DATA={}, SIGNAL=null, PICKED=null, SHADE='count', RSRC='fired';
let LAYOUT='time', SURF=null, PASTATS=null;

/* Colour for a price-action label = P(25x) among TRADEABLE events (filled,
   premium 2-20). NOT the max ratio: the max operator does the work rather than
   the signal, and the biggest ratios sit on 0.55-premium contracts that are one
   tick of noise, so max-shading would glow uniformly and say nothing. */
function colForHit(h){
  if(!(h>0)) return null;
  const lo=0.02, hi=0.06;
  const t=Math.max(0,Math.min(1,(h-lo)/(hi-lo)));
  return SCALE[Math.min(SCALE.length-1,Math.floor(t*(SCALE.length-0.001)))];
}

/* Put the panel beside the click, inside the viewport, on the opposite side so
   it never hides the cell that was just clicked. */
function placePA(el, td){
  const r=td.getBoundingClientRect(), vw=window.innerWidth, vh=window.innerHeight;
  if(r.left + r.width/2 < vw*0.6){ el.style.right='18px'; el.style.left='auto'; }
  else                           { el.style.left='18px';  el.style.right='auto'; }
  const h=el.offsetHeight;
  let top=r.top + r.height/2 - h/2;
  top=Math.max(12, Math.min(vh - h - 12, top));
  el.style.top=top+'px';
}

async function showPA(td){
  if(!PASTATS){ try{ PASTATS=await (await fetch('/api/pa-stats')).json(); }catch(_){ PASTATS={ok:false}; } }
  if(!PASTATS.ok){ return; }
  const iso=td.dataset.ei; if(!iso) return;
  const d=await (await fetch('/api/pa?signal='+encodeURIComponent(SIGNAL)+
    '&spot='+encodeURIComponent($('spot').value)+'&expiry='+encodeURIComponent(td.dataset.e)+
    '&duration='+encodeURIComponent(td.dataset.d||'')+
    '&iso='+encodeURIComponent(iso)+'&type='+encodeURIComponent(td.dataset.ty))).json();
  const syms=td.dataset.s?td.dataset.s.split(' '):[];
  // A real listener, not an inline onclick: the handler lives inside a template
  // literal, so quoting it inline emits bare quotes that terminate the JS string
  // and silently kill the whole script block.
  let h='<span class="x" id="paX" title="close">&times;</span>'+
    '<h4>'+esc(String(iso).slice(0,16).replace('T',' '))+'  ·  '+esc(td.dataset.e)+'</h4>'+
    '<div class="meta">'+(td.dataset.d?esc(td.dataset.d)+'m  ·  ':'')+
    (td.dataset.ty==='C'?'calls':'puts')+'  ·  '+syms.length+' strike'+(syms.length===1?'':'s')+
    '  ·  paid '+fmtR(d.ratio||+td.dataset.r||0)+'</div>';
  if(!d.labels||!d.labels.length){
    h+='<div class="note">No price action recorded for this moment — the sidecar may not cover it. '+
       'Run build_price_action.py.</div>';
  } else {
    // Order matters: what was measured to PREDICT first, then the two axes that
    // were measured and found not to, then description. The headings say which
    // is which so the panel never implies an untested label matters.
    // What the market WAS doing first, then the two rules measured to predict,
    // then everything measured not to. The headings carry the verdict so the
    // panel can never imply an untested label matters.
    const TIERS=[['state','what the 4h chart was doing'],
                 ['measured','MEASURED TO PREDICT — does the signal agree with it?'],
                 ['regime','MEASURED TO PREDICT — the 20-day filter, adds on top'],
                 ['role','structural role — measured, does NOT add'],
                 ['energy','energy at the signal timeframe — measured, INVERTED (louder = worse)'],
                 ['context','context — real, but measured NOT to add on top'],
                 ['structure','structure — bar mechanics, not scored']];
    for(const [tier,head] of TIERS){
      const rows=d.labels.filter(l=>l.tier===tier); if(!rows.length) continue;
      h+='<div class="tier">'+head+'</div>';
      for(const l of rows){
        const bg=tier==='structure'?null:colForHit(l.hit25);
        h+='<div class="row"><span class="sw" style="background:'+(bg||'#2b3648')+'"></span>'+
           esc(l.text)+'<span class="hit">'+(l.hit25!=null?(100*l.hit25).toFixed(2)+'% hit 25x':'')+
           (l.n?'  ·  n='+l.n.toLocaleString():'')+'</span></div>';
      }
    }
    h+='<div class="note">Shade = P(25x) for events carrying that label, over filled trades '+
       'with entry premium 2-20. Only the first tier was measured to predict anything; the '+
       'context tier is descriptive and was tested to add nothing on top of it.</div>';
  }
  const el=$('pa');
  el.innerHTML=h; el.classList.add('on');
  const px=$('paX'); if(px) px.addEventListener('click',()=>el.classList.remove('on'));
  placePA(el, td);
}
let viewY=null, viewM=null;   // month on screen, 0-indexed month

function colFor(n,max){
  if(!n) return null;
  if(max<=1) return SCALE[SCALE.length-1];
  const t=(n-1)/(max-1);
  return SCALE[Math.min(SCALE.length-1,Math.floor(t*(SCALE.length-0.001)))];
}

/** Payoff uses FIXED stops, not a per-grid max, so colour is comparable across
    durations and across dates. A per-grid scale would repaint the same 2x cell
    differently depending on what else happened to be on screen. */
function colForRatio(r){
  if(!(r>0)) return null;
  let i=0; while(i<PAYOFF_STOPS.length && r>=PAYOFF_STOPS[i]) i++;
  return SCALE[Math.min(SCALE.length-1,i)];
}

function fmtR(r){ return r>=10?r.toFixed(0)+'x':r>0?r.toFixed(2)+'x':'—'; }

// ─── Calendar ────────────────────────────────────────────────────────────────

function ymd(y,m,d){
  return y+'-'+String(m+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');
}

function renderCal(){
  if(viewY===null){ $('calGrid').innerHTML=''; return; }
  const first=new Date(Date.UTC(viewY,viewM,1));
  const lead=first.getUTCDay();
  const ndays=new Date(Date.UTC(viewY,viewM+1,0)).getUTCDate();

  // Shade against the busiest day in THIS month. A global max would flatten
  // every quiet month to one colour, which hides exactly the variation the
  // calendar exists to show.
  let mx=0;
  for(let d=1;d<=ndays;d++){
    const s=CAL.days[ymd(viewY,viewM,d)];
    if(s){ const v=SHADE==='payoff'?Math.max(ratOf(s,'C'),ratOf(s,'P')):(s.c+s.p); if(v>mx) mx=v; }
  }

  let h='<table class="cal7"><thead><tr>'+DOW.map(d=>'<th>'+d+'</th>').join('')+'</tr></thead><tbody><tr>';
  for(let i=0;i<lead;i++) h+='<td></td>';
  for(let d=1;d<=ndays;d++){
    if((lead+d-1)%7===0 && d>1) h+='</tr><tr>';
    const key=ymd(viewY,viewM,d), s=CAL.days[key];
    if(!s){ h+='<td>'+d+'</td>'; continue; }
    const v=SHADE==='payoff'?Math.max(ratOf(s,'C'),ratOf(s,'P')):(s.c+s.p);
    const bg=SHADE==='payoff'?colForRatio(v):colFor(v,mx);
    h+='<td class="has'+(key===PICKED?' sel':'')+'" data-d="'+key+'"'+
       (bg?' style="background:'+bg+'"':'')+
       ' title="'+key+' — '+s.c+' call / '+s.p+' put firings, best '+
       fmtR(Math.max(ratOf(s,'C'),ratOf(s,'P')))+'">'+d+'</td>';
  }
  h+='</tr></tbody></table>';
  $('calGrid').innerHTML=h;

  const lo=CAL.first?CAL.first.slice(0,7):null, hi=CAL.last?CAL.last.slice(0,7):null;
  const cur=viewY+'-'+String(viewM+1).padStart(2,'0');
  $('monthLabel').textContent=first.toLocaleString('en',{month:'short',timeZone:'UTC'})+' '+viewY;
  $('pm').disabled=$('py').disabled=(lo!==null && cur<=lo);
  $('nm').disabled=$('ny').disabled=(hi!==null && cur>=hi);

  for(const td of $('calGrid').querySelectorAll('td.has')){
    td.addEventListener('click',()=>{ PICKED=td.dataset.d; renderCal(); load(); });
  }
}

function ratOf(s,side){ return RSRC==='universe'?(side==='C'?s.uc:s.up):(side==='C'?s.fc:s.fp); }

function stepMonth(delta){
  let m=viewM+delta, y=viewY;
  while(m<0){ m+=12; y--; } while(m>11){ m-=12; y++; }
  viewY=y; viewM=m; renderCal();
}

// ─── Grids ───────────────────────────────────────────────────────────────────

function renderGrid(grid,duration,type){
  if(!grid.expiries.length) return '<div class="empty">No settled expiries in this window.</div>';

  const step=Math.max(1,Math.ceil(grid.times.length/14));
  const unit=duration>=1440?(duration/1440)+'d':duration>=60?(duration/60)+'h':duration+'m';

  let h='<div class="gridScroll"><table class="hm"><thead><tr>'+
        '<th class="corner">expiry \\\\ '+esc(unit)+' candles to expiry →</th>';
  grid.times.forEach((t,i)=>{
    h+='<th class="colh">'+((i%step===0||i===grid.times.length-1)?esc(t):'')+'</th>';
  });
  h+='<th class="best">best</th></tr></thead><tbody>';

  grid.expiries.forEach((e,ri)=>{
    h+='<tr><th class="rowh">'+esc(e)+'</th>';
    grid.times.forEach((t,ci)=>{
      const c=grid.cells[ri+','+ci];
      if(!c){ h+='<td class="zero"></td>'; return; }
      const bg=SHADE==='payoff'?colForRatio(c.r):colFor(c.n,grid.max);
      const txt=SHADE==='payoff'?(c.r>0?(c.r>=10?String(Math.round(c.r)):c.r.toFixed(1)):''):c.n;
      h+='<td'+(bg?' style="background:'+bg+'"':' class="zero"')+' data-d="'+duration+'" data-ty="'+type+
         '" data-e="'+esc(e)+'" data-t="'+esc(t)+'" data-n="'+c.n+'" data-r="'+c.r+
         '" data-st="'+esc(c.st||'')+'" data-s="'+esc(c.syms.join(' '))+
         '" data-ei="'+esc(c.iso||'')+'" data-u="'+esc((c.urls||[]).join(' '))+'">'+txt+'</td>';
    });
    const b=grid.rowBest[ri]||0;
    h+='<td class="bestc'+(b>=2?' hit':'')+'">'+fmtR(b)+'</td></tr>';
  });
  return h+'</tbody></table></div><div class="readout"></div>';
}

/* ── Expiry x STRIKE ──────────────────────────────────────────────────────────
   Rows are expiries that had NOT settled at the anchor moment, nearest first.
   Columns are absolute strikes: within one instant every expiry quotes off the
   same spot, so strikes line up across rows without normalising. The moneyness
   each column represents is in the header tooltip, since that is what changes
   between dates.                                                              */
function renderSurface(type,grid,mx,dur){
  const cols=(SURF.cols||{})[type]||[], rows=SURF.rows||[];
  grid=grid||[];
  if(!cols.length) return '<div class="empty">No '+(type==='C'?'calls':'puts')+
    ' on the board at this moment.</div>';
  const px=SURF.spotPx, step=Math.max(1,Math.ceil(cols.length/18));

  let h='<div class="gridScroll"><table class="hm"><thead><tr>'+
        '<th class="corner">expiry / strike →</th>';
  cols.forEach((k,i)=>{
    const m=px?((k-px)/px*100):null;
    const lab=(i%step===0||i===cols.length-1)
      ? (k>=1000?(Math.round(k/100)/10)+'k':String(k)) : '';
    h+='<th class="colh" title="'+k+(m==null?'':'  ('+(m>=0?'+':'')+m.toFixed(1)+'% from spot)')+
       '">'+lab+'</th>';
  });
  h+='</tr></thead><tbody>';

  rows.forEach((r,ri)=>{
    h+='<tr><th class="rowh" title="'+r.tte.toFixed(0)+'h to expiry">'+esc(r.expiry)+'</th>';
    (grid[ri]||[]).forEach((c,ci)=>{
      if(!c){ h+='<td class="zero"></td>'; return; }
      const bg=SHADE==='payoff'?colForRatio(c.peak):colFor(c.n,mx);
      const txt=SHADE==='payoff'
        ? (c.peak>0?(c.peak>=10?String(Math.round(c.peak)):c.peak.toFixed(1)):'')
        : (c.n||'');
      h+='<td'+(bg?' style="background:'+bg+'"':' class="zero"')+
         ' data-sk="1" data-d="'+(dur||'')+'" data-ty="'+type+'" data-e="'+esc(r.expiry)+'" data-t="'+r.tte.toFixed(0)+
         '" data-k="'+cols[ci]+'" data-n="'+(c.n||0)+'" data-r="'+(c.peak||0)+
         '" data-en="'+(c.entry||0)+'" data-du="'+(c.ratio||0)+
         '" data-s="'+esc((c.syms||[]).join(' '))+
         '" data-ei="'+esc(c.iso||'')+'" data-u="'+esc((c.urls||[]).join(' '))+'">'+txt+'</td>';
    });
    h+='</tr>';
  });
  return h+'</tbody></table></div><div class="readout"></div>';
}

function renderSurfaceAll(){
  if(!PICKED){ $('grids').innerHTML='<div class="empty">Pick a date on the calendar — it is the moment the move starts.</div>'; return; }
  if(!SURF||!SURF.rows||!SURF.rows.length){
    $('grids').innerHTML='<div class="empty">No expiry was still live on '+esc(PICKED)+
      ', or no option candles are stored for that moment.</div>'; return; }

  const nC=(SURF.cols.C||[]).length, nP=(SURF.cols.P||[]).length;
  let h='';
  if(!SURF.spotPx) h+='<div class="note">No spot candle at this moment, so the strike '+
    'headers carry no moneyness and the band filter was skipped.</div>';
  if(SURF.minPremium>0) h+='<div class="note">Contracts marked below '+SURF.minPremium+
    ' at entry are hidden. A 0.5 premium ticking to 11 is a 20x nobody could trade — '+
    'set "min premium" to <b>all</b> to see them.</div>';

  const head=extra=>'<span class="c">'+SURF.rows.length+' live expiries</span>'+
    '<span class="c">'+nC+' call / '+nP+' put strikes</span>'+
    (SURF.spotPx?'<span class="c">spot '+Math.round(SURF.spotPx).toLocaleString()+'</span>':'')+extra;

  if(SHADE==='payoff'){
    // The payoff layer is read off 60m candles, so it has no duration to split
    // by — every contract on the board gets one number whether anything fired on
    // it or not. Splitting it per duration would render N identical grids.
    h+='<div class="durRow"><div class="durHead"><span class="d">payoff</span>'+
       head('<span class="c">peak over +'+SURF.horizonHours+'h</span>'+
            '<span class="c">best '+fmtR(SURF.max.payoff)+'</span>'+
            '<span class="c">'+SURF.scanned.files+' contracts scanned</span>'+
            '<span class="c">every contract, fired or not — no duration split</span>')+'</div>'+
       '<div class="pair">'+
         '<div class="pane"><div class="t">Calls</div>'+renderSurface('C',SURF.grid.C,0,'')+'</div>'+
         '<div class="pane"><div class="t">Puts</div>'+renderSurface('P',SURF.grid.P,0,'')+'</div>'+
       '</div></div>';
  } else if(!SURF.boards||!SURF.boards.length){
    h+='<div class="empty">Nothing entered on '+esc(PICKED)+' on any duration at or '+
       'above the 30m floor. Pick another date, or switch "shade by" to payoff to see '+
       'the board anyway.</div>';
  } else {
    // Longest duration first, same order as the time-axis view.
    SURF.boards.slice().reverse().forEach(b=>{
      h+='<div class="durRow"><div class="durHead"><span class="d">'+b.duration+'m</span>'+
         head('<span class="c">'+b.total.C+' call / '+b.total.P+' put strike-firings on '+
              esc(PICKED)+'</span>'+
              '<span class="c">peak '+b.max+' in one cell</span>')+'</div>'+
         '<div class="pair">'+
           '<div class="pane"><div class="t">Calls</div>'+renderSurface('C',b.grid.C,b.max,b.duration)+'</div>'+
           '<div class="pane"><div class="t">Puts</div>'+renderSurface('P',b.grid.P,b.max,b.duration)+'</div>'+
         '</div></div>';
    });
  }
  $('grids').innerHTML=h;

  for(const td of document.querySelectorAll('table.hm td[data-sk]')){
    td.addEventListener('click',()=>showPA(td));
    td.addEventListener('mouseenter',()=>{
      const out=td.closest('.pane').querySelector('.readout');
      const syms=td.dataset.s?td.dataset.s.split(' '):[];
      const n=+td.dataset.n, en=+td.dataset.en;
      out.innerHTML='<b>strike '+(+td.dataset.k).toLocaleString()+'</b>'+
        '  ·  exp '+esc(td.dataset.e)+'  ·  '+td.dataset.t+'h to expiry'+
        '  ·  '+(td.dataset.ty==='C'?'call':'put')+
        (en?'  ·  premium '+en.toFixed(2)+' at entry':'')+
        '  ·  peak '+fmtR(+td.dataset.r)+
        '  ·  '+(n?n+' firing'+(n===1?'':'s')+(td.dataset.du?', signal ratio '+fmtR(+td.dataset.du):''):'no firing')+
        '<div class="syms">'+symLinks(syms,td.dataset.u?td.dataset.u.split(' '):[])+'</div>';
    });
  }
}

function renderAll(){
  if(LAYOUT==='strike') return renderSurfaceAll();
  const grids=DATA.grids||[];
  const nExp=(DATA.expiries||[]).length;

  if(!PICKED){ $('grids').innerHTML='<div class="empty">Pick a date on the calendar.</div>'; return; }
  if(!nExp){ $('grids').innerHTML='<div class="empty">No expiry settled in this window.</div>'; return; }
  if(!grids.length){
    $('grids').innerHTML='<div class="empty">'+nExp+' settled '+(nExp===1?'expiry':'expiries')+
      ', but no firing landed inside the last '+($('candles').value||40)+
      ' candles before settlement on any duration. Widen "candles back", or tick '+
      '"show empty durations" to see the grids anyway.</div>';
    return;
  }

  let h='';
  if(DATA.window&&DATA.window.capped) h+='<div class="note">Showing the '+nExp+
    ' most recent settled expiries in this window — the cap is for legibility, widen it in the source if you need more.</div>';
  if(DATA.hidden) h+='<div class="note">'+DATA.hidden+
    ' duration'+(DATA.hidden===1?'':'s')+' hidden — nothing fired in the window.</div>';

  grids.forEach(row=>{
    const best=Math.max(row.C.maxRatio||0,row.P.maxRatio||0);
    h+='<div class="durRow"><div class="durHead"><span class="d">'+row.duration+'m</span>'+
       '<span class="c">'+row.C.total+' call strike-firings · '+row.P.total+' put strike-firings</span>'+
       '<span class="c">peak '+Math.max(row.C.max,row.P.max)+' strikes in one cell</span>'+
       '<span class="c">best '+fmtR(best)+'</span>'+
       '<span class="c">'+row.C.expiries.length+' settled expiries</span></div>'+
       '<div class="pair">'+
         '<div class="pane"><div class="t">Calls</div>'+renderGrid(row.C,row.duration,'C')+'</div>'+
         '<div class="pane"><div class="t">Puts</div>'+renderGrid(row.P,row.duration,'P')+'</div>'+
       '</div></div>';
  });
  $('grids').innerHTML=h;

  for(const td of document.querySelectorAll('table.hm td[data-n]')){
    td.addEventListener('click',()=>showPA(td));
    td.addEventListener('mouseenter',()=>{
      const out=td.closest('.pane').querySelector('.readout');
      const syms=td.dataset.s?td.dataset.s.split(' '):[];
      out.innerHTML='<b>'+td.dataset.n+' strike'+(td.dataset.n==='1'?'':'s')+'</b>'+
        '  ·  paid '+fmtR(+td.dataset.r)+(td.dataset.st?'  ·  '+esc(td.dataset.st):'')+
        '  ·  '+td.dataset.d+'m  ·  '+(td.dataset.ty==='C'?'calls':'puts')+
        '  ·  exp '+esc(td.dataset.e)+'  ·  '+esc(td.dataset.t)+' to expiry'+
        '<div class="syms">'+symLinks(syms,td.dataset.u?td.dataset.u.split(' '):[])+
        (syms.length<+td.dataset.n?'  … +'+(+td.dataset.n-syms.length)+' more':'')+'</div>';
    });
  }
}

function renderLegend(){
  const items=SHADE==='payoff'
    ? SCALE.map((c,i)=>{
        const lo=i===0?'<1x':(PAYOFF_STOPS[i-1]+'x');
        return '<span class="k"><span class="sw" style="background:'+c+'"></span>'+lo+'</span>';
      })
    : SCALE.map((c,i)=>'<span class="k"><span class="sw" style="background:'+c+'"></span>'+
        (i===0?'few':(i===SCALE.length-1?'many':''))+'</span>');
  const what=SHADE==='payoff'?'payoff reached':(LAYOUT==='strike'?'firings on this strike':'strikes fired');
  $('legend').innerHTML='<span class="k">'+what+'</span>'+
    items.join('')+'<span class="k" style="margin-left:8px">hover a cell for the instruments</span>';
}

// ─── Load ────────────────────────────────────────────────────────────────────

function applyLayoutVis(){
  document.querySelectorAll('.surfOnly').forEach(e=>e.style.display=LAYOUT==='strike'?'':'none');
  document.querySelectorAll('.timeOnly').forEach(e=>e.style.display=LAYOUT==='strike'?'none':'');
}

async function loadSurface(){
  SURF=await (await fetch('/api/surface/'+encodeURIComponent(SIGNAL)+'/'+
    encodeURIComponent($('spot').value)+'?date='+encodeURIComponent(PICKED)+
    '&hour='+encodeURIComponent($('hour').value||0)+
    '&horizon='+encodeURIComponent($('horizon').value||72)+
    '&minprem='+encodeURIComponent($('minprem').value||0)+
    '&band='+encodeURIComponent($('band').value||30))).json();
  renderAll(); renderLegend();
}

async function load(){
  if(!SIGNAL||!PICKED){ renderAll(); return; }
  if(LAYOUT==='strike'){
    $('pickLabel').textContent=PICKED;
    $('pickInfo').innerHTML='Board as it stood on this date. Rows are expiries that had '+
      'not settled yet; columns are strikes. <b>Firings shown are only those that '+
      'entered on this calendar day</b> — one firing belongs to exactly one date. '+
      'The payoff window runs forward from the chosen hour.';
    return loadSurface();
  }
  const s=CAL.days[PICKED];
  $('pickLabel').textContent=PICKED;
  $('pickInfo').innerHTML=s
    ? '<b>'+s.c+'</b> call and <b>'+s.p+'</b> put firings on this expiry · best call '+
      fmtR(ratOf(s,'C'))+', best put '+fmtR(ratOf(s,'P'))
    : 'No expiry settled on this date — it is still a valid window end.';

  DATA=await (await fetch('/api/grids/'+encodeURIComponent(SIGNAL)+'/'+
    encodeURIComponent($('spot').value)+'?date='+encodeURIComponent(PICKED)+
    '&lookback='+encodeURIComponent($('lookback').value||30)+
    '&candles='+encodeURIComponent($('candles').value||40)+
    '&min='+encodeURIComponent($('minVal').value||0)+
    '&ratio='+encodeURIComponent(RSRC)+
    '&empty='+($('empty').checked?'1':'0'))).json();
  renderAll();
}

async function loadCalendar(){
  CAL=await (await fetch('/api/calendar/'+encodeURIComponent(SIGNAL)+'/'+
    encodeURIComponent($('spot').value))).json();

  $('calHint').innerHTML=CAL.count
    ? CAL.count.toLocaleString()+' settled expiries · '+CAL.first+' to '+CAL.last+
      '<br>Shaded days had an expiry settle. The pick is the END of the window.'
    : 'No settled expiries for this signal and spot.';

  PICKED = CAL.last || null;
  if(PICKED){ viewY=+PICKED.slice(0,4); viewM=+PICKED.slice(5,7)-1; }
  else { viewY=null; viewM=null; }
  renderCal();
  await load();
}

function toggle(barId,cur,set){
  $(barId).addEventListener('click',async e=>{
    const b=e.target.closest('button[data-v]'); if(!b) return;
    set(b.dataset.v);
    $(barId).querySelectorAll('button').forEach(x=>
      x.setAttribute('aria-pressed',String(x.dataset.v===cur())));
  });
}

(async function init(){
  renderLegend();

  const sigs=await (await fetch('/api/signals')).json();
  if(!sigs.length){ $('grids').innerHTML='<div class="empty">No signal data. Run backfill.js --signals-only.</div>'; return; }
  SIGNAL=sigs[0];
  $('sigs').innerHTML=sigs.map(s=>'<button data-s="'+esc(s)+'" aria-pressed="'+(s===SIGNAL)+'">'+esc(s)+'</button>').join('');
  $('sigs').addEventListener('click',async e=>{
    const b=e.target.closest('button[data-s]'); if(!b) return;
    SIGNAL=b.dataset.s;
    $('sigs').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.s===SIGNAL)));
    const spots=await (await fetch('/api/spots/'+encodeURIComponent(SIGNAL))).json();
    $('spot').innerHTML=spots.map(s=>'<option>'+esc(s)+'</option>').join('');
    await loadCalendar();
  });

  toggle('shade',()=>SHADE,v=>{ SHADE=v; renderLegend(); renderCal(); renderAll(); });
  toggle('rsrc', ()=>RSRC, v=>{ RSRC=v; renderCal(); load(); });
  toggle('layout',()=>LAYOUT,v=>{ LAYOUT=v; applyLayoutVis(); renderLegend(); load(); });

  $('hour').innerHTML=Array.from({length:24},(_,i)=>
    '<option value="'+i+'"'+(i===0?' selected':'')+'>'+String(i).padStart(2,'0')+':00</option>').join('');
  $('hour').addEventListener('change',load);
  $('horizon').addEventListener('change',load);
  $('minprem').addEventListener('change',load);
  $('band').addEventListener('change',load);
  applyLayoutVis();

  const spots=await (await fetch('/api/spots/'+encodeURIComponent(SIGNAL))).json();
  $('spot').innerHTML=spots.map(s=>'<option>'+esc(s)+'</option>').join('');
  $('spot').addEventListener('change',loadCalendar);
  $('lookback').addEventListener('change',load);
  $('candles').addEventListener('change',load);
  $('minVal').addEventListener('change',load);
  $('empty').addEventListener('change',load);
  $('pm').addEventListener('click',()=>stepMonth(-1));
  $('nm').addEventListener('click',()=>stepMonth(1));
  $('py').addEventListener('click',()=>stepMonth(-12));
  $('ny').addEventListener('click',()=>stepMonth(12));
  $('latest').addEventListener('click',()=>{
    if(!CAL.last) return;
    PICKED=CAL.last; viewY=+PICKED.slice(0,4); viewM=+PICKED.slice(5,7)-1;
    renderCal(); load();
  });

  await loadCalendar();
})();
</script>
</body>
</html>`;
}

// ─── Server ───────────────────────────────────────────────────────────────────

function json(res, b) {
    const s = JSON.stringify(b);
    res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(s) });
    res.end(s);
}

// ─── Startup self-check ───────────────────────────────────────────────────────
// The whole UI lives in one <script> block built by string concatenation inside
// a template literal. One stray quote makes the browser discard the ENTIRE block
// and the page renders with empty dropdowns and no error — which is exactly what
// happened on 2026-09-16 when an inline onclick emitted bare quotes. The server
// was fine, every API worked, and the page was dead.
//
// HANDOFF 3.7: a stage that can do zero work must say so loudly. So parse the
// emitted script at boot and refuse to pretend everything is fine.
function selfCheck() {
    try {
        const m = /<script>([\s\S]*?)<\/script>/.exec(renderPage());
        if (!m) { console.error('SELF-CHECK: no <script> block found in the page'); return false; }
        new Function(m[1]);          // parse only, never executed here
        return true;
    } catch (err) {
        console.error('\n!!! SELF-CHECK FAILED — the client script does not parse !!!');
        console.error('    ' + err.message);
        console.error('    The page will load but every control will be dead.\n');
        return false;
    }
}

http.createServer((req, res) => {
    const [rawPath, rawQuery] = req.url.split('?');
    const url = decodeURIComponent(rawPath);
    const q = new URLSearchParams(rawQuery || '');

    try {
        if (url === '/' || url === '/index.html') {
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
            return res.end(renderPage());
        }
        if (url === '/api/signals') return json(res, listSignals());
        if (url === '/api/pa-stats') return json(res, { ok: pa.available(), stats: pa.stats() });
        if (url === '/api/pa') {
            const hit = pa.lookup(q.get('signal'), q.get('spot'), q.get('expiry'),
                                  q.get('duration'), q.get('iso'), q.get('type'));
            return json(res, hit || { labels: [] });
        }

        let m = url.match(/^\/api\/spots\/([^/]+)$/);
        if (m) return json(res, listSpots(m[1]));

        m = url.match(/^\/api\/calendar\/([^/]+)\/([^/]+)$/);
        if (m) return json(res, calendar(m[1], m[2]));

        // Expiry x STRIKE board, anchored on a chosen moment. Different question
        // from /api/grids, which is expiry x time — see the header comment.
        m = url.match(/^\/api\/surface\/([^/]+)\/([^/]+)$/);
        if (m) {
            const date = q.get('date') || '';
            if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return json(res, null);
            const hour = Math.min(23, Math.max(0, parseInt(q.get('hour')) || 0));
            const ts = Math.floor(new Date(date + 'T00:00:00+05:30').getTime() / 1000) + hour * 3600;
            return json(res, surfaceMod.buildSurface(m[2], ts, {
                signalId:     m[1],
                horizonHours: parseInt(q.get('horizon')) || 72,
                bandPct:      parseFloat(q.get('band')),
                minPremium:   parseFloat(q.get('minprem')) || 0,
                minDuration:  MIN_DURATION_MINUTES,
                withPayoff:   true,
            }));
        }

        m = url.match(/^\/api\/grids\/([^/]+)\/([^/]+)$/);
        if (m) {
            const date = q.get('date') || '';
            if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return json(res, { expiries: [], grids: [], hidden: 0 });
            return json(res, buildAll(m[1], m[2], date, {
                lookbackDays: parseInt(q.get('lookback')) || 30,
                candlesBack:  parseInt(q.get('candles'))  || DEFAULT_CANDLES_BACK,
                minValue:     parseFloat(q.get('min'))    || 0,
                ratioSource:  q.get('ratio') === 'universe' ? 'universe' : 'fired',
                showEmpty:    q.get('empty') === '1',
            }));
        }

        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, '0.0.0.0', () => {
    selfCheck();
    console.log(netinfo.banner('Settled signal heatmaps — expiry × time to expiry', PORT, [
        `signals : ${listSignals().join(', ') || '(none)'}`,
        `layouts : expiry x time-to-expiry, and expiry x strike (board as of a date)`,
        `sibling : serve_grids.js on 3800 covers LIVE expiries`,
    ]));
});
