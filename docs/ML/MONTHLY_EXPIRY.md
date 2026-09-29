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

Hold-to-settlement measures the wrong trade. He would have sold the 57000 PE at
3100, not ridden it to zero, and P(peak>=10x) of 3.8-10.3% says the spikes are
genuinely there. Whether a FIXED-IN-ADVANCE exit rule captures them is the open
question -- `monthly_exit.py`.

Caveat carried throughout: these are MARK prices, not traded. 9,276 traded
contract-days exist for re-checking anything that survives.
