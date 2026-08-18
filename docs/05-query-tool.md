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

## Walk-forward validation

Three sequential folds with an expanding training window:

```
fold 1: train [start .. a)   test [a .. b)
fold 2: train [start .. b)   test [b .. c)
fold 3: train [start .. c)   test [c .. end]
```

Every fold's test window is strictly out of sample, and the page shows each
fold's train%, test%, gap and purge count, plus the **mean out-of-sample** and the
**fold spread**.

The spread matters as much as the mean: a result holding up across three regimes
is different from one carried by a single lucky window.

### Why by date, never randomly

A random split sends signals from the **same expiry** — the same underlying move
— to both sides. The holdout would then be measuring data it trained on, and
would read far better than anything achievable live.

The objection to date splitting is that regimes differ by date. That is true, and
it is exactly the point: when you trade this, you will be in a future regime you
did not train on. A date split simulates that; a random split does not.

Walk-forward answers the regime concern properly, by testing across several of
them rather than one.

### Purging

A signal can fire up to 40 days before its own expiry, so a test-side signal may
observe market days inside the training window.

```
fired = date the pattern started
if expiry <= trainEnd:            train
if fired <= trainEnd (test side): PURGE — its window straddles the boundary
otherwise:                        test
```

The purge count is shown per fold. With expiries close together and short
lookbacks it can legitimately be zero; with 40-day lookbacks it will not be.

## Merging

Rows are **filtered first, then merged** into market events by overlapping time
window within the same `(expiry, duration, type)`.

Filtering first is what keeps per-instrument fields meaningful: `ratio1 > 8` is
evaluated while rows are still individual. Merging first would collapse it to a
maximum across strikes.

A merged event:

- wins if **any** member reached the success target, matching `maxRatio` semantics
- carries the max ratio across members — the assumption being that on seeing one
  alert you pick a strike rather than buying all of them. Optimistic, and the same
  assumption every earlier number in this project rests on.

The **Count** selector switches between merged events and individual signals. The
gap between them measures how much confluence inflates the rate — measured at
12.9% merged against 6.2% individual on test data.

## The filter box is prefilled

It opens with the expression reproducing the current config, so you see what is
actually being applied and edit numbers rather than write from scratch:

```
signalValue >= 50 && tteHours >= 1.5
```

**Reset to current config** restores it. Add clauses freely:

```
signalValue >= 50 && tteHours >= 1.5
  && distancePct between 2 and 6
  && duration in [60, 240]
  && log10(cheapness) > 4.5
```

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

## What is and is not expressible

**Expressible now** — anything over the 38 stored fields, the 12 functions, and
any computed field built from them. Arithmetic, comparisons, boolean logic,
`in [...]`, `between`, parentheses, nesting.

**Not expressible** — anything needing data that was never stored. "The low of the
3rd red candle", or a comparison against a *different* instrument's candles.
Those need a new field in `patterns.js` `toRow()` plus a registry entry and a
`patterns.js --force`.

The practical rule: if it can be written from the field list, it is instant. If
not, it is one line in `toRow` plus a re-run.

## Result columns

`Ratio | Value | Pattern start | Fired | In | Instruments | TTE h | OTM% |
Expiry | Dur | T`

**Pattern start** is when the sequence began; **Fired** is the entry candle.
**In** is how many instruments merged into the event.
