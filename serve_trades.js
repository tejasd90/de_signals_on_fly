// serve_trades.js
// ─────────────────────────────────────────────────────────────────────────────
// Browser for the trades trades.js found. Run: node serve_trades.js  (port 3400)
//
// Purpose is inspection, not measurement: look at the biggest moves that
// happened and ask what the candles looked like BEFORE the low. That is where a
// missed pattern would show, so chart links open well before the trade window.
//
// LAYOUT
//   1. A horizontally scrollable calendar. Each expiry date is split — top half
//      shaded by the best CALL ratio that day, bottom half by the best PUT. A
//      whole history is ~1000 expiries, and picking one out of a dropdown that
//      long is unusable; here the interesting dates are visible as colour.
//   2. Every duration for the chosen date, stacked. Ordered by that side's own
//      max ratio, so the strongest duration is on top — and calls and puts are
//      ordered independently, because the duration that worked for one side
//      routinely is not the one that worked for the other.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg  = require('./config');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3400;
const DIR  = path.join(cfg.DATA_BASE_DIR, 'trades');

const CHART_BASE = 'http://localhost:3000/de';

// Lead-in before the trade window. Longer than the 20 used for signals: the
// question is what the setup looked like before the low, and opening at the low
// shows only the answer.
const CHART_LEAD_CANDLES = 40;

// ─── Paths and helpers ────────────────────────────────────────────────────────

function listSpots() {
    if (!fs.existsSync(DIR)) return [];
    return fs.readdirSync(DIR)
        .filter(d => !d.startsWith('.') && fs.statSync(path.join(DIR, d)).isDirectory())
        .sort();
}

function expiryDirs(spot) {
    const d = path.join(DIR, spot);
    if (!fs.existsSync(d)) return [];
    return fs.readdirSync(d)
        .filter(x => !x.startsWith('.') && fs.statSync(path.join(d, x)).isDirectory())
        .sort();
}

function durationsOf(spot, expiry) {
    const d = path.join(DIR, spot, expiry);
    if (!fs.existsSync(d)) return [];
    return fs.readdirSync(d)
        .filter(f => f.endsWith('.json') && !f.startsWith('_') && !f.includes('.tmp.'))
        .map(f => parseInt(f.replace('.json', '')))
        .filter(n => !isNaN(n))
        .sort((a, b) => a - b);
}

function pad(n) { return String(n).padStart(2, '0'); }
function istOf(ms) {
    const d = new Date(ms + (5 * 60 + 30) * 60000);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
           `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00+0530`;
}

function chartUrl(expiry, symbol, startMs, duration) {
    const from = istOf(startMs - CHART_LEAD_CANDLES * duration * 60000);
    return `${CHART_BASE}/${expiry}/${symbol}/${from}/${expiry}T18:00:00+0530/${duration}`;
}

// ─── Calendar summary ─────────────────────────────────────────────────────────

// Cached per spot: the calendar is read on every date click and rebuilding it
// each time would re-read a thousand files.
const _calCache = new Map();

/**
 * One row per expiry: best call ratio, best put ratio, durations available.
 *
 * Prefers the _summary.json trades.js writes. Where that is missing — data
 * computed before summaries existed — it scans the duration files once and
 * writes the summary, so the cost is paid a single time rather than per view.
 */
function calendarFor(spot) {
    if (_calCache.has(spot)) return _calCache.get(spot);

    const out = [];
    for (const expiry of expiryDirs(spot)) {
        const sp = path.join(DIR, spot, expiry, '_summary.json');

        let s = null;
        if (fs.existsSync(sp)) {
            try { s = JSON.parse(fs.readFileSync(sp, 'utf8')); } catch (_) { s = null; }
        }

        if (!s) {
            // Self-heal: build and persist it so this only ever happens once.
            try { s = require('./trades').writeSummary(spot, expiry); } catch (_) { s = null; }
        }
        if (!s) continue;

        out.push({
            expiry,
            C: s.C || 0,
            P: s.P || 0,
            cCount: s.cCount || 0,
            pCount: s.pCount || 0,
            durations: s.durations || durationsOf(spot, expiry),
        });
    }

    out.sort((a, b) => a.expiry < b.expiry ? -1 : 1);
    _calCache.set(spot, out);
    return out;
}

// ─── All durations for one expiry ─────────────────────────────────────────────

/**
 * Every duration for one expiry, each side ordered by its own max ratio.
 *
 * The two sides are ordered independently on purpose: the duration that produced
 * the biggest call move is frequently not the one that produced the biggest put
 * move, and forcing a shared order would bury one of them.
 */
function loadExpiry(spot, expiry) {
    const durations = durationsOf(spot, expiry);
    const panels = [];

    for (const duration of durations) {
        const p = path.join(DIR, spot, expiry, `${duration}.json`);
        let d;
        try { d = JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { continue; }

        for (const type of ['C', 'P']) {
            for (const ev of (d[type] || [])) {
                ev.startIso = istOf(ev.startMs);
                ev.endIso   = istOf(ev.endMs);
                for (const i of ev.instruments) {
                    i.url = chartUrl(expiry, i.symbol, ev.startMs, duration);
                }
            }
        }

        const maxOf = arr => arr.length ? Math.max(...arr.map(e => e.maxRatio)) : 0;
        panels.push({
            duration,
            C: d.C || [], P: d.P || [],
            maxC: maxOf(d.C || []), maxP: maxOf(d.P || []),
            scanned: d.scanned || 0,
        });
    }

    return {
        spot, expiry, durations,
        // Two orderings by duration index, resolved client-side.
        orderC: panels.slice().sort((a, b) => b.maxC - a.maxC).map(p => p.duration),
        orderP: panels.slice().sort((a, b) => b.maxP - a.maxP).map(p => p.duration),
        panels,
    };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trades — what actually happened</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{--ground:#14161c;--surface:#1c1f28;--raised:#242833;--line:#2e3340;
        --text:#c8ccd8;--muted:#6b7183;--accent:#d4703a;
        --r0:#3d4454;--r1:#5b7c99;--r2:#6a9d7f;--r3:#b8a44c;--r4:#d4703a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1,h2,h3{font-family:'Space Grotesk',system-ui,sans-serif;margin:0}
  .wrap{max-width:1700px;margin:0 auto;padding:22px 20px 70px}

  header{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;
         padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:16px}
  h1{font-size:18px;font-weight:700} h1 .k{color:var(--accent)}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;max-width:820px}
  .controls{margin-left:auto;display:flex;gap:13px;align-items:center;flex-wrap:wrap}
  label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
  select,input{background:var(--surface);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:5px 8px;font-family:inherit;font-size:12px}
  input#filter{width:110px}
  .hint{color:var(--muted);font-size:10px}

  /* ── Calendar ── */
  .calwrap{overflow-x:auto;border:1px solid var(--line);border-radius:3px;
           background:var(--surface);padding:10px;margin-bottom:8px}
  .cal{display:flex;gap:16px;min-width:max-content}
  .month{flex:none}
  .month .mlabel{color:var(--muted);font-size:10px;letter-spacing:.07em;
                 text-transform:uppercase;margin-bottom:4px;text-align:center}
  .dow{display:grid;grid-template-columns:repeat(7,20px);gap:2px;margin-bottom:2px}
  .dow span{color:#4a4f5e;font-size:8px;text-align:center}
  .days{display:grid;grid-template-columns:repeat(7,20px);gap:2px}
  .day{width:20px;height:20px;border-radius:2px;position:relative;overflow:hidden;
       background:#191c24;font-size:8.5px;color:#3f4450;display:flex;align-items:center;
       justify-content:center}
  .day.has{cursor:pointer;color:#0d0f14;font-weight:700}
  .day.has:hover{outline:1px solid var(--accent);outline-offset:0}
  .day.sel{outline:2px solid var(--accent);outline-offset:0}
  /* Split cell: top half = best call, bottom half = best put. Two stacked
     halves rather than a gradient, so each can carry its own tooltip. */
  .day .h{position:absolute;left:0;right:0;height:50%}
  .day .h.t{top:0} .day .h.b{bottom:0}
  .day .n{position:relative;z-index:1;text-shadow:0 0 2px rgba(0,0,0,.35)}

  .callegend{display:flex;gap:14px;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-bottom:18px}
  .callegend .k{display:inline-flex;align-items:center;gap:5px}
  .sw{width:11px;height:11px;border-radius:2px;display:inline-block}
  .swsplit{width:11px;height:11px;border-radius:2px;display:inline-block;position:relative;overflow:hidden}
  .swsplit i{position:absolute;left:0;right:0;height:50%}

  /* ── Duration panels ── */
  .cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:1300px){.cols{grid-template-columns:1fr}}
  .side>h2{font-size:14px;font-weight:700;margin-bottom:2px}
  .side>.n{color:var(--muted);font-size:11px;margin-bottom:10px}

  .dpanel{border:1px solid var(--line);border-radius:3px;margin-bottom:10px;background:var(--surface)}
  .dhead{display:flex;align-items:baseline;gap:10px;padding:6px 10px;
         background:var(--raised);border-bottom:1px solid var(--line);cursor:pointer}
  .dhead:hover{color:var(--accent)}
  .dhead .d{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:13px;min-width:46px}
  .dhead .m{margin-left:auto}
  .dhead .c{color:var(--muted);font-size:10.5px}
  .dbody{max-height:420px;overflow:auto}
  .dpanel.collapsed .dbody{display:none}

  table{border-collapse:collapse;width:100%;font-size:11.5px}
  thead th{position:sticky;top:0;z-index:2;background:var(--raised);color:var(--muted);
    font-weight:500;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;
    text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:4px 8px;border-bottom:1px solid rgba(46,51,64,.4);vertical-align:top}
  tbody tr:hover td{background:#1f2330}
  td.ts{color:var(--muted);font-size:10.5px;white-space:nowrap}
  .chip{display:inline-block;min-width:58px;text-align:right;padding:2px 6px;border-radius:3px;
        font-size:10.5px;font-weight:700;color:#0d0f14;font-variant-numeric:tabular-nums}
  .instr{display:flex;flex-wrap:wrap;gap:3px;max-width:380px}
  .instr a{color:var(--muted);text-decoration:none;font-size:10px;background:#1a1d25;
    border:1px solid var(--line);border-radius:3px;padding:1px 5px;white-space:nowrap}
  .instr a:hover{color:var(--accent);border-color:var(--accent)}
  .instr a.best{color:var(--accent);border-color:var(--accent);font-weight:700}
  .tag{font-size:9px;padding:0 4px;border-radius:2px;border:1px solid var(--line);color:var(--muted)}
  .tag.otm{color:var(--r2);border-color:var(--r2)}
  .empty{color:var(--muted);padding:12px;font-size:11.5px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1><span class="k">trades</span> — what actually happened</h1>
      <div class="sub">Every move found by recursive partitioning, merged across strikes.
        Calendar: top half of each date is the best call ratio, bottom half the best put.
        Click a date. Durations are stacked strongest-first, ordered separately per side.
        Charts open 40 candles before the low, so you see the setup rather than the move.</div>
    </div>
    <div class="controls">
      <span><label for="spot">Spot</label> <select id="spot"></select></span>
      <span><label for="filter">Ratio filter</label>
        <input id="filter" placeholder="&gt;40x" title="e.g.  >40x   >=100   <20   50-200">
        <div class="hint" id="fhint"></div></span>
    </div>
  </header>

  <div class="calwrap"><div class="cal" id="cal"></div></div>
  <div class="callegend" id="callegend"></div>

  <div id="sel" class="sub" style="margin-bottom:12px"></div>
  <div class="cols">
    <div class="side"><h2>Calls</h2><div class="n" id="nC"></div><div id="panC"></div></div>
    <div class="side"><h2>Puts</h2><div class="n" id="nP"></div><div id="panP"></div></div>
  </div>
</div>

<script>
const RCOL=['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
const BANDS=${JSON.stringify(cfg.RATIO_BANDS.map(b => ({ label: b.label, min: b.min, max: b.max === Infinity ? null : b.max })))};
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let CAL=null, DATA=null, COLLAPSED={};

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs=t=>String(t).slice(5,16).replace('T',' ');
function band(v){if(!(v>0))return null;for(let i=0;i<BANDS.length;i++){const b=BANDS[i];if(v>=b.min&&(b.max===null||v<b.max))return i;}return BANDS.length-1;}
function col(v){const b=band(v);return b===null?'transparent':RCOL[b];}

function parseFilter(raw){
  const s=(raw||'').trim().toLowerCase().replace(/x/g,'').replace(/\\s+/g,'');
  if(!s) return {fn:()=>true,label:''};
  let m;
  if((m=s.match(/^>=(-?[\\d.]+)$/))) return {fn:v=>v>=+m[1],label:'≥ '+m[1]+'x'};
  if((m=s.match(/^>(-?[\\d.]+)$/)))  return {fn:v=>v> +m[1],label:'> '+m[1]+'x'};
  if((m=s.match(/^<=(-?[\\d.]+)$/))) return {fn:v=>v<=+m[1],label:'≤ '+m[1]+'x'};
  if((m=s.match(/^<(-?[\\d.]+)$/)))  return {fn:v=>v< +m[1],label:'< '+m[1]+'x'};
  if((m=s.match(/^([\\d.]+)-([\\d.]+)$/))) return {fn:v=>v>=+m[1]&&v<=+m[2],label:m[1]+'–'+m[2]+'x'};
  if((m=s.match(/^([\\d.]+)$/)))     return {fn:v=>v>=+m[1],label:'≥ '+m[1]+'x'};
  return {fn:()=>true,label:'unrecognised'};
}

// ── Calendar ──
function renderCal(){
  if(!CAL||!CAL.length){ $('cal').innerHTML='<div class="empty">No trades computed. Run: node trades.js</div>'; return; }

  const byExp=new Map(CAL.map(r=>[r.expiry,r]));
  const first=CAL[0].expiry, last=CAL[CAL.length-1].expiry;
  const [fy,fm]=first.split('-').map(Number), [ly,lm]=last.split('-').map(Number);

  let h='';
  for(let y=fy,m=fm; y<ly||(y===ly&&m<=lm); (m===12?(m=1,y++):m++)){
    const firstDow=(new Date(Date.UTC(y,m-1,1)).getUTCDay()+6)%7;   // Monday-first
    const days=new Date(Date.UTC(y,m,0)).getUTCDate();
    h+='<div class="month"><div class="mlabel">'+MON[m-1]+' '+String(y).slice(2)+'</div>'+
       '<div class="dow"><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span></div>'+
       '<div class="days">';
    for(let i=0;i<firstDow;i++) h+='<div></div>';
    for(let d=1;d<=days;d++){
      const iso=y+'-'+String(m).padStart(2,'0')+'-'+String(d).padStart(2,'0');
      const r=byExp.get(iso);
      if(!r){ h+='<div class="day">'+d+'</div>'; continue; }
      const tip=iso+'   calls '+(r.C?r.C.toLocaleString()+'x':'—')+' ('+r.cCount+' events)'+
                '   puts '+(r.P?r.P.toLocaleString()+'x':'—')+' ('+r.pCount+' events)';
      h+='<div class="day has'+(DATA&&DATA.expiry===iso?' sel':'')+'" data-e="'+iso+'" title="'+esc(tip)+'">'+
         '<span class="h t" style="background:'+col(r.C)+'"></span>'+
         '<span class="h b" style="background:'+col(r.P)+'"></span>'+
         '<span class="n">'+d+'</span></div>';
    }
    h+='</div></div>';
  }
  $('cal').innerHTML=h;

  $('cal').querySelectorAll('.day.has').forEach(el=>{
    el.addEventListener('click',()=>loadExpiry(el.dataset.e));
  });

  $('callegend').innerHTML=
    '<span class="k">top half = best call · bottom half = best put</span>'+
    BANDS.map((b,i)=>'<span class="k"><span class="sw" style="background:'+RCOL[i]+'"></span>'+esc(b.label)+'</span>').join('')+
    '<span class="k"><span class="swsplit"><i style="top:0;background:'+RCOL[4]+'"></i>'+
    '<i style="bottom:0;background:'+RCOL[1]+'"></i></span>split example</span>';
}

// ── Duration panels ──
function renderSide(type){
  const wrap=$('pan'+type);
  if(!DATA){ wrap.innerHTML=''; return; }

  const f=parseFilter($('filter').value);
  $('fhint').textContent=f.label;

  const order=type==='C'?DATA.orderC:DATA.orderP;
  const byDur=new Map(DATA.panels.map(p=>[p.duration,p]));

  let total=0, shown=0, html='';
  for(const dur of order){
    const p=byDur.get(dur); if(!p) continue;
    const all=p[type]||[];
    total+=all.length;
    const evs=all.filter(e=>f.fn(e.maxRatio));
    if(!evs.length) continue;
    shown+=evs.length;

    const dmax=type==='C'?p.maxC:p.maxP;
    const key=type+dur;
    const collapsed=COLLAPSED[key]?' collapsed':'';

    html+='<div class="dpanel'+collapsed+'" data-k="'+key+'">'+
      '<div class="dhead"><span class="d">'+dur+'m</span>'+
      '<span class="chip" style="background:'+(band(dmax)===null?'var(--r0)':RCOL[band(dmax)])+'">'+dmax.toLocaleString()+'x</span>'+
      '<span class="c">'+evs.length+' events</span>'+
      '<span class="c m">'+(COLLAPSED[key]?'▸':'▾')+'</span></div>'+
      '<div class="dbody"><table><thead><tr>'+
      '<th class="num" title="Best ratio in this event">Ratio</th>'+
      '<th class="num" title="Instruments moving together">In</th>'+
      '<th title="Low to high, merged">Window</th>'+
      '<th class="num" title="Mean candles low to high">Hold</th>'+
      '<th class="num" title="Distance from spot of the best instrument">OTM%</th>'+
      '<th title="All contributors; best in bold">Instruments</th></tr></thead><tbody>';

    for(const e of evs.slice(0,300)){
      html+='<tr>'+
        '<td class="num"><span class="chip" style="background:'+RCOL[band(e.maxRatio)]+'">'+e.maxRatio.toLocaleString()+'x</span></td>'+
        '<td class="num">'+e.count+'</td>'+
        '<td class="ts">'+esc(shortTs(e.startIso))+'<br>'+esc(shortTs(e.endIso))+'</td>'+
        '<td class="num">'+e.holdCandles+'</td>'+
        '<td class="num">'+(e.distancePct==null?'—':'<span class="tag'+(e.otm?' otm':'')+'">'+e.distancePct+'%</span>')+'</td>'+
        '<td><div class="instr">'+e.instruments.map(i=>
          '<a href="'+esc(i.url)+'" target="_blank" rel="noopener" class="'+(i.symbol===e.maxSymbol?'best':'')+
          '" title="'+esc(i.symbol+'  '+i.ratio+'x')+'">'+esc(i.symbol)+' '+i.ratio+'x</a>').join('')+
        '</div></td></tr>';
    }
    html+='</tbody></table>';
    if(evs.length>300) html+='<div class="empty">Showing 300 of '+evs.length+'.</div>';
    html+='</div></div>';
  }

  $('n'+type).textContent = shown+' events'+(shown!==total?' of '+total:'')+
    '   ·   '+order.length+' durations, strongest first';
  wrap.innerHTML = html || '<div class="empty">No events match the filter.</div>';

  wrap.querySelectorAll('.dhead').forEach(hd=>{
    hd.addEventListener('click',()=>{
      const k=hd.parentElement.dataset.k;
      COLLAPSED[k]=!COLLAPSED[k];
      renderSide(type);
    });
  });
}

async function loadExpiry(expiry){
  $('sel').textContent='Loading '+expiry+'…';
  DATA=await (await fetch('/api/expiry/'+encodeURIComponent($('spot').value)+'/'+encodeURIComponent(expiry))).json();
  const r=(CAL||[]).find(x=>x.expiry===expiry)||{};
  $('sel').innerHTML='<b>'+esc(expiry)+'</b> — '+DATA.durations.length+' durations, '+
    (DATA.panels[0]?DATA.panels[0].scanned:0)+' instruments scanned'+
    '   ·   best call <b>'+(r.C||0).toLocaleString()+'x</b>   best put <b>'+(r.P||0).toLocaleString()+'x</b>';
  renderCal();                 // refresh the selected-date outline
  renderSide('C'); renderSide('P');
}

async function loadSpot(){
  $('cal').innerHTML='<div class="empty">Loading calendar…</div>';
  CAL=await (await fetch('/api/calendar/'+encodeURIComponent($('spot').value))).json();
  DATA=null; $('panC').innerHTML=''; $('panP').innerHTML='';
  renderCal();
  // Open the most recent expiry that produced anything, so the page is never blank.
  const withData=CAL.filter(r=>r.C>0||r.P>0);
  const pick=(withData.length?withData:CAL).slice(-1)[0];
  if(pick) await loadExpiry(pick.expiry);
}

(async function init(){
  const spots=await (await fetch('/api/spots')).json();
  if(!spots.length){ $('cal').innerHTML='<div class="empty">No data. Run: node trades.js</div>'; return; }
  $('spot').innerHTML=spots.map(s=>'<option>'+esc(s)+'</option>').join('');
  $('spot').addEventListener('change',loadSpot);
  $('filter').addEventListener('input',()=>{renderSide('C');renderSide('P');});
  await loadSpot();
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

        let m = url.match(/^\/api\/calendar\/([^/]+)$/);
        if (m) return json(res, calendarFor(m[1]));

        m = url.match(/^\/api\/expiry\/([^/]+)\/([^/]+)$/);
        if (m) return json(res, loadExpiry(m[1], m[2]));

        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, () => {
    console.log('');
    console.log(`Trades  →  http://localhost:${PORT}`);
    console.log(`  data : ${DIR}`);
    console.log('');
});
