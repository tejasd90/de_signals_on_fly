# DECISION DOCUMENT — de_signals_on_fly
**As of 2026-09-12.** What has been tested, what survived, what to do next.
Supersedes the scattered conclusions in HANDOFF.md and ML_SPEC.md.

> **Superseded in part 2026-10-02.** This document is the 2026-09-12 state and is
> kept as written. Three things changed after it: (1) funding carry, recommended in
> §6.3, was tested and **falsified** (FINDINGS §31–33); (2) the BTC+ETH AUC 0.7024
> was not like-for-like — BTC+ETH-only training gives **0.6942**, all-129-symbol
> training gives **0.7319** on the same BTC+ETH test rows (FINDINGS §34); (3) "nothing
> else remains" is no longer true — see README.md "State as of 2026-10-02",
> TOP10.md and PLAN.md for what survives now (cross-sectional low-vol book, the
> when-not-to-trade gate, R4, two option-selling rules, wait-and-hold).

---

## 1. One-paragraph summary

Across two months of work we built and honestly tested nine distinct strategy
hypotheses on 2.7 years of Delta Exchange data (220 perpetual futures, 2.5M
hourly bars; 146k option-chain files). **Eight are falsified with proper
controls.** One — a short-horizon futures classifier — is genuinely predictive
(AUC 0.70, well calibrated) but cannot be shown to make money after costs. The
single consistently profitable effect found is short-side altcoin decay, which
is a directional regime bet, not a skill. Every negative result is limited by
the same thing: **2.7 years is ~142 independent weeks**, which is too few to
prove a small edge.

---

## 2. Scoreboard

| # | Hypothesis | Result | Evidence |
|---|---|---|---|
| 1 | Four hand-built option signals carry information | **FALSIFIED** | pattern-shape features inert under permutation importance; `otm_wall` ranks nothing and is 39% of rows |
| 2 | Better encoding rescues pattern shape | **FALSIFIED** | ~140 mechanical shape features; spot 0.021, option 0.012 precision vs 0.019 context-only |
| 3 | Chain surface beats context | **CONFIRMED** | P@15% recall 0.030 vs 0.019; 21 features match what 159 achieve |
| 4 | The edge is just "buy the cheapest" (D-01) | **REJECTED** | cheapness alone LOSES (-0.042) and hits 25x less often than random |
| 5 | Option timing is predictable (Brooks, arm 4) | **FALSIFIED** | 105 spot features, AUC 0.5286, p=0.150, bootstrap CI [0.487,0.567] contains 0.5 |
| 6 | Leverage can create edge | **FALSIFIED (arithmetic)** | driftless-walk null gives EV exactly 0 at every leverage; measured +0.0000 |
| 7 | Short-horizon futures direction is predictable | **REAL BUT UNPROVEN** | AUC 0.7024 BTC+ETH at 24h, calibration near-perfect; best EV +0.0209/trade, CI [-0.033,+0.065]. **Superseded 2026-10-02:** 0.7024 is not like-for-like; on identical BTC+ETH test rows it is 0.6942 trained on BTC+ETH alone, 0.7319 trained on all 129 symbols — see FINDINGS §34 |
| 8 | Volatility compression predicts big moves | **FALSIFIED** | forward move flat at ~2.3 ATR at every compression level; coiled days move LESS in absolute terms |
| 9 | Breakout + pyramiding + trailing SL | **FALSIFIED** | every config loses, CIs entirely negative; pyramiding doubles the loss; ATH is the worst filter; re-entry makes it worse |

---

## 3. The five findings worth keeping

**3.1 Contract selection is predictable; timing is not.**
Within-episode AUC **0.9469** (which strike to buy) vs between-episode **0.5745**
(whether today matters). The model picks excellent contracts on days when nothing
happens. This is the sharpest single result in the project.

**3.2 Leverage is a cost multiplier, not a return multiplier.**
Fees are charged on notional, so cost on margin = L x fee. At 200x a 0.10% round
trip costs **20% of your margin**. Survival table (random entry, 72h hold):
99% -> 4x · 95% -> 7x · 90% -> 10x · 80% -> 13x · 50% -> 33x.

**3.3 Small profit targets have negative expectancy; the edge is all tail.**
2x: -0.069 · 5x: +0.021 · 25x: +0.306. Taking quick profits inverts the edge.

**3.4 Adding to winners is punished in this market.**
Pyramiding drops win rate 33.6% -> 19.9%. Each add raises average entry, pulling
the 2N stop closer in percentage terms, so ordinary pullbacks stop the whole
stack. Confirmed on both long and short sides.

**3.5 More data fixed calibration — the method was starved, not wrong.**
With 3 symbols the model said 67% when reality was 55%. With 129 symbols it says
70% and reality is 71%. That is the strongest evidence that this approach is
sound and data-limited.

---

## 4. The recurring trap (read before any new analysis)

Every promising result in this project died to one of these. All were hit at
least once:

1. **Label leakage.** A column named exactly `label` defeats a `label_` prefix
   filter -> AUC 1.000. Always assert the feature list.
2. **Ignoring `_w`.** Negatives are downsampled; every statistic — including
   trade counts, daily top-N selection and equity curves — must use weights.
   Unweighted per-episode rates inflate 6.5x (8.56% vs 1.31%).
3. **Float32 timestamps.** `_ts_hours * 3600` in float32 loses precision and
   silently matches ~6% of rows.
4. **Treating overlapping samples as independent.** 99,404 entries were really
   142 weekly blocks. Always block-bootstrap on TIME.
5. **Counting unresolved trades as breakeven.** Conditional on NOT reaching the
   target, terminal return is biased negative. This faked a +0.075 edge.
6. **Mixing horizons.** A fill test over one window with a miss-value from
   another is the same bug in a new costume.
7. **Mark prices are not trade prices.** A mark touching 25x is not a fill.
8. **Missing the matched control.** The short-breakdown "edge" (+0.2201, CI
   entirely positive) evaporated against random short entry (+0.4960). **A
   positive, significant result still means nothing without the right control.**

9. **k-means cluster indices are not stable identifiers.** They differ between
   runs, seeds and subsamples, so "cluster 2" in one script is a different group
   in the next. Carrying one by index produced a filter worth dEV +0.066 at
   P=0.007 that became +0.0005 once the cluster was identified by a *property*
   measured on the training half. Name clusters by what they are, never by index.

10. **Per-trade EV is not the objective; profit per unit time is.** Four regime
    filters raised EV per trade and every one of them lost on profit per week by
    discarding opportunities. Always report both, and bootstrap the pair.

---

## 5. What actually remains

**The futures classifier.** BTC+ETH, 24h horizon, AUC 0.7024, calibrated. EV
rises monotonically with selectivity — a genuine-edge signature. Best cell
+0.0209/trade at top-1% confidence (~1 signal/day), CI [-0.033,+0.065].
Not provable on 142 weeks.

**Short altcoin decay.** Positive every year (2024 +0.244 · 2025 +0.168 ·
2026 +0.106) but it is beta to "alts bleed against BTC", inverts in an alt
season, and is not significant on weekly blocks.

**Nothing else.**

**Superseded 2026-10-02:** "Nothing else" no longer holds. Later work found the
cross-sectional low-vol perp book (+59.4%/yr, Sharpe 2.48, P=0.0003 — PLAN.md
Tier 1), the when-not-to-trade gate (WHEN_NOT_TO_TRADE.md), R4 (TOP10 row 3), two
conditional option-selling rules (OPTION_SELLING.md) and wait-and-hold as a loss
cutter (TF_REPEAT_HOLD.md). The short-altcoin-decay item above is the same effect
that the low-vol book's short leg harvests (117% of its price return). The
classifier's AUC is corrected in §2 row 7.

---

## 6. Recommended next actions, in order

1. **Paper-trade the futures classifier forward.** BTC+ETH, 24h, top-1% of
   signals, 4-10x, limit orders only. Every week adds a genuinely new
   independent week — the only thing that still adds evidence. Zero capital.
2. **Keep a conviction journal.** Timestamp + instrument + reasoning, logged
   BEFORE the outcome. In six months this becomes a testable dataset about
   whether Tejas's discretionary reads carry alpha. Right now that question is
   unanswerable because nothing was recorded. The Aug 15 coil call was correct
   and there is no record of it.
3. **Investigate funding/basis harvesting.** Not tested at all, and it is the
   one place in crypto where a persistent, structural, non-predictive edge is
   known to exist (cash-and-carry: long spot, short perp, collect funding). It
   earns from flow, not from forecasting. Requires funding-rate history, which
   the API serves and we have not pulled.
   **Superseded 2026-10-02:** done and **falsified**. Delta India cannot hedge
   most perps on-venue, and the cross-sectional carry spread is adverse selection
   plus short-alt beta, not a carry edge (FINDINGS §31–33; `xsec.py` carry signal
   −5.8%/yr). Do not pursue.
4. **Stop searching for chart-pattern edges.** Nine hypotheses, eight dead. The
   marginal value of a tenth variant on this dataset is low.

---

## 7. Honest note on what this project proved

It did not find a tradeable edge. It did build something rarer: a pipeline where
a wrong answer gets caught. Eight of nine hypotheses were killed by controls that
most retail backtesting never applies — matched nulls, purged walk-forward,
weighted statistics, block bootstrap on time. Several of them looked like
winners first.

The measured hit rates here (2.8-4.7% at 25x) are lower than the remembered ones
(15-20%), and the difference is entirely accounting: oracle strike selection,
perfect exits, unweighted sampling, synthetic fixtures. That gap IS the finding.

---

# 8. OPEN QUESTIONS — swept and answered (2026-09-13)

## 8.1 ML_SPEC §0 PLAN, marked WAITING-TEJAS

| # | Question | Answer |
|---|---|---|
| **P1** | Random-entry null baseline (D-40) | **CLOSED.** `disc_final`'s `signal` column is 100% NULL — it already IS the random-entry population, so `make_random.py` was never needed. Matched null measures **-0.03 to -0.06** in every year and every type x tte cell: correctly negative. |
| **P2** | Merged-event ratio: max / nearest / mean (§3 of 08-open-questions) | **CLOSED: use MEAN.** `max` embeds an oracle worth up to **+3.38** expectancy (K=20) that is not implementable — buying K strikes costs K premiums, so the realised return is the mean. Ceiling check: max over ALL strikes with no model gives **52.8% at 25x**, so the max operator does the work, not the signal. **K=1 is optimal** (+1.708/unit vs +1.124 at K=5). |
| **P3** | D-30 — mode 1 (1/2/3) as first ML target? | **CLOSED: NO.** Mode classification is a *timing* task, and timing is precisely what was falsified: between-episode AUC **0.5745**, and arm 4 on the actionable target gave **p=0.150** with bootstrap CI [0.487, 0.567] containing 0.5. Mode 1/2/3 needs exactly the ability shown not to exist. Its ~10x base rate does not help if the signal is absent. |
| **P4** | D-13 — tradeability floor (min volume, min premium) | **NOW ANSWERABLE.** *Premium:* edge survives a floor up to **2.0** (exp +0.167 at 25x, tte>=24h); below ~0.25 the label is dominated by sub-tick artifacts. *Volume:* it exists after all — the plain option symbol (no `MARK:` prefix) returns traded candles with real volume; on 50 model-selected instruments the median had trades in **77.7%** of hourly bars and **0 of 50** never traded. |

## 8.2 ML_SPEC §8 open items

| ID | Answer |
|---|---|
| **O-01** positive episode count | **1,973 episodes**; positives 1,919 / 1,635 / 1,021 / 605 / 314 at 5/10/25/50/100x. Comfortably trainable; the binding limit is *independent weeks*, not episodes. |
| **O-02** real-vs-shuffled ratio | **SUPERSEDED.** The shuffle test targeted the retired `label_scan.js`. Its job is done better by the matched null (type x tte x year) and by the driftless-walk null, which reproduced **EV exactly +0.0000** at every leverage — an exact analytic control rather than a simulated one. |
| **O-03** tradeability thresholds | See P4. |
| **O-04** `k`, `N`, "large M" | **SUPERSEDED by D-25.** The payoff multiple is the threshold; no ATR multiplier to choose. |
| **O-05** does Delta serve historical IV? **(marked urgent)** | **ANSWERED, and it splits.** **OI: YES** — the `OI:` symbol prefix on `/v2/history/candles` returns OHLC of the open-interest level, and it works on *expired* options (189 hourly candles through the 2026-08-21 expiry). **IV: NO** — `IV:`, `MARKIV:`, `MARK_IV:`, `VOL:`, `MARKVOL:`, `IMPLIED:` and others all return 0 rows; `mark_vol` exists only in the live `/v2/tickers` snapshot. **So D-21's ticking clock applies to IV only. OI was never lost and can be backfilled today.** |
| **O-06** merged-event max | Same as P2 — use mean. |
| **O-07** no real backfill had been run | **CLOSED.** Real measured numbers now exist throughout; the synthetic-era figures (20% at 10x, the flat 15/15/16/17/17% matrix) are superseded by measured 2.82%/2.92% at 25x and best precision 4.7%. |

## 8.3 ../08-open-questions.md

| § | Answer |
|---|---|
| **§1** thresholds are guesses (`OTM_SIGNAL_THRESHOLD=10000`) | **MOOT.** The discovery pipeline is signal-free and threshold-free — it scans every contract, so nothing is discarded at generation. The concern (real edge sitting on options priced 25-40 would be invisible) does not apply to any number in this document. |
| **§2** `signalValue` may rank nothing | **CONFIRMED, and the cause is identified.** `signalValue` for the three OTM signals is literally `spot / mean(pattern lows)` — i.e. cheapness. Pattern shape is inert under permutation importance even with ~140 mechanical shape features. And cheapness alone **loses** (-0.042, hitting 25x *less often* than random). The doc's own instinct — "the fix would be a different formula, not a different cutoff" — was right. |
| **§3** merged events take the max | Answered: use mean. See P2. |
| **§4** ML deferred | **RUN.** Two of its predictions were correct and worth recording: "80-90% is not reachable" (measured ceiling ~4.7% precision at 25x), and "**better target: expectancy, not win rate**" — which is exactly what the whole futures analysis converged on. Its warning that the real constraint is labels not algorithms was also right, though the binding unit turned out to be independent *weeks* (142), not events. |

## 8.4 BROOKS_FEATURES.md open items

| Item | Answer |
|---|---|
| Which lookback set? | Used {5,10,20,50}. Moot for options — arm 4 falsified there. |
| Is Brooks fractal across timeframes? | **Tested both ways, and the answer is split.** On option-episode timing (hourly) the features are null (p=0.150). On *spot direction* at a 24h horizon the same 105 features reach **AUC 0.68-0.70**, well calibrated. So the concepts do carry signal — on spot direction, not on option timing. |
| Trend-line fitting: swing points vs all bars | **STILL OPEN, genuinely.** `brooks_features.py` uses a rolling-std channel-width proxy, not least-squares on swing points as specified. The only item on this list not actually done as written. |
