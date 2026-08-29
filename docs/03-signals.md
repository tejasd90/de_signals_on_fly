# The four signals

Every signal exports `{ id, requiresSpot, otmOnly, computeSignals }` and is listed
in `signal_registry.js`. Adding one is a file plus a line — fetching, grouping,
merging, storage, both viewers and quality all pick it up.

```
computeSignals(candles, instrument, ctx, opts) -> signal[]
    instrument = { symbol, type, strike }
    ctx        = { spotByTs, duration, expiryDate, spot }
    opts       = { minSignalValue }    overrides the config threshold
```

---

## Structural vs tuning

A distinction that runs through the whole design.

**Structural** defines what the pattern *is*. Without it there is no signal to
store: `MIN_SEQ_LENGTH`, reds must shrink, the trigger must be green.

**Tuning** filters patterns already found: the thresholds.

`processor.js` applies both. `patterns.js` applies only structural, passing
`minSignalValue: 0` — which is what makes the query tool able to explore a
threshold in *both* directions.

---

## 1. `red_squeeze`

The original. No spot required, not OTM-restricted.

```
N consecutive RED candles with STRICTLY SHRINKING bodies, then a STRICT GREEN.

zero-body candle  → breaks the run, cannot trigger
non-shrinking red → resets; that candle starts a new run
green             → always ends the run, signal or not

ratio1 = firstRedBody / lastRedBody      how tight the squeeze got
ratio2 = firstRedBody / greenBody        how small the trigger is
signalValue = max(ratio1, ratio2)

fires when EITHER ratio clears RED_SQUEEZE_THRESHOLD (15)
    signalValue >= T is exactly (ratio1 >= T || ratio2 >= T)

Was sum >= 50. The sum let two mediocre ratios combine into a signal neither
justified, and could MISS a very tight squeeze whose green happened to be
large. Both ratios remain stored, so a query can still require both.
ENTRY = the green trigger's close
```

Both ratios reward *smallness* — a tinier green raises `ratio2`, on the reading
that a large green means the move has already partly happened.

**Known weakness.** `signalValue` does not separate winners from ordinary decay.
On synthetic data the worst false positive scored 5757 and the weakest true
positive 51 — distributions almost entirely overlapping. Raising the threshold
kills true positives about as fast as false ones.

**Second weakness, and the reason for the OTM variants.** It fires on ITM options,
where premium carries intrinsic value that melts hard, so a clean pattern there
says little.

---

## 2. `otm_red_squeeze`

Same shape, OTM only, scored on cheapness instead of geometry.

```
Same red/green structure as red_squeeze.

REQUIRES OTM at PATTERN START (the first candle of the run):
    calls: strike > spot        puts: strike < spot
    judged on the spot close at that timestamp

Moneyness at pattern start rather than at trigger is the looser test, so an
instrument drifting across the money mid-pattern is kept.

signalValue = spot / mean(triggerClose, low of EVERY pattern candle)

    dimensionless, so one threshold serves BTC and XAUT alike
    higher = cheaper option = the reliability claim

fires when signalValue >= OTM_SIGNAL_THRESHOLD (1000)
    ≈ average price at or below spot/1000 — 100 for BTC near 100k, 4 for XAUT near 4k
ENTRY = the green trigger's close

also stores distancePct, so cheap-because-deep-OTM can be separated later
from cheap-and-close

ALSO RECORDS, without using them to fire:
    firstRedBody, lastRedBody, greenBody, ratio1, ratio2

    Squeeze geometry was removed from SCORING because it failed to rank in the
    unrestricted red_squeeze. Whether it ranks WITHIN the OTM population is a
    different and untested question — and unaskable if the numbers are not kept.
```

**The threshold was lowered from 10,000 to 1,000.** The original came from two
synthetic test observations and nothing else. Beyond being arbitrary, a fixed
price ceiling silently filters by TIME TO EXPIRY as much as by cheapness — a
40-day option costs far more than the same strike hours before settlement — and
`tteHours` is a queryable field and a much better way to control that explicitly.

It is kept non-zero only to trim obvious noise from the dashboards. Tighten with
the display-side minimum, which costs a redraw rather than a re-run.

---

## 3. `green_stairs`

The mirror image — accumulation rather than exhaustion.

```
N consecutive GREEN candles with NON-DECREASING bodies, then a candle
that CLOSES ABOVE the high of the whole run.

a body may merely EQUAL its predecessor at most GREEN_STAIRS_MAX_EQUAL_STEPS
times (1). Real chains often contain one flat step; allowing many lets a run
of identical candles pass as a staircase.

zero-body → breaks the run, but can still be the breakout: what matters is
            where it CLOSED

SIGNAL CANDLE = the LAST STEP of the run
    No separate breakout candle is required to FIRE. The staircase completing IS
    the signal; activation is then price exceeding the last step's high, the same
    rule as every other signal.

signalValue = same cheapness measure as otm_red_squeeze

ALSO RECORDS: firstRedBody, lastRedBody, greenBody,
              ratio1 = lastStepBody / firstStepBody   (staircase steepness)
```

**This replaced an earlier design** where the signal only existed once a later
candle CLOSED above the run high. That made `green_stairs` fire strictly later,
less often and at a worse price than the other signals, and made its ratios
incomparable with theirs. All three now share one activation rule.

A consequence: `green_stairs` fires considerably more often than before, since
completing the staircase is sufficient.

**A bug worth remembering:** the candle that ends a run is usually *green* — a run
is broken far more often by a smaller-bodied green than by a red. An early version
only tested non-green candles and fired zero.

---

## 4. `otm_wall`

A wall candle after a narrow range. Ported from the spike-after-flats signal in
the original `group.js`, minus its moving-average, volume and normalisation terms.

```
Over the 5 preceding candles:

  dist = Σ |OCmax(cur) − OCmax(p)| + |OCmin(cur) − OCmin(p)|
         where OCmax = max(open,close), OCmin = min(open,close)

  null if dist == 0, or if all 5 predecessors are dead candles
       (a first real print after untraded candles is not a wall)

  value = log10(open × close × dist²)

Compare against BOTH prev1 and prev2, take the larger jump:

  jump = value(cur) − value(prev)
  requires jump >= WALL_JUMP_THRESHOLD (2)      → a hundredfold growth
  requires close >= WALL_CLOSE_MULTIPLE (1.35) × that candle's close
  requires the candle to be GREEN
  requires OTM at pattern start

signalValue = the jump
ENTRY = the wall candle's close
```

Checking both `prev1` and `prev2` tolerates one small transitional candle between
the flat run and the wall.

**Narrowness is implicit, deliberately.** The predecessors are never tested for
being *small* — `dist` is large exactly when they were tightly clustered and the
current one departed. A fixed size threshold would only work at one price level,
whereas `dist` scales with whatever range the instrument trades in. Verified
firing at both tiny premiums (0.5 → 8) and ordinary prices (50 → 140).

Dropped from the original: `−4·log10(DTE+1)` and `−4·log10(1+spot/10000)`. Both
nearly cancel in a difference while making raw values incomparable across
expiries.

---

## Firing cutoff — all signals

```
A signal may not FIRE within MIN_TTE_HOURS_TO_FIRE (1.5) hours of settlement.

Applied AFTER outcome annotation, so a signal that fired earlier keeps its full
forward window and its ratio is unaffected. Only the decision to INITIATE is
restricted.

Boundary is inclusive: exactly 1.5h to expiry still fires; 1.4h does not.
```

STRUCTURAL — changing it needs both `--force-signals` and `patterns.js --force`.

---

## Opposite-direction spot filter — all signals

```
A sharp move spikes premium on BOTH calls and puts, so a bullish-looking option
pattern can fire purely because the underlying just dropped hard.

Suppress a CALL signal when the spot candle at entry is a big RED one.
Suppress a PUT  signal when it is a big GREEN one.

"big" = body exceeds BIG_CANDLE_BODY_FRACTION (0.6) of the candle's full range,
        so a long-wicked indecisive candle does not count however far it travelled

no spot candle at that timestamp -> keep the signal, cannot judge
```

Ported from the original `group.js`, where it was the final gate before a signal
was recorded. Dropped in the first rewrite, restored now.

Applied after outcome annotation, like the firing cutoff, so a surviving signal's
ratio is untouched. STRUCTURAL — needs `--force-signals` and `patterns.js --force`.

---

## Activation and outcomes — all signals

One rule across every signal:

```
ACTIVATION = price trading above the HIGH of the SIGNAL CANDLE.

An intrabar touch is enough — the candle need NOT close above the level. That
models a resting stop-buy at the signal candle's high, which fills the moment
the level trades regardless of where the candle ends.

    triggerPrice = signal candle's high
    peakAfter    = highest high across ALL candles after the signal candle
    signalRatio  = peakAfter / triggerPrice
    brokeOut     = peakAfter > triggerPrice        (strictly above)
    signalState  = brokeOut ? 'activated' : 'slHit'
                   'pending' when the signal candle is the last one
```

The signal candle per signal:

| Signal | Signal candle |
|---|---|
| `red_squeeze` | the green trigger |
| `otm_red_squeeze` | the green trigger |
| `green_stairs` | the **last step** of the staircase |
| `otm_wall` | the wall candle |

### The denominator is the HIGH, not the close

Stricter than the previous definition, and every ratio is correspondingly lower.
Worked example: a trigger closing at 101 with a high of 105, peaking at 320 after,
now scores **3.048** where it previously scored 3.168.

That is the point. The high is what a stop entry actually pays, so the number is
something achievable rather than a best case.

### Never truncated

Measured across all subsequent candles. Options decay below any pattern-derived
level, so stopping early would drive every ratio to ~1 — which is exactly what an
earlier version did.

`RED_SQUEEZE_SL_FACTOR` and `OTM_SL_FACTOR` no longer influence state; activation
is now defined purely by whether the trigger level was reached.

---

## `universeMaxRatio`

A signal fires on one instrument but is really a statement about the spot. The
big multiple usually lands on a different strike, so each merged range also
records the best payoff across every **eligible** instrument at that moment.

```
eligible = same type (a put signal never looks at calls)
         + already listed at the signal timestamp
         + for otmOnly signals, OTM at that moment

UNIVERSE_MAX_MODE = 'all_same_type'    any strike of the same type (DEFAULT)
                  = 'further_otm'      only strikes further out than the firing one
```

`all_same_type` is the default because the field measures *how big a move was
there*, not which strike to buy — and a boundary can truncate the answer. In
testing, `further_otm` reported 5x where the true best was 100x on a strike below
the firing one.

Always `>= maxSignalRatio`, since the firing instrument is itself eligible.

**Currently missing from `patterns.js`.** The query tool's `univRatio` equals
`ratio` until that is fixed. See `08-open-questions.md`.

---

## Differences from the old Indian-market `group.js`

| | Old | New |
|---|---|---|
| Stairs continuation | `!isRed` — a **doji continues** | strictly green; doji breaks |
| Stairs equal bodies | unlimited, rounded to integer | at most 1, unrounded |
| Stairs entry | fires when count reaches 3 | waits for a breakout close |
| Stairs strength | `duration × count²` × EMAs × volume | cheapness |
| Wall gates | 5 gates incl. volume and lot size | OTM + green + 1.35× |
| Firing gate | strength > 900, **plus** an opposite-direction spot filter | per-signal thresholds |
| Moneyness | both sides within a DTE-scaled band | strictly OTM |

**The opposite-direction filter has no counterpart here.** The old code suppressed
a call signal when spot printed a big red candle. That is genuine hygiene and it
was dropped without discussion — see `08-open-questions.md`.

The stairs entry difference is the largest: the new version fires strictly later,
less often, and at a higher price.
