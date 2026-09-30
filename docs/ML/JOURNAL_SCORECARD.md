# Discretionary journal — scorecard

Source: `github.com/tejasd90/market_observatios` (`cryptos.md`). No timestamps in
the text; **commit times supply them**, which is what makes scoring possible at all.
`DECISION_DOCUMENT` has long flagged that whether Tejas's discretionary reads
carry alpha is unanswerable because nothing was recorded. It is now answerable.

**First scoring 2026-09-28. Re-scored 2026-09-30: nine entries, seven resolved.**

| # | committed (IST) | the call | outcome |
|---|---|---|---|
| 1 | 09-23 12:42 | hourly double top; "further upmove unlikely for a couple of days"; BTC/SOL cleaner than ETH | **CORRECT.** Max upmove over the next 2 days: **BTC +0.16%, ETH +0.27%, SOL +0.48%**. All three then fell 1.3–2.6% |
| 2 | 09-23 12:45 | 70% conviction BTC stays >80K, ETH >2500 | **holding** (lows 82,650 / 2,626.6) |
| 3 | 09-24 14:29 | "markets going down, could breach levels for tomorrow's monthly expiry" | **WRONG.** BTC +0.37%, ETH +0.90% into the 25th; no expiry breach |
| 4 | 09-27 17:09 | ETH 12h symmetric wedge; "personally I am biased for an upside breakout" | **WRONG so far.** ETH −2.24%; high only +0.29% above the call |
| 5 | 09-28 09:28 | crypto tied to gold; 82,800 crucial for BTC, break → 80k | **SPLIT.** Level broke (low 82,500) but 80k never came; recovered to 83,788 |
| 6 | 09-28 11:27 | hammer + inverted hammer → range, 1:100 unlikely | **CORRECT.** BTC -0.77%/+1.67%, ETH -0.56%/+3.70% |
| 7 | 09-28 11:38 | no Aug-17-19-style upside blast in the near future | **CORRECT so far.** Aug ref was BTC +26.8% / ETH +36.4% in a week (biggest days +7.3% / +17.5%). Since: BTC max +1.80%, ETH +2.26%, biggest daily move 0.69% |
| 8 | 09-30 09:36 | wedge; explosive break on/before the 2 Oct weekly expiry; side unknown, slight bearish bias | **PENDING**, deadline Friday |
| 9 | 09-30 16:51 | long-term wedge resolving at **100k** (he confirms 199k was a typo), upside continuation bias | pending; still unfalsifiable as written ("further upside move, or some reversal" covers both outcomes) |

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
