# Smart money, defended strikes, decay timing and the three modes (2026-10-03)

Tejas's notes, 2026-10-03: manipulation happens at important points, not all the time
(Jane Street). All big play is through derivatives. Price returns to retail break-even,
then reverses. A contract that smart money doesn't want to explode tests a level many
times but never breaks it. An equidistant OTM pair where the gain beats the decay and
holds means an explosion is imminent. "We only know the times someone got caught", so
the tests below look for a statistical FINGERPRINT across every expiry, not for cases.
Also two never-tested observations from `context/Claude_Conversation_001.pdf`.

Scripts: `pair_strangle.py`, `fetch_opt_oi.py` (`data/opt_oi.parquet`: hourly option OI
over the final 30h, 299 expiries May–Oct 2026, 2 MB), `maxpain.py`, `decay_modes.py`,
`decay_traded.py`.

## In plain English

- **No fingerprint of strike defence or max-pain steering on Delta.** Settlement lands
  no nearer max pain than its mirror point (52% vs 50%), and heavily held strikes don't
  hold any better than empty levels at the same distance. That does NOT mean nobody
  manipulates anything. It means Delta's own option book is not what moves BTC; Delta
  settles on an index of bigger exchanges.
- **The equidistant pair adds nothing to finding multibaggers.** When it rises and
  holds, it only repeats what the recent spot move already says.
- **Your "sharp fall near market close" is real and daily:** 13:30–14:30 IST, in traded
  prices too. It's −10% of a strangle's value at 1 day to expiry and −3% at 2 days,
  mostly recovered by 19:00–21:00 IST. 13:30 IST is 08:00 UTC, when Deribit (the biggest
  crypto options venue) settles every day. **Practical: don't buy options in the hour
  before 13:30 IST, buy after 14:30. If selling, sell before 13:30.**
- **Your three modes, measured:** one side melts and the other goes sideways
  **59.6%** (you said 50–60%, spot on). Both melt **15%** (you said 30–40%). One melts and
  the other goes multibagger **19%** (you said 5–10%, and it is not fading much: 23% →
  18% → 18% by year).

## 1. Equidistant pair (`pair_strangle.py`)

At each hour 6–72h before expiry, strikes are locked at ±D around spot L hours earlier.
The feature is the pair ratio now vs then (gain beat decay if > 1), whether it held ≥ 1
for 3 hours, and its peak. Train on the first half of expiries, test on the second.

| D, lookback | 2% spot move in 24h: AUC controls → +pair | 10x option: AUC controls → +pair |
|---|---|---|
| 1%, 6h | 0.8187 → 0.8195 (+0.001, CI spans 0) | 0.599 → 0.598 |
| 2%, 12h | 0.8134 → 0.8178 (+0.004) | 0.593 → 0.590 |
| 3%, 24h | 0.7883 → 0.8182 (+0.030) | 0.582 → 0.579 |

The controls are the trailing spot move over the lookback, 24h realised vol, the pair's
price as % of spot, time to expiry and hour of day. The apparent +0.03 at 3%/24h only
recovers what the 6h trailing move already gives (0.819). **Multibaggers: negative at every
setting.** Within each tercile of the trailing move, "pair > 1 and held" has a LOWER 10x
rate (9.1–11.6%) than pair ≤ 1 (8.6–13.5%).

## 2. Max-pain pull and defended walls (`maxpain.py`)

| window | price ended closer to max pain than to its mirror (% of spot) | CI | closer to MP |
|---|---|---|---|
| final 24h | +0.004 | [−0.107, +0.119] | 52% |
| final 6h | −0.058 | [−0.173, +0.054] | 51% |
| final 3h | +0.022 | [−0.081, +0.140] | 52% |
| control 24h → 6h | +0.024 | [−0.080, +0.129] | 52% |

Max pain sits a median 0.14–0.19% from spot: OI spreads around wherever price is, so max
pain follows price.

Walls are the biggest call-OI strike 0.5–2.5% above spot and the biggest put-OI strike
below it, taken 24h out (median distance 1.6%). They are compared against the mirror
level at the same distance:

| | settles beyond: wall vs mirror | touched: wall vs mirror | held after touch: wall vs mirror |
|---|---|---|---|
| call wall | 18.5% vs 21.1% | 35.6% vs 41.3% | 48% vs 49% |
| put wall | 22.8% vs 20.1% | 38.3% vs 39.6% | 40% vs 49% |

Nothing is significant, and the put wall breaks slightly MORE often after a touch.

**What this does not cover:**
- Deribit/Binance positioning, where BTC's options weight actually sits.
- Index-level manipulation in Indian markets (the Jane Street case was Bank Nifty
  expiry days). That needs the NSE data the Kite pipeline in `context/` was built to fetch.
- His break-even-trap idea: it needs positions. His own Delta fills would test it: does
  price return to his average and reverse more often than for random entries at the same
  times?

## 3. The 13:30–14:30 IST cliff (`decay_modes.py` A, `decay_traded.py`)

The ±2% OTM strangle's mean hourly log-change, MARK, in the bar ending 14:30 IST: −7.0%
(1–2 DTE), −4.2% (2–3), −2.4% (3–5), −1.0% (5–10). Neighbouring hours are near 0.
Partial rebound at 19:00–21:00 IST (+1 to +4.6%).

Traded check on a sample of 2026 expiries, strangle change in that bar vs the 11:30–12:30
IST bar:

| | 1 DTE | 2 DTE |
|---|---|---|
| MARK | −9.9% vs −1.6% | −5.6% vs −0.1% |
| TRADED | **−10.5% vs −1.0%** | **−3.1% vs +0.0%** |

Deribit's 08:00 UTC daily settlement is a likely explanation: implied vol re-marks as the
front expiry rolls off. It is NOT verified, but nothing else falls on that hour every day.
At 2–10 DTE the 24h average is about 0, so options are fairly priced on average. This is
timing within the day, not a free carry.

## 4. Three modes (`decay_modes.py` B)

99 expiries with ≥ 7 days of life. A 5%-OTM call and put are chosen 7 days out and held to
expiry. Per side: multibagger = peak ≥ 10x; melt = ends ≤ 0.2x without reaching 2x; else
sideways.

| mode | his estimate | measured |
|---|---|---|
| one melts, other sideways | 50–60% | **59.6%** |
| both melt | 30–40% | 15.2% |
| one melts, other multibagger | 5–10% | **19.2%** (2024 23%, 2025 18%, 2026 18%) |
| both sideways | — | 6.1% |

Not yet tested: whether mode 1 can be identified early (his question), and the averaging
P&L he describes in that mode.

## Remaining never-tested observations from `context/`

Ranked list from the context review, 2026-10-03:
1. the sqrt(1+DTE)·body/open "premium exhausted" ratio
2. premium falling >2x faster than theta, then a sharp move
3. decay following a parabola of the lows
4. option OI vs past expiries as an event feature (the OI fetcher now exists)
5. trendline + round-number confluence
6. averaging into the trend side in mode 1

Items 1–3 are option-premium SHAPE claims. Note that ~140 shape features have been inert,
and only containment survived.

---

## 5. Follow-up 2026-10-03: ideas as directions, evolving markets, the quiet-before-the-storm picture

Tejas: the ideas are **directions to think in**, not rules to be judged by their average.
They work "at specific points". Markets evolve: event reactions changed from "good news up",
to "vs expectations", to now "hyped events yield nothing but volatility" (FOMC, NFP), while
the real breakout (Aug 19–21) came after an unusually quiet weekend and a week that held up.

### Hyped events (`event_hype.py`)

Short ATM straddle that spans the release, vs the same entry hour on ordinary days. MARK,
net of the bid haircut and fees.

| | event-day IV vs normal | 2024 seller net | 2025 | 2026 |
|---|---|---|---|---|
| FOMC (16:00 UTC entry, 20h tenor) | 1.27–1.33x every year | **−1.24%** (seller wins 13%) | −0.01% (69%) | **+0.40%** (58%) |
| NFP (approximate dates) | 1.14–1.23x | +0.13% | −0.03% | −0.20% |

The option market charges the same FOMC premium every year, while the move it pays for has
shrunk. Buying the FOMC straddle went from clearly profitable in 2024 to losing in 2026. That
matches his "hyped, yields nothing except volatility, traps option buyers". It is only 6–8
independent events a year, so the evolution is visible but not proven.

### What was visible before the 30 biggest 3-day moves (`bigmoves.py`)

Delta perp hourly with real volume and OI. Percentiles are causal, against the previous 365
days, as of the close before the move. The 15 largest non-overlapping per asset since 2024
are all ≥ 9.5% in 3 days.

- **Aug 19 2026 was exactly as he remembers:** BTC 7-day realised vol at the **1st**
  percentile, weekend range **2nd**, 5-day range **7th**, price at 81% of its 7-day high
  range (held up). ETH: 0th / 0th / 0th.
- **Big moves come in two kinds:** quiet-before-the-storm (ETH May-24, BTC Apr-25, ETH May-25,
  ETH Jul-25, Aug-26) and continuation of already-wild markets (Mar-24, Aug-24, Mar-25, Feb-26).
  The median precursor percentile is ~0.45–0.55. No single sign covers both kinds.
- **The "Aug-19 picture"** (quiet weekend AND low-vol week AND held up, all ≤ 0.3 / ≥ 0.6):
  175 days, P(big move) 7.4% vs 3.0% base (2.45x). It is robust across 6 cut choices (1.5–2.9x).
  - **Counted as episodes it is not significant:** 6 of 43 episodes hit vs 3.4 expected,
    P = 0.12.
  - **All 6 hits were UP moves,** vs 57% up for big moves overall (~3% by chance).

### As a trade (`quiet_calls.py`)

Calls 3–6% OTM, 3–8 days, bought at 00:00 UTC on the first day of each episode, held to
expiry, net of the 8.26% cost.
- **Mean +6.44 per unit vs +0.71 on other days.** But ONE trade (BTC 18 Aug 2026, 186x)
  carries it. The other 32 average ≈ +0.8, the same as the baseline.
- 10x hit rate 12% (4/33) vs 3.9%.
- Puts in the same episodes: nothing (+0.38 vs +0.18).

### What this says about "at specific points"

Specific points are, by construction, rare. In 2.7 years there are ~30 moves of this size,
in two different kinds, and ~6 of the quiet kind. No method can separate a real precursor
from coincidence on 6 events. The data can say the picture is *consistent with* his reading
(right sign, right direction, 2.45x), and the forward log is what will settle it. The cost of
acting on it is small, because cheap OTM calls lose ~1 unit when nothing happens.

**Shape of a rule worth trying small:** when the Aug-19 picture appears, hold a small,
fixed-size position in 3–6% OTM calls, 3–8 days out, and accept ~90% losers. Don't size it
from this backtest. It is one 186x trade plus noise.

## 6. Crowd anticipation and pattern rotation (`crowd_rotation.py`, 2026-10-03)

Tejas: the market rewards few. What people anticipate mostly doesn't happen, and when it does
it overshoots past where they book out (FOMO → volatility → sideways → trend). Patterns exist but
ROTATE, which traps people into expecting the last one to repeat.

**Crowd lean → opposite outcome?** Two measures, each a causal percentile:
- option skew: ±2% OTM call vs put premium, 24–72h tenor;
- funding: 24h perp funding.

Rank correlation with the next 24h/72h return is −0.012 to +0.038 in every year. Calls rich vs
puts rich are NOT followed by the opposite move, nor by the anticipated one. The crowd's lean is
already in the price and pays neither side. Funding is clamped at 0.01 for long stretches
(`de-signals-funding-endpoint`), so its top decile is empty in 2025–26.

**Patterns rotate?** 4 signals × 33 months, monthly 25x rate per event.
- **The raw rank correlation of +0.68 is a fixed ranking, not momentum:** otm_red_squeeze is the
  month's best in 64% of months, green_stairs in 33%, red_squeeze in 3%, otm_wall in 0%.
- **After removing each signal's own long-run level,** month-to-month correlation is +0.02 (lag 1),
  +0.11, +0.01, −0.05 (lag 6).
- **Per-signal lag-1 autocorrelation is −0.16,** inside the shuffled null [−0.19, +0.14]: a hint of
  reversal, not significant.

**Reading:** a good month for a pattern says NOTHING about next month. That is his trap exactly:
the last pattern seen is not more likely to repeat. The long-run ordering of patterns IS stable,
though. Keep the ranking, ignore the recent streak.
