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

**Rule** (BTC and ETH only):
1. Take one of his four signals on a **CALL** (activated, premium 2–20)...
2. ...on a **picture day**: quiet weekend (≤ 30th pct) AND low-vol week (rv7 ≤ 30th pct) AND price held
   near its 7-day high (dd7 ≥ 60th pct). Causal percentiles vs the previous 365 days, known at the
   PREVIOUS day's close.
3. ...and **R5 not vetoing**: the daily chart is NOT in a clean 20-day uptrend (efficiency > 0.35 with a
   positive 20d return).

**Backtest** (events.parquet, settled expiries 2024 → 3 Oct 2026; 2,790 events ≈ 21/week; TRADED):

| target | 2x | 5x | 10x | 25x | 50x | **100x** | 200x | 500x |
|---|---|---|---|---|---|---|---|---|
| hit rate | 49.9% | 25.7% | 18.6% | 13.6% | 10.5% | **6.6%** | 2.6% | 1.8% |
| EV / unit | −0.09 | +0.20 | +0.78 | +2.31 | +4.14 | **+5.48** | +4.19 | (+7.97, tail noise) |

- **25x on MARK:** 12.8%, week-block CI [4.2, 22.6]%.
- **By year (MARK, 25x):** 2024 11.5% · 2025 5.3% · 2026 21.1%.
- **Variant: PICTURE-CALL & not R5 & R4 up** (≈ 12/week): 25x traded 16.5% [2.8, 26.7]. More slicing of
  the same episodes, so not adopted. The forward log decides whether R4 helps.
- **Without R5** (plain PICTURE-CALL, 27/week): 25x traded 12.1%; 100x +4.38. On picture days that R5
  WOULD veto, 25x is 5.2%, and by year 0% / 13.4% / 0%. That is why R5 stays.

**Why it is believed:**
- **Not carried by one episode:** leave-one-episode-out keeps the picture 25x rate at 8.3–12.4%.
- **Puts on the same days are null** (4.0% vs 3.9%), consistent with "quiet + held up resolves UP".
- **Both halves of the picture matter:** neither 1.9% · held up only 4.7% · quiet only 7.4% · both 11.4%.
- **Fills are real:** first traded fill ≈ 0.95× mark, and every picture-day row traded after the signal.

**Why it is NOT proven:**
- about 43 episodes in 2.7 years, with 25x hits in ~14 of them, so CIs are wide;
- the depth behind traded prints at 50x–100x is unmeasured;
- it swings by year.

**Exits:**
- **EV peaks at 100x and falls at 200x** for this and every rule (an older study on the full signal set
  had 200x ≥ 100x, P = 0.12; not the case here).
- **Streak risk:** at 100x (6.6% hits) P(20 trades without a hit) ≈ 25%. At 25x (13.6%) it is ≈ 5%.
- **A split exit** (half at 25x, half at 100x) averages ≈ +3.9/unit with fewer long droughts.

**Forward status** (`python paper_log.py --report`, "forward, traded prices, by target"):

| | rows | expiries | 25x hits | best traded multiple |
|---|---|---|---|---|
| PICTURE-CALL | 104 | 4 | 0 | ~17x (ETH 4 Oct), ~16x (BTC 4 Oct) |
| PICTURE-CALL & not R5 | 62 | 4 | 0 | — |

These rows are only about 2 independent episodes (BTC 3–5 Oct, ETH 3–6 Oct). With ~1 in 3 backtest
episodes producing a 25x, 0 of 2 is unremarkable. **Too early to judge.**

## Setup 2: A+ (R4 + R5): BUY, the previous standard

**Rule:** his signals, CALL when the 4h always-in is UP (PUT when DOWN), AND R5 not vetoing. His
containment rule applies to the squeeze signals.

**Backtest** (calls, premium 2–20, MARK):

| target | 25x | 50x | **100x** | 200x |
|---|---|---|---|---|
| hit rate | 8.3% | 5.7% | 3.5% | 1.1% |
| EV / unit | +0.99 | +1.79 | **+2.38** | +1.17 |

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
