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

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3800;

// Candle slots shown behind the selected moment. Columns are CANDLES, not
// distinct firing moments, so a slot where nothing fired still appears — an
// empty column is information.
const DEFAULT_CANDLES_BACK = 40;

// Symbols carried per cell for the hover readout. A cell with forty strikes is
// not readable as a list anyway, and the payload would balloon.
const MAX_SYMBOLS_PER_CELL = 14;

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
        .map(Number).sort((a, b) => a - b);
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
        if (!bySymbol.has(k)) bySymbol.set(k, new Set());
        bySymbol.get(k).add(r.symbol);
    }

    const cells = {};
    let max = 0, total = 0;
    for (const [k, set] of bySymbol) {
        const syms = [...set].sort();
        cells[k] = { n: syms.length, syms: syms.slice(0, MAX_SYMBOLS_PER_CELL) };
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

  <div id="grids"></div>
  <div class="legend" id="legend"></div>
</div>

<script>
// Sequential scale: pale blue through to orange. Ordered by luminance so the
// count reads even without seeing the legend.
const SCALE=['#2b3648','#3a5570','#4d7a91','#6a9d7f','#9db866','#c9b053','#d4823f','#d4703a'];
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let TIMES=[], DATA=[], SIGNAL=null;

function colFor(n,max){
  if(!n) return null;
  if(max<=1) return SCALE[SCALE.length-1];
  const t=(n-1)/(max-1);
  return SCALE[Math.min(SCALE.length-1,Math.floor(t*(SCALE.length-0.001)))];
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
         '" data-s="'+esc(c.syms.join(' '))+'">'+c.n+'</td>';
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
    td.addEventListener('mouseenter',()=>{
      const out=td.closest('.pane').querySelector('.readout');
      const syms=td.dataset.s?td.dataset.s.split(' '):[];
      out.innerHTML='<b>'+td.dataset.n+' strike'+(td.dataset.n==='1'?'':'s')+'</b>'+
        '  ·  '+td.dataset.d+'m  ·  '+(td.dataset.ty==='C'?'calls':'puts')+
        '  ·  exp '+esc(td.dataset.e)+
        '  ·  '+esc(String(td.dataset.t).slice(0,16).replace('T',' '))+
        '<div class="syms">'+syms.map(esc).join('  ')+
        (syms.length<+td.dataset.n?'  … +'+(+td.dataset.n-syms.length)+' more':'')+'</div>';
    });
  }
}

async function load(){
  if(!SIGNAL) return;
  const t=TIMES[+$('time').value]||'';
  $('nowLabel').textContent=t?String(t).slice(0,16).replace('T',' '):'—';
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

        let m = url.match(/^\/api\/spots\/([^/]+)$/);
        if (m) return json(res, listSpots(m[1]));

        m = url.match(/^\/api\/timeline\/([^/]+)\/([^/]+)$/);
        if (m) return json(res, timeline(m[1], m[2]));

        m = url.match(/^\/api\/grids\/([^/]+)\/([^/]+)$/);
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
    console.log(netinfo.banner('Signal heatmaps — expiry × time', PORT, [
        `signals : ${listSignals().join(', ') || '(none)'}`,
    ]));
});
