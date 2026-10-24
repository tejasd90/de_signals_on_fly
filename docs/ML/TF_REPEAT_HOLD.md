# Cross-timeframe repeats and wait-and-hold (2026-10-02, corrected same day; re-tested out of sample 2026-10-24, §4)

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

## 4. Re-test, 24 Oct 2026: out of sample, and the 5–20m signals

**Why:** he traded the rule on 22–24 Oct ("signal formation and then premiums hold … gave a 1:20 yesterday and a
1:100 today", both on 1h `otm_red_squeeze`). This section checks those two trades, then re-runs the test on the
38 expiries since 17 Sep that §2 never saw, and on 5–20m signals, which did not exist as events before
(`build_events.py --min-duration 5 --max-duration 20` → `data/events_lowtf.parquet`). Script `tf_hold_oos.py`
(rows `data/tf_hold_oos.parquet`: in-sample 35% sample of 30m+, 15% of 5–20m; out of sample all rows). The
rule is unchanged: SL = trigger candle's low, wait 3 candles, held = no low below the SL, entry at the close of
candle 3. Value = 25 if 25x, else what is left at expiry (capped at 25), before the 8.26% cost. MARK prices.

### His two trades (`hold_case_oct.py`, 5m MARK and TRADED from the API, rebuilt to each signal's timeframe)

- **1:20 = the rule, exactly.** P-BTC-81000-231026, 1h `otm_red_squeeze` on the 21 Oct 23:30 IST candle: close
  30.4, SL 20.9. The next three lows were 25.0 / 24.5 / 29.1, so it held. It went sideways about 7 candles and
  broke at 06:30 on 22 Oct. The high was 543 traded at 21:30, **~18x** from the post-wait entry (30.1). The 80600
  to 82200 puts held the same way (17–26x after the wait), and so did ETH P-2380-231026 (~26x).
- **1:100 = the loose version ("SL should not get hit at least for some strikes").** ETH P-2300/2320-251026, 1h
  `otm_red_squeeze` (and `red_squeeze`) on the 24 Oct 10:30 candle. One candle (12:30) dipped just under the
  signal low (2300: 0.43 vs 0.51 MARK; traded 0.50), then the premium held until 19:30 and exploded at 20:30.
  Traded: P-2300 0.90 → 34.8 (**39x** from the signal close, 70x from the dip), P-2280 0.28 → 24.1 (**86x** from
  the dip; MARK 190x; it had 40m/45m `otm_red_squeeze` that morning).
- **The same 5 days, every signal:** held was not better than broke overall (puts reaching 10x after the wait:
  held 13.5% vs broke 29.9%). Only `otm_red_squeeze` looked better when it held (30–60m: 24% vs 12%; 90–180m:
  21% vs 14%), and that is one falling-market put episode.

### All signals

| period | timeframe | held | value: buy now | value: wait 3 & held | held − now (95% CI by expiry) | 25x now → held | doubled during the wait |
|---|---|---|---|---|---|---|---|
| to 16 Sep | 5–20m | 35% | 0.85 | 0.98 | **+0.13 [+0.09, +0.17]** | 2.06% → 2.15% | 4% |
| to 16 Sep | 30–60m | 34% | 0.90 | 1.06 | **+0.16 [+0.11, +0.22]** | 1.91% → 1.78% | 7% |
| to 16 Sep | 90–180m | 32% | 0.92 | 1.09 | **+0.17 [+0.10, +0.25]** | 1.82% → 1.63% | 9% |
| to 16 Sep | 4h–1d | 30% | 1.00 | 1.04 | +0.04 [−0.11, +0.20] | 1.94% → 0.97% | 12% |
| 17 Sep–24 Oct | 5–20m | 37% | 1.20 | 1.20 | +0.00 [−0.06, +0.08] | 3.51% → 3.30% | 6% |
| 17 Sep–24 Oct | 30–60m | 33% | 1.01 | 1.14 | +0.12 [−0.06, +0.30] | 2.64% → 2.47% | 10% |
| 17 Sep–24 Oct | 90–180m | 35% | 1.19 | 1.23 | +0.02 [−0.33, +0.30] | 3.08% → 1.88% | 14% |
| 17 Sep–24 Oct | 4h–1d | 29% | 1.03 | 1.02 | −0.02 [−0.62, +0.27] | 2.35% → 0.40% | 19% |

### Out of sample, by signal (held − now, 95% CI)

| signal | 5–20m | 30–60m | 90–180m |
|---|---|---|---|
| **otm_wall** | **+0.20 [+0.08, +0.34]** | **+0.36 [+0.19, +0.54]** | **+0.18 [+0.04, +0.30]** |
| green_stairs | −0.03 [−0.15, +0.10] | +0.31 [−0.21, +0.76] | −0.37 [−0.81, −0.04] |
| otm_red_squeeze | −0.08 [−0.24, +0.08] | −0.20 [−0.50, +0.10] | +0.71 [−0.32, +1.68] |
| red_squeeze | −0.05 [−0.18, +0.07] | −0.22 [−0.39, −0.03] | +0.24 [−0.21, +0.74] |

### In plain English

- **Your trades fit your rule.** The 1:20 is a textbook case. The 1:100 held "for some strikes", as you said.
- **The parts of the claim that hold up everywhere:**
  - Higher timeframes "don't wait": the share of signals whose premium already doubled during the wait rises
    with timeframe (4% → 12% before, 6% → 19% since).
  - On 4h–1d, waiting for the hold never helps.
  - Waiting does not find more 25x winners in any period (the 25x rate after a hold is the same or lower).
- **The part that does not hold up out of sample:** "the hold is more reliable" for every signal. Before 16 Sep,
  waiting for the hold kept ₹13–17 more per ₹100 on 5m–3h, including 5–20m, which was never tested before. Since
  17 Sep that gain is gone for all signals together (+0.00 / +0.12 / +0.02, every CI includes 0). In a month of
  crashes, the strikes that dipped through the SL and then exploded did better (5–20m "broke" 1.59 vs held 1.20).
- **`otm_wall` is the exception, and it is now confirmed out of sample.** It was the one positive signal in every
  timeframe in §3. Since 17 Sep it is positive again in all three groups, with CIs above zero (+0.18 to +0.36 per
  ₹1 staked). That is a real, repeatable improvement: **for `otm_wall`, wait 3 candles and buy only if the SL
  held.**
- **For `otm_red_squeeze`, your signal in both trades, the hold helped only on 90m–3h** (+0.71, CI includes 0).
  On 5m–1h it hurt slightly. So far, the two wins are the rule working in a crash, not evidence that it works
  in general.
- **Bounds:**
  - Values are MARK, so peaks are upper bounds.
  - 38 expiries out of sample dominated by three put crashes (4–8, 18 and 22–24 Oct).
  - One SL definition (the trigger candle's low) and one wait (3 candles).
