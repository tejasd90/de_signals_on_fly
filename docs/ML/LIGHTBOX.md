# The light-box model (his idea, 2026-09-30) — elegant, and null

> *"Consider the market is in a closed box... if light is emitted from the left
> towards right, how much light reaches the current candle BODY? Each candle
> absorbs some percentage... range-bound candles receive less light, inside bars
> receive quite less, range high/low do receive more, but if rejected, the formed
> wick is of not much use. This would cover trendlines as well."*

## Why it was worth building

Three genuine advantages over the weighted-hit-count it superficially resembles:

1. **Recency is free.** pascore needed an invented weight function (harmonic, log,
   power, exponential) -- four arbitrary choices that became a forking path. Here a
   recent bar blocking a level makes older bars at that level contribute nothing
   more. Recency is a consequence of geometry, not a parameter.
2. **Bodies-not-wicks is load-bearing.** A rejection leaves the wick at the extreme
   and the body inside the range, so the body stays shadowed. "A rejection is not a
   breakout" emerges from the model rather than being bolted on.
3. **Angles unify levels and trendlines.** Horizontal rays measure horizontal
   levels; sloped rays are lines of sight along trendlines. One mechanism.

## The maths

Log price, so slope is scale-free % per bar. Body of bar j occupies cells B[j,:].
For a ray of slope s, shear each row by s*j; then it is a plain cumulative sum:

```
C_s[j,k'] = B[j, k' + s*j]
N_s[i,k'] = sum_{j<i} C_s[j,k']          strictly j < i
T_s[i,k'] = (1 - alpha) ** N_s            Beer-Lambert
light(i)  = mean of T over bar i's body cells
```

7 slopes, 4 absorptions, 20 features, shifted one day so nothing is known early.
Reflection omitted in v1: multiple scattering is a radiosity system with its own
parameters and should only be paid for if pure absorption earns it.

## Result: NULL

Anti-leak check first, per AUDIT_2026-09-30.md:

```
rangeatr   rho(next) +0.069   rho(prev) +0.114   <- describes yesterday
mfe        rho(next) +0.026   rho(prev) +0.087   <- describes yesterday
```

Against the volatility baseline:

| target | side | base | +pascore | +light | +both | light gain | per asset |
|---|---|---:|---:|---:|---:|---:|---|
| rangeatr | QUIET | 0.568 | **0.619** | 0.584 | 0.611 | +0.016 | BTC +0.011, ETH +0.017 |
| rangeatr | BIG | 0.553 | 0.602 | 0.561 | 0.594 | +0.008 | BTC **-0.026**, ETH +0.044 |
| mfe | QUIET | 0.560 | 0.611 | 0.548 | 0.600 | -0.013 | BTC -0.017, ETH -0.011 |
| mfe | BIG | 0.538 | 0.583 | 0.534 | 0.557 | -0.004 | BTC **-0.033**, ETH +0.030 |

Near-zero gains, assets disagreeing in sign in two of four cells, and adding light
to pascore makes it WORSE (0.611 vs 0.619) -- redundant, and carrying noise.

## Why it fails, which is the useful part

Absorption sweep, light features only:

| alpha | AUC | effective memory |
|---:|---:|---:|
| 0.001 | 0.559 | ~4,600 bodies |
| 0.01 | 0.561 | ~458 bodies |
| 0.10 | 0.575 | ~44 bodies |
| **0.50** | **0.583** | **~7 bodies** |

Performance rises monotonically as the model becomes MORE OPAQUE. Opacity is depth
of memory, so the best-performing version sees barely a week back -- exactly what
the 5-day volatility baseline already encodes. **The deep-memory versions, which
are what the idea was actually about, perform worst.**

An earlier draft concluded from this that "the market's usable memory is short",
citing five failed formulations. **That conclusion was wrong and is withdrawn.**
`memory_depth.py` holds the pascore feature DEFINITIONS fixed and varies only the
lookback:

| target | side | baseline | L=20 | L=60 | L=250 | L=500 |
|---|---|---:|---:|---:|---:|---:|
| rangeatr | QUIET | 0.568 | 0.597 | 0.610 | 0.614 | **0.619** |
| rangeatr | BIG | 0.553 | 0.528 | 0.535 | 0.593 | **0.602** |
| mfe | QUIET | 0.560 | 0.573 | 0.583 | **0.617** | 0.611 |
| mfe | BIG | 0.538 | 0.570 | 0.547 | 0.576 | **0.583** |

Long memory wins in all four cells, and for `rangeatr BIG` the short lookbacks are
BELOW baseline while L=500 is well above. Deep history genuinely helps. The
light-box failed for its OWN reasons -- the occlusion formulation -- not because
long-range structure is worthless.

## What would revive it

Only one honest route: reflections. v1 is pure absorption, and his model included
light rebounding inside the box so that shadowed regions receive indirect
illumination. That is a genuinely different object (a radiosity solve) and is the
one untested part of his specification. Worth doing only if a cheap version can be
tried without adding several fitted parameters.


## Reflection, tested separately (2026-09-30) — also null, DISCARDED

v1 was pure absorption. His model had light rebounding inside the box so shadowed
regions receive indirect illumination. `reflect.py` implements the principled
version: the two-flux (Kubelka-Munk) model, standard for a scattering medium.
Forward flux F and backward flux B along each price row, at each body
`F_out = tau*F_in + rho*B_in`, `B_out = tau*B_in + rho*F_in`, iterated to
convergence, with near-mirror walls (0.9) making the box closed. rho=0 IS v1, so
the comparison is exact.

| target | side | base | rho=0 (v1) | rho>0 (refl) | refl gain | per asset |
|---|---|---:|---:|---:|---:|---|
| rangeatr | QUIET | 0.627 | 0.617 | 0.618 | +0.001 | BTC +0.001, ETH +0.002 |
| rangeatr | BIG | 0.586 | 0.580 | 0.580 | +0.000 | BTC +0.000, ETH -0.000 |
| mfe | QUIET | 0.616 | 0.611 | 0.607 | -0.003 | BTC -0.004, ETH -0.002 |
| mfe | BIG | 0.584 | 0.593 | 0.595 | +0.002 | BTC +0.004, ETH +0.001 |

Zero to three decimals on both assets. And the light features sit BELOW the
volatility baseline in three of four cells with or without reflection.

Plausible reason: reflection redistributes light SMOOTHLY, and a smooth field adds
no discriminating structure. Whatever information exists is in the occlusion
pattern, which pure absorption already captures fully.

**The light-box is now tested in full, both halves, and is closed.**
