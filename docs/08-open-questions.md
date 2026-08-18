# Open questions

Unresolved, roughly in order of how much they affect the numbers.
Items marked **AWAITING YOU** are ones raised without an answer yet.

---

## RESOLVED since the last revision

| Was | Now |
|---|---|
| `univRatio` equalled `ratio` in the query tool | `patterns.js` computes it via `universeMaxAt` |
| No merging in the query pipeline | Filter-then-merge, with a Count selector |
| Holdout had no purge | Walk-forward folds, purged at each boundary |
| Opposite-direction filter dropped | Restored, both big-red and big-green |
| Two query slots | Collapsed to one, prefilled with current criteria |
| Firing times not shown | `Pattern start` and `Fired` columns added |
| Wall-clock time fields | Superseded by `MIN_TTE_HOURS_TO_FIRE` |

---

## 1. Thresholds are guesses

**`OTM_SIGNAL_THRESHOLD = 10000`** was calibrated from two synthetic
observations. It means the average pattern price must be at or below
`spot/10000` — about 10 for BTC near 100k. Anything pricier is discarded at
generation and leaves no trace, so if the real edge sits on options priced 25 or
40 you would never see it.

Now less pressing: with `patterns.js` storing at `minSignalValue: 0`, the query
tool can explore in both directions. The threshold only matters for the
`processor.js` path that feeds `quality.js` and the calendar viewers.

**`otm_wall` strength bands** are set 2 to 6+, but test jumps came out at 8.35 and
10.46. If real data behaves similarly, everything lands in the top band. Display
only — no re-run needed to fix.

---

## 2. `signalValue` may rank nothing

The observed hit rate across strength bands was **15 / 15 / 16 / 17 / 17%** —
essentially flat. A signal scoring 50 and one scoring 1000+ reached 10x at almost
the same rate.

That is not the same as the pattern having no edge. It may mean the pattern is
worth something while `ratio1 + ratio2` fails to rank instances of it.

The distinction matters: **if the score does not rank, raising the threshold takes
fewer signals rather than better ones.** The fix would be a different formula, not
a different cutoff — `signalFn` is one line.

The `>=50x` and `>=100x` columns are the sharper test than `>=10x`.

---

## 3. Merged events take the max across members — **AWAITING YOU**

A merged event's ratio is the best among its members, assuming that on seeing one
alert you would pick the best strike. That is optimistic, and it is the assumption
underneath every number this project has produced.

Alternatives: the member closest to the money, or the mean across members. Either
would lower the headline figure and make it more honest.

Related: the same move at 60m and 240m currently counts as **two** events, since
merging is within `(expiry, duration, type)`. For a "how often would I have
traded" number that is probably wrong.

---

## 4. ML — deferred, and why

The feature table `patterns.js` produces **is** an ML feature table, so nothing is
wasted by having built the query tool first.

**On the 80–90% target: not reachable.** If a 10x move in a cheap OTM option were
85% predictable from candle history, the option would not be priced where it is.
Thin deep-OTM books leave *some* room — which is why an edge is plausible at all —
not that much room.

A second gap: 20% is measured on **peak from entry** with a perfect exit. Realized
returns are a fraction of that, and the fraction depends on an exit rule not
modelled anywhere yet.

**Better target: expectancy, not win rate.** At 20% reaching 10x, even with total
loss on the rest, that is strongly positive. Improving 20% → 32% would be a 60%
relative gain.

**What ML is genuinely good for here: context.** The heuristics ignore it — the
same shape scores identically 3 hours or 30 days from expiry, at 2% or 20% OTM.
Gradient boosting over `tteHours`, `distancePct`, `duration`, EMA spread and
volatility would find those interactions and report which matter.

**The real constraint is labels, not algorithms.** A million rows sounds ample, but
rows from one expiry share the same move, so the effective independent sample is
closer to the number of distinct market events — likely a few thousand.

**Variable-length patterns** are solvable three ways: pad to a fixed window, use a
sequence model, or encode as summary features. The third needs the least data,
stays interpretable, and is close to what already happens.

Plan: run the query tool on real data, then spend an afternoon on LightGBM over
the same features with a purged split. The comparison is unambiguous, because the
flat matrix says the current scoring ranks nothing.
