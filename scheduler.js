// scheduler.js
// ─────────────────────────────────────────────────────────────────────────────
// Expiry priority scheduler.
// Direct port of the fetchNextExpiry / updateWeights / updateExpirySpots
// logic from the original fetch_option_candles.js.
//
// Nearer expiries accumulate weight faster (weight += 1/ceil(daysToExpiry))
// and therefore get processed more frequently than farther ones.
//
// Usage:
//   const sched = new Scheduler(spots);
//   while (true) {
//     const { spot, expiryDate, isPast } = sched.next();
//     // ... process ...
//     sched.markProcessed(spot, expiryDate);
//   }
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const logger      = require('./logger');
const instruments = require('./instruments');
const api         = require('./api');
const expiryMod   = require('./expiry');

const SECONDS_24H = 24 * 3600;

// Settlement time is per-spot (BTC/ETH differ from XAUT), so every expiry
// comparison must be made against that spot's own settlement instant.
function expiryTs(spot, expiryDate) {
    return expiryMod.expiryUnix(spot, expiryDate);
}

class Scheduler {
    constructor() {
        // expirySpots: array of [expiryDate, spots[], weight]
        // Same structure as original fetch_option_candles.js expirySpots
        this._expirySpots = [];
        this._rebuild();
    }

    // ── Rebuild expiry-spot list from disk ─────────────────────────────────────

    _rebuild() {
        const spots = instruments.getSpots();
        const now   = Math.floor(Date.now() / 1000);

        for (const spot of spots) {
            const expiries       = instruments.getExpiries(spot);
            const futureExpiries = expiries.filter(e => expiryTs(spot, e) > now);

            for (const expiryDate of futureExpiries) {
                let entry = this._expirySpots.find(e => e[0] === expiryDate);
                if (!entry) {
                    entry = [expiryDate, [], 0];
                    this._expirySpots.push(entry);
                }
                if (!entry[1].includes(spot)) entry[1].push(spot);
            }
        }

        // Drop entries whose every spot has now settled. An entry is kept while
        // at least one of its spots is still live, because two spots sharing an
        // expiry DATE can settle at different times of day.
        this._expirySpots = this._expirySpots.filter(
            e => e[1].some(spot => expiryTs(spot, e[0]) > now)
        );

        logger.log('scheduler', `Scheduler rebuilt: ${this._expirySpots.length} future expiries`);
    }

    // ── Update weights ────────────────────────────────────────────────────────

    _updateWeights() {
        const now = Math.floor(Date.now() / 1000);
        for (let i = 0; i < this._expirySpots.length; i++) {
            const [expiryDate, spots] = this._expirySpots[i];
            // Spots sharing an expiry date may settle hours apart. Weight by the
            // soonest-settling spot so the most urgent one sets the priority.
            const soonestTs = Math.min(...spots.map(sp => expiryTs(sp, expiryDate)));
            const tte = soonestTs - now;
            if (i === 0) {
                this._expirySpots[i][2] = 0;
            } else {
                const daysLeft = Math.ceil(tte / SECONDS_24H);
                this._expirySpots[i][2] += daysLeft > 0 ? 1 / daysLeft : 0;
            }
        }
    }

    // ── Check if spot list changed ────────────────────────────────────────────

    _needsRebuild() {
        const spots = instruments.getSpots();
        const now   = Math.floor(Date.now() / 1000);

        const actual = [];
        for (const spot of spots) {
            for (const exp of instruments.getExpiries(spot)) {
                if (expiryTs(spot, exp) > now) actual.push(`${spot}_${exp}`);
            }
        }
        actual.sort();

        const existing = [];
        for (const entry of this._expirySpots) {
            for (const spot of entry[1]) existing.push(`${spot}_${entry[0]}`);
        }
        existing.sort();

        return actual.join(',') !== existing.join(',');
    }

    // ── Public: get next expiry to process ────────────────────────────────────

    /**
     * Returns the highest-weight (soonest) expiry and its associated spots.
     * Also returns all past expiries that have not yet been fully processed.
     *
     * @returns {{ future: {expiryDate, spots}|null, past: {expiryDate, spots}[] }}
     */
    next() {
        if (this._needsRebuild()) this._rebuild();
        this._updateWeights();

        // Sort descending by weight — highest weight = process next
        this._expirySpots.sort((a, b) => b[2] - a[2]);

        const future = this._expirySpots.length > 0
            ? { expiryDate: this._expirySpots[0][0], spots: this._expirySpots[0][1] }
            : null;

        // Past expiries: all spots × all past expiries (for past signal generation)
        const spots   = instruments.getSpots();
        const pastMap = {};
        const now     = Math.floor(Date.now() / 1000);

        for (const spot of spots) {
            for (const exp of instruments.getExpiries(spot)) {
                if (expiryTs(spot, exp) <= now) {
                    if (!pastMap[exp]) pastMap[exp] = [];
                    pastMap[exp].push(spot);
                }
            }
        }

        const past = Object.entries(pastMap)
            .sort(([a], [b]) => a < b ? -1 : 1)
            .map(([expiryDate, s]) => ({ expiryDate, spots: s }));

        if (future) {
            logger.log('scheduler',
                `Next future expiry: ${future.expiryDate} spots=[${future.spots.join(',')}]`);
        }
        logger.log('scheduler', `Past expiries to check: ${past.length}`);

        return { future, past };
    }
}

module.exports = Scheduler;
