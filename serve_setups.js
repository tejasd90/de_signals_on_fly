// serve_setups.js
// ─────────────────────────────────────────────────────────────────────────────
// Price-action SETUP review, one sheet per expiry.  Run: node serve_setups.js (4000)
//
// MERGED 2026-10-04 into the main dashboard (:8777, dash_server.py): the same sheet is the
// 'setup review' drawer there, and the setups are also drawn on the chart. Kept runnable,
// but docs/DASHBOARD.md is the place to look.
//
// Inverts the grid viewers. 3800/3900 start from a signal and show its context;
// this starts from a Brooks SETUP on spot and shows what happened next, plus any
// option signals that fired within a few bars of it. A few dozen rows per expiry
// instead of a few thousand cells, so a whole expiry reads at a glance.
//
// EVERY ROW CARRIES THE MEASURED WIN RATE, not only Brooks' claim. Across 220
// perps, 258,402 setups and 141 weeks, no setup reached his 60% benchmark and
// every reward multiple from 1R to 5R was negative after costs. The sheet shows
// that number next to the expectation so the two are never confused.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';
const http=require('http'), fs=require('fs'), path=require('path');
const netinfo=require('./netinfo'), chart=require('./chart_url');
const args=process.argv.slice(2);
const PORT=args.includes('--port')?parseInt(args[args.indexOf('--port')+1]):4000;
const BASE=path.join('data','setup_review');

const spots=()=>fs.existsSync(BASE)?fs.readdirSync(BASE).filter(d=>!d.startsWith('.')).sort():[];
const expiries=s=>{const d=path.join(BASE,s);return fs.existsSync(d)
  ?fs.readdirSync(d).filter(f=>f.endsWith('.json')).map(f=>f.slice(0,-5)).sort().reverse():[];};
function sheet(s,e){try{return JSON.parse(fs.readFileSync(path.join(BASE,s,`${e}.json`),'utf8'));}
  catch(_){return{spot:s,expiry:e,setups:[]};}}

function page(){return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>setup review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
<style>
 :root{--bg:#0e1117;--surface:#161b25;--line:#232a37;--text:#c9d1d9;--muted:#7d8694;--accent:#d4823f}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);
   font-family:'JetBrains Mono',monospace;font-size:12.5px}
 .wrap{max-width:1500px;margin:0 auto;padding:18px}
 h1{font-family:'Space Grotesk',sans-serif;font-size:17px;color:var(--accent);margin:0 0 3px}
 .sub{color:var(--muted);font-size:11.5px;max-width:960px;line-height:1.55}
 .ctl{display:flex;gap:16px;align-items:flex-end;margin:16px 0;flex-wrap:wrap}
 label{display:block;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
 select{background:var(--surface);color:var(--text);border:1px solid var(--line);
   border-radius:5px;padding:5px 8px;font-family:inherit;font-size:12px}
 table{border-collapse:collapse;width:100%;margin-top:6px}
 th{text-align:left;font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:#5a6070;
    padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
 td{padding:6px 8px;border-bottom:1px solid #1b212c;vertical-align:top}
 tr.s:hover{background:#1a202b}
 .dir{font-weight:700} .long{color:#6a9d7f} .short{color:#c96a5a}
 .win{color:#6a9d7f} .lose{color:#c96a5a} .unres{color:var(--muted)}
 .big{color:var(--accent);font-weight:700}
 .sig{font-size:11px;color:var(--muted);padding-left:14px}
 .sig a{color:var(--accent);text-decoration:none;border-bottom:1px dotted currentColor}
 .note{color:#5a6070;font-size:10.5px;margin:10px 0 0;line-height:1.5}
 .empty{color:var(--muted);padding:26px 0}
</style></head><body><div class="wrap">
 <h1>price-action setup review</h1>
 <div class="sub">Each row is a Brooks setup on SPOT during this expiry's life. "expected" is his
  claim; "measured" is the win rate from 258,402 setups across 220 perps — no setup reached his 60%
  benchmark, and every reward multiple from 1R to 5R was negative after costs. Signals listed
  beneath a row fired within 3 bars of it, in the same direction.</div>
 <div class="ctl">
  <span><label for="spot">Spot</label><select id="spot"></select></span>
  <span><label for="exp">Expiry</label><select id="exp"></select></span>
  <span><label for="filt">Show</label><select id="filt">
    <option value="all">all setups</option>
    <option value="sig">only those with signals</option>
    <option value="win">only those that hit target</option>
    <option value="big">only those with a 10x+ signal</option>
  </select></span>
 </div>
 <div id="out"></div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CHART_HOST=location.hostname;
const fix=u=>String(u||'').replace('__CHART_HOST__',CHART_HOST);
let DATA={setups:[]};
function row(s){
  const res=s.result==='target'?'<span class="win">target</span>'
          :s.result==='stopped'?'<span class="lose">stopped</span>'
          :'<span class="unres">unresolved</span>';
  const br=s.best_ratio>=10?'<span class="big">'+s.best_ratio+'x</span>'
         :(s.best_ratio>0?s.best_ratio+'x':'—');
  let h='<tr class="s"><td>'+esc(String(s.tsIso||'').slice(5,16).replace('T',' '))+'</td>'+
    '<td>'+s.tf+'m</td><td>'+esc(s.name)+'</td>'+
    '<td class="dir '+s.dir+'">'+s.dir+'</td>'+
    '<td>'+(s.measured!=null?s.measured+'%':'—')+'</td>'+
    '<td>'+res+'</td><td>'+s.mfe_R.toFixed(2)+'R</td>'+
    '<td>'+(s.n_signals||0)+'</td><td>'+br+'</td></tr>';
  if(s.signals&&s.signals.length){
    h+='<tr><td colspan="9" class="sig">'+s.expect+'<br>'+
      s.signals.map(g=>'<span>'+esc(g.signal)+' '+g.dur+'m '+g.ty+
        ' &middot; '+(g.lag>0?'+':'')+g.lag+' bars &middot; paid '+g.ratio+'x &middot; '+
        g.syms.map(x=>'<a href="'+fix(g.url&&g.url[x]||'#')+'" target="_blank" rel="noopener">'+esc(x)+'</a>').join(' ')+
        '</span>').join('<br>')+'</td></tr>';
  }
  return h;
}
function render(){
  const f=$('filt').value;
  let rows=DATA.setups||[];
  if(f==='sig') rows=rows.filter(s=>s.n_signals>0);
  if(f==='win') rows=rows.filter(s=>s.result==='target');
  if(f==='big') rows=rows.filter(s=>s.best_ratio>=10);
  if(!rows.length){$('out').innerHTML='<div class="empty">No setups match.</div>';return;}
  const n=rows.length, w=rows.filter(s=>s.result==='target').length;
  const withSig=rows.filter(s=>s.n_signals>0).length;
  $('out').innerHTML='<div class="note">'+n+' setups &middot; '+w+' reached target ('+
    (100*w/n).toFixed(0)+'%) &middot; '+withSig+' had a signal within 3 bars</div>'+
    '<table><thead><tr><th>when</th><th>tf</th><th>setup</th><th>dir</th>'+
    '<th>measured</th><th>spot</th><th>max fav</th><th>signals</th><th>best</th></tr></thead><tbody>'+
    rows.map(row).join('')+'</tbody></table>';
}
async function load(){
  const s=$('spot').value,e=$('exp').value;
  if(!s||!e){$('out').innerHTML='<div class="empty">No data.</div>';return;}
  DATA=await (await fetch('/api/sheet/'+encodeURIComponent(s)+'/'+encodeURIComponent(e))).json();
  render();
}
async function loadExp(){
  const s=$('spot').value;
  const ex=await (await fetch('/api/expiries/'+encodeURIComponent(s))).json();
  $('exp').innerHTML=ex.map(x=>'<option>'+x+'</option>').join('');
  await load();
}
(async function(){
  const sp=await (await fetch('/api/spots')).json();
  if(!sp.length){$('out').innerHTML='<div class="empty">Run build_setup_review.py first.</div>';return;}
  $('spot').innerHTML=sp.map(x=>'<option>'+x+'</option>').join('');
  $('spot').addEventListener('change',loadExp);
  $('exp').addEventListener('change',load);
  $('filt').addEventListener('change',render);
  await loadExp();
})();
</script></body></html>`;}

function selfCheck(){try{const m=/<script>([\s\S]*?)<\/script>/.exec(page());new Function(m[1]);return true;}
  catch(e){console.error('\n!!! SELF-CHECK FAILED — client script does not parse !!!\n    '+e.message+'\n');return false;}}

function json(res,b){const s=JSON.stringify(b);
  res.writeHead(200,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(s)});res.end(s);}

http.createServer((req,res)=>{
  const url=decodeURIComponent(req.url.split('?')[0]);
  try{
    if(url==='/'||url==='/index.html'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});return res.end(page());}
    if(url==='/api/spots') return json(res,spots());
    let m=url.match(/^\/api\/expiries\/([^/]+)$/); if(m) return json(res,expiries(m[1]));
    m=url.match(/^\/api\/sheet\/([^/]+)\/([^/]+)$/);
    if(m){
      const d=sheet(m[1],m[2]);
      for(const s of d.setups){
        s.tsIso=new Date(s.ts*1000+19800000).toISOString();
        for(const g of (s.signals||[])){
          g.url={}; for(const sym of g.syms)
            g.url[sym]=chart.chartUrl(m[1],m[2],sym,new Date(g.iso).getTime(),g.dur);
        }
      }
      return json(res,d);
    }
    res.writeHead(404);res.end('Not found');
  }catch(e){console.error(url,e);res.writeHead(500);res.end('Server error');}
}).listen(PORT,'0.0.0.0',()=>{
  selfCheck();
  console.log(netinfo.banner('Price-action setup review — one sheet per expiry',PORT,[
    `spots   : ${spots().join(', ')||'(none)'}`,
    `source  : data/setup_review, built by build_setup_review.py`,
  ]));
});
