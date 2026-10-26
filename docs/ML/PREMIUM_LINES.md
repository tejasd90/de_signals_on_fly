# Falling trendlines on the premium chart: flatter lines, bigger explosions? (26 Oct 2026)

His point, from NIFTY OCT 22600 CE and 22700 CE on 15m (`img/2026-10/2026-10-26_nifty_22600CE_15m.webp`,
`..._22700CE_15m.webp`):

> "the parabola initial part (prices shrinking part) has trendlines ... with flatter and flatter slopes. As the
> lines have more slope initially, the upward price explosions are less powerful, and more sideways ... As further
> fall ... seems unlikely, and THE TRENDLINES HOLD, we see more powerful explosions (like 1:3, 1:5 ...), and if time
> and price action permits, true multibagger."

On liquidity he added: in NIFTY, an A+ setup expecting 1:3 can turn ₹10 lakh into ₹30 lakh. That is about
NIFTY's depth, and it changes nothing in the crypto test.

Script `premium_lines.py` (`build`, then the analysis, then `control`). Rows: `data/premium_lines.parquet`.

## What was tested

There is no NIFTY option data here, so the test uses BTC/ETH Delta options (15m MARK, log premium, Jan 2024–23 Oct
2026):
- **Sample:** 2,652 contracts from 145 expiries, the 8 strikes nearest the money per expiry and side, alive at least
  4 days, using the last 10 days before settlement (the span of his charts).
- **Lines:** `levels.trendlines` on the premium chart. A falling line through 3 or more swing highs, usable only
  after it is confirmed (second anchor + 5 bars). Results are shown for lines spanning at least 12h and at least
  24h, the lines one would draw on a 10-day chart (about 10 per contract at 24h).
- **Break:** the first 15m close above the line.
- **Outcome:** the best later high within 24h compared with the break close (2x / 3x / 5x), and what the option
  is worth at expiry.
- **Comparison:** within the same asset × call/put × time-to-expiry bucket × premium-level quintile. CIs come from
  resampling expiries.

Three claims:
1. A flatter broken line gives a bigger move.
2. A line flatter than the previous one on the same contract gives a bigger move.
3. Later breaks in the sequence beat the first.

Plus a control: is a break any better than an ordinary moment?

## Results (lines spanning >= 24h; >= 12h agrees)

| broken line | n | ≥2x in 24h | ≥3x in 24h | ≥5x in 24h | worth at expiry (×) |
|---|---|---|---|---|---|
| steep third | 8,453 | 11.5% | 4.1% | 1.6% | 0.90 |
| middle | 8,431 | 11.8% | 4.6% | 1.5% | 1.00 |
| flat third | 8,474 | 14.1% | 5.8% | 1.7% | 1.19 |
| flat − steep (95% CI) | | +2.6pp [−0.4, +5.7] | **+1.7pp [−0.1, +3.7]** | +0.1pp [−1.0, +1.1] | **+0.28 [+0.01, +0.59]** |

- **Claim 2, flatter than the previous line:** the opposite happens. At 3x: 4.9% vs 6.2%, −1.4pp [−2.3, −0.4]. At
  12h: −1.1pp [−1.8, −0.5].
- **Claim 3, order:** the first break is slightly worse than later ones (stratum-adjusted −1.3pp). The 2nd, 3rd and
  later breaks are all about average.
- **His full story, two or more successive flattenings, then the break:** no better than other later breaks (−0.3pp
  [−1.4, +0.9]).
- **Control:** a random 15m bar on the same contract 3–12h away, at a premium within ±40% of the break. Break 3.06%
  vs control 3.42% at 3x, −0.36pp [−0.72, 0.00]. At 2x: 9.5% vs 11.4%. At 5x: 0.81% vs 0.90%.

## In plain English

- **A flatter falling line does break into a slightly bigger move**, as you said: 5.8% vs 4.1% reach 3x within a
  day. The gap is just short of significant, and the 5x rate is the same.
- **The clearer effect is what happens after the break.** After breaking a flat line, the option keeps more of its
  value to expiry (1.19x vs 0.90x of the break price). So steep-line breaks fade back, or move "more sideways" in
  your words, and flat-line breaks hold.
- **"Flatter and flatter" as a sequence does not add anything.** A line flatter than the previous one actually does
  a bit worse, and a run of flattenings is no better than any other later break.
- **The real problem is that a premium line break is no better than a random moment.** An ordinary 15m bar on the
  same option at a similar premium reaches 3x as often (3.4% vs 3.1%). Breaking a falling line on the option chart
  is not, by itself, a timing signal. This agrees with `PREMIUM_BASE.md` (base of higher lows: falsified),
  `LINE_HOVER.md` and `APPROACH_ENERGY.md`.
- **What this means for your NIFTY trade:** if you are in after a break, prefer one where the falling line was
  already flat; it keeps its value better if the explosion does not come. Don't treat the break itself, or the
  flattening sequence, as the reason to enter.

## Bounds

- **Crypto, not NIFTY.** NIFTY monthlies decay over weeks with deep liquidity and a VIX; Delta weeklies live about
  10 days. The geometry is comparable, the market is not.
- **MARK prices:** peaks are upper bounds.
- **Lines are found by code.** His eye picks perhaps 3–4 lines per chart; the code finds about 10 at a 24h span.
  The results agree at 12h and 24h.
- **The other parts of the idea were not tested separately:** "the trendlines hold" (the support side) and the
  squeeze. The premium-base test (higher lows holding) was falsified earlier.
