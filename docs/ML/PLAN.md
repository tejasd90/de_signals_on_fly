# A workable plan, 2026-09-30

Built only from results that survived the 2026-09-30 audit. Anything that failed
the per-asset check, the same-day/next-day check or the event-ordering check is
excluded, however good its headline number was.

**Tiered by evidence, not by appeal.** Tier 1 is the only component with a real
P&L backtest. Everything below it is a filter, a constraint, or a hypothesis to be
paper-traded. The plan is built so that Tiers 2-4 failing costs little.

---

## TIER 1 — The engine: cross-sectional perp book (futures, systematic)

The only thing in this project with a genuine equity curve.

| | |
|---|---|
| return | **+59.4%/yr**, vol 23.9%, **Sharpe 2.48**, maxDD −18.2% |
| significance | P(<=0) = **0.0003**, 5-95 CI [+34%, +84%] |
| sample | 1,003 days, 207 names incl. 22 delisted |
| survived | survivorship fix, equal-risk, beta hedge, capacity cap |

**Construction.** Signal = cross-sectional z-score of *negative* 20-day realised
vol (long calm, short wild). Beta-hedged each rebalance on 60-day beta. Rebalance
every **5 days**. Position cap 0.5% of each name's 20-day average dollar volume.

**Cost-robust.** At taker fees + 30bps slippage: **+50.8%/yr, Sharpe 2.13**.
Turnover is 25.6x/yr, so even 36bps all-in costs ~9%/yr against ~59% gross.
Cost is not what kills this.

**Funding is a tailwind, not a drag** (`xsec_funding.py`, new): long leg +18.75
raw/yr, short leg −5.97, net **+12.78** — about +12.8%/yr if rates are quoted in
percent. Coverage is 50% of name-days and units are unverified, so **bank the
+59% and treat funding as upside.** Note this rehabilitates the long leg, which
loses 8.8%/yr on price but earns carry.

**The real risks, none of them statistical:**
1. **117% of the price return is the short leg.** This is structurally short alt
   volatility. It will hurt badly in a violent alt melt-up.
2. **Operational.** ~100+ simultaneous short perp positions, rebalanced 5-daily,
   needs automation and margin. This is the binding constraint, not the edge.
3. Capacity is not an issue at any size he would trade ($10k book tested at
   +73%/yr).

**Decision required before any capital moves:** can a Delta India retail account
actually hold ~100 short alt perps with acceptable margin? If not, test a reduced
book (top/bottom 20 names) and re-measure — do NOT assume it scales down cleanly.

---

## TIER 2 — The gate: when NOT to trade (futures, discretionary overlay)

`docs/ML/WHEN_NOT_TO_TRADE.md`. Rank each day by P(quiet); **sit out the 30%
ranked quietest.**

| | |
|---|---|
| effect | avoid **40.9%** of dead days, miss **17.3%** of good ones |
| edge | **+23.5pp**; bootstrapped +21.5pp, P=1.000, CI [+7.9, +33.9] |
| per asset | BTC +15.2pp, ETH +20.7pp |
| control | random-skip +0.1pp; filter beats 100% of random skips |

**This gives NO direction** (trend-vs-chop is null, AUC 0.524). It says only
whether there will be room to move.

**Use:** a veto on discretionary activity, not a signal. Overtrading is the stated
problem; this removes a third of the opportunities to overtrade and removes the
dead ones twice as fast as the live ones.

---

## TIER 3 — Discretionary direction, gated (his edge, not the model's)

Journal scoring (`JOURNAL_SCORECARD.md`) suggests **structural reads score, biased
reads do not.** 4 resolved calls is far too few to trust — this is a hypothesis
under test, not a finding.

Rules:
1. Trade a discretionary view **only on days Tier 2 has not vetoed.**
2. Write the call **before** entry with a horizon, a falsifier and a confidence.
   Entry 2 of his journal already does this; it is the easiest to score.
3. **Label the call STRUCTURAL or DIRECTIONAL-BIAS at the time of writing.**
   If the journal pattern holds, size bias calls at zero.
4. Exits are **mechanical and set before entry.** His stated failure is watching
   profit wither — that is an exit-discipline failure, and no signal fixes it.
   Supporting evidence: time-stops beat hold-to-expiry in every monthly-option
   subset, and "press the winner" is falsified (8x Kelly, decays).

---

## TIER 4 — Options, deliberately narrow

Most option results died or were qualified. What is left:

**Do:**
- **R4 — agree with the 4h trend.** 5.96% vs 4.33% break-even, P=0.000. The only
  rule with traded-price backing (~6.0-6.3%) and the only one working at 100x.
- **Weekly expiry (3-9 DTE)**, not 0-2 DTE (4.26% vs 1.54% at 100x).
- **Exit on a time-stop**, not at expiry.

**Never:**
- **Buy a put when `hold` fires** — premium refusing to decay while spot moves
  against it means IV is already bid and you are overpaying. Direction-controlled:
  −0.45 / −2.18 / −6.57 / −16.63 dEV across four narrow crash bands, all P<=0.001.
  Fires 1.4-2.7% of the time. It is a veto, not a strategy.
- Buy cheap OTM on a schedule (EV −0.83, P=0.995).
- **Trade wedge or trendline breaks as entries.** The 2026-09-30 audit shows the
  break arrives AFTER the option is already running 62-74% of the time (BTC wedge
  median lead −2.5h). They describe a move, they do not call one.
- Run a grid. Income is path-length-bound and the position is short gamma.

---

## Capital and ruin

He trades to clear debt, which is exactly the pressure that produces the
profit-withering. The plan has to be built against that, not around it.

1. **Ring-fence.** Tier 1 capital is not withdrawable on a schedule tied to debt
   payments. A strategy with a −18% maxDD cannot fund a fixed obligation.
2. **Separate accounts** for Tier 1 (systematic) and Tiers 2-4 (discretionary).
   Mixing them makes it impossible to tell which is working.
3. **Discretionary risk cap:** a fixed fraction per trade, set in advance. The
   futures leverage study already showed random entry is significantly negative —
   survival comes from sizing, not from entry quality.

---

## Validation before capital

| step | test | pass condition |
|---|---|---|
| 1 | Tier 1 paper, 8 weeks, real fills | tracks backtest within noise; margin workable |
| 2 | Tier 2 gate logged daily | veto rate ~30%; skipped days are measurably quieter |
| 3 | Tier 3 journal, ~30 calls, pre-labelled | structural beat bias on realised outcome |
| 4 | Tier 4 only after 1-3 | R4 hit rate above 4.33% break-even on real fills |

**Order matters.** Tier 1 is the compounding engine and the only validated P&L.
Tiers 2-4 are refinements to discretionary trading that should not receive capital
until Tier 1 is running and Tier 3's journal has enough scored calls to mean
anything.

## Open items that would change the plan

- Tier 1 on **perp_candles traded prices** rather than the daily close series.
- Tier 2 against **actual futures P&L**, not range as a proxy for opportunity.
- Funding units verified — worth up to +12.8%/yr on Tier 1.
- Whether a reduced (20-40 name) book retains the Sharpe.
