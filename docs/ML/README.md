# docs/ML — the research tree

Everything in this directory is about **finding an edge**: labels, features,
models, controls, and the results. It is separate from `../` on purpose —
the docs one level up describe *running the project* (fetching candles,
generating signals, serving viewers) and are operational. These are evidential.

Nothing here is a how-to for the node pipeline. Nothing there is a claim about
whether a strategy makes money.

---

## Start here: `SETUPS.md`
The current playbook: every surviving setup with its exact rule, backtest percentages at each target, caveats, forward status, and a strict check of the latest big day.

## Read in this order

| # | doc | what it is | trust |
|---|---|---|---|
| 1 | **DECISION_DOCUMENT.md** | **Start here.** Scoreboard of 9 hypotheses (8 falsified), the 5 findings worth keeping, the 10 recurring traps, and every open question swept and answered. Supersedes scattered conclusions elsewhere. | as of 2026-09-12; §5–6 partly superseded (see its dated notes, and TOP10.md / PLAN.md for later results) |
| 2 | **HANDOFF.md** | The reasoning behind decisions that look arbitrary in code, and the traps that cost real time. §3 is the trap list; §4 the method rules. | current, §2 partly superseded by FINDINGS |
| 3 | **FINDINGS.md** | The measured record in 5 parts: options edge → leveraged futures → regimes/unsupervised/clustering → funding carry → neural nets. Every number is out-of-sample. | current |
| 4 | **ML_SPEC.md** | 43 numbered design decisions (D-01…D-41) plus open items O-01…O-07. The reference for *why* a label or split is shaped the way it is. | O-items now closed in DECISION_DOCUMENT §8 |
| 5 | **BROOKS_FEATURES.md** | Spec for the 105 mechanical spot features (arm 4), implemented in `brooks_features.py`. | spec current; arm 4 falsified for *option timing*, alive for *spot direction* |
| 6 | **TUNING_PIPELINE.md** | How to run the python side: `step1_prepare.py` → `step2_baseline.py` → `step3_tune.py`, and how to read the output. | current |
| 0 | **RESULTS_PLAIN.md** | **Plain-English summary of the context study** — what worked, what was disproved, what was never built. Start here if you want the answer without the method. | current |
| 6b | **BROOKS_SPOT.md** | Brooks' setups tested on SPOT by his own trader's equation — 258,402 setups, 220 perps. No edge at any reward multiple. | current |
| 7 | **CONTEXT_PLAN.md** | Grade a signal by the spot price action around it (Brooks structure, not parameters). The D-03 veto reframe. | proposed, not started |
| 8 | **INDIA_PLAN.md** | What happens next: Indian stocks + F&O, with gates and kill criteria. | proposed, not started |
| 9 | **OPTION_SELLING.md** | The seller's side of everything (2026-10-02). Unconditional selling nets ~0. Selling behind trendline breaks and high-IV straddles survive but halve out of sample. 5% margin vs −20% tail. | current; refreshes with the dashboard loop |
| 10 | **TF_REPEAT_HOLD.md** | Cross-timeframe repeats (mute after a lower-tf multibagger) and wait-and-hold (30m–3h only). Plain-English summary at top. | current; signals frozen at 2026-09-16 |
| 11 | **SMART_MONEY.md** | Smart-money fingerprint (max-pain pull, defended OI walls: null on Delta), equidistant pair (null for multibaggers), the daily 13:30–14:30 IST premium cliff (real, traded), his three modes measured. | current (2026-10-03) |
| 16 | **PREMIUM_BASE.md** | His premium-chart parabola of higher lows (entry 16, 2026-10-09): FALSIFIED with no tte/timeframe/cheapness assumptions (v3): 5m-4h, 1.35M moments, 25x 1.89% vs 1.98% matched; it fades along the chain as he said, but the flatter neighbours do no worse. |
| 15 | **SETUPS.md** | **The playbook** (start here): Setup 1 PICTURE-CALL + R5 (implementable traded: 25x 10.6%, 100x 5.1% EV +3.99; independently verified), Setup 2 A+ (superseded), Setup 3 quiet-day straddle sell; supporting rules; strict check of 7 Oct. |
| 14 | **PICTURE_CALLS.md** | **The lead:** quiet-before-the-storm picture × his call signals — 25x 12.1% vs 4.3% on TRADED prices, survives leave-one-episode-out, puts null. Forward-log next. |
| 13 | **REVIEW_2026-10-07.md** | Cross-study review: insights, ranked combinations (quiet picture × his call signals is the lead), mis-tested intuitions, bug list with status. |
| 12 | **HUG_MELT_HURDLE.md** | His points 1–3 (2026-10-07): the hug before a break (not a countdown; his exact picture 0.64 vs 0.57, n=39), the premium-melt mechanism (no footprint), hurdles: the carry result was a measurement artefact (CORRECTED same day). Hurdles add nothing measurable over ordinary peaks; his trap-exit + re-entry management is a weak, post-hoc candidate. |

Source material for CONTEXT_PLAN: `../../Brooks/0{0,1,2,3}-*.md` — distilled from
the Brooks trilogy, which supersedes the 2009 book for concepts.

Operational counterpart: `../RUNBOOK.md` carries the end-to-end sequence
(node steps 0-7, python steps 8-10). `../08-open-questions.md` is answered in
DECISION_DOCUMENT §8.3.

---

## State as of 2026-10-02

What currently survives, each with its own source doc:

1. **Cross-sectional low-vol perp book** (PLAN.md Tier 1, `xsec2.py` rerun
   2026-10-02): +59.4%/yr, Sharpe 2.48, maxDD −18.2%, P=0.0003, 207 names incl.
   22 delisted. Taker + 30bps: +50.8%, Sharpe 2.13. 117% of the price return is
   the short leg (short high-vol alts). The only result with a real equity curve.
2. **When not to trade** (WHEN_NOT_TO_TRADE.md): sit out the 30% quietest days —
   avoids 40.9% of dead days, misses 17.3% of good ones, +23.5pp, both assets. No
   direction (AUC 0.524).
3. **R4 — agree with the 4h trend** (TOP10 row 3): 5.96% vs 4.33% break-even.
4. **Option selling, two conditional rules** (OPTION_SELLING.md): sell behind a
   trendline break (+0.07% of spot out of sample) and sell high-IV straddles
   (+0.17% out of sample). Both halve out of sample. Unconditional selling nets ~0.
   Size by the −12 to −20% tail, never by Delta's margin.
5. **Wait-and-hold on 30m–3h signals** (TF_REPEAT_HOLD.md): cuts the loss from
   ~₹80 to ~₹97–101 per ₹100. It is a discipline filter, not a profit source. The
   cross-timeframe repeat rule is NOT supported.
6. **Break geometry on puts** (TOP10 row 6, P=0.011; 0.043 out of sample in 2026).

Withdrawn or qualified since 2026-09-14: funding carry (FINDINGS §33, falsified),
the price-action score (AUDIT_2026-09-30 §1, retracted), and the old-line /
wedge / break-day level results (AUDIT §2–3: mostly same-day, the break usually
arrives after the move).

## The one-paragraph state of play

**Superseded 2026-10-02:** the paragraph below is the 2026-09-12 state. "Eight
falsified" is no longer the whole count, and the "AUC 0.70 on BTC+ETH" figure is
the uncorrected one: like-for-like, BTC+ETH-only training gives 0.6942, and
training on all 129 symbols gives 0.7319 on the same BTC+ETH test rows (FINDINGS
§34). See "State as of 2026-10-02" above.

Nine strategy hypotheses were built and tested on 2.7 years of Delta Exchange
data with matched nulls, purged walk-forward, weighted statistics and block
bootstrap on time. **Eight are falsified.** One — a short-horizon futures
direction classifier, AUC 0.70 on BTC+ETH at 24h, well calibrated — is genuinely
predictive but cannot be shown profitable after costs. The binding constraint on
every result is the same: **2.7 years is ~142 independent weeks**, with a
cross-sectional N_eff of 5.8 across 129 perps, which is too few to prove a small
edge. INDIA_PLAN.md exists to attack exactly that constraint.

## The three results that survive

1. **Contract selection is predictable; timing is not.** Within-episode AUC
   0.9469 (which strike), between-episode 0.5745 (whether today matters).
2. **Leverage is a cost multiplier, not a return multiplier.** Fees are charged
   on notional, so cost on margin = L x fee.
3. **The edge is all tail.** Small profit targets have negative expectancy;
   every high-win-rate configuration loses.

## Before running any new analysis

Read DECISION_DOCUMENT §4. Every promising result in this project died to one of
those ten traps, and all ten were hit at least once. The two that recur most:
a column named exactly `label` defeating a `label_` prefix filter (AUC 1.000),
and **a positive, significant result with no matched control** — the short
breakdown "edge" of +0.2201 with a CI entirely above zero evaporated when random
short entry scored +0.4960.
