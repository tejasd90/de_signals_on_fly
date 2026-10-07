# The lead: quiet-before-the-storm picture × his CALL signals (2026-10-07)

Scripts `picture_calls.py` (mark, robustness) and `picture_traded.py` (traded prices).

## Definitions

- **Picture day:** quiet weekend AND low-vol week AND price held near its 7-day high. Causal
  percentiles known at the previous close (`bigmoves.py`): wkend ≤ 0.3, rv7 ≤ 0.3, dd7 ≥ 0.6.
- **Signals:** his four signals, CALLS, activated, premium 2–20, triggered on that day. One row per
  event (strikes averaged). From `events.parquet`, settled expiries 2024 → 3 Oct 2026.

## Results

| measure | picture days | other days | difference (week-block bootstrap) |
|---|---|---|---|
| 25x, MARK | **11.4%** (137 days, 43 episodes) | 3.5% | CI [+1.0, +15.6] pp, P = 0.013 |
| 25x, MARK, all premiums | 9.0% | 2.4% | CI [+0.9, +12.6] pp |
| **25x, TRADED** (filled at the first traded close after the signal; target on traded highs) | **12.1%** | 4.3% | CI [+0.7, +16.0] pp |
| PUTS on the same days (direction control) | 4.0% | 3.9% | null |

- **Fills:** median first traded fill / mark = 0.95, and every picture-day row traded after its signal.
- **Not carried by one episode.** Leave-one-episode-out keeps it at 8.3–12.4%. Without the 2 best
  episodes it is 9.0%. 14 of 43 episodes had a 25x hit.
- **Both halves of the picture matter, roughly multiplicatively.**

  | calls, 25x rate | not held up | held up |
  |---|---|---|
  | not quiet | 1.9% | 4.7% |
  | quiet | 7.4% | **11.4%** |

- **Against break-even:** 4.33% at a 25x target. The traded rate is about 2.8× that.

## Caveats

- **Depth:** the size behind the traded prints is unmeasured.
- **Sample:** effective sample is ~43 episodes in 2.7 years, with hits concentrated in about 14.
- **Interaction with R4/R5:** R5 (skip clean uptrends) vetoes many of these days. That interaction
  is still to be measured.
- **Earlier hint:** the picture was first found on spot moves (`SMART_MONEY.md` §5: 2.45x, all 6 hits
  UP). This is its first test on his own signals.

## Next

Add it to the forward log as its own rule ("PICTURE-CALL": picture day + his call signal), so it
accumulates evidence before any sizing.

## Should R5 step aside on picture days? NO (`r5_picture.py`, 2026-10-07)

**Population:** 47,290 call events over 132 weeks. Rates are 25x on MARK, with week-block CIs.

| cell | 25x | EV/unit | events/week |
|---|---|---|---|
| current A+ (R4 up, R5 not vetoing) | 8.31% [4.6, 12.8] | +1.00 | 59 |
| R5-vetoed days that are PICTURE days | 5.24% [0, 15] | +0.23 | 5 |
| R5-vetoed, not picture | 2.07% | −0.56 | 17 |
| A+ with R5 lifted on picture days | 8.07% | +0.93 | 65 |
| picture, any R4/R5 | 11.08% (traded 12.06%) | +1.69 | 27 |
| **picture with R5 KEEPING its veto** | **12.81% (traded 13.56%)** [4.2, 22.6] | **+2.12** | 21 |
| picture & not R5 & R4 up | 14.83% (traded 16.45%) [2.8, 26.7] | +2.63 | 12 |

- **R5-vetoed picture days by year:** 0% / 13.4% / 0%. All of it is May 2025, so 2 Oct 2026 was the
  exception. **Keep R5.**
- **The picture is a better standalone filter than A+:** 11% vs 8%, with half the trades.
- **Picture + R5 by year:** 11.5% (2024), 5.3% (2025), 21.1% (2026). CIs are wide because only about
  43 episodes underlie every cell, and every extra slice is another look at the same episodes.
- **Simplest defensible rule: PICTURE-CALL with R5 keeping its veto.** The forward report shows it as
  "PICTURE-CALL & not R5", next to plain PICTURE-CALL. Whether R4 adds anything is left to the forward
  log.

## Target matrix (`target_matrix.py`, 2026-10-07)

EV per unit = P(peak ≥ T) × T − 1 − 0.0826.

**MARK**

| rule | 2x | 5x | 10x | 25x | 50x | 100x | 200x | 500x |
|---|---|---|---|---|---|---|---|---|
| all calls (n 47,290) | 41.8% / −0.25 | 15.6% / −0.30 | 8.6% / −0.22 | 4.2% / −0.03 | 2.4% / +0.14 | 1.4% / +0.33 | 0.8% / +0.49 | 0.4% / +0.99 |
| A+ (n 7,840) | 50.6 / −0.07 | 22.2 / +0.03 | 14.1 / +0.32 | 8.3 / +0.99 | 5.7 / +1.79 | 3.5 / **+2.38** | 1.1 / +1.17 | 0.3 / +0.47 |
| picture (n 3,616) | 47.3 / −0.14 | 22.9 / +0.06 | 15.3 / +0.45 | 10.7 / +1.59 | 8.4 / +3.13 | 5.7 / **+4.66** | 2.4 / +3.66 | 1.4 / +5.73 |
| picture & not R5 (n 2,790) | 49.5 / −0.09 | 24.0 / +0.12 | 17.0 / +0.62 | 12.5 / +2.03 | 9.9 / +3.86 | 6.9 / **+5.78** | 2.7 / +4.30 | 1.6 / +6.82 |

**TRADED** (picture rows complete; the "all calls" and A+ rows use a sample tilted toward picture days,
so compare rules on MARK)

| rule | 25x | 50x | 100x | 200x |
|---|---|---|---|---|
| picture | 12.1% / +1.93 | 9.0% / +3.39 | 5.5% / **+4.38** | 2.2% / +3.25 |
| picture & not R5 | 13.6% / +2.31 | 10.5% / +4.14 | 6.6% / **+5.48** | 2.6% / +4.19 |

**Reading:**
- EV rises with the target up to **100x**, then drops at 200x for every rule.
- 500x looks highest but rests on ~45 hits from a handful of episodes, so ignore it.
- Small targets (2x) lose for every rule.
- The previous finding "200x ≥ 100x" (TOP10 #14, +4.59 vs +3.17, P = 0.12) does not hold for these rules.

The playbook with forward status is in `SETUPS.md`.
