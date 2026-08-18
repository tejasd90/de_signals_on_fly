// quality.js
// ─────────────────────────────────────────────────────────────────────────────
// Read stored signal files and compute quality metrics per duration.
// Run standalone: node quality.js [--spot BTC] [--dur 240] [--signal red_squeeze]
//
// Payoff is measured on universeMaxRatio by default — the best multiple reached
// by ANY same-type strike at the signal instant, not just the strike that
// happened to fire. Restricting to the firing instrument understates what the
// signal was worth, because the big multiple usually lands elsewhere in the
// chain. Pass --source fired for the stricter reading.
//
// Output per spot per duration:
//   total ranges, activated%, slHit%, and one column per MULTIBAGGER_THRESHOLD
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs     = require('fs');
const path   = require('path');
const cfg    = require('./config');
const logger = require('./logger');
const instr  = require('./instruments');
const writer = require('./writer');
const api    = require('./api');
const expiryMod = require('./expiry');
const spotStore = require('./spot_store');

// ─── CLI args ─────────────────────────────────────────────────────────────────

const args      = process.argv.slice(2);
const filterSpot   = args.includes('--spot')   ? args[args.indexOf('--spot')   + 1] : null;
const filterDur    = args.includes('--dur')    ? parseInt(args[args.indexOf('--dur')    + 1]) : null;
const filterSignal = args.includes('--signal') ? args[args.indexOf('--signal') + 1] : 'red_squeeze';

// 'universe' (index 7, universeMaxRatio) or 'fired' (index 4, maxSignalRatio)
const RATIO_SOURCE = args.includes('--source')
    ? args[args.indexOf('--source') + 1]
    : cfg.DEFAULT_RATIO_SOURCE;

if (!['universe', 'fired'].includes(RATIO_SOURCE)) {
    console.error(`--source must be 'universe' or 'fired', got '${RATIO_SOURCE}'`);
    process.exit(1);
}

// Which dimensions to break results down by. Comma-separated; two dimensions
// produce a cross-tab, which is what the duration x tte x moneyness hypothesis
// actually needs — aggregating one at a time averages the pockets away.
const BY = (args.includes('--by')
    ? args[args.indexOf('--by') + 1]
    : 'duration'
).split(',').map(x => x.trim()).filter(Boolean);

// Calls and puts are separate populations: a call pocket and a put pocket need
// not coincide, and pooling them averages one into the other. The original
// report always split them; this keeps that available both as a filter and as a
// grouping dimension.
const TYPE_FILTER = args.includes('--type') ? args[args.indexOf('--type') + 1] : 'both';
if (!['C', 'P', 'both'].includes(TYPE_FILTER)) {
    console.error(`--type must be C, P or both (got '${TYPE_FILTER}')`);
    process.exit(1);
}

const VALID_DIMS = ['duration', 'tte', 'moneyness', 'type'];
for (const d of BY) {
    if (!VALID_DIMS.includes(d)) {
        console.error(`--by must be one or two of: ${VALID_DIMS.join(', ')} (got '${d}')`);
        process.exit(1);
    }
}
if (BY.length > 3) {
    console.error('--by takes at most three dimensions.');
    process.exit(1);
}

/** Index of the first bucket whose max the value falls under. */
function bucketOf(value, buckets) {
    for (let i = 0; i < buckets.length; i++) if (value < buckets[i].max) return i;
    return buckets.length - 1;
}

/**
 * Hours remaining when the signal fired, from the range start and the per-spot
 * settlement time.
 */
function tteHoursOf(range, spot, expiry) {
    const startMs = new Date(range[0]).getTime();
    if (Number.isNaN(startMs)) return null;
    return (expiryMod.expiryMillis(spot, expiry) - startMs) / 3600000;
}

/**
 * Distance from spot, as a percentage, for the strike that produced the payoff.
 *
 * A merged range spans several strikes, so "the moneyness of the range" is
 * ambiguous. It is resolved by taking the strike that ACHIEVED the ratio being
 * measured — universeMaxSymbol (index 8) — which pairs the moneyness with the
 * outcome rather than averaging it across strikes that did not pay.
 *
 * Falls back to the mean across firing instruments when index 8 is absent, which
 * is the case for signal files written before universeMaxRatio existed.
 *
 * Needs stored spot covering the signal timestamp; returns null otherwise, and
 * those ranges are counted separately rather than silently dropped.
 */
function moneynessOf(range, spot, expiry, duration) {
    const spotIdx = spotIndex(spot, duration);
    if (!spotIdx || spotIdx.size === 0) return null;

    const sp = spotIdx.get(range[0]);
    if (!sp || !(sp.close > 0)) return null;

    const symbols = range[8] ? [range[8]] : (range[6] || []);
    if (!symbols.length) return null;

    let sum = 0, n = 0;
    for (const sym of symbols) {
        const p = instr.parseSymbol(sym);
        if (!p.type || !isFinite(p.strike)) continue;
        // Signed so that positive always means OUT of the money, for calls and
        // puts alike; negative is in the money.
        sum += (p.type === 'C' ? 1 : -1) * (p.strike - sp.close) / sp.close * 100;
        n++;
    }
    return n ? sum / n : null;
}

// Spot indexes are rebuilt per (spot, duration) and reused across every range,
// since a full history has tens of thousands of them.
const _spotCache = new Map();
function spotIndex(spot, duration) {
    const k = `${spot}|${duration}`;
    if (!_spotCache.has(k)) _spotCache.set(k, spotStore.spotIndexFor(spot, duration));
    return _spotCache.get(k);
}

/**
 * The payoff for one merged range under the selected source.
 * Index 7 is absent in signal files written before universeMaxRatio existed;
 * those read as 0 rather than throwing, and re-running
 * `backfill.js --signals-only --force-signals` fills them in.
 */
function payoffOf(range) {
    return Number(RATIO_SOURCE === 'universe' ? range[7] : range[4]) || 0;
}

// ─── Quality computation ──────────────────────────────────────────────────────

function computeQuality(ranges) {
    const total = ranges.length;
    if (total === 0) return null;

    const activated = ranges.filter(r => r[5] === 'activated').length;
    const slHit     = ranges.filter(r => r[5] === 'slHit').length;
    const pending   = ranges.filter(r => r[5] === 'pending').length;

    const multibaggers = {};
    const pct          = {};
    for (const t of cfg.MULTIBAGGER_THRESHOLDS) {
        const count           = ranges.filter(r => payoffOf(r) >= t).length;
        multibaggers[`${t}x`] = count;
        pct[`${t}x`]          = `${((count / total) * 100).toFixed(1)}%`;
    }

    return { total, activated, slHit, pending, multibaggers, pct };
}

/** Full configured axis for a dimension, so empty bands stay visible. */
function axisKeysFor(dim, seenIter) {
    const seen = [...seenIter];
    let keys;
    if (dim === 'moneyness')   keys = cfg.MONEYNESS_BUCKETS.map((_, i) => i);
    else if (dim === 'tte')    keys = cfg.TTE_BUCKETS.map((_, i) => i);
    else keys = seen.slice().sort((x, y) => (x === null) - (y === null) || (x > y ? 1 : -1));
    for (const k of seen) if (!keys.includes(k)) keys.push(k);
    return keys;
}

function groupCells(rows, dA, dB) {
    const cells = new Map();
    for (const r of rows) {
        const k = `${dA.key(r)}|${dB.key(r)}`;
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push(r);
    }
    return cells;
}

/**
 * Cross-tab of two dimensions, cells showing the headline-threshold hit rate.
 *
 * @param {number|null} forcedBest  when set, the star marks this value rather
 *        than the best in this table — used by the three-way view so the star
 *        identifies one global pocket instead of one per panel.
 */
function printCrossTab(rows, dA, dB, dimA, dimB, forcedBest, indent = '') {
    const T = cfg.DEFAULT_HEADLINE_THRESHOLD;
    const cells = groupCells(rows, dA, dB);

    const A = axisKeysFor(dimA, new Set(rows.map(r => dA.key(r))));
    const B = axisKeysFor(dimB, new Set(rows.map(r => dB.key(r))));

    if (!forcedBest) {
        console.log(`${indent}  cells show ${T}x hit rate and sample size. * = best in table.`);
        console.log('');
    }

    const w    = Math.max(...A.map(a => dA.fmt(a).length), dA.label.length) + 1;
    const colW = Math.max(...B.map(b => dB.fmt(b).length), 13);

    let hdr = `${indent}  ` + `${dA.label}\\${dB.label}`.padEnd(w);
    for (const b of B) hdr += dB.fmt(b).padStart(colW);
    console.log(hdr);

    let best = forcedBest;
    if (best === null || best === undefined) {
        best = 0;
        for (const [, cr] of cells) {
            const st = statsOf(cr);
            if (st.total >= cfg.QUALITY_MIN_CELL_SAMPLE && st.pct[T].pct > best) best = st.pct[T].pct;
        }
    }

    for (const a of A) {
        let line = `${indent}  ` + dA.fmt(a).padEnd(w);
        for (const b of B) {
            const st = statsOf(cells.get(`${a}|${b}`) || []);
            if (!st.total) { line += '·'.padStart(colW); continue; }
            const p = st.pct[T].pct;
            // Below the sample floor a high rate is noise, so it is
            // parenthesised and cannot take the star.
            const thin = st.total < cfg.QUALITY_MIN_CELL_SAMPLE;
            const mark = (!thin && best > 0 && Math.abs(p - best) < 1e-9) ? '*' : '';
            line += (thin ? `(${p.toFixed(0)}% ${st.total})`
                          : `${p.toFixed(0)}% ${st.total}${mark}`).padStart(colW);
        }
        console.log(line);
    }
    if (!forcedBest) {
        console.log('');
        console.log(`${indent}  ( ) = fewer than ${cfg.QUALITY_MIN_CELL_SAMPLE} samples, treat as noise`);
    }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

// ─── Grouping ─────────────────────────────────────────────────────────────────

/**
 * Collect every range for a spot, tagged with each dimension's bucket.
 * Ranges whose moneyness cannot be resolved are counted but excluded from any
 * moneyness breakdown, rather than being dumped into a bucket they do not belong in.
 */
function collectRanges(signalId, spot, durations) {
    const rows = [];
    let noMoneyness = 0;

    for (const dur of durations) {
        const durDir = path.join(cfg.SIGNALS_BASE_DIR, signalId, spot, String(dur));
        if (!fs.existsSync(durDir)) continue;

        const expiries = fs.readdirSync(durDir)
            .filter(f => !f.startsWith('.') && f.endsWith('.json'))
            .map(f => f.replace('.json', ''))
            .filter(e => expiryMod.isExpired(spot, e));

        for (const expiry of expiries) {
            const data = writer.readSignals(signalId, spot, dur, expiry);

            for (const type of ['C', 'P']) {
                if (TYPE_FILTER !== 'both' && type !== TYPE_FILTER) continue;

                for (const r of (data[type] || [])) {
                    const tte = tteHoursOf(r, spot, expiry);
                    const mny = BY.includes('moneyness')
                        ? moneynessOf(r, spot, expiry, dur) : null;

                    // Only a moneyness breakdown needs it, so only that path drops rows.
                    if (BY.includes('moneyness') && mny === null) { noMoneyness++; continue; }

                    rows.push({
                        type, duration: dur, expiry,
                        payoff: payoffOf(r),
                        state:  r[5],
                        tteBucket: tte === null ? null : bucketOf(tte, cfg.TTE_BUCKETS),
                        mnyBucket: mny === null ? null : bucketOf(mny, cfg.MONEYNESS_BUCKETS),
                    });
                }
            }
        }
    }
    return { rows, noMoneyness };
}

const DIM = {
    duration:  { label: 'duration',  key: r => r.duration,  fmt: v => v + 'm' },
    type:      { label: 'type',      key: r => r.type,
                 fmt: v => v === 'C' ? 'calls' : v === 'P' ? 'puts' : String(v) },
    tte:       { label: 'tte',       key: r => r.tteBucket,
                 fmt: v => v === null ? '(unknown)' : cfg.TTE_BUCKETS[v].label },
    moneyness: { label: 'moneyness', key: r => r.mnyBucket,
                 fmt: v => v === null ? '(unknown)' : cfg.MONEYNESS_BUCKETS[v].label },
};

function statsOf(rows) {
    const total = rows.length;
    const out = { total, activated: 0, slHit: 0, pct: {} };
    if (!total) return out;

    out.activated = rows.filter(r => r.state === 'activated').length;
    out.slHit     = rows.filter(r => r.state === 'slHit').length;

    for (const t of cfg.MULTIBAGGER_THRESHOLDS) {
        const n = rows.filter(r => r.payoff >= t).length;
        out.pct[t] = { n, pct: (n / total) * 100 };
    }
    return out;
}

/** Highlight the best cell per threshold, so the pocket is visible at a glance. */
function fmtRow(labelWidth, label, st, bestPct) {
    if (!st.total) return '  ' + label.padEnd(labelWidth) + '  (none)';
    let line = '  ' + label.padEnd(labelWidth) +
        `  n=${String(st.total).padStart(6)}` +
        `  act=${String(st.activated).padStart(5)}`;
    for (const t of cfg.MULTIBAGGER_THRESHOLDS) {
        const p = st.pct[t].pct;
        const mark = bestPct && bestPct[t] > 0 && Math.abs(p - bestPct[t]) < 1e-9 ? '*' : ' ';
        line += `  ${t}x=${p.toFixed(1).padStart(5)}%${mark}`;
    }
    return line;
}

/** Full configured axis for a dimension, so empty bands stay visible. */
function axisKeysFor(dim, seenIter) {
    const seen = [...seenIter];
    let keys;
    if (dim === 'moneyness')   keys = cfg.MONEYNESS_BUCKETS.map((_, i) => i);
    else if (dim === 'tte')    keys = cfg.TTE_BUCKETS.map((_, i) => i);
    else keys = seen.slice().sort((x, y) => (x === null) - (y === null) || (x > y ? 1 : -1));
    for (const k of seen) if (!keys.includes(k)) keys.push(k);
    return keys;
}

function groupCells(rows, dA, dB) {
    const cells = new Map();
    for (const r of rows) {
        const k = `${dA.key(r)}|${dB.key(r)}`;
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push(r);
    }
    return cells;
}

/**
 * Cross-tab of two dimensions, cells showing the headline-threshold hit rate.
 *
 * @param {number|null} forcedBest  when set, the star marks this value rather
 *        than the best in this table — used by the three-way view so the star
 *        identifies one global pocket instead of one per panel.
 */
function printCrossTab(rows, dA, dB, dimA, dimB, forcedBest, indent = '') {
    const T = cfg.DEFAULT_HEADLINE_THRESHOLD;
    const cells = groupCells(rows, dA, dB);

    const A = axisKeysFor(dimA, new Set(rows.map(r => dA.key(r))));
    const B = axisKeysFor(dimB, new Set(rows.map(r => dB.key(r))));

    if (!forcedBest) {
        console.log(`${indent}  cells show ${T}x hit rate and sample size. * = best in table.`);
        console.log('');
    }

    const w    = Math.max(...A.map(a => dA.fmt(a).length), dA.label.length) + 1;
    const colW = Math.max(...B.map(b => dB.fmt(b).length), 13);

    let hdr = `${indent}  ` + `${dA.label}\\${dB.label}`.padEnd(w);
    for (const b of B) hdr += dB.fmt(b).padStart(colW);
    console.log(hdr);

    let best = forcedBest;
    if (best === null || best === undefined) {
        best = 0;
        for (const [, cr] of cells) {
            const st = statsOf(cr);
            if (st.total >= cfg.QUALITY_MIN_CELL_SAMPLE && st.pct[T].pct > best) best = st.pct[T].pct;
        }
    }

    for (const a of A) {
        let line = `${indent}  ` + dA.fmt(a).padEnd(w);
        for (const b of B) {
            const st = statsOf(cells.get(`${a}|${b}`) || []);
            if (!st.total) { line += '·'.padStart(colW); continue; }
            const p = st.pct[T].pct;
            // Below the sample floor a high rate is noise, so it is
            // parenthesised and cannot take the star.
            const thin = st.total < cfg.QUALITY_MIN_CELL_SAMPLE;
            const mark = (!thin && best > 0 && Math.abs(p - best) < 1e-9) ? '*' : '';
            line += (thin ? `(${p.toFixed(0)}% ${st.total})`
                          : `${p.toFixed(0)}% ${st.total}${mark}`).padStart(colW);
        }
        console.log(line);
    }
    if (!forcedBest) {
        console.log('');
        console.log(`${indent}  ( ) = fewer than ${cfg.QUALITY_MIN_CELL_SAMPLE} samples, treat as noise`);
    }
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function run() {
    const signalId  = filterSignal;
    const signalDir = path.join(cfg.SIGNALS_BASE_DIR, signalId);

    if (!fs.existsSync(signalDir)) {
        console.log(`No signal data found at ${signalDir}`);
        return;
    }

    console.log(`\n${'='.repeat(78)}`);
    console.log(`Signal quality report: ${signalId}`);
    console.log(`Payoff measured on: ${RATIO_SOURCE === 'universe'
        ? 'universeMaxRatio (best same-type strike)'
        : 'maxSignalRatio (firing instrument only)'}`);
    console.log(`Broken down by: ${BY.join(' x ')}`);
    console.log(`Option type   : ${TYPE_FILTER === 'both'
        ? 'calls and puts POOLED — add --type C / --type P, or --by type, to split'
        : (TYPE_FILTER === 'C' ? 'calls only' : 'puts only')}`);
    console.log(`${'='.repeat(78)}`);

    const spots = filterSpot
        ? [filterSpot]
        : fs.readdirSync(signalDir).filter(d => !d.startsWith('.'));

    for (const spot of spots) {
        const spotDir = path.join(signalDir, spot);
        if (!fs.existsSync(spotDir)) continue;

        let durations = fs.readdirSync(spotDir)
            .filter(d => !d.startsWith('.') && !isNaN(d)).map(Number)
            .sort((a, b) => a - b);
        if (filterDur) durations = durations.filter(d => d === filterDur);
        if (!durations.length) continue;

        const { rows, noMoneyness } = collectRanges(signalId, spot, durations);
        if (!rows.length) {
            console.log(`\nSpot: ${spot}  — no settled-expiry ranges`);
            if (noMoneyness) console.log(`  (${noMoneyness} excluded: spot unavailable at signal time)`);
            continue;
        }

        const totalSeen = rows.length + noMoneyness;
        console.log(`\nSpot: ${spot}   ${rows.length} of ${totalSeen} ranges usable`);
        if (noMoneyness) {
            const pct = (noMoneyness / totalSeen * 100).toFixed(0);
            console.log(`  ${noMoneyness} ranges (${pct}%) EXCLUDED — no stored spot at the signal`);
            console.log(`  timestamp, so moneyness could not be determined. The table below covers`);
            console.log(`  only the remaining ${rows.length}, which may not be representative.`);
            console.log(`  Fix: node backfill.js --spot-candles --from 2024-01-01`);
        }
        console.log('-'.repeat(78));

        if (BY.length === 1) {
            const d = DIM[BY[0]];
            const groups = new Map();
            for (const r of rows) {
                const k = d.key(r);
                if (!groups.has(k)) groups.set(k, []);
                groups.get(k).push(r);
            }

            // Show every configured bucket, not only the occupied ones. An
            // absent bucket previously just vanished, which made the output look
            // like a different bucket set had been configured — and hid the fact
            // that a whole region of the distribution had no data at all.
            const keys = axisKeysFor(BY[0], groups.keys());

            // Best percentage per threshold, so the winning bucket is starred.
            const best = {};
            for (const t of cfg.MULTIBAGGER_THRESHOLDS) {
                best[t] = Math.max(...keys.map(k => {
                    const st = statsOf(groups.get(k) || []);
                    // Thin buckets are excluded from the star for the same reason
                    // thin cross-tab cells are parenthesised: a high rate on a
                    // handful of samples is noise, not the best bucket.
                    return st.total >= cfg.QUALITY_MIN_CELL_SAMPLE ? st.pct[t].pct : 0;
                }));
            }

            const w = Math.max(...keys.map(k => d.fmt(k).length), d.label.length);
            console.log('  ' + d.label.toUpperCase().padEnd(w) +
                '  ' + 'n'.padStart(8) + '  ' + 'act'.padStart(8) +
                cfg.MULTIBAGGER_THRESHOLDS.map(t => `  ${t}x`.padStart(10)).join(''));

            for (const k of keys) {
                console.log(fmtRow(w, d.fmt(k), statsOf(groups.get(k) || []), best));
            }

        } else if (BY.length === 2) {
            printCrossTab(rows, DIM[BY[0]], DIM[BY[1]], BY[0], BY[1], null);

        } else {
            // Three dimensions: one cross-tab per value of the first, since a
            // 3D table cannot be drawn in text. The hypothesis being tested is
            // inherently three-way — a duration works only in a certain window
            // AND at a certain distance — and collapsing any one of them averages
            // the pocket away.
            const dOuter = DIM[BY[0]], dA = DIM[BY[1]], dB = DIM[BY[2]];
            const T = cfg.DEFAULT_HEADLINE_THRESHOLD;

            const panels = new Map();
            for (const r of rows) {
                const k = dOuter.key(r);
                if (!panels.has(k)) panels.set(k, []);
                panels.get(k).push(r);
            }

            const outerKeys = axisKeysFor(BY[0], panels.keys());

            // One best figure across EVERY panel, so the star marks the single
            // strongest pocket overall rather than the best of each slice.
            let globalBest = 0;
            for (const [, rs] of panels) {
                const cells = groupCells(rs, dA, dB);
                for (const [, cr] of cells) {
                    const st = statsOf(cr);
                    if (st.total >= cfg.QUALITY_MIN_CELL_SAMPLE && st.pct[T].pct > globalBest) {
                        globalBest = st.pct[T].pct;
                    }
                }
            }

            for (const ok of outerKeys) {
                const rs = panels.get(ok) || [];
                console.log('');
                console.log(`  ${dOuter.label} = ${dOuter.fmt(ok)}` +
                            `   (${rs.length} ranges)`);
                if (!rs.length) { console.log('    (none)'); continue; }
                printCrossTab(rs, dA, dB, BY[1], BY[2], globalBest, '  ');
            }
        }
    }

    console.log(`\n${'='.repeat(78)}\n`);
    logger.log('quality',
        `report signal=${signalId} by=${BY.join(',')} source=${RATIO_SOURCE} type=${TYPE_FILTER}`);
}

if (require.main === module) {
    run();
}

module.exports = { run, computeQuality };
