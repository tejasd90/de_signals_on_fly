# Open questions

Unresolved, roughly in order of how much they affect the numbers.

---

## 1. `univRatio` in the query tool is wrong

**Status: a real defect, not a design choice.**

`patterns.js` reads `sig.universeRatio`, which only `processor.js` ever sets, and
falls back to `sig.signalRatio`. So in `serve_query.js`, **`univRatio` is identical
to `ratio`** — the firing instrument's own payoff, not the best same-type strike.

Any query using `univRatio >= 10` is really measuring `ratio`.

Merging was never required for this — `buildUniverseIndex` needs only
`candlesBySymbol`, which `patterns.js` already builds per duration. It is a small
addition: build the index once per duration, annotate each signal.

Should be fixed before drawing any conclusion from query results.

---

## 2. Merging is absent from the query pipeline

Stage 1 stores unmerged rows, and nothing merges them afterwards. A move firing on
8 strikes appears as 8 rows.

**What that measures:** "of every individual instrument signal, what fraction
reached 10x". Correct only if you would buy every signal on every strike.

**What you probably want:** "of distinct market events, what fraction paid" —
because when 8 strikes fire you would see one alert and buy one thing.

**Why it is not cosmetic:** unmerged overweights big confluences. If good setups
fire on more strikes, the rate is inflated; if decay noise fires broadly and real
squeezes are narrow, it is deflated. Neither is obviously true.

**The tension:** merging destroys the per-instrument fields the query language
exists to filter on.

Three options:

- **Filter then merge** — query on per-instrument fields, merge survivors. Clean,
  but event boundaries then depend on the filter, so two queries are not comparing
  quite the same events.
- **Merge first with aggregates** — store `maxRatio1`, `meanRatio1` etc. Stable
  boundaries, clumsier language, loses "any member with ratio1 > 8".
- **Report both** — keep rows unmerged and show two rates side by side. Reversible,
  and the *gap* is itself informative: 31% per-signal against 18% per-event is a
  finding about confluence.

Leaning toward the third.

Two sub-decisions either way: is the same move at 60m and 240m one event or two
(currently two, probably wrong for a "how often would I trade" number), and does
an event's outcome take the max across members (currently yes, which is
optimistic) or something less generous.

---

## 3. The holdout has no purge

Signals fire up to 40 days before their expiry, so a *test* signal can fire before
a *train* expiry has settled. Both observe the same market window and the holdout
reads better than it should.

The fix:

```
IF patternStart <= cutDate < expiry: DROP the row
```

Costs 5–10% of rows for a holdout you can trust. An embargo — a further buffer
after the cut — would be stricter still.

The current split catches blatant curve fits reliably (verified at a 77.8-point
gap) but subtle ones less so.

---

## 4. Thresholds are guesses

**`OTM_SIGNAL_THRESHOLD = 10000`** was calibrated from two synthetic observations.
It silently discards every pattern on an option pricier than about 10 for BTC, and
rejected signals leave no trace. Worth one run at 1000 to see the distribution
before trusting it.

**`otm_wall` strength bands** are set `2-2.5 … 6+`, but test jumps came out at 8.35
and 10.46 — both in the top band. If the matrix collapses the way
`otm_red_squeeze` did before its bands were fixed, widen them. Display-only.

---

## 5. The opposite-direction filter was dropped

The old `group.js` suppressed a call signal when the underlying printed a big red
candle, and a put signal when it printed a big green one:

```
checkForOppositeDirectionSignal =
    (CE AND spot candle is big red) OR (PE AND spot candle is big green)
```

That is genuine hygiene — a bullish option setup firing into a bearish spot bar —
and it has no counterpart in the new pipeline. It was dropped without discussion.

Cheap to add: spot candles are already indexed per duration.

---

## 6. Time-of-day fields are missing

There is no way to express "do not initiate after 4pm". `entryTs` is stored but
the language has no date functions.

Fix: add `entryHour`, `entryMinute`, possibly `entryDayOfWeek` to `toRow` plus
registry entries. Then `entryHour < 16` works. Needs a `patterns.js` re-run, so
worth batching with the `univRatio` fix.

The design already supports the semantics: the clause filters which signals you
*initiate*, while the outcome is measured over all subsequent candles regardless.

---

## 7. Query B's rows are not shown

Both slots compute and both sets of metrics display, but the tables below show
Query A only. Options: tabs, stacked tables, or a toggle.

---

## 8. `signalValue` may not rank anything

The observed hit rate across strength bands was **15/15/16/17/17%** — essentially
flat. On synthetic data the worst false positive scored 5757 and the weakest true
positive 51.

That is not the same as the signal having no edge. It could mean the *pattern*
carries an edge while the *scoring formula* fails to rank instances. Those need
different fixes, and the query tool exists largely to tell them apart.

Check the `≥50x` and `≥100x` columns: if those are flat too, the formula is the
problem and `signalFn` is one line to change.

---

## 9. ML — deferred, and why

The feature table stage 1 produces **is** an ML feature table, so nothing is
wasted by building the query tool first.

**On the 80–90% target:** not reachable. If a 10x move in a cheap OTM option were
85% predictable from candle history, the option would not be priced where it is.
Thin deep-OTM books leave *some* room, which is why an edge is plausible at all —
not that much room.

There is a second gap: 20% is measured on **peak from entry** with perfect exit.
Realized returns are a fraction of that, depending on an exit rule not modelled
anywhere yet.

Better target: **expectancy, not win rate.** At 20% reaching 10x, even with total
loss on the rest, that is strongly positive. Improving 20% → 32% would be a 60%
relative gain.

**What ML is genuinely good for here:** context. The heuristics ignore it
entirely — the same shape scores identically 3 hours or 30 days from expiry, at 2%
or 20% OTM. Gradient boosting over `tteHours`, `distancePct`, `duration`, EMA
spread and volatility would find those interactions and report which ones matter.

**The real constraint is labels, not algorithms.** A million rows sounds ample, but
rows from one expiry share the same move, so the effective independent sample is
closer to the number of distinct market events — likely a few thousand.

**Variable-length patterns** are solvable three ways: pad to a fixed window, use a
sequence model, or encode as summary features. The third needs the least data and
stays interpretable, and is close to what already happens.

Plan: run the query tool on real data first, then spend an afternoon on LightGBM
over the same features with a purged split. The comparison is unambiguous, because
the current flat matrix says the existing scoring ranks nothing.
