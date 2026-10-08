# Charts Tejas shared, October 2026

Saved 2026-10-08 so they survive a restart (the session's image files lived in /private/tmp). Charts that
were pasted inline and never existed as files are DESCRIBED here instead, written while the conversation
still showed them.

## Saved files

| file | what it shows | used in |
|---|---|---|
| `2026-10-07_point1_5m_hug_above_line.webp` | BTCUSD 5m, 6 Oct 20:00 → 7 Oct 09:00 IST, traded price. A rising support line at ~85.3–85.4k; after the 21:00 drop price sits in a tight range just ABOVE the line for ~8h (22:00 → 06:30), then breaks at ~06:55–07:30 to a low of ~83.5k, with a volume spike at the break | his point 1 (the hug); `HUG_MELT_HURDLE.md` |
| `2026-10-07_point1_15m_hug_and_break.webp` | Same move on 15m, 5 Oct 21:00 → 7 Oct 09:00: rally to ~86.6k on 6 Oct 20:30, drop, hug above the rising line, break | point 1 |
| `2026-10-07_point1_zoom_hug.png` | Zoomed crop of the hug: small candles hovering on the line, then two large red candles through it | point 1 |
| `2026-10-07_hurdles_1m_drop.webp` | BTCUSD 1m, 7 Oct 04:00 → 08:45 IST: flat on the line ~85.4–85.5k, a first dip at ~06:45, then the plunge 07:15–07:30 to ~83.5k and a partial recovery to ~84.1k | his note that sharp moves and hurdles live on 1–5m charts |
| `journal_2026-10-05_12h_wedge.png` | His journal entry 13 (5 Oct 09:43): BTCUSD 12h, a converging wedge (falling upper line from ~87.5k, rising lower line), price ~85.95k | `JOURNAL_SCORECARD.md` entry 13 |
| `journal_2026-10-05_second.png` | Journal entry 13, second chart (lower timeframe "wedge/flag") | entry 13 |
| `journal_2026-10-07_1h_trendline_break.png` | Journal entry 14 (7 Oct 09:28): BTCUSD 1h, the rising trendline from 18–19 Sep (~79k) through 29 Sep, 3 Oct and 6 Oct (~85.2k), broken the morning of 7 Oct | entry 14; `CASE_2026-10-02.md` follow-up |
| `journal_2026-10-07_6h_trendline_break.png` | Journal entry 14: the same line on BTCUSD 6h, Aug → Oct | entry 14 |
| `journal_2026-10-08_range_polarity.png` | Journal entry 15 (8 Oct 18:44): BTCUSD 6h MARK, Aug → Oct. Previous range ~76–82k (Aug 22 → Sep 18), recent range ~83–87k, price back at ~82.4k | entry 15 |
| `journal_2026-10-09_img1_nifty_support.png` | Entry 16 image 1: NIFTY DEC 23000 PE weekly. A double bottom at ~150 (support taken again at the same level), now 825 | entry 16 |
| `journal_2026-10-09_img2_live_signals.png` | Entry 16 image 2 (phone, 8 Oct 15:48): P-BTC-80500-091026 1h MARK. A base ~50–70 on 6–7 Oct, two spikes to ~200 on 7–8 Oct each pulling back, now ~98: the "parabola holding up" after a wall breakout | entry 16; premium-base idea |
| `journal_2026-10-09_img3_premiums_holding.png` | Entry 16 image 3 (8 Oct 18:12): the same put on 6h. Decay from ~2,300 (19 Sep) to near zero by 6–7 Oct, then holding and slowly rising to ~182 | entry 16 |
| `journal_2026-10-09_img4_explosion.png` | Entry 16 image 4 (8 Oct 23:27): P-BTC-81000-091026 1h MARK. Flat ~100 for days, small spikes on 7–8 Oct, then the explosion to H 938 (~23:00 IST), last 752 | entry 16 |

## Pasted inline only, described here (no file exists)

1. **C-BTC-87000-021026, 1h MARK premium** (shared 2 Oct ~10:15 IST).
   - Premium drifted from ~250 on 28 Sep to near zero by 1–2 Oct.
   - It then sat flat at single digits to ~20 for many hours.
   - On 2 Oct ~09:30 IST it spiked to ~300: candle O 69.7, H 321.4, L 44.9, C 203.3, +191.68%.
   - His points: the "wait then breakout" on lower timeframes, and the 87000C as a ~1:100.

   Used in: `TF_REPEAT_HOLD.md` (wait-and-hold), `CASE_2026-10-02.md`.
2. **Hurdles, four screenshots** (7 Oct ~10:11–10:13 IST, his point 2).
   - **BTCUSD 5m, 1–3 Oct:** a sharp spike on 2 Oct ~10:00 IST to ~86.9k, with a sharper drop back to
     ~86.1k. Again 2 Oct ~18:00–19:00: spikes to ~87.2k, then a sustained slide to ~84k overnight. This is
     the definition example of a hurdle.
   - **The same 5m chart with small circles** marking the spike highs/lows he calls hurdles.
   - **BTCUSD 5m, 6 Oct 05:00 → 7 Oct 06:30:** the rising support (~85.29k by 7 Oct) and the tight range
     above it.
   - **BTCUSD 1m, 6 Oct 17:30–22:30:** a spike to ~86,650 at ~20:30 IST, then a sharper fall below 86.0k
     by 21:30. The 6 Oct 20:30 hurdle example.

   Used in: `HUG_MELT_HURDLE.md`, `hurdles.py`, `hurdle_test.py`.
3. **Journal entry 11 chart** (2 Oct 18:51 IST): BTCUSD 6h, a "hairy" last candle at ~86.7k (O 86,375,
   H 87,223, L 86,261). Also in his journal repo `tejasd90/market_observatios`
   (asset 14afc14f-aac6-4332-8311-293224a66791).
4. **Journal entry 8 chart** (30 Sep 09:33 IST): BTCUSD 1h symmetric triangle from 20 Sep, apex ~1 Oct,
   price ~83.37k. Also in the journal repo (asset e0222e99-be05-4235-9b9b-d83de51222c7).

All of his journal screenshots remain retrievable from github.com/tejasd90/market_observatios
(`cryptos.md` links each image).
