# Cross-timeframe repeats and wait-and-hold (2026-10-02, corrected same day)

Tejas: (1) a signal fires on many timeframes. Once a LOWER timeframe has delivered
the multibagger, a later HIGHER-timeframe signal on the same move is a repeat and
should be skipped. (2) Lower timeframes WAIT a few candles after the signal,
holding without hitting the SL, and then break out. Higher timeframes either don't
break out or don't wait. Example: C-BTC-87000-021026 on 1h, 2 Oct.

**Data as of 2026-10-02:** signal events from `events.parquet`, expiries up to
**2026-09-16**, all MARK prices. That file comes from the node signal pipeline,
which the dashboard loop does NOT run, so these results do not refresh with the
dashboard. Regenerate the signals, then rerun the scripts below.

## In plain English

- **Waiting for the hold is a real improvement, but not a profitable rule on its
  own.** After the real 8.26% cost of getting in and out, buying every 30–60m
  signal immediately returns about **₹80 per ₹100** staked. Waiting 3 candles and
  buying only if the premium held above the signal candle's low returns about
  **₹97 per ₹100**. On 90m–3h it goes from about ₹83 to about ₹101. That cuts the
  loss by ₹10–22 per ₹100, for calls and puts alike, so it is not bull-market drift.
- **It does not find more multibaggers.** The 25x hit rate does not rise after a
  hold. The gain is that held options are still worth something at expiry,
  instead of decaying to zero.
- **It fits stress-free trading (Tejas):** waiting is the opposite of FOMO
  rush-buying, and only about 1 in 3 signals passes, so far fewer trades. It works
  as a discipline filter that cuts losses, not as a source of profit.
- **Per signal, after cost:** only `otm_wall` (all timeframes) and `green_stairs`
  / `otm_red_squeeze` on 90m–3h end up clearly above break-even. See §3.
- **On 4h–1d signals, waiting gives nothing reliable.**
- **The repeat rule is NOT supported** once measured without look-ahead. See §1.

Scripts: `tf_repeat.py` (superseded), `tf_repeat_causal.py`, `tf_hold.py`
(`data/tf_hold.parquet`, a 35% sample with 438k rows), `tf_hold_ci.py`,
`tf_hold_cp.py` (cost, calls vs puts), `tf_hold_settle.py` (settlement
intrinsic), `tf_combo.py`.

## 1. Repeats across timeframes: not significant (withdrawn)

The first version flagged a repeat by the lower-timeframe contract's PEAK time.
Being "the peak" also means no higher high came later, which is future information
about the same move, so it exaggerated the effect: it reported "about half as
good".

With the causal flag (`tf_repeat_causal.py`: the first bar where the lower-tf
contract crossed 25x, read from candle files), 9.6% of 2h–1d events are flagged.
Their P(25x), adjusted for time to expiry, is **0.79× expected, 95% CI [0.42,
1.31]**. That is lower in the 0–24h and 96h+ bands and HIGHER in the 24–96h
band. There is no usable rule here. The 5–20m signals he mentions were never
generated (`events.parquet` starts at 30m), so that version is untested.

## 2. Wait-and-hold

Rule: SL = trigger candle's low. Wait W = 3 candles of the same timeframe. If no
low went below the SL, enter at the close of candle 3. Exit at 25x or hold to
expiry, valued at settlement intrinsic. The 8.26% round-trip cost is deducted.

| timeframe | type | enter now | wait & held | difference (95% CI, before cost) |
|---|---|---|---|---|
| 30–60m | call | −0.22 | −0.07 | +0.16 [+0.09, +0.24] |
| 30–60m | put | −0.18 | −0.03 | +0.17 [+0.10, +0.23] |
| 90–180m | call | −0.25 | −0.03 | +0.25 [+0.16, +0.35] |
| 90–180m | put | −0.10 | +0.01 | +0.11 [+0.02, +0.21] |
| 4h–1d | call | −0.16 | −0.16 | +0.02 [−0.24, +0.22] |
| 4h–1d | put | −0.05 | +0.06 | +0.14 [−0.09, +0.34] |

- **Positive in both halves of time**, and in most years.
- **"Higher timeframes don't wait":** within 5 candles the premium has already doubled in 16% of 4h–1d signals vs 9% at 30–60m.
- **Reconciling with CONTEXT_PLAN's "delayed entry: 15 cells, all negative":** that test scored target-or-zero, i.e. hit-rate EV. On that metric waiting is ALSO slightly worse here (`tf_hold_cp.py`, hit-only columns). The two results agree. Waiting buys retained value, not hits.
- **Reconciling with PREMIUM_SIGNALS's "hold = already expensive, don't buy":** that was a holding pattern BEFORE entry, and it was about hit size. This is a post-signal hold, and its gain is retained value. They do not conflict, but both say a hold does not predict a bigger move.

## 3. Per signal (`tf_combo.py`, W = 3, 25x, before the 8.26% cost)

| signal | 30–60m now → hold | 90–180m now → hold | 4h–1d now → hold | kept |
|---|---|---|---|---|
| otm_wall | −0.14 → **+0.08** | −0.13 → **+0.10** | −0.05 → **+0.16** | 40–48% |
| green_stairs | −0.13 → **+0.14** | −0.12 → **+0.19** | −0.11 → −0.25 | 25–34% |
| otm_red_squeeze | −0.12 → −0.04 | −0.01 → **+0.19** | +0.13 → +0.03 | 15–22% |
| red_squeeze | −0.04 → +0.04 | −0.06 → +0.03 | −0.04 → −0.13 | 20–25% |

Subtract about 0.08 for cost. There are 12 cells with no per-cell CIs, so expect
noise. `otm_wall` is the largest sample and positive in all three groups.

## Bounds

- MARK prices: peaks are upper bounds, so treat the ₹ figures as comparisons.
- The SL is the trigger candle's low; no other SL was tried.
- A 35% sample of rows.
