# Quiet-decay -> spike cycles on the premium (13 Oct 2026)

His example: NIFTY 13 Oct 22600CE (img/2026-10/nifty_2026-10-13_22600CE_regime_cycles.webp) — noisy at a high
price, quiet decay, spike + noise, quiet decay, ... last quiet decay gives ~15x. Idea tested: the more
quiet-decay -> spike cycles a contract has completed, the likelier the next quiet decay ends in a big move.
Script `regime_cycles.py` (definitions in its docstring; % candle size so lower prices are fair; no strike,
expiry or price restriction). BTC/ETH, 2024-01 -> 2026-10, 15m / 1h / 4h; 885,729 quiet-decay phases.

| prior cycles | n | raw >=10x | raw >=25x |
|---|---|---|---|
| 0 | 830,584 | 2.43% | 0.72% |
| 1 | 48,438 | 3.50% | 1.46% |
| 2 | 5,593 | 3.16% | 1.54% |
| 3+ | 1,114 | 4.13% | 1.80% |

The raw lift disappears once matched on timeframe, call/put, time left and premium level (cycled contracts are
the cheap ones): >=10x 1 cycle -0.44pp [-1.01, +0.10], 2 cycles -1.28pp [-2.08, -0.21], 3+ -0.48pp;
>=25x all within +-0.25pp of control.

By timeframe (2+ cycles vs matched 0): 15m 2.73% vs 4.17%, 1h 3.77% vs 6.31%, **4h 13.1% vs 4.25%** (290 events,
44 expiries) — but 22 of the 38 4h hits are one expiry (BTC 2024-09-27); without it about 6% vs 4%, and the
4h result is one of three looks. Not an edge; worth watching on 4h only in live sightings.

Verdict: falsified as stated. Cycles mark cheapness, which is already priced in the comparison.
