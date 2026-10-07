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

**Not yet tested:**
- what a close beyond a hurdle pays in OPTIONS (it needs 1–5m option candles around each event, which
  only exist for recent days);
- hurdles as trap-exit points for an existing position.

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
