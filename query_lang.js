// query_lang.js
// ─────────────────────────────────────────────────────────────────────────────
// Small expression language for filtering signals.
//
//   signalValue > 500 && count >= 3
//   ratio1 + ratio2 > 400 && duration in [60, 240]
//   (tteHours < 48 && distancePct between 1.5 and 3.5) || seqLength >= 5
//
// A hand-written tokeniser and recursive-descent parser rather than eval() or
// new Function(). Those would be far shorter, but they execute arbitrary code:
// harmless on localhost, a remote-execution hole the moment this binds to
// anything else. A parser also lets an unknown field be REJECTED at parse time
// instead of silently evaluating to undefined and quietly matching nothing.
//
// EXTENSIBILITY
// Fields live in a registry keyed by name, carrying type, description and an
// `outcome` flag. Adding a queryable field is one entry there — the tokeniser,
// parser and UI all read from it.
//
// LOOKAHEAD GUARD
// Fields marked `outcome: true` describe what happened AFTER entry. Referencing
// one in a FILTER means selecting signals using information unavailable when the
// signal fired, which produces spectacular and entirely fake results. The parser
// therefore takes an `allowOutcome` flag and refuses those fields in filter
// context, naming the field rather than failing obscurely.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

// ─── Field registry ───────────────────────────────────────────────────────────

/**
 * @typedef {Object} FieldDef
 * @property {'number'|'string'|'boolean'} type
 * @property {boolean} outcome  known only after entry; banned in filters
 * @property {string}  desc
 */

/** @type {Object<string, FieldDef>} */
const FIELDS = {
    // ── Identity ──
    signal:      { type: 'string',  outcome: false, desc: 'Signal id, e.g. red_squeeze' },
    spot:        { type: 'string',  outcome: false, desc: 'Underlying, e.g. BTC' },
    expiry:      { type: 'string',  outcome: false, desc: 'Expiry date, YYYY-MM-DD' },
    symbol:      { type: 'string',  outcome: false, desc: 'Instrument symbol' },
    type:        { type: 'string',  outcome: false, desc: "'C' or 'P'" },
    strike:      { type: 'number',  outcome: false, desc: 'Strike price' },
    duration:    { type: 'number',  outcome: false, desc: 'Candle duration in minutes' },

    // ── Time of day at entry ──
    //
    // Derived at LOAD time from entryTs, which stage 1 already stores, so these
    // needed no re-extraction. All in IST, matching the +0530 the timestamps
    // carry — crypto trades round the clock, so hour-of-day is a real variable
    // rather than a session artefact.
    entryHour:   { type: 'number',  outcome: false, desc: 'Hour of entry, 0-23 IST' },
    entryMinute: { type: 'number',  outcome: false, desc: 'Minute of entry, 0-59' },
    entryHourF:  { type: 'number',  outcome: false, desc: 'Fractional hour, e.g. 16.5 = 16:30' },
    entryDow:    { type: 'number',  outcome: false, desc: 'Day of week at entry, 1=Mon .. 7=Sun' },
    entryDate:   { type: 'string',  outcome: false, desc: 'Entry date, YYYY-MM-DD' },
    entryTs:     { type: 'string',  outcome: false, desc: 'Full entry timestamp' },

    // ── Context at entry ──
    tteHours:    { type: 'number',  outcome: false, desc: 'Hours to expiry when the signal fired' },
    spotPrice:   { type: 'number',  outcome: false, desc: 'Spot at pattern start' },
    distancePct: { type: 'number',  outcome: false, desc: 'Distance from spot; positive = OTM' },
    otm:         { type: 'boolean', outcome: false, desc: 'True when out of the money' },
    entryPrice:  { type: 'number',  outcome: false, desc: 'Option close at entry' },

    // ── Pattern shape ──
    seqLength:   { type: 'number',  outcome: false, desc: 'Candles in the pattern sequence' },
    patternHigh: { type: 'number',  outcome: false, desc: 'Highest high across the pattern' },
    patternLow:  { type: 'number',  outcome: false, desc: 'Lowest low across the pattern' },
    triggerPrice:{ type: 'number',  outcome: false, desc: 'Activation level — the signal candle high' },

    // ── red_squeeze / otm_red_squeeze ──
    ratio1:      { type: 'number',  outcome: false, desc: 'firstRedBody / lastRedBody' },
    ratio2:      { type: 'number',  outcome: false, desc: 'firstRedBody / greenBody' },
    firstBody:   { type: 'number',  outcome: false, desc: 'Body of the first pattern candle' },
    lastBody:    { type: 'number',  outcome: false, desc: 'Body of the last pattern candle' },
    triggerBody: { type: 'number',  outcome: false, desc: 'Body of the trigger candle' },

    // ── otm_* cheapness ──
    avgPrice:    { type: 'number',  outcome: false, desc: 'Mean of trigger close and pattern lows' },
    cheapness:   { type: 'number',  outcome: false, desc: 'spot / avgPrice' },

    // ── otm_wall ──
    dist:        { type: 'number',  outcome: false, desc: 'Body distance from the previous 5 candles' },
    logValue:    { type: 'number',  outcome: false, desc: 'log10(open x close x dist^2)' },
    logJump:     { type: 'number',  outcome: false, desc: 'logValue minus a recent candle value' },

    // ── green_stairs ──
    equalSteps:  { type: 'number',  outcome: false, desc: 'Times a body merely equalled its predecessor' },

    // ── Generic strength ──
    signalValue: { type: 'number',  outcome: false, desc: 'Signal strength; meaning differs per signal' },

    // ── OUTCOMES — banned in filters ──
    ratio:       { type: 'number',  outcome: true,  desc: 'Peak high after entry / entry close' },
    univRatio:   { type: 'number',  outcome: true,  desc: 'Best ratio on any same-type strike' },
    state:       { type: 'string',  outcome: true,  desc: "'activated' | 'slHit' | 'pending'" },
    brokeOut:    { type: 'boolean', outcome: true,  desc: 'Closed above the pattern high afterwards' },
    holdCandles: { type: 'number',  outcome: true,  desc: 'Candles from entry to peak' },
    peakAfter:   { type: 'number',  outcome: true,  desc: 'Highest price after the signal candle' },
};

/** Register a field at runtime. Returns false if the name is taken. */
function registerField(name, def) {
    if (FIELDS[name]) return false;
    FIELDS[name] = { type: 'number', outcome: false, desc: '', ...def };
    return true;
}

// ─── Function registry ────────────────────────────────────────────────────────
//
// Extensible the same way FIELDS is: one entry adds a function everywhere.
// These close most of the gap to full JS for filter expressions — log10 in
// particular, since otm_wall is built on it and comparing raw log values is
// otherwise impossible to express.
//
// Every function is pure and numeric. Nothing here can touch the filesystem,
// the network or the process, which is the whole reason this exists instead of
// eval(): a page you visit while the server is running can POST to localhost,
// and with eval that is arbitrary code execution on your machine.

const FUNCS = {
    log10: { arity: 1, fn: a => (a > 0 ? Math.log10(a) : 0),  desc: 'base-10 log; 0 for non-positive input' },
    log:   { arity: 1, fn: a => (a > 0 ? Math.log(a) : 0),    desc: 'natural log; 0 for non-positive input' },
    exp:   { arity: 1, fn: a => Math.exp(a),                  desc: 'e^a' },
    sqrt:  { arity: 1, fn: a => (a >= 0 ? Math.sqrt(a) : 0),  desc: 'square root; 0 for negative input' },
    abs:   { arity: 1, fn: a => Math.abs(a),                  desc: 'absolute value' },
    round: { arity: 1, fn: a => Math.round(a),                desc: 'nearest integer' },
    floor: { arity: 1, fn: a => Math.floor(a),                desc: 'round down' },
    ceil:  { arity: 1, fn: a => Math.ceil(a),                 desc: 'round up' },
    sign:  { arity: 1, fn: a => Math.sign(a),                 desc: '-1, 0 or 1' },
    pow:   { arity: 2, fn: (a, b) => Math.pow(a, b),          desc: 'a to the power b' },
    min:   { arity: -1, fn: (...a) => Math.min(...a),         desc: 'smallest of its arguments' },
    max:   { arity: -1, fn: (...a) => Math.max(...a),         desc: 'largest of its arguments' },
};

/** Register a function at runtime. Returns false if the name is taken. */
function registerFunc(name, def) {
    if (FUNCS[name] || FIELDS[name]) return false;
    FUNCS[name] = { arity: def.arity ?? 1, fn: def.fn, desc: def.desc || '' };
    return true;
}

// ─── Tokeniser ────────────────────────────────────────────────────────────────

const PUNCT = ['>=', '<=', '==', '!=', '&&', '||', '>', '<', '=', '!', '(', ')', '[', ']', ',', '+', '-', '*', '/'];
const WORD_OPS = { and: '&&', or: '||', not: '!' };

function tokenise(src) {
    const out = [];
    let i = 0;

    while (i < src.length) {
        const ch = src[i];

        if (/\s/.test(ch)) { i++; continue; }

        // Number
        if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(src[i + 1] || ''))) {
            let j = i;
            while (j < src.length && /[0-9.]/.test(src[j])) j++;
            const text = src.slice(i, j);
            const v = Number(text);
            if (Number.isNaN(v)) throw new QueryError(`Bad number "${text}"`, i);
            out.push({ kind: 'num', value: v, pos: i });
            i = j; continue;
        }

        // String
        if (ch === '"' || ch === "'") {
            let j = i + 1;
            while (j < src.length && src[j] !== ch) j++;
            if (j >= src.length) throw new QueryError('Unterminated string', i);
            out.push({ kind: 'str', value: src.slice(i + 1, j), pos: i });
            i = j + 1; continue;
        }

        // Identifier or word operator
        if (/[A-Za-z_]/.test(ch)) {
            let j = i;
            while (j < src.length && /[A-Za-z0-9_]/.test(src[j])) j++;
            const word = src.slice(i, j);
            const lower = word.toLowerCase();

            if (WORD_OPS[lower])      out.push({ kind: 'punct', value: WORD_OPS[lower], pos: i });
            else if (lower === 'in')  out.push({ kind: 'punct', value: 'in', pos: i });
            else if (lower === 'between') out.push({ kind: 'punct', value: 'between', pos: i });
            else if (lower === 'true')  out.push({ kind: 'bool', value: true, pos: i });
            else if (lower === 'false') out.push({ kind: 'bool', value: false, pos: i });
            else out.push({ kind: 'ident', value: word, pos: i });
            i = j; continue;
        }

        // Punctuation, longest match first so '>=' is not read as '>' then '='
        const p = PUNCT.find(sym => src.startsWith(sym, i));
        if (p) { out.push({ kind: 'punct', value: p === '=' ? '==' : p, pos: i }); i += p.length; continue; }

        throw new QueryError(`Unexpected character "${ch}"`, i);
    }

    out.push({ kind: 'eof', value: null, pos: src.length });
    return out;
}

class QueryError extends Error {
    constructor(message, pos) { super(message); this.pos = pos; }
}

// ─── Parser ───────────────────────────────────────────────────────────────────

function parse(src, { allowOutcome = true } = {}) {
    const toks = tokenise(src);
    let p = 0;

    const peek = () => toks[p];
    const at   = v => toks[p].kind === 'punct' && toks[p].value === v;
    const eat  = v => { if (!at(v)) throw new QueryError(`Expected "${v}"`, peek().pos); return toks[p++]; };

    function primary() {
        const t = peek();

        if (t.kind === 'num' || t.kind === 'str' || t.kind === 'bool') { p++; return { n: 'lit', v: t.value }; }

        if (at('(')) { p++; const e = expr(); eat(')'); return e; }

        if (at('[')) {
            p++;
            const items = [];
            if (!at(']')) {
                items.push(expr());
                while (at(',')) { p++; items.push(expr()); }
            }
            eat(']');
            return { n: 'list', items };
        }

        if (at('!')) { p++; return { n: 'not', a: unary() }; }
        if (at('-')) { p++; return { n: 'neg', a: unary() }; }

        if (t.kind === 'ident') {
            p++;

            // Function call: identifier immediately followed by '('.
            if (at('(')) {
                const f = FUNCS[t.value];
                if (!f) {
                    throw new QueryError(
                        `Unknown function "${t.value}". Available: ${Object.keys(FUNCS).join(', ')}`,
                        t.pos);
                }
                p++;                                  // consume '('
                const argv = [];
                if (!at(')')) {
                    argv.push(expr());
                    while (at(',')) { p++; argv.push(expr()); }
                }
                eat(')');
                if (f.arity >= 0 && argv.length !== f.arity) {
                    throw new QueryError(
                        `"${t.value}" takes ${f.arity} argument${f.arity === 1 ? '' : 's'}, got ${argv.length}`,
                        t.pos);
                }
                if (f.arity < 0 && argv.length === 0) {
                    throw new QueryError(`"${t.value}" needs at least one argument`, t.pos);
                }
                return { n: 'call', name: t.value, argv };
            }

            const def = FIELDS[t.value];
            if (!def) {
                const near = Object.keys(FIELDS)
                    .filter(f => f.toLowerCase().startsWith(t.value.slice(0, 3).toLowerCase()))
                    .slice(0, 4);
                throw new QueryError(
                    `Unknown field "${t.value}"` + (near.length ? `. Did you mean: ${near.join(', ')}?` : ''),
                    t.pos);
            }
            if (def.outcome && !allowOutcome) {
                throw new QueryError(
                    `"${t.value}" is an OUTCOME field and cannot be used in a filter — ` +
                    `it is only known after entry, so filtering on it is lookahead. ` +
                    `Use it in the success expression instead.`, t.pos);
            }
            return { n: 'field', name: t.value };
        }

        throw new QueryError('Unexpected end of expression', t.pos);
    }

    function unary() {
        if (at('!')) { p++; return { n: 'not', a: unary() }; }
        if (at('-')) { p++; return { n: 'neg', a: unary() }; }
        return primary();
    }

    function mul() {
        let l = unary();
        while (at('*') || at('/')) { const op = toks[p++].value; l = { n: 'bin', op, l, r: unary() }; }
        return l;
    }

    function add() {
        let l = mul();
        while (at('+') || at('-')) { const op = toks[p++].value; l = { n: 'bin', op, l, r: mul() }; }
        return l;
    }

    function cmp() {
        let l = add();
        while (at('>') || at('<') || at('>=') || at('<=') || at('==') || at('!=') ||
               at('in') || at('between')) {
            const op = toks[p++].value;
            if (op === 'between') {
                const lo = add();
                // `between 2 and 5` — 'and' has already been tokenised as '&&'
                if (at('&&')) p++;
                const hi = add();
                l = { n: 'between', a: l, lo, hi };
            } else {
                l = { n: 'bin', op, l, r: add() };
            }
        }
        return l;
    }

    function and() {
        let l = cmp();
        while (at('&&')) { p++; l = { n: 'and', l, r: cmp() }; }
        return l;
    }

    function expr() {
        let l = and();
        while (at('||')) { p++; l = { n: 'or', l, r: and() }; }
        return l;
    }

    const ast = expr();
    if (peek().kind !== 'eof') throw new QueryError('Unexpected trailing input', peek().pos);
    return ast;
}

// ─── Evaluator ────────────────────────────────────────────────────────────────

function evalNode(node, row) {
    switch (node.n) {
        case 'lit':   return node.v;
        case 'list':  return node.items.map(x => evalNode(x, row));
        case 'field': {
            const v = row[node.name];
            return v === undefined ? null : v;
        }
        case 'call': {
            const f = FUNCS[node.name];
            return f.fn(...node.argv.map(a => num(evalNode(a, row))));
        }
        case 'not':   return !truthy(evalNode(node.a, row));
        case 'neg':   return -num(evalNode(node.a, row));
        case 'and':   return truthy(evalNode(node.l, row)) && truthy(evalNode(node.r, row));
        case 'or':    return truthy(evalNode(node.l, row)) || truthy(evalNode(node.r, row));
        case 'between': {
            const a = num(evalNode(node.a, row));
            return a >= num(evalNode(node.lo, row)) && a <= num(evalNode(node.hi, row));
        }
        case 'bin': {
            const L = evalNode(node.l, row);

            if (node.op === 'in') {
                const R = evalNode(node.r, row);
                return Array.isArray(R) ? R.some(x => looseEq(L, x)) : looseEq(L, R);
            }

            const R = evalNode(node.r, row);
            switch (node.op) {
                case '+': return num(L) + num(R);
                case '-': return num(L) - num(R);
                case '*': return num(L) * num(R);
                case '/': { const d = num(R); return d === 0 ? 0 : num(L) / d; }
                case '>':  return num(L) >  num(R);
                case '<':  return num(L) <  num(R);
                case '>=': return num(L) >= num(R);
                case '<=': return num(L) <= num(R);
                case '==': return looseEq(L, R);
                case '!=': return !looseEq(L, R);
            }
            throw new QueryError(`Unknown operator "${node.op}"`, 0);
        }
    }
    throw new QueryError(`Unknown node "${node.n}"`, 0);
}

// A missing numeric field evaluates to 0 rather than NaN: signals of different
// kinds share one table, so `ratio1` simply does not exist on a wall signal, and
// NaN would poison every comparison it touched.
function num(v)    { return typeof v === 'number' ? v : (v === true ? 1 : 0); }
function truthy(v) { return v === true || (typeof v === 'number' && v !== 0) || (typeof v === 'string' && v !== ''); }
function looseEq(a, b) {
    if (typeof a === 'number' || typeof b === 'number') return num(a) === num(b);
    return String(a) === String(b);
}

/** Compile once, run over many rows. */
function compile(src, opts = {}) {
    const ast = parse(src, opts);
    const fn = row => truthy(evalNode(ast, row));
    fn.ast = ast;
    fn.fields = collectFields(ast);
    return fn;
}

function collectFields(node, acc = new Set()) {
    if (!node || typeof node !== 'object') return acc;
    if (node.n === 'field') acc.add(node.name);
    for (const k of ['a', 'l', 'r', 'lo', 'hi']) if (node[k]) collectFields(node[k], acc);
    for (const x of (node.items || [])) collectFields(x, acc);
    for (const x of (node.argv  || [])) collectFields(x, acc);
    return acc;
}

// ─── Computed fields ──────────────────────────────────────────────────────────
//
// User-defined derived columns:
//
//     punch = ratio1 * ratio2 / avgPrice
//     logCheap = log10(cheapness)
//
// Each becomes queryable exactly like a stored field. This is what "experiment
// with fields as well as values" needs — inventing a metric is a derived column,
// not a language feature, so it needs no eval and no new syntax.
//
// Definitions are compiled once and evaluated onto each row before the filter
// and success expressions run, so a derived field may reference stored fields
// and any derived field defined ABOVE it.
//
// Derived fields inherit the outcome flag of everything they touch: a metric
// built on `ratio` is itself an outcome and is refused in filters, which stops
// lookahead sneaking in through a definition.

function parseDerived(text) {
    const defs = [];
    const lines = String(text || '').split(/[\n;]/).map(l => l.trim()).filter(Boolean);

    for (const line of lines) {
        const eq = line.indexOf('=');
        if (eq < 0) throw new QueryError(`Definition needs "name = expression": ${line}`, 0);

        const name = line.slice(0, eq).trim();
        const body = line.slice(eq + 1).trim();

        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
            throw new QueryError(`"${name}" is not a valid field name`, 0);
        }
        if (FIELDS[name]) throw new QueryError(`"${name}" already exists as a built-in field`, 0);
        if (FUNCS[name])  throw new QueryError(`"${name}" is a function name`, 0);
        if (!body)        throw new QueryError(`"${name}" has no expression`, 0);

        // Outcome-tainted if it references any outcome field, directly or via an
        // earlier derived field that was itself tainted.
        const ast = parse(body, { allowOutcome: true });
        const used = collectFields(ast);
        let outcome = false;
        for (const f of used) {
            if (FIELDS[f] && FIELDS[f].outcome) outcome = true;
            const prior = defs.find(d => d.name === f);
            if (prior && prior.outcome) outcome = true;
        }

        defs.push({ name, body, ast, outcome });
        // Registered so later definitions and the main expressions can see it.
        FIELDS[name] = { type: 'number', outcome, desc: `derived: ${body}`, derived: true };
    }
    return defs;
}

/** Remove previously registered derived fields, so each run starts clean. */
function clearDerived() {
    for (const [k, v] of Object.entries(FIELDS)) if (v.derived) delete FIELDS[k];
}

/** Evaluate derived fields onto a row, in definition order. */
function applyDerived(defs, row) {
    for (const d of defs) row[d.name] = evalNode(d.ast, row);
    return row;
}

module.exports = {
    FIELDS, FUNCS, registerField, registerFunc,
    tokenise, parse, compile, evalNode, collectFields,
    parseDerived, clearDerived, applyDerived,
    QueryError,
};
