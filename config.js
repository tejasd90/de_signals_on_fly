// config.js
// ─────────────────────────────────────────────────────────────────────────────
// All configurable parameters. Edit here only — nothing else needs to change.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

// ─── API ─────────────────────────────────────────────────────────────────────

const API_BASE_URL  = 'https://api.india.delta.exchange';
const API_KEY       = '';          // leave empty for unauthenticated
const API_SECRET    = '';

// ─── Retry / resilience ──────────────────────────────────────────────────────
// A multi-hour backfill will hit dropped connections, brief outages and the
// occasional 429. These control how hard the client tries before giving up.

// Attempts per HTTP request, including the first. 5 attempts with the backoff
// below spans roughly 15 seconds — long enough to ride out a wifi blip or a
// short exchange hiccup without stalling the run.
const API_MAX_RETRIES = 5;

// First backoff, doubling each attempt: 1s, 2s, 4s, 8s.
const API_RETRY_BASE_DELAY_MS = 1000;

// Floor for 429 specifically. Retrying a rate-limit breach on the normal
// backoff just re-triggers it, so wait meaningfully longer.
const API_RATE_LIMIT_BACKOFF_MS = 30000;

// Delay between each HTTP call (ms). Increase if you see 429 errors.
// At 150ms: ~6.6 req/sec, well under unauthenticated limit of ~11 req/sec.
const API_CALL_DELAY_MS = 150;

// Max candles returned per API request (Delta Exchange limit)
const MAX_CANDLES_PER_REQUEST = 1500;

// Days of candle history to fetch per option instrument
const PRIOR_DAYS = 40;

// Skip this many leading candles per instrument (warm-up artefact)
const SKIP_INITIAL_CANDLES = 20;

// ─── Parallelism ──────────────────────────────────────────────────────────────

// Max concurrent API calls when fetching candles for instruments within
// one expiry+duration. Keep low to avoid rate limit bursts.
const MAX_CONCURRENT_INSTRUMENT_FETCHES = 5;

// How many past (spot, expiry) combinations to backfill per main-loop iteration.
// Past backfill is a one-off cost per expiry (results are marked complete and
// never recomputed), so it is deliberately throttled: the live/near expiry must
// keep getting fresh signals rather than being starved behind a long backfill.
const MAX_PAST_EXPIRIES_PER_ITERATION = 2;

// ─── Durations ───────────────────────────────────────────────────────────────

// Each entry: durationMinutes → [startHoursBeforeExpiry]
//
//   startHours — do NOT consider candles further from expiry than this.
//
// This window is now also the STORAGE window: each duration is persisted for
// exactly its own window, no more. Previously only base durations were stored,
// but at the full PRIOR_DAYS span so they could feed the longest chain built on
// top of them — which meant keeping 40 days of 5m candles to serve a 5m signal
// that only ever looks back 2 days. Storing per-duration cut disk by ~79%.
//
// There is deliberately NO end cutoff: every duration is processed right up to
// expiry. An earlier version excluded the final hours on the theory that theta
// acceleration there manufactures false positives, but genuine multibaggers do
// occur in that window (observed on 1h and 6h candles), so excluding it costs
// real signals. False positives from decay are suppressed instead by requiring
// a strict non-zero-body green trigger — see RED_SQUEEZE_* below and the
// zero-body rules in signals/red_squeeze.js.
const DURATION_TIMES = {
    5:    [24 * 2],      // direct  (5m)
    10:   [24 * 4],      // grouped from 5
    20:   [24 * 12],     // grouped from 10
    40:   [24 * 16],     // grouped from 20
    15:   [24 * 8],      // direct  (15m)
    45:   [24 * 24],     // grouped from 15
    90:   [24 * 40],     // grouped from 45
    180:  [24 * 40],     // grouped from 90
    360:  [24 * 40],     // grouped from 180
    30:   [24 * 16],     // direct  (30m)
    60:   [24 * 40],     // direct  (1h)
    120:  [24 * 40],     // direct  (2h)
    240:  [24 * 40],     // direct  (4h)
    480:  [24 * 40],     // grouped from 240
    720:  [24 * 40],     // direct  (12h)
    1440: [24 * 40],     // direct  (1d)
};

// NOTE ON SOURCING
// There is no longer a hand-maintained grouping chain. grouper.sourceFor(d)
// computes each duration's source as the LARGEST direct-fetch duration that
// divides it evenly. That is always reachable in a single grouping step, where
// the old chain needed up to four (360m came 15 -> 45 -> 90 -> 180 -> 360;
// it is now simply 120 -> 360). Adding or removing a duration needs no config
// change, because the source is derived rather than declared.

// Durations fetched directly from the API and their API resolution strings
const DIRECT_DURATIONS = {
    5:    '5m',
    15:   '15m',
    30:   '30m',
    60:   '1h',
    120:  '2h',
    240:  '4h',
    720:  '12h',
    1440: '1d',
};

// ─── Paths ────────────────────────────────────────────────────────────────────

const DATA_BASE_DIR             = 'data';
const INSTRUMENTS_BASE_DIR      = `${DATA_BASE_DIR}/instruments`;
const SIGNALS_BASE_DIR          = `${DATA_BASE_DIR}/signals`;
const PAST_COMPLETE_MARKERS_DIR = `${DATA_BASE_DIR}/markers/past_complete`;

// Stored BASE candles for past expiries. Grouped durations are never stored —
// they are recomputed from a base in memory. See candle_store.js.
const CANDLES_BASE_DIR = `${DATA_BASE_DIR}/candles`;

// Spot candles are continuous, not per-expiry, so they get their own tree keyed
// by (spot, duration). Layout matches the original fetch_spot_candles.js.
const SPOT_CANDLES_BASE_DIR = `${DATA_BASE_DIR}/spot_candles`;
const SPOT_MARKERS_BASE_DIR = `${DATA_BASE_DIR}/markers/spot`;

// Default reach-back for a spot fetch with no --from given.
//
// Raised from 400 because 400 days silently capped every series at a fixed floor
// roughly a year back — with option history going further, OTM signals on the
// older expiries found no spot and quietly produced nothing. Pass --from to
// reach further still; it extends backwards past whatever is already stored.
const SPOT_HISTORY_DAYS = 1200;

// Overlap refetched on each incremental spot fetch, so the candle that was still
// forming when the marker was written gets its final values.
const SPOT_REFETCH_OVERLAP_MINUTES = 30;

// Two independent completion markers for past expiries:
//   candles_complete — candles fetched and on disk (expensive: API calls)
//   signals_complete — signals computed from them  (cheap: pure CPU)
// Clearing only signals_complete re-runs signal logic with zero API calls,
// which is what makes parameter tuning fast.
const CANDLES_COMPLETE_MARKERS_DIR = `${DATA_BASE_DIR}/markers/candles_complete`;
const SIGNALS_COMPLETE_MARKERS_DIR = `${DATA_BASE_DIR}/markers/signals_complete`;

// ─── Signal: Red Squeeze ──────────────────────────────────────────────────────

// Minimum consecutive RED candles required before the green trigger.
// 3 means the squeeze must show a sustained descent, not just two candles.
// Raising this makes signals rarer but each one better-evidenced.
const RED_SQUEEZE_MIN_SEQ_LENGTH = 3;
const RED_SQUEEZE_THRESHOLD      = 50;
const RED_SQUEEZE_MINIMUM_TICK   = 0.1;
const RED_SQUEEZE_SL_FACTOR      = 1.5;

// ─── OTM signals: shared parameters ──────────────────────────────────────────
// Both otm_red_squeeze and green_stairs require the option to be OUT of the
// money. Signals on ITM options are untrustworthy here: ITM premium carries
// intrinsic value that melts hard, so a clean-looking pattern there says little.
//
// Moneyness is judged at PATTERN START (the first candle of the sequence) rather
// than at the trigger. That is the looser test and keeps instruments that drift
// across the money mid-pattern, which is the safer direction when the aim is not
// to miss real signals.

// Signal strength for both OTM signals:
//     signalValue = spot / mean(greenClose, low of every candle in the pattern)
//
// Dimensionless, so one threshold works across BTC and XAUT alike. Higher means
// a cheaper option relative to spot, which is the reliability claim: the same
// pattern on a 0.5-priced option is worth more than on a 50-priced one.
//
// Each signal also records distancePct — how far OTM the strike was — because a
// DEEP OTM option being cheap is expected, while a NEAR OTM one being cheap is
// unusual. Keeping them separate lets that be untangled later without a re-run.
// Threshold is a PRICE CEILING expressed relative to spot: 10000 means the
// average pattern price must be at or below spot/10000 — about 10 for BTC near
// 100k. Calibrated from observed values: a 0.88-priced option scores ~113,000
// and a 1.66-priced one ~60,000, so anything under a few thousand filters
// essentially nothing. Check the distribution on your own data before trusting
// this number; distancePct is stored alongside so cheap-because-deep-OTM can be
// separated from cheap-and-close.
const OTM_SIGNAL_THRESHOLD = 10000;

// Minimum candles in the pattern before the trigger, for both signals.
const OTM_MIN_SEQ_LENGTH = 3;

// Peak multiple above entry separating 'activated' from 'slHit'.
const OTM_SL_FACTOR = 1.5;

// green_stairs only: how many times a body may merely EQUAL its predecessor
// rather than exceed it. Real chains often contain one flat step; allowing more
// than one lets a run of identical candles masquerade as an ascending staircase.
const GREEN_STAIRS_MAX_EQUAL_STEPS = 1;

// ─── otm_wall ────────────────────────────────────────────────────────────────
// A wall candle after a narrow range. Ported from the spike-after-flats signal
// in the original group.js, minus its moving-average, volume and normalisation
// terms.

// How many preceding candles define the narrow range. 5 in the original,
// arrived at empirically.
const WALL_LOOKBACK_CANDLES = 5;

// Minimum log10 jump between the wall candle's value and a recent one.
// 2 means the value grew a hundredfold — the original's `>= 2` condition.
// Jumps above about 6 are rare in practice, so this is not a dial with much
// useful range above its default.
const WALL_JUMP_THRESHOLD = 2;

// The wall must also close at least this multiple above the candle it is
// compared against, so a large `dist` alone cannot fire it. 1.35 in the original.
const WALL_CLOSE_MULTIPLE = 1.35;

// ─── Live runner ─────────────────────────────────────────────────────────────

// Signals older than this are dropped from the live snapshot: a live board is
// about what is actionable now, and history is what serve_signals is for.
const LIVE_SIGNAL_WINDOW_HOURS = 48;

// Cap on signals in one snapshot, so a burst cannot bloat the file.
const LIVE_MAX_SIGNALS = 500;

// Points kept per EMA-spread series — enough for a readable sparkline.
const LIVE_SERIES_POINTS = 240;

// Pause between loop iterations. The real pacing comes from API_CALL_DELAY_MS
// per request; this only stops a hot spin when there is nothing to do.
const LIVE_LOOP_DELAY_MS = 2000;

// How often the live board re-polls its snapshot.
const LIVE_REFRESH_MS = 15000;

// ─── Indicators ──────────────────────────────────────────────────────────────
// Continuous readings shown alongside signals. Neither fires.

const EMA_PERIODS = [20, 50, 100, 200];

// EMA spread on SPOT, as a percentage of close. Ordered WIDEST first, so band 0
// is a trending market and band 4 is extreme convergence. Logarithmic, because
// 0.05% and 0.005% are genuinely different states that a linear scale would
// lump together.
const EMA_SPREAD_BANDS = [
    { label: '>1%',          max: Infinity },
    { label: '1% - 0.1%',    max: 1 },
    { label: '0.1% - 0.01%', max: 0.1 },
    { label: '0.01%-0.001%', max: 0.01 },
    { label: '<0.001%',      max: 0.001 },
];

// Option price volatility: dist / (open x close). Ordered TIGHTEST first, so
// band 0 is the interesting state — premium holding rather than decaying.
//
// These edges are a placeholder. They have not been calibrated against real
// data, so expect to move them once the distribution is visible; the viewer
// reads them from here, so a change needs no re-run.
const VOLATILITY_WINDOWS = [5, 10];
const VOLATILITY_BANDS = [
    { label: 'very low',  max: 0.01 },
    { label: 'low',       max: 0.05 },
    { label: 'moderate',  max: 0.2 },
    { label: 'high',      max: 1 },
    { label: 'very high', max: Infinity },
];

// ─── quality.js breakdown dimensions ─────────────────────────────────────────
// Buckets for --by tte and --by moneyness.
//
// The hypothesis they exist to test: a duration only works within a certain
// window before expiry, and only at a certain distance from the money — e.g. 60m
// candles paying best in the last ~30h at 2-3.5% OTM. Aggregating only by
// duration averages those pockets away.

// Hours remaining when the signal fired. Log-ish spacing, because the action
// concentrates near expiry and equal buckets would put most signals in one.
// Minimum samples before a cross-tab cell is trusted. Below this the cell is
// parenthesised: a 100% hit rate on two samples is noise, but unmarked it reads
// as the strongest pocket in the table.
const QUALITY_MIN_CELL_SAMPLE = 30;

const TTE_BUCKETS = [
    { label: '0-6h',      max: 6 },
    { label: '6-48h',     max: 48 },
    { label: '48-120h',   max: 120 },
    { label: '120-480h',  max: 480 },
    { label: '480h+',     max: Infinity },
];

// Distance from spot, as a percentage. Negative is in the money. Tight bands
// near the money, since that is where the hypothesis is specific.
// Distance from spot, symmetric across the money. Sign convention: positive is
// OUT of the money for calls and puts alike, negative is IN the money.
//
// The innermost ITM and OTM bands are deliberately merged into one ±1.5% bucket.
// Within a percent and a half of spot the ITM/OTM label is close to arbitrary —
// spot crosses back and forth intraday — so splitting there would scatter one
// population across two columns for no informational gain.
//
// `max` values must run ASCENDING for bucketOf(), which returns the first bucket
// the value falls under. That means the ITM entries carry NEGATIVE maxima, which
// reads oddly but is what makes a single ordered scan cover both sides.
const MONEYNESS_BUCKETS = [
    { label: '12.5%+ ITM',   max: -12.5 },
    { label: '9-12.5% ITM',  max: -9 },
    { label: '6-9% ITM',     max: -6 },
    { label: '3.5-6% ITM',   max: -3.5 },
    { label: '1.5-3.5% ITM', max: -1.5 },
    { label: '±1.5%',        max: 1.5 },
    { label: '1.5-3.5% OTM', max: 3.5 },
    { label: '3.5-6% OTM',   max: 6 },
    { label: '6-9% OTM',     max: 9 },
    { label: '9-12.5% OTM',  max: 12.5 },
    { label: '12.5%+ OTM',   max: Infinity },
];

// ─── trades.js ───────────────────────────────────────────────────────────────

// Minimum ratio (high / low) for a trade to qualify. Applied AFTER the recursive
// split, never during it — a window's top-level trade is not necessarily its
// largest, so filtering during recursion would prune branches holding bigger ones.
const TRADE_MIN_RATIO = 5;

// Safety cap on trades found per instrument. Recursive partitioning over ~11,500
// five-minute candles can produce a long tail of small trades; the cap stops a
// pathological instrument dominating the output.
const TRADE_MAX_PER_INSTRUMENT = 200;

// Longest a merged event may span, in candles.
//
// Guards against chained merging: A overlaps B and B overlaps C, but A and C do
// not touch, and unchecked that chain can swallow most of an expiry into one
// event. A merge exceeding this is refused and the trade starts its own event.
// Raise it to allow looser confluence, lower it for tighter grouping.
const TRADE_MAX_MERGE_SPAN_CANDLES = 30;

// ─── Universe max ratio ──────────────────────────────────────────────────────
// A signal fires on ONE instrument, but it is really a statement about the spot:
// premium has stopped falling and a move looks imminent. In practice the signal
// often fires cleanly on a near-the-money or ITM strike while the big multiple
// lands on something further out. Recording only the firing instrument's payoff
// therefore understates what the signal was worth.
//
// So alongside maxSignalRatio (firing instruments only) each merged range also
// records universeMaxRatio: the best payoff available across every ELIGIBLE
// instrument at that moment, whether or not it fired.
//
// ELIGIBILITY has two conditions:
//
//   1. Strike range.
//        'all_same_type' — every call, or every put, at any strike (DEFAULT)
//        'further_otm'   — calls: strike >= firing strike
//                          puts:  strike <= firing strike
//
//      'all_same_type' is the default deliberately. universeMaxRatio exists to
//      answer "how big a move was actually there", not to choose a strike, and
//      any strike restriction can silently truncate that answer — a 100x sitting
//      a couple of strikes the wrong side of the boundary would simply not be
//      counted, making the signal look weaker than it was. Since spot candles are
//      not stored, absolute moneyness cannot be determined anyway, so any boundary
//      would be relative to the firing strike and therefore somewhat arbitrary.
//      Measuring the full same-type chain keeps the data complete; sizing a real
//      target below the observed ceiling is a separate decision made when trading.
//
//      Opposite-type instruments are never eligible: a put signal is a call on the
//      spot falling, so a call going 100x on the same expiry is the wrong direction
//      and would be a meaningless comparison.
//
//      Note that under 'all_same_type' universeMaxRatio is still always
//      >= maxSignalRatio, because the firing instrument remains in the universe.
//
//   2. The instrument must already have a candle at the signal timestamp. New
//      strikes get listed as spot moves, and a strike that did not yet exist
//      when the signal fired was not buyable then. Stored candles have already
//      had their leading 0.1-priced initialisation candles removed by
//      grouper.stripWarmup, so presence in stored data is a sufficient test.
const UNIVERSE_MAX_ENABLED = true;
const UNIVERSE_MAX_MODE    = 'all_same_type';   // 'all_same_type' | 'further_otm'

// ─── Reporting bands and thresholds ──────────────────────────────────────────
// Shared by quality.js and serve_signals.js so both always describe the same
// buckets. Edit here only.

// Cumulative thresholds: "what fraction of signals reached at least Nx".
// Add or remove freely — every percentage column, filter and report follows.
// e.g. add 20 for a 20x column: [5, 10, 20, 50, 100]
const MULTIBAGGER_THRESHOLDS = [5, 10, 50, 100];

// Which threshold the headline "% reached Nx" figures use before you click a
// different column. Must be one of MULTIBAGGER_THRESHOLDS.
const DEFAULT_HEADLINE_THRESHOLD = 10;

// Exclusive payoff bands for the heat matrix. Each covers [min, max).
const RATIO_BANDS = [
    { label: '<2x',    min: 0,   max: 2 },
    { label: '2-5x',   min: 2,   max: 5 },
    { label: '5-10x',  min: 5,   max: 10 },
    { label: '10-50x', min: 10,  max: 50 },
    { label: '50x+',   min: 50,  max: Infinity },
];

// Signal-strength bands, PER SIGNAL.
//
// signalValue means something different in each signal, on wildly different
// scales, so one shared band set cannot serve them:
//
//   red_squeeze      ratio1 + ratio2, observed roughly 50 to 5,757
//   otm_* signals    spot / avgPrice, always above OTM_SIGNAL_THRESHOLD
//                    (10,000) and running into the hundreds of thousands
//
// Using the red_squeeze bands for an OTM signal collapses every row into 1k+,
// which is exactly what happened before this was split: the heat matrix had
// four empty rows and one containing everything, telling you nothing.
const STRENGTH_BANDS_BY_SIGNAL = {
    // ratio1 + ratio2. Median around 95, p90 around 367.
    red_squeeze: [
        { label: '50-75',   min: 0,    max: 75 },
        { label: '75-150',  min: 75,   max: 150 },
        { label: '150-400', min: 150,  max: 400 },
        { label: '400-1k',  min: 400,  max: 1000 },
        { label: '1k+',     min: 1000, max: Infinity },
    ],

    // spot / avgPrice. Labels show the implied option price for BTC near 100k,
    // since "10k-25k" is meaningless on its own but "4-10" is immediately
    // readable. Higher band = cheaper option = the stronger claim.
    otm_red_squeeze: [
        { label: '<25k (~4-10)',   min: 0,      max: 25000 },
        { label: '25-50k (~2-4)',  min: 25000,  max: 50000 },
        { label: '50-100k (~1-2)', min: 50000,  max: 100000 },
        { label: '100-250k (<1)',  min: 100000, max: 250000 },
        { label: '250k+ (<0.4)',   min: 250000, max: Infinity },
    ],
};
// green_stairs scores identically to otm_red_squeeze, so it shares the bands.
STRENGTH_BANDS_BY_SIGNAL.green_stairs = STRENGTH_BANDS_BY_SIGNAL.otm_red_squeeze;

// otm_wall scores a log10 JUMP, so its whole useful range sits just above the
// threshold of 2 — jumps of 10 are almost never seen. Bands are correspondingly
// tight; the wide 2/3/4/6/10 split used elsewhere would put nearly everything
// in one row and show nothing.
STRENGTH_BANDS_BY_SIGNAL.otm_wall = [
    { label: '2-2.5',  min: 0,   max: 2.5 },
    { label: '2.5-3',  min: 2.5, max: 3 },
    { label: '3-4',    min: 3,   max: 4 },
    { label: '4-6',    min: 4,   max: 6 },
    { label: '6+',     min: 6,   max: Infinity },
];

/** Bands for a signal, falling back to red_squeeze's for anything unregistered. */
function strengthBandsFor(signalId) {
    return STRENGTH_BANDS_BY_SIGNAL[signalId] || STRENGTH_BANDS_BY_SIGNAL.red_squeeze;
}

// Back-compat default for callers that predate the per-signal split.
const STRENGTH_BANDS = STRENGTH_BANDS_BY_SIGNAL.red_squeeze;

// Which payoff definition reports use by default:
//   'universe' — universeMaxRatio, the best multiple on any same-type strike.
//                The honest measure of what the move was worth.
//   'fired'    — maxSignalRatio, restricted to instruments that actually fired.
// serve_signals.js can toggle at runtime; quality.js takes --source to override.
const DEFAULT_RATIO_SOURCE = 'universe';   // 'universe' | 'fired'

// ─── Logging ─────────────────────────────────────────────────────────────────

const LOG_BASE_DIR = 'logs';

// Master switches — set false to silence completely
const LOG_ENABLED   = true;
const DEBUG_ENABLED = false;   // more verbose: candle arrays, raw signal objects

// Per-function log switches (only matters if LOG_ENABLED = true)
const LOG_FLAGS = {
    scheduler:       true,
    fetcher:         true,
    grouper:         false,   // very verbose, turn on only when debugging grouping
    red_squeeze:     true,
    signal_writer:   true,
    candle_store:    true,
    quality:         true,
};

module.exports = {
    API_BASE_URL,
    API_KEY,
    API_SECRET,
    API_CALL_DELAY_MS,
    API_MAX_RETRIES,
    API_RETRY_BASE_DELAY_MS,
    API_RATE_LIMIT_BACKOFF_MS,
    MAX_CANDLES_PER_REQUEST,
    PRIOR_DAYS,
    SKIP_INITIAL_CANDLES,
    MAX_CONCURRENT_INSTRUMENT_FETCHES,
    MAX_PAST_EXPIRIES_PER_ITERATION,
    DURATION_TIMES,
    DIRECT_DURATIONS,
    DATA_BASE_DIR,
    INSTRUMENTS_BASE_DIR,
    SIGNALS_BASE_DIR,
    PAST_COMPLETE_MARKERS_DIR,
    CANDLES_BASE_DIR,
    SPOT_CANDLES_BASE_DIR,
    SPOT_MARKERS_BASE_DIR,
    SPOT_HISTORY_DAYS,
    SPOT_REFETCH_OVERLAP_MINUTES,
    CANDLES_COMPLETE_MARKERS_DIR,
    SIGNALS_COMPLETE_MARKERS_DIR,
    RED_SQUEEZE_MIN_SEQ_LENGTH,
    RED_SQUEEZE_THRESHOLD,
    RED_SQUEEZE_MINIMUM_TICK,
    RED_SQUEEZE_SL_FACTOR,
    OTM_SIGNAL_THRESHOLD,
    WALL_LOOKBACK_CANDLES,
    WALL_JUMP_THRESHOLD,
    WALL_CLOSE_MULTIPLE,
    OTM_MIN_SEQ_LENGTH,
    OTM_SL_FACTOR,
    GREEN_STAIRS_MAX_EQUAL_STEPS,
    LIVE_SIGNAL_WINDOW_HOURS,
    LIVE_MAX_SIGNALS,
    LIVE_SERIES_POINTS,
    LIVE_LOOP_DELAY_MS,
    LIVE_REFRESH_MS,
    EMA_PERIODS,
    EMA_SPREAD_BANDS,
    VOLATILITY_WINDOWS,
    VOLATILITY_BANDS,
    QUALITY_MIN_CELL_SAMPLE,
    TTE_BUCKETS,
    MONEYNESS_BUCKETS,
    TRADE_MIN_RATIO,
    TRADE_MAX_PER_INSTRUMENT,
    TRADE_MAX_MERGE_SPAN_CANDLES,
    UNIVERSE_MAX_ENABLED,
    UNIVERSE_MAX_MODE,
    MULTIBAGGER_THRESHOLDS,
    DEFAULT_HEADLINE_THRESHOLD,
    RATIO_BANDS,
    STRENGTH_BANDS,
    STRENGTH_BANDS_BY_SIGNAL,
    strengthBandsFor,
    DEFAULT_RATIO_SOURCE,
    LOG_BASE_DIR,
    LOG_ENABLED,
    DEBUG_ENABLED,
    LOG_FLAGS,
};
