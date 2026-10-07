# Hug → melt → break → hurdle: his points 1–3 (2026-10-07)

## His three points

1. **The hug.** After a downmove, price holds in a tight range just above the line (7 Oct: 8h above the
   1h support), "waiting to break it". That should signal an impending multibagger. How long it takes
   is the open question.
2. **Hurdles.** A peak made by a sharp move into prices not traded for a while, followed by an even
   sharper reversal: a quick touch. Hurdles act as support/resistance, as the place to book out of a
   trap, and as option targets. Re-entry rule: price going beyond the hurdle.
3. **The melt.** 1:50 moves are deliberate. The break waits until the attacking side's premiums have
   melted: the option writers have collected enough decay, and the buyers can buy cheap. The move then
   runs to where the cheap options pay. A push made while premiums are rich is thwarted and leaves a
   hurdle.

## Scripts and setup

`hurdles.py` (detector), `hug_melt.py` (tests A, B, D), with follow-ups run inline for C and the
exact-picture check. Inputs: 1h BTC+ETH candles since 2024, confirmed lines from `levels.all_levels`,
4h ATM straddle IV (1–3d tenor) from `data/short_straddles.parquet`, and 1:100 requirements from
`data/dashreq`.

## Definitions

- **Hug:** a close on the holding side of a confirmed line, within 0.5 ATR of it.
- **Episode:** consecutive hug bars that follow the line actually being hugged. It ends in a BREAK
  (close > 0.25 ATR beyond that line) or a BOUNCE (close > 1 ATR away).
- **Move in:** distance from the far-side extreme of the previous 6 bars, in ATR.

## Results: 3,005 episodes (1,723 breaks, 1,282 bounces)

| claim | result |
|---|---|
| **A. The hug is a countdown** (break hazard rises with hug length) | After a move in, P(break in the next 2 bars) is 0.38 in the first hour and **0.39** after 3h+: flat. Without a move in, 0.40 → 0.47 (CIs overlap). **Not a countdown.** |
| **His exact picture:** a sharp move in (≥ 2.5 ATR) then a LONG hug (≥ 6h) | P(break) **0.64 [0.49, 0.77]**, n = 39, vs 0.51 for sharp-in + 1–5h hugs and 0.57 overall. **Right direction, too few cases to confirm.** |
| **B. The break comes after the melt** (falling implied vol during the hug) | Hugging 3h+: IV down > 8% gives 0.35; flat 0.36; **IV up 0.47** [0.40, 0.54]. If anything breaks come when premiums are RISING, not melting. **Not supported.** |
| **C. The move is sized to the 1:50/1:100 target** | The 24h move after a break, divided by the 1:100 requirement on the immediate expiry: median 0.26; 11% reach it. Equal-width bins fall smoothly (10.4 → 7.6 → 5.2 → 3.5%), with no bump at 1. **No sign that moves stop at the option target.** |
| **D. Rich premiums get thwarted** (fewer breaks when IV is high at the hug start) | P(break) is 0.567 / 0.574 / 0.580 across low / mid / high IV. **No effect.** |

## ⚠ CORRECTION 2026-10-07 (same day): the hurdle "carry" result below was a measurement artefact

**What was wrong.** `hurdle_test.py` measured carry from the LEVEL, in ATR taken when the level FORMED.
A trader enters at the BREAK CLOSE, so that is where carry has to be measured from. Two things inflated
the gap:
- **Overshoot at the break.** Hurdle breaks already overshoot the level more at the break close (0.75 vs
  0.58 ATR), so part of the "carry" was already in the entry price.
- **Shrinking ATR on ordinary peaks.** Their ATR had shrunk to 0.72× by the time they broke, vs 0.97–1.02×
  for hurdles. That made their moves look smaller in formation-ATR units.

**Re-measured from the break close**, with ATR at the break and a day-block bootstrap:

| data | P(max move ≥ 3 ATR within 2h): hurdle vs ordinary peak | CI of difference | median max move |
|---|---|---|---|
| BTC 1m | 66.9% vs 65.5% | [−3.1, +5.8] | 0.42% vs 0.36% |
| ETH 1m | 66.0% vs 66.2% | [−4.2, +4.0] | 0.64% vs 0.61% |
| BTC 5m | 42.5% vs 41.3% | [−7.2, +9.0] | 0.48% vs 0.50% |
| ETH 5m | 43.7% vs 39.0% | [−2.4, +11.3] | 0.73% vs 0.65% |

**No difference.** The options test, which IS measured from the actual entry, agrees once it is
resampled by day:
- **Hold 2h:** hurdle +0.040, CI [−0.016, +0.103]. Vs ordinary peaks the difference CI is [−0.020, +0.183].
- **Trap exit + re-entry:** hurdle +0.076, CI [+0.017, +0.146], but this rule was chosen as the best of
  six exit variants on the same data. The same rule on ordinary-peak breaks gives +0.024, and the
  difference CI is [−0.054, +0.152]. It is flat in 2026.

**Verdict.**
- **That hurdles add to a break is NOT established.**
- What survives, weakly: his trade management on level breaks (exit when price closes back through the
  broken level, re-enter on a fresh close beyond). It is selected after the fact, so it is a candidate
  for the forward log, not a rule.

Found by the cross-study review of 2026-10-07 (`docs/ML/REVIEW_2026-10-07.md`) and re-verified
independently.

---

### Original (superseded) section follows

## Hurdles (point 2): TESTED, the re-entry rule holds (`hurdle_test.py`)

**His follow-up:** sharp moves and hurdles live on 1–5 minute charts. Trade off higher timeframes for
reliability, but use the low timeframes for targets and trap exits. So hurdles are detected on 1m
TRADED perp candles (`data/btc_1m.parquet` and `data/eth_1m.parquet`, `fetch_eth_1m.py <SYMBOL>`)
and on 5m MARK candles.

**Definitions.**
- **HURDLE:** an exposed extreme (beyond everything of the last 12h on 1m, 24h on 5m) with a sharp move
  in (≥ 2 ATR within M bars), a reversal of ≥ 0.7× that move within M bars, and ≤ 3 bars near it.
- **CONTROL:** the same kind of exposed extreme that rolled over SLOWLY (reversal < 0.5× the move in),
  i.e. an ordinary swing high or low.
- **Window:** levels are used only after they are known (bar i+M) and followed for 3 days. The robust
  version keeps only levels that price had LEFT by ≥ 1.5 ATR when known, so every retest is a genuine
  return.

**Results** (hurdle vs control, robust version):

| data | rejected when price returns | after a CLOSE beyond it: carries ≥ 3 ATR in 2h | median carry | holds in both halves? |
|---|---|---|---|---|
| BTC 1m traded (2024-01 → 2026-10) | 30.5% vs 26.5% (CI −0.1 to +8.0) | **75.2% vs 62.4%** (+7.7 to +17.9) | 6.4 vs 4.4 ATR | yes / yes |
| ETH 1m traded (2024-02 → 2026-09) | 31.6% vs 26.5% (+1.1 to +8.7) | **76.3% vs 65.3%** (+6.7 to +15.8) | 6.5 vs 4.3 ATR | yes / yes |
| BTC 5m mark | 34.8% vs 32.6% (n.s.) | **54.6% vs 34.6%** (+10.6 to +28.8) | 3.3 vs 2.4 ATR | yes / yes |
| ETH 5m mark | 35.9% vs 31.7% (n.s.) | **55.9% vs 35.8%** (+11.5 to +28.8) | 3.4 vs 2.2 ATR | yes / yes |

**Reading.**
- **His re-entry rule is the robust finding.** A close beyond a hurdle carries further and more often
  than a close beyond an ordinary peak: +8 to +20 points on every dataset, in both halves of time.
- **As resistance, hurdles are only slightly stronger than ordinary peaks.** That is significant on
  ETH 1m only, marginal on BTC 1m, and not significant on 5m.
- **So a hurdle is better read as a TRIGGER than a wall.** If price can get back through the level
  that was violently rejected, the move tends to run.
- **The 1m numbers are larger than the 5m ones.** That matches his point that these structures live
  on the lowest timeframes, and traded prices keep the wicks that mark prices smooth away.

### In options, with his exits and re-entry (`hurdle_options.py`, 2026-10-07)

**Setup.** 4,751 hurdle breaks and 1,098 ordinary-peak breaks on 1m TRADED BTC/ETH, 2024 → Oct 2026.
- **Entry:** 5 minutes after the break close, buy the ~0.75% OTM option in the break direction, on the
  nearest expiry with ≥ 3h left (median 17h).
- **Prices:** 5m MARK option candles; dust marks (< 0.03% of spot) excluded.
- **Cost:** 8.26% round trip per entry. Returns are per unit staked.

| exit rule | hurdle breaks | ordinary-peak breaks |
|---|---|---|
| hold 2h | +0.040 [−0.004, +0.085] | −0.047 |
| hold 6h | +0.045 [−0.014, +0.112] | −0.107 |
| hold to expiry | +0.059 [−0.031, +0.153] | −0.118 |
| TARGET at the next older hurdle ≥ 3 ATR ahead | −0.032 | −0.116 |
| target + TRAP exit (1m close back through by > 0.25 ATR) | −0.037 | −0.048 |
| target + trap + RE-ENTRY (fresh close beyond; ≤ 2 re-entries) | +0.014 | −0.007 |
| **trap exit + RE-ENTRY, no target** | **+0.076 [+0.037, +0.121]** | +0.024 (n.s.) |

The best rule, broken down:

| split | per unit staked |
|---|---|
| BTC | +0.061 [+0.012, +0.122] |
| ETH | +0.093 [+0.033, +0.163] |
| first half | +0.097 |
| second half | +0.056 |
| 2024 | +0.075 |
| 2025 | +0.126 |
| **2026** | **−0.001 (flat)** |

- **Re-entries:** 1.3 per trade on average.
- **Per-trade distribution:** median −0.19, 90th percentile +0.56, 99th +5.7, max +40.
- **Without the best 1% of trades the mean is −0.03.**

**Reading.**
- His trap exit plus re-entry is the only version clearly positive after costs, and beats the
  ordinary-peak control.
- **Booking at a hurdle target HURTS.** It cuts the right tail that pays for everything, as in
  `de-signals-no-highprob-setup`.
- Thin, tail-driven, MARK-priced, and flat in 2026. **Paper-trade it forward before sizing.**

**Still open:**
- higher-resolution option prices (1m traded) for the same events 

## Bugs found while testing (fixed)

- **The break candle went missing.** v1 took the nearest line at each bar. A candle that broke the
  hugged line by more than 2 ATR dropped it from view, and the episode was filed as a "bounce" off a
  lower line. The 7 Oct 06:30 break and the strongest breaks generally were misfiled, which biased A/B
  against his idea.
- **The "move in" window was wrong.** It was net travel over 10 bars, which on 7 Oct reached back past
  the 21:00 drop to the earlier rise.

## Reading

**The setup is real but not a timer.** His picture (sharp move in, long hug) breaks more often than
average (0.64 vs 0.57), but there are only 39 cases on 1h BTC/ETH, and a hug's length alone doesn't
make a break more imminent.

**The option-market mechanism in point 3 shows no footprint in prices:**
- implied vol is not falling before breaks;
- moves don't stop at the option target;
- rich premiums don't block breaks.

This matches earlier results: whatever the crowd anticipates is already priced (`SMART_MONEY.md` §6),
and Delta's book is too small to steer BTC. The melt may be real on Deribit's book, which we can't
see per strike.
