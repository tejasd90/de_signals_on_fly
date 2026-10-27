# Every parabola algorithm implemented so far (pseudocode), 27 Oct 2026

Written at his request, as step 1 of a step-by-step review: first exactly what the code does, then
success and failure cases one at a time. Notation:
- **swing low** at bar j = `low[j]` is the lowest low of bars j−2 … j+2, so it is only known at bar j+2;
- **x** = later high ÷ entry close;
- all prices are Delta MARK option candles unless stated.

His descriptions this is based on:
- **9 Oct (journal 16):** "long decay toward zero, then a parabola holding up / slowly rising, then the explosion".
- **2 Oct:** "signal, then the lower timeframes wait a few candles; it should HOLD over the wait period".
- **26 Oct:** "falling lines get flatter and flatter; when they hold, more powerful explosions".

## A. Premium base v1 / v2: `premium_base.py` (1h only)

```
for each contract, each 1h bar i (causal), while time to expiry >= 12h:
    window      = the last 48 bars
    lows        = swing lows inside the window known by bar i   (need >= 3)
    prior_high  = highest close in the 10 days before the window
    bottom      = min(lows)
    CHEAP       = bottom <= 0.15 * prior_high  AND  bottom <= 0.25% of spot
    after       = the swing lows after the bottom
    fit a quadratic a*x^2 + b*x + c through lows
    PARABOLA    = a > 0  AND  len(after) >= 2  AND  min(after) >= 1.5 * bottom
                  AND close_i >= last low  AND  close_i <= 3 * bottom   (still a base, not already exploded)
                  (v1 demanded strictly rising lows; v2 allowed 44 -> 31 -> 56 -> 52)
    if CHEAP and PARABOLA (>= 24 bars after the previous event): PATTERN event
    else if CHEAP and no low after the bottom yet: CONTROL event (once per contract)
outcome: max later high to settlement / close_i;  hit at 5x, 10x, 25x, 100x
compare: pattern vs control, reweighted to the same time-to-expiry x moneyness x cheapness mix
```
**Result:** 25x 2.2% (n 2,882) vs 4.6% for still-falling controls. **Falsified.** His correction followed: the 12h, 1h
and cheapness limits were assumptions he never stated.

## B. Premium base v3: `premium_base3.py` (5m, 15m, 1h, 4h; any time to expiry; any strike)

```
for each contract and timeframe, at every NEW swing low j (decision at i = j+2, close_i >= low_j):
    lows      = swing lows in the last 48 bars (need >= 3)
    bottom    = min(lows); after = lows after the bottom
    DECAYED   = bottom <= 0.15 * highest close before the window
    BOWL      = quadratic through lows opens up AND len(after) >= 2 AND all after > bottom
    ARM       = last 3 lows rising AND last step up > first step up (accelerating)
    if not DECAYED: skip
    PATTERN if BOWL or ARM else CONTROL   (each at most once per 48 bars per contract)
also record the next 3 strikes further OTM: their premium, outcome, and whether they show the shape
compare within timeframe x time to expiry x moneyness x decay depth (and x recovery from bottom)
```
**Result:** 25x 1.89% (n 491,705) vs 1.98%. Level in every slice. **Falsified.**

## C. Premium base v4: `premium_base4.py` (his correction: only the RISING parabola; no decay needed)

```
at every new swing low (as in B):
    run      = the trailing run of consecutive higher lows ending at this low (need >= 3)
    CONVEX   = quadratic through the run opens upward   (each step up tends to be bigger)
    ACCEL    = last step > first step   (recorded only)
    PATTERN if CONVEX else CONTROL;  decay depth recorded, never filtered
```
**Result:**
- 25x 0.66% (n 913,231) vs 0.71% for controls. Level in every slice.
- His examples fire (P-BTC-81000-091026: 8.9x).
- So do many that went nowhere: the 2 Oct expiry's 80500/81000/87000 strikes fired 3–4 times each in late Sep
  for 1.0–1.5x.
- **Falsified,** but note: **it fired 913k times**. The shape as coded is everywhere, so it cannot be the
  thing his eye picks out.

## D. Blind chart test: `blindtest/` (his eye, not code)

```
chart = one asset x expiry x call/put, shown as a ladder of the 5 nearest-OTM strikes (+3 on request)
        plus the underlying with 30 days of history; anonymised (no asset name, date, or strike values)
start = 40% into the expiry's life (min 24h after listing), at most 7 days before settlement
sample 100 charts, ratio hidden:
    A 40  some ladder strike later offered >= 10x
    B 30  none did, but detector C fired
    C 30  none did
he steps forward candle by candle (1h/4h/12h; 15m on expiry day only) and either CALLS (picks strikes,
target) or leaves / lets it run to expiry
score: his picked strikes' max later high / close at his decision point
```
**Result:**
- 10 calls, 0 reached target (best 2.75x).
- 36 of the 40 A charts were watched to expiry uncalled. Their moves came a median 15h before settlement.
- **Caveat he raised:** anonymising removes the live context he uses (asset, date, news, other strikes' values).

## E. Signal, then the premium holds: `tf_hold.py`, `tf_hold_oos.py` (his 2 Oct rule)

```
for each signal firing (otm_wall, green_stairs, otm_red_squeeze, red_squeeze) on each strike, at its own timeframe:
    trigger = the signal candle; SL = its low; entry_now = its close
    wait 3 candles; HELD = no low below SL during the wait
    entry_wait = close of candle 3
    value = 25 if later high >= 25 x entry else what is left at expiry (cap 25); minus 8.26% cost
compare held-and-wait vs buy-now, by timeframe and signal; CI by expiry
```
**Result:**
- Before 16 Sep: holding keeps ₹13–17 more per ₹100 on 5m–3h. It does NOT find more 25x.
- Out of sample (17 Sep–24 Oct): the gain survives only for **otm_wall** (+0.18 to +0.36, CIs > 0).
- His 22–24 Oct 1:20 and 1:100 trades fit the rule.

## F. Falling lines on the premium chart: `premium_lines.py` (his 26 Oct point)

```
for each contract (8 nearest strikes, life >= 4 days), last 10 days, 15m, log premium:
    lines = falling resistance lines through >= 3 swing highs (levels.trendlines), confirmed causally,
            spanning >= 24h
    break = first close above a line
    slope = the line's slope in log-premium per hour; flatter = closer to 0
    outcome: best later high within 24h / break close (2x, 3x, 5x); value at expiry
compare flat vs steep thirds (same asset x side x time to expiry x premium level);
        flatter-than-previous-line vs steeper; random bar on the same contract (control)
```
**Result:**
- Flat line: 3x 5.8% vs 4.1% for steep (CI touches 0). After the break it keeps more value to expiry
  (1.19x vs 0.90x, CI > 0).
- "Flatter than the previous line" does worse.
- A break is no better than a random bar on the same contract.

## What none of these encode (candidates from his charts and words)

- **The whole arc, not just the dips.** Every detector reads swing lows only. His NIFTY 22600 CE drawing is an arc
  through the bodies: falling, slowing, flattening, turning.
- **Where the strike sits in the chain:** the shape clear on one strike and flattening further out.
- **The spot / VIX context at the same moment:** further fall "unlikely".
- **Time to expiry, and which expiry:** the monthly vs weekly decay rhythm.
- **His signals' timing** relative to the arc.
- **A short, specific window per case,** not every new swing low of every contract (913k events).
