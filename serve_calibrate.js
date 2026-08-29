// serve_calibrate.js
// ─────────────────────────────────────────────────────────────────────────────
// Calibration workbench. Run: node serve_calibrate.js   (port 3600)
//
// One signal at a time, calls and puts pooled, every expiry consolidated. Two
// columns: successes sorted by ratio descending, failures ascending — so the
// best trade and the worst are both at the top of their column, which is where
// calibration questions get answered.
//
// WHAT IS EDITABLE, AND WHY THAT LIMIT EXISTS
// Firing criteria are applied when signals are GENERATED, not when they are
// read. What survives on disk is the merged range, which carries maxSignalValue.
// So:
//
//   RAISING a threshold  — pure filter over stored rows. Instant.
//   LOWERING it          — impossible here. Signals below the generation
//                          threshold were never written, so there is nothing to
//                          re-admit. That needs:
//                              node backfill.js --signals-only --force-signals
//                          after editing config.js.
//
// The form enforces this rather than silently returning fewer rows than the user
// expects, which would read as "lowering the threshold found nothing".
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg       = require('./config');
const netinfo = require('./netinfo');
const writer    = require('./writer');
const expiryMod = require('./expiry');
const instr     = require('./instruments');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3600;

// Host-relative. Hardcoding localhost meant a chart link opened on a phone
// resolved to the PHONE, so every link 404'd off the LAN. The page substitutes
// its own hostname client-side.
const CHART_HOST_PLACEHOLDER = '__CHART_HOST__';
const CHART_BASE = `http://${CHART_HOST_PLACEHOLDER}:3000/de`;
const CHART_LEAD_CANDLES = 40;
const CHART_TAIL_MINUTES = 30;

// ─── Which generation threshold each signal used ──────────────────────────────
// Needed so the form can refuse a value below it with an explanation.
function genThresholdOf(signalId) {
    if (signalId === 'red_squeeze')  return { value: cfg.RED_SQUEEZE_THRESHOLD, name: 'RED_SQUEEZE_THRESHOLD' };
    if (signalId === 'otm_wall')     return { value: cfg.WALL_JUMP_THRESHOLD,   name: 'WALL_JUMP_THRESHOLD' };
    if (signalId.startsWith('otm_') || signalId === 'green_stairs')
                                     return { value: cfg.OTM_SIGNAL_THRESHOLD,  name: 'OTM_SIGNAL_THRESHOLD' };
    return { value: 0, name: '(unknown)' };
}

// ─── Listing ──────────────────────────────────────────────────────────────────

function listSignalIds() {
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

// ─── Load every range for a signal + spot ─────────────────────────────────────

const _cache = new Map();

function pad(n) { return String(n).padStart(2, '0'); }
function istOf(ms) {
    const d = new Date(ms + (5 * 60 + 30) * 60000);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
           `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00+0530`;
}

/**
 * Every merged range across all durations and all SETTLED expiries, flattened.
 *
 * Calls and puts are pooled deliberately: a calibration question is about the
 * signal, not about one side of it, and splitting would mean tuning twice.
 * Cached because a full history runs to tens of thousands of rows.
 */
function loadAll(signalId, spot) {
    const key = `${signalId}|${spot}`;
    if (_cache.has(key)) return _cache.get(key);

    const spotDir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot);
    const rows = [];
    if (!fs.existsSync(spotDir)) { _cache.set(key, rows); return rows; }

    const durations = fs.readdirSync(spotDir)
        .filter(d => !d.startsWith('.') && !d.startsWith('_') && !isNaN(d))
        .map(Number).sort((a, b) => a - b);

    for (const duration of durations) {
        const dir = path.join(spotDir, String(duration));
        for (const f of fs.readdirSync(dir)) {
            if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
            const expiry = f.replace(/\.json$/, '');
            if (!expiryMod.isExpired(spot, expiry)) continue;   // no outcome yet

            const data = writer.readSignals(signalId, spot, duration, expiry);
            for (const type of ['C', 'P']) {
                for (const r of (data[type] || [])) {
                    const [startTs, endTs, count, sv, fired, state, instruments, univ, univSym] = r;
                    const best = univSym || (instruments || [])[0] || null;
                    rows.push({
                        expiry, duration, type,
                        startTs, endTs,
                        count:       count || 0,
                        signalValue: Number(sv) || 0,
                        fired:       Number(fired) || 0,
                        univ:        Number(univ) || 0,
                        state,
                        symbol: best,
                        url: best
                            ? `${CHART_BASE}/${expiry}/${best}/` +
                              `${istOf(new Date(startTs).getTime() - CHART_LEAD_CANDLES * duration * 60000)}/` +
                              `${istOf(expiryMod.expiryMillis(spot, expiry) + CHART_TAIL_MINUTES * 60000)}/${duration}`
                            : null,
                    });
                }
            }
        }
    }

    _cache.set(key, rows);
    return rows;
}

// ─── Evaluate one criteria set ────────────────────────────────────────────────

/**
 * Split rows into successes and failures under the supplied criteria.
 *
 * Every criterion here is a filter over stored fields, so evaluation is instant
 * no matter how many times it is adjusted — which is the point of a calibration
 * loop. Anything that would need signals to be regenerated is refused upstream.
 */
function evaluate(rows, c) {
    const ratioOf = r => (c.source === 'fired' ? r.fired : r.univ);

    const kept = rows.filter(r =>
        r.signalValue >= c.minSignalValue &&
        r.signalValue <= c.maxSignalValue &&
        r.count       >= c.minCount &&
        (c.duration === 0 || r.duration === c.duration) &&
        (c.type === 'both' || r.type === c.type)
    );

    const success = [], failure = [];
    for (const r of kept) {
        (ratioOf(r) >= c.successRatio ? success : failure).push(r);
    }

    // Best success first; worst failure first. Both columns therefore open on
    // their most informative row rather than their most typical one.
    success.sort((a, b) => ratioOf(b) - ratioOf(a));
    failure.sort((a, b) => ratioOf(a) - ratioOf(b));

    const total = kept.length;
    return {
        totalStored: rows.length,
        total,
        successCount: success.length,
        failureCount: failure.length,
        successPct: total ? (success.length / total * 100) : 0,
        success: success.slice(0, c.limit).map(r => ({ ...r, ratio: ratioOf(r) })),
        failure: failure.slice(0, c.limit).map(r => ({ ...r, ratio: ratioOf(r) })),
    };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Calibrate</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{--ground:#14161c;--surface:#1c1f28;--raised:#242833;--line:#2e3340;
        --text:#c8ccd8;--muted:#6b7183;--accent:#d4703a;
        --ok:#6a9d7f;--bad:#8a5a5a;
        --r0:#3d4454;--r1:#5b7c99;--r2:#6a9d7f;--r3:#b8a44c;--r4:#d4703a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1,h2{font-family:'Space Grotesk',system-ui,sans-serif;margin:0}
  .wrap{max-width:1600px;margin:0 auto;padding:22px 20px 70px}
  header{padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:16px}
  h1{font-size:18px;font-weight:700} h1 .k{color:var(--accent)}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;max-width:900px}

  form{background:var(--surface);border:1px solid var(--line);border-radius:3px;
       padding:14px;margin-bottom:8px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(178px,1fr));gap:12px}
  .f{display:flex;flex-direction:column;gap:3px}
  label{color:var(--muted);font-size:10px;letter-spacing:.07em;text-transform:uppercase}
  input,select{background:var(--ground);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:6px 8px;font-family:inherit;font-size:12px;width:100%}
  input:focus,select:focus{outline:2px solid var(--accent);outline-offset:1px}
  .note{color:var(--muted);font-size:10px}
  .warn{color:var(--accent);font-size:10px}
  .actions{display:flex;gap:10px;align-items:center;margin-top:13px}
  button{background:var(--accent);color:#14161c;border:0;border-radius:3px;
         padding:7px 18px;font-family:'Space Grotesk',sans-serif;font-weight:700;
         font-size:12.5px;cursor:pointer}
  button:hover{filter:brightness(1.1)}
  button.sec{background:var(--raised);color:var(--text)}

  .banner{border-left:2px solid var(--accent);background:var(--surface);
          padding:9px 12px;margin-bottom:16px;font-size:11.5px;display:none}
  .banner.on{display:block}

  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
         gap:8px;margin-bottom:18px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:9px 11px}
  .card .l{color:var(--muted);font-size:9.5px;letter-spacing:.07em;text-transform:uppercase}
  .card .v{font-size:19px;font-weight:700;font-family:'Space Grotesk',sans-serif;margin-top:2px}

  .cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:1200px){.cols{grid-template-columns:1fr}}
  .col h2{font-size:14px;font-weight:700;margin-bottom:2px}
  .col h2.ok{color:var(--ok)} .col h2.bad{color:var(--bad)}
  .col .n{color:var(--muted);font-size:11px;margin-bottom:9px}
  .tw{max-height:620px;overflow:auto;border:1px solid var(--line);border-radius:3px}
  table{border-collapse:collapse;width:100%;font-size:11.5px}
  thead th{position:sticky;top:0;z-index:2;background:var(--raised);color:var(--muted);
    font-weight:500;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;
    text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:help}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:4px 8px;border-bottom:1px solid rgba(46,51,64,.4);white-space:nowrap}
  tbody tr:hover td{background:#1f2330}
  td.ts{color:var(--muted);font-size:10.5px}
  .chip{display:inline-block;min-width:56px;text-align:right;padding:2px 6px;border-radius:3px;
        font-size:10.5px;font-weight:700;color:#0d0f14;font-variant-numeric:tabular-nums}
  a{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--line)}
  a:hover{color:var(--accent);border-bottom-color:var(--accent)}
  .empty{color:var(--muted);padding:14px;font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="k">calibrate</span> — successes and failures</h1>
    <div class="sub">All expiries consolidated, calls and puts pooled. Successes sorted by ratio
      descending, failures ascending, so each column opens on its most informative row. Edit the
      criteria and submit to recompute — every criterion is a filter over stored data, so it is
      instant.</div>
  </header>

  <form id="form" onsubmit="return false">
    <div class="grid">
      <div class="f"><label for="signal">Signal</label><select id="signal"></select></div>
      <div class="f"><label for="spot">Spot</label><select id="spot"></select></div>
      <div class="f"><label for="source">Payoff measured on</label>
        <select id="source">
          <option value="universe">Best same-type strike</option>
          <option value="fired">Fired instrument only</option>
        </select></div>
      <div class="f"><label for="successRatio">Success = ratio ≥</label>
        <input type="number" id="successRatio" value="10" min="0" step="1">
        <span class="note">the success/failure split</span></div>

      <div class="f"><label for="minSignalValue">Min signal value</label>
        <input type="number" id="minSignalValue" step="any">
        <span class="note" id="minNote"></span></div>
      <div class="f"><label for="maxSignalValue">Max signal value</label>
        <input type="number" id="maxSignalValue" step="any">
        <span class="note">upper bound; blank-ish = no cap</span></div>

      <div class="f"><label for="minCount">Min instruments</label>
        <input type="number" id="minCount" value="1" min="1" step="1">
        <span class="note">confluence across strikes</span></div>
      <div class="f"><label for="duration">Duration</label><select id="duration"></select></div>
      <div class="f"><label for="type">Type</label>
        <select id="type"><option value="both">Calls + puts</option>
          <option value="C">Calls only</option><option value="P">Puts only</option></select></div>
      <div class="f"><label for="limit">Rows per column</label>
        <input type="number" id="limit" value="300" min="10" step="10"></div>
    </div>
    <div class="actions">
      <button id="submit">Compute</button>
      <button id="reset" class="sec">Reset to defaults</button>
      <span class="note" id="status"></span>
    </div>
  </form>

  <div class="banner" id="banner"></div>
  <div class="cards" id="cards"></div>

  <div class="cols">
    <div class="col"><h2 class="ok">Successes</h2><div class="n" id="nS"></div>
      <div class="tw"><div id="tS"></div></div></div>
    <div class="col"><h2 class="bad">Failures</h2><div class="n" id="nF"></div>
      <div class="tw"><div id="tF"></div></div></div>
  </div>
</div>

<script>
// Chart links are built server-side with a placeholder host; swap in whatever
// host actually served this page so links work from any device on the LAN.
document.addEventListener('DOMContentLoaded',()=>{},{once:true});
const CHART_HOST=location.hostname;
function fixChartUrl(u){ return String(u||'').replace('__CHART_HOST__',CHART_HOST); }
const RCOL=['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
const BANDS=${JSON.stringify(cfg.RATIO_BANDS.map(b => ({ min: b.min, max: b.max === Infinity ? null : b.max })))};
let META=null;

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs=t=>String(t).slice(0,16).replace('T',' ');
function band(v){if(!(v>0))return 0;for(let i=0;i<BANDS.length;i++){const b=BANDS[i];if(v>=b.min&&(b.max===null||v<b.max))return i;}return BANDS.length-1;}

function criteria(){
  return {
    signal: $('signal').value, spot: $('spot').value, source: $('source').value,
    successRatio:   parseFloat($('successRatio').value)||0,
    minSignalValue: parseFloat($('minSignalValue').value)||0,
    maxSignalValue: parseFloat($('maxSignalValue').value)||Number.MAX_VALUE,
    minCount:       parseInt($('minCount').value)||1,
    duration:       parseInt($('duration').value)||0,
    type:           $('type').value,
    limit:          parseInt($('limit').value)||300,
  };
}

function renderTable(el, rows, source){
  if(!rows.length){ $(el).innerHTML='<div class="empty">None.</div>'; return; }
  let h='<table><thead><tr>'+
    '<th class="num" title="Payoff under the selected definition">Ratio</th>'+
    '<th class="num" title="Signal strength at entry — the value being calibrated">Value</th>'+
    '<th title="Instrument that achieved the ratio; links to its chart">Instrument</th>'+
    '<th class="num" title="Candle duration">Dur</th>'+
    '<th title="Expiry">Expiry</th>'+
    '<th>T</th>'+
    '<th class="num" title="Instruments merged into this range">In</th>'+
    '<th title="Entry timestamp">Entry</th></tr></thead><tbody>';
  for(const r of rows){
    h+='<tr>'+
      '<td class="num"><span class="chip" style="background:'+RCOL[band(r.ratio)]+'">'+r.ratio.toFixed(2)+'x</span></td>'+
      '<td class="num">'+r.signalValue.toFixed(1)+'</td>'+
      '<td>'+(r.url?'<a href="'+esc(fixChartUrl(r.url))+'" target="_blank" rel="noopener">'+esc(r.symbol)+' ↗</a>':esc(r.symbol||'—'))+'</td>'+
      '<td class="num">'+r.duration+'m</td>'+
      '<td class="ts">'+esc(r.expiry)+'</td>'+
      '<td>'+esc(r.type)+'</td>'+
      '<td class="num">'+r.count+'</td>'+
      '<td class="ts">'+esc(shortTs(r.endTs))+'</td></tr>';
  }
  $(el).innerHTML=h+'</tbody></table>';
}

async function compute(){
  const c=criteria();
  const g=META.genThreshold;

  // Refuse rather than silently return fewer rows: a value below the generation
  // threshold cannot admit signals that were never written to disk.
  if(c.minSignalValue < g.value){
    $('banner').className='banner on';
    $('banner').innerHTML='<b>Min signal value '+c.minSignalValue+' is below the generation threshold '+
      g.value+'.</b><br>Signals weaker than that were never stored, so nothing new can appear. '+
      'Raising the value filters instantly; to LOWER it, set <code>'+esc(g.name)+
      '</code> in config.js and run:<br><code>node backfill.js --signals-only --force-signals</code>';
    return;
  }
  $('banner').className='banner';

  $('status').textContent='computing…';
  const res=await (await fetch('/api/evaluate',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(c)})).json();
  $('status').textContent='';

  $('cards').innerHTML=[
    ['stored',        res.totalStored.toLocaleString()],
    ['after filters', res.total.toLocaleString()],
    ['successes',     res.successCount.toLocaleString()],
    ['failures',      res.failureCount.toLocaleString()],
    ['success rate',  res.successPct.toFixed(1)+'%'],
  ].map(([l,v])=>'<div class="card"><div class="l">'+esc(l)+'</div><div class="v">'+esc(v)+'</div></div>').join('');

  $('nS').textContent='ratio ≥ '+c.successRatio+'x, highest first'+
    (res.successCount>res.success.length?'  ·  showing '+res.success.length+' of '+res.successCount:'');
  $('nF').textContent='ratio < '+c.successRatio+'x, lowest first'+
    (res.failureCount>res.failure.length?'  ·  showing '+res.failure.length+' of '+res.failureCount:'');

  renderTable('tS',res.success,c.source);
  renderTable('tF',res.failure,c.source);
}

async function loadSignal(){
  META=await (await fetch('/api/meta/'+encodeURIComponent($('signal').value))).json();
  $('spot').innerHTML=(META.spots||[]).map(s=>'<option>'+esc(s)+'</option>').join('');
  $('duration').innerHTML='<option value="0">All</option>'+
    (META.durations||[]).map(d=>'<option value="'+d+'">'+d+'m</option>').join('');
  applyDefaults();
  if(META.spots&&META.spots.length) await compute();
}

function applyDefaults(){
  const g=META.genThreshold;
  $('minSignalValue').value=g.value;
  $('minSignalValue').min=g.value;
  $('maxSignalValue').value=Math.round(g.value*1e6);
  $('minNote').innerHTML='generated at <b>'+g.value+'</b> ('+esc(g.name)+') — cannot go lower';
  $('successRatio').value=${cfg.DEFAULT_HEADLINE_THRESHOLD};
  $('minCount').value=1;
  $('type').value='both';
  $('duration').value='0';
}

(async function init(){
  const sigs=await (await fetch('/api/signals')).json();
  if(!sigs.length){ $('tS').innerHTML='<div class="empty">No signal data. Run backfill.js --signals-only.</div>'; return; }
  $('signal').innerHTML=sigs.map(s=>'<option>'+esc(s)+'</option>').join('');
  $('signal').addEventListener('change',loadSignal);
  $('spot').addEventListener('change',compute);
  $('submit').addEventListener('click',compute);
  $('reset').addEventListener('click',()=>{applyDefaults();compute();});
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

        const m = url.match(/^\/api\/meta\/([^/]+)$/);
        if (m) {
            const spots = listSpots(m[1]);
            let durations = [];
            if (spots.length) {
                const d = path.join(cfg.SIGNALS_BASE_DIR, m[1], spots[0]);
                durations = fs.readdirSync(d)
                    .filter(x => !x.startsWith('.') && !x.startsWith('_') && !isNaN(x))
                    .map(Number).sort((a, b) => a - b);
            }
            return json(res, { signalId: m[1], spots, durations, genThreshold: genThresholdOf(m[1]) });
        }

        if (url === '/api/evaluate' && req.method === 'POST') {
            let body = '';
            req.on('data', c => { body += c; });
            req.on('end', () => {
                try {
                    const c = JSON.parse(body);
                    return json(res, evaluate(loadAll(c.signal, c.spot), c));
                } catch (err) {
                    console.error('evaluate failed:', err);
                    res.writeHead(500); res.end('bad request');
                }
            });
            return;
        }

        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, '0.0.0.0', () => {
    console.log(netinfo.banner('Calibrate', PORT));
});
