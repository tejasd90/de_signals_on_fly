// serve_grids.js
// ─────────────────────────────────────────────────────────────────────────────
// Signal heatmaps: expiry x time, one grid per (duration, type).
// Run: node serve_grids.js   (port 3800)
//
//   rows  = expiry
//   cols  = time
//   cell  = how many STRIKES fired the selected signal there
//
// Replaces an earlier 3D cube that used strike as a third axis. That was a
// design error: a (strike, expiry, time) cell identifies exactly one instrument,
// so its count could only ever be 0 or 1 and the shading carried no information.
// Collapsing strike into a count is what makes the shading mean something.
//
// Calls and puts sit side by side; durations stack, longest first.
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
const grouper   = require('./grouper');
const candleStore = require('./candle_store');
const api       = require('./api');
const surfaceMod = require('./surface');
const chart      = require('./chart_url');
const pa         = require('./price_action');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3800;

// Candle slots shown behind the selected moment. Columns are CANDLES, not
// distinct firing moments, so a slot where nothing fired still appears — an
// empty column is information.
const DEFAULT_CANDLES_BACK = 40;

// Symbols carried per cell for the hover readout. A cell with forty strikes is
// not readable as a list anyway, and the payload would balloon.
const MAX_SYMBOLS_PER_CELL = 14;

// Shortest signal duration these grids will show. Deliberate floor, applied at
// DISPLAY time only — the 5m/10m/15m/20m signal files are still written, still
// on disk, and still visible in every other viewer. Only this page and its
// sibling hide them. Set to 0 to get them back; nothing needs re-extracting.
const MIN_DURATION_MINUTES = 30;

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

// ─── Firing extraction ────────────────────────────────────────────────────────

const _cache = new Map();

function firings(signalId, spot, duration) {
    const key = `${signalId}|${spot}|${duration}`;
    if (_cache.has(key)) return _cache.get(key);

    const dir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot, String(duration));
    const out = { C: [], P: [] };
    if (!fs.existsSync(dir)) { _cache.set(key, out); return out; }

    for (const f of fs.readdirSync(dir)) {
        if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
        const expiry = f.replace(/\.json$/, '');
        // No settled-only filter here: whether an expiry was ALIVE is decided
        // per selected moment in buildGrid, not by whether it has settled today.

        const data = writer.readSignals(signalId, spot, duration, expiry);

        for (const type of ['C', 'P']) {
            for (const r of (data[type] || [])) {
                const ts = r[1];                                  // entry candle
                const sv = Number(r[3]) || 0;
                for (const sym of (r[6] || [])) {
                    const p = instr.parseSymbol(sym);
                    if (!isFinite(p.strike)) continue;
                    out[type].push({ expiry, ts, strike: p.strike, symbol: sym, signalValue: sv });
                }
            }
        }
    }

    _cache.set(key, out);
    return out;
}

/**
 * One heatmap as of `before`.
 *
 * A cell counts DISTINCT STRIKES, not firings. The same strike appearing in two
 * overlapping merged ranges at one timestamp is one strike having fired, and
 * counting it twice would make broad-but-shallow moments look like deep ones.
 */
/**
 * One heatmap as a POINT-IN-TIME SNAPSHOT: the board as it looked at `before`.
 *
 *   rows = expiries STILL ALIVE at that moment (settlement after it)
 *   cols = the last `candlesBack` candle slots at or before it
 *   cell = distinct strikes that fired for that expiry in that slot
 *
 * Two things this is deliberately NOT. It is not every settled expiry — an
 * expiry that had already settled was not on your screen and cannot be traded.
 * And columns are candle slots rather than firing moments, so a quiet slot shows
 * as an empty column instead of being silently skipped, which otherwise made
 * sparse durations look busier than they were.
 */
// When each expiry began trading. Derived once per expiry, then cached: the scan
// touches every stored symbol at the coarsest duration, which is cheap there but
// not worth repeating on every timeline scrub.
const _listedCache = new Map();

/**
 * When an expiry was LISTED, as a timestamp — or null if it cannot be told.
 *
 * The first candle across the expiry's instruments is when it started trading.
 * Strikes get added over time, so the EARLIEST across all of them is the moment
 * the expiry itself appeared.
 *
 * Uses the coarsest stored duration, which has the fewest candles per file and
 * therefore the cheapest scan; a daily candle resolves listing to within a day,
 * which is ample for deciding what was on the board.
 */
function expiryListedAt(spot, expiry) {
    const key = `${spot}|${expiry}`;
    if (_listedCache.has(key)) return _listedCache.get(key);

    let listed = null;
    try {
        const durations = candleStore.storedDurations(spot, expiry);
        if (durations.length) {
            const coarsest = Math.max(...durations);
            for (const sym of candleStore.storedSymbols(spot, expiry, coarsest)) {
                const c = candleStore.readCandles(spot, expiry, coarsest, sym);
                if (!c.length) continue;
                const t = new Date(c[0].dtstring).getTime();
                if (!Number.isNaN(t) && (listed === null || t < listed)) listed = t;
            }
        }
    } catch (_) { listed = null; }

    _listedCache.set(key, listed);
    return listed;
}

/**
 * Every expiry alive at a moment, from the INSTRUMENT list rather than from
 * signals.
 *
 * Deriving rows from firings meant an expiry with no signal simply vanished —
 * so calls and puts showed different rows for the same moment, and a quiet
 * expiry looked as though it did not exist. An empty row is information: it says
 * this expiry was tradeable and nothing fired on it.
 */
function activeExpiries(spot, beforeMs) {
    const fallbackMs = cfg.EXPIRY_LISTING_WINDOW_DAYS * 86400000;

    return instr.getExpiries(spot).filter(e => {
        const settleMs = expiryMod.expiryMillis(spot, e);
        if (!(settleMs > beforeMs)) return false;          // already settled

        const listed = expiryListedAt(spot, e);
        // Candles are authoritative. Without them, assume the expiry appeared
        // EXPIRY_LISTING_WINDOW_DAYS before settlement.
        return listed !== null
            ? listed <= beforeMs
            : (settleMs - fallbackMs) <= beforeMs;
    }).sort();
}

function buildGrid(signalId, spot, duration, type, before, minValue, candlesBack, expiries) {
    const empty = { expiries: expiries || [], times: [], cells: {}, max: 0, total: 0 };
    if (!before || !expiries || !expiries.length) return empty;

    const beforeMs = new Date(before).getTime();
    if (Number.isNaN(beforeMs)) return empty;

    // Column slots, walking back on the candle grid so they line up exactly with
    // stored candle timestamps.
    const n = candlesBack > 0 ? candlesBack : DEFAULT_CANDLES_BACK;
    const times = [];
    for (let i = n - 1; i >= 0; i--) {
        times.push(grouper.getKeyDuration(duration, api.formatTs(
            Math.floor((beforeMs - i * duration * 60000) / 1000))));
    }
    const uniqTimes = [...new Set(times)];
    const tIndex = new Map(uniqTimes.map((t, i) => [t, i]));
    const earliest = uniqTimes[0];

    // Rows are supplied by the caller, so calls and puts share one row set and
    // are readable side by side.
    const xi = new Map(expiries.map((e, i) => [e, i]));

    const rows = firings(signalId, spot, duration)[type].filter(f =>
        f.ts <= before && f.ts >= earliest &&
        (!minValue || f.signalValue >= minValue) &&
        xi.has(f.expiry));

    const bySymbol = new Map();
    for (const r of rows) {
        const ci = tIndex.get(r.ts);
        if (ci === undefined) continue;
        const k = `${xi.get(r.expiry)},${ci}`;
        if (!bySymbol.has(k)) bySymbol.set(k, { set: new Set(), at: new Map(), expiry: r.expiry, iso: r.ts });
        const e = bySymbol.get(k);
        e.set.add(r.symbol);
        if (!e.at.has(r.symbol)) e.at.set(r.symbol, new Date(r.ts).getTime());
    }

    const cells = {};
    let max = 0, total = 0;
    for (const [k, e] of bySymbol) {
        const syms = [...e.set].sort();
        const shown = syms.slice(0, MAX_SYMBOLS_PER_CELL);
        cells[k] = { n: syms.length, syms: shown, iso: e.iso,
                     urls: shown.map(sym =>
                        chart.chartUrl(spot, e.expiry, sym, e.at.get(sym), duration)) };
        if (syms.length > max) max = syms.length;
        total += syms.length;
    }

    return { expiries, times: uniqTimes, cells, max, total };
}

function buildAll(signalId, spot, before, minValue, candlesBack, showEmpty) {
    const beforeMs = new Date(before).getTime();
    const expiries = Number.isNaN(beforeMs) ? [] : activeExpiries(spot, beforeMs);

    const grids = [];
    let hidden = 0;

    // Longest duration first: it covers the most calendar time per column.
    for (const duration of listDurations(signalId, spot).slice().reverse()) {
        const C = buildGrid(signalId, spot, duration, 'C', before, minValue, candlesBack, expiries);
        const P = buildGrid(signalId, spot, duration, 'P', before, minValue, candlesBack, expiries);
        if (!C.total && !P.total && !showEmpty) { hidden++; continue; }
        grids.push({ duration, C, P });
    }

    // The count is returned rather than silently dropped, so a missing duration
    // is explained instead of looking like a fault.
    return { expiries, grids, hidden };
}

function timeline(signalId, spot) {
    const times = new Set();
    let lo = Infinity, hi = 0;
    for (const duration of listDurations(signalId, spot)) {
        const f = firings(signalId, spot, duration);
        for (const type of ['C', 'P']) {
            for (const r of f[type]) {
                times.add(r.ts);
                if (r.signalValue < lo) lo = r.signalValue;
                if (r.signalValue > hi) hi = r.signalValue;
            }
        }
    }
    return { times: [...times].sort(), minValue: isFinite(lo) ? lo : 0, maxValue: hi };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal heatmaps</title>
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

  .tl{background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:10px 13px;margin-bottom:14px}
  .tl .row{display:flex;gap:12px;align-items:center}
  .tl input[type=range]{flex:1;accent-color:var(--accent)}
  .tl .now{font-size:13px;font-weight:700;font-family:'Space Grotesk',sans-serif;color:var(--accent);min-width:150px}
  .tl .hint{color:var(--muted);font-size:10.5px;margin-top:5px}
  .tl button{background:var(--raised);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:4px 9px;font-family:inherit;font-size:11px;cursor:pointer}

  .durRow{margin-bottom:14px;border:1px solid var(--line);border-radius:3px;background:var(--surface)}
  .durHead{display:flex;align-items:baseline;gap:10px;padding:5px 11px;
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
  /* A 2px light border on a 22px cell is unmissable, which a 1px dark one on a
     dark background was not. */
  table.hm td{width:22px;height:22px;padding:0;text-align:center;font-size:9.5px;
              border:2px solid rgba(200,206,222,0.34);border-radius:2px;
              color:#0d0f14;font-weight:700;cursor:default}
  table.hm td.zero{border-color:rgba(70,76,92,0.30);background:#171a21;color:transparent}
  table.hm td:hover{outline:2px solid var(--accent);outline-offset:1px}

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
    <h1><span class="k">signal heatmaps</span> — expiry × time</h1>
    <div class="sub">Each cell is how many STRIKES fired the signal for that expiry at that
      moment. Rows are expiries, columns are time. Hover a cell for the instruments.
      A point-in-time snapshot: EVERY expiry alive at the selected moment gets a row,
      whether or not it fired, over the last N candles behind it. Calls and puts share
      the same rows. Scrub the timeline to move that moment.</div>
  </header>

  <div class="bar">
    <span><label for="spot">Spot</label><br><select id="spot"></select></span>
    <span><label>Signal</label><div class="radios" id="sigs"></div></span>
    <span><label>Layout</label><div class="radios" id="layout">
      <button data-v="time" aria-pressed="true">expiry × time</button>
      <button data-v="strike" aria-pressed="false">expiry × strike</button></div></span>
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
    <span><label for="minVal">Min strength</label><br>
      <input type="number" id="minVal" value="0" step="1" style="width:110px"></span>
    <span><label for="empty">Empty durations</label><br>
      <label style="text-transform:none;letter-spacing:0;font-size:11.5px;color:var(--text);cursor:pointer">
        <input type="checkbox" id="empty" style="vertical-align:-1px"> show</label></span>
    <span><label for="candles">Candles back</label><br>
      <select id="candles">
        <option value="20">20</option>
        <option value="40" selected>40</option>
        <option value="80">80</option>
        <option value="150">150</option>
      </select></span>
  </div>

  <div class="tl">
    <div class="row">
      <button id="prev">◀</button>
      <input type="range" id="time" min="0" max="0" value="0">
      <button id="next">▶</button>
      <span class="now" id="nowLabel">—</span>
    </div>
    <div class="hint" id="tlHint"></div>
  </div>

  <div id="pa" class="pa"></div>
  <div id="grids"></div>
  <div class="legend" id="legend"></div>
</div>

<script>
// Sequential scale: pale blue through to orange. Ordered by luminance so the
// count reads even without seeing the legend.
const SCALE=['#2b3648','#3a5570','#4d7a91','#6a9d7f','#9db866','#c9b053','#d4823f','#d4703a'];
const $=id=>document.getElementById(id);
${chart.CLIENT_HELPER}
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let TIMES=[], DATA=[], SIGNAL=null;
let LAYOUT='time', SURF=null, PASTATS=null;

/* Colour = P(25x) among tradeable events, not the max ratio. See price_action.js
   for why max cannot be used. On this LIVE board the cell itself has no ratio,
   so only the label statistics are shaded. */
function colForHit(h){
  if(!(h>0)) return null;
  const t=Math.max(0,Math.min(1,(h-0.02)/0.04));
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
  if(!PASTATS.ok) return;
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
    '  ·  live board, outcome not yet known</div>';
  if(!d.labels||!d.labels.length){
    h+='<div class="note">No price action recorded for this moment.</div>';
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
    h+='<div class="note">Shade = P(25x) for events carrying that label, measured on SETTLED '+
       'trades (filled, entry premium 2-20). Only the first tier was measured to predict.</div>';
  }
  const el=$('pa');
  el.innerHTML=h; el.classList.add('on');
  const px=$('paX'); if(px) px.addEventListener('click',()=>el.classList.remove('on'));
  placePA(el, td);
}

function colFor(n,max){
  if(!n) return null;
  if(max<=1) return SCALE[SCALE.length-1];
  const t=(n-1)/(max-1);
  return SCALE[Math.min(SCALE.length-1,Math.floor(t*(SCALE.length-0.001)))];
}

/* ── Expiry x STRIKE, live board ──────────────────────────────────────────────
   Rows are expiries not yet settled at the selected moment; columns are absolute
   strikes. Cells count firings inside the forward window. There is deliberately
   NO payoff shading here: the window has not elapsed, so any ratio would be a
   partial number that looks final. Use 3900 for that.                         */
function renderSurface(type,grid,mx,dur){
  const cols=(SURF.cols||{})[type]||[], rows=SURF.rows||[];
  grid=grid||[];
  if(!cols.length) return '<div class="empty">No '+(type==='C'?'calls':'puts')+' on the board.</div>';
  const px=SURF.spotPx, step=Math.max(1,Math.ceil(cols.length/18));

  let h='<div class="gridScroll"><table class="hm"><thead><tr>'+
        '<th class="corner">expiry / strike →</th>';
  cols.forEach((k,i)=>{
    const m=px?((k-px)/px*100):null;
    const lab=(i%step===0||i===cols.length-1)?(k>=1000?(Math.round(k/100)/10)+'k':String(k)):'';
    h+='<th class="colh" title="'+k+(m==null?'':'  ('+(m>=0?'+':'')+m.toFixed(1)+'% from spot)')+'">'+lab+'</th>';
  });
  h+='</tr></thead><tbody>';
  rows.forEach((r,ri)=>{
    h+='<tr><th class="rowh" title="'+r.tte.toFixed(0)+'h to expiry">'+esc(r.expiry)+'</th>';
    (grid[ri]||[]).forEach((c,ci)=>{
      if(!c||!c.n){ h+='<td class="zero"></td>'; return; }
      const bg=colFor(c.n,mx);
      h+='<td'+(bg?' style="background:'+bg+'"':' class="zero"')+
         ' data-sk="1" data-d="'+(dur||'')+'" data-ty="'+type+'" data-e="'+esc(r.expiry)+'" data-t="'+r.tte.toFixed(0)+
         '" data-k="'+cols[ci]+'" data-n="'+c.n+
         '" data-du="'+(c.ratio||0)+
         '" data-s="'+esc((c.syms||[]).join(' '))+'" data-ei="'+esc(c.iso||'')+
         '" data-u="'+esc((c.urls||[]).join(' '))+'">'+c.n+'</td>';
    });
    h+='</tr>';
  });
  return h+'</tbody></table></div><div class="readout"></div>';
}

function renderSurfaceAll(){
  if(!SURF||!SURF.rows||!SURF.rows.length){
    $('grids').innerHTML='<div class="empty">No expiry was live at this moment.</div>'; return; }
  const nC=(SURF.cols.C||[]).length, nP=(SURF.cols.P||[]).length;
  if(!SURF.boards||!SURF.boards.length){
    $('grids').innerHTML='<div class="empty">Nothing entered on the selected day on '+
      'any duration at or above the 30m floor.</div>'; return; }
  let h='';
  if(SURF.minPremium>0) h+='<div class="note">Contracts marked below '+SURF.minPremium+
    ' at entry are hidden — set "min premium" to <b>all</b> to see them.</div>';
  // Longest duration first, same order as the time-axis view.
  SURF.boards.slice().reverse().forEach(b=>{
    h+='<div class="durRow"><div class="durHead"><span class="d">'+b.duration+'m</span>'+
       '<span class="c">'+SURF.rows.length+' live expiries</span>'+
       '<span class="c">'+nC+' call / '+nP+' put strikes</span>'+
       (SURF.spotPx?'<span class="c">spot '+Math.round(SURF.spotPx).toLocaleString()+'</span>':'')+
       '<span class="c">'+b.total.C+' call / '+b.total.P+' put strike-firings that day</span>'+
       '<span class="c">peak '+b.max+' in one cell</span></div>'+
       '<div class="pair">'+
         '<div class="pane"><div class="t">Calls</div>'+renderSurface('C',b.grid.C,b.max,b.duration)+'</div>'+
         '<div class="pane"><div class="t">Puts</div>'+renderSurface('P',b.grid.P,b.max,b.duration)+'</div>'+
       '</div></div>';
  });
  $('grids').innerHTML=h;

  for(const td of document.querySelectorAll('table.hm td[data-sk]')){
    td.addEventListener('click',()=>showPA(td));
    td.addEventListener('mouseenter',()=>{
      const out=td.closest('.pane').querySelector('.readout');
      const syms=td.dataset.s?td.dataset.s.split(' '):[];
      out.innerHTML='<b>strike '+(+td.dataset.k).toLocaleString()+'</b>  ·  exp '+esc(td.dataset.e)+
        '  ·  '+td.dataset.t+'h to expiry  ·  '+(td.dataset.ty==='C'?'call':'put')+
        '  ·  '+td.dataset.n+' firing'+(td.dataset.n==='1'?'':'s')+
        (+td.dataset.du?', signal ratio '+(+td.dataset.du).toFixed(2)+'x':'')+
        '<div class="syms">'+symLinks(syms,td.dataset.u?td.dataset.u.split(' '):[])+'</div>';
    });
  }
}

function renderGrid(grid,duration,type){
  if(!grid.times.length) return '<div class="empty">No firings.</div>';

  // Show every Nth column label so the header does not collapse into a smear.
  const step=Math.max(1,Math.ceil(grid.times.length/14));

  // Include the YEAR whenever the columns span more than one. Without it a
  // column reading "07-15" beside a row reading "2024-07-19" gives no way to
  // tell whether they are the same year — which made a correct grid look wrong.
  const years=new Set(grid.times.map(t=>String(t).slice(0,4)));
  const fmtCol=t=>years.size>1
    ? String(t).slice(0,16).replace('T',' ')
    : String(t).slice(5,16).replace('T',' ');

  let h='<div class="gridScroll"><table class="hm"><thead><tr>'+
        '<th class="corner">expiry \\ time →</th>';
  grid.times.forEach((t,i)=>{
    h+='<th class="colh">'+(i%step===0?esc(fmtCol(t)):'')+'</th>';
  });
  h+='</tr></thead><tbody>';

  grid.expiries.forEach((e,ri)=>{
    h+='<tr><th class="rowh">'+esc(e)+'</th>';
    grid.times.forEach((t,ci)=>{
      const c=grid.cells[ri+','+ci];
      if(!c){ h+='<td class="zero"></td>'; return; }
      h+='<td style="background:'+colFor(c.n,grid.max)+'" data-d="'+duration+'" data-ty="'+type+
         '" data-e="'+esc(e)+'" data-t="'+esc(t)+'" data-n="'+c.n+
         '" data-s="'+esc(c.syms.join(' '))+'" data-ei="'+esc(c.iso||'')+
         '" data-u="'+esc((c.urls||[]).join(' '))+'">'+c.n+'</td>';
    });
    h+='</tr>';
  });
  return h+'</tbody></table></div><div class="readout"></div>';
}

/** Date range actually covered by a duration row, stated so it cannot surprise. */
function spanOf(row){
  const all=[...(row.C.times||[]),...(row.P.times||[])].sort();
  if(!all.length) return '';
  const a=String(all[0]).slice(0,10), b=String(all[all.length-1]).slice(0,10);
  return a===b?a:(a+' → '+b);
}

function renderAll(){
  const grids=DATA.grids||[];
  const nExp=(DATA.expiries||[]).length;

  if(!nExp){ $('grids').innerHTML='<div class="empty">No expiries were alive at this moment.</div>'; return; }
  if(!grids.length){
    $('grids').innerHTML='<div class="empty">'+nExp+' expiries alive, but no signal fired on any duration '+
      'in this window. Tick "show empty durations" to see the grids anyway.</div>';
    return;
  }

  let h='';
  if(DATA.hidden) h+='<div class="note">'+DATA.hidden+
    ' duration'+(DATA.hidden===1?'':'s')+' hidden — no firings in this window.</div>';

  grids.forEach(row=>{
    h+='<div class="durRow"><div class="durHead"><span class="d">'+row.duration+'m</span>'+
       '<span class="c">'+row.C.total+' call strike-firings · '+row.P.total+' put strike-firings</span>'+
       '<span class="c">peak '+Math.max(row.C.max,row.P.max)+' strikes in one cell</span>'+
       '<span class="c">'+spanOf(row)+'</span>'+
       '<span class="c">'+row.C.expiries.length+' expiries alive</span></div>'+
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
        '  ·  '+td.dataset.d+'m  ·  '+(td.dataset.ty==='C'?'calls':'puts')+
        '  ·  exp '+esc(td.dataset.e)+
        '  ·  '+esc(String(td.dataset.t).slice(0,16).replace('T',' '))+
        '<div class="syms">'+symLinks(syms,td.dataset.u?td.dataset.u.split(' '):[])+
        (syms.length<+td.dataset.n?'  … +'+(+td.dataset.n-syms.length)+' more':'')+'</div>';
    });
  }
}

function applyLayoutVis(){
  document.querySelectorAll('.surfOnly').forEach(e=>e.style.display=LAYOUT==='strike'?'':'none');
  document.querySelectorAll('.timeOnly').forEach(e=>e.style.display=LAYOUT==='strike'?'none':'');
}

async function load(){
  if(!SIGNAL) return;
  const t=TIMES[+$('time').value]||'';
  $('nowLabel').textContent=t?String(t).slice(0,16).replace('T',' '):'—';
  if(LAYOUT==='strike'){
    SURF=await (await fetch('/api/surface/'+encodeURIComponent(SIGNAL)+'/'+
      encodeURIComponent($('spot').value)+'?before='+encodeURIComponent(t)+
      '&minprem='+encodeURIComponent($('minprem').value||0)+
      '&band='+encodeURIComponent($('band').value||30))).json();
    return renderSurfaceAll();
  }
  DATA=await (await fetch('/api/grids/'+encodeURIComponent(SIGNAL)+'/'+
    encodeURIComponent($('spot').value)+'?before='+encodeURIComponent(t)+
    '&min='+encodeURIComponent($('minVal').value||0)+
    '&candles='+encodeURIComponent($('candles').value||40)+
    '&empty='+($('empty').checked?'1':'0'))).json();
  renderAll();
}

async function loadTimeline(){
  const tl=await (await fetch('/api/timeline/'+encodeURIComponent(SIGNAL)+'/'+
    encodeURIComponent($('spot').value))).json();
  TIMES=tl.times||[];
  const s=$('time'); s.min=0; s.max=Math.max(0,TIMES.length-1); s.value=Math.max(0,TIMES.length-1);
  $('minVal').title='observed strength range '+Math.round(tl.minValue)+' to '+Math.round(tl.maxValue);
  $('tlHint').textContent=TIMES.length
    ? TIMES.length.toLocaleString()+' firing moments  ·  '+String(TIMES[0]).slice(0,10)+
      ' to '+String(TIMES[TIMES.length-1]).slice(0,10)+
      '  ·  strength '+Math.round(tl.minValue)+' to '+Math.round(tl.maxValue)
    : 'No firings for this signal and spot.';
  await load();
}

(async function init(){
  $('legend').innerHTML='<span class="k">strikes fired</span>'+
    SCALE.map((c,i)=>'<span class="k"><span class="sw" style="background:'+c+'"></span>'+
      (i===0?'few':(i===SCALE.length-1?'many':''))+'</span>').join('')+
    '<span class="k" style="margin-left:8px">hover a cell for the instruments</span>';

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
    await loadTimeline();
  });

  const spots=await (await fetch('/api/spots/'+encodeURIComponent(SIGNAL))).json();
  $('spot').innerHTML=spots.map(s=>'<option>'+esc(s)+'</option>').join('');
  $('spot').addEventListener('change',loadTimeline);
  $('time').addEventListener('input',load);
  $('layout').addEventListener('click',e=>{
    const b=e.target.closest('button[data-v]'); if(!b) return;
    LAYOUT=b.dataset.v;
    $('layout').querySelectorAll('button').forEach(x=>
      x.setAttribute('aria-pressed',String(x.dataset.v===LAYOUT)));
    applyLayoutVis(); load();
  });
  $('band').addEventListener('change',load);
  $('minprem').addEventListener('change',load);
  applyLayoutVis();
  $('minVal').addEventListener('change',load);
  $('candles').addEventListener('change',load);
  $('empty').addEventListener('change',load);
  $('prev').addEventListener('click',()=>{ $('time').value=Math.max(0,+$('time').value-1); load(); });
  $('next').addEventListener('click',()=>{ $('time').value=Math.min(TIMES.length-1,+$('time').value+1); load(); });
  await loadTimeline();
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

        m = url.match(/^\/api\/timeline\/([^/]+)\/([^/]+)$/);
        if (m) return json(res, timeline(m[1], m[2]));

        m = url.match(/^\/api\/grids\/([^/]+)\/([^/]+)$/);
        let ms = url.match(/^\/api\/surface\/([^/]+)\/([^/]+)$/);
        if (ms) {
            const before = q.get('before') || '';
            const beforeMs = new Date(before).getTime();
            if (Number.isNaN(beforeMs)) return json(res, null);
            // withPayoff:false — on a LIVE board the forward window has not
            // elapsed, so a peak ratio here would be a partial number dressed up
            // as a final one. 3900 is where payoff is real.
            return json(res, surfaceMod.buildSurface(ms[2], Math.floor(beforeMs / 1000), {
                signalId:     ms[1],
                horizonHours: parseInt(q.get('horizon')) || 72,
                bandPct:      parseFloat(q.get('band')),
                minPremium:   parseFloat(q.get('minprem')) || 0,
                minDuration:  MIN_DURATION_MINUTES,
                withPayoff:   false,
            }));
        }

        if (m) return json(res, buildAll(m[1], m[2], q.get('before') || '',
                                         parseFloat(q.get('min')) || 0,
                                         parseInt(q.get('candles')) || DEFAULT_CANDLES_BACK,
                                         q.get('empty') === '1'));

        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, '0.0.0.0', () => {
    selfCheck();
    console.log(netinfo.banner('Signal heatmaps — expiry × time', PORT, [
        `signals : ${listSignals().join(', ') || '(none)'}`,
    ]));
});
