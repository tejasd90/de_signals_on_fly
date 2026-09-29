# His five signals, measured on the option's own chart

Tejas named five: **premium rebounce, premium holding, stairs, wall, red squeeze**,
and said *"maybe the communication was not done properly."* It was. Four of the
five charts he sent were OPTION charts. Every feature in this project reads the
UNDERLYING -- trendlines, ATR, wedges, always-in -- and the option appears only as
a payoff to be scored. His signals describe the premium series' own price action
and were never representable. The modelling was wrong, not the description.

`premium_pa.py`, 10,280,687 entry points, BTC+ETH, 15m, 142 weeks, COST=0.0826,
weekly block bootstrap.

## Result: OTM 2-15%

| signal | fires | dEV | P(dEV>0) |
|---|---:|---:|---:|
| wall | 19.3% | **+0.227** | 0.818 |
| stairs | 15.2% | +0.061 | 0.724 |
| squeeze | 8.3% | -0.144 | 0.016 |
| rebounce | 36.7% | -0.277 | 0.002 |
| hold | 2.4% | **-0.350** | 0.028 |

## Both predictions made in advance were wrong

`hold` was predicted to be the winner ("the only one with a mechanism"), `wall`
predicted to die on mark prices. **Exactly inverted.**

The `hold` reasoning was not merely unlucky, it was SIGN-INVERTED. The claim was:
an option that refuses to decay is one whose IV is being bid. Probably true -- and
that is precisely why it loses. If IV is being bid you are BUYING IT EXPENSIVE.
As a negative signal it is the most robust thing in the run: -0.239 overall
(P=0.001), -0.350 OTM, **-0.630 on PUTS (P=0.000)**.

## The positive half is not yet credible

Base EV before any signal fires:

```
OTM puts    -0.014
OTM calls   +0.236   <- buying a call at random "earned" 24%
```

2024-2026 was a bull market; that +0.236 is drift. The whole positive story lives
in that column: `wall` is +0.634 on CALLS (P=0.989) and **-0.164 on PUTS**.
`stairs` +0.213 calls, -0.087 puts. **On puts, all five signals are negative** --
and puts are the clean test, because drift runs against them.

Two further reasons for restraint:
- Win rates are 3-10%. Mean EV then rides on a few extreme outcomes and a
  bootstrap on means is fragile at that skew; P=0.989 does not mean what it
  usually means.
- These are MARK prices. A "wall" in a mark series cannot be order-book memory --
  a mark has no book. More likely a SPOT level showing through the pricing model,
  which would make `wall` a rediscovery of the horizontal-level work rather than
  a new premium signal.

Direction control (bucket by realised spot move, hold it fixed) decides whether
`wall` and `stairs` are signal or trend-following. See the tail of premium_pa.py.

## Engineering note

The first version of this script ran 3h+ and was killed. Two bugs, both mine:
a per-entry feature function called 10.3M times on 16-element slices, and a
bootstrap that rescanned all 10.3M rows once per week per iteration (~3e12 ops).
`fastboot.py` replaces the latter by summing each week ONCE and resampling the
summaries -- identical answer, 0.01s. The scan is now cached to
`data/premium_pa_cache2.npz`.

---

## Direction control: four die, one survives

Bucketing by realised spot move exposes the real structure. Base EV before any
signal fires:

```
spot quintile      1      2      3      4      5
CALLS base EV   -1.07  -1.04  -0.96  -1.03  +5.15
PUTS  base EV   +4.19  -1.03  -0.96  -1.05  -1.08
```

Options are a TOTAL LOSS in four buckets of five and pay hugely in the single
favourable tail. Only CALLS-q5 and PUTS-q1 carry information.

| signal | CALLS q5 (spot +2.5%+) | PUTS q1 (spot -2.1%-) |
|---|---:|---:|
| wall | +1.11 (P=0.712) | **-1.85** (P=0.062) |
| stairs | +0.62 (P=0.932) | **-0.92** (P=0.207) |
| rebounce | -1.65 (P=0.045) | -0.15 |
| squeeze | -0.21 | -0.12 |
| hold | +0.46 (P=0.585) | **-2.79 (P=0.000)** |

`wall` and `stairs` FLIP SIGN between the two favourable buckets -- helping calls
in rallies and hurting puts in crashes. That is a long-bias detector, exactly what
the control exists to catch. Rejected, with `rebounce` and `squeeze`.

## `hold` survives the tightest control available

Quintile 1 is unbounded (-2.1% to -inf) and a put's payoff is steep in depth of
decline, so the -2.79 could have been direction leaking through too wide a bucket.
`hold_finecheck.py` re-cuts it into narrow bands:

| spot band | n | base EV | EV when hold fires | dEV | P |
|---|---:|---:|---:|---:|---:|
| -2.1% to -4% | 141,973 | -0.53 | -0.97 | **-0.45** | 0.000 |
| -4% to -6% | 69,122 | +1.95 | -0.19 | **-2.18** | 0.000 |
| -6% to -9% | 48,940 | +7.71 | +1.25 | **-6.57** | 0.000 |
| -9% to -14% | 21,273 | +23.73 | +7.55 | **-16.63** | 0.001 |
| below -14% | 10,416 | +28.64 | +42.35 | +13.91 | 0.994 |

Four consecutive bands strongly negative. The feared leak is absent: firing rate
is 2.2 / 1.7 / 1.6 / 2.7 / 1.4 % across bands -- flat, no slope with depth.

Concretely: in a -6% to -9% move the average OTM put returned +7.7x. One that had
been "holding" beforehand returned +1.2x. Same crash, same strikes, same weeks --
**16% of the move captured, because it had already been paid for.**

**His signal is real and informative; it means the OPPOSITE of what was assumed.**
Not "about to move" -- "already expensive".

Caveats kept in view: the deepest band flips positive on only 151 fires (noise, or
a hint that in true catastrophes even an overpriced put pays -- undetermined);
firing rate 1.4-2.7% makes it a filter not a strategy; it is a DON'T-BUY rule, so
it saves losses rather than producing gains; and these are mark prices, with 9,276
traded contract-days available as the next check.
