// serve_live.js
// ─────────────────────────────────────────────────────────────────────────────
// Live board for future expiries. Run: node serve_live.js   (default port 3200)
//
// Reads the snapshots live_runner writes and auto-refreshes. Deliberately a
// separate page from serve_signals: that one is a research tool for settled
// outcomes, this is a monitor for what is happening now, and the two want
// opposite layouts. Colour language and band definitions are shared, so a chip
// means the same thing on both.
//
// Three panels:
//   1. Signal tape      newest first, across every registered signal
//   2. Spot EMA spread  convergence per duration, sparkline plus current band
//   3. Volatility map   compressed per-strike heatmap, ATM marked, ITM/OTM split
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg  = require('./config');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3200;
const LIVE_DIR = path.join(cfg.DATA_BASE_DIR, 'live');

// ─── Snapshot reading ─────────────────────────────────────────────────────────

function listSnapshots() {
    if (!fs.existsSync(LIVE_DIR)) return [];
    const out = [];
    for (const spot of fs.readdirSync(LIVE_DIR)) {
        const dir = path.join(LIVE_DIR, spot);
        if (!fs.statSync(dir).isDirectory()) continue;
        for (const f of fs.readdirSync(dir)) {
            if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
            out.push({ spot, expiry: f.replace(/\.json$/, '') });
        }
    }
    return out.sort((a, b) => a.expiry < b.expiry ? -1 : 1);
}

function readSnapshot(spot, expiry) {
    const p = path.join(LIVE_DIR, spot, `${expiry}.json`);
    if (!fs.existsSync(p)) return null;
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live board</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{
    --ground:#14161c; --surface:#1c1f28; --raised:#242833; --line:#2e3340;
    --text:#c8ccd8; --muted:#6b7183; --accent:#d4703a;
    --r0:#3d4454; --r1:#5b7c99; --r2:#6a9d7f; --r3:#b8a44c; --r4:#d4703a;
    --s0:#34304a; --s1:#464067; --s2:#5d5488; --s3:#7a6cae; --s4:#9d8bd4;
    --live:#6a9d7f;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1,h2{font-family:'Space Grotesk',system-ui,sans-serif;margin:0}
  .wrap{max-width:1400px;margin:0 auto;padding:22px 20px 70px}

  header{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;
         padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:22px}
  h1{font-size:18px;font-weight:700}
  h1 .k{color:var(--accent)}
  .sub{color:var(--muted);font-size:11px}
  .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--live);
       margin-right:5px;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  @media (prefers-reduced-motion:reduce){.dot{animation:none}}
  .controls{margin-left:auto;display:flex;gap:12px;align-items:center}
  label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}
  select{background:var(--surface);color:var(--text);border:1px solid var(--line);
         border-radius:3px;padding:5px 8px;font-family:inherit;font-size:12px}

  section{margin-bottom:26px}
  h2{font-size:14px;font-weight:700;margin-bottom:3px}
  .q{color:var(--muted);font-size:11.5px;margin-bottom:11px}

  table{border-collapse:collapse;width:100%;font-size:11.5px}
  thead th{position:sticky;top:0;background:var(--raised);color:var(--muted);
           font-weight:500;font-size:10px;letter-spacing:.06em;text-transform:uppercase;
           text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);cursor:help}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:4px 8px;border-bottom:1px solid rgba(46,51,64,.45);white-space:nowrap}
  tbody tr:hover td{background:var(--surface)}

  .chip{display:inline-block;min-width:52px;text-align:right;padding:2px 7px;border-radius:3px;
        font-size:11px;font-weight:700;color:#0d0f14;font-variant-numeric:tabular-nums}
  .tapewrap{max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:3px}

  /* EMA spread */
  .emagrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:9px}
  .emacard{background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:9px 11px}
  .emacard .d{color:var(--muted);font-size:10px;letter-spacing:.06em;text-transform:uppercase}
  .emacard .v{font-size:17px;font-weight:700;margin:3px 0}
  .emacard .b{font-size:10px}
  .spark{display:block;width:100%;height:26px;margin-top:5px}

  /* Volatility map: one narrow cell per strike, so a whole chain fits on screen */
  .volrow{display:flex;align-items:center;gap:2px;margin-bottom:3px;overflow-x:auto;padding-bottom:2px}
  .volrow .lbl{min-width:52px;color:var(--muted);font-size:10px;flex:none}
  .cell{width:15px;height:17px;border-radius:2px;flex:none;cursor:help}
  .cell.atm{outline:2px solid var(--accent);outline-offset:-2px}
  .cell.itm{opacity:.42}
  .volhead{display:flex;gap:12px;font-size:10px;color:var(--muted);margin:7px 0 3px 52px}
  .legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:9px;font-size:10.5px;color:var(--muted)}
  .legend .k{display:inline-flex;align-items:center;gap:5px}
  .sw{width:11px;height:11px;border-radius:2px;display:inline-block}
  .empty{color:var(--muted);padding:11px 4px;font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1><span class="dot"></span><span class="k">live</span> board</h1>
      <div class="sub" id="sub">connecting…</div>
    </div>
    <div class="controls">
      <span><label for="sel">Expiry</label> <select id="sel"></select></span>
      <span><label for="dur">Duration</label> <select id="dur"></select></span>
    </div>
  </header>

  <section>
    <h2>Signal tape</h2>
    <div class="q" id="tapeQ"></div>
    <div class="tapewrap"><div id="tape"></div></div>
  </section>

  <section>
    <h2>Spot EMA convergence</h2>
    <div class="q">Spread between the 20/50/100/200 EMAs as a percentage of price.
      Tight means every lookback agrees — the market has gone nowhere on all horizons
      at once, which is the compression that precedes a move.</div>
    <div class="emagrid" id="ema"></div>
  </section>

  <section>
    <h2>Option volatility map</h2>
    <div class="q">Body movement over the last 5 and 10 candles, divided by price.
      Dark means quiet. A quiet EXPENSIVE option is premium being held; a quiet cheap
      one is just decayed — which is why price divides rather than multiplies.
      Orange outline is the strike nearest spot; faded cells are in the money.</div>
    <div id="vol"></div>
    <div class="legend" id="volLegend"></div>
  </section>
</div>

<script>
const VOLCOL=['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
const EMACOL=['var(--s0)','var(--s1)','var(--s2)','var(--s3)','var(--s4)'];
const SIGCOL={red_squeeze:'var(--s1)',otm_red_squeeze:'var(--s2)',green_stairs:'var(--s3)',otm_wall:'var(--s4)'};
const VOLBANDS=${JSON.stringify(cfg.VOLATILITY_BANDS.map(b => b.label))};
const EMABANDS=${JSON.stringify(cfg.EMA_SPREAD_BANDS.map(b => b.label))};
const REFRESH=${cfg.LIVE_REFRESH_MS};

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs=t=>String(t).slice(5,16).replace('T',' ');
let SNAP=null, CUR=null;

async function loadList(){
  const list=await (await fetch('/api/snapshots')).json();
  if(!list.length){ $('sub').textContent='No snapshots yet — start live_runner.js'; return false; }
  const prev=$('sel').value;
  $('sel').innerHTML=list.map(s=>'<option value="'+esc(s.spot+'|'+s.expiry)+'">'+esc(s.spot+'  '+s.expiry)+'</option>').join('');
  if(prev && list.some(s=>s.spot+'|'+s.expiry===prev)) $('sel').value=prev;
  return true;
}

async function loadSnap(){
  const v=$('sel').value; if(!v) return;
  const [spot,expiry]=v.split('|');
  const r=await fetch('/api/snapshot/'+encodeURIComponent(spot)+'/'+encodeURIComponent(expiry));
  SNAP=await r.json();
  if(!SNAP||SNAP.error){ $('sub').textContent='Snapshot unavailable'; return; }

  const age=Math.round((Date.now()-new Date(SNAP.updatedAt).getTime())/1000);
  $('sub').textContent=SNAP.spot+' '+SNAP.expiry+'  ·  '+SNAP.hoursToExpiry+'h to expiry  ·  spot '+
    (SNAP.spotPrice??'?')+'  ·  '+SNAP.instruments+' instruments  ·  updated '+age+'s ago';

  const durs=SNAP.durations||[];
  const prev=$('dur').value;
  $('dur').innerHTML=durs.map(d=>'<option value="'+d+'">'+d+'m</option>').join('');
  if(prev&&durs.includes(+prev)) $('dur').value=prev;
  CUR=+$('dur').value||durs[0];

  renderTape(); renderEma(); renderVol();
}

function renderTape(){
  const sigs=SNAP.signals||[];
  $('tapeQ').textContent=sigs.length
    ? sigs.length+' signals in the last '+${cfg.LIVE_SIGNAL_WINDOW_HOURS}+'h, newest first, across all durations.'
    : 'No signals in the last '+${cfg.LIVE_SIGNAL_WINDOW_HOURS}+'h.';
  if(!sigs.length){ $('tape').innerHTML='<div class="empty">Nothing yet.</div>'; return; }

  let h='<table><thead><tr>'+
    '<th title="When the signal fired">Time</th>'+
    '<th title="Which signal">Signal</th>'+
    '<th title="Candle duration">Dur</th>'+
    '<th title="Contract">Instrument</th>'+
    '<th class="num" title="Strike">Strike</th>'+
    '<th class="num" title="How far OTM, % of spot. Negative is ITM.">OTM%</th>'+
    '<th class="num" title="Entry price">Entry</th>'+
    '<th class="num" title="Signal strength — scale differs per signal">Strength</th>'+
    '<th title="activated / slHit / pending">State</th></tr></thead><tbody>';
  for(const s of sigs){
    h+='<tr>'+
      '<td>'+esc(shortTs(s.dtstring))+'</td>'+
      '<td><span class="chip" style="background:'+(SIGCOL[s.signal]||'var(--s0)')+'">'+esc(s.signal.replace('otm_',''))+'</span></td>'+
      '<td>'+s.duration+'m</td>'+
      '<td>'+esc(s.symbol)+'</td>'+
      '<td class="num">'+s.strike+'</td>'+
      '<td class="num">'+(s.distancePct==null?'—':s.distancePct.toFixed(1))+'</td>'+
      '<td class="num">'+s.close+'</td>'+
      '<td class="num">'+(s.signalValue==null?'—':Number(s.signalValue).toFixed(2))+'</td>'+
      '<td>'+esc(s.state)+'</td></tr>';
  }
  $('tape').innerHTML=h+'</tbody></table>';
}

function renderEma(){
  const byDur=SNAP.emaSpread||{};
  const durs=Object.keys(byDur).map(Number).sort((a,b)=>a-b);
  if(!durs.length){ $('ema').innerHTML='<div class="empty">No spot candles stored — run backfill.js --spot-candles.</div>'; return; }

  let h='';
  for(const d of durs){
    const ser=byDur[d]; const last=ser[ser.length-1];
    const vals=ser.map(p=>p.spreadPct);
    const lo=Math.min(...vals), hi=Math.max(...vals), rng=(hi-lo)||1;
    // Sparkline: 100x26 viewBox, stretched by CSS. Shows the trend in
    // convergence, which matters as much as the current level.
    const pts=ser.map((p,i)=>(i/(ser.length-1||1)*100).toFixed(2)+','+(24-((p.spreadPct-lo)/rng)*22).toFixed(2)).join(' ');
    h+='<div class="emacard">'+
       '<div class="d">'+d+'m</div>'+
       '<div class="v" style="color:'+EMACOL[last.band]+'">'+last.spreadPct.toFixed(4)+'%</div>'+
       '<div class="b" style="color:'+EMACOL[last.band]+'">'+esc(EMABANDS[last.band])+'</div>'+
       '<svg class="spark" viewBox="0 0 100 26" preserveAspectRatio="none">'+
       '<polyline fill="none" stroke="'+EMACOL[last.band]+'" stroke-width="1.2" points="'+pts+'"/></svg>'+
       '</div>';
  }
  $('ema').innerHTML=h;
}

function renderVol(){
  const rows=(SNAP.volatility||{})[CUR];
  if(!rows||!rows.length){ $('vol').innerHTML='<div class="empty">No volatility data at '+CUR+'m.</div>'; $('volLegend').innerHTML=''; return; }

  const spot=SNAP.spotPrice;
  // Compressed: one narrow cell per strike so a whole chain fits without
  // scrolling into a giant table. Calls and puts on separate rows, split again
  // by the 5- and 10-candle windows.
  let h='';
  for(const type of ['C','P']){
    const set=rows.filter(r=>r.type===type);
    if(!set.length) continue;
    // Nearest strike to spot gets the ATM marker.
    let atm=null,best=Infinity;
    for(const r of set){ const d=Math.abs(r.strike-(spot||r.strike)); if(d<best){best=d;atm=r.symbol;} }

    h+='<div class="volhead">'+(type==='C'?'CALLS':'PUTS')+' — strike ascending, faded = ITM</div>';
    for(const w of [5,10]){
      h+='<div class="volrow"><span class="lbl">'+w+'-candle</span>';
      for(const r of set){
        const b=r['band'+w];
        const col=b==null?'var(--surface)':VOLCOL[b];
        const cls='cell'+(r.symbol===atm?' atm':'')+(r.otm===false?' itm':'');
        const t=r.symbol+'  strike '+r.strike+'  close '+r.close+
                '  vol'+w+' '+(r['vol'+w]==null?'—':r['vol'+w])+
                (b==null?'':'  ('+VOLBANDS[b]+')')+(r.otm===false?'  [ITM]':'  [OTM]');
        h+='<span class="'+cls+'" style="background:'+col+'" title="'+esc(t)+'"></span>';
      }
      h+='</div>';
    }
  }
  $('vol').innerHTML=h;
  $('volLegend').innerHTML='<span class="k">quiet</span>'+
    VOLBANDS.map((l,i)=>'<span class="k"><span class="sw" style="background:'+VOLCOL[i]+'"></span>'+esc(l)+'</span>').join('')+
    '<span class="k" style="margin-left:10px"><span class="sw" style="outline:2px solid var(--accent);outline-offset:-2px"></span>nearest spot</span>';
}

(async function init(){
  if(!await loadList()){ setTimeout(()=>location.reload(),5000); return; }
  $('sel').addEventListener('change',loadSnap);
  $('dur').addEventListener('change',()=>{CUR=+$('dur').value;renderVol();});
  await loadSnap();
  // Poll rather than push: snapshots are rewritten a few times a minute at most,
  // so a websocket would add moving parts for no gain.
  setInterval(async()=>{ await loadList(); await loadSnap(); },REFRESH);
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

http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split('?')[0]);
    try {
        if (url === '/' || url === '/index.html') {
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
            return res.end(renderPage());
        }
        if (url === '/api/snapshots') return json(res, listSnapshots());

        const m = url.match(/^\/api\/snapshot\/([^/]+)\/([^/]+)$/);
        if (m) {
            const snap = readSnapshot(m[1], m[2]);
            return json(res, snap || { error: 'not found' });
        }
        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, () => {
    console.log('');
    console.log(`Live board  →  http://localhost:${PORT}`);
    console.log(`  snapshots : ${LIVE_DIR}`);
    console.log(`  refresh   : every ${cfg.LIVE_REFRESH_MS / 1000}s`);
    console.log('');
});
