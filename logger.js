// logger.js
// ─────────────────────────────────────────────────────────────────────────────
// One log directory per program execution, mirroring signal directory structure.
// Each function writes to its own file within that directory.
// Debug output (candles, raw signals) goes to a separate .debug file.
//
// Log directory: logs/{YYYY-MM-DDTHH-MM-SS}/
//   scheduler.log
//   fetcher.log
//   grouper.log
//   red_squeeze.log
//   signal_writer.log
//   quality.log
//   *.debug  (same names, .debug extension, only written when DEBUG_ENABLED)
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs  = require('fs');
const path = require('path');
const cfg = require('./config');

// ─── Session directory ────────────────────────────────────────────────────────

// Created once when logger.js is first required. All writes go here.
//
// The directory name includes a worker label (from WORKER_LABEL env var, set by
// backfill.js) and the PID. Without these, two processes started in the same
// second would share a log directory and interleave their output, which makes
// parallel backfill logs unreadable.
function makeSessionDir() {
    const now  = new Date();
    const pad  = n => String(n).padStart(2, '0');
    const stamp = `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())}` +
                  `T${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;

    const label = process.env.WORKER_LABEL
        ? `_${String(process.env.WORKER_LABEL).replace(/[^A-Za-z0-9._-]/g, '-')}`
        : '';

    const dir = path.join(cfg.LOG_BASE_DIR, `${stamp}${label}_pid${process.pid}`);
    fs.mkdirSync(dir, { recursive: true });
    return dir;
}

const SESSION_DIR = cfg.LOG_ENABLED ? makeSessionDir() : null;

// ─── File handle cache ────────────────────────────────────────────────────────

const _handles = {};

function _getHandle(functionName, ext = 'log') {
    const key = `${functionName}.${ext}`;
    if (!_handles[key]) {
        const filePath = path.join(SESSION_DIR, key);
        _handles[key] = fs.openSync(filePath, 'a');
    }
    return _handles[key];
}

// ─── Core write ───────────────────────────────────────────────────────────────

function _write(functionName, level, message, ext = 'log') {
    if (!cfg.LOG_ENABLED || !SESSION_DIR) return;
    if (!cfg.LOG_FLAGS[functionName]) return;

    const ts   = new Date().toISOString();
    const line = `${ts} [${level.padEnd(5)}] ${message}\n`;

    try {
        fs.writeSync(_getHandle(functionName, ext), line);
    } catch (err) {
        // Silent — never let logging break the main process
    }
}

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Standard log entry. Always written when LOG_FLAGS[functionName] is true.
 * @param {string} functionName  — matches a key in LOG_FLAGS
 * @param {string} message
 */
function log(functionName, message) {
    _write(functionName, 'LOG', message, 'log');
    if (cfg.DEBUG_ENABLED) {
        // Also echo to console when debugging
        console.log(`[${functionName}] ${message}`);
    }
}

/**
 * Debug entry — written only when DEBUG_ENABLED is true.
 * Use for verbose data: candle arrays, raw signal objects, etc.
 * Goes to a separate .debug file so normal logs stay readable.
 * @param {string} functionName
 * @param {string} message
 * @param {*}      data         — optional, JSON-serialised if provided
 */
function debug(functionName, message, data = undefined) {
    if (!cfg.DEBUG_ENABLED) return;
    const payload = data !== undefined
        ? `${message}\n${JSON.stringify(data, null, 2)}`
        : message;
    _write(functionName, 'DEBUG', payload, 'debug');
}

/**
 * Error entry — always written regardless of LOG_FLAGS.
 * Goes to the same .log file as normal entries.
 */
function error(functionName, message, err = undefined) {
    if (!cfg.LOG_ENABLED || !SESSION_DIR) return;
    const detail = err ? ` | ${err.message || err}` : '';
    _write(functionName, 'ERROR', message + detail, 'log');
    console.error(`[${functionName}] ERROR: ${message}${detail}`);
}

/**
 * Returns the session log directory path (useful for printing at startup).
 */
function sessionDir() {
    return SESSION_DIR;
}

module.exports = { log, debug, error, sessionDir };
