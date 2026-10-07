# Discretionary journal — scorecard

Source: `github.com/tejasd90/market_observatios` (`cryptos.md`). No timestamps in
the text; **commit times supply them**, which is what makes scoring possible at all.
`DECISION_DOCUMENT` has long flagged that whether Tejas's discretionary reads
carry alpha is unanswerable because nothing was recorded. It is now answerable.

**First scoring 2026-09-28. Re-scored 2026-09-30: nine entries, seven resolved. Re-scored 2026-10-03 01:15 IST: eleven entries. Re-scored 2026-10-07 09:45 IST: fourteen entries** (prices: BTC/ETH perp hourly, `data/spot_candles`).

| # | committed (IST) | the call | outcome |
|---|---|---|---|
| 1 | 09-23 12:42 | hourly double top; "further upmove unlikely for a couple of days"; BTC/SOL cleaner than ETH | **CORRECT.** Max upmove over the next 2 days: **BTC +0.16%, ETH +0.27%, SOL +0.48%**. All three then fell 1.3–2.6% |
| 2 | 09-23 12:45 | 70% conviction BTC stays >80K, ETH >2500 | **holding** (lows 82,650 / 2,626.6) |
| 3 | 09-24 14:29 | "markets going down, could breach levels for tomorrow's monthly expiry" | **WRONG.** BTC +0.37%, ETH +0.90% into the 25th; no expiry breach |
| 4 | 09-27 17:09 | ETH 12h symmetric wedge; "personally I am biased for an upside breakout" | **WRONG so far.** ETH −2.24%; high only +0.29% above the call |
| 5 | 09-28 09:28 | crypto tied to gold; 82,800 crucial for BTC, break → 80k | **SPLIT.** Level broke (low 82,500) but 80k never came; recovered to 83,788 |
| 6 | 09-28 11:27 | hammer + inverted hammer → range, 1:100 unlikely | **CORRECT.** BTC -0.77%/+1.67%, ETH -0.56%/+3.70% |
| 7 | 09-28 11:38 | no Aug-17-19-style upside blast in the near future | **CORRECT so far.** Aug ref was BTC +26.8% / ETH +36.4% in a week (biggest days +7.3% / +17.5%). Since: BTC max +1.80%, ETH +2.26%, biggest daily move 0.69% |
| 8 | 09-30 09:36 | wedge; explosive break on/before the 2 Oct weekly expiry; side unknown, slight bearish bias | **STRUCTURE CORRECT, BIAS WRONG.** BTC broke UP out of the 1h triangle before expiry: 83,173 → high 87,224 (+4.9%) at 17:30 IST 2 Oct. The low (82,908) came 3h after the call and never broke down. Fastest hour +1.34% (09:30 IST 2 Oct). C-BTC-87000-021026 went ~10 → ~300 on mark (his own screenshot). It was a grind of steadily higher 4h closes more than an "explosion", but it was enough to multiply options. ETH +4.1% to 2,778. The slight bearish bias was wrong |
| 9 | 09-30 16:51 | long-term wedge resolving at **100k** (he confirms 199k was a typo), upside continuation bias | pending; still unfalsifiable as written ("further upside move, or some reversal" covers both outcomes) |
| 10 | 10-02 08:49 | market inching up with parabola-like support on 4h+; "bias for a breakout in coming days" | **WRONG.** BTC peaked 86,965 on Sun-night/Mon 5 Oct (06:30 IST), below the 22–23 Sep high (87,376) and 2 Oct (87,224), and then broke DOWN on 7 Oct. He says so himself in entry 14 |
| 11 | 10-02 18:53 | 6h BTC: the "hairy" last candle makes a breakout hard; "if the candle closes like this", triple top and the breakout is no longer imminent | **CORRECT (resolved 7 Oct).** The 6h candle (17:30–23:30 IST) printed 87,224 and closed near **84,012**, much weaker than "like this". That is a third failure at ~87.2–87.4k (22 Sep, 23 Sep, 2 Oct). BTC low 83,842 (−3.3% from the call), ETH 2,649 (−4.3%). It is a call about ABSENCE again, written while his own morning bias (entry 10) pointed the other way. Through 7 Oct no close above ~87.4k: a fourth failure at 86,965 (5 Oct), then the breakdown |
| 12 | 10-04 19:03 (Sat) | clean higher-timeframe patterns for an upside breakout, esp. SOL; "this week (or max next week) 90k BTC broken"; flags the weekend-trap risk himself | **pending to 18 Oct, looking wrong.** BTC 84.1k on 7 Oct, needs +7%. The weekend-trap caveat was the right half: the Sun-night push to 86,965 was the high |
| 13 | 10-05 09:46 | two wedges, the lower-timeframe one "also kind of a flag" | no side and no horizon, so **unscorable**. His 12h triangle's lower line was broken on 7 Oct |
| 14 | 10-07 09:31 | 1h rising support (from 18 Sep) broken this morning; the 87–88k push was a weekend trap, seen when Monday 05:30 turned into a range; recovered losses on the break; "follow-through till maybe 80–78k, question is till when" | the break is **observed, not called**: it came at the 06:30 IST close, 85.5k → 83.5k low (−2.3%). The 80–78k forecast has **no horizon**, so it is pending. Add one ("by Friday") to make it scoreable |

**Score note 2026-10-02.** The "3/3 on no move coming, 0/3 on direction" summary
(commit 9eb6dca) counts entry 7 as a hit, but entry 7 has no horizon ("near
future") and the table itself says "correct so far". It cannot be resolved yet.
Honest count on absence calls (1, 6, 7): **2/2 resolved + 1 pending**. Direction
calls (3, 4, 5): **0 hits** — 3 wrong, 5 split (level broke, target missed), 4
"wrong so far" with no horizon, so pending. The asymmetry
is the same; the counts are smaller. Entries 2, 8 and 9 remain pending (8's
deadline is today, 2 Oct). Ask for a horizon on every entry so this does not recur.

## The gold claim, measured

| window | gold–BTC corr | gold–ETH corr | BTC beta | ETH beta |
|---|---:|---:|---:|---:|
| full (162d) | 0.535 | 0.540 | 0.88 | 1.23 |
| last 90d | 0.556 | 0.566 | 0.96 | 1.35 |
| last 30d | 0.519 | 0.516 | 1.08 | 1.15 |

**Correlation is real (~0.52–0.57)** and "cryptos move more than gold" holds for
ETH (beta 1.15–1.35), roughly 1:1 for BTC. But "have tied themselves" implies a
recent development and the current 30d correlation is at the **34th percentile** —
slightly BELOW its own median. The link is long-standing, not tightening. (XAUT
data begins 2026-04-18, so earlier comparison is impossible.)

**Score note 2026-10-03.** Adding 8, 10, 11 by statement type:

- **Absence / "no move" calls (1, 6, 7, 11): 3/3 resolved + 1 pending.** Entry 11 resolved within hours, so it is provisional but the conditional was met and the consequence followed.
- **Timing/structure without a side (8): 1/1.** The break came before the stated deadline, and it was big enough for a 30x option on the right side.
- **Direction / bias (3, 4, 5, 8-bias, 10): 0 clean hits.** 3 wrong, 5 split, 8's bias wrong, 4 and 10 pending.

The asymmetry from the models holds again: he reads WHETHER and WHEN well, and WHICH WAY poorly. Entries 10→11 are the
best example yet. The morning bias said breakout, and the evening read of the actual candle said
no. The candle read was right within hours. When the two disagree, the structure read has the record.

**What entry 8's type maps to:** "explosion before expiry, side unknown" is a long STRANGLE. On 2 Oct the
call side paid ~30x while the put side expired worthless, so a strangle profits if the hit is big enough.
"No move coming" maps to SELLING premium (OPTION_SELLING.md §2b). Both use the part of his read
that scores and leave out the part that doesn't.


**Score note 2026-10-07.** Absence calls (1, 6, 7, 11): **3/3 resolved + 1 pending**, unchanged, and 11 is now
firmly resolved. Timing without a side (8): 1/1. Direction/bias (3, 4, 5, 8-bias, 10, 12, 14): **0 hits**. Wrong:
3, 8-bias, 10. Split: 5. Pending: 4, 12 (looking wrong), 14 (no horizon). The pattern holds again over a week where
the bias said up twice (10, 12) and price broke down.

His own post-mortem in 14 is the most useful line in the journal: *trap often happens during weekends; realised it
when Monday 05:30 turned straight into a range*. That is a testable rule: do weekend breakouts that fail to extend
in Monday's first IST session revert more often than weekday ones? Logged as a candidate test, not yet run.

## The pattern worth tracking

**Structural calls score; biased calls do not.**

Entry 1 names a mechanism (hourly double top), makes a specific claim (no further
upmove), states a horizon (a couple of days), and applies it to three instruments.
Realised max upside was +0.16%. That is not luck-shaped.

Entries 3 and 4 are the misses and both carry wishful framing — *"huge trades
would be possible"*, *"Personally I am biased for an upside breakout"*. He flags
his own bias in 4 and that is the one that fails.

Four resolved calls settles nothing statistically. But the split BY TYPE OF
STATEMENT is the thing to track: if it survives ~50 entries the rule writes
itself — trade the structural reads, log the biased ones without sizing them.

## How to keep scoring

Entries need no format change. What would sharpen scoring at zero cost:
a horizon ("next 2 days"), a falsifier ("wrong if BTC closes above X"), and a
confidence number — entry 2 already does all three and is the easiest to score.


## Checking entry 9 against our own line detector (2026-09-30)

He corrected the target to 100k. `levels.py` on BTC daily, independently of his chart:

**No wedge is visible to the detector.** Exactly ONE live trendline exists -- a
rising support anchored 2026-06-25, 97 days old, 3 touches, currently at **66,654**
with spot **24.6% above it**. There is NO live resistance trendline: all 53
descending lines ever found are already broken, most recently 2025-04-12. No
ceiling means no convergence.

That does not refute his chart -- he may be reading a weekly structure, or one our
swing detection misses -- but the code gives it no support.

**What the detector does find is a coincidence worth recording:**

| level | distance | rejections |
|---:|---:|---:|
| 91,216 | +9.8% | **5** |
| 94,144 | +13.4% | 3 |
| **101,093** | **+21.7%** | 3 |

His corrected 100k target lands almost exactly on a 3-rejection level at 101,093,
found by swing clustering with no knowledge of his chart. **The wedge geometry may
be wrong while the destination is right.**

The nearer obstacle is 91,216 with 5 rejections -- the strongest overhead structure
by touch count, and anything travelling to 100k passes through it first.

**Caution carried from AUDIT_2026-09-30.md**, relevant to entry 8: even if the
wedge is real and breaks explosively, TRADING the break is late -- the break
arrives after the option is already running 62-74% of the time.
