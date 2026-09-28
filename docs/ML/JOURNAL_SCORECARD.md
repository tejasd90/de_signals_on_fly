# Discretionary journal — scorecard

Source: `github.com/tejasd90/market_observatios` (`cryptos.md`). No timestamps in
the text; **commit times supply them**, which is what makes scoring possible at all.
`DECISION_DOCUMENT` has long flagged that whether Tejas's discretionary reads
carry alpha is unanswerable because nothing was recorded. It is now answerable.

**First scoring: 2026-09-28. Six entries, four resolved.**

| # | committed (IST) | the call | outcome |
|---|---|---|---|
| 1 | 09-23 12:42 | hourly double top; "further upmove unlikely for a couple of days"; BTC/SOL cleaner than ETH | **CORRECT.** Max upmove over the next 2 days: **BTC +0.16%, ETH +0.27%, SOL +0.48%**. All three then fell 1.3–2.6% |
| 2 | 09-23 12:45 | 70% conviction BTC stays >80K, ETH >2500 | **holding** (lows 82,650 / 2,626.6) |
| 3 | 09-24 14:29 | "markets going down, could breach levels for tomorrow's monthly expiry" | **WRONG.** BTC +0.37%, ETH +0.90% into the 25th; no expiry breach |
| 4 | 09-27 17:09 | ETH 12h symmetric wedge; "personally I am biased for an upside breakout" | **WRONG so far.** ETH −2.24%; high only +0.29% above the call |
| 5 | 09-28 09:28 | crypto tied to gold; 82,800 crucial for BTC, break → 80k | level broke (low 82,650), recovered; too early |
| 6 | 09-28 11:27 | hammer + inverted hammer → range, 1:100 unlikely | unresolved |

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
