# Setups: the current playbook (as of 2026-10-07)

One page: every setup that has survived testing, its exact rule, its numbers, its caveats and its forward
status. Anything not on this page is either falsified or untested; see `README.md` for the full record.
**Rules are applied strictly. A setup is not stretched to fit a day it did not match.**

Conventions:
- **"25x" etc.** means P(the option's peak after entry ≥ 25× entry).
- **EV per unit** = P × T − 1 − 0.0826: a resting sell at the target, a total loss otherwise, after the
  8.26% round trip.
- **Break-even hit rates:** 2x 54.1% · 5x 21.7% · 10x 10.8% · **25x 4.33%** · 50x 2.17% · **100x 1.08%** ·
  200x 0.54% · 500x 0.22%.
- **MARK** uses the stored mark candles. **TRADED** fills at the first traded print after the signal
  and takes the traded high after it.

---

## Setup 1: PICTURE-CALL with R5 (best simple rule): BUY

*Verified 2026-10-07 by an independent recomputation from raw inputs. See "Verification" below.*

**Rule** (BTC and ETH only):
1. Take one of his four signals on a **CALL** (premium 2–20)...
2. ...on a **picture day**: quiet weekend (≤ 30th pct) AND low-vol week (rv7 ≤ 30th pct) AND price held
   near its 7-day high (dd7 ≥ 60th pct). Causal percentiles vs the previous 365 days, known at the
   PREVIOUS day's close.
3. ...and **R5 not vetoing**: the daily chart is NOT in a clean 20-day uptrend (efficiency > 0.35 with a
   positive 20d return).

**How often it fires** (2024-03 → 2026-09, 2.5 years):
- 3,581 signal events, which bunch heavily: a median of 19 on a qualifying day, up to 65. Of these,
  2,790 later "activate" on mark.
- **126 qualifying asset-days ≈ 50 a year for BTC + ETH together, about one a week across both**
  (about one every two weeks per asset).
- **36 episodes** (runs of qualifying days; median 3 days, max 11) ≈ 14 a year for both assets, about one
  every 7 weeks per asset. 14 of the 36 had at least one 25x event.

**Headline: TRADED, implementable.** Buy at the first traded 1h close after the signal, whether or not it
later activates. Exit at the target on traded highs. 3,581 events:

| target | 2x | 5x | 10x | 25x | 50x | **100x** | 200x | 500x |
|---|---|---|---|---|---|---|---|---|
| hit rate | 42.8% | 21.2% | 15.0% | **10.6%** | 8.1% | **5.1%** | 2.1% | 1.4% |
| EV / unit | −0.23 | −0.02 | +0.41 | **+1.56** | +2.97 | **+3.99** | +3.02 | (+5.97, tail noise) |

**Stop-entry convention (MARK)**, for comparison with older results. Enter only if the mark breaks the
signal bar's high (an unfilled stop costs nothing), so the rows are the 2,790 activated events:

| target | 2x | 5x | 10x | 25x | 50x | 100x | 200x | 500x |
|---|---|---|---|---|---|---|---|---|
| hit rate | 44.9% | 22.5% | 17.0% | 12.8% | 10.2% | 6.5% | 2.4% | 1.8% |
| EV / unit | −0.18 | +0.04 | +0.62 | +2.12 | +4.00 | +5.42 | +3.78 | — |

- **25x MARK week-block CI:** [4.0, 22.4]%.
- **By year (MARK, 25x):** 2024 11.5% · 2025 5.3% · 2026 21.1%.
- **First signal of each day only:** 15.5%. 75 of 126 days have several signals closing at the same
  moment; ties are averaged, and the range across tie-breaks is 14.3–17.1%.
- **First signal of each episode only:** 11.1% (36 trades).

**The R4 variant and R5 without the veto.**
- **Variant PICTURE-CALL & not R5 & R4 up:** about half the events, MARK 25x 14.8%. More slicing of the
  same episodes, so not adopted. The forward log decides.
- **Without R5** (plain PICTURE-CALL, implementable traded 25x 9.3%, 100x +3.04): picture days that R5
  WOULD veto score 5.3% at 25x, and by year 0% / ~12% / 0%. That is why R5 stays.

**Why it is believed:**
- **Leave-one-episode-out** keeps the picture 25x rate at 8.6–12.0%.
- **Puts on the same days are null** (≈3.8–4.0% vs 3.9%), consistent with "quiet + held up resolves UP".
- **Both halves of the picture matter:** neither 1.9% · held only ≈4.4–4.7% · quiet only ≈7.0–7.4% ·
  both ≈11.1–11.4%.
- **Traded outcomes match the exchange** exactly on 15 refetched rows. 0.2% of rows never traded.

**Why it is NOT proven:**
- **36 episodes**, 14 with a 25x hit, so CIs are wide;
- the depth behind traded prints at 50x–100x is unmeasured, and ~10% of fills are below half the mark
  (excluding fills under 0.2× mark leaves 25x unchanged);
- it swings by year.

**Exits:**
- **EV peaks at 100x**, and 200x is lower on both conventions.
- **Streak risk (traded):** at 100x (5.1% hits) P(20 trades without a hit) ≈ 35%. At 25x (10.6%) it is ≈ 11%.
- **A split exit** (half at 25x, half at 100x) averages ≈ +2.8/unit with fewer long droughts.

**Forward status** (`python paper_log.py --report`, "forward, traded prices, by target"; the forward log
fills at the first traded close, like the headline table): PICTURE-CALL 104 rows / 4 expiries, 0 hits at
25x, best ~17x traded; PICTURE-CALL & not R5 62 rows, 0 hits. That is about **2 independent episodes**
(BTC 3–5 Oct, ETH 3–6 Oct). With ~14 of 36 backtest episodes producing a 25x, 0 of 2 is unremarkable.
**Too early to judge.**

## Setup 2: A+ (R4 + R5): BUY, the previous standard

**Rule:** his signals, CALL when the 4h always-in is UP (PUT when DOWN), AND R5 not vetoing. His
containment rule applies to the squeeze signals.

**Backtest** (calls, premium 2–20, MARK):

| target | 25x | 50x | **100x** | 200x |
|---|---|---|---|---|
| hit rate | 8.3% | 5.7% | 3.3% | 0.8% |
| EV / unit | +0.99 | +1.77 | **+2.18** | +0.61 |

- **About 59/week.**
- **Older traded-price figure** (all premiums, 142 weeks): 25x 6.01% vs 4.33% break-even, +0.42/trade.
- **Decaying by year:** 11.2% → 7.6% → 6.2%.
- **Superseded by Setup 1** in the backtest: higher hit rate, a third of the trades. Kept in the forward
  log for comparison. **Forward so far:** 36 TAKE rows over 5 expiries, 0% traded 25x (mark said 11%,
  because of mark-below-tradeable entries).

## Setup 3: Quiet-day STRADDLE SELL: SELL

- **Rule:** on days the walk-forward quiet-day model (`quiet_wf.py`) ranks in its quietest ~30%, sell the
  ATM straddle with **1–3 days** to expiry. **NOT on high-IV days.**
- **Backtest** (held-out Dec 2025 – Sep 2026, net of the bid haircut and fees, % of spot per straddle):
  +0.164% vs −0.279% on other days, CI [+0.094, +0.786], P = 0.005. Worst −17.7% vs −21.5%.
- **Do not stack with high IV:** quiet & high IV −0.84% vs quiet & not high +0.29%.
- **Caveats:**
  - only ~9 months held out;
  - same-day (≤ 1d) straddles show nothing;
  - entry at 00:00 UTC, which is the worst hour (re-test at 08:00 UTC is pending).
- **Margin:** Delta's ~5% initial margin vs a −20% worst trade. **Size by the tail, not the margin.**
- **Not yet in the forward log.**

## Supporting rules (not setups on their own)

- **13:30–14:30 IST premium cliff:** Deribit's 08:00 UTC settlement, confirmed. Strangles lose ~10%
  (1 DTE) / ~3% (2 DTE) in that hour on traded prices. **Buy after 14:30 IST, sell before 13:30.**
- **Wait-and-hold** (30m–3h signals, 3 candles above the trigger low): cuts losses (~₹80 → ~₹97 per ₹100)
  but is about break-even after cost. **A discipline filter, not a profit source.**
- **Never average the melting side** (mode 1): −0.37 vs strong side −0.02.
- **Strike ladder:**
  - after a sharp move, the immediate expiry runs out of cheap strikes on that side;
  - new strikes listed mid-move are already repriced;
  - ETH's ladder reaches further than BTC's.

  The cheap strike must exist BEFORE the move.
- **Skip quiet days as a futures/option BUYER:** the skip-30% edge is +24.4pp, with no direction.

## Strict check: was 7 Oct 2026 one of these setups? **No.**

| asset | picture day? | R5 | R4 at the break | verdict |
|---|---|---|---|---|
| BTC | no | clean uptrend (veto) | unclear by 11:30 IST; up before the drop | no Setup 1; Setup 2 puts = skip (4h not down) |
| ETH | **yes** | clean uptrend → **R5 vetoes** | unclear by 11:30 IST; up before the drop | **no Setup 1** (vetoed); Setup 2 = skip |

- **The winning trades were PUTS** (BTC P-84200 ~36x, ETH puts ~190–270x on traded prints). No setup
  covers them: Setup 1 is call-only, and Setup 2 required a 4h downtrend.
- **The rules were right not to take ETH calls** on its picture day, because ETH fell.
- **Recorded as a miss, not a reason to change a rule.**


## Verification (2026-10-07)

An independent agent recomputed every number in this file from raw inputs (`events.parquet`, perp and
spot candles, Delta traded candles), with its own code, before reading the author's scripts.

**What reproduced.**
- **Setup 1:** counts, mark rates, CI, by-year, first-of-episode and the stop-entry traded table, all
  exact.
- **Setup 2:** 25x/50x, weekly count, yearly decay.
- **Setup 3:** reproduced by running `quiet_wf.py` only, so this is not an independent check. The
  high-IV interaction is unchecked.

**What was corrected.**
- **Traded rates were selected on future mark activation.** That inflated 25x from 10.6% to 13.6%. The
  headline is now the implementable all-rows table (`picture_traded_all.py`).
- **The mark target matrix** now uses the same rows and the same stop-entry convention as the y_* labels
  (`target_matrix.py`). Setup 2's 100x/200x went from 3.5/1.1% to 3.3/0.8%.
- **The first-of-day rate depends on tie-breaking:** 15.5% (14.3–17.1), not 16.3%.
- **Wording:** "one a month per asset" became one every ~7 weeks per asset, and episodes are 36 for
  Setup 1 (43 counts all picture days).

**No look-ahead** was found in the picture, R4 or R5 inputs.
