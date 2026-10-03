# Monthly-expiry options: the instrument class this project never examined

Prompted by his Nifty/BankNifty Sep 2026 screenshots. Nifty broke its rising
trendline in early September, drifted, then crashed to 22,594 at month end. The
BANKNIFTY 57000 PE went roughly 500 -> 3100 in the final days; NIFTY 23100 PE
+143.87% in a session. His reading: *"Markets yielded significantly long after
breaking trendline/wedges, only near monthly expiry."*

## Why this was invisible until now

Delta lists monthly expiries -- last Friday of each month, 38-day contracts -- but
they are only **3.2% of expiry dates**. The 2-day contracts are 96.8% by count and
drowned them out of every prior analysis. Same family as the per-contract
weighting trap already documented, in a form not previously caught.

Measured: 1,935 expiries, median contract life 2.0 days, p90 20d, 3.2% at 38d.
3,643 monthly contracts recovered, 453,468 entry points, BTC+ETH, 60m bars.

## (1) Peak timing -- his claim HOLDS

Where the lifetime premium high lands within a monthly contract's life:

| peak occurs in | observed | uniform |
|---|---:|---:|
| final day | **6.8%** | 2.6% |
| final 3 days | **18.6%** | 7.9% |
| final week | **29.0%** | 18.4% |

Expiry-week peaks run **2.4-2.6x over chance**. And uniform understates the case:
a pure-theta option that never moves peaks at listing, position 0.0. Observed
median position is 0.237 through life, so genuine repricing pulls peaks later
than decay alone. NOTE: uniform is a weak null for a decaying asset; a matched
null is still owed before this is quoted as a headline number.

## (2) Buy-and-hold -- his claim DIES

OTM 2-15%, held to settlement, net of COST=0.0826:

| entered at | n | med peak | P>=10x | EV/trade | P(EV>0) | win% |
|---|---:|---:|---:|---:|---:|---:|
| <1d | 2,832 | 1.23 | 4.52% | **-0.736** | 0.000 | 1.3% |
| 1-3d | 6,172 | 1.58 | 10.29% | **-0.504** | 0.045 | 6.8% |
| 3-7d | 10,552 | 1.71 | 8.11% | **-0.627** | 0.003 | 7.2% |
| 7-14d | 17,463 | 1.71 | 4.43% | -0.132 | 0.316 | 12.5% |
| **14-21d** | 15,970 | 1.95 | 3.81% | **+0.008** | 0.484 | 19.6% |
| 21d+ | 36,049 | 1.88 | 3.87% | **-0.367** | 0.001 | 15.7% |

Deep OTM >15% is negative in every bucket; 3-7d reaches **-0.947 with a 0.2% win
rate**. This extends the earlier ">50% OTM, EV -0.83" result to the monthly class.

**Buying early and waiting loses** (-0.367 at 21d+, P=0.001). The only cell that
is not clearly losing is 14-21d at +0.008, P=0.484 -- a coin flip, not an edge.

The ratio column RISES as entry moves earlier (1.23 -> 1.95) while EV FALLS. That
divergence is the whole lesson: the chart flatters the early entry and the account
contradicts it.

## What is NOT yet settled

(**Settled 2026-10-02** -- see the update at the end of this section.)

Hold-to-settlement measures the wrong trade. He would have sold the 57000 PE at
3100, not ridden it to zero, and P(peak>=10x) of 3.8-10.3% says the spikes are
genuinely there. Whether a FIXED-IN-ADVANCE exit rule captures them is the open
question -- `monthly_exit.py`.

**Update 2026-10-02: `monthly_exit.py` has been run; the question is answered,
and no fixed exit rule pays.** Monthly contracts, OTM 2-15%, entered every 6h at
7-21 days to expiry, 35,446 entries, BTC+ETH, COST=0.0826, weekly block bootstrap.
`P(EV>0)` is the bootstrap share above zero (0.95 would be one-sided P=0.05).

| rule | ALL EV | P(EV>0) | PUTS EV | CALLS EV | CALLS P(EV>0) |
|---|---:|---:|---:|---:|---:|
| target 2x | -0.144 | 0.000 | -0.204 | -0.083 | 0.209 |
| target 3x | -0.158 | 0.011 | -0.227 | -0.088 | 0.245 |
| target 5x | -0.178 | 0.056 | -0.144 | -0.211 | 0.118 |
| target 10x | -0.134 | 0.189 | -0.217 | -0.048 | 0.415 |
| trail 30% | -0.131 | 0.000 | -0.149 | -0.113 | 0.000 |
| trail 50% | -0.111 | 0.021 | -0.246 | +0.027 | 0.570 |
| timestop 7d | +0.050 | 0.611 | -0.235 | +0.341 | 0.886 |
| timestop 3d | +0.076 | 0.616 | -0.409 | +0.571 | 0.932 |
| hold | -0.029 | 0.439 | -0.272 | +0.219 | 0.709 |

- **Every profit target and trailing stop loses** on the pooled book. Selling the
  spike at a pre-set multiple does not capture it: the spikes are real but too
  rare to pay for the many entries that never reach the target.
- **Puts lose under all nine rules.** His BankNifty-style put payoff does not
  appear in BTC/ETH monthlies as a fixed rule.
- **The only positive cells are calls with a time stop, and they are drift.**
  Calls timestop 3d by year: 2024 +0.29, **2025 −0.42**, 2026 **+1.89**. One bad
  year out of three and the result lives in the up years -- the beta control the
  script was written for. Not significant (P(EV>0)=0.932) and not an edge.

**Verdict:** the expiry-week peak timing in (1) is real; no causal exit rule
turns it into a trade. Monthly OTM buying stays dead, as in (2).

Caveat carried throughout: these are MARK prices, not traded. 9,276 traded
contract-days exist for re-checking anything that survives.
