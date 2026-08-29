// serve_signals.js
// ─────────────────────────────────────────────────────────────────────────────
// Lightweight viewer for the signals directory. No dependencies, no build step.
//
//   node serve_signals.js            → http://localhost:3100
//   node serve_signals.js --port 4000
//
// WHY A SERVER RATHER THAN A STATIC FILE
// A full history runs to roughly 128k merged ranges (~25 MB of JSON). Embedding
// that in one HTML file makes the page slow to open and slower to scroll. Here
// the tree (durations and expiries with counts) loads immediately and the ranges
// for a given expiry are fetched only when that section is expanded, so the DOM
// stays small no matter how much history is stored.
//
// PAST EXPIRIES ONLY. Live expiries are all 'pending' with signalRatio 0, so
// including them would dilute every percentage with unknowable outcomes.
//
// API
//   GET /                                  the page
//   GET /api/spots                         ["BTC", ...]
//   GET /api/tree/:spot                    durations, expiries, counts, heat matrix
//   GET /api/ranges/:spot/:dur/:expiry     the merged ranges for one section
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg  = require('./config');
const netinfo = require('./netinfo');
const api  = require('./api');
const expiryMod = require('./expiry');

// ─── Config ───────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3100;
const SIGNAL_ID = args.includes('--signal') ? args[args.indexOf('--signal') + 1] : 'red_squeeze';

// Your charting app.
// Host-relative. Hardcoding localhost meant a chart link opened on a phone
// resolved to the PHONE, so every link 404'd off the LAN. The page substitutes
// its own hostname client-side.
const CHART_HOST_PLACEHOLDER = '__CHART_HOST__';
const CHART_BASE = `http://${CHART_HOST_PLACEHOLDER}:3000/de`;

// Candles of lead-in before the pattern starts, so the chart opens with context
// rather than exactly on the first red candle.
const CHART_LEAD_CANDLES = 20;

// Minutes past settlement for the chart's end bound. Settlement is 17:30 IST,
// so the default 30 gives the 18:00 in your example.
const CHART_TAIL_MINUTES = 30;

// Bands and thresholds all live in config.js so quality.js and this page can
// never drift apart. Adding a 20x column is a one-line edit there.
const RATIO_BANDS    = cfg.RATIO_BANDS;
// Bands are per-signal: signalValue is on a different scale in each.
const STRENGTH_BANDS = cfg.strengthBandsFor(SIGNAL_ID);
const THRESHOLDS     = cfg.MULTIBAGGER_THRESHOLDS;

function bandIndex(bands, v) {
    const n = Number(v) || 0;
    for (let i = 0; i < bands.length; i++) {
        if (n >= bands[i].min && n < bands[i].max) return i;
    }
    return bands.length - 1;
}

// ─── Reading the signals directory ────────────────────────────────────────────

const signalRoot = () => path.join(cfg.SIGNALS_BASE_DIR, SIGNAL_ID);

function listSpots() {
    const root = signalRoot();
    if (!fs.existsSync(root)) return [];
    return fs.readdirSync(root)
        .filter(d => !d.startsWith('.') && fs.statSync(path.join(root, d)).isDirectory())
        .sort();
}

function listDurations(spot) {
    const dir = path.join(signalRoot(), spot);
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
        .filter(d => !d.startsWith('.') && !isNaN(d))
        .map(Number)
        .sort((a, b) => a - b);
}

/** Past expiries only, newest first. */
function listExpiries(spot, duration) {
    const dir = path.join(signalRoot(), spot, String(duration));
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
        .filter(f => !f.startsWith('.') && f.endsWith('.json'))
        .map(f => f.replace(/\.json$/, ''))
        .filter(e => expiryMod.isExpired(spot, e))
        .sort()
        .reverse();
}

function readRanges(spot, duration, expiry) {
    const file = path.join(signalRoot(), spot, String(duration), `${expiry}.json`);
    if (!fs.existsSync(file)) return { C: [], P: [] };
    try {
        return JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (err) {
        console.error(`Unreadable: ${file} — ${err.message}`);
        return { C: [], P: [] };
    }
}

// ─── Chart URL ────────────────────────────────────────────────────────────────

/**
 * Build a URL into the charting app for one instrument of one range.
 *
 *   {CHART_BASE}/{expiry}/{symbol}/{from}/{to}/{durationMinutes}
 *
 * from — the range's start, pulled back CHART_LEAD_CANDLES so the squeeze has
 *        visible context before it rather than starting hard on the first candle.
 * to   — settlement plus CHART_TAIL_MINUTES, resolved per spot so a spot that
 *        settles at a different hour gets its own bound.
 */
function chartUrl(spot, expiry, symbol, startTs, durationMins) {
    const fromMs = new Date(startTs).getTime() - CHART_LEAD_CANDLES * durationMins * 60000;
    const from   = api.formatTs(Math.floor(fromMs / 1000));

    const toMs = expiryMod.expiryMillis(spot, expiry) + CHART_TAIL_MINUTES * 60000;
    const to   = api.formatTs(Math.floor(toMs / 1000));

    return `${CHART_BASE}/${expiry}/${symbol}/${from}/${to}/${durationMins}`;
}

// ─── Tree + heat matrix ───────────────────────────────────────────────────────

/**
 * Everything the page needs before any section is expanded: per-duration and
 * per-expiry counts, plus the strength × ratio matrix across the whole spot.
 */
function buildTree(spot) {
    // Two matrices, one per ratio definition, so the page can toggle between
    // "what the firing instrument paid" and "what was available anywhere".
    const matrix     = STRENGTH_BANDS.map(() => RATIO_BANDS.map(() => 0));
    const matrixUniv = STRENGTH_BANDS.map(() => RATIO_BANDS.map(() => 0));
    // Row totals, so the page can turn per-threshold counts into percentages.
    const rowTotals  = STRENGTH_BANDS.map(() => 0);
    const durations = [];

    let grandTotal = 0;

    for (const dur of listDurations(spot)) {
        const expiries = [];
        let durTotal = 0;
        const dHits  = { fired: {}, univ: {} };
        for (const t of THRESHOLDS) { dHits.fired[t] = 0; dHits.univ[t] = 0; }

        for (const expiry of listExpiries(spot, dur)) {
            const data = readRanges(spot, dur, expiry);
            const all  = [...(data.C || []), ...(data.P || [])];
            if (all.length === 0) continue;

            // Counts per threshold, for both payoff definitions. Sending all of
            // them means switching threshold or source is instant in the browser
            // with no refetch.
            const eHits = { fired: {}, univ: {} };
            for (const t of THRESHOLDS) { eHits.fired[t] = 0; eHits.univ[t] = 0; }

            for (const r of all) {
                const sBand  = bandIndex(STRENGTH_BANDS, r[3]);
                const fired  = Number(r[4]) || 0;
                const univ   = Number(r[7]) || 0;

                matrix[sBand][bandIndex(RATIO_BANDS, fired)]++;
                matrixUniv[sBand][bandIndex(RATIO_BANDS, univ)]++;
                rowTotals[sBand]++;

                for (const t of THRESHOLDS) {
                    if (fired >= t) eHits.fired[t]++;
                    if (univ  >= t) eHits.univ[t]++;
                }
            }

            expiries.push({ expiry, total: all.length, hits: eHits });
            durTotal += all.length;
            for (const t of THRESHOLDS) {
                dHits.fired[t] += eHits.fired[t];
                dHits.univ[t]  += eHits.univ[t];
            }
        }

        if (durTotal === 0) continue;
        durations.push({ duration: dur, total: durTotal, hits: dHits, expiries });
        grandTotal += durTotal;
    }

    return {
        spot,
        grandTotal,
        durations,
        matrix,
        matrixUniv,
        rowTotals,
        thresholds:        THRESHOLDS,
        defaultThreshold:  cfg.DEFAULT_HEADLINE_THRESHOLD,
        defaultSource:     cfg.DEFAULT_RATIO_SOURCE === 'fired' ? 'fired' : 'univ',
        universeMode:      cfg.UNIVERSE_MAX_MODE,
        // Strength band edges, so clicking a row can set the min-strength filter.
        strengthMins:  STRENGTH_BANDS.map(b => b.min),
        ratioMins:     RATIO_BANDS.map(b => b.min),
        strengthBands: STRENGTH_BANDS.map(b => b.label),
        ratioBands:    RATIO_BANDS.map(b => b.label),
    };
}

/** Ranges for one section, decorated with band indices and chart links. */
function buildRanges(spot, duration, expiry) {
    const data = readRanges(spot, duration, expiry);
    const out  = { C: [], P: [] };

    for (const type of ['C', 'P']) {
        const rows = (data[type] || []).map(r => {
            const [startTs, endTs, count, signalValue, ratio, state, instruments,
                   univRatio, univSymbol] = r;
            const uRatio = Number(univRatio) || 0;
            return {
                startTs, endTs, count,
                signalValue: Number(signalValue) || 0,
                ratio:       Number(ratio) || 0,
                state,
                strengthBand: bandIndex(STRENGTH_BANDS, signalValue),
                ratioBand:    bandIndex(RATIO_BANDS, ratio),
                univRatio:    uRatio,
                univBand:     bandIndex(RATIO_BANDS, uRatio),
                // The instrument that reached universeMaxRatio gets its own chart
                // link: it is usually NOT one of the firing instruments.
                univSymbol:   univSymbol || null,
                univUrl:      univSymbol ? chartUrl(spot, expiry, univSymbol, startTs, duration) : null,
                instruments: (instruments || []).map(sym => ({
                    symbol: sym,
                    url:    chartUrl(spot, expiry, sym, startTs, duration),
                })),
            };
        });

        // Biggest payoff first — the winners are what you came to look at.
        rows.sort((a, b) => b.ratio - a.ratio);
        out[type] = rows;
    }

    return out;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal review — ${SIGNAL_ID}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --ground:  #14161c;
    --surface: #1c1f28;
    --raised:  #242833;
    --line:    #2e3340;
    --text:    #c8ccd8;
    --muted:   #6b7183;
    --accent:  #d4703a;

    /* Ratio scale — cool to warm. What the trade actually paid. */
    --r0: #3d4454;
    --r1: #5b7c99;
    --r2: #6a9d7f;
    --r3: #b8a44c;
    --r4: #d4703a;

    /* Strength scale — violet ramp. What the signal claimed beforehand.
       Deliberately a different hue family so the two boxes never read as
       the same measurement. */
    --s0: #34304a;
    --s1: #464067;
    --s2: #5d5488;
    --s3: #7a6cae;
    --s4: #9d8bd4;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--ground);
    color: var(--text);
    font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
    font-size: 13px;
    line-height: 1.5;
  }

  h1, h2, .display { font-family: 'Space Grotesk', system-ui, sans-serif; }

  .wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 80px; }

  /* ── Chrome ── */
  header {
    display: flex; flex-wrap: wrap; gap: 16px; align-items: baseline;
    padding-bottom: 18px; border-bottom: 1px solid var(--line); margin-bottom: 26px;
  }
  h1 { font-size: 19px; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
  h1 .sig { color: var(--accent); }
  .sub { color: var(--muted); font-size: 12px; }

  .controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: center; margin-left: auto; }
  .toggle { display: inline-flex; border: 1px solid var(--line); border-radius: 3px; overflow: hidden; }
  .toggle button {
    background: var(--surface); color: var(--muted); border: 0; cursor: pointer;
    font-family: inherit; font-size: 11px; padding: 5px 9px;
  }
  .toggle button[aria-pressed=true] { background: var(--raised); color: var(--text); }
  .toggle button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }
  select, input[type=number] {
    background: var(--surface); color: var(--text);
    border: 1px solid var(--line); border-radius: 3px;
    padding: 5px 8px; font-family: inherit; font-size: 12px;
  }
  select:focus, input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  input[type=number] { width: 62px; }

  /* ── Heat matrix: the page's thesis ── */
  .thesis { margin-bottom: 30px; }
  .thesis h2 { font-size: 15px; margin: 0 0 4px; font-weight: 700; }
  .thesis .q { color: var(--muted); font-size: 12px; margin-bottom: 14px; }

  table.matrix { border-collapse: collapse; }
  table.matrix th, table.matrix td {
    padding: 7px 11px; text-align: right; font-size: 12px;
    border: 1px solid var(--ground);
  }
  table.matrix th { color: var(--muted); font-weight: 500; font-size: 11px; }
  table.matrix th.rowhead { text-align: left; }
  table.matrix td { font-variant-numeric: tabular-nums; color: #0d0f14; font-weight: 700; }
  table.matrix td.zero { background: var(--surface) !important; color: var(--muted); font-weight: 400; }
  .axis { color: var(--muted); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; }

  /* Cumulative "% reached at least Nx" columns, one per MULTIBAGGER_THRESHOLD.
     Clicking any of them filters the sections below to exactly that slice. */
  table.matrix th.thr, table.matrix td.thr {
    background: var(--surface); color: var(--text); font-weight: 500;
    border-left: 1px solid var(--line); cursor: pointer;
  }
  table.matrix th.thr:first-of-type, table.matrix td.thr.first { border-left: 2px solid var(--line); }
  table.matrix th.thr:hover, table.matrix td.thr:hover { background: var(--raised); color: var(--accent); }
  table.matrix th.thr.on, table.matrix td.thr.on { background: var(--raised); color: var(--accent); font-weight: 700; }
  table.matrix td.thr small { color: var(--muted); font-weight: 400; }

  .active-filter {
    display: none; align-items: center; gap: 10px; margin-top: 12px;
    padding: 7px 11px; background: var(--surface);
    border-left: 2px solid var(--accent); border-radius: 0 3px 3px 0; font-size: 12px;
  }
  .active-filter.on { display: inline-flex; }
  .active-filter button {
    background: transparent; border: 1px solid var(--line); color: var(--muted);
    border-radius: 3px; padding: 2px 8px; font-family: inherit; font-size: 11px; cursor: pointer;
  }
  .active-filter button:hover { color: var(--accent); border-color: var(--accent); }

  /* ── Expiry x duration grid ──
     The tree is organised duration -> expiry, which is the wrong way round for
     "which expiries produced the big multiples". This pivots it: one row per
     expiry, one column per duration, so an outlier expiry is visible at a
     glance instead of requiring dozens of sections to be opened. */
  .grid-wrap {
    max-height: 430px; overflow: auto; border: 1px solid var(--line);
    border-radius: 3px; background: var(--surface);
  }
  table.grid { border-collapse: separate; border-spacing: 0; font-size: 11px; width: 100%; }

  table.grid th {
    position: sticky; top: 0; z-index: 3;
    background: var(--raised); color: var(--muted);
    font-weight: 500; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
    padding: 6px 7px; text-align: right; white-space: nowrap;
    border-bottom: 1px solid var(--line); cursor: pointer;
  }
  table.grid th:hover { color: var(--accent); }
  table.grid th.sorted { color: var(--accent); }

  /* Expiry label stays visible while scrolling sideways through durations. */
  table.grid th.exp-col, table.grid td.exp-col {
    position: sticky; left: 0; z-index: 2;
    background: var(--surface); text-align: left;
    border-right: 1px solid var(--line);
  }
  table.grid th.exp-col { z-index: 4; background: var(--raised); }

  table.grid td {
    padding: 3px 7px; text-align: right; white-space: nowrap;
    font-variant-numeric: tabular-nums; color: var(--text);
    border-bottom: 1px solid rgba(46,51,64,0.4);
  }
  table.grid td.hit { cursor: pointer; color: #0d0f14; font-weight: 700; }
  table.grid td.hit:hover { outline: 1px solid var(--accent); outline-offset: -1px; }
  table.grid td.nil { color: #3a3f4d; }
  table.grid td.total { font-weight: 700; border-left: 1px solid var(--line); }
  table.grid tr:hover td.exp-col { color: var(--accent); }

  .grid-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
  .grid-head h2 { font-size: 15px; margin: 0; font-weight: 700; }
  .grid-head .q { color: var(--muted); font-size: 12px; }

  /* ── Collapsible sections ── */
  details { border-top: 1px solid var(--line); }
  details > summary {
    cursor: pointer; padding: 10px 4px; list-style: none;
    display: flex; gap: 14px; align-items: baseline;
  }
  details > summary::-webkit-details-marker { display: none; }
  details > summary:hover { background: var(--surface); }
  details > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  summary .caret { color: var(--muted); width: 10px; display: inline-block; }
  details[open] > summary > .caret::before { content: '▾'; }
  details:not([open]) > summary > .caret::before { content: '▸'; }

  .dur-name { font-weight: 700; min-width: 70px; }
  .exp-name { min-width: 110px; }
  .count { color: var(--muted); }
  .hit { color: var(--r3); }

  .lvl2 { margin-left: 22px; }
  .lvl3 { margin-left: 22px; padding: 2px 0 10px; }

  /* ── Signal table ──
     A real table so every value sits under a labelled column. The previous
     layout was a bare sequence of chips, which meant you had to remember the
     schema to read a row. */
  table.signals { border-collapse: collapse; width: 100%; font-size: 11.5px; }

  table.signals thead th {
    position: sticky; top: 0; z-index: 2;
    background: var(--raised); color: var(--muted);
    font-weight: 500; font-size: 10px; letter-spacing: 0.07em; text-transform: uppercase;
    text-align: left; padding: 6px 8px; white-space: nowrap;
    border-bottom: 1px solid var(--line); cursor: help;
  }
  table.signals thead th.num { text-align: right; }

  table.signals tbody tr.row:hover > td { background: var(--surface); }
  table.signals td {
    padding: 4px 8px; vertical-align: middle; white-space: nowrap;
    border-bottom: 1px solid rgba(46,51,64,0.45);
  }
  table.signals td.num { text-align: right; font-variant-numeric: tabular-nums; }
  table.signals td.ts  { color: var(--muted); font-size: 11px; }

  /* Instruments get their own full-width row so many links never break the
     column alignment above. */
  table.signals tr.instr-row > td { border-bottom: 1px solid var(--line); padding: 2px 8px 8px 8px; }

  .chip {
    display: inline-block; min-width: 54px; text-align: right;
    padding: 2px 7px; border-radius: 3px;
    font-size: 11px; font-weight: 700; color: #0d0f14;
    font-variant-numeric: tabular-nums;
  }
  .chip.dim { color: #9aa0b0; }
  /* Universe chip: same warm ratio scale, but outlined rather than filled, so at
     a glance you can tell "what fired paid this" from "this was available". */
  .chip.univ { background: transparent !important; border: 1px solid; font-weight: 500; }

  .ts { color: var(--muted); font-size: 11px; }
  .state { font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; }
  .state.slHit { color: #8a5a5a; }
  .state.activated { color: #6a9d7f; }

  /* Instruments flow as wrapped pills rather than one line each: a range with
     eight instruments would otherwise push the next signal off the screen. */
  .instr { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
  .instr .lbl { color: var(--muted); font-size: 10px; letter-spacing: 0.06em;
                text-transform: uppercase; margin-right: 3px; }
  .instr a {
    color: var(--muted); text-decoration: none; font-size: 10.5px;
    background: var(--surface); border: 1px solid var(--line); border-radius: 3px;
    padding: 1px 6px; white-space: nowrap;
  }
  .instr a:hover { color: var(--accent); border-color: var(--accent); background: var(--raised); }
  .instr a:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

  .empty, .loading { color: var(--muted); padding: 12px 6px; font-size: 12px; }

  .legend { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 12px; font-size: 11px; color: var(--muted); }
  .legend .k { display: inline-flex; align-items: center; gap: 5px; }
  .legend .sw { width: 11px; height: 11px; border-radius: 2px; display: inline-block; }

  /* Field reference, so the schema never has to be looked up elsewhere. */
  details.schema { border: 0; margin-top: 14px; }
  details.schema > summary {
    display: inline-block; padding: 4px 0; color: var(--muted); font-size: 11px;
    border-bottom: 1px dotted var(--line); width: auto;
  }
  details.schema > summary:hover { color: var(--accent); }
  details.schema dl {
    display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px;
    margin: 12px 0 0; padding: 12px 14px; background: var(--surface);
    border-left: 2px solid var(--line); font-size: 11.5px;
  }
  details.schema dt { color: var(--text); font-weight: 700; }
  details.schema dd { margin: 0; color: var(--muted); }
  details.schema dd code { color: var(--accent); font-size: 11px; }

  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div>
      <h1><span class="sig">${SIGNAL_ID}</span> — signal review</h1>
      <div class="sub" id="sub">settled expiries only</div>
    </div>
    <div class="controls">
      <span><label for="spot">Spot</label>
        <select id="spot"></select></span>
      <span><label for="minRatio">Min ratio</label>
        <input type="number" id="minRatio" value="0" min="0" step="1"></span>
      <span><label for="minStrength">Min strength</label>
        <input type="number" id="minStrength" value="0" min="0" step="10"></span>
      <span><label for="type">Type</label>
        <select id="type"><option value="both">Both</option><option value="C">Calls</option><option value="P">Puts</option></select></span>
      <span><label>Payoff measured on</label><br>
        <span class="toggle" id="src">
          <button data-src="univ" aria-pressed="true">Best same-type strike</button>
          <button data-src="fired" aria-pressed="false">Fired instrument</button>
        </span></span>
    </div>
  </header>

  <section class="thesis">
    <h2>Does strength predict payoff?</h2>
    <div class="q" id="thesisQ"></div>
    <div id="matrix"></div>
    <div class="active-filter" id="activeFilter">
      <span id="activeFilterText"></span>
      <button id="clearFilter">Clear</button>
    </div>
    <div class="legend" id="legend"></div>

    <details class="schema">
      <summary>What each column means</summary>
      <dl id="schemaList"></dl>
    </details>
  </section>

  <section style="margin-bottom:30px">
    <div class="grid-head">
      <h2>Which expiries produced them?</h2>
      <span class="q" id="gridQ"></span>
      <label style="margin-left:auto;cursor:pointer;text-transform:none;letter-spacing:0">
        <input type="checkbox" id="gridHideEmpty" checked style="vertical-align:-1px">
        hide expiries with none
      </label>
    </div>
    <div class="grid-wrap"><div id="grid"></div></div>
  </section>

  <div id="tree"></div>
</div>

<script>
// Chart links carry a placeholder host; swap in whatever host served the page
// so links work from any device on the LAN.
const CHART_HOST=location.hostname;
function fixChartUrl(u){ return String(u||'').replace('__CHART_HOST__',CHART_HOST); }
const RCOL = ['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
let RATIO_MIN = [];   // lower edge of each ratio band, from the server
const SCOL = ['var(--s0)','var(--s1)','var(--s2)','var(--s3)','var(--s4)'];
let TREE = null;
// Which payoff definition drives the matrix, every headline percentage and the
// min-ratio filter.
//
// Defaults to 'univ' (universeMaxRatio) because that is the honest measure of
// what a signal was worth: the signal is a statement about the spot, and
// restricting the payoff to whichever strike happened to fire understates it —
// often badly, since the big multiple usually lands on a different strike.
// 'fired' remains one click away for the stricter "followed the signal
// literally" reading.
let SRC  = 'univ';   // 'univ' | 'fired'  (overridden by server default on load)

// Which cumulative threshold drives every headline percentage. Set by clicking
// a percentage column; comes from config.DEFAULT_HEADLINE_THRESHOLD initially.
let THR = 10;

// Grid sort: 'total' | 'expiry' | a duration number. Descending by count except
// for 'expiry', which sorts newest first.
let GRID_SORT = 'total';

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs = ts => String(ts).slice(0,16).replace('T',' ');

function filters() {
  return {
    minRatio:    parseFloat($('minRatio').value) || 0,
    minStrength: parseFloat($('minStrength').value) || 0,
    type:        $('type').value,
  };
}

// ── Heat matrix ──
// One definition per column: header label, tooltip, and the longer description
// used by the "What each column means" panel. Keeping them together means the
// header and the reference can never disagree.
const COLUMNS = [
  { key:'startTs', label:'Pattern start', num:false,
    tip:'Timestamp of the FIRST red candle of the squeeze.',
    doc:'Earliest <code>patternStart</code> across the instruments merged into this range — where the descending red sequence began.' },
  { key:'endTs', label:'Trigger', num:false,
    tip:'Timestamp of the green trigger candle. This is the entry point.',
    doc:'Latest trigger timestamp in the merged range. Entry is the CLOSE of this candle; every ratio is measured from there.' },
  { key:'type', label:'Type', num:false,
    tip:'C = call, P = put.',
    doc:'Option type. Calls and puts are merged and reported separately — a range never mixes them.' },
  { key:'count', label:'Instr', num:true,
    tip:'How many instrument signals merged into this range.',
    doc:'Number of separate instrument signals whose pattern windows overlapped and were merged into one range. Higher means more of the chain squeezed at once.' },
  { key:'signalValue', label:'Strength', num:true,
    tip:'maxSignalValue — ratio1 + ratio2, the highest among merged instruments.',
    doc:'<code>maxSignalValue</code>. ratio1 = firstRedBody / lastRedBody (how tight the squeeze got); ratio2 = firstRedBody / greenBody (how small the trigger was). Higher claims a stronger setup. Colour = strength band.' },
  { key:'ratio', label:'Fired ratio', num:true,
    tip:'maxSignalRatio — best multiple among instruments that ACTUALLY fired.',
    doc:'<code>maxSignalRatio</code>. Peak high after entry divided by entry close, restricted to instruments that fired. What you would have got following the signal literally. Filled chip.' },
  { key:'univRatio', label:'Best ratio', num:true,
    tip:'universeMaxRatio — best multiple on ANY same-type strike at that moment.',
    doc:'<code>universeMaxRatio</code>. Same measurement, but across every same-type strike already listed when the signal fired, whether or not it fired. Always ≥ Fired ratio. Outlined chip.' },
  { key:'univSymbol', label:'Best strike', num:false,
    tip:'universeMaxSymbol — which strike reached the Best ratio.',
    doc:'<code>universeMaxSymbol</code>. The instrument that achieved <code>universeMaxRatio</code>. Usually not one that fired; shown dashed in the instruments row when so.' },
  { key:'state', label:'State', num:false,
    tip:'activated = peak ≥ 1.5x entry. slHit = never got there. pending = no data after.',
    doc:'<code>signalState</code>, derived from the FIRED ratio only. <b>activated</b>: reached at least RED_SQUEEZE_SL_FACTOR (1.5x). <b>slHit</b>: went against the trade immediately. <b>pending</b>: the trigger was the last candle, so no outcome yet.' },
];

function renderSchema() {
  const extra = [
    { label:'Instruments', doc:'<code>instruments</code> — every contract that fired this signal. Each links to its chart. A dashed pill is the Best strike when it did not fire.' },
    { label:'Chart links', doc:'Open from the first red candle minus 20 candles of lead-in, through to settlement plus 30 minutes, at the duration of this section.' },
  ];
  $('schemaList').innerHTML =
    COLUMNS.map(c => '<dt>' + esc(c.label) + '</dt><dd>' + c.doc + '</dd>').join('') +
    extra.map(c => '<dt>' + esc(c.label) + '</dt><dd>' + c.doc + '</dd>').join('');
}

const FIRED_Q = 'Signal strength at entry against the multiple the FIRING instrument reached. ' +
                'A diagonal means strength is informative; a flat spread means it is not.';

// The eligibility sentence is derived from the server's configured mode rather
// than hardcoded, so the page never describes a rule the data was not built with.
function univQ(tree) {
  const scope = (tree && tree.universeMode === 'further_otm')
    ? 'same type and at least as far out as the firing strike'
    : 'any strike of the same type';
  return 'Signal strength at entry against the best multiple available on ANY eligible ' +
         'instrument at that moment — including strikes that never fired. Eligible means ' +
         scope + ', already listed when the signal fired. This measures how big a move ' +
         'was there, not which strike to buy.';
}

function renderMatrix(tree) {
  const { strengthBands, ratioBands, thresholds, rowTotals } = tree;
  const matrix = SRC === 'univ' ? (tree.matrixUniv || tree.matrix) : tree.matrix;
  document.getElementById('thesisQ').textContent = SRC === 'univ' ? univQ(tree) : FIRED_Q;

  const max = Math.max(1, ...matrix.flat());

  // Cumulative count for one strength row at one threshold: sum the band cells
  // whose lower edge is at or above the threshold. Bands are contiguous, so this
  // is exact as long as thresholds line up with band edges — and when one does
  // not, it rounds to the nearest band boundary at or above it, which is the
  // conservative direction.
  const cum = (si, t) => {
    let n = 0;
    for (let ri = 0; ri < ratioBands.length; ri++) {
      if (RATIO_MIN[ri] >= t) n += matrix[si][ri];
    }
    return n;
  };

  let h = '<table class="matrix"><tr><th class="rowhead axis">strength \\ ratio</th>';
  for (const rb of ratioBands) h += '<th>' + esc(rb) + '</th>';
  thresholds.forEach((t, i) => {
    h += '<th class="thr' + (t === THR ? ' on' : '') + '" data-thr="' + t +
         '" title="Click to filter everything below to signals reaching ' + t + 'x or more">' +
         '&ge;' + t + 'x</th>';
  });
  h += '</tr>';

  strengthBands.forEach((sb, si) => {
    const row = matrix[si];
    h += '<tr><th class="rowhead" style="color:' + SCOL[si] + '">' + esc(sb) + '</th>';
    row.forEach((n, ri) => {
      if (n === 0) { h += '<td class="zero">·</td>'; return; }
      const a = 0.22 + 0.78 * (n / max);
      h += '<td style="background:' + RCOL[ri] + ';opacity:' + a.toFixed(2) + '">' + n + '</td>';
    });
    const tot = rowTotals[si] || 0;
    thresholds.forEach((t, i) => {
      const n   = cum(si, t);
      const pct = tot ? (n / tot * 100).toFixed(0) + '%' : '·';
      h += '<td class="thr' + (i === 0 ? ' first' : '') + (t === THR ? ' on' : '') +
           '" data-thr="' + t + '" data-si="' + si + '"' +
           ' title="' + n + ' of ' + tot + ' signals in this strength band reached ' + t + 'x or more.' +
           ' Click to show only these.">' + pct + ' <small>' + n + '</small></td>';
    });
    h += '</tr>';
  });
  h += '</table>';
  $('matrix').innerHTML = h;

  // Header click → threshold only. Cell click → threshold AND that strength band.
  $('matrix').querySelectorAll('[data-thr]').forEach(el => {
    el.addEventListener('click', () => {
      const t  = Number(el.dataset.thr);
      const si = el.dataset.si === undefined ? null : Number(el.dataset.si);
      applyMatrixFilter(t, si, tree);
    });
  });

  let l = '<span class="k">payoff</span>';
  ratioBands.forEach((rb,i) => {
    l += '<span class="k"><span class="sw" style="background:' + RCOL[i] + '"></span>' + esc(rb) + '</span>';
  });
  l += '<span class="k" style="margin-left:12px">strength</span>';
  strengthBands.forEach((sb,i) => {
    l += '<span class="k"><span class="sw" style="background:' + SCOL[i] + '"></span>' + esc(sb) + '</span>';
  });
  $('legend').innerHTML = l;
}

/**
 * Clicking a percentage column sets the filters to that exact slice and opens
 * the sections below so the matching signals are immediately in view.
 *
 * Only duration sections are auto-opened. Expiry sections each trigger a fetch,
 * and a full history has hundreds of them — opening all would stall the page.
 * Their headline percentages update to the chosen threshold, so which ones are
 * worth opening is obvious at a glance.
 */
function applyMatrixFilter(threshold, strengthIdx, tree) {
  THR = threshold;
  $('minRatio').value = threshold;

  const minStrength = strengthIdx === null ? 0 : (tree.strengthMins[strengthIdx] || 0);
  $('minStrength').value = minStrength;

  const label = strengthIdx === null
    ? 'Showing signals that reached ' + threshold + 'x or more'
    : 'Showing strength ' + tree.strengthBands[strengthIdx] +
      ' signals that reached ' + threshold + 'x or more';
  $('activeFilterText').textContent = label;
  $('activeFilter').classList.add('on');

  renderMatrix(tree);
  renderGrid(tree);
  updateHitPercentages();

  document.querySelectorAll('#tree > details').forEach(d => { d.open = true; });
  repaintOpen();

  document.getElementById('tree').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function clearMatrixFilter() {
  THR = TREE ? (TREE.defaultThreshold || 10) : 10;
  $('minRatio').value = 0;
  $('minStrength').value = 0;
  $('activeFilter').classList.remove('on');
  if (TREE) { renderMatrix(TREE); renderGrid(TREE); }
  updateHitPercentages();
  repaintOpen();
}

// ── Expiry x duration grid ──
//
// Pivots the tree (duration -> expiry) into expiry -> duration. No extra fetch:
// every per-expiry, per-threshold count is already in the tree payload, for both
// payoff definitions, so switching source or threshold repivots instantly.

function buildGridRows(tree) {
  const byExpiry = new Map();   // expiry -> { total, perDur: Map<dur, count> }

  for (const d of tree.durations) {
    for (const e of d.expiries) {
      if (!byExpiry.has(e.expiry)) {
        byExpiry.set(e.expiry, { expiry: e.expiry, total: 0, perDur: new Map(), signals: 0 });
      }
      const row = byExpiry.get(e.expiry);
      const n   = hitsFor(e, SRC, THR);
      row.perDur.set(d.duration, n);
      row.total   += n;
      row.signals += e.total || 0;
    }
  }
  return [...byExpiry.values()];
}

function renderGrid(tree) {
  const durations = tree.durations.map(d => d.duration);
  let rows = buildGridRows(tree);

  // At a high threshold most expiries produce nothing, and across ~1000 rows
  // that noise buries the handful that matter. Hidden by default.
  const hideEmpty = $('gridHideEmpty').checked;
  const totalRows = rows.length;
  if (hideEmpty) rows = rows.filter(r => r.total > 0);
  const hiddenCount = totalRows - rows.length;

  if (!rows.length) {
    $('gridQ').textContent = 'No expiry produced a signal reaching ' + THR + 'x.';
    $('grid').innerHTML = '<div class="empty">Nothing at this threshold. Lower it, or untick "hide expiries with none".</div>';
    return;
  }

  $('gridQ').textContent =
    'Signals reaching ' + THR + 'x or more, per expiry per duration. Counts, not percentages. ' +
    'Click any number to open it below.' +
    (hiddenCount ? '  ' + hiddenCount + ' expiries with none are hidden.' : '');

  // Default sort puts the biggest producers on top — the whole point is to find
  // the outlier expiries without hunting through the tree.
  if (GRID_SORT === 'expiry')      rows.sort((a, b) => a.expiry < b.expiry ? 1 : -1);
  else if (GRID_SORT === 'total')  rows.sort((a, b) => b.total - a.total || (a.expiry < b.expiry ? 1 : -1));
  else {
    const d = Number(GRID_SORT);
    rows.sort((a, b) => (b.perDur.get(d) || 0) - (a.perDur.get(d) || 0) || b.total - a.total);
  }

  const max = Math.max(1, ...rows.map(r => Math.max(...[...r.perDur.values()], 0)));

  let h = '<table class="grid"><thead><tr>' +
    '<th class="exp-col' + (GRID_SORT === 'expiry' ? ' sorted' : '') + '" data-sort="expiry"' +
    ' title="Click to sort by date, newest first">Expiry</th>';
  for (const d of durations) {
    h += '<th data-sort="' + d + '"' + (String(GRID_SORT) === String(d) ? ' class="sorted"' : '') +
         ' title="Click to sort by this duration">' + d + 'm</th>';
  }
  h += '<th class="total' + (GRID_SORT === 'total' ? ' sorted' : '') + '" data-sort="total"' +
       ' title="Total across all durations. Click to sort.">Total</th></tr></thead><tbody>';

  for (const r of rows) {
    h += '<tr><td class="exp-col" title="' + r.signals + ' signals in total">' + esc(r.expiry) + '</td>';
    for (const d of durations) {
      const n = r.perDur.get(d) || 0;
      if (n === 0) { h += '<td class="nil">·</td>'; continue; }
      const a = 0.25 + 0.75 * (n / max);
      h += '<td class="hit" data-exp="' + esc(r.expiry) + '" data-dur="' + d +
           '" style="background:' + RCOL[4] + ';opacity:' + a.toFixed(2) + '"' +
           ' title="' + n + ' signals reached ' + THR + 'x at ' + d + 'm. Click to open.">' +
           n + '</td>';
    }
    h += '<td class="total">' + r.total + '</td></tr>';
  }
  h += '</tbody></table>';
  $('grid').innerHTML = h;

  // Re-render on toggle. Listener is re-attached each render, so replace it
  // rather than stacking duplicates.
  $('gridHideEmpty').onchange = () => renderGrid(tree);

  $('grid').querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => { GRID_SORT = th.dataset.sort; renderGrid(tree); });
  });

  // Clicking a count opens exactly that duration + expiry in the tree below.
  $('grid').querySelectorAll('td.hit').forEach(td => {
    td.addEventListener('click', () => openInTree(td.dataset.dur, td.dataset.exp));
  });
}

/** Open one duration+expiry section in the tree and scroll it into view. */
function openInTree(dur, expiry) {
  const durEl = document.querySelector('#tree > details[data-dur="' + dur + '"]');
  if (!durEl) return;
  durEl.open = true;

  const expEl = durEl.querySelector('details[data-exp="' + CSS.escape(expiry) + '"]');
  if (!expEl) { durEl.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }

  expEl.open = true;
  // Ranges load lazily on toggle; if already loaded, repaint for current filters.
  if (expEl.dataset.loaded && expEl._data) paintRanges(expEl);
  expEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ── Tree: durations → expiries, both collapsed ──
function renderTree(tree) {
  if (!tree.durations.length) {
    $('tree').innerHTML = '<div class="empty">No signals stored for this spot yet. Run backfill.js --signals-only.</div>';
    return;
  }
  let h = '';
  for (const d of tree.durations) {
    const dBig = hitsFor(d, SRC, THR);
    const pct  = d.total ? (dBig/d.total*100).toFixed(0) : '0';
    h += '<details data-dur="' + d.duration + '"><summary>' +
         '<span class="caret"></span>' +
         '<span class="dur-name">' + d.duration + 'm</span>' +
         '<span class="count">' + d.total + ' signals</span>' +
         '<span class="hit" data-hits="' + esc(JSON.stringify(d.hits || {})) +
         '" data-total="' + d.total + '" data-long="1">' + pct + '% reached ' + THR + 'x</span>' +
         '</summary><div class="lvl2">';
    for (const e of d.expiries) {
      const eBig = hitsFor(e, SRC, THR);
      const ep   = e.total ? (eBig/e.total*100).toFixed(0) : '0';
      h += '<details data-dur="' + d.duration + '" data-exp="' + esc(e.expiry) + '"><summary>' +
           '<span class="caret"></span>' +
           '<span class="exp-name">' + esc(e.expiry) + '</span>' +
           '<span class="count">' + e.total + '</span>' +
           '<span class="hit" data-hits="' + esc(JSON.stringify(e.hits || {})) +
           '" data-total="' + e.total + '">' + ep + '%</span>' +
           '</summary><div class="lvl3" data-slot="1"><div class="loading">Loading…</div></div>' +
           '</details>';
    }
    h += '</div></details>';
  }
  $('tree').innerHTML = h;

  // Ranges are fetched only when an expiry is opened. With ~128k ranges in a
  // full history, rendering everything up front would lock the page.
  $('tree').querySelectorAll('details[data-exp]').forEach(el => {
    el.addEventListener('toggle', () => {
      if (el.open && !el.dataset.loaded) loadRanges(el);
    });
  });
}

async function loadRanges(el) {
  el.dataset.loaded = '1';
  const slot = el.querySelector('[data-slot]');
  const spot = $('spot').value;
  const dur  = el.dataset.dur, exp = el.dataset.exp;
  try {
    const res = await fetch('/api/ranges/' + encodeURIComponent(spot) + '/' + dur + '/' + encodeURIComponent(exp));
    el._data = await res.json();
    paintRanges(el);
  } catch (err) {
    slot.innerHTML = '<div class="empty">Could not load ranges: ' + esc(err.message) + '</div>';
  }
}

function paintRanges(el) {
  const data = el._data;
  if (!data) return;
  const slot = el.querySelector('[data-slot]');
  const f = filters();

  const want = f.type === 'both' ? ['C','P'] : [f.type];
  const rows = [];

  for (const t of want) {
    for (const r of (data[t] || [])) {
      const active = SRC === 'univ' ? r.univRatio : r.ratio;
      if (active < f.minRatio || r.signalValue < f.minStrength) continue;
      rows.push({ t, r });
    }
  }

  if (!rows.length) {
    slot.innerHTML = '<div class="empty">Nothing here matches the current filters.</div>';
    return;
  }

  // Header row, labelled and tooltipped, so a row is readable without needing
  // the schema memorised.
  let h = '<table class="signals"><thead><tr>';
  for (const c of COLUMNS) {
    h += '<th' + (c.num ? ' class="num"' : '') + ' title="' + esc(c.tip) + '">' +
         esc(c.label) + '</th>';
  }
  h += '</tr></thead><tbody>';

  for (const { t, r } of rows) {
    h += '<tr class="row">' +
      '<td class="ts">'  + esc(shortTs(r.startTs)) + '</td>' +
      '<td class="ts">'  + esc(shortTs(r.endTs))   + '</td>' +
      '<td>'             + esc(t)                  + '</td>' +
      '<td class="num">' + r.count                 + '</td>' +
      '<td class="num"><span class="chip" style="background:' + SCOL[r.strengthBand] + '">' +
        r.signalValue.toFixed(0) + '</span></td>' +
      '<td class="num"><span class="chip' + (r.ratioBand === 0 ? ' dim' : '') +
        '" style="background:' + RCOL[r.ratioBand] + '">' + r.ratio.toFixed(2) + 'x</span></td>' +
      '<td class="num"><span class="chip univ" style="color:' + RCOL[r.univBand] +
        ';border-color:' + RCOL[r.univBand] + '">' + (r.univRatio || 0).toFixed(2) + 'x</span></td>' +
      '<td>' + (r.univSymbol
        ? '<a href="' + esc(fixChartUrl(r.univUrl)) + '" target="_blank" rel="noopener" style="color:' +
          RCOL[r.univBand] + ';text-decoration:none">' + esc(r.univSymbol) + ' &#8599;</a>'
        : '<span class="count">—</span>') + '</td>' +
      '<td><span class="state ' + esc(r.state) + '">' + esc(r.state) + '</span></td>' +
      '</tr>';

    // Instruments on their own full-width row: a range can merge many, and
    // wrapping them inside a cell would destroy the column alignment above.
    const fired = new Set(r.instruments.map(i => i.symbol));
    h += '<tr class="instr-row"><td colspan="' + COLUMNS.length + '"><div class="instr">' +
         '<span class="lbl">fired</span>';
    for (const i of r.instruments) {
      h += '<a href="' + esc(fixChartUrl(i.url)) + '" target="_blank" rel="noopener" title="Fired this signal">' +
           esc(i.symbol) + '</a>';
    }
    if (r.univSymbol && r.univUrl && !fired.has(r.univSymbol)) {
      h += '<span class="lbl" style="margin-left:8px">best</span>' +
           '<a href="' + esc(fixChartUrl(r.univUrl)) + '" target="_blank" rel="noopener"' +
           ' title="Best same-type strike — did not fire"' +
           ' style="border-style:dashed;color:' + RCOL[r.univBand] +
           ';border-color:' + RCOL[r.univBand] + '">' +
           esc(r.univSymbol) + ' ' + (r.univRatio || 0).toFixed(1) + 'x</a>';
    }
    h += '</div></td></tr>';
  }

  h += '</tbody></table>';
  slot.innerHTML = h;
}

// ── Wiring ──
async function loadSpot(spot) {
  $('tree').innerHTML = '<div class="loading">Loading…</div>';
  const res = await fetch('/api/tree/' + encodeURIComponent(spot));
  TREE = await res.json();
  RATIO_MIN = TREE.ratioMins || [];
  if (TREE.defaultThreshold && !$('activeFilter').classList.contains('on')) {
    THR = TREE.defaultThreshold;
  }
  $('sub').textContent = 'settled expiries only · ' + TREE.grandTotal.toLocaleString() + ' signals';
  renderMatrix(TREE);
  renderGrid(TREE);
  renderTree(TREE);
}

/** Hit count for a duration/expiry node under a given source and threshold. */
function hitsFor(node, src, threshold) {
  const h = node && node.hits;
  if (!h) return 0;
  const bucket = src === 'univ' ? h.univ : h.fired;
  return (bucket && Number(bucket[threshold])) || 0;
}

// Rewrite the headline percentages for the current source and threshold without
// touching the DOM structure, so open sections and their fetched ranges survive.
function updateHitPercentages() {
  document.querySelectorAll('.hit[data-total]').forEach(el => {
    const total = Number(el.dataset.total) || 0;
    let hits = {};
    try { hits = JSON.parse(el.dataset.hits || '{}'); } catch (_) {}
    const bucket = SRC === 'univ' ? (hits.univ || {}) : (hits.fired || {});
    const big    = Number(bucket[THR]) || 0;
    const pct    = total ? (big / total * 100).toFixed(0) : '0';
    el.textContent = el.dataset.long ? pct + '% reached ' + THR + 'x' : pct + '%';
  });
}

function repaintOpen() {
  document.querySelectorAll('details[data-exp][open]').forEach(el => { if (el._data) paintRanges(el); });
}

(async function init() {
  const spots = await (await fetch('/api/spots')).json();
  if (!spots.length) {
    document.querySelector('.wrap').innerHTML =
      '<div class="empty">No signals found. Run backfill.js --signals-only first.</div>';
    return;
  }
  $('spot').innerHTML = spots.map(s => '<option>' + esc(s) + '</option>').join('');
  renderSchema();
  $('spot').addEventListener('change', () => loadSpot($('spot').value));
  $('clearFilter').addEventListener('click', clearMatrixFilter);
  ['minRatio','minStrength','type'].forEach(id => $(id).addEventListener('input', repaintOpen));

  // Respect config.DEFAULT_RATIO_SOURCE for the initial toggle position.
  if (TREE && TREE.defaultSource && TREE.defaultSource !== SRC) {
    SRC = TREE.defaultSource;
    $('src').querySelectorAll('button').forEach(x =>
      x.setAttribute('aria-pressed', String(x.dataset.src === SRC)));
    renderMatrix(TREE); renderGrid(TREE); renderTree(TREE);
  }

  $('src').addEventListener('click', ev => {
    const b = ev.target.closest('button[data-src]');
    if (!b || b.dataset.src === SRC) return;
    SRC = b.dataset.src;
    $('src').querySelectorAll('button').forEach(x =>
      x.setAttribute('aria-pressed', String(x.dataset.src === SRC)));
    // Update in place rather than re-rendering: rebuilding the tree would discard
    // every already-fetched range and collapse whatever the user had open.
    if (TREE) { renderMatrix(TREE); renderGrid(TREE); }
    updateHitPercentages();
    repaintOpen();
  });
  await loadSpot(spots[0]);
})();
</script>
</body>
</html>`;
}

// ─── Server ───────────────────────────────────────────────────────────────────

function json(res, body) {
    const s = JSON.stringify(body);
    res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(s) });
    res.end(s);
}

const server = http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split('?')[0]);

    try {
        if (url === '/' || url === '/index.html') {
            const html = renderPage();
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
            return res.end(html);
        }

        if (url === '/api/spots') return json(res, listSpots());

        let m = url.match(/^\/api\/tree\/([^/]+)$/);
        if (m) return json(res, buildTree(m[1]));

        m = url.match(/^\/api\/ranges\/([^/]+)\/(\d+)\/([^/]+)$/);
        if (m) return json(res, buildRanges(m[1], Number(m[2]), m[3]));

        res.writeHead(404, { 'Content-Type': 'text/plain' });
        res.end('Not found');
    } catch (err) {
        console.error(`Error handling ${url}:`, err);
        res.writeHead(500, { 'Content-Type': 'text/plain' });
        res.end('Server error — see console');
    }
});

server.listen(PORT, '0.0.0.0', () => {
    const spots = listSpots();
    console.log(netinfo.banner('Signal review', PORT, [
        `signal  : ${SIGNAL_ID}`,
        `spots   : ${spots.length ? spots.join(', ') : '(none — run backfill.js --signals-only)'}`,
    ]));
});
