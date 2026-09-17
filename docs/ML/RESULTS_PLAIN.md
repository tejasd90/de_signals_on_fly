# What we found — in plain English

**Updated 2026-09-17.** Technical version: `CONTEXT_PLAN.md`. This one avoids
jargon.

Two parts. **Part A is what to do.** Part B is the full log of everything tried,
kept so we do not repeat it.

---

# PART A — WHAT TO DO

## The rules

**1. Direction.** Take the signal only when it agrees with which way the market
is already leaning on the **4-hour** chart — price above both moving averages
with the faster above the slower means up, the mirror means down, anything else
means unclear and you skip.

> Buy calls only when the 4h picture is up. Buy puts only when it is down.

Use **EMA 20 and EMA 100** (tuned; the 20/50 pair we started with was slightly
worse, and slower is better at every timeframe tested).

**2. Regime.** Stand aside entirely when the **daily chart has been in a clean
uptrend for the last 20 days** — defined as 20-day efficiency above 0.35 with a
positive 20-day return. Rule 1 collapses to 2.09% inside that regime, worse than
taking everything.

**3. Pattern.** For the two squeeze signals, the green trigger must **close and
top out below the first (largest) red candle**. Already built into the signal
code, so it applies automatically.

**4. Then hold to expiry.** Do not manage the position. Every exit rule tested
loses money — see Part B.

## What it is worth

Per trade, after the real Delta cost of getting in and out (8.26% of premium).

| | 25x rate | per trade |
|---|---|---|
| break-even | **4.33%** | 0 |
| take every signal (traded prices) | 3.51% | **−0.21** |
| **rules 1+2+3 (mark prices)** | **6.91%** | **+0.65** |
| **rules 1+2+3 (real traded prices)** | **6.01%** | **+0.42** |

You keep about **1 signal in 5**.

**Be clear about the margin: 6.01% against a 4.33% break-even.** That is a 39%
cushion. If the hit rate slips to 4.5% you are at roughly zero. This is a real
edge and a thin one.

## How much to bet

**Kelly says 2.0% of bankroll per trade. Half-Kelly is 1.0%.** That is the
ceiling, and it is the honest measure of how thin this is. About 94% of these
trades lose everything; the whole return lives in a 6% tail.

## What NOT to do

- **Do not cut a loser that fades.** Tested at every holding period and every
  threshold — 48 combinations, all negative. Faders are 72% of trades but 61% of
  all the 25x outcomes.
- **Do not wait for confirmation before entering.** Tested 15 ways, all
  significantly negative. You pay for the confirmation.
- **Do not chase trend-line breaks**, especially weekly ones — measurably harmful.
- **Do not take small profits.** 2x and 5x targets have negative expectancy.
- **Do not add to winners.** Pressing is ~8x Kelly and the log-growth is negative.

## The one idea worth carrying in your head

Sorting every result by *what kind of thing* was measured gives the clearest
pattern we have found:

**Things that WORK all say "something is still intact":**
the market is aligned · the daily trend has not gone one-way · the squeeze has
not been undone · price has not yet broken the line.

**Things that FAIL all say "something has already happened":**
a breakout · a trend line breaking · follow-through · a three-push move
completing · a wedge forming · an exhaustion bar · a climax · a big energetic
move · cutting a loser · waiting for confirmation.

Ten of the second kind fail. Four of the first kind work.

And we know why, because we measured it: **in a loud market the same ₹5 buys a
strike 36% further out of the money.** By the time something is visible on the
chart, it is in the option price. You are paid for what has NOT happened yet.

This explains several results at once. Your containment rule worked where ~140
other pattern features failed because it is the only one asking "is this still
intact" rather than "how big was this". Sustainability forecasts well but cannot
be traded because acting on it — cutting, or waiting to confirm — converts the
intact state into a finished event. High energy pays less for the same reason.

*Caveat worth stating: this story was assembled after seeing the results, which
is when a story is most tempting. It earns its keep only because it made a
prediction we then tested — that a state which has persisted longer should pay
less — and that held on two of three measures (4.41% down to 1.94% as price stays
away from its average longer).*

**What it means for you practically:** stop looking for the move to start. The
rules already encode this — they ask whether the market is aligned and whether
the setup is still coiled, not whether anything has fired.

## What is still unverified

- **Trade size.** Prices are real; whether you could get filled in size is not
  measured. This is the last open question before a live position.
- **19% of signals never fill at all** — the mark crossed the trigger, the market
  did not. Carry that in any forward expectation.
- **Everything rests on 142 independent weeks.** Held in all three years, which
  is good evidence and not proof.

---

# PART B — THE LOG

Everything tried, kept so it is not repeated.

## 1. The question

Your signals fire about 400,000 times in 2.7 years. Most go nowhere. The idea we
tested was yours: **a signal is not good or bad on its own — it depends on what
the wider market was doing at that moment.**

So: can we read the price action around each signal and tell in advance which
ones are worth taking?

---

## 2. The short answer

**Yes, and it is one sentence:**

> Take the signal only when its direction agrees with which way the market is
> already leaning on the 4-hour chart. Skip it otherwise.

"Which way the market is leaning" is Brooks' *always-in*: if you were forced to
be long or short right now, which would it be? We measure it mechanically —
price above both moving averages with the shorter above the longer means *up*,
the mirror means *down*, anything else *unclear*.

**Buy calls only when the 4-hour picture is up. Buy puts only when it is down.**

---

## 3. What it is worth

Per trade, after the real Delta cost of getting in and out (8.26% of premium,
verified against their live fee data).

| | take every signal | take only the agreeing ones |
|---|---|---|
| how often a 25x happens | 3.8% | **5.9%** |
| average result per trade | **you lose 0.15** | **you make 0.41** |
| trades kept | all | about 1 in 4 |

"Lose 0.15" means: for every ₹100 of premium, you end with about ₹85. "Make
0.41" means about ₹141.

**The headline is the sign change.** Taking every signal loses money. Taking the
quarter that agree with the 4-hour trend makes money. This is not a tweak — it is
the difference between a losing activity and a profitable one.

It also survives the obvious objection. We checked whether this is just "calls do
well when the market rises", which would be useless because you cannot know that
in advance. It is not. Holding fixed *what the market actually did next*, whether
it was a call or a put, how far out of the money it was, and how long it had to
expiry, the agreeing signals still hit 25x about **twice as often** — in 31 of the
38 groups we could measure.

---

## 4. We then tested 33 more ideas. None of them added anything.

This is the part worth dwelling on. After R4 worked, we built **every rule in
your Brooks summaries that this data can test** — 30 of them — plus your three
follow-up ideas.

Each was tested twice: alone, and *on top of R4*. The second is what matters,
because a rule that only restates R4 will look good alone and add nothing.

**Seven rules looked good alone. Zero added anything on top of R4.** The best
"does it add" result across all of them had roughly a 1-in-7 chance of being
noise — nowhere near good enough to act on.

Several actively *hurt* when stacked on R4: trading breakouts in your direction,
three-push moves, follow-through, wedges.

---

## 5. Things we proved wrong

**Buying at the edge of a range does not work — the opposite does.**
Brooks says fade the extremes: buy low in a range, sell high. On your data that
is one of the worst things you can do, and the only rule that loses money per
week as well as per trade. What works is the reverse: calls near the *top* of the
recent range, puts near the *bottom*. Momentum, not mean reversion.

*This includes the ETH example you sent.* It paid 1:20 and was a real trade. But
across 113,803 events the pattern behind it loses. We tested it three separate
ways — including the exact cross-timeframe version you described, rangebound on
the 4-hour with a rejection on the 1-hour — and that version hits 25x **less than
half as often as average**, one of the worst cells available.

There is a reason, and it ties the study together: **a rejection at a range
extreme is a countertrend trade, and R4 is a with-trend rule. They are opposite
strategies.** When we intersected them, only 6 events survived out of 113,803.
They cannot both be right, and R4 is the one with the evidence.

**Brooks' "single most important rule" does not hold here.**
Never trade against a trend until the trend line breaks. Not distinguishable from
luck, and it disappears once you control for which way the market actually went.

*You were right about one thing here.* You said breaks should allow for a few
points of overshoot rather than being declared on an exact touch. We rebuilt it
that way and the rule improved at every step — a wider tolerance gave a steadily
better result. It still did not reach significance, but your correction was real
and measurable, and every future break test now carries a tolerance.

**The higher timeframe does not overrule the lower one.**
When the 1-hour and daily readings disagree — 35% of the time — following the
daily gives 4.46% and following the hourly 4.41%. A coin flip.

But your instinct pointed at something real, just elsewhere. **What matters is
agreement, not seniority.** Both agree: 6.68%. One disagrees: ~4.4%. Neither
agrees: 3.05%. So when a signal fails it is not that a bigger timeframe was
holding against it — it is that the timeframes disagreed, and disagreement tells
you nothing. Stand aside.

**Signal strength is worthless — you were right to want it gone.**
We ran everything twice, with and without your strength numbers. Identical to
three decimal places. Delete them at no cost. The *shape* of the signal says when
to look; the *context* decides whether to act.

---

## 6. Your two ideas about "which bars matter"

Both were good enough to build, and both came back negative — but the second one
came back negative for a reason worth understanding.

**Culmination vs accumulation.** Your framing: some bars resolve something
(a rejection, a failed breakout, an exhaustion bar), most just build toward it.
You were right that nothing encoded this — every label we had was a flat
presence flag, so a rejection off an extreme and a lazy pullback counted the
same. Built it. Culmination bars hit 25x **3.32%** against a 3.84% base. Slightly
worse, not better.

**Significant vs regular (energy).** Your refinement: 3–4 strong trend bars are
accumulation *structurally* but significant *energetically*, and they pay. This
was the best idea in the whole study, because **every other rule answers "which
way?" and this one answers "how much?"** — and a multibagger needs both.

Built at each signal's own timeframe, as you asked. The result was inverted and
very consistent:

| market energy | 25x rate |
|---|---|
| quietest fifth | **4.02%** |
| middle | ~3.8% |
| loudest fifth | **3.47%** |

The loudest fifth was worse on 7 of the 8 timeframes we could measure.

### And here is why — this is the most useful negative in the study

It is not noise. We controlled what you *paid* (premium 2–20) but not what you
paid *for*:

| | how far out of the money | time to expiry | premium | 25x rate |
|---|---|---|---|---|
| quiet market | **7.12%** | 37h | ~$5 | 4.00% |
| loud market | **9.72%** | 50h | ~$5 | 3.64% |

**The same ₹5 buys you a strike 36% further away when the market is loud.** The
extra time does not make up for it.

So your intuition about the market is *correct* — big moves really do follow big
moves, volatility clusters. It is simply already in the price. You pay for the
movement before you get it. This is a known effect (the volatility risk premium)
and it runs against option buyers.

The inverse — buy when things are quiet — is weakly real on its own but does not
add to R4 either.

---

## 7. The machine-learning attempt lost to the one-line rule

We trained a model on all 175 available measurements. It did worse than the
sentence in section 2 — and that sentence was one of its inputs, ranked 29th of
175 in how much it used them.

Cutting it from 175 inputs to 7 **quadrupled** its performance. That is the real
problem in one number: 2.7 years is only about 142 independent weeks, and you
cannot fit 175 dials with 142 observations.

**So we are shipping a rule, not a model.** Simpler, applies by eye, honest.

---

## 8. What you can now see in the tool

Click any square on 3900 or 3800 and a panel opens beside it showing what the
price action actually was at that moment, in five tiers:

1. **measured to predict** — the always-in check. The only one that works.
2. **structural role** — culmination or accumulation. Measured, does not add.
3. **energy** — which fifth, quietest to loudest. Measured, inverted.
4. **context** — trend lines, range position, wedges, three-push. Descriptive.
5. **structure** — bar mechanics. Not scored.

Each is shaded by how often that kind of price action reached 25x. The tiers are
labelled so the tool never implies an untested thing matters.

*You asked for shading by the maximum ratio.* We could not use it honestly: the
biggest ratios sit on ₹0.55 contracts where one tick is a "900x", and every label
co-occurs with one of those eventually — three different labels all report a
maximum of 4616x. Shading by maximum would have made the whole panel glow. It is
shaded by hit rate instead, with the maximum shown as text.

---

## 9. What we did NOT build

We used your new `Brooks/*.md` summaries for everything and did not use the older
`brooks_features.py` at all. But some things remain unbuildable or unbuilt:

**Cannot be built from this data**, and were excluded rather than faked:
- anything about how a bar behaved *while forming* — needs tick data
- volume rules — spot candles carry no volume, and Brooks rates volume unreliable
- day-type rules (trend from the open, the 11am trap) — crypto is 24/7

**Built too crudely to be a fair test:**
- **Tight trading ranges.** "A tight range trumps everything" is one of his
  strongest claims, but our threshold fires on 0.3% of bars, so the rule keeps
  99.7% and tests nothing. Needs recalibrating before any conclusion.
- **Spike vs channel phase.** We flag single big bars; Brooks means a phase
  lasting many bars. His advice inverts between the two, so a feature that cannot
  tell them apart averages two opposite rules and finds nothing. Probably the
  biggest remaining gap.
- **Established lines.** Your point that a channel line is only definable after it
  forms, but then projects forward, is untested rather than refuted — we proxied
  "established" with a regression fit, and Brooks means *touches and rejections*.

---

## 10. What would most likely help

1. **Paper-trade R4 forward.** Every new week is genuinely new evidence, and
   independent weeks are the one thing this project is short of. Nothing else
   adds any.
2. **Check it on real traded prices.** Everything here uses *mark* prices — the
   exchange's fair-value estimate, not prices anyone paid. Comparisons survive
   that; the money figures do not. Cheap now, because R4 keeps only a quarter of
   events.
3. **Proper spike-vs-channel detection**, and recalibrated tight ranges. The two
   places where a fair test has not happened.
4. **More markets.** Indian stocks and F&O — see `INDIA_PLAN.md`. The only route
   to more independent time, which limits everything.

---

## 11. What you should not trust

- **The exact money figures.** Mark prices are not fill prices. Direction and
  ranking are trustworthy; "+0.41 per trade" is not a number to size on.
- **That it keeps working.** It held across all 142 weeks and all three years.
  Good evidence, not proof.
- **Anything below 30-minute charts.** Not tested, at your request.
- **XAUT.** 11,931 events, no daily chart data. Effectively untested.

---

## 11b. Later findings (2026-09-17)

**A second rule that works** (we call it R5 in the technical doc). Stand aside when the daily chart has been in a clean
uptrend for the last 20 days. It stacks on top of the first one:

| | trades kept | 25x rate | per trade | per week |
|---|---|---|---|---|
| take everything | 100% | 4.03% | lose 0.08 | −48 |
| agree with the 4h trend | 25% | 6.26% | make 0.48 | +78 |
| **...and skip clean daily uptrends** | **22%** | **6.83%** | **make 0.63** | **+87** |

**Your containment rule works** — the green candle must close and top out below
the first red. Contained setups hit 25x at **4.34%**, rejected ones at **2.00%**:
a 2.17x difference, P=0.014 on weekly blocks. It is the first pattern-SHAPE rule
in this project to survive a proper test; roughly 140 earlier shape features were
all inert. It removes about 20% of signals.

**Your sustainability observation — right about the market, wrong as an action,
and I reported it backwards at first.** Whether an option holds its ground in the
first six bars genuinely forecasts what is still to come (2.55% if it collapses,
6.41% if it holds). But CUTTING the faders loses money: hold-to-expiry makes 0.63
per trade, cutting makes −0.29. The reason is that faders are 72% of trades but
**61% of all the 25x outcomes** — 3.35% of them come back anyway. You would be
saving a premium already down 30% and giving up the tail that pays for
everything. Every cut threshold loses.

**Brooks' trend-line rule still does not pay, and now we are sure.** We suspected
the earlier negative was our own bad tooling — our "trend lines" were 30-day
regressions, and on your ETH chart one came out sloping UP while the real line
sloped down. We rebuilt them properly (they now find your 372-day line and flag
the break on the day it broke, on daily and weekly). Tested again: still nothing
on daily, and **significantly harmful** on weekly. By the time a weekly line
breaks, the move is already priced.

---

## 11c. Tuning pass (2026-09-17) — parameters measured instead of guessed

Five numbers had been picked by eye. All swept, full grids reported, and only a
coherent REGION of agreeing cells treated as real.

- **R4 (direction):** slower moving averages are better at every timeframe.
  4h with EMA 20/100 gives 6.20% against 5.96% for 20/50. Small but coherent.
- **R5 (regime):** the sweep peaks on exactly the values already in use — 20
  days, efficiency 0.35. The surrounding grid is flat, so it sits on a plateau
  rather than a spike. **Nothing to gain.**
- **Tight trading range:** previously flagged as never really tested — the old
  threshold fired on 0.3% of bars, so the rule kept 99.7% and tested nothing.
  Recalibrated across a sensible range: monotone toward the base rate, every cell
  negative EV. **Brooks' "a tight range trumps everything" does not hold here.**
- **Sustainability:** swept 8 holding periods x 6 thresholds = 48 cells for
  cutting, and 15 for delayed entry. **All 63 negative.**

**Total gain from tuning: +0.08pp** (5.94% -> 6.01% on traded prices). Noise.

What tuning bought was confidence, not performance: the parameters sit on
plateaus, so the edge is not an artifact of five numbers chosen by eye. That was
the real risk and it is now measured.

## 11d. The forward log, and what is now being recorded

`paper_log.py` writes every signal to `paper_trades.csv` BEFORE the outcome is
known — 2,541 from the last 10 days, 505 TAKE and 2,036 skip.

**It records the skips deliberately.** Without them the file is a record of
trades taken; with them it is a forward TEST of whether the filter was right.

Each row carries the 4h always-in state, the 20-day regime, both rule verdicts,
the distance to the daily and weekly structural lines, and a `note` column for
your reasoning at the time. That note column is the conviction journal the
decision document asks for — it is the only way "do my discretionary reads beat
the rules?" ever becomes answerable.

Run `--run` daily (seconds) and `--report` weekly.

One thing the first run revealed: **every current signal is deep past its
structural line** (`w_room` around -2.6 to -9.0), so none are in the interesting
13.29% cell. That is honest, not broken — BTC has run a long way from its
descending structure. It also shows why that cell cannot be settled by more
analysis: it is rare, and only elapsed time accumulates it.

## 11e. Things checked today that led nowhere

- **Strike selection inside a signal.** The old work found a near-perfect strike
  picker; combining it with the new timer looked promising. Dead: the median
  qualifying signal has ONE strike, and perfect hindsight only reaches 7.04%
  against 6.55%.
- **Freshness of alignment as a third rule.** Looked strong alone (7.43% vs
  3.89%) and failed where it counts — marginal to the existing rules, P=0.13-0.24
  with negative profit per week.
- **Trend line age and touch count.** Neither rescues the break rule. Better
  confirmed lines break WORSE (2 touches 2.44%, 4+ touches 1.45%).

## 11f. We tested Brooks properly, and he does not work here (2026-09-18)

Everything before this judged his ideas by whether an OPTION paid off. That was a
weak test — he never claimed to forecast option payoffs, he claims to forecast
PRICE. So we ran his setups directly on spot and scored them his way: is there a
60% chance of making at least your risk?

**Ten setups, 220 crypto instruments, 141 weeks, 258,402 occurrences.**

Nothing reached 60%. Everything landed between 41% and 54%, and the pooled figure
was 48-49% — which is what a coin flip looks like. His own headline claims did not
hold: failed breakouts (he says ~80% of range breakouts fail) came in at 42-48%,
and countertrend scalps (he says beginners lose 70%+) were no worse than his
with-trend pullbacks.

Then the fairer test, because he argues a 40% trade with a big reward is fine: we
swept the reward from 1x risk to 5x risk. **All 100 combinations lost money.** The
best was break-even to within a rounding error (P=0.52). And costs are not the
culprit — fees are about 4% of one unit of risk against losses of 9-36%.

**Two things we cannot claim.** These are our mechanical readings of his
descriptions, and twice this week a "failure" turned out to be our own
mis-specification. And the weekly timeframe — the one he now favours — is still
too thin to test, 725 setups across 68 weeks.

**Also tested: your inverse idea** — look for signals firing NEAR a setup rather
than the other way round. Same-bar co-occurrence (your ETH case) is real: 4.96%
against 3.89%, and the effect fades as the window widens, which is the shape of
something genuine. But it does not add on top of the existing rules, and the best
cell anywhere is 7.54% — nowhere near the 40% that would be transformative.

## 12. One-line summary

Your signals lose money taken as they come. Filtered to the quarter that agree
with the 4-hour trend, they make money. That single filter beat a 175-input
machine-learning model and 33 other ideas, and the strength numbers you wanted to
delete turned out to be worth exactly nothing.
