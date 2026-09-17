# Brooks-derived spot features — arm 4 specification

Source: Al Brooks, *Trading Price Action: Trends* (glossary + Ch. 1–8, 26),
*Trading Ranges*, *Reversals*. Definitions paraphrased into computable rules.

**Design rule (D-41).** Brooks supplies the *structure*; the model supplies the
*thresholds*. Nothing here is a hand-tuned trigger. Every item is a continuous
feature or a count, computed on **spot** candles, hourly or higher (D-35).

**Why this arm matters.** The spot side of the current feature set is thin (~15
numbers), yet per §1.2 of ML_SPEC the spot move is where the learnable signal
lives. Brooks is spot-only — that is the target, not a limitation.

---

## Convergence worth recording

Brooks: **shrinking stairs** — three or more pushes to new extremes where each
breakout is smaller than the last, read as waning momentum.

That is structurally `red_squeeze` (successive shrinking pushes → exhaustion),
derived independently from spot charts. Also the direct inverse of
`green_stairs`. His reading ("waning momentum" in a bear leg) and yours
("sellers exhausted, expansion next") are the same claim.

This makes the arm 1 vs arm 2 vs arm 4 comparison sharper: three independent
routes to a similar structural hypothesis, measured against one label.

---

## 1. Bar-level — trivially mechanizable, compute for last N bars

| Brooks concept | Computable form |
|---|---|
| trend bar vs doji | `bodyFraction = |close−open| / (high−low)`. Continuous; no doji cutoff |
| bull / bear bar | `sign(close − open)` |
| shaved top / bottom | `upperTail/(high−low)`, `lowerTail/(high−low)`; shaved ⇒ near 0 |
| tails | both tail fractions, kept separately (Brooks weights them differently) |
| close position in bar | `(close − low) / (high − low)` |
| bar size vs recent | `(high−low) / ATR_slow` |
| reversal bar | bull: `bodyFraction` high **and** `lowerTail` large **and** prior leg down. Emit the components, not the verdict |

## 2. Bar-to-bar relationships

| Concept | Computable form |
|---|---|
| inside bar | `high ≤ prevHigh AND low ≥ prevLow` → boolean + `insideDepth = (prevRange − range)/prevRange` |
| outside bar | `high ≥ prevHigh AND low ≤ prevLow` (Brooks allows the `≥`/`≤` boundary) |
| `ii`, `iii` | count of consecutive inside bars ending at t (0,1,2,3…). Brooks: `iii` more reliable than `ii` — let the model rank |
| bodies-only `ii` | same test on bodies rather than tails; Brooks calls this the weaker version |
| bar pullback | upswing: `low < prevLow`; downswing: `high > prevHigh` |
| gap | `low > prevHigh` or `high < prevLow`; magnitude in ATR units |
| overlap | `overlap(bar, prevBar) / range` — the core trading-range measure |

## 3. Swing structure

Brooks: swing high = high at or above both neighbours; swing low = low at or
below both. Trivial to compute, and everything below builds on it.

- `barsSinceSwingHigh`, `barsSinceSwingLow`
- `distToSwingHigh`, `distToSwingLow` in ATR units
- **higher high / higher low / lower high / lower low** — booleans on the last
  two swings each side
- **trending swings** — Brooks: three or more swings where highs *and* lows both
  advance. Emit `trendingSwingCount` (signed)
- **three pushes** — count of consecutive same-direction swing extremes
- **shrinking stairs** — for the last 3+ pushes, the sequence of breakout sizes
  (`newExtreme − priorExtreme`), and the ratio of the latest to the previous.
  **Direct analogue of `ratio1`.** Emit the ratios; do not threshold
- **micro double top / bottom** — consecutive or near-consecutive bars with
  highs/lows within a small band; emit the band width in ATR units

## 4. Trend vs range — the spectrum, as a continuum

Brooks (Ch. 1) frames trend↔range as a spectrum, not a binary. Match that:

- **trending closes** — Brooks: three or more bars whose closes advance
  monotonically. Emit the current run length, signed
- **overlap ratio** — mean bar-to-bar overlap over the last N bars. High ⇒
  trading range; low ⇒ trend. **The single best continuous trend/range measure**
- **tight trading range** — high overlap + small ranges. Emit both components
- **barbwire** — three or more largely overlapping bars, at least one a doji.
  Emit `overlapRatio` together with `maxBodyFraction` over the window
- **directional efficiency** — `|close_t − close_{t−N}| / Σ|close_i − close_{i−1}|`.
  Near 1 ⇒ clean trend; near 0 ⇒ range. Not Brooks' term, but it is his spectrum
  expressed as one number
- **channel tightness** — regress highs and lows over the window; emit the gap
  between the two fitted lines, normalised by ATR. Tight ⇒ Brooks' tight channel
- **micro channel** — count of consecutive bars whose highs (or lows) touch the
  fitted line within a small tolerance

## 5. Breakout and follow-through — most relevant to your use case

Brooks: breakout = current bar's high or low extends beyond a prior price of
significance (swing point, prior bar extreme, trend line).

- `breakoutMagnitude` — distance beyond the reference level, in ATR units,
  computed separately against: prior bar high/low, last swing point, N-bar
  extreme
- `barsSinceBreakout`
- **follow-through** — count and cumulative extension of bars continuing the move
  after a breakout bar. Brooks weights the *next* bar most; emit next-bar
  extension separately from the cumulative figure
- **breakout pullback** — depth of the first retrace after breakout, in ATR
  units, and bars until it occurred
- **breakout mode** — Brooks: a setup where a break either way should follow
  through. Proxy: low `overlapRatio`-adjusted range width + high inside-bar count
  + contracting ranges. **This is the compression precursor from ML_SPEC D-31
  phase 1, expressed in Brooks' vocabulary**
- **climax** — extension far beyond a fitted trend channel line, plus
  accelerating bar size. Emit `channelOvershoot` (ATR units) and
  `barSizeAcceleration`

## 6. Deliberately NOT mechanized

Brooks resists mechanizing these, and forcing them would inject exactly the
hand-tuned judgment D-41 excludes:

- **always in** — depends on accumulated context and the trader's confidence
- **second entries** — requires identifying which prior setup failed
- **measured moves** — depends on choosing the reference leg
- **trend vs channel classification** as a verdict — replaced above by the
  continuous spectrum, which is closer to his own Ch. 1 framing anyway

If the continuous features work, the verdicts were never needed. If arm 4 wins
on them, revisit.

---

## Implementation notes

- All distances in ATR units so features transfer across BTC / ETH / equities
- Compute at multiple lookbacks (e.g. 5, 10, 20, 50 bars); let the model pick
- Hourly minimum (D-35)
- No booleans where a continuous version exists — `insideDepth` beats `isInside`
- Expected count: **~90–120 features**, all mechanical

## Open

- Which lookback window set? Start with {5,10,20,50}, prune via permutation
  importance (D-42)
- Brooks is intraday-oriented (5-minute Emini). Concepts are fractal by his own
  claim ("every pattern is a fractal"), but this is an assumption arm 4 tests
  rather than assumes
- Trend line fitting method: least squares on swing points vs on all bars.
  Start with swing points — closer to how Brooks draws them
