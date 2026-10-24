# Sideways approach to a level: more breaks, bigger blasts? (24 Oct 2026)

His words, 26 Sep: *"price sideways approaching a trendline is more likely to result into breaking and blast (as not
much effort in sideways movement so energy is there) as opposed to rising/falling to reach the trendline ... Might
also want to check for support/resistance, or 20EMA."* Two claims: it **breaks** more, and it **blasts** more.
Script: `approach_energy.py`. Data: BTC/ETH MARK, Dec 2023 → 23 Oct 2026, 1h / 4h / 6h. 23,036 first touches:
trendlines 10,169, EMA20 12,222, horizontal S/R 645. Results: `data/approach_energy_touches.parquet`,
`data/approach_energy_results.csv`.

## In plain English

- **Not supported. Sideways approaches do not break more, and their breaks do not blast more. If anything, the
  steep approaches blast a little more.**
- **Break within 24h**, all levels: sideways **84.1%** vs directional **85.0%** (−1.0pp, CI −2.5 / +0.7). Trendlines
  look like a +5pp win for sideways, but that is geometry: a sloped line keeps moving into a price that goes
  nowhere, so it gets crossed without any push. Compared at the same line slope the gap is 0 (−0.8, +1.5, +0.7pp,
  all within noise). On the 20 EMA sideways approaches break **less** (−6pp). Horizontal S/R +4pp, not
  significant (only 429 touches).
- **Blast after the break** (biggest move in the break direction within 24h): **≥3%: 23.5% sideways vs 26.9%
  directional (−3.4pp, CI −6.0 / −0.8)**. ≥2 ATR: 47.1% vs 48.4% (−1.3pp, noise). Median blast on 4h: 1.64% vs
  2.05%; on 6h: 1.56% vs 2.34%. The steeper the timeframe, the more the directional approach wins.
- **Both claims together** (touch → break → ≥3% blast): 19.8% vs 23.3% (−3.5pp, CI −5.8 / −1.2).
- Once approaches are compared from the same starting distance, the blast gap shrinks to noise (−1.8pp ≥3%). So
  the honest reading is "no difference", not "the opposite is true".
- One exception that is not his claim: on **weekends** sideways approaches break more (+4pp) and blast ≥2 ATR more
  (+7pp, CI +1 / +12). That is weekend quietness (small ATR), the same thing WHEN_NOT_TO_TRADE found.
- This is the seventh form of "stored energy before the move" to come back null (see TOP10.md, approach.py on
  28 Sep). His 20 EMA observation does not survive either.

## Definitions (all causal)

- **Levels**, each usable only once known:
  - trendline: `levels.trendlines(max_span=400)`, >= 3 touches, usable from confirmed_i + 1 (confirmed_i >= anchor2
    + 5) until its first close through.
  - horizontal S/R: two swing highs (or two swing lows) within 0.6 ATR (`levels.horizontal_levels`); level = mean
    of the first two swings, usable 5 bars after the second swing (when it becomes visible), until its first close
    through; dropped if price closed through it before then.
  - EMA20: EMA of closes through the previous bar; support if the previous close was above it, else resistance.
- **First touch**: a bar reaches within 0.3 ATR of the level from its own side; the previous bar did not, and price
  closed >= 1.2 ATR away since the last touch.
- **Approach** over the K = 6 or 12 bars before the touch bar: efficiency ER = |net move| / sum of |bar moves|.
  **Sideways** = bottom tertile (ER about 0.00–0.17, mean 0.06 for K = 12); **directional** = top tertile and moved
  toward the level (ER about 0.24–1.0, mean 0.49). Tertiles within timeframe x level type.
- **Break** = a close through the level within 24h of bars (also checked: within 6 bars). **Blast** = biggest move
  in the break direction over the next 24h after the break close, in % and in ATR of the break bar.
- **Control**: compared within spot x timeframe x level type x side (support/resistance) x weekend, weighted to the
  sideways mix. "+start" also matches the start distance from the level K bars earlier (quartiles).
- CIs: 90%, weekly block bootstrap. Halves split at 21 May 2025.

## Break within 24h (K = 12, sideways vs directional)

| subset | sideways | directional | diff, pp | 90% CI | n sideways / directional |
|---|---|---|---|---|---|
| **all** | 84.1% | 85.0% | **−1.0** | −2.5 / +0.7 | 7,679 / 3,550 |
| trendline | 82.8% | 77.8% | +5.0 | +3.4 / +6.8 | 3,390 / 2,855 |
| trendline, same line slope (3 tertiles) | | | −0.8 / +1.5 / +0.7 | each includes 0 | 683–1,586 per cell |
| horizontal S/R | 71.6% | 67.3% | +4.3 | −2.9 / +12.8 | 215 / 214 |
| EMA20 | 85.8% | 92.0% | **−6.2** | −8.6 / −3.7 | 4,074 / 481 |
| 1h | 91.5% | 90.4% | +1.1 | −0.3 / +2.6 | 5,463 / 2,535 |
| 4h | 69.9% | 77.5% | −7.6 | −11.3 / −3.9 | 1,343 / 613 |
| 6h | 59.2% | 63.1% | −3.9 | −12.1 / +5.9 | 873 / 402 |
| BTC / ETH | | | −0.5 / −1.5 | both include 0 | |
| 1st half / 2nd half | | | +1.3 / −2.4 | 2nd: −4.2 / −0.4 | |
| weekday / weekend | | | −2.8 / **+4.3** | −4.8/−0.8 ; +2.0/+6.9 | 5,668 / 2,011 sideways |

Robustness, all levels: K = 6 +1.0pp (−0.7 / +2.6); break within 6 bars −2.2pp (−4.2 / −0.0); split on net
travel toward the level instead of ER +2.5pp (+1.5 / +3.6, again driven by trendline geometry); + start-distance
control +3.9pp (−0.9 / +7.2); fixed thresholds ER < 0.25 vs > 0.6 (K = 6) +3.5pp (+0.7 / +5.9).

## Blast after the break (K = 12)

| subset | ≥3% sideways | ≥3% directional | diff, pp (90% CI) | ≥2 ATR diff, pp (90% CI) | n breaks sideways / dir. |
|---|---|---|---|---|---|
| **all** | 23.5% | 26.9% | **−3.4** (−6.0 / −0.8) | −1.3 (−4.1 / +1.5) | 6,455 / 2,812 |
| trendline | 24.5% | 29.6% | −5.1 (−8.1 / −1.9) | −3.4 (−6.2 / −0.3) | 2,806 / 2,225 |
| horizontal S/R | 33.1% | 36.0% | −2.9 (−14.2 / +6.7) | +2.9 (−9.3 / +12.7) | 154 / 146 |
| EMA20 | 22.3% | 24.4% | −2.1 (−6.2 / +1.8) | +0.2 (−4.5 / +5.0) | 3,495 / 441 |
| 1h | 23.0% | 25.0% | −2.0 (−4.7 / +0.9) | +1.4 (−1.5 / +4.3) | 4,999 / 2,161 |
| 4h | 25.9% | 33.4% | −7.5 (−14.6 / −1.1) | −7.6 (−14.7 / −1.3) | 939 / 411 |
| 6h | 24.1% | 34.0% | −10.0 (−20.3 / +0.2) | −16.2 (−28.0 / −5.3) | 517 / 240 |
| 1st half / 2nd half | | | −6.3 / −2.0 | −2.6 / −0.5 | |
| BTC / ETH | | | −1.8 / −5.2 | −1.0 / −1.6 | |
| weekend | 17.7% | 17.7% | −0.0 (−3.8 / +3.8) | **+6.8** (+1.4 / +12.4) | 1,802 / 699 |
| all, + start-distance control | | | −1.8 (−6.8 / +3.1) | +3.7 (−2.0 / +9.0) | |

Median blast after a break, sideways vs directional: 1h 1.46% vs 1.68%; 4h 1.64% vs 2.05%; 6h 1.56% vs 2.34%.
Touch → break → ≥3% blast, all levels: 19.8% vs 23.3% (−3.5pp, −5.8 / −1.2).

## Bounds

- MARK prices, no volume. Blast is a best-case excursion (bar highs/lows), not a tradeable exit.
- Horizontal S/R has only 645 touches (2-swing levels that survived until usable); its CIs are wide.
- ER tertiles are cut on the full sample (a threshold choice, not a feature leak); fixed thresholds agree.
- Fixed ER > 0.6 over 12 bars is rare (824 touches, 4 on EMA20) and those rows are not used for conclusions.
- Touches of near-duplicate trendlines on the same bar count once; different lines on nearby bars do not, so the
  trendline n overstates independent events (the weekly bootstrap allows for this).
