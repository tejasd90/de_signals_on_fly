# docs/ML — the research tree

Everything in this directory is about **finding an edge**: labels, features,
models, controls, and the results. It is separate from `../` on purpose —
the docs one level up describe *running the project* (fetching candles,
generating signals, serving viewers) and are operational. These are evidential.

Nothing here is a how-to for the node pipeline. Nothing there is a claim about
whether a strategy makes money.

---

## Read in this order

| # | doc | what it is | trust |
|---|---|---|---|
| 1 | **DECISION_DOCUMENT.md** | **Start here.** Scoreboard of 9 hypotheses (8 falsified), the 5 findings worth keeping, the 10 recurring traps, and every open question swept and answered. Supersedes scattered conclusions elsewhere. | current |
| 2 | **HANDOFF.md** | The reasoning behind decisions that look arbitrary in code, and the traps that cost real time. §3 is the trap list; §4 the method rules. | current, §2 partly superseded by FINDINGS |
| 3 | **FINDINGS.md** | The measured record in 5 parts: options edge → leveraged futures → regimes/unsupervised/clustering → funding carry → neural nets. Every number is out-of-sample. | current |
| 4 | **ML_SPEC.md** | 43 numbered design decisions (D-01…D-41) plus open items O-01…O-07. The reference for *why* a label or split is shaped the way it is. | O-items now closed in DECISION_DOCUMENT §8 |
| 5 | **BROOKS_FEATURES.md** | Spec for the 105 mechanical spot features (arm 4), implemented in `brooks_features.py`. | spec current; arm 4 falsified for *option timing*, alive for *spot direction* |
| 6 | **TUNING_PIPELINE.md** | How to run the python side: `step1_prepare.py` → `step2_baseline.py` → `step3_tune.py`, and how to read the output. | current |
| 0 | **RESULTS_PLAIN.md** | **Plain-English summary of the context study** — what worked, what was disproved, what was never built. Start here if you want the answer without the method. | current |
| 6b | **BROOKS_SPOT.md** | Brooks' setups tested on SPOT by his own trader's equation — 258,402 setups, 220 perps. No edge at any reward multiple. | current |
| 7 | **CONTEXT_PLAN.md** | Grade a signal by the spot price action around it (Brooks structure, not parameters). The D-03 veto reframe. | proposed, not started |
| 8 | **INDIA_PLAN.md** | What happens next: Indian stocks + F&O, with gates and kill criteria. | proposed, not started |

Source material for CONTEXT_PLAN: `../../Brooks/0{0,1,2,3}-*.md` — distilled from
the Brooks trilogy, which supersedes the 2009 book for concepts.

Operational counterpart: `../RUNBOOK.md` carries the end-to-end sequence
(node steps 0-7, python steps 8-10). `../08-open-questions.md` is answered in
DECISION_DOCUMENT §8.3.

---

## The one-paragraph state of play

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
