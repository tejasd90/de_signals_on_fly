# NSE / BSE option data: pipeline (20 Nov 2026)

Code in `nse/` (Node, no dependencies; runs on the Windows VM that holds the data and on the Mac).
The data never leaves the VM. Paths below are the VM's.

## What exists

| program | does |
|---|---|
| `nse/calendar.js` | Holidays and special sessions (his lists from `explosion_after_premium_eroded_signal/utils.js`, 2026 added), session times. |
| `nse/group.js` | 1-minute candles → 5m, 10m, 15m, 25m, 1h, 75m, 125m, 1d, 1w; one gzip file per contract. Reads the per-day folders, the combined files, or the `.tar.gz` archives directly; cleans damaged files while reading. |
| `nse/read.js` | Reader; the two views of the 15:30–15:40 minutes; the close-to-close view; spot from the chain. |
| `nse/signals_run.js` | Runs the crypto signal modules (`signals/otm_red_squeeze.js`, `green_stairs.js`, `otm_wall.js`, unchanged) on a chain, both views, plus `otm_red_squeeze_c2c`. |
| `nse/fetch_expiry.js` | Downloads every contract expiring on a date as ONE file per contract (replaces `generate_candles_weekly_fo.ps1` + the combine step). **Not yet run against live candles:** the saved token had expired; first real run is the 23 Nov monthly expiry. |

## Rules in `group.js`

- **Sessions:** only normal trading days. Holidays, Muhurat and Saturday special sessions are dropped; so are pre-open minutes.
- **Session length:** 09:15–15:30; from **2026-08-03** 09:15–15:40 (every day from that date has minutes 15:30–15:39 in the
  data, none before).
- **Lead-in:** candles before the first traded minute (volume 0, a stale reference price) are dropped.
- **Gaps:** a missing bar inside the contract's life is flat at the previous close, volume 0, previous OI, up to the close
  of the expiry session.
- **Anchor:** every intraday bar is anchored at 09:15. 1w is Monday–Friday.
- **The two views of the extra ten minutes** (his request): stored as their own bar on the 5/10/15/25/75/125 grids
  ("separate"); `read.toCandles(rows, 'merged')` folds them into the bar before. 1h, 1d and 1w are the same in both.
- **Small timeframes only near expiry** (as in the crypto config): 5m last 2 trading days, 10m last 4, 15m last 8,
  25m last 16; 1h and above for the whole life.
- **Cleaning:** files where PowerShell turned arrays into `{"value":[...],"Count":n}` or dates into `/Date(ms)/`, in UTF-8
  or UTF-16, are read correctly. Sources are never modified.

## Layout on the VM

```
F:\nse\grouped\<expiry>\<TRADINGSYMBOL>_<token>.json.gz     {s, t, e, first, last, n1, c: {"5": [[ts,o,h,l,c,v,oi],...], ..., "1w": [...]}}
F:\nse\grouped\<expiry>\_report.json                         counts, dropped days, days with no data
F:\nse\signals\<expiry>\<UNDERLYING>.json                    every firing with entry, later peak, x, xEnd
F:\nse\logs\group_all_0.log, group_all_1.log                 the bulk run
```

A weekly index expiry is about 2.3 MB grouped (the archive is 8–12 MB, the extracted 1-minute files far more).

## Checks done

- **Three sources agree.** Expiries 2022-09-01, 2023-10-10, 2025-09-09 and 2026-01-13 grouped from the archive, the
  per-day folders and `combined_js` give byte-identical output (821 contracts).
- **Archives are not one-per-expiry.** `F:\minute_tars` has split and oddly named parts (`2024-05-30_0_5700_7000_12700`,
  `2024-05-30_remaining`, `2022-12-29_*`, `2024-01-25_*`, `2024-09-26_stocks`, `2023-12-29`); `2024-05-30.tar.gz` alone
  holds 8 contracts. The bulk run therefore reads `combined_js` for expiries to 14 Jan 2026 and the new archives after.
- **Holiday list vs data (Aug–Nov 2026):** 14 Sep, 2 Oct, 20 Oct, 10 Nov have no data; 8 Nov (Sunday, Muhurat) has a
  short session and is dropped.

## First look: November 2026 expiries

Raw firings (no strike merging, no opposite-direction filter), entry at the trigger close, entry ≥ ₹1, traded bar:

| expiry | contracts with a firing that later reached 100x | example |
|---|---|---|
| 3 Nov NIFTY | 0 (best 59x) | 23500 CE, 15m, 29 Oct: 5.25 → 311.9 |
| 5 Nov SENSEX | 21 | 77900 CE, 1h, 29 Oct: 5.1 → 1,650 (324x) |
| 9 Nov NIFTY | 28 | 24600 CE, 25m, 29 Oct: 1.85 → 517.7 (280x) |
| 12 Nov SENSEX | 4 | 79900 CE, 25m, 2 Nov: 9.1 → 2,647.7 (291x) |
| 17 Nov NIFTY | 9 | 24600 CE, 125m, 28 Oct: 4.7 → 910 (194x) |
| 19 Nov SENSEX | 0 (best 21x) | |

**Read with this beside it:** the index rose about 10% from 28 Oct to 9 Nov. In those expiries ANY traded bar of a cheap
out-of-the-money call (price ≤ spot/1000, entry ≥ ₹1) reached 100x 23–32% of the time (5 and 9 Nov, 25m–125m), against
3–12% for the firings; no put reached 25x. That comparison is not matched on strike distance or time and is six expiries.
The matched test over all 622 expiries comes after the bulk grouping.

### Daily-timeframe firings, 26–29 Oct 2026 (his case 1)

His reading, given 20 Nov with two NIFTY charts (kept locally in `data/shared_charts/2026-11/`, not in git): weekly support on
the rising line from early 2024; the daily falling line from August broken and retested; 29 Oct the clean bounce off it.
"With news, price action and signals combined, buying these cheap 1:100 trades was possible on 26–29 Oct"; the daily
signals are what he missed seeing by hand.

NIFTY implied by the chain, daily close: 23 Oct 22,659 · 26 Oct 22,870 · 27 Oct 22,781 · 28 Oct 22,753 · 29 Oct 23,031 ·
2 Nov 23,391 · 5 Nov 24,548.

Daily (`1d`) firings in the weekly expiries, one row per contract, entry at that day's close:

| trigger day | expiry | contracts fired | outcome |
|---|---|---|---|
| 26 Oct | 9 Nov NIFTY | 5 calls (23900–24500 CE, entry 5–21) | all ≥ 50x; three ≥ 100x (24400 CE 5.8 → 704, 121x) |
| 26 Oct | 5 Nov SENSEX | 2 calls (77700, 78000 CE, entry 21–29) | 63x and 72x |
| 26 Oct | 3 Nov NIFTY | 1 call (23600 CE, entry 15.55) | 13.6x |
| 27 Oct | 3 Nov NIFTY | 2 calls (23950, 24400 CE, entry 1.85–3.35) | expired near zero (0.9x, 1.0x best) |
| 28–29 Oct | all six | none on `1d` | |

All are `otm_red_squeeze` or its close-to-close variant. The 26 Oct daily firings were on the next-but-one expiries; the
nearest expiry's firings (3 Nov) paid least. The November monthly (23 Nov) is not collected yet. This is one episode; over
its whole life the 9 Nov expiry had 218 daily firings, so the 26 Oct ones are picked by his context, not by the signal alone.

## All history, signal bars against matched ordinary bars (21 Nov 2026)

Grouping finished: 622 expiries (Aug 2022 – 19 Nov 2026), no unreadable file, none needed cleaning. `signals_run.js --all`
wrote 2.51 million raw firings on the seven index chains. `nse/baseline.js` then counted every traded bar of the same chains.

**The comparison** (`nse/baseline_report.py`): a signal bar is compared with the traded bars of the SAME expiry, index,
timeframe and side that sit in the same bucket of days to expiry, distance out of the money and option price, and where that
signal did not fire. Out-of-the-money bars with close ≥ ₹1 only. Stored view (15:30–15:40 as its own bar). x = highest later
high ÷ trigger close. Intervals are 90%, bootstrap over expiries.

| signal | firings | reached 10x: signal vs matched bars | reached 25x | reached 100x |
|---|---|---|---|---|
| otm_red_squeeze, calls | 122,585 | 3.17% vs 2.88% (diff +0.19 to +0.40) | 1.03% vs 0.95% | 0.16% vs 0.15% |
| otm_red_squeeze, puts | 139,562 | 3.38% vs 3.17% (+0.13 to +0.28) | 0.98% vs 0.89% | 0.08% vs 0.08% |
| close-to-close squeeze, calls | 123,957 | 3.15% vs 2.85% (+0.20 to +0.40) | 1.02% vs 0.93% | 0.16% vs 0.15% |
| close-to-close squeeze, puts | 140,881 | 3.37% vs 3.12% (+0.17 to +0.33) | 0.98% vs 0.86% | 0.07% vs 0.07% |
| green_stairs, calls | 133,225 | 3.02% vs 4.45% (−1.66 to −1.20) | 1.02% vs 1.41% | 0.12% vs 0.16% |
| green_stairs, puts | 159,941 | 2.65% vs 3.89% (−1.44 to −1.06) | 0.59% vs 0.90% | 0.04% vs 0.05% |
| otm_wall, calls | 103,482 | 6.07% vs 9.55% (−4.18 to −2.81) | 1.75% vs 2.78% | 0.19% vs 0.24% |
| otm_wall, puts | 142,693 | 3.60% vs 7.65% (−4.80 to −3.32) | 0.51% vs 1.46% | 0.01% vs 0.04% |

- **Squeeze:** a small lift that is unlikely to be chance, on 5m to 1h (about 3.4% against 3.0% at 10x). It is gone on 75m and
  125m and turns negative on 1d (3.14% vs 3.51%; close-to-close 3.12% vs 3.79%) and 1w. No lift at 100x on any timeframe.
- **Close-to-close variant:** the same as the original everywhere.
- **Green stairs and wall:** worse than comparable ordinary bars on every timeframe and every index.
- **NIFTY daily calls** (his case 1 timeframe): squeeze 3.14% vs 4.09% over 209 expiries. The 26 Oct 2026 firings were good
  because every cheap call of those expiries was good.
- NIFTY, SENSEX and BANKNIFTY give the same picture. Full table: `data/nse/baseline_report.json` (local).

**Not usable yet: value held to expiry.** The script also sums last close ÷ trigger close. Ordinary near-the-money bars average
about 2x on that measure, which cannot be right: the grouped series is filled flat from a contract's last trade, so a contract
that stopped trading keeps a stale price to the end. It must be replaced by the settlement value from the index close before
any hold-to-expiry or P&L number is quoted. The peak multiples above do not depend on it.

**Also not done:** the merged view of the 15:30–15:40 bar, the processor's strike merging and filters, costs and slippage.

## Review page in the dashboard (21 Nov 2026)

`/nse` on the one dashboard (:8777): `dash_nse.py`, `nse.html`, routes in `dash_server.py`. Pick index, expiry and timeframe;
each row is one alert (trigger bar × side) with its strikes; a strike opens the index and the option on that timeframe with
every firing on that contract marked. Filters: side, minimum entry, what counts as a win (10/25/50/100x), wins or fails only.
Data on the Mac is small: `data/nse/signals.parquet` (46 MB, `nse/signals_to_parquet.py`), `data/nse/spot/` (index history,
23 MB), and option candles copied one contract at a time from the VM into `data/nse/cache/` when a chart is opened
(`data/nse/vm.json` holds the address; not in git). `?expiry=2026-11-09&auto=1` opens the first alert, used for the page check.

## New expiries into `combined_js` (21 Nov 2026)

`nse/combine.js` turns the 86 new tars (20 Jan – 19 Nov 2026) into the per-contract files the file server reads. Same format
as the old combiner, except duplicate minutes are dropped, damaged files are cleaned, and rows run to the real close (15:40
from 3 Aug 2026; the old one cut at 15:30). Markers in `F:\nse\logs\combined_marks`, log `F:\nse\logs\combine_all.log`.
