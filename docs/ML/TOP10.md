# The ten most promising findings, ranked

**Updated 2026-09-23.** Data current to 2026-09-23 (spot, all 220 perps, OI).
Ranked by evidence strength x effect size x robustness, not by headline number.

Break-even reference: an option needs a **4.33%** hit rate at a 25x target, or
**1.083%** at 100x, to cover the measured Delta round trip.

---

### 1. Cross-sectional market-neutral perp book — the strongest thing here
Rank 207 perps daily by 20-day realised volatility, long the calmest fifth, short
the wildest, beta-hedged. **+58.4%/yr, Sharpe 2.44, maxDD −18.2%, P=0.0003** over
142 weeks. Survives the survivorship fix (adding 22 delisted names: 61.6% →
60.6%), survives equal-risk weighting, capacity to ~$100M (47.6%).
**Weakness:** 119% of profit is the short leg — shorting illiquid alts, the
hardest thing to execute, and where the remaining survivorship doubt sits.
`xsec.py`, `xsec2.py`

### 2. Breadth is the structural lever, not better signals
Market-neutralising lifts effective breadth from **4.3 to 58.2** (mean pairwise
correlation 0.434 → −0.006). Since IR ≈ IC × √breadth, that is worth ~3.7x on
information ratio for identical skill. Every prior arm optimised the signal; none
questioned the structure of the bet. This reframes the whole project.

### 3. R4 — agreement with the 4h always-in state
**5.96% vs 3.89% base, P=0.000, and the ONLY rule that also works at 100x**
(1.799%, P=0.002). Fires in all 142 weeks. Timeframe swept 1h→weekly: broad
plateau 4h–12h, daily worse, **weekly actively harmful** (2.40%, dEV −0.368).
With R5 + containment it is also **the only figure backed by traded prices:
~6.0–6.3%**. `alwaysin_tf.py`

### 4. Breaks of levels rejected 3+ times
Break days carry **1.85x** the normal chance a 100x move starts (BTC 34.3% vs
18.5%, P=0.001; ETH 37.8% vs 20.9%, P=0.002). Tradeable form: buy **>10% OTM
aiming at 100x** — hit **2.22% vs 1.083% break-even, dEV +1.340, P=0.022** — while
**the same strikes off break days give 0.38%, dEV −0.379, P=0.995.** Survived a
look-ahead fix (levels were being priced with their own future).
`levels.py`, `levels_payoff.py`, `levels_dash.py`

### 5. Fakeouts do not matter to an option buyer
67% of level breaks close back within 10 days. hit100 on >10% OTM is **2.23% when
the break holds and 2.21% when it traps.** A trap is still a big move. This kills
the main objection to trading breaks — for option buyers, not for futures.

### 6. Break geometry pays on PUTS only
Channel-line AND trend-line broken together: puts **dEV +1.006, P=0.011**; calls
**−0.179, P=0.702**. Puts clear the direction control in all five forward-return
buckets; calls fail four of five. Robust to leave-one-month-out (P 0.002–0.027).
**Weakness:** fires in only 7 of 37 weeks in 2026. `channel_grid.py`, `maxt.py`

### 7. The grid path-length law
Grid gross income = path length × size, **independent of spacing**. Verified: gross
was ~$1.5M at every spacing from 2 to 50 points. So narrowing a grid only
multiplies fees. Also: leverage is irrelevant to a grid — peak margin at 200x was
$5,188 while the drawdown needed $151k–$916k. `grid_eth.py`

### 8. Tejas's containment rule
The green trigger's high AND close must stay below the first red candle's.
**2.17x lift, P=0.014** — the first pattern-shape feature to survive anything in
this project, and it came from his screen time, not from the data.

### 9. Grid and puts are one position, not two
A grid is short gamma; buying puts on downside breaks is long gamma. The put rule
fires on **24.2% of the grid's worst PnL days vs 6.3–8.5% of its best**. Since the
put rule is +EV standalone, it hedges the grid's left tail without paying carry.

### 10. Horizon separates two results that looked contradictory
Extended-down put breaks are the best option cell at horizons of **days**
(dEV +1.130, P=0.036) and the worst sustain at **60 days** (Q5−Q1 −6.86pp,
P=0.962). A crash into an oversold tape continues sharply, then mean-reverts.
Buy the puts; do not hold the view.

---

## What is dead, so it is not retried

Absorption / "calm before the move" (null everywhere, **adverse** on up-breaks,
and **significantly backwards** before level breaks: +15.5pp more traps in the
most compressed quartile). The 44 MA bounce (44 is not special; setup
underperforms its own control by −1.46% at 20d, P=0.964). Exhaustion lows
(1.0% base rate, nothing finds them — not candle shape, not **open interest**).
Open interest generally (orthogonal to price-vol: P=0.116). Buy-and-hold cheap
OTM (P 0.31–0.87). Options relative value on cheapness (P 0.41–0.77). Pyramiding
into pullbacks with rising size (needs 8.5x capital for 16%, and the median
pullback is 18.5% on majors). Funding carry (reproduced independently: −5.8%).
