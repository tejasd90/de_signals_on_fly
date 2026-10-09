# Premium base: the parabola of higher lows (tested 2026-10-09)

## v4: the RISING parabola only, no decay required (`premium_base4.py`, `premium_base4_eval.py`)

His correction to v3: only the rising parabola matters, and setups where the falling (decay) side is not
visible must not be dropped. **Rising parabola, in words:** the latest dips form a run of ≥ 3
higher lows, and the run curves upward (a quadratic through it opens upward; "accelerating" also
records the stricter "last step up bigger than the first").

- **No decay filter.** Decay is only a matching cell and a reported slice.
- **Same as v3:** every timeframe 5m/15m/1h/4h, any time to expiry, any strike, checked the moment a new
  higher low is confirmed.
- **Control:** the same moment without a rising parabola.
- **Rows:** 913,231 pattern, 2.49M control (BTC + ETH, settled expiries 2024-01 → 2026-10-08).

| target | rising parabola | none (A) | none (B, also matched on recovery) |
|---|---|---|---|
| 5x | 5.90% | 5.97% | 6.04% |
| 10x | 2.27% | 2.34% | 2.33% |
| 25x | 0.66% | 0.71% | 0.69% |
| 100x | 0.11% | 0.12% | 0.11% |

- **25x difference CI:** A [−0.1, −0.0]pp, B [−0.1, +0.0]pp.
- **Every slice is level or slightly worse:** each timeframe, calls/puts, each year, each asset, every
  time to expiry, moneyness, decay depth, accelerating or not, run length 3 / 4–5 / 6+.
- **Decay depth matters on its own** (25x 2.1% when the bottom is ≤ 2% of the earlier high vs 0.07% when
  it is > 60%), but the parabola adds nothing within any depth.
- **His examples fire.** P-BTC-81000-091026 at 7 Oct 15:30 IST (106 → 8.9x) and P-80000 at 14:30
  (55 → 8.1x). So do many that went nowhere; for example the 2 Oct expiry's 80500/81000/87000 strikes fire
  3–4 times each in late September for 1.0–1.5x.
- **Chain:** neighbours further OTM still show it 80 / 75 / 70% of the time (+1 / +2 / +3 strikes). The
  cheaper neighbour again does a little better (25x 0.68% vs 0.42% at +3).

**Verdict (v4): falsified.** A rising parabola of higher lows on the premium chart does not change the
odds versus the same option at the same moment without one.

---

## v3 (bowl after a decay; superseded by v4 above)

### v3: the idea only, with no extra assumptions (`premium_base3.py`, `premium_base3_eval.py`)

He corrected v2 (below): it assumed a time to expiry (≥ 12h), one timeframe (1h, 48 bars) and an
absolute cheapness (≤ 0.25% of spot, which keeps mostly far-OTM strikes, exactly where he says the shape
goes flat). v3 drops all three, and also v2's 1.5× rise and 3× cap.

**Parabola, in simple English:** look only at the dips (each candle low that is the lowest within 2 candles
either side). The dips trace a bowl: they come down, flatten at a bottom, and every later dip stays above
the bottom, curving up.
- **bowl:** a U-shaped curve through the dips, ≥ 2 dips after the bottom, all higher than it;
- **arm:** the rising side only, ≥ 3 higher lows in a row with each step bigger than the last.

**Decay toward zero:** the bottom ≤ 15% of the contract's highest close before the window.

**When it is checked:** two candles after a new dip prints (the first moment you could see it), with the
close still above that dip.

**Where it runs:** 5m, 15m, 1h and 4h, window 48 candles (4h / 12h / 2d / 8d), any time to expiry, any
strike, all settled BTC + ETH expiries 2024-01 → 2026-10-08.

**Control:** the same moment (a new dip just confirmed, decayed as far) without the shape. Both are
sampled at most once per window per contract. Matched within timeframe × time to expiry × moneyness ×
decay depth (A), and also on how far the premium has already recovered from its bottom (B).
**Rows:** 491,705 pattern, 854,843 control.

| target | parabola | no parabola (A) | no parabola (B) | break-even |
|---|---|---|---|---|
| 5x | 10.96% | 11.31% | 11.61% | 21.7% |
| 10x | 5.20% | 5.33% | 5.38% | 10.8% |
| 25x | 1.89% | 1.98% | 1.98% | 4.33% |
| 100x | 0.34% | 0.41% | 0.39% | 1.08% |

- **25x difference, week-block CI:** A [−0.2, +0.0]pp; B [−0.2, +0.0]pp. **The shape adds nothing**
  (if anything, slightly less).
- **Every timeframe is level:** 25x 5m 1.91 vs 2.06 · 15m 1.85 vs 1.82 · 1h 1.93 vs 1.98 · 4h 1.61 vs 2.00.
- **Level everywhere else too:** calls, puts, each year, each asset, every time-to-expiry bucket and every
  moneyness bucket. The last 6 hours to expiry are 0.90 vs 0.73, and still five times below break-even.
- **Bowl vs rising arm:** bowl 1.91 vs 2.02; rising arm 2.17 vs 1.92 (the best cut, 18k rows, still half
  of break-even).

**His chain point, tested.** For every bar showing the shape, the next 3 strikes further OTM at the same
bar:

| further OTM | also shows the shape | premium vs shown strike | 25x shown | 25x neighbour |
|---|---|---|---|---|
| +1 | 72% | 0.80× | 1.44% | 1.60% |
| +2 | 67% | 0.63× | 1.56% | 1.88% |
| +3 | 62% | 0.51× | 1.41% | 1.84% |

- **He is right that it fades along the chain:** the share of neighbours that still show it drops with
  each step.
- **The flatter, cheaper neighbours do slightly better** than the strike that shows it clearly. That is
  the general cheapness effect.
- **When the next strike is flat**, the clear strike does a little better (25x 1.82% vs 1.29% when the
  neighbour shows it too). Still far below break-even.

**Verdict (v3): falsified on every timeframe, every time to expiry and every strike.** Seeing the bowl
does not change the odds compared with the same option at the same moment without it. It catches the
eye because the winners had it, but so did most of the losers.

---

## v2 (superseded by v3 above: it had the tte/timeframe/cheapness assumptions)

His idea (journal entry 16, with charts in `img/2026-10/journal_2026-10-09_img2..4`): on the OPTION's own
chart, the premium decays toward zero, then **builds a parabola of higher lows** ("holding up", slowly
rising), then explodes. Examples: P-BTC-80500/81000-091026 (8 Oct), C-BTC-87000-021026 (2 Oct).
He stressed that the parabola is the part that "catches the eye immediately".

## Plain-English answer

**The parabola was tested as the thing that matters, and it does not help.** The comparison was cheap
options that had decayed just as far, with the same time to expiry and the same distance from spot,
but were **still making new lows** (no parabola). Those went 25x **more** often (4.6%) than the ones
with a parabola (2.2%). Puts with a parabola were level with puts without one (3.8% vs 3.3%, CI spans
zero, and 2026 reverses). The 8 Oct put is a genuine example (it fires at 03:30 IST at 74.5 and later
made 8.8x), but over 2.5 years the shape fires about 20 times a week, and most of those fade.

This fits what was found before: cheapness and time-to-expiry carry the information. The look of the
premium chart (entry 16's "holding", like the premium-series signals in `PREMIUM_SIGNALS.md`) does not
add to it. A base that is "holding up" means the option is already less cheap.

## Detector (`premium_base.py`)

1h MARK option candles, BTC + ETH, expiries 2024-01 → 2026-10-09. Causal at bar i:
- **swing lows:** lowest low within ±2 bars, so known 2 bars later;
- **decay / cheap bottom:** the lowest swing low in the last 48 bars is ≤ 15% of the highest close of
  the 10 days before the window, AND ≤ 0.25% of spot;
- **parabola:** ≥ 3 swing lows in the window, a quadratic through them is convex (U-shaped), and ≥ 2
  lows after the bottom, each ≥ 1.5× the bottom;
- **holding, not yet exploded:** close ≥ the last swing low and ≤ 3× the bottom;
- ≥ 12h to settlement; a contract can fire again after 24 bars.
- **Control:** the first bar where the same cheap-bottom and time conditions hold but the premium is
  still at its low (no lows after the bottom), one per contract.

v1 demanded strictly rising lows and missed his 80500P (lows 44 → 31 → 56 → 52). v2 matches his
picture: it fires on the 80500P, and the late 81000P trigger is dropped by the 3× cap. **Not caught:**
the 87000C flat base (single digits for hours, with no rising lows).

## Results (`premium_base_eval.py`)

Controls are reweighted to the pattern's mix of time-to-expiry × moneyness × cheapness cells (46 cells).
Outcome: max MARK high after the bar to settlement ÷ the close at the bar. EV = P·T − 1 − 0.0826.

| target | parabola (2,882) | no parabola, matched (10,423) | EV parabola | EV control |
|---|---|---|---|---|
| 5x | 12.0% | 15.9% | −0.48 | −0.29 |
| 10x | 5.9% | 9.7% | −0.49 | −0.11 |
| 25x | 2.2% | 4.6% | −0.53 | +0.07 |
| 100x | 0.49% | 1.36% | −0.60 | +0.28 |

- **Week-block bootstrap of the difference:** 10x [−8.1, +0.1]pp; 25x [−5.7, +0.2]pp (P(parabola
  better) ≈ 0.05).
- **Calls:** 25x 1.2% vs 5.9%. **Puts:** 3.8% vs 3.3%, CI [−2.3, +3.3]pp; by year 3.4/3.8, 5.8/1.9,
  1.8/4.5 (2024/2025/2026).
- **By year (all):** the parabola is behind in 2024 and 2026, and ahead only in 2025 (25x 3.0% vs 1.9%).
- **First event per contract only:** 25x 2.3% vs 4.6%. A tighter base (close ≤ 2× bottom), ≥ 3 higher
  lows, or ≥ 48h left all give 2.1–2.3%. **No variant rescues it.**
- **Traded-price check was not run.** MARK is already below break-even (4.33%), and traded fills have
  only ever been worse than MARK on this kind of entry.

## Verdict

**Falsified as a buy trigger.** Recorded with his 8 Oct example as a true positive that does not
generalise. The fact that "still making new lows" beats "holding up" agrees with the cheapness
finding: buy when it is cheapest, not after it has started to recover.
