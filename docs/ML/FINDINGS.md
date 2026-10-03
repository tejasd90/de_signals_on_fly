# FINDINGS — 2026-09-10 session

Supersedes parts of HANDOFF.md §2. Everything here is out-of-sample under
purged walk-forward on `disc_final` (942,769 sampled rows / 8.5M effective,
1,973 episodes, hourly, BTC+ETH+XAUT, 2024-02 .. 2026-09).

New code: `exit_sim.py` (stop-exit outcomes), `hold_sim.py` (no-stop / hold-to-
expiry outcomes), `edge_eval.py` (expectancy by selectivity).
New data: `exits/` (18M rows), `holds/`.

---

## 1. Answered: surface beats context (HANDOFF §2.3 open question)

Precision @15% recall: context 0.019 | **surface 0.030** | spot_shape 0.021 |
option-shape 0.012 | all-159 0.031.

21 features match what 159 achieve. Pattern shape stayed **inert under a much
richer encoding** (~140 mechanical shape features); option-candle shape scored
*worse than context alone*. The §2.1 caveat has now been tested properly and
came back the same way.

## 2. The edge is NOT the D-01 degenerate rule

| ranker (top 0.5%) | expectancy | 25x hit% |
|---|---|---|
| **ML score** | **+0.3059** | 2.807 |
| cheapness alone | -0.0415 | 0.074 |
| stdMoneyness alone | -0.0475 | 0.000 |
| random | -0.0607 | 0.199 |

`cheapness` alone LOSES and hits 25x *less often than random*. It tops
permutation importance (0.2133) only as a conditional interaction. The model is
not "buy the cheapest ticket".

## 3. Where the edge lives: 24h+ before expiry

| tteHours | expectancy |
|---|---|
| 0-6h | **-0.086** |
| 6-12h | +0.054 |
| 12-24h | +0.149 |
| 24-48h | **+0.545** |
| 48-120h | **+0.596** |
| >120h | +0.501 |

Filtering to `tte >= 24h` raises expectancy 0.306 -> 0.463 AND moves out of the
zone where mark/trade divergence is worst. Two reasons to do the same thing.

## 4. Do not take profits early

| target | exp @5% cost | exp @20% cost |
|---|---|---|
| 2x | -0.069 | -0.219 |
| 5x | +0.021 | -0.130 |
| 25x | +0.306 | +0.156 |
| 100x | +0.596 | +0.446 |

Small targets have NEGATIVE expectancy. The edge is entirely in the convex tail.

## 5. The stop was costing money — no-SL is mechanically sound

- 87.6% of stopped trades exit at **0.833x** premium after ~7.4 bars (losses are
  ~17%, not total); 12.4% run to the cap at 2.50x.
- **6.77% of trades were stopped and later reached 25x anyway.**
- No-stop + resting GTC limit at 25x requires zero monitoring.

## 6. Lift over a matched null (same type x tte-band x year)

Strips out directional beta. Matched null is -0.03..-0.055 everywhere, which is
correctly negative (option buyers lose slightly) - a good sanity check.

| policy | 2024 | 2025 | 2026 | all |
|---|---|---|---|---|
| stop | **+0.068** | +0.466 | +0.597 | **+0.505** |
| no-stop GTC | **-0.073** | +1.340 | +2.151 | +1.682 |

The selection edge is real and survives beta-stripping. But no-SL is
**regime-dependent** and lost money in 2024; the stop version stayed positive
every year.

Calls returned +0.234 held to expiry vs puts -0.019 — the call side is bull-market
beta. The model's *put* selections return +0.892 no-stop against a -0.019 random
put baseline, and that lift cannot be beta.

---

## 7. THE BLOCKER: absolute magnitudes are not trustworthy

Measured expectancy (+1.30 to +1.66/trade no-stop) is too good to be true and
compounds to absurd numbers over 766 days. The arithmetic is right, so the input
is wrong. Cause identified:

**Prices are MARK prices, not trade prices, with no volume anywhere.** A mark
touching 25x is not a fill. Among "filled" trades the marked peaks are:

    p50 60x | p75 227x | p90 593x | p99 3,453x | max 10,041x

Sensitivity to what you can actually realize:

| realized cap | expectancy |
|---|---|
| 25x | +1.656 |
| **10x** | **+0.138** |
| 5x | -0.410 |
| 3x | -0.643 |

Break-even capture = **32-38% of the marked move** (~8-10x out of 25x).
33% of all fills occur after the first 72 candles.

**Everything rests on whether you can sell these at 8-10x+.**

### 7b. RESOLVED (partly) — traded prices ARE available

`processor.js:141` hardcodes the `MARK:` prefix:

    const raw = await api.fetchCandles(`MARK:${symbol}`, resolution, ...)

The SAME endpoint (`/v2/history/candles`) returns **traded OHLCV with real
volume** when passed the plain symbol. Verified live. This was never an API
limitation — it is a one-line choice in the fetch layer.

Spot-check, 50 model-selected instruments (30 that reached 25x on marks):

| measure | result |
|---|---|
| hourly candles with any trade | median **77.7%** |
| instruments that never traded | **0 of 50** |
| reached 25x on marks AND on TRADED prices | **23 of 30 (77%)** |
| median capture (traded peak / mark peak) | **96.4%** |

So marks are broadly corroborated by prints: apply roughly a **23% haircut to
fill probability**, not the catastrophic haircut feared. Expectancy stays
clearly positive under that.

STILL UNKNOWN: trade **size**. A single lot printing at 25x does not mean you
can sell size there. Depth/bid-ask remains unmeasured.

---

## 8. What I'd trust, and what I wouldn't

Trust:
- surface > context; pattern shape inert
- the edge is not the cheapness tautology
- trade at tte >= 24h, never in the last 6h
- do not take small profits
- relative selection lift, positive every year, beta-stripped

Do not trust:
- any absolute expectancy or compounded return
- any equity curve or CAGR
- fill probabilities derived from mark-price peaks

## 9. Next

1. **Re-backfill without the `MARK:` prefix** (`processor.js:141`) to get traded
   candles + volume. Unblocks real fill validation AND the D-13 tradeability
   filter, which has never had volume to work with. Keep mark candles — the pair
   is more informative than either alone.
2. Paper-trade forward against live quotes — validates fills without capital.
3. Only then re-measure expectancy and consider sizing.

## 10. Traps hit this session (add to HANDOFF §3)

- A column named exactly **`label`** in disc_final defeats a `label_` prefix
  filter -> AUC 1.000/0.996. Filter on prefix `label`, and assert the list.
- **`_ts_hours` is float32**; `_ts_hours*3600` in DuckDB loses precision and
  silently matches ~6% of rows. `CAST(... AS DOUBLE)` first.
- Weighted data: `_w` must be used for EVERY statistic, including trade counts,
  daily top-N selection and equity curves — not just hit rates.
- Never mix horizons: a fill test over one window with a miss-value from another
  is the §3.3 trap in a new costume.

---

## 11. High-probability setups exist and are UNPROFITABLE (2026-09-10, later)

Trained directly on low targets — nobody had ever done this; every prior target
was 25x+. Mark prices only, no tte filter, no cost games.

| target | base | top0.1% | top0.5% | top1% | top5% | exp/trade @top0.5% |
|---|---|---|---|---|---|---|
| 1.5x | 16.66% | 61.9% | 54.6% | 50.1% | 42.6% | **-0.045** |
| 2x | 8.80% | 41.9% | 35.9% | 33.1% | 27.3% | **-0.058** |
| 3x | 4.08% | 25.7% | 21.7% | 20.2% | 16.0% | **-0.051** |
| 5x | 1.76% | 16.3% | 13.2% | 12.2% | 9.1% | +0.017 |
| 10x | 0.66% | 7.6% | 6.8% | 6.1% | 4.5% | +0.112 |
| 25x | 0.21% | 4.3% | 3.3% | 3.0% | 1.9% | **+0.386** |

**A 54% win rate at 1.5x loses money** (win 0.5, lose 0.58 on the other 46%).
Every high-win-rate setting is negative. Profit exists only where win rate
collapses. This is structural, not a tuning failure. 25x is the best cell.

## 12. The optimal-strike (max-across-members) framing — ML_SPEC O-06 settled

Per episode, buy the top-K ML-ranked strikes:

| K | ORACLE hit% @25x | ORACLE exp | REAL exp/unit | oracle gap |
|---|---|---|---|---|
| 1 | 8.6% | +1.724 | **+1.708** | +0.016 |
| 3 | 10.9% | +2.362 | +1.184 | +1.178 |
| 5 | 12.2% | +2.699 | +1.124 | +1.576 |
| 10 | 14.3% | +3.272 | +1.154 | +2.118 |
| 20 | 20.1% | +4.823 | +1.444 | +3.379 |

ORACLE = you knew ex ante which of the K would win (what a max-across-strikes
number reports). REAL = you buy all K, pay K premiums, so your return is the
MEAN. The gap is pure oracle and is not implementable.

Ceiling check — max over ALL strikes in the episode, no model at all:
**83.9% at 10x, 52.8% at 25x.** The max operator does the work, not the signal.
Any "pick the best strike" number must be read against that ceiling.

**Consequence: K=1 is optimal.** Buying one top-ranked strike gives the highest
return per unit capital (+1.708). Spreading across strikes dilutes, because when
a move happens ~50.6% of your strikes hit anyway — they are highly correlated.

**Comparison to the heuristics, like for like** (both under optimal-strike):

| | 10x | 25x |
|---|---|---|
| heuristics (as remembered) | 15-20% | 5-6% |
| ML, K=1 | 21.3% | 8.6% |
| ML, K=5 | 26.8% | 12.2% |

The ML is not worse in the heuristics' own framing. Separately, ML_SPEC O-07
records that the heuristic figures came from synthetic fixtures, and the real
backfill in HANDOFF 2.1 measured 2.82%/2.92% at 25x with best precision 4.7%.

## 13. CORRECTION + the structural result (2026-09-10, latest)

**Retracted:** the per-episode top-K table in §12 was computed unweighted across
episodes and is inflated by negative downsampling. Top-1-per-episode at 25x:
**8.56% unweighted vs 1.31% weighted** — a 6.5x inflation. Use weighted numbers.

**The structural finding.** Decomposing the model's AUC:

| what it ranks | AUC |
|---|---|
| **within-episode** (which strike, given the moment) | **0.9469** |
| **between-episode** (is this moment any good) | **0.5745** |

100% of mixed episodes rank better than chance within-episode. Within-episode
comparison of rankers: score 0.9469 · cheapness 0.9124 · tteHours 0.8173 ·
stdMoneyness 0.1507.

**The model is a STRIKE PICKER, not a timing model.** It is near-perfect at
"which contract on this chain" and near-useless at "is today a setup". That is
why K=1 inside the trusted slice gives 1.7% at 25x vs a 2.81% slice average — it
picks excellent strikes inside episodes containing no mover.

This is HANDOFF's "contract selection is the edge, timing has shown none",
now measured precisely rather than inferred.

**Consequence for where the remaining value is:** the binding constraint is
between-episode (timing/regime), at AUC 0.574. Every feature in disc_final is
computed on the OPTION chain plus 70 thin spot-shape columns. The spot side is
where timing information would live, and arm 4 (BROOKS_FEATURES.md, ~90-120
mechanical spot features) has never been built.

## 14. Pending items closed (ML_SPEC §0 WAITING-TEJAS)

- **P1 / D-40 random-entry null baseline — CLOSED.** `disc_final` is signal-free
  (`signal` is 100% NULL), so it already IS the random-entry population. Matched
  null measured at -0.03..-0.06 in every year and every type x tte cell —
  correctly negative. No `make_random.py` needed.
- **P2 / O-06 merged-event ratio — CLOSED: use MEAN, not max.** Max embeds an
  oracle worth up to +3.38 expectancy (K=20) that is not implementable. Buying K
  strikes costs K premiums, so the realised return is the mean. Ceiling check:
  max over ALL strikes with no model gives 83.9% at 10x / 52.8% at 25x, i.e. the
  max operator does the work. Per-contract labels are correct; K=1 is optimal.
- **P4 / D-13 tradeability floor — PARTIAL.** Min-premium sensitivity measured:
  the edge survives a floor up to 2.0 (exp +0.167 at 25x, tte>=24h). The volume
  half is unavailable from mark candles by construction.
- **P3 / D-30 mode 1 — OPEN, and now the recommended next step** (see §13).

## 15. ARM 4 (Brooks spot features) — BUILT AND FALSIFIED

`brooks_features.py` implements BROOKS_FEATURES.md: **105 mechanical spot
features** — bar shape, bar-to-bar relations, swing structure (incl. shrinking
stairs, the `ratio1` analogue), the trend/range continuum, breakout and
follow-through, regime/climax — at lookbacks {5,10,20,50}, all ATR-normalised,
no lookahead (swings consulted only at j <= i-1). Output `brooks_spot.parquet`,
49,702 hourly rows x 105 features across BTC/ETH/XAUT.

Feature health: 0 all-NaN, 0 zero-variance, median NaN fraction 0.000. The arm
is correctly built; it simply carries no timing information.

**Target 1 — "does this episode contain a mover":** AUC 0.517-0.540. But this
target is DEGENERATE: with ~4,244 real contracts per episode, "did any hit 25x"
is a max over thousands of draws, sits at 51.7% by construction, and measures
chain breadth, not the day. (Within episodes that had a hit, only 1.4% of
contracts hit.) Discard this target.

**Target 2 — "will trading this episode's top-10 strikes pay":**

| features | AUC |
|---|---|
| Brooks spot only (105) | 0.5286 |
| chain aggregates only (4) | 0.5198 |
| both | 0.5192 |

Significance: label-permuted null mean 0.5003 sd 0.0242 (95th pct 0.5387);
**p = 0.150**; bootstrap 95% CI **[0.4865, 0.5668]**, which contains 0.5.

**Conclusion: arm 4 is falsified.** Brooks spot structure does not predict which
moments pay, on this data, at hourly resolution. This was the last untested
hypothesis in ML_SPEC. Combined with §13, the project's central question is now
answered:

    Contract selection is predictable (within-episode AUC 0.947).
    Timing is not (between-episode AUC ~0.52-0.57, not distinguishable
    from chance).

**Practical consequence.** There is no "setup" to wait for. Chasing entry timing
is chasing something the data says is not there — which is directly relevant to
HANDOFF 5 (overtrading driven by expecting regular income from an irregular
strategy). The discipline is a consistent small-size process over many episodes,
with the edge coming from strike selection, not from picking moments.

Do NOT read this as "Brooks is wrong". It says these 105 encodings, on hourly
crypto spot, over 1,579 episodes, carry no episode-level signal. A different
resolution, a longer history, or cross-sectional breadth (more symbols) could
change it — that is ML_SPEC 3.2's point about where sample size actually grows.

---

# PART 2 — LEVERAGED FUTURES ON SPOT (2026-09-11)

New code: `liq_surface.py` (exact first-crossing surface), `fut_ml.py`.
Data: `liq/` — 99,404 entries (BTC/ETH/XAUT, hourly, both directions, H=168h).

## 16. The sizing question — exact, no model needed

P(NOT liquidated), random entry:

| lev | stop | 6h | 24h | 72h | 168h |
|---|---|---|---|---|---|
| 400x | 0.25% | 23.3% | 11.2% | 6.0% | 3.8% |
| 100x | 1.00% | 65.8% | 38.1% | 22.0% | 14.4% |
| 50x | 2.00% | 86.9% | 62.4% | 40.2% | 27.1% |
| 20x | 5.00% | 98.6% | 91.0% | 74.6% | 57.1% |
| 10x | 10.0% | 99.9% | 98.7% | 93.3% | 82.5% |
| 4x | 25.0% | 100% | 100% | 99.7% | 98.3% |

Max leverage for a survival target over 72h: **99% -> 4x · 95% -> 7x ·
90% -> 10x · 80% -> 13x · 50% -> 33x.**

Time to target (given reached, within 168h): +1% 85.6% median 10h ·
+2% 72.9% median 23h · +5% 42.9% median 59h · +10% 17.5% median 89h.

## 17. Leverage cannot create edge — confirmed exactly

For a driftless walk P(+a before -b) = b/(a+b), making EV on margin exactly 0 at
every leverage. Measured null EV came out **+0.0000 at every leverage**, which
validates the accounting.

Observed P(target first) tracks the null within ~1pt at high leverage and exceeds
it at low leverage (+2.8/+5.8/+12.5 pts at 7.5/10/15% stops) — a mean-reversion
signature, symmetric in long and short, i.e. a path property not a direction.

**But that apparent edge is an artifact of counting unresolved trades as
breakeven.** Conditional on NOT reaching the target, terminal return is biased
negative. Using real terminal exits swings 6.7x from +0.075 to -0.013 before
funding. Funding then makes every leverage negative:

| lev | no fund | 0.01%/8h | 0.03%/8h |
|---|---|---|---|
| 50x | -0.007 | -0.037 | -0.097 |
| 10x | -0.024 | -0.038 | -0.066 |
| 6.7x | -0.013 | -0.023 | -0.043 |

Block bootstrap (non-overlapping 7-day blocks) at 6.7x/+5%: observed **-0.0232**,
95% CI **[-0.0394, -0.0078]**, **P(EV<=0) = 0.998**. Random-entry leveraged
futures is significantly NEGATIVE. Fees scale with leverage (cost on margin =
L x fee), which is why high leverage is worst: at 200x a 0.10% round trip costs
20% of margin.

## 18. ML entry selection — best signal in the project, still not significant

105 Brooks spot features, purged walk-forward with an H-bar embargo (labels
overlap by construction).

| config | AUC | slice | win% | liq% | EV | 95% CI |
|---|---|---|---|---|---|---|
| 6.7x, +5% | 0.607 | ALL | 41.2% | 5.5% | -0.018 | [-0.031, -0.004] |
| 6.7x, +5% | 0.607 | top 5% | 56.6% | 8.2% | **+0.019** | [-0.042, +0.079] |
| 10x, +3% | 0.579 | top 5% | 69.9% | 15.9% | -0.008 | [-0.051, +0.031] |

Selection lifts win rate 41.2% -> 56.6% and EV from significantly negative to
break-even. It does NOT reach significant positive: the best CI spans zero, and
at 0.03% funding the best cell is +0.0025.

**AUC 0.607 is ~2.5 SE above chance and is the strongest predictive signal found
anywhere in this project** (options episode timing was 0.528, CI containing 0.5).
Note selecting harder RAISES liquidation (5.5% -> 8.2%) — the model picks
volatile setups where both barriers are nearer.

**Binding constraint: 141 non-overlapping 7-day blocks.** Not 99,404 rows. That
is too few to establish a small edge, and it is the same wall as everywhere else
in this project. The fix is cross-sectional breadth (more symbols), per
ML_SPEC 3.2 — not more features.

## 19. ALL-PERP EXPANSION (2026-09-11)

`fetch_perps.py` — 220 live perpetual futures, hourly, paginated backward
(a single request silently caps at ~4000 rows and makes every symbol look
newly-listed). **2,518,884 bars, current to 2026-09-11 06:00 UTC.** These are
TRADED candles: median 90% of bars carry volume, unlike the options mark data.
55 symbols have >=2y, 129 have >=1y.

**Independence gate.** 129 symbols, hourly returns: mean pairwise corr 0.385;
PC1 = 41.2% of variance, PC1-3 = 44.8%; **N_eff (participation) = 5.8**; but 88
PCs are needed for 90% of variance. So: one big common factor plus a long flat
idiosyncratic tail. Adding symbols does NOT add independent TIME periods (still
~142 weeks); it reduces within-week estimation noise. All significance testing
therefore blocks on time.

**Decision test (pre-registered), stop -15% (6.7x) / target +5%:**

| criterion | result | |
|---|---|---|
| AUC ~0.60 | **0.6015** (folds .574/.602/.598/.608) | PASS |
| calibration monotonic | .609->.608, .703->.712 | **PASS (fixed)** |
| half-Kelly CI clears 0 | [-0.0052,+0.0074], P(<=0)=0.279 | FAIL |

Calibration went from non-monotonic (3 symbols) to near-perfect (129) purely
from more data — the strongest evidence in this project that the approach is
sound and was data-starved rather than wrong.

**Why it still fails.** Break-even win prob = 1/(1+F/A) = 0.750; the model's best
bucket reaches 0.725. Conditional on RESOLVING, win/(win+liq) = 0.781, above
break-even — the gap is consumed by fees, funding and the unresolved branch.

## 20. Barrier-geometry scan, and the short-side effect

Best random-entry economics are tight-stop/big-target (trend-following payoff):
stop -2% (50x) / target +20%, EV **+0.0546** with NO model. Decomposition:
wins 6.4% (mean R +9.90) · liquidations 84.1% (-1.065) · unresolved 9.5%
(+3.332, mean tret +6.97% x50 leverage).

**But it is almost entirely SHORT side:**

| year | long EV | short EV |
|---|---|---|
| 2024 | +0.031 | **+0.244** |
| 2025 | -0.107 | **+0.168** |
| 2026 | -0.005 | **+0.106** |

That is altcoin decay — shorting alts with a tight stop and a big target
harvests the structural bleed of alt/BTC. It is a directional regime bet, not a
timing edge, and it reverses in an alt season.

**And it is not significant:** block bootstrap on 142 weekly blocks gives
EV +0.0546, 95% CI **[-0.0422, +0.1644]**, **P(EV<=0) = 0.138**. Funding
sensitivity: +0.055 at 0.01%/8h, +0.035 at 0.03%, **-0.035 at 0.10%**.

**Verdict: not a validated edge.** A plausible, known structural effect that does
not clear significance on the available history.

**Note 2026-10-02:** the same short-alt effect, harvested market-neutrally across
207 perps instead of directionally, IS significant: the cross-sectional low-vol
book (`xsec2.py`, beta-hedged, 5-day rebalance, incl. 22 delisted names) gives
**+59.4%/yr, vol 23.9%, Sharpe 2.48, maxDD −18.2%, P(<=0)=0.0003, CI [+34%, +84%]**.
The short leg is **117%** of the price return (long −8.8%/yr, short +61.6%/yr).
Numbers rerun 2026-10-02 and identical to PLAN.md Tier 1. Detail in CONTEXT_PLAN.md
"Steps 1-3 on the cross-sectional direction"; the earlier 55.4% / Sharpe 2.06 /
137% (`xsec.py`) and 58.4% / 2.44 / 119% (`xsec2.py`, 2026-09-19 data) figures
there are older versions of this number.

## 21. The constraint has MOVED

It is no longer symbols — 129 are in and calibration is fixed. It is now
**TIME: 142 weekly blocks over 2.7 years**, and more symbols cannot add weeks.
Levers that remain:
1. **Shorter horizons.** H=168h gives ~142 independent blocks; H=24h would give
   ~1,000. This multiplies independent periods without new data.
2. Forward paper-trading (adds weeks at one week per week).
3. Accept the short-side alt-decay effect as a regime bet, sized tiny, with
   explicit awareness it inverts in an alt season.

---

# GAME: Futures_Maximization_With_Hedging (2026-09-11)

Options are retired as an earning instrument. Futures earn; options were to hedge.

## 22. Shorter horizon was the right lever

| horizon | AUC (129 perps) | independent weekly blocks |
|---|---|---|
| 168h | 0.6015 | 142 |
| 48h | 0.6525 | 142 |
| **24h** | **0.6839** | 142 |

**And the edge is STRONGEST on the hedgeable pair:** BTC+ETH alone at 24h gives
**AUC 0.7024** vs 0.6840 pooled. Best predictive result anywhere in this project.

**Superseded 2026-10-02:** this comparison is not like-for-like (different test
populations). On identical BTC+ETH test rows: 0.6942 trained on BTC+ETH alone,
**0.7319** trained on all 129 symbols. Pooling creates the edge, it does not
dilute it. See §34.

## 23. Fees were the binding cost, and leverage multiplies them

Fee cost on margin = L x fee. At 6.7x a 0.10% round trip costs 0.67% of margin.
BTC+ETH, -15%/+5%, top-5%: taker -0.0052 -> maker/maker **-0.0012**. The model's
GROSS edge is +0.0015/trade — real, just under the toll.

Sweeping leverage x selectivity (BTC+ETH, maker fees), EV rises monotonically
with selectivity in nearly every row — the signature of a genuine edge
concentrated in high-confidence predictions:

| config | top1% EV | top5% EV |
|---|---|---|
| -10%/+3% 10x | **+0.0209** | -0.0098 |
| -15%/+10% 6.7x | +0.0082 | -0.0004 |
| -15%/+5% 6.7x | +0.0073 | +0.0032 |
| -25%/+5% 4x | +0.0059 | +0.0027 |

**But nothing is significant.** Block bootstrap, 142 weekly blocks:
-10%/+3% 10x top1% = +0.0209, 95% CI **[-0.0331, +0.0653]**, P(<=0)=0.176.
Every other config also spans zero.

## 24. HEDGING: REMOVED FROM THE PLAN

Three independent reasons, all measured:

1. **Lower leverage dominates and is free.** -25%/+5% at 4x gives EV +0.0059
   with CI +-0.019; -10%/+5% at 10x gives +0.0036 with CI +-0.049. Wider stops
   via less leverage beat tighter stops on both return AND variance, at zero cost.
   A hedge must beat a free alternative that already wins.
2. **The hedge does not prevent liquidation.** A 10% OTM put on a 10x position
   pays out only after the liquidation level is breached. The futures position is
   already gone; the put refunds part of the loss. It is compensation, not
   protection.
3. **It costs a large share of the edge.** Median 5-15% OTM BTC put, 12-36h to
   expiry, is 0.027% of spot (mark). Hedging full notional costs **0.27% of
   margin per day at 10x** against a measured edge of +0.6% to +2.1% per trade —
   13-45% of the edge, at MARK prices. Buying pays the ask, so the true figure is
   materially worse, and insurance is negative-EV by construction.

Conclusion: **the game is Futures_Maximization. Hedging is dropped.** Risk is
controlled by leverage and position size, which are free.

## 25. Where the game stands

- Engine: AUC 0.7024 on BTC+ETH at 24h, well calibrated. (**Superseded
  2026-10-02:** like-for-like 0.6942 BTC+ETH-trained / 0.7319 pooled-trained, §34.)
- Economics: gross edge positive, rises with selectivity, survives maker fees at
  top-1% selectivity (~1 signal/day across BTC+ETH).
- Blocker: unchanged — **142 independent weeks**. No config clears significance.
- Hedging: removed, with evidence.

## 26. CROSS-EXPIRY (term structure) — built and tested (2026-09-13)

**The gap was real.** `discover_build.py:434` loops `for exp in ...`; the chain is
assembled from one expiry directory; `_fit_one(strikes, ps)` fits log(premium)
against STRIKE only. All 15 `surf_` features are within-expiry. At any instant
there are a mean of **5.92 live expiries** and the model saw them separately.

**Built** `term_structure.py` + `term_features.py` -> `term_features.parquet`,
559,311 chain-instants, 10 new cross-expiry features. At each (spot, ts, type)
it interpolates premium at matched moneyness in every live expiry, then fits
log(premium) vs log(tte) ACROSS expiries. Headline feature `term_resid_*` =
this expiry's deviation from the board's own term structure (rich vs cheap).

Fit quality is excellent and physically sensible: **term_r2_p0 = 0.991**, ATM
slope **0.584** vs the theoretical sqrt(T) value of 0.5; 5% OTM slope 1.403.

**Result: no improvement.**

| arm | feats | AUC | P@15% rec |
|---|---|---|---|
| context | 5 | 0.9074 | 0.0187 |
| **surface** | 20 | **0.9173** | **0.0307** |
| term (new) | 15 | 0.9066 | 0.0186 |
| surf+term | 30 | 0.9150 | 0.0282 |

Term alone matches context alone; adding it to surface DILUTES (0.0307 ->
0.0282).

**Why — within-instant ranking of which expiry pays (3,930 mixed instants):**

| ranker | AUC |
|---|---|
| cheapness | **0.9160** |
| -surf_prem_vs_med | 0.8621 |
| -tteHours | 0.7672 |
| -term_resid_p5 (new) | 0.5811 |
| -term_resid_p0 (new) | 0.5293 |

Inside narrow tteHours bands term_resid gives 0.47-0.58, falling BELOW chance
beyond 120h.

**Correction to the framing.** `cheapness` (spot/premium), `stdMoneyness` and
`tteHours` are per-contract GLOBAL quantities — they never referenced a chain,
so they were never expiry-local. The model always had cross-expiry information
through them. Only the surface-SHAPE family was within-expiry. The term-structure
residual is genuine independent information (0.58) but is dominated by what
already existed.

**Viewer:** `build_surfaces.py` -> `surfaces.json` -> published artifact showing
36 events as strike x expiry tables, with a "model's view" toggle that dims all
but one expiry column.

---

# PART 3 — REGIMES, UNSUPERVISED STRUCTURE, AND SUCCESS CLUSTERING (2026-09-13)

Three questions, answered with the same controls as everything above: causal
labels only, weighted statistics, and **paired** bootstrap over non-overlapping
weekly blocks — filtered and unfiltered arms scored on identical resampled
weeks, so the CI is on the difference, which is the only quantity that can
justify a rule.

New code: `q1_regimes.py`, `q1b_signals_futures.py`, `q2_unsup.py`,
`q3b_clustering.py`, `q4_filters.py`, `q5b_verify.py`, `q6_final.py`.
Logs in `runs/`. New data: `runs/mktstate.parquet` (cross-sectional market state).

## 27. Q1 — the edge IS regime-dependent, and the direction is inverted

Five causal regime axes, each shifted a full day so nothing sees the bar it is
labelling. Top-0.5% policy on `oof_surface_25`, weighted, 110 weekly blocks.

| axis | state | top-0.5% EV | 95% CI |
|---|---|---|---|
| trend20 | down | +0.4303 | [-0.005, +0.868] |
| trend20 | sideways | +0.3509 | [+0.105, +0.645] |
| trend20 | **up** | **+0.0457** | [-0.169, +0.294] |
| pos60 | deep-drawdown | +0.4729 | [+0.213, +0.748] |
| pos60 | near-high | +0.1472 | [-0.170, +0.559] |
| dir20 | bear | +0.3850 | [+0.148, +0.641] |
| dir20 | bull | +0.2284 | [-0.027, +0.518] |
| vol20 | highvol | +0.3837 | [+0.133, +0.649] |
| vol20 | lowvol | +0.2895 | [+0.039, +0.581] |

Three separate axes agree: **deep-OTM buying pays in falling and range-bound
markets and stops paying in clean uptrends.** Baseline all-regime EV +0.3059.
The naive intuition (bull market -> calls moon) is backwards, because in an
uptrend the move is already priced and the OTM tickets are not cheap.

**The one rule that survives the paired test** (`q4_filters.py`, `q5b_verify.py`):

| filter | keep | EV | dEV | P(dEV<=0) | profit/wk change |
|---|---|---|---|---|---|
| **trend20 != up** | 82% | +0.3661 | **+0.0609** | **0.010** | -1.9 (p=0.62) |
| pos60 == deep-dd | 35% | +0.5025 | +0.1941 | 0.063 | -40.8 (p=0.92) |
| dir20 == bear | 48% | +0.4061 | +0.0995 | 0.110 | -34.8 (p=0.96) |
| vol20 == highvol | 29% | +0.3953 | +0.0866 | 0.256 | -59.6 (p=0.99) |

The narrow filters buy per-trade EV by throwing away opportunities and lose on
**profit per week**, which is the actual objective. Only `trend20 != up` raises
EV without costing throughput. Held-out half: dEV +0.0531, P(<=0)=0.096 — same
sign and size, underpowered at 54 weeks. Per year: 2024 -0.134 vs -0.140,
2025 +0.305 vs +0.269, 2026 +0.589 vs +0.491. Consistent in all three.

### 27b. How soon can a regime be named — measured, not assumed

| axis | mean block | median block | P(same +7d) | chance |
|---|---|---|---|---|
| vol20 | 15-20d | 8-10d | 0.73-0.82 | 0.50-0.57 |
| trend20 | 11-14d | 5-6d | 0.74-0.78 | 0.59 |
| dir20 | 8d | 2-3d | 0.72-0.76 | 0.50 |
| pos60 | 7-9d | 3d | 0.64-0.71 | 0.34-0.36 |
| **trend5** | **3d** | **3d** | **0.36-0.38** | **0.39** |

The 20-day label is causal (available the same day) and genuinely persistent —
knowing it today tells you something real about the next week. The 5-day version
is **at or below chance at a 7-day horizon**: it is noise. So the answer to
"which timeframe" is 20 days or slower; faster regime labels do not exist here.

### 27c. The otm_wall hypothesis — right about the ordering, wrong about the cause

| signal | sideways 25x | down | up | sideways 10x | up 10x |
|---|---|---|---|---|---|
| otm_wall | 1.57% | 1.21% | 0.98% | 5.03% | 3.34% |
| otm_red_squeeze | 1.74% | 1.66% | 1.22% | 5.71% | 5.15% |
| green_stairs | 1.27% | 1.09% | 0.87% | 4.58% | 4.07% |
| red_squeeze | 1.00% | 0.92% | 0.69% | 3.29% | 2.64% |

Sideways IS otm_wall's best regime — but it is *every* signal's best regime, and
"up" is *every* signal's worst. It is a market-wide effect, not something the
otm_wall shape captures. otm_wall stays the weakest ranker in every regime, and
the CIs overlap throughout. **The hypothesis is directionally right and
non-specific.**

### 27d. Regimes do NOT fix the timing problem

The binding constraint is between-episode AUC 0.5745 (FINDINGS 13). All regime
axes plus the cross-sectional market state, trained to rank episodes:
**AUC 0.5237, permutation null 0.4999 (95th 0.5306), p=0.090.** Does not clear.
Same verdict as arm 4 (0.5286, p=0.150). Regime conditioning improves the EV of
trades you were going to take anyway; it does not tell you when to trade.

The 24h futures classifier shows no usable regime dependence either — every
BTC-regime cell of the -15%/+5% top-5% slice sits within +-0.006 of zero.

## 28. Q2 — unsupervised learning finds real structure that is already known

**Chain-shape k-means (15 `surf_` features, fit on the first half of time).**
It finds a genuinely dead region: **40.5% of the universe with a 0.0027% 25x
rate**, against 0.15%+ elsewhere. That is real and large. It is also worthless,
because the supervised model already refuses it — the dead cluster is
**0.46% of the traded top-0.5% slice**. Held-out test across 3 values of k x 3
seeds: dEV +0.0004 to +0.0021, keep 100%. Nothing to add.

**Unsupervised spot regimes** (k-means on 12 PCs of the 105 Brooks features,
fitted on the first half, cluster to drop chosen by its training EV, applied
blind to the held-out half): 2 of 6 configurations significant, both at k=7
(dEV +0.04/+0.06, P<=0.001), nothing at k=3 or k=5. Median P(dEV<=0) = 0.205.
**Not established.** OOS cluster persistence is weak (P(same +1d) 0.31-0.41),
so these are daily states, not regimes.

**Cross-sectional market state** — the one genuinely new information channel,
since every other feature in the project is single-instrument. Built from the
129-perp daily panel (`runs/mktstate.parquet`): PC1 variance share, participation
N_eff, cross-sectional dispersion, breadth. Nothing clears:

| state | EV high | EV low | P(diff<=0) |
|---|---|---|---|
| N_eff | +0.4040 | +0.1208 | 0.096 |
| PC1 share | +0.1801 | +0.3847 | 0.819 |
| dispersion | +0.3496 | +0.3200 | 0.403 |
| breadth | +0.1831 | +0.2025 | 0.529 |

So unsupervised learning was worth running and returned one clean negative: on
this data it rediscovers what the supervised model has, and adds nothing on top.

### 28b. NEW TRAP — k-means cluster indices are not stable identifiers

`q4_filters.py` found "drop chain cluster 2" worth dEV +0.066 at P=0.007. It
replicated as -0.09 in the next script. Cause: cluster **indices are arbitrary**
and differ between runs, seeds, and subsamples, so "cluster 2" named a different
group in each file. The filter was excluding an arbitrary 14% of trades and the
significance was multiple-comparison noise across the six index choices.

**Rule: never carry a cluster by index. Identify it by a property measured on
the training half** (here: lowest weighted 25x rate), then apply that definition
blind. Doing so turned the +0.066/P=0.007 into +0.0005/keep-100%. Add to
DECISION_DOCUMENT section 4.

## 29. Q3 — successes do cluster, and pressing them is still ruinous

### 29a. The clustering is real but mostly double counting

| level | Fano (var/mean) | perm p |
|---|---|---|
| BTC contracts hitting 25x per week | **161.4** | 0.0000 |
| BTC *days* with any 25x, per week | **0.73** | 0.0003 |
| ETH contracts hitting 25x per week | 54.0 | 0.0000 |
| ETH *days* with any 25x, per week | 0.88 | 0.0000 |

The huge number is the known chain correlation — one BTC move prints 25x on
dozens of contracts. Collapsed to distinct move-days, over-dispersion against a
matched binomial null is much milder but still significant. 410 hit-days on BTC
collapse into **26 distinct move-clusters** over 110 weeks, median gap 6 days.
So yes: the paydays arrive in chunks, roughly two dozen of them in 2.7 years.

### 29b. But the clustering is not knowable in time to act on

Daily top-10-contract basket (weight-truncated, so no FINDINGS 13 inflation):
767 trade-days, P(basket profits) 19.04%.

| conditioning | n | P(win) | lift | p |
|---|---|---|---|---|
| lag-1: yesterday won | — | 32.88% | +13.82pp | **0.0000** |
| lag-2 | — | 20.55% | +1.46pp | 0.346 |
| **yesterday won AND the cash was in hand** | 56 | 25.00% | +5.96pp | **0.146** |

Only **38% of wins had paid out before the next entry**. Once you condition on
what you actually know at entry time, the lift halves and stops being
significant. And in EV rather than win-rate terms it inverts outright: the day
after a known payout returns **+0.1830 vs +0.3634** on all other days,
P(diff<=0) = 0.884.

### 29c. The Kelly arithmetic settles it regardless

Empirical top-0.5% distribution (hit 4.23%, mean R 1.3059, EV +0.3059):

| stake as % of bankroll | log-growth per trade |
|---|---|
| 1.00% | +0.00232 |
| 2.00% | +0.00351 |
| **3.05% (Kelly f\*)** | **+0.00389** |
| 5.00% | +0.00296 |
| 7.4% | **0 — growth turns negative above here** |
| 10.0% | -0.00522 |
| **25% (= pressing a 25x win on a 1% base)** | **-0.05199** |

**Pressing a 25x win into the next ticket stakes ~8.2x Kelly and converts a
+0.31-EV strategy into a bankroll that decays at 5% per trade.** Under the
realistic 10x-capture haircut from FINDINGS 7, EV is -0.127, f\* collapses to
0.2%, and every stake size loses.

The intuition behind the question is sound — clustered wins *should* reward
concentration. The correct response to clustering is **more tickets at the same
fraction**, never a bigger fraction per ticket. And 29b shows even that does not
pay here, because the cluster is only visible after it has passed.

## 30. What Part 3 changes

**Adopt:** skip the deep-OTM trade when the 20-day trend on the underlying is a
clean uptrend (efficiency > 0.35 and 20d return > 0). +0.061 EV per trade at 82%
throughput, P=0.010, consistent in all three years, held out at P=0.096. It is
the first regime rule in this project to survive a paired test.

**Reject:** every narrower regime filter (they cost more throughput than they
earn), unsupervised regimes and market-state conditioning, all forms of pressing
or parlaying winners.

**Unchanged:** timing is still not predictable — regime conditioning improves
trades you take, it does not find moments. And every absolute EV above is still
mark-price arithmetic (FINDINGS 7); the *relative* comparisons are what carry.

---

# PART 4 — FUNDING CARRY (2026-09-13/14)

New code: `fetch_funding.py`, `fund_study.py`, `carry_portfolio.py`.
New data: `data/funding/` (220 symbols, 8h rates, 2.7y), `runs/funding_carry.csv`,
`runs/carry_portfolio.csv`.

## 31. `FUNDING:` works on the candles endpoint — third prefix found

`/v2/history/candles?symbol=FUNDING:BTCUSD` returns OHLC of the funding rate.
`FUNDINGRATE:` and `FUNDING_RATE:` return 0 rows. Same one-line change as the
`MARK:` and `OI:` discoveries. **The project has only ever called two endpoints**
(`/v2/history/candles`, `/v2/products`) — no trades, no order book, no product
metadata. Every negative result in Parts 1-3 came from that single channel.

**Cadence resolved empirically:** the rate changes only on hours where
`hour mod 8 == 0` (DOGE 29/29 changes, PEPE 7/7, AAVE 9/9). So the quoted number
is a **per-8h percent** and annualised carry = `rate * 3 * 365`. Still worth one
confirmation against a real funding payment before sizing.

## 32. Delta India cannot support cash-and-carry, and it is structural

Product census (1,000 live): 452 calls, 428 puts, **112 perpetual futures**,
4 MOVE options, **4 spot pairs** — and **zero dated futures**. The spot pairs are
`BTC_INR`, `ETH_INR`, `SOL_INR`, `XRP_INR`, all quoted in INR against a
USD-quoted perp, so the hedge also carries a USDINR leg.

So exactly four perps can be hedged on-venue. Their carry:

| perp | spot leg | gross %/yr | % of 8h prints at the 0.01 clamp |
|---|---|---|---|
| ETHUSD | ETH_INR | 12.5 | 70% |
| BTCUSD | BTC_INR | 10.0 | 66% |
| SOLUSD | SOL_INR | 9.8 | 70% |
| XRPUSD | XRP_INR | 7.3 | 46% |

**And the 27 symbols paying above 20%/yr — AIO 97%, BLESS 89%, AIN 79% — are
hedgeable on Delta in exactly ZERO cases.** That is not bad luck; it is the
market being efficient in a boring way. Carry is available precisely where you
cannot lay off the risk.

Net of costs on the hedgeable four (0.20% one-off fees, 1.25x capital for the
margin buffer, 31.2% VDA tax):

| perp | gross | after fees | after capital | **after tax** | vs 7% FD |
|---|---|---|---|---|---|
| ETHUSD | 12.5 | 12.3 | 9.8 | **6.8** | -0.2 |
| BTCUSD | 10.0 | 9.8 | 7.9 | **5.4** | -1.6 |
| SOLUSD | 9.8 | 9.6 | 7.6 | **5.3** | -1.7 |
| XRPUSD | 7.3 | 7.1 | 5.7 | **3.9** | -3.1 |

**All four land below a fixed deposit**, for exchange risk, liquidation risk and
an unhedged USDINR leg. Same shape as the Nifty/NiftyBees version, different
mechanism: there it was SEBI margin with no cross-offset; here it is tax plus the
fact that the clamped symbols are the only hedgeable ones.

## 33. The cross-sectional carry spread — the carry is adverse selection

The median perp has **negative** carry (-10.9%/yr); only 35% are positive. So the
trade is not "short everything", it is a spread — short the top-decile funders,
long the bottom-decile — which needs no spot leg at all. Carry is also strongly
persistent: corr(this quarter, next quarter) = **0.461**, top quintile -> +19.8%/yr
next quarter, bottom quintile -> -41.3%/yr.

Monthly rebalanced, equal weight, 26 periods, ~117 eligible symbols, ~11 per leg:

| component | per month | annualised |
|---|---|---|
| funding collected | **+3.82%** | +56.9% |
| price p&l | **-2.03%** | -21.8% |
| gross | +1.80% | +23.8% |
| net of 0.20% | +1.60% | +20.9% |

Net +1.60%/month, 95% CI **[-2.06%, +5.19%]**, P(<=0)=0.188, 58% of months
positive, sd 9.2%. Not significant on 26 months.

**The leg decomposition is the finding:**

| leg | funding | price | total |
|---|---|---|---|
| LONG the negative funders | +4.50% | **-5.72%** | **-1.22%** |
| SHORT the positive funders | +3.14% | +1.67% | +4.81% |

Price p&l eats **53% of all funding collected**, and on the long leg it eats more
than 100% — you are paid to hold tokens that are dying, and the payment does not
cover the dying. That is the textbook objection to carry, confirmed here.
Survivorship flatters the long leg (only symbols alive at both month-ends are
eligible) and it still loses.

The only profitable leg is the short leg, and its +1.67% price component is the
**already-documented altcoin decay** from Part 1 sec 20 — a directional regime bet
that inverts in an alt season, not a carry edge.

**Verdict: hypothesis 14, FALSIFIED as a carry trade.** What looked like a
non-predictive structural edge is mostly compensation for adverse price selection
plus a re-discovery of short alt beta.


---

# PART 5 — NEURAL NETWORKS, AND A CORRECTION TO SECTION 22 (2026-09-14)

New code: `nn_futures.py`, `lgb_baseline_check.py`, `round2_tree.py`,
`pool_vs_solo.py`, `round2_nn.py`. Logs in `runs/`.

## 34. CORRECTION — section 22's BTC+ETH comparison is not like-for-like

Section 22 reads: "the edge is STRONGEST on the hedgeable pair: BTC+ETH alone at
24h gives **AUC 0.7024** vs 0.6840 pooled." Both numbers reproduce, but they are
measured on **different test populations** — 0.7024 on BTC+ETH rows, 0.6840 on
all-symbol rows. An AUC on one population cannot be compared to an AUC on
another, so that sentence does not support its own conclusion.

Reproduction (`round2_tree.py`, n = 1,704,048, matching `perp_oof_24.npz` exactly):
pooled AUC **0.6855** vs published 0.6840. The pipeline is faithful.

Like-for-like (`pool_vs_solo.py`) — **identical folds, identical 27,552 BTC+ETH
test rows, only the TRAINING SET differs:**

| training set | AUC on the same BTC+ETH test rows |
|---|---|
| BTC+ETH only (~46k rows) | 0.6942 |
| **all 129 symbols (~1.7M rows)** | **0.7319** |

**Pooling does not dilute the BTC+ETH edge — it creates it, by +3.8 AUC points.**
The practical rule inverts: **train on all 129 symbols, trade the two you can
hedge.** This is the same lesson as section 19 (3 symbols -> 129 fixed
calibration): the method is data-starved, not wrong.

Also worth recording: an earlier attempt measured BTC+ETH-only at 0.6614 because
the folds were built from BTC+ETH's OWN timestamp quantiles rather than the
pooled ones. Same data, same model, different test windows, 3 AUC points.
**Fold construction is a free parameter and must be stated with any AUC here.**

## 35. Neural networks, round 1 — identical folds, label and metrics

BTC+ETH, 24h, stop -15%/target +5%. 2 seeds for each NN, early-stopped on a
validation slice carved from TRAIN. EV is top-5%, maker/maker net.

| model | input | AUC | top-5% win% | top-5% EV |
|---|---|---|---|---|
| **LightGBM** | 105 Brooks | **0.6614** | 25.3% | +0.0020 |
| MLP | 105 Brooks | 0.5901 +-0.0024 | 17.3% | +0.0020 |
| GRU | raw 96-bar OHLCV | 0.5974 +-0.0055 | 17.1% | -0.0042 |
| LSTM | raw 96-bar OHLCV | 0.5769 +-0.0009 | 16.7% | +0.0010 |
| CNN | raw 96-bar OHLCV | 0.5029 +-0.0063 | 13.7% | -0.0024 |

Three separable facts:

1. **The tree wins by ~7 AUC points**, far outside the seed spread (+-0.006).
2. **It is the function class, not the input.** The MLP got the identical 105
   features and still lost 7 points. The signal is in the features; a net trained
   on 8k-31k rows extracts less of it than boosted trees do.
3. **The CNN on raw bars sits at chance (0.5029).** Representation learning on
   raw OHLCV recovered *less* than the hand-built Brooks features, not more. At
   this sample size the "RNNs are for timeseries" prior does not hold.

HANDOFF section 4's rule ("trees, not neural nets, at ~1-2k independent
episodes") was asserted without a number. It now has one, and it holds — but note
that the reason it holds is sample size, which section 34 shows is fixable.

## 36. Neural networks, round 2 — the NNs' best shot, and it still loses

Round 1 held the input fixed, which favours trees since the Brooks features were
engineered for one. Round 2 gives the NNs everything a tree cannot eat: all 129
symbols pooled (703k samples), a learned symbol embedding, raw 168-bar sequences
including VOLUME, and two CROSS-SECTIONAL channels (market median return and
dispersion) — the only genuinely new information channel in the project, since
every other feature describes one instrument in isolation.

Fold-matched against the pooled tree on identical windows:

| fold | tree pool | CNN | GRU | tree BE | CNN BE | GRU BE | tree EV | CNN EV | GRU EV |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.6713 | 0.6627 | 0.6610 | 0.7290 | 0.7065 | 0.7008 | +0.0075 | +0.0050 | +0.0041 |
| 2 | 0.6643 | 0.6464 | 0.6637 | 0.7263 | 0.6815 | 0.7115 | -0.0012 | +0.0275 | +0.0126 |
| 3 | 0.6571 | 0.6486 | 0.6576 | 0.6838 | 0.6650 | 0.6487 | -0.0009 | -0.0089 | -0.0138 |
| 4 | 0.7084 | 0.6942 | 0.6981 | 0.7173 | 0.6834 | 0.6989 | +0.0056 | +0.0042 | +0.0043 |
| **mean** | **0.6753** | 0.6630 | 0.6701 | **0.7141** | 0.6841 | 0.6900 | +0.0027 | +0.0069 | +0.0018 |

Tree wins **4/4 folds on pooled AUC vs CNN**, 3/4 vs GRU, and **4/4 on BTC+ETH AUC
vs both**. Transformer (fold 1 only, killed at 84 min/fold): pooled 0.6535,
BTC+ETH 0.7092 — the weakest and by far the most expensive.

**The one cell that looks like an NN win is noise.** CNN's mean top-5% EV
(+0.0069) exceeds the tree's (+0.0027), but the fold spread is +-0.0131 against a
mean of +0.0069, driven entirely by fold 2 (+0.0275 while the tree was -0.0012).
Per fold the tree still wins 3/4. Do not read that column as a win.

**What DID move was the data, not the architecture.** The CNN went from 0.5029
(exactly chance, round 1) to 0.6630 — the entire gain came from pooling, volume
and the market channels. Same lesson as sections 19 and 34: this project is
data-starved, and feeding the models more of the right data is worth far more
than changing the model family.

**Verdict: HANDOFF section 4's rule survives, now with numbers.** Trees beat MLPs,
CNNs, GRUs, LSTMs and a Transformer on this data, on both the engineered features
and the raw sequences, in round 1 and round 2. Cost matters too: LightGBM trains a
fold in ~1s; the GRU took ~20 minutes and the Transformer 84.
