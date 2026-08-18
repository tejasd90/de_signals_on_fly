// instruments.js
// ─────────────────────────────────────────────────────────────────────────────
// Load, store and query instrument (option contract) lists.
// Mirrors the original fetch_instruments.js + utils.loadInstruments pattern.
// Instruments are stored on disk per (spot, expiryDate) and read at startup.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs     = require('fs');
const path   = require('path');
const cfg    = require('./config');
const logger = require('./logger');
const api    = require('./api');
const expiryMod = require('./expiry');

// ─── Fetch and store ──────────────────────────────────────────────────────────

/**
 * Fetch all option products from Delta Exchange and write them to disk.
 * Matches the original fetch_instruments.js grouping:
 *   instruments/{spot}/{expiryDate}.json → { symbol: productId, ... }
 *
 * @param {'live'|'expired'} state
 */
async function fetchAndStoreInstruments(state = 'live') {
    logger.log('scheduler', `fetchAndStoreInstruments state=${state}`);
    const products = await api.fetchProducts(state);

    const grouped = {};
    for (const p of products) {
        const spot   = p.underlying_asset?.symbol;
        const expiry = p.settlement_time?.substring(0, 10);
        if (!spot || !expiry) continue;

        // Record the exchange's own settlement time for this (spot, expiry).
        // This is what makes differing settlement schedules (BTC/ETH vs XAUT)
        // work without any per-spot code. expiry.js prefers these values over
        // its config fallbacks.
        expiryMod.recordSettlementTime(spot, expiry, p.settlement_time);
        const key = `${spot}/${expiry}`;
        if (!grouped[key]) grouped[key] = {};
        if (p.symbol && p.symbol !== '-') {
            grouped[key][p.symbol] = p.id;
        }
    }

    for (const [key, instruments] of Object.entries(grouped)) {
        const [spot, expiry] = key.split('/');
        const dir  = path.join(cfg.INSTRUMENTS_BASE_DIR, spot);
        const file = path.join(dir, `${expiry}.json`);
        fs.mkdirSync(dir, { recursive: true });

        // Merge with existing (new strikes may appear)
        let existing = {};
        if (fs.existsSync(file)) {
            try { existing = JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) {}
        }
        fs.writeFileSync(file, JSON.stringify({ ...existing, ...instruments }));
    }

    logger.log('scheduler', `fetchAndStoreInstruments done: ${products.length} products`);
}

// ─── Read from disk ───────────────────────────────────────────────────────────

/**
 * Load instruments for a (spot, expiryDate) pair.
 * Returns { symbol: productId, ... } or {} if not found.
 */
function loadInstruments(spot, expiryDate) {
    const file = path.join(cfg.INSTRUMENTS_BASE_DIR, spot, `${expiryDate}.json`);
    if (!fs.existsSync(file)) return {};
    try {
        return JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (err) {
        logger.error('scheduler', `loadInstruments failed for ${spot}/${expiryDate}`, err);
        return {};
    }
}

/**
 * Get all known spot names (subdirectories of INSTRUMENTS_BASE_DIR).
 */
function getSpots() {
    if (!fs.existsSync(cfg.INSTRUMENTS_BASE_DIR)) return [];
    return fs.readdirSync(cfg.INSTRUMENTS_BASE_DIR)
        .filter(d => !d.startsWith('.') &&
                     fs.statSync(path.join(cfg.INSTRUMENTS_BASE_DIR, d)).isDirectory());
}

/**
 * Get all expiry dates for a spot, sorted ascending.
 */
function getExpiries(spot) {
    const dir = path.join(cfg.INSTRUMENTS_BASE_DIR, spot);
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
        .filter(f => !f.startsWith('.') && f.endsWith('.json'))
        .map(f => f.replace('.json', ''))
        .sort();
}

/**
 * Parse a symbol string into its components.
 * Format: {type}-{spot}-{strike}-{expiryCode}
 * e.g. 'C-BTC-92400-271125' → { type:'C', spot:'BTC', strike:92400, expiryCode:'271125' }
 */
function parseSymbol(symbol) {
    const parts = symbol.split('-');
    return {
        type:       parts[0],          // 'C' or 'P'
        spot:       parts[1],
        strike:     parseFloat(parts[2]),
        expiryCode: parts[3],
    };
}

module.exports = {
    fetchAndStoreInstruments,
    loadInstruments,
    getSpots,
    getExpiries,
    parseSymbol,
};
