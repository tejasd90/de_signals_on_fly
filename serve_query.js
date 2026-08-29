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
const netinfo = require('./netinfo');
const ql    = require('./query_lang');

const args = process.argv.slice(2);
const PORT = args.includes('--port') ? parseInt(args[args.indexOf('--port') + 1]) : 3700;
const DIR  = path.join(cfg.DATA_BASE_DIR, 'patterns');

// Host-relative. Hardcoding localhost meant a chart link opened on a phone
// resolved to the PHONE, so every link 404'd off the LAN. The page substitutes
// its own hostname client-side.
const CHART_HOST_PLACEHOLDER = '__CHART_HOST__';
const CHART_BASE = `http://${CHART_HOST_PLACEHOLDER}:3000/de`;
const CHART_LEAD_CANDLES = 40;

// Walk-forward: several sequential folds rather than one split.
//
// A single date split reports one number that depends heavily on which regime
// happened to land in the test half. Walk-forward tests across SEVERAL regimes,
// each strictly out of sample, and reports the spread as well as the mean.
//
// Splitting by DATE, not randomly. A random split sends signals from the SAME
// expiry — the same underlying move — to both sides, so the holdout is measuring
// data it already trained on and reads far better than anything achievable live.
// Trading is always forward in time; the split should be too.
const WALK_FORWARD_FOLDS = 3;

// Fraction used for the first fold's training window; each later fold trains on
// everything before its own test window.
const FIRST_TRAIN_FRACTION = 0.5;

// PURGE: a signal can fire up to this long before its own expiry, so a test
// signal may observe market days that fall inside the training window. Rows
// whose observation window straddles a fold boundary are dropped.
const PURGE_ENABLED = true;

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
    const out = { rows: [], expiries: [], folds: [] };
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
    out.folds = buildFolds(sorted);

    // Tag each row with, per fold, whether it is train / test / purged.
    for (const r of raw) {
        r._fold = out.folds.map(f => assignToFold(r, f));
    }

    out.rows = raw; out.expiries = sorted;
    _cache.set(key, out);
    return out;
}

/**
 * Sequential expanding-window folds.
 *
 *   fold 1: train [0 .. a)          test [a .. b)
 *   fold 2: train [0 .. b)          test [b .. c)
 *   fold 3: train [0 .. c)          test [c .. end]
 *
 * Expanding rather than sliding, because more history is genuinely better and a
 * sliding window would discard it for no benefit.
 */
function buildFolds(sortedExpiries) {
    const n = sortedExpiries.length;
    if (n < WALK_FORWARD_FOLDS * 2) {
        // Too few expiries to fold meaningfully; fall back to one split.
        const cut = sortedExpiries[Math.max(0, Math.floor(n * 0.7) - 1)] || null;
        return cut ? [{ index: 1, trainEnd: cut, testEnd: sortedExpiries[n - 1] }] : [];
    }

    const firstTrain = Math.max(1, Math.floor(n * FIRST_TRAIN_FRACTION));
    const remaining  = n - firstTrain;
    const perFold    = Math.max(1, Math.floor(remaining / WALK_FORWARD_FOLDS));

    const folds = [];
    let start = firstTrain;
    for (let i = 0; i < WALK_FORWARD_FOLDS; i++) {
        const isLast = (i === WALK_FORWARD_FOLDS - 1);
        const end    = isLast ? n : Math.min(n, start + perFold);
        if (start >= n) break;
        folds.push({
            index:    i + 1,
            trainEnd: sortedExpiries[start - 1],      // last TRAIN expiry
            testEnd:  sortedExpiries[end - 1],        // last TEST expiry
        });
        start = end;
    }
    return folds;
}

/**
 * Which side of one fold a row falls on.
 *
 * 'purge' means the row's observation window straddles the boundary: it fired
 * during the training period but settles during the test period, so it observes
 * days on both sides. Counting it either way leaks.
 */
function assignToFold(row, fold) {
    const fired = String(row.patternStart || row.entryTs).slice(0, 10);

    if (row.expiry <= fold.trainEnd) return 'train';
    if (row.expiry >  fold.testEnd)  return 'unused';   // beyond this fold's test window

    // Test-side row: purge it if it FIRED on or before the training boundary.
    if (PURGE_ENABLED && fired <= fold.trainEnd) return 'purge';
    return 'test';
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

/**
 * Fields referenced by an expression that are null or absent on EVERY row.
 *
 * A missing numeric field evaluates to 0, so a clause like `ratio1 + ratio2 > 50`
 * on a signal that never computes those fields parses cleanly, is always false,
 * and returns an empty table with no explanation. Naming the field turns a silent
 * zero into a reason.
 */
function unpopulatedFields(expr, rows) {
    if (!expr || !expr.fields || !rows.length) return [];

    const sample = rows.length > 5000
        ? rows.filter((_, i) => i % Math.ceil(rows.length / 5000) === 0)
        : rows;

    const missing = [];
    for (const f of expr.fields) {
        if (!ql.FIELDS[f] || ql.FIELDS[f].derived) continue;
        const anyPopulated = sample.some(r => r[f] !== undefined && r[f] !== null);
        if (!anyPopulated) missing.push(f);
    }
    return missing;
}

function runQuery(rows, folds, filterSrc, successSrc, limit, derivedSrc, merge) {
    ql.clearDerived();
    const derived = derivedSrc && derivedSrc.trim() ? ql.parseDerived(derivedSrc) : [];

    const filterFn  = filterSrc.trim()
        ? ql.compile(filterSrc,  { allowOutcome: false })   // lookahead guard
        : () => true;
    const successFn = ql.compile(successSrc, { allowOutcome: true });

    const notPopulated = [
        ...unpopulatedFields(filterFn,  rows),
        ...unpopulatedFields(successFn, rows),
    ].filter((v, i, a) => a.indexOf(v) === i);

    // Filter FIRST, merge after. Merging before would collapse the
    // per-instrument fields the filter works on into maxima.
    const kept = [];
    for (const r of rows) {
        if (derived.length) ql.applyDerived(derived, r);
        if (filterFn(r)) kept.push(r);
    }

    const units = merge ? mergeRows(kept) : kept.map(asUnit);

    const bucket = () => ({ n: 0, wins: 0 });
    const overall = bucket();
    const foldStats = folds.map(() => ({ train: bucket(), test: bucket(), purged: 0 }));

    const successes = [], failures = [];

    for (const u of units) {
        const win = u.rows.some(successFn);       // a merged event wins if ANY
                                                  // member reached the target,
                                                  // matching maxRatio semantics
        overall.n++; if (win) overall.wins++;
        (win ? successes : failures).push(u);

        folds.forEach((f, i) => {
            // A merged unit takes the fold side of its FIRST member; members of
            // one event share an expiry, so they always agree.
            const side = u.rows[0]._fold ? u.rows[0]._fold[i] : 'train';
            if (side === 'purge')  { foldStats[i].purged++; return; }
            if (side === 'unused') return;
            const b = foldStats[i][side];
            b.n++; if (win) b.wins++;
        });
    }

    successes.sort((a, b) => b.univRatio - a.univRatio);
    failures.sort((a, b) => a.univRatio - b.univRatio);

    const pct = b => b.n ? (b.wins / b.n) * 100 : 0;

    const foldOut = folds.map((f, i) => ({
        index: f.index, trainEnd: f.trainEnd, testEnd: f.testEnd,
        train: { ...foldStats[i].train, pct: pct(foldStats[i].train) },
        test:  { ...foldStats[i].test,  pct: pct(foldStats[i].test),
                 thin: foldStats[i].test.n < MIN_SAMPLE },
        purged: foldStats[i].purged,
        gap: pct(foldStats[i].train) - pct(foldStats[i].test),
    }));

    const testPcts = foldOut.filter(f => !f.test.thin).map(f => f.test.pct);
    const meanTest = testPcts.length
        ? testPcts.reduce((a, b) => a + b, 0) / testPcts.length : 0;
    const spread = testPcts.length > 1
        ? Math.max(...testPcts) - Math.min(...testPcts) : 0;

    return {
        merged: !!merge,
        notPopulated,
        totalRows: kept.length,
        total: overall.n,
        all: { n: overall.n, wins: overall.wins, pct: pct(overall) },
        folds: foldOut,
        meanTest, spread,
        successCount: successes.length,
        failureCount: failures.length,
        success: successes.slice(0, limit).map(slimUnit),
        failure: failures.slice(0, limit).map(slimUnit),
    };
}

/** A single unfiltered row presented as a one-member unit. */
function asUnit(r) {
    return {
        rows: [r], count: 1,
        startTs: r.patternStart || r.entryTs, entryTs: r.entryTs,
        signalValue: r.signalValue, ratio: r.ratio, univRatio: r.univRatio,
        univSymbol: r.univSymbol || null,
        symbols: [r.symbol], expiry: r.expiry, duration: r.duration, type: r.type,
        tteHours: r.tteHours, distancePct: r.distancePct, state: r.state,
    };
}

/**
 * Merge surviving rows into market events by overlapping time window, within
 * the same (expiry, duration, type).
 *
 * The same move fires on many strikes; without this, one event with 8 strikes
 * counts 8 times and the percentages measure how broadly signals cluster rather
 * than how often you would have been right.
 *
 * A merged unit carries the MAX ratio across members — the assumption being that
 * seeing one alert you would pick a strike, not buy all of them. Optimistic, and
 * the same assumption every earlier number in this project was built on.
 */
function mergeRows(rows) {
    const groups = new Map();
    for (const r of rows) {
        const k = `${r.expiry}|${r.duration}|${r.type}`;
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(r);
    }

    const units = [];

    for (const [, list] of groups) {
        list.sort((a, b) =>
            new Date(a.patternStart || a.entryTs) - new Date(b.patternStart || b.entryTs));

        let cur = null;
        for (const r of list) {
            const s = new Date(r.patternStart || r.entryTs).getTime();
            const e = new Date(r.entryTs).getTime();

            if (cur && s <= cur.endMs) {
                cur.endMs = Math.max(cur.endMs, e);
                cur.rows.push(r);
            } else {
                if (cur) units.push(finaliseUnit(cur));
                cur = { startMs: s, endMs: e, rows: [r] };
            }
        }
        if (cur) units.push(finaliseUnit(cur));
    }

    return units;
}

function finaliseUnit(u) {
    let best = u.rows[0];
    for (const r of u.rows) if ((r.univRatio || 0) > (best.univRatio || 0)) best = r;

    return {
        rows: u.rows, count: u.rows.length,
        startTs: best.patternStart || best.entryTs,
        entryTs: best.entryTs,
        signalValue: Math.max(...u.rows.map(r => r.signalValue || 0)),
        ratio:      Math.max(...u.rows.map(r => r.ratio || 0)),
        univRatio:  Math.max(...u.rows.map(r => r.univRatio || 0)),
        univSymbol: best.univSymbol || null,
        symbols: [...new Set(u.rows.map(r => r.symbol))],
        expiry: best.expiry, duration: best.duration, type: best.type,
        tteHours: best.tteHours, distancePct: best.distancePct, state: best.state,
    };
}

function slimUnit(u) {
    return {
        count: u.count, startTs: u.startTs, entryTs: u.entryTs,
        signalValue: u.signalValue, ratio: u.ratio, univRatio: u.univRatio,
        univSymbol: u.univSymbol, symbols: u.symbols.slice(0, 10),
        expiry: u.expiry, duration: u.duration, type: u.type,
        tteHours: u.tteHours, distancePct: u.distancePct, state: u.state,
        url: u.rows[0] ? chartUrl(u.rows[0]) : null,
    };
}

// ─── Page ─────────────────────────────────────────────────────────────────────

function renderPage() {
    const funcRows = Object.entries(ql.FUNCS)
        .map(([n, d]) => ({ name: n, arity: d.arity, desc: d.desc }));
    // The expression that reproduces the CURRENT config, so the box opens showing
    // what is actually being applied and you edit numbers rather than write from
    // scratch.
    const defaultFilters = {
        red_squeeze:     `signalValue >= ${cfg.RED_SQUEEZE_THRESHOLD} && tteHours >= ${cfg.MIN_TTE_HOURS_TO_FIRE}`,
        otm_red_squeeze: `signalValue >= ${cfg.OTM_SIGNAL_THRESHOLD} && tteHours >= ${cfg.MIN_TTE_HOURS_TO_FIRE} && seqLength >= ${cfg.OTM_MIN_SEQ_LENGTH}`,
        green_stairs:    `signalValue >= ${cfg.OTM_SIGNAL_THRESHOLD} && tteHours >= ${cfg.MIN_TTE_HOURS_TO_FIRE} && seqLength >= ${cfg.OTM_MIN_SEQ_LENGTH} && equalSteps <= ${cfg.GREEN_STAIRS_MAX_EQUAL_STEPS}`,
        otm_wall:        `signalValue >= ${cfg.WALL_JUMP_THRESHOLD} && tteHours >= ${cfg.MIN_TTE_HOURS_TO_FIRE}`,
    };

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
    <span><label for="merge">Count</label>
      <select id="merge">
        <option value="1">Merged events</option>
        <option value="0">Individual signals</option>
      </select></span>
    <button id="run">Run</button>
    <span class="sub" id="status"></span>
  </div>

  <div class="slot" style="margin-bottom:14px">
    <h3>Computed fields</h3>
    <textarea id="derived" placeholder="punch = ratio1 * ratio2 / avgPrice&#10;logCheap = log10(cheapness)"></textarea>
    <div class="sub" style="margin-top:5px">One per line, <code>name = expression</code>. Each becomes
      queryable like any other field, and may reference fields defined above it. A definition
      touching an outcome field is itself an outcome and refused in filters.</div>
    <div class="err" id="derr"></div>
  </div>

  <div class="slot">
    <h3>Query</h3>
    <div class="f"><label>Filter — entry-time fields only. Prefilled with the current criteria.</label>
      <textarea id="filter"></textarea>
      <div class="sub" style="margin-top:4px">
        <button class="sec" id="resetFilter" style="padding:3px 10px;font-size:11px">Reset to current config</button>
      </div></div>
    <div class="f"><label>Success</label>
      <textarea id="success">univRatio &gt;= 10</textarea></div>
    <div class="err" id="qerr"></div>
    <div class="res" id="res"></div>
    <div class="warn" id="warn"></div>
    <div id="folds" style="margin-top:10px"></div>
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
// Chart links are built server-side with a placeholder host; swap in whatever
// host actually served this page so links work from any device on the LAN.
document.addEventListener('DOMContentLoaded',()=>{},{once:true});
const CHART_HOST=location.hostname;
function fixChartUrl(u){ return String(u||'').replace('__CHART_HOST__',CHART_HOST); }
const FIELDS=${JSON.stringify(fieldRows)};
const FUNCS=${JSON.stringify(funcRows)};
const RCOL=['var(--r0)','var(--r1)','var(--r2)','var(--r3)','var(--r4)'];
const BANDS=${JSON.stringify(cfg.RATIO_BANDS.map(b => ({ min: b.min, max: b.max === Infinity ? null : b.max })))};
const MIN_SAMPLE=${MIN_SAMPLE};

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortTs=t=>String(t).slice(0,16).replace('T',' ');
function band(v){if(!(v>0))return 0;for(let i=0;i<BANDS.length;i++){const b=BANDS[i];if(v>=b.min&&(b.max===null||v<b.max))return i;}return BANDS.length-1;}

const DEFAULT_FILTERS=${JSON.stringify(defaultFilters)};

function renderMetrics(r){
  const cell=(cls,l,v,sub)=>'<div class="m '+cls+'"><div class="l">'+esc(l)+'</div><div class="v">'+
    esc(v)+'</div><div class="s">'+esc(sub||'')+'</div></div>';

  $('res').innerHTML=
    cell('','rows matched',r.totalRows.toLocaleString(),'')+
    cell('',r.merged?'merged events':'signals',r.total.toLocaleString(),'')+
    cell('','all',r.all.pct.toFixed(1)+'%',r.all.wins+' / '+r.all.n)+
    cell('test','mean out-of-sample',r.meanTest.toFixed(1)+'%','across folds')+
    cell('gap','fold spread',r.spread.toFixed(1)+' pts','max − min');

  // Per-fold detail: one line each, so a result that holds up in every regime
  // is distinguishable from one carried by a single lucky window.
  let h='<table style="font-size:11px"><thead><tr>'+
    '<th>Fold</th><th>Train ends</th><th>Test ends</th>'+
    '<th class="num">Train</th><th class="num">Test</th>'+
    '<th class="num">Gap</th><th class="num">Purged</th></tr></thead><tbody>';
  for(const f of r.folds){
    h+='<tr>'+
      '<td>'+f.index+'</td>'+
      '<td class="ts">'+esc(f.trainEnd)+'</td>'+
      '<td class="ts">'+esc(f.testEnd)+'</td>'+
      '<td class="num">'+f.train.pct.toFixed(1)+'% <span class="ts">'+f.train.n+'</span></td>'+
      '<td class="num"'+(f.test.thin?' style="color:var(--muted)"':'')+'>'+
        f.test.pct.toFixed(1)+'% <span class="ts">'+f.test.n+'</span></td>'+
      '<td class="num">'+f.gap.toFixed(1)+'</td>'+
      '<td class="num ts">'+f.purged+'</td></tr>';
  }
  $('folds').innerHTML=h+'</tbody></table>';

  let w='';
  if(r.notPopulated && r.notPopulated.length)
    w+='<b>Not populated for this signal: '+r.notPopulated.map(esc).join(', ')+'.</b> '+
       'Missing numeric fields evaluate to 0, so any clause using them matches nothing. '+
       'Check the field table for what this signal records.<br>';
  const thin=r.folds.some(f=>f.test.thin);
  if(thin) w+='<b>Thin fold.</b> At least one test window has fewer than '+MIN_SAMPLE+
              ' units — that percentage is noise. Loosen the filter.<br>';
  if(!thin && r.spread>15)
    w+='<b>Folds disagree by '+r.spread.toFixed(1)+' points.</b> The result depends heavily on '+
       'which regime it was tested in. Treat the mean as optimistic.<br>';
  const meanGap=r.folds.reduce((a,f)=>a+f.gap,0)/Math.max(1,r.folds.length);
  if(!thin && meanGap>10)
    w+='<b>Train beats test by '+meanGap.toFixed(1)+' points on average.</b> That gap is the '+
       'signature of a curve fit. Trust the out-of-sample number.';
  $('warn').className='warn'+(w?' on':'');
  $('warn').innerHTML=w;
}

function renderTable(el,rows){
  if(!rows.length){ $(el).innerHTML='<div class="empty">None.</div>'; return; }
  let h='<table><thead><tr>'+
    '<th class="num" title="Best payoff in this unit">Ratio</th>'+
    '<th class="num" title="Signal strength">Value</th>'+
    '<th title="When the pattern started">Pattern start</th>'+
    '<th title="When the signal fired — the entry candle">Fired</th>'+
    '<th class="num" title="Instruments merged here">In</th>'+
    '<th title="Best strike, and the ones that fired">Instruments</th>'+
    '<th class="num" title="Hours to expiry at entry">TTE h</th>'+
    '<th class="num" title="Distance from spot">OTM%</th>'+
    '<th>Expiry</th><th class="num">Dur</th><th>T</th></tr></thead><tbody>';
  for(const r of rows){
    h+='<tr>'+
      '<td class="num"><span class="chip" style="background:'+RCOL[band(r.univRatio)]+'">'+
        (r.univRatio||0).toFixed(2)+'x</span></td>'+
      '<td class="num">'+(r.signalValue==null?'—':Number(r.signalValue).toFixed(1))+'</td>'+
      '<td class="ts">'+esc(shortTs(r.startTs))+'</td>'+
      '<td class="ts">'+esc(shortTs(r.entryTs))+'</td>'+
      '<td class="num">'+r.count+'</td>'+
      '<td>'+(r.url?'<a href="'+esc(fixChartUrl(r.url))+'" target="_blank" rel="noopener">'+
        esc(r.univSymbol||r.symbols[0])+' ↗</a>':esc(r.symbols[0]||'—'))+
        (r.count>1?' <span class="ts">+'+(r.count-1)+'</span>':'')+'</td>'+
      '<td class="num">'+(r.tteHours==null?'—':r.tteHours.toFixed(0))+'</td>'+
      '<td class="num">'+(r.distancePct==null?'—':r.distancePct.toFixed(1))+'</td>'+
      '<td class="ts">'+esc(r.expiry)+'</td>'+
      '<td class="num">'+r.duration+'m</td>'+
      '<td>'+esc(r.type)+'</td></tr>';
  }
  $(el).innerHTML=h+'</tbody></table>';
}

async function runQuery(){
  $('qerr').className='err'; $('derr').className='err';
  $('status').textContent='running…';

  const body={signal:$('signal').value,spot:$('spot').value,
    filter:$('filter').value,success:$('success').value,derived:$('derived').value,
    merge:$('merge').value==='1',limit:parseInt($('limit').value)||200};

  const res=await (await fetch('/api/query',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  $('status').textContent='';

  if(res.error){
    const isDerived=/Definition needs|already exists|not a valid field name|has no expression|is a function name/.test(res.error);
    (isDerived?$('derr'):$('qerr')).className='err on';
    (isDerived?$('derr'):$('qerr')).textContent=res.error;
    $('res').innerHTML=''; $('folds').innerHTML=''; $('warn').className='warn';
    return;
  }

  renderMetrics(res);
  const unit=res.merged?'events':'signals';
  $('nS').textContent=res.successCount.toLocaleString()+' successful '+unit+', best first';
  $('nF').textContent=res.failureCount.toLocaleString()+' failed '+unit+', worst first';
  renderTable('tS',res.success); renderTable('tF',res.failure);
}

function resetFilter(){
  $('filter').value=DEFAULT_FILTERS[$('signal').value]||'signalValue >= 0';
}

async function loadSignal(){
  const meta=await (await fetch('/api/meta/'+encodeURIComponent($('signal').value))).json();
  $('spot').innerHTML=(meta.spots||[]).map(s=>'<option>'+esc(s)+'</option>').join('');
  resetFilter();
  if(meta.spots&&meta.spots.length) await runQuery();
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
  $('spot').addEventListener('change',runQuery);
  $('merge').addEventListener('change',runQuery);
  $('run').addEventListener('click',runQuery);
  $('resetFilter').addEventListener('click',resetFilter);
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
                    const { rows, folds } = loadRows(q.signal, q.spot);
                    return json(res, runQuery(rows, folds,
                        q.filter || '', q.success || 'univRatio >= 10',
                        q.limit || 200, q.derived || '', q.merge !== false));
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
}).listen(PORT, '0.0.0.0', () => {
    console.log(netinfo.banner('Query — filter, success, holdout', PORT));
});
