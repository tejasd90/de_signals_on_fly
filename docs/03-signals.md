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
signalValue = ratio1 + ratio2

fires when signalValue >= RED_SQUEEZE_THRESHOLD (50)
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

fires when signalValue >= OTM_SIGNAL_THRESHOLD (10000)
    ≈ average price at or below spot/10000, about 10 for BTC near 100k
ENTRY = the green trigger's close

also stores distancePct, so cheap-because-deep-OTM can be separated later
from cheap-and-close
```

**The threshold is a guess.** Calibrated from two synthetic observations, not real
data. It silently discards every pattern on an option pricier than ~10, and
rejected signals leave no trace. Worth one run at 1000 to see the distribution.

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

ENTRY = the BREAKOUT candle's close, not the last step
signalValue = same cheapness measure as otm_red_squeeze
```

**Entry differs from the squeeze signals**, so ratios are not directly comparable
between them.

A wick above the run high that closes back inside is rejection, not a breakout,
and is refused.

**A bug worth remembering:** the breaking candle is usually *green* — a run is
broken far more often by a smaller-bodied green than by a red. The first version
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

## Outcome annotation — all signals

```
signalRatio = max(high of EVERY candle after entry) / entry close
```

**Never truncated at a stop-loss.** An earlier version stopped measuring at the
first adverse close, and since options always decay below any pattern-derived
level, that made every ratio ≈ 1.0 and every state `slHit`.

```
signalState:
    'activated'  reached SL_FACTOR (1.5x) above entry, or broke out
    'slHit'      never got there — went against the trade immediately
    'pending'    the trigger was the last candle; no forward data yet
```

`slHit` does **not** mean stopped out. There is no simulated exit — `signalRatio`
is the best that was *available*, not what an exit rule would capture.

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
