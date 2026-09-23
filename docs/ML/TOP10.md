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


---

# The same ten, with the setup and what the numbers mean

Plain English. "Break-even" = the hit rate an option needs just to cover Delta's
fees: **4.33%** aiming at 25x, **1.083%** aiming at 100x.
"P" = the chance of seeing a result this good by luck, measured by resampling
whole WEEKS (because option jackpots cluster into a few weeks, so counting
individual trades as independent would be fiction).

### 1. Cross-sectional low-volatility perp book
**Setup.** Every 5 days rank all 207 crypto perpetuals by how jumpy their price
was over the last 20 days. Buy the calmest fifth, short-sell the wildest fifth,
equal money each side, then cancel out whatever market exposure is left.
**Strength.** +58.4% a year. Sharpe 2.44 means return divided by how bumpy the
ride was — above 2 is very good, so the profit arrived steadily rather than in
one lucky month. Worst losing stretch 18.2%. P=0.0003 is a 3-in-10,000 chance of
luck across 142 weeks. Still worth distrusting: 119% of the profit is the
short-selling half, which is the hardest half to actually execute.

### 2. Breadth is the lever, not better signals
**Setup.** Not a trade — a design rule. Stop betting on whether crypto goes up;
bet on which coins beat the others. Subtracting each day's average move removes
the thing that makes all coins move together.
**Strength.** Owning 158 coins is really about 4 bets, because they rise and fall
as one (average pairwise correlation 0.434). After removing the common move it
becomes 58 genuinely separate bets. Results improve with the SQUARE ROOT of the
number of bets, so √(58.2/4.3) ≈ 3.7 times better outcomes from identical skill.

### 3. R4 — agree with the 4-hour trend
**Setup.** Buy a call only when the 4-hour chart is leaning up (price above both
moving averages, faster one above slower). Buy a put only when it leans down.
Skip everything else — about three quarters of signals.
**Strength.** 5.96% of kept signals reach 25x, against 3.89% for taking
everything and 4.33% needed to break even. So it moves you from losing to
winning. P=0.000, and it fires in every one of 142 weeks. It is also the ONLY
rule that survives at a 100x target (1.799% against 1.083% needed).

### 4. Breaks of levels rejected 3+ times
**Setup.** Find a trendline or horizontal level that has turned price away three
or more times. Do nothing until a daily CLOSE goes past it — wicks do not count.
Then buy options more than 10% out of the money, aiming at 100x, not 25x.
**Strength.** 2.22% reach 100x against 1.083% needed — roughly double break-even.
"dEV +1.340" means each trade earns 1.34 stakes more than not filtering. P=0.022.
The clincher: the SAME strikes on non-break days hit only 0.38% and lose
confidently (P=0.995), so the break is doing the work, not the strike choice.

### 5. Fakeouts do not matter to an option buyer
**Setup.** Not a rule — permission to ignore the obvious objection. Two of every
three breaks reverse back through the level within 10 days.
**Strength.** Of contracts bought on break days, 2.23% reach 100x when the break
holds and 2.21% when it traps. Identical. You are paid for the MOVE, and a trap
is still a move. This is fatal for a futures trader and irrelevant to you.

### 6. Break geometry pays on puts only
**Setup.** When the trend line AND the channel line both break in the same
direction on the daily chart, buy puts. Never calls.
**Strength.** Puts earn +1.006 stakes per trade over the baseline (P=0.011);
calls LOSE 0.179 (P=0.702) and are worse than buying at random. Puts also beat
the "is this just direction betting" control in all five buckets while calls fail
four of five. Weakness: it fired in only 7 of 37 weeks in 2026.

### 7. The grid path-length law
**Setup.** Not a trade — a law that kills a whole family of ideas. A grid's gross
income equals the total distance price travelled multiplied by your position
size, and does NOT depend on how tightly you space the orders.
**Strength.** Gross income was ~$1.5M at every spacing tested from 2 to 50 points
— dead flat. So tightening a grid multiplies your fee bill and adds nothing. Also
measured: leverage is irrelevant to a grid, because peak margin at 200x was
$5,188 while the drawdown needed $151k–$916k.

### 8. Your containment rule
**Setup.** In the two squeeze signals, the green trigger candle must keep BOTH
its high and its close below the first (largest) red candle's high and close. If
it pokes above either, throw the signal away.
**Strength.** Contained triggers reach 25x 4.34% of the time versus 2.00% for the
ones it rejects — a 2.17x lift, P=0.014. It throws away 28.7% of triggers. This
is the only pattern-SHAPE feature that has ever survived here, and it came from
your screen time rather than from the data.

### 9. The grid and the put signal are one position
**Setup.** If you ever run the grid, buy the put-break signals as its hedge
instead of buying protection blindly.
**Strength.** The put rule fires on 24.2% of the grid's worst days versus 6.3–8.5%
of its best — about three times the concentration, exactly where the grid bleeds.
And because the put rule makes money on its own, the hedge pays you to hold it
instead of costing carry.

### 10. Horizon reconciles two results that looked contradictory
**Setup.** When a breakdown happens into an already-oversold market, buy puts
with DAYS to expiry. Do not hold the bearish view for months.
**Strength.** On options at day-scale, that exact state is the best cell measured
(+1.130 stakes per trade, P=0.036). On spot at 60 days, the same state has the
WORST hold rate (19.4% → 12.4% across quintiles, P=0.962). Both significant,
pointing opposite ways, because they measure different horizons. A crash into an
oversold tape continues sharply for days, then mean-reverts over months.
