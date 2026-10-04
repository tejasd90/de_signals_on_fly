// dashboard_selftest.js — loaded only when the page is opened with ?selftest.
// Drives the real page (real data, real Plotly) through the interactions the spec cares
// about, and writes PASS/FAIL lines into <pre id="selftest">, which headless Chrome dumps.
//   node: "Google Chrome" --headless=new --dump-dom --virtual-time-budget=60000 URL?selftest
(function () {
  const out = [];
  const errs = [];
  window.addEventListener('error', e => errs.push(String(e.message || e)));
  window.addEventListener('unhandledrejection', e => errs.push('promise: ' + String(e.reason)));
  const ok = (name, cond, detail) => out.push(`${cond ? 'PASS' : 'FAIL'} ${name}${detail ? '  -- ' + detail : ''}`);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const gd = () => document.getElementById('chart');
  const range = () => gd().layout.xaxis.range.map(x => new Date(x).getTime() / 1000);
  const hm = () => gd().data.find(t => t.type === 'heatmap');
  async function until(f, ms = 20000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (f()) return true; } catch (_) {} await sleep(100); } return false; }

  async function run() {
    const loaded = await until(() => P && gd().data && gd().data.length >= 4 && document.getElementById('exp').options.length);
    ok('page loads payload, setups and expiries', loaded, loaded ? '' : 'status: ' + document.getElementById('stamp').textContent + ' | P=' + (typeof P !== 'undefined' && !!P) + ' traces=' + ((gd().data||[]).length) + ' exp=' + document.getElementById('exp').options.length);
    if (!loaded) return finish();
    const C = P.candles, n = C.ts.length;

    // 1. one shared time axis for candles, PA points, setups and the 1:100 grid
    const axes = gd().data.map(t => t.xaxis || 'x');
    ok('all panes share one x axis', axes.every(a => a === 'x'), axes.join(','));
    const h = hm();
    const x0 = new Date(h.x[0]).getTime() / 1000, x4 = new Date(h.x[4]).getTime() / 1000;
    ok('grid cells sit inside their candle', x0 >= C.ts[0] - STEP / 2 && x4 <= C.ts[0] + STEP / 2, `${x0 - C.ts[0]}s .. ${x4 - C.ts[0]}s of a ${STEP}s candle`);
    ok('grid has 3 slot rows x 5 columns per candle', h.z.length === 3 && h.z[0].length === n * 5);

    // 2. first view: the latest ~45 candles, numbers printed
    const [a0, b0] = range();
    const vis0 = C.ts.filter(t => t >= a0 && t <= b0).length;
    ok('first view shows the latest candles', b0 >= C.ts[n - 1] && vis0 >= 6 && vis0 <= 46, `${vis0} candles visible`);
    await until(() => hm().texttemplate !== undefined);
    ok('numbers printed on cells at the default zoom', hm().texttemplate === '%{text}', `texttemplate=${JSON.stringify(hm().texttemplate)}`);
    const yr = gd().layout.yaxis.range;
    const vlo = Math.min(...C.l.filter((_, i) => C.ts[i] >= a0 && C.ts[i] <= b0)), vhi = Math.max(...C.h.filter((_, i) => C.ts[i] >= a0 && C.ts[i] <= b0));
    ok('price axis fits the visible candles', yr && yr[0] <= vlo && yr[1] >= vhi && (yr[1] - yr[0]) < 1.3 * (vhi - vlo) + 1e-6, `y ${yr && yr.map(v => v.toFixed(0))} vs candles ${vlo.toFixed(0)}..${vhi.toFixed(0)}`);
    const lab0 = gd().layout.yaxis3.ticktext.join('|');
    ok('slot labels name the expiries', /immediate<br>\d{4}-\d{2}-\d{2}/.test(lab0), lab0.replace(/<br>/g, ' '));

    // 3. zoom out: numbers hide when cells get too narrow to read
    await Plotly.relayout(gd(), { 'xaxis.range': [new Date(C.ts[0] * 1000), new Date(C.ts[n - 1] * 1000)] });
    await until(() => hm().texttemplate === '');
    ok('numbers hidden when zoomed out (unreadable)', hm().texttemplate === '');

    // 4. pan into the past: expiry labels follow the right-most visible candle
    const mid = Math.floor(n / 3);
    const vc = visibleCandles();
    await Plotly.relayout(gd(), { 'xaxis.range': [new Date((C.ts[mid - vc + 1] - STEP / 2) * 1000), new Date((C.ts[mid] + STEP / 2) * 1000)] });
    await sleep(800);
    const lab1 = gd().layout.yaxis3.ticktext.join('|');
    const want = (P.req || []).filter(r => r.ts === C.ts[mid] && r.slot === 'immediate').map(r => r.expiry)[0];
    ok('labels roll to the expiries live at that point in the past', !want || lab1.includes(want), `want ${want}, got ${lab1.replace(/<br>/g, ' ')}`);
    ok('numbers come back when zoomed in again', hm().texttemplate === '%{text}');

    // 5. auto-refresh keeps a panned-into-history view
    const before = range();
    await load(true); await sleep(500);
    const after = range();
    ok('auto-refresh keeps the user\'s view', Math.abs(before[0] - after[0]) < 1 && Math.abs(before[1] - after[1]) < 1);

    // 6. "latest" returns to the live edge
    document.getElementById('latest').click(); await sleep(500);
    const [a2, b2] = range();
    ok('"latest" returns to the newest candles', b2 >= C.ts[n - 1] && a2 > C.ts[Math.max(0, n - 80)]);

    // 7. setup markers on the PA pane
    const st = gd().data.find(t => t.name === 'setups');
    ok('setup markers drawn (or none in window)', st && st.x.length === SETUPS.length, `${SETUPS.length} setups`);
    if (SETUPS.length) ok('setup hover carries name, measured rate, result', /measured win rate/.test(st.text[0]) && /spot:/.test(st.text[0]));

    // 8. setup review drawer (was :4000)
    document.getElementById('toggleDrawer').click(); await sleep(300);
    ok('drawer opens', document.getElementById('drawer').classList.contains('open'));
    const lastImm = (P.req || []).filter(r => r.ts === C.ts[n - 1] && r.slot === 'immediate').map(r => r.expiry)[0];
    ok('drawer defaults to the immediate expiry', !lastImm || document.getElementById('exp').value === lastImm, `${document.getElementById('exp').value} vs ${lastImm}`);
    // pick an expiry inside the loaded window that has setups, then click a row
    const exps = [...document.getElementById('exp').options].map(o => o.value);
    let clicked = false;
    for (const e of exps) {
      if (new Date(e).getTime() / 1000 > C.ts[n - 1] + 31 * 86400) continue;
      document.getElementById('exp').value = e; await loadSheet();
      const row = [...document.querySelectorAll('#dtab tr.s')].find(r => +r.dataset.ts >= C.ts[0] && +r.dataset.ts <= C.ts[n - 1]);
      if (!row) continue;
      row.click(); await sleep(500);
      const [a3, b3] = range(); const t = +row.dataset.ts;
      ok('clicking a setup row centres the chart on it', a3 < t && b3 > t && Math.abs((a3 + b3) / 2 - t) < STEP * 2, `expiry ${e}`);
      clicked = true; break;
    }
    ok('found a setup inside the loaded window to click', clicked);
    for (const f of ['sig', 'win', 'big', 'all']) {
      document.getElementById('filt').value = f; renderSheet();
      const rows = [...document.querySelectorAll('#dtab tr.s')].length;
      const all = SHEET.setups.filter(s => f === 'all' || (f === 'sig' && s.n_signals > 0) || (f === 'win' && s.result === 'target') || (f === 'big' && s.best_ratio >= 10)).length;
      ok(`filter "${f}" shows the matching rows`, rows === all, `${rows} rows`);
    }
    const a = document.querySelector('#dtab a');
    if (a) ok('chart links point at :3000/de on this host', a.href.startsWith(`http://${location.hostname}:3000/de/`), a.href.slice(0, 60));

    // 9. side panels
    ok('proximity panel rendered', document.getElementById('prox').children.length > 0);
    await until(() => document.getElementById('live').textContent.includes('immediate'), 8000);
    ok('live 1:100 panel rendered', document.getElementById('live').textContent.includes('immediate'));
    finish();
  }
  function finish() {
    ok('no JavaScript errors', errs.length === 0, errs.slice(0, 3).join(' | '));
    const pre = document.createElement('pre'); pre.id = 'selftest';
    pre.textContent = out.join('\n') + `\n${out.filter(l => l.startsWith('FAIL')).length ? 'SELFTEST FAILED' : 'SELFTEST PASSED'}`;
    document.body.appendChild(pre);
    fetch('/api/selftest' + location.search, { method: 'POST', body: pre.textContent }).catch(() => {});
  }
  run().catch(e => { errs.push('selftest crashed: ' + e); finish(); });
})();
