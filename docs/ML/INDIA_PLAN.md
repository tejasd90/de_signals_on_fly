# INDIA PLAN — Indian stocks + Indian F&O

**Written 2026-09-16.** Extends DECISION_DOCUMENT.md. The crypto work is
data-limited, not method-limited: every result is capped by **142 independent
weeks x N_eff 5.8**, which is why the one surviving hypothesis (futures
direction, AUC 0.70) has CI [-0.033, +0.065]. This plan spends the new data on
*power*, not on new hypotheses.

The goal is NOT to find a tenth strategy. It is to answer, with enough power to
be believed either way:

> **Do mechanical Brooks price-action features carry directional information at
> all, in a liquid market, measured against the right null?**

A tight CI around zero closes the project honestly. A confirmation means the
crypto 0.70 is probably real and the remaining work is execution.

---

## 0. Logistics — settled

- **Go to the data that cannot move.** Work on the machine holding the Indian
  data. Do not move anything here.
- **The crypto side is 70 MB, not 40 GB.** `data/perp_candles/` (220 symbols,
  ts/o/h/l/c/v) is the entire live research input, and `fetch_perps.py` rebuilds
  it from the Delta API in ~2.5 min, unauthenticated. The 26 GB of option
  candles, 9.6 GB of patterns and the 4.8 GB `options_analytics.db` are all
  attached to closed hypotheses. Nothing needs transferring.
- **One repo, not two.** The replication test is only interpretable if the
  feature code is bit-identical across markets. Two repos guarantee
  `brooks_features.py` drifts, and then a null result is uninterpretable.

```
core/      brooks_features.py, labels, folds, bootstrap, metrics   (market-agnostic)
adapters/  delta_perps.py, nse_stocks.py, nse_fno.py               (-> uniform bar schema)
costs/     per-market fee / tax / impact models                    (never a shared constant)
data/      local only, gitignored, rebuilt by fetch scripts
```

`core/` must never know which market it is looking at.

---

## 1. Survivorship — accepted, with the design that neutralises it

The stock universe is currently-listed names only. This is accepted. It is
handled, not ignored:

- **Cross-sectional design.** Rank within the surviving universe; label =
  forward return **minus that day's universe median**. Survivorship shifts the
  median too, so it is common-mode and cancels out of the spread.
- **Large-cap control.** Top turnover deciles are nearly survivorship-free. If
  the effect holds there, survivorship is not driving it. This is a gate, not a
  footnote.
- **Universe-size-over-time diagnostic** (Phase 0) makes the bias visible: if
  name count grows monotonically toward the present, that curve *is* the bias.
- **What stays off-limits:** absolute return figures, equity curves, CAGRs, and
  any long-only claim. Same discipline the mark-price blocker imposed on the
  option results.

---

## 2. Phase 0 — audit and POWER, before any model (~half a day)

This phase exists to find out whether the power story is real. Everything else
is gated on it.

1. **Inventory** — names, date ranges, bar counts, missing sessions, volume
   coverage %, universe size per year.
2. **Adjustment check** — flag |daily return| > 40% with no volume spike, and
   ratios near 1/2, 1/5, 1/10. Unadjusted splits are phantom returns.
3. **Liquidity strata** — rolling 60-day median turnover (INR) per name;
   deciles recomputed monthly, **point-in-time**.
4. **N_eff, measured exactly as the perp panel was** — mean pairwise
   correlation, PC1 variance share, N_eff, PCs to 90% variance. Per liquidity
   stratum and per era.
5. **Independent-week / independent-month count** per stratum.

**GATE:** if N_eff among liquid names is ~6 as it is in crypto, the power gain
is illusory and this plan gets rewritten before a single model runs. Expected:
substantially higher than 5.8, because an equity cross-section spans sectors
rather than being uniformly BTC-beta. Expectation, not assumption — measure it.

---

## 3. Phase 1 — Stocks: cross-sectional Brooks (the main event, ~1 week)

**Universe:** liquid subset by rolling turnover, rebuilt monthly, point-in-time.

**Features:** the existing **105 Brooks features**, unchanged, on daily bars,
lookbacks {5,10,20,50} days. Same `core/brooks_features.py` as crypto — this is
the whole point.

**Labels:** forward 5 / 10 / 20-session return, **cross-sectionally demedianed**
(or rank-normalised to [0,1] within each day).

**Model:** LightGBM, crypto hyperparameters, **no retuning**.

**Folds:** purged walk-forward on calendar dates; embargo = horizon; every name
on a date lands in the same fold.

**Metrics (Tejas's stated preference — expectancy and profit per unit time, not
AUC alone):** daily rank IC, decile spread, expectancy per trade, profit per
month, turnover, and capacity by liquidity decile.

### 3.1 The nulls — this is where the project's value has always been

| control | what it destroys | what it tests |
|---|---|---|
| random decile | the signal | is ranking better than picking? |
| **features shuffled within day** | signal, keeps that day's return distribution | the matched null — the one that killed the grid |
| market return | beta | is the spread just long-the-index? |
| **12-1 momentum, size** | known factors | see 3.2 |

### 3.2 The control I most expect to bite

**Brooks trend/breakout features are almost certainly correlated with 12-1
momentum** — a factor with thirty years of literature that is already arbitraged
in liquid names. If the decile spread dies after regressing on momentum and
size, the "edge" is a repackaged factor, not price action. This is DECISION
DOCUMENT trap #8 (missing the matched control) in its most likely new costume,
and it must be run before any positive result is reported.

**Significance:** block bootstrap on calendar **months**, never on rows —
cross-sectional correlation within a day is near-total.

**Stratify every result** by liquidity decile and by era.

**KILL CRITERIA:** rank IC CI contains zero after factor controls, AND the
decile spread does not beat the shuffled-within-day null → Brooks is dead at
daily scale in equities. Write it up, stop, do not tune.

---

## 4. Phase 2 — Indian F&O: replication of the crypto result (~1 week)

Separate from Phase 1 on purpose. Pooling first would destroy the test, because
you could no longer distinguish replication from the pooled model leaning on
crypto.

**Instruments:** NIFTY and BANKNIFTY futures, FINNIFTY if present, liquid
single-stock futures if available.

**Target:** train and test *entirely within* Indian data, same features, same
model, same hyperparameters, no retuning. **Does AUC land near 0.68-0.70?**

### 4.1 What the 6h/5d structure forces

- **Horizons in BARS or SESSIONS, never calendar hours.** The crypto 24h horizon
  is 24 bars; an Indian "day" is ~6 bars spanning an overnight gap. Getting this
  wrong is HANDOFF sec 3.3 (mixing durations) in a new costume.
- **Overnight gaps.** ATR and bar-shape features computed across a gap measure a
  different quantity. Session-aware ATR + an explicit gap feature.
- **Intraday seasonality.** Strong open/close U-shape, absent in crypto. Needs a
  session-relative time-of-day feature.
- **Contract rolls — the highest-risk item.** Naively stitched futures make the
  roll gap look like a return nobody could earn. Structurally identical to the
  mark-price trap. Back-adjusted series, explicit roll dates, verified against
  known expiries.
- **Costs and leverage do not port.** No funding; basis/roll instead. Brokerage
  + STT + stamp + impact. SEBI margins mean ~5-6x, not 10x+, so the entire
  liquidation-surface analysis is rebuilt, not reused.

**Controls:** shuffled + demeaned returns null; and **random entry with real
exits** — the trap that swung the crypto 6.7x cell from +0.075 to -0.013.

**Significance:** block bootstrap on weeks (~208 available).

**Bonus, not a priority:** 4 years x ~2.5 expiries/week is ~500 expiry cycles,
roughly 10x crypto. Options are retired as an earning instrument, so this only
matters if the option side is ever reopened.

---

## 5. Phase 3 — pooled model and NNs (conditional, ~3 days)

**Only if Phases 1 and 2 both show something.** Otherwise skip entirely.

Pooling two structurally different markets is the first setting in this project
where NNs have a *principled* advantage: a tree must split on market identity
and thereafter fits two separate trees, learning nothing transferable, whereas a
shared encoder with per-market heads can transfer the lower layers.

Test: shared-encoder NN vs pooled tree with a market indicator, identical
calendar folds, using the existing `pool_vs_solo.py` comparison pattern.

**New leakage risk, not in HANDOFF:** folds must be cut on **calendar** time
across both markets, so the same week lands in the same fold. Otherwise an
Indian bar from week W in train and a crypto bar from week W in test share a
global macro shock.

Prior: trees still win. The measured record is trees 4/4 folds over CNN, GRU,
LSTM, MLP and a Transformer, and 20x more rows did not close a 1-7 point gap.

---

## 6. Decision gates

| gate | pass | fail |
|---|---|---|
| Phase 0 N_eff | proceed to Phase 1 | rewrite the plan; power gain was illusory |
| Phase 1 vs shuffled-within-day null | proceed to factor controls | Brooks dead at daily scale — write up, stop |
| Phase 1 vs momentum + size | real price-action edge | it is a repackaged known factor — write up, stop |
| Phase 1 large-cap stratum | survivorship not driving it | edge is a microcap/survivorship artifact |
| Phase 2 AUC ~0.68-0.70 | crypto result replicates | crypto result was fitted to 142 weeks — do not trade it |
| Phases 1 and 2 both pass | Phase 3 | stop; write up |

---

## 6b. A Kite/NSE pipeline ALREADY EXISTS — found 2026-09-16 in `context/`

`context/Claude_Artifacts_001.zip` contains a complete NSE F&O pipeline built on
Zerodha Kite Connect, mirroring the crypto project's structure file for file. It
is **not** extracted into this repo. Nothing in section 4 should be written from
scratch before reading it:

| file | what it does |
|---|---|
| `market_config.js` | single source of truth for NSE session (09:15–15:30 IST), holidays, broker nuances. Explicitly says no other file may hard-code calendar or session logic. |
| `kite_client.js` | Kite Connect wrapper; mirrors the crypto `api.js` interface so callers are unchanged |
| `fetch_instruments_fno.js` | NSE F&O instruments → `instruments/{SPOT}/{expiry}.json`, carrying `strike`, `lot_size`, `instrument_type` |
| `fetch_spot_candles_fno.js`, `fetch_option_candles_fno.js` | candle backfill |
| `group_candles_fno.js`, `candle_grouper.js` | duration grouping |
| `generate_signals_fno.js` | marker-based incremental signals; already has `stairsSignal` and `spikeAfterFlat` |
| `place_multiple_orders.ps1` | order placement |

This answers three of section 7's questions before they were asked: the
instruments are NSE F&O including index and stock options, lot size is carried
per instrument, and the session/holiday handling that section 4.1 flags as the
structural risk **already exists and is centralised**.

It does not answer the survivorship or adjustment questions, which are about the
stock dataset rather than this pipeline.

**Revised first step for Phase 2:** extract that pipeline, diff it against the
crypto equivalents, and decide what becomes a shared `core/` versus what stays
market-specific — rather than writing adapters from scratch. The `market_config`
/ `kite_client` split is already the adapter shape section 0 proposes.

---

## 7. Answer these before Phase 1 starts

1. **Bar resolution** of the Indian F&O data — 1-minute, 5-minute, hourly? And
   is it index futures, options chains, or both?
2. **Stock data resolution by era** — where exactly does daily-only end and
   intraday begin?
3. **Adjustment** — are prices split/bonus adjusted, and adjusted for dividends
   or not?
4. **Volume units** — shares or turnover? Is delivery volume separate?
5. **Which exchange(s)** — NSE only, or NSE+BSE (affects dedup and liquidity
   measurement).
6. **US stocks** — worth knowing whether it includes delisted names, since a
   survivorship-complete universe would let Phase 1 run a clean bias
   quantification that Indian data alone cannot.

---

## 8. What success looks like

A cross-sectional daily equity signal that survives the shuffled-within-day
null, the momentum and size controls, and holds in the top liquidity deciles —
reported as expectancy per trade **and** profit per month, with a monthly block
bootstrap CI, stratified by era.

If that exists, it is tradeable long-only in Indian cash equity with no leverage,
no funding, loss offset permitted, and none of the fee-multiplication that killed
the crypto futures result.

If it does not exist, the project ends with a properly powered negative — which
is worth more than another two months of searching at N_eff 5.8.
