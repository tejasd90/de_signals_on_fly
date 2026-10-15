# Trendline hover, break importance and expiry choice (15 Oct 2026)

His questions after the 15 Oct 07:45 IST break: can the lines be found by code; can the break's importance be
ranked; does long hovering at the line signal the break; should one trade the next / next-to-next expiry?
Scripts: `line_hover.py` (build), `line_hover_eval.py` (numbers). BTC/ETH MARK, 4h and 6h lines from
`levels.trendlines` (>= 3 touches, confirmed causally), 2024-01 → now; near-duplicate lines clustered (24h).

**Found by code, without his charts.** ETH 4h support 23 Aug → 8 Oct (4 touches) at 2,413, broken on the 4h close
at 09:30 IST 15 Oct (close 2,359); ETH 6h 16 Aug → 13 Oct; BTC 4h support 17 Aug → 13 Oct at 81,633, broken
09:30 IST; BTC 6h 16 Aug → 13 Oct (81,632) still unbroken at the 05:30 bar. Falling tops: BTC 2 Oct → 12 Oct
(~83.5k), ETH 5 Oct → 12 Oct (~2,518): his wedges/triangles. Price hovered 12–16 h at the support before breaking.

**(1) Hovering does not predict a break, slightly the reverse.** Of 1,623 touch episodes, 66% end in a break;
of those still at the line after 12h / 24h / 48h, 58% / 58% / 57%. On supports: >24h hover 54% break vs 69%.

**(2) Breaks do not follow through, and importance cannot be ranked.** 569 support breaks: median move over 96h
−0.29% in the break direction (47% continue), 90% CI [−0.77, +0.19]; reclaimed within 48h 66%. Resistance
breaks the same (+0.21%, 52%, reclaimed 64%). No split ranks them: hover >24h vs ≤24h, age >30d vs ≤30d,
touches ≥5 vs 3–4, 6h vs 4h all within noise (long-hover minus short-hover CI [−1.29, +0.73]).
"Not reclaimed" is only predictive in hindsight (not reclaimed over 48h → +2.0%, by construction). Causally:
still not reclaimed 12h after the break → next 96h −0.31% (47% continue), reclaimed later 60%; 24h after → 44%
continue, reclaimed later 48%.

**(3) Next expiries keep more value but are not an edge.** First-OTM option on the break side (MARK):
the chance of a ≥3x later is ~26–28% for expiry ranks 1, 2 and 3 alike; the further expiries hold more at 48h
(puts after a break: 0.00x / 0.00x / 0.27x median) and settle a little higher on average (0.93x / 1.03x /
1.14x), i.e. around break-even. Buying during the hover (12/24/48h in) is no better.

Consistent with SUSTAIN_FADE / channel-lines findings that breaks are mostly faded at these horizons; the
channel-lines put edge used a different, option-side construction and was not confirmed on traded prices.
