# Premium base: the parabola of higher lows (tested 2026-10-09)

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
