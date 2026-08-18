// serve_signals_cal.js
// ─────────────────────────────────────────────────────────────────────────────
// Calendar browser for signals. Run: node serve_signals_cal.js  (port 3500)
//   node serve_signals_cal.js --signal otm_wall --port 3501
//
// A second view onto the same data serve_signals.js shows, laid out the way
// serve_trades.js is. serve_signals.js stays as it is — its matrix and
// expiry-by-duration grid answer "does strength predict payoff", a research
// question. This answers "which dates produced moves, and at which duration",
// which is a browsing question and wants a calendar rather than a tree.
//
//   1. Horizontally scrollable calendar. Each expiry date split — top half
//      shaded by the best CALL ratio, bottom half by the best PUT.
//   2. Every duration for the chosen date, stacked, ordered by that side's own
//      max ratio. The two sides are ordered independently, since the duration
//      that worked for calls routinely is not the one that worked for puts.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg    = require('./config');
const writer = require('./writer');
const api    = require('./api');
const expiryMod = require('./expiry');

const args = process.argv.slice(2);
const PORT      = args.includes('--port')   ? parseInt(args[args.indexOf('--port') + 1]) : 3500;
// Mutable, because the page lets you switch signal without restarting. Every
// listing helper reads it, so a setter keeps their signatures free of an id
// argument that would otherwise thread through all of them.
let SIGNAL_ID = args.includes('--signal') ? args[args.indexOf('--signal') + 1] : 'red_squeeze';
function setSignal(id) { if (id && id !== SIGNAL_ID) SIGNAL_ID = id; }

const CHART_BASE = 'http://localhost:3000/de';
const CHART_LEAD_CANDLES = 40;
const CHART_TAIL_MINUTES = 30;

const signalRoot = () => path.join(cfg.SIGNALS_BASE_DIR, SIGNAL_ID);

// ─── Listing ──────────────────────────────────────────────────────────────────

function listSignalIds() {
    if (!fs.existsSync(cfg.SIGNALS_BASE_DIR)) return [];
    return fs.readdirSync(cfg.SIGNALS_BASE_DIR)
        .filter(d => !d.startsWith('.') &&
                     fs.statSync(path.join(cfg.SIGNALS_BASE_DIR, d)).isDirectory())
        .sort();
}

function listSpots() {
    const r = signalRoot();
    if (!fs.existsSync(r)) return [];
    return fs.readdirSync(r)
        .filter(d => !d.startsWith('.') && !d.startsWith('_') &&
                     fs.statSync(path.join(r, d)).isDirectory())
        .sort();
}

function durationDirs(spot) {
    const d = path.join(signalRoot(), spot);
    if (!fs.existsSync(d)) return [];
    return fs.readdirSync(d)
        .filter(x => !x.startsWith('.') && !x.startsWith('_') && !isNaN(x))
        .map(Number).sort((a, b) => a - b);
}

/** Settled expiries only — a live one has no outcome to show. */
function listExpiries(spot) {
    const seen = new Set();
    for (const d of durationDirs(spot)) {
        const dir = path.join(signalRoot(), spot, String(d));
        for (const f of fs.readdirSync(dir)) {
            if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
            seen.add(f.replace(/\.json$/, ''));
        }
    }
    return [...seen].filter(e => expiryMod.isExpired(spot, e)).sort();
}

// ─── Calendar ─────────────────────────────────────────────────────────────────

const _calCache = new Map();

/**
 * One row per settled expiry with both ratio maxima per side.
 *
 * Prefers the summary written at generation time. Where it is absent — data
 * generated before summaries existed — it is built once and persisted, so the
 * cost is paid a single time rather than on every view.
 */
function calendarFor(spot) {
    const key = `${SIGNAL_ID}|${spot}`;
    if (_calCache.has(key)) return _calCache.get(key);

    const out = [];
    for (const expiry of listExpiries(spot)) {
        let s = writer.readExpirySummary(SIGNAL_ID, spot, expiry);
        if (!s) s = writer.writeExpirySummary(SIGNAL_ID, spot, expiry);
        if (!s) continue;
        out.push({
            expiry,
            firedC: s.firedC || 0, firedP: s.firedP || 0,
            univC:  s.univC  || 0, univP:  s.univP  || 0,
            cCount: s.cCount || 0, pCount: s.pCount || 0,
            durations: s.durations || [],
        });
    }
    _calCache.set(key, out);
    return out;
}

// ─── One expiry, all durations ────────────────────────────────────────────────

function pad(n) { return String(n).padStart(2, '0'); }
function istOf(ms) {
    const d = new Date(ms + (5 * 60 + 30) * 60000);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
           `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00+0530`;
}

function chartUrl(spot, expiry, symbol, startTs, duration) {
    const from = istOf(new Date(startTs).getTime() - CHART_LEAD_CANDLES * duration * 60000);
    const to   = istOf(expiryMod.expiryMillis(spot, expiry) + CHART_TAIL_MINUTES * 60000);
    return `${CHART_BASE}/${expiry}/${symbol}/${from}/${to}/${duration}`;
}

function loadExpiry(spot, expiry) {
    const panels = [];

    for (const duration of durationDirs(spot)) {
        const data = writer.readSignals(SIGNAL_ID, spot, duration, expiry);
        const conv = type => (data[type] || []).map(r => {
            const [startTs, endTs, count, sv, fired, state, instruments, univ, univSym] = r;
            return {
                startTs, endTs, count,
                signalValue: Number(sv) || 0,
                fired: Number(fired) || 0,
                univ:  Number(univ)  || 0,
                state,
                univSymbol: univSym || null,
                univUrl: univSym ? chartUrl(spot, expiry, univSym, startTs, duration) : null,
                instruments: (instruments || []).map(sym => ({
                    symbol: sym, url: chartUrl(spot, expiry, sym, startTs, duration),
                })),
            };
        });

        const C = conv('C'), P = conv('P');
        if (!C.length && !P.length) continue;

        const mx = (arr, k) => arr.length ? Math.max(...arr.map(e => e[k])) : 0;
        panels.push({
            duration, C, P,
            maxFiredC: mx(C, 'fired'), maxFiredP: mx(P, 'fired'),
            maxUnivC:  mx(C, 'univ'),  maxUnivP:  mx(P, 'univ'),
        });
    }

    return { signalId: SIGNAL_ID, spot, expiry, panels };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${SIGNAL_ID} — calendar</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{--ground:#14161c;--surface:#1c1f28;--raised:#242833;--line:#2e3340;
        --text:#c8ccd8;--muted:#6b7183;--accent:#d4703a;
        --r0:#3d4454;--r1:#5b7c99;--r2:#6a9d7f;--r3:#b8a44c;--r4:#d4703a;
        --s0:#34304a;--s1:#464067;--s2:#5d5488;--s3:#7a6cae;--s4:#9d8bd4;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1,h2{font-family:'Space Grotesk',system-ui,sans-serif;margin:0}
  .wrap{max-width:1700px;margin:0 auto;padding:22px 20px 70px}
  header{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;
         padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:16px}
  h1{font-size:18px;font-weight:700} h1 .k{color:var(--accent)}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;max-width:840px}
  .controls{margin-left:auto;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
  select,input{background:var(--surface);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:5px 8px;font-family:inherit;font-size:12px}
  input#filter{width:105px}
  .hint{color:var(--muted);font-size:10px}
  .toggle{display:inline-flex;border:1px solid var(--line);border-radius:3px;overflow:hidden}
  .toggle button{background:var(--surface);color:var(--muted);border:0;cursor:pointer;
    font-family:inherit;font-size:11px;padding:5px 9px}
  .toggle button[aria-pressed=true]{background:var(--raised);color:var(--text)}

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
       background:#191c24;font-size:8.5px;color:#3f4450;display:flex;align-items:center;justify-content:center}
  .day.has{cursor:pointer;color:#0d0f14;font-weight:700}
  .day.has:hover{outline:1px solid var(--accent)}
  .day.sel{outline:2px solid var(--accent)}
  .day .h{position:absolute;left:0;right:0;height:50%}
  .day .h.t{top:0} .day .h.b{bottom:0}
  .day .n{position:relative;z-index:1;text-shadow:0 0 2px rgba(0,0,0,.35)}
  .callegend{display:flex;gap:14px;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-bottom:18px}
  .callegend .k{display:inline-flex;align-items:center;gap:5px}
  .sw{width:11px;height:11px;border-radius:2px;display:inline-block}

  .cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:1300px){.cols{grid-template-columns:1fr}}
  .side>h2{font-size:14px;font-weight:700;margin-bottom:2px}
  .side>.n{color:var(--muted);font-size:11px;margin-bottom:10px}
  .dpanel{border:1px solid var(--line);border-radius:3px;margin-bottom:10px;background:var(--surface)}
  .dhead{display:flex;align-items:baseline;gap:10px;padding:6px 10px;
         background:var(--raised);border-bottom:1px solid var(--line);cursor:pointer}
  .dhead:hover{color:var(--accent)}
  .dhead .d{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:13px;min-width:46px}
  .dhead .c{color:var(--muted);font-size:10.5px}
  .dhead .m{margin-left:auto}
  .dbody{max-height:430px;overflow:auto}
  .dpanel.collapsed .dbody{display:none}

  table{border-collapse:collapse;width:100%;font-size:11.5px}
  thead th{position:sticky;top:0;z-index:2;background:var(--raised);color:var(--muted);
    font-weight:500;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;
    text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:help}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:4px 8px;border-bottom:1px solid rgba(46,51,64,.4);vertical-align:top}
  tbody tr:hover td{background:#1f2330}
  td.ts{color:var(--muted);font-size:10.5px;white-space:nowrap}
  .chip{display:inline-block;min-width:54px;text-align:right;padding:2px 6px;border-radius:3px;
        font-size:10.5px;font-weight:700;color:#0d0f14;font-variant-numeric:tabular-nums}
  .chip.univ{background:transparent!important;border:1px solid;font-weight:500}
  .instr{display:flex;flex-wrap:wrap;gap:3px;max-width:360px;align-items:center}
  .instr a{color:var(--muted);text-decoration:none;font-size:10px;background:#1a1d25;
    border:1px solid var(--line);border-radius:3px;padding:1px 5px;white-space:nowrap}
  .instr a:hover{color:var(--accent);border-color:var(--accent)}
  .instr .lbl{color:#4a4f5e;font-size:9px;text-transform:uppercase}
  .state{font-size:9px;text-transform:uppercase}
  .state.slHit{color:#8a5a5a} .state.activated{color:var(--r2)}
  .empty{color:var(--muted);padding:12px;font-size:11.5px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1><span class="k" id="sigName">${SIGNAL_ID}</span> — calendar</h1>
      <div class="sub">Settled expiries. Calendar: top half of each date is the best call ratio,
        bottom half the best put. Click a date; durations stack strongest-first, ordered
        separately per side. Charts open 40 candles before the pattern.</div>
    </div>
    <div class="controls">
      <span><label for="sig">Signal</label> <select id="sig"></select></span>
      <span><label for="spot">Spot</label> <select id="spot"></select></span>
      <span><label for="filter">Ratio filter</label>
        <input id="filter" placeholder="&gt;10x" title="e.g.  >10x   >=50   <5   10-100">
        <div class="hint" id="fhint"></div></span>
      <span><label>Payoff on</label><br>
        <span class="toggle" id="src">
          <button data-src="univ" aria-pressed="true">Best same-type</button>
          <button data-src="fired" aria-pressed="false">Fired only</button>
        </span></span>
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
const SCOL=['var(--s0)','var(--s1)','var(--s2)','var(--s3)','var(--s4)'];
const BANDS=${JSON.stringify(cfg.RATIO_BANDS.map(b => ({ label: b.label, min: b.min, max: b.max === Infinity ? null : b.max })))};
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
let CAL=null, DATA=null, SRC='univ', COLLAPSED={}, SBANDS=[];

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs=t=>String(t).slice(5,16).replace('T',' ');
function band(v){if(!(v>0))return null;for(let i=0;i<BANDS.length;i++){const b=BANDS[i];if(v>=b.min&&(b.max===null||v<b.max))return i;}return BANDS.length-1;}
function col(v){const b=band(v);return b===null?'transparent':RCOL[b];}
function sband(v){for(let i=0;i<SBANDS.length;i++){if(v<SBANDS[i].max)return i;}return Math.max(0,SBANDS.length-1);}

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

const calC=r=>SRC==='univ'?r.univC:r.firedC;
const calP=r=>SRC==='univ'?r.univP:r.firedP;
const evR =e=>SRC==='univ'?e.univ:e.fired;

function renderCal(){
  if(!CAL||!CAL.length){ $('cal').innerHTML='<div class="empty">No settled-expiry signals. Run backfill.js --signals-only.</div>'; $('callegend').innerHTML=''; return; }
  const byExp=new Map(CAL.map(r=>[r.expiry,r]));
  const [fy,fm]=CAL[0].expiry.split('-').map(Number);
  const [ly,lm]=CAL[CAL.length-1].expiry.split('-').map(Number);

  let h='';
  for(let y=fy,m=fm; y<ly||(y===ly&&m<=lm); (m===12?(m=1,y++):m++)){
    const firstDow=(new Date(Date.UTC(y,m-1,1)).getUTCDay()+6)%7;
    const days=new Date(Date.UTC(y,m,0)).getUTCDate();
    h+='<div class="month"><div class="mlabel">'+MON[m-1]+' '+String(y).slice(2)+'</div>'+
       '<div class="dow"><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span></div><div class="days">';
    for(let i=0;i<firstDow;i++) h+='<div></div>';
    for(let d=1;d<=days;d++){
      const iso=y+'-'+String(m).padStart(2,'0')+'-'+String(d).padStart(2,'0');
      const r=byExp.get(iso);
      if(!r){ h+='<div class="day">'+d+'</div>'; continue; }
      const c=calC(r), p=calP(r);
      const tip=iso+'   calls '+(c?c.toLocaleString()+'x':'—')+' ('+r.cCount+')'+
                '   puts '+(p?p.toLocaleString()+'x':'—')+' ('+r.pCount+')';
      h+='<div class="day has'+(DATA&&DATA.expiry===iso?' sel':'')+'" data-e="'+iso+'" title="'+esc(tip)+'">'+
         '<span class="h t" style="background:'+col(c)+'"></span>'+
         '<span class="h b" style="background:'+col(p)+'"></span>'+
         '<span class="n">'+d+'</span></div>';
    }
    h+='</div></div>';
  }
  $('cal').innerHTML=h;
  $('cal').querySelectorAll('.day.has').forEach(el=>el.addEventListener('click',()=>loadExpiry(el.dataset.e)));
  $('callegend').innerHTML='<span class="k">top = best call · bottom = best put</span>'+
    BANDS.map((b,i)=>'<span class="k"><span class="sw" style="background:'+RCOL[i]+'"></span>'+esc(b.label)+'</span>').join('');
}

function renderSide(type){
  const wrap=$('pan'+type);
  if(!DATA){ wrap.innerHTML=''; $('n'+type).textContent=''; return; }
  const f=parseFilter($('filter').value);
  $('fhint').textContent=f.label;

  // Ordered by this side's own max under the active ratio definition, so
  // switching the toggle can legitimately reorder the panels.
  const mk=p=>SRC==='univ'?(type==='C'?p.maxUnivC:p.maxUnivP):(type==='C'?p.maxFiredC:p.maxFiredP);
  const order=DATA.panels.slice().sort((a,b)=>mk(b)-mk(a));

  let total=0, shown=0, html='';
  for(const p of order){
    const all=p[type]||[]; total+=all.length;
    const evs=all.filter(e=>f.fn(evR(e)));
    if(!evs.length) continue;
    shown+=evs.length;
    evs.sort((a,b)=>evR(b)-evR(a));

    const dmax=mk(p), key=type+p.duration;
    html+='<div class="dpanel'+(COLLAPSED[key]?' collapsed':'')+'" data-k="'+key+'">'+
      '<div class="dhead"><span class="d">'+p.duration+'m</span>'+
      '<span class="chip" style="background:'+(band(dmax)===null?'var(--r0)':RCOL[band(dmax)])+'">'+dmax.toLocaleString()+'x</span>'+
      '<span class="c">'+evs.length+' signals</span>'+
      '<span class="c m">'+(COLLAPSED[key]?'▸':'▾')+'</span></div>'+
      '<div class="dbody"><table><thead><tr>'+
      '<th title="Timestamp of the entry candle">Entry</th>'+
      '<th class="num" title="Signal strength — scale differs per signal">Str</th>'+
      '<th class="num" title="Best multiple among instruments that FIRED">Fired</th>'+
      '<th class="num" title="Best multiple on ANY same-type strike">Best</th>'+
      '<th class="num" title="Instruments merged into this range">In</th>'+
      '<th title="activated / slHit / pending">State</th>'+
      '<th title="Contributors; dashed = best strike that did not fire">Instruments</th></tr></thead><tbody>';

    for(const e of evs.slice(0,300)){
      const fb=band(e.fired), ub=band(e.univ);
      const fired=new Set(e.instruments.map(i=>i.symbol));
      html+='<tr>'+
        '<td class="ts">'+esc(shortTs(e.endTs))+'</td>'+
        '<td class="num"><span class="chip" style="background:'+SCOL[sband(e.signalValue)]+'">'+e.signalValue.toFixed(0)+'</span></td>'+
        '<td class="num"><span class="chip" style="background:'+(fb===null?'var(--r0)':RCOL[fb])+'">'+e.fired.toFixed(2)+'x</span></td>'+
        '<td class="num"><span class="chip univ" style="color:'+(ub===null?'var(--muted)':RCOL[ub])+';border-color:'+(ub===null?'var(--line)':RCOL[ub])+'">'+e.univ.toFixed(2)+'x</span></td>'+
        '<td class="num">'+e.count+'</td>'+
        '<td><span class="state '+esc(e.state)+'">'+esc(e.state)+'</span></td>'+
        '<td><div class="instr"><span class="lbl">fired</span>'+
          e.instruments.map(i=>'<a href="'+esc(i.url)+'" target="_blank" rel="noopener">'+esc(i.symbol)+'</a>').join('')+
          (e.univSymbol && e.univUrl && !fired.has(e.univSymbol)
            ? '<span class="lbl">best</span><a href="'+esc(e.univUrl)+'" target="_blank" rel="noopener" style="border-style:dashed;color:'+
              (ub===null?'var(--muted)':RCOL[ub])+';border-color:'+(ub===null?'var(--line)':RCOL[ub])+'">'+
              esc(e.univSymbol)+' '+e.univ.toFixed(1)+'x</a>' : '')+
        '</div></td></tr>';
    }
    html+='</tbody></table>';
    if(evs.length>300) html+='<div class="empty">Showing 300 of '+evs.length+'.</div>';
    html+='</div></div>';
  }

  $('n'+type).textContent=shown+' signals'+(shown!==total?' of '+total:'')+
    '   ·   '+order.length+' durations, strongest first';
  wrap.innerHTML=html||'<div class="empty">No signals match the filter.</div>';
  wrap.querySelectorAll('.dhead').forEach(hd=>hd.addEventListener('click',()=>{
    COLLAPSED[hd.parentElement.dataset.k]=!COLLAPSED[hd.parentElement.dataset.k];
    renderSide(type);
  }));
}

/**
 * The summary line above the tables. Split out because it quotes the ACTIVE
 * ratio definition — leaving it out of the toggle handler meant the panels
 * reordered while this line kept showing the other definition's figures.
 */
function renderSel(){
  if(!DATA){ $('sel').textContent=''; return; }
  const r=(CAL||[]).find(x=>x.expiry===DATA.expiry)||{};
  $('sel').innerHTML='<b>'+esc(DATA.expiry)+'</b> — '+DATA.panels.length+' durations with signals'+
    '   ·   best call <b>'+(calC(r)||0).toLocaleString()+'x</b>'+
    '   best put <b>'+(calP(r)||0).toLocaleString()+'x</b>'+
    '   <span style="color:var(--muted)">('+(SRC==='univ'?'best same-type strike':'fired instrument only')+')</span>';
}

async function loadExpiry(expiry){
  $('sel').textContent='Loading '+expiry+'…';
  DATA=await (await fetch('/api/expiry/'+encodeURIComponent($('sig').value)+'/'+
    encodeURIComponent($('spot').value)+'/'+encodeURIComponent(expiry))).json();
  renderSel();
  renderCal(); renderSide('C'); renderSide('P');
}

async function loadSpot(){
  $('cal').innerHTML='<div class="empty">Loading calendar…</div>';
  const q='/api/calendar/'+encodeURIComponent($('sig').value)+'/'+encodeURIComponent($('spot').value);
  CAL=await (await fetch(q)).json();
  DATA=null; $('panC').innerHTML=''; $('panP').innerHTML=''; $('sel').textContent='';
  renderCal();
  const withData=CAL.filter(r=>calC(r)>0||calP(r)>0);
  const pick=(withData.length?withData:CAL).slice(-1)[0];
  if(pick) await loadExpiry(pick.expiry);
}

async function loadSignal(){
  const meta=await (await fetch('/api/meta/'+encodeURIComponent($('sig').value))).json();
  SBANDS=meta.strengthBands||[];
  $('sigName').textContent=$('sig').value;
  $('spot').innerHTML=(meta.spots||[]).map(s=>'<option>'+esc(s)+'</option>').join('');
  if(!meta.spots||!meta.spots.length){ $('cal').innerHTML='<div class="empty">No spots for this signal.</div>'; return; }
  await loadSpot();
}

(async function init(){
  const meta=await (await fetch('/api/signals')).json();
  if(!meta.length){ $('cal').innerHTML='<div class="empty">No signal data. Run backfill.js --signals-only.</div>'; return; }
  $('sig').innerHTML=meta.map(s=>'<option'+(s==='${SIGNAL_ID}'?' selected':'')+'>'+esc(s)+'</option>').join('');
  $('sig').addEventListener('change',loadSignal);
  $('spot').addEventListener('change',loadSpot);
  $('filter').addEventListener('input',()=>{renderSide('C');renderSide('P');});
  $('src').addEventListener('click',ev=>{
    const b=ev.target.closest('button[data-src]'); if(!b||b.dataset.src===SRC) return;
    SRC=b.dataset.src;
    $('src').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.src===SRC)));
    renderSel(); renderCal(); renderSide('C'); renderSide('P');
  });
  await loadSignal();
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
        if (url === '/api/signals') return json(res, listSignalIds());

        let m = url.match(/^\/api\/meta\/([^/]+)$/);
        if (m) {
            setSignal(m[1]);
            return json(res, {
                signalId: m[1],
                spots: listSpots(),
                strengthBands: cfg.strengthBandsFor(m[1])
                    .map(b => ({ label: b.label, max: b.max === Infinity ? Number.MAX_VALUE : b.max })),
            });
        }

        m = url.match(/^\/api\/calendar\/([^/]+)\/([^/]+)$/);
        if (m) { setSignal(m[1]); return json(res, calendarFor(m[2])); }

        m = url.match(/^\/api\/expiry\/([^/]+)\/([^/]+)\/([^/]+)$/);
        if (m) { setSignal(m[1]); return json(res, loadExpiry(m[2], m[3])); }

        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, () => {
    console.log('');
    console.log(`Signals calendar  →  http://localhost:${PORT}`);
    console.log(`  signal : ${SIGNAL_ID}  (switchable in the page)`);
    console.log(`  signals available: ${listSignalIds().join(', ') || '(none)'}`);
    console.log('');
});
