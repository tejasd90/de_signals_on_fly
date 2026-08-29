# Decisions

Why things are the way they are. When something looks odd, the reason is
probably here.

---

## Storage

**Candles are stored for past expiries, not for live ones.**
A live expiry's candles are still forming and would be stale the moment they hit
disk. Past candles never change, and storing them is what makes signal re-runs
cost zero API calls.

**Two separate completion markers.**
`candles_complete` (expensive, API bound) and `signals_complete` (cheap, CPU
bound). Conflating them was the original sin: it meant a parameter change forced
a refetch. Clearing only the second gives a full recompute for free.

**Every duration is stored, each trimmed to its own window.**
An earlier version stored only base durations at the full `PRIOR_DAYS` span so a
base could feed the longest chain built on it — keeping 40 days of 5m candles to
serve a 5m signal that looks back 2 days. Storing per-duration cut disk by 79%,
from ~19,000 candles per instrument to ~7,900. It also means the signal path does
no grouping at all.

**Candle storage takes the full `PRIOR_DAYS` window regardless.**
Widening a `DURATION_TIMES` window later would otherwise force a refetch.

**Compact array format.**
`[time,o,h,l,c,v]` rather than objects: ~40 bytes per candle instead of ~100.
`dtstring` is rebuilt on read.

**Spot candles live in a separate tree.**
Option candles belong to an expiry and die with it. Spot is one continuous series
per `(spot, duration)` spanning all of them, so it cannot live under
`data/candles/{spot}/{expiry}/`.

---

## Sourcing and grouping

**Sourcing is computed, not configured.**
`sourceFor(d)` returns the largest direct-fetch duration dividing `d`, so every
duration is one grouping step from its source. The old hand-maintained chain took
360m through 15→45→90→180→360; it is now 120→360. Adding a duration needs no
config edit.

**Sources are fetched once and shared.**
5m feeds 5/10/20/40 in a single download. 13 API requests per instrument rather
than 22.

**Warm-up is time-scaled, not a fixed candle count.**
`SKIP_INITIAL_CANDLES` (20) was calibrated for 5-minute candles — a 100-minute
window. Applied unchanged to daily bars it discarded 20 **days**.

---

## Timing

**Settlement time is per spot, resolved from the API.**
`T17:30:00+0530` was hardcoded in six places across four files. XAUT settles on a
different schedule, and every one of those hardcodes drove something that
matters: past/future classification, scheduler weights, fetch bounds, DTE windows.
Now read from `product.settlement_time`, so a new listing works with no code
change.

**Timezone independence is explicit.**
`formatTs` and `getKeyDuration` shift by the IST offset and read UTC getters.
Verified byte-identical across five host timezones, and equivalent to the old
IST-only behaviour across 40,000 samples — so existing data stays valid.

**Fetch end is clamped to now.**
Requesting candles beyond the present for a live expiry only wastes paginated
requests.

---

## Scheduling

**Weighted, not round-robin.**
Weight accrues as `1/ceil(daysToExpiry)`, so the nearest expiry surfaces far more
often. That matches how fast each changes: a 7-DTE contract on 5m candles moves
constantly, a 60-DTE contract on 4h candles barely shifts between passes.

**Past backfill is throttled inside `live_runner`.**
Otherwise a long historical backfill starves the live expiry.

**`main.js` is retired, not deleted.**
It printed the replacement commands and exits 1, so an existing alias or cron
entry fails loudly rather than with a confusing module-not-found.

---

## Signals

**Activation is an intrabar touch of the signal candle's high, not a close above.**
A resting stop-buy fills the moment the level trades, whatever the candle does
afterwards, so requiring a close above would miss fills that genuinely happened.
The ratio's denominator is that same high rather than the close — stricter, and it
is what the stop entry actually pays, so the number is achievable rather than a
best case. Every ratio is lower than under the previous definition.

**`green_stairs` fires at the last step, not at a breakout candle.**
Previously it required a later candle to close above the run high, which made it
fire later, less often and at a worse price than the other signals — and made its
ratios incomparable with theirs. All signals now share one activation rule.

**Outcome ratios are never truncated at a stop-loss.**
An earlier version stopped measuring at the first adverse close. Since options
always decay below any pattern-derived level, that made **every** ratio ≈ 1.0 and
every state `slHit`. `signalRatio` is now the peak from entry across all
subsequent candles.

**Zero-body candles are excluded outright.**
They were previously admitted with their body floored to `MIN_TICK` (0.1), making
`ratio1 = firstRedBody / 0.1 = firstRedBody × 10`. Any doji ending a sequence with
`firstRedBody >= 5` cleared a threshold of 50 on `ratio1` alone. Deep-OTM options
near expiry are full of flat candles — 53% of them once prices are tick-quantised
— so this manufactured false positives exactly where they are hardest to spot.
Removing it eliminated 15.7% of false positives with no true positives lost.

**No end cutoff on `DURATION_TIMES`.**
An earlier version excluded the final hours before expiry, on the theory that
theta acceleration manufactures false positives there. But genuine multibaggers do
occur in that window, and excluding it costs real signals. Decay-driven false
positives are suppressed by the zero-body rules instead.

**Signals cannot fire in the last 1.5 hours before settlement.**
Applied as a post-filter after outcome annotation, so a signal that fired earlier
still measures its full forward window. Only initiation is restricted — there is
no point flagging an entry with minutes of life left, but a move that began
earlier and runs into the final hours is real and should be counted.

**Signals firing against a decisive opposite spot move are suppressed.**
A sharp move spikes premium on both sides, so a call pattern can fire purely
because the underlying fell hard — right shape, wrong direction. Body must exceed
60% of the candle's range to count as decisive, so a long-wicked candle does not
trigger it.

**The OTM signals record squeeze geometry without firing on it.**
`ratio1` and `ratio2` were removed from OTM scoring because they failed to rank in
the unrestricted `red_squeeze`. Removing them from the stored output as well was
an overreach: whether they rank *within* the OTM population is a separate question,
and it cannot be asked if the numbers were never kept.

**OTM checked at pattern start, not at trigger.**
The looser test, so an instrument drifting across the money mid-pattern is kept.
Chosen to avoid missing real signals.

**`universeMaxRatio` uses `all_same_type` by default.**
It measures *how big a move was there*, not which strike to buy, and a boundary
truncates that answer. With `further_otm`, a call firing at strike 95000 reported
5x when the true best was 100x on strike 90000 — the wrong side of the boundary.

Opposite type is never eligible: a put signal is a call on the spot falling, so a
call going 100x is the wrong direction entirely.

---

## Analysis

**Payoff defaults to `universeMaxRatio`.**
Restricting to the firing instrument understates what the signal was worth,
because the big multiple usually lands elsewhere in the chain.

**Calls and puts are reported separately by default in `quality.js`.**
Pooling them halves a genuine edge: with calls carrying an 80% pocket and puts
flat at 10%, the pooled figure read 46%.

**red_squeeze fires on max(ratio1, ratio2), not their sum.**
A sum let two unremarkable ratios combine into a signal neither justified, and
could miss a very tight squeeze whose green happened to be large. Using the max
also makes `signalValue >= T` exactly equivalent to the firing rule, which keeps
the calibration tools and the prefilled query filter honest.

**Storage thresholds are loose; tightening happens at display time.**
A high stored threshold discards irreversibly — those signals are never written
and cannot be recovered without a re-run. The dashboards now carry their own
minimum, so filtering is visible, adjustable and costs a redraw.

**Strength bands are per signal.**
`signalValue` means something different in each, on wildly different scales:
`ratio1 + ratio2` runs 50–5,757, while `spot/avgPrice` is always above 10,000.
One shared band set collapsed every OTM row into the top bucket, leaving four
empty rows and one containing everything.

**Three-way breakdown exists because two dimensions are not enough.**
Planting an 80% pocket at `60m × 6-48h × 1.5-3.5% OTM`: `--by duration` read
13.9%, `--by duration,tte` read 27%, and the full three-way read 85%. Every
dimension collapsed averages the pocket away.

**Thin cells are parenthesised and never starred.**
A 100% hit rate on two samples is the most seductive output this kind of tool can
produce.

**ITM is its own moneyness bucket.**
An in-the-money option carries intrinsic value that behaves nothing like pure
premium. The innermost ITM and OTM bands are merged into one ±1.5% bucket, since
within 1.5% of spot the label is close to arbitrary.

---

## Trades and multibaggers

**Recursive partitioning splits independently of the threshold.**
A window's top-level trade is not necessarily its largest: `10, 100, 0.1, 50`
gives 10x at the top level but 500x in the right partition. Filtering during
recursion would prune the branch containing it.

**The low must be strictly before the high candle.**
Within one candle there is no way to know which came first, so a same-candle pair
is not a tradeable round trip.

**Trade finding is iterative, not recursive.**
A monotonic decline over 11,500 candles shortens the window by one per split and
would blow the call stack.

**The merge cap limits extension, not absolute span.**
A single trade can legitimately run for days. Capping absolute span left six
instruments with near-identical 90h windows — obviously one event — as six
separate rows.

**`multibaggers.js` is perfect hindsight, deliberately.**
It buys the exact bottom and sells the exact top. No strategy reaches it. It is
the ceiling, and the denominator that makes recall computable: precision alone
cannot distinguish "my signals miss most opportunities" from "they fire plenty but
pick badly", and those need different fixes.

---

## Reliability

**Errors propagate; partial data is never marked complete.**
`fetchCandles` does not catch page failures — a swallowed error returns a silently
truncated series indistinguishable from a complete one. If any instrument fails,
the expiry stays unmarked and resumable.

**Progress is flushed after every instrument.**
An interruption loses at most one instrument's work.

**Writes are atomic everywhere.**
Temp file plus `rename()`, since a viewer may be reading. `writeFileSync` alone
can be observed mid-write and yields unparseable JSON.

**Claims are exclusive-create lockfiles.**
`fs.openSync(path, 'wx')` is atomic at the OS level. Verified: 8 racing processes,
exactly 1 winner. Stale claims self-heal after 30 minutes.

**Retries classify errors.**
Network faults and 5xx retry with exponential backoff; 429 gets a 30-second floor;
4xx fails immediately rather than burning quota on a request that cannot succeed.

---

## Viewers

**The signal view is a 2D heatmap, not a 3D cube.**
An earlier version used strike as a third axis. That was a design error: a
(strike, expiry, time) cell identifies exactly ONE instrument, so its count could
only ever be 0 or 1 and the shading carried no information at all. Collapsing
strike into a COUNT is what makes shading meaningful — a cell now says how many
strikes fired together, which is the confluence question worth asking.

**The heatmap is a POINT-IN-TIME SNAPSHOT, not a history.**
Rows are the expiries STILL ALIVE at the selected moment — settlement strictly
after it — over the last N candles behind it. An earlier version showed every
settled expiry across all history, which piled unrelated expiries into one grid
and made a correct filter look broken. An expiry that had already settled was not
on your screen and could not have been traded, so it does not belong in a view of
that moment.

**An expiry counts as alive only once it was LISTED, and the candles say when.**
Filtering on "settles after this moment" alone treats every future expiry as
available — 67 rows at once, where a real board carries a handful of dailies,
weeklies and monthlies. The first candle for an expiry is when it began trading,
and that is already on disk, so no hardcoded listing calendar is needed. Scanned
at the coarsest stored duration (fewest candles per file) and cached per expiry.

`EXPIRY_LISTING_WINDOW_DAYS` (40) is only the fallback for expiries with no
stored candles, and matches the window the fetcher already assumes.

**Rows come from the INSTRUMENT list, not from firings.**
Deriving rows from signals meant an expiry with nothing to show simply vanished —
so calls and puts displayed different rows for the same moment, and a quiet
expiry looked as though it had not existed. Every expiry alive at the selected
moment now gets a row, and calls and puts share one row set so they can be read
side by side. An empty row is information: this expiry was tradeable and nothing
fired on it.

**A duration with no firings is hidden, and the count is stated.**
Otherwise sixteen empty grids bury the two that matter. The header reports how
many were hidden, and a checkbox shows them, so a missing duration is explained
rather than looking like a fault.

**Columns are CANDLE SLOTS, not distinct firing moments.**
Generated by walking back on the candle grid via `getKeyDuration`, so they align
exactly with stored candle timestamps and a slot where nothing fired still
appears. An empty column is information; skipping it made sparse durations look
busier than they were.

**Column labels carry the year only when the columns span more than one.**
A column reading `07-15` beside a row reading `2024-07-19` gives no way to tell
whether they are the same year. Always showing the year would waste header space
in the common single-year case, so it is conditional. Each duration header also
states the span it covers.

**Cells count DISTINCT STRIKES, not firings.**
The same strike appearing in two overlapping merged ranges at one timestamp is
one strike having fired. Counting it twice would make broad-but-shallow moments
look deep.

**Cell borders are 2px and LIGHT.**
A 1px near-black border on a near-black background is invisible — it reads as
background wherever a cell has space around it. Measured on the earlier canvas
version: zero distinguishable border pixels dark, thousands light. In a table the
border is CSS, so it cannot be overpainted by a neighbouring cell the way canvas
rectangles could.

**Durations are ordered longest first.**
The coarse grid has fewest columns and reads immediately, so it is the one you
orient with before looking at the dense ones.

**Per-expiry summaries are precomputed.**
A calendar needs one number per side per expiry. Deriving that live would mean
~16 file reads per expiry and ~16,000 for a full history, on every page load.

**Duration panels are ordered per side.**
The duration that produced the biggest call move is routinely not the one that
produced the biggest put move.

**Chart lead-in differs by tool.**
Signals open 20 candles before the pattern; trades open 40. For trades the
question is what the *setup* looked like, and opening at the low shows only the
answer.

**`serve_signals.js` was kept when the calendar view was added.**
Its matrix answers "does strength predict payoff", a research question. The
calendar answers "which dates produced moves", a browsing question. Different
layouts suit each.

---

## The query pipeline

**Stage 1 stores unmerged rows.**
Merging keeps maxima and discards per-instrument `ratio1`, `ratio2`, `seqLength` —
exactly the fields a query wants.

**Structural rules are applied; tuning is not.**
This is what lets a threshold be explored in *both* directions. Raising one was
always possible by filtering stored data; lowering it needed a full re-run.

**Stage 1 over-stores.**
A field absent there cannot be queried later without re-running over candles,
which is the expensive step. Disk is cheap at these volumes.

**Filter and success are separate boxes.**
Sharing one namespace makes it easy to reference an outcome on the filter side,
which is lookahead and silently produces a perfect-looking result.

**Walk-forward rather than one split, and never a random one.**
A random split sends signals from the same expiry — the same underlying move — to
both sides, so the holdout measures data it trained on. The objection to date
splitting is that regimes differ by date; that is true, and it is the point, since
live trading always faces an unseen future regime. Walk-forward answers the regime
concern properly by testing across several.

**Purging at fold boundaries.**
A signal can fire 40 days before its expiry, so a test-side signal may observe
training-window days. Rows whose observation window straddles the boundary are
dropped — 5–10% of rows for a number that can be trusted.

**Filter first, then merge.**
Merging first collapses the per-instrument fields the filter works on into
maxima. Filtering first keeps `ratio1 > 8` meaning what it says. Event boundaries
then depend on the filter, which is arguably correct: you are asking how often you
would have been right under each set of criteria, and the events you would have
acted on genuinely differ.

**The holdout is permanent, not a toggle.**
With a million rows and free-form querying, finding a clause that looks excellent
in-sample is close to certain. Seeing the out-of-sample number beside it every
time is the only defence.
