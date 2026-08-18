// main.js — RETIRED
// ─────────────────────────────────────────────────────────────────────────────
// Superseded by live_runner.js.
//
// This file used to process live expiries and write signal files. live_runner.js
// now does that AND computes the two indicators, from the same single fetch.
// Running both meant fetching identical live candles twice and running every
// signal twice for one set of results.
//
// Left in place as a pointer rather than deleted, so an existing alias, cron
// entry or service unit fails loudly with instructions instead of a confusing
// module-not-found.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

console.error(`
main.js has been retired — use live_runner.js instead.

  node live_runner.js      live expiries: signals + indicators, one fetch
  node serve_live.js       live board          (default :3200)

live_runner.js writes both:
  data/signals/{id}/{spot}/{dur}/{expiry}.json   what main.js produced, so
                                                 serve_signals still sees live
  data/live/{spot}/{expiry}.json                 the live snapshot

Historical work is unchanged:
  node backfill.js --spot-candles --from 2024-01-01
  node backfill.js --from 2025-01-01 --to 2025-12-31 --candles-only
  node backfill.js --from 2025-01-01 --to 2025-12-31 --signals-only --force-signals
  node serve_signals.js --signal otm_wall        (default :3100)
`);

process.exit(1);
