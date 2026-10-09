# Added-assumptions audit (2026-10-09)

He objected that the premium-base test carried restrictions that were not part of his idea (a minimum
time to expiry, one timeframe, a cheapness cap copied from his example). This audit lists the same kind
of analyst-added restriction in every KEPT setup, then removes each one and measures what happens.
**Nothing in `SETUPS.md` is changed yet; he decides what to keep.**

Origin key: **T** his idea · **D** forced by data or cost · **A** the analyst's choice.

## What was found

| Setup | Restriction | Origin | Removed → result |
|---|---|---|---|
| 1 | premium 2–20 | A (a project-wide comparison band, never a trade rule) | **<2 is as good or better** (below) |
| 1 | calls only | partly T ("resolves up") | puts on picture days ≈ break-even; adding them dilutes |
| 1 | BTC/ETH only | A | XAUT: 2 picture days with signals, nothing to measure |
| 1 | cuts 0.3 / 0.3 / 0.6 | the idea is T, the numbers are A | a smooth plateau, not a picked peak (below) |
| 1 | signals ≥ 30m | A (`build_events --min-duration 30`) | **not yet removed:** 5–20m signals are on disk but not built into events |
| 3 | 1–3d to expiry | A | ≤1d nothing; **3–8d larger but not significant** |
| 3 | 00:00 UTC entry | A | **every 4h slot works** (below) |
| 3 | 70th pct threshold | A | every threshold 50–90 works |
| 3 | ATM, hold to expiry | A | not yet varied |
| forward log | no 2–20 band, first strike only, traded high ÷ mark close | mismatch with the backtest | noted; the log is not the same population as Setup 1 |

## Setup 1 with restrictions removed (`setup1_relax.py`, MARK; `setup1_sub2_traded.py`, TRADED)

**Picture-day BTC/ETH calls, R5 not vetoing.** "close" = all rows, bought at the signal close.
Asset-days, not calendar days.

| premium | events | 25x (close) | 100x (close) | 25x TRADED | 100x TRADED | EV100 traded |
|---|---|---|---|---|---|---|
| **< 2** | 4,678 | 11.4% | 7.3% | **10.3%** | **7.1%** | **+6.02** |
| 2–20 (kept) | 3,814 | 9.6% | 5.3% | 10.6% | 5.1% | +3.99 |
| > 20 | 5,027 | 4.6% | 2.1% | — | — | — |
| all | 10,838 | 8.8% | 5.2% | — | — | — |
| not picture, 2–20 (reference) | 56,002 | 3.0% | 0.85% | | | |

**Under $2, on traded prices:**
- 1% never traded;
- the median fill is 0.90× mark;
- the 25x week-block CI is [3.5, 16.8]%.

**Caveats:**
- **Lumpy.** 93% of its 100x hits come from 3 weeks (10–23 Aug 2026 ETH, his original Aug 19–21 picture,
  plus Jul 2025). Without the single best week: 25x 7.6%, 100x 4.1%, still above break-even.
- **ETH-only.** BTC under $2 is only 3.0% at 25x; ETH is 11.9%.
- **Floor fills.** Fills ≤ 0.1 (the price floor) do worst (25x 4.9%); fills 0.11–2 carry it.
- **Depth unknown.** The depth at a 100x exit on a sub-$1 ETH call is unmeasured.

**Calls only → puts too (2–20, close):**
- puts 4.0% at 25x, EV −0.07;
- calls + puts 6.5%;
- the picture's "resolves up" reading holds.

**Thresholds** (all premiums, close; 25x rate (asset-days)):

| wkend, rv7 ≤ | dd7 ≥ 0.4 | 0.5 | **0.6** | 0.7 | 0.8 |
|---|---|---|---|---|---|
| 0.2 | 10.7% | 10.3% | 10.3% | 9.5% | 21.5% (15) |
| **0.3** | 8.8% | 8.6% | **8.8%** | 8.0% | 19.1% (19) |
| 0.4 | 7.4% | 7.0% | 7.0% | 6.6% | 13.9% |
| 0.5 | 6.5% | 6.3% | 6.6% | 6.3% | 10.8% |

- Quieter is monotonically better.
- "Held up" is flat from 0.4 to 0.7; the ≥ 0.8 cells are too few days to trust.
- 0.3 / 0.3 / 0.6 is mid-plateau, not tuned to a spike.

## Setup 3 with restrictions removed (`setup3_relax.py`)

Held out Dec 2025 → 7 Sep 2026, net % of spot per straddle, quiet vs rest, week-block CI.

| tte | entry | quiet | rest | diff CI | P |
|---|---|---|---|---|---|
| **1–3d** | **00:00 (kept)** | +0.164% | −0.279% | [+0.11, +0.78] | 0.005 |
| 1–3d | 04 / 08 / 12 / 16 / 20 | +0.21 / +0.13 / +0.24 / +0.38 / +0.18 | −0.18 / −0.16 / −0.26 / −0.02 / −0.16 | | 0.007–0.058 |
| 1–3d | **all hours pooled** | +0.215% | −0.171% | [+0.07, +0.73] | 0.004 |
| ≤1d | all hours | +0.011% | +0.009% | [−0.17, +0.16] | 0.46 |
| 3–8d | all hours | +0.710% | −0.255% | [−0.50, +2.54] | 0.10 |

- **Threshold:** for 1–3d, every threshold works: q50 +0.24 vs −0.32 … q90 +0.67 vs −0.13 (P ≤ 0.01). Stricter
  thresholds earn more per trade on fewer trades.
- **3–8d:** larger means at q80/q90 (P 0.03–0.04), but CIs span zero at q70. Untested tail; a candidate,
  not a rule.

## Rising parabola only (premium base v4)

Falsified with no decay requirement: 913k rising-parabola moments, 25x 0.66% vs 0.71% matched, level on every
timeframe / tte / strike / decay depth. His 7 Oct 81000P and 80000P examples fire. See `PREMIUM_BASE.md` v4.

## Decisions for him

1. **Setup 1 premium band:** keep 2–20, or drop the lower bound (≤ 20, or < 2 as its own leg)? Traded says
   under $2 pays at least as well, but it is lumpier, ETH-heavy, and its depth is unknown.
2. **Setup 3 entry hour:** allow any 4h slot (the evidence says yes)?
3. **Setup 3 3–8d:** watch forward only, or allow?
4. **Signals under 30m:** build them into events and re-test (heavy: needs disk and a rebuild)?
