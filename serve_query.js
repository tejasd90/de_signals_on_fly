// serve_query.js
// ─────────────────────────────────────────────────────────────────────────────
// STAGE 3: query the patterns stage 1 extracted. Run: node serve_query.js (3700)
//
// Two expressions:
//   FILTER  — which signals to take. Outcome fields are refused here: choosing
//             signals by what happened after entry is lookahead and produces
//             results that cannot be traded.
//   SUCCESS — what counts as a win. Outcome fields allowed and expected.
//
// HOLDOUT IS NOT OPTIONAL
// Expiries are split by date: the earlier share is TRAIN, the rest TEST, and
// both numbers are always shown. With a million rows and free-form querying,
// finding a clause that looks excellent in-sample is close to certain; the only
// defence is seeing the out-of-sample number beside it every time. A large gap
// between them means a curve fit, not an edge.
//
// Two query slots (A and B) run side by side, because the real question is
// almost always "is this clause better than that one" rather than "how good is
// this clause".
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');
const cfg   = require('./config');
const ql    = require('./query_lang');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3700;
const DIR  = path.join(cfg.DATA_BASE_DIR, 'patterns');

const CHART_BASE = 'http://localhost:3000/de';
const CHART_LEAD_CANDLES = 40;

// Fraction of expiries, oldest first, used for tuning. The rest is held out.
const TRAIN_FRACTION = 0.7;

// Below this a percentage is noise; the UI greys it and never marks it best.
const MIN_SAMPLE = 30;

// ─── Loading ──────────────────────────────────────────────────────────────────

function listSignals() {
    if (!fs.existsSync(DIR)) return [];
    return fs.readdirSync(DIR)
        .filter(d => !d.startsWith('.') && !d.startsWith('_') &&
                     fs.statSync(path.join(DIR, d)).isDirectory())
        .sort();
}

function listSpots(signalId) {
    const d = path.join(DIR, signalId);
    if (!fs.existsSync(d)) return [];
    return fs.readdirSync(d)
        .filter(x => !x.startsWith('.') && fs.statSync(path.join(d, x)).isDirectory())
        .sort();
}

const _cache = new Map();

/**
 * Every row for a signal + spot, tagged train or test.
 *
 * The split is by EXPIRY DATE, not by row: rows from one expiry share the same
 * underlying move, so splitting at row level would leak the answer across the
 * boundary and make the held-out number meaningless.
 */
function loadRows(signalId, spot) {
    const key = `${signalId}|${spot}`;
    if (_cache.has(key)) return _cache.get(key);

    const spotDir = path.join(DIR, signalId, spot);
    const out = { rows: [], expiries: [], splitAt: null };
    if (!fs.existsSync(spotDir)) { _cache.set(key, out); return out; }

    const durations = fs.readdirSync(spotDir)
        .filter(d => !d.startsWith('.') && !isNaN(d)).map(Number).sort((a, b) => a - b);

    const expiries = new Set();
    const raw = [];

    for (const dur of durations) {
        const dir = path.join(spotDir, String(dur));
        for (const f of fs.readdirSync(dir)) {
            if (!f.endsWith('.json') || f.includes('.tmp.')) continue;
            try {
                for (const r of JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'))) {
                    raw.push(r); expiries.add(r.expiry);
                }
            } catch (_) {}
        }
    }

    const sorted = [...expiries].sort();
    const cut = sorted[Math.max(0, Math.floor(sorted.length * TRAIN_FRACTION) - 1)] || null;
    for (const r of raw) r._test = cut ? (r.expiry > cut) : false;

    out.rows = raw; out.expiries = sorted; out.splitAt = cut;
    _cache.set(key, out);
    return out;
}

function chartUrl(r) {
    const pad = n => String(n).padStart(2, '0');
    const ist = ms => {
        const d = new Date(ms + (5 * 60 + 30) * 60000);
        return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
               `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00+0530`;
    };
    const from = ist(new Date(r.patternStart).getTime() - CHART_LEAD_CANDLES * r.duration * 60000);
    return `${CHART_BASE}/${r.expiry}/${r.symbol}/${from}/${r.expiry}T18:00:00+0530/${r.duration}`;
}

// ─── Evaluation ───────────────────────────────────────────────────────────────

function runQuery(rows, filterSrc, successSrc, limit, derivedSrc) {
    // Derived fields are registered globally on FIELDS, so each run clears the
    // previous set — otherwise a definition removed from the box would linger
    // and keep resolving.
    ql.clearDerived();
    const derived = derivedSrc && derivedSrc.trim() ? ql.parseDerived(derivedSrc) : [];
    // allowOutcome false on the filter is the lookahead guard.
    const filterFn  = filterSrc.trim()
        ? ql.compile(filterSrc,  { allowOutcome: false })
        : () => true;
    const successFn = ql.compile(successSrc, { allowOutcome: true });

    const bucket = () => ({ n: 0, wins: 0, success: [], failure: [] });
    const train = bucket(), test = bucket(), all = bucket();

    for (const r of rows) {
        if (derived.length) ql.applyDerived(derived, r);
        if (!filterFn(r)) continue;
        const win = successFn(r);
        for (const b of [all, r._test ? test : train]) {
            b.n++; if (win) b.wins++;
        }
        (win ? all.success : all.failure).push(r);
    }

    // Best first among successes, worst first among failures: each column opens
    // on its most informative row rather than its most typical one.
    all.success.sort((a, b) => (b.univRatio || 0) - (a.univRatio || 0));
    all.failure.sort((a, b) => (a.univRatio || 0) - (b.univRatio || 0));

    const pct = b => b.n ? (b.wins / b.n) * 100 : 0;
    const slim = r => ({
        expiry: r.expiry, duration: r.duration, symbol: r.symbol, type: r.type,
        entryTs: r.entryTs, entryPrice: r.entryPrice, signalValue: r.signalValue,
        tteHours: r.tteHours, distancePct: r.distancePct,
        ratio: r.ratio, univRatio: r.univRatio, state: r.state,
        test: !!r._test, url: chartUrl(r),
    });

    return {
        total: all.n,
        all:   { n: all.n,   wins: all.wins,   pct: pct(all) },
        train: { n: train.n, wins: train.wins, pct: pct(train), thin: train.n < MIN_SAMPLE },
        test:  { n: test.n,  wins: test.wins,  pct: pct(test),  thin: test.n  < MIN_SAMPLE },
        gap:   pct(train) - pct(test),
        success: all.success.slice(0, limit).map(slim),
        failure: all.failure.slice(0, limit).map(slim),
        successCount: all.success.length,
        failureCount: all.failure.length,
    };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    const funcRows = Object.entries(ql.FUNCS)
        .map(([n, d]) => ({ name: n, arity: d.arity, desc: d.desc }));
    const fieldRows = Object.entries(ql.FIELDS)
        .map(([n, d]) => ({ name: n, type: d.type, outcome: d.outcome, desc: d.desc }));

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Query</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
  :root{--ground:#14161c;--surface:#1c1f28;--raised:#242833;--line:#2e3340;
        --text:#c8ccd8;--muted:#6b7183;--accent:#d4703a;--ok:#6a9d7f;--bad:#8a5a5a;
        --r0:#3d4454;--r1:#5b7c99;--r2:#6a9d7f;--r3:#b8a44c;--r4:#d4703a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--text);
       font-family:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;font-size:13px;line-height:1.5}
  h1,h2,h3{font-family:'Space Grotesk',system-ui,sans-serif;margin:0}
  .wrap{max-width:1680px;margin:0 auto;padding:22px 20px 70px}
  header{padding-bottom:13px;border-bottom:1px solid var(--line);margin-bottom:15px}
  h1{font-size:18px;font-weight:700} h1 .k{color:var(--accent)}
  .sub{color:var(--muted);font-size:11.5px;margin-top:3px;max-width:900px}

  .bar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin-bottom:12px}
  label{color:var(--muted);font-size:10px;letter-spacing:.07em;text-transform:uppercase;display:block}
  select,input,textarea{background:var(--surface);color:var(--text);border:1px solid var(--line);
    border-radius:3px;padding:6px 8px;font-family:inherit;font-size:12px}
  textarea{width:100%;resize:vertical;min-height:44px;line-height:1.45}
  textarea:focus,select:focus,input:focus{outline:2px solid var(--accent);outline-offset:1px}
  button{background:var(--accent);color:#14161c;border:0;border-radius:3px;padding:7px 18px;
         font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:12.5px;cursor:pointer}
  button.sec{background:var(--raised);color:var(--text)}
  button:hover{filter:brightness(1.1)}

  .slots{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
  @media(max-width:1100px){.slots{grid-template-columns:1fr}}
  .slot{background:var(--surface);border:1px solid var(--line);border-radius:3px;padding:12px}
  .slot h3{font-size:12px;margin-bottom:8px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
  .slot .f{margin-bottom:9px}
  .err{color:var(--bad);font-size:11px;margin-top:4px;display:none}
  .err.on{display:block}

  .res{display:grid;grid-template-columns:repeat(auto-fit,minmax(108px,1fr));gap:7px;margin-top:9px}
  .m{background:var(--ground);border:1px solid var(--line);border-radius:3px;padding:7px 9px}
  .m .l{color:var(--muted);font-size:9px;letter-spacing:.06em;text-transform:uppercase}
  .m .v{font-size:17px;font-weight:700;font-family:'Space Grotesk',sans-serif}
  .m .s{color:var(--muted);font-size:9.5px}
  .m.thin .v{color:var(--muted)}
  .m.test .v{color:var(--ok)}
  .m.gap .v{color:var(--accent)}
  .warn{border-left:2px solid var(--accent);background:var(--raised);padding:7px 10px;
        font-size:11px;margin-top:9px;display:none}
  .warn.on{display:block}

  details.fields{margin:14px 0}
  details.fields summary{cursor:pointer;color:var(--muted);font-size:11px;
    border-bottom:1px dotted var(--line);display:inline-block;padding:3px 0}
  details.fields summary:hover{color:var(--accent)}
  .ftab{margin-top:10px;max-height:280px;overflow:auto;border:1px solid var(--line);border-radius:3px}

  .cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
  @media(max-width:1200px){.cols{grid-template-columns:1fr}}
  .col h2{font-size:14px;font-weight:700}
  .col h2.ok{color:var(--ok)} .col h2.bad{color:var(--bad)}
  .col .n{color:var(--muted);font-size:11px;margin-bottom:8px}
  .tw{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:3px}
  table{border-collapse:collapse;width:100%;font-size:11.5px}
  thead th{position:sticky;top:0;z-index:2;background:var(--raised);color:var(--muted);
    font-weight:500;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;
    text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:4px 8px;border-bottom:1px solid rgba(46,51,64,.4);white-space:nowrap}
  tbody tr:hover td{background:#1f2330}
  td.ts{color:var(--muted);font-size:10.5px}
  .chip{display:inline-block;min-width:54px;text-align:right;padding:2px 6px;border-radius:3px;
        font-size:10.5px;font-weight:700;color:#0d0f14;font-variant-numeric:tabular-nums}
  .tag{font-size:9px;padding:0 4px;border-radius:2px;border:1px solid var(--line);color:var(--muted)}
  .tag.t{color:var(--ok);border-color:var(--ok)}
  a{color:var(--muted);text-decoration:none;border-bottom:1px dotted var(--line)}
  a:hover{color:var(--accent);border-bottom-color:var(--accent)}
  .empty{color:var(--muted);padding:14px;font-size:12px}
  code{color:var(--accent);font-size:11px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="k">query</span> — filter, success, holdout</h1>
    <div class="sub">Filter chooses which signals to take and refuses outcome fields, because
      selecting on what happened after entry is lookahead. Success defines a win. Train and test
      are split by expiry date and both are always shown — a large gap between them is a curve
      fit, not an edge.</div>
  </header>

  <div class="bar">
    <span><label for="signal">Signal</label><select id="signal"></select></span>
    <span><label for="spot">Spot</label><select id="spot"></select></span>
    <span><label for="limit">Rows shown</label><input type="number" id="limit" value="200" min="10" step="10" style="width:90px"></span>
    <button id="run">Run both</button>
    <span class="sub" id="status"></span>
  </div>

  <div class="slot" style="margin-bottom:14px">
    <h3>Computed fields — shared by both queries</h3>
    <textarea id="derived" placeholder="punch = ratio1 * ratio2 / avgPrice&#10;logCheap = log10(cheapness)"></textarea>
    <div class="sub" style="margin-top:5px">One per line, <code>name = expression</code>. Each becomes
      queryable like any other field, and may reference fields defined above it. A definition touching
      an outcome field is itself treated as an outcome and refused in filters.</div>
    <div class="err" id="derr"></div>
  </div>

  <div class="slots">
    <div class="slot" data-slot="A">
      <h3>Query A</h3>
      <div class="f"><label>Filter — entry-time fields only</label>
        <textarea data-f="filter">signalValue &gt; 50</textarea></div>
      <div class="f"><label>Success</label>
        <textarea data-f="success">univRatio &gt;= 10</textarea></div>
      <div class="err" data-e></div>
      <div class="res" data-res></div>
      <div class="warn" data-warn></div>
    </div>
    <div class="slot" data-slot="B">
      <h3>Query B</h3>
      <div class="f"><label>Filter — entry-time fields only</label>
        <textarea data-f="filter">signalValue &gt; 500 &amp;&amp; tteHours &lt; 48</textarea></div>
      <div class="f"><label>Success</label>
        <textarea data-f="success">univRatio &gt;= 10</textarea></div>
      <div class="err" data-e></div>
      <div class="res" data-res></div>
      <div class="warn" data-warn></div>
    </div>
  </div>

  <details class="fields">
    <summary>Available fields and syntax</summary>
    <div class="sub" style="margin-top:9px">
      Operators: <code>&gt; &lt; &gt;= &lt;= == !=</code> ·
      <code>&amp;&amp; ||</code> or <code>and or</code> ·
      <code>!</code> or <code>not</code> ·
      <code>+ - * /</code> ·
      <code>in [a, b]</code> ·
      <code>between a and b</code> · parentheses.<br>
      Outcome fields are marked and rejected in the filter box.<br>
      Functions: <span id="funclist"></span>
    </div>
    <div class="ftab" id="ftab"></div>
  </details>

  <div class="cols">
    <div class="col"><h2 class="ok">Successes</h2><div class="n" id="nS"></div>
      <div class="tw"><div id="tS"></div></div></div>
    <div class="col"><h2 class="bad">Failures</h2><div class="n" id="nF"></div>
      <div class="tw"><div id="tF"></div></div></div>
  </div>
</div>

<script>
const FIELDS=${JSON.stringify(fieldRows)};
const FUNCS=${JSON.stringify(funcRows)};
const RCOL=['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
const BANDS=${JSON.stringify(cfg.RATIO_BANDS.map(b => ({ min: b.min, max: b.max === Infinity ? null : b.max })))};
const MIN_SAMPLE=${MIN_SAMPLE};

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function band(v){if(!(v>0))return 0;for(let i=0;i<BANDS.length;i++){const b=BANDS[i];if(v>=b.min&&(b.max===null||v<b.max))return i;}return BANDS.length-1;}

function slotEls(name){
  const el=document.querySelector('.slot[data-slot="'+name+'"]');
  return {el,
    filter:el.querySelector('[data-f=filter]'), success:el.querySelector('[data-f=success]'),
    err:el.querySelector('[data-e]'), res:el.querySelector('[data-res]'), warn:el.querySelector('[data-warn]')};
}

function renderMetrics(s,r){
  const cell=(cls,l,v,sub)=>'<div class="m '+cls+'"><div class="l">'+esc(l)+'</div><div class="v">'+
    esc(v)+'</div><div class="s">'+esc(sub||'')+'</div></div>';
  s.res.innerHTML=
    cell('','matched',r.total.toLocaleString(),'')+
    cell('','all',r.all.pct.toFixed(1)+'%',r.all.wins+' / '+r.all.n)+
    cell(r.train.thin?'thin':'','train',r.train.pct.toFixed(1)+'%',r.train.wins+' / '+r.train.n)+
    cell('test '+(r.test.thin?'thin':''),'test (holdout)',r.test.pct.toFixed(1)+'%',r.test.wins+' / '+r.test.n)+
    cell('gap','train − test',r.gap.toFixed(1)+' pts','');

  // The two failure modes worth interrupting for: too little data to believe,
  // or a train/test gap that says the clause was fitted to history.
  let w='';
  if(r.test.thin||r.train.thin)
    w+='<b>Thin sample.</b> Fewer than '+MIN_SAMPLE+' rows on one side — this percentage is noise. Loosen the filter.<br>';
  if(!r.test.thin&&!r.train.thin&&r.gap>10)
    w+='<b>Train beats test by '+r.gap.toFixed(1)+' points.</b> That gap is the signature of a curve fit. Trust the test number.';
  s.warn.className='warn'+(w?' on':'');
  s.warn.innerHTML=w;
}

async function runSlot(name){
  const s=slotEls(name);
  s.err.className='err';
  const body={signal:$('signal').value,spot:$('spot').value,
    filter:s.filter.value,success:s.success.value,derived:$('derived').value,
    limit:parseInt($('limit').value)||200};
  const res=await (await fetch('/api/query',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  if(res.error){
    // A bad computed-field definition breaks both slots, so it is reported once
    // above rather than duplicated into each.
    const isDerived=/Definition needs|already exists|not a valid field name|has no expression|is a function name/.test(res.error);
    const target=isDerived?$('derr'):s.err;
    target.className='err on'; target.textContent=res.error;
    s.res.innerHTML=''; s.warn.className='warn'; return null;
  }
  $('derr').className='err';
  renderMetrics(s,res);
  return res;
}

function renderTable(el,rows){
  if(!rows.length){ $(el).innerHTML='<div class="empty">None.</div>'; return; }
  let h='<table><thead><tr>'+
    '<th class="num">Ratio</th><th class="num">Value</th><th>Instrument</th>'+
    '<th class="num">Dur</th><th class="num">TTE h</th><th class="num">OTM%</th>'+
    '<th>Expiry</th><th>Set</th></tr></thead><tbody>';
  for(const r of rows){
    h+='<tr>'+
      '<td class="num"><span class="chip" style="background:'+RCOL[band(r.univRatio)]+'">'+(r.univRatio||0).toFixed(2)+'x</span></td>'+
      '<td class="num">'+(r.signalValue==null?'—':Number(r.signalValue).toFixed(1))+'</td>'+
      '<td><a href="'+esc(r.url)+'" target="_blank" rel="noopener">'+esc(r.symbol)+' ↗</a></td>'+
      '<td class="num">'+r.duration+'m</td>'+
      '<td class="num">'+(r.tteHours==null?'—':r.tteHours.toFixed(0))+'</td>'+
      '<td class="num">'+(r.distancePct==null?'—':r.distancePct.toFixed(1))+'</td>'+
      '<td class="ts">'+esc(r.expiry)+'</td>'+
      '<td><span class="tag'+(r.test?' t':'')+'">'+(r.test?'test':'train')+'</span></td></tr>';
  }
  $(el).innerHTML=h+'</tbody></table>';
}

async function runAll(){
  $('status').textContent='running…';
  const a=await runSlot('A');
  const b=await runSlot('B');
  $('status').textContent='';
  const show=a||b;
  if(!show){ $('tS').innerHTML=''; $('tF').innerHTML=''; return; }
  $('nS').textContent='Query A · '+show.successCount.toLocaleString()+' successes, best first';
  $('nF').textContent='Query A · '+show.failureCount.toLocaleString()+' failures, worst first';
  renderTable('tS',show.success); renderTable('tF',show.failure);
}

async function loadSignal(){
  const meta=await (await fetch('/api/meta/'+encodeURIComponent($('signal').value))).json();
  $('spot').innerHTML=(meta.spots||[]).map(s=>'<option>'+esc(s)+'</option>').join('');
  if(meta.spots&&meta.spots.length) await runAll();
}

(function funcs(){
  $('funclist').innerHTML=FUNCS.map(f=>'<code title="'+esc(f.desc)+'">'+esc(f.name)+
    '('+(f.arity<0?'…':Array(f.arity).fill('a').join(', '))+')</code>').join(' · ');
})();

(function fields(){
  let h='<table><thead><tr><th>Field</th><th>Type</th><th>Use</th><th>Meaning</th></tr></thead><tbody>';
  for(const f of FIELDS)
    h+='<tr><td><code>'+esc(f.name)+'</code></td><td class="ts">'+esc(f.type)+'</td>'+
       '<td>'+(f.outcome?'<span class="tag">success only</span>':'<span class="tag t">filter + success</span>')+'</td>'+
       '<td class="ts">'+esc(f.desc)+'</td></tr>';
  $('ftab').innerHTML=h+'</tbody></table>';
})();

(async function init(){
  const sigs=await (await fetch('/api/signals')).json();
  if(!sigs.length){ $('tS').innerHTML='<div class="empty">No patterns. Run: node patterns.js</div>'; return; }
  $('signal').innerHTML=sigs.map(s=>'<option>'+esc(s)+'</option>').join('');
  $('signal').addEventListener('change',loadSignal);
  $('spot').addEventListener('change',runAll);
  $('run').addEventListener('click',runAll);
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
        if (url === '/api/signals') return json(res, listSignals());

        const m = url.match(/^\/api\/meta\/([^/]+)$/);
        if (m) return json(res, { signalId: m[1], spots: listSpots(m[1]) });

        if (url === '/api/query' && req.method === 'POST') {
            let body = '';
            req.on('data', c => { body += c; });
            req.on('end', () => {
                try {
                    const q = JSON.parse(body);
                    const { rows } = loadRows(q.signal, q.spot);
                    return json(res, runQuery(rows, q.filter || '', q.success || 'univRatio >= 10',
                                              q.limit || 200, q.derived || ''));
                } catch (err) {
                    // Parse errors are the user's, not the server's, so they are
                    // returned as text rather than a 500.
                    return json(res, { error: err.message || String(err) });
                }
            });
            return;
        }

        res.writeHead(404); res.end('Not found');
    } catch (err) {
        console.error(`Error on ${url}:`, err);
        res.writeHead(500); res.end('Server error');
    }
}).listen(PORT, () => {
    console.log('');
    console.log(`Query  →  http://localhost:${PORT}`);
    console.log(`  patterns : ${DIR}`);
    console.log(`  signals  : ${listSignals().join(', ') || '(none — run patterns.js)'}`);
    console.log(`  split    : ${(TRAIN_FRACTION * 100).toFixed(0)}% train / ${(100 - TRAIN_FRACTION * 100).toFixed(0)}% test, by expiry date`);
    console.log('');
});
