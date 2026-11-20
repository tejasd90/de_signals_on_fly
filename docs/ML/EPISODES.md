# Episodes: his labelled cases, with the context he read (started 20 Nov 2026)

Each episode is a label: a window where he says the combination of news, price action and signals made a large option
move capturable. His words are kept as given. "Data" is what the stored candles and signals show for the same window.
These are the positives for a context model; the matched non-episodes still have to be built.

## E1. NIFTY / SENSEX calls, entry window 26–30 Oct 2026

**Outcome:** index about 22,750 (28 Oct) to above 25,000 (9 Nov). Calls 5–10% out of the money went 50x–300x on the 5, 9, 12
and 17 Nov expiries.

**News (his, 20 Nov):**
- "Trump losing badly in midterms (which was heavily being predicted) should have been seen as a positive for India (would
  make way for India-favourable long awaited US-India trade deal, and loosening of the US's tough stance on India)."
- "BankNifty is the main driver (it is already way beyond ATH, whereas NIFTY is ~3% below ATH)."
- "The AI stocks crash would mean AI-lagging India would see reinvestment from FIIs."
- "All these combined would trigger a great squeeze in the 10-consecutive red-candle, badly beaten NIFTY."

**Price action (his, with two charts kept locally in `data/shared_charts/2026-11/`):**
- Weekly: support on the rising trendline formed since early 2024.
- Daily: the falling line from August broken, then support taken on it ("not very clean, still technically correct").
- 29 Oct: "the clean bounce after taking support".

**Checked in the index data (`F:\nse\spot`, fetched 20 Nov):**
- "10 consecutive red candles" is WEEKLY, and it is exact: the ten weeks starting 3 Aug to 5 Oct 2026 each closed below
  their open (24,571 → 22,520). Then one green, one red (week of 19 Oct, 22,600), then the week of 26 Oct turned.
- NIFTY all-time high 26,373; BANKNIFTY made a new high in November (64,681) while NIFTY was still about 2% below its own.
- NIFTY daily closes: 23 Oct 22,600 · 26 Oct 22,753 · 28 Oct 22,699 · 29 Oct 22,937 · 30 Oct 23,053 · 6 Nov 25,030.

**Signals (his):** daily-timeframe signals appeared around the bounce; he recalls 29 or 30 Oct, to be confirmed by him.

**Data (`1d` bars, weekly expiries only; the 23 Nov monthly is not collected yet):**

| trigger day | what fired on the daily | best later multiple |
|---|---|---|
| 23 Oct | 3 calls (`otm_red_squeeze`) | 46x (9 Nov expiry) |
| 26 Oct | 8 calls (`otm_red_squeeze` and close-to-close) | 121x (9 Nov), 72x (5 Nov), 14x (3 Nov) |
| 27 Oct | 2 calls, 3 Nov expiry | lost everything |
| 28, 29 Oct | nothing, in either variant or either view of the 15:30–15:40 minutes | |
| 30 Oct | 3 Nov expiry: 3 calls and 13 puts; 5 and 9 Nov: puts only | 52x (a 3 Nov call); puts about 1–3x |
| 2 Nov | calls on 3, 9, 17 Nov (`otm_red_squeeze`, `otm_wall`) | 182x (9 Nov) |

**What he says the lesson is:** he missed the whole context, not one signal. "Market does not repeat things. Think of
these episodes as labelling and think in ML terms."

## What a context model needs (plan, not built)

- **Price-action features, computed causally:** distance to a long rising support line, falling-line break and retest, run of
  red candles, distance from all-time high, BANKNIFTY against NIFTY. Needs the index history (`nse/fetch_spot.js`).
- **Signal features:** firings by timeframe, side and expiry distance in the days before.
- **News / events:** nothing is stored historically. Scheduled events (elections, Fed, RBI, budget) can be put in a calendar;
  his reading of them exists only for the episodes he writes down.
- **Negatives:** days where the same features looked similar and nothing followed. Without them an episode list cannot say
  how often the combination fails.
- **Limit:** a handful of episodes cannot train a model. They can fix the feature definitions (does the code see what he saw
  on those days?), after which the count of look-alike days with no move is the test.
