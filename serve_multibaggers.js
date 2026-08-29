// serve_multibaggers.js
// ─────────────────────────────────────────────────────────────────────────────
// Table view of ground-truth multibaggers. Run: node serve_multibaggers.js
// Default port 3300.
//
// Reads what multibaggers.js computed. Every row is a real trade that existed —
// no signal involved — so this is the denominator: what was available, against
// which any strategy's capture rate is measured.
//
// Deliberately one flat sortable table rather than the collapsible tree used by
// serve_signals. The question here is "what were the biggest moves and where",
// which is a sorting problem, not a drill-down.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg  = require('./config');
const netinfo = require('./netinfo');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3300;
const DIR  = path.join(cfg.DATA_BASE_DIR, 'multibaggers');

// Your charting app, same URL shape serve_signals uses.
// Host-relative. Hardcoding localhost meant a chart link opened on a phone
// resolved to the PHONE, so every link 404'd off the LAN. The page substitutes
// its own hostname client-side.
const CHART_HOST_PLACEHOLDER = '__CHART_HOST__';
const CHART_BASE = `http://${CHART_HOST_PLACEHOLDER}:3000/de`;
const CHART_LEAD_CANDLES = 20;

// ─── Data ─────────────────────────────────────────────────────────────────────

function listSpots() {
    if (!fs.existsSync(DIR)) return [];
    return fs.readdirSync(DIR)
        .filter(d => !d.startsWith('.') && fs.statSync(path.join(DIR, d)).isDirectory())
        .sort();
}

/**
 * Every qualifying trade for a spot, flattened across expiries.
 *
 * Flattened deliberately: the biggest move of the year matters whichever expiry
 * it happened in, and grouping by expiry would hide it behind whichever expiry
 * you happened to open.
 */
function loadRows(spot) {
    const dir = path.join(DIR, spot);
    if (!fs.existsSync(dir)) return { rows: [], expiries: 0, scanned: 0 };

    const rows = [];
    let expiries = 0, scanned = 0;

    for (const f of fs.readdirSync(dir)) {
        if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
        let d;
        try { d = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')); } catch (_) { continue; }

        expiries++;
        scanned += d.instruments || 0;

        for (const r of (d.rows || [])) {
            rows.push({
                ...r,
                expiry:   d.expiry,
                duration: d.duration,
                chartUrl: chartUrl(spot, d.expiry, r.symbol, r.entryTs, d.duration),
            });
        }
    }

    rows.sort((a, b) => b.ratio - a.ratio);
    return { rows, expiries, scanned };
}

function chartUrl(spot, expiry, symbol, entryTs, duration) {
    const fromMs = new Date(entryTs).getTime() - CHART_LEAD_CANDLES * duration * 60000;
    const pad = n => String(n).padStart(2, '0');
    const fmt = ms => {
        const d = new Date(ms + (5 * 60 + 30) * 60000);
        return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
               `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00+0530`;
    };
    const to = `${expiry}T18:00:00+0530`;
    return `${CHART_BASE}/${expiry}/${symbol}/${fmt(fromMs)}/${to}/${duration}`;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Multibaggers — ground truth</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{--ground:#14161c;--surface:#1c1f28;--raised:#242833;--line:#2e3340;
        --text:#c8ccd8;--muted:#6b7183;--accent:#d4703a;
        --r0:#3d4454;--r1:#5b7c99;--r2:#6a9d7f;--r3:#b8a44c;--r4:#d4703a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1,h2{font-family:'Space Grotesk',system-ui,sans-serif;margin:0}
  .wrap{max-width:1500px;margin:0 auto;padding:24px 20px 70px}

  header{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;
         padding-bottom:15px;border-bottom:1px solid var(--line);margin-bottom:20px}
  h1{font-size:18px;font-weight:700}
  h1 .k{color:var(--accent)}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;max-width:760px}
  .controls{margin-left:auto;display:flex;gap:13px;align-items:center;flex-wrap:wrap}
  label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
  select,input{background:var(--surface);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:5px 8px;font-family:inherit;font-size:12px}
  input[type=number]{width:66px}

  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin-bottom:22px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:9px 11px}
  .card .l{color:var(--muted);font-size:9.5px;letter-spacing:.07em;text-transform:uppercase}
  .card .v{font-size:19px;font-weight:700;font-family:'Space Grotesk',sans-serif;margin-top:2px}

  .tw{max-height:640px;overflow:auto;border:1px solid var(--line);border-radius:3px}
  table{border-collapse:collapse;width:100%;font-size:11.5px}
  thead th{position:sticky;top:0;z-index:2;background:var(--raised);color:var(--muted);
    font-weight:500;font-size:10px;letter-spacing:.06em;text-transform:uppercase;
    text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap}
  thead th:hover{color:var(--accent)}
  thead th.on{color:var(--accent)}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:4px 9px;border-bottom:1px solid rgba(46,51,64,.45);white-space:nowrap}
  tbody tr:hover td{background:var(--surface)}
  td.ts{color:var(--muted);font-size:11px}
  .chip{display:inline-block;min-width:62px;text-align:right;padding:2px 7px;border-radius:3px;
        font-size:11px;font-weight:700;color:#0d0f14;font-variant-numeric:tabular-nums}
  a{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--line)}
  a:hover{color:var(--accent);border-bottom-color:var(--accent)}
  .tag{font-size:9.5px;letter-spacing:.05em;padding:1px 5px;border-radius:2px;border:1px solid var(--line);color:var(--muted)}
  .tag.otm{color:var(--r2);border-color:var(--r2)}
  .empty{color:var(--muted);padding:16px;font-size:12px}
  .legend{display:flex;gap:15px;flex-wrap:wrap;margin-top:10px;font-size:10.5px;color:var(--muted)}
  .legend .k{display:inline-flex;align-items:center;gap:5px}
  .sw{width:11px;height:11px;border-radius:2px;display:inline-block}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1><span class="k">multibaggers</span> — ground truth</h1>
      <div class="sub">Every trade that existed, with no signal involved. Entry is the exact
        bottom and exit the exact top, so these are upper bounds no strategy reaches — the
        denominator your signals are measured against, not a target.</div>
    </div>
    <div class="controls">
      <span><label for="spot">Spot</label> <select id="spot"></select></span>
      <span><label for="min">Min ratio</label> <input type="number" id="min" value="10" min="1" step="1"></span>
      <span><label for="type">Type</label>
        <select id="type"><option value="both">Both</option><option value="C">Calls</option><option value="P">Puts</option></select></span>
      <span><label for="money">Moneyness</label>
        <select id="money"><option value="all">All</option><option value="otm">OTM only</option><option value="itm">ITM only</option></select></span>
      <span><label for="exp">Expiry</label> <select id="exp"><option value="">All</option></select></span>
    </div>
  </header>

  <div class="cards" id="cards"></div>
  <div class="tw"><div id="tbl"></div></div>
  <div class="legend" id="legend"></div>
</div>

<script>
// Chart links are built server-side with a placeholder host; swap in whatever
// host actually served this page so links work from any device on the LAN.
document.addEventListener('DOMContentLoaded',()=>{},{once:true});
const CHART_HOST=location.hostname;
function fixChartUrl(u){ return String(u||'').replace('__CHART_HOST__',CHART_HOST); }
const RCOL=['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
const BANDS=${JSON.stringify(cfg.RATIO_BANDS.map(b => ({ label: b.label, min: b.min, max: b.max === Infinity ? null : b.max })))};
const THR=${JSON.stringify(cfg.MULTIBAGGER_THRESHOLDS)};
let DATA=null, SORT='ratio', DESC=true;

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs=t=>String(t).slice(0,16).replace('T',' ');
function band(v){for(let i=0;i<BANDS.length;i++){const b=BANDS[i];if(v>=b.min&&(b.max===null||v<b.max))return i;}return BANDS.length-1;}

const COLS=[
  {k:'ratio',    l:'Ratio',   num:true,  tip:'Peak high after entry / entry close. Perfect hindsight.'},
  {k:'symbol',   l:'Instrument', num:false, tip:'Contract. Links to its chart.'},
  {k:'expiry',   l:'Expiry',  num:false, tip:'Settlement date'},
  {k:'type',     l:'T',       num:false, tip:'C = call, P = put'},
  {k:'strike',   l:'Strike',  num:true,  tip:'Strike price'},
  {k:'distancePct',l:'OTM%',  num:true,  tip:'Distance from spot at entry. Negative = ITM.'},
  {k:'entryTs',  l:'Entry',   num:false, tip:'When the bottom was'},
  {k:'entryPrice',l:'Buy',    num:true,  tip:'Entry close'},
  {k:'peakTs',   l:'Peak',    num:false, tip:'When the top was'},
  {k:'peakPrice',l:'Sell',    num:true,  tip:'Highest high after entry'},
  {k:'holdHours',l:'Hold h',  num:true,  tip:'Hours from entry to peak'},
  {k:'duration', l:'Dur',     num:true,  tip:'Candle duration used. Finest stored, so the bottom is not hidden.'},
];

function filtered(){
  if(!DATA) return [];
  const min=parseFloat($('min').value)||0, t=$('type').value, m=$('money').value, e=$('exp').value;
  return DATA.rows.filter(r=>
    r.ratio>=min &&
    (t==='both'||r.type===t) &&
    (m==='all'|| (m==='otm'? r.otm===true : r.otm===false)) &&
    (!e||r.expiry===e));
}

function renderCards(rows){
  const c=[];
  c.push(['shown', rows.length.toLocaleString()]);
  for(const t of THR) c.push([t+'x', rows.filter(r=>r.ratio>=t).length.toLocaleString()]);
  c.push(['best', rows.length? Math.round(rows[0].ratio).toLocaleString()+'x':'—']);
  c.push(['expiries', DATA?DATA.expiries:0]);
  c.push(['scanned', DATA?DATA.scanned.toLocaleString():0]);
  $('cards').innerHTML=c.map(([l,v])=>'<div class="card"><div class="l">'+esc(l)+'</div><div class="v">'+esc(v)+'</div></div>').join('');
}

function render(){
  const rows=filtered();
  renderCards(rows);

  if(!rows.length){ $('tbl').innerHTML='<div class="empty">Nothing matches. Lower the minimum ratio, or run multibaggers.js first.</div>'; return; }

  rows.sort((a,b)=>{
    const x=a[SORT], y=b[SORT];
    if(typeof x==='number'&&typeof y==='number') return DESC? y-x : x-y;
    return DESC? (String(y)>String(x)?1:-1) : (String(x)>String(y)?1:-1);
  });

  // Capped for DOM sanity: a full history can be tens of thousands of rows and
  // the point is the top of the list, not exhaustive scrolling.
  const cap=rows.slice(0,1000);

  let h='<table><thead><tr>';
  for(const c of COLS) h+='<th class="'+(c.num?'num ':'')+(SORT===c.k?'on':'')+'" data-k="'+c.k+'" title="'+esc(c.tip)+'">'+esc(c.l)+(SORT===c.k?(DESC?' ▾':' ▴'):'')+'</th>';
  h+='</tr></thead><tbody>';

  for(const r of cap){
    const b=band(r.ratio);
    h+='<tr>'+
      '<td class="num"><span class="chip" style="background:'+RCOL[b]+'">'+r.ratio.toLocaleString()+'x</span></td>'+
      '<td><a href="'+esc(fixChartUrl(r.chartUrl))+'" target="_blank" rel="noopener">'+esc(r.symbol)+' ↗</a></td>'+
      '<td class="ts">'+esc(r.expiry)+'</td>'+
      '<td>'+esc(r.type)+'</td>'+
      '<td class="num">'+r.strike+'</td>'+
      '<td class="num">'+(r.distancePct==null?'—':
         '<span class="tag'+(r.otm?' otm':'')+'">'+r.distancePct+'%</span>')+'</td>'+
      '<td class="ts">'+esc(shortTs(r.entryTs))+'</td>'+
      '<td class="num">'+r.entryPrice+'</td>'+
      '<td class="ts">'+esc(shortTs(r.peakTs))+'</td>'+
      '<td class="num">'+r.peakPrice+'</td>'+
      '<td class="num">'+r.holdHours+'</td>'+
      '<td class="num">'+r.duration+'m</td></tr>';
  }
  h+='</tbody></table>';
  if(rows.length>cap.length) h+='<div class="empty">Showing top '+cap.length.toLocaleString()+' of '+rows.length.toLocaleString()+'. Raise the minimum ratio to narrow.</div>';
  $('tbl').innerHTML=h;

  $('tbl').querySelectorAll('th[data-k]').forEach(th=>{
    th.addEventListener('click',()=>{
      const k=th.dataset.k;
      if(SORT===k) DESC=!DESC; else { SORT=k; DESC=true; }
      render();
    });
  });
}

async function loadSpot(s){
  $('tbl').innerHTML='<div class="empty">Loading…</div>';
  DATA=await (await fetch('/api/rows/'+encodeURIComponent(s))).json();
  const exps=[...new Set(DATA.rows.map(r=>r.expiry))].sort().reverse();
  $('exp').innerHTML='<option value="">All</option>'+exps.map(e=>'<option>'+esc(e)+'</option>').join('');
  render();
}

(async function init(){
  $('legend').innerHTML='<span class="k">ratio</span>'+
    BANDS.map((b,i)=>'<span class="k"><span class="sw" style="background:'+RCOL[i]+'"></span>'+esc(b.label)+'</span>').join('');
  const spots=await (await fetch('/api/spots')).json();
  if(!spots.length){ $('tbl').innerHTML='<div class="empty">No data. Run: node multibaggers.js</div>'; return; }
  $('spot').innerHTML=spots.map(s=>'<option>'+esc(s)+'</option>').join('');
  $('spot').addEventListener('change',()=>loadSpot($('spot').value));
  ['min','type','money','exp'].forEach(id=>$(id).addEventListener('input',render));
  await loadSpot(spots[0]);
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
    const url = decodeURIComponent(req.url.split('?')[0]);
    try {
        if (url === '/' || url === '/index.html') {
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
            return res.end(renderPage());
        }
        if (url === '/api/spots') return json(res, listSpots());
        const m = url.match(/^\/api\/rows\/([^/]+)$/);
        if (m) return json(res, loadRows(m[1]));
        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, '0.0.0.0', () => {
    console.log(netinfo.banner('Multibaggers — ground truth', PORT));
});
