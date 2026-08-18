# The query tool

```bash
node patterns.js --from 2025-01-01 --to 2025-12-31    # stage 1, no API calls
node serve_query.js                                    # :3700
```

Three stages: extract every structural match with no tuning filter, expose the
stored fields as a queryable registry, then filter with expressions.

---

## Why a parser rather than `eval`

`eval` or `new Function` would be far shorter. They also execute arbitrary code —
harmless on localhost until you consider that **any webpage you visit while the
server is running can POST to localhost**. A form POST with `text/plain` does not
even trigger a CORS preflight. With `eval` that is arbitrary code execution on
your machine.

A parser also lets an unknown field be **rejected at parse time** instead of
silently evaluating to `undefined` and quietly matching nothing.

The w3schools comparison does not hold: their JS runs in your browser's sandbox,
and their server languages run in disposable containers. Neither resembles `eval`
in a long-running Node process with your filesystem and API keys.

---

## Grammar

```
expr    := or
or      := and ( ('||' | 'or') and )*
and     := cmp ( ('&&' | 'and') cmp )*
cmp     := add ( ('>'|'<'|'>='|'<='|'=='|'!='|'in') add
                | 'between' add 'and' add )*
add     := mul ( ('+'|'-') mul )*
mul     := unary ( ('*'|'/') unary )*
unary   := ('!' | 'not' | '-') unary | primary
primary := NUMBER | STRING | BOOL
         | IDENT '(' args ')'          function call
         | IDENT                       field
         | '(' expr ')'
         | '[' list ']'
```

Examples:

```
signalValue > 500 && tteHours < 48
ratio1 + ratio2 > 400 && duration in [60, 240]
distancePct between 1.5 and 3.5 && seqLength >= 4
log10(cheapness) > 5 && abs(distancePct) < 4
(tteHours < 6 || duration == 60) && type == "C"
```

---

## Fields

Registry in `query_lang.js`. Adding one is a single entry carrying type,
description and an `outcome` flag — the tokeniser, parser and UI all read from it.

**Identity** — `signal` `spot` `expiry` `symbol` `type` `strike` `duration`

**Entry context** — `tteHours` `spotPrice` `distancePct` `otm` `entryPrice`

**Pattern shape** — `seqLength` `patternHigh` `patternLow`

**red_squeeze family** — `ratio1` `ratio2` `firstBody` `lastBody` `triggerBody`

**otm_\* cheapness** — `avgPrice` `cheapness`

**otm_wall** — `dist` `logValue` `logJump`

**green_stairs** — `equalSteps`

**Generic** — `signalValue`

**OUTCOMES, banned in filters** — `ratio` `univRatio` `state` `brokeOut` `holdCandles`

38 fields in total: 33 usable in filters, 5 outcome-only.

A missing numeric field evaluates to **0**, never NaN. Signals of different kinds
share one table, so `ratio1` simply does not exist on a wall signal, and NaN would
poison every comparison it touched.

---

## Functions

```
log10(a)  log(a)  exp(a)  sqrt(a)  abs(a)
round(a)  floor(a)  ceil(a)  sign(a)
pow(a,b)  min(...)  max(...)
```

`log10` and `log` return 0 for non-positive input; `sqrt` returns 0 for negative.
Division by zero yields 0. All pure and numeric — nothing here can reach the
filesystem, network or process.

Extensible the same way as fields: one entry in `FUNCS`.

---

## Computed fields

A shared box above both query slots:

```
punch = ratio1 * ratio2 / avgPrice
logPunch = log10(punch)
```

Each becomes queryable like a stored field, and may reference any field defined
**above** it. This is what "experiment with fields as well as values" needs —
inventing a metric is a derived column, not a language feature.

**Outcome taint propagates.** Define `sneaky = ratio * 2` and it is itself marked
an outcome, so using it in a filter is refused. Without that, lookahead could
enter through the back door of a definition.

---

## The lookahead guard

The **filter** box refuses outcome fields at parse time:

```
ratio > 5
→ "ratio" is an OUTCOME field and cannot be used in a filter — it is only
   known after entry, so filtering on it is lookahead. Use it in the success
   expression instead.
```

Choosing which signals to take based on what happened afterwards produces
spectacular and completely untradeable results. The **success** box allows them,
as it must.

Unknown fields get a suggestion: `ratio3` → *"Did you mean: ratio1, ratio2, ratio?"*

---

## The holdout

Not optional, and always displayed.

```
expiries sorted ascending
cut = expiries[floor(count × 0.7) − 1]
row._test = row.expiry > cut
```

Split by **expiry date**, never by row: rows from one expiry share the same
underlying move, so a row-level split would put the same event on both sides.

Every query shows `matched`, `all%`, `train%`, `test (holdout)%` and
`train − test`. Warnings fire when a side falls below 30 samples, or when the gap
exceeds 10 points.

**Verified:** a spurious pattern planted only in the training half showed
**94.7% train, 16.9% test, 77.8 point gap**. A real edge present in both halves
showed a small gap.

### Known weakness: no purge

Signals fire up to 40 days before their expiry, so a *test* signal can fire
before a *train* expiry has settled. Both then observe the same market window and
the holdout is contaminated — it reads better than it should.

The fix is to drop rows whose observation window straddles the cut:

```
IF patternStart <= cutDate < expiry: DROP the row
```

Costs perhaps 5–10% of rows for a holdout you can trust. Not yet implemented.

So: the current holdout catches blatant curve fits reliably, subtle ones less so.

---

## Two query slots

A and B are independent and run together. The real question is almost always
"is this clause better than that one", and answering it by editing one box and
remembering the previous number is where mistakes happen.

**Known wart:** the results tables below show Query A only. B's metrics appear
but its rows do not.

---

## Structural vs tuning, revisited

`patterns.js` passes `minSignalValue: 0`, so **tuning thresholds are fully
queryable in both directions**. Structural rules are baked in.

| Parameter | Queryable? |
|---|---|
| `RED_SQUEEZE_THRESHOLD` etc. | yes, both directions |
| `MIN_SEQ_LENGTH` | yes **if** stage 1 ran at 2 — `seqLength` is stored |
| `GREEN_STAIRS_MAX_EQUAL_STEPS` | yes **if** stage 1 ran high — `equalSteps` stored |
| `WALL_LOOKBACK_CANDLES` | no — no stored trace |
| `WALL_CLOSE_MULTIPLE` | no — no stored trace |
| OTM-only restriction | only if ITM rows were stored too |

Hence the advice in `01-running.md`: run stage 1 at the **loosest** structural
settings and tighten by query.

---

## Volume

Removing the tuning threshold multiplies row count. Estimated 1–5M rows and
0.2–4 GB for a full history — manageable, and it fits in memory if loaded per
`(signal, spot)`, which is what the server does. First query on a pair is slow,
the rest instant.

If it outgrows JSON, the answer is a columnar store rather than a smaller dataset.

---

## Current caveat

**`univRatio` in the query tool equals `ratio`.** `patterns.js` does not compute
the universe max — it reads `sig.universeRatio`, which only `processor.js` sets,
and falls back to `sig.signalRatio`.

So any query using `univRatio >= 10` is really measuring the firing instrument's
own payoff. Fine for checking the pipeline runs; not something to draw
conclusions from. See `08-open-questions.md`.
